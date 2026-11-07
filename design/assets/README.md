# Assets

Logos, icons and imagery, copied from the MOSAIC Design System artifact (the source of truth;
see `../README.md`). Use these files as they are: regenerate them in the design system and copy
them here again, never redraw or edit them. The brand book (sections 2 to 4) says how and where
each one is used.

## Logos (`logos/`)

"The last shard": a square tile of three shards with a fourth, lighter shard being set into its
corner, alone or locked up with the wordmark.

| File | Use |
| --- | --- |
| `mosaic-lockup-light.svg` / `.png` | On white: mark, wordmark in `brand-navy`, category line in `accent` |
| `mosaic-lockup-dark.svg` / `.png` | On `brand-navy`: white mark and wordmark, category line in `shard-4` |
| `mosaic-mark-light.svg` / `.png` | The mark alone, transparent, for light grounds |
| `mosaic-mark-dark.svg` / `.png` | The mark alone, transparent, for navy grounds |
| `mosaic-app-icon-512.png`, `-180.png`, `-32.png` | The dark mark on a navy square: favicons, avatars, the organisation picture |

SVGs have their text converted to outlines; use PNG only where SVG is not accepted. Clear space
is a quarter of the mark's width. Minimum size: 16px or 8 mm for the mark, 120px or 35 mm for a
lockup.

## Icons (`icons/`)

One mark, five states of a build. The Build state is the logo mark itself; the other four are
here, plus the strip that shows all five in order.

| File | State | Stands for |
| --- | --- | --- |
| `mosaic-icon-tessera-*` | Tessera: the last piece, alone | One frozen input: a `.tessera` file, and the tessera builders that make it |
| `mosaic-icon-recipe-*` | Pattern: the seams inside a dashed square (file name kept from "recipe") | A pattern: `pattern.yaml` and `proposals.yaml` |
| `mosaic-icon-built-*` | Built mosaic: all four pieces in place | A `.mosaic` file and its releases |
| `mosaic-icon-embedded-*` | Embedded: the built mosaic in a rounded frame | The mosaic kit, and anything that embeds it |
| `mosaic-build-strip-*` | All five states in build order, with chevrons | The README and the docs home page |

Each comes as `-light` (white grounds) and `-dark` (navy grounds), in SVG (viewBox 100 × 100;
the strip 644 × 100) and transparent PNG (512px; the strip 1288 × 200). Minimum 16px; the
pattern icon 24px. State icons name things: never use them as bullets or decoration.

## Imagery (`imagery/`)

Trencadís artwork: loose pieces on the left settle into the bands of a finished mosaic on the
right. It is decorative, so it carries no data caption.

| File | Use |
| --- | --- |
| `mosaic-hero-glaze.png`, `mosaic-hero-blue.png` | 16:9 title images (2880 × 1620) with mark, wordmark, category line and tagline |
| `mosaic-hero-glaze-clean.png`, `mosaic-hero-blue-clean.png` | The same art without text, for your own titles and the 2:1 social preview; keep text in the left 40% |
| `banner-assembly-glaze.png`, `banner-assembly-blue.png` | The A4 one-pager header (3:1); keep text in the left third |
| `flyer-strip.png` | The ShardStrip divider |
| `mosaic-viewer-mock.png` | The viewer mock-up the brand book's section 6 refers to |

## In the viewer

The viewer's mark and favicon come from `logos/` (the dark mark on the navy header band, the app
icons for the favicon), and its empty states use the tessera icon, as brand book section 6 says.
Colours still come from tokens: these files are pictures, never a source of values.
