# Detailing Ops (MVP)

Aplikasi web multi-user untuk operasional auto detailing dengan:
- Booking layanan: PPF, Coating, Polishing, Interior Detailing
- Integrasi inbound/outbound WhatsApp melalui endpoint adapter
- Reminder otomatis: H-3 hari, H-1 hari, H-8 jam
- Role-based access: admin, cs, technician

## 1) Fitur MVP

- Login multi-user
- Dashboard ringkas operasional
- Manajemen booking dengan validasi:
  - Jam operasional 09:00-18:00
  - Durasi layanan variatif
  - Cek bentrok jadwal
- Inbox pesan WhatsApp
- Halaman Settings untuk konfigurasi koneksi WhatsApp bridge QR
- Endpoint inbound WhatsApp:
  - `POST /api/whatsapp/inbound`
- Trigger reminder manual:
  - `POST /api/reminders/run`
- Scheduler background tiap 10 menit untuk reminder otomatis

## 2) Struktur Role

- `admin`: full access + manajemen user
- `cs`: kelola booking + inbox WA + trigger reminder
- `technician`: akses dashboard (bisa diperluas untuk update status job)

## 3) Quick Start (tanpa Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.app
```

Akses: http://localhost:5000

Akun bootstrap:
- Hanya `admin` yang dibuat otomatis saat startup jika belum ada.
- Password admin diambil dari env: `SEED_ADMIN_PASSWORD`.
- Jika env password tidak diisi, sistem membuat password acak satu kali (tidak hardcoded).

## 4) Quick Start (Docker)

```bash
cp .env.example .env
docker compose up --build
```

## 5) Contoh Payload Inbound WhatsApp

`POST /api/whatsapp/inbound`

```json
{
  "phone": "628123456789",
  "text": "Saya mau booking PPF 21-07-2026 10:00"
}
```

Jika parsing berhasil, sistem membuat booking `pending` dari sumber `whatsapp` lalu mengirim balasan otomatis.

## 6) Catatan Integrasi QR WhatsApp

Implementasi mendukung 2 mode:
- `mock`: untuk testing internal tanpa kirim WA nyata
- `bridge`: untuk koneksi ke WhatsApp QR gateway Anda

Konfigurasi dilakukan dari menu `Settings` (admin):
- `Mode WhatsApp`

Parameter teknis seperti URL bridge, API key, instance id, send path, dan QR path sekarang dideteksi otomatis oleh aplikasi.

### Arti Bridge Base URL

Bridge Base URL adalah alamat service WhatsApp gateway QR yang menjalankan sesi WhatsApp Web Anda.
Aplikasi sekarang akan mendeteksi URL bridge secara otomatis jika service bridge aktif.

Contoh:
- `http://127.0.0.1:3000` jika bridge jalan di mesin yang sama
- `http://10.0.0.15:3000` jika bridge ada di server internal lain
- `https://wa-bridge.domainanda.com` jika bridge dipublish lewat domain

Jika bridge aktif dan kompatibel, aplikasi akan otomatis menemukan endpoint QR dan endpoint kirim.

Untuk mode QR, jalankan bridge terpisah (misalnya gateway WhatsApp Web berbasis QR) lalu arahkan webhook inbound ke endpoint aplikasi ini:
- `POST /api/whatsapp/inbound`

Setelah settings tersimpan:
1. Buka URL QR bridge (ditampilkan pada halaman Settings)
2. Scan QR dengan WhatsApp Anda
3. Coba tombol `Kirim Test` dari halaman Settings

Catatan: aplikasi ini menampilkan QR dari service bridge. Aplikasi tidak mengimplementasikan protokol WhatsApp Web secara native.

## 7) Next Step Disarankan

- Tambah halaman kalender (drag-and-drop)
- Tambah assignment teknisi per booking
- Tambah retry queue untuk pengiriman WA gagal
- Migrasi DB ke PostgreSQL untuk production
- Migrasi gateway dari QR ke WhatsApp Business API saat siap produksi

## 8) Database Migration Workflow (Best Practice)

Project ini sekarang memakai Flask-Migrate (Alembic) untuk perubahan skema DB.

Perintah utama:

```bash
# Terapkan migration terbaru
flask db upgrade

# Seed data default (idempotent)
flask seed-defaults

# Buat revision migration baru setelah ubah model
flask db migrate -m "deskripsi perubahan"

# (Opsional) rollback 1 step
flask db downgrade -1
```

Catatan operasional:
- Docker startup menjalankan `flask db upgrade` otomatis sebelum app start.
- Docker startup juga menjalankan `flask seed-defaults` (idempotent).
- Local startup via `start.sh` menjalankan `flask db upgrade` + `flask seed-defaults` otomatis.
- Untuk setiap perubahan model (tambah/ubah kolom), selalu commit file di `migrations/versions/` bersama perubahan kode.
