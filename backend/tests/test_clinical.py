from datetime import date, timedelta

import pytest
from sqlalchemy import update

from app import db as dbmod
from app.db import utcnow
from app.models import Visit
from tests.conftest import new_patient, new_service

API = "/api/v1"
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def ctx(as_role, admin):
    doctor = as_role("doctor", username="drsara")
    rec = as_role("receptionist")
    svc = new_service(admin, name="Cleaning", price=4000, duration_min=40)
    p1 = new_patient(admin, name="Pat One", phone="0790000001")
    p2 = new_patient(admin, name="Pat Two", phone="0790000002")
    return {"doctor": doctor, "doc_id": doctor.user.staff_id, "rec": rec, "svc": svc, "p1": p1, "p2": p2}


def book(c, ctx, patient, time="10:00", **kw):
    body = {"patient_id": patient["id"], "doctor_id": ctx["doc_id"], "service_id": ctx["svc"]["id"],
            "date": TOMORROW, "time": time, **kw}
    return c.post(f"{API}/appointments", json=body)


# ---------------------------------------------------------------- appointments
def test_service_fills_duration_and_clinic(ctx):
    a = book(ctx["rec"], ctx, ctx["p1"]).json()
    assert a["duration_min"] == 40 and a["clinic"] == "dental" and a["time"] == "10:00"


def test_overlap_blocked_for_doctor_room_and_patient(ctx):
    rec = ctx["rec"]
    assert book(rec, ctx, ctx["p1"], room="Room 1").status_code == 201
    r = book(rec, ctx, ctx["p2"], time="10:20")  # same doctor
    assert r.status_code == 409 and r.json()["detail"]["conflicts"][0]["clash"] == ["doctor"]
    r = book(rec, ctx, ctx["p2"], time="10:20", doctor_id=None, room="Room 1")  # same room
    assert r.status_code == 409 and "room" in r.json()["detail"]["conflicts"][0]["clash"]
    r = book(rec, ctx, ctx["p1"], time="10:30", doctor_id=None)  # same patient
    assert r.status_code == 409 and "patient" in r.json()["detail"]["conflicts"][0]["clash"]
    assert book(rec, ctx, ctx["p2"], time="10:40").status_code == 201  # back-to-back is fine


def test_admin_override_needs_reason_and_is_audited(ctx, admin):
    book(ctx["rec"], ctx, ctx["p1"])
    # receptionist cannot override even with a reason
    assert book(ctx["rec"], ctx, ctx["p2"], override_reason="urgent").status_code == 409
    r = book(admin, ctx, ctx["p2"], override_reason="Emergency, doctor agreed")
    assert r.status_code == 201 and r.json()["override_reason"] == "Emergency, doctor agreed"
    assert admin.get(f"{API}/audit", params={"action": "override"}).json()["total"] == 1


def test_cancelled_booking_frees_the_slot(ctx):
    a = book(ctx["rec"], ctx, ctx["p1"]).json()
    ctx["rec"].post(f"{API}/appointments/{a['id']}/status", json={"status": "Cancelled"})
    assert book(ctx["rec"], ctx, ctx["p2"]).status_code == 201
    # re-activating the cancelled one would double-book
    r = ctx["rec"].post(f"{API}/appointments/{a['id']}/status", json={"status": "Scheduled"})
    assert r.status_code == 409


def test_status_log_and_completion_prefill(ctx):
    rec = ctx["rec"]
    a = book(rec, ctx, ctx["p1"]).json()
    for s in ("Confirmed", "Checked-in", "In progress"):
        rec.post(f"{API}/appointments/{a['id']}/status", json={"status": s})
    done = rec.post(f"{API}/appointments/{a['id']}/status", json={"status": "Completed"}).json()
    assert done["next"]["visit"]["appointment_id"] == a["id"]
    assert done["next"]["invoice"]["service_id"] == ctx["svc"]["id"]
    hist = rec.get(f"{API}/appointments/{a['id']}/history").json()
    assert [h["to"] for h in hist] == ["Scheduled", "Confirmed", "Checked-in", "In progress", "Completed"]
    assert all(h["user"] for h in hist)


def test_week_view_filters(ctx):
    book(ctx["rec"], ctx, ctx["p1"], room="Room 2")
    week = ctx["rec"].get(f"{API}/appointments", params={"date": date.today().isoformat(), "days": 7}).json()
    assert len(week) == 1
    assert ctx["rec"].get(f"{API}/appointments", params={"date": TOMORROW, "room": "Room 1"}).json() == []
    assert len(ctx["rec"].get(f"{API}/appointments", params={"date": TOMORROW, "doctor": ctx["doc_id"]}).json()) == 1


