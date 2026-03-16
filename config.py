from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    APP_URL: str = "https://yourdomain.cpanelfree.com"
    SECRET_KEY: str = "CHANGE_ME"
    DEBUG: bool = False

    DB_HOST: str = "sql113.cpanelfree.com"
    DB_PORT: int = 3306
    DB_NAME: str = "cpfr_41396776_Mediaflow"
    DB_USER: str = "cpfr_41396776"
    DB_PASS: str = "7g6UNkmt20"

    ALLOWED_ORIGINS: List[str] = ["https://yourdomain.cpanelfree.com", "http://localhost"]

    JWT_SECRET: str = "CHANGE_ME_JWT"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 30

    # yt-dlp uses ffmpeg — imageio installs it to a writable path
    YTDLP_PATH: str = "/opt/render/project/.venv/bin/yt-dlp"
    FFMPEG_PATH: str = ""  # auto-detected by yt-dlp via imageio

    DOWNLOAD_TEMP: str = "/tmp/mediaflow_dl"
    UPLOAD_TEMP: str = "/tmp/mediaflow_uploads"

    class Config:
        env_file = ".env"


settings = Settings()

DATABASE_URL = (
    f"mysql+aiomysql://{settings.DB_USER}:{settings.DB_PASS}"
    f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}?charset=utf8mb4"
)
