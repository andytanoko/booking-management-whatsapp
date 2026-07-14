from __future__ import annotations

from datetime import datetime, timedelta

from app.models import Booking, ServiceType


OPERATING_START_HOUR = 9
OPERATING_END_HOUR = 18


def compute_booking_end(service: ServiceType, start_time: datetime) -> datetime:
    return start_time + timedelta(minutes=service.duration_minutes)


def is_within_operating_hours(start_time: datetime, end_time: datetime) -> bool:
    if start_time.date() != end_time.date():
        return False
    open_minutes = OPERATING_START_HOUR * 60
    close_minutes = OPERATING_END_HOUR * 60
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    return open_minutes <= start_minutes and end_minutes <= close_minutes


def has_conflict(start_time: datetime, end_time: datetime, exclude_booking_id: int = None) -> bool:
    """Check if a time slot has conflict with existing bookings.
    
    Only checks active bookings (not reschedule, cancel, or batal).
    Optionally excludes a specific booking (useful for rescheduling).
    """
    query = (
        Booking.query
        .filter(~Booking.status.in_(["reschedule", "cancel", "batal", "selesai"]))
        .filter(Booking.scheduled_start < end_time)
        .filter(Booking.scheduled_end > start_time)
    )
    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)
    overlaps = query.count()
    return overlaps > 0
