from datetime import date, timedelta

import pytest

from app import db as dbmod
from app.services.billing import commission_for
from tests.conftest import new_patient, new_service

API = "/api/v1"


@pytest.fixture
def world(as_role, admin):
    doctor = as_role("doctor", username="drsara", share=40, salary=260000)
    fin = as_role("finance")
    svc = new_service(admin, name="Crown", price=10000, lab_cost=1000)  # share blank → doctor 40 %
    pat = new_patient(admin)
    inv = fin.post(f"{API}/invoices", json={
        "patient_id": pat["id"], "clinic": "dental", "doctor_id": doctor.user.staff_id,
        "discount_type": "percent", "discount_value": 10, "lines": [{"service_id": svc["id"], "qty": 2}]}).json()
    return {"doctor": doctor, "fin": fin, "inv": inv, "staff_id": doctor.user.staff_id}


def test_commission_formula_pay_03(world):
    """(qty×price×(1−disc share) − qty×lab) × share × paid fraction = (20000−2000−2000)×40 % = 6400."""
    fin, inv = world["fin"], world["inv"]
    today = date.today()
    fin.post(f"{API}/invoices/{inv['id']}/payments", json={"amount": 9000})  # half of 18000
    with dbmod.SessionLocal() as s:
        total, lines = commission_for(s, world["staff_id"], today, today)
    assert total == 3200
    assert lines[0].base == 6400 and lines[0].paid_fraction == 0.5
    fin.post(f"{API}/invoices/{inv['id']}/payments", json={"amount": 9000})
    with dbmod.SessionLocal() as s:
        assert commission_for(s, world["staff_id"], today, today)[0] == 6400


def test_commission_scaled_by_month_of_payment(world):
    fin, inv = world["fin"], world["inv"]
    last_month = date.today().replace(day=1) - timedelta(days=1)
    fin.post(f"{API}/invoices/{inv['id']}/payments", json={"amount": 4500, "date": last_month.isoformat()})
    fin.post(f"{API}/invoices/{inv['id']}/payments", json={"amount": 13500})
    with dbmod.SessionLocal() as s:
        prev = commission_for(s, world["staff_id"], last_month.replace(day=1), last_month)[0]
        cur = commission_for(s, world["staff_id"], date.today().replace(day=1), date.today())[0]
    assert prev == 1600 and cur == 4800 and prev + cur == 6400


def test_refund_claws_back_commission(world):
    fin, inv = world["fin"], world["inv"]
    inv = fin.post(f"{API}/invoices/{inv['id']}/payments", json={"amount": 18000}).json()
    fin.post(f"{API}/payments/{inv['payments'][0]['id']}/refund", json={"amount": 9000, "reason": "partial refund"})
    with dbmod.SessionLocal() as s:
        assert commission_for(s, world["staff_id"], date.today(), date.today())[0] == 3200


def test_negative_net_gives_zero_commission(as_role, admin):
    doctor = as_role("doctor", username="drz", share=50)
    svc = new_service(admin, name="Lab heavy", price=1000, lab_cost=5000)
    pat = new_patient(admin)
    inv = admin.post(f"{API}/invoices", json={"patient_id": pat["id"], "clinic": "dental",
                                               "doctor_id": doctor.user.staff_id,
                                               "lines": [{"service_id": svc["id"], "qty": 1}]}).json()
    admin.post(f"{API}/invoices/{inv['id']}/payments", json={"amount": 1000})
    with dbmod.SessionLocal() as s:
        assert commission_for(s, doctor.user.staff_id, date.today(), date.today())[0] == 0


