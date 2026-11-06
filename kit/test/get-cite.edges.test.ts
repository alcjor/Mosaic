// Edge cases for M2.4 (`get`, `cite`), written from the spec's words, not the implementation:
//   sections 8.1, 8.2, 3.5, 3.6, 3.8 step 4, 10 and spec/answers.schema.json.
import { Ajv2020 } from "ajv/dist/2020.js";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  CUT_MARKER,
  RESULT_LIMIT,
  openFile,
  type Answer,
  type CiteAnswer,
  type ErrorAnswer,
  type GetAnswer,
  type SealedFile,
} from "../src/index.js";
import { DOC_HASH, buildMosaic, type MosaicSpec } from "./build-mosaic.js";

const repo = (path: string): string => fileURLToPath(new URL(`../../${path}`, import.meta.url));
const schema = JSON.parse(readFileSync(repo("spec/answers.schema.json"), "utf8")) as object;
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);

function valid<T extends Answer>(answer: T): T {
  if (!validate(answer)) {
    throw new Error(`answer is not valid: ${JSON.stringify(validate.errors)}\n${JSON.stringify(answer).slice(0, 2000)}`);
  }
  return answer;
}

async function open(spec: MosaicSpec, options?: { timeLimitMs?: number }): Promise<SealedFile> {
  return openFile(buildMosaic(spec), "test.mosaic", options);
}

async function got(file: SealedFile, args: unknown): Promise<GetAnswer["data"]> {
  const answer = valid(await file.get(args));
  if (!("data" in answer)) throw new Error(`get failed: ${JSON.stringify(answer)}`);
  return answer.data;
}

async function cited(file: SealedFile, args: unknown): Promise<CiteAnswer["data"]> {
  const answer = valid(await file.cite(args));
  if (!("data" in answer)) throw new Error(`cite failed: ${JSON.stringify(answer)}`);
  return answer.data;
}

async function failed(answer: Promise<Answer>): Promise<ErrorAnswer["error"]> {
  const a = valid(await answer);
  if (!("error" in a)) throw new Error(`expected an error: ${JSON.stringify(a).slice(0, 500)}`);
  return a.error;
}

const wellFormed = (s: string): boolean => !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(s);
const chars = (s: string): number => Array.from(s).length;
const H1 = "1".repeat(64);
const H2 = "2".repeat(64);
const H3 = "3".repeat(64);

