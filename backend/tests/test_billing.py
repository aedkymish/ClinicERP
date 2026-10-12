from datetime import date

import pytest
from sqlalchemy import text

from app import db as dbmod
from app.models import InvoiceLine
from app.services.billing import compute_lines, discount_amount
from tests.conftest import new_patient, new_service

API = "/api/v1"


@pytest.fixture
def setup(as_role, admin):
    doctor = as_role("doctor", username="drsara", share=40)
    svc = new_service(admin, name="Crown", price=10000, share_pct=None, lab_cost=1000)
    pat = new_patient(admin)
    return {"doctor": doctor, "doctor_staff": doctor.user.staff_id, "svc": svc, "pat": pat}


def invoice(c, setup, lines=None, **kw):
    body = {"patient_id": setup["pat"]["id"], "clinic": "dental", "doctor_id": setup["doctor_staff"],
            "lines": lines if lines is not None else [{"service_id": setup["svc"]["id"], "qty": 2}], **kw}
    r = c.post(f"{API}/invoices", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- arithmetic
def test_discount_amount():
    assert discount_amount(10000, "percent", 10) == 1000
    assert discount_amount(10000, "amount", 2500) == 2500
    assert discount_amount(10000, "amount", 99999) == 10000  # capped
    assert discount_amount(0, "percent", 50) == 0


def test_line_split_and_vat():
    lines = [InvoiceLine(qty=1, unit_price=3333, vat_applies=True), InvoiceLine(qty=2, unit_price=3333, vat_applies=False)]
    subtotal, discount, vat, calcs = compute_lines(lines, "amount", 1000, 16)
    assert subtotal == 9999 and discount == 1000
    assert sum(c.discount for c in calcs) == 1000  # rounding absorbed by the last line
    assert vat == round((3333 - calcs[0].discount) * 0.16)


def test_totals_and_balance(as_role, setup):
    rec = as_role("receptionist")
    inv = invoice(rec, setup, discount_type="percent", discount_value=10)
    assert inv["subtotal"] == 20000 and inv["discount"] == 2000 and inv["total"] == 18000
    assert inv["balance"] == 18000 and inv["payment_status"] == "Unpaid" and inv["status"] == "Draft"


def test_vat_applied_when_enabled(admin, setup):
    admin.put(f"{API}/settings", json={"vat_enabled": True, "vat_rate": 16})
    admin.patch(f"{API}/services/{setup['svc']['id']}", json={"vat_applies": True})
    inv = invoice(admin, setup)
    assert inv["vat_rate"] == 16 and inv["vat"] == 3200 and inv["total"] == 23200


# ---------------------------------------------------------------- numbering (INV-02)
def test_numbering_per_clinic_without_gaps(admin, setup):
    derma_svc = new_service(admin, clinic="derma", name="Peel", price=5000)
    year = date.today().year
    a = invoice(admin, setup)
    b = invoice(admin, setup)
    c = invoice(admin, setup, clinic="derma", lines=[{"service_id": derma_svc["id"], "qty": 1}])
    assert a["number"] == f"D-{year}-00001" and b["number"] == f"D-{year}-00002"
    assert c["number"] == f"M-{year}-00001"


# ---------------------------------------------------------------- copy from service (INV-03)
def test_line_copies_share_and_lab_cost(admin, setup):
    inv = invoice(admin, setup)
    line = inv["lines"][0]
    assert line["unit_price"] == 10000 and line["lab_cost"] == 1000
    assert line["share_pct"] == 40  # blank on service → doctor default
    svc2 = new_service(admin, name="Implant", price=50000, share_pct=25, lab_cost=20000)
    inv2 = invoice(admin, setup, lines=[{"service_id": svc2["id"], "qty": 1}])
    assert inv2["lines"][0]["share_pct"] == 25


def test_finance_can_override_line_values_receptionist_cannot(as_role, setup):
    fin, rec = as_role("finance"), as_role("receptionist")
    lines = [{"service_id": setup["svc"]["id"], "qty": 1, "share_pct": 55, "lab_cost": 0}]
    inv = invoice(fin, setup, lines=lines)
    assert inv["lines"][0]["share_pct"] == 55 and inv["lines"][0]["lab_cost"] == 0
    inv = invoice(rec, setup, lines=lines)
    assert inv["lines"][0]["share_pct"] == 40 and inv["lines"][0]["lab_cost"] == 1000
    r = rec.post(f"{API}/invoices", json={"patient_id": setup["pat"]["id"], "clinic": "dental",
                                          "lines": [{"service_id": setup["svc"]["id"], "qty": 1, "unit_price": 1}]})
    assert r.status_code == 403


def test_later_price_change_does_not_alter_existing_line(admin, setup):
    inv = invoice(admin, setup)
    admin.patch(f"{API}/services/{setup['svc']['id']}", json={"price": 99999, "share_pct": 90})
    again = admin.get(f"{API}/invoices/{inv['id']}").json()
    assert again["lines"][0]["unit_price"] == 10000 and again["lines"][0]["share_pct"] == 40


# ---------------------------------------------------------------- posting and locks (INV-06/07, NFR-06)
def test_first_payment_posts_and_locks(as_role, setup):
    rec = as_role("receptionist")
    inv = invoice(rec, setup)
    r = rec.post(f"{API}/invoices/{inv['id']}/payments", json={"amount": 5000, "method": "Cash"})
    assert r.status_code == 201
    inv = r.json()
    assert inv["status"] == "Posted" and inv["payment_status"] == "Partial" and inv["balance"] == 15000
    r = rec.patch(f"{API}/invoices/{inv['id']}", json={"discount_value": 100})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "locked"


def test_overpayment_rejected(admin, setup):
    inv = invoice(admin, setup)
    assert admin.post(f"{API}/invoices/{inv['id']}/payments", json={"amount": 20001}).status_code == 422


def test_print_posts_invoice(admin, setup):
    inv = invoice(admin, setup)
    r = admin.get(f"{API}/invoices/{inv['id']}/pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert admin.get(f"{API}/invoices/{inv['id']}").json()["status"] == "Posted"
    assert admin.get(f"{API}/invoices/{inv['id']}/pdf", params={"paper": "thermal", "kind": "receipt"}).status_code == 200


def test_refund_void_and_credit_note(as_role, setup):
    rec, fin = as_role("receptionist"), as_role("finance")
    inv = invoice(rec, setup)
    inv = rec.post(f"{API}/invoices/{inv['id']}/payments", json={"amount": 20000, "method": "Card"}).json()
    assert inv["payment_status"] == "Paid"
    pay_id = inv["payments"][0]["id"]
    # receptionist may not refund or void
    assert rec.post(f"{API}/payments/{pay_id}/refund", json={"reason": "test"}).status_code == 403
    assert rec.post(f"{API}/invoices/{inv['id']}/void", json={"reason": "test"}).status_code == 403
    # void blocked while money is held
    r = fin.post(f"{API}/invoices/{inv['id']}/void", json={"reason": "wrong patient"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "has_payments"
    # credit note reduces the balance
    inv = fin.post(f"{API}/invoices/{inv['id']}/credit-notes", json={"amount": 2000, "reason": "goodwill"}).json()
    assert inv["credited"] == 2000 and inv["balance"] == -2000 and inv["payment_status"] == "Credit"
    inv = fin.post(f"{API}/payments/{pay_id}/refund", json={"amount": 2000, "reason": "goodwill refund"}).json()
    assert inv["balance"] == 0 and inv["refunded"] == 2000
    inv = fin.post(f"{API}/payments/{pay_id}/refund", json={"reason": "full refund"}).json()
    assert inv["refunded"] == 20000
    assert fin.post(f"{API}/payments/{pay_id}/refund", json={"reason": "again"}).status_code == 422
    inv = fin.post(f"{API}/invoices/{inv['id']}/void", json={"reason": "wrong patient"}).json()
    assert inv["status"] == "Void" and inv["balance"] == 0
    # payments are never deleted: there is no endpoint, and the DB refuses
    assert fin.delete(f"{API}/payments/{pay_id}").status_code in (404, 405)
    with dbmod.SessionLocal() as s, pytest.raises(Exception):
        s.execute(text("delete from payments"))
        s.commit()


def test_doctor_sees_only_own_invoices(as_role, admin, setup):
    other = as_role("doctor", username="drother")
    inv = invoice(admin, setup)
    assert setup["doctor"].get(f"{API}/invoices/{inv['id']}").status_code == 200
    assert other.get(f"{API}/invoices/{inv['id']}").status_code == 403
    assert other.get(f"{API}/invoices").json()["total"] == 0
    assert setup["doctor"].post(f"{API}/invoices", json={"patient_id": 1, "clinic": "dental"}).status_code == 403


# ---------------------------------------------------------------- stock deduction (INV-09)
def test_posting_deducts_stock_and_void_restores(as_role, admin, setup):
    nurse = as_role("nurse")
    item = nurse.post(f"{API}/inventory", json={"clinic": "dental", "name": "Zirconia block", "unit": "pcs",
                                                "opening_qty": 3, "reorder_level": 1}).json()
    assert admin.put(f"{API}/services/{setup['svc']['id']}/items",
                     json=[{"item_id": item["id"], "qty_per_unit": 1}]).status_code == 200
    inv = invoice(admin, setup)  # qty 2
    admin.post(f"{API}/invoices/{inv['id']}/post")
    items = {i["id"]: i for i in nurse.get(f"{API}/inventory").json()}
    assert items[item["id"]]["qty"] == 1 and items[item["id"]]["low"]
    # second invoice needs 2 but only 1 left → refused
    inv2 = invoice(admin, setup)
    r = admin.post(f"{API}/invoices/{inv2['id']}/post")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stock_shortage"
    admin.post(f"{API}/invoices/{inv['id']}/void", json={"reason": "cancelled treatment"})
    items = {i["id"]: i for i in nurse.get(f"{API}/inventory").json()}
    assert items[item["id"]]["qty"] == 3
    kinds = [m["kind"] for m in nurse.get(f"{API}/inventory/{item['id']}/movements").json()]
    assert kinds.count("Auto") == 2


def test_stale_update_rejected(admin, setup):
    inv = invoice(admin, setup)
    v = inv["version"]
    assert admin.patch(f"{API}/invoices/{inv['id']}", json={"notes": "first", "version": v}).status_code == 200
    r = admin.patch(f"{API}/invoices/{inv['id']}", json={"notes": "second", "version": v})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale"


def test_invoice_exports(admin, setup):
    invoice(admin, setup)
    for fmt in ("csv", "xlsx", "pdf"):
        r = admin.get(f"{API}/invoices", params={"format": fmt})
        assert r.status_code == 200 and len(r.content) > 50
