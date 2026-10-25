"""The engine pipeline (04-mocker § 2).

    profile.build_world(rng, size)  →  World
    renderers                       →  artifact models (references as typed pieces)
    defect injectors                →  mutated models + Defect records
    serializers + writer            →  files + ground_truth.json

Placements are read off the final models, after defects, so the ground truth always
describes the files as written (MOCK-12, MOCK-25).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import random
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from mosaic_mock import __version__
from mosaic_mock.engine import serialize, truth
from mosaic_mock.engine.model import Artifact, Document, LinesFile, RawFile, TableFile
from mosaic_mock.engine.rng import Rng
from mosaic_mock.engine.textgen import PROVIDERS, LlmProvider, TextGen
from mosaic_mock.engine.truth import Defect, Placement, XrefTruth
from mosaic_mock.engine.world import World


@dataclass(frozen=True)
class SizeSpec:
    name: str
    counts: Mapping[str, int]

    def scaled(self, factor: float) -> SizeSpec:
        if factor == 1.0:
            return self
        return SizeSpec(self.name, {k: max(1, round(v * factor)) for k, v in self.counts.items()})

    def __getitem__(self, key: str) -> int:
        return self.counts[key]


@dataclass
class RenderContext:
    rng: Rng
    size: SizeSpec
    date: dt.date
    textgen: TextGen
    world: World
    used_locators: set[tuple[str, str]] = field(default_factory=set)


class Renderer(Protocol):
    name: str

    def render(self, ctx: RenderContext) -> Sequence[Artifact]: ...


class DefectInjector(Protocol):
    code: str  # D01 …
    kind: str
    where: str
    expected_detection: str

    def inject(
        self, ctx: RenderContext, artifacts: dict[str, Artifact], rng: random.Random, defect_id: str
    ) -> Defect | None: ...


class Profile(Protocol):
    name: str
    sizes: Mapping[str, SizeSpec]
    default_defects: Sequence[str]  # kinds in the "default" set

    def build_world(self, rng: Rng, size: SizeSpec) -> World: ...
    def renderers(self) -> Sequence[Renderer]: ...
    def defect_injectors(self) -> Mapping[str, DefectInjector]: ...
    def template_dir(self) -> Path: ...
    def xrefs(self, placements: Sequence[Placement], ctx: RenderContext) -> list[XrefTruth]: ...


@dataclass
class Generated:
    files: dict[str, bytes]
    truth: dict[str, Any]


def truth_file(a: Artifact) -> str:
    if isinstance(a, Document):
        return f"{a.path}.{a.formats[0]}"
    return a.path


def placements(artifacts: Mapping[str, Artifact]) -> list[Placement]:
    out = []
    for a in artifacts.values():
        if isinstance(a, LinesFile | Document):
            f = truth_file(a)
            for loc, scope, r in a.placements():
                if r.match != "none":
                    out.append(Placement(f, loc, scope, r.text, r.item, r.role, r.match))
    return out


def defect_plan(profile: Profile, defects: str | Path) -> list[tuple[str, int]]:
    """``none``, ``default``, ``all`` or a YAML file ``{defects: [{kind, count}]}``."""
    kinds = list(profile.defect_injectors())
    if defects == "none":
        return []
    if defects == "default":
        return [(k, 1) for k in profile.default_defects]
    if defects == "all":
        return [(k, 2) for k in kinds]
    spec = yaml.safe_load(Path(defects).read_text(encoding="utf-8")) or {}
    plan = []
    for entry in spec.get("defects", []):
        if entry["kind"] not in kinds:
            raise ValueError(f"unknown defect kind {entry['kind']!r}; known: {', '.join(kinds)}")
        plan.append((entry["kind"], int(entry.get("count", 1))))
    return plan


def serialize_all(artifacts: Mapping[str, Artifact], date: dt.date) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for a in artifacts.values():
        if isinstance(a, LinesFile):
            files[a.path] = serialize.lines_bytes(a)
        elif isinstance(a, TableFile):
            files[a.path] = serialize.table_bytes(a)
        elif isinstance(a, RawFile):
            files[a.path] = a.data
        else:
            for fmt in a.formats:
                p = f"{a.path}.{fmt}"
                if fmt == "html":
                    files[p] = serialize.html_bytes(a)
                elif fmt == "docx":
                    files[p] = serialize.docx_bytes(a, date)
                elif fmt == "pdf":
                    files[p] = serialize.pdf_bytes(a, footer=a.title)
                else:
                    raise ValueError(f"unknown document format {fmt!r}")
    return dict(sorted(files.items()))


def generate(
    profile: Profile,
    *,
    size: str = "small",
    scale: float = 1.0,
    seed: int = 42,
    defects: str | Path = "none",
    date: dt.date = dt.date(2026, 1, 1),
    llm: str | LlmProvider | None = None,
    cache_dir: Path | None = None,
) -> Generated:
    rng = Rng(seed)
    spec = profile.sizes[size].scaled(scale)
    world = profile.build_world(rng, spec)
    provider = PROVIDERS[llm]() if isinstance(llm, str) else llm
    textgen = TextGen(
        profile.template_dir(),
        provider,
        (cache_dir / profile.name) if cache_dir and provider else None,
    )
    ctx = RenderContext(rng, spec, date, textgen, world)

    artifacts: dict[str, Artifact] = {}
    for r in profile.renderers():
        for a in r.render(ctx):
            artifacts[a.path] = a

    injectors = profile.defect_injectors()
    found: list[Defect] = []
    for kind, count in defect_plan(profile, defects):
        inj = injectors[kind]
        for i in range(count):
            d = inj.inject(
                ctx, artifacts, rng.stream(f"defect:{kind}:{i}"), f"{inj.code}-{i + 1:04d}"
            )
            if d is not None:
                ctx.used_locators.add((d.file, d.loc))
                found.append(d)

    places = placements(artifacts)
    xrefs = profile.xrefs(places, ctx)
    files = serialize_all(artifacts, date)
    doc: dict[str, Any] = {
        "profile": profile.name,
        "size": size,
        "scale": scale,
        "seed": seed,
        "mocker_version": __version__,
        "defect_set": str(defects) if not isinstance(defects, Path) else defects.name,
        "llm": provider.name if provider else None,
        "items": [
            {"type": i.type, "key": i.key, "attrs": {k: v for k, v in i.attrs.items() if v != ""}}
            for i in ctx.world
        ],
        "edges": [{"type": e.type, "from": e.src, "to": e.dst} for e in ctx.world.edges],
        "mentions": [
            {
                "file": p.file,
                "loc": p.loc,
                "surface": p.surface,
                "item": p.item,
                "role": p.role,
                "match": p.match,
            }
            for p in places
        ],
        "xrefs": [x.as_json() for x in xrefs],
        "defects": [d.as_json() for d in found],
        "files": [{"path": p, "sha256": hashlib.sha256(b).hexdigest()} for p, b in files.items()],
    }
    return Generated(files, doc)


def write(out: Path, gen: Generated) -> None:
    """Write a generation to ``out``, replacing a previous mocker output there."""
    if out.exists() and any(out.iterdir()):
        if not (out / "ground_truth.json").exists():
            raise FileExistsError(f"{out} is not empty and is not a mocker output; not overwriting")
        shutil.rmtree(out)
    for rel, data in gen.files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (out / "ground_truth.json").write_bytes(truth.dumps(gen.truth))
