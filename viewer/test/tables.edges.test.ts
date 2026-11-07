// Edge cases for M2.10 (viewer: tables rebuilt from node types), written from the spec's words,
// not the implementation: docs/design.md (First milestone: Viewer), sections 3.1 (no integer row
// ids shown), 8.1 and 8.6 (`table`), 8.2 (cut text), 10 (untrusted data), and the milestone's
// wording: "one table per node type the mosaic declares, its columns the type's declared
// properties, filled by `table`", "sorting, filtering by the `where` operators and paging go
// through `table`; a row opens its node page".
import { render } from "svelte/server";
import { describe, expect, it } from "vitest";
import { TEXT_LIMITS, cut } from "@mosaic/kit";
import { buildMosaic, type MosaicSpec } from "../../kit/test/build-mosaic.js";
import App from "../src/App.svelte";
import TableViewComponent from "../src/components/TableView.svelte";
import TypeList from "../src/components/TypeList.svelte";
import { nodePage, openMosaic } from "../src/lib/mosaic.js";
import { OPERATORS, parseRoute, routeHash, type TableRoute } from "../src/lib/route.js";
import { PAGE_ROWS, cellText, filterValue, tableArgs, tableView, type TableView } from "../src/lib/tables.js";
import { Viewer } from "../src/lib/viewer.svelte.js";

const ITEM: TableRoute = { type: "Item", page: 1, order: null, where: [] };
const tableHref = (table: TableRoute) => routeHash({ query: "", node: null, table });
const nodeHref = (id: string) => routeHash({ query: "", node: id });
const canon = (value: unknown): string => JSON.stringify(value);

function attributes(html: string, attribute: string): string[] {
  return [...html.matchAll(new RegExp(`${attribute}="([^"]*)"`, "g"))].map((m) => m[1]!.replaceAll("&amp;", "&"));
}

async function open(spec: MosaicSpec) {
  return openMosaic(buildMosaic(spec), "built.mosaic");
}

async function viewOf(spec: MosaicSpec, route: TableRoute): Promise<TableView> {
  const file = await open(spec);
  const view = await tableView(file, route);
  file.close();
  if (!("rows" in view)) throw new Error(`not a table view: ${JSON.stringify(view)}`);
  return view;
}

function draw(view: TableView, route: TableRoute = view.route): string {
  return render(TableViewComponent, { props: { view, route, hrefFor: tableHref, nodeHref, onfilter: () => {} } }).body;
}

/** The hrefs of the anchors whose opening tag carries `needle` (an attribute, in any order). */
function anchors(html: string, needle: RegExp): string[] {
  return [...html.matchAll(/<a\s[^>]*>/g)]
    .map((m) => m[0])
    .filter((tag) => needle.test(tag))
    .map((tag) => /href="([^"]*)"/.exec(tag)?.[1]?.replaceAll("&amp;", "&") ?? "");
}

const ids = (view: TableView): unknown[] => view.rows.map((r) => r[0]);
const numbered = (n: number): MosaicSpec => ({
  typeProps: { Item: '{"n":"integer"}' },
  nodes: Array.from({ length: n }, (_, i) => ({ type: "Item", key: String(i).padStart(3, "0"), props: canon({ n: i }) })),
});

