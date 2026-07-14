"""
Targeted tests to reach 100% coverage for:
- app/services/whatsapp.py
- app/services/reminders.py
- app/services/message_service.py
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch
from urllib import error

import pytest

from app.models import Booking, Customer, ReminderLog, ServiceType, WhatsAppMessage, db
from app.services import whatsapp as wa
from app.services.whatsapp import (
    BridgeProfile,
    BridgeWhatsAppGateway,
    WhatsAppGateway,
    _probe_bridge,
    discover_bridge_base_url,
    discover_bridge_profile,
)
from app.services.reminders import ReminderService
from app.services.message_service import MessageService
from app.services.settings_store import set_setting


def _resp(status=200, body='{"ok": true}'):
    """Build a mock context-manager urlopen response."""
    m = MagicMock()
    m.status = status
    m.read.return_value = body.encode("utf-8")
    m.__enter__ = MagicMock(return_value=m)
    m.__exit__ = MagicMock(return_value=False)
    return m


# --------------------------------------------------------------------------- #
# whatsapp.py
# --------------------------------------------------------------------------- #
class TestWhatsAppCoverage:
    def test_probe_bridge_server_error_status(self):
        """status >= 500 keeps looping and ultimately returns False (55->51)."""
        with patch("app.services.whatsapp.request.urlopen", return_value=_resp(status=500)):
            assert _probe_bridge("http://localhost:3000", "/qr") is False

    def test_discover_uses_env_url(self, app, monkeypatch):
        """WHATSAPP_BRIDGE_BASE_URL is added to candidates (line 73)."""
        monkeypatch.setenv("WHATSAPP_BRIDGE_BASE_URL", "http://env-host:3000")
        with app.app_context():
            with patch("app.services.whatsapp._probe_bridge", return_value=False):
                assert discover_bridge_base_url() == ""

    def test_discover_public_base_without_hostname(self, app):
        """public_base_url without a hostname skips the append (77->80)."""
        with app.app_context():
            set_setting("public_base_url", "not-a-url")
            with patch("app.services.whatsapp._probe_bridge", return_value=False):
                assert discover_bridge_base_url() == ""

    def test_discover_skips_empty_candidate(self, app):
        """Empty candidate strings are skipped (line 94)."""
        with app.app_context():
            with patch("app.services.whatsapp._probe_bridge", return_value=False):
                assert discover_bridge_base_url(extra_candidates=[""]) == ""

    def test_profile_configured_paths_status_with_env_key(self, app, monkeypatch):
        """Configured qr/send paths, failing qr probes, status found with env key.

        Covers 126-127, 129-130, 133->144, 138->133, 158-true, 173->176.
        """
        monkeypatch.setenv("WHATSAPP_BRIDGE_API_KEY", "envkey")
        with app.app_context():
            set_setting("bridge_qr_path", "myqr")
            set_setting("bridge_send_path", "mysend")
            with patch(
                "app.services.whatsapp.discover_bridge_base_url",
                return_value="http://localhost:3000",
            ), patch(
                "app.services.whatsapp.request.urlopen",
                return_value=_resp(status=500),
            ), patch(
                "app.services.whatsapp._request_json",
                return_value={"connected": True, "instance_id": "abc"},
            ):
                profile = discover_bridge_profile()
        assert profile is not None
        assert profile.send_path == "/mysend"
        assert profile.qr_path == "/qr"
        assert profile.api_key == "envkey"
        assert profile.connected is True

    def test_profile_no_status_qr_exception(self, app, monkeypatch):
        """No status payload and qr probes raising exceptions.

        Covers 141-142, 152->158, 154->152, 158->176.
        """
        monkeypatch.delenv("WHATSAPP_BRIDGE_API_KEY", raising=False)
        with app.app_context():
            with patch(
                "app.services.whatsapp.discover_bridge_base_url",
                return_value="http://localhost:3000",
            ), patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=Exception("down"),
            ), patch(
                "app.services.whatsapp._request_json",
                return_value=None,
            ):
                profile = discover_bridge_profile()
        assert profile is not None
        assert profile.detected_from == "heuristic"
        assert profile.connected is False
        assert profile.api_key == ""

    def test_abstract_gateway_raises_not_implemented(self):
        """Calling the abstract send_message raises NotImplementedError (line 194)."""

        class Concrete(WhatsAppGateway):
            def send_message(self, phone, text, chat_id=None):
                return super().send_message(phone, text, chat_id=chat_id)

        with pytest.raises(NotImplementedError):
            Concrete().send_message("628", "hi")

    def test_bridge_send_missing_url(self, app):
        """Profile with empty base_url returns bridge-missing-url (line 215)."""
        profile = BridgeProfile(
            base_url="",
            send_path="/send",
            qr_path="/qr",
            api_key="",
            instance_id="",
            auth_required=False,
            connected=True,
            has_qr=False,
            detected_from="heuristic",
        )
        with app.app_context():
            with patch(
                "app.services.whatsapp.discover_bridge_profile",
                return_value=profile,
            ):
                ok, status = BridgeWhatsAppGateway().send_message("628", "hi")
        assert ok is False
        assert status == "bridge-missing-url"

    def test_bridge_send_http_error(self, app):
        """urlopen raising HTTPError returns bridge-http-<code> (line 243)."""
        profile = BridgeProfile(
            base_url="http://localhost:3000",
            send_path="/send",
            qr_path="/qr",
            api_key="key",
            instance_id="inst",
            auth_required=False,
            connected=True,
            has_qr=False,
            detected_from="heuristic",
        )
        http_error = error.HTTPError(
            url="http://localhost:3000/send",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        with app.app_context():
            with patch(
                "app.services.whatsapp.discover_bridge_profile",
                return_value=profile,
            ), patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=http_error,
            ):
                ok, status = BridgeWhatsAppGateway().send_message("628", "hi", chat_id="628@c.us")
        assert ok is False
        assert status == "bridge-http-401"


# --------------------------------------------------------------------------- #
# reminders.py
# --------------------------------------------------------------------------- #
def _make_confirmed_booking(scheduled_start):
    service = ServiceType.query.first()
    customer = Customer(name="Rem Test", phone="628123456789")
    booking = Booking(
        customer=customer,
        service_type=service,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_start + timedelta(hours=2),
        status="dikonfirmasi",
    )
    db.session.add_all([customer, booking])
    db.session.commit()
    return booking


class TestRemindersCoverage:
    def test_send_reminder_sender_exception_rolls_back(self, app):
        """message_sender raising triggers rollback and returns False (133-135)."""
        with app.app_context():
            booking = _make_confirmed_booking(datetime.now() + timedelta(days=1))
            sender = Mock(side_effect=Exception("send failed"))
            service = ReminderService(message_sender=sender)
            result = service.send_reminder(booking, "H1", datetime.now())
            assert result is False
            assert ReminderLog.query.count() == 0

    def test_run_due_reminders_sends_and_counts(self, app):
        """A due booking is sent and counted (162-163)."""
        with app.app_context():
            now = datetime.now()
            booking = _make_confirmed_booking(now + timedelta(days=1))
            sender = Mock()
            service = ReminderService(
                reminder_rules={"H1": timedelta(days=1)},
                message_sender=sender,
            )
            sent = service.run_due_reminders(now)
            assert sent == 1
            sender.assert_called_once()

    def test_get_pending_reminders_lists_due(self, app):
        """A due booking appears in pending reminders."""
        with app.app_context():
            now = datetime.now()
            booking = _make_confirmed_booking(now + timedelta(days=1))
            service = ReminderService(reminder_rules={"H1": timedelta(days=1)})
            pending = service.get_pending_reminders(now)
            assert len(pending) == 1
            assert pending[0][1] == "H1"

    def test_run_due_reminders_skips_when_send_fails(self, app):
        """send_reminder returning False is not counted (162->154)."""
        with app.app_context():
            now = datetime.now()
            service_type = ServiceType.query.first()
            customer = Customer(name="No Phone", phone="")
            booking = Booking(
                customer=customer,
                service_type=service_type,
                scheduled_start=now + timedelta(days=1),
                scheduled_end=now + timedelta(days=1, hours=2),
                status="dikonfirmasi",
            )
            db.session.add_all([customer, booking])
            db.session.commit()
            service = ReminderService(reminder_rules={"H1": timedelta(days=1)})
            sent = service.run_due_reminders(now)
            assert sent == 0

    def test_get_pending_reminders_skips_already_sent(self, app):
        """Already-sent reminders are skipped in pending list (line 184)."""
        with app.app_context():
            now = datetime.now()
            booking = _make_confirmed_booking(now + timedelta(days=1))
            db.session.add(
                ReminderLog(
                    booking_id=booking.id,
                    reminder_type="H1",
                    scheduled_for=now,
                    sent_at=now,
                    status="sent",
                )
            )
            db.session.commit()
            service = ReminderService(reminder_rules={"H1": timedelta(days=1)})
            pending = service.get_pending_reminders(now)
            assert pending == []


# --------------------------------------------------------------------------- #
# message_service.py
# --------------------------------------------------------------------------- #
class TestMessageServiceCoverage:
    def test_parse_booking_form_skips_unknown_label(self):
        """Unknown labelled lines are skipped (86->76)."""
        text = (
            "Nama: John\n"
            "Catatan: sesuatu\n"
            "No HP: 628123456789\n"
            "Paket: Coating\n"
        )
        fields = MessageService.parse_booking_form(text)
        assert fields is not None
        assert fields["name"] == "John"
        assert "sesuatu" not in fields.values()

    def test_log_message_invalid_timestamp_falls_back(self, app):
        """A timestamp that raises falls back to now() (212-213)."""
        with app.app_context():
            msg = MessageService.log_message("628", "hi", timestamp=10 ** 12)
            assert isinstance(msg, WhatsAppMessage)
            assert msg.created_at is not None