describe("get: nodes with little (section 8.1)", () => {
  it("a node with no edges has an empty links list", async () => {
    // Section 8.1: link counts per edge type and direction; a node with none has none.
    const file = await open({ edgeTypes: [["rel", "Item", "Item"]], nodes: [{ type: "Item", key: "lonely" }] });
    expect((await got(file, { id: "Item:lonely" })).links).toEqual([]);
    file.close();
  });

  it("an empty mosaic answers any get with unknown_id, not a crash", async () => {
    // Section 8.1: an unknown id MUST be an error, never an empty success.
    const file = await open({ nodes: [] });
    const error = await failed(file.get({ id: "Item:a" }));
    expect(error).toMatchObject({ code: "unknown_id", suggestions: [] });
    expect((await failed(file.cite({ id: "Item:a" }))).code).toBe("unknown_id");
    file.close();
  });

  it("links name only edge types that have edges, each direction counted apart", async () => {
    // Section 8.1: counts per edge type and direction; schema `count` minimum is 1.
    const file = await open({
      edgeTypes: [
        ["a_to", "Item", "Item"],
        ["b_to", "Item", "Item"],
        ["unused", "Item", "Item"],
      ],
      nodes: ["x", "y", "z"].map((key) => ({ type: "Item", key })),
      edges: [
        { type: "a_to", from: "Item:x", to: "Item:y" },
        { type: "a_to", from: "Item:z", to: "Item:y" },
        { type: "b_to", from: "Item:y", to: "Item:x" },
      ],
    });
    const key = (l: { edge: string; direction: string; count: number }) => `${l.edge} ${l.direction} ${l.count}`;
    expect((await got(file, { id: "Item:y" })).links.map(key).sort()).toEqual(["a_to in 2", "b_to out 1"]);
    expect((await got(file, { id: "Item:x" })).links.map(key).sort()).toEqual(["a_to out 1", "b_to in 1"]);
    file.close();
  });

  it("nodes of different types with the same key are different ids", async () => {
    // Section 3.1/8.1: an id is <type>:<key>.
    const file = await open({
      nodes: [
        { type: "Alpha", key: "x", label: "first" },
        { type: "Beta", key: "x", label: "second" },
      ],
    });
    expect((await got(file, { id: "Alpha:x" })).label).toBe("first");
    expect((await got(file, { id: "Beta:x" })).label).toBe("second");
    file.close();
  });

  it("keys with colons, spaces and non-ASCII characters are fetched by their exact id", async () => {
    // Section 8.1: the id is taken whole; only the first colon separates the type.
    const keys = ["a:b:c", "with space", "日本語", "é", "é", "emoji😀"];
    const file = await open({ nodes: keys.map((key) => ({ type: "Item", key })) });
    for (const key of keys) expect((await got(file, { id: `Item:${key}` })).id).toBe(`Item:${key}`);
    // NFC and NFD forms are different bytes, so different ids (UTF-8 byte comparison, CLAUDE.md).
    expect((await got(file, { id: "Item:é" })).id).toBe("Item:é");
    expect((await got(file, { id: "Item:é" })).id).toBe("Item:é");
    file.close();
  });
});

describe("get: aliases in order (sections 3.6, 8.1)", () => {
  it("lists aliases by NOCASE (ASCII folding) then UTF-8 bytes, and counts them all", async () => {
    // Section 3.6: alias order is `text` under NOCASE; NOCASE folds ASCII letters only.
    const aliases = ["b", "A", "c", "É", "é", "Z"];
    const file = await open({ nodes: [{ type: "Item", key: "n", aliases }] });
    const data = await got(file, { id: "Item:n" });
    expect(data.aliases).toEqual(["A", "b", "c", "Z", "É", "é"]);
    expect(data.aliases_total).toBe(6);
    file.close();
  });

  it("orders non-BMP and high-BMP aliases by UTF-8 bytes, not UTF-16 units", async () => {
    // Section 3.6: text is ordered by its UTF-8 bytes. U+FF5E is EF BD 9E; U+1F600 is F0 9F 98 80.
    const file = await open({ nodes: [{ type: "Item", key: "n", aliases: ["\u{1F600}", "～"] }] });
    expect((await got(file, { id: "Item:n" })).aliases).toEqual(["～", "\u{1F600}"]);
    file.close();
  });

  it("exactly 20 aliases are all listed; 21 are cut to 20 with the total", async () => {
    // Section 8.2: lists are cut at 20 items with the total count.
    const make = (n: number) => Array.from({ length: n }, (_, i) => `alias ${String(i).padStart(2, "0")}`);
    const file = await open({
      nodes: [
        { type: "Item", key: "a", aliases: make(20) },
        { type: "Item", key: "b", aliases: make(21) },
      ],
    });
    const a = await got(file, { id: "Item:a" });
    expect([a.aliases.length, a.aliases_total]).toEqual([20, 20]);
    const b = await got(file, { id: "Item:b" });
    expect([b.aliases.length, b.aliases_total]).toEqual([RESULT_LIMIT, 21]);
    expect(b.aliases).toEqual(make(21).slice(0, 20));
    file.close();
  });
});

