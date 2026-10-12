"""Billing — INV-01..09: invoices, posting, void, credit notes, payments and refunds."""
import datetime as dt
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import log_event
from ..db import get_db, utcnow
from ..deps import (check_version, clinic_filter, clinic_tz, conflict, ensure_clinic, ensure_scope_value, forbidden,
                    http_error, not_found, require, settings_map)
from ..models import (CLINIC_CODES, CLINIC_IDS, PAYMENT_METHODS, Appointment, CreditNote, Invoice, InvoiceLine, Patient,
                      Payment, Service, Staff, User)
from ..permissions import can
from ..services.billing import (StockShortage, next_credit_number, next_invoice_number, post_invoice, reverse_stock,
                                totals)
from ..services.export import export, file_response
from ..services.pdf import credit_note_pdf, invoice_pdf
from ..timeutil import iso_utc, local_today

router = APIRouter(tags=["billing"])


class LineIn(BaseModel):
    service_id: int | None = None
    description: str | None = None
    qty: float = Field(1, gt=0)
    unit_price: int | None = Field(default=None, ge=0)
    share_pct: float | None = Field(default=None, ge=0, le=100)  # Finance/Admin override (INV-03)
    lab_cost: int | None = Field(default=None, ge=0)
    vat_applies: bool | None = None


class InvoiceIn(BaseModel):
    patient_id: int
    clinic: Literal["dental", "derma"]
    doctor_id: int | None = None
    appointment_id: int | None = None
    date: dt.date | None = None
    discount_type: Literal["amount", "percent"] = "amount"
    discount_value: float = Field(0, ge=0)
    notes: str | None = None
    lines: list[LineIn] = []


class InvoicePatch(BaseModel):
    patient_id: int | None = None
    doctor_id: int | None = None
    date: dt.date | None = None
    discount_type: Literal["amount", "percent"] | None = None
    discount_value: float | None = Field(default=None, ge=0)
    notes: str | None = None
    lines: list[LineIn] | None = None
    version: int | None = None


class PaymentIn(BaseModel):
    amount: int = Field(gt=0)
    method: str = "Cash"
    date: dt.date | None = None
    note: str | None = None


class RefundIn(BaseModel):
    amount: int | None = Field(default=None, gt=0)  # default: the remaining refundable amount
    reason: str = Field(min_length=3)
    method: str | None = None


class VoidIn(BaseModel):
    reason: str = Field(min_length=3)


class CreditIn(BaseModel):
    amount: int = Field(gt=0)
    reason: str = Field(min_length=3)


# ---------------------------------------------------------------- helpers
def _name(db: Session, model, id_: int | None) -> str | None:
    obj = db.get(model, id_) if id_ else None
    return getattr(obj, "name", None) if obj else None


def refundable(inv: Invoice, p: Payment) -> int:
    done = sum(r.amount for r in inv.payments if r.kind == "Refund" and r.refund_of == p.id)
    return p.amount - done


def out(db: Session, inv: Invoice, full: bool = True) -> dict:
    t = totals(inv)
    p = db.get(Patient, inv.patient_id)
    d = {
        "id": inv.id, "number": inv.number, "clinic": CLINIC_CODES[inv.clinic_id], "clinic_id": inv.clinic_id,
        "patient_id": inv.patient_id, "patient_name": p.name if p else None, "patient_file_no": p.file_no if p else None,
        "doctor_id": inv.doctor_id, "doctor_name": _name(db, Staff, inv.doctor_id), "appointment_id": inv.appointment_id,
        "date": inv.date.isoformat(), "status": inv.status, "payment_status": t.payment_status,
        "discount_type": inv.discount_type, "discount_value": inv.discount_value, "vat_rate": inv.vat_rate,
        "subtotal": t.subtotal, "discount": t.discount, "vat": t.vat, "total": t.total, "credited": t.credited,
        "paid": t.paid, "refunded": t.refunded, "balance": t.balance, "version": inv.version,
        "posted_at": iso_utc(inv.posted_at), "void_reason": inv.void_reason, "notes": inv.notes,
    }
    if full:
        d["lines"] = [{
            "id": l.id, "service_id": l.service_id, "description": l.description, "qty": l.qty,
            "unit_price": l.unit_price, "share_pct": l.share_pct, "lab_cost": l.lab_cost, "vat_applies": l.vat_applies,
            "gross": c.gross, "discount": c.discount, "vat": c.vat,
        } for l, c in zip(inv.lines, t.lines, strict=True)]
        d["payments"] = [{
            "id": pm.id, "date": pm.date.isoformat(), "amount": pm.amount, "method": pm.method, "kind": pm.kind,
            "refund_of": pm.refund_of, "note": pm.note, "received_by": _username(db, pm.received_by),
            "refundable": refundable(inv, pm) if pm.kind == "Payment" else 0,
        } for pm in inv.payments]
        d["credit_notes"] = [{"id": c.id, "number": c.number, "amount": c.amount, "reason": c.reason,
                              "date": c.created_at.date().isoformat()} for c in inv.credit_notes]
    return d


