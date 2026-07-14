"""
Unit tests for customer_service.py
Tests customer operations in isolation without Flask/database side effects.
"""
import pytest
from app.services.customer_service import CustomerService
from app.models import Customer, db


class TestCustomerServicePhoneNormalization:
    """Test phone number normalization."""

    def test_normalize_08x_format(self):
        """Test normalizing 08x format to 628x."""
        result = CustomerService.normalize_phone("08123456789")
        assert result == "628123456789"

    def test_normalize_628x_format(self):
        """Test 628x format unchanged."""
        result = CustomerService.normalize_phone("628123456789")
        assert result == "628123456789"

    def test_normalize_with_plus_sign(self):
        """Test normalizing +628x format."""
        result = CustomerService.normalize_phone("+628123456789")
        assert result == "628123456789"

    def test_normalize_with_spaces(self):
        """Test normalizing phone with spaces."""
        result = CustomerService.normalize_phone("0812 345 6789")
        assert result == "628123456789"

    def test_normalize_with_dashes(self):
        """Test normalizing phone with dashes."""
        result = CustomerService.normalize_phone("0812-345-6789")
        assert result == "628123456789"

    def test_normalize_with_parens(self):
        """Test normalizing phone with parentheses."""
        result = CustomerService.normalize_phone("(0812) 345-6789")
        assert result == "628123456789"

    def test_normalize_empty_string(self):
        """Test normalizing empty string."""
        result = CustomerService.normalize_phone("")
        assert result == ""

    def test_normalize_non_numeric(self):
        """Test normalizing non-numeric string."""
        result = CustomerService.normalize_phone("abc")
        assert result == ""


class TestCustomerServiceValidation:
    """Test phone validation."""

    def test_validate_valid_628x(self):
        """Test valid 628x format."""
        assert CustomerService.validate_phone("628123456789") is True

    def test_validate_valid_08x(self):
        """Test valid 08x format (will be normalized)."""
        assert CustomerService.validate_phone("08123456789") is True

    def test_validate_too_short(self):
        """Test phone too short."""
        assert CustomerService.validate_phone("62812") is False

    def test_validate_too_long(self):
        """Test phone too long."""
        assert CustomerService.validate_phone("628123456789012345") is False

    def test_validate_empty(self):
        """Test empty phone."""
        assert CustomerService.validate_phone("") is False

    def test_validate_invalid_prefix(self):
        """Test invalid country prefix."""
        assert CustomerService.validate_phone("123456789") is False