describe("one table per declared node type (design.md Viewer; section 8.6)", () => {
  it("a declared type with no nodes still has its table, empty, one page, total 0", async () => {
    const spec: MosaicSpec = { types: ["Empty"], nodes: [{ type: "Item", key: "a" }] };
    const file = await open(spec);
    expect(file.nodeTypes).toContainEqual({ name: "Empty", count: 0 });
    const { body } = render(TypeList, { props: { types: file.nodeTypes, hrefFor: (t: string) => tableHref({ ...ITEM, type: t }) } });
    expect(attributes(body, "data-type")).toEqual(["Empty", "Item"]);
    file.close();
    const view = await viewOf(spec, { ...ITEM, type: "Empty" });
    expect(view.rows).toEqual([]);
    expect(view.total).toBe(0);
    expect(view.pages).toBe(1);
    expect(view.columns[0]).toBe("id");
    expect(draw(view)).not.toContain("undefined");
  });

  it("a mosaic with no node at all lists no table and does not break the page", async () => {
    const viewer = new Viewer();
    await viewer.open(buildMosaic({ nodes: [] }), "empty.mosaic");
    expect(viewer.status).toBe("ready");
    const { body } = render(App, { props: { viewer } });
    expect(body).not.toContain("undefined");
    expect(attributes(body, "data-type")).toEqual([]);
  });

  it("tables are listed by type name in UTF-8 byte order, each with its own link and count", async () => {
    const names = ["Zed", "Ab", "AB", "A1", "B"];
    const file = await open({ types: names, nodes: [{ type: "B", key: "1" }] });
    const { body } = render(TypeList, { props: { types: file.nodeTypes, hrefFor: (t: string) => tableHref({ ...ITEM, type: t }) } });
    file.close();
    expect(attributes(body, "data-type")).toEqual(["A1", "AB", "Ab", "B", "Zed"]);
    expect(attributes(body, "href").map((h) => parseRoute(h).table?.type)).toEqual(["A1", "AB", "Ab", "B", "Zed"]);
  });

  it("a type name taken from the address that looks like markup is shown as text, never as markup", async () => {
    const evil = `"><script>alert(1)</script><img src=x onerror=alert(2)>`;
    const viewer = new Viewer();
    await viewer.open(buildMosaic({ nodes: [{ type: "Item", key: "a" }] }), "a.mosaic");
    await viewer.showTable({ ...ITEM, type: evil });
    expect(viewer.table && "message" in viewer.table).toBe(true);
    const { body } = render(App, { props: { viewer } });
    expect(body).not.toContain("<script>");
    expect(body).not.toContain("<img");
  });

  it("every table lists exactly the type's nodes: their counts equal the totals `table` gives", async () => {
    const spec: MosaicSpec = {
      types: ["Empty"],
      nodes: [
        { type: "A", key: "1" },
        { type: "A", key: "2" },
        { type: "A", key: "3" },
        { type: "B", key: "1" },
      ],
    };
    const file = await open(spec);
    for (const t of file.nodeTypes) {
      const answer = await file.table({ type: t.name });
      if (!("data" in answer)) throw new Error("table failed");
      expect(answer.data.total, t.name).toBe(t.count);
    }
    file.close();
  });
});

describe("columns are the declared properties, filled by `table` (section 8.6)", () => {
  it("shows label, then the declared properties in the type's declaration order, and never an undeclared one", async () => {
    const view = await viewOf(
      {
        typeProps: { Item: '{"zeta":"text","alpha":"integer","mid":"boolean"}' },
        nodes: [{ type: "Item", key: "a", label: "A", props: canon({ zeta: "z", alpha: 1, mid: true, stray: "s" }) }],
      },
      ITEM,
    );
    expect(view.columns[0]).toBe("id");
    expect(view.columns).not.toContain("stray");
    expect(view.columns).toHaveLength(view.rows[0]!.length);
    expect(new Set(view.columns)).toEqual(new Set(["id", "label", "zeta", "alpha", "mid"]));
    expect(draw(view)).not.toContain("stray");
  });

  it("a type declaring more than 20 properties shows at most 20 columns after the id", async () => {
    const declared = Object.fromEntries(Array.from({ length: 25 }, (_, i) => [`p${String(i).padStart(2, "0")}`, "text"]));
    const view = await viewOf({ typeProps: { Item: canon(declared) }, nodes: [{ type: "Item", key: "a" }] }, ITEM);
    expect(view.columns.length).toBeLessThanOrEqual(21);
    expect(view.columns.length).toBeGreaterThan(2);
    expect(view.rows[0]).toHaveLength(view.columns.length);
  });

  it("a node with no value in a column has an empty cell, a stored 0, false and empty text are not empty", async () => {
    const view = await viewOf(
      {
        typeProps: { Item: '{"n":"integer","f":"boolean","t":"text","miss":"text"}' },
        nodes: [{ type: "Item", key: "a", props: canon({ n: 0, f: false, t: "" }) }],
      },
      ITEM,
    );
    const row = Object.fromEntries(view.columns.map((c, i) => [c, view.rows[0]![i]]));
    expect(row.n).toBe(0);
    expect(row.f).toBe(false);
    expect(row.t).toBe("");
    expect(row.miss ?? null).toBeNull();
    const body = draw(view);
    expect(body).toContain(">0<");
    expect(body).toContain(">false<");
    expect(cellText(row.miss)).toBe("");
    expect(cellText(0)).toBe("0");
  });

  it("long text is cut as section 8.2 says, so a table cell never holds a whole long text", async () => {
    const view = await viewOf(
      {
        typeProps: { Item: '{"t":"text"}' },
        nodes: [{ type: "Item", key: "a", label: "L".repeat(500), props: canon({ t: "P".repeat(2000) }) }],
      },
      ITEM,
    );
    const row = Object.fromEntries(view.columns.map((c, i) => [c, view.rows[0]![i]]));
    expect(row.label).toBe(cut("L".repeat(500), TEXT_LIMITS.label));
    expect((row.label as string).length).toBeLessThan(500);
    expect(row.t).toBe(cut("P".repeat(2000), TEXT_LIMITS.summary));
    expect((row.t as string).length).toBeLessThan(2000);
    expect(draw(view)).not.toContain("P".repeat(1000));
  });

  it("text from the file in a cell is escaped, never markup", async () => {
    const evil = `<script>alert(1)</script><b onclick="x">`;
    const view = await viewOf(
      { typeProps: { Item: '{"t":"text"}' }, nodes: [{ type: "Item", key: "a", label: evil, props: canon({ t: evil }) }] },
      ITEM,
    );
    const body = draw(view);
    expect(body).not.toContain("<script>");
    expect(body).not.toContain("<b onclick");
  });

  it("the table shows text ids only: the first cell of every row is a node's id, no integer row id", async () => {
    const view = await viewOf(numbered(3), ITEM);
    expect(ids(view)).toEqual(["Item:000", "Item:001", "Item:002"]);
    expect(view.columns).not.toContain("nid");
    expect(draw(view)).not.toMatch(/data-id="\d+"/);
  });
});

