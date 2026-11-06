// Edge cases for the maintainer's answers on #110 (readings A, D and H) for M2.4, written from the
// spec's words (sections 8.1, 8.2, 3.4, 3.5, 3.6, 3.8 step 4, 10, spec/answers.schema.json), not
// from the implementation:
//   Q1 A: text section 8.2 names no limit for is cut at 400 characters with the marker.
//   Q2 A (reading D): get's external_refs and links are cut at 20, each with a total field.
//   Q3 B (reading H): cite takes an optional qualifier; with it, that edge's evidence only, and
//   subject echoes the qualifier.
import { Ajv2020 } from "ajv/dist/2020.js";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  CUT_MARKER,
  openFile,
  type Answer,
  type CiteAnswer,
  type ErrorAnswer,
  type GetAnswer,
  type SealedFile,
} from "../src/index.js";
import { buildMosaic, type EdgeSpec, type MosaicSpec } from "./build-mosaic.js";

const repo = (path: string): string => fileURLToPath(new URL(`../../${path}`, import.meta.url));
const schema = JSON.parse(readFileSync(repo("spec/answers.schema.json"), "utf8")) as object;
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);

function valid<T extends Answer>(answer: T): T {
  if (!validate(answer)) {
    throw new Error(`answer is not valid: ${JSON.stringify(validate.errors)}\n${JSON.stringify(answer).slice(0, 2000)}`);
  }
  return answer;
}

async function open(spec: MosaicSpec): Promise<SealedFile> {
  return openFile(buildMosaic(spec), "test.mosaic");
}

async function got(file: SealedFile, args: unknown): Promise<GetAnswer["data"]> {
  const answer = valid(await file.get(args));
  if (!("data" in answer)) throw new Error(`get failed: ${JSON.stringify(answer).slice(0, 500)}`);
  return answer.data;
}

async function cited(file: SealedFile, args: unknown): Promise<CiteAnswer["data"]> {
  const answer = valid(await file.cite(args));
  if (!("data" in answer)) throw new Error(`cite failed: ${JSON.stringify(answer).slice(0, 500)}`);
  return answer.data;
}

async function failed(answer: Promise<Answer>): Promise<ErrorAnswer["error"]> {
  const a = valid(await answer);
  if (!("error" in a)) throw new Error(`expected an error: ${JSON.stringify(a).slice(0, 500)}`);
  return a.error;
}

const wellFormed = (s: string): boolean => !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(s);
const chars = (s: string): number => Array.from(s).length;
const pad = (i: number, width = 3): string => String(i).padStart(width, "0");
const EDGE: Pick<MosaicSpec, "edgeTypes"> = { edgeTypes: [["feeds", "Item", "Item"]] };
const PAIR = [
  { type: "Item", key: "a" },
  { type: "Item", key: "b" },
];
const FEEDS = { from: "Item:a", type: "feeds", to: "Item:b" };

// ---------------------------------------------------------------------------------------------
// Q1 A: other text from the file is cut at 400 characters with the marker (section 8.2).