describe("get: external references in canonical order (section 3.6)", () => {
  it("lists them by system, kind and locator bytes, whatever the order they were given", async () => {
    // Section 3.6: external_ref rows ordered by (nid, system, kind, locator).
    const file = await open({
      nodes: [
        {
          type: "Item",
          key: "n",
          externalRefs: [
            { system: "zeta", kind: "a", locator: '{"k":1}' },
            { system: "alpha", kind: "b", locator: '{"k":2}' },
            { system: "alpha", kind: "a", locator: '{"k":3}' },
            { system: "alpha", kind: "a", locator: '{"k":"é"}' },
          ],
        },
      ],
    });
    const refs = (await got(file, { id: "Item:n" })).external_refs;
    expect(refs.map((r) => `${r.system}/${r.kind}/${JSON.stringify(r.locator)}`)).toEqual([
      'alpha/a/{"k":"é"}',
      'alpha/a/{"k":3}',
      'alpha/b/{"k":2}',
      'zeta/a/{"k":1}',
    ]);
    file.close();
  });
});

describe("get and cite: text limits at the boundary (section 8.2)", () => {
  it("cuts at one character over the limit: 121 labels, 401 summaries, 121 aliases, 601 snippets", async () => {
    const file = await open({
      nodes: [
        {
          type: "Item",
          key: "n",
          label: "l".repeat(121),
          summary: "s".repeat(401),
          aliases: ["a".repeat(121)],
          evidence: [{ snippet: "n".repeat(601) }],
        },
      ],
    });
    const data = await got(file, { id: "Item:n" });
    expect(data.label).toBe("l".repeat(120) + CUT_MARKER);
    expect(data.summary).toBe("s".repeat(400) + CUT_MARKER);
    expect(data.aliases).toEqual(["a".repeat(120) + CUT_MARKER]);
    expect((await cited(file, { id: "Item:n" })).evidence[0]!.snippet).toBe("n".repeat(600) + CUT_MARKER);
    file.close();
  });

  it("never cuts inside a surrogate pair", async () => {
    // Section 8.2 counts characters; an emoji sitting on the cut must stay whole or go whole.
    const label = "a".repeat(119) + "\u{1F600}" + "b".repeat(10);
    const snippet = "a".repeat(599) + "\u{1F600}" + "b".repeat(10);
    const file = await open({ nodes: [{ type: "Item", key: "n", label, evidence: [{ snippet }] }] });
    const data = await got(file, { id: "Item:n" });
    expect(wellFormed(data.label!)).toBe(true);
    expect(data.label).toBe("a".repeat(119) + "\u{1F600}" + CUT_MARKER);
    const s = (await cited(file, { id: "Item:n" })).evidence[0]!.snippet!;
    expect(wellFormed(s)).toBe(true);
    expect(s).toBe("a".repeat(599) + "\u{1F600}" + CUT_MARKER);
    file.close();
  });

  it("keeps newlines and spaces inside a short snippet exactly", async () => {
    const snippet = "  line one\n\tline two  \n";
    const file = await open({ nodes: [{ type: "Item", key: "n", evidence: [{ snippet }] }] });
    expect((await cited(file, { id: "Item:n" })).evidence[0]!.snippet).toBe(snippet);
    file.close();
  });

  it("cuts a very long summary and snippet (200,000 characters) quickly and to the limit", async () => {
    const file = await open({
      nodes: [{ type: "Item", key: "n", summary: "s".repeat(200_000), evidence: [{ snippet: "n".repeat(200_000) }] }],
    });
    const started = performance.now();
    expect(chars((await got(file, { id: "Item:n" })).summary!)).toBe(401);
    expect(chars((await cited(file, { id: "Item:n" })).evidence[0]!.snippet!)).toBe(601);
    expect(performance.now() - started).toBeLessThan(1_000);
    file.close();
  });

  it("cuts text inside nested property values too, and keeps non-text values as they are", async () => {
    // Section 8.2: text from the file MUST be length-limited. Numbers, booleans and null are not text.
    const long = "p".repeat(1000);
    const props = JSON.stringify({ list: [long, 1, true, null], nested: { deep: long }, n: 2.5, b: false, z: null });
    const file = await open({ typeProps: { Item: '{"list":"json","n":"real"}' }, nodes: [{ type: "Item", key: "n", props }] });
    const data = await got(file, { id: "Item:n" });
    const p = data.props as { list: unknown[]; nested: { deep: string }; n: number; b: boolean; z: null };
    expect(p.n).toBe(2.5);
    expect(p.b).toBe(false);
    expect(p.z).toBeNull();
    expect(p.list.slice(1)).toEqual([1, true, null]);
    for (const text of [p.list[0] as string, p.nested.deep]) {
      expect(chars(text)).toBeLessThan(1000);
      expect(text.endsWith(CUT_MARKER)).toBe(true);
    }
    file.close();
  });

  it("answers for a locator and a source id of 5,000 characters without failing the schema", async () => {
    // Section 8.2 limits labels, summaries and snippets only; other text is a spec gap, but the
    // answer must still be valid and not crash.
    const file = await open({ nodes: [{ type: "Item", key: "n", evidence: [{ locator: "file=" + "f".repeat(5000) }] }] });
    const data = await cited(file, { id: "Item:n" });
    expect(data.total).toBe(1);
    file.close();
  });
});

