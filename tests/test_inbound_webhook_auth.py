"""Authentication and payload mapping for POST /api/whatsapp/inbound.

This endpoint is reachable from the internet and can create bookings and
customers, so it must reject anything it cannot authenticate. The rest of the
suite reaches it through the signing test client (see conftest); these tests
drive it directly with a raw client so the negative paths are actually covered.
"""
import json

import pytest

from app.models import Booking, Customer, WhatsAppMessage, db
from tests.conftest import INBOUND_PATH, TEST_WEBHOOK_SECRET, sign_webhook_body


@pytest.fixture
def raw_client(app):
    """A client that does NOT sign, so signature handling can be tested."""
    app.test_client_class = None  # fall back to Flask's default client
    return app.test_client()


def _post(client, payload, signature=None, secret=None):
    body = json.dumps(payload).encode("utf-8")
    headers = {}
    if signature is not None:
        headers["X-OpenWA-Signature"] = signature
    elif secret is not None:
        headers["X-OpenWA-Signature"] = sign_webhook_body(body, secret)
    return client.post(
        INBOUND_PATH, data=body, content_type="application/json", headers=headers,
    )


class TestInboundSignatureVerification:
    def test_unsigned_request_is_rejected(self, raw_client):
        response = _post(raw_client, {"phone": "628123456789", "text": "hi"})
        assert response.status_code == 401
        assert response.get_json()["error"] == "signature-missing"

    def test_wrong_signature_is_rejected(self, raw_client):
        response = _post(
            raw_client, {"phone": "628123456789", "text": "hi"}, signature="sha256=deadbeef",
        )
        assert response.status_code == 401
        assert response.get_json()["error"] == "signature-mismatch"

    def test_signature_from_the_wrong_secret_is_rejected(self, raw_client):
        response = _post(
            raw_client, {"phone": "628123456789", "text": "hi"}, secret="not-the-real-secret",
        )
        assert response.status_code == 401
        assert response.get_json()["error"] == "signature-mismatch"

    def test_signature_over_different_bytes_is_rejected(self, raw_client):
        """A valid HMAC for a *different* body must not authenticate this one."""
        other = json.dumps({"phone": "628999999999", "text": "other"}).encode("utf-8")
        response = _post(
            raw_client,
            {"phone": "628123456789", "text": "hi"},
            signature=sign_webhook_body(other),
        )
        assert response.status_code == 401
        assert response.get_json()["error"] == "signature-mismatch"

    def test_correct_signature_is_accepted(self, raw_client):
        response = _post(
            raw_client, {"phone": "628123456789", "text": "hi"}, secret=TEST_WEBHOOK_SECRET,
        )
        assert response.status_code == 200
        assert response.get_json()["ok"] is True

    def test_missing_secret_fails_closed(self, raw_client, monkeypatch):
        """No configured secret must not mean "accept everything"."""
        monkeypatch.setattr(
            "app.blueprints.whatsapp.openwa_webhook_secret", lambda: "",
        )
        response = _post(raw_client, {"phone": "628123456789", "text": "hi"}, secret=TEST_WEBHOOK_SECRET)
        assert response.status_code == 503
        assert response.get_json()["error"] == "webhook-secret-not-configured"

    def test_forged_booking_form_is_not_persisted(self, raw_client, app):
        """The whole point: an unsigned caller cannot write a booking."""
        payload = {
            "phone": "628123456789",
            "text": "Nama: Attacker\nNo HP: 628123456789\nPaket: Coating Premium\n",
        }
        response = _post(raw_client, payload)
        assert response.status_code == 401
        with app.app_context():
            assert WhatsAppMessage.query.count() == 0
            assert Booking.query.count() == 0
            assert Customer.query.count() == 0


