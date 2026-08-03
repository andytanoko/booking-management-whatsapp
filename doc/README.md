# Detailing Ops — Feature Documentation

This folder documents every major feature of the app. Each file covers what
the feature does, the relevant routes/services, and how to use it.

| Doc | Covers |
|---|---|
| [authentication-and-roles.md](authentication-and-roles.md) | Login, sessions, `admin`/`cs`/`technician` roles |
| [booking-management.md](booking-management.md) | Creating/editing bookings, statuses, conflict checks, customer notifications |
| [customer-management.md](customer-management.md) | Customer CRUD, phone normalization, WhatsApp contact sync |
| [whatsapp-messaging.md](whatsapp-messaging.md) | Inbox, live stream, manual send, inbound webhook, auto booking-form parsing, mock/bridge gateway |
| [whatsapp-multi-number.md](whatsapp-multi-number.md) | Registering additional WhatsApp numbers via QR code |
| [reminders-and-maintenance.md](reminders-and-maintenance.md) | Automatic H-3/H-1/H-8 reminders and 6-month maintenance/review reminders |
| [settings-and-templates.md](settings-and-templates.md) | WhatsApp mode, service catalog, message templates, Google Maps review link |
| [semantic-service-matching.md](semantic-service-matching.md) | Matching free-text package names to configured services |

## App at a glance

A Flask web app for running auto-detailing operations (PPF, coating,
polishing, interior detailing) with WhatsApp as the customer channel:

- Multi-user login with role-based access (`admin`, `cs`, `technician`)
- Booking calendar/list with operating-hours and conflict validation
- A CS inbox that mirrors WhatsApp conversations, with manual reply
- A WhatsApp "bridge" integration (QR-based, via `tools/wa-real-bridge`)
  that can also register multiple numbers
- Automatic booking reminders and post-service maintenance/review reminders
- An admin Settings page for WhatsApp mode, service catalog, and message
  templates

See the root [README.md](../README.md) for setup/quick-start instructions.
