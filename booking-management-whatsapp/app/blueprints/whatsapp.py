import json
import time
from datetime import datetime, timedelta

from flask import Blueprint, Response, current_app, jsonify, render_template, request, stream_with_context
from flask_login import current_user, login_required

from app.models import AuditLog, Booking, Customer, ServiceType, WhatsAppMessage, db
from app.services.booking_engine import compute_booking_end, has_conflict
from app.services.message_service import MessageService
from app.services.semantic_matcher import get_variant_info, match_package_to_service
from app.services.whatsapp import check_whatsapp_number_registered, log_inbound_message, normalize_whatsapp_number, send_and_log_message

whatsapp_bp = Blueprint('whatsapp', __name__)


def _authorized(*roles: str) -> bool:
    return current_user.is_authenticated and current_user.role in roles


def wants_partial() -> bool:
    return request.headers.get('X-Requested-With') == 'fetch'


def _extract_lid(payload: dict, phone: str) -> str:
    chat_id = str(payload.get('chat_id', '') or '').strip().lower()
    if chat_id.endswith('@lid'):
        return chat_id.split('@', 1)[0]
    if str(phone or '').startswith('lid:'):
        return str(phone).split(':', 1)[1]
    return ''


def _resolve_real_number(payload: dict, phone: str) -> str:
    chat_id = str(payload.get('chat_id', '') or '').strip().lower()
    if chat_id.endswith('@c.us'):
        return normalize_whatsapp_number(chat_id.split('@', 1)[0])
    return normalize_whatsapp_number(payload.get('contact_number') or payload.get('phone') or phone)


def _sync_customer_from_inbound(payload: dict, phone: str) -> None:
    real_number = _resolve_real_number(payload, phone)
    lid = _extract_lid(payload, phone)
    if not real_number and not lid:
        return

    contact_name = str(payload.get('contact_name', '') or '').strip()
    customer = Customer.query.filter_by(lid=lid).first() if lid else None
    if customer is None and real_number:
        customer = Customer.query.filter_by(phone=real_number).first()

    if customer is None:
        if not real_number:
            return
        customer = Customer(
            name=contact_name or f'WhatsApp {real_number[-4:]}',
            phone=real_number,
            lid=lid or None,
            notes='Otomatis dari WhatsApp',
        )
        db.session.add(customer)
        db.session.commit()
        return

    changed = False
    if lid and not customer.lid:
        customer.lid = lid
        changed = True
    if contact_name and (not customer.name or customer.name.startswith('WhatsApp ') or customer.name.startswith('Pelanggan ')):
        customer.name = contact_name
        changed = True
    if changed:
        db.session.commit()


def _validate_active_whatsapp_number(phone: str) -> str:
    normalized = normalize_whatsapp_number(phone)
    if not normalized:
        return 'Format nomor WhatsApp tidak valid'
    registered, _ = check_whatsapp_number_registered(normalized)
    if registered is False:
        return 'Nomor WhatsApp tidak ditemukan/tidak aktif di WhatsApp'
    return ''


def _create_booking_from_form(form: dict, payload: dict) -> Booking | None:
    phone = MessageService.extract_phone_from_form(form) or ''
    name = (form.get('name') or '').strip() or 'Pelanggan WhatsApp'
    vehicle_type = (form.get('vehicle_type') or '').strip()
    if not phone:
        return None

    def reject(reason: str) -> None:
        db.session.add(AuditLog(actor_user_id=None, action='booking.from_whatsapp_rejected', details=f'customer={phone} reason={reason}'))
        db.session.commit()

    if not vehicle_type:
        reject('Jenis kendaraan wajib diisi')
        return None

    customer = Customer.query.filter_by(phone=phone).first()
    if customer is None:
        wa_error = _validate_active_whatsapp_number(phone)
        if wa_error:
            reject(wa_error)
            return None

    if customer is None:
        customer = Customer(
            name=name,
            phone=phone,
            vehicle_info=vehicle_type or None,
            notes=form.get('domicile') or 'Dari form WhatsApp',
        )
        db.session.add(customer)
        db.session.flush()
    else:
        if vehicle_type and not customer.vehicle_info:
            customer.vehicle_info = vehicle_type
        if name and (not customer.name or customer.name.startswith('WhatsApp ') or customer.name.startswith('Pelanggan ')):
            customer.name = name

    package = (form.get('package') or 'Paket WhatsApp').strip()
    all_active_services = ServiceType.query.filter_by(active=True).all()
    service = match_package_to_service(package, all_active_services)
    if service is None:
        service = ServiceType.query.filter_by(name='Lainnya').first()
        if service is None:
            service = ServiceType(name='Lainnya', duration_minutes=240, active=True)
            db.session.add(service)
            db.session.flush()

    start_time = MessageService.parse_date(form.get('schedule_text', '')) or datetime.utcnow()
    end_time = compute_booking_end(service, start_time)

    duplicate = (
        Booking.query.filter_by(customer_id=customer.id, service_type_id=service.id)
        .filter(Booking.created_at >= datetime.utcnow() - timedelta(minutes=30))
        .first()
    )
    if duplicate:
        db.session.commit()
        return duplicate

    if has_conflict(start_time, end_time):
        reject('Slot penuh untuk hari tersebut')
        return None

    detail_lines = ['Booking dari WhatsApp']
    variant_info = get_variant_info(package, all_active_services)
    package_display = f'Paket: {package}'
    if variant_info:
        package_display += f' (varian: {variant_info})'
    detail_lines.append(package_display)

    label_map = [
        ('vehicle_type', 'Mobil'),
        ('license_plate', 'Nomor Polisi'),
        ('domicile', 'Domisili'),
        ('outlet', 'Outlet'),
        ('data_from', 'Data From'),
        ('schedule_text', 'Tanggal masuk'),
        ('price_normal', 'Harga Normal'),
        ('price_disc', 'Harga Disc'),
        ('price_nett', 'Harga Nett'),
    ]
    for key, label in label_map:
        value = (form.get(key) or '').strip()
        if value:
            detail_lines.append(f'{label}: {value}')

    booking = Booking(
        customer_id=customer.id,
        service_type_id=service.id,
        scheduled_start=start_time,
        scheduled_end=end_time,
        status='dikonfirmasi',
        source='whatsapp',
        notes='\n'.join(detail_lines),
        other_info=package,
        vehicle_type=(form.get('vehicle_type') or '').strip(),
        license_plate=(form.get('license_plate') or '').strip(),
    )
    db.session.add(booking)
    db.session.add(AuditLog(actor_user_id=None, action='booking.from_whatsapp', details=f'customer={phone} package={package}'))
    db.session.commit()
    return booking


