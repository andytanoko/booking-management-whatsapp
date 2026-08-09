# Authentication & Roles

## Overview

Simple session-based login (Flask session cookie), no external identity
provider. Passwords are hashed with `pbkdf2:sha256` (see `User` model in
[app/models.py](../app/models.py)).

## Routes

| Route | Method | Access |
|---|---|---|
| `/login` | GET, POST | public |
| `/logout` | GET | any logged-in user |
| `/` | GET | redirects to `/dashboard` or `/login` |

Login checks `User.query.filter_by(username=..., active=True)` and verifies
the password with `check_password()`. On success, `login_user(user.id, user.role)`
stores `user_id` and `role` in the session (see [app/auth.py](../app/auth.py)).

## Roles

| Role | Access |
|---|---|
| `admin` | Everything, including Users and Settings |
| `cs` | Bookings, customers, inbox, reschedule, maintenance, reminders |
| `technician` | Dashboard only (read-only operational overview) |

Enforcement is done with two decorators from `app/auth.py`:

- `@require_auth` — must be logged in (any role), else `401`
- `@require_roles("admin", "cs")` — must be logged in **and** have one of
  the listed roles, else `401` (not logged in) or `403` (wrong role)

Every protected route in `app/app.py` is annotated with one of these, e.g.:

```python
@app.route("/settings", methods=["GET", "POST"])
@require_roles("admin")
def settings():
    ...
```

## Default accounts (from README quick start)

- `admin` / `admin123`
- `cs1` / `cs123`
- `tech1` / `tech123`

## Managing users

Admins manage users on `/users` (`app/templates/users.html`): create new
users with a username, password, and role (`admin`, `cs`, `technician`).
Every creation is recorded in `AuditLog` (`action="user.create"`).
