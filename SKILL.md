---
name: recording-to-pdf
description: Turn any talk or meeting recording (YouTube, X, AWS Summit / Corrivium livestream, a live Zoom meeting recorded on a Mac, or a local file) into a polished review document — Hebrew or English PDF/DOCX with the speaker's own slides, quotes, and for meetings the decisions and per-owner assignments plus a machine-readable record other sessions can read. Use when someone asks to record a Zoom, summarise, write up, or "make a PDF" from a recorded session, meeting, webinar, workshop or conference talk.
---

# Recording → review pack

Produces the artefact people actually read: a sectioned document, slides
interleaved with the argument, every claim traceable to the recording
(timestamps are stripped from the output by default; `--timestamps` keeps them). First built for a 5h49m Zoom workshop (42 pages), then generalised.

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
| X (Twitter) post | `yt-dlp <post-url>` works without login (`/video/1` suffix optional). Reposts are usually clipped from a YouTube talk/interview and the caption is engagement bait — misattributed speakers, invented quotes. Take title, speaker and claims from the transcript + slides only; name the original event if the frames show it, else say it is unidentified |
| Zoom | needs `--cookies-from-browser chrome`; without it yt-dlp reports "no video formats" |
| AWS Summit / Corrivium | `fetch.py` resolves site → CMS `frontend.json` → MediaConvert HLS. No login needed for the VOD manifests even when the page is gated |
| Local file / direct `.m3u8` | passed straight through |

## Stage notes that matter

**Transcription.** `mlx-whisper` large-v3-turbo, ~12× realtime on an M1 Pro.
Hebrew (`--lang he`) uses ivrit.ai's fine-tune of the same model
(`mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx`): on a real meeting it
fixed most garbled words and returned full punctuated sentences, at about the
same speed. It still misspells some names, so keep the roster prompt.
`R2R_MODEL=<hf repo>` overrides the choice.
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

**Meetings are different: use `lib/screenshare.py`, not `r2r slides`.** In a
meeting the pictures that matter are shared screens, and they hide among faces,
avatars and app chrome. `r2r slides` is tuned for decks (big scene jumps) and
dedupes whole frames, so the chrome makes different screens look identical —
on 20 Oct 2026 that left 1 picture from an hour of screen-sharing. `screenshare.py`
finds the shared-content rectangle in each frame (not dark UI, not desktop
wallpaper, edge-dense; a skin-tone check rejects camera feeds), crops to it and
dedupes on the crop:
```bash
.venv/bin/python lib/screenshare.py frames <window_jpgs_dir> work/frames   # Mac window captures
.venv/bin/python lib/screenshare.py video  work/rec.mp4      work/frames --every 5
```
Result: `work/frames/kept/ss_NNN.jpg` (+ `.txt` with the source time) and
`sheet_NN.jpg`. Same day: DevOps 1 → 5 pictures, a Meetup 3 → 10.

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
verbatim (draft with `[m:ss]`, render strips them by default); when a deck is
supplied, every slide goes in as an image next to its section; give each image a descriptive caption rather than
repeating the heading; flag uncertain names instead of asserting them.

Pictures in meetings: aim for at least one per topic where a screen was shared
(typically 5–15 per hour). Never drop a useful frame because of a toolbar, a
name strip or a corner of something private — crop it. Leave a frame out only
when the content itself is an email header with addresses, a chat panel, a
participant list or a dialog box; for an email body, crop off the
From/To/CC block and keep the body.

## Meetings (work vs. not)

A recording is a **meeting** when it is a live call among colleagues (Zoom
meeting the user joined, a forwarded meeting invite, tiles of named
participants) rather than a published talk. For meetings add the `meeting`
object to content.json (see `lib/schema.md`).

**Classify `context` yourself, don't ask:**
- `work` (+ an `org` label) when the invite addresses, the Zoom host domain
  (`<company>.zoom.us`), branding in the frames or internal system names in the
  transcript point at the user's employer. Keep the list of those signals in your
  own private notes, not in this repo.
