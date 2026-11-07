/**
 * The viewer's state: the open mosaic, the search and the node page. Each change asks the kit,
 * in the page, and keeps only the latest answer, so a slow answer never replaces a newer one.
 */
import type { SealedFile } from "@mosaic/kit";
import { nodePage, openMosaic, search, type NodeView, type SearchView, type ToolFailure } from "./mosaic.js";

export type Status = "empty" | "loading" | "ready" | "error";

export class Viewer {
  /** The open mosaic, or null before one is opened. */
  file = $state.raw<SealedFile | null>(null);
  status = $state<Status>("empty");
  /** Why the last file could not be opened. */
  error = $state<string | null>(null);
  query = $state("");
  results = $state.raw<SearchView | ToolFailure | null>(null);
  nodeId = $state<string | null>(null);
  page = $state.raw<NodeView | ToolFailure | null>(null);

  #searches = 0;
  #pages = 0;

  /** Open `bytes` as the mosaic `name`, closing the one before; a refused file is an error. */
  async open(bytes: Uint8Array, name: string): Promise<void> {
    this.status = "loading";
    this.error = null;
    try {
      const file = await openMosaic(bytes, name);
      this.file?.close();
      this.file = file;
      this.status = "ready";
      this.results = null;
      this.page = null;
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
}
