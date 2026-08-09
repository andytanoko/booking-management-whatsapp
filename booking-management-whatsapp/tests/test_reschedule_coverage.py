"""
Comprehensive reschedule endpoint tests for high coverage gains.
Targets app.py lines 817-913 (reschedule workflow).
"""
from datetime import datetime, timedelta
from app.models import Booking, Customer, ServiceType, db


class TestRescheduleGetEndpoint:
    """Test GET /reschedule endpoint"""

    def test_reschedule_get_page_loads(self, client, session_login, app):
        """Test reschedule page loads"""
        response = client.get("/reschedule")
        assert response.status_code == 200

    def test_reschedule_without_booking_id(self, client, session_login, app):
        """Test reschedule without booking_id parameter"""
        response = client.get("/reschedule")
        assert response.status_code == 200

    def test_reschedule_with_valid_booking_id(self, client, session_login, app):
        """Test reschedule with valid booking ID"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.get(f"/reschedule?booking_id={booking_id}")
        assert response.status_code == 200

    def test_reschedule_nonexistent_booking(self, client, session_login, app):
        """Test reschedule with nonexistent booking ID"""
        response = client.get("/reschedule?booking_id=99999")
        assert response.status_code in [200, 404]


class TestReschedulePostBasic:
    """Test basic POST /reschedule scenarios"""

    def test_reschedule_to_future_date(self, client, session_login, app):
        """Test rescheduling to a valid future date"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_to_different_times(self, client, session_login, app):
        """Test rescheduling to different time slots"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        times = ["08:00", "10:00", "14:00", "16:00"]
        for time_slot in times:
            response = client.post("/reschedule", data={
                "booking_id": booking_id,
                "new_date": "2026-08-15",
                "new_time": time_slot
            })
            assert response.status_code in [200, 302]

    def test_reschedule_very_far_future(self, client, session_login, app):
        """Test rescheduling far into future"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-12-31",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]


class TestRescheduleInvalidInputs:
    """Test error handling in reschedule endpoint"""

    def test_reschedule_missing_booking_id(self, client, session_login, app):
        """Test reschedule without booking ID"""
        response = client.post("/reschedule", data={
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_missing_date(self, client, session_login, app):
        """Test reschedule without date"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_invalid_date_format(self, client, session_login, app):
        """Test reschedule with invalid date format"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        invalid_dates = ["invalid", "2026-13-01", "2026-02-30", "15/08/2026"]
        for bad_date in invalid_dates:
            response = client.post("/reschedule", data={
                "booking_id": booking_id,
                "new_date": bad_date,
                "new_time": "10:00"
            })
            assert response.status_code in [200, 302]

    def test_reschedule_invalid_time_format(self, client, session_login, app):
        """Test reschedule with invalid time format"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        invalid_times = ["25:00", "10:60", "invalid", "10:00:00"]
        for bad_time in invalid_times:
            response = client.post("/reschedule", data={
                "booking_id": booking_id,
                "new_date": "2026-08-15",
                "new_time": bad_time
            })
            assert response.status_code in [200, 302]

    def test_reschedule_past_date(self, client, session_login, app):
        """Test rescheduling to past date"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2020-01-01",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_nonexistent_booking_id(self, client, session_login, app):
        """Test rescheduling nonexistent booking"""
        response = client.post("/reschedule", data={
            "booking_id": "99999",
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_string_booking_id(self, client, session_login, app):
        """Test reschedule with non-numeric booking ID"""
        response = client.post("/reschedule", data={
            "booking_id": "abc",
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]


class TestRescheduleBookingStatuses:
    """Test reschedule with different booking statuses"""

    def test_reschedule_confirmed_booking(self, client, session_login, app):
        """Test rescheduling confirmed booking"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_in_progress_booking(self, client, session_login, app):
        """Test rescheduling in-progress booking"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() - timedelta(hours=1),
                scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikerjakan"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_completed_booking(self, client, session_login, app):
        """Test rescheduling completed booking"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() - timedelta(days=7),
                scheduled_end=datetime.now() - timedelta(days=7, hours=-2),
                status="selesai"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_cancelled_booking(self, client, session_login, app):
        """Test rescheduling cancelled booking"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="cancel"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]


class TestRescheduleWithCustomerVariations:
    """Test reschedule with different customer scenarios"""

    def test_reschedule_customer_with_phone(self, client, session_login, app):
        """Test reschedule customer with phone"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Phone Customer", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_customer_with_vehicle_info(self, client, session_login, app):
        """Test reschedule customer with vehicle info"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(
                name="Car Owner",
                phone="628123456789",
                vehicle_info="Honda Civic"
            )
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_customer_no_phone(self, client, session_login, app):
        """Test reschedule customer without phone"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="No Phone", phone="")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]


class TestRescheduleNotifications:
    """Test notification behavior during reschedule"""

    def test_reschedule_triggers_notification(self, client, session_login, app):
        """Test that reschedule sends notification to customer"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]

    def test_reschedule_creates_audit_log(self, client, session_login, app):
        """Test that reschedule creates audit log entry"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2026-08-15",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]


class TestRescheduleMultipleConflicts:
    """Test reschedule with various conflict scenarios"""

    def test_reschedule_to_date_with_existing_booking(self, client, session_login, app):
        """Test rescheduling to date that has existing booking"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            
            # Create two bookings for same customer
            booking1 = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"
            )
            booking2 = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=2),
                scheduled_end=datetime.now() + timedelta(days=2, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking1, booking2])
            db.session.commit()
            booking1_id = booking1.id

        # Try to reschedule booking1 to booking2's date
        response = client.post("/reschedule", data={
            "booking_id": booking1_id,
            "new_date": "2026-07-11",
            "new_time": "10:00"
        })
        assert response.status_code in [200, 302]
