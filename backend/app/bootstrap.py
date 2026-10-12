"""Reference data and database-level guards shared by Alembic migrations and tests."""
from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from .models import Clinic

APPEND_ONLY = {
    "audit_log": ("UPDATE", "DELETE"),
    "appointment_status_log": ("UPDATE", "DELETE"),
    "visit_addenda": ("UPDATE", "DELETE"),
    "stock_movements": ("UPDATE", "DELETE"),
    "tooth_entries": ("UPDATE", "DELETE"),
    "payments": ("UPDATE", "DELETE"),
}


def install_guards(conn: Connection) -> None:
    """NFR-05/INV-07: the database itself refuses to change or remove append-only rows."""
    if conn.dialect.name == "sqlite":
        for table, ops in APPEND_ONLY.items():
            for op in ops:
                name = f"trg_{table}_no_{op.lower()}"
                conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
                conn.execute(text(
                    f"CREATE TRIGGER {name} BEFORE {op} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"))
    elif conn.dialect.name == "postgresql":
        conn.execute(text(
            "CREATE OR REPLACE FUNCTION clinicerp_append_only() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END; $$ LANGUAGE plpgsql"))
        for table, ops in APPEND_ONLY.items():
            conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}"))
            conn.execute(text(f"CREATE TRIGGER trg_{table}_append_only BEFORE {' OR '.join(ops)} ON {table} "
                              f"FOR EACH ROW EXECUTE FUNCTION clinicerp_append_only()"))


def seed_reference(db: Session) -> None:
    """The two clinics (section 4: 2 rows). Names and prefixes are editable in Settings."""
    have = {c.code for c in db.scalars(select(Clinic))}
    if "dental" not in have:
        db.add(Clinic(id=1, code="dental", name="Dental Clinic", invoice_prefix="D"))
    if "derma" not in have:
        db.add(Clinic(id=2, code="derma", name="Derma Clinic", invoice_prefix="M"))
    db.commit()
