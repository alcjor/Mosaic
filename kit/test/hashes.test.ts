// Section 3.8 step 3: the kit recomputes the knowledge hash (3.6) and the vector hash (3.7) on
// every open and refuses the file on a mismatch, naming the hash that differs.
import sqlite3InitModule, { type Database } from "@sqlite.org/sqlite-wasm";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { FileRefusedError, encodeKnowledge, knowledgeHash, openFile, vectorHash } from "../src/index.js";

const conformance = (path: string): string =>
  fileURLToPath(new URL(`../../conformance/${path}`, import.meta.url));

const read = (path: string): Uint8Array => new Uint8Array(readFileSync(conformance(path)));

interface Hashes {
  opens: boolean;
  knowledge_hash: string;
  vector_hash: string | null;
}

/** What `mosaic_format` computes for every file that reaches step 3 (scripts/make_reading_files.py). */
const HASHES = JSON.parse(readFileSync(conformance("reading/hashes.json"), "utf8")) as Record<string, Hashes>;

const sqlite3 = await sqlite3InitModule();

/** `bytes` as a database, read-only, without the reading rules: to compute hashes alone. */
function database(bytes: Uint8Array, writable = false): Database {
  // An in-memory copy cannot be in WAL mode: read a WAL-flagged file as it stands (3.1).
  if (bytes[18] === 2) bytes[18] = 1;
  if (bytes[19] === 2) bytes[19] = 1;
  const db = new sqlite3.oo1.DB(":memory:", "c");
  const p = sqlite3.wasm.allocFromTypedArray(bytes);
  const flags =
    sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE |
    (writable ? sqlite3.capi.SQLITE_DESERIALIZE_RESIZEABLE : sqlite3.capi.SQLITE_DESERIALIZE_READONLY);
  const rc = sqlite3.capi.sqlite3_deserialize(db, "main", p, bytes.length, bytes.length, flags);
  if (rc !== 0) throw new Error(`deserialize failed: ${rc}`);
  return db;
}

