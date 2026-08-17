---
name: python-development
description: "This skill should be used when the user asks to 'add a new feature', 'fix a python bug', 'write tests', or 'refactor backend code' in this project."
risk: low
source: internal
date_added: "2023-10-27"
---

# Python Development Skill

## Purpose
This skill provides the standard workflow for developing, testing, and maintaining the Python/Flask backend of this application. It ensures consistency in code style, error handling, and testing.

## Prerequisites
- Working knowledge of Flask and SQLite/PostgreSQL.
- Python 3.x environment with `requirements.txt` installed.
- `pytest` for running the test suite.

## Core Workflow

### 1. Feature Implementation
- **Models**: Add or update models in `app/models.py`. Ensure SQL schema in `db/schema.sql` reflects changes.
- **Services**: Business logic should reside in `app/services/` (e.g., `booking_engine.py`, `message_service.py`).
- **Blueprints/Routes**: Define endpoints in `app/app.py` or separate module files. Routes should only parse the request, call a service, and render/redirect — they must not contain business logic.

#### Table writes live in services
- **Read-only queries are fine anywhere.** Blueprints, routes, and templates MAY call `Model.query...` to fetch/display data.
- **Any write to a table MUST be handled by a service** in `app/services/`. Routes must not call `db.session.add/flush/commit/delete` or otherwise mutate model instances directly — that is business logic and belongs in the service layer. Instead call a service method (e.g. `CustomerService.sync_from_whatsapp(...)`, `CustomerService.find_or_create(...)`).
- When the same create/update (mutation) pattern appears in more than one place, extract it into a single reusable service method rather than duplicating it. Routes then just call that one method.
- Services own the mutation and the placeholder/validation rules; the caller decides when to `commit` only if the service explicitly defers it.

### 2. Standard Code Style
- Use type hinting where possible.
- Wrap database operations in try-except blocks.
- Use the `SettingsStore` for fetching configuration instead of hardcoding.

### 3. Testing Workflow
Before submitting any Python code, run the existing tests:
```bash
# Run all tests
pytest

# Run tests for a specific module
pytest tests/test_services.py
```
- New features **must** include a corresponding test file in `tests/`.

### 4. Database Changes
If changes involve the database:
1. Update `db/schema.sql`.
2. Update `db/seed.sql` if new default data is needed.
3. Ensure `app/models.py` matches the new schema.

## Common Snippets

### Adding a Service Method
```python
def my_new_action(data):
    try:
        # logic here
        return {"status": "success", "data": data}
    except Exception as e:
        app.logger.error(f"Error in my_new_action: {e}")
        return {"status": "error", "message": str(e)}
```

## Constraints
- **Safety**: Never hardcode credentials. Use `.env` or `app/config.py`.
- **Database**: Always use parameterized queries to prevent SQL injection.
- **Database**: Read-only queries are allowed in routes/blueprints, but all table **writes** (`db.session.add/flush/commit/delete`, model mutations) must live in a service under `app/services/`. No stray write/business logic outside the service layer.
- **Logging**: Use `app.logger` for errors rather than `print()`.

## Patterns & Lessons
- **Don't persist fabricated placeholder identity values.** Never write a made-up name/label (e.g. `WhatsApp <last4>`, `Pelanggan ...`) into a table just because the real value is missing. Only store real, detected values; gate row creation on a real value being present, and compute display fallbacks (e.g. `Kontak WhatsApp`) at render time. Keep the "is this a placeholder?" test in one shared helper (e.g. `CustomerService.is_placeholder_name`).
- **One find-or-create/update method per concept.** When the same match → create-if-real → backfill pattern appears in multiple entry points (sync button, inbound webhook, service layer), collapse it into a single service method instead of duplicating query + mutation logic.
- **Return a status, let the caller own the commit.** Such a method should return `(entity_or_None, status)` with `status` in `{created, updated, unchanged, skipped}`, do `add`/`flush` (for FK/ids) but **not** `commit`. Callers commit once (bulk loop) or per-event (webhook) as appropriate. This preserves transaction control and lets routes tally results without embedding logic.

## When to Use
Use this skill when modifying any `.py` files, adding new API endpoints, or improving the logic in the `app/services/` directory.