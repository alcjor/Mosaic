// Edge cases for M2.13 (`table`) from section 8.6 (7 November 2026), beyond the existing tests:
// list-size limits (1 to 20 conditions and order keys, at most 20 columns), cuts of keys and
// summaries, booleans under ordering operators, `contains` on kinds that are not text, Unicode
// lowercase mapping without folding, precedence of a field over an edge, ties under `desc`.
import { Ajv2020 } from "ajv/dist/2020.js";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CUT_MARKER, openFile, type Answer, type ErrorAnswer, type SealedFile, type TableAnswer } from "../src/index.js";
import { buildMosaic, type MosaicSpec } from "./build-mosaic.js";

const repo = (path: string): string => fileURLToPath(new URL(`../../${path}`, import.meta.url));
const schema = JSON.parse(readFileSync(repo("spec/answers.schema.json"), "utf8")) as object;
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);

function valid<T extends Answer>(answer: T): T {
  if (!validate(answer)) throw new Error(`answer is not valid: ${JSON.stringify(validate.errors)}`);
  return answer;
}
async function open(spec: MosaicSpec): Promise<SealedFile> {
  return openFile(buildMosaic(spec), "test.mosaic");
}
async function tabled(file: SealedFile, args: unknown): Promise<TableAnswer["data"]> {
  const a = valid(await file.table(args));
  if (!("data" in a)) throw new Error(`table failed: ${JSON.stringify(a).slice(0, 500)}`);
  return a.data;
}
async function failed(p: Promise<Answer>): Promise<ErrorAnswer["error"]> {
  const a = valid(await p);
  if (!("error" in a)) throw new Error(`expected an error: ${JSON.stringify(a).slice(0, 500)}`);
  return a.error;
}
const ids = (d: TableAnswer["data"]): unknown[] => d.rows.map((r) => r[0]);

const names = (n: number): string[] => Array.from({ length: n }, (_, i) => `p${String(i).padStart(2, "0")}`);
const WIDE: MosaicSpec = {
  typeProps: { Wide: `{${names(25).map((p) => `"${p}":"integer"`).join(",")}}` },
  nodes: [
    { type: "Wide", key: "a", props: `{${names(25).map((p) => `"${p}":1`).join(",")}}` },
    { type: "Wide", key: "b", props: `{${names(25).map((p) => `"${p}":2`).join(",")}}` },
  ],
};

describe("table limits (section 8.6)", () => {
  it("accepts 20 conditions, refuses 21 and an empty list", async () => {
    const file = await open(WIDE);
    const cond = (n: number) => names(n).map((column) => ({ column, op: ">=", value: 1 }));
    expect(ids(await tabled(file, { type: "Wide", where: cond(20) }))).toEqual(["Wide:a", "Wide:b"]);
    expect((await failed(file.table({ type: "Wide", where: [...cond(20), { column: "p20", op: ">=", value: 1 }] }))).code).toBe("bad_argument");
    expect((await failed(file.table({ type: "Wide", where: [] }))).code).toBe("bad_argument");
  });

  it("accepts 20 order keys, refuses 21 and an empty list", async () => {
    const file = await open(WIDE);
    expect(ids(await tabled(file, { type: "Wide", order: names(20).map((column) => ({ column, direction: "desc" })) }))).toEqual(["Wide:b", "Wide:a"]);
    expect((await failed(file.table({ type: "Wide", order: names(21) }))).code).toBe("bad_argument");
    expect((await failed(file.table({ type: "Wide", order: [] }))).code).toBe("bad_argument");
  });

  it("accepts 20 columns and refuses 21, or one named twice", async () => {
    const file = await open(WIDE);
    const data = await tabled(file, { type: "Wide", columns: names(20) });
    expect(data.columns).toEqual(["id", ...names(20)]);
    expect((await failed(file.table({ type: "Wide", columns: names(21) }))).code).toBe("bad_argument");
    expect((await failed(file.table({ type: "Wide", columns: ["p00", "p00"] }))).code).toBe("bad_argument");
  });

  it("the same column may be used in two conditions and two order keys", async () => {
    const file = await open(WIDE);
    const d = await tabled(file, { type: "Wide", where: [{ column: "p00", op: ">", value: 0 }, { column: "p00", op: "<", value: 2 }], order: ["p00", { column: "p00", direction: "desc" }] });
    expect(ids(d)).toEqual(["Wide:a"]);
  });

  it("order direction other than asc or desc, and a missing column, are refused", async () => {
    const file = await open(WIDE);
    expect((await failed(file.table({ type: "Wide", order: { column: "p00", direction: "ASC" } }))).code).toBe("bad_argument");
    expect((await failed(file.table({ type: "Wide", order: { direction: "asc" } }))).code).not.toBe(undefined);
  });
});

