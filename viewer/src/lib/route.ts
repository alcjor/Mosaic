/**
 * Where the viewer is, kept in the page's address after `#`, so the browser's back button,
 * links and bookmarks work without a server: `#q=<query>&node=<id>`, both optional. A link to
 * a node keeps the search beside it. An empty `node` is no node.
 *
 * A table view adds `t=<node type>`, and optionally `p=<page>`, `o=<column>` with `d=1` for
 * descending order, and `w=<JSON list of {column, op, value}>`: everything `table` is asked
 * (section 8.6), so a table view can be linked to and reloaded.
 */

/** One `where` condition of `table` (section 8.6). */
export interface Condition {
  readonly column: string;
  readonly op: "=" | "!=" | "<" | "<=" | ">" | ">=" | "contains";
  readonly value: string | number | boolean;
}

export const OPERATORS: readonly Condition["op"][] = ["=", "!=", "<", "<=", ">", ">=", "contains"];

/** What a table view asks `table`. */
export interface TableRoute {
  readonly type: string;
  /** From 1. */
  readonly page: number;
  readonly order: { readonly column: string; readonly desc: boolean } | null;
  readonly where: readonly Condition[];
}

export interface Route {
  /** The search box's query; empty when there is none. */
  readonly query: string;
  /** The id of the node whose page is open, or null. */
  readonly node: string | null;
  /** The table view open, or null. */
  readonly table?: TableRoute | null;
}

function isCondition(value: unknown): value is Condition {
  if (typeof value !== "object" || value === null) return false;
  const c = value as Record<string, unknown>;
  return (
    typeof c.column === "string" &&
    OPERATORS.includes(c.op as Condition["op"]) &&
    (typeof c.value === "string" || typeof c.value === "number" || typeof c.value === "boolean")
  );
}

function conditions(text: string | null): Condition[] {
  if (text === null) return [];
  try {
    const parsed: unknown = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.filter(isCondition) : [];
  } catch {
    return [];
  }
}

/** The route a location hash names; anything it does not name is empty. */
export function parseRoute(hash: string): Route {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const node = params.get("node");
  const type = params.get("t");
  const pageText = params.get("p");
  const page = pageText !== null && /^[1-9][0-9]{0,8}$/.test(pageText) ? Number(pageText) : 1;
  const column = params.get("o");
  const table =
    type === null || type === ""
      ? null
      : {
          type,
          page,
          order: column === null || column === "" ? null : { column, desc: params.get("d") === "1" },
          where: conditions(params.get("w")),
        };
  const route: Route = { query: params.get("q") ?? "", node: node === null || node === "" ? null : node };
  return table === null ? route : { ...route, table };
}

/** The location hash of `route`, as {@link parseRoute} reads it. */
export function routeHash(route: Route): string {
  const params = new URLSearchParams();
  if (route.query !== "") params.set("q", route.query);
  if (route.node !== null) params.set("node", route.node);
  const table = route.table;
  if (table) {
    params.set("t", table.type);
    if (table.page !== 1) params.set("p", String(table.page));
    if (table.order) {
      params.set("o", table.order.column);
      if (table.order.desc) params.set("d", "1");
    }
    if (table.where.length > 0) params.set("w", JSON.stringify(table.where));
  }
  const text = params.toString();
  return text === "" ? "#" : `#${text}`;
}
