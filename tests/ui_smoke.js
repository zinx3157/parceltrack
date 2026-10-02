#!/usr/bin/env node
/* ParcelDesk UI smoke test — no browser, no dependencies, just node.
 *
 *     node tests/ui_smoke.js
 *
 * Executes the real app.js against a stub DOM and renders every screen twice:
 *   1. "normal"   — a regular browser.
 *   2. "sandbox"  — a sandbox="allow-scripts" iframe / locked-down browser, where reading
 *                   localStorage and calling history.pushState throw SecurityError and
 *                   window.open returns null. The app must still boot and route.
 * Catches runtime errors that a syntax check cannot: undefined fields, bad template
 * literals, missing DOM ids, blocked browser APIs.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const APP = path.join(__dirname, "..", "app", "static", "app.js");
const failures = [];
const log = (ok, name, detail = "") => {
  console.log(`${ok ? "OK  " : "FAIL"} ${name}${detail ? " — " + detail : ""}`);
  if (!ok) failures.push(name);
};

/* ------------------------------------------------------------------ fixtures */
const PARCEL = {
  id: 7, tracking_number: "789123456789", carrier: "fedex", status: "received",
  status_text: "Received at warehouse", description: "Lab equipment", client_reference: "POI-4488",
  client_name: "Pharma Océan Indien", client: { name: "Pharma Océan Indien", email: "logistics@pharma-oi.mg" },
  storage_location: "Cold room — Shelf 2", cartons_expected: 2, cartons_received: 1,
  cartons_outstanding: 1, complete: false, released_at: null, released_to: null, released_by: null,
  received_at: "2026-10-01T09:00:00Z", received_by: "Administrator", barcode: "BAR-7781",
  barcode_svg_url: "/api/parcels/7/barcode.svg", label_url: "/labels/7", share_token: "tok123",
  tracking_url: "https://www.fedex.com/fedextrack/?trknbr=789123456789",
  days_in_transit: 9, eta: "2026-10-05T00:00:00Z", sync_enabled: true, weight_kg: 5,
  cost_amount: 1000, cost_currency: "MGA", notes: "fragile", last_sync_error: null,
  created_at: "2026-09-21T09:00:00Z", updated_at: "2026-10-01T09:00:00Z",
  events: [{ occurred_at: "2026-10-01T09:00:00Z", status: "received", status_text: "Received", location: "TNR", source: "manual" }],
};
const CLIENT = { id: 3, name: "Pharma Océan Indien", contact_name: "Dr. Rasoa", email: "logistics@pharma-oi.mg",
  phone: "+261 33 45 678 90", reference_prefix: "POI", notes: "", notify_client: true, notify_sms: false,
  share_token: "tok123", portal_login: true, last_login_at: null, portal_url: "http://localhost:8000/portal/tok123",
  parcel_count: 3, created_at: "2026-09-01T00:00:00Z" };
const RESPONSES = [
  [/^\/api\/parcels\/7/, PARCEL],
  [/^\/api\/parcels\/7\/events/, []],
  [/^\/api\/parcels\?/, { items: [PARCEL], total: 1 }],
  [/^\/api\/parcels\/stats/, { total: 11, open: 8, delivered: 3, in_customs: 2, exceptions: 0, out_for_delivery: 1,
    stuck: 0, avg_transit_days: 6.4, on_time_pct: 82, window_days: 30, delivered_period: 3, added_period: 5,
    by_status: [{ status: "in_transit", count: 3 }], by_carrier: [{ carrier: "fedex", total: 4, delivered: 2, open: 2, avg_transit_days: 6 }] }],
  [/^\/api\/parcels/, { items: [PARCEL], total: 1 }],
  [/^\/api\/receiving\/stock/, { items: [{ ...PARCEL, days_on_shelf: 11, stale: true, complete: false, released_at: null }],
    summary: { in_warehouse: 1, stale: 1, cartons_on_shelf: 1, released_total: 0, locations: ["Cold room — Shelf 2"], stale_after_days: 7 } }],
  [/^\/api\/receiving\/(recent|pending)/, [PARCEL]],
  [/^\/api\/diagnostics/, { generated_at: "2026-10-02T08:00:00Z", run_probes: false, verdict: "working with warnings",
    summary: { pass: 11, warn: 5, fail: 0 }, app: { name: "ParcelDesk", version: "1.1.0", demo_mode: true, company: "My Company" },
    checks: [{ name: "Code 128 symbol table", status: "pass", detail: "107 symbols", group: "barcode" },
             { name: "Warehouse ageing", status: "warn", detail: "1 parcel over 7 days", group: "warehouse" }] }],
  [/^\/api\/portal\/me/, { client: { id: 3, name: "Pharma Océan Indien", email: "logistics@pharma-oi.mg" }, open_count: 1, total: 1, company_name: "My Company" }],
  [/^\/api\/portal\/parcels/, { parcels: [PARCEL], company_name: "My Company", open_count: 1, client: { name: "Pharma Océan Indien" } }],
  [/^\/api\/clients/, [CLIENT]],
  [/^\/api\/carriers/, { demo_mode: true, carriers: [{ name: "fedex", label: "FedEx", abbr: "FX", configured: true, demo: true, missing: [] },
    { name: "dhl", label: "DHL Express", abbr: "DHL", configured: true, demo: true, missing: [] }] }],
  [/^\/api\/settings/, { company_name: "My Company", warehouse_stale_days: 7, ofd_sync_enabled: true, ofd_sync_minutes: 60,
    alerts_enabled: true, alert_on_statuses: "delivered,exception", stuck_customs_days: 5, stuck_transit_days: 14,
    daily_digest_hour: 7, sync_interval_minutes: 30, public_base_url: "http://localhost:8000", smtp_configured: false,
    smtp_host: "", smtp_from: "x@y.z", demo_mode: true }],
  [/^\/api\/users/, []],
  [/^\/api\/sync\/runs/, []],
  [/^\/api\/notifications/, []],
  [/^\/api\/messaging/, { provider: "none", provider_label: "Not configured", configured: false, missing: [], alert_statuses: "delivered" }],
];

