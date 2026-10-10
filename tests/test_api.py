"""API tests. The Theme lifecycle test runs against DATABASE_URL (the Neon dev
branch locally) and cleans up after itself; market data is faked throughout."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, db, main, marketdata
from app.stats import Bar

H = {"X-MD": "1"}
needs_db = pytest.mark.skipif(not config.database_url(), reason="DATABASE_URL not set")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(main._stats, "snapshot_due", lambda: False)
    monkeypatch.setattr(main._stats, "take_log_row", lambda force: None)
    return TestClient(main.app)


def login(client):
    r = client.post("/api/login", json={"password": "pw"})
    assert r.status_code == 200, r.text


def fake_lookup(symbol, name, kind="price"):
    d0 = date(2026, 9, 1)
    bars = [Bar(d0 + timedelta(days=i), 100.0 + i) for i in range(30)]
    return marketdata.Lookup(
        source="yahoo", symbol=symbol, name=name, kind=kind, currency="USD",
        instrument_type="EQUITY", decimals=2, history=marketdata.History(bars=bars),
    )


def test_me_and_login(client):
    assert client.get("/api/me").json() == {"editor": False, "editing_enabled": True}
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    login(client)
    assert client.get("/api/me").json()["editor"] is True
    client.post("/api/logout")
    assert client.get("/api/me").json()["editor"] is False


def test_editing_requires_login_and_header(client):
    assert client.post("/api/themes", json={"name": "X"}, headers=H).status_code == 401
    login(client)
    assert client.post("/api/themes", json={"name": "X"}).status_code == 403  # no X-MD header


def test_quotes_dedupes_refs_and_is_cdn_cached(client, monkeypatch):
    calls = []

    def fake_fetch(refs):
        calls.append(refs)
        return {"yahoo:MU": {"last": 1.0, "fetched": "2026-10-05T00:00:00+00:00"}}, {}

    monkeypatch.setattr(marketdata, "fetch_quotes", fake_fetch)
    r = client.get("/api/quotes", params={"s": "yahoo:mu:price,yahoo:MU:price"})
    assert r.status_code == 200
    assert calls == [[("yahoo", "MU", "price")]]
    assert r.headers["cache-control"] == "public, max-age=0, must-revalidate"
    assert r.headers["vercel-cdn-cache-control"].startswith("max-age=")
    body = r.json()
    assert body["quotes"]["yahoo:MU"]["last"] == 1.0
    assert body["market"]["state"] in ("open", "pre", "post", "closed")


@pytest.mark.parametrize("s", ["yahoo:MU", "nasdaq:MU:price", "yahoo:MU:weird", "yahoo:SK HYNIX:price"])
def test_quotes_rejects_bad_refs(client, s):
    assert client.get("/api/quotes", params={"s": s}).status_code == 422


def test_quotes_total_failure_is_503_and_uncached(client, monkeypatch):
    monkeypatch.setattr(marketdata, "fetch_quotes", lambda refs: ({}, {"yahoo:MU": "throttled"}))
    monkeypatch.setattr(db, "load_quotes", lambda conn, refs: {})
    r = client.get("/api/quotes", params={"s": "yahoo:MU:price"})
    assert r.status_code == 503
    assert r.headers["cache-control"] == "no-store"


def test_quotes_partial_failure_uses_fallback_and_short_cache(client, monkeypatch):
    monkeypatch.setattr(marketdata, "fetch_quotes", lambda refs: (
        {"yahoo:MU": {"last": 1.0, "fetched": "2026-10-05T00:00:00+00:00"}}, {"yahoo:NVDA": "error"}))
    monkeypatch.setattr(db, "load_quotes", lambda conn, refs: {"yahoo:NVDA": {"last": 2.0}})
    r = client.get("/api/quotes", params={"s": "yahoo:MU:price,yahoo:NVDA:price"})
    body = r.json()
    assert body["stale"] == ["yahoo:NVDA"]
    assert body["quotes"]["yahoo:NVDA"] == {"last": 2.0, "stale": True}
    assert body["errors"] == {}
    assert r.headers["vercel-cdn-cache-control"].startswith("max-age=15,")


@needs_db
def test_theme_lifecycle(client, monkeypatch):
    login(client)
    fakes = {"MU": fake_lookup("MU", "Micron Technology, Inc."), "NVDA": fake_lookup("NVDA", "NVIDIA Corporation")}
    monkeypatch.setattr(marketdata, "lookup", lambda s: fakes.get(s))
    monkeypatch.setattr(marketdata, "suggest", lambda q: [{"symbol": "000660.KS", "name": "SK hynix Inc.", "exchange": "Korea"}])

    r = client.post("/api/themes", json={"name": "  Pytest   theme ", "note": "temporary"}, headers=H)
    assert r.status_code == 200, r.text
    theme = r.json()["group"]
    assert theme["name"] == "Pytest theme" and theme["kind"] == "theme"
    gid = theme["id"]
    try:
        r = client.post(f"/api/groups/{gid}/symbols", json={"symbol": " mu "}, headers=H)
        assert r.status_code == 200, r.text
        mu = r.json()["item"]
        assert (mu["symbol"], mu["key"], mu["label"], mu["subsection"]) == ("MU", "yahoo:MU", "Micron Technology", None)
        assert r.json()["quote"]["last"] == 129.0

        assert client.post(f"/api/groups/{gid}/symbols", json={"symbol": "MU"}, headers=H).status_code == 409
        r = client.post(f"/api/groups/{gid}/symbols", json={"symbol": "SKHYNIX"}, headers=H)
        assert r.status_code == 404
        assert r.json()["suggestions"][0]["symbol"] == "000660.KS"
        r = client.post(f"/api/groups/{gid}/symbols", json={"symbol": "SK HYNIX"}, headers=H)
        assert r.status_code == 422
        assert r.json()["suggestions"][0]["symbol"] == "000660.KS"

        nvda = client.post(f"/api/groups/{gid}/symbols", json={"symbol": "NVDA"}, headers=H).json()["item"]
        r = client.put(f"/api/groups/{gid}/symbols/order", json={"items": [{"id": nvda["id"]}, {"id": mu["id"]}]}, headers=H)
        assert r.status_code == 200, r.text
        assert client.put(f"/api/groups/{gid}/symbols/order", json={"items": [{"id": mu["id"]}]}, headers=H).status_code == 409

        r = client.patch(f"/api/groups/{gid}", json={"name": "Renamed", "note": "why it matters"}, headers=H)
        assert r.json()["group"]["name"] == "Renamed"
        assert client.patch(f"/api/groups/{gid}", json={"name": "   "}, headers=H).status_code == 422

        groups = client.get("/api/groups").json()["groups"]
        mine = next(g for g in groups if g["id"] == gid)
        assert [i["symbol"] for i in mine["items"]] == ["NVDA", "MU"]
        assert mine["note"] == "why it matters"
        assert [g["kind"] for g in groups[:2]] == ["market", "watchlist"]

        themes = [g["id"] for g in groups if g["kind"] == "theme"]
        moved = [gid] + [t for t in themes if t != gid]
        assert client.put("/api/themes/order", json={"ids": moved}, headers=H).status_code == 200
        after = [g["id"] for g in client.get("/api/groups").json()["groups"] if g["kind"] == "theme"]
        assert after == moved
        assert client.put("/api/themes/order", json={"ids": themes}, headers=H).status_code == 200

        market = groups[0]["id"]
        assert client.delete(f"/api/groups/{market}", headers=H).status_code == 404  # not a Theme
        assert client.patch(f"/api/groups/{market}", json={"name": "X"}, headers=H).status_code == 404

        assert client.delete(f"/api/groups/{gid}/symbols/{mu['id']}", headers=H).status_code == 200
        assert client.delete(f"/api/groups/{gid}/symbols/{mu['id']}", headers=H).status_code == 404
    finally:
        assert client.delete(f"/api/groups/{gid}", headers=H).status_code == 200
    assert all(g["id"] != gid for g in client.get("/api/groups").json()["groups"])


@needs_db
def test_market_symbols_get_a_subsection(client, monkeypatch):
    login(client)
    market = client.get("/api/groups").json()["groups"][0]
    assert market["kind"] == "market"
    eth = fake_lookup("ETH-USD", "Ethereum USD")
    eth.instrument_type = "CRYPTOCURRENCY"
    monkeypatch.setattr(marketdata, "lookup", lambda s: eth if s == "ETH-USD" else None)
    r = client.post(f"/api/groups/{market['id']}/symbols", json={"symbol": "ETH-USD"}, headers=H)
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    try:
        assert item["subsection"] == "crypto"
        bad = [{"id": i["id"], "subsection": "nowhere"} for i in market["items"]] + [{"id": item["id"], "subsection": "crypto"}]
        assert client.put(f"/api/groups/{market['id']}/symbols/order", json={"items": bad}, headers=H).status_code == 422
    finally:
        client.delete(f"/api/groups/{market['id']}/symbols/{item['id']}", headers=H)
