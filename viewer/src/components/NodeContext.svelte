<script lang="ts">
  /**
   * The context column (brand book, section 6): the node's links from `neighbors`, grouped by
   * edge type and direction with a count (NeighborList), each opening the other node; then its
   * sources from `cite` (CitationChip). With a view file, the links are those of the edge types
   * its `page` names, in that order, under its labels.
   */
  import type { NodeView } from "../lib/mosaic.js";
  import { inPageOrder, type Shape } from "../lib/view.js";

  let { view, hrefFor, shape = null }: { view: NodeView; hrefFor: (id: string) => string; shape?: Shape | null } = $props();

  let links = $derived(inPageOrder(view.links, shape?.page(view.node.type) ?? null, (group) => group.edge));

  /**
   * An edge type as a reader says it: `directed_by` out is "directed by", in is "← directed by";
   * the view file's label for it, on this node's type, replaces the words.
   */
  function edgeName(edge: string, direction: "out" | "in"): string {
    const words = shape?.label(view.node.type, edge) ?? edge.replaceAll("_", " ");
    return direction === "out" ? words : `← ${words}`;
  }
</script>

<section class="block" aria-label="Links">
  <h2 class="heading section-label">Links</h2>
  {#if links.length === 0}
    <p class="empty body-screen">No links.</p>
  {/if}
  {#each links as group (`${group.edge} ${group.direction}`)}
    <section class="group" aria-label={edgeName(group.edge, group.direction)} data-edge={group.edge} data-direction={group.direction}>
      <h3 class="edge section-label">{edgeName(group.edge, group.direction)} · {group.count}</h3>
      <ul class="rows">
        {#each group.edges as link (`${link.id} ${link.qualifier ?? ""}`)}
          <li>
            <a class="row" href={hrefFor(link.id)} data-id={link.id}>
              <span class="label panel-title">{link.label ?? link.id}</span>
              <span class="meta caption">{link.id}{link.qualifier ? ` · ${link.qualifier}` : ""}</span>
            </a>
          </li>
        {/each}
      </ul>
      {#if group.count > group.edges.length}
        <p class="more caption">and {group.count - group.edges.length} more</p>
      {/if}
    </section>
  {/each}
</section>

<section class="block" aria-label="Sources">
  <h2 class="heading section-label">Sources</h2>
  <ul class="rows">
    {#each view.sources as row, i (i)}
      <li class="source">
        <span class="cite code" title={row.snippet ?? undefined}>{row.source}{row.locator ? `:${row.locator}` : ""}</span>
        <span class="method caption">{row.method}{row.confidence !== null ? ` · confidence ${row.confidence}` : ""}</span>
        {#if row.snippet !== null}
          <blockquote class="snippet caption">{row.snippet}</blockquote>
        {/if}
      </li>
    {/each}
  </ul>
  {#if view.sourcesTotal > view.sources.length}
    <p class="more caption">and {view.sourcesTotal - view.sources.length} more</p>
  {/if}
</section>

<style>
  .block {
    padding: var(--space-3) 0;
  }

  .heading,
  .edge {
    margin: var(--space-3) var(--space-3) var(--space-1);
    color: var(--accent);
    text-transform: uppercase;
  }

  .edge {
    color: var(--ink-muted);
  }

  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .row {
    display: block;
    padding: var(--space-1) var(--space-3);
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

  .label {
    display: block;
    overflow-wrap: anywhere;
  }

  .meta {
    display: block;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    overflow-wrap: anywhere;
  }

  .source {
    padding: var(--space-2) var(--space-3);
  }

  .cite {
    display: inline-block;
    padding: 0 var(--space-1);
    border-radius: var(--radius-sm);
    background: var(--surface-tint);
    overflow-wrap: anywhere;
  }

  .method {
    display: block;
    color: var(--ink-muted);
  }

  .snippet {
    margin: var(--space-1) 0 0;
    padding-inline-start: var(--space-2);
    border-inline-start: 2px solid var(--border);
    color: var(--ink);
    overflow-wrap: anywhere;
  }

  .empty,
  .more {
    margin: var(--space-1) var(--space-3);
    color: var(--ink-muted);
  }
</style>
