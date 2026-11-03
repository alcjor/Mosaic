# Conformance suite

Versioned with the specification (docs/spec-0.1.md, section 11). Both the Python
builders and the TypeScript kit are tested against the cases here; this is where
the two languages meet.

| Directory | Holds | Status |
| --- | --- | --- |
| `fixtures/` | `manifest.json` of fixture sources (pinned by hash, downloaded, never committed), and per fixture: its pattern, view file and **expected** hashes and build report | Manifest only; licences pending |
| `invalid/files/` | One invalid tessera or mosaic per invariant of section 3.9, each naming the invariant it breaks | M1 |
| `invalid/patterns/` | One invalid pattern or proposals file per rule of sections 5 and 5.6 | M1 |
| `tools/` | Kit tool cases on the Chinook mosaic with expected answers, valid against `spec/answers.schema.json` | M3 |

**Expected values are the contract.** Files named `expected*` and the manifest are
owned by the maintainer (see `.github/CODEOWNERS`). An agent never edits them to
make a test pass; if an expected value looks wrong, it opens an issue labelled
`needs-decision`.
