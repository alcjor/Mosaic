/**
 * Open a tessera or mosaic by the reading rules (Specification 0.1, section 3.8).
 *
 * {@link openFile} returns a {@link SealedFile} only after these checks pass:
 *
 * 1. The bytes are copied into SQLite WebAssembly and opened read-only; the caller's bytes are
 *    never written (step 1). The page has no file system, so no journal can lie beside it.
 * 2. Text is stored as UTF-8 (section 3.1, decision B on #104). `application_id` and
 *    `user_version` are those of format 0.1. The header's
 *    `format_version` is one this kit implements: only `0.1`, so a newer minor version is
 *    refused too (section 9). The schema holds exactly the objects of `format.sql`, with the
 *    same definitions (SQLite's statistics tables may be present). The header is exactly one
 *    row of a known kind (step 2). The version is read before the schema is compared whenever
 *    `header` is a plain table with a stored `format_version` column, so a newer minor version
 *    that adds a column to `header` is refused for its version, not its schema.
 * 3. The knowledge hash (section 3.6) and, if the file holds vectors, the vector hash (section
 *    3.7) are recomputed and equal the header's (step 3). A file whose vectors the header does
 *    not name, or whose header names vectors it does not hold, is a vector hash mismatch.
 *
 * Anything else is refused with {@link FileRefusedError}, naming the file and what failed.
 * The same files open or are refused for the same rule as in the Python reader:
 * `conformance/reading/` holds the cases both read.
 *
 * Every value in the file is untrusted data (step 4, section 10). Opening reads the schema, at
 * most two header rows however many the file holds, and each hashed row once, in a time that
 * grows with the file's size alone; the tools bound their own queries.
 */
import sqlite3InitModule, { type Database, type Sqlite3Static } from "@sqlite.org/sqlite-wasm";
import {
  type CiteAnswer,
  type ErrorAnswer,
  type FindAnswer,
  type GetAnswer,
  type NeighborsAnswer,
  type TableAnswer,
  ToolError,
  errorAnswer,
} from "./answers.js";
import { Deadline, TIME_LIMIT_MS } from "./bounds.js";
import { APPLICATION_ID, FORMAT_VERSION, USER_VERSION, type ToolName } from "./constants.js";
import { cite } from "./cite.js";
import { DIMENSIONS, type QueryEmbedder } from "./embed.js";
import { find, findArgs, hasWords } from "./find.js";
import { FORMAT_SQL } from "./format-sql.js";
import { get } from "./get.js";
import { UnhashableError, knowledgeHash, vectorHash } from "./hashes.js";
import { neighbors } from "./neighbors.js";
import { table } from "./table.js";

/** Format versions this kit implements (section 9). */
export const IMPLEMENTED_VERSIONS: readonly string[] = [FORMAT_VERSION];

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
  "encoding",
  "application_id",
  "user_version",
  "format_version",
  "schema",
  "header",
  "knowledge_hash",
  "vector_hash",
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

/** How a file is opened. */
export interface OpenOptions {
  /** The time bound of one tool call, in milliseconds; {@link TIME_LIMIT_MS} by default. */
  readonly timeLimitMs?: number;
  /**
   * What embeds queries for `find`'s vector tier ({@link loadEmbedder}). Used only for a mosaic
   * with vectors whose `embed_model` is the embedder's model; any other file is searched by
   * names and full text only (section 3.8).
   */
  readonly embedder?: QueryEmbedder;
}

/** A node type the file declares, with how many nodes it has (section 3.4). */
export interface NodeType {
  readonly name: string;
  readonly count: number;
}

/** Most node types {@link SealedFile.nodeTypes} lists (section 3.8 step 4: bounded result size). */
export const NODE_TYPE_LIMIT = 1000;

/** An edge type the file declares, with the node types it joins (section 3.4). */
export interface EdgeType {
  readonly name: string;
  readonly from: string | null;
  readonly to: string | null;
}

