// M2.13, decisions of 7 November 2026 on #113 (section 8.6): `table` shows a node type the way a
// source table would. Columns are declared properties, the node fields `key`, `label` and
// `summary`, or edge types leaving the type; `where` and `order` take any column; `!=` keeps nodes
// with no value; `contains` ignores case and looks inside lists; `order` keeps kinds in fixed
// groups with no value last in both directions.
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
  if (!validate(answer)) {
    throw new Error(`answer is not valid: ${JSON.stringify(validate.errors)}\n${JSON.stringify(answer)}`);
  }
  return answer;
}

async function open(spec: MosaicSpec): Promise<SealedFile> {
  return openFile(buildMosaic(spec), "test.mosaic");
}

async function tabled(file: SealedFile, args: unknown): Promise<TableAnswer["data"]> {
  const answer = valid(await file.table(args));
  if (!("data" in answer)) throw new Error(`table failed: ${JSON.stringify(answer)}`);
  return answer.data;
}

async function failed(answer: Promise<Answer>): Promise<ErrorAnswer["error"]> {
  const a = valid(await answer);
  if (!("error" in a)) throw new Error(`expected an error: ${JSON.stringify(a)}`);
  return a.error;
}

const ids = (data: TableAnswer["data"]): unknown[] => data.rows.map((r) => r[0]);

// Four records read like four rows of a source table: properties of each kind, a label and a
// summary, and two edge types leaving Record (made_by, tagged) and one arriving (cites).
const SAMPLE: MosaicSpec = {
  typeProps: {
    Record: '{"flag":"json","kind":"text","size":"integer","tags":"json"}',
    Agent: "{}",
    Tag: "{}",
  },
  edgeTypes: [
    ["made_by", "Record", "Agent"],
    ["tagged", "Record", "Tag"],
    ["cites", "Tag", "Record"],
  ],
  nodes: [
    { type: "Record", key: "r1", label: "Inlet", summary: "First record", props: '{"flag":true,"kind":"PG","size":4,"tags":["Action","Drama"]}' },
    { type: "Record", key: "r2", label: "Outlet", props: '{"flag":2,"kind":5,"size":2}' },
    { type: "Record", key: "r3", label: null, props: '{"flag":"a","size":"10"}' },
    { type: "Record", key: "r4", label: "Tank", props: '{"flag":["x"],"kind":null}' },
    { type: "Agent", key: "a1", label: "Zed" },
    { type: "Agent", key: "a2", label: "Amy" },
    { type: "Agent", key: "a3", label: null },
    { type: "Tag", key: "t1", label: "TV Dramas" },
    { type: "Tag", key: "t2", label: "Comedy" },
    { type: "Tag", key: "t3", label: "ÉCOLE" },
  ],
  edges: [
    { type: "made_by", from: "Record:r1", to: "Agent:a2" },
    { type: "made_by", from: "Record:r1", to: "Agent:a1" },
    { type: "made_by", from: "Record:r1", to: "Agent:a3" },
    { type: "made_by", from: "Record:r2", to: "Agent:a2", qualifier: "x" },
    { type: "made_by", from: "Record:r2", to: "Agent:a2", qualifier: "y" },
    { type: "tagged", from: "Record:r1", to: "Tag:t1" },
    { type: "tagged", from: "Record:r2", to: "Tag:t2" },
    { type: "tagged", from: "Record:r4", to: "Tag:t3" },
    { type: "cites", from: "Tag:t1", to: "Record:r1" },
  ],
};

