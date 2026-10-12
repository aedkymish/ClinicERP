"""Inventory, expenses, attendance, reports, audit, settings, backup/restore and v1 import."""
import io
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app import db as dbmod
from app.db import utcnow
from app.models import Attendance, Invoice
from tests.conftest import new_patient, new_service

API = "/api/v1"


# ---------------------------------------------------------------- inventory (STOCK)
def test_stock_movements_rules(as_role):
    nurse = as_role("nurse")
    item = nurse.post(f"{API}/inventory", json={"name": "Gauze", "opening_qty": 5, "reorder_level": 2,
                                                "expiry": (date.today() + timedelta(days=10)).isoformat()}).json()
    assert item["qty"] == 5 and item["expiring"] and not item["low"]
    r = nurse.post(f"{API}/inventory/{item['id']}/movements", json={"kind": "Use", "qty": 6})
    assert r.status_code == 409
    assert nurse.post(f"{API}/inventory/{item['id']}/movements", json={"kind": "Use", "qty": 3}).json()["low"]
    assert nurse.post(f"{API}/inventory/{item['id']}/movements", json={"kind": "Adjust", "qty": -1}).status_code == 422
    r = nurse.post(f"{API}/inventory/{item['id']}/movements", json={"kind": "Adjust", "qty": -1, "reason": "Damaged"})
    assert r.json()["qty"] == 1
    # quantity is not a writable field
    nurse.patch(f"{API}/inventory/{item['id']}", json={"qty": 999, "name": "Gauze 10cm"})
    assert nurse.get(f"{API}/inventory").json()[0]["qty"] == 1
    moves = nurse.get(f"{API}/inventory/{item['id']}/movements").json()
    assert [m["kind"] for m in moves] == ["Adjust", "Use", "Receive"] and all(m["user"] for m in moves)
    assert len(nurse.get(f"{API}/inventory", params={"flag": "low"}).json()) == 1


# ---------------------------------------------------------------- expenses (EXP-02)
def test_expense_total_follows_filters(as_role):
    fin = as_role("finance")
    today = date.today()
    for d, cat, amt in ((today, "Rent", 1000), (today, "Supplies", 300), (today - timedelta(days=40), "Rent", 5000)):
        assert fin.post(f"{API}/expenses", json={"date": d.isoformat(), "category": cat, "amount": amt}).status_code == 201
    r = fin.get(f"{API}/expenses", params={"from": (today - timedelta(days=7)).isoformat()}).json()
    assert r["total_amount"] == 1300 and r["total"] == 2
    r = fin.get(f"{API}/expenses", params={"category": "Rent"}).json()
    assert r["total_amount"] == 6000
    e = r["items"][0]
    up = fin.post(f"{API}/expenses/{e['id']}/receipt", files={"file": ("r.pdf", b"%PDF-1.4", "application/pdf")})
    assert up.json()["has_receipt"]


# ---------------------------------------------------------------- attendance (ATT)
def test_clock_in_out_and_late(as_role, admin, monkeypatch):
    nurse = as_role("nurse")
    admin.put(f"{API}/settings", json={"shift_start": "00:00", "grace_min": 0})
    r = nurse.post(f"{API}/attendance/clock-in")
    assert r.status_code == 200 and r.json()["status"] == "Late"
    assert nurse.post(f"{API}/attendance/clock-in").status_code == 409
    assert nurse.post(f"{API}/attendance/clock-out").status_code == 200
    assert nurse.post(f"{API}/attendance/clock-out").status_code == 409
    sheet = nurse.get(f"{API}/attendance", params={"month": date.today().strftime("%Y-%m")}).json()
    assert len(sheet["rows"]) == 1
    # corrections need a reason and record who made them
    rec_id = sheet["rows"][0]["id"]
    fin = as_role("finance")
    assert fin.patch(f"{API}/attendance/{rec_id}", json={"status": "Present"}).status_code == 422
    r = fin.patch(f"{API}/attendance/{rec_id}", json={"status": "Present", "note": "traffic accident, approved"})
    assert r.json()["status"] == "Present" and r.json()["corrected_by"]
    assert nurse.patch(f"{API}/attendance/{rec_id}", json={"status": "Present", "note": "self"}).status_code == 403
    csv = fin.get(f"{API}/attendance", params={"month": date.today().strftime("%Y-%m"), "format": "csv"})
    assert csv.status_code == 200 and b"Present" in csv.content


def test_on_time_clock_in(as_role, admin):
    admin.put(f"{API}/settings", json={"shift_start": "23:59", "grace_min": 0})
    with dbmod.SessionLocal() as s:  # make sure no previous row for today
        s.query(Attendance).delete()
        s.commit()
    nurse = as_role("nurse")
    r = nurse.post(f"{API}/attendance/clock-in").json()
    assert r["status"] in ("Present", "Late")  # "Late" only if the test runs in the last minute of the day


