# Viewer mock-ups (reference only)

Seven screens that show one way the viewer could look once it has a graph view, chains and a
reworked shell. They illustrate the needs; they are **not** requirements.

| Image | Shows | Illustrates |
| --- | --- | --- |
| `1-node-page.png` | A node's page: search in the header, a type rail, links as sentences, sources and provenance on the right, a status bar | Brand book section 6 (Shell) |
| `2-graph-schema.png` | The mosaic's types and edge types as one map, with counts | Graph explorer (later) |
| `3-graph-neighbourhood.png` | A node and its neighbours grouped by edge type; extra neighbours folded into bundles; a proposal | UC-03, graph explorer (later) |
| `4-graph-path.png` | The path between two things, with each step's source | UC-03 |
| `5-chains.png` | A chain shown as cards per step and as a joined table, with card fields chosen per type | UC-16, "Viewer: chains and cards" |
| `6-table.png` | A node type as rows, with linked columns and the source's column layout | UC-04 |
| `7-graph-overview.png` | The whole mosaic as shards, one per thing (experimental) | Graph explorer (later) |

## How to use them

- **What is binding** is, in this order: the needs in `docs/design.md`, then the brand book
  (section 6, "App") and `tokens.json`. Where an image disagrees with either, the image is
  wrong.
- **Layout, wording, controls and interactions are suggestions.** Choose differently when it
  serves the needs better; no PR has to justify departing from these images.
- **Colours and sizes in the images were drawn by hand.** Read them through the tokens: the
  viewer uses `var(--…)` and the type-style classes only, never values picked from a picture.
- **The data is illustrative.** Names come from the Netflix titles fixture; counts, row numbers
  and the proposal are invented, and bracketed values are placeholders.

The source canvas is a Claude Design artifact owned by the maintainer; these PNGs are its
exports from 7 November 2026.
