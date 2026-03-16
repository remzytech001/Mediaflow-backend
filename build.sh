#!/bin/bash
set -e

echo "→ Upgrading pip, setuptools and wheel..."
pip install --upgrade pip setuptools wheel

echo "→ Installing Python dependencies..."
pip install -r requirements.txt

echo "→ Installing yt-dlp..."
pip install -U yt-dlp

echo "→ Installing ffmpeg..."
apt-get update -qq && apt-get install -y -qq ffmpeg 2>/dev/null || \
  (wget -q https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz \
    -O /tmp/ffmpeg.tar.xz && \
   tar -xf /tmp/ffmpeg.tar.xz -C /tmp && \
   cp /tmp/ffmpeg-master-latest-linux64-gpl/bin/ffmpeg /usr/local/bin/ffmpeg && \
   chmod +x /usr/local/bin/ffmpeg)

echo "→ yt-dlp version: $(yt-dlp --version)"
echo "✓ Build complete"
