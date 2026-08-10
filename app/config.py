from __future__ import annotations

import logging
import os
import secrets

logger = logging.getLogger(__name__)

_SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not _SECRET_KEY:
    # Signs session cookies. Do not use a known static fallback value.
    _SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning(
        "SECRET_KEY is not set - using an ephemeral key for this process only. "
        "Set SECRET_KEY before deploying to production."
    )


class Config:
    SECRET_KEY = _SECRET_KEY
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///detailing.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Jakarta")
