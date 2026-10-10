-- Market Dashboard schema. Every statement is idempotent; scripts/init_db.py runs it.

CREATE TABLE IF NOT EXISTS symbols (
  source          TEXT NOT NULL CHECK (source IN ('yahoo', 'fred')),
  symbol          TEXT NOT NULL,
  name            TEXT NOT NULL DEFAULT '',
  label           TEXT NOT NULL DEFAULT '',
  kind            TEXT NOT NULL DEFAULT 'price' CHECK (kind IN ('price', 'rate', 'spread', 'vol', 'peg')),
  currency        TEXT,
  instrument_type TEXT,
  decimals        SMALLINT NOT NULL DEFAULT 2,
  PRIMARY KEY (source, symbol)
);

CREATE TABLE IF NOT EXISTS groups (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind       TEXT NOT NULL CHECK (kind IN ('market', 'watchlist', 'theme')),
  name       TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
  note       TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
  position   INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Market and the Watchlist each exist exactly once; Themes come and go.
CREATE UNIQUE INDEX IF NOT EXISTS groups_one_market_one_watchlist ON groups (kind) WHERE kind <> 'theme';

CREATE TABLE IF NOT EXISTS group_symbols (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  group_id   BIGINT NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
  source     TEXT NOT NULL,
  symbol     TEXT NOT NULL,
  -- Only Market Symbols sit in a subsection.
  subsection TEXT CHECK (subsection IN ('indices', 'rates', 'fx', 'commodities', 'crypto')),
  position   INTEGER NOT NULL DEFAULT 0,
  added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (source, symbol) REFERENCES symbols (source, symbol),
  UNIQUE (group_id, source, symbol)
);

-- The last good quote per Symbol, shown (marked stale) when its source fails.
CREATE TABLE IF NOT EXISTS quote_cache (
  source     TEXT NOT NULL,
  symbol     TEXT NOT NULL,
  kind       TEXT NOT NULL,
  quote      JSONB NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (source, symbol)
);

-- Upstream fetch outcomes, aggregated per function instance, to judge whether
-- Yahoo tolerates requests from Vercel (ADR 0001).
CREATE TABLE IF NOT EXISTS fetch_log (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  host        TEXT NOT NULL,
  refreshes   INTEGER NOT NULL,
  requested   INTEGER NOT NULL,
  failed      INTEGER NOT NULL,
  throttled   INTEGER NOT NULL,
  avg_ms      INTEGER,
  detail      TEXT
);
