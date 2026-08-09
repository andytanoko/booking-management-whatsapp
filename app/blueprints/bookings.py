from datetime import datetime, timedelta

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import AuditLog, Booking, Customer, MaintenanceReminder, ServiceType, db
from app.services.booking_engine import compute_booking_end, has_conflict
from app.services.customer_service import CustomerService
from app.services.semantic_matcher import get_variant_info, match_package_to_service
from app.services.settings_store import get_setting
from app.services.whatsapp import check_whatsapp_number_registered, normalize_whatsapp_number, send_and_log_message

bookings_bp = Blueprint('bookings', __name__)

BOOKING_STATUSES = {
    'dikonfirmasi': 'Dikonfirmasi',
    'kendaraan_masuk': 'Kendaraan Masuk',
    'dikerjakan': 'Dikerjakan',
    'qc': 'QC / Cek Hasil',
    'siap_diambil': 'Siap Diambil',
    'selesai': 'Selesai',
    'reschedule': 'Reschedule',
    'cancel': 'Cancel',
    'batal': 'Batal',
}
DEFAULT_BOOKING_DONE_TEMPLATE = (
    'Halo {nama}, kabar baik! Kendaraan Anda untuk layanan *{layanan}* '
    'sudah *selesai* dikerjakan dan siap diambil. '
    'Terima kasih telah mempercayakan kendaraan Anda kepada kami 🙏'
)


def wants_partial() -> bool:
    return request.headers.get('X-Requested-With') == 'fetch'


def _authorized() -> bool:
    return current_user.is_authenticated and current_user.role in {'admin', 'cs'}


def _validate_active_whatsapp_number(phone: str) -> str:
    normalized = normalize_whatsapp_number(phone)
    if not normalized:
        return 'Format nomor WhatsApp tidak valid'
    registered, _ = check_whatsapp_number_registered(normalized)
    if registered is False:
        return 'Nomor WhatsApp tidak ditemukan/tidak aktif di WhatsApp'
    return ''


def _booking_notify_target(customer: Customer) -> str:
    if customer is None:
        return ''
    normalized_phone = normalize_whatsapp_number(customer.phone or '')
    if normalized_phone:
        return f'{normalized_phone}@c.us'
    lid = str(customer.lid or '').strip()
    if lid.isdigit():
        return f'{lid}@lid'
    return ''


def _booking_done_message(booking: Booking) -> str:
    template = get_setting('booking_done_template', DEFAULT_BOOKING_DONE_TEMPLATE) or DEFAULT_BOOKING_DONE_TEMPLATE
    return (
        template.replace('{nama}', booking.customer.name if booking.customer else 'Kak')
        .replace('{layanan}', booking.service_type.name if booking.service_type else 'layanan')
        .replace('{tanggal}', booking.scheduled_start.strftime('%d-%m-%Y') if booking.scheduled_start else '-')
    )


