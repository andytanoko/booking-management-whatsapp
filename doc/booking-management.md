# Booking Management

## Overview

Bookings tie a `Customer` to a `ServiceType` for a scheduled time window,
with a status workflow and automatic customer notifications on key statuses.

Route: `/bookings` (GET/POST), edit: `/bookings/<id>/edit` — both restricted
to `admin` and `cs` (`app/templates/bookings.html`, `edit_booking.html`).

## Statuses

Defined in `BOOKING_STATUSES` in [app/app.py](../app/app.py):

| Key | Label |
|---|---|
| `dikonfirmasi` | Dikonfirmasi |
| `kendaraan_masuk` | Kendaraan Masuk |
| `dikerjakan` | Dikerjakan |
| `qc` | QC / Cek Hasil |
| `siap_diambil` | Siap Diambil |
| `selesai` | Selesai |
| `reschedule` | Reschedule |
| `cancel` / `batal` | Cancel / Batal |

`NOTIFY_ON_STATUS = {"siap_diambil", "selesai"}` — moving a booking into
either of these statuses sends the customer a WhatsApp message built from
an editable template (see [settings-and-templates.md](settings-and-templates.md)).

## Validation rules ([app/services/booking_engine.py](../app/services/booking_engine.py))

- **Operating hours**: bookings must fall within `09:00`–`18:00`
  (`is_within_operating_hours`).
- **Duration**: computed from the selected `ServiceType.duration_minutes`
  (`compute_booking_end`).
- **Conflict check**: `has_conflict` rejects overlapping bookings for the
  same time slot.

## Fields captured

`Booking` (see [app/models.py](../app/models.py)) stores: customer, service
type, scheduled start/end, status, source (`manual` or `whatsapp`), notes,
`other_info` (package name), `vehicle_type`, `license_plate`, creator user,
and assigned technician.

## Creating a booking

- **Manually**: admin/cs fills the form on `/bookings`.
- **From WhatsApp**: when an inbound message matches the structured booking
  form pattern, a `pending`/`dikonfirmasi` booking is created automatically
  with `source="whatsapp"` — see
  [whatsapp-messaging.md](whatsapp-messaging.md#automatic-booking-creation).

## Updating status

`action=update_status` on `/bookings` updates `Booking.status`. If the new
status is in `NOTIFY_ON_STATUS`, the rendered template computes a
notification target (`booking_notify_target`) and message
(`booking_done_message`) that CS can review/send from the bookings table.

## Reschedule flow

`/reschedule` (GET/POST, `admin`/`cs`) lists bookings with
`status == "reschedule"` and lets CS confirm a new date/time, sending a
reschedule confirmation message built from the reschedule template.

## Audit trail

Status changes, service catalog edits, and other mutating actions are
recorded in `AuditLog` with an `action` string and free-text `details`.
