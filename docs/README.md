# Docs

- [`design.md`](design.md) — *Mosaic — Design and specification*. Parts 1–5 in reading order.
  Nine diagrams are not in the repository yet and are marked in place.
- [`spec-0.1.md`](spec-0.1.md) — Part 5 on its own: the normative Specification 0.1.
- [`adr/`](adr/) — ADR-001 to ADR-007, one file each, copied from Part 3.

These files are the source of truth for the design. They change through pull requests that the
maintainer reviews (the paths are CODEOWNERS-protected). Agents read them and never edit them on
their own.

`spec-0.1.md` and the ADR files are copies of parts of `design.md`: edit `design.md` and the
copy in the same pull request. `tests/test_docs.py` fails when they drift apart.
