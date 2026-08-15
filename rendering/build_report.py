# -*- coding: utf-8 -*-
"""Generic renderer: any trail-race-strategy Markdown -> fixed-style HTML + PDF.

This is the ONLY entry point. It reads the Markdown produced by the
trail-race-strategist skill (or any compatible MD), then renders it with the
fixed visual style defined in this directory (style-spec.md + report.css +
pdf_style.py). It does NOT modify any skill file.

Usage:
    python build_report.py <report.md> [--out-dir DIR]

Outputs:
    <name>.html  and  <name>.pdf.  The output directory is selected in this
    order: --out-dir, TRAIL_RACE_OUTPUT_DIR, then the Markdown source folder.

The style assets (report.css, pdf_style.py) are loaded from THIS script's own
directory, so it works no matter where the Markdown lives or where you call it.
"""
import os
import sys
import re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def resolve_output_directory(
    source: str,
    arguments: list[str],
    environ: dict[str, str] | None = None,
) -> str:
    """Return a portable output directory without inventing a machine path."""
    values: list[str] = []
    for index, token in enumerate(arguments):
        if token != "--out-dir":
            continue
        if index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
            raise ValueError("--out-dir requires a writable directory path")
        values.append(arguments[index + 1])
    if len(values) > 1:
        raise ValueError("--out-dir may be supplied only once")

    environment = os.environ if environ is None else environ
    candidate = values[0] if values else environment.get("TRAIL_RACE_OUTPUT_DIR")
    if candidate is None:
        candidate = os.path.dirname(os.path.abspath(source))
    if not candidate.strip():
        raise ValueError("output directory is empty")

    resolved = os.path.abspath(os.path.expanduser(candidate))
    if os.path.exists(resolved) and not os.path.isdir(resolved):
        raise ValueError(f"output path is not a directory: {resolved}")
    return resolved


def main():
    if len(sys.argv) < 2:
        print("usage: python build_report.py <report.md> [--out-dir DIR]")
        sys.exit(1)

    src = sys.argv[1]
    if not os.path.exists(src):
        print("ERROR: markdown not found:", src)
        sys.exit(1)

    name = os.path.splitext(os.path.basename(src))[0]
    try:
        out_dir = resolve_output_directory(src, sys.argv[2:])
        os.makedirs(out_dir, exist_ok=True)
    except (OSError, ValueError) as exc:
        print("ERROR: cannot use output directory:", exc)
        sys.exit(1)

    from markdown import markdown
    from pdf_style import build_pdf  # noqa: E402
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