- `personal` for the user's own non-work calls; `public` is for talks (then omit
  `meeting` entirely).

**What a meeting record must capture** (another session reads it to know what
happened): a 2–3 sentence `summary`; `decisions` as short statements;
`actions` with one row per task and a named `owner` (use the participant's
name as it appears in Zoom; "לא נקבע" when nobody took it); `due` only if said;
`open_questions`. Who said what is often unclear in ASR — attribute only when
the transcript or tile makes it clear, otherwise leave the owner as said
("הצוות של מיכל").

**Status-round meetings** (e.g. a weekly team sync over a shared Jira board):
people report roughly in the order of the board's quick-filter buttons
(left→right, or reversed on another board). Read the filter bar from a frame
and use that order to attribute each update; the name the host calls out
("איתי, בוקר טוב") anchors it. **Attribute with the speaker timeline first:**
`.venv/bin/python lib/zoom_speakers.py <win_dir> work/transcript.json <audio start HH:MM:SS> work/attributed.txt`
OCRs the green active-speaker tile in every other window capture (macOS Vision)
and writes the transcript with `<<name>>` at each change — write the per-person
table from that. For a screen recording of the Zoom app instead (any OS; OCR is
macOS Vision or Windows.Media.Ocr):
`python lib/zoom_speakers.py video work/rec.mp4 work/transcript.json work/attributed.txt --self "<recorder's Zoom name>"`
reads the green-bordered tile (gallery / filmstrip during a share) or the big
tile's label (speaker view) every second; `--self` drops the recorder's own tile.
Re-run ASR with `initial_prompt` = participant names + domain
terms and `no_speech_threshold=0.9`; the default pass silently drops stretches.
When in doubt, check the Zoom frames at that moment: the active speaker's tile
has a green border (frame time = recording start + transcript offset). The person
called on is not always the one who answers. Ask the user who was absent before
attributing by board order. If you keep a roster of correct name spellings,
check it before writing names.

**Who said it — rules that catch the common mistakes:**
- A name at the start of a turn ("Dana, Yossi?") is usually who is being
  *addressed*, not who speaks. Take the speaker from the timeline/green tile.
- First-person statements ("I'm on vacation Sunday–Monday", "I'll send it",
  "my team") belong to the person actually speaking — never to the name
  mentioned just before.
- `<<Name?>>` (with `?`) is a guess carried over from the last seen tile.
  Check the frames at that offset before attributing anything personal
  (absence, ownership, an opinion) to that person.
- The user who recorded the meeting is a participant too; their own updates
  get attributed to them like anyone else's.
  Their own tile is often missing from the strip (self-view hidden), so when
  they talk there is no green tile and the timeline shows the previous speaker
  with `?`. A `?` run that answers a question put to someone else is often the user.

**People file (private).** A people file says who is who: canonical full name, Zoom display name,
English spelling, `gender`, nicknames/ASR misspellings (`aka`), team, role and
what they work on. Format: `examples/people.example.md`. It holds real
colleagues' details, so keep it **outside any repo** and point
`R2R_PEOPLE` at it (`export R2R_PEOPLE=~/path/to/PEOPLE.md`). Then:
- `r2r asr` passes every name + `aka` as whisper's `initial_prompt`;
- `zoom_speakers.py` maps OCR'd tile names to the canonical name.

When writing, read your private people file and use it:
- **Gender** drives Hebrew verb/adjective agreement (סיפר/סיפרה, הציע/הציעה).
  Never infer gender from a name; if it's `?` or the person isn't listed,
  phrase neutrally ("לדברי X", "X: ...").
