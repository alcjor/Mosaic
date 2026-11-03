# MOSAIC

**MOSAIC — Embeddable data.** Many pieces in. One picture out.

Mosaic builds small, sealed knowledge graphs that travel with small AI models: the curated data a local agent reads to answer questions about one system, with a source for every answer. People browse the same file. Tessera builders turn each source into a tessera, a pattern says how the pieces fit, the mosaic builder seals the mosaics it names, and the mosaic kit answers questions from them, wherever it is embedded. The identity borrows from Gaudí's *trencadís*: broken pieces, worth little on their own, set into something whole.

> **Open source, with its own identity.** The blues and IBM Plex are Mosaic's own palette and type, no longer stand-ins for a corporate palette. To change a colour, change `tokens.json` and the generator scripts together (section 4).

---

## 1. Name and messaging

### The name
- **Mosaic** in running text. **MOSAIC**, in capitals, only as the wordmark: lockups, covers, title slides. Files and code are lowercase: `.mosaic`, `.tessera`, `pattern.yaml`, `proposals.yaml`.
- Acronym: *Model Of Systems Assembled from Information already Collected*. Spell it out once, in small text, never in a headline.
- **Embeddable data** is the category line; the long form is "embeddable data, built from anything". Call what people get *data* or a *built mosaic*.
- Lockup order is fixed: **MOSAIC**, then **Embeddable data**, then the tagline.
- **Other projects already use the name**, among them the UW Interactive Data Lab's Mosaic visualization framework and Databricks' Mosaic AI. The brand name stays Mosaic; the repository, package and command get a distinctive name, checked on GitHub, PyPI and npm before the first release. Until then write **[package name]**.

### Core lines (use verbatim)
| Line | Text | Where |
|---|---|---|
| Tagline | Many pieces in. One picture out. | Under the lockup, first line of the repository README, covers. "One picture out." may be set in `saffron` on navy |
| Category | Embeddable data, built from anything. | Repository description, package metadata, social cards |
| Long description | Mosaic builds small, sealed knowledge graphs that travel with small AI models: the curated data a local agent reads to answer questions about one system, with a source for every answer. | Introductions, the README's first paragraph |
| How it works | Tessera builders turn each source into a tessera, a pattern says how the pieces fit, the mosaic builder seals the mosaics it names, and the mosaic kit answers questions from them. | Straight after the long description |
| Definition | A built mosaic is one read-only SQLite file: every thing your sources mention, typed, linked and traced to where it came from. | The first time "built mosaic" appears in any piece |
| Evidence | Every value knows where it came from. | Feature lists, the docs home page |
| Trust | Machines propose, people decide. | Next to any mention of AI, matchers or linkers |
| Retrofit | No rebuild, no re-entry: inputs keep their own shape. | When existing data and tools come up |

### Key messages, in priority order
1. **Build a model from what you already have.** Tables, structured files, code and documents become tesserae as they are. A new kind of input needs only a new reader.
2. **Embed it anywhere.** A mosaic is one sealed SQLite file; the mosaic kit is one small read-only TypeScript library (SQLite in WASM) with six tools: find, get, neighbors, path, table, cite. Anything that embeds the kit can ask it questions: the Mosaic viewer, an editor, a documentation site, a notebook, an agent. Any SQLite tool can open the file too.
3. **Every value knows where it came from.** Each value, link and place points to the row it came from. Conflicts are settled when building and reported to whoever builds.
4. **Machines propose, people decide.** AI, matchers and linkers write proposals to `proposals.yaml`; the pattern author accepts or rejects each one, and only accepted ones enter.
5. **Reproducible by construction.** Nothing changes once frozen: a change is a new file with a new hash, so every build can be reproduced.
6. **Open to contributions.** The way in is to write a reader for a format you know.

### The six rules
Keep the wording and the order. In docs, mark a feature with the rule it relies on: a numbered `ShardBadge` and the rule's words ("4 · Every value has evidence").
1. Copy what fits, reference what doesn't.
2. Inputs keep their own shape.
3. Nothing changes once frozen.
4. Every value has evidence.
5. Conflicts are settled when building.
6. Machines propose, people decide.

