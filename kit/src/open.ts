/**
 * Open a tessera or mosaic by the reading rules (Specification 0.1, section 3.8).
 *
 * {@link openFile} returns a {@link SealedFile} only after these checks pass:
 *
 * 1. The bytes are copied into SQLite WebAssembly and opened read-only; the caller's bytes are
 *    never written (step 1). The page has no file system, so no journal can lie beside it.
 * 2. `application_id` and `user_version` are those of format 0.1. The header's
 *    `format_version` is one this kit implements: only `0.1`, so a newer minor version is
 *    refused too (section 9). The schema holds exactly the objects of `format.sql`, with the
 *    same definitions (SQLite's statistics tables may be present). The header is exactly one
 *    row of a known kind (step 2). The version is read before the schema is compared whenever
 *    `header` is a plain table with a stored `format_version` column, so a newer minor version
 *    that adds a column to `header` is refused for its version, not its schema.
 *
 * Anything else is refused with {@link FileRefusedError}, naming the file and what failed.
 * The same files open or are refused for the same rule as in the Python reader:
 * `conformance/reading/` holds the cases both read.
 *
 * Every value in the file is untrusted data (step 4, section 10). Opening reads the schema and
 * at most two header rows; the tools bound their own queries.
 */
import sqlite3InitModule, { type Database, type Sqlite3Static } from "@sqlite.org/sqlite-wasm";
import { FORMAT_SQL } from "./format-sql.js";

/** Format versions this kit implements (section 9). */
export const IMPLEMENTED_VERSIONS: readonly string[] = ["0.1"];

/** PRAGMA application_id of every tessera and mosaic: "MOSA" (section 3.1). */
const APPLICATION_ID = 0x4d4f5341;

/** PRAGMA user_version of format 0.1 (section 3.1). */
const USER_VERSION = 1;

/** The kinds of file a header names (section 3.3). */
const KINDS = ["tessera", "mosaic"] as const;

/** SQLite's statistics tables, which `ANALYZE` writes: the only objects allowed beyond format.sql. */
const STATISTICS: Readonly<Record<string, string>> = {
  sqlite_stat1: "CREATE TABLE sqlite_stat1(tbl,idx,stat)",
  sqlite_stat4: "CREATE TABLE sqlite_stat4(tbl,idx,neq,nlt,ndlt,sample)",
};

/** Why a file was refused; `conformance/reading/cases.json` uses the same names. */
export const REFUSAL_RULES = [
  "sqlite",
  "application_id",
  "user_version",
  "format_version",
  "schema",
  "header",
] as const;

export type RefusalRule = (typeof REFUSAL_RULES)[number];

/** A file that the reading rules of section 3.8 refuse. */
export class FileRefusedError extends Error {
  override readonly name = "FileRefusedError";

  constructor(
    /** The file's name, as given to {@link openFile}. */
    readonly file: string,
    /** The rule it breaks. */
    readonly rule: RefusalRule,
    reason: string,
  ) {
    super(`${file}: ${reason}`);
  }
}

/** The header row of a tessera or mosaic (section 3.3), as the file holds it. */
export interface Header {
  readonly one: number;
  readonly format_version: string;
  readonly kind: (typeof KINDS)[number];
  readonly producer: string;
  /** Canonical JSON text, as stored. */
  readonly settings: string;
  readonly knowledge_hash: string;
  readonly vector_hash: string | null;
  readonly embed_model: string | null;
  readonly pattern_hash: string | null;
  readonly target: string | null;
  readonly ai_model: string | null;
}

/** A tessera or mosaic that passed the reading rules, open read-only. */
export interface SealedFile {
  /** The name it was opened under. */
  readonly name: string;
  readonly header: Header;
  /** Free the file's memory. Closing twice is harmless. */
  close(): void;
}

let engine: Promise<Sqlite3Static> | undefined;

/** SQLite WebAssembly, loaded once. */
function sqlite(): Promise<Sqlite3Static> {
  engine ??= sqlite3InitModule().then((s) => {
    // The engine warns on the console for every failed statement; a refused file is an
    // answer here, not a fault, and the error says what failed.
    const config = (s as unknown as { config?: { warn?: (...args: unknown[]) => void } }).config;
    if (config) config.warn = () => {};
    return s;
  });
  return engine;
}

/**
 * Open `bytes`, a tessera or mosaic named `name`, by the reading rules of section 3.8, or
 * refuse it with a {@link FileRefusedError} naming the file and what failed.
 */
