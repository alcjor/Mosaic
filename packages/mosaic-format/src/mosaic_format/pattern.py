"""Check a pattern and its proposals: the schemas and the rules of sections 5.1 and 5.6.

``check_pattern`` reports every violation it can see from what it is given, in file and line
order. Two kinds of rule need more than the YAML files (decisions on #10):

- the piece rules need the candidate piece files, which the caller chooses (section 5.1:
  "which files are available is up to the tool that reads the pattern");
- the existence of proposal ids needs the ``built_from`` mosaic, and is skipped without it.

A rule that is not run is listed in :attr:`Report.skipped`, never passed silently. The
cross-checks of a file run only when that file is valid against its schema.
"""

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError, best_match
from jsonschema.protocols import Validator

from mosaic_format import schema
from mosaic_format.reader import FileRefusedError, SealedFile
from mosaic_format.reader import open as open_sealed
from mosaic_format.yaml_core import Document, YamlError, load

RULES: Mapping[str, tuple[str, str]] = {
    "yaml": ("5", "the file is read as YAML 1.2 core schema"),
    "duplicate-key": ("5", "a reader MUST reject duplicate keys"),
    "schema": ("5", "the file is valid against pattern.schema.json or proposals.schema.json"),
    "piece-unmatched": ("5.1", "a piece's hash matches no available file"),
    "piece-ambiguous": ("5.1", "a piece's hash matches more than one available file"),
    "piece-refused": ("3.8", "an available piece file breaks the reading rules"),
    "unique-name": ("5.6", "names are unique within each section"),
    "own-output": ("5.6", "no piece has the name of a target of the same pattern"),
    "from-piece": ("5.6", "every `from` names a listed piece"),
    "from-type": ("5.6", "every `from` names a node type that piece declares"),
    "map-piece": ("5.6", "every `map` entry names a listed piece"),
    "map-type": ("5.6", "every `map` entry names an edge type that piece declares"),
    "edge-type": ("5.6", "edge `from` and `to` name declared types"),
    "target-type": ("5.6", "target `types` name declared types"),
    "proposal-node-type": ("5.6", "a proposal's node ids have a node type declared in the pattern"),
    "proposal-edge": ("5.6", "an edge proposal's `type` is an edge declared in `edges`"),
    "proposal-edge-ends": ("5.6", "an edge proposal's ids have the types of that edge's ends"),
    "proposal-node-missing": ("5.6", "a proposal's node ids exist in the built_from mosaic"),
}
"""Every rule the checker reports, by name: the section that states it, and what it says."""

PIECE_RULES = ("piece-unmatched", "piece-ambiguous", "piece-refused", "from-type", "map-type")
"""The rules that need the candidate piece files."""

type _Where = tuple[str | int, ...]


@dataclass(frozen=True, order=True)
class Violation:
    """One broken rule: the file, the line (1-based) and the place in the document."""

    file: str
    line: int | None
    where: str
    rule: str
    message: str

    def __str__(self) -> str:
        at = self.file if self.line is None else f"{self.file}:{self.line}"
        place = f" {self.where}:" if self.where else ""
        return f"{at}:{place} {self.message} [{self.rule}, section {RULES[self.rule][0]}]"


@dataclass(frozen=True)
class Report:
    """What :func:`check_pattern` found, and the rules it could not run."""

    violations: tuple[Violation, ...]
    skipped: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class _Piece:
    """A sealed file offered as a piece, by its knowledge hash and declared types."""

    path: Path
    knowledge_hash: str
    node_types: frozenset[str]
    edge_types: frozenset[str]


class _File:
    """One YAML file being checked, collecting its violations."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = str(path)
        self.doc: Document | None = None
        self.violations: list[Violation] = []

    def add(self, where: _Where, rule: str, message: str, line: int | None = None) -> None:
        if line is None and self.doc is not None:
            line = self.doc.line(where)
        place = "/".join(str(part) for part in where)
        self.violations.append(Violation(self.name, line, place, rule, message))

    def read(self, schema_name: str) -> Any:
        """Load and validate the file; return its data, or None when it broke a rule."""
        try:
            text = self.path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as e:
            self.add((), "yaml", f"not UTF-8 text (byte {e.start})")
            return None
        try:
            self.doc = load(text, self.name)
        except YamlError as e:
            self.add((), e.rule, e.message, e.line)
            return None
        errors = sorted(_validator(schema_name).iter_errors(self.doc.data), key=_error_order)
        for error in errors:
            shown = _deepest(error)
            self.add(tuple(error.absolute_path), "schema", _short(shown.message))
        return None if errors else self.doc.data


@cache
def _validator(name: str) -> Validator:
    return Draft202012Validator(schema.json_schema(name))


def _deepest(error: ValidationError) -> ValidationError:
    """The most telling cause of an error: of a ``oneOf``, the branch of the value's own type."""
    if not error.context:
        return error
    same_type = [e for e in error.context if e.validator != "type"]
    return best_match(same_type or error.context) or error


