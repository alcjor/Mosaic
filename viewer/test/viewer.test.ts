// M2.9: the search box calls `find`; a node page calls `get`, `neighbors` and `cite`; only the
// latest answer is kept.
import { describe, expect, it, vi } from "vitest";
import type { SearchView } from "../src/lib/mosaic.js";
import { Viewer } from "../src/lib/viewer.svelte.js";
import { reading } from "./fixtures.js";

describe("Viewer", () => {
  it("opens a mosaic; a refused file is an error and keeps no file", async () => {
    const viewer = new Viewer();
    expect(viewer.status).toBe("empty");
    await viewer.open(reading("application-id.mosaic"), "application-id.mosaic");
    expect(viewer.status).toBe("error");
    expect(viewer.error).toMatch(/application-id\.mosaic/);
    expect(viewer.file).toBeNull();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    expect(viewer.status).toBe("ready");
    expect(viewer.error).toBeNull();
    expect(viewer.file?.name).toBe("mosaic.mosaic");
  });

  it("the search box's query goes to find, and its answer is the results", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    const find = vi.spyOn(viewer.file!, "find");
    await viewer.search("Item B");
    expect(find).toHaveBeenCalledWith({ query: "Item B" });
    expect(viewer.query).toBe("Item B");
    const ids = (viewer.results as SearchView).groups.flatMap((g) => g.results.map((r) => r.id));
    expect(ids).toContain("Item:b");
    await viewer.search("  ");
    expect(viewer.results).toBeNull();
    expect(find).toHaveBeenCalledTimes(1);
  });

  it("a node page calls get, neighbors and cite on the node", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    const file = viewer.file!;
    const get = vi.spyOn(file, "get");
    const neighbors = vi.spyOn(file, "neighbors");
    const cite = vi.spyOn(file, "cite");
    await viewer.show("Item:a");
    expect(get).toHaveBeenCalledWith({ id: "Item:a" });
    expect(neighbors).toHaveBeenCalledWith({ id: "Item:a", edge: "in_group", direction: "out" });
    expect(cite).toHaveBeenCalledWith({ id: "Item:a" });
    expect(viewer.page && "node" in viewer.page && viewer.page.node.id).toBe("Item:a");
    await viewer.show(null);
    expect(viewer.page).toBeNull();
  });

  it("a slow answer never replaces a newer one", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    const first = viewer.search("Item A");
    const second = viewer.search("Group");
    await Promise.all([second, first]);
    expect((viewer.results as SearchView).query).toBe("Group");
  });
});
