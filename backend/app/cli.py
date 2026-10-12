"""Server-side admin commands.

    python -m app.cli init                  # run migrations and create the two clinics
    python -m app.cli create-admin NAME     # first administrator; prints a one-time password
    python -m app.cli backup                # one backup now (for OS cron instead of the built-in scheduler)
    python -m app.cli seed-demo             # demo data for a fresh test install only (SET-04)
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import func, select

from .db import SessionLocal


def init() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")
    from .bootstrap import seed_reference

    with SessionLocal() as db:
        seed_reference(db)
    print("Database ready.")


def create_admin(username: str) -> None:
    from .models import Staff, User
    from .security import hash_password, one_time_password

    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == username.lower())):
            sys.exit(f"User {username} already exists")
        staff = Staff(name=username, role="admin", clinic_scope="both")
        db.add(staff)
        db.flush()
        otp = one_time_password()
        db.add(User(username=username.lower(), role="admin", clinic_scope="both", staff_id=staff.id,
                    password_hash=hash_password(otp), must_change_pw=True))
        db.commit()
    print(f"Administrator '{username.lower()}' created.\nOne-time password: {otp}\n"
          "It must be changed at first sign-in.")


def backup() -> None:
    from .services.backup import make_backup

    print(make_backup("nightly"))


def seed_demo() -> None:
    from .models import Patient

    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Patient)):
            sys.exit("Refusing to seed: the database already has patients (demo data only on a fresh install).")
        from .demo import seed

        for line in seed(db):
            print(line)


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    ca = sub.add_parser("create-admin")
    ca.add_argument("username")
    sub.add_parser("backup")
    sub.add_parser("seed-demo")
    a = p.parse_args()
    {"init": init, "backup": backup, "seed-demo": seed_demo}.get(a.cmd, lambda: create_admin(a.username))()


if __name__ == "__main__":
    main()
