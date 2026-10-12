"""Invoice arithmetic, numbering, posting and doctor commission (INV-02..09, PAY-03).

All money is integer minor units. Rounding is half-up at the last step of each figure.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Clinic, CreditNote, Invoice, InvoiceLine, InventoryItem, Payment, Service, StockMovement


def rnd(x: Decimal | float) -> int:
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class LineCalc:
    gross: int
    discount: int
    net: int  # gross − discount share (before VAT)
    vat: int


@dataclass
class Totals:
    subtotal: int
    discount: int
    vat: int
    total: int
    credited: int
    paid: int
    refunded: int
    balance: int
    payment_status: str  # Unpaid | Partial | Paid | Void | Credit
    lines: list[LineCalc] = field(default_factory=list)


def discount_amount(subtotal: int, discount_type: str, discount_value: float) -> int:
    if subtotal <= 0 or not discount_value:
        return 0
    if discount_type == "percent":
        pct = min(max(Decimal(str(discount_value)), Decimal(0)), Decimal(100))
        return rnd(Decimal(subtotal) * pct / 100)
    return min(max(int(discount_value), 0), subtotal)


def compute_lines(lines: list[InvoiceLine], discount_type: str, discount_value: float, vat_rate: float
                  ) -> tuple[int, int, int, list[LineCalc]]:
    gross = [rnd(Decimal(str(l.qty)) * l.unit_price) for l in lines]
    subtotal = sum(gross)
    discount = discount_amount(subtotal, discount_type, discount_value)
    # spread the discount over lines in proportion to gross; the last line absorbs rounding
    shares, given = [], 0
    for i, g in enumerate(gross):
        if i == len(gross) - 1:
            s = discount - given
        else:
            s = rnd(Decimal(discount) * g / subtotal) if subtotal else 0
        shares.append(s)
        given += s
    rate = Decimal(str(vat_rate or 0))
    calcs = []
    for l, g, s in zip(lines, gross, shares, strict=True):
        net = g - s
        vat = rnd(Decimal(net) * rate / 100) if l.vat_applies and rate else 0
        calcs.append(LineCalc(gross=g, discount=s, net=net, vat=vat))
    return subtotal, discount, sum(c.vat for c in calcs), calcs


def totals(inv: Invoice) -> Totals:
    subtotal, discount, vat, calcs = compute_lines(inv.lines, inv.discount_type, inv.discount_value, inv.vat_rate)
    total = subtotal - discount + vat
    credited = sum(c.amount for c in inv.credit_notes)
    paid = sum(p.amount for p in inv.payments if p.kind == "Payment")
    refunded = sum(p.amount for p in inv.payments if p.kind == "Refund")
    if inv.status == "Void":
        balance, status = 0, "Void"
    else:
        # INV-04, extended with credit notes (INV-07)
        balance = total - credited - paid + refunded
        if balance < 0:
            status = "Credit"
        elif balance == 0 and total > 0:
            status = "Paid"
        elif paid - refunded > 0:
            status = "Partial"
        else:
            status = "Unpaid" if total > 0 else "Paid"
    return Totals(subtotal, discount, vat, total, credited, paid, refunded, balance, status, calcs)


# ---------------------------------------------------------------- numbering (INV-02)
def next_invoice_number(db: Session, clinic_id: int, on: date) -> str:
    clinic = db.get(Clinic, clinic_id)
    prefix = f"{clinic.invoice_prefix}-{on.year}-"
    last = db.scalar(
        select(func.max(Invoice.number)).where(Invoice.clinic_id == clinic_id, Invoice.number.like(f"{prefix}%"))
    )
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


def next_credit_number(db: Session, inv: Invoice) -> str:
    clinic = db.get(Clinic, inv.clinic_id)
    year = utcnow().year
    prefix = f"CN-{clinic.invoice_prefix}-{year}-"
    last = db.scalar(select(func.max(CreditNote.number)).where(CreditNote.number.like(f"{prefix}%")))
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


# ---------------------------------------------------------------- stock
def stock_on_hand(db: Session, item_id: int) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(StockMovement.qty), 0)).where(StockMovement.item_id == item_id)))


class StockShortage(Exception):
    def __init__(self, item: InventoryItem, needed: float, available: float):
        self.item, self.needed, self.available = item, needed, available
        super().__init__(f"Not enough stock of {item.name}: need {needed:g} {item.unit}, have {available:g}")


def consumption(db: Session, inv: Invoice) -> dict[int, float]:
    """Inventory consumed by the invoice's services (SVC-03): item_id -> qty."""
    need: dict[int, float] = {}
    for line in inv.lines:
        if not line.service_id:
            continue
        svc = db.get(Service, line.service_id)
        for si in svc.items:
            need[si.item_id] = need.get(si.item_id, 0) + si.qty_per_unit * line.qty
    return need


