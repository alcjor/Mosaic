/**
 * Time the kit's tools in a browser (Chromium, through Playwright): `find`, `get`, `neighbors`,
 * `cite` and a page of `table` (Specification 0.1, section 8.1; ADR-007: tool latency in a
 * browser within 3 times the native 100 ms at the 95th percentile). The kit is bundled for the
 * browser with the SQLite WebAssembly beside it, served from a local port, and opens the given
 * file inside the page, as the viewer will; each call is timed from the page. Prints one JSON
 * line: `{"file", "bytes", "runs", "p95_ms": {tool: ms}, "median_ms": {tool: ms}}`.
 *
 *     bun kit/scripts/tool-latency.ts FILE CALLS.json [--runs N]
 *
 * `CALLS.json` maps each tool to the arguments of the call to time. Playwright is not a
 * dependency of the kit: the agent environment provides it with its browser
 * (`require("playwright")`).
 */
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const file = args[0];
const callsFile = args[1];
const runsAt = args.indexOf("--runs");
const runs = runsAt >= 0 ? Number(args[runsAt + 1]) : 50;
if (!file || !callsFile || !(runs > 0)) {
  console.error("usage: bun kit/scripts/tool-latency.ts FILE CALLS.json [--runs N]");
  process.exit(2);
}
const calls = JSON.parse(readFileSync(callsFile, "utf8")) as Record<string, unknown>;

const kit = fileURLToPath(new URL("..", import.meta.url));
const require = createRequire(import.meta.url);
const out = mkdtempSync(join(tmpdir(), "kit-tool-latency-"));

try {
  const built = await Bun.build({ entrypoints: [join(kit, "src/index.ts")], outdir: out, target: "browser", naming: "kit.js" });
  if (!built.success) throw new Error(`bundling the kit failed: ${built.logs.join("\n")}`);
  const wasm = join(dirname(require.resolve("@sqlite.org/sqlite-wasm/package.json")), "dist", "sqlite3.wasm");
  copyFileSync(wasm, join(out, "sqlite3.wasm"));
  copyFileSync(file, join(out, "file.bin"));
  writeFileSync(join(out, "index.html"), '<!doctype html><meta charset="utf-8"><title>tool latency</title>');

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
      async ({ runs, name, calls }) => {
        const kit = await import("/kit.js");
        const bytes = new Uint8Array(await (await fetch("/file.bin")).arrayBuffer());
        const opened = await kit.openFile(bytes, name);
        const times: Record<string, number[]> = {};
        const answers: Record<string, unknown> = {};
        try {
          for (const [tool, args] of Object.entries(calls)) {
            // One call first, untimed, as a page warms up before its first answer.
            answers[tool] = await opened[tool](args);
            times[tool] = [];
            for (let i = 0; i < runs; i++) {
              const start = performance.now();
              await opened[tool](args);
              times[tool].push(performance.now() - start);
            }
          }
        } finally {
          opened.close();
        }
        return { times, answers, bytes: bytes.length };
      },
      { runs, name: basename(file), calls },
    );
    const at = (times: number[], q: number): number => {
      const sorted = [...times].sort((a, b) => a - b);
      return Math.round(sorted[Math.min(sorted.length - 1, Math.ceil(q * sorted.length) - 1)]! * 100) / 100;
    };
    const p95: Record<string, number> = {};
    const median: Record<string, number> = {};
    for (const [tool, times] of Object.entries(result.times)) {
      p95[tool] = at(times, 0.95);
      median[tool] = at(times, 0.5);
    }
    console.log(
      JSON.stringify({ file: basename(file), bytes: result.bytes, runs, p95_ms: p95, median_ms: median, answers: result.answers }),
    );
  } finally {
    await browser.close();
    server.stop(true);
  }
} finally {
  rmSync(out, { recursive: true, force: true });
}
