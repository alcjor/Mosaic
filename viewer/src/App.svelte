<script lang="ts">
  /**
   * The viewer's shell (brand book, section 6): a header band with the mosaic's name, its short
   * knowledge hash and the search field; then the results, the node's card, and its links and
   * sources; or the tables rebuilt from the mosaic's node types, each page one `table` call. The
   * kit runs in this page: a mosaic is opened from a file the reader picks, or from
   * the address's `?mosaic=<url>`, and nothing is asked of a server but the file itself. When the
   * address also names the model (`?model=<url>`, from `mosaic view --model`), it is loaded in
   * the page first, so `find` searches by vectors too; a model that fails to load is shown as an
   * error and the page searches by names and full text only (section 3.8). The view file's
   * settings, from the address's `?view=<url>` (lib/view.ts), shape the page: the types listed,
   * their labels, columns and node pages, the theme and the search mode; what they name that the
   * mosaic does not have is shown as a notice, and the page still opens. The page asks for them
   * again every second, so a view file saved under `mosaic view` reshapes it; settings that
   * cannot be read (a file saved with an error) are shown as an error and the page stays as it was.
   * A single-file export (lib/exported.ts) holds its mosaic, its view file's settings and SQLite's
   * WebAssembly in the document: the page opens them, fetches nothing, watches nothing, and says
   * it is a read-only export (brand book, section 6, Shell).
   */
  import { onMount } from "svelte";
  import EntityCard from "./components/EntityCard.svelte";
  import NodeContext from "./components/NodeContext.svelte";
  import ResultList from "./components/ResultList.svelte";
  import SearchField from "./components/SearchField.svelte";
  import TableView from "./components/TableView.svelte";
  import TypeList from "./components/TypeList.svelte";
  import { fetchNamedModel, fetchNamedMosaic, loadModel, shortHash } from "./lib/mosaic.js";
  import { parseRoute, routeHash, type Condition, type TableRoute } from "./lib/route.js";
  import { useSqliteWasm } from "@mosaic/kit";
  import { cutFrom, readExport, runtimeOf } from "./lib/exported.js";
  import { applyTheme, watchView } from "./lib/view.js";
  import { Viewer } from "./lib/viewer.svelte.js";

  let { viewer = new Viewer(), exported = false }: { viewer?: Viewer; exported?: boolean } = $props();

  /** Why the view file's settings could not be read; the page then uses the defaults. */
  let viewError = $state<string | null>(null);
  let stopWatching: () => void = () => {};

  $effect(() => applyTheme(document.documentElement, viewer.view.theme));

  const hrefFor = (id: string): string => routeHash({ query: viewer.query, node: id });
  const tableHref = (table: TableRoute): string => routeHash({ query: viewer.query, node: null, table });
  const typeHref = (type: string): string => tableHref({ type, page: 1, order: null, where: [] });

  function filtered(condition: Condition): void {
    const table = viewer.tableRoute;
    if (table) location.hash = tableHref({ ...table, page: 1, where: [...table.where, condition] });
  }

  /** Follow the address after `#`: the query, and the node or the table view it names. */
  function follow(): void {
    const route = parseRoute(location.hash);
    if (route.query !== viewer.query || viewer.results === null) void viewer.search(route.query);
    if (route.node !== viewer.nodeId || viewer.page === null) void viewer.show(route.node);
    const table = route.table ?? null;
    if (routeHash({ query: "", node: null, table }) !== routeHash({ query: "", node: null, table: viewer.tableRoute }) || viewer.table === null) {
      void viewer.showTable(table);
    }
  }

  async function opened(bytes: Uint8Array, name: string): Promise<void> {
    await viewer.open(bytes, name);
    if (viewer.status === "ready") {
      viewer.results = null;
      viewer.page = null;
      follow();
    }
  }

  async function picked(event: Event): Promise<void> {
    const input = event.currentTarget as HTMLInputElement;
    const chosen = input.files?.[0];
    if (chosen) await opened(new Uint8Array(await chosen.arrayBuffer()), chosen.name);
  }

  /** Open the export the document holds; true when it holds one. */
  async function openExport(): Promise<boolean> {
    let found;
    try {
      found = await readExport(document);
    } catch (e) {
      viewer.status = "error";
      viewer.error = e instanceof Error ? e.message : String(e);
      exported = true;
      return true;
    }
    if (found === null) return false;
    exported = true;
    useSqliteWasm(found.sqlite);
    if (found.model !== null) {
      try {
        viewer.embedder = await loadModel(found.model.files, await runtimeOf(found.model));
      } catch (e) {
        viewer.modelError = `search by names and full text only: ${e instanceof Error ? e.message : String(e)}`;
      }
    }
    await viewer.setView(found.view);
    await opened(found.mosaic, found.name);
    return true;
  }

  onMount(() => {
    window.addEventListener("hashchange", follow);
    void (async () => {
      if (await openExport()) return;
      const model = (async () => {
        try {
          const files = await fetchNamedModel(location.search, location.href);
          if (files) viewer.embedder = await loadModel(files);
        } catch (e) {
          viewer.modelError = `search by names and full text only: ${e instanceof Error ? e.message : String(e)}`;
        }
      })();
      let first: () => void = () => {};
      const view = new Promise<void>((resolve) => (first = resolve));
      stopWatching = watchView(
        location.search,
        location.href,
        (settings) => void viewer.setView(settings).then(first),
        (error) => {
          viewError = error;
          first();
        },
      );
      if (!new URLSearchParams(location.search).get("view")) first();
      try {
        const named = await fetchNamedMosaic(location.search, location.href);
        await Promise.all([model, view]);
        if (named) await opened(named.bytes, named.name);
      } catch (e) {
        viewer.status = "error";
        viewer.error = e instanceof Error ? e.message : String(e);
      }
    })();
    return () => {
      window.removeEventListener("hashchange", follow);
      stopWatching();
    };
  });
