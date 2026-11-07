// More edge cases for M2.10 (viewer: tables rebuilt from node types), written from the spec's
// words and not the implementation, and not repeated from tables.edges.test.ts: docs/design.md
// (First milestone: Viewer), sections 8.1 and 8.6 (`table`: columns, kinds, `where`, `order`,
// `page`), 8.2 (cut text), 10 (untrusted data).
import { render } from "svelte/server";
import { describe, expect, it } from "vitest";
import { TEXT_LIMITS, cut } from "@mosaic/kit";
import { buildMosaic, type MosaicSpec } from "../../kit/test/build-mosaic.js";
import TableViewComponent from "../src/components/TableView.svelte";
import TypeList from "../src/components/TypeList.svelte";
import { openMosaic } from "../src/lib/mosaic.js";
import { parseRoute, routeHash, type TableRoute } from "../src/lib/route.js";
import { tableView, type TableView } from "../src/lib/tables.js";
import { Viewer } from "../src/lib/viewer.svelte.js";

const ITEM: TableRoute = { type: "Item", page: 1, order: null, where: [] };
const tableHref = (table: TableRoute) => routeHash({ query: "", node: null, table });
const nodeHref = (id: string) => routeHash({ query: "", node: id });
const canon = (value: unknown): string => JSON.stringify(value);

async function viewOf(spec: MosaicSpec, route: TableRoute): Promise<TableView> {
  const file = await openMosaic(buildMosaic(spec), "built.mosaic");
  const view = await tableView(file, route);
  file.close();
  if (!("rows" in view)) throw new Error(`not a table view: ${JSON.stringify(view)}`);
  return view;
}

function draw(view: TableView, route: TableRoute = view.route): string {
  return render(TableViewComponent, { props: { view, route, hrefFor: tableHref, nodeHref, onfilter: () => {} } }).body;
}

const ids = (view: TableView): unknown[] => view.rows.map((r) => r[0]);
const cells = (view: TableView, column: string): unknown[] => {
  const at = view.columns.indexOf(column);
  expect(at, `column ${column} in ${view.columns.join(",")}`).toBeGreaterThan(-1);
  return view.rows.map((r) => r[at]);
};
const numbered = (n: number): MosaicSpec => ({
  typeProps: { Item: '{"n":"integer"}' },
  nodes: Array.from({ length: n }, (_, i) => ({ type: "Item", key: String(i).padStart(4, "0"), props: canon({ n: i }) })),
});

