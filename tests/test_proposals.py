import os
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from solar_crm.db import execute, init_db
from solar_crm.proposal_documents import generate_proposal_pdf
from solar_crm.records import create_proposal


TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "tests"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_TEMP_ROOT)


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.db_path = TEST_TEMP_ROOT / f"proposal-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)
        init_db(seed=True)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_create_and_render_branded_proposal(self):
        execute(
            "UPDATE settings SET app_name='Gestão Solar Parceira', company_name='Empresa Solar Parceira' WHERE id=1"
        )
        proposal_id = create_proposal({
            "client_id": 1,
            "title": "Proposta de consultoria técnica",
            "service_type": "Consultoria técnica",
            "issue_date": date.today().isoformat(),
            "valid_until": (date.today() + timedelta(days=15)).isoformat(),
            "amount": 2500,
            "payment_terms": "50% na aprovação e 50% na entrega.",
            "scope": "Análise técnica do sistema fotovoltaico.",
            "deliverables": "Relatório técnico\nReunião de apresentação",
            "exclusions": "Execução e materiais.",
            "deadline_days": 15,
        })
        pdf = generate_proposal_pdf(proposal_id)
        reader = PdfReader(BytesIO(pdf))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("PROPOSTA COMERCIAL", text)
        self.assertIn("Empresa Solar Parceira", text)
        self.assertNotIn("OnGrid Energia Solar", text)
        self.assertIn("Carlos Jessé Soares", text)
        self.assertGreater(len(pdf), 10_000)


if __name__ == "__main__":
    unittest.main()
