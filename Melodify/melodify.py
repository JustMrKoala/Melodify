import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import json
import os
import sys
import time
import shutil
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
import re

# ── optional deps ──────────────────────────────────────────────────────────────
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

try:
    from pytubefix import Search
    PYTUBE_AVAILABLE = True
except ImportError:
    PYTUBE_AVAILABLE = False


def lrclib_fetch(title: str, artist: str) -> dict:
    """
    Fetch lyrics from lrclib.net — free, no auth.
    Returns dict with keys:
      'plain'  – plain text lyrics (str or None)
      'synced' – list of (seconds_float, line_str) tuples, or []
    """
    result = {"plain": None, "synced": []}
    if not REQUESTS_AVAILABLE:
        return result
    try:
        import urllib.parse
        params = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
        r = requests.get(
            f"https://lrclib.net/api/get?{params}", timeout=8,
            headers={"User-Agent": "Melodify/1.0"})
        if r.status_code != 200:
            # try without artist
            params2 = urllib.parse.urlencode({"track_name": title})
            r = requests.get(
                f"https://lrclib.net/api/get?{params2}", timeout=8,
                headers={"User-Agent": "Melodify/1.0"})
        if r.status_code == 200:
            data = r.json()
            result["plain"] = (data.get("plainLyrics") or "").strip() or None
            synced_raw = data.get("syncedLyrics") or ""
            if synced_raw:
                lines = []
                for ln in synced_raw.splitlines():
                    m = re.match(r'\[(\d+):(\d+\.\d+)\]\s*(.*)', ln)
                    if m:
                        secs = int(m.group(1)) * 60 + float(m.group(2))
                        lines.append((secs, m.group(3)))
                result["synced"] = lines
    except Exception as e:
        print(f"lrclib error: {e}")
    return result


try:
    import pygame
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.mixer.init()
    PYGAME_AVAILABLE = True
except Exception:
    PYGAME_AVAILABLE = False

def _check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

FFMPEG_AVAILABLE = _check_ffmpeg()

# ── paths ──────────────────────────────────────────────────────────────────────
APP_DIR        = Path.home() / ".melodify"
MUSIC_DIR      = APP_DIR / "music"
THUMBNAILS_DIR = APP_DIR / "thumbnails"
TMP_DIR        = APP_DIR / "tmp"
DATA_FILE      = APP_DIR / "data.json"
COMPRESS_DAYS  = 30

