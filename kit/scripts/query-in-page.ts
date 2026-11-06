/**
 * Embed queries in a browser page with the kit (Specification 0.1, section 6; plan M2.8): the kit
 * is bundled for the browser with SQLite's and ONNX Runtime's WebAssembly beside it, served from
 * a local port, and loads the model files inside the page (Chromium, through Playwright), as the
 * viewer will. Each query of `conformance/embedding/cases.json` is embedded in the page and its
 * signs compared with the builder's. Prints one JSON line:
 * `{"texts", "dimensions", "differing", "differing_pct", "worst_agree_pct", "median_ms", "tokens_equal"}`.
 *
 *     uv run python scripts/fetch_model.py
 *     bun kit/scripts/query-in-page.ts [--model DIR]
 *
 * Playwright is not a dependency of the kit: the agent environment provides it with its browser.
 */
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { MODEL } from "../src/embed.js";

const args = process.argv.slice(2);
const kit = fileURLToPath(new URL("..", import.meta.url));
const repo = join(kit, "..");
const modelAt = args.indexOf("--model");
const modelDir = modelAt >= 0 ? args[modelAt + 1]! : join(repo, ".cache", "model", `${MODEL.name}@${MODEL.revision}`);
const require = createRequire(import.meta.url);
const out = mkdtempSync(join(tmpdir(), "kit-query-in-page-"));

try {
  const built = await Bun.build({
    entrypoints: [join(kit, "src/index.ts")],
    outdir: out,
    target: "browser",
    splitting: true,
    naming: { entry: "kit.js", chunk: "[name]-[hash].js" },
  });
  if (!built.success) throw new Error(`bundling the kit failed: ${built.logs.join("\n")}`);
  const sqlite = join(dirname(require.resolve("@sqlite.org/sqlite-wasm/package.json")), "dist");
  const ort = join(dirname(require.resolve("onnxruntime-web/package.json")), "dist");
  copyFileSync(join(sqlite, "sqlite3.wasm"), join(out, "sqlite3.wasm"));
  for (const name of ["ort-wasm-simd-threaded.wasm", "ort-wasm-simd-threaded.mjs"]) copyFileSync(join(ort, name), join(out, name));
  copyFileSync(join(modelDir, MODEL.modelFile.path), join(out, "model.onnx"));
  copyFileSync(join(modelDir, MODEL.tokenizer.path), join(out, "tokenizer.json"));
  copyFileSync(join(repo, "conformance", "embedding", "cases.json"), join(out, "cases.json"));
  writeFileSync(join(out, "index.html"), '<!doctype html><meta charset="utf-8"><title>query in page</title>');

  const types: Record<string, string> = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".wasm": "application/wasm",
    ".html": "text/html",
    ".json": "application/json",
  };
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
    const result = await page.evaluate(async () => {
      const kit = await import("/kit.js");
      const bytes = async (path: string) => new Uint8Array(await (await fetch(path)).arrayBuffer());
      const files = { model: await bytes("/model.onnx"), tokenizer: await bytes("/tokenizer.json") };
      const embedder = await kit.loadEmbedder(files);
      const tokenizer = new kit.WordPiece(new TextDecoder().decode(files.tokenizer));
      const cases = (await (await fetch("/cases.json")).json()) as {
        cases: { query: string; text: string; ids: number[]; bits: string }[];
      };
      let differing = 0;
      let worst = 1;
      let tokensEqual = true;
      const times: number[] = [];
      for (const c of cases.cases) {
        tokensEqual &&= JSON.stringify(tokenizer.encode(c.text, kit.MAX_TOKENS)) === JSON.stringify(c.ids);
        const start = performance.now();
        const v = await embedder.embedQuery(c.query);
        times.push(performance.now() - start);
        let agree = 0;
        for (let i = 0; i < 384; i++) {
          const bit = (parseInt(c.bits.slice((i >> 3) * 2, (i >> 3) * 2 + 2), 16) & (0x80 >> (i & 7))) !== 0;
          if (v[i]! > 0 === bit) agree += 1;
        }
        differing += 384 - agree;
        worst = Math.min(worst, agree / 384);
      }
      times.sort((a, b) => a - b);
      return { texts: cases.cases.length, differing, worst, median: times[Math.floor(times.length / 2)]!, tokensEqual };
    });
    const dimensions = result.texts * 384;
    console.log(
      JSON.stringify({
        texts: result.texts,
        dimensions,
        differing: result.differing,
        differing_pct: Number(((100 * result.differing) / dimensions).toFixed(2)),
        worst_agree_pct: Number((100 * result.worst).toFixed(2)),
        median_ms: Number(result.median.toFixed(1)),
        tokens_equal: result.tokensEqual,
      }),
    );
  } finally {
    await browser.close();
    server.stop(true);
  }
} finally {
  rmSync(out, { recursive: true, force: true });
}
