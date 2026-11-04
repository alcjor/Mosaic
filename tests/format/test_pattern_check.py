"""``mosaic_format.pattern.check_pattern`` checks a pattern and its proposals (Spec 0.1 section 5).

The checker reports every violation of section 5 it can see from its inputs. Rules that need
piece files run only when the caller gives the candidate files, and the proposals' existence
check runs only when the caller gives the ``built_from`` mosaic (decisions on #10, section
5.1 and 5.6); the report lists the rules it skipped. The one-rule-per-case conformance files
are in ``tests/spec/test_invalid_patterns.py``.
"""

from pathlib import Path

import pytest
from mosaic_format import seal
from mosaic_format.pattern import PIECE_RULES, RULES, Report, Violation, check_pattern

from tests.cases import content

EXAMPLES = Path(__file__).resolve().parents[1] / "spec" / "examples"
PATTERN = EXAMPLES / "pattern-plant.yaml"
PROPOSALS = EXAMPLES / "proposals.yaml"

PIECE = {"kind": "tessera", "types": {"Row": "node", "Other": "node", "links": ["Row", "Row"]}}
BUILT = {
    "kind": "mosaic",
    "types": {"Item": "node", "Group": "node"},
    "nodes": ["Item:A", "Group:g"],
}


def rules(report: Report) -> list[str]:
    return [v.rule for v in report.violations]


def write(path: Path, text: str) -> Path:
    path.write_text(text, "utf-8", newline="\n")
    return path


