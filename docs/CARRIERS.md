# Connecting DHL, FedEx and Aramex

ParcelDesk polls each carrier through its official API. Nothing here is required to start:
without credentials the platform still works, with that carrier in manual mode.

Check live status any time in **Settings → Carriers** — it lists, per carrier, exactly which
variables are still missing.

---

## 1. DHL Express — *Shipment Tracking – Unified* API

**Where:** <https://developer.dhl.com> → register (free) → *My Apps* → **Create App**
→ subscribe to the API product **"Shipment Tracking - Unified"**.

**Copy into `.env`:**

```env
DHL_API_KEY=your_api_key          # the app's "API Key" = HTTP Basic username
DHL_API_SECRET=your_api_secret    # the app's "API Secret" = HTTP Basic password
DHL_USE_TEST=false                # true switches to .../mydhlapi/test
```

**How ParcelDesk calls it:** `GET {base}/shipments/{trackingNumber}/tracking` with HTTP Basic
auth (key/secret), `limit=100`. The response's `shipments[0].events[]` become timeline entries
(`timestamp`, `status` / `statusCode`, `location.address.addressLocality`, `description`),
and `estimatedDeliveryDate` becomes the ETA.

**Good to know**
- Express AWB numbers are normally 10 digits (e.g. `1234567890`); ParcelDesk auto-detects them.
- DHL eCommerce / Parcel numbers (`GM…`, `JJD…`, `JVGL…`) are recognised for routing too, but
  they need a different API product (DHL eCommerce Solutions) — ask if you ship those.
- The free tier is rate-limited per app; a 30-minute sync interval is comfortable for a few
  hundred parcels. HTTP 429 responses are reported and retried on the next cycle.

---

## 2. FedEx — Track API (OAuth)

**Where:** <https://developer.fedex.com> → *My Projects* → **Create Project** →
add the **Track API** to it. Then copy the project's **API Key** and **Secret Key**
(from the API Keys section) — plus your FedEx account number.

**Copy into `.env`:**

```env
FEDEX_CLIENT_ID=your_api_key
FEDEX_CLIENT_SECRET=your_secret_key
FEDEX_ACCOUNT_NUMBER=your_account_number
FEDEX_USE_SANDBOX=false          # true = apis-sandbox.fedex.com for testing
```

**How ParcelDesk calls it**
1. `POST {base}/oauth/token` with `grant_type=client_credentials` → access token (cached
   in memory for its lifetime, one token per server, not per parcel).
2. `POST {base}/track/v1/trackingnumbers` with `includeDetailedScans: true` →
   `output.completeTrackResults[0].trackResults[0].scanEvents[]` become the timeline, and
   `dateAndTimes[ESTIMATED_DELIVERY]` becomes the ETA.

FedEx status codes are mapped onto the internal scale (`DL`→delivered, `OD`→out for delivery,
`IT`/`AF`/`AR`→in transit, `PU`→picked up, `OC`→label created, `DE`/`EX`/`HL`→exception, …).

**Good to know**
- The project must actually contain **Track API**; otherwise every call returns an
  authorization error — this is the most common setup mistake.
- Sandbox works without a production agreement, but only returns test tracking numbers.
- A single tracking request covers one AWB in ParcelDesk; the API also supports fetching
  numbers by reference if you ever want to add that.

---

## 3. Aramex — Shipping API v2 (TrackShipments)

Aramex API access is **not self-service** like DHL/FedEx: you request it from your Aramex
account manager, who issues credentials tied to your account.

Ask your Aramex contact for *"Shipping API (v2) access + tracking API credentials for our
account"*. You need:

| Value | Notes |
|---|---|
| Username / Password | The API login (often different from the web portal login) |
| Account number | Your 6-digit Aramex account |
| Account PIN | The 4-digit PIN on the account |
| Account entity | Aramex station/branch code (e.g. `TNR`) |
| Account country code | `MG` for Madagascar |

**Copy into `.env`:**

```env
ARAMEX_USERNAME=
ARAMEX_PASSWORD=
ARAMEX_ACCOUNT_NUMBER=
ARAMEX_ACCOUNT_PIN=
ARAMEX_ACCOUNT_ENTITY=
ARAMEX_ACCOUNT_COUNTRY_CODE=MG
```

**How ParcelDesk calls it:**
`POST {base}/Tracking/Service_1_0.svc/json/TrackShipments` with the standard
`ClientInfo` block and the AWB list. The parser walks the JSON defensively and picks up any
record containing a date plus a status/description, so it tolerates the different response
shapes Aramex has shipped over the years (`UpdateDateTime`/`EventDate`, `UpdateLocation`,
`Comments`, …).

**Good to know**
- Some accounts can only track AWBs booked on their own account — third-party Aramex numbers
  will return "no data". Use manual updates for those (Parcel → *Add update*).
- If your credentials are the newer OAuth style, tell your developer: it's a 20-line change
  in `app/carriers/aramex.py` (swap the ClientInfo block for a bearer-token call).

---

## 4. UPS — Track API

**Where:** <https://developer.ups.com> → *Apps* → create an app → add the **Tracking** API.
Copy the **Client ID** and **Client Secret**. For production tracking you also apply for the app
to be promoted out of the test environment (UPS reviews it, usually within a few days).

```env
UPS_CLIENT_ID=your_client_id
UPS_CLIENT_SECRET=your_client_secret
UPS_ACCOUNT_NUMBER=your_account_number
UPS_USE_TEST=false          # true uses the CIE test host (test tracking numbers only)
```

**How ParcelDesk calls it**
1. `POST {base}/security/v1/oauth/token` (HTTP Basic, `grant_type=client_credentials`) — the
   token is cached in memory and shared across all parcels.
