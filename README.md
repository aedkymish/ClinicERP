# ClinicERP v2

Multi-user clinic management for a dental and a dermatology clinic, built to
*وثيقة متطلبات البرمجيات (SRS) — ClinicERP.md* (SRS v2.0).

```
Browser ──HTTPS──▶ Nginx (TLS, HSTS) ──▶ Next.js (frontend/) ──/api/v1──▶ FastAPI (backend/) ──▶ SQLite (WAL)
```

The browser only talks to the Next.js server, which forwards `/api/v1/*` to FastAPI on the private network.
JWTs live in httpOnly, Secure, SameSite=Strict cookies and never reach page scripts. Every permission and
clinic-scope rule is enforced in FastAPI.

## Quick start (development)

```bash
# API
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export CLINIC_COOKIE_SECURE=false            # plain http on localhost only
.venv/bin/python -m app.cli init             # migrations + the two clinics
.venv/bin/python -m app.cli create-admin admin   # prints a one-time password
# optional, fresh test install only: .venv/bin/python -m app.cli seed-demo
.venv/bin/uvicorn app.main:app --port 8000

# Web
cd frontend
npm install
npm run build && API_URL=http://127.0.0.1:8000 npm start   # or: npm run dev
```

Open http://localhost:3000, sign in with the one-time password and choose your own password.
API docs: http://localhost:8000/api/v1/docs

## Server installation (Docker)

Requirements: Docker Engine + Compose plugin (Linux) or Docker Desktop (Windows / macOS).

```bash
./install.sh                     # Linux / macOS
install.bat                      # Windows (Command Prompt or double-click)
```

The installer:
- checks Docker;
- creates `backend/.env` with a random session key and backup encryption key;
- creates a self-signed TLS certificate, unless you pass `--cert`/`--key`;
- builds and starts the containers and waits for the API;
- creates the first administrator, printing a one-time password.

Run it again after updating the code: it keeps secrets, certificates and data.

Options (same for both): `--domain NAME`, `--admin NAME`, `--http-port N`, `--https-port N`,
`--offsite PATH`, `--cert FILE --key FILE`, `--help`.
Example: `./install.sh --domain clinic.example.com --offsite /mnt/nas/clinic-backups`

**Back up `backend/.env`.** Encrypted backups cannot be restored without its `CLINIC_BACKUP_ENCRYPTION_KEY`.

## Manual production setup

1. `cp backend/.env.example backend/.env`, set `CLINIC_SECRET_KEY` and `CLINIC_BACKUP_ENCRYPTION_KEY`.
2. Put the TLS certificate in `deploy/certs/fullchain.pem` and `privkey.pem`.
3. Set `OFFSITE_BACKUP_PATH` to a mounted NAS or synced folder for the off-server backup copy.
4. `docker compose up -d --build`, then `docker compose exec api python -m app.cli create-admin admin`.

Nightly backups run at 02:00 clinic time (SQLite online-backup API, 30 kept, copied off-server,
optionally Fernet-encrypted). `python -m app.cli backup` can be called from OS cron instead.
Disk encryption for the database volume (NFR-04) is an OS-level step: use LUKS, BitLocker or FileVault.

## Tests

```bash
cd backend && .venv/bin/pytest --cov=app          # 77 API tests, incl. the full role × endpoint matrix
cd frontend && E2E_USER=admin E2E_PASSWORD=… npx playwright test   # UI tests against a running stack
```

## Layout

| Path | Contents |
| --- | --- |
| `backend/app/models.py` | the 24 tables of SRS §4, plus `user_sessions` for logout and idle timeout |
| `backend/app/permissions.py` | the role matrix of SRS §2.2 |
| `backend/app/services/billing.py` | invoice maths, numbering, posting, stock deduction, the commission formula (PAY-03) |
| `backend/app/services/payroll.py` | payroll runs (PAY-01..04) |
| `backend/app/audit.py` | automatic before/after audit of every insert, update and delete |
| `backend/app/bootstrap.py` | DB triggers that make the audit log, payments, stock movements, status log, addenda and tooth history append-only |
| `backend/alembic/` | versioned migrations |
| `frontend/src/app/(app)/` | one folder per screen |
| `frontend/src/lib/i18n.tsx` | English and Arabic strings; Arabic switches to RTL |

## Decisions taken where the SRS was silent or inconsistent

| Topic | Decision |
| --- | --- |
| Open decision §7.1: hosting | Works on-premise or on a cloud VM; Docker Compose is provided |
| Open decision §7.1: VAT | Off by default; rate and on/off in Settings; VAT applies per service |
| Open decision §7.1: numbering | `D-2026-00001` / `M-2026-00001`, per clinic and per year; prefixes editable in Settings |
| Balance with credit notes | INV-04 leaves out credit notes, so balance = total − credit notes − payments + refunds |
| Void | Allowed only after all payments are refunded; reverses auto stock deductions |
| Stock on posting | Posting is refused (409) if linked stock would go below zero (§4 rule); Receive or Adjust first |
| Commission and refunds | Paid share per period = (payments − refunds) ÷ total, so a refund reduces commission |
| Net profit | Collections − refunds − expenses − approved payroll. Payroll already contains commission, so commission is not subtracted twice |
| Patients' clinic | Added `patients.clinic_scope` (dental/derma/both): drives clinic scope and the dental-chart tab ("dental patients only") |
| Attendance permissions | §2.2 says Finance has "read, approve" but ATT-03 says Finance records and corrects; ATT-03 is followed |
| Optimistic locking | Every table has a `version` column (NFR-09); edits send it back and get 409 when stale |
| Money | Integer minor units in the API and DB; the UI converts using the currency's decimals |
| Session idle | Enforced on the server (session `last_seen`) and in the browser (30 min without input) |
| v1 import | The v1 file format is not in the SRS; the importer accepts the usual key spellings. **Verify it with a real v1 backup (dry run) before go-live** |
