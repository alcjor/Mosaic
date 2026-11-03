# ShardBadge

A numbered, irregular shard that replaces circles and pills for sequences: steps and the six rules.

- Sizes: 30px (steps and rules, `heading` fill) and 20px (compact sequences, `accent` fill). The number is in `surface`, 700 weight, so a badge holds on paper and on navy.
- Use the four outlines shown, in order, so badges in one sequence never look identical; a fifth or sixth badge starts again from the first. They are part of the identity; don't redraw them as regular polygons.
- Rule badges: in docs, a numbered badge followed by the rule's words ("4 · Every value has evidence") marks the rule a feature relies on.
- Never round the corners (`radius-none`), add strokes or shadows.
- In a static SVG, mark it `aria-hidden="true"` when the step title already carries the number; otherwise give it `role="img"` and an `aria-label`.
