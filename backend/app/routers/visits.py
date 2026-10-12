"""Clinical notes — VISIT-01..04."""
import datetime as dt
import re
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import snapshot
from ..db import get_db, utcnow
from ..deps import (check_version, clinic_filter, clinic_tz, conflict, ensure_clinic, ensure_scope_value, forbidden,
                    http_error, not_found, require)
from ..models import CLINIC_CODES, CLINIC_IDS, DENTAL, DERMA, Appointment, Patient, Staff, User, Visit, VisitAddendum
from ..timeutil import iso_utc, local_today

router = APIRouter(prefix="/visits", tags=["visits"])
SKIN = ("I", "II", "III", "IV", "V", "VI")
EDIT_WINDOW = timedelta(hours=24)


class VisitIn(BaseModel):
    patient_id: int
    clinic: Literal["dental", "derma"]
    doctor_id: int | None = None
    appointment_id: int | None = None
    date: dt.date | None = None
    complaint: str | None = None
    diagnosis: str | None = None
    treatment: str | None = None
    prescription: str | None = None
    teeth: str | None = None
    skin_type: str | None = None
    area: str | None = None
    follow_up: dt.date | None = None
    notes: str | None = None


class VisitPatch(BaseModel):
    doctor_id: int | None = None
    date: dt.date | None = None
    complaint: str | None = None
    diagnosis: str | None = None
    treatment: str | None = None
    prescription: str | None = None
    teeth: str | None = None
    skin_type: str | None = None
    area: str | None = None
    follow_up: dt.date | None = None
    notes: str | None = None
    version: int | None = None


class AddendumIn(BaseModel):
    text: str = Field(min_length=1)


def _norm_teeth(raw: str | None) -> str | None:
    if not raw:
        return None
    nums = []
    for tok in re.split(r"[\s,;]+", raw.strip()):
        if not tok:
            continue
        if not tok.isdigit() or not (11 <= int(tok) <= 85) or int(tok) % 10 == 0 or int(tok) % 10 > 8:
            raise http_error(422, f"Invalid FDI tooth number: {tok}", "validation", field="teeth")
        nums.append(str(int(tok)))
    return ",".join(dict.fromkeys(nums)) or None


def out(db: Session, v: Visit, user: User | None = None) -> dict:
    d = snapshot(v)
    d["clinic"] = CLINIC_CODES[v.clinic_id]
    doc = db.get(Staff, v.doctor_id) if v.doctor_id else None
    d["doctor_name"] = doc.name if doc else None
    p = db.get(Patient, v.patient_id)
    d["patient_name"] = p.name if p else None
    author = db.get(User, v.created_by) if v.created_by else None
    d["author"] = (author.staff.name if author and author.staff else author.username) if author else None
    d["locked"] = utcnow() >= v.locked_at
    d["locked_at"] = iso_utc(v.locked_at)
    d["can_edit"] = bool(user and not d["locked"] and (v.created_by == user.id or user.role == "admin"))
    adds = db.scalars(select(VisitAddendum).where(VisitAddendum.visit_id == v.id).order_by(VisitAddendum.id))
    d["addenda"] = []
    for a in adds:
        au = db.get(User, a.user_id) if a.user_id else None
        d["addenda"].append({"id": a.id, "text": a.text, "at": iso_utc(a.created_at),
                             "user": (au.staff.name if au and au.staff else au.username) if au else None})
    return d


def _get(db: Session, user: User, visit_id: int) -> Visit:
    v = db.get(Visit, visit_id)
    if not v:
        raise not_found("Clinical note")
    ensure_clinic(user, v.clinic_id)
    return v


def _validate_specialty(v: Visit) -> None:
    if v.skin_type and v.skin_type not in SKIN:
        raise http_error(422, "Fitzpatrick skin type must be I–VI", "validation", field="skin_type")
    if v.clinic_id == DERMA and v.teeth:
        v.teeth = None
    if v.clinic_id == DENTAL:
        v.skin_type, v.area = None, None


