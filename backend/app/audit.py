"""Audit trail (AUD-01..03).

Every ORM insert/update/delete is captured automatically by a flush listener, with before/after
values. Non-CRUD events (sign-in, void, refund, override, export, view, restore...) are written with
``log_event``.
"""
import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .db import utcnow
from .models import AuditLog, UserSession

FINANCIAL_ENTITIES = {
    "invoices", "invoice_lines", "payments", "credit_notes", "expenses",
    "payroll_runs", "payroll_lines", "services", "staff",
}
REDACTED = {"password_hash"}
SKIP_TABLES = {"audit_log", "user_sessions"}
# Column changes that are pure bookkeeping and would only add noise
NOISE = {"updated_at", "version"}


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def snapshot(obj: Any) -> dict:
    return {
        c.key: ("***" if c.key in REDACTED else _jsonable(getattr(obj, c.key)))
        for c in inspect(obj).mapper.column_attrs
    }


def _dump(d: dict | None) -> str | None:
    return None if d is None else json.dumps(d, ensure_ascii=False, default=str)


def _row(session: Session, action: str, entity: str, entity_id: int | None, before: dict | None,
         after: dict | None, user_id: int | None = None) -> dict:
    return {
        "user_id": user_id if user_id is not None else session.info.get("user_id"),
        "at": utcnow(),
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "before_json": _dump(before),
        "after_json": _dump(after),
        "ip": session.info.get("ip"),
        "financial": entity in FINANCIAL_ENTITIES,
    }


def log_event(db: Session, action: str, entity: str, entity_id: int | None = None,
              before: dict | None = None, after: dict | None = None, user_id: int | None = None) -> None:
    db.add(AuditLog(**_row(db, action, entity, entity_id, before, after, user_id)))


_PENDING = "_audit_pending"


@event.listens_for(Session, "before_flush")
def _before_flush(session: Session, *_):
    pending = session.info.setdefault(_PENDING, [])
    for obj in session.dirty:
        table = getattr(obj, "__tablename__", None)
        if table in SKIP_TABLES or table is None or not session.is_modified(obj):
            continue
        state = inspect(obj)
        before, after = {}, {}
        for attr in state.mapper.column_attrs:
            hist = state.attrs[attr.key].history
            if hist.has_changes() and attr.key not in NOISE:
                old = hist.deleted[0] if hist.deleted else None
                new = hist.added[0] if hist.added else None
                masked = attr.key in REDACTED
                before[attr.key] = "***" if masked else _jsonable(old)
                after[attr.key] = "***" if masked else _jsonable(new)
        if after:
            pending.append(("update", table, obj, before, after))
    for obj in session.deleted:
        table = getattr(obj, "__tablename__", None)
        if table and table not in SKIP_TABLES:
            pending.append(("delete", table, obj, snapshot(obj), None))
    actor = session.info.get("user_id")
    for obj in session.new:
        if actor and hasattr(obj, "created_by") and obj.created_by is None:
            obj.created_by = actor
        table = getattr(obj, "__tablename__", None)
        if table and table not in SKIP_TABLES:
            pending.append(("create", table, obj, None, None))


@event.listens_for(Session, "after_flush")
def _after_flush(session: Session, _ctx):
    pending = session.info.pop(_PENDING, [])
    if not pending:
        return
    rows = []
    for action, table, obj, before, after in pending:
        if action == "create":
            after = snapshot(obj)
        rows.append(_row(session, action, table, getattr(obj, "id", None), before, after))
    session.connection().execute(AuditLog.__table__.insert(), rows)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session):
    session.info.pop(_PENDING, None)


__all__ = ["log_event", "snapshot", "FINANCIAL_ENTITIES", "UserSession"]
