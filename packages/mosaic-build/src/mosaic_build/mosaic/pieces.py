"""Step 1 of a build: check the pattern and proposals, resolve and open the pieces.

Specification 0.1, section 7.1 step 1 and sections 5.1 and 5.6. The pattern and proposals are
checked by :func:`mosaic_format.pattern.check_pattern`; any violation stops the build with
``invalid_input``. Each piece is resolved by its hash among the available files: the files
the caller gives and each piece's own ``path``, relative to the pattern file (section 5.1).
A piece that matches no file or more than one, or whose ``kind`` in the pattern is not the
file's, stops the build with ``piece_mismatch``. Every available file is opened by the reading
rules (section 3.8); one that they refuse stops the build with ``invalid_input``, since it may
be the piece.
"""

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


def check(
    pattern: str | os.PathLike[str],
    *,
    pieces: Iterable[str | os.PathLike[str]] = (),
    proposals: str | os.PathLike[str] | None = None,
) -> Inputs:
    """Step 1: check ``pattern`` and ``proposals``, and resolve and open every piece.

    ``pieces`` are the available files besides each piece's own ``path``. Raises
    :class:`BuildError` when the build must stop, and :class:`FileNotFoundError` when a given
    file does not exist. The caller closes the returned :class:`Inputs`.
    """
    pattern_path = Path(pattern)
    given = [Path(p) for p in pieces]
    for path in (pattern_path, *given, *(() if proposals is None else (Path(proposals),))):
        if not path.is_file():
            raise FileNotFoundError(f"{path}: no such file")

    report = check_pattern(pattern_path, proposals=proposals)
    if not report.ok:
        raise _violations((str(v) for v in report.violations), f"{pattern_path}: pattern check")
    data = load(pattern_path.read_bytes().decode("utf-8"), str(pattern_path)).data
    entries = _entries(data)

    available = list(given)
    for _, _, _, path in entries:
        if path is not None and (pattern_path.parent / path).is_file():
            available.append(pattern_path.parent / path)

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
            pattern_path, proposals=proposals, pieces=[p.file.path for p in resolved]
        )
        if not report.ok:
            raise _violations(
                (str(v) for v in report.violations), f"{pattern_path}: pattern check with pieces"
            )
        proposals_data = (
            None
            if proposals is None
            else load(Path(proposals).read_bytes().decode("utf-8"), str(proposals)).data
        )
    except BaseException:
        for f in files:
            f.close()
        raise
    for f in files:
        if f.path not in chosen:
            f.close()
    return Inputs(pattern_path, data, proposals_data, tuple(resolved))
