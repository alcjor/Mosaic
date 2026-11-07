// M3.8: a page that cannot fetch files (a single-file export opened from file://) gives the kit
// SQLite's WebAssembly as bytes before the first open. Run in a fresh module, so this file's
// SQLite is the first one loaded.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

const repo = (path: string): string => fileURLToPath(new URL(`../../${path}`, import.meta.url));

function sqliteWasm(): Uint8Array {
  const require = createRequire(import.meta.url);
  const entry = require.resolve("@sqlite.org/sqlite-wasm");
  return new Uint8Array(readFileSync(join(dirname(entry), "sqlite3.wasm")));
}

describe("useSqliteWasm", () => {
  it("opens files with SQLite loaded from the bytes given", async () => {
    vi.resetModules();
    const kit = await import("../src/index.js");
    kit.useSqliteWasm(sqliteWasm());
    const file = await kit.openFile(new Uint8Array(readFileSync(repo("conformance/reading/mosaic.mosaic"))), "mosaic.mosaic");
    expect(file.nodeTypes.map((t) => t.name)).toEqual(["Group", "Item"]);
    file.close();
  });

  it("cannot change SQLite once it is loaded", async () => {
    vi.resetModules();
    const kit = await import("../src/index.js");
    (await kit.openFile(new Uint8Array(readFileSync(repo("conformance/reading/mosaic.mosaic"))), "m.mosaic")).close();
    expect(() => kit.useSqliteWasm(sqliteWasm())).toThrow(/already loaded/);
  });

  it("bytes that are not WebAssembly fail the open, not silently", async () => {
    vi.resetModules();
    const kit = await import("../src/index.js");
    kit.useSqliteWasm(new Uint8Array([1, 2, 3]));
    await expect(kit.openFile(new Uint8Array(readFileSync(repo("conformance/reading/mosaic.mosaic"))), "m.mosaic")).rejects.toThrow();
  });
});
