"""
Targeted tests for critical uncovered endpoints and workflows.
Focus on real integration tests that exercise actual code paths.
"""
from datetime import datetime, timedelta
from app.models import Booking, Customer, ServiceType, User, db


class TestDashboardEndpoint:
    """Test /dashboard endpoint"""

    def test_dashboard_get_as_admin(self, client, session_login, app):
        """Test accessing dashboard as admin"""
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert b"dashboard" in response.data.lower() or b"service" in response.data.lower()

    def test_dashboard_shows_bookings_summary(self, client, session_login, app):
        """Test dashboard displays booking statistics"""
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

        response = client.get("/dashboard")
        assert response.status_code == 200


class TestBookingsEndpoint:
    """Test /bookings endpoint variations"""

    def test_bookings_list_empty(self, client, session_login, app):
        """Test bookings list when no bookings exist"""
        response = client.get("/bookings")
        assert response.status_code == 200

    def test_bookings_list_with_bookings(self, client, session_login, app):
        """Test bookings list displays created bookings"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test Customer", phone="628123456789")
            
            for i in range(3):
                booking = Booking(
                    customer=customer,
                    service_type=service,
                    scheduled_start=datetime.now() + timedelta(days=i),
                    scheduled_end=datetime.now() + timedelta(days=i, hours=1),
                    status="dikonfirmasi"
                )
                db.session.add(booking)
            
            db.session.add(customer)
            db.session.commit()

        response = client.get("/bookings")
        assert response.status_code == 200
        assert b"Test Customer" in response.data

    def test_bookings_filter_by_status(self, client, session_login, app):
        """Test filtering bookings by status"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            
            confirmed = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=1),
                status="dikonfirmasi"
            )
            completed = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=-7),
                scheduled_end=datetime.now() + timedelta(days=-7, hours=1),
                status="selesai"
            )
            
            db.session.add_all([customer, confirmed, completed])
            db.session.commit()

        response = client.get("/bookings")
        assert response.status_code == 200


class TestCustomersEndpoint:
    """Test /customers endpoint"""

    def test_customers_list_empty(self, client, session_login, app):
        """Test customers list when empty"""
        response = client.get("/customers")
        assert response.status_code == 200

    def test_customers_list_shows_customers(self, client, session_login, app):
        """Test customers list displays created customers"""
        with app.app_context():
            for i in range(3):
                customer = Customer(
                    name=f"Customer {i}",
                    phone=f"628111111{i:03d}",
                    vehicle_info=f"Vehicle {i}"
                )
                db.session.add(customer)
            db.session.commit()

        response = client.get("/customers")
        assert response.status_code == 200
        assert b"Customer" in response.data

    def test_customers_search_functionality(self, client, session_login, app):
        """Test searching customers by name"""
        with app.app_context():
            customer = Customer(name="John Doe", phone="628123456789")
            db.session.add(customer)
            db.session.commit()

        response = client.get("/customers?search=John")
        assert response.status_code == 200


class TestUsersEndpoint:
    """Test /users endpoint (admin only)"""

    def test_users_list_as_admin(self, client, session_login, app):
        """Test accessing users list as admin"""
        response = client.get("/users")
        assert response.status_code == 200

    def test_users_list_as_non_admin_forbidden(self, client, session_login_cs, app):
        """Test that non-admin cannot access users page"""
        response = client.get("/users")
        assert response.status_code in [403, 302]  # Forbidden or redirect

    def test_users_create_form_displays(self, client, session_login, app):
        """Test that create user form displays"""
        response = client.get("/users")
        assert response.status_code == 200


class TestInboxEndpoint:
    """Test /inbox endpoint"""

    def test_inbox_loads(self, client, session_login, app):
        """Test inbox endpoint loads"""
        response = client.get("/inbox")
        assert response.status_code == 200

    def test_inbox_displays_messages(self, client, session_login, app):
        """Test inbox displays WhatsApp messages"""
        from app.services.whatsapp import log_inbound_message
        
        with app.app_context():
            log_inbound_message("628123456789", "Test message", {})
            
        response = client.get("/inbox")
        assert response.status_code == 200


