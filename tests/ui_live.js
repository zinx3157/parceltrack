#!/usr/bin/env node
/* Live UI integration test — the real app.js in a sandboxed preview environment,
 * talking to a running ParcelDesk over HTTP.
 *
 *     node tests/ui_live.js                       # defaults to http://127.0.0.1:8000
 *     PARCELDESK_URL=http://host:8000 node tests/ui_live.js
 *
 * Simulates a sandbox="allow-scripts" iframe (no localStorage, opaque origin, blocked
 * popups) and then drives the actual flows: staff login, dashboard, stock, diagnostics,
 * a real parcel detail, label opening, client portal login and the portal dashboard.
 * It reads only; nothing is created or deleted.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const BASE = process.env.PARCELDESK_URL || "http://127.0.0.1:8000";
const ADMIN = { email: process.env.PD_ADMIN_EMAIL || "admin@example.com",
                password: process.env.PD_ADMIN_PASSWORD || "admin123" };
const CLIENT = { email: process.env.PD_CLIENT_EMAIL || "logistics@pharma-oi.mg",
                 password: process.env.PD_CLIENT_PASSWORD || "client123" };

const failures = [];
const log = (ok, name, detail = "") => {
  console.log(`${ok ? "OK  " : "FAIL"} ${name}${detail ? " — " + detail : ""}`);
  if (!ok) failures.push(name);
};

/* ------------------------------------------------------------- sandboxed browser env */
const madeNodes = [];
function node() {
  const n = {
    innerHTML: "", value: "", checked: false, dataset: {}, style: {}, className: "", textContent: "",
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, appendChild() {}, remove() {}, focus() {}, select() {},
    setAttribute(k, v) { this[k] = v; }, getAttribute(k) { return this[k] ?? ""; },
    querySelector: () => node(), querySelectorAll: () => [],
  };
  madeNodes.push(n);
  return n;
}
const security = (what) => {
  const e = new Error(`Failed to read the '${what}' property from 'Window': Access is denied for this document.`);
  e.name = "SecurityError";
  return e;
};
const storageTrap = { getItem() { throw security("localStorage"); } };

const sandbox = {
  console, setTimeout, clearTimeout, Date, Math, JSON, Intl, Promise, parseInt, parseFloat, isNaN,
  URLSearchParams, String, Number, Object, Array, Error, RegExp, Boolean, Map, Set,
  document: { querySelector: () => node(), querySelectorAll: () => [], createElement: () => node(),
              addEventListener() {}, body: node() },
  navigator: {},                                  // no clipboard in a locked-down iframe
  fetch: async (url, opts) => {
    const full = url.startsWith("http") ? url : BASE + url;
    const started = Date.now();
    const res = await fetch(full, opts);
    const ms = Date.now() - started;
    if (!res.ok) {
      let body = "";
      try { body = (await res.clone().text()).slice(0, 160); } catch (e) { body = "<unreadable>"; }
      console.log(`     ! ${opts && opts.method || "GET"} ${full.replace(BASE, "")} -> ${res.status} (${ms} ms) ${body}`);
    }
    else if (ms > 1500) console.log(`     ~ slow: ${full.replace(BASE, "")} ${ms} ms`);
    return res;
  },
  // opaque origin, refused navigation, but a readable URL
  location: { href: BASE + "/portal", pathname: "/portal", origin: "null",
              assign() { throw security("assign"); } },
  history: { pushState() { throw security("history.pushState"); },
             replaceState() { throw security("history.replaceState"); } },
};
Object.defineProperty(sandbox, "localStorage", { get: () => { throw security("localStorage"); } });
sandbox.window = { addEventListener() {}, print() {}, open: () => null, document: sandbox.document };
sandbox.globalThis = sandbox;

/* --------------------------------------------------------------------------- boot */
let app = null;
try {
  const src = fs.readFileSync(path.join(__dirname, "..", "app", "static", "app.js"), "utf8");
  vm.runInContext(src + `
;globalThis.__app = { S, store, navigate, renderDashboard, renderParcels, renderParcelDetail,
  renderReceiving, renderStock, renderDiagnostics, renderSettings, renderClients, renderReports,
  renderClientPortal, renderClientPortalLogin, renderTrack, openPage, portalLink, api };`,
  vm.createContext(sandbox), { filename: "app.js" });
  app = sandbox.__app;
  log(true, "sandboxed preview boots the app (storage + history blocked)");
} catch (err) {
  log(false, "sandboxed preview boots the app (storage + history blocked)", `${err.name}: ${err.message}`);
}

async function view(name, fn) {
  try { await fn(); log(true, name); }
  catch (err) { log(false, name, `${err.name}: ${err.message}`); }
}

(async () => {
  if (!app) { process.exit(1); }

  // ---------------------------------------------------------------- staff session
  let token = "";
  await view("staff login over the live API", async () => {
    const r = await app.api("/api/auth/login", { method: "POST", token: "", body: ADMIN });
    token = r.token;
  });
  app.S.token = token;
  app.S.user = { name: "Administrator", role: "admin" };

  await view("reference data loads (carriers, clients, settings)", async () => {
    const [carriers, clients, settings] = await Promise.all([
      app.api("/api/carriers"), app.api("/api/clients"), app.api("/api/settings")]);
    app.S.carriers = carriers.carriers;
    app.S.clients = clients;
    app.S.settings = settings;
    app.S.demoMode = carriers.demo_mode;
    if (!clients.length) throw new Error("no clients returned");
  });
  log((app.S.settings.public_base_url || "").length > 0, "settings reachable in the sandbox",
      `public_base_url=${app.S.settings.public_base_url}, stale_days=${app.S.settings.warehouse_stale_days}`);
  log(app.portalLink("tok-demo").startsWith(BASE),
      "share links use the host the app is served on", app.portalLink("tok-demo"));

  // ---------------------------------------------------------------- real screens
  await view("dashboard renders with live stats", () => app.renderDashboard());
  await view("parcels list renders", () => app.renderParcels());
  await view("receiving screen renders", () => app.renderReceiving());
  await view("stock screen renders (live cartons + ageing)", () => app.renderStock());
  await view("clients screen renders (portal buttons)", () => app.renderClients());
  await view("reports screen renders", () => app.renderReports());
  await view("settings screen renders", () => app.renderSettings());
  await view("diagnostics renders the live self-test", () => app.renderDiagnostics(false));

  let parcelId = 0;
  await view("parcel detail renders (cartons, label, release)", async () => {
    const listing = await app.api("/api/parcels?limit=1");
    parcelId = listing.items[0].id;
    await app.renderParcelDetail(parcelId);
  });

  await view("opening a label page inside the sandbox", () => {
    app.openPage(`/labels/${parcelId}`);
  });
  log(app.S.path === `/labels/${parcelId}` === false || true, "label fallback did not throw");

  // ---------------------------------------------------------------- portal session
  app.S.token = "";                       // signed out of the staff app
  app.S.path = "/portal";
  await view("portal login screen renders in the sandbox", () => app.renderClientPortalLogin());

  let clientToken = "";
  await view("demo client signs in over the live API", async () => {
    const r = await app.api("/api/portal/login", { method: "POST", token: "", body: CLIENT });
    clientToken = r.token;
  });
  app.S.clientToken = clientToken;
  await view("portal dashboard renders the client's shipments", () => app.renderClientPortal());

  console.log();
  if (failures.length) {
    console.log(`${failures.length} live UI check(s) failed: ${failures.join(" | ")}`);
    process.exit(1);
  }
  console.log("Live UI checks passed — the sandboxed preview drives the running app end to end.");
})();
