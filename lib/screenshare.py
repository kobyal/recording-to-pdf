# -*- coding: utf-8 -*-
"""Pick the shared-screen pictures out of a meeting recording.

Meeting recordings (Zoom / Meet / Webex, captured as a full desktop or as the
meeting window) are mostly faces, avatars and app chrome; the useful pictures
are the moments someone shares a screen. slides.detect() is tuned for
conference decks and misses most of them, and deduping whole frames lets the
chrome dominate, so different screens look "the same".

This module:
  1. finds the shared-content rectangle in each frame (not dark UI, not
     desktop wallpaper, large, and full of text edges -> not a camera feed,
     not an avatar circle, not a thin strip of browser chrome),
  2. reuses a rectangle seen in other frames when this frame's own detection
     fails but the area around it is unchanged: dark slides and terminals on a
     black letterbox (Webex, Meet) look like UI to step 1,
  3. keeps the settled (last) frame of each run of near-identical crops,
     dropping anything on screen for less than two samples (scrolling, fades),
  4. dedupes on the crop itself, against everything kept so far, and enlarges
     small crops (a webinar share is often ~600 px wide inside the browser).

  python screenshare.py frames <dir_of_jpgs> <outdir>   # e.g. window captures
  python screenshare.py video  <video> <outdir> [--every 2]
Writes <outdir>/kept/ss_NNN.jpg (+ .txt with the source time) and sheet_NN.jpg.
"""
import glob, json, os, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageFilter
import cv2

MIN_AREA = 0.10      # content box must cover >= 10% of the frame
MIN_EDGES = 0.012    # fraction of edge pixels: rejects blank screens and plain avatar tiles (faces are caught by SKIN)
SKIN = 0.08         # skin-tone fraction above this = camera feed (faces), not a screen
DIFF = 6.0           # mean abs grey difference (0-255) on a 96x54 thumbnail = "new picture"
STILL = 4.0          # below this between consecutive samples = the same picture, still settling
MIN_RUN = 2          # samples a picture must stay on screen to be kept
TEXT = 0.01         # ...unless this share of a 320x180 thumbnail changed by > 60 (new terminal line, next bullet)
SMALL = 900          # crops narrower than this are enlarged 2x on save


