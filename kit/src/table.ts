/**
 * `table` (Specification 0.1, section 8.1): the rows of one node type, with its declared
 * properties as columns.
 *
 * - `type` is a node type the mosaic declares. Anything else (an edge type included) is
 *   `unknown_type`, never an empty success, and the message names the closest node types by
 *   edit distance, at most 5: only names of the form section 3.4 allows, which hold nothing but
 *   letters and digits, as `find`'s suggestions hold ids.
 * - `data.columns` is `id`, then the declared properties shown: by default the type's declared
 *   properties in the order its `props` object holds them, the first 20 (section 8.2 cuts lists
 *   at 20); with `columns`, those named, in the order given, at most 20 and each once. Each row
 *   holds the node's id, then each column's value as the node's `props` holds it (a string,
 *   number, boolean, array or object), or null when the node has no such property.
 * - `where` is one condition `{column, op, value}` or a list of at most 20, all of which must
 *   hold. `column` is a declared property of the type; `op` is one of `=`, `!=`, `<`, `<=`, `>`,
 *   `>=` and `contains`; `value` is a string, a number or a boolean, and a string for
 *   `contains`. A condition holds only on a node that has the property with a value of the same
 *   kind: text compares by UTF-8 bytes, numbers by value, `false` before `true`; `!=` holds on a
 *   node whose value is not null and not equal, whatever its kind; `contains` holds on a text
 *   value that holds the given text, by bytes. Names and values are bound as parameters, so a
 *   value holding SQL is a value and no part of a query comes from the caller or the file.
 * - `order` is a declared property, `{column, direction}` with `asc` (default) or `desc`, or a
 *   list of at most 20 of these. Values order as SQLite orders them: null (no value) first,
 *   then numbers (booleans as 0 and 1), then text, arrays and objects together, text by its
 *   UTF-8 bytes and arrays and objects by those of their JSON text; `desc` reverses that. Ties, and every call without `order`, go by id
 *   (UTF-8 bytes).
 * - `page` (default 1) picks 20 rows at a time; `total` counts every node of the type that
 *   `where` keeps, so a page past the last is an empty success with the total.
 * - Text read from the file is cut at 400 characters with the marker (section 8.2, as `get`
 *   cuts property values; decision A on #110), in values, inside arrays and objects, and in
 *   column names; ids are whole. A node whose id is longer than an answer's id can be (512
 *   characters) is left out of the rows and still counted in `total`, as in `neighbors`.
 */
import type { Database } from "@sqlite.org/sqlite-wasm";
import { type TableAnswer, ToolError, shownArgument } from "./answers.js";
import { QUERY_LIMIT, RESULT_LIMIT } from "./bounds.js";
import { ID_LIMIT, OTHER_TEXT_LIMIT, argumentsOf, cutJson } from "./lookup.js";

/** One `where` condition. */
export interface TableCondition {
  readonly column: string;
  readonly op: "=" | "!=" | "<" | "<=" | ">" | ">=" | "contains";
  readonly value: string | number | boolean;
}

/** One `order` key. */
export type TableOrder = string | { readonly column: string; readonly direction?: "asc" | "desc" };

export interface TableArgs {
  readonly type: string;
  readonly columns?: readonly string[];
  readonly where?: TableCondition | readonly TableCondition[];
  readonly order?: TableOrder | readonly TableOrder[];
  readonly page?: number;
}

const TAKES = "type, and optional columns, where, order and page";

const OPERATORS = ["=", "!=", "<", "<=", ">", ">=", "contains"] as const;

type Operator = (typeof OPERATORS)[number];

/** Most closest types an unknown type's message names. */
const CLOSEST = 5;

/** A node type name (section 3.4), safe to name in a message. */
const TYPE_NAME = /^[A-Z][A-Za-z0-9]*$/;

/** Longest type name an unknown type's message names. */
const SHOWN_TYPE_LIMIT = 40;

/** The JSON kinds `json_each` reports that a value of each argument kind compares with. */
const KINDS = { string: "'text'", number: "'integer', 'real'", boolean: "'true', 'false'" } as const;

/** A property's value as a comparable SQL value: booleans as 0 and 1, no value as NULL. */
const VALUE = "CASE p.type WHEN 'true' THEN 1 WHEN 'false' THEN 0 WHEN 'null' THEN NULL ELSE p.value END";

interface Condition {
  readonly column: string;
  readonly op: Operator;
  readonly value: string | number | boolean;
}

