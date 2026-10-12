"""NFR-02: every endpoint is called as every role; denials must be 403.

The expected matrix mirrors SRS section 2.2. A role listed as allowed must NOT get 403 (it may get
404/409/422 because the probe bodies are minimal); every other role MUST get 403.
"""
from datetime import date

import pytest

from app.main import app
from tests.conftest import ROLES, new_patient, new_service

API = "/api/v1"
ALL = set(ROLES)
CLIN = {"admin", "doctor", "nurse", "assistant"}
FRONT = {"admin", "doctor", "nurse", "assistant", "receptionist"}
MONTH = date.today().strftime("%Y-%m")

# (method, path, body, allowed roles)
MATRIX = [
    ("GET", "/patients", None, ALL),
    ("POST", "/patients", {"name": "A", "phone": "0711111111"}, FRONT),
    ("PATCH", "/patients/{pid}", {"notes": "x"}, FRONT),
    ("POST", "/patients/{pid}/archive", None, {"admin"}),
    ("GET", "/patients/{pid}/teeth", None, CLIN),
    ("POST", "/patients/{pid}/teeth", {"tooth": 11, "condition": "Healthy"}, {"admin", "doctor", "nurse"}),
    ("GET", "/appointments", None, FRONT),
    ("POST", "/appointments", {"patient_id": 0, "clinic": "dental", "date": "2030-01-01", "time": "09:00"}, FRONT),
    ("GET", "/visits", None, CLIN),
    ("POST", "/visits", {"patient_id": 0, "clinic": "dental"}, {"admin", "doctor", "nurse"}),
    ("GET", "/services", None, ALL),
    ("POST", "/services", {"clinic": "dental", "name": "S", "price": 1}, {"admin"}),
    ("PATCH", "/services/{sid}", {"price": 1}, {"admin", "finance"}),
    ("PATCH", "/services/{sid}", {"name": "Renamed"}, {"admin"}),
    ("PUT", "/services/{sid}/items", [], {"admin"}),
    ("GET", "/invoices", None, {"admin", "doctor", "receptionist", "finance"}),
    ("POST", "/invoices", {"patient_id": 0, "clinic": "dental"}, {"admin", "receptionist", "finance"}),
    ("POST", "/invoices/0/payments", {"amount": 1}, {"admin", "receptionist", "finance"}),
    ("POST", "/invoices/0/void", {"reason": "xyz"}, {"admin", "finance"}),
    ("POST", "/invoices/0/credit-notes", {"amount": 1, "reason": "xyz"}, {"admin", "finance"}),
    ("POST", "/payments/0/refund", {"reason": "xyz"}, {"admin", "finance"}),
    ("GET", "/inventory", None, {"admin", "doctor", "nurse", "assistant", "finance"}),
    ("POST", "/inventory", {"name": "I"}, {"admin", "nurse", "assistant"}),
    ("POST", "/inventory/0/movements", {"kind": "Receive", "qty": 1}, {"admin", "nurse", "assistant"}),
    ("GET", "/expenses", None, {"admin", "finance"}),
    ("POST", "/expenses", {"date": "2030-01-01", "category": "Rent", "amount": 1}, {"admin", "finance"}),
    ("POST", "/staff", {"name": "S", "role": "nurse"}, {"admin"}),
    ("PATCH", "/staff/{other_staff}", {"salary": 1}, {"admin", "finance"}),
    ("PATCH", "/staff/{other_staff}", {"role": "admin"}, {"admin"}),
    ("GET", "/users", None, {"admin"}),
    ("POST", "/users", {"username": "zz", "role": "nurse"}, {"admin"}),
    ("PATCH", "/users/{other_user}", {"role": "admin"}, {"admin"}),
    ("POST", "/users/{other_user}/reset-password", None, {"admin"}),
    ("POST", "/attendance", {"staff_id": 0, "date": "2030-01-01", "status": "Absent", "note": "abc"}, {"admin", "finance"}),
    ("GET", f"/attendance?month={MONTH}&staff_id={{other_staff}}", None, {"admin", "finance"}),
    ("GET", "/payroll/runs", None, {"admin", "finance"}),
    ("POST", "/payroll/runs", {"month": "2001-01"}, {"admin", "finance"}),
    ("POST", "/payroll/runs/0/approve", None, {"admin"}),
    ("GET", "/reports/summary", None, {"admin", "finance"}),
    ("GET", "/reports/revenue", None, {"admin", "finance"}),
    ("GET", "/reports/aging", None, {"admin", "finance"}),
    ("GET", "/reports/expenses", None, {"admin", "finance"}),
    ("GET", "/reports/commission", None, {"admin", "finance", "doctor"}),
    ("GET", "/reports/cash", None, {"admin", "finance", "receptionist"}),
    ("GET", "/audit", None, {"admin", "finance"}),
    ("GET", "/settings", None, {"admin"}),
    ("PUT", "/settings", {"currency": "JOD"}, {"admin"}),
    ("POST", "/admin/backup", None, {"admin"}),
    ("GET", "/auth/me", None, ALL),
    ("GET", "/dashboard", None, ALL),
    ("GET", "/payroll/my", None, ALL),
]


