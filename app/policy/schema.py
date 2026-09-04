"""The constrained policy language.

A policy is **data**, never code. This module is the allowlist: fields,
operators, value types, thresholds, actions, and action parameters. Anything a
model proposes that is not expressible here fails validation and can never be
activated.

There is no `eval`, no generated Python, no SQL, no shell, and no
natural-language condition anywhere in this file or in the engine that reads it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.config import MAX_MISSING_COMPONENTS_CEILING, MAX_REPLACEMENT_COST_CEILING_USD

POLICY_FAMILY = "returns.missing_accessory"

# --------------------------------------------------------------------- fields

BOOL_FIELDS: frozenset[str] = frozenset(
    {
        "missing_component_serialized",
        "missing_component_safety_critical",
        "missing_component_essential",
        "serial_match",
        "new_damage_present",
        "evidence_complete",
    }
)

NUMBER_FIELDS: frozenset[str] = frozenset(
    {
        "missing_component_count",
        "replacement_cost_usd",
    }
)

ENUM_FIELDS: dict[str, frozenset[str]] = {
    "kit_category": frozenset({"camera_kit", "lens_kit", "audio_kit", "drone_kit"}),
}

ALLOWED_FIELDS: frozenset[str] = BOOL_FIELDS | NUMBER_FIELDS | frozenset(ENUM_FIELDS)

# Outer walls. A proposal may be *tighter* than these. It may never be looser.
NUMERIC_CEILINGS: dict[str, float] = {
    "replacement_cost_usd": MAX_REPLACEMENT_COST_CEILING_USD,
    "missing_component_count": float(MAX_MISSING_COMPONENTS_CEILING),
}


class Operator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    IN = "in"
    NOT_IN = "not_in"


BOOL_OPERATORS = frozenset({Operator.EQ, Operator.NEQ})
NUMBER_OPERATORS = frozenset({Operator.EQ, Operator.NEQ, Operator.LT, Operator.LTE, Operator.GT, Operator.GTE})
ENUM_OPERATORS = frozenset({Operator.EQ, Operator.NEQ, Operator.IN, Operator.NOT_IN})

ConditionValue = Union[bool, int, float, str, list[str]]


class Condition(BaseModel):
    """One allowlisted comparison against one allowlisted fact field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(description="Fact field to test. Must be on the allowlist.")
    operator: Operator = Field(description="Comparison operator. Must be on the allowlist.")
    value: ConditionValue = Field(description="Literal value to compare against.")

    @field_validator("field")
    @classmethod
    def _field_allowlisted(cls, v: str) -> str:
        if v not in ALLOWED_FIELDS:
            raise ValueError(
                f"field '{v}' is not allowlisted; allowed: {sorted(ALLOWED_FIELDS)}"
            )
        return v

    @model_validator(mode="after")
    def _check_operator_and_value(self) -> "Condition":
        field, op, value = self.field, self.operator, self.value

        if field in BOOL_FIELDS:
            if op not in BOOL_OPERATORS:
                raise ValueError(f"operator '{op}' not allowed on boolean field '{field}'")
            if not isinstance(value, bool):
                raise ValueError(f"field '{field}' requires a boolean value, got {type(value).__name__}")
            return self

        if field in NUMBER_FIELDS:
            if op not in NUMBER_OPERATORS:
                raise ValueError(f"operator '{op}' not allowed on numeric field '{field}'")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"field '{field}' requires a numeric value")
            if value < 0:
                raise ValueError(f"field '{field}' may not be compared against a negative value")
            ceiling = NUMERIC_CEILINGS.get(field)
            if ceiling is not None and op in {Operator.LT, Operator.LTE, Operator.EQ} and float(value) > ceiling:
                raise ValueError(
                    f"field '{field}' threshold {value} exceeds the hard ceiling {ceiling}"
                )
            return self

        allowed_values = ENUM_FIELDS[field]
        if op not in ENUM_OPERATORS:
            raise ValueError(f"operator '{op}' not allowed on enum field '{field}'")
        candidates = value if isinstance(value, list) else [value]
        if op in {Operator.IN, Operator.NOT_IN} and not isinstance(value, list):
            raise ValueError(f"operator '{op}' requires a list value")
        if op in {Operator.EQ, Operator.NEQ} and isinstance(value, list):
            raise ValueError(f"operator '{op}' requires a single value")
        for candidate in candidates:
            if not isinstance(candidate, str) or candidate not in allowed_values:
                raise ValueError(
                    f"value '{candidate}' is not an allowed value for '{field}'; "
                    f"allowed: {sorted(allowed_values)}"
                )
        return self

    def describe(self) -> str:
        symbol = {
            Operator.EQ: "is",
            Operator.NEQ: "is not",
            Operator.LT: "<",
            Operator.LTE: "<=",
            Operator.GT: ">",
            Operator.GTE: ">=",
            Operator.IN: "in",
            Operator.NOT_IN: "not in",
        }[self.operator]
        return f"{self.field} {symbol} {self.value}"


