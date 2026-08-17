"""Settings-page reporting for the WhatsApp gateway.

Covers two bugs that made a working link look broken:

1. Auto-refresh was gated on regex-matching the Indonesian status labels, so
   adding a label switched it off and the status only changed when some other
   action happened to re-render the page. It is now driven by a server-rendered
   `data-wa-pending` attribute.
2. The test-send failure message was a fixed string blaming the API key and the
   "bridge QR", because send_and_log_message discarded the gateway's reason. The
   reason is now preserved and the advice matches it.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.models import WhatsAppMessage, db


def _instance(**overrides):
    inst = {
        "id": "default",
        "label": "Default",
        "status": "ready",
        "connected": True,
        "has_qr": False,
        "phone": "628123456789",
        "pairing_code": "",
        "error": "",
        "qr_embed_url": "",
    }
    inst.update(overrides)
    return inst


def _profile(**overrides):
    defaults = {
        "base_url": "http://openwa:2785",
        "qr_path": "/whatsapp/qr",
        "has_qr": False,
        "auth_required": False,
        "connected": True,
        "instance_id": "default",
        "detected_from": "openwa:ready",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


class TestPendingFlag:
    """data-wa-pending decides whether the browser keeps polling."""

    @pytest.mark.parametrize(
        "status,has_qr,expected",
        [
            ("qr_ready", True, "1"),       # waiting for the scan
            ("authenticating", False, "1"),  # scan accepted, finishing up
            ("initializing", False, "1"),  # engine booting
            ("ready", False, "0"),         # done, nothing to wait for
            ("created", False, "0"),       # not started; will never change alone
            ("disconnected", False, "0"),  # terminal until someone acts
            ("failed", False, "0"),        # terminal until someone acts
        ],
    )
    def test_flag_reflects_only_real_transitions(
        self, client, session_login, status, has_qr, expected
    ):
        instances = [_instance(status=status, has_qr=has_qr, connected=status == "ready")]
        with patch("app.app.discover_bridge_profile", return_value=_profile()), \
             patch("app.app.list_wa_instances", return_value=(True, "ok", instances)):
            response = client.get("/settings")
        assert response.status_code == 200
        assert f'data-wa-pending="{expected}"'.encode() in response.data

    def test_partial_response_still_carries_the_table_and_flag(self, client, session_login):
        """The poller asks for a partial; it must contain the container it swaps."""
        instances = [_instance(status="qr_ready", has_qr=True, connected=False)]
        with patch("app.app.discover_bridge_profile", return_value=_profile(has_qr=True, connected=False)), \
             patch("app.app.list_wa_instances", return_value=(True, "ok", instances)):
            response = client.get("/settings", headers={"X-Requested-With": "fetch"})
        assert response.status_code == 200
        assert b'id="wa-instances-status"' in response.data
        assert b'data-wa-pending="1"' in response.data
        # A partial must not drag the whole page layout along.
        assert b"<html" not in response.data.lower()

    def test_poller_is_not_gated_on_translated_labels(self):
        """Regression guard: the old text-matching gate must not come back."""
        source = open("app/templates/settings.html", encoding="utf-8").read()
        assert "data-wa-pending" in source
        assert "Menunggu Scan QR|Menyiapkan" not in source
        # And it must request the value wants_partial() actually checks for.
        assert "'X-Requested-With': 'fetch'" in source


class TestTestSendFailureMessage:
    """What the page tells the operator when a test send fails.

    Patched at app.app.send_and_log_message rather than at the gateway, because
    app.py rewrites a 'failed' status to 'sent' whenever current_app.testing is
    set (app/app.py:262) - so a gateway-level failure cannot reach this branch
    under the test client.
    """

    def _post_test_send(self, client, reason):
        failed = MagicMock(status="failed", send_error=reason)
        with patch("app.app.send_and_log_message", return_value=failed):
            return client.post(
                "/settings",
                data={"action": "test_send", "test_phone": "628123456789", "test_message": "hi"},
            )

    def test_unconnected_session_says_so(self, client, session_login):
        response = self._post_test_send(client, "wa_not_connected")
        assert response.status_code == 200
        assert "belum tersambung".encode() in response.data
        # The old misleading advice must be gone.
        assert "API key benar".encode() not in response.data

    def test_unreachable_gateway_names_the_container(self, client, session_login):
        response = self._post_test_send(client, "bridge-not-found")
        assert response.status_code == 200
        assert b"openwa" in response.data

    def test_unregistered_number_is_reported_plainly(self, client, session_login):
        response = self._post_test_send(client, "number_not_on_whatsapp: 628123456789@c.us")
        assert response.status_code == 200
        assert "tidak terdaftar di WhatsApp".encode() in response.data

    def test_unknown_reason_is_shown_verbatim(self, client, session_login):
        response = self._post_test_send(client, "some-unexpected-gateway-error")
        assert response.status_code == 200
        assert b"some-unexpected-gateway-error" in response.data

    def test_success_reports_the_gateway_status(self, client, session_login):
        ok = MagicMock(status="sent", send_error="")
        with patch("app.app.send_and_log_message", return_value=ok):
            response = client.post(
                "/settings",
                data={"action": "test_send", "test_phone": "628123456789", "test_message": "hi"},
            )
        assert response.status_code == 200
        assert b"terkirim" in response.data


class TestFailureReasonIsPersisted:
    """The reason must survive on the row, or nothing downstream can explain it.

    Exercised against the service function directly: app.py's testing-mode
    override would otherwise rewrite the failure to a success.
    """

    def test_reason_stored_in_payload_and_exposed(self, app):
        from app.services.whatsapp import send_and_log_message

        with app.app_context():
            with patch("app.services.whatsapp.get_gateway") as gw:
                gw.return_value = MagicMock(
                    send_message=lambda phone, text, chat_id=None: (False, "wa_not_connected")
                )
                msg = send_and_log_message("628123456789", "hi")

            # The stored status stays the literal callers expect...
            assert msg.status == "failed"
            # ...while the cause is both attached and persisted.
            assert msg.send_error == "wa_not_connected"
            row = WhatsAppMessage.query.filter_by(direction="outbound").first()
            assert json.loads(row.payload_json)["send_error"] == "wa_not_connected"

    def test_successful_send_records_no_error(self, app):
        from app.services.whatsapp import send_and_log_message

        with app.app_context():
            with patch("app.services.whatsapp.get_gateway") as gw:
                gw.return_value = MagicMock(
                    send_message=lambda phone, text, chat_id=None: (True, "sent")
                )
                msg = send_and_log_message("628123456789", "hi")

            assert msg.status == "sent"
            assert msg.send_error == ""
            row = WhatsAppMessage.query.filter_by(direction="outbound").first()
            assert "send_error" not in json.loads(row.payload_json)
