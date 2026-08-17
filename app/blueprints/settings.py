from datetime import datetime

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import Booking, MaintenanceReminder, ServiceType, db
from app.services.audit_service import AuditService
from app.services.maintenance_service import MaintenanceService
from app.services.reminders import DEFAULT_APPOINTMENT_REMINDER_TEMPLATE
from app.services.service_type_service import ServiceTypeService
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

DEFAULT_BOOKING_DONE_TEMPLATE = (
    'Halo {nama}, kabar baik! Kendaraan Anda untuk layanan *{layanan}* '
    'sudah *selesai* dikerjakan dan siap diambil. Nomor polisi: *{nomor_polisi}*. Terima kasih 🙏'
)
DEFAULT_RESCHEDULE_TEMPLATE = (
    'Halo {nama}, kami terima permintaan reschedule untuk *{layanan}*. '
    'Jadwal awal: {tanggal_lama} -> Jadwal baru: {tanggal_baru}. '
    'Nomor polisi: *{nomor_polisi}*. Apakah sudah tepat? Silakan konfirmasi ya.'
)
DEFAULT_MAINTENANCE_REMINDER_TEMPLATE = (
    'Halo {nama}, sudah 6 bulan sejak layanan *{layanan}* kami selesaikan ({tanggal_selesai}). '
    'Nomor polisi: *{nomor_polisi}*. Kami rekomendasikan maintenance sekarang. Hubungi kami untuk booking ya 😊'
)
DEFAULT_REVIEW_REQUEST_TEMPLATE = (
    'Halo {nama}, terima kasih telah menggunakan layanan *{layanan}* kami! '
    'Nomor polisi: *{nomor_polisi}*. Bantu kami berkembang dengan memberikan review di Google Maps: {link_review} 🙏'
)

# All message templates that CS/admin can edit from the Template page.
TEMPLATE_DEFAULTS = {
    'booking_done_template': DEFAULT_BOOKING_DONE_TEMPLATE,
    'reschedule_template': DEFAULT_RESCHEDULE_TEMPLATE,
    'appointment_reminder_template': DEFAULT_APPOINTMENT_REMINDER_TEMPLATE,
    'maintenance_reminder_template': DEFAULT_MAINTENANCE_REMINDER_TEMPLATE,
    'review_request_template': DEFAULT_REVIEW_REQUEST_TEMPLATE,
}

TEMPLATE_REQUIRED_PLACEHOLDERS = {
    key: {'{nomor_polisi}'} for key in TEMPLATE_DEFAULTS.keys()
}


def _booking_police_number(booking: Booking | None) -> str:
    if booking and booking.license_plate:
        return booking.license_plate
    if booking and booking.vehicle_type:
        return booking.vehicle_type
    return '-'


