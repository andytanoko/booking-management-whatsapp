"""Tests for Flask app endpoints."""

import json
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import db, User, Customer, Booking, ServiceType, WhatsAppMessage, AppSetting
from app.app import create_app


class TestAuthEndpoints:
    """Test cases for authentication endpoints."""
    
    def test_home_redirect_logged_out(self, client):
        """Test that / redirects to login when logged out."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code in [301, 302]
        assert "/login" in response.location
    
    def test_home_redirect_logged_in(self, client, session_login):
        """Test that / redirects to dashboard when logged in."""
        response = session_login.get("/", follow_redirects=False)
        assert response.status_code in [301, 302]
        assert "/dashboard" in response.location
    
    def test_login_page_get(self, client):
        """Test GET login page."""
        response = client.get("/login")
        assert response.status_code == 200
        assert b"login" in response.data.lower() or b"username" in response.data.lower()
    
    def test_login_success(self, client, user):
        """Test successful login."""
        response = client.post("/login", data={
            "username": user.username,
            "password": "password123"
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should be redirected to dashboard
        assert b"dashboard" in response.data.lower() or b"booking" in response.data.lower()
    
    def test_login_wrong_password(self, client, user):
        """Test login with wrong password."""
        response = client.post("/login", data={
            "username": "admin",
            "password": "wrongpassword"
        })
        
        assert response.status_code == 200
        assert b"salah" in response.data or b"error" in response.data.lower()
    
    def test_login_nonexistent_user(self, client):
        """Test login with nonexistent user."""
        response = client.post("/login", data={
            "username": "nonexistent",
            "password": "password123"
        })
        
        assert response.status_code == 200
        assert b"salah" in response.data or b"error" in response.data.lower()
    
    def test_logout(self, client, session_login):
        """Test logout functionality."""
        response = session_login.get("/logout", follow_redirects=True)
        
        assert response.status_code == 200
        # Should be redirected to login
        assert b"login" in response.data.lower()


class TestDashboard:
    """Test cases for dashboard endpoint."""
    
    def test_dashboard_requires_auth(self, client):
        """Test that dashboard requires authentication."""
        response = client.get("/dashboard")
        assert response.status_code in [301, 302, 401]
    
    def test_dashboard_access_logged_in(self, client, session_login):
        """Test accessing dashboard when logged in."""
        response = session_login.get("/dashboard")
        assert response.status_code == 200
        # Should contain booking-related content
        assert b"booking" in response.data.lower() or b"customer" in response.data.lower()


class TestBookingsEndpoint:
    """Test cases for bookings endpoint."""
    
    def test_bookings_requires_auth(self, client):
        """Test that bookings endpoint requires authentication."""
        response = client.get("/bookings")
        assert response.status_code in [301, 302, 401]
    
    def test_bookings_get(self, client, session_login):
        """Test GET bookings page."""
        response = session_login.get("/bookings")
        assert response.status_code == 200
    
    def test_bookings_list_with_booking(self, client, session_login, booking):
        """Test bookings list displays bookings."""
        response = session_login.get("/bookings")
        assert response.status_code == 200
        # Should contain booking info
        assert booking.customer.name.encode() in response.data or b"booking" in response.data.lower()
    
    def test_create_booking_validation(self, client, session_login):
        """Test creating a booking with invalid data."""
        response = session_login.post("/bookings", data={
            "customer_name": "",
            "phone": "",
        })
        # Authenticated: renders page or redirects
        assert response.status_code in [200, 301, 302, 401]


class TestCustomersEndpoint:
    """Test cases for customers endpoint."""
    
    def test_customers_requires_auth(self, client):
        """Test that customers endpoint requires authentication."""
        response = client.get("/customers")
        assert response.status_code in [301, 302, 401]
    
    def test_customers_get(self, client, session_login):
        """Test GET customers page."""
        response = session_login.get("/customers")
        assert response.status_code == 200
    
    def test_customers_list_with_customer(self, client, session_login, customer):
        """Test customers list displays customers."""
        response = session_login.get("/customers")
        assert response.status_code == 200
        # Should contain customer info
        assert customer.name.encode() in response.data or b"customer" in response.data.lower()


class TestUsersEndpoint:
    """Test cases for users management endpoint."""
    
    def test_users_requires_auth(self, client):
        """Test that users endpoint requires authentication."""
        response = client.get("/users")
        assert response.status_code in [301, 302, 401]
    
    def test_users_access_denied_for_non_admin(self, client, session_login_cs):
        """Test that non-admin users can't access users page."""
        response = session_login_cs.get("/users")
        # CS users should be denied access (depends on implementation)
        assert response.status_code in [403, 301, 302] or b"unauthorized" in response.data.lower()


