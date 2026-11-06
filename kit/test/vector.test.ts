// M2.8: `find`'s vector tier (sections 6, 8.1, 8.5, 3.8 fallback). These tests stand in for the
// model with a fixed query vector; the real model and tokenizer are tested in `test/model/`
// (slow, `tests/test_kit_model.py`).
import { Ajv2020 } from "ajv/dist/2020.js";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  DIMENSIONS,
  EMBED_MODEL,
  ModelFileError,
  QUERY_PREFIX,
  RESULT_LIMIT,
  loadEmbedder,
  openFile,
  pool,
  queryText,
  score,
  type Answer,
  type FindAnswer,
  type QueryEmbedder,
  type SealedFile,
} from "../src/index.js";
import { buildMosaic, type MosaicSpec } from "./build-mosaic.js";

const repo = (path: string): string => fileURLToPath(new URL(`../../${path}`, import.meta.url));
const schema = JSON.parse(readFileSync(repo("spec/answers.schema.json"), "utf8")) as object;
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);

function valid<T extends Answer>(answer: T): T {
  if (!validate(answer)) throw new Error(`answer is not valid: ${JSON.stringify(validate.errors)}`);
  return answer;
}

/** A query vector: `values` in its first dimensions, 0 elsewhere, normalised. */
function vector(...values: number[]): Float32Array {
  const v = new Float32Array(DIMENSIONS);
  values.forEach((x, i) => (v[i] = x));
  const norm = Math.hypot(...v);
  return v.map((x) => x / norm);
}

/** 48 stored bytes with bit i set for each i in `set` (most significant bit first). */
function bits(...set: number[]): Uint8Array {
  const b = new Uint8Array(DIMENSIONS / 8);
  for (const i of set) b[i >> 3]! |= 0x80 >> (i & 7);
  return b;
}

/** An embedder that gives `v` for every query, and records the queries. */
function fixed(v: Float32Array, model = EMBED_MODEL): QueryEmbedder & { queries: string[] } {
  const queries: string[] = [];
  return {
    model,
    queries,
    async embedQuery(query: string) {
      queries.push(query);
      return v;
    },
  };
}

async function found(file: SealedFile, args: Record<string, unknown>): Promise<FindAnswer["data"]> {
  const answer = valid(await file.find(args));
  if (!("data" in answer)) throw new Error(`find failed: ${JSON.stringify(answer)}`);
  return answer.data;
}

const tiers = (data: FindAnswer["data"]): string[] => data.results.map((r) => `${r.match} ${r.id}`);

// Query vector (0.8, 0.6, 0, …): a node scores +0.8 for bit 0 set, else −0.8, and +0.6 for
// bit 1 set, else −0.6 (dimensions where the query is 0 add nothing).
const Q = vector(0.8, 0.6);
const SPEC: MosaicSpec = {
  nodes: [
    { type: "Item", key: "both", label: "Pump station" },
    { type: "Item", key: "first", label: "Valve" },
    { type: "Item", key: "second", label: "Heater" },
    { type: "Item", key: "none", label: "Tank" },
    { type: "Part", key: "both2", label: "Pump part", snippets: ["the pump"] },
  ],
  vectors: {
    "Item:both": bits(0, 1),
    "Item:first": bits(0),
    "Item:second": bits(1),
    "Item:none": bits(),
    "Part:both2": bits(0, 1, 2, 3),
  },
};

