<script lang="ts">
  /**
   * SearchField (brand book, section 6): one search box; submitting it asks `find`. A mode switch
   * at its right, *Semantic* / *Text*, starts as the view file's `search` setting.
   */
  import { MODE_NAMES, SEARCH_MODES, type SearchMode } from "../lib/view.js";

  let {
    value = "",
    disabled = false,
    mode = "semantic",
    onsearch,
    onmode = () => {},
  }: {
    value?: string;
    disabled?: boolean;
    mode?: SearchMode;
    onsearch: (query: string) => void;
    onmode?: (mode: SearchMode) => void;
  } = $props();

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
  <span class="modes" role="group" aria-label="Search mode">
    {#each SEARCH_MODES as m (m)}
      <button
        class="mode caption"
        class:active={m === mode}
        type="button"
        aria-pressed={m === mode}
        data-mode={m}
        {disabled}
        onclick={() => onmode(m)}>{MODE_NAMES[m]}</button
      >
    {/each}
  </span>
</form>

<style>
  .search {
    display: flex;
    flex: 1;
    gap: var(--space-2);
    align-items: center;
    max-inline-size: 40rem;
  }

  .field {
    box-sizing: border-box;
    flex: 1;
    min-inline-size: 0;
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

  .modes {
    display: inline-flex;
    border: 1px solid var(--ink-muted);
    border-radius: var(--radius-md);
    background: var(--surface);
    overflow: hidden;
  }

  .mode {
    padding: var(--space-1) var(--space-2);
    border: none;
    background: transparent;
    color: var(--ink-muted);
    cursor: pointer;
  }

  .mode.active {
    background: var(--accent);
    color: var(--surface);
  }

  .mode:hover:not(.active, :disabled) {
    background: var(--surface-tint);
  }

  .mode:focus-visible {
    outline: 2px solid var(--focus-ring);
    outline-offset: 2px;
  }

  .mode:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