@bookings_bp.route('/bookings', methods=['GET', 'POST'])
@login_required
def list_bookings():
    if not _authorized():
        return redirect(url_for('dashboard'))

    message = request.args.get('sync_ok')
    error = None

    def render_bookings(message_value, error_value):
        data = Booking.query.filter(~Booking.status.in_(['cancel', 'batal', 'selesai'])).order_by(Booking.scheduled_start.asc()).all()
        services = ServiceType.query.filter_by(active=True).all()
        notify = {}
        for booking in data:
            if booking.status == 'selesai':
                notify[booking.id] = {
                    'target': _booking_notify_target(booking.customer),
                    'message': _booking_done_message(booking),
                }
        return render_template(
            'bookings.html',
            bookings=data,
            services=services,
            statuses=BOOKING_STATUSES,
            notify=notify,
            message=message_value,
            error=error_value,
            partial=wants_partial(),
        )

    if request.method == 'POST':
        action = request.form.get('action', 'create').strip()

        if action == 'update_status':
            booking_id = int(request.form.get('booking_id', '0') or 0)
            new_status = request.form.get('status', '').strip().lower()
            booking = db.session.get(Booking, booking_id)
            if not booking:
                error = 'Booking tidak ditemukan'
            elif new_status not in BOOKING_STATUSES:
                error = 'Status tidak valid'
            else:
                old_status = booking.status
                booking.status = new_status
                db.session.add(AuditLog(actor_user_id=current_user.id, action='booking.status_change', details=f'booking_id={booking.id} {old_status}->{new_status}'))
                db.session.commit()
                message = f"Status booking #{booking.id} diperbarui menjadi '{BOOKING_STATUSES[new_status]}'"
                if new_status == 'selesai' and booking.service_type.after_service:
                    existing_reminder = MaintenanceReminder.query.filter_by(booking_id=booking.id).first()
                    if not existing_reminder:
                        reminder = MaintenanceReminder(
                            booking_id=booking.id,
                            customer_id=booking.customer_id,
                            service_type=booking.service_type.name,
                            completed_at=datetime.utcnow(),
                            maintenance_due_at=datetime.utcnow() + timedelta(days=180),
                        )
                        db.session.add(reminder)
                        db.session.commit()
                        message += ' | Maintenance reminder dibuat (6 bulan).'
            return render_bookings(message, error)

        if action == 'notify_customer':
            booking_id = int(request.form.get('booking_id', '0') or 0)
            text = request.form.get('message', '').strip()
            booking = db.session.get(Booking, booking_id)
            if not booking:
                error = 'Booking tidak ditemukan'
            elif not text:
                error = 'Pesan tidak boleh kosong'
            else:
                target = _booking_notify_target(booking.customer)
                if not target:
                    error = 'Nomor WhatsApp customer tidak tersedia'
                else:
                    from app import app as app_module

                    sent = app_module.send_and_log_message(target.split('@', 1)[0], text, chat_id=target)
                    if sent.status == 'failed':
                        error = f'Gagal mengirim notifikasi: {sent.status}'
                    else:
                        db.session.add(AuditLog(actor_user_id=current_user.id, action='booking.notify_customer', details=f"booking_id={booking.id} to={target.split('@', 1)[0]}"))
                        db.session.commit()
                        message = f'Notifikasi terkirim ke {booking.customer.name}'
            return render_bookings(message, error)

        if action == 'request_reschedule':
            booking_id = int(request.form.get('booking_id', '0') or 0)
            new_date_raw = request.form.get('new_scheduled_start', '').strip()
            booking = db.session.get(Booking, booking_id)
            if not booking:
                error = 'Booking tidak ditemukan'
            elif booking.status == 'reschedule':
                error = 'Booking sudah dalam status reschedule'
            else:
                requested_date = None
                if new_date_raw:
                    try:
                        try:
                            new_date = datetime.strptime(new_date_raw, '%Y-%m-%dT%H:%M')
                        except ValueError:
                            new_date = datetime.strptime(new_date_raw, '%Y-%m-%d')
                        requested_date = new_date.strftime('%d-%m-%Y')
                    except ValueError:
                        error = 'Format tanggal tidak valid'
                if not error:
                    booking.status = 'reschedule'
                    if requested_date:
                        note_prefix = f'[Permintaan reschedule: {requested_date}]'
                        booking.notes = f'{note_prefix}\n{booking.notes}' if booking.notes else note_prefix
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='booking.request_reschedule', details=f"booking_id={booking.id} requested_date={requested_date or 'none'}"))
                    db.session.commit()
                    message = f'Permintaan reschedule untuk booking #{booking.id} berhasil dikirim'
            return render_bookings(message, error)

        customer_name = request.form.get('customer_name', '').strip()
        phone = CustomerService.normalize_phone(request.form.get('phone', '').strip())
        vehicle_type = request.form.get('vehicle_type', '').strip()
        license_plate = request.form.get('license_plate', '').strip()
        service_id = int(request.form.get('service_id', '0') or 0)
        package_name = request.form.get('package_name', '').strip()
        schedule_raw = request.form.get('scheduled_start', '').strip()
        notes = request.form.get('notes', '').strip()

        service = None
        variant_info = None
        lainnya_service = ServiceType.query.filter_by(name='Lainnya').first()

        if not customer_name or not phone:
            error = 'Nama pelanggan dan nomor WhatsApp wajib diisi'
        elif package_name and not service_id:
            all_services = ServiceType.query.filter_by(active=True).all()
            matched_service = match_package_to_service(package_name, all_services)
            if matched_service:
                service = matched_service
                variant_info = get_variant_info(package_name, all_services)
                package_note = f'Paket: {package_name}'
                if variant_info:
                    package_note += f' (varian: {variant_info})'
                notes = f'{package_note}\n{notes}' if notes else package_note
            else:
                service = lainnya_service
                if service:
                    package_note = f'Paket: {package_name} (tidak cocok dengan layanan standard, masuk ke Lainnya)'
                    notes = f'{package_note}\n{notes}' if notes else package_note
                else:
                    error = "Service default 'Lainnya' tidak tersedia"
        elif service_id:
            service = db.session.get(ServiceType, service_id)
            if not service:
                error = 'Layanan tidak ditemukan'
        else:
            service = lainnya_service
            if not service:
                error = "Service default 'Lainnya' tidak tersedia"

        start_time = None
        if not error:
            try:
                try:
                    start_time = datetime.strptime(schedule_raw, '%Y-%m-%dT%H:%M')
                except ValueError:
                    start_time = datetime.strptime(schedule_raw, '%Y-%m-%d')
            except ValueError:
                error = 'Format tanggal tidak valid'

        if service and start_time and not error:
            end_time = compute_booking_end(service, start_time)
            if has_conflict(start_time, end_time):
                error = 'Jadwal bentrok dengan booking lain'
            else:
                customer = Customer.query.filter_by(phone=phone).first()
                if not customer:
                    wa_error = _validate_active_whatsapp_number(phone)
                    if wa_error:
                        error = wa_error

                if not error:
                    if not customer:
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
                        created_by_user_id=current_user.id,
                    )
                    db.session.add(booking)
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='booking.create', details=f'booking_id=pending customer={customer.phone} service={service.name}'))
                    db.session.commit()
                    message = 'Booking berhasil dibuat'

    return render_bookings(message, error)


