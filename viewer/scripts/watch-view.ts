/**
 * Drive the page `mosaic view FILE --view VIEW` opened, in Chromium through Playwright, while
 * the view file is saved twice, and print what a reader sees as one JSON line (plan M3.7).
 *
 *     bun viewer/scripts/watch-view.ts --url URL --view VIEW --next NEXT --broken BROKEN
 *
 * It reads the page's type list as the first view file shapes it; saves NEXT's text over VIEW
 * and waits for the list to change, without reloading the page or restarting `mosaic view`;
 * then saves BROKEN's text over VIEW and waits for the page to show an error, reading the list
 * again. Playwright is not a dependency: the agent environment provides it with its browser.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const argv = process.argv.slice(2);
const option = (name: string): string => {
  const at = argv.indexOf(name);
  const value = at >= 0 ? argv[at + 1] : undefined;
  if (value === undefined) {
    console.error("usage: bun viewer/scripts/watch-view.ts --url URL --view VIEW --next NEXT --broken BROKEN");
    process.exit(2);
  }
  return value;
};
const url = option("--url");
const viewPath = option("--view");
const next = readFileSync(option("--next"), "utf8");
const broken = readFileSync(option("--broken"), "utf8");

const require = createRequire(import.meta.url);
const { chromium } = require("playwright") as typeof import("playwright");
const browser = await chromium.launch();
const errors: string[] = [];
try {
  const page = await browser.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  let loads = 0;
  page.on("load", () => loads++);
  await page.goto(url);
  const list = page.locator('nav[aria-label="Results"] a[data-type]');
  const read = () => list.evaluateAll((as) => as.map((a) => ({ type: a.getAttribute("data-type"), text: (a as HTMLElement).innerText.trim() })));
  await list.first().waitFor({ timeout: 120_000 });
  const first = await read();
  const theme = () => page.evaluate(() => document.documentElement.dataset.theme ?? "auto");
  const firstTheme = await theme();

  const saved = performance.now();
  writeFileSync(viewPath, next);
  const before = JSON.stringify(first);
  await page.waitForFunction(
    (b) => JSON.stringify([...document.querySelectorAll('nav[aria-label="Results"] a[data-type]')].map((a) => ({ type: a.getAttribute("data-type"), text: (a as HTMLElement).innerText.trim() }))) !== b,
    before,
    { timeout: 15_000 },
  );
  const reshapedMs = Math.round(performance.now() - saved);
  const second = await read();
  const secondTheme = await theme();

  writeFileSync(viewPath, broken);
  const alert = page.locator('[role="alert"]', { hasText: "view file:" });
  await alert.first().waitFor({ timeout: 15_000 });
  const error = await alert.first().innerText();
  const third = await read();
  const thirdTheme = await theme();
  console.log(JSON.stringify({ first, firstTheme, second, secondTheme, reshapedMs, error, third, thirdTheme, loads, errors }));
} finally {
  await browser.close();
}
