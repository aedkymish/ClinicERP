# Software Requirements Specification (SRS) — ClinicERP v2.0

Oct 12, 2026 · @Ali Edkymish

ClinicERP v2 rebuilds the system as a multi-user web application: a Node.js (Next.js) frontend, a FastAPI REST backend, and a SQLite database, and it closes all 13 gaps found in v1.

| Version | Date | Change |
| --- | --- | --- |
| 2.0 | 2026-10-12 | Target architecture FastAPI + SQLite + Node.js frontend; GAP-01 to GAP-13 resolved as requirements |
| 1.0 | 2026-10-12 | As-built specification reverse-engineered from `ClinicERP.html` |

## 1. Introduction

This SRS v2.0 is the build specification for ClinicERP: it keeps every v1 function and moves the system to a server with real authentication, audit, and a shared database.

### 1.1 Purpose

Give the development team and the clinic owner one agreed baseline for building, testing, and accepting ClinicERP v2.

### 1.2 Scope

In scope: patients, appointments, clinical notes (FDI dental chart with history, Fitzpatrick skin type), services and prices, billing, payments and refunds, expenses, inventory with stock movements, staff, attendance, payroll with doctor commission, reports, audit log, settings, backup and restore, migration of v1 data.

Out of scope for v2: insurance claims, e-prescriptions, SMS/email reminders, patient portal, more than two clinics, native mobile apps.

### 1.3 Definitions

| Term | Meaning |
| --- | --- |
| Frontend | Next.js application running on Node.js; renders the UI and calls the API |
| API | FastAPI (Python) REST service; the only component that reads or writes the database |
| SQLite (WAL) | Single-file database in write-ahead-log mode, allowing concurrent reads with one writer |
| RBAC | Role-based access control, enforced by the API on every request |
| JWT | Signed access token; stored in an httpOnly cookie, never in browser storage |
| Clinic | `dental`, `derma`, or `both` for shared resources |
| FDI | International tooth numbering: 11–48 permanent, 51–85 primary |
| Fitzpatrick | Skin type classification I–VI |
| Doctor share | Doctor's percentage of a line's net value after discount and lab cost |
| Posted invoice | An invoice that has a payment or has been printed; it can no longer be edited |
| Cash basis | Revenue counted when a payment is received |

### 1.4 References

