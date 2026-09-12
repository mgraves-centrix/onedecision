"""Domain pack: accounts payable, an invoice that does not match its PO.

A second domain on the same machinery, and the reason the machinery is worth
having. Nothing below is a new guarantee: the policy language, the replay gate,
the activation gate, idempotent execution, read-back verification and the audit
log are the same code the returns domain uses. What changes is the facts, the
guardrails, the actions, and the systems of record.

The story is the one from returns, in a different room. An AP clerk sees the same
$40 freight variance twenty times a week, approves it in thirty seconds, and
never writes it down.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db import Connection

from pydantic import BaseModel, ConfigDict, Field

from app.adapters import ap_ledger
from app.adapters.returns_system import AdapterError
from app.config import settings
from app.domains import ActionSpec, DomainSpec, register

FAMILY = "ap.invoice_variance"

# Outer walls for this domain, in its own units. A policy may be tighter.
MAX_VARIANCE_CEILING_USD = 250.0
MAX_VARIANCE_PCT_CEILING = 5.0
GL_VARIANCE_ACCOUNT = "GL-5820-PRICE-VARIANCE"
MONEY_TOLERANCE_USD = 0.01

BOOL_FIELDS = frozenset(
    {"po_match", "receipt_match", "tax_consistent", "duplicate_suspected", "vendor_on_hold", "evidence_complete"}
)

NUMBER_FIELDS = frozenset({"variance_usd", "variance_pct"})

ENUM_FIELDS = {"vendor_risk_tier": frozenset({"low", "medium", "high"})}

NUMERIC_CEILINGS = {
    "variance_usd": MAX_VARIANCE_CEILING_USD,
    "variance_pct": MAX_VARIANCE_PCT_CEILING,
}

ACTIONS = (
    ActionSpec(
        type="post_adjustment",
        literals={"gl_account": (GL_VARIANCE_ACCOUNT,)},
        caps={"max_amount_usd": MAX_VARIANCE_CEILING_USD},
        bound_by=("max_amount_usd", "variance_usd"),
    ),
    ActionSpec(type="release_payment", literals={"release_type": ("SCHEDULED",)}),
    ActionSpec(type="close_exception", literals={"resolution_code": ("RESOLVED_INVOICE_VARIANCE",)}),
)


class InvoiceFacts(BaseModel):
    """Deterministically derived, allowlist-typed facts about one invoice.

    Field names here are exactly the field names a policy is allowed to test.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    vendor_id: str
    vendor_name: str = ""
    po_number: str | None = None

    variance_usd: float | None = Field(default=None, ge=0)
    variance_pct: float | None = Field(default=None, ge=0)
    po_match: bool = False
    receipt_match: bool = False
    tax_consistent: bool = False
    duplicate_suspected: bool = False
    vendor_on_hold: bool = False
    evidence_complete: bool = False
    vendor_risk_tier: str = "high"

    # Not policy-testable. Carried for the decision card and the audit trail.
    invoice_total_usd: float = 0.0
    po_total_usd: float | None = None
    received_total_usd: float | None = None
    duplicate_of: tuple[str, ...] = ()
    missing_evidence_fields: tuple[str, ...] = ()
    tool_failures: tuple[str, ...] = ()

    def policy_view(self) -> dict[str, object]:
        """The subset a policy engine may read. Nothing else is visible to it."""
        return {
            "variance_usd": self.variance_usd,
            "variance_pct": self.variance_pct,
            "po_match": self.po_match,
            "receipt_match": self.receipt_match,
            "tax_consistent": self.tax_consistent,
            "duplicate_suspected": self.duplicate_suspected,
            "vendor_on_hold": self.vendor_on_hold,
            "evidence_complete": self.evidence_complete,
            "vendor_risk_tier": self.vendor_risk_tier,
        }


