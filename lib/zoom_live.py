# -*- coding: utf-8 -*-
"""Record a live Zoom meeting on Windows without admin rights or extra drivers.

  python zoom_live.py start  <work> [--every 2] [--grace 45] [--wait 600] [--max-hours 4]
  python zoom_live.py status <work>
  python zoom_live.py stop   <work>          # or create <work>\\STOP
  python zoom_live.py windows                # list Zoom windows (diagnostics)

Audio: WASAPI loopback of the default playback device (what you hear = every participant;
your own microphone is not in it). Pictures: the Zoom meeting window every --every seconds via
PrintWindow (works while covered, not while minimised); while you share your own screen the
meeting window hides, so the primary screen is captured instead. Stops by itself when no
meeting window has been seen for --grace seconds.

Writes <work>/audio.wav, <work>/win/HHMMSS.jpg, <work>/status.json, live.log, and at the end
<work>/rec.mp4 (audio only, for `r2r asr`) + meta.json. Pictures: screenshare.py frames <work>/win ...
"""
import ctypes, ctypes.wintypes as W, json, os, subprocess, sys, threading, time, wave

u32, k32, g32 = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.gdi32
u32.SetProcessDPIAware()

# Meeting windows of the Zoom client (classic and Workplace); the home/chat window is not one.
MEETING = {"ConfMultiTabContentWndClass", "ZPContentViewWndClass"}
SHARING = {"ZPToolBarParentWndClass", "ZPShareToolbarWndClass", "ZPFloatToolbarClass"}
HOME = {"ZPPTMainFrmWndClassEx", "ZPPTMainFrmWndClass", "ZPFrameWndClass"}


def _proc_name(h):
    pid = W.DWORD(); u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    hp = k32.OpenProcess(0x1000, 0, pid.value)
    buf = ctypes.create_unicode_buffer(260); n = W.DWORD(260)
    k32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(n)); k32.CloseHandle(hp)
    return os.path.basename(buf.value).lower()


def zoom_windows():
    out = []
    def cb(h, _):
        if u32.IsWindowVisible(h) and _proc_name(h) in ("zoom.exe", "cpthost.exe"):
            c = ctypes.create_unicode_buffer(256); u32.GetClassNameW(h, c, 256)
            t = ctypes.create_unicode_buffer(256); u32.GetWindowTextW(h, t, 256)
            r = W.RECT(); u32.GetWindowRect(h, ctypes.byref(r))
            out.append(dict(hwnd=h, cls=c.value, title=t.value, w=r.right - r.left,
                            h=r.bottom - r.top, iconic=bool(u32.IsIconic(h))))
        return True
    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)(cb), 0)
    return out


def meeting_window(wins):
    """(hwnd or None, sharing?) - the biggest meeting window, else a big non-home Zoom window."""
    big = [x for x in wins if not x["iconic"] and x["w"] >= 400 and x["h"] >= 300]
    m = [x for x in big if x["cls"] in MEETING] or [x for x in big if x["cls"] not in HOME | SHARING]
    # the share toolbar exists at 0x0 during every meeting; it is only "sharing" when it is on screen
    sharing = any(x["cls"] in SHARING and x["w"] > 0 and x["h"] > 0 for x in wins)
    if m:
        return max(m, key=lambda x: x["w"] * x["h"])["hwnd"], sharing
    return None, sharing


def in_meeting(wins):
    """A meeting is on while a meeting window exists (also minimised), or - while the user shares and
    Zoom hides that window - the share toolbar is on screen."""
    return any(x["cls"] in MEETING or (x["cls"] in SHARING and x["w"] > 0 and x["h"] > 0) for x in wins)


def grab_window(h):
    from PIL import Image
    r = W.RECT(); u32.GetWindowRect(h, ctypes.byref(r))
    w, ht = r.right - r.left, r.bottom - r.top
    hdc = u32.GetWindowDC(h); mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, ht); g32.SelectObject(mdc, bmp)
    ok = u32.PrintWindow(h, mdc, 2)  # PW_RENDERFULLCONTENT: also GPU-drawn content
    class BIH(ctypes.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                    ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                    ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                    ("biClrImportant", W.DWORD)]
    bi = BIH(ctypes.sizeof(BIH), w, -ht, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * ht * 4)
    g32.GetDIBits(mdc, bmp, 0, ht, buf, ctypes.byref(bi), 0)
    g32.DeleteObject(bmp); g32.DeleteDC(mdc); u32.ReleaseDC(h, hdc)
    return Image.frombuffer("RGB", (w, ht), buf, "raw", "BGRX", 0, 1) if ok else None


def grab_screen():
    from PIL import ImageGrab
    return ImageGrab.grab()


