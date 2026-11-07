// M3.6: the viewer shaped by a view file (docs/design.md, Implementation plan, "View file"; the
// keys and defaults answered on #120). The page lists only the view file's types, in its order;
// its tables show the file's columns; its labels replace type, property and edge names; node
// pages show what its `page` names; the theme and the search field's mode switch follow it; and
// a name the mosaic does not have shows a notice while the page still opens. A type left out is
// absent from the type list and tables only: search and links still reach it (Reading A).
import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import App from "../src/App.svelte";
import EntityCard from "../src/components/EntityCard.svelte";
import NodeContext from "../src/components/NodeContext.svelte";
import ResultList from "../src/components/ResultList.svelte";
import SearchField from "../src/components/SearchField.svelte";
import TableView from "../src/components/TableView.svelte";
import TypeList from "../src/components/TypeList.svelte";
import { nodePage, openMosaic, search, type NodeView, type SearchView } from "../src/lib/mosaic.js";
import { routeHash, type TableRoute } from "../src/lib/route.js";
import { tableArgs, type TableView as Table } from "../src/lib/tables.js";
import { applyTheme, DEFAULT_VIEW, fetchNamedView, parseView, Shape, type ViewSettings } from "../src/lib/view.js";
import { Viewer } from "../src/lib/viewer.svelte.js";
import { reading } from "./fixtures.js";

const hrefFor = (id: string) => routeHash({ query: "", node: id });
const tableHref = (route: TableRoute) => routeHash({ query: "", node: null, table: route });
const route = (type: string): TableRoute => ({ type, page: 1, order: null, where: [] });

/** A view file's settings in the JSON form `mosaic view` hands the page (`ViewSettings.as_json`). */
function settings(json: object): ViewSettings {
  return parseView({ search: "semantic", theme: "auto", types: null, export: { types: null }, ...json });
}

const SHAPED = settings({
  search: "text",
  theme: "dark",
  types: [
    {
      name: "Item",
      label: "Thing",
      columns: ["size"],
      page: ["in_group", "size"],
      names: { size: "How big", in_group: "Belongs to" },
    },
  ],
});

async function open(): Promise<Awaited<ReturnType<typeof openMosaic>>> {
  return openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
}

function attributes(html: string, attribute: string): string[] {
  return [...html.matchAll(new RegExp(`${attribute}="([^"]*)"`, "g"))].map((m) => m[1]!.replaceAll("&amp;", "&"));
}

describe("the view file's settings", () => {
  it("default to M2's viewer", () => {
    expect(settings({})).toEqual(DEFAULT_VIEW);
    expect(parseView({})).toEqual(DEFAULT_VIEW);
    expect(DEFAULT_VIEW).toEqual({ search: "semantic", theme: "auto", types: null, exportTypes: null });
  });

  it("read every setting from the JSON form, types in order", () => {
    const view = settings({
      types: [
        { name: "Zeta", label: null, columns: null, page: null, names: {} },
        { name: "Alpha", label: "A", columns: ["x"], page: ["y", "x"], names: { x: "Ex" } },
      ],
      export: { types: ["Alpha"] },
    });
    expect(view.types!.map((t) => t.name)).toEqual(["Zeta", "Alpha"]);
    expect(view.types![1]).toEqual({ name: "Alpha", label: "A", columns: ["x"], page: ["y", "x"], names: new Map([["x", "Ex"]]) });
    expect(view.exportTypes).toEqual(["Alpha"]);
  });

  it.each([
    [{ search: "fuzzy" }, /search/],
    [{ theme: "sepia" }, /theme/],
    [{ types: {} }, /types/],
    [{ types: [{ name: "" }] }, /types\[0\]\.name/],
    [{ types: [{ name: "A", columns: "x" }] }, /types\[0\]\.columns/],
    [{ types: [{ name: "A", names: { x: 1 } }] }, /types\[0\]\.names\.x/],
    [{ export: { types: [1] } }, /export\.types\[0\]/],
  ])("a malformed settings object %j is an error naming the setting", (json, named) => {
    expect(() => settings(json)).toThrow(named);
  });

  it("are fetched from the address's ?view=<url>, or absent without one", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ search: "text" })));
    expect(await fetchNamedView("?mosaic=file/a.mosaic", "http://127.0.0.1/", fetcher)).toBeNull();
    const view = await fetchNamedView("?mosaic=file/a.mosaic&view=view.json", "http://127.0.0.1/x/", fetcher);
    expect(view?.search).toBe("text");
    expect(String((fetcher.mock.calls[0] as unknown[])[0])).toBe("http://127.0.0.1/x/view.json");
    const bad = vi.fn(async () => new Response("not json"));
    await expect(fetchNamedView("?view=v.json", "http://127.0.0.1/", bad)).rejects.toThrow(/view file/);
  });
});