describe("paging goes through `table`, 20 rows a page (section 8.6)", () => {
  it("PAGE_ROWS is 20", () => {
    expect(PAGE_ROWS).toBe(20);
  });

  it("45 nodes make 3 pages of 20, 20 and 5 rows in id order, with the same total on each", async () => {
    const spec = numbered(45);
    const pages = await Promise.all([1, 2, 3].map((page) => viewOf(spec, { ...ITEM, page })));
    expect(pages.map((p) => p.rows.length)).toEqual([20, 20, 5]);
    expect(pages.map((p) => p.total)).toEqual([45, 45, 45]);
    expect(pages.map((p) => p.pages)).toEqual([3, 3, 3]);
    expect(pages.flatMap(ids)).toEqual(Array.from({ length: 45 }, (_, i) => `Item:${String(i).padStart(3, "0")}`));
  });

  it("exactly 20 nodes make one page, 21 nodes make two, none makes one", async () => {
    expect((await viewOf(numbered(20), ITEM)).pages).toBe(1);
    expect((await viewOf(numbered(21), ITEM)).pages).toBe(2);
    expect((await viewOf({ ...numbered(0), types: ["Item"] }, ITEM)).pages).toBe(1);
  });

  it("a page past the last is empty or an error shown, never rows of another page, and never throws", async () => {
    const file = await open(numbered(5));
    const view = await tableView(file, { ...ITEM, page: 9 });
    file.close();
    if ("rows" in view) expect(view.rows).toEqual([]);
    else expect(view.message.length).toBeGreaterThan(0);
  });

  it("an absurd page number in the address does not throw", async () => {
    const route = parseRoute("#t=Item&p=99999999999999999999999").table;
    expect(route).toBeTruthy();
    const file = await open(numbered(5));
    const view = await tableView(file, route!);
    file.close();
    expect("rows" in view || "message" in view).toBe(true);
  });

  it("the pager keeps the order and the filters, and says where the reader is", async () => {
    const route: TableRoute = {
      type: "Item",
      page: 2,
      order: { column: "n", desc: true },
      where: [{ column: "n", op: ">=", value: 0 }],
    };
    const view = await viewOf(numbered(45), route);
    const body = draw(view, route);
    expect(view.page).toBe(2);
    expect(body).toContain("Page 2 of 3 · 45 rows");
    const pageLinks = anchors(body, /rel="(prev|next)"/).map(parseRoute);
    expect(pageLinks).toHaveLength(2);
    for (const link of pageLinks) {
      expect(link.table!.order).toEqual({ column: "n", desc: true });
      expect(link.table!.where).toEqual(route.where);
    }
  });

  it("the first page offers no previous page and the last offers no next page", async () => {
    const spec = numbered(45);
    const first = draw(await viewOf(spec, ITEM));
    expect(first).not.toContain('rel="prev"');
    expect(first).toContain('rel="next"');
    const last = draw(await viewOf(spec, { ...ITEM, page: 3 }));
    expect(last).toContain('rel="prev"');
    expect(last).not.toContain('rel="next"');
    const only = draw(await viewOf(numbered(3), ITEM));
    expect(only).not.toContain('rel="prev"');
    expect(only).not.toContain('rel="next"');
  });
});