def _error_order(error: ValidationError) -> tuple[str, str]:
    return ("/".join(str(p) for p in error.absolute_path), error.message)


def _short(message: str, limit: int = 300) -> str:
    return message if len(message) <= limit else message[: limit - 1] + "…"


def _split(reference: str) -> tuple[str, str]:
    """``<piece>.<Type>`` → (piece, Type); a type name never holds a ``.``."""
    piece, _, name = reference.rpartition(".")
    return piece, name


def _pieces(candidates: Iterable[str | os.PathLike[str]]) -> tuple[list[_Piece], list[str]]:
    """Open each candidate once; return the readable pieces and the refusals."""
    pieces: list[_Piece] = []
    refusals: list[str] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path = Path(candidate)
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            sealed = open_sealed(path)
        except FileRefusedError as e:
            refusals.append(str(e))
            continue
        with sealed:
            rows = sealed.query("SELECT name, kind FROM type")
            nodes = frozenset(str(n) for n, kind in rows if kind == "node")
            edges = frozenset(str(n) for n, kind in rows if kind == "edge")
            pieces.append(_Piece(path, sealed.knowledge_hash, nodes, edges))
    return pieces, refusals


def _check_pattern(
    f: _File, pattern: Mapping[str, Any], candidates: Sequence[_Piece] | None
) -> None:
    """Sections 5.1 and 5.6 on a pattern that is valid against its schema."""
    listed: dict[str, str] = {}  # piece name -> hash prefix, first entry of each name
    for i, entry in enumerate(pattern["pieces"]):
        name, prefix = (
            entry.split("@", 1) if isinstance(entry, str) else (entry["name"], entry["hash"])
        )
        if name in listed:
            f.add(("pieces", i), "unique-name", f"piece {name!r} is listed more than once")
        else:
            listed[name] = prefix
        if name in pattern.get("mosaics", {}):
            f.add(
                ("pieces", i),
                "own-output",
                f"piece {name!r} has the name of a target of this pattern; rename the piece",
            )
        if candidates is not None:
            matches = sorted(str(p.path) for p in candidates if p.knowledge_hash.startswith(prefix))
            if not matches:
                f.add(
                    ("pieces", i),
                    "piece-unmatched",
                    f"piece {name}@{prefix} matches no available file",
                )
            elif len(matches) > 1:
                f.add(
                    ("pieces", i),
                    "piece-ambiguous",
                    f"piece {name}@{prefix} matches {len(matches)} files: {', '.join(matches)}",
                )

    found: dict[str, _Piece] = {}
    if candidates is not None:
        for name, prefix in listed.items():
            matches = [p for p in candidates if p.knowledge_hash.startswith(prefix)]
            if len(matches) == 1:
                found[name] = matches[0]

    types = pattern["types"]
    for type_name, definition in types.items():
        for reference in definition["from"]:
            where = ("types", type_name, "from", reference)
            piece, piece_type = _split(reference)
            if piece not in listed:
                f.add(
                    where,
                    "from-piece",
                    f"{reference!r} names {piece!r}, which is not a listed piece",
                )
            elif piece in found and piece_type not in found[piece].node_types:
                f.add(
                    where,
                    "from-type",
                    f"{reference!r}: piece {piece!r} declares no node type {piece_type!r}",
                )

    for edge_name, definition in pattern.get("edges", {}).items():
        for end in ("from", "to"):
            if definition[end] not in types:
                f.add(
                    ("edges", edge_name, end),
                    "edge-type",
                    f"edge {edge_name!r}: {end} type {definition[end]!r} is not declared in types",
                )
        for i, reference in enumerate(definition.get("map", [])):
            where = ("edges", edge_name, "map", i)
            piece, piece_edge = _split(reference)
            if piece not in listed:
                f.add(
                    where,
                    "map-piece",
                    f"{reference!r} names {piece!r}, which is not a listed piece",
                )
            elif piece in found and piece_edge not in found[piece].edge_types:
                f.add(
                    where,
                    "map-type",
                    f"{reference!r}: piece {piece!r} declares no edge type {piece_edge!r}",
                )

    for target, definition in pattern.get("mosaics", {}).items():
        in_scope = definition.get("types", "all")
        if in_scope == "all":
            continue
        for i, type_name in enumerate(in_scope):
            if type_name not in types:
                f.add(
                    ("mosaics", target, "types", i),
                    "target-type",
                    f"target {target!r}: type {type_name!r} is not declared in types",
                )


