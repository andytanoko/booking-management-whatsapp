"""
Coverage tests for the multi-number WhatsApp registration feature:
- app/services/whatsapp.py: list_wa_instances, create_wa_instance,
  delete_wa_instance, start_wa_instance, request_wa_pairing_code,
  wa_instance_qr_embed_url
- app/app.py: /settings wa_number_add / wa_number_delete actions and the
  registered-numbers block rendered on the settings page.

Sessions are addressed by UUID on the gateway, so tests that reach a
session-scoped path seed the module's name -> uuid cache and clear it afterwards.
"""
import json
import re
from unittest.mock import MagicMock, patch
from urllib import error
from urllib.parse import urlsplit

import pytest

from app.models import AuditLog, db
from app.services.whatsapp import (
    _SESSION_UUID_CACHE,
    create_wa_instance,
    delete_wa_instance,
    fetch_session_qr_png,
    list_wa_instances,
    request_wa_pairing_code,
    start_wa_instance,
    wa_instance_qr_embed_url,
)

BASE_URL = "http://openwa-test:2785"
SESSION_NAME = "default"
SESSION_UUID = "12345678-1234-1234-1234-123456789abc"


def _resp(status=200, body='{"ok": true}'):
    """Build a mock context-manager urlopen response."""
    m = MagicMock()
    m.status = status
    m.read.return_value = body.encode("utf-8")
    m.__enter__ = MagicMock(return_value=m)
    m.__exit__ = MagicMock(return_value=False)
    return m


def _router(routes, default=None):
    """urlopen side_effect that answers by request path (full-match regex)."""
    def _open(req, timeout=None):
        path = urlsplit(req.full_url).path
        for pattern, outcome in routes.items():
            if re.fullmatch(pattern, path):
                if isinstance(outcome, BaseException):
                    raise outcome
                return _resp(*outcome)
        if default is None:
            raise AssertionError(f"unexpected OpenWA request path: {path}")
        return _resp(*default)

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
    """As openwa_env, plus a pre-resolved session uuid."""
    _SESSION_UUID_CACHE[SESSION_NAME] = SESSION_UUID
    yield SESSION_UUID


def _session(**overrides):
    payload = {
        "id": SESSION_UUID,
        "name": SESSION_NAME,
        "status": "ready",
        "phone": "628123456789",
        "pushName": "Detailing CS",
    }
    payload.update(overrides)
    return payload


class TestListWaInstances:
    def test_no_bridge(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=""):
                ok, status, instances = list_wa_instances()
                assert ok is False
                assert status == "bridge-not-found"
                assert instances == []

    def test_session_list_unavailable_yields_no_instances(self, app, openwa_env):
        """A reachable gateway that cannot list sessions reports zero sessions."""
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=BASE_URL), \
                 patch(
                     "app.services.whatsapp.request.urlopen",
                     side_effect=_router({r"/api/sessions": (500, '{"message": "boom"}')}),
                 ):
                ok, status, instances = list_wa_instances()
                assert ok is True
                assert status == "ok"
                assert instances == []

    def test_success(self, app, openwa_env):
        body = json.dumps([_session()])
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=BASE_URL), \
                 patch(
                     "app.services.whatsapp.request.urlopen",
                     side_effect=_router({r"/api/sessions": (200, body)}),
                 ):
                ok, status, instances = list_wa_instances()
        assert ok is True
        assert status == "ok"
        assert len(instances) == 1
        instance = instances[0]
        assert instance["id"] == SESSION_NAME
        assert instance["uuid"] == SESSION_UUID
        assert instance["label"] == SESSION_NAME
        assert instance["connected"] is True
        assert instance["has_qr"] is False
        assert instance["phone"] == "628123456789"
        assert instance["error"] == ""

    def test_instance_surfaces_restriction(self, app, openwa_env):
        """A WhatsApp-imposed restriction is the failure that must not stay silent."""
        body = json.dumps([_session(status="action_required", restriction="spam_warning")])
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=BASE_URL), \
                 patch(
                     "app.services.whatsapp.request.urlopen",
                     side_effect=_router({r"/api/sessions": (200, body)}),
                 ):
                ok, _, instances = list_wa_instances()
        assert ok is True
        assert instances[0]["error"] == "restriction: spam_warning"
        assert instances[0]["ready"] is False

    def test_instances_not_list(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=BASE_URL), \
                 patch(
                     "app.services.whatsapp.request.urlopen",
                     side_effect=_router({r"/api/sessions": (200, '{"not": "a list"}')}),
                 ):
                ok, status, instances = list_wa_instances()
                assert ok is True
                assert instances == []


