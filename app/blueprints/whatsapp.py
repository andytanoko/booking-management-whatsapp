import json
import hashlib
import hmac
import time
from datetime import datetime, timedelta

from flask import Blueprint, Response, current_app, jsonify, render_template, request, stream_with_context
from flask_login import current_user, login_required

from app.models import AuditLog, Booking, Customer, ServiceType, WhatsAppMessage, db
from app.services.booking_engine import compute_booking_end, has_conflict
from app.services.customer_service import CustomerService
from app.services.message_service import MessageService
from app.services.semantic_matcher import get_variant_info, match_package_to_service
from app.services.whatsapp import (
    check_whatsapp_number_registered,
    fetch_session_qr_png,
    log_inbound_message,
    normalize_whatsapp_number,
    openwa_webhook_secret,
    send_and_log_message,
)

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
    contact_name = str(payload.get('contact_name', '') or '').strip()
    _, outcome = CustomerService.sync_from_whatsapp(
        number=real_number,
        lid=lid,
        contact_name=contact_name,
        notes='Otomatis dari WhatsApp',
    )
    if outcome in ('created', 'updated'):
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
        if name and CustomerService.is_placeholder_name(customer.name):
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


@whatsapp_bp.route('/whatsapp/qr/<instance_id>')
@login_required
def whatsapp_qr(instance_id: str):
    """Serve the gateway's linking QR as a PNG, behind an admin login.

    The gateway's own QR endpoint requires an X-API-Key header that a browser
    cannot attach to an <img> tag. Fetching it here keeps the key server-side and
    keeps the QR itself off the public internet: anyone who can read a live
    linking QR can attach their own device to the WhatsApp account.
    """
    if not _authorized('admin'):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    ok, status, png = fetch_session_qr_png(instance_id)
    if not ok or not png:
        # 404 keeps the <img> simply not rendering while linking isn't pending.
        code = 404 if status.startswith('qr-') else 502
        return jsonify({'ok': False, 'error': status}), code

    response = Response(png, mimetype='image/png')
    response.headers['Cache-Control'] = 'no-store'
    return response


# Message events we turn into inbox rows. Everything else the gateway sends
# (acks, session lifecycle, presence, calls) is acknowledged and logged only.
_OPENWA_MESSAGE_EVENTS = ('message.received', 'message.sent')


def _verify_openwa_signature(raw_body: bytes) -> tuple[bool, str]:
    """Verify OpenWA's HMAC over the raw request body.

    This endpoint is reachable from the internet and it can create bookings and
    customers, so an unsigned request must never be trusted. Fails closed: a
    missing secret is a configuration error, not a reason to accept anything.
    """
    secret = openwa_webhook_secret()
    if not secret:
        return False, 'webhook-secret-not-configured'

    provided = str(request.headers.get('X-OpenWA-Signature', '') or '').strip()
    if not provided:
        return False, 'signature-missing'

    expected = 'sha256=' + hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        return False, 'signature-mismatch'
    return True, 'ok'


def _flatten_openwa_message(envelope: dict) -> dict | None:
    """Map an OpenWA message event onto the flat payload this app already reads.

    Returns None for anything that should not reach the inbox (groups, channels,
    status broadcasts). The `lid:` / `wa:` phone prefixes are preserved because
    _extract_lid() and build_message_view() parse them.
    """
    data = envelope.get('data')
    if not isinstance(data, dict):
        return None

    chat_id = str(data.get('chatId') or data.get('from') or '').strip()
    kind = str(data.get('kind') or '').strip()

    # Only 1:1 conversations belong in the CS inbox.
    if data.get('isGroup') or data.get('isStatusBroadcast') or chat_id.endswith('@g.us'):
        return None
    if kind and kind != 'individual':
        return None

    contact = data.get('contact') if isinstance(data.get('contact'), dict) else {}
    # senderPhone is the authoritative number behind an @lid sender, supplied by
    # the gateway when RESOLVE_LID_TO_PHONE is enabled.
    sender_phone = normalize_whatsapp_number(data.get('senderPhone') or '')
    contact_number = normalize_whatsapp_number(contact.get('number') or '') or sender_phone

    phone = ''
    if chat_id.endswith('@c.us'):
        phone = normalize_whatsapp_number(chat_id.split('@', 1)[0])
    if not phone:
        phone = sender_phone or contact_number
    if not phone:
        # Never drop a message for lack of an identity; fall back to a token the
        # inbox knows how to label.
        user = chat_id.split('@', 1)[0]
        if chat_id.endswith('@lid'):
            phone = f'lid:{user}'
        elif user:
            phone = f'wa:{user}'
        else:
            phone = 'wa:unknown'

    return {
        'phone': phone,
        'text': str(data.get('body') or '').strip(),
        'from_me': bool(data.get('fromMe')),
        'chat_id': chat_id or None,
        'contact_name': str(contact.get('name') or contact.get('pushName') or '').strip(),
        'contact_number': contact_number,
        'is_group': False,
        'source': 'openwa',
        'event': str(envelope.get('event') or ''),
        'message_id': data.get('id'),
        'timestamp': data.get('timestamp'),
        'session_id': envelope.get('sessionId'),
        'instance_id': envelope.get('sessionId'),
        'idempotency_key': envelope.get('idempotencyKey'),
        'is_lid_sender': bool(data.get('isLidSender')),
    }


@whatsapp_bp.post('/api/whatsapp/inbound')
def whatsapp_inbound():
    # Read the raw body before parsing: the HMAC covers the exact bytes sent.
    raw_body = request.get_data(cache=True) or b''

    signed, reason = _verify_openwa_signature(raw_body)
    if not signed:
        if reason == 'webhook-secret-not-configured':
            current_app.logger.error(
                'Inbound webhook rejected: OPENWA_WEBHOOK_SECRET is not set, so deliveries '
                'cannot be authenticated. Set it on both the app and the gateway webhook.'
            )
            return jsonify({'ok': False, 'error': reason}), 503
        current_app.logger.warning(
            'Inbound webhook rejected (%s) from %s', reason, request.remote_addr,
        )
        return jsonify({'ok': False, 'error': reason}), 401

    envelope = request.get_json(silent=True) or {}

    # OpenWA wraps events as {event, sessionId, data, ...}. Anything without that
    # shape is treated as an already-flat payload.
    if isinstance(envelope.get('data'), dict) and envelope.get('event'):
        event = str(envelope.get('event') or '')
        if event not in _OPENWA_MESSAGE_EVENTS:
            # Acknowledge so the gateway doesn't retry, but surface the ones that
            # explain an outage: a restriction or a reconnect loop is exactly the
            # failure that was previously invisible.
            if event.startswith('session.'):
                current_app.logger.warning(
                    'OpenWA session event %s: %s', event, envelope.get('data'),
                )
            return jsonify({'ok': True, 'status': 'ignored', 'event': event})

        payload = _flatten_openwa_message(envelope)
        if payload is None:
            return jsonify({'ok': True, 'status': 'filtered'})
    else:
        payload = envelope

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