@router.get("")
def list_visits(
    patient_id: int | None = None, clinic: str | None = None, doctor: int | None = None,
    from_: dt.date | None = Query(None, alias="from"), to: date | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(require("visits.read")), db: Session = Depends(get_db),
):
    q = select(Visit).where(clinic_filter(Visit.clinic_id, user, clinic))
    if patient_id:
        q = q.where(Visit.patient_id == patient_id)
    if doctor:
        q = q.where(Visit.doctor_id == doctor)
    if from_:
        q = q.where(Visit.date >= from_)
    if to:
        q = q.where(Visit.date <= to)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Visit.date.desc(), Visit.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [out(db, v, user) for v in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/follow-ups")
def follow_ups(days: int = 0, clinic: str | None = None, user: User = Depends(require("visits.read")),
               db: Session = Depends(get_db)):
    """VISIT-04: open follow-up tasks due up to today (+days)."""
    today = local_today(clinic_tz(db))
    q = select(Visit).where(clinic_filter(Visit.clinic_id, user, clinic), Visit.follow_up.is_not(None),
                            Visit.follow_up_done.is_(False), Visit.follow_up <= today + timedelta(days=days))
    if user.role == "doctor" and user.staff_id:
        q = q.where(Visit.doctor_id == user.staff_id)
    rows = db.scalars(q.order_by(Visit.follow_up))
    return [{"visit_id": v.id, "patient_id": v.patient_id, "patient_name": db.get(Patient, v.patient_id).name,
             "follow_up": v.follow_up.isoformat(), "overdue": v.follow_up < today, "clinic": CLINIC_CODES[v.clinic_id],
             "diagnosis": v.diagnosis} for v in rows]


@router.get("/{visit_id}")
def get_visit(visit_id: int, user: User = Depends(require("visits.read")), db: Session = Depends(get_db)):
    return out(db, _get(db, user, visit_id), user)


@router.post("", status_code=201)
def create_visit(body: VisitIn, user: User = Depends(require("visits.write")), db: Session = Depends(get_db)):
    p = db.get(Patient, body.patient_id)
    if not p or p.archived:
        raise not_found("Patient")
    ensure_scope_value(user, p.clinic_scope)
    data = body.model_dump()
    clinic_id = CLINIC_IDS[data.pop("clinic")]
    ensure_clinic(user, clinic_id)
    if data["appointment_id"]:
        a = db.get(Appointment, data["appointment_id"])
        if not a or a.patient_id != p.id:
            raise not_found("Appointment")
    if not data["doctor_id"] and user.role == "doctor":
        data["doctor_id"] = user.staff_id
    data["teeth"] = _norm_teeth(data["teeth"])
    data["date"] = data["date"] or local_today(clinic_tz(db))
    now = utcnow()
    v = Visit(clinic_id=clinic_id, locked_at=now + EDIT_WINDOW, **data)
    _validate_specialty(v)
    db.add(v)
    db.commit()
    return out(db, v, user)


@router.patch("/{visit_id}")
def patch_visit(visit_id: int, body: VisitPatch, user: User = Depends(require("visits.write")),
                db: Session = Depends(get_db)):
    v = _get(db, user, visit_id)
    if utcnow() >= v.locked_at:
        raise conflict("This note is locked (older than 24 hours). Add an addendum instead.", "locked")
    if v.created_by != user.id and user.role != "admin":
        raise forbidden("Only the author can edit this note")
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    if "teeth" in data:
        data["teeth"] = _norm_teeth(data["teeth"])
    check_version(v, version)
    for k, val in data.items():
        setattr(v, k, val)
    if "follow_up" in data:
        v.follow_up_done = False
    _validate_specialty(v)
    db.commit()
    return out(db, v, user)


@router.post("/{visit_id}/addenda", status_code=201)
def add_addendum(visit_id: int, body: AddendumIn, user: User = Depends(require("visits.write")),
                 db: Session = Depends(get_db)):
    v = _get(db, user, visit_id)
    db.add(VisitAddendum(visit_id=v.id, text=body.text.strip(), user_id=user.id))
    db.commit()
    return out(db, v, user)


@router.post("/{visit_id}/follow-up-done")
def follow_up_done(visit_id: int, user: User = Depends(require("visits.write")), db: Session = Depends(get_db)):
    v = _get(db, user, visit_id)
    v.follow_up_done = True  # task state only, allowed after the note is locked
    db.commit()
    return {"ok": True}
