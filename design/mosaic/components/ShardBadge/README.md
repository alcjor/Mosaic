# ShardBadge

A numbered, irregular shard that replaces circles and pills for sequences: steps, phases, stages.

- Sizes: 30px (steps, `brand-navy` fill) and 20px (roadmap phases, `accent` fill). The number is white, 700 weight.
- Use the four outlines shown, in order, so badges in one sequence never look identical. They are part of the identity; don't redraw them as regular polygons.
- Never round the corners (`radius-none`), add strokes or shadows.
- In a static SVG, mark it `aria-hidden="true"` when the step title already carries the number; otherwise give it `role="img"` and an `aria-label`.
