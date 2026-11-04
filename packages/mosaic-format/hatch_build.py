"""Ship the five normative files of ``spec/`` inside the package as ``mosaic_format/spec/``.

From the repository, both targets copy ``<repo>/spec``: the sdist into
``src/mosaic_format/spec`` (so a wheel built from the sdist finds it as package data) and
the wheel into ``mosaic_format/spec``. From an unpacked sdist the files are already in place.
An editable install ships nothing: ``mosaic_format.schema`` falls back to ``<repo>/spec``.
"""

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import (  # ty: ignore[unresolved-import]
    BuildHookInterface,
)

NORMATIVE_FILES = (
    "format.sql",
    "pattern.schema.json",
    "proposals.schema.json",
    "build-report.schema.json",
    "answers.schema.json",
)
PACKAGED = Path("src", "mosaic_format", "spec")


class SpecHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version == "editable":
            return  # an editable install reads the repository's spec/ directly
        root = Path(self.root)
        if all((root / PACKAGED / name).is_file() for name in NORMATIVE_FILES):
            return  # building from an sdist: the files are package data already
        spec = root.parent.parent / "spec"
        missing = [name for name in NORMATIVE_FILES if not (spec / name).is_file()]
        if missing:
            raise FileNotFoundError(f"normative files missing from {spec}: {', '.join(missing)}")
        dest = PACKAGED if self.target_name == "sdist" else Path("mosaic_format", "spec")
        for name in NORMATIVE_FILES:
            build_data["force_include"][str(spec / name)] = (dest / name).as_posix()
