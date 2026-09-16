from pathlib import Path
import unittest
from io import BytesIO

from pypdf import PdfReader

from solar_crm.compensation_documents import generate_compensation_statement_pdf
from solar_crm.compensation_statement import analyze_compensation_statement


SOURCE = Path(r"C:\Users\Jessé\Downloads\demonstrativo-compensacao-5-1916467-2---9-2026.pdf")


class CompensationStatementTests(unittest.TestCase):
    @unittest.skipUnless(SOURCE.exists(), "Demonstrativo real não disponível neste ambiente")
    def test_real_energisa_compensation_statement_is_fully_parsed(self):
        statement = analyze_compensation_statement(SOURCE.read_bytes(), SOURCE.name)

        self.assertEqual(statement.client_name, "CLINICA VISAO DR JOSE VICENTE DE OLIVEIRA NETO LTDA")
        self.assertEqual(statement.unit_code, "2.058.850.053-25")
        self.assertEqual(statement.reference_month, "2026-09")
        self.assertEqual(len(statement.history), 26)
        self.assertEqual(statement.measured_kwh, 6)
        self.assertEqual(statement.injected_kwh, 11198)
        self.assertEqual(statement.compensated_kwh, 6)
        self.assertEqual(statement.previous_balance_kwh, 23)
        self.assertEqual(statement.transferred_kwh, 11191)
        self.assertEqual(statement.allocated_kwh, 11191)
        self.assertEqual(statement.available_credit_kwh, 24)
        self.assertEqual(sum(item.allocation_pct for item in statement.transfers), 100)
        self.assertEqual([item.total_kwh for item in statement.transfers], [8953, 1790, 448])

    @unittest.skipUnless(SOURCE.exists(), "Demonstrativo real não disponível neste ambiente")
    def test_compensation_report_contains_client_facing_summary(self):
        statement = analyze_compensation_statement(SOURCE.read_bytes(), SOURCE.name)
        pdf = generate_compensation_statement_pdf(statement)
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn("RELATÓRIO DE COMPENSAÇÃO DE ENERGIA", text)
        self.assertIn("11.191 kWh", text)
        self.assertIn("Rateio para unidades beneficiárias", text)
        self.assertIn("Conclusão para o cliente", text)
