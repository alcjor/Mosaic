// M2.8 on the real model (section 6): the kit's tokenizer gives the builder's token ids, the
// kit's query vectors agree in sign with the builder's, the vector tier finds by meaning, and
// the kit with the model stays under its size budget (ADR-007). The builder's ids and signs are
// in `conformance/embedding/cases.json` (`scripts/make_embedding_cases.py`).
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { beforeAll, describe, expect, it } from "vitest";
import {
  DIMENSIONS,
  EMBED_MODEL,
  MAX_TOKENS,
  MODEL,
  WordPiece,
  loadEmbedder,
  openFile,
  queryText,
  type QueryEmbedder,
} from "../../src/index.js";
import { buildMosaic } from "../build-mosaic.js";

const repo = (path: string): string => fileURLToPath(new URL(`../../../${path}`, import.meta.url));
const MODEL_DIR = process.env["MOSAIC_MODEL_DIR"] ?? repo(`.cache/model/${MODEL.name}@${MODEL.revision}`);

interface Case {
  query: string;
  text: string;
  ids: number[];
  bits: string;
}
const CASES = JSON.parse(readFileSync(repo("conformance/embedding/cases.json"), "utf8")) as {
  embed_model: string;
  max_tokens: number;
  cases: Case[];
};

function modelFile(path: string): Uint8Array {
  try {
    return new Uint8Array(readFileSync(join(MODEL_DIR, path)));
  } catch {
    throw new Error(`${join(MODEL_DIR, path)} is missing: run uv run python scripts/fetch_model.py`);
  }
}

const hexBytes = (hex: string): Uint8Array => Uint8Array.from(hex.match(/../g)!, (h) => parseInt(h, 16));
const bitOf = (bytes: Uint8Array, i: number): boolean => (bytes[i >> 3]! & (0x80 >> (i & 7))) !== 0;

let embedder: QueryEmbedder;
let tokenizer: WordPiece;

beforeAll(async () => {
  const files = { model: modelFile(MODEL.modelFile.path), tokenizer: modelFile(MODEL.tokenizer.path) };
  tokenizer = new WordPiece(new TextDecoder().decode(files.tokenizer));
  embedder = await loadEmbedder(files);
});

describe("the real model (section 6)", () => {
  it("is the model the cases were made with", () => {
    expect(CASES.embed_model).toBe(EMBED_MODEL);
    expect(CASES.max_tokens).toBe(MAX_TOKENS);
    expect(embedder.model).toBe(EMBED_MODEL);
  });

  it("the kit's tokenizer gives the builder's token ids for every case, truncated at 256", () => {
    for (const c of CASES.cases) {
      expect(c.text).toBe(queryText(c.query));
      expect(tokenizer.encode(c.text, MAX_TOKENS), JSON.stringify(c.query).slice(0, 60)).toEqual(c.ids);
    }
    expect(CASES.cases.some((c) => c.ids.length === MAX_TOKENS)).toBe(true);
  });

  it("the kit's query vectors agree in sign with the builder's on at least 98 % of the dimensions of the set", async () => {
    let differing = 0;
    let worst = 1;
    for (const c of CASES.cases) {
      const v = await embedder.embedQuery(c.query);
      expect(v).toHaveLength(DIMENSIONS);
      expect(Math.hypot(...v)).toBeCloseTo(1, 5);
      const builder = hexBytes(c.bits);
      let agree = 0;
      for (let i = 0; i < DIMENSIONS; i++) if (v[i]! > 0 === bitOf(builder, i)) agree += 1;
      differing += DIMENSIONS - agree;
      worst = Math.min(worst, agree / DIMENSIONS);
    }
    const total = CASES.cases.length * DIMENSIONS;
    console.log(
      `sign agreement: ${CASES.cases.length} texts, ${differing} of ${total} dimensions differ ` +
        `(${((100 * differing) / total).toFixed(2)} %), worst text ${(100 * worst).toFixed(2)} % agree`,
    );
    // Spike S5 measured 0.87 % of bits differing between runtimes, over a set of texts.
    expect(1 - differing / total).toBeGreaterThanOrEqual(0.98);
    // No text is far off: a tokenizer or pooling fault would show here first.
    expect(worst).toBeGreaterThanOrEqual(0.95);
  });

  it("embeds a query in tens of milliseconds", async () => {
    const times: number[] = [];
    for (let i = 0; i < 10; i++) {
      const started = performance.now();
      await embedder.embedQuery(`which film is about a robot, take ${i}`);
      times.push(performance.now() - started);
    }
    times.sort((a, b) => a - b);
    console.log(`query embedding: median ${times[5]!.toFixed(1)} ms, max ${times[9]!.toFixed(1)} ms`);
    expect(times[5]).toBeLessThan(1_000);
  });

  it("find lists by meaning: a query sharing no word with the node finds it in the vector tier", async () => {
    // Stored vectors are the builder's, from the cases: each node holds the signs the builder
    // gave one text.
    const byQuery = new Map(CASES.cases.map((c) => [c.query, hexBytes(c.bits)]));
    const texts = {
      "Item:robot": "a film about a lonely robot who falls in love in space",
      "Item:ocean": "documentary on ocean life and coral reefs",
      "Item:heat": "which step switches the heater on?",
      "Item:temp": "inlet temperature",
    };
    const nodes = Object.keys(texts).map((id) => ({ type: "Item", key: id.slice(5), label: id.slice(5) }));
    const vectors = Object.fromEntries(Object.entries(texts).map(([id, t]) => [id, byQuery.get(t)!]));
    const file = await openFile(buildMosaic({ nodes, vectors }), "meaning.mosaic", { embedder });
    expect(file.vectorSearch).toBe(true);
    const first = async (query: string) => {
      const answer = await file.find({ query });
      if (!("data" in answer)) throw new Error(JSON.stringify(answer));
      return answer.data.results[0];
    };
    expect(await first("android romance among the stars")).toMatchObject({ id: "Item:robot", match: "vector" });
    expect(await first("marine animals under the sea")).toMatchObject({ id: "Item:ocean", match: "vector" });
    file.close();
  });
});

describe("kit size with the model (ADR-007)", () => {
  it("is under 60 MB compressed: the kit, SQLite, ONNX Runtime's WebAssembly and the model files", () => {
    const require = createRequire(import.meta.url);
    const src = fileURLToPath(new URL("../../src/", import.meta.url));
    const sqlite = join(dirname(require.resolve("@sqlite.org/sqlite-wasm/package.json")), "dist");
    const ort = dirname(require.resolve("onnxruntime-web/wasm"));
    const files = [
      ...readdirSync(src).map((name) => join(src, name)),
      join(sqlite, "index.mjs"),
      join(sqlite, "sqlite3.wasm"),
      join(ort, "ort.wasm.bundle.min.mjs"),
      join(ort, "ort-wasm-simd-threaded.wasm"),
      join(MODEL_DIR, MODEL.modelFile.path),
      join(MODEL_DIR, MODEL.tokenizer.path),
    ];
    const sizes = files.map((path) => gzipSync(readFileSync(path), { level: 9 }).byteLength);
    const total = sizes.reduce((a, b) => a + b, 0);
    const mb = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`;
    console.log(
      `kit with model: ${mb(total)} compressed (model ${mb(sizes.at(-2)!)}, ONNX Runtime ${mb(sizes.at(-3)! + sizes.at(-4)!)})`,
    );
    expect(total).toBeLessThan(60 * 1024 * 1024);
  });
});
