<script lang="ts">
  import { FORMAT_VERSION, TOOLS } from "@mosaic/kit";
</script>

<header class="band">
  <span class="name code">Mosaic viewer</span>
</header>
<main>
  <h1 class="section-label label">Status</h1>
  <p class="body-screen">Reads Mosaic format {FORMAT_VERSION}. Opening a mosaic arrives in milestone M2.</p>
  <p class="caption muted">Kit tools: {TOOLS.join(", ")}</p>
</main>

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
    block-size: var(--app-header);
    padding-inline: var(--space-4);
    background: var(--slab);
  }

  .name {
    color: var(--shard-4);
  }

  main {
    max-inline-size: 40rem;
    margin-inline: auto;
    padding: var(--space-5) var(--space-4);
  }

  .label {
    margin: 0 0 var(--space-2);
    color: var(--accent);
    text-transform: uppercase;
  }

  .muted {
    color: var(--ink-muted);
  }
</style>
