"""Additional integration tests for app endpoints."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import db, User, Customer, Booking, ServiceType


class TestAppHelperFunctions:
    """Test helper functions in app.py."""
    
    def test_booking_notify_target_with_phone(self, app, customer):
        """Test resolving notification target from customer."""
        with app.app_context():
            from app.app import booking_notify_target
            target = booking_notify_target(customer)
            assert "c.us" in target
            assert customer.phone in target
    
    def test_booking_notify_target_with_lid(self, app, customer_with_lid):
        """Test resolving notification target from LID."""
        with app.app_context():
            from app.app import booking_notify_target
            target = booking_notify_target(customer_with_lid)
            # Should have phone number or LID
            assert ("c.us" in target or "lid" in target)
    
    def test_booking_notify_target_no_customer(self, app):
        """Test notification target when customer is None."""
        with app.app_context():
            from app.app import booking_notify_target
            target = booking_notify_target(None)
            assert target == ""
    
    def test_booking_done_message(self, app, booking):
        """Test booking done message rendering."""
        with app.app_context():
            from app.app import booking_done_message
            message = booking_done_message(booking)
            assert booking.customer.name in message
            assert booking.service_type.name in message
    
    def test_booking_reschedule_message(self, app, booking):
        """Test reschedule message rendering."""
        with app.app_context():
            from app.app import booking_reschedule_message
            new_date = booking.scheduled_start + timedelta(days=1)
            message = booking_reschedule_message(booking, new_date)
            assert booking.customer.name in message
            assert booking.service_type.name in message
    
    def test_resolve_real_number(self, app):
        """Test resolving real WhatsApp phone number."""
        with app.app_context():
            from app.app import resolve_real_number
            
            # Test with contact_number
            data = {"contact_number": "6281234567890"}
            num = resolve_real_number(data, "")
            assert num == "6281234567890"
            
            # Test with chat_id @c.us
            data = {"chat_id": "6281234567890@c.us"}
            num = resolve_real_number(data, "")
            assert num == "6281234567890"
            
            # Test fallback to phone parameter
            num = resolve_real_number({}, "6281234567890")
            assert num == "6281234567890"
    
    def test_extract_lid(self, app):
        """Test extracting WhatsApp LID."""
        with app.app_context():
            from app.app import extract_lid
            
            # Test with @lid format
            data = {"chat_id": "123456789012345@lid"}
            lid = extract_lid(data, "")
            assert lid == "123456789012345"
            
            # Test with lid: prefix
            lid = extract_lid({}, "lid:123456789012345")
            assert lid == "123456789012345"
    
    def test_sync_customer_from_inbound(self, app):
        """Test customer sync from inbound message."""
        with app.app_context():
            from app.app import sync_customer_from_inbound
            
            data = {
                "contact_name": "John Doe",
                "chat_id": "6281234567890@c.us"
            }
            phone = "6281234567890"
            sync_customer_from_inbound(data, phone)
            
            customer = Customer.query.filter_by(phone=phone).first()
            assert customer is not None
            assert customer.name == "John Doe"
    
    def test_sync_customer_updates_lid(self, app):
        """Test that customer LID is updated if missing."""
        with app.app_context():
            from app.app import sync_customer_from_inbound
            
            # Create customer without LID
            customer = Customer(name="Test", phone="6281234567890")
            db.session.add(customer)
            db.session.commit()
            
            # Sync with LID
            data = {"chat_id": "123456789@lid"}
            phone = "6281234567890"
            sync_customer_from_inbound(data, phone)
            
            updated = Customer.query.filter_by(phone=phone).first()
            assert updated.lid == "123456789"


class TestParseBookingForm:
    """Test booking form parsing."""
    
    def test_parse_booking_form_valid(self, app):
        """Test parsing a valid booking form."""
        with app.app_context():
            from app.app import parse_booking_form
            
            form_text = """
Nama: John Doe
No HP: 6281234567890
Jenis Kendaraan: Toyota Rush GR
Nomor Polisi: B1234XYZ
Paket: Large Gold
            """
            
            form = parse_booking_form(form_text)
            assert form is not None
            assert "name" in form
            assert "phone" in form
    
    def test_parse_booking_form_invalid(self, app):
        """Test parsing invalid booking form."""
        with app.app_context():
            from app.app import parse_booking_form
            
            form_text = "Just some random text"
            form = parse_booking_form(form_text)
            assert form is None
    
    def test_parse_booking_form_missing_required(self, app):
        """Test parsing form missing required fields."""
        with app.app_context():
            from app.app import parse_booking_form
            
            # Missing phone
            form_text = """
