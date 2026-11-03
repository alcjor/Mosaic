# ADR-002: Node identity

**Status:** Accepted, 2026-10-27 · **Deciders:** the maintainer

**Decision: a node's id is its type plus its canonical key, readable, such as `Sensor:TEMP-3`.** The pattern names the key property for each type; the mosaic builder normalises it. A key that changes in its source is a new id; any piece still using the old name is a stale reference, reported in the build report for the user to fix. SQLite row numbers are used for joins inside the file and never shown.

## Context

Tessera ids are only unique within one tessera. After the pattern merges nodes from several pieces, each thing needs one id that:

- agents cite in answers and pass from one tool call to the next
- stays the same when the mosaic is rebuilt from the same or changed pieces, so citations and comparisons between builds hold (UC-15)
- survives import into another pattern, so a shared mosaic's ids still mean something there
- is deterministic, since the mosaic builder must give the same mosaic for the same input

## Where the type and the key come from

Both come from the pattern, not from the tesserae. Each tessera arrives in its builder's own vocabulary (`Row`, `Define`, `Section`); the pattern's types section declares the canonical types and the key property of each, and its `from` mappings say how each piece fills them (full syntax in ADR-004 and Part 2):

```yaml
types:
  Sensor:
    key: tag
    from:
      sensorlist.Row: {tag: Tag}
      code.Define:    {tag: name, strip: PARAM_}
```

Normalisation, declared per type, cleans the value. When pieces spell a key differently (TEMP\_3 in the code, TEMP-3 in the list), normalisation or an accepted identity proposal makes them one node, and piece order picks the authoritative piece; its spelling becomes the canonical key and the others become aliases. The node is then `Sensor:TEMP-3`.

## Options considered

| Criterion | A: Type plus canonical key | B: Hash of type and key | C: Ids assigned in a registry | D: Ids from the first piece |
| --- | --- | --- | --- | --- |
| Example | `Sensor:TEMP-3` | `n_7f3a9c21` | `n_000412` | `sensorlist#row17` |
| Readable by people and small models | Yes, carries meaning | No | No | Partly |
| Stable across rebuilds | Yes, while the key holds | Yes, while the key holds | Yes, even across renames | No: changes when piece order changes |
| Survives a rename | New key, new id; stale references reported | Same as A | Yes | No |
| Deterministic without extra state | Yes | Yes | No: the registry is state the user must commit | Yes, but fragile |
| Length in tokens | Short to medium | Short, but meaningless | Short | Medium |

## Trade-offs

- **Readable ids help small models.** `Sensor:TEMP-3` tells the model what the thing is before any call, and an answer citing it is checkable by a person. Opaque ids cost a `get` call to mean anything.
- **Key-based ids depend on keys staying put.** Most engineering keys (tags, mnemonics, part numbers) are stable for years. When one changes, every piece should change with it; a piece that still uses the old key is out of date, and the build report says so instead of hiding it.
- **A registry survives every rename** but adds state that must be updated and committed on each build, which breaks "pieces and pattern in, mosaic out".

## Rules

- The pattern declares one key property per type; keys are unique per type, and a duplicate is a build-report conflict.
- Normalisation is declared per type in the pattern (for example trim and keep case); the original spelling stays as an alias.
- Edges are identified by type, from id and to id, plus an optional qualifier when two edges of the same type join the same pair.
- Renames are not declared anywhere. A changed key gives a new id; references to the old key in other pieces become unresolved names in the build report, with the likely new key as a hint. Citations made against an earlier mosaic stay valid for that mosaic, which is sealed.
- An imported mosaic's ids are treated like source keys: the importing pattern maps them, and keeps them as aliases so references to the shared mosaic's ids resolve.
- A type with no natural key gets a key from its piece's key and position; the build report lists these as weak ids.

## Consequences

- Easier: answers are readable, citations hold across rebuilds while keys hold, stale references surface in the build report, and comparing two builds is a join on ids; a rename shows there as a hint, detected from matching properties.
- Harder: the pattern author must choose good keys; types without natural keys get weaker ids.
- To revisit: if weak ids turn out common in real sources, add an optional id registry for those types only.
