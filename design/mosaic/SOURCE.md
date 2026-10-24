# Source

Copied from the MOSAIC design system artifact
<https://claude.ai/artifact/LwLFNqDsgwtSAvM7r8aans>, version `1792834084-c3ea`,
on 2026-10-25. That artifact is the source of truth; this folder is a read-only copy for
the repo, so builds and agents work offline.

| Here | In the design system |
|---|---|
| `README.md` | Brand guidelines: name, messaging, voice, colour, type, shard motif, logo, Tessera |
| `tokens.json` | Colour, type, spacing and radius tokens |
| `logos/` | MOSAIC and MOSAIC Tessera marks, lockups and app icons |
| `imagery/flyer-strip.png` | The ShardStrip divider. The hero and banner images are not copied (marketing only) |
| `components/` | Component notes and static previews (they expect the tokens as CSS variables) |

Rules:

- Never edit these files by hand. To update, copy the new version from the artifact,
  update the version above, and note it in `docs/decisions.md`.
- The blues are placeholders until the corporate values are confirmed; changing
  `tokens.json` must be enough to rebrand the viewer.
- How the system applies to the viewer: `design/viewer-guidelines.md`.
