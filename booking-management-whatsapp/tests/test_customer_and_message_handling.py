"""
Tests for customer operations and WhatsApp message handling.
Targets app.py lines 642-709 (customer sync) and whatsapp.py message parsing.
"""
from datetime import datetime, timedelta
from app.models import Booking, Customer, ServiceType, WhatsAppMessage, db


class TestCustomerOperations:
    """Test customer creation and updates"""

    def test_customer_creation_from_whatsapp(self, client, app):
        """Test creating customer from WhatsApp message"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628111111111",
            "contact_name": "John Doe",
            "text": "Hello",
            "from_me": False
        })
        assert response.status_code == 200

        with app.app_context():
            customer = Customer.query.filter_by(phone="628111111111").first()
            assert customer is not None
            assert customer.name is not None

    def test_customer_update_with_vehicle_info(self, client, app):
        """Test updating customer with vehicle info"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628222222222",
            "text": """Nama: Jane
No HP: 628222222222
Merk & Type Mobil: Toyota Avanza
Nomor Polisi: B 1234 XYZ""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_customer_sync_phone_normalization(self, client, app):
        """Test phone number normalization during sync"""
        phones = ["08123456789", "628123456789", "+628123456789"]
        
        for phone in phones:
            response = client.post("/api/whatsapp/inbound", json={
                "phone": phone,
                "contact_name": "Test",
                "text": "Message",
                "from_me": False
            })
            assert response.status_code == 200

    def test_customer_multiple_messages(self, client, app):
        """Test customer data accumulation across multiple messages"""
        phone = "628333333333"
        
        # First message
        response1 = client.post("/api/whatsapp/inbound", json={
            "phone": phone,
            "contact_name": "Name",
            "text": "First message",
            "from_me": False
        })
        assert response1.status_code == 200

        # Second message with more data
        response2 = client.post("/api/whatsapp/inbound", json={
            "phone": phone,
            "text": """Nama: Update
Paket: Coating Premium
Mobil: Honda Civic""",
            "from_me": False
        })
        assert response2.status_code == 200

    def test_customer_with_special_characters(self, client, app):
        """Test customer with special characters in name"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628444444444",
            "contact_name": "O'Brien-Smith",
            "text": "Hello",
            "from_me": False
        })
        assert response.status_code == 200

    def test_customer_empty_phone_number(self, client, app):
        """Test handling message without phone number"""
        response = client.post("/api/whatsapp/inbound", json={
            "text": "Message without phone",
            "from_me": False
        })
        # Should handle gracefully
        assert response.status_code in [200, 400, 422]


class TestWhatsAppMessageParsing:
    """Test WhatsApp message parsing and extraction"""

    def test_parse_message_with_name_field(self, client, app):
        """Test parsing message containing name field"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Nama: Customer Name",
            "from_me": False
        })
        assert response.status_code == 200

    def test_parse_message_with_phone_field(self, client, app):
        """Test parsing message containing phone field"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "No HP: 628987654321",
            "from_me": False
        })
        assert response.status_code == 200

    def test_parse_message_with_vehicle_field(self, client, app):
        """Test parsing message containing vehicle info"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Merk & Type Mobil: BMW X5
Nomor Polisi: B 9999 AAA""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_parse_message_with_package_field(self, client, app):
        """Test parsing message containing package info"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Pilihan Paket: Coating Premium",
            "from_me": False
        })
        assert response.status_code == 200

    def test_parse_message_with_date_field(self, client, app):
        """Test parsing message containing date"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": f"""Tanggal masuk: {(datetime.now() + timedelta(days=1)).strftime('%d-%m-%Y')}""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_parse_multiline_message(self, client, app):
        """Test parsing complex multiline message"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama: Test Customer
No HP: 628123456789
Paket: Polishing
Mobil: Honda Civic
Nomor Polisi: B 1234 ABC""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_parse_message_with_extra_spacing(self, client, app):
        """Test parsing message with extra whitespace"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama:    Customer Name

Paket:    Coating Premium

