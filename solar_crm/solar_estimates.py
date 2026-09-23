from __future__ import annotations


# Produção específica mensal conservadora (kWh/kWp/mês) para estimativas
# operacionais quando ainda não existe uma leitura real. O relatório técnico
# e o dimensionamento continuam dependendo dos dados medidos e do projeto.
STATE_MONTHLY_YIELD = {
    "AC": 125, "AL": 148, "AP": 128, "AM": 122, "BA": 150, "CE": 160,
    "DF": 145, "ES": 137, "GO": 148, "MA": 145, "MT": 147, "MS": 143,
    "MG": 140, "PA": 130, "PB": 150, "PR": 122, "PE": 152, "PI": 162,
    "RJ": 132, "RN": 158, "RS": 115, "RO": 132, "RR": 138, "SC": 116,
    "SP": 130, "SE": 146, "TO": 151,
}

DEFAULT_MONTHLY_YIELD = 135.0
DEFAULT_TARIFF_BRL_KWH = 0.95


def estimated_monthly_generation(installed_kwp: float, state: str | None, expected_kwh: float = 0) -> float:
    if float(expected_kwh or 0) > 0:
        return round(float(expected_kwh), 2)
    yield_value = STATE_MONTHLY_YIELD.get(str(state or "").strip().upper(), DEFAULT_MONTHLY_YIELD)
    return round(max(float(installed_kwp or 0), 0) * yield_value, 2)


def estimated_monthly_savings(generation_kwh: float, tariff: float | None = None) -> float:
    effective_tariff = float(tariff or 0)
    if effective_tariff <= 0:
        effective_tariff = DEFAULT_TARIFF_BRL_KWH
    return round(max(float(generation_kwh or 0), 0) * effective_tariff, 2)
