"""Admin-facing management of an organization's owner-alert Telegram chats.

The panel never learns a chat id. An admin mints a link, hands it to the
director over any channel, and the director's own Telegram tells the webhook
which chat to bind. That asymmetry is the whole security story: an admin can
create and revoke a link but cannot point one at a chat they chose, so nobody
inside a customer can quietly redirect the owner's alerts to themselves.

The deep link is only returned while the row is unactivated. After activation
the token has done its job, and echoing it back would leave a live re-binding
credential sitting in every list response.
"""
from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_org_id, require_role
from app.models.enums import UserRole
from app.models.owner_alerts import AlertKind, AlertSeverity, TelegramAccount
from app.models.users import User
from app.services.owner_alerts.commands import build_owner_deep_link
from app.services.telegram import send_message

router = APIRouter(prefix="/api/org/telegram", tags=["Owner Alerts"])

_ADMIN = require_role(UserRole.admin)
_READ = require_role(UserRole.admin, UserRole.manager)


class LinkCreate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    user_id: uuid.UUID | None = None


class LinkOut(BaseModel):
    id: uuid.UUID
    token: str
    deep_link: str
    label: str | None


class AccountUpdate(BaseModel):
    """Every field optional, and "absent" differs from "null".

    Clearing the quiet window is a real action ("tell me at any hour"), so the
    handler reads ``model_fields_set`` rather than treating ``None`` as
    "unchanged" — otherwise the only way out of quiet hours would be to unlink
    and start again.
    """

    muted_kinds: list[AlertKind] | None = None
    min_severity: AlertSeverity | None = None
    quiet_from_hour: int | None = Field(default=None, ge=0, le=23)
    quiet_to_hour: int | None = Field(default=None, ge=0, le=23)
    is_active: bool | None = None


class AccountOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    label: str | None
    activated: bool
    activated_at: str | None
    is_active: bool
    muted_kinds: list[str]
    min_severity: AlertSeverity
    quiet_from_hour: int | None
    quiet_to_hour: int | None
    # Present only until the owner opens it — see the module docstring.
    deep_link: str | None
    created_at: str


def _to_out(account: TelegramAccount) -> AccountOut:
    activated = account.chat_id is not None
    return AccountOut(
        id=account.id,
        user_id=account.user_id,
        label=account.label,
        activated=activated,
        activated_at=account.activated_at.isoformat() if account.activated_at else None,
        is_active=account.is_active,
        muted_kinds=list(account.muted_kinds or []),
        min_severity=account.min_severity,
        quiet_from_hour=account.quiet_from_hour,
        quiet_to_hour=account.quiet_to_hour,
        deep_link=None if activated else build_owner_deep_link(account.token),
        created_at=account.created_at.isoformat(),
    )


async def _get_owned(db: AsyncSession, account_id: uuid.UUID, org: uuid.UUID) -> TelegramAccount:
    account = (
        await db.execute(
            select(TelegramAccount).where(
                TelegramAccount.id == account_id, TelegramAccount.org_id == org
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Telegram account not found")
    return account


@router.post("/link", response_model=LinkOut, status_code=201)
async def create_link(
    data: LinkCreate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_ADMIN),
):
    """Mint an unactivated chat link.

    Works with no bot configured, exactly as trip subscriptions do: a customer
    can be onboarded before the bot exists, and the link starts working the day
    it is provisioned.
    """
    if data.user_id is not None:
        owner = (
            await db.execute(
                select(User).where(User.id == data.user_id, User.org_id == org)
            )
        ).scalar_one_or_none()
        if owner is None:
            raise HTTPException(status_code=404, detail="User not found")

    account = TelegramAccount(
        org_id=org,
        user_id=data.user_id,
        token=secrets.token_urlsafe(16),
        label=data.label,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return LinkOut(
        id=account.id,
        token=account.token,
        deep_link=build_owner_deep_link(account.token),
        label=account.label,
    )


@router.get("", response_model=list[AccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_READ),
):
    accounts = (
        await db.execute(
            select(TelegramAccount)
            .where(TelegramAccount.org_id == org)
            .order_by(TelegramAccount.created_at.desc())
        )
    ).scalars().all()
    return [_to_out(a) for a in accounts]


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: uuid.UUID,
    data: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_ADMIN),
):
    """Change one chat's delivery preferences."""
    account = await _get_owned(db, account_id, org)
    fields = data.model_dump(exclude_unset=True)

    if "muted_kinds" in fields:
        kinds = data.muted_kinds or []
        # Assigned as a new list rather than mutated in place: SQLAlchemy does
        # not track mutation inside a JSONB value, so an in-place append would
        # never reach the database.
        account.muted_kinds = [k.value for k in kinds]
    if "min_severity" in fields and data.min_severity is not None:
        account.min_severity = data.min_severity
    if "quiet_from_hour" in fields:
        account.quiet_from_hour = data.quiet_from_hour
    if "quiet_to_hour" in fields:
        account.quiet_to_hour = data.quiet_to_hour
    if "is_active" in fields and data.is_active is not None:
        account.is_active = data.is_active

    await db.commit()
    await db.refresh(account)
    return _to_out(account)


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_ADMIN),
):
    """Unlink a chat for good. The owner stops receiving anything immediately."""
    account = await _get_owned(db, account_id, org)
    await db.delete(account)
    await db.commit()
    return Response(status_code=204)


class TestResult(BaseModel):
    sent: bool


@router.post("/{account_id}/test", response_model=TestResult)
async def send_test(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_ADMIN),
):
    """Prove the link works, right now.

    Deliberately bypasses the alert bus: mute list, minimum severity, quiet
    hours and dedupe would each turn "did my link work?" into an unanswerable
    silence, and this is the one message whose entire purpose is to arrive.
    """
    account = await _get_owned(db, account_id, org)
    if account.chat_id is None:
        raise HTTPException(status_code=400, detail="Chat is not activated yet")

    result = await send_message(
        account.chat_id,
        "✅ <b>Sinov xabari</b>\nUlanish ishlayapti — muhim xabarlar shu chatga keladi.",
    )
    return TestResult(sent=result.ok)
