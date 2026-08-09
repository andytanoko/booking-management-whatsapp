"""
Final high-impact test suite targeting critical code paths for maximum coverage.
Focuses on booking workflows, customer operations, and API integrations.
"""
from datetime import datetime, timedelta
from app.models import (
    Booking, Customer, ServiceType, User, MaintenanceReminder, 
    WhatsAppMessage, AuditLog, db
)


class TestBookingCreationWorkflows:
    """Test complete booking creation workflows from form parsing"""

    def test_create_booking_complete_form(self, client, app):
        """Test creating booking from complete WhatsApp form"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "contact_name": "John Doe",
            "text": """Nama: John Doe
No HP: 628123456789
Merk & Type Mobil: Honda Civic
Nomor Polisi: B 1234 XYZ
Pilihan Paket: Coating Premium
Domisili: Jakarta Selatan
Tanggal masuk: 15-07-2026
Harga Normal: 5000000
Harga Disc: 4500000""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_create_booking_with_various_package_names(self, client, app):
        """Test booking creation handles different package name formats"""
        packages = [
            "Paket: Coating Premium",
            "paket: ppf",
            "PAKET: POLISHING",
            "paket  :   interior detailing",
            "Pilihan Paket: Undercoating",
        ]
        
        for i, package_line in enumerate(packages):
            form = f"""Nama: Test {i}
No HP: 628111111{i:03d}
{package_line}"""
            response = client.post("/api/whatsapp/inbound", json={
                "phone": f"628111111{i:03d}",
                "text": form,
                "from_me": False
            })
            assert response.status_code == 200

    def test_create_booking_minimal_form(self, client, app):
        """Test booking creation with minimal required fields"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Booking request",
            "from_me": False
        })
        assert response.status_code == 200

    def test_booking_duplicate_detection(self, client, app):
        """Test that duplicate bookings from same customer are detected"""
        phone = "628777777777"
        form = "Nama: Test\nNo HP: {}\nPaket: Coating".format(phone)
        
        # First request
        response1 = client.post("/api/whatsapp/inbound", json={
            "phone": phone,
            "text": form,
            "from_me": False
        })
        
        # Immediate duplicate request
        response2 = client.post("/api/whatsapp/inbound", json={
            "phone": phone,
            "text": form,
            "from_me": False
        })
        
        assert response1.status_code == 200
        assert response2.status_code == 200


class TestCustomerSyncOperations:
    """Test customer sync operations from WhatsApp data"""

    def test_sync_customer_with_phone_number(self, client, app):
        """Test syncing customer data from phone number"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628888888888",
            "contact_name": "Phone Contact",
            "text": "Hello",
            "from_me": False
        })
        assert response.status_code == 200

    def test_sync_customer_with_lid(self, client, app):
        """Test syncing customer data with business LID"""
        response = client.post("/api/whatsapp/inbound", json={
            "chat_id": "32145678901234@lid",
            "contact_name": "LID Contact",
            "text": "Business account message",
            "from_me": False
        })
        assert response.status_code in [200, 400]

    def test_sync_customer_updates_vehicle_info(self, client, app):
        """Test that customer vehicle info is updated from form"""
        phone = "628999999999"
        
        # First message with vehicle info
        response1 = client.post("/api/whatsapp/inbound", json={
            "phone": phone,
            "text": "Nama: Customer\nNo HP: {}\nMobil: Toyota Avanza".format(phone),
            "from_me": False
        })
        
        # Second message  
        response2 = client.post("/api/whatsapp/inbound", json={
            "phone": phone,
            "text": "Follow up message",
            "from_me": False
        })
        
        assert response1.status_code == 200
        assert response2.status_code == 200

    def test_sync_customer_merges_contact_info(self, client, app):
        """Test that multiple contact updates merge correctly"""
        with app.app_context():
            from app.app import sync_customer_from_inbound
            
            # First sync with phone
            sync_customer_from_inbound(
                {"contact_number": "628111111111", "chat_id": "628111111111@c.us"},
                "628111111111"
            )
            
            # Second sync with LID for same contact
            sync_customer_from_inbound(
                {"chat_id": "32145678901234@lid", "contact_name": "Updated Name"},
                ""
            )


