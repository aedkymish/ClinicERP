from datetime import timedelta

from sqlalchemy import select, text

from app import db as dbmod
from app.models import User, UserSession
from tests.conftest import PASSWORD, Client, app, login, make_user

API = "/api/v1"


def test_login_sets_httponly_cookies_and_me():
    make_user("doctor", username="dr")
    c = Client(app)
    r = c.post(f"{API}/auth/login", json={"username": "dr", "password": PASSWORD})
    assert r.status_code == 200
    cookies = r.headers.get_list("set-cookie")
    access = next(x for x in cookies if x.startswith("access_token="))
    assert "HttpOnly" in access and "SameSite=strict" in access.replace("Strict", "strict")
    assert "HttpOnly" not in next(x for x in cookies if x.startswith("csrf_token="))
    me = c.get(f"{API}/auth/me").json()
    assert me["role"] == "doctor" and "visits.write" in me["permissions"]


def test_password_stored_as_argon2id():
    u = make_user("nurse")
    assert u.password_hash.startswith("$argon2id$")
    assert PASSWORD not in u.password_hash


def test_wrong_password_and_lockout_after_five_failures(admin):
    make_user("receptionist", username="rec")
    c = Client(app)
    for _ in range(5):
        assert c.post(f"{API}/auth/login", json={"username": "rec", "password": "nope-nope"}).status_code == 401
    # 6th attempt refused even with the right password (NFR-01)
    r = c.post(f"{API}/auth/login", json={"username": "rec", "password": PASSWORD})
    assert r.status_code == 423
    uid = next(u["id"] for u in admin.get(f"{API}/users").json() if u["username"] == "rec")
    assert admin.post(f"{API}/users/{uid}/unlock").status_code == 200
    assert c.post(f"{API}/auth/login", json={"username": "rec", "password": PASSWORD}).status_code == 200


def test_failed_logins_are_audited(admin):
    Client(app).post(f"{API}/auth/login", json={"username": "ghost", "password": "whatever1"})
    items = admin.get(f"{API}/audit", params={"action": "login_failed"}).json()["items"]
    assert items


def test_csrf_required_on_state_change():
    make_user("doctor", username="dr")
    c = login("dr")
    r = TestNoCsrf(c).post(f"{API}/patients", json={"name": "X", "phone": "123"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "csrf"


class TestNoCsrf:
    __test__ = False

    def __init__(self, c):
        self.c = c

    def post(self, url, **kw):
        from fastapi.testclient import TestClient

        return TestClient.request(self.c, "POST", url, **kw)


def test_one_time_password_flow(admin):
    staff = admin.post(f"{API}/staff", json={"name": "New Nurse", "role": "nurse"}).json()
    r = admin.post(f"{API}/users", json={"username": "newnurse", "role": "nurse", "staff_id": staff["id"]})
    assert r.status_code == 201
    otp = r.json()["one_time_password"]
    c = login("newnurse", otp)
    # everything except the password change is blocked
    blocked = c.get(f"{API}/patients")
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "password_change_required"
    assert c.post(f"{API}/auth/change-password", json={"current_password": otp, "new_password": "short"}).status_code == 422
    assert c.post(f"{API}/auth/change-password",
                  json={"current_password": otp, "new_password": "A-much-better-pw1"}).status_code == 200
    assert c.get(f"{API}/patients").status_code == 200


def test_only_admin_manages_accounts(as_role):
    fin = as_role("finance")
    target = make_user("nurse", username="n1")
    assert fin.patch(f"{API}/users/{target.id}", json={"role": "admin"}).status_code == 403  # GAP-01
    assert fin.post(f"{API}/users/{target.id}/reset-password").status_code == 403
    assert fin.post(f"{API}/users", json={"username": "x1", "role": "admin"}).status_code == 403


def test_last_admin_cannot_be_removed(admin):
    me = admin.get(f"{API}/auth/me").json()
    r = admin.patch(f"{API}/users/{me['id']}", json={"active": False})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "last_admin"
    r = admin.patch(f"{API}/users/{me['id']}", json={"role": "finance"})
    assert r.status_code == 409


def test_logout_revokes_session():
    make_user("doctor", username="dr")
    c = login("dr")
    access = c.cookies.get("access_token")
    c.post(f"{API}/auth/logout")
    c2 = Client(app)
    c2.cookies.set("access_token", access)
    assert c2.get(f"{API}/auth/me").status_code == 401


def test_idle_timeout_ends_session():
    make_user("doctor", username="dr")
    c = login("dr")
    with dbmod.SessionLocal() as s:
        sess = s.scalars(select(UserSession)).first()
        sess.last_seen = sess.last_seen - timedelta(minutes=31)
        s.commit()
    r = c.get(f"{API}/auth/me")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "session_expired"
    assert c.post(f"{API}/auth/refresh").status_code == 401


def test_refresh_issues_new_access_token():
    make_user("doctor", username="dr")
    c = login("dr")
    c.cookies.delete("access_token")
    assert c.post(f"{API}/auth/refresh").status_code == 200
    assert c.get(f"{API}/auth/me").status_code == 200


def test_deactivated_user_cannot_sign_in(admin):
    u = make_user("assistant", username="asst")
    c = login("asst")
    admin.patch(f"{API}/users/{u.id}", json={"active": False})
    assert c.get(f"{API}/auth/me").status_code == 401
    assert Client(app).post(f"{API}/auth/login", json={"username": "asst", "password": PASSWORD}).status_code == 401


def test_change_own_password_requires_current(as_role):
    c = as_role("receptionist")
    r = c.post(f"{API}/auth/change-password", json={"current_password": "wrong-pass", "new_password": "Another-pass-1"})
    assert r.status_code == 422


def test_no_default_accounts_exist():
    with dbmod.SessionLocal() as s:
        assert s.execute(text("select count(*) from users")).scalar() == 0
        assert not s.scalars(select(User)).all()