describe("table cells and cuts (section 8.6, 8.2)", () => {
  const long = "k".repeat(401);
  const spec: MosaicSpec = {
    typeProps: { Doc: '{"tags":"json","t":"text"}' },
    nodes: [
      { type: "Doc", key: long, label: "L".repeat(121), summary: "S".repeat(401), props: `{"t":"${"x".repeat(401)}","tags":["${"y".repeat(401)}"]}` },
      { type: "Doc", key: "exact", label: "L".repeat(120), summary: "S".repeat(400), props: `{"t":"${"x".repeat(400)}"}` },
    ],
  };
  it("cuts key and summary at 400, label at 120, and keeps the exact length whole", async () => {
    const file = await open(spec);
    const d = await tabled(file, { type: "Doc", columns: ["key", "label", "summary", "t", "tags"], order: "label" });
    const rows = Object.fromEntries(d.rows.map((r) => [(r[0] as string).length > 100 ? "long" : "exact", r]));
    const long_ = rows["long"]!;
    expect(long_[1]).not.toBe(long);
    expect((long_[1] as string).length).toBeLessThanOrEqual(400 + CUT_MARKER.length);
    expect(long_[1] as string).toContain(CUT_MARKER);
    expect((long_[2] as string).length).toBeLessThanOrEqual(120 + CUT_MARKER.length);
    expect(long_[2] as string).toContain(CUT_MARKER);
    expect(long_[3] as string).toContain(CUT_MARKER);
    expect(long_[4] as string).toContain(CUT_MARKER);
    expect(long_[5]).toEqual([expect.stringContaining(CUT_MARKER)]);
    expect(rows["exact"]![2]).toBe("L".repeat(120));
    expect(rows["exact"]![3]).toBe("S".repeat(400));
    expect(rows["exact"]![4]).toBe("x".repeat(400));
  });

  it("a filter compares the stored value, not the cut one", async () => {
    const file = await open(spec);
    expect(ids(await tabled(file, { type: "Doc", where: { column: "summary", op: "=", value: "S".repeat(401) } }))).toHaveLength(1);
    expect(ids(await tabled(file, { type: "Doc", where: { column: "t", op: "contains", value: "x".repeat(401) } }))).toHaveLength(1);
  });
});

