from __future__ import annotations

import unittest
from io import BytesIO

import pandas as pd
from PIL import Image

from solar_crm.ai_assistant import AssistantError, ask_assistant, prepare_attachment


class _Response:
    status_code = 200

    def json(self):
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Hipótese técnica com verificação em campo."}],
                }
            ],
            "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
        }


class _Session:
    def __init__(self):
        self.request = None

    def post(self, url, **kwargs):
        self.request = {"url": url, **kwargs}
        return _Response()


class AiAssistantTests(unittest.TestCase):
    def test_spreadsheet_is_summarized_before_ai_request(self):
        frame = pd.DataFrame(
            {
                "time": pd.date_range("2026-09-07 06:00", periods=4, freq="5min"),
                "Active power(kW)": [0.2, 1.8, 3.4, 2.1],
                "E-today(kWh)": [0.0, 0.1, 0.3, 0.5],
            }
        )
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            frame.to_excel(writer, index=False, sheet_name="Telemetria")

        attachment = prepare_attachment("curva.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer.getvalue())

        self.assertEqual(attachment["kind"], "document")
        self.assertIn('"linhas": 4', attachment["summary"])
        self.assertIn("diagnóstico_solaros", attachment["summary"])

    def test_photo_is_optimized_and_sent_as_visual_input(self):
        source = BytesIO()
        Image.new("RGB", (2400, 1600), "orange").save(source, format="PNG")
        attachment = prepare_attachment("quadro.png", "image/png", source.getvalue())
        session = _Session()

        answer, usage = ask_assistant(
            "sk-test",
            "gpt-5-mini",
            "Avalie esta foto",
            [],
            [attachment],
            session=session,
        )

        self.assertIn("verificação em campo", answer)
        self.assertEqual(usage["total_tokens"], 150)
        payload = session.request["json"]
        self.assertFalse(payload["store"])
        self.assertTrue(any(item["type"] == "input_image" for item in payload["input"][0]["content"]))
        self.assertNotIn("sk-test", str(payload))

    def test_missing_api_key_is_rejected_before_network_call(self):
        with self.assertRaisesRegex(AssistantError, "chave da API"):
            ask_assistant("", "gpt-5-mini", "Teste", [], [])


if __name__ == "__main__":
    unittest.main()
