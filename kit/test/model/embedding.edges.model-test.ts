// M2.8 verifier edge cases on the real model (section 6). `embedding-edge-cases.json` holds token
// ids and sign bits the builder (`mosaic_build.mosaic.vectors`, the pinned tokenizer and model)
// gives for queries `conformance/embedding/cases.json` does not hold: the tokenizer's special
// tokens written as text, combining marks, Hangul jamo, supplementary-plane ideographs, ZWJ
// sequences, odd white space, NUL, very long words and the 256-token boundary.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
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
  score,
  type QueryEmbedder,
} from "../../src/index.js";
import { buildMosaic } from "../build-mosaic.js";

const repo = (path: string): string => fileURLToPath(new URL(`../../../${path}`, import.meta.url));
const MODEL_DIR = process.env["MOSAIC_MODEL_DIR"] ?? repo(`.cache/model/${MODEL.name}@${MODEL.revision}`);

interface Case {
  query: string;
  ids: number[];
  bits: string;
}
const ALL = JSON.parse(readFileSync(new URL("./embedding-edge-cases.json", import.meta.url), "utf8")) as Case[];
/** The special tokens written as text: the pinned tokenizer reads each as one token (own tests). */
const SPECIAL = ALL.find((c) => c.query.startsWith("[CLS]"))!;
const CASES = ALL.filter((c) => c !== SPECIAL);

const hexBytes = (hex: string): Uint8Array => Uint8Array.from(hex.match(/../g)!, (h) => parseInt(h, 16));
const bitOf = (bytes: Uint8Array, i: number): boolean => (bytes[i >> 3]! & (0x80 >> (i & 7))) !== 0;
const label = (q: string): string => JSON.stringify(q).slice(0, 50);

let embedder: QueryEmbedder;
let tokenizer: WordPiece;

beforeAll(async () => {
  const read = (path: string) => new Uint8Array(readFileSync(join(MODEL_DIR, path)));
  const files = { model: read(MODEL.modelFile.path), tokenizer: read(MODEL.tokenizer.path) };
  tokenizer = new WordPiece(new TextDecoder().decode(files.tokenizer));
  embedder = await loadEmbedder(files);
});

describe("the tokenizer on queries outside the conformance cases (section 6)", () => {
  it("gives the builder's token ids for every edge case", () => {
    const wrong: string[] = [];
    for (const c of CASES) {
      const ids = tokenizer.encode(queryText(c.query), MAX_TOKENS);
      if (JSON.stringify(ids) !== JSON.stringify(c.ids)) wrong.push(`${label(c.query)}: ${ids.length} vs ${c.ids.length} ids`);
    }
    expect(wrong).toEqual([]);
  });

  it("reads the special tokens [CLS] [SEP] [UNK] [MASK] [PAD] written in a query as the pinned tokenizer.json does (one token each)", () => {
    // tokenizer.json lists them as added special tokens, so the builder's tokenizer gives
    // 9 prefix tokens + 5 + [SEP] = 15 ids, not the pieces of "[", "cls", "]", …
    expect(SPECIAL.ids).toHaveLength(15);
    expect(tokenizer.encode(queryText(SPECIAL.query), MAX_TOKENS)).toEqual(SPECIAL.ids);
  });

  it("embeds a query holding special-token text with a vector agreeing in sign with the builder's on 98 % of the dimensions", async () => {
    const v = await embedder.embedQuery(SPECIAL.query);
    const builder = hexBytes(SPECIAL.bits);
    let agree = 0;
    for (let i = 0; i < DIMENSIONS; i++) if (v[i]! > 0 === bitOf(builder, i)) agree += 1;
    expect(agree / DIMENSIONS).toBeGreaterThanOrEqual(0.98);
  });

  it("truncates at 256 tokens, special tokens included: 255 stays, 256 stays, more is cut to 256 ending in [SEP]", () => {
    const lengths = CASES.filter((c) => c.query.startsWith("word word")).map((c) => c.ids.length);
    expect(lengths).toEqual([255, 256, 256]);
    for (const c of CASES.filter((c) => c.ids.length === MAX_TOKENS)) {
      const ids = tokenizer.encode(queryText(c.query), MAX_TOKENS);
      expect(ids).toHaveLength(MAX_TOKENS);
      expect(ids[0]).toBe(101);
      expect(ids[MAX_TOKENS - 1]).toBe(102);
    }
  });
});

