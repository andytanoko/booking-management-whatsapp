# Automatic & Manual Reminders

Two independent reminder systems exist: pre-appointment reminders (H-3/H-1/H-8)
and post-service maintenance/review reminders (6 months later).

## Pre-appointment reminders (H-3, H-1, H-8)

[app/services/reminders.py](../app/services/reminders.py) — `ReminderService`.

| Rule | Timing before `scheduled_start` |
|---|---|
| `H3` | 3 days |
| `H1` | 1 day |
| `H8` | 8 hours |

For each active booking and each rule, the service computes the target send
time (`scheduled_start - rule_delta`) and sends the reminder if `now` falls
within a **dispatch window** (default 15 minutes) after that target time —
so a reminder isn't missed if the scheduler runs a few minutes late, but
also isn't sent hours late. Each successful send is recorded in
`ReminderLog` (`booking_id`, `reminder_type`, `scheduled_for`, `sent_at`,
`status`) so `already_sent()` prevents duplicates.

`send_reminder()` builds the message with `format_reminder_message()`
(booking service name, customer name, formatted date/time) and sends it via
`send_and_log_message` (the same gateway used everywhere else — mock or
bridge).

### Triggering

- **Automatic**: a `BackgroundScheduler` (APScheduler) job runs every 10
  minutes (`app/app.py`, `scheduler.add_job(..., "interval", minutes=10)`),
  calling `run_due_reminders(now)` in the app's configured timezone
  (`Config.APP_TIMEZONE`).
- **Manual**: `POST /api/reminders/run` (`admin`/`cs`) runs the same check
  immediately and returns `{"ok": true, "sent": <count>}`.

## Maintenance & review reminders (6 months after coating/PPF)

When a booking's status is changed to `selesai` (done) **and** the service
is `Coating Premium` or `PPF`, the app automatically creates a
`MaintenanceReminder` row (`app/app.py`, inside the `/bookings` status-update
handler):

- `completed_at` = now
- `maintenance_due_at` = now + 180 days (6 months)

### Managing maintenance reminders (`/maintenance`)

`admin`/`cs` route, listing all `MaintenanceReminder` rows (joined with
customer/booking) ordered by `maintenance_due_at`. Two manual actions, each
shown as an expandable panel (`<details>`) with a pre-filled, **editable**
textarea so CS/admin can tweak the wording before it's actually sent:

| `action` | Effect |
|---|---|
| `send_reminder` | Sends the edited text (default draft built from `maintenance_reminder_template`) and stamps `reminder_sent_at` |
| `send_review` | Sends the edited text (default draft built from `review_request_template` + `google_maps_business_url`) and stamps `review_requested_at` |

The route rejects an empty `message` field ("Pesan tidak boleh kosong"),
mirroring the same editable-message pattern already used for booking-done
notifications (`/bookings`, `notify_customer`) and reschedule confirmations
(`/reschedule`, `send_reminder`).

Both actions log an `AuditLog` entry (`maintenance.reminder_sent` /
`maintenance.review_requested`) and use `send_and_log_message`, so failures
surface as an error banner instead of silently failing.

See [settings-and-templates.md](settings-and-templates.md) for editing the
message templates and the Google Maps business URL.
