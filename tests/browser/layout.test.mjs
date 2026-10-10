import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { launch, open, phone, smallPhone, desktop } from "./helpers.mjs";

let browser;
before(async () => (browser = await launch()));
after(() => browser?.close());

const widths = { desktop, laptop: { width: 1024, height: 800 }, tablet: { width: 700, height: 800 }, phone, "small phone": smallPhone };

for (const [name, viewport] of Object.entries(widths)) {
  test(`${name} (${viewport.width}px): no sideways scroll, no price running into its change`, async () => {
    const page = await open(browser, { viewport });
    const r = await page.evaluate(() => ({
      vw: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      // 7px of slack: the 2σ wash deliberately bleeds into the tile's padding.
      collisions: [...document.querySelectorAll(".tile-main")]
        .filter((e) => e.scrollWidth > e.clientWidth + 7).map((e) => e.textContent),
    }));
    assert.equal(r.scrollWidth, r.vw, "page scrolls sideways");
    assert.deepEqual(r.collisions, []);
    assert.deepEqual(page.errors, []);
    await page.close();
  });
}

test("dark mode follows the system", async () => {
  const page = await open(browser, { theme: "dark" });
  assert.equal(await page.$eval("body", (b) => getComputedStyle(b).backgroundColor), "rgb(0, 0, 0)");
  await page.close();
});

test("phone: tapping a row and a tile opens their details", async () => {
  const page = await open(browser, { viewport: phone });
  await page.tap("#watchlist-body tbody.item tr.main");
  await page.tap("#market-body .tile");
  await page.waitForSelector("#watchlist-body tr.detail .facts span");
  const facts = await page.$eval("#watchlist-body tr.detail .facts", (e) => e.innerText);
  assert.match(facts, /52W/);
  assert.equal(await page.$eval("#market-body .tile.open .tile-foot", (e) => getComputedStyle(e).display), "flex");
  await page.close();
});

test("the bar shows a compact date once the large one scrolls under it", async () => {
  const page = await open(browser);
  assert.equal(await page.$eval("body", (b) => b.classList.contains("scrolled")), false);
  await page.evaluate(() => window.scrollTo(0, 600));
  await page.waitForFunction(() => document.body.classList.contains("scrolled"));
  assert.notEqual(await page.$eval("#bar-title", (e) => e.textContent.trim()), "");
  await page.close();
});
