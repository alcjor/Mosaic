/**
 * The viewer's state: the open mosaic, the search and the node page. Each change asks the kit,
 * in the page, and keeps only the latest answer, so a slow answer never replaces a newer one.
 *
 * The view file's settings (lib/view.ts) shape what the page shows; the search mode starts as
 * the file's `search`. In *Text* mode the mosaic is opened without the query embedder, so `find`
 * searches names and full text only; in *Semantic* mode it is opened with the embedder, when
 * the page has one (section 3.8). Switching the mode opens the same bytes again.
 */
import type { QueryEmbedder, SealedFile } from "@mosaic/kit";
import { nodePage, openMosaic, search, type NodeView, type SearchView, type ToolFailure } from "./mosaic.js";
import type { TableRoute } from "./route.js";
import { tableView, type TableView } from "./tables.js";
import { DEFAULT_VIEW, Shape, type SearchMode, type ViewSettings } from "./view.js";

export type Status = "empty" | "loading" | "ready" | "error";

export class Viewer {
  /** The open mosaic, or null before one is opened. */
  file = $state.raw<SealedFile | null>(null);
  status = $state<Status>("empty");
  /** Why the last file could not be opened. */
  error = $state<string | null>(null);
  /** What embeds queries for `find`'s vector tier, when the page was given the model. */
  embedder = $state.raw<QueryEmbedder | null>(null);
  /** Why the model could not be loaded; the page then searches by names and full text only. */
  modelError = $state<string | null>(null);
  query = $state("");
  results = $state.raw<SearchView | ToolFailure | null>(null);
  nodeId = $state<string | null>(null);
  page = $state.raw<NodeView | ToolFailure | null>(null);
  /** The table view asked for, and its page from `table`. */
  tableRoute = $state.raw<TableRoute | null>(null);
  table = $state.raw<TableView | ToolFailure | null>(null);
  /** The view file's settings; the defaults are M2's viewer. */
  view = $state.raw<ViewSettings>(DEFAULT_VIEW);
  /** The view file applied to the open mosaic, or null before one is opened. */
  shape = $state.raw<Shape | null>(null);
  /** How `find` searches: with the embedder (*Semantic*) or by names and full text (*Text*). */
  mode = $state<SearchMode>(DEFAULT_VIEW.search);

  #searches = 0;
  #pages = 0;
  #tables = 0;
  #opened: { bytes: Uint8Array; name: string } | null = null;

  /** The embedder `find` uses in the current mode, if any. */
  get searchEmbedder(): QueryEmbedder | null {
    return this.mode === "semantic" ? this.embedder : null;
  }

  /** Shape the page by the view file's settings; the search mode becomes the file's `search`. */
  async setView(view: ViewSettings): Promise<void> {
    this.view = view;
    if (this.file !== null) this.shape = new Shape(view, this.file);
    await this.setMode(view.search);
    if (this.tableRoute !== null) await this.showTable(this.tableRoute);
  }

  /** Search in `mode`; an open mosaic is opened again, and its search and pages asked again. */
  async setMode(mode: SearchMode): Promise<void> {
    if (mode === this.mode) return;
    this.mode = mode;
    const opened = this.#opened;
    if (opened === null) return;
    const { query, nodeId, tableRoute } = this;
    await this.open(opened.bytes, opened.name);
    await Promise.all([this.search(query), this.show(nodeId), this.showTable(tableRoute)]);
  }

  /** Open `bytes` as the mosaic `name`, closing the one before; a refused file is an error. */
  async open(bytes: Uint8Array, name: string): Promise<void> {
    this.status = "loading";
    this.error = null;
    try {
      const file = await openMosaic(bytes, name, this.searchEmbedder);
      this.file?.close();
      this.file = file;
      this.#opened = { bytes, name };
      this.shape = new Shape(this.view, file);
      this.status = "ready";
      this.results = null;
      this.page = null;
      this.table = null;
    } catch (e) {
      this.status = this.file === null ? "error" : "ready";
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  /** Search the open mosaic with `find`; an empty query clears the results. */
  async search(query: string): Promise<void> {
    this.query = query;
    const n = ++this.#searches;
    if (this.file === null || query.trim() === "") {
      this.results = null;
      return;
    }
    const view = await search(this.file, query);
    if (n === this.#searches) this.results = view;
  }

  /** Show the page of the node `id` (null closes it). */
  async show(id: string | null): Promise<void> {
    this.nodeId = id;
    const n = ++this.#pages;
    if (this.file === null || id === null) {
      this.page = null;
      return;
    }
    const view = await nodePage(this.file, id);
    if (n === this.#pages) this.page = view;
  }

  /** Show a page of a table view with `table` (null closes it). */
  async showTable(route: TableRoute | null): Promise<void> {
    this.tableRoute = route;
    const n = ++this.#tables;
    if (this.file === null || route === null) {
      this.table = null;
      return;
    }
    const shape = this.shape;
    const view =
      shape !== null && !shape.lists(route.type)
        ? { message: `The view file does not list ${route.type}, so its table is not shown.`, suggestions: [] }
        : await tableView(this.file, route, shape?.columns(route.type) ?? null);
    if (n === this.#tables) this.table = view;
  }
}
