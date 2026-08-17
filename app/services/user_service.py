"""
User service - user account management (create/update/toggle/delete).

Keeps all User table writes and the related validation/audit logic out of the
route layer.
"""
from typing import Optional, Tuple

from app.models import User, db
from app.services.audit_service import AuditService

VALID_ROLES = {'admin', 'cs', 'technician'}

# (message, error) - exactly one is non-None.
Result = Tuple[Optional[str], Optional[str]]


class UserService:
    """Service for managing user accounts."""

    @staticmethod
    def create(username: str, password: str, role: str, actor_id: Optional[int]) -> Result:
        username = (username or '').strip()
        password = (password or '').strip()
        role = (role or '').strip()
        if not username or not password or role not in VALID_ROLES:
            return None, 'Username, password, dan role wajib diisi'
        if User.query.filter_by(username=username).first():
            return None, 'Username sudah digunakan'
        user = User(username=username, role=role, active=True)
        user.set_password(password)
        db.session.add(user)
        AuditService.log('user.create', actor_id=actor_id, details=f'username={username} role={role}')
        db.session.commit()
        return 'User berhasil ditambahkan', None

    @staticmethod
    def update(user_id: int, username: str, password: str, role: str, actor_id: Optional[int]) -> Result:
        username = (username or '').strip()
        password = (password or '').strip()
        role = (role or '').strip()
        user = User.query.get(user_id)
        if not user:
            return None, 'User tidak ditemukan'
        if not username or role not in VALID_ROLES:
            return None, 'Username dan role wajib diisi'
        if User.query.filter(User.username == username, User.id != user_id).first():
            return None, 'Username sudah digunakan oleh user lain'
        user.username = username
        user.role = role
        if password:
            user.set_password(password)
        AuditService.log('user.update', actor_id=actor_id, details=f'user_id={user_id} username={username} role={role}')
        db.session.commit()
        return f"User '{username}' berhasil diperbarui", None

    @staticmethod
    def toggle_active(user_id: int, actor_id: Optional[int]) -> Result:
        user = User.query.get(user_id)
        if not user:
            return None, 'User tidak ditemukan'
        if user.id == actor_id:
            return None, 'Tidak bisa menonaktifkan akun sendiri'
        user.active = not user.active
        AuditService.log('user.toggle_active', actor_id=actor_id, details=f'username={user.username} active={user.active}')
        db.session.commit()
        return f"User '{user.username}' berhasil {'diaktifkan' if user.active else 'dinonaktifkan'}", None

    @staticmethod
    def delete(user_id: int, actor_id: Optional[int]) -> Result:
        user = User.query.get(user_id)
        if not user:
            return None, 'User tidak ditemukan'
        if user.id == actor_id:
            return None, 'Tidak bisa menghapus akun sendiri'
        username = user.username
        AuditService.log('user.delete', actor_id=actor_id, details=f'username={user.username} role={user.role}')
        db.session.delete(user)
        db.session.commit()
        return f"User '{username}' berhasil dihapus", None
