"""Appointments — APPT-01..06. Times are given and shown in clinic local time."""
import datetime as dt
from datetime import date, time, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..db import get_db, utcnow
from ..deps import (check_version, clinic_filter, clinic_tz, conflict, ensure_clinic, ensure_scope_value,
                    http_error, not_found, require)
from ..models import (APPT_INACTIVE, APPT_STATUSES, CLINIC_CODES, CLINIC_IDS, Appointment, AppointmentStatusLog,
                      Invoice, Patient, Service, Staff, User, Visit)
from ..permissions import can
from ..timeutil import day_bounds_utc, iso_utc, to_local, to_utc

router = APIRouter(prefix="/appointments", tags=["appointments"])


class ApptIn(BaseModel):
    patient_id: int
    clinic: str | None = None  # dental | derma; taken from the service when omitted
    doctor_id: int | None = None
    service_id: int | None = None
    date: dt.date
    time: dt.time
    duration_min: int | None = Field(default=None, ge=5, le=600)
    room: str | None = None
    notes: str | None = None
    override_reason: str | None = None


class ApptPatch(BaseModel):
    patient_id: int | None = None
    clinic: str | None = None
    doctor_id: int | None = None
    service_id: int | None = None
    date: dt.date | None = None
    time: dt.time | None = None
    duration_min: int | None = Field(default=None, ge=5, le=600)
    room: str | None = None
    notes: str | None = None
    override_reason: str | None = None
    version: int | None = None


class StatusIn(BaseModel):
    status: str


