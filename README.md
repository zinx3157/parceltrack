# ParcelDesk — multi-carrier parcel tracking (DHL · FedEx · Aramex · UPS · Colissimo · 17TRACK)

A self-hosted parcel control tower for operations that move 10–1000+ shipments a month.
It polls the official carrier APIs (or takes manual updates), keeps a full event history
per parcel, prints barcode labels, tracks what is physically on your warehouse shelves,
alerts your team and clients by email or WhatsApp/SMS, and gives every client their own
password-protected tracking portal.

Built to run on your own PC or server — no monthly subscription, your data never leaves
your machine.

---

## 1. What you get

**Tracking**
- DHL Express (Shipment Tracking – Unified API), FedEx (OAuth + Track API), Aramex (Shipping API v2)
- UPS (OAuth + Track API), DHL eCommerce / Parcel, Colissimo / La Poste (Enterprise REST),
  and **17TRACK** as an aggregator covering EMS, China Post, national posts and 3,000+ couriers
- Automatic carrier detection from the tracking number format
- Manual / "other carrier" mode for shipments booked by phone, WhatsApp or with local agents
- Background sync every N minutes + on-demand "Sync now" per parcel
- Full movement timeline with locations, timestamps and the carrier's own wording
- Deduplicated events (re-running a sync never duplicates history)

**Operations**
- Dashboard: open parcels, delivered (30d), in customs, exceptions, out for delivery, avg transit, on-time rate, stuck beyond SLA
- Filters: search (tracking / reference / description / notes), carrier, status, client, period
- Parcel detail: ETA, days in transit, weight, cost, origin/destination, internal notes
- Bulk import: paste a list, or upload CSV/Excel (recognises French/English column names too)
- Exports: styled Excel workbook (parcels + summary sheet) and CSV
- Reports: carrier performance, completion rates, average door-to-door transit, on-time %

**Clients**
- Client accounts with contact details, reference prefixes and per-client parcel views
- Per-parcel share link and per-client portal link (read-only, no login, revocable)
- Optional automatic client emails on status change

**Warehouse receiving (barcode)**
- Dedicated **Receiving** screen: scan or type a barcode and the parcel is looked up, checked in
  and stamped with who received it and where it is stored (rack/bin)
- "Received at warehouse" status with the full receiving detail in the parcel history
- Expected-inbound to-do list and a recently-received list, live while you scan
- Alternate barcode field for labels that differ from the tracking number; partial scans still match
- Storage location and barcode are importable and exportable, and searchable
- **Partial shipments:** set how many cartons a tracking number contains, then check the cartons in
  one by one — each carton gets its own receipt row (who, when, where), and the parcel is only
  "complete" when every carton has arrived
- **Stock view:** everything currently on the shelves with carton counts, days on shelf and an
  ageing flag after your threshold; release to the consignee (with signature-ish detail) and undo a
  release if the hand-over was a mistake; Excel export of the stock list
- **Release** is blocked until all expected cartons have been received

**Labels (Code 128, printable)**
- Barcode and full label rendered as SVG by the app itself — no barcode library, no internet, no licence
- Label carries your company, carrier + tracking number, client reference, description, carton
  "2 of 3", storage slot, ETA and print timestamp
- One label per carton, batch printing from the stock list or a single parcel, and a print sheet
  sized for 100×60 mm (label size configurable via `LABEL_WIDTH_MM` / `LABEL_HEIGHT_MM` / `LABEL_MODULE_MM`)
- Code 128 with the compact Code C subset for numeric tracking numbers (a self-test in Diagnostics
  cross-checks the whole symbol table for you)

**Client portal logins**
- Each client can sign in at `/portal` with their email and a password you set — they see only their
  own shipments, carton progress, warehouse status and releases
- Staff controls: give portal access, reset the password, revoke it (revoking kills live sessions)
- Sessions are invalidated when the password changes; the old read-only share links still work

