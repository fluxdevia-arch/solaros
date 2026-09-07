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


class _GeminiResponse:
    status_code = 200

    def json(self):
        return {
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "Possível aquecimento; confirme por termografia."}],
                }
            ],
            "usage": {
                "total_input_tokens": 90,
                "total_output_tokens": 20,
                "total_tokens": 110,
            },
        }


class _ForbiddenResponse:
    status_code = 403

    def json(self):
        return {"error": {"status": "PERMISSION_DENIED"}}


class _Session:
    def __init__(self, response=None):
        self.request = None
        self.response = response or _Response()

    def post(self, url, **kwargs):
        self.request = {"url": url, **kwargs}
        return self.response


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

    def test_gemini_photo_request_uses_free_tier_connector(self):
        source = BytesIO()
        Image.new("RGB", (800, 600), "blue").save(source, format="JPEG")
        attachment = prepare_attachment("inversor.jpg", "image/jpeg", source.getvalue())
        session = _Session(_GeminiResponse())

        answer, usage = ask_assistant(
            "gemini-test-key",
            "gemini-3.7-flash",
            "Avalie o inversor",
            [],
            [attachment],
            provider="gemini",
            session=session,
        )

        self.assertIn("termografia", answer)
        self.assertEqual(usage["total_tokens"], 110)
        self.assertEqual(session.request["url"], "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(session.request["headers"]["x-goog-api-key"], "gemini-test-key")
        payload = session.request["json"]
        self.assertEqual(payload["model"], "gemini-3.7-flash")
        self.assertIn("system_instruction", payload)
        self.assertTrue(any(part.get("type") == "text" for part in payload["input"]))
        self.assertTrue(any(part.get("type") == "image" for part in payload["input"]))
        self.assertNotIn("gemini-test-key", str(payload))

    def test_gemini_permission_error_explains_project_access(self):
        with self.assertRaisesRegex(AssistantError, "projeto do Google.*tipo Auth"):
            ask_assistant(
                "standard-key",
                "gemini-3.7-flash",
                "Teste",
                [],
                [],
                provider="gemini",
                session=_Session(_ForbiddenResponse()),
            )


if __name__ == "__main__":
    unittest.main()