for _d in [APP_DIR, MUSIC_DIR, THUMBNAILS_DIR, TMP_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── palette ────────────────────────────────────────────────────────────────────
C = {
    "bg":      "#0D0D0D",
    "bg2":     "#121212",
    "card":    "#181818",
    "hover":   "#282828",
    "sidebar": "#000000",
    "accent":  "#1DB954",
    "acc_h":   "#1ed760",
    "acc_dim": "#158a3e",
    "fg":      "#FFFFFF",
    "fg2":     "#B3B3B3",
    "dim":     "#535353",
    "prog_bg": "#404040",
    "warn":    "#F39C12",
    "liked":   "#E91E63",
}

ctk.set_appearance_mode("dark")

# ── load saved accent colour (applied before DataManager so C is ready) ───────
def _load_accent():
    """Read accent colour from data.json without loading the full DataManager."""
    try:
        if DATA_FILE.exists():
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            return raw.get("settings", {}).get("accent_color", None)
    except Exception:
        pass
    return None

_saved_accent = _load_accent()
if _saved_accent:
    # derive a lighter hover and darker dim variant automatically
    def _hex_scale(hex_col, factor):
        hex_col = hex_col.lstrip("#")
        r, g, b = int(hex_col[0:2],16), int(hex_col[2:4],16), int(hex_col[4:6],16)
        r = min(255, max(0, int(r * factor)))
        g = min(255, max(0, int(g * factor)))
        b = min(255, max(0, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    C["accent"]  = _saved_accent
    C["acc_h"]   = _hex_scale(_saved_accent, 1.12)
    C["acc_dim"] = _hex_scale(_saved_accent, 0.70)


# ══════════════════════════════════════════════════════════════════════════════
# TOOLTIP helper
# ══════════════════════════════════════════════════════════════════════════════
class Tooltip:
    """Small dark tooltip that follows the cursor."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text   = text
        self._id    = None
        self._win   = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._cancel)

    def _schedule(self, _e):
        self._cancel(None)
        self._id = self.widget.after(600, self._show)

    def _cancel(self, _e):
        if self._id:
            self.widget.after_cancel(self._id)
            self._id = None
        if self._win:
            self._win.destroy()
            self._win = None

    def _show(self):
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() - 28
        self._win = tk.Toplevel(self.widget)
        self._win.wm_overrideredirect(True)
        self._win.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._win, text=self.text,
            background="#1a1a1a", foreground="#ffffff",
            font=("Arial", 10), padx=8, pady=4,
            relief="flat", borderwidth=0
        ).pack()


def _hex_scale(hex_col, factor):
    hex_col = hex_col.lstrip("#")
    r, g, b = int(hex_col[0:2],16), int(hex_col[2:4],16), int(hex_col[4:6],16)
    r = min(255, max(0, int(r * factor)))
    g = min(255, max(0, int(g * factor)))
    b = min(255, max(0, int(b * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"

def apply_accent(color: str):
    """Update C accent colours globally. Call after changing colour."""
    C["accent"]  = color
    C["acc_h"]   = _hex_scale(color, 1.12)
    C["acc_dim"] = _hex_scale(color, 0.70)

def open_in_folder(filepath: str):
    """Open the system file manager at the folder containing filepath."""
    import platform
    folder = str(Path(filepath).parent)
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(["explorer", "/select,", filepath])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", filepath])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception as e:
        print(f"open_in_folder error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# DATA MANAGER
# ══════════════════════════════════════════════════════════════════════════════
class DataManager:
    def __init__(self):
        self.data = self._load()
        for key, default in [
            ("songs",        {}),
            ("playlists",    {}),
            ("play_history", []),
            ("settings",     {"download_dir": str(MUSIC_DIR),
                              "compress_days": COMPRESS_DAYS,
                              "accent_color":  "#1DB954"}),
        ]:
            if key not in self.data:
                self.data[key] = default
        for name in ("Default", "Liked Songs"):
            if name not in self.data["playlists"]:
                self.data["playlists"][name] = {
                    "songs": [], "created": str(datetime.now())}
        self.save()

    def _load(self):
        if DATA_FILE.exists():
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    # songs ────────────────────────────────────────────────────────────────────
    def add_song(self, sid, meta):
        self.data["songs"][sid] = meta
        if sid not in self.data["playlists"]["Default"]["songs"]:
            self.data["playlists"]["Default"]["songs"].append(sid)
        self.save()

    def get_song(self, sid):
        return self.data["songs"].get(sid)

    def update_play_time(self, sid):
        s = self.data["songs"].get(sid)
        if s:
            s["last_played"] = str(datetime.now())
            s["play_count"]  = s.get("play_count", 0) + 1
        self.data["play_history"].insert(
            0, {"id": sid, "time": str(datetime.now())})
        self.data["play_history"] = self.data["play_history"][:200]
        self.save()

    # playlists ────────────────────────────────────────────────────────────────
    def get_playlists(self):
        return self.data["playlists"]

    def create_playlist(self, name):
        if name not in self.data["playlists"]:
            self.data["playlists"][name] = {
                "songs": [], "created": str(datetime.now())}
            self.save()
            return True
        return False

    def toggle_like(self, sid):
        pl = self.data["playlists"]["Liked Songs"]["songs"]
        if sid in pl:
            pl.remove(sid)
            liked = False
        else:
            pl.append(sid)
            liked = True
        self.save()
        return liked

    def is_liked(self, sid):
        return sid in self.data["playlists"]["Liked Songs"]["songs"]

    def add_to_playlist(self, playlist, sid):
        pl = self.data["playlists"].get(playlist)
        if pl and sid not in pl["songs"]:
            pl["songs"].append(sid)
            self.save()

    def remove_from_playlist(self, playlist, sid):
        pl = self.data["playlists"].get(playlist)
        if pl and sid in pl["songs"]:
            pl["songs"].remove(sid)
            self.save()

    # compression ──────────────────────────────────────────────────────────────
    def songs_needing_compression(self):
        days = self.data["settings"].get("compress_days", COMPRESS_DAYS)
        threshold = datetime.now() - timedelta(days=days)
        out = []
        for sid, m in self.data["songs"].items():
            if m.get("compressed"):
                continue
            fp = m.get("file")
            if not fp or not Path(fp).exists():
                continue
            lp = m.get("last_played")
            da = m.get("downloaded_at")
            ref = (datetime.fromisoformat(lp) if lp
                   else datetime.fromisoformat(da) if da else None)
            if ref and ref < threshold:
                out.append(sid)
        return out

    def validate_library(self):
        """Remove or flag songs whose files no longer exist. Returns list of pruned sids."""
        pruned = []
        for sid, m in list(self.data["songs"].items()):
            fp = m.get("file")
            if not fp or not Path(fp).exists():
                pruned.append(sid)
                # remove from all playlists
                for pl in self.data["playlists"].values():
                    if sid in pl.get("songs", []):
                        pl["songs"].remove(sid)
                del self.data["songs"][sid]
        if pruned:
            self.save()
        return pruned

    def get_recommendations(self):
        counts = {}
        for m in self.data["songs"].values():
            a = m.get("artist", "")
            if a:
                counts[a] = counts.get(a, 0) + m.get("play_count", 1)
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:3]
        return [a for a, _ in top]


dm = DataManager()


# ══════════════════════════════════════════════════════════════════════════════
# DOWNLOADER  (yt-dlp primary, pytubefix fallback)
# ══════════════════════════════════════════════════════════════════════════════
class Downloader:
    @staticmethod
    def _fmt(sec):
        if not sec:
            return "0:00"
        m, s = divmod(int(sec), 60)
        return f"{m}:{s:02d}"

    # ── search ─────────────────────────────────────────────────────────────────
    def search(self, query, n=12):
        """Try yt-dlp first; fall back to pytubefix."""
        results = []

        # ── yt-dlp search ──
        if YTDLP_AVAILABLE:
            try:
                opts = {
                    "quiet":           True,
                    "no_warnings":     True,
                    "extract_flat":    True,
                    "default_search":  "ytsearch",
                    "noplaylist":      True,
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(
                        f"ytsearch{n}:{query} music", download=False)
                    entries = info.get("entries", []) if info else []
                    for e in entries:
                        if not e:
                            continue
                        vid = e.get("id") or e.get("url", "")
                        results.append({
                            "id":           vid,
                            "title":        e.get("title", "Unknown"),
                            "artist":       e.get("uploader") or e.get("channel", "Unknown"),
                            "duration":     self._fmt(e.get("duration")),
                            "duration_sec": e.get("duration") or 0,
                            "thumbnail":    e.get("thumbnail") or
                                            f"https://img.youtube.com/vi/{vid}/mqdefault.jpg",
                        })
                    return results
            except Exception as ex:
                print(f"yt-dlp search error: {ex}")

        # ── pytubefix fallback ──
        if PYTUBE_AVAILABLE:
            try:
                from pytubefix import Search as PTSearch
                s = PTSearch(f"{query} music")
                for v in (s.videos or [])[:n]:
                    try:
                        results.append({
                            "id":           v.video_id,
                            "title":        v.title,
                            "artist":       v.author,
                            "duration":     self._fmt(v.length),
                            "duration_sec": v.length or 0,
                            "thumbnail":    v.thumbnail_url,
                        })
                    except Exception:
                        pass
            except Exception as ex:
                print(f"pytubefix search error: {ex}")

        return results

    # ── download ───────────────────────────────────────────────────────────────
    def download(self, video_data, progress_cb=None):
        vid    = video_data["id"]
        title  = video_data["title"]
        artist = video_data["artist"]
        dur    = video_data.get("duration_sec", 0)
        thumb  = video_data.get("thumbnail")
        url    = f"https://www.youtube.com/watch?v={vid}"

        safe = re.sub(r'[<>:"/\\|?*\n\r\t]', '', title).strip()[:80] or vid
        dest = MUSIC_DIR / f"{safe}.mp3"

        if not YTDLP_AVAILABLE and not PYTUBE_AVAILABLE:
            return False, "Install yt-dlp:  pip install yt-dlp"

        # ── yt-dlp download (preferred) ────────────────────────────────────────
        if YTDLP_AVAILABLE:
            try:
                if progress_cb:
                    progress_cb(5, "Preparing…")

                def _hook(d):
                    if not progress_cb:
                        return
                    status = d.get("status")
                    if status == "downloading":
                        total     = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        downloaded= d.get("downloaded_bytes", 0)
                        if total > 0:
                            pct = int(downloaded / total * 75) + 10
                            speed = d.get("_speed_str", "")
                            progress_cb(pct, f"Downloading… {speed}")
                        else:
                            progress_cb(40, "Downloading…")
                    elif status == "finished":
                        progress_cb(88, "Converting…")

                # Build postprocessors list conditionally
                postprocessors = [{"key": "FFmpegExtractAudio",
                                   "preferredcodec": "mp3",
                                   "preferredquality": "192"}]

                opts = {
                    "format":            "bestaudio/best",
                    "outtmpl":           str(TMP_DIR / f"{vid}.%(ext)s"),
                    "quiet":             True,
                    "no_warnings":       True,
                    "postprocessors":    postprocessors,
                    "progress_hooks":    [_hook],
                    "noplaylist":        True,
                    # if ffmpeg isn't available yt-dlp will still download raw audio
                    "ignoreerrors":      False,
                }

                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])

                # find output file (could be .mp3 or original container)
                tmp_mp3 = TMP_DIR / f"{vid}.mp3"
                if not tmp_mp3.exists():
                    # ffmpeg wasn't available – look for any audio file
                    candidates = sorted(TMP_DIR.glob(f"{vid}.*"),
                                        key=lambda p: p.stat().st_mtime,
                                        reverse=True)
                    if not candidates:
                        return False, "Download produced no file"
                    tmp_mp3 = candidates[0]

                # move to music dir
                if dest.exists():
                    dest.unlink()
                shutil.move(str(tmp_mp3), str(dest))

                # clean up any leftover temp files for this vid
                for f in TMP_DIR.glob(f"{vid}.*"):
                    try:
                        f.unlink()
                    except Exception:
                        pass

                if progress_cb:
                    progress_cb(95, "Saving…")

            except Exception as ex:
                print(f"yt-dlp download error: {ex}")
                # fall through to pytubefix
                if not PYTUBE_AVAILABLE:
                    return False, str(ex)
            else:
                # yt-dlp succeeded – store metadata and return
                return self._finish(vid, title, artist, dur, thumb, dest, progress_cb)

        # ── pytubefix fallback download ────────────────────────────────────────
        try:
            from pytubefix import YouTube
            if progress_cb:
                progress_cb(10, "Starting download…")

            def _pt_prog(stream, chunk, remaining):
                if progress_cb and stream.filesize:
                    pct = int((1 - remaining / stream.filesize) * 65) + 10
                    progress_cb(pct, "Downloading…")

            yt     = YouTube(url, on_progress_callback=_pt_prog)
            stream = yt.streams.filter(only_audio=True).order_by("abr").last()
            if not stream:
                return False, "No audio stream found"

            tmp_file = stream.download(output_path=str(TMP_DIR),
                                       filename=f"{vid}.tmp")
            if progress_cb:
                progress_cb(80, "Converting…")
            self._ffmpeg_convert(tmp_file, str(dest))

        except Exception as ex:
            return False, str(ex)

        return self._finish(vid, title, artist, dur, thumb, dest, progress_cb)

    def _finish(self, vid, title, artist, dur, thumb, dest, progress_cb):
        """Save thumbnail + metadata after audio is on disk."""
        # thumbnail
        thumb_path = None
        if thumb and REQUESTS_AVAILABLE:
            try:
                r = requests.get(thumb, timeout=6)
                thumb_path = str(THUMBNAILS_DIR / f"{vid}.jpg")
                with open(thumb_path, "wb") as f:
                    f.write(r.content)
            except Exception:
                pass

        meta = {
            "title":        title,
            "artist":       artist,
            "file":         str(dest),
            "duration":     self._fmt(dur),
            "duration_sec": dur,
            "thumbnail":    thumb_path or thumb,
            "downloaded_at":str(datetime.now()),
            "play_count":   0,
            "last_played":  None,
            "compressed":   False,
            "video_id":     vid,
        }
        dm.add_song(vid, meta)
        if progress_cb:
            progress_cb(100, "Done!")
        return True, meta

    def _ffmpeg_convert(self, src, dst):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", src,
                 "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k", dst],
                check=True, capture_output=True
            )
            try:
                os.remove(src)
            except Exception:
                pass
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                os.remove(dst)
            except Exception:
                pass
            shutil.move(src, dst)

    def compress(self, sid):
        m = dm.get_song(sid)
        if not m or not m.get("file"):
            return False
        p = Path(m["file"])
        if not p.exists():
            return False
        tmp = p.with_suffix(".cmp.mp3")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(p),
                 "-vn", "-ar", "22050", "-ac", "1", "-b:a", "64k", str(tmp)],
                check=True, capture_output=True
            )
            shutil.move(str(tmp), str(p))
            dm.data["songs"][sid]["compressed"] = True
            dm.save()
            return True
        except Exception:
            try:
                tmp.unlink()
            except Exception:
                pass
            return False


dl = Downloader()


# ══════════════════════════════════════════════════════════════════════════════
# PLAYER  (pygame – cross-platform, pause works on Windows)
# ══════════════════════════════════════════════════════════════════════════════
class Player:
    def __init__(self):
        self.current_meta = None
        self.is_playing   = False
        self.is_paused    = False
        self.start_time   = 0.0
        self.pause_offset = 0.0
        self.on_finish    = None
        self._app         = None

    def play(self, meta):
        self.stop()
        fp = meta.get("file")
        if not fp or not Path(fp).exists():
            return False
        if not PYGAME_AVAILABLE:
            return False
        try:
            pygame.mixer.music.load(fp)
            pygame.mixer.music.play()
            self.current_meta = meta
            self.is_playing   = True
            self.is_paused    = False
            self.start_time   = time.time()
            self.pause_offset = 0.0
            self._poll()
            return True
        except Exception as e:
            print(f"Player error: {e}")
            return False

    def toggle_pause(self):
        if not self.is_playing or not PYGAME_AVAILABLE:
            return
        if self.is_paused:
            pygame.mixer.music.unpause()
            self.start_time = time.time() - self.pause_offset
            self.is_paused  = False
            self._poll()
        else:
            pygame.mixer.music.pause()
            self.pause_offset = time.time() - self.start_time
            self.is_paused    = True

    def stop(self):
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self.is_playing   = False
        self.is_paused    = False
        self.current_meta = None
        self.pause_offset = 0.0

    def set_volume(self, v):
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.music.set_volume(max(0.0, min(1.0, float(v))))
            except Exception:
                pass

    @property
    def position(self):
        if not self.is_playing:
            return 0
        return int(self.pause_offset if self.is_paused
                   else time.time() - self.start_time)

    def _poll(self):
        if not self.is_playing or self.is_paused or not self._app:
            return
        if PYGAME_AVAILABLE and not pygame.mixer.music.get_busy():
            self.is_playing = False
            if self.on_finish:
                self.on_finish()
            return
        self._app.after(800, self._poll)


player = Player()


# ══════════════════════════════════════════════════════════════════════════════
# PLAYLIST DROPDOWN  (inline popover, no separate window)
# ══════════════════════════════════════════════════════════════════════════════
class PlaylistPopover(tk.Toplevel):
    """Dropdown popover anchored to the ⊕ button."""

    def __init__(self, master, song, anchor_widget, refresh_cb=None):
        super().__init__(master)
        self.song       = song
        self.refresh_cb = refresh_cb
        self.overrideredirect(True)
        self.configure(background=C["card"])

        self._build()
        self.update_idletasks()

        # position below anchor
        ax = anchor_widget.winfo_rootx()
        ay = anchor_widget.winfo_rooty() + anchor_widget.winfo_height() + 4
        # keep on screen
        sw = self.winfo_screenwidth()
        w  = self.winfo_reqwidth()
        if ax + w > sw:
            ax = sw - w - 4
        self.geometry(f"+{ax}+{ay}")

        # close on click outside
        self.bind("<FocusOut>", lambda e: self.destroy())
        self.focus_force()

    def _build(self):
        # header
        hf = tk.Frame(self, background=C["hover"])
        hf.pack(fill="x")
        tk.Label(hf, text="Add to playlist", background=C["hover"],
                 foreground=C["fg2"], font=("Arial", 10, "bold"),
                 padx=12, pady=8).pack(side="left")
        tk.Button(hf, text="✕", background=C["hover"], foreground=C["dim"],
                  relief="flat", bd=0, font=("Arial", 11),
                  command=self.destroy).pack(side="right", padx=8)

        # new playlist row
        nf = tk.Frame(self, background=C["card"])
        nf.pack(fill="x", padx=8, pady=(8, 4))
        self.entry = tk.Entry(nf, background=C["hover"], foreground=C["fg"],
                              insertbackground=C["fg"], relief="flat",
                              font=("Arial", 11), width=18)
        self.entry.pack(side="left", padx=(0, 4), ipady=4)
        self.entry.insert(0, "New playlist…")
        self.entry.bind("<FocusIn>",
                        lambda e: self.entry.delete(0, "end")
                        if self.entry.get() == "New playlist…" else None)
        self.entry.bind("<Return>", lambda e: self._create_add())
        tk.Button(nf, text="Create", background=C["accent"],
                  foreground=C["fg"], relief="flat", bd=0,
                  font=("Arial", 10, "bold"), padx=8, pady=4,
                  command=self._create_add).pack(side="left")

        sep = tk.Frame(self, background=C["hover"], height=1)
        sep.pack(fill="x", padx=8, pady=4)

        # existing playlists
        for name, pl in dm.get_playlists().items():
            if name == "Liked Songs":   # liked is handled by heart button
                continue
            sid  = self._sid()
            already = sid in pl.get("songs", [])
            row  = tk.Frame(self, background=C["card"], cursor="hand2")
            row.pack(fill="x", padx=4, pady=1)
            row.bind("<Enter>",
                     lambda e, r=row: r.configure(background=C["hover"]))
            row.bind("<Leave>",
                     lambda e, r=row: r.configure(background=C["card"]))
            icon = "✓ " if already else "   "
            lbl  = tk.Label(row, text=f"{icon}{name}",
                            background=C["card"], foreground=C["fg"],
                            font=("Arial", 11), padx=12, pady=6, anchor="w")
            lbl.pack(fill="x")
            lbl.bind("<Button-1>", lambda e, n=name: self._add(n))
            row.bind("<Button-1>", lambda e, n=name: self._add(n))

        # bottom padding
        tk.Frame(self, background=C["card"], height=6).pack()

    def _sid(self):
        return self.song.get("id") or self.song.get("video_id", "")

    def _create_add(self):
        name = self.entry.get().strip()
        if name and name != "New playlist…":
            dm.create_playlist(name)
            self._add(name)

    def _add(self, playlist):
        sid = self._sid()
        if sid:
            dm.add_to_playlist(playlist, sid)
        if self.refresh_cb:
            self.refresh_cb()
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
# SONG CARD
# ══════════════════════════════════════════════════════════════════════════════
class SongCard(ctk.CTkFrame):
    """
    Universal song card for both search results and library.
    Buttons shown:
      • ▶  play          (if downloaded)
      • ⬇  download      (if not downloaded) + progress bar
      • ♥  like toggle   always
      • ↗  open YouTube  always
      • ⊕  add to playlist dropdown  (if downloaded, so we have a sid)
    """
    def __init__(self, master, song,
                 on_play=None, on_download=None, on_like=None,
                 downloaded=False, refresh_sidebar=None, on_delete=None, **kw):
        super().__init__(master, fg_color=C["card"], corner_radius=8, **kw)
        self.song            = song
        self.on_play         = on_play
        self.on_download     = on_download
        self.on_like         = on_like
        self.downloaded      = downloaded
        self.refresh_sidebar = refresh_sidebar
        self.on_delete       = on_delete
        self._dl_active      = False
        self._build()
        self.bind("<Enter>", lambda e: self.configure(fg_color=C["hover"]))
        self.bind("<Leave>", lambda e: self.configure(fg_color=C["card"]))

    def _sid(self):
        return self.song.get("id") or self.song.get("video_id", "")

    def _build(self):
        self.grid_columnconfigure(1, weight=1)

        # ── thumbnail ──────────────────────────────────────────────────────────
        ico = ctk.CTkFrame(self, width=52, height=52,
                           fg_color=C["hover"], corner_radius=6)
        ico.grid(row=0, column=0, padx=(10, 8), pady=8, rowspan=2)
        ico.grid_propagate(False)
        self._note_lbl = ctk.CTkLabel(
            ico, text="♪", font=("Arial", 22), text_color=C["accent"])
        self._note_lbl.place(relx=.5, rely=.5, anchor="center")
        th = self.song.get("thumbnail")
        if th and PIL_AVAILABLE:
            threading.Thread(target=self._load_thumb, args=(th, ico),
                             daemon=True).start()

        # ── title / artist ─────────────────────────────────────────────────────
        ctk.CTkLabel(self,
                     text=self.song.get("title", "Unknown")[:65],
                     font=("Arial", 13, "bold"),
                     text_color=C["fg"], anchor="w"
                     ).grid(row=0, column=1, sticky="sw", padx=4)
        ctk.CTkLabel(self,
                     text=self.song.get("artist", "Unknown Artist")[:50],
                     font=("Arial", 11),
                     text_color=C["fg2"], anchor="w"
                     ).grid(row=1, column=1, sticky="nw", padx=4)

        # ── duration ───────────────────────────────────────────────────────────
        dur = self.song.get("duration", "")
        if dur:
            ctk.CTkLabel(self, text=dur, font=("Arial", 11),
                         text_color=C["dim"]
                         ).grid(row=0, column=2, padx=8, rowspan=2)

        # ── compressed badge ───────────────────────────────────────────────────
        if self.song.get("compressed"):
            ctk.CTkLabel(self, text="compressed", font=("Arial", 9),
                         text_color=C["warn"], fg_color=C["hover"],
                         corner_radius=4
                         ).grid(row=0, column=3, padx=4, rowspan=2)

        # ── action buttons ─────────────────────────────────────────────────────
        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.grid(row=0, column=4, padx=(4, 10), rowspan=2)
        self._bf = bf

        # Play (downloaded) or Download (not yet)
        if self.downloaded and self.on_play:
            pb = ctk.CTkButton(
                bf, text="▶", width=34, height=34,
                fg_color=C["accent"], hover_color=C["acc_h"],
                corner_radius=17, font=("Arial", 14),
                command=lambda: self.on_play(self.song))
            pb.pack(side="left", padx=3)
            Tooltip(pb, "Play")

        elif not self.downloaded and self.on_download:
            self.dl_btn = ctk.CTkButton(
                bf, text="⬇", width=34, height=34,
                fg_color=C["hover"], hover_color=C["acc_dim"],
                corner_radius=17, font=("Arial", 14),
                command=self._start_download)
            self.dl_btn.pack(side="left", padx=3)
            Tooltip(self.dl_btn, "Download song")

            # inline progress bar (hidden until download starts)
            self.prog_frame = ctk.CTkFrame(self, fg_color="transparent")
            self.prog_bar = ctk.CTkProgressBar(
                self.prog_frame, width=120, height=4,
                fg_color=C["prog_bg"], progress_color=C["accent"])
            self.prog_bar.set(0)
            self.prog_label = ctk.CTkLabel(
                self.prog_frame, text="", font=("Arial", 9),
                text_color=C["fg2"])
            self.prog_bar.pack()
            self.prog_label.pack()
            # placed in column 5 when visible
            self.prog_frame.grid(row=0, column=5, padx=(0, 6), rowspan=2)
            self.prog_frame.grid_remove()

        # Like button
        sid   = self._sid()
        liked = dm.is_liked(sid)
        heart = "♥" if liked else "♡"
        clr   = C["liked"] if liked else C["fg2"]
        self.like_btn = ctk.CTkButton(
            bf, text=heart, width=34, height=34,
            fg_color="transparent", hover_color=C["hover"],
            corner_radius=17, font=("Arial", 16),
            text_color=clr, command=self._toggle_like)
        self.like_btn.pack(side="left", padx=3)
        Tooltip(self.like_btn, "Like / Unlike")

        # Open on YouTube
        yt_btn = ctk.CTkButton(
            bf, text="▷ YT", width=40, height=34,
            fg_color="transparent", hover_color=C["hover"],
            corner_radius=8, font=("Arial", 10),
            text_color=C["dim"], command=self._open_yt)
        yt_btn.pack(side="left", padx=3)
        Tooltip(yt_btn, "Open on YouTube")

        # Add to playlist  (only if we have a saved song_id)
        if sid:
            pl_btn = ctk.CTkButton(
                bf, text="⊕", width=34, height=34,
                fg_color="transparent", hover_color=C["hover"],
                corner_radius=17, font=("Arial", 18),
                text_color=C["fg2"], command=self._open_playlist_popover)
            pl_btn.pack(side="left", padx=3)
            Tooltip(pl_btn, "Add to playlist")
            self._pl_btn = pl_btn

        # Delete button (only for downloaded songs)
        if self.downloaded and self.on_delete:
            del_btn = ctk.CTkButton(
                bf, text="🗑", width=34, height=34,
                fg_color="transparent", hover_color="#3a1010",
                corner_radius=17, font=("Arial", 14),
                text_color=C["dim"], command=self._confirm_delete)
            del_btn.pack(side="left", padx=3)
            Tooltip(del_btn, "Delete song")

        # Open in folder (plays the song + reveals file in explorer)
        if self.downloaded and self.song.get("file"):
            def _play_and_open(s=self.song):
                if self.on_play:

                    open_in_folder(s["file"])
            folder_btn = ctk.CTkButton(
                bf, text="📁", width=34, height=34,
                fg_color="transparent", hover_color=C["hover"],
                corner_radius=17, font=("Arial", 14),
                text_color=C["dim"], command=_play_and_open)
            folder_btn.pack(side="left", padx=3)
            Tooltip(folder_btn, "Play & show in folder")

    # ── helpers ────────────────────────────────────────────────────────────────
    def _load_thumb(self, url, container):
        try:
            from io import BytesIO
            if url.startswith("http") and REQUESTS_AVAILABLE:
                r   = requests.get(url, timeout=5)
                img = Image.open(BytesIO(r.content)).resize((52, 52))
            elif not url.startswith("http"):
                img = Image.open(url).resize((52, 52))
            else:
                return
            ci  = ctk.CTkImage(img, size=(52, 52))
            lbl = ctk.CTkLabel(container, image=ci, text="")
            lbl.place(relx=0, rely=0, relwidth=1, relheight=1)
        except Exception:
            pass

    def _toggle_like(self):
        sid   = self._sid()
        if not sid:
            return
        # If not yet downloaded we still allow liking by sid alone
        liked = dm.toggle_like(sid)
        self.like_btn.configure(
            text="♥" if liked else "♡",
            text_color=C["liked"] if liked else C["fg2"])
        if self.on_like:
            self.on_like(sid, liked)

    def _open_yt(self):
        vid = self._sid()
        if vid:
            webbrowser.open(f"https://www.youtube.com/watch?v={vid}")

    def _open_playlist_popover(self):
        if hasattr(self, "_pl_btn"):
            PlaylistPopover(self.winfo_toplevel(), self.song,
                            self._pl_btn,
                            refresh_cb=self.refresh_sidebar)

    def _confirm_delete(self):
        title = self.song.get("title", "this song")[:40]
        if messagebox.askyesno("Delete Song",
                               f"Delete '{title}'?\nThis removes the file from disk.",
                               parent=self.winfo_toplevel()):
            if self.on_delete:
                self.on_delete()

    def _start_download(self):
        if self._dl_active:
            return
        self._dl_active = True
        self.dl_btn.configure(state="disabled", text="…")
        self.prog_frame.grid()
        if self.on_download:
            self.on_download(self.song, self._update_progress,
                             self._download_done)

    def _update_progress(self, pct, msg):
        """Called from download thread via app.after()."""
        try:
            self.prog_bar.set(pct / 100)
            self.prog_label.configure(text=msg[:28])
        except Exception:
            pass

    def _download_done(self, ok, err_msg="", meta=None):
        self._dl_active = False
        try:
            if ok:
                self.prog_frame.grid_remove()
                self.dl_btn.destroy()
                # Get the freshest meta from dm (guaranteed to have correct file path)
                sid = self._sid()
                live_meta = dm.get_song(sid) or meta or self.song

                # Find the app instance to use its _play_song method reliably
                app = self.winfo_toplevel()
                play_fn = getattr(app, "_play_song", None) or self.on_play

                pb = ctk.CTkButton(
                    self._bf, text="▶", width=34, height=34,
                    fg_color=C["accent"], hover_color=C["acc_h"],
                    corner_radius=17, font=("Arial", 14),
                    command=lambda: play_fn(dm.get_song(sid) or live_meta) if play_fn else None)
                pb.pack(side="left", padx=3, before=self.like_btn)
                Tooltip(pb, "Play")
                self.downloaded = True

                # Add playlist button if not already there
                if sid and not hasattr(self, "_pl_btn"):
                    pl_btn = ctk.CTkButton(
                        self._bf, text="⊕", width=34, height=34,
                        fg_color="transparent", hover_color=C["hover"],
                        corner_radius=17, font=("Arial", 18),
                        text_color=C["fg2"], command=self._open_playlist_popover)
                    pl_btn.pack(side="left", padx=3)
                    Tooltip(pl_btn, "Add to playlist")
                    self._pl_btn = pl_btn

                # Add delete button
                if not hasattr(self, "_del_btn"):
                    del_btn = ctk.CTkButton(
                        self._bf, text="🗑", width=34, height=34,
                        fg_color="transparent", hover_color="#3a1010",
                        corner_radius=17, font=("Arial", 14),
                        text_color=C["dim"], command=self._confirm_delete)
                    del_btn.pack(side="left", padx=3)
                    Tooltip(del_btn, "Delete song")
                    self._del_btn = del_btn
                    # Wire delete to app
                    self.on_delete = lambda s=sid: getattr(app, "_delete_song", lambda x: None)(s)
            else:
                self.dl_btn.configure(state="normal", text="↺",
                                      fg_color="#c0392b")
                self.prog_label.configure(text=err_msg[:28])
        except Exception as e:
            print(f"_download_done error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class MelodifyApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Melodify")
        self.geometry("1200x760")
        self.minsize(900, 620)
        self.configure(fg_color=C["bg"])

        player._app      = self
        player.on_finish = self._on_song_finish

        self.current_song    = None
        self.queue           = []
        self.autoplay_list   = []   # flat list of metas for current context
        self.autoplay_idx    = -1   # current position in autoplay_list
        self.shuffle_mode    = False
        self.repeat_mode     = False  # repeat single song
        self._shuffle_order  = []   # shuffled indices
        self._lyrics_cache    = None
        self._lyrics_loading  = False
        self._np_win          = None
        self._np_lyrics_ready = False

        self._build_ui()
        # Validate library on every launch
        pruned = dm.validate_library()
        if pruned:
            print(f"Removed {len(pruned)} missing song(s) from library.")

        if not FFMPEG_AVAILABLE:
            self.after(200, self._show_ffmpeg_installer)
        else:
            self._show_home()
        self._tick_player()
        self.after(60_000, self._auto_compress_check)

    # ── FFMPEG INSTALLER SCREEN ───────────────────────────────────────────────
    def _show_ffmpeg_installer(self):
        """Show a friendly ffmpeg installation screen."""
        self._clear()

        outer = ctk.CTkFrame(self.content, fg_color="transparent")
        outer.pack(expand=True, fill="both", pady=40)

        card = ctk.CTkFrame(outer, fg_color=C["card"], corner_radius=16)
        card.pack(padx=60, pady=20, fill="x")

        ctk.CTkLabel(card, text="⚡", font=("Arial", 52)).pack(pady=(28, 4))
        ctk.CTkLabel(card, text="ffmpeg is not installed",
                     font=("Arial", 22, "bold"),
                     text_color=C["fg"]).pack()
        ctk.CTkLabel(card,
                     text="ffmpeg is needed to convert audio files.\nDon't worry — we can install it for you automatically!",
                     font=("Arial", 13), text_color=C["fg2"],
                     justify="center").pack(pady=(8, 20))

        self._ffmpeg_log = ctk.CTkTextbox(card, height=120, font=("Courier", 11),
                                          fg_color=C["bg"], text_color=C["fg2"],
                                          state="disabled")
        self._ffmpeg_log.pack(fill="x", padx=20, pady=(0, 16))

        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(pady=(0, 24))

        self._install_btn = ctk.CTkButton(
            btn_frame, text="Install ffmpeg automatically",
            font=("Arial", 14, "bold"),
            fg_color=C["accent"], hover_color=C["acc_h"],
            height=44, width=260,
            command=self._run_ffmpeg_install)
        self._install_btn.pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame, text="Skip (reduced quality)",
            font=("Arial", 13),
            fg_color=C["hover"], hover_color=C["bg"],
            height=44, width=200,
            command=self._show_home
        ).pack(side="left", padx=8)

    def _ffmpeg_log_append(self, text):
        try:
            self._ffmpeg_log.configure(state="normal")
            self._ffmpeg_log.insert("end", text + "\n")
            self._ffmpeg_log.see("end")
            self._ffmpeg_log.configure(state="disabled")
        except Exception:
            pass

    def _run_ffmpeg_install(self):
        self._install_btn.configure(state="disabled",
                                    text="Installing…")
        threading.Thread(target=self._do_ffmpeg_install, daemon=True).start()

    def _do_ffmpeg_install(self):
        import platform
        system = platform.system()

        def log(msg):
            self.after(0, lambda m=msg: self._ffmpeg_log_append(m))

        def run_logged(cmd, shell=False):
            cmd_label = cmd if isinstance(cmd, str) else " ".join(cmd)
            log(f"$ {cmd_label}")
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=shell
            )
            lines = []
            if p.stdout:
                for line in p.stdout:
                    line = line.rstrip()
                    if line:
                        log(line)
                        lines.append(line)
            p.wait()
            return p.returncode, "\n".join(lines)

        def done(ok):
            global FFMPEG_AVAILABLE
            FFMPEG_AVAILABLE = _check_ffmpeg()
            if ok and FFMPEG_AVAILABLE:
                self.after(0, lambda: self._ffmpeg_log_append("✅ ffmpeg installed successfully!"))
                self.after(800, self._show_home)
            else:
                self.after(0, lambda: self._ffmpeg_log_append(
                    "❌ Automatic install failed.\n"
                    "Please install manually:\n"
                    "  Windows: winget install ffmpeg\n"
                    "  Mac:     brew install ffmpeg\n"
                    "  Linux:   sudo apt install ffmpeg"))
                self.after(0, lambda: self._install_btn.configure(
                    state="normal", text="Try again"))

        try:
            if system == "Windows":
                ps = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
                scoop_cmd = Path.home() / "scoop" / "shims" / "scoop.cmd"

                log("Checking for Scoop package manager...")
                scoop_check, _ = run_logged(["where.exe", "scoop"])
                if scoop_check != 0 and scoop_cmd.exists():
                    scoop_check = 0
                    log(f"Using local Scoop shim: {scoop_cmd}")

                if scoop_check != 0:
                    log("Scoop not found - installing Scoop...")
                    install_scoop = (
                        "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force; "
                        "Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression"
                    )
                    rc, _ = run_logged(ps + [install_scoop])
                    if rc != 0:
                        log("Scoop install failed.")
                        # Try winget as fallback
                        log("Trying winget instead...")
                        rc2, _ = run_logged(
                            ["winget", "install", "--id=Gyan.FFmpeg", "-e",
                             "--accept-package-agreements", "--accept-source-agreements"]
                        )
                        done(rc2 == 0)
                        return
                    log("Scoop installed.")
                else:
                    log("Scoop already installed.")

                # Scoop may not be available in PATH until shell restart.
                scoop_runner = [str(scoop_cmd)] if scoop_cmd.exists() else ps + ["scoop"]
                log("Installing ffmpeg via Scoop...")
                rc, _ = run_logged(scoop_runner + ["install", "ffmpeg"])
                if rc != 0:
                    log("Scoop ffmpeg failed, trying winget...")
                    rc2, _ = run_logged(
                        ["winget", "install", "--id=Gyan.FFmpeg", "-e",
                         "--accept-package-agreements", "--accept-source-agreements"]
                    )
                    done(rc2 == 0)
                    return
                done(True)

            elif system == "Darwin":
                log("Checking for Homebrew…")
                brew = subprocess.run(["which", "brew"], capture_output=True)
                if brew.returncode != 0:
                    log("Installing Homebrew…")
                    subprocess.run(
                        ["/bin/bash", "-c",
                         '$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)'],
                        check=True)
                log("Installing ffmpeg via Homebrew…")
                result = subprocess.run(["brew", "install", "ffmpeg"],
                                        capture_output=True, text=True)
                done(result.returncode == 0)

            else:  # Linux
                log("Installing ffmpeg via apt…")
                result = subprocess.run(
                    ["sudo", "apt-get", "install", "-y", "ffmpeg"],
                    capture_output=True, text=True)
                if result.returncode != 0:
                    log("apt failed, trying snap…")
                    result2 = subprocess.run(
                        ["sudo", "snap", "install", "ffmpeg"],
                        capture_output=True, text=True)
                    done(result2.returncode == 0)
                    return
                done(True)

        except Exception as ex:
            log(f"Error: {ex}")
            done(False)

    # ── build ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self._build_sidebar()
        self._build_main()
        self._build_player_bar()

    # ── SIDEBAR ────────────────────────────────────────────────────────────────
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=C["sidebar"],
                          corner_radius=12, width=220)
        sb.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        sb.grid_propagate(False)
        sb.grid_rowconfigure(7, weight=1)

        self.logo_lbl = ctk.CTkLabel(sb, text="♫  Melodify",
                     font=("Arial", 22, "bold"),
                     text_color=C["accent"])
        self.logo_lbl.grid(row=0, column=0, padx=20, pady=(20, 25), sticky="w")

        for i, (lbl, cmd) in enumerate([
            ("🏠  Home",    self._show_home),
            ("🔍  Search",  self._show_search_view),
            ("📚  Library", self._show_library),
        ], 1):
            ctk.CTkButton(
                sb, text=lbl, anchor="w", font=("Arial", 13),
                fg_color="transparent", hover_color=C["hover"],
                text_color=C["fg"], height=40, command=cmd
            ).grid(row=i, column=0, sticky="ew", padx=10, pady=2)

        ctk.CTkFrame(sb, height=1, fg_color=C["hover"]
                     ).grid(row=4, column=0, sticky="ew", padx=10, pady=12)

        ph = ctk.CTkFrame(sb, fg_color="transparent")
        ph.grid(row=5, column=0, sticky="ew", padx=12)
        ph.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(ph, text="PLAYLISTS",
                     font=("Arial", 11, "bold"),
                     text_color=C["dim"]).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(ph, text="+", width=24, height=24,
                      fg_color=C["hover"], hover_color=C["accent"],
                      command=self._create_playlist_dlg
                      ).grid(row=0, column=1)

        self.pl_list = ctk.CTkScrollableFrame(
            sb, fg_color="transparent", height=260)
        self.pl_list.grid(row=6, column=0, sticky="nsew", padx=5)
        self._refresh_pl_sidebar()

        ctk.CTkButton(
            sb, text="🗜  Compress Old Songs", anchor="w",
            font=("Arial", 11), fg_color="transparent",
            hover_color=C["hover"], text_color=C["fg2"],
            command=self._manual_compress
        ).grid(row=8, column=0, sticky="ew", padx=10, pady=2)

        ctk.CTkButton(
            sb, text="⚙  Settings", anchor="w",
            font=("Arial", 11), fg_color="transparent",
            hover_color=C["hover"], text_color=C["fg2"],
            command=self._show_settings
        ).grid(row=9, column=0, sticky="ew", padx=10, pady=(2, 12))

    def _refresh_pl_sidebar(self):
        for w in self.pl_list.winfo_children():
            w.destroy()
        for name in dm.get_playlists():
            ctk.CTkButton(
                self.pl_list, text=f"▤  {name}", anchor="w",
                font=("Arial", 12), fg_color="transparent",
                hover_color=C["hover"], text_color=C["fg2"], height=32,
                command=lambda n=name: self._show_playlist(n)
            ).pack(fill="x", pady=1)

    # ── MAIN AREA ──────────────────────────────────────────────────────────────
    def _build_main(self):
        self.main = ctk.CTkFrame(self, fg_color=C["bg2"], corner_radius=12)
        self.main.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self.main, fg_color="transparent", height=60)
        top.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 5))
        top.grid_columnconfigure(1, weight=1)
        top.grid_propagate(False)

        ctk.CTkButton(top, text="◀", width=32, height=32,
                      fg_color=C["hover"], hover_color=C["card"],
                      command=self._show_home
                      ).grid(row=0, column=0, padx=(0, 8))

        self.search_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(
            top, textvariable=self.search_var,
            placeholder_text="Search songs, artists…",
            font=("Arial", 13), height=36,
            fg_color=C["hover"], border_color=C["card"])
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=5)
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        ctk.CTkButton(
            top, text="Search", width=80, height=36,
            fg_color=C["accent"], hover_color=C["acc_h"],
            command=self._do_search
        ).grid(row=0, column=2, padx=(5, 0))

        self.content = ctk.CTkScrollableFrame(
            self.main, fg_color="transparent",
            scrollbar_button_color=C["hover"])
        self.content.grid(row=1, column=0, sticky="nsew",
                          padx=15, pady=(0, 10))
        self.content.grid_columnconfigure(0, weight=1)

    def _clear(self):
        for w in self.content.winfo_children():
            w.destroy()

    # ── PLAYER BAR ─────────────────────────────────────────────────────────────
    def _build_player_bar(self):
        bar = ctk.CTkFrame(self, fg_color=C["card"],
                           corner_radius=0, height=92)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        # song info — clickable to open now-playing view
        info = ctk.CTkFrame(bar, fg_color="transparent", width=260, cursor="hand2")
        info.grid(row=0, column=0, padx=20, pady=10, sticky="w")
        info.grid_propagate(False)
        self.bar_title = ctk.CTkLabel(
            info, text="No song playing",
            font=("Arial", 13, "bold"), text_color=C["fg"],
            width=240, anchor="w")
        self.bar_title.pack(anchor="w")
        self.bar_artist = ctk.CTkLabel(
            info, text="", font=("Arial", 11),
            text_color=C["fg2"], width=240, anchor="w")
        self.bar_artist.pack(anchor="w")
        # click anywhere on info to open now-playing
        for w in (info, self.bar_title, self.bar_artist):
            w.bind("<Button-1>", lambda e: self._open_now_playing())

        # controls
        ctrl = ctk.CTkFrame(bar, fg_color="transparent")
        ctrl.grid(row=0, column=1, pady=5)

        self.prev_btn = ctk.CTkButton(
            ctrl, text="⏮", width=36, height=36,
            fg_color="transparent", hover_color=C["hover"],
            font=("Arial", 16), command=self._prev_song)
        self.prev_btn.pack(side="left", padx=5)

        self.play_btn = ctk.CTkButton(
            ctrl, text="▶", width=46, height=46,
            fg_color=C["accent"], hover_color=C["acc_h"],
            corner_radius=23, font=("Arial", 18),
            command=self._toggle_pause)
        self.play_btn.pack(side="left", padx=5)

        self.next_btn = ctk.CTkButton(
            ctrl, text="⏭", width=36, height=36,
            fg_color="transparent", hover_color=C["hover"],
            font=("Arial", 16), command=self._next_song)
        self.next_btn.pack(side="left", padx=5)

        self.shuffle_btn = ctk.CTkButton(
            ctrl, text="⇄", width=34, height=34,
            fg_color="transparent", hover_color=C["hover"],
            font=("Arial", 15), text_color=C["dim"],
            command=self._toggle_shuffle)
        self.shuffle_btn.pack(side="left", padx=3)
        Tooltip(self.shuffle_btn, "Shuffle")

        self.repeat_btn = ctk.CTkButton(
            ctrl, text="↺", width=34, height=34,
            fg_color="transparent", hover_color=C["hover"],
            font=("Arial", 15), text_color=C["dim"],
            command=self._toggle_repeat)
        self.repeat_btn.pack(side="left", padx=3)
        Tooltip(self.repeat_btn, "Repeat song")

        # progress (draggable)
        pf = ctk.CTkFrame(bar, fg_color="transparent")
        pf.grid(row=0, column=2, padx=20)
        self.time_lbl = ctk.CTkLabel(
            pf, text="0:00 / 0:00",
            font=("Arial", 10), text_color=C["fg2"])
        self.time_lbl.pack()

        # custom draggable seek bar
        self._seek_dragging  = False
        self._seek_val       = 0.0   # 0.0–1.0
        SEEK_W, SEEK_H = 220, 16

        self._seek_canvas = tk.Canvas(
            pf, width=SEEK_W, height=SEEK_H,
            bg=C["card"], highlightthickness=0, cursor="hand2")
        self._seek_canvas.pack()

        def _draw_seek(val):
            c = self._seek_canvas
            c.delete("all")
            # track background
            y = SEEK_H // 2
            c.create_line(0, y, SEEK_W, y, fill=C["prog_bg"], width=4, capstyle="round")
            # filled portion
            filled = max(4, int(val * SEEK_W))
            c.create_line(0, y, filled, y, fill=C["accent"], width=4, capstyle="round")
            # thumb dot
            r = 6
            c.create_oval(filled - r, y - r, filled + r, y + r,
                          fill=C["accent"], outline=C["acc_h"], width=1)

        self._draw_seek = _draw_seek
        _draw_seek(0)

        def _seek_press(e):
            self._seek_dragging = True
            _seek_move(e)

        def _seek_move(e):
            if self._seek_dragging:
                val = max(0.0, min(1.0, e.x / SEEK_W))
                self._seek_val = val
                _draw_seek(val)

        def _seek_release(e):
            if not self._seek_dragging:
                return
            self._seek_dragging = False
            val = max(0.0, min(1.0, e.x / SEEK_W))
            # seek pygame
            if PYGAME_AVAILABLE and self.current_song:
                dur = self.current_song.get("duration_sec", 0) or 0
                if dur > 0:
                    target_sec = val * dur
                    try:
                        pygame.mixer.music.set_pos(target_sec)
                        # recalculate start_time so position tracking stays correct
                        player.start_time   = time.time() - target_sec
                        player.pause_offset = target_sec
                    except Exception as ex:
                        print(f"Seek error: {ex}")

        self._seek_canvas.bind("<ButtonPress-1>",   _seek_press)
        self._seek_canvas.bind("<B1-Motion>",        _seek_move)
        self._seek_canvas.bind("<ButtonRelease-1>",  _seek_release)

        # keep a reference so _tick_player can call it
        self.prog_bar = None  # legacy ref – not used any more

        # volume
        vf = ctk.CTkFrame(bar, fg_color="transparent")
        vf.grid(row=0, column=3, padx=20)
        ctk.CTkLabel(vf, text="🔊", font=("Arial", 14)).pack(side="left")
        self.vol_slider = ctk.CTkSlider(
            vf, width=80, from_=0, to=100,
            button_color=C["fg2"],
            command=lambda v: player.set_volume(float(v) / 100))
        self.vol_slider.set(70)
        self.vol_slider.pack(side="left", padx=5)
        player.set_volume(0.70)

    # ═══════════════════════════════════════════════════════════════════════════
    # VIEWS
    # ═══════════════════════════════════════════════════════════════════════════

    def _show_home(self):
        self._clear()
        ctk.CTkLabel(self.content, text="Good evening 👋",
                     font=("Arial", 28, "bold"),
                     text_color=C["fg"]).pack(anchor="w", pady=(10, 5))

        # recently played
        hist = [h["id"] for h in dm.data.get("play_history", [])[:6]]
        if hist:
            ctk.CTkLabel(self.content, text="Recently Played",
                         font=("Arial", 18, "bold"),
                         text_color=C["fg"]).pack(anchor="w", pady=(20, 8))
            g = ctk.CTkFrame(self.content, fg_color="transparent")
            g.pack(fill="x")
            for c in range(3):
                g.grid_columnconfigure(c, weight=1)
            for i, sid in enumerate(hist):
                m = dm.get_song(sid)
                if m:
                    self._mini_card(g, m).grid(
                        row=i // 3, column=i % 3,
                        padx=5, pady=5, sticky="ew")

        # recommendations
        recs = dm.get_recommendations()
        if recs:
            ctk.CTkLabel(self.content, text="More like what you love",
                         font=("Arial", 18, "bold"),
                         text_color=C["fg"]).pack(anchor="w", pady=(22, 4))
            ctk.CTkLabel(self.content,
                         text=f"Based on: {', '.join(recs)}",
                         font=("Arial", 12),
                         text_color=C["fg2"]).pack(anchor="w", pady=(0, 8))
            for a in recs[:2]:
                ctk.CTkButton(
                    self.content,
                    text=f"🔍  Find more from {a}",
                    anchor="w", fg_color=C["card"],
                    hover_color=C["hover"],
                    text_color=C["fg"], height=44,
                    font=("Arial", 13),
                    command=lambda x=a: self._quick_search(x)
                ).pack(fill="x", pady=3)

        # songs
        ctk.CTkLabel(self.content, text="Your Songs",
                     font=("Arial", 18, "bold"),
                     text_color=C["fg"]).pack(anchor="w", pady=(22, 8))
        songs = list(dm.data["songs"].values())
        if songs:
            for m in songs[:6]:
                SongCard(self.content, m,
                         on_play=self._play_song,
                         downloaded=True,
                         refresh_sidebar=self._refresh_pl_sidebar
                         ).pack(fill="x", pady=3)
            if len(songs) > 6:
                ctk.CTkButton(
                    self.content, text="See all  →",
                    fg_color="transparent", text_color=C["accent"],
                    hover_color=C["hover"], anchor="w",
                    command=self._show_library
                ).pack(anchor="w", pady=4)
        else:
            f = ctk.CTkFrame(self.content, fg_color=C["card"],
                             corner_radius=12)
            f.pack(fill="x", pady=20)
            ctk.CTkLabel(f, text="🎵",
                         font=("Arial", 48)).pack(pady=(18, 4))
            ctk.CTkLabel(f,
                         text="No music yet — search and download!",
                         font=("Arial", 14, "bold"),
                         text_color=C["fg"]).pack()
            ctk.CTkLabel(f,
                         text="Use the search bar above to find songs.",
                         font=("Arial", 12),
                         text_color=C["fg2"]).pack(pady=(4, 18))

    def _mini_card(self, master, meta):
        f = ctk.CTkFrame(master, fg_color=C["card"],
                         corner_radius=8, height=56, cursor="hand2")
        f.grid_columnconfigure(1, weight=1)
        f.grid_propagate(False)
        ctk.CTkLabel(f, text="♪", font=("Arial", 18),
                     fg_color=C["hover"], width=56, height=56,
                     corner_radius=4).grid(row=0, column=0)
        ctk.CTkLabel(f, text=meta.get("title", "")[:28],
                     font=("Arial", 12, "bold"),
                     text_color=C["fg"], anchor="w"
                     ).grid(row=0, column=1, padx=8, sticky="w")
        cb = lambda e, m=meta: self._play_song(m)
        f.bind("<Button-1>", cb)
        for child in f.winfo_children():
            child.bind("<Button-1>", cb)
        return f

    # ── SEARCH ─────────────────────────────────────────────────────────────────
    def _show_search_view(self):
        self._clear()
        ctk.CTkLabel(self.content, text="Browse Genres",
                     font=("Arial", 22, "bold"),
                     text_color=C["fg"]).pack(anchor="w", pady=(10, 15))
        genres = [
            ("Pop", "#E74C3C"), ("Rock", "#3498DB"),
            ("Hip-Hop", "#9B59B6"), ("Electronic", "#1ABC9C"),
            ("Jazz", "#F39C12"), ("Classical", "#2ECC71"),
            ("R&B", "#E67E22"), ("Lo-fi", "#1DB954"),
        ]
        g = ctk.CTkFrame(self.content, fg_color="transparent")
        g.pack(fill="x")
        for c in range(4):
            g.grid_columnconfigure(c, weight=1)
        for i, (genre, clr) in enumerate(genres):
            ctk.CTkButton(
                g, text=genre, fg_color=clr, hover_color=clr,
                height=65, font=("Arial", 14, "bold"), corner_radius=8,
                command=lambda x=genre: self._quick_search(x + " music")
            ).grid(row=i // 4, column=i % 4, padx=5, pady=5, sticky="ew")

    def _quick_search(self, q):
        self.search_var.set(q)
        self._do_search()

    def _do_search(self):
        q = self.search_var.get().strip()
        if not q:
            return
        self._clear()
        ctk.CTkLabel(self.content,
                     text=f'🔍  Searching for "{q}"…',
                     font=("Arial", 15),
                     text_color=C["fg2"]).pack(pady=40)
        self.update()
        threading.Thread(target=lambda: self._run_search(q),
                         daemon=True).start()

    def _run_search(self, q):
        results = dl.search(q)
        orig = self._detect_original(results, q)
        self.after(0, lambda: self._show_results(results, q, orig))

    @staticmethod
    def _detect_original(results: list, query: str) -> dict | None:
        """
        Pick the most likely original/official upload.
        Prefer official audio over music video (audio is the song itself).
        """
        if not results:
            return None

        def _score(r):
            ch = (r.get("artist") or "").lower()
            ti = (r.get("title")  or "").lower()
            if "vevo" in ch and ("audio" in ti or "official audio" in ti): return 0
            if "vevo" in ch:                                                return 1
            if "official audio" in ti:                                      return 2
            if "official" in ch:                                            return 3
            if "official video" in ti or "official music video" in ti:      return 4
            if "official" in ti:                                            return 5
            return 9

        best = min(results, key=_score)
        artist = re.sub(r'(?i)\s*vevo$|\s*-\s*topic$', '', best.get("artist", "")).strip()
        return {
            "artist": artist or best.get("artist", ""),
            "title":  best.get("title", query),
            "yt_id":  best.get("id", ""),
            "result": best,   # full result dict for SongCard
        }

    def _show_results(self, results, q, orig=None):
        self._clear()
        ctk.CTkLabel(self.content,
                     text=f'Results for "{q}"',
                     font=("Arial", 20, "bold"),
                     text_color=C["fg"]).pack(anchor="w", pady=(10, 8))

        # ── Pinned original at top ─────────────────────────────────────────────
        if orig and orig.get("result"):
            best = orig["result"]
            oa   = orig["artist"]

            # Small label above
            tk.Label(self.content,
                     text=f"  ✓  Original · {oa}  ",
                     font=("Arial", 10, "bold"),
                     bg=C["bg2"], fg=C["accent"]
                     ).pack(anchor="w", pady=(0, 2))

            already = best["id"] in dm.data["songs"]
            SongCard(self.content, best,
                     on_play=self._play_song if already else None,
                     on_download=self._download_song if not already else None,
                     downloaded=already,
                     refresh_sidebar=self._refresh_pl_sidebar,
                     ).pack(fill="x", pady=(0, 2))

            # thin divider
            tk.Frame(self.content, bg=C["hover"], height=1).pack(fill="x", pady=(4, 8))

            # remove the pinned entry from the rest so it doesn't appear twice
            results = [r for r in results if r["id"] != best["id"]]

        # ── Remaining results ─────────────────────────────────────────────────
        if not results and not orig:
            ctk.CTkLabel(self.content,
                         text="No results. Make sure yt-dlp is installed:\n  pip install yt-dlp",
                         font=("Arial", 13), text_color=C["fg2"]).pack(pady=20)
            return
        for r in results:
            already = r["id"] in dm.data["songs"]
            SongCard(self.content, r,
                     on_play=self._play_song if already else None,
                     on_download=self._download_song if not already else None,
                     downloaded=already,
                     refresh_sidebar=self._refresh_pl_sidebar,
                     ).pack(fill="x", pady=3)

    # ── LIBRARY ────────────────────────────────────────────────────────────────
    def _show_library(self):
        self._clear()
        ctk.CTkLabel(self.content, text="Your Library",
                     font=("Arial", 28, "bold"),
                     text_color=C["fg"]).pack(anchor="w", pady=(10, 12))
        songs = list(dm.data["songs"].items())
        if not songs:
            ctk.CTkLabel(
                self.content,
                text="No songs yet – search and download!",
                font=("Arial", 13),
                text_color=C["fg2"]
            ).pack(pady=30)
            return

        total_mb   = sum(
            os.path.getsize(m["file"])
            for _, m in songs
            if m.get("file") and os.path.exists(m["file"])
        ) // (1024 * 1024)
        compressed = sum(1 for _, m in songs if m.get("compressed"))

        sf = ctk.CTkFrame(self.content, fg_color=C["card"], corner_radius=8)
        sf.pack(fill="x", pady=(0, 12))
        for c in range(3):
            sf.grid_columnconfigure(c, weight=1)
        for i, (val, lbl) in enumerate([
            (f"{len(songs)}", "Songs"),
            (f"{total_mb} MB", "Storage"),
            (f"{compressed}", "Compressed"),
        ]):
            ctk.CTkLabel(sf, text=f"{val}\n{lbl}",
                         font=("Arial", 14, "bold"),
                         text_color=C["fg"]
                         ).grid(row=0, column=i, pady=14)

        all_metas = [m for _, m in songs]

        def _play_from_library(m):
            self.autoplay_list = list(all_metas)
            self.autoplay_idx  = all_metas.index(m) if m in all_metas else 0
            self._shuffle_order = []
            self._play_song(m)

        for sid, m in songs:
            SongCard(self.content, m,
                     on_play=_play_from_library,
                     downloaded=True,
                     refresh_sidebar=self._refresh_pl_sidebar,
                     on_delete=lambda s=sid: self._delete_song(s),
                     ).pack(fill="x", pady=3)

    # ── PLAYLIST VIEW ───────────────────────────────────────────────────────────
    def _show_playlist(self, name):
        self._clear()
        pl = dm.get_playlists().get(name, {})
        ids = pl.get("songs", [])
        metas = [m for sid in ids for m in [dm.get_song(sid)] if m]

        h = ctk.CTkFrame(self.content, fg_color=C["card"],
                         corner_radius=12, height=130)
        h.pack(fill="x", pady=(0, 15))
        h.pack_propagate(False)
        ctk.CTkLabel(h, text="▤", font=("Arial", 48),
                     text_color=C["accent"]).pack(side="left", padx=20)
        inf = ctk.CTkFrame(h, fg_color="transparent")
        inf.pack(side="left", fill="y", pady=12)
        ctk.CTkLabel(inf, text="PLAYLIST",
                     font=("Arial", 11),
                     text_color=C["fg2"]).pack(anchor="w")
        ctk.CTkLabel(inf, text=name,
                     font=("Arial", 24, "bold"),
                     text_color=C["fg"]).pack(anchor="w")
        ctk.CTkLabel(inf,
                     text=f"{len(metas)} songs",
                     font=("Arial", 12),
                     text_color=C["fg2"]).pack(anchor="w")

        # Play All / Shuffle buttons
        if metas:
            btn_row = ctk.CTkFrame(h, fg_color="transparent")
            btn_row.pack(side="left", padx=20, pady=10, anchor="s")

            def play_all():
                import random as _rnd
                self.autoplay_list = list(metas)
                self.autoplay_idx  = 0
                self._shuffle_order = []
                self.shuffle_mode   = False
                self.shuffle_btn.configure(text_color=C["dim"])
                self._play_song(metas[0])

            def play_shuffle():
                import random as _rnd
                shuffled = list(metas)
                _rnd.shuffle(shuffled)
                self.autoplay_list  = shuffled
                self.autoplay_idx   = 0
                self._shuffle_order = []
                self.shuffle_mode   = True
                self.shuffle_btn.configure(text_color=C["accent"])
                self._play_song(shuffled[0])

            ctk.CTkButton(btn_row, text="▶  Play All",
                          fg_color=C["accent"], hover_color=C["acc_h"],
                          height=36, width=110, font=("Arial", 12, "bold"),
                          command=play_all).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btn_row, text="⇄  Shuffle",
                          fg_color=C["hover"], hover_color=C["bg"],
                          height=36, width=110, font=("Arial", 12),
                          command=play_shuffle).pack(side="left")

        if not metas:
            ctk.CTkLabel(self.content,
                         text="This playlist is empty.",
                         font=("Arial", 13),
                         text_color=C["fg2"]).pack(pady=20)
            return

        def _on_play_from_playlist(m):
            self.autoplay_list = list(metas)
            self.autoplay_idx  = metas.index(m) if m in metas else 0
            self._shuffle_order = []
            self._play_song(m)

        for sid in ids:
            m = dm.get_song(sid)
            if m:
                SongCard(self.content, m,
                         on_play=_on_play_from_playlist,
                         downloaded=True,
                         refresh_sidebar=self._refresh_pl_sidebar,
                         on_delete=lambda s=sid: self._delete_song(s),
                         ).pack(fill="x", pady=3)

    # ═══════════════════════════════════════════════════════════════════════════
    # DOWNLOAD
    # ═══════════════════════════════════════════════════════════════════════════
    def _download_song(self, song_data, progress_cb=None, done_cb=None):
        """Called by SongCard. Runs download in background thread."""
        def run():
            def _prog(pct, msg):
                if progress_cb:
                    self.after(0, lambda p=pct, m=msg: progress_cb(p, m))

            ok, res = dl.download(song_data, progress_cb=_prog)
            err  = "" if ok else str(res)
            meta = res if ok else None
            if done_cb:
                self.after(0, lambda: done_cb(ok, err, meta))
            if ok:
                self.after(0, self._refresh_pl_sidebar)
                self.after(0, lambda: self.toast(
                    f"✓ Downloaded: {song_data['title'][:40]}"))
            else:
                self.after(0, lambda: self.toast(f"✗ {err[:60]}"))

        threading.Thread(target=run, daemon=True).start()

    def _delete_song(self, sid):
        m = dm.get_song(sid)
        if not m:
            return
        # Stop if currently playing
        if (player.current_meta and
                (player.current_meta.get("video_id") == sid or
                 player.current_meta.get("id") == sid)):
            player.stop()
            self.play_btn.configure(text="▶")
            self.bar_title.configure(text="No song playing")
            self.bar_artist.configure(text="")
            self.current_song = None
        # Delete file
        fp = m.get("file")
        if fp:
            try:
                Path(fp).unlink(missing_ok=True)
            except Exception:
                pass
        # Remove thumbnail
        th = m.get("thumbnail")
        if th and not th.startswith("http"):
            try:
                Path(th).unlink(missing_ok=True)
            except Exception:
                pass
        # Remove from data
        dm.data["songs"].pop(sid, None)
        for pl in dm.data["playlists"].values():
            if sid in pl.get("songs", []):
                pl["songs"].remove(sid)
        dm.save()
        self.toast(f"🗑 Deleted: {m.get('title','')[:40]}")
        self._refresh_pl_sidebar()
        # Refresh current view
        self._show_library()

    # ═══════════════════════════════════════════════════════════════════════════
    # PLAYBACK
    # ═══════════════════════════════════════════════════════════════════════════
    def _play_song(self, meta):
        ok = player.play(meta)
        if not ok:
            self.toast("⚠ Could not play.  Run:  pip install pygame")
            return
        self.current_song = meta
        sid = meta.get("video_id") or meta.get("id")
        if sid:
            dm.update_play_time(sid)
        # sync autoplay_idx to current song
        for i, m in enumerate(self.autoplay_list):
            msid = m.get("video_id") or m.get("id")
            if msid == sid:
                self.autoplay_idx = i
                break
        self.bar_title.configure(text=meta.get("title", "")[:50])
        self.bar_artist.configure(text=meta.get("artist", ""))
        self.play_btn.configure(text="⏸")
        # Pre-fetch lyrics in background for now-playing view
        self._lyrics_cache    = None
        self._lyrics_loading  = True
        self._np_lyrics_ready = False
        threading.Thread(target=self._fetch_lyrics_bg, daemon=True).start()
        # Update now-playing if open
        if hasattr(self, "_np_win") and self._np_win and self._np_win.winfo_exists():
            self._np_win.after(0, self._np_update_song)

    def _fetch_lyrics_bg(self):
        meta = self.current_song
        if not meta:
            return
        raw_title  = meta.get("title", "")
        raw_artist = meta.get("artist", "")
        clean_artist = re.sub(r'(?i)\s*vevo$|\s*-\s*topic$', '', raw_artist).strip()
        clean_title  = re.sub(
            r'\s*[\(\[](official\s*(video|audio|music\s*video|mv)?'
            r'|lyrics?|hd|hq|explicit)[^\)\]]*[\)\]]',
            '', raw_title, flags=re.IGNORECASE).strip()
        if clean_artist and ' - ' in clean_title:
            parts = clean_title.split(' - ', 1)
            if parts[0].strip().lower() in clean_artist.lower():
                clean_title = parts[1].strip()
        data = lrclib_fetch(clean_title or raw_title, clean_artist or raw_artist)
        self._lyrics_cache   = data
        self._lyrics_loading = False
        if hasattr(self, "_np_win") and self._np_win and self._np_win.winfo_exists():
            self._np_win.after(0, self._np_refresh_lyrics)

    def _open_now_playing(self):
        if not self.current_song:
            return
        if hasattr(self, "_np_win") and self._np_win and self._np_win.winfo_exists():
            self._np_win.lift()
            return

        win = tk.Toplevel(self)
        self._np_win = win
        win.title("Now Playing")
        win.geometry("700x640")
        win.configure(bg=C["bg"])
        win.resizable(True, True)

        # ── Header: thumbnail + song info ──────────────────────────────────────
        hdr = tk.Frame(win, bg=C["bg"])
        hdr.pack(fill="x", padx=30, pady=(28, 0))

        self._np_thumb_lbl = tk.Label(hdr, bg=C["hover"], width=10, height=5,
                                      text="♪", font=("Arial", 36), fg=C["accent"])
        self._np_thumb_lbl.pack(side="left")

        txt = tk.Frame(hdr, bg=C["bg"])
        txt.pack(side="left", padx=20, fill="x", expand=True)
        self._np_title_lbl  = tk.Label(txt, text="", font=("Arial", 20, "bold"),
                                        bg=C["bg"], fg=C["fg"], anchor="w", justify="left",
                                        wraplength=380)
        self._np_title_lbl.pack(anchor="w")
        self._np_artist_lbl = tk.Label(txt, text="", font=("Arial", 13),
                                        bg=C["bg"], fg=C["fg2"], anchor="w")
        self._np_artist_lbl.pack(anchor="w", pady=(4, 0))

        # ── Tab bar: Info / Lyrics ─────────────────────────────────────────────
        tab_bar = tk.Frame(win, bg=C["bg"])
        tab_bar.pack(fill="x", padx=30, pady=(20, 0))

        self._np_tab = tk.StringVar(value="lyrics")

        def _switch(tab):
            self._np_tab.set(tab)
            info_btn.configure(
                relief="flat",
                fg=C["accent"] if tab == "info" else C["fg2"],
                font=("Arial", 12, "bold") if tab == "info" else ("Arial", 12))
            lyr_btn.configure(
                relief="flat",
                fg=C["accent"] if tab == "lyrics" else C["fg2"],
                font=("Arial", 12, "bold") if tab == "lyrics" else ("Arial", 12))
            info_frame.pack_forget()
            lyr_frame.pack_forget()
            if tab == "info":
                info_frame.pack(fill="both", expand=True, padx=30, pady=10)
            else:
                lyr_frame.pack(fill="both", expand=True, padx=0, pady=0)

        info_btn = tk.Button(tab_bar, text="Info", font=("Arial", 12),
                             bg=C["bg"], fg=C["fg2"], relief="flat", bd=0,
                             activebackground=C["bg"], activeforeground=C["accent"],
                             command=lambda: _switch("info"))
        info_btn.pack(side="left", padx=(0, 20))

        lyr_btn = tk.Button(tab_bar, text="Lyrics", font=("Arial", 12, "bold"),
                            bg=C["bg"], fg=C["accent"], relief="flat", bd=0,
                            activebackground=C["bg"], activeforeground=C["accent"],
                            command=lambda: _switch("lyrics"))
        lyr_btn.pack(side="left")

        tk.Frame(win, bg=C["hover"], height=1).pack(fill="x", padx=30, pady=(8, 0))

        # ── Info tab ───────────────────────────────────────────────────────────
        info_frame = tk.Frame(win, bg=C["bg"])

        # ── Lyrics tab ────────────────────────────────────────────────────────
        lyr_frame = tk.Frame(win, bg=C["bg"])
        lyr_frame.pack(fill="both", expand=True, padx=0, pady=0)

        self._np_canvas    = tk.Canvas(lyr_frame, bg=C["bg"], highlightthickness=0)
        self._np_scrollbar = tk.Scrollbar(lyr_frame, orient="vertical",
                                          command=self._np_canvas.yview)
        self._np_canvas.configure(yscrollcommand=self._np_scrollbar.set)
        self._np_scrollbar.pack(side="right", fill="y")
        self._np_canvas.pack(side="left", fill="both", expand=True)

        self._np_lyr_inner = tk.Frame(self._np_canvas, bg=C["bg"])
        self._np_canvas_window = self._np_canvas.create_window(
            (0, 0), window=self._np_lyr_inner, anchor="nw")

        def _on_configure(e):
            self._np_canvas.configure(scrollregion=self._np_canvas.bbox("all"))
        def _on_canvas_resize(e):
            self._np_canvas.itemconfig(self._np_canvas_window, width=e.width)
        self._np_lyr_inner.bind("<Configure>", _on_configure)
        self._np_canvas.bind("<Configure>", _on_canvas_resize)

        self._np_line_labels = []   # list of tk.Label, one per lyric line
        self._np_synced      = []   # [(secs, text), ...]
        self._np_cur_line    = -1

        self._np_update_song()
        self._np_tick()
        win.bind("<Destroy>", lambda e: setattr(self, "_np_win", None))

    def _np_update_song(self):
        """Refresh header with current song metadata + trigger lyrics reload."""
        meta = self.current_song
        if not meta or not hasattr(self, "_np_title_lbl"):
            return
        self._np_title_lbl.configure(text=meta.get("title", "")[:80])
        self._np_artist_lbl.configure(text=meta.get("artist", ""))
        self._np_line_labels  = []
        self._np_synced       = []
        self._np_cur_line     = -1
        self._np_lyrics_ready = False
        for w in self._np_lyr_inner.winfo_children():
            w.destroy()
        tk.Label(self._np_lyr_inner, text="Loading lyrics…",
                 font=("Arial", 13), bg=C["bg"], fg=C["dim"]
                 ).pack(pady=40)

        # If lyrics already fetched (song was playing before window opened), show now
        if not self._lyrics_loading and self._lyrics_cache is not None:
            self._np_refresh_lyrics()

        # load thumbnail
        th = meta.get("thumbnail")
        if th and PIL_AVAILABLE:
            threading.Thread(target=self._np_load_thumb, args=(th,), daemon=True).start()

    def _np_load_thumb(self, url):
        try:
            from io import BytesIO
            from PIL import ImageTk
            if url.startswith("http") and REQUESTS_AVAILABLE:
                r   = requests.get(url, timeout=5)
                img = Image.open(BytesIO(r.content)).resize((110, 110))
            else:
                img = Image.open(url).resize((110, 110))
            photo = ImageTk.PhotoImage(img)
            def _apply():
                if hasattr(self, "_np_thumb_lbl") and self._np_thumb_lbl.winfo_exists():
                    self._np_thumb_lbl.configure(image=photo, text="",
                                                  width=110, height=110)
                    self._np_thumb_lbl.image = photo  # keep reference
            self.after(0, _apply)
        except Exception:
            pass

    def _np_refresh_lyrics(self):
        """Called after lyrics finish loading in background."""
        if not hasattr(self, "_np_lyr_inner") or not self._np_lyr_inner.winfo_exists():
            return
        self._np_lyrics_ready = True
        for w in self._np_lyr_inner.winfo_children():
            w.destroy()
        self._np_line_labels = []
        self._np_synced      = []
        self._np_cur_line    = -1

        data   = self._lyrics_cache or {}
        synced = data.get("synced", [])
        plain  = data.get("plain")

        if synced:
            self._np_synced = synced
            tk.Label(self._np_lyr_inner, text="", bg=C["bg"], height=2).pack()
            for _secs, line in synced:
                lbl = tk.Label(
                    self._np_lyr_inner,
                    text=line or " ",
                    font=("Arial", 15),
                    bg=C["bg"], fg=C["dim"],
                    wraplength=580, justify="center", pady=6)
                lbl.pack(fill="x", padx=40)
                self._np_line_labels.append(lbl)
            tk.Label(self._np_lyr_inner, text="", bg=C["bg"], height=4).pack()
        elif plain:
            tk.Label(self._np_lyr_inner, text="", bg=C["bg"], height=2).pack()
            for line in plain.splitlines():
                tk.Label(
                    self._np_lyr_inner,
                    text=line or " ",
                    font=("Arial", 15),
                    bg=C["bg"], fg=C["fg2"],
                    wraplength=580, justify="center", pady=5
                ).pack(fill="x", padx=40)
            tk.Label(self._np_lyr_inner, text="", bg=C["bg"], height=4).pack()
        else:
            tk.Label(self._np_lyr_inner,
                     text="Lyrics not found in lrclib database.",
                     font=("Arial", 13), bg=C["bg"], fg=C["dim"]
                     ).pack(pady=60)

    def _np_tick(self):
        """250ms tick: sync lyric highlight to playback position."""
        try:
            if not self._np_win or not self._np_win.winfo_exists():
                return
        except Exception:
            return

        # If lyrics just finished loading, render them
        if not self._lyrics_loading and self._lyrics_cache is not None:
            if not getattr(self, "_np_lyrics_ready", False):
                self._np_refresh_lyrics()

        # Sync highlighted line
        if self._np_synced and player.is_playing and self.current_song:
            pos = player.position
            cur = -1
            for i, (secs, _) in enumerate(self._np_synced):
                if secs <= pos:
                    cur = i
            if cur != self._np_cur_line:
                if 0 <= self._np_cur_line < len(self._np_line_labels):
                    self._np_line_labels[self._np_cur_line].configure(
                        fg=C["dim"], font=("Arial", 15))
                if 0 <= cur < len(self._np_line_labels):
                    self._np_line_labels[cur].configure(
                        fg=C["fg"], font=("Arial", 18, "bold"))
                    # Auto-scroll to keep active line vertically centred
                    lbl = self._np_line_labels[cur]
                    self._np_lyr_inner.update_idletasks()
                    y     = lbl.winfo_y()
                    h     = self._np_canvas.winfo_height()
                    total = self._np_lyr_inner.winfo_height()
                    if total > 0:
                        frac = max(0.0, min(1.0, (y - h // 2) / total))
                        self._np_canvas.yview_moveto(frac)
                self._np_cur_line = cur

        self._np_win.after(250, self._np_tick)

    def _toggle_pause(self):
        if not player.is_playing:
            return
        player.toggle_pause()
        self.play_btn.configure(text="▶" if player.is_paused else "⏸")

    def _next_song(self):
        # Repeat single
        if self.repeat_mode and self.current_song:
            self._play_song(self.current_song)
            return
        # Explicit queue first
        if self.queue:
            self._play_song(self.queue.pop(0))
            return
        # Autoplay list (set when playing from a playlist / library)
        if self.autoplay_list:
            n = len(self.autoplay_list)
            if self.shuffle_mode:
                import random
                # advance through shuffle order
                if not self._shuffle_order:
                    self._shuffle_order = list(range(n))
                    random.shuffle(self._shuffle_order)
                if self._shuffle_order:
                    idx = self._shuffle_order.pop(0)
                    self._play_song(self.autoplay_list[idx])
                    return
            else:
                self.autoplay_idx = (self.autoplay_idx + 1) % n
                self._play_song(self.autoplay_list[self.autoplay_idx])
                return

    def _prev_song(self):
        if self.autoplay_list and self.autoplay_idx > 0:
            self.autoplay_idx -= 1
            self._play_song(self.autoplay_list[self.autoplay_idx])
            return
        hist = dm.data.get("play_history", [])
        if len(hist) > 1:
            m = dm.get_song(hist[1]["id"])
            if m:
                self._play_song(m)

    def _on_song_finish(self):
        self.play_btn.configure(text="▶")
        self._next_song()

    def _toggle_shuffle(self):
        self.shuffle_mode = not self.shuffle_mode
        self._shuffle_order = []  # reset on toggle
        clr = C["accent"] if self.shuffle_mode else C["dim"]
        self.shuffle_btn.configure(text_color=clr)
        self.toast("Shuffle ON 🔀" if self.shuffle_mode else "Shuffle OFF")

    def _toggle_repeat(self):
        self.repeat_mode = not self.repeat_mode
        clr = C["accent"] if self.repeat_mode else C["dim"]
        self.repeat_btn.configure(text_color=clr)
        self.toast("Repeat ON ↺" if self.repeat_mode else "Repeat OFF")

    def _tick_player(self):
        if player.is_playing and self.current_song and not self._seek_dragging:
            dur = self.current_song.get("duration_sec", 0) or 0
            pos = player.position
            val = min(pos / dur, 1.0) if dur > 0 else 0.0
            self._seek_val = val
            self._draw_seek(val)
            pm, ps  = divmod(pos, 60)
            dm2, ds = divmod(int(dur), 60)
            self.time_lbl.configure(text=f"{pm}:{ps:02d} / {dm2}:{ds:02d}")
        self.after(1000, self._tick_player)

    # ═══════════════════════════════════════════════════════════════════════════
    # COMPRESSION
    # ═══════════════════════════════════════════════════════════════════════════
    def _auto_compress_check(self):
        ids = dm.songs_needing_compression()
        if ids:
            self.toast(f"💾 Auto-compressing {len(ids)} unused song(s)…")
            for sid in ids[:5]:
                threading.Thread(target=dl.compress,
                                 args=(sid,), daemon=True).start()
        self.after(3_600_000, self._auto_compress_check)

    def _manual_compress(self):
        ids = dm.songs_needing_compression()
        days = dm.data["settings"].get("compress_days", COMPRESS_DAYS)
        if not ids:
            messagebox.showinfo(
                "Compression",
                f"No songs unplayed for {days}+ days.")
            return
        if messagebox.askyesno(
                "Compress",
                f"Compress {len(ids)} rarely-played song(s)?"):
            def run():
                for sid in ids:
                    dl.compress(sid)
                self.after(0, lambda: messagebox.showinfo(
                    "Done", f"Compressed {len(ids)} song(s)!"))
            threading.Thread(target=run, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════════════════
    # SETTINGS
    # ═══════════════════════════════════════════════════════════════════════════
    def _show_settings(self):
        w = ctk.CTkToplevel(self)
        w.title("Settings")
        w.geometry("500x560")
        w.configure(fg_color=C["bg2"])
        w.resizable(False, False)
        w.grab_set()

        ctk.CTkLabel(w, text="⚙  Settings",
                     font=("Arial", 20, "bold"),
                     text_color=C["fg"]).pack(pady=(18, 10))

        tab = ctk.CTkTabview(w, fg_color=C["card"],
                             segmented_button_fg_color=C["hover"],
                             segmented_button_selected_color=C["accent"],
                             segmented_button_selected_hover_color=C["acc_h"],
                             segmented_button_unselected_color=C["hover"],
                             segmented_button_unselected_hover_color=C["bg"])
        tab.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        tab.add("General")
        tab.add("Appearance")

        # ── GENERAL tab ──────────────────────────────────────────────────────
        gf = tab.tab("General")

        ctk.CTkLabel(gf, text="Download folder:",
                     font=("Arial", 12), text_color=C["fg2"]
                     ).pack(anchor="w", padx=8, pady=(14, 4))
        prow = ctk.CTkFrame(gf, fg_color="transparent")
        prow.pack(fill="x", padx=8, pady=(0, 10))
        pv = tk.StringVar(value=dm.data["settings"].get("download_dir", str(MUSIC_DIR)))
        ctk.CTkEntry(prow, textvariable=pv, fg_color=C["hover"]
                     ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(prow, text="Browse", width=70, fg_color=C["accent"],
                      command=lambda: pv.set(filedialog.askdirectory() or pv.get())
                      ).pack(side="left", padx=5)

        ctk.CTkLabel(gf, text="Compress songs unplayed for (days):",
                     font=("Arial", 12), text_color=C["fg2"]
                     ).pack(anchor="w", padx=8, pady=(6, 4))
        dv = tk.StringVar(value=str(dm.data["settings"].get("compress_days", COMPRESS_DAYS)))
        ctk.CTkEntry(gf, textvariable=dv, width=80
                     ).pack(anchor="w", padx=8, pady=(0, 14))

        # ── APPEARANCE tab ────────────────────────────────────────────────────
        af = tab.tab("Appearance")

        ctk.CTkLabel(af, text="Accent colour",
                     font=("Arial", 13, "bold"), text_color=C["fg"]
                     ).pack(anchor="w", padx=8, pady=(14, 6))
        ctk.CTkLabel(af,
                     text="This colour is used for buttons, highlights, the progress bar\nand the logo throughout the app.",
                     font=("Arial", 11), text_color=C["fg2"], justify="left"
                     ).pack(anchor="w", padx=8, pady=(0, 10))

        # preset swatches
        presets = [
            ("#1DB954", "Spotify Green"),
            ("#1E90FF", "Electric Blue"),
            ("#E91E63", "Neon Pink"),
            ("#FF6B35", "Tangerine"),
            ("#9B59B6", "Purple"),
            ("#F39C12", "Amber"),
            ("#00BCD4", "Cyan"),
            ("#E74C3C", "Red"),
            ("#2ECC71", "Emerald"),
            ("#FF1744", "Cherry"),
        ]

        swatch_frame = ctk.CTkFrame(af, fg_color="transparent")
        swatch_frame.pack(fill="x", padx=8, pady=(0, 12))

        current_accent = tk.StringVar(value=dm.data["settings"].get("accent_color", C["accent"]))

        # preview patch
        preview_row = ctk.CTkFrame(af, fg_color="transparent")
        preview_row.pack(fill="x", padx=8, pady=(0, 10))
        ctk.CTkLabel(preview_row, text="Preview:", font=("Arial", 11),
                     text_color=C["fg2"]).pack(side="left")
        self._acc_preview = ctk.CTkButton(
            preview_row, text="♫  Melodify", width=130, height=32,
            font=("Arial", 13, "bold"), fg_color=current_accent.get(),
            hover_color=current_accent.get(), corner_radius=8,
            text_color=C["fg"], state="disabled")
        self._acc_preview.pack(side="left", padx=10)

        def _pick_preset(hex_c):
            current_accent.set(hex_c)
            self._acc_preview.configure(fg_color=hex_c, hover_color=hex_c)
            hex_entry.delete(0, "end")
            hex_entry.insert(0, hex_c)

        for i, (hex_c, name) in enumerate(presets):
            sw = tk.Canvas(swatch_frame, width=28, height=28,
                           bg=hex_c, highlightthickness=2,
                           highlightbackground=C["hover"],
                           cursor="hand2")
            sw.grid(row=i // 5, column=i % 5, padx=4, pady=4)
            sw.bind("<Button-1>", lambda e, h=hex_c: _pick_preset(h))
            Tooltip(sw, name)

        # custom hex input
        hex_row = ctk.CTkFrame(af, fg_color="transparent")
        hex_row.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkLabel(hex_row, text="Custom hex:", font=("Arial", 11),
                     text_color=C["fg2"]).pack(side="left")
        hex_entry = ctk.CTkEntry(hex_row, width=100, fg_color=C["hover"],
                                 placeholder_text="#1DB954")
        hex_entry.insert(0, current_accent.get())
        hex_entry.pack(side="left", padx=8)

        def _apply_hex(*_):
            val = hex_entry.get().strip()
            if re.match(r"^#[0-9a-fA-F]{6}$", val):
                _pick_preset(val)

        hex_entry.bind("<Return>", _apply_hex)
        ctk.CTkButton(hex_row, text="Apply", width=60,
                      fg_color=C["hover"], hover_color=C["bg"],
                      command=_apply_hex).pack(side="left")

        # ── save ─────────────────────────────────────────────────────────────
        def save():
            # general
            dm.data["settings"]["download_dir"] = pv.get()
            try:
                dm.data["settings"]["compress_days"] = int(dv.get())
            except Exception:
                pass
            # accent
            new_accent = current_accent.get()
            dm.data["settings"]["accent_color"] = new_accent
            dm.save()

            # apply globally
            apply_accent(new_accent)
            self._rebuild_after_theme()
            messagebox.showinfo("Saved",
                                "Settings saved!\nAccent colour applied.",
                                parent=w)
            w.destroy()

        ctk.CTkButton(w, text="💾  Save Settings",
                      fg_color=C["accent"], hover_color=C["acc_h"],
                      font=("Arial", 13, "bold"), height=40,
                      command=save).pack(pady=14)

    # ═══════════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════════════
    def toast(self, msg):
        if not hasattr(self, "_toast_lbl") or \
                not self._toast_lbl.winfo_exists():
            self._toast_lbl = ctk.CTkLabel(
                self, text=msg, font=("Arial", 12),
                fg_color=C["card"], corner_radius=8,
                text_color=C["fg"], padx=14, pady=8)
            self._toast_lbl.place(relx=0.5, rely=0.93, anchor="center")
        else:
            self._toast_lbl.configure(text=msg)
        if hasattr(self, "_toast_job"):
            try:
                self.after_cancel(self._toast_job)
            except Exception:
                pass
        self._toast_job = self.after(4500, self._hide_toast)

    def _hide_toast(self):
        if hasattr(self, "_toast_lbl") and self._toast_lbl.winfo_exists():
            self._toast_lbl.place_forget()

    def _create_playlist_dlg(self):
        d = ctk.CTkInputDialog(text="Playlist name:", title="New Playlist")
        name = d.get_input()
        if name and name.strip():
            dm.create_playlist(name.strip())
            self._refresh_pl_sidebar()

    def _rebuild_after_theme(self):
        """Re-colour all accent-tinted widgets after a theme change."""
        try:
            # Logo label
            self.logo_lbl.configure(text_color=C["accent"])
            # Player bar play button
            self.play_btn.configure(fg_color=C["accent"], hover_color=C["acc_h"])
            # Shuffle/repeat indicators
            if self.shuffle_mode:
                self.shuffle_btn.configure(text_color=C["accent"])
            if self.repeat_mode:
                self.repeat_btn.configure(text_color=C["accent"])
            # Seek bar thumb + fill
            self._draw_seek(self._seek_val)
            # Refresh content area so newly rendered cards/buttons pick up C["accent"]
            self._show_home()
        except Exception as e:
            print(f"Theme rebuild error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    missing = []
    if not YTDLP_AVAILABLE:    missing.append("yt-dlp")
    if not PIL_AVAILABLE:      missing.append("Pillow")
    if not REQUESTS_AVAILABLE: missing.append("requests")
    if not PYGAME_AVAILABLE:   missing.append("pygame")
    if missing:
        print(f"⚠  Missing packages: {', '.join(missing)}")
        print(f"   Run: pip install {' '.join(missing)}\n")
    if not YTDLP_AVAILABLE and not PYTUBE_AVAILABLE:
        print("⛔ Neither yt-dlp nor pytubefix is installed.")
        print("   Run: pip install yt-dlp\n")

    app = MelodifyApp()
    app.mainloop()