describe("score (section 6)", () => {
  it("is the dot product of the query with the stored bits read as +1 and -1", () => {
    expect(score(Q, bits(0, 1))).toBeCloseTo(1.4, 6);
    expect(score(Q, bits(0))).toBeCloseTo(0.2, 6);
    expect(score(Q, bits(1))).toBeCloseTo(-0.2, 6);
    expect(score(Q, bits())).toBeCloseTo(-1.4, 6);
  });

  it("reads bit i as the most significant first: bit 0 is 0x80 of byte 0, bit 383 is 0x01 of byte 47", () => {
    const last = new Float32Array(DIMENSIONS);
    last[DIMENSIONS - 1] = 1;
    const b = new Uint8Array(48);
    b[47] = 0x01;
    expect(score(last, b)).toBe(1);
    b[47] = 0x02;
    expect(score(last, b)).toBe(-1);
    const first = new Float32Array(DIMENSIONS);
    first[0] = 1;
    const c = new Uint8Array(48);
    c[0] = 0x80;
    expect(score(first, c)).toBe(1);
  });

  it("uses the full-precision query, never its bits", () => {
    // By the query's signs alone, bits(0) and bits(1) tie (each agrees on one of the two
    // dimensions the query is positive in); at full precision bits(0) scores 0.2, bits(1) -0.2.
    expect(score(Q, bits(0))).toBeGreaterThan(score(Q, bits(1)));
  });
});

describe("find: vector matches after the exact and text tiers (sections 8.1, 8.5)", () => {
  it("lists vector matches not already listed, tagged vector, highest score first", async () => {
    const embedder = fixed(Q);
    const file = await openFile(buildMosaic(SPEC), "v.mosaic", { embedder });
    expect(file.vectorSearch).toBe(true);
    const data = await found(file, { query: "pump" });
    expect(tiers(data)).toEqual([
      "text Part:both2",
      "text Item:both",
      "vector Item:first",
      "vector Item:second",
      "vector Item:none",
    ]);
    expect(embedder.queries).toEqual(["pump"]);
    file.close();
  });

  it("puts exact matches first, then text, then vector", async () => {
    const file = await openFile(buildMosaic(SPEC), "v.mosaic", { embedder: fixed(Q) });
    const data = await found(file, { query: "second" });
    expect(tiers(data)).toEqual([
      "exact Item:second",
      // Part:both2 has two more bits set, where the query is 0: it ties Item:both, by id.
      "vector Item:both",
      "vector Part:both2",
      "vector Item:first",
      "vector Item:none",
    ]);
    file.close();
  });

  it("breaks ties in score by id, by UTF-8 bytes", async () => {
    const same = bits(0);
    const file = await openFile(
      buildMosaic({
        nodes: [
          { type: "Item", key: "b" },
          { type: "Item", key: "a" },
          { type: "Item", key: "～" },
          { type: "Item", key: "😀" },
        ],
        vectors: { "Item:a": same, "Item:b": same, "Item:～": same, "Item:😀": same },
      }),
      "v.mosaic",
      { embedder: fixed(Q) },
    );
    // U+FF5E is EF BD 9E in UTF-8 and U+1F600 is F0 9F 98 80: by UTF-16 the order would differ.
    expect(tiers(await found(file, { query: "zzz" }))).toEqual([
      "vector Item:a",
      "vector Item:b",
      "vector Item:～",
      "vector Item:😀",
    ]);
    file.close();
  });

  it("keeps type and limit: vector matches fill the room the other tiers leave", async () => {
    const file = await openFile(buildMosaic(SPEC), "v.mosaic", { embedder: fixed(Q) });
    expect(tiers(await found(file, { query: "pump", type: "Item" }))).toEqual([
      "text Item:both",
      "vector Item:first",
      "vector Item:second",
      "vector Item:none",
    ]);
    expect(tiers(await found(file, { query: "pump", limit: 3 }))).toEqual([
      "text Part:both2",
      "text Item:both",
      "vector Item:first",
    ]);
    expect(tiers(await found(file, { query: "pump", limit: 2 }))).toEqual(["text Part:both2", "text Item:both"]);
    file.close();
  });

  it("gives at most 20 results on a mosaic of more nodes", async () => {
    const nodes = Array.from({ length: 50 }, (_, i) => ({ type: "Item", key: `k${String(i).padStart(2, "0")}` }));
    const vectors = Object.fromEntries(nodes.map((n, i) => [`Item:${n.key}`, bits(i % 7)]));
    const file = await openFile(buildMosaic({ nodes, vectors }), "v.mosaic", { embedder: fixed(Q) });
    const data = await found(file, { query: "anything", limit: 100 });
    expect(data.results).toHaveLength(RESULT_LIMIT);
    expect(data.results.every((r) => r.match === "vector")).toBe(true);
    file.close();
  });

  it("does not embed a query with no words, nor arguments find refuses", async () => {
    const embedder = fixed(Q);
    const file = await openFile(buildMosaic(SPEC), "v.mosaic", { embedder });
    expect(await found(file, { query: "" })).toEqual({ results: [], total: 0 });
    expect(await found(file, { query: "..." })).toEqual({ results: [], total: 0 });
    expect(await found(file, { query: "* + ?" })).toEqual({ results: [], total: 0 });
    for (const args of [{ query: 3 }, {}, { query: "a ".repeat(1000) }]) {
      expect("error" in valid(await file.find(args))).toBe(true);
    }
    expect(embedder.queries).toEqual([]);
    file.close();
  });

  it("on a 10,000-node mosaic, the vector tier stops at the time bound with an error naming it", async () => {
    const n = 10_000;
    const nodes = Array.from({ length: n }, (_, i) => ({ type: "Item", key: `i${String(i).padStart(5, "0")}` }));
    const vectors = Object.fromEntries(nodes.map((node, i) => [`Item:${node.key}`, bits(i % 384, (i * 7) % 384)]));
    const bytes = buildMosaic({ nodes, vectors });
    const normal = await openFile(bytes, "large.mosaic", { embedder: fixed(Q) });
    const started = performance.now();
    const data = await found(normal, { query: "nothing matches" });
    console.log(`vector tier on ${n} nodes: ${(performance.now() - started).toFixed(1)} ms`);
    expect(data.results).toHaveLength(RESULT_LIMIT);
    normal.close();
    const bound = 0.01;
    const file = await openFile(bytes, "large.mosaic", { embedder: fixed(Q), timeLimitMs: bound });
    const answer = valid(await file.find({ query: "nothing matches" }));
    expect("error" in answer && answer.error.code).toBe("limit_exceeded");
    expect("error" in answer && answer.error.message).toContain(`${bound} ms`);
    file.close();
  }, 120_000);
});