def post_invoice(db: Session, inv: Invoice, user_id: int | None) -> None:
    """Draft -> Posted: lock the invoice and auto-deduct linked stock (INV-06, INV-09)."""
    if inv.status != "Draft":
        return
    if not inv.lines:
        raise ValueError("An invoice needs at least one line before it can be posted")
    need = consumption(db, inv)
    for item_id, qty in need.items():
        item = db.get(InventoryItem, item_id)
        have = stock_on_hand(db, item_id)
        if have + 1e-9 < qty:
            raise StockShortage(item, qty, have)
    for item_id, qty in need.items():
        db.add(StockMovement(item_id=item_id, kind="Auto", qty=-qty, invoice_id=inv.id, user_id=user_id,
                             reason=f"Invoice {inv.number}"))
    inv.status = "Posted"
    inv.posted_at = utcnow()


def reverse_stock(db: Session, inv: Invoice, user_id: int | None) -> None:
    moves = db.scalars(select(StockMovement).where(StockMovement.invoice_id == inv.id, StockMovement.kind == "Auto"))
    per_item: dict[int, float] = {}
    for m in moves:
        per_item[m.item_id] = per_item.get(m.item_id, 0) + m.qty
    for item_id, qty in per_item.items():
        if qty:
            db.add(StockMovement(item_id=item_id, kind="Auto", qty=-qty, invoice_id=inv.id, user_id=user_id,
                                 reason=f"Void of invoice {inv.number}"))


# ---------------------------------------------------------------- commission (PAY-03)
@dataclass
class CommissionLine:
    invoice_id: int
    invoice_number: str
    invoice_date: date
    patient_id: int
    description: str
    qty: float
    unit_price: int
    discount: int
    lab_cost: int
    share_pct: float
    base: int  # max(0, net − lab) × share — commission if the invoice were fully paid
    paid_fraction: float
    commission: int


def line_commission_base(line: InvoiceLine, calc: LineCalc) -> Decimal:
    """max(0, qty×price×(1 − discount share) − qty×lab cost) × share %."""
    lab = Decimal(str(line.qty)) * line.lab_cost
    value = max(Decimal(0), Decimal(calc.net) - lab)
    return value * Decimal(str(line.share_pct or 0)) / 100


def commission_for(db: Session, doctor_id: int, start: date, end: date, clinic_ids: set[int] | None = None
                   ) -> tuple[int, list[CommissionLine]]:
    """Commission earned by a doctor from payments received in [start, end].

    Each invoice's commission base is scaled by the share of the invoice total paid (net of refunds)
    in the period, so partial payments earn partial commission and a refund claws it back.
    """
    q = (
        select(Payment.invoice_id, Payment.kind, func.sum(Payment.amount))
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(Invoice.doctor_id == doctor_id, Payment.date >= start, Payment.date <= end)
        .group_by(Payment.invoice_id, Payment.kind)
    )
    if clinic_ids is not None:
        q = q.where(Invoice.clinic_id.in_(clinic_ids))
    net_paid: dict[int, int] = {}
    for inv_id, kind, amount in db.execute(q):
        net_paid[inv_id] = net_paid.get(inv_id, 0) + (amount if kind == "Payment" else -amount)

    detail: list[CommissionLine] = []
    total = Decimal(0)
    for inv_id, paid in sorted(net_paid.items()):
        inv = db.get(Invoice, inv_id)
        t = totals(inv)
        if t.total <= 0 or paid == 0:
            continue
        fraction = Decimal(paid) / Decimal(t.total)
        for line, calc in zip(inv.lines, t.lines, strict=True):
            base = line_commission_base(line, calc)
            amount = base * fraction
            total += amount
            detail.append(CommissionLine(
                invoice_id=inv.id, invoice_number=inv.number, invoice_date=inv.date, patient_id=inv.patient_id,
                description=line.description, qty=line.qty, unit_price=line.unit_price, discount=calc.discount,
                lab_cost=line.lab_cost, share_pct=line.share_pct, base=rnd(base), paid_fraction=float(fraction),
                commission=rnd(amount),
            ))
    return rnd(total), detail
