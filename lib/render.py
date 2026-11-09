# -*- coding: utf-8 -*-
"""content.json -> DOCX -> PDF, with correct Hebrew/RTL in Word (not just LO).

Schema (see schema.md): {lang, rtl, title, subtitle, meta[], blocks[]}
Block kinds: h1 h2 h3 body bullets table image callout quote pagebreak
"""
import json, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from builder import Doc

LTR_ISOLATE = "⁦%s⁩"


def _iso(s):
    """Wrap bare Latin/numeric runs so bidi does not reorder timestamps etc."""
    return s


TS = re.compile(r'\s*\[\d{1,2}:\d{2}(?::\d{2})?(?:[–-]\d{1,2}:\d{2}(?::\d{2})?)?'
                r'(?:,\s*\d{1,2}:\d{2}(?::\d{2})?(?:[–-]\d{1,2}:\d{2}(?::\d{2})?)?)*\]')
TIME_HEADERS = {"זמן", "time", "Time", "timestamp", "Timestamp"}


def _strip(s):
    return TS.sub("", s).replace(" .", ".").replace(" ,", ",") if isinstance(s, str) else s


def strip_timestamps(blocks):
    """Default output has no [m:ss] references and no time columns."""
    for b in blocks:
        for k in ("text", "by", "caption"):
            if k in b:
                b[k] = _strip(b[k])
        if b.get("kind") == "quote" and b.get("by", "").strip() in ("—", "-", ""):
            b["by"] = ""
        if b.get("kind") == "bullets":
            b["items"] = [[_strip(x) for x in i] if isinstance(i, list) else _strip(i)
                          for i in b["items"]]
        if b.get("kind") == "table":
            keep = [i for i, h in enumerate(b["headers"]) if h.strip() not in TIME_HEADERS]
            if len(keep) < len(b["headers"]):
                b["headers"] = [b["headers"][i] for i in keep]
                b["rows"] = [[r[i] for i in keep] for r in b["rows"]]
                if b.get("widths"):
                    w = [b["widths"][i] for i in keep]
                    b["widths"] = [x * 7.0 / sum(w) for x in w]
            b["rows"] = [[_strip(c) for c in r] for r in b["rows"]]
    return blocks


MEETING_LABELS = {
    "he": {"work": "פגישת עבודה – פנימי", "personal": "פגישה – אישי", "public": "תוכן ציבורי",
           "actions": "משימות לפי אחראי", "owner": "אחראי", "task": "משימה",
           "due": "יעד", "status": "סטטוס", "decisions": "החלטות"},
    "en": {"work": "Work meeting – internal", "personal": "Meeting – personal",
           "public": "Public content", "actions": "Assignments by owner", "owner": "Owner",
           "task": "Task", "due": "Due", "status": "Status", "decisions": "Decisions"},
}


def meeting_blocks(spec):
    """Banner + decisions + per-owner assignments, generated from spec['meeting']."""
    m = spec.get("meeting")
    if not m:
        return [], []
    L = MEETING_LABELS.get(spec.get("lang", "he"), MEETING_LABELS["en"])
    ctx = m.get("context", "work")
    label = L.get(ctx, ctx)
    if m.get("org"):
        label += f" · {m['org']}"
    head = [{"kind": "callout", "label": label, "text": m.get("banner",
             "מסמך פנימי – לא להפצה מחוץ למשתתפים." if spec.get("lang", "he") == "he"
             else "Internal document – do not distribute outside the participants.")}]
    tail = []
    if m.get("decisions"):
        tail += [{"kind": "h1", "text": L["decisions"]},
                 {"kind": "bullets", "bold_lead": False, "items": m["decisions"]}]
    acts = m.get("actions", [])
    if acts:
        tail.append({"kind": "h1", "text": L["actions"]})
        owners = []
        for a in acts:
            if a.get("owner", "") not in owners:
                owners.append(a.get("owner", ""))
        for o in owners:
            mine = [a for a in acts if a.get("owner", "") == o]
            tail.append({"kind": "h2", "text": o or "—"})
            tail.append({"kind": "table", "headers": [L["task"], L["due"], L["status"]],
                         "widths": [4.6, 1.2, 1.2],
                         "rows": [[a.get("task", ""), a.get("due", ""), a.get("status", "")]
                                  for a in mine]})
    return head, tail


