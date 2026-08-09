from datetime import datetime

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import AuditLog, Booking, MaintenanceReminder, ServiceType, db
from app.services.booking_engine import compute_booking_end
from app.services.reminders import DEFAULT_APPOINTMENT_REMINDER_TEMPLATE
from app.services.settings_store import get_many, get_setting, set_setting
from app.services.whatsapp import (
    create_wa_instance,
    delete_wa_instance,
    discover_bridge_profile,
    list_wa_instances,
    send_and_log_message,
    wa_instance_qr_embed_url,
)

settings_bp = Blueprint('settings', __name__)

MAINTENANCE_SERVICE_NAME = 'Maintenance'
VALID_AFTER_SERVICE_VALUES = {'', 'Maintenance'}
DEFAULT_BOOKING_DONE_TEMPLATE = (
    'Halo {nama}, kabar baik! Kendaraan Anda untuk layanan *{layanan}* '
    'sudah *selesai* dikerjakan dan siap diambil. Terima kasih 🙏'
)
DEFAULT_RESCHEDULE_TEMPLATE = (
    'Halo {nama}, kami terima permintaan reschedule untuk *{layanan}*. '
    'Jadwal awal: {tanggal_lama} -> Jadwal baru: {tanggal_baru}. '
    'Apakah sudah tepat? Silakan konfirmasi ya.'
)
DEFAULT_MAINTENANCE_REMINDER_TEMPLATE = (
    'Halo {nama}, sudah 6 bulan sejak layanan *{layanan}* kami selesaikan ({tanggal_selesai}). '
    'Kami rekomendasikan maintenance sekarang. Hubungi kami untuk booking ya 😊'
)
DEFAULT_REVIEW_REQUEST_TEMPLATE = (
    'Halo {nama}, terima kasih telah menggunakan layanan *{layanan}* kami! '
    'Bantu kami berkembang dengan memberikan review di Google Maps: {link_review} 🙏'
)

# All message templates that CS/admin can edit from the Template page.
TEMPLATE_DEFAULTS = {
    'booking_done_template': DEFAULT_BOOKING_DONE_TEMPLATE,
    'reschedule_template': DEFAULT_RESCHEDULE_TEMPLATE,
    'appointment_reminder_template': DEFAULT_APPOINTMENT_REMINDER_TEMPLATE,
    'maintenance_reminder_template': DEFAULT_MAINTENANCE_REMINDER_TEMPLATE,
    'review_request_template': DEFAULT_REVIEW_REQUEST_TEMPLATE,
}


def _authorized(*roles: str) -> bool:
    return current_user.is_authenticated and current_user.role in roles


def wants_partial() -> bool:
    return request.headers.get('X-Requested-With') == 'fetch'


