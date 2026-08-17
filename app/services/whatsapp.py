"""WhatsApp integration, backed by a self-hosted OpenWA gateway.

Replaces the previous custom Node bridge (tools/wa-real-bridge). The public
function names and signatures here are deliberately unchanged so app.py, the
settings blueprint and the templates keep working without edits.

Two things about OpenWA shape the code below:

1. Paths address a session by UUID, not by name. `GET /api/sessions/default`
   fails with "uuid is expected". Config therefore stores a human-readable
   session NAME and this module resolves it to a UUID at runtime (cached), so a
   recreated session doesn't require a config change.

2. Every endpoint needs an `X-API-Key` header. A browser cannot attach that to
   an <img> tag, so the linking QR is fetched here, server-side, and re-served by
   an authenticated Flask route. That also avoids re-creating the hole the old
   bridge had, where the QR was reachable unauthenticated over the internet and
   anyone who polled it could link their own device.
"""

from __future__ import annotations

import base64
import json
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime
from urllib import error, request

from flask import current_app

from app.models import WhatsAppMessage, db
from app.services.db_ops import safe_commit
from app.services.settings_store import get_setting

# OpenWA session lifecycle. `ready` is the only state that can send.
STATUS_READY = 'ready'
STATUS_QR_READY = 'qr_ready'
KNOWN_STATUSES = (
    'created', 'initializing', 'qr_ready', 'authenticating',
    'ready', 'disconnected', 'action_required', 'failed',
)

# name -> uuid. Cleared whenever a lookup fails so a recreated session re-resolves.
_SESSION_UUID_CACHE: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _cfg(setting_key: str, env_key: str, default: str = '') -> str:
    """Settings table first (runtime-editable), then environment, then default."""
    try:
        value = str(get_setting(setting_key, '') or '').strip()
        if value:
            return value
    except Exception:
        # Called outside an app/DB context (e.g. at import time) - fall through.
        pass
    return str(os.getenv(env_key, '') or default).strip()


def openwa_base_url() -> str:
    return _cfg('openwa_base_url', 'OPENWA_BASE_URL', 'http://openwa:2785').rstrip('/')


def openwa_api_key() -> str:
    return _cfg('openwa_api_key', 'OPENWA_API_KEY')


def openwa_session_name() -> str:
    return _cfg('openwa_session_id', 'OPENWA_SESSION_ID', 'default')


def openwa_webhook_secret() -> str:
    """Shared secret for verifying X-OpenWA-Signature on inbound deliveries."""
    return _cfg('openwa_webhook_secret', 'OPENWA_WEBHOOK_SECRET')


def normalize_whatsapp_number(phone: str) -> str:
    """Normalize a WhatsApp phone identifier to digits only."""
    digits = re.sub(r"\D", "", str(phone or ""))
    return digits if 8 <= len(digits) <= 15 else ""


# ---------------------------------------------------------------------------
# Low-level HTTP
# ---------------------------------------------------------------------------

def _openwa_request(
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 10.0,
) -> tuple[int, object]:
    """Call OpenWA. Returns (status_code, parsed_body).

    status_code 0 means the gateway was unreachable. The body is parsed JSON when
    possible, otherwise the raw text, so callers can read OpenWA's `message`
    field on errors.
    """
    base = openwa_base_url()
    key = openwa_api_key()
    if not base or not key:
        return 0, {'message': 'openwa-not-configured'}

    url = f"{base}{path if path.startswith('/') else '/' + path}"
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = request.Request(url, data=data, method=method)
    req.add_header('X-API-Key', key)
    if data is not None:
        req.add_header('Content-Type', 'application/json')

    def _parse(raw: str) -> object:
        raw = (raw or '').strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.status, _parse(response.read().decode('utf-8', errors='ignore'))
    except error.HTTPError as exc:
        try:
            return exc.code, _parse(exc.read().decode('utf-8', errors='ignore'))
        except Exception:
            return exc.code, {}
    except Exception as exc:
        try:
            current_app.logger.warning('OpenWA unreachable at %s: %s', url, exc)
        except Exception:
            pass
        return 0, {'message': 'openwa-unreachable'}


