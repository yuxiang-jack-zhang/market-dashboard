"""Daily history from Yahoo (through yfinance) and FRED.

One Yahoo chart request per Symbol returns a year of daily bars plus the live
quote, which covers everything a row shows. FRED has no live data; its series
update once a day, so they're cached in-process for half an hour.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html import unescape

import requests

from . import config, symbols
from .stats import Bar, merge_live, summarize

log = logging.getLogger(__name__)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_PAGE = "https://fred.stlouisfed.org/series/{}"
# FRED's CDN stalls requests that send a browser or custom User-Agent but
# answers python-requests' default one, so no User-Agent is set here.
FRED_TTL = 30 * 60
YAHOO_TTL = 20  # collapses concurrent refreshes within one function instance
TIMEOUT = 8
WORKERS = 12


class NotFound(Exception):
    """The source has no such Symbol."""


class Throttled(Exception):
    """The source is rate-limiting us."""


@dataclass
class History:
    bars: list[Bar]
    name: str = ""
    currency: str | None = None
    instrument_type: str | None = None
    price_hint: int | None = None
    units: str | None = None
    quote_time: str | None = None  # last trade, ISO 8601 UTC
    fetched_at: float = field(default_factory=time.time)


_yf_module = None
_yf_lock = threading.Lock()


def _yf():
    global _yf_module
    with _yf_lock:
        if _yf_module is None:
            import yfinance

            yfinance.cache.set_cache_location(config.YF_CACHE_DIR)
            _yf_module = yfinance
    return _yf_module


def _float(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def yahoo_history(symbol: str) -> History:
    yf = _yf()
    ticker = yf.Ticker(symbol)
    try:
        df = ticker.history(
            period="1y", interval="1d", auto_adjust=False, actions=False,
            raise_errors=True, timeout=TIMEOUT,
        )
    except yf.exceptions.YFRateLimitError as e:
        raise Throttled(str(e)) from e
    except (
        yf.exceptions.YFPricesMissingError,
        yf.exceptions.YFTickerMissingError,
        yf.exceptions.YFTzMissingError,
        yf.exceptions.YFInvalidPeriodError,
    ) as e:
        raise NotFound(str(e)) from e
    except ValueError as e:  # e.g. a 12-character FRED ID mistaken for an ISIN
        raise NotFound(str(e)) from e
    if df is None or df.empty:
        raise NotFound(symbol)

    bars = []
    for ts, close, high, low in zip(df.index, df["Close"], df["High"], df["Low"]):
        close = _float(close)
        if close is not None:
            bars.append(Bar(ts.date(), close, _float(high), _float(low)))
    if not bars:
        raise NotFound(symbol)

    meta = ticker.history_metadata or {}
    quote_time = meta.get("regularMarketTime")
    quote_day = None
    if quote_time is not None and hasattr(quote_time, "date"):
        quote_day = quote_time.date()  # in the exchange's timezone, like the bars
        quote_time = quote_time.astimezone(timezone.utc).isoformat()
    else:
        quote_time = None
    bars = merge_live(bars, meta.get("regularMarketPrice"), quote_day)

    hint = meta.get("priceHint")
    return History(
        bars=bars,
        name=meta.get("longName") or meta.get("shortName") or symbol,
        currency=meta.get("currency"),
        instrument_type=meta.get("instrumentType"),
        price_hint=int(hint) if isinstance(hint, (int, float)) else None,
        quote_time=quote_time,
    )


def fred_history(series_id: str, start: date | None = None) -> History:
    start = start or (date.today() - timedelta(days=400))
    try:
        r = requests.get(FRED_CSV, params={"id": series_id, "cosd": start.isoformat()}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise RuntimeError(f"FRED unreachable: {type(e).__name__}") from e
    if r.status_code == 404:
        raise NotFound(series_id)
    if r.status_code == 429:
        raise Throttled("FRED 429")
    r.raise_for_status()
    if "csv" not in r.headers.get("content-type", ""):
        raise NotFound(series_id)
    rows = csv.reader(io.StringIO(r.text))
    header = next(rows, [])
    if len(header) < 2 or header[1].strip().upper() != series_id.upper():
        raise NotFound(series_id)
    bars = []
    for row in rows:
        if len(row) < 2 or row[1].strip() in ("", "."):
            continue  # FRED leaves holidays blank
        value = _float(row[1])
        if value is not None:
            bars.append(Bar(date.fromisoformat(row[0]), value))
    if not bars:
        raise NotFound(series_id)
    return History(bars=bars, name=series_id)


_OG_TITLE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"')
_UNITS = re.compile(r'class="series-meta-value-units"[^>]*>\s*([^<]+?)\s*<')


def fred_info(series_id: str) -> tuple[str, str]:
    """A series' title and units, scraped from its FRED page (best effort)."""
    try:
        r = requests.get(FRED_PAGE.format(series_id), timeout=TIMEOUT)
    except requests.RequestException:
        return series_id, ""
    if r.status_code != 200:
        return series_id, ""
    title = _OG_TITLE.search(r.text)
    units = _UNITS.search(r.text)
    return (unescape(title.group(1)).strip() if title else series_id, unescape(units.group(1)) if units else "")


