"""Groups and Symbols in Neon Postgres.

Each request opens its own short connection through Neon's pooler; serverless
instances come and go too often for a client-side pool to pay off.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import config

SCHEMA = Path(__file__).with_name("schema.sql")


class NotConfigured(Exception):
    pass


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    url = config.database_url()
    if not url:
        raise NotConfigured("DATABASE_URL is not set")
    # prepare_threshold=None: Neon's pooler runs PgBouncer in transaction mode.
    with psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=10) as conn:
        yield conn


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text())


# --- Reading ------------------------------------------------------------------

_ITEM_COLUMNS = """
    gs.id, gs.group_id, gs.source, gs.symbol, gs.subsection, gs.position,
    s.name, s.label, s.kind, s.currency, s.instrument_type, s.decimals
"""


def list_groups(conn: psycopg.Connection) -> list[dict]:
    """Market, the Watchlist, then Themes in Jack's order; each with its Symbols."""
    groups = conn.execute(
        """
        SELECT id, kind, name, note, position FROM groups
        ORDER BY CASE kind WHEN 'market' THEN 0 WHEN 'watchlist' THEN 1 ELSE 2 END, position, id
        """
    ).fetchall()
    items = conn.execute(
        f"""
        SELECT {_ITEM_COLUMNS}
        FROM group_symbols gs JOIN symbols s USING (source, symbol)
        ORDER BY gs.group_id, gs.position, gs.id
        """
    ).fetchall()
    by_group: dict[int, list[dict]] = {g["id"]: [] for g in groups}
    for item in items:
        by_group[item.pop("group_id")].append(item)
    for g in groups:
        g["items"] = by_group[g["id"]]
    return groups


def get_group(conn: psycopg.Connection, group_id: int) -> dict | None:
    return conn.execute("SELECT id, kind, name, note, position FROM groups WHERE id = %s", (group_id,)).fetchone()


def get_item(conn: psycopg.Connection, item_id: int) -> dict | None:
    return conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM group_symbols gs JOIN symbols s USING (source, symbol) WHERE gs.id = %s",
        (item_id,),
    ).fetchone()


def find_item(conn: psycopg.Connection, group_id: int, source: str, symbol: str) -> dict | None:
    return conn.execute(
        "SELECT id FROM group_symbols WHERE group_id = %s AND source = %s AND symbol = %s",
        (group_id, source, symbol),
    ).fetchone()


# --- Editing ------------------------------------------------------------------


def upsert_symbol(
    conn: psycopg.Connection, *, source: str, symbol: str, name: str, label: str, kind: str,
    currency: str | None, instrument_type: str | None, decimals: int,
) -> None:
    """Record what a Symbol is. An existing label is kept, so a hand-set one survives."""
    conn.execute(
        """
        INSERT INTO symbols (source, symbol, name, label, kind, currency, instrument_type, decimals)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, symbol) DO UPDATE SET
            name = EXCLUDED.name, kind = EXCLUDED.kind, currency = EXCLUDED.currency,
            instrument_type = EXCLUDED.instrument_type, decimals = EXCLUDED.decimals,
            label = CASE WHEN symbols.label = '' THEN EXCLUDED.label ELSE symbols.label END
        """,
        (source, symbol, name, label, kind, currency, instrument_type, decimals),
    )


def add_item(conn: psycopg.Connection, group_id: int, source: str, symbol: str, subsection: str | None) -> int:
    """Append a Symbol to the end of a Group (or of its Market subsection)."""
    row = conn.execute(
        """
        INSERT INTO group_symbols (group_id, source, symbol, subsection, position)
        SELECT %s, %s, %s, %s, COALESCE(MAX(position) + 1, 0) FROM group_symbols WHERE group_id = %s
        RETURNING id
        """,
        (group_id, source, symbol, subsection, group_id),
    ).fetchone()
    return row["id"]


def delete_item(conn: psycopg.Connection, group_id: int, item_id: int) -> bool:
    cur = conn.execute("DELETE FROM group_symbols WHERE id = %s AND group_id = %s", (item_id, group_id))
    return cur.rowcount == 1


