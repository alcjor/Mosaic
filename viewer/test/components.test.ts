// M2.9: the search results list each result's id, type, label and how it matched; a node page
// shows what `get` returns, its links from `neighbors`, each opening the other node, and its
// sources from `cite`. Rendered on the server side of Svelte, from real kit answers.
import { render } from "svelte/server";
import { describe, expect, it } from "vitest";
import App from "../src/App.svelte";
import EntityCard from "../src/components/EntityCard.svelte";
import NodeContext from "../src/components/NodeContext.svelte";
import ResultList from "../src/components/ResultList.svelte";
import { nodePage, openMosaic, search, type NodeView, type SearchView } from "../src/lib/mosaic.js";
import { parseRoute, routeHash } from "../src/lib/route.js";
import { Viewer } from "../src/lib/viewer.svelte.js";
import { reading } from "./fixtures.js";

const hrefFor = (id: string) => routeHash({ query: "Item", node: id });

/** The values of `attribute` on every element of the markup that has it. */
function attributes(html: string, attribute: string): string[] {
  return [...html.matchAll(new RegExp(`${attribute}="([^"]*)"`, "g"))].map((m) => m[1]!.replaceAll("&amp;", "&"));
}

describe("ResultList", () => {
  it("lists each result's label, type, id and match, grouped by tier, each linking to its node", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const view = (await search(file, "Item")) as SearchView;
    const results = view.groups.flatMap((g) => g.results);
    expect(results.length).toBeGreaterThan(1);
    const { body } = render(ResultList, { props: { view, selected: "Item:b", hrefFor } });
    for (const r of results) {
      expect(body).toContain(`data-id="${r.id}"`);
      expect(body).toContain(`>${r.label}<`);
      expect(body).toContain(`>${r.type}<`);
      expect(body).toContain(`>${r.id}<`);
    }
    expect(attributes(body, "data-match")).toEqual(results.map((r) => r.match));
    expect(attributes(body, "href").map((h) => parseRoute(h).node)).toEqual(results.map((r) => r.id));
    expect(body).toMatch(/aria-current="page"[^>]*data-id="Item:b"/);
    for (const g of view.groups) expect(body).toContain({ exact: ">Exact<", text: ">Text<", vector: ">Similar<" }[g.match]);
    file.close();
  });

  it("says when nothing matched, and shows a tool's error", () => {
    expect(render(ResultList, { props: { view: { query: "zz", groups: [], total: 0 }, hrefFor } }).body).toContain("No results for “zz”");
    const failed = render(ResultList, { props: { view: { message: "find: bad query", suggestions: [] }, hrefFor } }).body;
    expect(failed).toContain('role="alert"');
    expect(failed).toContain("find: bad query");
  });

  it("text from the file is escaped, never markup", () => {
    const view: SearchView = {
      query: "x",
      total: 1,
      groups: [{ match: "text", results: [{ id: "Item:<b>", type: "Item", label: "<script>alert(1)</script>", match: "text" }] }],
    };
    const { body } = render(ResultList, { props: { view, hrefFor } });
    expect(body).not.toContain("<script>");
    expect(body).toContain("&lt;script>");
  });
});

describe("node page", () => {
  it("the card shows what get returns: label, type, id, summary and properties", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const view = (await nodePage(file, "Item:b")) as NodeView;
    const { body } = render(EntityCard, { props: { node: view.node } });
    expect(body).toContain("Item B");
    expect(body).toContain("Item:b");
    expect(body).toContain(">Item<");
    expect(body).toContain("Second");
    for (const [key, value] of Object.entries(view.node.props ?? {})) {
      expect(body).toContain(`>${key}<`);
      expect(body).toContain(`>${typeof value === "string" ? value : JSON.stringify(value)}<`);
    }
    file.close();
  });

  it("the context shows the links from neighbors, each opening the other node, and the sources from cite", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const view = (await nodePage(file, "Group:x")) as NodeView;
    const { body } = render(NodeContext, { props: { view, hrefFor } });
    expect(body).toContain("← in group · 2");
    const links = attributes(body, "href").map(parseRoute);
    expect(links).toEqual([
      { query: "Item", node: "Item:a" },
      { query: "Item", node: "Item:b" },
    ]);
    for (const row of view.sources) {
      expect(body).toContain(`${row.source}${row.locator ? `:${row.locator}` : ""}`);
      if (row.snippet) expect(body).toContain(row.snippet);
    }
    expect(view.sources.length).toBeGreaterThan(0);
    file.close();
  });
});

describe("App", () => {
  it("before a mosaic is open, offers to open one and the search box is disabled", () => {
    const { body } = render(App, { props: { viewer: new Viewer() } });
    expect(body).toContain("Open a mosaic");
    expect(body).toMatch(/type="file"/);
    expect(body).toMatch(/type="search"[^>]*disabled/);
  });

  it("with a mosaic open, names it with its short hash, and shows the results and the node page", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    await viewer.search("Item");
    await viewer.show("Item:a");
    const { body } = render(App, { props: { viewer } });
    const hash = viewer.file!.header.knowledge_hash;
    expect(body).toContain(">mosaic.mosaic<");
    expect(body).toContain(`>${hash.slice(0, 12)}<`);
    expect(body).toMatch(/type="search"(?![^>]*disabled)/);
    expect(body).toContain('aria-label="Results"');
    expect(body).toContain('aria-label="Item:a"');
    expect(body).toContain('aria-label="Links and sources"');
  });
});