def derive_facts(conn: "Connection", case_id: str) -> InvoiceFacts:
    """Build the normalized, policy-testable view of one invoice."""
    tool_failures: list[str] = []
    invoice = ap_ledger.get_invoice(conn, case_id)

    vendor: dict[str, Any] = {}
    try:
        vendor = ap_ledger.get_vendor(conn, invoice["vendor_id"])
    except AdapterError as exc:
        tool_failures.append(str(exc))

    invoice_total = float(invoice["invoice_total_usd"])
    po_total = invoice["po_total_usd"]
    received_total = invoice["received_total_usd"]
    po_total = float(po_total) if po_total is not None else None
    received_total = float(received_total) if received_total is not None else None

    po_match = bool(invoice["po_number"]) and po_total is not None
    variance_usd = abs(invoice_total - po_total) if po_total is not None else None
    variance_pct = (
        round(variance_usd / po_total * 100, 4) if variance_usd is not None and po_total else None
    )

    receipt_match = (
        received_total is not None
        and po_total is not None
        and abs(received_total - po_total) <= MONEY_TOLERANCE_USD
    )

    tax, expected_tax = invoice["tax_amount_usd"], invoice["expected_tax_usd"]
    tax_consistent = (
        tax is not None
        and expected_tax is not None
        and abs(float(tax) - float(expected_tax)) <= MONEY_TOLERANCE_USD
    )

    duplicates = tuple(ap_ledger.duplicate_candidates(conn, invoice))
    gaps = tuple(ap_ledger.missing_evidence_fields(invoice["evidence"]))

    return InvoiceFacts(
        case_id=invoice["invoice_id"],
        vendor_id=invoice["vendor_id"],
        vendor_name=vendor.get("name", ""),
        po_number=invoice["po_number"],
        variance_usd=round(variance_usd, 2) if variance_usd is not None else None,
        variance_pct=variance_pct,
        po_match=po_match,
        receipt_match=receipt_match,
        tax_consistent=tax_consistent,
        duplicate_suspected=bool(duplicates),
        vendor_on_hold=bool(vendor.get("on_hold", True)),
        evidence_complete=not gaps,
        vendor_risk_tier=str(vendor.get("risk_tier", "high")),
        invoice_total_usd=invoice_total,
        po_total_usd=po_total,
        received_total_usd=received_total,
        duplicate_of=duplicates,
        missing_evidence_fields=gaps,
        tool_failures=tuple(tool_failures),
    )


@dataclass
class GuardrailResult:
    passed: bool
    reasons: tuple[str, ...] = dataclass_field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        return not self.passed


def evaluate_guardrails(
    facts: InvoiceFacts,
    *,
    confidence: float | None = None,
    tool_failures: tuple[str, ...] = (),
    matching_policy_count: int = 0,
) -> GuardrailResult:
    """Non-overridable invariants for paying an invoice variance automatically."""
    reasons: list[str] = []

    failures = tuple(tool_failures) or facts.tool_failures
    if failures:
        reasons.append(f"tool failure during investigation: {', '.join(failures)}")

    if facts.duplicate_suspected:
        reasons.append(f"possible duplicate of {', '.join(facts.duplicate_of)}")

    if facts.vendor_on_hold:
        reasons.append("vendor is on payment hold")

    if not facts.po_match:
        reasons.append("no purchase order matches this invoice")

    if not facts.receipt_match:
        reasons.append("goods received do not match the purchase order")

    if not facts.tax_consistent:
        reasons.append("tax does not reconcile against the expected amount")

    if not facts.evidence_complete:
        missing = ", ".join(facts.missing_evidence_fields) or "unspecified fields"
        reasons.append(f"approval evidence is incomplete ({missing})")

    if facts.variance_usd is None:
        reasons.append("variance cannot be computed; the purchase order total is unavailable")
    elif facts.variance_usd > MAX_VARIANCE_CEILING_USD:
        reasons.append(
            f"variance ${facts.variance_usd:.2f} exceeds the hard ceiling "
            f"${MAX_VARIANCE_CEILING_USD:.2f}"
        )

    if facts.variance_pct is not None and facts.variance_pct > MAX_VARIANCE_PCT_CEILING:
        reasons.append(
            f"variance {facts.variance_pct:.2f}% exceeds the hard ceiling "
            f"{MAX_VARIANCE_PCT_CEILING:.2f}%"
        )

    if confidence is not None and confidence < settings.confidence_threshold:
        reasons.append(
            f"agent confidence {confidence:.2f} is below the threshold "
            f"{settings.confidence_threshold:.2f}"
        )

    if matching_policy_count > 1:
        reasons.append(f"{matching_policy_count} active policies match this invoice; policies conflict")

    return GuardrailResult(passed=not reasons, reasons=tuple(reasons))


