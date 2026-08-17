"""
Unit tests for user_service.py
"""
from app.services.user_service import UserService
from app.models import User, AuditLog, db


class TestUserServiceCreate:
    def test_create_success(self, app):
        with app.app_context():
            msg, err = UserService.create("newuser", "pw", "cs", actor_id=None)
            assert err is None
            assert msg
            u = User.query.filter_by(username="newuser").first()
            assert u is not None and u.role == "cs" and u.active is True
            assert u.check_password("pw")
            assert AuditLog.query.filter_by(action="user.create").count() == 1

    def test_create_missing_fields(self, app):
        with app.app_context():
            msg, err = UserService.create("", "pw", "cs", actor_id=None)
            assert msg is None and err

    def test_create_bad_role(self, app):
        with app.app_context():
            msg, err = UserService.create("u", "pw", "wizard", actor_id=None)
            assert msg is None and err

    def test_create_duplicate_username(self, app):
        with app.app_context():
            existing = User(username="dupe", role="cs", active=True)
            existing.set_password("x")
            db.session.add(existing)
            db.session.commit()
            msg, err = UserService.create("dupe", "pw", "cs", actor_id=None)
            assert msg is None and err == "Username sudah digunakan"


class TestUserServiceUpdate:
    def _seed(self):
        u = User(username="editme", role="cs", active=True)
        u.set_password("old")
        db.session.add(u)
        db.session.commit()
        return u.id

    def test_update_success_with_password(self, app):
        with app.app_context():
            uid = self._seed()
            msg, err = UserService.update(uid, "edited", "newpw", "admin", actor_id=uid)
            assert err is None and msg
            u = User.query.get(uid)
            assert u.username == "edited" and u.role == "admin"
            assert u.check_password("newpw")

    def test_update_not_found(self, app):
        with app.app_context():
            msg, err = UserService.update(99999, "x", "", "cs", actor_id=None)
            assert msg is None and err == "User tidak ditemukan"

    def test_update_bad_role(self, app):
        with app.app_context():
            uid = self._seed()
            msg, err = UserService.update(uid, "editme", "", "nope", actor_id=uid)
            assert msg is None and err

    def test_update_duplicate_username(self, app):
        with app.app_context():
            uid = self._seed()
            other = User(username="taken", role="cs", active=True)
            other.set_password("x")
            db.session.add(other)
            db.session.commit()
            msg, err = UserService.update(uid, "taken", "", "cs", actor_id=uid)
            assert msg is None and "user lain" in err


class TestUserServiceToggle:
    def test_toggle_success(self, app):
        with app.app_context():
            u = User(username="tog", role="cs", active=True)
            u.set_password("x")
            db.session.add(u)
            db.session.commit()
            msg, err = UserService.toggle_active(u.id, actor_id=99999)
            assert err is None and msg
            assert User.query.get(u.id).active is False

    def test_toggle_self_blocked(self, app):
        with app.app_context():
            u = User(username="self", role="admin", active=True)
            u.set_password("x")
            db.session.add(u)
            db.session.commit()
            msg, err = UserService.toggle_active(u.id, actor_id=u.id)
            assert msg is None and err

    def test_toggle_not_found(self, app):
        with app.app_context():
            msg, err = UserService.toggle_active(99999, actor_id=None)
            assert msg is None and err == "User tidak ditemukan"


class TestUserServiceDelete:
    def test_delete_success(self, app):
        with app.app_context():
            u = User(username="del", role="cs", active=True)
            u.set_password("x")
            db.session.add(u)
            db.session.commit()
            uid = u.id
            msg, err = UserService.delete(uid, actor_id=99999)
            assert err is None and msg
            assert User.query.get(uid) is None

    def test_delete_self_blocked(self, app):
        with app.app_context():
            u = User(username="selfdel", role="admin", active=True)
            u.set_password("x")
            db.session.add(u)
            db.session.commit()
            msg, err = UserService.delete(u.id, actor_id=u.id)
            assert msg is None and err

    def test_delete_not_found(self, app):
        with app.app_context():
            msg, err = UserService.delete(99999, actor_id=None)
            assert msg is None and err == "User tidak ditemukan"