describe("get and cite: hostile arguments and ids (sections 3.8 step 4, 10)", () => {
  const hostile: [string, string][] = [
    ["empty", ""],
    ["a lone colon", ":"],
    ["a NUL character", "Item:a\u0000b"],
    ["a quote and FTS operators", 'Item:"a" OR NEAR(b c) * -d'],
    ["parentheses and a star", "Item:(*)"],
    ["a single quote and SQL", "Item:a'; DROP TABLE node; --"],
    ["a percent and an underscore", "Item:%_"],
    ["a lone surrogate", "Item:\uD800"],
    ["200,000 characters", "Item:" + "x".repeat(200_000)],
    ["only whitespace", "   "],
    ["a newline", "Item:a\nb"],
  ];
  const spec: MosaicSpec = {
    nodes: [
      { type: "Item", key: "a", label: "alpha" },
      { type: "Item", key: "ab", label: "a b" },
    ],
  };

  it.each(hostile)("get with %s is an error answer valid against the schema, never a crash or an empty success", async (_name, id) => {
    const file = await open(spec);
    const started = performance.now();
    const error = await failed(file.get({ id }));
    expect(["unknown_id", "bad_argument"]).toContain(error.code);
    expect(performance.now() - started).toBeLessThan(2_000);
    file.close();
  });

  it.each(hostile)("cite with %s is an error answer valid against the schema", async (_name, id) => {
    const file = await open(spec);
    expect(["unknown_id", "bad_argument"]).toContain((await failed(file.cite({ id }))).code);
    expect(["unknown_id", "bad_argument", "unknown_edge"]).toContain(
      (await failed(file.cite({ from: id, type: "rel", to: "Item:a" }))).code,
    );
    file.close();
  });

  it("an error answer names the tool that failed and the mosaic's hash", async () => {
    const file = await open(spec);
    const g = valid(await file.get({ id: "nope" })) as ErrorAnswer;
    const c = valid(await file.cite({ id: "nope" })) as ErrorAnswer;
    expect([g.tool, c.tool]).toEqual(["get", "cite"]);
    expect([g.mosaic, c.mosaic]).toEqual([file.header.knowledge_hash, file.header.knowledge_hash]);
    file.close();
  });

  it("arguments of the wrong shape are bad_argument: arrays, numbers, empty type, unknown keys", async () => {
    const file = await open(spec);
    for (const args of [{ id: ["Item:a"] }, { id: null }, { id: {} }, 7, true, [{ id: "Item:a" }]]) {
      expect((await failed(file.get(args))).code).toBe("bad_argument");
    }
    for (const args of [
      { from: ["Item:a"], type: "rel", to: "Item:a" },
      { from: "Item:a", type: "rel", to: "Item:a", extra: 1 },
      { id: "Item:a", type: "rel" },
      { id: "Item:a", to: "Item:a" },
      null,
      "Item:a",
    ]) {
      expect(["bad_argument"]).toContain((await failed(file.cite(args))).code);
    }
    file.close();
  });

  it("accepts frozen argument objects and does not change them", async () => {
    const file = await open(spec);
    const args = Object.freeze({ id: "Item:a" });
    expect((await got(file, args)).id).toBe("Item:a");
    expect(args).toEqual({ id: "Item:a" });
    file.close();
  });

  it("a node whose id is longer than the schema's 512 characters still gives a schema-valid answer", async () => {
    // answers.schema.json: `id` has maxLength 512. Whatever the kit chooses, no answer may break the schema.
    const key = "k".repeat(600);
    const file = await open({ nodes: [{ type: "Item", key }, { type: "Item", key: "near" }] });
    const id = `Item:${key}`;
    valid(await file.get({ id }));
    valid(await file.cite({ id }));
    valid(await file.get({ id: "Item:" + "k".repeat(599) }));
    file.close();
  });
});

