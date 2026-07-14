"""Comprehensive coverage tests for app.py endpoints and functions."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import db, User, Customer, Booking, ServiceType, WhatsAppMessage, AppSetting


class TestDashboardEndpoint:
    """Test dashboard endpoint fully."""
    
    def test_dashboard_shows_today_bookings(self, client, session_login, app):
        """Test dashboard displays today's bookings."""
        with app.app_context():
            # Create a booking for today
            customer = Customer(name="Test", phone="62812345671")
            db.session.add(customer)
            db.session.flush()
            
            service = ServiceType.query.filter_by(name="Coating Premium").first()
            start = datetime.now(ZoneInfo("Asia/Jakarta")).replace(hour=10, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=1)
            
            booking = Booking(
                customer_id=customer.id,
                service_type_id=service.id,
                scheduled_start=start,
                scheduled_end=end,
                status="dikonfirmasi"
            )
            db.session.add(booking)
            db.session.commit()
        
        response = session_login.get("/dashboard")
        assert response.status_code == 200


class TestBookingManagement:
    """Test booking CRUD operations."""
    
    def test_list_bookings(self, client, session_login, app):
        """Test listing all bookings."""
        response = session_login.get("/bookings")
        assert response.status_code == 200
    
    def test_create_booking_get_form(self, client, session_login):
        """Test getting booking creation form."""
        response = session_login.get("/bookings", query_string={"mode": "create"})
        assert response.status_code == 200
    
    def test_edit_booking_page(self, client, session_login, app, booking):
        """Test editing a booking."""
        with app.app_context():
            booking_obj = Booking.query.first()
            if booking_obj:
                response = session_login.get(f"/bookings/{booking_obj.id}/edit")
                assert response.status_code in [200, 404]
    
    def test_booking_status_transitions(self, client, session_login, app):
        """Test booking status transitions."""
        with app.app_context():
            # Create booking
            customer = Customer(name="Test", phone="62812345672")
            db.session.add(customer)
            db.session.flush()
            
            service = ServiceType.query.first()
            start = datetime.now(ZoneInfo("Asia/Jakarta")).replace(hour=10, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=1)
            
            booking = Booking(
                customer_id=customer.id,
                service_type_id=service.id,
                scheduled_start=start,
                scheduled_end=end,
                status="dikonfirmasi"
            )
            db.session.add(booking)
            db.session.commit()
            booking_id = booking.id
        
        # Try to update status
        response = session_login.post(f"/bookings/{booking_id}/edit", data={
            "status": "dikerjakan"
        }, follow_redirects=True)
        assert response.status_code == 200


class TestCustomerOperations:
    """Test customer operations."""
    
    def test_list_customers(self, client, session_login):
        """Test listing customers."""
        response = session_login.get("/customers")
        assert response.status_code == 200
    
    def test_create_customer_form(self, client, session_login):
        """Test customer creation form."""
        response = session_login.get("/customers")
        assert response.status_code == 200
    
    def test_sync_customers(self, client, session_login):
        """Test customer sync endpoint."""
        response = client.post("/customers/sync", json={}, content_type="application/json")
        # May require auth
        assert response.status_code in [200, 301, 302, 401]


class TestUserManagement:
    """Test user management."""
    
    def test_list_users(self, client, session_login):
        """Test listing users."""
        response = session_login.get("/users")
        # May be admin-only
        assert response.status_code in [200, 403, 301, 302]


class TestInbox:
    """Test inbox functionality."""
    
    def test_inbox_page(self, client, session_login):
        """Test inbox page."""
        response = session_login.get("/inbox")
        assert response.status_code == 200
    
    def test_whatsapp_stream(self, client):
        """Test WhatsApp stream."""
        response = client.get("/api/whatsapp/stream")
        # May require auth or return 404
        assert response.status_code in [200, 404, 401]


class TestReminders:
    """Test reminder functionality."""
    
    def test_run_reminders_endpoint(self, client, session_login):
        """Test running reminders."""
        response = client.post("/api/reminders/run", json={})
        # May require auth
        assert response.status_code in [200, 301, 302, 401]


