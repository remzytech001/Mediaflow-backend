#!/bin/bash
set -e

echo "→ Upgrading pip..."
pip install --upgrade pip

echo "→ Installing Python packages..."
pip install -r requirements.txt

echo "→ Installing yt-dlp..."
pip install -U yt-dlp

echo "→ Installing ffmpeg..."
apt-get update -qq 2>/dev/null && apt-get install -y -qq ffmpeg 2>/dev/null || {
  echo "apt failed, trying static ffmpeg..."
  mkdir -p /usr/local/bin
  wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -O /tmp/ff.tar.xz \
    && tar -xf /tmp/ff.tar.xz -C /tmp \
    && cp /tmp/ffmpeg-*-static/ffmpeg /usr/local/bin/ffmpeg \
    && cp /tmp/ffmpeg-*-static/ffprobe /usr/local/bin/ffprobe \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && echo "ffmpeg installed from static build"
}

echo "→ Verifying installs..."
yt-dlp --version && echo "✓ yt-dlp OK"
ffmpeg -version 2>&1 | head -1 && echo "✓ ffmpeg OK"

echo "✓ Build complete"
