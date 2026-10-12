"""Payroll runs and payslips — PAY-01..06."""
import datetime as dt
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..db import get_db, utcnow
from ..deps import conflict, forbidden, get_current_user, http_error, not_found, require
from ..models import PAYMENT_METHODS, PayrollLine, PayrollRun, Staff, User
from ..permissions import can
from ..services.billing import commission_for
from ..services.export import file_response
from ..services.payroll import generate
from ..services.pdf import payslip_pdf
from ..timeutil import iso_utc, month_bounds

router = APIRouter(prefix="/payroll", tags=["payroll"])


class RunIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class LinePatch(BaseModel):
    bonus: int | None = Field(default=None, ge=0)
    deductions: int | None = Field(default=None, ge=0)
    note: str | None = None


class PayIn(BaseModel):
    paid_on: dt.date
    method: str = "Bank transfer"


def line_out(db: Session, l: PayrollLine) -> dict:
    s = db.get(Staff, l.staff_id)
    return {"id": l.id, "run_id": l.run_id, "staff_id": l.staff_id, "staff_name": s.name if s else None,
            "role": s.role if s else None, "base": l.base, "absence_days": l.absence_days,
            "absence_deduction": l.absence_deduction, "commission": l.commission, "bonus": l.bonus,
            "deductions": l.deductions, "net": l.net, "note": l.note}


def run_out(db: Session, r: PayrollRun, lines: bool = True) -> dict:
    approver = db.get(User, r.approved_by) if r.approved_by else None
    d = {"id": r.id, "month": r.month, "status": r.status, "approved_by": approver.username if approver else None,
         "approved_at": iso_utc(r.approved_at), "paid_on": r.paid_on.isoformat() if r.paid_on else None,
         "method": r.method, "total_net": sum(l.net for l in r.lines), "employees": len(r.lines)}
    if lines:
        d["lines"] = [line_out(db, l) for l in r.lines]
    return d


def _run(db: Session, run_id: int) -> PayrollRun:
    r = db.get(PayrollRun, run_id)
    if not r:
        raise not_found("Payroll run")
    return r


@router.get("/runs")
def list_runs(user: User = Depends(require("payroll.manage")), db: Session = Depends(get_db)):
    return [run_out(db, r, False) for r in db.scalars(select(PayrollRun).order_by(PayrollRun.month.desc()))]


@router.post("/runs", status_code=201)
def create_run(body: RunIn, user: User = Depends(require("payroll.manage")), db: Session = Depends(get_db)):
    """Generate the run for a month, or recalculate it while it is still Draft."""
    r = db.scalar(select(PayrollRun).where(PayrollRun.month == body.month))
    if r and r.status != "Draft":
        raise conflict(f"Payroll for {body.month} is {r.status} and locked", "locked")
    if not r:
        r = PayrollRun(month=body.month, status="Draft")
        db.add(r)
        db.flush()
    generate(db, r)
    db.commit()
    db.refresh(r)
    return run_out(db, r)


@router.get("/runs/{run_id}")
def get_run(run_id: int, user: User = Depends(require("payroll.manage")), db: Session = Depends(get_db)):
    return run_out(db, _run(db, run_id))


@router.patch("/lines/{line_id}")
def patch_line(line_id: int, body: LinePatch, user: User = Depends(require("payroll.manage")),
               db: Session = Depends(get_db)):
    """PAY-04: bonuses and deductions with notes on a draft run."""
    l = db.get(PayrollLine, line_id)
    if not l:
        raise not_found("Payroll line")
    r = _run(db, l.run_id)
    if r.status != "Draft":
        raise conflict("Approved payroll is locked", "locked")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(l, k, v if v is not None or k == "note" else 0)
    l.net = l.base - l.absence_deduction + l.commission + l.bonus - l.deductions
    db.commit()
    return line_out(db, l)


@router.post("/runs/{run_id}/approve")
def approve(run_id: int, user: User = Depends(require("payroll.approve")), db: Session = Depends(get_db)):
    r = _run(db, run_id)
    if r.status != "Draft":
        raise conflict("Only a draft run can be approved", "locked")
    if not r.lines:
        raise conflict("The run has no lines", "empty")
    r.status = "Approved"
    r.approved_by = user.id
    r.approved_at = utcnow()
    db.commit()
    return run_out(db, r)


@router.post("/runs/{run_id}/pay")
def pay(run_id: int, body: PayIn, user: User = Depends(require("payroll.manage")), db: Session = Depends(get_db)):
    r = _run(db, run_id)
    if r.status != "Approved":
        raise conflict("Only an approved run can be marked paid", "not_approved")
    if body.method not in PAYMENT_METHODS:
        raise http_error(422, "Unknown payment method", "validation", field="method")
    r.status = "Paid"
    r.paid_on = body.paid_on
    r.method = body.method
    db.commit()
    return run_out(db, r)


@router.get("/my")
def my_payslips(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """PAY-06: the employee's own payslips (approved or paid runs only)."""
    if not user.staff_id:
        return []
    rows = db.execute(select(PayrollLine, PayrollRun).join(PayrollRun, PayrollRun.id == PayrollLine.run_id)
                      .where(PayrollLine.staff_id == user.staff_id, PayrollRun.status != "Draft")
                      .order_by(PayrollRun.month.desc()))
    return [{**line_out(db, l), "month": r.month, "status": r.status} for l, r in rows]


@router.get("/lines/{line_id}/payslip")
def payslip(line_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    l = db.get(PayrollLine, line_id)
    if not l:
        raise not_found("Payslip")
    r = _run(db, l.run_id)
    if not can(user.role, "payroll.manage"):
        if l.staff_id != user.staff_id or r.status == "Draft":
            raise forbidden()
    log_event(db, "export", "payroll_lines", l.id, after={"format": "pdf", "name": "payslip"})
    db.commit()
    return file_response(payslip_pdf(db, l), "pdf", f"payslip-{r.month}-{l.staff_id}", inline=True)


@router.get("/lines/{line_id}/commission")
def commission_detail(line_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    l = db.get(PayrollLine, line_id)
    if not l:
        raise not_found("Payroll line")
    r = _run(db, l.run_id)
    if not can(user.role, "payroll.manage") and l.staff_id != user.staff_id:
        raise forbidden()
    first, last = month_bounds(r.month)
    total, detail = commission_for(db, l.staff_id, first, last)
    return {"total": total, "lines": [d.__dict__ | {"invoice_date": d.invoice_date.isoformat()} for d in detail]}