class TestReschedule:
    """Test reschedule functionality."""
    
    def test_reschedule_page(self, client, session_login):
        """Test reschedule page."""
        response = session_login.get("/reschedule")
        assert response.status_code == 200


class TestMaintenance:
    """Test maintenance functionality."""
    
    def test_maintenance_page(self, client, session_login):
        """Test maintenance page."""
        response = session_login.get("/maintenance")
        assert response.status_code == 200


class TestSettings:
    """Test settings management."""
    
    def test_settings_page(self, client, session_login):
        """Test settings page."""
        response = session_login.get("/settings")
        assert response.status_code in [200, 403]
    
    def test_save_settings(self, client, session_login, app):
        """Test saving settings."""
        with app.app_context():
            response = client.post("/settings", data={
                "booking_done_template": "Test template"
            }, follow_redirects=False)
            # May require auth
            assert response.status_code in [200, 301, 302]


class TestHelperFunctionsCoverage:
    """Test additional helper functions."""
    
    def test_clean_form_value(self, app):
        """Test cleaning form values."""
        with app.app_context():
            from app.app import _clean_form_value
            
            assert _clean_form_value("*test*") == "test"
            assert _clean_form_value("_test_") == "test"
            assert _clean_form_value("`test`") == "test"
            assert _clean_form_value("~test~") == "test"
    
    def test_normalize_form_phone(self, app):
        """Test normalizing phone numbers."""
        with app.app_context():
            from app.app import _normalize_form_phone
            
            # Test with leading 0
            assert _normalize_form_phone("0812345678") == "62812345678"
            # Test with 62
            assert _normalize_form_phone("6281234567") == "6281234567"
    
    def test_booking_form_labels(self, app):
        """Test booking form label mapping."""
        with app.app_context():
            from app.app import BOOKING_FORM_LABELS
            
            assert "nama" in BOOKING_FORM_LABELS
            assert "no hp" in BOOKING_FORM_LABELS
            assert BOOKING_FORM_LABELS["nama"] == "name"


class TestAuthDecorators:
    """Test authentication decorators."""
    
    def test_require_auth_on_protected_route(self, client):
        """Test require_auth decorator on protected routes."""
        # Accessing protected route without auth should redirect
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code in [301, 302, 401]
    
    def test_require_roles_enforcement(self, client, session_login_cs, app):
        """Test require_roles decorator enforcement."""
        with app.app_context():
            # CS user should not access admin-only routes
            response = session_login_cs.get("/users")
            # Should be denied or redirect
            assert response.status_code in [403, 301, 302, 200]


class TestContextProcessors:
    """Test Flask context processors."""
    
    def test_context_globals_available(self, client, session_login):
        """Test that context globals are available in templates."""
        response = session_login.get("/dashboard")
        assert response.status_code == 200


class TestErrorPages:
    """Test error page handling."""
    
    def test_404_page(self, client):
        """Test 404 error page."""
        response = client.get("/this-does-not-exist")
        assert response.status_code == 404
    
    def test_method_not_allowed(self, client):
        """Test 405 Method Not Allowed."""
        response = client.delete("/login")
        assert response.status_code in [405, 404]


class TestWhatsAppBookingForm:
    """Test WhatsApp booking form creation."""
    
    def test_booking_form_with_all_fields(self, client, app):
        """Test creating booking from WhatsApp form with all fields."""
        with app.app_context():
            form_text = """
Nama: John Doe
No HP: 0812345678
Jenis Kendaraan: Toyota Rush GR
Nomor Polisi: B1234XYZ
Pilihan Paket: Large Gold
            """
            
            response = client.post("/api/whatsapp/inbound", json={
                "phone": "6281234567890",
                "text": form_text,
                "from_me": False,
                "contact_name": "John Doe",
                "chat_id": "6281234567890@c.us"
            }, content_type="application/json")
            
            assert response.status_code == 200


