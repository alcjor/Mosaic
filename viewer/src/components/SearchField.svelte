<script lang="ts">
  /** SearchField (brand book, section 6): one search box; submitting it asks `find`. */
  let {
    value = "",
    disabled = false,
    onsearch,
  }: { value?: string; disabled?: boolean; onsearch: (query: string) => void } = $props();

  let draft = $derived(value);
</script>

<form
  class="search"
  role="search"
  onsubmit={(event) => {
    event.preventDefault();
    onsearch(draft);
  }}
>
  <input
    class="field body-screen"
    type="search"
    name="q"
    aria-label="Search the mosaic"
    placeholder="Search names, text and aliases"
    autocomplete="off"
    {disabled}
    bind:value={draft}
  />
</form>

<style>
  .search {
    flex: 1;
    max-inline-size: 40rem;
  }

  .field {
    box-sizing: border-box;
    inline-size: 100%;
    block-size: 2.5rem;
    padding-inline: var(--space-3);
    border: 1px solid var(--ink-muted);
    border-radius: var(--radius-md);
    background: var(--surface);
    color: var(--ink);
  }

  .field::placeholder {
    color: var(--ink-muted);
  }

  .field:focus-visible {
    outline: 2px solid var(--focus-ring);
    outline-offset: 2px;
  }

  .field:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