class TestCustomerServiceFindOrCreate:
    """Test finding and creating customers."""

    def test_find_existing_by_phone(self, app):
        """Test finding existing customer by phone."""
        with app.app_context():
            # Create customer
            customer = Customer(name="Test", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            # Find customer
            result = CustomerService.find_or_create(phone="628111111111")
            assert result is not None
            assert result.name == "Test"
            assert result.phone == "628111111111"

    def test_create_new_customer(self, app):
        """Test creating new customer."""
        with app.app_context():
            result = CustomerService.find_or_create(
                phone="628222222222",
                contact_name="New Customer"
            )
            assert result is not None
            assert result.phone == "628222222222"
            assert result.name == "New Customer"

    def test_find_with_normalized_phone(self, app):
        """Test finding with non-normalized phone."""
        with app.app_context():
            # Create customer with normalized phone
            customer = Customer(name="Test", phone="628333333333")
            db.session.add(customer)
            db.session.commit()
            
            # Find with non-normalized phone
            result = CustomerService.find_or_create(phone="08333333333")
            assert result is not None
            assert result.id == customer.id

    def test_create_with_lid(self, app):
        """Test creating customer with LID."""
        with app.app_context():
            import uuid
            unique_lid = f"{uuid.uuid4().hex}@lid"
            result = CustomerService.find_or_create(
                lid=unique_lid,
                contact_name="LID Customer"
            )
            assert result is not None
            assert result.lid == unique_lid

    def test_find_no_identifier(self, app):
        """Test find/create with no identifier."""
        with app.app_context():
            result = CustomerService.find_or_create()
            assert result is None


class TestCustomerServiceUpdate:
    """Test updating customer information."""

    def test_update_empty_name(self, app):
        """Test updating empty customer name."""
        with app.app_context():
            customer = Customer(name="", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.update_if_needed(
                customer,
                contact_name="New Name"
            )
            assert result.name == "New Name"

    def test_update_generic_name(self, app):
        """Test updating generic customer name."""
        with app.app_context():
            customer = Customer(name="WhatsApp 1111", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.update_if_needed(
                customer,
                contact_name="Real Name"
            )
            assert result.name == "Real Name"

    def test_preserve_real_name(self, app):
        """Test preserving real customer name."""
        with app.app_context():
            customer = Customer(name="Real Name", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.update_if_needed(
                customer,
                contact_name="New Name"
            )
            assert result.name == "Real Name"  # Should not change

    def test_add_lid(self, app):
        """Test adding LID to existing customer."""
        with app.app_context():
            customer = Customer(name="Test", phone="628111111111", lid=None)
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.update_if_needed(
                customer,
                lid="12345@lid"
            )
            assert result.lid == "12345@lid"


class TestCustomerServiceGetMethods:
    """Test retrieving customer information."""

    def test_get_by_phone(self, app):
        """Test getting customer by phone."""
        with app.app_context():
            customer = Customer(name="Test", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.get_by_phone("628111111111")
            assert result is not None
            assert result.id == customer.id

    def test_get_by_phone_not_found(self, app):
        """Test getting customer by phone when not exists."""
        with app.app_context():
            result = CustomerService.get_by_phone("628999999999")
            assert result is None

    def test_get_by_id(self, app):
        """Test getting customer by ID."""
        with app.app_context():
            customer = Customer(name="Test", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.get_by_id(customer.id)
            assert result is not None
            assert result.name == "Test"

    def test_get_by_id_not_found(self, app):
        """Test getting customer by invalid ID."""
        with app.app_context():
            result = CustomerService.get_by_id(99999)
            assert result is None

    def test_list_all(self, app):
        """Test listing all customers."""
        with app.app_context():
            # Create multiple customers
            for i in range(3):
                customer = Customer(name=f"Customer {i}", phone=f"62811111111{i}")
                db.session.add(customer)
            db.session.commit()
            
            results = CustomerService.list_all()
            assert len(results) >= 3

    def test_count(self, app):
        """Test counting customers."""
        with app.app_context():
            initial = CustomerService.count()
            
            customer = Customer(name="Test", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            final = CustomerService.count()
            assert final == initial + 1


class TestCustomerServiceVehicleInfo:
    """Test updating vehicle information."""

    def test_update_vehicle_info(self, app):
        """Test updating vehicle info."""
        with app.app_context():
            customer = Customer(name="Test", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.update_vehicle_info(customer, "Honda Civic")
            assert result.vehicle_info == "Honda Civic"

    def test_update_vehicle_with_license(self, app):
        """Test updating vehicle with license plate."""
        with app.app_context():
            customer = Customer(name="Test", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.update_vehicle_info(
                customer,
                "Toyota Avanza (B 1234 XYZ)"
            )
            assert "Toyota" in result.vehicle_info


class TestCustomerServiceNotes:
    """Test updating customer notes."""

    def test_update_notes_new(self, app):
        """Test adding notes to customer without notes."""
        with app.app_context():
            customer = Customer(name="Test", phone="628111111111")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.update_notes(customer, "New note")
            assert "New note" in result.notes

    def test_append_notes(self, app):
        """Test appending notes."""
        with app.app_context():
            customer = Customer(name="Test", phone="628111111111", notes="Old note")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.update_notes(customer, "New note", append=True)
            assert "Old note" in result.notes
            assert "New note" in result.notes

    def test_replace_notes(self, app):
        """Test replacing notes."""
        with app.app_context():
            customer = Customer(name="Test", phone="628111111111", notes="Old note")
            db.session.add(customer)
            db.session.commit()
            
            result = CustomerService.update_notes(customer, "New note", append=False)
            assert result.notes == "New note"
            assert "Old note" not in result.notes

    def test_update_notes_empty_noop(self, app):
        """Empty notes leave the customer unchanged."""
        with app.app_context():
            customer = Customer(name="Test", phone="628111111111", notes="Old note")
            db.session.add(customer)
            db.session.commit()

            result = CustomerService.update_notes(customer, "   ")
            assert result.notes == "Old note"


class TestCustomerServiceGetOrCreateByPhone:
    """Test get_or_create_by_phone."""

    def test_invalid_phone_returns_none(self, app):
        """Non-numeric phone normalizes to empty and returns None."""
        with app.app_context():
            assert CustomerService.get_or_create_by_phone("abc") is None

    def test_creates_new_customer(self, app):
        """A new customer is created when none exists for the phone."""
        with app.app_context():
            result = CustomerService.get_or_create_by_phone("08123456789")
            assert result is not None
            assert result.phone == "628123456789"
            assert result.id is not None

    def test_returns_existing_customer(self, app):
        """An existing customer is returned without creating a duplicate."""
        with app.app_context():
            existing = Customer(name="Existing", phone="628123456789")
            db.session.add(existing)
            db.session.commit()

            result = CustomerService.get_or_create_by_phone("08123456789")
            assert result.id == existing.id
            assert Customer.query.filter_by(phone="628123456789").count() == 1

    def test_get_by_phone_invalid_returns_none(self, app):
        """get_by_phone with an unnormalizable phone returns None."""
        with app.app_context():
            assert CustomerService.get_by_phone("abc") is None


class TestCustomerServiceVehicleInfoNoop:
    """Test update_vehicle_info no-op path."""

    def test_update_vehicle_info_empty_noop(self, app):
        """Empty vehicle info leaves the customer unchanged."""
        with app.app_context():
            customer = Customer(
                name="Test", phone="628111111111", vehicle_info="Honda Civic"
            )
            db.session.add(customer)
            db.session.commit()

            result = CustomerService.update_vehicle_info(customer, "   ")
            assert result.vehicle_info == "Honda Civic"