def reorder_items(conn: psycopg.Connection, group_id: int, order: list[tuple[int, str | None]]) -> bool:
    """Set a Group's order (and, for Market, each Symbol's subsection).

    `order` must name every Symbol in the Group exactly once.
    """
    with conn.transaction():
        current = {r["id"] for r in conn.execute(
            "SELECT id FROM group_symbols WHERE group_id = %s FOR UPDATE", (group_id,)
        ).fetchall()}
        ids = [i for i, _ in order]
        if len(ids) != len(set(ids)) or set(ids) != current:
            return False
        conn.execute(
            """
            UPDATE group_symbols AS g SET position = v.pos, subsection = v.sub
            FROM unnest(%s::bigint[], %s::int[], %s::text[]) AS v(id, pos, sub)
            WHERE g.id = v.id AND g.group_id = %s
            """,
            (ids, list(range(len(ids))), [s for _, s in order], group_id),
        )
    return True


def create_theme(conn: psycopg.Connection, name: str, note: str) -> dict:
    return conn.execute(
        """
        INSERT INTO groups (kind, name, note, position)
        SELECT 'theme', %s, %s, COALESCE(MAX(position) + 1, 0) FROM groups WHERE kind = 'theme'
        RETURNING id, kind, name, note, position
        """,
        (name, note),
    ).fetchone()


def update_theme(conn: psycopg.Connection, group_id: int, name: str | None, note: str | None) -> dict | None:
    return conn.execute(
        """
        UPDATE groups SET name = COALESCE(%s, name), note = COALESCE(%s, note)
        WHERE id = %s AND kind = 'theme'
        RETURNING id, kind, name, note, position
        """,
        (name, note, group_id),
    ).fetchone()


def delete_theme(conn: psycopg.Connection, group_id: int) -> bool:
    cur = conn.execute("DELETE FROM groups WHERE id = %s AND kind = 'theme'", (group_id,))
    return cur.rowcount == 1


def reorder_themes(conn: psycopg.Connection, ids: list[int]) -> bool:
    with conn.transaction():
        current = {r["id"] for r in conn.execute(
            "SELECT id FROM groups WHERE kind = 'theme' FOR UPDATE"
        ).fetchall()}
        if len(ids) != len(set(ids)) or set(ids) != current:
            return False
        conn.execute(
            """
            UPDATE groups AS g SET position = v.pos
            FROM unnest(%s::bigint[], %s::int[]) AS v(id, pos)
            WHERE g.id = v.id
            """,
            (ids, list(range(len(ids)))),
        )
    return True


# --- Quote fallback and fetch log -----------------------------------------------


def save_quotes(conn: psycopg.Connection, rows: list[tuple[str, str, str, dict, datetime]]) -> None:
    """Upsert (source, symbol, kind, quote, fetched_at) rows."""
    if not rows:
        return
    sources, syms, kinds, quotes, times = zip(*rows)
    conn.execute(
        """
        INSERT INTO quote_cache (source, symbol, kind, quote, fetched_at)
        SELECT * FROM unnest(%s::text[], %s::text[], %s::text[], %s::jsonb[], %s::timestamptz[])
        ON CONFLICT (source, symbol) DO UPDATE SET
            kind = EXCLUDED.kind, quote = EXCLUDED.quote, fetched_at = EXCLUDED.fetched_at
        """,
        (list(sources), list(syms), list(kinds), [Jsonb(q) for q in quotes], list(times)),
    )


def load_quotes(conn: psycopg.Connection, refs: list[tuple[str, str, str]]) -> dict[str, dict]:
    """Last good quotes for (source, symbol, kind) refs, keyed "source:symbol"."""
    if not refs:
        return {}
    sources, syms, kinds = zip(*refs)
    rows = conn.execute(
        """
        SELECT c.source, c.symbol, c.quote FROM quote_cache c
        JOIN unnest(%s::text[], %s::text[], %s::text[]) AS r(source, symbol, kind)
          ON c.source = r.source AND c.symbol = r.symbol AND c.kind = r.kind
        """,
        (list(sources), list(syms), list(kinds)),
    ).fetchall()
    return {f"{r['source']}:{r['symbol']}": r["quote"] for r in rows}


def log_fetch(conn: psycopg.Connection, *, host: str, refreshes: int, requested: int, failed: int,
              throttled: int, avg_ms: int | None, detail: str | None) -> None:
    conn.execute(
        """
        INSERT INTO fetch_log (host, refreshes, requested, failed, throttled, avg_ms, detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (host, refreshes, requested, failed, throttled, avg_ms, detail),
    )


def recent_fetch_log(conn: psycopg.Connection, hours: int = 24) -> list[dict]:
    return conn.execute(
        """
        SELECT at, host, refreshes, requested, failed, throttled, avg_ms, detail FROM fetch_log
        WHERE at > now() - make_interval(hours => %s) ORDER BY at DESC LIMIT 500
        """,
        (hours,),
    ).fetchall()
