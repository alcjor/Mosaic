import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { FileRefusedError, openFile } from "../src/index.js";

/** Databases the kit has opened and not yet closed, counted by wrapping SQLite's DB class. */
const live = vi.hoisted(() => ({ count: 0 }));

vi.mock("@sqlite.org/sqlite-wasm", async (importOriginal) => {
  const real = await importOriginal<typeof import("@sqlite.org/sqlite-wasm")>();
  const init = async () => {
    const s = await real.default();
    const Base = s.oo1.DB;
    class Counted extends Base {
      #open = true;
      constructor(...args: [filename?: string, flags?: string, vfs?: string]) {
        super(...args);
        live.count++;
      }
      override close(): void {
        if (this.#open) live.count--;
        this.#open = false;
        super.close();
      }
    }
    s.oo1.DB = Counted as unknown as typeof Base;
    return s;
  };
  return { ...real, default: init };
});

const read = (path: string): Uint8Array =>
  new Uint8Array(readFileSync(fileURLToPath(new URL(`../../conformance/${path}`, import.meta.url))));

describe("a refused or closed file leaves no database open (3.8 step 4: bounded resources)", () => {
  it("counts open databases, so these tests can see one left open", async () => {
    const file = await openFile(read("reading/mosaic.mosaic"), "mosaic.mosaic");
    expect(live.count).toBe(1);
    file.close();
    expect(live.count).toBe(0);
  });

  const refused = [
    "utf-16.mosaic",
    "not-sqlite.mosaic",
    "empty.mosaic",
    "application-id.mosaic",
    "user-version.mosaic",
    "format-version.mosaic",
    "schema-extra-table.mosaic",
    "no-header.mosaic",
  ];
  for (const name of refused) {
    it(`refuses ${name} and keeps no database open`, async () => {
      await expect(openFile(read(`reading/${name}`), name)).rejects.toBeInstanceOf(FileRefusedError);
      expect(live.count).toBe(0);
    });
  }

  it("refuses a truncated file and keeps no database open", async () => {
    const whole = read("reading/mosaic.mosaic");
    await expect(openFile(whole.slice(0, whole.length / 2), "cut.mosaic")).rejects.toBeInstanceOf(
      FileRefusedError,
    );
    expect(live.count).toBe(0);
  });
});
