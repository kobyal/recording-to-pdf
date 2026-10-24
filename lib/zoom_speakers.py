# -*- coding: utf-8 -*-
"""Speaker timeline for a Zoom meeting.

  python zoom_speakers.py <win_dir> <transcript_segments.json> <audio_start HH:MM:SS> <out.txt>
  python zoom_speakers.py video <recording.mp4> <transcript.json> <out.txt> [--every 1] [--self "Name,Name"]

Window mode (macOS): window JPEGs named HHMMSS.jpg. Finds the green
active-speaker border in the tile strip of each frame, OCRs the name with
macOS Vision (ocr_tiles.swift).

Video mode (any OS): a screen recording of the Zoom app. Every second it
reads the name label of the green-bordered tile (gallery / filmstrip during a
share), or of the big video tile in speaker view. OCR is macOS Vision on a Mac
and Windows.Media.Ocr (ocr_tiles.ps1) on Windows. --self names the recorder's
own tile, which never counts as a speaker.

Both write the transcript with a <<speaker>> marker at every change. Names
ending in "?" were inferred from the nearest earlier run, not seen in a frame.
With R2R_PEOPLE set, tile names are mapped to the people file's canonical names.
"""
import difflib, glob, json, os, re, subprocess, sys, tempfile
import numpy as np
from PIL import Image
from people import load, canonical

HERE = os.path.dirname(os.path.abspath(__file__))


def tiles(win_dir, out_dir, step=2):
    for f in sorted(glob.glob(win_dir + "/*.jpg"))[::step]:
        im = Image.open(f).convert("RGB"); w, h = im.size
        top = int(h * .04); strip = np.asarray(im.crop((0, top, w, int(h * .22)))).astype(int)
        g = (strip[:, :, 1] > 150) & (strip[:, :, 1] - strip[:, :, 0] > 60) & (strip[:, :, 2] < 160)
        cc = g.sum(0)
        if cc.max() < 30:                      # no vertical green edge = no active tile
            continue
        cols = np.where(cc > cc.max() * 0.7)[0]    # relative: works at any window size
        if len(cols) < 2 or not w * .04 < cols.max() - cols.min() < w * .3:
            continue
        x0, x1 = cols.min(), cols.max()
        rows = np.where(g[:, x0:x1].sum(1) > (x1 - x0) * 0.5)[0]
        y0, y1 = (rows.min(), rows.max()) if len(rows) >= 2 else (0, strip.shape[0] - 1)
        im.crop((x0, top + y0, x1, top + y1)).save(os.path.join(out_dir, os.path.basename(f)))


def _ocr_run(img_dir):
    if sys.platform == "win32":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               os.path.join(HERE, "ocr_tiles.ps1"), img_dir]
    else:
        cmd = ["swift", os.path.join(HERE, "ocr_tiles.swift"), img_dir]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8").stdout
    res = {}
    for l in out.splitlines():
        f, _, text = l.strip().partition(" ")
        res[f] = [x.strip() for x in text.split(" | ") if x.strip()]
    return res


def ocr(img_dir):
    """{file name: [text lines]} for every .jpg in img_dir."""
    res = _ocr_run(img_dir)
    if sys.platform == "win32":
        # Windows OCR reads some labels only at 2x and loses others at 2x: read both, keep both
        big = os.path.join(img_dir, "x2"); os.makedirs(big, exist_ok=True)
        for f in glob.glob(os.path.join(img_dir, "*.jpg")):
            im = Image.open(f)
            im.resize((im.width * 2, im.height * 2), Image.LANCZOS).save(os.path.join(big, os.path.basename(f)), quality=95)
        for f, lines in _ocr_run(big).items():
            res[f] = res.get(f, []) + lines
    return res


def speaker_at(runs, gap=4):
    """t -> name seen within gap seconds, else the previous name + "?"."""
    def who(t):
        prev, near = None, None
        for a, b, n in runs:
            d = max(a - t, 0, t - b)                   # 0 inside the run
            if d <= gap and (near is None or d < near[0] or (d == near[0] and a > t)):
                near = (d, n)
            if b < t:
                prev = n
        return near[1] if near else (prev or "?") + "?"
    return who


