// M3.8: a single-file export holds its mosaic, its view file's settings and SQLite's WebAssembly
// in one JSON element; the page reads them from the document and fetches nothing.
import { render } from "svelte/server";
import { describe, expect, it } from "vitest";
import App from "../src/App.svelte";
import { EXPORT_ID, parseExport, readExport } from "../src/lib/exported.js";
import { DEFAULT_VIEW } from "../src/lib/view.js";
import { reading } from "./fixtures.js";

import { gzipSync } from "node:zlib";

const b64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...gzipSync(bytes)));

describe("an export's data", () => {
  it("gives the mosaic's name and bytes, SQLite's WebAssembly and the view file's settings", async () => {
    const mosaic = reading("mosaic.mosaic");
    const found = await parseExport(JSON.stringify({ name: "m.mosaic", mosaic: b64(mosaic.slice(0, 4096)), sqlite: b64(new Uint8Array([0, 97, 115, 109])), view: { search: "text" } }));
    expect(found.name).toBe("m.mosaic");
    expect(found.mosaic).toEqual(mosaic.slice(0, 4096));
    expect(found.sqlite).toEqual(new Uint8Array([0, 97, 115, 109]));
    expect(found.view).toEqual({ ...DEFAULT_VIEW, search: "text" });
  });

  it("an export with search: semantic also gives the model's files and ONNX Runtime", async () => {
    const empty = b64(new Uint8Array());
    const text = (t: string) => b64(new TextEncoder().encode(t));
    const found = await parseExport(
      JSON.stringify({
        name: "m",
        mosaic: empty,
        sqlite: empty,
        view: { search: "semantic" },
        model: { model: text("onnx"), tokenizer: text("{}") },
        ort: { module: text("export const env = {};"), wasm: b64(new Uint8Array([0, 97, 115, 109])) },
      }),
    );
    expect(new TextDecoder().decode(found.model!.files.model)).toBe("onnx");
    expect(new TextDecoder().decode(found.model!.files.tokenizer)).toBe("{}");
    expect(new TextDecoder().decode(found.model!.ortModule)).toBe("export const env = {};");
    expect(found.model!.ortWasm).toEqual(new Uint8Array([0, 97, 115, 109]));
    const plain = await parseExport(JSON.stringify({ name: "m", mosaic: empty, sqlite: empty, view: {} }));
    expect(plain.model).toBeNull();
  });

  it.each([
    [JSON.stringify({ name: "m", mosaic: b64(new Uint8Array()), sqlite: b64(new Uint8Array()), view: {}, model: 3 }), /model must be an object/],
    ["not json", /not JSON/],
    ["[]", /must be an object/],
    [JSON.stringify({ name: "", mosaic: "", sqlite: "", view: {} }), /name/],
    [JSON.stringify({ name: "m", mosaic: "@@@", sqlite: "", view: {} }), /mosaic is not base64/],
    [JSON.stringify({ name: "m", mosaic: btoa("plain"), sqlite: "", view: {} }), /mosaic is not gzip-compressed/],
    [JSON.stringify({ name: "m", mosaic: b64(new Uint8Array()), sqlite: 3, view: {} }), /sqlite must be base64/],
    [JSON.stringify({ name: "m", mosaic: b64(new Uint8Array()), sqlite: b64(new Uint8Array()), view: { theme: "sepia" } }), /theme/],
  ])("malformed data %s is an error naming what is wrong", async (text, named) => {
    await expect(parseExport(text)).rejects.toThrow(named);
  });

  it("a page with no export element is not an export", async () => {
    expect(await readExport({ getElementById: () => null })).toBeNull();
    const empty = b64(new Uint8Array());
    const element = { textContent: JSON.stringify({ name: "m", mosaic: empty, sqlite: empty, view: {} }) };
    expect((await readExport({ getElementById: (id: string) => (id === EXPORT_ID ? (element as HTMLElement) : null) }))?.name).toBe("m");
  });

  it("an export says it is a read-only export; a page mosaic view serves does not", () => {
    expect(render(App, { props: { exported: true } }).body).toContain("Read-only export");
    expect(render(App, {}).body).not.toContain("Read-only export");
  });
});