# ---------------------------------------------------------------- reports
def test_aging_buckets_and_cash_report(as_role, admin):
    rec = as_role("receptionist")
    svc = new_service(admin, price=1000)
    p = new_patient(admin)
    old = admin.post(f"{API}/invoices", json={"patient_id": p["id"], "clinic": "dental",
                                               "date": (date.today() - timedelta(days=45)).isoformat(),
                                               "lines": [{"service_id": svc["id"], "qty": 1}]}).json()
    admin.post(f"{API}/invoices/{old['id']}/post")
    new = rec.post(f"{API}/invoices", json={"patient_id": p["id"], "clinic": "dental",
                                             "lines": [{"service_id": svc["id"], "qty": 2}]}).json()
    rec.post(f"{API}/invoices/{new['id']}/payments", json={"amount": 500, "method": "Cash"})
    aging = admin.get(f"{API}/reports/aging").json()
    assert aging["buckets"] == {"0-30": 1500, "31-60": 1000, "61-90": 0, "90+": 0}
    cash = rec.get(f"{API}/reports/cash").json()
    assert cash["net"] == 500 and cash["totals"][0]["method"] == "Cash"
    for fmt in ("csv", "xlsx", "pdf"):
        for name in ("summary", "revenue", "commission", "cash", "aging", "expenses"):
            r = admin.get(f"{API}/reports/{name}", params={"format": fmt})
            assert r.status_code == 200, (name, fmt, r.text[:200])
    rev = admin.get(f"{API}/reports/revenue").json()
    assert rev["by_method"] == [{"method": "Cash", "amount": 500}]
    assert rev["by_service"][0]["amount"] == 500


def test_dashboard_by_role(as_role, admin):
    fin = as_role("finance")
    d = fin.get(f"{API}/dashboard").json()
    assert "finance" in d and len(d["finance"]["chart"]) == 6
    rec = as_role("receptionist")
    d = rec.get(f"{API}/dashboard").json()
    assert "finance" not in d and "cash_today" in d and "low_stock" not in d
    doc = as_role("doctor")
    d = doc.get(f"{API}/dashboard").json()
    assert "mtd_commission" in d and "follow_ups" in d


# ---------------------------------------------------------------- audit (AUD)
def test_audit_records_before_and_after(admin):
    p = new_patient(admin, name="Before")
    admin.patch(f"{API}/patients/{p['id']}", json={"name": "After"})
    items = admin.get(f"{API}/audit", params={"entity": "patients", "action": "update"}).json()["items"]
    assert items[0]["before"]["name"] == "Before" and items[0]["after"]["name"] == "After"
    assert items[0]["user"] == "admin-both"
    created = admin.get(f"{API}/audit", params={"entity": "patients", "action": "create"}).json()["items"]
    assert created[0]["after"]["name"] == "Before"


def test_audit_append_only_and_finance_filter(as_role, admin):
    new_patient(admin)
    fin = as_role("finance")
    fin.post(f"{API}/expenses", json={"date": date.today().isoformat(), "category": "Rent", "amount": 10})
    ents = {i["entity"] for i in fin.get(f"{API}/audit", params={"page_size": 200}).json()["items"]}
    assert "expenses" in ents and "patients" not in ents
    with dbmod.SessionLocal() as s, pytest.raises(Exception):
        s.execute(text("update audit_log set action='x'"))
        s.commit()
    with dbmod.SessionLocal() as s, pytest.raises(Exception):
        s.execute(text("delete from audit_log"))
        s.commit()
    from app.main import app

    audit_ops = {m for path, ops in app.openapi()["paths"].items() if path.startswith(f"{API}/audit") for m in ops}
    assert audit_ops == {"get"}


def test_exports_are_audited(admin):
    admin.get(f"{API}/patients", params={"format": "csv"})
    assert admin.get(f"{API}/audit", params={"action": "export"}).json()["total"] == 1


def test_password_hash_never_in_audit(admin):
    admin.post(f"{API}/users", json={"username": "someone", "role": "nurse"})
    rows = admin.get(f"{API}/audit", params={"entity": "users", "page_size": 200}).json()["items"]
    assert rows and all("$argon2" not in json.dumps(r) for r in rows)


# ---------------------------------------------------------------- settings
def test_settings_validation_and_clinic_names(admin):
    assert admin.put(f"{API}/settings", json={"time_zone": "Mars/Base"}).status_code == 422
    r = admin.put(f"{API}/settings", json={"time_zone": "Asia/Amman", "currency": "JOD", "currency_decimals": 3,
                                           "clinics": {"dental": "Smile Dental", "derma": "Glow Derma"}})
    assert r.status_code == 200
    s = r.json()
    assert s["clinics"]["dental"]["name"] == "Smile Dental" and s["currency"] == "JOD" and s["time_zone"] == "Asia/Amman"
    assert admin.put(f"{API}/settings", json={"clinics": {"derma_prefix": "D"}}).status_code == 422


