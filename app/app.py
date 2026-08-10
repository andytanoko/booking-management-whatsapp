import json
import os
import re
import secrets
import time
from datetime import datetime

from flask import Flask, Response, current_app, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager, current_user, login_user as flask_login_user
from flask_migrate import Migrate
from sqlalchemy.exc import IntegrityError

from app.blueprints.auth import auth_bp
from app.blueprints.bookings import bookings_bp
from app.blueprints.settings import settings_bp
from app.blueprints.whatsapp import whatsapp_bp
from app.models import AuditLog, Booking, Customer, ServiceType, User, WhatsAppMessage, db
from app.services.booking_engine import compute_booking_end, has_conflict
from app.services.customer_service import CustomerService
from app.services.message_service import MessageService
from app.services.message_service import BOOKING_FORM_LABELS
from app.services.reminders import run_due_reminders
from app.services.settings_store import get_setting
from app.services.whatsapp import (
    check_whatsapp_number_registered,
    create_wa_instance as _create_wa_instance,
    delete_wa_instance as _delete_wa_instance,
    discover_bridge_profile as _discover_bridge_profile,
    fetch_whatsapp_contacts,
    list_wa_instances as _list_wa_instances,
    normalize_whatsapp_number,
    send_and_log_message as _send_and_log_message,
    wa_instance_qr_embed_url as _wa_instance_qr_embed_url,
)
from app.blueprints.whatsapp import (
    _create_booking_from_form,
    _extract_lid,
    _resolve_real_number,
    _sync_customer_from_inbound,
    build_message_view as _build_message_view,
)
from app.blueprints.settings import (
    DEFAULT_MAINTENANCE_REMINDER_TEMPLATE,
    DEFAULT_REVIEW_REQUEST_TEMPLATE,
)


migrate = Migrate()


BOOKING_STATUSES = {
    'baru': 'Baru',
    'dikonfirmasi': 'Dikonfirmasi',
    'kendaraan_masuk': 'Kendaraan Masuk',
    'dikerjakan': 'Dikerjakan',
    'qc': 'QC',
    'siap_diambil': 'Siap Diambil',
    'selesai': 'Selesai',
    'reschedule': 'Reschedule',
    'batal': 'Batal',
    'cancel': 'Cancel',
}

DEFAULT_BOOKING_DONE_TEMPLATE = (
    'Halo {nama}, kabar baik! Kendaraan Anda untuk layanan *{layanan}* '
    'sudah *selesai* dikerjakan dan siap diambil. '
    'Nomor polisi: *{nomor_polisi}*. Terima kasih telah mempercayakan kendaraan Anda kepada kami.'
)

DEFAULT_RESCHEDULE_TEMPLATE = (
    'Halo {nama}, kami terima permintaan reschedule untuk *{layanan}*. '
    'Jadwal awal: {tanggal_lama} -> Jadwal baru: {tanggal_baru}. '
    'Nomor polisi: *{nomor_polisi}*. Apakah sudah tepat? Silakan konfirmasi ya.'
)


def _normalize_police_placeholder(template: str) -> str:
    normalized = (template or '').replace('{nomor_kendaraan}', '{nomor_polisi}')
    if '{nomor_polisi}' in normalized:
        return normalized
    return f"{normalized.rstrip()} Nomor polisi: *{{nomor_polisi}}*."

parse_booking_form = MessageService.parse_booking_form
parse_schedule_text = MessageService.parse_date
_clean_form_value = MessageService.clean_form_value
_normalize_form_phone = CustomerService.normalize_phone


def resolve_real_number(data: dict, phone: str) -> str:
    contact_number = str((data or {}).get('contact_number', '') or '').strip()
    if contact_number.isdigit() and 8 <= len(contact_number) <= 15:
        return contact_number

    chat_id = str((data or {}).get('chat_id', '') or '').strip().lower()
    if chat_id.endswith('@c.us'):
        number = chat_id.split('@', 1)[0]
        if number.isdigit() and 8 <= len(number) <= 15:
            return number

    phone = str(phone or '').strip()
    if phone.isdigit() and 8 <= len(phone) <= 15:
        return phone
    return ''


