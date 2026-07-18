# -*- coding: utf-8 -*-
"""Generic renderer: any trail-race-strategy Markdown -> fixed-style HTML + PDF.

This is the ONLY entry point. It reads the Markdown produced by the
trail-race-strategist skill (or any compatible MD), then renders it with the
fixed visual style defined in this directory (style-spec.md + report.css +
pdf_style.py). It does NOT modify any skill file.

Usage:
    python build_report.py <report.md> [--out-dir DIR]

Outputs:
    <name>.html  and  <name>.pdf   (next to the MD, or in --out-dir)

The style assets (report.css, pdf_style.py) are loaded from THIS script's own
directory, so it works no matter where the Markdown lives or where you call it.
"""
import os
import sys
import re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pdf_style import build_pdf  # noqa: E402

from markdown import markdown


def main():
    if len(sys.argv) < 2:
        print("usage: python build_report.py <report.md> [--out-dir DIR]")
        sys.exit(1)

    src = sys.argv[1]
    out_dir = None
    if "--out-dir" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--out-dir") + 1]

    if not os.path.exists(src):
        print("ERROR: markdown not found:", src)
        sys.exit(1)

    name = os.path.splitext(os.path.basename(src))[0]
    out_dir = out_dir or os.path.dirname(os.path.abspath(src))
    os.makedirs(out_dir, exist_ok=True)
    out_html = os.path.join(out_dir, name + ".html")
    out_pdf = os.path.join(out_dir, name + ".pdf")

    md = open(src, encoding="utf-8").read()

    # ---- HTML (style from report.css in this dir) ----
    css = open(os.path.join(HERE, "report.css"), encoding="utf-8").read()
    m = re.search(r"^#\s+(.+)$", md, re.M)
    title = m.group(1).strip() if m else name
    html_body = markdown(md, extensions=["tables", "fenced_code", "toc", "nl2br"])
    html_doc = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{css}</style></head>
<body><div class="wrap">{html_body}</div></body></html>"""
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print("HTML written:", out_html, os.path.getsize(out_html), "bytes")

    # ---- PDF (style from pdf_style.py in this dir) ----
    pdf_path = build_pdf(md, out_pdf)
    print("PDF written:", pdf_path, os.path.getsize(pdf_path), "bytes")


if __name__ == "__main__":
    main()
