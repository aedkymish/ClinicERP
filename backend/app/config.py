"""Runtime configuration, read from environment variables (prefix CLINIC_)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLINIC_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'clinic.db'}"
    secret_key: str = "change-me-in-production-please-32+chars"
    cookie_secure: bool = True
    access_minutes: int = 15
    refresh_hours: int = 8
    idle_minutes: int = 30
    lockout_attempts: int = 5
    lockout_minutes: int = 15

    data_dir: Path = BASE_DIR / "data"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    backup_dir: Path = BASE_DIR / "data" / "backups"
    # Off-server copy target (mounted network share, synced folder, ...). Empty = disabled.
    offsite_backup_dir: Path | None = None
    backup_keep: int = 30
    backup_hour: int = 2  # local clinic time for the nightly backup
    # Fernet key used to encrypt backup files at rest (NFR-04). Empty = plain SQLite file.
    backup_encryption_key: str = ""
    scheduler_enabled: bool = True

    max_upload_mb: int = 10
    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    for d in (s.data_dir, s.upload_dir, s.backup_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s