class TestCreateWaInstance:
    def test_label_required(self, app, openwa_env):
        with app.app_context():
            ok, status, instance = create_wa_instance("   ")
        assert ok is False
        assert status == "label-required"
        assert instance is None

    def test_no_bridge(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=""):
                ok, status, instance = create_wa_instance("CS 2")
                assert ok is False
                assert status == "bridge-not-found"
                assert instance is None

    def test_success(self, app, openwa_env):
        body = json.dumps({"id": SESSION_UUID, "name": "CS 2", "status": "created"})
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=BASE_URL), \
                 patch(
                     "app.services.whatsapp.request.urlopen",
                     side_effect=_router({r"/api/sessions": (201, body)}),
                 ):
                ok, status, instance = create_wa_instance("CS 2")
        assert ok is True
        assert status == "ok"
        assert instance["id"] == "CS 2"
        assert instance["uuid"] == SESSION_UUID
        # The new session's uuid is cached so later calls skip the lookup.
        assert _SESSION_UUID_CACHE["CS 2"] == SESSION_UUID

    def test_gateway_rejects_label(self, app, openwa_env):
        body = json.dumps({"message": "name must be unique"})
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=BASE_URL), \
                 patch(
                     "app.services.whatsapp.request.urlopen",
                     side_effect=_router({r"/api/sessions": (400, body)}),
                 ):
                ok, status, instance = create_wa_instance("CS 2")
        assert ok is False
        assert status == "name must be unique"
        assert instance is None

    def test_http_error(self, app, openwa_env):
        http_error = error.HTTPError(
            url=f"{BASE_URL}/api/sessions", code=500, msg="Boom", hdrs=None, fp=None
        )
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=BASE_URL), \
                 patch("app.services.whatsapp.request.urlopen", side_effect=http_error):
                ok, status, instance = create_wa_instance("CS 2")
        assert ok is False
        assert status == "bridge-http-500"
        assert instance is None

    def test_generic_exception(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=BASE_URL), \
                 patch("app.services.whatsapp.request.urlopen", side_effect=Exception("net")):
                ok, status, instance = create_wa_instance("CS 2")
        assert ok is False
        assert status == "openwa-unreachable"
        assert instance is None


class TestDeleteWaInstance:
    def test_unknown_instance(self, app, openwa_env):
        """An unresolvable session name never reaches the gateway."""
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r"/api/sessions": (200, "[]")}),
            ):
                ok, status = delete_wa_instance("cs-2")
        assert ok is False
        assert status == "instance_not_found"

    def test_success_logs_out_then_deletes(self, app, openwa_session):
        calls = []

        def _open(req, timeout=None):
            calls.append((req.get_method(), urlsplit(req.full_url).path))
            return _resp(status=204, body="")

        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=_open):
                ok, status = delete_wa_instance(SESSION_NAME)
        assert (ok, status) == (True, "ok")
        assert calls == [
            ("POST", f"/api/sessions/{SESSION_UUID}/logout"),
            ("DELETE", f"/api/sessions/{SESSION_UUID}"),
        ]
        # Cache entry dropped so a re-created session re-resolves.
        assert SESSION_NAME not in _SESSION_UUID_CACHE

    def test_gateway_refuses_delete(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    rf"/api/sessions/{SESSION_UUID}/logout": (200, "{}"),
                    rf"/api/sessions/{SESSION_UUID}": (
                        409, '{"message": "cannot_delete_default_instance"}',
                    ),
                }),
            ):
                ok, status = delete_wa_instance(SESSION_NAME)
        assert ok is False
        assert status == "cannot_delete_default_instance"

    def test_http_error(self, app, openwa_session):
        http_error = error.HTTPError(
            url=f"{BASE_URL}/api/sessions/{SESSION_UUID}", code=404,
            msg="Not Found", hdrs=None, fp=None,
        )
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=http_error):
                ok, status = delete_wa_instance(SESSION_NAME)
        assert ok is False
        assert status == "bridge-http-404"

    def test_generic_exception(self, app, openwa_session):
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=Exception("net")):
                ok, status = delete_wa_instance(SESSION_NAME)
        assert ok is False
        assert status == "openwa-unreachable"


