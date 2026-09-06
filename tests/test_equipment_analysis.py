import os
import unittest
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from solar_crm.db import execute, init_db, query
from solar_crm.equipment_analysis import (
    NORMALIZED_REST,
    PHB85K_MT,
    EquipmentAnalysisError,
    analyze_string_samples,
    create_equipment_integration,
    equipment_profile,
    phb85k_mt_collector_config,
    sync_equipment_integration,
)


def _samples(factors: dict[str, list[float]]) -> list[dict]:
    rows = []
    start = datetime(2026, 9, 6, 8)
    for offset in range(len(next(iter(factors.values())))):
        for string_name, values in factors.items():
            current = 10 * values[offset]
            rows.append(
                {
                    "integration_id": 1,
                    "source_name": "Inversor teste",
                    "sample_at": (start + timedelta(hours=offset)).isoformat(),
                    "inverter_name": "INV 1",
                    "mppt": "MPPT 1",
                    "string_name": string_name,
                    "current_a": current,
                    "voltage_v": 550,
                    "power_kw": current * 550 / 1000,
                }
            )
    return rows


class EquipmentDiagnosticTests(unittest.TestCase):
    def test_phb85k_profile_and_collector_are_read_only(self):
        profile = equipment_profile(PHB85K_MT)
        config = phb85k_mt_collector_config(modbus_address=48)

        self.assertEqual(profile["mppt_count"], 4)
        self.assertEqual(profile["string_count"], 16)
        self.assertEqual(config["modbus_address"], 48)
        self.assertEqual(config["collector_mode"], "read_only")
        self.assertEqual(config["register_map"], "SOLICITAR_MAPA_OFICIAL_PHB")

    def test_phb85k_collector_rejects_invalid_modbus_address(self):
        with self.assertRaises(EquipmentAnalysisError):
            phb85k_mt_collector_config(modbus_address=0)

    def test_constant_deficit_is_classified_as_electrical(self):
        rows = _samples({"S1": [1, 1, 1, 1], "S2": [1, 1, 1, 1], "S3": [0.6, 0.6, 0.6, 0.6]})

        diagnostics = analyze_string_samples(rows)
        affected = next(item for item in diagnostics if item.string_name == "S3")

        self.assertEqual(affected.status, "Degradada")
        self.assertEqual(affected.pattern, "constante")
        self.assertIn("Conexão elétrica", affected.probable_cause)
        self.assertGreater(affected.loss_kwh, 0)

    def test_hour_window_points_to_shading(self):
        rows = _samples(
            {
                "S1": [1, 1, 1, 1, 1, 1],
                "S2": [1, 1, 1, 1, 1, 1],
                "S3": [1, 0.62, 0.62, 0.62, 1, 1],
            }
        )

        diagnostics = analyze_string_samples(rows)
        affected = next(item for item in diagnostics if item.string_name == "S3")

        self.assertEqual(affected.pattern, "janela")
        self.assertIn("Sombreamento", affected.probable_cause)

    def test_uniform_irradiance_drop_does_not_create_false_alarm(self):
        rows = _samples({"S1": [1, 0.4, 1], "S2": [1, 0.4, 1], "S3": [1, 0.4, 1]})

        diagnostics = analyze_string_samples(rows)

        self.assertTrue(all(item.status == "Saudável" for item in diagnostics))


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _EquipmentSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "/strings" in url:
            return _FakeResponse(
                {
                    "data": [
                        {
                            "timestamp": "2026-09-06T10:00:00",
                            "inverter": "INV 1",
                            "mppt": "MPPT 1",
                            "string": "S1",
                            "current_a": 8.2,
                            "voltage_v": 552,
                            "power_kw": 4.52,
                        }
                    ]
                }
            )
        return _FakeResponse(
            {
                "data": [
                    {
                        "id": "A-10",
                        "timestamp": "2026-09-06T10:02:00",
                        "code": "DC_LOW",
                        "severity": "Alta",
                        "title": "Corrente baixa",
                        "status": "Aberto",
                    }
                ]
            }
        )


class EquipmentIntegrationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / f"equipment-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)
        init_db(seed=False)
        client_id = execute("INSERT INTO clients (name) VALUES ('Cliente API')")
        self.plant_id = execute("INSERT INTO plants (client_id, name) VALUES (?, 'Usina API')", (client_id,))

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        self.db_path.unlink(missing_ok=True)

    def test_normalized_api_persists_samples_and_alarms(self):
        source_id = create_equipment_integration(
            plant_id=self.plant_id,
            name="Gateway do inversor",
            provider=NORMALIZED_REST,
            base_url="https://gateway.example.com",
            auth_type="Sem autenticação",
            credential_key="",
            credential_secret="",
            device_sn="INV-123",
            strings_path="/equipment/{device_sn}/strings?date={date}",
            alarms_path="/equipment/{device_sn}/alarms?date={date}",
        )
        session = _EquipmentSession()

        result = sync_equipment_integration(source_id, date(2026, 9, 6), session=session)

        self.assertEqual(result.string_samples, 1)
        self.assertEqual(result.alarms, 1)
        self.assertEqual(len(query("SELECT * FROM equipment_string_samples")), 1)
        self.assertEqual(len(query("SELECT * FROM equipment_alarms")), 1)
        self.assertIn("INV-123", session.calls[0][0])

    def test_phb_gateway_uses_the_normalized_collector_contract(self):
        source_id = create_equipment_integration(
            plant_id=self.plant_id,
            name="PHB85K-MT · 048",
            provider=PHB85K_MT,
            base_url="https://gateway.example.com",
            auth_type="Sem autenticação",
            credential_key="",
            credential_secret="",
            device_sn="048",
            strings_path="/equipment/{device_sn}/strings?date={date}",
            alarms_path="/equipment/{device_sn}/alarms?date={date}",
        )

        result = sync_equipment_integration(
            source_id,
            date(2026, 9, 6),
            session=_EquipmentSession(),
        )

        self.assertEqual(result.string_samples, 1)
        self.assertEqual(result.alarms, 1)


if __name__ == "__main__":
    unittest.main()
