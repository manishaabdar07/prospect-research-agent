"""Stage 6 - Send Email.

Generic SMTP only for v1 -- no third-party provider SDK, per the current
spec. Credentials come only from Settings (env vars), never hardcoded.
Sending is synchronous: a single SMTP send is fast, and the user expects
immediate feedback from clicking Send, so unlike Stage 3's research loop
there is no background-task/polling dance here.
"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from typing import Protocol

from app.config import Settings, get_settings


class EmailSendError(Exception):
    """Raised on any failure to actually send -- never leaks raw SMTP
    exception text that might embed credentials; callers get a clean message."""


class EmailService(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...


class SMTPEmailService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, *, to: str, subject: str, body: str) -> None:
        settings = self._settings
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = subject
        message["From"] = settings.EMAIL_FROM
        message["To"] = to

        try:
            if settings.EMAIL_PORT == 465:
                server = smtplib.SMTP_SSL(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=15)
            else:
                server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=15)
            try:
                if settings.EMAIL_PORT != 465:
                    server.starttls()
                if settings.EMAIL_USERNAME and settings.EMAIL_PASSWORD:
                    server.login(settings.EMAIL_USERNAME, settings.EMAIL_PASSWORD)
                server.sendmail(settings.EMAIL_FROM, [to], message.as_string())
            finally:
                server.quit()
        except Exception as exc:
            raise EmailSendError(f"Failed to send email: {exc.__class__.__name__}") from exc


def get_email_service() -> EmailService:
    """Only 'smtp' is supported for v1 -- EMAIL_PROVIDER exists for a future
    provider switch without changing calling code."""
    return SMTPEmailService(get_settings())