class TestStartWaInstance:
    def test_no_bridge(self, app, monkeypatch):
        monkeypatch.setenv("OPENWA_BASE_URL", BASE_URL)
        monkeypatch.delenv("OPENWA_API_KEY", raising=False)
        _SESSION_UUID_CACHE.clear()
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen") as mock_open:
                ok, status = start_wa_instance(SESSION_NAME)
            mock_open.assert_not_called()
        assert ok is False
        assert status == "bridge-not-found"

    def test_success(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({rf"/api/sessions/{SESSION_UUID}/start": (202, "{}")}),
            ):
                ok, status = start_wa_instance(SESSION_NAME)
        assert (ok, status) == (True, "ok")

    def test_failure_surfaces_message(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    rf"/api/sessions/{SESSION_UUID}/start": (
                        500, '{"message": "engine failed to boot"}',
                    ),
                }),
            ):
                ok, status = start_wa_instance(SESSION_NAME)
        assert ok is False
        assert status == "engine failed to boot"


class TestFetchSessionQrPng:
    def test_no_session(self, app, openwa_env):
        with app.app_context():
            with patch("app.services.whatsapp.resolve_session_uuid", return_value=""):
                ok, status, png = fetch_session_qr_png()
        assert ok is False
        assert status == "bridge-not-found"
        assert png is None

    def test_decodes_data_url(self, app, openwa_session):
        # 1x1 transparent PNG
        b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
            "AAAwAB/AL+g6mDAAAAAElFTkSuQmCC"
        )
        body = json.dumps({"qrCode": f"data:image/png;base64,{b64}"})
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({rf"/api/sessions/{SESSION_UUID}/qr": (200, body)}),
            ):
                ok, status, png = fetch_session_qr_png(SESSION_NAME)
        assert (ok, status) == (True, "ok")
        assert png.startswith(b"\x89PNG")

    def test_empty_qr(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({rf"/api/sessions/{SESSION_UUID}/qr": (200, '{"qrCode": ""}')}),
            ):
                ok, status, png = fetch_session_qr_png(SESSION_NAME)
        assert ok is False
        assert status == "qr-empty"
        assert png is None

    def test_qr_unavailable(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({rf"/api/sessions/{SESSION_UUID}/qr": (409, "")}),
            ):
                ok, status, png = fetch_session_qr_png(SESSION_NAME)
        assert ok is False
        assert status == "qr-unavailable-409"


class TestWaInstanceQrEmbedUrl:
    def test_builds_cache_busted_url(self):
        url = wa_instance_qr_embed_url("cs-2-ab12")
        assert url.startswith("/whatsapp/qr/cs-2-ab12?t=")

    def test_second_argument_wins(self):
        """Kept for the old (base_url, instance_id) call shape."""
        url = wa_instance_qr_embed_url("http://localhost:3000", "cs-2-ab12")
        assert url.startswith("/whatsapp/qr/cs-2-ab12?t=")


