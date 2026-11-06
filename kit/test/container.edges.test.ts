// Edge cases for M2.1 after the maintainer's answers on #104, written from the spec's words:
//   B: a tessera or mosaic stores its text as UTF-8; every reader refuses a UTF-16 file (3.1).
//   C: `sqlite_stat4` may be present, as `sqlite_stat1` may (3.1).
// Also the shape of the `search` virtual table (3.1: "with the same definitions") and
// headers whose values have the wrong storage type (3.3). Files are made here with SQLite
// WebAssembly from the conformance files, so each differs from a valid file in one thing.
import sqlite3InitModule from "@sqlite.org/sqlite-wasm";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { FileRefusedError, REFUSAL_RULES, openFile, type RefusalRule } from "../src/index.js";

const repo = (path: string): string =>
  fileURLToPath(new URL(`../../${path}`, import.meta.url));

const read = (path: string): Uint8Array =>
  new Uint8Array(readFileSync(repo(`conformance/${path}`)));

const MOSAIC = "reading/mosaic.mosaic";
const TESSERA = "reading/tessera.tessera";
const STAT4 = "CREATE TABLE sqlite_stat4(tbl,idx,neq,nlt,ndlt,sample)";

/** Edit a copy of `path` with SQL (checks off, schema writable) and return the new bytes. */
async function mutate(path: string, ...statements: string[]): Promise<Uint8Array> {
  return mutateBytes(read(path), ...statements);
}

async function mutateBytes(bytes: Uint8Array, ...statements: string[]): Promise<Uint8Array> {
  const sqlite3 = await sqlite3InitModule();
  const db = new sqlite3.oo1.DB(":memory:", "c");
  try {
    const p = sqlite3.wasm.allocFromTypedArray(bytes);
    const rc = sqlite3.capi.sqlite3_deserialize(
      db.pointer!,
      "main",
      p,
      bytes.length,
      bytes.length,
      sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE | sqlite3.capi.SQLITE_DESERIALIZE_RESIZEABLE,
    );
    if (rc !== 0) throw new Error(`deserialize failed: ${rc}`);
    db.exec("PRAGMA ignore_check_constraints = 1");
    db.exec("PRAGMA foreign_keys = 0");
    for (const sql of statements) db.exec(sql);
    return new Uint8Array(sqlite3.capi.sqlite3_js_db_export(db.pointer!));
  } finally {
    db.close();
  }
}

/** SQL that adds `sqlite_stat4` as SQLite declares it (the `sqlite_` prefix is reserved). */
const addStat4 = (): string[] => [
  STAT4.replace("sqlite_stat4", "stat4_placeholder"),
  "PRAGMA writable_schema = 1",
  `UPDATE sqlite_schema SET name = 'sqlite_stat4', tbl_name = 'sqlite_stat4', sql = '${STAT4}' WHERE name = 'stat4_placeholder'`,
  "PRAGMA writable_schema = 0",
];

/**
 * The knowledge hash of a tessera holding nothing but its header (section 3.6): every part is
 * its heading alone, the header part its one row. Since M2.2 the kit checks it on open.
 */
const EMPTY_TESSERA_HASH = createHash("sha256")
  .update(
    "#header\n'0.1','tessera'\n" +
      ["source", "type", "node", "edge", "alias", "evidence", "snippet", "mention", "source_text", "external_ref"]
        .map((part) => `#${part}\n`)
        .join(""),
  )
  .digest("hex");

/** A file built from `spec/format.sql` as it is (UTF-8), with a header row. */
async function fromFormatSql(): Promise<Uint8Array> {
  const sqlite3 = await sqlite3InitModule();
  const db = new sqlite3.oo1.DB(":memory:", "c");
  try {
    db.exec(readFileSync(repo("spec/format.sql"), "utf8"));
    db.exec(
      `INSERT INTO header (one, format_version, kind, producer, knowledge_hash)
       VALUES (1, '0.1', 'tessera', 'tool/1', '${EMPTY_TESSERA_HASH}')`,
    );
    return new Uint8Array(sqlite3.capi.sqlite3_js_db_export(db.pointer!));
  } finally {
    db.close();
  }
}

async function refusal(bytes: Uint8Array, name: string): Promise<FileRefusedError> {
  try {
    (await openFile(bytes, name)).close();
  } catch (e) {
    expect(e).toBeInstanceOf(FileRefusedError);
    return e as FileRefusedError;
  }
  throw new Error(`${name} opened, but it must be refused`);
}

