<script lang="ts">
  /**
   * TableView (brand book, section 6): one page of `table` for a node type. The column headers
   * sort, the filter form adds a `where` condition, and the pager moves through pages; each is a
   * new `table` call through the page's address. A row's id opens its node page. With a view
   * file, the type and its columns carry the file's labels.
   */
  import type { ToolFailure } from "../lib/mosaic.js";
  import { OPERATORS, type Condition, type TableRoute } from "../lib/route.js";
  import { cellText, filterValue, type TableView } from "../lib/tables.js";
  import type { Shape } from "../lib/view.js";

  let {
    view,
    route,
    hrefFor,
    nodeHref,
    onfilter,
    shape = null,
  }: {
    view: TableView | ToolFailure | null;
    route: TableRoute;
    hrefFor: (route: TableRoute) => string;
    nodeHref: (id: string) => string;
    onfilter: (condition: Condition) => void;
    shape?: Shape | null;
  } = $props();

  const named = (column: string): string => shape?.label(route.type, column) ?? column;

  let column = $state("");
  let op = $state<Condition["op"]>("=");
  let kind = $state<"text" | "number" | "boolean">("text");
  let text = $state("");
  let problem = $state<string | null>(null);

  let columns = $derived(view && "columns" in view ? view.columns.slice(1) : []);

  // The column picked is always one of this table's columns, shown in the select: the first
  // until the reader picks another, and the first again when the table's columns change.
  $effect(() => {
    if (!columns.includes(column)) column = columns[0] ?? "";
  });

  /** The route that sorts by `name`: ascending first, then descending. */
  function sorted(name: string): TableRoute {
    const desc = route.order?.column === name && !route.order.desc;
    return { ...route, page: 1, order: { column: name, desc } };
  }

  function sortState(name: string): "ascending" | "descending" | "none" {
    if (route.order?.column !== name) return "none";
    return route.order.desc ? "descending" : "ascending";
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    const value = filterValue(text, kind);
    const chosen = columns.includes(column) ? column : columns[0];
    if (chosen === undefined) return;
    if (value === null) {
      problem = kind === "number" ? "Enter a number." : "Enter true or false.";
      return;
    }
    if (op === "contains" && typeof value !== "string") {
      problem = "contains takes text.";
      return;
    }
    problem = null;
    onfilter({ column: chosen, op, value });
  }
</script>