describe("the query embedder on queries outside the conformance cases (section 6)", () => {
  it("gives a finite vector of 384 dimensions with Euclidean norm 1 for every edge case, including NUL and white space only", async () => {
    for (const c of CASES) {
      const v = await embedder.embedQuery(c.query);
      expect(v, label(c.query)).toHaveLength(DIMENSIONS);
      expect(v.every(Number.isFinite), label(c.query)).toBe(true);
      expect(Math.hypot(...v), label(c.query)).toBeCloseTo(1, 4);
    }
  });

  it("agrees in sign with the builder's vector on at least 98 % of the dimensions over the edge cases", async () => {
    let differing = 0;
    let worst = 1;
    for (const c of CASES) {
      const v = await embedder.embedQuery(c.query);
      const builder = hexBytes(c.bits);
      let agree = 0;
      for (let i = 0; i < DIMENSIONS; i++) if (v[i]! > 0 === bitOf(builder, i)) agree += 1;
      differing += DIMENSIONS - agree;
      worst = Math.min(worst, agree / DIMENSIONS);
    }
    const total = CASES.length * DIMENSIONS;
    console.log(`edge cases: ${CASES.length} texts, ${differing} of ${total} differ (${((100 * differing) / total).toFixed(2)} %), worst ${(100 * worst).toFixed(2)} % agree`);
    expect(1 - differing / total).toBeGreaterThanOrEqual(0.98);
    expect(worst).toBeGreaterThanOrEqual(0.95);
  });

  it("gives the same vector for the same query twice, and a result that a caller can change without changing the next", async () => {
    const q = "inlet temperature of the second pump";
    const a = await embedder.embedQuery(q);
    const saved = Float32Array.from(a);
    a.fill(0);
    const b = await embedder.embedQuery(q);
    expect([...b]).toEqual([...saved]);
  });

  it("answers concurrent embeddings each with its own query's vector", async () => {
    const queries = CASES.slice(0, 8).map((c) => c.query);
    const alone: Float32Array[] = [];
    for (const q of queries) alone.push(Float32Array.from(await embedder.embedQuery(q)));
    const together = await Promise.all(queries.map((q) => embedder.embedQuery(q)));
    together.forEach((v, i) => expect([...v], label(queries[i]!)).toEqual([...alone[i]!]));
  });

  it("scores a stored vector made from the same text higher than other texts' vectors (cosine near 1 against sign bits)", async () => {
    const own = CASES.find((c) => c.query === "x-ray co-operate don't e.g. 3.14 a/b")!;
    const v = await embedder.embedQuery(own.query);
    const ownScore = score(v, hexBytes(own.bits));
    for (const other of CASES.filter((c) => c !== own && c.query.length > 3)) {
      expect(ownScore, label(other.query)).toBeGreaterThan(score(v, hexBytes(other.bits)));
    }
  });
});

describe("find with the real model on stored builder vectors (sections 6, 8.5)", () => {
  it("lists the node whose vector the builder made from the query's own text first, tagged vector, whichever the id order", async () => {
    const picks = CASES.filter((c) => c.query.length > 3 && c.query.length < 60 && !c.query.includes("\0"));
    const nodes = picks.slice(0, 8).map((c, i) => ({ type: "Item", key: `n${7 - i}`, label: `node ${i}` }));
    const vectors = Object.fromEntries(picks.slice(0, 8).map((c, i) => [`Item:n${7 - i}`, hexBytes(c.bits)]));
    const file = await openFile(buildMosaic({ nodes, vectors }), "own.mosaic", { embedder });
    expect(file.vectorSearch).toBe(true);
    for (const [i, c] of picks.slice(0, 8).entries()) {
      const answer = await file.find({ query: c.query });
      if (!("data" in answer)) throw new Error(JSON.stringify(answer));
      // A query made only of punctuation has no words: nothing is searched.
      const hasWords = /[\p{L}\p{N}]/u.test(c.query);
      if (!hasWords) continue;
      expect(answer.data.results[0], label(c.query)).toMatchObject({ id: `Item:n${7 - i}`, match: "vector" });
    }
    file.close();
  });

  it("two finds with the real model on one file give the same bytes", async () => {
    const nodes = [{ type: "Item", key: "a" }, { type: "Item", key: "b" }];
    const vectors = { "Item:a": hexBytes(CASES[2]!.bits), "Item:b": hexBytes(CASES[3]!.bits) };
    const file = await openFile(buildMosaic({ nodes, vectors }), "det.mosaic", { embedder });
    const one = JSON.stringify(await file.find({ query: "heater switch" }));
    const two = JSON.stringify(await file.find({ query: "heater switch" }));
    expect(two).toBe(one);
    file.close();
  });

  it("a mosaic whose embed_model is the kit's name with another file hash is not vector-searched", async () => {
    const other = `${MODEL.name}@${"0".repeat(64)}`;
    const file = await openFile(
      buildMosaic({ nodes: [{ type: "Item", key: "a" }], vectors: { "Item:a": hexBytes(CASES[2]!.bits) }, embedModel: other }),
      "other.mosaic",
      { embedder },
    );
    expect(EMBED_MODEL).not.toBe(other);
    expect(file.vectorSearch).toBe(false);
    file.close();
  });
});
