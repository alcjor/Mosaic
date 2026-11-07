"""The kit's tool cases on the Chinook mosaic (Specification 0.1, sections 8 and 11; plan M3.4).

Section 11: "tool cases with expected answers, on the Chinook mosaic. A kit's answers match and
are valid against ``answers.schema.json``". The mosaic is built as ``test_chinook.py`` builds it
(the source and the model fetched and checked by their pinned SHA-256, a new and empty directory,
vectors on), and is the one ``expected-hashes.json`` names. Then ``kit/scripts/run-cases.ts`` runs
every case of ``conformance/tools/expected-answers.json`` in the kit, with the model for the
vector tier of ``find``: each answer equals its expected answer and is valid against
``spec/answers.schema.json``. Run it with ``-s`` for the command and a line per case.
"""

import json
import shutil
import subprocess
import sys
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from mosaic_format.reader import open as open_sealed

from tests.conftest import MODEL, REPO
from tests.fixtures import test_chinook
from tests.fixtures.expected import load_expected
from tests.fixtures.tool_cases import FILE, SCHEMA, differences, load

pytestmark = pytest.mark.slow

NODE_IDS: set[str] = set()
"""The ids of the built mosaic's nodes: an unknown id's suggestions must be among them."""


@pytest.fixture(scope="module")
def answers(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The kit's answer to every case, on the Chinook mosaic built in a new, empty directory."""
    fetched = subprocess.run(
        [sys.executable, "-I", str(REPO / "scripts" / "fetch_fixtures.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert "ok   chinook" in fetched.stdout, fetched.stdout + fetched.stderr
    model = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "fetch_model.py"), "--dest", str(MODEL)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert model.returncode == 0, model.stdout + model.stderr
    run = test_chinook._run(tmp_path_factory.mktemp("chinook-tools") / "build")
    expected = load_expected(test_chinook.FIXTURE)[test_chinook.TARGET]
    assert run.mosaic_hash == expected.knowledge_hash, "the mosaic expected-hashes.json names"
    mosaic = tmp_path_factory.mktemp("chinook-mosaic") / "chinook.mosaic"
    mosaic.write_bytes(run.mosaic_bytes)
    bun = shutil.which("bun")
    assert bun, "bun runs the kit (CLAUDE.md, Commands)"
    command = [bun, "kit/scripts/run-cases.ts", str(mosaic), str(FILE), "--model", str(MODEL)]
    done = subprocess.run(
        command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr
    found: dict[str, Any] = json.loads(done.stdout)
    with open_sealed(mosaic) as m:
        NODE_IDS.update(str(i) for (i,) in m.query("SELECT id FROM node"))
    print(f"\n$ bun kit/scripts/run-cases.ts {mosaic.name} {FILE.relative_to(REPO)} --model …")
    for name, answer in found.items():
        if "error" in answer:
            print(f"{name}: {answer['tool']} error {answer['error']['code']}")
            continue
        data = answer["data"]
        listed = next(
            (data[k] for k in ("results", "rows", "edges", "evidence") if k in data), None
        )
        shown = "" if listed is None else f" {len(listed)} of {data['total']}"
        print(f"{name}: {answer['tool']}{shown}")
    return found


def test_every_case_gives_its_expected_answer(answers: dict[str, Any]) -> None:
    found = differences(load(FILE)["cases"], answers, node_ids=NODE_IDS or None)
    assert not found, "\n".join(found)


def test_every_answer_is_valid_against_the_answers_schema(answers: dict[str, Any]) -> None:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    for name, answer in answers.items():
        errors = [e.message for e in validator.iter_errors(answer)]
        assert not errors, f"{name}: {errors}"


def test_the_run_answers_every_case_and_nothing_else(answers: dict[str, Any]) -> None:
    assert list(answers) == list(load(FILE)["cases"])
