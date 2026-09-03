import os
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from solar_crm.monitoring import (
    GROWATT,
    SOLARZ,
    DailyTelemetry,
    RemotePlant,
    SolarZClient,
    SolisClient,
    create_integration,
    discover_remote_plants,
    link_plant,
    sync_mapping,
)
from solar_crm.secure_store import protect_secret, unprotect_secret


class _FakeConnector:
    def list_plants(self):
        return [RemotePlant("remote-101", "Usina remota", 74.8, 12.3, 123456.0, "online")]

    def fetch_month(self, remote_plant_id, reference_month):
        return [
            DailyTelemetry("2030-01-01", 120.5, 18.2, expected_generation_kwh=150),
            DailyTelemetry("2030-01-02", 179.5, 22.8, expected_generation_kwh=150),
        ]


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _SolarZSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "plantWithInfos/list" in url:
            return _FakeResponse({
                "content": [{
                    "id": 431,
                    "name": "Residência SolarZ",
                    "installedPower": 9.9,
                    "energyProducedKwh": 18342.5,
                    "status": {"status": "ONLINE"},
                }]
            })
        return _FakeResponse([
            {"date": "2026-08-01", "total": 42.5, "totalExpected": 40.0},
            {"date": "2026-08-02", "total": 38.0, "totalExpected": 40.0},
        ])


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = temp_root / f"monitoring-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        self.db_path.unlink(missing_ok=True)

    def test_windows_credentials_are_protected(self):
        encrypted = protect_secret("token-super-secreto")
        self.assertNotIn("token-super-secreto", encrypted)
        self.assertEqual(unprotect_secret(encrypted), "token-super-secreto")

    def test_solis_signature_is_deterministic(self):
        client = SolisClient("api-id", "api-secret")
        body = b'{"pageNo":1,"pageSize":100}'
        moment = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
        first = client._headers("/v1/api/userStationList", body, moment)
        second = client._headers("/v1/api/userStationList", body, moment)
        self.assertEqual(first, second)
        self.assertTrue(first["Authorization"].startswith("API api-id:"))
        self.assertEqual(first["Date"], "Thu, 03 Sep 2026 12:00:00 GMT")

    def test_solarz_uses_basic_auth_and_official_energy_route(self):
        session = _SolarZSession()
        client = SolarZClient("usuario-api", "senha-api", session=session)

        plants = client.list_plants()
        telemetry = client.fetch_month("431", "2026-08-01")

        self.assertEqual(plants[0], RemotePlant("431", "Residência SolarZ", 9.9, 0, 18342.5, "ONLINE"))
        self.assertEqual(len(telemetry), 2)
        self.assertEqual(telemetry[0].expected_generation_kwh, 40.0)
        self.assertEqual(session.calls[0][1]["auth"], ("usuario-api", "senha-api"))
        self.assertIn("/openApi/seller/plant/energy/plantId/431/month/2026-08", session.calls[1][0])

    def test_solarz_is_the_primary_provider(self):
        from solar_crm.monitoring import SUPPORTED_PROVIDERS

        self.assertEqual(SUPPORTED_PROVIDERS[0], SOLARZ)

    def test_discovery_link_and_monthly_sync(self):
        from solar_crm.db import init_db, query_one

        init_db(seed=True)
        integration_id = create_integration(
            "Conta Growatt",
            GROWATT,
            "https://openapi.growatt.com",
            "",
            "token-de-teste",
        )
        stored = query_one("SELECT * FROM monitoring_integrations WHERE id=?", (integration_id,))
        self.assertNotIn("token-de-teste", stored["credential_secret_encrypted"])

        with patch("solar_crm.monitoring._connector", return_value=_FakeConnector()):
            remote = discover_remote_plants(integration_id)
            self.assertEqual(remote[0].remote_id, "remote-101")
            local_plant = query_one("SELECT id FROM plants ORDER BY id LIMIT 1")
            link_plant(local_plant["id"], integration_id, "remote-101")
            mapping = query_one("SELECT id FROM plant_integrations WHERE plant_id=?", (local_plant["id"],))
            result = sync_mapping(mapping["id"], "2030-01-01")

        self.assertEqual(result.records_received, 2)
        self.assertEqual(result.generation_kwh, 300.0)
        self.assertEqual(result.performance_pct, 100.0)
        reading = query_one(
            "SELECT generation_kwh, meter_reading FROM readings WHERE plant_id=? AND reference_month='2030-01-01'",
            (local_plant["id"],),
        )
        self.assertEqual(reading["generation_kwh"], 300.0)
        self.assertIn("Growatt", reading["meter_reading"])
        self.assertEqual(query_one("SELECT COUNT(*) AS value FROM telemetry_daily")["value"], 2)
        self.assertEqual(query_one("SELECT status FROM integration_sync_logs ORDER BY id DESC")["status"], "Sucesso")


if __name__ == "__main__":
    unittest.main()
