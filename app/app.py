from __future__ import annotations

import os
import re
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, Response, jsonify, redirect, render_template, request, url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import current_user_id, current_user_role, login_user, logout_user, require_auth, require_roles
from app.config import Config
from app.models import AuditLog, Booking, Customer, ServiceType, User, WhatsAppMessage, MaintenanceReminder, db
from app.services.booking_engine import compute_booking_end, has_conflict, is_within_operating_hours
from app.services.reminders import run_due_reminders
from app.services.settings_store import get_many, get_setting, set_setting
from app.services.semantic_matcher import match_package_to_service, get_variant_info
from app.services.whatsapp import (
    create_wa_instance,
    delete_wa_instance,
    discover_bridge_profile,
    fetch_whatsapp_contacts,
    list_wa_instances,
    log_inbound_message,
    send_and_log_message,
    wa_instance_qr_embed_url,
)

scheduler = BackgroundScheduler()


def wants_partial() -> bool:
    """True when the request comes from the SPA router (app.js), which only
    needs the inner content block, not the full page shell."""
    return request.headers.get("X-Requested-With") == "fetch"

# Booking workflow statuses (key -> label shown in the UI). Ordered.
BOOKING_STATUSES = {
    "dikonfirmasi": "Dikonfirmasi",
    "kendaraan_masuk": "Kendaraan Masuk",
    "dikerjakan": "Dikerjakan",
    "qc": "QC / Cek Hasil",
    "siap_diambil": "Siap Diambil",
    "selesai": "Selesai",
    "reschedule": "Reschedule",
    "cancel": "Cancel",
    "batal": "Batal",
}

# Which statuses trigger customer notifications
NOTIFY_ON_STATUS = {"siap_diambil", "selesai"}

# Default template for the "selesai" customer notification. Editable in Settings.
# Placeholders: {nama}, {layanan}, {tanggal}
DEFAULT_BOOKING_DONE_TEMPLATE = (
    "Halo {nama}, kabar baik! Kendaraan Anda untuk layanan *{layanan}* "
    "sudah *selesai* dikerjakan dan siap diambil. "
    "Silakan hubungi kami untuk pengaturan pengambilan. "
    "Terima kasih telah mempercayakan kendaraan Anda kepada kami 🙏"
)

# Default template for "siap_diambil" notification. Editable in Settings.
# Placeholders: {nama}, {layanan}, {tanggal}
DEFAULT_SIAP_DIAMBIL_TEMPLATE = (
    "Halo {nama}, kendaraan Anda untuk layanan *{layanan}* "
    "sudah selesai dan *siap diambil*. "
    "Terima kasih telah mempercayakan kendaraan Anda kepada kami 🙏"
)

# Default template for reschedule reminder. Editable in Settings.
# Placeholders: {nama}, {layanan}, {tanggal_lama}, {tanggal_baru}
DEFAULT_RESCHEDULE_TEMPLATE = (
    "Halo {nama}, kami terima permintaan reschedule untuk *{layanan}*. "
    "Jadwal awal: {tanggal_lama} → Jadwal baru: {tanggal_baru}. "
    "Apakah sudah tepat? Silakan konfirmasi ya."
)

# Default template for maintenance reminder (6 months after coating/ppf). Editable in Settings.
# Placeholders: {nama}, {layanan}, {tanggal_selesai}
DEFAULT_MAINTENANCE_REMINDER_TEMPLATE = (
    "Halo {nama}, sudah 6 bulan sejak layanan *{layanan}* kami selesaikan ({tanggal_selesai}). "
    "Untuk menjaga kualitas, kami rekomendasikan maintenance sekarang. "
    "Hubungi kami untuk booking maintenance Anda ya 😊"
)

# Default template for review request. Editable in Settings.
# Placeholders: {nama}, {layanan}, {link_review}
DEFAULT_REVIEW_REQUEST_TEMPLATE = (
    "Halo {nama}, terima kasih telah menggunakan layanan *{layanan}* kami! "
    "Bantu kami berkembang dengan memberikan review di Google Maps: {link_review} "
    "Apresiasi Anda sangat berarti untuk kami 🙏"
)


def booking_notify_target(customer) -> str:
    """Resolve where a customer notification should be delivered."""
    if customer is None:
        return ""
    phone = str(customer.phone or "").strip()
    if phone.isdigit():
        return f"{phone}@c.us"
    lid = str(getattr(customer, "lid", "") or "").strip()
    if lid.isdigit():
        return f"{lid}@lid"
    return ""


def booking_done_message(booking) -> str:
    """Render the 'selesai' notification from the (customizable) template."""
    template = (
        get_setting("booking_done_template", DEFAULT_BOOKING_DONE_TEMPLATE)
        or DEFAULT_BOOKING_DONE_TEMPLATE
    )
    name = (booking.customer.name if booking.customer else "") or "Kak"
    service = booking.service_type.name if booking.service_type else "layanan"
    tanggal = (
        booking.scheduled_start.strftime("%d-%m-%Y")
        if booking.scheduled_start
        else "-"
    )
    return (
        template.replace("{nama}", name)
        .replace("{layanan}", service)
        .replace("{tanggal}", tanggal)
    )


def booking_reschedule_message(booking, new_scheduled_start) -> str:
    """Render the reschedule reminder from the (customizable) template."""
    template = (
        get_setting("reschedule_template", DEFAULT_RESCHEDULE_TEMPLATE)
        or DEFAULT_RESCHEDULE_TEMPLATE
    )
    name = (booking.customer.name if booking.customer else "") or "Kak"
    service = booking.service_type.name if booking.service_type else "layanan"
    tanggal_lama = (
        booking.scheduled_start.strftime("%d-%m-%Y")
        if booking.scheduled_start
        else "-"
    )
    tanggal_baru = (
        new_scheduled_start.strftime("%d-%m-%Y")
        if new_scheduled_start
        else "-"
    )
    return (
        template.replace("{nama}", name)
        .replace("{layanan}", service)
        .replace("{tanggal_lama}", tanggal_lama)
        .replace("{tanggal_baru}", tanggal_baru)
    )


def resolve_real_number(data: dict, phone: str) -> str:
    """Return a real WhatsApp phone number when one is available.

    WhatsApp exposes the actual contact number via the bridge (contact_number)
    or through a standard @c.us chat id. A LID (@lid) is a private identity and
    never a phone number, so it is ignored here.
    """
    contact_number = str((data or {}).get("contact_number", "") or "").strip()
    if contact_number.isdigit() and 8 <= len(contact_number) <= 15:
        return contact_number

    chat_id = str((data or {}).get("chat_id", "") or "").strip().lower()
    if chat_id.endswith("@c.us"):
        num = chat_id.split("@", 1)[0]
        if num.isdigit() and 8 <= len(num) <= 15:
            return num

    phone = str(phone or "").strip()
    if phone.isdigit() and 8 <= len(phone) <= 15:
        return phone

    return ""


def extract_lid(data: dict, phone: str) -> str:
    """Return the WhatsApp LID (private identity) digits when present."""
    chat_id = str((data or {}).get("chat_id", "") or "").strip().lower()
    if chat_id.endswith("@lid"):
        lid = chat_id.split("@", 1)[0]
        if lid.isdigit() and 8 <= len(lid) <= 20:
            return lid

    phone = str(phone or "").strip().lower()
    if phone.startswith("lid:"):
        lid = phone.split(":", 1)[1]
        if lid.isdigit() and 8 <= len(lid) <= 20:
            return lid

    return ""


