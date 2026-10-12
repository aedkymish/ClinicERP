"""SQLAlchemy models — SRS section 4. Money columns are integer minor units (cents)."""
import datetime as dt
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, TimestampMixin, utcnow

ROLES = ("admin", "doctor", "nurse", "assistant", "receptionist", "finance")
SCOPES = ("dental", "derma", "both")
DENTAL, DERMA = 1, 2
CLINIC_IDS = {"dental": DENTAL, "derma": DERMA}
CLINIC_CODES = {v: k for k, v in CLINIC_IDS.items()}

APPT_STATUSES = ("Scheduled", "Confirmed", "Checked-in", "In progress", "Completed", "Cancelled", "No-show")
APPT_INACTIVE = ("Cancelled", "No-show")
TOOTH_CONDITIONS = (
    "Healthy", "Caries", "Filling", "Crown", "Root canal", "Implant", "Missing", "Planned extraction",
)
INVOICE_STATUSES = ("Draft", "Posted", "Void")
PAYMENT_METHODS = ("Cash", "Card", "Bank transfer", "Cheque", "Other")
MOVEMENT_KINDS = ("Receive", "Use", "Adjust", "Auto")
ATT_STATUSES = ("Present", "Late", "Absent", "Paid leave", "Unpaid leave", "Day off")
PAYROLL_STATUSES = ("Draft", "Approved", "Paid")


class Clinic(TimestampMixin, Base):
    __tablename__ = "clinics"
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    invoice_prefix: Mapped[str] = mapped_column(String(5))


class Staff(TimestampMixin, Base):
    __tablename__ = "staff"
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    clinic_scope: Mapped[str] = mapped_column(String(10), default="both")
    specialty: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(120))
    hire_date: Mapped[dt.date | None] = mapped_column(Date)
    salary: Mapped[int] = mapped_column(Integer, default=0)
    default_share_pct: Mapped[float] = mapped_column(Float, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("clinic_scope in ('dental','derma','both')", name="ck_staff_scope"),)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    clinic_scope: Mapped[str] = mapped_column(String(10), default="both")
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), unique=True)
    must_change_pw: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(5), default="en")
    staff: Mapped[Staff | None] = relationship(foreign_keys=[staff_id])
    __table_args__ = (
        CheckConstraint(
            "role in ('admin','doctor','nurse','assistant','receptionist','finance')", name="ck_users_role"
        ),
        CheckConstraint("clinic_scope in ('dental','derma','both')", name="ck_users_scope"),
    )


class UserSession(Base):
    """Server-side session record: enables logout revocation and the 30-minute idle timeout (AUTH-04)."""

    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    ip: Mapped[str | None] = mapped_column(String(64))


class Patient(TimestampMixin, Base):
    __tablename__ = "patients"
    file_no: Mapped[str | None] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    phone: Mapped[str] = mapped_column(String(40), index=True)
    email: Mapped[str | None] = mapped_column(String(120))
    dob: Mapped[dt.date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(Text)
    insurance: Mapped[str | None] = mapped_column(String(160))
    allergies: Mapped[str | None] = mapped_column(Text)
    history: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    # Which clinic(s) the patient belongs to — drives clinic scope and the dental-chart tab.
    clinic_scope: Mapped[str] = mapped_column(String(10), default="both")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    __table_args__ = ({"sqlite_autoincrement": True},)  # ids (and file numbers) are never reused


class PatientFile(TimestampMixin, Base):
    __tablename__ = "patient_files"
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(500))
    __table_args__ = (CheckConstraint("size <= 10485760", name="ck_file_size"),)


class Service(TimestampMixin, Base):
    __tablename__ = "services"
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(80))
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    price: Mapped[int] = mapped_column(Integer, default=0)
    vat_applies: Mapped[bool] = mapped_column(Boolean, default=False)
    share_pct: Mapped[float | None] = mapped_column(Float)  # NULL = doctor's default
    lab_cost: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    items: Mapped[list["ServiceItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class InventoryItem(TimestampMixin, Base):
    __tablename__ = "inventory_items"
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"), index=True)  # NULL = shared
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(80))
    unit: Mapped[str] = mapped_column(String(30), default="pcs")
    reorder_level: Mapped[float] = mapped_column(Float, default=0)
    unit_cost: Mapped[int] = mapped_column(Integer, default=0)
    supplier: Mapped[str | None] = mapped_column(String(160))
    expiry: Mapped[dt.date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ServiceItem(TimestampMixin, Base):
    __tablename__ = "service_items"
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"))
    qty_per_unit: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("service_id", "item_id"),)


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"))
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))
    room: Mapped[str | None] = mapped_column(String(40))
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="Scheduled")
    notes: Mapped[str | None] = mapped_column(Text)
    override_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("end_at > start_at", name="ck_appt_range"),)


