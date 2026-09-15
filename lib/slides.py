# -*- coding: utf-8 -*-
"""Harvest the speaker's slides out of the video.

detect  -> scene-change frames
dedupe  -> drop near-identical frames (dhash) and near-black ones
sheet   -> numbered contact sheets for visual review
clean   -> crop letterbox, optionally paint over overlay boxes
"""
import glob, os, re, subprocess, sys
from PIL import Image, ImageChops, ImageStat


def detect(video, outdir, thresh=0.12, width=1400):
    raw = os.path.join(outdir, "raw")
    os.makedirs(raw, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-i", video, "-vf",
                    f"select='gt(scene,{thresh})',showinfo,scale={width}:-1",
                    "-vsync", "vfr", "-q:v", "2",
                    os.path.join(raw, "s_%04d.jpg")], check=True,
                   capture_output=True)
    return sorted(glob.glob(os.path.join(raw, "*.jpg")))


def dhash(img, size=8):
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for r in range(size):
        for c in range(size):
            i = r * (size + 1) + c
            bits = (bits << 1) | (px[i] < px[i + 1])
    return bits


def ham(a, b):
    return bin(a ^ b).count("1")


def flatness(img):
    """Slides have large flat areas; stage shots do not. 0..1, higher = flatter."""
    g = img.convert("L").resize((160, 90))
    h = g.histogram()
    return max(h) / float(sum(h))


def dedupe(files, outdir, hamming=6, dark=28, keep_flat=0.0):
    keep, hashes = [], []
    for f in files:
        im = Image.open(f)
        if ImageStat.Stat(im.convert("L")).mean[0] < dark:
            continue
        if keep_flat and flatness(im) < keep_flat:
            continue
        h = dhash(im)
        if any(ham(h, p) <= hamming for p in hashes[-12:]):
            continue
        hashes.append(h)
        keep.append(f)
    sel = os.path.join(outdir, "kept")
    os.makedirs(sel, exist_ok=True)
    out = []
    for i, f in enumerate(keep, 1):
        d = os.path.join(sel, f"k_{i:03d}.jpg")
        Image.open(f).save(d, quality=92)
        out.append(d)
    return out


def sheet(files, out, cols=5, tw=380):
    if not files:
        return None
    from PIL import ImageDraw
    w, h = Image.open(files[0]).size
    th = int(tw * h / w)
    rows = (len(files) + cols - 1) // cols
    sh = Image.new("RGB", (cols * tw, rows * (th + 20)), "white")
    d = ImageDraw.Draw(sh)
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGB").resize((tw, th))
        x, y = (i % cols) * tw, (i // cols) * (th + 20)
        sh.paste(im, (x, y + 20))
        d.text((x + 5, y + 5), os.path.basename(f), fill="black")
    sh.save(out, quality=88)
    return out


def sheets(files, outdir, per=30, cols=5):
    made = []
    for i in range(0, len(files), per):
        p = os.path.join(outdir, f"sheet_{i//per + 1:02d}.jpg")
        sheet(files[i:i + per], p, cols=cols)
        made.append(p)
    return made


def autocrop(im, thresh=14):
    g = im.convert("L")
    bg = Image.new("L", im.size, 0)
    diff = ImageChops.difference(g, bg)
    bbox = diff.point(lambda p: 255 if p > thresh else 0).getbbox()
    return im.crop(bbox) if bbox else im


def clean(files, outdir, boxes=(), crop=True):
    """boxes: list of (x0,y0,x1,y1) as fractions, painted with a sampled colour."""
    os.makedirs(outdir, exist_ok=True)
    out = []
    for f in files:
        im = Image.open(f).convert("RGB")
        W, H = im.size
        for (a, b, c, d) in boxes:
            box = (int(a * W), int(b * H), int(c * W), int(d * H))
            sx = max(0, box[0] - 12)
            col = im.getpixel((sx, min(H - 1, box[3] - 2)))
            im.paste(col, box)
        if crop:
            im = autocrop(im)
        p = os.path.join(outdir, os.path.basename(f).replace(".jpg", ".png"))
        im.save(p)
        out.append(p)
    return out


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("outdir")
    ap.add_argument("--thresh", type=float, default=0.12)
    ap.add_argument("--hamming", type=int, default=6)
    ap.add_argument("--flat", type=float, default=0.0)
    ap.add_argument("--per", type=int, default=30)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    raw = sorted(glob.glob(os.path.join(a.outdir, "raw", "*.jpg")))
    if not raw:
        raw = detect(a.video, a.outdir, a.thresh)
    kept = dedupe(raw, a.outdir, a.hamming, keep_flat=a.flat)
    sh = sheets(kept, a.outdir, a.per)
    print(json.dumps({"raw": len(raw), "kept": len(kept), "sheets": sh},
                     ensure_ascii=False))


# --------------------------------------------------------- slide-region crop
def crop_slide(path, out=None, min_area=0.12, ar=(1.30, 2.10), pad=2):
    """Conference streams inset the deck inside stage furniture. Find the
    largest screen-like rectangle and crop to it. Needs opencv; returns the
    original path if nothing convincing is found."""
    try:
        import cv2, numpy as np
    except ImportError:
        return path
    im = cv2.imread(path)
    if im is None:
        return path
    H, W = im.shape[:2]
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    edges = cv2.Canny(g, 40, 130)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        area = (w * h) / float(W * H)
        if area < min_area or h == 0:
            continue
        a = w / float(h)
        if not (ar[0] <= a <= ar[1]):
            continue
        if area > best_area:
            best, best_area = (x, y, w, h), area
    if not best:
        return path
    x, y, w, h = best
    x, y = max(0, x + pad), max(0, y + pad)
    w, h = min(W - x, w - 2 * pad), min(H - y, h - 2 * pad)
    dst = out or path
    cv2.imwrite(dst, im[y:y + h, x:x + w])
    return dst


def crop_all(files, outdir, **kw):
    """Crop what we can; pass the rest through unchanged so the set stays whole."""
    import shutil
    os.makedirs(outdir, exist_ok=True)
    out, cropped = [], 0
    for f in files:
        d = os.path.join(outdir, os.path.basename(f))
        r = crop_slide(f, d, **kw)
        if r == f:                      # nothing convincing found
            shutil.copy(f, d)
        else:
            cropped += 1
        out.append(d)
    sys.stderr.write(f"cropped {cropped}/{len(files)}\n")
    return out
