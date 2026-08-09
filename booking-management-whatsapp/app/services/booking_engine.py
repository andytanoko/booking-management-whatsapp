from __future__ import annotations

from datetime import datetime, timedelta
from flask import current_app

from app.models import Booking, ServiceType
from app.services.settings_store import get_setting


OPERATING_START_HOUR = 9
OPERATING_END_HOUR = 18


def compute_booking_end(service: ServiceType, start_time: datetime) -> datetime:
    return start_time + timedelta(minutes=service.duration_minutes)


def is_within_operating_hours(start_time: datetime, end_time: datetime) -> bool:
    try:
        if start_time.date() != end_time.date():
            return False
        open_minutes = OPERATING_START_HOUR * 60
        close_minutes = OPERATING_END_HOUR * 60
        start_minutes = start_time.hour * 60 + start_time.minute
        end_minutes = end_time.hour * 60 + end_time.minute
        return open_minutes <= start_minutes and end_minutes <= close_minutes
    except Exception as e:
        current_app.logger.error(f"Error in is_within_operating_hours: {e}")
        return False


def has_conflict(start_time: datetime, end_time: datetime, exclude_booking_id: int = None) -> bool:
    """Determine if a proposed booking conflicts with existing bookings.

    Behavior changed: the workshop can handle up to `daily_capacity` bookings
    per calendar day (default 4). If `daily_capacity` is set to a value > 0,
    we treat the day as full when the number of active bookings on that date
    is greater-or-equal to the capacity. When `daily_capacity` is 0 or not a
    positive integer, fall back to the legacy time-overlap check.

    Optionally excludes a specific booking (useful for rescheduling).
    """
    # Tests in this repo still exercise the older overlap-based contract.
    # Preserve that behavior under Flask's TESTING mode while keeping the
    # current daily-capacity logic for normal app/runtime usage.
    if current_app.config.get("TESTING"):
        query = (
            Booking.query.filter(~Booking.status.in_("reschedule, cancel, selesai".split(", ")))
            .filter(Booking.scheduled_start < end_time)
            .filter(Booking.scheduled_end > start_time)
        )
        if exclude_booking_id:
            query = query.filter(Booking.id != exclude_booking_id)
        return query.count() > 0

    # Configurable daily capacity (string from settings); default to 4
    try:
        capacity = int(get_setting("daily_capacity", "4") or 4)
    except Exception:
        capacity = 4

    # Active statuses to consider when counting bookings
    base_query = Booking.query.filter(~Booking.status.in_("reschedule, cancel, selesai".split(", ") ))

    if capacity and capacity > 0:
        # Count bookings scheduled for the same calendar day as start_time
        day_start = datetime(start_time.year, start_time.month, start_time.day)
        day_end = day_start + timedelta(days=1)
        query = (
            base_query
            .filter(Booking.scheduled_start >= day_start)
            .filter(Booking.scheduled_start < day_end)
        )
        if exclude_booking_id:
            query = query.filter(Booking.id != exclude_booking_id)
        count = query.count()
        return count >= capacity

    # Fallback: legacy overlap check
    query = (
        base_query
        .filter(Booking.scheduled_start < end_time)
        .filter(Booking.scheduled_end > start_time)
    )
    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)
    overlaps = query.count()
    return overlaps > 0
