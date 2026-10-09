"""Outbound email (Phase 7): password-reset delivery.

Before Phase 7 a deployed instance had no way to deliver a reset link (it was returned in the API response in
development and logged -- token included -- everywhere). Now the link is emailed, and neither returned nor logged.

* `SmtpSender` -- any SMTP relay (SES, Postmark, Mailgun, a corporate relay). STARTTLS by default.
* `NullSender` -- used when SMTP is not configured: it records that an email *could not be sent*, never the content.

Sending happens off the request path (`send_in_background`), so how long it takes can never reveal whether an
address is registered.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)

_background: set[asyncio.Task] = set()


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, text: str) -> None: ...


class SmtpSender:
    async def send(self, to: str, subject: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        await asyncio.to_thread(self._deliver, message)

    @staticmethod
    def _deliver(message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if settings.smtp_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
        with server:
            if not settings.smtp_ssl and settings.smtp_starttls:
                server.starttls(context=context)
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)


class NullSender:
    async def send(self, to: str, subject: str, text: str) -> None:
        logger.warning("Email not sent: SMTP is not configured (subject=%r)", subject)


def get_email_sender() -> EmailSender:
    return SmtpSender() if settings.smtp_host else NullSender()


def send_in_background(to: str, subject: str, text: str) -> None:
    """Fire and forget. A failure is logged (never with the message body) and never reaches the caller."""

    async def _go() -> None:
        try:
            await get_email_sender().send(to, subject, text)
        except Exception:
            logger.warning("Email delivery failed (subject=%r)", subject, exc_info=True)

    task = asyncio.get_running_loop().create_task(_go())
    _background.add(task)
    task.add_done_callback(_background.discard)


def password_reset_message(reset_url: str) -> tuple[str, str]:
    minutes = settings.password_reset_token_expire_minutes
    return (
        "Reset your LivePitch password",
        "Someone asked to reset the password for your LivePitch account.\n\n"
        f"Open this link within {minutes} minutes to choose a new password:\n{reset_url}\n\n"
        "If this was not you, ignore this email: your password has not changed.\n",
    )
