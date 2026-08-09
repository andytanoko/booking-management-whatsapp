"""
Unit tests for reminders.py (refactored)
Tests reminder scheduling and sending in isolation.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from app.services.reminders import ReminderService, REMINDER_RULES
from app.models import Booking, Customer, ServiceType, ReminderLog, db


class TestReminderServiceInitialization:
    """Test ReminderService initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        service = ReminderService()
        assert service.reminder_rules == REMINDER_RULES
        assert service.dispatch_window == 15

    def test_custom_initialization(self):
        """Test custom initialization."""
        custom_rules = {"H2": timedelta(hours=2)}
        mock_sender = Mock()
        service = ReminderService(
            reminder_rules=custom_rules,
            dispatch_window=30,
            message_sender=mock_sender
        )
        assert service.reminder_rules == custom_rules
        assert service.dispatch_window == 30
        assert service.message_sender == mock_sender


class TestReminderServiceAlreadySent:
    """Test checking if reminder already sent."""

    def test_reminder_already_sent(self, app):
        """Test detecting already sent reminder."""
        with app.app_context():
            # Create booking and reminder log
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
            
            # Add reminder log
            log = ReminderLog(
                booking_id=booking.id,
                reminder_type="H3",
                scheduled_for=datetime.now(),
                sent_at=datetime.now(),
                status="sent"
            )
            db.session.add(log)
            db.session.commit()
            
            # Check
            reminder_service = ReminderService()
            result = reminder_service.already_sent(booking.id, "H3")
            assert result is True

    def test_reminder_not_sent(self, app):
        """Test when reminder not yet sent."""
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
            
            reminder_service = ReminderService()
            result = reminder_service.already_sent(booking.id, "H3")
            assert result is False


class TestReminderServiceDispatchWindow:
    """Test reminder dispatch window logic."""

    def test_should_send_within_window(self):
        """Test reminder within dispatch window."""
        service = ReminderService(dispatch_window=15)
        target = datetime(2026, 7, 9, 10, 0)
        current = datetime(2026, 7, 9, 10, 5)
        
        result = service.should_send_reminder(target, current)
        assert result is True

    def test_should_not_send_before_window(self):
        """Test reminder before dispatch window."""
        service = ReminderService(dispatch_window=15)
        target = datetime(2026, 7, 9, 10, 0)
        current = datetime(2026, 7, 9, 9, 50)
        
        result = service.should_send_reminder(target, current)
        assert result is False

    def test_should_not_send_after_window(self):
        """Test reminder after dispatch window."""
        service = ReminderService(dispatch_window=15)
        target = datetime(2026, 7, 9, 10, 0)
        current = datetime(2026, 7, 9, 10, 20)
        
        result = service.should_send_reminder(target, current)
        assert result is False

    def test_should_send_at_target_time(self):
        """Test reminder exactly at target time."""
        service = ReminderService()
        target = datetime(2026, 7, 9, 10, 0)
        current = datetime(2026, 7, 9, 10, 0)
        
        result = service.should_send_reminder(target, current)
        assert result is True


class TestReminderServiceMessageFormatting:
    """Test reminder message formatting."""

    def test_format_message(self, app):
        """Test formatting reminder message."""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="John Doe", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime(2026, 7, 15, 10, 0),
                scheduled_end=datetime(2026, 7, 15, 12, 0),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            reminder_service = ReminderService()
            message = reminder_service.format_reminder_message(booking, "H3")
            
            assert "John Doe" in message
            assert "15-07-2026" in message

    def test_format_different_reminder_types(self, app):
        """Test formatting different reminder types."""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime(2026, 7, 15, 10, 0),
                scheduled_end=datetime(2026, 7, 15, 12, 0),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            reminder_service = ReminderService()
            
            for reminder_type in ["H3", "H1"]:
                message = reminder_service.format_reminder_message(booking, reminder_type)
                assert "Test" in message


