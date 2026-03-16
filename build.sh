#!/bin/bash
set -e

echo "→ Upgrading pip..."
pip install --upgrade pip setuptools wheel

echo "→ Installing dependencies..."
pip install --no-cache-dir fastapi uvicorn[standard] pydantic pydantic-settings
pip install --no-cache-dir python-jose[cryptography] passlib[bcrypt]
pip install --no-cache-dir aiomysql "SQLAlchemy[asyncio]"
pip install --no-cache-dir httpx python-multipart aiofiles python-dotenv anyio
pip install --no-cache-dir yt-dlp

echo "→ Installing ffmpeg..."
apt-get update -qq && apt-get install -y -qq ffmpeg 2>/dev/null && echo "ffmpeg installed via apt" || \
  (wget -q https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz \
    -O /tmp/ffmpeg.tar.xz && \
   tar -xf /tmp/ffmpeg.tar.xz -C /tmp && \
   cp /tmp/ffmpeg-master-latest-linux64-gpl/bin/ffmpeg /usr/local/bin/ffmpeg && \
   chmod +x /usr/local/bin/ffmpeg && echo "ffmpeg installed manually")

echo "→ Versions:"
python -c "import fastapi; print('fastapi', fastapi.__version__)"
yt-dlp --version
echo "✓ Build complete"
