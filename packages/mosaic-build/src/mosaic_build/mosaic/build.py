"""A whole build, steps 1 to 8, and step 8: seal (Specification 0.1, sections 3.3, 7, 7.1).

Step 8 writes the selected content with the sealed writer, which ranks every row in canonical
order (section 3.6), derives ``link_count`` and ``search``, computes the hashes and runs
``ANALYZE`` and ``VACUUM``. The header names the target, the SHA-256 of the pattern file's bytes
as ``pattern_hash``, the target's ``settings`` (section 3.3) and ``mosaic-build/<version>`` as
its ``producer`` (decision Q6 on #16).

When the sealed file is larger than the target's budget, the file is removed and the build
fails with ``over_budget`` (decision Q4 on #16).

Until M2 (#20), a target with ``vectors: true`` is built without vectors: ``vector_hash`` and
``embed_model`` are NULL, and the build returns the message ``vectors skipped, not yet
implemented`` for the CLI to print; the build report gets nothing (decision Q5 on #16).
"""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from mosaic_format.file import SIDECARS
from mosaic_format.writer import Content, Header, seal

from mosaic_build import __version__
from mosaic_build.mosaic.derive import declare
from mosaic_build.mosaic.errors import BuildError
from mosaic_build.mosaic.link import apply_identities, link
from mosaic_build.mosaic.merge import Assembly, merge
from mosaic_build.mosaic.pieces import check
from mosaic_build.mosaic.select import select
from mosaic_build.mosaic.target import target as find_target

PRODUCER = f"mosaic-build/{__version__}"
"""The header's ``producer`` of every mosaic this builder writes (section 3.3)."""

VECTORS_SKIPPED = "vectors skipped, not yet implemented"
"""What a build of a target with ``vectors: true`` says until vectors are built (#20)."""


@dataclass(frozen=True)
class Built:
    """A sealed mosaic and what its build report needs (section 7.2)."""

    path: Path
    target: str
    knowledge_hash: str
    vector_hash: str | None
    file_size: int
    pattern_hash: str
    settings: str
    assembly: Assembly
    """The selected content: nodes, edges, conflicts, mentions and proposals of the target."""
    messages: tuple[str, ...] = ()
    """What the CLI prints beside the report, such as skipped vectors."""


def _remove(path: Path) -> None:
    for leftover in [path, *(path.with_name(path.name + s) for s in SIDECARS)]:
        leftover.unlink(missing_ok=True)


def build(
    pattern: str | os.PathLike[str],
    target: str,
    out: str | os.PathLike[str],
    *,
    pieces: list[str | os.PathLike[str]] | tuple[str | os.PathLike[str], ...] = (),
    proposals: str | os.PathLike[str] | None = None,
    previous: str | os.PathLike[str] | None = None,
) -> Built:
    """Build ``target`` of ``pattern`` into a new mosaic at ``out`` (section 7.1, steps 1-8).

    ``pieces`` are the available files besides each piece's ``path``; ``proposals`` and
    ``previous`` (the previous mosaic of the target) are optional. Raises :class:`BuildError`
    when the build fails, leaving no file at ``out``.
    """
    pattern_path = Path(pattern)
    out_path = Path(out)
    with check(pattern_path, pieces=pieces, proposals=proposals, previous=previous) as inputs:
        t = find_target(inputs.pattern, target)
        a = merge(inputs)
        apply_identities(inputs, a)
        link(inputs, a)
        select(inputs, a, t)
        types = declare(inputs, a, t)
        pattern_hash = hashlib.sha256(pattern_path.read_bytes()).hexdigest()
        settings = t.settings()
        content = Content(
            header=Header(
                kind="mosaic",
                producer=PRODUCER,
                settings=settings,
                pattern_hash=pattern_hash,
                target=t.name,
            ),
            sources=a.sources,
            types=types,
            nodes=a.node_rows(),
            edges=a.edge_rows(),
            aliases=a.aliases(),
            evidence=a.evidence,
            external_refs=a.external_refs,
        )
        sealed = seal(out_path, content)

    size = sealed.path.stat().st_size
    budget = t.budget
    if budget is not None and size > budget:
        _remove(sealed.path)
        raise BuildError(
            "over_budget",
            f"target {t.name!r}: the mosaic is {size} bytes, over its budget of "
            f"{t.fields['budget']} ({budget} bytes)",
        )
    return Built(
        path=sealed.path,
        target=t.name,
        knowledge_hash=sealed.knowledge_hash,
        vector_hash=sealed.vector_hash,
        file_size=size,
        pattern_hash=pattern_hash,
        settings=settings,
        assembly=a,
        messages=(VECTORS_SKIPPED,) if t.vectors else (),
    )
