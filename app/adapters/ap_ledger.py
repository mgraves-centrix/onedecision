"""SYNTHETIC ADAPTER — accounts-payable ledger.

Invented, like every adapter in this package: no ERP, no bank, no vendor master.
Reads are free of side effects. Writes (an adjustment, a payment release) take an
idempotency key and suppress duplicates, the same contract the warehouse adapter
honors, because the machinery above re-runs on retry and must not pay twice.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db import Connection

from app.adapters.returns_system import AdapterError

REQUIRED_EVIDENCE = ("po_number", "receipt_id", "approver_id")


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "+00:00")


# ------------------------------------------------------------------- reads


def get_invoice(conn: "Connection", invoice_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM ap_invoices WHERE invoice_id = ?", (invoice_id,)
    ).fetchone()
    if row is None:
        raise AdapterError(f"invoice '{invoice_id}' not found in the AP ledger")
    invoice = dict(row)
    evidence = invoice.get("evidence")
    invoice["evidence"] = json.loads(evidence) if isinstance(evidence, str) else (evidence or {})
    return invoice


def get_vendor(conn: "Connection", vendor_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM ap_vendors WHERE vendor_id = ?", (vendor_id,)).fetchone()
    if row is None:
        raise AdapterError(f"vendor '{vendor_id}' not found in the vendor master")
    return dict(row)


def missing_evidence_fields(evidence: dict[str, Any]) -> list[str]:
    return [f for f in REQUIRED_EVIDENCE if not evidence.get(f)]


def duplicate_candidates(conn: "Connection", invoice: dict[str, Any]) -> list[str]:
    """Other invoices from the same vendor with the same number or the same total."""
    rows = conn.execute(
        """SELECT invoice_id FROM ap_invoices
            WHERE vendor_id = ? AND invoice_id <> ?
              AND (vendor_invoice_no = ? OR invoice_total_usd = ?)
            ORDER BY invoice_id""",
        (
            invoice["vendor_id"],
            invoice["invoice_id"],
            invoice["vendor_invoice_no"],
            invoice["invoice_total_usd"],
        ),
    ).fetchall()
    return [r["invoice_id"] for r in rows]


def get_adjustments(conn: "Connection", invoice_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM ap_adjustments WHERE invoice_id = ? ORDER BY adjustment_id", (invoice_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_payment_release(conn: "Connection", invoice_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM ap_payment_releases WHERE invoice_id = ?", (invoice_id,)
    ).fetchone()
    return dict(row) if row else None


# ------------------------------------------------------------------ writes


def post_adjustment(
    conn: "Connection",
    *,
    invoice_id: str,
    gl_account: str,
    amount_usd: float,
    max_amount_usd: float,
    idempotency_key: str,
) -> dict[str, Any]:
    """Post a variance adjustment to the ledger. Refuses to exceed the cap."""
    if amount_usd > max_amount_usd:
        raise AdapterError(
            f"adjustment ${amount_usd:.2f} exceeds the policy cap ${max_amount_usd:.2f}"
        )
    existing = conn.execute(
        "SELECT adjustment_id FROM ap_adjustments WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    if existing:
        return {"adjustment_id": existing["adjustment_id"], "duplicate_suppressed": True}

    adjustment_id = f"ADJ-{idempotency_key[:12]}"
    conn.execute(
        """INSERT INTO ap_adjustments (adjustment_id, invoice_id, gl_account, amount_usd,
               status, idempotency_key, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (adjustment_id, invoice_id, gl_account, amount_usd, "POSTED", idempotency_key, _now()),
    )
    return {"adjustment_id": adjustment_id, "duplicate_suppressed": False}


def release_payment(
    conn: "Connection",
    *,
    invoice_id: str,
    release_type: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Release the invoice for the next payment run. Never moves money here."""
    existing = conn.execute(
        "SELECT invoice_id FROM ap_payment_releases WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    if existing:
        return {"invoice_id": existing["invoice_id"], "duplicate_suppressed": True}

    already = get_payment_release(conn, invoice_id)
    if already:
        return {"invoice_id": invoice_id, "duplicate_suppressed": True}

    conn.execute(
        """INSERT INTO ap_payment_releases (invoice_id, release_type, status,
               idempotency_key, released_at) VALUES (?,?,?,?,?)""",
        (invoice_id, release_type, "RELEASED", idempotency_key, _now()),
    )
    return {"invoice_id": invoice_id, "duplicate_suppressed": False}