/** A copy of `path` changed by `statements` (constraints off), its header left as it was. */
function changed(path: string, ...statements: string[]): Uint8Array {
  const db = database(read(path), true);
  try {
    db.exec("PRAGMA ignore_check_constraints = ON");
    db.exec("PRAGMA foreign_keys = OFF");
    for (const sql of statements) db.exec(sql);
    return sqlite3.capi.sqlite3_js_db_export(db);
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

describe("conformance/reading/hashes.json: the kit's hashes are those of mosaic_format (3.6, 3.7)", () => {
  const keys = Object.keys(HASHES).sort();

  it("covers the valid files of conformance/ and the files refused for a hash", () => {
    expect(keys).toContain("reading/mosaic.mosaic");
    expect(keys).toContain("reading/tessera.tessera");
    expect(keys).toContain("reading/non-ascii.mosaic");
    expect(keys).toContain("invalid/files/inv-15-piece.tessera");
    expect(keys.filter((k) => !HASHES[k]!.opens).length).toBeGreaterThanOrEqual(7);
  });

  for (const key of keys) {
    const expected = HASHES[key]!;

    it(`computes the knowledge and vector hash of ${key} as mosaic_format does`, () => {
      const db = database(read(key));
      try {
        expect(knowledgeHash(db)).toBe(expected.knowledge_hash);
        expect(vectorHash(db)).toBe(expected.vector_hash);
      } finally {
        db.close();
      }
    });

    if (expected.opens) {
      it(`opens ${key}, whose header holds the hashes its content gives`, async () => {
        const file = await openFile(read(key), key);
        try {
          expect(file.header.knowledge_hash).toBe(expected.knowledge_hash);
          expect(file.header.vector_hash).toBe(expected.vector_hash);
        } finally {
          file.close();
        }
      });
    } else {
      it(`refuses ${key}, naming the hash that differs and both values`, async () => {
        const db = database(read(key));
        const header = db.selectObject("SELECT knowledge_hash, vector_hash FROM header") as Record<string, unknown>;
        db.close();
        const error = await refusal(read(key), key);
        if (header.knowledge_hash !== expected.knowledge_hash) {
          expect(error.rule).toBe("knowledge_hash");
          expect(error.message).toContain("knowledge hash mismatch");
          expect(error.message).toContain(String(header.knowledge_hash));
          expect(error.message).toContain(expected.knowledge_hash);
        } else {
          expect(error.rule).toBe("vector_hash");
          expect(error.message).toContain("vector hash mismatch");
          expect(error.message).toContain(String(header.vector_hash));
          expect(error.message).toContain(String(expected.vector_hash));
        }
      });
    }
  }
});

describe("one changed row is refused on open, naming the hash that differs (3.8 step 3)", () => {
  const MOSAIC = "reading/mosaic.mosaic";
  const TESSERA = "reading/tessera.tessera";
  const knowledge: Record<string, [string, string]> = {
    "the format version's kind": [TESSERA, "UPDATE header SET kind = 'mosaic'"],
    "a source": [MOSAIC, "UPDATE source SET notice = 'changed' WHERE sid = 1"],
    "a type": [MOSAIC, "UPDATE type SET description = 'changed' WHERE name = 'Item'"],
    "a node": [MOSAIC, "UPDATE node SET summary = 'changed' WHERE nid = 1"],
    "a node's id": [MOSAIC, "UPDATE node SET id = 'Item:aa' WHERE nid = 1"],
    "an edge": [MOSAIC, "UPDATE edge SET qualifier = 'q' WHERE eid = 2"],
    "an alias": [MOSAIC, "UPDATE alias SET origin = 'pattern' WHERE text = 'A'"],
    "an evidence row": [MOSAIC, "UPDATE evidence SET producer = 'other/1' WHERE evid = 1"],
    "a confidence, past the sixth decimal": [MOSAIC, "UPDATE evidence SET confidence = 0.500001 WHERE confidence IS NOT NULL"],
    "a snippet": [MOSAIC, "UPDATE snippet SET text = 'changed' WHERE evid = 1"],
    "a mention": [TESSERA, "UPDATE mention SET locator = 'row=9' WHERE mid = 1"],
    "an external reference": [MOSAIC, "UPDATE external_ref SET system = 'other' WHERE xid = 1"],
    "a removed node row": [MOSAIC, "DELETE FROM node WHERE nid = 3"],
    "an added alias": [MOSAIC, "INSERT INTO alias (text, nid, origin) VALUES ('extra', 1, 'source')"],
  };
  for (const [what, [path, sql]] of Object.entries(knowledge)) {
    it(`refuses ${what} for knowledge_hash`, async () => {
      const error = await refusal(changed(path, sql), "changed.mosaic");
      expect(error.rule).toBe("knowledge_hash");
      expect(error.message).toMatch(/^changed\.mosaic: knowledge hash mismatch: the header says '[0-9a-f]{64}', the content gives '[0-9a-f]{64}'/);
    });
  }

  it("opens a confidence changed below the sixth decimal, which the hash rounds away (3.6)", async () => {
    const bytes = changed(MOSAIC, "UPDATE evidence SET confidence = 0.5000001 WHERE confidence IS NOT NULL");
    (await openFile(bytes, "rounded.mosaic")).close();
  });

  it("opens a changed derived table, which the hash does not cover (3.6: link_count)", async () => {
    const bytes = changed(MOSAIC, "UPDATE link_count SET count = 9 WHERE nid = 1");
    (await openFile(bytes, "derived.mosaic")).close();
  });

  const vector: Record<string, string> = {
    "a changed vector": "UPDATE vector SET bits = zeroblob(48) WHERE nid = 2",
    "a removed vector": "DELETE FROM vector WHERE nid = 3",
    "two vectors swapped":
      "CREATE TEMP TABLE old AS SELECT nid, bits FROM vector; " +
      "UPDATE vector SET bits = (SELECT bits FROM old WHERE old.nid = 3 - vector.nid) WHERE nid IN (1, 2)",
    "every vector removed": "DELETE FROM vector",
  };
  for (const [what, sql] of Object.entries(vector)) {
    it(`refuses ${what} for vector_hash`, async () => {
      const error = await refusal(changed(MOSAIC, sql), "changed.mosaic");
      expect(error.rule).toBe("vector_hash");
      expect(error.message).toContain("vector hash mismatch: the header says '");
    });
  }

  it("refuses vectors in a file whose header has no vector hash", async () => {
    const bytes = changed(TESSERA, "INSERT INTO vector (nid, bits) VALUES (1, zeroblob(48))");
    const error = await refusal(bytes, "vectors.tessera");
    expect(error.rule).toBe("vector_hash");
    expect(error.message).toContain("the header says null");
  });

  it("refuses a vector that is not a 48-byte blob, naming its node", async () => {
    const error = await refusal(changed(MOSAIC, "UPDATE vector SET bits = zeroblob(47) WHERE nid = 1"), "short.mosaic");
    expect(error.rule).toBe("vector_hash");
    expect(error.message).toContain("'Group:x'");
    expect(error.message).toContain("48-byte blob");
  });

  it("refuses a value the knowledge hash cannot encode: a REAL outside confidence", async () => {
    const error = await refusal(changed(MOSAIC, "UPDATE alias SET nid = 1.5 WHERE text = 'A'"), "real.mosaic");
    expect(error.rule).toBe("knowledge_hash");
    expect(error.message).toContain("part 'alias', row 1 in canonical order, column 'nid'");
  });

  it("refuses a value the knowledge hash cannot encode: a confidence that is not REAL", async () => {
    const bytes = changed(MOSAIC, "UPDATE evidence SET confidence = 'high' WHERE confidence IS NOT NULL");
    const error = await refusal(bytes, "text.mosaic");
    expect(error.rule).toBe("knowledge_hash");
    expect(error.message).toContain("column 'confidence'");
  });
});

describe("canonical order compares text by UTF-8 bytes (3.6)", () => {
  // U+FF5E is EF BD 9E in UTF-8 and FF5E in UTF-16; U+1F600 is F0 9F 98 80 and D83D DE00.
  const [tilde, emoji] = ["～", "\u{1F600}"];

  it("non-ascii.mosaic holds ids, keys and aliases that sort the other way by UTF-16", () => {
    expect(tilde < emoji).toBe(false);
    const db = database(read("reading/non-ascii.mosaic"));
    try {
      const ids = db.selectValues("SELECT id FROM node WHERE key IN (?, ?) ORDER BY nid", [tilde, emoji]);
      expect(ids).toEqual([`Item:${tilde}`, `Item:${emoji}`]);
      expect(db.selectValues("SELECT text FROM alias WHERE nid > 3 ORDER BY text COLLATE NOCASE, nid")).toEqual([tilde, emoji]);
    } finally {
      db.close();
    }
  });

  it("gives the header's hash for that file, and another once its two aliases trade nodes", async () => {
    const file = await openFile(read("reading/non-ascii.mosaic"), "non-ascii.mosaic");
    file.close();
    const swapped = changed(
      "reading/non-ascii.mosaic",
      "UPDATE alias SET nid = CASE nid WHEN 4 THEN 5 ELSE 4 END WHERE nid IN (4, 5)",
    );
    expect((await refusal(swapped, "swapped.mosaic")).rule).toBe("knowledge_hash");
  });

  it("writes the alias part in UTF-8 byte order, as SHA-256 over those bytes gives the header's hash", () => {
    const db = database(read("reading/non-ascii.mosaic"));
    try {
      const chunks: Uint8Array[] = [];
      encodeKnowledge(db, (bytes) => chunks.push(bytes.slice()));
      const text = Buffer.concat(chunks).toString("utf8");
      expect(text).toContain(`'${tilde}',4,'source'\n'${emoji}',5,'source'\n`);
      expect(text).toContain(`,'Item:${tilde}','Item','${tilde}',`);
      expect(text.indexOf(`'Item:${tilde}'`)).toBeLessThan(text.indexOf(`'Item:${emoji}'`));
      const header = db.selectValue("SELECT knowledge_hash FROM header");
      expect(createHash("sha256").update(Buffer.concat(chunks)).digest("hex")).toBe(header);
    } finally {
      db.close();
    }
  });
});
