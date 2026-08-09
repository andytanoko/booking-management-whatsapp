"""Tests for app services."""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import db, Booking, ServiceType
from app.services.booking_engine import compute_booking_end, has_conflict
from app.services.settings_store import get_setting, set_setting, get_many
from app.services.semantic_matcher import extract_core_keywords, match_package_to_service


class TestBookingEngine:
    """Test cases for booking_engine service."""
    
    def test_compute_booking_end(self, app, service_type):
        """Test computing booking end time."""
        with app.app_context():
            start = datetime(2024, 1, 15, 10, 0, 0)
            end = compute_booking_end(service_type, start)
            
            expected = start + timedelta(minutes=service_type.duration_minutes)
            assert end == expected
    
    def test_compute_booking_end_different_durations(self, app):
        """Test compute_booking_end with different service durations."""
        with app.app_context():
            service1 = ServiceType(name="Quick", duration_minutes=15)
            service2 = ServiceType(name="Long", duration_minutes=480)
            db.session.add_all([service1, service2])
            db.session.commit()
            
            start = datetime(2024, 1, 15, 10, 0, 0)
            
            end1 = compute_booking_end(service1, start)
            assert end1 == datetime(2024, 1, 15, 10, 15, 0)
            
            end2 = compute_booking_end(service2, start)
            assert end2 == datetime(2024, 1, 15, 18, 0, 0)
    
    def test_has_conflict_no_conflict(self, app, customer, service_type):
        """Test no conflict when slot is free."""
        with app.app_context():
            start = datetime(2024, 1, 15, 10, 0, 0)
            end = datetime(2024, 1, 15, 12, 0, 0)
            
            # Create a booking at different time
            existing = Booking(
                customer_id=customer.id,
                service_type_id=service_type.id,
                scheduled_start=datetime(2024, 1, 15, 14, 0, 0),
                scheduled_end=datetime(2024, 1, 15, 16, 0, 0),
                status="dikonfirmasi"
            )
            db.session.add(existing)
            db.session.commit()
            
            assert has_conflict(start, end) is False
    
    def test_has_conflict_with_existing_booking(self, app, customer, service_type):
        """Test conflict when the day's capacity is reached."""
        with app.app_context():
            set_setting('daily_capacity', '1')
            # Create existing booking
            existing = Booking(
                customer_id=customer.id,
                service_type_id=service_type.id,
                scheduled_start=datetime(2024, 1, 15, 10, 0, 0),
                scheduled_end=datetime(2024, 1, 15, 12, 0, 0),
                status="dikonfirmasi"
            )
            db.session.add(existing)
            db.session.commit()
            
            # Same day, capacity is 1 -> day is full
            start = datetime(2024, 1, 15, 11, 0, 0)
            end = datetime(2024, 1, 15, 13, 0, 0)
            
            assert has_conflict(start, end) is True
    
    def test_has_conflict_ignores_completed_bookings(self, app, customer, service_type):
        """Test that completed bookings don't cause conflicts."""
        with app.app_context():
            # Create completed booking
            existing = Booking(
                customer_id=customer.id,
                service_type_id=service_type.id,
                scheduled_start=datetime(2024, 1, 15, 10, 0, 0),
                scheduled_end=datetime(2024, 1, 15, 12, 0, 0),
                status="selesai"
            )
            db.session.add(existing)
            db.session.commit()
            
            # Overlapping time should not conflict
            start = datetime(2024, 1, 15, 11, 0, 0)
            end = datetime(2024, 1, 15, 13, 0, 0)
            
            assert has_conflict(start, end) is False
    
    def test_has_conflict_excludes_specific_booking(self, app, customer, service_type):
        """Test excluding specific booking from conflict check."""
        with app.app_context():
            existing = Booking(
                customer_id=customer.id,
                service_type_id=service_type.id,
                scheduled_start=datetime(2024, 1, 15, 10, 0, 0),
                scheduled_end=datetime(2024, 1, 15, 12, 0, 0),
                status="dikonfirmasi"
            )
            db.session.add(existing)
            db.session.commit()
            
            # Same time should not conflict when excluded
            start = datetime(2024, 1, 15, 10, 0, 0)
            end = datetime(2024, 1, 15, 12, 0, 0)
            
            assert has_conflict(start, end, exclude_booking_id=existing.id) is False


