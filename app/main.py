"""Market Dashboard: a FastAPI backend behind a static page.

Reading is public. Editing Groups needs the one password (see auth.py).

Quotes and Headlines are cached on Vercel's CDN, so every open tab and device
shares one upstream fetch per minute. The page passes its Symbols in the
quotes URL, which keeps the hot path off the database: Neon is only touched to
save fallback quotes every few minutes and when a source fails.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator

from . import auth, config, db, headlines, hours, marketdata, symbols

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dashboard")

app = FastAPI(title="Market Dashboard", docs_url=None, redoc_url=None, openapi_url=None)

INDEX = config.ROOT / "public" / "index.html"
MAX_SYMBOLS = 150
SNAPSHOT_EVERY = 15 * 60  # seconds between fallback-quote saves per instance


def cdn_cache(response: Response, seconds: int, swr: int) -> None:
    """Cache on Vercel's CDN only. Browsers always revalidate, so a poll never
    gets a stale copy from the browser's own cache (Chrome honours
    stale-while-revalidate in Cache-Control)."""
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    response.headers["Vercel-CDN-Cache-Control"] = (
        f"max-age={seconds}, stale-while-revalidate={swr}, stale-if-error=86400"
    )


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@app.exception_handler(db.NotConfigured)
@app.exception_handler(psycopg.OperationalError)
async def database_down(request: Request, exc: Exception):
    log.error("database unavailable: %s", exc)
    return JSONResponse({"detail": "The database is unavailable. Try again shortly."}, status_code=503,
                        headers={"Cache-Control": "no-store"})


def require_editor(request: Request) -> None:
    if not auth.valid_token(request.cookies.get(auth.COOKIE)):
        raise HTTPException(401, "Log in to edit.")
    # A custom header can't be sent cross-site without a CORS preflight, which this app never allows.
    if request.method not in ("GET", "HEAD") and request.headers.get("x-md") != "1":
        raise HTTPException(403, "Missing request header.")


Editor = Depends(require_editor)


# --- Page ---------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def index():
    if not INDEX.is_file():  # on Vercel, public/ may be served by the CDN only
        return RedirectResponse("/index.html", status_code=307)
    return FileResponse(INDEX, headers={"Cache-Control": "public, max-age=0, must-revalidate",
                                        "Vercel-CDN-Cache-Control": "max-age=300"})


# --- Login --------------------------------------------------------------------


class LoginBody(BaseModel):
    password: str = Field(max_length=200)


@app.get("/api/me")
def me(request: Request, response: Response):
    no_store(response)
    return {
        "editor": auth.valid_token(request.cookies.get(auth.COOKIE)),
        "editing_enabled": auth.editing_enabled(),
    }


@app.post("/api/login")
def login(body: LoginBody, request: Request, response: Response):
    no_store(response)
    if not auth.editing_enabled():
        raise HTTPException(503, "Editing isn't set up: DASHBOARD_PASSWORD is missing.")
    if not auth.check_password(body.password):
        time.sleep(0.75)  # slow down guessing
        raise HTTPException(401, "Wrong password.")
    secure = config.ON_VERCEL or request.url.scheme == "https"
    response.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.MAX_AGE, httponly=True,
                        secure=secure, samesite="lax", path="/")
    return {"editor": True}


@app.post("/api/logout")
def logout(response: Response):
    no_store(response)
    response.delete_cookie(auth.COOKIE, path="/")
    return {"editor": False}


# --- Groups -------------------------------------------------------------------


def _item_json(item: dict) -> dict:
    out = dict(item)
    out["key"] = symbols.key(item["source"], item["symbol"])
    band = symbols.PEG_BANDS.get(item["symbol"]) if item["kind"] == "peg" else None
    if band:
        out["band"] = list(band)
    return out


@app.get("/api/groups")
def get_groups(response: Response):
    no_store(response)
    with db.connect() as conn:
        groups = db.list_groups(conn)
    for g in groups:
        g["items"] = [_item_json(i) for i in g["items"]]
    return {"groups": groups, "subsections": list(symbols.SUBSECTIONS)}


class ThemeBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    note: str = Field("", max_length=500)

    @field_validator("name", "note")
    @classmethod
    def squash_spaces(cls, v: str) -> str:
        return " ".join(v.split())


class ThemePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    note: str | None = Field(None, max_length=500)

    @field_validator("name", "note")
    @classmethod
    def squash_spaces(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v is not None else None


@app.post("/api/themes", dependencies=[Editor])
def create_theme(body: ThemeBody, response: Response):
    no_store(response)
    if not body.name:
        raise HTTPException(422, "A Theme needs a name.")
    with db.connect() as conn:
        group = db.create_theme(conn, body.name, body.note)
    return {"group": {**group, "items": []}}


@app.patch("/api/groups/{group_id}", dependencies=[Editor])
def update_theme(group_id: int, body: ThemePatch, response: Response):
    no_store(response)
    if body.name == "":
        raise HTTPException(422, "A Theme needs a name.")
    with db.connect() as conn:
        group = db.update_theme(conn, group_id, body.name, body.note)
    if group is None:
        raise HTTPException(404, "No such Theme.")
    return {"group": group}


@app.delete("/api/groups/{group_id}", dependencies=[Editor])
def delete_theme(group_id: int, response: Response):
    no_store(response)
    with db.connect() as conn:
        if not db.delete_theme(conn, group_id):
            raise HTTPException(404, "No such Theme.")
    return {"deleted": group_id}


class ThemesOrder(BaseModel):
    ids: list[int] = Field(max_length=200)


@app.put("/api/themes/order", dependencies=[Editor])
def reorder_themes(body: ThemesOrder, response: Response):
    no_store(response)
    with db.connect() as conn:
        if not db.reorder_themes(conn, body.ids):
            raise HTTPException(409, "The Themes changed elsewhere. Reload and try again.")
    return {"ok": True}


class AddSymbol(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    subsection: str | None = None


@app.post("/api/groups/{group_id}/symbols", dependencies=[Editor])
def add_symbol(group_id: int, body: AddSymbol, response: Response):
    no_store(response)
    symbol = symbols.normalize(body.symbol)
    if not symbols.is_valid_format(symbol):
        # Probably a name ("SK Hynix"): offer the Yahoo symbols that match it.
        return JSONResponse(
            {"detail": f"{body.symbol.strip()!r} isn't a Yahoo symbol or FRED series ID.",
             "suggestions": marketdata.suggest(body.symbol.strip())},
            status_code=422, headers={"Cache-Control": "no-store"},
        )
    with db.connect() as conn:
        group = db.get_group(conn, group_id)
        if group is None:
            raise HTTPException(404, "No such Group.")
        if any(db.find_item(conn, group_id, src, symbol) for src in symbols.SOURCES):
            raise HTTPException(409, f"{symbol} is already in {group['name']}.")
    is_market = group["kind"] == "market"
    if is_market and body.subsection not in (None, "", *symbols.SUBSECTIONS):
        raise HTTPException(422, "Unknown Market subsection.")

    try:
        found = marketdata.lookup(symbol)
    except marketdata.SourceDown:
        raise HTTPException(503, "Yahoo and FRED didn't respond, so the Symbol couldn't be checked. Try again.")
    if found is None:
        return JSONResponse(
            {"detail": f"{symbol} wasn't found on Yahoo or FRED.", "suggestions": marketdata.suggest(body.symbol)},
            status_code=404, headers={"Cache-Control": "no-store"},
        )

    subsection = None
    if is_market:
        subsection = body.subsection or symbols.default_subsection(found.source, found.kind, found.instrument_type, found.name)
    with db.connect() as conn:
        db.upsert_symbol(
            conn, source=found.source, symbol=found.symbol, name=found.name,
            label=symbols.default_label(found.source, found.symbol, found.name), kind=found.kind,
            currency=found.currency, instrument_type=found.instrument_type, decimals=found.decimals,
        )
        try:
            item_id = db.add_item(conn, group_id, found.source, found.symbol, subsection)
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, f"{symbol} is already in {group['name']}.")
        item = db.get_item(conn, item_id)
    item.pop("group_id", None)
    return {"item": _item_json(item), "quote": marketdata.quote_from(found.history, found.kind)}


@app.delete("/api/groups/{group_id}/symbols/{item_id}", dependencies=[Editor])
def remove_symbol(group_id: int, item_id: int, response: Response):
    no_store(response)
    with db.connect() as conn:
        if not db.delete_item(conn, group_id, item_id):
            raise HTTPException(404, "That Symbol isn't in this Group.")
    return {"deleted": item_id}


class OrderItem(BaseModel):
    id: int
    subsection: str | None = None


class ItemsOrder(BaseModel):
    items: list[OrderItem] = Field(max_length=500)


@app.put("/api/groups/{group_id}/symbols/order", dependencies=[Editor])
def reorder_symbols(group_id: int, body: ItemsOrder, response: Response):
    no_store(response)
    with db.connect() as conn:
        group = db.get_group(conn, group_id)
        if group is None:
            raise HTTPException(404, "No such Group.")
        if group["kind"] == "market":
            if any(i.subsection not in symbols.SUBSECTIONS for i in body.items):
                raise HTTPException(422, "Every Market Symbol needs a subsection.")
            order = [(i.id, i.subsection) for i in body.items]
        else:
            order = [(i.id, None) for i in body.items]
        if not db.reorder_items(conn, group_id, order):
            raise HTTPException(409, "This Group changed elsewhere. Reload and try again.")
    return {"ok": True}


# --- Quotes -------------------------------------------------------------------


class _FetchStats:
    """Per-instance tally of upstream fetches, flushed to fetch_log periodically."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_flush = 0.0
        self.last_snapshot = 0.0
        self._reset()

    def _reset(self) -> None:
        self.refreshes = self.requested = self.failed = self.throttled = 0
        self.total_ms = 0
        self.detail: str | None = None

    def record(self, requested: int, errors: dict[str, str], ms: int) -> None:
        with self.lock:
            self.refreshes += 1
            self.requested += requested
            self.failed += len(errors)
            self.throttled += sum(1 for e in errors.values() if e == "throttled")
            self.total_ms += ms
            if errors:
                self.detail = ", ".join(f"{k}={v}" for k, v in sorted(errors.items())[:12])

    def take_log_row(self, force: bool) -> dict | None:
        with self.lock:
            now = time.time()
            due = now - self.last_flush >= (60 if force else SNAPSHOT_EVERY)
            if not self.refreshes or not due:
                return None
            row = {
                "host": "vercel" if config.ON_VERCEL else "local", "refreshes": self.refreshes,
                "requested": self.requested, "failed": self.failed, "throttled": self.throttled,
                "avg_ms": self.total_ms // self.refreshes, "detail": self.detail,
            }
            self.last_flush = now
            self._reset()
            return row

    def snapshot_due(self) -> bool:
        with self.lock:
            if time.time() - self.last_snapshot >= SNAPSHOT_EVERY:
                self.last_snapshot = time.time()
                return True
            return False


