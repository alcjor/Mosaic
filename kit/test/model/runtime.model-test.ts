// M3.9 on the real model: a page that cannot fetch files (a single-file export from file://)
// gives `loadEmbedder` ONNX Runtime's module and its WebAssembly as bytes; the query vectors are
// the same as when the kit imports the runtime itself (section 6).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MODEL, loadEmbedder } from "../../src/index.js";

const repo = (path: string): string => fileURLToPath(new URL(`../../../${path}`, import.meta.url));
const MODEL_DIR = process.env["MOSAIC_MODEL_DIR"] ?? repo(`.cache/model/${MODEL.name}@${MODEL.revision}`);
const files = () => ({
  model: new Uint8Array(readFileSync(join(MODEL_DIR, MODEL.modelFile.path))),
  tokenizer: new Uint8Array(readFileSync(join(MODEL_DIR, MODEL.tokenizer.path))),
});

function ortWasm(): Uint8Array {
  const require = createRequire(import.meta.url);
  const entry = require.resolve("onnxruntime-web/wasm");
  let dir = dirname(entry);
  while (!dir.endsWith("dist")) dir = dirname(dir);
  return new Uint8Array(readFileSync(join(dir, "ort-wasm-simd-threaded.wasm")));
}

describe("loadEmbedder with a given runtime", () => {
  it("embeds a query as the kit's own import of ONNX Runtime does", async () => {
    const module = await import("onnxruntime-web/wasm");
    const given = await loadEmbedder(files(), { module, wasm: ortWasm() });
    const own = await loadEmbedder(files());
    const query = "high school chemistry teacher becomes a drug dealer";
    const [a, b] = [await given.embedQuery(query), await own.embedQuery(query)];
    expect(a.length).toBe(384);
    expect(Array.from(a)).toEqual(Array.from(b));
  });
});