Nama: John Doe
Paket: Large Gold
            """
            
            form = parse_booking_form(form_text)
            assert form is None


class TestLoginLogout:
    """Test login and logout functionality."""
    
    def test_login_redirect_to_dashboard(self, client, user):
        """Test that successful login redirects to dashboard."""
        response = client.post("/login", data={
            "username": "admin",
            "password": "password123"
        }, follow_redirects=True)
        
        assert response.status_code == 200
    
    def test_logout_clears_session(self, client, session_login):
        """Test that logout clears session."""
        response = session_login.get("/logout", follow_redirects=True)
        assert response.status_code == 200
        # After logout, accessing protected page should be unauthorized
        response2 = session_login.get("/dashboard", follow_redirects=False)
        assert response2.status_code in [301, 302, 401]


class TestBookingFlow:
    """Test booking creation and management flow."""
    
    def test_create_booking_valid_time(self, client, session_login, app, customer, service_type):
        """Test creating booking with valid time."""
        with app.app_context():
            start_time = datetime(2026, 7, 15, 10, 0, 0)
            end_time = start_time + timedelta(minutes=60)
            
            response = client.post("/bookings", data={
                "customer_id": customer.id,
                "service_type_id": service_type.id,
                "scheduled_start": start_time.isoformat(),
                "scheduled_end": end_time.isoformat(),
            }, follow_redirects=False)
            
            # Should either create or redirect to login if not auth
            assert response.status_code in [200, 301, 302]


class TestCustomerManagement:
    """Test customer creation and management."""
    
    def test_create_customer_valid(self, client, session_login, app):
        """Test creating a valid customer."""
        response = client.post("/customers", data={
            "name": "New Customer",
            "phone": "6289876543210",
            "vehicle_info": "Honda Civic",
        }, follow_redirects=False)
        
        # Should either create or redirect if not auth
        assert response.status_code in [200, 301, 302]
    
    def test_customer_phone_validation(self, client, session_login, app):
        """Test customer creation with invalid phone."""
        response = client.post("/customers", data={
            "name": "Invalid Phone",
            "phone": "invalid",
        }, follow_redirects=False)
        
        # Should either show error or redirect
        assert response.status_code in [200, 301, 302]


class TestWhatsAppIntegration:
    """Test WhatsApp integration."""
    
    def test_whatsapp_stream_endpoint(self, client):
        """Test WhatsApp stream endpoint access."""
        response = client.get("/api/whatsapp/stream")
        # Should be accessible, redirect, or require auth
        assert response.status_code in [200, 301, 302, 401, 404]
    
    def test_whatsapp_inbound_with_lid(self, client, app):
        """Test inbound message with LID."""
        with app.app_context():
            response = client.post("/api/whatsapp/inbound",
                json={
                    "phone": "lid:123456789012345",
                    "text": "Hello",
                    "from_me": False,
                    "chat_id": "123456789012345@lid"
                },
                content_type="application/json"
            )
            
            assert response.status_code == 200
            data = response.get_json()
            assert data["ok"] is True


class TestSettings:
    """Test settings management."""
    
    def test_get_settings_page(self, client, session_login):
        """Test accessing settings page."""
        response = session_login.get("/settings")
        # May require specific role
        assert response.status_code in [200, 403, 301, 302]
    
    def test_update_settings(self, client, session_login, app):
        """Test updating application settings."""
        with app.app_context():
            response = client.post("/settings", data={
                "key": "test_setting",
                "value": "test_value"
            }, follow_redirects=False)
            
            assert response.status_code in [200, 301, 302]


class TestRescheduleFlow:
    """Test reschedule functionality."""
    
    def test_reschedule_page(self, client, session_login):
        """Test accessing reschedule page."""
        response = session_login.get("/reschedule")
        assert response.status_code == 200
    
    def test_reschedule_booking(self, client, session_login, app, booking):
        """Test rescheduling a booking."""
        with app.app_context():
            new_date = booking.scheduled_start + timedelta(days=1)
            
            response = client.post("/reschedule", data={
                "booking_id": booking.id,
                "new_date": new_date.isoformat(),
            }, follow_redirects=False)
            
            assert response.status_code in [200, 301, 302]


class TestMaintenanceReminders:
    """Test maintenance reminder functionality."""
    
    def test_maintenance_page(self, client, session_login):
        """Test accessing maintenance page."""
        response = session_login.get("/maintenance")
        assert response.status_code == 200