# --- In-process caches --------------------------------------------------------

_cache: dict[str, History] = {}
_cache_lock = threading.Lock()


def _cached(k: str, ttl: float) -> History | None:
    with _cache_lock:
        h = _cache.get(k)
    return h if h and time.time() - h.fetched_at < ttl else None


def _store(k: str, h: History) -> History:
    with _cache_lock:
        _cache[k] = h
    return h


def history(source: str, symbol: str) -> History:
    k = symbols.key(source, symbol)
    if source == "fred":
        return _cached(k, FRED_TTL) or _store(k, fred_history(symbol))
    return _cached(k, YAHOO_TTL) or _store(k, yahoo_history(symbol))


# --- Quotes for the page ------------------------------------------------------


def quote_from(h: History, kind: str) -> dict | None:
    q = summarize(h.bars, kind)
    if q is None:
        return None
    q["time"] = h.quote_time
    q["fetched"] = datetime.fromtimestamp(h.fetched_at, timezone.utc).isoformat()
    return q


def classify_error(e: Exception) -> str:
    if isinstance(e, NotFound):
        return "not_found"
    if isinstance(e, Throttled):
        return "throttled"
    return "error"


def fetch_quotes(refs: list[tuple[str, str, str]]) -> tuple[dict[str, dict], dict[str, str]]:
    """Fetch (source, symbol, kind) refs in parallel.

    Returns quotes keyed "source:symbol", and an error code for each failure.
    """
    quotes: dict[str, dict] = {}
    errors: dict[str, str] = {}

    def one(ref):
        source, symbol, kind = ref
        return quote_from(history(source, symbol), kind)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {symbols.key(s, sym): pool.submit(one, (s, sym, kind)) for s, sym, kind in refs}
        for k, fut in futures.items():
            try:
                q = fut.result()
            except Exception as e:  # one bad Symbol must not sink the rest
                errors[k] = classify_error(e)
                log.warning("quote %s failed: %s: %s", k, type(e).__name__, str(e)[:200])
                continue
            if q is None:
                errors[k] = "not_found"
            else:
                quotes[k] = q
    return quotes, errors


# --- Checking a new Symbol ----------------------------------------------------


@dataclass
class Lookup:
    source: str
    symbol: str
    name: str
    kind: str
    currency: str | None
    instrument_type: str | None
    decimals: int
    history: History


class SourceDown(Exception):
    """Neither source could answer, so we can't say whether the Symbol exists."""


def lookup(symbol: str) -> Lookup | None:
    """Check Yahoo, then FRED. None means neither has it."""
    unsure = False
    try:
        h = yahoo_history(symbol)
    except NotFound:
        h = None
    except Exception as e:
        log.warning("yahoo lookup %s failed: %s", symbol, e)
        h, unsure = None, True
    if h is not None:
        kind = symbols.yahoo_kind(symbol, h.name)
        _store(symbols.key("yahoo", symbol), h)
        return Lookup(
            source="yahoo", symbol=symbol, name=h.name, kind=kind,
            currency=h.currency, instrument_type=h.instrument_type,
            decimals=symbols.decimals(kind, h.instrument_type, h.currency, h.price_hint, h.bars[-1].close),
            history=h,
        )

    try:
        h = fred_history(symbol)
    except NotFound:
        h = None
    except Exception as e:
        log.warning("fred lookup %s failed: %s", symbol, e)
        h, unsure = None, True
    if h is not None:
        title, units = fred_info(symbol)
        kind = symbols.fred_kind(title, units)
        h.name, h.units = title, units
        _store(symbols.key("fred", symbol), h)
        return Lookup(
            source="fred", symbol=symbol, name=title, kind=kind, currency=None,
            instrument_type=None, decimals=symbols.decimals(kind, None, None, 2, h.bars[-1].close),
            history=h,
        )

    if unsure:
        raise SourceDown(symbol)
    return None


def suggest(query: str, limit: int = 5) -> list[dict]:
    """Yahoo symbols that match a name, for when an added Symbol isn't found."""
    try:
        found = _yf().Search(query, max_results=limit, news_count=0, timeout=TIMEOUT).quotes
    except Exception as e:
        log.warning("yahoo search %r failed: %s", query, e)
        return []
    out = []
    for q in found or []:
        sym = q.get("symbol")
        if sym and symbols.is_valid_format(sym.upper()):
            out.append({
                "symbol": sym.upper(),
                "name": " ".join((q.get("longname") or q.get("shortname") or "").split()),
                "exchange": q.get("exchDisp") or q.get("exchange") or "",
            })
    return out[:limit]
