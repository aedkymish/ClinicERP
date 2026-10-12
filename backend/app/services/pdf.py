"""PDF documents: invoice / receipt / credit note (A4 and 80 mm), payslip, report tables."""
import io
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from ..deps import settings_map
from ..models import Clinic, Invoice, Patient, PayrollLine, PayrollRun, Staff, User
from .billing import totals

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]+(?:[\s\d.,:()/-]*[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]+)*")
_fonts_ready = False
BASE, BOLD, AR, AR_BOLD = "Helvetica", "Helvetica-Bold", "Helvetica", "Helvetica-Bold"


def _register_fonts() -> None:
    global _fonts_ready, BASE, BOLD, AR, AR_BOLD
    if _fonts_ready:
        return
    _fonts_ready = True
    files = {
        "NotoSans": "NotoSans-Regular.ttf", "NotoSans-Bold": "NotoSans-Bold.ttf",
        "NotoArabic": "NotoSansArabic-Regular.ttf", "NotoArabic-Bold": "NotoSansArabic-Bold.ttf",
    }
    ok = {}
    for name, f in files.items():
        p = FONT_DIR / f
        if p.exists():
            try:
                pdfmetrics.registerFont(TTFont(name, str(p)))
                ok[name] = True
            except Exception:
                pass
    if ok.get("NotoSans") and ok.get("NotoSans-Bold"):
        BASE, BOLD = "NotoSans", "NotoSans-Bold"
        pdfmetrics.registerFontFamily("NotoSans", normal="NotoSans", bold="NotoSans-Bold")
    if ok.get("NotoArabic"):
        AR = "NotoArabic"
        AR_BOLD = "NotoArabic-Bold" if ok.get("NotoArabic-Bold") else "NotoArabic"


def rich(text: object, bold: bool = False) -> str:
    """Escape for Paragraph markup and render Arabic runs shaped, right-to-left, in an Arabic font."""
    s = "" if text is None else str(text)
    if not _ARABIC.search(s):
        return escape(s)
    import arabic_reshaper
    from bidi.algorithm import get_display

    visual = get_display(arabic_reshaper.reshape(s))
    font = AR_BOLD if bold else AR
    out, pos = [], 0
    for m in _ARABIC.finditer(visual):
        out.append(escape(visual[pos:m.start()]))
        out.append(f'<font name="{font}">{escape(m.group(0))}</font>')
        pos = m.end()
    out.append(escape(visual[pos:]))
    return "".join(out)


class Fmt:
    def __init__(self, db: Session):
        st = settings_map(db)
        self.currency = st["currency"]
        self.decimals = int(st["currency_decimals"] or 2)

    def money(self, cents: int | None) -> str:
        v = (cents or 0) / (10 ** self.decimals)
        return f"{v:,.{self.decimals}f} {self.currency}"


def _styles(size: float = 9):
    _register_fonts()
    return {
        "n": ParagraphStyle("n", fontName=BASE, fontSize=size, leading=size * 1.35),
        "b": ParagraphStyle("b", fontName=BOLD, fontSize=size, leading=size * 1.35),
        "r": ParagraphStyle("r", fontName=BASE, fontSize=size, leading=size * 1.35, alignment=2),
        "rb": ParagraphStyle("rb", fontName=BOLD, fontSize=size, leading=size * 1.35, alignment=2),
        "c": ParagraphStyle("c", fontName=BASE, fontSize=size, leading=size * 1.35, alignment=1),
        "h": ParagraphStyle("h", fontName=BOLD, fontSize=size * 1.7, leading=size * 2.1),
        "hc": ParagraphStyle("hc", fontName=BOLD, fontSize=size * 1.3, leading=size * 1.7, alignment=1),
    }


def _logo(db: Session, width: float):
    path = settings_map(db).get("logo_path")
    if path and Path(path).exists():
        try:
            img = Image(path)
            ratio = img.imageHeight / float(img.imageWidth)
            img.drawWidth, img.drawHeight = width, width * ratio
            return img
        except Exception:
            return None
    return None


def _grid(data, widths, header=True, align_right_from: int | None = None):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#334155")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")))
    t.setStyle(TableStyle(style))
    return t


def _build(story, pagesize, margins=15 * mm) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=margins, rightMargin=margins,
                            topMargin=margins, bottomMargin=margins)
    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------- invoice / receipt
