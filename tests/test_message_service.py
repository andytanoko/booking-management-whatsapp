"""
Unit tests for message_service.py
Tests message parsing and handling logic in isolation.
"""
import pytest
from datetime import datetime, timedelta
from app.services.message_service import MessageService
from app.models import WhatsAppMessage, db


class TestMessageServiceFormCleaning:
    """Test cleaning form values."""

    def test_remove_bold_markdown(self):
        """Test removing *bold* markdown."""
        result = MessageService.clean_form_value("*Test*")
        assert result == "Test"

    def test_remove_italic_markdown(self):
        """Test removing _italic_ markdown."""
        result = MessageService.clean_form_value("_Test_")
        assert result == "Test"

    def test_remove_code_markdown(self):
        """Test removing `code` markdown."""
        result = MessageService.clean_form_value("`Test`")
        assert result == "Test"

    def test_remove_strikethrough_markdown(self):
        """Test removing ~strikethrough~ markdown."""
        result = MessageService.clean_form_value("~Test~")
        assert result == "Test"

    def test_remove_mixed_markdown(self):
        """Test removing mixed markdown."""
        result = MessageService.clean_form_value("*_`Test`_*")
        assert result == "Test"

    def test_remove_whitespace(self):
        """Test removing leading/trailing whitespace."""
        result = MessageService.clean_form_value("  Test  ")
        assert result == "Test"

    def test_clean_none_value(self):
        """Test cleaning None value."""
        result = MessageService.clean_form_value(None)
        assert result == ""


class TestMessageServiceFormParsing:
    """Test parsing booking forms."""

    def test_parse_simple_form(self):
        """Test parsing simple booking form."""
        form = """Nama: John Doe
No HP: 628123456789
Paket: Coating Premium"""
        result = MessageService.parse_booking_form(form)
        assert result is not None
        assert result["name"] == "John Doe"
        assert result["phone"] == "628123456789"
        assert result["package"] == "Coating Premium"

    def test_parse_form_with_markdown(self):
        """Test parsing form with markdown."""
        form = """Nama: *John Doe*
No HP: `628123456789`
Paket: _Coating Premium_"""
        result = MessageService.parse_booking_form(form)
        assert result is not None
        assert result["name"] == "John Doe"

    def test_parse_form_with_bullets(self):
        """Test parsing form with bullet points."""
        form = """• Nama: John Doe
• No HP: 628123456789
• Paket: Coating Premium"""
        result = MessageService.parse_booking_form(form)
        assert result is not None
        assert result["name"] == "John Doe"

    def test_parse_form_missing_name(self):
        """Test parsing form without name."""
        form = """No HP: 628123456789
Paket: Coating Premium"""
        result = MessageService.parse_booking_form(form)
        assert result is None  # Not a valid form

    def test_parse_form_missing_phone(self):
        """Test parsing form without phone."""
        form = """Nama: John Doe
Paket: Coating Premium"""
        result = MessageService.parse_booking_form(form)
        assert result is None  # Not a valid form

    def test_parse_form_missing_package(self):
        """Test parsing form without package."""
        form = """Nama: John Doe
No HP: 628123456789"""
        result = MessageService.parse_booking_form(form)
        assert result is None  # Not a valid form

    def test_parse_complete_form(self):
        """Test parsing complete booking form."""
        form = """Nama: John Doe
No HP: 628123456789
Merk & Type Mobil: Honda Civic
Nomor Polisi: B 1234 XYZ
Paket: Coating Premium
Domisili: Jakarta Selatan
Tanggal masuk: 15-07-2026"""
        result = MessageService.parse_booking_form(form)
        assert result is not None
        assert "name" in result
        assert "vehicle_type" in result
        assert "license_plate" in result

    def test_parse_form_case_insensitive(self):
        """Test form parsing is case insensitive."""
        form = """NAMA: John Doe
NO HP: 628123456789
PAKET: Coating Premium"""
        result = MessageService.parse_booking_form(form)
        assert result is not None
        assert result["name"] == "John Doe"

    def test_parse_empty_form(self):
        """Test parsing empty form."""
        result = MessageService.parse_booking_form("")
        assert result is None


class TestMessageServiceDateParsing:
    """Test parsing dates."""

    def test_parse_date_ddmmyyyy_dash(self):
        """Test parsing DD-MM-YYYY format."""
        result = MessageService.parse_date("15-07-2026")
        assert result is not None
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 15

    def test_parse_date_ddmmyyyy_slash(self):
        """Test parsing DD/MM/YYYY format."""
        result = MessageService.parse_date("15/07/2026")
        assert result is not None
        assert result.year == 2026

    def test_parse_date_ddmmyyyy_dot(self):
        """Test parsing DD.MM.YYYY format."""
        result = MessageService.parse_date("15.07.2026")
        assert result is not None
        assert result.year == 2026

    def test_parse_date_days_relative(self):
        """Test parsing relative date (days)."""
        now = datetime.now()
        result = MessageService.parse_date("3 hari")
        assert result is not None
        # Should be approximately 3 days from now
        assert (result - now).days >= 2

    def test_parse_date_weeks_relative(self):
        """Test parsing relative date (weeks)."""
        now = datetime.now()
        result = MessageService.parse_date("2 minggu")
        assert result is not None
        # Should be approximately 14 days from now
        assert (result - now).days >= 13

    def test_parse_date_months_relative(self):
        """Test parsing relative date (months)."""
        now = datetime.now()
        result = MessageService.parse_date("1 bulan")
        assert result is not None
        # Should be approximately 30 days from now
        assert (result - now).days >= 29

    def test_parse_invalid_date(self):
        """Test parsing invalid date."""
        result = MessageService.parse_date("invalid")
        assert result is None

    def test_parse_empty_date(self):
        """Test parsing empty date."""
        result = MessageService.parse_date("")
        assert result is None


