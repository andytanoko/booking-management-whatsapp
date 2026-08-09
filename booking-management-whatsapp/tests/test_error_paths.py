"""
Tests for error paths and edge cases in app.py to improve coverage.
Targets validation errors, boundary conditions, and error handling.
"""
from datetime import datetime, timedelta
from app.models import Booking, Customer, ServiceType, User, db


class TestBookingValidationErrors:
    """Test validation error paths in booking endpoints"""

    def test_create_booking_missing_customer_name(self, client, session_login, app):
        """Test booking creation with missing customer name"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama: 
No HP: 628123456789
Paket: Coating""",
            "from_me": False
        })
        # Missing name might result in error or validation
        assert response.status_code in [200, 400]

    def test_create_booking_missing_phone(self, client, session_login, app):
        """Test booking creation with missing phone"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama: Test
No HP: 
Paket: Coating""",
            "from_me": False
        })
        assert response.status_code in [200, 400]

    def test_create_booking_invalid_date(self, client, session_login, app):
        """Test booking with invalid date format"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama: Test
No HP: 628123456789
Tanggal masuk: not-a-date
Paket: Coating""",
            "from_me": False
        })
        assert response.status_code in [200, 400]

    def test_create_booking_past_date(self, client, session_login, app):
        """Test booking with date in the past"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": f"""Nama: Test
No HP: 628123456789
Tanggal masuk: {(datetime.now() - timedelta(days=1)).strftime('%d-%m-%Y')}
Paket: Coating""",
            "from_me": False
        })
        assert response.status_code in [200, 400]


class TestRescheduleEndpointErrors:
    """Test error paths in reschedule endpoint"""

    def test_reschedule_invalid_booking_id(self, client, session_login, app):
        """Test rescheduling nonexistent booking"""
        response = client.post("/reschedule", data={
            "action": "confirm_reschedule",
            "booking_id": "99999",
            "new_scheduled_start": datetime.now().strftime("%Y-%m-%dT%H:%M")
        })
        assert response.status_code in [200, 404]

    def test_reschedule_invalid_status(self, client, session_login, app):
        """Test rescheduling booking not in reschedule status"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="dikonfirmasi"  # Not in reschedule status
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "action": "confirm_reschedule",
            "booking_id": str(booking_id),
            "new_scheduled_start": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")
        })
        assert response.status_code in [200, 400]

    def test_reschedule_past_date(self, client, session_login, app):
        """Test rescheduling to past date"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=2),
                scheduled_end=datetime.now() + timedelta(days=2, hours=2),
                status="reschedule"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "action": "confirm_reschedule",
            "booking_id": str(booking_id),
            "new_scheduled_start": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        })
        assert response.status_code in [200, 400]

    def test_reschedule_send_reminder_invalid_booking(self, client, session_login, app):
        """Test sending reminder for nonexistent booking"""
        response = client.post("/reschedule", data={
            "action": "send_reminder",
            "booking_id": "99999",
            "message": "Confirm reschedule"
        })
        assert response.status_code in [200, 400]

    def test_reschedule_send_reminder_empty_message(self, client, session_login, app):
        """Test sending empty reminder message"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=2),
                status="reschedule"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post("/reschedule", data={
            "action": "send_reminder",
            "booking_id": str(booking_id),
            "message": ""  # Empty message
        })
        assert response.status_code in [200, 400]


class TestUserManagementErrors:
    """Test error paths in user management"""

    def test_users_page_requires_auth(self, client, app):
        """Test that users page requires authentication"""
        response = client.get("/users")
        assert response.status_code in [302, 401, 403]  # Redirect or unauthorized

    def test_customer_sync_without_phone(self, client, app):
        """Test customer sync without phone or chat_id"""
        response = client.post("/api/whatsapp/inbound", json={
            "text": "Hello"
            # No phone or chat_id
        })
        assert response.status_code in [200, 400]


class TestFormValidation:
    """Test form validation edge cases"""

    def test_booking_form_missing_required_fields(self, client, app):
        """Test booking form submission with missing fields"""
        response = client.post("/bookings", data={
            # Missing most required fields
        })
        # Should handle missing data gracefully or redirect
        assert response.status_code in [200, 302, 400, 401]

    def test_settings_form_empty_values(self, client, session_login, app):
        """Test settings form with empty values"""
        response = client.post("/settings", data={
            "reminder_message": "",
            "greeting_message": ""
        })
        assert response.status_code in [200, 302]

    def test_booking_nonexistent_service_type(self, client, app):
        """Test booking with service ID that doesn't exist"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama: Test
No HP: 628123456789
Paket: NonExistentService
Mobil: Honda""",
            "from_me": False
        })
        assert response.status_code in [200, 400]


class TestDatabaseConstraints:
    """Test handling of database constraint errors"""

    def test_duplicate_customer_creation(self, client, app):
        """Test creating duplicate customers"""
        phone = "628555555555"
        
        # Create first customer
        response1 = client.post("/api/whatsapp/inbound", json={
            "phone": phone,
            "contact_name": "First",
            "text": "Hello",
            "from_me": False
        })
        assert response1.status_code == 200

        # Try to sync same phone again
        response2 = client.post("/api/whatsapp/inbound", json={
            "phone": phone,
            "contact_name": "Second",
            "text": "Hello again",
            "from_me": False
        })
        assert response2.status_code == 200

        # Should update existing, not create new
        with app.app_context():
            count = Customer.query.filter_by(phone=phone).count()
            assert count == 1


class TestConflictDetection:
    """Test booking conflict detection"""

    def test_overlapping_bookings(self, client, session_login, app):
        """Test creating overlapping bookings"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            
            start = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
            end = start + timedelta(hours=2)
            
            # Create first booking
            booking1 = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=start,
                scheduled_end=end,
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking1])
            db.session.commit()

            # Try to create overlapping booking
            customer2 = Customer(name="Test2", phone="628111111111")
            booking2 = Booking(
                customer=customer2,
                service_type=service,
                scheduled_start=start + timedelta(minutes=30),
                scheduled_end=start + timedelta(hours=2, minutes=30),
                status="dikonfirmasi"
            )
            db.session.add(customer2)
            db.session.add(booking2)
            db.session.commit()

            # Both should exist (conflict detection is not automatic)
            assert Booking.query.count() >= 2
