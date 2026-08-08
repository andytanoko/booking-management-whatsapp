from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from app.models import Booking, db
from typing import List

bookings_bp = Blueprint('bookings', __name__)

@bookings_bp.route('/bookings', methods=['GET', 'POST'])
@login_required
def list_bookings():
    try:
        bookings = Booking.query.order_by(Booking.scheduled_start.desc()).all()
        return render_template('bookings/list.html', bookings=bookings)
    except Exception as e:
        current_app.logger.error(f'Error in list_bookings: {e}')
        flash('Terjadi kesalahan saat memuat data booking.', 'danger')
        return redirect(url_for('dashboard'))

@bookings_bp.route('/bookings/<int:booking_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_booking(booking_id: int):
    try:
        booking = Booking.query.get_or_404(booking_id)
        return render_template('bookings/edit.html', booking=booking)
    except Exception as e:
        current_app.logger.error(f'Error editing booking {booking_id}: {e}')
        flash('Gagal mengubah data booking.', 'danger')
        return redirect(url_for('bookings.list_bookings'))
