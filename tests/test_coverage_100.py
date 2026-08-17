"""
Targeted tests to reach 100% coverage for:
- app/services/whatsapp.py
- app/services/reminders.py
- app/services/message_service.py
"""
import json
import re
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch
from urllib import error
from urllib.parse import urlsplit

import pytest

from app.models import Booking, Customer, ReminderLog, ServiceType, WhatsAppMessage, db
from app.services import whatsapp as wa
from app.services.whatsapp import (
    _SESSION_UUID_CACHE,
    BridgeProfile,
    BridgeWhatsAppGateway,
    WhatsAppGateway,
    _openwa_request,
    discover_bridge_base_url,
    discover_bridge_profile,
)
from app.services.reminders import ReminderService
from app.services.message_service import MessageService
from app.services.settings_store import set_setting

BASE_URL = "http://openwa-test:2785"
SESSION_NAME = "default"
SESSION_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


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


# --------------------------------------------------------------------------- #
# whatsapp.py
# --------------------------------------------------------------------------- #
class TestWhatsAppCoverage:
    def test_openwa_request_server_error_status_is_returned(self, openwa_env):
        """A 5xx is reported as-is instead of being swallowed.

        The old bridge probe treated any non-2xx as "keep looking at the next
        candidate host". There are no candidates now, so the status has to reach
        the caller.
        """
        with patch("app.services.whatsapp.request.urlopen", return_value=_resp(status=500)):
            assert _openwa_request("GET", "/api/health/ready") == (500, {"ok": True})

    def test_discover_uses_env_base_url(self, app, openwa_env, monkeypatch):
        """OPENWA_BASE_URL is the single source of the gateway address."""
        monkeypatch.setenv("OPENWA_BASE_URL", "http://env-host:2785")
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r"/api/health/ready": (200, "{}")}),
            ):
                assert discover_bridge_base_url() == "http://env-host:2785"

    def test_discover_returns_empty_when_health_fails(self, app, openwa_env):
        """Health check not 200 means "no gateway" for every caller."""
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r"/api/health/ready": (500, "{}")}),
            ):
                assert discover_bridge_base_url() == ""

    def test_discover_returns_empty_when_unconfigured(self, app, monkeypatch):
        """No API key means no request is attempted at all."""
        monkeypatch.setenv("OPENWA_BASE_URL", BASE_URL)
        monkeypatch.delenv("OPENWA_API_KEY", raising=False)
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen") as mock_open:
                assert discover_bridge_base_url() == ""
            mock_open.assert_not_called()

    def test_discover_ignores_extra_candidates(self, app, openwa_env):
        """extra_candidates survives only for signature compatibility."""
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({r"/api/health/ready": (200, "{}")}),
            ):
                result = discover_bridge_base_url(extra_candidates=["", "http://extra-host:3000"])
        assert result == BASE_URL

    def test_profile_fields_come_from_the_session_record(self, app, openwa_session):
        """Paths are fixed and the API key is never surfaced to templates."""
        session_body = json.dumps({
            "id": SESSION_UUID, "name": "cs-2", "status": "ready",
        })
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=_router({
                    r"/api/health/ready": (200, "{}"),
                    rf"/api/sessions/{SESSION_UUID}": (200, session_body),
                }),
            ):
                profile = discover_bridge_profile()
        assert profile is not None
        assert profile.send_path == "/api/sessions/{session}/messages/send-text"
        assert profile.qr_path == "/whatsapp/qr"
        assert profile.api_key == ""
        assert profile.instance_id == "cs-2"
        assert profile.connected is True
        assert profile.detected_from == "openwa:ready"

    def test_profile_when_session_lookup_is_unreachable(self, app, openwa_session):
        """Gateway reachable, session fetch failing: not connected, no status."""
        with app.app_context():
            with patch(
                "app.services.whatsapp.discover_bridge_base_url",
                return_value=BASE_URL,
            ), patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=Exception("down"),
            ):
                profile = discover_bridge_profile()
        assert profile is not None
        assert profile.detected_from == "openwa"
        assert profile.connected is False
        assert profile.has_qr is False
        assert profile.auth_required is True
        assert profile.api_key == ""

    def test_abstract_gateway_raises_not_implemented(self):
        """Calling the abstract send_message raises NotImplementedError."""

        class Concrete(WhatsAppGateway):
            def send_message(self, phone, text, chat_id=None):
                return super().send_message(phone, text, chat_id=chat_id)

        with pytest.raises(NotImplementedError):
            Concrete().send_message("628", "hi")

    def test_bridge_send_unconfigured_gateway(self, app, monkeypatch):
        """No API key: the session cannot be resolved, so nothing is sent.

        Replaces the old "profile with an empty base_url" case: the base URL is
        no longer discovered, so the failure mode is an unresolvable session.
        """
        monkeypatch.setenv("OPENWA_BASE_URL", BASE_URL)
        monkeypatch.delenv("OPENWA_API_KEY", raising=False)
        _SESSION_UUID_CACHE.clear()
        with app.app_context():
            with patch("app.services.whatsapp.request.urlopen") as mock_open:
                ok, status = BridgeWhatsAppGateway().send_message("628123456789", "hi")
            mock_open.assert_not_called()
        assert ok is False
        assert status == "bridge-not-found"

    def test_bridge_send_http_error(self, app, openwa_session):
        """urlopen raising HTTPError with no body returns bridge-http-<code>."""
        http_error = error.HTTPError(
            url=f"{BASE_URL}/api/sessions/{SESSION_UUID}/messages/send-text",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=http_error,
            ):
                ok, status = BridgeWhatsAppGateway().send_message(
                    "628123456789", "hi", chat_id="628123456789@c.us",
                )
        assert ok is False
        assert status == "bridge-http-401"

    def test_bridge_send_http_error_with_body(self, app, openwa_session):
        """An HTTPError carrying OpenWA's message surfaces that message."""
        http_error = error.HTTPError(
            url=f"{BASE_URL}/api/sessions/{SESSION_UUID}/messages/send-text",
            code=422,
            msg="Unprocessable",
            hdrs=None,
            fp=None,
        )
        http_error.read = MagicMock(return_value=b'{"message": ["chatId is required"]}')
        with app.app_context():
            with patch(
                "app.services.whatsapp.request.urlopen",
                side_effect=http_error,
            ):
                ok, status = BridgeWhatsAppGateway().send_message("628123456789", "hi")
        assert ok is False
        assert status == "chatId is required"


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
