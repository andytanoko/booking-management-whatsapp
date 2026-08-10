"""
Reminders service module - handles booking reminders.
Refactored for improved testability and dependency injection.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Dict, Callable

from app.models import Booking, ReminderLog, db
from app.services.db_ops import safe_commit
from app.services.settings_store import get_setting
from app.services.whatsapp import send_and_log_message


# Default reminder rules: when to send reminders before scheduled start
REMINDER_RULES = {
    "H3": timedelta(days=3),      # 3 days before
    "H1": timedelta(days=1),      # 1 day before
}

# Default template for automatic pre-appointment reminders; configurable in Settings.
DEFAULT_APPOINTMENT_REMINDER_TEMPLATE = (
    'Halo {nama}, mengingatkan booking *{layanan}* Anda dijadwalkan pada '
    '{tanggal}. Nomor polisi: *{nomor_polisi}*. Sampai jumpa ya! 🙏'
)

# Default dispatch window for scheduler jitter tolerance (minutes)
DEFAULT_DISPATCH_WINDOW = 15


class ReminderService:
    """Service for managing booking reminders."""

    def __init__(
        self,
        reminder_rules: Optional[Dict[str, timedelta]] = None,
        dispatch_window: int = DEFAULT_DISPATCH_WINDOW,
        message_sender: Optional[Callable] = None
    ):
        """Initialize reminder service.
        
        Args:
            reminder_rules: Dict of reminder_type -> timedelta
            dispatch_window: Window in minutes for sending reminders
            message_sender: Function to send messages (for testing)
        """
        self.reminder_rules = reminder_rules or REMINDER_RULES
        self.dispatch_window = dispatch_window
        self.message_sender = message_sender or send_and_log_message

    def already_sent(self, booking_id: int, reminder_type: str) -> bool:
        """Check if reminder already sent for booking.
        
        Args:
            booking_id: Booking ID
            reminder_type: Type of reminder (e.g., "H3", "H1", "H8")
            
        Returns:
            True if reminder was already sent
        """
        count = ReminderLog.query.filter_by(
            booking_id=booking_id,
            reminder_type=reminder_type,
            status="sent"
        ).count()
        return count > 0

    def should_send_reminder(
        self,
        target_time: datetime,
        current_time: datetime
    ) -> bool:
        """Check if reminder should be sent now.
        
        Args:
            target_time: When reminder should be sent
            current_time: Current time
            
        Returns:
            True if within dispatch window
        """
        window = timedelta(minutes=self.dispatch_window)
        return target_time <= current_time <= target_time + window

    def format_reminder_message(
        self,
        booking: Booking,
        reminder_type: str
    ) -> str:
        """Format reminder message for sending.
        
        Args:
            booking: Booking object
            reminder_type: Type of reminder (e.g., "H3", "H1", "H8")
            
        Returns:
            Formatted message text
        """
        template = get_setting('appointment_reminder_template', DEFAULT_APPOINTMENT_REMINDER_TEMPLATE) or DEFAULT_APPOINTMENT_REMINDER_TEMPLATE
        template = template.replace('{nomor_kendaraan}', '{nomor_polisi}')
        if '{nomor_polisi}' not in template:
            template = f"{template.rstrip()} Nomor polisi: *{{nomor_polisi}}*."
        scheduled = booking.scheduled_start
        nomor_polisi = booking.license_plate or booking.vehicle_type or '-'
        return (
            template.replace('{nama}', booking.customer.name if booking.customer else 'Kak')
            .replace('{layanan}', booking.service_type.name if booking.service_type else 'layanan')
            .replace('{tanggal}', scheduled.strftime('%d-%m-%Y') if scheduled else '-')
            .replace('{nomor_polisi}', nomor_polisi)
            .replace('{nomor_kendaraan}', nomor_polisi)
        )

    def send_reminder(
        self,
        booking: Booking,
        reminder_type: str,
        sent_at: datetime
    ) -> bool:
        """Send reminder for booking and log it.
        
        Args:
            booking: Booking to send reminder for
            reminder_type: Type of reminder
            sent_at: When reminder was sent
            
        Returns:
            True if successfully sent and logged
        """
        if not booking.customer or not booking.customer.phone:
            return False
        
        try:
            message = self.format_reminder_message(booking, reminder_type)
            self.message_sender(booking.customer.phone, message)
            
            target = booking.scheduled_start - self.reminder_rules[reminder_type]
            log = ReminderLog(
                booking_id=booking.id,
                reminder_type=reminder_type,
                scheduled_for=target,
                sent_at=sent_at,
                status="sent"
            )
            db.session.add(log)
            return safe_commit("reminder send_reminder")
        except Exception as e:
            db.session.rollback()
            return False

    def run_due_reminders(self, now: datetime) -> int:
        """Send all due reminders.
        
        Args:
            now: Current datetime
            
        Returns:
            Number of reminders sent
        """
        sent_count = 0
        
        # Get bookings that are confirmed and not yet completed
        upcoming = Booking.query.filter(
            Booking.status.in_(['dikonfirmasi', 'confirmed'])
        ).all()
        
        for booking in upcoming:
            for reminder_type, delta in self.reminder_rules.items():
                # Skip if already sent
                if self.already_sent(booking.id, reminder_type):
                    continue
                
                # Check if this reminder should be sent now
                target = booking.scheduled_start - delta
                if self.should_send_reminder(target, now):
                    if self.send_reminder(booking, reminder_type, now):
                        sent_count += 1
        
        return sent_count

    def get_pending_reminders(self, now: datetime) -> list:
        """Get list of pending reminders that should be sent.
        
        Args:
            now: Current datetime
            
        Returns:
            List of (booking, reminder_type) tuples
        """
        pending = []
        upcoming = Booking.query.filter(
            Booking.status.in_(['dikonfirmasi', 'confirmed'])
        ).all()
        
        for booking in upcoming:
            for reminder_type, delta in self.reminder_rules.items():
                if self.already_sent(booking.id, reminder_type):
                    continue
                
                target = booking.scheduled_start - delta
                if self.should_send_reminder(target, now):
                    pending.append((booking, reminder_type))
        
        return pending

    def get_reminder_status(self, booking_id: int) -> Dict[str, str]:
        """Get status of all reminders for a booking.
        
        Args:
            booking_id: Booking ID
            
        Returns:
            Dict mapping reminder_type to status
        """
        statuses = {}
        for reminder_type in self.reminder_rules.keys():
            log = ReminderLog.query.filter_by(
                booking_id=booking_id,
                reminder_type=reminder_type
            ).order_by(ReminderLog.sent_at.desc()).first()
            statuses[reminder_type] = log.status if log else "pending"
        return statuses


# Create default instance for backward compatibility
_default_service = ReminderService()


def run_due_reminders(now: datetime) -> int:
    """Send all due reminders (legacy function).
    
    Args:
        now: Current datetime
        
    Returns:
        Number of reminders sent
    """
    return _default_service.run_due_reminders(now)
