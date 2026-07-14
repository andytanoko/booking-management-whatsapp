from __future__ import annotations

import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///detailing.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Jakarta")
    WHATSAPP_MODE = os.getenv("WHATSAPP_MODE", "mock")