class Audio(threading.Thread):
    """WASAPI loopback of the default output device -> 16-bit wav; keeps a running level."""
    def __init__(self, path):
        super().__init__(daemon=True); self.path, self.stop, self.db, self.err = path, False, None, None
    def run(self):
        import array, math, pyaudiowpatch as pa
        p = pa.PyAudio()
        try:
            dev = p.get_default_wasapi_loopback()
            ch, rate = dev["maxInputChannels"], int(dev["defaultSampleRate"])
            self.device = dev["name"]
            wf = wave.open(self.path, "wb"); wf.setnchannels(ch); wf.setsampwidth(2); wf.setframerate(rate)
            s = p.open(format=pa.paInt16, channels=ch, rate=rate, input=True,
                       input_device_index=dev["index"], frames_per_buffer=rate // 10)
            while not self.stop:
                d = s.read(rate // 10, exception_on_overflow=False); wf.writeframes(d)
                a = array.array("h", d); rms = math.sqrt(sum(x * x for x in a[::8]) / max(1, len(a) // 8))
                self.db = round(20 * math.log10(rms / 32768), 1) if rms else -99.0
            s.stop_stream(); s.close(); wf.close()
        except Exception as e:
            self.err = repr(e)
        finally:
            p.terminate()


def start(work, every=2, grace=45, wait=600, max_hours=4):
    os.makedirs(os.path.join(work, "win"), exist_ok=True)
    log = open(os.path.join(work, "live.log"), "a", encoding="utf-8")
    def say(m):
        line = time.strftime("%H:%M:%S ") + m; print(line, flush=True); log.write(line + "\n"); log.flush()
    t0 = time.time()
    while meeting_window(zoom_windows())[0] is None:
        if time.time() - t0 > wait:
            say("no Zoom meeting window found - join the meeting first"); return 1
        time.sleep(3)
    aud = Audio(os.path.join(work, "audio.wav")); aud.start()
    started, last_seen, n, quiet_since = time.time(), time.time(), 0, None
    say("recording started (audio + Zoom window every %ss)" % every)
    say("REMINDER: tell the participants you are recording (e.g. in the Zoom chat) - they get no Zoom notice")
    stop = os.path.join(work, "STOP")
    while True:
        tick = time.time()
        wins = zoom_windows()
        h, sharing = meeting_window(wins)
        if in_meeting(wins):
            last_seen = tick
        img = None
        try:
            if h:
                img = grab_window(h)
            elif sharing:
                img = grab_screen()
        except Exception as e:
            say("capture error: %r" % e)
        if img is not None:
            img.save(os.path.join(work, "win", time.strftime("%H%M%S") + ".jpg"), quality=85); n += 1
        if aud.db is not None and aud.db < -60:
            quiet_since = quiet_since or tick
        else:
            quiet_since = None
        json.dump(dict(state="recording", started=time.strftime("%H:%M:%S", time.localtime(started)),
                       minutes=round((tick - started) / 60, 1), frames=n, audio_db=aud.db,
                       audio_error=aud.err, silent_for_s=int(tick - quiet_since) if quiet_since else 0,
                       mode="window" if h else ("screen" if sharing else ("minimised" if tick == last_seen else "none"))),
                  open(os.path.join(work, "status.json"), "w"))
        if aud.err:
            say("audio failed: " + aud.err); break
        if tick - last_seen > grace:
            say("no Zoom meeting for %ss - meeting ended" % grace); break
        if os.path.exists(stop):
            say("STOP file - stopping"); break
        if tick - started > max_hours * 3600:
            say("max length reached - stopping"); break
        time.sleep(max(0.2, every - (time.time() - tick)))
    aud.stop = True; aud.join(10)
    rec = os.path.join(work, "rec.mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", os.path.join(work, "audio.wav"),
                    "-ac", "1", "-c:a", "aac", "-b:a", "96k", rec], check=True)
    meta = dict(source="zoom live (Windows)", kind="zoom-live", audio_start=time.strftime("%H:%M:%S", time.localtime(started)),
                date=time.strftime("%Y-%m-%d", time.localtime(started)), frames=n,
                minutes=round((time.time() - started) / 60, 1), audio_device=getattr(aud, "device", None))
    json.dump(meta, open(os.path.join(work, "meta.json"), "w"), ensure_ascii=False)
    json.dump(dict(json.load(open(os.path.join(work, "status.json"))), state="done"), open(os.path.join(work, "status.json"), "w"))
    say("done: %s min, %d frames -> rec.mp4 + win\\" % (meta["minutes"], n))
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    opt = lambda k, d: type(d)(a[a.index(k) + 1]) if k in a else d
    if a and a[0] == "windows":
        for x in zoom_windows():
            print(x)
        print("meeting window:", meeting_window(zoom_windows()))
    elif a and a[0] == "status":
        print(open(os.path.join(a[1], "status.json")).read())
    elif a and a[0] == "stop":
        open(os.path.join(a[1], "STOP"), "w").close(); print("stop requested")
    elif a and a[0] == "start":
        sys.exit(start(a[1], opt("--every", 2), opt("--grace", 45), opt("--wait", 600), opt("--max-hours", 4)))
    else:
        print(__doc__)
