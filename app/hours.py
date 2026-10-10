"""US market hours on the NYSE calendar.

Drives the status badge at the top of the page and how often the page
refreshes. Unscheduled closures (e.g. a national day of mourning) can't be
predicted and show as an ordinary session.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PRE_OPEN = time(4, 0)
OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
POST_CLOSE = time(20, 0)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = (date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    # Anonymous Gregorian algorithm.
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month = (h + l - 7 * m + 90) // 25
    day = (h + l - 7 * m + 33 * month + 19) % 32
    return date(year, month, day)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=8)
def holidays(year: int) -> dict[date, str]:
    days: dict[date, str] = {}
    new_year = date(year, 1, 1)
    # A Saturday New Year's Day is not made up on the Friday before (NYSE Rule 7.2).
    if new_year.weekday() != 5:
        days[_observed(new_year)] = "New Year's Day"
    days[_nth_weekday(year, 1, 0, 3)] = "Martin Luther King Jr. Day"
    days[_nth_weekday(year, 2, 0, 3)] = "Washington's Birthday"
    days[_easter(year) - timedelta(days=2)] = "Good Friday"
    days[_last_weekday(year, 5, 0)] = "Memorial Day"
    if year >= 2022:
        days[_observed(date(year, 6, 19))] = "Juneteenth"
    days[_observed(date(year, 7, 4))] = "Independence Day"
    days[_nth_weekday(year, 9, 0, 1)] = "Labor Day"
    days[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving"
    days[_observed(date(year, 12, 25))] = "Christmas"
    return days


@lru_cache(maxsize=8)
def early_closes(year: int) -> frozenset[date]:
    """1pm closes: July 3, the day after Thanksgiving, and Christmas Eve."""
    out = {_nth_weekday(year, 11, 3, 4) + timedelta(days=1)}
    july3 = date(year, 7, 3)
    if july3.weekday() < 4:  # Independence Day falls Tuesday to Friday
        out.add(july3)
    christmas_eve = date(year, 12, 24)
    if christmas_eve.weekday() < 4:  # Christmas falls Tuesday to Friday
        out.add(christmas_eve)
    return frozenset(out)


def regular_session(d: date) -> tuple[datetime, datetime] | None:
    """Open and close of the regular session on `d`, or None if closed all day."""
    if d.weekday() >= 5 or d in holidays(d.year):
        return None
    close = EARLY_CLOSE if d in early_closes(d.year) else CLOSE
    return datetime.combine(d, OPEN, ET), datetime.combine(d, close, ET)


def next_open(now: datetime) -> datetime:
    et = now.astimezone(ET)
    d = et.date()
    for _ in range(15):
        session = regular_session(d)
        if session and session[0] > et:
            return session[0]
        d += timedelta(days=1)
    raise RuntimeError("no session in the next two weeks")


def status(now: datetime) -> dict:
    """Where the US market is right now, for the badge and the refresh cadence.

    `state` is one of open, pre (4:00-9:30am ET), post (close-8pm ET) or closed.
    """
    et = now.astimezone(ET)
    d = et.date()
    session = regular_session(d)
    out: dict = {"state": "closed", "early_close": False, "holiday": None}
    if session is None:
        out["holiday"] = holidays(d.year).get(d)
    else:
        open_at, close_at = session
        out["early_close"] = close_at.time() == EARLY_CLOSE
        if open_at <= et < close_at:
            out["state"] = "open"
            out["closes_at"] = close_at.isoformat()
        elif datetime.combine(d, PRE_OPEN, ET) <= et < open_at:
            out["state"] = "pre"
        elif close_at <= et < datetime.combine(d, POST_CLOSE, ET):
            out["state"] = "post"
    if out["state"] != "open":
        out["next_open"] = next_open(now).isoformat()
    return out
