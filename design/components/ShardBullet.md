# ShardBullet

A list whose markers are small 10px shards in `accent`, rotating through three outlines so no two neighbours match.

- Markup: a real `<ul>`; the shard SVG is decorative (`aria-hidden="true"`).
- Marker sits 4px down to align with the first line's x-height at `body-print`; gap `space-2`.
- Up to five items; each item one or two lines. Longer content becomes StepRows.
