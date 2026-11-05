"""The white space of `trim` and `collapse-spaces` is Unicode White_Space (section 5.2, #14).

The list is read from the spec text itself, so a typo there fails here. Python's
`str.isspace` is that set plus U+001C-U+001F (information separators), which is why the spec
lists the code points instead of naming a function. JavaScript's `/\\p{White_Space}/u` is
exactly the set; its `\\s` is not (it lacks U+0085 and adds U+FEFF).
"""

import re

from tests.conftest import REPO

SPEC = REPO / "docs" / "spec-0.1.md"
SENTENCE = re.compile(
    r"White space means the characters with the Unicode `White_Space` property: ([^(]+)\("
)
CODE_POINT = re.compile(r"U\+([0-9A-F]{4})(?:\u2013U\+([0-9A-F]{4}))?")  # ranges use an en dash


def _spec_white_space() -> set[int]:
    match = SENTENCE.search(SPEC.read_text(encoding="utf-8"))
    assert match, "section 5.2 no longer defines white space"
    points: set[int] = set()
    for first, last in CODE_POINT.findall(match.group(1)):
        start = int(first, 16)
        points.update(range(start, int(last or first, 16) + 1))
    return points


def test_the_spec_lists_the_25_white_space_characters() -> None:
    assert len(_spec_white_space()) == 25


def test_the_list_is_python_isspace_without_the_information_separators() -> None:
    isspace = {c for c in range(0x110000) if chr(c).isspace()}
    separators = set(range(0x1C, 0x20))
    assert _spec_white_space() == isspace - separators
    assert separators <= isspace  # why `str.isspace` alone would be wrong
