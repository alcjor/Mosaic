<script lang="ts">
  /**
   * The search results (brand book, section 6: ResultRow): each result's label, type, id and
   * how it matched, grouped by tier in `find`'s order, exact first. A row opens its node.
   */
  import type { SearchView, ToolFailure } from "../lib/mosaic.js";
  import { TIER_NAMES } from "../lib/mosaic.js";

  let {
    view,
    selected = null,
    hrefFor,
    typeLabel = (type: string) => type,
  }: {
    view: SearchView | ToolFailure;
    selected?: string | null;
    hrefFor: (id: string) => string;
    typeLabel?: (type: string) => string;
  } = $props();
</script>

{#if "message" in view}
  <p class="banner body-screen" role="alert">{view.message}</p>
{:else if view.groups.length === 0}
  <p class="empty body-screen">No results for “{view.query}”.</p>
{:else}
  <p class="count caption">{view.total} {view.total === 1 ? "result" : "results"}</p>
  {#each view.groups as group (group.match)}
    <section aria-label={TIER_NAMES[group.match]}>
      <h2 class="tier section-label">{TIER_NAMES[group.match]}</h2>
      <ul class="rows">
        {#each group.results as result (result.id)}
          <li>
            <a
              class="row"
              class:selected={result.id === selected}
              href={hrefFor(result.id)}
              aria-current={result.id === selected ? "page" : undefined}
              data-id={result.id}
              data-match={result.match}
            >
              <span class="label panel-title">{result.label ?? result.id}</span>
              <span class="meta caption"><span class="code-text">{typeLabel(result.type)}</span> · <span class="code-text">{result.id}</span></span>
              <span class="tag caption">{TIER_NAMES[result.match]}</span>
            </a>
          </li>
        {/each}
      </ul>
    </section>
  {/each}
{/if}

<style>
  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .row {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 0 var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-inline-start: 3px solid transparent;
    color: var(--ink);
    text-decoration: none;
  }

  .row:hover {
    background: var(--surface-tint);
  }

  .row:focus-visible {
    outline: 2px solid var(--focus-ring);
    outline-offset: 2px;
  }

  .row.selected {
    border-inline-start-color: var(--accent);
    background: var(--surface-tint);
  }

  .row.selected .label {
    color: var(--accent);
  }

  .label {
    grid-column: 1;
    overflow-wrap: anywhere;
  }

  .meta {
    grid-column: 1;
    color: var(--ink-muted);
    overflow-wrap: anywhere;
  }

  .code-text {
    font-family: var(--font-mono);
  }

  .tag {
    grid-column: 2;
    grid-row: 1 / span 2;
    align-self: center;
    color: var(--ink-muted);
  }

  .tier {
    margin: var(--space-4) var(--space-3) var(--space-1);
    color: var(--accent);
    text-transform: uppercase;
  }

  .count,
  .empty {
    margin: var(--space-3);
    color: var(--ink-muted);
  }

  .banner {
    margin: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--majolica-tint);
    color: var(--majolica-text);
  }
</style>
