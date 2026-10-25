"""Serializers: artifact models to bytes, deterministically (MOCK-30).

HTML, code, scripts and tables: UTF-8, ``\\n`` line endings, no timestamps. ``.docx``:
fixed core properties and zip entries in a fixed order with a fixed timestamp. PDF:
ReportLab ``invariant=1``.
"""

from __future__ import annotations

import datetime as dt
import html
import io
import zipfile
from collections.abc import Iterable

from mosaic_mock.engine.model import Document, LinesFile, Para, Section, TableFile
from mosaic_mock.engine.text import Piece, Styled, plain

ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def lines_bytes(f: LinesFile) -> bytes:
    return ("\n".join(plain(line) for line in f.lines) + "\n").encode()


def table_bytes(f: TableFile) -> bytes:
    rows = ([f.header] if f.header else []) + f.rows
    return "".join(f.delimiter.join(r) + "\n" for r in rows).encode()


# --- HTML -------------------------------------------------------------------------------


def _html_text(text: Iterable[Piece]) -> str:
    out = []
    for p in text:
        if isinstance(p, Styled):
            tag = {"b": "b", "i": "i", "code": "code"}[p.mark]
            out.append(f"<{tag}>{html.escape(p.text, quote=False)}</{tag}>")
        else:
            out.append(html.escape(p if isinstance(p, str) else p.text, quote=False))
    return "".join(out)


def _html_blocks(sec: Section, out: list[str], base_level: int) -> None:
    h = min(sec.level + base_level, 6)
    out.append(f"<h{h}>{html.escape(sec.number)} {_html_text(sec.title)}</h{h}>")
    for i, b in enumerate(sec.blocks):
        if isinstance(b, Para):
            if b.style == "bullet":
                prev = sec.blocks[i - 1] if i else None
                nxt = sec.blocks[i + 1] if i + 1 < len(sec.blocks) else None
                opens = not (isinstance(prev, Para) and prev.style == "bullet")
                closes = not (isinstance(nxt, Para) and nxt.style == "bullet")
                out.append(
                    ("<ul>" if opens else "")
                    + f"<li>{_html_text(b.text)}</li>"
                    + ("</ul>" if closes else "")
                )
            else:
                cls = ' class="caption"' if b.style == "caption" else ""
                out.append(f"<p{cls}>{_html_text(b.text)}</p>")
        else:
            out.append("<table>")
            if b.caption:
                out.append(f"<caption>{html.escape(b.caption)}</caption>")
            out.append(
                "<thead><tr>"
                + "".join(f"<th>{html.escape(c)}</th>" for c in b.header)
                + "</tr></thead><tbody>"
            )
            for row in b.rows:
                out.append("<tr>" + "".join(f"<td>{_html_text(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
    for c in sec.children:
        _html_blocks(c, out, base_level)


def html_bytes(doc: Document) -> bytes:
    """A plain generated HTML page, with the kind of script and handlers real tools emit."""
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(doc.title)}</title>",
        "<style>body{font-family:sans-serif;max-width:60em}td,th{border:1px solid #999;"
        "padding:2px 6px}table{border-collapse:collapse}</style>",
        "<script>function printPage(){window.print();}</script>",
        "</head>",
        "<body>",
        f'<h1 onclick="printPage()">{html.escape(doc.title)}</h1>',
    ]
    out += [f"<p>{_html_text(p.text)}</p>" for p in doc.front]
    for s in doc.sections:
        _html_blocks(s, out, base_level=1)
    out += ["</body>", "</html>"]
    return ("\n".join(out) + "\n").encode()


# --- .docx ------------------------------------------------------------------------------


def _docx_runs(par, text: Iterable[Piece]) -> None:
    for p in text:
        if isinstance(p, Styled):
            run = par.add_run(p.text)
            run.bold = p.mark == "b"
            run.italic = p.mark == "i"
            if p.mark == "code":
                run.font.name = "Courier New"
        else:
            par.add_run(p if isinstance(p, str) else p.text)


def docx_bytes(doc: Document, date: dt.date) -> bytes:
    from docx import Document as DocxDocument
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    d = DocxDocument()
    stamp = dt.datetime(date.year, date.month, date.day, tzinfo=dt.UTC)
    cp = d.core_properties
    cp.author = "Mosaic mocker"
    cp.last_modified_by = "Mosaic mocker"
    cp.title = doc.title
    cp.created = stamp
    cp.modified = stamp
    cp.last_printed = stamp
    cp.revision = 1

    d.add_paragraph(doc.title, style="Title")
    for p in doc.front:
        _docx_runs(d.add_paragraph(), p.text)

    def section(sec: Section) -> None:
        h = d.add_paragraph(style=f"Heading {min(sec.level, 9)}")
        _docx_runs(h, [f"{sec.number} " if sec.number else "", *sec.title])
        for b in sec.blocks:
            if isinstance(b, Para):
                style = {"bullet": "List Bullet", "caption": "Caption"}.get(b.style)
                _docx_runs(d.add_paragraph(style=style), b.text)
                continue
            if b.caption:
                d.add_paragraph(b.caption, style="Caption")
            t = d.add_table(rows=1 + len(b.rows), cols=len(b.header))
            t.style = "Table Grid"
            hdr = t.rows[0]
            tr_pr = hdr._tr.get_or_add_trPr()
            flag = OxmlElement("w:tblHeader")
            flag.set(qn("w:val"), "true")
            tr_pr.append(flag)
            for i, name in enumerate(b.header):
                hdr.cells[i].paragraphs[0].add_run(name).bold = True
            for r, row in enumerate(b.rows, 1):
                for i, cell in enumerate(row):
                    _docx_runs(t.rows[r].cells[i].paragraphs[0], cell)
        for c in sec.children:
            section(c)

    for s in doc.sections:
        section(s)
    raw = io.BytesIO()
    d.save(raw)
    return _normalise_zip(raw.getvalue())


