from datetime import date, datetime, timezone

from app import hours
from app.hours import ET


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def test_2026_holidays_match_nyse_calendar():
    assert set(hours.holidays(2026)) == {
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
        date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
        date(2026, 11, 26), date(2026, 12, 25),
    }


def test_2027_observed_holidays():
    h = hours.holidays(2027)
    assert date(2027, 3, 26) in h  # Good Friday
    assert date(2027, 6, 18) in h  # Juneteenth on a Saturday -> Friday
    assert date(2027, 7, 5) in h  # Independence Day on a Sunday -> Monday
    assert date(2027, 12, 24) in h  # Christmas on a Saturday -> Friday


def test_saturday_new_year_is_not_made_up():
    # Jan 1 2028 is a Saturday; NYSE stays open on Friday Dec 31 2027.
    assert date(2027, 12, 31) not in hours.holidays(2027)
    assert date(2027, 12, 31) not in hours.holidays(2028)
    assert hours.regular_session(date(2027, 12, 31)) is not None


def test_easter_dates():
    assert hours._easter(2024) == date(2024, 3, 31)
    assert hours._easter(2025) == date(2025, 4, 20)
    assert hours._easter(2026) == date(2026, 4, 5)
    assert hours._easter(2027) == date(2027, 3, 28)
    assert hours._easter(2038) == date(2038, 4, 25)


def test_early_closes():
    assert hours.early_closes(2026) == {date(2026, 11, 27), date(2026, 12, 24)}
    assert date(2025, 7, 3) in hours.early_closes(2025)
    _, close = hours.regular_session(date(2026, 12, 24))
    assert close.hour == 13


def test_status_through_a_trading_day():
    assert hours.status(at(2026, 10, 5, 3, 59))["state"] == "closed"
    assert hours.status(at(2026, 10, 5, 4, 0))["state"] == "pre"
    assert hours.status(at(2026, 10, 5, 9, 30))["state"] == "open"
    assert hours.status(at(2026, 10, 5, 15, 59))["state"] == "open"
    assert hours.status(at(2026, 10, 5, 16, 0))["state"] == "post"
    assert hours.status(at(2026, 10, 5, 20, 0))["state"] == "closed"


def test_status_on_a_weekend_points_to_monday_open():
    s = hours.status(datetime(2026, 10, 4, 21, 0, tzinfo=timezone.utc))  # Sunday
    assert s["state"] == "closed"
    assert s["next_open"] == at(2026, 10, 5, 9, 30).isoformat()


def test_status_on_a_holiday_names_it():
    s = hours.status(at(2026, 11, 26, 11, 0))
    assert s["state"] == "closed"
    assert s["holiday"] == "Thanksgiving"
    assert s["next_open"] == at(2026, 11, 27, 9, 30).isoformat()


def test_early_close_day_is_post_market_after_1pm():
    s = hours.status(at(2026, 11, 27, 13, 30))
    assert s["state"] == "post"
    assert s["early_close"] is True