export async function openFile(bytes: Uint8Array, name: string): Promise<SealedFile> {
  const [s, expected] = await Promise.all([sqlite(), referenceSchema()]);
  const db = load(s, bytes, name);
  try {
    const header = verify(db, name, expected);
    return sealedFile(db, name, header);
  } catch (e) {
    db.close();
    if (e instanceof FileRefusedError) throw e;
    throw new FileRefusedError(name, "sqlite", `not a readable SQLite 3 database (${message(e)}) (section 3.1)`);
  }
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** A read-only database holding a copy of `bytes` (section 3.8 step 1). */
function load(s: Sqlite3Static, bytes: Uint8Array, name: string): Database {
  const db = new s.oo1.DB(":memory:", "c");
  if (bytes.byteLength === 0) {
    // SQLite reads an empty file as an empty database, which the checks then refuse.
    configure(db);
    return db;
  }
  refuseUtf16(bytes, name);
  const { capi, wasm } = s;
  const pointer = wasm.allocFromTypedArray(walCleared(bytes));
  const flags = capi.SQLITE_DESERIALIZE_FREEONCLOSE | capi.SQLITE_DESERIALIZE_READONLY;
  const rc = capi.sqlite3_deserialize(db, "main", pointer, bytes.byteLength, bytes.byteLength, flags);
  if (rc !== capi.SQLITE_OK) {
    db.close();
    throw new FileRefusedError(
      name,
      "sqlite",
      `not a readable SQLite 3 database (${capi.sqlite3_js_rc_str(rc)}) (section 3.1)`,
    );
  }
  configure(db);
  return db;
}

/** The 16 bytes that open every SQLite 3 database file. */
const SQLITE_MAGIC = new TextEncoder().encode("SQLite format 3\0");

function isSqliteHeader(bytes: Uint8Array): boolean {
  return bytes.byteLength >= 100 && SQLITE_MAGIC.every((b, i) => bytes[i] === b);
}

/**
 * Refuse a database whose text is stored as UTF-16: the SQLite WebAssembly the kit runs on is
 * built without UTF-16 (`SQLITE_OMIT_UTF16`), so it cannot read one. Bytes 56–59 of the
 * SQLite header hold the text encoding: 1 for UTF-8, 2 for UTF-16le, 3 for UTF-16be.
 */
function refuseUtf16(bytes: Uint8Array, name: string): void {
  if (!isSqliteHeader(bytes)) return;
  const encoding = new DataView(bytes.buffer, bytes.byteOffset + 56, 4).getUint32(0);
  if (encoding === 2 || encoding === 3) {
    const label = encoding === 2 ? "UTF-16le" : "UTF-16be";
    throw new FileRefusedError(
      name,
      "sqlite",
      `text encoding ${label}: this kit reads SQLite databases whose text is UTF-8 only (section 3.1)`,
    );
  }
}

/**
 * The bytes to load, with a write-ahead-log flag cleared. A sealed file has no write-ahead log
 * beside it (section 3.1), so one opened in WAL mode is read as it stands, as SQLite reads an
 * immutable file; an in-memory copy cannot be opened in WAL mode. Bytes 18 and 19 of the
 * SQLite header are 2 in WAL mode and 1 otherwise. The caller's bytes are never changed.
 */
function walCleared(bytes: Uint8Array): Uint8Array {
  if (!isSqliteHeader(bytes) || (bytes[18] !== 2 && bytes[19] !== 2)) return bytes;
  const copy = bytes.slice();
  if (copy[18] === 2) copy[18] = 1;
  if (copy[19] === 2) copy[19] = 1;
  return copy;
}

function configure(db: Database): void {
  db.exec("PRAGMA query_only = ON");
  db.exec("PRAGMA trusted_schema = OFF");
  db.exec("PRAGMA cell_size_check = ON");
}

function verify(db: Database, name: string, expected: Schema): Header {
  const applicationId = Number(db.selectValue("PRAGMA application_id"));
  if (applicationId !== APPLICATION_ID) {
    const hex = (n: number) => `0x${(n >>> 0).toString(16).toUpperCase().padStart(8, "0")}`;
    throw new FileRefusedError(
      name,
      "application_id",
      `application_id ${hex(applicationId)} is not ${hex(APPLICATION_ID)} (MOSA): not a tessera or mosaic (section 3.1)`,
    );
  }
  checkVersion(db, name);
  checkSchema(db, name, expected);
  return readHeader(db, name);
}

function implemented(): string {
  return IMPLEMENTED_VERSIONS.join(", ");
}

/** Refuse a format version this kit does not implement (sections 3.8 step 2 and 9). */
function checkVersion(db: Database, name: string): void {
  const userVersion = Number(db.selectValue("PRAGMA user_version"));
  if (userVersion !== USER_VERSION) {
    throw new FileRefusedError(
      name,
      "user_version",
      `user_version ${userVersion}: this kit implements format version ${implemented()} (user_version ${USER_VERSION}) only and refuses any other (section 9)`,
    );
  }
  if (!hasStoredFormatVersion(db)) return;
  // format.sql's header holds one row; read at most two of a crafted table, so a file with
  // millions of rows costs nothing here (section 10). Extra rows are a schema mismatch.
  for (const [version] of db.selectArrays("SELECT format_version FROM header LIMIT 2")) {
    if (typeof version !== "string" || !IMPLEMENTED_VERSIONS.includes(version)) {
      throw new FileRefusedError(
        name,
        "format_version",
        `format version ${JSON.stringify(version)} is not implemented by this kit, which reads ${implemented()} only; a newer minor version is refused too (section 9)`,
      );
    }
  }
}

/**
 * Whether `header` is a plain table with a stored `format_version` column. Only then is the
 * version read before the schema check: a view, a virtual table or a computed column could be
 * endless or costly (section 10), so it is left to the schema check.
 */
function hasStoredFormatVersion(db: Database): boolean {
  const rows = db.selectArrays("SELECT type, sql FROM sqlite_schema WHERE name = 'header'");
  if (rows.length !== 1) return false;
  const [type, sql] = rows[0]!;
  if (type !== "table" || typeof sql !== "string" || !sql.startsWith("CREATE TABLE ")) return false;
  return db
    .selectArrays("SELECT name, hidden FROM pragma_table_xinfo('header')")
    .some(([column, hidden]) => column === "format_version" && hidden === 0);
}

type SchemaRow = readonly [type: string, name: string, tblName: string, sql: string | null];

const SCHEMA_QUERY = "SELECT type, name, tbl_name, sql FROM sqlite_schema";

/** Each object's definitions (table name and SQL), keyed by type and name. */
type Schema = ReadonlyMap<string, ReadonlySet<string>>;

let reference: Promise<Schema> | undefined;

function key(type: string, name: string): string {
  return `${type} ${name}`;
}

function bySchemaKey(rows: readonly SchemaRow[]): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  for (const [type, name, tblName, sql] of rows) {
    const k = key(type, name);
    const defs = out.get(k) ?? new Set<string>();
    defs.add(JSON.stringify([tblName, sql]));
    out.set(k, defs);
  }
  return out;
}

