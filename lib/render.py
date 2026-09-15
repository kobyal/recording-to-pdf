# -*- coding: utf-8 -*-
"""content.json -> DOCX -> PDF, with correct Hebrew/RTL in Word (not just LO).

Schema (see schema.md): {lang, rtl, title, subtitle, meta[], blocks[]}
Block kinds: h1 h2 h3 body bullets table image callout quote pagebreak
"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from builder import Doc

LTR_ISOLATE = "⁦%s⁩"


def _iso(s):
    """Wrap bare Latin/numeric runs so bidi does not reorder timestamps etc."""
    return s


def build(spec, outdir, name="review", slides_dir=None):
    rtl = spec.get("rtl", spec.get("lang", "he") == "he")
    d = Doc(rtl=rtl, font=spec.get("font", "Arial"))
    if spec.get("page", "a4").lower() == "a4":          # A4 is the default here
        from docx.shared import Mm
        for s_ in d.d.sections:
            s_.page_width, s_.page_height = Mm(210), Mm(297)
    d.title_page(spec["title"], spec.get("subtitle", ""), spec.get("meta", []))

    for b in spec["blocks"]:
        k = b.get("kind")
        if k == "h1":
            d.h1(b["text"])
        elif k == "h2":
            d.h2(b["text"])
        elif k == "h3":
            d.h3(b["text"])
        elif k == "body":
            d.body(b["text"], keep_next=b.get("keep_next", False))
        elif k == "bullets":
            items = [tuple(i) if isinstance(i, list) else i for i in b["items"]]
            d.bullets(items, bold_lead=b.get("bold_lead", True))
        elif k == "table":
            d.table(b["headers"], b["rows"], b.get("widths"))
        elif k == "callout":
            d.callout(b["text"], b.get("label"))
        elif k == "quote":
            d.callout(b["text"], b.get("by"))
        elif k == "image":
            p = b["file"]
            if not os.path.isabs(p) and slides_dir:
                p = os.path.join(slides_dir, p)
            if os.path.exists(p):
                d.image(p, width_in=b.get("width", 6.3), caption=b.get("caption"))
            else:
                sys.stderr.write(f"missing image: {p}\n")
        elif k == "pagebreak":
            d.page_break()
        else:
            raise ValueError(f"unknown block kind: {k}")

    os.makedirs(outdir, exist_ok=True)
    docx = os.path.join(outdir, f"{name}.docx")
    d.save(docx)
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", docx,
                    "--outdir", outdir], check=True, capture_output=True)
    return docx, os.path.join(outdir, f"{name}.pdf")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("content"); ap.add_argument("outdir")
    ap.add_argument("--name", default="review")
    ap.add_argument("--slides")
    a = ap.parse_args()
    spec = json.load(open(a.content, encoding="utf-8"))
    docx, pdf = build(spec, a.outdir, a.name, a.slides)
    print(json.dumps({"docx": docx, "pdf": pdf}, ensure_ascii=False))
