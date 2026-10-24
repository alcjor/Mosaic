# Mosaic — Connected manual

Read-only exploration of data that already exists, joined across sources and linked to the
text that mentions it. First system pack: the connected user manual for on-board software
(SRDB, SW ICD, SW user manual, SCSW code, FOPs).

Status: specification. Nothing is implemented yet.

## Start here

1. `docs/specs/00-overview.md`: scope, glossary, decisions, open questions
2. `prototype/index.html`: clickable sketch of the ops view with a slice of the demo mission
3. `docs/engineering.md`: repo layout, quality gates, milestones

## Once built

```
uv sync --all-packages
uv run mosaic demo        # generate the mock mission, build, serve, open the browser
```
