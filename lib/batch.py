# -*- coding: utf-8 -*-
"""Run fetch -> asr -> slides over every session of an event, disk-safely.

Video is deleted as soon as frames are out, so peak disk stays ~1 GB even for
a 48-session conference. Resumable: a session with status.json is skipped.
"""
import json, os, subprocess, sys, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch as F


def human(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def one(src, work, lang=None, client=None, thresh=0.12, keep_video=False):
    os.makedirs(work, exist_ok=True)
    st = os.path.join(work, "status.json")
    if os.path.exists(st):
        return json.load(open(st))
    t0 = time.time()
    rec = os.path.join(work, "rec.mp4")
    wav = os.path.join(work, "audio.wav")
    out = {"src": src, "started": time.strftime("%F %T")}
    try:
        r = F.fetch(src, work, client=client)
        out["meta"] = r["meta"]
        json.dump(r["meta"], open(os.path.join(work, "meta.json"), "w"),
                  ensure_ascii=False, indent=2)
        out["fetched_s"] = round(time.time() - t0)

        import asr, slides
        asr.extract_audio(rec, wav)
        out["asr"] = asr.transcribe(wav, work, lang)

        raw = slides.detect(rec, os.path.join(work, "frames"), thresh)
        kept = slides.dedupe(raw, os.path.join(work, "frames"))
        slides.crop_all(kept, os.path.join(work, "frames", "crop"))
        slides.sheets(kept, os.path.join(work, "frames"), per=30)
        out["frames"] = {"raw": len(raw), "kept": len(kept)}
        out["ok"] = True
    except Exception as e:
        out["ok"] = False
        out["error"] = f"{type(e).__name__}: {e}"
        out["trace"] = traceback.format_exc()[-1200:]
    finally:
        for p in ([] if keep_video else [rec, wav]):
            if os.path.exists(p):
                os.remove(p)
        raw_dir = os.path.join(work, "frames", "raw")   # keep only deduped
        if os.path.isdir(raw_dir):
            subprocess.run(["rm", "-rf", raw_dir], check=False)
        out["total_s"] = round(time.time() - t0)
        json.dump(out, open(st, "w"), ensure_ascii=False, indent=2)
    return out


def batch(event_url, root, lang=None, client=None, limit=None, only=None):
    import re
    m = re.match(r"https?://([^/]+)/([^/]+)/?", event_url)
    host, any_slug = m.group(1), m.group(2)
    sessions = F.aws_list_sessions(host, any_slug, client)
    if only:
        want = set(only)
        sessions = [s for s in sessions if s[0] in want]
    if limit:
        sessions = sessions[:limit]
    os.makedirs(root, exist_ok=True)
    index = []
    t0 = time.time()
    for i, (slug, title, track) in enumerate(sessions, 1):
        work = os.path.join(root, slug)
        url = f"https://{host}/{slug}/live/"
        print(f"[{i}/{len(sessions)}] {slug} — {title}", flush=True)
        r = one(url, work, lang, client)
        r.update(slug=slug, title=title, track=track)
        index.append(r)
        json.dump(index, open(os.path.join(root, "index.json"), "w"),
                  ensure_ascii=False, indent=2)
        flag = "ok" if r.get("ok") else "FAIL " + r.get("error", "")[:70]
        print(f"      {flag}  {human(r['total_s'])}  "
              f"frames={r.get('frames', {}).get('kept', '-')}", flush=True)
    print(f"\ndone: {sum(1 for r in index if r.get('ok'))}/{len(index)} in "
          f"{human(time.time() - t0)}")
    return index


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("event_url"); ap.add_argument("root")
    ap.add_argument("--lang"); ap.add_argument("--client")
    ap.add_argument("--limit", type=int); ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    batch(a.event_url, a.root, a.lang, a.client, a.limit, a.only)
