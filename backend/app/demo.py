"""Demo data for a fresh test install. Every demo login gets a random one-time password (no default passwords)."""
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .bootstrap import seed_reference
from .models import (DENTAL, DERMA, Appointment, Expense, InventoryItem, Patient, Service, ServiceItem, Staff,
                     StockMovement, User)
from .security import hash_password, one_time_password
from .timeutil import to_utc


def seed(db: Session) -> list[str]:
    seed_reference(db)
    out = ["Demo logins (one-time passwords, must be changed at first sign-in):"]
    people = [
        ("Dr. Sara Haddad", "doctor", "dental", "Orthodontics", 120000, 40, "sara"),
        ("Dr. Omar Khalil", "doctor", "derma", "Dermatology", 130000, 35, "omar"),
        ("Lina Nasser", "nurse", "both", None, 60000, 0, "lina"),
        ("Rami Saleh", "receptionist", "both", None, 50000, 0, "rami"),
        ("Huda Ali", "finance", "both", None, 70000, 0, "huda"),
        ("Admin", "admin", "both", None, 0, 0, "admin"),
    ]
    staff = {}
    for name, role, scope, spec, salary, share, username in people:
        s = Staff(name=name, role=role, clinic_scope=scope, specialty=spec, salary=salary,
                  default_share_pct=share, hire_date=date.today() - timedelta(days=400), phone="0790000000")
        db.add(s)
        db.flush()
        staff[username] = s
        otp = one_time_password()
        db.add(User(username=username, role=role, clinic_scope=scope, staff_id=s.id,
                    password_hash=hash_password(otp), must_change_pw=True))
        out.append(f"  {username:<8} {role:<13} {otp}")

    gloves = InventoryItem(clinic_id=None, name="Nitrile gloves (box)", category="Consumables", unit="box",
                           reorder_level=5, unit_cost=650, supplier="MedSupply")
    composite = InventoryItem(clinic_id=DENTAL, name="Composite resin", category="Dental materials", unit="syringe",
                              reorder_level=3, unit_cost=2500, supplier="DentalPro",
                              expiry=date.today() + timedelta(days=20))
    botox = InventoryItem(clinic_id=DERMA, name="Botulinum toxin 100U", category="Injectables", unit="vial",
                          reorder_level=2, unit_cost=18000, supplier="AestheticCo",
                          expiry=date.today() + timedelta(days=120))
    db.add_all([gloves, composite, botox])
    db.flush()
    for item, qty in ((gloves, 20), (composite, 4), (botox, 6)):
        db.add(StockMovement(item_id=item.id, kind="Receive", qty=qty, reason="Opening stock"))

    svcs = [
        Service(clinic_id=DENTAL, name="Consultation", category="General", duration_min=20, price=2000),
        Service(clinic_id=DENTAL, name="Scaling & polishing", category="Hygiene", duration_min=40, price=4000),
        Service(clinic_id=DENTAL, name="Composite filling", category="Restorative", duration_min=45, price=6000,
                lab_cost=500),
        Service(clinic_id=DENTAL, name="Zirconia crown", category="Prosthetics", duration_min=60, price=25000,
                lab_cost=9000, share_pct=30),
        Service(clinic_id=DERMA, name="Dermatology consultation", category="General", duration_min=20, price=2500),
        Service(clinic_id=DERMA, name="Botox (per area)", category="Injectables", duration_min=30, price=15000,
                lab_cost=0),
        Service(clinic_id=DERMA, name="Chemical peel", category="Procedures", duration_min=45, price=8000),
    ]
    db.add_all(svcs)
    db.flush()
    db.add(ServiceItem(service_id=svcs[2].id, item_id=composite.id, qty_per_unit=1))
    db.add(ServiceItem(service_id=svcs[5].id, item_id=botox.id, qty_per_unit=0.25))

    pats = [
        Patient(name="Ahmad Yousef", phone="0791234567", dob=date(1988, 4, 2), gender="male", clinic_scope="dental",
                allergies="Penicillin"),
        Patient(name="Maya Fares", phone="0797654321", dob=date(1995, 9, 15), gender="female", clinic_scope="derma"),
        Patient(name="خالد العلي", phone="0795550000", dob=date(1979, 1, 20), gender="male", clinic_scope="both"),
    ]
    db.add_all(pats)
    db.flush()
    for p in pats:
        p.file_no = f"P-{p.id:06d}"
    today = date.today()
    tz = ZoneInfo("UTC")
    for i, (p, svc, doc, hour) in enumerate([(pats[0], svcs[0], staff["sara"], 10), (pats[1], svcs[4], staff["omar"], 11),
                                             (pats[2], svcs[1], staff["sara"], 12)]):
        start = to_utc(today, time(hour), tz)
        db.add(Appointment(patient_id=p.id, clinic_id=svc.clinic_id, doctor_id=doc.id, service_id=svc.id,
                           room=f"Room {i + 1}", start_at=start, end_at=start + timedelta(minutes=svc.duration_min),
                           status="Scheduled"))
    db.add(Expense(clinic_id=None, date=today.replace(day=1), category="Rent", description="Monthly rent",
                   amount=150000, paid_to="Landlord"))
    db.commit()
    return out