def out(db: Session, a: Appointment, tz) -> dict:
    p = db.get(Patient, a.patient_id)
    d = db.get(Staff, a.doctor_id) if a.doctor_id else None
    s = db.get(Service, a.service_id) if a.service_id else None
    local = to_local(a.start_at, tz)
    return {
        "id": a.id, "patient_id": a.patient_id, "patient_name": p.name if p else None,
        "patient_file_no": p.file_no if p else None, "patient_phone": p.phone if p else None,
        "clinic": CLINIC_CODES[a.clinic_id], "clinic_id": a.clinic_id,
        "doctor_id": a.doctor_id, "doctor_name": d.name if d else None,
        "service_id": a.service_id, "service_name": s.name if s else None,
        "room": a.room, "start_at": iso_utc(a.start_at), "end_at": iso_utc(a.end_at),
        "date": local.date().isoformat(), "time": local.strftime("%H:%M"),
        "duration_min": int((a.end_at - a.start_at).total_seconds() // 60),
        "status": a.status, "notes": a.notes, "override_reason": a.override_reason, "version": a.version,
        "visit_id": db.scalar(select(Visit.id).where(Visit.appointment_id == a.id)),
        "invoice_id": db.scalar(select(Invoice.id).where(Invoice.appointment_id == a.id, Invoice.status != "Void")),
    }


def _find_conflicts(db: Session, a: Appointment) -> list[Appointment]:
    who = [Appointment.patient_id == a.patient_id]
    if a.doctor_id:
        who.append(Appointment.doctor_id == a.doctor_id)
    if a.room:
        who.append(and_(Appointment.room == a.room, Appointment.clinic_id == a.clinic_id))
    q = select(Appointment).where(
        Appointment.status.not_in(APPT_INACTIVE), Appointment.start_at < a.end_at, Appointment.end_at > a.start_at,
        or_(*who),
    )
    if a.id:
        q = q.where(Appointment.id != a.id)
    return list(db.scalars(q))


def _check_overlap(db: Session, a: Appointment, user: User, reason: str | None, tz) -> None:
    """APPT-05: block doctor / room / patient double-booking; Admin may override with a reason."""
    if a.status in APPT_INACTIVE:
        return
    clashes = _find_conflicts(db, a)
    if not clashes:
        return
    if reason and reason.strip() and can(user.role, "appointments.override"):
        a.override_reason = reason.strip()
        db.flush()
        log_event(db, "override", "appointments", a.id,
                  after={"reason": a.override_reason, "conflicts_with": [c.id for c in clashes]})
        return
    details = []
    for c in clashes:
        kinds = []
        if a.doctor_id and c.doctor_id == a.doctor_id:
            kinds.append("doctor")
        if a.room and c.room == a.room and c.clinic_id == a.clinic_id:
            kinds.append("room")
        if c.patient_id == a.patient_id:
            kinds.append("patient")
        details.append({**out(db, c, tz), "clash": kinds})
    raise conflict("This time overlaps another booking", "overlap", conflicts=details,
                   can_override=can(user.role, "appointments.override"))


def _apply(db: Session, a: Appointment, data: dict, user: User, tz) -> None:
    if "patient_id" in data:
        p = db.get(Patient, data["patient_id"])
        if not p or p.archived:
            raise not_found("Patient")
        ensure_scope_value(user, p.clinic_scope)
        a.patient_id = p.id
    svc = None
    if data.get("service_id"):
        svc = db.get(Service, data["service_id"])
        if not svc:
            raise not_found("Service")
        a.service_id = svc.id
        a.clinic_id = svc.clinic_id  # APPT-03
    elif "service_id" in data:
        a.service_id = None
    if data.get("clinic"):
        if data["clinic"] not in CLINIC_IDS:
            raise http_error(422, "clinic must be dental or derma", "validation", field="clinic")
        if not svc:
            a.clinic_id = CLINIC_IDS[data["clinic"]]
    if not a.clinic_id:
        raise http_error(422, "Choose a clinic or a service", "validation", field="clinic")
    ensure_clinic(user, a.clinic_id)
    if "doctor_id" in data:
        if data["doctor_id"]:
            d = db.get(Staff, data["doctor_id"])
            if not d or not d.active:
                raise not_found("Doctor")
        a.doctor_id = data["doctor_id"]
    for k in ("room", "notes"):
        if k in data:
            setattr(a, k, data[k] or None)
    # timing
    cur_local = to_local(a.start_at, tz) if a.start_at else None
    cur_dur = int((a.end_at - a.start_at).total_seconds() // 60) if a.start_at else None
    d = data.get("date") or (cur_local.date() if cur_local else None)
    t = data.get("time") or (cur_local.time() if cur_local else None)
    duration = data.get("duration_min") or (svc.duration_min if svc else None) or cur_dur or 30
    if d is None or t is None:
        raise http_error(422, "Date and time are required", "validation")
    a.start_at = to_utc(d, t, tz)
    a.end_at = a.start_at + timedelta(minutes=duration)


@router.get("")
def list_appts(
    date_: dt.date | None = Query(None, alias="date"), days: int = Query(1, ge=1, le=42),
    doctor: int | None = None, room: str | None = None, clinic: str | None = None,
    patient_id: int | None = None, status: str | None = None,
    user: User = Depends(require("appointments.read")), db: Session = Depends(get_db),
):
    tz = clinic_tz(db)
    q = select(Appointment).where(clinic_filter(Appointment.clinic_id, user, clinic))
    if patient_id:
        q = q.where(Appointment.patient_id == patient_id)
    if date_:
        lo, hi = day_bounds_utc(date_, days, tz)
        q = q.where(Appointment.start_at >= lo, Appointment.start_at < hi)
    if doctor:
        q = q.where(Appointment.doctor_id == doctor)
    if room:
        q = q.where(Appointment.room == room)
    if status:
        q = q.where(Appointment.status == status)
    q = q.order_by(Appointment.start_at.desc() if patient_id and not date_ else Appointment.start_at)
    return [out(db, a, tz) for a in db.scalars(q.limit(2000))]


@router.get("/{appt_id}")
def get_appt(appt_id: int, user: User = Depends(require("appointments.read")), db: Session = Depends(get_db)):
    a = db.get(Appointment, appt_id)
    if not a:
        raise not_found("Appointment")
    ensure_clinic(user, a.clinic_id)
    return out(db, a, clinic_tz(db))


@router.post("", status_code=201)
def create_appt(body: ApptIn, user: User = Depends(require("appointments.write")), db: Session = Depends(get_db)):
    tz = clinic_tz(db)
    a = Appointment(status="Scheduled")
    data = body.model_dump()
    reason = data.pop("override_reason")
    _apply(db, a, data, user, tz)
    db.add(a)
    db.flush()
    _check_overlap(db, a, user, reason, tz)
    db.add(AppointmentStatusLog(appointment_id=a.id, from_status=None, to_status=a.status, user_id=user.id))
    db.commit()
    return out(db, a, tz)


@router.patch("/{appt_id}")
def patch_appt(appt_id: int, body: ApptPatch, user: User = Depends(require("appointments.write")),
               db: Session = Depends(get_db)):
    tz = clinic_tz(db)
    a = db.get(Appointment, appt_id)
    if not a:
        raise not_found("Appointment")
    ensure_clinic(user, a.clinic_id)
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    reason = data.pop("override_reason", None)
    check_version(a, version)
    _apply(db, a, data, user, tz)
    db.flush()
    _check_overlap(db, a, user, reason, tz)
    db.commit()
    return out(db, a, tz)


@router.post("/{appt_id}/status")
def set_status(appt_id: int, body: StatusIn, user: User = Depends(require("appointments.write")),
               db: Session = Depends(get_db)):
    tz = clinic_tz(db)
    a = db.get(Appointment, appt_id)
    if not a:
        raise not_found("Appointment")
    ensure_clinic(user, a.clinic_id)
    if body.status not in APPT_STATUSES:
        raise http_error(422, "Unknown status", "validation", field="status")
    if body.status == a.status:
        return out(db, a, tz)
    old = a.status
    a.status = body.status
    if old in APPT_INACTIVE and a.status not in APPT_INACTIVE:
        db.flush()
        _check_overlap(db, a, user, None, tz)  # re-activating must not create a double booking
    db.add(AppointmentStatusLog(appointment_id=a.id, from_status=old, to_status=a.status, user_id=user.id,
                                at=utcnow()))
    db.commit()
    result = out(db, a, tz)
    if a.status == "Completed":
        # APPT-06: offer a clinical note and a draft invoice, pre-filled
        result["next"] = {
            "visit": None if result["visit_id"] else {
                "patient_id": a.patient_id, "clinic": CLINIC_CODES[a.clinic_id], "doctor_id": a.doctor_id,
                "appointment_id": a.id, "date": result["date"],
            },
            "invoice": None if result["invoice_id"] else {
                "patient_id": a.patient_id, "clinic": CLINIC_CODES[a.clinic_id], "doctor_id": a.doctor_id,
                "appointment_id": a.id, "service_id": a.service_id,
            },
        }
    return result


@router.get("/{appt_id}/history")
def status_history(appt_id: int, user: User = Depends(require("appointments.read")), db: Session = Depends(get_db)):
    a = db.get(Appointment, appt_id)
    if not a:
        raise not_found("Appointment")
    ensure_clinic(user, a.clinic_id)
    tz = clinic_tz(db)
    rows = db.scalars(select(AppointmentStatusLog).where(AppointmentStatusLog.appointment_id == appt_id)
                      .order_by(AppointmentStatusLog.id))
    res = []
    for r in rows:
        u = db.get(User, r.user_id) if r.user_id else None
        res.append({"from": r.from_status, "to": r.to_status, "user": u.username if u else None,
                    "at": iso_utc(r.at), "local": to_local(r.at, tz).strftime("%Y-%m-%d %H:%M")})
    return res
