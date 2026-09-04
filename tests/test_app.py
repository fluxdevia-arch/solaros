import os
import tempfile
import unittest
import uuid
from pathlib import Path

TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "tests"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_TEMP_ROOT)

from streamlit.testing.v1 import AppTest


class StreamlitSmokeTest(unittest.TestCase):
    def setUp(self):
        self.db_path = TEST_TEMP_ROOT / f"app-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_entrypoint_renders_dashboard(self):
        app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
        app = AppTest.from_file(app_path, default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertGreaterEqual(len(app.metric), 8)
        self.assertTrue(any("Clientes ativos" == metric.label for metric in app.metric))

        for page_path in [
            "app_pages/clients.py",
            "app_pages/plants.py",
            "app_pages/readings.py",
            "app_pages/integrations.py",
            "app_pages/operations.py",
            "app_pages/service_orders.py",
            "app_pages/inspections.py",
            "app_pages/reports.py",
            "app_pages/pricing.py",
            "app_pages/proposals.py",
            "app_pages/cash.py",
            "app_pages/sizing.py",
            "app_pages/settings.py",
        ]:
            app.switch_page(page_path).run()
            self.assertFalse(app.exception, f"Falha ao renderizar {page_path}")


if __name__ == "__main__":
    unittest.main()
