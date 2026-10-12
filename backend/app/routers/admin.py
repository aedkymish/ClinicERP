"""Settings, logo, backup/restore and v1 import — SCOPE-04, SET-01..04."""
import json
import mimetypes
from typing import Literal
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import get_current_user, http_error, not_found, require, settings_map
from ..models import Clinic, Setting, Staff, User
from ..routers.auth import public_settings
from ..services import backup as B
from ..services.import_v1 import run_import

router = APIRouter(tags=["admin"])


class ClinicNames(BaseModel):
    dental: str | None = Field(default=None, min_length=1, max_length=120)
    derma: str | None = Field(default=None, min_length=1, max_length=120)
    dental_prefix: str | None = Field(default=None, pattern=r"^[A-Z]{1,5}$")
    derma_prefix: str | None = Field(default=None, pattern=r"^[A-Z]{1,5}$")


class SettingsIn(BaseModel):
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    currency_decimals: int | None = Field(default=None, ge=0, le=3)
    vat_enabled: bool | None = None
    vat_rate: float | None = Field(default=None, ge=0, le=100)
    time_zone: str | None = None
    shift_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    grace_min: int | None = Field(default=None, ge=0, le=240)
    work_days: int | None = Field(default=None, ge=1, le=31)
    rooms: list[str] | None = None
    expense_categories: list[str] | None = None
    default_language: Literal["en", "ar"] | None = None
    clinics: ClinicNames | None = None

    @field_validator("time_zone")
    @classmethod
    def _tz(cls, v):
        if v is not None and v not in available_timezones():
            raise ValueError("Unknown time zone")
        return v


def _all(db: Session) -> dict:
    st = settings_map(db)
    pub = public_settings(db)
    return {**pub, "shift_start": st["shift_start"], "grace_min": int(st["grace_min"] or 0),
            "work_days": int(st["work_days"] or 26), "backups": B.list_backups() if _is_sqlite() else [],
            "encryption": bool(get_settings().backup_encryption_key),
            "offsite": str(get_settings().offsite_backup_dir or "")}


def _is_sqlite() -> bool:
    return get_settings().database_url.startswith("sqlite")


@router.get("/settings")
def get_settings_endpoint(user: User = Depends(require("settings")), db: Session = Depends(get_db)):
    return _all(db)


@router.get("/settings/public")
def get_public(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return public_settings(db)


@router.put("/settings")
def put_settings(body: SettingsIn, user: User = Depends(require("settings")), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    clinics = data.pop("clinics", None)
    for k, v in data.items():
        if v is None:
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, list):
            v = ",".join(x.strip().replace(",", " ") for x in v if x.strip())
        row = db.scalar(select(Setting).where(Setting.key == k)) or Setting(key=k)
        row.value = str(v)
        db.add(row)
    if clinics:
        for code in ("dental", "derma"):
            c = db.scalar(select(Clinic).where(Clinic.code == code))
            if clinics.get(code):
                c.name = clinics[code]
            if clinics.get(f"{code}_prefix"):
                c.invoice_prefix = clinics[f"{code}_prefix"]
        prefixes = [c.invoice_prefix for c in db.scalars(select(Clinic))]
        if len(set(prefixes)) != len(prefixes):
            raise http_error(422, "The two clinics need different invoice prefixes", "validation")
    db.commit()
    return _all(db)


@router.post("/settings/logo")
async def upload_logo(file: UploadFile = File(...), user: User = Depends(require("settings")),
                      db: Session = Depends(get_db)):
    content = await file.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise http_error(413, "Logo must be 2 MB or smaller", "too_large")
    mime = file.content_type or ""
    if mime not in ("image/png", "image/jpeg"):
        raise http_error(422, "Logo must be PNG or JPEG", "validation")
    path = get_settings().data_dir / f"logo{mimetypes.guess_extension(mime) or '.png'}"
    path.write_bytes(content)
    row = db.scalar(select(Setting).where(Setting.key == "logo_path")) or Setting(key="logo_path")
    row.value = str(path)
    db.add(row)
    db.commit()
    return {"ok": True}


@router.get("/settings/logo")
def get_logo(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    path = settings_map(db).get("logo_path")
    if not path:
        raise not_found("Logo")
    return FileResponse(path)


@router.get("/lookups")
def lookups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Small reference lists every signed-in user needs for forms (doctors, staff names)."""
    staff = db.scalars(select(Staff).where(Staff.active.is_(True)).order_by(Staff.name))
    rows = [{"id": s.id, "name": s.name, "role": s.role, "clinic_scope": s.clinic_scope} for s in staff]
    return {"doctors": [r for r in rows if r["role"] == "doctor"], "staff": rows,
            "time_zones": sorted(available_timezones()) if user.role == "admin" else []}


# ---------------------------------------------------------------- backup / restore (SET-01, SET-02)
@router.post("/admin/backup")
def backup_now(user: User = Depends(require("settings")), db: Session = Depends(get_db)):
    try:
        path = B.make_backup("manual")
    except B.BackupError as e:
        raise http_error(422, str(e), "backup") from e
    log_event(db, "backup", "settings", None, after={"file": path.name})
    db.commit()
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/admin/backups/{name}")
def download_backup(name: str, user: User = Depends(require("settings")), db: Session = Depends(get_db)):
    path = get_settings().backup_dir / name
    if "/" in name or ".." in name or not path.exists():
        raise not_found("Backup")
    log_event(db, "export", "settings", None, after={"backup": name})
    db.commit()
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post("/admin/restore")
async def restore(file: UploadFile = File(...), confirm: str = Form(...), user: User = Depends(require("settings"))):
    if confirm != "RESTORE":
        raise http_error(422, 'Type RESTORE to confirm', "validation", field="confirm")
    content = await file.read()
    try:
        safety = B.restore(content)
    except B.BackupError as e:
        raise http_error(422, str(e), "backup") from e
    # the old session points at the replaced file — log into the restored database
    with SessionLocal() as db:
        log_event(db, "restore", "settings", None, after={"file": file.filename, "safety_copy": safety.name},
                  user_id=user.id)
        db.commit()
    return {"ok": True, "safety_copy": safety.name}


@router.post("/admin/import-v1")
async def import_v1(file: UploadFile = File(...), dry_run: bool = Form(True), user: User = Depends(require("settings")),
                    db: Session = Depends(get_db)):
    try:
        payload = json.loads((await file.read()).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise http_error(422, f"Not a valid JSON file: {e}", "validation") from e
    if not isinstance(payload, dict):
        raise http_error(422, "Unexpected backup format", "validation")
    try:
        rep = run_import(db, payload, dry_run, user.id)
    except Exception as e:
        db.rollback()
        raise http_error(422, f"Import failed, nothing was saved: {e}", "import") from e
    return {"dry_run": dry_run, "counts": rep.counts, "warnings": rep.warnings, "filled_lines": rep.filled_lines}


__all__ = ["router", "ZoneInfo"]
