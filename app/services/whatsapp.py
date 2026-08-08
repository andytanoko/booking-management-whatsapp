from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from urllib import error, request
from urllib.parse import urlparse
from abc import ABC, abstractmethod
from datetime import datetime

from flask import current_app

from app.models import WhatsAppMessage, db
from app.services.settings_store import get_setting


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


def _request_json(endpoint: str, timeout: float = 5.0) -> dict | None:
    req = request.Request(endpoint, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="ignore").strip()
            if not raw:
                return None
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def normalize_whatsapp_number(phone: str) -> str:
    """Normalize a WhatsApp phone identifier to digits only."""
    digits = re.sub(r"\D", "", str(phone or ""))
    return digits if 8 <= len(digits) <= 15 else ""


def _probe_bridge(base_url: str, qr_path: str) -> bool:
    url = base_url.rstrip("/")
    path = qr_path if qr_path.startswith("/") else f"/{qr_path}"
    candidates = [
        f"{url}/health",
        f"{url}/status",
        f"{url}{path}",
    ]
    for endpoint in candidates:
        req = request.Request(endpoint, method="GET")
        try:
            with request.urlopen(req, timeout=3.0) as response:
                if 200 <= response.status < 500:
                    return True
        except Exception:
            continue
    return False


def discover_bridge_base_url(extra_candidates: list[str] | None = None) -> str:
    qr_path = get_setting("bridge_qr_path", "/qr").strip() or "/qr"

    configured = get_setting("bridge_base_url", "").strip().rstrip("/")
    env_url = os.getenv("WHATSAPP_BRIDGE_BASE_URL", "").strip().rstrip("/")
    public_base = get_setting("public_base_url", "").strip()

    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    if env_url:
        candidates.append(env_url)

    if public_base:
        parsed = urlparse(public_base)
        if parsed.hostname:
            candidates.append(f"{parsed.scheme or 'http'}://{parsed.hostname}:3000")

    candidates.extend(
        [
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://wa-bridge:3000",
        ]
    )

    if extra_candidates:
        candidates.extend(extra_candidates)

    seen = set()
    for item in candidates:
        if not item:
            continue
        normalized = item.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        if _probe_bridge(normalized, qr_path):
            return normalized
    return ""


def discover_bridge_profile(extra_candidates: list[str] | None = None) -> BridgeProfile | None:
    base_url = discover_bridge_base_url(extra_candidates)
    if not base_url:
        return None

    qr_candidates = [
        "/qr",
        "/qr-code",
        "/api/qr",
        "/session/qr",
    ]
    send_candidates = [
        "/send-message",
        "/api/send-message",
        "/api/messages/send",
        "/message/send",
    ]

    # Keep configured values as first preference if present.
    configured_qr = get_setting("bridge_qr_path", "").strip()
    configured_send = get_setting("bridge_send_path", "").strip()
    if configured_qr:
        q = configured_qr if configured_qr.startswith("/") else f"/{configured_qr}"
        qr_candidates.insert(0, q)
    if configured_send:
        s = configured_send if configured_send.startswith("/") else f"/{configured_send}"
        send_candidates.insert(0, s)

    qr_path = "/qr"
    for path in qr_candidates:
        endpoint = f"{base_url.rstrip('/')}{path}"
        req = request.Request(endpoint, method="GET")
        try:
            with request.urlopen(req, timeout=3.0) as response:
                if 200 <= response.status < 500:
                    qr_path = path
                    break
        except Exception:
            continue

    api_key = os.getenv("WHATSAPP_BRIDGE_API_KEY", "").strip()
    instance_id = ""
    auth_required = False
    connected = False
    has_qr = False
    detected_from = "heuristic"

    status_payload = None
    for status_path in ["/status", "/health", "/api/status", "/session/status"]:
        status_payload = _request_json(f"{base_url.rstrip('/')}{status_path}")
        if status_payload:
            detected_from = status_path
            break

    if status_payload:
        instance_id = str(
            status_payload.get("instance_id")
            or status_payload.get("session")
            or status_payload.get("client_id")
            or ""
        ).strip()
        connected = bool(status_payload.get("connected") or False)
        has_qr = bool(status_payload.get("has_qr") or status_payload.get("qr") or False)
        auth_required = bool(
            status_payload.get("auth_required")
            or status_payload.get("require_auth")
            or status_payload.get("protected")
            or False
        )
        if not api_key:
            api_key = str(status_payload.get("api_key") or status_payload.get("token") or "").strip()

    send_path = send_candidates[0]

    return BridgeProfile(
        base_url=base_url.rstrip("/"),
        send_path=send_path,
        qr_path=qr_path,
        api_key=api_key,
        instance_id=instance_id,
        auth_required=auth_required,
        connected=connected,
        has_qr=has_qr,
        detected_from=detected_from,
    )


