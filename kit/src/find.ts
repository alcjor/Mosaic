/**
 * `find` by its exact and full-text tiers (Specification 0.1, sections 8.1 and 8.5).
 *
 * Results come in tiers, each tagged in the answer:
 *
 * 1. `exact`: nodes whose id or key equals the query, and nodes with an alias equal to it
 *    (aliases compare without regard to ASCII case, as `format.sql` declares them), by id;
 * 2. `text`: full-text hits not already listed, best rank (FTS5's bm25) first, ties by id.
 *
 * Ids compare by UTF-8 bytes (SQLite's BINARY collation on UTF-8 text). The query is searched
 * as text (section 10): every whitespace-separated word becomes one quoted FTS5 string, which
 * the index's own tokenizer splits, so quotes, `*`, `OR`, `NEAR`, `:`, `^` and brackets are
 * characters, never operators. A node is a full-text hit when it holds every word of the query,
 * in any order and column (FTS5's implicit AND; decision A on #109); a word with no letters or
 * digits, such as `*`, adds nothing, and a query with no words is an empty success (decision D).
 * `type` keeps the nodes of that node type; `limit` (default and at most 20) cuts
 * the list, and `total` counts every node either tier matched.
 *
 * 3. `vector`, when the caller gives the query's vector (the mosaic holds vectors of a model the
 *    kit supports, section 3.8): nodes not already listed, by score (section 6), highest first,
 *    ties by id. They fill the room the first two tiers leave in the list, and `total` counts
 *    the exact and text matches plus the vector matches listed (decision C on #111). A query
 *    with no words has no vector tier (decision D on #109).
 */
import type { Database } from "@sqlite.org/sqlite-wasm";
import { type FindAnswer, type FindResult, ToolError, shownArgument } from "./answers.js";
import { QUERY_LIMIT, RESULT_LIMIT } from "./bounds.js";
import { TEXT_LIMITS, cut } from "./constants.js";
import { compareUtf8, score } from "./vectors.js";

export interface FindArgs {
  readonly query: string;
  readonly type?: string;
  readonly limit?: number;
}

const ARGUMENTS = new Set(["query", "type", "limit"]);

/** `args` checked as `find`'s arguments (section 8.1), or a `bad_argument` error. */
function checked(args: unknown): FindArgs {
  if (typeof args !== "object" || args === null || Array.isArray(args)) {
    throw new ToolError("bad_argument", "find takes an object of arguments: query, and optional type and limit");
  }
  const given = args as Record<string, unknown>;
  for (const name of Object.keys(given).sort()) {
    if (!ARGUMENTS.has(name)) {
      throw new ToolError(
        "bad_argument",
        `find has no argument ${shownArgument(name)}; it takes query, and optional type and limit`,
      );
    }
  }
  const { query, type, limit } = given;
  if (typeof query !== "string") throw new ToolError("bad_argument", "find needs query, a string");
  if (type !== undefined && typeof type !== "string") {
    throw new ToolError("bad_argument", "find's type must be a node type name, a string");
  }
  if (limit !== undefined && !(typeof limit === "number" && Number.isInteger(limit) && limit >= 1)) {
    throw new ToolError("bad_argument", `find's limit must be a whole number of 1 or more, not ${shownArgument(limit)}`);
  }
  const out: { query: string; type?: string; limit?: number } = { query };
  if (type !== undefined) out.type = type;
  if (limit !== undefined) out.limit = limit;
  return out;
}

/**
 * The FTS5 expression that searches `query` as text: each word one quoted string. A query with
 * no words is the empty string `""`, which matches nothing.
 */
export function textQuery(query: string): string {
  const words = query
    .replace(/\u0000/g, " ")
    .split(/\s+/u)
    .filter((word) => word !== "")
    .map((word) => `"${word.replace(/"/g, '""')}"`);
  return words.length === 0 ? '""' : words.join(" ");
}

const EXACT = `
  SELECT nid FROM node WHERE id = $query
  UNION SELECT nid FROM node
        WHERE type IN (SELECT name FROM type WHERE kind = 'node') AND key = $query
  UNION SELECT nid FROM alias WHERE text = $query`;

const FIND = `
  WITH exact(nid) AS (${EXACT}),
  hits(tier, score, nid) AS (
    SELECT 0, 0.0, nid FROM exact
    UNION ALL
    SELECT 1, rank, rowid FROM search
     WHERE search MATCH $text AND rowid NOT IN (SELECT nid FROM exact)
  )
  SELECT n.id, n.type, n.label, h.tier, count(*) OVER () AS total
    FROM hits AS h JOIN node AS n ON n.nid = h.nid
   WHERE $type IS NULL OR n.type = $type
   ORDER BY h.tier, h.score, n.id
   LIMIT $limit`;

