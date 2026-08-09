"""
Message service module - handles message parsing and WhatsApp operations.
Extracted from app.py to improve testability.
"""
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from flask import current_app
from app.models import WhatsAppMessage, db


# Labels recognised in booking forms (normalized -> field)
BOOKING_FORM_LABELS = {
    "nama": "name",
    "no hp": "phone",
    "nohp": "phone",
    "no. hp": "phone",
    "nomor hp": "phone",
    "no telp": "phone",
    "no. telp": "phone",
    "no wa": "phone",
    "no. wa": "phone",
    "merk & type mobil": "vehicle_type",
    "merk type mobil": "vehicle_type",
    "merk dan type mobil": "vehicle_type",
    "merk & tipe mobil": "vehicle_type",
    "jenis kendaraan": "vehicle_type",
    "mobil": "vehicle_type",
    "nomor polisi": "license_plate",
    "nopol": "license_plate",
    "no. polisi": "license_plate",
    "plat": "license_plate",
    "pilihan paket": "package",
    "paket": "package",
    "domisili": "domicile",
    "tanggal masuk mobil": "schedule_text",
    "tanggal masuk": "schedule_text",
    "tanggal": "schedule_text",
    "outlet": "outlet",
    "data from": "data_from",
    "sumber": "data_from",
    "harga normal": "price_normal",
    "harga disc": "price_disc",
    "harga discount": "price_disc",
    "harga nett": "price_nett",
    "harga net": "price_nett",
}


class MessageService:
    """Service for message parsing and WhatsApp operations."""

    @staticmethod
    def clean_form_value(value: str) -> str:
        """Remove WhatsApp markdown emphasis (_ * ` ~) and whitespace.
        
        Args:
            value: Value with possible markdown
            
        Returns:
            Cleaned value
        """
        return re.sub(r'[_*`~]', '', str(value or '')).strip()

    @staticmethod
    def parse_booking_form(text: str) -> Optional[Dict[str, str]]:
        """Parse structured WhatsApp booking form into fields.
        
        Args:
            text: Text content of message
            
        Returns:
            Dict of parsed fields, or None if not a valid booking form
        """
        fields: Dict[str, str] = {}
        
        for raw_line in str(text or '').splitlines():
            line = raw_line.strip().lstrip('-•*').strip()
            if ':' not in line:
                continue
            
            label, _, value = line.partition(':')
            key = re.sub(r'[^a-z0-9& ]', '', label.strip().lower())
            key = re.sub(r'\s+', ' ', key).strip()
            
            mapped = BOOKING_FORM_LABELS.get(key)
            if mapped and mapped not in fields:
                fields[mapped] = MessageService.clean_form_value(value)
        
        # Valid booking form must have name, phone, and package
        has_name = 'name' in fields and fields['name']
        has_phone = 'phone' in fields and fields['phone']
        has_package = 'package' in fields and fields['package']
        
        if not (has_name and has_phone and has_package):
            return None
        
        return fields

    @staticmethod
    def parse_date(date_text: str) -> Optional[datetime]:
        """Parse date from various formats.
        
        Handles:
        - DD-MM-YYYY
        - DD/MM/YYYY
        - DD.MM.YYYY
        - Relative: "2 minggu", "3 hari", "1 bulan"
        
        Args:
            date_text: Date text to parse
            
        Returns:
            Parsed datetime or None if invalid
        """
        date_text = str(date_text or '').strip()
        if not date_text:
            return None
        
        # Try relative dates first
        relative_match = re.match(r'(\d+)\s*(hari|minggu|bulan)', date_text.lower())
        if relative_match:
            amount = int(relative_match.group(1))
            unit = relative_match.group(2)
            now = datetime.now()
            
            if unit == 'hari':
                return now + timedelta(days=amount)
            elif unit == 'minggu':
                return now + timedelta(weeks=amount)
            else:  # bulan
                # Approximate: 30 days per month
                return now + timedelta(days=amount * 30)
        
        # Try fixed date formats
        for fmt in ['%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y', '%d-%m-%y', '%d/%m/%y']:
            try:
                parsed = datetime.strptime(date_text, fmt)
                # Set to noon to avoid timezone issues
                return parsed.replace(hour=12, minute=0, second=0)
            except ValueError:
                continue
        
        return None

    @staticmethod
    def extract_phone_from_form(fields: Dict[str, str]) -> Optional[str]:
        """Extract phone number from parsed form fields.
        
        Args:
            fields: Parsed form fields
            
        Returns:
            Normalized phone number or None
        """
        phone = fields.get('phone', '').strip()
        if not phone:
            return None
        
        # Normalize the phone
        from app.services.customer_service import CustomerService
        normalized = CustomerService.normalize_phone(phone)
        
        if CustomerService.validate_phone(normalized):
            return normalized
        return None

    @staticmethod
    def extract_vehicle_from_form(fields: Dict[str, str]) -> Optional[str]:
        """Extract vehicle info from parsed form fields.
        
        Args:
            fields: Parsed form fields
            
        Returns:
            Vehicle info string or None
        """
        vehicle_type = fields.get('vehicle_type', '').strip()
        license_plate = fields.get('license_plate', '').strip()
        
        if vehicle_type and license_plate:
            return f"{vehicle_type} ({license_plate})"
        elif vehicle_type:
            return vehicle_type
        elif license_plate:
            return f"({license_plate})"
        
        return None

    @staticmethod
    def log_message(
        phone: str,
        text: str,
        from_me: bool = False,
        timestamp: Optional[int] = None
    ) -> WhatsAppMessage:
        """Log WhatsApp message to database.
        
        Args:
            phone: Sender phone number
            text: Message text
            from_me: Whether message is from self (outbound)
            timestamp: Unix timestamp (defaults to now)
            
        Returns:
            Created WhatsAppMessage record
        """
        if timestamp is None:
            created_at = datetime.now()
        else:
            try:
                created_at = datetime.fromtimestamp(timestamp)
            except (ValueError, OSError):
                created_at = datetime.now()
        
        message = WhatsAppMessage(
            phone=phone,
            message_text=text,
            direction="outbound" if from_me else "inbound",
            status="sent" if from_me else "received",
            created_at=created_at
        )
        db.session.add(message)
        db.session.commit()
        return message

    @staticmethod
    def get_recent_messages(phone: str, limit: int = 10) -> list:
        """Get recent messages from specific contact.
        
        Args:
            phone: Phone number
            limit: Max number of messages to return
            
        Returns:
            List of WhatsAppMessage records
        """
        return WhatsAppMessage.query.filter_by(phone=phone).order_by(
            WhatsAppMessage.created_at.desc()
        ).limit(limit).all()

    @staticmethod
    def get_messages_since(phone: str, since: datetime) -> list:
        """Get messages from contact since specific time.
        
        Args:
            phone: Phone number
            since: Datetime to get messages after
            
        Returns:
            List of WhatsAppMessage records
        """
        return WhatsAppMessage.query.filter(
            WhatsAppMessage.phone == phone,
            WhatsAppMessage.created_at >= since
        ).order_by(WhatsAppMessage.created_at.desc()).all()

    @staticmethod
    def is_booking_form(text: str) -> bool:
        """Check if message appears to be a booking form.
        
        Args:
            text: Message text
            
        Returns:
            True if looks like booking form
        """
        return MessageService.parse_booking_form(text) is not None

    @staticmethod
    def is_from_self(from_me: bool) -> bool:
        """Check if message is from self (outbound).
        
        Args:
            from_me: from_me flag
            
        Returns:
            True if outbound message
        """
        return bool(from_me)
