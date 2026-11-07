"""A cache for the slow tests' fixture builds, keyed by everything a build depends on.

Principle 5 says the same pieces and pattern give the same knowledge hash, so the slow tests build
a fixture twice from clean directories and compare. Those two builds are only worth repeating when
something they depend on changed. ``twice`` builds twice when the inputs are new and records both
results; the same inputs reuse the two recorded builds. The key is a SHA-256 of every input file
(directories are walked, bytecode caches skipped) and of the Python version and platform.

The cache lives outside the repository, in ``$MOSAIC_FIXTURE_CACHE`` (default
``~/.cache/mosaic/fixtures``), so the builder, the verifier and the reviewer of one environment
share it. ``MOSAIC_FRESH_BUILDS=1`` always builds twice and refreshes the entry. Callers get
copies of the cached files, never the cached files themselves.
"""

import hashlib
import json
import os
import platform
import shutil
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

KEEP = 2
"""Entries kept per fixture: the newest ones, so switching between two branches stays cheap."""

SKIPPED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache"}


@dataclass(frozen=True)
class Builds:
    key: str
    records: list[dict[str, object]]
    """What each build returned, first then second (JSON values)."""
    files: list[Path]
    """The file each build produced, first then second: copies the caller may change."""
    reused: bool


def cache_root() -> Path:
    configured = os.environ.get("MOSAIC_FIXTURE_CACHE")
    return Path(configured) if configured else Path.home() / ".cache" / "mosaic" / "fixtures"


def _files(path: Path) -> list[tuple[str, Path]]:
    if path.is_file():
        return [(path.name, path)]
    if not path.is_dir():
        raise FileNotFoundError(f"build cache input not found: {path}")
    found = []
    for directory, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
        for name in names:
            if name.endswith(".pyc"):
                continue
            full = Path(directory) / name
            found.append((full.relative_to(path).as_posix(), full))
    return sorted(found, key=lambda item: item[0].encode("utf-8"))


def inputs_key(inputs: Iterable[Path]) -> str:
    """SHA-256 over each input's files, as (name length, name, size, content), in order."""
    digest = hashlib.sha256()
    digest.update(f"{sys.version}|{platform.system()}|{platform.machine()}".encode())
    for index, path in enumerate(inputs):
        digest.update(f"input {index}\n".encode())
        for name, file in _files(path):
            data = file.read_bytes()
            encoded = name.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big") + encoded)
            digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def _prune(fixture: Path) -> None:
    entries = []
    for entry in fixture.iterdir():
        record = entry / "record.json"
        if entry.is_dir() and record.is_file():
            created = json.loads(record.read_text(encoding="utf-8")).get("created_ns", 0)
            entries.append((created, entry))
    for _, entry in sorted(entries, reverse=True)[KEEP:]:
        shutil.rmtree(entry, ignore_errors=True)


def twice(
    name: str,
    inputs: Sequence[Path],
    build: Callable[[Path], tuple[dict[str, object], Path]],
    work: Path,
) -> Builds:
    """Build ``name`` twice in ``work/first`` and ``work/second``, or reuse a recorded pair.

    ``build(directory)`` builds into ``directory`` (which does not exist yet) and returns a JSON
    record of the build and the file it produced.
    """
    key = inputs_key(inputs)
    fixture = cache_root() / name
    entry = fixture / key
    fresh = os.environ.get("MOSAIC_FRESH_BUILDS", "") not in ("", "0")
    record_file = entry / "record.json"
    if not fresh and record_file.is_file():
        record = json.loads(record_file.read_text(encoding="utf-8"))
        files = []
        for label, cached_name in zip(("first", "second"), record["files"], strict=True):
            (work / label).mkdir(parents=True, exist_ok=True)
            copy = work / label / cached_name
            shutil.copyfile(entry / f"{label}-{cached_name}", copy)
            files.append(copy)
        return Builds(key=key, records=record["records"], files=files, reused=True)

    first_record, first_file = build(work / "first")
    second_record, second_file = build(work / "second")
    fixture.mkdir(parents=True, exist_ok=True)
    staging = fixture / f".{key}.{os.getpid()}.{time.time_ns()}"
    staging.mkdir()
    for label, file in (("first", first_file), ("second", second_file)):
        shutil.copyfile(file, staging / f"{label}-{file.name}")
    (staging / "record.json").write_text(
        json.dumps(
            {
                "key": key,
                "inputs": [str(p) for p in inputs],
                "created_ns": time.time_ns(),
                "records": [first_record, second_record],
                "files": [first_file.name, second_file.name],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    shutil.rmtree(entry, ignore_errors=True)
    try:
        staging.replace(entry)
    except OSError:  # another session stored the same key meanwhile
        shutil.rmtree(staging, ignore_errors=True)
    _prune(fixture)
    return Builds(
        key=key,
        records=[first_record, second_record],
        files=[first_file, second_file],
        reused=False,
    )
