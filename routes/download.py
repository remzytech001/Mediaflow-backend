"""
routes/download.py
yt-dlp powered. Returns direct stream URL to browser.
Works without ffmpeg by using pre-merged formats only.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from database import get_db, get_setting
from middleware.auth import get_current_user, get_user_optional
from utils.helpers import ok, err, paged
from config import settings
import asyncio, json, re, shutil

router = APIRouter()

PLATFORMS = {
    "youtube":     {"re": r"(youtube\.com|youtu\.be)",    "icon": "fa-brands fa-youtube",    "color": "#FF0000"},
    "tiktok":      {"re": r"tiktok\.com",                  "icon": "fa-brands fa-tiktok",      "color": "#010101"},
    "instagram":   {"re": r"instagram\.com",               "icon": "fa-brands fa-instagram",   "color": "#E1306C"},
    "twitter":     {"re": r"(twitter\.com|x\.com)",        "icon": "fa-brands fa-x-twitter",   "color": "#000000"},
    "facebook":    {"re": r"(facebook\.com|fb\.watch)",    "icon": "fa-brands fa-facebook",    "color": "#1877F2"},
    "vimeo":       {"re": r"vimeo\.com",                   "icon": "fa-brands fa-vimeo-v",     "color": "#1AB7EA"},
    "pinterest":   {"re": r"pinterest\.",                  "icon": "fa-brands fa-pinterest",   "color": "#E60023"},
    "snapchat":    {"re": r"snapchat\.com",                "icon": "fa-brands fa-snapchat",    "color": "#FFFC00"},
    "soundcloud":  {"re": r"soundcloud\.com",              "icon": "fa-brands fa-soundcloud",  "color": "#FF5500"},
    "twitch":      {"re": r"twitch\.tv",                   "icon": "fa-brands fa-twitch",      "color": "#9146FF"},
    "reddit":      {"re": r"reddit\.com",                  "icon": "fa-brands fa-reddit",      "color": "#FF4500"},
    "dailymotion": {"re": r"dailymotion\.com",             "icon": "fa-solid fa-play",         "color": "#003E8A"},
}


def detect_platform(url: str) -> str:
    for name, info in PLATFORMS.items():
        if re.search(info["re"], url, re.I):
            return name
    return "other"


def get_ytdlp_path() -> str:
    """Find yt-dlp wherever it is installed."""
    path = shutil.which("yt-dlp")
    if path:
        return path
    for p in ["/usr/local/bin/yt-dlp", "/usr/bin/yt-dlp", "/opt/render/project/src/.venv/bin/yt-dlp"]:
        import os
        if os.path.isfile(p):
            return p
    return "yt-dlp"


async def run_ytdlp(*args, timeout=60) -> tuple[int, str, str]:
    cmd = [get_ytdlp_path()] + list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", "Timeout"
    return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


class AnalyzeIn(BaseModel):
    url: str


class StartIn(BaseModel):
    url: str
    format_id: str = "best"
    audio_only: bool = False


# ── Analyze ────────────────────────────────────────────
@router.post("/analyze")
async def analyze(
    body: AnalyzeIn,
    db: AsyncSession = Depends(get_db),
    cu=Depends(get_user_optional),
):
    url = body.url.strip()
    if not url.startswith("http"):
        return err("Please enter a valid URL starting with http.")

    platform = detect_platform(url)
    plat_info = PLATFORMS.get(platform, {"icon": "fa-solid fa-video", "color": "#3B82F6"})

    code, stdout, stderr = await run_ytdlp(
        "--dump-json",
        "--no-playlist",
        "--no-warnings",
        "--no-check-certificates",
        url
    )

    if code != 0 or not stdout.strip():
        if "Video unavailable" in stderr:
            return err("This video is unavailable or private.")
        if "Sign in" in stderr or "login" in stderr.lower():
            return err("This video requires a login.")
        if "Unsupported URL" in stderr:
            return err("This platform is not supported yet.")
        return err("Could not fetch video info. Check the URL and try again.")

    try:
        info = json.loads(stdout.strip().split('\n')[0])
    except json.JSONDecodeError:
        return err("Failed to parse video metadata.")

    user_plan = cu["plan"] if cu else "free"
    free_max_q = await get_setting(db, "free_max_quality", "720p")
    formats = _build_formats(info.get("formats", []), user_plan, free_max_q)

    return ok({
        "id":           info.get("id"),
        "title":        info.get("title", "Untitled"),
        "author":       info.get("uploader") or info.get("channel", "Unknown"),
        "thumbnail":    info.get("thumbnail"),
        "duration":     info.get("duration"),
        "view_count":   info.get("view_count"),
        "platform":     platform,
        "platform_info": plat_info,
        "formats":      formats,
        "webpage_url":  info.get("webpage_url", url),
    })


# ── Start Download ─────────────────────────────────────
@router.post("/start")
async def start_download(
    body: StartIn,
    req: Request,
    db: AsyncSession = Depends(get_db),
    cu=Depends(get_user_optional),
):
    url        = body.url.strip()
    platform   = detect_platform(url)
    user_id    = cu["id"] if cu else None
    user_plan  = cu["plan"] if cu else "free"
    ip         = req.client.host

    # Daily limit check for free users
    free_limit = int(await get_setting(db, "free_downloads_day", "10"))
    if user_plan == "free":
        cnt_query = (
            text("SELECT COUNT(*) FROM downloads WHERE user_id=:id AND DATE(created_at)=CURDATE()")
            if user_id else
            text("SELECT COUNT(*) FROM downloads WHERE ip_address=:id AND DATE(created_at)=CURDATE() AND user_id IS NULL")
        )
        cnt = (await db.execute(cnt_query, {"id": user_id or ip})).scalar()
        if cnt >= free_limit:
            return err(f"Free limit: {free_limit} downloads/day. Upgrade to Pro for unlimited.", 429)

    # Build format selector — no ffmpeg needed
    # Use best pre-merged format so no post-processing required
    if body.audio_only:
        fmt = "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio"
    else:
        fmt = body.format_id if body.format_id != "best" else "best[ext=mp4]/best"

    # Get direct URL
    code, stdout, stderr = await run_ytdlp(
        "--get-url",
        "--format", fmt,
        "--no-playlist",
        "--no-warnings",
        "--no-check-certificates",
        url
    )

    if code != 0 or not stdout.strip():
        # Fallback to absolute best single file
        code, stdout, stderr = await run_ytdlp(
            "--get-url", "--format", "best",
            "--no-playlist", "--no-warnings", "--no-check-certificates",
            url
        )
        if code != 0 or not stdout.strip():
            return err("Could not extract download URL. The video may be restricted.")

    download_url = stdout.strip().split('\n')[0]

    # Get filename
    _, fname_out, _ = await run_ytdlp(
        "--get-filename", "--format", fmt,
        "--no-playlist", "-o", "%(title)s.%(ext)s", url
    )
    filename = fname_out.strip().split('\n')[0] if fname_out.strip() else "download.mp4"

    # Log to DB
    result = await db.execute(
        text("""
            INSERT INTO downloads(user_id,platform,source_url,format,download_url,status,ip_address)
            VALUES(:uid,:plat,:src,:fmt,:dl,'ready',:ip)
        """),
        {"uid": user_id, "plat": platform, "src": url,
         "fmt": "mp3" if body.audio_only else "mp4",
         "dl": download_url, "ip": ip}
    )

    if user_id:
        await db.execute(
            text("UPDATE users SET download_count=download_count+1 WHERE id=:id"),
            {"id": user_id}
        )

    return ok({
        "download_url": download_url,
        "filename":     filename,
        "platform":     platform,
        "download_id":  result.lastrowid,
    })


# ── History ────────────────────────────────────────────
@router.get("/history")
async def history(
    page: int = 1, per_page: int = 20,
    db: AsyncSession = Depends(get_db),
    cu=Depends(get_current_user)
):
    total = (await db.execute(
        text("SELECT COUNT(*) FROM downloads WHERE user_id=:id"), {"id": cu["id"]}
    )).scalar()
    offset = (page - 1) * per_page
    rows = await db.execute(
        text("""SELECT id,platform,source_url,quality,format,status,created_at
                FROM downloads WHERE user_id=:id
                ORDER BY created_at DESC LIMIT :l OFFSET :o"""),
        {"id": cu["id"], "l": per_page, "o": offset}
    )
    return paged([dict(r._mapping) for r in rows], total, page, per_page)


def _build_formats(raw_formats: list, user_plan: str, free_max: str) -> list:
    FREE_MAX_MAP = {"360p": 0, "480p": 1, "720p": 2, "1080p": 3, "1440p": 4, "4k": 5}
    free_rank = FREE_MAX_MAP.get(free_max.lower().replace(" ", ""), 2)

    # Get available heights
    available = set()
    for f in raw_formats:
        h = f.get("height") or 0
        if h:
            available.add(h)

    quality_levels = [
        ("8K",    "best[height>=4320][ext=mp4]/best[height>=4320]", 6),
        ("4K",    "best[height>=2160][ext=mp4]/best[height>=2160]", 5),
        ("1440p", "best[height>=1440][ext=mp4]/best[height>=1440]", 4),
        ("1080p", "best[height>=1080][ext=mp4]/best[height>=1080]", 3),
        ("720p",  "best[height>=720][ext=mp4]/best[height>=720]",   2),
        ("480p",  "best[height>=480][ext=mp4]/best[height>=480]",   1),
        ("360p",  "best[ext=mp4]/best",                              0),
        ("MP3",   "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio",-1),
    ]

    result = []
    for label, fmt_str, rank in quality_levels:
        is_audio = label == "MP3"
        requires_pro = (rank > free_rank) and not is_audio
        if user_plan in ("pro", "enterprise"):
            requires_pro = False

        # Skip unavailable qualities
        if not is_audio and available:
            needed = {"8K": 4320, "4K": 2160, "1440p": 1440,
                      "1080p": 1080, "720p": 720, "480p": 480, "360p": 360}.get(label, 0)
            if needed > 0 and not any(h >= needed * 0.85 for h in available):
                continue

        result.append({
            "label":        label,
            "format_id":    fmt_str,
            "ext":          "mp3" if is_audio else "mp4",
            "requires_pro": requires_pro,
            "audio_only":   is_audio,
        })

    return result
