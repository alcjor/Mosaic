// M2.12 (answer A on #117): the model reaches the page at runtime, from the address `mosaic view`
// gives it (`?model=<url>`), never from the viewer's build. With an embedder, `find` in the page
// lists vector matches; without one, names and full text only (section 3.8).
import type { QueryEmbedder } from "@mosaic/kit";
import { MODEL } from "@mosaic/kit";
import { describe, expect, it } from "vitest";
import { fetchNamedModel, MODEL_PARAM, type SearchView } from "../src/lib/mosaic.js";
import { Viewer } from "../src/lib/viewer.svelte.js";
import { reading } from "./fixtures.js";

/** The `embed_model` of conformance/reading/mosaic.mosaic, whose vectors are invented. */
const READING_MODEL = "invented-model@ca56847038f3f329524caec5a86e14865f49918d68094c90dd021a5e67b927f6";

function fixed(model: string): QueryEmbedder & { queries: string[] } {
  const queries: string[] = [];
  const v = new Float32Array(384).fill(1 / Math.sqrt(384));
  return {
    model,
    queries,
    async embedQuery(query: string) {
      queries.push(query);
      return v;
    },
  };
}

function fetcher(files: Record<string, Uint8Array>, seen: string[] = []): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input);
    seen.push(url);
    const body = files[url];
    return body === undefined ? new Response("not found", { status: 404, statusText: "Not Found" }) : new Response(body);
  }) as typeof fetch;
}

describe("fetchNamedModel", () => {
  const base = "http://127.0.0.1:8000/?mosaic=file%2Fm.mosaic&model=model%2F";
  const model = new Uint8Array([1, 2, 3]);
  const tokenizer = new Uint8Array([4, 5]);
  const files = {
    [`http://127.0.0.1:8000/model/${MODEL.modelFile.path}`]: model,
    [`http://127.0.0.1:8000/model/${MODEL.tokenizer.path}`]: tokenizer,
  };

  it("is null when the address names no model", async () => {
    const seen: string[] = [];
    expect(await fetchNamedModel("?mosaic=file%2Fm.mosaic", base, fetcher(files, seen))).toBeNull();
    expect(await fetchNamedModel(`?${MODEL_PARAM}=`, base, fetcher(files, seen))).toBeNull();
    expect(seen).toEqual([]);
  });

  it("fetches the model file and the tokenizer of section 6 under the named address", async () => {
    const got = await fetchNamedModel(new URL(base).search, base, fetcher(files));
    expect(got).not.toBeNull();
    expect([...got!.model]).toEqual([...model]);
    expect([...got!.tokenizer]).toEqual([...tokenizer]);
  });

  it("a file it cannot fetch is an error naming the file", async () => {
    const only = { [`http://127.0.0.1:8000/model/${MODEL.modelFile.path}`]: model };
    await expect(fetchNamedModel(new URL(base).search, base, fetcher(only))).rejects.toThrow(MODEL.tokenizer.path);
    const failing = (async () => {
      throw new TypeError("network down");
    }) as typeof fetch;
    await expect(fetchNamedModel(new URL(base).search, base, failing)).rejects.toThrow(/network down/);
  });
});

describe("Viewer with an embedder", () => {
  it("opens the mosaic with it, so find lists vector matches", async () => {
    const embedder = fixed(READING_MODEL);
    const viewer = new Viewer();
    viewer.embedder = embedder;
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    await viewer.search("something unnamed");
    const matches = (viewer.results as SearchView).groups.map((g) => g.match);
    expect(matches).toContain("vector");
    expect(embedder.queries).toEqual(["something unnamed"]);
  });

  it("without one, find lists no vector matches", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    await viewer.search("something unnamed");
    const results = viewer.results as SearchView;
    expect(results.groups.map((g) => g.match)).not.toContain("vector");
  });

  it("an embedder of another model is not used (section 3.8 fallback)", async () => {
    const embedder = fixed("other-model@" + "0".repeat(64));
    const viewer = new Viewer();
    viewer.embedder = embedder;
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    await viewer.search("Item");
    expect((viewer.results as SearchView).groups.map((g) => g.match)).not.toContain("vector");
    expect(embedder.queries).toEqual([]);
  });
});
