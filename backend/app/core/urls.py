"""Externally reachable URLs into the web app.

Both audiences that get a link from this backend — the fleet owner reading an
alert, and the cargo owner reading their morning card — need the same answer to
"where does the browser live", and getting it wrong ships a message with a
``None/trips/…`` href in it. One resolver, so the two can never disagree.
"""
from __future__ import annotations

import os

from app.core.config import settings

__all__ = ["web_base_url", "panel_link", "track_url"]


def web_base_url() -> str:
    """Base URL of the browser app, without a trailing slash. ``""`` if unknown.

    Read from ``PUBLIC_WEB_URL`` when set, otherwise the first configured CORS
    origin — which is by definition the browser app allowed to call this API, so
    in every real deployment it is already the right answer. Callers drop the
    link entirely on an empty result rather than sending a broken one.
    """
    explicit = (settings.public_web_url or os.environ.get("PUBLIC_WEB_URL", "")).strip()
    if explicit:
        return explicit.rstrip("/")
    origins = settings.cors_origins_list()
    return origins[0].rstrip("/") if origins else ""


def panel_link(path: str | None) -> str | None:
    """A link into the signed-in panel, e.g. ``/trips/<id>``."""
    if not path:
        return None
    base = web_base_url()
    if not base:
        return None
    return f"{base}/{path.lstrip('/')}"


def track_url(token: str | None) -> str | None:
    """The public tracking page for one subscription's token.

    No login: the token *is* the credential, and it is the same one the cargo
    owner already holds from their Telegram deep link. Returns ``None`` when the
    web app's address is unknown, so the card simply omits the line.
    """
    if not token:
        return None
    base = web_base_url()
    if not base:
        return None
    return f"{base}/track/{token}"
