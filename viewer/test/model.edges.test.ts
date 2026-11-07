// Edge cases for M2.12 (answer A on #117): the model reaches the page at runtime from the address
// `mosaic view` gives it, and `find` in the page lists vector matches only with an embedder whose
// model the mosaic names. Written from the spec's words (sections 3.8, 6, 8.1, 8.5), not the
// implementation.
import type { QueryEmbedder } from "@mosaic/kit";
import { MODEL, QUERY_LIMIT } from "@mosaic/kit";
import { describe, expect, it } from "vitest";
import { fetchNamedModel, MODEL_PARAM, type SearchView, type ToolFailure } from "../src/lib/mosaic.js";
import { Viewer } from "../src/lib/viewer.svelte.js";
import { reading } from "./fixtures.js";

/** The `embed_model` of conformance/reading/mosaic.mosaic, whose vectors are invented. */
const READING_MODEL = "invented-model@ca56847038f3f329524caec5a86e14865f49918d68094c90dd021a5e67b927f6";

type Recording = QueryEmbedder & { queries: string[] };

function embedder(embed: (q: string) => Promise<Float32Array>, model = READING_MODEL): Recording {
  const queries: string[] = [];
  return {
    model,
    queries,
    async embedQuery(q: string) {
      queries.push(q);
      return embed(q);
    },
  };
}

const ones = (): Float32Array => new Float32Array(384).fill(1 / Math.sqrt(384));

function view(v: SearchView | ToolFailure | null): SearchView {
  if (!v || !("groups" in v)) throw new Error(`not a search view: ${JSON.stringify(v)}`);
  return v;
}

async function opened(e: QueryEmbedder | null): Promise<Viewer> {
  const viewer = new Viewer();
  if (e) viewer.embedder = e;
  await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
  expect(viewer.status).toBe("ready");
  return viewer;
}

const ok = (body: Uint8Array) => new Response(body);

describe("fetchNamedModel: the address names the model's directory (answer A)", () => {
  const model = new Uint8Array([1, 2, 3]);
  const tokenizer = new Uint8Array([4, 5]);
  const at = (prefix: string): Record<string, Uint8Array> => ({
    [`${prefix}${MODEL.modelFile.path}`]: model,
    [`${prefix}${MODEL.tokenizer.path}`]: tokenizer,
  });
  const serve = (files: Record<string, Uint8Array>, seen: string[] = []): typeof fetch =>
    (async (input: RequestInfo | URL) => {
      seen.push(String(input));
      const body = files[String(input)];
      return body === undefined ? new Response("no", { status: 404, statusText: "Not Found" }) : ok(body);
    }) as typeof fetch;

  it("the parameter is called 'model' and the mosaic's is not taken for it", async () => {
    expect(MODEL_PARAM).toBe("model");
    const seen: string[] = [];
    expect(await fetchNamedModel("?mosaic=file%2Fm.mosaic", "http://h/", serve({}, seen))).toBeNull();
    expect(seen).toEqual([]);
  });

  it("resolves the directory against the page's own address, in a subdirectory too", async () => {
    const base = "http://h:1/app/index.html?model=weights%2F";
    const got = await fetchNamedModel("?model=weights%2F", base, serve(at("http://h:1/app/weights/")));
    expect([...got!.model]).toEqual([...model]);
    expect([...got!.tokenizer]).toEqual([...tokenizer]);
  });

  it("asks for exactly the two pinned files, once each, and nothing else", async () => {
    const seen: string[] = [];
    await fetchNamedModel("?model=m%2F", "http://h/?model=m%2F", serve(at("http://h/m/"), seen));
    expect([...seen].sort()).toEqual(
      [`http://h/m/${MODEL.modelFile.path}`, `http://h/m/${MODEL.tokenizer.path}`].sort(),
    );
  });

  it("a status that is not success is an error naming the file and the status", async () => {
    const files = at("http://h/m/");
    const gone = serve({ [`http://h/m/${MODEL.modelFile.path}`]: model });
    const err = await fetchNamedModel("?model=m%2F", "http://h/", gone).catch((e: Error) => e);
    expect(err).toBeInstanceOf(Error);
    expect(String((err as Error).message)).toContain(MODEL.tokenizer.path);
    expect(String((err as Error).message)).toMatch(/404/);
    const server = (async () => new Response("boom", { status: 500, statusText: "Server Error" })) as typeof fetch;
    const err2 = await fetchNamedModel("?model=m%2F", "http://h/", server).catch((e: Error) => e);
    expect(String((err2 as Error).message)).toMatch(/500/);
    expect(Object.keys(files)).toHaveLength(2);
  });

  it("malformed percent-escapes in the address do not throw something that is not an error", async () => {
    for (const search of ["?model=%", "?model=%E0%A4%A", "?model=%zz", "?%=%&model"]) {
      await Promise.resolve(fetchNamedModel(search, "http://h/", serve({}))).then(
        (got) => expect(got === null || typeof got === "object").toBe(true),
        (e) => expect(e).toBeInstanceOf(Error),
      );
    }
  });

  it("two calls fetch the same bytes: no state is kept between them", async () => {
    const files = at("http://h/m/");
    const a = await fetchNamedModel("?model=m%2F", "http://h/", serve(files));
    const b = await fetchNamedModel("?model=m%2F", "http://h/", serve(files));
    expect([...a!.model]).toEqual([...b!.model]);
    expect([...a!.tokenizer]).toEqual([...b!.tokenizer]);
  });
});

