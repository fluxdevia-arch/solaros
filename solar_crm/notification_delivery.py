from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

import requests

from solar_crm.config import as_bool, setting
from solar_crm.db import connect, now_iso, query, query_one


SEVERITY_ORDER = {"Baixa": 0, "Média": 1, "Alta": 2, "Crítica": 3}
DELIVERY_CHANNELS = ("WhatsApp", "E-mail")


def _phone(value: object) -> str:
    phone = re.sub(r"\D", "", str(value or ""))
    if len(phone) in {10, 11}:
        phone = f"55{phone}"
    return phone


def whatsapp_config() -> dict[str, Any]:
    return {
        "access_token": str(setting("WHATSAPP_ACCESS_TOKEN", section="whatsapp", default="") or "").strip(),
        "phone_number_id": str(setting("WHATSAPP_PHONE_NUMBER_ID", section="whatsapp", default="") or "").strip(),
        "api_version": str(setting("WHATSAPP_API_VERSION", section="whatsapp", default="v23.0") or "v23.0").strip(),
        "template_name": str(setting("WHATSAPP_TEMPLATE_NAME", section="whatsapp", default="") or "").strip(),
        "template_language": str(setting("WHATSAPP_TEMPLATE_LANGUAGE", section="whatsapp", default="pt_BR") or "pt_BR").strip(),
    }


def email_config() -> dict[str, Any]:
    return {
        "host": str(setting("SMTP_HOST", section="email", default="") or "").strip(),
        "port": int(setting("SMTP_PORT", section="email", default=587) or 587),
        "username": str(setting("SMTP_USERNAME", section="email", default="") or "").strip(),
        "password": str(setting("SMTP_PASSWORD", section="email", default="") or ""),
        "from_email": str(setting("SMTP_FROM_EMAIL", section="email", default="") or "").strip(),
        "from_name": str(setting("SMTP_FROM_NAME", section="email", default="GRID Engenharia") or "GRID Engenharia").strip(),
        "security": str(setting("SMTP_SECURITY", section="email", default="starttls") or "starttls").strip().lower(),
    }


def delivery_configuration() -> dict[str, bool]:
    whatsapp = whatsapp_config()
    email = email_config()
    return {
        "whatsapp": bool(whatsapp["access_token"] and whatsapp["phone_number_id"]),
        "email": bool(email["host"] and email["from_email"]),
    }


def format_notification_message(notification: dict) -> str:
    recipient = notification.get("recipient_name") or notification.get("client_name") or "cliente"
    return f"Olá, {recipient}. {notification['title']}: {notification['message']}"