/* ------------------------------------------------------------------ stub DOM */
function makeEnv({ sandboxed }) {
  const made = [];
  const node = () => {
    const n = {
      innerHTML: "", value: "", checked: false, disabled: false, dataset: {}, style: {}, className: "",
      textContent: "", childNodes: [], tagName: "div",
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      addEventListener() {}, removeEventListener() {}, appendChild() {}, remove() {}, focus() {}, select() {},
      setAttribute(k, v) { this[k] = v; }, getAttribute(k) { return this[k] ?? ""; },
      querySelector: () => node(), querySelectorAll: () => [], insertAdjacentHTML() {}, after() {}, before() {},
    };
    made.push(n);
    return n;
  };
  const document = { querySelector: () => node(), querySelectorAll: () => [], createElement: () => node(),
                     addEventListener() {}, body: node(), documentElement: node() };
  const security = (what) => {
    const e = new Error(`Failed to read the '${what}' property from 'Window': Access is denied for this document.`);
    e.name = "SecurityError";
    return e;
  };
  const storage = {
    _m: new Map(),
    getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
    setItem(k, v) { this._m.set(k, String(v)); },
    removeItem(k) { this._m.delete(k); },
  };
  const opened = [];
  const sandbox = {
    console, setTimeout: (fn, ms) => ms > 10000 ? 0 : setTimeout(fn, ms), clearTimeout, Date, Math, JSON, Intl, Promise, parseInt, parseFloat, isNaN,
    URL: { createObjectURL: () => "blob:test-print", revokeObjectURL() {} }, URLSearchParams, String, Number, Object, Array, Error, RegExp, Boolean, Map, Set,
    document,
    navigator: sandboxed ? {} : { clipboard: { writeText: async () => {} } },
    fetch: async (url, opts = {}) => {
      if (url.startsWith("/api/never")) {          // used by the session-safety checks
        const status = (opts && opts.headers && opts.headers.Authorization) ? 401 : 401;
        const payload = { detail: opts && opts.headers && opts.headers.Authorization
          ? "Invalid session token" : "Not authenticated" };
        return { ok: false, status, headers: { get: () => "application/json" },
                 json: async () => payload, text: async () => JSON.stringify(payload) };
      }
      const hit = RESPONSES.find(([re]) => re.test(url));
      const body = hit ? hit[1] : {};
      return { ok: true, status: 200, headers: { get: () => "application/json" },
               blob: async () => ({}), json: async () => JSON.parse(JSON.stringify(body)), text: async () => JSON.stringify(body) };
    },
    location: sandboxed
      // a sandbox="allow-scripts" iframe: opaque origin ("null") and assign() refused,
      // but the document URL is still readable
      ? { href: "https://8000-preview.e2b.app/portal", pathname: "/portal", origin: "null",
          assign() { throw security("assign"); } }
      : { pathname: "/", origin: "http://localhost:8000", href: "http://localhost:8000/", assign() {} },
    history: sandboxed
      ? { pushState() { throw security("history.pushState"); }, replaceState() { throw security("history.replaceState"); } }
      : { pushState() {}, replaceState() {} },
  };
  sandbox.localStorage = sandboxed ? { get length() { throw security("localStorage"); } } : storage;
  Object.defineProperty(sandbox, "localStorage", { get: () => (sandboxed ? (() => { throw security("localStorage"); })() : storage) });
  sandbox.window = { addEventListener() {}, print() {}, open(url) { if (sandboxed) return null; opened.push(url); return { focus() {}, close() {}, location: "", opener: null }; },
                     localStorage: sandboxed ? undefined : storage, document };
  sandbox.globalThis = sandbox;
  return { sandbox, opened };
}

/* ------------------------------------------------------------------ run */
const src = fs.readFileSync(APP, "utf8");

function boot(env) {
  const ctx = vm.createContext(env.sandbox);
  const exported = src + `
;globalThis.__app = { renderDashboard, renderParcels, renderParcelDetail, renderReceiving, renderStock,
  renderDiagnostics, renderClients, renderSettings, renderReports, renderTrack, renderClientPortal,
  renderClientPortalLogin, renderLogin, router, navigate, cartonChip, releaseModal, clientPortalModal,
  openPage, portalLink, shareBase, api, S, store };
`;
  vm.runInContext(exported, ctx, { filename: "app.js" });
  return env.sandbox.__app;
}

