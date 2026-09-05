import os
import tempfile
import unittest
import uuid
from pathlib import Path

TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "tests"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_TEMP_ROOT)

from streamlit.testing.v1 import AppTest


ALL_PAGE_PATHS = [
    "app_pages/clients.py",
    "app_pages/plants.py",
    "app_pages/readings.py",
    "app_pages/integrations.py",
    "app_pages/operations.py",
    "app_pages/service_orders.py",
    "app_pages/inspections.py",
    "app_pages/reports.py",
    "app_pages/pricing.py",
    "app_pages/pipeline.py",
    "app_pages/proposals.py",
    "app_pages/cash.py",
    "app_pages/sizing.py",
    "app_pages/service_contracts.py",
    "app_pages/settings.py",
]


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

        for page_path in ALL_PAGE_PATHS:
            app.switch_page(page_path).run()
            self.assertFalse(app.exception, f"Falha ao renderizar {page_path}")

    def test_all_pages_render_with_an_empty_database(self):
        previous_seed = os.environ.get("SOLAROS_SEED_DEMO")
        os.environ["SOLAROS_SEED_DEMO"] = "false"
        try:
            app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
            app = AppTest.from_file(app_path, default_timeout=20).run()
            self.assertFalse(app.exception)

            for page_path in ALL_PAGE_PATHS:
                app.switch_page(page_path).run()
                self.assertFalse(app.exception, f"Falha no estado vazio de {page_path}")
        finally:
            if previous_seed is None:
                os.environ.pop("SOLAROS_SEED_DEMO", None)
            else:
                os.environ["SOLAROS_SEED_DEMO"] = previous_seed

    def test_public_service_order_route_renders_without_login(self):
        from solar_crm.db import init_db, query_one
        from solar_crm.workflow import create_service_order

        init_db(seed=True)
        client = query_one("SELECT id FROM clients ORDER BY id LIMIT 1")
        plant = query_one("SELECT id, address FROM plants WHERE client_id=? ORDER BY id LIMIT 1", (client["id"],))
        order_id = create_service_order(
            {
                "client_id": client["id"],
                "plant_id": plant["id"],
                "title": "Teste de campo",
                "address": plant["address"],
                "work_description": "Validar a ficha pública da equipe.",
            }
        )
        order = query_one("SELECT public_token FROM service_orders WHERE id=?", (order_id,))

        app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
        app = AppTest.from_file(app_path, default_timeout=20)
        app.query_params["os"] = order["public_token"]
        app.run()

        self.assertFalse(app.exception)
        self.assertTrue(any(title.value == "Ordem de serviço" for title in app.title))
        self.assertTrue(any("Teste de campo" in heading.value for heading in app.subheader))

    def test_public_inspection_route_renders_without_login(self):
        from solar_crm.db import init_db, query_one
        from solar_crm.inspections import create_inspection, inspection_details

        init_db(seed=True)
        client = query_one("SELECT id FROM clients ORDER BY id LIMIT 1")
        plant = query_one("SELECT id, address FROM plants WHERE client_id=? ORDER BY id LIMIT 1", (client["id"],))
        inspection_id = create_inspection(
            {
                "client_id": client["id"],
                "plant_id": plant["id"],
                "address": plant["address"],
                "inspection_type": "Vistoria técnica",
                "technician": "Equipe de teste",
            }
        )
        inspection = inspection_details(inspection_id)

        app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
        app = AppTest.from_file(app_path, default_timeout=20)
        app.query_params["inspection"] = inspection["public_token"]
        app.run()

        self.assertFalse(app.exception)
        self.assertTrue(any(title.value == "Vistoria técnica" for title in app.title))
        self.assertGreaterEqual(len(app.selectbox), 25)


if __name__ == "__main__":
    unittest.main()
