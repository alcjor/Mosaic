// M2.5: `neighbors` (sections 8.1 and 8.2, `spec/answers.schema.json`), on files that passed the
// reading rules (section 3.8): edges with the other node's id and label and the total count,
// optional `edge`, `direction` and `limit`, unknown ids as errors naming the closest matches from
// `find`, text from the file only inside `data` and length-limited, and the result size and time
// bounded (section 3.8 step 4, section 10).
import { Ajv2020 } from "ajv/dist/2020.js";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  CUT_MARKER,
  RESULT_LIMIT,
  TEXT_LIMITS,
  openFile,
  type Answer,
  type ErrorAnswer,
  type NeighborsAnswer,
  type SealedFile,
} from "../src/index.js";
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

async function open(spec: MosaicSpec, options?: { timeLimitMs?: number }): Promise<SealedFile> {
  return openFile(buildMosaic(spec), "test.mosaic", options);
}

async function linked(file: SealedFile, args: unknown): Promise<NeighborsAnswer["data"]> {
  const answer = valid(await file.neighbors(args));
  if (!("data" in answer)) throw new Error(`neighbors failed: ${JSON.stringify(answer)}`);
  expect(answer.tool).toBe("neighbors");
  expect(answer.mosaic).toBe(file.header.knowledge_hash);
  expect(Object.keys(answer).sort()).toEqual(["data", "mosaic", "tool"]);
  return answer.data;
}

async function failed(answer: Promise<Answer>): Promise<ErrorAnswer["error"]> {
  const a = valid(await answer);
  if (!("error" in a)) throw new Error(`expected an error: ${JSON.stringify(a)}`);
  expect(a.tool).toBe("neighbors");
  expect(Object.keys(a).sort()).toEqual(["error", "mosaic", "tool"]);
  return a.error;
}

// A step reads two probes and is part of a manual; one probe feeds another and itself.
const SAMPLE: MosaicSpec = {
  edgeTypes: [
    ["feeds", "Probe", "Probe"],
    ["reads", "Step", "Probe"],
    ["part_of", "Step", "Manual"],
  ],
  nodes: [
    { type: "Probe", key: "TMP-3", label: "Inlet temperature" },
    { type: "Probe", key: "TMP-4", label: "Outlet temperature" },
    { type: "Probe", key: "PRS-1" },
    { type: "Step", key: "S1", label: "Switch heater A on" },
    { type: "Step", key: "S2", label: "Check the outlet" },
    { type: "Manual", key: "M", label: "Power manual" },
  ],
  edges: [
    { type: "reads", from: "Step:S1", to: "Probe:TMP-3" },
    { type: "reads", from: "Step:S2", to: "Probe:TMP-3" },
    { type: "reads", from: "Step:S2", to: "Probe:TMP-4" },
    { type: "part_of", from: "Step:S1", to: "Manual:M" },
    { type: "part_of", from: "Step:S2", to: "Manual:M" },
    { type: "feeds", from: "Probe:TMP-3", to: "Probe:TMP-4" },
    { type: "feeds", from: "Probe:PRS-1", to: "Probe:TMP-3" },
    { type: "feeds", from: "Probe:TMP-3", to: "Probe:TMP-3" },
  ],
};

