"""Database backup and restore — SET-01, SET-02, NFR-04, NFR-07.

Backups use the SQLite online backup API, so they are consistent while the clinic keeps working.
When CLINIC_BACKUP_ENCRYPTION_KEY is set, files are encrypted with Fernet (AES-128-CBC + HMAC).
"""
import asyncio
import logging
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .. import db as dbmod
from ..config import get_settings

log = logging.getLogger("clinicerp.backup")
REQUIRED_TABLES = {"users", "patients", "invoices", "payments", "audit_log", "settings"}
SQLITE_MAGIC = b"SQLite format 3\x00"


class BackupError(Exception):
    pass


def db_path() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise BackupError("Built-in backup supports SQLite only; use pg_dump for PostgreSQL")
    return Path(url.removeprefix("sqlite:///"))


def _fernet() -> Fernet | None:
    key = get_settings().backup_encryption_key
    return Fernet(key.encode()) if key else None


def _snapshot(dest: Path) -> None:
    src = sqlite3.connect(db_path())
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def make_backup(kind: str = "manual") -> Path:
    """Write a consistent copy to the backup dir; returns its path."""
    s = get_settings()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    f = _fernet()
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "clinic.db"
        _snapshot(raw)
        if f:
            target = s.backup_dir / f"{kind}-{stamp}.db.enc"
            target.write_bytes(f.encrypt(raw.read_bytes()))
        else:
            target = s.backup_dir / f"{kind}-{stamp}.db"
            shutil.copy2(raw, target)
    if s.offsite_backup_dir:
        try:
            s.offsite_backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, s.offsite_backup_dir / target.name)
        except OSError as e:  # never lose the local copy because the share is down
            log.error("Off-server copy failed: %s", e)
    prune(kind)
    return target


def prune(kind: str) -> None:
    s = get_settings()
    for folder in filter(None, [s.backup_dir, s.offsite_backup_dir]):
        files = sorted(Path(folder).glob(f"{kind}-*.db*"), reverse=True)
        for old in files[s.backup_keep:]:
            old.unlink(missing_ok=True)


def list_backups() -> list[dict]:
    s = get_settings()
    return [{"name": p.name, "size": p.stat().st_size,
             "created": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}
            for p in sorted(s.backup_dir.glob("*.db*"), reverse=True)]


def decode_upload(content: bytes) -> bytes:
    if content.startswith(SQLITE_MAGIC):
        return content
    f = _fernet()
    if not f:
        raise BackupError("File is not a SQLite database (encrypted backups need the encryption key)")
    try:
        plain = f.decrypt(content)
    except InvalidToken as e:
        raise BackupError("Backup could not be decrypted with this server's key") from e
    if not plain.startswith(SQLITE_MAGIC):
        raise BackupError("Decrypted file is not a SQLite database")
    return plain


def restore(content: bytes) -> Path:
    """Replace the live database with an uploaded backup. Returns the safety copy taken first."""
    plain = decode_upload(content)
    with tempfile.TemporaryDirectory() as tmp:
        src_path = Path(tmp) / "restore.db"
        src_path.write_bytes(plain)
        src = sqlite3.connect(src_path)
        try:
            tables = {r[0] for r in src.execute("select name from sqlite_master where type='table'")}
            missing = REQUIRED_TABLES - tables
            if missing:
                raise BackupError(f"Not a ClinicERP backup (missing tables: {', '.join(sorted(missing))})")
            if src.execute("pragma integrity_check").fetchone()[0] != "ok":
                raise BackupError("Backup file failed the integrity check")
            safety = make_backup("pre-restore")
            dbmod.engine.dispose()
            dst = sqlite3.connect(db_path())
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    dbmod.engine.dispose()
    return safety


async def nightly_loop() -> None:
    """In-process scheduler for the nightly backup (an OS cron calling `python -m app.cli backup` also works)."""
    from zoneinfo import ZoneInfo

    from ..deps import settings_map

    while True:
        try:
            with dbmod.SessionLocal() as db:
                tz = ZoneInfo(settings_map(db)["time_zone"] or "UTC")
        except Exception:
            tz = ZoneInfo("UTC")
        now = datetime.now(tz)
        run_at = now.replace(hour=get_settings().backup_hour, minute=0, second=0, microsecond=0)
        if run_at <= now:
            run_at += timedelta(days=1)
        await asyncio.sleep((run_at - now).total_seconds())
        try:
            path = await asyncio.to_thread(make_backup, "nightly")
            log.info("Nightly backup written to %s", path)
        except Exception:
            log.exception("Nightly backup failed")
