# Invalid patterns and proposals

One case per rule of sections 5, 5.1 and 5.6 of the specification (section 11). Each
directory is named after the one rule it breaks; a checker must reject it naming that rule,
and no other.

A case holds:

- `pattern.yaml`: the pattern;
- `proposals.yaml`, for the proposals rules: the proposals, checked against that pattern;
- `files.json`, for the rules that need sealed files: a description of them. `pieces` are the
  available piece files (section 5.1); without that key the checker is given none, and the
  piece rules do not run. `built_from` is the mosaic the proposals were made from. Each
  description is `{"kind", "types": {name: "node" | [from, to]}, "nodes": [id, ...]}`; the
  harness seals it with one source and one evidence row per node.

A piece is named by its knowledge hash, which section 3.6 defines from the content, so
`{{hash:<file name>}}` and `{{hash:built_from}}` in the YAML files stand for the full
knowledge hash of the sealed file. `tests/cases.py` seals the files and fills them in.

| Rule | Section | Broken by |
| --- | --- | --- |
| `yaml` | 5 | A flow sequence that is never closed |
| `duplicate-key` | 5 | A node type declared twice |
| `schema` | 5 | A piece without a hash |
| `piece-unmatched` | 5.1 | A piece whose hash matches no available file |
| `piece-ambiguous` | 5.1 | A piece whose hash matches two available files |
| `unique-name` | 5.6 | Two pieces with the same name |
| `own-output` | 5.6 | A piece with the name of a target |
| `from-piece` | 5.6 | A `from` naming a piece that is not listed |
| `from-type` | 5.6 | A `from` naming a node type the piece does not declare |
| `map-piece` | 5.6 | A `map` entry naming a piece that is not listed |
| `map-type` | 5.6 | A `map` entry naming an edge type the piece does not declare |
| `edge-type` | 5.6 | An edge ending at an undeclared type |
| `target-type` | 5.6 | A target listing an undeclared type |
| `proposal-node-type` | 5.6 | An identity proposal for a node of an undeclared type |
| `proposal-edge` | 5.6 | An edge proposal for an undeclared edge |
| `proposal-edge-ends` | 5.6 | An edge proposal whose `to` has the wrong type |
| `proposal-node-missing` | 5.6 | An edge proposal to a node the `built_from` mosaic does not have |