def valid_case(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """A pattern with one real piece and proposals with their real ``built_from`` mosaic."""
    piece = tmp_path / "rows.tessera"
    piece_hash = seal(piece, content(PIECE)).knowledge_hash
    built = tmp_path / "built.mosaic"
    built_hash = seal(built, content(BUILT)).knowledge_hash
    pattern = write(
        tmp_path / "pattern.yaml",
        f"""format: "0.1"
pieces:
  - rows@{piece_hash[:8]}
types:
  Item:
    key: code
    from:
      rows.Row: {{code: key}}
  Group:
    key: code
    from:
      rows.Other: {{code: key}}
edges:
  member:
    from: Item
    to: Group
    map: [rows.links]
mosaics:
  all: {{}}
  some: {{types: [Item]}}
""",
    )
    proposals = write(
        tmp_path / "proposals.yaml",
        f"""format: "0.1"
built_from: {built_hash}
assistant: helper/1
proposals:
  - id: p1
    kind: identity
    node: Item:A
    same_as: [a-one]
    confidence: 0.5
    evidence: [{{source: doc, locator: page=1}}]
    decision: open
  - id: p2
    kind: edge
    type: member
    from: Item:A
    to: Group:g
    confidence: 0.9
    evidence: [{{source: doc, locator: page=2}}]
    decision: accepted
    decided_by: someone
""",
    )
    return pattern, proposals, piece, built


# --- Conforming inputs are accepted ---------------------------------------------------------


def test_the_documented_pattern_is_accepted_without_piece_files() -> None:
    report = check_pattern(PATTERN)
    assert report.ok, [str(v) for v in report.violations]
    assert report.violations == ()
    assert set(report.skipped) == set(PIECE_RULES)


def test_the_documented_proposals_are_accepted_without_their_mosaic() -> None:
    report = check_pattern(PATTERN, proposals=PROPOSALS)
    assert report.ok, [str(v) for v in report.violations]
    assert set(report.skipped) == {*PIECE_RULES, "proposal-node-missing"}


def test_a_pattern_with_its_pieces_and_mosaic_runs_every_rule(tmp_path: Path) -> None:
    pattern, proposals, piece, built = valid_case(tmp_path)
    report = check_pattern(pattern, proposals=proposals, pieces=[piece], built_from=built)
    assert report.ok, [str(v) for v in report.violations]
    assert report.skipped == ()


def test_the_same_candidate_given_twice_is_one_file(tmp_path: Path) -> None:
    pattern, _, piece, _ = valid_case(tmp_path)
    other_spelling = tmp_path / "." / piece.name
    assert check_pattern(pattern, pieces=[piece, other_spelling]).ok


def test_candidates_may_be_any_iterable(tmp_path: Path) -> None:
    pattern, _, piece, _ = valid_case(tmp_path)
    report = check_pattern(pattern, pieces=(p for p in [piece]))
    assert report.ok, [str(v) for v in report.violations]
    assert report.skipped == ()


def test_candidates_that_match_no_piece_are_ignored(tmp_path: Path) -> None:
    pattern, _, piece, _ = valid_case(tmp_path)
    unrelated = tmp_path / "other.tessera"
    seal(unrelated, content({"kind": "tessera", "types": {"Else": "node"}}))
    assert check_pattern(pattern, pieces=[unrelated, piece]).ok


# --- Piece files ------------------------------------------------------------------------------


def test_no_candidates_leave_every_piece_unmatched() -> None:
    report = check_pattern(PATTERN, pieces=[])
    assert rules(report) == ["piece-unmatched"] * 3
    assert report.skipped == ()
    # The type rules need the piece file, so they are not reported on top.
    assert [v.where for v in report.violations] == ["pieces/0", "pieces/1", "pieces/2"]


def test_a_candidate_refused_by_the_reading_rules_is_reported(tmp_path: Path) -> None:
    pattern, _, piece, _ = valid_case(tmp_path)
    broken = write(tmp_path / "broken.tessera", "not a database")
    report = check_pattern(pattern, pieces=[piece, broken])
    assert rules(report) == ["piece-refused"]
    assert str(broken) in str(report.violations[0])
    assert "section 3.8" in str(report.violations[0])


def test_a_missing_candidate_is_an_error(tmp_path: Path) -> None:
    pattern, *_ = valid_case(tmp_path)
    with pytest.raises(FileNotFoundError):
        check_pattern(pattern, pieces=[tmp_path / "nowhere.tessera"])


def test_a_piece_type_must_be_of_the_right_kind(tmp_path: Path) -> None:
    pattern, _, piece, _ = valid_case(tmp_path)
    text = pattern.read_text("utf-8")
    # `links` is an edge type of the piece, `Row` a node type: each is used in the wrong place.
    text = text.replace("rows.Other: {code: key}", "rows.Missing: {code: key}")
    text = text.replace("map: [rows.links]", "map: [rows.nothing]")
    write(pattern, text)
    report = check_pattern(pattern, pieces=[piece])
    assert rules(report) == ["from-type", "map-type"]
    assert "Missing" in report.violations[0].message
    assert "nothing" in report.violations[1].message


# --- Proposals ---------------------------------------------------------------------------------


def test_built_from_must_be_the_mosaic_the_proposals_name(tmp_path: Path) -> None:
    pattern, proposals, _, _ = valid_case(tmp_path)
    other = tmp_path / "other.mosaic"
    seal(other, content({**BUILT, "nodes": ["Item:B"]}))
    with pytest.raises(ValueError, match="built_from"):
        check_pattern(pattern, proposals=proposals, built_from=other)


def test_built_from_must_be_a_mosaic(tmp_path: Path) -> None:
    pattern, proposals, piece, _ = valid_case(tmp_path)
    with pytest.raises(ValueError, match="mosaic"):
        check_pattern(pattern, proposals=proposals, built_from=piece)


def test_built_from_needs_proposals(tmp_path: Path) -> None:
    pattern, _, _, built = valid_case(tmp_path)
    with pytest.raises(ValueError, match="proposals"):
        check_pattern(pattern, built_from=built)


def test_existence_is_checked_in_the_built_from_mosaic(tmp_path: Path) -> None:
    pattern, proposals, piece, built = valid_case(tmp_path)
    write(proposals, proposals.read_text("utf-8").replace("to: Group:g", "to: Group:h"))
    report = check_pattern(pattern, proposals=proposals, pieces=[piece], built_from=built)
    assert rules(report) == ["proposal-node-missing"]
    assert report.violations[0].where == "proposals/1/to"
    assert "Group:h" in report.violations[0].message


def test_an_undeclared_type_is_not_also_reported_as_a_wrong_end(tmp_path: Path) -> None:
    text = PROPOSALS.read_text("utf-8").replace("from: Step:", "from: Valve:")
    report = check_pattern(PATTERN, proposals=write(tmp_path / "proposals.yaml", text))
    assert rules(report) == ["proposal-node-type"]


# --- Reporting -------------------------------------------------------------------------------


def test_schema_violations_stop_the_cross_checks(tmp_path: Path) -> None:
    text = PATTERN.read_text("utf-8").replace("to: Sensor", "to: sensor")
    text = text.replace("types: [Sensor]", "types: [Valve]")
    report = check_pattern(write(tmp_path / "p.yaml", text), proposals=PROPOSALS)
    assert set(rules(report)) == {"schema"}
    assert report.violations[0].where == "edges/reads/to"
    assert report.violations[0].line == 25


def test_proposals_are_still_read_when_the_pattern_is_broken(tmp_path: Path) -> None:
    pattern = write(tmp_path / "p.yaml", "format: '0.1'\npieces: []\n")
    proposals = write(tmp_path / "q.yaml", "format: '0.1'\nformat: '0.1'\n")
    report = check_pattern(pattern, proposals=proposals)
    assert set(rules(report)) == {"schema", "duplicate-key"}
    assert rules(report)[-1] == "duplicate-key"
    files = [v.file for v in report.violations]
    assert files == [str(pattern)] * (len(files) - 1) + [str(proposals)]


def test_text_that_is_not_utf8_is_a_yaml_violation(tmp_path: Path) -> None:
    pattern = tmp_path / "p.yaml"
    pattern.write_bytes(b"format: '0.1'\nname: \xff\n")
    report = check_pattern(pattern)
    assert rules(report) == ["yaml"]
    assert "UTF-8" in report.violations[0].message


def test_a_violation_names_file_line_place_rule_and_section() -> None:
    v = Violation(file="p.yaml", line=3, where="types/T", rule="from-piece", message="m")
    assert str(v) == "p.yaml:3: types/T: m [from-piece, section 5.6]"
    assert str(Violation(file="p.yaml", line=None, where="", rule="yaml", message="m")) == (
        "p.yaml: m [yaml, section 5]"
    )


def test_violations_come_in_file_and_line_order(tmp_path: Path) -> None:
    text = PATTERN.read_text("utf-8")
    text = text.replace("procedures.Step", "nobody.Step").replace("code.Define", "none.Define")
    text = text.replace("- code@", "- supplier@")
    report = check_pattern(write(tmp_path / "p.yaml", text))
    lines = [v.line or 0 for v in report.violations]
    assert lines == sorted(lines)
    assert rules(report) == ["own-output", "from-piece", "from-piece"]


def test_every_rule_names_a_section() -> None:
    for rule, (section, meaning) in RULES.items():
        assert section.split(".")[0] in {"3", "5"}, rule
        assert meaning