describe("Q1 A: text with no named limit is cut at 400 characters (section 8.2)", () => {
  it("leaves a property text of exactly 400 characters whole and cuts 401 to 400 plus the marker", async () => {
    const file = await open({
      nodes: [{ type: "Item", key: "a", props: JSON.stringify({ at: "x".repeat(400), over: "y".repeat(401) }) }],
    });
    const props = (await got(file, { id: "Item:a" })).props as Record<string, string>;
    expect(props["at"]).toBe("x".repeat(400));
    expect(props["over"]).toBe("y".repeat(400) + CUT_MARKER);
    file.close();
  });

  it("counts characters, not UTF-16 units, at 400, and never cuts inside a surrogate pair", async () => {
    const whole = "\u{1F600}".repeat(400);
    const over = "\u{1F600}".repeat(401);
    const file = await open({ nodes: [{ type: "Item", key: "a", props: JSON.stringify({ whole, over }) }] });
    const props = (await got(file, { id: "Item:a" })).props as Record<string, string>;
    expect(props["whole"]).toBe(whole);
    expect(props["over"]).toBe(whole + CUT_MARKER);
    expect(wellFormed(props["over"]!)).toBe(true);
    file.close();
  });

  it("cuts the text of every nested position: arrays of arrays, objects in arrays, and their keys", async () => {
    const long = "z".repeat(900);
    const props = JSON.stringify({ a: [[long], { [long]: long }], b: { c: { d: [long] } } });
    const file = await open({ nodes: [{ type: "Item", key: "a", props }] });
    const cutText = "z".repeat(400) + CUT_MARKER;
    expect((await got(file, { id: "Item:a" })).props).toEqual({
      a: [[cutText], { [cutText]: cutText }],
      b: { c: { d: [cutText] } },
    });
    file.close();
  });

  it("leaves numbers, booleans and null in properties as they are, however large the text next to them", async () => {
    const props = '{"i":-0,"f":1.5e300,"t":true,"f2":false,"n":null,"s":"' + "q".repeat(900) + '"}';
    const file = await open({ nodes: [{ type: "Item", key: "a", props }] });
    const p = (await got(file, { id: "Item:a" })).props as Record<string, unknown>;
    expect(p["f"]).toBe(1.5e300);
    expect(p["t"]).toBe(true);
    expect(p["f2"]).toBe(false);
    expect(p["n"]).toBeNull();
    expect(p["s"]).toBe("q".repeat(400) + CUT_MARKER);
    file.close();
  });

  it("keeps a property text that holds the escape of a NUL (U+0000) and still answers", async () => {
    // Section 3.8 step 4 (untrusted data): NUL-containing text is data, not a terminator.
    const file = await open({ nodes: [{ type: "Item", key: "a", props: '{"k":"ab\\u0000cd"}' }] });
    expect((await got(file, { id: "Item:a" })).props).toEqual({ k: "ab\u0000cd" });
    file.close();
  });

  it("cuts a locator of exactly 400 characters never, of 401 characters to 400 plus the marker", async () => {
    const at = "file=" + "l".repeat(395);
    const over = "file=" + "l".repeat(396);
    expect(chars(at)).toBe(400);
    const file = await open({
      nodes: [{ type: "Item", key: "a", evidence: [{ locator: at }, { locator: over }] }],
    });
    const locators = (await cited(file, { id: "Item:a" })).evidence.map((e) => e.locator).sort();
    expect(locators).toEqual([at, Array.from(over).slice(0, 400).join("") + CUT_MARKER].sort());
    file.close();
  });

  it("cuts a locator on an edge's evidence too", async () => {
    const locator = "file=" + "m".repeat(900);
    const file = await open({
      ...EDGE,
      nodes: PAIR,
      edges: [{ type: "feeds", from: "Item:a", to: "Item:b", evidence: [{ locator }] }],
    });
    const rows = (await cited(file, FEEDS)).evidence;
    expect(rows[0]!.locator).toBe(Array.from(locator).slice(0, 400).join("") + CUT_MARKER);
    file.close();
  });

  it("cuts a source id of 900 characters at 400 and keeps its hash whole", async () => {
    const id = "src/" + "s".repeat(896);
    const hash = "e".repeat(64);
    const file = await open({
      sources: [{ id, kind: "file", hash }],
      nodes: [{ type: "Item", key: "a", evidence: [{ source: id }] }],
    });
    const row = (await cited(file, { id: "Item:a" })).evidence[0]!;
    expect(row.source).toBe(Array.from(id).slice(0, 400).join("") + CUT_MARKER);
    expect(row.source_hash).toBe(hash);
    file.close();
  });

  it("cuts the system, the kind and the locator texts of an external reference", async () => {
    const system = "p".repeat(700);
    const kind = "k".repeat(700);
    const file = await open({
      nodes: [
        {
          type: "Item",
          key: "a",
          externalRefs: [{ system, kind, locator: JSON.stringify({ series: "v".repeat(700), ["w".repeat(700)]: 1 }) }],
        },
      ],
    });
    const ref = (await got(file, { id: "Item:a" })).external_refs[0]!;
    expect(ref.system).toBe("p".repeat(400) + CUT_MARKER);
    expect(ref.kind).toBe("k".repeat(400) + CUT_MARKER);
    expect(ref.locator).toEqual({ series: "v".repeat(400) + CUT_MARKER, ["w".repeat(400) + CUT_MARKER]: 1 });
    file.close();
  });

  it("keeps the named limits: a label of 400 characters is still cut at 120, a snippet at 600", async () => {
    // The 400 default must not replace the limits section 8.2 names.
    const file = await open({
      nodes: [{ type: "Item", key: "a", label: "l".repeat(400), snippets: ["n".repeat(500)] }],
    });
    expect((await got(file, { id: "Item:a" })).label).toBe("l".repeat(120) + CUT_MARKER);
    expect((await cited(file, { id: "Item:a" })).evidence[0]!.snippet).toBe("n".repeat(500));
    file.close();
  });

  it("answers for properties nested 800 levels deep without throwing", async () => {
    // Section 3.8 step 4 and section 10: hostile shapes must not crash the kit.
    const depth = 800;
    const props = '{"d":' + "[".repeat(depth) + "]".repeat(depth) + "}";
    const file = await open({ nodes: [{ type: "Item", key: "a", props }] });
    const answer = valid(await file.get({ id: "Item:a" }));
    expect(answer.tool).toBe("get");
    expect("data" in answer || "error" in answer).toBe(true);
    file.close();
  });

  it("gives the same cut twice and after a second open of the same bytes", async () => {
    const bytes = buildMosaic({
      nodes: [{ type: "Item", key: "a", props: JSON.stringify({ t: "é".repeat(1000) }), evidence: [{ locator: "file=" + "é".repeat(500) }] }],
    });
    const one = await openFile(bytes, "one.mosaic");
    const two = await openFile(bytes, "two.mosaic");
    const first = JSON.stringify([await one.get({ id: "Item:a" }), await one.cite({ id: "Item:a" })]);
    expect(JSON.stringify([await one.get({ id: "Item:a" }), await one.cite({ id: "Item:a" })])).toBe(first);
    expect(JSON.stringify([await two.get({ id: "Item:a" }), await two.cite({ id: "Item:a" })])).toBe(first);
    one.close();
    two.close();
  });
});

