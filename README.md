# Market Dashboard

A daily catch-up on the market: Market, Headlines, Watchlist, then Themes. Vocabulary is in
`CONTEXT.md`; why it runs on Vercel with Neon and yfinance is in `docs/adr/0001-*`.

- `app/`: the FastAPI backend (Vercel entrypoint `app.main:app`)
- `public/`: the page (`index.html`, `app.js`, `styles.css`), served by Vercel's CDN
- `scripts/init_db.py`: creates the tables and the starting Groups on an empty database

## Run locally

```sh
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8765   # http://localhost:8765
.venv/bin/python -m pytest
```

`.env` (git- and Vercel-ignored) holds `DATABASE_URL`, pointing at the Neon `dev` branch,
plus a local `DASHBOARD_PASSWORD` and `SESSION_SECRET`.

## Deploy

Live at https://market-dashboard-nine-zeta.vercel.app (Vercel project
`yuxiang-jack-zhangs-projects/market-dashboard`). Neon project `market-dashboard`
(`billowing-art-43253745`): branch `main` is production, `dev` is for local work. Vercel needs
three environment variables:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the `main` branch's pooled connection string |
| `DASHBOARD_PASSWORD` | the one password that unlocks Edit |
| `SESSION_SECRET` | a long random string; changing it logs every device out |

```sh
npx vercel login
npx vercel link                      # once, creates the project
npx vercel env add DATABASE_URL production   # and the other two
npx vercel deploy --prod
```

## Checking whether Yahoo tolerates Vercel

Each function instance logs its upstream fetches to the `fetch_log` table every 15 minutes, and
immediately when a fetch fails. Logged in, open `/api/diagnostics?hours_back=24` to see refreshes,
failures and throttles. ADR 0001 says what to do if Yahoo starts refusing.