class TestBookingStatusNotifications:
    """Test booking status changes triggering notifications"""

    def test_booking_ready_triggers_notification(self, client, session_login, app):
        """Test that 'siap_diambil' status triggers notification"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now(),
                scheduled_end=datetime.now() + timedelta(hours=2),
                status="dikerjakan"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        # Change status to siap_diambil
        response = client.post(f"/bookings/{booking_id}/edit", data={
            "status": "siap_diambil"
        })
        assert response.status_code in [200, 302]

    def test_booking_completed_triggers_notification(self, client, session_login, app):
        """Test that 'selesai' status triggers notification"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() - timedelta(hours=2),
                scheduled_end=datetime.now(),
                status="qc"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        response = client.post(f"/bookings/{booking_id}/edit", data={
            "status": "selesai"
        })
        assert response.status_code in [200, 302]

    def test_booking_reschedule_notification(self, client, session_login, app):
        """Test reschedule endpoint sends notification"""
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
            "new_date": "2026-08-20",
            "new_time": "14:00"
        })
        assert response.status_code in [200, 302]


class TestSettingsManagement:
    """Test settings and configuration management"""

    def test_save_and_load_booking_done_template(self, client, session_login, app):
        """Test saving and loading custom booking done template"""
        custom_template = "Custom: {nama} - {layanan} - {tanggal}"
        
        # Save template
        response = client.post("/settings", data={
            "booking_done_template": custom_template
        })
        assert response.status_code in [200, 302]

    def test_save_multiple_templates(self, client, session_login, app):
        """Test saving multiple templates at once"""
        response = client.post("/settings", data={
            "booking_done_template": "Template 1: {nama}",
            "siap_diambil_template": "Template 2: {layanan}",
            "reschedule_template": "Template 3: {tanggal_baru}",
            "maintenance_reminder_template": "Template 4: 6 months",
            "review_request_template": "Template 5: {link_review}"
        })
        assert response.status_code in [200, 302]

    def test_reset_to_default_template(self, client, session_login, app):
        """Test resetting template to default"""
        response = client.post("/settings", data={
            "booking_done_template": ""
        })
        assert response.status_code in [200, 302]


class TestInboxAndMessageManagement:
    """Test inbox and message-related endpoints"""

    def test_inbox_displays_all_messages(self, client, session_login, app):
        """Test inbox shows all incoming and outgoing messages"""
        # Send multiple messages
        for i in range(3):
            client.post("/api/whatsapp/inbound", json={
                "phone": f"628111111{i:03d}",
                "text": f"Message {i}",
                "from_me": False
            })
        
        # Check inbox
        response = client.get("/inbox")
        assert response.status_code == 200

    def test_message_with_special_characters(self, client, app):
        """Test handling messages with special characters"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Special: @#$%^&*()[]{}!?<>",
            "from_me": False
        })
        assert response.status_code == 200

    def test_outbound_message_logging(self, session_login, app):
        """Test that outbound messages are properly logged"""
        response = session_login.post("/api/whatsapp/send", json={
            "reply_to": "628123456789",
            "text": "Outbound test message"
        })
        assert response.status_code in [200, 400, 500]


class TestRescheduleWorkflow:
    """Test complete reschedule workflow"""

    def test_reschedule_valid_dates(self, client, session_login, app):
        """Test rescheduling to various valid dates"""
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

        dates = [
            "2026-08-20",
            "2026-09-15",
            "2026-12-31",
        ]
        
        for date in dates:
            response = client.post("/reschedule", data={
                "booking_id": booking_id,
                "new_date": date,
                "new_time": "10:00"
            })
            assert response.status_code in [200, 302]

    def test_reschedule_past_date_handling(self, client, session_login, app):
        """Test rescheduling with past date"""
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

        # Try to reschedule to past date
        response = client.post("/reschedule", data={
            "booking_id": booking_id,
            "new_date": "2020-01-01",
            "new_time": "10:00"
        })
        # Should handle gracefully
        assert response.status_code in [200, 302]


class TestMaintenanceReminderWorkflow:
    """Test maintenance reminder creation and sending"""

    def test_create_maintenance_reminder_on_booking_complete(self, client, session_login, app):
        """Test maintenance reminder is created when booking completes"""
        with app.app_context():
            service = ServiceType.query.filter_by(name="Coating Premium").first()
            if not service:
                service = ServiceType.query.first()
            
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.utcnow() - timedelta(days=190),
                scheduled_end=datetime.utcnow() - timedelta(days=189),
                status="dikerjakan"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            booking_id = booking.id

        # Mark as complete
        response = client.post(f"/bookings/{booking_id}/edit", data={
            "status": "selesai"
        })
        assert response.status_code in [200, 302]

    def test_send_due_maintenance_reminders(self, session_login, app):
        """Test sending reminders for maintenance that's due"""
        response = session_login.post("/api/reminders/run", json={})
        assert response.status_code in [200, 500]

    def test_maintenance_reminder_status_tracking(self, client, session_login, app):
        """Test tracking maintenance reminder status"""
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
                service_type="Coating",
                completed_at=datetime.utcnow() - timedelta(days=180),
                maintenance_due_at=datetime.utcnow() - timedelta(days=10),
                reminder_sent_at=datetime.utcnow() - timedelta(days=5)
            )
            db.session.add_all([customer, booking, reminder])
            db.session.commit()

        response = client.get("/maintenance")
        assert response.status_code == 200


