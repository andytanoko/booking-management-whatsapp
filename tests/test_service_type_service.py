"""
Unit tests for service_type_service.py
"""
from app.services.service_type_service import ServiceTypeService
from app.models import ServiceType, Booking, Customer, AuditLog, db


class TestServiceTypeCreate:
    def test_create_success_minutes(self, app):
        with app.app_context():
            msg, err = ServiceTypeService.create("Wax Coat", "30", "menit", "", actor_id=None)
            assert err is None and msg
            s = ServiceType.query.filter_by(name="Wax Coat").first()
            assert s is not None and s.duration_minutes == 30 and s.active is True
            assert AuditLog.query.filter_by(action="service.create").count() == 1

    def test_create_hours_conversion(self, app):
        with app.app_context():
            ServiceTypeService.create("Big Job", "2", "jam", "Maintenance", actor_id=None)
            s = ServiceType.query.filter_by(name="Big Job").first()
            assert s.duration_minutes == 120 and s.after_service == "Maintenance"

    def test_create_bad_duration(self, app):
        with app.app_context():
            msg, err = ServiceTypeService.create("Name Here", "abc", "menit", "", actor_id=None)
            assert msg is None and err == "Durasi harus berupa angka"

    def test_create_short_name(self, app):
        with app.app_context():
            msg, err = ServiceTypeService.create("ab", "10", "menit", "", actor_id=None)
            assert msg is None and "minimal 3" in err

    def test_create_bad_after_service(self, app):
        with app.app_context():
            msg, err = ServiceTypeService.create("Valid Name", "10", "menit", "Nope", actor_id=None)
            assert msg is None and err == "After Service tidak valid"

    def test_create_duplicate(self, app):
        with app.app_context():
            db.session.add(ServiceType(name="Existing Svc", duration_minutes=10, active=True))
            db.session.commit()
            msg, err = ServiceTypeService.create("Existing Svc", "10", "menit", "", actor_id=None)
            assert msg is None and "sudah ada" in err


class TestServiceTypeUpdate:
    def _seed(self):
        s = ServiceType(name="Editable Svc", duration_minutes=10, active=True)
        db.session.add(s)
        db.session.commit()
        return s.id

    def test_update_success(self, app):
        with app.app_context():
            sid = self._seed()
            msg, err = ServiceTypeService.update(sid, "Renamed Svc", "1", "hari", "", actor_id=None)
            assert err is None and msg
            s = ServiceType.query.get(sid)
            assert s.name == "Renamed Svc" and s.duration_minutes == 1440

    def test_update_not_found(self, app):
        with app.app_context():
            msg, err = ServiceTypeService.update(99999, "Whatever", "10", "menit", "", actor_id=None)
            assert msg is None and err == "Layanan tidak ditemukan"

    def test_update_bad_duration(self, app):
        with app.app_context():
            sid = self._seed()
            msg, err = ServiceTypeService.update(sid, "Editable Svc", "x", "menit", "", actor_id=None)
            assert msg is None and err == "Durasi harus berupa angka"

    def test_update_duplicate_name(self, app):
        with app.app_context():
            sid = self._seed()
            db.session.add(ServiceType(name="Taken Svc", duration_minutes=5, active=True))
            db.session.commit()
            msg, err = ServiceTypeService.update(sid, "Taken Svc", "10", "menit", "", actor_id=None)
            assert msg is None and "sudah ada" in err


class TestServiceTypeDelete:
    def test_delete_success(self, app):
        with app.app_context():
            s = ServiceType(name="Deletable Svc", duration_minutes=10, active=True)
            db.session.add(s)
            db.session.commit()
            sid = s.id
            msg, err = ServiceTypeService.delete(sid, actor_id=None)
            assert err is None and msg
            assert ServiceType.query.get(sid) is None

    def test_delete_not_found(self, app):
        with app.app_context():
            msg, err = ServiceTypeService.delete(99999, actor_id=None)
            assert msg is None and err == "Layanan tidak ditemukan"

    def test_delete_in_use_blocked(self, app):
        with app.app_context():
            from datetime import datetime, timedelta
            s = ServiceType(name="Used Svc", duration_minutes=10, active=True)
            c = Customer(name="C", phone="628111222333")
            db.session.add_all([s, c])
            db.session.commit()
            db.session.add(Booking(
                customer_id=c.id, service_type_id=s.id,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            ))
            db.session.commit()
            msg, err = ServiceTypeService.delete(s.id, actor_id=None)
            assert msg is None and "masih digunakan" in err


class TestServiceTypeToggle:
    def test_toggle_success(self, app):
        with app.app_context():
            s = ServiceType(name="Toggle Svc", duration_minutes=10, active=True)
            db.session.add(s)
            db.session.commit()
            msg, err = ServiceTypeService.toggle(s.id, actor_id=None)
            assert err is None and msg
            assert ServiceType.query.get(s.id).active is False

    def test_toggle_not_found(self, app):
        with app.app_context():
            msg, err = ServiceTypeService.toggle(99999, actor_id=None)
            assert msg is None and err == "Layanan tidak ditemukan"
