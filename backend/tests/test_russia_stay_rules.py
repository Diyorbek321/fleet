"""The 90-in-180 count, as Russia applies it to a visa-free foreigner.

Any 180-day window may hold at most 90 days in Russia; the day of entry and
the day of exit both count. A driver who leaves does not get a fresh 90 when
they come back — the days they spent are still inside the window until they
age out of it. Getting this wrong is a deportation and an entry ban, so these
are written against dates, not against the implementation.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services.russia_stay import Stay, days_in_window, summarize


def d(day: int, month: int = 10) -> date:
    return date(2026, month, day)


def test_entry_and_exit_days_both_count():
    assert days_in_window([Stay(d(1), d(1))], on=d(1)) == 1
    assert days_in_window([Stay(d(1), d(10))], on=d(20)) == 10


def test_an_open_stay_counts_up_to_today():
    assert days_in_window([Stay(d(1), None)], on=d(14)) == 14


def test_days_older_than_the_window_drop_out():
    long_ago = Stay(date(2026, 1, 1), date(2026, 1, 30))  # 30 days, then 180+ days ago
    assert days_in_window([long_ago], on=date(2026, 9, 1)) == 0


def test_a_stay_straddling_the_window_edge_counts_only_its_inside_part():
    on = d(14)
    window_start = on - timedelta(days=179)
    stay = Stay(window_start - timedelta(days=5), window_start + timedelta(days=4))
    assert days_in_window([stay], on=on) == 5


def test_a_first_entry_must_leave_on_the_90th_day():
    s = summarize([Stay(d(1), None)], today=d(14))
    assert s.in_russia is True
    assert s.day_of_stay == 14
    assert s.days_used == 14
    assert s.must_leave_by == d(1) + timedelta(days=89)
    assert s.days_to_leave == (s.must_leave_by - d(14)).days


def test_a_return_trip_does_not_reset_the_count():
    # 60 days in, out for 20, back in: 30 left, not 90.
    first = Stay(date(2026, 6, 1), date(2026, 6, 1) + timedelta(days=59))
    back_on = first.left_on + timedelta(days=21)
    s = summarize([first, Stay(back_on, None)], today=back_on)

    assert s.days_used == 61
    assert s.must_leave_by == back_on + timedelta(days=29)


def test_old_days_ageing_out_can_lengthen_the_stay():
    # 80 days spent long enough ago that they start dropping out of the window
    # while the driver is on their second stay: the deadline moves out with them.
    first = Stay(date(2026, 1, 10), date(2026, 3, 30))  # 80 days
    second_entry = date(2026, 7, 1)
    s = summarize([first, Stay(second_entry, None)], today=second_entry)

    naive = second_entry + timedelta(days=9)  # 90 - 80 = 10 days, if nothing aged out
    assert s.must_leave_by > naive
    # Whatever it is, staying through it never breaks the rule, and one more day does.
    stays = [first, Stay(second_entry, None)]
    for day in range((s.must_leave_by - second_entry).days + 1):
        on = second_entry + timedelta(days=day)
        assert days_in_window(stays, on=on) <= 90
    assert days_in_window(stays, on=s.must_leave_by + timedelta(days=1)) > 90


def test_an_overstay_is_reported_as_one():
    s = summarize([Stay(date(2026, 7, 1), None)], today=date(2026, 7, 1) + timedelta(days=95))
    assert s.days_used == 96
    assert s.overstay_days == 6
    assert s.days_to_leave < 0


def test_out_of_russia_it_says_how_many_days_a_new_entry_would_have():
    s = summarize([Stay(d(1, 8), d(9, 9))], today=d(14))  # 40 days, recently
    assert s.in_russia is False
    assert s.days_used == 40
    assert s.days_available == 50
    assert s.must_leave_by is None


def test_no_stays_means_a_clean_slate():
    s = summarize([], today=d(14))
    assert (s.in_russia, s.days_used, s.days_available) == (False, 0, 90)


def test_leaving_and_coming_back_the_same_day_counts_that_day_once():
    stays = [Stay(d(1), d(10)), Stay(d(10), d(12))]
    assert days_in_window(stays, on=d(20)) == 12