# ---------------------------------------------------------------- clinical notes
def test_note_editable_by_author_for_24h_then_locked(ctx, as_role):
    doc = ctx["doctor"]
    v = doc.post(f"{API}/visits", json={"patient_id": ctx["p1"]["id"], "clinic": "dental", "diagnosis": "Caries",
                                        "teeth": "16, 17", "follow_up": date.today().isoformat()}).json()
    assert v["doctor_id"] == ctx["doc_id"] and v["teeth"] == "16,17" and v["can_edit"]
    assert doc.patch(f"{API}/visits/{v['id']}", json={"treatment": "Filling"}).status_code == 200
    nurse = as_role("nurse")
    assert nurse.patch(f"{API}/visits/{v['id']}", json={"treatment": "X"}).status_code == 403
    with dbmod.SessionLocal() as s:
        s.execute(update(Visit).where(Visit.id == v["id"]).values(locked_at=utcnow() - timedelta(seconds=1)))
        s.commit()
    r = doc.patch(f"{API}/visits/{v['id']}", json={"treatment": "Changed"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "locked"
    r = doc.post(f"{API}/visits/{v['id']}/addenda", json={"text": "Patient called, pain resolved"})
    assert r.status_code == 201 and r.json()["addenda"][0]["text"] == "Patient called, pain resolved"
    # follow-up task appears on the dashboard (VISIT-04)
    dash = doc.get(f"{API}/dashboard").json()
    assert dash["follow_ups"][0]["visit_id"] == v["id"]


def test_note_validation(ctx):
    doc = ctx["doctor"]
    r = doc.post(f"{API}/visits", json={"patient_id": ctx["p1"]["id"], "clinic": "dental", "teeth": "19"})
    assert r.status_code == 422
    r = doc.post(f"{API}/visits", json={"patient_id": ctx["p1"]["id"], "clinic": "derma", "skin_type": "VII"})
    assert r.status_code == 422
    v = doc.post(f"{API}/visits", json={"patient_id": ctx["p1"]["id"], "clinic": "derma", "skin_type": "III",
                                        "area": "Forehead"}).json()
    assert v["skin_type"] == "III"


def test_receptionist_and_assistant_note_access(ctx, as_role):
    assert ctx["rec"].get(f"{API}/visits").status_code == 403
    asst = as_role("assistant")
    assert asst.get(f"{API}/visits").status_code == 200
    assert asst.post(f"{API}/visits", json={"patient_id": ctx["p1"]["id"], "clinic": "dental"}).status_code == 403


# ---------------------------------------------------------------- dental chart
def test_dental_chart_keeps_history(ctx, admin):
    doc = ctx["doctor"]
    pid = ctx["p1"]["id"]
    doc.post(f"{API}/patients/{pid}/teeth", json={"tooth": 36, "condition": "Caries"})
    doc.post(f"{API}/patients/{pid}/teeth", json={"tooth": 36, "condition": "Filling", "surface": "O"})
    doc.post(f"{API}/patients/{pid}/teeth", json={"tooth": 55, "condition": "Missing"})  # primary tooth
    chart = doc.get(f"{API}/patients/{pid}/teeth").json()
    assert chart["current"]["36"]["condition"] == "Filling"
    assert [h["condition"] for h in chart["history"]["36"]] == ["Filling", "Caries"]
    assert doc.post(f"{API}/patients/{pid}/teeth", json={"tooth": 19, "condition": "Caries"}).status_code == 422
    assert doc.post(f"{API}/patients/{pid}/teeth", json={"tooth": 11, "condition": "Broken"}).status_code == 422
    derma = new_patient(admin, name="Skin Only", phone="0791110000", scope="derma")
    assert doc.get(f"{API}/patients/{derma['id']}/teeth").status_code == 422


# ---------------------------------------------------------------- patients
def test_duplicate_warning_and_file_numbers(admin):
    r = admin.post(f"{API}/patients", json={"name": "Ali", "phone": "+962 79 123 4567"})
    assert r.status_code == 201 and r.json()["file_no"] == "P-000001"
    r = admin.post(f"{API}/patients", json={"name": "Ali B", "phone": "0791234567"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate"
    r = admin.post(f"{API}/patients", json={"name": "Ali B", "phone": "0791234567"}, params={"confirm_duplicate": True})
    assert r.json()["file_no"] == "P-000002"
    assert admin.post(f"{API}/patients", json={"name": "", "phone": "1"}).status_code == 422


def test_archive_only_admin_and_hidden(as_role, admin):
    p = new_patient(admin)
    rec = as_role("receptionist")
    assert rec.post(f"{API}/patients/{p['id']}/archive").status_code == 403
    assert admin.post(f"{API}/patients/{p['id']}/archive").status_code == 200
    assert rec.get(f"{API}/patients").json()["total"] == 0
    assert admin.get(f"{API}/patients", params={"archived": True}).json()["total"] == 1
    assert admin.delete(f"{API}/patients/{p['id']}").status_code == 405


def test_patient_header_balance_and_view_logged(admin):
    p = new_patient(admin, allergies="Latex")
    svc = new_service(admin, price=5000)
    admin.post(f"{API}/invoices", json={"patient_id": p["id"], "clinic": "dental",
                                         "lines": [{"service_id": svc["id"], "qty": 1}]}).json()
    got = admin.get(f"{API}/patients/{p['id']}").json()
    assert got["allergies"] == "Latex" and got["balance"] == 5000
    views = admin.get(f"{API}/audit", params={"action": "view", "entity": "patients"}).json()
    assert views["total"] == 1 and views["items"][0]["entity_id"] == p["id"]


def test_patient_documents(admin):
    p = new_patient(admin)
    r = admin.post(f"{API}/patients/{p['id']}/files", files={"file": ("xray.png", b"\x89PNG....", "image/png")})
    assert r.status_code == 201
    assert admin.post(f"{API}/patients/{p['id']}/files",
                      files={"file": ("evil.exe", b"MZ", "application/x-msdownload")}).status_code == 422
    big = b"0" * (10 * 1024 * 1024 + 1)
    assert admin.post(f"{API}/patients/{p['id']}/files", files={"file": ("big.pdf", big, "application/pdf")}).status_code == 413
    files = admin.get(f"{API}/patients/{p['id']}/files").json()
    assert len(files) == 1
    assert admin.get(f"{API}/patients/{p['id']}/files/{files[0]['id']}").content == b"\x89PNG...."


def test_patient_export(admin):
    new_patient(admin, name="عبدالله")
    for fmt in ("csv", "xlsx"):
        r = admin.get(f"{API}/patients", params={"format": fmt})
        assert r.status_code == 200
    assert "عبدالله".encode() in admin.get(f"{API}/patients", params={"format": "csv"}).content
