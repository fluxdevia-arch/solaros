import os
import unittest
import uuid
from datetime import date
from pathlib import Path

from solar_crm.db import execute, init_db, query, query_one
from solar_crm.notifications import (
    create_manual_notification,
    notification_counts,
    notifications_for_role,
    refresh_automatic_notifications,
    set_notification_status,
    whatsapp_url,
)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = temp_root / f"notifications-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
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


if __name__ == "__main__":
    unittest.main()
