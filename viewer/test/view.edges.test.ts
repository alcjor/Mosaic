// Edge cases for M3.6 (viewer shaped by a view file), written from the spec's words and not the
// implementation, and not repeated from view.test.ts: docs/design.md (Implementation plan, "View
// file"), the keys, values and defaults of views/example.yaml as answered on #120 (Question 1;
// Question 2, Reading A: a type left out is absent from the type list and tables only), brand
// book section 6 (SearchField mode switch), sections 8.1 and 8.6 (`table`), 10 (untrusted data).
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import { buildMosaic, type MosaicSpec } from "../../kit/test/build-mosaic.js";
import App from "../src/App.svelte";
import EntityCard from "../src/components/EntityCard.svelte";
import NodeContext from "../src/components/NodeContext.svelte";
import TableView from "../src/components/TableView.svelte";
import TypeList from "../src/components/TypeList.svelte";
import { nodePage, openMosaic, type NodeView, type SearchView } from "../src/lib/mosaic.js";
import { routeHash, type TableRoute } from "../src/lib/route.js";
import { type TableView as Table } from "../src/lib/tables.js";
import { DEFAULT_VIEW, fetchNamedView, parseView, Shape, type ViewSettings } from "../src/lib/view.js";
import { Viewer } from "../src/lib/viewer.svelte.js";
import { reading } from "./fixtures.js";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const canon = (value: unknown): string => JSON.stringify(value);
const hrefFor = (id: string) => routeHash({ query: "", node: id });
const tableHref = (route: TableRoute) => routeHash({ query: "", node: null, table: route });
const route = (type: string): TableRoute => ({ type, page: 1, order: null, where: [] });

type TypeJson = { name: string; label?: string | null; columns?: string[] | null; page?: string[] | null; names?: Record<string, string> };

/** A view file's settings in the JSON form `mosaic view` hands the page (`ViewSettings.as_json`). */
function settings(json: { search?: string; theme?: string; types?: TypeJson[] | null; export?: { types: string[] | null } }): ViewSettings {
  const types = json.types?.map((t) => ({ label: null, columns: null, page: null, names: {}, ...t }));
  return parseView({ search: "semantic", theme: "auto", export: { types: null }, ...json, types: types ?? null });
}

/** Two types and two edge types; Item has three properties, Other has one of the same name. */
const TWO_EDGES: MosaicSpec = {
  typeProps: {
    Item: canon({ alpha: "text", beta: "integer", gamma: "text" }),
    Other: canon({ alpha: "text" }),
    Tag: canon({ name: "text" }),
  },
  edgeTypes: [
    ["has_tag", "Item", "Tag"],
    ["next_to", "Item", "Other"],
  ],
  nodes: [
    { type: "Item", key: "one", label: "Item one", props: canon({ alpha: "A1", beta: 2, gamma: "G1" }) },
    { type: "Item", key: "bare", label: "Item bare" },
    { type: "Other", key: "o", label: "Other o", props: canon({ alpha: "OA" }) },
    { type: "Tag", key: "t", label: "Tag t" },
  ],
  edges: [
    { type: "has_tag", from: "Item:one", to: "Tag:t" },
    { type: "next_to", from: "Item:one", to: "Other:o" },
  ],
};

async function viewerOn(view: ViewSettings, spec: MosaicSpec = TWO_EDGES): Promise<Viewer> {
  const viewer = new Viewer();
  await viewer.setView(view);
  await viewer.open(buildMosaic(spec), "built.mosaic");
  if (viewer.status !== "ready") throw new Error(`did not open: ${viewer.error}`);
  return viewer;
}

function attributes(html: string, attribute: string): string[] {
  return [...html.matchAll(new RegExp(`${attribute}="([^"]*)"`, "g"))].map((m) => m[1]!.replaceAll("&amp;", "&"));
}