def _err(payload: object, fallback: str) -> str:
    """Pull OpenWA's error text out of a response body."""
    if isinstance(payload, dict):
        for field in ('message', 'error'):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list) and value:
                return '; '.join(str(v) for v in value)
    if isinstance(payload, str) and payload.strip():
        return payload.strip()[:200]
    return fallback


# ---------------------------------------------------------------------------
# Session resolution
# ---------------------------------------------------------------------------

def list_openwa_sessions() -> list[dict]:
    status, body = _openwa_request('GET', '/api/sessions', timeout=5.0)
    if status == 200 and isinstance(body, list):
        return [s for s in body if isinstance(s, dict)]
    return []


def resolve_session_uuid(name: str | None = None, refresh: bool = False) -> str:
    """Map a session name to its UUID, which is what the API paths require."""
    target = (name or openwa_session_name()).strip()
    if not target:
        return ''

    # Already a UUID? Use it as-is.
    if re.fullmatch(r'[0-9a-fA-F-]{36}', target):
        return target

    if not refresh:
        cached = _SESSION_UUID_CACHE.get(target)
        if cached:
            return cached

    for session in list_openwa_sessions():
        if str(session.get('name') or '') == target:
            uuid = str(session.get('id') or '')
            if uuid:
                _SESSION_UUID_CACHE[target] = uuid
                return uuid

    _SESSION_UUID_CACHE.pop(target, None)
    return ''


def ensure_session(name: str | None = None) -> str:
    """Return the session UUID, creating the session if it doesn't exist yet.

    Creating does NOT start it: no WhatsApp connection or linking handshake
    happens here.
    """
    target = (name or openwa_session_name()).strip()
    if not target:
        return ''

    uuid = resolve_session_uuid(target)
    if uuid:
        return uuid

    status, body = _openwa_request('POST', '/api/sessions', {'name': target}, timeout=15.0)
    if status in (200, 201) and isinstance(body, dict):
        uuid = str(body.get('id') or '')
        if uuid:
            _SESSION_UUID_CACHE[target] = uuid
            return uuid
    return resolve_session_uuid(target, refresh=True)


def get_session_state(name: str | None = None) -> dict | None:
    """Fetch one session's record, or None if unreachable/missing."""
    uuid = resolve_session_uuid(name)
    if not uuid:
        return None
    status, body = _openwa_request('GET', f'/api/sessions/{uuid}', timeout=5.0)
    if status == 200 and isinstance(body, dict):
        return body
    if status == 404:
        _SESSION_UUID_CACHE.pop((name or openwa_session_name()).strip(), None)
    return None


# ---------------------------------------------------------------------------
# Gateway profile (kept for the settings page, which renders these fields)
# ---------------------------------------------------------------------------

class BridgeProfile(dict):
    def __init__(
        self,
        base_url: str,
        send_path: str,
        qr_path: str,
        api_key: str,
        instance_id: str,
        auth_required: bool,
        connected: bool,
        has_qr: bool,
        detected_from: str,
    ):
        super().__init__(
            base_url=base_url,
            send_path=send_path,
            qr_path=qr_path,
            api_key=api_key,
            instance_id=instance_id,
            auth_required=auth_required,
            connected=connected,
            has_qr=has_qr,
            detected_from=detected_from,
        )

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def discover_bridge_base_url(extra_candidates: list[str] | None = None) -> str:
    """The gateway URL is configured, not probed.

    The old bridge was found by trying a list of candidate hosts and paths. That
    guesswork is gone: OpenWA lives at a known address. Returns '' when the
    gateway is unreachable so callers keep their existing "not found" handling.
    """
    if not openwa_base_url() or not openwa_api_key():
        return ''
    status, _ = _openwa_request('GET', '/api/health/ready', timeout=5.0)
    return openwa_base_url() if status == 200 else ''