### Voice
- Plain, concrete and developer-literate. Show a real case instead of an abstraction: the docs follow one, TEMP-3, a temperature sensor in a sensor list, control code, a manual and a time-series store.
- Lead headlines with what people do: *build, embed, freeze, resolve, query*. Keep *platform, ontology, digital thread, knowledge graph* out of headlines; use them in body text where they are precise.
- Never say "AI builds the model" or "fully automated". Say "machines propose, people decide".
- **Built or planned, never blurred.** Anything not in a release is "planned" or "later", never in the present tense.
- **Name a standard only where Mosaic really uses it:** SQLite (the one file format for tesserae and mosaics), YAML and JSON Schema (the pattern). Never claim conformance or certification.
- No invented numbers. A missing figure is a visible placeholder like **[BUILD TIME]**.
- Write for international readers: common words over specialist ones, and the same name for a thing every time. The four steps are **Tesserae → Pattern → Build → Embed**.

### The metaphor, when explaining
| Mosaic craft | Mosaic |
|---|---|
| Tessera: one piece of glass or stone | One input, frozen as it was read: a `.tessera` file |
| Cartoon: the full-size drawing laid out before setting | The pattern: which pieces, and how they fit |
| Mosaicist: the person who sets the pieces | The builder, the only writer |
| The finished mosaic | The built mosaic: one read-only file |
| Emblema: a fine panel made ready in a tray, then set into a larger floor | Embedded: a built mosaic set into the viewer, an editor, a site, a notebook or an agent, through the mosaic kit |
| Trencadís: Gaudí's mosaics of broken tiles | The idea as a whole: pieces worth little alone, joined into something whole |

Optional codename for the AI that proposes links: **Jujol**, after the craftsman who worked alongside Gaudí on the Park Güell trencadís.

---

## 2. Visual foundations

### Colour
- **Blue leads, glaze colours support.** Mosaic's blues carry the brand. Five secondary and accent colours come from the glazes of Park Güell's trencadís: turquoise, terracotta, saffron, olive and majolica red, plus a warm ceramic white. Each has one job, so colour always means something.
- **`brand-navy` is the identity colour.** It takes the big fields: header bands, hero grounds, the logo tile.
- **Proportions:** blues about 75% of any screen or page, secondary colours up to 20%, accents under 5%. Tints (`*-tint`) for areas; the strong shade for borders, icons and chart series; `*-text` for words.

| Colour | Role | Tokens |
|---|---|---|
| Cobalt blues | Brand, the pattern, tables, structured files and code, primary actions, info | `brand-navy`, `accent`, `data-pattern`, `data-reference`, `status-info` |
| Turquoise | Time series and other external data, kept outside and reached by key | `turquoise`, `data-external` |
| Terracotta | Documents, highlights | `terracotta`, `data-documents` |
| Saffron | Proposals awaiting a decision, warnings | `saffron`, `ai-proposal`, `status-warning` |
| Olive | Success, accepted | `olive`, `status-success` |
| Majolica red | Errors, rejected | `majolica`, `status-error` |
| Ceramic white | Warm background for marketing pieces | `ceramic` |

- **Use the semantic tokens** (`data-*`, `ai-proposal`, `status-*`) in diagrams and apps, not the raw colours, so meanings stay consistent. The `data-*` categories follow the kinds of input in the spec.
- **Saffron means "proposed, not yet decided".** Use it for every proposal from AI, a matcher or a linker, so "machines propose, people decide" is visible without words. Once accepted, an item takes its normal category colour.
- **Colour-blind safety (checked against deuteranopia):**
  - blue, turquoise, terracotta and saffron stay distinct, so they're safe as categories;
  - olive becomes nearly identical to terracotta and majolica, so olive and majolica are status-only and always carry an icon or label (check, cross).
- **Majolica red** is never decorative.
- **Ceramic white** is optional for marketing pieces; app screens stay on `surface`.
- **Text pairings that pass 4.5:1:**
  - `ink` or `heading` on `surface` or `surface-tint`;
  - `accent` on white;
  - on navy, white, `#E6EEF8` or `shard-4`.
- **Shard colours carry meaning.** In data-driven art each `shard-*` token is one category, numbered 1 to 7; a pattern or view file says which category each one shows. Never shuffle them for decoration in a piece that claims to show data.
- **Light and dark grounds:**
  - Light pieces (A4, documents, the README on a light theme) use white paper with navy accents.
  - Dark pieces (slides, covers, banners) use a navy ground of `ground-shard` tiles with `grout` gaps.

### Typography
- Two families, both IBM Plex:
  - `sans` (IBM Plex Sans) for everything people read;
  - `mono` (IBM Plex Mono) for code, commands, file names and identifiers: `find("TEMP_3")`, `.mosaic`, `TEMP-3`.