def build_message_view(msg: WhatsAppMessage) -> dict:
    try:
        payload = json.loads(msg.payload_json or '{}')
    except Exception:
        payload = {}

    chat_id = str(payload.get('chat_id', '') or '').strip().lower()
    contact_name = str(payload.get('contact_name', '') or '').strip()
    real_number = _resolve_real_number(payload, msg.phone)
    lid = _extract_lid(payload, msg.phone)

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

    reply_phone = customer_number or real_number or ''
    if reply_phone:
        reply_to = f'{reply_phone}@c.us'
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


@whatsapp_bp.route('/inbox')
@login_required
def inbox():
    try:
        if not _authorized('admin', 'cs'):
            return render_template('inbox.html', conversations=[], last_id=0, partial=wants_partial())

        messages = WhatsAppMessage.query.order_by(WhatsAppMessage.id.desc()).limit(500).all()
        messages.reverse()
        conversations = {}
        for msg in messages:
            view = build_message_view(msg)
            key = view['conv_key']
            conversation = conversations.get(key)
            if conversation is None:
                conversation = {
                    'key': key,
                    'name': view['name'],
                    'number_label': view['number_label'],
                    'avatar': view['avatar'],
                    'messages': [],
                    'last_text': '',
                    'last_time': '',
                    'last_direction': 'inbound',
                    'last_id': 0,
                    'reply_to': '',
                }
                conversations[key] = conversation
            conversation['messages'].append(view)
            conversation['name'] = view['name']
            conversation['number_label'] = view['number_label']
            conversation['avatar'] = view['avatar']
            conversation['last_text'] = view['text']
            conversation['last_time'] = view['time']
            conversation['last_direction'] = view['direction']
            conversation['last_id'] = view['id']
            if view['reply_to']:
                conversation['reply_to'] = view['reply_to']

        conversation_list = sorted(conversations.values(), key=lambda item: item['last_id'], reverse=True)
        return render_template('inbox.html', conversations=conversation_list, last_id=messages[-1].id if messages else 0, partial=wants_partial())
    except Exception as e:
        current_app.logger.error(f'Error in inbox: {e}')
        return 'Error loading inbox', 500


@whatsapp_bp.route('/api/whatsapp/stream')
@login_required
def stream():
    if not _authorized('admin', 'cs'):
        return Response(': unauthorized\n\n', mimetype='text/event-stream')

    try:
        after_id = int(request.args.get('after', '0'))
    except (TypeError, ValueError):
        after_id = 0

    @stream_with_context
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


@whatsapp_bp.post('/api/whatsapp/send')
@login_required
def send_message():
    if not _authorized('admin', 'cs'):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 403

    data = request.get_json(silent=True) or {}
    reply_to = str(data.get('reply_to', '') or '').strip()
    text = str(data.get('text', '') or '').strip()
    if not text:
        return jsonify({'ok': False, 'error': 'text is required'}), 400
    if not reply_to:
        return jsonify({'ok': False, 'error': 'reply target is required'}), 400

    chat_id = reply_to if '@' in reply_to else None
    phone = reply_to.split('@', 1)[0]
    message = send_and_log_message(phone, text, chat_id=chat_id)
    view = build_message_view(message)
    return jsonify({'ok': message.status != 'failed', 'status': message.status, 'message': view})


@whatsapp_bp.post('/api/whatsapp/inbound')
def whatsapp_inbound():
    payload = request.get_json(silent=True) or {}
    phone = str(payload.get('phone', '')).strip()
    text = str(payload.get('text', '')).strip()
    from_me = bool(payload.get('from_me', False))
    if not phone:
        return jsonify({'ok': False, 'error': 'phone is required'}), 400

    if from_me:
        recent = (
            WhatsAppMessage.query.filter(WhatsAppMessage.direction == 'outbound')
            .filter(WhatsAppMessage.message_text == text)
            .filter(WhatsAppMessage.created_at >= datetime.utcnow() - timedelta(seconds=120))
            .first()
        )
        if recent:
            return jsonify({'ok': True, 'status': 'duplicate_skipped'})

    log_inbound_message(phone, text, payload=payload, direction='outbound' if from_me else 'inbound')

    if not from_me:
        _sync_customer_from_inbound(payload, phone)
        form = MessageService.parse_booking_form(text)
        if form:
            from app import app as app_module
            try:
                booking = app_module.create_booking_from_form(form, payload)
                return jsonify({'ok': True, 'status': 'booking_created' if booking else 'booking_rejected'})
            except Exception:
                current_app.logger.exception('Inbound booking form processing failed')
                return jsonify({'ok': True, 'status': 'booking_error'})

    return jsonify({'ok': True, 'status': 'logged'})
