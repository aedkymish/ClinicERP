"""Staff records — STAFF-01..03."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import check_version, ensure_scope_value, forbidden, get_current_user, not_found, require, scope_values
from ..models import Staff, User
from ..permissions import can
from ..services.export import export

router = APIRouter(prefix="/staff", tags=["staff"])
StaffRole = Literal["admin", "doctor", "nurse", "assistant", "receptionist", "finance"]
Scope = Literal["dental", "derma", "both"]
SALARY_FIELDS = {"salary", "default_share_pct"}
SELF_FIELDS = {"phone", "email"}


class StaffIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: StaffRole
    clinic_scope: Scope = "both"
    specialty: str | None = None
    phone: str | None = None
    email: str | None = None
    hire_date: date | None = None
    salary: int = Field(0, ge=0)
    default_share_pct: float = Field(0, ge=0, le=100)


class StaffPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: StaffRole | None = None
    clinic_scope: Scope | None = None
    specialty: str | None = None
    phone: str | None = None
    email: str | None = None
    hire_date: date | None = None
    salary: int | None = Field(default=None, ge=0)
    default_share_pct: float | None = Field(default=None, ge=0, le=100)
    active: bool | None = None
    version: int | None = None


def out(s: Staff, with_pay: bool, db: Session | None = None) -> dict:
    d = {"id": s.id, "name": s.name, "role": s.role, "clinic_scope": s.clinic_scope, "specialty": s.specialty,
         "phone": s.phone, "email": s.email, "hire_date": s.hire_date.isoformat() if s.hire_date else None,
         "active": s.active, "version": s.version}
    if with_pay:
        d["salary"] = s.salary
        d["default_share_pct"] = s.default_share_pct
    if db is not None:
        u = db.scalar(select(User).where(User.staff_id == s.id))
        d["username"] = u.username if u else None
    return d


COLUMNS = [("name", "Name"), ("role", "Role"), ("clinic_scope", "Clinic"), ("specialty", "Specialty"),
           ("phone", "Phone"), ("email", "Email"), ("hire_date", "Hire date"), ("salary", "Salary"),
           ("default_share_pct", "Default share %"), ("active", "Active")]


@router.get("")
def list_staff(clinic: str | None = None, active: bool | None = None, format: str | None = None,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not can(user.role, "staff.read_all"):
        own = db.get(Staff, user.staff_id) if user.staff_id else None
        return [out(own, True, db)] if own else []
    q = select(Staff).where(Staff.clinic_scope.in_(scope_values(user, clinic)))
    if active is not None:
        q = q.where(Staff.active.is_(active))
    rows = [out(s, True, db) for s in db.scalars(q.order_by(Staff.name))]
    if format:
        return export(db, rows, COLUMNS, format, "staff", "staff", "Staff")
    return rows


@router.get("/{staff_id}")
def get_staff(staff_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(Staff, staff_id)
    if not s:
        raise not_found("Staff member")
    if staff_id != user.staff_id and not can(user.role, "staff.read_all"):
        raise forbidden()
    return out(s, True, db)


@router.post("", status_code=201)
def create_staff(body: StaffIn, user: User = Depends(require("staff.write")), db: Session = Depends(get_db)):
    ensure_scope_value(user, body.clinic_scope)
    s = Staff(**body.model_dump())
    db.add(s)
    db.commit()
    return out(s, True, db)


@router.patch("/{staff_id}")
def patch_staff(staff_id: int, body: StaffPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(Staff, staff_id)
    if not s:
        raise not_found("Staff member")
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    fields = set(data)
    if can(user.role, "staff.write"):
        pass
    elif can(user.role, "staff.salary"):
        if fields - SALARY_FIELDS:
            raise forbidden("Finance may only edit salary fields")  # GAP-01
    elif staff_id == user.staff_id:
        if fields - SELF_FIELDS:
            raise forbidden("You can only change your phone and email")
    else:
        raise forbidden()
    if "clinic_scope" in data and data["clinic_scope"]:
        ensure_scope_value(user, data["clinic_scope"])
    check_version(s, version)
    for k, v in data.items():
        if k in ("name", "role", "clinic_scope", "salary", "default_share_pct", "active") and v is None:
            continue
        setattr(s, k, v)  # STAFF-03: deactivate, never delete
    db.commit()
    return out(s, True, db)
