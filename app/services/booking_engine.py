from __future__ import annotations

from datetime import datetime, timedelta

from app.models import Booking, ServiceType
from app.services.settings_store import get_setting


def compute_booking_end(service: ServiceType, start_time: datetime) -> datetime:
    return start_time + timedelta(minutes=service.duration_minutes)


def has_conflict(start_time: datetime, end_time: datetime, exclude_booking_id: int = None) -> bool:
    """Return True when the calendar day of ``start_time`` is already full.

    Bookings are day-based: a day can hold up to ``daily_capacity`` active
    bookings (default 4). When ``daily_capacity`` is 0 or invalid there is no
    limit and this always returns False. ``end_time`` is accepted for call-site
    compatibility but no longer used.
    """
    try:
        capacity = int(get_setting("daily_capacity", "4") or 4)
    except Exception:
        capacity = 4

    if not capacity or capacity <= 0:
        return False

    day_start = datetime(start_time.year, start_time.month, start_time.day)
    day_end = day_start + timedelta(days=1)
    query = (
        Booking.query.filter(~Booking.status.in_("reschedule, cancel, selesai".split(", ")))
        .filter(Booking.scheduled_start >= day_start)
        .filter(Booking.scheduled_start < day_end)
    )
    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)
    return query.count() >= capacity
