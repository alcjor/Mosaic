# Design system

Mosaic's visual identity and the viewer's app style. **The source of truth is the
MOSAIC Design System artifact**; this folder is a copy of its text and tokens so
code can use them and tests can enforce them.

| File | What |
| --- | --- |
| `tokens.json` | Colours (light "Paper" and dark "Navy ground" themes), type, spacing, radii |
| `brand-book.md` | The brand book: naming, voice, colour roles, the shard motif, logo, **section 6: App** (the viewer's components and states) |
| `components/*.md` | Guidelines per component |

Logos, icons and imagery stay in the design system's asset store.

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
