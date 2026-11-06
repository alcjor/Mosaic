import sqlite3InitModule from "@sqlite.org/sqlite-wasm";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { FORMAT_SQL } from "../src/format-sql.js";
import { FileRefusedError, REFUSAL_RULES, openFile, type RefusalRule } from "../src/index.js";

const conformance = (path: string): string =>
  fileURLToPath(new URL(`../../conformance/${path}`, import.meta.url));

const read = (path: string): Uint8Array => new Uint8Array(readFileSync(conformance(path)));

interface ReadingCase {
  opens: boolean;
  rule: RefusalRule | null;
  header?: Record<string, unknown>;
}

const CASES = JSON.parse(readFileSync(conformance("reading/cases.json"), "utf8")) as Record<
  string,
  ReadingCase
>;

/** What the error message names for each rule, so a person can tell what failed. */
const NAMES: Record<RefusalRule, string> = {
  sqlite: "SQLite",
  application_id: "application_id",
  user_version: "user_version",
  format_version: "format version",
  schema: "schema",
  header: "header",
};

async function refusal(bytes: Uint8Array, name: string): Promise<FileRefusedError> {
  try {
    (await openFile(bytes, name)).close();
  } catch (e) {
    expect(e).toBeInstanceOf(FileRefusedError);
    return e as FileRefusedError;
  }
  throw new Error(`${name} opened, but it must be refused`);
}

describe("conformance/reading: the kit opens or refuses each file as cases.json says (3.8)", () => {
  const names = Object.keys(CASES).sort();

  it("covers every refusal rule and both kinds of file", () => {
    const rules = new Set(Object.values(CASES).map((c) => c.rule));
    expect([...rules].filter((r) => r !== null).sort()).toEqual([...REFUSAL_RULES].sort());
    expect(names.filter((n) => CASES[n]!.opens)).toEqual(["mosaic.mosaic", "tessera.tessera"]);
  });

  for (const name of names) {
    const c = CASES[name]!;
    if (c.opens) {
      it(`opens ${name} and returns its header (3.3)`, async () => {
        const file = await openFile(read(`reading/${name}`), name);
        try {
          expect(file.name).toBe(name);
          expect({ ...file.header }).toEqual(c.header);
        } finally {
          file.close();
        }
      });
    } else {
      it(`refuses ${name} for ${c.rule}, naming the file and what failed`, async () => {
        const error = await refusal(read(`reading/${name}`), name);
        expect(error.rule).toBe(c.rule);
        expect(error.file).toBe(name);
        expect(error.message.startsWith(`${name}: `)).toBe(true);
        expect(error.message).toContain(NAMES[c.rule!]);
      });
    }
  }
});

describe("conformance/invalid/files: the kit refuses the files that break 3.8 step 2", () => {
  const invalid = JSON.parse(readFileSync(conformance("invalid/files/cases.json"), "utf8")) as Record<
    string,
    { rules: string[] }
  >;
  const step2: Record<string, { rule: RefusalRule; checker: string }> = {
    "container.tessera": { rule: "application_id", checker: "container" },
    "inv-1-no-header.tessera": { rule: "header", checker: "inv-1" },
    "inv-1-version.tessera": { rule: "format_version", checker: "inv-1" },
  };

  for (const [name, { rule, checker }] of Object.entries(step2)) {
    it(`refuses ${name} for ${rule}, as mosaic check does (${checker})`, async () => {
      expect(invalid[name]?.rules).toContain(checker);
      const error = await refusal(read(`invalid/files/${name}`), name);
      expect(error.rule).toBe(rule);
    });
  }
});

describe("opening is read-only (3.8 step 1)", () => {
  it("leaves the given bytes as they were and opens them again the same way", async () => {
    const bytes = read("reading/mosaic.mosaic");
    const before = bytes.slice();
    const first = await openFile(bytes, "mosaic.mosaic");
    const header = { ...first.header };
    first.close();
    expect(bytes).toEqual(before);
    const second = await openFile(bytes, "mosaic.mosaic");
    expect({ ...second.header }).toEqual(header);
    second.close();
    expect(bytes).toEqual(before);
  });

  it("gives a header that cannot be changed", async () => {
    const file = await openFile(read("reading/tessera.tessera"), "tessera.tessera");
    try {
      expect(Object.isFrozen(file.header)).toBe(true);
    } finally {
      file.close();
    }
  });

  it("keeps its header after it is closed, and closing twice is harmless", async () => {
    const file = await openFile(read("reading/tessera.tessera"), "tessera.tessera");
    file.close();
    expect(file.header.kind).toBe("tessera");
    expect(() => file.close()).not.toThrow();
  });
});

describe("the schema the kit compares against (3.1)", () => {
  const spec = readFileSync(fileURLToPath(new URL("../../spec/format.sql", import.meta.url)), "utf8");

  it("is spec/format.sql without the comment lines between statements", () => {
    const lines = spec.split("\n");
    expect(FORMAT_SQL).toBe(lines.filter((line) => !line.startsWith("--")).join("\n"));
  });

  it("makes the same sqlite_schema as spec/format.sql", async () => {
    const sqlite3 = await sqlite3InitModule();
    const schema = (sql: string) => {
      const db = new sqlite3.oo1.DB(":memory:", "c");
      try {
        db.exec(sql);
        return db.selectArrays("SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name");
      } finally {
        db.close();
      }
    };
    expect(schema(FORMAT_SQL)).toEqual(schema(spec));
  });
});