describe("sorting goes through `table` (section 8.6)", () => {
  const MIXED: MosaicSpec = {
    typeProps: { Item: '{"v":"text"}' },
    nodes: [
      { type: "Item", key: "a-none" },
      { type: "Item", key: "b-text", props: canon({ v: "b" }) },
      { type: "Item", key: "c-num", props: canon({ v: 5 }) },
      { type: "Item", key: "d-true", props: canon({ v: true }) },
      { type: "Item", key: "e-false", props: canon({ v: false }) },
      { type: "Item", key: "f-list", props: canon({ v: ["x"] }) },
      { type: "Item", key: "g-obj", props: canon({ v: { k: 1 } }) },
      { type: "Item", key: "h-num", props: canon({ v: -2 }) },
      { type: "Item", key: "i-text", props: canon({ v: "a" }) },
      { type: "Item", key: "j-null", props: canon({ v: null }) },
    ],
  };

  it("values of different kinds sort in groups, nodes with no value last in both directions", async () => {
    const asc = await viewOf(MIXED, { ...ITEM, order: { column: "v", desc: false } });
    expect(ids(asc)).toEqual([
      "Item:e-false",
      "Item:d-true",
      "Item:h-num",
      "Item:c-num",
      "Item:i-text",
      "Item:b-text",
      "Item:f-list",
      "Item:g-obj",
      "Item:a-none",
      "Item:j-null",
    ]);
    const desc = await viewOf(MIXED, { ...ITEM, order: { column: "v", desc: true } });
    expect(ids(desc)).toEqual([
      "Item:d-true",
      "Item:e-false",
      "Item:c-num",
      "Item:h-num",
      "Item:b-text",
      "Item:i-text",
      "Item:f-list",
      "Item:g-obj",
      "Item:a-none",
      "Item:j-null",
    ]);
  });

  it("descending keeps ties in id order, as ascending does", async () => {
    const spec: MosaicSpec = {
      typeProps: { Item: '{"g":"integer"}' },
      nodes: ["c", "a", "b"].map((k) => ({ type: "Item", key: k, props: canon({ g: 1 }) })),
    };
    expect(ids(await viewOf(spec, { ...ITEM, order: { column: "g", desc: false } }))).toEqual(["Item:a", "Item:b", "Item:c"]);
    expect(ids(await viewOf(spec, { ...ITEM, order: { column: "g", desc: true } }))).toEqual(["Item:a", "Item:b", "Item:c"]);
  });

  it("text sorts by UTF-8 bytes, not by locale or case", async () => {
    const spec: MosaicSpec = {
      typeProps: { Item: '{"s":"text"}' },
      nodes: ["é", "z", "Z", "a", "～", "\u{1F600}"].map((s, i) => ({ type: "Item", key: String(i), props: canon({ s }) })),
    };
    const view = await viewOf(spec, { ...ITEM, order: { column: "s", desc: false } });
    const col = view.columns.indexOf("s");
    expect(view.rows.map((r) => r[col])).toEqual(["Z", "a", "z", "é", "～", "\u{1F600}"]);
  });

  it("a sort by the node's label, key or summary needs no declared property", async () => {
    const spec: MosaicSpec = {
      nodes: [
        { type: "Item", key: "1", label: "B", summary: "x" },
        { type: "Item", key: "2", label: "A", summary: "z" },
      ],
    };
    expect(ids(await viewOf(spec, { ...ITEM, order: { column: "label", desc: false } }))).toEqual(["Item:2", "Item:1"]);
    expect(ids(await viewOf(spec, { ...ITEM, order: { column: "summary", desc: true } }))).toEqual(["Item:2", "Item:1"]);
    expect(ids(await viewOf(spec, { ...ITEM, order: { column: "key", desc: true } }))).toEqual(["Item:2", "Item:1"]);
  });

  it("sorting by a column the type does not have is an error naming it, never rows in another order", async () => {
    const file = await open(numbered(3));
    const view = await tableView(file, { ...ITEM, order: { column: "nope", desc: false } });
    file.close();
    expect("rows" in view).toBe(false);
    expect("message" in view && view.message).toContain("nope");
  });

  it("a header's sort link keeps the filters; a sorted column's link flips its direction", async () => {
    const route: TableRoute = {
      type: "Item",
      page: 1,
      order: { column: "n", desc: true },
      where: [{ column: "n", op: "<", value: 10 }],
    };
    const view = await viewOf(numbered(45), route);
    const body = draw(view, route);
    expect(body).toContain('aria-sort="descending"');
    const sorts = anchors(body, /data-column="n"/).map(parseRoute);
    expect(sorts).toHaveLength(1);
    for (const s of sorts) {
      expect(s.table!.where).toEqual(route.where);
      expect(s.table!.order).toEqual({ column: "n", desc: false });
      expect(s.table!.page).toBeGreaterThanOrEqual(1);
    }
  });

  it("an unsorted table marks no property column as sorted (the id order is the default one)", async () => {
    const body = draw(await viewOf(numbered(3), ITEM));
    for (const tag of body.match(/<th\s[^>]*>[^]*?<\/th>/g) ?? []) {
      if (/data-column=/.test(tag)) expect(tag).not.toMatch(/aria-sort="(ascending|descending)"/);
    }
  });
});