def sync_customer_from_inbound(data: dict, phone: str) -> None:
    """Auto-capture the WhatsApp contact into the customer list.

    A contact is matched first by its LID, then by its real phone number, so an
    inbound chat that only carries a LID is still linked to the right customer.
    """
    real_number = resolve_real_number(data, phone)
    lid = extract_lid(data, phone)
    if not real_number and not lid:
        return

    contact_name = str((data or {}).get("contact_name", "") or "").strip()

    customer = None
    if lid:
        customer = Customer.query.filter_by(lid=lid).first()
    if customer is None and real_number:
        customer = Customer.query.filter_by(phone=real_number).first()

    if customer is None:
        # Only create a new contact when we have a real phone number to key on.
        if not real_number:
            return
        customer = Customer(
            name=contact_name or f"WhatsApp {real_number[-4:]}",
            phone=real_number,
            lid=lid or None,
            notes="Otomatis dari WhatsApp",
        )
        db.session.add(customer)
        db.session.commit()
        return

    changed = False
    if lid and not customer.lid:
        customer.lid = lid
        changed = True
    if contact_name and (
        not customer.name
        or customer.name.startswith("WhatsApp ")
        or customer.name.startswith("Pelanggan ")
    ):
        customer.name = contact_name
        changed = True
    if changed:
        db.session.commit()


# Labels recognised in an incoming WhatsApp booking form (normalized -> field).
BOOKING_FORM_LABELS = {
    "nama": "name",
    "no hp": "phone",
    "nohp": "phone",
    "no. hp": "phone",
    "nomor hp": "phone",
    "no telp": "phone",
    "no. telp": "phone",
    "no wa": "phone",
    "no. wa": "phone",
    "merk & type mobil": "vehicle_type",
    "merk type mobil": "vehicle_type",
    "merk dan type mobil": "vehicle_type",
    "merk & tipe mobil": "vehicle_type",
    "jenis kendaraan": "vehicle_type",
    "mobil": "vehicle_type",
    "nomor polisi": "license_plate",
    "nopol": "license_plate",
    "no. polisi": "license_plate",
    "plat": "license_plate",
    "pilihan paket": "package",
    "paket": "package",
    "domisili": "domicile",
    "tanggal masuk mobil": "schedule_text",
    "tanggal masuk": "schedule_text",
    "tanggal": "schedule_text",
    "outlet": "outlet",
    "data from": "data_from",
    "sumber": "data_from",
    "harga normal": "price_normal",
    "harga disc": "price_disc",
    "harga discount": "price_disc",
    "harga nett": "price_nett",
    "harga net": "price_nett",
}


def _clean_form_value(value: str) -> str:
    # Remove WhatsApp markdown emphasis (_ * ` ~) and surrounding whitespace.
    return re.sub(r"[_*`~]", "", str(value or "")).strip()


def _normalize_form_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits


def parse_booking_form(text: str) -> dict | None:
    """Parse a structured WhatsApp booking form into fields.

    Returns a dict of recognised fields, or None when the message is not a
    booking form (name + phone + package must all be present).
    """
    fields: dict[str, str] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip().lstrip("-•*").strip()
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        key = re.sub(r"[^a-z0-9& ]", "", label.strip().lower())
        key = re.sub(r"\s+", " ", key).strip()
        mapped = BOOKING_FORM_LABELS.get(key)
        if mapped and mapped not in fields:
            fields[mapped] = _clean_form_value(value)

    if fields.get("name") and fields.get("phone") and fields.get("package"):
        return fields
    return None


def parse_schedule_text(text: str) -> datetime | None:
    """Best-effort parse of a schedule field into a datetime.

    Handles concrete dates (dd-mm-yyyy) and relative estimates like
    "2 minggu", "3 hari", "1 bulan". Returns None when nothing is parseable.
    """
    t = str(text or "").lower().strip()
    if not t:
        return None

    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", t)
    if m:
        day, month, year = (int(g) for g in m.groups())
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day, 10, 0)
        except ValueError:
            pass

    m = re.search(r"(\d+)\s*minggu", t)
    if m:
        return datetime.utcnow() + timedelta(weeks=int(m.group(1)))
    m = re.search(r"(\d+)\s*hari", t)
    if m:
        return datetime.utcnow() + timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*bulan", t)
    if m:
        return datetime.utcnow() + timedelta(days=30 * int(m.group(1)))
    return None


def create_booking_from_form(form: dict, data: dict) -> Booking | None:
    """Create (or reuse) a customer and a pending booking from a parsed form."""
    phone = _normalize_form_phone(form.get("phone", ""))
    name = (form.get("name") or "").strip() or "Pelanggan WhatsApp"
    if not phone:
        return None

    # Upsert the customer.
    customer = Customer.query.filter_by(phone=phone).first()
    if customer is None:
        customer = Customer(
            name=name,
            phone=phone,
            vehicle_info=form.get("vehicle_type") or None,
            notes=form.get("domicile") or "Dari form WhatsApp",
        )
        db.session.add(customer)
        db.session.flush()
    else:
        if form.get("vehicle_type") and not customer.vehicle_info:
            customer.vehicle_info = form.get("vehicle_type")
        if name and (
            not customer.name
            or customer.name.startswith("WhatsApp ")
            or customer.name.startswith("Pelanggan ")
        ):
            customer.name = name

    # Resolve the service type from the package name using semantic matching.
    package = (form.get("package") or "Paket WhatsApp").strip()
    
    # Try semantic matching first
    all_active_services = ServiceType.query.filter_by(active=True).all()
    service = match_package_to_service(package, all_active_services)
    
    # If no match found, fallback to "Lainnya" service
    if service is None:
        service = ServiceType.query.filter_by(name="Lainnya").first()
        if service is None:
            # Last resort: create Lainnya if it doesn't exist
            service = ServiceType(name="Lainnya", duration_minutes=240, active=True)
            db.session.add(service)
            db.session.flush()

    # Schedule (best-effort; CS confirms afterwards).
    start_time = parse_schedule_text(form.get("schedule_text", "")) or datetime.utcnow()
    end_time = compute_booking_end(service, start_time)

    # Avoid duplicates from repeated/echoed messages.
    duplicate = (
        Booking.query.filter_by(customer_id=customer.id, service_type_id=service.id)
        .filter(Booking.created_at >= datetime.utcnow() - timedelta(minutes=30))
        .first()
    )
    if duplicate:
        db.session.commit()
        return duplicate

    detail_lines = ["Booking dari WhatsApp"]
    
    # Add package info with variant if available
    variant_info = get_variant_info(package, all_active_services)
    package_display = f"Paket: {package}"
    if variant_info:
        package_display += f" (varian: {variant_info})"
    detail_lines.append(package_display)
    
    label_map = [
        ("vehicle_type", "Mobil"),
        ("license_plate", "Nomor Polisi"),
        ("domicile", "Domisili"),
        ("outlet", "Outlet"),
        ("data_from", "Data From"),
        ("schedule_text", "Tanggal masuk"),
        ("price_normal", "Harga Normal"),
        ("price_disc", "Harga Disc"),
        ("price_nett", "Harga Nett"),
    ]
    for key, label in label_map:
        value = (form.get(key) or "").strip()
        if value:
            detail_lines.append(f"{label}: {value}")

    booking = Booking(
        customer_id=customer.id,
        service_type_id=service.id,
        scheduled_start=start_time,
        scheduled_end=end_time,
        status="dikonfirmasi",
        source="whatsapp",
        notes="\n".join(detail_lines),
        other_info=package,  # Store original package name
        vehicle_type=(form.get("vehicle_type") or "").strip(),
        license_plate=(form.get("license_plate") or "").strip(),
    )
    db.session.add(booking)
    db.session.add(
        AuditLog(
            actor_user_id=None,
            action="booking.from_whatsapp",
            details=f"customer={phone} package={package}",
        )
    )
    db.session.commit()
    return booking


