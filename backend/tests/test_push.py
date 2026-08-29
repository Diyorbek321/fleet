"""Expo push delivery.

Until now the platform resolved a driver's devices, marked the watch as
notified, and then sent nothing: `/api/me/push-token` stored tokens the mobile
app never registered, and `notify_queue_change` carried a NOTE saying delivery
was "a separate integration". Both halves of the chain were missing, so the
border-queue feature looked complete and told drivers nothing.

These tests pin the server half. They never touch the network — the Expo
endpoint is driven through an injected transport.
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.driver_app import PushToken
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.users import User
from app.services import push as push_service


def _expo_token(n: int = 0) -> str:
    return f"ExponentPushToken[xxxxxxxxxxxxxxxxxxxx{n:02d}]"


async def _make_user_with_tokens(tokens: list[str]) -> tuple[uuid.UUID, list[uuid.UUID]]:
    async with SessionLocal() as db:
        org = Organization(name=f"Push Co {uuid.uuid4().hex[:6]}")
        db.add(org)
        await db.flush()
        user = User(
            org_id=org.id,
            email=f"push-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="x",
            role=UserRole.driver,
        )
        db.add(user)
        await db.flush()
        rows = [PushToken(user_id=user.id, token=t, platform="android") for t in tokens]
        db.add_all(rows)
        await db.commit()
        return user.id, [r.id for r in rows]


def _ok_response(request: httpx.Request) -> httpx.Response:
    sent = json.loads(request.content)
    return httpx.Response(200, json={"data": [{"status": "ok", "id": "x"} for _ in sent]})


class TestSendToTokens:
    async def test_no_tokens_makes_no_request(self):
        calls = 0

        def handler(request):
            nonlocal calls
            calls += 1
            return _ok_response(request)

        async with SessionLocal() as db:
            out = await push_service.send_to_tokens(
                db, [], title="t", body="b", transport=httpx.MockTransport(handler)
            )
        assert calls == 0
        assert out.accepted == 0

    async def test_sends_the_message_expo_expects(self):
        user_id, _ = await _make_user_with_tokens([_expo_token(1)])
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.extend(json.loads(request.content))
            return _ok_response(request)

        async with SessionLocal() as db:
            tokens = (
                await db.execute(select(PushToken).where(PushToken.user_id == user_id))
            ).scalars().all()
            out = await push_service.send_to_tokens(
                db,
                tokens,
                title="Navbat",
                body="Kechikyapsiz",
                data={"kind": "queue"},
                transport=httpx.MockTransport(handler),
            )

        assert out.accepted == 1
        assert len(seen) == 1
        assert seen[0]["to"] == _expo_token(1)
        assert seen[0]["title"] == "Navbat"
        assert seen[0]["body"] == "Kechikyapsiz"
        assert seen[0]["data"] == {"kind": "queue"}

    async def test_batches_at_the_expo_limit(self):
        """Expo rejects more than 100 messages in one request."""
        many = [_expo_token(i) for i in range(150)]
        user_id, _ = await _make_user_with_tokens(many)
        batch_sizes: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            batch_sizes.append(len(json.loads(request.content)))
            return _ok_response(request)

        async with SessionLocal() as db:
            tokens = (
                await db.execute(select(PushToken).where(PushToken.user_id == user_id))
            ).scalars().all()
            out = await push_service.send_to_tokens(
                db, tokens, title="t", body="b", transport=httpx.MockTransport(handler)
            )

        assert sorted(batch_sizes, reverse=True) == [100, 50]
        assert out.accepted == 150

    async def test_device_not_registered_deletes_the_token(self):
        """An uninstalled app leaves a token that can never receive anything.

        Left in place it is retried on every notification forever, so the table
        fills with dead rows and every send does needless work.
        """
        dead, alive = _expo_token(8), _expo_token(9)
        user_id, _ = await _make_user_with_tokens([dead, alive])

        def handler(request: httpx.Request) -> httpx.Response:
            sent = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"status": "ok", "id": "1"}
                        if m["to"] == alive
                        else {
                            "status": "error",
                            "message": "not registered",
                            "details": {"error": "DeviceNotRegistered"},
                        }
                        for m in sent
                    ]
                },
            )

        async with SessionLocal() as db:
            tokens = (
                await db.execute(select(PushToken).where(PushToken.user_id == user_id))
            ).scalars().all()
            out = await push_service.send_to_tokens(
                db, tokens, title="t", body="b", transport=httpx.MockTransport(handler)
            )
            await db.commit()

        assert out.accepted == 1
        assert out.removed == [dead]

        async with SessionLocal() as db:
            left = (
                await db.execute(select(PushToken.token).where(PushToken.user_id == user_id))
            ).scalars().all()
        assert left == [alive]

    async def test_other_errors_keep_the_token(self):
        """A transient Expo-side failure must not cost the driver their device."""
        token = _expo_token(11)
        user_id, _ = await _make_user_with_tokens([token])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"data": [{"status": "error", "message": "MessageTooBig",
                                "details": {"error": "MessageTooBig"}}]},
            )

        async with SessionLocal() as db:
            tokens = (
                await db.execute(select(PushToken).where(PushToken.user_id == user_id))
            ).scalars().all()
            out = await push_service.send_to_tokens(
                db, tokens, title="t", body="b", transport=httpx.MockTransport(handler)
            )
            await db.commit()

        assert out.accepted == 0
        assert out.removed == []

        async with SessionLocal() as db:
            left = (
                await db.execute(select(PushToken.token).where(PushToken.user_id == user_id))
            ).scalars().all()
        assert left == [token]

    async def test_a_dead_expo_never_breaks_the_caller(self):
        """Delivery is best-effort: the poll that triggered it must still finish."""
        user_id, _ = await _make_user_with_tokens([_expo_token(12)])

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("expo is down")

        async with SessionLocal() as db:
            tokens = (
                await db.execute(select(PushToken).where(PushToken.user_id == user_id))
            ).scalars().all()
            out = await push_service.send_to_tokens(
                db, tokens, title="t", body="b", transport=httpx.MockTransport(handler)
            )

        assert out.accepted == 0
        assert out.failed == 1

    async def test_non_expo_tokens_are_skipped(self):
        """The Expo endpoint only accepts its own token format.

        A bare FCM/APNs token posted to it is rejected for every message in the
        same batch, so one stale row would silently cost the whole send.
        """
        user_id, _ = await _make_user_with_tokens(["raw-fcm-token", _expo_token(13)])
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.extend(json.loads(request.content))
            return _ok_response(request)

        async with SessionLocal() as db:
            tokens = (
                await db.execute(select(PushToken).where(PushToken.user_id == user_id))
            ).scalars().all()
            out = await push_service.send_to_tokens(
                db, tokens, title="t", body="b", transport=httpx.MockTransport(handler)
            )

        assert [m["to"] for m in seen] == [_expo_token(13)]
        assert out.skipped == 1


class TestQueueMessage:
    @pytest.mark.parametrize(
        "status,expected_in_body",
        [
            ("late", "kechik"),
            ("revoked", "bekor"),
            ("crossed", "o'tdi"),
            ("in_queue", "navbat"),
        ],
    )
    def test_each_status_says_what_happened(self, status, expected_in_body):
        title, body = push_service.queue_status_message(status, plate="01A123AA",
                                                        checkpoint="Yallama")
        assert title
        assert expected_in_body.lower() in body.lower()
        assert "01A123AA" in f"{title} {body}"

    def test_unknown_status_still_produces_a_message(self):
        title, body = push_service.queue_status_message("something-new", plate="X",
                                                        checkpoint="Y")
        assert title and body


class TestQueueChangeActuallySends:
    """The wiring between a status change and a driver's phone.

    Previously this was the gap: `notify_queue_change` counted the devices,
    logged, and returned. Everything downstream of it looked healthy.
    """

    async def test_a_status_change_reaches_the_devices(self, monkeypatch):
        from app.models.drivers import Driver
        from app.models.driver_app import QueueWatch
        from app.services import queue as queue_service

        async with SessionLocal() as db:
            org = Organization(name=f"Notify Co {uuid.uuid4().hex[:6]}")
            db.add(org)
            await db.flush()
            driver = Driver(org_id=org.id, name="Test Driver",
                            license_number=f"L{uuid.uuid4().hex[:10]}")
            db.add(driver)
            await db.flush()
            user = User(
                org_id=org.id,
                email=f"notify-{uuid.uuid4().hex[:8]}@example.com",
                password_hash="x",
                role=UserRole.driver,
                driver_id=driver.id,
            )
            db.add(user)
            await db.flush()
            db.add(PushToken(user_id=user.id, token=_expo_token(21), platform="android"))
            watch = QueueWatch(
                driver_id=driver.id,
                plate="01A123AA",
                checkpoint="Yallama",
                last_status="late",
            )
            db.add(watch)
            await db.commit()
            watch_id = watch.id

        sent: list[dict] = []

        async def fake_send(db, tokens, *, title, body, data=None, transport=None):
            sent.append({"tokens": [t.token for t in tokens], "title": title, "body": body,
                         "data": data})
            return push_service.PushOutcome(accepted=len(tokens))

        monkeypatch.setattr(queue_service.push, "send_to_tokens", fake_send)

        async with SessionLocal() as db:
            watch = await db.get(QueueWatch, watch_id)
            delivered = await queue_service.notify_queue_change(db, watch, None)
            await db.commit()

        assert delivered == 1
        assert len(sent) == 1
        assert sent[0]["tokens"] == [_expo_token(21)]
        assert "01A123AA" in sent[0]["body"]
        assert sent[0]["data"]["kind"] == "queue"

    async def test_the_watch_is_marked_even_when_delivery_fails(self, monkeypatch):
        """Otherwise an unreachable phone gets the same alert on every sweep."""
        from app.models.drivers import Driver
        from app.models.driver_app import QueueWatch
        from app.services import queue as queue_service

        async with SessionLocal() as db:
            org = Organization(name=f"Fail Co {uuid.uuid4().hex[:6]}")
            db.add(org)
            await db.flush()
            driver = Driver(org_id=org.id, name="Test Driver 2",
                            license_number=f"L{uuid.uuid4().hex[:10]}")
            db.add(driver)
            await db.flush()
            user = User(
                org_id=org.id,
                email=f"fail-{uuid.uuid4().hex[:8]}@example.com",
                password_hash="x",
                role=UserRole.driver,
                driver_id=driver.id,
            )
            db.add(user)
            await db.flush()
            db.add(PushToken(user_id=user.id, token=_expo_token(22), platform="android"))
            watch = QueueWatch(
                driver_id=driver.id, plate="02B456BB", checkpoint="Gishtko'prik",
                last_status="revoked",
            )
            db.add(watch)
            await db.commit()
            watch_id = watch.id

        async def dead_send(db, tokens, **kw):
            return push_service.PushOutcome(failed=len(tokens))

        monkeypatch.setattr(queue_service.push, "send_to_tokens", dead_send)

        async with SessionLocal() as db:
            watch = await db.get(QueueWatch, watch_id)
            await queue_service.notify_queue_change(db, watch, None)
            await db.commit()

        async with SessionLocal() as db:
            watch = await db.get(QueueWatch, watch_id)
            assert watch.last_notified_status == "revoked"