class WhatsAppGateway(ABC):
    @abstractmethod
    def send_message(self, phone: str, text: str, chat_id: str | None = None) -> tuple[bool, str]:
        raise NotImplementedError


class MockWhatsAppGateway(WhatsAppGateway):
    def send_message(self, phone: str, text: str, chat_id: str | None = None) -> tuple[bool, str]:
        current_app.logger.info("MOCK WA SEND phone=%s chat_id=%s text=%s", phone, chat_id, text)
        return True, "mock-sent"


class BridgeWhatsAppGateway(WhatsAppGateway):
    def send_message(self, phone: str, text: str, chat_id: str | None = None) -> tuple[bool, str]:
        profile = discover_bridge_profile()
        if not profile:
            return False, "bridge-not-found"

        base_url = profile.base_url
        send_path = profile.send_path
        api_key = profile.api_key
        instance_id = profile.instance_id

        if not base_url:
            return False, "bridge-missing-url"

        if not send_path.startswith("/"):
            send_path = f"/{send_path}"

        normalized_phone = normalize_whatsapp_number(phone)
        payload = {
            "phone": normalized_phone or phone,
            "text": text,
        }
        if chat_id:
            if chat_id.endswith("@lid") and normalized_phone:
                current_app.logger.warning(
                    "Bridge WhatsApp send skipping @lid chat_id because numeric phone is available: phone=%s chat_id=%s",
                    normalized_phone,
                    chat_id,
                )
                chat_id = None
            else:
                payload["chat_id"] = chat_id
        if instance_id:
            payload["instance_id"] = instance_id

        current_app.logger.info(
            "Bridge WhatsApp send payload phone=%s chat_id=%s instance_id=%s text=%s",
            normalized_phone or phone,
            chat_id,
            instance_id,
            text[:64],
        )

        raw = json.dumps(payload).encode("utf-8")
        endpoint = f"{base_url}{send_path}"
        req = request.Request(endpoint, data=raw, method="POST")
        req.add_header("Content-Type", "application/json")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
            req.add_header("X-API-Key", api_key)

        try:
            with request.urlopen(req, timeout=10) as response:
                body_text = response.read().decode("utf-8", errors="ignore") or ""
                current_app.logger.debug(
                    "Bridge WhatsApp send response status=%s body=%s",
                    response.status,
                    body_text,
                )

                status = f"bridge-{response.status}"
                if 200 <= response.status < 300:
                    if body_text:
                        try:
                            body = json.loads(body_text)
                            status = str(body.get("status") or status)
                        except json.JSONDecodeError:
                            pass
                    return True, status

                if body_text:
                    try:
                        body = json.loads(body_text)
                        return False, str(body.get("error") or body.get("status") or status)
                    except json.JSONDecodeError:
                        pass
                return False, f"bridge-{response.status}"
        except error.HTTPError as exc:
            try:
                body_text = exc.read().decode("utf-8", errors="ignore") or ""
                current_app.logger.error(
                    "Bridge WhatsApp HTTPError status=%s body=%s",
                    exc.code,
                    body_text,
                )
            except Exception:
                current_app.logger.exception("Failed reading HTTPError body")
            return False, f"bridge-http-{exc.code}"
        except Exception as exc:
            current_app.logger.exception("Bridge WhatsApp send failed: %s", exc)
            return False, "bridge-error"


def get_gateway() -> WhatsAppGateway:
    return BridgeWhatsAppGateway()


