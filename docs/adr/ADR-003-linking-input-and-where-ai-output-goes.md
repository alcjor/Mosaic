# ADR-003: Linking input, and where AI output goes

**Status:** Accepted, 2026-10-27 · **Deciders:** the maintainer

**Decision: tessera builders record mentions, and the pattern's link rules turn them into edges; AI summaries come from per-source tessera builders, and AI proposals across pieces live in the pattern, written by a pattern assistant.**

## Context

Two questions from Part 1, both about what a tessera carries:

- **Linking:** edges across pieces, such as a procedure step that sends a command or a manual section that describes a sensor, cannot be made by a tessera builder, which sees only its own source. The pattern makes them, so it needs something to match: the places where one source names a thing from another.
- **Derived tesserae:** AI proposals (these two nodes are the same; this step reads that sensor) and summaries are made from other tesserae, not from a source. The format says a tessera comes from one source, and mosaics already compose pieces.

## Part 1: what a tessera carries for linking

| Option | How it works | Verdict |
| --- | --- | --- |
| A: Mentions | The tessera builder records each place a name appears: the text it saw, its location in the source, the node that contains it, and a role hint from the source's structure (a call argument, a table column, a heading) | Chosen |
| B: Full text | Tesserae carry their text; the pattern searches it | Rejected: big, and it moves parsing into the pattern |
| C: Builders resolve links | Each builder looks up other sources | Rejected: builders see one source by design |

A mention is small: `{in: Step:FOP-PWR-001/2, text: "PWRC0101", at: line 14, role: send_tc.arg0}`. A link rule then reads like: mentions with role `send_tc.arg0` that match a `Command` key become `sends` edges from their containing node. A mention that looks like an id but matches nothing, or matches more than one thing, goes to the build report. Mentions are an optional but fully specified part of the tessera format (Part 5, section 4.2).

## Part 2: AI proposals and summaries

**The mosaic builder never runs AI, so AI output enters as input, and each kind goes where it belongs.** Tesserae always have one source, which is never a mosaic; mosaics are read only by the mosaic builder and the mosaic kit.

| AI output | Where it goes | Why |
| --- | --- | --- |
| Facts and summaries about things one source describes | That source's tessera, written by its tessera builder with an optional AI step | One source, as the format says; the manual's tessera summarises TEMP-3 from the manual section about it |
| Proposals across pieces: identities (TEMP\_3 is TEMP-3) and links (this step reads that sensor) | A proposals file in the pattern, written by a pattern assistant | They are identity and link decisions, which already live in the pattern |

Rejected: tesserae built from several tesserae, and tesserae built from a mosaic. Both add a second way to compose pieces, which mosaics already provide, and make tessera builders consume what only the mosaic builder should handle.

## The pattern assistant

An AI tool outside the core that helps the user write the pattern:

1. The mosaic builder builds a mosaic as usual.
2. The assistant reads the mosaic and the build report's unresolved names, and writes proposals into the pattern's proposals file, each with a confidence and the evidence it relied on.
3. The user reviews them like code (accept, reject, edit); accepted proposals become extracted facts sourced to that decision, and open or rejected ones have no effect.
4. The mosaic builder builds again from the pieces plus the pattern.

This is the same loop as a user fixing a conflict, so there is no cycle: the assistant edits the pattern, and an ordinary build follows. Each proposals file records which build it was made from, and the build report flags proposals made from an outdated build.

## Consequences

- Easier: one format and one import path for every piece; AI output is reviewable, pinned and replaceable.
- Easier: link rules stay in the pattern, so one tessera serves many patterns.
- Harder: AI tesserae are not reproducible from their inputs. The rule "same source and settings give the same file" becomes: rule-based builders are deterministic; AI builders record their model and settings, and their output is fixed by its hash once pinned.
- To revisit: if mentions grow large for long documents, store them per section with offsets only (spike S12 found this unnecessary at PX4 scale).
