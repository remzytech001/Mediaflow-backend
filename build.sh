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

echo "→ Installing ffmpeg via imageio..."
pip install --no-cache-dir imageio[ffmpeg]
python -c "import imageio; imageio.plugins.ffmpeg.download()"

echo "→ Versions:"
python -c "import fastapi; print('fastapi', fastapi.__version__)"
python -c "import yt_dlp; print('yt-dlp', yt_dlp.version.__version__)"
echo "✓ Build complete"