/** A tessera or mosaic that passed the reading rules, open read-only. */
export interface SealedFile {
  /** The name it was opened under. */
  readonly name: string;
  readonly header: Header;
  /**
   * The node types the file declares, by name (UTF-8 bytes), each with its node count: what a
   * viewer lists as tables and the card lists as things (sections 3.4, 8.3). Only names of the
   * form section 3.4 allows, at most {@link NODE_TYPE_LIMIT}.
   */
  readonly nodeTypes: readonly NodeType[];
  /**
   * The edge types the file declares, by name (UTF-8 bytes), each with the node types it joins
   * (section 3.4). Only names of the form section 3.4 allows, at most {@link NODE_TYPE_LIMIT}.
   */
  readonly edgeTypes: readonly EdgeType[];
  /**
   * The properties node type `type` declares, in the order its `props` object holds them
   * (section 3.4); empty for a type {@link nodeTypes} does not list.
   */
  propsOf(type: string): readonly string[];
  /** The time bound of one tool call, in milliseconds (section 3.8 step 4). */
  readonly timeLimitMs: number;
  /**
   * True when `find` has its vector tier: the file holds vectors, and its `embed_model` is the
   * model of the embedder it was opened with (sections 3.8 and 6).
   */
  readonly vectorSearch: boolean;
  /**
   * `find` (sections 8.1 and 8.5): nodes matching `args.query`, exact matches first, then
   * full-text hits, or an error answer. `args` is taken as untrusted input and checked.
   */
  find(args: unknown): Promise<FindAnswer | ErrorAnswer>;
  /**
   * `get` (section 8.1): the node `args.id`, with its type, label, summary, properties, aliases,
   * external references and link counts, or an error answer naming the closest matches.
   */
  get(args: unknown): Promise<GetAnswer | ErrorAnswer>;
  /**
   * `neighbors` (section 8.1): the edges of the node `args.id`, optionally of one `args.edge`
   * type and `args.direction`, each with the other node's id and label, and the total count, or
   * an error answer.
   */
  neighbors(args: unknown): Promise<NeighborsAnswer | ErrorAnswer>;
  /**
   * `table` (sections 8.1 and 8.6): the nodes of the type `args.type`, a page of 20 rows with the
   * node's id, then its label and declared properties or the columns `args.columns` names
   * (properties, `key`, `label`, `summary`, edges leaving the type), optionally filtered by
   * `args.where`, sorted by `args.order` and paged by `args.page`, or an error answer.
   */
  table(args: unknown): Promise<TableAnswer | ErrorAnswer>;
  /**
   * `cite` (section 8.1): the evidence of the node `args.id`, or of the edge `args.from`,
   * `args.type`, `args.to`, or an error answer.
   */
  cite(args: unknown): Promise<CiteAnswer | ErrorAnswer>;
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
export async function openFile(bytes: Uint8Array, name: string, options: OpenOptions = {}): Promise<SealedFile> {
  const timeLimitMs = options.timeLimitMs ?? TIME_LIMIT_MS;
  if (!(Number.isFinite(timeLimitMs) && timeLimitMs > 0)) {
    throw new RangeError(`timeLimitMs must be a positive number of milliseconds, not ${timeLimitMs}`);
  }
  const [s, expected] = await Promise.all([sqlite(), referenceSchema()]);
  let db: Database;
  try {
    db = load(s, bytes, name);
  } catch (e) {
    throw refused(name, e);
  }
  try {
    const header = verify(db, name, expected);
    return sealedFile(db, name, header, new Deadline(s, db, timeLimitMs), options.embedder);
  } catch (e) {
    db.close();
    throw refused(name, e);
  }
}

/** `e` as a refusal: SQLite's own errors mean the file is not a readable database. */
function refused(name: string, e: unknown): FileRefusedError {
  if (e instanceof FileRefusedError) return e;
  return new FileRefusedError(name, "sqlite", `not a readable SQLite 3 database (${message(e)}) (section 3.1)`);
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** A read-only database holding a copy of `bytes` (section 3.8 step 1). */
function load(s: Sqlite3Static, bytes: Uint8Array, name: string): Database {
  // Refuse what needs no SQLite before a database handle exists, so a refusal leaks nothing.
  refuseUtf16(bytes, name);
  const db = new s.oo1.DB(":memory:", "c");
  try {
    if (bytes.byteLength > 0) {
      // An empty file is read as an empty database, which the checks then refuse.
      const { capi, wasm } = s;
      const pointer = wasm.allocFromTypedArray(walCleared(bytes));
      // With FREEONCLOSE, SQLite frees the copy when the database closes, or at once on failure.
      const flags = capi.SQLITE_DESERIALIZE_FREEONCLOSE | capi.SQLITE_DESERIALIZE_READONLY;
      const rc = capi.sqlite3_deserialize(db, "main", pointer, bytes.byteLength, bytes.byteLength, flags);
      if (rc !== capi.SQLITE_OK) {
        throw new FileRefusedError(
          name,
          "sqlite",
          `not a readable SQLite 3 database (${capi.sqlite3_js_rc_str(rc)}) (section 3.1)`,
        );
      }
    }
    configure(db);
    return db;
  } catch (e) {
    db.close();
    throw e;
  }
}

/** The 16 bytes that open every SQLite 3 database file. */
const SQLITE_MAGIC = new TextEncoder().encode("SQLite format 3\0");

function isSqliteHeader(bytes: Uint8Array): boolean {
  return bytes.byteLength >= 100 && SQLITE_MAGIC.every((b, i) => bytes[i] === b);
}

/**
 * Refuse a file whose text is stored as UTF-16: a tessera or mosaic stores its text as UTF-8
 * (section 3.1, decision B on #104). Bytes 56–59 of the SQLite header hold the text encoding:
 * 1 for UTF-8, 2 for UTF-16le, 3 for UTF-16be. The check reads the bytes, before SQLite: the
 * SQLite WebAssembly the kit runs on is built without UTF-16 and could not read the file.
 */
function refuseUtf16(bytes: Uint8Array, name: string): void {
  if (!isSqliteHeader(bytes)) return;
  const encoding = new DataView(bytes.buffer, bytes.byteOffset + 56, 4).getUint32(0);
  if (encoding === 2 || encoding === 3) {
    const label = encoding === 2 ? "UTF-16le" : "UTF-16be";
    throw new FileRefusedError(
      name,
      "encoding",
      `text encoding ${label}: a tessera or mosaic stores its text as UTF-8 (section 3.1)`,
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
  const header = readHeader(db, name);
  checkHashes(db, name, header);
  return header;
}

/** A header value as the messages show it. */
function shown(value: string | null): string {
  return value === null ? "null" : `'${value}'`;
}

/** Recompute both hashes and compare them with the header's (section 3.8 step 3). */
function checkHashes(db: Database, name: string, header: Header): void {
  const knowledge = hashed(name, "knowledge_hash", "3.6", () => knowledgeHash(db));
  if (knowledge !== header.knowledge_hash) {
    throw new FileRefusedError(
      name,
      "knowledge_hash",
      `knowledge hash mismatch: the header says ${shown(header.knowledge_hash)}, ` +
        `the content gives ${shown(knowledge)} (section 3.6)`,
    );
  }
  const vectors = hashed(name, "vector_hash", "3.7", () => vectorHash(db));
  if (vectors !== header.vector_hash) {
    throw new FileRefusedError(
      name,
      "vector_hash",
      `vector hash mismatch: the header says ${shown(header.vector_hash)}, ` +
        `the vectors give ${shown(vectors)} (section 3.7)`,
    );
  }
}

/** `compute()`, with a value the hash cannot take refused for `rule`. */
function hashed<T>(name: string, rule: RefusalRule, section: string, compute: () => T): T {
  try {
    return compute();
  } catch (e) {
    if (e instanceof UnhashableError) {
      throw new FileRefusedError(name, rule, `${e.message} (section ${section})`);
    }
    throw e;
  }
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
  // CHECK (one = 1) is not enforced on read, so a crafted header can hold any number of rows:
  // read at most two, so it costs nothing to refuse (section 10).
  const rows = db.selectObjects("SELECT * FROM header LIMIT 2");
  if (rows.length !== 1) {
    const found = rows.length === 0 ? "0 rows" : "2 rows or more";
    throw new FileRefusedError(name, "header", `header has ${found}; it must hold exactly one (section 3.3)`);
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

/** Why an embedding was not used: the vector tier is left out, as for an unsupported model. */
class NoVector extends Error {}

/**
 * The vector of `query`, or a `NoVector` when the embedder fails or gives anything but
 * {@link DIMENSIONS} finite numbers, or a `limit_exceeded` error once `limitMs` has passed.
 */
async function embedded(embedder: QueryEmbedder, query: string, limitMs: number, late: () => ToolError): Promise<Float32Array> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(late()), limitMs);
  });
  try {
    const vector = await Promise.race([
      embedder.embedQuery(query).then(
        (v) => v,
        () => {
          throw new NoVector();
        },
      ),
      timeout,
    ]);
    if (!(vector instanceof Float32Array) || vector.length !== DIMENSIONS || !vector.every(Number.isFinite)) {
      throw new NoVector();
    }
    return Float32Array.from(vector);
  } finally {
    clearTimeout(timer);
  }
}

/** Node type names of the form section 3.4 allows. */
const NODE_TYPE_NAME = /^[A-Z][A-Za-z0-9]*$/;

/** The declared node types and their node counts, read once when the file opens. */
function nodeTypes(db: Database): NodeType[] {
  const rows = db.selectArrays(
    `SELECT t.name, (SELECT count(*) FROM node AS n WHERE n.type = t.name)
       FROM type AS t WHERE t.kind = 'node' AND length(t.name) <= 120
      ORDER BY t.name COLLATE BINARY LIMIT ?`,
    [NODE_TYPE_LIMIT],
  );
  return rows
    .filter(([name]) => typeof name === "string" && NODE_TYPE_NAME.test(name))
    .map(([name, count]) => ({ name: String(name), count: Number(count) }));
}

const EDGE_TYPE_NAME = /^[a-z][a-z0-9_]*$/;

function edgeTypes(db: Database): EdgeType[] {
  const rows = db.selectArrays(
    `SELECT name, from_type, to_type FROM type
      WHERE kind = 'edge' AND length(name) <= 120 ORDER BY name COLLATE BINARY LIMIT ?`,
    [NODE_TYPE_LIMIT],
  );
  const named = (value: unknown): string | null =>
    typeof value === "string" && NODE_TYPE_NAME.test(value) ? value : null;
  return rows
    .filter(([name]) => typeof name === "string" && EDGE_TYPE_NAME.test(name))
    .map(([name, from, to]) => ({ name: String(name), from: named(from), to: named(to) }));
}

/** Each listed node type's declared properties, at most {@link NODE_TYPE_LIMIT} each. */
function declaredProps(db: Database, types: readonly NodeType[]): Map<string, readonly string[]> {
  const props = new Map<string, readonly string[]>();
  for (const { name } of types) {
    const keys = db.selectValues(
      `SELECT j.key FROM type AS t, json_each(CASE WHEN json_valid(t.props) THEN t.props ELSE '{}' END) AS j
        WHERE t.name = ? AND t.kind = 'node' AND length(j.key) <= 120 ORDER BY j.id LIMIT ?`,
      [name, NODE_TYPE_LIMIT],
    );
    props.set(name, [...new Set(keys.filter((k): k is string => typeof k === "string"))]);
  }
  return props;
}

function sealedFile(db: Database, name: string, header: Header, deadline: Deadline, embedder?: QueryEmbedder): SealedFile {
  let open = true;
  const types = nodeTypes(db);
  const edges = edgeTypes(db);
  const declared = declaredProps(db, types);
  const mosaic = header.knowledge_hash;
  const vectorSearch =
    embedder !== undefined && header.vector_hash !== null && header.embed_model === embedder.model;
  /** Run one tool call under the time bound; a failed call is an error answer. */
  function answer<T>(tool: ToolName, work: () => T, startedAt?: number): T | ErrorAnswer {
    if (!open) throw new Error(`${name} is closed`);
    try {
      return deadline.run(tool, work, startedAt);
    } catch (e) {
      if (e instanceof ToolError) return errorAnswer(tool, mosaic, e);
      throw e;
    }
  }
  return {
    name,
    header,
    nodeTypes: types,
    edgeTypes: edges,
    propsOf: (type) => declared.get(type) ?? [],
    timeLimitMs: deadline.limitMs,
    vectorSearch,
    find: async (args) => {
      const startedAt = performance.now();
      if (!vectorSearch) return answer("find", () => find(db, mosaic, args));
      // Arguments find refuses are refused before the model runs.
      const checked = answer("find", () => findArgs(db, args));
      if ("error" in checked) return checked;
      let vector: Float32Array | undefined;
      if (hasWords(checked.query)) {
        try {
          vector = await embedded(embedder!, checked.query, deadline.limitMs, () => deadline.exceeded("find"));
        } catch (e) {
          if (e instanceof ToolError) return errorAnswer("find", mosaic, e);
          if (!(e instanceof NoVector)) throw e;
        }
      }
      const vq = vector && { vector, checkpoint: () => deadline.checkpoint() };
      return answer("find", () => find(db, mosaic, args, vq), startedAt);
    },
    get: async (args) => answer("get", () => get(db, mosaic, args)),
    neighbors: async (args) => answer("neighbors", () => neighbors(db, mosaic, args)),
    table: async (args) => answer("table", () => table(db, mosaic, args, () => deadline.checkpoint())),
    cite: async (args) => answer("cite", () => cite(db, mosaic, args)),
    close() {
      if (open) db.close();
      open = false;
    },
  };
}
