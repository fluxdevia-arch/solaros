from __future__ import annotations

import re
from typing import Any, Iterable

from solar_crm.bill_audit import BillAudit


def normalize_unit_code(value: Any) -> str:
    """Normalize a distributor unit code without assuming it is numeric."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def find_bill_target(
    unit_code: str,
    plants: Iterable[dict[str, Any]],
    beneficiaries: Iterable[dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None]:
    """Return the registered plant or beneficiary that owns the bill UC."""
    normalized = normalize_unit_code(unit_code)
    if not normalized:
        return None, None
    plant_matches = [row for row in plants if normalize_unit_code(row.get("unit_code")) == normalized]
    if len(plant_matches) == 1:
        return "plant", plant_matches[0]
    beneficiary_matches = [row for row in beneficiaries if normalize_unit_code(row.get("unit_code")) == normalized]
    if len(beneficiary_matches) == 1:
        return "beneficiary", beneficiary_matches[0]
    return None, None


def reading_values_from_bill(
    audit: BillAudit,
    plant: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map invoice fields to a plant reading while preserving monitoring data."""
    current = existing or {}
    if not audit.reference_month:
        raise ValueError("A referência mensal não foi identificada na fatura.")
    consumption = float(audit.consumption_kwh or 0)
    tariff = float(audit.gross_consumption_cost / consumption) if consumption > 0 else float(current.get("tariff") or 0)
    measured_injection = (
        float(audit.injected_measured_kwh)
        if audit.injected_measured_kwh is not None
        else float(current.get("injected_kwh") or 0)
    )
    source_reference = f"Fatura Energisa: {audit.source_filename}"
    previous_reference = str(current.get("meter_reading") or "").strip()
    meter_reference = (
        f"{previous_reference} | {source_reference}"
        if previous_reference and source_reference not in previous_reference
        else previous_reference or source_reference
    )
    return {
        "plant_id": int(plant["id"]),
        "reference_month": f"{audit.reference_month[:7]}-01",
        "consumption_kwh": consumption,
        "generation_kwh": float(current.get("generation_kwh") or 0),
        "injected_kwh": measured_injection,
        "compensated_kwh": float(audit.compensated_kwh or 0),
        "tariff": round(tariff, 6),
        "billed_amount": float(audit.invoice_amount or 0),
        "reference_amount": float(audit.estimated_without_solar or 0),
        "availability_pct": float(current.get("availability_pct") if current.get("availability_pct") is not None else 100),
        "performance_ratio": float(current.get("performance_ratio") or 0),
        "downtime_hours": float(current.get("downtime_hours") or 0),
        "incidents": int(current.get("incidents") or 0),
        "failure_notes": current.get("failure_notes") or "",
        "meter_reading": meter_reference,
    }


def beneficiary_values_from_bill(
    audit: BillAudit,
    beneficiary: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map a beneficiary invoice without inventing the energy allocated by the plant."""
    current = existing or {}
    if not audit.reference_month:
        raise ValueError("A referência mensal não foi identificada na fatura.")
    source_note = f"Importado da fatura Energisa: {audit.source_filename}"
    previous_note = str(current.get("notes") or "").strip()
    notes = (
        f"{previous_note} | {source_note}"
        if previous_note and source_note not in previous_note
        else previous_note or source_note
    )
    return {
        "beneficiary_id": int(beneficiary["id"]),
        "reference_month": f"{audit.reference_month[:7]}-01",
        "allocated_kwh": float(current.get("allocated_kwh") or 0),
        "compensated_kwh": float(audit.compensated_kwh or 0),
        "billed_consumption_kwh": float(audit.consumption_kwh or 0),
        "previous_credit_kwh": float(current.get("previous_credit_kwh") or 0),
        "ending_credit_kwh": float(audit.credit_balance_kwh or 0),
        "notes": notes,
    }
