/**
 * Drive the built viewer (`viewer/dist`) in Chromium, through Playwright, on one mosaic, and
 * print what a reader sees as one JSON line. The page and the mosaic are served as static files
 * from a local port, with no query server: everything the page shows comes from the kit running
 * in it.
 *
 *     bun viewer/scripts/browse.ts FILE QUERY NODE_ID
 *     bun viewer/scripts/browse.ts --url URL QUERY NODE_ID
 *
 * With `--url`, it serves nothing and walks the page at URL once, as `mosaic view` opens it.
 *
 * Twice: once with the mosaic named in the address (`?mosaic=`), once picked with the page's
 * file chooser. Each time it types QUERY in the search box and presses Enter, opens NODE_ID from
 * the results, then opens the first link of its node page. The first time it also opens the
 * table of the type `Item`, sorts it by its last column both ways, filters it to values under 2,
 * and opens the remaining row's node page. Playwright is not a dependency: the
 * agent environment provides it with its browser (`require("playwright")`).
 */
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const given = process.argv.slice(2);
const pageUrl = given[0] === "--url" ? given[1] : undefined;
const [file, query, nodeId] = pageUrl === undefined ? given : given.slice(1);
if (!file || !query || !nodeId) {
  console.error("usage: bun viewer/scripts/browse.ts FILE QUERY NODE_ID | --url URL QUERY NODE_ID");
  process.exit(2);
}

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
if (pageUrl === undefined && !existsSync(join(dist, "index.html"))) throw new Error("build the viewer first: bun run build");
const types: Record<string, string> = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".wasm": "application/wasm",
};
const requests: string[] = [];
const server = Bun.serve({
  port: 0,
  fetch(request) {
    const path = decodeURIComponent(new URL(request.url).pathname);
    requests.push(`${request.method} ${path}`);
    if (path === `/${basename(file)}`) return new Response(readFileSync(file));
    const local = normalize(join(dist, path === "/" ? "index.html" : path));
    if (!local.startsWith(dist) || !existsSync(local)) return new Response("not found", { status: 404 });
    return new Response(readFileSync(local), { headers: { "content-type": types[extname(local)] ?? "application/octet-stream" } });
  },
});

const require = createRequire(import.meta.url);
const { chromium } = require("playwright") as typeof import("playwright");
const browser = await chromium.launch();

type Page = import("playwright").Page;

async function walk(page: Page) {
  const box = page.getByRole("searchbox", { name: "Search the mosaic" });
  await box.waitFor({ state: "visible" });
  await page.waitForFunction(() => !(document.querySelector('input[type="search"]') as HTMLInputElement).disabled);
  const header = (await page.locator("header").innerText()).split("\n").map((s) => s.trim()).filter(Boolean);
  await box.fill(query!);
  await box.press("Enter");
  const rows = page.locator('nav[aria-label="Results"] a[data-id]');
  await rows.first().waitFor();
  const results = await rows.evaluateAll((as) =>
    as.map((a) => ({ id: a.getAttribute("data-id"), match: a.getAttribute("data-match"), text: (a as HTMLElement).innerText })),
  );
  await page.locator(`nav[aria-label="Results"] a[data-id="${nodeId}"]`).click();
  const card = page.locator(`article[aria-label="${nodeId}"]`);
  await card.waitFor();
  const cardText = await card.innerText();
  const context = page.locator('aside[aria-label="Links and sources"]');
  const links = await context.locator("a[data-id]").evaluateAll((as) => as.map((a) => a.getAttribute("data-id")));
  const sources = await context.locator(".cite").allInnerTexts();
  const first = links[0];
  let opened: string | null = null;
  if (first) {
    await context.locator(`a[data-id="${first}"]`).first().click();
    await page.locator(`article[aria-label="${first}"]`).waitFor();
    opened = first;
  }
  return { header, results, card: cardText, links, sources, opened, hash: new URL(page.url()).hash };
}

/** The tables: open a type's table, sort it both ways, filter it, then open a row's node page. */
async function tables(page: Page, type: string) {
  const ids = (p: Page) => p.locator('section[aria-label^="Table"] tbody a[data-id]').evaluateAll((as) => as.map((a) => a.getAttribute("data-id")));
  const listed = await page.locator("a[data-type]").evaluateAll((as) => as.map((a) => a.getAttribute("data-type")));
  await page.locator(`a[data-type="${type}"]`).click();
  const table = page.locator(`section[aria-label="Table ${type}"]`);
  await table.locator("tbody a[data-id]").first().waitFor();
  const headers = await table.locator("thead th").allInnerTexts();
  const rows = await ids(page);
  const column = (await table.locator("thead a[data-column]").last().getAttribute("data-column"))!;
  await table.locator(`thead a[data-column="${column}"]`).click();
  await table.locator('th[aria-sort="ascending"] a[data-column]').waitFor();
  const ascending = await ids(page);
  await table.locator(`thead a[data-column="${column}"]`).click();
  await table.locator('th[aria-sort="descending"]').waitFor();
  const descending = await ids(page);
  await table.getByLabel("Column", { exact: true }).selectOption(column);
  await table.getByLabel("Operator", { exact: true }).selectOption("<");
  await table.getByLabel("Value kind", { exact: true }).selectOption("number");
  await table.getByLabel("Value", { exact: true }).fill("2");
  await table.getByRole("button", { name: "Filter" }).click();
  await table.locator('ul[aria-label="Filters"]').waitFor();
  await page.waitForFunction(() => document.querySelectorAll('section[aria-label^="Table"] tbody tr').length === 1);
  const filtered = await ids(page);
  const pager = await table.locator('nav[aria-label="Pages"]').innerText();
  const first = filtered[0]!;
  await table.locator(`tbody a[data-id="${first}"]`).click();
  await page.locator(`article[aria-label="${first}"]`).waitFor();
  return { listed, headers, rows, column, ascending, descending, filtered, pager, opened: first, hash: new URL(page.url()).hash };
}

if (pageUrl !== undefined) {
  try {
    const page = await browser.newPage();
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(pageUrl);
    console.log(JSON.stringify({ named: await walk(page), errors }));
  } finally {
    await browser.close();
    server.stop(true);
  }
  process.exit(0);
}

try {
  const page = await browser.newPage();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const started = performance.now();
  await page.goto(`http://localhost:${server.port}/?mosaic=${encodeURIComponent(basename(file))}`);
  const named = await walk(page);
  const namedMs = Math.round(performance.now() - started);
  const tablesSeen = await tables(page, "Item");

  const second = await browser.newPage();
  second.on("pageerror", (e) => errors.push(e.message));
  await second.goto(`http://localhost:${server.port}/`);
  const empty = await second.locator("main").innerText();
  await second.locator('input[type="file"]').setInputFiles(file);
  const picked = await walk(second);
  console.log(JSON.stringify({ named, picked, tables: tablesSeen, empty, errors, requests, named_ms: namedMs }));
} finally {
  await browser.close();
  server.stop(true);
}