describe("find: names and full text only without supported vectors (section 3.8, section 6)", () => {
  it("a mosaic without vectors opens and find has no vector tier", async () => {
    const embedder = fixed(Q);
    const { vectors: _v, ...plain } = SPEC;
    const file = await openFile(buildMosaic(plain), "plain.mosaic", { embedder });
    expect(file.vectorSearch).toBe(false);
    expect(tiers(await found(file, { query: "pump" }))).toEqual(["text Part:both2", "text Item:both"]);
    expect(embedder.queries).toEqual([]);
    file.close();
  });

  it("a mosaic whose embed_model the kit does not support opens and find has no vector tier", async () => {
    const embedder = fixed(Q);
    const other = `other-model@${"0".repeat(64)}`;
    const file = await openFile(buildMosaic({ ...SPEC, embedModel: other }), "other.mosaic", { embedder });
    expect(file.header.embed_model).toBe(other);
    expect(file.vectorSearch).toBe(false);
    expect(tiers(await found(file, { query: "pump" }))).toEqual(["text Part:both2", "text Item:both"]);
    expect(embedder.queries).toEqual([]);
    file.close();
  });

  it("an embedder for another model is not used on a mosaic of the kit's model", async () => {
    const embedder = fixed(Q, `other-model@${"0".repeat(64)}`);
    const file = await openFile(buildMosaic(SPEC), "v.mosaic", { embedder });
    expect(file.vectorSearch).toBe(false);
    expect(tiers(await found(file, { query: "pump" }))).toEqual(["text Part:both2", "text Item:both"]);
    file.close();
  });

  it("opened without an embedder, a mosaic with vectors is searched by names and full text", async () => {
    const file = await openFile(buildMosaic(SPEC), "v.mosaic");
    expect(file.vectorSearch).toBe(false);
    expect(tiers(await found(file, { query: "pump" }))).toEqual(["text Part:both2", "text Item:both"]);
    file.close();
  });
});

