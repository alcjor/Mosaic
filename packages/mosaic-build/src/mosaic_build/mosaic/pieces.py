"""Step 1 of a build: check the pattern and proposals, resolve and open the pieces.

Specification 0.1, section 7.1 step 1 and sections 5.1 and 5.6. The pattern and proposals are
checked by :func:`mosaic_format.pattern.check_pattern`; any violation stops the build with
``invalid_input``. Each piece is resolved by its hash among the available files: the files
the caller gives and each piece's own ``path``, relative to the pattern file (section 5.1).
A piece that matches no file or more than one, or whose ``kind`` in the pattern is not the
file's, stops the build with ``piece_mismatch``. Every available file is opened by the reading
rules (section 3.8); one that they refuse stops the build with ``invalid_input``, since it may
be the piece.

The builder may also be given the previous mosaic of the target (section 7). It is used only
to flag outdated proposals (section 5.5): step 1 opens it by the reading rules, a refusal stops
the build with ``invalid_input``, and only its knowledge hash is kept. When it is the mosaic
the proposals were built from (``built_from`` is a prefix of its knowledge hash), it is the
``built_from`` mosaic of section 5.6, and the ids the proposals name must exist in it.
"""

import hashlib
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from mosaic_format.pattern import check_pattern
from mosaic_format.reader import FileRefusedError, Limits, SealedFile
from mosaic_format.reader import open as open_sealed
from mosaic_format.yaml_core import load

from mosaic_build.mosaic.errors import BuildError

READ_ALL = Limits(seconds=None, rows=None)
"""The builder reads every row of its pieces, so their queries are not bounded."""


@dataclass(frozen=True)
class Piece:
    """One piece of the pattern, resolved and open: its name, position in ``pieces`` and file."""

    name: str
    rank: int
    file: SealedFile
    path: str | None = None
    """The piece's ``path`` in the pattern, if it gives one."""

    @property
    def kind(self) -> str:
        return self.file.kind

    @property
    def knowledge_hash(self) -> str:
        return self.file.knowledge_hash


@dataclass(frozen=True)
class Inputs:
    """What step 1 hands on: the checked pattern and proposals, and the open pieces in order."""

    pattern_path: Path
    pattern: Mapping[str, Any]
    proposals: Mapping[str, Any] | None
    pieces: Sequence[Piece]
    proposals_path: Path | None = None
    proposals_hash: str | None = None
    """SHA-256 of the proposals file's bytes, as checked: its ``source`` row (section 3.2)."""
    previous_hash: str | None = None
    """Knowledge hash of the previous mosaic of the target, when it is given (section 7)."""

    def piece(self, name: str) -> Piece:
        for p in self.pieces:
            if p.name == name:
                return p
        raise KeyError(name)

    def close(self) -> None:
        for p in self.pieces:
            p.file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _violations(report_text: Iterable[str], what: str) -> BuildError:
    listed = "; ".join(report_text)
    return BuildError("invalid_input", f"{what}: {listed}")


def _entries(pattern: Mapping[str, Any]) -> list[tuple[str, str, str | None, str | None]]:
    """Each piece as (name, hash prefix, kind, path), in pattern order."""
    entries: list[tuple[str, str, str | None, str | None]] = []
    for entry in pattern["pieces"]:
        if isinstance(entry, str):
            name, prefix = entry.split("@", 1)
            entries.append((name, prefix, None, None))
        else:
            entries.append((entry["name"], entry["hash"], entry.get("kind"), entry.get("path")))
    return entries


def piece_paths(pattern_path: Path, pattern: Mapping[str, Any]) -> list[Path]:
    """The files that the pieces' own ``path`` names, relative to the pattern file, that exist.

    ``pattern`` is the pattern's data, valid against its schema (section 5.1).
    """
    return [
        pattern_path.parent / path
        for _, _, _, path in _entries(pattern)
        if path is not None and (pattern_path.parent / path).is_file()
    ]


def _open_all(paths: Sequence[Path]) -> list[SealedFile]:
    """Open every available file once, by the reading rules; a refusal stops the build."""
    opened: list[SealedFile] = []
    seen: set[Path] = set()
    try:
        for path in paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                opened.append(open_sealed(path, limits=READ_ALL))
            except FileRefusedError as e:
                raise BuildError(
                    "invalid_input", f"available file refused by the reading rules: {e}"
                ) from None
    except BaseException:
        for f in opened:
            f.close()
        raise
    return opened