def build_message_view(msg: WhatsAppMessage) -> dict:
    """Build a rich view of a stored WhatsApp message for the grouped inbox.

    The contact is resolved by real number or by LID, so a private (LID) chat
    still shows the saved customer name. A stable ``conv_key`` groups every
    message of the same person into one conversation.
    """
    try:
        payload = json.loads(msg.payload_json or "{}")
    except Exception:
        payload = {}

    chat_id = str(payload.get("chat_id", "") or "").strip().lower()
    contact_name = str(payload.get("contact_name", "") or "").strip()
    real_number = resolve_real_number(payload, msg.phone)
    lid = extract_lid(payload, msg.phone)

    # Resolve the linked customer, preferring the real number then the LID.
    customer = None
    if real_number:
        customer = Customer.query.filter_by(phone=real_number).first()
    if customer is None and lid:
        customer = Customer.query.filter_by(lid=lid).first()

    # A customer's stored phone can itself be a real number or a LID placeholder.
    customer_number = ""
    if customer and customer.phone and customer.phone.isdigit():
        customer_number = customer.phone

    if customer_number:
        number_label = customer_number
    elif real_number:
        number_label = real_number
    elif chat_id.endswith("@g.us"):
        number_label = "Grup WhatsApp"
    elif lid or msg.phone.startswith(("lid:", "wa:")):
        number_label = "Nomor private"
    else:
        number_label = ""

    saved_name = customer.name if customer else ""
    name_label = saved_name or contact_name or "Kontak WhatsApp"

    # Stable conversation key so every message of one person groups together.
    if customer is not None:
        conv_key = f"c{customer.id}"
    elif chat_id.endswith("@g.us"):
        conv_key = f"g:{chat_id}"
    elif real_number:
        conv_key = f"n:{real_number}"
    elif lid:
        conv_key = f"l:{lid}"
    else:
        conv_key = f"p:{msg.phone or 'unknown'}"

    avatar = (name_label.strip()[:1] or "#").upper()

    # Where a reply should be delivered. Prefer the real number (@c.us); fall
    # back to the original chat id (group or LID) so replies stay in-thread.
    reply_phone = customer_number or real_number or ""
    if reply_phone:
        reply_to = f"{reply_phone}@c.us"
    elif chat_id:
        reply_to = chat_id
    elif lid:
        reply_to = f"{lid}@lid"
    else:
        reply_to = ""

    return {
        "id": msg.id,
        "conv_key": conv_key,
        "name": name_label,
        "number_label": number_label,
        "avatar": avatar,
        "direction": msg.direction,
        "text": msg.message_text,
        "time": msg.created_at.strftime("%H:%M"),
        "date": msg.created_at.strftime("%d-%m-%Y"),
        "created_at": msg.created_at.strftime("%d-%m-%Y %H:%M:%S"),
        "status": msg.status,
        "reply_to": reply_to,
    }


SEED_USERS_SQL_PATH = os.path.join(os.path.dirname(__file__), "sql", "seed_users.sql")


def seed_default_users() -> None:
    """Create the default first-run accounts (admin/cs1/tech1) from a SQL
    script instead of hard-coding usernames/passwords in Python. The script
    only ever contains password *hashes* and is idempotent (ON CONFLICT DO
    NOTHING), so it is safe to run on every startup."""
    with open(SEED_USERS_SQL_PATH, "r", encoding="utf-8") as f:
        sql_script = f.read()
    db.session.execute(text(sql_script))


