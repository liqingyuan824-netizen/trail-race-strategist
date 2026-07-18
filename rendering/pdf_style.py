# -*- coding: utf-8 -*-
"""PDF rendering engine for the race-strategy report style-template.

Centralizes EVERY visual constant (palette, font, paragraph styles, table/list
styles, markdown->flowable rules) so the look is fixed and identical no matter
which agent/model produced the Markdown or when it is re-run.

The palette/scale here MUST stay in sync with style-spec.md and report.css.
"""
import os
import re

from markdown import markdown
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                ListFlowable, ListItem, Preformatted, HRFlowable)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ----------------------------------------------------------------------------
# Palette — must match style-spec.md / report.css
# ----------------------------------------------------------------------------
INK    = "#1f2933"
MUTED  = "#52606d"
LINE   = "#d9e2ec"
ACCENT = "#b91c1c"
TITLE_C = "#0b1f33"
H3_C   = "#102a43"
H4_C   = "#243b53"
QUOTE_C = "#7c2d12"
CODE_C = "#e2e8f0"
TH_BG  = "#eef2f7"
ZEBRA  = "#fbfcfe"

# ----------------------------------------------------------------------------
# CJK font registration (system fonts, no download)
# ----------------------------------------------------------------------------
def _register_font():
    for cand, idx in [("C:/Windows/Fonts/msyh.ttc", 0),
                      ("C:/Windows/Fonts/simhei.ttf", 0),
                      ("C:/Windows/Fonts/simsun.ttc", 0)]:
        try:
            pdfmetrics.registerFont(TTFont("CJK", cand, subfontIndex=idx))
            pdfmetrics.registerFont(TTFont("CJK-B", "C:/Windows/Fonts/msyhbd.ttc", subfontIndex=idx))
            return "CJK", "CJK-B"
        except Exception:
            continue
    # fallback: built-in CID font, no external file needed
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light", "STSong-Light"

FONT, CJKB = _register_font()

USABLE = A4[0] - 3.2 * cm  # left+right margin 1.6cm

# ----------------------------------------------------------------------------
# Paragraph styles
# ----------------------------------------------------------------------------
def st(name, size, leading=None, bold=False, color=INK, space_before=6, space_after=6, align=TA_LEFT):
    return ParagraphStyle(name, fontName=CJKB if bold else FONT, fontSize=size,
                           leading=leading or size * 1.45, textColor=colors.HexColor(color),
                           spaceBefore=space_before, spaceAfter=space_after, alignment=align, wordWrap="CJK")

S_TITLE  = st("t", 19, bold=True, color=TITLE_C, space_after=2)
S_META   = st("m", 9, color=MUTED, space_after=2)
S_H1     = st("h1", 15, bold=True, color=TITLE_C, space_before=12, space_after=6)
S_H2     = st("h2", 12.5, bold=True, color=TITLE_C, space_before=10, space_after=4)
S_H3     = st("h3", 11, bold=True, color=H3_C, space_before=8, space_after=3)
S_BODY   = st("b", 9.3, space_after=5)
S_QUOTE  = st("q", 9, color=QUOTE_C, space_before=4, space_after=4)
S_CODE   = st("c", 7.6, color=CODE_C, space_before=4, space_after=6)
S_CELL   = st("cell", 7.6, space_after=0, space_before=0)
S_CELLH  = st("cellh", 7.6, bold=True, color=H3_C, space_after=0, space_before=0)
S_CELL_SM = st("cellsm", 5.6, space_after=0, space_before=0)  # CP overview (wide table)

# ----------------------------------------------------------------------------
# Inline markup (bold + strip links)
# ----------------------------------------------------------------------------
def inline(t):
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)  # markdown link -> plain text
    return t

def cell_para(text, header=False, small=False):
    style = S_CELLH if header else (S_CELL_SM if small else S_CELL)
    return Paragraph(inline(text), style)