describe("the JSON form Python hands the page", () => {
  // docs/design.md, View file: used by both view and export. `ViewSettings.as_json` is what the
  // page reads (M3.5's hand-off to M3.6); both shipped view files must cross unchanged.
  function asJson(path: string): unknown {
    const code = "import json,sys\nfrom mosaic_build import view_file\nprint(json.dumps(view_file.read(sys.argv[1]).as_json()))";
    const out = execFileSync("uv", ["run", "--quiet", "python", "-I", "-c", code, path], { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    return JSON.parse(out);
  }

  it("views/example.yaml crosses with its types in the order written", () => {
    const view = parseView(asJson("views/example.yaml"));
    expect(view.search).toBe("semantic");
    expect(view.theme).toBe("auto");
    expect(view.types!.map((t) => t.name)).toEqual(["Title", "Person", "Genre"]);
    expect(view.types![0]).toMatchObject({ label: "Film or show", columns: ["release_year", "rating"], page: ["release_year", "directed_by", "features", "listed_in"] });
    expect(view.types![0]!.names.get("release_year")).toBe("Year");
    expect(view.types![1]).toMatchObject({ label: null, columns: null, page: null });
    expect(view.exportTypes).toEqual(["Title", "Person", "Genre"]);
  });

  it("the Netflix view file crosses, with an export default left to M3.10", () => {
    const view = parseView(asJson("conformance/fixtures/netflix/view.yaml"));
    expect(view.types!.map((t) => t.name)).toEqual(["Title", "Person", "Genre", "Country"]);
    expect(view.types![0]!.columns).toEqual(["type", "release_year", "rating", "duration", "duration_unit"]);
    expect(view.types![0]!.names.get("features")).toBe("Cast");
    expect(view.exportTypes).toBeNull();
  });

  it("an empty view file crosses as M2's viewer", () => {
    // docs/design.md / #120: every key optional, an empty file gives M2's viewer.
    const code = "import json\nfrom mosaic_build import view_file\nprint(json.dumps(view_file.from_json({}).as_json()))";
    const out = execFileSync("uv", ["run", "--quiet", "python", "-I", "-c", code], { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    expect(parseView(JSON.parse(out))).toEqual(DEFAULT_VIEW);
  });
});

describe("a malformed settings object or address", () => {
  it.each([[[]], ["text"], [3], [true]])("a settings value %j that is not an object is an error naming the view file", (data) => {
    expect(() => parseView(data)).toThrow(/view file/);
  });

  it("a view address answered with an error status is an error, not M2's viewer", async () => {
    // #120: "no view file gives the viewer M2 has"; a view file that cannot be read is not "none".
    const missing = vi.fn(async () => new Response("gone", { status: 404 }));
    await expect(fetchNamedView("?view=view.json", "http://127.0.0.1/", missing)).rejects.toThrow(/view file/);
  });

  it("a view address that cannot be fetched is an error naming the view file", async () => {
    const down = vi.fn(async () => {
      throw new TypeError("network down");
    });
    await expect(fetchNamedView("?view=view.json", "http://127.0.0.1/", down)).rejects.toThrow(/view file/);
  });

  it("settings for the wrong kind of value in a type's name list name the setting", () => {
    expect(() => settings({ types: [{ name: "A", page: [3 as unknown as string] }] })).toThrow(/types\[0\]\.page\[0\]/);
    expect(() => settings({ types: [{ name: "A", columns: [null as unknown as string] }] })).toThrow(/types\[0\]\.columns\[0\]/);
  });
});

describe("which types appear (docs/design.md, View file; #120 Question 2, Reading A)", () => {
  it("a view file listing no types lists none, and the page still opens and searches", async () => {
    // #120 (assumption 2 of M3.5): `types: {}` lists no types; leaving `types` out lists every one.
    const viewer = await viewerOn(settings({ types: [] }));
    expect(viewer.shape!.types).toEqual([]);
    await viewer.search("Item one");
    const ids = (viewer.results as SearchView).groups.flatMap((g) => g.results.map((r) => r.id));
    expect(ids).toContain("Item:one");
    await viewer.show("Item:one");
    expect((viewer.page as NodeView).node.id).toBe("Item:one");
    expect(render(App, { props: { viewer } }).body).not.toContain("View file notices");
  });

  it("type names are matched exactly: `item` is not `Item`", async () => {
    const file = await openMosaic(buildMosaic(TWO_EDGES), "built.mosaic");
    const shape = new Shape(settings({ types: [{ name: "item" }] }), file);
    expect(shape.types).toEqual([]);
    expect(shape.notices).toHaveLength(1);
    expect(shape.notices[0]).toContain("item");
    file.close();
  });

  it("an edge type's name is not a node type", async () => {
    const file = await openMosaic(buildMosaic(TWO_EDGES), "built.mosaic");
    const shape = new Shape(settings({ types: [{ name: "has_tag" }] }), file);
    expect(shape.types).toEqual([]);
    expect(shape.notices).toHaveLength(1);
    file.close();
  });

  it("export.types does not shape the page: a type the export leaves out is still listed", async () => {
    // #120: what export.types means stays with M3.10; the viewer's type list follows `types` only.
    const file = await openMosaic(buildMosaic(TWO_EDGES), "built.mosaic");
    const shape = new Shape(settings({ export: { types: ["Item"] } }), file);
    expect(shape.types.map((t) => t.name)).toEqual(["Item", "Other", "Tag"]);
    expect(shape.notices).toEqual([]);
    file.close();
  });

  it("a mosaic with no node types and a view file naming types opens, with a notice for each", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "A" }, { name: "B" }] }), { nodes: [] });
    expect(viewer.shape!.types).toEqual([]);
    expect(viewer.shape!.notices).toHaveLength(2);
    expect(render(App, { props: { viewer } }).body).toContain('aria-label="View file notices"');
  });

  it("when every type named is missing, the page opens with notices and no table", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Nope" }] }));
    expect(viewer.status).toBe("ready");
    expect(viewer.shape!.types).toEqual([]);
    expect(viewer.shape!.notices).toHaveLength(1);
    await viewer.showTable(route("Item"));
    expect(viewer.table).toMatchObject({ message: expect.any(String) });
  });

  it("a type left out keeps M2's defaults: its labels, its columns and its node page", async () => {
    const view = settings({ types: [{ name: "Item", label: "Thing", columns: ["alpha"], page: ["alpha"], names: { alpha: "First" } }] });
    const file = await openMosaic(buildMosaic(TWO_EDGES), "built.mosaic");
    const shape = new Shape(view, file);
    expect(shape.lists("Other")).toBe(false);
    expect(shape.typeLabel("Other")).toBe("Other");
    expect(shape.columns("Other")).toBeNull();
    expect(shape.page("Other")).toBeNull();
    expect(shape.label("Other", "alpha")).toBeNull();
    const node = (await nodePage(file, "Other:o")) as NodeView;
    expect(render(EntityCard, { props: { node: node.node, shape } }).body).toBe(render(EntityCard, { props: { node: node.node } }).body);
    file.close();
  });
});

