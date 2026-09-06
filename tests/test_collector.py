import json
import unittest
import uuid
from pathlib import Path

from collector.solaros_collector import (
    CollectorError,
    OfflineQueue,
    collect_snapshot,
    decode_registers,
    publish_with_queue,
    simulated_snapshot,
    validate_config,
)
from solar_crm.equipment_analysis import phb85k_mt_collector_config


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.config = phb85k_mt_collector_config(modbus_address=48, integration_id=7)

    def test_template_requires_official_register_map(self):
        with self.assertRaisesRegex(CollectorError, "mapa oficial PHB"):
            validate_config(self.config)

    def test_simulation_has_all_strings_and_mppts(self):
        validate_config(self.config, require_registers=False)
        payload = simulated_snapshot(self.config)

        self.assertEqual(len(payload["samples"]), 16)
        self.assertEqual({row["mppt"] for row in payload["samples"]}, {"MPPT 1", "MPPT 2", "MPPT 3", "MPPT 4"})
        self.assertTrue(all(row["power_kw"] > 0 for row in payload["samples"]))

    def test_decode_signed_and_scaled_register(self):
        self.assertEqual(decode_registers([0xFF9C], data_type="int16", scale=0.1), -10)

    def test_collect_snapshot_never_requires_write_callback(self):
        config = json.loads(json.dumps(self.config))
        for index, item in enumerate(config["registers"]["strings"]):
            item["current_a"] = {"address": index * 2}
            item["voltage_v"] = {"address": index * 2 + 1}
        payload = collect_snapshot(config, lambda spec: 8 if spec["address"] % 2 == 0 else 550)

        self.assertEqual(len(payload["samples"]), 16)
        self.assertEqual(payload["samples"][0]["power_kw"], 4.4)

    def test_failed_publish_is_queued_and_replayed(self):
        class Publisher:
            def __init__(self):
                self.fail = True
                self.received = []

            def publish(self, payload):
                if self.fail:
                    raise ConnectionError("offline")
                self.received.append(payload)

        payload = simulated_snapshot(self.config)
        publisher = Publisher()
        queue_path = Path(__file__).resolve().parents[1] / "tmp" / "tests" / f"queue-{uuid.uuid4().hex}.db"
        queue = OfflineQueue(queue_path)
        try:
            with self.assertRaises(ConnectionError):
                publish_with_queue(payload, publisher, queue)
            self.assertEqual(len(queue.pending()), 1)
            publisher.fail = False
            publish_with_queue(payload, publisher, queue)
            self.assertEqual(len(queue.pending()), 0)
            self.assertEqual(len(publisher.received), 2)
        finally:
            queue.close()
            queue_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
