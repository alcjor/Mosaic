/**
 * Tables rebuilt from node types (docs/design.md, First milestone: Viewer; Specification 0.1,
 * sections 8.1 and 8.6): every page of a table view is one `table` call, with the view's
 * sorting, filters and page. The page sorts, filters and pages nothing itself.
 */
import type { SealedFile, TableAnswer } from "@mosaic/kit";
import type { ToolFailure } from "./mosaic.js";
import type { Condition, TableRoute } from "./route.js";

/** Rows a `table` page holds (section 8.6). */
export const PAGE_ROWS = 20;

export interface TableView {
  readonly route: TableRoute;
  /** `id`, then the columns shown. */
  readonly columns: readonly string[];
  readonly rows: readonly (readonly unknown[])[];
  readonly page: number;
  readonly total: number;
  /** How many pages `total` makes, at least 1. */
  readonly pages: number;
}

/**
 * The arguments of `table` for a table view; with `columns`, the view file's, the node's name
 * (`label`) then those columns, else `table`'s default.
 */
export function tableArgs(route: TableRoute, columns: readonly string[] | null = null): Record<string, unknown> {
  const args: Record<string, unknown> = { type: route.type, page: route.page };
  if (columns !== null) args.columns = ["label", ...columns.filter((c) => c !== "label")];
  if (route.order) args.order = { column: route.order.column, direction: route.order.desc ? "desc" : "asc" };
  if (route.where.length > 0) args.where = route.where.map((c) => ({ column: c.column, op: c.op, value: c.value }));
  return args;
}

/** One page of a table view, from `table`. */
export async function tableView(
  file: SealedFile,
  route: TableRoute,
  columns: readonly string[] | null = null,
): Promise<TableView | ToolFailure> {
  const answer = await file.table(tableArgs(route, columns));
  if ("error" in answer) return { message: answer.error.message, suggestions: answer.error.suggestions };
  const data: TableAnswer["data"] = answer.data;
  return {
    route,
    columns: data.columns,
    rows: data.rows,
    page: data.page,
    total: data.total,
    pages: Math.max(1, Math.ceil(data.total / PAGE_ROWS)),
  };
}

/** The value a filter's text stands for, read as the kind the reader picked. */
export function filterValue(text: string, kind: "text" | "number" | "boolean"): Condition["value"] | null {
  if (kind === "text") return text;
  if (kind === "boolean") return text.trim() === "true" ? true : text.trim() === "false" ? false : null;
  const n = Number(text.trim());
  return text.trim() !== "" && Number.isFinite(n) ? n : null;
}

/** A cell as text: text as it is, lists joined by commas, other values as JSON, null as empty. */
export function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value) && value.every((v) => typeof v === "string" || v === null)) {
    return value.map((v) => v ?? "").join(", ");
  }
  return JSON.stringify(value);
}
