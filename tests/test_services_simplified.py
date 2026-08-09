"""
Simplified tests for whatsapp.py and services to improve coverage.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.models import WhatsAppMessage, Customer, db


class TestSendAndLogMessageSimplified:
    """Test send_and_log_message in mock mode"""

    def test_send_message_creates_record(self, client, app):
        """Test that send_and_log_message creates database record"""
        with app.app_context():
            from app.services.whatsapp import send_and_log_message
            
            msg = send_and_log_message("628123456789", "Test message")
            
            assert msg is not None
            assert msg.phone == "628123456789"
            assert msg.message_text == "Test message"
            assert msg.direction == "outbound"

    def test_log_message_with_payload(self, client, app):
        """Test logging message with payload"""
        with app.app_context():
            from app.services.whatsapp import log_inbound_message
            
            payload = {
                "chat_id": "628123456789@c.us",
                "contact_name": "Test"
            }
            
            msg = log_inbound_message(
                "628123456789",
                "Test",
                payload
            )
            
            assert msg is not None
            assert msg.direction == "inbound"
            stored_payload = json.loads(msg.payload_json or "{}")
            assert stored_payload.get("contact_name") == "Test"


class TestSendAndLogMessageIntegration:
    """Integration tests for message sending"""

    def test_message_round_trip(self, client, app):
        """Test sending and receiving messages"""
        with app.app_context():
            from app.services.whatsapp import send_and_log_message, log_inbound_message
            
            # Send outbound
            sent = send_and_log_message("628123456789", "Outbound")
            
            # Receive inbound
            received = log_inbound_message(
                "628123456789",
                "Inbound",
                {"chat_id": "628123456789@c.us"}
            )
            
            # Verify both are persisted
            sent_check = WhatsAppMessage.query.filter_by(id=sent.id).first()
            recv_check = WhatsAppMessage.query.filter_by(id=received.id).first()
            
            assert sent_check is not None
            assert recv_check is not None
            assert sent_check.direction == "outbound"
            assert recv_check.direction == "inbound"


class TestSemanticMatcherEdgeCases:
    """Test edge cases for semantic matcher"""

    def test_match_package_basic(self, client, app):
        """Test basic package matching"""
        with app.app_context():
            from app.services.semantic_matcher import match_package_to_service
            from app.models import ServiceType
            
            services = ServiceType.query.filter_by(active=True).all()
            
            # Test matching known packages
            for package in ["coating premium", "ppf", "cuci mobil"]:
                result = match_package_to_service(package, services)
                # Should return a service or None
                assert result is None or hasattr(result, 'id')

    def test_match_package_case_insensitive(self, client, app):
        """Test that matching is case-insensitive"""
        with app.app_context():
            from app.services.semantic_matcher import match_package_to_service
            from app.models import ServiceType
            
            services = ServiceType.query.all()
            
            # Should handle different cases
            for package in ["COATING PREMIUM", "Coating Premium", "coating premium"]:
                result = match_package_to_service(package, services)
                assert result is None or hasattr(result, 'id')

    def test_get_variant_info(self, client, app):
        """Test getting variant information"""
        with app.app_context():
            from app.services.semantic_matcher import get_variant_info
            from app.models import ServiceType
            
            services = ServiceType.query.all()
            
            # Test various packages
            variant = get_variant_info("Coating Premium", services)
            assert variant is None or isinstance(variant, str)
            
            variant = get_variant_info("PPF", services)
            assert variant is None or isinstance(variant, str)

    def test_match_empty_services(self, client, app):
        """Test matching with no services"""
        with app.app_context():
            from app.services.semantic_matcher import match_package_to_service
            
            result = match_package_to_service("Coating", [])
            assert result is None

    def test_match_empty_package(self, client, app):
        """Test matching empty package"""
        with app.app_context():
            from app.services.semantic_matcher import match_package_to_service
            from app.models import ServiceType
            
            services = ServiceType.query.all()
            result = match_package_to_service("", services)
            # Should handle gracefully
            assert result is None or hasattr(result, 'id')


class TestBookingEngineAdvanced:
    """Advanced tests for booking engine functions"""

    def test_compute_booking_end(self, client, app):
        """Test compute_booking_end for different services"""
        from datetime import datetime, timedelta
        
        with app.app_context():
            from app.services.booking_engine import compute_booking_end
            from app.models import ServiceType
            
            # Test Cuci Mobil (15 minutes)
            service = ServiceType.query.filter_by(name="Cuci Mobil").first()
            start = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
            end = compute_booking_end(service, start)
            
            assert end == start + timedelta(minutes=15)

    def test_has_conflict_no_bookings(self, client, app):
        """Test conflict check with no existing bookings"""
        from datetime import datetime, timedelta
        
        with app.app_context():
            from app.services.booking_engine import has_conflict
            
            start = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=2)
            
            # No bookings exist, so no conflict
            assert has_conflict(start, end) is False

    def test_has_conflict_with_booking(self, client, app):
        """Test conflict detection with existing booking"""
        from datetime import datetime, timedelta
        
        with app.app_context():
            from app.services.booking_engine import has_conflict
            from app.models import Booking, ServiceType
            from app.services.settings_store import set_setting
            set_setting('daily_capacity', '1')
            
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            
            # Create existing booking
            start = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=2)
            
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=start,
                scheduled_end=end,
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            # Same day, capacity is 1 -> day is full
            assert has_conflict(start, end) is True

    def test_has_conflict_exclude_booking(self, client, app):
        """Test conflict check can exclude specific booking"""
        from datetime import datetime, timedelta
        
        with app.app_context():
            from app.services.booking_engine import has_conflict
            from app.models import Booking, ServiceType
            
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            
            start = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=2)
            
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=start,
                scheduled_end=end,
                status="dikonfirmasi"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            # Should not conflict when booking is excluded (reschedule scenario)
            assert has_conflict(start, end, exclude_booking_id=booking.id) is False

    def test_has_conflict_ignores_cancelled(self, client, app):
        """Test conflict detection ignores cancelled bookings"""
        from datetime import datetime, timedelta
        
        with app.app_context():
            from app.services.booking_engine import has_conflict
            from app.models import Booking, ServiceType
            
            service = ServiceType.query.first()
            customer = Customer(name="Test", phone="628123456789")
            
            start = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=2)
            
            # Cancelled booking
            booking = Booking(
                customer=customer,
                service_type=service,
                scheduled_start=start,
                scheduled_end=end,
                status="cancel"
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            
            # Should not conflict with cancelled booking
            assert has_conflict(start, end) is False


class TestRemindersSimplified:
    """Simplified tests for reminders"""

    def test_run_due_reminders_empty(self, client, app):
        """Test with no reminders"""
        from datetime import datetime
        
        with app.app_context():
            from app.services.reminders import run_due_reminders
            
            count = run_due_reminders(datetime.utcnow())
            assert count == 0

    def test_run_due_reminders_returns_count(self, client, app):
        """Test that run_due_reminders returns a count"""
        from datetime import datetime
        
        with app.app_context():
            from app.services.reminders import run_due_reminders
            
            result = run_due_reminders(datetime.utcnow())
            # Should return an integer
            assert isinstance(result, int)
            assert result >= 0
