// Edge cases for M2.9 (viewer: search box and node page), written from the spec's words, not the
// implementation: Specification 0.1 sections 3.8 (reading rules), 8.1 and 8.2 (tools, bounds),
// 10 (untrusted data), spec/answers.schema.json, conformance/reading/ and the milestone's wording:
// "a node page shows what `get` returns, its links from `neighbors` and its sources from `cite`".
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { render } from "svelte/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QUERY_LIMIT, RESULT_LIMIT, openFile } from "@mosaic/kit";
import { buildMosaic, type EdgeSpec, type MosaicSpec, type NodeSpec } from "../../kit/test/build-mosaic.js";
import App from "../src/App.svelte";
import EntityCard from "../src/components/EntityCard.svelte";
import NodeContext from "../src/components/NodeContext.svelte";
import ResultList from "../src/components/ResultList.svelte";
import {
  fetchNamedMosaic,
  nodePage,
  openMosaic,
  search,
  type NodeView,
  type SearchView,
  type ToolFailure,
} from "../src/lib/mosaic.js";
import { parseRoute, routeHash } from "../src/lib/route.js";
import { Viewer } from "../src/lib/viewer.svelte.js";
import { reading } from "./fixtures.js";

afterEach(() => vi.unstubAllGlobals());

const hrefFor = (id: string) => routeHash({ query: "", node: id });

const cases = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../conformance/reading/cases.json", import.meta.url)), "utf8"),
) as Record<string, { opens: boolean; rule: string | null }>;

async function viewerOn(spec: MosaicSpec): Promise<Viewer> {
  const viewer = new Viewer();
  await viewer.open(buildMosaic(spec), "built.mosaic");
  if (viewer.status !== "ready") throw new Error(`did not open: ${viewer.error}`);
  return viewer;
}

const many = (n: number, make: (i: number) => NodeSpec): NodeSpec[] => Array.from({ length: n }, (_, i) => make(i));

function groups(view: SearchView | ToolFailure | null): SearchView {
  if (!view || !("groups" in view)) throw new Error(`not a search view: ${JSON.stringify(view)}`);
  return view;
}

function nodeView(view: NodeView | ToolFailure | null): NodeView {
  if (!view || !("node" in view)) throw new Error(`not a node view: ${JSON.stringify(view)}`);
  return view;
}

