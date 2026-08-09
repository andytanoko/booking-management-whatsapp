from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict, Any, List
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    """System user model for authentication and authorization."""
    id: int = db.Column(db.Integer, primary_key=True)
    username: str = db.Column(db.String(80), unique=True, nullable=False)
    password_hash: str = db.Column(db.String(255), nullable=False)
    role: str = db.Column(db.String(20), nullable=False)  # admin, cs, technician
    active: bool = db.Column(db.Boolean, default=True, nullable=False)
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, raw_password: str) -> None:
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(raw_password, method='pbkdf2:sha256')

    def check_password(self, raw_password: str) -> bool:
        """Verify the provided password against the hash."""
        return check_password_hash(self.password_hash, raw_password)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize user data."""
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'active': self.active,
            'created_at': self.created_at.isoformat()
        }

class Customer(db.Model):
    """Customer information and vehicle details."""
    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(120), nullable=False)
    phone: str = db.Column(db.String(30), unique=True, nullable=False)
    lid: Optional[str] = db.Column(db.String(40), nullable=True, index=True)
    vehicle_info: Optional[str] = db.Column(db.String(200), nullable=True)
    notes: Optional[str] = db.Column(db.Text, nullable=True)
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize customer data."""
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'lid': self.lid,
            'vehicle_info': self.vehicle_info,
            'notes': self.notes
        }

class ServiceType(db.Model):
    """Available service types and their durations."""
    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(80), unique=True, nullable=False)
    duration_minutes: int = db.Column(db.Integer, nullable=False)
    active: bool = db.Column(db.Boolean, default=True, nullable=False)
    after_service: Optional[str] = db.Column(db.String(50), nullable=True, default=None)
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize service type data."""
        return {
            'id': self.id,
            'name': self.name,
            'duration': self.duration_minutes,
            'active': self.active
        }

class Booking(db.Model):
    """Booking records linking customers to services."""
    id: int = db.Column(db.Integer, primary_key=True)
    customer_id: int = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    service_type_id: int = db.Column(db.Integer, db.ForeignKey('service_type.id'), nullable=False)
    scheduled_start: datetime = db.Column(db.DateTime, nullable=False)
    scheduled_end: datetime = db.Column(db.DateTime, nullable=False)
    status: str = db.Column(db.String(30), nullable=False, default='confirmed')
    source: str = db.Column(db.String(30), nullable=False, default='manual')
    notes: Optional[str] = db.Column(db.Text, nullable=True)
    other_info: Optional[str] = db.Column(db.String(255), nullable=True)
    vehicle_type: Optional[str] = db.Column(db.String(100), nullable=True)
    license_plate: Optional[str] = db.Column(db.String(20), nullable=True)
    created_by_user_id: Optional[int] = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    assigned_tech_id: Optional[int] = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship('Customer', foreign_keys=[customer_id])
    service_type = db.relationship('ServiceType', foreign_keys=[service_type_id])
    created_by_user = db.relationship('User', foreign_keys=[created_by_user_id])
    assigned_technician = db.relationship('User', foreign_keys=[assigned_tech_id])

    def to_dict(self) -> Dict[str, Any]:
        """Serialize booking data."""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'service_id': self.service_type_id,
            'status': self.status,
            'start': self.scheduled_start.isoformat(),
            'end': self.scheduled_end.isoformat(),
            'vehicle': f"{self.vehicle_type} ({self.license_plate})" if self.vehicle_type else self.license_plate
        }

class WhatsAppMessage(db.Model):
    """Logs for inbound and outbound WhatsApp messages."""
    id: int = db.Column(db.Integer, primary_key=True)
    direction: str = db.Column(db.String(10), nullable=False)
    phone: str = db.Column(db.String(30), nullable=False)
    message_text: str = db.Column(db.Text, nullable=False)
    payload_json: Optional[str] = db.Column(db.Text, nullable=True)
    status: str = db.Column(db.String(20), nullable=False, default='received')
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize message data."""
        return {
            'id': self.id,
            'direction': self.direction,
            'phone': self.phone,
            'text': self.message_text,
            'status': self.status,
            'created_at': self.created_at.isoformat()
        }

class ReminderLog(db.Model):
    """Logs for automated reminders sent to customers."""
    id: int = db.Column(db.Integer, primary_key=True)
    booking_id: int = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    reminder_type: str = db.Column(db.String(20), nullable=False)  # H3, H1, H8
    scheduled_for: datetime = db.Column(db.DateTime, nullable=False)
    sent_at: Optional[datetime] = db.Column(db.DateTime, nullable=True)
    status: str = db.Column(db.String(20), nullable=False, default="queued")
    error_message: Optional[str] = db.Column(db.String(200), nullable=True)

    booking = db.relationship("Booking", foreign_keys=[booking_id])

class MaintenanceReminder(db.Model):
    """Track maintenance reminders for completed coating/ppf services."""
    id: int = db.Column(db.Integer, primary_key=True)
    booking_id: int = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False, unique=True)
    customer_id: int = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    service_type: str = db.Column(db.String(50), nullable=False)
    completed_at: datetime = db.Column(db.DateTime, nullable=False)
    maintenance_due_at: datetime = db.Column(db.DateTime, nullable=False)
    reminder_sent_at: Optional[datetime] = db.Column(db.DateTime, nullable=True)
    review_requested_at: Optional[datetime] = db.Column(db.DateTime, nullable=True)
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    booking = db.relationship("Booking", foreign_keys=[booking_id])
    customer = db.relationship("Customer", foreign_keys=[customer_id])

class AuditLog(db.Model):
    """Audit trail for system actions."""
    id: int = db.Column(db.Integer, primary_key=True)
    actor_user_id: Optional[int] = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    action: str = db.Column(db.String(100), nullable=False)
    details: Optional[str] = db.Column(db.Text, nullable=True)
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    actor = db.relationship("User", foreign_keys=[actor_user_id])

class AppSetting(db.Model):
    """System-wide configuration settings."""
    id: int = db.Column(db.Integer, primary_key=True)
    key: str = db.Column(db.String(100), unique=True, nullable=False)
    value: str = db.Column(db.Text, nullable=False, default='')
    updated_at: datetime = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize setting data."""
        return {
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat()
        }