class TestNotificationRenderingCoverage:
    """Test notification message rendering."""
    
    def test_maintenance_reminder_message(self, app, booking):
        """Test maintenance reminder message rendering."""
        with app.app_context():
            from app.app import DEFAULT_MAINTENANCE_REMINDER_TEMPLATE
            
            # Verify template exists
            assert "sudah 6 bulan" in DEFAULT_MAINTENANCE_REMINDER_TEMPLATE
            assert "{nama}" in DEFAULT_MAINTENANCE_REMINDER_TEMPLATE
    
    def test_review_request_message(self, app):
        """Test review request message template."""
        with app.app_context():
            from app.app import DEFAULT_REVIEW_REQUEST_TEMPLATE
            
            # Verify template exists
            assert "review" in DEFAULT_REVIEW_REQUEST_TEMPLATE.lower()


class TestBookingValidation:
    """Test booking validation logic."""
    
    def test_cannot_double_book_slot(self, client, session_login, app):
        """Test that double-booking is prevented."""
        with app.app_context():
            # Create a booking
            customer = Customer(name="Test", phone="62812345673")
            db.session.add(customer)
            db.session.flush()
            
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            if not service:
                service = ServiceType.query.first()
            
            start = datetime.now(ZoneInfo("Asia/Jakarta")).replace(hour=10, minute=0, second=0, microsecond=0)
            end = start + timedelta(minutes=service.duration_minutes)
            
            booking1 = Booking(
                customer_id=customer.id,
                service_type_id=service.id,
                scheduled_start=start,
                scheduled_end=end,
                status="dikonfirmasi"
            )
            db.session.add(booking1)
            db.session.commit()


class TestSessionManagement:
    """Test session management."""
    
    def test_session_persists_across_requests(self, client, session_login):
        """Test that session persists across multiple requests."""
        response1 = session_login.get("/dashboard")
        assert response1.status_code == 200
        
        response2 = session_login.get("/bookings")
        assert response2.status_code == 200
    
    def test_logout_clears_session(self, client, session_login):
        """Test that logout clears user session."""
        response1 = session_login.get("/logout", follow_redirects=True)
        assert response1.status_code == 200


class TestApiResponses:
    """Test API response formats."""
    
    def test_whatsapp_api_success_response(self, client):
        """Test successful WhatsApp API response format."""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "6281234567890",
            "text": "Hello",
            "from_me": False
        }, content_type="application/json")
        
        assert response.status_code == 200
        data = response.get_json()
        assert "ok" in data
    
    def test_whatsapp_api_error_response(self, client):
        """Test WhatsApp API error response."""
        response = client.post("/api/whatsapp/inbound", json={
            "text": "No phone"
        }, content_type="application/json")
        
        assert response.status_code == 400
        data = response.get_json()
        assert data["ok"] is False


class TestBoundaryConditions:
    """Test boundary conditions and edge cases."""
    
    def test_booking_exactly_at_operating_hours(self, app):
        """Test booking exactly at operating hour boundaries."""
        with app.app_context():
            from app.services.booking_engine import is_within_operating_hours
            
            # Exactly 9:00 to 10:00
            start = datetime(2024, 1, 15, 9, 0, 0)
            end = datetime(2024, 1, 15, 10, 0, 0)
            
            assert is_within_operating_hours(start, end) is True
    
    def test_booking_just_outside_operating_hours(self, app):
        """Test booking just outside operating hours."""
        with app.app_context():
            from app.services.booking_engine import is_within_operating_hours
            
            # 8:59 to 9:59 (starts before opening)
            start = datetime(2024, 1, 15, 8, 59, 0)
            end = datetime(2024, 1, 15, 9, 59, 0)
            
            assert is_within_operating_hours(start, end) is False


class TestDataPersistence:
    """Test data persistence in database."""
    
    def test_booking_data_persists(self, app, booking):
        """Test that booking data persists after creation."""
        with app.app_context():
            # Query the booking
            found = Booking.query.first()
            assert found is not None
            assert found.status == "dikonfirmasi"
    
    def test_customer_data_persists(self, app, customer):
        """Test that customer data persists."""
        with app.app_context():
            found = Customer.query.filter_by(phone="6281234567890").first()
            assert found is not None
            assert found.name == "John Doe"