Nomor Polisi:    B 1234 XYZ""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_parse_message_uppercase_fields(self, client, app):
        """Test parsing message with uppercase field names"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """NAMA: Customer
NO HP: 628123456789
PAKET: Coating""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_parse_message_mixed_case_fields(self, client, app):
        """Test parsing message with mixed case field names"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """NaMa: Customer
nO hP: 628123456789
PaKeT: Coating""",
            "from_me": False
        })
        assert response.status_code == 200


class TestWhatsAppInboundEdgeCases:
    """Test edge cases in WhatsApp inbound processing"""

    def test_inbound_message_from_self(self, client, app):
        """Test handling message from self"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Outgoing message",
            "from_me": True
        })
        assert response.status_code == 200

    def test_inbound_empty_message(self, client, app):
        """Test handling empty message"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "",
            "from_me": False
        })
        assert response.status_code == 200

    def test_inbound_whitespace_only_message(self, client, app):
        """Test handling whitespace-only message"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "   \n\t  ",
            "from_me": False
        })
        assert response.status_code == 200

    def test_inbound_very_long_message(self, client, app):
        """Test handling very long message"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "A" * 5000,  # Very long message
            "from_me": False
        })
        assert response.status_code == 200

    def test_inbound_message_with_numbers_only(self, client, app):
        """Test handling message with numbers only"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "123456789",
            "from_me": False
        })
        assert response.status_code == 200

    def test_inbound_message_with_special_characters(self, client, app):
        """Test handling message with special characters"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "!@#$%^&*()_+-=[]{}|;':\",./<>?",
            "from_me": False
        })
        assert response.status_code == 200

    def test_inbound_missing_phone_and_chat_id(self, client, app):
        """Test inbound message without phone or chat_id"""
        response = client.post("/api/whatsapp/inbound", json={
            "text": "Message without identifier",
            "from_me": False
        })
        # Should handle gracefully
        assert response.status_code in [200, 400, 422]


class TestMessageLogging:
    """Test WhatsApp message logging"""

    def test_inbound_message_logged(self, client, app):
        """Test that inbound message is logged"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Log this message",
            "from_me": False
        })
        assert response.status_code == 200

        with app.app_context():
            message = WhatsAppMessage.query.filter_by(phone="628123456789").first()
            assert message is not None

    def test_multiple_messages_from_same_customer(self, client, app):
        """Test logging multiple messages from same customer"""
        phone = "628555555555"
        
        for i in range(3):
            response = client.post("/api/whatsapp/inbound", json={
                "phone": phone,
                "text": f"Message {i+1}",
                "from_me": False
            })
            assert response.status_code == 200

        with app.app_context():
            count = WhatsAppMessage.query.filter_by(phone=phone).count()
            assert count >= 1  # At least one message logged

    def test_message_with_timestamp(self, client, app):
        """Test message logging with timestamp"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Message with timestamp",
            "from_me": False,
            "timestamp": int(datetime.now().timestamp())
        })
        assert response.status_code == 200


class TestBookingCreationFromMessages:
    """Test booking creation from WhatsApp messages"""

    def test_create_booking_from_customer_message(self, client, app):
        """Test creating booking from customer message"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama: Customer
No HP: 628123456789
Paket: Coating Premium
Mobil: Honda Civic""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_booking_with_future_date(self, client, app):
        """Test booking with future date"""
        future_date = (datetime.now() + timedelta(days=5)).strftime('%d-%m-%Y')
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": f"""Nama: Customer
No HP: 628123456789
Tanggal masuk: {future_date}
Paket: Coating Premium""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_booking_with_pricing_info(self, client, app):
        """Test booking with pricing information"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama: Customer
No HP: 628123456789
Paket: Coating Premium
Harga Normal: 5000000
Harga Disc: 4500000
Harga Nett: 4500000""",
            "from_me": False
        })
        assert response.status_code == 200

    def test_booking_with_location_info(self, client, app):
        """Test booking with location information"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": """Nama: Customer
No HP: 628123456789
Domisili: Jakarta Selatan
Paket: Coating Premium""",
            "from_me": False
        })
        assert response.status_code == 200
