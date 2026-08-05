from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_SECRET_KEY_DEFAULT = "dev-secret"
_SECRET_KEY = os.getenv("SECRET_KEY", _SECRET_KEY_DEFAULT)
if _SECRET_KEY == _SECRET_KEY_DEFAULT:
    # Signs session cookies - a known, hardcoded value lets anyone forge sessions.
    logger.warning(
        "SECRET_KEY is not set - using the insecure default. Set SECRET_KEY "
        "before deploying to production."
    )


class Config:
    SECRET_KEY = _SECRET_KEY
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///detailing.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Jakarta")