def _normalise_zip(data: bytes) -> bytes:
    """Rewrite a zip with sorted entries and a fixed timestamp."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    names = src.namelist()
    # [Content_Types].xml must stay first for Office; the rest in a fixed order.
    order = [n for n in names if n == "[Content_Types].xml"] + sorted(
        n for n in names if n != "[Content_Types].xml"
    )
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in order:
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            dst.writestr(info, src.read(name))
    return out.getvalue()


# --- PDF --------------------------------------------------------------------------------


def _pdf_text(text: Iterable[Piece]) -> str:
    out = []
    for p in text:
        if isinstance(p, Styled):
            t = html.escape(p.text, quote=False)
            out.append(
                {
                    "b": f"<b>{t}</b>",
                    "i": f"<i>{t}</i>",
                    "code": f'<font name="Courier">{t}</font>',
                }[p.mark]
            )
        else:
            out.append(html.escape(p if isinstance(p, str) else p.text, quote=False))
    return "".join(out)


def pdf_bytes(doc: Document, footer: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        LongTable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        TableStyle,
    )

    ss = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=ss["BodyText"], fontName="Helvetica", fontSize=10, leading=13
    )
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2)
    caption = ParagraphStyle("caption", parent=body, fontName="Helvetica-Oblique", fontSize=9)
    cell = ParagraphStyle("cell", parent=body, fontSize=9, leading=11)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold")
    title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=24)
    hstyles = {
        1: ParagraphStyle(
            "h1",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            spaceBefore=12,
            spaceAfter=6,
        ),
        2: ParagraphStyle(
            "h2",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            spaceBefore=10,
            spaceAfter=4,
        ),
        3: ParagraphStyle(
            "h3",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=14,
            spaceBefore=8,
            spaceAfter=3,
        ),
    }

    class Heading(Paragraph):
        def __init__(self, text: str, level: int, key: str, label: str) -> None:
            super().__init__(text, hstyles[min(level, 3)])
            self.level = level
            self.key = key
            self.label = label

    story: list = [Paragraph(html.escape(doc.title), title), Spacer(1, 6)]
    story += [Paragraph(_pdf_text(p.text), body) for p in doc.front]
    n = 0

    def section(sec: Section) -> None:
        nonlocal n
        n += 1
        label = sec.heading()
        story.append(
            Heading(html.escape(f"{sec.number} ") + _pdf_text(sec.title), sec.level, f"s{n}", label)
        )
        for b in sec.blocks:
            if isinstance(b, Para):
                if b.style == "bullet":
                    story.append(Paragraph(_pdf_text(b.text), bullet, bulletText="-"))
                else:
                    story.append(
                        Paragraph(_pdf_text(b.text), caption if b.style == "caption" else body)
                    )
                continue
            if b.caption:
                story.append(Paragraph(html.escape(b.caption), caption))
            data = [[Paragraph(html.escape(h), head) for h in b.header]]
            data += [[Paragraph(_pdf_text(c), cell) for c in row] for row in b.rows]
            t = LongTable(data, repeatRows=1, hAlign="LEFT")
            t.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.extend([t, Spacer(1, 6)])
        for c in sec.children:
            section(c)

    for s in doc.sections:
        section(s)

    def after(flowable: object) -> None:
        if isinstance(flowable, Heading):
            c = pdf.canv
            c.bookmarkPage(flowable.key)
            c.addOutlineEntry(flowable.label, flowable.key, level=flowable.level - 1)

    def page(canvas, _doc) -> None:
        canvas.setFont("Helvetica", 8)
        canvas.drawString(20 * mm, 10 * mm, f"{footer} · page {canvas.getPageNumber()}")

    out = io.BytesIO()
    pdf = SimpleDocTemplate(
        out,
        pagesize=A4,
        invariant=1,
        title=doc.title,
        author="Mosaic mocker",
        creator="Mosaic mocker",
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    pdf.afterFlowable = after  # ty: ignore[invalid-assignment] - ReportLab hook by assignment
    pdf.build(story, onFirstPage=page, onLaterPages=page)
    return out.getvalue()