describe("the columns of a table (section 8.6, Rows)", () => {
  it("shows label, then the declared properties in stored order, 20 columns in all after the id", async () => {
    // Section 8.6: "label, then the declared properties in the order the type declares them,
    // 20 columns in all" (id comes first and is extra: `data.columns` is `id`, then the columns).
    const declared = Object.fromEntries(Array.from({ length: 25 }, (_, i) => [`p${String(i).padStart(2, "0")}`, "text"]));
    const view = await viewOf({ typeProps: { Item: canon(declared) }, nodes: [{ type: "Item", key: "a" }] }, ITEM);
    expect(view.columns).toEqual(["id", "label", ...Array.from({ length: 19 }, (_, i) => `p${String(i).padStart(2, "0")}`)]);
    expect(view.rows[0]).toHaveLength(21);
  });

  it("a type declaring exactly 19 properties shows all of them", async () => {
    const declared = Object.fromEntries(Array.from({ length: 19 }, (_, i) => [`p${String(i).padStart(2, "0")}`, "text"]));
    const view = await viewOf({ typeProps: { Item: canon(declared) }, nodes: [{ type: "Item", key: "a" }] }, ITEM);
    expect(view.columns).toHaveLength(21);
    expect(view.columns.at(-1)).toBe("p18");
  });

  it("a type declaring no property has only id and label", async () => {
    const view = await viewOf({ typeProps: { Item: "{}" }, nodes: [{ type: "Item", key: "a", label: "A" }] }, ITEM);
    expect(view.columns).toEqual(["id", "label"]);
    expect(view.rows).toEqual([["Item:a", "A"]]);
  });

  it("property names that are also names of JavaScript objects are plain columns", async () => {
    const names = ["__proto__", "constructor", "hasOwnProperty", "toString", "length"];
    const declared = Object.fromEntries(names.map((n) => [n, "text"]));
    const props = `{${names.map((n, i) => `${canon(n)}:${canon(`v${i}`)}`).join(",")}}`;
    const view = await viewOf({ typeProps: { Item: `{${names.map((n) => `${canon(n)}:"text"`).join(",")}}` }, nodes: [{ type: "Item", key: "a", props }] }, ITEM);
    expect(Object.keys(declared)).toHaveLength(5);
    expect([...view.columns].sort()).toEqual(["id", "label", ...names].sort());
    for (const [i, n] of names.entries()) expect(cells(view, n), n).toEqual([`v${i}`]);
    // And a filter and an order on them go through `table` like any other column.
    const filtered = await viewOf(
      { typeProps: { Item: `{${names.map((n) => `${canon(n)}:"text"`).join(",")}}` }, nodes: [{ type: "Item", key: "a", props }, { type: "Item", key: "b", props: "{}" }] },
      { ...ITEM, where: [{ column: "constructor", op: "=", value: "v1" }], order: { column: "__proto__", desc: false } },
    );
    expect(ids(filtered)).toEqual(["Item:a"]);
  });

  it("column names with markup are escaped in headers, attributes and links", async () => {
    const evil = `"><img src=x onerror=alert(1)>`;
    const view = await viewOf({ typeProps: { Item: canon({ [evil]: "text" }) }, nodes: [{ type: "Item", key: "a", props: canon({ [evil]: evil }) }] }, ITEM);
    const body = draw(view, { ...ITEM, order: { column: evil, desc: false } });
    expect(body).not.toContain("<img");
    expect(body).not.toMatch(/<[^>]*\sonerror=/);
    // The sort links still carry the exact name.
    const names = [...body.matchAll(/<a\s[^>]*href="([^"]*)"/g)].map((m) => parseRoute(m[1]!.replaceAll("&amp;", "&")).table?.order?.column);
    expect(names).toContain(evil);
  });

  it("a node id with quotes and markup is one link to exactly that node, never markup", async () => {
    const key = `x"><script>alert(1)</script>'`;
    const view = await viewOf({ nodes: [{ type: "Item", key, label: "L" }] }, ITEM);
    const body = draw(view);
    expect(body).not.toContain("<script>");
    const links = [...body.matchAll(/<a\s[^>]*href="([^"]*)"/g)].map((m) => parseRoute(m[1]!.replaceAll("&amp;", "&")).node);
    expect(links).toContain(`Item:${key}`);
  });

  it("a json property holding a list or an object is drawn as its JSON text, escaped", async () => {
    const view = await viewOf(
      {
        typeProps: { Item: '{"j":"json"}' },
        nodes: [
          { type: "Item", key: "1", props: canon({ j: { k: "<b>" } }) },
          { type: "Item", key: "2", props: canon({ j: ["x", "y"] }) },
        ],
      },
      ITEM,
    );
    expect(cells(view, "j")).toEqual([{ k: "<b>" }, ["x", "y"]]);
    const body = draw(view);
    expect(body).not.toContain("[object");
    expect(body).not.toContain("<b>");
  });

  it("a stored JSON null in a property is an empty cell, like a node with no value", async () => {
    const view = await viewOf(
      { typeProps: { Item: '{"v":"text"}' }, nodes: [{ type: "Item", key: "a", props: canon({ v: null }) }, { type: "Item", key: "b" }] },
      ITEM,
    );
    expect(cells(view, "v")).toEqual([null, null]);
  });

  it("a label of many astral characters is cut at 120 characters without breaking one in half", async () => {
    const label = "\u{1F600}".repeat(300);
    const view = await viewOf({ nodes: [{ type: "Item", key: "a", label }] }, ITEM);
    const cell = cells(view, "label")[0] as string;
    expect(cell).toBe(cut(label, TEXT_LIMITS.label));
    expect(cell.isWellFormed()).toBe(true);
    expect(draw(view).includes("\u{1F600}".repeat(200))).toBe(false);
  });

  it("a summary or key filter sees the stored text, not the cut one", async () => {
    // Section 8.6: text is cut in cells; `where` compares the values (section 8.2 cuts what is returned).
    const long = "q".repeat(300) + "TAIL";
    const spec: MosaicSpec = { nodes: [{ type: "Item", key: "a", label: long }, { type: "Item", key: "b", label: "short" }] };
    const view = await viewOf(spec, { ...ITEM, where: [{ column: "label", op: "contains", value: "tail" }] });
    expect(ids(view)).toEqual(["Item:a"]);
  });
});

