"""
Maintenance service - owns writes for maintenance reminders and the
reminder-to-booking conversion.
"""
from datetime import datetime
from typing import Optional, Tuple

from app.models import Booking, MaintenanceReminder, ServiceType, db
from app.services.audit_service import AuditService
from app.services.booking_engine import compute_booking_end

MAINTENANCE_SERVICE_NAME = 'Maintenance'

# (message, error) - exactly one is non-None.
Result = Tuple[Optional[str], Optional[str]]


class MaintenanceService:
    """Service for maintenance-reminder actions."""

    @staticmethod
    def _send(phone: str, text: str):
        # Local import keeps the app-level send wrapper (and its test shim)
        # without a circular import at module load.
        from app import app as app_module
        return app_module.send_and_log_message(phone, text)

    @staticmethod
    def send_reminder(reminder_id: int, message_text: str, actor_id: Optional[int]) -> Result:
        reminder = MaintenanceReminder.query.get(reminder_id)
        if not reminder:
            return None, 'Maintenance reminder tidak ditemukan'
        message_text = (message_text or '').strip()
        if not message_text:
            return None, 'Pesan tidak boleh kosong'
        sent = MaintenanceService._send(reminder.customer.phone, message_text)
        if sent.status == 'failed':
            return None, f'Gagal kirim reminder: {sent.status}'
        reminder.reminder_sent_at = datetime.utcnow()
        AuditService.log('maintenance.reminder_sent', actor_id=actor_id, details=f'reminder_id={reminder_id} customer={reminder.customer.phone}')
        db.session.commit()
        return f'Maintenance reminder terkirim ke {reminder.customer.name}', None

    @staticmethod
    def send_review(reminder_id: int, message_text: str, actor_id: Optional[int]) -> Result:
        reminder = MaintenanceReminder.query.get(reminder_id)
        if not reminder:
            return None, 'Maintenance reminder tidak ditemukan'
        message_text = (message_text or '').strip()
        if not message_text:
            return None, 'Pesan tidak boleh kosong'
        sent = MaintenanceService._send(reminder.customer.phone, message_text)
        if sent.status == 'failed':
            return None, f'Gagal kirim review request: {sent.status}'
        reminder.review_requested_at = datetime.utcnow()
        AuditService.log('maintenance.review_requested', actor_id=actor_id, details=f'reminder_id={reminder_id} customer={reminder.customer.phone}')
        db.session.commit()
        return f'Review request terkirim ke {reminder.customer.name}', None

    @staticmethod
    def book_maintenance(reminder_id: int, schedule_raw: str, actor_id: Optional[int]) -> Result:
        reminder = MaintenanceReminder.query.get(reminder_id)
        service = ServiceType.query.filter_by(name=MAINTENANCE_SERVICE_NAME).first()
        if not reminder:
            return None, 'Maintenance reminder tidak ditemukan'
        if not service:
            return None, f"Layanan '{MAINTENANCE_SERVICE_NAME}' belum tersedia di Settings"
        try:
            start_time = datetime.strptime((schedule_raw or '').strip(), '%Y-%m-%d')
        except ValueError:
            return None, 'Tanggal booking wajib diisi dengan format yang valid'
        original_booking = reminder.booking
        customer_name = reminder.customer.name
        new_booking = Booking(
            customer_id=reminder.customer.id,
            service_type_id=service.id,
            scheduled_start=start_time,
            scheduled_end=compute_booking_end(service, start_time),
            status='dikonfirmasi',
            source='maintenance',
            notes=f'Booking maintenance dari reminder #{reminder.id}',
            vehicle_type=(original_booking.vehicle_type if original_booking else None) or reminder.customer.vehicle_info,
            license_plate=original_booking.license_plate if original_booking else None,
            created_by_user_id=actor_id,
        )
        db.session.add(new_booking)
        AuditService.log('maintenance.booking_created', actor_id=actor_id, details=f'reminder_id={reminder.id} customer={reminder.customer.phone} service={service.name}')
        db.session.delete(reminder)
        db.session.commit()
        return f"Booking '{service.name}' berhasil dibuat untuk {customer_name}. Atur tanggal jadwalnya di halaman Bookings.", None