# -------------------------------------------------------------------- actions


class SetDispositionAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["set_disposition"] = "set_disposition"
    disposition: Literal["PARTS_HOLD"] = Field(
        description="Only PARTS_HOLD may be set by policy. Everything else is a human action."
    )


class CreateWorkOrderAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["create_work_order"] = "create_work_order"
    work_order_type: Literal["REPLACEMENT_PARTS"] = Field(
        description="Only replacement-parts work orders may be created by policy."
    )
    max_cost_usd: float = Field(
        gt=0,
        le=MAX_REPLACEMENT_COST_CEILING_USD,
        description="Per-action spend cap. Enforced again at execution time.",
    )


class CloseExceptionAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["close_exception"] = "close_exception"
    resolution_code: Literal["RESOLVED_PARTS_REPLACEMENT"] = "RESOLVED_PARTS_REPLACEMENT"


PolicyAction = Annotated[
    Union[SetDispositionAction, CreateWorkOrderAction, CloseExceptionAction],
    Field(discriminator="type"),
]

REQUIRED_ACTION_TYPES = ("set_disposition", "create_work_order", "close_exception")


# ------------------------------------------------------------------- policies


class PolicyDefinition(BaseModel):
    """A complete, activatable policy. Purely declarative."""

    model_config = ConfigDict(extra="forbid")

    family: Literal["returns.missing_accessory"] = POLICY_FAMILY
    name: str = Field(min_length=4, max_length=120)
    description: str = Field(max_length=600)
    conditions: list[Condition] = Field(min_length=1, max_length=12)
    actions: list[PolicyAction] = Field(min_length=1, max_length=4)
    min_confidence: float = Field(default=0.75, ge=0.5, le=1.0)

    @model_validator(mode="after")
    def _check_actions(self) -> "PolicyDefinition":
        types = [a.type for a in self.actions]
        if len(types) != len(set(types)):
            raise ValueError("duplicate action types in policy")
        for required in REQUIRED_ACTION_TYPES:
            if required not in types:
                raise ValueError(
                    f"policy must include the '{required}' action; "
                    "a policy that acts must also dispose and close"
                )
        fields = [c.field for c in self.conditions]
        if len(fields) != len(set(fields)):
            raise ValueError("a policy may test each field at most once")
        return self

    @model_validator(mode="after")
    def _check_cost_cap_consistency(self) -> "PolicyDefinition":
        """A spend cap must be backed by a matching cost condition."""
        wo = next((a for a in self.actions if a.type == "create_work_order"), None)
        if wo is None:
            return self
        cost_conditions = [
            c
            for c in self.conditions
            if c.field == "replacement_cost_usd" and c.operator in {Operator.LT, Operator.LTE}
        ]
        if not cost_conditions:
            raise ValueError(
                "a policy that creates a work order must bound replacement_cost_usd "
                "with an lt/lte condition"
            )
        bound = min(float(c.value) for c in cost_conditions)  # type: ignore[arg-type]
        if wo.max_cost_usd > bound:
            raise ValueError(
                f"work order max_cost_usd {wo.max_cost_usd} exceeds the policy's own "
                f"cost condition bound {bound}"
            )
        return self

    def condition_summary(self) -> list[str]:
        return [c.describe() for c in self.conditions]

    def action_summary(self) -> list[str]:
        out = []
        for a in self.actions:
            if a.type == "set_disposition":
                out.append(f"set disposition to {a.disposition}")
            elif a.type == "create_work_order":
                out.append(f"create {a.work_order_type} work order (cap ${a.max_cost_usd:.2f})")
            else:
                out.append(f"close exception as {a.resolution_code}")
        return out


class PolicyValidationError(Exception):
    """Raised when a proposal cannot be expressed in the constrained language."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


def validate_policy_payload(payload: dict) -> PolicyDefinition:
    """Parse and validate an untrusted policy payload. Never executes anything."""
    try:
        return PolicyDefinition.model_validate(payload)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ]
        raise PolicyValidationError("policy failed schema validation", errors) from exc