describe("get and cite: determinism (principle 5, section 8.2)", () => {
  const spec: MosaicSpec = {
    edgeTypes: [["rel", "Item", "Item"]],
    nodes: [
      { type: "Item", key: "a", label: "A", aliases: ["x", "Y", "z"], evidence: [{ snippet: "one" }, { locator: "line=2", snippet: "two" }] },
      { type: "Item", key: "b", label: "B" },
    ],
    edges: [{ type: "rel", from: "Item:a", to: "Item:b" }],
  };

  it("the same call twice, and on a second open of the same bytes, gives the same JSON", async () => {
    const bytes = buildMosaic(spec);
    const one = await openFile(bytes, "a.mosaic");
    const two = await openFile(bytes, "b.mosaic");
    const calls = (f: SealedFile) =>
      Promise.all([
        f.get({ id: "Item:a" }),
        f.cite({ id: "Item:a" }),
        f.cite({ from: "Item:a", type: "rel", to: "Item:b" }),
        f.get({ id: "zzz" }),
      ]);
    const first = JSON.stringify(await calls(one));
    expect(JSON.stringify(await calls(one))).toBe(first);
    expect(JSON.stringify(await calls(two))).toBe(first);
    one.close();
    two.close();
  });

  it("calls made together give what the same calls made one after the other give", async () => {
    const file = await openFile(buildMosaic(spec), "a.mosaic");
    const ids = ["Item:a", "Item:b", "Item:nope", "Item:a"];
    const together = await Promise.all(ids.map((id) => file.get({ id })));
    const apart: Answer[] = [];
    for (const id of ids) apart.push(await file.get({ id }));
    expect(JSON.stringify(together)).toBe(JSON.stringify(apart));
    file.close();
  });

  it("does not change the file: the answers are the same after many calls", async () => {
    const file = await openFile(buildMosaic(spec), "a.mosaic");
    const before = JSON.stringify(await file.get({ id: "Item:a" }));
    for (let i = 0; i < 50; i++) await file.cite({ id: "Item:a" });
    expect(JSON.stringify(await file.get({ id: "Item:a" }))).toBe(before);
    file.close();
  });
});