class TestRequestWaPairingCode:
    def test_invalid_phone(self, app, openwa_env):
        with app.app_context():
            ok, status, code = request_wa_pairing_code("abc")
            assert ok is False
            assert status == "invalid-phone"
            assert code is None

    def test_no_bridge(self, app, monkeypatch):
        monkeypatch.setenv("OPENWA_BASE_URL", BASE_URL)
        monkeypatch.delenv("OPENWA_API_KEY", raising=False)
        _SESSION_UUID_CACHE.clear()
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen") as mock_open:
                ok, status, code = request_wa_pairing_code("6281234567890")
            mock_open.assert_not_called()
        assert ok is False
        assert status == "bridge-not-found"
        assert code is None

    def test_success(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    rf"/api/sessions/{SESSION_UUID}": (200, json.dumps(_session(status="qr_ready"))),
                    rf"/api/sessions/{SESSION_UUID}/pairing-code": (
                        200, '{"pairingCode": "ABCD-1234"}',
                    ),
                }),
            ):
                ok, status, code = request_wa_pairing_code("6281234567890", SESSION_NAME)
        assert ok is True
        assert status == "ok"
        assert code == "ABCD-1234"

    def test_starts_a_created_session_first(self, app, openwa_session):
        calls = []

        def _open(req, timeout=None):
            path = urlsplit(req.full_url).path
            calls.append(path)
            if path.endswith("/pairing-code"):
                return _resp(status=200, body='{"pairingCode": "WXYZ-9876"}')
            if path.endswith("/start"):
                return _resp(status=202, body="{}")
            return _resp(status=200, body=json.dumps(_session(status="created")))

        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=_open):
                ok, status, code = request_wa_pairing_code("6281234567890", SESSION_NAME)
        assert (ok, status, code) == (True, "ok", "WXYZ-9876")
        assert f"/api/sessions/{SESSION_UUID}/start" in calls

    def test_already_connected(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    rf"/api/sessions/{SESSION_UUID}": (200, json.dumps(_session(status="ready"))),
                }),
            ):
                ok, status, code = request_wa_pairing_code("6281234567890", SESSION_NAME)
        assert ok is False
        assert status == "already_connected"
        assert code is None

    def test_empty_pairing_code(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    rf"/api/sessions/{SESSION_UUID}": (200, json.dumps(_session(status="qr_ready"))),
                    rf"/api/sessions/{SESSION_UUID}/pairing-code": (200, '{"pairingCode": ""}'),
                }),
            ):
                ok, status, code = request_wa_pairing_code("6281234567890", SESSION_NAME)
        assert ok is False
        assert status == "pair-failed"
        assert code is None

    def test_http_error_surfaces_gateway_message(self, app, openwa_session):
        http_error = error.HTTPError(
            url=f"{BASE_URL}/api/sessions/{SESSION_UUID}/pairing-code", code=409,
            msg="Conflict", hdrs=None, fp=None,
        )
        http_error.read = MagicMock(return_value=b'{"message": "already_connected"}')

        def _open(req, timeout=None):
            path = urlsplit(req.full_url).path
            if path.endswith("/pairing-code"):
                raise http_error
            return _resp(status=200, body=json.dumps(_session(status="qr_ready")))

        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=_open):
                ok, status, code = request_wa_pairing_code("6281234567890", SESSION_NAME)
        assert ok is False
        assert status == "already_connected"
        assert code is None

    def test_rate_limited(self, app, openwa_session):
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    rf"/api/sessions/{SESSION_UUID}": (200, json.dumps(_session(status="qr_ready"))),
                    rf"/api/sessions/{SESSION_UUID}/pairing-code": (
                        429, '{"message": "too many requests"}',
                    ),
                }),
            ):
                ok, status, code = request_wa_pairing_code("6281234567890", SESSION_NAME)
        assert ok is False
        assert status.startswith("rate_limited:")
        assert code is None

    def test_generic_exception(self, app, openwa_session):
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen", side_effect=Exception("net")):
                ok, status, code = request_wa_pairing_code("6281234567890", SESSION_NAME)
        assert ok is False
        assert status == "openwa-unreachable"
        assert code is None