- SRS v1.0 (this doc's version history): as-built specification of `ClinicERP.html`.
- FastAPI, SQLAlchemy 2, Alembic, Next.js documentation (versions fixed in section 2.1).

## 2. Overall Description

ClinicERP v2 is a three-tier web application hosted on one clinic server: Node.js frontend, FastAPI backend, SQLite database.

### 2.1 Technology stack

| Layer | Technology | Notes |
| --- | --- | --- |
| Frontend | Node.js 20 LTS, Next.js 14+ (React, TypeScript) | Server-side rendering; calls the API from the Next.js server so the JWT cookie never reaches client scripts |
| UI kit | Tailwind CSS with RTL support | English and Arabic layouts |
| Backend | Python 3.12, FastAPI, Pydantic v2 | OpenAPI schema generated automatically at `/docs` |
| Data access | SQLAlchemy 2.0 ORM, Alembic migrations | All schema changes through versioned migrations |
| Database | SQLite 3.40+ in WAL mode, foreign keys ON | One file `clinic.db` on the server |
| Auth | Argon2id password hashing, JWT access (15 min) + refresh (8 h) tokens | Tokens in httpOnly, Secure, SameSite=Strict cookies |
| Server | Uvicorn (API), Node (frontend), Nginx reverse proxy with TLS | Optional Docker Compose for deployment |
| Tests | pytest (API), Playwright (UI) | Run in CI on every change |

### 2.2 User roles and permissions

The API enforces this matrix on every request; the frontend only hides what the user cannot use.

| Module | Admin | Doctor | Nurse | Assistant | Receptionist | Finance |
| --- | --- | --- | --- | --- | --- | --- |
| Dashboard | Full | Clinical | Clinical | Clinical | Front desk | Financial |
| Patients | Full | Read/write | Read/write | Read/write | Read/write | Read |
| Appointments | Full | Read/write | Read/write | Read/write | Read/write | — |
| Clinical notes | Full | Read/write (own notes editable 24 h) | Read/write | Read | — | — |
| Billing | Full | Read own | — | — | Create, take payments | Full except delete |
| Refunds and voids | Yes | — | — | — | — | Yes |
| Services & prices | Full | Read | Read | Read | Read | Edit prices and shares |
| Inventory | Full | Read | Read/write | Read/write | — | Read |
| Expenses | Full | — | — | — | — | Full |
| Staff records | Full | Own profile | Own profile | Own profile | Own profile | Read, edit salary fields only |
| Roles, logins, passwords | Yes | — | — | — | — | — |
| Attendance | All staff | Own | Own | Own | Own | All staff (read), approve |
| Payroll | Full | Own payslips | Own payslips | Own payslips | Own payslips | Full |
| Reports | Full | Own commission | — | — | Daily cash | Full |
| Audit log | Read | — | — | — | — | Read (financial events) |
| Settings, backup | Yes | — | — | — | — | — |

Staff assigned to one clinic see only that clinic's records plus shared ones; `both` staff see all. The v1 role "Other" is removed; such staff use attendance through a self-service login.

### 2.3 Deployment and operating environment

- One server (Linux or Windows) on the clinic network or a cloud VM, reachable over HTTPS only.
- Clients: current Chrome, Edge, Firefox, Safari on desktop, tablet (≥ 768 px) and phone (≥ 360 px).
- Printer support through the browser print dialog for invoices, payslips and reports.

### 2.4 Constraints and assumptions

- SQLite allows one writer at a time; v2 targets up to 30 concurrent users. Above that, the same SQLAlchemy models move to PostgreSQL without API changes.
- One currency per installation; VAT is configurable (rate and on/off) per installation.
- All dates are stored in UTC and shown in the clinic's time zone.

### 2.5 Migration from v1

- The API shall import a v1 JSON backup (`clinic-erp-backup-<date>.json`) into SQLite in one transaction, with a dry-run report first.
- Imported staff get no password; Admin sets one-time passwords that must be changed at first login.
- v1 invoice line `pct`/`lab` values (always empty in v1) are filled from the current service settings and flagged in the audit log.

### 2.6 Architecture

&#91;embedded content: ClinicERP v2 architecture · 4 tiers on one server\]

The browser never talks to the database or holds a token in script-readable storage; every rule in section 2.2 is enforced in FastAPI.

## 3. Functional Requirements

All "shall" statements are mandatory for v2 acceptance. Tags: **\[New\]** added in v2, **\[Changed\]** behaviour differs from v1; untagged rows carry over from v1 unchanged.

### 3.1 Authentication and accounts (AUTH)

| ID | Requirement |
| --- | --- |
| AUTH-01 | **\[Changed\]** Users shall sign in with username and password (min. 8 characters); passwords are stored as Argon2id hashes only. |
| AUTH-02 | **\[New\]** Accounts created or reset by Admin shall get a one-time password that must be changed at first sign-in. No default or demo password exists. |
| AUTH-03 | **\[New\]** After 5 failed attempts in 15 minutes the account shall lock for 15 minutes; Admin can unlock it. |
| AUTH-04 | **\[Changed\]** Sessions shall use a 15-minute access token and an 8-hour refresh token in httpOnly cookies; idle sessions end after 30 minutes. |
| AUTH-05 | **\[Changed\]** Only Admin shall create accounts, change roles, reset passwords, or deactivate users. Finance cannot change role or credentials (closes GAP-01). |
| AUTH-06 | At least one active Admin shall always remain. |
| AUTH-07 | **\[New\]** Every user shall change their own password from their profile. |

### 3.2 Access control and clinic scope (SCOPE)

| ID | Requirement |
| --- | --- |
| SCOPE-01 | **\[Changed\]** The API shall check role permission (section 2.2) on every endpoint and return 403 when denied. |
| SCOPE-02 | **\[New\]** Staff assigned to one clinic shall only read and write that clinic's records and shared (`both`) records. |
| SCOPE-03 | Users with access to both clinics shall switch the view between Both, Dental, and Derma. |
| SCOPE-04 | Admin shall configure the two clinic names, currency, VAT rate, time zone, and logo. |

### 3.3 Dashboard (DASH)

| ID | Requirement |
| --- | --- |
| DASH-01 | The dashboard shall show today's appointments, total patients, and low-stock items. |
| DASH-02 | Finance and Admin shall also see month-to-date revenue, expenses, outstanding balances, and a 6-month revenue chart per clinic. |
| DASH-03 | **\[Changed\]** Doctors shall see their own schedule, today's follow-ups, and month-to-date commission. |
| DASH-04 | **\[New\]** Items expiring within 30 days shall be listed next to low-stock items. |

### 3.4 Patients (PAT)

| ID | Requirement |
| --- | --- |
| PAT-01 | Users shall create, edit, search and export patients; full name and phone are mandatory. |
| PAT-02 | **\[New\]** On create, the system shall warn about possible duplicates (same phone, or same name and date of birth). |
| PAT-03 | **\[New\]** Patients shall get a file number, e.g. `P-000123`, unique and never reused. |
| PAT-04 | The patient file shall have tabs: Overview, Clinical notes, Dental chart (dental patients only), Appointments, Billing, Documents. |
| PAT-05 | Allergies and outstanding balance shall show as alerts in the patient header. |
| PAT-06 | **\[Changed\]** Patients shall be archived, not deleted; archived patients are hidden from lists and kept with all records. Only Admin may archive. |
| PAT-07 | **\[New\]** Users shall attach files (images, PDF, max 10 MB each) to a patient. |

### 3.5 Dental chart (CHART)

| ID | Requirement |
| --- | --- |
| CHART-01 | **\[Changed\]** The chart shall show permanent (11–48) and primary (51–85) dentition, switchable. |
| CHART-02 | **\[Changed\]** Each change shall add a dated entry (tooth, surface optional, condition, note, user, visit); the chart shows the latest condition and the full history per tooth (closes GAP-12). |
| CHART-03 | Conditions: Healthy, Caries, Filling, Crown, Root canal, Implant, Missing, Planned extraction, each with a colour and legend. |

### 3.6 Appointments (APPT)

| ID | Requirement |
| --- | --- |
| APPT-01 | **\[Changed\]** Users shall view appointments by day and by week, per doctor or per room. |
| APPT-02 | An appointment shall hold patient, clinic, doctor, service, date, time, duration, room, status, notes. |
| APPT-03 | Choosing a service shall fill duration and clinic. |
| APPT-04 | Status: Scheduled, Confirmed, Checked-in, In progress, Completed, Cancelled, No-show; every change is logged with user and time. |
| APPT-05 | **\[Changed\]** The API shall block overlapping active bookings for the same doctor, room, or patient; Admin may override with a written reason (closes GAP-10). |
| APPT-06 | **\[New\]** Marking an appointment Completed shall offer to open a clinical note and a draft invoice pre-filled with patient, doctor, clinic and service (closes GAP-11). |

### 3.7 Clinical notes (VISIT)

| ID | Requirement |
| --- | --- |
| VISIT-01 | A note shall hold patient, clinic, doctor, date, complaint, diagnosis, treatment/plan, prescription, follow-up date, notes, and link to its appointment when there is one. |
| VISIT-02 | Dental notes add teeth involved (FDI); derma notes add Fitzpatrick skin type and area treated. |
| VISIT-03 | **\[New\]** The author may edit a note for 24 hours; after that it is locked and changes are made by addendum. |
| VISIT-04 | **\[New\]** A follow-up date shall create a follow-up task visible on the dashboard. |

### 3.8 Services and prices (SVC)

| ID | Requirement |
| --- | --- |
| SVC-01 | Admin and Finance shall maintain a price list per clinic: name, category, duration, price, VAT on/off. |
| SVC-02 | Each service shall hold doctor share % (blank = doctor default) and lab/material cost per unit. |
| SVC-03 | **\[New\]** A service may list inventory items and quantities consumed per unit (closes GAP-11). |
| SVC-04 | **\[Changed\]** Services in use shall be deactivated, not deleted (closes GAP-13). |

### 3.9 Billing (INV)

| ID | Requirement |
| --- | --- |
| INV-01 | An invoice shall hold patient, clinic, doctor, date, lines, discount (amount or %), VAT, payments, notes. |
| INV-02 | **\[Changed\]** The API shall assign invoice numbers per clinic in sequence, e.g. `D-2026-00001`, with no gaps. |
| INV-03 | **\[Changed\]** Picking a service shall copy its price, doctor share % and lab cost onto the line; Finance may override them per line (closes GAP-04). |
| INV-04 | Subtotal = sum(qty × price); total = subtotal − discount + VAT; balance = total − payments + refunds. |
| INV-05 | Payments shall record amount, date, method, received by; partial payments allowed. |
| INV-06 | **\[New\]** An invoice is Draft until its first payment or print; then it is Posted and its lines, discount and prices are locked (closes GAP-05). |
| INV-07 | **\[New\]** Posted invoices shall be corrected only by void (with reason) or credit note; payments are reversed by refund entries, never deleted. |
| INV-08 | Users shall print invoices and receipts (PDF) with the clinic logo, and export the list to CSV/Excel. |
| INV-09 | **\[New\]** Posting an invoice shall deduct the linked inventory items of its services as stock movements. |

### 3.10 Inventory (STOCK)

| ID | Requirement |
| --- | --- |
| STOCK-01 | Users shall maintain items: clinic, category, unit, reorder level, unit cost, supplier, expiry. |
| STOCK-02 | **\[Changed\]** Quantity shall change only through stock movements (receive, use, adjust, auto-deduct from invoice), each with user, time and reason. |
| STOCK-03 | Items at or below reorder level are flagged low; items within 30 days of expiry are flagged expiring. |

### 3.11 Expenses (EXP)

| ID | Requirement |
| --- | --- |
| EXP-01 | Finance and Admin shall record expenses: date, category, description, amount, clinic, paid to, receipt attachment. |
| EXP-02 | **\[Changed\]** The list shall filter by date range and category and total only what is shown (closes GAP-13). |

### 3.12 Staff (STAFF)

| ID | Requirement |
| --- | --- |
| STAFF-01 | Admin shall maintain staff: name, role, clinic, specialty, contact, hire date, active flag. |
| STAFF-02 | Admin and Finance shall maintain pay terms: monthly salary, default doctor share %. |
| STAFF-03 | **\[Changed\]** Staff with history shall be deactivated, not deleted (closes GAP-13). |

### 3.13 Attendance (ATT) — new module (closes GAP-06)

| ID | Requirement |
| --- | --- |
| ATT-01 | **\[New\]** Each user shall clock in and clock out from the app; the server records the time. |
| ATT-02 | **\[New\]** A clock-in later than shift start plus grace minutes (defaults 09:00 and 10 min) shall be marked Late. |
| ATT-03 | **\[New\]** Finance and Admin shall record Absent, Paid leave, Unpaid leave, Day off, and correct times with a reason. |
| ATT-04 | **\[New\]** A monthly attendance sheet per employee shall be viewable and exportable. |

### 3.14 Payroll (PAY) — new module (closes GAP-03, GAP-06)

| ID | Requirement |
| --- | --- |
| PAY-01 | **\[New\]** Finance shall generate a monthly payroll run that creates one line per active employee. |
| PAY-02 | **\[New\]** Base = monthly salary; unpaid leave and absence deduct salary ÷ working days (default 26) per day. |
| PAY-03 | **\[New\]** Doctor commission = sum over paid invoice lines of max(0, qty × price × (1 − discount share) − qty × lab cost) × share %, scaled by the share of the invoice paid in that month. |
| PAY-04 | **\[New\]** Finance shall add bonuses and deductions with notes; net = base + commission + bonus − deductions. |
| PAY-05 | **\[New\]** A run moves Draft → Approved (Admin) → Paid (date, method); approved runs are locked. |
| PAY-06 | **\[New\]** Each employee shall view and print their own payslips. |

### 3.15 Reports (REP)

| ID | Requirement |
| --- | --- |
| REP-01 | Reports shall run for a date range and follow clinic scope. |
| REP-02 | **\[Changed\]** KPIs: revenue collected, refunds, expenses, actual payroll from payroll runs, doctor commission per PAY-03, net profit. |
| REP-03 | Breakdowns: revenue by clinic, doctor, payment method and service; expenses by category; commission per doctor with line detail. |
| REP-04 | **\[New\]** Daily cash report per user (receptionist close-out). |
| REP-05 | **\[New\]** Accounts receivable aging: 0–30, 31–60, 61–90, 90+ days. |
| REP-06 | All reports shall export to CSV, Excel and PDF. |

### 3.16 Audit (AUD) — new module

| ID | Requirement |
| --- | --- |
| AUD-01 | **\[New\]** The API shall log every create, update, delete, sign-in, failed sign-in, void, refund, override and export: user, time, entity, record id, before and after values. |
| AUD-02 | **\[New\]** The audit log shall be append-only and viewable by Admin (all) and Finance (financial events), filterable by user, entity and date. |
| AUD-03 | **\[New\]** Every view of a patient file shall be logged. |

### 3.17 Settings, backup and data (SET)

| ID | Requirement |
| --- | --- |
| SET-01 | **\[Changed\]** The server shall back up the database nightly with the SQLite online backup API, keep 30 daily copies, and copy them off the server (closes GAP-08). |
| SET-02 | Admin shall download a backup on demand and restore one after confirmation; restore is logged. |
| SET-03 | **\[New\]** Admin shall import a v1 JSON backup (section 2.5). |
| SET-04 | **\[Changed\]** "Erase everything" is removed; test data is cleared only on a fresh install. |

## 4. Data Model

The database is SQLite with 24 normalised tables; every table has an integer primary key `id`, `created_at`, `created_by`, `updated_at`, and foreign keys are enforced.

| Table | Key columns | Constraints and links |
| --- | --- | --- |
| clinics | code (`dental`, `derma`), name, invoice\_prefix | 2 rows |
| users | username, password\_hash, role, clinic\_scope, staff\_id, must\_change\_pw, failed\_logins, locked\_until, active | username unique; role in 6 roles |
| staff | name, role, clinic\_scope, specialty, phone, email, hire\_date, salary, default\_share\_pct, active | 1 user per staff max |
| patients | file\_no, name, phone, email, dob, gender, address, insurance, allergies, history, notes, archived | file\_no unique; index on phone, name |
| patient\_files | patient\_id, filename, mime, size, path | max 10 MB |
| appointments | patient\_id, clinic\_id, doctor\_id, service\_id, room, start\_at, end\_at, status, notes, override\_reason | API checks no overlap per doctor, room, patient |
| appointment\_status\_log | appointment\_id, from\_status, to\_status, user\_id, at | append-only |
| visits | patient\_id, clinic\_id, doctor\_id, appointment\_id, date, complaint, diagnosis, treatment, prescription, teeth, skin\_type, area, follow\_up, notes, locked\_at | locked 24 h after create |
| visit\_addenda | visit\_id, text, user\_id | append-only |
| tooth\_entries | patient\_id, tooth (11–85), surface, condition, note, visit\_id, user\_id, at | history per tooth |
| services | clinic\_id, name, category, duration\_min, price, vat\_applies, share\_pct, lab\_cost, active |  |
| service\_items | service\_id, item\_id, qty\_per\_unit | links services to stock |
| invoices | number, clinic\_id, patient\_id, doctor\_id, date, discount\_type, discount\_value, vat\_rate, status (Draft, Posted, Void), void\_reason, posted\_at | number unique per clinic |
| invoice\_lines | invoice\_id, service\_id, description, qty, unit\_price, share\_pct, lab\_cost | values copied from service at pick time |
| payments | invoice\_id, date, amount, method, received\_by, kind (Payment, Refund) | never deleted |
| credit\_notes | invoice\_id, number, amount, reason |  |
| inventory\_items | clinic\_id (null = shared), name, category, unit, reorder\_level, unit\_cost, supplier, expiry | qty = sum of movements |
| stock\_movements | item\_id, kind (Receive, Use, Adjust, Auto), qty (+/−), reason, invoice\_id, user\_id, at | append-only |
| expenses | clinic\_id, date, category, description, amount, paid\_to, receipt\_path |  |
| attendance | staff\_id, date, clock\_in, clock\_out, status, note, corrected\_by | one row per staff per day |
| payroll\_runs | month, status (Draft, Approved, Paid), approved\_by, paid\_on, method | one run per month |
| payroll\_lines | run\_id, staff\_id, base, absence\_deduction, commission, bonus, deductions, net, note |  |
| audit\_log | user\_id, at, action, entity, entity\_id, before\_json, after\_json, ip | append-only; no update or delete endpoint |
| settings | key, value | currency, VAT rate, time zone, shift\_start, grace\_min, work\_days |

**Business rules**

- Money is stored as integer minor units (cents) to avoid rounding errors.
- Stock on hand = sum of `stock_movements.qty`; it may not go below zero without an Adjust with reason.
- Balance = invoice total − payments + refunds; status Paid, Partial or Unpaid is derived, not stored.
- Doctor commission follows PAY-03; it is computed from `invoice_lines.share_pct` and `lab_cost` as stored on the line, so later price changes do not alter past commission.

## 5. External Interface Requirements

The Next.js frontend is the only UI; it reaches data only through the versioned FastAPI REST API under `/api/v1`.

### 5.1 User interface (Next.js on Node.js)

- **UI-01** Layout: sidebar navigation filtered by role, top bar with clinic switcher, language switch (English / Arabic), user menu.
- **UI-02** Below 1024 px the sidebar shall collapse into a menu button; every screen shall work at 360 px width (closes GAP-09).
- **UI-03** Arabic shall render right-to-left with Arabic labels; dates and numbers follow the chosen locale.
- **UI-04** Lists share one pattern: search, filters, paging (50 rows), export, "+ New", row actions by permission.
- **UI-05** Forms validate on the client and show the API's field errors; mandatory fields marked \*.
- **UI-06** Confirmations, warnings and errors use in-app dialogs and toasts, never browser `alert`/`confirm`/`prompt`.
- **UI-07** Dental blue and Derma purple colour coding is kept; status badges meet WCAG 2.1 AA contrast.

### 5.2 Outputs

| Output | Format | Who |
| --- | --- | --- |
| Invoice, receipt, credit note | PDF, A4 and 80 mm thermal | Billing roles |
| Payslip | PDF | Finance, Admin, the employee |
| Reports | CSV, Excel, PDF | Per section 2.2 |
| List exports | CSV, Excel (UTF-8) | Roles with access to the list |
| Backup | SQLite file, downloadable by Admin | Admin |

### 5.3 REST API (FastAPI)

All endpoints take and return JSON, are described in OpenAPI at `/api/v1/docs`, and return 401 (not signed in), 403 (no permission), 409 (conflict such as overlapping booking or locked record), 422 (validation).

| Resource | Endpoints | Notes |
| --- | --- | --- |
| Auth | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/change-password` | Sets and clears httpOnly cookies |
| Users | `GET/POST /users`, `PATCH /users/{id}`, `POST /users/{id}/reset-password`, `POST /users/{id}/unlock` | Admin only |
| Patients | `GET/POST /patients`, `GET/PATCH /patients/{id}`, `POST /patients/{id}/archive`, `GET/POST /patients/{id}/files` | `?q=` search, paging |
| Dental chart | `GET /patients/{id}/teeth`, `POST /patients/{id}/teeth` | POST adds a history entry |
| Appointments | `GET/POST /appointments`, `PATCH /appointments/{id}`, `POST /appointments/{id}/status` | `?from&to&doctor&room`; 409 on overlap |
| Visits | `GET/POST /visits`, `PATCH /visits/{id}`, `POST /visits/{id}/addenda` | PATCH refused after lock |
| Services | `GET/POST /services`, `PATCH /services/{id}`, `PUT /services/{id}/items` |  |
| Invoices | `GET/POST /invoices`, `PATCH /invoices/{id}`, `POST /invoices/{id}/post`, `POST /invoices/{id}/void`, `POST /invoices/{id}/credit-notes`, `GET /invoices/{id}/pdf` | PATCH refused when Posted |
| Payments | `POST /invoices/{id}/payments`, `POST /payments/{id}/refund` | No DELETE |
| Inventory | `GET/POST /inventory`, `PATCH /inventory/{id}`, `POST /inventory/{id}/movements` |  |
| Expenses | `GET/POST /expenses`, `PATCH /expenses/{id}` |  |
| Staff | `GET/POST /staff`, `PATCH /staff/{id}` | Salary fields by Admin/Finance only |
| Attendance | `POST /attendance/clock-in`, `POST /attendance/clock-out`, `GET /attendance`, `PATCH /attendance/{id}` |  |
| Payroll | `POST /payroll/runs`, `GET /payroll/runs/{id}`, `POST /payroll/runs/{id}/approve`, `POST /payroll/runs/{id}/pay`, `GET /payroll/lines/{id}/payslip` |  |
| Reports | `GET /reports/{name}?from&to&clinic&format=` | name = summary, revenue, commission, cash, aging, expenses |
| Audit | `GET /audit` | Admin, Finance (financial only) |
| Admin | `GET /settings`, `PUT /settings`, `POST /admin/backup`, `POST /admin/restore`, `POST /admin/import-v1` | Admin only |

## 6. Non-Functional Requirements

Each requirement has a measurable acceptance check for v2 sign-off.

| ID | Area | Requirement | Acceptance check |
| --- | --- | --- | --- |
| NFR-01 | Authentication | Argon2id hashes, lockout after 5 failures, no default passwords | Pen test finds no plain-text credentials; 6th wrong attempt is refused |
| NFR-02 | Authorisation | Every endpoint checks role and clinic scope on the server | Automated test calls every endpoint as every role; all denials return 403 |
| NFR-03 | Transport | HTTPS only (TLS 1.2+), HSTS, secure cookies, CSRF protection on state-changing requests | SSL Labs grade A; HTTP redirects to HTTPS |
| NFR-04 | Privacy | Database file and backups encrypted at rest (disk or file encryption); patient-file views logged | Backups unreadable without key; AUD-03 test passes |
| NFR-05 | Audit | Append-only audit log kept at least 7 years | No API or UI path updates or deletes audit rows |
| NFR-06 | Integrity | Posted invoices, approved payroll, locked notes cannot be edited | API returns 409 on every such attempt |
| NFR-07 | Backup and recovery | Nightly backup, 30 copies, off-server copy; RPO 24 h, RTO 2 h | Monthly restore drill on a spare machine succeeds |
| NFR-08 | Performance | Lists and searches return in under 1 s, saves in under 500 ms, with 20,000 patients, 100,000 invoices, 30 concurrent users | Load test with that data set passes at p95 |
| NFR-09 | Concurrency | SQLite WAL mode, 5 s busy timeout; edits use a version column and reject stale updates with 409 | Two users editing one record: the second gets a conflict message, no lost update |
| NFR-10 | Availability | 99.5% during clinic hours; services restart automatically | Uptime monitor over the first 3 months |
| NFR-11 | Usability | Works on desktop, tablet (≥ 768 px) and phone (≥ 360 px); common tasks (book, invoice, pay) in 3 screens or fewer | Usability test with reception and one doctor |
| NFR-12 | Localisation | English and Arabic with full RTL; currency and VAT configurable | Every screen reviewed in Arabic |
| NFR-13 | Accessibility | WCAG 2.1 AA for contrast, keyboard use and labels | Automated axe scan shows no serious issues |
| NFR-14 | Maintainability | Typed code (TypeScript, Python type hints), Alembic migrations, ≥ 80% test coverage on billing, commission and payroll | CI fails below threshold |
| NFR-15 | Scalability | SQLAlchemy models portable to PostgreSQL without API change | Test suite passes against PostgreSQL |

## 7. Gap Resolution (v1 → v2)

All 13 gaps from the v1 review are closed in this specification. Status here means specified; implementation is tracked against the requirement IDs.

| Gap | v1 problem | v2 resolution | Requirements | Status |
| --- | --- | --- | --- | --- |
| GAP-01 | Finance could change any role and PIN | Only Admin manages roles and credentials, enforced by the API | AUTH-05, SCOPE-01 | Done |
| GAP-02 | Plain-text PINs, demo PIN 1234, checks only in the browser | Argon2id passwords, one-time first password, lockout, server-side RBAC | AUTH-01–04, NFR-01–03 | Done |
| GAP-03 | Commission ignored service %, lab cost and discount | One commission formula from stored line values, used by payroll and reports | PAY-03, REP-02 | Done |
| GAP-04 | Invoice lines lost share % and lab cost | Copied from the service when a line is picked | INV-03 | Done |
| GAP-05 | Paid invoices editable, payments deletable | Draft → Posted lock, void with reason, credit notes, refunds | INV-06, INV-07, NFR-06 | Done |
| GAP-06 | Attendance and payroll had no screens | New Attendance and Payroll modules | ATT-01–04, PAY-01–06 | Done |
| GAP-07 | Server mode unreachable | FastAPI + SQLite server with Next.js frontend | Sections 2.1, 2.6, 5.3 | Done |
| GAP-08 | Data only in browser storage | Nightly server backups, 30 copies, off-server; restore drills | SET-01, NFR-07 | Done |
| GAP-09 | No navigation under 800 px | Collapsible menu; works from 360 px | UI-02, NFR-11 | Done |
| GAP-10 | Doctor-only clash warning | Server blocks doctor, room and patient overlaps; Admin override with reason | APPT-05 | Done |
| GAP-11 | Modules not linked; stock drifted | Appointment → note → invoice flow; services deduct stock | APPT-06, SVC-03, INV-09, STOCK-02 | Done |
| GAP-12 | Tooth chart overwrote history | Dated tooth entries, primary dentition, dental patients only | CHART-01, CHART-02, PAT-04 | Done |
| GAP-13 | Deletes left blank names; expense total ignored dates | Archive/deactivate instead of delete; date-filtered totals | PAT-06, SVC-04, STAFF-03, EXP-02 | Done |

### 7.1 Open decisions

- [ ] Hosting: on-premise clinic server or cloud VM?
- [ ] VAT: is it charged on any services today, and at what rate?
- [ ] Invoice numbering format `D-2026-00001` / `M-2026-00001`: confirm, or keep `INV-0001`.