class TestMessageServicePhoneExtraction:
    """Test extracting phone from forms."""

    def test_extract_valid_phone(self):
        """Test extracting valid phone."""
        fields = {"phone": "628123456789"}
        result = MessageService.extract_phone_from_form(fields)
        assert result == "628123456789"

    def test_extract_phone_08x_format(self):
        """Test extracting 08x format phone."""
        fields = {"phone": "08123456789"}
        result = MessageService.extract_phone_from_form(fields)
        assert result == "628123456789"

    def test_extract_invalid_phone(self):
        """Test extracting invalid phone."""
        fields = {"phone": "abc"}
        result = MessageService.extract_phone_from_form(fields)
        assert result is None

    def test_extract_missing_phone(self):
        """Test extracting missing phone."""
        fields = {}
        result = MessageService.extract_phone_from_form(fields)
        assert result is None


class TestMessageServiceVehicleExtraction:
    """Test extracting vehicle info from forms."""

    def test_extract_vehicle_and_license(self):
        """Test extracting vehicle and license plate."""
        fields = {
            "vehicle_type": "Honda Civic",
            "license_plate": "B 1234 XYZ"
        }
        result = MessageService.extract_vehicle_from_form(fields)
        assert result is not None
        assert "Honda" in result
        assert "1234" in result

    def test_extract_vehicle_only(self):
        """Test extracting vehicle only."""
        fields = {"vehicle_type": "Honda Civic"}
        result = MessageService.extract_vehicle_from_form(fields)
        assert result == "Honda Civic"

    def test_extract_license_only(self):
        """Test extracting license plate only."""
        fields = {"license_plate": "B 1234 XYZ"}
        result = MessageService.extract_vehicle_from_form(fields)
        assert "(B 1234 XYZ)" in result

    def test_extract_no_vehicle(self):
        """Test extracting with no vehicle info."""
        fields = {}
        result = MessageService.extract_vehicle_from_form(fields)
        assert result is None


class TestMessageServiceLogging:
    """Test message logging."""

    def test_log_inbound_message(self, app):
        """Test logging inbound message."""
        with app.app_context():
            result = MessageService.log_message(
                "628123456789",
                "Test message",
                from_me=False
            )
            assert result is not None
            assert result.phone == "628123456789"
            assert result.message_text == "Test message"
            assert result.direction == "inbound"

    def test_log_outbound_message(self, app):
        """Test logging outbound message."""
        with app.app_context():
            result = MessageService.log_message(
                "628123456789",
                "Outbound message",
                from_me=True
            )
            assert result.direction == "outbound"

    def test_log_message_with_timestamp(self, app):
        """Test logging message with timestamp."""
        with app.app_context():
            timestamp = int(datetime.now().timestamp())
            result = MessageService.log_message(
                "628123456789",
                "Test",
                timestamp=timestamp
            )
            # Timestamp should be close to provided value
            assert abs((result.created_at - datetime.fromtimestamp(timestamp)).total_seconds()) < 2

    def test_get_recent_messages(self, app):
        """Test getting recent messages."""
        with app.app_context():
            # Log multiple messages
            for i in range(3):
                MessageService.log_message(f"628{i}111111", f"Message {i}")
            
            # Get recent from one contact
            result = MessageService.get_recent_messages("6280111111", limit=5)
            assert len(result) >= 1

    def test_get_messages_since(self, app):
        """Test getting messages since time."""
        with app.app_context():
            now = datetime.now()
            MessageService.log_message("628123456789", "Recent message")
            
            # Get messages from last hour
            since = now - timedelta(hours=1)
            result = MessageService.get_messages_since("628123456789", since)
            assert len(result) >= 1


class TestMessageServiceChecks:
    """Test various message checks."""

    def test_is_booking_form_true(self):
        """Test recognizing booking form."""
        form = """Nama: John
No HP: 628123456789
Paket: Coating"""
        result = MessageService.is_booking_form(form)
        assert result is True

    def test_is_booking_form_false(self):
        """Test non-booking form."""
        form = "This is just a regular message"
        result = MessageService.is_booking_form(form)
        assert result is False

    def test_is_from_self_true(self):
        """Test detecting outbound message."""
        result = MessageService.is_from_self(True)
        assert result is True

    def test_is_from_self_false(self):
        """Test detecting inbound message."""
        result = MessageService.is_from_self(False)
        assert result is False