@pytest.fixture
def ids(admin):
    p = new_patient(admin, scope="dental")
    s = new_service(admin)
    other = admin.post(f"{API}/staff", json={"name": "Other", "role": "nurse"}).json()
    u = admin.post(f"{API}/users", json={"username": "other", "role": "nurse", "staff_id": other["id"]}).json()
    return {"pid": p["id"], "sid": s["id"], "other_staff": other["id"], "other_user": u["id"]}


@pytest.mark.parametrize("role", ROLES)
def test_permission_matrix(role, as_role, ids):
    c = as_role(role)
    failures = []
    for method, path, body, allowed in MATRIX:
        url = API + path.format(**ids)
        r = c.request(method, url, json=body)
        denied = r.status_code == 403
        if role in allowed and denied:
            failures.append(f"{method} {path}: expected allowed, got 403 {r.text[:120]}")
        if role not in allowed and not denied:
            failures.append(f"{method} {path}: expected 403, got {r.status_code}")
    assert not failures, "\n".join(failures)


def test_every_route_requires_sign_in():
    import re

    from fastapi.testclient import TestClient

    anon = TestClient(app)
    open_paths = {"/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout", "/api/v1/health"}
    checked = 0
    for path, ops in app.openapi()["paths"].items():
        if path in open_paths:
            continue
        url = re.sub(r"\{name\}", "summary", path)
        url = re.sub(r"\{[^}]+\}", "1", url)
        for method in ops:
            r = anon.request(method.upper(), url)
            assert r.status_code in (401, 422), f"{method} {path} -> {r.status_code}"
            checked += 1
    assert checked > 60


# ---------------------------------------------------------------- clinic scope (SCOPE-02)
def test_single_clinic_staff_see_only_their_clinic(as_role, admin):
    dental_svc = new_service(admin, clinic="dental", name="D")
    derma_svc = new_service(admin, clinic="derma", name="M")
    dp = new_patient(admin, name="Dental P", phone="0711000001", scope="dental")
    mp = new_patient(admin, name="Derma P", phone="0711000002", scope="derma")
    rec = as_role("receptionist", scope="dental")
    assert [s["name"] for s in rec.get(f"{API}/services").json()] == ["D"]
    assert {p["name"] for p in rec.get(f"{API}/patients").json()["items"]} == {"Dental P"}
    assert rec.get(f"{API}/patients/{mp['id']}").status_code == 403
    r = rec.post(f"{API}/appointments", json={"patient_id": dp["id"], "service_id": derma_svc["id"],
                                              "date": "2030-01-01", "time": "09:00"})
    assert r.status_code == 403
    r = rec.post(f"{API}/invoices", json={"patient_id": dp["id"], "clinic": "derma"})
    assert r.status_code == 403
    inv = admin.post(f"{API}/invoices", json={"patient_id": mp["id"], "clinic": "derma",
                                               "lines": [{"service_id": derma_svc["id"], "qty": 1}]}).json()
    assert rec.get(f"{API}/invoices/{inv['id']}").status_code == 403
    assert rec.get(f"{API}/invoices").json()["total"] == 0
    # admin (both) can switch the view (SCOPE-03)
    assert [s["name"] for s in admin.get(f"{API}/services", params={"clinic": "derma"}).json()] == ["M"]
    assert len(admin.get(f"{API}/services").json()) == 2
    assert dental_svc


def test_finance_staff_edit_limited_to_salary(as_role, admin):
    fin = as_role("finance")
    st = admin.post(f"{API}/staff", json={"name": "Dr X", "role": "doctor"}).json()
    r = fin.patch(f"{API}/staff/{st['id']}", json={"salary": 150000, "default_share_pct": 35})
    assert r.status_code == 200 and r.json()["salary"] == 150000
    assert fin.patch(f"{API}/staff/{st['id']}", json={"name": "Hacked"}).status_code == 403


def test_staff_see_own_profile_only(as_role, admin):
    nurse = as_role("nurse")
    admin.post(f"{API}/staff", json={"name": "Someone", "role": "doctor"})
    rows = nurse.get(f"{API}/staff").json()
    assert len(rows) == 1 and rows[0]["id"] == nurse.user.staff_id
    assert nurse.patch(f"{API}/staff/{nurse.user.staff_id}", json={"phone": "0700"}).status_code == 200
    assert nurse.patch(f"{API}/staff/{nurse.user.staff_id}", json={"salary": 1}).status_code == 403