def _send_whatsapp(notification: dict) -> str:
    config = whatsapp_config()
    if not (config["access_token"] and config["phone_number_id"]):
        raise ValueError("Configure WHATSAPP_ACCESS_TOKEN e WHATSAPP_PHONE_NUMBER_ID nos Secrets.")
    recipient = _phone(notification.get("recipient_phone"))
    if not recipient:
        raise ValueError("O cliente não possui um telefone válido.")

    message = format_notification_message(notification)
    payload: dict[str, Any] = {"messaging_product": "whatsapp", "to": recipient}
    if config["template_name"]:
        payload.update({
            "type": "template",
            "template": {
                "name": config["template_name"],
                "language": {"code": config["template_language"]},
                "components": [{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(notification.get("recipient_name") or "cliente")},
                        {"type": "text", "text": str(notification["title"])},
                        {"type": "text", "text": str(notification["message"])},
                    ],
                }],
            },
        })
    else:
        payload.update({"type": "text", "text": {"preview_url": False, "body": message}})

    response = requests.post(
        f"https://graph.facebook.com/{config['api_version']}/{config['phone_number_id']}/messages",
        headers={"Authorization": f"Bearer {config['access_token']}", "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    messages = result.get("messages") or []
    return str(messages[0].get("id") if messages else "enviado")


def _send_email(notification: dict) -> str:
    config = email_config()
    recipient = str(notification.get("recipient_email") or "").strip()
    if not recipient:
        raise ValueError("O cliente não possui um e-mail válido.")
    if not (config["host"] and config["from_email"]):
        raise ValueError("Configure SMTP_HOST e SMTP_FROM_EMAIL nos Secrets.")

    message = EmailMessage()
    message["Subject"] = str(notification["title"])
    message["From"] = f"{config['from_name']} <{config['from_email']}>"
    message["To"] = recipient
    message.set_content(format_notification_message(notification))
    context = ssl.create_default_context()
    if config["security"] == "ssl":
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(config["host"], config["port"], timeout=20, context=context)
    else:
        smtp = smtplib.SMTP(config["host"], config["port"], timeout=20)
    try:
        if config["security"] in {"tls", "starttls"}:
            smtp.starttls(context=context)
        if config["username"]:
            smtp.login(config["username"], config["password"])
        smtp.send_message(message)
    finally:
        smtp.quit()
    return str(message.get("Message-ID") or "enviado")


def _save_delivery(notification_id: int, channel: str, recipient: str, status: str, *,
                   provider_message_id: str | None = None, error: str | None = None) -> None:
    now = now_iso()
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO notification_deliveries
               (notification_id, channel, recipient, status, attempts, provider_message_id,
                last_error, sent_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?, CASE WHEN ?='Enviada' THEN ? ELSE NULL END, ?)
               ON CONFLICT(notification_id, channel) DO UPDATE SET
                 recipient=excluded.recipient, status=excluded.status,
                 attempts=notification_deliveries.attempts + 1,
                 provider_message_id=excluded.provider_message_id,
                 last_error=excluded.last_error,
                 sent_at=CASE WHEN excluded.status='Enviada' THEN excluded.sent_at ELSE notification_deliveries.sent_at END,
                 updated_at=excluded.updated_at""",
            (notification_id, channel, recipient, status, provider_message_id, error, status, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _claim_delivery(notification_id: int, channel: str, recipient: str, *, retry: bool) -> bool:
    """Reserve one delivery before the network call so concurrent sessions cannot duplicate it."""
    now = now_iso()
    conn = connect()
    try:
        cursor = conn.execute(
            """INSERT INTO notification_deliveries
               (notification_id, channel, recipient, status, attempts, updated_at)
               VALUES (?, ?, ?, 'Enviando', 0, ?)
               ON CONFLICT(notification_id, channel) DO NOTHING""",
            (notification_id, channel, recipient or "não informado", now),
        )
        claimed = bool(getattr(cursor, "rowcount", 0))
        if not claimed:
            existing = conn.execute(
                "SELECT status, attempts FROM notification_deliveries WHERE notification_id=? AND channel=?",
                (notification_id, channel),
            ).fetchone()
            if existing:
                current_status = existing["status"] if isinstance(existing, dict) else existing[0]
                attempts = int(existing["attempts"] if isinstance(existing, dict) else existing[1])
                if current_status == "Erro" and (retry or attempts < 3):
                    updated = conn.execute(
                        """UPDATE notification_deliveries SET status='Enviando', recipient=?, updated_at=?
                           WHERE notification_id=? AND channel=? AND status='Erro'""",
                        (recipient or "não informado", now, notification_id, channel),
                    )
                    claimed = bool(getattr(updated, "rowcount", 0))
                elif current_status == "Enviada" and retry:
                    updated = conn.execute(
                        """UPDATE notification_deliveries SET status='Enviando', recipient=?, updated_at=?
                           WHERE notification_id=? AND channel=? AND status='Enviada'""",
                        (recipient or "não informado", now, notification_id, channel),
                    )
                    claimed = bool(getattr(updated, "rowcount", 0))
        conn.commit()
        return claimed
    finally:
        conn.close()


def send_notification_channel(notification_id: int, channel: str, *, retry: bool = False) -> dict:
    if channel not in DELIVERY_CHANNELS:
        raise ValueError("Canal de envio inválido.")
    notification = query_one(
        """SELECT ne.*, c.name AS client_name FROM notification_events ne
           LEFT JOIN clients c ON c.id=ne.client_id WHERE ne.id=?""",
        (notification_id,),
    )
    if not notification:
        raise ValueError("Notificação não encontrada.")
    existing = query_one(
        "SELECT * FROM notification_deliveries WHERE notification_id=? AND channel=?",
        (notification_id, channel),
    )
    if existing and existing["status"] == "Enviada" and not retry:
        return existing

    recipient = _phone(notification.get("recipient_phone")) if channel == "WhatsApp" else str(notification.get("recipient_email") or "").strip()
    if not _claim_delivery(notification_id, channel, recipient, retry=retry):
        return query_one(
            "SELECT * FROM notification_deliveries WHERE notification_id=? AND channel=?",
            (notification_id, channel),
        )
    try:
        provider_id = _send_whatsapp(notification) if channel == "WhatsApp" else _send_email(notification)
        _save_delivery(notification_id, channel, recipient, "Enviada", provider_message_id=provider_id)
    except Exception as exc:
        error = str(exc)[:1000]
        _save_delivery(notification_id, channel, recipient or "não informado", "Erro", error=error)
    return query_one(
        "SELECT * FROM notification_deliveries WHERE notification_id=? AND channel=?",
        (notification_id, channel),
    )


def notification_deliveries(notification_id: int) -> list[dict]:
    return query(
        "SELECT * FROM notification_deliveries WHERE notification_id=? ORDER BY channel",
        (notification_id,),
    )


def dispatch_pending_notifications(limit: int = 20) -> dict[str, int]:
    settings_row = query_one("SELECT * FROM settings WHERE id=1") or {}
    result = {"sent": 0, "errors": 0, "skipped": 0}
    if not as_bool(settings_row.get("notifications_auto_enabled")):
        return result

    enabled_channels = []
    if as_bool(settings_row.get("notifications_whatsapp_enabled")):
        enabled_channels.append("WhatsApp")
    if as_bool(settings_row.get("notifications_email_enabled")):
        enabled_channels.append("E-mail")
    if not enabled_channels:
        return result

    allowed_categories = {
        item.strip() for item in str(settings_row.get("notifications_categories") or "").split(",") if item.strip()
    }
    minimum = SEVERITY_ORDER.get(settings_row.get("notifications_min_severity"), 1)
    started_at = settings_row.get("notifications_delivery_started_at")
    rows = query(
        """SELECT * FROM notification_events
           WHERE status IN ('Nova','Lida') AND recipient_name IS NOT NULL
             AND (? IS NULL OR created_at>=?)
           ORDER BY created_at LIMIT ?""",
        (started_at, started_at, max(1, min(int(limit), 100))),
    )
    for notification in rows:
        if (allowed_categories and notification["category"] not in allowed_categories) or SEVERITY_ORDER.get(notification["severity"], 1) < minimum:
            result["skipped"] += 1
            continue
        for channel in enabled_channels:
            if channel == "WhatsApp" and not _phone(notification.get("recipient_phone")):
                result["skipped"] += 1
                continue
            if channel == "E-mail" and not str(notification.get("recipient_email") or "").strip():
                result["skipped"] += 1
                continue
            previous = query_one(
                "SELECT status FROM notification_deliveries WHERE notification_id=? AND channel=?",
                (notification["id"], channel),
            )
            if previous and previous["status"] == "Enviada":
                result["skipped"] += 1
                continue
            delivery = send_notification_channel(notification["id"], channel)
            if delivery["status"] == "Enviada":
                result["sent"] += 1
            else:
                result["errors"] += 1
    return result
