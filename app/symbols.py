"""What kind of thing a Symbol is, and how it's labelled and displayed."""

from __future__ import annotations

import re

SOURCES = ("yahoo", "fred")
SUBSECTIONS = ("indices", "rates", "fx", "commodities", "crypto")

# Yahoo's Treasury yield indices are quoted in percent, so they move in bp.
YAHOO_YIELDS = {"^IRX", "^FVX", "^TNX", "^TYX"}
# Volatility indices move in points, not percent.
YAHOO_VOLS = {
    "^VIX", "^VIX1D", "^VIX9D", "^VIX3M", "^VIX6M", "^VIX1Y", "^VVIX", "^VXN",
    "^VXD", "^RVX", "^OVX", "^GVZ", "^MOVE", "^VXEEM", "^EVZ", "^VXTLT",
}
# Currencies held in a band, drawn as a bar across the band instead of a 52-week range.
PEG_BANDS = {"HKD=X": (7.75, 7.85)}

# A Yahoo symbol (MU, ^GSPC, 000660.KS, GBPUSD=X, BTC-USD, CL=F, DX-Y.NYB)
# or a FRED series ID (DGS2, BAMLH0A0HYM2). Case is normalised to upper.
SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9^=.\-]{0,23}$")


def normalize(raw: str) -> str:
    return raw.strip().upper()


def is_valid_format(symbol: str) -> bool:
    return bool(SYMBOL_RE.match(symbol))


def key(source: str, symbol: str) -> str:
    return f"{source}:{symbol}"


def yahoo_kind(symbol: str, name: str | None) -> str:
    if symbol in PEG_BANDS:
        return "peg"
    if symbol in YAHOO_YIELDS:
        return "rate"
    if symbol in YAHOO_VOLS or (symbol.startswith("^") and "volatility" in (name or "").lower()):
        return "vol"
    return "price"


def fred_kind(title: str | None, units: str | None) -> str:
    """Percent-unit series are rates; spreads between two rates show their level in bp."""
    if "percent" not in (units or "").lower():
        return "price"
    t = (title or "").lower()
    if "spread" in t or " minus " in t:
        return "spread"
    return "rate"


_FUTURE_MONTH = re.compile(r"\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2}$")
_CORP_SUFFIX = re.compile(
    r",?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Co\.,? Ltd\.?|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|A/S|AG|SE"
    r"|(?:and|&) Co(?:mpany|\.)?|Company|Co\.?|Holdings?|Group)$"
)


def clean_name(name: str | None) -> str:
    """'Micron Technology, Inc.' -> 'Micron Technology'; 'Crude Oil Nov 26' -> 'Crude Oil'."""
    if not name:
        return ""
    out = _FUTURE_MONTH.sub("", name.strip()).removesuffix(" (The)")
    for _ in range(3):  # 'Foo Holdings, Inc.' has two suffixes
        out = _CORP_SUFFIX.sub("", out).strip().rstrip(",")
    return out or name.strip()


def default_label(source: str, symbol: str, name: str | None) -> str:
    if source == "fred":
        return symbol
    return clean_name(name) or symbol


def default_subsection(source: str, kind: str, instrument_type: str | None, name: str | None) -> str:
    """Where a new Symbol lands in Market when no subsection is picked."""
    if source == "fred" or kind in ("rate", "spread"):
        return "rates"
    n = (name or "").lower()
    it = (instrument_type or "").upper()
    if it == "CURRENCY" or kind == "peg" or "dollar index" in n:
        return "fx"
    if it == "CRYPTOCURRENCY":
        return "crypto"
    if it == "FUTURE":
        if any(w in n for w in ("s&p", "nasdaq", "dow", "russell", "nikkei", "vix")):
            return "indices"
        if any(w in n for w in ("treasury", "t-note", "t-bond", "note", "bond")):
            return "rates"
        return "commodities"
    return "indices"


def decimals(kind: str, instrument_type: str | None, currency: str | None, price_hint: int | None, last: float | None) -> int:
    """How many decimals the last value shows with."""
    if kind in ("rate", "spread", "vol"):
        return 2
    it = (instrument_type or "").upper()
    value = abs(last or 0.0)
    if it == "CURRENCY" or kind == "peg":
        return 2 if value >= 20 else 4
    if value >= 100_000 or (currency in ("KRW", "JPY", "TWD", "IDR") and it in ("EQUITY", "ETF")):
        return 0
    if it == "CRYPTOCURRENCY" and value >= 1000:
        return 0
    if price_hint is not None and 0 <= price_hint <= 6:
        return int(price_hint)
    return 2