describe("the type list (design.md Viewer)", () => {
  it("shows each table's count next to its name, 0 for a declared type without nodes", async () => {
    const file = await openMosaic(
      buildMosaic({ types: ["Empty"], nodes: [{ type: "A", key: "1" }, { type: "A", key: "2" }, { type: "A", key: "3" }] }),
      "t.mosaic",
    );
    const { body } = render(TypeList, { props: { types: file.nodeTypes, hrefFor: (t: string) => tableHref({ ...ITEM, type: t }) } });
    file.close();
    const row = (name: string) => new RegExp(`data-type="${name}"[^]*?</a>`).exec(body)![0];
    expect(row("A")).toMatch(/>3</);
    expect(row("Empty")).toMatch(/>0</);
  });
});

describe("filtering and ordering, through `table` (section 8.6)", () => {
  it("`contains` ignores case across the Unicode default lowercase mapping and finds list items", async () => {
    const spec: MosaicSpec = {
      typeProps: { Item: '{"s":"text","l":"json"}' },
      nodes: [
        { type: "Item", key: "1", props: canon({ s: "Éclair", l: ["Red", "Green"] }) },
        { type: "Item", key: "2", props: canon({ s: "eclair", l: ["Blue"] }) },
        { type: "Item", key: "3", props: canon({ s: "ΣΑΣ", l: [1, 2] }) },
        { type: "Item", key: "4" },
      ],
    };
    const run = async (column: string, value: string) => ids(await viewOf(spec, { ...ITEM, where: [{ column, op: "contains", value }] }));
    expect(await run("s", "éCL")).toEqual(["Item:1"]);
    expect(await run("s", "ECL")).toEqual(["Item:2"]);
    // A text always contains itself, whatever the lowercase mapping does to it (final sigma included).
    expect(await run("s", "ΣΑΣ")).toEqual(["Item:3"]);
    expect(await run("l", "GREEN")).toEqual(["Item:1"]);
    expect(await run("l", "1")).toEqual([]);
  });

  it("`contains` with an empty text holds on every node with text, and on none without", async () => {
    // Section 8.6: "holds on text that contains the given text"; every text contains "".
    const spec: MosaicSpec = {
      typeProps: { Item: '{"s":"text"}' },
      nodes: [{ type: "Item", key: "1", props: canon({ s: "x" }) }, { type: "Item", key: "2", props: canon({ s: "" }) }, { type: "Item", key: "3" }],
    };
    const view = await viewOf(spec, { ...ITEM, where: [{ column: "s", op: "contains", value: "" }] });
    expect(ids(view)).toEqual(["Item:1", "Item:2"]);
  });

  it("text comparisons go by UTF-8 bytes: an astral character is above a character of the plane below it", async () => {
    // U+FF5E (3 bytes EF BD 9E) sorts before U+1F600 (F0 9F 98 80) in bytes; UTF-16 order would reverse them.
    const spec: MosaicSpec = {
      typeProps: { Item: '{"s":"text"}' },
      nodes: ["\u{1F600}", "～", "ﬁ"].map((s, i) => ({ type: "Item", key: String(i), props: canon({ s }) })),
    };
    const gt = await viewOf(spec, { ...ITEM, where: [{ column: "s", op: ">", value: "～" }] });
    expect(cells(gt, "s")).toEqual(["\u{1F600}"]);
    const lt = await viewOf(spec, { ...ITEM, where: [{ column: "s", op: "<", value: "～" }] });
    expect(cells(lt, "s")).toEqual(["ﬁ"]);
  });

  it("numbers compare by value whatever their spelling: 1, 1.0 and 1e0 are one value", async () => {
    const spec: MosaicSpec = {
      typeProps: { Item: '{"x":"number"}' },
      nodes: [
        { type: "Item", key: "a", props: '{"x":1}' },
        { type: "Item", key: "b", props: '{"x":1.0}' },
        { type: "Item", key: "c", props: '{"x":10e-1}' },
        { type: "Item", key: "d", props: '{"x":-0}' },
        { type: "Item", key: "e", props: '{"x":0.5}' },
      ],
    };
    expect(ids(await viewOf(spec, { ...ITEM, where: [{ column: "x", op: "=", value: 1 }] }))).toEqual(["Item:a", "Item:b", "Item:c"]);
    expect(ids(await viewOf(spec, { ...ITEM, where: [{ column: "x", op: "=", value: 0 }] }))).toEqual(["Item:d"]);
    expect(ids(await viewOf(spec, { ...ITEM, order: { column: "x", desc: false } }))).toEqual(["Item:d", "Item:e", "Item:a", "Item:b", "Item:c"]);
  });

  it("an order on one column and a filter on another both hold, and paging runs over the filtered total", async () => {
    const view = await viewOf(numbered(70), {
      type: "Item",
      page: 2,
      order: { column: "n", desc: true },
      where: [{ column: "n", op: "<", value: 50 }, { column: "n", op: ">=", value: 5 }],
    });
    expect(view.total).toBe(45);
    expect(view.pages).toBe(3);
    expect(cells(view, "n")).toEqual(Array.from({ length: 20 }, (_, i) => 29 - i));
  });

  it("the last page of a filtered table holds the remainder", async () => {
    const view = await viewOf(numbered(70), { ...ITEM, page: 3, where: [{ column: "n", op: "<", value: 45 }] });
    expect(view.total).toBe(45);
    expect(cells(view, "n")).toEqual([40, 41, 42, 43, 44]);
  });

  it("ordering by label puts nodes with no label last, ascending or descending, ties by id", async () => {
    const spec: MosaicSpec = {
      nodes: [
        { type: "Item", key: "1", label: "B" },
        { type: "Item", key: "2" },
        { type: "Item", key: "3", label: "A" },
        { type: "Item", key: "4", label: "B" },
        { type: "Item", key: "0" },
      ],
    };
    expect(ids(await viewOf(spec, { ...ITEM, order: { column: "label", desc: false } }))).toEqual(["Item:3", "Item:1", "Item:4", "Item:0", "Item:2"]);
    expect(ids(await viewOf(spec, { ...ITEM, order: { column: "label", desc: true } }))).toEqual(["Item:1", "Item:4", "Item:3", "Item:0", "Item:2"]);
  });

  it("a boolean filter on a property that holds text, numbers or nothing keeps only real booleans for `=`", async () => {
    const spec: MosaicSpec = {
      typeProps: { Item: '{"f":"boolean"}' },
      nodes: [
        { type: "Item", key: "1", props: canon({ f: true }) },
        { type: "Item", key: "2", props: canon({ f: "true" }) },
        { type: "Item", key: "3", props: canon({ f: 1 }) },
        { type: "Item", key: "4" },
      ],
    };
    expect(ids(await viewOf(spec, { ...ITEM, where: [{ column: "f", op: "=", value: true }] }))).toEqual(["Item:1"]);
    expect(ids(await viewOf(spec, { ...ITEM, where: [{ column: "f", op: "!=", value: true }] }))).toEqual(["Item:2", "Item:3", "Item:4"]);
  });

  it("an unknown column is refused even when the table has no node, and the message names the column", async () => {
    const file = await openMosaic(buildMosaic({ types: ["Empty"], nodes: [{ type: "A", key: "1" }] }), "t.mosaic");
    for (const route of [
      { ...ITEM, type: "Empty", where: [{ column: "ghost", op: "=" as const, value: 1 }] },
      { ...ITEM, type: "Empty", order: { column: "ghost", desc: true } },
    ]) {
      const view = await tableView(file, route);
      expect("rows" in view).toBe(false);
      expect("message" in view && view.message).toContain("ghost");
    }
    file.close();
  });

  it("a column name of another type is unknown here", async () => {
    const file = await openMosaic(
      buildMosaic({
        typeProps: { A: '{"only_a":"text"}', B: '{"only_b":"text"}' },
        nodes: [{ type: "A", key: "1", props: canon({ only_a: "x" }) }, { type: "B", key: "1", props: canon({ only_b: "y" }) }],
      }),
      "t.mosaic",
    );
    const view = await tableView(file, { type: "B", page: 1, order: null, where: [{ column: "only_a", op: "=", value: "x" }] });
    expect("rows" in view).toBe(false);
    expect("message" in view && view.message).toContain("only_a");
    file.close();
  });
});

