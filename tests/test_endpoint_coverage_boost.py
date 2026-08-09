"""
Comprehensive endpoint coverage tests targeting uncovered app.py branches.
Focuses on /bookings POST actions, edit_booking, reschedule, maintenance,
and customer sync endpoints.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from app.models import (
    db, User, Customer, ServiceType, Booking,
    MaintenanceReminder, WhatsAppMessage, AuditLog
)


def _mk_datetime_str(days_ahead=1, hour=10):
    """Build a schedule string within operating hours on a future weekday."""
    dt = datetime.now() + timedelta(days=days_ahead)
    dt = dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M")


class TestBookingsUpdateStatus:
    """Test /bookings POST update_status action."""

    def test_update_status_booking_not_found(self, session_login, app):
        with app.app_context():
            resp = session_login.post("/bookings", data={
                "action": "update_status",
                "booking_id": "99999",
                "status": "selesai",
            })
            assert resp.status_code == 200
            assert "tidak ditemukan".encode() in resp.data or b"Booking" in resp.data

    def test_update_status_invalid_status(self, session_login, app):
        with app.app_context():
            customer = Customer(name="C", phone="628111000111")
            service = ServiceType.query.filter_by(name="Coating Premium").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=2),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/bookings", data={
            "action": "update_status",
            "booking_id": str(bid),
            "status": "not_a_real_status",
        })
        assert resp.status_code == 200

    def test_request_reschedule_without_date(self, session_login, app):
        with app.app_context():
            customer = Customer(name="C5", phone="628111000555")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/bookings", data={
            "action": "request_reschedule",
            "booking_id": str(bid),
            "new_scheduled_start": "",
        })
        assert resp.status_code == 200
        with app.app_context():
            assert db.session.get(Booking, bid).status == "reschedule"

    def test_request_reschedule_with_date(self, session_login, app):
        with app.app_context():
            customer = Customer(name="C6", phone="628111000666")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/bookings", data={
            "action": "request_reschedule",
            "booking_id": str(bid),
            "new_scheduled_start": "2026-12-31",
        })
        assert resp.status_code == 200
        with app.app_context():
            booking = db.session.get(Booking, bid)
            assert booking.status == "reschedule"
            assert "Permintaan reschedule" in (booking.notes or "")

    def test_update_status_valid(self, session_login, app):
        with app.app_context():
            customer = Customer(name="C2", phone="628111000222")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/bookings", data={
            "action": "update_status",
            "booking_id": str(bid),
            "status": "dikerjakan",
        })
        assert resp.status_code == 200
        with app.app_context():
            assert db.session.get(Booking, bid).status == "dikerjakan"

    def test_update_status_selesai_creates_maintenance(self, session_login, app):
        with app.app_context():
            customer = Customer(name="C3", phone="628111000333")
            service = ServiceType.query.filter_by(name="Coating Premium").first()
            service.after_service = "Maintenance"
            db.session.commit()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=2),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/bookings", data={
            "action": "update_status",
            "booking_id": str(bid),
            "status": "selesai",
        })
        assert resp.status_code == 200
        with app.app_context():
            reminder = MaintenanceReminder.query.filter_by(booking_id=bid).first()
            assert reminder is not None


class TestBookingsNotifyCustomer:
    """Test /bookings POST notify_customer action."""

    def test_notify_booking_not_found(self, session_login, app):
        resp = session_login.post("/bookings", data={
            "action": "notify_customer",
            "booking_id": "99999",
            "message": "Hello",
        })
        assert resp.status_code == 200

    def test_notify_empty_message(self, session_login, app):
        with app.app_context():
            customer = Customer(name="C4", phone="628111000444")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/bookings", data={
            "action": "notify_customer",
            "booking_id": str(bid),
            "message": "",
        })
        assert resp.status_code == 200

    def test_notify_success(self, session_login, app):
        with app.app_context():
            customer = Customer(name="C5", phone="628111000555")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/bookings", data={
            "action": "notify_customer",
            "booking_id": str(bid),
            "message": "Kendaraan siap",
        })
        assert resp.status_code == 200


class TestBookingsCreate:
    """Test /bookings POST create booking flow."""

    def test_create_with_service_id(self, session_login, app):
        with app.app_context():
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            sid = service.id

        resp = session_login.post("/bookings", data={
            "customer_name": "New Cust",
            "phone": "628222000111",
            "vehicle_type": "Toyota",
            "service_id": str(sid),
            "scheduled_start": _mk_datetime_str(),
        })
        assert resp.status_code == 200

    def test_create_with_package_name(self, session_login, app):
        resp = session_login.post("/bookings", data={
            "customer_name": "Pkg Cust",
            "phone": "628222000222",
            "package_name": "Coating Premium",
            "scheduled_start": _mk_datetime_str(),
        })
        assert resp.status_code == 200

    def test_create_invalid_date(self, session_login, app):
        resp = session_login.post("/bookings", data={
            "customer_name": "Bad Date",
            "phone": "628222000333",
            "package_name": "Cuci Mobil",
            "scheduled_start": "not-a-date",
        })
        assert resp.status_code == 200
        assert "tidak valid".encode() in resp.data or b"tanggal" in resp.data.lower()

    def test_create_outside_operating_hours(self, session_login, app):
        with app.app_context():
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            sid = service.id
        # 3 AM is outside operating hours
        resp = session_login.post("/bookings", data={
            "customer_name": "Night Cust",
            "phone": "628222000444",
            "service_id": str(sid),
            "scheduled_start": _mk_datetime_str(hour=3),
        })
        assert resp.status_code == 200


class TestEditBooking:
    """Test /bookings/<id>/edit endpoint."""

    def test_edit_get_page(self, session_login, app):
        with app.app_context():
            customer = Customer(name="Edit C", phone="628333000111")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.get(f"/bookings/{bid}/edit")
        assert resp.status_code == 200

    def test_edit_not_found(self, session_login, app):
        resp = session_login.get("/bookings/99999/edit")
        assert resp.status_code == 404

    def test_edit_update_missing_fields(self, session_login, app):
        with app.app_context():
            customer = Customer(name="Edit C2", phone="628333000222")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post(f"/bookings/{bid}/edit", data={
            "action": "update",
            "customer_name": "",
            "phone": "",
        })
        assert resp.status_code == 200

    def test_edit_update_success(self, session_login, app):
        with app.app_context():
            customer = Customer(name="Edit C3", phone="628333000333")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id
            sid = service.id

        resp = session_login.post(f"/bookings/{bid}/edit", data={
            "action": "update",
            "customer_name": "Updated Name",
            "phone": "628333000333",
            "service_id": str(sid),
            "scheduled_start": _mk_datetime_str(),
        }, follow_redirects=False)
        assert resp.status_code in [200, 302]


class TestRescheduleEndpoint:
    """Test /reschedule endpoint."""

    def test_reschedule_get(self, session_login, app):
        resp = session_login.get("/reschedule")
        assert resp.status_code == 200

    def test_reschedule_send_reminder_not_found(self, session_login, app):
        resp = session_login.post("/reschedule", data={
            "action": "send_reminder",
            "booking_id": "99999",
            "message": "Reminder",
        })
        assert resp.status_code == 200

    def test_reschedule_confirm_not_found(self, session_login, app):
        resp = session_login.post("/reschedule", data={
            "action": "confirm_reschedule",
            "booking_id": "99999",
            "new_scheduled_start": _mk_datetime_str(),
        })
        assert resp.status_code == 200

    def test_reschedule_confirm_wrong_status(self, session_login, app):
        with app.app_context():
            customer = Customer(name="RS C", phone="628444000111")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",  # not reschedule
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/reschedule", data={
            "action": "confirm_reschedule",
            "booking_id": str(bid),
            "new_scheduled_start": _mk_datetime_str(),
        })
        assert resp.status_code == 200

    def test_reschedule_confirm_success(self, session_login, app):
        with app.app_context():
            customer = Customer(name="RS C2", phone="628444000222")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="reschedule",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/reschedule", data={
            "action": "confirm_reschedule",
            "booking_id": str(bid),
            "new_scheduled_start": _mk_datetime_str(),
        })
        assert resp.status_code == 200
        with app.app_context():
            assert db.session.get(Booking, bid).status == "dikonfirmasi"

    def test_reschedule_confirm_invalid_date(self, session_login, app):
        with app.app_context():
            customer = Customer(name="RS C3", phone="628444000333")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="reschedule",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            bid = booking.id

        resp = session_login.post("/reschedule", data={
            "action": "confirm_reschedule",
            "booking_id": str(bid),
            "new_scheduled_start": "invalid-date",
        })
        assert resp.status_code == 200


class TestMaintenanceEndpoint:
    """Test /maintenance endpoint."""

    def _make_reminder(self, app, phone="628555000111"):
        with app.app_context():
            customer = Customer(name="Maint C", phone=phone)
            service = ServiceType.query.filter_by(name="Coating Premium").first()
            booking = Booking(
                customer=customer, service_type=service,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=2),
                status="selesai",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            reminder = MaintenanceReminder(
                booking_id=booking.id,
                customer_id=customer.id,
                service_type="Coating Premium",
                completed_at=datetime.utcnow() - timedelta(days=180),
                maintenance_due_at=datetime.utcnow(),
            )
            db.session.add(reminder)
            db.session.commit()
            return reminder.id

    def test_maintenance_get(self, session_login, app):
        resp = session_login.get("/maintenance")
        assert resp.status_code == 200

    def test_maintenance_send_reminder_not_found(self, session_login, app):
        resp = session_login.post("/maintenance", data={
            "action": "send_reminder",
            "reminder_id": "99999",
        })
        assert resp.status_code == 200

    def test_maintenance_send_reminder(self, session_login, app):
        rid = self._make_reminder(app, phone="628555000222")
        resp = session_login.post("/maintenance", data={
            "action": "send_reminder",
            "reminder_id": str(rid),
        })
        assert resp.status_code == 200

    def test_maintenance_send_review(self, session_login, app):
        rid = self._make_reminder(app, phone="628555000333")
        resp = session_login.post("/maintenance", data={
            "action": "send_review",
            "reminder_id": str(rid),
        })
        assert resp.status_code == 200


class TestCustomerSync:
    """Test /customers/sync-whatsapp endpoint with mocked bridge."""

    def test_sync_bridge_not_found(self, session_login, app):
        with patch("app.app.fetch_whatsapp_contacts", return_value=(False, "bridge-not-found", [])):
            resp = session_login.post("/customers/sync", data={}, follow_redirects=False)
            assert resp.status_code in [200, 302]

    def test_sync_creates_contacts(self, session_login, app):
        contacts = [
            {"number": "628666000111", "lid": "", "name": "Sync One"},
            {"number": "628666000222", "lid": "", "name": "Sync Two"},
        ]
        with patch("app.app.fetch_whatsapp_contacts", return_value=(True, "ok", contacts)):
            resp = session_login.post("/customers/sync", data={}, follow_redirects=False)
            assert resp.status_code in [200, 302]
        with app.app_context():
            assert Customer.query.filter_by(phone="628666000111").first() is not None

    def test_sync_updates_existing(self, session_login, app):
        with app.app_context():
            existing = Customer(name="WhatsApp 1234", phone="628666000333")
            db.session.add(existing)
            db.session.commit()
        contacts = [
            {"number": "628666000333", "lid": "", "name": "Real Name"},
        ]
        with patch("app.app.fetch_whatsapp_contacts", return_value=(True, "ok", contacts)):
            resp = session_login.post("/customers/sync", data={}, follow_redirects=False)
            assert resp.status_code in [200, 302]
