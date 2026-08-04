"""
Targeted tests to push app/app.py to 100% coverage.
Covers helper functions, route branches, and edge cases not exercised elsewhere.
"""
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

import app.app as app_module
from app.app import (
    resolve_real_number,
    extract_lid,
    parse_schedule_text,
    create_booking_from_form,
    build_message_view,
    bootstrap_defaults,
)
from app.models import (
    AuditLog,
    Booking,
    Customer,
    MaintenanceReminder,
    ServiceType,
    User,
    WhatsAppMessage,
    db,
)


def _mk_message(phone="628123456789", payload=None, direction="inbound", text="hi"):
    msg = WhatsAppMessage(
        direction=direction,
        phone=phone,
        message_text=text,
        payload_json=payload if isinstance(payload, str) else json.dumps(payload or {}),
        status="received",
        created_at=datetime(2026, 7, 13, 10, 30, 0),
    )
    db.session.add(msg)
    db.session.commit()
    return msg


def _mk_booking(status="dikonfirmasi", service_name="Coating Premium", phone="628123456789"):
    service = ServiceType.query.filter_by(name=service_name).first()
    customer = Customer(name="Cust", phone=phone)
    booking = Booking(
        customer=customer,
        service_type=service,
        scheduled_start=datetime(2026, 7, 20, 10, 0),
        scheduled_end=datetime(2026, 7, 20, 12, 0),
        status=status,
        source="manual",
    )
    db.session.add_all([customer, booking])
    db.session.commit()
    return booking


class _FailedSend:
    status = "failed"


# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #
class TestResolveRealNumber:
    def test_chat_id_cus_number_too_short_falls_through(self):
        # chat_id @c.us but number too short -> skip, no phone -> ""
        assert resolve_real_number({"chat_id": "12@c.us"}, "") == ""

    def test_valid_phone_fallback(self):
        assert resolve_real_number({}, "628123456789") == "628123456789"


class TestExtractLid:
    def test_chat_id_lid_invalid_falls_through(self):
        assert extract_lid({"chat_id": "abc@lid"}, "") == ""

    def test_phone_lid_prefix_invalid(self):
        assert extract_lid({}, "lid:abc") == ""

    def test_phone_lid_prefix_valid(self):
        assert extract_lid({}, "lid:123456789") == "123456789"


class TestParseScheduleText:
    def test_invalid_concrete_date_returns_none(self):
        assert parse_schedule_text("32-13-2025") is None

    def test_relative_minggu(self):
        result = parse_schedule_text("2 minggu")
        assert result is not None
        assert result > datetime.utcnow()

    def test_relative_hari(self):
        result = parse_schedule_text("3 hari")
        assert result is not None

    def test_relative_bulan(self):
        result = parse_schedule_text("1 bulan")
        assert result is not None

    def test_two_digit_year(self):
        result = parse_schedule_text("05-06-25")
        assert result is not None
        assert result.year == 2025


class TestCreateBookingFromForm:
    def test_missing_phone_returns_none(self, app):
        with app.app_context():
            assert create_booking_from_form({"name": "A", "package": "X"}, {}) is None

    def test_creates_lainnya_when_missing(self, app):
        with app.app_context():
            # Remove every service so semantic match fails and Lainnya must be created.
            ServiceType.query.delete()
            db.session.commit()
            form = {
                "name": "New Cust",
                "phone": "08123456789",
                "package": "Unknown Package",
            }
            booking = create_booking_from_form(form, {})
            assert booking is not None
            assert ServiceType.query.filter_by(name="Lainnya").first() is not None


class TestBuildMessageView:
    def test_invalid_payload_json(self, app):
        with app.app_context():
            msg = _mk_message(payload="{not valid json")
            view = build_message_view(msg)
            assert view["id"] == msg.id

    def test_group_chat(self, app):
        with app.app_context():
            msg = _mk_message(phone="12345@g.us", payload={"chat_id": "12345@g.us"})
            view = build_message_view(msg)
            assert view["number_label"] == "Grup WhatsApp"
            assert view["conv_key"].startswith("g:")
            assert view["reply_to"] == "12345@g.us"

    def test_lid_from_chat_id(self, app):
        with app.app_context():
            msg = _mk_message(phone="lid:123456789", payload={"chat_id": "123456789@lid"})
            view = build_message_view(msg)
            assert view["number_label"] == "Nomor private"
            assert view["conv_key"].startswith("l:")
            assert view["reply_to"] == "123456789@lid"

    def test_lid_from_phone_prefix(self, app):
        with app.app_context():
            msg = _mk_message(phone="lid:987654321", payload={})
            view = build_message_view(msg)
            assert view["conv_key"].startswith("l:")
            assert view["reply_to"] == "987654321@lid"

    def test_real_number_without_customer(self, app):
        with app.app_context():
            msg = _mk_message(phone="628111222333", payload={"contact_number": "628111222333"})
            view = build_message_view(msg)
            assert view["number_label"] == "628111222333"
            assert view["conv_key"].startswith("n:")
            assert view["reply_to"] == "628111222333@c.us"

    def test_bare_unknown_phone(self, app):
        with app.app_context():
            msg = _mk_message(phone="wa:xyz", payload={})
            view = build_message_view(msg)
            assert view["number_label"] == "Nomor private"
            assert view["conv_key"].startswith("p:")
            assert view["reply_to"] == ""

    def test_plain_unknown_phone(self, app):
        with app.app_context():
            msg = _mk_message(phone="plainstring", payload={})
            view = build_message_view(msg)
            assert view["number_label"] == ""
            assert view["conv_key"].startswith("p:")


