"""
routes/download.py
yt-dlp runs on Render.com server — no exec() restrictions.
Returns direct stream URL to browser (no file stored on server).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from database import get_db, setting
from middleware.auth import get_current_user, optional_user
from utils.response import ok, err, paged
from config import PLATFORMS
import yt_dlp, re, asyncio, logging

router = APIRouter()
logger = logging.getLogger(__name__)


def detect_platform(url: str) -> str:
    patterns = {
        "youtube":    r"(youtube\.com|youtu\.be)",
        "tiktok":     r"tiktok\.com",
        "instagram":  r"instagram\.com",
        "twitter":    r"(twitter\.com|x\.com)",
        "facebook":   r"(facebook\.com|fb\.watch)",
        "vimeo":      r"vimeo\.com",
        "pinterest":  r"pinterest\.",
        "snapchat":   r"snapchat\.com",
        "soundcloud": r"soundcloud\.com",
        "twitch":     r"twitch\.tv",
        "reddit":     r"reddit\.com",
        "dailymotion":r"dailymotion\.com",
        "linkedin":   r"linkedin\.com",
        "bilibili":   r"bilibili\.com",
    }
    for name, pat in patterns.items():
        if re.search(pat, url, re.I):
            return name
    return "other"


QUALITY_FORMATS = {
    "360p":  "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "480p":  "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "720p":  "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]",
    "4k":    "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "max":   "bestvideo+bestaudio/best",
    "audio": "bestaudio/best",
}


class AnalyzeIn(BaseModel):
    url: str


class StartIn(BaseModel):
    url:        str
    quality:    str = "720p"
    audio_only: bool = False


def _ytdlp_info(url: str) -> dict:
    """Extract info without downloading — runs in thread."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "noplaylist": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _ytdlp_url(url: str, fmt: str) -> str:
    """Get the direct media URL for a format — runs in thread."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": fmt,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        # For merged formats, return the best direct url available
        if "url" in info:
            return info["url"]
        # For split video+audio, return the video url (browser will handle)
        formats = info.get("formats", [])
        if formats:
            return formats[-1].get("url", "")
        return ""


# ── Analyze ────────────────────────────────────────────
@router.post("/analyze")
async def analyze(
    body: AnalyzeIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(optional_user),
):
    url = body.url.strip()
    if not url.startswith("http"):
        return err("Please enter a valid URL starting with http.")

    platform = detect_platform(url)
    plat_info = PLATFORMS.get(platform, {"name": platform.title(), "icon": "fa-solid fa-video", "color": "#3B82F6"})

    try:
        info = await asyncio.to_thread(_ytdlp_info, url)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "Private" in msg or "unavailable" in msg.lower():
            return err("This video is private or unavailable.")
        if "age" in msg.lower():
            return err("Age-restricted content cannot be downloaded.")
        return err(f"Could not read video info. The URL may be invalid or unsupported.")
    except Exception as e:
        logger.error(f"yt-dlp error: {e}")
        return err("Failed to analyze URL. Please try again.")

    user_plan = current_user["plan"] if current_user else "free"

    # Build quality options
    raw_formats = info.get("formats", [])
    seen_heights = set()
    qualities = []
    for f in reversed(raw_formats):
        h = f.get("height")
        if not h or h in seen_heights:
            continue
        seen_heights.add(h)
        label = f"{h}p"
        is_pro = h > 720
        qualities.append({
            "label":    label,
            "value":    label,
            "pro_only": is_pro,
            "locked":   is_pro and user_plan == "free",
            "filesize": f.get("filesize") or f.get("filesize_approx"),
        })
    qualities.sort(key=lambda x: int(x["value"].replace("p","")), reverse=True)
    # Always add audio
    qualities.append({"label": "MP3 Audio", "value": "audio", "pro_only": False, "locked": False, "filesize": None})

    return ok({
        "id":           info.get("id"),
        "title":        info.get("title", "Untitled"),
        "author":       info.get("uploader") or info.get("channel", ""),
        "thumbnail":    info.get("thumbnail"),
        "duration":     info.get("duration"),
        "view_count":   info.get("view_count"),
        "platform":     platform,
        "platform_info":plat_info,
        "webpage_url":  info.get("webpage_url", url),
        "qualities":    qualities,
        "has_subtitles":bool(info.get("subtitles")),
    })


# ── Start Download ─────────────────────────────────────
@router.post("/start")
async def start_download(
    body: StartIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(optional_user),
):
    url = body.url.strip()
    platform = detect_platform(url)
    user_id  = current_user["id"]   if current_user else None
    plan     = current_user["plan"] if current_user else "free"
    ip       = request.client.host

    # ── Daily limit check ────────────────────────────
    daily_limit = int(await setting(db, "free_downloads_day", "10"))
    if plan in ("free", None):
        key = ("SELECT COUNT(*) FROM downloads WHERE user_id=:id AND DATE(created_at)=CURDATE()"
               if user_id else
               "SELECT COUNT(*) FROM downloads WHERE ip_address=:id AND DATE(created_at)=CURDATE()")
        count = (await db.execute(text(key), {"id": user_id or ip})).scalar()
        if count >= daily_limit:
            return err(
                f"Daily limit reached ({daily_limit} downloads/day on Free plan). "
                "Upgrade to Pro for unlimited downloads.", 429
            )

    # ── Quality cap for free users ───────────────────
    quality = "audio" if body.audio_only else body.quality
    if plan == "free" and quality not in ("360p","480p","720p","audio"):
        quality = await setting(db, "free_max_quality", "720p")

    fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["720p"])

    # ── Get direct URL via yt-dlp ────────────────────
    try:
        download_url = await asyncio.to_thread(_ytdlp_url, url, fmt)
    except Exception as e:
        logger.error(f"yt-dlp download URL error: {e}")
        return err("Could not process this video. It may be private or region-locked.")

    if not download_url:
        return err("No downloadable stream found for this quality.")

    # ── Log to database ──────────────────────────────
    r = await db.execute(
        text("""
            INSERT INTO downloads(user_id,platform,source_url,quality,format,download_url,status,ip_address)
            VALUES(:uid,:plat,:src,:q,:fmt,:dl,'ready',:ip)
        """),
        {"uid": user_id, "plat": platform, "src": url, "q": quality,
         "fmt": "mp3" if body.audio_only else "mp4",
         "dl": download_url, "ip": ip}
    )
    if user_id:
        await db.execute(text("UPDATE users SET download_count=download_count+1 WHERE id=:id"), {"id": user_id})

    return ok({
        "download_url": download_url,
        "quality":      quality,
        "platform":     platform,
        "audio_only":   body.audio_only,
        "download_id":  r.lastrowid,
    })


# ── History ───────────────────────────────────────────
@router.get("/history")
async def history(
    page: int = 1, per_page: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    uid = current_user["id"]
    total = (await db.execute(text("SELECT COUNT(*) FROM downloads WHERE user_id=:id"), {"id": uid})).scalar()
    offset = (page-1)*per_page
    rows = await db.execute(
        text("SELECT id,platform,source_url,title,quality,format,status,download_url,created_at FROM downloads WHERE user_id=:id ORDER BY created_at DESC LIMIT :l OFFSET :o"),
        {"id": uid, "l": per_page, "o": offset}
    )
    return paged([dict(r._mapping) for r in rows], total, page, per_page)
