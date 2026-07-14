"""
Focused tests for app.py endpoints and helper functions to maximize coverage.
"""
import json
from datetime import datetime, timedelta

import pytest

from app.models import Customer, ServiceType, WhatsAppMessage, db


class TestHelperFunctions:
    """Test helper functions in app.py"""

    def test_booking_notify_target_with_phone(self, client, app):
        """Test booking_notify_target with valid phone number"""
        with app.app_context():
            customer = Customer(name="Test", phone="628123456789")
            db.session.add(customer)
            db.session.commit()

            from app.app import booking_notify_target
            result = booking_notify_target(customer)
            assert result == "628123456789@c.us"

    def test_booking_notify_target_with_lid(self, client, app):
        """Test booking_notify_target with LID"""
        with app.app_context():
            customer = Customer(name="Test", phone="", lid="32145678901234")
            db.session.add(customer)
            db.session.commit()

            from app.app import booking_notify_target
            result = booking_notify_target(customer)
            assert result == "32145678901234@lid"

    def test_booking_notify_target_none(self, client, app):
        """Test booking_notify_target with None"""
        from app.app import booking_notify_target
        result = booking_notify_target(None)
        assert result == ""

    def test_booking_notify_target_invalid(self, client, app):
        """Test booking_notify_target with invalid phone"""
        with app.app_context():
            customer = Customer(name="Test", phone="invalid")
            db.session.add(customer)
            db.session.commit()

            from app.app import booking_notify_target
            result = booking_notify_target(customer)
            assert result == ""

    def test_resolve_real_number_from_contact_number(self, client, app):
        """Test resolve_real_number with contact_number"""
        from app.app import resolve_real_number
        data = {"contact_number": "628123456789"}
        result = resolve_real_number(data, "")
        assert result == "628123456789"

    def test_resolve_real_number_from_chat_id(self, client, app):
        """Test resolve_real_number from chat_id @c.us"""
        from app.app import resolve_real_number
        data = {"chat_id": "628123456789@c.us"}
        result = resolve_real_number(data, "")
        assert result == "628123456789"

    def test_resolve_real_number_from_phone(self, client, app):
        """Test resolve_real_number from phone parameter"""
        from app.app import resolve_real_number
        result = resolve_real_number({}, "628123456789")
        assert result == "628123456789"

    def test_resolve_real_number_invalid(self, client, app):
        """Test resolve_real_number with invalid data"""
        from app.app import resolve_real_number
        result = resolve_real_number({}, "not_a_phone")
        assert result == ""

    def test_extract_lid_from_chat_id(self, client, app):
        """Test extract_lid from chat_id"""
        from app.app import extract_lid
        data = {"chat_id": "32145678901234@lid"}
        result = extract_lid(data, "")
        assert result == "32145678901234"

    def test_extract_lid_from_phone_prefix(self, client, app):
        """Test extract_lid from phone with lid: prefix"""
        from app.app import extract_lid
        result = extract_lid({}, "lid:32145678901234")
        assert result == "32145678901234"

    def test_extract_lid_invalid(self, client, app):
        """Test extract_lid with invalid data"""
        from app.app import extract_lid
        result = extract_lid({}, "not_a_lid")
        assert result == ""

    def test_sync_customer_from_inbound_new_customer(self, client, app):
        """Test sync_customer_from_inbound creates new customer"""
        with app.app_context():
            from app.app import sync_customer_from_inbound
            data = {
                "contact_number": "628123456789",
                "contact_name": "John Doe",
                "chat_id": "628123456789@c.us"
            }
            sync_customer_from_inbound(data, "628123456789")
            
            customer = Customer.query.filter_by(phone="628123456789").first()
            assert customer is not None
            assert customer.name == "John Doe"

    def test_sync_customer_from_inbound_no_data(self, client, app):
        """Test sync_customer_from_inbound with no real data"""
        with app.app_context():
            from app.app import sync_customer_from_inbound
            data = {}
            # Should not raise error
            sync_customer_from_inbound(data, "")

    def test_build_message_view_with_customer(self, client, app):
        """Test build_message_view with linked customer"""
        with app.app_context():
            customer = Customer(name="Test Customer", phone="628123456789")
            db.session.add(customer)
            db.session.commit()

            msg = WhatsAppMessage(
                phone="628123456789",
                message_text="Test message",
                direction="inbound",
                status="received",
                payload_json=json.dumps({
                    "chat_id": "628123456789@c.us",
                    "contact_name": "Test"
                })
            )
            db.session.add(msg)
            db.session.commit()

            from app.app import build_message_view
            view = build_message_view(msg)
            assert view["name"] == "Test Customer"
            assert view["text"] == "Test message"
            assert view["direction"] == "inbound"

    def test_build_message_view_with_group(self, client, app):
        """Test build_message_view with group chat"""
        with app.app_context():
            msg = WhatsAppMessage(
                phone="123456789@g.us",
                message_text="Group message",
                direction="inbound",
                status="received",
                payload_json=json.dumps({"chat_id": "123456789@g.us"})
            )
            db.session.add(msg)
            db.session.commit()

            from app.app import build_message_view
            view = build_message_view(msg)
            assert "Grup" in view["number_label"] or view["number_label"] == "Grup WhatsApp"

    def test_parse_booking_form_valid(self, client, app):
        """Test parse_booking_form with valid form"""
        from app.app import parse_booking_form
        form_text = """Nama: John Doe
No HP: 628123456789
Merk & Type Mobil: Toyota Avanza
Nomor Polisi: AB 1234 CD
Pilihan Paket: Coating Premium
Tanggal Masuk: 15-07-2026"""
        result = parse_booking_form(form_text)
        assert result is not None
        assert result["name"] == "John Doe"

    def test_parse_booking_form_missing_required(self, client, app):
        """Test parse_booking_form without required fields"""
        from app.app import parse_booking_form
        form_text = """Nama: John Doe
Merk & Type Mobil: Toyota Avanza"""
        result = parse_booking_form(form_text)
        assert result is None

    def test_parse_booking_form_with_markdown(self, client, app):
        """Test parse_booking_form handles markdown emphasis"""
        from app.app import parse_booking_form
        form_text = """Nama: *John Doe*
No HP: 628123456789
Paket: _Coating Premium_"""
        result = parse_booking_form(form_text)
        assert result is not None
        assert result["name"] == "John Doe"

    def test_booking_done_message(self, client, app):
        """Test booking_done_message generation"""
        with app.app_context():
            from app.models import Booking, User
            from app.app import booking_done_message
            
            customer = Customer(name="John Doe", phone="628123456789")
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now(),
                scheduled_end=datetime.now() + timedelta(hours=1),
                status="selesai"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            message = booking_done_message(booking)
            assert "John Doe" in message
            assert "Cuci Mobil" in message

    def test_booking_reschedule_message(self, client, app):
        """Test booking_reschedule_message generation"""
        with app.app_context():
            from app.app import booking_reschedule_message
            from app.models import Booking
            
            customer = Customer(name="John", phone="628123456789")
            service = ServiceType.query.first()
            start = datetime.now()
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=start,
                scheduled_end=start + timedelta(hours=1),
                status="reschedule"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            new_start = start + timedelta(days=1)
            message = booking_reschedule_message(booking, new_start)
            assert "John" in message

    def test_clean_form_value(self, client, app):
        """Test _clean_form_value removes markdown"""
        from app.app import _clean_form_value
        
        assert _clean_form_value("*test*") == "test"
        assert _clean_form_value("_test_") == "test"
        assert _clean_form_value("`test`") == "test"
        assert _clean_form_value("~test~") == "test"

    def test_normalize_form_phone(self, client, app):
        """Test _normalize_form_phone formats phone"""
        from app.app import _normalize_form_phone
        
        # With leading 0
        assert _normalize_form_phone("0812-3456-789") == "6281234567 89".replace(" ", "")
        # Already international
        result = _normalize_form_phone("628123456789")
        assert "62" in result or result.replace(" ", "").startswith("62")