describe("neighbors (section 8.1)", () => {
  it("returns the node's edges with the other node's id and label, and the total count", async () => {
    const file = await open(SAMPLE);
    const data = await linked(file, { id: "Step:S2" });
    expect(data.id).toBe("Step:S2");
    expect(data.edges).toEqual([
      { edge: "part_of", direction: "out", id: "Manual:M", label: "Power manual" },
      { edge: "reads", direction: "out", id: "Probe:TMP-3", label: "Inlet temperature" },
      { edge: "reads", direction: "out", id: "Probe:TMP-4", label: "Outlet temperature" },
    ]);
    expect(data.total).toBe(3);
    file.close();
  });

  it("gives null for another node with no label", async () => {
    const file = await open(SAMPLE);
    const data = await linked(file, { id: "Probe:TMP-3", edge: "feeds", direction: "in" });
    expect(data.edges).toContainEqual({ edge: "feeds", direction: "in", id: "Probe:PRS-1", label: null });
    file.close();
  });

  it("without direction lists both, by edge type (UTF-8 bytes), out before in, then the other node's id", async () => {
    const file = await open(SAMPLE);
    const data = await linked(file, { id: "Probe:TMP-3" });
    expect(data.edges.map((e) => [e.edge, e.direction, e.id])).toEqual([
      ["feeds", "out", "Probe:TMP-3"],
      ["feeds", "out", "Probe:TMP-4"],
      ["feeds", "in", "Probe:PRS-1"],
      ["feeds", "in", "Probe:TMP-3"],
      ["reads", "in", "Step:S1"],
      ["reads", "in", "Step:S2"],
    ]);
    expect(data.total).toBe(6);
    expect(await linked(file, { id: "Probe:TMP-3", direction: "both" })).toEqual(data);
    file.close();
  });

  it("direction out and in keep the edges that leave or reach the node", async () => {
    const file = await open(SAMPLE);
    const out = await linked(file, { id: "Probe:TMP-3", direction: "out" });
    expect(out.edges.map((e) => [e.edge, e.direction, e.id])).toEqual([
      ["feeds", "out", "Probe:TMP-3"],
      ["feeds", "out", "Probe:TMP-4"],
    ]);
    expect(out.total).toBe(2);
    const into = await linked(file, { id: "Probe:TMP-3", direction: "in" });
    expect(into.edges.map((e) => [e.edge, e.direction, e.id])).toEqual([
      ["feeds", "in", "Probe:PRS-1"],
      ["feeds", "in", "Probe:TMP-3"],
      ["reads", "in", "Step:S1"],
      ["reads", "in", "Step:S2"],
    ]);
    expect(into.total).toBe(4);
    file.close();
  });

  it("edge keeps the edges of that type", async () => {
    const file = await open(SAMPLE);
    const data = await linked(file, { id: "Probe:TMP-3", edge: "reads", direction: "in" });
    expect(data.edges.map((e) => e.id)).toEqual(["Step:S1", "Step:S2"]);
    expect(data.total).toBe(2);
    const none = await linked(file, { id: "Manual:M", edge: "reads" });
    expect(none).toEqual({ id: "Manual:M", edges: [], total: 0 });
    file.close();
  });

  it("a node with no edges is an empty success", async () => {
    const file = await open({ nodes: [{ type: "Item", key: "a" }] });
    expect(await linked(file, { id: "Item:a" })).toEqual({ id: "Item:a", edges: [], total: 0 });
    file.close();
  });

  it("the total equals the link counts get gives", async () => {
    const file = await open(SAMPLE);
    for (const id of ["Probe:TMP-3", "Probe:TMP-4", "Step:S1", "Step:S2", "Manual:M", "Probe:PRS-1"]) {
      const g = await file.get({ id });
      if (!("data" in g)) throw new Error("get failed");
      const sum = g.data.links.reduce((n, l) => n + l.count, 0);
      expect((await linked(file, { id })).total).toBe(sum);
    }
    file.close();
  });

  it("shows a qualifier only on an edge that has one, and orders by it", async () => {
    const file = await open({
      edgeTypes: [["route", "Port", "Port"]],
      nodes: [
        { type: "Port", key: "A" },
        { type: "Port", key: "B" },
      ],
      edges: [
        { type: "route", from: "Port:A", to: "Port:B", qualifier: "z" },
        { type: "route", from: "Port:A", to: "Port:B", qualifier: "b" },
        { type: "route", from: "Port:A", to: "Port:B" },
      ],
    });
    const data = await linked(file, { id: "Port:A" });
    expect(data.edges).toEqual([
      { edge: "route", direction: "out", id: "Port:B", label: null },
      { edge: "route", direction: "out", id: "Port:B", label: null, qualifier: "b" },
      { edge: "route", direction: "out", id: "Port:B", label: null, qualifier: "z" },
    ]);
    expect(data.total).toBe(3);
    file.close();
  });
});

describe("neighbors: an unknown id is an error naming the closest matches from find (section 8.1)", () => {
  it("names the node whose key the id holds", async () => {
    const file = await open(SAMPLE);
    const error = await failed(file.neighbors({ id: "Probe:TMP-9" }));
    expect(error.code).toBe("unknown_id");
    expect(error.message).toContain('"Probe:TMP-9"');
    const near = await failed(file.neighbors({ id: "Sensor:TMP-3" }));
    expect(near.code).toBe("unknown_id");
    expect(near.suggestions).toContain("Probe:TMP-3");
    file.close();
  });

  it("an edge type the mosaic does not declare is unknown_edge, never an empty success", async () => {
    const file = await open(SAMPLE);
    for (const edge of ["writes", "Probe", "READS"]) {
      const error = await failed(file.neighbors({ id: "Probe:TMP-3", edge }));
      expect(error.code).toBe("unknown_edge");
    }
    file.close();
  });
});

describe("neighbors: bad arguments", () => {
  it("are bad_argument errors naming what is wrong", async () => {
    const file = await open(SAMPLE);
    const cases: unknown[] = [
      null,
      "Probe:TMP-3",
      [],
      {},
      { id: 3 },
      { id: "Probe:TMP-3", edges: "reads" },
      { id: "Probe:TMP-3", edge: 1 },
      { id: "Probe:TMP-3", direction: "up" },
      { id: "Probe:TMP-3", direction: "OUT" },
      { id: "Probe:TMP-3", limit: 0 },
      { id: "Probe:TMP-3", limit: 2.5 },
      { id: "Probe:TMP-3", limit: "5" },
    ];
    for (const args of cases) {
      const error = await failed(file.neighbors(args));
      expect(error.code, JSON.stringify(args)).toBe("bad_argument");
    }
    file.close();
  });
});

