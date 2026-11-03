# Mosaic

**Small, sealed knowledge for small models.** Mosaic builds small knowledge graphs —
one read-only SQLite file each — that a local AI model reads in a few tool calls,
with a source for every fact. People browse the same file.

*Many pieces in. One picture out.* Tessera builders turn each source (a table, a
database, code, a document) into a **tessera**; the mosaic builder assembles
tesserae by a **pattern** and seals the **mosaics** it names; agents and people
read them through the **mosaic kit**.

> Status: milestone M0 (skeleton). Nothing builds a mosaic yet.

## Repository

```
spec/          the five normative files of Specification 0.1 (format.sql + 4 JSON Schemas)
docs/          design.md (vision, data model, ADRs, corpus, spec), spec-0.1.md, adr/
packages/      Python (uv workspace): mosaic-format (schema, hashes, checker), mosaic-build (builders, CLI)
kit/           TypeScript kit (SQLite WebAssembly, ONNX Runtime Web)
viewer/        Svelte viewer and single-file export
design/        tokens, brand book and component guidelines (enforced in the viewer)
conformance/   fixtures (pinned by hash), invalid files and patterns, tool cases
views/         example view files
```

## Develop

Requires [uv](https://docs.astral.sh/uv/) and [Bun](https://bun.sh) 1.4+.

```
uv sync && bun install
./scripts/check-fast.sh
```

## Licence

Apache-2.0.