def _previous_hash(previous: Path) -> str:
    """The knowledge hash of the previous mosaic, opened by the reading rules (section 3.8)."""
    try:
        with open_sealed(previous, limits=READ_ALL) as f:
            return f.knowledge_hash
    except FileRefusedError as e:
        raise BuildError(
            "invalid_input", f"previous mosaic refused by the reading rules: {e}"
        ) from None


def check(
    pattern: str | os.PathLike[str],
    *,
    pieces: Iterable[str | os.PathLike[str]] = (),
    proposals: str | os.PathLike[str] | None = None,
    previous: str | os.PathLike[str] | None = None,
) -> Inputs:
    """Step 1: check ``pattern`` and ``proposals``, and resolve and open every piece.

    ``pieces`` are the available files besides each piece's own ``path``; ``previous`` is the
    previous mosaic of the target, if any. Raises :class:`BuildError` when the build must stop,
    and :class:`FileNotFoundError` when a given file does not exist. The caller closes the
    returned :class:`Inputs`.
    """
    pattern_path = Path(pattern)
    given = [Path(p) for p in pieces]
    proposals_path = None if proposals is None else Path(proposals)
    previous_path = None if previous is None else Path(previous)
    optional = [p for p in (proposals_path, previous_path) if p is not None]
    for path in (pattern_path, *given, *optional):
        if not path.is_file():
            raise FileNotFoundError(f"{path}: no such file")

    report = check_pattern(pattern_path, proposals=proposals_path)
    if not report.ok:
        raise _violations((str(v) for v in report.violations), f"{pattern_path}: pattern check")
    data = load(pattern_path.read_bytes().decode("utf-8"), str(pattern_path)).data
    entries = _entries(data)
    proposals_bytes = None if proposals_path is None else proposals_path.read_bytes()
    proposals_data = (
        None
        if proposals_bytes is None
        else load(proposals_bytes.decode("utf-8"), str(proposals_path)).data
    )
    previous_hash = None if previous_path is None else _previous_hash(previous_path)
    built_from = None
    if (
        previous_path is not None
        and proposals_data is not None
        and str(previous_hash).startswith(proposals_data["built_from"])
    ):
        built_from = previous_path

    available = [*given, *piece_paths(pattern_path, data)]

    files = _open_all(available)
    chosen: dict[Path, SealedFile] = {}
    resolved: list[Piece] = []
    try:
        for rank, (name, prefix, kind, path) in enumerate(entries):
            matches = [f for f in files if f.knowledge_hash.startswith(prefix)]
            if not matches:
                raise BuildError(
                    "piece_mismatch", f"piece {name}@{prefix} matches no available file"
                )
            if len(matches) > 1:
                listed = ", ".join(sorted(str(f.path) for f in matches))
                raise BuildError(
                    "piece_mismatch",
                    f"piece {name}@{prefix} matches {len(matches)} files: {listed}",
                )
            (match,) = matches
            if kind is not None and match.kind != kind:
                raise BuildError(
                    "piece_mismatch",
                    f"piece {name}@{prefix} is a {kind} in the pattern, but {match.path} is a "
                    f"{match.kind}",
                )
            chosen[match.path] = match
            resolved.append(Piece(name=name, rank=rank, file=match, path=path))

        report = check_pattern(
            pattern_path,
            proposals=proposals_path,
            pieces=[p.file.path for p in resolved],
            built_from=built_from,
        )
        if not report.ok:
            raise _violations(
                (str(v) for v in report.violations), f"{pattern_path}: pattern check with pieces"
            )
    except BaseException:
        for f in files:
            f.close()
        raise
    for f in files:
        if f.path not in chosen:
            f.close()
    return Inputs(
        pattern_path,
        data,
        proposals_data,
        tuple(resolved),
        proposals_path=proposals_path,
        proposals_hash=None
        if proposals_bytes is None
        else hashlib.sha256(proposals_bytes).hexdigest(),
        previous_hash=previous_hash,
    )