describe("labels (docs/design.md, View file; example.yaml: `label` renames the type, `names` its property and edge names)", () => {
  it("a label changes what is shown, never the type's name in links and data attributes", async () => {
    const file = await openMosaic(buildMosaic(TWO_EDGES), "built.mosaic");
    const shape = new Shape(settings({ types: [{ name: "Item", label: "Other" }, { name: "Other", label: "Item" }] }), file);
    const { body } = render(TypeList, { props: { types: shape.types, hrefFor: (t: string) => `#t=${t}`, labelFor: (t: string) => shape.typeLabel(t) } });
    expect(attributes(body, "data-type")).toEqual(["Item", "Other"]);
    expect(attributes(body, "href")).toEqual(["#t=Item", "#t=Other"]);
    file.close();
  });

  it("a table is asked for by the type's name, not its label", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Item", label: "Thing" }] }));
    await viewer.showTable(route("Thing"));
    expect(viewer.table).toMatchObject({ message: expect.any(String) });
    await viewer.showTable(route("Item"));
    expect((viewer.table as Table).rows.length).toBe(2);
  });

  it("names of one type do not relabel the same property of another type", async () => {
    const file = await openMosaic(buildMosaic(TWO_EDGES), "built.mosaic");
    const shape = new Shape(settings({ types: [{ name: "Item", names: { alpha: "First" } }, { name: "Other" }] }), file);
    expect(shape.label("Item", "alpha")).toBe("First");
    expect(shape.label("Other", "alpha")).toBeNull();
    const node = (await nodePage(file, "Other:o")) as NodeView;
    const body = render(EntityCard, { props: { node: node.node, shape } }).body;
    expect(body).toMatch(/data-prop="alpha"[^>]*>alpha</);
    file.close();
  });

  it("names relabel the headers of the default columns too", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Item", names: { beta: "Second" } }] }));
    await viewer.showTable(route("Item"));
    const view = viewer.table as Table;
    expect(view.columns).toEqual(["id", "label", "alpha", "beta", "gamma"]);
    const body = render(TableView, { props: { view, route: route("Item"), hrefFor: tableHref, nodeHref: hrefFor, onfilter: () => {}, shape: viewer.shape } }).body;
    expect(body).toMatch(/data-column="beta"[^>]*>Second</);
    expect(body).toMatch(/data-column="alpha"[^>]*>alpha</);
  });

  it("a label of the view file is text, never markup (section 10)", async () => {
    // Section 10: data from a file is untrusted. A view file is edited by hand, but its labels
    // reach the page through the same rendering as the mosaic's own text.
    const hostile = '<img src=x onerror="boom()"><script>boom()</script>';
    const view = settings({ types: [{ name: "Item", label: hostile, columns: ["alpha"], page: ["alpha", "has_tag"], names: { alpha: hostile, has_tag: hostile } }] });
    const viewer = await viewerOn(view);
    await viewer.showTable(route("Item"));
    await viewer.show("Item:one");
    const pieces = [
      render(TypeList, { props: { types: viewer.shape!.types, hrefFor: (t: string) => `#${t}`, labelFor: (t: string) => viewer.shape!.typeLabel(t) } }).body,
      render(TableView, { props: { view: viewer.table as Table, route: route("Item"), hrefFor: tableHref, nodeHref: hrefFor, onfilter: () => {}, shape: viewer.shape } }).body,
      render(EntityCard, { props: { node: (viewer.page as NodeView).node, shape: viewer.shape } }).body,
      render(NodeContext, { props: { view: viewer.page as NodeView, hrefFor, shape: viewer.shape } }).body,
    ];
    for (const body of pieces) {
      expect(body).not.toContain("<script>");
      expect(body).not.toContain("<img");
    }
    expect(pieces.some((b) => b.includes("&lt;script"))).toBe(true);
  });

  it("a type name the mosaic does not have is shown in its notice as text, never markup", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "<script>boom()</script>" }] }));
    const body = render(App, { props: { viewer } }).body;
    expect(body).toContain('aria-label="View file notices"');
    expect(body).not.toContain("<script>boom");
  });

  it("a label with a NUL or a very long text does not stop the page", async () => {
    const long = "L".repeat(20000);
    const viewer = await viewerOn(settings({ types: [{ name: "Item", label: `a\u0000b${long}` }] }));
    await viewer.showTable(route("Item"));
    expect(viewer.status).toBe("ready");
    expect(() => render(App, { props: { viewer } })).not.toThrow();
  });
});