async function expectRule(bytes: Uint8Array, name: string, rule: RefusalRule): Promise<void> {
  const error = await refusal(bytes, name);
  expect(error.rule).toBe(rule);
  expect(error.file).toBe(name);
  expect(error.message.startsWith(`${name}: `)).toBe(true);
}

async function opensAs(bytes: Uint8Array, name: string, kind: string): Promise<void> {
  const file = await openFile(bytes, name);
  try {
    expect(file.header.kind).toBe(kind);
  } finally {
    file.close();
  }
}

describe("text is stored as UTF-8 (3.1, decision B on #104)", () => {
  it("opens a file built from format.sql whose text is UTF-8 (control)", async () => {
    await opensAs(await fromFormatSql(), "u8.tessera", "tessera");
  });

  it("refuses a mosaic whose encoding flag says UTF-16be, for encoding", async () => {
    const bytes = read(MOSAIC);
    bytes[59] = 3;
    await expectRule(bytes, "be.mosaic", "encoding");
  });

  it("refuses the UTF-16 conformance mosaic the same way on every try", async () => {
    const first = await refusal(read("reading/utf-16.mosaic"), "u16.mosaic");
    const second = await refusal(read("reading/utf-16.mosaic"), "u16.mosaic");
    expect(first.rule).toBe("encoding");
    expect(second.message).toBe(first.message);
  });

  it("names the encoding it found in the error", async () => {
    const error = await refusal(read("reading/utf-16.mosaic"), "u16.mosaic");
    expect(error.message).toMatch(/UTF-16/i);
  });

  it("refuses UTF-16 for encoding even when the file is a tessera carrying only the flag", async () => {
    const bytes = read(TESSERA);
    bytes[59] = 2; // UTF-16le
    await expectRule(bytes, "flag.tessera", "encoding");
  });
});

describe("sqlite_stat4 may be present (3.1, decision C on #104)", () => {
  it("opens a mosaic holding sqlite_stat4 and returns the same header as without it", async () => {
    const bytes = await mutate(MOSAIC, ...addStat4());
    const file = await openFile(bytes, "s4.mosaic");
    try {
      const plain = await openFile(read(MOSAIC), "plain.mosaic");
      try {
        expect({ ...file.header }).toEqual({ ...plain.header });
      } finally {
        plain.close();
      }
    } finally {
      file.close();
    }
  });

  it("opens a tessera holding sqlite_stat4", async () => {
    await opensAs(await mutate(TESSERA, ...addStat4()), "s4.tessera", "tessera");
  });

  it("opens a tessera holding sqlite_stat1 and sqlite_stat4 together", async () => {
    await opensAs(await mutate(TESSERA, "ANALYZE", ...addStat4()), "s14.tessera", "tessera");
  });

  it("opens a mosaic whose sqlite_stat4 has rows that no statistics would give", async () => {
    // The table is declared in one pass and filled in a second, once SQLite has reread the schema.
    const declared = await mutate(MOSAIC, ...addStat4());
    const bytes = await mutateBytes(
      declared,
      "INSERT INTO sqlite_stat4 VALUES ('node', 'nothing', 'x y z', '1', '2', x'00ff')",
      "INSERT INTO sqlite_stat4 VALUES (NULL, NULL, NULL, NULL, NULL, NULL)",
      "INSERT INTO sqlite_stat4 VALUES ('no_such_table', 'no_such_index', '9999999999 1', '', '', zeroblob(5000))",
    );
    // Statistics are not knowledge, and are not read as knowledge: the file still opens.
    await opensAs(bytes, "s4junk.mosaic", "mosaic");
  });

  it("opens a file whose sqlite_stat1 holds garbage rows", async () => {
    const bytes = await mutate(
      MOSAIC,
      "ANALYZE",
      "INSERT INTO sqlite_stat1 VALUES ('node', 'zz', 'not numbers')",
      "INSERT INTO sqlite_stat1 VALUES ('ghost', NULL, '-5 -5')",
    );
    await opensAs(bytes, "s1junk.mosaic", "mosaic");
  });

  it("still refuses a file that holds sqlite_stat4 and a table format.sql does not define", async () => {
    const bytes = await mutate(MOSAIC, ...addStat4(), "CREATE TABLE extra (x)");
    await expectRule(bytes, "s4extra.mosaic", "schema");
  });

  it("still refuses a file that holds sqlite_stat4 and a wrong user_version, for user_version", async () => {
    const bytes = await mutate(MOSAIC, ...addStat4(), "PRAGMA user_version = 2");
    await expectRule(bytes, "s4uv.mosaic", "user_version");
  });

  it("still refuses a file that holds sqlite_stat4 and a dropped index", async () => {
    const bytes = await mutate(MOSAIC, ...addStat4(), "DROP INDEX edge_in");
    await expectRule(bytes, "s4idx.mosaic", "schema");
  });

  it("does not take a user table named like a statistics table for one", async () => {
    // `stat4_placeholder` is not an SQLite internal table: it stays an extra table.
    const bytes = await mutate(MOSAIC, STAT4.replace("sqlite_stat4", "stat4_placeholder"));
    await expectRule(bytes, "lookalike.mosaic", "schema");
  });

  it("does not take a table named sqlite_stat41 for one of SQLite's statistics tables", async () => {
    const bytes = await mutate(
      MOSAIC,
      "CREATE TABLE stat_x (tbl,idx,neq,nlt,ndlt,sample)",
      "PRAGMA writable_schema = 1",
      "UPDATE sqlite_schema SET name = 'sqlite_stat41', tbl_name = 'sqlite_stat41', sql = 'CREATE TABLE sqlite_stat41(tbl,idx,neq,nlt,ndlt,sample)' WHERE name = 'stat_x'",
      "PRAGMA writable_schema = 0",
    );
    await expectRule(bytes, "stat41.mosaic", "schema");
  });
});

