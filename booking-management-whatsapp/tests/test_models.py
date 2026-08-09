"""Tests for models module."""

import pytest
from datetime import datetime
from app.models import db, User, Customer, ServiceType, Booking, WhatsAppMessage, ReminderLog, MaintenanceReminder, AuditLog, AppSetting


class TestUser:
    """Test cases for User model."""
    
    def test_user_creation(self, app):
        """Test creating a new user."""
        with app.app_context():
            user = User(username="testuser", role="admin")
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()
            
            assert user.id is not None
            assert user.username == "testuser"
            assert user.role == "admin"
            assert user.active is True
    
    def test_user_password_hashing(self, app):
        """Test password hashing and verification."""
        with app.app_context():
            user = User(username="testuser", role="cs")
            user.set_password("mypassword")
            db.session.add(user)
            db.session.commit()
            
            assert user.check_password("mypassword") is True
            assert user.check_password("wrongpassword") is False
    
    def test_user_unique_username(self, app):
        """Test that usernames must be unique."""
        with app.app_context():
            user1 = User(username="duplicate", role="admin")
            user1.set_password("pass1")
            db.session.add(user1)
            db.session.commit()
            
            user2 = User(username="duplicate", role="cs")
            user2.set_password("pass2")
            db.session.add(user2)
            
            with pytest.raises(Exception):  # IntegrityError
                db.session.commit()
    
    def test_user_inactive_flag(self, app):
        """Test user active flag."""
        with app.app_context():
            user = User(username="inactive", role="admin", active=False)
            user.set_password("pass")
            db.session.add(user)
            db.session.commit()
            
            assert user.active is False


class TestCustomer:
    """Test cases for Customer model."""
    
    def test_customer_creation(self, app):
        """Test creating a new customer."""
        with app.app_context():
            customer = Customer(
                name="John Doe",
                phone="6281234567890",
                vehicle_info="Toyota Rush GR"
            )
            db.session.add(customer)
            db.session.commit()
            
            assert customer.id is not None
            assert customer.name == "John Doe"
            assert customer.phone == "6281234567890"
    
    def test_customer_phone_unique(self, app):
        """Test that phone numbers must be unique."""
        with app.app_context():
            customer1 = Customer(name="John", phone="6281234567890")
            db.session.add(customer1)
            db.session.commit()
            
            customer2 = Customer(name="Jane", phone="6281234567890")
            db.session.add(customer2)
            
            with pytest.raises(Exception):  # IntegrityError
                db.session.commit()
    
    def test_customer_with_lid(self, app):
        """Test customer with LID (WhatsApp private ID)."""
        with app.app_context():
            customer = Customer(
                name="Jane",
                phone="6281234567891",
                lid="123456789012345"
            )
            db.session.add(customer)
            db.session.commit()
            
            assert customer.lid == "123456789012345"
            # Verify LID is indexed
            found = Customer.query.filter_by(lid="123456789012345").first()
            assert found is not None


class TestServiceType:
    """Test cases for ServiceType model."""
    
    def test_service_type_creation(self, app):
        """Test creating a service type."""
        with app.app_context():
            service = ServiceType(
                name="Test Service Type",
                duration_minutes=360,
                active=True
            )
            db.session.add(service)
            db.session.commit()
            
            assert service.id is not None
            assert service.duration_minutes == 360
    
    def test_service_type_unique_name(self, app):
        """Test that service names must be unique."""
        with app.app_context():
            service1 = ServiceType(name="Unique Service Name 1", duration_minutes=480)
            db.session.add(service1)
            db.session.commit()
            
            service2 = ServiceType(name="Unique Service Name 1", duration_minutes=600)
            db.session.add(service2)
            
            with pytest.raises(Exception):  # IntegrityError
                db.session.commit()
    
    def test_service_type_inactive(self, app):
        """Test inactive service types."""
        with app.app_context():
            service = ServiceType(
                name="Old Service Type",
                duration_minutes=120,
                active=False
            )
            db.session.add(service)
            db.session.commit()
            
            assert service.active is False