describe("the query embedding (section 6)", () => {
  it("embeds the query text: the section 6 prefix, then the query", () => {
    expect(QUERY_PREFIX).toBe("Represent this sentence for searching relevant passages: ");
    expect(queryText("inlet temperature")).toBe("Represent this sentence for searching relevant passages: inlet temperature");
  });

  it("names the model as the header's embed_model does", () => {
    expect(EMBED_MODEL).toBe("snowflake-arctic-embed-xs@e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1");
  });

  it("pools the first token's output divided by its Euclidean norm", () => {
    const hidden = new Float32Array(DIMENSIONS * 2);
    hidden[0] = 3;
    hidden[1] = 4;
    hidden[DIMENSIONS] = 100; // the second token is ignored
    const v = pool(hidden);
    expect(v).toHaveLength(DIMENSIONS);
    expect(v[0]).toBeCloseTo(0.6, 6);
    expect(v[1]).toBeCloseTo(0.8, 6);
    expect(v.slice(2).every((x) => x === 0)).toBe(true);
    expect(() => pool(new Float32Array(DIMENSIONS))).toThrow(/norm/);
  });

  it("refuses model files that are not the pinned ones, naming the file and both hashes", async () => {
    const other = new TextEncoder().encode("not the model");
    const hash = "f6ef9b5ac7a0aabd5e3fa4a5d3c6c45f2b4dbb04b34c7d0f8b0b3c86d2d98a1c";
    await expect(loadEmbedder({ model: other, tokenizer: other })).rejects.toThrow(ModelFileError);
    await expect(loadEmbedder({ model: other, tokenizer: other })).rejects.toThrow(
      /onnx\/model_quantized\.onnx has SHA-256 [0-9a-f]{64}, not the pinned e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1/,
    );
    expect(hash).toHaveLength(64);
  });
});

describe("find: decision C on #111 (the vector tier fills the list; total counts what is listed)", () => {
  // 100 nodes with vectors; one holds the query's word.
  const nodes = Array.from({ length: 100 }, (_, i) => ({
    type: "Item",
    key: `k${String(i).padStart(3, "0")}`,
    label: i === 42 ? "robot romance" : `thing ${i}`,
  }));
  const vectors = Object.fromEntries(nodes.map((n, i) => [`Item:${n.key}`, bits(i % 3)]));

  it("one text match and limit 20: the text match, then 19 vector matches, total 20", async () => {
    const file = await openFile(buildMosaic({ nodes, vectors }), "c.mosaic", { embedder: fixed(Q) });
    const data = await found(file, { query: "robot romance" });
    expect(data.results).toHaveLength(20);
    expect(data.results[0]).toMatchObject({ id: "Item:k042", match: "text" });
    expect(data.results.slice(1).every((r) => r.match === "vector")).toBe(true);
    expect(data.total).toBe(20);
    file.close();
  });

  it("limit 5: 5 results, total 5", async () => {
    const file = await openFile(buildMosaic({ nodes, vectors }), "c.mosaic", { embedder: fixed(Q) });
    const data = await found(file, { query: "robot romance", limit: 5 });
    expect(data.results).toHaveLength(5);
    expect(data.total).toBe(5);
    file.close();
  });

  it("more text matches than the list holds: no vector matches, total counts the text matches", async () => {
    const file = await openFile(buildMosaic({ nodes, vectors }), "c.mosaic", { embedder: fixed(Q) });
    const data = await found(file, { query: "thing" });
    expect(data.results).toHaveLength(20);
    expect(data.results.every((r) => r.match === "text")).toBe(true);
    expect(data.total).toBe(99);
    file.close();
  });
});