describe("neighbors: text from the file only inside data, length-limited (section 8.2)", () => {
  it("cuts the other node's label at 120 characters with the marker", async () => {
    const long = "L".repeat(300);
    const file = await open({
      edgeTypes: [["rel", "Item", "Item"]],
      nodes: [
        { type: "Item", key: "a" },
        { type: "Item", key: "b", label: long },
      ],
      edges: [{ type: "rel", from: "Item:a", to: "Item:b" }],
    });
    const data = await linked(file, { id: "Item:a" });
    expect(data.edges[0]!.label).toBe("L".repeat(TEXT_LIMITS.label) + CUT_MARKER);
    file.close();
  });
});

describe("neighbors: an other node's id too long for an answer (answers.schema.json, id maxLength 512)", () => {
  it("leaves that edge out of the list and still counts it in the total", async () => {
    const long = "k".repeat(600);
    const file = await open({
      edgeTypes: [["rel", "Item", "Item"]],
      nodes: [
        { type: "Item", key: "a" },
        { type: "Item", key: "b" },
        { type: "Item", key: long },
      ],
      edges: [
        { type: "rel", from: "Item:a", to: "Item:b" },
        { type: "rel", from: "Item:a", to: `Item:${long}` },
      ],
    });
    const data = await linked(file, { id: "Item:a" });
    expect(data.edges.map((e) => e.id)).toEqual(["Item:b"]);
    expect(data.total).toBe(2);
    const only = await linked(file, { id: "Item:a", limit: 1 });
    expect(only.edges.map((e) => e.id)).toEqual(["Item:b"]);
    file.close();
    const alone = await open({
      edgeTypes: [["rel", "Item", "Item"]],
      nodes: [
        { type: "Item", key: "a" },
        { type: "Item", key: long },
      ],
      edges: [{ type: "rel", from: "Item:a", to: `Item:${long}` }],
    });
    expect(await linked(alone, { id: "Item:a" })).toEqual({ id: "Item:a", edges: [], total: 1 });
    alone.close();
  });
});

describe("neighbors: bounded time and result size (section 3.8 step 4, section 10)", () => {
  const hub = (n: number): MosaicSpec => ({
    edgeTypes: [["rel", "Item", "Item"]],
    nodes: Array.from({ length: n }, (_, i) => ({ type: "Item", key: `i${String(i).padStart(5, "0")}`, label: `Item ${i}` })),
    edges: Array.from({ length: n - 1 }, (_, i) => ({
      type: "rel",
      from: `Item:i${String(i + 1).padStart(5, "0")}`,
      to: "Item:i00000",
    })),
  });

  it("limit defaults to 20 and cuts the list, with the total of every matching edge", async () => {
    const file = await open(hub(46));
    const data = await linked(file, { id: "Item:i00000" });
    expect(data.edges).toHaveLength(RESULT_LIMIT);
    expect(data.edges.map((e) => e.id)).toEqual(
      Array.from({ length: RESULT_LIMIT }, (_, i) => `Item:i${String(i + 1).padStart(5, "0")}`),
    );
    expect(data.total).toBe(45);
    const five = await linked(file, { id: "Item:i00000", limit: 5 });
    expect(five.edges).toEqual(data.edges.slice(0, 5));
    expect(five.total).toBe(45);
    file.close();
  });

  it("a limit above 20 still gives at most 20 edges with the total", async () => {
    const file = await open(hub(46));
    const data = await linked(file, { id: "Item:i00000", limit: 1000 });
    expect(data.edges).toHaveLength(RESULT_LIMIT);
    expect(data.total).toBe(45);
    file.close();
  });

  it("on a 10,000-node mosaic, stops a call that runs past the time bound with an error naming it", async () => {
    const n = 10_000;
    const bytes = buildMosaic(hub(n));
    const normal = await openFile(bytes, "large.mosaic");
    const data = await linked(normal, { id: "Item:i00000" });
    expect(data.edges).toHaveLength(RESULT_LIMIT);
    expect(data.total).toBe(n - 1);
    normal.close();

    const bound = 0.01;
    const file = await openFile(bytes, "large.mosaic", { timeLimitMs: bound });
    const started = performance.now();
    const error = await failed(file.neighbors({ id: "Item:i00000" }));
    expect(performance.now() - started).toBeLessThan(1_000);
    expect(error.code).toBe("limit_exceeded");
    expect(error.message).toContain(`${bound} ms`);
    file.close();
  }, 120_000);
});