**Alerts (email + WhatsApp/SMS)**
- Status-change alerts (configurable which statuses trigger: delivered, exception, customs, out for delivery…)
- "Stuck in customs" and "no movement" alerts after your SLA thresholds
- Daily digest of open parcels and items needing attention
- **WhatsApp / SMS** alerts through three providers: Meta WhatsApp Cloud API, Twilio (SMS or
  WhatsApp), or a generic HTTP webhook (Africa's Talking, Vonage, n8n, your own bot)
- Per-user and per-client opt-in: phone number fields, "receive SMS/WhatsApp" flags
- Every alert — email or text — is stored in an in-app log with its channel, even when nothing
  is configured yet

**Faster last mile**
- Parcels that reach *out for delivery* are polled on their own tighter schedule (default hourly,
  configurable in Settings → Automation) instead of waiting for the next full sync
- Warehouse ageing alert: parcels sitting too long past your threshold are flagged in Stock and
  reported in the alerts log

**Self-test / diagnostics**
- In-app **Diagnostics** page: database read/write round-trip, pending schema changes, disk space,
  scheduler jobs, barcode engine, carrier credentials, SMTP, WhatsApp/SMS, alert log, warehouse,
  SLA and cost efficiency — each check reports pass/warn/fail plus a plain-language reason
- Optional live probes: one real tracking request per configured carrier
- Three automated suites: `tests/test_all_features.py` (62 checks), `tests/smoke_test.py`
  (41 checks against a running server), `tests/test_messaging_webhook.py` (WhatsApp/SMS pipeline)

**Team & security**
- Logins with roles: **admin** (everything), **operator** (add/edit/sync), **viewer** (read-only)
- JWT sessions, PBKDF2 password hashing, per-user email-alert preference
- Per-user accounts, password resets by admin, account disable

---

## 2. Quick start

```bash
cd parceltrack
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run.py --demo               # explore with simulated carrier data
```

Open **http://localhost:8000** and sign in with the first-run admin account
(`admin@example.com` / `admin123` — change it immediately, see §4).

Going live with real carriers:

```bash
cp .env.example .env               # then fill in your carrier credentials
python run.py                      # DEMO_MODE=false pulls real carrier data
```

Full per-OS and Docker instructions: **[docs/SETUP.md](docs/SETUP.md)**
Carrier credential walkthroughs: **[docs/CARRIERS.md](docs/CARRIERS.md)**

---

## 3. Configuration

Everything lives in `.env` (see `.env.example` for the complete, commented list).

| Variable | Purpose |
|---|---|
| `DEMO_MODE` | `true` = simulated carrier data (no credentials needed) |
| `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` | Account created on first start |
| `SECRET_KEY` | Signs login tokens — set a long random value in production |
| `DATABASE_URL` | `sqlite:///./data/parceltrack.db` by default; PostgreSQL supported |
| `SYNC_INTERVAL_MINUTES` | How often carriers are polled (default 30) |
| `DHL_API_KEY` / `DHL_API_SECRET` | DHL Express credentials |
| `FEDEX_CLIENT_ID` / `FEDEX_CLIENT_SECRET` | FedEx OAuth credentials |
| `ARAMEX_USERNAME` / `_PASSWORD` / `_ACCOUNT_NUMBER` / `_ACCOUNT_PIN` / `_ACCOUNT_ENTITY` / `_ACCOUNT_COUNTRY_CODE` | Aramex credentials |
| `UPS_CLIENT_ID` / `UPS_CLIENT_SECRET` | UPS OAuth credentials |
| `DHL_ECOM_API_KEY` | DHL eCommerce / Parcel tracking (can reuse `DHL_API_KEY`) |
| `COLISSIMO_API_KEY` / `COLISSIMO_CONTRACT_NUMBER` / `COLISSIMO_PASSWORD` | Colissimo Enterprise |
| `TRACK17_API_KEY` | 17TRACK aggregator (EMS, postal, other couriers) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | Email alerts |
| `MESSAGING_PROVIDER` | `whatsapp` \| `twilio` \| `webhook` \| `none` |
| `WHATSAPP_TOKEN` / `WHATSAPP_PHONE_ID` | Meta WhatsApp Cloud API |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM` / `TWILIO_USE_WHATSAPP` | Twilio SMS/WhatsApp |
| `WEBHOOK_URL` / `WEBHOOK_TOKEN` / `WEBHOOK_PAYLOAD_TEMPLATE` | Generic messaging gateway |
| `MESSAGING_ALERT_STATUSES` / `MESSAGING_RECIPIENTS` | Which statuses trigger a text, fallback numbers |
| `ALERTS_ENABLED`, `ALERT_ON_STATUSES` | Master switch and which statuses trigger emails |
| `STUCK_CUSTOMS_DAYS`, `STUCK_TRANSIT_DAYS` | SLA thresholds for stuck alerts |
| `PUBLIC_BASE_URL` | Base URL used in client share links and emails |

A missing carrier credential never breaks the app — that carrier simply reports
"not configured" in **Settings → Carriers** and stays in manual mode.

---

## 4. Production checklist

1. **Change the admin password** (Settings → Users → Reset password) and create one
   account per colleague instead of sharing logins.
2. **Set `SECRET_KEY`** to a long random string:
   `python -c "import secrets;print(secrets.token_urlsafe(48))"`
3. **Set `PUBLIC_BASE_URL`** to the address your clients will open (e.g. `https://parcels.yourcompany.mg`).
4. **Configure SMTP** so alerts actually leave the building (Gmail needs an App Password).
5. **Put it behind HTTPS** — reverse proxy examples in [docs/SETUP.md](docs/SETUP.md).
6. **Back up `data/parceltrack.db`** (or your PostgreSQL database) daily. A one-line cron
   example is in the setup guide.
7. Run it as a service so it survives reboots (systemd unit and NSSM instructions included).

---

## 5. Project structure

```
parceltrack/
├── run.py                     # launcher (--demo, --port, --host, --seed-demo)
├── requirements.txt
├── .env.example               # every configuration option, commented
├── run-demo.sh / run-demo.bat # one-command demo launcher (Linux/macOS, Windows)
├── app/
│   ├── main.py                # FastAPI app factory, static SPA hosting
│   ├── config.py              # settings (env + .env)
│   ├── migrations.py          # additive schema updates for existing installs
│   ├── database.py            # SQLAlchemy engine/session (SQLite or PostgreSQL)
│   ├── models.py              # User, Client, Parcel, ParcelEvent, Notification, SyncRun, Setting
│   ├── schemas.py             # request/response models
│   ├── security.py            # password hashing, JWT, role dependencies
│   ├── scheduler.py           # periodic sync / stuck check / daily digest
│   ├── seed.py                # first admin + demo dataset
│   ├── carriers/
│   │   ├── dhl.py  fedex.py  aramex.py  ups.py  dhlecom.py  colissimo.py  track17.py
│   │   ├── demo.py                        # simulated carrier (used in demo mode)
│   │   ├── manual.py  base.py             # manual mode + status normalisation (EN/FR)
│   │   └── __init__.py                    # registry, auto-detection, public tracking URLs
│   ├── services/
│   │   ├── tracking.py        # sync engine, event dedupe, stuck detection, OFD sweep
│   │   ├── receiving.py       # barcode lookup, carton receipts, stock, release
│   │   ├── barcode.py         # Code 128 encoder + label SVG (self-tested)
│   │   ├── messaging.py       # WhatsApp / SMS / webhook delivery
│   │   ├── alerts.py          # email + text alerts, digest, notification log
│   │   ├── importer.py        # paste / CSV / Excel import
│   │   ├── reports.py         # KPIs, Excel & CSV export
│   │   └── parcels.py         # shared queries & serialisation
│   ├── api/                   # auth, parcels, clients, receiving, labels, portal, admin, public
│   └── static/                # dashboard UI (index.html, app.js, styles.css)
├── docs/SETUP.md  docs/CARRIERS.md
├── deploy/                    # Dockerfile, docker-compose, systemd unit, Windows scripts
└── tests/
    ├── test_all_features.py         # 62 checks — labels, portal, cartons, stock, sweeps
    ├── smoke_test.py                # 41 checks against a running installation
    ├── test_messaging_webhook.py    # end-to-end check of the WhatsApp/SMS pipeline
    ├── ui_smoke.js                  # every screen, normal + sandboxed browser (node)
    └── ui_live.js                   # every screen against a running server (node)
```

---

## 6. API quick reference

All endpoints live under `/api`. Interactive docs: **/docs** (Swagger UI).

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/login` | Get a session token |
| GET | `/api/parcels?q=&carrier=&status=&client_id=&days=` | List/search parcels |
| POST | `/api/parcels` | Add a parcel (carrier auto-detected if omitted) |
| GET | `/api/parcels/{id}` | Parcel + full event history |
| PATCH / DELETE | `/api/parcels/{id}` | Edit / delete |
| POST | `/api/parcels/{id}/sync` | Poll the carrier now |
| POST | `/api/parcels/{id}/events` | Add a manual tracking update |
| POST | `/api/parcels/{id}/share` | Create the client tracking link |
| POST | `/api/parcels/{id}/remind` | Email a status update to the client |
| POST | `/api/parcels/import` · `/import/file` | Bulk import from paste or CSV/XLSX (incl. barcode, storage_location) |
| GET | `/api/parcels/export.xlsx` · `/export.csv` | Exports (respect filters) |
| GET | `/api/parcels/stats?days=30` | Dashboard KPIs |
| GET | `/api/stuck` | Parcels past SLA |
| GET/POST | `/api/clients`, `/api/clients/{id}/portal` | Clients and portal links |
| GET/POST | `/api/clients/{id}/password` | Give / reset / revoke a client's portal login |
| POST | `/api/portal/login`, `/api/portal/change-password` | Client portal sign-in and password change |
| GET | `/api/portal/me`, `/api/portal/parcels` | What a signed-in client is allowed to see |
| GET | `/api/parcels/{id}/barcode.svg` | The parcel's Code 128 barcode as SVG |
| GET | `/api/labels/{id}.svg`, `/labels/{id}`, `/labels/print?ids=1,2` | Single label, print page, batch sheet |
| GET/POST | `/api/receiving/stock`, `/api/receiving/stock.xlsx` | Warehouse stock list and Excel export |
| POST | `/api/receiving/{id}/release`, `/api/receiving/{id}/release/undo` | Release from the warehouse / undo |
| GET | `/api/diagnostics?run_probes=false` | The self-test report used by the Diagnostics page |
| GET | `/api/carriers` | Which carriers are connected |
| POST | `/api/sync/run`, GET `/api/sync/runs` | Trigger and inspect syncs |
| GET | `/api/receiving/lookup?code=` | Find a parcel by tracking number or barcode |
| POST | `/api/receiving/scan` | Look up **and** check in (one call — ideal for scanners) |
| POST | `/api/receiving/{id}/receive` · `/undo` | Check in / clear a receipt |
| GET | `/api/receiving/pending` · `/recent` | Expected inbound and recently received lists |
| GET | `/api/notifications` | Alert log (each entry tagged with its channel) |
| GET | `/api/messaging` | WhatsApp/SMS provider status |
| POST | `/api/messaging/test` | Send a test WhatsApp/SMS message |
| GET/PUT | `/api/settings` | Runtime settings (sync interval, thresholds, company name) |
| GET | `/api/public/track/{token}` · `/api/public/client/{token}` | Public read-only views |
| GET/POST/PATCH | `/api/users` | Team management (admin) |

---

## 7. Verify your installation

Three suites, all safe to run on a live installation (they use their own data or clean up):

```bash
python tests/test_all_features.py        # 62 checks, in-process, throwaway database
python tests/smoke_test.py               # 41 checks (server must be running)
python tests/test_messaging_webhook.py   # WhatsApp/SMS pipeline, self-contained
node tests/ui_smoke.js                   # every screen, in a normal *and* a sandboxed browser
node tests/ui_live.js                    # the same screens driving a running installation
```

The two `node` suites are optional (they need Node.js, not part of the Python app) and check the
front end rather than the API: `ui_smoke.js` renders every screen against a stub DOM in two
environments — an ordinary browser and a locked-down one — while `ui_live.js` does the same against
a running installation, including the client portal. They exist because browser storage and the
history API are blocked in some embedded/locked-down contexts, and a front end that assumes them
would show a blank page instead of an error message.

`test_all_features.py` covers the Code 128 engine against the published symbol table, label
rendering, warehouse receiving with partial cartons, the stock list and ageing flag, release and
undo-release, the client portal (including that one client cannot see another's parcels and that
revoking access kills live sessions), the out-for-delivery sweep and the diagnostics report.

`smoke_test.py` drives a running installation over HTTP: login, stats, create/sync/import,
warehouse check-in, cartons, release, label printing, client portal login, diagnostics, exports,
then cleans up after itself.

`test_messaging_webhook.py` starts a local stand-in gateway, sends the test message and a real
delivery alert through it, and confirms both the delivery and the in-app log.

The same checks are visible in the app itself: open **Diagnostics** in the sidebar, where you can
also fire one live tracking request per configured carrier.

---

## 8. Notes & honest caveats

- The DHL, FedEx and Aramex adapters implement each carrier's **documented** request/response
  formats and normalise their statuses onto one internal scale. Carrier APIs evolve and
  access is account-specific, so validate with your own credentials: add one real parcel,
  press **Sync now**, and confirm the timeline appears. If a carrier changes a field name,
  only that one adapter file needs a small edit (`app/carriers/*.py`).
- FedEx requires your developer account to be granted the **Track API** project; without it
  every call returns an authorization error (the app shows the carrier's message).
- Aramex API credentials are issued by Aramex (they're not self-service like DHL/FedEx);
  the adapter accepts the documented account fields and tolerates the response variants
  Aramex has shipped over time. Some Aramex accounts are limited to their own shipments.
- Free tier rate limits apply. The default 30-minute sync interval keeps a few hundred
  parcels comfortably inside typical quotas; finished parcels (delivered/cancelled/returned)
  stop being polled automatically.
- Email delivery requires your own SMTP account; without it, alerts are still recorded in
  the in-app log so nothing is silently lost.
- **WhatsApp alerting via the Meta Cloud API** has one important rule: free-form messages are
  only delivered inside a 24-hour customer-service window. For company-initiated alerts (the
  usual case here) Meta requires pre-approved **template messages**, or a BSP/aggregator.
  Practically: use Twilio or the generic webhook (Africa's Talking, Vonage, a BSP) for outbound
  alerting, or register templates with Meta and wire them through your provider. The platform
  supports all three paths; pick per your WhatsApp compliance situation.
- UPS and Colissimo require approved developer/enterprise access (UPS: app in production mode;
  Colissimo: Enterprise contract). Until they're approved the carrier stays in manual mode.
- 17TRACK free tier is quota-limited; the 30-minute sync cycle and "stop polling finished
  parcels" rule keep you well inside it for typical volumes.

---

## 9. Extending it

Natural next steps if you want them (each is a small, self-contained change):

- Additional carriers (UPS, DHL eCommerce, Colissimo, La Poste) — copy an adapter file
- WhatsApp/SMS alerts instead of email (add a gateway in `services/alerts.py`)
- Automatic hourly sync for parcels in `out_for_delivery`
- Client-facing email digest per client, per week
- Barcode scanning of incoming shipments at the warehouse

---

ParcelDesk — built for your operation. Everything is plain Python + SQLite/PostgreSQL,
so any developer can maintain it, and it runs fine on a small VPS, a NAS, or a PC in
the office.
