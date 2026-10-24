---
name: mosaic-design
description: MOSAIC brand and UI rules for this repo. Use for any change to the viewer (viewer/), its theme, the static export or Tessera branding, logos, icons, colours, fonts, UI copy, or the prototype.
---

# MOSAIC design

The viewer must look and read like MOSAIC. Before changing any UI:

1. Read `design/viewer-guidelines.md` (rules DG-01 … DG-53). It says how the design
   system applies to this app.
2. For anything it does not cover, read `design/mosaic/README.md` (the brand guidelines)
   and `design/mosaic/tokens.json`.
3. Look at `prototype/index.html` for the agreed look of the ops view.

Hard rules:

- Colours, fonts, spacing and radii only through the CSS variables generated from
  `design/mosaic/tokens.json`. No hex values in `viewer/src` outside the generated theme.
- Colour carries meaning (reference data blue, documents terracotta, warnings saffron,
  errors majolica). Never use a colour for decoration or for a different meaning.
- Logos come from `design/mosaic/logos/` unchanged. Never draw or recolour a mark.
- Fonts are bundled; no requests to Google Fonts or any other host.
- Files under `design/mosaic/` are a copy of the design system: never edit them. If the
  design system lacks something, stop and ask.

Before saying a UI change is done, run the checklist in
`design/viewer-guidelines.md` § 7 and put the screenshots in the PR.