class TestLoginEndpoint:
    """Test login endpoint"""

    def test_login_page_get(self, client):
        """Test GET /login"""
        response = client.get("/login")
        assert response.status_code == 200
        assert b"Username" in response.data

    def test_login_invalid_credentials(self, client):
        """Test login with invalid credentials"""
        response = client.post("/login", data={
            "username": "admin",
            "password": "wrongpassword"
        })
        assert response.status_code == 200
        assert "salah" in response.data.decode().lower()

    def test_login_inactive_user(self, client, app):
        """Test login with inactive user"""
        with app.app_context():
            from app.models import User
            user = User(username="inactive", role="admin", active=False)
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()

        response = client.post("/login", data={
            "username": "inactive",
            "password": "password123"
        })
        assert response.status_code == 200
        assert "salah" in response.data.decode().lower()

    def test_home_redirects_to_login(self, client):
        """Test / redirects to login when not authenticated"""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location


class TestEndpointsRequireAuth:
    """Test that endpoints require authentication"""

    def test_dashboard_requires_auth(self, client):
        """Test dashboard requires authentication"""
        response = client.get("/dashboard")
        assert response.status_code == 401

    def test_bookings_requires_auth(self, client):
        """Test bookings requires authentication"""
        response = client.get("/bookings")
        assert response.status_code == 401

    def test_customers_requires_auth(self, client):
        """Test customers requires authentication"""
        response = client.get("/customers")
        assert response.status_code == 401

    def test_users_requires_auth(self, client):
        """Test users requires authentication"""
        response = client.get("/users")
        assert response.status_code == 401

    def test_inbox_requires_auth(self, client):
        """Test inbox requires authentication"""
        response = client.get("/inbox")
        assert response.status_code == 401

    def test_reschedule_requires_auth(self, client):
        """Test reschedule requires authentication"""
        response = client.get("/reschedule")
        assert response.status_code == 401

    def test_maintenance_requires_auth(self, client):
        """Test maintenance requires authentication"""
        response = client.get("/maintenance")
        assert response.status_code == 401

    def test_settings_requires_auth(self, client):
        """Test settings requires authentication"""
        response = client.get("/settings")
        assert response.status_code == 401


