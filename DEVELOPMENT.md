# Development

How to run, test, deploy and maintain the dashboard. For what it is, see the [README](README.md);
for why it runs on Vercel with Neon and yfinance, see [ADR 0001](docs/adr/0001-hosted-on-vercel-with-neon-and-yfinance.md).

## Layout

- `app/`: the FastAPI backend (Vercel entrypoint `app.main:app`)
  - `main.py` routes, `marketdata.py` Yahoo and FRED, `headlines.py` feeds, `hours.py` NYSE calendar,
    `stats.py` changes and σ, `symbols.py` kinds and labels, `auth.py` the login cookie, `db.py` and
    `schema.sql` Postgres
- `public/`: the page (`index.html`, `app.js`, `styles.css`), served by Vercel's CDN
- `scripts/init_db.py`: creates the tables and the starting Groups on an empty database
- `tests/`: pytest tests for the backend; `tests/browser/` drives the page in Chrome

## Run locally

```sh
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8765   # http://localhost:8765
```

`.env` (git- and Vercel-ignored) holds `DATABASE_URL`, pointing at the Neon `dev` branch, plus a local
`DASHBOARD_PASSWORD` and `SESSION_SECRET`. Restart the server after editing it; `--reload` only
watches `app/`. Changes under `public/` show on a browser reload.

## Tests

**Backend:** 50 tests, with market data faked. The Theme lifecycle test writes to `DATABASE_URL` and
cleans up after itself; it's skipped when that isn't set.

```sh
.venv/bin/python -m pytest
```

**Browser:** drives the real page in your installed Chrome (`puppeteer-core`, no browser download).
Start the local server first.

```sh
cd tests/browser && npm install   # once
npm test
```

| File | Checks |
|---|---|
| `layout.test.mjs` | no sideways scroll and no price running into its change, from 360px to 1280px; dark mode; tap-to-expand on a phone; the compact date in the bar |
| `theme.test.mjs` | the light/dark toggle switches, is remembered, and returns to following the system |
| `stale.test.mjs` | fakes failed refreshes: the banner names the Symbols, highlights them and links to them |
| `edit.test.mjs` | login, adding and removing Symbols, suggestions for a wrong symbol, a Theme's lifecycle, sorting |

`edit.test.mjs` logs in with `DASHBOARD_PASSWORD` (from the environment, else `.env`) and edits the
Groups for real, so point it only at the local server. It removes what it added, even if a step fails,
and skips itself when there's no password. Set `BASE` to test another URL, and `CHROME` if Chrome isn't
in `/Applications`.

## Deploy

Live at https://market-dashboard-nine-zeta.vercel.app (Vercel project
`yuxiang-jack-zhangs-projects/market-dashboard`, connected to this GitHub repo).

- **Push to `main`:** Vercel builds and replaces the live site in a minute or two.
- **Push any other branch:** Vercel builds a preview at
  `market-dashboard-git-<branch>-yuxiang-jack-zhangs-projects.vercel.app`, visible only when signed in
  to Vercel. Previews use the Neon `dev` branch, so editing there never touches the real Groups.
- **Something broke:** in the Vercel dashboard, Deployments → Instant Rollback.
- **Settings changed, no code change:** Deployments → ⋯ → Redeploy. A deployment keeps the settings it
  was built with.
- **Deploying without Git:** `npx vercel deploy` (preview) or `npx vercel deploy --prod` uploads the
  local folder as it is, uncommitted changes included.

Neon project `market-dashboard` (`billowing-art-43253745`) has two branches: `main` is production, `dev`
is for previews and local work. Each Vercel environment has its own copy of these settings, all stored
as secrets that can't be read back:

| Variable | Production | Preview |
|---|---|---|
| `DATABASE_URL` | Neon `main`, pooled | Neon `dev`, pooled |
| `DASHBOARD_PASSWORD` | the one password that unlocks Edit | same idea; Edit is off on previews without it |
| `SESSION_SECRET` | a long random string | a different random string |

### Changing the password

```sh
npx vercel env add DASHBOARD_PASSWORD production --sensitive --force   # paste the new one
```

Then redeploy, either by pushing to `main` or with Redeploy in the dashboard. Use `preview`, or
`production,preview`, for previews. Devices that are already logged in stay logged in, because the
login cookie is signed with `SESSION_SECRET`. To log every device out, replace that too:

```sh
openssl rand -base64 32 | npx vercel env add SESSION_SECRET production --sensitive --force
```

To check a password took effect, open the site in a private window (your normal one may still have a
login cookie) and log in with it.

### Setting up from scratch

```sh
npx vercel login
npx vercel link                                          # creates the project
npx vercel env add DATABASE_URL production --sensitive   # and the other variables above
npx vercel git connect                                   # deploy on push
DATABASE_URL=... .venv/bin/python scripts/init_db.py     # tables and starting Groups
```

## Checking whether Yahoo tolerates Vercel

Each function instance logs its upstream fetches to the `fetch_log` table every 15 minutes, and
immediately when a fetch fails. Logged in, open `/api/diagnostics?hours_back=24` to see refreshes,
failures and throttles. ADR 0001 says what to do if Yahoo starts refusing.