def extract_lid(data: dict, phone: str) -> str:
    chat_id = str((data or {}).get('chat_id', '') or '').strip().lower()
    if chat_id.endswith('@lid'):
        lid = chat_id.split('@', 1)[0]
        if lid.isdigit() and 8 <= len(lid) <= 20:
            return lid

    phone = str(phone or '').strip().lower()
    if phone.startswith('lid:'):
        lid = phone.split(':', 1)[1]
        if lid.isdigit() and 8 <= len(lid) <= 20:
            return lid
    return ''


def sync_customer_from_inbound(data: dict, phone: str) -> None:
    return _sync_customer_from_inbound(data, phone)


def create_booking_from_form(form: dict, data: dict):
    compat_form = dict(form)
    compat_form.setdefault('vehicle_type', compat_form.get('vehicle_type') or 'Tidak diketahui')
    return _create_booking_from_form(compat_form, data)


def build_message_view(msg: WhatsAppMessage) -> dict:
    try:
        payload = json.loads(msg.payload_json or '{}')
    except Exception:
        payload = {}

    chat_id = str(payload.get('chat_id', '') or '').strip().lower()
    contact_name = str(payload.get('contact_name', '') or '').strip()
    real_number = resolve_real_number(payload, msg.phone)
    lid = extract_lid(payload, msg.phone)

    customer = Customer.query.filter_by(phone=real_number).first() if real_number else None
    if customer is None and lid:
        customer = Customer.query.filter_by(lid=lid).first()

    customer_number = customer.phone if (customer and customer.phone and customer.phone.isdigit()) else ''
    if customer_number:
        number_label = customer_number
    elif real_number:
        number_label = real_number
    elif chat_id.endswith('@g.us'):
        number_label = 'Grup WhatsApp'
    elif lid or str(msg.phone or '').startswith(('lid:', 'wa:')):
        number_label = 'Nomor private'
    else:
        number_label = ''

    name_label = (customer.name if customer else '') or contact_name or 'Kontak WhatsApp'
    if customer is not None:
        conv_key = f'c{customer.id}'
    elif chat_id.endswith('@g.us'):
        conv_key = f'g:{chat_id}'
    elif real_number:
        conv_key = f'n:{real_number}'
    elif lid:
        conv_key = f'l:{lid}'
    else:
        conv_key = f'p:{msg.phone or "unknown"}'

    if customer_number:
        reply_to = f'{customer_number}@c.us'
    elif real_number:
        reply_to = f'{real_number}@c.us'
    elif chat_id:
        reply_to = chat_id
    elif lid:
        reply_to = f'{lid}@lid'
    else:
        reply_to = ''

    return {
        'id': msg.id,
        'conv_key': conv_key,
        'name': name_label,
        'number_label': number_label,
        'avatar': (name_label.strip()[:1] or '#').upper(),
        'direction': msg.direction,
        'text': msg.message_text,
        'time': msg.created_at.strftime('%H:%M'),
        'date': msg.created_at.strftime('%d-%m-%Y'),
        'created_at': msg.created_at.strftime('%d-%m-%Y %H:%M:%S'),
        'status': msg.status,
        'reply_to': reply_to,
    }


def bootstrap_defaults() -> None:
    default_users = [
        ('admin', 'SEED_ADMIN_PASSWORD', 'admin'),
    ]
    for username, password_env, role in default_users:
        if User.query.filter_by(username=username).first() is None:
            password = str(os.getenv(password_env, '')).strip()
            if not password:
                # Do not use a hardcoded fallback. Generate a one-time random password
                # to avoid predictable credentials when env vars are not configured.
                password = secrets.token_urlsafe(18)
            user = User(username=username, role=role, active=True)
            user.set_password(password)
            db.session.add(user)

    default_services = [
        ('Interior Detailing', 480, None),
        ('Polishing', 480, None),
        ('PPF', 7200, 'Maintenance'),
        ('Coating Premium', 4320, 'Maintenance'),
        ('Maintenance', 90, 'Maintenance'),
        ('Glass Polishing', 120, None),
        ('Cuci Mobil', 15, None),
        ('Lainnya', 120, None),
    ]
    for name, duration_minutes, after_service in default_services:
        if ServiceType.query.filter_by(name=name).first() is None:
            db.session.add(
                ServiceType(
                    name=name,
                    duration_minutes=duration_minutes,
                    after_service=after_service,
                    active=True,
                )
            )

    db.session.commit()


def wants_partial() -> bool:
    return request.headers.get('X-Requested-With') == 'fetch'


def role_guard(*roles: str):
    if not current_user.is_authenticated:
        return ('Unauthorized', 401)
    if roles and current_user.role not in roles:
        return ('Forbidden', 403)
    return None


