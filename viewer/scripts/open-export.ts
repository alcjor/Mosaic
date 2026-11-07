/**
 * Open a single-file export (`mosaic export`) from `file://` in Chromium through Playwright, with
 * networking blocked, and print what a reader sees as one JSON line (plan M3.8).
 *
 *     bun viewer/scripts/open-export.ts EXPORT.html QUERY NODE_ID TYPE [TEXT_QUERY TEXT_ID]
 *
 * It waits for the page to open the mosaic, searches QUERY by name and opens NODE_ID's node page,
 * searches TEXT_QUERY (words in the full text) and checks TEXT_ID is listed, then opens the table
 * of TYPE. Every request that is not to the file itself is refused and recorded. Playwright is
 * not a dependency: the agent environment provides it with its browser.
 */
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const [file, query, nodeId, type, textQuery, textId] = process.argv.slice(2);
if (!file || !query || !nodeId || !type) {
  console.error("usage: bun viewer/scripts/open-export.ts EXPORT.html QUERY NODE_ID TYPE [TEXT_QUERY TEXT_ID]");
  process.exit(2);
}
const url = pathToFileURL(file).href;
const require = createRequire(import.meta.url);
const { chromium } = require("playwright") as typeof import("playwright");
const browser = await chromium.launch();
const blocked: string[] = [];
const errors: string[] = [];
try {
  const context = await browser.newContext({ offline: true });
  await context.route("**/*", (route) => {
    const asked = route.request().url();
    if (asked === url || asked.startsWith(`${url}#`)) return route.continue();
    blocked.push(asked);
    return route.abort();
  });
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  const started = performance.now();
  await page.goto(url);
  const box = page.getByRole("searchbox", { name: "Search the mosaic" });
  const banner = page.locator('[role="alert"]');
  await page.waitForFunction(
    () => !(document.querySelector('input[type="search"]') as HTMLInputElement | null)?.disabled || document.querySelector('[role="alert"]') !== null,
    null,
    { timeout: 120_000 },
  );
  const readyMs = Math.round(performance.now() - started);
  const header = (await page.locator("header").innerText()).split("\n").map((s) => s.trim()).filter(Boolean);
  const alerts = await banner.allInnerTexts();
  if (alerts.length > 0) {
    console.log(JSON.stringify({ header, alerts, readyMs, blocked, errors }));
    process.exit(0);
  }
  const search = async (q: string) => {
    await box.fill(q);
    await box.press("Enter");
    const rows = page.locator('nav[aria-label="Results"] a[data-id]');
    await rows.first().waitFor();
    return rows.evaluateAll((as) => as.map((a) => ({ id: a.getAttribute("data-id"), match: a.getAttribute("data-match") })));
  };
  const results = await search(query);
  await page.locator(`nav[aria-label="Results"] a[data-id="${nodeId}"]`).click();
  const card = page.locator(`article[aria-label="${nodeId}"]`);
  await card.waitFor();
  const cardText = await card.innerText();
  const links = await page.locator('aside[aria-label="Links and sources"] a[data-id]').evaluateAll((as) => as.map((a) => a.getAttribute("data-id")));
  const textResults = textQuery ? await search(textQuery) : [];
  await page.locator(`nav[aria-label="Results"] a[data-type="${type}"]`).click();
  const table = page.locator(`section[aria-label="Table ${type}"]`);
  await table.locator("tbody a[data-id]").first().waitFor();
  const rows = await table.locator("tbody a[data-id]").evaluateAll((as) => as.map((a) => a.getAttribute("data-id")));
  const mode = await page.locator('[data-mode][aria-pressed="true"]').getAttribute("data-mode");
  console.log(JSON.stringify({ header, alerts, readyMs, results, card: cardText, links, textResults, textId, rows, mode, blocked, errors }));
} finally {
  await browser.close();
}
