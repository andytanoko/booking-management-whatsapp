from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import Booking, Customer, ServiceType, db
from app.services.audit_service import AuditService
from app.services.booking_engine import compute_booking_end, has_conflict
from app.services.booking_service import BookingService
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
    'Nomor polisi: *{nomor_polisi}*. Terima kasih telah mempercayakan kendaraan Anda kepada kami 🙏'
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
    template = template.replace('{nomor_kendaraan}', '{nomor_polisi}')
    if '{nomor_polisi}' not in template:
        template = f"{template.rstrip()} Nomor polisi: *{{nomor_polisi}}*."
    nomor_polisi = booking.license_plate or booking.vehicle_type or '-'
    return (
        template.replace('{nama}', booking.customer.name if booking.customer else 'Kak')
        .replace('{layanan}', booking.service_type.name if booking.service_type else 'layanan')
        .replace('{tanggal}', booking.scheduled_start.strftime('%d-%m-%Y') if booking.scheduled_start else '-')
        .replace('{nomor_polisi}', nomor_polisi)
        .replace('{nomor_kendaraan}', nomor_polisi)
    )


def _parse_price_input(raw_value: str) -> tuple[Decimal | None, str]:
    raw = (raw_value or '').strip()
    if not raw:
        return None, ''

    normalized = raw.lower().replace('rp', '').replace(' ', '')
    normalized = normalized.replace('.', '').replace(',', '.')
    try:
        value = Decimal(normalized)
    except InvalidOperation:
        return None, 'Format harga tidak valid'

    if value < 0:
        return None, 'Harga tidak boleh negatif'

    return value.quantize(Decimal('0.01')), ''


@bookings_bp.route('/bookings', methods=['GET', 'POST'])
@login_required
def list_bookings():
    if not _authorized():
        return redirect(url_for('dashboard'))

    message = request.args.get('sync_ok')
    error = None
    page = request.args.get('page', 1, type=int)
    per_page = 20

    def render_bookings(message_value, error_value):
        pagination = (
            Booking.query
            .filter(~Booking.status.in_(['cancel', 'batal', 'selesai']))
            .order_by(Booking.scheduled_start.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        services = ServiceType.query.filter_by(active=True).all()
        notify = {}
        for booking in pagination.items:
            if booking.status == 'selesai':
                notify[booking.id] = {
                    'target': _booking_notify_target(booking.customer),
                    'message': _booking_done_message(booking),
                }
        return render_template(
            'bookings.html',
            bookings=pagination.items,
            bookings_pagination=pagination,
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
            message, error = BookingService.update_status(booking_id, new_status, actor_id=current_user.id)
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
                        AuditService.log('booking.notify_customer', actor_id=current_user.id, details=f"booking_id={booking.id} to={target.split('@', 1)[0]}")
                        db.session.commit()
                        message = f'Notifikasi terkirim ke {booking.customer.name}'
            return render_bookings(message, error)

        if action == 'request_reschedule':
            booking_id = int(request.form.get('booking_id', '0') or 0)
            new_date_raw = request.form.get('new_scheduled_start', '').strip()
            message, error = BookingService.request_reschedule(booking_id, new_date_raw, actor_id=current_user.id)
            return render_bookings(message, error)

        customer_name = request.form.get('customer_name', '').strip()
        phone = CustomerService.normalize_phone(request.form.get('phone', '').strip())
        vehicle_type = request.form.get('vehicle_type', '').strip()
        license_plate = request.form.get('license_plate', '').strip()
        service_id = int(request.form.get('service_id', '0') or 0)
        package_name = request.form.get('package_name', '').strip()
        schedule_raw = request.form.get('scheduled_start', '').strip()
        price_raw = request.form.get('price_amount', '').strip()
        notes = request.form.get('notes', '').strip()
        price_amount = None

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

        if not error:
            price_amount, price_error = _parse_price_input(price_raw)
            if price_error:
                error = price_error

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
                    booking = BookingService.create_manual(
                        customer=customer,
                        customer_name=customer_name,
                        phone=phone,
                        vehicle_type=vehicle_type,
                        service=service,
                        start_time=start_time,
                        end_time=end_time,
                        notes=notes,
                        package_name=package_name,
                        license_plate=license_plate,
                        price_amount=price_amount,
                        actor_id=current_user.id,
                    )
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
            price_raw = request.form.get('price_amount', '').strip()
            notes = request.form.get('notes', '').strip()
            price_amount = None

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
                        price_amount, price_error = _parse_price_input(price_raw)
                        if price_error:
                            error = price_error

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
                            BookingService.apply_edit(
                                booking,
                                target_customer,
                                customer_name=customer_name,
                                phone=phone,
                                vehicle_type=vehicle_type,
                                service=service,
                                start_time=start_time,
                                end_time=end_time,
                                notes=notes,
                                package_name=package_name,
                                license_plate=license_plate,
                                price_amount=price_amount,
                                actor_id=current_user.id,
                            )
                            message = 'Booking berhasil diperbarui'
                            return redirect(url_for('bookings.list_bookings'))

    return render_template('edit_booking.html', booking=booking, services=services, statuses=BOOKING_STATUSES, message=message, error=error, partial=wants_partial())