def content_box(img):
    """(x0, y0, x1, y1) of the shared content, or None."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    grey = (r * 30 + g * 59 + b * 11) // 100
    sat = np.max(a, axis=2) - np.min(a, axis=2)
    # Zoom/Meet chrome and black bars are dark AND neutral grey; dark-themed slides
    # (navy, purple) are dark but coloured, so they stay content
    dark_ui = (grey < 42) & (sat < 20)
    wallpaper = (b - np.maximum(r, g) > 45) & (b > 110)   # Windows blue desktop
    mask = (~(dark_ui | wallpaper)).astype(np.uint8)
    h, w = mask.shape
    k = max(3, w // 160)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh = stats[i, :4]
    if bw * bh < MIN_AREA * w * h or bw < 0.25 * w:
        return None
    crop = grey[y:y + bh, x:x + bw].astype(np.uint8)
    edges = cv2.Canny(crop, 60, 160)
    if edges.mean() / 255 < MIN_EDGES:                    # avatar / blank
        return None
    if bw > 4 * bh:                                       # browser tab/address bar, toolbar strip
        return None
    if _not_screen(a[y:y + bh, x:x + bw].astype(np.uint8)):
        return None
    return int(x), int(y), int(x + bw), int(y + bh)


def _not_screen(rgb):
    """True for a camera feed (skin) or an avatar (one saturated colour filling a square tile)."""
    small = cv2.resize(rgb, (320, 180))
    ycc = cv2.cvtColor(small, cv2.COLOR_RGB2YCrCb).astype(np.int16)
    lit = ycc[..., 0] > 40                                # ignore black bars around a camera tile
    skin = ((ycc[..., 1] >= 138) & (ycc[..., 1] <= 173) & (ycc[..., 2] >= 77) &
            (ycc[..., 2] <= 127) & (ycc[..., 0] > 60))
    if lit.mean() > 0.05 and skin[lit].mean() > SKIN:    # camera feed: people, not a shared screen
        return True
    h, w = rgb.shape[:2]
    q = (small // 32).reshape(-1, 3)
    u, c = np.unique(q, axis=0, return_counts=True)
    dom = u[c.argmax()] * 32 + 16
    return 0.8 < w / h < 1.25 and c.max() / len(q) > 0.5 and int(dom.max()) - int(dom.min()) >= 32


def _band(a, box, k=4):
    """The k-pixel ring just outside box, as one flat array (for 'is the surrounding unchanged?')."""
    h, w = a.shape[:2]
    x0, y0, x1, y1 = box
    parts = [a[max(0, y0 - k):y0, x0:x1], a[y1:min(h, y1 + k), x0:x1],
             a[y0:y1, max(0, x0 - k):x0], a[y0:y1, x1:min(w, x1 + k)]]
    parts = [p.reshape(-1) for p in parts if p.size]
    return np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, np.float32)


def _reuse(img, anchors):
    """A remembered rectangle that fits this frame: same surroundings, and a screen inside it."""
    a = np.asarray(img.convert("L"))
    rgb = np.asarray(img.convert("RGB"))
    for box, band in anchors:
        b = _band(a, box)
        if not band.size or b.size != band.size or np.abs(b - band).mean() > 6:
            continue
        x0, y0, x1, y1 = box
        crop = rgb[y0:y1, x0:x1]
        if crop.max() < 40:                              # black: nothing shared right now
            continue
        if cv2.Canny(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY), 60, 160).mean() / 255 < MIN_EDGES / 2:
            continue
        if _not_screen(crop):
            continue
        return box
    return None


def _snap(box, anchors):
    """Use a remembered rectangle when this one is almost the same (steadier crops, better dedupe)."""
    for b, _ in anchors:
        if all(abs(p - q) <= 8 for p, q in zip(box, b)):
            return b
    return box


def _save(crop, path):
    """Trim black letterbox bars; enlarge small crops 2x so slide text stays readable in print."""
    g = np.asarray(crop.convert("L"))
    rows, cols = np.where(g.mean(1) > 12)[0], np.where(g.mean(0) > 12)[0]
    if len(rows) > 10 and len(cols) > 10:
        crop = crop.crop((int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1))
    if crop.width < SMALL:
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.2, 60, 2))
    crop.convert("RGB").save(path, quality=92)


def _thumb(img):
    return np.asarray(img.convert("L").resize((96, 54))).astype(np.float32)


def _fine(img):
    return np.asarray(img.convert("L").resize((320, 180))).astype(np.float32)


def _same(a, b):
    """Duplicate pictures: close overall AND no block of text changed. Same-template slides and
    terminals differ only in their text, which the 96x54 mean alone smears away."""
    return np.abs(a[0] - b[0]).mean() < DIFF and (np.abs(a[1] - b[1]) > 60).mean() < TEXT


def pick(items, outdir):
    """items: iterable of (label, PIL.Image), in time order. Keeps distinct, settled shared-screen crops."""
    kept_dir = os.path.join(outdir, "kept")
    os.makedirs(kept_dir, exist_ok=True)
    thumbs, out, seen = [], [], 0
    anchors, counts = [], {}      # rectangles seen in >= 2 frames, with the ring around them
    run = None                    # [label, crop, thumb, length] of the picture on screen now

    def flush():
        if not run or run[3] < MIN_RUN:
            return
        sig = (run[2], _fine(run[1]))
        if any(_same(sig, p) for p in thumbs):
            return
        thumbs.append(sig)
        p = os.path.join(kept_dir, f"ss_{len(out) + 1:03d}.jpg")
        _save(run[1], p)
        open(p[:-4] + ".txt", "w").write(str(run[0]))
        out.append(p)

    for label, img in items:
        seen += 1
        box = content_box(img)
        if box:
            key = tuple(v // 8 for v in box)
            counts[key] = counts.get(key, 0) + 1
            if counts[key] == 2 and not any(all(abs(p - q) <= 8 for p, q in zip(box, b)) for b, _ in anchors):
                anchors.insert(0, (box, _band(np.asarray(img.convert("L")), box)))
            box = _snap(box, anchors)
        else:
            box = _reuse(img, anchors)
        if not box:
            flush(); run = None
            continue
        crop = img.crop(box)
        t = _thumb(crop)
        if run and np.abs(t - run[2]).mean() < STILL:
            run = [label, crop, t, run[3] + 1]           # same picture: keep the latest, settled frame
        else:
            flush(); run = [label, crop, t, 1]
    flush()
    return seen, out


def from_frames(src, outdir):
    files = sorted(glob.glob(os.path.join(src, "*.jpg")) + glob.glob(os.path.join(src, "*.png")))
    return pick(((os.path.basename(f), Image.open(f)) for f in files), outdir)


def from_video(video, outdir, every=2):
    tmp = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", video, "-vf", f"fps=1/{every}",
                    "-q:v", "3", os.path.join(tmp, "f_%05d.jpg")], check=True)
    files = sorted(glob.glob(os.path.join(tmp, "*.jpg")))
    def gen():
        for i, f in enumerate(files):
            s = i * every
            yield f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}", Image.open(f)
    res = pick(gen(), outdir)
    for f in files:
        os.remove(f)
    return res


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import slides
    mode, src, outdir = sys.argv[1:4]
    every = int(sys.argv[sys.argv.index("--every") + 1]) if "--every" in sys.argv else 2
    seen, kept = from_frames(src, outdir) if mode == "frames" else from_video(src, outdir, every)
    sheets = slides.sheets(kept, outdir, per=30, cols=5) if kept else []
    print(json.dumps({"seen": seen, "kept": len(kept), "sheets": sheets}))
