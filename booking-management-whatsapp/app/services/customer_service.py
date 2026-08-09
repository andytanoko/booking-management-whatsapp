"""
Customer service module - handles all customer-related operations.
Extracted from app.py to improve testability.
"""
import re



from typing import Optional
from app.models import Customer, db


class CustomerService:
    """Service for managing customer operations."""

    @staticmethod
    def normalize_phone(raw: str) -> str:
        """Normalize phone number to 628x format.
        
        Handles formats like:
        - 08123456789 -> 628123456789
        - 628123456789 -> 628123456789
        - +628123456789 -> 628123456789
        - 0812-345-6789 -> 628123456789
        """
        digits = re.sub(r'\D', '', str(raw or ''))
        if not digits:
            return ''
        if digits.startswith('0'):
            digits = '62' + digits[1:]
        return digits

    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Validate phone number is in valid format.
        
        Args:
            phone: Phone number (should already be normalized)
            
        Returns:
            True if valid, False otherwise
        """
        if not phone:
            return False
        # Must start with 628 and have reasonable length (11-15 digits)
        normalized = CustomerService.normalize_phone(phone)
        return normalized.startswith('628') and 11 <= len(normalized) <= 15

    @staticmethod
    def find_or_create(
        phone: Optional[str] = None,
        lid: Optional[str] = None,
        contact_name: Optional[str] = None
    ) -> Optional[Customer]:
        """Find existing customer or create new one.
        
        Priority: phone number > LID
        
        Args:
            phone: WhatsApp phone number
            lid: WhatsApp LID (business account)
            contact_name: Contact name from WhatsApp
            
        Returns:
            Customer object or None if no identifier provided
        """
        real_number = CustomerService.normalize_phone(phone) if phone else None
        
        customer = None
        if real_number:
            customer = Customer.query.filter_by(phone=real_number).first()
        elif lid:
            customer = Customer.query.filter_by(lid=lid).first()
        
        if customer is None:
            # Only create new customer with a real identifier
            if not real_number and not lid:
                return None
























                
            customer = Customer(
                name=contact_name or f"WhatsApp {real_number[-4:] if real_number else 'Customer'}",
                phone=real_number or "",
                lid=lid or None,
                notes="Otomatis dari WhatsApp"
            )
            db.session.add(customer)
            db.session.commit()
            return customer
        
        # Update existing customer
        return CustomerService.update_if_needed(customer, lid, contact_name)

    @staticmethod
    def update_if_needed(
        customer: Customer,
        lid: Optional[str] = None,
        contact_name: Optional[str] = None
    ) -> Customer:
        """Update customer if new information provided.
        
        Args:
            customer: Existing customer
            lid: LID to add if not present
            contact_name: Contact name to update if name is empty/generic
            
        Returns:
            Updated customer
        """
        changed = False
        
        if lid and not customer.lid:
            customer.lid = lid
            changed = True
            
        if contact_name and (
            not customer.name
            or customer.name.startswith('WhatsApp ')
            or customer.name.startswith('Pelanggan ')
        ):
            customer.name = contact_name
            changed = True
        
        if changed:
            db.session.commit()
        
        return customer

    @staticmethod
    def get_or_create_by_phone(phone: str) -> Optional[Customer]:
        """Get customer by phone or create if not exists.
        
        Args:
            phone: Phone number (will be normalized)
            
        Returns:
            Customer object or None if phone invalid
        """
        normalized = CustomerService.normalize_phone(phone)
        if not normalized:
            return None
        











        try:
            customer = Customer.query.filter_by(phone=normalized).first()
            if not customer:
                customer = Customer(
                    name=f"WhatsApp {normalized[-4:]}",
                    phone=normalized,
                    notes="Otomatis dari WhatsApp"
                )
                db.session.add(customer)
                db.session.commit()
            return customer
        except Exception as e:
            current_app.logger.error(f"Error in get_or_create_by_phone: {e}")
            db.session.rollback()
            return None

    @staticmethod
    def update_vehicle_info(customer: Customer, vehicle_info: str) -> Customer:
        """Update customer vehicle information.
        
        Args:
            customer: Customer to update
            vehicle_info: Vehicle info (e.g., "Honda Civic", "B 1234 XYZ")
            
        Returns:
            Updated customer
        """
        if vehicle_info and vehicle_info.strip():
            customer.vehicle_info = vehicle_info.strip()
            db.session.commit()
        return customer

    @staticmethod
    def update_notes(customer: Customer, notes: str, append: bool = True) -> Customer:
        """Update customer notes.
        
        Args:
            customer: Customer to update
            notes: Notes to add/set
            append: If True, append to existing notes; if False, replace
            
        Returns:
            Updated customer
        """
        if notes and notes.strip():
            if append and customer.notes:
                customer.notes = f"{customer.notes}\n{notes}"
            else:
                customer.notes = notes
            db.session.commit()
        return customer

    @staticmethod
    def get_by_phone(phone: str) -> Optional[Customer]:
        """Get customer by phone number.
        
        Args:
            phone: Phone number (will be normalized)
            
        Returns:
            Customer or None if not found
        """
        normalized = CustomerService.normalize_phone(phone)
        if not normalized:
            return None
        return Customer.query.filter_by(phone=normalized).first()

    @staticmethod
    def get_by_id(customer_id: int) -> Optional[Customer]:
        """Get customer by ID.
        
        Args:
            customer_id: Customer ID
            
        Returns:
            Customer or None if not found
        """
        return Customer.query.get(customer_id)

    @staticmethod
    def list_all() -> list:
        """Get all customers.
        
        Returns:
            List of customers
        """
        return Customer.query.all()

    @staticmethod
    def count() -> int:
        """Count total customers.
        
        Returns:
            Number of customers
        """
        return Customer.query.count()


























