from __future__ import annotations

import ast
import io

import pytest
from mosaic_mock.profiles.spacecraft.srdb_columns import COLUMNS, CUSTOM


@pytest.mark.req("MOCK-41")
def test_dat_rows_have_the_spec_column_count(small) -> None:
    _, gen = small
    tables = [p for p in gen.files if p.startswith("srdb/")]
    assert len(tables) >= 15
    for path in tables:
        table = path.removeprefix("srdb/").removesuffix(".dat").upper()
        width = len(COLUMNS[table]) + len(CUSTOM.get(table, []))
        for line in gen.files[path].decode().splitlines():
            assert len(line.split("\t")) == width, (path, line)


@pytest.mark.req("MOCK-41")
def test_docx_reopens_with_python_docx(small) -> None:
    from docx import Document

    _, gen = small
    doc = Document(io.BytesIO(gen.files["sum/sum.docx"]))
    headings = [
        p.text for p in doc.paragraphs if p.style and (p.style.name or "").startswith("Heading")
    ]
    assert "4 Power application (PWR)" in headings
    assert len(doc.tables) > 10


@pytest.mark.req("MOCK-41")
def test_pdf_text_extracts_with_pypdf(small) -> None:
    from pypdf import PdfReader

    _, gen = small
    reader = PdfReader(io.BytesIO(gen.files["sum/sum.pdf"]))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "4.2 Telecommands" in text
    assert "PWRC0101" in text
    assert len(reader.outline) > 5  # bookmarks


@pytest.mark.req("MOCK-41")
def test_fops_parse(small) -> None:
    _, gen = small
    fops = [p for p in gen.files if p.startswith("fops/")]
    assert len(fops) == 6
    for path in fops:
        ast.parse(gen.files[path].decode(), path)


@pytest.mark.req("MOCK-41")
def test_c_parses_without_error_nodes(small) -> None:
    import tree_sitter_c
    from tree_sitter import Language, Parser

    parser = Parser(Language(tree_sitter_c.language()))
    sources = [p for p in gen_files(small) if p.endswith((".c", ".h"))]
    assert len(sources) == 14
    for path in sources:
        tree = parser.parse(small[1].files[path])
        assert not tree.root_node.has_error, path


def gen_files(small) -> list[str]:
    return list(small[1].files)


@pytest.mark.req("MOCK-41")
def test_icd_html_has_tables_per_packet_and_tc(small) -> None:
    _, gen = small
    html = gen.files["icd/scsw_icd.html"].decode()
    assert html.count("<h3>") == 8 + 30
    assert "<h3>2.1 PWRC0101 PWR_HTR_A_ON</h3>" in html


def test_example_fop_matches_the_spec(small) -> None:
    """04-mocker § 5.2 shows FOP-PWR-001 for the small mission with seed 42."""
    _, gen = small
    expected = '''"""FOP-PWR-001 Battery heater activation

Purpose: switch on battery heater A when the battery is cold.
Preconditions: BAT_V_MAIN (PWRT0012) above 26 V.
"""
from demoproc import step, send_tc, verify_tm, wait


@step(1, "Check battery voltage")
def step_1():
    verify_tm("PWRT0012", ">", 26.0)      # BAT_V_MAIN


@step(2, "Switch heater A on")
def step_2():
    send_tc("PWRC0101", PWRP0001=1)       # PWR_HTR_A_ON, thermostat mode
    wait(5)
    verify_tm("PWRT0031", "==", "ON")     # HTR_A_STAT
'''
    assert gen.files["fops/fop_pwr_001.py"].decode() == expected
