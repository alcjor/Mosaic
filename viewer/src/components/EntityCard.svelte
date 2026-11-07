<script lang="ts">
  /**
   * EntityCard (brand book, section 6): what `get` returns for one node: its label, type, id,
   * summary, properties, aliases and external references.
   */
  import type { GetData } from "@mosaic/kit";
  import TypeChip from "./TypeChip.svelte";

  let { node }: { node: GetData } = $props();

  /** A property value as text: strings as they are, anything else as JSON. */
  function shown(value: unknown): string {
    return typeof value === "string" ? value : JSON.stringify(value);
  }

  let entries = $derived(Object.entries(node.props ?? {}));
</script>

<article class="card" aria-label={node.id}>
  <h1 class="title category">{node.label ?? node.id}</h1>
  <p class="kind"><TypeChip type={node.type} /> <span class="id code">{node.id}</span></p>
  {#if node.summary !== null}
    <p class="summary body-screen">{node.summary}</p>
  {/if}

  {#if entries.length > 0}
    <h2 class="heading section-label">Properties</h2>
    <table class="props body-screen">
      <tbody>
        {#each entries as [key, value] (key)}
          <tr>
            <th scope="row" class="key">{key}</th>
            <td class="value" class:mono={typeof value !== "string"}>{shown(value)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if node.aliases.length > 0}
    <h2 class="heading section-label">Also known as</h2>
    <ul class="aliases body-screen">
      {#each node.aliases as alias (alias)}
        <li>{alias}</li>
      {/each}
    </ul>
    {#if node.aliases_total > node.aliases.length}
      <p class="more caption">and {node.aliases_total - node.aliases.length} more</p>
    {/if}
  {/if}

  {#if node.external_refs.length > 0}
    <h2 class="heading section-label">External references</h2>
    <ul class="refs code">
      {#each node.external_refs as ref, i (i)}
        <li><span class="ref-chip">{ref.system} · {ref.kind}</span> {JSON.stringify(ref.locator)}</li>
      {/each}
    </ul>
  {/if}
</article>

<style>
  .card {
    padding: var(--space-5);
  }

  .title {
    margin: 0;
    color: var(--heading);
    overflow-wrap: anywhere;
  }

  .kind {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: var(--space-2) 0 0;
  }

  .id {
    color: var(--ink-muted);
    overflow-wrap: anywhere;
  }

  .summary {
    margin: var(--space-4) 0 0;
  }

  .heading {
    margin: var(--space-5) 0 var(--space-2);
    color: var(--accent);
    text-transform: uppercase;
  }

  .props {
    inline-size: 100%;
    border-collapse: collapse;
  }

  .props tr {
    border-block-end: 1px solid var(--border);
  }

  .key {
    padding: var(--space-1) var(--space-3) var(--space-1) 0;
    color: var(--ink-muted);
    font-weight: normal;
    text-align: start;
    vertical-align: top;
  }

  .value {
    padding: var(--space-1) 0;
    color: var(--ink);
    overflow-wrap: anywhere;
  }

  .mono {
    font-family: var(--font-mono);
  }

  .aliases,
  .refs {
    margin: 0;
    padding-inline-start: var(--space-4);
  }

  .ref-chip {
    padding: 0 var(--space-1);
    border-radius: var(--radius-sm);
    background: var(--turquoise-tint);
    color: var(--turquoise-text);
  }

  .more {
    margin: var(--space-1) 0 0;
    color: var(--ink-muted);
  }
</style>
