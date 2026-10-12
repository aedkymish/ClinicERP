"""User accounts — Admin only (AUTH-02, AUTH-03, AUTH-05, AUTH-06)."""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..audit import log_event
from ..db import get_db
from ..deps import check_version, conflict, http_error, not_found, require
from ..models import Staff, User, UserSession
from ..security import hash_password, one_time_password

router = APIRouter(prefix="/users", tags=["users"])
Role = Literal["admin", "doctor", "nurse", "assistant", "receptionist", "finance"]
Scope = Literal["dental", "derma", "both"]


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    role: Role
    clinic_scope: Scope = "both"
    staff_id: int | None = None


class UserPatch(BaseModel):
    role: Role | None = None
    clinic_scope: Scope | None = None
    staff_id: int | None = None
    active: bool | None = None
    version: int | None = None


def out(u: User) -> dict:
    return {
        "id": u.id, "username": u.username, "role": u.role, "clinic_scope": u.clinic_scope,
        "staff_id": u.staff_id, "staff_name": u.staff.name if u.staff else None,
        "active": u.active, "must_change_pw": u.must_change_pw,
        "locked_until": u.locked_until.isoformat() if u.locked_until else None,
        "version": u.version,
    }


def _active_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True)))


def _revoke_sessions(db: Session, user_id: int) -> None:
    db.execute(update(UserSession).where(UserSession.user_id == user_id).values(revoked=True))


def _check_staff(db: Session, staff_id: int | None, user_id: int | None = None) -> None:
    if staff_id is None:
        return
    if not db.get(Staff, staff_id):
        raise not_found("Staff member")
    other = db.scalar(select(User).where(User.staff_id == staff_id))
    if other and other.id != user_id:
        raise conflict("This staff member already has a login", "duplicate")


@router.get("")
def list_users(_: User = Depends(require("users")), db: Session = Depends(get_db)):
    return [out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("", status_code=201)
def create_user(body: UserIn, _: User = Depends(require("users")), db: Session = Depends(get_db)):
    username = body.username.lower()
    if db.scalar(select(User).where(User.username == username)):
        raise conflict("Username already exists", "duplicate")
    _check_staff(db, body.staff_id)
    otp = one_time_password()
    u = User(username=username, role=body.role, clinic_scope=body.clinic_scope, staff_id=body.staff_id,
             password_hash=hash_password(otp), must_change_pw=True)
    db.add(u)
    db.commit()
    return {**out(u), "one_time_password": otp}


@router.patch("/{user_id}")
def patch_user(user_id: int, body: UserPatch, me: User = Depends(require("users")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise not_found("User")
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    losing_admin = u.role == "admin" and u.active and (
        (data.get("role") not in (None, "admin")) or data.get("active") is False
    )
    if losing_admin and _active_admins(db) <= 1:
        raise conflict("At least one active administrator must remain", "last_admin")
    if "staff_id" in data:
        _check_staff(db, data["staff_id"], u.id)
    check_version(u, version)
    for k, v in data.items():
        setattr(u, k, v)
    if data.get("active") is False or "role" in data:
        _revoke_sessions(db, u.id)
    db.commit()
    return out(u)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, _: User = Depends(require("users")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise not_found("User")
    otp = one_time_password()
    u.password_hash = hash_password(otp)
    u.must_change_pw = True
    u.failed_logins = 0
    u.locked_until = None
    _revoke_sessions(db, u.id)
    log_event(db, "password_reset", "users", u.id)
    db.commit()
    return {**out(u), "one_time_password": otp}


@router.post("/{user_id}/unlock")
def unlock(user_id: int, _: User = Depends(require("users")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise not_found("User")
    if not u.locked_until:
        raise http_error(422, "Account is not locked", "validation")
    u.locked_until = None
    u.failed_logins = 0
    log_event(db, "unlock", "users", u.id)
    db.commit()
    return out(u)
