from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
from mosaic_mock import profiles
from mosaic_mock.engine import truth
from mosaic_mock.engine.generate import generate

SRC = Path(__file__).parents[1] / "src" / "mosaic_mock"

# Golden hashes of ground_truth.json per (profile, size, seed). Update only on purpose,
# after reviewing the change in the generated files (MOCK-40).
GOLDEN = {
    ("spacecraft", "small", 42): "8a14c7b8ee996bff707aa1bb43e23cc9bac19189639189b4e2094518b86b55bc",
    ("toy", "small", 42): "e44ceba3a654822e5950c26d4cf84e828fb2ce9dc6e1cc70fa49c39574d6f2d5",
}


def _digest(profile: str, size: str, seed: int) -> str:
    gen = generate(profiles.get(profile), size=size, seed=seed)
    h = hashlib.sha256(truth.dumps(gen.truth))
    for path, data in gen.files.items():
        h.update(path.encode())
        h.update(data)
    return h.hexdigest()


@pytest.mark.req("MOCK-02", "MOCK-40")
@pytest.mark.parametrize("profile", ["spacecraft", "toy"])
def test_two_generations_are_byte_identical(profile: str) -> None:
    assert _digest(profile, "small", 42) == _digest(profile, "small", 42)


@pytest.mark.req("MOCK-40")
@pytest.mark.parametrize(("profile", "size", "seed"), list(GOLDEN))
def test_golden_hashes(profile: str, size: str, seed: int) -> None:
    gen = generate(profiles.get(profile), size=size, seed=seed)
    assert hashlib.sha256(truth.dumps(gen.truth)).hexdigest() == GOLDEN[(profile, size, seed)]


@pytest.mark.req("MOCK-02")
def test_seed_changes_the_output() -> None:
    assert _digest("spacecraft", "small", 42) != _digest("spacecraft", "small", 7)


@pytest.mark.req("MOCK-30")
def test_docx_zip_is_normalised(small) -> None:
    _, gen = small
    z = zipfile.ZipFile(io.BytesIO(gen.files["sum/sum.docx"]))
    assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    names = z.namelist()
    assert names[0] == "[Content_Types].xml"
    assert names[1:] == sorted(names[1:])
    core = z.read("docProps/core.xml").decode()
    assert "2026-01-01T00:00:00Z" in core


@pytest.mark.req("MOCK-30")
def test_text_files_use_lf_and_utf8(small) -> None:
    _, gen = small
    for path, data in gen.files.items():
        if path.endswith((".py", ".c", ".h", ".html", ".dat", ".yaml")):
            text = data.decode("utf-8")
            assert "\r" not in text, path


@pytest.mark.req("MOCK-30")
def test_pdf_is_invariant(small) -> None:
    _, gen = small
    pdf = gen.files["sum/sum.pdf"]
    assert b"/CreationDate" not in pdf or b"D:20000101000000" in pdf


@pytest.mark.req("MOCK-31")
def test_no_global_random_set_order_or_clock() -> None:
    bad = re.compile(
        r"(?<![\w.])random\.(random|randint|choice|shuffle|seed|randrange|sample)\(|"
        r"time\.time\(|datetime\.now\(|date\.today\(|uuid\.uuid4\("
    )
    hits = []
    for f in SRC.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if bad.search(line) and "random.Random" not in line:
                hits.append(f"{f.relative_to(SRC)}:{n}: {line.strip()}")
    assert hits == []


@pytest.mark.req("MOCK-31", "MOCK-02")
def test_output_does_not_depend_on_hash_seed(tmp_path: Path) -> None:
    """Set iteration order follows PYTHONHASHSEED; the output must not."""
    script = (
        "import hashlib, sys; from mosaic_mock import profiles; "
        "from mosaic_mock.engine import truth; from mosaic_mock.engine.generate import generate; "
        "g = generate(profiles.get('spacecraft')); h = hashlib.sha256(truth.dumps(g.truth)); "
        "[h.update(d) for d in g.files.values()]; print(h.hexdigest())"
    )
    digests = set()
    for seed in ("1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(
            [sys.executable, "-c", script], env=env, check=True, capture_output=True, text=True
        )
        digests.add(out.stdout.strip())
    assert len(digests) == 1


@pytest.mark.req("MOCK-44")
def test_small_generation_under_five_seconds() -> None:
    t = time.perf_counter()
    generate(profiles.get("spacecraft"))
    assert time.perf_counter() - t < 5.0