</script>

<header class="band">
  {#if viewer.file}
    <span class="name code">{viewer.file.name}</span>
    <span class="hash code" title={viewer.file.header.knowledge_hash}>{shortHash(viewer.file.header.knowledge_hash)}</span>
  {:else}
    <span class="name code">Mosaic viewer</span>
  {/if}
  <SearchField
    value={viewer.query}
    disabled={viewer.file === null}
    mode={viewer.mode}
    onsearch={(query) => (location.hash = routeHash({ query, node: viewer.nodeId }))}
    onmode={(mode) => void viewer.setMode(mode)}
  />
  {#if exported}
    <span class="export caption">Read-only export</span>
    {@const from = viewer.file ? cutFrom(viewer.file.pieces) : null}
    {#if from}
      <span class="export caption" title={from.hash}>from {from.id} {shortHash(from.hash)}</span>
    {/if}
  {/if}
  <label class="open caption">
    Open a mosaic
    <input class="file" type="file" accept=".mosaic" onchange={picked} />
  </label>
</header>
{#if viewer.status === "loading"}
  <div class="loading" role="progressbar" aria-label="Opening the mosaic"></div>
{/if}
{#if viewer.error}
  <p class="banner body-screen" role="alert">{viewer.error}</p>
{/if}
{#if viewer.modelError}
  <p class="banner body-screen" role="alert">{viewer.modelError}</p>
{/if}
{#if viewError}
  <p class="banner body-screen" role="alert">{viewError}</p>
{/if}
{#if viewer.shape && viewer.shape.notices.length > 0}
  <ul class="notices body-screen" role="status" aria-label="View file notices">
    {#each viewer.shape.notices as notice, i (i)}
      <li>{notice}</li>
    {/each}
  </ul>
{/if}

{#if viewer.file === null}
  <main class="start">
    <p class="empty body-screen">Open a mosaic to search it. It is read in this page; nothing is sent anywhere.</p>
  </main>
{:else}
  <main class="columns">
    <nav class="results" aria-label="Results">
      {#if viewer.results}
        <ResultList view={viewer.results} selected={viewer.nodeId} {hrefFor} typeLabel={(type) => viewer.shape?.typeLabel(type) ?? type} />
      {:else}
        <p class="empty body-screen">Search for a name, an alias or words in the text.</p>
      {/if}
      <TypeList
        types={viewer.shape?.types ?? viewer.file.nodeTypes}
        selected={viewer.tableRoute?.type ?? null}
        hrefFor={typeHref}
        labelFor={(type) => viewer.shape?.typeLabel(type) ?? type}
      />
    </nav>
    {#if viewer.tableRoute}
      <div class="wide">
        {#key viewer.tableRoute.type}
          <TableView
            view={viewer.table}
            route={viewer.tableRoute}
            hrefFor={tableHref}
            nodeHref={hrefFor}
            onfilter={filtered}
            shape={viewer.shape}
          />
        {/key}
      </div>
    {:else if viewer.page && "message" in viewer.page}
      <section class="entity">
        <p class="banner body-screen" role="alert">{viewer.page.message}</p>
        {#if viewer.page.suggestions.length > 0}
          <p class="caption">Closest:</p>
          <ul class="suggestions code">
            {#each viewer.page.suggestions as id (id)}
              <li><a href={hrefFor(id)}>{id}</a></li>
            {/each}
          </ul>
        {/if}
      </section>
      <aside class="context"></aside>
    {:else if viewer.page}
      <section class="entity"><EntityCard node={viewer.page.node} shape={viewer.shape} /></section>
      <aside class="context" aria-label="Links and sources"><NodeContext view={viewer.page} {hrefFor} shape={viewer.shape} /></aside>
    {:else}
      <section class="entity"><p class="empty body-screen">Pick a result to see its page.</p></section>
      <aside class="context"></aside>
    {/if}
  </main>
{/if}

<style>
  :global(body) {
    margin: 0;
    background: var(--surface);
    color: var(--ink);
    font-family: var(--font-sans);
  }

  .band {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    block-size: var(--app-header);
    padding-inline: var(--space-4);
    background: var(--slab);
  }

  .name {
    color: var(--shard-4);
  }

  .hash {
    color: var(--shard-4);
    opacity: 0.8;
  }

  .export {
    color: var(--shard-4);
  }

  .open {
    color: var(--shard-4);
    cursor: pointer;
  }

  .file {
    inline-size: 1px;
    block-size: 1px;
    opacity: 0;
  }

  .open:focus-within {
    outline: 2px solid var(--focus-ring);
    outline-offset: 2px;
  }

  .loading {
    block-size: 2px;
    background: var(--accent);
  }

  .banner {
    margin: var(--space-3) var(--space-4);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--majolica-tint);
    color: var(--majolica-text);
  }

  .notices {
    margin: var(--space-3) var(--space-4);
    padding: var(--space-2) var(--space-3) var(--space-2) var(--space-5);
    border-inline-start: 3px solid var(--status-warning);
    border-radius: var(--radius-md);
    background: var(--surface-tint);
    color: var(--ink);
  }

  .start {
    max-inline-size: 40rem;
    margin-inline: auto;
    padding: var(--space-5) var(--space-4);
  }

  .empty {
    margin: var(--space-3);
    color: var(--ink-muted);
  }

  .columns {
    display: grid;
    grid-template-columns: 1fr;
  }

  .results,
  .context {
    border-block-end: 1px solid var(--border);
  }

  .wide {
    min-inline-size: 0;
  }

  .suggestions {
    margin: 0;
    padding-inline-start: var(--space-4);
  }

  @media (width >= 960px) {
    .columns {
      grid-template-columns: 320px 1fr 320px;
      min-block-size: calc(100vh - var(--app-header));
    }

    .results,
    .context {
      border-block-end: none;
    }

    .results {
      border-inline-end: 1px solid var(--border);
    }

    .context {
      border-inline-start: 1px solid var(--border);
    }

    .wide {
      grid-column: 2 / span 2;
    }
  }
</style>
