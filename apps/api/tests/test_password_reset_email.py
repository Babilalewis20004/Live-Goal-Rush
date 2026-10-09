"""Password-reset delivery by email (Phase 7): the link goes to the mailbox, not to the API response or the logs."""

import asyncio
import logging

import pytest

from app.core.config import settings
from app.services import email as email_module

PASSWORD = "Sup3rSecret!"


class Outbox:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    async def send(self, to, subject, text):
        if self.fail:
            raise ConnectionError("smtp relay down")
        self.sent.append((to, subject, text))


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr(email_module, "get_email_sender", lambda: box)
    return box


async def _settle():
    """Let the fire-and-forget delivery task run."""
    for _ in range(5):
        await asyncio.sleep(0)
    if email_module._background:
        await asyncio.gather(*list(email_module._background), return_exceptions=True)


async def _register(client, email):
    await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})


async def _request(client, email):
    return await client.post("/api/v1/auth/password-reset/request", json={"email": email})


async def test_a_registered_address_receives_a_working_link(client, outbox):
    await _register(client, "reader@example.com")
    resp = await _request(client, "reader@example.com")
    await _settle()
    assert resp.status_code == 202
    assert len(outbox.sent) == 1
    to, subject, body = outbox.sent[0]
    assert to == "reader@example.com" and "password" in subject.lower()
    assert f"{settings.public_site_url}/reset-password?token=" in body
    token = body.split("token=")[1].split()[0]
    confirm = await client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Brand-New-Pass1"})
    assert confirm.status_code == 204
    login = await client.post("/api/v1/auth/login", json={"email": "reader@example.com", "password": "Brand-New-Pass1"})
    assert login.status_code == 200


async def test_an_unknown_address_gets_the_same_answer_and_no_email(client, outbox):
    await _register(client, "exists@example.com")
    known = await _request(client, "exists@example.com")
    unknown = await _request(client, "nobody@example.com")
    await _settle()
    assert known.status_code == unknown.status_code == 202
    assert known.json()["detail"] == unknown.json()["detail"]
    assert [to for to, _, _ in outbox.sent] == ["exists@example.com"]


async def test_the_response_does_not_wait_for_the_mail_server(client, outbox, monkeypatch):
    """If delivery were awaited, response time would reveal whether the address exists."""
    gate = asyncio.Event()

    async def slow_send(to, subject, text):
        await gate.wait()
        outbox.sent.append((to, subject, text))

    outbox.send = slow_send
    await _register(client, "slowmail@example.com")
    resp = await asyncio.wait_for(_request(client, "slowmail@example.com"), timeout=5)
    assert resp.status_code == 202 and outbox.sent == []  # answered while the email was still "in flight"
    gate.set()
    await _settle()
    assert len(outbox.sent) == 1


async def test_a_mail_server_outage_does_not_change_the_response_or_leak_the_token(client, outbox, caplog):
    outbox.fail = True
    await _register(client, "outage@example.com")
    with caplog.at_level(logging.DEBUG):
        resp = await _request(client, "outage@example.com")
        await _settle()
    assert resp.status_code == 202
    assert "reset-password?token=" not in caplog.text


async def test_a_deployed_instance_returns_nothing_but_still_sends_the_email(client, outbox, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    await _register(client, "prod@example.com")
    resp = await _request(client, "prod@example.com")
    await _settle()
    assert resp.json()["dev_reset_url"] is None
    assert len(outbox.sent) == 1


async def test_without_a_mail_server_nothing_is_sent_and_the_content_is_not_logged(client, caplog, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    await _register(client, "nomail@example.com")
    with caplog.at_level(logging.DEBUG):
        await _request(client, "nomail@example.com")
        await _settle()
    assert "SMTP is not configured" in caplog.text
    assert "reset-password?token=" not in caplog.text


async def test_the_smtp_sender_uses_starttls_and_authenticates(monkeypatch):
    events = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            events.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            events.append(("quit",))

        def starttls(self, context=None):
            events.append(("starttls",))

        def login(self, user, password):
            events.append(("login", user))

        def send_message(self, message):
            events.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_username", "mailer")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    await email_module.SmtpSender().send("a@example.com", "Hello", "body")
    assert events == [("connect", "smtp.example.com", 587), ("starttls",), ("login", "mailer"), ("send", "a@example.com", "Hello"), ("quit",)]