class TestBooking:
    """Test cases for Booking model."""
    
    def test_booking_creation(self, app, customer, service_type):
        """Test creating a booking."""
        with app.app_context():
            from datetime import timedelta
            start = datetime.now()
            end = start + timedelta(minutes=service_type.duration_minutes)
            
            booking = Booking(
                customer_id=customer.id,
                service_type_id=service_type.id,
                scheduled_start=start,
                scheduled_end=end,
                status="dikonfirmasi"
            )
            db.session.add(booking)
            db.session.commit()
            
            assert booking.id is not None
            assert booking.status == "dikonfirmasi"
    
    def test_booking_with_user_assignment(self, app, customer, service_type, user, tech_user):
        """Test booking with user assignments."""
        with app.app_context():
            from datetime import timedelta
            start = datetime.now()
            end = start + timedelta(minutes=60)
            
            booking = Booking(
                customer_id=customer.id,
                service_type_id=service_type.id,
                scheduled_start=start,
                scheduled_end=end,
                created_by_user_id=user.id,
                assigned_tech_id=tech_user.id
            )
            db.session.add(booking)
            db.session.commit()
            
            assert booking.created_by_user_id == user.id
            assert booking.assigned_tech_id == tech_user.id
    
    def test_booking_optional_fields(self, app, customer, service_type):
        """Test booking with optional fields."""
        with app.app_context():
            from datetime import timedelta
            start = datetime.now()
            end = start + timedelta(minutes=60)
            
            booking = Booking(
                customer_id=customer.id,
                service_type_id=service_type.id,
                scheduled_start=start,
                scheduled_end=end,
                vehicle_type="Honda City",
                license_plate="B1234ABC",
                other_info="Large Gold",
                notes="Extra care needed"
            )
            db.session.add(booking)
            db.session.commit()
            
            assert booking.vehicle_type == "Honda City"
            assert booking.license_plate == "B1234ABC"
            assert booking.other_info == "Large Gold"


class TestWhatsAppMessage:
    """Test cases for WhatsAppMessage model."""
    
    def test_whatsapp_message_creation(self, app):
        """Test creating a WhatsApp message."""
        with app.app_context():
            msg = WhatsAppMessage(
                direction="inbound",
                phone="6281234567890",
                message_text="Hello from WhatsApp",
                status="received"
            )
            db.session.add(msg)
            db.session.commit()
            
            assert msg.id is not None
            assert msg.direction == "inbound"
    
    def test_whatsapp_message_outbound(self, app):
        """Test outbound WhatsApp message."""
        with app.app_context():
            msg = WhatsAppMessage(
                direction="outbound",
                phone="6281234567890",
                message_text="Thank you for booking",
                status="sent"
            )
            db.session.add(msg)
            db.session.commit()
            
            assert msg.direction == "outbound"
            assert msg.status == "sent"


class TestMaintenanceReminder:
    """Test cases for MaintenanceReminder model."""
    
    def test_maintenance_reminder_creation(self, app, booking):
        """Test creating a maintenance reminder."""
        with app.app_context():
            from datetime import timedelta
            now = datetime.utcnow()
            due_at = now + timedelta(days=180)
            
            reminder = MaintenanceReminder(
                booking_id=booking.id,
                customer_id=booking.customer_id,
                service_type="Coating Premium",
                completed_at=now,
                maintenance_due_at=due_at
            )
            db.session.add(reminder)
            db.session.commit()
            
            assert reminder.id is not None
            assert reminder.service_type == "Coating Premium"


class TestAuditLog:
    """Test cases for AuditLog model."""
    
    def test_audit_log_creation(self, app, user):
        """Test creating an audit log."""
        with app.app_context():
            log = AuditLog(
                actor_user_id=user.id,
                action="booking_created",
                details="Booking #123 created"
            )
            db.session.add(log)
            db.session.commit()
            
            assert log.id is not None
            assert log.action == "booking_created"


class TestAppSetting:
    """Test cases for AppSetting model."""
    
    def test_app_setting_creation(self, app):
        """Test creating an app setting."""
        with app.app_context():
            setting = AppSetting(
                key="booking_done_template",
                value="Your booking is done!"
            )
            db.session.add(setting)
            db.session.commit()
            
            assert setting.id is not None
            assert setting.key == "booking_done_template"
    
    def test_app_setting_unique_key(self, app):
        """Test that settings keys must be unique."""
        with app.app_context():
            setting1 = AppSetting(key="test_key", value="value1")
            db.session.add(setting1)
            db.session.commit()
            
            setting2 = AppSetting(key="test_key", value="value2")
            db.session.add(setting2)
            
            with pytest.raises(Exception):  # IntegrityError
                db.session.commit()
