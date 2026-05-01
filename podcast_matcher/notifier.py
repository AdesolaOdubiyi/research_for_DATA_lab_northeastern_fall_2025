"""Optional email alerts via environment variables (no secrets in repo)."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any, Dict

logger = logging.getLogger(__name__)


def send_email(subject: str, body: str) -> bool:
    """Send email when SMTP settings are present in the environment."""
    host = os.environ.get("SMTP_HOST")
    if not host:
        logger.info("SMTP_HOST unset; skipping email subject=%s", subject)
        return False
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    mail_from = os.environ.get("NOTIFY_FROM", user)
    mail_to = os.environ.get("NOTIFY_TO", user)
    if not mail_from or not mail_to:
        logger.warning("NOTIFY_FROM / NOTIFY_TO incomplete; skip email")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = mail_from
        msg["To"] = mail_to
        msg.set_content(body)
        with smtplib.SMTP_SSL(host, port) as smtp:
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        logger.info("Email sent subject=%s", subject)
        return True
    except OSError as exc:
        logger.error("Email failed subject=%s error=%s", subject, exc)
        return False


def send_circuit_breaker_alert(stats: Dict[str, Any]) -> None:
    """Notify when a circuit breaker trips (best-effort)."""
    body = (
        "Circuit breaker triggered.\n\n"
        f"shows_processed={stats.get('shows_processed')}\n"
        f"episodes_matched={stats.get('episodes_matched')}\n"
    )
    send_email("Podcast matcher: circuit breaker", body)