describe("table where: kinds and contains (section 8.6)", () => {
  const spec: MosaicSpec = {
    typeProps: { Item: '{"b":"boolean","n":"integer","o":"json","l":"json","t":"text"}' },
    nodes: [
      { type: "Item", key: "1", label: "Alpha", props: '{"b":false,"n":4,"o":{"k":"abc"},"l":[4,["abc"],"zzz"],"t":"İSTANBUL"}' },
      { type: "Item", key: "2", label: "Beta", props: '{"b":true,"n":-0.0,"o":{"k":"x"},"l":["Abc",null],"t":"Straße ﬁsh"}' },
      { type: "Item", key: "3", label: null, props: '{"t":""}' },
    ],
  };
  const w = async (column: string, op: string, value: unknown): Promise<unknown[]> =>
    ids(await tabled(await open(spec), { type: "Item", where: { column, op, value } }));

  it("orders booleans false before true under < <= > >=, never across kinds", async () => {
    expect(await w("b", "<", true)).toEqual(["Item:1"]);
    expect(await w("b", ">", false)).toEqual(["Item:2"]);
    expect(await w("b", "<=", true)).toEqual(["Item:1", "Item:2"]);
    expect(await w("b", ">=", true)).toEqual(["Item:2"]);
    expect(await w("b", "<", 1)).toEqual([]);
    expect(await w("b", ">", "")).toEqual([]);
  });

  it("zero equals negative zero by value", async () => {
    expect(await w("n", "=", 0)).toEqual(["Item:2"]);
    expect(await w("n", "<", 1)).toEqual(["Item:2"]);
  });

  it("contains holds only on text and on lists with a text item: not numbers, objects, nested lists or non-text items", async () => {
    expect(await w("n", "contains", "4")).toEqual([]);
    expect(await w("o", "contains", "abc")).toEqual([]);
    expect(await w("l", "contains", "abc")).toEqual(["Item:2"]);
    expect(await w("l", "contains", "4")).toEqual([]);
    expect(await w("l", "contains", "null")).toEqual([]);
    expect(await w("b", "contains", "true")).toEqual([]);
  });

  it("contains with an empty text holds on any text, and on a list with a text item, never on no value", async () => {
    expect(await w("t", "contains", "")).toEqual(["Item:1", "Item:2", "Item:3"]);
    expect(await w("l", "contains", "")).toEqual(["Item:1", "Item:2"]);
    expect(await w("n", "contains", "")).toEqual([]);
  });

  it("contains uses Unicode lowercase mapping, and folds nothing else", async () => {
    expect(await w("t", "contains", "i̇stanbul")).toEqual(["Item:1"]);
    expect(await w("t", "contains", "İstanbul")).toEqual(["Item:1"]);
    expect(await w("t", "contains", "STRAßE")).toEqual(["Item:2"]);
    expect(await w("t", "contains", "strasse")).toEqual([]);
    expect(await w("t", "contains", "fish")).toEqual([]);
  });

  it("id is not a column unless a property is named so, and a label with no text is a no value", async () => {
    const file = await open(spec);
    expect((await failed(file.table({ type: "Item", columns: ["id"] }))).code).toBe("unknown_column");
    expect(ids(await tabled(file, { type: "Item", where: { column: "label", op: "!=", value: "Alpha" } }))).toEqual(["Item:2", "Item:3"]);
    expect(ids(await tabled(file, { type: "Item", where: { column: "label", op: "<", value: "~" } }))).toEqual(["Item:1", "Item:2"]);
  });
});

describe("table order and names (section 8.6)", () => {
  it("desc keeps ties in id order, ascending", async () => {
    const file = await open({
      typeProps: { Item: '{"n":"integer"}' },
      nodes: ["c", "a", "b", "d"].map((key, i) => ({ type: "Item", key, props: `{"n":${i < 3 ? 1 : 2}}` })),
    });
    expect(ids(await tabled(file, { type: "Item", order: { column: "n", direction: "desc" } }))).toEqual(["Item:d", "Item:a", "Item:b", "Item:c"]);
  });

  it("a node field is a column before an edge type of the same name, and a property before a field", async () => {
    const file = await open({
      typeProps: { Item: '{"key":"text"}', Other: "{}" },
      edgeTypes: [["summary", "Item", "Other"], ["label", "Item", "Other"]],
      nodes: [
        { type: "Item", key: "i", label: "Mine", summary: "Sum", props: '{"key":"prop"}' },
        { type: "Other", key: "o", label: "Far" },
      ],
      edges: [{ type: "summary", from: "Item:i", to: "Other:o" }, { type: "label", from: "Item:i", to: "Other:o" }],
    });
    const d = await tabled(file, { type: "Item", columns: ["key", "label", "summary"] });
    expect(d.rows).toEqual([["Item:i", "prop", "Mine", "Sum"]]);
  });
});