describe("opening: every file of conformance/reading follows section 3.8", () => {
  for (const [name, expected] of Object.entries(cases)) {
    it(`the viewer ${expected.opens ? "opens" : `refuses, for ${expected.rule},`} ${name}`, async () => {
      const viewer = new Viewer();
      await viewer.open(reading(name), name);
      if (expected.opens) {
        expect(viewer.status).toBe("ready");
        expect(viewer.error).toBeNull();
        expect(viewer.file?.header.knowledge_hash).toHaveLength(64);
      } else {
        expect(viewer.status).toBe("error");
        expect(viewer.error).toContain(name); // section 3.8: an error that names the file
        expect(viewer.file).toBeNull();
      }
    });
  }

  it("the viewer's error carries what failed, as the kit words it", async () => {
    const bytes = reading("node-changed.mosaic");
    const viewer = new Viewer();
    await viewer.open(bytes, "node-changed.mosaic");
    const kit = await openFile(bytes, "node-changed.mosaic").then(
      () => "",
      (e: Error) => e.message,
    );
    expect(kit).not.toBe("");
    expect(viewer.error).toContain(kit);
  });

  it("a refused file after a good one is an error the page shows, naming the new file", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "good.mosaic");
    await viewer.open(reading("application-id.mosaic"), "bad.mosaic");
    expect(viewer.error).toContain("bad.mosaic");
    expect(render(App, { props: { viewer } }).body).toContain("bad.mosaic");
  });

  it("opening a second mosaic clears the first one's results and node page", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "one.mosaic");
    await viewer.search("Item");
    await viewer.show("Item:a");
    await viewer.open(reading("non-ascii.mosaic"), "two.mosaic");
    expect(viewer.status).toBe("ready");
    expect(viewer.file?.name).toBe("two.mosaic");
    expect(viewer.results).toBeNull();
    expect(viewer.page).toBeNull();
  });

  it("opening reads the bytes and never writes them (principle 8, section 3.8 step 1)", async () => {
    const bytes = reading("mosaic.mosaic");
    const before = new Uint8Array(bytes);
    const viewer = new Viewer();
    await viewer.open(bytes, "mosaic.mosaic");
    await viewer.search("Item");
    await viewer.show("Item:a");
    expect(bytes).toEqual(before);
  });

  it("an empty byte array is a refused file, not a crash", async () => {
    const viewer = new Viewer();
    await viewer.open(new Uint8Array(0), "nothing.mosaic");
    expect(viewer.status).toBe("error");
    expect(viewer.error).toContain("nothing.mosaic");
  });

  it("a mosaic with no nodes opens; search finds nothing and a node page says unknown id", async () => {
    const viewer = await viewerOn({ nodes: [] });
    await viewer.search("anything");
    expect(groups(viewer.results)).toEqual({ query: "anything", groups: [], total: 0 });
    await viewer.show("Item:a");
    expect(viewer.page && "message" in viewer.page).toBe(true);
  });

  it("a file name with markup is shown escaped, in the page and in an error", async () => {
    const hostile = `<img src=x onerror=alert(1)>.mosaic`;
    const viewer = new Viewer();
    await viewer.open(reading("application-id.mosaic"), hostile);
    expect(render(App, { props: { viewer } }).body).not.toContain("<img");
    const ok = new Viewer();
    await ok.open(reading("mosaic.mosaic"), hostile);
    expect(render(App, { props: { viewer: ok } }).body).not.toContain("<img");
  });

  it("with the page's open, search and node page, nothing is fetched, nor a socket or request opened (no query server)", async () => {
    (await openMosaic(reading("mosaic.mosaic"), "warm.mosaic")).close(); // SQLite loaded once
    const ask = vi.fn(() => {
      throw new Error("the viewer asked a server");
    });
    vi.stubGlobal("fetch", ask);
    vi.stubGlobal("WebSocket", ask);
    vi.stubGlobal("XMLHttpRequest", ask);
    vi.stubGlobal("EventSource", ask);
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    await viewer.search("Item");
    await viewer.show("Group:x");
    expect(viewer.status).toBe("ready");
    expect(viewer.page && "node" in viewer.page).toBe(true);
    expect(ask).not.toHaveBeenCalled();
  });
});