def write_attributed(segments, runs, out, gap=4):
    """Transcript with <<name>> at every change. runs: [start, end, name] in seconds."""
    who = speaker_at(runs, gap)

    pieces = []        # (start, name, text): long segments are split where the speaker changes
    for sg in segments:
        s, e, text = sg["start"], sg["end"], sg["text"].strip()
        if sg.get("words"):
            for wd in sg["words"]:
                pieces.append((wd["start"], who((wd["start"] + wd["end"]) / 2), wd["word"].strip()))
            continue
        marks = [(s, who(s + min(1.5, (e - s) / 2)))]
        t = s + 2
        while t < e - 1:
            n = who(t)
            if n != marks[-1][1] and not n.endswith("?"):
                marks.append((t, n))
            t += 1
        words = text.split()
        for i, (t, n) in enumerate(marks):     # no word times: split the text by elapsed time
            nxt = marks[i + 1][0] if i + 1 < len(marks) else e
            a = round(len(words) * (t - s) / max(e - s, 1e-6))
            b = round(len(words) * (nxt - s) / max(e - s, 1e-6))
            if words[a:b]:
                pieces.append((t, n, " ".join(words[a:b])))
    parts, cur = [], None
    for t, n, text in pieces:
        if n != cur:
            parts.append(f"\n[{int(t)//60}:{int(t)%60:02d}] <<{n}>>"); cur = n
        parts.append(text)
    open(out, "w", encoding="utf-8").write(" ".join(parts))


def main(win_dir, seg_json, start, out):
    tmp = tempfile.mkdtemp()
    tiles(win_dir, tmp)
    ocr = subprocess.run(["swift", os.path.join(HERE, "ocr_tiles.swift"), tmp],
                         capture_output=True, text=True).stdout
    h, m, s = map(int, start.split(":")); t0 = h * 3600 + m * 60 + s
    names = canonical(load())
    runs = []
    for l in ocr.splitlines():
        f, _, name = l.strip().partition(" ")
        name = re.sub(r"@.*", "", name.split(" | ")[-1]).replace("...", "").strip()
        name = names.get(name.lower(), name)
        t = int(f[:2]) * 3600 + int(f[2:4]) * 60 + int(f[4:6]) - t0
        if not name or t < -5:
            continue
        if runs and runs[-1][2] == name and t - runs[-1][1] <= 15:
            runs[-1][1] = t
        else:
            runs.append([t, t, name])
    segs = json.load(open(seg_json))
    write_attributed(segs["segments"] if isinstance(segs, dict) else segs, runs, out)
    print(" -> ".join(dict.fromkeys(n for a, b, n in runs if b - a >= 6)))


# ---------- video mode ----------

