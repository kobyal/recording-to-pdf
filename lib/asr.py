# -*- coding: utf-8 -*-
"""Transcribe with mlx-whisper (Apple Silicon) and emit reader-friendly blocks."""
import json, os, subprocess, sys, time

MODEL = os.environ.get("R2R_MODEL", "mlx-community/whisper-large-v3-turbo")


def extract_audio(video, out):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", video,
                    "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out],
                   check=True)
    return out


def ts(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def blocks(segments, window=90):
    """Collapse segments into ~window-second timestamped blocks."""
    out, cur, start = [], [], None
    for s in segments:
        if start is None:
            start = s["start"]
        cur.append(s["text"].strip())
        if s["end"] - start >= window:
            out.append(f"[{ts(start)}] " + " ".join(cur))
            cur, start = [], None
    if cur:
        out.append(f"[{ts(start or 0)}] " + " ".join(cur))
    return out


def transcribe(audio, outdir, lang=None, window=90):
    import contextlib, io, mlx_whisper
    t0 = time.time()
    kw = dict(path_or_hf_repo=MODEL, verbose=False, condition_on_previous_text=False)
    if lang:
        kw["language"] = lang
    # mlx-whisper writes a tqdm bar to stderr regardless of verbose=False,
    # which drowns a batch log. Swallow it; keep real errors.
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        r = mlx_whisper.transcribe(audio, **kw)
    os.makedirs(outdir, exist_ok=True)
    json.dump(r, open(f"{outdir}/transcript.json", "w"), ensure_ascii=False)
    with open(f"{outdir}/transcript.txt", "w") as f:
        for s in r["segments"]:
            f.write(f"[{ts(s['start'])}] {s['text'].strip()}\n")
    bl = blocks(r["segments"], window)
    open(f"{outdir}/transcript_blocks.txt", "w").write("\n\n".join(bl))
    return {"language": r.get("language"), "segments": len(r["segments"]),
            "blocks": len(bl), "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("outdir")
    ap.add_argument("--lang"); ap.add_argument("--window", type=int, default=90)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    wav = os.path.join(a.outdir, "audio.wav")
    if not os.path.exists(wav):
        extract_audio(a.video, wav)
    print(json.dumps(transcribe(wav, a.outdir, a.lang, a.window), ensure_ascii=False))
