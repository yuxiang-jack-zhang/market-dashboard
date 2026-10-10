// Shared setup: launch the installed Chrome, open the page, wait for prices.
import fs from "node:fs";
import puppeteer from "puppeteer-core";

export const BASE = process.env.BASE || "http://localhost:8765";
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

export const phone = { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
export const smallPhone = { width: 360, height: 740, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
export const desktop = { width: 1280, height: 900, deviceScaleFactor: 1 };

export function launch() {
  return puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-first-run", "--no-default-browser-check"] });
}

// Opens the page and waits until every Market tile shows a price. page.errors collects script errors.
export async function open(browser, { viewport = desktop, theme = "light", setup } = {}) {
  const page = await browser.newPage();
  page.errors = [];
  page.on("pageerror", (e) => page.errors.push(e.message));
  await page.setViewport(viewport);
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: theme }]);
  if (setup) await setup(page);
  await page.goto(BASE + "/", { waitUntil: "networkidle0", timeout: 45_000 });
  await waitForPrices(page);
  return page;
}

export function waitForPrices(page) {
  return page.waitForFunction(() => {
    const tiles = [...document.querySelectorAll(".tile-last")];
    return tiles.length > 5 && tiles.every((e) => e.textContent.trim() !== "");
  }, { timeout: 30_000 });
}

export const pause = (ms) => new Promise((r) => setTimeout(r, ms));

// DASHBOARD_PASSWORD from the environment, else from the repo's .env.
export function password() {
  if (process.env.DASHBOARD_PASSWORD) return process.env.DASHBOARD_PASSWORD;
  try {
    const line = fs.readFileSync(new URL("../../.env", import.meta.url), "utf8")
      .split("\n").find((l) => l.startsWith("DASHBOARD_PASSWORD="));
    return line?.slice("DASHBOARD_PASSWORD=".length).trim() || null;
  } catch {
    return null;
  }
}