def write_record(spec, outdir, name, pdf, index=None):
    """Machine-readable meeting record for other sessions: record.json + record.md + INDEX."""
    m = spec.get("meeting")
    if not m:
        return None
    rec = {"title": spec.get("title"), "date": m.get("date"), "kind": "meeting",
           "context": m.get("context", "work"), "org": m.get("org"),
           "participants": m.get("participants", []), "summary": m.get("summary", ""),
           "decisions": m.get("decisions", []), "actions": m.get("actions", []),
           "open_questions": m.get("open_questions", []), "pdf": os.path.abspath(pdf)}
    if m.get("context_updates"):  # proposed edits to a private context file, applied by a later session
        rec["context_updates"] = m["context_updates"]
        open(os.path.join(outdir, "context_updates.md"), "w", encoding="utf-8").write(
            "# Proposed context updates\n\n" + "\n".join(
                f"- {u}" if isinstance(u, str) else
                f"- {u.get('item','')}: {u.get('old','')} → {u.get('new','')} ({u.get('date','')}, {u.get('source','')})"
                for u in m["context_updates"]) + "\n")
    rj = os.path.join(outdir, "record.json")
    json.dump(rec, open(rj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = [f"# {rec['title']}", "",
          f"- date: {rec['date']}", f"- context: {rec['context']}" + (f" ({rec['org']})" if rec['org'] else ""),
          f"- participants: {', '.join(rec['participants'])}", f"- pdf: {rec['pdf']}", ""]
    if rec["summary"]:
        md += ["## Summary", rec["summary"], ""]
    if rec["decisions"]:
        md += ["## Decisions"] + [f"- {d}" for d in rec["decisions"]] + [""]
    if rec["actions"]:
        md += ["## Actions", "| owner | task | due | status |", "|---|---|---|---|"]
        md += [f"| {a.get('owner','')} | {a.get('task','')} | {a.get('due','')} | {a.get('status','')} |"
               for a in rec["actions"]] + [""]
    if rec["open_questions"]:
        md += ["## Open questions"] + [f"- {q}" for q in rec["open_questions"]] + [""]
    open(os.path.join(outdir, "record.md"), "w", encoding="utf-8").write("\n".join(md))
    if index:
        line = (f"| {rec['date']} | {rec['context']} | {rec['title']} | "
                f"{len(rec['actions'])} | {os.path.abspath(rj)} |")
        rows = []
        if os.path.exists(index):
            rows = [l for l in open(index, encoding="utf-8").read().splitlines()
                    if l.startswith("| ") and not l.startswith("| date") and os.path.abspath(rj) not in l]
        rows.append(line)
        rows.sort(reverse=True)
        open(index, "w", encoding="utf-8").write(
            "# Meeting index\n\nOne row per reviewed meeting. Read the record.json for "
            "decisions and per-owner actions.\n\n| date | context | title | actions | record |\n"
            "|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    return rj


def build(spec, outdir, name="review", slides_dir=None, timestamps=None):
    spec = json.loads(json.dumps(spec))               # never mutate the caller's copy
    head, tail = meeting_blocks(spec)
    spec["blocks"] = head + spec["blocks"] + tail
    if not (timestamps if timestamps is not None else spec.get("timestamps", False)):
        strip_timestamps(spec["blocks"])
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
    pdf = os.path.join(outdir, f"{name}.pdf")
    if shutil.which("soffice"):
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", docx,
                        "--outdir", outdir], check=True, capture_output=True)
    else:
        # Windows without LibreOffice (locked-down PCs): Word does the conversion
        ps = ("$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
              f"$d = $w.Documents.Open('{os.path.abspath(docx)}', $false, $true); "
              f"$d.SaveAs2('{os.path.abspath(pdf)}', 17); $d.Close($false); $w.Quit()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)
    return docx, pdf


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("content"); ap.add_argument("outdir")
    ap.add_argument("--name", default="review")
    ap.add_argument("--slides")
    ap.add_argument("--timestamps", action="store_true",
                    help="keep [m:ss] references and time columns (default: strip)")
    ap.add_argument("--index", default=os.environ.get("R2R_INDEX"),
                    help="meeting index (INDEX.md) to update; default $R2R_INDEX")
    a = ap.parse_args()
    spec = json.load(open(a.content, encoding="utf-8-sig"))
    docx, pdf = build(spec, a.outdir, a.name, a.slides, True if a.timestamps else None)
    rec = write_record(spec, a.outdir, a.name, pdf, a.index)
    print(json.dumps({"docx": docx, "pdf": pdf, "record": rec}, ensure_ascii=False))
