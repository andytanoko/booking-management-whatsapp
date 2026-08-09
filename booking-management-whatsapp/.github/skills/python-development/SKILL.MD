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
- **Blueprints/Routes**: Define endpoints in `app/app.py` or separate module files.

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
- **Logging**: Use `app.logger` for errors rather than `print()`.

## When to Use
Use this skill when modifying any `.py` files, adding new API endpoints, or improving the logic in the `app/services/` directory.