- **Hierarchy:** `wordmark` → `category` → `statement` → `section-label` (uppercase, accent) → `step-title` / `panel-title` → `body-*` → `caption`; `code` wherever code appears.
- **The wordmark is drawn, not typed.** The lockups carry it as outlines (DejaVu Sans Bold); never retype it next to the mark.
- **Print:** body never below 12px (9pt). Captions in `ink-muted`.
- **Headlines:** short, balanced, at most 6 words.

### The shard motif (the core of the identity)
- **Shapes:** irregular polygons, like broken ceramic, with uneven gaps. They are never squares, hexagons or rounded tiles (`radius-none`).
- **Construction:** a Voronoi tessellation; each cell inset by about half the grout width, one corner sometimes chipped, vertices slightly jittered.
- **Gaps between shards** (the `grout` tokens; a design term only, never in user-facing copy):
  - `grout` on dark grounds;
  - white on light grounds (the divider strip);
  - width `grout-print` in print art, `grout-hero` in 1920-wide art.
- **Data-driven or decorative, never ambiguous:**
  - **Data-driven:** if a mosaic claims to show data, one shard = one real thing, coloured by a `shard-*` or `data-*` token, with a caption that says so ("Each shard is one thing in the built mosaic …").
  - **Decorative:** no caption, and no implied meaning.
- **The hero subject is a build:**
  - Grey, randomly tilted fragments on the left (the inputs) turn to follow the curve as they near concentric curved bands of tiles on the right (the built mosaic).
  - The bands also read as Gaudí's curved, undulating trencadís.
  - Loose fragments are grey; each finished band carries one colour. Colour arrives with order: many pieces in, one picture out.
  - Pieces never overlap or crash together; settling is shown by alignment, not movement.
- **Text over shards:**
  - Only over the quiet `ground-shard` field, never over bright shards.
  - Keep a calm zone behind type: the left 40% of a hero, the left third of a banner, or a solid navy band.
- **Don't:**
  - gradients, glows, bevels, 3D tiles, drop shadows;
  - photographic textures;
  - shards in non-blue colours in brand artwork (glaze colours belong to data and status, not to the hero mosaic);
  - mosaics that look like pixel grids.

### Layout
- **Repository README:**
  1. the lockup in a `<picture>`: `mosaic-lockup-dark` for `prefers-color-scheme: dark`, `mosaic-lockup-light` otherwise;
  2. the tagline as the first line of text, then at most one row of status badges (build, release, licence);
  3. the build strip, switched the same way, then the long description and the "How it works" line;
  4. quick start and the six rules.
- **Docs site:** a navy header band with the dark lockup; each state icon heads the docs about that state (Tesserae, Patterns, Building, The mosaic, Embedding).
- **Social preview (1280 × 640):** a clean hero cropped to 2:1, with the dark lockup in its calm zone.
- **A4 one-pager (794 × 1123 px):**
  - top to bottom: navy banner (≈264px), statement band, shard divider strip, two-column body, footer;
  - side margins `margin-print` (48px);
  - nothing closer than `safe-edge` to a trimmed edge.
- **Slides (16:9):**
  - navy hero with the assembly mosaic (curved bands) on the right and the lockup on the left;
  - content slides on white, with a shard strip under the title band.
- **Grid:** two equal columns with a `space-6` gutter for text; four or five columns for steps.

### Iconography
- **State icons:** the five states of a build (section 3), for files, docs, diagrams and the README. They name things; they are never decoration or bullets.
- **Shard badges (`ShardBadge`):** numbered irregular polygons, for steps and the six rules.
- **Shard bullets (`ShardBullet`):** list markers.
- **Check marks:** 2px stroke, round caps, in `accent`.
- No emoji, no clip-art, no stock icon sets. In apps, a small set of functional line icons (section 6) is the one exception.

---

## 3. Logo

### The mark: "The last shard"
A square tile of three shards with a fourth, lighter shard being set into its corner.
- **What it says:** a build in progress. Most of the picture is already there (what you have); the last piece is being set, on purpose. It is the middle state of the family below.
- **Mark and imagery split the work:** the mark carries the idea; the imagery (the assembly mosaic of curved bands) carries the subject.
- **No letterforms:** the mark is deliberately not a monogram. Monograms read as generic and only repeat the name.