describe("table columns (section 8.6)", () => {
  it("defaults to label, then the declared properties in declared order", async () => {
    const data = await tabled(await open(SAMPLE), { type: "Record" });
    expect(data.columns).toEqual(["id", "label", "flag", "kind", "size", "tags"]);
    expect(data.rows[0]).toEqual(["Record:r1", "Inlet", true, "PG", 4, ["Action", "Drama"]]);
    expect(data.rows[2]).toEqual(["Record:r3", null, "a", null, "10", null]);
    expect(data.rows[3]).toEqual(["Record:r4", "Tank", ["x"], null, null, null]);
  });

  it("shows key, label and summary as the node's fields, null when empty", async () => {
    const data = await tabled(await open(SAMPLE), { type: "Record", columns: ["key", "label", "summary"] });
    expect(data.columns).toEqual(["id", "key", "label", "summary"]);
    expect(data.rows).toEqual([
      ["Record:r1", "r1", "Inlet", "First record"],
      ["Record:r2", "r2", "Outlet", null],
      ["Record:r3", "r3", null, null],
      ["Record:r4", "r4", "Tank", null],
    ]);
  });

  it("shows an edge leaving the type as the labels of the nodes it leads to, one per node, by their ids", async () => {
    const data = await tabled(await open(SAMPLE), { type: "Record", columns: ["made_by", "tagged"] });
    expect(data.columns).toEqual(["id", "made_by", "tagged"]);
    expect(data.rows).toEqual([
      ["Record:r1", ["Zed", "Amy", null], ["TV Dramas"]],
      ["Record:r2", ["Amy"], ["Comedy"]],
      ["Record:r3", [], []],
      ["Record:r4", [], ["ÉCOLE"]],
    ]);
  });

  it("does not cut an edge cell at 20 items, but cuts each label at 120 characters", async () => {
    const long = "L".repeat(130);
    const spec: MosaicSpec = {
      typeProps: { Record: "{}", Agent: "{}" },
      edgeTypes: [["made_by", "Record", "Agent"]],
      nodes: [
        { type: "Record", key: "r1", label: "One" },
        ...Array.from({ length: 25 }, (_, i) => ({ type: "Agent", key: `a${String(i).padStart(2, "0")}`, label: i === 0 ? long : `A${i}` })),
      ],
      edges: Array.from({ length: 25 }, (_, i) => ({ type: "made_by", from: "Record:r1", to: `Agent:a${String(i).padStart(2, "0")}` })),
    };
    const data = await tabled(await open(spec), { type: "Record", columns: ["made_by"] });
    const cell = data.rows[0]![1] as string[];
    expect(cell).toHaveLength(25);
    expect(cell[0]).toBe("L".repeat(120) + CUT_MARKER);
    expect(cell[24]).toBe("A24");
  });

  it("takes a declared property before a node field or an edge of the same name", async () => {
    const spec: MosaicSpec = {
      typeProps: { Box: '{"label":"text","linked":"text"}', Agent: "{}" },
      edgeTypes: [["linked", "Box", "Agent"]],
      nodes: [
        { type: "Box", key: "b1", label: "Node label", props: '{"label":"Stored label","linked":"no"}' },
        { type: "Agent", key: "a1", label: "Amy" },
      ],
      edges: [{ type: "linked", from: "Box:b1", to: "Agent:a1" }],
    };
    const file = await open(spec);
    const data = await tabled(file, { type: "Box", columns: ["label", "linked", "key"] });
    expect(data.rows).toEqual([["Box:b1", "Stored label", "no", "b1"]]);
    expect(ids(await tabled(file, { type: "Box", where: { column: "label", op: "=", value: "Stored label" } }))).toEqual(["Box:b1"]);
  });

  it("caps the default columns at 20 with label first", async () => {
    const props = `{${Array.from({ length: 25 }, (_, i) => `"p${String(i).padStart(2, "0")}":"text"`).join(",")}}`;
    const data = await tabled(await open({ typeProps: { Wide: props }, nodes: [{ type: "Wide", key: "w1", label: "W" }] }), { type: "Wide" });
    expect(data.columns).toHaveLength(21);
    expect(data.columns.slice(0, 3)).toEqual(["id", "label", "p00"]);
    expect(data.columns[20]).toBe("p18");
  });

  it("refuses a name that is no column of the type, an edge arriving at it included", async () => {
    const file = await open(SAMPLE);
    for (const args of [
      { type: "Record", columns: ["cites"] },
      { type: "Record", columns: ["nope"] },
      { type: "Record", where: { column: "cites", op: "contains", value: "x" } },
      { type: "Record", order: "nope" },
      { type: "Agent", columns: ["made_by"] },
    ]) {
      expect((await failed(file.table(args))).code).toBe("unknown_column");
    }
  });
});

