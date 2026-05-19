#!/usr/bin/env bash
# Setup script untuk Linux (Ubuntu 22.04+)
# Membuat virtualenv, install dependencies, dan menyiapkan .env

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "[autolive] === Setup Autolive Bot (Linux) ==="

if ! command -v python3 >/dev/null 2>&1; then
  echo "[autolive] python3 belum terinstall. Install dulu: sudo apt install python3 python3-venv python3-pip"
  exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
PY_OK="$(python3 -c 'import sys; print(sys.version_info >= (3,10))')"
if [ "$PY_OK" != "True" ]; then
  echo "[autolive] Python $PY_VERSION terdeteksi. Butuh Python 3.10+. Silakan upgrade dulu."
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[autolive] FFmpeg tidak ditemukan. Install otomatis (perlu sudo)..."
  if command -v sudo >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y ffmpeg
  else
    echo "[autolive] sudo tidak tersedia. Install FFmpeg manual: apt-get install ffmpeg"
    exit 1
  fi
fi

if [ ! -d ".venv" ]; then
  echo "[autolive] Membuat virtualenv di .venv ..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[autolive] Upgrading pip..."
pip install --upgrade pip

echo "[autolive] Install dependencies dari requirements.txt ..."
pip install -r requirements.txt

if [ ! -f ".env" ]; then
  echo "[autolive] Membuat .env dari .env.example ..."
  cp .env.example .env
  echo "[autolive] Edit .env dan isi YOUTUBE_STREAM_KEY + ANTHROPIC_API_KEY sebelum menjalankan bot."
fi

mkdir -p logs assets/backgrounds assets/music assets/fonts assets/overlays

echo "[autolive] Setup selesai. Aktifkan virtualenv lalu jalankan:"
echo "  source .venv/bin/activate"
echo "  python main.py --test-content      # preview konten"
echo "  python main.py --dry-run           # uji pipeline tanpa streaming"
echo "  python main.py                     # mulai streaming 24/7"
