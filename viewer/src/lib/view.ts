/**
 * The view file, as the page applies it (docs/design.md, Implementation plan, "View file"; plan
 * M3.5 and M3.6). `mosaic view` and `mosaic export` read the YAML file and hand the page its
 * settings as JSON (`mosaic_build.view_file`, `ViewSettings.as_json`); `null` there is a
 * default the page applies. Every setting has a default, so no view file is M2's viewer.
 *
 * {@link Shape} applies the settings to one open mosaic: which node types the page lists, in the
 * order the file writes them; each type's label; its table's columns; what its node page shows,
 * in order; and the labels of its property and edge names. A type the file leaves out is absent
 * from the type list and tables only: search and links still reach its nodes, and the kit is
 * never shaped by the view file (answer on #120, Reading A). A type, property or edge type the
 * mosaic does not have is dropped with a notice, and the page still opens.
 */
import type { EdgeType, NodeType, SealedFile } from "@mosaic/kit";

export type SearchMode = "semantic" | "text";
export type Theme = "auto" | "light" | "dark";

export const SEARCH_MODES: readonly SearchMode[] = ["semantic", "text"];
export const THEMES: readonly Theme[] = ["auto", "light", "dark"];

/** How each search mode is named on the search field's switch (brand book, section 6). */
export const MODE_NAMES: Readonly<Record<SearchMode, string>> = { semantic: "Semantic", text: "Text" };

/** One node type's settings; `null` is the default. */
export interface TypeSettings {
  readonly name: string;
  readonly label: string | null;
  readonly columns: readonly string[] | null;
  readonly page: readonly string[] | null;
  readonly names: ReadonlyMap<string, string>;
}

export interface ViewSettings {
  readonly search: SearchMode;
  readonly theme: Theme;
  /** The node types listed, in order; null lists every node type, by name. */
  readonly types: readonly TypeSettings[] | null;
  /** Which types an export carries (M3.10); null is its default. */
  readonly exportTypes: readonly string[] | null;
}

/** M2's viewer. */
export const DEFAULT_VIEW: ViewSettings = { search: "semantic", theme: "auto", types: null, exportTypes: null };

/** The query parameter that names the view file's settings, as JSON, for the page to fetch. */
export const VIEW_PARAM = "view";

function fail(where: string, what: string): never {
  throw new Error(`view file: ${where} must be ${what}`);
}

function record(value: unknown, where: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(where, "an object");
  return value as Record<string, unknown>;
}

function text(value: unknown, where: string): string {
  if (typeof value !== "string" || value === "") fail(where, "non-empty text");
  return value;
}

function texts(value: unknown, where: string): readonly string[] | null {
  if (value === null) return null;
  if (!Array.isArray(value)) fail(where, "a list of names or null");
  return value.map((v, i) => text(v, `${where}[${i}]`));
}

function oneOf<T extends string>(value: unknown, where: string, values: readonly T[]): T {
  if (!values.includes(value as T)) fail(where, `one of ${values.join(", ")}`);
  return value as T;
}

/** The view file's settings from their JSON form (`ViewSettings.as_json`); throws when malformed. */
export function parseView(data: unknown): ViewSettings {
  const given = record(data, "the settings");
  const types =
    given.types === null || given.types === undefined
      ? null
      : (Array.isArray(given.types) ? given.types : fail("types", "a list or null")).map((t, i): TypeSettings => {
          const where = `types[${i}]`;
          const entry = record(t, where);
          const names = record(entry.names ?? {}, `${where}.names`);
          return {
            name: text(entry.name, `${where}.name`),
            label: entry.label === null || entry.label === undefined ? null : text(entry.label, `${where}.label`),
            columns: texts(entry.columns ?? null, `${where}.columns`),
            page: texts(entry.page ?? null, `${where}.page`),
            names: new Map(Object.keys(names).map((k) => [k, text(names[k], `${where}.names.${k}`)])),
          };
        });
  const exported = record(given.export ?? {}, "export");
  return {
    search: oneOf(given.search ?? "semantic", "search", SEARCH_MODES),
    theme: oneOf(given.theme ?? "auto", "theme", THEMES),
    types,
    exportTypes: texts(exported.types ?? null, "export.types"),
  };
}

/** The view file's settings the address's `?view=<url>` names, fetched as JSON, or null. */
export async function fetchNamedView(search: string, base: string, fetcher: typeof fetch = fetch): Promise<ViewSettings | null> {
  const named = new URLSearchParams(search).get(VIEW_PARAM);
  if (named === null || named === "") return null;
  let response: Response;
  try {
    response = await fetcher(new URL(named, base));
  } catch (e) {
    throw new Error(`could not fetch the view file's settings: ${e instanceof Error ? e.message : String(e)}`);
  }
  if (!response.ok) throw new Error(`could not fetch the view file's settings: ${response.status} ${response.statusText}`.trim());
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error("view file: the settings are not JSON");
  }
  return parseView(data);
}