2. `GET {base}/api/track/v1/details/{trackingNumber}` with a `transId` header.

`activity[]` entries become the timeline (`date`+`time`, `status.description`, `location.address`),
and UPS status types are mapped internally (`D`→delivered, `I`→in transit, `M`→label created,
`X`→exception, `O`/`P`/`RS`…).

UPS numbers are recognised automatically — `1Z` + 16 characters (e.g. `1Z999AA10123456784`) and
`T` + 10 digits (UPS Mail Innovations).

---

## 5. DHL eCommerce / DHL Parcel

**Where:** same <https://developer.dhl.com> account — subscribe the app to
**"Shipment Tracking - Unified"**. Express and eCommerce are separate products, but the
eCommerce adapter accepts your `DHL_API_KEY` as a fallback, so one key can serve both.

```env
DHL_ECOM_API_KEY=your_key     # optional: leave empty to reuse DHL_API_KEY
```

**How ParcelDesk calls it:** `GET https://api-eu.dhl.com/track/shipments?trackingNumber=…` with the
`DHL-API-Key` header. Shipment numbers like `RX123456789DE`, `LX…DE`, `GM…` are auto-detected as
DHL eCommerce rather than Express.

---

## 6. Colissimo / La Poste (France)

Colissimo's tracking API is part of the **Colissimo Enterprise** offer: your contract provides a
**contract number**, a **password** and an **API key** (`X-Okapi-Key`).

```env
COLISSIMO_API_KEY=your_okapi_key
COLISSIMO_CONTRACT_NUMBER=123456
COLISSIMO_PASSWORD=your_contract_password
```

**How ParcelDesk calls it:** `POST {base}/sls-ws/SlsServiceWSRest/2.0/track` with
`{"contractNumber", "password", "parcelNumber"}`. The response parser walks the JSON for any
dated event and normalises **French wording** (`En cours de livraison` → out for delivery,
`Colis livré` → delivered, `en attente de dédouanement` → customs, `retard` → exception, …),
so the timeline reads correctly for your team and clients. `…FR` S10 numbers and `6A`/`8R`
barcodes are auto-detected.

---

## 7. 17TRACK — EMS, China Post, national posts, everything else

The catch-all for carriers with no usable direct API. One key covers **EMS, China Post,
Singapore Post, most national postal operators and 3,000+ couriers**, and it resolves the
operator for you.

**Where:** <https://api.17track.net> → register → free tier available for small volumes.

```env
TRACK17_API_KEY=your_17token
```

**How ParcelDesk calls it:** `POST /register` (idempotent — teaches 17TRACK the number) then
`POST /gettrackinfo`, with the key in the `17token` header. Its `stage` values
(`InfoReceived`, `InTransit`, `Pickup`, `Delivered`, `Undelivered`, `Exception`, `Expired`) map
straight onto the internal statuses, so a China Post parcel shows the same clean timeline as a
DHL one.

Use it for: EMS shipments, Chinese/Aliexpress parcels, postal operators, and any courier not
listed above. Quota is per-query, so the standard 30-minute cycle and
"stop polling finished parcels" rule keep you comfortably inside the free tier.

---

## 8. Carriers without an API

Use **Manual / Other**: keep the tracking number, add updates yourself via *Add update*
(status, date, location, note). They merge into the same timeline as API events.

---

## 9. Verifying a connection (5 minutes)

1. Add one real shipment per carrier: **Parcels → Add parcel** (paste the AWB; the carrier
   is detected automatically — UPS `1Z…`, Colissimo `…FR`, eCommerce `RX…DE`, EMS `EE…CN`).
2. Open the parcel → **Sync now**.
3. Success = timeline entries appear within seconds. The parcel row also clears its sync note.
4. Failure messages are explicit, e.g.
   - `DHL: invalid API key/secret (401/403)` → wrong key/secret or app not subscribed
   - `FedEx auth failed (400)` → wrong client id/secret, or Track API missing from the project
   - `Aramex: Invalid account information` → PIN/entity/country mismatch
5. Re-run and confirm nothing duplicates: event deduplication is by parcel + timestamp +
   status text + location.

---

## 9b. How often each parcel is polled

Two schedules run side by side:

| Schedule | Default | What it covers | Where to change it |
|---|---|---|---|
| Full sync | every 30 min | every parcel that has a carrier API, auto-sync on, and is not yet delivered/cancelled/returned | Settings → Automation (`SYNC_INTERVAL_MINUTES`) |
| **Out-for-delivery sweep** | every 60 min | only parcels currently *out for delivery* — the last mile, where statuses move fastest | Settings → Automation (`OFD_SYNC_ENABLED`, `OFD_SYNC_MINUTES`, minimum 10 min) |

Finished parcels stop being polled entirely, which keeps you well inside carrier quotas. Manual
parcels are never polled. You can always force one parcel with **Sync now** on its page, or kick
off a full run with **Run full carrier sync now** in Settings.

---

## 10. Rate limits & etiquette

| Carrier | Typical limit | ParcelDesk behaviour |
|---|---|---|
| DHL | per-app quota (varies) | 30-min default cycle; 429 → skip and retry next run |
| UPS | per-app quota, hourly buckets | token cached; 429 → skip and retry next cycle |
| Colissimo | per-contract | sequential requests only |
| 17TRACK | per-query quota (free tier) | registered once, queried on the normal cycle |
| FedEx | per-project, per-endpoint | one cached OAuth token; 429 → skip and retry |
| Aramex | per-account | sequential requests, no aggressive polling |

Delivered, cancelled and returned parcels stop being polled automatically (toggle
*"Keep checking this parcel"* off in the parcel's edit dialog for anything earlier). This
keeps your quota for live shipments and avoids needless calls.
