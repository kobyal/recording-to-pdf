# -*- coding: utf-8 -*-
"""Transcribe with mlx-whisper (Apple Silicon), or faster-whisper on CPU
elsewhere (Windows/Linux), and emit reader-friendly blocks."""
import json, os, subprocess, sys, time

# ivrit.ai's Hebrew fine-tune of the same turbo model: far fewer garbled words
# and real sentences on Hebrew meetings. Base model for everything else.
MODELS = {"he": "mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx"}
DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


def model_for(lang):
    return os.environ.get("R2R_MODEL") or MODELS.get(lang, DEFAULT_MODEL)


# The same models as CTranslate2 builds, for faster-whisper (no Apple GPU).
FW_MODELS = {"he": "ivrit-ai/whisper-large-v3-turbo-ct2"}
FW_DEFAULT_MODEL = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


def fw_transcribe(audio, lang, initial_prompt=None):
    """faster-whisper on CPU; returns the same shape as mlx_whisper.transcribe."""
    from faster_whisper import WhisperModel, BatchedInferencePipeline
    name = os.environ.get("R2R_MODEL") or FW_MODELS.get(lang, FW_DEFAULT_MODEL)
    model = WhisperModel(name, device="cpu", compute_type="int8")
    # batched decoding: ~25% faster on a 4-vCPU VM, same text. Timestamps on: sentence-level
    # segments (~4 s) instead of one per 30 s chunk, at no measurable cost - speaker
    # attribution needs them.
    segs, info = BatchedInferencePipeline(model=model).transcribe(audio, language=lang, batch_size=8,
                                                               initial_prompt=initial_prompt,
                                                               without_timestamps=False)
    segs = [{"start": s.start, "end": s.end, "text": s.text} for s in segs]
    return {"text": "".join(s["text"] for s in segs), "segments": segs,
            "language": info.language}


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
    import contextlib, io
    t0 = time.time()
    try:
        import mlx_whisper
    except ImportError:
        mlx_whisper = None
    kw = dict(path_or_hf_repo=model_for(lang), verbose=False, condition_on_previous_text=False)
    if lang:
        kw["language"] = lang
    # names from the private people file (R2R_PEOPLE) fix their spelling
    from people import load, prompt
    names = prompt(load())
    if names:
        kw["initial_prompt"] = names
    # mlx-whisper writes a tqdm bar to stderr regardless of verbose=False,
    # which drowns a batch log. Swallow it; keep real errors.
    buf = io.StringIO()
    if mlx_whisper is None:
        r = fw_transcribe(audio, lang, kw.get("initial_prompt"))
    else:
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