def green_tile(a):
    """(x0, y0, x1, y1) of the green active-speaker border in a full frame, or None."""
    import cv2
    h, w = a.shape[:2]
    g = ((a[..., 1] > 150) & (a[..., 1] - a[..., 0] > 60) & (a[..., 2] < 160)).astype(np.uint8)
    if g.sum() < 50:
        return None
    blobs = cv2.morphologyEx(g, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    g = g & ~cv2.dilate(blobs, np.ones((3, 3), np.uint8))   # drop filled shapes (green avatars), keep lines
    g = cv2.dilate(g, np.ones((9, 9), np.uint8))     # compression breaks the thin line at the round corners
    n, _, st, _ = cv2.connectedComponentsWithStats(g, 8)
    # border pieces split at the corners (or doubled mid-animation): merge boxes that touch
    boxes = [[x, y, x + bw, y + bh] for x, y, bw, bh, _ in st[1:] if bw > w * .02 or bh > h * .02]
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a0, b0 = boxes[i], boxes[j]
                if a0[0] - 12 <= b0[2] and b0[0] - 12 <= a0[2] and a0[1] - 12 <= b0[3] and b0[1] - 12 <= a0[3]:
                    boxes[i] = [min(a0[0], b0[0]), min(a0[1], b0[1]), max(a0[2], b0[2]), max(a0[3], b0[3])]
                    del boxes[j]; merged = True; break
            if merged:
                break
    best = None
    for x0, y0, x1, y1 in boxes:
        bw, bh = x1 - x0, y1 - y0
        if not (w * .04 < bw < w * .6 and 1.1 < bw / max(bh, 1) < 2.5):
            continue
        box = g[y0:y1, x0:x1]
        if box.mean() > .45:                          # filled green = content, not a border
            continue
        sides = (box[:10].max(0).mean(), box[-10:].max(0).mean(),
                 box[:, :10].max(1).mean(), box[:, -10:].max(1).mean())
        # a closed rectangle; one vertical edge may fade where it crosses bright video
        if min(sides[:2]) < .8 or max(sides[2:]) < .8 or min(sides[2:]) < .3:
            continue
        if best is None or bw * bh > (best[2] - best[0]) * (best[3] - best[1]):
            best = (int(x0), int(y0), int(x1), int(y1))
    return best


def main_tile(a):
    """(x0, y0, x1, y1) of the big video tile in speaker view, or None."""
    h, w = a.shape[:2]
    lit = a.max(2) > 14                               # tiles are dark grey or video; the window is black
    y_lo, y_hi = int(h * .03), int(h * .955)          # under the title bar, above the taskbar
    cols = np.where(lit[y_lo:y_hi].mean(0) > .5)[0]
    if len(cols) < w * .3:
        return None
    x0, x1 = cols.min(), cols.max()
    rows = lit[y_lo:y_hi, x0:x1].mean(1) > .6
    best, run = (0, 0), None                          # longest run of lit rows = the tile
    for i, r in enumerate(list(rows) + [False]):
        if r and run is None:
            run = i
        elif not r and run is not None:
            if i - run > best[1] - best[0]:
                best = (run, i)
            run = None
    y0, y1 = y_lo + best[0], y_lo + best[1]
    if y1 - y0 < h * .3:
        return None
    return int(x0), int(y0), int(x1), int(y1)


def label_crop(img, box):
    """The name label in the bottom-left corner of a tile, enlarged for OCR."""
    x0, y0, x1, y1 = box
    w, h = img.size
    lh = int(h * .045)                                   # label bar ~3.5% of the screen height
    c = img.crop((x0 + 1, max(y0, y1 - lh), min(x1, x0 + int(w * .3)), y1 - 1))
    k = max(1.0, 96 / max(c.size[1], 1))                 # text ~40 px tall for the OCR
    return c.resize((int(c.size[0] * k), int(c.size[1] * k)), Image.LANCZOS)


def clean(line):
    line = re.sub(r"@\S*", "", line)                     # "first.last@company.com" -> "first.last"
    line = re.sub(r"\((guest|host|co-host|me)\)", "", line, flags=re.I)
    line = re.sub(r"^[^A-Za-z֐-׿]+", "", line)  # mic / signal icons read as symbols
    line = line.replace("•", "-")                   # Windows OCR reads "-" in names as a bullet
    return re.sub(r"\s+", " ", line.replace("...", "")).strip(" .-|:;,'\"")


def sample(video, every, tmp):
    """Label crops of the active tile every `every` s. Returns (crops dir, {crop: (s, kind)},
    {crop: earlier crop that looks the same}) - only changed labels need OCR."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", video, "-vf", f"fps=1/{every}",
                    "-q:v", "2", os.path.join(tmp, "f_%06d.jpg")], check=True)
    crops = os.path.join(tmp, "crops"); os.makedirs(crops)
    kinds, same, last = {}, {}, {}
    for i, f in enumerate(sorted(glob.glob(os.path.join(tmp, "f_*.jpg")))):
        img = Image.open(f).convert("RGB"); a = np.asarray(img).astype(np.int16)
        box, kind = green_tile(a), "g"
        if box is None:              # speaker view (or a share: its text rarely matches a name)
            box, kind = main_tile(a), "m"
        if box:
            name = f"{i:06d}_{kind}.jpg"
            c = label_crop(img, box)
            th = np.asarray(c.convert("L").resize((96, 12))).astype(np.int16)
            prev = last.get(kind)
            kinds[name] = ((i + .5) * every, kind)     # ffmpeg's fps filter picks mid-interval frames
            if prev and np.abs(np.subtract(box, prev[2])).max() <= 4 and np.abs(th - prev[1]).mean() < 6:
                same[name] = prev[0]
            else:
                c.save(os.path.join(crops, name), quality=95)
                last[kind] = (name, th, box)
        os.remove(f)
    return crops, kinds, same


def video_main(video, seg_json, out, every=1, self_names=""):
    tmp = tempfile.mkdtemp()
    crops, kinds, same = sample(video, every, tmp)
    seen = ocr(crops)
    for f, g in same.items():
        seen[f] = seen.get(g, [])
    segs = json.load(open(seg_json, encoding="utf-8"))
    segs = segs["segments"] if isinstance(segs, dict) else segs
    stats = attribute(kinds, seen, segs, out, every, self_names)
    stats["ocr_calls"] = len(kinds) - len(same)
    stats.pop("runs")
    print(json.dumps(stats, ensure_ascii=False))


def attribute(kinds, seen, segs, out, every=1, self_names=""):
    """kinds: {crop file: (seconds, "g"|"m")}, seen: {crop file: OCR lines} -> writes out, returns stats."""
    alias = canonical(load())
    selfs = {s.strip().lower() for s in self_names.split(",") if s.strip()}
    raw = {f: [c for c in map(clean, seen.get(f, [])) if 2 <= len(c) <= 48] for f in kinds}

    def score(line, key):
        """Similarity of an OCR'd label to a name; tolerates a leading icon read as letters
        and an e-mail domain whose '@' was misread."""
        best = 0
        for v in {line, line[1:], line[2:], line.partition(" ")[2]}:
            best = max(best, difflib.SequenceMatcher(None, v, key).ratio())
            if len(key) >= 8:
                best = max(best, difflib.SequenceMatcher(None, v[:len(key)], key).ratio())
            if len(v) >= 4 and key.startswith(v):
                best = max(best, .79)                  # label cut short; needs a clear margin to count
        return best

    def match(line, keys, cut=.8, margin=True):
        """Best key at >= cut, or (margin) a weaker one (>= .6) that clearly beats the runner-up."""
        k = line.lower()
        hits = sorted(((score(k, x), x) for x in keys), reverse=True)
        if not hits:
            return None
        second = hits[1][0] if len(hits) > 1 else 0
        if hits[0][0] >= cut or (margin and hits[0][0] >= .6 and hits[0][0] - second >= .2):
            return hits[0][1]
        return None

    # roster: people-file aliases + other names read on a green tile in 8+ frames (clustered by
    # similarity). Only green tiles: a big-tile crop may be a shared screen, whose text is not a name.
    roster = dict(alias)
    first0 = {a.split()[0].split(".")[0] for a in list(alias) + list(selfs)}
    groups = []
    for f, lines in raw.items():
        if kinds[f][1] != "g":
            continue
        for l in lines:
            k = l.lower()
            if match(k, list(roster) + list(selfs), .65) or k in first0:
                continue                               # a known name, or an OCR misread of one
            for g in groups:
                if score(k, g[0]) >= .7 or score(g[0], k) >= .7:
                    g.append(k); break
            else:
                groups.append([k])
    groups.sort(key=len, reverse=True)                 # biggest first: misreads join the real name
    for g in groups:
        if len(g) < 8:                                 # under ~8 s on the green tile: OCR noise
            continue
        top = max(set(g), key=g.count)
        if not match(top, list(roster), .7):
            roster[top] = top

    first = {}                                         # first name -> people with it
    for key, n in roster.items():
        first.setdefault(key.split()[0].split(".")[0], set()).add(n)

    def resolve(line):
        k = line.lower()
        if match(k, selfs, .85, False):                       # the recorder's own tile is never a speaker
            return None
        hit = match(k, list(roster))
        if hit:
            return roster[hit]
        if " " not in k and len(k) >= 4 and len(first.get(k, ())) == 1:   # label cut to a first name
            return next(iter(first[k]))
        return None

    obs = []
    for f in sorted(kinds):
        t, kind = kinds[f]
        if any(match(l.lower(), selfs, .85, False) for l in raw[f]):
            continue                                   # the recorder's own tile (alone / not maximised)
        names = [n for n in map(resolve, raw[f]) if n]
        if names:
            obs.append((t, names[-1], kind))
    runs = []
    for t, n, _ in obs:
        if runs and runs[-1][2] == n and t - runs[-1][1] <= max(every * 4, 6):
            runs[-1][1] = t
        else:
            runs.append([t, t, n])
    write_attributed(segs, runs, out, gap=every + 1)
    who = speaker_at(runs, every + 1)
    secs = [who(t + .5) for s in segs for t in range(int(s["start"]), int(s["end"]))]
    return {"frames": int(max([t for t, _ in kinds.values()] + [0]) / every) + 1,
            "labelled": len(obs), "green": sum(k == "g" for _, _, k in obs),
            "speech_seen": round(sum(not n.endswith("?") for n in secs) / max(len(secs), 1), 3),
            "speakers": list(dict.fromkeys(n for a, b, n in runs if b - a >= every * 2)),
            "runs": runs}


if __name__ == "__main__":
    if sys.argv[1] == "video":
        av = sys.argv[2:]
        opt = lambda k, d: av[av.index(k) + 1] if k in av else d
        video_main(av[0], av[1], av[2], int(opt("--every", 1)), opt("--self", os.environ.get("R2R_SELF", "")))
    else:
        main(*sys.argv[1:5])