describe("cite: evidence rows (sections 3.5, 3.6, 8.1)", () => {
  it("keeps confidence 0 and 1 as numbers on inferred rows, and null on extracted rows", async () => {
    // Section 3.5: inferred rows have a confidence from 0 to 1, extracted rows NULL.
    const file = await open({
      nodes: [
        {
          type: "Item",
          key: "n",
          evidence: [
            { locator: "line=1", method: "inferred", confidence: 0 },
            { locator: "line=2", method: "inferred", confidence: 1 },
            { locator: "line=3", method: "extracted" },
          ],
        },
      ],
    });
    const rows = (await cited(file, { id: "Item:n" })).evidence;
    expect(rows.map((r) => [r.method, r.confidence])).toEqual([
      ["inferred", 0],
      ["inferred", 1],
      ["extracted", null],
    ]);
    file.close();
  });

  it("gives via as the array it is, innermost first, and leaves it out when there is none", async () => {
    // Section 3.5: via lists the knowledge hashes the evidence passed through, innermost first.
    const file = await open({
      nodes: [
        {
          type: "Item",
          key: "n",
          evidence: [
            { locator: "line=1", via: [H2, H1, H3] },
            { locator: "line=2" },
          ],
        },
      ],
    });
    const rows = (await cited(file, { id: "Item:n" })).evidence;
    expect(rows[0]!.via).toEqual([H2, H1, H3]);
    expect("via" in rows[1]!).toBe(false);
    file.close();
  });

  it("two rows that differ only in via are both returned", async () => {
    // Section 3.5: the same citation can appear twice when it differs only in via.
    const file = await open({
      nodes: [{ type: "Item", key: "n", evidence: [{ locator: "line=1", via: [H1] }, { locator: "line=1", via: [H2] }] }],
    });
    const data = await cited(file, { id: "Item:n" });
    expect(data.total).toBe(2);
    expect(data.evidence.map((e) => e.via)).toEqual([[H1], [H2]]);
    file.close();
  });

  it("includes rows about one property of the node, and shows no field the schema does not have", async () => {
    // Section 3.5: each row has exactly one subject; a row with `prop` is still the node's evidence.
    const file = await open({
      nodes: [{ type: "Item", key: "n", evidence: [{ locator: "line=1", prop: "label" }, { locator: "line=2" }] }],
    });
    const data = await cited(file, { id: "Item:n" });
    expect(data.total).toBe(2);
    expect(data.evidence.map((e) => e.locator)).toEqual(["line=1", "line=2"]);
    file.close();
  });

  it("gives each row its own source id and hash, sources in sid order", async () => {
    // Section 3.2/3.6: evidence names the original source; rows ordered by (sid, locator, ...).
    const file = await open({
      sources: [
        { id: "b/second", hash: H2 },
        { id: "a/first", hash: H1 },
      ],
      nodes: [
        {
          type: "Item",
          key: "n",
          evidence: [
            { source: "b/second", locator: "line=1" },
            { source: "a/first", locator: "line=9" },
            { source: "doc", locator: "line=5" },
          ],
        },
      ],
    });
    const rows = (await cited(file, { id: "Item:n" })).evidence;
    expect(rows.map((r) => [r.source, r.source_hash])).toEqual([
      ["a/first", H1],
      ["b/second", H2],
      ["doc", DOC_HASH],
    ]);
    file.close();
  });

  it("orders rows with the same source by locator bytes, not UTF-16 units", async () => {
    // Section 3.6: ties by (sid, locator, ...) with text in UTF-8 byte order.
    const file = await open({
      nodes: [{ type: "Item", key: "n", evidence: [{ locator: "file=\u{1F600}" }, { locator: "file=～" }, { locator: "file=z" }] }],
    });
    expect((await cited(file, { id: "Item:n" })).evidence.map((e) => e.locator)).toEqual(["file=z", "file=～", "file=\u{1F600}"]);
    file.close();
  });

  it("keeps locator names it does not know (section 3.5: readers MUST keep unknown ones)", async () => {
    const locator = "file=a.txt;zzz=1;line=2;entry=x";
    const file = await open({ nodes: [{ type: "Item", key: "n", evidence: [{ locator }] }] });
    expect((await cited(file, { id: "Item:n" })).evidence[0]!.locator).toBe(locator);
    file.close();
  });

  it("an edge with exactly 20 rows has all of them; with 21 it has 20 and the total 21", async () => {
    // Section 8.2: lists are cut at 20 with the total.
    const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ locator: `line=${String(i).padStart(2, "0")}` }));
    const file = await open({
      edgeTypes: [["rel", "Item", "Item"]],
      nodes: [{ type: "Item", key: "a" }, { type: "Item", key: "b" }, { type: "Item", key: "c" }],
      edges: [
        { type: "rel", from: "Item:a", to: "Item:b", evidence: rows(20) },
        { type: "rel", from: "Item:a", to: "Item:c", evidence: rows(21) },
      ],
    });
    const twenty = await cited(file, { from: "Item:a", type: "rel", to: "Item:b" });
    expect([twenty.evidence.length, twenty.total]).toEqual([20, 20]);
    const more = await cited(file, { from: "Item:a", type: "rel", to: "Item:c" });
    expect([more.evidence.length, more.total]).toEqual([20, 21]);
    expect(more.evidence.map((e) => e.locator)).toEqual(rows(21).slice(0, 20).map((r) => r.locator));
    file.close();
  });

  it("a self-loop edge is cited by the same node at both ends", async () => {
    const file = await open({
      edgeTypes: [["next", "Item", "Item"]],
      nodes: [{ type: "Item", key: "a" }],
      edges: [{ type: "next", from: "Item:a", to: "Item:a", evidence: [{ locator: "line=1", snippet: "loop" }] }],
    });
    const data = await cited(file, { from: "Item:a", type: "next", to: "Item:a" });
    expect(data.subject).toEqual({ from: "Item:a", type: "next", to: "Item:a" });
    expect(data.evidence.map((e) => e.snippet)).toEqual(["loop"]);
    file.close();
  });

  it("the same two nodes joined by two edge types keep their evidence apart", async () => {
    const file = await open({
      edgeTypes: [
        ["one", "Item", "Item"],
        ["two", "Item", "Item"],
      ],
      nodes: [{ type: "Item", key: "a" }, { type: "Item", key: "b" }],
      edges: [
        { type: "one", from: "Item:a", to: "Item:b", evidence: [{ snippet: "by one" }] },
        { type: "two", from: "Item:a", to: "Item:b", evidence: [{ snippet: "by two" }] },
      ],
    });
    expect((await cited(file, { from: "Item:a", type: "one", to: "Item:b" })).evidence.map((e) => e.snippet)).toEqual(["by one"]);
    expect((await cited(file, { from: "Item:a", type: "two", to: "Item:b" })).evidence.map((e) => e.snippet)).toEqual(["by two"]);
    file.close();
  });

  it("an edge between two known nodes with an undeclared type is unknown_edge, not unknown_id", async () => {
    const file = await open({ nodes: [{ type: "Item", key: "a" }, { type: "Item", key: "b" }] });
    expect((await failed(file.cite({ from: "Item:a", type: "rel", to: "Item:b" }))).code).toBe("unknown_edge");
    file.close();
  });

  it("the edge type is taken exactly: another case is no edge", async () => {
    const file = await open({
      edgeTypes: [["rel", "Item", "Item"]],
      nodes: [{ type: "Item", key: "a" }, { type: "Item", key: "b" }],
      edges: [{ type: "rel", from: "Item:a", to: "Item:b" }],
    });
    expect((await failed(file.cite({ from: "Item:a", type: "REL", to: "Item:b" }))).code).toBe("unknown_edge");
    expect((await failed(file.cite({ from: "Item:a", type: "rel ", to: "Item:b" }))).code).toBe("unknown_edge");
    file.close();
  });
});

