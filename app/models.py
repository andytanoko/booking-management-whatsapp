from __future__ import annotations

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin, cs, technician
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password, method="pbkdf2:sha256")

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), unique=True, nullable=False)
    lid = db.Column(db.String(40), nullable=True, index=True)
    vehicle_info = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ServiceType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    service_type_id = db.Column(db.Integer, db.ForeignKey("service_type.id"), nullable=False)
    scheduled_start = db.Column(db.DateTime, nullable=False)
    scheduled_end = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="confirmed")
    source = db.Column(db.String(30), nullable=False, default="manual")
    notes = db.Column(db.Text, nullable=True)
    other_info = db.Column(db.String(255), nullable=True)  # Package name like "Large Gold"
    vehicle_type = db.Column(db.String(100), nullable=True)  # Jenis Kendaraan: Toyota Rush GR, Honda City, etc
    license_plate = db.Column(db.String(20), nullable=True)  # Nomor Polisi: B1234XYZ
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    assigned_tech_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer = db.relationship("Customer", foreign_keys=[customer_id])
    service_type = db.relationship("ServiceType", foreign_keys=[service_type_id])
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    assigned_technician = db.relationship("User", foreign_keys=[assigned_tech_id])


class WhatsAppMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    direction = db.Column(db.String(10), nullable=False)  # inbound/outbound
    phone = db.Column(db.String(30), nullable=False)
    message_text = db.Column(db.Text, nullable=False)
    payload_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="received")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ReminderLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    reminder_type = db.Column(db.String(20), nullable=False)  # H3, H1, H8
    scheduled_for = db.Column(db.DateTime, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="queued")
    error_message = db.Column(db.String(200), nullable=True)

    booking = db.relationship("Booking", foreign_keys=[booking_id])


class MaintenanceReminder(db.Model):
    """Track maintenance reminders for completed coating/ppf services"""
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False, unique=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    service_type = db.Column(db.String(50), nullable=False)  # "Coating Premium" or "PPF"
    completed_at = db.Column(db.DateTime, nullable=False)  # When original service completed
    maintenance_due_at = db.Column(db.DateTime, nullable=False)  # 6 months from completed_at
    reminder_sent_at = db.Column(db.DateTime, nullable=True)  # When reminder was sent
    review_requested_at = db.Column(db.DateTime, nullable=True)  # When review request was sent
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    booking = db.relationship("Booking", foreign_keys=[booking_id])
    customer = db.relationship("Customer", foreign_keys=[customer_id])


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    actor = db.relationship("User", foreign_keys=[actor_user_id])


class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
