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
 * the results, then opens the first link of its node page. Playwright is not a dependency: the
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

  const second = await browser.newPage();
  second.on("pageerror", (e) => errors.push(e.message));
  await second.goto(`http://localhost:${server.port}/`);
  const empty = await second.locator("main").innerText();
  await second.locator('input[type="file"]').setInputFiles(file);
  const picked = await walk(second);
  console.log(JSON.stringify({ named, picked, empty, errors, requests, named_ms: namedMs }));
} finally {
  await browser.close();
  server.stop(true);
}