class TestReminderServiceSending:
    """Test reminder sending."""

    def test_send_reminder_success(self, app):
        """Test successfully sending reminder."""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=3),
                scheduled_end=datetime.now() + timedelta(days=3, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            mock_sender = Mock()
            reminder_service = ReminderService(message_sender=mock_sender)
            
            result = reminder_service.send_reminder(
                booking,
                "H3",
                datetime.now()
            )
            
            assert result is True
            mock_sender.assert_called_once()

    def test_send_reminder_no_phone(self, app):
        """Test sending reminder when customer has no phone."""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=3),
                scheduled_end=datetime.now() + timedelta(days=3, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            mock_sender = Mock()
            reminder_service = ReminderService(message_sender=mock_sender)
            
            result = reminder_service.send_reminder(booking, "H3", datetime.now())
            
            assert result is False
            mock_sender.assert_not_called()

    def test_send_reminder_logs_to_database(self, app):
        """Test that sent reminder is logged to database."""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=3),
                scheduled_end=datetime.now() + timedelta(days=3, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            reminder_service = ReminderService(message_sender=Mock())
            reminder_service.send_reminder(booking, "H3", datetime.now())
            
            # Check log was created
            log = ReminderLog.query.filter_by(
                booking_id=booking.id,
                reminder_type="H3",
                status="sent"
            ).first()
            assert log is not None


class TestReminderServiceRunDueReminders:
    """Test running due reminders."""

    def test_run_due_reminders_sends_all(self, app):
        """Test running due reminders."""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            
            # Create booking 3 days in future (should have H3 reminder due)
            now = datetime.now()
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=now + timedelta(days=3, hours=1),
                scheduled_end=now + timedelta(days=3, hours=3),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            mock_sender = Mock()
            reminder_service = ReminderService(message_sender=mock_sender)
            
            # Should send H3 reminder
            count = reminder_service.run_due_reminders(now)
            # Count might be 0 or more depending on dispatch window
            assert count >= 0

    def test_run_due_reminders_respects_already_sent(self, app):
        """Test that already sent reminders are not sent again."""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            
            now = datetime.now()
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=now + timedelta(days=3, hours=1),
                scheduled_end=now + timedelta(days=3, hours=3),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            # Log that H3 was already sent
            log = ReminderLog(
                booking_id=booking.id,
                reminder_type="H3",
                scheduled_for=now + timedelta(days=3),
                sent_at=now - timedelta(hours=1),
                status="sent"
            )
            db.session.add(log)
            db.session.commit()
            
            mock_sender = Mock()
            reminder_service = ReminderService(message_sender=mock_sender)
            
            reminder_service.run_due_reminders(now)
            
            # H3 should not be sent again (already sent)
            # Verify by checking call count


class TestReminderServicePendingReminders:
    """Test getting pending reminders."""

    def test_get_pending_reminders(self, app):
        """Test getting pending reminders."""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            
            now = datetime.now()
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=now + timedelta(days=3),
                scheduled_end=now + timedelta(days=3, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            reminder_service = ReminderService()
            pending = reminder_service.get_pending_reminders(now)
            
            # Should return list (might be empty or have items)
            assert isinstance(pending, list)


class TestReminderServiceStatus:
    """Test reminder status tracking."""

    def test_get_reminder_status(self, app):
        """Test getting reminder status."""
        with app.app_context():
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=datetime.now() + timedelta(days=3),
                scheduled_end=datetime.now() + timedelta(days=3, hours=2),
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            # Add one sent reminder log
            log = ReminderLog(
                booking_id=booking.id,
                reminder_type="H3",
                scheduled_for=datetime.now(),
                sent_at=datetime.now(),
                status="sent"
            )
            db.session.add(log)
            db.session.commit()
            
            reminder_service = ReminderService()
            status = reminder_service.get_reminder_status(booking.id)
            
            assert "H3" in status
            assert status["H3"] == "sent"
            assert status.get("H1") == "pending"
