---
name: recording-to-pdf
description: Turn any talk recording (YouTube, Zoom, AWS Summit / Corrivium livestream, or a local file) into a polished review document — Hebrew or English PDF/DOCX with the speaker's own slides extracted from the video, quotes and timestamps. Use when someone asks to summarise, write up, or "make a PDF" from a recorded session, webinar, workshop or conference talk.
---

# Recording → review pack

Produces the artefact people actually read: a sectioned document, slides
interleaved with the argument, every claim carrying a timestamp back to the
recording. First built for a 5h49m Zoom workshop (42 pages), then generalised.

## Toolchain

`ffmpeg`, `yt-dlp`, `soffice`, `pdftoppm` on PATH; Python deps live in the
skill venv (`.venv`, Python 3.12 — mlx-whisper does not build on 3.14):

```bash
python3.12 -m venv ~/.claude/skills/recording-to-pdf/.venv
~/.claude/skills/recording-to-pdf/.venv/bin/pip install mlx-whisper python-docx python-pptx pillow opencv-python-headless
```

`bin/r2r` uses that venv automatically. Override with `R2R_PY=/path/to/python`.

## Pipeline

```bash
R=~/.claude/skills/recording-to-pdf/bin/r2r
$R fetch  <url|file> work/            # -> work/rec.mp4 + work/meta.json
$R asr    work/ --lang he             # -> transcript.json/.txt/_blocks.txt
$R slides work/ --flat 0.18           # -> work/frames/{raw,kept}/ + sheet_NN.jpg
# ... you read + write content.json ...
$R render work/ --content content.json --name MyTalk_HE
```

`$R all <url> work/ --lang he` runs the first three and stops where judgement
starts. `$R list <event-url>` enumerates every session on a Corrivium/AWS
Summit event site — that is how you batch a whole conference.

### Sources

| Source | Handling |
|---|---|
| YouTube | `yt-dlp`; chapters become a free agenda; **check `--list-subs` first**, real captions skip ASR |
| Zoom | needs `--cookies-from-browser chrome`; without it yt-dlp reports "no video formats" |
| AWS Summit / Corrivium | `fetch.py` resolves site → CMS `frontend.json` → MediaConvert HLS. No login needed for the VOD manifests even when the page is gated |
| Local file / direct `.m3u8` | passed straight through |

## Stage notes that matter

**Transcription.** `mlx-whisper` large-v3-turbo, ~12× realtime on an M1 Pro.
Always pass `--lang`; auto-detect latches onto the wrong language when a talk
opens with English pre-show noise. `condition_on_previous_text=False` stops
repetition loops during silence. Read `transcript_blocks.txt` (90-second
timestamped blocks) in full — decisions are scattered and the long tail matters.

**Slides are the step that pays.** Scene detection at `--thresh 0.12` pulls one
frame per slide; dedupe by dhash removes the near-identical ones. A 25-minute
conference talk yields ~90 raw → ~55 unique in about 40 seconds. Then look at
`sheet_NN.jpg` — choosing slides is a visual job, do not skip it.

`slides.crop_all()` finds the slide rectangle inside stage furniture (the
conference production mix insets the deck) and crops to it; frames where it
finds nothing convincing pass through untouched, so the set stays whole.
For Zoom, `clean()` also paints over the camera PIP and burnt-in timestamp.

**Reconcile transcript against deck.** The slides carry facts the audio does
not, and ASR garbles domain terms and names. Verify every quote at its
timestamp before it goes in.

## Writing content.json

See `lib/schema.md`. Structure that works:

1. About + how to read + a source-accuracy disclaimer (`callout`)
2. Executive summary — bullets with a bold claim, then the evidence
3. Background sections, each opening with its slide
4. The demo or worked example, step by step, with the outcome slide
5. Code/infrastructure section
6. What to take away + an open-questions table
7. Glossary

Rules: interleave images with the argument, never append them; every quote
verbatim with `[m:ss]`; give each image a descriptive caption rather than
repeating the heading; flag uncertain names instead of asserting them.

## Hebrew / RTL

`lib/builder.py` handles three separate Word bugs that LibreOffice hides:
element order inside `w:pPr`, complex-script properties (`w:szCs`/`w:bCs`),
and `w:jc` being logical inside a bidi paragraph (emit none). Verify in Word or
Pages, not only in a LibreOffice preview. Pages default to A4.

## Verify

```bash
pdftoppm -jpeg -r 50 out/NAME.pdf /tmp/p && \
  .venv/bin/python -c "import sys;sys.path.insert(0,'lib');import slides,glob;\
  slides.sheet(sorted(glob.glob('/tmp/p-*.jpg')),'/tmp/sheet.jpg',cols=4,tw=420)"
```

Then look at every page. Watch for: blank pages after an explicit `pagebreak`
that followed a full page, images that swallow a page, orphaned headings.

## Cost

25-minute talk on an M1 Pro: fetch ~30 s, ASR ~2 min, slides ~40 s, render
~10 s. The writing is the real work.
