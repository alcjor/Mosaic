# ADR-004: Pattern language

**Status:** Accepted, 2026-10-27 · **Deciders:** the maintainer

**Decision: a pattern is one YAML file with four sections (pieces, types, edges and mosaics), plus an optional proposals file. No LinkML, no SQL, no code.** Defaults replace most of the rules a pattern would otherwise spell out, and anything that needs computation belongs in a tessera builder.

## Context

A pattern has to say which pieces to use, the types they become, how pieces link, how conflicts resolve, and which mosaics to build. A first design gave each concern its own file and language (LinkML types, YAML and SQL mappings, identity and link rule files, SQL checks): nine concepts and three languages. A pattern must instead:

- be readable and editable by a domain expert who is not a programmer
- be safe to build when it comes from someone else, and deterministic
- be validated before a build, with errors that name the line
- stay small enough that most patterns fit on one screen

## What the defaults replace

| Concern | How the simple pattern handles it |
| --- | --- |
| Types | Plain YAML types with a key and a description, in the pattern file. LinkML can come later as an export |
| Mappings | Each type lists the piece types it comes from and which fields fill it. Anything needing computation is done by the tessera builder |
| Identity | Default: same type and same key after normalisation is the same thing. Spelling variants arrive as aliases from pieces; fuzzy matches arrive as proposals from the pattern assistant (ADR-003) |
| Link rules | Part of each edge's definition: the mention role it comes from (ADR-003) |
| Conflict policy | The order of the pieces list: the first piece wins. Per-field overrides only if a real pattern needs them |
| Checks | The build report's built-in checks: unresolved names, conflicts, duplicate keys, broken edges, outdated proposals. Custom checks later |
| Proposals and decisions | One proposals file, written by the assistant or a person, with accept or reject per line |
| Targets | The mosaics section; by default one mosaic with everything |

The whole pattern for the plant fits on one screen; it is shown, as it validates, in Part 2 (Pattern schemas).

## Options considered

| Criterion | A: One YAML file with defaults | B: Separate files, LinkML, YAML and SQL | C: Python patterns |
| --- | --- | --- | --- |
| Concepts to learn | 4: pieces, types, edges, mosaics | 9 | A programming language |
| Languages | YAML | YAML, LinkML, SQL | Python |
| Complex mappings | Moved to tessera builders | In the pattern, through SQL | In the pattern |
| Safe and deterministic | Yes | Yes, with read-only SQL | No |
| Effort for one maintainer | Low | Medium | Low, but unsafe |

## Trade-offs

- **Complex mappings leave the pattern.** A source that needs real transformation gets a smarter tessera builder. That is the right place: one source's quirks should not leak into every pattern that uses it.
- **Conflict policy is coarse.** Piece order covers most cases; per-field overrides are added only when a real pattern needs them.
- **Custom checks wait.** The built-in ones cover the use cases of Part 1.
- **LinkML's validation is replaced** by a JSON Schema for `pattern.yaml`, checked by `mosaic check`.

## Consequences

- Easier: a pattern fits on one screen, is read like configuration, and is safe to build from anyone.
- Easier: the mosaic builder implements a few clear defaults instead of a rule engine.
- Harder: tessera builders must produce clean, well-shaped pieces; the reference builders need options for common cleanups.
- To revisit: per-field policy, custom checks and fuzzy identity rules, each only when a real pattern needs it.
