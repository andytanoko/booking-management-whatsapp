"""
Audit service - centralizes writes to the AuditLog table.

Keeps `db.session.add(AuditLog(...))` out of routes/blueprints so the audit
trail is written in exactly one place.
"""
from typing import Optional

from app.models import AuditLog, db


class AuditService:
    """Service for recording audit-trail entries."""

    @staticmethod
    def log(
        action: str,
        actor_id: Optional[int] = None,
        details: str = '',
        commit: bool = False,
    ) -> AuditLog:
        """Record an audit-trail entry.

        Adds the row to the session. By default it does not commit, so callers
        can group the audit write into the same transaction as the change it
        describes and commit once. Pass ``commit=True`` for standalone entries.
        """
        entry = AuditLog(actor_user_id=actor_id, action=action, details=details)
        db.session.add(entry)
        if commit:
            db.session.commit()
        return entry
