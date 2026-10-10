// Fakes failed refreshes by rewriting the /api/quotes response in the browser.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { launch, open, desktop, phone, pause } from "./helpers.mjs";

let browser;
before(async () => (browser = await launch()));
after(() => browser?.close());

async function breakQuotes(page) {
  await page.setRequestInterception(true);
  page.on("request", async (req) => {
    if (!req.url().includes("/api/quotes")) return req.continue();
    const r = await fetch(req.url()).then((x) => x.json());
    const keys = Object.keys(r.quotes);
    const stale = [keys.find((k) => k === "fred:BAMLH0A0HYM2"), keys.find((k) => k === "yahoo:WDC")];
    for (const k of stale) r.quotes[k] = { ...r.quotes[k], stale: true, fetched: new Date(Date.now() - 3600e3).toISOString() };
    delete r.quotes["yahoo:TSLA"];
    Object.assign(r, { stale, errors: { "yahoo:TSLA": "throttled" } });
    req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(r) });
  });
}

for (const [name, viewport] of [["desktop", desktop], ["phone", phone]]) {
  test(`${name}: the notice names the Symbols, which are highlighted and reachable`, async () => {
    const page = await open(browser, { viewport, setup: breakQuotes });
    await page.waitForFunction(() => !document.querySelector("#notice").hidden);
    assert.equal(await page.$eval("#notice", (e) => e.textContent),
      "Couldn't refresh HY OAS, WDC; showing their last saved prices. No data for TSLA.");

    const marked = await page.$$eval(".stale, .missing", (els) => els.map((e) => `${e.dataset.key} ${e.classList.contains("stale") ? "stale" : "missing"}`).sort());
    assert.ok(marked.includes("fred:BAMLH0A0HYM2 stale"));
    assert.ok(marked.includes("yahoo:WDC stale"));
    assert.ok(marked.includes("yahoo:TSLA missing"));
    assert.equal(await page.$eval('[data-key="yahoo:WDC"] .stale-mark', (e) => e.textContent), "!");

    const jumps = await page.$$("#notice .jump");
    await jumps[1].click(); // WDC
    await pause(800);
    const wdc = await page.$eval('[data-key="yahoo:WDC"].flash', (e) => {
      const r = e.getBoundingClientRect();
      return r.top >= 0 && r.bottom <= innerHeight;
    });
    assert.equal(wdc, true, "WDC should be flashed and on screen");
    assert.deepEqual(page.errors, []);
    await page.close();
  });
}