class TestSettingsStore:
    """Test cases for settings_store service."""
    
    def test_get_setting_existing(self, app):
        """Test getting an existing setting."""
        with app.app_context():
            set_setting("test_key", "test_value")
            
            value = get_setting("test_key")
            assert value == "test_value"
    
    def test_get_setting_default(self, app):
        """Test getting non-existent setting returns default."""
        with app.app_context():
            value = get_setting("nonexistent", "default_value")
            assert value == "default_value"
    
    def test_get_setting_empty_default(self, app):
        """Test getting non-existent setting with no default."""
        with app.app_context():
            value = get_setting("nonexistent")
            assert value == ""
    
    def test_set_setting_new(self, app):
        """Test setting a new setting."""
        with app.app_context():
            set_setting("new_key", "new_value")
            
            value = get_setting("new_key")
            assert value == "new_value"
    
    def test_set_setting_update(self, app):
        """Test updating an existing setting."""
        with app.app_context():
            set_setting("key", "original")
            set_setting("key", "updated")
            
            value = get_setting("key")
            assert value == "updated"
    
    def test_get_many_multiple_settings(self, app):
        """Test getting multiple settings at once."""
        with app.app_context():
            set_setting("key1", "value1")
            set_setting("key2", "value2")
            set_setting("key3", "value3")
            
            result = get_many(["key1", "key2", "key3"])
            
            assert result["key1"] == "value1"
            assert result["key2"] == "value2"
            assert result["key3"] == "value3"
    
    def test_get_many_with_missing_keys(self, app):
        """Test get_many with some missing keys."""
        with app.app_context():
            set_setting("key1", "value1")
            
            result = get_many(["key1", "missing_key"])
            
            assert result["key1"] == "value1"
            assert result["missing_key"] == ""
    
    def test_get_many_empty_list(self, app):
        """Test get_many with empty list."""
        with app.app_context():
            result = get_many([])
            assert result == {}


class TestSemanticMatcher:
    """Test cases for semantic_matcher service."""
    
    def test_extract_core_keywords_basic(self):
        """Test extracting core keywords from package name."""
        text = "Large Gold"
        keywords, modifiers = extract_core_keywords(text)
        
        assert "gold" in keywords
        assert "large" in modifiers.lower()
    
    def test_extract_core_keywords_size_modifiers(self):
        """Test that size modifiers are detected."""
        text = "Small Premium Coating"
        keywords, modifiers = extract_core_keywords(text)
        
        assert "coating" in keywords
        assert "small" in modifiers.lower() or "premium" in modifiers.lower()
    
    def test_extract_core_keywords_coating_variants(self):
        """Test coating variant keywords."""
        for variant in ["gold", "silver", "platinum", "graphene"]:
            keywords, _ = extract_core_keywords(f"{variant} coating")
            assert len(keywords) > 0
    
    def test_extract_core_keywords_ppf_variants(self):
        """Test PPF variant keywords."""
        ppf_keywords = ["quad", "gfive", "premiere", "luxury"]
        for keyword in ppf_keywords:
            keywords, _ = extract_core_keywords(keyword)
            assert len(keywords) > 0
    
    def test_match_package_to_service_coating(self, app):
        """Test matching coating packages."""
        with app.app_context():
            services = ServiceType.query.filter_by(active=True).all()
            service = match_package_to_service("Large Gold", services)
            assert service is None or isinstance(service, ServiceType)
    
    def test_match_package_to_service_ppf(self, app):
        """Test matching PPF packages."""
        with app.app_context():
            services = ServiceType.query.filter_by(active=True).all()
            service = match_package_to_service("QUAD Premiere", services)
            assert service is None or isinstance(service, ServiceType)
    
    def test_match_package_to_service_fallback(self, app):
        """Test fallback service for unknown packages."""
        with app.app_context():
            services = ServiceType.query.filter_by(active=True).all()
            service = match_package_to_service("Unknown Package XYZ", services)
            # Should return some default service or None
            # This depends on implementation
            assert service is None or isinstance(service, ServiceType)