describe("get and cite: unknown ids and the closest matches (section 8.1)", () => {
  it("suggestions are ids of nodes that exist", async () => {
    const nodes = ["alpha", "alphabet", "beta", "gamma"].map((key) => ({ type: "Item", key, label: `the ${key} thing` }));
    const file = await open({ nodes });
    const known = new Set(nodes.map((n) => `Item:${n.key}`));
    for (const id of ["alph", "Item:alpa", "the beta", "gamma thing", "Item:"]) {
      for (const error of [await failed(file.get({ id })), await failed(file.cite({ id }))]) {
        for (const s of error.suggestions) expect(known.has(s)).toBe(true);
        expect(new Set(error.suggestions).size).toBe(error.suggestions.length);
      }
    }
    file.close();
  });

  it("a query that find answers with one exact match is named first in the suggestions", async () => {
    const file = await open({
      nodes: [
        { type: "Item", key: "target", label: "something else" },
        { type: "Item", key: "other", label: "target in the text only" },
      ],
    });
    const error = await failed(file.get({ id: "target" }));
    expect(error.suggestions[0]).toBe("Item:target");
    file.close();
  });

  it("the same unknown id twice gives the same error", async () => {
    const file = await open({ nodes: [{ type: "Item", key: "a", label: "same words" }, { type: "Item", key: "b", label: "same words" }] });
    const one = await file.get({ id: "same words" });
    const two = await file.get({ id: "same words" });
    expect(JSON.stringify(one)).toBe(JSON.stringify(two));
    file.close();
  });

  it("the message does not copy a label, alias or snippet of the file, only the caller's argument", async () => {
    const secret = "SECRET-LABEL-TEXT";
    const file = await open({ nodes: [{ type: "Item", key: "k", label: secret, aliases: [secret + "-alias"], evidence: [{ snippet: secret + "-snip" }] }] });
    for (const error of [await failed(file.get({ id: secret })), await failed(file.cite({ id: secret }))]) {
      expect(error.message.split(secret).length).toBeLessThanOrEqual(2);
      expect(error.message).not.toContain(secret + "-alias");
      expect(error.message).not.toContain(secret + "-snip");
      expect(error.suggestions).toEqual(["Item:k"]);
    }
    file.close();
  });

  it("an error message is within the schema's 400 characters whatever the argument", async () => {
    const file = await open({ nodes: [{ type: "Item", key: "a" }] });
    const error = await failed(file.get({ id: "Item:" + "\u{1F600}".repeat(400) }));
    expect(chars(error.message)).toBeLessThanOrEqual(400);
    file.close();
  });
});

