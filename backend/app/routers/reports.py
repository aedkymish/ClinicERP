"""Reports — REP-01..06 — and the role-aware dashboard (DASH-01..04)."""
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import clinic_tz, forbidden, get_current_user, view_clinics
from ..models import Appointment, Patient, User
from ..permissions import can
from ..routers.appointments import out as appt_out
from ..routers.inventory import list_items
from ..services import reports as R
from ..services.billing import commission_for
from ..services.export import export
from ..services.pdf import Fmt
from ..timeutil import day_bounds_utc, local_today

router = APIRouter(tags=["reports"])
ReportName = Literal["summary", "revenue", "commission", "cash", "aging", "expenses"]


def _check(user: User, name: str) -> None:
    if can(user.role, "reports.full"):
        return
    if name == "commission" and can(user.role, "reports.commission_own"):
        return
    if name == "cash" and can(user.role, "reports.cash"):
        return
    raise forbidden("You cannot run this report")


@router.get("/reports/{name}")
def report(
    name: ReportName, from_: date | None = Query(None, alias="from"), to: date | None = None,
    clinic: str | None = None, doctor: int | None = None, user_id: int | None = None,
    format: Literal["csv", "xlsx", "pdf"] | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _check(user, name)
    today = local_today(clinic_tz(db))
    to = to or today
    from_ = from_ or (to if name == "cash" else to.replace(day=1))
    ids = view_clinics(user, clinic)
    include_shared = clinic in (None, "", "both") and user.clinic_scope == "both"
    f = Fmt(db)
    period = f"{from_.isoformat()} – {to.isoformat()}"
    result: dict = {"name": name, "from": from_.isoformat(), "to": to.isoformat(), "clinics": sorted(ids)}

    if name == "summary":
        k = R.summary(db, from_, to, ids, include_shared)
        rev = R.revenue(db, from_, to, ids)
        exp = R.expenses_by_category(db, from_, to, ids, include_shared)
        result |= {"kpis": k, **rev, "expenses_by_category": exp["by_category"]}
        rows = [{"metric": key.replace("_", " ").capitalize(), "amount": f.money(v)} for key, v in k.items()]
        cols = [("metric", "Metric"), ("amount", "Amount")]
        summary_rows = []
    elif name == "revenue":
        rev = R.revenue(db, from_, to, ids)
        result |= rev
        rows = [{"group": g, "name": r.get(g) or r.get(g.replace("by_", "")), "amount": f.money(r["amount"])}
                for g in ("by_clinic", "by_doctor", "by_method", "by_service") for r in rev[g]]
        rows = [{"group": r["group"].replace("by_", "").capitalize(), "name": r["name"], "amount": r["amount"]}
                for r in rows]
        cols = [("group", "Breakdown"), ("name", "Name"), ("amount", "Amount")]
        summary_rows = []
    elif name == "commission":
        if not can(user.role, "reports.full"):
            doctor = user.staff_id  # doctors see their own commission only
            if not doctor:
                raise forbidden()
        c = R.commission(db, from_, to, ids, doctor)
        result |= c
        rows = [{**l, "unit_price": f.money(l["unit_price"]), "discount": f.money(l["discount"]),
                 "lab_cost": f.money(l["lab_cost"]), "base": f.money(l["base"]),
                 "commission": f.money(l["commission"])} for l in c["lines"]]
        cols = [("doctor", "Doctor"), ("invoice", "Invoice"), ("date", "Date"), ("patient", "Patient"),
                ("description", "Service"), ("qty", "Qty"), ("unit_price", "Price"), ("discount", "Discount"),
                ("lab_cost", "Lab/unit"), ("share_pct", "Share %"), ("paid_pct", "Paid %"),
                ("commission", "Commission")]
        summary_rows = [(r["doctor"], f.money(r["commission"])) for r in c["per_doctor"]] + \
            [("Total", f.money(c["total"]))]
    elif name == "cash":
        if not can(user.role, "reports.full"):
            user_id = user.id  # receptionists close out their own cash
        c = R.cash(db, from_, to, ids, user_id)
        result |= c
        rows = [{**r, "amount": f.money(r["amount"])} for r in c["rows"]]
        cols = [("date", "Date"), ("user", "Received by"), ("invoice", "Invoice"), ("patient", "Patient"),
                ("method", "Method"), ("kind", "Type"), ("amount", "Amount")]
        summary_rows = [(f'{t["date"]} {t["user"]} {t["method"]}', f.money(t["net"])) for t in c["totals"]] + \
            [("Net", f.money(c["net"]))]
    elif name == "aging":
        a = R.aging(db, to, ids)
        result |= a
        rows = [{**r, "balance": f.money(r["balance"])} for r in a["rows"]]
        cols = [("invoice", "Invoice"), ("date", "Date"), ("patient", "Patient"), ("phone", "Phone"),
                ("clinic", "Clinic"), ("age_days", "Age (days)"), ("bucket", "Bucket"), ("balance", "Balance")]
        summary_rows = [(k + " days", f.money(v)) for k, v in a["buckets"].items()] + [("Total", f.money(a["total"]))]
    else:  # expenses
        e = R.expenses_by_category(db, from_, to, ids, include_shared)
        result |= e
        rows = [{**r, "amount": f.money(r["amount"])} for r in e["by_category"]]
        cols = [("category", "Category"), ("count", "Entries"), ("amount", "Amount")]
        summary_rows = [("Total", f.money(e["total"]))]

    if format:
        title = f"{name.capitalize()} report — {period}"
        return export(db, rows, cols, format, f"{name}-{from_}-{to}", "reports", title, summary_rows)
    return result


@router.get("/dashboard")
def dashboard(clinic: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tz = clinic_tz(db)
    today = local_today(tz)
    ids = view_clinics(user, clinic)
    data: dict = {"today": today.isoformat(), "role": user.role}
    data["total_patients"] = db.scalar(select(func.count()).select_from(Patient).where(Patient.archived.is_(False)))
    if can(user.role, "appointments.read"):
        lo, hi = day_bounds_utc(today, 1, tz)
        q = select(Appointment).where(Appointment.clinic_id.in_(ids), Appointment.start_at >= lo,
                                      Appointment.start_at < hi).order_by(Appointment.start_at)
        if user.role == "doctor" and user.staff_id:
            q = q.where(Appointment.doctor_id == user.staff_id)  # DASH-03: own schedule
        data["appointments"] = [appt_out(db, a, tz) for a in db.scalars(q)]
    if can(user.role, "inventory.read"):
        items = list_items(db, user, clinic)
        data["low_stock"] = [i for i in items if i["low"]]
        data["expiring"] = [i for i in items if i["expiring"]]  # DASH-04
    if can(user.role, "visits.read"):
        from .visits import follow_ups

        data["follow_ups"] = follow_ups(0, clinic, user, db)
    if can(user.role, "reports.full"):
        first = today.replace(day=1)
        include_shared = clinic in (None, "", "both") and user.clinic_scope == "both"
        k = R.summary(db, first, today, ids, include_shared)
        data["finance"] = {
            "mtd_revenue": k["net_revenue"], "mtd_expenses": k["expenses"],
            "outstanding": R.outstanding(db, ids), "chart": R.monthly_revenue(db, 6, today, ids),
        }
    if user.role == "doctor" and user.staff_id:
        data["mtd_commission"] = commission_for(db, user.staff_id, today.replace(day=1), today, ids)[0]
    if user.role == "receptionist":
        c = R.cash(db, today, today, ids, user.id)
        data["cash_today"] = c["net"]
    return data


__all__ = ["router", "timedelta"]