describe("filtering goes through `table`, with the where operators (section 8.6)", () => {
  const SPEC: MosaicSpec = {
    typeProps: { Item: '{"code":"text","n":"integer","f":"boolean"}' },
    nodes: [
      { type: "Item", key: "1", label: "One", props: canon({ code: "Alpha", n: 1, f: true }) },
      { type: "Item", key: "2", label: "Two", props: canon({ code: "beta", n: 2, f: false }) },
      { type: "Item", key: "3", label: "Three", props: canon({ code: "ALPHABET", n: 3 }) },
      { type: "Item", key: "4", label: "Four", props: canon({ n: "3" }) },
      { type: "Item", key: "5", label: "Five" },
    ],
  };
  const where = async (column: string, op: TableRoute["where"][number]["op"], value: string | number | boolean) =>
    ids(await viewOf(SPEC, { ...ITEM, where: [{ column, op, value }] })).map((id) => String(id).slice(5));

  it("each operator is passed through unchanged and holds as section 8.6 words it", async () => {
    expect(await where("n", "=", 2)).toEqual(["2"]);
    expect(await where("n", "!=", 2)).toEqual(["1", "3", "4", "5"]);
    expect(await where("n", "<", 3)).toEqual(["1", "2"]);
    expect(await where("n", "<=", 3)).toEqual(["1", "2", "3"]);
    expect(await where("n", ">", 1)).toEqual(["2", "3"]);
    expect(await where("n", ">=", 2)).toEqual(["2", "3"]);
    expect(await where("code", "contains", "alpha")).toEqual(["1", "3"]);
    expect(await where("f", "=", true)).toEqual(["1"]);
    expect(await where("f", "!=", true)).toEqual(["2", "3", "4", "5"]);
    expect(OPERATORS).toHaveLength(7);
  });

  it("text 3 and number 3 are different values: the kind of the filter decides", async () => {
    expect(await where("n", "=", "3")).toEqual(["4"]);
    expect(await where("n", "=", 3)).toEqual(["3"]);
    expect(await where("f", "=", "true")).toEqual([]);
  });

  it("several filters must all hold", async () => {
    const both = await viewOf(SPEC, {
      ...ITEM,
      where: [
        { column: "code", op: "contains", value: "alpha" },
        { column: "n", op: ">", value: 1 },
      ],
    });
    expect(ids(both)).toEqual(["Item:3"]);
    expect(both.total).toBe(1);
  });

  it("the total counts every node the filters keep, not the page's rows", async () => {
    const view = await viewOf(numbered(45), { ...ITEM, where: [{ column: "n", op: ">=", value: 10 }] });
    expect(view.total).toBe(35);
    expect(view.rows).toHaveLength(20);
    expect(view.pages).toBe(2);
  });

  it("a filter that keeps nothing shows an empty table with total 0, not an error", async () => {
    const view = await viewOf(SPEC, { ...ITEM, where: [{ column: "code", op: "=", value: "nothing" }] });
    expect(view.rows).toEqual([]);
    expect(view.total).toBe(0);
    expect(view.pages).toBe(1);
    expect(draw(view)).toContain("0 rows");
  });

  it("filtering on a column the type does not have is an error naming it, never an empty table", async () => {
    const file = await open(SPEC);
    const view = await tableView(file, { ...ITEM, where: [{ column: "colour", op: "=", value: "red" }] });
    file.close();
    expect("rows" in view).toBe(false);
    expect("message" in view && view.message).toContain("colour");
  });

  it("21 filters are refused by `table` and the refusal is shown, not thrown", async () => {
    const file = await open(SPEC);
    const where = Array.from({ length: 21 }, () => ({ column: "n", op: ">=" as const, value: 0 }));
    const view = await tableView(file, { ...ITEM, where });
    file.close();
    expect("rows" in view).toBe(false);
    expect("message" in view && view.message.length).toBeGreaterThan(0);
  });

  it("a filter on a column that `columns` leaves out still works: the table's own columns do not limit it", async () => {
    const view = await viewOf(SPEC, { ...ITEM, where: [{ column: "key", op: "=", value: "2" }] });
    expect(ids(view)).toEqual(["Item:2"]);
  });

  it("the filter form's removal links keep the other filters and the order", async () => {
    const route: TableRoute = {
      type: "Item",
      page: 1,
      order: { column: "n", desc: false },
      where: [
        { column: "code", op: "contains", value: "a" },
        { column: "n", op: ">", value: 0 },
      ],
    };
    const view = await viewOf(SPEC, route);
    const body = draw(view, route);
    const removals = attributes(body, "href")
      .map(parseRoute)
      .filter((r) => r.table && r.table.where.length === 1 && r.node === null);
    expect(removals.map((r) => r.table!.where[0]).sort((a, b) => a!.column.localeCompare(b!.column))).toEqual([
      { column: "code", op: "contains", value: "a" },
      { column: "n", op: ">", value: 0 },
    ]);
    for (const r of removals) expect(r.table!.order).toEqual({ column: "n", desc: false });
  });
});

