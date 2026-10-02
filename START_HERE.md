# START HERE — your parcel tracking platform

**ParcelDesk** is running in this workspace right now with demo data, so you can click
through everything.

| Sign in as | Where | Credentials |
|---|---|---|
| Your team (control tower) | `/login` | `admin@example.com` / `admin123` |
| A customer (client portal) | `/portal` | `logistics@pharma-oi.mg` / `client123` |

Then the three steps to make it yours.

---

## Step 1 — Try it (10 minutes, no setup)

| Where | What to look at |
|---|---|
| **Dashboard** | KPIs: open parcels, in customs, exceptions, stuck beyond SLA, avg transit, on-time % |
| **Parcels** | 11 demo parcels across 8 carriers — filters, search, per-row "Sync now", Excel/CSV export |
| A parcel | Full timeline, cartons received, **Print label**, **Release**, share link, "Add update", "Email update" |
| **Receiving** | Scan screen — type or scan a barcode, it finds the parcel and checks in **one carton at a time** |
| **Stock** | 🆕 What is physically on your shelves: cartons, days on shelf, ageing warning, release / undo release, Excel export |
| **Clients** | Accounts, SMS/email flags, **portal access** (set/reset/revoke a customer's password) |
| **Reports** | Carrier performance, completion rates, door-to-door transit |
| **Diagnostics** | 🆕 The test app: 25+ self-checks with pass/warn/fail, optional live carrier probes |
| **Settings → Carriers** | All 8 carriers and exactly which credentials each one still needs |
| **Settings → Alerts** | Email rules + WhatsApp/SMS provider status, test send, channel-tagged alert log |
| **Settings → Automation** | Sync interval, out-for-delivery sweep, warehouse ageing limit, SLA thresholds |
| **Settings → Users** | Roles, phone numbers, per-user email/WhatsApp/SMS opt-in |

**Try the warehouse flow:** Receiving → paste `789123456789` (2-carton lab equipment, 1 carton
already on the shelf) → **Check in** → it tells you one carton is still missing. Open **Stock**,
release `5522334455` (3 of 3 cartons, collected by the client) and watch the shelf count drop.
To undo: **Undo release** puts it straight back.

**Try labels:** open any parcel → **Label** (or Stock → **Print labels**) → a 100×60 mm page opens
with a real Code 128 barcode, one label per carton, ready for a label printer. Barcodes are drawn
in-house — no barcode library, no internet, nothing to license.

**Try the client portal:** open `/portal`, sign in as the demo customer, and you see only that
customer's shipments, their carton progress and whether they are still in the warehouse. Give any
other client access from **Clients → Give portal access** (generates a password and copies it).

**Try the test app:** **Diagnostics** in the sidebar → *Re-run checks* → each check tells you what
it verified (database write/read, scheduler jobs, barcode engine, carrier credentials, email,
WhatsApp, warehouse ageing, SLA…). "Ping live carrier APIs" sends one real tracking request per
live carrier. The same suites run from a terminal:

```bash
python tests/test_all_features.py    # 62 checks — labels, portal, cartons, stock, sync sweeps
python tests/smoke_test.py           # 41 checks against the running server
python tests/test_messaging_webhook.py   # WhatsApp/SMS pipeline (starts a local webhook receiver)
node tests/ui_smoke.js                   # every screen, in a normal and a locked-down browser
node tests/ui_live.js                    # the same screens against the running app (needs Node.js)
```

---

## Step 2 — Run it on your own PC or server

Two one-command options:

```bash
# Linux / macOS — demo mode (simulated carriers, no credentials)
cd parceltrack && ./run-demo.sh

# …or live mode, with your real carrier keys
bash deploy/install.sh
```

Windows: double-click **`run-demo.bat`** (demo) or **`deploy\windows-start.bat`** (live).
Docker: `docker compose -f deploy/docker-compose.yml up -d --build`.

Run it as a service so it survives reboots — systemd unit and Windows service (NSSM) commands
are in `docs/SETUP.md` §1–2, HTTPS reverse proxy in §4, backups in §6.

Edit `.env` before going live:

```env
SECRET_KEY=<long random string>          # python -c "import secrets;print(secrets.token_urlsafe(48))"
FIRST_ADMIN_EMAIL=you@yourcompany.mg     # your real login
FIRST_ADMIN_PASSWORD=<strong password>   # change it after first login
COMPANY_NAME=Your Company Name
PUBLIC_BASE_URL=https://parcels.yourcompany.mg
DEMO_MODE=false                          # once carrier credentials are in
```

**Upgrading an existing install?** Just replace the `app/` folder and restart — new tables and
columns are added to your database automatically (verified on a live 11-parcel database:
`clients.password_hash`, `clients.last_login_at`, `parcels.cartons_expected`, `parcels.released_at`,
`released_to`, `released_by` and the `receipt_lines` table were added in place).

**Want an empty database?** Stop the app, delete `data/parceltrack.db*` and start it again — the
demo data only comes back if `DEMO_MODE=true`.

---

## Step 3 — Connect carriers and alerts

Step-by-step credential guides: **`docs/CARRIERS.md`** (all 8 integrations).

| Carrier | How to get access |
|---|---|
| **DHL Express** | Free self-service app at developer.dhl.com — product *"Shipment Tracking – Unified"* |
| **FedEx** | developer.fedex.com — the project must include **Track API** |
| **UPS** | developer.ups.com — client ID/secret; needs app approval for production |
| **Aramex** | Credentials issued by your Aramex account manager |
| **DHL eCommerce / Parcel** | Same DHL developer account, public tracking host (can reuse your DHL key) |
| **Colissimo / La Poste** | Enterprise contract: contract number + X-Okapi-Key |
| **17TRACK** | Free key at api.17track.net — covers **EMS, China Post and 3,000+ couriers** |
| **Manual / Other** | No API: keep the number, add updates by hand (phone/WhatsApp from the courier) |

**Alerts:** any SMTP account for email; WhatsApp/SMS via Meta Cloud API, Twilio or a generic
webhook (Africa's Talking, Vonage, n8n, your own bot). Full setup in `docs/SETUP.md` §5 and §5b.

> One compliance note worth knowing up front: WhatsApp's Meta Cloud API only allows free-form
> messages inside a 24-hour window — for company-initiated alerts you need pre-approved templates
> or a BSP. Twilio SMS or the webhook route avoids that paperwork entirely. Details in
> `README.md` §8.

**Verify each connection** by adding one real AWB, opening it and pressing **Sync now** — the
carrier's own error message is shown if something is wrong. Parcels that reach *out for delivery*
are then re-checked on their own faster schedule (Settings → Automation, default hourly) so the
last mile arrives in near real time.

---

## What is where

| File | Purpose |
|---|---|
| `README.md` | Full feature list, API reference, project structure, caveats |
| `docs/SETUP.md` | Install per OS, HTTPS, email + WhatsApp/SMS setup, backups, troubleshooting |
| `docs/CARRIERS.md` | Credential walkthroughs and verification for all 8 carriers |
| `.env.example` | Every configuration option, commented |
| `deploy/` | Dockerfile, docker-compose, systemd unit, Windows launcher, installer |
| `app/carriers/*.py` | One small file per carrier — the usual place for tweaks |
| `app/services/barcode.py` | Code 128 encoder + label SVG (no external barcode library) |
| `app/services/receiving.py` | Barcode lookup, carton receipts, stock, release |
| `app/services/messaging.py` | WhatsApp / SMS / webhook delivery |
| `app/api/{labels,portal,receiving}.py` | Label printing, client logins, warehouse endpoints |
| `tests/` | Feature suite, installation smoke test, WhatsApp/SMS pipeline test |

---

## Delivered so far

Everything from the first build, plus the extensions you asked for:

- 8 carriers (DHL, FedEx, Aramex, UPS, DHL eCommerce, Colissimo, 17TRACK, manual) with demo mode
- Email + WhatsApp/SMS alerts, digest, stuck-parcel watchdog, alert log
- Barcode receiving screen with keyboard-wedge scanner support
- Client logins with passwords — staff enable/reset/revoke, sessions die on password change
- Printable Code 128 labels (SVG + print sheet, one per carton, configurable label size)
- Warehouse stock view: cartons, days on shelf, ageing flags, release / undo release, Excel export
- Partial shipments: cartons expected vs received, per-carton receipts, release only when complete
- Faster polling for out-for-delivery parcels (separate interval, adjustable in Settings)
- Diagnostics / test app: in-app self-test report with optional live carrier probes, plus three
  automated suites that run from the terminal

Ideas for later, whenever you want them: address-book style clients with saved consignees,
per-client rate cards, delivery-route batching, and a mobile scan mode (phone camera as scanner).
