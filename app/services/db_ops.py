"""Database operation helpers for safe transaction handling."""

from flask import current_app

from app.models import db


def safe_commit(operation: str) -> bool:
    """Commit current transaction and rollback with logging on failure."""
    try:
        db.session.commit()
        return True
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("DB commit failed during %s: %s", operation, exc)
        return False


def safe_flush(operation: str) -> bool:
    """Flush current session and rollback with logging on failure."""
    try:
        db.session.flush()
        return True
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("DB flush failed during %s: %s", operation, exc)
        return False
