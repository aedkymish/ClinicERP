"""Request dependencies: authentication, CSRF, RBAC, clinic scope, settings, helpers."""
import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db, utcnow
from .models import CLINIC_IDS, Setting, User, UserSession
from .permissions import can
from .security import decode_token

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# reachable while the user still has to replace a one-time password
PW_CHANGE_ALLOWED = {"/api/v1/auth/change-password", "/api/v1/auth/me", "/api/v1/auth/logout"}

DEFAULT_SETTINGS: dict[str, str] = {
    "currency": "USD",
    "currency_decimals": "2",
    "vat_enabled": "false",
    "vat_rate": "0",
    "time_zone": "UTC",
    "shift_start": "09:00",
    "grace_min": "10",
    "work_days": "26",
    "rooms": "Room 1,Room 2,Room 3",
    "expense_categories": "Rent,Utilities,Salaries,Supplies,Lab,Maintenance,Marketing,Other",
    "default_language": "en",
    "logo_path": "",
}


# ---------------------------------------------------------------- errors
def http_error(status: int, message: str, code: str | None = None, **extra: Any) -> HTTPException:
    detail: dict[str, Any] = {"message": message}
    if code:
        detail["code"] = code
    detail.update(extra)
    return HTTPException(status_code=status, detail=detail)


def not_found(what: str = "Record") -> HTTPException:
    return http_error(404, f"{what} not found", "not_found")


def forbidden(message: str = "You do not have permission for this action") -> HTTPException:
    return http_error(403, message, "forbidden")


def conflict(message: str, code: str = "conflict", **extra: Any) -> HTTPException:
    return http_error(409, message, code, **extra)


def check_version(obj: Any, version: int | None) -> None:
    """NFR-09 optimistic locking: reject a save based on a stale copy."""
    if version is not None and obj.version != version:
        raise conflict(
            "This record was changed by someone else. Reload it and apply your changes again.", "stale"
        )
    obj.version = obj.version + 1


# ---------------------------------------------------------------- settings
def settings_map(db: Session) -> dict[str, str]:
    values = dict(DEFAULT_SETTINGS)
    values.update({s.key: s.value or "" for s in db.scalars(select(Setting))})
    return values


def clinic_tz(db: Session) -> ZoneInfo:
    try:
        return ZoneInfo(settings_map(db)["time_zone"])
    except Exception:
        return ZoneInfo("UTC")


# ---------------------------------------------------------------- auth
def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def check_csrf(request: Request) -> None:
    """Double-submit token: state-changing requests must echo the csrf cookie in X-CSRF-Token."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get("csrf_token")
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise http_error(403, "Missing or invalid CSRF token", "csrf")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    db.info["ip"] = _client_ip(request)
    token = request.cookies.get("access_token")
    data = decode_token(token, "access") if token else None
    if not data:
        raise http_error(401, "Not signed in", "unauthenticated")
    sess = db.get(UserSession, data["sid"])
    now = utcnow()
    idle = timedelta(minutes=get_settings().idle_minutes)
    if not sess or sess.revoked or sess.expires_at < now or now - sess.last_seen > idle:
        raise http_error(401, "Session expired", "session_expired")
    user = db.get(User, int(data["sub"]))
    if not user or not user.active or sess.user_id != user.id:
        raise http_error(401, "Account disabled", "unauthenticated")
    check_csrf(request)
    if user.must_change_pw and request.url.path not in PW_CHANGE_ALLOWED:
        raise http_error(403, "You must change your password first", "password_change_required")
    # Background polling (X-Background: 1) must not keep an idle session alive.
    if request.headers.get("x-background") != "1" and now - sess.last_seen > timedelta(seconds=30):
        sess.last_seen = now
        db.commit()
    db.info["user_id"] = user.id  # acting user for created_by and the audit log
    return user


def require(*perms: str) -> Callable[..., User]:
    """Dependency: signed-in user holding at least one of ``perms``."""

    def dep(user: User = Depends(get_current_user)) -> User:
        if not any(can(user.role, p) for p in perms):
            raise forbidden()
        return user

    return dep


# ---------------------------------------------------------------- clinic scope (SCOPE-02/03)
def allowed_clinics(user: User) -> set[int]:
    if user.clinic_scope == "both":
        return set(CLINIC_IDS.values())
    return {CLINIC_IDS[user.clinic_scope]}


def view_clinics(user: User, clinic: str | None) -> set[int]:
    """Clinics in view: the user's scope narrowed by the clinic switcher (both|dental|derma)."""
    allowed = allowed_clinics(user)
    if clinic and clinic in CLINIC_IDS:
        return allowed & {CLINIC_IDS[clinic]}
    return allowed


def clinic_filter(col: Any, user: User, clinic: str | None = None, shared: bool = False) -> ColumnElement:
    ids = view_clinics(user, clinic)
    cond = col.in_(ids)
    return or_(cond, col.is_(None)) if shared else cond


def scope_values(user: User, clinic: str | None = None) -> list[str]:
    """Values of a ``clinic_scope`` column visible to the user (patients, staff)."""
    ids = view_clinics(user, clinic)
    codes = [code for code, cid in CLINIC_IDS.items() if cid in ids]
    return codes + ["both"]


def ensure_clinic(user: User, clinic_id: int | None, shared_ok: bool = False) -> None:
    if clinic_id is None:
        if shared_ok:
            return
        raise http_error(422, "Clinic is required", "validation")
    if clinic_id not in allowed_clinics(user):
        raise forbidden("This record belongs to another clinic")


def ensure_scope_value(user: User, scope: str) -> None:
    if user.clinic_scope != "both" and scope not in (user.clinic_scope, "both"):
        raise forbidden("This record belongs to another clinic")
