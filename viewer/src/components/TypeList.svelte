<script lang="ts">
  /** The node types the mosaic declares, each opening its table, with its node count. */
  import type { NodeType } from "@mosaic/kit";
  import TypeChip from "./TypeChip.svelte";

  let {
    types,
    selected = null,
    hrefFor,
  }: { types: readonly NodeType[]; selected?: string | null; hrefFor: (type: string) => string } = $props();
</script>

<h2 class="heading section-label">Tables</h2>
{#if types.length === 0}
  <p class="empty body-screen">This mosaic declares no node type.</p>
{/if}
<ul class="rows">
  {#each types as type (type.name)}
    <li>
      <a
        class="row"
        class:selected={type.name === selected}
        href={hrefFor(type.name)}
        aria-current={type.name === selected ? "page" : undefined}
        data-type={type.name}
      >
        <TypeChip type={type.name} />
        <span class="count caption">{type.count}</span>
      </a>
    </li>
  {/each}
</ul>

<style>
  .heading {
    margin: var(--space-4) var(--space-3) var(--space-1);
    color: var(--accent);
    text-transform: uppercase;
  }

  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .row {
    display: flex;
    justify-content: space-between;
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

  .count {
    color: var(--ink-muted);
    font-family: var(--font-mono);
  }

  .empty {
    margin: var(--space-3);
    color: var(--ink-muted);
  }
</style>