def check_whatsapp_number_registered(phone: str) -> tuple[bool | None, str]:
    """Ask the bridge whether a phone number is a real, active WhatsApp account.

    Returns (True, "ok") if registered, (False, reason) if the bridge
    confirmed the number does NOT exist on WhatsApp, or (None, reason) if the
    check was inconclusive (bridge unreachable/not connected) - callers
    should treat None as "unknown" and not hard-block on it.
    """
    normalized = normalize_whatsapp_number(phone)
    if not normalized:
        return False, "invalid-format"

    profile = discover_bridge_profile()
    if not profile or not profile.base_url:
        return None, "bridge-not-found"

    raw = json.dumps({"phone": normalized, "instance_id": profile.instance_id}).encode("utf-8")
    endpoint = f"{profile.base_url.rstrip('/')}/check-number"
    req = request.Request(endpoint, data=raw, method="POST")
    req.add_header("Content-Type", "application/json")
    if profile.api_key:
        req.add_header("Authorization", f"Bearer {profile.api_key}")
        req.add_header("X-API-Key", profile.api_key)

    try:
        with request.urlopen(req, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
            if not body.get("ok"):
                return None, str(body.get("error") or "check-failed")
            return bool(body.get("registered")), "ok"
    except error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", errors="ignore") or "{}")
            err_msg = str(body.get("error") or f"bridge-http-{exc.code}")
        except Exception:
            err_msg = f"bridge-http-{exc.code}"
        # wa_not_connected (409) or any other bridge-side failure is
        # inconclusive, not a confirmed "number doesn't exist" - don't block.
        return None, err_msg
    except Exception:
        return None, "bridge-error"


def fetch_whatsapp_contacts(saved_only: bool = True) -> tuple[bool, str, list[dict]]:
    """Pull the WhatsApp address book from the bridge.

    Returns (ok, status, contacts). Each contact is a dict with at least
    ``number`` and ``name`` keys.
    """
    base_url = discover_bridge_base_url()
    if not base_url:
        return False, "bridge-not-found", []

    flag = "true" if saved_only else "false"
    endpoint = f"{base_url.rstrip('/')}/contacts?saved_only={flag}"
    data = _request_json(endpoint, timeout=30.0)
    if not data:
        return False, "contacts-unavailable", []

    if not data.get("ok"):
        return False, str(data.get("error") or "contacts-error"), []

    contacts = data.get("contacts")
    if not isinstance(contacts, list):
        contacts = []
    return True, "ok", contacts


def list_wa_instances() -> tuple[bool, str, list[dict]]:
    """List every WhatsApp number/session registered on the bridge."""
    base_url = discover_bridge_base_url()
    if not base_url:
        return False, "bridge-not-found", []

    data = _request_json(f"{base_url.rstrip('/')}/instances", timeout=5.0)
    if not data or not data.get("ok"):
        return False, str((data or {}).get("error") or "instances-unavailable"), []

    instances = data.get("instances")
    if not isinstance(instances, list):
        instances = []
    return True, "ok", instances


def create_wa_instance(label: str) -> tuple[bool, str, dict | None]:
    """Register a new WhatsApp number on the bridge; a QR code is generated for it."""
    base_url = discover_bridge_base_url()
    if not base_url:
        return False, "bridge-not-found", None

    raw = json.dumps({"label": label}).encode("utf-8")
    req = request.Request(f"{base_url.rstrip('/')}/instances", data=raw, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(req, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
            if body.get("ok"):
                return True, "ok", body.get("instance")
            return False, str(body.get("error") or "create-failed"), None
    except error.HTTPError as exc:
        return False, f"bridge-http-{exc.code}", None
    except Exception:
        return False, "bridge-error", None


def delete_wa_instance(instance_id: str) -> tuple[bool, str]:
    """Log out and remove a previously registered WhatsApp number."""
    base_url = discover_bridge_base_url()
    if not base_url:
        return False, "bridge-not-found"

    req = request.Request(f"{base_url.rstrip('/')}/instances/{instance_id}", method="DELETE")
    try:
        with request.urlopen(req, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
            if body.get("ok"):
                return True, "ok"
            return False, str(body.get("error") or "delete-failed")
    except error.HTTPError as exc:
        return False, f"bridge-http-{exc.code}"
    except Exception:
        return False, "bridge-error"


def wa_instance_qr_embed_url(instance_id: str, maybe_instance_id: str | None = None) -> str:
    """Build a cache-busted, browser-facing QR image URL.

    Routed through nginx's /wa-bridge/ prefix rather than the internal
    bridge_base (e.g. http://wa-bridge:3000), which is a Docker-network-only
    hostname the user's browser cannot resolve.
    """
    ts = int(datetime.utcnow().timestamp())
    if maybe_instance_id is not None:
        return f"{instance_id.rstrip('/')}/instances/{maybe_instance_id}/qr?t={ts}"
    return f"/wa-bridge/instances/{instance_id}/qr?t={ts}"




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
    db.session.commit()
    return message


def send_and_log_message(phone: str, text: str, chat_id: str | None = None) -> WhatsAppMessage:
    gateway = get_gateway()
    success, status = gateway.send_message(phone, text, chat_id=chat_id)
    payload = {}
    if chat_id:
        payload["chat_id"] = chat_id
    message = WhatsAppMessage(
        direction="outbound",
        phone=phone,
        message_text=text,
        payload_json=json.dumps(payload, ensure_ascii=True),
        status=status if success else "failed",
        created_at=datetime.utcnow(),
    )
    db.session.add(message)
    db.session.commit()
    return message
