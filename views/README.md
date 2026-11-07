# View files

A view file (YAML) shapes `mosaic view` and `mosaic export`: which types appear,
columns, what a node page shows, labels, theme, which types an export carries, and
`search: semantic` or `search: text` (docs/design.md, Implementation plan, View file).

- `view.schema.json`: its JSON Schema (not a normative file).
- `example.yaml`: every setting, with its default in a comment.

Every key is optional, so an empty view file, or none, gives M2's viewer. The reader
is `mosaic_build.view_file`; each fixture's view file is
`conformance/fixtures/<fixture>/view.yaml`.