describe("the page lists only the view file's types", () => {
  it("with no view file, every node type, by name, under its own name", async () => {
    const file = await open();
    const shape = new Shape(DEFAULT_VIEW, file);
    expect(shape.types.map((t) => t.name)).toEqual(["Group", "Item"]);
    expect(shape.notices).toEqual([]);
    expect(shape.typeLabel("Item")).toBe("Item");
    expect(shape.columns("Item")).toBeNull();
    expect(shape.page("Item")).toBeNull();
    file.close();
  });

  it("with one, only its types, in the order it writes them, under its labels", async () => {
    const file = await open();
    const view = settings({
      types: [
        { name: "Item", label: "Thing", columns: null, page: null, names: {} },
        { name: "Group", label: null, columns: null, page: null, names: {} },
      ],
    });
    const shape = new Shape(view, file);
    expect(shape.types.map((t) => t.name)).toEqual(["Item", "Group"]);
    const { body } = render(TypeList, {
      props: { types: shape.types, hrefFor: (t: string) => `#${t}`, labelFor: (t: string) => shape.typeLabel(t) },
    });
    expect(attributes(body, "data-type")).toEqual(["Item", "Group"]);
    expect(body).toContain(">Thing<");
    expect(body).not.toContain(">Item<");
    expect(new Shape(SHAPED, file).types.map((t) => t.name)).toEqual(["Item"]);
    file.close();
  });

  it("a type left out has no table, but search and links still reach its nodes", async () => {
    const viewer = new Viewer();
    await viewer.setView(SHAPED);
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    const table = vi.spyOn(viewer.file!, "table");
    await viewer.showTable(route("Group"));
    expect(viewer.table).toMatchObject({ message: expect.stringMatching(/Group/) });
    expect(table).not.toHaveBeenCalled();
    await viewer.search("Group x");
    const ids = (viewer.results as SearchView).groups.flatMap((g) => g.results.map((r) => r.id));
    expect(ids).toContain("Group:x");
    await viewer.show("Item:a");
    const page = viewer.page as NodeView;
    expect(page.links.flatMap((l) => l.edges.map((e) => e.id))).toContain("Group:x");
    await viewer.show("Group:x");
    expect((viewer.page as NodeView).node.id).toBe("Group:x");
  });
});

describe("tables show the view file's columns", () => {
  it("table is asked for the node's name, then the file's columns", async () => {
    expect(tableArgs(route("Item"), ["size", "code"])).toEqual({ type: "Item", page: 1, columns: ["label", "size", "code"] });
    expect(tableArgs(route("Item"))).toEqual({ type: "Item", page: 1 });
    const viewer = new Viewer();
    await viewer.setView(SHAPED);
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    const table = vi.spyOn(viewer.file!, "table");
    await viewer.showTable(route("Item"));
    expect(table).toHaveBeenCalledWith({ type: "Item", page: 1, columns: ["label", "size"] });
    expect((viewer.table as Table).columns).toEqual(["id", "label", "size"]);
  });

  it("the table's title and headers carry the file's labels", async () => {
    const file = await open();
    const shape = new Shape(SHAPED, file);
    const view: Table = { route: route("Item"), columns: ["id", "label", "size"], rows: [["Item:a", "Item A", 1]], page: 1, total: 1, pages: 1 };
    const { body } = render(TableView, {
      props: { view, route: route("Item"), hrefFor: tableHref, nodeHref: hrefFor, onfilter: () => {}, shape },
    });
    expect(body).toContain(">Thing<");
    expect(body).toMatch(/data-column="size"[^>]*>How big</);
    expect(body).toContain('<option value="size">How big</option>');
    file.close();
  });

  it("without a view file, the table and its headers are as M2's", async () => {
    const file = await open();
    const view: Table = { route: route("Item"), columns: ["id", "label", "size"], rows: [], page: 1, total: 0, pages: 1 };
    const props = { view, route: route("Item"), hrefFor: tableHref, nodeHref: hrefFor, onfilter: () => {} };
    expect(render(TableView, { props: { ...props, shape: new Shape(DEFAULT_VIEW, file) } }).body).toBe(render(TableView, { props }).body);
    file.close();
  });
});