def discover_bridge_profile(extra_candidates: list[str] | None = None) -> BridgeProfile | None:
    base_url = discover_bridge_base_url(extra_candidates)
    if not base_url:
        return None

    session = get_session_state()
    status_name = str((session or {}).get('status') or '')

    return BridgeProfile(
        base_url=base_url,
        send_path='/api/sessions/{session}/messages/send-text',
        # Points at this app's authenticated proxy route, not at OpenWA, because
        # the QR endpoint needs an API key the browser cannot send.
        qr_path='/whatsapp/qr',
        api_key='',  # never surfaced to templates
        instance_id=str((session or {}).get('name') or openwa_session_name()),
        auth_required=status_name != STATUS_READY,
        connected=status_name == STATUS_READY,
        has_qr=status_name == STATUS_QR_READY,
        detected_from=f'openwa:{status_name}' if status_name else 'openwa',
    )


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

class WhatsAppGateway(ABC):
    @abstractmethod
    def send_message(self, phone: str, text: str, chat_id: str | None = None) -> tuple[bool, str]:
        raise NotImplementedError


class MockWhatsAppGateway(WhatsAppGateway):
    def send_message(self, phone: str, text: str, chat_id: str | None = None) -> tuple[bool, str]:
        current_app.logger.info("MOCK WA SEND phone=%s chat_id=%s text=%s", phone, chat_id, text)
        return True, "mock-sent"


class OpenWaWhatsAppGateway(WhatsAppGateway):
    def send_message(self, phone: str, text: str, chat_id: str | None = None) -> tuple[bool, str]:
        uuid = resolve_session_uuid()
        if not uuid:
            return False, "bridge-not-found"

        normalized_phone = normalize_whatsapp_number(phone)

        # A @lid privacy id is not addressable for sending; prefer a real number
        # whenever we have one. Same rule the previous bridge applied.
        target = ''
        if chat_id:
            if chat_id.endswith('@lid') and normalized_phone:
                current_app.logger.warning(
                    'OpenWA send skipping @lid chat_id because a numeric phone is available: '
                    'phone=%s chat_id=%s', normalized_phone, chat_id,
                )
            else:
                target = chat_id
        if not target:
            if not normalized_phone:
                return False, "invalid-phone"
            target = f"{normalized_phone}@c.us"

        current_app.logger.info(
            'OpenWA send chatId=%s text=%s', target, str(text)[:64],
        )

        status, body = _openwa_request(
            'POST',
            f'/api/sessions/{uuid}/messages/send-text',
            {'chatId': target, 'text': text},
            timeout=20.0,
        )

        if status in (200, 201):
            # Keep returning "sent": this string is persisted as
            # WhatsAppMessage.status and existing rows/queries depend on it.
            return True, 'sent'

        if status == 0:
            return False, 'bridge-error'
        if status == 409:
            # Session exists but isn't connected - a transient, retryable state.
            return False, 'wa_not_connected'
        return False, _err(body, f'bridge-http-{status}')


# Backwards-compatible alias: older code/tests may still reference this name.
BridgeWhatsAppGateway = OpenWaWhatsAppGateway


def get_gateway() -> WhatsAppGateway:
    mode = str(current_app.config.get("WHATSAPP_MODE", "mock") or "mock").strip().lower()
    if mode in ('bridge', 'openwa'):
        return OpenWaWhatsAppGateway()
    return MockWhatsAppGateway()


# ---------------------------------------------------------------------------
# Number checks, contacts, LID resolution
# ---------------------------------------------------------------------------

