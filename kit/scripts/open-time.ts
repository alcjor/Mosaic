/**
 * Time the kit's `openFile` in a browser (Chromium, through Playwright), hash checks included
 * (Specification 0.1, section 3.8; ADR-007: open under 3 s). The kit is bundled for the browser
 * with the SQLite WebAssembly beside it, served from a local port, and opens the given file
 * inside the page, as the viewer will. Prints one JSON line:
 * `{"file", "bytes", "runs_ms", "median_ms", "knowledge_hash", "vector_hash"}`.
 *
 *     bun kit/scripts/open-time.ts FILE [--runs N]
 *
 * Playwright is not a dependency of the kit: the agent environment provides it with its
 * browser (`require("playwright")`).
 */
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const file = args[0];
const runsAt = args.indexOf("--runs");
const runs = runsAt >= 0 ? Number(args[runsAt + 1]) : 3;
if (!file || !(runs > 0)) {
  console.error("usage: bun kit/scripts/open-time.ts FILE [--runs N]");
  process.exit(2);
}

const kit = fileURLToPath(new URL("..", import.meta.url));
const require = createRequire(import.meta.url);
const out = mkdtempSync(join(tmpdir(), "kit-open-time-"));

try {
  const built = await Bun.build({ entrypoints: [join(kit, "src/index.ts")], outdir: out, target: "browser", naming: "kit.js" });
  if (!built.success) throw new Error(`bundling the kit failed: ${built.logs.join("\n")}`);
  const wasm = join(dirname(require.resolve("@sqlite.org/sqlite-wasm/package.json")), "dist", "sqlite3.wasm");
  copyFileSync(wasm, join(out, "sqlite3.wasm"));
  copyFileSync(file, join(out, "file.bin"));
  writeFileSync(join(out, "index.html"), '<!doctype html><meta charset="utf-8"><title>open time</title>');

  const types: Record<string, string> = { ".js": "text/javascript", ".wasm": "application/wasm", ".html": "text/html" };
  const server = Bun.serve({
    port: 0,
    fetch(request) {
      const name = basename(new URL(request.url).pathname) || "index.html";
      try {
        const body = readFileSync(join(out, name));
        const ext = name.slice(name.lastIndexOf("."));
        return new Response(body, { headers: { "content-type": types[ext] ?? "application/octet-stream" } });
      } catch {
        return new Response("not found", { status: 404 });
      }
    },
  });

  const { chromium } = require("playwright") as typeof import("playwright");
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(`http://localhost:${server.port}/index.html`);
    const result = await page.evaluate(
      async ({ runs, name }) => {
        const kit = await import("/kit.js");
        const bytes = new Uint8Array(await (await fetch("/file.bin")).arrayBuffer());
        // Load SQLite WebAssembly once, as a page does before its first file.
        (await kit.openFile(bytes, name)).close();
        const times: number[] = [];
        let header: { knowledge_hash: string; vector_hash: string | null } | undefined;
        for (let i = 0; i < runs; i++) {
          const start = performance.now();
          const opened = await kit.openFile(bytes, name);
          times.push(performance.now() - start);
          header = opened.header;
          opened.close();
        }
        return { times, bytes: bytes.length, header: header! };
      },
      { runs, name: basename(file) },
    );
    const sorted = [...result.times].sort((a, b) => a - b);
    console.log(
      JSON.stringify({
        file: basename(file),
        bytes: result.bytes,
        runs_ms: result.times.map((t) => Math.round(t)),
        median_ms: Math.round(sorted[Math.floor(sorted.length / 2)]!),
        knowledge_hash: result.header.knowledge_hash,
        vector_hash: result.header.vector_hash,
      }),
    );
  } finally {
    await browser.close();
    server.stop(true);
  }
} finally {
  rmSync(out, { recursive: true, force: true });
}