- **Role / works on** resolve who an update or topic belongs to when ASR is
  unclear (the portal migration update is Yossi's, not whoever was called).
- **Spelling**: write the canonical name, not the ASR's version.

**Context file (private, optional).** Next to the people file you can keep a
context file for a recurring meeting: a glossary of internal systems and terms
(with the ASR's usual misspellings), the running topics with owner and status,
and key dates. Read it before writing; it fixes names of systems, items and
numbers the transcript garbles. The meeting wins when they conflict. To keep it
current, put proposed changes in `meeting.context_updates` (strings, or
`{item, old, new, date, source}`); `render` copies them to `record.json` and
`context_updates.md` so a later session can apply them. Keep it outside any repo.

**Render with an index:**
```bash
$R render work/ --content content.json --name NAME --index reviews/INDEX.md
```
This writes `work/out/record.json` + `record.md` next to the PDF and upserts
one row in `INDEX.md` (date · context · title · #actions · record path), so
other sessions can find what was decided.

Meeting recordings and reviews are private material: keep them outside any
public repo, and don't send them anywhere the user didn't name.

## Recording a live Zoom on a Mac

Once the user is in the meeting, one command does everything below:

```bash
lib/zoom_record.sh start [--lang he]   # new ~/Documents/r2r-work/zoom-YYYYMMDD-HHMM, OBS + window frames, audio check at 35 s
lib/zoom_record.sh check               # health check of the latest recording; run every 3 min
```

It refuses to start without a meeting (no `CptHost`). It closes OBS, rewrites the
R2R profile and scene to point at the new folder, and records Zoom app audio,
the default mic (Zoom's output never has the user's own voice) and Zoom app
video at 1080p/5 fps. That video is the backup for slides if the window frames fail:
`screenshare.py video`. It also starts `zoom_wincap.sh`. `check` prints
OK/FAIL for frames, OBS and audio, with what Whisper heard in the last 30 s.
It refuses while OBS is already running (quitting it would lose a recording in
progress); `--force` overrides. On speakers use `--no-mic`: the mic also hears Zoom,
so everyone else would be recorded twice.

- Audio: OBS (`open -a OBS --args --startrecording --minimize-to-tray`), source
  "macOS Screen Capture" in **application mode on Zoom** (scene JSON:
  `type: 2, application: "us.zoom.xos"`), Capture Audio on. Display mode can
  come back black with near-silent audio (≈ −42 dB flat).
- **Verify by transcribing, not by volume:** after ~30 s, cut the last 30 s and
  run mlx-whisper on it. Silence comes back as "תודה רבה." or gibberish; good
  meeting audio sits around −22 dB mean. Do this check again once people
  actually start talking.
- Picture: capture the **Zoom Meeting window**, not the screen, so the user can
  keep working — `screencapture -x -o -l<windowid> -t jpg` every 3 s, window id
  from `CGWindowListCopyWindowInfo` (owner `zoom.us`, name "Zoom Meeting",
  layer 0), re-resolved every minute — `lib/zoom_wincap.sh <scratch> <rec_dir>`
  with `lib/zoom_window.swift` does exactly this. Works while covered; fails only if
  minimised. Feed those JPEGs to `lib/screenshare.py frames` (see above), not
  `r2r slides`.
- End trigger: poll `pgrep CptHost` (Zoom's in-meeting process). Never use
  System Events window lists — Accessibility can be revoked mid-meeting.
- Health check every 3 min (frames growing, OBS up, audio not silent) and tell
  the user immediately if one fails. `<rec_dir>/wincap.log` records every window
  switch and failed capture. Zoom keeps unnamed windows parked off-display and
  titles the meeting window just "Zoom" while viewing a share, so a picker that
  ignores either one captures nothing. Don't filter on `kCGWindowIsOnscreen`: it is false
  for a full-screen meeting on another Space, which `screencapture -l` still captures.
- OBS traps: a quit leaves a crash sentinel → next launch blocks on a dialog;
  delete `~/Library/Application Support/obs-studio/.sentinel/*` first. Edit the
  scene JSON only with OBS closed (it overwrites on exit).

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
