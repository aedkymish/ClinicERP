"""Expenses — EXP-01..02."""
import datetime as dt
import mimetypes
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import check_version, clinic_filter, ensure_clinic, http_error, not_found, require
from ..models import CLINIC_CODES, CLINIC_IDS, Expense, User
from ..services.export import export

router = APIRouter(prefix="/expenses", tags=["expenses"])
ALLOWED = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic"}


class ExpenseIn(BaseModel):
    clinic: Literal["dental", "derma", "shared"] = "shared"
    date: dt.date
    category: str = Field(min_length=1, max_length=80)
    description: str | None = None
    amount: int = Field(gt=0)
    paid_to: str | None = None


class ExpensePatch(BaseModel):
    clinic: Literal["dental", "derma", "shared"] | None = None
    date: dt.date | None = None
    category: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    amount: int | None = Field(default=None, gt=0)
    paid_to: str | None = None
    version: int | None = None


def out(e: Expense) -> dict:
    return {"id": e.id, "clinic": CLINIC_CODES.get(e.clinic_id, "shared"), "date": e.date.isoformat(),
            "category": e.category, "description": e.description, "amount": e.amount, "paid_to": e.paid_to,
            "has_receipt": bool(e.receipt_path), "version": e.version}


COLUMNS = [("date", "Date"), ("clinic", "Clinic"), ("category", "Category"), ("description", "Description"),
           ("paid_to", "Paid to"), ("amount", "Amount")]


def expense_query(user: User, clinic: str | None, from_: date | None, to: date | None, category: str | None,
                  q: str | None = None):
    query = select(Expense).where(clinic_filter(Expense.clinic_id, user, clinic, shared=True))
    if from_:
        query = query.where(Expense.date >= from_)
    if to:
        query = query.where(Expense.date <= to)
    if category:
        query = query.where(Expense.category == category)
    if q:
        query = query.where(or_(Expense.description.ilike(f"%{q}%"), Expense.paid_to.ilike(f"%{q}%")))
    return query


@router.get("")
def list_expenses(
    clinic: str | None = None, from_: date | None = Query(None, alias="from"), to: date | None = None,
    category: str | None = None, q: str | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), format: str | None = None,
    user: User = Depends(require("expenses")), db: Session = Depends(get_db),
):
    query = expense_query(user, clinic, from_, to, category, q)
    # EXP-02: the total covers exactly the filtered rows
    filtered = query.subquery()
    total_amount = db.scalar(select(func.coalesce(func.sum(filtered.c.amount), 0)))
    query = query.order_by(Expense.date.desc(), Expense.id.desc())
    if format:
        rows = [out(e) for e in db.scalars(query)]
        return export(db, rows, COLUMNS, format, "expenses", "expenses", "Expenses",
                      summary=[("Total", f"{total_amount}")])
    count = db.scalar(select(func.count()).select_from(query.subquery()))
    items = [out(e) for e in db.scalars(query.offset((page - 1) * page_size).limit(page_size))]
    return {"items": items, "total": count, "page": page, "page_size": page_size, "total_amount": total_amount}


def _get(db: Session, user: User, exp_id: int) -> Expense:
    e = db.get(Expense, exp_id)
    if not e:
        raise not_found("Expense")
    ensure_clinic(user, e.clinic_id, shared_ok=True)
    return e


@router.post("", status_code=201)
def create_expense(body: ExpenseIn, user: User = Depends(require("expenses")), db: Session = Depends(get_db)):
    data = body.model_dump()
    code = data.pop("clinic")
    clinic_id = None if code == "shared" else CLINIC_IDS[code]
    ensure_clinic(user, clinic_id, shared_ok=True)
    e = Expense(clinic_id=clinic_id, **data)
    db.add(e)
    db.commit()
    return out(e)


@router.patch("/{exp_id}")
def patch_expense(exp_id: int, body: ExpensePatch, user: User = Depends(require("expenses")),
                  db: Session = Depends(get_db)):
    e = _get(db, user, exp_id)
    data = body.model_dump(exclude_unset=True)
    check_version(e, data.pop("version", None))
    if "clinic" in data:
        code = data.pop("clinic")
        data["clinic_id"] = None if code in (None, "shared") else CLINIC_IDS[code]
        ensure_clinic(user, data["clinic_id"], shared_ok=True)
    for k, v in data.items():
        if k in ("date", "category", "amount") and v is None:
            continue
        setattr(e, k, v)
    db.commit()
    return out(e)


@router.post("/{exp_id}/receipt")
async def upload_receipt(exp_id: int, file: UploadFile = File(...), user: User = Depends(require("expenses")),
                         db: Session = Depends(get_db)):
    e = _get(db, user, exp_id)
    s = get_settings()
    content = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(content) > s.max_upload_mb * 1024 * 1024:
        raise http_error(413, f"File is larger than {s.max_upload_mb} MB", "too_large")
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if mime not in ALLOWED:
        raise http_error(422, "Only images and PDF files are allowed", "validation", field="file")
    folder = s.upload_dir / "receipts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{mimetypes.guess_extension(mime) or ''}"
    path.write_bytes(content)
    e.receipt_path = str(path)
    db.commit()
    return out(e)


@router.get("/{exp_id}/receipt")
def get_receipt(exp_id: int, user: User = Depends(require("expenses")), db: Session = Depends(get_db)):
    e = _get(db, user, exp_id)
    if not e.receipt_path:
        raise not_found("Receipt")
    return FileResponse(e.receipt_path, content_disposition_type="inline")
