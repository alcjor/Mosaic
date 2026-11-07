<script lang="ts">
  /** TypeChip (brand book, section 6): the type name after a small shard. */
  let { type }: { type: string } = $props();
</script>

<span class="chip caption"><span class="shard" aria-hidden="true"></span>{type}</span>

<style>
  .chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    color: var(--ink-muted);
  }

  .shard {
    inline-size: 10px;
    block-size: 10px;
    background: var(--ink-muted);
    clip-path: polygon(10% 0, 100% 20%, 85% 100%, 0 75%);
  }
</style>