describe("get and cite: time bound (section 3.8 step 4)", () => {
  it("a call stopped by the bound leaves the file usable for the next call", async () => {
    const n = 5_000;
    const bytes = buildMosaic({
      nodes: Array.from({ length: n }, (_, i) => ({
        type: "Item",
        key: `i${String(i).padStart(5, "0")}`,
        ...(i === 0 ? { aliases: Array.from({ length: n }, (_, j) => `alias ${j}`) } : {}),
      })),
    });
    const stopped = await openFile(bytes, "large.mosaic", { timeLimitMs: 0.01 });
    expect((await failed(stopped.get({ id: "Item:i00000" }))).code).toBe("limit_exceeded");
    stopped.close();
    // The same bytes with the default bound answer in full: a stop is per call, not per file.
    const normal = await openFile(bytes, "large.mosaic");
    expect((await got(normal, { id: "Item:i00000" })).aliases_total).toBe(n);
    normal.close();
  }, 60_000);

  it("a limit_exceeded error names the bound it was given", async () => {
    const n = 5_000;
    const bytes = buildMosaic({
      nodes: Array.from({ length: n }, (_, i) => ({
        type: "Item",
        key: `i${String(i).padStart(5, "0")}`,
        ...(i === 0 ? { evidence: Array.from({ length: n }, (_, j) => ({ locator: `line=${j}` })) } : {}),
      })),
    });
    for (const bound of [0.02, 0.05]) {
      const file = await openFile(bytes, "large.mosaic", { timeLimitMs: bound });
      const error = await failed(file.cite({ id: "Item:i00000" }));
      expect(error.code).toBe("limit_exceeded");
      expect(error.message).toContain(String(bound));
      file.close();
    }
  }, 60_000);
});
