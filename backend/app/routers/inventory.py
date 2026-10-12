"""Inventory with stock movements — STOCK-01..03."""
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import (check_version, clinic_filter, clinic_tz, conflict, ensure_clinic, http_error, not_found,
                    require)
from ..models import CLINIC_CODES, CLINIC_IDS, InventoryItem, StockMovement, User
from ..services.export import export
from ..timeutil import iso_utc, local_today, to_local

router = APIRouter(prefix="/inventory", tags=["inventory"])
EXPIRY_DAYS = 30


class ItemIn(BaseModel):
    clinic: Literal["dental", "derma", "shared"] = "shared"
    name: str = Field(min_length=1, max_length=160)
    category: str | None = None
    unit: str = "pcs"
    reorder_level: float = Field(0, ge=0)
    unit_cost: int = Field(0, ge=0)
    supplier: str | None = None
    expiry: date | None = None
    opening_qty: float = Field(0, ge=0)


class ItemPatch(BaseModel):
    clinic: Literal["dental", "derma", "shared"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    category: str | None = None
    unit: str | None = None
    reorder_level: float | None = Field(default=None, ge=0)
    unit_cost: int | None = Field(default=None, ge=0)
    supplier: str | None = None
    expiry: date | None = None
    active: bool | None = None
    version: int | None = None


class MovementIn(BaseModel):
    kind: Literal["Receive", "Use", "Adjust"]
    qty: float  # Receive/Use: positive amount; Adjust: signed change
    reason: str | None = None


def qty_map(db: Session, ids: list[int]) -> dict[int, float]:
    if not ids:
        return {}
    rows = db.execute(select(StockMovement.item_id, func.sum(StockMovement.qty))
                      .where(StockMovement.item_id.in_(ids)).group_by(StockMovement.item_id))
    return {i: float(q or 0) for i, q in rows}


def out(it: InventoryItem, qty: float, today: date) -> dict:
    return {
        "id": it.id, "clinic": CLINIC_CODES.get(it.clinic_id, "shared"), "name": it.name, "category": it.category,
        "unit": it.unit, "reorder_level": it.reorder_level, "unit_cost": it.unit_cost, "supplier": it.supplier,
        "expiry": it.expiry.isoformat() if it.expiry else None, "active": it.active, "qty": round(qty, 3),
        "low": qty <= it.reorder_level,
        "expiring": bool(it.expiry and it.expiry <= today + timedelta(days=EXPIRY_DAYS)),
        "expired": bool(it.expiry and it.expiry < today),
        "value": round(qty * it.unit_cost), "version": it.version,
    }


def _clinic_id(code: str) -> int | None:
    return None if code == "shared" else CLINIC_IDS[code]


COLUMNS = [("clinic", "Clinic"), ("name", "Item"), ("category", "Category"), ("unit", "Unit"), ("qty", "On hand"),
           ("reorder_level", "Reorder level"), ("unit_cost", "Unit cost"), ("supplier", "Supplier"),
           ("expiry", "Expiry"), ("low", "Low"), ("expiring", "Expiring")]


def list_items(db: Session, user: User, clinic: str | None = None, q: str | None = None, flag: str | None = None,
               active: bool | None = True) -> list[dict]:
    query = select(InventoryItem).where(clinic_filter(InventoryItem.clinic_id, user, clinic, shared=True))
    if active is not None:
        query = query.where(InventoryItem.active.is_(active))
    if q:
        query = query.where(or_(InventoryItem.name.ilike(f"%{q}%"), InventoryItem.category.ilike(f"%{q}%"),
                                InventoryItem.supplier.ilike(f"%{q}%")))
    items = list(db.scalars(query.order_by(InventoryItem.name)))
    qm = qty_map(db, [i.id for i in items])
    today = local_today(clinic_tz(db))
    rows = [out(i, qm.get(i.id, 0), today) for i in items]
    if flag == "low":
        rows = [r for r in rows if r["low"]]
    elif flag == "expiring":
        rows = [r for r in rows if r["expiring"]]
    return rows


@router.get("")
def get_items(clinic: str | None = None, q: str | None = None, flag: Literal["low", "expiring"] | None = None,
              active: bool | None = True, format: str | None = None,
              user: User = Depends(require("inventory.read")), db: Session = Depends(get_db)):
    rows = list_items(db, user, clinic, q, flag, active)
    if format:
        return export(db, rows, COLUMNS, format, "inventory", "inventory_items", "Inventory")
    return rows


def _get(db: Session, user: User, item_id: int) -> InventoryItem:
    it = db.get(InventoryItem, item_id)
    if not it:
        raise not_found("Item")
    ensure_clinic(user, it.clinic_id, shared_ok=True)
    return it


@router.post("", status_code=201)
def create_item(body: ItemIn, user: User = Depends(require("inventory.write")), db: Session = Depends(get_db)):
    data = body.model_dump()
    clinic_id = _clinic_id(data.pop("clinic"))
    ensure_clinic(user, clinic_id, shared_ok=True)
    opening = data.pop("opening_qty")
    it = InventoryItem(clinic_id=clinic_id, **data)
    db.add(it)
    db.flush()
    if opening:
        db.add(StockMovement(item_id=it.id, kind="Receive", qty=opening, reason="Opening stock", user_id=user.id))
    db.commit()
    return out(it, opening, local_today(clinic_tz(db)))


@router.patch("/{item_id}")
def patch_item(item_id: int, body: ItemPatch, user: User = Depends(require("inventory.write")),
               db: Session = Depends(get_db)):
    it = _get(db, user, item_id)
    data = body.model_dump(exclude_unset=True)
    check_version(it, data.pop("version", None))
    if "clinic" in data:
        data["clinic_id"] = _clinic_id(data.pop("clinic"))
        ensure_clinic(user, data["clinic_id"], shared_ok=True)
    for k, v in data.items():
        if k in ("name", "unit", "reorder_level", "unit_cost", "active") and v is None:
            continue
        setattr(it, k, v)
    db.commit()
    return out(it, qty_map(db, [it.id]).get(it.id, 0), local_today(clinic_tz(db)))


@router.get("/{item_id}/movements")
def movements(item_id: int, user: User = Depends(require("inventory.read")), db: Session = Depends(get_db)):
    _get(db, user, item_id)
    tz = clinic_tz(db)
    rows = db.scalars(select(StockMovement).where(StockMovement.item_id == item_id).order_by(StockMovement.id.desc()))
    res = []
    for m in rows:
        u = db.get(User, m.user_id) if m.user_id else None
        res.append({"id": m.id, "kind": m.kind, "qty": m.qty, "reason": m.reason, "invoice_id": m.invoice_id,
                    "user": u.username if u else None, "at": iso_utc(m.at),
                    "local": to_local(m.at, tz).strftime("%Y-%m-%d %H:%M")})
    return res


@router.post("/{item_id}/movements", status_code=201)
def add_movement(item_id: int, body: MovementIn, user: User = Depends(require("inventory.write")),
                 db: Session = Depends(get_db)):
    """STOCK-02: quantity changes only through movements; stock may not go below zero."""
    it = _get(db, user, item_id)
    if body.qty == 0:
        raise http_error(422, "Quantity cannot be zero", "validation", field="qty")
    if body.kind in ("Receive", "Use") and body.qty < 0:
        raise http_error(422, "Enter a positive quantity", "validation", field="qty")
    if body.kind == "Adjust" and not (body.reason and body.reason.strip()):
        raise http_error(422, "An adjustment needs a reason", "validation", field="reason")
    delta = -body.qty if body.kind == "Use" else body.qty
    have = qty_map(db, [it.id]).get(it.id, 0)
    if have + delta < -1e-9:
        raise conflict(f"Only {have:g} {it.unit} in stock", "stock_shortage")
    db.add(StockMovement(item_id=it.id, kind=body.kind, qty=delta, reason=(body.reason or "").strip() or None,
                         user_id=user.id, at=utcnow()))
    db.commit()
    return out(it, have + delta, local_today(clinic_tz(db)))
