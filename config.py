# config.py - Centralized environment-based configuration for AI Study Assistant
#
# Keeping all environment variable reads in one place makes it obvious what
# the app needs to run, and makes local dev vs. production (Render) behavior
# easy to reason about. Loaded once at import time by app.py.

import os

from dotenv import load_dotenv

# Load variables from a local .env file if present. In production (Render),
# environment variables are injected directly by the platform and this is a
# harmless no-op (no .env file will exist there).
load_dotenv()


class Config:
    """Base configuration shared across all environments."""

    # Flask requires a secret key to sign session cookies. NEVER hardcode this
    # in source control — generate one with `python -c "import secrets; print(secrets.token_hex(32))"`
    # and set it as the SECRET_KEY env var in production.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")

    # Gemini API key — required for any AI feature to function. See .env.example.
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

    # SQLite database file location. Override in production to point at a
    # persistent disk mount if you want data to survive redeploys on Render.
    DATABASE_PATH = os.environ.get("DATABASE_PATH", "study_assistant.db")

    # Render (and most PaaS providers) inject PORT; default to 5000 for local dev.
    PORT = int(os.environ.get("PORT", 5000))

    # Toggles Flask debug mode + auto-reload. Must be False in production.
    DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    # Cookies should only travel over HTTPS once deployed behind Render's TLS.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Logging verbosity, configurable without a code change.
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

    @classmethod
    def validate(cls):
        """
        Return a list of human-readable warnings about missing/insecure config.
        Called at startup so misconfiguration is loud and obvious in logs,
        rather than silently producing confusing runtime errors later.
        """
        warnings = []
        if not cls.GEMINI_API_KEY:
            warnings.append(
                "GEMINI_API_KEY is not set — chat, study notes, and quiz "
                "generation will all fail until it is configured."
            )
        if cls.SECRET_KEY == "dev-only-insecure-key-change-me" and not cls.DEBUG:
            warnings.append(
                "SECRET_KEY is using the insecure default in a non-debug run — "
                "set a real SECRET_KEY environment variable in production."
            )
        return warnings