def check_whatsapp_number_registered(phone: str) -> tuple[bool | None, str]:
    """Ask the gateway whether a number is a real, active WhatsApp account.

    (True, "ok")      - registered
    (False, reason)   - the gateway CONFIRMED the number is not on WhatsApp
    (None, reason)    - inconclusive; callers must not hard-block on this

    The distinction matters: a confirmed False blocks a booking, so an
    unreachable gateway, an unconnected session (409) or an unanswered lookup
    (503) must all stay None.
    """
    normalized = normalize_whatsapp_number(phone)
    if not normalized:
        return False, "invalid-format"

    uuid = resolve_session_uuid()
    if not uuid:
        return None, "bridge-not-found"

    status, body = _openwa_request(
        'GET', f'/api/sessions/{uuid}/contacts/check/{normalized}', timeout=15.0,
    )

    if status == 200 and isinstance(body, dict):
        return bool(body.get('exists')), "ok"
    if status == 409:
        return None, "wa_not_connected"
    if status == 503:
        return None, "lookup-unanswered"
    if status == 0:
        return None, "bridge-error"
    return None, _err(body, f"bridge-http-{status}")


def fetch_whatsapp_contacts(saved_only: bool = True) -> tuple[bool, str, list[dict]]:
    """Pull the WhatsApp address book.

    Returns (ok, status, contacts) where each contact has at least ``number`` and
    ``name``, matching what the previous bridge returned.
    """
    uuid = resolve_session_uuid()
    if not uuid:
        return False, "bridge-not-found", []

    page_size = 500
    max_pages = 40  # hard ceiling so a huge book can't stall the request
    collected: dict[str, dict] = {}

    for page in range(max_pages):
        offset = page * page_size
        status, body = _openwa_request(
            'GET',
            f'/api/sessions/{uuid}/contacts?limit={page_size}&offset={offset}',
            timeout=30.0,
        )
        if status == 409:
            return False, "wa_not_connected", []
        if status != 200 or not isinstance(body, list):
            if page == 0:
                return False, _err(body, "contacts-unavailable"), []
            break

        for raw in body:
            if not isinstance(raw, dict):
                continue
            if raw.get('isBlocked'):
                continue
            is_my_contact = bool(raw.get('isMyContact'))
            if saved_only and not is_my_contact:
                continue

            jid = str(raw.get('id') or '')
            number = normalize_whatsapp_number(raw.get('number') or '')
            lid = ''
            if jid.endswith('@lid'):
                lid = normalize_whatsapp_number(jid.split('@', 1)[0])
            elif not number:
                number = normalize_whatsapp_number(jid.split('@', 1)[0])

            key = number or lid
            if not key:
                continue

            entry = collected.setdefault(key, {
                'number': '', 'lid': '', 'name': '',
                'is_my_contact': False, 'is_business': False,
            })
            if number:
                entry['number'] = number
            if lid and not entry['lid']:
                entry['lid'] = lid
            name = str(raw.get('name') or raw.get('pushName') or '').strip()
            if name and not entry['name']:
                entry['name'] = name
            entry['is_my_contact'] = entry['is_my_contact'] or is_my_contact

        if len(body) < page_size:
            break

    return True, "ok", list(collected.values())


def resolve_lid_to_phone(contact_id: str) -> str:
    """Resolve an @lid privacy id to real phone digits, or '' if unmappable.

    Only needed as a fallback: with RESOLVE_LID_TO_PHONE enabled the gateway
    already attaches `senderPhone` to inbound messages.
    """
    target = str(contact_id or '').strip()
    if not target:
        return ''
    uuid = resolve_session_uuid()
    if not uuid:
        return ''

    status, body = _openwa_request(
        'GET', f'/api/sessions/{uuid}/contacts/{target}/phone', timeout=10.0,
    )
    if status == 200:
        if isinstance(body, dict):
            for field in ('phone', 'phoneNumber', 'number'):
                value = normalize_whatsapp_number(body.get(field) or '')
                if value:
                    return value
        elif isinstance(body, str):
            return normalize_whatsapp_number(body)
    return ''


# ---------------------------------------------------------------------------
# Session management, exposed to the settings page as "instances"
# ---------------------------------------------------------------------------