_stats = _FetchStats()


def parse_refs(raw: str) -> list[tuple[str, str, str]]:
    refs, seen = [], set()
    for token in filter(None, raw.split(",")):
        parts = token.split(":")
        if len(parts) != 3:
            raise HTTPException(422, f"Bad Symbol reference {token!r}; expected source:symbol:kind.")
        source, symbol, kind = parts[0], symbols.normalize(parts[1]), parts[2]
        if source not in symbols.SOURCES or kind not in ("price", "rate", "spread", "vol", "peg") \
                or not symbols.is_valid_format(symbol):
            raise HTTPException(422, f"Bad Symbol reference {token!r}.")
        if (source, symbol) not in seen:
            seen.add((source, symbol))
            refs.append((source, symbol, kind))
    if len(refs) > MAX_SYMBOLS:
        raise HTTPException(422, f"At most {MAX_SYMBOLS} Symbols per request.")
    return refs


@app.get("/api/quotes")
def get_quotes(response: Response, s: str = Query("", max_length=6000)):
    refs = parse_refs(s)
    now = datetime.now(timezone.utc)
    market = hours.status(now)
    started = time.perf_counter()
    quotes, errors = marketdata.fetch_quotes(refs)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _stats.record(len(refs), errors, elapsed_ms)

    stale: list[str] = []
    retryable = {k: v for k, v in errors.items() if v != "not_found"}
    log_row = _stats.take_log_row(force=bool(retryable))
    save_snapshot = bool(quotes) and _stats.snapshot_due()
    if retryable or log_row or save_snapshot:
        try:
            with db.connect() as conn:
                if retryable:
                    kinds = {symbols.key(src, sym): kind for src, sym, kind in refs}
                    wanted = [(*k.split(":", 1), kinds[k]) for k in retryable]
                    for k, q in db.load_quotes(conn, wanted).items():
                        quotes[k] = {**q, "stale": True}
                        stale.append(k)
                if save_snapshot:
                    by_key = {symbols.key(src, sym): (src, sym, kind) for src, sym, kind in refs}
                    db.save_quotes(conn, [
                        (*by_key[k], q, datetime.fromisoformat(q["fetched"]))
                        for k, q in quotes.items() if not q.get("stale")
                    ])
                if log_row:
                    db.log_fetch(conn, **log_row)
        except (db.NotConfigured, psycopg.Error) as e:
            log.warning("quote fallback/snapshot skipped: %s", e)

    if refs and not quotes:
        # Nothing to show. A 5xx lets the CDN keep serving its last good copy.
        return JSONResponse({"detail": "Quotes are unavailable right now.", "errors": errors},
                            status_code=503, headers={"Cache-Control": "no-store"})
    if retryable:
        cdn_cache(response, 15, 60)
    else:
        cdn_cache(response, 60 if market["state"] == "open" else 300, 600)
    return {
        "as_of": now.isoformat(),
        "market": market,
        "quotes": quotes,
        "errors": {k: v for k, v in errors.items() if k not in stale},
        "stale": stale,
    }


# --- Headlines ----------------------------------------------------------------


@app.get("/api/headlines")
def get_headlines(response: Response):
    items, failed = headlines.fetch()
    if not items:
        return JSONResponse({"detail": "Headlines are unavailable right now.", "failed": failed},
                            status_code=503, headers={"Cache-Control": "no-store"})
    cdn_cache(response, 300 if not failed else 60, 900)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "items": [h.to_json() for h in items],
        "failed": failed,
    }


# --- Diagnostics --------------------------------------------------------------


@app.get("/api/diagnostics", dependencies=[Editor])
def diagnostics(response: Response, hours_back: int = Query(24, ge=1, le=24 * 14)):
    """Upstream fetch outcomes, to judge whether Yahoo tolerates Vercel (ADR 0001)."""
    no_store(response)
    with db.connect() as conn:
        rows = db.recent_fetch_log(conn, hours_back)
    totals = {k: sum(r[k] for r in rows) for k in ("refreshes", "requested", "failed", "throttled")}
    return {"hours": hours_back, "totals": totals, "rows": rows}


# Locally, serve the page and its assets too. On Vercel the CDN serves public/.
if not config.ON_VERCEL:
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=config.ROOT / "public", html=True), name="public")