describe("node pages show what the view file sets", () => {
  it("the card shows the properties `page` names, in its order, under its labels", async () => {
    const file = await open();
    const shape = new Shape(settings({ types: [{ name: "Item", label: "Thing", columns: null, page: ["size", "code"], names: { code: "Code" } }] }), file);
    const view = (await nodePage(file, "Item:a")) as NodeView;
    const { body } = render(EntityCard, { props: { node: view.node, shape } });
    expect(attributes(body, "data-prop")).toEqual(["size", "code"]);
    expect(body).toMatch(/data-prop="code"[^>]*>Code</);
    expect(body).toMatch(/data-prop="size"[^>]*>size</);
    expect(body).toContain(">Thing<");
    const only = new Shape(settings({ types: [{ name: "Item", label: null, columns: null, page: ["in_group"], names: {} }] }), file);
    expect(attributes(render(EntityCard, { props: { node: view.node, shape: only } }).body, "data-prop")).toEqual([]);
    file.close();
  });

  it("the links are the edge types `page` names, under its labels", async () => {
    const file = await open();
    const view = (await nodePage(file, "Item:a")) as NodeView;
    const shown = render(NodeContext, { props: { view, hrefFor, shape: new Shape(SHAPED, file) } }).body;
    expect(shown).toContain("Belongs to · 1");
    expect(shown).toContain('data-id="Group:x"');
    const hidden = new Shape(settings({ types: [{ name: "Item", label: null, columns: null, page: ["size"], names: {} }] }), file);
    const none = render(NodeContext, { props: { view, hrefFor, shape: hidden } }).body;
    expect(none).toContain("No links.");
    expect(none).not.toContain('data-id="Group:x"');
    file.close();
  });

  it("an incoming edge on the page takes its type's label, after an arrow", async () => {
    const file = await open();
    const view = (await nodePage(file, "Group:x")) as NodeView;
    const shape = new Shape(settings({ types: [{ name: "Group", label: null, columns: null, page: ["in_group"], names: { in_group: "Members" } }] }), file);
    expect(render(NodeContext, { props: { view, hrefFor, shape } }).body).toContain("← Members · 2");
    file.close();
  });

  it("without a view file, the node page is as M2's", async () => {
    const file = await open();
    const view = (await nodePage(file, "Item:a")) as NodeView;
    const shape = new Shape(DEFAULT_VIEW, file);
    expect(render(EntityCard, { props: { node: view.node, shape } }).body).toBe(render(EntityCard, { props: { node: view.node } }).body);
    expect(render(NodeContext, { props: { view, hrefFor, shape } }).body).toBe(render(NodeContext, { props: { view, hrefFor } }).body);
    file.close();
  });

  it("search results carry the type's label", async () => {
    const file = await open();
    const shape = new Shape(SHAPED, file);
    const view = (await search(file, "Item A")) as SearchView;
    const body = render(ResultList, { props: { view, hrefFor, typeLabel: (t: string) => shape.typeLabel(t) } }).body;
    expect(body).toContain(">Thing<");
    file.close();
  });
});

