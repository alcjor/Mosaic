# MOSAIC

**MOSAIC — Reverse MBSE platform.** From scattered mission data to structured insight with AI. No rebuild, no re-entry.

MOSAIC turns the data a mission already has (the SRDB, flight procedures, operational user manuals, telemetry) into one navigable model: connected, analysable from notebooks, comparable across missions, and a recovered system model that supports the move to MBSE. Its visual identity borrows from Gaudí's *trencadís*: broken tiles, reassembled into something whole.

> **Corporate standards come first.** This system sits inside the company's blue palette and type rules. Every hex value here is a placeholder until the corporate blues are confirmed, and IBM Plex Sans stands in for the corporate typeface. When they are known, change `tokens.json` and the generator script together, and nothing else needs to change.

---

## 1. Name and messaging

### The name
- **MOSAIC**, always in capitals. Acronym: *Model Of Spacecraft Assembled from Information already Collected*. Spell it out once, in small text, never in a headline.
- **Reverse MBSE platform** is the category line. Write "Reverse MBSE" with that capitalisation, never "reverse-MBSE" or "rMBSE". Because "platform" can suggest something big and costly, always pair it with the retrofit promise (the tagline's "No rebuild, no re-entry").
- Lockup order is fixed: **MOSAIC** first, **Reverse MBSE platform** under or after it, the tagline last.

### Core lines (use verbatim)
| Line | Text | Where |
|---|---|---|
| Tagline | From scattered mission data to structured insight with AI. No rebuild, no re-entry. | Under the lockup, covers, email signatures. "No rebuild, no re-entry." may be highlighted in `saffron` on navy |
| Long description | An MBSE view of every mission, assembled with AI from the data we already have. | Body copy, introductions |
| Definition | Instead of building the mission from a model, we build the model from the mission's existing data. | The first time "Reverse MBSE" appears in any piece |
| Positioning | A step towards Teamcenter, Cameo and Polarion: it makes the structure already in our mission data visible, so existing missions aren't left out of the adoption. | Anywhere the MBSE and PLM tools being adopted come up |
| Trust | AI proposes, engineers approve. | Next to any mention of AI |

### Key messages, in priority order
1. **Retrofit, not rebuild.** It works on existing missions, at any stage of their life.
2. **No re-entry, no new licences.** Data stays where it is; its structure is recovered, not retyped. The stack is open source.
3. **AI-assisted, engineer-approved.** Structured data is linked by rules, exactly. AI only proposes the links the data doesn't contain, each with a confidence score, and an engineer accepts or rejects it.
4. **It supports the adoption of our MBSE and PLM tools:** existing missions aren't left behind, because their structure is recovered instead of rebuilt by hand.
5. **It builds on what exists:** relview, the SRDB adapter, the mission time-series platform (under study).
6. **Every phase is usable on its own:** connected operational manual → telemetry → cross-mission → recovered system model, with the AI layer alongside every phase.
7. **Value beyond our walls:** MOSAIC Tessera, the connected data pack, and stronger bids. Upside only: never counted in the ROI.

### Voice
- Plain, concrete and engineering-literate. Name real artefacts (SRDB, flight procedures, operational user manual, telemetry) instead of abstractions.
- Small, safe and practical. Lead headlines with *map, retrofit, assemble, existing, explore*. Keep *platform, ontology, digital thread, transformation* out of headlines; use them in body text where they are precise.
- Never say "AI builds the model" or "fully automated". Say "assembled **with** AI", "AI proposes".
- No invented numbers. A missing figure is a visible placeholder like **[HOURS SAVED]**.
- **Internal tools: complement, never compete.** MOSAIC reads what existing tools produce and connects it. Never describe it as replacing, improving on or fixing a tool a team already uses. Lead with what only cross-source links give (follow a parameter across flight procedures, documents and telemetry), not with single-source features such as browsing the SRDB or viewing a document.
- **MBSE and PLM tools being adopted (Teamcenter, Cameo, Polarion): support, don't position against.** MOSAIC helps existing missions join the adoption. Never call it a complement or an alternative, and never promise that its output can be imported into those tools; say it "makes the structure visible" and provides "a recovered system model".
- **No standards promises in outward copy.** Don't name XTCE, ECSS or SysML v2 in brand pieces; say "one formal schema, shared across missions" and "a recovered system model".
- **Lifecycle-neutral, operations vocabulary.** Say "existing missions, at any stage"; don't single out one phase or one team. Prefer operations terms (SRDB, flight procedures, operational user manual) over test-campaign ones.
- Write for international readers. Prefer common words over specialist ones: the four steps are **Shards → Pattern → Assisted assembly → The picture** (not "grout").

### The metaphor, when explaining
| Trencadís | MOSAIC |
|---|---|
| Shards | The data we already have, left where it is |
| Pattern | The formal schema: the plan of how the pieces relate |
| The artisan | The engineer who places and approves each piece |
| The assistant who sorts the shards | The AI that proposes where pieces fit |
| The picture | One navigable model of the mission |

Optional codename for the AI assistant: **Jujol**, after the craftsman who worked alongside Gaudí on the Park Güell trencadís.

---

## 2. Visual foundations

### Colour
- **Blue leads, glaze colours support.** The corporate blues carry the brand. Five secondary and accent colours are taken from the glazes of Park Güell's trencadís: turquoise, terracotta, saffron, olive and majolica red, plus a warm ceramic white. Each has one job, so colour always means something.
- **`brand-navy` is the identity colour.** It takes the big fields: header bands, hero grounds, the logo tile.
- **Proportions:** blues about 75% of any screen or page, secondary colours up to 20%, accents under 5%. Tints (`*-tint`) for areas; the strong shade for borders, icons and chart series; `*-text` for words.

| Colour | Role | Tokens |
|---|---|---|
| Cobalt blues | Brand, reference data, primary actions, info | `brand-navy`, `accent`, `data-reference`, `status-info` |
| Turquoise | Telemetry and time series | `turquoise`, `data-telemetry` |
| Terracotta | Documents, highlights | `terracotta`, `data-documents` |
| Saffron | AI proposals awaiting review, warnings | `saffron`, `ai-proposal`, `status-warning` |
| Olive | Success, approved | `olive`, `status-success` |
| Majolica red | Errors, rejected | `majolica`, `status-error` |
| Ceramic white | Warm background for marketing pieces | `ceramic` |

- **Use the semantic tokens** (`data-*`, `ai-proposal`, `status-*`) in diagrams and apps, not the raw colours, so meanings stay consistent.
- **Saffron means "proposed, not yet approved".** Use it for every AI suggestion, so "AI proposes, engineers approve" is visible without words. Once approved, an item takes its normal category colour.
- **Colour-blind safety (checked against deuteranopia):**
  - blue, turquoise, terracotta and saffron stay distinct, so they're safe as categories;
  - olive becomes nearly identical to terracotta and majolica, so olive and majolica are status-only and always carry an icon or label (check, cross).
- **Majolica red** is never decorative.
- **Ceramic white** is optional for marketing pieces; app screens stay on `surface`.
- **Approval:** the secondary colours go beyond the corporate blue palette; confirm with the corporate brand owner before external use.
- **Text pairings that pass 4.5:1:**
  - `ink` or `heading` on `surface` or `surface-tint`;
  - `accent` on white;
  - on navy, white, `#E6EEF8` or `shard-tcs`.
- **Shard colours carry meaning.** In data-driven art, each `shard-*` token is one subsystem. Never shuffle them for decoration in a piece that claims to show data.
- **Light and dark grounds:**
  - Light pieces (A4, documents) use white paper with navy accents.
  - Dark pieces (slides, covers, banners) use a navy ground of `ground-shard` tiles with `grout` gaps.

### Typography
- One family, set in the `sans` stack (IBM Plex Sans as stand-in; replace with the corporate face).
- **Hierarchy:** `wordmark` → `category` → `statement` → `section-label` (uppercase, accent) → `step-title` / `panel-title` → `body-*` → `caption`.
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
  - **Data-driven:** if a mosaic claims to show data, one shard = one real item, coloured by a `shard-*` token, with a caption that says so ("Each shard is one telemetry parameter …").
  - **Decorative:** no caption, and no implied meaning.
- **The hero subject** is order being created:
  - Grey, randomly tilted fragments on the left turn to follow the curve as they near concentric curved bands of tiles on the right.
  - The bands read as orbits or a planet's horizon, and as Gaudí's curved, undulating trencadís.
  - Loose fragments are grey (unstructured); each finished band carries one colour (structured). Colour arrives with order.
  - Pieces never overlap or crash together; settling is shown by alignment, not movement.
- **Text over shards:**
  - Only over the quiet `ground-shard` field, never over bright shards.
  - Keep a calm zone behind type: the left third of a banner, or a solid navy band.
- **Don't:**
  - gradients, glows, bevels, 3D tiles, drop shadows;
  - photographic textures;
  - shards in non-blue colours in brand artwork (glaze colours belong to data and status, not to the hero mosaic);
  - mosaics that look like pixel grids.

### Layout
- **A4 one-pager (794 × 1123 px):**
  - top to bottom: navy banner (≈264px), statement band, shard divider strip, two-column body, roadmap, footer;
  - side margins `margin-print` (48px);
  - nothing closer than `safe-edge` to a trimmed edge.
- **Slides (16:9):**
  - navy hero with the assembly mosaic (curved bands) on the right and the lockup on the left;
  - content slides on white, with a shard strip under the title band.
- **Grid:** two equal columns with a `space-6` gutter for text; four columns for roadmaps.

### Iconography
- **Shard badges (`ShardBadge`):** numbered irregular polygons, for steps and phases.
- **Shard bullets (`ShardBullet`):** list markers.
- **Check marks:** 2px stroke, round caps, in `accent`. No other icon set unless the corporate one is required.
- No emoji, no clip-art satellites, no stock icons.

---

## 3. Logo

### The mark: "The last shard"
A square tile of three shards with a fourth, lighter shard being slotted into its corner.
- **What it says:** the picture is mostly there already (the data we have), and one piece is being placed by hand. In other words, assisted assembly that an engineer approves.
- **Mark and imagery split the work:** the mark carries the idea; the imagery (the assembly mosaic of curved bands) carries the subject. Never put a satellite in the mark.
- **No letterforms:** the mark is deliberately not a monogram. Monograms read as generic and corporate, and only repeat the name.

| Asset | Use |
|---|---|
| `mosaic-lockup-light` | Default: mark + MOSAIC + Reverse MBSE on white |
| `mosaic-lockup-dark` | On `brand-navy` grounds |
| `mosaic-mark-light` | Mark alone on white or light grounds (transparent background) |
| `mosaic-mark-dark` | Mark alone on navy grounds (transparent background) |
| `mosaic-app-icon-512` / `-180` / `-32` | Solid navy square with the dark mark: app icons, favicons, avatars |

- **Clear space:** a quarter of the mark's width on every side, measured from the displaced shard.
- **Minimum size:**
  - mark: 16px on screen (use the app icon there), 8 mm in print;
  - lockup: 120px wide on screen, 35 mm in print.
- **Don't:**
  - close the gap or realign the displaced shard. The offset is the meaning;
  - recolour outside the palette, or make the displaced shard the same colour as the others;
  - stretch, rotate, or add effects;
  - re-typeset the wordmark in another face;
  - use the earlier circular medallion. It is retired because it doesn't read at small sizes.

### Sub-brand: MOSAIC Tessera

**MOSAIC Tessera — the connected data pack.** With every data pack, the customer receives an offline, read-only view of that pack’s own data, exported from MOSAIC: searchable, every link followable, nothing to install. A *tessera* is a single tile of a mosaic: the piece we hand over.

**The mark: “Joined”.** One tile in two colours, ours (`brand-navy`) and the customer’s (`tessera`), meeting along a clean, shard-like joint.
- **What it says:** one piece, made together; what we deliver and what the customer holds fit exactly.
- **It never shows a gap or a crack.** A split tile would read as broken; the joint is a line, not a break.
- **Turquoise is Tessera’s identity colour** (`tessera`, `tessera-bright` on navy). Inside apps and diagrams turquoise still means telemetry (`data-telemetry`), so the Tessera mark is never used as a data symbol.

| Asset | Use |
|---|---|
| `tessera-lockup-light` | Default: mark + MOSAIC Tessera + “The connected data pack” on white |
| `tessera-lockup-dark` | On `brand-navy` grounds |
| `tessera-mark-light` / `tessera-mark-dark` | Mark alone, transparent, for light and navy grounds |
| `tessera-app-icon-512` / `-180` / `-32` | Dark mark on a navy square: the icon of the delivered viewer |

**Naming and messaging**
- Always **MOSAIC Tessera** in full the first time; **Tessera** alone afterwards. Descriptor: “the connected data pack”.
- Say it is **scoped to the contract** and **tied to the document baseline**; **the documents stay the contractual deliverable**.
- Never promise live data, editing or integration with the customer’s tools: it is a read-only snapshot.
- In internal business cases, Tessera and stronger bids are **upside only**, never counted in the ROI.

**Don’t:** separate the two halves, add a gap or crack, swap the colours (ours is always on the left), or put the MOSAIC mark and the Tessera mark side by side without the wordmarks.

---

## 4. Assets and how to regenerate them

- **Logos:** see section 3; Tessera assets are regenerated with `generate_tessera.py`.
- **Imagery:**
  - `banner-assembly-glaze`: A4 header, the current hero (glaze colours);
  - `banner-assembly-blue`: the same in corporate blues only, where secondary colours aren't allowed;
  - `mosaic-hero-glaze` / `-blue`: 16:9 title slides with the lockup and tagline; `-clean` versions without text;
  - `flyer-strip`: the divider.
- **Regenerating:** the hero and banner come from `generate_hero.py` and the logo from `generate_logo.py`, both delivered with the asset bundles.
  - Swap the placeholder hexes for corporate values at the top of the scripts.
  - Re-upload the outputs here.

---

## 5. Components

Static HTML patterns. Copy their markup and bind colours to the tokens.

- **SectionLabel**: uppercase accent label opening every section.
- **Statement**: the definition line with an accent lead-in.
- **ShardBadge**: numbered shard for steps and roadmap phases.
- **ShardBullet**: shard-marked list.
- **StepRow**: badge + title + one-line description ("How it works").
- **CheckPanel**: the "Retrofit, not rebuild" panel.
- **RoadmapCard**: one phase of the roadmap.
- **ShardStrip**: the trencadís divider between header and body.