| Asset | Use |
|---|---|
| `mosaic-lockup-light` | Default: mark + MOSAIC + Embeddable data on white |
| `mosaic-lockup-dark` | On `brand-navy` grounds |
| `mosaic-mark-light` | Mark alone on white or light grounds (transparent background) |
| `mosaic-mark-dark` | Mark alone on navy grounds (transparent background) |
| `mosaic-app-icon-512` / `-180` / `-32` | Solid navy square with the dark mark: favicons, avatars, the organisation picture |

- **Clear space:** a quarter of the mark's width on every side, measured from the displaced shard.
- **Minimum size:**
  - mark: 16px on screen (use the app icon there), 8 mm in print;
  - lockup: 120px wide on screen, 35 mm in print.
- **Don't:**
  - close the gap or realign the displaced shard. The offset is the meaning;
  - recolour outside the `mark-*` tokens, or give the displaced shard the same colour as the others;
  - stretch, rotate, or add effects;
  - re-typeset the wordmark in another face;
  - use the earlier circular medallion. It is retired because it doesn't read at small sizes.

### One mark, five states
The mark's grid, seams and colours, drawn at five moments of a build. Each state names one thing in Mosaic, so files, docs and diagrams can show what they are about. They read left to right in build order:

| State | Asset | Drawing | Stands for |
|---|---|---|---|
| Tessera | `mosaic-icon-tessera` | The last piece, alone | One frozen input: a `.tessera` file, and the readers that make it |
| Pattern | `mosaic-icon-recipe` (file name kept from the earlier "recipe"; it is the pattern icon) | The mark's seams inside a dashed square: the plan, nothing set yet | A pattern: `pattern.yaml` with pieces, types, edges and mosaics, and `proposals.yaml` |
| Build | `mosaic-mark` | The brand mark: the last piece being set | The project itself, the builder, the build command |
| Built mosaic | `mosaic-icon-built` | All four pieces in place | A `.mosaic` file and its releases |
| Embedded | `mosaic-icon-embedded` | The built mosaic inside a rounded frame | The mosaic kit, and anything that embeds it: the viewer, a single-file HTML export, an agent |

- `mosaic-build-strip-light` / `-dark`: the five in order, joined by chevrons, for the README and the docs home page. In HTML use the `BuildStrip` component, which adds the labels.
- **Colours** are the mark's (`mark-base`, `mark-mid`, `mark-piece`, `mark-line`): light values on white grounds, dark values on navy. Each icon comes as `-light` and `-dark`, SVG and 512px PNG.
- **The last piece is always `mark-piece`, always the same shape.** It is the tessera: the piece in the tessera icon is the piece being set in the mark.
- **The frame of Embedded is the only rounded shape in the identity:** it is the host, not the mosaic.
- **Minimum size:** 16px; the pattern icon 24px, because its dashes close up below that.
- **Don't:** invent further states, fill the pattern icon, colour the pieces by meaning, use a state icon as a bullet or decoration, or use the build mark for a finished file (the offset means "still being built").

---

## 4. Assets and how to regenerate them

