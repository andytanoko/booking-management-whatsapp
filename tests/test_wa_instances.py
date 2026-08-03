"""
Coverage tests for the multi-number WhatsApp registration feature:
- app/services/whatsapp.py: list_wa_instances, create_wa_instance,
  delete_wa_instance, wa_instance_qr_embed_url
- app/app.py: /settings wa_number_add / wa_number_delete actions and the
  registered-numbers block rendered on the settings page.
"""
from unittest.mock import MagicMock, patch
from urllib import error

from app.models import AuditLog, db
from app.services.whatsapp import (
    create_wa_instance,
    delete_wa_instance,
    list_wa_instances,
    wa_instance_qr_embed_url,
)


def _resp(status=200, body='{"ok": true}'):
    """Build a mock context-manager urlopen response."""
    m = MagicMock()
    m.status = status
    m.read.return_value = body.encode("utf-8")
    m.__enter__ = MagicMock(return_value=m)
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestListWaInstances:
    def test_no_bridge(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=""):
                ok, status, instances = list_wa_instances()
                assert ok is False
                assert status == "bridge-not-found"
                assert instances == []

    def test_unavailable(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp._request_json", return_value=None):
                ok, status, instances = list_wa_instances()
                assert ok is False
                assert status == "instances-unavailable"

    def test_error_flag(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp._request_json", return_value={"ok": False, "error": "boom"}):
                ok, status, instances = list_wa_instances()
                assert ok is False
                assert status == "boom"

    def test_success(self, app):
        with app.app_context():
            payload = {"ok": True, "instances": [{"id": "default", "label": "Default"}]}
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp._request_json", return_value=payload):
                ok, status, instances = list_wa_instances()
                assert ok is True
                assert status == "ok"
                assert len(instances) == 1

    def test_instances_not_list(self, app):
        with app.app_context():
            payload = {"ok": True, "instances": "not-a-list"}
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp._request_json", return_value=payload):
                ok, status, instances = list_wa_instances()
                assert ok is True
                assert instances == []


class TestCreateWaInstance:
    def test_no_bridge(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=""):
                ok, status, instance = create_wa_instance("CS 2")
                assert ok is False
                assert status == "bridge-not-found"
                assert instance is None

    def test_success(self, app):
        with app.app_context():
            body = '{"ok": true, "instance": {"id": "cs-2-ab12", "label": "CS 2"}}'
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp.request.urlopen", return_value=_resp(body=body)):
                ok, status, instance = create_wa_instance("CS 2")
                assert ok is True
                assert status == "ok"
                assert instance["id"] == "cs-2-ab12"

    def test_body_not_ok(self, app):
        with app.app_context():
            body = '{"ok": false, "error": "label is required"}'
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp.request.urlopen", return_value=_resp(body=body)):
                ok, status, instance = create_wa_instance("CS 2")
                assert ok is False
                assert status == "label is required"
                assert instance is None

    def test_http_error(self, app):
        with app.app_context():
            http_error = error.HTTPError(
                url="http://localhost:3000/instances", code=500, msg="Boom", hdrs=None, fp=None
            )
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp.request.urlopen", side_effect=http_error):
                ok, status, instance = create_wa_instance("CS 2")
                assert ok is False
                assert status == "bridge-http-500"

    def test_generic_exception(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp.request.urlopen", side_effect=Exception("net")):
                ok, status, instance = create_wa_instance("CS 2")
                assert ok is False
                assert status == "bridge-error"


class TestDeleteWaInstance:
    def test_no_bridge(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value=""):
                ok, status = delete_wa_instance("cs-2-ab12")
                assert ok is False
                assert status == "bridge-not-found"

    def test_success(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp.request.urlopen", return_value=_resp()):
                ok, status = delete_wa_instance("cs-2-ab12")
                assert ok is True
                assert status == "ok"

    def test_body_not_ok(self, app):
        with app.app_context():
            body = '{"ok": false, "error": "cannot_delete_default_instance"}'
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp.request.urlopen", return_value=_resp(body=body)):
                ok, status = delete_wa_instance("default")
                assert ok is False
                assert status == "cannot_delete_default_instance"

    def test_http_error(self, app):
        with app.app_context():
            http_error = error.HTTPError(
                url="http://localhost:3000/instances/x", code=404, msg="Not Found", hdrs=None, fp=None
            )
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp.request.urlopen", side_effect=http_error):
                ok, status = delete_wa_instance("missing")
                assert ok is False
                assert status == "bridge-http-404"

    def test_generic_exception(self, app):
        with app.app_context():
            with patch("app.services.whatsapp.discover_bridge_base_url", return_value="http://localhost:3000"), \
                 patch("app.services.whatsapp.request.urlopen", side_effect=Exception("net")):
                ok, status = delete_wa_instance("cs-2-ab12")
                assert ok is False
                assert status == "bridge-error"


class TestWaInstanceQrEmbedUrl:
    def test_builds_cache_busted_url(self):
        url = wa_instance_qr_embed_url("http://localhost:3000", "cs-2-ab12")
        assert url.startswith("http://localhost:3000/instances/cs-2-ab12/qr?t=")


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
                base_url="http://localhost:3000",
                qr_path="/qr",
                has_qr=False,
                auth_required=False,
                connected=True,
                detected_from="status",
            )
            with patch("app.app.list_wa_instances", return_value=(True, "ok", instances_payload)):
                response = client.get("/settings")
                assert response.status_code == 200
                assert b"CS 2" in response.data

    def test_settings_page_bridge_not_detected(self, client, session_login, app):
        with patch("app.app.discover_bridge_profile", return_value=None):
            response = client.get("/settings")
            assert response.status_code == 200
