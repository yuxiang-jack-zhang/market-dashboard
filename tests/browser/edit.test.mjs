// Logs in and edits Groups for real: run it against the local server (Neon dev branch).
// Anything it adds is removed again, even if a step fails.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { launch, open, password, BASE } from "./helpers.mjs";

const PASSWORD = password();
const THEME = "E2E test theme";
const skip = !PASSWORD && "no DASHBOARD_PASSWORD in the environment or .env";
let browser, page;

before(async () => {
  if (skip) return;
  browser = await launch();
  page = await open(browser);
  page.on("dialog", (d) => d.accept());
});

after(async () => {
  if (skip) return;
  await browser?.close();
  await cleanUp();
});

async function cleanUp() {
  const H = { "Content-Type": "application/json", "X-MD": "1" };
  const login = await fetch(`${BASE}/api/login`, { method: "POST", headers: H, body: JSON.stringify({ password: PASSWORD }) });
  const cookie = login.headers.get("set-cookie")?.split(";")[0];
  if (!cookie) return;
  const { groups } = await fetch(`${BASE}/api/groups`).then((r) => r.json());
  for (const g of groups) {
    if (g.name === THEME) await fetch(`${BASE}/api/groups/${g.id}`, { method: "DELETE", headers: { ...H, cookie } });
    if (g.kind === "market") {
      for (const i of g.items.filter((i) => i.symbol === "ETH-USD")) {
        await fetch(`${BASE}/api/groups/${g.id}/symbols/${i.id}`, { method: "DELETE", headers: { ...H, cookie } });
      }
    }
  }
}

test("a wrong password is refused", { skip }, async () => {
  await page.click("#login-btn");
  await page.type("#login-form input[name=password]", "wrong-password");
  await page.click("#login-form button[type=submit]");
  await page.waitForSelector("#login-error:not([hidden])");
  assert.equal(await page.$eval("#login-error", (e) => e.textContent), "Wrong password.");
});

test("the right password turns on editing", { skip }, async () => {
  await page.$eval("#login-form input[name=password]", (e) => (e.value = ""));
  await page.type("#login-form input[name=password]", PASSWORD);
  await page.click("#login-form button[type=submit]");
  await page.waitForSelector("body.editing");
  assert.ok((await page.$$("form.add")).length >= 2);
});

test("a Symbol added to Market lands in its subsection", { skip }, async () => {
  const form = "#market-body form.add";
  await page.type(`${form} input`, "eth-usd");
  await page.click(`${form} button[type=submit]`);
  await page.waitForSelector('#market-body .tiles[data-sub="crypto"] .tile[data-key="yahoo:ETH-USD"]', { timeout: 30_000 });
});

test("a company name instead of a symbol gets suggestions", { skip }, async () => {
  const form = "#watchlist-body form.add";
  await page.type(`${form} input`, "SKHYNIX");
  await page.click(`${form} button[type=submit]`);
  await page.waitForSelector(`${form} .add-msg.error`, { timeout: 30_000 });
  assert.match(await page.$eval(`${form} .add-msg`, (e) => e.textContent), /wasn't found/);
  assert.ok((await page.$$(`${form} .suggestions button`)).length > 0);
});

test("a Theme can be created, filled and deleted", { skip }, async () => {
  await page.type(".new-theme input[name=name]", THEME);
  await page.type(".new-theme input[name=note]", "made by the browser tests");
  await page.click(".new-theme button[type=submit]");
  await page.waitForFunction((n) => [...document.querySelectorAll(".theme input.name")].some((i) => i.value === n), {}, THEME);
  const sel = await page.evaluate((n) => {
    const sec = [...document.querySelectorAll(".theme")].find((s) => s.querySelector("input.name")?.value === n);
    return `.theme[data-gid="${sec.dataset.gid}"]`;
  }, THEME);
  await page.type(`${sel} form.add input`, "QQQ");
  await page.click(`${sel} form.add button[type=submit]`);
  await page.waitForSelector(`${sel} tbody.item[data-key="yahoo:QQQ"]`, { timeout: 30_000 });
  await page.click(`${sel} .theme-head .del`);
  await page.waitForFunction((s) => !document.querySelector(s), {}, sel);
});

test("a Market Symbol can be removed", { skip }, async () => {
  await page.click('#market-body .tile[data-key="yahoo:ETH-USD"] .del');
  await page.waitForFunction(() => !document.querySelector('#market-body .tile[data-key="yahoo:ETH-USD"]'));
});

test("sorting cycles descending, ascending, then back to the saved order", { skip }, async () => {
  const order = () => page.$$eval("#watchlist-body tbody.item", (t) => t.map((x) => x.dataset.key));
  const saved = await order();
  await page.click("#watchlist-body th[data-col=d] button");
  assert.equal(await page.$eval("#watchlist-body table", (t) => t.classList.contains("sorted")), true);
  await page.click("#watchlist-body th[data-col=d] button");
  await page.click("#watchlist-body th[data-col=d] button");
  assert.deepEqual(await order(), saved);
});

test("Done turns editing off", { skip }, async () => {
  await page.click("#edit-btn");
  assert.equal(await page.$("body.editing"), null);
});
