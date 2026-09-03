from pathlib import Path

from solar_crm.db import available_months, init_db, query_one
from solar_crm.pdf_report import generate_client_report

init_db(seed=True)
months = available_months()
month = months[1] if len(months) > 1 else months[0]
client = query_one("SELECT id, name FROM clients ORDER BY id LIMIT 1")
target = Path("output/pdf/relatorio-demonstrativo-solar.pdf")
generate_client_report(client["id"], month, target)
print(target.resolve())
