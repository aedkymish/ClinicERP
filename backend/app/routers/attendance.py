"""Attendance — ATT-01..04."""
import datetime as dt
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import (check_version, clinic_tz, conflict, forbidden, get_current_user, http_error, not_found,
                    require, settings_map)
from ..models import ATT_STATUSES, Attendance, Staff, User
from ..permissions import can
from ..services.export import export
from ..timeutil import iso_utc, local_today, month_bounds, to_local, to_utc

router = APIRouter(prefix="/attendance", tags=["attendance"])


class RecordIn(BaseModel):
    staff_id: int
    date: dt.date
    status: str
    clock_in: dt.time | None = None
    clock_out: dt.time | None = None
    note: str = Field(min_length=3)  # reason (ATT-03)


class RecordPatch(BaseModel):
    status: str | None = None
    clock_in: dt.time | None = None
    clock_out: dt.time | None = None
    note: str = Field(min_length=3)
    version: int | None = None


def _hm(dt: datetime | None, tz) -> str | None:
    return to_local(dt, tz).strftime("%H:%M") if dt else None


def out(db: Session, a: Attendance, tz) -> dict:
    s = db.get(Staff, a.staff_id)
    hours = round((a.clock_out - a.clock_in).total_seconds() / 3600, 2) if a.clock_in and a.clock_out else None
    corrected = db.get(User, a.corrected_by) if a.corrected_by else None
    return {"id": a.id, "staff_id": a.staff_id, "staff_name": s.name if s else None, "date": a.date.isoformat(),
            "clock_in": _hm(a.clock_in, tz), "clock_out": _hm(a.clock_out, tz), "clock_in_utc": iso_utc(a.clock_in),
            "status": a.status, "note": a.note, "hours": hours,
            "corrected_by": corrected.username if corrected else None, "version": a.version}


def is_late(db: Session, local_dt: datetime) -> bool:
    """ATT-02: later than shift start + grace minutes."""
    st = settings_map(db)
    h, m = (int(x) for x in (st["shift_start"] or "09:00").split(":"))
    limit = datetime.combine(local_dt.date(), time(h, m), tzinfo=local_dt.tzinfo) + timedelta(minutes=int(st["grace_min"] or 0))
    return local_dt > limit


def _own_staff(user: User) -> int:
    if not user.staff_id:
        raise http_error(422, "Your login is not linked to a staff record", "no_staff")
    return user.staff_id


