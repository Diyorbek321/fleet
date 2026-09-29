"""A truck's Telegram group, and the order sheet posted there on a new trip.

What must hold: the post reads like the sheet dispatchers paste by hand, it
carries no money, it goes out once per trip, and only a group added with the
panel's own link can receive a truck's orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.routers import telegram as telegram_router
from app.services import trip_orders
from app.services.telegram import SendResult
from app.services.trip_orders import DEFAULT_RULES, format_trip_order, parse_group_start

GROUP_CHAT = {"id": -100123, "type": "supergroup", "title": "01A123BC Anvar"}


def _trip(**over) -> SimpleNamespace:
    fields = dict(
        reference="Angren Tek-0026",
        direction="ru_uz",
        border_crossing="Майский",
        origin_name="Елабуга",
        destination_name="Ташкент",
        shipper='ООО "КАСТАМОНУ"',
        loading_address="Республика Татарстан, улица Ш-3 https://yandex.uz/maps/-/CTsRe-O~",
        cargo_description="ДСП",
        cargo_weight_kg=22000,
        scheduled_start=datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc),
        loading_contact=None,
        consignee="ООО KS LUX INTERTRADING",
        customs_point="ТАШКЕНТ ТОВАРНЫЙ",
        unloading_address="Г. ТАШКЕНТ, ДЖАРКУРГАН 76",
        declarant_contact="903170002 Деклорант",
        rate=4200,
        currency="USD",
    )
    fields.update(over)
    return SimpleNamespace(**fields)


# ── The text ─────────────────────────────────────────────────────────────


def test_the_post_follows_the_hand_written_sheet():
    org = SimpleNamespace(trip_order_rules=None, trip_order_footer="Узб +99895 111 70 81")
    text = format_trip_order(_trip(), org)

    assert text.startswith("#26Импорт\n\nПогран. переход через МАЙСКИЙ !!!\n\n📍 Маршрут: Елабуга - Ташкент")
    assert "📦 Отправитель: ООО \"КАСТАМОНУ\"" in text
    assert "📦 Груз: ДСП 22 тн" in text
    assert "📅 Дата погрузки: 20.08" in text
    assert "\n\n———\n\n📦 Получатель: ООО KS LUX INTERTRADING" in text
    assert "🛃 Растаможка: ТАШКЕНТ ТОВАРНЫЙ" in text
    assert "📞 Контакты: 903170002 Деклорант" in text
    assert "⚠️ <b>ОБЯЗАТЕЛЬНО К ИСПОЛНЕНИЮ:</b>\n\n1️⃣ Чистый" in text
    assert text.endswith("Узб +99895 111 70 81 <b>ПОДТВЕРЖДАЕТЕ ЗАЯВКУ ?</b>")


def test_the_post_never_carries_the_rate():
    """The driver is in the group; the rate is between company and customer."""
    text = format_trip_order(_trip(rate=4200, currency="USD"), None)
    assert "4200" not in text and "USD" not in text


def test_empty_fields_are_left_out_not_printed_blank():
    text = format_trip_order(_trip(loading_contact=None, border_crossing=None, direction=None), None)
    assert text.startswith("#26\n\n📍 Маршрут")
    assert text.count("📞 Контакты") == 1


def test_an_export_is_tagged_as_one():
    assert format_trip_order(_trip(direction="uz_ru"), None).startswith("#26Экспорт")


def test_typed_text_cannot_inject_markup():
    text = format_trip_order(_trip(shipper="<b>Fake</b> & Co"), None)
    assert "&lt;b&gt;Fake&lt;/b&gt; &amp; Co" in text


def test_a_company_can_write_its_own_rules():
    org = SimpleNamespace(trip_order_rules="1️⃣ Только наши правила", trip_order_footer=None)
    text = format_trip_order(_trip(), org)
    assert "Только наши правила" in text
    assert DEFAULT_RULES.splitlines()[0] not in text


@pytest.mark.parametrize(
    "text,token",
    [
        ("/start truck_abc-1_Z", "abc-1_Z"),
        ("/start@FleetBot truck_abc", "abc"),
        ("/start trip_abc", None),
        ("/start truck_", None),
        ("/start truck_a b", None),
        ("hello truck_abc", None),
    ],
)
def test_only_a_truck_link_is_read_as_one(text, token):
    assert parse_group_start(text) == token


# ── The flow ─────────────────────────────────────────────────────────────


@pytest.fixture
def telegram(monkeypatch) -> list[tuple[str, str]]:
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    monkeypatch.setattr(settings, "telegram_bot_username", "FleetBot", raising=False)
    sent: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sent.append((str(chat_id), text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(trip_orders, "send_message", _fake_send)
    monkeypatch.setattr(telegram_router, "send_message", _fake_send)
    return sent


async def _truck(client: AsyncClient, headers, plate: str = "01A123BC") -> str:
    res = await client.post("/api/trucks", headers=headers, json={"name": plate, "plate_number": plate})
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _webhook(client: AsyncClient, update: dict) -> None:
    res = await client.post("/api/telegram/webhook", json={"update_id": 1, **update})
    assert res.status_code == 200, res.text


def _message(text: str, chat: dict = GROUP_CHAT) -> dict:
    return {"message": {"message_id": 1, "chat": chat, "text": text}}


async def _linked_truck(client: AsyncClient, headers, telegram) -> str:
    truck_id = await _truck(client, headers)
    link = (await client.post(f"/api/trucks/{truck_id}/telegram-group", headers=headers)).json()
    assert link["status"] == "pending"
    assert link["deep_link"].startswith("https://t.me/FleetBot?startgroup=truck_")
    token = link["deep_link"].split("startgroup=truck_", 1)[1]
    await _webhook(client, _message(f"/start@FleetBot truck_{token}"))
    telegram.clear()  # the "group connected" reply
    return truck_id


async def test_adding_the_bot_with_the_link_binds_the_group(
    client: AsyncClient, admin_headers, telegram
):
    truck_id = await _truck(client, admin_headers)
    link = (await client.post(f"/api/trucks/{truck_id}/telegram-group", headers=admin_headers)).json()
    token = link["deep_link"].split("startgroup=truck_", 1)[1]

    await _webhook(client, _message(f"/start@FleetBot truck_{token}"))
    assert telegram and "01A123BC" in telegram[0][1]

    status = (await client.get(f"/api/trucks/{truck_id}/telegram-group", headers=admin_headers)).json()
    assert status["status"] == "linked"
    assert status["chat_title"] == "01A123BC Anvar"
    assert status["deep_link"] is None  # spent

    # A second group opening the same link does not take the truck over.
    other = {"id": -100999, "type": "group", "title": "Somebody else"}
    await _webhook(client, _message(f"/start truck_{token}", chat=other))
    status = (await client.get(f"/api/trucks/{truck_id}/telegram-group", headers=admin_headers)).json()
    assert status["chat_title"] == "01A123BC Anvar"


async def test_a_new_trip_is_posted_to_its_trucks_group_once(
    client: AsyncClient, admin_headers, telegram
):
    truck_id = await _linked_truck(client, admin_headers, telegram)

    trip = (
        await client.post(
            "/api/trips",
            headers=admin_headers,
            json={"truck_id": truck_id, "origin_name": "Елабуга", "destination_name": "Ташкент"},
        )
    ).json()
    assert len(telegram) == 1
    assert telegram[0][0] == str(GROUP_CHAT["id"])
    assert "📍 Маршрут: Елабуга - Ташкент" in telegram[0][1]

    # An edit is not a new trip.
    await client.put(f"/api/trips/{trip['id']}", headers=admin_headers, json={"shipper": "X"})
    assert len(telegram) == 1

    # The dispatcher's "send again" button does send again.
    res = await client.post(f"/api/trips/{trip['id']}/send-order", headers=admin_headers)
    assert res.status_code == 200
    assert len(telegram) == 2


async def test_a_trip_given_its_truck_later_is_posted_then(
    client: AsyncClient, admin_headers, telegram
):
    truck_id = await _linked_truck(client, admin_headers, telegram)
    trip = (await client.post("/api/trips", headers=admin_headers, json={})).json()
    assert telegram == []

    await client.put(f"/api/trips/{trip['id']}", headers=admin_headers, json={"truck_id": truck_id})
    await client.put(f"/api/trips/{trip['id']}", headers=admin_headers, json={"shipper": "Y"})
    assert len(telegram) == 1


async def test_a_truck_without_a_group_posts_nothing(client: AsyncClient, admin_headers, telegram):
    truck_id = await _truck(client, admin_headers)
    trip = (await client.post("/api/trips", headers=admin_headers, json={"truck_id": truck_id})).json()
    assert telegram == []
    res = await client.post(f"/api/trips/{trip['id']}/send-order", headers=admin_headers)
    assert res.status_code == 409


async def test_removing_the_bot_from_the_group_shows_as_lost(
    client: AsyncClient, admin_headers, telegram
):
    truck_id = await _linked_truck(client, admin_headers, telegram)
    await _webhook(
        client,
        {"my_chat_member": {"chat": GROUP_CHAT, "new_chat_member": {"status": "kicked"}}},
    )
    status = (await client.get(f"/api/trucks/{truck_id}/telegram-group", headers=admin_headers)).json()
    assert status["status"] == "lost"

    await client.post("/api/trips", headers=admin_headers, json={"truck_id": truck_id})
    assert telegram == []


async def test_the_link_follows_a_group_upgraded_to_a_supergroup(
    client: AsyncClient, admin_headers, telegram
):
    truck_id = await _linked_truck(client, admin_headers, telegram)
    await _webhook(
        client,
        {"message": {"message_id": 2, "chat": GROUP_CHAT, "migrate_to_chat_id": -100777}},
    )
    await client.post("/api/trips", headers=admin_headers, json={"truck_id": truck_id})
    assert telegram[0][0] == "-100777"


async def test_the_bot_stays_quiet_in_a_group(client: AsyncClient, admin_headers, telegram):
    await _linked_truck(client, admin_headers, telegram)
    await _webhook(client, _message("Анвар, ты где?"))
    await _webhook(client, _message("/start"))
    assert telegram == []


async def test_the_company_footer_reaches_the_post(client: AsyncClient, admin_headers, telegram):
    res = await client.put(
        "/api/org/trip-order-template",
        headers=admin_headers,
        json={"rules": "", "footer": "Узб +99895 111 70 81"},
    )
    assert res.status_code == 200
    assert res.json()["rules"] is None  # empty = built-in list

    truck_id = await _linked_truck(client, admin_headers, telegram)
    await client.post("/api/trips", headers=admin_headers, json={"truck_id": truck_id})
    assert telegram[0][1].endswith("Узб +99895 111 70 81 <b>ПОДТВЕРЖДАЕТЕ ЗАЯВКУ ?</b>")


async def test_unlinking_stops_the_posts(client: AsyncClient, admin_headers, telegram):
    truck_id = await _linked_truck(client, admin_headers, telegram)
    res = await client.delete(f"/api/trucks/{truck_id}/telegram-group", headers=admin_headers)
    assert res.json()["status"] == "none"
    await client.post("/api/trips", headers=admin_headers, json={"truck_id": truck_id})
    assert telegram == []


async def test_a_driver_cannot_link_groups(client: AsyncClient, admin_headers, driver_login):
    truck_id = await _truck(client, admin_headers)
    res = await client.post(f"/api/trucks/{truck_id}/telegram-group", headers=driver_login["headers"])
    assert res.status_code == 403