@settings_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def manage_settings():
    try:
        if not _authorized('admin'):
            return redirect(url_for('dashboard'))

        message = None
        error = None
        setting_keys = [
            'daily_capacity',
        ]

        if request.method == 'POST':
            action = request.form.get('action', 'save')
            if action == 'service_create':
                name = request.form.get('service_name', '').strip()
                duration_value = request.form.get('service_duration', '').strip()
                duration_unit = request.form.get('service_unit', 'menit').strip()
                after_service = request.form.get('service_after_service', '').strip()
                try:
                    duration_num = float(duration_value)
                    duration_minutes = duration_num * {'menit': 1, 'jam': 60, 'hari': 1440}.get(duration_unit, 1)
                    if not name or len(name) < 3:
                        error = 'Nama layanan harus minimal 3 karakter'
                    elif after_service not in VALID_AFTER_SERVICE_VALUES:
                        error = 'After Service tidak valid'
                    elif ServiceType.query.filter_by(name=name).first():
                        error = 'Layanan dengan nama ini sudah ada'
                    else:
                        db.session.add(ServiceType(name=name, duration_minutes=duration_minutes, active=True, after_service=after_service or None))
                        db.session.add(AuditLog(actor_user_id=current_user.id, action='service.create', details=f'name={name} duration={duration_num}{duration_unit} after_service={after_service or "-"}'))
                        db.session.commit()
                        message = f"Layanan '{name}' berhasil ditambahkan"
                except (ValueError, TypeError):
                    error = 'Durasi harus berupa angka'
            elif action == 'service_update':
                service_id = int(request.form.get('service_id', '0') or 0)
                name = request.form.get('service_name', '').strip()
                duration_value = request.form.get('service_duration', '').strip()
                duration_unit = request.form.get('service_unit', 'menit').strip()
                after_service = request.form.get('service_after_service', '').strip()
                service = ServiceType.query.get(service_id)
                if not service:
                    error = 'Layanan tidak ditemukan'
                else:
                    try:
                        duration_num = float(duration_value)
                        duration_minutes = duration_num * {'menit': 1, 'jam': 60, 'hari': 1440}.get(duration_unit, 1)
                        if not name or len(name) < 3:
                            error = 'Nama layanan harus minimal 3 karakter'
                        elif after_service not in VALID_AFTER_SERVICE_VALUES:
                            error = 'After Service tidak valid'
                        elif ServiceType.query.filter(ServiceType.name == name, ServiceType.id != service_id).first():
                            error = 'Layanan dengan nama ini sudah ada'
                        else:
                            service.name = name
                            service.duration_minutes = duration_minutes
                            service.after_service = after_service or None
                            db.session.add(AuditLog(actor_user_id=current_user.id, action='service.update', details=f'service_id={service_id} name={name} duration={duration_num}{duration_unit} after_service={after_service or "-"}'))
                            db.session.commit()
                            message = f"Layanan '{name}' berhasil diperbarui"
                    except (ValueError, TypeError):
                        error = 'Durasi harus berupa angka'
            elif action == 'service_delete':
                service_id = int(request.form.get('service_id', '0') or 0)
                service = ServiceType.query.get(service_id)
                if not service:
                    error = 'Layanan tidak ditemukan'
                elif Booking.query.filter_by(service_type_id=service_id).count() > 0:
                    error = 'Layanan tidak bisa dihapus karena masih digunakan di booking'
                else:
                    service_name = service.name
                    db.session.delete(service)
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='service.delete', details=f'service_id={service_id} name={service_name}'))
                    db.session.commit()
                    message = f"Layanan '{service_name}' berhasil dihapus"
            elif action == 'service_toggle':
                service_id = int(request.form.get('service_id', '0') or 0)
                service = ServiceType.query.get(service_id)
                if not service:
                    error = 'Layanan tidak ditemukan'
                else:
                    service.active = not service.active
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='service.toggle', details=f'service_id={service_id} active={service.active}'))
                    db.session.commit()
                    message = f"Layanan '{service.name}' berhasil {'diaktifkan' if service.active else 'dinonaktifkan'}"
            elif action == 'save':
                set_setting('public_base_url', request.url_root.strip().rstrip('/'))
                for key in setting_keys:
                    value = request.form.get(key, '').strip()
                    if value:
                        if key == 'daily_capacity':
                            try:
                                int(value)
                            except ValueError:
                                error = 'Daily capacity harus berupa angka bulat'
                                break
                        set_setting(key, value)
                if not error:
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='settings.whatsapp.update', details='bridge-only'))
                    db.session.commit()
                    message = 'Settings berhasil disimpan'
            elif action == 'test_send':
                phone = request.form.get('test_phone', '').strip()
                text = request.form.get('test_message', 'Tes koneksi dari Detailing Ops').strip()
                if not phone:
                    error = 'Nomor tujuan wajib diisi untuk test kirim'
                else:
                    from app import app as app_module

                    sent = app_module.send_and_log_message(phone, text)
                    if sent.status == 'failed':
                        error = 'Gagal kirim. Pastikan bridge QR aktif, API key benar, dan session QR sudah tersambung'
                    else:
                        message = f'Pesan test terkirim dengan status: {sent.status}'
            elif action == 'wa_number_add':
                label = request.form.get('wa_number_label', '').strip()
                if not label:
                    error = 'Nama/label nomor WhatsApp wajib diisi'
                else:
                    from app import app as app_module

                    ok, status, instance = app_module.create_wa_instance(label)
                    if ok and instance:
                        db.session.add(AuditLog(actor_user_id=current_user.id, action='whatsapp.instance.create', details=f"instance_id={instance.get('id')} label={label}"))
                        db.session.commit()
                        message = f"Nomor WhatsApp '{label}' berhasil didaftarkan. Scan QR di bawah untuk menghubungkan."
                    else:
                        error = f'Gagal mendaftarkan nomor WhatsApp: {status}'
            elif action == 'wa_number_delete':
                instance_id = request.form.get('instance_id', '').strip()
                if not instance_id:
                    error = 'instance_id wajib diisi'
                else:
                    from app import app as app_module

                    ok, status = app_module.delete_wa_instance(instance_id)
                    if ok:
                        db.session.add(AuditLog(actor_user_id=current_user.id, action='whatsapp.instance.delete', details=f'instance_id={instance_id}'))
                        db.session.commit()
                        message = 'Nomor WhatsApp berhasil dihapus'
                    else:
                        error = f'Gagal menghapus nomor WhatsApp: {status}'

        settings_map = get_many(setting_keys)
        if not settings_map.get('daily_capacity'):
            settings_map['daily_capacity'] = get_setting('daily_capacity', '4')

        from app import app as app_module

        profile = app_module.discover_bridge_profile([f"http://{request.host.split(':')[0]}:3000"])
        bridge_base = profile.base_url if profile else ''
        bridge_detected = bool(bridge_base)
        qr_url = f"{request.host_url.rstrip('/')}/wa-bridge{profile.qr_path}" if (profile and bridge_base and profile.has_qr) else ''
        qr_embed_url = f"/wa-bridge{profile.qr_path}?t={int(datetime.utcnow().timestamp())}" if (profile and qr_url) else ''
        wa_instances = []
        if bridge_detected:
            ok_instances, _, raw_instances = app_module.list_wa_instances()
            if ok_instances:
                for inst in raw_instances:
                    item = dict(inst)
                    inst_id = str(inst.get('id') or '')
                    item['qr_embed_url'] = app_module.wa_instance_qr_embed_url(inst_id) if (inst_id and inst.get('has_qr')) else ''
                    wa_instances.append(item)

        return render_template(
            'settings.html',
            settings=settings_map,
            services=ServiceType.query.order_by(ServiceType.created_at.desc()).all(),
            message=message,
            error=error,
            webhook_url=f"{request.url_root.strip().rstrip('/')}/api/whatsapp/inbound",
            bridge_base=bridge_base,
            bridge_detected=bridge_detected,
            bridge_auth_required=profile.auth_required if profile else False,
            bridge_connected=profile.connected if profile else False,
            bridge_has_qr=profile.has_qr if profile else False,
            bridge_detected_from=profile.detected_from if profile else '',
            qr_url=qr_url,
            qr_embed_url=qr_embed_url,
            wa_instances=wa_instances,
            partial=wants_partial(),
        )
    except Exception as e:
        current_app.logger.error(f'Error in manage_settings: {e}')
        return redirect(url_for('dashboard'))


