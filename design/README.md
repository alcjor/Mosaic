# Design system

Mosaic's visual identity and the viewer's app style. **The source of truth is the
MOSAIC Design System artifact**; this folder is a copy of its text, tokens and assets so
code can use them and tests can enforce them.

| File | What |
| --- | --- |
| `assets/` | Logos, state icons and imagery, as SVG and PNG files ready to use |
| `tokens.json` | Colours (light "Paper" and dark "Navy ground" themes), type, spacing, radii |
| `brand-book.md` | The brand book: naming, voice, colour roles, the shard motif, logo, **section 6: App** (the viewer's components and states) |
| `components/*.md` | Guidelines per component |
| `reference/viewer/` | Mock-ups of the viewer, for reference only: they illustrate needs in `docs/design.md` and bind nothing (see its README) |

Logos, icons and imagery are copied into `assets/` (see its README); the design system's asset
store stays their source.

## How it is enforced

- `scripts/gen_tokens.py` turns `tokens.json` into `viewer/src/design/tokens.css`
  (CSS custom properties, one `.class` per type style). A test fails when the CSS
  is out of date.
- Viewer styles use tokens only: Stylelint (`viewer/.stylelintrc.json`) rejects
  hex, `rgb()`/`hsl()` and named colours, and raw lengths for spacing, radii and
  font sizes; a test rejects `var(--…)` names that are not tokens and inline
  `style=` attributes.
- These files and `viewer/src/design/` are in `.github/CODEOWNERS`.

## Changing it

Change the design system first, then copy `tokens.json` (and any changed text)
here and run `uv run python scripts/gen_tokens.py`.