def _session_to_instance(session: dict) -> dict:
    """Map an OpenWA session onto the instance dict the settings page renders."""
    status_name = str(session.get('status') or '')
    restriction = session.get('restriction')
    last_error = session.get('lastError')

    # Surface a restriction prominently: it means WhatsApp has limited the
    # account, which is exactly the failure that is otherwise invisible.
    problem = ''
    if restriction:
        problem = f'restriction: {restriction}'
    elif last_error:
        problem = str(last_error)
    elif status_name in ('failed', 'action_required', 'disconnected'):
        problem = f'status: {status_name}'

    name = str(session.get('name') or '')
    return {
        'id': name or str(session.get('id') or ''),
        'uuid': str(session.get('id') or ''),
        'client_id': str(session.get('id') or ''),
        'label': name or 'Default',
        'status': status_name,
        'ready': status_name == STATUS_READY,
        'connected': status_name == STATUS_READY,
        'has_qr': status_name == STATUS_QR_READY,
        'phone': normalize_whatsapp_number(session.get('phone') or ''),
        'push_name': str(session.get('pushName') or ''),
        # OpenWA does not persist a pairing code on the session; it is returned
        # once by the pair request and shown in the flash message.
        'pairing_code': '',
        'error': problem,
        'created_at': str(session.get('createdAt') or ''),
        'connected_at': str(session.get('connectedAt') or ''),
    }


def list_wa_instances() -> tuple[bool, str, list[dict]]:
    """List every WhatsApp session registered on the gateway."""
    if not discover_bridge_base_url():
        return False, "bridge-not-found", []
    sessions = list_openwa_sessions()
    return True, "ok", [_session_to_instance(s) for s in sessions]


def create_wa_instance(label: str) -> tuple[bool, str, dict | None]:
    """Register a new WhatsApp session. Does not start it."""
    name = str(label or '').strip()
    if not name:
        return False, "label-required", None
    if not discover_bridge_base_url():
        return False, "bridge-not-found", None

    status, body = _openwa_request('POST', '/api/sessions', {'name': name}, timeout=20.0)
    if status in (200, 201) and isinstance(body, dict):
        uuid = str(body.get('id') or '')
        if uuid:
            _SESSION_UUID_CACHE[name] = uuid
        return True, "ok", _session_to_instance(body)
    return False, _err(body, f"bridge-http-{status}"), None


def delete_wa_instance(instance_id: str) -> tuple[bool, str]:
    """Log out and remove a session."""
    uuid = resolve_session_uuid(instance_id)
    if not uuid:
        return False, "instance_not_found"

    # Best-effort logout so WhatsApp drops the companion device too.
    _openwa_request('POST', f'/api/sessions/{uuid}/logout', timeout=30.0)

    status, body = _openwa_request('DELETE', f'/api/sessions/{uuid}', timeout=30.0)
    if status in (200, 202, 204):
        _SESSION_UUID_CACHE.pop(str(instance_id or '').strip(), None)
        return True, "ok"
    return False, _err(body, f"bridge-http-{status}")


def start_wa_instance(instance_id: str | None = None) -> tuple[bool, str]:
    """Start a session's engine so it can produce a QR or a pairing code.

    Separate from creation on purpose: starting is what initiates a linking
    handshake with WhatsApp, and repeated handshakes are what get an account
    rate-limited.
    """
    uuid = ensure_session(instance_id)
    if not uuid:
        return False, "bridge-not-found"
    status, body = _openwa_request('POST', f'/api/sessions/{uuid}/start', timeout=60.0)
    if status in (200, 201, 202):
        return True, "ok"
    return False, _err(body, f"bridge-http-{status}")