describe("the search virtual table has format.sql's definition (3.1)", () => {
  const search = (definition: string): string[] => [
    "DROP TABLE search",
    `CREATE VIRTUAL TABLE search USING fts5 (${definition})`,
  ];
  const cases: Record<string, string[]> = {
    "another tokenizer": search(
      `label, aliases, summary, snippets, content = '', tokenize = "unicode61"`,
    ),
    "the porter tokenizer": search(
      `label, aliases, summary, snippets, content = '', tokenize = "porter unicode61 tokenchars '-_.'"`,
    ),
    "other token characters": search(
      `label, aliases, summary, snippets, content = '', tokenize = "unicode61 tokenchars '-_'"`,
    ),
    "stored content": search(
      `label, aliases, summary, snippets, tokenize = "unicode61 tokenchars '-_.'"`,
    ),
    "columns in another order": search(
      `aliases, label, summary, snippets, content = '', tokenize = "unicode61 tokenchars '-_.'"`,
    ),
    "a column fewer": search(
      `label, aliases, summary, content = '', tokenize = "unicode61 tokenchars '-_.'"`,
    ),
    "a column more": search(
      `label, aliases, summary, snippets, extra, content = '', tokenize = "unicode61 tokenchars '-_.'"`,
    ),
    "a prefix index": search(
      `label, aliases, summary, snippets, content = '', prefix = '2', tokenize = "unicode61 tokenchars '-_.'"`,
    ),
    "no positions": search(
      `label, aliases, summary, snippets, content = '', detail = 'column', tokenize = "unicode61 tokenchars '-_.'"`,
    ),
  };
  for (const [what, sql] of Object.entries(cases)) {
    it(`refuses ${what}, for schema`, async () => {
      await expectRule(await mutate(MOSAIC, ...sql), "search.mosaic", "schema");
    });
  }

  it("refuses an fts5vocab table beside search", async () => {
    const bytes = await mutate(MOSAIC, "CREATE VIRTUAL TABLE vocab USING fts5vocab(search, 'row')");
    await expectRule(bytes, "vocab.mosaic", "schema");
  });

  it("refuses a table named like a shadow table of search that SQLite did not make", async () => {
    const bytes = await mutate(MOSAIC, "CREATE TABLE search_extra (x)");
    await expectRule(bytes, "shadow.mosaic", "schema");
  });

  it("refuses a missing search table", async () => {
    await expectRule(await mutate(MOSAIC, "DROP TABLE search"), "nosearch.mosaic", "schema");
  });

  it("opens the conformance files, whose search table has its shadow tables", async () => {
    await opensAs(read(MOSAIC), "m.mosaic", "mosaic");
    await opensAs(read(TESSERA), "t.tessera", "tessera");
  });
});

describe("a header value stored as the wrong type is not the value it looks like (3.3)", () => {
  it("refuses a kind stored as a blob that spells tessera", async () => {
    const bytes = await mutate(TESSERA, "UPDATE header SET kind = CAST('tessera' AS BLOB)");
    const error = await refusal(bytes, "blobkind.tessera");
    expect(REFUSAL_RULES).toContain(error.rule);
  });

  it("refuses a format_version stored as a blob that spells 0.1", async () => {
    const bytes = await mutate(TESSERA, "UPDATE header SET format_version = CAST('0.1' AS BLOB)");
    const error = await refusal(bytes, "blobversion.tessera");
    expect(REFUSAL_RULES).toContain(error.rule);
  });
});
