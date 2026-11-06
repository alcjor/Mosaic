/**
 * `neighbors` (Specification 0.1, section 8.1): the edges of one node, each with the other node's
 * id and label, and the total count.
 *
 * - `edge` keeps the edges of that declared edge type; a name the mosaic does not declare as an
 *   edge type is `unknown_edge`, never an empty success.
 * - `direction` is `out` (edges that leave the node), `in` (edges that reach it) or `both`, the
 *   default. A loop is listed once each way, as `get` counts it.
 * - Edges come by edge type (UTF-8 bytes), `out` before `in`, then by the other node's id and the
 *   qualifier (UTF-8 bytes), as `get` orders its link counts; `limit` (default and at most 20)
 *   cuts the list, and `total` counts every edge that `edge` and `direction` keep.
 * - An edge's `qualifier` (section 3.4) is shown when it is not empty, so two edges of one type
 *   between the same pair stay apart; like other text §8.2 names no limit for, it is cut at
 *   400 characters with the marker (decision A on #110).
 * - The other node's label is cut at 120 characters with the marker (section 8.2). An edge whose
 *   other node has an id longer than an answer's id can be (512 characters,
 *   `answers.schema.json`) is left out of the list, as from suggestions, and still counted in
 *   `total`, which matches `get`'s link counts.
 */
import type { Database } from "@sqlite.org/sqlite-wasm";
import { type NeighborEdge, type NeighborsAnswer, ToolError, shownArgument } from "./answers.js";
import { RESULT_LIMIT } from "./bounds.js";
import { TEXT_LIMITS } from "./constants.js";
import { ID_LIMIT, OTHER_TEXT_LIMIT, argumentsOf, idArgument, nodeOf, text } from "./lookup.js";

export interface NeighborsArgs {
  readonly id: string;
  readonly edge?: string;
  readonly direction?: "out" | "in" | "both";
  readonly limit?: number;
}

const TAKES = "id, and optional edge, direction (out, in or both) and limit";

const DIRECTIONS = ["out", "in", "both"] as const;

const NEIGHBORS = `
  WITH links(type, direction, other, qualifier) AS (
    SELECT type, 'out', dst, qualifier FROM edge
     WHERE src = $nid AND $direction IN ('out', 'both') AND ($edge IS NULL OR type = $edge)
    UNION ALL
    SELECT type, 'in', src, qualifier FROM edge
     WHERE dst = $nid AND $direction IN ('in', 'both') AND ($edge IS NULL OR type = $edge)
  )
  SELECT type, direction, id, label, qualifier, total FROM (
    SELECT l.type, l.direction, n.id, n.label, l.qualifier, count(*) OVER () AS total
      FROM links AS l JOIN node AS n ON n.nid = l.other
  )
   WHERE length(id) <= $idLimit
   ORDER BY type COLLATE BINARY, direction DESC, id COLLATE BINARY, qualifier COLLATE BINARY
   LIMIT $limit`;

const TOTAL = `
  SELECT (SELECT count(*) FROM edge
           WHERE src = $nid AND $direction IN ('out', 'both') AND ($edge IS NULL OR type = $edge))
       + (SELECT count(*) FROM edge
           WHERE dst = $nid AND $direction IN ('in', 'both') AND ($edge IS NULL OR type = $edge))`;

/** Run `neighbors` on `db`, which passed the reading rules; the caller bounds its time. */
export function neighbors(db: Database, mosaic: string, args: unknown): NeighborsAnswer {
  const given = argumentsOf("neighbors", args, ["id", "edge", "direction", "limit"], TAKES);
  const id = idArgument("neighbors", "id", given.id);
  const { edge, direction, limit } = given;
  if (edge !== undefined && typeof edge !== "string") {
    throw new ToolError("bad_argument", "neighbors' edge must be an edge type name, a string");
  }
  if (direction !== undefined && !DIRECTIONS.includes(direction as (typeof DIRECTIONS)[number])) {
    throw new ToolError("bad_argument", `neighbors' direction must be out, in or both, not ${shownArgument(direction)}`);
  }
  if (limit !== undefined && !(typeof limit === "number" && Number.isInteger(limit) && limit >= 1)) {
    throw new ToolError("bad_argument", `neighbors' limit must be a whole number of 1 or more, not ${shownArgument(limit)}`);
  }
  const nid = nodeOf(db, mosaic, "neighbors", id);
  if (edge !== undefined && db.selectValue("SELECT 1 FROM type WHERE name = ? AND kind = 'edge'", [edge]) === undefined) {
    throw new ToolError("unknown_edge", `${shownArgument(edge)} is not an edge type of this mosaic`);
  }
  const keep = { $nid: nid, $edge: edge ?? null, $direction: (direction as NeighborsArgs["direction"]) ?? "both" };
  const rows = db.selectArrays(NEIGHBORS, { ...keep, $idLimit: ID_LIMIT, $limit: Math.min(limit ?? RESULT_LIMIT, RESULT_LIMIT) });
  const edges = rows.map(([type, way, other, label, qualifier]): NeighborEdge => {
    const found: NeighborEdge = {
      edge: String(type),
      direction: way === "out" ? "out" : "in",
      id: String(other),
      label: text(label, TEXT_LIMITS.label),
    };
    const shown = text(qualifier, OTHER_TEXT_LIMIT);
    return shown === null || shown === "" ? found : { ...found, qualifier: shown };
  });
  const total = rows.length === 0 ? Number(db.selectValue(TOTAL, keep)) : Number(rows[0]![5]);
  return { tool: "neighbors", mosaic, data: { id, edges, total } };
}
