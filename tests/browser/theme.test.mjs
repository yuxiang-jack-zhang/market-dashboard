import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { launch, open, phone, pause } from "./helpers.mjs";

let browser;
before(async () => (browser = await launch()));
after(() => browser?.close());

const read = (page) => page.evaluate(() => ({
  forced: document.documentElement.dataset.theme ?? null,
  saved: localStorage.getItem("md-theme"),
  bg: getComputedStyle(document.body).backgroundColor,
}));
const BG = { light: "rgb(255, 255, 255)", dark: "rgb(0, 0, 0)" };

for (const [system, other] of [["light", "dark"], ["dark", "light"]]) {
  test(`system ${system}: toggle switches, is remembered, and switching back follows the system again`, async () => {
    const ctx = await browser.createBrowserContext(); // fresh localStorage
    const page = await open(ctx, { viewport: phone, theme: system });
    assert.deepEqual(await read(page), { forced: null, saved: null, bg: BG[system] });

    await page.click("#theme-btn");
    await pause(500); // cross-fade
    assert.deepEqual(await read(page), { forced: other, saved: other, bg: BG[other] });

    await page.reload({ waitUntil: "networkidle0" });
    assert.deepEqual(await read(page), { forced: other, saved: other, bg: BG[other] });

    await page.click("#theme-btn");
    await pause(500);
    assert.deepEqual(await read(page), { forced: null, saved: null, bg: BG[system] });
    assert.deepEqual(page.errors, []);
    await ctx.close();
  });
}
