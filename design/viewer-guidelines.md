# Viewer design guidelines

How the MOSAIC design system (`design/mosaic/`) applies to the viewer and its exports.
The design system's `README.md` wins on anything not covered here. The prototype
(`prototype/index.html`) shows these rules applied.

## 1. Tokens, never literals

- **DG-01** Every colour, font, spacing and radius in `viewer/src` comes from a CSS
  variable. The variables are generated at build time from `design/mosaic/tokens.json`
  into one theme file; that file is the only place a hex value may appear (lint test).
- **DG-02** Light theme uses each token's `light` value, dark theme its `dark` value;
  tokens with a single value apply to both. Both themes follow the OS setting and have a
  manual toggle.
- **DG-03** The viewer does not add colours the design system lacks. If a needed shade is
  missing, stop and ask; the fix is a design-system change, not a local colour.

## 2. Colour means something

| Meaning | Token | In the viewer |
|---|---|---|
| Brand | `brand-navy`, `slab` | Header bar, centre of a selection |
| Reference data | `accent` (`data-reference`) | Links to SRDB entries, FOPs, code; their icons and chips |
| Documents | `terracotta` (`data-documents`) | Icons, chips and dashed borders for manual and ICD sources; `terracotta-text` for words |
| Telemetry | `turquoise` (`data-telemetry`) | Reserved for the telemetry hook. Unused in v1 |
| Warning | `saffron` (`status-warning`) | Unresolved references (dashed underline), warning badges. Text uses `saffron-text` |
| Error | `majolica` (`status-error`) | Unresolved references a FOP sends, error badges. Always with a label or icon |
| Success | `olive` (`status-success`) | Only with a check icon |
| AI proposal | `saffron` (`ai-proposal`) | Reserved for AI-proposed links. Unused in v1 |

- **DG-10** Saffron and majolica are never decoration, and never text on white.
- **DG-11** Syntax highlighting in code and scripts uses only `heading` (keywords),
  `ink-muted` (comments, docstrings) and `accent` (preprocessor, decorators), so it never
  competes with links or status colours.
- **DG-12** Colour is never the only signal: unresolved references are also dashed, errors
  carry a label, documents a document icon.

## 3. Brand elements

- **DG-20** Header: `mosaic-mark-dark` on the navy slab, then the wordmark **MOSAIC** in
  capitals (700 weight, 0.04em tracking), then the project and view. Never redraw, recolour
  or re-typeset the mark; use the SVG from `design/mosaic/logos/`.
- **DG-21** Favicon: `mosaic-app-icon-32.png`; larger icons from the same set.
- **DG-22** A customer export (MOSAIC Tessera) uses the Tessera mark and lockup instead,
  and the descriptor "The connected data pack". Never place both marks side by side
  without wordmarks.
- **DG-23** The shard motif stays out of content. At most the ShardStrip under the header
  and ShardBadges for numbered sequences (FOP steps may use them). No decorative shards
  in panels or tables.

## 4. Type

- **DG-30** One family, the design system's `sans` stack (IBM Plex Sans, plus IBM Plex
  Mono for IDs, mnemonics and code), bundled with the viewer (SIL OFL). No font requests
  to the network.
- **DG-31** Section and group titles use the `section-label` style: 12px, 600 weight,
  uppercase, 1.6px tracking, `accent` (`terracotta-text` for document groups).
- **DG-32** IDs and mnemonics are always set in mono; descriptions in sans.
- **DG-33** Body text 14–16px; nothing below 11px.

## 5. Layout and components

- **DG-40** Surfaces: page `surface`, panels on `surface` with `border` hairlines,
  highlighted areas on `surface-tint`. Radius `radius-md` (6px) on panels and cards;
  shards and badges are never rounded.
- **DG-41** Cards only where they mean "a separate object" (the detail panel, a search
  result); not around every block.
- **DG-42** Spacing from the `space-*` scale only.

## 6. Words in the UI

- **DG-50** Plain, concrete, operations vocabulary: name the real artefact ("SW user
  manual 4.2", "FOP-PWR-001 step 2"), not the mechanism ("segment", "scope").
- **DG-51** Buttons say what happens ("Open page", "Open location"); errors say what went
  wrong and what to do.
- **DG-52** Never "AI builds", "fully automated". When AI arrives: "AI proposes, engineers
  approve".
- **DG-53** The brand's outward-copy rules (no standards promises, no positioning against
  tools) apply to anything the viewer shows customers, such as a Tessera footer.

## 7. Checks before a UI change is done

1. Screenshots of the changed screens, light and dark, desktop and 390 px wide, in the PR.
2. No literal colours outside the generated theme file (DG-01 test passes).
3. Contrast: text 4.5:1, large text and UI parts 3:1, in both themes (axe run, VIEW-83).
4. Logo files untouched; the header matches DG-20.
5. Every new colour use maps to a row in § 2.
