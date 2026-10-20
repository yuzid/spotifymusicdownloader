#!/usr/bin/env bash
# ─────────────────────────────────────────────────────
# SpotDown — Start Script
# ─────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/venv"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5000}"

# Check venv
if [ ! -d "$VENV" ]; then
  echo "❌  Virtual environment not found. Run setup.sh first."
  exit 1
fi

# Activate venv
source "$VENV/bin/activate"

echo ""
echo "  🎵  SpotDown — Spotify Downloader"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  → URL    : http://127.0.0.1:$PORT (http://localhost:$PORT)"
echo "  → Press Ctrl+C to stop"
echo ""

# Open browser on localhost after 1 second
(sleep 1 && xdg-open "http://127.0.0.1:$PORT" 2>/dev/null \
  || open "http://127.0.0.1:$PORT" 2>/dev/null || true) &

# Start Flask on localhost
HOST="$HOST" PORT="$PORT" python "$SCRIPT_DIR/backend/app.py"
