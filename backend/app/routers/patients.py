"""Patients, documents and the dental chart — PAT-01..07, CHART-01..03, AUD-03."""
import mimetypes
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..audit import log_event, snapshot
from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import (check_version, conflict, ensure_scope_value, forbidden, http_error, not_found, require,
                    scope_values)
from ..models import TOOTH_CONDITIONS, Invoice, Patient, PatientFile, Staff, ToothEntry, User, Visit
from ..permissions import can
from ..services.billing import totals
from ..services.export import export

router = APIRouter(prefix="/patients", tags=["patients"])
Scope = Literal["dental", "derma", "both"]
ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp", "image/heic"}
PERMANENT = {q * 10 + n for q in (1, 2, 3, 4) for n in range(1, 9)}
PRIMARY = {q * 10 + n for q in (5, 6, 7, 8) for n in range(1, 6)}


class PatientIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=3, max_length=40)
    email: str | None = None
    dob: date | None = None
    gender: Literal["male", "female", "other"] | None = None
    address: str | None = None
    insurance: str | None = None
    allergies: str | None = None
    history: str | None = None
    notes: str | None = None
    clinic_scope: Scope = "both"


class PatientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    phone: str | None = Field(default=None, min_length=3, max_length=40)
    email: str | None = None
    dob: date | None = None
    gender: Literal["male", "female", "other"] | None = None
    address: str | None = None
    insurance: str | None = None
    allergies: str | None = None
    history: str | None = None
    notes: str | None = None
    clinic_scope: Scope | None = None
    version: int | None = None


class ToothIn(BaseModel):
    tooth: int
    surface: str | None = Field(default=None, max_length=10)
    condition: str
    note: str | None = None
    visit_id: int | None = None


def balance_of(db: Session, patient_id: int) -> int:
    invs = db.scalars(select(Invoice).where(Invoice.patient_id == patient_id, Invoice.status != "Void"))
    return sum(max(totals(i).balance, 0) for i in invs)


def out(p: Patient, balance: int | None = None) -> dict:
    d = {k: v for k, v in snapshot(p).items() if k not in ("created_by",)}
    if balance is not None:
        d["balance"] = balance
    return d


def get_patient(db: Session, user: User, patient_id: int) -> Patient:
    p = db.get(Patient, patient_id)
    if not p:
        raise not_found("Patient")
    ensure_scope_value(user, p.clinic_scope)
    return p


def _norm_phone(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())[-9:]


def find_duplicates(db: Session, name: str, phone: str, dob: date | None, exclude: int | None = None) -> list[Patient]:
    digits = _norm_phone(phone)
    conds = []
    if digits:
        conds.append(func.replace(func.replace(func.replace(Patient.phone, " ", ""), "-", ""), "+", "").like(f"%{digits}"))
    if dob:
        conds.append(and_(func.lower(Patient.name) == name.strip().lower(), Patient.dob == dob))
    if not conds:
        return []
    q = select(Patient).where(or_(*conds))
    if exclude:
        q = q.where(Patient.id != exclude)
    return list(db.scalars(q.limit(10)))


COLUMNS = [("file_no", "File no."), ("name", "Name"), ("phone", "Phone"), ("email", "Email"), ("dob", "Date of birth"),
           ("gender", "Gender"), ("clinic_scope", "Clinic"), ("insurance", "Insurance"), ("allergies", "Allergies"),
           ("address", "Address")]


@router.get("")
def list_patients(
    q: str | None = None, clinic: str | None = None, archived: bool = False,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), format: str | None = None,
    user: User = Depends(require("patients.read")), db: Session = Depends(get_db),
):
    query = select(Patient).where(Patient.clinic_scope.in_(scope_values(user, clinic)))
    query = query.where(Patient.archived.is_(archived)) if (archived and can(user.role, "patients.archive")) \
        else query.where(Patient.archived.is_(False))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Patient.name.ilike(like), Patient.phone.ilike(like), Patient.file_no.ilike(like),
                                Patient.email.ilike(like)))
    query = query.order_by(Patient.name)
    if format:
        rows = [out(p) for p in db.scalars(query)]
        return export(db, rows, COLUMNS, format, "patients", "patients", "Patients")
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [out(p) for p in items], "total": total, "page": page, "page_size": page_size}


@router.get("/duplicates")
def duplicates(name: str = "", phone: str = "", dob: date | None = None,
               user: User = Depends(require("patients.write")), db: Session = Depends(get_db)):
    return [out(p) for p in find_duplicates(db, name, phone, dob)]


@router.post("", status_code=201)
def create_patient(body: PatientIn, confirm_duplicate: bool = False,
                   user: User = Depends(require("patients.write")), db: Session = Depends(get_db)):
    ensure_scope_value(user, body.clinic_scope)
    dups = find_duplicates(db, body.name, body.phone, body.dob)
    if dups and not confirm_duplicate:
        raise conflict("Possible duplicate patient", "duplicate", candidates=[out(p) for p in dups])
    p = Patient(**body.model_dump())
    db.add(p)
    db.flush()
    p.file_no = f"P-{p.id:06d}"
    db.commit()
    return out(p, 0)


@router.get("/{patient_id}")
def get_one(patient_id: int, user: User = Depends(require("patients.read")), db: Session = Depends(get_db)):
    p = get_patient(db, user, patient_id)
    log_event(db, "view", "patients", p.id)  # AUD-03
    db.commit()
    return out(p, balance_of(db, p.id))