@bookings_bp.route('/bookings/<int:booking_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_booking(booking_id: int):
    if not _authorized():
        return redirect(url_for('dashboard'))

    booking = db.session.get(Booking, booking_id)
    if not booking:
        return 'Booking tidak ditemukan', 404

    message = None
    error = None
    services = ServiceType.query.filter_by(active=True).all()

    if request.method == 'POST':
        action = request.form.get('action', '').strip()
        if action == 'update':
            customer_name = request.form.get('customer_name', '').strip()
            phone = CustomerService.normalize_phone(request.form.get('phone', '').strip())
            vehicle_type = request.form.get('vehicle_type', '').strip()
            license_plate = request.form.get('license_plate', '').strip()
            service_id = int(request.form.get('service_id', '0') or 0)
            package_name = request.form.get('package_name', '').strip()
            schedule_raw = request.form.get('scheduled_start', '').strip()
            notes = request.form.get('notes', '').strip()

            service = None
            variant_info = None
            lainnya_service = ServiceType.query.filter_by(name='Lainnya').first()

            if not customer_name or not phone:
                error = 'Nama pelanggan dan nomor WhatsApp wajib diisi'
            elif not schedule_raw:
                error = 'Jadwal wajib diisi'
            else:
                if package_name and not service_id:
                    all_services = ServiceType.query.filter_by(active=True).all()
                    matched_service = match_package_to_service(package_name, all_services)
                    if matched_service:
                        service = matched_service
                        variant_info = get_variant_info(package_name, all_services)
                        package_note = f'Paket: {package_name}'
                        if variant_info:
                            package_note += f' (varian: {variant_info})'
                        notes = f'{package_note}\n{notes}' if notes else package_note
                    else:
                        service = lainnya_service
                        if service:
                            package_note = f'Paket: {package_name} (tidak cocok dengan layanan standard, masuk ke Lainnya)'
                            notes = f'{package_note}\n{notes}' if notes else package_note
                elif service_id:
                    service = db.session.get(ServiceType, service_id)
                    if not service:
                        error = 'Layanan tidak ditemukan'
                else:
                    service = lainnya_service
                    if not service:
                        error = "Service default 'Lainnya' tidak tersedia"

                if not error and service:
                    try:
                        try:
                            start_time = datetime.strptime(schedule_raw, '%Y-%m-%dT%H:%M')
                        except ValueError:
                            start_time = datetime.strptime(schedule_raw, '%Y-%m-%d')
                    except ValueError:
                        error = 'Format tanggal tidak valid'

                    if not error:
                        end_time = compute_booking_end(service, start_time)
                        if has_conflict(start_time, end_time, exclude_booking_id=booking.id):
                            error = 'Jadwal bentrok dengan booking lain'
                        else:
                            customer = booking.customer
                            target_customer = customer
                            if customer.phone != phone:
                                existing_customer = Customer.query.filter(Customer.phone == phone, Customer.id != customer.id).first()
                                if existing_customer:
                                    error = 'Nomor WhatsApp sudah terdaftar untuk kontak lain'
                                else:
                                    error = _validate_active_whatsapp_number(phone)

                        if not error:
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
                            db.session.add(AuditLog(actor_user_id=current_user.id, action='booking.edit', details=f'booking_id={booking.id} customer={target_customer.phone} service={service.name}'))
                            db.session.commit()
                            message = 'Booking berhasil diperbarui'
                            return redirect(url_for('bookings.list_bookings'))

    return render_template('edit_booking.html', booking=booking, services=services, statuses=BOOKING_STATUSES, message=message, error=error, partial=wants_partial())