const HIT_NIDS = `
  WITH exact(nid) AS (${EXACT}),
  hits(nid) AS (
    SELECT nid FROM exact
    UNION SELECT rowid FROM search WHERE search MATCH $text
  )
  SELECT h.nid FROM hits AS h JOIN node AS n ON n.nid = h.nid
   WHERE $type IS NULL OR n.type = $type`;

const VECTORS = `
  SELECT v.nid, n.id, n.type, n.label, v.bits
    FROM vector AS v JOIN node AS n ON n.nid = v.nid
   WHERE $type IS NULL OR n.type = $type`;

const TIERS = ["exact", "text"] as const;

/** What the vector tier needs: the query's vector, and a check of the time bound. */
export interface VectorQuery {
  readonly vector: Float32Array;
  /** Throws once the tool call's time bound has passed. */
  readonly checkpoint: () => void;
}

/**
 * True when `query` holds a word, a letter or a digit: only then is there a vector tier. A query
 * of punctuation alone, like one of white space, is a query with no words (decision D on #109).
 */
export function hasWords(query: string): boolean {
  return /[\p{L}\p{N}]/u.test(query);
}

/** `args` checked as `find` checks them against `db`, or the `ToolError` `find` would give. */
export function findArgs(db: Database, args: unknown): FindArgs {
  const given = checked(args);
  const { query, type } = given;
  if (Array.from(query).length > QUERY_LIMIT) {
    throw new ToolError(
      "limit_exceeded",
      `find's query is longer than the kit's bound of ${QUERY_LIMIT} characters (section 3.8 step 4)`,
    );
  }
  if (type !== undefined) {
    const declared = db.selectValue("SELECT 1 FROM type WHERE name = ? AND kind = 'node'", [type]);
    if (declared === undefined) {
      throw new ToolError("unknown_type", `${shownArgument(type)} is not a node type of this mosaic`);
    }
  }
  return given;
}

/** Run `find` on `db`, which passed the reading rules; the caller bounds its time. */
export function find(db: Database, mosaic: string, args: unknown, vectorQuery?: VectorQuery): FindAnswer {
  const { query, type, limit } = findArgs(db, args);
  const room = Math.min(limit ?? RESULT_LIMIT, RESULT_LIMIT);
  const bind = { $query: query, $text: textQuery(query), $type: type ?? null };
  const rows = db.selectArrays(FIND, { ...bind, $limit: room });
  const results: FindResult[] = rows.map(([id, nodeType, label, tier]) => ({
    id: String(id),
    type: String(nodeType),
    label: typeof label === "string" ? cut(label, TEXT_LIMITS.label) : null,
    match: TIERS[Number(tier)]!,
  }));
  let total = rows.length === 0 ? 0 : Number(rows[0]![4]);
  if (vectorQuery !== undefined && hasWords(query) && results.length < room) {
    const listed = new Set(db.selectArrays(HIT_NIDS, bind).map(([nid]) => Number(nid)));
    // The best `want` nodes, kept sorted as the rows go by: memory stays within the list's room.
    const want = room - results.length;
    const scored: { id: string; type: string; label: unknown; score: number }[] = [];
    const before = (a: { id: string; score: number }, b: { id: string; score: number }) =>
      a.score > b.score || (a.score === b.score && compareUtf8(a.id, b.id) < 0);
    for (const [nid, id, nodeType, label, bits] of db.selectArrays(VECTORS, { $type: bind.$type })) {
      vectorQuery.checkpoint();
      if (listed.has(Number(nid)) || !(bits instanceof Uint8Array)) continue;
      const node = { id: String(id), type: String(nodeType), label, score: score(vectorQuery.vector, bits) };
      if (scored.length === want && !before(node, scored[want - 1]!)) continue;
      let at = scored.length;
      while (at > 0 && before(node, scored[at - 1]!)) at -= 1;
      scored.splice(at, 0, node);
      if (scored.length > want) scored.pop();
    }
    for (const node of scored) {
      results.push({
        id: node.id,
        type: node.type,
        label: typeof node.label === "string" ? cut(node.label, TEXT_LIMITS.label) : null,
        match: "vector",
      });
      total += 1;
    }
  }
  return { tool: "find", mosaic, data: { results, total } };
}
