import os

from dotenv import load_dotenv
load_dotenv()

class settings:
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    SESSION_NAME = os.getenv("SESSION_NAME")

    BOT_TOKEN = os.getenv("BOT_TOKEN")

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL")

    # Services
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

    # Behavior
    MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", 10))
    DEFAULT_VOLUME = int(os.getenv("DEFAULT_VOLUME", 80))

  # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()           # Default: INFO
    LOG_FILE = os.getenv("LOG_FILE", "bot.log")                  # Optional log file name
    SENTRY_DSN = os.getenv("SENTRY_DSN", None)                   # Optional Sentry DSN

    # proxy rotator Flags
    IP_ROTATION_ENABLED = os.getenv("IP_ROTATION_ENABLED", "false").lower() == "true"

settings = settings()
