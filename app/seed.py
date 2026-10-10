"""The Groups the dashboard starts with (settled 2026-10-04). Edit them in the page afterwards."""

from __future__ import annotations

import logging

import psycopg

from . import db, marketdata, symbols

log = logging.getLogger(__name__)

# (subsection, symbol, label). Yahoo is tried first, then FRED, as for any new Symbol.
MARKET = [
    ("indices", "^GSPC", "S&P 500"),
    ("indices", "^NDX", "Nasdaq 100"),
    ("indices", "^DJI", "Dow Jones"),
    ("indices", "^RUT", "Russell 2000"),
    ("indices", "^VIX", "VIX"),
    ("rates", "DGS2", "2Y yield"),
    ("rates", "^TNX", "10Y yield"),
    ("rates", "T10Y2Y", "2s10s"),
    ("rates", "BAMLH0A0HYM2", "HY OAS"),
    ("fx", "DX-Y.NYB", "Dollar index"),
    ("fx", "GBPUSD=X", "GBPUSD"),
    ("fx", "JPY=X", "USDJPY"),
    ("fx", "HKD=X", "USDHKD"),
    ("commodities", "CL=F", "WTI crude"),
    ("commodities", "GC=F", "Gold"),
    ("commodities", "HG=F", "Copper"),
    ("crypto", "BTC-USD", "Bitcoin"),
]

WATCHLIST = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO"]

THEMES = [
    ("Memory", ["MU", "SNDK", "WDC", "STX", "000660.KS", "005930.KS"]),
    ("GTA 6", ["TTWO", "SONY", "MSFT"]),
    ("Biohacking", ["LLY", "NVO", "DXCM", "ABT", "HIMS"]),
    ("Data Center", ["NVDA", "AVGO", "ANET", "VRT", "ETN", "EQIX", "DLR", "CEG", "VST", "SMCI"]),
    ("Middle East War", ["LMT", "RTX", "NOC", "FRO", "EIS"]),
]


def _add(conn: psycopg.Connection, group_id: int, symbol: str, label: str | None = None,
         subsection: str | None = None) -> None:
    found = marketdata.lookup(symbol)
    if found is None:
        log.warning("seed: %s not found on Yahoo or FRED; skipped", symbol)
        return
    db.upsert_symbol(
        conn, source=found.source, symbol=found.symbol, name=found.name,
        label=label or symbols.default_label(found.source, found.symbol, found.name),
        kind=found.kind, currency=found.currency, instrument_type=found.instrument_type,
        decimals=found.decimals,
    )
    db.add_item(conn, group_id, found.source, found.symbol, subsection)
    log.info("seed: %-14s %-6s %-6s %s", found.symbol, found.source, found.kind, label or found.name)


def seed(conn: psycopg.Connection) -> bool:
    """Create the starting Groups if there are none yet. Returns whether it seeded."""
    if conn.execute("SELECT 1 FROM groups LIMIT 1").fetchone():
        return False
    market = conn.execute("INSERT INTO groups (kind, name) VALUES ('market', 'Market') RETURNING id").fetchone()["id"]
    for subsection, symbol, label in MARKET:
        _add(conn, market, symbol, label, subsection)
    watchlist = conn.execute("INSERT INTO groups (kind, name) VALUES ('watchlist', 'Watchlist') RETURNING id").fetchone()["id"]
    for symbol in WATCHLIST:
        _add(conn, watchlist, symbol)
    for name, members in THEMES:
        theme = db.create_theme(conn, name, "")
        for symbol in members:
            _add(conn, theme["id"], symbol)
    return True