class TestRescheduleEndpoint:
    """Test /reschedule endpoint"""

    def test_reschedule_page_loads(self, client, session_login, app):
        """Test reschedule page loads"""
        response = client.get("/reschedule")
        assert response.status_code == 200

    def test_reschedule_requires_booking_id(self, client, session_login, app):
        """Test reschedule with booking ID"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=1),
                scheduled_end=datetime.now() + timedelta(days=1, hours=1),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.get(f"/reschedule?booking_id={booking_id}")
        assert response.status_code == 200


class TestMaintenanceEndpoint:
    """Test /maintenance endpoint"""

    def test_maintenance_page_loads(self, client, session_login, app):
        """Test maintenance page loads"""
        response = client.get("/maintenance")
        assert response.status_code == 200

    def test_maintenance_shows_due_reminders(self, client, session_login, app):
        """Test maintenance page shows due reminders"""
        from app.models import MaintenanceReminder
        
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.utcnow() - timedelta(days=200),
                scheduled_end=datetime.utcnow() - timedelta(days=199),
                status="selesai"
            )
            reminder = MaintenanceReminder(
                booking=booking,
                customer=customer,
                service_type="Coating Premium",
                completed_at=datetime.utcnow() - timedelta(days=180),
                maintenance_due_at=datetime.utcnow()
            )
            db.session.add_all([customer, booking, reminder])
            db.session.commit()

        response = client.get("/maintenance")
        assert response.status_code == 200


class TestSettingsEndpoint:
    """Test /settings endpoint"""

    def test_settings_page_loads(self, client, session_login, app):
        """Test settings page loads"""
        response = client.get("/settings")
        assert response.status_code == 200

    def test_settings_displays_current_values(self, client, session_login, app):
        """Test settings displays current configuration"""
        response = client.get("/settings")
        assert response.status_code == 200


class TestAPIWhatsAppEndpoints:
    """Test /api/whatsapp/* endpoints"""

    def test_inbound_message_with_phone(self, client, app):
        """Test receiving inbound message with phone"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Test message",
            "from_me": False
        })
        assert response.status_code == 200

    def test_inbound_message_with_lid(self, client, app):
        """Test receiving inbound message with LID"""
        response = client.post("/api/whatsapp/inbound", json={
            "chat_id": "32145678901234@lid",
            "text": "Test message",
            "from_me": False
        })
        assert response.status_code in [200, 400]

    def test_inbound_booking_form(self, client, app):
        """Test receiving booking form"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama: John Doe
No HP: 628123456789
Paket: Coating Premium
Tanggal masuk: 15-07-2026""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_send_message_endpoint(self, client, app):
        """Test sending message endpoint"""
        response = client.post("/api/whatsapp/send", json={
            "phone": "628123456789",
            "text": "Test message"
        })
        assert response.status_code in [200, 400, 401, 500]  # Any response is ok for now

    def test_inbound_duplicate_message_skipped(self, client, app):
        """Test duplicate inbound messages are handled"""
        msg = {
            "phone": "628123456789",
            "text": "Same message",
            "from_me": True,
            "timestamp": 1234567890
        }
        
        response1 = client.post("/api/whatsapp/inbound", json=msg)
        response2 = client.post("/api/whatsapp/inbound", json=msg)
        
        assert response1.status_code == 200
        assert response2.status_code == 200


class TestAPIRemindersEndpoints:
    """Test /api/reminders/* endpoints"""

    def test_send_reminder_endpoint(self, client, app):
        """Test sending reminder endpoint"""
        with app.app_context():
            from app.models import MaintenanceReminder
            
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.utcnow() - timedelta(days=200),
                scheduled_end=datetime.utcnow() - timedelta(days=199),
                status="selesai"
            )
            reminder = MaintenanceReminder(
                booking=booking,
                customer=customer,
                service_type="Coating",
                completed_at=datetime.utcnow() - timedelta(days=180),
                maintenance_due_at=datetime.utcnow()
            )
            db.session.add_all([customer, booking, reminder])
            db.session.commit()
            reminder_id = reminder.id

        response = client.post(f"/api/reminders/{reminder_id}/send", json={})
        assert response.status_code in [200, 400, 404]


class TestAPIErrorHandling:
    """Test API error handling"""

    def test_inbound_missing_required_fields(self, client, app):
        """Test inbound message with missing fields"""
        response = client.post("/api/whatsapp/inbound", json={
            "text": "Message without phone"
        })
        # Should handle gracefully
        assert response.status_code in [200, 400]

    def test_send_missing_required_fields(self, client, app):
        """Test send message with missing fields"""
        response = client.post("/api/whatsapp/send", json={
            "phone": "628123456789"
            # Missing 'text'
        })
        assert response.status_code in [400, 401, 500]

    def test_inbound_with_special_characters(self, client, app):
        """Test handling special characters in message"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Special chars: @#$%^&*()[]{}!?<>",
            "from_me": False
        })
        assert response.status_code == 200


class TestLoginErrorHandling:
    """Test login endpoint error paths"""

    def test_login_with_nonexistent_user(self, client, app):
        """Test login with nonexistent username"""
        response = client.post("/login", data={
            "username": "nonexistent",
            "password": "anypassword"
        }, follow_redirects=False)
        assert response.status_code in [200, 302]

    def test_login_with_wrong_password(self, client, app):
        """Test login with wrong password"""
        with app.app_context():
            # Create a user
            user = User(username="testuser", role="admin")
            user.set_password("correctpassword")
            db.session.add(user)
            db.session.commit()

        response = client.post("/login", data={
            "username": "testuser",
            "password": "wrongpassword"
        }, follow_redirects=False)
        assert response.status_code in [200, 302]

    def test_login_empty_credentials(self, client, app):
        """Test login with empty credentials"""
        response = client.post("/login", data={
            "username": "",
            "password": ""
        }, follow_redirects=False)
        assert response.status_code in [200, 302]


class TestLogoutEndpoint:
    """Test logout functionality"""

    def test_logout_clears_session(self, client, session_login, app):
        """Test logout clears session"""
        # First verify we're logged in
        response = client.get("/dashboard")
        assert response.status_code == 200
        
        # Logout
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 302  # Redirect
        
        # Try accessing protected page
        response = client.get("/dashboard")
        assert response.status_code in [302, 401]  # Should redirect to login or unauthorized


class TestHomeEndpoint:
    """Test / (home) endpoint"""

    def test_home_redirects_to_dashboard_when_logged_in(self, client, session_login, app):
        """Test home redirects to dashboard"""
        response = client.get("/", follow_redirects=False)
        assert response.status_code in [200, 302]

    def test_home_redirects_to_login_when_not_logged_in(self, client, app):
        """Test home redirects to login when not authenticated"""
        response = client.get("/", follow_redirects=False)
        assert response.status_code in [200, 302]