function schemaRows(db: Database): SchemaRow[] {
  return db.selectArrays(SCHEMA_QUERY).map(([type, name, tblName, sql]) => [
    String(type),
    String(name),
    String(tblName),
    typeof sql === "string" ? sql : null,
  ]);
}

/** `sqlite_schema` of a fresh database made from `format.sql`: what a file must hold. */
function referenceSchema(): Promise<Schema> {
  reference ??= sqlite().then((s) => {
    const db = new s.oo1.DB(":memory:", "c");
    try {
      db.exec(FORMAT_SQL);
      return bySchemaKey(schemaRows(db));
    } finally {
      db.close();
    }
  });
  return reference;
}

/** Exactly the objects of `format.sql`, with the same definitions (section 3.1). */
function checkSchema(db: Database, name: string, expected: Schema): void {
  const actual = bySchemaKey(
    schemaRows(db).filter(([type, n, , sql]) => !(type === "table" && STATISTICS[n] === sql)),
  );
  const problems: string[] = [];
  const sorted = (keys: Iterable<string>) => [...keys].sort(compareUtf8);
  for (const k of sorted(expected.keys())) if (!actual.has(k)) problems.push(`${k} is missing`);
  for (const k of sorted(actual.keys())) if (!expected.has(k)) problems.push(`${k} is not in format.sql`);
  for (const k of sorted(expected.keys())) {
    const have = actual.get(k);
    if (have && !sameSet(expected.get(k)!, have)) problems.push(`${k} differs from its definition in format.sql`);
  }
  if (problems.length > 0) {
    throw new FileRefusedError(name, "schema", `schema does not match format.sql (section 3.1): ${problems.join("; ")}`);
  }
}

function sameSet(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  return a.size === b.size && [...a].every((x) => b.has(x));
}

const encoder = new TextEncoder();

/** Order by UTF-8 bytes, as the specification compares text. */
function compareUtf8(a: string, b: string): number {
  const x = encoder.encode(a);
  const y = encoder.encode(b);
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) if (x[i] !== y[i]) return x[i]! - y[i]!;
  return x.length - y.length;
}

/** The one header row (section 3.3), with a kind this kit knows. */
function readHeader(db: Database, name: string): Header {
  const rows = db.selectObjects("SELECT * FROM header");
  if (rows.length !== 1) {
    throw new FileRefusedError(name, "header", `header has ${rows.length} rows; it must hold exactly one (section 3.3)`);
  }
  const row = rows[0]!;
  if (row.one !== 1) {
    throw new FileRefusedError(name, "header", `header row has one = ${JSON.stringify(row.one)}, not 1 (section 3.3)`);
  }
  if (!KINDS.includes(row.kind as (typeof KINDS)[number])) {
    throw new FileRefusedError(
      name,
      "header",
      `header kind ${JSON.stringify(row.kind)} is not one of ${KINDS.join(", ")} (section 3.3)`,
    );
  }
  return Object.freeze({ ...row }) as unknown as Header;
}

function sealedFile(db: Database, name: string, header: Header): SealedFile {
  let open = true;
  return {
    name,
    header,
    close() {
      if (open) db.close();
      open = false;
    },
  };
}