def _ensure_police_placeholder(template: str) -> str:
    normalized = (template or '').replace('{nomor_kendaraan}', '{nomor_polisi}')
    if '{nomor_polisi}' in normalized:
        return normalized
    return f"{normalized.rstrip()} Nomor polisi: *{{nomor_polisi}}*."


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
                message, error = ServiceTypeService.create(
                    request.form.get('service_name', ''),
                    request.form.get('service_duration', ''),
                    request.form.get('service_unit', 'menit'),
                    request.form.get('service_after_service', ''),
                    actor_id=current_user.id,
                )
            elif action == 'service_update':
                message, error = ServiceTypeService.update(
                    int(request.form.get('service_id', '0') or 0),
                    request.form.get('service_name', ''),
                    request.form.get('service_duration', ''),
                    request.form.get('service_unit', 'menit'),
                    request.form.get('service_after_service', ''),
                    actor_id=current_user.id,
                )
            elif action == 'service_delete':
                message, error = ServiceTypeService.delete(
                    int(request.form.get('service_id', '0') or 0),
                    actor_id=current_user.id,
                )
            elif action == 'service_toggle':
                message, error = ServiceTypeService.toggle(
                    int(request.form.get('service_id', '0') or 0),
                    actor_id=current_user.id,
                )
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
                    AuditService.log('settings.whatsapp.update', actor_id=current_user.id, details='bridge-only')
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
                        # Report the reason the gateway actually gave, and match
                        # the advice to it. A generic "check the API key" hint is
                        # actively misleading when the session simply isn't linked.
                        reason = str(getattr(sent, 'send_error', '') or '').strip()
                        if 'wa_not_connected' in reason or 'not connected' in reason:
                            error = (
                                'Gagal kirim: nomor WhatsApp belum tersambung. Jalankan sesi lalu '
                                'scan QR di tabel "Nomor WhatsApp Terdaftar" sampai statusnya "Terhubung".'
                            )
                        elif 'bridge-not-found' in reason or 'unreachable' in reason or 'not-configured' in reason:
                            error = (
                                'Gagal kirim: gateway WhatsApp tidak bisa dihubungi. Periksa container '
                                f'`openwa` (docker compose ps). Detail: {reason}'
                            )
                        elif 'number_not_on_whatsapp' in reason or 'not_on_whatsapp' in reason:
                            error = f'Gagal kirim: nomor {phone} tidak terdaftar di WhatsApp.'
                        elif 'invalid-phone' in reason:
                            error = f'Gagal kirim: format nomor {phone} tidak valid (gunakan 62...).'
                        elif reason:
                            error = f'Gagal kirim: {reason}'
                        else:
                            error = 'Gagal kirim (tidak ada detail dari gateway).'
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
                        AuditService.log('whatsapp.instance.create', actor_id=current_user.id, details=f"instance_id={instance.get('id')} label={label}")
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
                        AuditService.log('whatsapp.instance.delete', actor_id=current_user.id, details=f'instance_id={instance_id}')
                        db.session.commit()
                        message = 'Nomor WhatsApp berhasil dihapus'
                    else:
                        error = f'Gagal menghapus nomor WhatsApp: {status}'
            elif action == 'wa_number_start':
                # Creating a session does not connect it. Starting is what boots
                # the engine and produces a QR - and it is also a linking
                # handshake with WhatsApp, which is why it is an explicit action
                # rather than something that happens on its own.
                instance_id = request.form.get('instance_id', '').strip() or 'default'
                from app import app as app_module

                ok, status = app_module.start_wa_instance(instance_id)
                if ok:
                    AuditService.log('whatsapp.instance.start', actor_id=current_user.id, details=f'instance_id={instance_id}')
                    db.session.commit()
                    message = (
                        'Sesi WhatsApp sedang dijalankan. Tunggu beberapa saat, '
                        'lalu QR akan muncul di tabel di bawah (halaman menyegarkan sendiri).'
                    )
                elif 'rate' in status.lower() or '429' in status:
                    error = (
                        'WhatsApp menolak permintaan tautan karena terlalu banyak percobaan '
                        f'(rate-overlimit / 429): {status}. Tunggu 48-72 jam tanpa mencoba lagi, '
                        'lalu coba sekali saja.'
                    )
                else:
                    error = f'Gagal menjalankan sesi WhatsApp: {status}'
            elif action == 'wa_number_pair':
                instance_id = request.form.get('instance_id', '').strip() or 'default'
                phone = request.form.get('pair_phone', '').strip()
                if not phone:
                    error = 'Nomor WhatsApp wajib diisi untuk mendapatkan kode pairing'
                else:
                    from app import app as app_module

                    ok, status, pairing_code = app_module.request_wa_pairing_code(phone, instance_id)
                    if ok and pairing_code:
                        AuditService.log('whatsapp.instance.pair', actor_id=current_user.id, details=f'instance_id={instance_id} phone={phone}')
                        db.session.commit()
                        message = f"Kode pairing untuk {phone}: {pairing_code}. Buka WhatsApp > Perangkat tertaut > Tautkan dengan nomor telepon, lalu masukkan kode ini."
                    elif 'rate_limited' in status or 'rate-overlimit' in status:
                        error = (
                            'WhatsApp menolak permintaan tautan karena terlalu banyak percobaan '
                            f'untuk nomor {phone} (rate-overlimit / 429). Tunggu beberapa jam '
                            'sebelum mencoba lagi, lalu coba sekali saja.'
                        )
                    else:
                        error = f'Gagal membuat kode pairing: {status}'

        settings_map = get_many(setting_keys)
        if not settings_map.get('daily_capacity'):
            settings_map['daily_capacity'] = get_setting('daily_capacity', '4')

        from app import app as app_module

        profile = app_module.discover_bridge_profile([f"http://{request.host.split(':')[0]}:3000"])
        bridge_base = profile.base_url if profile else ''
        bridge_detected = bool(bridge_base)
        # The QR is served by this app's own authenticated route now, not proxied
        # straight through to the gateway, so there is no /wa-bridge prefix.
        if profile and bridge_base and profile.has_qr:
            qr_embed_url = app_module.wa_instance_qr_embed_url(profile.instance_id)
            qr_url = f"{request.host_url.rstrip('/')}{qr_embed_url}"
        else:
            qr_url = ''
            qr_embed_url = ''
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
        has_change = False
        for key in template_keys:
            if key not in request.form:
                continue
            value = request.form.get(key, '').strip()
            if value:
                missing = [ph for ph in TEMPLATE_REQUIRED_PLACEHOLDERS.get(key, set()) if ph not in value]
                if missing:
                    error = f"Template harus menyertakan placeholder: {', '.join(missing)}"
                    break
                value = _ensure_police_placeholder(value)
                set_setting(key, value)
                has_change = True
        if not error:
            review_url = request.form.get('google_maps_business_url', '').strip()
            if review_url:
                set_setting('google_maps_business_url', review_url)
                has_change = True
            if has_change:
                AuditService.log('settings.templates.update', actor_id=current_user.id, details='templates')
                db.session.commit()
                message = 'Template berhasil disimpan'
            else:
                error = 'Tidak ada perubahan template yang disimpan'

    settings_map = get_many(template_keys + ['google_maps_business_url'])
    for key, default in TEMPLATE_DEFAULTS.items():
        current_value = settings_map.get(key)
        if not current_value:
            current_value = get_setting(key, default)
        settings_map[key] = _ensure_police_placeholder(current_value)

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
            message, error = MaintenanceService.send_reminder(
                reminder_id, request.form.get('message', ''), actor_id=current_user.id,
            )
        elif action == 'send_review':
            reminder_id = int(request.form.get('reminder_id', '0') or 0)
            message, error = MaintenanceService.send_review(
                reminder_id, request.form.get('message', ''), actor_id=current_user.id,
            )
        elif action == 'book_maintenance':
            reminder_id = int(request.form.get('reminder_id', '0') or 0)
            message, error = MaintenanceService.book_maintenance(
                reminder_id, request.form.get('scheduled_start', ''), actor_id=current_user.id,
            )

    reminders = MaintenanceReminder.query.join(Booking).order_by(MaintenanceReminder.maintenance_due_at.asc()).all()
    reminder_template = get_setting('maintenance_reminder_template', DEFAULT_MAINTENANCE_REMINDER_TEMPLATE)
    review_template = get_setting('review_request_template', DEFAULT_REVIEW_REQUEST_TEMPLATE)
    reminder_template = _ensure_police_placeholder(reminder_template)
    review_template = _ensure_police_placeholder(review_template)
    review_link = get_setting('google_maps_business_url', '')
    drafts = {}
    for reminder in reminders:
        nomor_polisi = _booking_police_number(reminder.booking)
        drafts[reminder.id] = {
            'reminder_message': reminder_template.format(nama=reminder.customer.name, layanan=reminder.service_type, tanggal_selesai=reminder.completed_at.strftime('%d-%m-%Y'), nomor_polisi=nomor_polisi, nomor_kendaraan=nomor_polisi),
            'review_message': review_template.format(nama=reminder.customer.name, layanan=reminder.service_type, link_review=review_link, nomor_polisi=nomor_polisi, nomor_kendaraan=nomor_polisi),
        }

    return render_template('maintenance.html', reminders=reminders, drafts=drafts, message=message, error=error, now=datetime.utcnow(), partial=wants_partial())
