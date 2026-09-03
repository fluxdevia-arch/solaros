from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


def money(value: float | int | Decimal | None) -> str:
    """Format a number as Brazilian reais without depending on OS locale."""
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    raw = f"{amount:,.2f}"
    return f"R$ {raw.replace(',', 'X').replace('.', ',').replace('X', '.')}"


def number_br(value: float | int | Decimal | None, decimals: int = 1) -> str:
    raw = f"{float(value or 0):,.{decimals}f}"
    return raw.replace(",", "X").replace(".", ",").replace("X", ".")


def percent(value: float | int | None, decimals: int = 1) -> str:
    return f"{number_br(value, decimals)}%"


def calculate_savings(reference_amount: float, billed_amount: float) -> float:
    return max(round(float(reference_amount or 0) - float(billed_amount or 0), 2), 0.0)


def calculate_coverage(generation_kwh: float, consumption_kwh: float) -> float:
    consumption = float(consumption_kwh or 0)
    if consumption <= 0:
        return 0.0
    return round((float(generation_kwh or 0) / consumption) * 100, 2)


def calculate_performance(generation_kwh: float, expected_kwh: float) -> float:
    expected = float(expected_kwh or 0)
    if expected <= 0:
        return 0.0
    return round((float(generation_kwh or 0) / expected) * 100, 2)


@dataclass(frozen=True)
class PriceBreakdown:
    base: float
    plants: float
    capacity: float
    extras: float
    discount: float
    monthly_total: float
    annual_total: float


def calculate_service_price(
    base_fee: float,
    plant_count: int,
    per_plant_fee: float,
    total_kwp: float,
    per_kwp_fee: float,
    extras_fee: float = 0,
    discount_pct: float = 0,
) -> PriceBreakdown:
    base = max(float(base_fee or 0), 0)
    plants = max(int(plant_count or 0), 0) * max(float(per_plant_fee or 0), 0)
    capacity = max(float(total_kwp or 0), 0) * max(float(per_kwp_fee or 0), 0)
    extras = max(float(extras_fee or 0), 0)
    subtotal = base + plants + capacity + extras
    safe_discount_pct = min(max(float(discount_pct or 0), 0), 100)
    discount = subtotal * safe_discount_pct / 100
    monthly = round(subtotal - discount, 2)
    return PriceBreakdown(
        base=round(base, 2),
        plants=round(plants, 2),
        capacity=round(capacity, 2),
        extras=round(extras, 2),
        discount=round(discount, 2),
        monthly_total=monthly,
        annual_total=round(monthly * 12, 2),
    )


def contract_monthly_value(contract: dict, plant_count: int, total_kwp: float) -> float:
    return calculate_service_price(
        contract.get("base_fee", 0),
        plant_count,
        contract.get("per_plant_fee", 0),
        total_kwp,
        contract.get("per_kwp_fee", 0),
        contract.get("extras_fee", 0),
        contract.get("discount_pct", 0),
    ).monthly_total
