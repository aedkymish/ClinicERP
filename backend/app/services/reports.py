"""Report calculations — REP-01..05 and dashboard figures. All amounts in minor units."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CLINIC_CODES, Expense, Invoice, Patient, Payment, PayrollLine, PayrollRun, Service, Staff, User
from .billing import commission_for, rnd, totals


def payments_in(db: Session, start: date, end: date, clinic_ids: set[int], received_by: int | None = None):
    q = (select(Payment, Invoice).join(Invoice, Invoice.id == Payment.invoice_id)
         .where(Payment.date >= start, Payment.date <= end, Invoice.clinic_id.in_(clinic_ids)))
    if received_by:
        q = q.where(Payment.received_by == received_by)
    return db.execute(q.order_by(Payment.date, Payment.id)).all()


def expenses_total(db: Session, start: date, end: date, clinic_ids: set[int], include_shared: bool) -> int:
    cond = Expense.clinic_id.in_(clinic_ids)
    if include_shared:
        cond = cond | Expense.clinic_id.is_(None)
    return db.scalar(select(func.coalesce(func.sum(Expense.amount), 0))
                     .where(Expense.date >= start, Expense.date <= end, cond))


def payroll_total(db: Session, start: date, end: date) -> int:
    """REP-02: actual payroll from approved/paid runs whose month starts inside the range."""
    months = []
    d = date(start.year, start.month, 1)
    while d <= end:
        if d >= start:
            months.append(f"{d.year:04d}-{d.month:02d}")
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    if not months:
        return 0
    return db.scalar(select(func.coalesce(func.sum(PayrollLine.net), 0)).join(PayrollRun)
                     .where(PayrollRun.month.in_(months), PayrollRun.status.in_(("Approved", "Paid"))))


def doctors(db: Session, clinic_ids: set[int]) -> list[Staff]:
    return list(db.scalars(select(Staff).where(Staff.role == "doctor").order_by(Staff.name)))


def summary(db: Session, start: date, end: date, clinic_ids: set[int], include_shared: bool) -> dict:
    pays = payments_in(db, start, end, clinic_ids)
    collected = sum(p.amount for p, _ in pays if p.kind == "Payment")
    refunds = sum(p.amount for p, _ in pays if p.kind == "Refund")
    expenses = expenses_total(db, start, end, clinic_ids, include_shared)
    payroll = payroll_total(db, start, end) if include_shared else 0
    commission = sum(commission_for(db, d.id, start, end, clinic_ids)[0] for d in doctors(db, clinic_ids))
    return {
        "revenue_collected": collected, "refunds": refunds, "net_revenue": collected - refunds,
        "expenses": expenses, "payroll": payroll, "doctor_commission": commission,
        # payroll nets already include commission, so it is not subtracted twice
        "net_profit": collected - refunds - expenses - payroll,
    }


def revenue(db: Session, start: date, end: date, clinic_ids: set[int]) -> dict:
    by_clinic: dict[str, int] = defaultdict(int)
    by_doctor: dict[str, int] = defaultdict(int)
    by_method: dict[str, int] = defaultdict(int)
    by_service: dict[str, Decimal] = defaultdict(Decimal)
    cache: dict[int, tuple] = {}
    for p, inv in payments_in(db, start, end, clinic_ids):
        sign = 1 if p.kind == "Payment" else -1
        amt = sign * p.amount
        by_clinic[CLINIC_CODES[inv.clinic_id]] += amt
        doc = db.get(Staff, inv.doctor_id) if inv.doctor_id else None
        by_doctor[doc.name if doc else "—"] += amt
        by_method[p.method] += amt
        if inv.id not in cache:
            cache[inv.id] = (inv, totals(inv))
        _, t = cache[inv.id]
        if t.total > 0:
            # allocate the payment to lines in proportion to each line's share of the total
            for line, c in zip(inv.lines, t.lines, strict=True):
                svc = db.get(Service, line.service_id) if line.service_id else None
                by_service[svc.name if svc else line.description] += Decimal(amt) * (c.net + c.vat) / t.total

    def rows(d, key):
        return [{key: k, "amount": int(v)} for k, v in sorted(d.items(), key=lambda kv: -kv[1])]

    return {
        "by_clinic": rows(by_clinic, "clinic"), "by_doctor": rows(by_doctor, "doctor"),
        "by_method": rows(by_method, "method"),
        "by_service": [{"service": k, "amount": rnd(v)} for k, v in sorted(by_service.items(), key=lambda kv: -kv[1])],
    }


def commission(db: Session, start: date, end: date, clinic_ids: set[int], doctor_id: int | None = None) -> dict:
    docs = [db.get(Staff, doctor_id)] if doctor_id else doctors(db, clinic_ids)
    per_doctor, lines = [], []
    for d in docs:
        if not d:
            continue
        total, detail = commission_for(db, d.id, start, end, clinic_ids)
        if not total and not detail and not doctor_id:
            continue
        per_doctor.append({"doctor_id": d.id, "doctor": d.name, "commission": total, "lines": len(detail)})
        for x in detail:
            p = db.get(Patient, x.patient_id)
            lines.append({"doctor": d.name, "invoice": x.invoice_number, "date": x.invoice_date.isoformat(),
                          "patient": p.name if p else "", "description": x.description, "qty": x.qty,
                          "unit_price": x.unit_price, "discount": x.discount, "lab_cost": x.lab_cost,
                          "share_pct": x.share_pct, "base": x.base, "paid_pct": round(x.paid_fraction * 100, 1),
                          "commission": x.commission})
    return {"per_doctor": per_doctor, "lines": lines, "total": sum(r["commission"] for r in per_doctor)}


def cash(db: Session, start: date, end: date, clinic_ids: set[int], user_id: int | None = None) -> dict:
    """REP-04: receptionist close-out — what each user took in, by method."""
    per: dict[tuple, dict] = {}
    rows = []
    for p, inv in payments_in(db, start, end, clinic_ids, user_id):
        u = db.get(User, p.received_by) if p.received_by else None
        uname = (u.staff.name if u and u.staff else u.username) if u else "—"
        key = (p.date.isoformat(), uname, p.method)
        rec = per.setdefault(key, {"date": key[0], "user": uname, "method": p.method, "received": 0, "refunded": 0})
        rec["received" if p.kind == "Payment" else "refunded"] += p.amount
        pt = db.get(Patient, inv.patient_id)
        rows.append({"date": p.date.isoformat(), "user": uname, "invoice": inv.number, "patient": pt.name if pt else "",
                     "method": p.method, "kind": p.kind, "amount": p.amount if p.kind == "Payment" else -p.amount})
    totals_ = list(per.values())
    for t in totals_:
        t["net"] = t["received"] - t["refunded"]
    return {"totals": totals_, "rows": rows, "net": sum(t["net"] for t in totals_)}


def aging(db: Session, as_of: date, clinic_ids: set[int]) -> dict:
    """REP-05: outstanding balances by age of the invoice."""
    buckets = {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    rows = []
    q = select(Invoice).where(Invoice.status == "Posted", Invoice.clinic_id.in_(clinic_ids), Invoice.date <= as_of)
    for inv in db.scalars(q.order_by(Invoice.date)):
        bal = totals(inv).balance
        if bal <= 0:
            continue
        age = (as_of - inv.date).days
        b = "0-30" if age <= 30 else "31-60" if age <= 60 else "61-90" if age <= 90 else "90+"
        buckets[b] += bal
        p = db.get(Patient, inv.patient_id)
        rows.append({"invoice": inv.number, "date": inv.date.isoformat(), "patient": p.name if p else "",
                     "phone": p.phone if p else "", "clinic": CLINIC_CODES[inv.clinic_id], "age_days": age,
                     "bucket": b, "balance": bal})
    return {"buckets": buckets, "rows": rows, "total": sum(buckets.values())}


def expenses_by_category(db: Session, start: date, end: date, clinic_ids: set[int], include_shared: bool) -> dict:
    cond = Expense.clinic_id.in_(clinic_ids)
    if include_shared:
        cond = cond | Expense.clinic_id.is_(None)
    rows = db.execute(select(Expense.category, func.sum(Expense.amount), func.count())
                      .where(Expense.date >= start, Expense.date <= end, cond)
                      .group_by(Expense.category).order_by(func.sum(Expense.amount).desc()))
    data = [{"category": c, "amount": a, "count": n} for c, a, n in rows]
    return {"by_category": data, "total": sum(r["amount"] for r in data)}


def monthly_revenue(db: Session, months: int, today: date, clinic_ids: set[int]) -> list[dict]:
    """Dashboard chart: last N months of net collections per clinic."""
    first = date(today.year, today.month, 1)
    for _ in range(months - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    out: dict[str, dict] = {}
    d = first
    while d <= today:
        out[f"{d.year:04d}-{d.month:02d}"] = {CLINIC_CODES[c]: 0 for c in sorted(clinic_ids)}
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    for p, inv in payments_in(db, first, today, clinic_ids):
        key = f"{p.date.year:04d}-{p.date.month:02d}"
        out[key][CLINIC_CODES[inv.clinic_id]] += p.amount if p.kind == "Payment" else -p.amount
    return [{"month": k, **v} for k, v in out.items()]


def outstanding(db: Session, clinic_ids: set[int]) -> int:
    q = select(Invoice).where(Invoice.status == "Posted", Invoice.clinic_id.in_(clinic_ids))
    return sum(max(totals(i).balance, 0) for i in db.scalars(q))
