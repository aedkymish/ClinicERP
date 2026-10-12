import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="clinicerp-test-"))
os.environ["CLINIC_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["CLINIC_DATA_DIR"] = str(_TMP)
os.environ["CLINIC_UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["CLINIC_BACKUP_DIR"] = str(_TMP / "backups")
os.environ["CLINIC_COOKIE_SECURE"] = "false"  # TestClient talks plain http
os.environ["CLINIC_SCHEDULER_ENABLED"] = "false"
os.environ["CLINIC_SECRET_KEY"] = "test-secret-key-test-secret-key-0123456789"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.bootstrap import install_guards, seed_reference  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Staff, User  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "Correct-horse-9"
ROLES = ("admin", "doctor", "nurse", "assistant", "receptionist", "finance")


class Client(TestClient):
    """TestClient that echoes the CSRF cookie like the frontend does."""

    def request(self, method, url, **kw):
        token = self.cookies.get("csrf_token")
        if token:
            kw["headers"] = {**(kw.get("headers") or {}), "X-CSRF-Token": token}
        return super().request(method, url, **kw)


@pytest.fixture(autouse=True)
def fresh_db():
    eng = dbmod.engine
    with eng.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    dbmod.Base.metadata.drop_all(eng)
    dbmod.Base.metadata.create_all(eng)
    with eng.begin() as conn:
        install_guards(conn)
    with dbmod.SessionLocal() as s:
        seed_reference(s)
    yield


@pytest.fixture
def db():
    with dbmod.SessionLocal() as s:
        yield s


def make_user(role: str, scope: str = "both", username: str | None = None, salary: int = 0, share: float = 0,
              must_change: bool = False) -> User:
    with dbmod.SessionLocal() as s:
        staff = Staff(name=(username or role).title(), role=role, clinic_scope=scope, salary=salary,
                      default_share_pct=share)
        s.add(staff)
        s.flush()
        u = User(username=username or f"{role}-{scope}", role=role, clinic_scope=scope, staff_id=staff.id,
                 password_hash=hash_password(PASSWORD), must_change_pw=must_change)
        s.add(u)
        s.commit()
        s.refresh(u)
        return u


def login(username: str, password: str = PASSWORD) -> Client:
    c = Client(app)
    r = c.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def as_role():
    """as_role('finance') -> signed-in client (user created on demand)."""
    cache: dict = {}

    def factory(role: str, scope: str = "both", **kw) -> Client:
        key = (role, scope, kw.get("username"))
        if key not in cache:
            u = make_user(role, scope, **kw)
            cache[key] = login(u.username)
            cache[key].user = u
        return cache[key]

    return factory


@pytest.fixture
def admin(as_role):
    return as_role("admin")


# ---------------------------------------------------------------- data helpers
def new_patient(c: Client, name="Test Patient", phone="0790001111", scope="both", **kw) -> dict:
    r = c.post("/api/v1/patients", json={"name": name, "phone": phone, "clinic_scope": scope, **kw},
               params={"confirm_duplicate": True})
    assert r.status_code == 201, r.text
    return r.json()


def new_service(c: Client, clinic="dental", name="Filling", price=10000, share_pct=None, lab_cost=0, **kw) -> dict:
    r = c.post("/api/v1/services", json={"clinic": clinic, "name": name, "price": price, "share_pct": share_pct,
                                         "lab_cost": lab_cost, **kw})
    assert r.status_code == 201, r.text
    return r.json()