describe("the page's search with an embedder (sections 3.8, 8.1, 8.5)", () => {
  it("lists vector matches after the exact and text ones, each id once", async () => {
    const e = embedder(async () => ones());
    const viewer = await opened(e);
    await viewer.search("Item");
    const v = view(viewer.results);
    const order = v.groups.map((g) => g.match);
    const rank = { exact: 0, text: 1, vector: 2 } as const;
    expect(order).toEqual([...order].sort((a, b) => rank[a] - rank[b]));
    const ids = v.groups.flatMap((g) => g.results.map((r) => r.id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("the vector tier lists every node a query names by neither id nor text, up to the node count", async () => {
    const viewer = await opened(embedder(async () => ones()));
    await viewer.search("zzzz unmatched words");
    const v = view(viewer.results);
    expect(v.groups.map((g) => g.match)).toEqual(["vector"]);
    expect(v.groups[0]!.results.length).toBeGreaterThan(0);
    expect(v.total).toBe(v.groups[0]!.results.length);
  });

  it("embeds the query once as typed, and not at all for a blank query", async () => {
    const e = embedder(async () => ones());
    const viewer = await opened(e);
    await viewer.search("  \t\n ");
    expect(e.queries).toEqual([]);
    await viewer.search("a query");
    expect(e.queries).toEqual(["a query"]);
  });

  it("does not embed a query over the kit's limit", async () => {
    const e = embedder(async () => ones());
    const viewer = await opened(e);
    await viewer.search("a".repeat(QUERY_LIMIT + 1));
    expect(e.queries).toEqual([]);
    expect(viewer.results && "message" in viewer.results).toBe(true);
  });

  it("an embedder that fails is not an exception: the search resolves and the page stays ready", async () => {
    const e = embedder(async () => {
      throw new Error("the model is gone");
    });
    const viewer = await opened(e);
    await expect(viewer.search("Item")).resolves.toBeUndefined();
    expect(viewer.status).toBe("ready");
    expect(viewer.results).not.toBeNull();
    // Whatever it shows, it lists no vector match it could not rank.
    const r = viewer.results;
    if (r && "groups" in r) expect(r.groups.map((g) => g.match)).not.toContain("vector");
  });

  it("a vector of the wrong length or with NaN is not used to rank", async () => {
    for (const bad of [new Float32Array(3).fill(1), new Float32Array(384).fill(NaN), new Float32Array(0)]) {
      const viewer = await opened(embedder(async () => bad));
      await expect(viewer.search("Item")).resolves.toBeUndefined();
      const r = viewer.results;
      if (r && "groups" in r) expect(r.groups.map((g) => g.match)).not.toContain("vector");
      expect(viewer.status).toBe("ready");
    }
  });

  it("the same query twice gives the same view, vector results included", async () => {
    const viewer = await opened(embedder(async () => ones()));
    await viewer.search("zzzz");
    const first = JSON.stringify(viewer.results);
    await viewer.search("zzzz");
    expect(JSON.stringify(viewer.results)).toBe(first);
  });

  it("opening a mosaic whose model differs from the embedder's never calls the embedder", async () => {
    const e = embedder(async () => ones(), `${MODEL.name}@${"0".repeat(64)}`);
    const viewer = await opened(e);
    await viewer.search("zzzz");
    expect(e.queries).toEqual([]);
    expect(view(viewer.results).groups.every((g) => g.match !== "vector")).toBe(true);
  });

  it("an embedder that answers late for an earlier query does not replace the later query's results", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const e = embedder(async (q) => {
      if (q === "slow") await gate;
      return ones();
    });
    const viewer = await opened(e);
    const slow = viewer.search("slow");
    await viewer.search("Item");
    const fast = JSON.stringify(viewer.results);
    release();
    await slow;
    expect(JSON.stringify(viewer.results)).toBe(fast);
  });

  it("opening a second mosaic keeps using the viewer's embedder only where the model matches", async () => {
    const e = embedder(async () => ones());
    const viewer = await opened(e);
    await viewer.open(reading("tessera.tessera"), "tessera.tessera");
    expect(viewer.status).toBe("ready");
    await viewer.search("zzzz");
    expect(view(viewer.results).groups.every((g) => g.match !== "vector")).toBe(true);
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    await viewer.search("zzzz");
    expect(view(viewer.results).groups.map((g) => g.match)).toContain("vector");
  });
});