describe("table where (section 8.6)", () => {
  it("keeps nodes with no value under !=, and values of another kind", async () => {
    const file = await open(SAMPLE);
    const kept = ids(await tabled(file, { type: "Record", where: { column: "kind", op: "!=", value: "PG" } }));
    expect(kept).toEqual(["Record:r2", "Record:r3", "Record:r4"]);
    expect(ids(await tabled(file, { type: "Record", where: { column: "label", op: "!=", value: "Inlet" } }))).toEqual([
      "Record:r2",
      "Record:r3",
      "Record:r4",
    ]);
  });

  it("never matches a missing value or another kind with =, < or >", async () => {
    const file = await open(SAMPLE);
    expect(ids(await tabled(file, { type: "Record", where: { column: "size", op: ">", value: 3 } }))).toEqual(["Record:r1"]);
    expect(ids(await tabled(file, { type: "Record", where: { column: "size", op: "=", value: 10 } }))).toEqual([]);
    expect(ids(await tabled(file, { type: "Record", where: { column: "flag", op: "=", value: true } }))).toEqual(["Record:r1"]);
    expect(ids(await tabled(file, { type: "Record", where: { column: "made_by", op: "=", value: "Amy" } }))).toEqual([]);
  });

  it("all conditions must hold", async () => {
    const data = await tabled(await open(SAMPLE), {
      type: "Record",
      where: [
        { column: "size", op: ">", value: 1 },
        { column: "label", op: "contains", value: "let" },
      ],
    });
    expect(ids(data)).toEqual(["Record:r1", "Record:r2"]);
  });

  it("filters on node fields", async () => {
    const file = await open(SAMPLE);
    expect(ids(await tabled(file, { type: "Record", where: { column: "summary", op: "=", value: "First record" } }))).toEqual(["Record:r1"]);
    expect(ids(await tabled(file, { type: "Record", where: { column: "key", op: "<", value: "r3" } }))).toEqual(["Record:r1", "Record:r2"]);
  });

  it("contains ignores case, Unicode included, in text and in list items, edge cells included", async () => {
    const file = await open(SAMPLE);
    const kept = async (column: string, value: string) =>
      ids(await tabled(file, { type: "Record", where: { column, op: "contains", value } }));
    expect(await kept("kind", "pg")).toEqual(["Record:r1"]);
    expect(await kept("tags", "dRaMa")).toEqual(["Record:r1"]);
    expect(await kept("tagged", "drama")).toEqual(["Record:r1"]);
    expect(await kept("tagged", "école")).toEqual(["Record:r4"]);
    expect(await kept("made_by", "AMY")).toEqual(["Record:r1", "Record:r2"]);
    expect(await kept("size", "1")).toEqual(["Record:r3"]);
    expect(await kept("flag", "x")).toEqual(["Record:r4"]);
  });

  it("treats a value holding SQL as a value, on fields and edges too", async () => {
    const file = await open(SAMPLE);
    for (const column of ["label", "key", "made_by"]) {
      const data = await tabled(file, { type: "Record", where: { column, op: "contains", value: "' OR 1=1 --" } });
      expect(data.total).toBe(0);
    }
  });
});

describe("table order (section 8.6)", () => {
  it("keeps the kinds in fixed groups, no value last, in both directions", async () => {
    const file = await open(SAMPLE);
    const sorted = async (column: string, direction: "asc" | "desc") =>
      ids(await tabled(file, { type: "Record", order: { column, direction } }));
    // size: 4 and 2 are numbers, "10" is text, r4 has none.
    expect(await sorted("size", "asc")).toEqual(["Record:r2", "Record:r1", "Record:r3", "Record:r4"]);
    expect(await sorted("size", "desc")).toEqual(["Record:r1", "Record:r2", "Record:r3", "Record:r4"]);
    // flag: a boolean, a number, text, a list.
    expect(await sorted("flag", "asc")).toEqual(["Record:r1", "Record:r2", "Record:r3", "Record:r4"]);
    expect(await sorted("flag", "desc")).toEqual(["Record:r1", "Record:r2", "Record:r3", "Record:r4"]);
    // kind: r3 has none and r4 holds a JSON null; both come last, by id.
    expect(await sorted("kind", "asc")).toEqual(["Record:r2", "Record:r1", "Record:r3", "Record:r4"]);
    expect(await sorted("kind", "desc")).toEqual(["Record:r2", "Record:r1", "Record:r3", "Record:r4"]);
  });

  it("sorts node fields and edge cells, no label last", async () => {
    const file = await open(SAMPLE);
    const sorted = async (column: string, direction: "asc" | "desc") =>
      ids(await tabled(file, { type: "Record", order: { column, direction } }));
    expect(await sorted("label", "asc")).toEqual(["Record:r1", "Record:r2", "Record:r4", "Record:r3"]);
    expect(await sorted("label", "desc")).toEqual(["Record:r4", "Record:r2", "Record:r1", "Record:r3"]);
    // Lists by their JSON text, by UTF-8 bytes: ["Amy"] before ["Zed",…] before [] (" is 0x22, ] 0x5D).
    expect(await sorted("made_by", "asc")).toEqual(["Record:r2", "Record:r1", "Record:r3", "Record:r4"]);
    expect(await sorted("made_by", "desc")).toEqual(["Record:r3", "Record:r4", "Record:r1", "Record:r2"]);
  });
});
