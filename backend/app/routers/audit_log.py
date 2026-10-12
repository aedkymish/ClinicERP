"""Audit log viewer — AUD-02. Read-only: there is no update or delete endpoint."""
import json
from datetime import date, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import clinic_tz, require
from ..models import AuditLog, User
from ..services.export import export
from ..timeutil import iso_utc, to_local, to_utc

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(
    user_id: int | None = None, entity: str | None = None, action: str | None = None, entity_id: int | None = None,
    from_: date | None = Query(None, alias="from"), to: date | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), format: str | None = None,
    user: User = Depends(require("audit")), db: Session = Depends(get_db),
):
    tz = clinic_tz(db)
    q = select(AuditLog)
    if user.role != "admin":
        q = q.where(AuditLog.financial.is_(True))  # Finance: financial events only
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if entity:
        q = q.where(AuditLog.entity == entity)
    if action:
        q = q.where(AuditLog.action == action)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if from_:
        q = q.where(AuditLog.at >= to_utc(from_, time(0), tz))
    if to:
        q = q.where(AuditLog.at < to_utc(to + timedelta(days=1), time(0), tz))
    users = {u.id: u.username for u in db.scalars(select(User))}

    def row(a: AuditLog) -> dict:
        return {"id": a.id, "at": iso_utc(a.at), "local": to_local(a.at, tz).strftime("%Y-%m-%d %H:%M:%S"),
                "user_id": a.user_id, "user": users.get(a.user_id), "action": a.action, "entity": a.entity,
                "entity_id": a.entity_id, "before": json.loads(a.before_json) if a.before_json else None,
                "after": json.loads(a.after_json) if a.after_json else None, "ip": a.ip}

    q = q.order_by(AuditLog.id.desc())
    if format:
        rows = [row(a) | {"before": a.before_json, "after": a.after_json} for a in db.scalars(q.limit(50000))]
        cols = [("local", "Time"), ("user", "User"), ("action", "Action"), ("entity", "Entity"),
                ("entity_id", "Record"), ("before", "Before"), ("after", "After"), ("ip", "IP")]
        return export(db, rows, cols, format, "audit-log", "audit_log", "Audit log")
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = [row(a) for a in db.scalars(q.offset((page - 1) * page_size).limit(page_size))]
    entities = [e for (e,) in db.execute(select(AuditLog.entity).distinct().order_by(AuditLog.entity))]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "entities": entities}