describe("a row opens its node page (design.md Viewer)", () => {
  const ODD = ["a/b c", "x&y=z", "h#h", "q?r", "p%20q", "é+ü", "日本", "a:b"];
  const SPEC: MosaicSpec = { nodes: ODD.map((key) => ({ type: "Item", key, label: `L ${key}` })) };

  it("every row's link carries exactly that row's id, whatever characters the id has", async () => {
    const view = await viewOf(SPEC, ITEM);
    const body = draw(view);
    const rowIds = attributes(body, "data-id").map((a) => a.replaceAll("&quot;", '"'));
    expect(rowIds.sort()).toEqual(ids(view).map(String).sort());
    const linked = attributes(body, "href").map(parseRoute).filter((r) => r.node !== null).map((r) => r.node);
    expect(new Set(linked)).toEqual(new Set(ODD.map((k) => `Item:${k}`)));
  });

  it("the node a row links to opens through `get`: its page shows that node", async () => {
    const file = await open(SPEC);
    const view = await tableView(file, ITEM);
    if (!("rows" in view)) throw new Error("no table");
    for (const row of view.rows) {
      const node = parseRoute(nodeHref(String(row[0]))).node;
      expect(node).toBe(row[0]);
      const page = await nodePage(file, node!);
      expect("node" in page, String(row[0])).toBe(true);
    }
    file.close();
  });

  it("a node link leaves the table's view: the address of a row holds the node and no stale table state", async () => {
    const link = parseRoute(nodeHref("Item:a/b c"));
    expect(link.node).toBe("Item:a/b c");
    expect(link.table ?? null).toBeNull();
  });
});

