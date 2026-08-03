# Customer Management

## Overview

Route: `/customers` (GET/POST, `admin`/`cs`), template
`app/templates/customers.html`. Manages the customer address book used by
bookings and messaging.

## Fields

`Customer` model ([app/models.py](../app/models.py)): `name`, `phone`
(unique), `lid` (WhatsApp LID/privacy identifier, optional), `vehicle_info`,
`notes`, `created_at`.

## CRUD actions (`/customers` POST)

| `action` | Behavior |
|---|---|
| `create` (default) | Requires `name` + `phone`; rejects duplicate phone numbers |
| `update` | Updates an existing contact by `customer_id` |
| `delete` | Blocked if the customer has any bookings (`Booking.query.filter_by(customer_id=...)`) |

Search box (`?q=`) filters by name or phone (case-insensitive `ilike`).
The list view also shows a booking count per customer.

## Phone normalization

[app/services/customer_service.py](../app/services/customer_service.py)
(`CustomerService`):

- `normalize_phone()` — converts local formats (`0812...`, `+62812...`,
  `0812-345-6789`) into the canonical `628...` form.
- `validate_phone()` — must start with `628` and be 11–15 digits.
- `find_or_create(phone, lid, contact_name)` — used by the inbound WhatsApp
  webhook to auto-register a customer the first time they message in,
  matching by phone first and falling back to `lid`.

## Syncing from WhatsApp contacts

`POST /customers/sync` pulls the address book from the WhatsApp bridge
(`fetch_whatsapp_contacts()` in
[app/services/whatsapp.py](../app/services/whatsapp.py)) and creates/updates
local `Customer` records from real WhatsApp contacts (name + number),
skipping ones without a plausible phone number. Redirects back to
`/customers` with `sync_ok`/`sync_error` query params for the flash message.
