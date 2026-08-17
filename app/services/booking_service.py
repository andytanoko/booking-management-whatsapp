"""
Booking service - owns all Booking (and booking-triggered) table writes.

Keeps status changes, reschedule requests, booking creation/editing and the
maintenance-reminder side effect out of the route layer.
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.models import Booking, Customer, MaintenanceReminder, db
from app.services.audit_service import AuditService

# (message, error) - exactly one is non-None.
Result = Tuple[Optional[str], Optional[str]]


class BookingService:
    """Service for managing bookings and their write side effects."""

    @staticmethod
    def update_status(booking_id: int, new_status: str, actor_id: Optional[int]) -> Result:
        from app.blueprints.bookings import BOOKING_STATUSES

        new_status = (new_status or '').strip().lower()
        booking = db.session.get(Booking, booking_id)
        if not booking:
            return None, 'Booking tidak ditemukan'
        if new_status not in BOOKING_STATUSES:
            return None, 'Status tidak valid'
        old_status = booking.status
        booking.status = new_status
        AuditService.log('booking.status_change', actor_id=actor_id, details=f'booking_id={booking.id} {old_status}->{new_status}')
        db.session.commit()
        message = f"Status booking #{booking.id} diperbarui menjadi '{BOOKING_STATUSES[new_status]}'"
        if new_status == 'selesai' and booking.service_type.after_service:
            existing_reminder = MaintenanceReminder.query.filter_by(booking_id=booking.id).first()
            if not existing_reminder:
                db.session.add(MaintenanceReminder(
                    booking_id=booking.id,
                    customer_id=booking.customer_id,
                    service_type=booking.service_type.name,
                    completed_at=datetime.utcnow(),
                    maintenance_due_at=datetime.utcnow() + timedelta(days=180),
                ))
                db.session.commit()
                message += ' | Maintenance reminder dibuat (6 bulan).'
        return message, None

    @staticmethod
    def request_reschedule(booking_id: int, new_date_raw: str, actor_id: Optional[int]) -> Result:
        booking = db.session.get(Booking, booking_id)
        if not booking:
            return None, 'Booking tidak ditemukan'
        if booking.status == 'reschedule':
            return None, 'Booking sudah dalam status reschedule'
        requested_date = None
        new_date_raw = (new_date_raw or '').strip()
        if new_date_raw:
            try:
                try:
                    new_date = datetime.strptime(new_date_raw, '%Y-%m-%dT%H:%M')
                except ValueError:
                    new_date = datetime.strptime(new_date_raw, '%Y-%m-%d')
                requested_date = new_date.strftime('%d-%m-%Y')
            except ValueError:
                return None, 'Format tanggal tidak valid'
        booking.status = 'reschedule'
        if requested_date:
            note_prefix = f'[Permintaan reschedule: {requested_date}]'
            booking.notes = f'{note_prefix}\n{booking.notes}' if booking.notes else note_prefix
        AuditService.log('booking.request_reschedule', actor_id=actor_id, details=f"booking_id={booking.id} requested_date={requested_date or 'none'}")
        db.session.commit()
        return f'Permintaan reschedule untuk booking #{booking.id} berhasil dikirim', None

    @staticmethod
    def create_manual(
        customer: Optional[Customer],
        customer_name: str,
        phone: str,
        vehicle_type: str,
        service,
        start_time: datetime,
        end_time: datetime,
        notes: str,
        package_name: str,
        license_plate: str,
        price_amount,
        actor_id: Optional[int],
    ) -> Booking:
        """Create a manual booking, creating the customer first if needed.

        Caller is responsible for validating the customer/schedule beforehand.
        """
        if customer is None:
            customer = Customer(name=customer_name, phone=phone, vehicle_info=vehicle_type or None)
            db.session.add(customer)
            db.session.flush()
        booking = Booking(
            customer_id=customer.id,
            service_type_id=service.id,
            scheduled_start=start_time,
            scheduled_end=end_time,
            status='dikonfirmasi',
            source='manual',
            notes=notes,
            other_info=package_name,
            vehicle_type=vehicle_type,
            license_plate=license_plate,
            price_amount=price_amount,
            created_by_user_id=actor_id,
        )
        db.session.add(booking)
        AuditService.log('booking.create', actor_id=actor_id, details=f'booking_id=pending customer={customer.phone} service={service.name}')
        db.session.commit()
        return booking

    @staticmethod
    def apply_edit(
        booking: Booking,
        target_customer: Customer,
        customer_name: str,
        phone: str,
        vehicle_type: str,
        service,
        start_time: datetime,
        end_time: datetime,
        notes: str,
        package_name: str,
        license_plate: str,
        price_amount,
        actor_id: Optional[int],
    ) -> Booking:
        """Apply an edit to an existing booking and its customer."""
        target_customer.name = customer_name
        target_customer.phone = phone
        target_customer.vehicle_info = vehicle_type or None
        booking.service_type_id = service.id
        booking.scheduled_start = start_time
        booking.scheduled_end = end_time
        booking.notes = notes
        booking.other_info = package_name
        booking.vehicle_type = vehicle_type
        booking.license_plate = license_plate
        booking.price_amount = price_amount
        AuditService.log('booking.edit', actor_id=actor_id, details=f'booking_id={booking.id} customer={target_customer.phone} service={service.name}')
        db.session.commit()
        return booking