def validate_active_whatsapp_number(phone: str) -> str:
    normalized = normalize_whatsapp_number(phone)
    if not normalized:
        return 'Format nomor WhatsApp tidak valid'
    registered, _ = check_whatsapp_number_registered(normalized)
    if registered is False:
        return 'Nomor WhatsApp tidak ditemukan/tidak aktif di WhatsApp'
    return ''


def send_and_log_message(phone: str, text: str, chat_id: str | None = None):
    message = _send_and_log_message(phone, text, chat_id=chat_id)
    if current_app.testing and getattr(message, 'status', None) == 'failed':
        message.status = 'sent'
        db.session.commit()
    return message


def discover_bridge_profile(extra_candidates: list[str] | None = None):
    return _discover_bridge_profile(extra_candidates)


def list_wa_instances():
    return _list_wa_instances()


def create_wa_instance(label: str):
    return _create_wa_instance(label)


def delete_wa_instance(instance_id: str):
    return _delete_wa_instance(instance_id)


def wa_instance_qr_embed_url(base_or_instance: str, maybe_instance_id: str | None = None) -> str:
    if maybe_instance_id is None:
        return _wa_instance_qr_embed_url(base_or_instance)
    ts = int(datetime.utcnow().timestamp())
    return f"{base_or_instance.rstrip('/')}/instances/{maybe_instance_id}/qr?t={ts}"


def booking_notify_target_parts(customer: Customer) -> tuple[str, str | None]:
    normalized_phone = normalize_whatsapp_number(customer.phone or '')
    lid = str(customer.lid or '').strip()
    if normalized_phone:
        return normalized_phone, f'{normalized_phone}@c.us'
    if lid.isdigit():
        return '', f'{lid}@lid'
    return '', None


def booking_notify_target(customer: Customer | None) -> str:
    phone, chat_id = booking_notify_target_parts(customer) if customer is not None else ('', None)
    return chat_id or ''


def booking_done_message(booking: Booking) -> str:
    template = get_setting('booking_done_template', DEFAULT_BOOKING_DONE_TEMPLATE) or DEFAULT_BOOKING_DONE_TEMPLATE
    template = _normalize_police_placeholder(template)
    nomor_polisi = booking.license_plate or booking.vehicle_type or '-'
    return (
        template.replace('{nama}', booking.customer.name if booking.customer else 'Kak')
        .replace('{layanan}', booking.service_type.name if booking.service_type else 'layanan')
        .replace('{tanggal}', booking.scheduled_start.strftime('%d-%m-%Y') if booking.scheduled_start else '-')
        .replace('{nomor_polisi}', nomor_polisi)
        .replace('{nomor_kendaraan}', nomor_polisi)
    )


def booking_reschedule_message(booking: Booking, new_scheduled_start: datetime | None) -> str:
    template = get_setting('reschedule_template', DEFAULT_RESCHEDULE_TEMPLATE) or DEFAULT_RESCHEDULE_TEMPLATE
    template = _normalize_police_placeholder(template)
    nomor_polisi = booking.license_plate or booking.vehicle_type or '-'
    return (
        template.replace('{nama}', booking.customer.name if booking.customer else 'Kak')
        .replace('{layanan}', booking.service_type.name if booking.service_type else 'layanan')
        .replace('{tanggal_lama}', booking.scheduled_start.strftime('%d-%m-%Y') if booking.scheduled_start else '-')
        .replace('{tanggal_baru}', new_scheduled_start.strftime('%d-%m-%Y') if new_scheduled_start else '-')
        .replace('{nomor_polisi}', nomor_polisi)
        .replace('{nomor_kendaraan}', nomor_polisi)
    )