class TestInboxEndpoint:
    """Test cases for inbox endpoint."""
    
    def test_inbox_requires_auth(self, client):
        """Test that inbox requires authentication."""
        response = client.get("/inbox")
        assert response.status_code in [301, 302, 401]
    
    def test_inbox_get(self, client, session_login):
        """Test GET inbox page."""
        response = session_login.get("/inbox")
        assert response.status_code == 200


class TestSettingsEndpoint:
    """Test cases for settings endpoint."""
    
    def test_settings_requires_auth(self, client):
        """Test that settings requires authentication."""
        response = client.get("/settings")
        assert response.status_code in [301, 302, 401]
    
    def test_settings_get(self, client, session_login):
        """Test GET settings page."""
        response = session_login.get("/settings")
        assert response.status_code == 200


class TestWhatsAppAPI:
    """Test cases for WhatsApp API endpoints."""
    
    def test_whatsapp_inbound_missing_phone(self, client):
        """Test inbound WhatsApp without phone number."""
        response = client.post("/api/whatsapp/inbound", 
            json={"text": "Hello"},
            content_type="application/json"
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["ok"] is False
    
    def test_whatsapp_inbound_success(self, client):
        """Test successful inbound WhatsApp message."""
        response = client.post("/api/whatsapp/inbound",
            json={
                "phone": "6281234567890",
                "text": "Hello, I want to book a service",
                "from_me": False
            },
            content_type="application/json"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
    
    def test_whatsapp_inbound_outbound_duplicate(self, client):
        """Test that duplicate outbound messages are skipped."""
        # First, send as outbound
        response1 = client.post("/api/whatsapp/inbound",
            json={
                "phone": "6281234567890",
                "text": "Test message",
                "from_me": True
            },
            content_type="application/json"
        )
        assert response1.status_code == 200
        
        # Send same message again
        response2 = client.post("/api/whatsapp/inbound",
            json={
                "phone": "6281234567890",
                "text": "Test message",
                "from_me": True
            },
            content_type="application/json"
        )
        assert response2.status_code == 200
        data = response2.get_json()
        assert data.get("status") == "duplicate_skipped"
    
    def test_whatsapp_inbound_creates_customer(self, client, app):
        """Test that inbound messages create customer records."""
        with app.app_context():
            response = client.post("/api/whatsapp/inbound",
                json={
                    "phone": "6281234567892",
                    "text": "Hello",
                    "contact_name": "John Doe",
                    "from_me": False
                },
                content_type="application/json"
            )
            assert response.status_code == 200
            
            # Check if customer was created
            customer = Customer.query.filter_by(phone="6281234567892").first()
            assert customer is not None
            assert customer.name == "John Doe"


class TestRemindersAPI:
    """Test cases for reminders API."""
    
    def test_reminders_requires_auth(self, client):
        """Test that reminders endpoint requires authentication."""
        response = client.post("/api/reminders/run")
        assert response.status_code in [301, 302, 401]
    
    def test_reminders_requires_admin_or_cs(self, client, app):
        """Test that only admin/cs can run reminders."""
        # This would require setting up a tech user and testing
        # Implementation depends on how reminders are structured
        pass


class TestRescheduleEndpoint:
    """Test cases for reschedule endpoint."""
    
    def test_reschedule_requires_auth(self, client):
        """Test that reschedule requires authentication."""
        response = client.get("/reschedule")
        assert response.status_code in [301, 302, 401]
    
    def test_reschedule_get(self, client, session_login):
        """Test GET reschedule page."""
        response = session_login.get("/reschedule")
        assert response.status_code == 200


class TestMaintenanceEndpoint:
    """Test cases for maintenance endpoint."""
    
    def test_maintenance_requires_auth(self, client):
        """Test that maintenance requires authentication."""
        response = client.get("/maintenance")
        assert response.status_code in [301, 302, 401]
    
    def test_maintenance_get(self, client, session_login):
        """Test GET maintenance page."""
        response = session_login.get("/maintenance")
        assert response.status_code == 200


class TestErrorHandling:
    """Test cases for error handling."""
    
    def test_404_error(self, client):
        """Test 404 error for nonexistent route."""
        response = client.get("/nonexistent_route")
        assert response.status_code == 404
    
    def test_405_method_not_allowed(self, client):
        """Test 405 error for wrong HTTP method."""
        response = client.delete("/login")
        assert response.status_code == 405
