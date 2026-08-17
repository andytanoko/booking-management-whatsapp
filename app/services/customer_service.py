"""
Customer service module - handles all customer-related operations.
Extracted from app.py to improve testability.
"""
import re



from typing import Optional
from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.models import Customer, db
from app.services.db_ops import safe_commit


class CustomerService:
    """Service for managing customer operations."""

    @staticmethod
    def is_placeholder_name(name: Optional[str]) -> bool:
        """True when a name is empty or an auto-generated WhatsApp placeholder."""
        n = (name or '').strip()
        return not n or n.startswith('WhatsApp ') or n.startswith('Pelanggan ')

    @staticmethod
    def sync_from_whatsapp(
        number: Optional[str] = None,
        lid: Optional[str] = None,
        contact_name: Optional[str] = None,
        notes: str = 'Sinkron dari WhatsApp',
    ) -> tuple[Optional[Customer], str]:
        """Find-or-create/update a customer from a WhatsApp-sourced contact.

        Single source of truth for both the contact-sync button and the inbound
        webhook. Matching order: LID first, then phone. A record is created only
        when a real name is supplied (never fabricate a placeholder); existing
        records get phone (when free of clashes), LID, and placeholder names
        backfilled. Adds/flushes but does not commit — the caller owns the
        transaction and commit.

        Returns (customer_or_None, status) where status is one of
        'created', 'updated', 'unchanged', 'skipped'.
        """
        number = str(number or '').strip()
        lid = str(lid or '').strip()
        contact_name = str(contact_name or '').strip()
        number_ok = number.isdigit() and 8 <= len(number) <= 15
        lid_ok = lid.isdigit() and 8 <= len(lid) <= 20
        if not number_ok and not lid_ok:
            return None, 'skipped'

        customer = Customer.query.filter_by(lid=lid).first() if lid_ok else None
        if customer is None and number_ok:
            customer = Customer.query.filter_by(phone=number).first()

        if customer is None:
            if not contact_name:
                return None, 'skipped'
            phone_val = number if number_ok else lid
            customer = Customer(
                name=contact_name,
                phone=phone_val,
                lid=lid if lid_ok else None,
                notes=notes,
            )
            db.session.add(customer)
            try:
                db.session.flush()
            except IntegrityError:
                db.session.rollback()
                return None, 'skipped'
            return customer, 'created'

        changed = False
        if number_ok and customer.phone != number:
            clash = Customer.query.filter(Customer.phone == number, Customer.id != customer.id).first()
            if clash is None:
                customer.phone = number
                changed = True
        if lid_ok and not customer.lid:
            customer.lid = lid
            changed = True
        if contact_name and CustomerService.is_placeholder_name(customer.name):
            customer.name = contact_name
            changed = True
        return customer, ('updated' if changed else 'unchanged')

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
            # Only create a customer when we have an identifier AND a real name.
            # Unnamed contacts must not pollute the customer table.
            if not real_number and not lid:
                return None
            if not contact_name:
                return None
            customer = Customer(
                name=contact_name,
                phone=real_number or "",
                lid=lid or None,
                notes="Otomatis dari WhatsApp"
            )
            db.session.add(customer)
            if not safe_commit("customer find_or_create insert"):
                return None
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
            
        if contact_name and CustomerService.is_placeholder_name(customer.name):
            customer.name = contact_name
            changed = True
        
        if changed:
            safe_commit("customer update_if_needed")
        
        return customer

    @staticmethod
    def get_or_create_by_phone(phone: str) -> Optional[Customer]:
        """Get customer by phone. Does not create placeholder-named records.

        Args:
            phone: Phone number (will be normalized)

        Returns:
            Existing customer, or None if phone invalid or not found
        """
        normalized = CustomerService.normalize_phone(phone)
        if not normalized:
            return None
        try:
            # Never fabricate a placeholder name: return the existing customer or
            # None. Callers that need to create must supply a real name via
            # find_or_create(contact_name=...).
            return Customer.query.filter_by(phone=normalized).first()
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
            safe_commit("customer update_vehicle_info")
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
            safe_commit("customer update_notes")
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
        return db.session.get(Customer, customer_id)

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


























