# -*- coding: utf-8 -*-
"""Source adapters: turn any talk URL (or file) into local media + metadata.

Supported sources
  youtube      -> yt-dlp (subs + chapters harvested when present)
  zoom         -> yt-dlp with browser cookies (recordings are auth-gated)
  awslivestream-> AWS Summit / Corrivium event sites: resolves the HLS VOD
  hls          -> a direct .m3u8
  file         -> a local media file
"""
import json, os, re, subprocess, sys, urllib.request

CMS = "https://site-assets.corrivium.live/cms/events"
UA = {"User-Agent": "Mozilla/5.0"}


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=True,
                          capture_output=True, text=True, **kw).stdout


def get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")


def detect(src):
    if os.path.exists(src):
        return "file"
    if re.search(r"youtube\.com|youtu\.be", src):
        return "youtube"
    if "zoom.us" in src:
        return "zoom"
    if src.endswith(".m3u8"):
        return "hls"
    if "awslivestream.com" in src or "corrivium" in src:
        return "awslivestream"
    return "generic"


# ----------------------------------------------------------- awslivestream
def aws_client_id(host, slug):
    """Find the Corrivium CMS client id for an event host."""
    html = get(f"https://{host}/{slug}/")
    m = re.search(r"cms/events/([A-Za-z0-9._-]+)/", html)
    if m:
        return m.group(1)
    for js in re.findall(r'src="([^"]+\.js)"', html):
        url = js if js.startswith("http") else f"https://{host}{js}"
        try:
            m = re.search(r"cms/events/([A-Za-z0-9._-]+)/", get(url))
            if m:
                return m.group(1)
        except Exception:
            pass
    # last resort: the slug prefix usually mirrors the client id (tlv-xxx -> ...tlv..)
    raise RuntimeError("could not resolve CMS client id; pass --client")


def aws_resolve(src, client=None):
    """URL of a session page -> (manifest, meta dict)."""
    m = re.match(r"https?://([^/]+)/([^/]+)/?", src)
    host, slug = m.group(1), m.group(2)
    client = client or aws_client_id(host, slug)
    fe = json.loads(get(f"{CMS}/{client}/{slug}/prod/frontend.json"))
    blob = json.dumps(fe)
    urls = re.findall(r"https://[^\"\\ ]+/outputs/mediaconvert/[^\"\\ ]+index\.m3u8", blob)
    if not urls:
        urls = re.findall(r"https://[^\"\\ ]+index\.m3u8", blob)
    meta = {"slug": slug, "client": client, "host": host,
            "title": fe.get("metaTags", {}).get("title") or slug}
    try:
        ev = json.loads(get(f"{CMS}/{client}/root/prod/events.json"))
        for e in ev.get("upcoming", []) + ev.get("onDemand", []):
            if e.get("sessionEventId") == slug:
                meta.update(title=e.get("eventtitle") or meta["title"],
                            description=e.get("description", ""),
                            track=e.get("customCategory", ""),
                            tags=e.get("filterTags", ""))
    except Exception:
        pass
    if not urls:
        raise RuntimeError("no HLS manifest in frontend.json")
    return urls[0], meta


def aws_list_sessions(host, any_slug, client=None):
    """Every session on the event site: [(slug, title, track)]."""
    client = client or aws_client_id(host, any_slug)
    ev = json.loads(get(f"{CMS}/{client}/root/prod/events.json"))
    out = []
    for e in ev.get("upcoming", []) + ev.get("onDemand", []):
        out.append((e.get("sessionEventId"), e.get("eventtitle"),
                    e.get("customCategory", "")))
    return out


def variant(manifest, want="video"):
    """Pick a rendition from a master playlist: best video, or the audio-only."""
    body = get(manifest)
    base = manifest.rsplit("/", 1)[0] + "/"
    if want == "audio":
        m = re.search(r'URI="([^"]*audio[^"]*\.m3u8)"', body)
        return base + m.group(1) if m else None
    best, best_bw = None, -1
    for bw, uri in re.findall(r"BANDWIDTH=(\d+)[^\n]*\n([^\n#]+)", body):
        if int(bw) > best_bw:
            best, best_bw = uri.strip(), int(bw)
    return base + best if best else manifest


# ------------------------------------------------------------------- fetch
def fetch(src, outdir, client=None, kind=None, quality="best"):
    os.makedirs(outdir, exist_ok=True)
    kind = kind or detect(src)
    meta = {"source": src, "kind": kind}
    video = os.path.join(outdir, "rec.mp4")

    if kind == "file":
        meta["title"] = os.path.basename(src)
        return {"video": os.path.abspath(src), "meta": meta}

    if kind in ("youtube", "zoom", "generic"):
        cmd = ["yt-dlp", "-f", "bv*+ba/b", "-o", video, src]
        if kind == "zoom":
            cmd[1:1] = ["--cookies-from-browser", "chrome"]
        subprocess.run(cmd, check=True)
        try:
            j = json.loads(sh(["yt-dlp", "--dump-json", "--skip-download", src]))
            meta.update(title=j.get("title"), channel=j.get("uploader"),
                        date=j.get("upload_date"), duration=j.get("duration"),
                        chapters=j.get("chapters") or [])
        except Exception:
            pass
        subprocess.run(["yt-dlp", "--write-subs", "--write-auto-subs",
                        "--sub-langs", "en.*,he.*", "--skip-download",
                        "-o", os.path.join(outdir, "subs"), src], check=False)
        return {"video": video, "meta": meta}

    if kind in ("awslivestream", "hls"):
        if kind == "hls":
            manifest, m = src, {}
        else:
            manifest, m = aws_resolve(src, client)
        meta.update(m)
        meta["manifest"] = manifest
        # HLS masters here carry video-only renditions plus a separate audio
        # group; muxing both explicitly is the only way to get sound.
        v = variant(manifest, "video")
        a = variant(manifest, "audio")
        if a and a != v:
            cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", v, "-i", a,
                   "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", video]
        else:
            cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", v,
                   "-c", "copy", video]
        subprocess.run(cmd, check=True)
        return {"video": video, "meta": meta}

    raise RuntimeError(f"unsupported source: {src}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("outdir")
    ap.add_argument("--client"); ap.add_argument("--kind")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        m = re.match(r"https?://([^/]+)/([^/]+)/?", a.src)
        for s, t, tr in aws_list_sessions(m.group(1), m.group(2), a.client):
            print(f"{s}\t{t}\t{tr}")
        sys.exit()
    r = fetch(a.src, a.outdir, a.client, a.kind)
    json.dump(r["meta"], open(os.path.join(a.outdir, "meta.json"), "w"),
              ensure_ascii=False, indent=2)
    print(json.dumps(r, ensure_ascii=False)[:400])