class TestBootstrapDefaults:
    def test_creates_users_and_is_idempotent(self, app):
        with app.app_context():
            User.query.delete()
            db.session.commit()
            bootstrap_defaults()
            assert User.query.filter_by(username="admin").first() is not None
            count_after = ServiceType.query.count()
            # Running again should not duplicate services or users.
            bootstrap_defaults()
            assert ServiceType.query.count() == count_after


def _failed_send(*args, **kwargs):
    m = Mock()
    m.status = "failed"
    return m


@pytest.fixture
def no_bridge():
    with patch("app.app.discover_bridge_profile", return_value=None):
        yield


# --------------------------------------------------------------------------- #
# /login
# --------------------------------------------------------------------------- #
class TestLoginRoute:
    def test_login_success(self, client, app):
        with app.app_context():
            user = User(username="loginok", role="admin", active=True)
            user.set_password("secret123")
            db.session.add(user)
            db.session.commit()
        resp = client.post(
            "/login", data={"username": "loginok", "password": "secret123"}
        )
        assert resp.status_code == 302


# --------------------------------------------------------------------------- #
# /bookings
# --------------------------------------------------------------------------- #
class TestBookingsRoute:
    def test_get_renders_selesai_notify(self, session_login, app):
        with app.app_context():
            _mk_booking(status="selesai", service_name="Cuci Mobil")
        resp = session_login.get("/bookings")
        assert resp.status_code == 200

    def test_update_status_not_found(self, session_login):
        resp = session_login.post(
            "/bookings",
            data={"action": "update_status", "booking_id": "99999", "status": "selesai"},
        )
        assert resp.status_code == 200
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_update_status_invalid(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
        resp = session_login.post(
            "/bookings",
            data={"action": "update_status", "booking_id": bid, "status": "bogus"},
        )
        assert "tidak valid" in resp.get_data(as_text=True)

    def test_update_status_selesai_non_coating(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(service_name="Cuci Mobil").id
        resp = session_login.post(
            "/bookings",
            data={"action": "update_status", "booking_id": bid, "status": "selesai"},
        )
        assert resp.status_code == 200

    def test_update_status_selesai_coating_creates_reminder(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(service_name="Coating Premium").id
        resp = session_login.post(
            "/bookings",
            data={"action": "update_status", "booking_id": bid, "status": "selesai"},
        )
        assert resp.status_code == 200
        with app.app_context():
            assert MaintenanceReminder.query.filter_by(booking_id=bid).first() is not None

    def test_update_status_selesai_coating_existing_reminder(self, session_login, app):
        with app.app_context():
            booking = _mk_booking(service_name="PPF")
            bid = booking.id
            db.session.add(
                MaintenanceReminder(
                    booking_id=bid,
                    customer_id=booking.customer_id,
                    service_type="PPF",
                    completed_at=datetime.utcnow(),
                    maintenance_due_at=datetime.utcnow() + timedelta(days=180),
                )
            )
            db.session.commit()
        resp = session_login.post(
            "/bookings",
            data={"action": "update_status", "booking_id": bid, "status": "selesai"},
        )
        assert resp.status_code == 200
        with app.app_context():
            assert MaintenanceReminder.query.filter_by(booking_id=bid).count() == 1

    def test_notify_customer_not_found(self, session_login):
        resp = session_login.post(
            "/bookings",
            data={"action": "notify_customer", "booking_id": "99999", "message": "hi"},
        )
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_notify_customer_empty_text(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
        resp = session_login.post(
            "/bookings",
            data={"action": "notify_customer", "booking_id": bid, "message": ""},
        )
        assert "tidak boleh kosong" in resp.get_data(as_text=True)

    def test_notify_customer_no_target(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(phone="not-a-number").id
        resp = session_login.post(
            "/bookings",
            data={"action": "notify_customer", "booking_id": bid, "message": "hi"},
        )
        assert "tidak tersedia" in resp.get_data(as_text=True)

    def test_notify_customer_send_failed(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
        with patch("app.app.send_and_log_message", side_effect=_failed_send):
            resp = session_login.post(
                "/bookings",
                data={"action": "notify_customer", "booking_id": bid, "message": "hi"},
            )
        assert "Gagal mengirim" in resp.get_data(as_text=True)

    def test_notify_customer_success(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
        resp = session_login.post(
            "/bookings",
            data={"action": "notify_customer", "booking_id": bid, "message": "hi"},
        )
        assert "terkirim" in resp.get_data(as_text=True)

    def test_create_with_package_match(self, session_login):
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "Pkg Cust",
                "phone": "628999888777",
                "package_name": "gold detailing",
                "scheduled_start": "2026-08-01T10:00",
            },
        )
        assert resp.status_code == 200

    def test_create_with_package_no_match(self, session_login):
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "Pkg Cust",
                "phone": "628999888666",
                "package_name": "qwerty zxcvb",
                "scheduled_start": "2026-08-01T10:00",
            },
        )
        assert resp.status_code == 200

    def test_create_package_no_match_lainnya_missing(self, session_login, app):
        with app.app_context():
            ServiceType.query.filter_by(name="Lainnya").delete()
            db.session.commit()
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "Pkg Cust",
                "phone": "628999888555",
                "package_name": "qwerty zxcvb",
                "scheduled_start": "2026-08-01T10:00",
            },
        )
        assert "Lainnya" in resp.get_data(as_text=True)

    def test_create_invalid_service_id(self, session_login):
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "X",
                "phone": "628111000999",
                "service_id": "99999",
                "scheduled_start": "2026-08-01T10:00",
            },
        )
        assert "Layanan tidak ditemukan" in resp.get_data(as_text=True)

    def test_create_invalid_date(self, session_login, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "X",
                "phone": "628111000888",
                "service_id": sid,
                "scheduled_start": "not-a-date",
            },
        )
        assert "Format tanggal tidak valid" in resp.get_data(as_text=True)

    def test_create_out_of_hours(self, session_login, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "X",
                "phone": "628111000777",
                "service_id": sid,
                "scheduled_start": "2026-08-01T07:00",
            },
        )
        assert "jam operasional" in resp.get_data(as_text=True)

    def test_create_conflict(self, session_login, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
            _mk_booking(service_name="Cuci Mobil", phone="628000000001")
        # existing booking is at 2026-07-20 10:00-12:00
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "X",
                "phone": "628111000666",
                "service_id": sid,
                "scheduled_start": "2026-07-20T10:00",
            },
        )
        assert "bentrok" in resp.get_data(as_text=True)

    def test_create_success_new_customer(self, session_login, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "Fresh Cust",
                "phone": "628111000555",
                "service_id": sid,
                "scheduled_start": "2026-09-01T10:00",
            },
        )
        assert "berhasil dibuat" in resp.get_data(as_text=True)

    def test_create_success_existing_customer(self, session_login, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
            db.session.add(Customer(name="Existing", phone="628111000444"))
            db.session.commit()
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "Existing",
                "phone": "628111000444",
                "service_id": sid,
                "scheduled_start": "2026-09-02T10:00",
            },
        )
        assert "berhasil dibuat" in resp.get_data(as_text=True)

    def test_create_lainnya_missing(self, session_login, app):
        with app.app_context():
            ServiceType.query.filter_by(name="Lainnya").delete()
            db.session.commit()
        resp = session_login.post(
            "/bookings",
            data={
                "customer_name": "X",
                "phone": "628111000222",
                "scheduled_start": "2026-09-03T10:00",
            },
        )
        assert "Lainnya" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# /bookings/<id>/edit
