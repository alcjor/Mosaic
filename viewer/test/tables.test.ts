// M2.10: one table per node type the mosaic declares, its columns those `table` gives, filled by
// `table`; sorting, filtering by the `where` operators and paging go through `table`; a row
// opens its node page (docs/design.md, First milestone: Viewer; sections 8.1 and 8.6).
import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import App from "../src/App.svelte";
import TableViewComponent from "../src/components/TableView.svelte";
import TypeList from "../src/components/TypeList.svelte";
import { openMosaic } from "../src/lib/mosaic.js";
import { OPERATORS, parseRoute, routeHash, type TableRoute } from "../src/lib/route.js";
import { cellText, filterValue, tableArgs, tableView, type TableView } from "../src/lib/tables.js";
import { Viewer } from "../src/lib/viewer.svelte.js";
import { reading } from "./fixtures.js";

const ITEM: TableRoute = { type: "Item", page: 1, order: null, where: [] };
const tableHref = (table: TableRoute) => routeHash({ query: "", node: null, table });
const nodeHref = (id: string) => routeHash({ query: "", node: id });

function attributes(html: string, attribute: string): string[] {
  return [...html.matchAll(new RegExp(`${attribute}="([^"]*)"`, "g"))].map((m) => m[1]!.replaceAll("&amp;", "&"));
}

describe("table routes", () => {
  it("a table view's type, page, order and filters survive the address", () => {
    const routes: TableRoute[] = [
      ITEM,
      { type: "Item", page: 3, order: { column: "size", desc: true }, where: [] },
      {
        type: "Item",
        page: 2,
        order: { column: "label", desc: false },
        where: [
          { column: "code", op: "contains", value: "a&b=#" },
          { column: "size", op: ">=", value: 1 },
          { column: "flag", op: "!=", value: false },
        ],
      },
    ];
    for (const table of routes) {
      expect(parseRoute(routeHash({ query: "q", node: null, table })).table).toEqual(table);
    }
    expect(parseRoute("#q=x").table ?? null).toBeNull();
    expect(parseRoute("#t=").table ?? null).toBeNull();
  });

  it("a malformed page or filter in the address is ignored, never an error", () => {
    expect(parseRoute("#t=Item&p=0").table?.page).toBe(1);
    expect(parseRoute("#t=Item&p=-2").table?.page).toBe(1);
    expect(parseRoute("#t=Item&p=1e3").table?.page).toBe(1);
    expect(parseRoute("#t=Item&w=%7Bnot").table?.where).toEqual([]);
    expect(parseRoute(`#t=Item&w=${encodeURIComponent('[{"column":"a","op":"LIKE","value":"x"},{"column":"a","op":"=","value":1}]')}`).table?.where).toEqual([
      { column: "a", op: "=", value: 1 },
    ]);
  });
});

describe("tables through table", () => {
  it("the open file lists one table per declared node type, each opening its table", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const { body } = render(TypeList, { props: { types: file.nodeTypes, hrefFor: (t: string) => tableHref({ ...ITEM, type: t }) } });
    expect(attributes(body, "data-type")).toEqual(["Group", "Item"]);
    expect(attributes(body, "href").map((h) => parseRoute(h).table?.type)).toEqual(["Group", "Item"]);
    expect(body).toContain(">2<");
    file.close();
  });

  it("a table view is one table call with its page, order and filters, and shows what it returns", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const call = vi.spyOn(file, "table");
    const route: TableRoute = { type: "Item", page: 1, order: { column: "size", desc: true }, where: [{ column: "code", op: "contains", value: "A" }] };
    const view = (await tableView(file, route)) as TableView;
    expect(call).toHaveBeenCalledTimes(1);
    expect(call).toHaveBeenCalledWith({
      type: "Item",
      page: 1,
      order: { column: "size", direction: "desc" },
      where: [{ column: "code", op: "contains", value: "A" }],
    });
    const answer = await file.table(tableArgs(route));
    if (!("data" in answer)) throw new Error("table failed");
    expect(view.columns).toEqual(answer.data.columns);
    expect(view.rows).toEqual(answer.data.rows);
    expect(view.total).toBe(answer.data.total);
    expect(view.pages).toBe(1);
    file.close();
  });

  it("without order or filters the call names the type and page only; the columns are table's defaults", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    expect(tableArgs(ITEM)).toEqual({ type: "Item", page: 1 });
    const view = (await tableView(file, ITEM)) as TableView;
    expect(view.columns).toEqual(["id", "label", "code", "size"]);
    expect(view.rows.map((r) => r[0])).toEqual(["Item:a", "Item:b"]);
    file.close();
  });

  it("a table call's error is shown, never an empty table", async () => {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const view = await tableView(file, { ...ITEM, order: { column: "colour", desc: false } });
    expect("message" in view && view.message).toMatch(/colour/);
    const unknown = await tableView(file, { ...ITEM, type: "Itme" });
    expect("message" in unknown && unknown.message).toMatch(/Item/);
    file.close();
  });

  it("the Viewer keeps the latest table page", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    const first = viewer.showTable(ITEM);
    const second = viewer.showTable({ ...ITEM, type: "Group" });
    await Promise.all([second, first]);
    expect(viewer.table && "route" in viewer.table && viewer.table.route.type).toBe("Group");
    await viewer.showTable(null);
    expect(viewer.table).toBeNull();
  });
});