/** What {@link Shape} needs of an open mosaic. */
export type Schema = Pick<SealedFile, "nodeTypes" | "edgeTypes" | "propsOf">;

/** The most columns a table shows after the node's name (section 8.6: 20 columns in all). */
const MORE_COLUMNS = 19;

/** The view file's settings applied to one open mosaic. */
export class Shape {
  /** The node types the page lists, in the view file's order. */
  readonly types: readonly NodeType[];
  /** What the view file names that the mosaic does not have; each was left out. */
  readonly notices: readonly string[];
  readonly #settings = new Map<string, TypeSettings>();
  readonly #columns = new Map<string, readonly string[]>();
  readonly #page = new Map<string, readonly string[]>();

  constructor(view: ViewSettings, schema: Schema) {
    const notices: string[] = [];
    const known = new Map(schema.nodeTypes.map((t) => [t.name, t]));
    const listed: NodeType[] = [];
    for (const settings of view.types ?? schema.nodeTypes.map((t) => typeSettings(t.name))) {
      const type = known.get(settings.name);
      if (type === undefined) {
        notices.push(`view file: types.${settings.name}: the mosaic has no node type ${settings.name}`);
        continue;
      }
      listed.push(type);
      this.#settings.set(type.name, settings);
      const props = schema.propsOf(type.name);
      const leaving = edgesOf(schema.edgeTypes, type.name, "out");
      const touching = edgesOf(schema.edgeTypes, type.name, "both");
      const keep = (names: readonly string[], allowed: (n: string) => boolean, where: string, what: string) =>
        names.filter((n) => {
          if (allowed(n)) return true;
          notices.push(`view file: types.${type.name}.${where}: ${type.name} has no ${what} ${n}`);
          return false;
        });
      if (settings.columns !== null) {
        const columns = keep(settings.columns, (n) => props.includes(n) || leaving.has(n), "columns", "property");
        this.#columns.set(type.name, columns.slice(0, MORE_COLUMNS));
      }
      if (settings.page !== null) {
        this.#page.set(type.name, keep(settings.page, (n) => props.includes(n) || touching.has(n), "page", "property or edge type"));
      }
      keep([...settings.names.keys()], (n) => props.includes(n) || touching.has(n), "names", "property or edge type");
    }
    for (const name of view.exportTypes ?? []) {
      if (!known.has(name)) notices.push(`view file: export.types: the mosaic has no node type ${name}`);
    }
    this.types = listed;
    this.notices = notices;
  }

  /** True when the page lists `type` and shows its table. */
  lists(type: string): boolean {
    return this.#settings.has(type);
  }

  /** What the page calls node type `type`. */
  typeLabel(type: string): string {
    return this.#settings.get(type)?.label ?? type;
  }

  /** The label the view file gives `name`, a property or edge type, on `type`'s pages, or null. */
  label(type: string, name: string): string | null {
    return this.#settings.get(type)?.names.get(name) ?? null;
  }

  /** The columns `type`'s table shows after the node's name, or null for `table`'s default. */
  columns(type: string): readonly string[] | null {
    return this.#columns.get(type) ?? null;
  }

  /** The properties and edge types `type`'s node page shows, in order, or null for all of them. */
  page(type: string): readonly string[] | null {
    return this.#page.get(type) ?? null;
  }
}

function typeSettings(name: string): TypeSettings {
  return { name, label: null, columns: null, page: null, names: new Map() };
}

/** The edge types that leave `type` (`out`), or that leave or enter it (`both`). */
function edgesOf(edges: readonly EdgeType[], type: string, direction: "out" | "both"): Set<string> {
  return new Set(
    edges
      .filter((e) => e.from === null || e.from === type || (direction === "both" && (e.to === null || e.to === type)))
      .map((e) => e.name),
  );
}

/** Set the page's theme: `auto` follows the system, `light` and `dark` fix it (tokens.css). */
export function applyTheme(root: { dataset: Record<string, string | undefined> }, theme: Theme): void {
  if (theme === "auto") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

/** Items of `items` that `page` names, by `nameOf`, in `page`'s order; all of them when `page` is null. */
export function inPageOrder<T>(items: readonly T[], page: readonly string[] | null, nameOf: (item: T) => string): T[] {
  if (page === null) return [...items];
  const rank = new Map(page.map((n, i) => [n, i]));
  return items
    .map((item, i) => ({ item, i, r: rank.get(nameOf(item)) }))
    .filter((x): x is { item: T; i: number; r: number } => x.r !== undefined)
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((x) => x.item);
}