describe("columns (example.yaml: the node's name, then these properties; at most 20 in all, section 8.6)", () => {
  it("none listed gives the node's name alone", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Item", columns: [] }] }));
    await viewer.showTable(route("Item"));
    expect((viewer.table as Table).columns).toEqual(["id", "label"]);
    expect((viewer.table as Table).total).toBe(2);
  });

  it("the file's order is the table's order, not the type's declared order", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Item", columns: ["gamma", "alpha"] }] }));
    await viewer.showTable(route("Item"));
    expect((viewer.table as Table).columns).toEqual(["id", "label", "gamma", "alpha"]);
    const row = (viewer.table as Table).rows.find((r) => r[0] === "Item:one")!;
    expect(row.slice(2)).toEqual(["G1", "A1"]);
  });

  it("a property the node has not is an empty cell, not the text null or undefined", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Item", columns: ["alpha"] }] }));
    await viewer.showTable(route("Item"));
    const body = render(TableView, { props: { view: viewer.table as Table, route: route("Item"), hrefFor: tableHref, nodeHref: hrefFor, onfilter: () => {}, shape: viewer.shape } }).body;
    expect(body).not.toContain("undefined");
    expect(body).not.toMatch(/>null</);
  });

  it("an edge type leaving the type is a column (section 8.6: a column is a property, a field or an edge type)", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Item", columns: ["has_tag"] }] }));
    await viewer.showTable(route("Item"));
    const view = viewer.table as Table;
    expect(view.columns).toEqual(["id", "label", "has_tag"]);
    expect(view.rows.find((r) => r[0] === "Item:one")![2]).toEqual(["Tag t"]);
    expect(viewer.shape!.notices).toEqual([]);
  });

  it("more columns than a table can show never stop the page (section 8.6: at most 20)", async () => {
    const declared = Object.fromEntries(Array.from({ length: 25 }, (_, i) => [`p${String(i).padStart(2, "0")}`, "text"]));
    const names = Object.keys(declared);
    const spec: MosaicSpec = { typeProps: { Item: canon(declared) }, nodes: [{ type: "Item", key: "a" }] };
    const viewer = await viewerOn(settings({ types: [{ name: "Item", columns: names }] }), spec);
    await viewer.showTable(route("Item"));
    expect(viewer.status).toBe("ready");
    const table = viewer.table as Table | { message: string };
    if ("columns" in table) expect(table.columns.length).toBeLessThanOrEqual(21);
    else expect(table.message).toEqual(expect.any(String));
    expect(() => render(App, { props: { viewer } })).not.toThrow();
  });

  it("sorting a table by a column the view file does not show does not stop the page", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Item", columns: ["alpha"] }] }));
    await viewer.showTable({ type: "Item", page: 1, order: { column: "gamma", desc: false }, where: [] });
    expect(viewer.status).toBe("ready");
    expect(viewer.table).not.toBeNull();
    expect(() => render(App, { props: { viewer } })).not.toThrow();
  });

  it("a filter on a column the view file does not show still answers (section 8.6: where allows any column)", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Item", columns: ["alpha"] }] }));
    await viewer.showTable({ type: "Item", page: 1, order: null, where: [{ column: "gamma", op: "=", value: "G1" }] });
    const view = viewer.table as Table;
    expect(view.rows.map((r) => r[0])).toEqual(["Item:one"]);
    expect(view.columns).toEqual(["id", "label", "alpha"]);
  });
});

