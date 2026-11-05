"""
Alert delivery: Telegram and email (via Resend).
Sends signal status alerts — ACTIVE, WIN, or INVALIDATED.
Set these in GitHub Actions secrets:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  — for Telegram
  RESEND_API_KEY, ALERT_EMAIL           — for email via Resend
"""
from __future__ import annotations
import logging, os
import requests

log = logging.getLogger("notify_alerts")


def send_telegram(message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
        log.info("Telegram alert sent")
        return True
    except Exception as exc:
        log.warning("Telegram alert failed: %s", exc)
        return False


def send_email(subject: str, body: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "")
    to_email = os.environ.get("ALERT_EMAIL", "")
    from_email = os.environ.get("ALERT_FROM_EMAIL", "alerts@yourdomain.com")
    if not api_key or not to_email:
        return False
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": from_email, "to": [to_email], "subject": subject,
                  "text": body, "html": f"<pre>{body}</pre>"},
            timeout=15,
        )
        r.raise_for_status()
        log.info("Email alert sent to %s", to_email)
        return True
    except Exception as exc:
        log.warning("Email alert failed: %s", exc)
        return False


def send_alert(message: str, subject: str = "FX Desk Signal Alert") -> None:
    """Send to all configured channels."""
    send_telegram(message)
    send_email(subject, message)