interface OrderKey {
  readonly column: string;
  readonly desc: boolean;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** `value` as a list: one item becomes a list of one; at most {@link RESULT_LIMIT} items. */
function listOf(name: string, value: unknown, single: (v: unknown) => boolean): unknown[] {
  const list = Array.isArray(value) ? value : single(value) ? [value] : undefined;
  if (list === undefined || list.length === 0 || list.length > RESULT_LIMIT) {
    throw new ToolError("bad_argument", `table's ${name} must be one entry or a list of 1 to ${RESULT_LIMIT}`);
  }
  return list;
}

function columnName(name: string, value: unknown): string {
  if (typeof value !== "string") throw new ToolError("bad_argument", `table's ${name} must name a column, a string`);
  if (Array.from(value).length > QUERY_LIMIT) {
    throw new ToolError("bad_argument", `table's ${name} is longer than ${QUERY_LIMIT} characters`);
  }
  return value;
}

function columnsArgument(value: unknown): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0 || value.length > RESULT_LIMIT) {
    throw new ToolError("bad_argument", `table's columns must be a list of 1 to ${RESULT_LIMIT} declared property names`);
  }
  const columns = value.map((c) => columnName("columns", c));
  if (new Set(columns).size !== columns.length) {
    throw new ToolError("bad_argument", "table's columns must name each property once");
  }
  return columns;
}

function whereArgument(value: unknown): Condition[] {
  if (value === undefined) return [];
  return listOf("where", value, isObject).map((c): Condition => {
    if (!isObject(c)) throw new ToolError("bad_argument", "each condition of table's where is {column, op, value}");
    for (const key of Object.keys(c).sort()) {
      if (!["column", "op", "value"].includes(key)) {
        throw new ToolError("bad_argument", `a condition of table's where has no ${shownArgument(key)}; it is {column, op, value}`);
      }
    }
    const column = columnName("where column", c.column);
    const op = c.op;
    if (typeof op !== "string" || !OPERATORS.includes(op as Operator)) {
      throw new ToolError("bad_argument", `table's where allows ${OPERATORS.join(", ")}, not ${shownArgument(op)}`);
    }
    const v = c.value;
    const ok =
      op === "contains"
        ? typeof v === "string"
        : typeof v === "string" || typeof v === "boolean" || (typeof v === "number" && Number.isFinite(v));
    if (!ok) {
      const kinds = op === "contains" ? "a string" : "a string, a number or a boolean";
      throw new ToolError("bad_argument", `table's where value for ${op} must be ${kinds}, not ${shownArgument(v)}`);
    }
    if (typeof v === "string" && Array.from(v).length > QUERY_LIMIT) {
      throw new ToolError("bad_argument", `table's where value is longer than ${QUERY_LIMIT} characters`);
    }
    return { column, op: op as Operator, value: v as Condition["value"] };
  });
}

function orderArgument(value: unknown): OrderKey[] {
  if (value === undefined) return [];
  return listOf("order", value, (v) => typeof v === "string" || isObject(v)).map((o): OrderKey => {
    if (typeof o === "string") return { column: columnName("order", o), desc: false };
    if (!isObject(o)) throw new ToolError("bad_argument", "each key of table's order is a column name or {column, direction}");
    for (const key of Object.keys(o).sort()) {
      if (key !== "column" && key !== "direction") {
        throw new ToolError("bad_argument", `a key of table's order has no ${shownArgument(key)}; it is {column, direction}`);
      }
    }
    const column = columnName("order column", o.column);
    const direction = o.direction ?? "asc";
    if (direction !== "asc" && direction !== "desc") {
      throw new ToolError("bad_argument", `table's order direction must be asc or desc, not ${shownArgument(direction)}`);
    }
    return { column, desc: direction === "desc" };
  });
}

function pageArgument(value: unknown): number {
  if (value === undefined) return 1;
  if (!(typeof value === "number" && Number.isSafeInteger(value) && value >= 1)) {
    throw new ToolError("bad_argument", `table's page must be a whole number of 1 or more, not ${shownArgument(value)}`);
  }
  return value;
}

/** Levenshtein distance between `a` and `b`, by code point. */
function distance(a: string, b: string): number {
  const x = Array.from(a);
  const y = Array.from(b);
  let row = Array.from({ length: y.length + 1 }, (_, j) => j);
  for (let i = 1; i <= x.length; i++) {
    const next = [i];
    for (let j = 1; j <= y.length; j++) {
      next[j] = Math.min(row[j]! + 1, next[j - 1]! + 1, row[j - 1]! + (x[i - 1] === y[j - 1] ? 0 : 1));
    }
    row = next;
  }
  return row[y.length]!;
}

function byBytes(a: string, b: string): number {
  // Type names hold ASCII letters and digits only, so code unit order is byte order.
  return a < b ? -1 : a > b ? 1 : 0;
}

/** The `unknown_type` error for `type`, naming the closest node types. */
function unknownType(db: Database, type: string, checkpoint: () => void): ToolError {
  const asked = Array.from(type.toLowerCase()).slice(0, SHOWN_TYPE_LIMIT * 2).join("");
  const names = db
    .selectValues("SELECT name FROM type WHERE kind = 'node' AND length(name) <= ?", [SHOWN_TYPE_LIMIT])
    .filter((n): n is string => typeof n === "string" && TYPE_NAME.test(n));
  const closest = names
    .map((name) => {
      checkpoint();
      return { name, d: distance(asked, name.toLowerCase()) };
    })
    .sort((a, b) => a.d - b.d || byBytes(a.name, b.name))
    .slice(0, CLOSEST)
    .map((c) => c.name);
  const named = closest.length === 0 ? "this mosaic declares no node type" : `the closest node types: ${closest.join(", ")}`;
  return new ToolError("unknown_type", `table: ${shownArgument(type)} is not a node type of this mosaic; ${named}`);
}

