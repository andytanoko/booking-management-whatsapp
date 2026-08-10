"""
Coverage tests for app/services/whatsapp.py gateway and bridge functions.
Uses mocking to avoid real network calls.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from app.services.whatsapp import (
    MockWhatsAppGateway,
    BridgeWhatsAppGateway,
    get_gateway,
    discover_bridge_base_url,
    discover_bridge_profile,
    fetch_whatsapp_contacts,
    _request_json,
    _probe_bridge,
    BridgeProfile,
    send_and_log_message,
    log_inbound_message,
)
from app.models import WhatsAppMessage, db
from app.services.settings_store import set_setting


def _mock_urlopen_response(status=200, body='{"ok": true}'):
    """Build a mock context-manager urlopen response."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body.encode("utf-8")
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


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

    def test_get_gateway_setting_overrides_config(self, app):
        with app.app_context():
            app.config["WHATSAPP_MODE"] = "mock"
            set_setting("wa_mode", "bridge")
            gw = get_gateway()
            assert isinstance(gw, BridgeWhatsAppGateway)


class TestRequestJson:
    def test_request_json_success(self):
        resp = _mock_urlopen_response(body='{"key": "value"}')
        with patch("app.services.whatsapp.request.urlopen", return_value=resp):
            result = _request_json("http://x/status")
            assert result == {"key": "value"}

    def test_request_json_empty(self):
        resp = _mock_urlopen_response(body='')
        with patch("app.services.whatsapp.request.urlopen", return_value=resp):
            result = _request_json("http://x/status")
            assert result is None

    def test_request_json_non_dict(self):
        resp = _mock_urlopen_response(body='[1, 2, 3]')
        with patch("app.services.whatsapp.request.urlopen", return_value=resp):
            result = _request_json("http://x/status")
            assert result is None

    def test_request_json_exception(self):
        with patch("app.services.whatsapp.request.urlopen", side_effect=Exception("boom")):
            result = _request_json("http://x/status")
            assert result is None


class TestProbeBridge:
    def test_probe_success(self):
        resp = _mock_urlopen_response(status=200)
        with patch("app.services.whatsapp.request.urlopen", return_value=resp):
            assert _probe_bridge("http://localhost:3000", "/qr") is True

    def test_probe_failure(self):
        with patch("app.services.whatsapp.request.urlopen", side_effect=Exception("down")):
            assert _probe_bridge("http://localhost:3000", "/qr") is False


class TestDiscoverBridgeBaseUrl:
    def test_discover_none_found(self, app):
        with app.app_context():
            with patch("app.services.whatsapp._probe_bridge", return_value=False):
                result = discover_bridge_base_url()
                assert result == ""

    def test_discover_found(self, app):
        with app.app_context():
            with patch("app.services.whatsapp._probe_bridge", return_value=True):
                result = discover_bridge_base_url()
                assert result != ""

    def test_discover_with_configured(self, app):
        with app.app_context():
            set_setting("bridge_base_url", "http://configured:3000")
            with patch("app.services.whatsapp._probe_bridge", return_value=True):
                result = discover_bridge_base_url()
                assert "configured" in result

    def test_discover_extra_candidates(self, app):
        with app.app_context():
            def probe(url, qr):
                return "extra-host" in url
            with patch("app.services.whatsapp._probe_bridge", side_effect=probe):
                result = discover_bridge_base_url(extra_candidates=["http://extra-host:3000"])
                assert "extra-host" in result


class TestDiscoverBridgeProfile:
    def test_profile_no_bridge(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=""):
                assert discover_bridge_profile() is None

    def test_profile_found(self, app):
        with app.app_context():
            resp = _mock_urlopen_response(status=200, body='{"connected": true, "instance_id": "s1"}')
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp.request.urlopen", return_value=resp), \
                 patch("app.services.whatsapp._request_json", return_value={"connected": True, "instance_id": "s1", "has_qr": False}):
                profile = discover_bridge_profile()
                assert profile is not None
                assert isinstance(profile, BridgeProfile)
                assert profile.connected is True


class TestBridgeGatewaySend:
    def test_bridge_send_no_profile(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_profile", return_value=None):
                gw = BridgeWhatsAppGateway()
                ok, status = gw.send_message("628123456789", "Hi")
                assert ok is False
                assert status == "bridge-not-found"

    def test_bridge_send_success(self, app):
        with app.app_context():
            profile = BridgeProfile(
                base_url="http://localhost:3000", send_path="/send-message",
                qr_path="/qr", api_key="key", instance_id="s1",
                auth_required=False, connected=True, has_qr=False, detected_from="test",
            )
            resp = _mock_urlopen_response(status=200)
            with patch("app.services.whatsapp.discover_bridge_profile", return_value=profile), \
                 patch("app.services.whatsapp.request.urlopen", return_value=resp):
                gw = BridgeWhatsAppGateway()
                ok, status = gw.send_message("628123456789", "Hi", chat_id="628123456789@c.us")
                assert ok is True

    def test_bridge_send_http_error_status(self, app):
        with app.app_context():
            profile = BridgeProfile(
                base_url="http://localhost:3000", send_path="send-message",
                qr_path="/qr", api_key="", instance_id="",
                auth_required=False, connected=True, has_qr=False, detected_from="test",
            )
            resp = _mock_urlopen_response(status=500)
            with patch("app.services.whatsapp.discover_bridge_profile", return_value=profile), \
                 patch("app.services.whatsapp.request.urlopen", return_value=resp):
                gw = BridgeWhatsAppGateway()
                ok, status = gw.send_message("628123456789", "Hi")
                assert ok is False

    def test_bridge_send_exception(self, app):
        with app.app_context():
            profile = BridgeProfile(
                base_url="http://localhost:3000", send_path="/send-message",
                qr_path="/qr", api_key="", instance_id="",
                auth_required=False, connected=True, has_qr=False, detected_from="test",
            )
            with patch("app.services.whatsapp.discover_bridge_profile", return_value=profile), \
                 patch("app.services.whatsapp.request.urlopen", side_effect=Exception("net")):
                gw = BridgeWhatsAppGateway()
                ok, status = gw.send_message("628123456789", "Hi")
                assert ok is False
                assert status == "bridge-error"


class TestFetchContacts:
    def test_fetch_no_bridge(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=""):
                ok, status, contacts = fetch_whatsapp_contacts()
                assert ok is False
                assert status == "bridge-not-found"
                assert contacts == []

    def test_fetch_unavailable(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp._request_json", return_value=None):
                ok, status, contacts = fetch_whatsapp_contacts()
                assert ok is False
                assert status == "contacts-unavailable"

    def test_fetch_error_flag(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp._request_json", return_value={"ok": False, "error": "custom-error"}):
                ok, status, contacts = fetch_whatsapp_contacts()
                assert ok is False
                assert status == "custom-error"

    def test_fetch_success(self, app):
        with app.app_context():
            payload = {"ok": True, "contacts": [{"number": "628111", "name": "A"}]}
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp._request_json", return_value=payload):
                ok, status, contacts = fetch_whatsapp_contacts()
                assert ok is True
                assert status == "ok"
                assert len(contacts) == 1

    def test_fetch_contacts_not_list(self, app):
        with app.app_context():
            payload = {"ok": True, "contacts": "not-a-list"}
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp._request_json", return_value=payload):
                ok, status, contacts = fetch_whatsapp_contacts()
                assert ok is True
                assert contacts == []


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
