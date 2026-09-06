import os
import unittest
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image


class PlantEquipmentTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = temp_root / f"equipment-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        self.db_path.unlink(missing_ok=True)

    def test_equipment_serials_photos_and_client_summary(self):
        from solar_crm.db import init_db, query_one
        from solar_crm.plant_equipment import (
            add_equipment_photo,
            create_equipment,
            equipment_for_plant,
            equipment_photos,
            equipment_summary_for_client,
            normalize_serial_numbers,
            update_equipment,
        )

        init_db(seed=True)
        plant = query_one("SELECT id, client_id FROM plants ORDER BY id LIMIT 1")
        self.assertEqual(normalize_serial_numbers("INV-1, INV-2\nINV-1"), "INV-1\nINV-2")

        equipment_id = create_equipment(plant["id"], {
            "equipment_type": "Inversor",
            "manufacturer": "WEG",
            "model": "SIW500",
            "quantity": 2,
            "serial_numbers": "INV-1, INV-2",
            "nominal_power": 10,
            "power_unit": "kW",
            "status": "Operando",
        })
        update_equipment(equipment_id, {
            "equipment_type": "Inversor",
            "manufacturer": "WEG",
            "model": "SIW500 atualizado",
            "quantity": 2,
            "serial_numbers": "INV-1\nINV-2",
            "nominal_power": 10,
            "power_unit": "kW",
            "status": "Atenção",
            "location": "Casa de máquinas",
        })

        raw = BytesIO()
        Image.new("RGB", (1800, 900), "#173b2f").save(raw, format="PNG")
        add_equipment_photo(equipment_id, raw.getvalue(), "inversor.png", "Vista frontal")

        rows = equipment_for_plant(plant["id"])
        saved = next(row for row in rows if row["id"] == equipment_id)
        self.assertEqual(saved["model"], "SIW500 atualizado")
        self.assertEqual(saved["serial_numbers"], "INV-1\nINV-2")
        self.assertEqual(saved["photo_count"], 1)
        stored_photo = equipment_photos(equipment_id)[0]
        with Image.open(BytesIO(stored_photo["image_data"])) as normalized:
            self.assertEqual(normalized.format, "JPEG")
            self.assertLessEqual(max(normalized.size), 1600)

        summary = equipment_summary_for_client(plant["client_id"])
        self.assertEqual(summary[plant["id"]]["Inversor"], 2)

    def test_quantity_must_be_positive(self):
        from solar_crm.db import init_db, query_one
        from solar_crm.plant_equipment import create_equipment

        init_db(seed=True)
        plant = query_one("SELECT id FROM plants ORDER BY id LIMIT 1")
        with self.assertRaisesRegex(ValueError, "quantidade"):
            create_equipment(plant["id"], {"equipment_type": "Painel solar", "quantity": 0})


if __name__ == "__main__":
    unittest.main()