/** The `unknown_column` error for `column` of `type`; it names no property read from the file. */
function unknownColumn(type: string, column: string): ToolError {
  return new ToolError(
    "unknown_column",
    `table: ${shownArgument(column)} is not a declared property of ${type}; table on ${type} without columns lists them (the id column is always first)`,
  );
}

/** The value of property `$<n>` of node `n`, as JSON text, or NULL. */
const shown = (n: string) => `(SELECT n.props -> p.fullkey FROM json_each(n.props) AS p WHERE p.key = ${n} LIMIT 1)`;

/** An SQL condition on property `$<c>` compared with `$<v>`, both bound by the caller. */
function condition(c: Condition, col: string, val: string): string {
  if (c.op === "contains") {
    return `EXISTS (SELECT 1 FROM json_each(n.props) AS p WHERE p.key = ${col} AND p.type = 'text' AND instr(p.value, ${val}) > 0)`;
  }
  const kinds = KINDS[typeof c.value as keyof typeof KINDS];
  const same = (op: string) => `p.type IN (${kinds}) AND (${VALUE}) ${op} ${val}`;
  if (c.op === "!=") {
    return `EXISTS (SELECT 1 FROM json_each(n.props) AS p WHERE p.key = ${col} AND p.type <> 'null' AND NOT (${same("=")}))`;
  }
  return `EXISTS (SELECT 1 FROM json_each(n.props) AS p WHERE p.key = ${col} AND ${same(c.op)})`;
}

/**
 * Run `table` on `db`, which passed the reading rules; the caller bounds its time, and
 * `checkpoint` throws once the bound has passed, for the work done outside SQLite.
 */
export function table(db: Database, mosaic: string, args: unknown, checkpoint: () => void = () => {}): TableAnswer {
  const given = argumentsOf("table", args, ["type", "columns", "where", "order", "page"], TAKES);
  const type = given.type;
  if (typeof type !== "string") throw new ToolError("bad_argument", "table needs type, a node type name, a string");
  if (Array.from(type).length > QUERY_LIMIT) {
    throw new ToolError("bad_argument", `table's type is longer than ${QUERY_LIMIT} characters`);
  }
  const asked = columnsArgument(given.columns);
  const where = whereArgument(given.where);
  const order = orderArgument(given.order);
  const page = pageArgument(given.page);

  const props = db.selectValue("SELECT props FROM type WHERE name = ? AND kind = 'node'", [type]);
  if (props === undefined) throw unknownType(db, type, checkpoint);
  const declared: string[] = [];
  for (const key of db.selectValues("SELECT key FROM json_each(?)", [typeof props === "string" ? props : "{}"])) {
    if (typeof key === "string" && !declared.includes(key)) declared.push(key);
  }
  const known = (column: string): string => {
    if (!declared.includes(column)) throw unknownColumn(type, column);
    return column;
  };
  const columns = asked === undefined ? declared.slice(0, RESULT_LIMIT) : asked.map(known);
  where.forEach((c) => known(c.column));
  order.forEach((o) => known(o.column));

  const bind: Record<string, string | number> = { $type: type };
  const filter = where.map((c, i) => {
    bind[`$wc${i}`] = c.column;
    bind[`$wv${i}`] = typeof c.value === "boolean" ? (c.value ? 1 : 0) : c.value;
    return ` AND ${condition(c, `$wc${i}`, `$wv${i}`)}`;
  });
  const from = `FROM node AS n WHERE n.type = $type${filter.join("")}`;
  const total = Number(db.selectValue(`SELECT count(*) ${from}`, bind));

  const offset = (page - 1) * RESULT_LIMIT;
  let rows: unknown[][] = [];
  if (offset < total) {
    const values = columns.map((c, i) => {
      bind[`$c${i}`] = c;
      return shown(`$c${i}`);
    });
    const keys = order.map((o, i) => {
      bind[`$o${i}`] = o.column;
      const value = `(SELECT ${VALUE} FROM json_each(n.props) AS p WHERE p.key = $o${i} LIMIT 1)`;
      return `${value} ${o.desc ? "DESC" : "ASC"}`;
    });
    const sql =
      `SELECT ${["n.id", ...values].join(", ")} ${from} AND length(n.id) <= ${ID_LIMIT}` +
      ` ORDER BY ${[...keys, "n.id COLLATE BINARY"].join(", ")} LIMIT ${RESULT_LIMIT} OFFSET $offset`;
    rows = db.selectArrays(sql, { ...bind, $offset: offset }).map(([id, ...cells]) => [
      String(id),
      ...cells.map((cell) => (typeof cell === "string" ? cutJson(JSON.parse(cell) as unknown, OTHER_TEXT_LIMIT) : null)),
    ]);
  }
  return {
    tool: "table",
    mosaic,
    data: { type, columns: ["id", ...columns.map((c) => cutJson(c, OTHER_TEXT_LIMIT) as string)], rows, page, total },
  };
}