def _username(db: Session, uid: int | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return (u.staff.name if u.staff else u.username) if u else None


def _get(db: Session, user: User, inv_id: int) -> Invoice:
    inv = db.get(Invoice, inv_id)
    if not inv:
        raise not_found("Invoice")
    ensure_clinic(user, inv.clinic_id)
    if user.role == "doctor" and inv.doctor_id != user.staff_id:
        raise forbidden("Doctors can only see their own invoices")
    return inv


def _build_lines(db: Session, inv: Invoice, lines: list[LineIn], user: User) -> None:
    """INV-03: copy price, doctor share % and lab cost from the service at pick time."""
    override = can(user.role, "billing.override")
    doctor = db.get(Staff, inv.doctor_id) if inv.doctor_id else None
    old = {(l.service_id, l.description): l for l in inv.lines}
    inv.lines.clear()
    db.flush()
    for li in lines:
        if li.service_id:
            svc = db.get(Service, li.service_id)
            if not svc:
                raise not_found("Service")
            if svc.clinic_id != inv.clinic_id:
                raise http_error(422, f"{svc.name} belongs to the other clinic", "validation")
            prev = old.get((svc.id, li.description or svc.name))
            share = svc.share_pct if svc.share_pct is not None else (doctor.default_share_pct if doctor else 0)
            line = InvoiceLine(service_id=svc.id, description=li.description or svc.name, qty=li.qty,
                               unit_price=svc.price, share_pct=share or 0, lab_cost=svc.lab_cost,
                               vat_applies=svc.vat_applies)
            if prev and not override:
                # keep values already on the line (e.g. set by Finance) when the cashier re-saves
                line.unit_price, line.share_pct, line.lab_cost = prev.unit_price, prev.share_pct, prev.lab_cost
            if li.unit_price is not None and li.unit_price != line.unit_price:
                if not override and svc.price != 0:  # zero-priced services are priced by the cashier
                    raise forbidden("Only Finance or Admin can change a service price on an invoice")
                line.unit_price = li.unit_price
        else:
            if not li.description or li.unit_price is None:
                raise http_error(422, "A free-text line needs a description and a price", "validation")
            line = InvoiceLine(description=li.description, qty=li.qty, unit_price=li.unit_price,
                               share_pct=doctor.default_share_pct if doctor else 0, lab_cost=0,
                               vat_applies=bool(li.vat_applies))
        if override:
            if li.share_pct is not None:
                line.share_pct = li.share_pct
            if li.lab_cost is not None:
                line.lab_cost = li.lab_cost
            if li.vat_applies is not None:
                line.vat_applies = li.vat_applies
        inv.lines.append(line)


def _vat_rate(db: Session) -> float:
    st = settings_map(db)
    return float(st["vat_rate"] or 0) if st["vat_enabled"] == "true" else 0.0


def _do_post(db: Session, inv: Invoice, user: User) -> None:
    try:
        post_invoice(db, inv, user.id)
    except StockShortage as e:
        raise conflict(str(e), "stock_shortage", item_id=e.item.id) from e
    except ValueError as e:
        raise conflict(str(e), "empty_invoice") from e


COLUMNS = [("number", "Number"), ("date", "Date"), ("clinic", "Clinic"), ("patient_file_no", "File no."),
           ("patient_name", "Patient"), ("doctor_name", "Doctor"), ("status", "Status"),
           ("payment_status", "Payment"), ("total", "Total"), ("paid", "Paid"), ("refunded", "Refunded"),
           ("credited", "Credited"), ("balance", "Balance")]


# ---------------------------------------------------------------- invoices
@router.get("/invoices")
def list_invoices(
    q: str | None = None, clinic: str | None = None, patient_id: int | None = None, doctor: int | None = None,
    status: str | None = None, payment_status: str | None = None,
    from_: dt.date | None = Query(None, alias="from"), to: date | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), format: str | None = None,
    user: User = Depends(require("billing.read")), db: Session = Depends(get_db),
):
    query = select(Invoice).join(Patient, Patient.id == Invoice.patient_id)\
        .where(clinic_filter(Invoice.clinic_id, user, clinic))
    if user.role == "doctor":
        query = query.where(Invoice.doctor_id == user.staff_id)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Invoice.number.ilike(like), Patient.name.ilike(like), Patient.file_no.ilike(like),
                                Patient.phone.ilike(like)))
    if patient_id:
        query = query.where(Invoice.patient_id == patient_id)
    if doctor:
        query = query.where(Invoice.doctor_id == doctor)
    if status:
        query = query.where(Invoice.status == status)
    if from_:
        query = query.where(Invoice.date >= from_)
    if to:
        query = query.where(Invoice.date <= to)
    query = query.order_by(Invoice.date.desc(), Invoice.id.desc())
    if payment_status or format:
        # derived status → filter in Python (list sizes are bounded by the date filter in practice)
        rows = [out(db, i, full=False) for i in db.scalars(query)]
        if payment_status:
            rows = [r for r in rows if r["payment_status"] == payment_status]
        if format:
            return export(db, rows, COLUMNS, format, "invoices", "invoices", "Invoices")
        total = len(rows)
        items = rows[(page - 1) * page_size: page * page_size]
    else:
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        items = [out(db, i, full=False) for i in db.scalars(query.offset((page - 1) * page_size).limit(page_size))]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/invoices/{inv_id}")
def get_invoice(inv_id: int, user: User = Depends(require("billing.read")), db: Session = Depends(get_db)):
    return out(db, _get(db, user, inv_id))


