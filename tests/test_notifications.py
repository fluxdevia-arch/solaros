import os
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from solar_crm.db import execute, init_db, query, query_one
from solar_crm.notifications import (
    create_manual_notification,
    notification_counts,
    notifications_for_role,
    refresh_automatic_notifications,
    set_notification_status,
    whatsapp_url,
)
from solar_crm.notification_delivery import (
    delivery_configuration,
    dispatch_pending_notifications,
    email_config,
    notification_deliveries,
    send_notification_channel,
)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = temp_root / f"notifications-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        self.delivery_env = {
            name: os.environ.get(name)
            for name in (
                "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TEMPLATE_NAME",
                "SMTP_HOST", "SMTP_PORT", "SMTP_FROM_EMAIL", "SMTP_SECURITY",
            )
        }
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)
        init_db(seed=False)
        self.client_id = execute(
            """INSERT INTO clients (name, contact_name, phone, email, city, state)
               VALUES ('Cliente Alerta','Maria','(83) 99999-0000','maria@example.com','João Pessoa','PB')"""
        )
        self.plant_id = execute(
            """INSERT INTO plants (client_id, name, installed_kwp, warranty_expiry)
               VALUES (?, 'Usina Teste', 50, '2026-10-01')""",
            (self.client_id,),
        )

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        for name, value in self.delivery_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.db_path.unlink(missing_ok=True)

    def test_refresh_creates_and_resolves_business_notifications(self):
        cash_id = execute(
            """INSERT INTO cash_transactions
               (transaction_type, category, client_id, competence_month, issue_date, due_date,
                amount, status, description)
               VALUES ('Receita','Consultoria',?,'2026-09-01','2026-09-01','2026-09-20',3000,'A receber','Consultoria solar')""",
            (self.client_id,),
        )
        task_id = execute(
            """INSERT INTO tasks (client_id, plant_id, title, category, due_date)
               VALUES (?, ?, 'Enviar laudo', 'Relatório', '2026-09-24')""",
            (self.client_id, self.plant_id),
        )
        created = refresh_automatic_notifications(date(2026, 9, 23))
        self.assertGreaterEqual(created, 4)  # caixa, atividade, garantia e leitura
        cash_notice = query_one("SELECT * FROM notification_events WHERE event_key=?", (f"cash:{cash_id}",))
        self.assertEqual(cash_notice["severity"], "Crítica")
        self.assertIn("3000", cash_notice["message"].replace(".", ""))
        self.assertIn("wa.me/5583999990000", whatsapp_url(cash_notice))
        self.assertGreater(notification_counts("Administrador")["new"], 0)

        execute("UPDATE cash_transactions SET status='Recebido', settlement_date='2026-09-23' WHERE id=?", (cash_id,))
        execute("UPDATE tasks SET status='Concluída', completed_at='2026-09-23' WHERE id=?", (task_id,))
        refresh_automatic_notifications(date(2026, 9, 23))
        self.assertEqual(query_one("SELECT status FROM notification_events WHERE event_key=?", (f"cash:{cash_id}",))["status"], "Resolvida")
        self.assertEqual(query_one("SELECT status FROM notification_events WHERE event_key=?", (f"task:{task_id}",))["status"], "Resolvida")

    def test_monthly_reading_deadline_is_the_fifth_day(self):
        refresh_automatic_notifications(date(2026, 9, 2))
        notice = query_one(
            "SELECT * FROM notification_events WHERE event_key=?",
            (f"reading:{self.plant_id}:2026-09-01",),
        )
        self.assertEqual(notice["due_date"], "2026-09-05")
        self.assertEqual(notice["severity"], "Média")

    def test_manual_notification_respects_audience_and_status(self):
        notification_id = create_manual_notification({
            "title": "Cobrança revisada",
            "message": "Entrar em contato com o cliente.",
            "category": "Financeiro",
            "severity": "Alta",
            "audience": "Financeiro",
            "client_id": self.client_id,
            "recipient_name": "Maria",
            "recipient_phone": "83999990000",
        })
        self.assertEqual(len(notifications_for_role("Financeiro")), 1)
        self.assertEqual(len(notifications_for_role("Técnico")), 0)
        set_notification_status(notification_id, "Lida")
        self.assertEqual(query_one("SELECT status FROM notification_events WHERE id=?", (notification_id,))["status"], "Lida")
        set_notification_status(notification_id, "Arquivada")
        self.assertEqual(len(notifications_for_role("Financeiro")), 0)
        self.assertEqual(len(notifications_for_role("Financeiro", include_archived=True)), 1)

    @patch("solar_crm.notification_delivery.requests.post")
    def test_automatic_whatsapp_delivery_is_configurable_and_not_duplicated(self, post):
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "test-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "123456"
        response = MagicMock()
        response.json.return_value = {"messages": [{"id": "wamid.test"}]}
        response.raise_for_status.return_value = None
        post.return_value = response
        notification_id = create_manual_notification({
            "title": "Cobrança próxima",
            "message": "O vencimento será amanhã.",
            "category": "Financeiro",
            "severity": "Alta",
            "audience": "Financeiro",
            "client_id": self.client_id,
            "recipient_name": "Maria",
            "recipient_phone": "83999990000",
            "recipient_email": "maria@example.com",
        })
        execute(
            """UPDATE settings SET notifications_auto_enabled=1,
               notifications_whatsapp_enabled=1, notifications_email_enabled=0,
               notifications_categories='Financeiro', notifications_min_severity='Média',
               notifications_delivery_started_at='2026-09-23T10:00:00' WHERE id=1"""
        )
        execute(
            "UPDATE notification_events SET created_at='2026-09-23 10:01:00' WHERE id=?",
            (notification_id,),
        )

        self.assertTrue(delivery_configuration()["whatsapp"])
        first = dispatch_pending_notifications()
        second = dispatch_pending_notifications()

        self.assertEqual(first["sent"], 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(notification_deliveries(notification_id)[0]["status"], "Enviada")
        self.assertEqual(second["sent"], 0)

    @patch("solar_crm.notification_delivery.smtplib.SMTP")
    def test_manual_email_delivery_records_provider_error_or_success(self, smtp_class):
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_PORT"] = "587"
        os.environ["SMTP_FROM_EMAIL"] = "alertas@example.com"
        os.environ["SMTP_SECURITY"] = "starttls"
        notification_id = create_manual_notification({
            "title": "Relatório disponível",
            "message": "Seu relatório mensal está pronto.",
            "category": "Leitura",
            "severity": "Média",
            "audience": "Financeiro",
            "client_id": self.client_id,
            "recipient_name": "Maria",
            "recipient_email": "maria@example.com",
        })

        delivery = send_notification_channel(notification_id, "E-mail")

        self.assertEqual(delivery["status"], "Enviada")
        smtp_class.assert_called_once()
        smtp_class.return_value.starttls.assert_called_once()
        smtp_class.return_value.send_message.assert_called_once()

    def test_invalid_smtp_port_falls_back_without_crashing_settings(self):
        os.environ["SMTP_PORT"] = "porta-invalida"
        self.assertEqual(email_config()["port"], 587)


if __name__ == "__main__":
    unittest.main()