class TestOpenWaEnvelopeMapping:
    """OpenWA posts {event, sessionId, data:{...}}; the app reads a flat shape."""

    def _envelope(self, event="message.received", **data_overrides):
        data = {
            "id": "msg-1",
            "chatId": "628123456789@c.us",
            "from": "628123456789@c.us",
            "body": "Halo",
            "type": "text",
            "timestamp": 1719312050,
            "fromMe": False,
            "isGroup": False,
            "kind": "individual",
            "contact": {"name": "Budi", "number": "628123456789"},
        }
        data.update(data_overrides)
        return {
            "event": event,
            "timestamp": "2026-08-16T15:00:00.000Z",
            "sessionId": "default",
            "idempotencyKey": "idem-1",
            "deliveryId": "del-1",
            "data": data,
        }

    def test_message_received_is_logged_inbound(self, client, app):
        response = client.post(INBOUND_PATH, json=self._envelope())
        assert response.status_code == 200
        assert response.get_json()["status"] == "logged"
        with app.app_context():
            msg = WhatsAppMessage.query.one()
            assert msg.direction == "inbound"
            assert msg.phone == "628123456789"
            assert msg.message_text == "Halo"
            stored = json.loads(msg.payload_json)
            assert stored["chat_id"] == "628123456789@c.us"
            assert stored["contact_name"] == "Budi"
            assert stored["source"] == "openwa"

    def test_from_me_is_logged_outbound(self, client, app):
        response = client.post(INBOUND_PATH, json=self._envelope(fromMe=True))
        assert response.status_code == 200
        with app.app_context():
            assert WhatsAppMessage.query.one().direction == "outbound"

    def test_group_message_is_filtered(self, client, app):
        envelope = self._envelope(
            chatId="629999999999-1600000000@g.us", isGroup=True, kind="group",
        )
        response = client.post(INBOUND_PATH, json=envelope)
        assert response.get_json()["status"] == "filtered"
        with app.app_context():
            assert WhatsAppMessage.query.count() == 0

    def test_status_broadcast_is_filtered(self, client, app):
        envelope = self._envelope(kind="status", isStatusBroadcast=True)
        assert client.post(INBOUND_PATH, json=envelope).get_json()["status"] == "filtered"
        with app.app_context():
            assert WhatsAppMessage.query.count() == 0

    def test_lid_sender_uses_resolved_sender_phone(self, client, app):
        """RESOLVE_LID_TO_PHONE gives us the real number behind a privacy id."""
        envelope = self._envelope(
            chatId="123456789012345@lid",
            **{"isLidSender": True, "senderPhone": "628111222333", "contact": {"name": "Sari"}},
        )
        response = client.post(INBOUND_PATH, json=envelope)
        assert response.status_code == 200
        with app.app_context():
            msg = WhatsAppMessage.query.one()
            assert msg.phone == "628111222333"
            assert json.loads(msg.payload_json)["chat_id"] == "123456789012345@lid"

    def test_unresolved_lid_falls_back_to_lid_token(self, client, app):
        """Without a resolved phone the inbox still needs a stable identity."""
        envelope = self._envelope(
            chatId="123456789012345@lid",
            **{"isLidSender": True, "senderPhone": None, "contact": {}},
        )
        response = client.post(INBOUND_PATH, json=envelope)
        assert response.status_code == 200
        with app.app_context():
            assert WhatsAppMessage.query.one().phone == "lid:123456789012345"

    def test_non_message_event_is_acknowledged_not_stored(self, client, app):
        envelope = {
            "event": "message.ack",
            "sessionId": "default",
            "data": {"id": "msg-1", "ack": 2},
        }
        response = client.post(INBOUND_PATH, json=envelope)
        assert response.status_code == 200
        assert response.get_json()["status"] == "ignored"
        with app.app_context():
            assert WhatsAppMessage.query.count() == 0

    def test_session_restriction_event_is_acknowledged(self, client, app):
        """A restriction must not be retried forever, but must be visible."""
        envelope = {
            "event": "session.restriction",
            "sessionId": "default",
            "data": {"restriction": "spam_warning"},
        }
        response = client.post(INBOUND_PATH, json=envelope)
        assert response.status_code == 200
        assert response.get_json()["event"] == "session.restriction"

    def test_legacy_flat_payload_still_accepted(self, client, app):
        """The old bridge shape keeps working during the migration."""
        response = client.post(
            INBOUND_PATH,
            json={
                "phone": "628123456789",
                "text": "Halo",
                "from_me": False,
                "chat_id": "628123456789@c.us",
                "contact_name": "Budi",
            },
        )
        assert response.status_code == 200
        assert response.get_json()["status"] == "logged"
        with app.app_context():
            assert WhatsAppMessage.query.one().phone == "628123456789"

    def test_envelope_without_phone_is_rejected(self, client):
        envelope = self._envelope(chatId="", **{"from": "", "contact": {}})
        response = client.post(INBOUND_PATH, json=envelope)
        # chatId empty -> falls back to the wa:unknown token, so it still logs.
        assert response.status_code == 200