- **Logos:** lockups, marks and app icons, from `generate_logo.py` (with `marks.py`, which holds the mark's geometry).
- **Icons:** the four state icons and the build strip, from `generate_icons.py`, on the same geometry.
- **Imagery:**
  - `mosaic-hero-glaze` / `-blue`: 16:9 title images with the lockup and tagline; `-clean` versions without text;
  - `banner-assembly-glaze`: A4 header (3:1); `banner-assembly-blue`: the same in blues only;
  - `flyer-strip`: the divider.
- **Regenerating:**
  - the art comes from `generate_hero.py`; `letter_hero.py` sets the type on a clean hero;
  - colours sit at the top of each script and in `tokens.json`: change them together;
  - re-upload the outputs here.

---

## 5. Components

Static HTML patterns. Copy their markup and bind colours to the tokens.

- **SectionLabel**: uppercase accent label opening every section.
- **Statement**: the definition line with an accent lead-in.
- **ShardBadge**: numbered shard for steps and the six rules.
- **ShardBullet**: shard-marked list.
- **StepRow**: badge + title + one-line description ("How it works": Tesserae → Pattern → Build → Embed).
- **CheckPanel**: the "What stays true" panel.
- **ShardStrip**: the trencadís divider between header and body.
- **BuildStrip**: the five state icons in build order, labelled.

---

## 6. App

> The viewer mock-up image lives in the design system (Imagery → `mosaic-viewer-mock.png`).

The Mosaic viewer (Svelte, running the kit in the page), the single-file HTML export and the building GUI share one app style. It is a working tool: calm, dense, blue. The brand shows in the header band and the mark, not in the content area.

### Shell
- **Header band:** 48px, `slab`, with the dark mark, the mosaic's name in `mono` (`netflix.mosaic`) and its knowledge hash, short, in `shard-4`. One search field in the middle. Nothing else on navy.
- **Body:** `surface`. Three columns at 1280px and up: results (320px), the entity card (flexible), and a context column (320px) for neighbours, sources and proposals. Below 960px the side columns become tabs.
- **Status bar** (optional, 28px, `surface-tint`): trust level, build date, row counts, in `caption`.
- **Exported HTML** looks the same; a `caption` in the header says "Read-only export".

### Components
- **SearchField:** 40px, `border` outline in `ink-muted` (3:1), `radius-md`. Placeholder in `ink-muted`. A mode switch at its right: *Semantic* / *Text*, from the view file's `search` setting.
- **ResultRow:** label in `heading` (15px, 600), type and id in `mono` `caption`, and a tier tag on the right: **Exact**, **Text** or **Similar** (vector). Tiers group the list with a `section-label` per group; exact first.
- **TypeChip:** type name with a 10px shard (irregular polygon, `radius-none`) in the type's `shard-*` colour. Colour by type only when the pattern assigns one.
- **EntityCard:** the card template from the spec: label (`panel-title` at 22px), type chip, summary, then a properties table. Each value carries a **CitationChip**.
- **PropertyTable:** two columns, key in `ink-muted`, value in `ink`; identifiers and numbers in `mono`. Row hairlines in `border`; no zebra striping.
- **CitationChip:** `mono` 12px, tessera name and row (`titles.csv:412`) on `surface-tint`; hover shows the source row; click opens the source text. Documents use `terracotta-tint` / `terracotta-text`, external refs `turquoise-tint` / `turquoise-text`.
- **NeighborList:** grouped by edge name (`section-label`), each item a compact ResultRow without the tier tag, with a count per group ("directed by · 2").
- **PathView:** the steps of a `path` result as a horizontal chain of chips joined by edge labels in `caption`.
- **TableView:** results of `table`: sticky header on `surface-tint`, `mono` for ids, sortable columns with a 2px `accent` underline on the sorted one.
- **ProposalRow:** saffron is the only "pending" signal. `saffron-tint` ground, a 12px `saffron` shard, the claim, `by` (who proposed it) in `caption`, and two buttons: **Accept** (secondary, with check) and **Reject** (ghost, with cross). Accepted: `olive-tint` and a check, labelled "Accepted by …"; rejected: `majolica-tint`, a cross, labelled "Rejected by …". Never colour alone.
- **BuildReport panel:** one row per check: icon + label + count, in `status-*` colours with their tints; strict-only findings are tagged "strict".
- **ColumnMapper** (building GUI): one row per CSV column: column name in `mono`, a select (*Property* / *Linked things* / *Ignore*), an optional split character, a type conversion, and a preview of the first three values.
- **Buttons:** 32px high, `radius-md`, 14px 600. *Primary*: `accent` fill, white text (one per view). *Secondary*: `surface`, `accent` 1px border and text. *Ghost*: text only, `ink`.
- **Empty, loading, error:** empty states are one `body-screen` line and the tessera icon, in `ink-muted`; loading uses a thin 2px `accent` bar under the header, never spinners over content; errors use a `majolica-tint` banner with icon.

### States
- **Hover:** rows and chips on `surface-tint`; buttons darken one step (`shard-3` for primary).
- **Focus:** a 2px `accent` ring, 2px offset, on every control (3:1 on both themes). Never removed.
- **Selected:** the row gets `surface-tint` and a 3px `accent` bar at its left edge, and its label turns `accent`.
- **Disabled:** 40% opacity, no hover, `not-allowed` cursor; disabled buttons keep their label.
- **Proposed / accepted / rejected:** as ProposalRow, everywhere the item appears (results, neighbours, tables).

### App icons
16px line icons, 1.5px stroke, round caps, in `ink-muted` (or `accent` when active): search, close, check, cross, chevron, external link, copy, filter, sort. Drawn in-house on the same stroke as the check marks. State icons may head panels (the tessera icon on sources, the pattern icon on proposals), never as buttons.

### Theme
The app follows the system's light or dark setting: *Paper* by default, *Navy ground* in dark mode, using the same tokens. Charts and diagrams in the app use `data-*` colours, not `shard-*`, unless one shard means one thing.
