# Settings & Templates

Route: `/settings` (GET/POST, `admin` only), template
`app/templates/settings.html`. Backed by a simple key-value store
([app/services/settings_store.py](../app/services/settings_store.py) →
`AppSetting` table: `get_setting`, `set_setting`, `get_many`).

## WhatsApp mode

`wa_mode` — `mock` (testing, no real messages sent) or `bridge` (real
WhatsApp via the QR bridge). See
[whatsapp-messaging.md](whatsapp-messaging.md) for the gateway abstraction
and [whatsapp-multi-number.md](whatsapp-multi-number.md) for registering
additional numbers.

Saving settings also auto-captures `public_base_url` from the current
request (`request.url_root`) so the correct inbound webhook URL
(`{public_base_url}/api/whatsapp/inbound`) can be shown to configure on the
bridge side.

## Service catalog (`ServiceType`)

Manage the services customers can book (e.g. PPF, Coating Premium,
Polishing), each with a duration used for conflict/end-time calculation.

| `action` | Effect |
|---|---|
| `service_create` | Add a service; duration entered as a number + unit (`menit`/`jam`/`hari`), converted to minutes |
| `service_update` | Rename / change duration; rejects duplicate names |
| `service_delete` | Blocked if any booking references the service |
| `service_toggle` | Flip `active` (inactive services are hidden from new-booking forms but existing bookings keep working) |

Every change is recorded in `AuditLog`.

## Message templates

Editable templates with placeholders substituted at send time:

| Setting key | Used when | Placeholders |
|---|---|---|
| `booking_done_template` | Booking marked `selesai` | `{nama}`, `{layanan}`, `{tanggal}` |
| `reschedule_template` | Reschedule confirmation | `{nama}`, `{layanan}`, `{tanggal_lama}`, `{tanggal_baru}` |
| `maintenance_reminder_template` | 6-month maintenance reminder | `{nama}`, `{layanan}`, `{tanggal_selesai}` |
| `review_request_template` | Google review request | `{nama}`, `{layanan}`, `{link_review}` |

Defaults live in `app/app.py` as `DEFAULT_*_TEMPLATE` constants and are used
whenever a setting hasn't been customized yet.

## Google Maps business URL

`google_maps_business_url` — the link shared in the review-request
template (`{link_review}`), configured once and reused for every review
request sent from [maintenance](reminders-and-maintenance.md).

## Bridge connection status & test send

The Settings page auto-detects a running WhatsApp bridge
(`discover_bridge_profile()`), shows its connection status, and displays a
QR code to scan (for the default number). A **Test Kirim Pesan** form lets
an admin send a one-off message to any phone number to verify the
configured gateway works end-to-end.
