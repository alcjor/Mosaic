/**
 * What `get` and `cite` share (Specification 0.1, sections 8.1 and 8.2): checking their
 * arguments, finding a node by its id, the error for an unknown id, and cutting text read from
 * the file.
 *
 * - An id is taken exactly as given: no trimming, no case folding; a key or an alias is not an
 *   id. An unknown id is an `unknown_id` error naming the closest matches from `find` (section
 *   8.1): `find` on the id, then, for an id of the form `<type>:<key>`, `find` on its key, at
 *   most 5 distinct ids.
 * - Text read from the file goes only into `data`, cut with the marker (section 8.2): labels and
 *   aliases at 120 characters, summaries at 400, snippets at 600, and every other text value
 *   (property names and text values, locators, source ids, external references) at 400.
 */
import type { Database } from "@sqlite.org/sqlite-wasm";
import { ToolError, shownArgument } from "./answers.js";
import { QUERY_LIMIT } from "./bounds.js";
import { TEXT_LIMITS, cut, type ToolName } from "./constants.js";
import { find } from "./find.js";

/** Longest id an answer holds (`answers.schema.json`, `id`). */
export const ID_LIMIT = 512;

/** Most suggestions an error names (`answers.schema.json`, `error.suggestions`). */
const SUGGESTION_LIMIT = 5;

/** The limit of text read from the file that §8.2 names no limit for. */
export const OTHER_TEXT_LIMIT = TEXT_LIMITS.summary;

/** `args` as an object of arguments of `tool`, whose names are all in `names`. */
export function argumentsOf(tool: ToolName, args: unknown, names: readonly string[], takes: string): Record<string, unknown> {
  if (typeof args !== "object" || args === null || Array.isArray(args)) {
    throw new ToolError("bad_argument", `${tool} takes an object of arguments: ${takes}`);
  }
  const given = args as Record<string, unknown>;
  for (const name of Object.keys(given).sort()) {
    if (!names.includes(name)) {
      throw new ToolError("bad_argument", `${tool} has no argument ${shownArgument(name)}; it takes ${takes}`);
    }
  }
  return given;
}

/** `value` as the id argument `name` of `tool`: a string of at most {@link ID_LIMIT} characters. */
export function idArgument(tool: ToolName, name: string, value: unknown): string {
  if (typeof value !== "string") throw new ToolError("bad_argument", `${tool} needs ${name}, a node id, a string`);
  if (Array.from(value).length > ID_LIMIT) {
    throw new ToolError("bad_argument", `${tool}'s ${name} is longer than an id can be, ${ID_LIMIT} characters`);
  }
  return value;
}

/** The closest matches from `find` for an id no node has. */
function suggestions(db: Database, mosaic: string, id: string): string[] {
  const queries = [id];
  const colon = id.indexOf(":");
  if (colon > 0 && colon < id.length - 1) queries.push(id.slice(colon + 1));
  const out: string[] = [];
  for (const query of queries) {
    if (Array.from(query).length > QUERY_LIMIT) continue;
    for (const result of find(db, mosaic, { query, limit: SUGGESTION_LIMIT }).data.results) {
      if (out.length < SUGGESTION_LIMIT && !out.includes(result.id) && Array.from(result.id).length <= ID_LIMIT) {
        out.push(result.id);
      }
    }
  }
  return out;
}

/** The `nid` of the node `id`, or an `unknown_id` error naming the closest matches. */
export function nodeOf(db: Database, mosaic: string, tool: ToolName, id: string): number {
  const nid = db.selectValue("SELECT nid FROM node WHERE id = ?", [id]);
  if (typeof nid === "number") return nid;
  if (typeof nid === "bigint") return Number(nid);
  throw new ToolError("unknown_id", `${tool}: no node has the id ${shownArgument(id)}; see the suggestions`, suggestions(db, mosaic, id));
}

/** Text read from the file, cut at `limit`; anything else (NULL included) as null. */
export function text(value: unknown, limit: number): string | null {
  return typeof value === "string" ? cut(value, limit) : null;
}

/**
 * A JSON value read from the file, with every string in it, object keys included, cut at
 * `limit`. Keys become own properties whatever their name (`__proto__` included), so no key
 * the file holds is lost or reaches the object's prototype; two keys that are the same once cut
 * keep the later value.
 */
export function cutJson(value: unknown, limit: number): unknown {
  if (typeof value === "string") return cut(value, limit);
  if (Array.isArray(value)) return value.map((v) => cutJson(v, limit));
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [cut(k, limit), cutJson(v, limit)]));
  }
  return value;
}

/** JSON text read from the file as an object, or null when it is NULL or not an object. */
export function jsonObject(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "string") return null;
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}
