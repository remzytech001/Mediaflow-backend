from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "MediaFlow Pro"
    SECRET_KEY: str = "change_me"
    JWT_SECRET: str = "change_me_jwt"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 30
    DEBUG: bool = False

    # Database — your cPanel MySQL
    DB_HOST: str = "sql113.cpanelfree.com"
    DB_PORT: int = 3306
    DB_NAME: str = "cpfr_41396776_Mediaflow"
    DB_USER: str = "cpfr_41396776"
    DB_PASS: str = "7g6UNkmt20"

    # CORS
    FRONTEND_URL: str = "https://yourdomain.cpanelfree.com"

    # Paystack (can also be changed from Admin Panel)
    PAYSTACK_PUBLIC_KEY: str = "pk_live_REPLACE_ME"
    PAYSTACK_SECRET_KEY: str = "sk_live_REPLACE_ME"

    # yt-dlp temp folder on Render
    DOWNLOAD_TEMP_DIR: str = "/tmp/mediaflow_downloads"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

DATABASE_URL = (
    f"mysql+aiomysql://{settings.DB_USER}:{settings.DB_PASS}"
    f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
    f"?charset=utf8mb4"
)

# All platforms yt-dlp supports (shown on frontend)
PLATFORMS = {
    "youtube":     {"name": "YouTube",    "icon": "fa-brands fa-youtube",    "color": "#FF0000"},
    "tiktok":      {"name": "TikTok",     "icon": "fa-brands fa-tiktok",     "color": "#010101"},
    "instagram":   {"name": "Instagram",  "icon": "fa-brands fa-instagram",  "color": "#E1306C"},
    "twitter":     {"name": "Twitter/X",  "icon": "fa-brands fa-x-twitter",  "color": "#000000"},
    "facebook":    {"name": "Facebook",   "icon": "fa-brands fa-facebook",   "color": "#1877F2"},
    "vimeo":       {"name": "Vimeo",      "icon": "fa-brands fa-vimeo-v",    "color": "#1AB7EA"},
    "pinterest":   {"name": "Pinterest",  "icon": "fa-brands fa-pinterest",  "color": "#E60023"},
    "snapchat":    {"name": "Snapchat",   "icon": "fa-brands fa-snapchat",   "color": "#FFFC00"},
    "soundcloud":  {"name": "SoundCloud", "icon": "fa-brands fa-soundcloud", "color": "#FF5500"},
    "twitch":      {"name": "Twitch",     "icon": "fa-brands fa-twitch",     "color": "#9146FF"},
    "reddit":      {"name": "Reddit",     "icon": "fa-brands fa-reddit",     "color": "#FF4500"},
    "dailymotion": {"name": "Dailymotion","icon": "fa-solid fa-play",        "color": "#003E8A"},
    "linkedin":    {"name": "LinkedIn",   "icon": "fa-brands fa-linkedin",   "color": "#0A66C2"},
    "bilibili":    {"name": "Bilibili",   "icon": "fa-solid fa-video",       "color": "#00A1D6"},
}
