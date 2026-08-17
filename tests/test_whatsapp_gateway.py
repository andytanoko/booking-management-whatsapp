"""
Coverage tests for app/services/whatsapp.py gateway and OpenWA functions.
Uses mocking to avoid real network calls.
"""
import json
import re
from unittest.mock import MagicMock, patch
from urllib import error
from urllib.parse import urlsplit

import pytest

from app.services.whatsapp import (
    _SESSION_UUID_CACHE,
    BridgeProfile,
    BridgeWhatsAppGateway,
    MockWhatsAppGateway,
    _openwa_request,
    discover_bridge_base_url,
    discover_bridge_profile,
    fetch_whatsapp_contacts,
    get_gateway,
    log_inbound_message,
    resolve_session_uuid,
    send_and_log_message,
)
from app.services.settings_store import set_setting

BASE_URL = "http://openwa-test:2785"
SESSION_NAME = "default"
SESSION_UUID = "11111111-2222-3333-4444-555555555555"


def _mock_urlopen_response(status=200, body='{"ok": true}'):
    """Build a mock context-manager urlopen response."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body.encode("utf-8")
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _router(routes, default=None):
    """Build a urlopen side_effect that answers by request path.

    ``routes`` maps a full-match regex for the request path to either an
    ``(status, body)`` tuple or an exception instance to raise. Unrouted paths
    fail loudly unless a ``default`` tuple is given, so a test can never
    accidentally assert against a response meant for a different endpoint.
    """
    def _open(req, timeout=None):
        path = urlsplit(req.full_url).path
        for pattern, outcome in routes.items():
            if re.fullmatch(pattern, path):
                if isinstance(outcome, BaseException):
                    raise outcome
                return _mock_urlopen_response(*outcome)
        if default is None:
            raise AssertionError(f"unexpected OpenWA request path: {path}")
        return _mock_urlopen_response(*default)

    return _open


@pytest.fixture
def openwa_env(monkeypatch):
    """Configure OpenWA and keep the session-uuid cache from leaking."""
    monkeypatch.setenv("OPENWA_BASE_URL", BASE_URL)
    monkeypatch.setenv("OPENWA_API_KEY", "test-api-key")
    monkeypatch.setenv("OPENWA_SESSION_ID", SESSION_NAME)
    _SESSION_UUID_CACHE.clear()
    yield
    _SESSION_UUID_CACHE.clear()


@pytest.fixture
def openwa_session(openwa_env):
    """As openwa_env, plus a pre-resolved session uuid so paths can be built."""
    _SESSION_UUID_CACHE[SESSION_NAME] = SESSION_UUID
    yield SESSION_UUID


class TestMockGateway:
    def test_mock_send(self, app):
        with app.app_context():
            gw = MockWhatsAppGateway()
            ok, status = gw.send_message("628123456789", "Hello")
            assert ok is True
            assert status == "mock-sent"

    def test_mock_send_with_chat_id(self, app):
        with app.app_context():
            gw = MockWhatsAppGateway()
            ok, status = gw.send_message("628123456789", "Hi", chat_id="628123456789@c.us")
            assert ok is True


class TestGetGateway:
    def test_get_gateway_defaults_to_mock(self, app):
        with app.app_context():
            app.config["WHATSAPP_MODE"] = "mock"
            gw = get_gateway()
            assert isinstance(gw, MockWhatsAppGateway)

    def test_get_gateway_bridge_via_config(self, app):
        with app.app_context():
            app.config["WHATSAPP_MODE"] = "bridge"
            gw = get_gateway()
            assert isinstance(gw, BridgeWhatsAppGateway)

    def test_get_gateway_ignores_db_setting(self, app):
        with app.app_context():
            app.config["WHATSAPP_MODE"] = "mock"
            set_setting("wa_mode", "bridge")
            gw = get_gateway()
            assert isinstance(gw, MockWhatsAppGateway)


class TestOpenWaRequest:
    """_openwa_request replaces the old _request_json / _probe_bridge pair.

    Same underlying concerns: HTTP success, empty body, non-JSON body, transport
    exceptions and HTTPError-with-a-body. It now also reports the status code, so
    callers can tell "not connected" from "unreachable".
    """

    def test_success_returns_status_and_parsed_json(self, openwa_env):
        resp = _mock_urlopen_response(body='{"key": "value"}')
        with patch("app.services.whatsapp.request.urlopen", return_value=resp):
            assert _openwa_request("GET", "/api/health/ready") == (200, {"key": "value"})

    def test_empty_body_becomes_empty_dict(self, openwa_env):
        resp = _mock_urlopen_response(body="")
        with patch("app.services.whatsapp.request.urlopen", return_value=resp):
            assert _openwa_request("GET", "/api/health/ready") == (200, {})

    def test_non_json_body_returned_as_text(self, openwa_env):
        resp = _mock_urlopen_response(status=502, body="<html>bad gateway</html>")
        with patch("app.services.whatsapp.request.urlopen", return_value=resp):
            status, body = _openwa_request("GET", "/api/sessions")
        assert status == 502
        assert body == "<html>bad gateway</html>"

    def test_json_list_body_is_preserved(self, openwa_env):
        resp = _mock_urlopen_response(body="[1, 2, 3]")
        with patch("app.services.whatsapp.request.urlopen", return_value=resp):
            assert _openwa_request("GET", "/api/sessions") == (200, [1, 2, 3])

    def test_transport_exception_reports_status_zero(self, openwa_env):
        with patch("app.services.whatsapp.request.urlopen", side_effect=Exception("boom")):
            status, body = _openwa_request("GET", "/api/health/ready")
        assert status == 0
        assert body == {"message": "openwa-unreachable"}

    def test_http_error_returns_code_and_error_body(self, openwa_env):
        http_error = error.HTTPError(
            url=f"{BASE_URL}/api/sessions", code=401, msg="Unauthorized", hdrs=None, fp=None,
        )
        http_error.read = MagicMock(return_value=b'{"message": "invalid api key"}')
        with patch("app.services.whatsapp.request.urlopen", side_effect=http_error):
            status, body = _openwa_request("GET", "/api/sessions")
        assert status == 401
        assert body == {"message": "invalid api key"}

    def test_http_error_with_unreadable_body(self, openwa_env):
        http_error = error.HTTPError(
            url=f"{BASE_URL}/api/sessions", code=500, msg="Boom", hdrs=None, fp=None,
        )
        http_error.read = MagicMock(side_effect=OSError("stream closed"))
        with patch("app.services.whatsapp.request.urlopen", side_effect=http_error):
            assert _openwa_request("GET", "/api/sessions") == (500, {})

    def test_not_configured_short_circuits(self, monkeypatch):
        monkeypatch.setenv("OPENWA_BASE_URL", BASE_URL)
        monkeypatch.delenv("OPENWA_API_KEY", raising=False)
        with patch("app.services.whatsapp.request.urlopen") as mock_open:
            status, body = _openwa_request("GET", "/api/health/ready")
        assert (status, body) == (0, {"message": "openwa-not-configured"})
        mock_open.assert_not_called()

    def test_sends_api_key_and_json_body(self, openwa_env):
        captured = {}

        def _open(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["key"] = req.get_header("X-api-key")
            captured["content_type"] = req.get_header("Content-type")
            captured["data"] = req.data
            return _mock_urlopen_response(status=201, body='{"id": "abc"}')

        with patch("app.services.whatsapp.request.urlopen", side_effect=_open):
            status, body = _openwa_request("POST", "api/sessions", {"name": "cs-2"})

        assert (status, body) == (201, {"id": "abc"})
        assert captured["url"] == f"{BASE_URL}/api/sessions"
        assert captured["method"] == "POST"
        assert captured["key"] == "test-api-key"
        assert captured["content_type"] == "application/json"
        assert json.loads(captured["data"]) == {"name": "cs-2"}


class TestDiscoverBridgeBaseUrl:
    """The gateway URL is configured now, not probed across candidate hosts."""

    def test_returns_configured_url_when_health_ready(self, app, openwa_env):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r"/api/health/ready": (200, '{"status": "ok"}')}),
            ):
                assert discover_bridge_base_url() == BASE_URL

    def test_returns_empty_when_health_not_200(self, app, openwa_env):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r"/api/health/ready": (503, '{"status": "starting"}')}),
            ):
                assert discover_bridge_base_url() == ""

    def test_returns_empty_when_unreachable(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=Exception("down")):
                assert discover_bridge_base_url() == ""

    def test_returns_empty_when_api_key_missing(self, app, monkeypatch):
        monkeypatch.setenv("OPENWA_BASE_URL", BASE_URL)
        monkeypatch.delenv("OPENWA_API_KEY", raising=False)
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen") as mock_open:
                assert discover_bridge_base_url() == ""
            mock_open.assert_not_called()

    def test_settings_url_wins_over_env(self, app, openwa_env):
        with app.app_context():
            set_setting("openwa_base_url", "http://configured:2785")
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r"/api/health/ready": (200, "{}")}),
            ):
                assert discover_bridge_base_url() == "http://configured:2785"


class TestResolveSessionUuid:
    def test_resolves_name_from_session_list(self, app, openwa_env):
        body = json.dumps([{"id": SESSION_UUID, "name": SESSION_NAME, "status": "ready"}])
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r"/api/sessions": (200, body)}),
            ):
                assert resolve_session_uuid() == SESSION_UUID
        assert _SESSION_UUID_CACHE[SESSION_NAME] == SESSION_UUID

    def test_unknown_name_returns_empty_and_clears_cache(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r"/api/sessions": (200, "[]")}),
            ):
                assert resolve_session_uuid(SESSION_NAME, refresh=True) == ""
        assert SESSION_NAME not in _SESSION_UUID_CACHE

    def test_uuid_passes_through_without_a_lookup(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen") as mock_open:
                assert resolve_session_uuid(SESSION_UUID) == SESSION_UUID
            mock_open.assert_not_called()


class TestDiscoverBridgeProfile:
    def test_profile_no_bridge(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=""):
                assert discover_bridge_profile() is None

    def test_profile_found_connected(self, app, openwa_session):
        session_body = json.dumps({"id": SESSION_UUID, "name": SESSION_NAME, "status": "ready"})
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    r"/api/health/ready": (200, "{}"),
                    rf"/api/sessions/{SESSION_UUID}": (200, session_body),
                }),
            ):
                profile = discover_bridge_profile()
        assert isinstance(profile, BridgeProfile)
        assert profile.base_url == BASE_URL
        assert profile.connected is True
        assert profile.has_qr is False
        assert profile.auth_required is False
        assert profile.instance_id == SESSION_NAME
        assert profile.detected_from == "openwa:ready"
        # The QR is proxied through this app because OpenWA needs an API key.
        assert profile.qr_path == "/whatsapp/qr"
        assert profile.api_key == ""

    def test_profile_qr_ready(self, app, openwa_session):
        session_body = json.dumps({"id": SESSION_UUID, "name": SESSION_NAME, "status": "qr_ready"})
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    r"/api/health/ready": (200, "{}"),
                    rf"/api/sessions/{SESSION_UUID}": (200, session_body),
                }),
            ):
                profile = discover_bridge_profile()
        assert profile.has_qr is True
        assert profile.connected is False
        assert profile.auth_required is True
        assert profile.detected_from == "openwa:qr_ready"

    def test_profile_without_session_state(self, app, openwa_session):
        """Gateway up but the session record is missing (replaces the old
        "no status payload" heuristic case)."""
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    r"/api/health/ready": (200, "{}"),
                    rf"/api/sessions/{SESSION_UUID}": (404, '{"message": "not found"}'),
                }),
            ):
                profile = discover_bridge_profile()
        assert profile is not None
        assert profile.connected is False
        assert profile.has_qr is False
        assert profile.detected_from == "openwa"
        assert profile.instance_id == SESSION_NAME


class TestBridgeGatewaySend:
    def test_bridge_send_no_session(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.resolve_session_uuid", return_value=""):
                ok, status = BridgeWhatsAppGateway().send_message("628123456789", "Hi")
        assert ok is False
        assert status == "bridge-not-found"

    def test_bridge_send_success(self, app, openwa_session):
        captured = {}

        def _open(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data)
            return _mock_urlopen_response(status=201, body='{"id": "msg-1"}')

        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=_open):
                ok, status = BridgeWhatsAppGateway().send_message(
                    "628123456789", "Hi", chat_id="628123456789@c.us",
                )
        assert ok is True
        assert status == "sent"
        assert captured["url"] == f"{BASE_URL}/api/sessions/{SESSION_UUID}/messages/send-text"
        assert captured["body"] == {"chatId": "628123456789@c.us", "text": "Hi"}

    def test_bridge_send_builds_chat_id_from_phone(self, app, openwa_session):
        captured = {}

        def _open(req, timeout=None):
            captured["body"] = json.loads(req.data)
            return _mock_urlopen_response(status=200, body="{}")

        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=_open):
                ok, status = BridgeWhatsAppGateway().send_message("628123456789", "Hi")
        assert (ok, status) == (True, "sent")
        assert captured["body"]["chatId"] == "628123456789@c.us"

    def test_bridge_send_prefers_phone_over_lid(self, app, openwa_session):
        captured = {}

        def _open(req, timeout=None):
            captured["body"] = json.loads(req.data)
            return _mock_urlopen_response(status=200, body="{}")

        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=_open):
                ok, _ = BridgeWhatsAppGateway().send_message(
                    "628123456789", "Hi", chat_id="123456789012345@lid",
                )
        assert ok is True
        assert captured["body"]["chatId"] == "628123456789@c.us"

    def test_bridge_send_invalid_phone(self, app, openwa_session):
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen") as mock_open:
                ok, status = BridgeWhatsAppGateway().send_message("abc", "Hi")
            mock_open.assert_not_called()
        assert ok is False
        assert status == "invalid-phone"

    def test_bridge_send_http_error_status(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r".*send-text": (500, "")}),
            ):
                ok, status = BridgeWhatsAppGateway().send_message("628123456789", "Hi")
        assert ok is False
        assert status == "bridge-http-500"

    def test_bridge_send_surfaces_gateway_message(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r".*send-text": (400, '{"message": "chatId is invalid"}')}),
            ):
                ok, status = BridgeWhatsAppGateway().send_message("628123456789", "Hi")
        assert ok is False
        assert status == "chatId is invalid"

    def test_bridge_send_not_connected(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r".*send-text": (409, '{"message": "session not ready"}')}),
            ):
                ok, status = BridgeWhatsAppGateway().send_message("628123456789", "Hi")
        assert ok is False
        assert status == "wa_not_connected"

    def test_bridge_send_exception(self, app, openwa_session):
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=Exception("net")):
                ok, status = BridgeWhatsAppGateway().send_message("628123456789", "Hi")
        assert ok is False
        assert status == "bridge-error"


class TestFetchContacts:
    def test_fetch_no_bridge(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.resolve_session_uuid", return_value=""):
                ok, status, contacts = fetch_whatsapp_contacts()
        assert ok is False
        assert status == "bridge-not-found"
        assert contacts == []

    def test_fetch_unavailable(self, app, openwa_session):
        """A 200 that isn't a contact list is still unusable."""
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r".*/contacts": (200, "{}")}),
            ):
                ok, status, contacts = fetch_whatsapp_contacts()
        assert ok is False
        assert status == "contacts-unavailable"
        assert contacts == []

    def test_fetch_error_message(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r".*/contacts": (500, '{"error": "custom-error"}')}),
            ):
                ok, status, contacts = fetch_whatsapp_contacts()
        assert ok is False
        assert status == "custom-error"

    def test_fetch_not_connected(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r".*/contacts": (409, '{"message": "not ready"}')}),
            ):
                ok, status, contacts = fetch_whatsapp_contacts()
        assert ok is False
        assert status == "wa_not_connected"

    def test_fetch_success(self, app, openwa_session):
        body = json.dumps([
            {"id": "628123456781@c.us", "number": "628123456781", "name": "A", "isMyContact": True},
        ])
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r".*/contacts": (200, body)}),
            ):
                ok, status, contacts = fetch_whatsapp_contacts()
        assert ok is True
        assert status == "ok"
        assert len(contacts) == 1
        assert contacts[0]["number"] == "628123456781"
        assert contacts[0]["name"] == "A"

    def test_fetch_skips_unsaved_and_blocked(self, app, openwa_session):
        body = json.dumps([
            {"id": "628123456781@c.us", "number": "628123456781", "name": "Saved", "isMyContact": True},
            {"id": "628123456782@c.us", "number": "628123456782", "name": "Unsaved", "isMyContact": False},
            {"id": "628123456783@c.us", "number": "628123456783", "isMyContact": True, "isBlocked": True},
            "not-a-dict",
        ])
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r".*/contacts": (200, body)}),
            ):
                ok, _, contacts = fetch_whatsapp_contacts()
        assert ok is True
        assert [c["number"] for c in contacts] == ["628123456781"]

    def test_fetch_includes_unsaved_when_asked(self, app, openwa_session):
        body = json.dumps([
            {"id": "628123456782@c.us", "number": "628123456782", "pushName": "Unsaved", "isMyContact": False},
        ])
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r".*/contacts": (200, body)}),
            ):
                ok, _, contacts = fetch_whatsapp_contacts(saved_only=False)
        assert ok is True
        assert contacts[0]["name"] == "Unsaved"
        assert contacts[0]["is_my_contact"] is False


class TestSendAndLog:
    def test_send_and_log(self, app):
        with app.app_context():
            msg = send_and_log_message("628123456789", "Hello")
            assert msg is not None
            assert msg.direction == "outbound"
            assert msg.phone == "628123456789"

    def test_log_inbound(self, app):
        with app.app_context():
            msg = log_inbound_message("628123456789", "Incoming")
            assert msg.direction == "inbound"
            assert msg.status == "received"
