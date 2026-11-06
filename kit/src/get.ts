/**
 * `get` (Specification 0.1, section 8.1): one node by its id, with its type, label, summary,
 * properties, aliases, external references and link counts per edge type and direction.
 *
 * - `aliases` are in alias order (section 3.6: `NOCASE`, then by UTF-8 bytes), at most 20, with
 *   `aliases_total` counting them all (section 8.2).
 * - `external_refs` are in `external_ref` order (section 3.6), each with its system, kind and
 *   locator object, at most 20, with `external_refs_total` (decision D on #110).
 * - `links` count the node's edges in `edge`, which the knowledge hash covers, per edge type and
 *   direction: by edge type (UTF-8 bytes), `out` before `in`. A loop counts once each way. At
 *   most 20, with `links_total` (decision D on #110).
 * - `props` is the node's property object, or null.
 */
import type { Database } from "@sqlite.org/sqlite-wasm";
import type { GetAnswer } from "./answers.js";
import { RESULT_LIMIT } from "./bounds.js";
import { TEXT_LIMITS } from "./constants.js";
import { OTHER_TEXT_LIMIT, argumentsOf, cutJson, idArgument, jsonObject, nodeOf, text } from "./lookup.js";

export interface GetArgs {
  readonly id: string;
}

const NODE = "SELECT id, type, label, summary, props FROM node WHERE nid = ?";

const ALIASES = `
  SELECT text, count(*) OVER () FROM alias WHERE nid = $nid
   ORDER BY text COLLATE NOCASE, text COLLATE BINARY LIMIT $limit`;

const EXTERNAL_REFS = `
  SELECT system, kind, locator, count(*) OVER () FROM external_ref WHERE nid = $nid
   ORDER BY xid LIMIT $limit`;

const LINKS = `
  WITH links(type, direction, count) AS (
    SELECT type, 'out', count(*) FROM edge WHERE src = $nid GROUP BY type
    UNION ALL
    SELECT type, 'in', count(*) FROM edge WHERE dst = $nid GROUP BY type
  )
  SELECT type, direction, count, count(*) OVER () FROM links
   ORDER BY type COLLATE BINARY, direction DESC LIMIT $limit`;

/** Run `get` on `db`, which passed the reading rules; the caller bounds its time. */
export function get(db: Database, mosaic: string, args: unknown): GetAnswer {
  const given = argumentsOf("get", args, ["id"], "id");
  const nid = nodeOf(db, mosaic, "get", idArgument("get", "id", given.id));
  const [id, type, label, summary, props] = db.selectArray(NODE, [nid])!;
  const aliases = db.selectArrays(ALIASES, { $nid: nid, $limit: RESULT_LIMIT });
  const refs = db.selectArrays(EXTERNAL_REFS, { $nid: nid, $limit: RESULT_LIMIT });
  const links = db.selectArrays(LINKS, { $nid: nid, $limit: RESULT_LIMIT });
  const totalOf = (rows: unknown[][], at: number) => (rows.length === 0 ? 0 : Number(rows[0]![at]));
  const parsedProps = jsonObject(props);
  return {
    tool: "get",
    mosaic,
    data: {
      id: String(id),
      type: String(type),
      label: text(label, TEXT_LIMITS.label),
      summary: text(summary, TEXT_LIMITS.summary),
      props: parsedProps === null ? null : (cutJson(parsedProps, OTHER_TEXT_LIMIT) as Record<string, unknown>),
      aliases: aliases.map(([alias]) => text(alias, TEXT_LIMITS.label) ?? ""),
      aliases_total: aliases.length === 0 ? 0 : Number(aliases[0]![1]),
      external_refs: refs.map(([system, kind, locator]) => ({
        system: text(system, OTHER_TEXT_LIMIT) ?? "",
        kind: text(kind, OTHER_TEXT_LIMIT) ?? "",
        locator: (cutJson(jsonObject(locator) ?? {}, OTHER_TEXT_LIMIT) as Record<string, unknown>),
      })),
      external_refs_total: totalOf(refs, 3),
      links: links.map(([edge, direction, count]) => ({
        edge: String(edge),
        direction: direction === "out" ? "out" : "in",
        count: Number(count),
      })),
      links_total: totalOf(links, 3),
    },
  };
}
