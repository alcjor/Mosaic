/**
 * `table` (Specification 0.1, sections 8.1 and 8.6): the rows of one node type, laid out as a
 * source table would show them.
 *
 * - `type` is a node type the mosaic declares. Anything else (an edge type included) is
 *   `unknown_type`, never an empty success, and the message names the closest node types by
 *   edit distance, at most 5: only names of the form section 3.4 allows, which hold nothing but
 *   letters and digits, as `find`'s suggestions hold ids.
 * - A column name means, in this order: a declared property of the type; the node field `key`,
 *   `label` or `summary`; an edge type whose `from_type` is the type. Any other name in
 *   `columns`, `where` or `order` is `unknown_column`.
 * - `data.columns` is `id`, then the columns shown: by default `label`, then the declared
 *   properties in the order the type's `props` object holds them, 20 in all; with `columns`,
 *   those named, in the order given, at most 20 and each once. A property's cell is its value as
 *   stored, or null when the node has none; a field's cell is its text or null; an edge's cell
 *   is the labels of the nodes those edges lead to, one per node, by their ids, never cut at 20.
 * - `where` is one condition `{column, op, value}` or a list of at most 20, all of which must
 *   hold. A condition compares only values of its own kind (text by UTF-8 bytes, numbers by
 *   value, booleans with booleans); `!=` holds on every node whose value is not the given one,
 *   nodes without a value included. `contains` takes text and ignores case (Unicode default
 *   lowercase mapping, by {@link FOLD}); it holds on text, and on a list with a text item, that
 *   contains it. Names and values are bound as parameters, so a value holding SQL is a value and
 *   no part of a query comes from the caller or the file.
 * - `order` is a column name, `{column, direction}` with `asc` (default) or `desc`, or a list of
 *   at most 20 of these. Values sort in groups kept in both directions: booleans, numbers, text,
 *   lists, objects (by JSON text), then no value; `desc` reverses inside each group. Ties, and
 *   every call without `order`, go by id (UTF-8 bytes).
 * - `page` (default 1) picks 20 rows at a time; `total` counts every node of the type that
 *   `where` keeps, so a page past the last is an empty success with the total.
 * - Text read from the file is cut with the marker (section 8.2): labels at 120 characters, in
 *   edge cells too, other text at 400, in values, inside arrays and objects, and in column
 *   names; ids are whole. A node whose id is longer than an answer's id can be (512 characters)
 *   is left out of the rows and still counted in `total`, as in `neighbors`.
 */