def test_payroll_run_end_to_end(world, as_role, admin):
    fin, doctor = world["fin"], world["doctor"]
    fin.post(f"{API}/invoices/{world['inv']['id']}/payments", json={"amount": 18000})
    month = date.today().strftime("%Y-%m")
    # two days unpaid absence → 260000 / 26 × 2 = 20000
    for d in (1, 2):
        r = fin.post(f"{API}/attendance", json={"staff_id": world["staff_id"], "date": date.today().replace(day=d).isoformat(),
                                                "status": "Unpaid leave" if d == 1 else "Absent", "note": "recorded"})
        assert r.status_code == 201
    run = fin.post(f"{API}/payroll/runs", json={"month": month}).json()
    line = next(l for l in run["lines"] if l["staff_id"] == world["staff_id"])
    assert line["base"] == 260000 and line["absence_days"] == 2 and line["absence_deduction"] == 20000
    assert line["commission"] == 6400
    line = fin.patch(f"{API}/payroll/lines/{line['id']}", json={"bonus": 5000, "deductions": 1000, "note": "x"}).json()
    assert line["net"] == 260000 - 20000 + 6400 + 5000 - 1000
    # draft payslips are not visible to the employee
    assert doctor.get(f"{API}/payroll/lines/{line['id']}/payslip").status_code == 403
    # finance cannot approve; admin can
    assert fin.post(f"{API}/payroll/runs/{run['id']}/approve").status_code == 403
    assert admin.post(f"{API}/payroll/runs/{run['id']}/approve").status_code == 200
    # approved runs are locked (NFR-06)
    assert fin.patch(f"{API}/payroll/lines/{line['id']}", json={"bonus": 1}).status_code == 409
    assert fin.post(f"{API}/payroll/runs", json={"month": month}).status_code == 409
    paid = fin.post(f"{API}/payroll/runs/{run['id']}/pay", json={"paid_on": date.today().isoformat(),
                                                               "method": "Bank transfer"}).json()
    assert paid["status"] == "Paid"
    # the employee sees and prints only their own payslip
    mine = doctor.get(f"{API}/payroll/my").json()
    assert len(mine) == 1 and mine[0]["net"] == line["net"]
    pdf = doctor.get(f"{API}/payroll/lines/{line['id']}/payslip")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    other_line = next(l for l in run["lines"] if l["staff_id"] != world["staff_id"])
    assert doctor.get(f"{API}/payroll/lines/{other_line['id']}/payslip").status_code == 403
    assert doctor.get(f"{API}/payroll/runs").status_code == 403


def test_recalculate_draft_keeps_bonus(world):
    fin = world["fin"]
    month = date.today().strftime("%Y-%m")
    run = fin.post(f"{API}/payroll/runs", json={"month": month}).json()
    line = run["lines"][0]
    fin.patch(f"{API}/payroll/lines/{line['id']}", json={"bonus": 777})
    run = fin.post(f"{API}/payroll/runs", json={"month": month}).json()
    assert next(l for l in run["lines"] if l["id"] == line["id"])["bonus"] == 777


def test_report_summary_uses_payroll_and_commission(world, admin):
    fin = world["fin"]
    fin.post(f"{API}/invoices/{world['inv']['id']}/payments", json={"amount": 18000})
    fin.post(f"{API}/expenses", json={"date": date.today().isoformat(), "category": "Rent", "amount": 5000})
    month = date.today().strftime("%Y-%m")
    run = fin.post(f"{API}/payroll/runs", json={"month": month}).json()
    admin.post(f"{API}/payroll/runs/{run['id']}/approve")
    k = fin.get(f"{API}/reports/summary").json()["kpis"]
    assert k["revenue_collected"] == 18000 and k["expenses"] == 5000 and k["doctor_commission"] == 6400
    assert k["payroll"] == sum(l["net"] for l in run["lines"])
    assert k["net_profit"] == 18000 - 5000 - k["payroll"]
    # doctor sees own commission report only
    rep = world["doctor"].get(f"{API}/reports/commission").json()
    assert rep["total"] == 6400 and len(rep["per_doctor"]) == 1
    assert world["doctor"].get(f"{API}/reports/summary").status_code == 403
