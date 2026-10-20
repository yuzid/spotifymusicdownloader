#!/usr/bin/env bash
# ─────────────────────────────────────────────────────
# SpotDown — First-Time Setup Script
# ─────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "  🎵  SpotDown Setup"
echo "  ━━━━━━━━━━━━━━━━━━"

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "❌  Python3 is required but not found."
  exit 1
fi

# Create virtual environment
if [ ! -d "$SCRIPT_DIR/venv" ]; then
  echo "  → Creating virtual environment..."
  python3 -m venv "$SCRIPT_DIR/venv"
fi

# Activate and install dependencies
source "$SCRIPT_DIR/venv/bin/activate"
echo "  → Installing dependencies..."
pip install -q --upgrade pip
pip install -q spotdl spotipy flask flask-cors

# Check ffmpeg
if ! command -v ffmpeg &>/dev/null; then
  echo "  ⚠️  ffmpeg not found. Please install it:"
  echo "     Ubuntu/Debian: sudo apt install ffmpeg"
  echo "     Arch:          sudo pacman -S ffmpeg"
  echo "     macOS:         brew install ffmpeg"
else
  echo "  ✓  ffmpeg found"
fi

echo ""
echo "  ✅  Setup complete! Run ./run.sh to start SpotDown."
echo ""
