# Hosted on Vercel, Groups in Neon, prices from yfinance

The dashboard has to open on both Mac and phone, including while the laptop is asleep, so it runs on Vercel (FastAPI plus a static page) rather than as a local server or a claude.ai Artifact snapshot. Vercel can't write to its own files, so Groups are stored in Neon Postgres rather than a `groups.yaml`; Neon also has room for the Phase 2 holdings. Prices come from yfinance even though it's unofficial and Yahoo may throttle cloud IPs, because it is free and covers everything the Groups need (futures, `^VIX`, Korean listings, FX). FRED supplies the rates Yahoo lacks.

## Consequences

- yfinance from Vercel gets a one-day test first. If Yahoo blocks it, drop the 60-second refresh to refreshing on page load. If that still fails, switch to a keyed provider (Finnhub or Twelve Data), or move to a fixed-IP host such as Fly.io.
- The page is public to read. Editing and the Phase 2 holdings require one password.
