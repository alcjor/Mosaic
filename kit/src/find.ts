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
 */
import type { Database } from "@sqlite.org/sqlite-wasm";
import { type FindAnswer, ToolError, shownArgument } from "./answers.js";
import { QUERY_LIMIT, RESULT_LIMIT } from "./bounds.js";
import { TEXT_LIMITS, cut } from "./constants.js";

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

const TIERS = ["exact", "text"] as const;

/** Run `find` on `db`, which passed the reading rules; the caller bounds its time. */
export function find(db: Database, mosaic: string, args: unknown): FindAnswer {
  const { query, type, limit } = checked(args);
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
  const rows = db.selectArrays(FIND, {
    $query: query,
    $text: textQuery(query),
    $type: type ?? null,
    $limit: Math.min(limit ?? RESULT_LIMIT, RESULT_LIMIT),
  });
  const results = rows.map(([id, nodeType, label, tier]) => ({
    id: String(id),
    type: String(nodeType),
    label: typeof label === "string" ? cut(label, TEXT_LIMITS.label) : null,
    match: TIERS[Number(tier)]!,
  }));
  const total = rows.length === 0 ? 0 : Number(rows[0]![4]);
  return { tool: "find", mosaic, data: { results, total } };
}
