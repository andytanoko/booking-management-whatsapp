# WhatsApp Messaging

## Overview

The app talks to WhatsApp through a pluggable **gateway** abstraction
([app/services/whatsapp.py](../app/services/whatsapp.py)), so the rest of
the app never needs to know whether messages are actually sent or just
logged for testing.

```python
class WhatsAppGateway(ABC):
    def send_message(self, phone, text, chat_id=None) -> tuple[bool, str]: ...
```

Two implementations, selected by the `wa_mode` setting
(see [settings-and-templates.md](settings-and-templates.md)):

- **`MockWhatsAppGateway`** — logs the send and always reports success.
  Used for local development/testing without a real WhatsApp session.
- **`BridgeWhatsAppGateway`** — sends via the HTTP bridge described in
  [whatsapp-multi-number.md](whatsapp-multi-number.md) (auto-discovers the
  bridge's base URL, send path, and API key via `discover_bridge_profile()`).

`get_gateway()` reads `wa_mode` from settings (falls back to
`app.config["WHATSAPP_MODE"]`, default `mock`).

Every outbound send goes through `send_and_log_message(phone, text, chat_id)`,
which calls the active gateway and always writes a `WhatsAppMessage` row
(`direction="outbound"`) regardless of success/failure, recording the
gateway's status string (or `"failed"`).

## Inbox (`/inbox`)

`admin`/`cs` only. Groups all logged `WhatsAppMessage` rows into per-contact
conversations (keyed by phone/chat), showing the latest message, avatar/name,
and full history per conversation. Rendered by `app/templates/inbox.html`.

### Live updates

`GET /api/whatsapp/stream` is a Server-Sent-Events (SSE) endpoint that polls
for new `WhatsAppMessage` rows every 3 seconds and streams them as
`data: [...]\n\n` JSON events (with periodic `: keepalive` comments to keep
proxies/browsers from closing an idle connection). The inbox page uses this
to update conversations in real time without a full page reload.

### Manual reply

`POST /api/whatsapp/send` — body `{ "reply_to": "<phone or chat_id>", "text": "..." }`.
If `reply_to` contains `@` it's treated as a full chat id (e.g. a `@lid`
identity); otherwise it's a plain phone number. Calls
`send_and_log_message()` and returns the created message view as JSON.

## Inbound webhook

`POST /api/whatsapp/inbound` — called by the bridge (`APP_WEBHOOK_URL`) for
every message it sees. Body:

```json
{
  "phone": "628123456789",
  "text": "...",
  "from_me": false,
  "chat_id": "628123456789@c.us",
  "contact_name": "...",
  "contact_number": "...",
  "instance_id": "default"
}
```

Behavior:

- **`from_me: true`** (a message sent from the phone itself, or an echo of
  something this app just sent): deduplicates against a recent outbound
  message with the same text sent in the last 120 seconds (to avoid double-
  logging our own sends), otherwise logs it as `outbound` and syncs the
  customer record.
- **Otherwise**: logs the message as `inbound`, syncs/creates the customer
  (`sync_customer_from_inbound`), and checks whether the text is a
  structured **booking form** (see below). There is no automatic reply —
  CS handles every conversation manually from the inbox.

## Automatic booking creation

[app/services/message_service.py](../app/services/message_service.py)
(`MessageService.parse_booking_form`) recognizes free-text "forms" like:

```
Nama: Budi
No HP: 0812xxxxxxx
Merk & Type Mobil: Toyota Rush GR
Nomor Polisi: B1234XYZ
Pilihan Paket: Coating Premium Gold
Tanggal Masuk Mobil: 21-07-2026
```

Recognized labels are mapped via `BOOKING_FORM_LABELS` (name, phone,
vehicle type, license plate, package, domicile, schedule date, outlet,
etc). A message only counts as a valid booking form if it has **name**,
**phone**, and **package**. `parse_date()` supports `DD-MM-YYYY` /
`DD/DD/YYYY` / `DD.MM.YYYY` and relative dates like `"2 minggu"`,
`"3 hari"`, `"1 bulan"`.

When a valid form is detected, `whatsapp_inbound()` calls
`create_booking_from_form(form, data)`, which:

1. Normalizes/validates the phone, finds-or-creates the `Customer`.
2. Matches the free-text package name to a configured `ServiceType` using
   the semantic matcher — see
   [semantic-service-matching.md](semantic-service-matching.md).
3. Creates a `Booking` with `source="whatsapp"`.

Failures are caught and rolled back so a malformed form never crashes the
webhook (the webhook still responds `200 OK`).