@router.patch("/{patient_id}")
def patch(patient_id: int, body: PatientPatch, user: User = Depends(require("patients.write")),
          db: Session = Depends(get_db)):
    p = get_patient(db, user, patient_id)
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    if "clinic_scope" in data:
        ensure_scope_value(user, data["clinic_scope"])
    for key in ("name", "phone"):
        if key in data and data[key] is None:
            raise http_error(422, f"{key} is required", "validation", field=key)
    check_version(p, version)
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    return out(p, balance_of(db, p.id))


@router.post("/{patient_id}/archive")
def archive(patient_id: int, archived: bool = True, user: User = Depends(require("patients.archive")),
            db: Session = Depends(get_db)):
    p = get_patient(db, user, patient_id)
    p.archived = archived
    db.commit()
    return out(p)


# ---------------------------------------------------------------- documents (PAT-07)
def _file_out(f: PatientFile) -> dict:
    return {"id": f.id, "filename": f.filename, "mime": f.mime, "size": f.size, "created_at": f.created_at.isoformat()}


@router.get("/{patient_id}/files")
def list_files(patient_id: int, user: User = Depends(require("patients.read")), db: Session = Depends(get_db)):
    get_patient(db, user, patient_id)
    files = db.scalars(select(PatientFile).where(PatientFile.patient_id == patient_id).order_by(PatientFile.id.desc()))
    return [_file_out(f) for f in files]


@router.post("/{patient_id}/files", status_code=201)
async def upload_file(patient_id: int, file: UploadFile = File(...),
                      user: User = Depends(require("patients.write")), db: Session = Depends(get_db)):
    get_patient(db, user, patient_id)
    s = get_settings()
    content = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(content) > s.max_upload_mb * 1024 * 1024:
        raise http_error(413, f"File is larger than {s.max_upload_mb} MB", "too_large")
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if mime not in ALLOWED_MIME:
        raise http_error(422, "Only images and PDF files are allowed", "validation", field="file")
    folder = s.upload_dir / "patients" / str(patient_id)
    folder.mkdir(parents=True, exist_ok=True)
    ext = mimetypes.guess_extension(mime) or ""
    path = folder / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(content)
    f = PatientFile(patient_id=patient_id, filename=(file.filename or path.name)[:255], mime=mime,
                    size=len(content), path=str(path))
    db.add(f)
    db.commit()
    return _file_out(f)


@router.get("/{patient_id}/files/{file_id}")
def download_file(patient_id: int, file_id: int, user: User = Depends(require("patients.read")),
                  db: Session = Depends(get_db)):
    get_patient(db, user, patient_id)
    f = db.get(PatientFile, file_id)
    if not f or f.patient_id != patient_id:
        raise not_found("File")
    log_event(db, "view", "patient_files", f.id)
    db.commit()
    return FileResponse(f.path, media_type=f.mime, filename=f.filename, content_disposition_type="inline")


# ---------------------------------------------------------------- dental chart (CHART-01..03)
def _tooth_out(db: Session, e: ToothEntry) -> dict:
    u = db.get(User, e.user_id) if e.user_id else None
    staff = db.get(Staff, u.staff_id) if u and u.staff_id else None
    return {"id": e.id, "tooth": e.tooth, "surface": e.surface, "condition": e.condition, "note": e.note,
            "visit_id": e.visit_id, "at": e.at.isoformat(), "user": staff.name if staff else (u.username if u else None)}


def _dental_patient(p: Patient) -> None:
    if p.clinic_scope not in ("dental", "both"):
        raise http_error(422, "The dental chart is only available for dental patients", "not_dental")


@router.get("/{patient_id}/teeth")
def teeth(patient_id: int, user: User = Depends(require("chart.read")), db: Session = Depends(get_db)):
    p = get_patient(db, user, patient_id)
    _dental_patient(p)
    entries = db.scalars(select(ToothEntry).where(ToothEntry.patient_id == patient_id)
                         .order_by(ToothEntry.at, ToothEntry.id)).all()
    current: dict[int, dict] = {}
    history: dict[int, list] = {}
    for e in entries:
        d = _tooth_out(db, e)
        current[e.tooth] = d
        history.setdefault(e.tooth, []).insert(0, d)
    return {"current": current, "history": history, "conditions": TOOTH_CONDITIONS}


@router.post("/{patient_id}/teeth", status_code=201)
def add_tooth(patient_id: int, body: ToothIn, user: User = Depends(require("chart.write")),
              db: Session = Depends(get_db)):
    p = get_patient(db, user, patient_id)
    _dental_patient(p)
    if body.tooth not in PERMANENT | PRIMARY:
        raise http_error(422, "Invalid FDI tooth number", "validation", field="tooth")
    if body.condition not in TOOTH_CONDITIONS:
        raise http_error(422, "Unknown condition", "validation", field="condition")
    if body.visit_id:
        v = db.get(Visit, body.visit_id)
        if not v or v.patient_id != patient_id:
            raise not_found("Visit")
    e = ToothEntry(patient_id=patient_id, tooth=body.tooth, surface=body.surface, condition=body.condition,
                   note=body.note, visit_id=body.visit_id, user_id=user.id, at=utcnow())
    db.add(e)
    db.commit()
    return _tooth_out(db, e)


__all__ = ["router", "get_patient", "forbidden"]
