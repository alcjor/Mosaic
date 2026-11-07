// M2.9: the viewer opens a mosaic with the kit running inside the page, with no query server;
// the search box's results come from `find`, and a node page from `get`, `neighbors` and `cite`
// (Specification 0.1, sections 3.8, 8.1 and 8.2).
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchNamedMosaic, nodePage, openMosaic, search, shortHash, type NodeView, type SearchView } from "../src/lib/mosaic.js";
import { reading } from "./fixtures.js";

afterEach(() => vi.unstubAllGlobals());

const noServer = () =>
  vi.stubGlobal(
    "fetch",
    vi.fn(() => {
      throw new Error("the viewer asked a server");
    }),
  );

describe("opening a mosaic in the page", () => {
  it("opens the bytes with the kit, which checks the reading rules, and asks no server", async () => {
    (await openMosaic(reading("mosaic.mosaic"), "warm.mosaic")).close(); // SQLite loaded once
    noServer();
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    expect(file.name).toBe("mosaic.mosaic");
    expect(file.header.kind).toBe("mosaic");
    expect(shortHash(file.header.knowledge_hash)).toBe(file.header.knowledge_hash.slice(0, 12));
    await search(file, "Item");
    await nodePage(file, "Item:a");
    expect(fetch).not.toHaveBeenCalled();
    file.close();
  });

  it("a file the reading rules refuse is an error naming it", async () => {
    await expect(openMosaic(reading("user-version.mosaic"), "user-version.mosaic")).rejects.toThrow(/user-version\.mosaic/);
  });

  it("fetches the mosaic the address names with ?mosaic=, and nothing when none is named", async () => {
    const bytes = reading("mosaic.mosaic");
    const fetcher = vi.fn(async (url: URL | RequestInfo) => {
      expect(String(url)).toBe("http://localhost:8000/files/my%20data.mosaic");
      return new Response(bytes);
    });
    const named = await fetchNamedMosaic("?mosaic=files/my%20data.mosaic", "http://localhost:8000/index.html", fetcher as typeof fetch);
    expect(named?.name).toBe("my data.mosaic");
    expect(named?.bytes).toEqual(bytes);
    expect(await fetchNamedMosaic("", "http://localhost:8000/", fetcher as typeof fetch)).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
    const missing = vi.fn(async () => new Response("no", { status: 404, statusText: "Not Found" }));
    await expect(fetchNamedMosaic("?mosaic=x.mosaic", "http://localhost/", missing as typeof fetch)).rejects.toThrow(/x\.mosaic.*404/);
  });
});

describe("search: find's results, grouped by how they matched", () => {
  it("lists each result's id, type, label and match, exact first, as find gives them", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const view = (await search(file, "Item A")) as SearchView;
    const answer = await file.find({ query: "Item A" });
    if (!("data" in answer)) throw new Error("find failed");
    expect(view.total).toBe(answer.data.total);
    expect(view.groups.flatMap((g) => g.results)).toEqual(answer.data.results);
    expect(view.groups.map((g) => g.match)).toEqual([...new Set(answer.data.results.map((r) => r.match))]);
    for (const group of view.groups) expect(group.results.every((r) => r.match === group.match)).toBe(true);
    const exact = (await search(file, "Item:a")) as SearchView;
    expect(exact.groups[0]?.match).toBe("exact");
    expect(exact.groups[0]?.results[0]).toEqual({ id: "Item:a", type: "Item", label: "Item A", match: "exact" });
    file.close();
  });

  it("a query with no match has no group", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    expect(await search(file, "zzzz")).toEqual({ query: "zzzz", groups: [], total: 0 });
    file.close();
  });
});

describe("node page: get, then neighbors per edge type and direction, then cite", () => {
  it("shows what get returns, the links neighbors gives with their counts, and the sources cite gives", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const view = (await nodePage(file, "Group:x")) as NodeView;
    const got = await file.get({ id: "Group:x" });
    const cited = await file.cite({ id: "Group:x" });
    if (!("data" in got) || !("data" in cited)) throw new Error("get or cite failed");
    expect(view.node).toEqual(got.data);
    expect(view.links).toEqual([
      {
        edge: "in_group",
        direction: "in",
        count: 2,
        edges: [
          { edge: "in_group", direction: "in", id: "Item:a", label: "Item A" },
          { edge: "in_group", direction: "in", id: "Item:b", label: "Item B" },
        ],
      },
    ]);
    expect(view.sources).toEqual(cited.data.evidence);
    expect(view.sourcesTotal).toBe(cited.data.total);
    const item = (await nodePage(file, "Item:a")) as NodeView;
    expect(item.links.map((l) => [l.edge, l.direction, l.edges.map((e) => e.id)])).toEqual([["in_group", "out", ["Group:x"]]]);
    file.close();
  });

  it("an unknown id shows the kit's error and the closest matches", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const view = await nodePage(file, "Item:Item");
    expect("message" in view && view.message).toMatch(/Item:Item/);
    expect("suggestions" in view && view.suggestions.length).toBeGreaterThan(0);
    file.close();
  });
});