# ---------------------------------------------------------------- backup / restore (SET-01/02)
def test_backup_and_restore_roundtrip(admin):
    new_patient(admin, name="Keep Me")
    r = admin.post(f"{API}/admin/backup")
    assert r.status_code == 200 and r.content.startswith(b"SQLite format 3")
    snapshot = r.content
    new_patient(admin, name="Added Later", phone="0799999999")
    assert admin.get(f"{API}/patients").json()["total"] == 2
    bad = admin.post(f"{API}/admin/restore", files={"file": ("x.db", b"garbage", "application/octet-stream")},
                     data={"confirm": "RESTORE"})
    assert bad.status_code == 422
    assert admin.post(f"{API}/admin/restore", files={"file": ("b.db", snapshot, "application/octet-stream")},
                      data={"confirm": "yes"}).status_code == 422
    r = admin.post(f"{API}/admin/restore", files={"file": ("b.db", snapshot, "application/octet-stream")},
                   data={"confirm": "RESTORE"})
    assert r.status_code == 200, r.text
    names = [p["name"] for p in admin.get(f"{API}/patients").json()["items"]]
    assert names == ["Keep Me"]
    assert admin.get(f"{API}/audit", params={"action": "restore"}).json()["total"] == 1


def test_encrypted_backup(admin, monkeypatch):
    from cryptography.fernet import Fernet

    from app.config import get_settings
    from app.services import backup as B

    monkeypatch.setattr(get_settings(), "backup_encryption_key", Fernet.generate_key().decode())
    path = B.make_backup("manual")
    data = path.read_bytes()
    assert not data.startswith(b"SQLite") and B.decode_upload(data).startswith(b"SQLite format 3")


def test_backup_retention(monkeypatch):
    from app.config import get_settings
    from app.services import backup as B

    monkeypatch.setattr(get_settings(), "backup_keep", 3)
    for i in range(5):
        (get_settings().backup_dir / f"nightly-2026010{i}-000000.db").write_bytes(b"x")
    B.prune("nightly")
    assert len(list(get_settings().backup_dir.glob("nightly-*"))) == 3


# ---------------------------------------------------------------- v1 import (SET-03)
V1 = {
    "data": {
        "settings": {"currency": "JOD"},
        "staff": [{"id": "s1", "name": "Dr Old", "role": "Doctor", "clinic": "dental", "salary": 1500, "pct": 30,
                   "username": "drold", "pin": "1234"},
                  {"id": "s2", "name": "Cleaner", "role": "Other"}],
        "services": [{"id": "v1", "name": "Filling", "clinic": "dental", "price": 50, "pct": "", "lab": 5}],
        "patients": [{"id": "p1", "name": "Old Patient", "phone": "0790000000", "clinic": "Dental",
                      "teeth": {"16": "Caries", "21": "crown"}}],
        "appointments": [{"id": "a1", "patientId": "p1", "doctorId": "s1", "serviceId": "v1", "date": "2026-09-01",
                          "time": "10:30", "status": "completed"}],
        "invoices": [{"id": "i1", "number": "INV-0001", "patientId": "p1", "doctorId": "s1", "clinic": "dental",
                      "date": "2026-09-01", "discount": 0,
                      "lines": [{"serviceId": "v1", "qty": 2, "price": 50, "pct": "", "lab": ""}],
                      "payments": [{"amount": 60, "date": "2026-09-01", "method": "cash"}]}],
        "expenses": [{"date": "2026-09-02", "category": "Rent", "amount": 700.5}],
    }
}


def test_import_v1_dry_run_then_real(admin):
    payload = io.BytesIO(json.dumps(V1).encode())
    r = admin.post(f"{API}/admin/import-v1", files={"file": ("clinic-erp-backup-2026-09-30.json", payload)},
                   data={"dry_run": "true"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["counts"]["patients"] == 1 and rep["counts"]["invoices"] == 1 and rep["filled_lines"] == 1
    assert any("Other" in w for w in rep["warnings"])
    assert admin.get(f"{API}/patients").json()["total"] == 0  # dry run saved nothing
    r = admin.post(f"{API}/admin/import-v1", files={"file": ("b.json", io.BytesIO(json.dumps(V1).encode()))},
                   data={"dry_run": "false"})
    assert r.status_code == 200
    pats = admin.get(f"{API}/patients").json()["items"]
    assert pats[0]["name"] == "Old Patient" and pats[0]["file_no"].startswith("P-")
    inv = admin.get(f"{API}/invoices").json()["items"][0]
    assert inv["total"] == 10000 and inv["paid"] == 6000 and inv["status"] == "Posted"
    full = admin.get(f"{API}/invoices/{inv['id']}").json()
    assert full["lines"][0]["share_pct"] == 30 and full["lines"][0]["lab_cost"] == 500  # filled from service/doctor
    assert admin.get(f"{API}/audit", params={"action": "import_fill"}).json()["total"] == 1
    users = {u["username"]: u for u in admin.get(f"{API}/users").json()}
    assert users["drold"]["must_change_pw"]
    chart = admin.get(f"{API}/patients/{pats[0]['id']}/teeth").json()
    assert chart["current"]["21"]["condition"] == "Crown"
    with dbmod.SessionLocal() as s:
        assert s.query(Invoice).count() == 1
    # the imported login has no password until Admin issues one
    from tests.conftest import Client, app

    assert Client(app).post(f"{API}/auth/login", json={"username": "drold", "password": "1234"}).status_code == 401
    assert utcnow()
