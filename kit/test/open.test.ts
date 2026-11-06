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
  encoding: "text encoding",
  application_id: "application_id",
  user_version: "user_version",
  format_version: "format version",
  schema: "schema",
  header: "header",
  knowledge_hash: "knowledge hash mismatch",
  vector_hash: "vector hash mismatch",
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
    expect(names.filter((n) => CASES[n]!.opens)).toEqual([
      "mosaic.mosaic",
      "non-ascii.mosaic",
      "stat4.mosaic",
      "tessera.tessera",
      "wal.mosaic",
    ]);
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

describe("conformance/invalid/files: the kit refuses the files that break 3.8 steps 2 and 3", () => {
  const invalid = JSON.parse(readFileSync(conformance("invalid/files/cases.json"), "utf8")) as Record<
    string,
    { rules: string[] }
  >;
  const step2: Record<string, { rule: RefusalRule; checker: string }> = {
    "container.tessera": { rule: "application_id", checker: "container" },
    "inv-1-no-header.tessera": { rule: "header", checker: "inv-1" },
    "inv-1-version.tessera": { rule: "format_version", checker: "inv-1" },
    "inv-6-hash.tessera": { rule: "knowledge_hash", checker: "inv-6" },
    "inv-14-vector-hash.mosaic": { rule: "vector_hash", checker: "inv-14" },
  };

  for (const [name, { rule, checker }] of Object.entries(step2)) {
    it(`refuses ${name} for ${rule}, as mosaic check does (${checker})`, async () => {
      expect(invalid[name]?.rules).toContain(checker);
      const error = await refusal(read(`invalid/files/${name}`), name);
      expect(error.rule).toBe(rule);
    });
  }
});

describe("SQLite header settings that section 3.8 step 2 does not check", () => {
  it("opens a file in WAL mode with no write-ahead log beside it, without changing its bytes", async () => {
    const bytes = read("reading/wal.mosaic");
    expect([bytes[18], bytes[19]]).toEqual([2, 2]);
    const before = bytes.slice();
    const file = await openFile(bytes, "wal.mosaic");
    expect({ ...file.header }).toEqual(CASES["mosaic.mosaic"]!.header);
    file.close();
    expect(bytes).toEqual(before);
  });

  it("refuses a file flagged UTF-16, naming the encoding (3.1, decision B on #104)", async () => {
    for (const [code, label] of [
      [2, "UTF-16le"],
      [3, "UTF-16be"],
    ] as const) {
      const bytes = read("reading/mosaic.mosaic");
      new DataView(bytes.buffer, bytes.byteOffset).setUint32(56, code);
      const error = await refusal(bytes, "utf16.mosaic");
      expect(error.rule).toBe("encoding");
      expect(error.message).toContain(`text encoding ${label}`);
    }
  });
});

describe("a crafted header (3.8 step 4, section 10)", () => {
  const COLUMNS =
    "format_version, kind, producer, settings, knowledge_hash, vector_hash, embed_model, pattern_hash, target, ai_model";

  /** mosaic.mosaic with `extra` more header rows: CHECK (one = 1) is not enforced on read. */
  async function withHeaderRows(extra: number): Promise<Uint8Array> {
    const s = await sqlite3InitModule();
    const bytes = read("reading/mosaic.mosaic");
    const db = new s.oo1.DB(":memory:", "c");
    try {
      const pointer = s.wasm.allocFromTypedArray(bytes);
      const flags = s.capi.SQLITE_DESERIALIZE_FREEONCLOSE | s.capi.SQLITE_DESERIALIZE_RESIZEABLE;
      expect(s.capi.sqlite3_deserialize(db, "main", pointer, bytes.length, bytes.length, flags)).toBe(0);
      db.exec("PRAGMA ignore_check_constraints = ON");
      db.exec(
        `WITH RECURSIVE n(i) AS (SELECT 2 UNION ALL SELECT i + 1 FROM n WHERE i < ${extra + 1}) ` +
          `INSERT INTO header SELECT n.i, ${COLUMNS} FROM n, (SELECT ${COLUMNS} FROM header WHERE one = 1)`,
      );
      expect(db.selectValue("SELECT count(*) FROM header")).toBe(extra + 1);
      return s.capi.sqlite3_js_db_export(db);
    } finally {
      db.close();
    }
  }

  it("refuses a header of 100,000 rows for header, saying it has 2 rows or more", async () => {
    const error = await refusal(await withHeaderRows(99_999), "rows.mosaic");
    expect(error.rule).toBe("header");
    expect(error.message).toContain("header has 2 rows or more");
  });

  it("says a header with no rows has 0 rows", async () => {
    const error = await refusal(read("reading/no-header.mosaic"), "no-header.mosaic");
    expect(error.message).toContain("header has 0 rows");
  });
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
