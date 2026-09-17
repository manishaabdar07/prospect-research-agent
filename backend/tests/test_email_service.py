from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.email_service import EmailSendError, SMTPEmailService


def _settings(**overrides) -> Settings:
    defaults = dict(
        EMAIL_PROVIDER="smtp",
        EMAIL_HOST="smtp.example.com",
        EMAIL_PORT=587,
        EMAIL_USERNAME="user",
        EMAIL_PASSWORD="pass",
        EMAIL_FROM="outreach@example.com",
    )
    defaults.update(overrides)
    return Settings(**defaults)


@patch("app.email_service.smtplib.SMTP")
def test_send_uses_starttls_and_login_on_587(mock_smtp_cls):
    mock_server = MagicMock()
    mock_smtp_cls.return_value = mock_server

    service = SMTPEmailService(_settings())
    service.send(to="jane@acme.example", subject="Hi", body="Hello there")

    mock_smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=15)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("user", "pass")
    assert mock_server.sendmail.call_count == 1
    from_addr, to_addrs, _msg = mock_server.sendmail.call_args[0]
    assert from_addr == "outreach@example.com"
    assert to_addrs == ["jane@acme.example"]
    mock_server.quit.assert_called_once()


@patch("app.email_service.smtplib.SMTP_SSL")
def test_send_uses_ssl_on_465_and_skips_starttls(mock_smtp_ssl_cls):
    mock_server = MagicMock()
    mock_smtp_ssl_cls.return_value = mock_server

    service = SMTPEmailService(_settings(EMAIL_PORT=465))
    service.send(to="jane@acme.example", subject="Hi", body="Hello")

    mock_smtp_ssl_cls.assert_called_once_with("smtp.example.com", 465, timeout=15)
    mock_server.starttls.assert_not_called()
    mock_server.login.assert_called_once()


@patch("app.email_service.smtplib.SMTP")
def test_send_skips_login_when_no_credentials(mock_smtp_cls):
    mock_server = MagicMock()
    mock_smtp_cls.return_value = mock_server

    service = SMTPEmailService(_settings(EMAIL_USERNAME=None, EMAIL_PASSWORD=None))
    service.send(to="jane@acme.example", subject="Hi", body="Hello")

    mock_server.login.assert_not_called()
    mock_server.sendmail.assert_called_once()


@patch("app.email_service.smtplib.SMTP")
def test_send_wraps_smtp_exception_as_email_send_error(mock_smtp_cls):
    mock_server = MagicMock()
    mock_server.sendmail.side_effect = RuntimeError("mailbox unavailable")
    mock_smtp_cls.return_value = mock_server

    service = SMTPEmailService(_settings())
    with pytest.raises(EmailSendError):
        service.send(to="jane@acme.example", subject="Hi", body="Hello")
