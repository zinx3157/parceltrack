# Setup guide — ParcelDesk

Choose your platform below. Total time: about 10 minutes.

---

## 1. Windows (office PC)

1. Install **Python 3.11+** from python.org — during install, tick
   *"Add python.exe to PATH"*.
2. Copy the `parceltrack` folder somewhere permanent, e.g. `C:\parceltrack`.
3. Open **Command Prompt** in that folder and run:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env            (fill in your credentials)
python run.py           (add --demo to try it without credentials)
```

4. Browse to <http://localhost:8000>.
5. To let colleagues on the office network use it, run `python run.py --host 0.0.0.0`
   and open Windows Firewall for port 8000, then share `http://YOUR-PC-IP:8000`.

**Run it as a Windows service** (auto-start on boot) using NSSM:

```bat
nssm install ParcelDesk "C:\parceltrack\.venv\Scripts\python.exe" "C:\parceltrack\run.py"
nssm set ParcelDesk AppDirectory C:\parceltrack
nssm start ParcelDesk
```

A convenience launcher is included: `deploy\windows-start.bat`.

---

## 2. Linux / macOS

```bash
cd parceltrack
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env                     # credentials + SECRET_KEY + PUBLIC_BASE_URL
python run.py --host 0.0.0.0 --port 8000
```

**Run as a systemd service** (Debian/Ubuntu, recommended for a VPS):

```bash
sudo useradd -r -s /bin/false parceldesk
sudo mkdir -p /opt/parceltrack && sudo chown parceldesk: /opt/parceltrack
# copy the app into /opt/parceltrack, create the venv and .env there
sudo cp deploy/parceldesk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now parceldesk
systemctl status parceldesk
```

---

## 3. Docker (any machine with Docker)

```bash
cd parceltrack
cp .env.example .env
docker compose -f deploy/docker-compose.yml up -d --build
```

The database and configuration persist in `./data` and `.env`.
Logs: `docker compose -f deploy/docker-compose.yml logs -f parceldesk`. Update: same command with `up -d --build`.

---

## 4. Access from outside your network (HTTPS)

ParcelDesk itself serves plain HTTP; put a reverse proxy in front of it.

**Caddy** (automatic HTTPS, simplest):

```
parcels.yourcompany.mg {
    reverse_proxy 127.0.0.1:8000
}
```

**nginx**:

```nginx
server {
    listen 443 ssl;
    server_name parcels.yourcompany.mg;
    ssl_certificate     /etc/letsencrypt/live/parcels.yourcompany.mg/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/parcels.yourcompany.mg/privkey.pem;
    client_max_body_size 20M;          # bulk Excel imports
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then set `PUBLIC_BASE_URL=https://parcels.yourcompany.mg` in `.env` so client links and
emails use the external address.

**Quick remote access without a domain:** a Cloudflare Tunnel (`cloudflared tunnel --url
http://localhost:8000`) or Tailscale — both give you a private HTTPS URL in minutes.

---

## 5. Email alerts (SMTP)