class AppointmentStatusLog(TimestampMixin, Base):
    __tablename__ = "appointment_status_log"
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Visit(TimestampMixin, Base):
    __tablename__ = "visits"
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"))
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    complaint: Mapped[str | None] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    treatment: Mapped[str | None] = mapped_column(Text)
    prescription: Mapped[str | None] = mapped_column(Text)
    teeth: Mapped[str | None] = mapped_column(String(200))  # comma-separated FDI numbers
    skin_type: Mapped[str | None] = mapped_column(String(4))  # Fitzpatrick I–VI
    area: Mapped[str | None] = mapped_column(String(160))
    follow_up: Mapped[dt.date | None] = mapped_column(Date, index=True)
    follow_up_done: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime] = mapped_column(DateTime)


class VisitAddendum(TimestampMixin, Base):
    __tablename__ = "visit_addenda"
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ToothEntry(TimestampMixin, Base):
    __tablename__ = "tooth_entries"
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    tooth: Mapped[int] = mapped_column(Integer)
    surface: Mapped[str | None] = mapped_column(String(10))
    condition: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (CheckConstraint("tooth between 11 and 85", name="ck_tooth"),)


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"
    number: Mapped[str] = mapped_column(String(30))
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"))
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    discount_type: Mapped[str] = mapped_column(String(10), default="amount")  # amount | percent
    discount_value: Mapped[float] = mapped_column(Float, default=0)  # cents, or percent
    vat_rate: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(10), default="Draft")
    void_reason: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    lines: Mapped[list["InvoiceLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="InvoiceLine.id"
    )
    payments: Mapped[list["Payment"]] = relationship(lazy="selectin", order_by="Payment.id")
    credit_notes: Mapped[list["CreditNote"]] = relationship(lazy="selectin", order_by="CreditNote.id")
    __table_args__ = (UniqueConstraint("clinic_id", "number", name="uq_invoice_number"),)


class InvoiceLine(TimestampMixin, Base):
    __tablename__ = "invoice_lines"
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))
    description: Mapped[str] = mapped_column(String(255))
    qty: Mapped[float] = mapped_column(Float, default=1)
    unit_price: Mapped[int] = mapped_column(Integer)
    share_pct: Mapped[float] = mapped_column(Float, default=0)
    lab_cost: Mapped[int] = mapped_column(Integer, default=0)
    vat_applies: Mapped[bool] = mapped_column(Boolean, default=False)


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(20))
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(10), default="Payment")  # Payment | Refund
    refund_of: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payment_amount"),)


class CreditNote(TimestampMixin, Base):
    __tablename__ = "credit_notes"
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint("amount > 0", name="ck_credit_amount"),)


class StockMovement(TimestampMixin, Base):
    __tablename__ = "stock_movements"
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    qty: Mapped[float] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Expense(TimestampMixin, Base):
    __tablename__ = "expenses"
    clinic_id: Mapped[int | None] = mapped_column(ForeignKey("clinics.id"))  # NULL = shared
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[int] = mapped_column(Integer)
    paid_to: Mapped[str | None] = mapped_column(String(160))
    receipt_path: Mapped[str | None] = mapped_column(String(500))


class Attendance(TimestampMixin, Base):
    __tablename__ = "attendance"
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    clock_in: Mapped[datetime | None] = mapped_column(DateTime)
    clock_out: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="Present")
    note: Mapped[str | None] = mapped_column(Text)
    corrected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("staff_id", "date", name="uq_attendance_day"),)


class PayrollRun(TimestampMixin, Base):
    __tablename__ = "payroll_runs"
    month: Mapped[str] = mapped_column(String(7), unique=True)  # YYYY-MM
    status: Mapped[str] = mapped_column(String(10), default="Draft")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    paid_on: Mapped[dt.date | None] = mapped_column(Date)
    method: Mapped[str | None] = mapped_column(String(20))
    lines: Mapped[list["PayrollLine"]] = relationship(lazy="selectin", order_by="PayrollLine.id")


class PayrollLine(TimestampMixin, Base):
    __tablename__ = "payroll_lines"
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    base: Mapped[int] = mapped_column(Integer, default=0)
    absence_days: Mapped[float] = mapped_column(Float, default=0)
    absence_deduction: Mapped[int] = mapped_column(Integer, default=0)
    commission: Mapped[int] = mapped_column(Integer, default=0)
    bonus: Mapped[int] = mapped_column(Integer, default=0)
    deductions: Mapped[int] = mapped_column(Integer, default=0)
    net: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("run_id", "staff_id"),)


class AuditLog(Base):
    """Append-only; no update/delete endpoint and DB triggers forbid UPDATE/DELETE (NFR-05)."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    action: Mapped[str] = mapped_column(String(30), index=True)
    entity: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    financial: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Setting(TimestampMixin, Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), unique=True)
    value: Mapped[str | None] = mapped_column(Text)


Index("ix_appt_doctor_time", Appointment.doctor_id, Appointment.start_at)
Index("ix_movements_item", StockMovement.item_id, StockMovement.at)
