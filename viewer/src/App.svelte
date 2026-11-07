<script lang="ts">
  /**
   * The viewer's shell (brand book, section 6): a header band with the mosaic's name, its short
   * knowledge hash and the search field; then the results, the node's card, and its links and
   * sources; or the tables rebuilt from the mosaic's node types, each page one `table` call. The
   * kit runs in this page: a mosaic is opened from a file the reader picks, or from
   * the address's `?mosaic=<url>`, and nothing is asked of a server but the file itself.
   */
  import { onMount } from "svelte";
  import EntityCard from "./components/EntityCard.svelte";
  import NodeContext from "./components/NodeContext.svelte";
  import ResultList from "./components/ResultList.svelte";
  import SearchField from "./components/SearchField.svelte";
  import TableView from "./components/TableView.svelte";
  import TypeList from "./components/TypeList.svelte";
  import { fetchNamedMosaic, shortHash } from "./lib/mosaic.js";
  import { parseRoute, routeHash, type Condition, type TableRoute } from "./lib/route.js";
  import { Viewer } from "./lib/viewer.svelte.js";

  let { viewer = new Viewer() }: { viewer?: Viewer } = $props();

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

  onMount(() => {
    window.addEventListener("hashchange", follow);
    void (async () => {
      try {
        const named = await fetchNamedMosaic(location.search, location.href);
        if (named) await opened(named.bytes, named.name);
      } catch (e) {
        viewer.status = "error";
        viewer.error = e instanceof Error ? e.message : String(e);
      }
    })();
    return () => window.removeEventListener("hashchange", follow);
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
    onsearch={(query) => (location.hash = routeHash({ query, node: viewer.nodeId }))}
  />
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

{#if viewer.file === null}
  <main class="start">
    <p class="empty body-screen">Open a mosaic to search it. It is read in this page; nothing is sent anywhere.</p>
  </main>
{:else}
  <main class="columns">
    <nav class="results" aria-label="Results">
      {#if viewer.results}
        <ResultList view={viewer.results} selected={viewer.nodeId} {hrefFor} />
      {:else}
        <p class="empty body-screen">Search for a name, an alias or words in the text.</p>
      {/if}
      <TypeList types={viewer.file.nodeTypes} selected={viewer.tableRoute?.type ?? null} hrefFor={typeHref} />
    </nav>
    {#if viewer.tableRoute}
      <div class="wide">
        <TableView view={viewer.table} route={viewer.tableRoute} hrefFor={tableHref} nodeHref={hrefFor} onfilter={filtered} />
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
      <section class="entity"><EntityCard node={viewer.page.node} /></section>
      <aside class="context" aria-label="Links and sources"><NodeContext view={viewer.page} {hrefFor} /></aside>
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
