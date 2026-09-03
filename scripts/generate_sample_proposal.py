from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

from solar_crm.db import init_db
from solar_crm.proposal_documents import generate_proposal_pdf
from solar_crm.records import create_proposal


project_root = Path(__file__).resolve().parents[1]
output_path = project_root / "output" / "pdf" / "proposta_on_grid_exemplo.pdf"
output_path.parent.mkdir(parents=True, exist_ok=True)
temp_root = project_root / "tmp"
temp_root.mkdir(parents=True, exist_ok=True)

handle, database_name = tempfile.mkstemp(prefix="solaros-proposal-", suffix=".db", dir=temp_root)
os.close(handle)
Path(database_name).unlink(missing_ok=True)
os.environ["SOLAR_CRM_DB"] = database_name

try:
    init_db(seed=True)
    proposal_id = create_proposal({
        "client_id": 1,
        "title": "Proposta de projeto e dimensionamento fotovoltaico",
        "service_type": "Projeto e dimensionamento FV",
        "issue_date": date.today().isoformat(),
        "valid_until": (date.today() + timedelta(days=15)).isoformat(),
        "amount": 3500,
        "payment_terms": "50% na aprovação e 50% na entrega, por PIX ou transferência bancária.",
        "scope": "Levantamento de premissas e dimensionamento de módulos, inversor, strings, cabos, proteções e croqui preliminar da instalação.",
        "deliverables": "Memorial de dimensionamento\nCroqui de distribuição dos módulos por string\nLista técnica de cabos e proteções\nReunião de apresentação",
        "exclusions": "Execução da obra, materiais, projeto estrutural, taxas e aprovação junto à distribuidora.",
        "deadline_days": 15,
        "notes": "A proposta poderá ser ajustada após vistoria e confirmação das condições da cobertura.",
    })
    generate_proposal_pdf(proposal_id, output_path)
    print(output_path)
finally:
    Path(database_name).unlink(missing_ok=True)