describe("the theme and the search mode follow the view file", () => {
  it("auto follows the system; light and dark fix the theme", () => {
    const root = { dataset: {} as Record<string, string | undefined> };
    applyTheme(root, "dark");
    expect(root.dataset.theme).toBe("dark");
    applyTheme(root, "light");
    expect(root.dataset.theme).toBe("light");
    applyTheme(root, "auto");
    expect("theme" in root.dataset).toBe(false);
  });

  it("the viewer takes the file's theme and search mode", async () => {
    const viewer = new Viewer();
    expect(viewer.view.theme).toBe("auto");
    expect(viewer.mode).toBe("semantic");
    await viewer.setView(SHAPED);
    expect(viewer.view.theme).toBe("dark");
    expect(viewer.mode).toBe("text");
  });

  it("the mode switch shows Semantic and Text, the file's mode pressed", () => {
    const semantic = render(SearchField, { props: { onsearch: () => {} } }).body;
    expect(semantic).toContain(">Semantic<");
    expect(semantic).toContain(">Text<");
    expect(semantic).toMatch(/aria-pressed="true"[^>]*data-mode="semantic"/);
    const text = render(SearchField, { props: { mode: "text", onsearch: () => {} } }).body;
    expect(text).toMatch(/aria-pressed="true"[^>]*data-mode="text"/);
    expect(text).toMatch(/aria-pressed="false"[^>]*data-mode="semantic"/);
  });

  it("Text searches without the embedder, Semantic with it; switching opens the same mosaic again", async () => {
    const embedder = { model: "none", embedQuery: async () => new Float32Array(384) };
    const viewer = new Viewer();
    viewer.embedder = embedder;
    expect(viewer.searchEmbedder).toBe(embedder);
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    await viewer.search("Item");
    await viewer.show("Item:a");
    const first = viewer.file;
    await viewer.setMode("text");
    expect(viewer.searchEmbedder).toBeNull();
    expect(viewer.file).not.toBe(first);
    expect(viewer.file?.name).toBe("mosaic.mosaic");
    expect((viewer.results as SearchView).query).toBe("Item");
    expect((viewer.page as NodeView).node.id).toBe("Item:a");
    await viewer.setMode("semantic");
    expect(viewer.searchEmbedder).toBe(embedder);
  });

  it("the page's search field shows the viewer's mode", async () => {
    const viewer = new Viewer();
    await viewer.setView(SHAPED);
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    expect(render(App, { props: { viewer } }).body).toMatch(/aria-pressed="true"[^>]*data-mode="text"/);
  });
});

describe("a view file naming what the mosaic does not have", () => {
  const WRONG = settings({
    types: [
      { name: "Nothing", label: null, columns: null, page: null, names: {} },
      { name: "Item", label: null, columns: ["size", "weight"], page: ["colour", "in_group"], names: { shade: "Shade", code: "Code" } },
    ],
  });

  it("shows a notice for each, and leaves each out", async () => {
    const file = await open();
    const shape = new Shape(WRONG, file);
    expect(shape.types.map((t) => t.name)).toEqual(["Item"]);
    expect(shape.columns("Item")).toEqual(["size"]);
    expect(shape.page("Item")).toEqual(["in_group"]);
    expect(shape.notices).toEqual([
      "view file: types.Nothing: the mosaic has no node type Nothing",
      "view file: types.Item.columns: Item has no property weight",
      "view file: types.Item.page: Item has no property or edge type colour",
      "view file: types.Item.names: Item has no property or edge type shade",
    ]);
    expect(shape.label("Item", "shade")).toBeNull();
    expect(shape.label("Item", "code")).toBe("Code");
    file.close();
  });

  it("an edge type that only enters the type is not one of its columns", async () => {
    const file = await open();
    const shape = new Shape(settings({ types: [{ name: "Group", label: null, columns: ["in_group"], page: ["in_group"], names: {} }] }), file);
    expect(shape.columns("Group")).toEqual([]);
    expect(shape.page("Group")).toEqual(["in_group"]);
    expect(shape.notices).toEqual(["view file: types.Group.columns: Group has no property in_group"]);
    file.close();
  });

  it("the page still opens, with the notices", async () => {
    const viewer = new Viewer();
    await viewer.setView(WRONG);
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    expect(viewer.status).toBe("ready");
    await viewer.showTable(route("Item"));
    expect((viewer.table as Table).columns).toEqual(["id", "label", "size"]);
    const { body } = render(App, { props: { viewer } });
    expect(body).toContain('aria-label="View file notices"');
    expect(body).toContain("the mosaic has no node type Nothing");
    expect(body).toContain('aria-label="Table Item"');
  });

  it("a page with no view file shows no notice", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    expect(render(App, { props: { viewer } }).body).not.toContain("View file notices");
  });
});