<section class="table-view" aria-label={`Table ${route.type}`} data-type={route.type}>
  <h1 class="title category">{shape?.typeLabel(route.type) ?? route.type}</h1>

  {#if route.where.length > 0}
    <ul class="filters" aria-label="Filters">
      {#each route.where as condition, i (i)}
        <li class="filter caption">
          <span class="code-text">{condition.column} {condition.op} {JSON.stringify(condition.value)}</span>
          <a
            class="remove"
            href={hrefFor({ ...route, page: 1, where: route.where.filter((_, j) => j !== i) })}
            aria-label={`Remove filter ${condition.column} ${condition.op} ${JSON.stringify(condition.value)}`}>×</a
          >
        </li>
      {/each}
    </ul>
  {/if}

  {#if columns.length > 0}
    <form class="filter-form" aria-label="Add a filter" onsubmit={submit}>
      <select class="control caption" name="column" aria-label="Column" bind:value={column}>
        {#each columns as name (name)}
          <option value={name}>{named(name)}</option>
        {/each}
      </select>
      <select class="control caption" name="op" aria-label="Operator" bind:value={op}>
        {#each OPERATORS as o (o)}
          <option value={o}>{o}</option>
        {/each}
      </select>
      <select class="control caption" name="kind" aria-label="Value kind" bind:value={kind}>
        <option value="text">text</option>
        <option value="number">number</option>
        <option value="boolean">true / false</option>
      </select>
      <input class="control caption" name="value" aria-label="Value" bind:value={text} />
      <button class="button caption" type="submit">Filter</button>
      {#if problem}<span class="problem caption" role="alert">{problem}</span>{/if}
    </form>
  {/if}

  {#if view === null}
    <p class="empty body-screen">Loading…</p>
  {:else if "message" in view}
    <p class="banner body-screen" role="alert">{view.message}</p>
  {:else}
    <div class="scroll">
      <table class="rows body-screen">
        <thead>
          <tr>
            <th scope="col" class="head caption" aria-sort={route.order === null ? "ascending" : "none"}>
              <a href={hrefFor({ ...route, page: 1, order: null })} class:sorted={route.order === null}>id</a>
            </th>
            {#each columns as name (name)}
              <th scope="col" class="head caption" aria-sort={sortState(name)}>
                <a href={hrefFor(sorted(name))} class:sorted={sortState(name) !== "none"} data-column={name}
                  >{named(name)}{sortState(name) === "ascending" ? " ↑" : sortState(name) === "descending" ? " ↓" : ""}</a
                >
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each view.rows as row (String(row[0]))}
            <tr>
              <td class="id"><a href={nodeHref(String(row[0]))} data-id={String(row[0])}>{String(row[0])}</a></td>
              {#each row.slice(1) as cell, i (i)}
                <td class:mono={typeof cell === "number" || typeof cell === "boolean"}>{cellText(cell)}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if view.rows.length === 0}
      <p class="empty body-screen">No rows.</p>
    {/if}
    <nav class="pager caption" aria-label="Pages">
      {#if view.page > 1}
        <a href={hrefFor({ ...route, page: view.page - 1 })} rel="prev">Previous</a>
      {/if}
      <span class="where">Page {view.page} of {view.pages} · {view.total} {view.total === 1 ? "row" : "rows"}</span>
      {#if view.page < view.pages}
        <a href={hrefFor({ ...route, page: view.page + 1 })} rel="next">Next</a>
      {/if}
    </nav>
  {/if}
</section>

<style>
  .table-view {
    padding: var(--space-5);
    min-inline-size: 0;
  }

  .title {
    margin: 0 0 var(--space-3);
    color: var(--heading);
  }

  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0 0 var(--space-3);
    padding: 0;
    list-style: none;
  }

  .filter {
    display: inline-flex;
    gap: var(--space-1);
    padding: 0 var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--surface-tint);
  }

  .remove {
    color: var(--ink-muted);
    text-decoration: none;
  }

  .filter-form {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: 0 0 var(--space-3);
  }

  .control {
    block-size: 2rem;
    padding-inline: var(--space-2);
    border: 1px solid var(--ink-muted);
    border-radius: var(--radius-md);
    background: var(--surface);
    color: var(--ink);
  }

  .button {
    block-size: 2rem;
    padding-inline: var(--space-3);
    border: 1px solid var(--accent);
    border-radius: var(--radius-md);
    background: var(--surface);
    color: var(--accent);
    cursor: pointer;
  }

  .control:focus-visible,
  .button:focus-visible,
  a:focus-visible {
    outline: 2px solid var(--focus-ring);
    outline-offset: 2px;
  }

  .problem {
    color: var(--majolica-text);
  }

  .scroll {
    overflow-x: auto;
  }

  .rows {
    inline-size: 100%;
    border-collapse: collapse;
  }

  .head {
    position: sticky;
    inset-block-start: 0;
    padding: var(--space-2) var(--space-3);
    background: var(--surface-tint);
    text-align: start;
    white-space: nowrap;
  }

  .head a {
    color: var(--ink);
    text-decoration: none;
  }

  .head a.sorted {
    border-block-end: 2px solid var(--accent);
  }

  td {
    padding: var(--space-1) var(--space-3);
    border-block-end: 1px solid var(--border);
    vertical-align: top;
    overflow-wrap: anywhere;
  }

  .id a {
    color: var(--accent);
    font-family: var(--font-mono);
  }

  .mono,
  .code-text {
    font-family: var(--font-mono);
  }

  .pager {
    display: flex;
    gap: var(--space-3);
    margin-block-start: var(--space-3);
    color: var(--ink-muted);
  }

  .empty {
    color: var(--ink-muted);
  }

  .banner {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--majolica-tint);
    color: var(--majolica-text);
  }
</style>