async function exercise(app, label, opened) {
  const views = [
    ["dashboard", () => app.renderDashboard()],
    ["parcels list", () => app.renderParcels()],
    ["parcel detail (cartons + label)", () => app.renderParcelDetail(7)],
    ["receiving screen", () => app.renderReceiving()],
    ["stock screen", () => app.renderStock()],
    ["diagnostics screen", () => app.renderDiagnostics(false)],
    ["clients screen", () => app.renderClients()],
    ["settings screen", () => app.renderSettings()],
    ["reports screen", () => app.renderReports()],
    ["public tracking page", () => app.renderTrack("tok123")],
    ["carton chips (1 / 0-of-3 / 3-of-3)", () => {
      app.cartonChip({ cartons_expected: 1, cartons_received: 1 });
      app.cartonChip({ cartons_expected: 3, cartons_received: 0 });
      app.cartonChip({ cartons_expected: 3, cartons_received: 3 });
    }],
    ["release modal", () => app.releaseModal({ id: 7, tracking_number: "X", client_name: "C" })],
    ["portal access modal", () => app.clientPortalModal({ id: 3, name: "Client" })],
  ];
  for (const [name, fn] of views) {
    try { await fn(); log(true, `[${label}] ${name}`); }
    catch (err) { log(false, `[${label}] ${name}`, `${err.name}: ${err.message}`); }
  }
  // routing with a blocked/working history API
  try {
    app.S.token = "staff-token";
    app.navigate("/stock"); app.navigate("/parcels/7"); app.navigate("/diagnostics");
    log(true, `[${label}] navigation between routes`);
  } catch (err) { log(false, `[${label}] navigation between routes`, `${err.name}: ${err.message}`); }
  // the client portal, signed out and signed in
  try {
    app.S.token = ""; app.S.clientToken = "";
    await app.renderClientPortalLogin();
    app.S.clientToken = "client-token";
    await app.renderClientPortal();
    log(true, `[${label}] client portal (signed out + signed in)`);
  } catch (err) { log(false, `[${label}] client portal (signed out + signed in)`, `${err.name}: ${err.message}`); }
  // a token-less 401 must NOT sign a signed-in user out (regression: public pages
  // loading shared data used to clear a freshly established session)
  try {
    app.S.token = "live-session-token";
    app.S.path = "/";
    let threw = false;
    try { await app.api("/api/never", { token: "" }); } catch (e) { threw = true; }
    log(threw && app.S.token === "live-session-token",
        `[${label}] anonymous 401 leaves the staff session alone`,
        `token ${app.S.token ? "kept" : "CLEARED"}`);
    // …but a 401 on a request that did carry the session token must still sign out
    let signedOut = false;
    try { await app.api("/api/never"); } catch (e) { signedOut = true; }
    log(signedOut && app.S.token === "", `[${label}] rejected session token signs the user out`,
        `token ${app.S.token ? "kept" : "cleared"}`);
    app.S.token = "staff-token";
  } catch (err) { log(false, `[${label}] session safety`, `${err.name}: ${err.message}`); }

  // opening the label/print page must never throw, even with popups blocked
  try {
    if (app.openPage) await app.openPage("/labels/7");
    log(true, `[${label}] opening a label page`);
  } catch (err) { log(false, `[${label}] opening a label page`, `${err.name}: ${err.message}`); }
  // share links must not point at localhost when reached through another hostname
  try {
    if (app.portalLink) {
      const link = app.portalLink("tok123");
      const usable = !/^undefined|^null/.test(link) && link.includes("/portal/tok123");
      log(usable, `[${label}] portal share link`, link);
      if (label === "sandbox") {
        log(link.startsWith("https://8000-preview.e2b.app/"),
            `[${label}] share link uses the host it is served on (not localhost)`, link);
      }
    }
  } catch (err) { log(false, `[${label}] portal share link`, `${err.name}: ${err.message}`); }
  if (opened && opened.length) log(true, `[${label}] popup fallback recorded`, opened.join(", "));
}

(async () => {
  const normal = makeEnv({ sandboxed: false });
  log(true, "app.js parses");
  const appNormal = boot(normal);
  log(!!appNormal.renderStock && !!appNormal.renderDiagnostics, "all views exported");
  await exercise(appNormal, "normal", normal.opened);

  const blocked = makeEnv({ sandboxed: true });
  let appBlocked = null;
  try { appBlocked = boot(blocked); log(true, "[sandbox] app boots with storage + history blocked"); }
  catch (err) { log(false, "[sandbox] app boots with storage + history blocked", `${err.name}: ${err.message}`); }
  if (appBlocked) await exercise(appBlocked, "sandbox", null);

  console.log();
  if (failures.length) {
    console.log(`${failures.length} UI check(s) failed: ${failures.join(" | ")}`);
    process.exit(1);
  }
  console.log("All UI checks passed — every screen renders in a normal browser and in a sandboxed preview.");
})();
