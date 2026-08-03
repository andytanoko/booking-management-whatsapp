# Multi-Number WhatsApp Registration (QR Code)

This feature lets you connect **more than one WhatsApp number** to the app.
Each number runs as its own independent session on the bridge and is linked
by scanning its own QR code — the same way the original single-number setup
works, just repeated per number.

## Why

The original bridge (`tools/wa-real-bridge/bridge.js`) only ever managed a
single `whatsapp-web.js` client (one phone number). Businesses that run
multiple WhatsApp numbers (e.g. per branch, per CS agent) needed a way to
register additional numbers without standing up a second bridge process.

## How it works

### Bridge (`tools/wa-real-bridge/bridge.js`)

The bridge now manages a **map of instances**, keyed by an `instance_id`.
Each instance owns its own `whatsapp-web.js` `Client` (and therefore its own
`LocalAuth` session folder, QR code, and connection state).

- The original number is preserved as the `default` instance
  (`clientId: "detailing-ops"`), so an already-paired device does **not**
  need to re-scan after upgrading.
- Registered instances (id, label, clientId) persist to
  `tools/wa-real-bridge/instances.json` so they survive bridge restarts.

New endpoints:

| Method | Path                          | Purpose                                   |
|--------|-------------------------------|--------------------------------------------|
| GET    | `/instances`                  | List all registered numbers + live status  |
| POST   | `/instances`                  | Register a new number (`{ "label": "..." }`), starts pairing |
| GET    | `/instances/:id/status`       | Status of one instance                     |
| GET    | `/instances/:id/qr`           | PNG QR code to scan for that instance      |
| POST   | `/instances/:id/send-message` | Send a message via that specific instance  |
| DELETE | `/instances/:id`              | Logout + remove a number (not `default`)   |

The original single-session endpoints (`/health`, `/status`, `/qr`,
`/contacts`, `/send-message`) are unchanged and always operate on the
`default` instance, so existing integrations keep working.

Inbound messages (`message_create`) now also carry `instance_id`,
`instance_label`, and `instance_phone` in the payload forwarded to
`APP_WEBHOOK_URL`, so you can tell which number received a message.

### Python (`app/services/whatsapp.py`)

New helper functions call the bridge's instance endpoints:

- `list_wa_instances()` — fetch all registered numbers and their status
- `create_wa_instance(label)` — register a new number, returns its `id`
- `delete_wa_instance(instance_id)` — remove a number
- `wa_instance_qr_embed_url(base_url, instance_id)` — cache-busted QR image URL

### Settings page (`/settings`)

A new **"Nomor WhatsApp Terdaftar"** (Registered WhatsApp Numbers) section:

- Lists every registered number with its label, instance ID, connection
  status, phone number (once connected), and QR code (while pending).
- A form to add a new number: enter a label (e.g. "CS 2", "Cabang Selatan")
  and submit — the bridge immediately starts a new session and a QR code
  appears in the table.
- Each non-default number has a **Hapus** (delete) button to log out and
  remove it.

## Usage

1. Make sure the bridge is running (`node tools/wa-real-bridge/bridge.js`,
   port `3000` by default) and Mode WhatsApp is set to **Bridge QR**.
2. Go to **Settings**.
3. Under "Nomor WhatsApp Terdaftar", enter a label for the new number and
   click **Tambah Nomor & Generate QR**.
4. Scan the QR code that appears in the table using WhatsApp on the phone
   for that number.
5. Once connected, the row shows "Terhubung" and the linked phone number.
6. To remove a number, click **Hapus** next to it (this logs out that
   session on the bridge and deletes its local auth data).

## Notes / limitations

- The `default` instance cannot be deleted from the UI/API.
- Outbound sends via `send_and_log_message` / `BridgeWhatsAppGateway` still
  target the `default` instance; routing a specific outbound message through
  a non-default number would require passing an `instance_id` through that
  call path (not yet wired into the UI).
- Each additional number spins up its own Puppeteer/Chromium instance under
  the hood, so registering many numbers increases memory/CPU usage on the
  host running the bridge.