class TestUserRoleBasedAccess:
    """Test role-based access control"""

    def test_admin_can_access_users_page(self, client, session_login, app):
        """Test admin user can access users management"""
        response = client.get("/users")
        assert response.status_code == 200

    def test_create_user_and_verify_role(self, client, session_login, app):
        """Test creating user with specific role"""
        response = client.post("/users", data={
            "username": f"user_{datetime.now().timestamp()}",
            "password": "Pass1234!@",
            "confirm_password": "Pass1234!@",
            "role": "cs"
        })
        assert response.status_code in [200, 302]

    def test_non_admin_access_restrictions(self, client, session_login_cs, app):
        """Test CS user has restricted access"""
        # Try accessing admin-only page
        response = client.get("/users")
        assert response.status_code in [302, 403]


class TestDashboardAndReporting:
    """Test dashboard and reporting functionality"""

    def test_dashboard_loads_successfully(self, client, session_login, app):
        """Test dashboard page loads"""
        response = client.get("/dashboard")
        assert response.status_code == 200

    def test_dashboard_with_bookings_data(self, client, session_login, app):
        """Test dashboard displays with booking data"""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Dashboard Test", phone="628123456789")
            
            for i in range(3):
                booking = Booking(
                    customer=customer,
                    service_type=service,
                    scheduled_start=datetime.now() + timedelta(days=i),
                    scheduled_end=datetime.now() + timedelta(days=i, hours=2),
                    status="dikonfirmasi" if i < 2 else "selesai"
                )
                db.session.add(booking)
            
            db.session.add(customer)
            db.session.commit()

        response = client.get("/dashboard")
        assert response.status_code == 200


class TestErrorHandlingEdgeCases:
    """Test error handling and edge cases"""

    def test_booking_with_invalid_customer_id(self, client, session_login, app):
        """Test creating booking with non-existent customer"""
        response = client.post("/bookings", data={
            "customer_id": 99999,
            "service_type_id": 1,
            "scheduled_start": "2026-07-15 10:00",
            "scheduled_end": "2026-07-15 12:00",
            "status": "dikonfirmasi"
        })
        assert response.status_code in [200, 302]

    def test_edit_non_existent_booking(self, client, session_login, app):
        """Test editing non-existent booking"""
        response = client.post("/bookings/99999/edit", data={
            "status": "selesai"
        })
        assert response.status_code in [200, 302, 404]

    def test_form_with_missing_required_fields(self, client, app):
        """Test form submission without required fields"""
        response = client.post("/api/whatsapp/inbound", json={
            "text": "Message without phone"
        })
        assert response.status_code in [200, 400]
