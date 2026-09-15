# content.json

```jsonc
{
  "lang": "he",              // he | en ...
  "rtl": true,               // default: lang == "he"
  "title": "...",
  "subtitle": "...",
  "meta": ["speaker · date", "duration · source"],
  "blocks": [
    {"kind": "h1",   "text": "1. תקציר מנהלים"},
    {"kind": "body", "text": "פסקה.\n\nפסקה שנייה."},
    {"kind": "bullets", "items": [["מוביל: ", "שאר המשפט"], "פריט רגיל"]},
    {"kind": "table", "headers": ["זמן","נושא"], "rows": [["0:00","פתיחה"]],
                      "widths": [1.2, 5.0]},
    {"kind": "image", "file": "k_012.png", "caption": "...", "width": 6.3},
    {"kind": "callout", "text": "...", "label": "שימו לב"},
    {"kind": "quote", "text": "ציטוט", "by": "— שם"},
    {"kind": "pagebreak"}
  ]
}
```

Rules that keep the document good:
- Interleave `image` blocks with the argument; never dump them in an appendix.
- Every quote must exist verbatim in the transcript; cite `[h:mm:ss]` in the body.
- Bold lead on bullets carries the claim, the rest carries the evidence.
- Open with: about + disclaimer, then executive summary, then detail, then actions.
