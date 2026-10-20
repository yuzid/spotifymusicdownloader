# 🎵 SpotDown — Spotify Downloader

A beautiful web app to download Spotify songs, albums, and playlists as high-quality MP3 files — with cover art and metadata embedded automatically.

## Features

- 🎵 **Songs** — Download any individual track
- 💿 **Albums** — Download entire albums
- 📋 **Playlists** — Download full playlists or pick individual songs
- 📦 **Direct or ZIP Archive** — Choose between direct individual files or a packaged `.zip` archive with instant 1-click browser download
- 🎨 **Cover Art & Metadata** — Automatically embedded (title, artist, album, duration)
- ⚡ **MP3 320kbps** — High quality audio (FLAC, M4A, Opus also supported)
- 📁 **Custom Output Folder** — Choose where files are saved
- 🔄 **Real-time Progress** — Live download progress tracking with instant process cancellation
- 📜 **Download History** — See all past downloads

## Quick Start

```bash
# 1. Run setup (first time only)
./setup.sh

# 2. Start the app
./run.sh

# 3. Open http://localhost:5000 in your browser
```

## Requirements

- Python 3.9+
- ffmpeg (`sudo pacman -S ffmpeg` on Arch)
- Internet connection

## How it Works

1. Paste a Spotify URL (song, album, or playlist)
2. Click **Fetch** to load track info
3. Click **Download All** or select specific tracks to download
4. Files are saved to `~/Music/Spotify Downloads` (configurable in Settings)

## Tech Stack

- **Backend**: Python + Flask + spotdl
- **Frontend**: Vanilla HTML/CSS/JS (no frameworks)
- **Audio**: yt-dlp + ffmpeg (via spotdl)
