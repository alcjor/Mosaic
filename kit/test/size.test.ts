import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";

/** ADR-007: the bare kit (reader, tools, SQLite) is under 3 MB compressed, dependencies included. */
const BARE_KIT_BUDGET = 3 * 1024 * 1024;

const require = createRequire(import.meta.url);

describe("bare kit size (ADR-007)", () => {
  it("is under 3 MB compressed: the kit's code and the SQLite WebAssembly the page loads", () => {
    const src = fileURLToPath(new URL("../src/", import.meta.url));
    const sqlite = join(dirname(require.resolve("@sqlite.org/sqlite-wasm/package.json")), "dist");
    const files = [
      ...readdirSync(src).map((name) => join(src, name)),
      join(sqlite, "index.mjs"),
      join(sqlite, "sqlite3.wasm"),
    ];
    const sizes = files.map((path) => gzipSync(readFileSync(path), { level: 9 }).byteLength);
    const total = sizes.reduce((a, b) => a + b, 0);
    console.log(`bare kit: ${(total / 1024).toFixed(0)} KB compressed (${files.length} files)`);
    expect(total).toBeLessThan(BARE_KIT_BUDGET);
  });
});