describe("what a node page shows (example.yaml: these properties and edge types, in this order)", () => {
  it("an empty `page` shows no property and no link", async () => {
    const viewer = await viewerOn(settings({ types: [{ name: "Item", page: [] }] }));
    await viewer.show("Item:one");
    const view = viewer.page as NodeView;
    const shape = viewer.shape!;
    expect(attributes(render(EntityCard, { props: { node: view.node, shape } }).body, "data-prop")).toEqual([]);
    const links = render(NodeContext, { props: { view, hrefFor, shape } }).body;
    expect(links).toContain("No links.");
    expect(links).not.toContain('data-id="Tag:t"');
    expect(links).not.toContain('data-id="Other:o"');
  });

  it("the edge types are in the order `page` writes them, not the mosaic's", async () => {
    const file = await openMosaic(buildMosaic(TWO_EDGES), "built.mosaic");
    const view = (await nodePage(file, "Item:one")) as NodeView;
    const order = (page: string[]) => {
      const shape = new Shape(settings({ types: [{ name: "Item", page }] }), file);
      const body = render(NodeContext, { props: { view, hrefFor, shape } }).body;
      return [body.indexOf('data-id="Tag:t"'), body.indexOf('data-id="Other:o"')];
    };
    const [tag1, other1] = order(["has_tag", "next_to"]);
    expect(tag1).toBeGreaterThan(-1);
    expect(tag1).toBeLessThan(other1!);
    const [tag2, other2] = order(["next_to", "has_tag"]);
    expect(other2).toBeGreaterThan(-1);
    expect(other2).toBeLessThan(tag2!);
    file.close();
  });

  it("the properties are in the order `page` writes them", async () => {
    const file = await openMosaic(buildMosaic(TWO_EDGES), "built.mosaic");
    const view = (await nodePage(file, "Item:one")) as NodeView;
    const shape = new Shape(settings({ types: [{ name: "Item", page: ["gamma", "alpha"] }] }), file);
    expect(attributes(render(EntityCard, { props: { node: view.node, shape } }).body, "data-prop")).toEqual(["gamma", "alpha"]);
    file.close();
  });

  it("a node without a property `page` names shows no value for it, and no null or undefined text", async () => {
    const file = await openMosaic(buildMosaic(TWO_EDGES), "built.mosaic");
    const view = (await nodePage(file, "Item:bare")) as NodeView;
    const shape = new Shape(settings({ types: [{ name: "Item", page: ["alpha", "has_tag"] }] }), file);
    const card = render(EntityCard, { props: { node: view.node, shape } }).body;
    const links = render(NodeContext, { props: { view, hrefFor, shape } }).body;
    for (const body of [card, links]) {
      expect(body).not.toContain("undefined");
      expect(body).not.toMatch(/>null</);
    }
    file.close();
  });

  it("the page of a node whose type the file leaves out still opens, with M2's page", async () => {
    // #120 Question 2: links reach nodes of a type left out.
    const viewer = await viewerOn(settings({ types: [{ name: "Item", page: [] }] }));
    await viewer.show("Tag:t");
    const view = viewer.page as NodeView;
    expect(view.node.id).toBe("Tag:t");
    const default_ = render(NodeContext, { props: { view, hrefFor } }).body;
    expect(render(NodeContext, { props: { view, hrefFor, shape: viewer.shape } }).body).toBe(default_);
  });
});