def invoice_pdf(db: Session, inv: Invoice, paper: str = "a4", kind: str = "invoice") -> bytes:
    """kind: invoice | receipt; paper: a4 | thermal (80 mm roll)."""
    thermal = paper == "thermal"
    st = _styles(7.5 if thermal else 9)
    f = Fmt(db)
    clinic = db.get(Clinic, inv.clinic_id)
    patient = db.get(Patient, inv.patient_id)
    doctor = db.get(Staff, inv.doctor_id) if inv.doctor_id else None
    t = totals(inv)
    width = 72 * mm if thermal else A4[0] - 30 * mm
    story = []
    logo = _logo(db, 30 * mm if thermal else 40 * mm)
    title = {"invoice": "INVOICE", "receipt": "RECEIPT"}[kind]
    if inv.status == "Void":
        title += " — VOID"
    elif inv.status == "Draft":
        title += " (DRAFT)"
    head = [Paragraph(rich(clinic.name, True), st["hc" if thermal else "h"]), Paragraph(title, st["hc" if thermal else "b"])]
    if thermal:
        if logo:
            story.append(logo)
        story += head
    elif logo:
        story.append(Table([[logo, head]], colWidths=[45 * mm, width - 45 * mm],
                           style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))
    else:
        story += head
    story.append(Spacer(1, 4 * mm))
    meta = [
        ("No.", inv.number), ("Date", inv.date.isoformat()),
        ("Patient", patient.name), ("File no.", patient.file_no), ("Phone", patient.phone),
    ]
    if doctor:
        meta.append(("Doctor", doctor.name))
    story.append(Table([[Paragraph(k, st["b"]), Paragraph(rich(v), st["n"])] for k, v in meta],
                       colWidths=[18 * mm if thermal else 30 * mm, width - (18 * mm if thermal else 30 * mm)]))
    story.append(Spacer(1, 3 * mm))
    if thermal:
        rows = [[Paragraph("Item", st["b"]), Paragraph("Amount", st["rb"])]]
        for line, c in zip(inv.lines, t.lines, strict=True):
            rows.append([Paragraph(f"{rich(line.description)}<br/>{line.qty:g} × {f.money(line.unit_price)}", st["n"]),
                         Paragraph(f.money(c.gross), st["r"])])
        story.append(_grid(rows, [width * 0.62, width * 0.38]))
    else:
        rows = [[Paragraph(h, st["b" if i == 0 else "rb"]) for i, h in enumerate(["Description", "Qty", "Unit price", "Amount"])]]
        for line, c in zip(inv.lines, t.lines, strict=True):
            rows.append([Paragraph(rich(line.description), st["n"]), Paragraph(f"{line.qty:g}", st["r"]),
                         Paragraph(f.money(line.unit_price), st["r"]), Paragraph(f.money(c.gross), st["r"])])
        story.append(_grid(rows, [width * 0.5, width * 0.1, width * 0.2, width * 0.2]))
    story.append(Spacer(1, 3 * mm))
    summary = [("Subtotal", t.subtotal)]
    if t.discount:
        summary.append(("Discount", -t.discount))
    if t.vat:
        summary.append((f"VAT {inv.vat_rate:g}%", t.vat))
    summary.append(("Total", t.total))
    if t.credited:
        summary.append(("Credit notes", -t.credited))
    summary.append(("Paid", -t.paid))
    if t.refunded:
        summary.append(("Refunded", t.refunded))
    summary.append(("Balance due", t.balance))
    sw = [width * 0.55, width * 0.45] if thermal else [width * 0.75, width * 0.25]
    story.append(Table([[Paragraph(k, st["rb" if k in ("Total", "Balance due") else "r"]),
                         Paragraph(f.money(v), st["rb" if k in ("Total", "Balance due") else "r"])] for k, v in summary],
                       colWidths=sw))
    if inv.payments:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Payments", st["b"]))
        if thermal:
            prow = [[Paragraph(h, st["b"]) for h in ("Date", "Method")] + [Paragraph("Amount", st["rb"])]]
            for p in inv.payments:
                amount = f.money(p.amount if p.kind == "Payment" else -p.amount)
                prow.append([Paragraph(p.date.strftime("%d/%m/%y"), st["n"]), Paragraph(p.method, st["n"]),
                             Paragraph(amount, st["r"])])
            story.append(_grid(prow, [width * 0.28, width * 0.32, width * 0.40]))
        else:
            prow = [[Paragraph(h, st["b"]) for h in ("Date", "Method", "Type")] + [Paragraph("Amount", st["rb"])]]
            for p in inv.payments:
                prow.append([Paragraph(p.date.isoformat(), st["n"]), Paragraph(p.method, st["n"]),
                             Paragraph(p.kind, st["n"]), Paragraph(f.money(p.amount), st["r"])])
            story.append(_grid(prow, [width * 0.25] * 4))
    if inv.status == "Void" and inv.void_reason:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(f"Void reason: {rich(inv.void_reason)}", st["n"]))
    if inv.notes:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(rich(inv.notes), st["n"]))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Thank you", st["c"]))
    if thermal:
        # 80 mm roll; height grows with content
        height = max(150 * mm, (60 + 12 * (len(inv.lines) + len(inv.payments) + len(summary))) * mm)
        return _build(story, (80 * mm, height), margins=4 * mm)
    return _build(story, A4)


