/**
 * The knowledge hash (Specification 0.1, section 3.6) and the vector hash (section 3.7) of an
 * open file, as the kit recomputes them on every open (section 3.8 step 3).
 *
 * The canonical byte string is built in SQL, which section 3.6 allows: each row is its column
 * values as SQLite's `quote()` writes them, joined by commas and ended by a newline, read back
 * as a blob so text keeps its exact UTF-8 bytes. Rows come in each part's row order; `ORDER BY`
 * compares text with SQLite's `BINARY` collation, that is by UTF-8 bytes, and `alias` by its
 * declared `NOCASE` collation, then `nid`. The bytes stream into SHA-256 row by row.
 *
 * `quote()` has no portable form for a REAL, so a REAL anywhere but `confidence`, or a
 * `confidence` that is not REAL, is refused as the Python reader refuses it: such a value
 * breaks `format.sql`'s column types, and two SQLite versions could hash it differently.
 */
import type { Database } from "@sqlite.org/sqlite-wasm";
import { Sha256 } from "./sha256.js";

/** One part of the knowledge hash: its table, columns in order, and row order (section 3.6). */
interface Part {
  readonly name: string;
  readonly columns: readonly string[];
  readonly order: string;
}

/** The parts of the knowledge hash, in order. Each part is the table of that name. */
export const PARTS: readonly Part[] = [
  { name: "header", columns: ["format_version", "kind"], order: "one" },
  { name: "source", columns: ["sid", "id", "kind", "hash", "notice"], order: "sid" },
  {
    name: "type",
    columns: ["name", "kind", "description", "key_prop", "from_type", "to_type", "props"],
    order: "name",
  },
  { name: "node", columns: ["nid", "id", "type", "key", "label", "summary", "props"], order: "nid" },
  { name: "edge", columns: ["eid", "type", "src", "dst", "qualifier", "props"], order: "eid" },
  { name: "alias", columns: ["text", "nid", "origin"], order: "text COLLATE NOCASE, nid" },
  {
    name: "evidence",
    columns: ["evid", "nid", "eid", "prop", "sid", "locator", "method", "producer", "confidence", "via"],
    order: "evid",
  },
  { name: "snippet", columns: ["evid", "text"], order: "evid" },
  { name: "mention", columns: ["mid", "text", "locator", "nid", "role", "kind"], order: "mid" },
  { name: "source_text", columns: ["sid", "text"], order: "sid" },
  { name: "external_ref", columns: ["xid", "nid", "system", "kind", "locator", "sid"], order: "xid" },
];

/** The one column hashed as a rounded integer rather than with plain `quote()`. */
const CONFIDENCE = "confidence";

/** Length of one stored vector: 384 sign bits (section 3.7). */
export const VECTOR_BYTES = 48;

/** A value one of the hashes cannot take; the reader refuses the file, naming where it is. */
export class UnhashableError extends Error {
  override readonly name = "UnhashableError";
}

function isConfidence(part: Part, column: string): boolean {
  return part.name === "evidence" && column === CONFIDENCE;
}

function encoded(part: Part, column: string): string {
  return isConfidence(part, column) ? `quote(CAST(round(${column}*1000000) AS INTEGER))` : `quote(${column})`;
}

/** The first column of a row the hash cannot encode, or NULL. */
function unhashable(part: Part): string {
  const cases = part.columns.map((c) =>
    isConfidence(part, c)
      ? `WHEN typeof(${c}) NOT IN ('real', 'null') THEN '${c}'`
      : `WHEN typeof(${c}) = 'real' THEN '${c}'`,
  );
  return `CASE ${cases.join(" ")} END`;
}

function partQuery(part: Part): string {
  const line = `${part.columns.map((c) => encoded(part, c)).join(" || ',' || ")} || char(10)`;
  return `SELECT CAST(${line} AS BLOB), ${unhashable(part)} FROM ${part.name} ORDER BY ${part.order}`;
}

const QUERIES: readonly string[] = PARTS.map(partQuery);

const encoder = new TextEncoder();

/** Stream the canonical byte string of section 3.6 into `sink`, part by part. */
export function encodeKnowledge(db: Database, sink: (bytes: Uint8Array) => void): void {
  PARTS.forEach((part, i) => {
    sink(encoder.encode(`#${part.name}\n`));
    const stmt = db.prepare(QUERIES[i]!);
    try {
      for (let row = 1; stmt.step(); row++) {
        const bad = stmt.get(1);
        if (typeof bad === "string") {
          const where = `part '${part.name}', row ${row} in canonical order, column '${bad}'`;
          throw new UnhashableError(
            isConfidence(part, bad)
              ? `${where}: a value that is not REAL; confidence must be REAL or NULL`
              : `${where}: a REAL value has no portable quote() form; only confidence may be REAL`,
          );
        }
        sink(stmt.get(0) as Uint8Array);
      }
    } finally {
      stmt.finalize();
    }
  });
}

/** The knowledge hash of the open file (section 3.6): SHA-256 as 64 lowercase hex characters. */
export function knowledgeHash(db: Database): string {
  const digest = new Sha256();
  encodeKnowledge(db, (bytes) => digest.update(bytes));
  return digest.hex();
}

/**
 * The vector hash of section 3.7, or null when the file holds no vectors: SHA-256 of the
 * 48-byte `bits` values concatenated in `nid` order. A value that is not a 48-byte blob is
 * refused, naming the node it belongs to.
 */
export function vectorHash(db: Database): string | null {
  const digest = new Sha256();
  const stmt = db.prepare(
    "SELECT n.id, typeof(v.bits), length(v.bits), v.bits FROM vector AS v LEFT JOIN node AS n ON n.nid = v.nid ORDER BY v.nid",
  );
  let count = 0;
  try {
    while (stmt.step()) {
      count++;
      const [node, type, length] = [stmt.get(0), stmt.get(1), stmt.get(2)];
      if (type !== "blob" || length !== VECTOR_BYTES) {
        const shown = type === "blob" ? `${String(length)}-byte blob` : String(type);
        const named = typeof node === "string" ? `'${node}'` : "null";
        throw new UnhashableError(
          `vector of node ${named} (row ${count} in nid order): bits is a ${shown}, not a ${VECTOR_BYTES}-byte blob`,
        );
      }
      digest.update(stmt.get(3) as Uint8Array);
    }
  } finally {
    stmt.finalize();
  }
  return count > 0 ? digest.hex() : null;
}
