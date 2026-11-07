// M3.7: under `mosaic view --view FILE` the page asks for the view file's settings again every
// second and is reshaped when they change; a file saved with an error answers that error, which
// the page shows while it keeps what it shows (docs/design.md, View file: "mosaic view watches
// it and reloads the page on save").
import { describe, expect, it, vi } from "vitest";
import { fetchNamedView, watchView, type ViewSettings } from "../src/lib/view.js";
import { Viewer } from "../src/lib/viewer.svelte.js";
import { reading } from "./fixtures.js";

const BASE = "http://127.0.0.1:8000/?mosaic=file/a.mosaic&view=view.json";
const SEARCH = new URL(BASE).search;

const ok = (json: object) => new Response(JSON.stringify(json), { status: 200, headers: { "content-type": "application/json" } });
const bad = (error: string) => new Response(JSON.stringify({ error }), { status: 422 });

/** A fetcher that answers each call with the next of `answers`, the last one from then on. */
function answering(...answers: (() => Response)[]): typeof fetch {
  let i = 0;
  return vi.fn(async () => answers[Math.min(i++, answers.length - 1)]!()) as unknown as typeof fetch;
}

async function until(done: () => boolean): Promise<void> {
  for (let i = 0; i < 400 && !done(); i++) await new Promise((r) => setTimeout(r, 5));
  expect(done()).toBe(true);
}

describe("the view file's settings from mosaic view", () => {
  it("an answer with an error is that error, as mosaic view names it", async () => {
    const fetcher = answering(() => bad("view.yaml:2: view file: theme must be one of auto, light, dark, not 'sepia'"));
    await expect(fetchNamedView(SEARCH, BASE, fetcher)).rejects.toThrow("view.yaml:2: view file: theme must be one of auto, light, dark, not 'sepia'");
  });

  it("are asked for again, and a change reshapes the page", async () => {
    const fetcher = answering(
      () => ok({ search: "semantic" }),
      () => ok({ search: "semantic" }),
      () => ok({ search: "text" }),
    );
    const seen: ViewSettings[] = [];
    const stop = watchView(SEARCH, BASE, (v) => seen.push(v), () => {}, { fetcher, everyMs: 5 });
    await until(() => seen.length === 2);
    stop();
    expect(seen.map((v) => v.search)).toEqual(["semantic", "text"]);
    expect(String(vi.mocked(fetcher).mock.calls[0]![0])).toBe("http://127.0.0.1:8000/view.json");
  });

  it("settings saved with an error are reported and change nothing; fixed, they clear the error", async () => {
    const fetcher = answering(
      () => ok({ theme: "dark" }),
      () => bad("view.yaml:1: view file: theme must be one of auto, light, dark, not 'sepia'"),
      () => bad("view.yaml:1: view file: theme must be one of auto, light, dark, not 'sepia'"),
      () => ok({ theme: "light" }),
    );
    const seen: string[] = [];
    const errors: (string | null)[] = [];
    const stop = watchView(SEARCH, BASE, (v) => seen.push(v.theme), (e) => errors.push(e), { fetcher, everyMs: 5 });
    await until(() => seen.length === 2);
    stop();
    expect(seen).toEqual(["dark", "light"]);
    expect(errors[0]).toMatch(/view\.yaml:1: view file: theme/);
    expect(errors.at(-1)).toBeNull();
    expect(errors.filter((e) => e === null)).toHaveLength(1);
  });

  it("a view file that cannot be fetched (mosaic view stopped) is an error, and the page keeps its settings", async () => {
    const fetcher = answering(
      () => ok({ search: "text" }),
      () => {
        throw new TypeError("Failed to fetch");
      },
    );
    const seen: ViewSettings[] = [];
    const errors: (string | null)[] = [];
    const stop = watchView(SEARCH, BASE, (v) => seen.push(v), (e) => errors.push(e), { fetcher, everyMs: 5 });
    await until(() => errors.length > 0);
    stop();
    expect(seen).toHaveLength(1);
    expect(errors[0]).toMatch(/could not fetch the view file's settings/);
  });

  it("without ?view= nothing is watched", () => {
    const fetcher = answering(() => ok({}));
    const stop = watchView("?mosaic=file/a.mosaic", BASE, () => {}, () => {}, { fetcher, everyMs: 5 });
    stop();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("stopping stops the asking", async () => {
    const fetcher = answering(() => ok({}));
    const stop = watchView(SEARCH, BASE, () => {}, () => {}, { fetcher, everyMs: 5 });
    await until(() => vi.mocked(fetcher).mock.calls.length >= 1);
    stop();
    const calls = vi.mocked(fetcher).mock.calls.length;
    await new Promise((r) => setTimeout(r, 40));
    expect(vi.mocked(fetcher).mock.calls.length).toBeLessThanOrEqual(calls + 1);
  });
});

describe("switching the search mode", () => {
  it("when the mosaic cannot be opened again, the mode stays as the file searches", async () => {
    const viewer = new Viewer();
    await viewer.open(reading("mosaic.mosaic"), "mosaic.mosaic");
    const file = viewer.file;
    const open = vi.spyOn(viewer, "open").mockImplementation(async () => {
      viewer.error = "could not open";
    });
    await viewer.setMode("text");
    expect(open).toHaveBeenCalled();
    expect(viewer.file).toBe(file);
    expect(viewer.mode).toBe("semantic");
  });
});
