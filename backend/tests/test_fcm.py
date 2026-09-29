"""Pushes sent straight to Firebase (FCM HTTP v1), without Expo in between.

Never touches the network: Google's token endpoint and FCM are both served by
one mock transport. What matters: the OAuth exchange is signed with the key
and cached, the message carries what Android needs to show it while the app is
closed, and only Firebase's "UNREGISTERED" deletes a token.
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.driver_app import PushToken
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.users import User
from app.services import fcm
from app.services import push as push_service


@pytest.fixture
def credentials(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    path = tmp_path / "fcm.json"
    path.write_text(
        json.dumps(
            {"project_id": "fleet-test", "client_email": "push@fleet-test.iam", "private_key": pem}
        )
    )
    monkeypatch.setattr(settings, "fcm_credentials_file", str(path), raising=False)
    fcm.reset_cache()
    yield key.public_key()
    fcm.reset_cache()


class FakeGoogle:
    """Google's token endpoint plus FCM, recording what each received."""

    def __init__(self, fail_tokens: dict[str, httpx.Response] | None = None):
        self.token_requests: list[dict] = []
        self.messages: list[dict] = []
        self.fail_tokens = fail_tokens or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            self.token_requests.append(form)
            return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer ya29.test"
        assert request.url.path == "/v1/projects/fleet-test/messages:send"
        body = json.loads(request.content)
        self.messages.append(body["message"])
        return self.fail_tokens.get(body["message"]["token"], httpx.Response(200, json={"name": "m/1"}))


async def test_messages_are_signed_sent_and_shown_while_the_app_is_closed(credentials):
    google = FakeGoogle()
    results = await fcm.send(
        ["tok-a", "tok-b"],
        title="Нет сигнала GPS",
        body="01A123BC",
        data={"kind": "message", "count": 3},
        transport=httpx.MockTransport(google),
    )
    assert [r.ok for r in results] == [True, True]

    # One OAuth exchange for the batch, signed with the service-account key.
    assert len(google.token_requests) == 1
    claims = jwt.decode(
        google.token_requests[0]["assertion"],
        credentials.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
        algorithms=["RS256"],
        audience="https://oauth2.googleapis.com/token",
    )
    assert claims["iss"] == "push@fleet-test.iam"
    assert claims["scope"] == "https://www.googleapis.com/auth/firebase.messaging"

    msg = google.messages[0]
    assert msg["notification"] == {"title": "Нет сигнала GPS", "body": "01A123BC"}
    assert msg["data"] == {"kind": "message", "count": "3"}  # FCM wants strings
    assert msg["android"]["notification"]["channel_id"] == "default"
    assert msg["android"]["notification"]["icon"] == "notification_icon"


async def test_the_access_token_is_reused(credentials):
    google = FakeGoogle()
    transport = httpx.MockTransport(google)
    await fcm.send(["a"], title="t", body="b", transport=transport)
    await fcm.send(["b"], title="t", body="b", transport=transport)
    assert len(google.token_requests) == 1


async def test_without_a_key_nothing_is_sent(monkeypatch):
    monkeypatch.setattr(settings, "fcm_credentials_file", "/nonexistent/fcm.json", raising=False)
    fcm.reset_cache()
    google = FakeGoogle()
    results = await fcm.send(["a"], title="t", body="b", transport=httpx.MockTransport(google))
    assert [r.ok for r in results] == [False]
    assert google.messages == []


async def _user_with_tokens(tokens: list[str]) -> uuid.UUID:
    async with SessionLocal() as db:
        org = Organization(name=f"FCM Co {uuid.uuid4().hex[:6]}")
        db.add(org)
        await db.flush()
        user = User(
            org_id=org.id,
            email=f"fcm-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="x",
            role=UserRole.driver,
        )
        db.add(user)
        await db.flush()
        db.add_all([PushToken(user_id=user.id, token=t, platform="fcm") for t in tokens])
        await db.commit()
        return user.id


async def test_only_an_unregistered_token_is_deleted(credentials):
    """A 400 is as likely our own payload as a bad token; deleting on it would
    wipe every driver's registration on the first malformed message."""
    google = FakeGoogle(
        fail_tokens={
            "gone": httpx.Response(
                404,
                json={"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}},
            ),
            "bad-payload": httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}}),
        }
    )
    user_id = await _user_with_tokens(["gone", "bad-payload", "fine"])

    async with SessionLocal() as db:
        rows = (await db.execute(select(PushToken).where(PushToken.user_id == user_id))).scalars().all()
        out = await push_service.send_to_tokens(
            db, rows, title="t", body="b", transport=httpx.MockTransport(google)
        )
        await db.commit()

    assert out.accepted == 1
    assert out.failed == 2
    assert out.removed == ["gone"]
    async with SessionLocal() as db:
        left = (await db.execute(select(PushToken.token).where(PushToken.user_id == user_id))).scalars().all()
    assert sorted(left) == ["bad-payload", "fine"]
