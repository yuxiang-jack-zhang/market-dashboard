"""Turn a Symbol's daily history into what a row shows.

Every change is expressed in the unit the Symbol's kind calls for:

- price, peg: percent
- rate, spread: basis points (the series are quoted in percent)
- vol: index points (VIX and friends)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

KINDS = ("price", "rate", "spread", "vol", "peg")

TYPICAL_WINDOW = 20  # sessions used for a Symbol's typical daily move
UNUSUAL_Z = 2.0  # a day move this many typical moves away gets shaded


@dataclass(frozen=True)
class Bar:
    day: date
    close: float
    high: float | None = None
    low: float | None = None


def change(new: float | None, ref: float | None, kind: str) -> float | None:
    if new is None or ref is None:
        return None
    if kind in ("rate", "spread"):
        return (new - ref) * 100.0
    if kind == "vol":
        return new - ref
    if ref == 0:
        return None
    return (new / ref - 1.0) * 100.0


def _finite(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _range_bounds(bar: Bar) -> tuple[float, float]:
    """The bar's low and high, falling back to the close for bad prints.

    Yahoo occasionally reports a 0.0 low for indices like ^VIX and ^TNX.
    """
    lo = bar.low if bar.low is not None and 0 < bar.low <= bar.close and bar.low >= bar.close * 0.5 else bar.close
    hi = bar.high if bar.high is not None and bar.close <= bar.high <= bar.close * 2 else bar.close
    return lo, hi


def summarize(bars: list[Bar], kind: str) -> dict | None:
    """Last value plus day, week and YTD changes, sparkline and 52-week range.

    `bars` are daily closes in any order; non-finite closes are dropped. The
    last bar is taken as the latest value (live, if the session is running).
    """
    clean = sorted(
        (b for b in bars if _finite(b.close) is not None),
        key=lambda b: b.day,
    )
    if not clean:
        return None
    last = clean[-1]
    prev = clean[-2] if len(clean) > 1 else None

    week_cutoff = last.day - timedelta(days=7)
    week_ref = next((b for b in reversed(clean) if b.day <= week_cutoff), None)
    year_start = date(last.day.year, 1, 1)
    ytd_ref = next((b for b in reversed(clean) if b.day < year_start), None)

    year_ago = last.day - timedelta(days=365)
    lows, highs = zip(*(_range_bounds(b) for b in clean if b.day > year_ago))

    moves = [change(b.close, a.close, kind) for a, b in zip(clean, clean[1:])]
    moves = [m for m in moves if m is not None]
    day = change(last.close, prev.close, kind) if prev else None
    history = moves[-(TYPICAL_WINDOW + 1):-1]
    typical = math.sqrt(sum(m * m for m in history) / len(history)) if len(history) >= 10 else None
    z = day / typical if day is not None and typical else None

    month_ago = last.day - timedelta(days=31)
    spark = [[b.day.isoformat(), round(b.close, 6)] for b in clean if b.day > month_ago]

    return {
        "last": last.close,
        "date": last.day.isoformat(),
        "prev": prev.close if prev else None,
        "d": day,
        "w": change(last.close, week_ref.close, kind) if week_ref else None,
        "ytd": change(last.close, ytd_ref.close, kind) if ytd_ref else None,
        "typical": typical,
        "z": z,
        "unusual": z is not None and abs(z) >= UNUSUAL_Z,
        "lo": min(lows),
        "hi": max(highs),
        "spark": spark,
    }


def merge_live(bars: list[Bar], price: float | None, day: date | None) -> list[Bar]:
    """Fold the live quote into the daily bars.

    Yahoo's daily bars can lag the live price for a few minutes after a session
    opens; without this, "day %" would compare yesterday to the day before.
    """
    price = _finite(price)
    if price is None or day is None or not bars:
        return bars
    last = bars[-1]
    if day == last.day:
        hi = max(last.high, price) if last.high is not None else None
        lo = min(last.low, price) if last.low is not None else None
        return [*bars[:-1], Bar(day, price, hi, lo)]
    if day > last.day:
        return [*bars, Bar(day, price, price, price)]
    return bars
