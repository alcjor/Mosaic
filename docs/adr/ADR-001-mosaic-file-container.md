# ADR-001: Mosaic file container

**Status:** Accepted, 2026-10-27 · **Deciders:** the maintainer

**Decision: a mosaic is one SQLite file.** Nodes, edges, names, evidence and link counts are plain tables; lexical search uses SQLite's built-in full-text index; vectors are binary columns searched by the mosaic kit itself. Bigger models query it with read-only SQL over documented views. A graph database may still run inside the mosaic builder, but never ships.

## Context

Part 1 fixes what a mosaic must be, and the container has to serve all of it:

- one file, offline, with no server (principle 10)
- readable from any language, and inside browsers through WebAssembly (quality goal 5, constraints)
- lexical search over names, aliases, summaries and snippets, and vector search by default
- answers in under 100 ms on a large generated system (quality goal 6)
- the same pieces and pattern give the same mosaic (quality goal 7)
- small, and a format stable enough to read the previous release's files
- a licence compatible with Apache-2.0, and a codebase one maintainer can hold

## Options considered

| Criterion | A: SQLite file | B: LadybugDB file | C: Parquet or Arrow files | D: Own binary format |
| --- | --- | --- | --- | --- |
| One file, no server | Yes | Yes, embedded | Several files, or one archive of them | Yes |
| WebAssembly | Official build, widely used | To verify for the fork | Through DuckDB or Arrow libraries, heavier | Write it ourselves |
| Any language | Bindings almost everywhere | Main languages only | Wide, through Arrow | Write each binding |
| Lexical search | Built in (full-text index) | Built in | Needs an extra engine | Write it |
| Vectors | Binary columns, scanned by the kit; extensions optional | Built-in index | Columns, scanned by a library | Write it |
| Graph queries | Indexed edge table; recursive queries for paths | Native, Cypher | Joins in a query engine | Write it |
| Byte-identical builds | Achievable with a fixed write order and SQLite version; to prove in a spike | Unknown | Achievable with fixed writer settings | Full control |
| Format stability | Very high, long-term stable file format | Young project, format may change | High | Ours to keep |
| Size | Small; full-text index is the largest part | Larger, columnar storage plus indexes | Small, compressed | Smallest |
| Licence | Public domain | MIT | Apache-2.0 | Apache-2.0 |
| Effort for one maintainer | Low | Medium, plus dependency risk | Medium | High |

## Trade-offs

- **SQLite gives up native graph queries** for reach, stability and size. At mosaic scale (thousands to tens of thousands of nodes), an indexed edge table answers neighbors in well under a millisecond, and a recursive query finds short paths; the six tools never need a general graph language.
- **LadybugDB is the best graph engine** of the four, but it is a young fork with an unproven browser build, and its file format may change; shipping it would tie every reader of every mosaic to it.
- **Parquet or Arrow** suit analytics, not lookups: search and point queries need a second engine, and one mosaic becomes several files.
- **An own format** wins on size and determinism, and loses on everything one maintainer cannot afford: bindings, tools, search and trust from other people.

## Consequences

- Easier: any language and the browser read mosaics with stock tools; people can open a mosaic with any SQLite browser; Datasette-style publishing works as is.
- Easier: bigger models get a query language they already know well, SQL, over read-only views.
- Harder: path queries beyond a few hops are slower than in a graph engine; the kit caps path length.
- Harder: byte-identical files need care (write order, page size, no timestamps, pinned SQLite version); spike S1 showed bytes differ across SQLite versions, so the mosaic's identity hash covers its logical content (canonical row order and encoding, Part 5 section 3.6) instead of its bytes.
- To revisit: if mosaics outgrow tens of thousands of nodes, or vector search by scanning gets slow, add an index extension or reconsider B.