describe("paging (section 8.6: page from 1, 20 rows, total counts every kept node)", () => {
  it("1000 nodes: the last page holds 20, the pager says 50 pages, and rows are in id byte order", async () => {
    const spec = numbered(1000);
    const last = await viewOf(spec, { ...ITEM, page: 50 });
    expect(last.pages).toBe(50);
    expect(last.total).toBe(1000);
    expect(ids(last)).toEqual(Array.from({ length: 20 }, (_, i) => `Item:${String(980 + i).padStart(4, "0")}`));
  });

  it("ids sort by UTF-8 bytes across pages: upper case before lower case, no locale folding", async () => {
    const keys = ["b", "B", "a", "A", "é", "e", "Z", "z", "_", "0"];
    const spec: MosaicSpec = { nodes: keys.map((key) => ({ type: "Item", key })) };
    const view = await viewOf(spec, ITEM);
    expect(ids(view)).toEqual(["0", "A", "B", "Z", "_", "a", "b", "e", "z", "é"].map((k) => `Item:${k}`));
  });

  it("page 0, a negative page and a fractional page are refused by `table` and shown, never thrown", async () => {
    const file = await openMosaic(buildMosaic(numbered(3)), "t.mosaic");
    for (const page of [0, -1, 1.5, Number.NaN]) {
      const view = await tableView(file, { ...ITEM, page });
      expect("rows" in view || "message" in view, String(page)).toBe(true);
      if ("rows" in view) expect(view.page).toBeGreaterThanOrEqual(1);
    }
    file.close();
  });

  it("the singular and the plural of the row count", async () => {
    expect(draw(await viewOf(numbered(1), ITEM))).toContain("Page 1 of 1 · 1 row<");
    expect(draw(await viewOf(numbered(2), ITEM))).toContain("Page 1 of 1 · 2 rows<");
    expect(draw(await viewOf({ ...numbered(0), types: ["Item"] }, ITEM))).toContain("Page 1 of 1 · 0 rows<");
  });

  it("a big table is read in a page's time: 3000 nodes ordered and filtered answer well inside the kit's limit", async () => {
    const spec = numbered(3000);
    const file = await openMosaic(buildMosaic(spec), "big.mosaic");
    const started = performance.now();
    const view = await tableView(file, { type: "Item", page: 75, order: { column: "n", desc: true }, where: [{ column: "n", op: ">=", value: 1000 }] });
    const took = performance.now() - started;
    file.close();
    expect("rows" in view).toBe(true);
    if ("rows" in view) {
      expect(view.total).toBe(2000);
      expect(view.pages).toBe(100);
      expect(cells(view, "n")).toEqual(Array.from({ length: 20 }, (_, i) => 2999 - 74 * 20 - i));
    }
    expect(took).toBeLessThan(3000);
  });
});

