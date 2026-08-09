from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import abort, session


def login_user(user_id: int, role: str) -> None:
    session["user_id"] = user_id
    session["role"] = role


def logout_user() -> None:
    session.pop("user_id", None)
    session.pop("role", None)


def current_user_id() -> int | None:
    return session.get("user_id")


def current_user_role() -> str | None:
    return session.get("role")


def require_auth(fn: Callable):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user_id():
            abort(401)
        return fn(*args, **kwargs)

    return wrapper


def require_roles(*allowed_roles: str):
    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user_id():
                abort(401)
            if current_user_role() not in allowed_roles:
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
