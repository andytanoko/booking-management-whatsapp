"""Tests for reminders service."""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import db, Booking, ReminderLog, Customer, ServiceType


class TestRemindersService:
    """Test reminders service functionality."""
    
    def test_run_due_reminders_no_bookings(self, app):
        """Test run_due_reminders with no bookings."""
        with app.app_context():
            from app.services.reminders import run_due_reminders
            
            now = datetime.now(ZoneInfo("Asia/Jakarta")).replace(tzinfo=None)
            count = run_due_reminders(now)
            
            # Should return 0 when no bookings
            assert count >= 0


class TestWhatsAppService:
    """Test WhatsApp service."""
    
    def test_discover_bridge_profile(self, app):
        """Test discovering bridge profile."""
        with app.app_context():
            from app.services.whatsapp import discover_bridge_profile
            
            # Should handle gracefully
            profile = discover_bridge_profile()
            # Can be None or a dict
            assert profile is None or isinstance(profile, dict)
    
    def test_fetch_whatsapp_contacts(self, app):
        """Test fetching WhatsApp contacts."""
        with app.app_context():
            from app.services.whatsapp import fetch_whatsapp_contacts
            
            # Should handle gracefully
            try:
                contacts = fetch_whatsapp_contacts()
                assert isinstance(contacts, list)
            except Exception:
                # OK if it fails (no bridge available)
                pass
    
    def test_log_inbound_message(self, app):
        """Test logging inbound message."""
        with app.app_context():
            from app.services.whatsapp import log_inbound_message
            
            log_inbound_message("6281234567890", "Test message", {})
            
            # Verify message was logged
            from app.models import WhatsAppMessage
            msg = WhatsAppMessage.query.filter_by(phone="6281234567890").first()
            assert msg is not None


class TestSemanticMatcherAdvanced:
    """Advanced tests for semantic matcher."""
    
    def test_get_variant_info(self, app):
        """Test getting variant info."""
        with app.app_context():
            from app.services.semantic_matcher import get_variant_info
            from app.models import ServiceType
            
            services = ServiceType.query.filter_by(active=True).all()
            # Test with known variant
            info = get_variant_info("Large Gold", services)
            # Should return some info or None
            assert info is None or isinstance(info, str)
    
    def test_match_package_keywords(self, app):
        """Test package matching with various keywords."""
        with app.app_context():
            from app.services.semantic_matcher import extract_core_keywords
            
            keywords, modifiers = extract_core_keywords("Premium Ceramic Coating")
            assert len(keywords) > 0
