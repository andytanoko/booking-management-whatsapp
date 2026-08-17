"""
Unit tests for booking_service.py
"""
from datetime import datetime, timedelta

from app.services.booking_service import BookingService
from app.models import Booking, Customer, ServiceType, MaintenanceReminder, AuditLog, db


def _seed_booking(status="dikonfirmasi", service_name="Cuci Mobil"):
    service = ServiceType.query.filter_by(name=service_name).first()
    customer = Customer(name="Cust", phone="628123123123")
    db.session.add(customer)
    db.session.commit()
    booking = Booking(
        customer_id=customer.id,
        service_type_id=service.id,
        scheduled_start=datetime.now(),
        scheduled_end=datetime.now() + timedelta(hours=1),
        status=status,
    )
    db.session.add(booking)
    db.session.commit()
    return booking


class TestUpdateStatus:
    def test_not_found(self, app):
        with app.app_context():
            msg, err = BookingService.update_status(99999, "selesai", actor_id=None)
            assert msg is None and err == "Booking tidak ditemukan"

    def test_invalid_status(self, app):
        with app.app_context():
            b = _seed_booking()
            msg, err = BookingService.update_status(b.id, "bogus", actor_id=None)
            assert msg is None and err == "Status tidak valid"

    def test_success(self, app):
        with app.app_context():
            b = _seed_booking()
            msg, err = BookingService.update_status(b.id, "dikerjakan", actor_id=None)
            assert err is None and msg
            assert db.session.get(Booking, b.id).status == "dikerjakan"

    def test_selesai_creates_maintenance_reminder(self, app):
        with app.app_context():
            # PPF has after_service = Maintenance
            b = _seed_booking(service_name="PPF")
            msg, err = BookingService.update_status(b.id, "selesai", actor_id=None)
            assert err is None and "Maintenance reminder" in msg
            assert MaintenanceReminder.query.filter_by(booking_id=b.id).count() == 1

    def test_selesai_no_duplicate_reminder(self, app):
        with app.app_context():
            b = _seed_booking(service_name="PPF")
            BookingService.update_status(b.id, "selesai", actor_id=None)
            # Re-run: should not create a second reminder
            BookingService.update_status(b.id, "selesai", actor_id=None)
            assert MaintenanceReminder.query.filter_by(booking_id=b.id).count() == 1


class TestRequestReschedule:
    def test_not_found(self, app):
        with app.app_context():
            msg, err = BookingService.request_reschedule(99999, "", actor_id=None)
            assert msg is None and err == "Booking tidak ditemukan"

    def test_already_reschedule(self, app):
        with app.app_context():
            b = _seed_booking(status="reschedule")
            msg, err = BookingService.request_reschedule(b.id, "", actor_id=None)
            assert msg is None and "sudah dalam status reschedule" in err

    def test_bad_date(self, app):
        with app.app_context():
            b = _seed_booking()
            msg, err = BookingService.request_reschedule(b.id, "not-a-date", actor_id=None)
            assert msg is None and err == "Format tanggal tidak valid"

    def test_success_with_date(self, app):
        with app.app_context():
            b = _seed_booking()
            msg, err = BookingService.request_reschedule(b.id, "2030-01-02T10:00", actor_id=None)
            assert err is None and msg
            updated = db.session.get(Booking, b.id)
            assert updated.status == "reschedule"
            assert "02-01-2030" in (updated.notes or "")

    def test_success_no_date(self, app):
        with app.app_context():
            b = _seed_booking()
            msg, err = BookingService.request_reschedule(b.id, "", actor_id=None)
            assert err is None and msg
            assert db.session.get(Booking, b.id).status == "reschedule"


class TestCreateAndEdit:
    def test_create_manual_new_customer(self, app):
        with app.app_context():
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            start = datetime.now()
            booking = BookingService.create_manual(
                customer=None, customer_name="New Cust", phone="628999888777",
                vehicle_type="Sedan", service=service, start_time=start,
                end_time=start + timedelta(minutes=15), notes="n", package_name="",
                license_plate="B1", price_amount=None, actor_id=None,
            )
            assert booking.id is not None
            assert Customer.query.filter_by(phone="628999888777").first() is not None
            assert AuditLog.query.filter_by(action="booking.create").count() == 1

    def test_apply_edit(self, app):
        with app.app_context():
            b = _seed_booking()
            service = ServiceType.query.filter_by(name="Polishing").first()
            start = datetime.now() + timedelta(days=1)
            BookingService.apply_edit(
                b, b.customer, customer_name="Edited", phone="628111000111",
                vehicle_type="SUV", service=service, start_time=start,
                end_time=start + timedelta(hours=8), notes="edited", package_name="",
                license_plate="B2", price_amount=None, actor_id=None,
            )
            updated = db.session.get(Booking, b.id)
            assert updated.service_type_id == service.id
            assert updated.customer.name == "Edited" and updated.customer.phone == "628111000111"