@router.post("/invoices", status_code=201)
def create_invoice(body: InvoiceIn, user: User = Depends(require("billing.create")), db: Session = Depends(get_db)):
    p = db.get(Patient, body.patient_id)
    if not p or p.archived:
        raise not_found("Patient")
    ensure_scope_value(user, p.clinic_scope)
    clinic_id = CLINIC_IDS[body.clinic]
    ensure_clinic(user, clinic_id)
    if body.doctor_id and not db.get(Staff, body.doctor_id):
        raise not_found("Doctor")
    if body.appointment_id:
        a = db.get(Appointment, body.appointment_id)
        if not a or a.patient_id != p.id:
            raise not_found("Appointment")
    on = body.date or local_today(clinic_tz(db))
    for attempt in range(3):
        inv = Invoice(number=next_invoice_number(db, clinic_id, on), clinic_id=clinic_id, patient_id=p.id,
                      doctor_id=body.doctor_id, appointment_id=body.appointment_id, date=on,
                      discount_type=body.discount_type, discount_value=body.discount_value, vat_rate=_vat_rate(db),
                      notes=body.notes, status="Draft")
        db.add(inv)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()  # another cashier took the number; retry with the next one
            if attempt == 2:
                raise conflict("Could not allocate an invoice number, please retry") from None
            continue
        break
    _build_lines(db, inv, body.lines, user)
    db.commit()
    db.refresh(inv)
    return out(db, inv)


@router.patch("/invoices/{inv_id}")
def patch_invoice(inv_id: int, body: InvoicePatch, user: User = Depends(require("billing.create")),
                  db: Session = Depends(get_db)):
    inv = _get(db, user, inv_id)
    if inv.status != "Draft":
        raise conflict("Posted invoices cannot be edited. Use a credit note or void it.", "locked")
    data = body.model_dump(exclude_unset=True)
    check_version(inv, data.pop("version", None))
    lines = data.pop("lines", None)
    if "patient_id" in data:
        p = db.get(Patient, data["patient_id"])
        if not p or p.archived:
            raise not_found("Patient")
        ensure_scope_value(user, p.clinic_scope)
    for k, v in data.items():
        if k in ("discount_type", "discount_value", "date", "patient_id") and v is None:
            continue
        setattr(inv, k, v)
    inv.vat_rate = _vat_rate(db)
    if lines is not None:
        _build_lines(db, inv, [LineIn(**l) for l in lines], user)
    db.commit()
    db.refresh(inv)
    return out(db, inv)


@router.post("/invoices/{inv_id}/post")
def post(inv_id: int, user: User = Depends(require("billing.create")), db: Session = Depends(get_db)):
    inv = _get(db, user, inv_id)
    if inv.status != "Draft":
        raise conflict("Invoice is already posted", "locked")
    _do_post(db, inv, user)
    db.commit()
    return out(db, inv)


@router.post("/invoices/{inv_id}/void")
def void(inv_id: int, body: VoidIn, user: User = Depends(require("billing.void")), db: Session = Depends(get_db)):
    inv = _get(db, user, inv_id)
    if inv.status == "Void":
        raise conflict("Invoice is already void", "locked")
    t = totals(inv)
    if t.paid - t.refunded > 0:
        raise conflict("Refund the payments on this invoice before voiding it", "has_payments")
    before = {"status": inv.status}
    if inv.status == "Posted":
        reverse_stock(db, inv, user.id)
    inv.status = "Void"
    inv.void_reason = body.reason.strip()
    inv.version += 1
    log_event(db, "void", "invoices", inv.id, before=before, after={"status": "Void", "reason": inv.void_reason})
    db.commit()
    return out(db, inv)


