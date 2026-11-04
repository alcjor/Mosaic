"""The ``mosaic-format`` wheel ships the five normative files and they open from the install.

Issue #5: "A wheel built with ``uv build`` contains the five files and a test opens them from
the installed wheel." ``uv build`` builds an sdist first and the wheel from it, so this covers
both packaging paths.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from mosaic_format import NORMATIVE_FILES

from tests.conftest import REPO, SPEC

PACKAGE = REPO / "packages" / "mosaic-format"

PROBE = """
import hashlib, json, sqlite3, sys, tempfile
from pathlib import Path
import mosaic_format
from mosaic_format import NORMATIVE_FILES, create, schema

out = {
    "package": str(Path(mosaic_format.__file__).resolve().parent),
    "spec_dir": str(Path(str(schema.spec_dir())).resolve()),
    "sha256": {n: hashlib.sha256(schema.read_text(n).encode("utf-8")).hexdigest()
               for n in NORMATIVE_FILES},
    "json_schemas": [schema.json_schema(n)["$schema"] for n in schema.JSON_SCHEMAS],
}
with tempfile.TemporaryDirectory() as d:
    path = create(Path(d) / "t.tessera", "tessera")
    con = sqlite3.connect(path)
    out["objects"] = con.execute("SELECT count(*) FROM sqlite_schema").fetchone()[0]
    con.close()
print(json.dumps(out))
"""


def _uv() -> str:
    uv = shutil.which("uv")
    assert uv, "uv is required to build the wheel"
    return uv


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [_uv(), "build", str(PACKAGE), "--out-dir", str(out), "--quiet"],
        check=True,
        cwd=REPO,
    )
    wheels = sorted(out.glob("mosaic_format-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def test_wheel_contains_the_five_files(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as zf:
        for name in NORMATIVE_FILES:
            assert zf.read(f"mosaic_format/spec/{name}") == (SPEC / name).read_bytes(), name


def test_installed_wheel_opens_the_files(wheel: Path, tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    subprocess.run([_uv(), "venv", str(venv), "--python", sys.executable, "--quiet"], check=True)
    python = venv / ("Scripts" if os.name == "nt" else "bin") / "python"
    subprocess.run(
        [
            _uv(),
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--offline",
            "--quiet",
            str(wheel),
        ],
        check=True,
    )
    # -I: isolated mode, so neither the repository nor its editable install is importable.
    done = subprocess.run(
        [str(python), "-I", "-c", PROBE],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    out = json.loads(done.stdout)
    package = Path(out["package"])
    assert package.is_relative_to(venv.resolve()), package
    assert Path(out["spec_dir"]) == package / "spec"
    assert out["sha256"] == {
        name: hashlib.sha256((SPEC / name).read_bytes()).hexdigest() for name in NORMATIVE_FILES
    }
    assert set(out["json_schemas"]) == {"https://json-schema.org/draft/2020-12/schema"}
    assert out["objects"] > 0
