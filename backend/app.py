#!/usr/bin/env python3
"""
Spotify Downloader - Flask Backend
Credentials (Client ID + Secret) are loaded in priority order:
  1. .env file  (SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET)
  2. config.json (saved via the web UI)
All spotdl/spotipy calls pass them via CLI flags.
"""

import os
import re
import json
import uuid
import urllib.request
import urllib.parse
import threading
import subprocess
import zipfile
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

# Load .env from project root (if it exists)
load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

BASE_DIR    = Path(__file__).parent.parent
CONFIG_FILE = BASE_DIR / "config.json"
DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Music" / "Spotify Downloads")

jobs: dict = {}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def save_config(data: dict):
    cfg = load_config()
    cfg.update(data)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def get_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret).

    Priority:
      1. Environment variables / .env file
      2. config.json (saved via the web UI)
    Note: Credentials are completely OPTIONAL. SpotDL runs seamlessly without them.
    """
    env_id  = os.environ.get("SPOTIFY_CLIENT_ID",     "").strip()
    env_sec = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if env_id and env_sec:
        return env_id, env_sec

    cfg = load_config()
    return cfg.get("client_id", ""), cfg.get("client_secret", "")


def get_spotdl_path() -> str:
    candidates = [
        BASE_DIR / "venv" / "bin" / "spotdl",
        Path("/usr/local/bin/spotdl"),
        Path("/usr/bin/spotdl"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return "spotdl"


def spotdl_base_cmd() -> list[str]:
    """Return base spotdl command with credentials injected if available."""
    cmd = [get_spotdl_path()]
    cid, csec = get_credentials()
    if cid and csec:
        cmd += ["--client-id", cid, "--client-secret", csec]
    return cmd


@app.route("/")
def index():
    return send_from_directory("../frontend", "index.html")


# ── Credentials ──────────────────────────────────────────────────────────────

@app.route("/api/credentials", methods=["GET"])
def get_creds():
    cid, csec = get_credentials()
    return jsonify({
        "client_id":     cid,
        "client_secret": "•" * len(csec) if csec else "",  # masked
        "has_credentials": bool(cid and csec),
    })


@app.route("/api/credentials", methods=["POST"])
def set_creds():
    data = request.get_json(force=True)
    cid  = (data.get("client_id")     or "").strip()
    csec = (data.get("client_secret") or "").strip()

    if not cid or not csec:
        return jsonify({"error": "Both Client ID and Client Secret are required."}), 400

    # Quick validation: test the credentials with spotdl
    ok, msg = test_credentials(cid, csec)
    if not ok:
        return jsonify({"error": msg}), 400

    save_config({"client_id": cid, "client_secret": csec})
    return jsonify({"ok": True, "message": "Credentials saved and verified ✓"})


@app.route("/api/credentials", methods=["DELETE"])
def delete_creds():
    save_config({"client_id": "", "client_secret": ""})
    return jsonify({"ok": True})


# ── Track fetching ────────────────────────────────────────────────────────────

@app.route("/api/fetch-info", methods=["POST"])
def fetch_info():
    data = request.get_json(force=True)
    url  = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    url_type = detect_url_type(url)
    if not url_type:
        return jsonify({"error": "Invalid Spotify URL. Paste a song, album, or playlist link."}), 400

    try:
        info = fetch_spotify_info(url, url_type)
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return cleaned or "spotify_download"


# ── Download ──────────────────────────────────────────────────────────────────

@app.route("/api/download", methods=["POST"])
def start_download():
    data       = request.get_json(force=True)
    urls       = data.get("urls", [])
    output_dir = data.get("output_dir", DEFAULT_DOWNLOAD_DIR)
    track_name = data.get("track_name", "")
    fmt        = data.get("format", "mp3")
    as_zip     = bool(data.get("as_zip", False))

    if not urls:
        return jsonify({"error": "No URLs provided"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "id":               job_id,
        "status":           "queued",
        "progress":         0,
        "total":            len(urls),
        "done":             0,
        "error":            None,
        "tracks":           [],
        "output_dir":       output_dir,
        "track_name":       track_name,
        "as_zip":           as_zip,
        "zip_name":         None,
        "zip_path":         None,
        "zip_ready":        False,
        "zip_download_url": None,
        "cancelled":        False,
        "log":              [],
    }

    thread = threading.Thread(
        target=run_download,
        args=(job_id, urls, output_dir, fmt, as_zip, track_name),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>/download-zip", methods=["GET"])
def download_job_zip(job_id):
    job = jobs.get(job_id)
    if not job or not job.get("zip_path"):
        return jsonify({"error": "ZIP file not found or not ready"}), 404
    zip_path = Path(job["zip_path"])
    if not zip_path.exists():
        return jsonify({"error": "ZIP file does not exist on disk"}), 404
    return send_file(
        zip_path,
        as_attachment=True,
        download_name=job.get("zip_name", "download.zip"),
        mimetype="application/zip",
    )


@app.route("/api/job/<job_id>", methods=["GET"])
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    return jsonify(list(reversed(list(jobs.values()))))


active_processes: dict = {}


@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job["cancelled"] = True
    job["status"] = "cancelled"
    proc = active_processes.get(job_id)
    if proc:
        try:
            proc.kill()
        except Exception:
            pass
        active_processes.pop(job_id, None)
    return jsonify({"ok": True})


@app.route("/api/default-dir", methods=["GET"])
def default_dir():
    cfg = load_config()
    return jsonify({
        "dir": cfg.get("output_dir", DEFAULT_DOWNLOAD_DIR),
        "format": cfg.get("format", "mp3"),
    })


@app.route("/api/settings", methods=["POST"])
def save_settings():
    data = request.get_json(force=True)
    patch = {}
    if "output_dir" in data:
        patch["output_dir"] = data["output_dir"]
    if "format" in data:
        patch["format"] = data["format"]
    save_config(patch)
    return jsonify({"ok": True})


SPOTIFY_URL_PATTERNS = {
    "track":    r"open\.spotify\.com/track/([A-Za-z0-9]+)",
    "playlist": r"open\.spotify\.com/playlist/([A-Za-z0-9]+)",
    "album":    r"open\.spotify\.com/album/([A-Za-z0-9]+)",
}


def detect_url_type(url: str):
    for kind, pattern in SPOTIFY_URL_PATTERNS.items():
        if re.search(pattern, url):
            return kind
    return None


def test_credentials(client_id: str, client_secret: str) -> tuple[bool, str]:
    """Validate Spotify credentials by fetching a known track."""
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        ))
        # Fetch a known public track to confirm creds work
        sp.track("4cOdK2wGLETKBW3PvgPWqT")
        return True, "OK"
    except Exception as e:
        msg = str(e)
        if "401" in msg or "invalid" in msg.lower():
            return False, "Invalid Client ID or Client Secret. Double-check your Spotify Developer Dashboard."
        return False, f"Could not verify credentials: {msg}"


def fetch_spotify_oembed(url: str) -> dict | None:
    """Fetch Spotify metadata using official public oEmbed API.
    Fast (< 1s), does not require Spotify credentials or Premium account.
    """
    try:
        encoded = urllib.parse.quote(url, safe=":/")
        oembed_url = f"https://open.spotify.com/oembed?url={encoded}"
        req = urllib.request.Request(
            oembed_url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=6) as res:
            if res.status == 200:
                return json.loads(res.read().decode())
    except Exception:
        pass
    return None


def scrape_spotify_entity(url: str, url_type: str) -> dict | None:
    """Scrape playlist, album, or track info and full track list directly from Spotify embed data.
    Fast (< 1s), does not require Spotify credentials or Premium account.
    """
    match = re.search(r"open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)", url)
    if not match:
        return None
    kind, item_id = match.group(1), match.group(2)
    embed_url = f"https://open.spotify.com/embed/{kind}/{item_id}"

    req = urllib.request.Request(embed_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            html = res.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    matches = re.findall(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not matches:
        return None

    try:
        data = json.loads(matches[0])
    except Exception:
        return None

    entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
    if not entity:
        return None

    title = entity.get("title") or entity.get("name") or "Spotify Collection"
    sources = entity.get("coverArt", {}).get("sources", [])
    cover = sources[0]["url"] if sources else ""

    raw_tracks = entity.get("trackList", [])
    formatted_tracks = []
    for item in raw_tracks:
        uri = item.get("uri", "")
        track_id = uri.split(":")[-1] if uri else ""
        track_url = f"https://open.spotify.com/track/{track_id}" if track_id else url
        subtitle = (item.get("subtitle") or "").replace("\xa0", " ")

        # For playlists: subtitle may be "Artist · Album" or "Artist · Year"
        # For albums: artist name only. For tracks: artist name.
        artists = subtitle
        album_name = ""
        if kind == "album":
            album_name = title
        elif kind == "playlist" and " · " in subtitle:
            parts = subtitle.split(" · ", 1)
            artists = parts[0].strip()
            album_name = parts[1].strip() if len(parts) > 1 else ""

        formatted_tracks.append({
            "name": item.get("title", "Unknown"),
            "artists": artists,
            "album": album_name,
            "duration": int(item.get("duration", 0)),  # keep raw ms for frontend formatDuration()
            "cover": cover,
            "url": track_url,
            "explicit": item.get("isExplicit", False),
        })

    # For single tracks if trackList was empty
    if not formatted_tracks and kind == "track":
        # entity.artists is a list of {name, uri} objects for single tracks
        raw_artists = entity.get("artists") or []
        if isinstance(raw_artists, list):
            artists_str = ", ".join(a["name"] for a in raw_artists if a.get("name"))
        else:
            artists_str = (entity.get("subtitle") or "").replace("\xa0", " ")

        formatted_tracks.append({
            "name": title,
            "artists": artists_str,
            "album": "",
            "duration": int(entity.get("duration", 0)),  # keep raw ms for frontend formatDuration()
            "cover": cover,
            "url": url,
            "explicit": entity.get("isExplicit", False),
        })

    if not formatted_tracks:
        return None

    return {
        "type": kind,
        "title": title,
        "cover": cover,
        "track_count": len(formatted_tracks),
        "tracks": formatted_tracks,
        "source_url": url,
    }


def fetch_via_spotipy(url: str, url_type: str, cid: str, csec: str) -> dict | None:
    """Fetch all tracks using official Spotipy with pagination if credentials have API access."""
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
        sp = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(client_id=cid, client_secret=csec),
            requests_timeout=10,
        )
        match = re.search(r"open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)", url)
        if not match:
            return None
        kind, item_id = match.group(1), match.group(2)
        if kind == "playlist":
            pl = sp.playlist(item_id)
            title = pl.get("name", "Spotify Playlist")
            images = pl.get("images") or []
            cover = images[0].get("url", "") if images else ""

            tracks = []
            results = sp.playlist_items(item_id, limit=100)
            while results:
                for it in results.get("items", []):
                    tr = it.get("track")
                    if not tr:
                        continue
                    artists = ", ".join(a["name"] for a in tr.get("artists", []))
                    album_obj = tr.get("album") or {}
                    album_name = album_obj.get("name", "")
                    img_list = album_obj.get("images") or []
                    tr_cover = img_list[0].get("url", "") if img_list else cover
                    tr_url = tr.get("external_urls", {}).get("spotify") or f"https://open.spotify.com/track/{tr.get('id')}"
                    tracks.append({
                        "name": tr.get("name", "Unknown"),
                        "artists": artists,
                        "album": album_name,
                        "duration": tr.get("duration_ms", 0),
                        "cover": tr_cover,
                        "url": tr_url,
                        "explicit": tr.get("isExplicit", tr.get("explicit", False)),
                    })
                if results.get("next"):
                    results = sp.next(results)
                else:
                    break

            if tracks:
                return {
                    "type": "playlist",
                    "title": title,
                    "cover": cover,
                    "track_count": len(tracks),
                    "tracks": tracks,
                    "source_url": url,
                }
    except Exception:
        pass
    return None


def fetch_spotify_info(url: str, url_type: str) -> dict:
    # 0. If user has Spotify credentials configured, try official API first to get unlimited tracks
    cid, csec = get_credentials()
    if cid and csec and url_type == "playlist":
        sp_info = fetch_via_spotipy(url, url_type, cid, csec)
        if sp_info and sp_info.get("tracks"):
            return sp_info

    # 1. Primary: fast scrape directly from Spotify Embed data (< 1s, extracts individual songs)
    info = scrape_spotify_entity(url, url_type)

    # Always fetch oEmbed to get thumbnail for single tracks (embed data has no coverArt)
    oembed = fetch_spotify_oembed(url)
    real_cover = oembed.get("thumbnail_url", "") if oembed else ""
    real_title = oembed.get("title", "") if oembed else ""

    if info and info.get("tracks"):
        # Enrich missing cover art (single tracks have no coverArt in embed data)
        if not info.get("cover") and real_cover:
            info["cover"] = real_cover
            for t in info["tracks"]:
                if not t.get("cover"):
                    t["cover"] = real_cover
        if url_type == "playlist" and len(info["tracks"]) >= 50:
            info["has_more_notice"] = True
        return info

    # 2. Secondary: oEmbed for single tracks
    if url_type == "track" and real_title:
        return {
            "type": "track",
            "title": real_title,
            "cover": real_cover,
            "track_count": 1,
            "tracks": [{
                "name": real_title,
                "artists": "",
                "album": "",
                "duration": 0,
                "cover": real_cover,
                "url": url,
                "explicit": False,
            }],
            "source_url": url,
        }

    # 3. Fallback: use spotdl save
    spotdl = get_spotdl_path()
    save_file = f"/tmp/spotdl_info_{uuid.uuid4().hex}.spotdl"

    cmd = [spotdl, "save", url, "--save-file", save_file]
    if cid and csec:
        cmd += ["--client-id", cid, "--client-secret", csec]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=90,
        )

        if os.path.exists(save_file):
            with open(save_file) as f:
                raw = json.load(f)
            os.remove(save_file)
            tracks = raw if isinstance(raw, list) else []
            if tracks:
                return format_track_info(tracks, url, url_type, real_title, real_cover)

    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    finally:
        if os.path.exists(save_file):
            try:
                os.remove(save_file)
            except Exception:
                pass

    if real_title:
        label = "Playlist" if url_type == "playlist" else "Album"
        return {
            "type": url_type,
            "title": real_title,
            "cover": real_cover,
            "track_count": 1,
            "tracks": [{
                "name": f"All Tracks in {label}: {real_title}",
                "artists": "Full " + label,
                "album": real_title,
                "duration": 0,
                "cover": real_cover,
                "url": url,
                "explicit": False,
            }],
            "source_url": url,
        }

    raise RuntimeError("Could not fetch info from Spotify. Please check the URL and make sure it is public.")


def format_track_info(tracks: list, url: str, url_type: str, real_title: str = "", real_cover: str = "") -> dict:
    formatted = []
    for t in tracks:
        formatted.append({
            "name":     t.get("name", "Unknown"),
            "artists":  ", ".join(t.get("artists", [])) if isinstance(t.get("artists"), list) else t.get("artist", ""),
            "album":    t.get("album_name", ""),
            "duration": t.get("duration", 0),
            "cover":    t.get("cover_url", "") or real_cover,
            "url":      t.get("url", url),
            "explicit": t.get("explicit", False),
        })

    # Pick the correct header title
    if url_type == "playlist":
        title = real_title or "Spotify Playlist"
        cover = real_cover or (formatted[0]["cover"] if formatted else "")
    elif url_type == "album":
        title = real_title or (tracks[0].get("album_name") if tracks else "Spotify Album")
        cover = real_cover or (formatted[0]["cover"] if formatted else "")
    elif url_type == "track" and formatted:
        title = real_title or f"{formatted[0]['name']} — {formatted[0]['artists']}"
        cover = real_cover or formatted[0]["cover"]
    elif formatted:
        title = real_title or tracks[0].get("album_name", "Spotify Collection")
        cover = real_cover or formatted[0]["cover"]
    else:
        title = real_title or "Spotify Music"
        cover = real_cover

    return {
        "type":        url_type,
        "title":       title,
        "cover":       cover,
        "track_count": len(formatted),
        "tracks":      formatted,
        "source_url":  url,
    }


def run_download(job_id: str, urls: list, output_dir: str, fmt: str = "mp3", as_zip: bool = False, track_name: str = ""):
    job = jobs[job_id]
    job["status"] = "running"
    cid, csec = get_credentials()
    os.makedirs(output_dir, exist_ok=True)

    base_name = safe_filename(track_name or "spotify_tracks")
    if as_zip:
        download_target = Path(output_dir) / f"{base_name}_{job_id[:6]}"
        download_target.mkdir(parents=True, exist_ok=True)
    else:
        download_target = Path(output_dir)

    for i, url in enumerate(urls):
        if job.get("cancelled"):
            job["status"] = "cancelled"
            return

        job["current_url"] = url

        cmd = [
            get_spotdl_path(), "download", url,
            "--output",  str(download_target),
            "--format",  fmt,
            "--bitrate", "320k",
            "--threads", "4",
        ]
        if cid and csec:
            cmd += ["--client-id", cid, "--client-secret", csec]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            active_processes[job_id] = proc
            stdout, stderr = proc.communicate(timeout=600)
            active_processes.pop(job_id, None)

            if job.get("cancelled"):
                job["status"] = "cancelled"
                return

            ok = proc.returncode == 0
            stderr_clean = (stderr or "").strip()
            track_result = {
                "url":    url,
                "status": "done" if ok else "error",
                "error":  stderr_clean[-400:] if not ok else None,
            }
            if not ok:
                job["log"].append(stderr_clean[-400:])
        except subprocess.TimeoutExpired:
            p = active_processes.pop(job_id, None)
            if p:
                try:
                    p.kill()
                except Exception:
                    pass
            track_result = {"url": url, "status": "error", "error": "Download timed out"}
        except Exception as e:
            active_processes.pop(job_id, None)
            track_result = {"url": url, "status": "error", "error": str(e)}

        job["tracks"].append(track_result)
        job["done"]     = i + 1
        job["progress"] = round((i + 1) / len(urls) * 100)

    # If as_zip, compress all audio files into a .zip archive
    if as_zip and not job.get("cancelled"):
        job["status"] = "zipping"
        try:
            zip_filename = f"{base_name}.zip"
            zip_path = Path(output_dir) / zip_filename
            if zip_path.exists():
                zip_filename = f"{base_name}_{job_id[:6]}.zip"
                zip_path = Path(output_dir) / zip_filename

            audio_files = []
            for ext in [fmt, "mp3", "m4a", "flac", "opus", "ogg", "wav"]:
                audio_files.extend(list(download_target.glob(f"*.{ext}")))
            seen = set()
            unique_files = [f for f in audio_files if not (f.name in seen or seen.add(f.name))]

            if unique_files:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in unique_files:
                        zf.write(f, arcname=f.name)
                job["zip_name"] = zip_filename
                job["zip_path"] = str(zip_path)
                job["zip_ready"] = True
                job["zip_download_url"] = f"/api/job/{job_id}/download-zip"
            else:
                job["zip_error"] = "No audio files found to package."
        except Exception as ze:
            job["zip_error"] = str(ze)

    errors = [t for t in job["tracks"] if t["status"] == "error"]
    job["status"] = "done_with_errors" if errors else "done"


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    print(f"🎵  SpotDown backend running")
    print(f"   URL: http://{host}:{port} (http://localhost:{port})")
    app.run(debug=False, host=host, port=port)
