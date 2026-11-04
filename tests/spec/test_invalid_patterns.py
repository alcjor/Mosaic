"""The conformance cases of invalid patterns and proposals: one per rule (Spec 0.1 section 11).

Section 11: "Invalid patterns and proposals, one per rule in sections 5 and 5.6 | A checker
rejects each." Each case directory is named after the one rule it breaks, and the checker
must reject it naming that rule and no other.
"""

from pathlib import Path

import pytest
from mosaic_format.pattern import RULES, check_pattern

from tests.cases import PATTERN_CASES, prepare

CASES = sorted(p.name for p in PATTERN_CASES.iterdir() if p.is_dir())

# Rules of other sections that the pattern checker also reports, without a case here.
NOT_SECTION_5 = {"piece-refused"}


def test_every_rule_of_section_5_has_one_case() -> None:
    section_5 = {rule for rule, (section, _) in RULES.items() if rule not in NOT_SECTION_5}
    assert all(RULES[rule][0].startswith("5") for rule in section_5)
    assert set(CASES) == section_5


@pytest.mark.parametrize("rule", CASES)
def test_the_case_is_rejected_naming_its_rule(rule: str, tmp_path: Path) -> None:
    report = check_pattern(**prepare(PATTERN_CASES / rule, tmp_path))
    assert not report.ok
    assert {v.rule for v in report.violations} == {rule}, [str(v) for v in report.violations]
    for violation in report.violations:
        assert violation.line is not None, str(violation)
        assert f"[{rule}, section {RULES[rule][0]}]" in str(violation)


@pytest.mark.parametrize("rule", CASES)
def test_the_case_has_a_readme_line(rule: str) -> None:
    readme = (PATTERN_CASES / "README.md").read_text("utf-8")
    assert f"`{rule}`" in readme
