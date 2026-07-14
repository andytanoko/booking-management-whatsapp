from __future__ import annotations

from app.models import AppSetting, db


def get_setting(key: str, default: str = "") -> str:
    item = AppSetting.query.filter_by(key=key).first()
    if not item:
        return default
    return item.value or default


def set_setting(key: str, value: str) -> None:
    item = AppSetting.query.filter_by(key=key).first()
    if not item:
        item = AppSetting(key=key, value=value)
        db.session.add(item)
    else:
        item.value = value


def get_many(keys: list[str]) -> dict[str, str]:
    rows = AppSetting.query.filter(AppSetting.key.in_(keys)).all()
    row_map = {row.key: (row.value or "") for row in rows}
    return {key: row_map.get(key, "") for key in keys}
