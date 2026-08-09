"""
Coverage tests for /settings actions, /inbox rendering, and WhatsApp gateway.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
from app.models import (
    db, Customer, ServiceType, Booking, WhatsAppMessage, AuditLog
)


class TestSettingsServiceCRUD:
    """Test /settings service create/update/delete/toggle actions (admin only)."""

    def test_settings_get(self, session_login, app):
        resp = session_login.get("/settings")
        assert resp.status_code == 200

    def test_service_create_success(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "service_create",
            "service_name": "Nano Coating XL",
            "service_duration": "3",
            "service_unit": "jam",
        })
        assert resp.status_code == 200
        with app.app_context():
            svc = ServiceType.query.filter_by(name="Nano Coating XL").first()
            assert svc is not None
            assert svc.duration_minutes == 180

    def test_service_create_short_name(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "service_create",
            "service_name": "ab",
            "service_duration": "60",
            "service_unit": "menit",
        })
        assert resp.status_code == 200
        assert "minimal 3 karakter".encode() in resp.data

    def test_service_create_invalid_duration(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "service_create",
            "service_name": "Bad Duration Svc",
            "service_duration": "abc",
            "service_unit": "menit",
        })
        assert resp.status_code == 200
        assert "angka".encode() in resp.data

    def test_service_create_duplicate(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "service_create",
            "service_name": "Cuci Mobil",  # exists from bootstrap
            "service_duration": "30",
            "service_unit": "menit",
        })
        assert resp.status_code == 200
        assert "sudah ada".encode() in resp.data

    def test_service_update_success(self, session_login, app):
        with app.app_context():
            svc = ServiceType(name="Temp Svc Update", duration_minutes=60, active=True)
            db.session.add(svc)
            db.session.commit()
            sid = svc.id
        resp = session_login.post("/settings", data={
            "action": "service_update",
            "service_id": str(sid),
            "service_name": "Temp Svc Updated",
            "service_duration": "2",
            "service_unit": "jam",
        })
        assert resp.status_code == 200
        with app.app_context():
            svc = ServiceType.query.get(sid)
            assert svc.name == "Temp Svc Updated"
            assert svc.duration_minutes == 120

    def test_service_update_not_found(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "service_update",
            "service_id": "99999",
            "service_name": "Ghost",
            "service_duration": "60",
            "service_unit": "menit",
        })
        assert resp.status_code == 200
        assert "tidak ditemukan".encode() in resp.data

    def test_service_delete_success(self, session_login, app):
        with app.app_context():
            svc = ServiceType(name="Deletable Svc", duration_minutes=30, active=True)
            db.session.add(svc)
            db.session.commit()
            sid = svc.id
        resp = session_login.post("/settings", data={
            "action": "service_delete",
            "service_id": str(sid),
        })
        assert resp.status_code == 200
        with app.app_context():
            assert ServiceType.query.get(sid) is None

    def test_service_delete_in_use(self, session_login, app):
        with app.app_context():
            svc = ServiceType(name="InUse Svc", duration_minutes=30, active=True)
            customer = Customer(name="C", phone="628777000111")
            db.session.add_all([svc, customer])
            db.session.commit()
            booking = Booking(
                customer_id=customer.id, service_type_id=svc.id,
                scheduled_start=datetime.now(), scheduled_end=datetime.now() + timedelta(hours=1),
                status="dikonfirmasi",
            )
            db.session.add(booking)
            db.session.commit()
            sid = svc.id
        resp = session_login.post("/settings", data={
            "action": "service_delete",
            "service_id": str(sid),
        })
        assert resp.status_code == 200
        assert "masih digunakan".encode() in resp.data

    def test_service_toggle(self, session_login, app):
        with app.app_context():
            svc = ServiceType(name="Toggle Svc", duration_minutes=30, active=True)
            db.session.add(svc)
            db.session.commit()
            sid = svc.id
        resp = session_login.post("/settings", data={
            "action": "service_toggle",
            "service_id": str(sid),
        })
        assert resp.status_code == 200
        with app.app_context():
            assert ServiceType.query.get(sid).active is False

    def test_service_toggle_not_found(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "service_toggle",
            "service_id": "99999",
        })
        assert resp.status_code == 200


class TestSettingsSave:
    """Test /settings save and test_send actions."""

    def test_save_settings(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "save",
            "booking_done_template": "Custom done {nama}",
            "reschedule_template": "Custom reschedule {nama}",
        })
        assert resp.status_code == 200
        assert "disimpan".encode() in resp.data

    def test_save_invalid_wa_mode_defaults(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "save",
        })
        assert resp.status_code == 200

    def test_test_send_missing_phone(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "test_send",
            "test_phone": "",
        })
        assert resp.status_code == 200
        assert "wajib diisi".encode() in resp.data

    def test_test_send_with_phone(self, session_login, app):
        resp = session_login.post("/settings", data={
            "action": "test_send",
            "test_phone": "628123456789",
            "test_message": "Hello test",
        })
        assert resp.status_code == 200


class TestInboxRendering:
    """Test /inbox endpoint with messages."""

    def test_inbox_empty(self, session_login, app):
        resp = session_login.get("/inbox")
        assert resp.status_code == 200

    def test_inbox_with_messages(self, session_login, app):
        with app.app_context():
            customer = Customer(name="Inbox Cust", phone="628888000111")
            db.session.add(customer)
            db.session.commit()
            for i in range(3):
                msg = WhatsAppMessage(
                    direction="inbound" if i % 2 == 0 else "outbound",
                    phone="628888000111",
                    message_text=f"Message {i}",
                    payload_json="{}",
                    status="received",
                    created_at=datetime.utcnow(),
                )
                db.session.add(msg)
            db.session.commit()
        resp = session_login.get("/inbox")
        assert resp.status_code == 200


class TestWhatsAppInbound:
    """Test /api/whatsapp/inbound processing paths."""

    def test_inbound_creates_customer(self, client, app):
        resp = client.post("/api/whatsapp/inbound", json={
            "phone": "628999000111",
            "text": "Halo saya mau booking",
            "from_me": False,
            "contact_name": "Inbound User",
        })
        assert resp.status_code == 200
        with app.app_context():
            assert WhatsAppMessage.query.filter_by(phone="628999000111").first() is not None

    def test_inbound_booking_form(self, client, app):
        form_text = """Nama: Form User
No HP: 628999000222
Merk & Type Mobil: Honda Jazz
Nomor Polisi: B 1234 XY
Paket: Coating Premium
Tanggal masuk: 20-12-2026"""
        resp = client.post("/api/whatsapp/inbound", json={
            "phone": "628999000222",
            "text": form_text,
            "from_me": False,
            "contact_name": "Form User",
        })
        assert resp.status_code == 200

    def test_inbound_from_me_ignored(self, client, app):
        resp = client.post("/api/whatsapp/inbound", json={
            "phone": "628999000333",
            "text": "Outbound echo",
            "from_me": True,
        })
        assert resp.status_code == 200