# ----------------------------------------------------------------------------
# Table — render ALL columns so PDF matches the full HTML table
# ----------------------------------------------------------------------------
def parse_table(rows):
    header = rows[0]
    data = rows[2:]
    is_cp = any(("到达时间" in h) or ("赛段区间" in h) for h in header)
    n = len(header)
    colw = [USABLE / n] * n
    tbl_rows = [[cell_para(h, header=True, small=is_cp) for h in header]] + \
               [[cell_para(c, small=is_cp) for c in row] for row in data]
    t = Table(tbl_rows, colWidths=colw, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(TH_BG)),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(ZEBRA)]),
    ]))
    return t

# ----------------------------------------------------------------------------
# List — ALWAYS red bullet, never numeric (reportlab bulletType="1" fails on
# multi-item lists and renders "1" on every line). This is a fixed rule.
# ----------------------------------------------------------------------------
def parse_list(items, numbered=False):
    flow = [ListItem(Paragraph(inline(it), S_BODY), leftIndent=10) for it in items]
    return ListFlowable(flow, bulletType="bullet", start="•",
                        leftIndent=14, bulletFontName=FONT, bulletColor=colors.HexColor(ACCENT))

# ----------------------------------------------------------------------------
# Markdown -> reportlab flowables
# ----------------------------------------------------------------------------
def md_to_flowables(text):
    lines = text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip()
        if line.strip() == "":
            i += 1; continue
        if line.startswith("```"):
            buf = []
            i += 1
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1  # skip closing fence
            out.append(Preformatted("\n".join(buf), S_CODE))
            out.append(Spacer(1, 4))
            continue
        if line.startswith("### "):
            out.append(Paragraph(inline(line[4:]), S_H3)); i += 1; continue
        if line.startswith("## "):
            out.append(Paragraph(inline(line[3:]), S_H2)); i += 1; continue
        if line.startswith("# "):
            out.append(Paragraph(inline(line[2:]), S_H1)); i += 1; continue
        if line.startswith("> "):
            buf = []
            while i < n and lines[i].startswith("> "):
                buf.append(lines[i][2:]); i += 1
            out.append(Paragraph(inline(" ".join(buf)), S_QUOTE)); continue
        if line.strip() == "---":
            out.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor(LINE),
                                  spaceBefore=8, spaceAfter=8)); i += 1; continue
        if line.startswith("|"):
            buf = []
            while i < n and lines[i].lstrip().startswith("|"):
                buf.append(lines[i]); i += 1
            rows = [r.strip().strip("|").split("|") for r in buf]
            rows = [[c.strip() for c in r] for r in rows]
            out.append(parse_table(rows)); out.append(Spacer(1, 6)); continue
        if re.match(r"^\s*[-*]\s+", line):
            buf = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                buf.append(re.sub(r"^\s*[-*]\s+", "", lines[i])); i += 1
            out.append(parse_list(buf, numbered=False)); continue
        if re.match(r"^\s*\d+\.\s+", line):
            buf = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                buf.append(re.sub(r"^\s*\d+\.\s+", "", lines[i])); i += 1
            out.append(parse_list(buf, numbered=True)); continue
        # paragraph: gather consecutive non-special lines
        buf = [line]
        i += 1
        while i < n and lines[i].strip() != "" and not lines[i].startswith(("|", "#", ">", "```", "- ", "* ")) \
                and not re.match(r"^\s*\d+\.\s+", lines[i]) and lines[i].strip() != "---":
            buf.append(lines[i]); i += 1
        out.append(Paragraph(inline(" ".join(s.strip() for s in buf)), S_BODY))
    return out

# ----------------------------------------------------------------------------
# Public: build PDF from markdown text
# ----------------------------------------------------------------------------
def build_pdf(md, out_pdf):
    flow = md_to_flowables(md)
    tmp = out_pdf + ".tmp"
    doc = SimpleDocTemplate(tmp, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.5 * cm,
                            title="Race Strategy Report", author="Trail Race Strategist")
    doc.build(flow)
    try:
        os.replace(tmp, out_pdf)
        return out_pdf
    except OSError:
        alt = out_pdf[:-4] + "-v2.pdf"
        os.replace(tmp, alt)
        return alt