@settings_bp.route('/templates', methods=['GET', 'POST'])
@login_required
def manage_templates():
    if not _authorized('admin', 'cs'):
        return redirect(url_for('dashboard'))

    message = None
    error = None
    template_keys = list(TEMPLATE_DEFAULTS.keys())

    if request.method == 'POST':
        for key in template_keys:
            value = request.form.get(key, '').strip()
            if value:
                set_setting(key, value)
        review_url = request.form.get('google_maps_business_url', '').strip()
        if review_url:
            set_setting('google_maps_business_url', review_url)
        db.session.add(AuditLog(actor_user_id=current_user.id, action='settings.templates.update', details='templates'))
        db.session.commit()
        message = 'Template berhasil disimpan'

    settings_map = get_many(template_keys + ['google_maps_business_url'])
    for key, default in TEMPLATE_DEFAULTS.items():
        if not settings_map.get(key):
            settings_map[key] = get_setting(key, default)

    return render_template(
        'templates.html',
        settings=settings_map,
        message=message,
        error=error,
        partial=wants_partial(),
    )



@settings_bp.route('/maintenance', methods=['GET', 'POST'])
@login_required
def maintenance():
    if not _authorized('admin', 'cs'):
        return redirect(url_for('dashboard'))

    message = None
    error = None
    if request.method == 'POST':
        action = request.form.get('action', '').strip()
        if action == 'send_reminder':
            reminder_id = int(request.form.get('reminder_id', '0') or 0)
            reminder = MaintenanceReminder.query.get(reminder_id)
            if not reminder:
                error = 'Maintenance reminder tidak ditemukan'
            else:
                message_text = request.form.get('message', '').strip()
                if not message_text:
                    error = 'Pesan tidak boleh kosong'
                else:
                    from app import app as app_module

                    sent = app_module.send_and_log_message(reminder.customer.phone, message_text)
                    if sent.status == 'failed':
                        error = f'Gagal kirim reminder: {sent.status}'
                    else:
                        reminder.reminder_sent_at = datetime.utcnow()
                        db.session.add(AuditLog(actor_user_id=current_user.id, action='maintenance.reminder_sent', details=f'reminder_id={reminder_id} customer={reminder.customer.phone}'))
                        db.session.commit()
                        message = f'Maintenance reminder terkirim ke {reminder.customer.name}'
        elif action == 'send_review':
            reminder_id = int(request.form.get('reminder_id', '0') or 0)
            reminder = MaintenanceReminder.query.get(reminder_id)
            if not reminder:
                error = 'Maintenance reminder tidak ditemukan'
            else:
                message_text = request.form.get('message', '').strip()
                if not message_text:
                    error = 'Pesan tidak boleh kosong'
                else:
                    from app import app as app_module

                    sent = app_module.send_and_log_message(reminder.customer.phone, message_text)
                    if sent.status == 'failed':
                        error = f'Gagal kirim review request: {sent.status}'
                    else:
                        reminder.review_requested_at = datetime.utcnow()
                        db.session.add(AuditLog(actor_user_id=current_user.id, action='maintenance.review_requested', details=f'reminder_id={reminder_id} customer={reminder.customer.phone}'))
                        db.session.commit()
                        message = f'Review request terkirim ke {reminder.customer.name}'
        elif action == 'book_maintenance':
            reminder_id = int(request.form.get('reminder_id', '0') or 0)
            reminder = MaintenanceReminder.query.get(reminder_id)
            service = ServiceType.query.filter_by(name=MAINTENANCE_SERVICE_NAME).first()
            if not reminder:
                error = 'Maintenance reminder tidak ditemukan'
            elif not service:
                error = f"Layanan '{MAINTENANCE_SERVICE_NAME}' belum tersedia di Settings"
            else:
                schedule_raw = request.form.get('scheduled_start', '').strip()
                try:
                    start_time = datetime.strptime(schedule_raw, '%Y-%m-%d')
                except ValueError:
                    start_time = None
                    error = 'Tanggal booking wajib diisi dengan format yang valid'
                if not error and start_time is not None:
                    original_booking = reminder.booking
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
                        created_by_user_id=current_user.id,
                    )
                    db.session.add(new_booking)
                    db.session.add(AuditLog(actor_user_id=current_user.id, action='maintenance.booking_created', details=f'reminder_id={reminder.id} customer={reminder.customer.phone} service={service.name}'))
                    db.session.delete(reminder)
                    db.session.commit()
                    message = f"Booking '{service.name}' berhasil dibuat untuk {reminder.customer.name}. Atur tanggal jadwalnya di halaman Bookings."

    reminders = MaintenanceReminder.query.join(Booking).order_by(MaintenanceReminder.maintenance_due_at.asc()).all()
    reminder_template = get_setting('maintenance_reminder_template', DEFAULT_MAINTENANCE_REMINDER_TEMPLATE)
    review_template = get_setting('review_request_template', DEFAULT_REVIEW_REQUEST_TEMPLATE)
    review_link = get_setting('google_maps_business_url', '')
    drafts = {}
    for reminder in reminders:
        drafts[reminder.id] = {
            'reminder_message': reminder_template.format(nama=reminder.customer.name, layanan=reminder.service_type, tanggal_selesai=reminder.completed_at.strftime('%d-%m-%Y')),
            'review_message': review_template.format(nama=reminder.customer.name, layanan=reminder.service_type, link_review=review_link),
        }

    return render_template('maintenance.html', reminders=reminders, drafts=drafts, message=message, error=error, now=datetime.utcnow(), partial=wants_partial())