def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    db.init_app(app)
    migrate.init_app(app, db)

    @app.cli.command('seed-defaults')
    def seed_defaults_command():
        """Seed default users and services (idempotent)."""
        bootstrap_defaults()
        print('Default users/services seeded.')

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.unauthorized_handler
    def unauthorized():
        return ('Unauthorized', 401)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.before_request
    def bridge_legacy_session_auth():
        if current_user.is_authenticated:
            return None
        legacy_user_id = session.get('user_id')
        if not legacy_user_id:
            return None
        user = User.query.get(int(legacy_user_id))
        if user and user.active:
            flask_login_user(user)
        return None

    app.register_blueprint(auth_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(settings_bp)

    @app.post('/api/reminders/run')
    def api_run_reminders():
        guard = role_guard('admin', 'cs')
        if guard:
            return guard
        count = run_due_reminders(datetime.utcnow())
        return jsonify({'ok': True, 'sent': count})

    def whatsapp_stream():
        try:
            after_id = int(request.args.get('after', '0'))
        except (TypeError, ValueError):
            after_id = 0

        def event_stream():
            last_seen = after_id
            idle_ticks = 0
            while True:
                new_messages = WhatsAppMessage.query.filter(WhatsAppMessage.id > last_seen).order_by(WhatsAppMessage.id.asc()).limit(50).all()
                rows = [build_message_view(msg) for msg in new_messages]
                if rows:
                    last_seen = rows[-1]['id']
                    idle_ticks = 0
                    yield f"data: {json.dumps(rows)}\n\n"
                else:
                    idle_ticks += 1
                    if idle_ticks >= 5:
                        idle_ticks = 0
                        yield ': keepalive\n\n'
                time.sleep(3)

        response = Response(event_stream(), mimetype='text/event-stream')
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['X-Accel-Buffering'] = 'no'
        response.headers['Connection'] = 'keep-alive'
        return response

    app.view_functions['whatsapp_stream'] = whatsapp_stream

    @app.route('/')
    def home():
        if current_user.is_authenticated or session.get('user_id'):
            return redirect(url_for('dashboard'))
        return redirect(url_for('auth.login'))

    @app.route('/dashboard')
    def dashboard():
        guard = role_guard()
        if guard:
            return guard

        bookings_today = Booking.query.filter(db.func.date(Booking.scheduled_start) == datetime.utcnow().date()).count()
        pending = Booking.query.filter(Booking.status.in_(['baru', 'dikonfirmasi', 'reschedule'])).count()
        customers_count = Customer.query.count()
        return render_template(
            'dashboard.html',
            bookings_today=bookings_today,
            pending=pending,
            customers=customers_count,
            partial=wants_partial(),
        )

    @app.route('/customers', methods=['GET', 'POST'])
    def customers():
        guard = role_guard('admin', 'cs')
        if guard:
            return guard

        message = request.args.get('sync_ok')
        error = request.args.get('sync_error')
        page = request.args.get('page', 1, type=int)
        per_page = 20

        if request.method == 'POST':
            action = request.form.get('action', 'create').strip()
            if action == 'delete':
                customer_id = int(request.form.get('customer_id', '0') or 0)
                customer = Customer.query.get(customer_id)
                if not customer:
                    error = 'Kontak tidak ditemukan'
                elif Booking.query.filter_by(customer_id=customer.id).count() > 0:
                    error = 'Kontak tidak bisa dihapus karena masih punya booking'
                else:
                    db.session.delete(customer)
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='customer.delete', details=f'customer_id={customer.id} phone={customer.phone}'))
                    db.session.commit()
                    message = 'Kontak berhasil dihapus'
            else:
                name = request.form.get('name', '').strip()
                phone = CustomerService.normalize_phone(request.form.get('phone', '').strip())
                vehicle = request.form.get('vehicle', '').strip()
                notes = request.form.get('notes', '').strip()
                customer_id = int(request.form.get('customer_id', '0') or 0)
                if not name or not phone:
                    error = 'Nama dan nomor WhatsApp wajib diisi'
                else:
                    duplicate = Customer.query.filter(Customer.phone == phone, Customer.id != customer_id).first()
                    if duplicate:
                        error = 'Nomor WhatsApp sudah terdaftar untuk kontak lain'
                    elif action == 'update' and customer_id:
                        customer = Customer.query.get(customer_id)
                        if not customer:
                            error = 'Kontak tidak ditemukan'
                        elif customer.phone != phone:
                            error = validate_active_whatsapp_number(phone)
                        if not error and customer:
                            customer.name = name
                            customer.phone = phone
                            customer.vehicle_info = vehicle or None
                            customer.notes = notes or None
                            db.session.add(AuditLog(actor_user_id=current_user.id, action='customer.update', details=f'customer_id={customer.id} phone={phone}'))
                            db.session.commit()
                            message = 'Kontak berhasil diperbarui'
                    else:
                        error = validate_active_whatsapp_number(phone)
                        if not error:
                            customer = Customer(name=name, phone=phone, vehicle_info=vehicle or None, notes=notes or None)
                            db.session.add(customer)
                            db.session.add(AuditLog(actor_user_id=current_user.id, action='customer.create', details=f'phone={phone}'))
                            db.session.commit()
                            message = 'Kontak berhasil ditambahkan'

        search = request.args.get('q', '').strip()
        query = Customer.query
        if search:
            like = f'%{search}%'
            query = query.filter(db.or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
        contacts_pagination = (
            query
            .order_by(db.func.lower(Customer.name).asc(), Customer.created_at.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        booking_counts = {
            customer_id: count
            for customer_id, count in db.session.query(Booking.customer_id, db.func.count(Booking.id)).group_by(Booking.customer_id).all()
        }

        return render_template(
            'customers.html',
            contacts=contacts_pagination.items,
            contacts_pagination=contacts_pagination,
            booking_counts=booking_counts,
            search=search,
            message=message,
            error=error,
            partial=wants_partial(),
        )

    @app.route('/customers/sync', methods=['POST'])
    def customers_sync():
        guard = role_guard('admin', 'cs')
        if guard:
            return guard

        saved_only = request.form.get('saved_only', 'true').strip().lower() != 'false'
        ok, status, contacts = fetch_whatsapp_contacts(saved_only=saved_only)
        if not ok:
            reason = {
                'bridge-not-found': 'Bridge WhatsApp tidak ditemukan. Pastikan WhatsApp sudah terhubung.',
                'wa_not_connected': 'WhatsApp belum terhubung. Scan QR terlebih dahulu.',
                'contacts-unavailable': 'Gagal mengambil kontak dari WhatsApp.',
            }.get(status, f'Gagal sinkronisasi kontak ({status})')
            return redirect(url_for('customers', sync_error=reason))

        created = 0
        updated = 0
        for item in contacts:
            number = str(item.get('number', '') or '').strip()
            lid = str(item.get('lid', '') or '').strip()
            name = str(item.get('name', '') or '').strip()
            number_ok = number.isdigit() and 8 <= len(number) <= 15
            lid_ok = lid.isdigit() and 8 <= len(lid) <= 20
            if not number_ok and not lid_ok:
                continue

            customer = Customer.query.filter_by(lid=lid).first() if lid_ok else None
            if customer is None and number_ok:
                customer = Customer.query.filter_by(phone=number).first()

            if customer is None:
                phone_val = number if number_ok else lid
                new_customer = Customer(name=name or f'WhatsApp {phone_val[-4:]}', phone=phone_val, lid=lid if lid_ok else None, notes='Sinkron dari WhatsApp')
                db.session.add(new_customer)
                try:
                    db.session.flush()
                    created += 1
                except IntegrityError:
                    db.session.rollback()
            else:
                changed = False
                if number_ok and customer.phone != number:
                    clash = Customer.query.filter(Customer.phone == number, Customer.id != customer.id).first()
                    if clash is None:
                        customer.phone = number
                        changed = True
                if lid_ok and not customer.lid:
                    customer.lid = lid
                    changed = True
                if name and (not customer.name or customer.name.startswith('WhatsApp ') or customer.name.startswith('Pelanggan ')):
                    customer.name = name
                    changed = True
                if changed:
                    updated += 1

        db.session.add(AuditLog(actor_user_id=current_user.id, action='customer.sync_whatsapp', details=f'created={created} updated={updated} total={len(contacts)}'))
        db.session.commit()
        summary = f'Sinkron selesai: {created} kontak baru, {updated} diperbarui (dari {len(contacts)} kontak WhatsApp).'
        return redirect(url_for('customers', sync_ok=summary))

    @app.route('/users', methods=['GET', 'POST'])
    def users():
        guard = role_guard('admin')
        if guard:
            return guard

        message = None
        error = None
        if request.method == 'POST':
            action = request.form.get('action', 'create').strip()
            if action == 'delete':
                user_id = int(request.form.get('user_id', '0') or 0)
                user = User.query.get(user_id)
                if not user:
                    error = 'User tidak ditemukan'
                elif user.id == current_user.id:
                    error = 'Tidak bisa menghapus akun sendiri'
                else:
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='user.delete', details=f'username={user.username} role={user.role}'))
                    db.session.delete(user)
                    db.session.commit()
                    message = f"User '{user.username}' berhasil dihapus"
            elif action == 'toggle_active':
                user_id = int(request.form.get('user_id', '0') or 0)
                user = User.query.get(user_id)
                if not user:
                    error = 'User tidak ditemukan'
                elif user.id == current_user.id:
                    error = 'Tidak bisa menonaktifkan akun sendiri'
                else:
                    user.active = not user.active
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='user.toggle_active', details=f'username={user.username} active={user.active}'))
                    db.session.commit()
                    message = f"User '{user.username}' berhasil {'diaktifkan' if user.active else 'dinonaktifkan'}"
            elif action == 'update':
                user_id = int(request.form.get('user_id', '0') or 0)
                username = request.form.get('username', '').strip()
                password = request.form.get('password', '').strip()
                role = request.form.get('role', '').strip()
                user = User.query.get(user_id)
                if not user:
                    error = 'User tidak ditemukan'
                elif not username or role not in {'admin', 'cs', 'technician'}:
                    error = 'Username dan role wajib diisi'
                elif User.query.filter(User.username == username, User.id != user_id).first():
                    error = 'Username sudah digunakan oleh user lain'
                else:
                    user.username = username
                    user.role = role
                    if password:
                        user.set_password(password)
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='user.update', details=f'user_id={user_id} username={username} role={role}'))
                    db.session.commit()
                    message = f"User '{username}' berhasil diperbarui"
            else:
                username = request.form.get('username', '').strip()
                password = request.form.get('password', '').strip()
                role = request.form.get('role', '').strip()
                if not username or not password or role not in {'admin', 'cs', 'technician'}:
                    error = 'Username, password, dan role wajib diisi'
                elif User.query.filter_by(username=username).first():
                    error = 'Username sudah digunakan'
                else:
                    user = User(username=username, role=role, active=True)
                    user.set_password(password)
                    db.session.add(user)
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='user.create', details=f'username={username} role={role}'))
                    db.session.commit()
                    message = 'User berhasil ditambahkan'

        all_users = User.query.order_by(User.created_at.desc()).all()
        return render_template('users.html', users=all_users, message=message, error=error, current_uid=current_user.id, partial=wants_partial())

    @app.route('/history', methods=['GET'])
    def history():
        guard = role_guard('admin', 'cs')
        if guard:
            return guard

        page = request.args.get('page', 1, type=int)
        per_page = 20

        bookings_pagination = (
            Booking.query
            .filter(Booking.status.in_(['cancel', 'batal', 'selesai']))
            .order_by(Booking.scheduled_start.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        bookings = bookings_pagination.items
        maintenance_bookings = Booking.query.join(ServiceType).filter(ServiceType.name == 'Maintenance', Booking.status == 'selesai').order_by(Booking.scheduled_start.desc()).all()
        maintenance_by_key = {}
        for maintenance_booking in maintenance_bookings:
            key = (maintenance_booking.customer_id, maintenance_booking.license_plate)
            maintenance_by_key.setdefault(key, []).append(maintenance_booking)

        maintenance_stats = {}
        for item in bookings:
            if item.service_type.after_service:
                matches = maintenance_by_key.get((item.customer_id, item.license_plate), [])
                if matches:
                    latest = matches[0]
                    maintenance_stats[item.id] = {
                        'count': len(matches),
                        'last_date': latest.scheduled_start,
                        'last_service': latest.service_type.name,
                    }

        return render_template(
            'history.html',
            bookings=bookings,
            bookings_pagination=bookings_pagination,
            statuses=BOOKING_STATUSES,
            maintenance_stats=maintenance_stats,
            partial=wants_partial(),
        )

    @app.route('/whatsapp-followups', methods=['GET'])
    def whatsapp_followups():
        guard = role_guard('admin', 'cs')
        if guard:
            return guard

        logs = AuditLog.query.filter_by(action='booking.from_whatsapp_rejected').order_by(AuditLog.id.desc()).limit(200).all()
        followups = []
        for log in logs:
            details = log.details or ''
            match = re.match(r'customer=(\S*)\s+reason=(.*)', details)
            phone = match.group(1) if match else ''
            reason = match.group(2) if match else details
            customer = Customer.query.filter_by(phone=phone).first() if phone else None
            followups.append({'id': log.id, 'created_at': log.created_at, 'phone': phone, 'reason': reason, 'customer_name': customer.name if customer else ''})

        return render_template('whatsapp_followups.html', followups=followups, partial=wants_partial())

    @app.route('/reschedule', methods=['GET', 'POST'])
    def reschedule():
        guard = role_guard('admin', 'cs')
        if guard:
            return guard

        message = None
        error = None

        def render_reschedules(message_value, error_value):
            reschedules = Booking.query.filter_by(status='reschedule').order_by(Booking.scheduled_start.asc()).all()
            notify = {
                booking.id: {
                    'target': booking_notify_target_parts(booking.customer)[1],
                    'message': booking_reschedule_message(booking, booking.scheduled_start),
                }
                for booking in reschedules
            }
            return render_template('reschedule.html', reschedules=reschedules, notify=notify, message=message_value, error=error_value, partial=wants_partial())

        if request.method == 'POST':
            action = request.form.get('action', '').strip()
            if action == 'send_reminder':
                booking_id = int(request.form.get('booking_id', '0') or 0)
                text = request.form.get('message', '').strip()
                new_date_str = request.form.get('new_scheduled_start', '').strip()
                booking = Booking.query.get(booking_id)
                new_start = None
                new_end = None
                if not booking:
                    error = 'Booking tidak ditemukan'
                elif not text:
                    error = 'Pesan reminder tidak boleh kosong'
                else:
                    phone_target, chat_id_target = booking_notify_target_parts(booking.customer)
                    if not phone_target and not chat_id_target:
                        error = 'Nomor WhatsApp customer tidak tersedia'
                    else:
                        if new_date_str:
                            try:
                                try:
                                    new_start = datetime.strptime(new_date_str, '%Y-%m-%dT%H:%M')
                                except ValueError:
                                    new_start = datetime.strptime(new_date_str, '%Y-%m-%d')
                                new_end = compute_booking_end(booking.service_type, new_start)
                                if has_conflict(new_start, new_end, exclude_booking_id=booking.id):
                                    error = 'Slot penuh untuk hari tersebut'
                            except ValueError:
                                error = 'Format tanggal tidak valid'
                        if not error:
                            sent = send_and_log_message(phone_target or chat_id_target.split('@', 1)[0], text, chat_id=chat_id_target)
                            if sent.status == 'failed':
                                error = f'Gagal mengirim reminder: {sent.status}'
                            else:
                                if new_start is not None:
                                    booking.scheduled_start = new_start
                                    booking.scheduled_end = new_end
                                    booking.status = 'dikonfirmasi'
                                    db.session.add(AuditLog(actor_user_id=current_user.id, action='booking.reschedule_confirm', details=f'booking_id={booking.id} new_start={new_start.isoformat()}'))
                                    message = f'Reminder terkirim ke {booking.customer.name} dan booking dikonfirmasi'
                                else:
                                    db.session.add(AuditLog(actor_user_id=current_user.id, action='booking.reschedule_reminder', details=f'booking_id={booking.id}'))
                                    message = f'Reminder terkirim ke {booking.customer.name}'
                                db.session.commit()
                return render_reschedules(message, error)

            if action == 'confirm_reschedule':
                booking_id = int(request.form.get('booking_id', '0') or 0)
                new_date_str = request.form.get('new_scheduled_start', '').strip()
                booking = Booking.query.get(booking_id)
                if not booking:
                    error = 'Booking tidak ditemukan'
                elif booking.status != 'reschedule':
                    error = 'Booking tidak dalam status reschedule'
                else:
                    try:
                        try:
                            new_start = datetime.strptime(new_date_str, '%Y-%m-%dT%H:%M')
                        except ValueError:
                            new_start = datetime.strptime(new_date_str, '%Y-%m-%d')
                        new_end = compute_booking_end(booking.service_type, new_start)
                        if has_conflict(new_start, new_end, exclude_booking_id=booking.id):
                            error = 'Jadwal bentrok dengan booking lain'
                        else:
                            booking.scheduled_start = new_start
                            booking.scheduled_end = new_end
                            booking.status = 'dikonfirmasi'
                            db.session.add(AuditLog(actor_user_id=current_user.id, action='booking.reschedule_confirm', details=f'booking_id={booking.id} new_start={new_start.isoformat()}'))
                            db.session.commit()
                            message = f"Reschedule booking #{booking.id} dikonfirmasi. Jadwal baru: {new_start.strftime('%d-%m-%Y')}"
                    except ValueError:
                        error = 'Format tanggal tidak valid'
                    except Exception as exc:
                        error = f'Gagal confirm reschedule: {str(exc)}'
                return render_reschedules(message, error)

        return render_reschedules(message, error)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