def _node_type(node_id: str) -> str:
    return node_id.split(":", 1)[0]


def _check_proposals(
    f: _File, pattern: Mapping[str, Any], proposals: Mapping[str, Any], built: SealedFile | None
) -> None:
    """Section 5.6 on proposals that are valid against their schema, for a valid pattern."""
    types = pattern["types"]
    edges = pattern.get("edges", {})
    for i, proposal in enumerate(proposals["proposals"]):
        ends = ("node",) if proposal["kind"] == "identity" else ("from", "to")
        declared = {}
        for end in ends:
            node_id = proposal[end]
            declared[end] = _node_type(node_id) in types
            if not declared[end]:
                f.add(
                    ("proposals", i, end),
                    "proposal-node-type",
                    f"proposal {proposal['id']!r}: {node_id!r} has no node type declared in "
                    f"the pattern",
                )
            if built is not None and not built.query("SELECT 1 FROM node WHERE id = ?", (node_id,)):
                f.add(
                    ("proposals", i, end),
                    "proposal-node-missing",
                    f"proposal {proposal['id']!r}: {node_id!r} is not a node of the mosaic "
                    f"{built.knowledge_hash[:12]} it was built from",
                )
        if proposal["kind"] != "edge":
            continue
        edge = edges.get(proposal["type"])
        if edge is None:
            f.add(
                ("proposals", i, "type"),
                "proposal-edge",
                f"proposal {proposal['id']!r}: edge {proposal['type']!r} is not declared in edges",
            )
            continue
        for end in ("from", "to"):
            if declared[end] and _node_type(proposal[end]) != edge[end]:
                f.add(
                    ("proposals", i, end),
                    "proposal-edge-ends",
                    f"proposal {proposal['id']!r}: {proposal[end]!r} is not a {edge[end]}, the "
                    f"{end} type of edge {proposal['type']!r}",
                )


def check_pattern(
    pattern: str | os.PathLike[str],
    *,
    proposals: str | os.PathLike[str] | None = None,
    pieces: Iterable[str | os.PathLike[str]] | None = None,
    built_from: str | os.PathLike[str] | None = None,
) -> Report:
    """Check ``pattern`` and, if given, ``proposals`` by section 5 of the specification.

    ``pieces`` are the available piece files (section 5.1); when it is None, the piece rules
    are skipped. ``built_from`` is the mosaic the proposals were made from; when it is None,
    the existence of proposal ids is not checked. Raises :class:`FileNotFoundError` for a
    missing file and :class:`ValueError` when ``built_from`` is not the mosaic the proposals
    name.
    """
    pieces = None if pieces is None else list(pieces)
    for path in (pattern, proposals, built_from, *(pieces or ())):
        if path is not None and not Path(path).is_file():
            raise FileNotFoundError(f"{path}: no such file")
    if built_from is not None and proposals is None:
        raise ValueError(f"{built_from}: built_from is only used to check proposals; none given")

    skipped: list[str] = []
    candidates: list[_Piece] | None = None
    pattern_file = _File(Path(pattern))
    if pieces is None:
        skipped += PIECE_RULES
    else:
        candidates, refusals = _pieces(pieces)
        for refusal in refusals:
            pattern_file.add((), "piece-refused", refusal)
    pattern_data = pattern_file.read("pattern")
    if pattern_data is not None:
        _check_pattern(pattern_file, pattern_data, candidates)
    files = [pattern_file]

    if proposals is not None:
        proposals_file = _File(Path(proposals))
        proposals_data = proposals_file.read("proposals")
        files.append(proposals_file)
        if built_from is None:
            skipped.append("proposal-node-missing")
        if pattern_data is not None and proposals_data is not None:
            if built_from is None:
                _check_proposals(proposals_file, pattern_data, proposals_data, None)
            else:
                with _built_from(Path(built_from), proposals_data["built_from"]) as built:
                    _check_proposals(proposals_file, pattern_data, proposals_data, built)

    violations = [v for f in files for v in sorted(f.violations, key=_order)]
    return Report(tuple(violations), tuple(sorted(set(skipped), key=list(RULES).index)))


def _order(v: Violation) -> tuple[int, str, str, str]:
    return (v.line or 0, v.where, v.rule, v.message)


def _built_from(path: Path, named: str) -> SealedFile:
    sealed = open_sealed(path)
    if sealed.kind != "mosaic" or not sealed.knowledge_hash.startswith(named):
        what = sealed.kind if sealed.kind != "mosaic" else f"mosaic {sealed.knowledge_hash}"
        sealed.close()
        raise ValueError(
            f"{path}: is the {what}, not the mosaic {named} the proposals were built_from"
        )
    return sealed
