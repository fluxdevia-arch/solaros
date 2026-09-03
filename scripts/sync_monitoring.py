from __future__ import annotations

import argparse
from datetime import date

from solar_crm.db import init_db
from solar_crm.monitoring import MonitoringError, sync_all


parser = argparse.ArgumentParser(description="Sincroniza as usinas vinculadas aos portais de monitoramento.")
parser.add_argument(
    "--month",
    default=date.today().strftime("%Y-%m"),
    help="Mês de referência no formato AAAA-MM. O padrão é o mês atual.",
)
args = parser.parse_args()

reference_month = f"{args.month[:7]}-01"
init_db(seed=True)

try:
    results = sync_all(reference_month)
except MonitoringError as exc:
    raise SystemExit(f"Sincronização interrompida: {exc}") from exc

if not results:
    print("Nenhuma usina ativa está vinculada a uma integração.")
else:
    for result in results:
        print(
            f"Usina {result.plant_id}: {result.generation_kwh:.1f} kWh, "
            f"{result.records_received} dias, desempenho {result.performance_pct:.1f}%"
        )
