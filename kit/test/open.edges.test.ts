// Edge cases for M2.1 (kit opens a mosaic by the reading rules, 3.8 steps 1, 2 and 4),
// written from the spec's words. Mutated files are made here from the conformance files
// with SQLite WebAssembly, so each breaks one thing.
import sqlite3InitModule from "@sqlite.org/sqlite-wasm";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  FileRefusedError,
  IMPLEMENTED_VERSIONS,
  REFUSAL_RULES,
  openFile,
  type RefusalRule,
} from "../src/index.js";

const conformance = (path: string): string =>
  fileURLToPath(new URL(`../../conformance/${path}`, import.meta.url));

const read = (path: string): Uint8Array => new Uint8Array(readFileSync(conformance(path)));

const MOSAIC = "reading/mosaic.mosaic";
const TESSERA = "reading/tessera.tessera";

/** Edit a copy of `path` with SQL (checks off, schema writable) and return the new bytes. */
async function mutate(path: string, ...statements: string[]): Promise<Uint8Array> {
  const sqlite3 = await sqlite3InitModule();
  const bytes = read(path);
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

/** Opens, or is refused cleanly; any other failure is a bug (3.8 step 4: untrusted input). */
async function opensOrRefused(bytes: Uint8Array, name: string): Promise<"opened" | "refused"> {
  try {
    (await openFile(bytes, name)).close();
    return "opened";
  } catch (e) {
    expect(e, `${name}: ${String(e)}`).toBeInstanceOf(FileRefusedError);
    expect(REFUSAL_RULES).toContain((e as FileRefusedError).rule);
    return "refused";
  }
}

describe("versions (3.3, 9)", () => {
  it("implements exactly format 0.1", () => {
    expect([...IMPLEMENTED_VERSIONS]).toEqual(["0.1"]);
  });

  for (const version of ["0.2", "0.10", "0.0", "1.0", "0.1.1", "2.0", "0.11"]) {
    it(`refuses format_version ${version} for its version (9: only 0.1 is implemented)`, async () => {
      const bytes = await mutate(TESSERA, `UPDATE header SET format_version = '${version}'`);
      await expectRule(bytes, "v.tessera", "format_version");
    });
  }

  it("refuses a newer minor version of a mosaic even when its schema is also changed (9: cannot check)", async () => {
    const bytes = await mutate(
      MOSAIC,
      "UPDATE header SET format_version = '0.2'",
      "CREATE TABLE added_in_0_2 (x INTEGER)",
    );
    await expectRule(bytes, "future.mosaic", "format_version");
  });
});

describe("application_id and user_version (3.1, 3.8 step 2)", () => {
  it("refuses application_id that differs from MOSA by one bit", async () => {
    const bytes = await mutate(TESSERA, `PRAGMA application_id = ${0x4d4f5341 ^ 1}`);
    await expectRule(bytes, "app.tessera", "application_id");
  });

  it("refuses application_id that is negative", async () => {
    const bytes = await mutate(TESSERA, "PRAGMA application_id = -1");
    await expectRule(bytes, "app.tessera", "application_id");
  });

  for (const v of [0, 2, -1, 256]) {
    it(`refuses user_version ${v}`, async () => {
      const bytes = await mutate(MOSAIC, `PRAGMA user_version = ${v}`);
      await expectRule(bytes, "uv.mosaic", "user_version");
    });
  }

  it("refuses a file whose application_id and user_version are both wrong, for one of the two", async () => {
    const bytes = await mutate(TESSERA, "PRAGMA application_id = 5", "PRAGMA user_version = 9");
    const error = await refusal(bytes, "both.tessera");
    expect(["application_id", "user_version"]).toContain(error.rule);
    expect(error.message).toMatch(/application_id|user_version/);
  });
});

describe("the schema is exactly 3.1's (3.8 step 2)", () => {
  const cases: Record<string, string[]> = {
    "an added trigger": [
      "CREATE TRIGGER sneaky AFTER INSERT ON alias BEGIN SELECT 1; END",
    ],
    "an added view": ["CREATE VIEW v_extra AS SELECT id FROM node"],
    "an added index": ["CREATE INDEX node_label ON node (label)"],
    "an added table": ["CREATE TABLE extra (x)"],
    "a dropped table": ["DROP TABLE external_ref"],
    "a dropped view": ["DROP VIEW v_node"],
    "a view with a different definition": [
      "DROP VIEW v_node",
      "CREATE VIEW v_node AS SELECT id, type FROM node",
    ],
    "a CHECK constraint that differs": [
      "PRAGMA writable_schema = 1",
      "UPDATE sqlite_schema SET sql = replace(sql, 'count > 0', 'count > 1') WHERE name = 'link_count'",
    ],
    "a different index definition": [
      "DROP INDEX edge_in",
      "CREATE INDEX edge_in ON edge (type, dst)",
    ],
    "an added column on a data table": ["ALTER TABLE node ADD COLUMN extra TEXT"],
  };
  for (const [what, sql] of Object.entries(cases)) {
    it(`refuses ${what} in a mosaic`, async () => {
      const bytes = await mutate(MOSAIC, ...sql);
      await expectRule(bytes, "schema.mosaic", "schema");
    });
  }

  it("refuses an added trigger in a tessera too", async () => {
    const bytes = await mutate(TESSERA, "CREATE TRIGGER t AFTER INSERT ON node BEGIN SELECT 1; END");
    await expectRule(bytes, "schema.tessera", "schema");
  });

  it("opens a file that holds sqlite_stat1, which format.sql allows", async () => {
    const bytes = await mutate(MOSAIC, "ANALYZE");
    const file = await openFile(bytes, "stat.mosaic");
    try {
      expect(file.header.kind).toBe("mosaic");
    } finally {
      file.close();
    }
  });
});

describe("the header is exactly one row of a known kind (3.3)", () => {
  it("refuses two header rows", async () => {
    const bytes = await mutate(
      TESSERA,
      "INSERT INTO header SELECT 2, format_version, kind, producer, settings, knowledge_hash, vector_hash, embed_model, pattern_hash, target, ai_model FROM header",
    );
    await expectRule(bytes, "two.tessera", "header");
  });

  it("refuses a single header row whose `one` is not 1", async () => {
    const bytes = await mutate(TESSERA, "UPDATE header SET one = 2");
    await expectRule(bytes, "one.tessera", "header");
  });

  for (const kind of ["Tessera", "MOSAIC", "", "tessera ", "piece"]) {
    it(`refuses header kind ${JSON.stringify(kind)}`, async () => {
      const bytes = await mutate(TESSERA, `UPDATE header SET kind = '${kind}'`);
      await expectRule(bytes, "kind.tessera", "header");
    });
  }

  it("returns text of the header as UTF-8, with non-ASCII and emoji intact", async () => {
    const producer = "ツール🧩/1.0";
    const aiModel = "modèle-é@2";
    const bytes = await mutate(
      TESSERA,
      `UPDATE header SET producer = '${producer}', ai_model = '${aiModel}'`,
    );
    const file = await openFile(bytes, "utf8.tessera");
    try {
      expect(file.header.producer).toBe(producer);
      expect(file.header.ai_model).toBe(aiModel);
      expect(file.header.embed_model).toBeNull();
    } finally {
      file.close();
    }
  });

  it("returns a long settings value whole", async () => {
    const settings = JSON.stringify({ k: "x".repeat(100_000) });
    const bytes = await mutate(TESSERA, `UPDATE header SET settings = '${settings}'`);
    const file = await openFile(bytes, "long.tessera");
    try {
      expect(file.header.settings).toBe(settings);
    } finally {
      file.close();
    }
  });
});

describe("untrusted, truncated and corrupt files are refused, never a crash (3.8 step 4, 10)", () => {
  it("refuses an empty byte array as it refuses empty.mosaic", async () => {
    await expectRule(new Uint8Array(0), "zero.mosaic", "application_id");
  });

  it("refuses a few bytes that are not a database", async () => {
    await expectRule(new Uint8Array([0x53, 0x51, 0x4c]), "three.mosaic", "sqlite");
  });

  it("refuses 100 zero bytes", async () => {
    expect(await opensOrRefused(new Uint8Array(100), "zeros.mosaic")).toBe("refused");
  });

  it("refuses the SQLite magic with nothing after it", async () => {
    const magic = new TextEncoder().encode("SQLite format 3\0");
    expect(await opensOrRefused(magic, "magic.mosaic")).toBe("refused");
  });

  for (const fraction of [0.1, 0.25, 0.5, 0.75, 0.99]) {
    it(`refuses a mosaic cut to ${fraction * 100}% of its bytes`, async () => {
      const whole = read(MOSAIC);
      const cut = whole.slice(0, Math.floor(whole.length * fraction));
      const error = await refusal(cut, "cut.mosaic");
      expect(REFUSAL_RULES).toContain(error.rule);
    });
  }

  it("refuses a mosaic cut by one byte", async () => {
    const whole = read(MOSAIC);
    expect(await opensOrRefused(whole.slice(0, whole.length - 1), "cut1.mosaic")).toBe("refused");
  });

  it("refuses a mosaic with extra bytes that are not a whole page", async () => {
    const whole = read(MOSAIC);
    const longer = new Uint8Array(whole.length + 7);
    longer.set(whole);
    // The page count in the file header no longer matches the length: opened or refused,
    // never another error.
    await opensOrRefused(longer, "long.mosaic");
  });

  it("opens or refuses cleanly with any one byte of the first 100 changed", async () => {
    const whole = read(TESSERA);
    for (let i = 0; i < 100; i++) {
      for (const value of [0x00, 0xff, whole[i]! ^ 0x01]) {
        const bytes = whole.slice();
        bytes[i] = value;
        await opensOrRefused(bytes, `byte-${i}-${value}.tessera`);
      }
    }
  });

  it("opens or refuses cleanly with a whole data page overwritten", async () => {
    const whole = read(MOSAIC);
    const pages = Math.floor(whole.length / 4096);
    for (const page of [1, 2, Math.floor(pages / 2), pages - 1]) {
      if (page < 1 || page >= pages) continue;
      for (const fill of [0x00, 0xff]) {
        const bytes = whole.slice();
        bytes.fill(fill, page * 4096, (page + 1) * 4096);
        await opensOrRefused(bytes, `page-${page}-${fill}.mosaic`);
      }
    }
  });

  it("opens a file whose header flags say WAL, with no write-ahead log beside it (3.1)", async () => {
    const bytes = read(TESSERA);
    bytes[18] = 2;
    bytes[19] = 2;
    expect(await opensOrRefused(bytes, "wal.tessera")).toBe("opened");
  });

  it("refuses a file whose text encoding flag says UTF-16, for encoding (3.1, decision B on #104)", async () => {
    for (const enc of [2, 3]) {
      const bytes = read(TESSERA);
      bytes[59] = enc;
      await expectRule(bytes, `enc-${enc}.tessera`, "encoding");
    }
  });

  it("opens or cleanly refuses a file whose text encoding flag is no SQLite encoding", async () => {
    const bytes = read(TESSERA);
    bytes[59] = 7;
    await opensOrRefused(bytes, "enc-7.tessera");
  });
});

describe("what a caller gives and gets back (3.8 step 1, 3.3)", () => {
  it("opens bytes that are a view into a larger buffer", async () => {
    const whole = read(MOSAIC);
    const big = new Uint8Array(whole.length + 37);
    big.fill(0xaa);
    big.set(whole, 17);
    const view = big.subarray(17, 17 + whole.length);
    expect(view.byteOffset).toBe(17);
    const file = await openFile(view, "view.mosaic");
    try {
      const expected = JSON.parse(readFileSync(conformance("reading/cases.json"), "utf8"))[
        "mosaic.mosaic"
      ].header;
      expect({ ...file.header }).toEqual(expected);
    } finally {
      file.close();
    }
  });

  it("refuses a view whose surrounding buffer would be valid but whose own bytes are not", async () => {
    const whole = read(MOSAIC);
    const big = new Uint8Array(whole.length + 8);
    big.set(whole, 0);
    const view = big.subarray(8); // starts mid-file
    expect(await opensOrRefused(view, "shifted.mosaic")).toBe("refused");
  });

  it("does not change the given bytes when it refuses the file", async () => {
    for (const name of ["application-id.mosaic", "schema-extra-table.mosaic", "no-header.mosaic"]) {
      const bytes = read(`reading/${name}`);
      const before = bytes.slice();
      await refusal(bytes, name);
      expect(bytes).toEqual(before);
    }
  });

  it("keeps the header after the caller changes the given bytes", async () => {
    const bytes = read(TESSERA);
    const file = await openFile(bytes, "t.tessera");
    const before = { ...file.header };
    bytes.fill(0);
    expect({ ...file.header }).toEqual(before);
    file.close();
  });

  it("does not let the header be changed, even in strict mode", async () => {
    const file = await openFile(read(TESSERA), "t.tessera");
    try {
      expect(() => {
        (file.header as { kind: string }).kind = "mosaic";
      }).toThrow(TypeError);
      expect(file.header.kind).toBe("tessera");
    } finally {
      file.close();
    }
  });

  it("opens the same bytes twice at once, and closing one leaves the other", async () => {
    const bytes = read(MOSAIC);
    const [a, b] = await Promise.all([openFile(bytes, "a.mosaic"), openFile(bytes, "b.mosaic")]);
    expect(a.name).toBe("a.mosaic");
    expect(b.name).toBe("b.mosaic");
    expect({ ...a.header }).toEqual({ ...b.header });
    a.close();
    expect(b.header.kind).toBe("mosaic");
    b.close();
  });

  it("opens several files in turn, a refusal in between changing nothing", async () => {
    const good = read(TESSERA);
    const first = await openFile(good, "1.tessera");
    await refusal(read("reading/not-sqlite.mosaic"), "bad.mosaic");
    const second = await openFile(good, "2.tessera");
    expect({ ...first.header }).toEqual({ ...second.header });
    first.close();
    second.close();
  });
});

describe("the error names the file and what failed (3.8 step 2, M2.1)", () => {
  const odd = ["", "a b.mosaic", "名前.mosaic", "with\nnewline.mosaic", "dir/sub/x.tessera", "a'b\".mosaic"];
  for (const name of odd) {
    it(`keeps the name ${JSON.stringify(name)} as given`, async () => {
      const error = await refusal(read("reading/user-version.mosaic"), name);
      expect(error.file).toBe(name);
      expect(error.message.startsWith(`${name}: `)).toBe(true);
      expect(error.message).toContain("user_version");
      expect(error.name).toBe("FileRefusedError");
      expect(error).toBeInstanceOf(Error);
    });
  }

  it("gives a different message for each rule", async () => {
    const files: Record<RefusalRule, string> = {
      sqlite: "not-sqlite.mosaic",
      encoding: "utf-16.mosaic",
      application_id: "application-id.mosaic",
      user_version: "user-version.mosaic",
      format_version: "format-version.mosaic",
      schema: "schema-extra-table.mosaic",
      header: "no-header.mosaic",
      knowledge_hash: "node-changed.mosaic",
      vector_hash: "vector-changed.mosaic",
    };
    const messages = new Set<string>();
    for (const rule of REFUSAL_RULES) {
      const error = await refusal(read(`reading/${files[rule]}`), "f");
      expect(error.rule).toBe(rule);
      messages.add(error.message);
    }
    expect(messages.size).toBe(REFUSAL_RULES.length);
  });

  it("names the version it found when it refuses a format version", async () => {
    const error = await refusal(read("reading/newer-minor.mosaic"), "n.mosaic");
    expect(error.message).toContain("0.2");
  });

  it("refuses the same way on a second try (same rule, same message)", async () => {
    const first = await refusal(read("reading/header-kind.mosaic"), "h.mosaic");
    const second = await refusal(read("reading/header-kind.mosaic"), "h.mosaic");
    expect(second.rule).toBe(first.rule);
    expect(second.message).toBe(first.message);
  });

  it("has one distinct rule name per refusal rule", () => {
    expect(new Set(REFUSAL_RULES).size).toBe(REFUSAL_RULES.length);
    expect([...REFUSAL_RULES].sort()).toEqual(
      [
        "application_id",
        "encoding",
        "format_version",
        "header",
        "knowledge_hash",
        "schema",
        "sqlite",
        "user_version",
        "vector_hash",
      ].sort(),
    );
  });
});