import type { Database } from "@sqlite.org/sqlite-wasm";
import { type TableAnswer, ToolError, shownArgument } from "./answers.js";
import { QUERY_LIMIT, RESULT_LIMIT } from "./bounds.js";
import { TEXT_LIMITS, cut } from "./constants.js";
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
    throw new ToolError("bad_argument", `table's columns must be a list of 1 to ${RESULT_LIMIT} column names`);
  }
  const columns = value.map((c) => columnName("columns", c));
  if (new Set(columns).size !== columns.length) {
    throw new ToolError("bad_argument", "table's columns must name each column once");
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


/** The `unknown_column` error for `column` of `type`; it names no name read from the file. */
function unknownColumn(type: string, column: string): ToolError {
  return new ToolError(
    "unknown_column",
    `table: ${shownArgument(column)} is not a column of ${type}: a column is a declared property, key, label, summary or an edge type leaving ${type}; table on ${type} without columns lists the label and declared properties`,
  );
}

/** The node fields a column may name, with the length their text is cut to (section 8.2). */
const FIELDS = { key: OTHER_TEXT_LIMIT, label: TEXT_LIMITS.label, summary: OTHER_TEXT_LIMIT } as const;

type Field = keyof typeof FIELDS;

/** What a column name means for one type (section 8.6): a property, a node field or an edge. */
type Column =
  | { readonly name: string; readonly kind: "property" }
  | { readonly name: string; readonly kind: "field"; readonly field: Field }
  | { readonly name: string; readonly kind: "edge" };

function isField(name: string): name is Field {
  return Object.hasOwn(FIELDS, name);
}

/** Lowercase by the Unicode default mapping, as `contains` compares (section 8.6). */
const FOLD = "mosaic_fold";

const folding = new WeakSet<Database>();

/** Give `db` the {@link FOLD} function, once. */
function withFold(db: Database): void {
  if (folding.has(db)) return;
  db.createFunction(FOLD, {
    arity: 1,
    deterministic: true,
    xFunc: (_ctx, value) => (typeof value === "string" ? value.toLowerCase() : value),
  });
  folding.add(db);
}

/**
 * The JSON kind of column `c` on node `n` (`text`, `integer`, `real`, `true`, `false`, `array`,
 * `object`), or NULL when the node has no value; `name` is the bound parameter holding its name.
 */
function kindOf(c: Column, name: string): string {
  switch (c.kind) {
    case "property":
      return `(SELECT NULLIF(p.type, 'null') FROM json_each(n.props) AS p WHERE p.key = ${name} LIMIT 1)`;
    case "field":
      return `(CASE WHEN n.${c.field} IS NULL THEN NULL ELSE 'text' END)`;
    case "edge":
      return "'array'";
  }
}

/** The labels of the nodes the edges `$<name>` lead to from `n`, by their ids, as JSON text. */
const edgeLabels = (name: string) =>
  `(SELECT json_group_array(d.label ORDER BY d.id COLLATE BINARY) FROM node AS d` +
  ` WHERE d.nid IN (SELECT e.dst FROM edge AS e WHERE e.src = n.nid AND e.type = ${name}))`;

/**
 * The comparable value of column `c` on node `n`: text as text, numbers as numbers, booleans as
 * 0 and 1, lists and objects as their JSON text, NULL when the node has no value.
 */
function valueOf(c: Column, name: string): string {
  switch (c.kind) {
    case "property":
      return `(SELECT CASE p.type WHEN 'null' THEN NULL ELSE p.value END FROM json_each(n.props) AS p WHERE p.key = ${name} LIMIT 1)`;
    case "field":
      return `n.${c.field}`;
    case "edge":
      return edgeLabels(name);
  }
}

/** Column `c` of node `n` as JSON text to show (JSON `null` or SQL NULL when it has no value). */
function shownOf(c: Column, name: string): string {
  switch (c.kind) {
    case "property":
      return `(SELECT n.props -> p.fullkey FROM json_each(n.props) AS p WHERE p.key = ${name} LIMIT 1)`;
    case "field":
      return `json_quote(n.${c.field})`;
    case "edge":
      return edgeLabels(name);
  }
}

/** The JSON kinds a `where` value of each argument kind compares with. */
const SAME_KIND = { string: "'text'", number: "'integer', 'real'", boolean: "'true', 'false'" } as const;

/**
 * Whether text `x` holds the bound, already folded text `val`, ignoring case. On ASCII text the
 * Unicode default lowercase mapping is SQLite's `lower`, so {@link FOLD}, a call into the page,
 * runs only on text holding other characters (UTF-8 bytes outnumber characters).
 */
const contains = (x: string, val: string) =>
  `(instr(lower(${x}), ${val}) > 0 OR (length(CAST(${x} AS BLOB)) <> length(${x}) AND instr(${FOLD}(${x}), ${val}) > 0))`;

/**
 * An SQL condition on the kind `t` and value `v` of column `column` (its name bound as `name`),
 * against the bound value `val`. An edge's cell is a list, so only `contains` and `!=` can hold
 * on it; `contains` reads the labels directly rather than building the list for every node.
 */
function condition(c: Condition, column: Column, name: string, t: string, v: string, val: string): string {
  if (column.kind === "edge") {
    if (c.op === "!=") return "1";
    if (c.op !== "contains") return "0";
    return (
      `EXISTS (SELECT 1 FROM edge AS e JOIN node AS d ON d.nid = e.dst` +
      ` WHERE e.src = r.nid AND e.type = ${name} AND ${contains("d.label", val)})`
    );
  }
  if (c.op === "contains") {
    const has = (x: string) => contains(x, val);
    return (
      `((${t} = 'text' AND ${has(v)}) OR (${t} = 'array' AND EXISTS ` +
      `(SELECT 1 FROM json_each(${v}) AS j WHERE j.type = 'text' AND ${has("j.value")})))`
    );
  }
  const same = `${t} IN (${SAME_KIND[typeof c.value as keyof typeof SAME_KIND]})`;
  if (c.op === "!=") return `NOT coalesce(${same} AND ${v} = ${val}, 0)`;
  return `coalesce(${same} AND ${v} ${c.op} ${val}, 0)`;
}

/** The group a value's kind sorts in: booleans, numbers, text, lists, objects, then no value. */
const group = (t: string) =>
  `CASE ${t} WHEN 'true' THEN 1 WHEN 'false' THEN 1 WHEN 'integer' THEN 2 WHEN 'real' THEN 2` +
  ` WHEN 'text' THEN 3 WHEN 'array' THEN 4 WHEN 'object' THEN 5 ELSE 6 END`;

/** A cell to show: `json` read from the file as JSON text, cut as section 8.2 says. */
function cell(c: Column, json: unknown): unknown {
  if (typeof json !== "string") return null;
  const value = JSON.parse(json) as unknown;
  switch (c.kind) {
    case "property":
      return cutJson(value, OTHER_TEXT_LIMIT);
    case "field":
      return typeof value === "string" ? cut(value, FIELDS[c.field]) : null;
    case "edge":
      return Array.isArray(value) ? value.map((l) => (typeof l === "string" ? cut(l, TEXT_LIMITS.label) : null)) : [];
  }
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
  const edges = new Set(
    db
      .selectValues("SELECT name FROM type WHERE kind = 'edge' AND from_type = ?", [type])
      .filter((n): n is string => typeof n === "string"),
  );
  // A declared property first, then a node field, then an edge leaving the type (section 8.6).
  const resolve = (name: string): Column => {
    if (declared.includes(name)) return { name, kind: "property" };
    if (isField(name)) return { name, kind: "field", field: name };
    if (edges.has(name)) return { name, kind: "edge" };
    throw unknownColumn(type, name);
  };
  const names = asked ?? [...new Set(["label", ...declared])].slice(0, RESULT_LIMIT);
  const columns = names.map(resolve);
  const filters = where.map((c) => ({ c, column: resolve(c.column) }));
  const keys = order.map((o) => ({ o, column: resolve(o.column) }));
  withFold(db);

  // Each column `where` or `order` reads is computed once per node, as kind t<i> and value v<i>.
  const bind: Record<string, string | number> = { $type: type };
  const used: string[] = [];
  const index = (column: Column): number => {
    let i = used.indexOf(column.name);
    if (i < 0) {
      i = used.push(column.name) - 1;
      if (column.kind !== "field") bind[`$u${i}`] = column.name;
    }
    return i;
  };
  const parts: string[] = [];
  const conds = filters.map(({ c, column }, k) => {
    const i = index(column);
    // An edge's list is never equal to, nor before or after, a single value: no value to bind.
    if (column.kind !== "edge" || c.op === "contains") {
      bind[`$w${k}`] = typeof c.value === "boolean" ? (c.value ? 1 : 0) : c.op === "contains" ? (c.value as string).toLowerCase() : c.value;
    }
    return condition(c, column, `$u${i}`, `t${i}`, `v${i}`, `$w${k}`);
  });
  const sort = keys.flatMap(({ o, column }) => {
    const i = index(column);
    return [`${group(`t${i}`)}`, `v${i} COLLATE BINARY ${o.desc ? "DESC" : "ASC"}`];
  });
  for (const [i, name] of used.entries()) {
    const column = resolve(name);
    parts.push(`${kindOf(column, `$u${i}`)} AS t${i}`, `${valueOf(column, `$u${i}`)} AS v${i}`);
  }
  const rowsOf =
    `WITH r AS (SELECT ${["n.id AS id", "n.nid AS nid", ...parts].join(", ")} FROM node AS n WHERE n.type = $type)` +
    ` SELECT %s FROM r${conds.length > 0 ? ` WHERE ${conds.join(" AND ")}` : ""}`;
  const total = Number(db.selectValue(rowsOf.replace("%s", "count(*)"), bind));

  const offset = (page - 1) * RESULT_LIMIT;
  let rows: unknown[][] = [];
  if (offset < total) {
    const shownIds = db
      .selectValues(
        `${rowsOf.replace("%s", "id")}${conds.length > 0 ? " AND" : " WHERE"} length(id) <= ${ID_LIMIT}` +
          ` ORDER BY ${[...sort, "id COLLATE BINARY"].join(", ")} LIMIT ${RESULT_LIMIT} OFFSET $offset`,
        { ...bind, $offset: offset },
      )
      .map(String);
    checkpoint();
    const show: Record<string, string> = { $ids: JSON.stringify(shownIds) };
    const cells = columns.map((c, i) => {
      if (c.kind !== "field") show[`$c${i}`] = c.name;
      return shownOf(c, `$c${i}`);
    });
    rows = db
      .selectArrays(
        `SELECT ${["n.id", ...cells].join(", ")} FROM json_each($ids) AS k JOIN node AS n ON n.id = k.value ORDER BY k.key`,
        show,
      )
      .map(([id, ...values]) => [String(id), ...values.map((v, i) => cell(columns[i]!, v))]);
  }
  return {
    tool: "table",
    mosaic,
    data: { type, columns: ["id", ...names.map((c) => cutJson(c, OTHER_TEXT_LIMIT) as string)], rows, page, total },
  };
}