describe("TableView", () => {
  async function rendered(route: TableRoute) {
    const file = await openMosaic(reading("mosaic.mosaic"), "mosaic.mosaic");
    const view = (await tableView(file, route)) as TableView;
    file.close();
    const { body } = render(TableViewComponent, { props: { view, route, hrefFor: tableHref, nodeHref, onfilter: () => {} } });
    return { view, body };
  }

  it("shows one header per column and one row per node, each row's id opening its node page", async () => {
    const { view, body } = await rendered(ITEM);
    for (const column of view.columns) expect(body).toContain(`>${column}`);
    const ids = attributes(body, "data-id");
    expect(ids).toEqual(["Item:a", "Item:b"]);
    const nodes = attributes(body, "href").map(parseRoute).filter((r) => r.node !== null).map((r) => r.node);
    expect(nodes).toEqual(["Item:a", "Item:b"]);
    expect(body).toContain("Item A");
    expect(body).toContain(">a<");
  });

  it("each column header sorts through table: ascending, then descending", async () => {
    const { body } = await rendered(ITEM);
    const sorts = attributes(body, "data-column");
    expect(sorts).toEqual(["label", "code", "size"]);
    const hrefs = attributes(body, "href").map(parseRoute).filter((r) => r.table?.order).map((r) => r.table!.order);
    expect(hrefs).toEqual([
      { column: "label", desc: false },
      { column: "code", desc: false },
      { column: "size", desc: false },
    ]);
    const asc = await rendered({ ...ITEM, order: { column: "size", desc: false } });
    expect(asc.body).toContain('aria-sort="ascending"');
    const next = attributes(asc.body, "href").map(parseRoute).find((r) => r.table?.order?.column === "size");
    expect(next?.table?.order).toEqual({ column: "size", desc: true });
  });

  it("offers every where operator, and each filter can be removed", async () => {
    const route: TableRoute = { ...ITEM, where: [{ column: "code", op: "contains", value: "a" }] };
    const { body } = await rendered(route);
    const options = [...body.matchAll(/<option value="([^"]*)"/g)].map((m) => m[1]!.replaceAll("&lt;", "<").replaceAll("&gt;", ">"));
    for (const op of OPERATORS) expect(options).toContain(op);
    const removal = attributes(body, "href").map(parseRoute).find((r) => r.table && r.table.where.length === 0);
    expect(removal?.table?.type).toBe("Item");
  });

  it("pages through table, 20 rows a page, with the total", () => {
    const view: TableView = {
      route: { ...ITEM, page: 2 },
      columns: ["id", "label"],
      rows: Array.from({ length: 20 }, (_, i) => [`Item:${i}`, `Item ${i}`]),
      page: 2,
      total: 45,
      pages: 3,
    };
    const { body } = render(TableViewComponent, { props: { view, route: view.route, hrefFor: tableHref, nodeHref, onfilter: () => {} } });
    expect(body).toContain("Page 2 of 3 · 45 rows");
    const pages = attributes(body, "href").map(parseRoute).filter((r) => r.table && r.node === null && r.table.where.length === 0 && r.table.order === null && r.table.page !== 1).map((r) => r.table!.page);
    expect(pages).toContain(3);
    expect(body).toContain('rel="prev"');
    expect(body).toContain('rel="next"');
  });
});

describe("filter values and cells", () => {
  it("a filter's text is read as the kind the reader picks", () => {
    expect(filterValue("2020", "text")).toBe("2020");
    expect(filterValue("2020", "number")).toBe(2020);
    expect(filterValue(" -1.5 ", "number")).toBe(-1.5);
    expect(filterValue("x", "number")).toBeNull();
    expect(filterValue("", "number")).toBeNull();
    expect(filterValue("true", "boolean")).toBe(true);
    expect(filterValue("false", "boolean")).toBe(false);
    expect(filterValue("yes", "boolean")).toBeNull();
  });

  it("cells show text, lists of labels, numbers and JSON; no value is empty", () => {
    expect(cellText("PG")).toBe("PG");
    expect(cellText(["Ann", null, "Bo"])).toBe("Ann, , Bo");
    expect(cellText(3)).toBe("3");
    expect(cellText(false)).toBe("false");
    expect(cellText({ a: 1 })).toBe('{"a":1}');
    expect(cellText([1, 2])).toBe("[1,2]");
    expect(cellText(null)).toBe("");
  });
});

describe("App", () => {
  it("lists the tables beside the results and shows the table view a route asks for", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    await viewer.showTable(ITEM);
    const { body } = render(App, { props: { viewer } });
    expect(body).toContain(">Tables<");
    expect(body).toContain('aria-label="Table Item"');
    expect(body).toContain('data-id="Item:a"');
  });
});
