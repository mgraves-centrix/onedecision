"""Core domain types.

`CaseFacts` is the single normalised view of a return case. It is derived
**deterministically from the synthetic adapters**, never from model output.
The agent's `InvestigationReport` is reconciled against it; a disagreement is
an escalation, not a tie-break.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExceptionStatus(StrEnum):
    NEW = "new"
    INVESTIGATING = "investigating"
    WAITING_DECISION = "waiting_decision"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class PolicyStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"
    REJECTED = "rejected"


class Outcome(StrEnum):
    """The three terminal outcomes the evaluation harness scores."""

    AUTO_RESOLVED = "auto_resolved"
    ESCALATED = "escalated"
    DECISION_REQUESTED = "decision_requested"


class MissingComponent(BaseModel):
    model_config = ConfigDict(frozen=True)

    component_id: str
    name: str
    serialized: bool
    safety_critical: bool
    essential: bool
    replacement_cost_usd: float | None = None
    stock_status: str = "unknown"


class CaseFacts(BaseModel):
    """Deterministically derived, allowlist-typed facts about one return case.

    Field names here are exactly the field names a policy is allowed to test.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    sku: str
    kit_category: str

    missing_component_count: int = Field(ge=0)
    missing_component_serialized: bool
    missing_component_safety_critical: bool
    missing_component_essential: bool

    serial_match: bool
    replacement_cost_usd: float | None
    new_damage_present: bool
    evidence_complete: bool

    # Not policy-testable. Carried for the decision card and the audit trail.
    missing_components: tuple[MissingComponent, ...] = ()
    unexpected_components: tuple[str, ...] = ()
    missing_evidence_fields: tuple[str, ...] = ()
    expected_serial: str = ""
    received_serial: str | None = None
    tool_failures: tuple[str, ...] = ()

    def policy_view(self) -> dict[str, object]:
        """The subset a policy engine may read. Nothing else is visible to it."""
        return {
            "missing_component_count": self.missing_component_count,
            "missing_component_serialized": self.missing_component_serialized,
            "missing_component_safety_critical": self.missing_component_safety_critical,
            "missing_component_essential": self.missing_component_essential,
            "serial_match": self.serial_match,
            "replacement_cost_usd": self.replacement_cost_usd,
            "new_damage_present": self.new_damage_present,
            "evidence_complete": self.evidence_complete,
            "kit_category": self.kit_category,
        }


# ------------------------------------------------------------------ agent I/O
# These are the typed structured outputs the Strands agent must produce.


class EvidenceItem(BaseModel):
    label: str = Field(description="Short human-readable label for this piece of evidence.")
    value: str = Field(description="The observed value, stated plainly.")
    source_tool: str = Field(description="Which tool produced this observation.")


class InvestigationReport(BaseModel):
    """What the agent believes after gathering evidence. Advisory only."""

    case_id: str
    evidence: list[EvidenceItem] = Field(
        default_factory=list, description="Concrete observations gathered via tools."
    )
    observed_missing_component_count: int = Field(
        ge=0, description="How many kit components the agent believes are missing."
    )
    observed_serial_match: bool = Field(
        description="Whether the agent believes the received serial matches the expected serial."
    )
    observed_new_damage: bool = Field(description="Whether the agent observed new damage.")
    observed_evidence_complete: bool = Field(
        description="Whether every required inspection evidence field was present."
    )
    observed_replacement_cost_usd: float | None = Field(
        default=None, description="Replacement cost the agent read from the parts catalogue."
    )
    matching_policy_id: str | None = Field(
        default=None, description="Active policy the agent believes applies, or null."
    )
    recommended_action: Literal["apply_policy", "request_decision", "escalate"] = Field(
        description="What the agent recommends. Deterministic code makes the final call."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Agent confidence in this report.")
    rationale: str = Field(
        max_length=600,
        description="Two or three sentences a returns supervisor can read. No internal reasoning.",
    )


class ProposedBoundary(BaseModel):
    """A plain-language boundary shown on the decision card."""

    description: str
    reason: str


class DecisionCard(BaseModel):
    """One compact decision, put to a human."""

    case_id: str
    headline: str = Field(max_length=140, description="One-line statement of the exception.")
    evidence: list[EvidenceItem]
    recommended_action: str = Field(
        max_length=280, description="The concrete action the agent recommends taking."
    )
    uncertainty: list[str] = Field(
        default_factory=list, description="What the agent is not sure about."
    )
    proposed_boundaries: list[ProposedBoundary] = Field(
        default_factory=list,
        description="The limits within which this decision should be allowed to repeat.",
    )
    why_human_must_decide: str = Field(
        max_length=400, description="Why this cannot be auto-resolved today."
    )
    estimated_cost_usd: float | None = None


class PolicyCondition(BaseModel):
    """One proposed condition. Re-validated against the allowlist server-side."""

    field: str = Field(description="Fact field to test.")
    operator: str = Field(description="One of: eq, neq, lt, lte, gt, gte, in, not_in.")
    value: bool | int | float | str | list[str] = Field(
        description="Literal value to compare against."
    )


class PolicyProposal(BaseModel):
    """The agent's constrained policy proposal.

    Deliberately flat: the *actions* are not part of the proposal at all. The
    agent chooses conditions and a spend cap; the action set is fixed by
    `app/policy/proposal.py`. A model cannot propose an action that is not
    already on the allowlist, because there is nowhere to write one.
    """

    name: str = Field(min_length=4, max_length=120, description="Short name for the policy.")
    description: str = Field(
        max_length=600,
        description="What the policy does, in plain language a supervisor can audit.",
    )
    conditions: list[PolicyCondition] = Field(
        min_length=1,
        max_length=12,
        description="Every condition that must hold before this policy may act.",
    )
    max_cost_usd: float = Field(
        gt=0,
        description="Spend cap for the replacement-parts work order this policy authorises.",
    )
    min_confidence: float = Field(default=0.75, ge=0.5, le=1.0)
    justification: str = Field(
        max_length=600, description="Why these boundaries match the decision the human approved."
    )
    expected_effect: str = Field(
        max_length=600, description="What becomes automatic, and what still escalates."
    )


class ActionResult(BaseModel):
    action: str
    ok: bool
    idempotency_key: str
    detail: str = ""
    duplicate_suppressed: bool = False
    reference: str | None = None


class VerificationResult(BaseModel):
    ok: bool
    checks: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class HandlingResult(BaseModel):
    """The end-to-end result of handling one exception event."""

    case_id: str
    exception_id: str
    trace_id: str
    outcome: Outcome
    status: ExceptionStatus
    policy_id: str | None = None
    escalation_reasons: list[str] = Field(default_factory=list)
    actions: list[ActionResult] = Field(default_factory=list)
    verification: VerificationResult | None = None
    decision_card: DecisionCard | None = None
    report: InvestigationReport | None = None
    tool_calls: list[str] = Field(default_factory=list)
    duration_ms: int = 0