def request_wa_pairing_code(phone: str, instance_id: str = "default") -> tuple[bool, str, str | None]:
    """Request a "Link with phone number" pairing code.

    The session must be started first, so this starts it when necessary.
    """
    normalized = normalize_whatsapp_number(phone)
    if not normalized:
        return False, "invalid-phone", None

    uuid = ensure_session(instance_id)
    if not uuid:
        return False, "bridge-not-found", None

    state = get_session_state(instance_id) or {}
    status_name = str(state.get('status') or '')
    if status_name == STATUS_READY:
        return False, "already_connected", None
    if status_name in ('created', 'disconnected', 'failed', ''):
        ok, start_status = start_wa_instance(instance_id)
        if not ok:
            return False, start_status, None

    status, body = _openwa_request(
        'POST', f'/api/sessions/{uuid}/pairing-code',
        {'phoneNumber': normalized}, timeout=90.0,
    )

    if status in (200, 201) and isinstance(body, dict):
        code = str(body.get('pairingCode') or '').strip()
        return (True, "ok", code) if code else (False, "pair-failed", None)

    reason = _err(body, f"bridge-http-{status}")
    if re.search(r'rate.?overlimit|429|too many', reason, re.IGNORECASE):
        return False, f"rate_limited: {reason}", None
    return False, reason, None


def fetch_session_qr_png(instance_id: str | None = None) -> tuple[bool, str, bytes | None]:
    """Fetch the linking QR and return decoded PNG bytes.

    OpenWA returns it as a data URL (`data:image/png;base64,...`) from an
    endpoint that requires the API key, which is why this is proxied here rather
    than linked directly from the browser.
    """
    uuid = resolve_session_uuid(instance_id)
    if not uuid:
        return False, "bridge-not-found", None

    status, body = _openwa_request('GET', f'/api/sessions/{uuid}/qr', timeout=15.0)
    if status != 200 or not isinstance(body, dict):
        return False, _err(body, f"qr-unavailable-{status}"), None

    raw = str(body.get('qrCode') or '').strip()
    if not raw:
        return False, "qr-empty", None

    payload = raw.split(',', 1)[1] if raw.startswith('data:') and ',' in raw else raw
    try:
        return True, "ok", base64.b64decode(payload, validate=False)
    except Exception:
        return False, "qr-decode-failed", None


def wa_instance_qr_embed_url(instance_id: str, maybe_instance_id: str | None = None) -> str:
    """Cache-busted, browser-facing QR URL.

    Points at this app's own authenticated route. The gateway's QR endpoint needs
    an API key that an <img> tag cannot send, and exposing it unauthenticated
    would let anyone who polls it link their own device.
    """
    target = maybe_instance_id if maybe_instance_id is not None else instance_id
    ts = int(datetime.utcnow().timestamp())
    return f"/whatsapp/qr/{str(target or '').strip()}?t={ts}"


# ---------------------------------------------------------------------------
# Persistence (unchanged)
# ---------------------------------------------------------------------------

def log_inbound_message(
    phone: str, text: str, payload: dict | None = None, direction: str = "inbound"
) -> WhatsAppMessage:
    message = WhatsAppMessage(
        direction=direction,
        phone=phone,
        message_text=text,
        payload_json=json.dumps(payload or {}, ensure_ascii=True),
        status="received" if direction == "inbound" else "sent",
        created_at=datetime.utcnow(),
    )
    db.session.add(message)
    if not safe_commit("whatsapp log_inbound_message"):
        raise RuntimeError("Failed to persist inbound WhatsApp message")
    return message


def send_and_log_message(phone: str, text: str, chat_id: str | None = None) -> WhatsAppMessage:
    gateway = get_gateway()
    success, status = gateway.send_message(phone, text, chat_id=chat_id)
    payload = {}
    if chat_id:
        payload["chat_id"] = chat_id
    if not success:
        # The row's status stays the literal "failed" that callers and queries
        # expect, but the actual reason must not be thrown away - without it the
        # UI can only guess, which is how "check your API key" ends up on screen
        # for what is really an unconnected session.
        payload["send_error"] = status
    message = WhatsAppMessage(
        direction="outbound",
        phone=phone,
        message_text=text,
        payload_json=json.dumps(payload, ensure_ascii=True),
        status=status if success else "failed",
        created_at=datetime.utcnow(),
    )
    db.session.add(message)
    if not safe_commit("whatsapp send_and_log_message"):
        raise RuntimeError("Failed to persist outbound WhatsApp message")
    # Transient attribute (not a column) so the caller can report the cause.
    message.send_error = '' if success else status
    return message
