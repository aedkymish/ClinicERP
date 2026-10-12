"""Import of a v1 JSON backup (`clinic-erp-backup-<date>.json`) — section 2.5, SET-03.

The v1 file came from the single-page `ClinicERP.html`; its exact key names are not part of the SRS,
so the importer accepts the common spellings (camelCase / snake_case, a top-level ``data`` wrapper,
amounts as decimals). Everything runs in one transaction; a dry run rolls it back and returns the
report.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..db import utcnow
from ..models import (APPT_STATUSES, CLINIC_IDS, DENTAL, TOOTH_CONDITIONS, Appointment, Expense, InventoryItem,
                      Invoice, InvoiceLine, Patient, Payment, Service, Setting, Staff, StockMovement, ToothEntry, User,
                      Visit)
from .billing import next_invoice_number, rnd

ALIASES = {
    "patients": ("patients", "patient"),
    "staff": ("staff", "employees", "users"),
    "services": ("services", "priceList", "price_list", "prices"),
    "appointments": ("appointments", "appts", "bookings"),
    "visits": ("visits", "notes", "clinicalNotes", "clinical_notes"),
    "invoices": ("invoices", "bills", "billing"),
    "expenses": ("expenses",),
    "inventory": ("inventory", "stock", "items"),
    "settings": ("settings", "config"),
}
ROLE_MAP = {"admin": "admin", "doctor": "doctor", "nurse": "nurse", "assistant": "assistant",
            "receptionist": "receptionist", "reception": "receptionist", "finance": "finance",
            "accountant": "finance"}


@dataclass
class Report:
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    filled_lines: int = 0

    def add(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


def pick(rec: dict, *names: str, default: Any = None) -> Any:
    for n in names:
        if n in rec and rec[n] not in (None, ""):
            return rec[n]
    return default


def money(v: Any) -> int:
    """v1 stored plain decimal amounts; convert to minor units."""
    if v in (None, ""):
        return 0
    try:
        return rnd(Decimal(str(v)) * 100)
    except Exception:
        return 0


def as_date(v: Any) -> date | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 10**11 else v).date()
    s = str(v)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(str(v)[:10], fmt).date()
            except ValueError:
                pass
    return None


def clinic_code(v: Any, default: str = "both") -> str:
    s = str(v or "").lower()
    if s.startswith("dent"):
        return "dental"
    if s.startswith("derm") or s.startswith("skin") or s.startswith("aesth"):
        return "derma"
    return default


def collection(data: dict, key: str) -> list[dict]:
    for k in ALIASES[key]:
        v = data.get(k)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict) and key != "settings":
            return [dict(x, id=x.get("id", i)) for i, x in v.items() if isinstance(x, dict)]
    return []


def run_import(db: Session, payload: dict, dry_run: bool, user_id: int | None) -> Report:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    rep = Report()
    ids: dict[str, dict[Any, int]] = {k: {} for k in ALIASES}

    # settings
    st = next((data[k] for k in ALIASES["settings"] if isinstance(data.get(k), dict)), {})
    for src, dst in (("currency", "currency"), ("vat", "vat_rate"), ("vatRate", "vat_rate"),
                     ("timezone", "time_zone"), ("timeZone", "time_zone")):
        if st.get(src) not in (None, ""):
            row = db.scalar(select(Setting).where(Setting.key == dst)) or Setting(key=dst)
            row.value = str(st[src])
            db.add(row)
            rep.add("settings")

    # staff → staff rows; logins without password (Admin issues one-time passwords)
    for s in collection(data, "staff"):
        role = ROLE_MAP.get(str(pick(s, "role", default="")).lower())
        name = pick(s, "name", "fullName", "full_name")
        if not name:
            rep.warnings.append(f"Staff without a name skipped: {s.get('id')}")
            continue
        if not role:
            rep.warnings.append(f"Staff '{name}' had role '{s.get('role')}' (removed in v2) — imported as assistant "
                                "without login; use attendance self-service after Admin creates a login")
        staff = Staff(name=name, role=role or "assistant", clinic_scope=clinic_code(pick(s, "clinic")),
                      specialty=pick(s, "specialty"), phone=pick(s, "phone"), email=pick(s, "email"),
                      hire_date=as_date(pick(s, "hireDate", "hire_date")),
                      salary=money(pick(s, "salary", "monthlySalary", default=0)),
                      default_share_pct=float(pick(s, "share", "sharePct", "pct", "commission", default=0) or 0),
                      active=bool(pick(s, "active", default=True)))
        db.add(staff)
        db.flush()
        ids["staff"][s.get("id")] = staff.id
        rep.add("staff")
        username = str(pick(s, "username", "login", default="")).strip().lower()
        if role and username and not db.scalar(select(User).where(User.username == username)):
            db.add(User(username=username, role=role, clinic_scope=staff.clinic_scope, staff_id=staff.id,
                        password_hash=None, must_change_pw=True))
            rep.add("logins (no password)")

    # inventory
    for it in collection(data, "inventory"):
        code = clinic_code(pick(it, "clinic"), "shared")
        item = InventoryItem(clinic_id=CLINIC_IDS.get(code), name=pick(it, "name", default="Item"),
                             category=pick(it, "category"), unit=pick(it, "unit", default="pcs"),
                             reorder_level=float(pick(it, "reorder", "reorderLevel", "min", default=0) or 0),
                             unit_cost=money(pick(it, "cost", "unitCost", "unit_cost", default=0)),
                             supplier=pick(it, "supplier"), expiry=as_date(pick(it, "expiry", "expiryDate")))
        db.add(item)
        db.flush()
        ids["inventory"][it.get("id")] = item.id
        qty = float(pick(it, "qty", "quantity", "stock", default=0) or 0)
        if qty:
            db.add(StockMovement(item_id=item.id, kind="Adjust", qty=qty, reason="Imported from v1", user_id=user_id))
        rep.add("inventory")

    # services
    for s in collection(data, "services"):
        code = clinic_code(pick(s, "clinic"), "dental")
        share = pick(s, "pct", "share", "sharePct")
        svc = Service(clinic_id=CLINIC_IDS[code], name=pick(s, "name", default="Service"), category=pick(s, "category"),
                      duration_min=int(pick(s, "duration", "durationMin", default=30) or 30),
                      price=money(pick(s, "price", default=0)), vat_applies=bool(pick(s, "vat", default=False)),
                      share_pct=float(share) if share not in (None, "") else None,
                      lab_cost=money(pick(s, "lab", "labCost", default=0)), active=bool(pick(s, "active", default=True)))
        db.add(svc)
        db.flush()
        ids["services"][s.get("id")] = svc.id
        rep.add("services")

    # patients (+ v1 tooth chart, which only stored the current state)
    for p in collection(data, "patients"):
        name, phone = pick(p, "name", "fullName", "full_name"), pick(p, "phone", "mobile", default="")
        if not name:
            rep.warnings.append(f"Patient without a name skipped: {p.get('id')}")
            continue
        if not phone:
            rep.warnings.append(f"Patient '{name}' has no phone; stored as '-'")
        pat = Patient(name=name, phone=phone or "-", email=pick(p, "email"), dob=as_date(pick(p, "dob", "birthDate")),
                      gender=(str(pick(p, "gender", default="")).lower() or None) if str(pick(p, "gender", default="")).lower() in ("male", "female", "other") else None,
                      address=pick(p, "address"), insurance=pick(p, "insurance"), allergies=pick(p, "allergies"),
                      history=pick(p, "history", "medicalHistory"), notes=pick(p, "notes"),
                      clinic_scope=clinic_code(pick(p, "clinic")), archived=bool(pick(p, "archived", default=False)))
        db.add(pat)
        db.flush()
        pat.file_no = f"P-{pat.id:06d}"
        ids["patients"][p.get("id")] = pat.id
        rep.add("patients")
        chart = pick(p, "teeth", "chart", "dentalChart")
        if isinstance(chart, dict):
            for tooth, cond in chart.items():
                c = cond.get("condition") if isinstance(cond, dict) else cond
                c = next((x for x in TOOTH_CONDITIONS if x.lower() == str(c).lower()), None)
                if str(tooth).isdigit() and 11 <= int(tooth) <= 85 and c:
                    db.add(ToothEntry(patient_id=pat.id, tooth=int(tooth), condition=c, note="Imported from v1",
                                      user_id=user_id, at=utcnow()))
                    rep.add("tooth entries")

    def ref(kind: str, rec: dict, *keys: str) -> int | None:
        return ids[kind].get(pick(rec, *keys))

    # appointments
    for a in collection(data, "appointments"):
        pid = ref("patients", a, "patientId", "patient_id", "patient")
        d = as_date(pick(a, "date"))
        if not pid or not d:
            rep.warnings.append(f"Appointment {a.get('id')} skipped (unknown patient or date)")
            continue
        hh, mm = (str(pick(a, "time", default="09:00")) + ":00").split(":")[:2]
        start = datetime(d.year, d.month, d.day, int(hh or 9), int(mm or 0))
        dur = int(pick(a, "duration", default=30) or 30)
        status = next((s for s in APPT_STATUSES if s.lower() == str(pick(a, "status", default="")).lower()), "Scheduled")
        svc_id = ref("services", a, "serviceId", "service_id", "service")
        clinic = CLINIC_IDS[clinic_code(pick(a, "clinic"), "dental")]
        if svc_id:
            clinic = db.get(Service, svc_id).clinic_id
        appt = Appointment(patient_id=pid, clinic_id=clinic, doctor_id=ref("staff", a, "doctorId", "doctor_id", "doctor"),
                           service_id=svc_id, room=pick(a, "room"), start_at=start,
                           end_at=start + timedelta(minutes=dur), status=status, notes=pick(a, "notes"))
        db.add(appt)
        db.flush()
        ids["appointments"][a.get("id")] = appt.id
        rep.add("appointments")

    # clinical notes — historical, so imported already locked
    for v in collection(data, "visits"):
        pid = ref("patients", v, "patientId", "patient_id", "patient")
        if not pid:
            rep.warnings.append(f"Note {v.get('id')} skipped (unknown patient)")
            continue
        d = as_date(pick(v, "date")) or date.today()
        visit = Visit(patient_id=pid, clinic_id=CLINIC_IDS[clinic_code(pick(v, "clinic"), "dental")],
                      doctor_id=ref("staff", v, "doctorId", "doctor_id", "doctor"),
                      appointment_id=ref("appointments", v, "appointmentId", "appointment_id"), date=d,
                      complaint=pick(v, "complaint"), diagnosis=pick(v, "diagnosis"),
                      treatment=pick(v, "treatment", "plan"), prescription=pick(v, "prescription", "rx"),
                      teeth=",".join(map(str, pick(v, "teeth", default=[]))) if isinstance(pick(v, "teeth"), list) else pick(v, "teeth"),
                      skin_type=pick(v, "skinType", "skin_type", "fitzpatrick"), area=pick(v, "area"),
                      follow_up=as_date(pick(v, "followUp", "follow_up")), notes=pick(v, "notes"), locked_at=utcnow())
        db.add(visit)
        rep.add("clinical notes")

    # invoices with payments; v1 lines had empty pct/lab → fill from current service settings (2.5)
    for inv_rec in sorted(collection(data, "invoices"), key=lambda r: str(pick(r, "date", default=""))):
        pid = ref("patients", inv_rec, "patientId", "patient_id", "patient")
        if not pid:
            rep.warnings.append(f"Invoice {inv_rec.get('number') or inv_rec.get('id')} skipped (unknown patient)")
            continue
        d = as_date(pick(inv_rec, "date")) or date.today()
        clinic = CLINIC_IDS[clinic_code(pick(inv_rec, "clinic"), "dental")]
        doctor_id = ref("staff", inv_rec, "doctorId", "doctor_id", "doctor")
        disc = pick(inv_rec, "discount", default=0) or 0
        dtype = "percent" if str(pick(inv_rec, "discountType", default="")).lower() in ("percent", "%", "pct") else "amount"
        inv = Invoice(number=next_invoice_number(db, clinic, d), clinic_id=clinic, patient_id=pid, doctor_id=doctor_id,
                      date=d, discount_type=dtype, discount_value=float(disc) if dtype == "percent" else money(disc),
                      vat_rate=float(pick(inv_rec, "vatRate", "vat", default=0) or 0),
                      notes=f"v1 number {pick(inv_rec, 'number', 'no', default=inv_rec.get('id'))}", status="Draft")
        db.add(inv)
        db.flush()
        doctor = db.get(Staff, doctor_id) if doctor_id else None
        for li in pick(inv_rec, "lines", "items", default=[]) or []:
            svc_id = ref("services", li, "serviceId", "service_id", "service")
            svc = db.get(Service, svc_id) if svc_id else None
            pct, lab = pick(li, "pct", "share"), pick(li, "lab", "labCost")
            filled = pct in (None, "") or lab in (None, "")
            line = InvoiceLine(service_id=svc_id, description=pick(li, "description", "name", default=svc.name if svc else "Item"),
                               qty=float(pick(li, "qty", "quantity", default=1) or 1),
                               unit_price=money(pick(li, "price", "unitPrice", default=0)),
                               share_pct=float(pct) if pct not in (None, "") else (
                                   svc.share_pct if svc and svc.share_pct is not None else (doctor.default_share_pct if doctor else 0)),
                               lab_cost=money(lab) if lab not in (None, "") else (svc.lab_cost if svc else 0),
                               vat_applies=bool(svc.vat_applies) if svc else False)
            inv.lines.append(line)
            if filled:
                rep.filled_lines += 1
        db.flush()
        pays = pick(inv_rec, "payments", default=[]) or []
        for pm in pays:
            amt = money(pick(pm, "amount", default=0))
            if amt > 0:
                db.add(Payment(invoice_id=inv.id, date=as_date(pick(pm, "date")) or d, amount=amt,
                               method=str(pick(pm, "method", default="Cash")).capitalize() if str(pick(pm, "method", default="Cash")).capitalize() in ("Cash", "Card", "Cheque", "Other") else "Other",
                               received_by=user_id, kind="Payment"))
                rep.add("payments")
        if pays or str(pick(inv_rec, "status", default="")).lower() in ("paid", "posted", "printed"):
            inv.status, inv.posted_at = "Posted", utcnow()  # historical: no stock deduction
        rep.add("invoices")
    if rep.filled_lines:
        log_event(db, "import_fill", "invoice_lines", None,
                  after={"lines": rep.filled_lines, "note": "v1 pct/lab were empty; filled from current service settings"})

    for e in collection(data, "expenses"):
        d = as_date(pick(e, "date"))
        amt = money(pick(e, "amount", default=0))
        if not d or amt <= 0:
            rep.warnings.append(f"Expense {e.get('id')} skipped (no date or amount)")
            continue
        code = clinic_code(pick(e, "clinic"), "shared")
        db.add(Expense(clinic_id=CLINIC_IDS.get(code), date=d, category=pick(e, "category", default="Other"),
                       description=pick(e, "description", "desc"), amount=amt, paid_to=pick(e, "paidTo", "paid_to", "vendor")))
        rep.add("expenses")

    log_event(db, "import_v1", "settings", None, after={"dry_run": dry_run, "counts": rep.counts,
                                                        "warnings": len(rep.warnings)})
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return rep


__all__ = ["run_import", "Report", "DENTAL"]
