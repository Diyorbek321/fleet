"""How long a driver has been in Russia, and by when they must leave.

A visa-free foreigner — every Uzbek driver — may spend at most 90 days in
Russia in any 180-day period. The window slides: each day it looks back 180
days (that day included) and counts the days spent in Russia, entry and exit
days both. Leaving does not reset anything; the days spent only stop counting
once they are more than 180 days old.

So "must leave by" is not entry + 90. It is the last day on which, staying
continuously until then, the count is still within 90 — which can be later
than entry + 90 minus the days already spent, because old days age out of the
window while the driver is inside. This module works it out day by day rather
than by formula, so it is right in exactly the cases a formula gets wrong.

Pure functions over dates; the database and the reminders live elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

LIMIT_DAYS = 90
WINDOW_DAYS = 180
# Reminder thresholds: days until the last legal day.
REMINDER_DAYS = (15, 7, 3)


@dataclass(frozen=True)
class Stay:
    entered_on: date
    # None while the driver is still in Russia.
    left_on: date | None


@dataclass(frozen=True)
class StaySummary:
    in_russia: bool
    entered_on: date | None
    # 1 on the day of entry; None outside Russia.
    day_of_stay: int | None
    # Days in Russia inside the 180-day window ending today.
    days_used: int
    # 90 - days_used: what a new entry would get today (may be negative).
    days_available: int
    # In Russia only: the last day the driver may still be there.
    must_leave_by: date | None
    # In Russia only: days from today to must_leave_by (0 = leave today, < 0 = overstay).
    days_to_leave: int | None
    overstay_days: int


def _window_start(on: date) -> date:
    return on - timedelta(days=WINDOW_DAYS - 1)


def days_in_window(stays: Iterable[Stay], *, on: date) -> int:
    """Days spent in Russia in the 180-day window ending on ``on``.

    An open stay counts through ``on``: asked about a future day, it assumes
    the driver stays until then — which is the question "must leave by" asks.
    """
    start = _window_start(on)
    # A set of days, not a sum of lengths: leaving and coming back the same
    # day is one day in Russia, not two.
    days: set[int] = set()
    for stay in stays:
        first = max(stay.entered_on, start)
        last = min(stay.left_on or on, on)
        if last >= first:
            days.update(range(first.toordinal(), last.toordinal() + 1))
    return len(days)


def _last_legal_day(stays: list[Stay], today: date) -> date:
    """The last day a continuous stay from today keeps the count within 90.

    Walks forward; the count can only rise by one a day and the walk ends at
    the first day over the limit. Bounded by the window: past 180 days ahead
    every older day has aged out, and an open stay alone cannot outlast 90.
    """
    day = today
    if days_in_window(stays, on=day) > LIMIT_DAYS:
        # Already over: the last legal day is behind us. Walk back to it.
        while day > today - timedelta(days=WINDOW_DAYS) and days_in_window(stays, on=day) > LIMIT_DAYS:
            day -= timedelta(days=1)
        return day
    for _ in range(WINDOW_DAYS + LIMIT_DAYS):
        nxt = day + timedelta(days=1)
        if days_in_window(stays, on=nxt) > LIMIT_DAYS:
            return day
        day = nxt
    return day


def summarize(stays: Iterable[Stay], *, today: date) -> StaySummary:
    stays = [s for s in stays if s.entered_on <= today]
    open_stay = next((s for s in stays if s.left_on is None), None)
    used = days_in_window(stays, on=today)

    if open_stay is None:
        return StaySummary(
            in_russia=False,
            entered_on=None,
            day_of_stay=None,
            days_used=used,
            days_available=LIMIT_DAYS - used,
            must_leave_by=None,
            days_to_leave=None,
            overstay_days=0,
        )

    must_leave_by = _last_legal_day(stays, today)
    return StaySummary(
        in_russia=True,
        entered_on=open_stay.entered_on,
        day_of_stay=(today - open_stay.entered_on).days + 1,
        days_used=used,
        days_available=LIMIT_DAYS - used,
        must_leave_by=must_leave_by,
        days_to_leave=(must_leave_by - today).days,
        overstay_days=max(0, used - LIMIT_DAYS),
    )


def reminder_bucket(summary: StaySummary) -> str | None:
    """Which reminder is due today, or None. ``"over"`` repeats daily."""
    if not summary.in_russia or summary.days_to_leave is None:
        return None
    if summary.overstay_days > 0 or summary.days_to_leave < 0:
        return "over"
    for threshold in sorted(REMINDER_DAYS):
        if summary.days_to_leave <= threshold:
            return str(threshold)
    return None