def fixed_actions(cap: float) -> list[dict[str, Any]]:
    """The action set a proposal always gets. The agent never chooses these."""
    return [
        {
            "type": "post_adjustment",
            "gl_account": GL_VARIANCE_ACCOUNT,
            "max_amount_usd": min(float(cap), MAX_VARIANCE_CEILING_USD),
        },
        {"type": "release_payment", "release_type": "SCHEDULED"},
        {"type": "close_exception", "resolution_code": "RESOLVED_INVOICE_VARIANCE"},
    ]


def corpus(conn: "Connection") -> list[tuple[str, str, str]]:
    rows = conn.execute(
        """SELECT invoice_id, expected_label, scenario_note FROM ap_invoices
            WHERE is_historical = ? ORDER BY invoice_id""",
        (True,),
    ).fetchall()
    return [(r["invoice_id"], r["expected_label"], r["scenario_note"] or "") for r in rows]


def execute(conn: "Connection", action: Any, *, facts: InvoiceFacts, idem_key: str) -> dict[str, Any]:
    """Perform one ledger write. The orchestrator owns the loop and the audit."""
    if action.type == "post_adjustment":
        if facts.variance_usd is None:
            raise AdapterError("variance unavailable at execution time")
        out = ap_ledger.post_adjustment(
            conn,
            invoice_id=facts.case_id,
            gl_account=action.gl_account,
            amount_usd=facts.variance_usd,
            max_amount_usd=action.max_amount_usd,
            idempotency_key=idem_key,
        )
        return {
            "label": f"post_adjustment:{action.gl_account}",
            "detail": f"{out['adjustment_id']} for ${facts.variance_usd:.2f} to {action.gl_account}",
            "duplicate_suppressed": out["duplicate_suppressed"],
            "reference": out["adjustment_id"],
        }

    if action.type == "release_payment":
        out = ap_ledger.release_payment(
            conn,
            invoice_id=facts.case_id,
            release_type=action.release_type,
            idempotency_key=idem_key,
        )
        return {
            "label": f"release_payment:{action.release_type}",
            "detail": f"{facts.case_id} released for the {action.release_type.lower()} payment run",
            "duplicate_suppressed": out["duplicate_suppressed"],
            "reference": facts.case_id,
        }

    raise AdapterError(f"'{action.type}' is not an action this domain performs")


def verify(conn: "Connection", case_id: str) -> tuple[list[str], list[str]]:
    """Read the ledger back. Returns (checks passed, failures)."""
    checks: list[str] = []
    failures: list[str] = []

    adjustments = ap_ledger.get_adjustments(conn, case_id)
    if len(adjustments) == 1:
        checks.append(f"one adjustment on file: {adjustments[0]['adjustment_id']}")
    elif not adjustments:
        failures.append("no variance adjustment was posted")
    else:
        failures.append(f"{len(adjustments)} adjustments exist for this invoice; expected exactly one")

    release = ap_ledger.get_payment_release(conn, case_id)
    if release and release["status"] == "RELEASED":
        checks.append("invoice is released for payment")
    else:
        failures.append("invoice was not released for payment")

    return checks, failures


SPEC = register(
    DomainSpec(
        family=FAMILY,
        label="Accounts payable — invoice variance",
        subject="invoice",
        bool_fields=BOOL_FIELDS,
        number_fields=NUMBER_FIELDS,
        enum_fields=ENUM_FIELDS,
        numeric_ceilings=NUMERIC_CEILINGS,
        actions=ACTIONS,
        required_action_types=("post_adjustment", "release_payment", "close_exception"),
        derive_facts=derive_facts,
        guardrails=evaluate_guardrails,
        corpus=corpus,
        execute=execute,
        verify=verify,
        fixed_actions=fixed_actions,
    )
)
