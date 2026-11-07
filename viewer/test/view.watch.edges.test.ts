// Edge cases of the page asking `mosaic view` for the view file's settings again (M3.7;
// docs/design.md, View file: "mosaic view watches it and reloads the page on save"; a file saved
// with an error keeps the page as it was and shows the error). Written from watchView's
// documented contract: `changed` on new settings, `failed(error)` while they cannot be read,
// `failed(null)` once they can again, a stop function, nothing watched without `?view=`.
import { describe, expect, it, vi } from "vitest";
import { watchView, type ViewSettings } from "../src/lib/view.js";

const BASE = "http://127.0.0.1:8000/?mosaic=file/a.mosaic&view=view.json";
const SEARCH = new URL(BASE).search;

const ok = (json: object) => new Response(JSON.stringify(json), { status: 200, headers: { "content-type": "application/json" } });

function answering(...answers: (() => Response | Promise<Response>)[]): typeof fetch {
  let i = 0;
  return vi.fn(async () => answers[Math.min(i++, answers.length - 1)]!()) as unknown as typeof fetch;
}

async function until(done: () => boolean): Promise<void> {
  for (let i = 0; i < 400 && !done(); i++) await new Promise((r) => setTimeout(r, 5));
  expect(done()).toBe(true);
}

describe("watching the view file's settings: answers that are not settings", () => {
  it.each([
    ["an HTML error page with status 500", () => new Response("<html>oops</html>", { status: 500 })],
    ["a 404", () => new Response("not found", { status: 404 })],
    ["a 200 that is not JSON", () => new Response("<html></html>", { status: 200 })],
    ["a 200 with an empty body", () => new Response("", { status: 200 })],
    ["settings with a wrong value", () => ok({ theme: "sepia" })],
    ["a JSON array", () => ok([] as unknown as object)],
  ])("%s is an error, keeps the page's settings, and the next good answer recovers", async (_name, broken) => {
    const fetcher = answering(() => ok({ search: "text" }), broken, broken, () => ok({ search: "semantic" }));
    const seen: ViewSettings[] = [];
    const errors: (string | null)[] = [];
    const stop = watchView(SEARCH, BASE, (v) => seen.push(v), (e) => errors.push(e), { fetcher, everyMs: 2 });
    await until(() => seen.length === 2);
    stop();
    expect(seen.map((v) => v.search)).toEqual(["text", "semantic"]);
    expect(typeof errors[0]).toBe("string");
    expect(errors[0]).not.toBe("");
    expect(errors.at(-1)).toBeNull();
  });
});

describe("watching the view file's settings: timing", () => {
  it("a stop while an answer is still on its way reports nothing afterwards", async () => {
    let release: (r: Response) => void = () => {};
    const slow = new Promise<Response>((resolve) => (release = resolve));
    const fetcher = answering(() => slow);
    const seen: ViewSettings[] = [];
    const errors: (string | null)[] = [];
    const stop = watchView(SEARCH, BASE, (v) => seen.push(v), (e) => errors.push(e), { fetcher, everyMs: 2 });
    await until(() => vi.mocked(fetcher).mock.calls.length === 1);
    stop();
    release(ok({ search: "text" }));
    await new Promise((r) => setTimeout(r, 30));
    expect(seen).toEqual([]);
    expect(errors).toEqual([]);
    expect(vi.mocked(fetcher).mock.calls.length).toBe(1);
  });

  it("a slow answer is not overlapped by another request", async () => {
    let inFlight = 0;
    let most = 0;
    const fetcher = vi.fn(async () => {
      inFlight++;
      most = Math.max(most, inFlight);
      await new Promise((r) => setTimeout(r, 15));
      inFlight--;
      return ok({ search: "text" });
    }) as unknown as typeof fetch;
    const stop = watchView(SEARCH, BASE, () => {}, () => {}, { fetcher, everyMs: 1 });
    await new Promise((r) => setTimeout(r, 80));
    stop();
    expect(most).toBe(1);
  });

  it("the same error twice is not a change, and settings that come back to an earlier value are", async () => {
    const fetcher = answering(
      () => ok({ search: "text" }),
      () => ok({ search: "semantic" }),
      () => ok({ search: "text" }),
    );
    const seen: string[] = [];
    const stop = watchView(SEARCH, BASE, (v) => seen.push(v.search), () => {}, { fetcher, everyMs: 2 });
    await until(() => seen.length === 3);
    stop();
    expect(seen).toEqual(["text", "semantic", "text"]);
  });

  it("keeps asking after a failure, so a mosaic view restarted on the same address is found again", async () => {
    const fetcher = answering(
      () => {
        throw new TypeError("Failed to fetch");
      },
      () => ok({ search: "text" }),
    );
    const seen: ViewSettings[] = [];
    const errors: (string | null)[] = [];
    const stop = watchView(SEARCH, BASE, (v) => seen.push(v), (e) => errors.push(e), { fetcher, everyMs: 2 });
    await until(() => seen.length === 1);
    stop();
    expect(errors[0]).not.toBeNull();
    expect(errors.at(-1)).toBeNull();
  });
});

describe("watching the view file's settings: the address", () => {
  it.each([["?view="], ["?mosaic=file/a.mosaic"], [""]])("%j names no view file: nothing is asked", (search) => {
    const fetcher = answering(() => ok({}));
    const stop = watchView(search, BASE, () => {}, () => {}, { fetcher, everyMs: 2 });
    stop();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("the settings address is resolved against the page, not against the mosaic's", async () => {
    const fetcher = answering(() => ok({}));
    const base = "http://127.0.0.1:9/deep/?mosaic=file/a.mosaic&view=view.json";
    const stop = watchView(new URL(base).search, base, () => {}, () => {}, { fetcher, everyMs: 50 });
    await until(() => vi.mocked(fetcher).mock.calls.length >= 1);
    stop();
    expect(String(vi.mocked(fetcher).mock.calls[0]![0])).toBe("http://127.0.0.1:9/deep/view.json");
  });
});