describe("table addresses (reload and share)", () => {
  it("filter values keep their kind through the address: text 2020, number 2020, true and text true", () => {
    const where: TableRoute["where"] = [
      { column: "a", op: "=", value: "2020" },
      { column: "a", op: "=", value: 2020 },
      { column: "a", op: "=", value: true },
      { column: "a", op: "=", value: "true" },
      { column: "a", op: "=", value: "" },
      { column: "a", op: ">", value: 0 },
      { column: "a", op: "<", value: -0.5 },
      { column: "a", op: "<=", value: 1e21 },
      { column: "a", op: "contains", value: "null" },
      { column: "a", op: "contains", value: "日本 \u{1F600} é" },
    ];
    const table: TableRoute = { type: "Item", page: 1, order: null, where };
    expect(parseRoute(routeHash({ query: "", node: null, table })).table).toEqual(table);
  });

  it("column and type names with reserved characters survive the address", () => {
    const table: TableRoute = {
      type: "T&p=1#x%",
      page: 4,
      order: { column: "col&w=[]", desc: true },
      where: [{ column: "c=d", op: "=", value: "v&t=Other" }],
    };
    const back = parseRoute(routeHash({ query: "", node: null, table })).table;
    expect(back).toEqual(table);
  });

  it("the table, the search query and the open node do not overwrite one another", () => {
    const route = { query: "heater a", node: "Item:a", table: { ...ITEM, page: 2 } };
    const back = parseRoute(routeHash(route));
    expect(back.query).toBe("heater a");
    expect(back.node).toBe("Item:a");
    expect(back.table).toEqual(route.table);
  });

  it("the same route always gives the same address", () => {
    const table: TableRoute = {
      type: "Item",
      page: 2,
      order: { column: "n", desc: false },
      where: [{ column: "n", op: ">", value: 1 }],
    };
    const route = { query: "", node: null, table };
    expect(routeHash(route)).toBe(routeHash({ ...route }));
    expect(routeHash(parseRoute(routeHash(route)))).toBe(routeHash(route));
  });

  it("a route without a table gives an address with no table part", () => {
    expect(routeHash({ query: "x", node: null })).not.toMatch(/[#&]t=/);
    expect(routeHash({ query: "x", node: null, table: null })).not.toMatch(/[#&]t=/);
  });

  it("a malformed address never gives a table with page below 1, a fractional page or an unknown operator", () => {
    for (const p of ["0", "-1", "2.5", "abc", "", "NaN", "Infinity", " "]) {
      const table = parseRoute(`#t=Item&p=${encodeURIComponent(p)}`).table;
      expect(table?.page, `p=${JSON.stringify(p)}`).toBe(1);
    }
    for (const w of ["[]", "{}", "null", "1", '"x"', "[null]", '[{"column":"a"}]', '[{"column":"a","op":"=","value":null}]', '[{"column":"a","op":"=","value":{"x":1}}]', '[{"column":"a","op":"=","value":[1]}]']) {
      const table = parseRoute(`#t=Item&w=${encodeURIComponent(w)}`).table;
      expect(table?.where, `w=${w}`).toEqual([]);
    }
    for (const o of [""]) {
      expect(parseRoute(`#t=Item&o=${encodeURIComponent(o)}`).table?.order ?? null, `o=${o}`).toBeNull();
    }
  });

  it("an address never makes the viewer throw: any table asked of the open mosaic is a view or a shown error", async () => {
    const file = await open(numbered(3));
    for (const hash of ["#t=Item&p=0", "#t=Item&w=%00", "#t=%00", "#t=Item&o=%5B%5D", "#t=Item&w=%5B%7B%7D%5D", "#t=__proto__", "#t=constructor"]) {
      const route = parseRoute(hash).table;
      if (!route) continue;
      const view = await tableView(file, route);
      expect("rows" in view || "message" in view, hash).toBe(true);
    }
    file.close();
  });

  it("the table's arguments for a route are the same call twice, and never carry a field the route lacks", () => {
    const route: TableRoute = {
      type: "Item",
      page: 3,
      order: { column: "n", desc: true },
      where: [{ column: "n", op: "!=", value: 2 }],
    };
    expect(tableArgs(route)).toEqual(tableArgs(route));
    expect(Object.keys(tableArgs(ITEM)).sort()).toEqual(["page", "type"]);
    expect(tableArgs(route)).toEqual({
      type: "Item",
      page: 3,
      order: { column: "n", direction: "desc" },
      where: [{ column: "n", op: "!=", value: 2 }],
    });
  });
});

describe("filter values and cells, edge inputs", () => {
  it("a number filter refuses what JSON cannot carry", () => {
    for (const text of ["Infinity", "-Infinity", "NaN", "1,5", "1 2", "--1", "0x", "  "]) {
      expect(filterValue(text, "number"), text).toBeNull();
    }
    expect(filterValue("1e3", "number")).toBe(1000);
    expect(filterValue("0", "number")).toBe(0);
    expect(filterValue("-0.25", "number")).toBe(-0.25);
  });

  it("a text filter is the text as typed, spaces and case kept", () => {
    expect(filterValue(" Ab ", "text")).toBe(" Ab ");
    expect(filterValue("null", "text")).toBe("null");
    expect(filterValue("2020", "text")).toBe("2020");
  });

  it("a boolean filter is only true or false", () => {
    for (const text of ["", "1", "0", "null", "on", "no"]) expect(filterValue(text, "boolean"), text).toBeNull();
  });

  it("cell text of a list or an object is JSON or labels and never `[object Object]`", () => {
    expect(cellText({ a: { b: [1, "x"] } })).toBe('{"a":{"b":[1,"x"]}}');
    expect(cellText([])).toBe("");
    expect(cellText(["日本", "é"])).toBe("日本, é");
    expect(cellText(undefined)).toBe("");
    expect(cellText("")).toBe("");
    expect(cellText("a\nb")).toContain("a");
    for (const v of [{ x: 1 }, [{ x: 1 }], [[1]], true, 1.5, -3]) expect(cellText(v)).not.toContain("[object");
  });
});

describe("the Viewer and its tables", () => {
  const A: MosaicSpec = { nodes: [{ type: "Item", key: "a" }] };
  const B: MosaicSpec = { nodes: [{ type: "Other", key: "b" }] };

  it("asking for a table before a mosaic is open does not throw and shows no table", async () => {
    const viewer = new Viewer();
    await viewer.showTable(ITEM);
    expect(viewer.table ?? null).toBeNull();
  });

  it("opening another mosaic drops the table of the previous one", async () => {
    const viewer = new Viewer();
    await viewer.open(buildMosaic(A), "a.mosaic");
    await viewer.showTable(ITEM);
    expect(viewer.table && "rows" in viewer.table).toBe(true);
    await viewer.open(buildMosaic(B), "b.mosaic");
    expect(viewer.table ?? null).toBeNull();
    expect(viewer.file?.nodeTypes.map((t) => t.name)).toEqual(["Other"]);
  });

  it("the table of a type the open mosaic lacks is a shown error naming the type, then a real table replaces it", async () => {
    const viewer = new Viewer();
    await viewer.open(buildMosaic(A), "a.mosaic");
    await viewer.showTable({ ...ITEM, type: "Ghost" });
    expect(viewer.table && "message" in viewer.table && viewer.table.message).toContain("Ghost");
    await viewer.showTable(ITEM);
    expect(viewer.table && "rows" in viewer.table).toBe(true);
  });

  it("many table requests in a row end on the last one asked", async () => {
    const viewer = new Viewer();
    await viewer.open(buildMosaic(numbered(45)), "n.mosaic");
    const asked = [1, 2, 3, 2, 1, 3].map((page) => viewer.showTable({ ...ITEM, page }));
    await Promise.all(asked);
    expect(viewer.table && "page" in viewer.table && viewer.table.page).toBe(3);
  });

  it("the same table drawn twice is the same page, byte for byte", async () => {
    const view = await viewOf(numbered(25), { ...ITEM, order: { column: "n", desc: true }, where: [{ column: "n", op: ">", value: 2 }] });
    expect(draw(view)).toBe(draw(view));
    const again = await viewOf(numbered(25), view.route);
    expect(again.rows).toEqual(view.rows);
  });

  it("the table view's route is the route asked", async () => {
    const route: TableRoute = { ...ITEM, page: 2, order: { column: "n", desc: true } };
    expect((await viewOf(numbered(45), route)).route).toEqual(route);
  });
});