# --------------------------------------------------------------------------- #
class TestEditBookingRoute:
    def test_edit_not_found(self, session_login):
        resp = session_login.get("/bookings/99999/edit")
        assert resp.status_code == 404

    def test_edit_missing_schedule(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={"action": "update", "customer_name": "N", "phone": "628111", "scheduled_start": ""},
        )
        assert "Jadwal wajib diisi" in resp.get_data(as_text=True)

    def test_edit_invalid_date(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628111000111",
                "service_id": sid,
                "scheduled_start": "bad-date",
            },
        )
        assert "Format tanggal tidak valid" in resp.get_data(as_text=True)

    def test_edit_package_match(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628111000111",
                "package_name": "gold detailing",
                "scheduled_start": "2026-09-10T10:00",
            },
        )
        assert resp.status_code in (200, 302)

    def test_edit_package_no_match(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628111000111",
                "package_name": "qwerty zxcvb",
                "scheduled_start": "2026-09-11T10:00",
            },
        )
        assert resp.status_code in (200, 302)

    def test_edit_package_match_no_variant(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628111000111",
                "package_name": "gold",
                "scheduled_start": "2026-09-18T10:00",
            },
        )
        assert resp.status_code in (200, 302)

    def test_edit_package_no_match_lainnya_missing(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
            ServiceType.query.filter_by(name="Lainnya").delete()
            db.session.commit()
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628111000111",
                "package_name": "qwerty zxcvb",
                "scheduled_start": "2026-09-11T10:00",
            },
        )
        assert resp.status_code in (200, 302)

    def test_edit_default_lainnya(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(service_name="Cuci Mobil", phone="628111000121").id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628111000121",
                "scheduled_start": "2026-09-19T10:00",
            },
        )
        assert resp.status_code in (200, 302)

    def test_edit_invalid_service_id(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628111000111",
                "service_id": "99999",
                "scheduled_start": "2026-09-12T10:00",
            },
        )
        assert "Layanan tidak ditemukan" in resp.get_data(as_text=True)

    def test_edit_out_of_hours(self, session_login, app):
        with app.app_context():
            bid = _mk_booking().id
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628111000111",
                "service_id": sid,
                "scheduled_start": "2026-09-13T07:00",
            },
        )
        assert "jam operasional" in resp.get_data(as_text=True)

    def test_edit_conflict(self, session_login, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
            _mk_booking(service_name="Cuci Mobil", phone="628000000009")
            bid = _mk_booking(service_name="Cuci Mobil", phone="628000000010").id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628000000010",
                "service_id": sid,
                "scheduled_start": "2026-07-20T10:00",
            },
        )
        assert "bentrok" in resp.get_data(as_text=True)

    def test_edit_duplicate_phone(self, session_login, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
            db.session.add(Customer(name="Other", phone="628777666555"))
            db.session.commit()
            bid = _mk_booking(service_name="Cuci Mobil", phone="628111222444").id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628777666555",
                "service_id": sid,
                "scheduled_start": "2026-09-14T10:00",
            },
        )
        assert "sudah terdaftar" in resp.get_data(as_text=True)

    def test_edit_success(self, session_login, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
            bid = _mk_booking(service_name="Cuci Mobil", phone="628111222333").id
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "Updated Name",
                "phone": "628111222333",
                "service_id": sid,
                "scheduled_start": "2026-09-15T10:00",
            },
        )
        assert resp.status_code == 302

    def test_edit_lainnya_missing(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(service_name="Cuci Mobil", phone="628111222999").id
            ServiceType.query.filter_by(name="Lainnya").delete()
            db.session.commit()
        resp = session_login.post(
            f"/bookings/{bid}/edit",
            data={
                "action": "update",
                "customer_name": "N",
                "phone": "628111222999",
                "scheduled_start": "2026-09-16T10:00",
            },
        )
        assert "Lainnya" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# /customers
# --------------------------------------------------------------------------- #
class TestCustomersRoute:
    def test_delete_not_found(self, session_login):
        resp = session_login.post("/customers", data={"action": "delete", "customer_id": "99999"})
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_delete_with_bookings(self, session_login, app):
        with app.app_context():
            cid = _mk_booking().customer_id
        resp = session_login.post("/customers", data={"action": "delete", "customer_id": cid})
        assert "masih punya booking" in resp.get_data(as_text=True)

    def test_delete_success(self, session_login, app):
        with app.app_context():
            c = Customer(name="Del", phone="628123000111")
            db.session.add(c)
            db.session.commit()
            cid = c.id
        resp = session_login.post("/customers", data={"action": "delete", "customer_id": cid})
        assert "berhasil dihapus" in resp.get_data(as_text=True)

    def test_create_missing_fields(self, session_login):
        resp = session_login.post("/customers", data={"action": "create", "name": "", "phone": ""})
        assert "wajib diisi" in resp.get_data(as_text=True)

    def test_create_duplicate(self, session_login, app):
        with app.app_context():
            db.session.add(Customer(name="Dup", phone="628123000222"))
            db.session.commit()
        resp = session_login.post(
            "/customers", data={"action": "create", "name": "New", "phone": "628123000222"}
        )
        assert "sudah terdaftar" in resp.get_data(as_text=True)

    def test_update_not_found(self, session_login):
        resp = session_login.post(
            "/customers",
            data={"action": "update", "customer_id": "99999", "name": "N", "phone": "628123000333"},
        )
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_update_success(self, session_login, app):
        with app.app_context():
            c = Customer(name="Old", phone="628123000444")
            db.session.add(c)
            db.session.commit()
            cid = c.id
        resp = session_login.post(
            "/customers",
            data={"action": "update", "customer_id": cid, "name": "New", "phone": "628123000444"},
        )
        assert "berhasil diperbarui" in resp.get_data(as_text=True)

    def test_create_success(self, session_login):
        resp = session_login.post(
            "/customers", data={"action": "create", "name": "Brand New", "phone": "628123000555"}
        )
        assert "berhasil ditambahkan" in resp.get_data(as_text=True)

    def test_search(self, session_login, app):
        with app.app_context():
            db.session.add(Customer(name="Searchable", phone="628123000666"))
            db.session.commit()
        resp = session_login.get("/customers?q=Searchable")
        assert resp.status_code == 200
        assert "Searchable" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# /customers/sync
# --------------------------------------------------------------------------- #
class TestCustomersSyncRoute:
    def test_sync_not_ok(self, session_login):
        with patch("app.app.fetch_whatsapp_contacts", return_value=(False, "bridge-not-found", [])):
            resp = session_login.post("/customers/sync", data={})
        assert resp.status_code == 302

    def test_sync_creates_and_skips(self, session_login):
        contacts = [
            {"number": "628123111000", "name": "New One"},
            {"number": "12", "lid": "x"},  # invalid -> skipped
        ]
        with patch("app.app.fetch_whatsapp_contacts", return_value=(True, "ok", contacts)):
            resp = session_login.post("/customers/sync", data={})
        assert resp.status_code == 302

    def test_sync_updates_existing(self, session_login, app):
        with app.app_context():
            db.session.add(
                Customer(name="WhatsApp 7777", phone="000000000", lid="123456789012345")
            )
            db.session.add(Customer(name="Existing", phone="628123111222", lid=None))
            db.session.commit()
        contacts = [
            {"number": "628123111333", "lid": "123456789012345", "name": "Real Name"},
            {"number": "628123111222", "lid": "999888777666555", "name": "Existing"},
        ]
        with patch("app.app.fetch_whatsapp_contacts", return_value=(True, "ok", contacts)):
            resp = session_login.post("/customers/sync", data={"saved_only": "false"})
        assert resp.status_code == 302

    def test_sync_create_integrity_error(self, session_login, app):
        with app.app_context():
            # Existing customer whose phone equals the lid we will try to create.
            db.session.add(Customer(name="Clash", phone="123456789012345", lid=None))
            db.session.commit()
        contacts = [{"lid": "123456789012345", "name": "Ghost"}]
        with patch("app.app.fetch_whatsapp_contacts", return_value=(True, "ok", contacts)):
            resp = session_login.post("/customers/sync", data={})
        assert resp.status_code == 302

    def test_sync_phone_upgrade_clash(self, session_login, app):
        with app.app_context():
            db.session.add(Customer(name="WhatsApp 0001", phone="000000001", lid="111222333444555"))
            db.session.add(Customer(name="Owner", phone="628123556000", lid=None))
            db.session.commit()
        contacts = [{"number": "628123556000", "lid": "111222333444555", "name": "X"}]
        with patch("app.app.fetch_whatsapp_contacts", return_value=(True, "ok", contacts)):
            resp = session_login.post("/customers/sync", data={})
        assert resp.status_code == 302

    def test_sync_no_change(self, session_login, app):
        with app.app_context():
            db.session.add(Customer(name="Real", phone="628123556111", lid="222333444555666"))
            db.session.commit()
        contacts = [{"number": "628123556111", "lid": "222333444555666", "name": "Real"}]
        with patch("app.app.fetch_whatsapp_contacts", return_value=(True, "ok", contacts)):
            resp = session_login.post("/customers/sync", data={})
        assert resp.status_code == 302


# --------------------------------------------------------------------------- #
# /users
# --------------------------------------------------------------------------- #
class TestUsersRoute:
    def test_create_user(self, session_login):
        resp = session_login.post(
            "/users", data={"username": "newuser", "password": "pw123", "role": "cs"}
        )
        assert resp.status_code == 200

    def test_create_existing_user(self, session_login, app):
        with app.app_context():
            u = User(username="dupuser", role="cs")
            u.set_password("x")
            db.session.add(u)
            db.session.commit()
        resp = session_login.post(
            "/users", data={"username": "dupuser", "password": "pw123", "role": "cs"}
        )
        assert resp.status_code == 200

    def test_create_user_invalid(self, session_login):
        resp = session_login.post(
            "/users", data={"username": "noRole", "password": "pw123", "role": ""}
        )
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# /inbox
# --------------------------------------------------------------------------- #
class TestInboxRoute:
    def test_inbox_renders(self, session_login, app):
        with app.app_context():
            _mk_message(phone="628123222000", payload={"contact_number": "628123222000"})
            _mk_message(phone="wa:bare", payload={})
        resp = session_login.get("/inbox")
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# /reschedule
# --------------------------------------------------------------------------- #
class TestRescheduleRoute:
    def test_send_reminder_not_found(self, session_login):
        resp = session_login.post(
            "/reschedule",
            data={"action": "send_reminder", "booking_id": "99999", "message": "hi"},
        )
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_send_reminder_empty(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(status="reschedule").id
        resp = session_login.post(
            "/reschedule",
            data={"action": "send_reminder", "booking_id": bid, "message": ""},
        )
        assert "tidak boleh kosong" in resp.get_data(as_text=True)

    def test_send_reminder_no_target(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(status="reschedule", phone="not-digit").id
        resp = session_login.post(
            "/reschedule",
            data={"action": "send_reminder", "booking_id": bid, "message": "hi"},
        )
        assert "tidak tersedia" in resp.get_data(as_text=True)

    def test_send_reminder_failed(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(status="reschedule").id
        with patch("app.app.send_and_log_message", side_effect=_failed_send):
            resp = session_login.post(
                "/reschedule",
                data={"action": "send_reminder", "booking_id": bid, "message": "hi"},
            )
        assert "Gagal mengirim" in resp.get_data(as_text=True)

    def test_send_reminder_success(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(status="reschedule").id
        resp = session_login.post(
            "/reschedule",
            data={"action": "send_reminder", "booking_id": bid, "message": "hi"},
        )
        assert "terkirim" in resp.get_data(as_text=True)

    def test_confirm_not_found(self, session_login):
        resp = session_login.post(
            "/reschedule",
            data={"action": "confirm_reschedule", "booking_id": "99999", "new_scheduled_start": "2026-09-20T10:00"},
        )
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_confirm_wrong_status(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(status="dikonfirmasi").id
        resp = session_login.post(
            "/reschedule",
            data={"action": "confirm_reschedule", "booking_id": bid, "new_scheduled_start": "2026-09-20T10:00"},
        )
        assert "tidak dalam status reschedule" in resp.get_data(as_text=True)

    def test_confirm_invalid_date(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(status="reschedule", service_name="Cuci Mobil").id
        resp = session_login.post(
            "/reschedule",
            data={"action": "confirm_reschedule", "booking_id": bid, "new_scheduled_start": "bad"},
        )
        assert "Format tanggal tidak valid" in resp.get_data(as_text=True)

    def test_confirm_success(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(status="reschedule", service_name="Cuci Mobil").id
        resp = session_login.post(
            "/reschedule",
            data={"action": "confirm_reschedule", "booking_id": bid, "new_scheduled_start": "2026-09-21T10:00"},
        )
        assert "dikonfirmasi" in resp.get_data(as_text=True)

    def test_confirm_generic_exception(self, session_login, app):
        with app.app_context():
            bid = _mk_booking(status="reschedule", service_name="Cuci Mobil").id
        with patch("app.app.compute_booking_end", side_effect=RuntimeError("boom")):
            resp = session_login.post(
                "/reschedule",
                data={"action": "confirm_reschedule", "booking_id": bid, "new_scheduled_start": "2026-09-22T10:00"},
            )
        assert "Gagal confirm" in resp.get_data(as_text=True)

    def test_confirm_conflict(self, session_login, app):
        with app.app_context():
            _mk_booking(status="dikonfirmasi", service_name="Cuci Mobil", phone="628124111000")
            bid = _mk_booking(status="reschedule", service_name="Cuci Mobil", phone="628124111001").id
        resp = session_login.post(
            "/reschedule",
            data={"action": "confirm_reschedule", "booking_id": bid, "new_scheduled_start": "2026-07-20T10:00"},
        )
        assert "bentrok" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# /maintenance
# --------------------------------------------------------------------------- #
def _mk_reminder(app):
    booking = _mk_booking(service_name="Coating Premium", phone="628124000111")
    reminder = MaintenanceReminder(
        booking_id=booking.id,
        customer_id=booking.customer_id,
        service_type="Coating Premium",
        completed_at=datetime.utcnow() - timedelta(days=180),
        maintenance_due_at=datetime.utcnow(),
    )
    db.session.add(reminder)
    db.session.commit()
    return reminder.id


class TestMaintenanceRoute:
    def test_send_reminder_not_found(self, session_login):
        resp = session_login.post(
            "/maintenance", data={"action": "send_reminder", "reminder_id": "99999", "message": "hi"}
        )
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_send_reminder_empty(self, session_login, app):
        with app.app_context():
            rid = _mk_reminder(app)
        resp = session_login.post(
            "/maintenance", data={"action": "send_reminder", "reminder_id": rid, "message": ""}
        )
        assert "tidak boleh kosong" in resp.get_data(as_text=True)

    def test_send_reminder_success(self, session_login, app):
        with app.app_context():
            rid = _mk_reminder(app)
        resp = session_login.post(
            "/maintenance", data={"action": "send_reminder", "reminder_id": rid, "message": "hi"}
        )
        assert "terkirim" in resp.get_data(as_text=True)

    def test_send_reminder_failed(self, session_login, app):
        with app.app_context():
            rid = _mk_reminder(app)
        with patch("app.app.send_and_log_message", side_effect=_failed_send):
            resp = session_login.post(
                "/maintenance", data={"action": "send_reminder", "reminder_id": rid, "message": "hi"}
            )
        assert "Gagal kirim reminder" in resp.get_data(as_text=True)

    def test_send_review_not_found(self, session_login):
        resp = session_login.post(
            "/maintenance", data={"action": "send_review", "reminder_id": "99999", "message": "hi"}
        )
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_send_review_empty(self, session_login, app):
        with app.app_context():
            rid = _mk_reminder(app)
        resp = session_login.post(
            "/maintenance", data={"action": "send_review", "reminder_id": rid, "message": ""}
        )
        assert "tidak boleh kosong" in resp.get_data(as_text=True)

    def test_send_review_success(self, session_login, app):
        with app.app_context():
            rid = _mk_reminder(app)
        resp = session_login.post(
            "/maintenance", data={"action": "send_review", "reminder_id": rid, "message": "hi"}
        )
        assert "terkirim" in resp.get_data(as_text=True)

    def test_send_review_failed(self, session_login, app):
        with app.app_context():
            rid = _mk_reminder(app)
        with patch("app.app.send_and_log_message", side_effect=_failed_send):
            resp = session_login.post(
                "/maintenance", data={"action": "send_review", "reminder_id": rid, "message": "hi"}
            )
        assert "Gagal kirim review" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# /settings
# --------------------------------------------------------------------------- #
class TestSettingsRoute:
    def test_get(self, session_login, no_bridge):
        resp = session_login.get("/settings")
        assert resp.status_code == 200

    def test_service_create_success(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings",
            data={"action": "service_create", "service_name": "Nano Coat", "service_duration": "2", "service_unit": "jam"},
        )
        assert "berhasil ditambahkan" in resp.get_data(as_text=True)

    def test_service_create_short_name(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings",
            data={"action": "service_create", "service_name": "ab", "service_duration": "2"},
        )
        assert "minimal 3 karakter" in resp.get_data(as_text=True)

    def test_service_create_duplicate(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings",
            data={"action": "service_create", "service_name": "Cuci Mobil", "service_duration": "15"},
        )
        assert "sudah ada" in resp.get_data(as_text=True)

    def test_service_create_bad_duration(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings",
            data={"action": "service_create", "service_name": "Zzz Service", "service_duration": "abc"},
        )
        assert "harus berupa angka" in resp.get_data(as_text=True)

    def test_service_update_not_found(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings",
            data={"action": "service_update", "service_id": "99999", "service_name": "Xyz", "service_duration": "2"},
        )
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_service_update_short_name(self, session_login, no_bridge, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
        resp = session_login.post(
            "/settings",
            data={"action": "service_update", "service_id": sid, "service_name": "ab", "service_duration": "2"},
        )
        assert "minimal 3 karakter" in resp.get_data(as_text=True)

    def test_service_update_duplicate(self, session_login, no_bridge, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
        resp = session_login.post(
            "/settings",
            data={"action": "service_update", "service_id": sid, "service_name": "Polishing", "service_duration": "2"},
        )
        assert "sudah ada" in resp.get_data(as_text=True)

    def test_service_update_bad_duration(self, session_login, no_bridge, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Cuci Mobil").first().id
        resp = session_login.post(
            "/settings",
            data={"action": "service_update", "service_id": sid, "service_name": "Renamed", "service_duration": "xx"},
        )
        assert "harus berupa angka" in resp.get_data(as_text=True)

    def test_service_update_success(self, session_login, no_bridge, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Glass Polishing").first().id
        resp = session_login.post(
            "/settings",
            data={"action": "service_update", "service_id": sid, "service_name": "Glass Polish Pro", "service_duration": "3", "service_unit": "jam"},
        )
        assert "berhasil diperbarui" in resp.get_data(as_text=True)

    def test_service_delete_not_found(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings", data={"action": "service_delete", "service_id": "99999"}
        )
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_service_delete_in_use(self, session_login, no_bridge, app):
        with app.app_context():
            sid = _mk_booking(service_name="Cuci Mobil").service_type_id
        resp = session_login.post(
            "/settings", data={"action": "service_delete", "service_id": sid}
        )
        assert "masih digunakan" in resp.get_data(as_text=True)

    def test_service_delete_success(self, session_login, no_bridge, app):
        with app.app_context():
            s = ServiceType(name="Temp Service", duration_minutes=30, active=True)
            db.session.add(s)
            db.session.commit()
            sid = s.id
        resp = session_login.post(
            "/settings", data={"action": "service_delete", "service_id": sid}
        )
        assert "berhasil dihapus" in resp.get_data(as_text=True)

    def test_service_toggle_not_found(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings", data={"action": "service_toggle", "service_id": "99999"}
        )
        assert "tidak ditemukan" in resp.get_data(as_text=True)

    def test_service_toggle_success(self, session_login, no_bridge, app):
        with app.app_context():
            sid = ServiceType.query.filter_by(name="Polishing").first().id
        resp = session_login.post(
            "/settings", data={"action": "service_toggle", "service_id": sid}
        )
        assert resp.status_code == 200

    def test_save_success(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings",
            data={
                "action": "save",
                "booking_done_template": "done {nama}",
                "reschedule_template": "resc {nama}",
                "maintenance_reminder_template": "maint {nama}",
                "review_request_template": "review {nama}",
                "google_maps_business_url": "https://maps.example.com",
            },
        )
        assert "berhasil disimpan" in resp.get_data(as_text=True)

    def test_save_invalid_wa_mode_empty_templates(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings",
            data={"action": "save"},
        )
        assert "berhasil disimpan" in resp.get_data(as_text=True)

    def test_test_send_no_phone(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings", data={"action": "test_send", "test_phone": ""}
        )
        assert "wajib diisi" in resp.get_data(as_text=True)

    def test_test_send_success(self, session_login, no_bridge):
        resp = session_login.post(
            "/settings",
            data={"action": "test_send", "test_phone": "628123999000", "test_message": "hi"},
        )
        assert "terkirim" in resp.get_data(as_text=True)

    def test_test_send_failed(self, session_login, no_bridge):
        with patch("app.app.send_and_log_message", side_effect=_failed_send):
            resp = session_login.post(
                "/settings",
                data={"action": "test_send", "test_phone": "628123999111"},
            )
        assert "Gagal kirim" in resp.get_data(as_text=True)

    def test_unknown_action_falls_through(self, session_login, no_bridge):
        resp = session_login.post("/settings", data={"action": "bogus"})
        assert resp.status_code == 200

    def test_get_with_qr_profile(self, session_login):
        from types import SimpleNamespace

        profile = SimpleNamespace(
            base_url="http://bridge:3000",
            qr_path="/qr",
            has_qr=True,
            auth_required=False,
            connected=True,
            detected_from="/status",
        )
        with patch("app.app.discover_bridge_profile", return_value=profile):
            resp = session_login.get("/settings")
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# /api/whatsapp/inbound and /api/reminders/run
# --------------------------------------------------------------------------- #
class TestApiRoutes:
    def test_inbound_booking_form_exception(self, client):
        form_text = "Nama: John\nNo HP: 08123456789\nPaket: Coating\n"
        with patch("app.app.create_booking_from_form", side_effect=RuntimeError("boom")):
            resp = client.post(
                "/api/whatsapp/inbound",
                json={"phone": "628123888000", "text": form_text},
            )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_run_reminders(self, session_login):
        resp = session_login.post("/api/reminders/run")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True


class _StopStream(Exception):
    pass


# --------------------------------------------------------------------------- #
# /api/whatsapp/stream (SSE generator)
# --------------------------------------------------------------------------- #
class TestWhatsAppStream:
    def _run_stream(self, app, url, sleep_side_effect):
        """Drive the streaming view's generator until sleep raises _StopStream."""
        chunks = []
        with patch("app.app.time.sleep", side_effect=sleep_side_effect):
            with app.test_request_context(url):
                from flask import session

                session["user_id"] = 1
                session["role"] = "admin"
                view = app.view_functions["whatsapp_stream"]
                resp = view()
                try:
                    for chunk in resp.response:
                        chunks.append(chunk)
                except _StopStream:
                    pass
        return chunks

    def test_stream_yields_rows(self, app):
        with app.app_context():
            _mk_message(phone="628125000111", payload={"contact_number": "628125000111"})

        def sleep_once(_):
            raise _StopStream()

        chunks = self._run_stream(app, "/api/whatsapp/stream?after=0", sleep_once)
        assert any("data:" in c for c in chunks)

    def test_stream_keepalive(self, app):
        calls = {"n": 0}

        def sleep_until_fifth(_):
            calls["n"] += 1
            if calls["n"] >= 5:
                raise _StopStream()

        # after a very high id -> no rows -> idle -> keepalive after 5 ticks
        chunks = self._run_stream(app, "/api/whatsapp/stream?after=999999", sleep_until_fifth)
        assert any("keepalive" in c for c in chunks)

    def test_stream_invalid_after(self, app):
        def sleep_once(_):
            raise _StopStream()

        # invalid 'after' -> ValueError -> after_id = 0
        self._run_stream(app, "/api/whatsapp/stream?after=abc", sleep_once)
