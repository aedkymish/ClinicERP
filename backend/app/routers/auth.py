"""Sign-in, refresh, sign-out, password change — AUTH-01..07."""
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import _client_ip, check_csrf, get_current_user, http_error, settings_map
from ..models import Clinic, User, UserSession
from ..permissions import permissions_for
from ..security import decode_token, hash_password, make_token, password_problem, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


def _set_cookies(response: Response, user: User, sess: UserSession) -> None:
    s = get_settings()
    common = {"httponly": True, "secure": s.cookie_secure, "samesite": "strict"}
    response.set_cookie("access_token", make_token(user.id, sess.id, "access"),
                        max_age=s.access_minutes * 60, path="/", **common)
    response.set_cookie("refresh_token", make_token(user.id, sess.id, "refresh"),
                        max_age=s.refresh_hours * 3600, path="/api/v1/auth", **common)
    # readable by the frontend so it can echo it in X-CSRF-Token (double-submit)
    response.set_cookie("csrf_token", secrets.token_urlsafe(24), max_age=s.refresh_hours * 3600, path="/",
                        httponly=False, secure=s.cookie_secure, samesite="strict")


def _clear_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    response.delete_cookie("csrf_token", path="/")


def me_payload(db: Session, user: User) -> dict:
    staff = user.staff
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "clinic_scope": user.clinic_scope,
        "staff_id": user.staff_id,
        "name": staff.name if staff else user.username,
        "must_change_pw": user.must_change_pw,
        "language": user.language,
        "permissions": permissions_for(user.role),
        "settings": public_settings(db),
    }


def public_settings(db: Session) -> dict:
    st = settings_map(db)
    clinics = {c.code: {"id": c.id, "name": c.name, "prefix": c.invoice_prefix} for c in db.scalars(select(Clinic))}
    return {
        "currency": st["currency"],
        "currency_decimals": int(st["currency_decimals"] or 2),
        "vat_enabled": st["vat_enabled"] == "true",
        "vat_rate": float(st["vat_rate"] or 0),
        "time_zone": st["time_zone"],
        "rooms": [r.strip() for r in st["rooms"].split(",") if r.strip()],
        "expense_categories": [c.strip() for c in st["expense_categories"].split(",") if c.strip()],
        "has_logo": bool(st["logo_path"]),
        "default_language": st["default_language"],
        "clinics": clinics,
    }


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    db.info["ip"] = _client_ip(request)
    now = utcnow()
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if user is None:
        log_event(db, "login_failed", "users", None, after={"username": body.username})
        db.commit()
        raise http_error(401, "Wrong username or password", "bad_credentials")
    db.info["user_id"] = user.id
    if user.locked_until and user.locked_until > now:
        log_event(db, "login_failed", "users", user.id, after={"reason": "locked"}, user_id=user.id)
        db.commit()
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise http_error(423, f"Account locked. Try again in {minutes} minutes or ask an administrator.", "locked")
    if not user.active or not verify_password(body.password, user.password_hash):
        window = timedelta(minutes=s.lockout_minutes)
        if not user.last_failed_at or now - user.last_failed_at > window:
            user.failed_logins = 0
        user.failed_logins += 1
        user.last_failed_at = now
        if user.failed_logins >= s.lockout_attempts:
            user.locked_until = now + window
            user.failed_logins = 0
        log_event(db, "login_failed", "users", user.id, user_id=user.id)
        db.commit()
        raise http_error(401, "Wrong username or password", "bad_credentials")
    user.failed_logins = 0
    user.last_failed_at = None
    user.locked_until = None
    sess = UserSession(user_id=user.id, expires_at=now + timedelta(hours=s.refresh_hours), ip=db.info["ip"])
    db.add(sess)
    db.flush()
    log_event(db, "login", "users", user.id, user_id=user.id)
    db.commit()
    _set_cookies(response, user, sess)
    return me_payload(db, user)


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("refresh_token")
    data = decode_token(token, "refresh") if token else None
    if not data:
        raise http_error(401, "Not signed in", "unauthenticated")
    check_csrf(request)
    sess = db.get(UserSession, data["sid"])
    now = utcnow()
    idle = timedelta(minutes=get_settings().idle_minutes)
    if not sess or sess.revoked or sess.expires_at < now or now - sess.last_seen > idle:
        _clear_cookies(response)
        raise http_error(401, "Session expired", "session_expired")
    user = db.get(User, sess.user_id)
    if not user or not user.active:
        raise http_error(401, "Account disabled", "unauthenticated")
    s = get_settings()
    response.set_cookie("access_token", make_token(user.id, sess.id, "access"), max_age=s.access_minutes * 60,
                        path="/", httponly=True, secure=s.cookie_secure, samesite="strict")
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    for name, kind in (("access_token", "access"), ("refresh_token", "refresh")):
        tok = request.cookies.get(name)
        data = decode_token(tok, kind) if tok else None
        if data:
            sess = db.get(UserSession, data["sid"])
            if sess and not sess.revoked:
                sess.revoked = True
                log_event(db, "logout", "users", sess.user_id, user_id=sess.user_id)
            break
    db.commit()
    _clear_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return me_payload(db, user)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise http_error(422, "Current password is wrong", "validation", field="current_password")
    problem = password_problem(body.new_password)
    if problem:
        raise http_error(422, problem, "validation", field="new_password")
    if body.new_password == body.current_password:
        raise http_error(422, "Choose a password different from the current one", "validation", field="new_password")
    user.password_hash = hash_password(body.new_password)
    user.must_change_pw = False
    log_event(db, "password_change", "users", user.id)
    db.commit()
    return me_payload(db, user)


class LanguageIn(BaseModel):
    language: str


@router.post("/language")
def set_language(body: LanguageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.language not in ("en", "ar"):
        raise http_error(422, "Language must be en or ar", "validation")
    user.language = body.language
    db.commit()
    return {"language": user.language}