describe("the Viewer and tables in flight (design.md Viewer)", () => {
  const A: MosaicSpec = { nodes: [{ type: "Item", key: "a" }] };
  const B: MosaicSpec = { nodes: [{ type: "Other", key: "b" }] };

  it("requests asked page 3, 2, 1 end on page 1, the last asked", async () => {
    const viewer = new Viewer();
    await viewer.open(buildMosaic(numbered(60)), "n.mosaic");
    await Promise.all([3, 2, 1].map((page) => viewer.showTable({ ...ITEM, page })));
    expect(viewer.table && "page" in viewer.table && viewer.table.page).toBe(1);
  });

  it("a table still being read when another mosaic opens is not shown over the new mosaic", async () => {
    const viewer = new Viewer();
    await viewer.open(buildMosaic(A), "a.mosaic");
    const pending = viewer.showTable(ITEM);
    await viewer.open(buildMosaic(B), "b.mosaic");
    await pending;
    expect(viewer.file?.nodeTypes.map((t) => t.name)).toEqual(["Other"]);
    const shown = viewer.table;
    // Either nothing, or a refusal: never the rows of the file that is closed.
    expect(shown && "rows" in shown ? shown.rows : []).toEqual([]);
  });

  it("showing a table twice with the same route gives equal views", async () => {
    const viewer = new Viewer();
    await viewer.open(buildMosaic(numbered(30)), "n.mosaic");
    await viewer.showTable({ ...ITEM, page: 2, order: { column: "n", desc: true } });
    const first = JSON.stringify(viewer.table);
    await viewer.showTable({ ...ITEM, page: 2, order: { column: "n", desc: true } });
    expect(JSON.stringify(viewer.table)).toBe(first);
  });
});