describe("fetching the named mosaic", () => {
  const ok = (bytes: Uint8Array) => vi.fn(async () => new Response(bytes));

  it("an empty ?mosaic= names nothing", async () => {
    const fetcher = ok(new Uint8Array(1));
    expect(await fetchNamedMosaic("?mosaic=", "http://localhost/", fetcher as typeof fetch)).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("other parameters name nothing", async () => {
    const fetcher = ok(new Uint8Array(1));
    expect(await fetchNamedMosaic("?q=a.mosaic&node=x", "http://localhost/", fetcher as typeof fetch)).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("the fetched bytes go through the reading rules like any picked file", async () => {
    const named = await fetchNamedMosaic("?mosaic=bad.mosaic", "http://localhost/", ok(reading("user-version.mosaic")) as typeof fetch);
    expect(named?.name).toBe("bad.mosaic");
    const viewer = new Viewer();
    await viewer.open(named!.bytes, named!.name);
    expect(viewer.status).toBe("error");
    expect(viewer.error).toContain("bad.mosaic");
  });

  it("a network failure is an error naming the file", async () => {
    const down = vi.fn(async () => {
      throw new TypeError("network down");
    });
    await expect(fetchNamedMosaic("?mosaic=far.mosaic", "http://localhost/", down as typeof fetch)).rejects.toThrow(/far\.mosaic/);
  });
});

describe("search: find's bounds and untrusted text (sections 8.1, 8.2, 10)", () => {
  const thirty = (): MosaicSpec => ({
    nodes: many(30, (i) => ({ type: "Item", key: `k${String(i).padStart(2, "0")}`, label: `Widget ${i}` })),
  });

  it("more matches than the list holds: the list stops at 20 and total counts them all", async () => {
    const viewer = await viewerOn(thirty());
    await viewer.search("Widget");
    const view = groups(viewer.results);
    expect(view.groups.flatMap((g) => g.results)).toHaveLength(RESULT_LIMIT);
    expect(view.total).toBe(30);
  });

  it("the results list names how many matched when it shows fewer", async () => {
    const viewer = await viewerOn(thirty());
    await viewer.search("Widget");
    const { body } = render(ResultList, { props: { view: groups(viewer.results), hrefFor } });
    expect(body).toMatch(/\b30\b/);
  });

  it("a query over the kit's limit is the kit's error on screen, not an exception", async () => {
    const viewer = await viewerOn(thirty());
    await viewer.search("a".repeat(QUERY_LIMIT + 1));
    expect(viewer.results && "message" in viewer.results).toBe(true);
    const failure = viewer.results as ToolFailure;
    expect(failure.message).not.toBe("");
    expect(render(ResultList, { props: { view: failure, hrefFor } }).body).toContain('role="alert"');
  });

  it("a query exactly at the limit is searched", async () => {
    const viewer = await viewerOn(thirty());
    await viewer.search("a".repeat(QUERY_LIMIT));
    expect(groups(viewer.results).total).toBe(0);
  });

  it("a query with a NUL, or only punctuation, never throws", async () => {
    const viewer = await viewerOn(thirty());
    for (const q of ["Wid\u0000get", "\u0000", '"', "*", "OR", "NEAR(", '" OR *', "a AND", "'; DROP TABLE node; --"]) {
      await expect(viewer.search(q)).resolves.toBeUndefined();
      expect(viewer.results).not.toBeUndefined();
    }
    expect(viewer.status).toBe("ready");
  });

  it("after an error answer, the next good query replaces it, and the error replaces good results", async () => {
    const viewer = await viewerOn(thirty());
    await viewer.search("Widget");
    expect(groups(viewer.results).total).toBe(30);
    await viewer.search("a".repeat(QUERY_LIMIT + 1));
    expect(viewer.results && "message" in viewer.results).toBe(true);
    await viewer.search("Widget 7");
    expect(groups(viewer.results).query).toBe("Widget 7");
  });

  it("non-ASCII queries find non-ASCII ids, labels and aliases by their characters", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("non-ascii.mosaic"), "non-ascii.mosaic");
    for (const q of ["～", "😀"]) {
      await viewer.search(q);
      const ids = groups(viewer.results).groups.flatMap((g) => g.results.map((r) => r.id));
      expect(ids.length, q).toBeGreaterThan(0);
      expect(ids.some((id) => id.includes(q)), q).toBe(true);
    }
  });

  it("the same query twice gives the same view", async () => {
    const viewer = await viewerOn(thirty());
    await viewer.search("Widget 1");
    const first = JSON.stringify(viewer.results);
    await viewer.search("Widget 2");
    await viewer.search("Widget 1");
    expect(JSON.stringify(viewer.results)).toBe(first);
  });

  it("a query that is only spaces, tabs or newlines is no search", async () => {
    const viewer = await viewerOn(thirty());
    await viewer.search("Widget");
    await viewer.search(" \t\n ");
    expect(viewer.results).toBeNull();
  });

  it("a blank query clears the results even while an earlier search is still running", async () => {
    const viewer = await viewerOn(thirty());
    const slow = viewer.search("Widget");
    const blank = viewer.search("");
    await Promise.all([blank, slow]);
    expect(viewer.results).toBeNull();
  });

  it("a search that finishes after another mosaic was opened does not show its results", async () => {
    const viewer = await viewerOn(thirty());
    const slow = viewer.search("Widget");
    await viewer.open(reading("non-ascii.mosaic"), "other.mosaic");
    await slow;
    expect(viewer.results).toBeNull();
  });

  it("a node page that finishes after a newer one never replaces it", async () => {
    const viewer = await viewerOn(thirty());
    const first = viewer.show("Item:k01");
    const second = viewer.show("Item:k02");
    await Promise.all([second, first]);
    expect(nodeView(viewer.page).node.id).toBe("Item:k02");
    expect(viewer.nodeId).toBe("Item:k02");
  });

  it("closing the node page while it loads leaves no page", async () => {
    const viewer = await viewerOn(thirty());
    const pending = viewer.show("Item:k01");
    await viewer.show(null);
    await pending;
    expect(viewer.page).toBeNull();
  });
});

describe("results list: every result shows id, type, label and match (section 8.2)", () => {
  it("a result with no label still shows its id, type and match, and no 'null'", () => {
    const view: SearchView = {
      query: "x",
      total: 1,
      groups: [{ match: "exact", results: [{ id: "Item:nolabel", type: "Item", label: null, match: "exact" }] }],
    };
    const { body } = render(ResultList, { props: { view, hrefFor } });
    expect(body).toContain("Item:nolabel");
    expect(body).toContain('data-match="exact"');
    expect(body).not.toMatch(/>\s*(null|undefined)\s*</);
  });

  it("a result of the vector tier is marked as one", () => {
    const view: SearchView = {
      query: "x",
      total: 1,
      groups: [{ match: "vector", results: [{ id: "Item:v", type: "Item", label: "V", match: "vector" }] }],
    };
    expect(render(ResultList, { props: { view, hrefFor } }).body).toContain('data-match="vector"');
  });

  it("an id with quotes, ampersands and angle brackets cannot break out of an attribute", () => {
    const id = `Item:"><img src=x onerror=1>&'`;
    const view: SearchView = {
      query: "x",
      total: 1,
      groups: [{ match: "text", results: [{ id, type: "Item", label: id, match: "text" }] }],
    };
    const { body } = render(ResultList, { props: { view, hrefFor: (i: string) => `#node=${i}`, selected: id } });
    expect(body).not.toContain("<img");
    expect(body).not.toMatch(/"><img/);
  });

  it("a tool error's message and suggestions are escaped", () => {
    const view: ToolFailure = { message: "<script>x</script>", suggestions: ["Item:<i>a</i>"] };
    const { body } = render(ResultList, { props: { view, hrefFor } });
    expect(body).not.toContain("<script>");
    expect(body).not.toContain("<i>");
  });

  it("two results with the same label are two rows, told apart by their ids", () => {
    const view: SearchView = {
      query: "x",
      total: 2,
      groups: [
        {
          match: "text",
          results: [
            { id: "Item:a", type: "Item", label: "Same", match: "text" },
            { id: "Other:a", type: "Other", label: "Same", match: "text" },
          ],
        },
      ],
    };
    const { body } = render(ResultList, { props: { view, hrefFor } });
    expect(body.match(/data-id="/g)).toHaveLength(2);
    expect(body).toContain('data-id="Item:a"');
    expect(body).toContain('data-id="Other:a"');
  });
});

describe("node page: get, neighbors and cite on awkward nodes (sections 8.1, 8.2, 3.4)", () => {
  const edge = (from: string, to: string, type = "rel"): EdgeSpec => ({ type, from, to });

  it("a node with no edges has no links and still has its sources", async () => {
    const viewer = await viewerOn({ nodes: [{ type: "Item", key: "lone", label: "Lone", snippets: ["why it exists"] }] });
    await viewer.show("Item:lone");
    const view = nodeView(viewer.page);
    expect(view.links).toEqual([]);
    expect(view.sources.length).toBeGreaterThan(0);
    expect(view.sourcesTotal).toBe(view.sources.length);
    const { body } = render(NodeContext, { props: { view, hrefFor } });
    expect(body).toContain("why it exists");
  });

  it("a node with more than 20 neighbours on one edge type lists 20 and counts them all", async () => {
    const nodes = [{ type: "Hub", key: "h", label: "Hub" }, ...many(25, (i) => ({ type: "Item", key: `i${String(i).padStart(2, "0")}`, label: `Item ${i}` }))];
    const viewer = await viewerOn({
      nodes,
      edgeTypes: [["rel", "Item", "Hub"]],
      edges: nodes.slice(1).map((n) => edge(`${n.type}:${n.key}`, "Hub:h")),
    });
    await viewer.show("Hub:h");
    const view = nodeView(viewer.page);
    expect(view.links).toHaveLength(1);
    expect(view.links[0]!.count).toBe(25);
    expect(view.links[0]!.edges).toHaveLength(RESULT_LIMIT);
    const { body } = render(NodeContext, { props: { view, hrefFor } });
    expect(body).toContain("25");
    expect(body.match(/href="/g)).toHaveLength(RESULT_LIMIT);
  });

  it("a node with both directions and several edge types has one group for each", async () => {
    const viewer = await viewerOn({
      nodes: [
        { type: "N", key: "a", label: "A" },
        { type: "N", key: "b", label: "B" },
        { type: "N", key: "c", label: "C" },
      ],
      edgeTypes: [
        ["knows", "N", "N"],
        ["likes", "N", "N"],
      ],
      edges: [edge("N:a", "N:b", "knows"), edge("N:c", "N:a", "knows"), edge("N:a", "N:c", "likes")],
    });
    await viewer.show("N:a");
    const view = nodeView(viewer.page);
    expect(view.links.map((l) => `${l.edge}/${l.direction}/${l.count}`).sort()).toEqual(["knows/in/1", "knows/out/1", "likes/out/1"]);
    const { body } = render(NodeContext, { props: { view, hrefFor } });
    const opened = [...body.matchAll(/href="([^"]*)"/g)].map((m) => parseRoute(m[1]!.replaceAll("&amp;", "&")).node).sort();
    expect(opened).toEqual(["N:b", "N:c", "N:c"]);
  });

  it("a self-loop shows once outgoing and once incoming, and each opens the node itself", async () => {
    const viewer = await viewerOn({
      nodes: [{ type: "N", key: "a", label: "A" }],
      edgeTypes: [["same", "N", "N"]],
      edges: [edge("N:a", "N:a", "same")],
    });
    await viewer.show("N:a");
    const view = nodeView(viewer.page);
    expect(view.links.map((l) => `${l.direction}/${l.count}`).sort()).toEqual(["in/1", "out/1"]);
  });

  it("parallel edges of one type between the same two nodes with different qualifiers are all counted", async () => {
    const viewer = await viewerOn({
      nodes: [
        { type: "N", key: "a", label: "A" },
        { type: "N", key: "b", label: "B" },
      ],
      edgeTypes: [["rel", "N", "N"]],
      edges: [
        { type: "rel", from: "N:a", to: "N:b", qualifier: "one" },
        { type: "rel", from: "N:a", to: "N:b", qualifier: "two" },
      ],
    });
    await viewer.show("N:a");
    const link = nodeView(viewer.page).links[0]!;
    expect(link.count).toBe(2);
    expect(link.edges).toHaveLength(2);
  });

  it("a neighbour with no label is still a link that opens it", async () => {
    const viewer = await viewerOn({
      nodes: [
        { type: "N", key: "a", label: "A" },
        { type: "N", key: "unlabelled", label: null },
      ],
      edgeTypes: [["rel", "N", "N"]],
      edges: [edge("N:a", "N:unlabelled")],
    });
    await viewer.show("N:a");
    const { body } = render(NodeContext, { props: { view: nodeView(viewer.page), hrefFor } });
    expect(parseRoute((/href="([^"]*)"/.exec(body)?.[1] ?? "").replaceAll("&amp;", "&")).node).toBe("N:unlabelled");
    expect(body).toContain("N:unlabelled");
    expect(body).not.toMatch(/>\s*(null|undefined)\s*</);
  });

  it("a node with no label, summary or props shows its id and type and no 'null'", async () => {
    const viewer = await viewerOn({ nodes: [{ type: "N", key: "bare", label: null, summary: null, props: null }] });
    await viewer.show("N:bare");
    const { body } = render(EntityCard, { props: { node: nodeView(viewer.page).node } });
    expect(body).toContain("N:bare");
    expect(body).toContain(">N<");
    expect(body).not.toMatch(/>\s*(null|undefined)\s*</);
  });

  it("aliases and external references, which get returns, are on the page", async () => {
    const viewer = await viewerOn({
      nodes: [
        {
          type: "N",
          key: "a",
          label: "A",
          aliases: ["the first letter", "alpha"],
          externalRefs: [{ system: "historian", kind: "timeseries", locator: '{"series":"TEMP-3"}' }],
        },
      ],
    });
    await viewer.show("N:a");
    const view = nodeView(viewer.page);
    expect(view.node.aliases).toEqual(expect.arrayContaining(["alpha", "the first letter"]));
    const { body } = render(EntityCard, { props: { node: view.node } });
    expect(body).toContain("the first letter");
    expect(body).toContain("alpha");
    expect(body).toContain("historian");
    expect(body).toContain("timeseries");
    expect(body).toContain("TEMP-3");
  });

  it("evidence on an edge, not the node, is not in the node's sources", async () => {
    const viewer = await viewerOn({
      nodes: [
        { type: "N", key: "a", label: "A", snippets: ["about a"] },
        { type: "N", key: "b", label: "B", snippets: ["about b"] },
      ],
      edgeTypes: [["rel", "N", "N"]],
      edges: [{ type: "rel", from: "N:a", to: "N:b", evidence: [{ snippet: "edge evidence" }] }],
    });
    await viewer.show("N:a");
    const view = nodeView(viewer.page);
    const { body } = render(NodeContext, { props: { view, hrefFor } });
    expect(body).toContain("about a");
    expect(body).not.toContain("about b");
    const cited = await viewer.file!.cite({ id: "N:a" });
    if (!("data" in cited)) throw new Error("cite failed");
    expect(view.sources).toEqual(cited.data.evidence);
  });

  it("more than 20 evidence rows: 20 are listed and the total is the real count", async () => {
    const viewer = await viewerOn({
      nodes: [{ type: "N", key: "a", label: "A", evidence: many(23, (i) => ({ locator: `row${i}`, snippet: `snip ${i}` })) }],
    });
    await viewer.show("N:a");
    const view = nodeView(viewer.page);
    expect(view.sources).toHaveLength(RESULT_LIMIT);
    expect(view.sourcesTotal).toBe(23);
  });

  it("an inferred source shows how it was made, with its confidence", async () => {
    const viewer = await viewerOn({
      nodes: [{ type: "N", key: "a", label: "A", evidence: [{ method: "inferred", confidence: 0.25, producer: "guesser", snippet: "maybe" }] }],
    });
    await viewer.show("N:a");
    const view = nodeView(viewer.page);
    expect(view.sources[0]).toMatchObject({ method: "inferred", confidence: 0.25 });
    const { body } = render(NodeContext, { props: { view, hrefFor } });
    expect(body).toMatch(/inferred/i);
    expect(body).toContain("0.25");
  });

  it("text from the file in props, summary, aliases, labels, snippets and locators is escaped everywhere on the page", async () => {
    const evil = "<img src=x onerror=alert(1)>";
    const viewer = await viewerOn({
      nodes: [
        {
          type: "N",
          key: "a",
          label: evil,
          summary: evil,
          props: JSON.stringify({ name: evil }),
          aliases: [evil],
          snippets: [evil],
          evidence: [{ locator: evil, snippet: evil }],
        },
        { type: "N", key: "b", label: evil },
      ],
      edgeTypes: [["rel", "N", "N"]],
      edges: [edge("N:a", "N:b")],
    });
    await viewer.search("a");
    await viewer.show("N:a");
    const { body } = render(App, { props: { viewer } });
    expect(body).not.toContain("<img");
  });

  it("an id of 512 characters, the longest an id can be, opens a page; one more is an error shown, not thrown", async () => {
    const key = "k".repeat(509);
    const viewer = await viewerOn({ nodes: [{ type: "N", key, label: "Long" }] });
    await viewer.show(`N:${key}`);
    expect(nodeView(viewer.page).node.id).toBe(`N:${key}`);
    await viewer.show(`N:${key}k`);
    expect(viewer.page && "message" in viewer.page).toBe(true);
  });

  it("an unknown id is the kit's error with its suggestions, and the page offers each suggestion as a link", async () => {
    const viewer = await viewerOn({ nodes: [{ type: "Item", key: "apple", label: "Apple" }] });
    await viewer.show("Item:appel");
    const failure = viewer.page as ToolFailure;
    expect("message" in failure).toBe(true);
    expect(failure.message).toContain("Item:appel");
    const { body } = render(App, { props: { viewer } });
    expect(body).toContain("Item:appel");
    for (const s of failure.suggestions) expect(body).toContain(s);
  });

  it("showing the same node twice gives equal pages", async () => {
    const viewer = await viewerOn({
      nodes: [
        { type: "N", key: "a", label: "A" },
        { type: "N", key: "b", label: "B" },
      ],
      edgeTypes: [["rel", "N", "N"]],
      edges: [edge("N:a", "N:b")],
    });
    await viewer.show("N:a");
    const first = JSON.stringify(viewer.page);
    await viewer.show("N:b");
    await viewer.show("N:a");
    expect(JSON.stringify(viewer.page)).toBe(first);
  });

  it("the node page of a tessera opens too: it is a file the reading rules accept", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("tessera.tessera"), "tessera.tessera");
    expect(viewer.status).toBe("ready");
    await viewer.search("Item");
    expect(viewer.results).not.toBeNull();
  });

  it("a mosaic whose vectors the kit's model does not cover still searches by names and text (section 3.8)", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic"); // embed_model is 'invented-model@…'
    expect(viewer.status).toBe("ready");
    await viewer.search("Item A");
    const found = groups(viewer.results).groups.flatMap((g) => g.results.map((r) => r.id));
    expect(found).toContain("Item:a");
    expect(groups(viewer.results).groups.every((g) => g.match !== "vector")).toBe(true);
  });
});

describe("routes: whatever the address holds, the page can read it", () => {
  it("malformed percent-escapes do not throw", () => {
    for (const hash of ["#q=%", "#q=%E0%A4%A", "#node=%zz", "#q=%ff%fe&node=%c0%af", "#%", "#=", "#&&&", "#q"]) {
      expect(() => parseRoute(hash), hash).not.toThrow();
      const route = parseRoute(hash);
      expect(typeof route.query).toBe("string");
      expect(route.node === null || typeof route.node === "string").toBe(true);
    }
  });

  it("unknown parameters are ignored and the first or last of a repeated one wins consistently", () => {
    expect(parseRoute("#zzz=1&q=a&node=Item%3Ab")).toEqual({ query: "a", node: "Item:b" });
    const twice = parseRoute("#q=a&q=b");
    expect(["a", "b"]).toContain(twice.query);
  });

  it("an empty node is no node", () => {
    expect(parseRoute("#q=a&node=").node).toBeNull();
  });

  it("the address without its leading # reads the same", () => {
    expect(parseRoute("q=a&node=Item%3Ab")).toEqual(parseRoute("#q=a&node=Item%3Ab"));
  });

  it("a NUL, a newline and a 1000-character query survive the round trip", () => {
    for (const query of ["a\u0000b", "line1\nline2", "x".repeat(QUERY_LIMIT)]) {
      expect(parseRoute(routeHash({ query, node: "Item:a" }))).toEqual({ query, node: "Item:a" });
    }
  });

  it("an id of 512 astral characters survives the round trip", () => {
    const node = "N:" + "😀".repeat(510);
    expect(parseRoute(routeHash({ query: "", node }))).toEqual({ query: "", node });
  });

  it("a query with a lone surrogate does not make the link throw", () => {
    expect(() => routeHash({ query: "a\uD800", node: null })).not.toThrow();
  });

  it("the route's text is the same string whatever the order the same route is built in", () => {
    expect(routeHash({ query: "a", node: "Item:a" })).toBe(routeHash({ node: "Item:a", query: "a" }));
  });
});

describe("what the page shows of the header", () => {
  it("the page names the mosaic by the 12 hex characters of its knowledge hash, from the header as hashed", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    const body = render(App, { props: { viewer } }).body;
    expect(body).toContain(">8adae50b32ad<"); // conformance/reading/cases.json: knowledge_hash
  });

  it("a tessera and a mosaic opened one after the other are each named by their own hash", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("tessera.tessera"), "t.tessera");
    expect(render(App, { props: { viewer } }).body).toContain(">9a56bbb09c60<");
    await viewer.open(reading("mosaic.mosaic"), "m.mosaic");
    const body = render(App, { props: { viewer } }).body;
    expect(body).toContain(">8adae50b32ad<");
    expect(body).not.toContain("9a56bbb09c60");
  });
});

describe("the viewer keeps what the helpers answer", () => {
  it("search() and nodePage() give the same views as the Viewer keeps", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    await viewer.search("Item");
    await viewer.show("Item:a");
    expect(viewer.results).toEqual(await search(viewer.file!, "Item"));
    expect(viewer.page).toEqual(await nodePage(viewer.file!, "Item:a"));
  });
});