class TestSettingsWaNumberActions:
    def test_add_number_missing_label(self, client, session_login, app):
        response = client.post("/settings", data={"action": "wa_number_add", "wa_number_label": ""})
        assert response.status_code in (200, 302)

    def test_add_number_success(self, client, session_login, app):
        with patch("app.app.create_wa_instance", return_value=(True, "ok", {"id": "cs-2-ab12", "label": "CS 2"})):
            response = client.post(
                "/settings", data={"action": "wa_number_add", "wa_number_label": "CS 2"}
            )
            assert response.status_code in (200, 302)
        with app.app_context():
            assert AuditLog.query.filter_by(action="whatsapp.instance.create").count() == 1

    def test_add_number_failure(self, client, session_login, app):
        with patch("app.app.create_wa_instance", return_value=(False, "bridge-not-found", None)):
            response = client.post(
                "/settings", data={"action": "wa_number_add", "wa_number_label": "CS 2"}
            )
            assert response.status_code in (200, 302)

    def test_start_number_success(self, client, session_login, app):
        """A created session shows no QR until it is explicitly started."""
        with patch("app.app.start_wa_instance", return_value=(True, "ok")) as mock_start:
            response = client.post(
                "/settings", data={"action": "wa_number_start", "instance_id": "default"}
            )
            assert response.status_code in (200, 302)
            mock_start.assert_called_once_with("default")
        with app.app_context():
            assert AuditLog.query.filter_by(action="whatsapp.instance.start").count() == 1

    def test_start_number_rate_limited_is_explained(self, client, session_login, app):
        """The 429 must be reported as a cooldown, not a generic failure."""
        with patch(
            "app.app.start_wa_instance",
            return_value=(False, "rate_limited: CompanionHelloError: rate-overlimit (429)"),
        ):
            response = client.post(
                "/settings", data={"action": "wa_number_start", "instance_id": "default"}
            )
        assert response.status_code == 200
        assert b"rate-overlimit" in response.data
        with app.app_context():
            assert AuditLog.query.filter_by(action="whatsapp.instance.start").count() == 0

    def test_start_number_failure(self, client, session_login, app):
        with patch("app.app.start_wa_instance", return_value=(False, "bridge-not-found")):
            response = client.post(
                "/settings", data={"action": "wa_number_start", "instance_id": "default"}
            )
        assert response.status_code in (200, 302)

    def test_delete_number_missing_id(self, client, session_login, app):
        response = client.post("/settings", data={"action": "wa_number_delete", "instance_id": ""})
        assert response.status_code in (200, 302)

    def test_delete_number_success(self, client, session_login, app):
        with patch("app.app.delete_wa_instance", return_value=(True, "ok")):
            response = client.post(
                "/settings", data={"action": "wa_number_delete", "instance_id": "cs-2-ab12"}
            )
            assert response.status_code in (200, 302)
        with app.app_context():
            assert AuditLog.query.filter_by(action="whatsapp.instance.delete").count() == 1

    def test_delete_number_failure(self, client, session_login, app):
        with patch("app.app.delete_wa_instance", return_value=(False, "instance_not_found")):
            response = client.post(
                "/settings", data={"action": "wa_number_delete", "instance_id": "missing"}
            )
            assert response.status_code in (200, 302)

    def test_settings_page_lists_instances(self, client, session_login, app):
        instances_payload = [
            {"id": "default", "label": "Default", "connected": True, "has_qr": False, "phone": "62811", "error": None},
            {"id": "cs-2-ab12", "label": "CS 2", "connected": False, "has_qr": True, "phone": "", "error": None},
        ]
        with patch("app.app.discover_bridge_profile") as mock_profile:
            mock_profile.return_value = MagicMock(
                base_url=BASE_URL,
                qr_path="/whatsapp/qr",
                has_qr=False,
                auth_required=False,
                connected=True,
                detected_from="openwa:ready",
            )
            with patch("app.app.list_wa_instances", return_value=(True, "ok", instances_payload)):
                response = client.get("/settings")
                assert response.status_code == 200
                assert b"CS 2" in response.data

    def test_settings_page_bridge_not_detected(self, client, session_login, app):
        with patch("app.app.discover_bridge_profile", return_value=None):
            response = client.get("/settings")
            assert response.status_code == 200
