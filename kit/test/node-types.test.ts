// M2.10: the open file lists the node types it declares with their node counts, which a viewer
// shows as tables (docs/design.md, First milestone: Viewer; sections 3.4 and 8.3), bounded
// (section 3.8 step 4).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { NODE_TYPE_LIMIT, openFile } from "../src/index.js";
import { buildMosaic } from "./build-mosaic.js";

const repo = (path: string): string => fileURLToPath(new URL(`../../${path}`, import.meta.url));

describe("nodeTypes", () => {
  it("lists every declared node type by name (UTF-8 bytes) with its node count, no edge type", async () => {
    const file = await openFile(
      buildMosaic({
        types: ["Valve", "Aa"],
        edgeTypes: [["reads", "Step", "Probe"]],
        nodes: [
          { type: "Probe", key: "p1" },
          { type: "Probe", key: "p2" },
          { type: "Step", key: "s1" },
          { type: "Zeta", key: "z" },
          { type: "B", key: "b" },
        ],
      }),
      "t.mosaic",
    );
    expect(file.nodeTypes).toEqual([
      { name: "Aa", count: 0 },
      { name: "B", count: 1 },
      { name: "Probe", count: 2 },
      { name: "Step", count: 1 },
      { name: "Valve", count: 0 },
      { name: "Zeta", count: 1 },
    ]);
    file.close();
  });

  it("gives the conformance mosaic's types and counts", async () => {
    const file = await openFile(new Uint8Array(readFileSync(repo("conformance/reading/mosaic.mosaic"))), "mosaic.mosaic");
    expect(file.nodeTypes).toEqual([
      { name: "Group", count: 1 },
      { name: "Item", count: 2 },
    ]);
    file.close();
  });

  it("is bounded: at most 1,000 types, the first by name", async () => {
    const names = Array.from({ length: NODE_TYPE_LIMIT + 5 }, (_, i) => `T${String(i).padStart(4, "0")}`);
    const file = await openFile(buildMosaic({ types: names, nodes: [{ type: "T0000", key: "a" }] }), "t.mosaic");
    expect(NODE_TYPE_LIMIT).toBe(1000);
    expect(file.nodeTypes).toHaveLength(NODE_TYPE_LIMIT);
    expect(file.nodeTypes[0]).toEqual({ name: "T0000", count: 1 });
    expect(file.nodeTypes.at(-1)?.name).toBe("T0999");
    file.close();
  });
});
