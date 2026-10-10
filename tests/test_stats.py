import math
from datetime import date, timedelta

import pytest

from app.stats import Bar, change, merge_live, summarize


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_change_units_by_kind():
    assert change(110, 100, "price") == pytest.approx(10.0)
    assert change(4.12, 4.18, "rate") == pytest.approx(-6.0)  # bp
    assert change(0.55, 0.40, "spread") == pytest.approx(15.0)  # bp
    assert change(16.5, 15.0, "vol") == pytest.approx(1.5)  # points
    assert change(7.85, 7.80, "peg") == pytest.approx(0.641, abs=1e-3)
    assert change(1, 0, "price") is None
    assert change(None, 1, "price") is None


def test_summarize_day_week_ytd():
    days = weekdays(date(2025, 12, 1), 30)  # Dec 2025 into Jan 2026
    bars = [Bar(d, 100.0 + i) for i, d in enumerate(days)]
    q = summarize(bars, "price")
    last = bars[-1]
    assert q["last"] == last.close
    assert q["date"] == last.day.isoformat()
    assert q["d"] == pytest.approx((last.close / bars[-2].close - 1) * 100)
    week_ref = [b for b in bars if b.day <= last.day - timedelta(days=7)][-1]
    assert q["w"] == pytest.approx((last.close / week_ref.close - 1) * 100)
    dec31 = [b for b in bars if b.day.year == 2025][-1]
    assert q["ytd"] == pytest.approx((last.close / dec31.close - 1) * 100)


def test_ytd_missing_without_prior_year_history():
    bars = [Bar(d, 50.0) for d in weekdays(date(2026, 1, 5), 25)]
    assert summarize(bars, "price")["ytd"] is None


def test_rates_change_in_bp():
    days = weekdays(date(2026, 9, 1), 25)
    bars = [Bar(d, 4.00 + 0.01 * i) for i, d in enumerate(days)]
    q = summarize(bars, "rate")
    assert q["d"] == pytest.approx(1.0)  # one basis point a day


def test_typical_move_and_unusual_flag():
    days = weekdays(date(2026, 8, 3), 25)
    closes = [100.0]
    for i in range(23):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 0.99))  # +-1% days
    closes.append(closes[-1] * 1.05)  # then a 5% day
    q = summarize([Bar(d, c) for d, c in zip(days, closes)], "price")
    assert q["typical"] == pytest.approx(1.0, rel=0.02)
    assert q["z"] == pytest.approx(5.0, rel=0.03)
    assert q["unusual"] is True


def test_typical_needs_ten_moves():
    bars = [Bar(d, 100.0 + i) for i, d in enumerate(weekdays(date(2026, 9, 1), 6))]
    q = summarize(bars, "price")
    assert q["typical"] is None and q["z"] is None and q["unusual"] is False


def test_52_week_range_ignores_bad_zero_lows():
    days = weekdays(date(2026, 1, 5), 30)
    bars = [Bar(d, 15.0 + i % 3, high=17.0 + i % 3, low=14.0 + i % 3) for i, d in enumerate(days)]
    bars[10] = Bar(days[10], 16.0, high=16.5, low=0.0)  # Yahoo's bad print
    q = summarize(bars, "vol")
    assert q["lo"] == 14.0
    assert q["hi"] == 19.0


def test_52_week_range_window_is_one_year():
    old = Bar(date(2025, 1, 2), 1.0, 1.0, 1.0)
    recent = [Bar(d, 10.0, 11.0, 9.0) for d in weekdays(date(2026, 9, 1), 5)]
    q = summarize([old, *recent], "price")
    assert q["lo"] == 9.0


def test_spark_covers_a_month():
    bars = [Bar(d, float(i)) for i, d in enumerate(weekdays(date(2026, 6, 1), 80))]
    q = summarize(bars, "price")
    first = date.fromisoformat(q["spark"][0][0])
    assert date.fromisoformat(q["date"]) - first <= timedelta(days=31)
    assert len(q["spark"]) >= 20


def test_non_finite_closes_dropped_and_unsorted_input_ok():
    days = weekdays(date(2026, 9, 1), 5)
    bars = [Bar(days[3], 13.0), Bar(days[0], 10.0), Bar(days[4], math.nan), Bar(days[1], 11.0), Bar(days[2], 12.0)]
    q = summarize(bars, "price")
    assert q["last"] == 13.0 and q["prev"] == 12.0


def test_empty_history():
    assert summarize([], "price") is None


def test_merge_live_replaces_same_day_and_appends_new_day():
    d1, d2 = date(2026, 10, 1), date(2026, 10, 2)
    bars = [Bar(d1, 100.0, 101.0, 99.0)]
    same = merge_live(bars, 102.5, d1)
    assert same[-1] == Bar(d1, 102.5, 102.5, 99.0)
    nxt = merge_live(bars, 98.0, d2)
    assert [b.day for b in nxt] == [d1, d2] and nxt[-1].close == 98.0
    assert merge_live(bars, 98.0, date(2026, 9, 30)) == bars
    assert merge_live(bars, None, d2) == bars
