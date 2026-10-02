"""Lightweight additive migrations.

ParcelDesk ships new columns over time (receiving fields, SMS preferences, notification
channels…). Instead of a migration framework, on startup we compare each model's columns
with the actual database and ADD anything missing — safe for SQLite and PostgreSQL and a
no-op on fresh installs.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .database import Base

log = logging.getLogger("parceldesk.migrations")


def _default_sql(column, dialect: str) -> str:
    """SQL for a column default so existing rows get a sensible value."""
    default = getattr(column, "default", None)
    value = getattr(default, "arg", None)
    if value is None:
        try:
            return ""
        except Exception:  # pragma: no cover
            return ""
    if isinstance(value, bool):
        return " DEFAULT 1" if value else " DEFAULT 0"
    if isinstance(value, (int, float)):
        return f" DEFAULT {value}"
    if isinstance(value, str):
        safe = value.replace("'", "''")
        return f" DEFAULT '{safe}'"
    return ""


def sync_schema(engine: Engine) -> list[str]:
    """Add missing columns; returns the list of changes applied."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    applied: list[str] = []

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                type_sql = column.type.compile(dialect=engine.dialect)
                ddl = (f"ALTER TABLE {table.name} ADD COLUMN {column.name} {type_sql}"
                       f"{_default_sql(column, engine.dialect.name)}")
                try:
                    conn.execute(text(ddl))
                    applied.append(f"{table.name}.{column.name}")
                except Exception as exc:  # pragma: no cover
                    log.warning("Could not add column %s.%s: %s", table.name, column.name, exc)
                    continue
                # backfill nulls where the model expects a non-null default
                if column.default is not None and not column.nullable:
                    default = getattr(column.default, "arg", None)
                    if isinstance(default, (bool, int, float, str)):
                        literal = (f"'{default}'" if isinstance(default, str)
                                   else ("1" if default is True else "0" if default is False else str(default)))
                        try:
                            conn.execute(text(
                                f"UPDATE {table.name} SET {column.name} = {literal} "
                                f"WHERE {column.name} IS NULL"))
                        except Exception:  # pragma: no cover
                            pass

    if applied:
        log.info("Schema updated with new column(s): %s", ", ".join(applied))
    return applied
