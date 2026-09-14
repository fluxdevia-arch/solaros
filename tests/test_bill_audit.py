from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from solar_crm.bill_audit import analyze_energisa_bill
from solar_crm.bill_audit_documents import generate_bill_audit_pdf
from solar_crm.db import init_db


TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "tests"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_TEMP_ROOT)


FIRST_PAGE = """
ENERGISA PARAIBA - DISTRIBUIDORA DE ENERGIA S/A
Classificação: MTC-CONVENCIONAL BAIXA TENSÃO / B3
COMERCIAL / OUTROS SERVIÇOS E OUTRAS ATIVIDADES                    LIGAÇÃO:TRIFASICO
Agosto / 2026                             01/09/2026                          R$ 1.531,98
Itens da Fatura                                          Unid.         Quant.     Preço unit (R$)      Valor (R$)
Consumo em kWh                                                        10.168,00     0,930630          9.462,82       700,25         9.462,82    20        1.892,56      0,675650      PIS              0,01    1,6500           0,01
Energia Atv Injetada GDI mUC 7/2026 mPT                                2.161,00     0,815120         -1.761,49      -148,81           -762,94   20          -152,59     0,675650      COFINS           0,01    7,6000           0,01
Energia Atv Injetada GDII oUC 8/2026 mPT                               1.401,00     0,815120         -1.141,99       -96,48           -494,62   20           -98,92     0,675650
Energia Atv Injetada GDI oUC 8/2026 mPT                                6.606,00     0,815120         -5.384,74      -454,94         -2.332,30   20          -466,46     0,675650
Ajuste GDII - TRF Reduzida(Lei 14.300/22) - Conv.                      1.401,00     0,141600            198,39         0,00              0,00   0              0,00     0,141608
MULTA  07/2026                                                                                            26,87
TOTAL:                           1.531,98         0,02         5.872,96              1.174,59
DATA DE EMISSÃO:17/08/2026
NOTA FISCAL Nº: 009.060.559 - Série: 002
PAGADOR
CENTRO AVANCADO SOUSENSE DE OFTALMOLOGIA LTDA                                      09.319.013/0001-00
RUA BENTO FREIRE, 37    SOUSA (AG: 177)                                            CPF/CNPJ
SACADOR/ AVALISTA
1157384-2026-08-3
"""

SECOND_PAGE = """
UC de compensação de energia classificada como GD_I, conforme Lei 14.300/22
Saldo Acumulado: 4.462 A expirar no próximo ciclo: 0
AGO/26        10.168,00
JUL/26         8.919,00
JUN/26         8.459,00
Leitura Anterior:09/07/2026 Leitura Atual:14/08/2026 Dias:36
Serviço de distribuição 64,23 4,19 KWH Ponta 835.182,00 825.014,00 1,00 10.168,00 10.168,00
Encargo de Uso do Sistema de Distribuição
(Ref 06/2026): R$ 440,52
"""


class EnergisaBillAuditTests(unittest.TestCase):
    def setUp(self):
        self.db_path = TEST_TEMP_ROOT / f"bill-audit-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)
        init_db(seed=False)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_extracts_low_voltage_generator_and_financial_savings(self):
        with patch("solar_crm.bill_audit._extract_layout", return_value=(FIRST_PAGE, SECOND_PAGE)):
            audit = analyze_energisa_bill(b"synthetic", "energisa.pdf")

        self.assertEqual(audit.unit_profile, "Geradora - baixa tensão")
        self.assertEqual(audit.unit_code, "1157384")
        self.assertEqual(audit.client_name, "CENTRO AVANCADO SOUSENSE DE OFTALMOLOGIA LTDA")
        self.assertAlmostEqual(audit.consumption_kwh, 10168.0)
        self.assertAlmostEqual(audit.compensated_kwh, 10168.0)
        self.assertAlmostEqual(audit.credit_balance_kwh, 4462.0)
        self.assertAlmostEqual(audit.solar_credit_value, 8288.22)
        self.assertAlmostEqual(audit.fio_b_value, 198.39)
        self.assertAlmostEqual(audit.estimated_savings_month, 8089.83)
        self.assertAlmostEqual(audit.estimated_without_solar, 9621.81)
        self.assertAlmostEqual(audit.icms_value, 1174.59)

    def test_generates_signed_audit_pdf_with_financial_and_energy_sections(self):
        with patch("solar_crm.bill_audit._extract_layout", return_value=(FIRST_PAGE, SECOND_PAGE)):
            audit = analyze_energisa_bill(b"synthetic", "energisa.pdf")
        pdf = generate_bill_audit_pdf(audit)
        reader = PdfReader(BytesIO(pdf))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn("AUDITORIA DE FATURA DE ENERGIA", text)
        self.assertIn("Balanço de energia e créditos", text)
        self.assertIn("Fio B / ajuste GD II", text)
        self.assertIn("Achados da auditoria", text)
        self.assertIn("Carlos Jessé Soares", text)


if __name__ == "__main__":
    unittest.main()