def credit_note_pdf(db: Session, inv: Invoice, note_id: int) -> bytes:
    st = _styles()
    f = Fmt(db)
    note = next(c for c in inv.credit_notes if c.id == note_id)
    clinic = db.get(Clinic, inv.clinic_id)
    patient = db.get(Patient, inv.patient_id)
    width = A4[0] - 30 * mm
    story = [Paragraph(rich(clinic.name, True), st["h"]), Paragraph("CREDIT NOTE", st["b"]), Spacer(1, 5 * mm)]
    rows = [("Credit note", note.number), ("Date", note.created_at.date().isoformat()),
            ("Invoice", inv.number), ("Patient", patient.name), ("File no.", patient.file_no),
            ("Amount", f.money(note.amount)), ("Reason", note.reason)]
    story.append(Table([[Paragraph(k, st["b"]), Paragraph(rich(v), st["n"])] for k, v in rows],
                       colWidths=[35 * mm, width - 35 * mm]))
    return _build(story, A4)


# ---------------------------------------------------------------- payslip (PAY-06)
def payslip_pdf(db: Session, line: PayrollLine) -> bytes:
    st = _styles(10)
    f = Fmt(db)
    run = db.get(PayrollRun, line.run_id)
    staff = db.get(Staff, line.staff_id)
    width = A4[0] - 30 * mm
    clinic_names = " / ".join(c.name for c in db.query(Clinic).order_by(Clinic.id))
    story = []
    logo = _logo(db, 35 * mm)
    if logo:
        story.append(logo)
    story += [Paragraph(rich(clinic_names, True), st["h"]), Paragraph(f"PAYSLIP — {run.month}", st["b"]),
              Spacer(1, 5 * mm)]
    info = [("Employee", staff.name), ("Role", staff.role), ("Status", run.status)]
    if run.paid_on:
        info.append(("Paid on", f"{run.paid_on.isoformat()} ({run.method or ''})"))
    story.append(Table([[Paragraph(k, st["b"]), Paragraph(rich(v), st["n"])] for k, v in info],
                       colWidths=[35 * mm, width - 35 * mm]))
    story.append(Spacer(1, 5 * mm))
    rows = [[Paragraph("Item", st["b"]), Paragraph("Amount", st["rb"])],
            [Paragraph("Base salary", st["n"]), Paragraph(f.money(line.base), st["r"])],
            [Paragraph(f"Absence / unpaid leave ({line.absence_days:g} days)", st["n"]),
             Paragraph(f.money(-line.absence_deduction), st["r"])],
            [Paragraph("Doctor commission", st["n"]), Paragraph(f.money(line.commission), st["r"])],
            [Paragraph("Bonus", st["n"]), Paragraph(f.money(line.bonus), st["r"])],
            [Paragraph("Deductions", st["n"]), Paragraph(f.money(-line.deductions), st["r"])],
            [Paragraph("Net pay", st["b"]), Paragraph(f.money(line.net), st["rb"])]]
    story.append(_grid(rows, [width * 0.7, width * 0.3]))
    if line.note:
        story += [Spacer(1, 4 * mm), Paragraph(rich(line.note), st["n"])]
    return _build(story, A4)


# ---------------------------------------------------------------- generic report table
def table_pdf(db: Session, title: str, columns: Sequence[tuple[str, str]], rows: list[dict],
              summary: list[tuple[str, str]]) -> bytes:
    wide = len(columns) > 6
    pagesize = landscape(A4) if wide else A4
    st = _styles(8 if wide else 9)
    width = pagesize[0] - 30 * mm
    clinic_names = " / ".join(c.name for c in db.query(Clinic).order_by(Clinic.id))
    story = [Paragraph(rich(clinic_names, True), st["b"]), Paragraph(rich(title), st["h"]),
             Paragraph(f"Generated {date.today().isoformat()}", st["n"]), Spacer(1, 4 * mm)]
    if summary:
        story.append(Table([[Paragraph(rich(k), st["b"]), Paragraph(rich(v), st["r"])] for k, v in summary],
                           colWidths=[width * 0.5, width * 0.3], hAlign="LEFT"))
        story.append(Spacer(1, 4 * mm))
    data = [[Paragraph(rich(h), st["b"]) for _, h in columns]]
    for r in rows:
        data.append([Paragraph(rich("" if r.get(k) is None else r.get(k)), st["n"]) for k, _ in columns])
    story.append(_grid(data, [width / len(columns)] * len(columns)))
    return _build(story, pagesize)


__all__ = ["invoice_pdf", "credit_note_pdf", "payslip_pdf", "table_pdf", "Fmt", "rich", "User"]