describe("decided edges", () => {
  it("an incoming edge with no label on the page's type takes its source type's label", async () => {
    const file = await open();
    const view = (await nodePage(file, "Group:x")) as NodeView;
    const shape = new Shape(SHAPED, file);
    expect(shape.edgeLabel("Group", "in_group")).toBe("Belongs to");
    expect(render(NodeContext, { props: { view, hrefFor, shape } }).body).toContain("← Belongs to · 2");
    file.close();
  });

  it("columns past what a table shows are left out with a notice", () => {
    const props = Array.from({ length: 21 }, (_, i) => `p${String(i).padStart(2, "0")}`);
    const schema = { nodeTypes: [{ name: "Item", count: 0 }], edgeTypes: [], propsOf: () => props };
    const shape = new Shape(settings({ types: [{ name: "Item", label: null, columns: props, page: null, names: {} }] }), schema);
    expect(shape.columns("Item")).toEqual(props.slice(0, 19));
    expect(shape.notices).toEqual([
      "view file: types.Item.columns: a table shows at most 19 columns after the name; left out: p19, p20",
    ]);
  });

  it("settings listing a type twice are refused", () => {
    const twice = { name: "A", label: null, columns: null, page: null, names: {} };
    expect(() => settings({ types: [twice, twice] })).toThrow(/types\[1\]\.name/);
  });
});

describe("decided in review", () => {
  it("a table's columns are declared properties only: an edge type leaving the type is a notice", async () => {
    const file = await open();
    const shape = new Shape(settings({ types: [{ name: "Item", label: null, columns: ["in_group", "size"], page: null, names: {} }] }), file);
    expect(shape.columns("Item")).toEqual(["size"]);
    expect(shape.notices).toEqual(["view file: types.Item.columns: Item has no property in_group"]);
    file.close();
  });

  it("a name left out with a notice relabels nothing", async () => {
    const file = await open();
    const shape = new Shape(settings({ types: [{ name: "Item", label: null, columns: null, page: null, names: { label: "Title" } }] }), file);
    expect(shape.notices).toEqual(["view file: types.Item.names: Item has no property or edge type label"]);
    const view: Table = { route: route("Item"), columns: ["id", "label"], rows: [], page: 1, total: 0, pages: 1 };
    const body = render(TableView, { props: { view, route: route("Item"), hrefFor: tableHref, nodeHref: hrefFor, onfilter: () => {}, shape } }).body;
    expect(body).not.toContain(">Title<");
    file.close();
  });

  it("export.types does not make a notice on the page: its meaning is M3.10's", async () => {
    const file = await open();
    expect(new Shape(settings({ export: { types: ["Ghost"] } }), file).notices).toEqual([]);
    file.close();
  });

  it("a name listed twice in a list is refused", () => {
    expect(() => settings({ types: [{ name: "A", label: null, columns: ["x", "x"], page: null, names: {} }] })).toThrow(/types\[0\]\.columns\[1\]/);
  });

  it("of two opens, the later one wins, whichever finishes first", async () => {
    const viewer = new Viewer();
    const first = viewer.open(reading("mosaic.mosaic"), "first.mosaic");
    const second = viewer.open(reading("mosaic.mosaic"), "second.mosaic");
    await Promise.all([second, first]);
    expect(viewer.file?.name).toBe("second.mosaic");
    expect(viewer.status).toBe("ready");
  });
});