| Provider | Settings |
|---|---|
| Gmail / Google Workspace | host `smtp.gmail.com`, port 587, TLS on, password = **App Password** (2-Step Verification must be on) |
| Microsoft 365 | host `smtp.office365.com`, port 587, TLS on, password = account or app password |
| OVH / Infomaniak / most hosts | host `smtp.yourdomain.mg`, port 587 or 465 (SSL), your mailbox credentials |
| Local relay | host `localhost`, port 25, no credentials (set `SMTP_USER=` empty) |

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=app_password_here
SMTP_FROM=parcels@yourcompany.mg
SMTP_USE_TLS=true
```

Test it in **Settings → Alerts & email → Send test email**. If it fails, the exact SMTP
error is shown; a copy of every alert stays in the in-app log regardless.

---

## 5b. WhatsApp / SMS alerts

Set one provider in `.env` and restart. Check status any time in
**Settings → Alerts → WhatsApp / SMS alerts** (it shows the provider and what is missing),
then use **Send test text**.

### Option A — Twilio (recommended for pure outbound alerts)

Works for SMS immediately and for WhatsApp if your Twilio number is WhatsApp-enabled.

```env
MESSAGING_PROVIDER=twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_FROM=+12025550123
TWILIO_USE_WHATSAPP=false        # true -> send WhatsApp instead of SMS
MESSAGING_RECIPIENTS=+261340000000
```

Numbers must be in E.164 format (`+261…`). Twilio trial accounts can only message verified
numbers until you upgrade — that tripped many a first test.

### Option B — Meta WhatsApp Cloud API

```env
MESSAGING_PROVIDER=whatsapp
WHATSAPP_TOKEN=permanent_token_from_meta
WHATSAPP_PHONE_ID=1234567890
WHATSAPP_API_VERSION=v21.0
MESSAGING_RECIPIENTS=+261340000000
```

**Important compliance detail:** WhatsApp only allows *free-form* messages inside a 24-hour
service window opened by the recipient. Company-initiated notifications (which is what parcel
alerts are) require **pre-approved template messages**. So for alerting, either:
- register a utility template (e.g. *"Your parcel {{1}} is now {{2}}"*) with Meta and have your
  provider send it, or
- route through a BSP/aggregator that handles templates for you (see Option C), or
- use SMS (Option A) for the alerting step.

ParcelDesk sends plain text through the Cloud API — perfect for two-way customer care within the
window, and for production alerting pair it with a template-aware provider.

### Option C — Generic HTTP gateway (Africa's Talking, Vonage, n8n, your own bot)

```env
MESSAGING_PROVIDER=webhook
WEBHOOK_URL=https://your-gateway.example.com/send
WEBHOOK_TOKEN=optional_bearer_token
# optional custom JSON body ({to} and {message} are substituted):
# WEBHOOK_PAYLOAD_TEMPLATE={"phone":"{to}","text":"{message}"}
```

Each alert POSTs `{"to": "+261…", "message": "…", "sender": "Your Company"}`. Return any 2xx
and the alert is marked sent; anything else is recorded with the HTTP status in the alert log.
This is the most flexible route for Madagascar — it plugs into local SMS aggregators and lets
you change provider without touching ParcelDesk.

**Who gets texts:** team members with a phone number whose "SMS/WA" box is ticked
(Settings → Users), plus clients flagged the same way (Clients → edit), falling back to
`MESSAGING_RECIPIENTS`. Which statuses trigger a text is set by `MESSAGING_ALERT_STATUSES`
(or reuses `ALERT_ON_STATUSES` when empty).

---

## 5c. Warehouse receiving (barcode scanner)

No configuration needed. Open **Receiving**:

1. Put the cursor in the scan field (it is focused automatically).
2. Scan the label — any USB/Bluetooth barcode reader in "keyboard" mode works, and many phone
   apps can act as one over Bluetooth.
3. The parcel is found, checked in, stamped with your user and the storage location, and the
   field clears itself for the next carton.

Tips
- Set the storage location **once** before scanning a batch — it is reused for every parcel until
  you change it.
- If a label's barcode differs from the tracking number, put that code in the parcel's
  **Alternate barcode** field and scans will resolve to it.
- Partial scans still work (the lookup falls back to a "contains" match), so a smudged label
  usually still finds the parcel.
- Nothing found? The screen offers **Add it as a new parcel** with the code pre-filled.
- Check-ins are reversible: open the parcel → **Receive at warehouse** again to update the
  location, or use `/api/receiving/{id}/undo` to clear it.

---

## 5d. Partial shipments (one AWB, several cartons)

Set **Cartons expected** when you create or edit a parcel (default 1). Each scan/check-in then
records **one carton**:

- Every carton gets its own row: carton number, time, who received it, storage location, note.
- The parcel shows `2 of 3 cartons`; the status only moves to *Received at warehouse* when the
  last carton arrives (earlier cartons leave the status untouched).
- Scanning more cartons than expected is allowed but flagged, so a miscount is visible instead of
  silently breaking the receipt.
- **Release is blocked until every expected carton is in.** That is deliberate: it stops a
  half-shipment being handed over by mistake.

## 5e. Labels and label printing

Nothing to install — the barcode (Code 128) and the whole label are generated by the app.

- **Single parcel:** open the parcel → **Label**, or `/labels/{id}`.
- **A batch:** **Stock** → *Print labels* (all un-released parcels), or `/labels/print?ids=1,2,3`.
- **One label per carton:** a 3-carton shipment prints three labels, marked *Carton 1 of 3*,
  *2 of 3*, *3 of 3* — stick one on each box.
- The page opens the print dialog automatically. In the print dialog: **scale 100 %**, margins
  *none*, and turn off *fit to page*. The page size is set to your label size, so a thermal
  label printer prints one label per page.

Tuning (`.env`, restart afterwards):

| Setting | Meaning |
|---|---|
| `LABEL_WIDTH_MM` / `LABEL_HEIGHT_MM` | Label size, default 100 × 60 mm |
| `LABEL_MODULE_MM` | Width of one barcode bar module. Default `0.33`; raise it (0.4–0.5) for a bigger, more forgiving barcode on cheap printers — the app shrinks nothing, it just draws wider |

If a scanned barcode will not read: increase `LABEL_MODULE_MM`, print at 100 % scale, and avoid
printing on a laser printer's lowest resolution. The barcode is verified by the built-in encoder
self-test (**Diagnostics → Barcode engine**).

## 5f. Warehouse stock view and releases

**Stock** lists everything that has been checked in and not yet released:

- cartons on the shelf vs expected, days on the shelf, storage location, who received it;
- an ageing flag after **Settings → Automation → warehouse ageing** days (default 7);
- **Release** (records who collected it + an optional note) and **Undo release** if the hand-over
  was recorded by mistake;
- filters by search text and storage location, plus *Include released* and an Excel export.

Released shipments stay in the parcel history forever — the stock list is just the current
physical picture. Use `WAREHOUSE_STALE_DAYS` in `.env` or the Automation tab to change the
ageing threshold; ageing parcels are also reported in the alert log.

## 5g. Client portal logins

Clients sign in at `/portal` with their email address and a password you set — read-only, and
scoped to their own shipments only.

1. **Clients** → find the client → **Give portal access** (or *Reset password*).
2. The app generates a password and copies it to your clipboard — send it to the client however
   you like. You can type your own instead (minimum 6 characters).
3. The client can change it themselves once signed in (**Change password**).

Notes

- The client's email address *is* the login name, so it must be filled in first (the app tells you
  if it is missing).
- Changing or revoking the password immediately invalidates sessions that are already signed in.
- **Revoke** removes the login without touching the client's data or the old read-only share links.
- Clients only ever see: tracking number, carrier, description, status, carton count, warehouse
  shelf/release state, ETA and the timeline. Costs, notes and internal fields are never exposed.

## 5h. The test app (diagnostics)

**Diagnostics** in the sidebar runs the installation's self-check and prints pass / warn / fail
with a plain-language reason for each line: database read/write, pending schema changes, disk
space, scheduled jobs, the barcode engine, carrier credentials, SMTP, WhatsApp/SMS, the alert log,
warehouse ageing, SLA rules and cost efficiency. Tick **Ping live carrier APIs** to also send one
real tracking request per configured carrier.

The identical suites run from a terminal (all safe on a live install):

```bash
python tests/test_all_features.py        # 62 checks, own throwaway database
python tests/smoke_test.py               # 41 checks against a running server
python tests/test_messaging_webhook.py   # WhatsApp/SMS pipeline with a local stand-in gateway
```

## 5i. Faster polling for the last mile

Parcels that are **out for delivery** are polled on their own schedule, separate from the normal
sync, because that is when status changes fastest. Default: every 60 minutes, on. Change it in
**Settings → Automation** (`OFD_SYNC_ENABLED`, `OFD_SYNC_MINUTES` in `.env`; the minimum is 10
minutes). Switching it off simply returns those parcels to the normal sync interval.

---

## 6. Backups

SQLite (default): stop-free backup with the built-in tool.

```bash
# daily at 02:00, keep 30 days
0 2 * * * cd /opt/parceltrack && sqlite3 data/parceltrack.db ".backup 'backups/pd-$(date +\%F).db'" && find backups -name 'pd-*.db' -mtime +30 -delete
```

PostgreSQL: `pg_dump parceltrack > parceltrack-$(date +%F).sql` on the same schedule.

To restore: stop the service, replace `data/parceltrack.db`, start again.

---

## 7. Maintenance

| Task | Where |
|---|---|
| Change sync interval / alert thresholds | Settings → Automation (or `.env`) |
| Add a teammate | Settings → Users (admin) |
| Rotate a carrier key | Edit `.env`, restart the service |
| See sync errors | Settings → Automation → Sync history |
| Check which carriers are connected | Settings → Carriers |
| Update the app | Replace the `app/` folder with the new version, restart (database is untouched) |

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `Address already in use` | Another instance is running — use `--port 8001` or stop the old process |
| Login fails | Reset with `python run.py --seed-demo` won't help; instead delete `data/parceltrack.db` for a fresh install, or ask an admin to reset your password |
| Carrier shows "not configured" | Credentials missing in `.env` (Settings → Carriers lists exactly which variables) |
| FedEx "not authorized" | Your developer project lacks the Track API — enable it in the FedEx portal |
| Aramex errors | Confirm account number / PIN / entity; some accounts only see their own AWB range |
| A parcel never updates | Check the parcel isn't `delivered` (polling stops), that auto-sync is on, and read the sync note on the parcel row |
| Emails not arriving | Send a test email from Settings; check spam; verify App Password for Gmail |
| No WhatsApp/SMS arriving | Settings → Alerts shows the provider and missing variables; check the alert log for the exact API error; Twilio trials only message verified numbers |
| WhatsApp "re-engagement" error | Free-form messages outside the 24-hour window are rejected by Meta — use an approved template or the SMS/webhook route (see §5b) |
| Barcode scanner types nothing | Click the scan field first (readers type like a keyboard); check the reader is in HID/keyboard mode, not "inventory mode" |
| Printed barcode will not scan | Print at 100 % scale, raise `LABEL_MODULE_MM` (0.4–0.5), and check the printer is not scaling to fit; laser printers need ≥600 dpi |
| Label page prints blank | In the print dialog choose the label printer, scale 100 %, margins none — the sheet is sized to the label, so "fit to page" shrinks it off the edge |
| Client cannot sign in | The client needs an email address **and** a password set from the Clients screen; if you just reset the password, sessions signed in with the old one are invalidated on purpose |
| Release button is missing/disabled | The parcel is not fully received yet — every expected carton must be checked in first (Stock shows "awaiting cartons") |
| Stock list is empty although parcels were received | Parcels appear in Stock once checked in through Receiving; use *Include released* to see shipments already handed over |
| Diagnostics says "pending schema changes" | Restart the app once — new tables/columns are added on startup |
| Parcel not found when scanning | Verify the label code matches the tracking number or set it as the **Alternate barcode**; trailing newline characters from some readers are handled automatically |