@router.post("/invoices/{inv_id}/credit-notes", status_code=201)
def credit_note(inv_id: int, body: CreditIn, user: User = Depends(require("billing.void")), db: Session = Depends(get_db)):
    inv = _get(db, user, inv_id)
    if inv.status != "Posted":
        raise conflict("Credit notes apply to posted invoices only", "not_posted")
    t = totals(inv)
    if body.amount > t.total - t.credited:
        raise http_error(422, "Credit exceeds the invoice total not yet credited", "validation", field="amount")
    note = CreditNote(invoice_id=inv.id, number=next_credit_number(db, inv), amount=body.amount,
                      reason=body.reason.strip())
    db.add(note)
    db.commit()
    db.refresh(inv)
    return out(db, inv)


@router.get("/invoices/{inv_id}/pdf")
def invoice_pdf_endpoint(inv_id: int, paper: Literal["a4", "thermal"] = "a4",
                         kind: Literal["invoice", "receipt"] = "invoice", credit_note_id: int | None = None,
                         user: User = Depends(require("billing.read")), db: Session = Depends(get_db)):
    inv = _get(db, user, inv_id)
    if credit_note_id:
        if not any(c.id == credit_note_id for c in inv.credit_notes):
            raise not_found("Credit note")
        return file_response(credit_note_pdf(db, inv, credit_note_id), "pdf", f"credit-note-{credit_note_id}", True)
    if inv.status == "Draft" and can(user.role, "billing.create"):
        _do_post(db, inv, user)  # INV-06: printing posts the invoice
    log_event(db, "print", "invoices", inv.id, after={"kind": kind, "paper": paper})
    db.commit()
    return file_response(invoice_pdf(db, inv, paper, kind), "pdf", f"{kind}-{inv.number}", inline=True)


# ---------------------------------------------------------------- payments
@router.post("/invoices/{inv_id}/payments", status_code=201)
def add_payment(inv_id: int, body: PaymentIn, user: User = Depends(require("billing.pay")), db: Session = Depends(get_db)):
    inv = _get(db, user, inv_id)
    if inv.status == "Void":
        raise conflict("Invoice is void", "locked")
    if body.method not in PAYMENT_METHODS:
        raise http_error(422, "Unknown payment method", "validation", field="method")
    t = totals(inv)
    if body.amount > t.balance:
        raise http_error(422, "Payment is larger than the balance due", "validation", field="amount")
    if inv.status == "Draft":
        _do_post(db, inv, user)  # INV-06: first payment posts the invoice
    db.add(Payment(invoice_id=inv.id, date=body.date or local_today(clinic_tz(db)), amount=body.amount,
                   method=body.method, received_by=user.id, kind="Payment", note=body.note))
    db.commit()
    db.refresh(inv)
    return out(db, inv)


@router.post("/payments/{payment_id}/refund", status_code=201)
def refund(payment_id: int, body: RefundIn, user: User = Depends(require("billing.void")), db: Session = Depends(get_db)):
    p = db.get(Payment, payment_id)
    if not p or p.kind != "Payment":
        raise not_found("Payment")
    inv = _get(db, user, p.invoice_id)
    left = refundable(inv, p)
    amount = body.amount or left
    if amount <= 0 or amount > left:
        raise http_error(422, f"At most {left} can be refunded from this payment", "validation", field="amount")
    method = body.method or p.method
    if method not in PAYMENT_METHODS:
        raise http_error(422, "Unknown payment method", "validation", field="method")
    r = Payment(invoice_id=inv.id, date=local_today(clinic_tz(db)), amount=amount, method=method,
                received_by=user.id, kind="Refund", refund_of=p.id, note=body.reason.strip())
    db.add(r)
    db.flush()
    log_event(db, "refund", "payments", r.id, after={"invoice": inv.number, "amount": amount, "of_payment": p.id,
                                                    "reason": r.note})
    db.commit()
    db.refresh(inv)
    return out(db, inv)


@router.get("/billing/prefill")
def prefill(appointment_id: int, user: User = Depends(require("billing.create")), db: Session = Depends(get_db)):
    """Draft-invoice values for a completed appointment (APPT-06)."""
    a = db.get(Appointment, appointment_id)
    if not a:
        raise not_found("Appointment")
    ensure_clinic(user, a.clinic_id)
    return {"patient_id": a.patient_id, "clinic": CLINIC_CODES[a.clinic_id], "doctor_id": a.doctor_id,
            "appointment_id": a.id, "lines": [{"service_id": a.service_id, "qty": 1}] if a.service_id else [],
            "generated_at": iso_utc(utcnow())}