// ---------------------------------------------------------------------------------------------
// Q2 reading D: external_refs and links are cut at 20 with a total field each (section 8.2).

describe("Q2 reading D: external_refs and links cut at 20 with their totals (section 8.2)", () => {
  const refs = (n: number) =>
    Array.from({ length: n }, (_, i) => ({ system: "sys", kind: "record", locator: `{"n":"${pad(i)}"}` }));

  it("keeps exactly 20 external references whole, and cuts 21 to 20 with the total 21", async () => {
    const file = await open({
      nodes: [
        { type: "Item", key: "twenty", externalRefs: refs(20) },
        { type: "Item", key: "twentyone", externalRefs: refs(21) },
      ],
    });
    const twenty = await got(file, { id: "Item:twenty" });
    expect(twenty.external_refs).toHaveLength(20);
    expect(twenty.external_refs_total ?? 20).toBe(20);
    const more = await got(file, { id: "Item:twentyone" });
    expect(more.external_refs).toHaveLength(20);
    expect(more.external_refs_total).toBe(21);
    expect(more.external_refs.map((r) => r.locator["n"])).toEqual(Array.from({ length: 20 }, (_, i) => pad(i)));
    file.close();
  });

  it("cuts 1,000 external references to the first 20 in canonical order with the total 1,000", async () => {
    // Section 3.6: external_ref ordered by (nid, system, kind, locator), the cut keeps the first 20.
    const many = [
      ...Array.from({ length: 500 }, (_, i) => ({ system: "zz", kind: "a", locator: `{"n":"${pad(i)}"}` })),
      ...Array.from({ length: 500 }, (_, i) => ({ system: "aa", kind: "b", locator: `{"n":"${pad(i)}"}` })),
    ];
    const file = await open({ nodes: [{ type: "Item", key: "a", externalRefs: many }] });
    const data = await got(file, { id: "Item:a" });
    expect(data.external_refs_total).toBe(1000);
    expect(data.external_refs).toHaveLength(20);
    expect(data.external_refs.every((r) => r.system === "aa" && r.kind === "b")).toBe(true);
    expect(data.external_refs.map((r) => r.locator["n"])).toEqual(Array.from({ length: 20 }, (_, i) => pad(i)));
    file.close();
  });

  it("counts only the node's own external references, not those of the nodes around it", async () => {
    const file = await open({
      nodes: [
        { type: "Item", key: "a", externalRefs: refs(3) },
        { type: "Item", key: "b", externalRefs: refs(25) },
        { type: "Item", key: "c" },
      ],
    });
    const a = await got(file, { id: "Item:a" });
    expect([a.external_refs.length, a.external_refs_total ?? 3]).toEqual([3, 3]);
    const c = await got(file, { id: "Item:c" });
    expect(c.external_refs).toEqual([]);
    expect(c.external_refs_total ?? 0).toBe(0);
    expect((await got(file, { id: "Item:b" })).external_refs_total).toBe(25);
    file.close();
  });

  const groups = (n: number) => {
    // n edge types, each with one out edge a -> b: n link groups at node a.
    const edgeTypes = Array.from({ length: n }, (_, i) => [`rel${pad(i)}`, "Item", "Item"] as [string, string, string]);
    const edges: EdgeSpec[] = edgeTypes.map(([type]) => ({ type, from: "Item:a", to: "Item:b" }));
    return { edgeTypes, edges };
  };

  it("keeps exactly 20 link groups whole, and cuts 21 to 20 with the total 21", async () => {
    const twenty = await open({ ...groups(20), nodes: PAIR });
    const d20 = await got(twenty, { id: "Item:a" });
    expect(d20.links).toHaveLength(20);
    expect(d20.links_total ?? 20).toBe(20);
    twenty.close();
    const more = await open({ ...groups(21), nodes: PAIR });
    const d21 = await got(more, { id: "Item:a" });
    expect(d21.links).toHaveLength(20);
    expect(d21.links_total).toBe(21);
    expect(d21.links.map((l) => l.edge)).toEqual(Array.from({ length: 20 }, (_, i) => `rel${pad(i)}`));
    more.close();
  });

  it("counts link groups, not edges: 30 edges of one type and direction are one group of 30", async () => {
    const nodes = [{ type: "Item", key: "hub" }, ...Array.from({ length: 30 }, (_, i) => ({ type: "Item", key: `n${pad(i)}` }))];
    const edges: EdgeSpec[] = nodes.slice(1).map((n) => ({ type: "feeds", from: "Item:hub", to: `Item:${n.key}` }));
    const file = await open({ ...EDGE, nodes, edges });
    const data = await got(file, { id: "Item:hub" });
    expect(data.links).toEqual([{ edge: "feeds", direction: "out", count: 30 }]);
    expect(data.links_total ?? 1).toBe(1);
    file.close();
  });

  it("lists the cut link groups in the same order whatever the order the edges were given", async () => {
    // Principle 5 and section 3.6: same content, same bytes. 30 groups, edges given in two orders.
    const { edgeTypes, edges } = groups(30);
    const forward = await open({ edgeTypes, nodes: PAIR, edges });
    const backward = await open({ edgeTypes: [...edgeTypes].reverse(), nodes: [...PAIR].reverse(), edges: [...edges].reverse() });
    const one = await got(forward, { id: "Item:a" });
    const two = await got(backward, { id: "Item:a" });
    expect(JSON.stringify(two)).toBe(JSON.stringify(one));
    expect(one.links_total).toBe(30);
    forward.close();
    backward.close();
  });

  it("orders link groups by edge type in UTF-8 byte order, out before in (digits < underscore < letters)", async () => {
    // Assumption 3 (accepted): by edge type bytes, `out` before `in`.
    const file = await open({
      edgeTypes: [
        ["ab", "Item", "Item"],
        ["a_", "Item", "Item"],
        ["a1", "Item", "Item"],
      ],
      nodes: PAIR,
      edges: [
        { type: "ab", from: "Item:a", to: "Item:b" },
        { type: "ab", from: "Item:b", to: "Item:a" },
        { type: "a_", from: "Item:a", to: "Item:b" },
        { type: "a1", from: "Item:b", to: "Item:a" },
      ],
    });
    const links = (await got(file, { id: "Item:a" })).links.map((l) => `${l.edge} ${l.direction}`);
    expect(links).toEqual(["a1 in", "a_ out", "ab out", "ab in"]);
    file.close();
  });

  it("cuts aliases, external references and links of one node independently, each with its own total", async () => {
    const { edgeTypes, edges } = groups(22);
    const file = await open({
      edgeTypes,
      nodes: [
        { type: "Item", key: "a", aliases: Array.from({ length: 23 }, (_, i) => `alias ${pad(i)}`), externalRefs: refs(24) },
        { type: "Item", key: "b" },
      ],
      edges,
    });
    const data = await got(file, { id: "Item:a" });
    expect([data.aliases.length, data.aliases_total]).toEqual([20, 23]);
    expect([data.external_refs.length, data.external_refs_total]).toEqual([20, 24]);
    expect([data.links.length, data.links_total]).toEqual([20, 22]);
    file.close();
  });

  it("keeps a totals field an integer of at least the list's length, whatever the node", async () => {
    const file = await open({
      ...EDGE,
      nodes: [{ type: "Item", key: "a", externalRefs: refs(2) }, { type: "Item", key: "b" }],
      edges: [{ type: "feeds", from: "Item:a", to: "Item:b" }],
    });
    for (const id of ["Item:a", "Item:b"]) {
      const d = await got(file, { id });
      for (const [list, total] of [
        [d.external_refs, d.external_refs_total],
        [d.links, d.links_total],
        [d.aliases, d.aliases_total],
      ] as const) {
        if (total !== undefined) {
          expect(Number.isInteger(total)).toBe(true);
          expect(total).toBeGreaterThanOrEqual(list.length);
        }
      }
    }
    file.close();
  });
});