describe("the theme and the search mode (brand book section 6; example.yaml: search, theme)", () => {
  it("a new view file replaces the last, it is not merged into it", async () => {
    const viewer = new Viewer();
    await viewer.setView(settings({ search: "text", theme: "dark", types: [{ name: "Item", label: "Thing" }] }));
    await viewer.open(buildMosaic(TWO_EDGES), "built.mosaic");
    await viewer.setView(settings({}));
    expect(viewer.view).toEqual(DEFAULT_VIEW);
    expect(viewer.mode).toBe("semantic");
    expect(viewer.shape!.types.map((t) => t.name)).toEqual(["Item", "Other", "Tag"]);
    expect(viewer.shape!.typeLabel("Item")).toBe("Item");
    expect(viewer.shape!.notices).toEqual([]);
  });

  it("a view file set while a mosaic is open reshapes the page and keeps the mosaic and its search", async () => {
    // docs/design.md, View file: the page reloads shaped by the new file on save.
    const viewer = new Viewer();
    await viewer.open(buildMosaic(TWO_EDGES), "built.mosaic");
    await viewer.search("Item one");
    await viewer.show("Item:one");
    await viewer.setView(settings({ search: "text", types: [{ name: "Tag" }] }));
    expect(viewer.status).toBe("ready");
    expect(viewer.file?.name).toBe("built.mosaic");
    expect(viewer.mode).toBe("text");
    expect(viewer.shape!.types.map((t) => t.name)).toEqual(["Tag"]);
    expect(viewer.query).toBe("Item one");
    expect((viewer.page as NodeView).node.id).toBe("Item:one");
  });

  it("a view file naming a type or property the mosaic lacks, set on an open mosaic, gives a notice", async () => {
    const viewer = new Viewer();
    await viewer.open(buildMosaic(TWO_EDGES), "built.mosaic");
    expect(viewer.shape?.notices ?? []).toEqual([]);
    await viewer.setView(settings({ types: [{ name: "Item", columns: ["nope"] }] }));
    expect(viewer.shape!.notices).toHaveLength(1);
    await viewer.setView(settings({}));
    expect(viewer.shape!.notices).toEqual([]);
  });

  it("with `search: text` the query is never embedded, and the answer has no vector tier", async () => {
    const embedQuery = vi.fn(async () => new Float32Array(384));
    const viewer = new Viewer();
    viewer.embedder = { model: "none", embedQuery };
    await viewer.setView(settings({ search: "text" }));
    await viewer.open(buildMosaic(TWO_EDGES), "built.mosaic");
    await viewer.search("Item one");
    expect(embedQuery).not.toHaveBeenCalled();
    const groups = (viewer.results as SearchView).groups;
    expect(groups.flatMap((g) => g.results.map((r) => r.id))).toContain("Item:one");
    expect(groups.some((g) => g.match === "vector")).toBe(false);
  });

  it("`search: text` on a mosaic that holds no vectors finds a node by name", async () => {
    const viewer = await viewerOn(settings({ search: "text" }));
    await viewer.search("bare");
    expect((viewer.results as SearchView).groups.flatMap((g) => g.results.map((r) => r.id))).toContain("Item:bare");
  });

  it("the mode switch offers both modes whatever the file sets, and presses exactly one", async () => {
    for (const search of ["semantic", "text"] as const) {
      const viewer = await viewerOn(settings({ search }));
      const body = render(App, { props: { viewer } }).body;
      expect(attributes(body, "data-mode").sort()).toEqual(["semantic", "text"]);
      expect([...body.matchAll(/aria-pressed="true"[^>]*data-mode="(\w+)"/g)].map((m) => m[1])).toEqual([search]);
    }
  });

  it("the same view file and mosaic draw the same page twice", async () => {
    const view = settings({ search: "text", theme: "light", types: [{ name: "Item", label: "Thing", columns: ["alpha"] }, { name: "Gone" }] });
    const one = await viewerOn(view);
    const two = await viewerOn(view);
    await one.showTable(route("Item"));
    await two.showTable(route("Item"));
    expect(render(App, { props: { viewer: one } }).body).toBe(render(App, { props: { viewer: two } }).body);
    expect(one.shape!.notices).toEqual(two.shape!.notices);
  });
});

describe("the page with the committed conformance mosaic and no view file", () => {
  it("draws the same page as a viewer that was never given a view file", async () => {
    const plain = new Viewer();
    await plain.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    const given = new Viewer();
    await given.setView(DEFAULT_VIEW);
    await given.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    expect(render(App, { props: { viewer: given } }).body).toBe(render(App, { props: { viewer: plain } }).body);
  });
});