def bootstrap_defaults() -> None:
    seed_default_users()

    defaults = [
        ("Interior Detailing", 480),  # 8 jam
        ("Polishing", 480),  # 8 jam
        ("PPF", 7200),  # 5 hari
        ("Coating Premium", 4320),  # 3 hari
        ("Glass Polishing", 120),  # 2 jam
        ("Cuci Mobil", 15),  # 15 menit
        ("Lainnya", 120),  # 2 jam - default untuk package yang tidak match
    ]
    for name, duration in defaults:
        existing = ServiceType.query.filter_by(name=name).first()
        if not existing:
            db.session.add(ServiceType(name=name, duration_minutes=duration))

    db.session.commit()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        bootstrap_defaults()

    @app.context_processor
    def inject_globals():
        return {
            "current_role": current_user_role(),
            "current_user_id": current_user_id(),
        }

    @app.route("/")
    def home():
        if current_user_id():
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username, active=True).first()
            if user and user.check_password(password):
                login_user(user.id, user.role)
                return redirect(url_for("dashboard"))
            error = "Username atau password salah"
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @require_auth
    def dashboard():
        bookings_today = Booking.query.filter(
            db.func.date(Booking.scheduled_start) == datetime.now().date()
        ).count()
        pending = Booking.query.filter_by(status="reschedule").count()
        customers = Customer.query.count()
        return render_template(
            "dashboard.html",
            bookings_today=bookings_today,
            pending=pending,
            customers=customers,
            partial=wants_partial(),
        )

    @app.route("/bookings", methods=["GET", "POST"])
    @require_roles("admin", "cs")
    def bookings():
        message = None
        error = None

        def render_bookings():
            data = Booking.query.order_by(Booking.scheduled_start.asc()).all()
            services = ServiceType.query.filter_by(active=True).all()
            notify = {}
            for b in data:
                if b.status == "selesai":
                    notify[b.id] = {
                        "target": booking_notify_target(b.customer),
                        "message": booking_done_message(b),
                    }
            return render_template(
                "bookings.html",
                bookings=data,
                services=services,
                statuses=BOOKING_STATUSES,
                notify=notify,
                message=message,
                error=error,
                partial=wants_partial(),
            )

        if request.method == "POST":
            action = request.form.get("action", "create").strip()

            if action == "update_status":
                booking_id = int(request.form.get("booking_id", "0") or 0)
                new_status = request.form.get("status", "").strip().lower()
                booking = Booking.query.get(booking_id)
                if not booking:
                    error = "Booking tidak ditemukan"
                elif new_status not in BOOKING_STATUSES:
                    error = "Status tidak valid"
                else:
                    old_status = booking.status
                    booking.status = new_status
                    db.session.add(
                        AuditLog(
                            actor_user_id=current_user_id(),
                            action="booking.status_change",
                            details=f"booking_id={booking.id} {old_status}->{new_status}",
                        )
                    )
                    db.session.commit()
                    message = f"Status booking #{booking.id} diperbarui menjadi '{BOOKING_STATUSES[new_status]}'"
                    if new_status == "selesai":
                        message += " — cek & kirim notifikasi ke customer di bawah."
                        # Create maintenance reminder if service is Coating Premium or PPF
                        service_name = booking.service_type.name
                        if service_name in ["Coating Premium", "PPF"]:
                            existing_reminder = MaintenanceReminder.query.filter_by(booking_id=booking.id).first()
                            if not existing_reminder:
                                maintenance_due = datetime.utcnow() + timedelta(days=180)  # 6 months
                                reminder = MaintenanceReminder(
                                    booking_id=booking.id,
                                    customer_id=booking.customer_id,
                                    service_type=service_name,
                                    completed_at=datetime.utcnow(),
                                    maintenance_due_at=maintenance_due,
                                )
                                db.session.add(reminder)
                                db.session.commit()
                                message += f" | Maintenance reminder dibuat (6 bulan)."
                return render_bookings()

            if action == "notify_customer":
                booking_id = int(request.form.get("booking_id", "0") or 0)
                text = request.form.get("message", "").strip()
                booking = Booking.query.get(booking_id)
                if not booking:
                    error = "Booking tidak ditemukan"
                elif not text:
                    error = "Pesan tidak boleh kosong"
                else:
                    target = booking_notify_target(booking.customer)
                    if not target:
                        error = "Nomor WhatsApp customer tidak tersedia"
                    else:
                        sent = send_and_log_message(
                            target.split("@", 1)[0], text, chat_id=target
                        )
                        if sent.status == "failed":
                            error = "Gagal mengirim notifikasi (cek koneksi WhatsApp)"
                        else:
                            db.session.add(
                                AuditLog(
                                    actor_user_id=current_user_id(),
                                    action="booking.notify_customer",
                                    details=f"booking_id={booking.id} to={target.split('@', 1)[0]}",
                                )
                            )
                            db.session.commit()
                            message = f"Notifikasi terkirim ke {booking.customer.name}"
                return render_bookings()

            customer_name = request.form.get("customer_name", "").strip()
            phone = request.form.get("phone", "").strip()
            vehicle_type = request.form.get("vehicle_type", "").strip()
            license_plate = request.form.get("license_plate", "").strip()
            service_id = int(request.form.get("service_id", "0") or 0)
            package_name = request.form.get("package_name", "").strip()
            schedule_raw = request.form.get("scheduled_start", "").strip()
            notes = request.form.get("notes", "").strip()

            service = None
            variant_info = None
            lainnya_service = ServiceType.query.filter_by(name="Lainnya").first()
            
            # If package_name is provided, use semantic matching to find the service
            if package_name and not service_id:
                all_services = ServiceType.query.filter_by(active=True).all()
                matched_service = match_package_to_service(package_name, all_services)
                
                if matched_service:
                    service = matched_service
                    variant_info = get_variant_info(package_name, all_services)
                    # Build notes with package info
                    package_note = f"Paket: {package_name}"
                    if variant_info:
                        package_note += f" (varian: {variant_info})"
                    notes = f"{package_note}\n{notes}" if notes else package_note
                else:
                    # No match found - fallback to "Lainnya" service
                    service = lainnya_service
                    if service:
                        package_note = f"Paket: {package_name} (tidak cocok dengan layanan standard, masuk ke Lainnya)"
                        notes = f"{package_note}\n{notes}" if notes else package_note
            
            # Otherwise, use the provided service_id
            elif service_id:
                service = ServiceType.query.get(service_id)
                if not service:
                    error = "Layanan tidak ditemukan"
            
            # If no service found and no service_id, default to "Lainnya"
            if not service and not error:
                service = lainnya_service
                if not service:
                    error = "Service default 'Lainnya' tidak tersedia"
            
            start_time = None
            try:
                # Accept either full datetime (from older clients) or date-only.
                try:
                    start_time = datetime.strptime(schedule_raw, "%Y-%m-%dT%H:%M")
                except ValueError:
                    # date-only input: treat as start of day
                    start_time = datetime.strptime(schedule_raw, "%Y-%m-%d")
            except ValueError:
                error = "Format tanggal tidak valid"

            if service and start_time and not error:
                end_time = compute_booking_end(service, start_time)
                # Do not enforce operating hours check when schedule is date-only/user requested removal
                if has_conflict(start_time, end_time):
                    error = "Jadwal bentrok dengan booking lain"
                else:
                    customer = Customer.query.filter_by(phone=phone).first()
                    if not customer:
                        customer = Customer(name=customer_name, phone=phone, vehicle_info=vehicle_type)
                        db.session.add(customer)
                        db.session.flush()

                    booking = Booking(
                        customer_id=customer.id,
                        service_type_id=service.id,
                        scheduled_start=start_time,
                        scheduled_end=end_time,
                        status="dikonfirmasi",
                        source="manual",
                        notes=notes,
                        other_info=package_name,  # Store original package name
                        vehicle_type=vehicle_type,
                        license_plate=license_plate,
                        created_by_user_id=current_user_id(),
                    )
                    db.session.add(booking)
                    db.session.add(
                        AuditLog(
                            actor_user_id=current_user_id(),
                            action="booking.create",
                            details=f"booking_id=pending customer={customer.phone} service={service.name}",
                        )
                    )
                    db.session.commit()
                    message = "Booking berhasil dibuat"

        return render_bookings()

    @app.route("/bookings/<int:booking_id>/edit", methods=["GET", "POST"])
    @require_roles("admin", "cs")
    def edit_booking(booking_id):
        """Edit an existing booking"""
        booking = Booking.query.get(booking_id)
        if not booking:
            return "Booking tidak ditemukan", 404

        message = None
        error = None
        services = ServiceType.query.filter_by(active=True).all()

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            
            if action == "update":
                customer_name = request.form.get("customer_name", "").strip()
                phone = request.form.get("phone", "").strip()
                vehicle_type = request.form.get("vehicle_type", "").strip()
                license_plate = request.form.get("license_plate", "").strip()
                service_id = int(request.form.get("service_id", "0") or 0)
                package_name = request.form.get("package_name", "").strip()
                schedule_raw = request.form.get("scheduled_start", "").strip()
                notes = request.form.get("notes", "").strip()

                service = None
                variant_info = None
                lainnya_service = ServiceType.query.filter_by(name="Lainnya").first()

                # Validate customer data
                if not customer_name or not phone:
                    error = "Nama pelanggan dan nomor WhatsApp wajib diisi"
                elif not schedule_raw:
                    error = "Jadwal wajib diisi"
                else:
                    # Check if package_name is provided, use semantic matching
                    if package_name and not service_id:
                        all_services = ServiceType.query.filter_by(active=True).all()
                        matched_service = match_package_to_service(package_name, all_services)
                        
                        if matched_service:
                            service = matched_service
                            variant_info = get_variant_info(package_name, all_services)
                            package_note = f"Paket: {package_name}"
                            if variant_info:
                                package_note += f" (varian: {variant_info})"
                            notes = f"{package_note}\n{notes}" if notes else package_note
                        else:
                            service = lainnya_service
                            if service:
                                package_note = f"Paket: {package_name} (tidak cocok dengan layanan standard, masuk ke Lainnya)"
                                notes = f"{package_note}\n{notes}" if notes else package_note
                    elif service_id:
                        service = ServiceType.query.get(service_id)
                        if not service:
                            error = "Layanan tidak ditemukan"
                    else:
                        service = lainnya_service
                        if not service:
                            error = "Service default 'Lainnya' tidak tersedia"

                    if not error and service:
                        try:
                            try:
                                start_time = datetime.strptime(schedule_raw, "%Y-%m-%dT%H:%M")
                            except ValueError:
                                start_time = datetime.strptime(schedule_raw, "%Y-%m-%d")
                        except ValueError:
                            error = "Format tanggal tidak valid"

                        if not error:
                            end_time = compute_booking_end(service, start_time)

                            # Do not enforce operating hours; still check conflicts (excluding current booking)
                            if has_conflict(start_time, end_time, exclude_booking_id=booking.id):
                                error = "Jadwal bentrok dengan booking lain"
                            else:
                                # Update customer info
                                customer = booking.customer
                                customer.name = customer_name
                                
                                # Check if phone number is being changed to a duplicate
                                if customer.phone != phone:
                                    existing_customer = Customer.query.filter(
                                        Customer.phone == phone,
                                        Customer.id != customer.id
                                    ).first()
                                    if existing_customer:
                                        error = "Nomor WhatsApp sudah terdaftar untuk customer lain"
                                
                                if not error:
                                    customer.phone = phone
                                    customer.vehicle_info = vehicle_type or None
                                    
                                    # Update booking info
                                    booking.service_type_id = service.id
                                    booking.scheduled_start = start_time
                                    booking.scheduled_end = end_time
                                    booking.notes = notes
                                    booking.other_info = package_name
                                    booking.vehicle_type = vehicle_type
                                    booking.license_plate = license_plate
                                    
                                    db.session.add(
                                        AuditLog(
                                            actor_user_id=current_user_id(),
                                            action="booking.edit",
                                            details=f"booking_id={booking.id} customer={customer.phone} service={service.name}",
                                        )
                                    )
                                    db.session.commit()
                                    message = "Booking berhasil diperbarui"
                                    return redirect(url_for("bookings"))

        return render_template(
            "edit_booking.html",
            booking=booking,
            services=services,
            statuses=BOOKING_STATUSES,
            message=message,
            error=error,
            partial=wants_partial(),
        )

    @app.route("/customers", methods=["GET", "POST"])
    @require_roles("admin", "cs")
    def customers():
        message = request.args.get("sync_ok")
        error = request.args.get("sync_error")

        if request.method == "POST":
            action = request.form.get("action", "create").strip()

            if action == "delete":
                customer_id = int(request.form.get("customer_id", "0") or 0)
                customer = Customer.query.get(customer_id)
                if not customer:
                    error = "Kontak tidak ditemukan"
                elif Booking.query.filter_by(customer_id=customer.id).count() > 0:
                    error = "Kontak tidak bisa dihapus karena masih punya booking"
                else:
                    db.session.delete(customer)
                    db.session.add(
                        AuditLog(
                            actor_user_id=current_user_id(),
                            action="customer.delete",
                            details=f"customer_id={customer.id} phone={customer.phone}",
                        )
                    )
                    db.session.commit()
                    message = "Kontak berhasil dihapus"
            else:
                name = request.form.get("name", "").strip()
                phone = request.form.get("phone", "").strip()
                vehicle = request.form.get("vehicle", "").strip()
                notes = request.form.get("notes", "").strip()
                customer_id = int(request.form.get("customer_id", "0") or 0)

                if not name or not phone:
                    error = "Nama dan nomor WhatsApp wajib diisi"
                else:
                    duplicate = Customer.query.filter(
                        Customer.phone == phone, Customer.id != customer_id
                    ).first()
                    if duplicate:
                        error = "Nomor WhatsApp sudah terdaftar untuk kontak lain"
                    elif action == "update" and customer_id:
                        customer = Customer.query.get(customer_id)
                        if not customer:
                            error = "Kontak tidak ditemukan"
                        else:
                            customer.name = name
                            customer.phone = phone
                            customer.vehicle_info = vehicle or None
                            customer.notes = notes or None
                            db.session.add(
                                AuditLog(
                                    actor_user_id=current_user_id(),
                                    action="customer.update",
                                    details=f"customer_id={customer.id} phone={phone}",
                                )
                            )
                            db.session.commit()
                            message = "Kontak berhasil diperbarui"
                    else:
                        customer = Customer(
                            name=name,
                            phone=phone,
                            vehicle_info=vehicle or None,
                            notes=notes or None,
                        )
                        db.session.add(customer)
                        db.session.add(
                            AuditLog(
                                actor_user_id=current_user_id(),
                                action="customer.create",
                                details=f"phone={phone}",
                            )
                        )
                        db.session.commit()
                        message = "Kontak berhasil ditambahkan"

        search = request.args.get("q", "").strip()
        query = Customer.query
        if search:
            like = f"%{search}%"
            query = query.filter(db.or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
        contacts = query.order_by(Customer.created_at.desc()).all()

        booking_counts = {
            customer_id: count
            for customer_id, count in db.session.query(
                Booking.customer_id, db.func.count(Booking.id)
            ).group_by(Booking.customer_id).all()
        }

        return render_template(
            "customers.html",
            contacts=contacts,
            booking_counts=booking_counts,
            search=search,
            message=message,
            error=error,
            partial=wants_partial(),
        )

    @app.route("/customers/sync", methods=["POST"])
    @require_roles("admin", "cs")
    def customers_sync():
        saved_only = request.form.get("saved_only", "true").strip().lower() != "false"
        ok, status, contacts = fetch_whatsapp_contacts(saved_only=saved_only)

        if not ok:
            reason = {
                "bridge-not-found": "Bridge WhatsApp tidak ditemukan. Pastikan WhatsApp sudah terhubung.",
                "wa_not_connected": "WhatsApp belum terhubung. Scan QR terlebih dahulu.",
                "contacts-unavailable": "Gagal mengambil kontak dari WhatsApp.",
            }.get(status, f"Gagal sinkronisasi kontak ({status})")
            return redirect(url_for("customers", sync_error=reason))

        created = 0
        updated = 0
        for item in contacts:
            number = str(item.get("number", "") or "").strip()
            lid = str(item.get("lid", "") or "").strip()
            name = str(item.get("name", "") or "").strip()

            number_ok = number.isdigit() and 8 <= len(number) <= 15
            lid_ok = lid.isdigit() and 8 <= len(lid) <= 20
            if not number_ok and not lid_ok:
                continue

            # Match an existing contact by LID first, then by real number.
            customer = None
            if lid_ok:
                customer = Customer.query.filter_by(lid=lid).first()
            if customer is None and number_ok:
                customer = Customer.query.filter_by(phone=number).first()

            if customer is None:
                phone_val = number if number_ok else lid
                new_customer = Customer(
                    name=name or f"WhatsApp {phone_val[-4:]}",
                    phone=phone_val,
                    lid=lid if lid_ok else None,
                    notes="Sinkron dari WhatsApp",
                )
                db.session.add(new_customer)
                try:
                    db.session.flush()
                    created += 1
                except IntegrityError:
                    db.session.rollback()
            else:
                changed = False
                # Upgrade a LID-placeholder phone to the real number when known.
                if number_ok and customer.phone != number:
                    clash = Customer.query.filter(
                        Customer.phone == number, Customer.id != customer.id
                    ).first()
                    if clash is None:
                        customer.phone = number
                        changed = True
                if lid_ok and not customer.lid:
                    customer.lid = lid
                    changed = True
                if name and (
                    not customer.name
                    or customer.name.startswith("WhatsApp ")
                    or customer.name.startswith("Pelanggan ")
                ):
                    customer.name = name
                    changed = True
                if changed:
                    updated += 1

        db.session.add(
            AuditLog(
                actor_user_id=current_user_id(),
                action="customer.sync_whatsapp",
                details=f"created={created} updated={updated} total={len(contacts)}",
            )
        )
        db.session.commit()

        summary = f"Sinkron selesai: {created} kontak baru, {updated} diperbarui (dari {len(contacts)} kontak WhatsApp)."
        return redirect(url_for("customers", sync_ok=summary))

    @app.route("/users", methods=["GET", "POST"])
    @require_roles("admin")
    def users():
        message = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            role = request.form.get("role", "").strip()
            if username and password and role in {"admin", "cs", "technician"}:
                existing = User.query.filter_by(username=username).first()
                if not existing:
                    user = User(username=username, role=role)
                    user.set_password(password)
                    db.session.add(user)
                    db.session.add(
                        AuditLog(
                            actor_user_id=current_user_id(),
                            action="user.create",
                            details=f"username={username} role={role}",
                        )
                    )
                    db.session.commit()
                    message = "User berhasil ditambahkan"
        all_users = User.query.order_by(User.created_at.desc()).all()
        return render_template("users.html", users=all_users, message=message, partial=wants_partial())

    @app.route("/inbox")
    @require_roles("admin", "cs")
    def inbox():
        messages = (
            WhatsAppMessage.query.order_by(WhatsAppMessage.id.desc()).limit(500).all()
        )
        messages.reverse()  # oldest -> newest for natural reading order

        conversations: dict[str, dict] = {}
        for msg in messages:
            view = build_message_view(msg)
            key = view["conv_key"]
            conv = conversations.get(key)
            if conv is None:
                conv = {
                    "key": key,
                    "name": view["name"],
                    "number_label": view["number_label"],
                    "avatar": view["avatar"],
                    "messages": [],
                    "last_text": "",
                    "last_time": "",
                    "last_direction": "inbound",
                    "last_id": 0,
                    "reply_to": "",
                }
                conversations[key] = conv
            conv["messages"].append(view)
            conv["name"] = view["name"]
            conv["number_label"] = view["number_label"]
            conv["avatar"] = view["avatar"]
            conv["last_text"] = view["text"]
            conv["last_time"] = view["time"]
            conv["last_direction"] = view["direction"]
            conv["last_id"] = view["id"]
            if view["reply_to"]:
                conv["reply_to"] = view["reply_to"]

        conversation_list = sorted(
            conversations.values(), key=lambda c: c["last_id"], reverse=True
        )
        last_id = messages[-1].id if messages else 0
        return render_template(
            "inbox.html", conversations=conversation_list, last_id=last_id, partial=wants_partial()
        )

    @app.route("/api/whatsapp/stream")
    @require_roles("admin", "cs")
    def whatsapp_stream():
        try:
            after_id = int(request.args.get("after", "0"))
        except (TypeError, ValueError):
            after_id = 0

        def event_stream(start_id: int):
            last_seen = start_id
            idle_ticks = 0
            while True:
                with app.app_context():
                    new_messages = (
                        WhatsAppMessage.query
                        .filter(WhatsAppMessage.id > last_seen)
                        .order_by(WhatsAppMessage.id.asc())
                        .limit(50)
                        .all()
                    )
                    rows = [build_message_view(msg) for msg in new_messages]

                if rows:
                    last_seen = rows[-1]["id"]
                    idle_ticks = 0
                    yield f"data: {json.dumps(rows)}\n\n"
                else:
                    idle_ticks += 1
                    # Send a keepalive comment periodically so proxies/browsers
                    # do not close an idle connection.
                    if idle_ticks >= 5:
                        idle_ticks = 0
                        yield ": keepalive\n\n"

                time.sleep(3)

        response = Response(event_stream(after_id), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
        return response

    @app.post("/api/whatsapp/send")
    @require_roles("admin", "cs")
    def whatsapp_send():
        data = request.get_json(silent=True) or {}
        reply_to = str(data.get("reply_to", "") or "").strip()
        text = str(data.get("text", "") or "").strip()

        if not text:
            return jsonify({"ok": False, "error": "text is required"}), 400
        if not reply_to:
            return jsonify({"ok": False, "error": "reply target is required"}), 400

        chat_id = reply_to if "@" in reply_to else None
        phone = reply_to.split("@", 1)[0]

        message = send_and_log_message(phone, text, chat_id=chat_id)
        view = build_message_view(message)
        ok = message.status not in {"failed"}
        return jsonify({"ok": ok, "status": message.status, "message": view})

    @app.route("/reschedule", methods=["GET", "POST"])
    @require_roles("admin", "cs")
    def reschedule():
        message = None
        error = None

        def render_reschedules():
            data = Booking.query.filter_by(status="reschedule").order_by(
                Booking.scheduled_start.asc()
            ).all()
            notify = {}
            for b in data:
                notify[b.id] = {
                    "target": booking_notify_target(b.customer),
                    "message": booking_reschedule_message(b, b.scheduled_start),
                }
            return render_template(
                "reschedule.html",
                reschedules=data,
                notify=notify,
                message=message,
                error=error,
                partial=wants_partial(),
            )

        if request.method == "POST":
            action = request.form.get("action", "").strip()

            if action == "send_reminder":
                booking_id = int(request.form.get("booking_id", "0") or 0)
                text = request.form.get("message", "").strip()
                booking = Booking.query.get(booking_id)
                if not booking:
                    error = "Booking tidak ditemukan"
                elif not text:
                    error = "Pesan reminder tidak boleh kosong"
                else:
                    target = booking_notify_target(booking.customer)
                    if not target:
                        error = "Nomor WhatsApp customer tidak tersedia"
                    else:
                        sent = send_and_log_message(
                            target.split("@", 1)[0], text, chat_id=target
                        )
                        if sent.status == "failed":
                            error = "Gagal mengirim reminder (cek koneksi WhatsApp)"
                        else:
                            db.session.add(
                                AuditLog(
                                    actor_user_id=current_user_id(),
                                    action="booking.reschedule_reminder",
                                    details=f"booking_id={booking.id} to={target.split('@', 1)[0]}",
                                )
                            )
                            db.session.commit()
                            message = f"Reminder terkirim ke {booking.customer.name}"
                return render_reschedules()

            if action == "confirm_reschedule":
                booking_id = int(request.form.get("booking_id", "0") or 0)
                new_date_str = request.form.get("new_scheduled_start", "").strip()
                booking = Booking.query.get(booking_id)

                if not booking:
                    error = "Booking tidak ditemukan"
                elif booking.status != "reschedule":
                    error = "Booking tidak dalam status reschedule"
                else:
                    try:
                        try:
                            new_start = datetime.strptime(new_date_str, "%Y-%m-%dT%H:%M")
                        except ValueError:
                            new_start = datetime.strptime(new_date_str, "%Y-%m-%d")
                        new_end = compute_booking_end(booking.service_type, new_start)

                        # Do not enforce operating hours; only check conflicts
                        if has_conflict(new_start, new_end, exclude_booking_id=booking.id):
                            error = "Jadwal baru bentrok dengan booking lain"
                        else:
                            booking.scheduled_start = new_start
                            booking.scheduled_end = new_end
                            booking.status = "dikonfirmasi"
                            db.session.add(
                                AuditLog(
                                    actor_user_id=current_user_id(),
                                    action="booking.reschedule_confirm",
                                    details=f"booking_id={booking.id} new_start={new_start.isoformat()}",
                                )
                            )
                            db.session.commit()
                            message = f"Reschedule booking #{booking.id} dikonfirmasi. Jadwal baru: {new_start.strftime('%d-%m-%Y %H:%M')}"
                    except ValueError:
                        error = "Format tanggal tidak valid"
                    except Exception as e:
                        error = f"Gagal confirm reschedule: {str(e)}"

                return render_reschedules()

        return render_reschedules()

    @app.route("/maintenance", methods=["GET", "POST"])
    @require_roles("admin", "cs")
    def maintenance():
        """Manage maintenance reminders for customers with completed coating/ppf services."""
        message = None
        error = None

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            
            if action == "send_reminder":
                reminder_id = int(request.form.get("reminder_id", "0") or 0)
                reminder = MaintenanceReminder.query.get(reminder_id)
                if not reminder:
                    error = "Maintenance reminder tidak ditemukan"
                else:
                    customer = reminder.customer
                    message_text = request.form.get("message", "").strip()
                    if not message_text:
                        error = "Pesan tidak boleh kosong"
                    else:
                        sent = send_and_log_message(customer.phone, message_text)
                        if sent.status == "failed":
                            error = f"Gagal kirim reminder: {sent.status}"
                        else:
                            reminder.reminder_sent_at = datetime.utcnow()
                            db.session.add(
                                AuditLog(
                                    actor_user_id=current_user_id(),
                                    action="maintenance.reminder_sent",
                                    details=f"reminder_id={reminder_id} customer={customer.phone}",
                                )
                            )
                            db.session.commit()
                            message = f"Maintenance reminder terkirim ke {customer.name}"
            
            elif action == "send_review":
                reminder_id = int(request.form.get("reminder_id", "0") or 0)
                reminder = MaintenanceReminder.query.get(reminder_id)
                if not reminder:
                    error = "Maintenance reminder tidak ditemukan"
                else:
                    customer = reminder.customer
                    message_text = request.form.get("message", "").strip()
                    if not message_text:
                        error = "Pesan tidak boleh kosong"
                    else:
                        sent = send_and_log_message(customer.phone, message_text)
                        if sent.status == "failed":
                            error = f"Gagal kirim review request: {sent.status}"
                        else:
                            reminder.review_requested_at = datetime.utcnow()
                            db.session.add(
                                AuditLog(
                                    actor_user_id=current_user_id(),
                                    action="maintenance.review_requested",
                                    details=f"reminder_id={reminder_id} customer={customer.phone}",
                                )
                            )
                            db.session.commit()
                            message = f"Review request terkirim ke {customer.name}"

        # Get all active maintenance reminders (not yet sent or sent but reminder pending)
        reminders = MaintenanceReminder.query.join(Customer).join(Booking).order_by(
            MaintenanceReminder.maintenance_due_at.asc()
        ).all()

        # Pre-fill editable message drafts per reminder so CS/admin can tweak
        # the text before it's actually sent.
        reminder_template = get_setting("maintenance_reminder_template", DEFAULT_MAINTENANCE_REMINDER_TEMPLATE)
        review_template = get_setting("review_request_template", DEFAULT_REVIEW_REQUEST_TEMPLATE)
        review_link = get_setting("google_maps_business_url", "https://maps.google.com")
        drafts = {}
        for reminder in reminders:
            drafts[reminder.id] = {
                "reminder_message": reminder_template.format(
                    nama=reminder.customer.name,
                    layanan=reminder.service_type,
                    tanggal_selesai=reminder.completed_at.strftime("%d-%m-%Y"),
                ),
                "review_message": review_template.format(
                    nama=reminder.customer.name,
                    layanan=reminder.service_type,
                    link_review=review_link,
                ),
            }

        return render_template(
            "maintenance.html",
            reminders=reminders,
            drafts=drafts,
            message=message,
            error=error,
            now=datetime.utcnow(),
            partial=wants_partial(),
        )

    @app.route("/settings", methods=["GET", "POST"])
    @require_roles("admin")
    def settings():
        message = None
        error = None
        setting_keys = ["booking_done_template", "reschedule_template", "maintenance_reminder_template", "review_request_template", "google_maps_business_url"]

        if request.method == "POST":
            action = request.form.get("action", "save")
            if action == "service_create":
                name = request.form.get("service_name", "").strip()
                duration_value = request.form.get("service_duration", "").strip()
                duration_unit = request.form.get("service_unit", "menit").strip()
                try:
                    duration_num = float(duration_value)
                    # Convert to minutes
                    unit_multipliers = {"menit": 1, "jam": 60, "hari": 1440}
                    multiplier = unit_multipliers.get(duration_unit, 1)
                    duration_minutes = duration_num * multiplier
                    
                    if not name or len(name) < 3:
                        error = "Nama layanan harus minimal 3 karakter"
                    else:
                        existing = ServiceType.query.filter_by(name=name).first()
                        if existing:
                            error = "Layanan dengan nama ini sudah ada"
                        else:
                            service = ServiceType(name=name, duration_minutes=duration_minutes, active=True)
                            db.session.add(service)
                            db.session.add(
                                AuditLog(
                                    actor_user_id=current_user_id(),
                                    action="service.create",
                                    details=f"name={name} duration={duration_num}{duration_unit}",
                                )
                            )
                            db.session.commit()
                            message = f"Layanan '{name}' berhasil ditambahkan"
                except (ValueError, TypeError):
                    error = "Durasi harus berupa angka"
            elif action == "service_update":
                service_id = int(request.form.get("service_id", "0") or 0)
                name = request.form.get("service_name", "").strip()
                duration_value = request.form.get("service_duration", "").strip()
                duration_unit = request.form.get("service_unit", "menit").strip()
                service = ServiceType.query.get(service_id)
                if not service:
                    error = "Layanan tidak ditemukan"
                else:
                    try:
                        duration_num = float(duration_value)
                        # Convert to minutes
                        unit_multipliers = {"menit": 1, "jam": 60, "hari": 1440}
                        multiplier = unit_multipliers.get(duration_unit, 1)
                        duration_minutes = duration_num * multiplier
                        
                        if not name or len(name) < 3:
                            error = "Nama layanan harus minimal 3 karakter"
                        else:
                            # Check for name conflict with other services
                            conflict = ServiceType.query.filter(
                                ServiceType.name == name, ServiceType.id != service_id
                            ).first()
                            if conflict:
                                error = "Layanan dengan nama ini sudah ada"
                            else:
                                service.name = name
                                service.duration_minutes = duration_minutes
                                db.session.add(
                                    AuditLog(
                                        actor_user_id=current_user_id(),
                                        action="service.update",
                                        details=f"service_id={service_id} name={name} duration={duration_num}{duration_unit}",
                                    )
                                )
                                db.session.commit()
                                message = f"Layanan '{name}' berhasil diperbarui"
                    except (ValueError, TypeError):
                        error = "Durasi harus berupa angka"
            elif action == "service_delete":
                service_id = int(request.form.get("service_id", "0") or 0)
                service = ServiceType.query.get(service_id)
                if not service:
                    error = "Layanan tidak ditemukan"
                elif Booking.query.filter_by(service_type_id=service_id).count() > 0:
                    error = "Layanan tidak bisa dihapus karena masih digunakan di booking"
                else:
                    service_name = service.name
                    db.session.delete(service)
                    db.session.add(
                        AuditLog(
                            actor_user_id=current_user_id(),
                            action="service.delete",
                            details=f"service_id={service_id} name={service_name}",
                        )
                    )
                    db.session.commit()
                    message = f"Layanan '{service_name}' berhasil dihapus"
            elif action == "service_toggle":
                service_id = int(request.form.get("service_id", "0") or 0)
                service = ServiceType.query.get(service_id)
                if not service:
                    error = "Layanan tidak ditemukan"
                else:
                    service.active = not service.active
                    status = "diaktifkan" if service.active else "dinonaktifkan"
                    db.session.add(
                        AuditLog(
                            actor_user_id=current_user_id(),
                            action="service.toggle",
                            details=f"service_id={service_id} active={service.active}",
                        )
                    )
                    db.session.commit()
                    message = f"Layanan '{service.name}' berhasil {status}"
            elif action == "save":
                auto_public = request.url_root.strip().rstrip("/")
                set_setting("public_base_url", auto_public)

                booking_done_template = request.form.get("booking_done_template", "").strip()
                if booking_done_template:
                    set_setting("booking_done_template", booking_done_template)

                reschedule_template = request.form.get("reschedule_template", "").strip()
                if reschedule_template:
                    set_setting("reschedule_template", reschedule_template)

                maintenance_reminder_template = request.form.get("maintenance_reminder_template", "").strip()
                if maintenance_reminder_template:
                    set_setting("maintenance_reminder_template", maintenance_reminder_template)

                review_request_template = request.form.get("review_request_template", "").strip()
                if review_request_template:
                    set_setting("review_request_template", review_request_template)

                google_maps_business_url = request.form.get("google_maps_business_url", "").strip()
                if google_maps_business_url:
                    set_setting("google_maps_business_url", google_maps_business_url)

                db.session.add(
                    AuditLog(
                        actor_user_id=current_user_id(),
                        action="settings.whatsapp.update",
                        details="bridge-only",
                    )
                )
                db.session.commit()
                message = "Settings berhasil disimpan"
            elif action == "test_send":
                phone = request.form.get("test_phone", "").strip()
                text = request.form.get("test_message", "Tes koneksi dari Detailing Ops").strip()
                if not phone:
                    error = "Nomor tujuan wajib diisi untuk test kirim"
                else:
                    sent = send_and_log_message(phone, text)
                    if sent.status == "failed":
                        error = "Gagal kirim. Pastikan bridge QR aktif, API key benar, dan session QR sudah tersambung"
                    else:
                        message = f"Pesan test terkirim dengan status: {sent.status}"
            elif action == "wa_number_add":
                label = request.form.get("wa_number_label", "").strip()
                if not label:
                    error = "Nama/label nomor WhatsApp wajib diisi"
                else:
                    ok, status, instance = create_wa_instance(label)
                    if ok and instance:
                        db.session.add(
                            AuditLog(
                                actor_user_id=current_user_id(),
                                action="whatsapp.instance.create",
                                details=f"instance_id={instance.get('id')} label={label}",
                            )
                        )
                        db.session.commit()
                        message = f"Nomor WhatsApp '{label}' berhasil didaftarkan. Scan QR di bawah untuk menghubungkan."
                    else:
                        error = f"Gagal mendaftarkan nomor WhatsApp: {status}"
            elif action == "wa_number_delete":
                instance_id = request.form.get("instance_id", "").strip()
                if not instance_id:
                    error = "instance_id wajib diisi"
                else:
                    ok, status = delete_wa_instance(instance_id)
                    if ok:
                        db.session.add(
                            AuditLog(
                                actor_user_id=current_user_id(),
                                action="whatsapp.instance.delete",
                                details=f"instance_id={instance_id}",
                            )
                        )
                        db.session.commit()
                        message = "Nomor WhatsApp berhasil dihapus"
                    else:
                        error = f"Gagal menghapus nomor WhatsApp: {status}"

        settings_map = get_many(setting_keys)
        if not settings_map.get("booking_done_template"):
            settings_map["booking_done_template"] = get_setting(
                "booking_done_template", DEFAULT_BOOKING_DONE_TEMPLATE
            )
        if not settings_map.get("reschedule_template"):
            settings_map["reschedule_template"] = get_setting(
                "reschedule_template", DEFAULT_RESCHEDULE_TEMPLATE
            )
        if not settings_map.get("maintenance_reminder_template"):
            settings_map["maintenance_reminder_template"] = get_setting(
                "maintenance_reminder_template", DEFAULT_MAINTENANCE_REMINDER_TEMPLATE
            )
        if not settings_map.get("review_request_template"):
            settings_map["review_request_template"] = get_setting(
                "review_request_template", DEFAULT_REVIEW_REQUEST_TEMPLATE
            )
        if not settings_map.get("google_maps_business_url"):
            settings_map["google_maps_business_url"] = get_setting("google_maps_business_url", "")

        public_base_url = request.url_root.strip().rstrip("/")
        webhook_url = "(isi Public Base URL terlebih dahulu)"
        if public_base_url:  # pragma: no cover
            webhook_url = f"{public_base_url}/api/whatsapp/inbound"

        host_only = request.host.split(":")[0]
        profile = discover_bridge_profile(
            [
                f"http://{host_only}:3000",
            ]
        )
        bridge_base = profile.base_url if profile else ""
        bridge_detected = bool(bridge_base)
        bridge_qr_path = profile.qr_path if profile else "/qr"
        # Browser-facing: relative path through nginx's /wa-bridge/ proxy.
        # bridge_base (e.g. http://wa-bridge:3000) is a Docker-internal
        # hostname the user's browser can't resolve, so it's never embedded
        # directly in HTML sent to the browser.
        qr_url = f"{request.host_url.rstrip('/')}/wa-bridge{bridge_qr_path}" if (bridge_base and profile and profile.has_qr) else ""
        qr_embed_url = ""
        if qr_url:
            ts = int(datetime.utcnow().timestamp())
            qr_embed_url = f"/wa-bridge{bridge_qr_path}?t={ts}"

        wa_instances = []
        if bridge_detected:
            ok_instances, _, wa_instances_raw = list_wa_instances()
            if ok_instances:
                for inst in wa_instances_raw:
                    item = dict(inst)
                    inst_id = str(inst.get("id") or "")
                    item["qr_embed_url"] = (
                        wa_instance_qr_embed_url(inst_id)
                        if (inst_id and inst.get("has_qr"))
                        else ""
                    )
                    wa_instances.append(item)

        return render_template(
            "settings.html",
            settings=settings_map,
            services=ServiceType.query.order_by(ServiceType.created_at.desc()).all(),
            message=message,
            error=error,
            webhook_url=webhook_url,
            bridge_base=bridge_base,
            bridge_detected=bridge_detected,
            bridge_auth_required=profile.auth_required if profile else False,
            bridge_connected=profile.connected if profile else False,
            bridge_has_qr=profile.has_qr if profile else False,
            bridge_detected_from=profile.detected_from if profile else "",
            qr_url=qr_url,
            qr_embed_url=qr_embed_url,
            wa_instances=wa_instances,
            partial=wants_partial(),
        )

    @app.post("/api/whatsapp/inbound")
    def whatsapp_inbound():
        data = request.get_json(silent=True) or {}
        phone = str(data.get("phone", "")).strip()
        text = str(data.get("text", "")).strip()
        from_me = bool(data.get("from_me", False))
        if not phone:
            return jsonify({"ok": False, "error": "phone is required"}), 400

        if from_me:
            # A reply we sent ourselves (from the phone or via this app).
            # Skip the echo of messages already logged by the send endpoint.
            recent = (
                WhatsAppMessage.query
                .filter(WhatsAppMessage.direction == "outbound")
                .filter(WhatsAppMessage.message_text == text)
                .filter(
                    WhatsAppMessage.created_at
                    >= datetime.utcnow() - timedelta(seconds=120)
                )
                .first()
            )
            if recent:
                return jsonify({"ok": True, "status": "duplicate_skipped"})
            log_inbound_message(phone, text, data, direction="outbound")
            sync_customer_from_inbound(data, phone)
            return jsonify({"ok": True, "status": "logged_outbound"})

        # Record the incoming customer message. Auto-reply has been removed:
        # CS handles every conversation manually.
        log_inbound_message(phone, text, data)
        sync_customer_from_inbound(data, phone)

        # If the message is a structured booking form, create a pending booking
        # and register the customer automatically.
        form = parse_booking_form(text)
        if form:
            try:
                create_booking_from_form(form, data)
            except Exception:
                db.session.rollback()
                app.logger.exception("Failed to create booking from WhatsApp form")

        return jsonify({"ok": True, "status": "logged"})

    @app.post("/api/reminders/run")
    @require_roles("admin", "cs")
    def run_reminders():
        tz = ZoneInfo(app.config["APP_TIMEZONE"])
        now = datetime.now(tz=tz).replace(tzinfo=None)
        total = run_due_reminders(now)
        return jsonify({"ok": True, "sent": total})

    if not scheduler.running:
        tz = ZoneInfo(app.config["APP_TIMEZONE"])

        def scheduled_job() -> None:  # pragma: no cover
            with app.app_context():
                now = datetime.now(tz=tz).replace(tzinfo=None)
                run_due_reminders(now)

        scheduler.add_job(scheduled_job, "interval", minutes=10, id="reminder_job", replace_existing=True)
        scheduler.start()

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
