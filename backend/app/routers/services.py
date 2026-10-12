"""Services and prices — SVC-01..04."""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import check_version, clinic_filter, ensure_clinic, forbidden, http_error, not_found, require
from ..models import CLINIC_CODES, CLINIC_IDS, InventoryItem, Service, ServiceItem, User
from ..permissions import can
from ..services.export import export

router = APIRouter(prefix="/services", tags=["services"])
PRICE_FIELDS = {"price", "share_pct", "lab_cost", "vat_applies"}


class ServiceIn(BaseModel):
    clinic: Literal["dental", "derma"]
    name: str = Field(min_length=1, max_length=160)
    category: str | None = None
    duration_min: int = Field(30, ge=5, le=600)
    price: int = Field(ge=0)
    vat_applies: bool = False
    share_pct: float | None = Field(default=None, ge=0, le=100)
    lab_cost: int = Field(0, ge=0)


class ServicePatch(BaseModel):
    clinic: Literal["dental", "derma"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    category: str | None = None
    duration_min: int | None = Field(default=None, ge=5, le=600)
    price: int | None = Field(default=None, ge=0)
    vat_applies: bool | None = None
    share_pct: float | None = Field(default=None, ge=0, le=100)
    lab_cost: int | None = Field(default=None, ge=0)
    active: bool | None = None
    version: int | None = None


class ItemLink(BaseModel):
    item_id: int
    qty_per_unit: float = Field(gt=0)


def out(db: Session, s: Service) -> dict:
    items = []
    for si in s.items:
        it = db.get(InventoryItem, si.item_id)
        items.append({"item_id": si.item_id, "name": it.name if it else None, "unit": it.unit if it else None,
                      "qty_per_unit": si.qty_per_unit})
    return {"id": s.id, "clinic": CLINIC_CODES[s.clinic_id], "clinic_id": s.clinic_id, "name": s.name,
            "category": s.category, "duration_min": s.duration_min, "price": s.price, "vat_applies": s.vat_applies,
            "share_pct": s.share_pct, "lab_cost": s.lab_cost, "active": s.active, "items": items, "version": s.version}


COLUMNS = [("clinic", "Clinic"), ("name", "Service"), ("category", "Category"), ("duration_min", "Minutes"),
           ("price", "Price (minor units)"), ("vat_applies", "VAT"), ("share_pct", "Doctor share %"),
           ("lab_cost", "Lab cost (minor units)"), ("active", "Active")]


@router.get("")
def list_services(clinic: str | None = None, active: bool | None = None, q: str | None = None,
                  format: str | None = None, user: User = Depends(require("services.read")),
                  db: Session = Depends(get_db)):
    query = select(Service).where(clinic_filter(Service.clinic_id, user, clinic))
    if active is not None:
        query = query.where(Service.active.is_(active))
    if q:
        query = query.where(or_(Service.name.ilike(f"%{q}%"), Service.category.ilike(f"%{q}%")))
    rows = [out(db, s) for s in db.scalars(query.order_by(Service.clinic_id, Service.category, Service.name))]
    if format:
        return export(db, rows, COLUMNS, format, "services", "services", "Services & prices")
    return rows


@router.post("", status_code=201)
def create_service(body: ServiceIn, user: User = Depends(require("services.write")), db: Session = Depends(get_db)):
    data = body.model_dump()
    clinic_id = CLINIC_IDS[data.pop("clinic")]
    ensure_clinic(user, clinic_id)
    s = Service(clinic_id=clinic_id, **data)
    db.add(s)
    db.commit()
    return out(db, s)


@router.patch("/{service_id}")
def patch_service(service_id: int, body: ServicePatch, user: User = Depends(require("services.write", "services.price")),
                  db: Session = Depends(get_db)):
    s = db.get(Service, service_id)
    if not s:
        raise not_found("Service")
    ensure_clinic(user, s.clinic_id)
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    if not can(user.role, "services.write") and set(data) - PRICE_FIELDS:
        raise forbidden("Finance may only change prices, VAT, doctor share and lab cost")
    if "clinic" in data:
        data["clinic_id"] = CLINIC_IDS[data.pop("clinic")]
        ensure_clinic(user, data["clinic_id"])
    for k in ("name", "duration_min", "price", "lab_cost", "vat_applies", "active"):
        if k in data and data[k] is None:
            raise http_error(422, f"{k} cannot be empty", "validation", field=k)
    check_version(s, version)
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    return out(db, s)


@router.put("/{service_id}/items")
def set_items(service_id: int, body: list[ItemLink], user: User = Depends(require("services.write")),
              db: Session = Depends(get_db)):
    """SVC-03: inventory consumed per unit of the service."""
    s = db.get(Service, service_id)
    if not s:
        raise not_found("Service")
    ensure_clinic(user, s.clinic_id)
    seen = set()
    for link in body:
        it = db.get(InventoryItem, link.item_id)
        if not it:
            raise not_found("Inventory item")
        if it.clinic_id not in (None, s.clinic_id):
            raise http_error(422, f"{it.name} belongs to the other clinic", "validation")
        if link.item_id in seen:
            raise http_error(422, "Each item may appear once", "validation")
        seen.add(link.item_id)
    s.items.clear()
    db.flush()
    for link in body:
        s.items.append(ServiceItem(item_id=link.item_id, qty_per_unit=link.qty_per_unit))
    db.commit()
    db.refresh(s)
    return out(db, s)
