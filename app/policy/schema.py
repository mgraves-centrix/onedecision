"""The constrained policy language.

A policy is **data**, never code. This module is the allowlist: fields,
operators, value types, thresholds, actions, and action parameters. Anything a
model proposes that is not expressible here fails validation and can never be
activated.

The allowlist itself belongs to a domain (`app/domains/`), because what a policy
may test and do depends on what kind of exception it governs. This module holds
the rules that are true of every domain: a condition may only name an allowlisted
field, compare it with an operator its type permits, and stay inside the hard
ceiling; a policy must carry its domain's full action set, each action's
parameters pinned to their allowlist, and any spend cap backed by a condition
that bounds it.

There is no `eval`, no generated Python, no SQL, no shell, and no
natural-language condition anywhere in this file or in the engine that reads it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app import domains

# The domain this product shipped with, and the default family for a proposal.
POLICY_FAMILY = "returns.missing_accessory"


def spec_for(family: str) -> domains.DomainSpec:
    """The domain that owns this family, loading the packs on first use."""
    try:
        return domains.get(family)
    except KeyError:
        domains.load()
        return domains.get(family)


def _field_kind(name: str) -> tuple[str, domains.DomainSpec] | tuple[None, None]:
    """Which domain allowlists this field, and as what type."""
    domains.load()
    for spec in domains.all_specs():
        if name in spec.bool_fields:
            return "bool", spec
        if name in spec.number_fields:
            return "number", spec
        if name in spec.enum_fields:
            return "enum", spec
    return None, None


def allowed_fields() -> frozenset[str]:
    """Every field any registered domain allows a policy to test."""
    domains.load()
    out: frozenset[str] = frozenset()
    for spec in domains.all_specs():
        out |= spec.allowed_fields
    return out


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
        kind, _ = _field_kind(v)
        if kind is None:
            raise ValueError(
                f"field '{v}' is not allowlisted; allowed: {sorted(allowed_fields())}"
            )
        return v

    @model_validator(mode="after")
    def _check_operator_and_value(self) -> "Condition":
        field, op, value = self.field, self.operator, self.value
        kind, spec = _field_kind(field)

        if kind == "bool":
            if op not in BOOL_OPERATORS:
                raise ValueError(f"operator '{op}' not allowed on boolean field '{field}'")
            if not isinstance(value, bool):
                raise ValueError(f"field '{field}' requires a boolean value, got {type(value).__name__}")
            return self

        if kind == "number":
            if op not in NUMBER_OPERATORS:
                raise ValueError(f"operator '{op}' not allowed on numeric field '{field}'")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"field '{field}' requires a numeric value")
            if value < 0:
                raise ValueError(f"field '{field}' may not be compared against a negative value")
            ceiling = spec.numeric_ceilings.get(field) if spec else None
            if ceiling is not None and op in {Operator.LT, Operator.LTE, Operator.EQ} and float(value) > ceiling:
                raise ValueError(
                    f"field '{field}' threshold {value} exceeds the hard ceiling {ceiling}"
                )
            return self

        allowed_values = spec.enum_fields[field] if spec else frozenset()
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


class PolicyAction(BaseModel):
    """One action from a domain's fixed set, with its parameters.

    The parameters are open here and pinned by the domain's `ActionSpec` in
    `PolicyDefinition`: a model cannot invent an action type, a parameter, or a
    value, because each is checked against the spec that owns it.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    type: str

    def params(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class PolicyValidationError(Exception):
    """Raised when a proposal cannot be expressed in the constrained language."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


# ------------------------------------------------------------------- policies


class PolicyDefinition(BaseModel):
    """A complete, activatable policy. Purely declarative."""

    model_config = ConfigDict(extra="forbid")

    family: str = POLICY_FAMILY
    name: str = Field(min_length=4, max_length=120)
    description: str = Field(max_length=600)
    conditions: list[Condition] = Field(min_length=1, max_length=12)
    actions: list[PolicyAction] = Field(min_length=1, max_length=4)
    min_confidence: float = Field(default=0.75, ge=0.5, le=1.0)

    @field_validator("family")
    @classmethod
    def _family_registered(cls, v: str) -> str:
        spec_for(v)  # raises KeyError with the registered families if unknown
        return v

    @property
    def spec(self) -> domains.DomainSpec:
        return spec_for(self.family)

    @model_validator(mode="after")
    def _check_conditions(self) -> "PolicyDefinition":
        spec = self.spec
        fields = [c.field for c in self.conditions]
        if len(fields) != len(set(fields)):
            raise ValueError("a policy may test each field at most once")
        for name in fields:
            if name not in spec.allowed_fields:
                raise ValueError(
                    f"field '{name}' does not belong to family '{self.family}'; "
                    f"allowed: {sorted(spec.allowed_fields)}"
                )
        return self

    @model_validator(mode="after")
    def _check_actions(self) -> "PolicyDefinition":
        spec = self.spec
        types = [a.type for a in self.actions]
        if len(types) != len(set(types)):
            raise ValueError("duplicate action types in policy")

        for action in self.actions:
            action_spec = spec.action(action.type)
            if action_spec is None:
                raise ValueError(
                    f"action '{action.type}' is not an action of family '{self.family}'; "
                    f"allowed: {[a.type for a in spec.actions]}"
                )
            params = action.params()
            expected = set(action_spec.literals) | set(action_spec.caps)
            unknown = sorted(set(params) - expected)
            if unknown:
                raise ValueError(
                    f"action '{action.type}' has parameters that are not on its allowlist: {unknown}"
                )
            for param, allowed in action_spec.literals.items():
                if param not in params:
                    raise ValueError(f"action '{action.type}' requires '{param}'")
                if params[param] not in allowed:
                    raise ValueError(
                        f"action '{action.type}' parameter '{param}' must be one of "
                        f"{list(allowed)}, got '{params[param]}'"
                    )
            for param, ceiling in action_spec.caps.items():
                if param not in params:
                    raise ValueError(f"action '{action.type}' requires '{param}'")
                value = params[param]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"action '{action.type}' parameter '{param}' must be a number")
                if value <= 0:
                    raise ValueError(f"action '{action.type}' parameter '{param}' must be greater than zero")
                if float(value) > ceiling:
                    raise ValueError(
                        f"action '{action.type}' parameter '{param}' {value} exceeds the hard "
                        f"ceiling {ceiling}"
                    )

        for required in spec.required_action_types:
            if required not in types:
                raise ValueError(
                    f"policy must include the '{required}' action; "
                    "a policy that acts must also complete and close the case"
                )
        return self

    @model_validator(mode="after")
    def _check_cap_is_backed_by_a_condition(self) -> "PolicyDefinition":
        """A cap must be backed by a condition that bounds the same fact."""
        spec = self.spec
        for action in self.actions:
            action_spec = spec.action(action.type)
            if action_spec is None or not action_spec.bound_by:
                continue
            param, bound_field = action_spec.bound_by
            cap = action.params().get(param)
            if cap is None:
                continue
            bounding = [
                c
                for c in self.conditions
                if c.field == bound_field and c.operator in {Operator.LT, Operator.LTE}
            ]
            if not bounding:
                raise ValueError(
                    f"a policy with '{action.type}' must bound {bound_field} with an lt/lte condition"
                )
            bound = min(float(c.value) for c in bounding)  # type: ignore[arg-type]
            if float(cap) > bound:
                raise ValueError(
                    f"action '{action.type}' {param} {cap} exceeds the policy's own "
                    f"{bound_field} bound {bound}"
                )
        return self

    def spend_cap(self) -> float:
        """The most this policy may authorize on one capped action."""
        return self.spec.cap_of(list(self.actions))

    def enum_restriction(self, field_name: str) -> str | None:
        """The single value this policy is limited to on an enum field, if any."""
        for condition in self.conditions:
            if condition.field == field_name and condition.operator == Operator.EQ:
                return str(condition.value)
        return None

    def kit_category_restriction(self) -> str | None:
        """The kit category this policy is limited to, if any (returns domain)."""
        return self.enum_restriction("kit_category")

    def condition_summary(self) -> list[str]:
        return [c.describe() for c in self.conditions]

    def action_summary(self) -> list[str]:
        spec = self.spec
        out = []
        for action in self.actions:
            action_spec = spec.action(action.type)
            out.append(
                action_spec.describe(action.params()) if action_spec else action.type
            )
        return out


def __getattr__(name: str):
    """`ALLOWED_FIELDS` used to be a module constant, before fields belonged to a
    domain. It is computed on access now, so importing this module stays free of
    side effects and the name keeps meaning what it always did: every field any
    domain will let a policy test."""
    if name == "ALLOWED_FIELDS":
        return allowed_fields()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def validate_policy_payload(payload: dict) -> PolicyDefinition:
    """Parse and validate an untrusted policy payload. Never executes anything."""
    try:
        return PolicyDefinition.model_validate(payload)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ]
        raise PolicyValidationError("policy failed schema validation", errors) from exc
