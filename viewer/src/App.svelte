<script lang="ts">
  import { FORMAT_VERSION, TOOLS } from "@mosaic/kit";
</script>

<main>
  <h1>Mosaic viewer</h1>
  <p>Reads Mosaic format {FORMAT_VERSION}. Opening a mosaic arrives in milestone M2.</p>
  <p>Kit tools: {TOOLS.join(", ")}</p>
</main>

<style>
  main {
    font-family: system-ui, sans-serif;
    max-width: 40rem;
    margin: 2rem auto;
    padding: 0 1rem;
  }
</style>
