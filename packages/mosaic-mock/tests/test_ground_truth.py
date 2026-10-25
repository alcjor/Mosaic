from __future__ import annotations

import re
from collections import Counter

import jsonschema
import pytest
import yaml
from mosaic_mock.engine import truth
from mosaic_mock.engine.readers import self_check

LOC = re.compile(r"^(line=\d+|section=[A-Z0-9.]+|table=[A-Z]+,row=\d+)$")


@pytest.mark.req("MOCK-10", "MOCK-11")
@pytest.mark.parametrize("which", ["small", "toy"])
def test_ground_truth_validates_against_its_schema(which, request) -> None:
    _, gen = request.getfixturevalue(which)
    jsonschema.validate(gen.truth, truth.schema())


@pytest.mark.req("MOCK-10")
def test_locators_are_coarse_and_format_independent(small) -> None:
    _, gen = small
    for m in gen.truth["mentions"]:
        assert LOC.match(m["loc"]), m
        kind = m["loc"].split("=")[0]
        if m["file"].endswith((".py", ".c", ".h")):
            assert kind == "line"
        else:
            assert kind == "section"


@pytest.mark.req("MOCK-11")
def test_long_descriptions_are_fuzzy_only(small) -> None:
    _, gen = small
    matches = Counter(m["match"] for m in gen.truth["mentions"])
    assert matches["exact"] > 1000
    assert matches["fuzzy_only"] > 100
    ld = {i["attrs"].get("PCF_LDESCR") for i in gen.truth["items"] if i["type"] == "PCF"}
    for m in gen.truth["mentions"]:
        if m["surface"] in ld:
            assert m["match"] == "fuzzy_only", m


@pytest.mark.req("MOCK-12", "MOCK-42")
@pytest.mark.parametrize("which", ["small", "toy"])
def test_every_placement_is_where_the_ground_truth_says(which, request) -> None:
    root, gen = request.getfixturevalue(which)
    assert self_check(root, gen.truth) == []


@pytest.mark.req("MOCK-16")
def test_project_file_points_at_generated_files(small) -> None:
    root, _ = small
    project = yaml.safe_load((root / "mosaic.yaml").read_text())
    assert project["pack"] == "spacecraft"
    for src in project["sources"].values():
        paths = src["path"] if isinstance(src["path"], list) else [src["path"]]
        for p in paths:
            assert (root / p).exists(), p


def test_roles_cover_every_link_rule(small) -> None:
    _, gen = small
    roles = {m["role"] for m in gen.truth["mentions"] if m["match"] == "exact"}
    assert roles == {
        "describes",
        "defines_id",
        "handles",
        "uses",
        "sends",
        "sets",
        "reads",
        "mentions",
    }


def test_xrefs_cover_every_rule_type(small) -> None:
    _, gen = small
    types = Counter(x["type"] for x in gen.truth["xrefs"])
    assert set(types) == {"described_in", "defined_in", "handled_by", "documented_in", "see_also"}
    step2 = {
        (x["type"], x["to"]["scope"])
        for x in gen.truth["xrefs"]
        if x["from"] == {"file": "fops/fop_pwr_001.py", "scope": "step=2"}
    }
    assert ("described_in", "section=4.2") in step2  # the example in 04-mocker § 3
    assert ("handled_by", "function=pwr_tc_dispatch") in step2


def test_functions_and_handles_edges(small) -> None:
    _, gen = small
    fn = {i["key"] for i in gen.truth["items"] if i["type"] == "Function"}
    assert "src/pwr_app.c::pwr_tc_dispatch" in fn
    handles = [e for e in gen.truth["edges"] if e["type"] == "handles"]
    assert len(handles) == 30
