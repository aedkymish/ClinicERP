"""Monthly payroll calculation — PAY-01..04."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import settings_map
from ..models import Attendance, PayrollLine, PayrollRun, Staff
from ..timeutil import month_bounds
from .billing import commission_for, rnd

DEDUCTED = ("Absent", "Unpaid leave")


def absence_days(db: Session, staff_id: int, month: str) -> int:
    first, last = month_bounds(month)
    return len(db.scalars(select(Attendance.id).where(
        Attendance.staff_id == staff_id, Attendance.date >= first, Attendance.date <= last,
        Attendance.status.in_(DEDUCTED))).all())


def calc_line(db: Session, line: PayrollLine, month: str) -> None:
    """(Re)compute base, absence deduction, commission and net for a draft line (PAY-02..04)."""
    staff = db.get(Staff, line.staff_id)
    work_days = int(settings_map(db)["work_days"] or 26) or 26
    first, last = month_bounds(month)
    line.base = staff.salary
    line.absence_days = absence_days(db, staff.id, month)
    line.absence_deduction = min(line.base, rnd(Decimal(staff.salary) / work_days * Decimal(line.absence_days)))
    line.commission = commission_for(db, staff.id, first, last)[0] if staff.role == "doctor" else 0
    line.net = line.base - line.absence_deduction + line.commission + line.bonus - line.deductions


def generate(db: Session, run: PayrollRun) -> None:
    """One line per active employee (PAY-01); existing bonus/deductions/notes are kept on recalculation."""
    existing = {l.staff_id: l for l in run.lines}
    for staff in db.scalars(select(Staff).where(Staff.active.is_(True)).order_by(Staff.name)):
        line = existing.get(staff.id)
        if not line:
            line = PayrollLine(run_id=run.id, staff_id=staff.id, bonus=0, deductions=0)
            db.add(line)
            run.lines.append(line)
        calc_line(db, line, run.month)