@router.get("/today")
def today(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tz = clinic_tz(db)
    if not user.staff_id:
        return None
    a = db.scalar(select(Attendance).where(Attendance.staff_id == user.staff_id, Attendance.date == local_today(tz)))
    return out(db, a, tz) if a else None


@router.post("/clock-in")
def clock_in(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tz = clinic_tz(db)
    staff_id = _own_staff(user)
    now = utcnow()
    local_now = to_local(now, tz)
    a = db.scalar(select(Attendance).where(Attendance.staff_id == staff_id, Attendance.date == local_now.date()))
    if a and a.clock_in:
        raise conflict("You already clocked in today", "already")
    if not a:
        a = Attendance(staff_id=staff_id, date=local_now.date())
        db.add(a)
    a.clock_in = now  # ATT-01: server time
    a.status = "Late" if is_late(db, local_now) else "Present"
    db.commit()
    return out(db, a, tz)


@router.post("/clock-out")
def clock_out(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tz = clinic_tz(db)
    staff_id = _own_staff(user)
    a = db.scalar(select(Attendance).where(Attendance.staff_id == staff_id, Attendance.date == local_today(tz)))
    if not a or not a.clock_in:
        raise conflict("You have not clocked in today", "not_clocked_in")
    if a.clock_out:
        raise conflict("You already clocked out today", "already")
    a.clock_out = utcnow()
    db.commit()
    return out(db, a, tz)


def summarize(rows: list[dict]) -> dict:
    summary = {s: 0 for s in ATT_STATUSES}
    hours = 0.0
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
        hours += r["hours"] or 0
    summary["hours"] = round(hours, 2)
    return summary


COLUMNS = [("date", "Date"), ("staff_name", "Employee"), ("status", "Status"), ("clock_in", "In"),
           ("clock_out", "Out"), ("hours", "Hours"), ("note", "Note"), ("corrected_by", "Corrected by")]


@router.get("")
def sheet(month: str = Query(pattern=r"^\d{4}-\d{2}$"), staff_id: int | None = None, format: str | None = None,
          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ATT-04: monthly sheet; staff see their own, Admin/Finance everyone."""
    tz = clinic_tz(db)
    if not can(user.role, "attendance.manage"):
        if staff_id and staff_id != user.staff_id:
            raise forbidden()
        staff_id = _own_staff(user)
    first, last = month_bounds(month)
    q = select(Attendance).where(Attendance.date >= first, Attendance.date <= last)
    if staff_id:
        q = q.where(Attendance.staff_id == staff_id)
    rows = [out(db, a, tz) for a in db.scalars(q.order_by(Attendance.date, Attendance.staff_id))]
    if format:
        name = f"attendance-{month}" + (f"-{staff_id}" if staff_id else "")
        return export(db, rows, COLUMNS, format, name, "attendance", f"Attendance {month}")
    per_staff: dict[int, list] = {}
    for r in rows:
        per_staff.setdefault(r["staff_id"], []).append(r)
    return {"month": month, "rows": rows,
            "summary": {sid: {"staff_name": rs[0]["staff_name"], **summarize(rs)} for sid, rs in per_staff.items()}}


def _local_dt(d: date, t: time | None, tz) -> datetime | None:
    return to_utc(d, t, tz) if t else None


@router.post("", status_code=201)
def record(body: RecordIn, user: User = Depends(require("attendance.manage")), db: Session = Depends(get_db)):
    """ATT-03: record absence / leave / day off, or a missed clock-in, with a reason."""
    tz = clinic_tz(db)
    if body.status not in ATT_STATUSES:
        raise http_error(422, "Unknown status", "validation", field="status")
    if not db.get(Staff, body.staff_id):
        raise not_found("Staff member")
    a = db.scalar(select(Attendance).where(Attendance.staff_id == body.staff_id, Attendance.date == body.date))
    if not a:
        a = Attendance(staff_id=body.staff_id, date=body.date)
        db.add(a)
    a.status = body.status
    if body.clock_in:
        a.clock_in = _local_dt(body.date, body.clock_in, tz)
    if body.clock_out:
        a.clock_out = _local_dt(body.date, body.clock_out, tz)
    a.note = body.note.strip()
    a.corrected_by = user.id
    db.commit()
    return out(db, a, tz)


@router.patch("/{att_id}")
def correct(att_id: int, body: RecordPatch, user: User = Depends(require("attendance.manage")),
            db: Session = Depends(get_db)):
    tz = clinic_tz(db)
    a = db.get(Attendance, att_id)
    if not a:
        raise not_found("Attendance record")
    data = body.model_dump(exclude_unset=True)
    check_version(a, data.pop("version", None))
    if data.get("status"):
        if data["status"] not in ATT_STATUSES:
            raise http_error(422, "Unknown status", "validation", field="status")
        a.status = data["status"]
    if "clock_in" in data:
        a.clock_in = _local_dt(a.date, data["clock_in"], tz)
    if "clock_out" in data:
        a.clock_out = _local_dt(a.date, data["clock_out"], tz)
    if a.clock_in and a.clock_out and a.clock_out < a.clock_in:
        raise http_error(422, "Clock-out is before clock-in", "validation", field="clock_out")
    if "clock_in" in data and "status" not in data and a.status in ("Present", "Late") and a.clock_in:
        a.status = "Late" if is_late(db, to_local(a.clock_in, tz)) else "Present"
    a.note = body.note.strip()
    a.corrected_by = user.id
    db.commit()
    return out(db, a, tz)
