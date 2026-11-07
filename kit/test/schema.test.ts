// M3.6: the open file gives each node type's declared properties and the edge types it declares
// with the node types they join (section 3.4), so a viewer can tell whether a view file names
// something the mosaic has. Bounded like `nodeTypes` (section 3.8 step 4).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { NODE_TYPE_LIMIT, openFile } from "../src/index.js";
import { buildMosaic } from "./build-mosaic.js";

const repo = (path: string): string => fileURLToPath(new URL(`../../${path}`, import.meta.url));

describe("propsOf", () => {
  it("gives a node type's declared properties in the order its props object holds them", async () => {
    const file = await openFile(
      buildMosaic({
        types: ["Step"],
        typeProps: { Step: '{"zeta":"text","alpha":"integer","mid":"json"}' },
        nodes: [{ type: "Probe", key: "p" }],
      }),
      "t.mosaic",
    );
    expect(file.propsOf("Step")).toEqual(["zeta", "alpha", "mid"]);
    expect(file.propsOf("Probe")).toEqual(["name"]);
    file.close();
  });

  it("is empty for a type the file does not declare, an edge type, or a type with no properties", async () => {
    const file = await openFile(
      buildMosaic({
        types: ["Bare"],
        typeProps: { Bare: "{}" },
        edgeTypes: [["reads", "Bare", "Bare"]],
        nodes: [],
      }),
      "t.mosaic",
    );
    expect(file.propsOf("Bare")).toEqual([]);
    expect(file.propsOf("reads")).toEqual([]);
    expect(file.propsOf("Absent")).toEqual([]);
    expect(file.propsOf("__proto__")).toEqual([]);
    expect(file.propsOf("constructor")).toEqual([]);
    file.close();
  });

  it("gives the conformance mosaic's declared properties", async () => {
    const file = await openFile(new Uint8Array(readFileSync(repo("conformance/reading/mosaic.mosaic"))), "mosaic.mosaic");
    expect(file.propsOf("Item")).toEqual(["code", "size"]);
    expect(file.propsOf("Group")).toEqual(["name"]);
    file.close();
  });
});

describe("edgeTypes", () => {
  it("lists every declared edge type by name (UTF-8 bytes) with the node types it joins, no node type", async () => {
    const file = await openFile(
      buildMosaic({
        types: ["Probe", "Step"],
        edgeTypes: [
          ["reads", "Step", "Probe"],
          ["after", "Step", "Step"],
          ["zz_last", "Probe", "Step"],
        ],
        nodes: [],
      }),
      "t.mosaic",
    );
    expect(file.edgeTypes).toEqual([
      { name: "after", from: "Step", to: "Step" },
      { name: "reads", from: "Step", to: "Probe" },
      { name: "zz_last", from: "Probe", to: "Step" },
    ]);
    file.close();
  });

  it("gives the conformance mosaic's edge types", async () => {
    const file = await openFile(new Uint8Array(readFileSync(repo("conformance/reading/mosaic.mosaic"))), "mosaic.mosaic");
    expect(file.edgeTypes).toEqual([{ name: "in_group", from: "Item", to: "Group" }]);
    file.close();
  });

  it("lists at most NODE_TYPE_LIMIT edge types", async () => {
    const edgeTypes: [string, string, string][] = [];
    for (let i = 0; i < NODE_TYPE_LIMIT + 5; i++) edgeTypes.push([`e${String(i).padStart(5, "0")}`, "Step", "Step"]);
    const file = await openFile(buildMosaic({ types: ["Step"], edgeTypes, nodes: [] }), "t.mosaic");
    expect(file.edgeTypes).toHaveLength(NODE_TYPE_LIMIT);
    expect(file.edgeTypes[0]!.name).toBe("e00000");
    file.close();
  });
});

describe("pieces", () => {
  it("lists the pieces the file was built from, in sid order, with their hashes", async () => {
    const file = await openFile(new Uint8Array(readFileSync(repo("conformance/reading/mosaic.mosaic"))), "mosaic.mosaic");
    expect(file.pieces).toEqual([
      { id: "first", kind: "tessera", hash: "9a56bbb09c609a344b3008385d52ffec894ce391a6d3d7434fa78bb527515a4f" },
      { id: "inner", kind: "mosaic", hash: "cc18c7ce68009a0dc543fd8ad6915a1d02c57dfaa49c0c5c762455719ffe6f96" },
    ]);
    file.close();
  });

  it("lists none for a tessera", async () => {
    const file = await openFile(new Uint8Array(readFileSync(repo("conformance/reading/tessera.tessera"))), "t.tessera");
    expect(file.pieces).toEqual([]);
    file.close();
  });
});