// ---------------------------------------------------------------------------------------------
// Q3 reading H: cite takes an optional qualifier (sections 3.4, 8.1).

describe("Q3 reading H: cite with an optional qualifier (sections 3.4, 8.1)", () => {
  const QUALIFIED: MosaicSpec = {
    ...EDGE,
    sources: [{ id: "other", kind: "file", hash: "b".repeat(64) }],
    nodes: PAIR,
    edges: [
      { type: "feeds", from: "Item:a", to: "Item:b", qualifier: "", evidence: [{ locator: "line=1", snippet: "plain" }] },
      { type: "feeds", from: "Item:a", to: "Item:b", qualifier: "backup", evidence: [{ locator: "line=2", snippet: "backup 1", source: "other" }, { locator: "line=3", snippet: "backup 2", source: "other" }] },
      { type: "feeds", from: "Item:a", to: "Item:b", qualifier: "Backup", evidence: [{ locator: "line=4", snippet: "capital" }] },
    ],
  };

  it("without a qualifier, the subject has exactly from, type and to, and no qualifier key", async () => {
    const file = await open(QUALIFIED);
    const data = await cited(file, FEEDS);
    expect(Object.keys(data.subject as object).sort()).toEqual(["from", "to", "type"]);
    file.close();
  });

  it("without a qualifier, a pair with one unqualified edge has no qualifier key either", async () => {
    const file = await open({ ...EDGE, nodes: PAIR, edges: [{ type: "feeds", from: "Item:a", to: "Item:b" }] });
    const data = await cited(file, FEEDS);
    expect(Object.keys(data.subject as object).sort()).toEqual(["from", "to", "type"]);
    expect(data.total).toBe(1);
    file.close();
  });

  it("without a qualifier, gives the evidence of every edge of the pair in the edges' canonical order", async () => {
    // Section 3.6: edge ordered by qualifier bytes ("" < "Backup" < "backup"), evidence by eid.
    const file = await open(QUALIFIED);
    const data = await cited(file, FEEDS);
    expect(data.total).toBe(4);
    expect(data.evidence.map((e) => e.snippet)).toEqual(["plain", "capital", "backup 1", "backup 2"]);
    file.close();
  });

  it("with a qualifier, gives that edge's rows only, with their own sources and hashes", async () => {
    const file = await open(QUALIFIED);
    const data = await cited(file, { ...FEEDS, qualifier: "backup" });
    expect(data.subject).toEqual({ ...FEEDS, qualifier: "backup" });
    expect(data.total).toBe(2);
    expect(data.evidence.map((e) => [e.source, e.source_hash, e.snippet])).toEqual([
      ["other", "b".repeat(64), "backup 1"],
      ["other", "b".repeat(64), "backup 2"],
    ]);
    file.close();
  });

  it("takes the qualifier exactly: case, spaces and prefixes make another (or no) edge", async () => {
    const file = await open(QUALIFIED);
    expect((await cited(file, { ...FEEDS, qualifier: "Backup" })).evidence.map((e) => e.snippet)).toEqual(["capital"]);
    for (const qualifier of ["BACKUP", "backup ", " backup", "back", "backup\u0000", "backups"]) {
      expect((await failed(file.cite({ ...FEEDS, qualifier }))).code).toBe("unknown_edge");
    }
    file.close();
  });

  it("an explicit empty qualifier is the unqualified edge, which is not 'every edge'", async () => {
    const file = await open(QUALIFIED);
    const data = await cited(file, { ...FEEDS, qualifier: "" });
    expect(data.subject).toEqual({ ...FEEDS, qualifier: "" });
    expect(data.total).toBe(1);
    expect(data.evidence.map((e) => e.snippet)).toEqual(["plain"]);
    file.close();
  });

  it("an explicit empty qualifier on a pair whose only edge is qualified is unknown_edge, never that edge's rows", async () => {
    // Section 3.4: an edge is identified by (src, type, dst, qualifier); (a, feeds, b, "") is not in the file.
    const file = await open({
      ...EDGE,
      nodes: PAIR,
      edges: [{ type: "feeds", from: "Item:a", to: "Item:b", qualifier: "only" }],
    });
    expect((await failed(file.cite({ ...FEEDS, qualifier: "" }))).code).toBe("unknown_edge");
    expect((await cited(file, { ...FEEDS, qualifier: "only" })).total).toBe(1);
    expect((await cited(file, FEEDS)).total).toBe(1);
    file.close();
  });

  it("tells apart qualifiers that differ only in Unicode normalisation, by bytes", async () => {
    const nfc = "é";
    const nfd = "é";
    const file = await open({
      ...EDGE,
      nodes: PAIR,
      edges: [
        { type: "feeds", from: "Item:a", to: "Item:b", qualifier: nfc, evidence: [{ snippet: "nfc" }] },
        { type: "feeds", from: "Item:a", to: "Item:b", qualifier: nfd, evidence: [{ snippet: "nfd" }] },
      ],
    });
    expect((await cited(file, { ...FEEDS, qualifier: nfc })).evidence.map((e) => e.snippet)).toEqual(["nfc"]);
    expect((await cited(file, { ...FEEDS, qualifier: nfd })).evidence.map((e) => e.snippet)).toEqual(["nfd"]);
    expect((await cited(file, { ...FEEDS, qualifier: nfd })).subject).toEqual({ ...FEEDS, qualifier: nfd });
    file.close();
  });

  it("echoes a qualifier of non-ASCII characters and spaces exactly as the caller gave it", async () => {
    const qualifier = " zurück \u{1F600} ";
    const file = await open({
      ...EDGE,
      nodes: PAIR,
      edges: [{ type: "feeds", from: "Item:a", to: "Item:b", qualifier }],
    });
    expect((await cited(file, { ...FEEDS, qualifier })).subject).toEqual({ ...FEEDS, qualifier });
    file.close();
  });

  it("cuts a qualifier's rows at 20 with the total, and the pair's rows at 20 with the total over all edges", async () => {
    // Section 8.2: lists are cut at 20 items with the total count.
    const rows = (prefix: string, n: number) => Array.from({ length: n }, (_, i) => ({ locator: `${prefix}=${pad(i)}` }));
    const file = await open({
      ...EDGE,
      nodes: PAIR,
      edges: [
        { type: "feeds", from: "Item:a", to: "Item:b", qualifier: "x", evidence: rows("x", 15) },
        { type: "feeds", from: "Item:a", to: "Item:b", qualifier: "y", evidence: rows("y", 21) },
      ],
    });
    const all = await cited(file, FEEDS);
    expect([all.evidence.length, all.total]).toEqual([20, 36]);
    const x = await cited(file, { ...FEEDS, qualifier: "x" });
    expect([x.evidence.length, x.total]).toEqual([15, 15]);
    const y = await cited(file, { ...FEEDS, qualifier: "y" });
    expect([y.evidence.length, y.total]).toEqual([20, 21]);
    expect(y.evidence.every((e) => e.locator.startsWith("y="))).toBe(true);
    file.close();
  });

  it("with a qualifier on a self-loop, cites the loop with that qualifier only", async () => {
    const file = await open({
      ...EDGE,
      nodes: [{ type: "Item", key: "a" }],
      edges: [
        { type: "feeds", from: "Item:a", to: "Item:a", qualifier: "p", evidence: [{ snippet: "p" }] },
        { type: "feeds", from: "Item:a", to: "Item:a", qualifier: "q", evidence: [{ snippet: "q" }] },
      ],
    });
    const data = await cited(file, { from: "Item:a", type: "feeds", to: "Item:a", qualifier: "q" });
    expect(data.evidence.map((e) => e.snippet)).toEqual(["q"]);
    file.close();
  });

  it("the other direction has its own qualifiers: a qualifier of a -> b does not match b -> a", async () => {
    const file = await open({
      ...EDGE,
      nodes: PAIR,
      edges: [{ type: "feeds", from: "Item:a", to: "Item:b", qualifier: "fwd" }],
    });
    expect((await failed(file.cite({ from: "Item:b", type: "feeds", to: "Item:a", qualifier: "fwd" }))).code).toBe("unknown_edge");
    file.close();
  });

  it("a qualifier does not change which error comes first: unknown ends are unknown_id with suggestions, an undeclared type is unknown_edge", async () => {
    const file = await open(QUALIFIED);
    const noEnd = await failed(file.cite({ from: "Other:a", type: "feeds", to: "Item:b", qualifier: "backup" }));
    expect(noEnd.code).toBe("unknown_id");
    // find("a") has the exact key match Item:a (section 8.1).
    expect(noEnd.suggestions).toContain("Item:a");
    expect((await failed(file.cite({ from: "Item:a", type: "nope", to: "Item:b", qualifier: "backup" }))).code).toBe("unknown_edge");
    file.close();
  });

  it("rejects a qualifier that is not a string: null, boolean, array, object, number", async () => {
    const file = await open(QUALIFIED);
    for (const qualifier of [true, false, [], ["backup"], {}, { q: "backup" }, 0, 1.5]) {
      expect((await failed(file.cite({ ...FEEDS, qualifier }))).code).toBe("bad_argument");
    }
    file.close();
  });

  it("rejects a qualifier without a complete edge: alone, with only some of from, type and to, or with an id", async () => {
    const file = await open(QUALIFIED);
    for (const args of [
      { qualifier: "backup" },
      { type: "feeds", to: "Item:b", qualifier: "backup" },
      { from: "Item:a", to: "Item:b", qualifier: "backup" },
      { from: "Item:a", type: "feeds", qualifier: "backup" },
      { id: "Item:a", ...FEEDS, qualifier: "backup" },
      { id: "Item:a", qualifier: "" },
    ]) {
      expect((await failed(file.cite(args))).code).toBe("bad_argument");
    }
    file.close();
  });

  it("get takes no qualifier: it is an unknown argument", async () => {
    const file = await open(QUALIFIED);
    expect((await failed(file.get({ id: "Item:a", qualifier: "backup" }))).code).toBe("bad_argument");
    file.close();
  });

  it("a qualifier of 200,000 characters is an error within the schema's 400-character message, or an answer, never a crash", async () => {
    const file = await open(QUALIFIED);
    const answer = valid(await file.cite({ ...FEEDS, qualifier: "q".repeat(200_000) }));
    expect(answer.tool).toBe("cite");
    if ("error" in answer) {
      expect(["unknown_edge", "bad_argument", "limit_exceeded"]).toContain(answer.error.code);
      expect(answer.error.message.length).toBeLessThanOrEqual(400);
    }
    file.close();
  });

  it("a qualifier with a NUL character finds the edge that has it", async () => {
    // Section 3.8 step 4: text is data, a NUL is not a terminator.
    const qualifier = "a\u0000b";
    const file = await open({
      ...EDGE,
      nodes: PAIR,
      edges: [
        { type: "feeds", from: "Item:a", to: "Item:b", qualifier, evidence: [{ snippet: "nul" }] },
        { type: "feeds", from: "Item:a", to: "Item:b", qualifier: "a", evidence: [{ snippet: "a" }] },
      ],
    });
    expect((await cited(file, { ...FEEDS, qualifier })).evidence.map((e) => e.snippet)).toEqual(["nul"]);
    expect((await cited(file, { ...FEEDS, qualifier: "a" })).evidence.map((e) => e.snippet)).toEqual(["a"]);
    file.close();
  });

  it("a qualifier is a value, not a pattern: SQL and LIKE characters match nothing else", async () => {
    // Section 10: arguments are untrusted; no raw SQL.
    const file = await open(QUALIFIED);
    for (const qualifier of ["%", "_ackup", "back%", "' OR '1'='1", "backup'; DROP TABLE edge; --", "*"]) {
      expect((await failed(file.cite({ ...FEEDS, qualifier }))).code).toBe("unknown_edge");
    }
    expect((await cited(file, { ...FEEDS, qualifier: "backup" })).total).toBe(2);
    file.close();
  });

  it("a qualifier named __proto__, constructor or toString is an ordinary qualifier", async () => {
    const file = await open({
      ...EDGE,
      nodes: PAIR,
      edges: [{ type: "feeds", from: "Item:a", to: "Item:b", qualifier: "__proto__", evidence: [{ snippet: "p" }] }],
    });
    expect((await cited(file, { ...FEEDS, qualifier: "__proto__" })).evidence.map((e) => e.snippet)).toEqual(["p"]);
    expect((await failed(file.cite({ ...FEEDS, qualifier: "constructor" }))).code).toBe("unknown_edge");
    expect((await failed(file.cite({ ...FEEDS, qualifier: "toString" }))).code).toBe("unknown_edge");
    file.close();
  });

  it("gives the same answer twice, leaves the argument object unchanged, and accepts a frozen one", async () => {
    const file = await open(QUALIFIED);
    const args = Object.freeze({ ...FEEDS, qualifier: "backup" });
    const one = JSON.stringify(await file.cite(args));
    expect(JSON.stringify(await file.cite(args))).toBe(one);
    expect(args).toEqual({ ...FEEDS, qualifier: "backup" });
    file.close();
  });

  it("a qualified edge's own rows are not mixed with the nodes' evidence or another type's edge between the same nodes", async () => {
    const file = await open({
      edgeTypes: [
        ["feeds", "Item", "Item"],
        ["other", "Item", "Item"],
      ],
      nodes: [
        { type: "Item", key: "a", snippets: ["node a"] },
        { type: "Item", key: "b", snippets: ["node b"] },
      ],
      edges: [
        { type: "feeds", from: "Item:a", to: "Item:b", qualifier: "q", evidence: [{ snippet: "feeds q" }] },
        { type: "other", from: "Item:a", to: "Item:b", qualifier: "q", evidence: [{ snippet: "other q" }] },
      ],
    });
    expect((await cited(file, { ...FEEDS, qualifier: "q" })).evidence.map((e) => e.snippet)).toEqual(["feeds q"]);
    file.close();
  });
});
