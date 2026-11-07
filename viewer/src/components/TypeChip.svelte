<script lang="ts">
  /** TypeChip (brand book, section 6): the type name, or the view file's label for it, after a small shard. */
  let { type, label = null }: { type: string; label?: string | null } = $props();
</script>

<span class="chip caption"><span class="shard" aria-hidden="true"></span>{label ?? type}</span>

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