class TestAPIEndpoints:
    """Test API endpoints"""

    def test_whatsapp_inbound_basic(self, client):
        """Test POST /api/whatsapp/inbound"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Customer message",
            "from_me": False,
            "contact_name": "Test"
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("ok") is True

    def test_whatsapp_inbound_missing_phone(self, client):
        """Test POST /api/whatsapp/inbound without phone"""
        response = client.post("/api/whatsapp/inbound", json={
            "text": "Message"
        })
        assert response.status_code == 400

    def test_whatsapp_inbound_booking_form(self, client):
        """Test inbound booking form creation"""
        form_text = """Nama: John Doe
No HP: 628123456789
Merk & Type Mobil: Toyota
Nomor Polisi: AB 1234
Paket: Coating Premium
Tanggal Masuk: 15-07-2026"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": form_text,
            "from_me": False,
            "contact_name": "John Doe"
        })
        assert response.status_code == 200

    def test_whatsapp_send_missing_text(self, session_login):
        """Test POST /api/whatsapp/send without text"""
        response = session_login.post("/api/whatsapp/send", json={
            "reply_to": "628123456789@c.us",
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data.get("ok") is False

    def test_whatsapp_send_missing_reply_to(self, session_login):
        """Test POST /api/whatsapp/send without reply_to"""
        response = session_login.post("/api/whatsapp/send", json={
            "text": "Test message"
        })
        assert response.status_code == 400
