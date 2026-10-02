/* ParcelDesk front-end (vanilla JS, no build step, no CDN) */
"use strict";

/* Some environments block browser storage and the history API outright — notably a
   sandbox="allow-scripts" preview iframe, and locked-down kiosk browsers. Both throw
   SecurityError, which would kill the whole app on load, so fall back to memory and keep
   routing inside the app instead of depending on the address bar. */
const store = (() => {
  try {
    const probe = "__pd_probe__";
    window.localStorage.setItem(probe, "1");
    window.localStorage.removeItem(probe);
    return window.localStorage;
  } catch (e) {
    const mem = new Map();
    return {
      getItem: (k) => (mem.has(k) ? mem.get(k) : null),
      setItem: (k, v) => { mem.set(k, String(v)); },
      removeItem: (k) => { mem.delete(k); },
      _memoryOnly: true,
    };
  }
})();

function currentPath() {
  try { return location.pathname || "/"; } catch (e) { return "/"; }
}

/* Open a server-rendered page (labels, print sheets). A sandboxed preview iframe blocks
   window.open, so fall back to navigating this tab rather than doing nothing. */
async function openPage(url) {
  let win = null;
  try { win = window.open("about:blank", "_blank"); if (win) win.opener = null; } catch {}
  try {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${S.token}` } });
    if (!res.ok) throw new Error("Cannot open print page — sign in again or retry");
    const blobUrl = URL.createObjectURL(await res.blob());
    if (win) win.location = blobUrl;
    else location.assign(blobUrl);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 600000);
  } catch (err) { if (win) win.close(); toast(err.message, "err"); }
}

async function downloadFile(url) {
  try {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${S.token}` } });
    if (!res.ok) throw new Error("Export failed — sign in again or retry");
    const blobUrl = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = (res.headers.get("content-disposition") || "").match(/filename="([^"\r\n]+)"/)?.[1] || url.split("?")[0].split("/").pop();
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
  } catch (err) { toast(err.message, "err"); }
}

function liveOrigin() {
  // location.href is readable even where location.origin is opaque ("null")
  try {
    const match = String(location.href || "").match(/^([a-z][a-z0-9+.\-]*:\/\/[^\/]+)/i);
    if (match) return match[1];
  } catch (e) { /* fall through */ }
  try {
    const origin = location.origin;
    if (origin && origin !== "null") return origin;
  } catch (e) { /* fall through */ }
  return "";
}

function shareBase() {
  const configured = String((S.settings && S.settings.public_base_url) || "").replace(/\/+$/, "");
  const isLocalhost = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(configured);
  if (configured && !isLocalhost) return configured;   // an explicit public address wins
  return liveOrigin().replace(/\/+$/, "") || configured;  // else whatever host it is served on
}

function portalLink(token) {
  return `${shareBase()}/portal/${token}`;
}

function publicOrigin() {
  const configured = (S.settings && S.settings.public_base_url) || "";
  try { return configured || location.origin; } catch (e) { return configured; }
}

const S = {
  path: currentPath(),
  token: store.getItem("pd_token") || "",
  clientToken: store.getItem("pd_client_token") || "",
  client: null,
  user: null,
  carriers: [],
  clients: [],
  demoMode: false,
  settings: {},
  filters: { q: "", carrier: "all", status: "all", client_id: "", days: "", offset: 0, limit: 50 },
};

const CARRIER_LABEL = { dhl: "DHL Express", fedex: "FedEx", aramex: "Aramex", ups: "UPS",
  dhlecom: "DHL eCommerce / Parcel", colissimo: "Colissimo / La Poste", track17: "17TRACK (EMS, postal, other)",
  manual: "Manual / Other" };
const CARRIER_ABBR = { dhl: "DHL", fedex: "FX", aramex: "ARX", ups: "UPS", dhlecom: "DHe",
  colissimo: "COL", track17: "17T", manual: "—" };
const STATUS_ORDER = ["registered", "picked_up", "received", "in_transit", "customs", "out_for_delivery",
  "delivered", "exception", "returned", "cancelled", "unknown"];
const STATUS_LABEL = {
  registered: "Label created", picked_up: "Picked up", received: "Received at warehouse",
  in_transit: "In transit", customs: "In customs", out_for_delivery: "Out for delivery",
  delivered: "Delivered", exception: "Exception", returned: "Returned",
  cancelled: "Cancelled", unknown: "Update",
};

/* ------------------------------------------------------------------ utils */
const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtDate(iso, withTime = true) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (isNaN(d)) return "—";
  const date = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  return withTime ? `${date} ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : date;
}
function fmtRel(iso) {
  if (!iso) return "never";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (isNaN(mins)) return "—";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} d ago`;
}
function money(amount, currency) {
  if (amount === null || amount === undefined || amount === "") return "—";
  try {
    return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(amount) + " " + (currency || "");
  } catch { return `${amount} ${currency || ""}`; }
}
function statusChip(status) {
  return `<span class="chip s-${esc(status)}"><span class="dot"></span>${esc(STATUS_LABEL[status] || status)}</span>`;
}
function carrierCell(carrier) {
  const key = CARRIER_LABEL[carrier] ? carrier : "manual";
  const abbr = CARRIER_ABBR[key] || key.slice(0, 3).toUpperCase();
  return `<span class="carrier carrier-${key}"><span class="badge">${abbr}</span>${esc(CARRIER_LABEL[key])}</span>`;
}
function carrierOptions(selected = "", includeAuto = true) {
  return (includeAuto ? '<option value="">Auto-detect</option>' : "") +
    Object.keys(CARRIER_LABEL).map((c) =>
      `<option value="${c}" ${selected === c ? "selected" : ""}>${esc(CARRIER_LABEL[c])}</option>`).join("");
}
function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = message;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 6500 : 4200);
}
async function copy(text) {
  try {
    if (!navigator.clipboard) throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard", "ok");
  } catch { prompt("Copy this link:", text); }
}

async function api(path, { method = "GET", body, form, token } = {}) {
  const headers = {};
  const isPortalCall = path.startsWith("/api/portal/");
  const isLogin = path.includes("/auth/login");
  const auth = token === undefined ? (isPortalCall ? S.clientToken : S.token) : token;
  if (auth) headers.Authorization = `Bearer ${auth}`;
  // remember exactly which session this request went out with ("" = anonymous request)
  const sentToken = isPortalCall ? "" : (auth || "");
  let payload;
  if (form) { payload = form; }
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }

  // One quiet retry first. A dropped connection or a proxy hiccup on a flaky link must not
  // sign the user out or paint an error over a screen that would have loaded fine.
  let res = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      res = await fetch(path, { method, headers, body: payload });
    } catch (err) {
      if (attempt === 0 && method === "GET") { await sleep(400); continue; }
      throw new Error("Cannot reach the server — check your connection and try again");
    }
    const transient = (res.status === 401 || res.status === 502 || res.status === 503)
      && attempt === 0 && !isLogin && method === "GET";
    if (!transient) break;
    await sleep(300);
  }

  // A 401 only means "session expired" if this request carried the session token we are
  // still using. A token-less request (public page, portal, first boot) is just a
  // rejection of that call — it must never clear someone else's live session.
  if (res.status === 401 && !isLogin && !isPortalCall && sentToken && S.token === sentToken) {
    logout(); throw new Error("Session expired");
  }
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) throw new Error((isJson && (data.detail || data.message)) || "Request failed");
  return data;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* ------------------------------------------------------------------ modal */
function modal({ title, body, submitLabel = "Save", onSubmit, width, danger = false }) {
  closeModal();
  const wrap = document.createElement("div");
  wrap.className = "modal-backdrop";
  wrap.id = "modal-backdrop";
  wrap.innerHTML = `
    <div class="modal" style="${width ? `width:min(${width},100%)` : ""}">
      <div class="modal-head"><h3>${esc(title)}</h3><button class="x-btn" data-close>&times;</button></div>
      <form id="modal-form"><div class="modal-body">${body}</div>
        <div class="modal-foot">
          <button type="button" class="btn" data-close>Cancel</button>
          <button type="submit" class="btn ${danger ? "danger" : "primary"}">${esc(submitLabel)}</button>
        </div></form>
    </div>`;
  document.body.appendChild(wrap);
  wrap.addEventListener("click", (e) => { if (e.target === wrap || e.target.dataset.close !== undefined) closeModal(); });
  wrap.querySelector("#modal-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    try { await onSubmit(new FormData(e.target)); closeModal(); }
    catch (err) { toast(err.message, "err"); }
    finally { btn.disabled = false; }
  });
  return wrap;
}
function closeModal() { $("#modal-backdrop")?.remove(); }

/* ------------------------------------------------------------------ icons */
const ICONS = {
  dashboard: '<path d="M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z"/>',
  box: '<path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.5 3-5.5 6.5-5.5s6.5 2 6.5 5.5"/><path d="M17 4.5a3 3 0 010 7M18 20c0-2.4-.7-4-2-5"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  scan: '<path d="M4 8V5.5A1.5 1.5 0 015.5 4H8M16 4h2.5A1.5 1.5 0 0120 5.5V8M20 16v2.5a1.5 1.5 0 01-1.5 1.5H16M8 20H5.5A1.5 1.5 0 014 18.5V16"/><path d="M4 12h16"/>',
  refresh: '<path d="M21 12a9 9 0 11-3-6.7"/><path d="M21 3v6h-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"/>',
  download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 20h16"/>',
  logout: '<path d="M15 4h3a1 1 0 011 1v14a1 1 0 01-1 1h-3"/><path d="M10 8l-4 4 4 4M6 12h9"/>',
  link: '<path d="M10 13a5 5 0 007 0l2-2a5 5 0 00-7-7l-1 1"/><path d="M14 11a5 5 0 00-7 0l-2 2a5 5 0 007 7l1-1"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
  trash: '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/>',
  edit: '<path d="M4 20h4L20 8l-4-4L4 16z"/>',
  alert: '<path d="M12 3l9 16H3z"/><path d="M12 9v5M12 17h.01"/>',
  printer: '<path d="M6 9V3h12v6"/><rect x="4" y="9" width="16" height="8" rx="1.5"/><path d="M8 17h8v4H8z"/>',
  warehouse: '<path d="M2 8.5L12 3l10 5.5V11H2z"/><path d="M4 11v10h16V11"/><path d="M9 21v-6h6v6"/>',
  activity: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
  truck: '<path d="M3 16V6h11v10"/><path d="M14 9h4l3 3v4h-7z"/><circle cx="7.5" cy="18" r="1.8"/><circle cx="17.5" cy="18" r="1.8"/>',
  key: '<circle cx="8" cy="14" r="4"/><path d="M11 11l9-9M17 5l2 2M14 8l2 2"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;

/* ------------------------------------------------------------------ shell */
function shell(active, title, contentHTML, actionsHTML = "") {
  const navItems = [
    ["/", "dashboard", "Dashboard"],
    ["/parcels", "box", "Parcels"],
    ["/receiving", "scan", "Receiving"],
    ["/stock", "warehouse", "Stock"],
    ["/clients", "users", "Clients"],
    ["/reports", "chart", "Reports"],
    ["/diagnostics", "activity", "Diagnostics"],
    ["/settings", "gear", "Settings"],
  ];
  $("#root").innerHTML = `
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo">PD</div>
        <div><div class="brand-name">ParcelDesk</div><div class="brand-sub">${esc(S.settings.company_name || "Multi-carrier tracking")}</div></div>
      </div>
      ${S.demoMode ? '<div class="demo-flag">DEMO MODE — simulated carrier data</div>' : ""}
      ${navItems.map(([href, ic, label]) => `
        <a class="nav-item ${active === href ? "active" : ""}" href="${href}" data-nav>
          ${icon(ic)}<span>${label}</span></a>`).join("")}
      <div class="sidebar-foot">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <div class="avatar">${esc((S.user?.name || S.user?.email || "?").slice(0, 1).toUpperCase())}</div>
          <div><div style="color:#e2e8f0">${esc(S.user?.name || S.user?.email || "")}</div>
          <div>${esc(S.user?.role || "")}</div></div>
        </div>
        <button class="nav-item" id="logout-btn">${icon("logout")}<span>Sign out</span></button>
      </div>
    </aside>
    <div class="main">
      <div class="topbar">
        <h1>${esc(title)}</h1>
        <div class="grow"></div>
        <div class="search">${icon("search")}<input id="global-search" placeholder="Search tracking no, ref, client…" value="${esc(S.filters.q)}"></div>
        ${actionsHTML}
      </div>
      <div class="content" id="view">${contentHTML}</div>
    </div>
  </div>`;
  document.querySelectorAll("a[data-nav]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault(); navigate(a.getAttribute("href"));
  }));
  $("#logout-btn").addEventListener("click", logout);
  const search = $("#global-search");
  if (search) {
    let t;
    search.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(() => { S.filters.q = search.value; S.filters.offset = 0; navigate("/parcels"); }, 350);
    });
  }
}
function setPath(path, replace = false) {
  S.path = path;
  try {
    if (replace) history.replaceState({}, "", path); else history.pushState({}, "", path);
  } catch (e) {
    /* address bar not writable here — routing continues in JS below */
  }
}
function navigate(path, replace = false) {
  setPath(path, replace);
  router();
}
function logout() {
  store.removeItem("pd_token");
  S.token = ""; S.user = null;
  setPath("/login", true);
  router();
}
function loading() { $("#root").innerHTML = '<div class="page-load"><span class="spinner"></span></div>'; }

/* ------------------------------------------------------------------ router */
async function router() {
  closeModal();
  const path = S.path || "/";
  if (path.startsWith("/track/")) return renderTrack(path.split("/")[2]);
  if (path.startsWith("/portal/")) return renderPortal(path.split("/")[2]);
  if (path === "/portal") return renderClientPortalLogin();
  if (!S.token) return renderLogin();
  if (!S.user) {
    loading();
    try {
      S.user = await api("/api/auth/me");
      await loadRefData();
    } catch { return renderLogin(); }
  }
  if (path === "/login") return navigate("/", true);
  if (path === "/" || path === "") return renderDashboard();
  if (path === "/parcels") return renderParcels();
  if (path.startsWith("/parcels/")) return renderParcelDetail(parseInt(path.split("/")[2], 10));
  if (path === "/receiving") return renderReceiving();
  if (path === "/stock") return renderStock();
  if (path === "/clients") return renderClients();
  if (path === "/reports") return renderReports();
  if (path === "/diagnostics") return renderDiagnostics();
  if (path === "/settings") return renderSettings();
  return navigate("/", true);
}
window.addEventListener("popstate", () => {
  S.path = currentPath();      // back/forward button — resync from the address bar
  router();
});

async function loadRefData() {
  try {
    const [carriers, clients, settings] = await Promise.all([
      api("/api/carriers"), api("/api/clients"), api("/api/settings"),
    ]);
    S.carriers = carriers.carriers;
    S.carriers.forEach((c) => { CARRIER_LABEL[c.name] = c.label; CARRIER_ABBR[c.name] = c.abbr || c.name; });
    S.demoMode = carriers.demo_mode;
    S.clients = clients;
    S.settings = settings;
  } catch (e) { /* non fatal */ }
}

/* ------------------------------------------------------------------ login */
function renderLogin() {
  $("#root").innerHTML = `
  <div class="auth-wrap"><div class="auth-card">
    <div class="brand"><div class="brand-logo">PD</div>
      <div><div class="brand-name">ParcelDesk</div>
      <div class="brand-sub">DHL · FedEx · Aramex tracking</div></div></div>
    <h2 style="margin-top:14px">Sign in</h2>
    <p class="muted small">Track every parcel, alert on delays, keep clients informed.</p>
    <form id="login-form">
      <div class="field"><label>Email</label><input name="email" type="email" autocomplete="username" required value="admin@example.com"></div>
      <div class="field"><label>Password</label><input name="password" type="password" autocomplete="current-password" required></div>
      <button class="btn primary" style="width:100%;justify-content:center" type="submit">Sign in</button>
    </form>
    <p class="help" style="margin-top:14px">First run uses the FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD from your .env file.</p>
  </div></div>`;
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const res = await api("/api/auth/login", { method: "POST", body: { email: fd.get("email"), password: fd.get("password") } });
      S.token = res.token; S.user = res.user;
      store.setItem("pd_token", res.token);
      await loadRefData();
      navigate("/", true);
    } catch (err) { toast(err.message, "err"); }
  });
}

/* ------------------------------------------------------------------ dashboard */
async function renderDashboard() {
  loading();
  try {
    const [stats, recent, stuck, runs] = await Promise.all([
      api("/api/parcels/stats?days=30"),
      api("/api/parcels?limit=8"),
      api("/api/stuck"),
      api("/api/sync/runs?limit=1"),
    ]);
    const lastRun = runs[0];
    const content = `
      <div class="row" style="justify-content:space-between;margin-bottom:16px">
        <div class="muted">Live overview of every shipment across your carriers.</div>
        <div class="row">
          <button class="btn" id="sync-all">${icon("refresh")} Sync all now</button>
          <button class="btn" id="import-btn">${icon("upload")} Import</button>
          <button class="btn primary" id="add-parcel">${icon("plus")} Add parcel</button>
        </div>
      </div>
      ${S.demoMode ? '<div class="banner warn">Demo mode is on — carrier responses are simulated so you can explore the platform. Add your DHL/FedEx/Aramex credentials in <b>.env</b> and restart to go live.</div>' : ""}
      ${stuck.length ? `<div class="banner warn"><b>${stuck.length} parcel(s) need attention</b> — held in customs or with no movement. <a href="#" id="show-stuck">Review now</a></div>` : ""}
      <div class="kpis">
        <div class="kpi"><div class="label">Open parcels</div><div class="value">${stats.open}</div>
          <div class="sub">${stats.added_period} added in ${stats.window_days}d</div></div>
        <div class="kpi accent-green"><div class="label">Delivered</div><div class="value">${stats.delivered_period}</div>
          <div class="sub">last ${stats.window_days} days</div></div>
        <div class="kpi accent-amber"><div class="label">In customs</div><div class="value">${stats.in_customs}</div>
          <div class="sub">clearance pending</div></div>
        <div class="kpi accent-red"><div class="label">Exceptions</div><div class="value">${stats.exceptions}</div>
          <div class="sub">needs action</div></div>
        <div class="kpi accent-violet"><div class="label">Out for delivery</div><div class="value">${stats.out_for_delivery}</div>
          <div class="sub">arriving today</div></div>
        <div class="kpi"><div class="label">Avg transit</div><div class="value">${stats.avg_transit_days ?? "—"}</div>
          <div class="sub">days, delivered</div></div>
        <div class="kpi"><div class="label">On-time rate</div><div class="value">${stats.on_time_pct ?? "—"}${stats.on_time_pct ? "%" : ""}</div>
          <div class="sub">vs carrier ETA</div></div>
        <div class="kpi accent-red"><div class="label">Stuck &gt; SLA</div><div class="value">${stats.stuck}</div>
          <div class="sub">customs / silent</div></div>
      </div>
      <div class="cols">
        <div class="card">
          <div class="card-head"><h2>Latest activity</h2><div class="grow"></div>
            <a class="btn sm" href="/parcels" data-viewall>View all</a></div>
          <div class="table-wrap">${recentTable(recent.items)}</div>
        </div>
        <div>
          <div class="card" style="margin-bottom:18px">
            <div class="card-head"><h3>By carrier</h3></div>
            <div class="card-body">${carrierBars(stats.by_carrier)}</div>
          </div>
          <div class="card" style="margin-bottom:18px">
            <div class="card-head"><h3>Pipeline</h3></div>
            <div class="card-body">${statusBars(stats.by_status, stats.total)}</div>
          </div>
          <div class="card">
            <div class="card-head"><h3>System</h3></div>
            <div class="card-body small">
              <div style="margin-bottom:6px"><b>Carrier sync:</b>
                ${lastRun ? `last run ${fmtRel(lastRun.started_at)} — ${lastRun.parcels_checked} checked, ${lastRun.events_added} new events${lastRun.errors ? `, <span style="color:var(--red)">${lastRun.errors} errors</span>` : ""}` : "not run yet"}</div>
              <div style="margin-bottom:6px"><b>Interval:</b> every ${S.settings.sync_interval_minutes} min · <b>Demo:</b> ${S.demoMode ? "on" : "off"}</div>
              <div><b>Alerts:</b> ${S.settings.alerts_enabled ? "enabled" : "disabled"} · Email: ${S.settings.smtp_configured ? "SMTP configured" : "<span style='color:var(--amber)'>SMTP not configured</span>"}</div>
            </div>
          </div>
        </div>
      </div>`;

    shell("/", "Dashboard", content, `<button class="btn" id="export-xlsx">${icon("download")} Export</button>`);
    $("#add-parcel").addEventListener("click", () => parcelModal());
    $("#import-btn").addEventListener("click", importModal);
    $("#export-xlsx").addEventListener("click", () => downloadFile("/api/parcels/export.xlsx"));
    document.querySelectorAll("[data-parcel]").forEach((r) => r.addEventListener("click", () => navigate(`/parcels/${r.dataset.parcel}`)));
    document.querySelector("[data-viewall]")?.addEventListener("click", (e) => { e.preventDefault(); navigate("/parcels"); });
    $("#sync-all").addEventListener("click", async (e) => {
      e.target.disabled = true;
      try { toast((await api("/api/sync/run", { method: "POST" })).message); setTimeout(router, 2500); }
      catch (err) { toast(err.message, "err"); e.target.disabled = false; }
    });
    $("#show-stuck")?.addEventListener("click", (e) => { e.preventDefault(); S.filters.status = "customs"; navigate("/parcels"); });
  } catch (err) {
    $("#root").innerHTML = `<div class="content"><div class="banner err">${esc(err.message)}</div></div>`;
  }
}

function recentTable(items) {
  if (!items.length) return `<div class="empty"><h3>No parcels yet</h3><p>Add your first tracking number to get started.</p></div>`;
  return `<table><thead><tr><th>Tracking</th><th>Carrier</th><th>Client</th><th>Status</th><th>ETA</th><th>Updated</th></tr></thead><tbody>
    ${items.map((p) => `<tr class="clickable" data-parcel="${p.id}">
      <td><span class="mono">${esc(p.tracking_number)}</span>${p.client_reference ? `<div class="muted small">${esc(p.client_reference)}</div>` : ""}</td>
      <td>${carrierCell(p.carrier)}</td>
      <td class="truncate">${esc(p.client_name || "—")}</td>
      <td>${statusChip(p.status)}<div class="muted small truncate" style="max-width:230px">${esc(p.status_text || "")}</div></td>
      <td class="nowrap small">${fmtDate(p.eta, false)}</td>
      <td class="nowrap small muted">${fmtRel(p.last_event_at || p.created_at)}</td>
    </tr>`).join("")}</tbody></table>`;
}
function carrierBars(rows) {
  if (!rows.length) return '<div class="muted small">No data yet.</div>';
  const max = Math.max(...rows.map((r) => r.total)) || 1;
  return rows.map((r) => `<div class="bar-row">
      <div>${esc(CARRIER_LABEL[r.carrier] || r.carrier)}</div>
      <div class="bar"><span style="width:${Math.round(100 * r.total / max)}%"></span></div>
      <div class="muted">${r.total}</div></div>
      <div class="small muted" style="margin:-4px 0 10px 102px">${r.open} open · ${r.delivered} delivered</div>`).join("");
}
function statusBars(rows, total) {
  if (!rows.length) return '<div class="muted small">No data yet.</div>';
  const max = Math.max(...rows.map((r) => r.count)) || 1;
  return rows.map((r) => `<div class="bar-row">
      <div>${esc(STATUS_LABEL[r.status] || r.status)}</div>
      <div class="bar ${["delivered"].includes(r.status) ? "green" : ["customs", "exception"].includes(r.status) ? "amber" : ""}"><span style="width:${Math.round(100 * r.count / max)}%"></span></div>
      <div class="muted">${r.count}</div></div>`).join("");
}

/* ------------------------------------------------------------------ parcels list */
async function renderParcels() {
  loading();
  const f = S.filters;
  const params = new URLSearchParams();
  if (f.q) params.set("q", f.q);
  if (f.carrier !== "all") params.set("carrier", f.carrier);
  if (f.status !== "all") params.set("status", f.status);
  if (f.client_id) params.set("client_id", f.client_id);
  if (f.days) params.set("days", f.days);
  params.set("limit", f.limit); params.set("offset", f.offset);

  try {
    const data = await api("/api/parcels?" + params.toString());
    const content = `
      <div class="row" style="margin-bottom:14px">
        <select id="f-carrier" style="width:auto">${["all", ...Object.keys(CARRIER_LABEL)]
          .map((c) => `<option value="${c}" ${f.carrier === c ? "selected" : ""}>${c === "all" ? "All carriers" : CARRIER_LABEL[c]}</option>`).join("")}</select>
        <select id="f-status" style="width:auto">${["all", "open", ...STATUS_ORDER]
          .map((s) => `<option value="${s}" ${f.status === s ? "selected" : ""}>${s === "all" ? "All statuses" : s === "open" ? "Open only" : STATUS_LABEL[s]}</option>`).join("")}</select>
        <select id="f-client" style="width:auto"><option value="">All clients</option>
          ${S.clients.map((c) => `<option value="${c.id}" ${String(f.client_id) === String(c.id) ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
        <select id="f-days" style="width:auto">${[["", "Any time"], [7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"]]
          .map(([v, l]) => `<option value="${v}" ${String(f.days) === String(v) ? "selected" : ""}>${l}</option>`).join("")}</select>
        <div class="grow" style="flex:1"></div>
        <span class="muted small">${data.total} parcel(s)</span>
      </div>
      <div class="card"><div class="table-wrap">
        ${data.items.length ? parcelsTable(data.items) : '<div class="empty"><h3>Nothing matches these filters</h3><p>Try clearing the search or filters.</p></div>'}
      </div></div>
      <div class="row" style="justify-content:space-between;margin-top:14px">
        <button class="btn" id="prev" ${f.offset === 0 ? "disabled" : ""}>← Previous</button>
        <span class="muted small">Showing ${f.offset + 1}–${Math.min(f.offset + f.limit, data.total)} of ${data.total}</span>
        <button class="btn" id="next" ${f.offset + f.limit >= data.total ? "disabled" : ""}>Next →</button>
      </div>`;

    shell("/parcels", "Parcels", content,
      `<button class="btn" id="import-btn">${icon("upload")} Import</button>
       <button class="btn" id="export-csv">CSV</button>
       <button class="btn" id="export-xlsx">${icon("download")} Excel</button>
       <button class="btn primary" id="add-parcel">${icon("plus")} Add parcel</button>`);

    const rebuild = () => { S.filters.offset = 0; renderParcels(); };
    $("#f-carrier").addEventListener("change", (e) => { f.carrier = e.target.value; rebuild(); });
    $("#f-status").addEventListener("change", (e) => { f.status = e.target.value; rebuild(); });
    $("#f-client").addEventListener("change", (e) => { f.client_id = e.target.value; rebuild(); });
    $("#f-days").addEventListener("change", (e) => { f.days = e.target.value; rebuild(); });
    $("#prev").addEventListener("click", () => { f.offset = Math.max(0, f.offset - f.limit); renderParcels(); });
    $("#next").addEventListener("click", () => { f.offset += f.limit; renderParcels(); });
    $("#add-parcel").addEventListener("click", () => parcelModal());
    $("#import-btn").addEventListener("click", importModal);
    const exportParams = new URLSearchParams(params); exportParams.delete("limit"); exportParams.delete("offset");
    $("#export-xlsx").addEventListener("click", () => downloadFile("/api/parcels/export.xlsx?" + exportParams));
    $("#export-csv").addEventListener("click", () => downloadFile("/api/parcels/export.csv?" + exportParams));
    document.querySelectorAll("[data-parcel]").forEach((el) => el.addEventListener("click", () => navigate(`/parcels/${el.dataset.parcel}`)));
    document.querySelectorAll("[data-sync]").forEach((el) => el.addEventListener("click", async (e) => {
      e.stopPropagation(); el.disabled = true;
      try {
        const r = await api(`/api/parcels/${el.dataset.sync}/sync`, { method: "POST" });
        toast(r.error ? r.error : `Synced — ${r.added} new event(s)`, r.error ? "err" : "ok");
        renderParcels();
      } catch (err) { toast(err.message, "err"); el.disabled = false; }
    }));
  } catch (err) { $("#root").innerHTML = `<div class="content"><div class="banner err">${esc(err.message)}</div></div>`; }
}

function parcelsTable(items) {
  const canEdit = ["admin", "operator"].includes(S.user?.role);
  return `<table><thead><tr>
      <th>Tracking</th><th>Carrier</th><th>Client / Reference</th><th>Description</th>
      <th>Status</th><th>ETA</th><th>Days</th><th>Last update</th>${canEdit ? "<th></th>" : ""}
    </tr></thead><tbody>
    ${items.map((p) => `<tr class="clickable" data-parcel="${p.id}">
      <td><span class="mono">${esc(p.tracking_number)}</span>
        ${p.storage_location ? `<div class="small" style="color:var(--green)">▣ ${esc(p.storage_location)}</div>` : ""}
        ${p.last_sync_error && !["finished", "manual tracking", "sync disabled for this parcel"].includes(p.last_sync_error) ? `<div class="small" style="color:var(--amber)" title="${esc(p.last_sync_error)}">⚠ ${esc(p.last_sync_error.slice(0, 34))}…</div>` : ""}</td>
      <td>${carrierCell(p.carrier)}</td>
      <td><div class="truncate">${esc(p.client_name || "—")}</div><div class="muted small">${esc(p.client_reference || "")}</div></td>
      <td class="truncate small">${esc(p.description || "—")}</td>
      <td>${statusChip(p.status)}<div class="muted small truncate" style="max-width:240px">${esc(p.status_text || "")}</div></td>
      <td class="nowrap small">${fmtDate(p.eta, false)}</td>
      <td class="small">${p.days_in_transit}</td>
      <td class="nowrap small muted">${fmtRel(p.last_event_at || p.created_at)}</td>
      ${canEdit ? `<td class="nowrap"><button class="btn sm" data-sync="${p.id}" title="Sync with carrier">${icon("refresh")}</button></td>` : ""}
    </tr>`).join("")}</tbody></table>`;
}

/* ------------------------------------------------------------------ parcel detail */
async function renderParcelDetail(id) {
  loading();
  try {
    const p = await api(`/api/parcels/${id}`);
    const canEdit = ["admin", "operator"].includes(S.user?.role);
    const isAdmin = S.user?.role === "admin";
    const events = p.events || [];
    const content = `
      <div class="row" style="margin-bottom:16px">
        <a class="btn" href="/parcels" data-back>← All parcels</a>
        <div class="grow" style="flex:1"></div>
        ${canEdit ? `<button class="btn primary" id="receive">${icon("scan")} ${p.received_at ? "Update receipt" : "Receive at warehouse"}</button>
        <button class="btn" id="sync">${icon("refresh")} Sync now</button>
        <button class="btn" id="add-update">${icon("plus")} Add update</button>
        <button class="btn" id="edit">${icon("edit")} Edit</button>
        <button class="btn" id="label">${icon("printer")} Label</button>
        ${p.received_at && !p.released_at ? `<button class="btn" id="release">${icon("truck")} Release</button>` : ""}
        ${p.released_at ? `<button class="btn" id="unrelease">Undo release</button>` : ""}
        <button class="btn" id="share">${icon("link")} Share link</button>
        <button class="btn" id="remind">${icon("mail")} Email update</button>` : ""}
        ${isAdmin ? `<button class="btn danger" id="delete">${icon("trash")} Delete</button>` : ""}
      </div>
      <div class="card" style="margin-bottom:18px">
        <div class="card-body">
          <div class="row" style="justify-content:space-between">
            <div>
              <div class="tag">${esc(CARRIER_LABEL[p.carrier])}</div>
              <h2 class="mono" style="font-size:1.35rem;margin:2px 0 8px">${esc(p.tracking_number)}</h2>
              <div class="row">${statusChip(p.status)}<span class="muted">${esc(p.status_text || "")}</span></div>
            </div>
            <div style="text-align:right">
              ${p.tracking_url ? `<a class="btn" href="${esc(p.tracking_url)}" target="_blank" rel="noopener">Carrier website ↗</a>` : ""}
              ${p.share_token ? `<div class="small muted" style="margin-top:8px">Client link active</div>` : ""}
            </div>
          </div>
          ${p.last_sync_error && !["finished", "manual tracking"].includes(p.last_sync_error) ? `<div class="banner warn" style="margin:14px 0 0">Carrier sync note: ${esc(p.last_sync_error)}</div>` : ""}
        </div>
      </div>
      <div class="split">
        <div class="card">
          <div class="card-head"><h2>Tracking history</h2><div class="grow" style="flex:1"></div>
            <span class="muted small">${events.length} event(s)</span></div>
          <div class="card-body">
            ${events.length ? `<ul class="timeline">${events.map((e, i) => `
              <li class="${i === 0 ? "now" : ""}">
                <div class="t-title">${esc(e.status_text || STATUS_LABEL[e.status] || e.status)}
                  ${e.source === "manual" ? '<span class="pill">manual</span>' : ""}</div>
                <div class="t-meta">${fmtDate(e.occurred_at)}${e.location ? " · " + esc(e.location) : ""}</div>
                ${e.description && e.description !== e.status_text ? `<div class="t-desc">${esc(e.description)}</div>` : ""}
              </li>`).join("")}</ul>` : '<div class="empty"><p>No tracking events yet. Use “Sync now” or add a manual update.</p></div>'}
          </div>
        </div>
        <div>
          <div class="card" style="margin-bottom:18px">
            <div class="card-head"><h3>Shipment details</h3></div>
            <div class="card-body">
              <dl class="dl">
                <dt>Client</dt><dd>${p.client ? esc(p.client.name) : "—"}</dd>
                <dt>Reference</dt><dd>${esc(p.client_reference || "—")}</dd>
                <dt>Description</dt><dd>${esc(p.description || "—")}</dd>
                <dt>Origin</dt><dd>${esc(p.origin || "—")}</dd>
                <dt>Destination</dt><dd>${esc(p.destination || "—")}</dd>
                <dt>ETA</dt><dd>${fmtDate(p.eta, false)}</dd>
                <dt>Delivered</dt><dd>${fmtDate(p.delivered_at)}</dd>
                <dt>Days in transit</dt><dd>${p.days_in_transit}</dd>
                <dt>Weight</dt><dd>${p.weight_kg ? p.weight_kg + " kg" : "—"}</dd>
                <dt>Cost</dt><dd>${money(p.cost_amount, p.cost_currency)}</dd>
                <dt>Received at</dt><dd>${p.received_at ? `${fmtDate(p.received_at)} — ${esc(p.received_by || "")}` : "not received yet"}</dd>
                <dt>Storage location</dt><dd>${esc(p.storage_location || "—")}</dd>
                <dt>Cartons</dt><dd>${p.cartons_expected > 1
                  ? `${p.cartons_received || 0} of ${p.cartons_expected} received${p.cartons_outstanding ? ` · ${p.cartons_outstanding} still to arrive` : " · complete"}`
                  : (p.cartons_expected ? "1 carton" : "—")}</dd>
                <dt>Released</dt><dd>${p.released_at ? `${fmtDate(p.released_at)} — ${esc(p.released_to || "")}` : "still in the warehouse"}</dd>
                <dt>Barcode</dt><dd class="mono">${esc(p.barcode || "—")}${p.barcode_svg_url ? ` <a href="/labels/${p.id}" data-open-page>print label ↗</a>` : ""}</dd>
                <dt>Created</dt><dd>${fmtDate(p.created_at)}</dd>
                <dt>Last synced</dt><dd>${fmtRel(p.last_synced_at)}</dd>
                <dt>Auto-sync</dt><dd>${p.sync_enabled ? "on" : "off"}</dd>
              </dl>
              ${p.notes ? `<div style="margin-top:14px"><div class="tag">Notes</div><div class="small">${esc(p.notes)}</div></div>` : ""}
            </div>
          </div>
          ${p.client ? `<div class="card">
            <div class="card-head"><h3>Client contact</h3></div>
            <div class="card-body small">
              <div style="font-weight:600">${esc(p.client.name)}</div>
              ${p.client.email ? `<div><a href="mailto:${esc(p.client.email)}">${esc(p.client.email)}</a></div>` : ""}
              ${p.client.phone ? `<div>${esc(p.client.phone)}</div>` : ""}
            </div></div>` : ""}
        </div>
      </div>`;

    shell("/parcels", "Parcel " + p.tracking_number, content);
    $("[data-back]").addEventListener("click", (e) => { e.preventDefault(); navigate("/parcels"); });
    document.querySelectorAll("[data-open-page]").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault(); openPage(a.getAttribute("href"));
    }));

    $("#sync")?.addEventListener("click", async (e) => {
      e.target.disabled = true; e.target.innerHTML = `<span class="spinner"></span> Syncing…`;
      try {
        const r = await api(`/api/parcels/${id}/sync`, { method: "POST" });
        toast(r.error ? r.error : `Synced — ${r.added} new event(s)`, r.error ? "err" : "ok");
      } catch (err) { toast(err.message, "err"); }
      renderParcelDetail(id);
    });
    $("#receive")?.addEventListener("click", () => receiveModal(p, () => renderParcelDetail(id)));
    $("#label")?.addEventListener("click", () => openPage(`/labels/${id}`));
    $("#release")?.addEventListener("click", () => releaseModal({
      id, tracking_number: p.tracking_number, client_name: p.client?.name || p.released_to || "" },
      () => renderParcelDetail(id)));
    $("#unrelease")?.addEventListener("click", async () => {
      try {
        await api(`/api/receiving/${id}/release/undo`, { method: "POST" });
        toast("Release undone — parcel is back on the shelf", "ok");
      } catch (err) { toast(err.message, "err"); }
      renderParcelDetail(id);
    });
    $("#add-update")?.addEventListener("click", () => manualUpdateModal(p));
    $("#edit")?.addEventListener("click", () => parcelModal(p));
    $("#delete")?.addEventListener("click", () => modal({
      title: "Delete parcel", danger: true, submitLabel: "Delete permanently",
      body: `<p>Delete <b class="mono">${esc(p.tracking_number)}</b> and its full history? This cannot be undone.</p>`,
      onSubmit: async () => { await api(`/api/parcels/${id}`, { method: "DELETE" }); toast("Parcel deleted", "ok"); navigate("/parcels"); },
    }));
    $("#share")?.addEventListener("click", async () => {
      const r = await api(`/api/parcels/${id}/share`, { method: "POST" });
      modal({
        title: "Share tracking link", submitLabel: "Done",
        body: `<p class="small">Send this read-only link to your client — no login needed, it shows the live timeline.</p>
               <input value="${esc(r.url)}" readonly onclick="this.select()">
               <div class="row" style="margin-top:10px"><button type="button" class="btn" id="copy-link">Copy link</button>
               <button type="button" class="btn danger" id="revoke">Revoke link</button></div>`,
        onSubmit: async () => {},
      });
      $("#copy-link").addEventListener("click", () => copy(r.url));
      $("#revoke").addEventListener("click", async () => {
        await api(`/api/parcels/${id}/share`, { method: "DELETE" });
        toast("Link revoked", "ok"); closeModal(); renderParcelDetail(id);
      });
    });
    $("#remind")?.addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        const r = await api(`/api/parcels/${id}/remind`, { method: "POST" });
        toast(r.ok ? `Email sent to ${r.recipients.join(", ")}` : `Email queued but not sent: ${r.error}`,
          r.ok ? "ok" : "err");
      } catch (err) { toast(err.message, "err"); }
      e.target.disabled = false;
    });
  } catch (err) { $("#root").innerHTML = `<div class="content"><div class="banner err">${esc(err.message)}</div></div>`; }
}

/* ------------------------------------------------------------------ modals: parcel / update / import */
function parcelModal(existing = null) {
  const p = existing || {};
  modal({
    title: existing ? "Edit parcel" : "Add parcel",
    submitLabel: existing ? "Save changes" : "Add & track",
    body: `
      <div class="field"><label>Tracking number *</label>
        <input name="tracking_number" required value="${esc(p.tracking_number || "")}" ${existing ? "readonly" : ""} placeholder="e.g. 1234567890">
        <div class="help" id="detect-hint">${existing ? "" : "Carrier is detected automatically from the number format."}</div></div>
      <div class="grid2">
        <div class="field"><label>Carrier</label>
          <select name="carrier">${carrierOptions(p.carrier)}</select></div>
        <div class="field"><label>Client</label>
          <input name="client_name" list="client-list" value="${esc(p.client ? p.client.name : p.client_name || "")}" placeholder="Existing or new client">
          <datalist id="client-list">${S.clients.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist></div>
      </div>
      <div class="grid2">
        <div class="field"><label>Client reference / order no</label><input name="client_reference" value="${esc(p.client_reference || "")}"></div>
        <div class="field"><label>Description of goods</label><input name="description" value="${esc(p.description || "")}"></div>
      </div>
      <div class="grid2">
        <div class="field"><label>Origin</label><input name="origin" value="${esc(p.origin || "")}" placeholder="Paris (CDG), FR"></div>
        <div class="field"><label>Destination</label><input name="destination" value="${esc(p.destination || "Antananarivo (TNR), MG")}"></div>
      </div>
      <div class="grid3">
        <div class="field"><label>Cost</label><input name="cost_amount" type="number" step="any" value="${p.cost_amount ?? ""}"></div>
        <div class="field"><label>Currency</label><input name="cost_currency" value="${esc(p.cost_currency || "MGA")}"></div>
        <div class="field"><label>Weight (kg)</label><input name="weight_kg" type="number" step="any" value="${p.weight_kg ?? ""}"></div>
      </div>
      <div class="grid2">
        <div class="field"><label>Alternate barcode (for scanning)</label><input name="barcode" value="${esc(p.barcode || "")}" placeholder="optional — scanned label code"></div>
        <div class="field"><label>Storage location</label><input name="storage_location" value="${esc(p.storage_location || "")}" placeholder="e.g. Rack B3 / Bin 12"></div>
        <div class="field"><label>Cartons expected</label><input name="cartons_expected" type="number" min="1" value="${p.cartons_expected || 1}"></div>
      </div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="2">${esc(p.notes || "")}</textarea></div>
      ${existing ? `<div class="checkbox"><input type="checkbox" name="sync_enabled" id="se" ${p.sync_enabled ? "checked" : ""}><label for="se" style="margin:0">Keep checking this parcel automatically</label></div>` : ""}`,
    onSubmit: async (fd) => {
      if (existing) {
        const payload = {
          carrier: fd.get("carrier") || existing.carrier,
          description: fd.get("description"), client_reference: fd.get("client_reference"),
          origin: fd.get("origin"), destination: fd.get("destination"),
          cost_amount: fd.get("cost_amount") ? parseFloat(fd.get("cost_amount")) : null,
          cost_currency: fd.get("cost_currency"), weight_kg: fd.get("weight_kg") ? parseFloat(fd.get("weight_kg")) : null,
          barcode: fd.get("barcode"), storage_location: fd.get("storage_location"),
          cartons_expected: Math.max(1, parseInt(fd.get("cartons_expected") || "1", 10) || 1),
          notes: fd.get("notes"), sync_enabled: fd.get("sync_enabled") !== null,
        };
        const clientName = String(fd.get("client_name") || "").trim();
        if (clientName && clientName !== (existing.client?.name || "")) {
          const existingClient = S.clients.find((c) => c.name.toLowerCase() === clientName.toLowerCase());
          payload.client_id = existingClient ? existingClient.id : undefined;
          if (!existingClient) {
            const created = await api("/api/clients", { method: "POST", body: { name: clientName } });
            payload.client_id = created.id;
          }
        }
        await api(`/api/parcels/${existing.id}`, { method: "PATCH", body: payload });
        toast("Parcel updated", "ok");
        await loadRefData(); renderParcelDetail(existing.id);
        return;
      }
      const body = {
        tracking_number: String(fd.get("tracking_number")).trim(),
        carrier: fd.get("carrier") || null,
        client_name: String(fd.get("client_name") || "").trim() || null,
        description: fd.get("description"), client_reference: fd.get("client_reference"),
        origin: fd.get("origin"), destination: fd.get("destination"),
        cost_amount: fd.get("cost_amount") ? parseFloat(fd.get("cost_amount")) : null,
        cost_currency: fd.get("cost_currency"), weight_kg: fd.get("weight_kg") ? parseFloat(fd.get("weight_kg")) : null,
        barcode: fd.get("barcode") || "", storage_location: fd.get("storage_location") || "",
        cartons_expected: Math.max(1, parseInt(fd.get("cartons_expected") || "1", 10) || 1),
        notes: fd.get("notes"), sync_now: true,
      };
      const created = await api("/api/parcels", { method: "POST", body });
      toast(`Tracking ${created.tracking_number} via ${CARRIER_LABEL[created.carrier]}`, "ok");
      await loadRefData();
      navigate(`/parcels/${created.id}`);
    },
  });
  const tn = document.querySelector('input[name="tracking_number"]');
  const hint = $("#detect-hint");
  if (tn && !existing) {
    let timer;
    tn.addEventListener("input", () => {
      clearTimeout(timer);
      const value = tn.value.trim();
      if (value.length < 6) { hint.textContent = "Carrier is detected automatically from the number format."; return; }
      timer = setTimeout(async () => {
        try {
          const r = await api("/api/parcels/detect?number=" + encodeURIComponent(value));
          hint.innerHTML = `Detected: <b>${esc(CARRIER_LABEL[r.guess])}</b>${r.candidates.length > 1 ? ` (could also be ${r.candidates.slice(1).map((c) => esc(CARRIER_LABEL[c.carrier])).join(", ")})` : ""}`;
          const sel = document.querySelector('select[name="carrier"]');
          if (sel && !sel.value) sel.value = r.guess;
        } catch { /* ignore */ }
      }, 320);
    });
  }
}

function manualUpdateModal(parcel) {
  modal({
    title: "Add manual tracking update",
    submitLabel: "Save update",
    body: `
      <p class="small muted">Use this when the carrier API has no data yet, or when the courier tells you something by phone/WhatsApp.</p>
      <div class="grid2">
        <div class="field"><label>Status</label><select name="status">
          ${STATUS_ORDER.map((s) => `<option value="${s}" ${s === parcel.status ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("")}
        </select></div>
        <div class="field"><label>Date &amp; time</label><input type="datetime-local" name="occurred_at"></div>
      </div>
      <div class="field"><label>What happened</label><input name="status_text" placeholder="e.g. Cleared customs, awaiting pickup"></div>
      <div class="field"><label>Location</label><input name="location" placeholder="Antananarivo (TNR), MG"></div>
      <div class="field"><label>Internal note (optional)</label><textarea name="description" rows="2"></textarea></div>`,
    onSubmit: async (fd) => {
      await api(`/api/parcels/${parcel.id}/events`, {
        method: "POST",
        body: {
          status: fd.get("status"), status_text: fd.get("status_text"),
          location: fd.get("location"), description: fd.get("description"),
          occurred_at: fd.get("occurred_at") ? new Date(fd.get("occurred_at")).toISOString() : null,
        },
      });
      toast("Update saved", "ok");
      renderParcelDetail(parcel.id);
    },
  });
}

function importModal() {
  modal({
    title: "Import parcels",
    submitLabel: "Import",
    width: "720px",
    body: `<div class="tabs"><button type="button" class="tab active" data-tab="paste">Paste list</button>
        <button type="button" class="tab" data-tab="file">Upload CSV / Excel</button></div>
      <div id="tab-paste">
        <div class="field"><label>One parcel per line</label>
          <textarea name="text" rows="8" placeholder="tracking_number, carrier, client, description
1234567890, DHL, Société Mada Import, Spare parts
9876543210, Aramex, Pharma Océan Indien, Documents"></textarea>
          <div class="help">Carrier and client are optional — carrier is auto-detected, unknown clients are created automatically. Comma, semicolon or tab separated.</div></div>
        <div class="checkbox"><input type="checkbox" name="sync_now" id="imp-sync" checked><label for="imp-sync" style="margin:0">Fetch carrier status right after import</label></div>
      </div>
      <div id="tab-file" style="display:none">
        <div class="field"><label>CSV or XLSX file</label><input type="file" name="file" accept=".csv,.xlsx,.xlsm,.txt"></div>
        <div class="help">Recognised columns: tracking_number, carrier, client, reference, description, origin, destination, cost, currency, weight, barcode, storage_location, notes, eta. A single column of tracking numbers also works.</div>
      </div>`,
    onSubmit: async (fd) => {
      const file = fd.get("file");
      const usingFile = file && file.size > 0 && $("#tab-file").style.display !== "none";
      let result;
      if (usingFile) {
        const form = new FormData();
        form.append("file", file);
        form.append("sync_now", fd.get("sync_now") ? "true" : "false");
        result = await api("/api/parcels/import/file", { method: "POST", form });
      } else {
        result = await api("/api/parcels/import", { method: "POST", body: {
          text: fd.get("text") || "", sync_now: !!fd.get("sync_now"),
        } });
      }
      toast(`Imported ${result.created.length} parcel(s)${result.skipped.length ? `, skipped ${result.skipped.length} duplicate(s)` : ""}`, "ok");
      await loadRefData();
      renderParcels();
    },
  });
  document.querySelectorAll("#modal-backdrop .tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll("#modal-backdrop .tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    $("#tab-paste").style.display = tab.dataset.tab === "paste" ? "" : "none";
    $("#tab-file").style.display = tab.dataset.tab === "file" ? "" : "none";
  }));
}

/* ------------------------------------------------------------------ clients */
async function renderClients() {
  loading();
  try {
    const clients = await api("/api/clients");
    S.clients = clients;
    const canEdit = ["admin", "operator"].includes(S.user?.role);
    const content = `
      <div class="row" style="justify-content:space-between;margin-bottom:16px">
        <div class="muted">Client accounts, references and their read-only tracking portals.</div>
        ${canEdit ? `<button class="btn primary" id="add-client">${icon("plus")} Add client</button>` : ""}
      </div>
      <div class="card"><div class="table-wrap">
        ${clients.length ? `<table><thead><tr><th>Client</th><th>Contact</th><th>Parcels</th><th>Reference prefix</th><th>Tracking link</th><th>Portal login</th>${canEdit ? "<th></th>" : ""}</tr></thead>
        <tbody>${clients.map((c) => `<tr>
          <td><b>${esc(c.name)}</b>${c.notify_client ? '<div class="pill" style="margin-top:3px">email notifications on</div>' : ""}</td>
          <td class="small">${esc(c.contact_name || "—")}<div class="muted">${esc(c.email || "")}</div><div class="muted">${esc(c.phone || "")}</div></td>
          <td><a href="#" data-parcels="${c.id}">${c.parcel_count}</a></td>
          <td class="small">${esc(c.reference_prefix || "—")}</td>
          <td class="small">${c.share_token
            ? `<button class="btn sm" data-copy-portal="${esc(portalLink(c.share_token))}">${icon("link")} Copy</button>
               <button class="btn sm" data-open-portal="${esc(portalLink(c.share_token))}">Open</button>`
            : canEdit ? `<button class="btn sm" data-enable-portal="${c.id}">Create link</button>` : '<span class="muted">none</span>'}</td>
          <td class="small">${c.portal_login
            ? `<span class="chip s-delivered"><span class="dot"></span>enabled</span>
               <div class="muted" style="margin-top:3px">${c.last_login_at ? "last seen " + fmtRel(c.last_login_at) : "never signed in"}</div>
               ${canEdit ? `<button class="btn sm" data-portal-pw="${c.id}">Reset password</button>
                 <button class="btn sm danger" data-portal-off="${c.id}">Revoke</button>` : ""}`
            : canEdit ? `<button class="btn sm" data-portal-pw="${c.id}">${icon("key")} Give portal access</button>`
                      : '<span class="muted">no password</span>'}</td>
          ${canEdit ? `<td class="nowrap"><button class="btn sm" data-edit-client="${c.id}">${icon("edit")}</button>
            ${S.user.role === "admin" ? `<button class="btn sm danger" data-del-client="${c.id}">${icon("trash")}</button>` : ""}</td>` : ""}
        </tr>`).join("")}</tbody></table>` : '<div class="empty"><h3>No clients yet</h3><p>Add a client, or simply type a new client name when adding a parcel.</p></div>'}
      </div></div>`;
    shell("/clients", "Clients", content);
    $("#add-client")?.addEventListener("click", () => clientModal());
    document.querySelectorAll("[data-edit-client]").forEach((b) => b.addEventListener("click", () =>
      clientModal(clients.find((c) => c.id === parseInt(b.dataset.editClient, 10)))));
    document.querySelectorAll("[data-del-client]").forEach((b) => b.addEventListener("click", () => {
      const client = clients.find((c) => c.id === parseInt(b.dataset.delClient, 10));
      modal({
        title: "Delete client", danger: true, submitLabel: "Delete",
        body: `<p>Delete <b>${esc(client.name)}</b>? Their parcels stay in the system but become unassigned.</p>`,
        onSubmit: async () => { await api(`/api/clients/${client.id}`, { method: "DELETE" }); toast("Client deleted", "ok"); renderClients(); },
      });
    }));
    document.querySelectorAll("[data-enable-portal]").forEach((b) => b.addEventListener("click", async () => {
      const r = await api(`/api/clients/${b.dataset.enablePortal}/portal`, { method: "POST" });
      copy(r.portal_url); renderClients();
    }));
    document.querySelectorAll("[data-copy-portal]").forEach((b) => b.addEventListener("click", () => copy(b.dataset.copyPortal)));
    document.querySelectorAll("[data-open-portal]").forEach((b) => b.addEventListener("click", () => openPage(b.dataset.openPortal)));
    document.querySelectorAll("[data-portal-pw]").forEach((b) => b.addEventListener("click", () =>
      clientPortalModal(clients.find((c) => c.id === parseInt(b.dataset.portalPw, 10)))));
    document.querySelectorAll("[data-portal-off]").forEach((b) => b.addEventListener("click", () => {
      const client = clients.find((c) => c.id === parseInt(b.dataset.portalOff, 10));
      modal({
        title: "Revoke portal access", danger: true, submitLabel: "Revoke access",
        body: `<p>Remove the portal password for <b>${esc(client.name)}</b>? Any device still signed in is kicked out
               immediately. The tracking link keeps working.</p>`,
        onSubmit: async () => {
          await api(`/api/clients/${client.id}/password`, { method: "DELETE" });
          toast("Portal access revoked", "ok"); renderClients();
        },
      });
    }));
    document.querySelectorAll("[data-parcels]").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault(); S.filters = { ...S.filters, client_id: a.dataset.parcels, offset: 0 }; navigate("/parcels");
    }));
  } catch (err) { $("#root").innerHTML = `<div class="content"><div class="banner err">${esc(err.message)}</div></div>`; }
}

function clientPortalModal(client) {
  modal({
    title: `Portal access — ${client.name}`,
    submitLabel: client.portal_login ? "Reset password" : "Enable portal login",
    body: `<p class="small muted">The client signs in at <span class="mono">${esc(publicOrigin())}/portal</span>
        with this email address and password, and sees only their own shipments, cartons and releases.</p>
      <div class="field"><label>Login email *</label>
        <input name="email" type="email" required value="${esc(client.email || "")}" placeholder="client@example.com"></div>
      <div class="field"><label>Password *</label>
        <input name="password" type="text" minlength="6" required
          value="${Math.random().toString(36).slice(2, 6) + "-" + Math.random().toString(36).slice(2, 6)}"
          placeholder="at least 6 characters"></div>
      <div class="help">Read the password out to the client, or copy it and send it by WhatsApp/email. They can change it
        themselves once signed in.</div>`,
    onSubmit: async (fd) => {
      const email = String(fd.get("email") || "").trim();
      if (email && email !== (client.email || "")) {
        await api(`/api/clients/${client.id}`, { method: "PATCH", body: { email } });
      }
      await api(`/api/clients/${client.id}/password`, { method: "POST", body: {
        password: fd.get("password") } });
      copy(String(fd.get("password")));
      toast("Portal access enabled — password copied", "ok");
      renderClients();
    },
  });
}

function clientModal(client = null) {
  const c = client || {};
  modal({
    title: client ? "Edit client" : "Add client",
    submitLabel: client ? "Save" : "Create client",
    body: `<div class="field"><label>Company / client name *</label><input name="name" required value="${esc(c.name || "")}"></div>
      <div class="grid2">
        <div class="field"><label>Contact person</label><input name="contact_name" value="${esc(c.contact_name || "")}"></div>
        <div class="field"><label>Email</label><input name="email" type="email" value="${esc(c.email || "")}"></div>
      </div>
      <div class="grid2">
        <div class="field"><label>Phone</label><input name="phone" value="${esc(c.phone || "")}"></div>
        <div class="field"><label>Reference prefix</label><input name="reference_prefix" value="${esc(c.reference_prefix || "")}" placeholder="e.g. POI"></div>
      </div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="2">${esc(c.notes || "")}</textarea></div>
      <div class="checkbox" style="margin-bottom:6px"><input type="checkbox" name="notify_client" id="nc" ${c.notify_client ? "checked" : ""}>
        <label for="nc" style="margin:0">Email this client automatically on status changes (needs SMTP configured)</label></div>
      <div class="checkbox"><input type="checkbox" name="notify_sms" id="ncs" ${c.notify_sms ? "checked" : ""}>
        <label for="ncs" style="margin:0">Send this client WhatsApp/SMS alerts on key status changes</label></div>`,
    onSubmit: async (fd) => {
      const body = {
        name: fd.get("name"), contact_name: fd.get("contact_name"), email: fd.get("email"),
        phone: fd.get("phone"), reference_prefix: fd.get("reference_prefix"),
        notes: fd.get("notes"), notify_client: !!fd.get("notify_client"),
        notify_sms: !!fd.get("notify_sms"),
      };
      if (client) await api(`/api/clients/${client.id}`, { method: "PATCH", body });
      else await api("/api/clients", { method: "POST", body });
      toast("Client saved", "ok");
      renderClients();
    },
  });
}

/* ------------------------------------------------------------------ reports */
async function renderReports() {
  loading();
  const content = `
    <div class="row" style="margin-bottom:16px">
      <label style="margin:0">Period</label>
      <select id="days" style="width:auto">
        <option value="7">Last 7 days</option><option value="30" selected>Last 30 days</option>
        <option value="90">Last 90 days</option><option value="365">Last 12 months</option>
      </select>
      <div style="flex:1"></div>
      <button class="btn" id="exp-csv">${icon("download")} CSV</button>
      <button class="btn primary" id="exp-xlsx">${icon("download")} Excel report</button>
    </div>
    <div id="report-body"><div class="page-load"><span class="spinner"></span></div></div>`;
  shell("/reports", "Reports", content);
  const load = async (days) => {
    $("#report-body").innerHTML = '<div class="page-load"><span class="spinner"></span></div>';
    const stats = await api(`/api/parcels/stats?days=${days}`);
    $("#report-body").innerHTML = `
      <div class="kpis">
        <div class="kpi"><div class="label">Parcels added</div><div class="value">${stats.added_period}</div><div class="sub">last ${days} days</div></div>
        <div class="kpi accent-green"><div class="label">Delivered</div><div class="value">${stats.delivered_period}</div><div class="sub">last ${days} days</div></div>
        <div class="kpi"><div class="label">Avg transit</div><div class="value">${stats.avg_transit_days ?? "—"}</div><div class="sub">days door to door</div></div>
        <div class="kpi accent-green"><div class="label">On-time rate</div><div class="value">${stats.on_time_pct ?? "—"}${stats.on_time_pct ? "%" : ""}</div><div class="sub">delivered by carrier ETA</div></div>
        <div class="kpi accent-red"><div class="label">Currently stuck</div><div class="value">${stats.stuck}</div><div class="sub">past SLA</div></div>
      </div>
      <div class="cols">
        <div class="card"><div class="card-head"><h2>Carrier performance</h2></div><div class="table-wrap">
          <table><thead><tr><th>Carrier</th><th>Total</th><th>Open</th><th>Delivered</th><th>Completion</th></tr></thead><tbody>
          ${stats.by_carrier.map((r) => `<tr><td>${carrierCell(r.carrier)}</td><td>${r.total}</td><td>${r.open}</td>
            <td>${r.delivered}</td><td>${r.total ? Math.round(100 * r.delivered / r.total) : 0}%</td></tr>`).join("")}
          </tbody></table></div></div>
        <div class="card"><div class="card-head"><h2>Status breakdown</h2></div><div class="card-body">${statusBars(stats.by_status, stats.total)}</div></div>
      </div>
      <div class="card" style="margin-top:18px"><div class="card-head"><h2>Selected parcels export</h2></div>
        <div class="card-body">
          <p class="small muted">Exports include every field (client, reference, cost, weight, ETA, tracking link) plus a summary sheet, ready to send to a client or your accountant.</p>
          <div class="row">
            <button class="btn" id="exp-xlsx2">${icon("download")} Export all parcels (Excel)</button>
            <button class="btn" id="exp-open">Open parcels only</button>
            <button class="btn" id="exp-delivered">Delivered only</button>
          </div>
        </div></div>`;
    $("#exp-xlsx2").addEventListener("click", () => downloadFile("/api/parcels/export.xlsx"));
    $("#exp-open").addEventListener("click", () => downloadFile("/api/parcels/export.xlsx?status=open"));
    $("#exp-delivered").addEventListener("click", () => downloadFile("/api/parcels/export.xlsx?status=delivered"));
  };
  await load(30);
  $("#days").addEventListener("change", (e) => load(e.target.value));
  $("#exp-xlsx").addEventListener("click", () => downloadFile("/api/parcels/export.xlsx"));
  $("#exp-csv").addEventListener("click", () => downloadFile("/api/parcels/export.csv"));
}

/* ------------------------------------------------------------------ settings */
async function renderSettings() {
  loading();
  try {
    const [carriers, settings, users, runs, notifications, messaging] = await Promise.all([
      api("/api/carriers"), api("/api/settings"),
      api("/api/users").catch(() => []), api("/api/sync/runs?limit=10"),
      api("/api/notifications?limit=20"), api("/api/messaging"),
    ]);
    S.settings = settings;
    const isAdmin = S.user?.role === "admin";
    const envSnippet = `# .env — paste your carrier credentials, then restart ParcelDesk
DEMO_MODE=false

# DHL Express — developer.dhl.com (Shipment Tracking - Unified)
DHL_API_KEY=your_key
DHL_API_SECRET=your_secret

# FedEx — developer.fedex.com (Track API project required)
FEDEX_CLIENT_ID=your_client_id
FEDEX_CLIENT_SECRET=your_client_secret

# Aramex — account credentials issued for API access
ARAMEX_USERNAME=your_user
ARAMEX_PASSWORD=your_pass
ARAMEX_ACCOUNT_NUMBER=123456
ARAMEX_ACCOUNT_PIN=1234
ARAMEX_ACCOUNT_ENTITY=TNR
ARAMEX_ACCOUNT_COUNTRY_CODE=MG

# Email alerts (Gmail example: use an App Password)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=app_password
SMTP_FROM=parcels@yourcompany.mg`;

    const content = `
      <div class="tabs">
        <button class="tab active" data-tab="carriers">Carriers</button>
        <button class="tab" data-tab="alerts">Alerts &amp; email</button>
        <button class="tab" data-tab="automation">Automation</button>
        ${isAdmin ? '<button class="tab" data-tab="users">Users</button>' : ""}
      </div>

      <div id="t-carriers">
        <div class="grid3">
          ${carriers.carriers.map((c) => `<div class="card"><div class="card-body">
            <div class="row" style="justify-content:space-between">
              <h3 style="margin:0">${esc(c.label)}</h3>
              ${c.demo ? '<span class="chip s-customs"><span class="dot"></span>demo</span>'
                       : c.configured ? '<span class="chip s-delivered"><span class="dot"></span>connected</span>'
                                      : '<span class="chip s-exception"><span class="dot"></span>not configured</span>'}
            </div>
            <p class="small muted" style="margin:8px 0 0">
              ${c.name === "manual" ? "Track by hand — no API needed."
                : c.configured ? "Live API polling is active for this carrier."
                : `Missing: ${esc(c.missing.join(", ") || "credentials")}`}
            </p>
          </div></div>`).join("")}
        </div>
        <div class="card" style="margin-top:18px">
          <div class="card-head"><h2>How to connect live carrier APIs</h2></div>
          <div class="card-body">
            <ol class="small" style="margin:0 0 12px;padding-left:18px">
              <li><b>DHL:</b> register at developer.dhl.com → create an app with <i>Shipment Tracking – Unified</i> → copy API Key + Secret.</li>
              <li><b>FedEx:</b> register at developer.fedex.com → create a project with <b>Track API</b> → copy API Key + Secret Key.</li>
              <li><b>Aramex:</b> request API access from your Aramex account manager → they issue username, password, account number, PIN, entity and country code.</li>
              <li>Put the values in <span class="mono">.env</span> next to the app, set <span class="mono">DEMO_MODE=false</span>, restart, then press <b>Test connection</b> below or run a sync.</li>
            </ol>
            <div class="code">${esc(envSnippet)}</div>
            <div class="help" style="margin-top:8px">Credentials stay on your server — they are never sent anywhere except the carrier APIs.</div>
          </div>
        </div>
      </div>

      <div id="t-alerts" style="display:none">
        <div class="cols">
          <div class="card"><div class="card-head"><h2>Alert rules</h2></div><div class="card-body">
            <div class="checkbox" style="margin-bottom:12px">
              <input type="checkbox" id="alerts-enabled" ${settings.alerts_enabled ? "checked" : ""} ${isAdmin ? "" : "disabled"}>
              <label for="alerts-enabled" style="margin:0">Email alerts enabled</label></div>
            <div class="small muted" style="margin-bottom:12px">Alert on these statuses (from .env ALERT_ON_STATUSES): <b>${esc(settings.alert_on_statuses)}</b></div>
            <div class="small" style="margin-bottom:14px">Stuck-in-customs alert after <b>${settings.stuck_customs_days}</b> days · no-movement alert after <b>${settings.stuck_transit_days}</b> days. Adjust in the Automation tab.</div>
            <div class="row">
              ${isAdmin ? `<button class="btn" id="test-email">${icon("mail")} Send test email</button>
              <button class="btn" id="digest">Send digest now</button>
              <button class="btn" id="stuck-now">Check stuck parcels now</button>` : '<span class="muted small">Admin access required.</span>'}
            </div>
            <div class="banner ${settings.smtp_configured ? "info" : "warn"}" style="margin-top:16px">
              ${settings.smtp_configured
                ? `SMTP server configured: <b>${esc(settings.smtp_host)}</b> — emails are sent from ${esc(settings.smtp_from)}.`
                : "SMTP is not configured yet, so alerts are saved in the log below but not emailed. Add SMTP_HOST, SMTP_USER and SMTP_PASSWORD to .env (Gmail needs an App Password) and restart."}
            </div>
          </div></div>
          <div class="card" style="margin-top:18px"><div class="card-head"><h2>WhatsApp / SMS alerts</h2>
            <div style="flex:1"></div>
            ${messaging.configured ? '<span class="chip s-delivered"><span class="dot"></span>connected</span>'
              : messaging.provider === "none" ? '<span class="chip s-cancelled"><span class="dot"></span>not configured</span>'
              : '<span class="chip s-exception"><span class="dot"></span>incomplete</span>'}</div>
            <div class="card-body">
              <div class="small" style="margin-bottom:10px"><b>Provider:</b> ${esc(messaging.provider_label)}
                ${messaging.missing.length ? `<span class="muted">· missing ${esc(messaging.missing.join(", "))}</span>` : ""}</div>
              <div class="small muted" style="margin-bottom:12px">Text alerts fire on: <b>${esc(messaging.alert_statuses)}</b> · recipients are team members who ticked &ldquo;SMS/WA&rdquo; plus clients flagged for it, or the fallback numbers in .env.</div>
              <div class="code"># WhatsApp (Meta Cloud API) — developers.facebook.com → WhatsApp → API Setup
MESSAGING_PROVIDER=whatsapp
WHATSAPP_TOKEN=permanent_token
WHATSAPP_PHONE_ID=1234567890

# Twilio (SMS or WhatsApp)
# MESSAGING_PROVIDER=twilio
# TWILIO_ACCOUNT_SID=ACxxx
# TWILIO_AUTH_TOKEN=xxx
# TWILIO_FROM=+12025550123
# TWILIO_USE_WHATSAPP=false

# Generic HTTP gateway (Africa's Talking, Vonage, n8n, your own bot)
# MESSAGING_PROVIDER=webhook
# WEBHOOK_URL=https://example.com/send
# MESSAGING_RECIPIENTS=+261340000000</div>
              <div class="row" style="margin-top:14px">
                ${isAdmin ? `<input id="msg-to" placeholder="+261 34 000 0000" style="width:200px">
                <button class="btn" id="test-msg">${icon("mail")} Send test text</button>` : '<span class="muted small">Admin access required.</span>'}
              </div>
            </div></div>
          <div class="card" style="margin-top:18px"><div class="card-head"><h2>Recent alerts</h2></div><div class="table-wrap">
            <table><thead><tr><th>When</th><th>Where</th><th>Subject</th><th>Sent</th></tr></thead><tbody>
            ${notifications.length ? notifications.map((n) => `<tr>
              <td class="small nowrap">${fmtDate(n.created_at)}</td>
              <td class="small"><span class="pill">${esc(n.channel || "email")}</span></td>
              <td class="small">${esc(n.subject)}<div class="muted">${esc(n.recipients || "no recipients")}</div>
                ${n.error ? `<div class="small" style="color:var(--amber)">${esc(n.error)}</div>` : ""}</td>
              <td>${n.ok ? '<span class="chip s-delivered"><span class="dot"></span>sent</span>' : '<span class="chip s-cancelled"><span class="dot"></span>logged</span>'}</td>
            </tr>`).join("") : '<tr><td colspan="3" class="muted small" style="padding:20px">No alerts yet.</td></tr>'}
            </tbody></table></div></div>
        </div>
      </div>

      <div id="t-automation" style="display:none">
        <div class="cols">
          <div class="card"><div class="card-head"><h2>Tracking automation</h2></div><div class="card-body">
            <div class="grid2">
              <div class="field"><label>Sync every (minutes)</label><input type="number" id="sync-interval" value="${settings.sync_interval_minutes}" min="5" ${isAdmin ? "" : "disabled"}></div>
              <div class="field"><label>Daily digest hour (0-23, UTC)</label><input type="number" id="digest-hour" value="${settings.daily_digest_hour}" min="0" max="23" ${isAdmin ? "" : "disabled"}></div>
              <div class="field"><label>Stuck in customs after (days)</label><input type="number" id="stuck-customs" value="${settings.stuck_customs_days}" min="1" ${isAdmin ? "" : "disabled"}></div>
              <div class="field"><label>No movement after (days)</label><input type="number" id="stuck-transit" value="${settings.stuck_transit_days}" min="1" ${isAdmin ? "" : "disabled"}></div>
            </div>
            <div class="grid3">
              <div class="field"><label>Out-for-delivery sweep</label>
                <select id="ofd-enabled" ${isAdmin ? "" : "disabled"}>
                  <option value="1" ${settings.ofd_sync_enabled ? "selected" : ""}>On — poll faster near delivery</option>
                  <option value="0" ${settings.ofd_sync_enabled ? "" : "selected"}>Off</option></select></div>
              <div class="field"><label>Out-for-delivery every (minutes)</label><input type="number" id="ofd-minutes" value="${settings.ofd_sync_minutes}" min="10" ${isAdmin ? "" : "disabled"}></div>
              <div class="field"><label>Warehouse ageing alert after (days)</label><input type="number" id="stale-days" value="${settings.warehouse_stale_days}" min="1" ${isAdmin ? "" : "disabled"}></div>
            </div>
            <div class="help" style="margin-bottom:12px">Parcels that are out for delivery move fastest, so they are re-checked on
              their own tighter schedule instead of waiting for the next full sync. Warehouse ageing drives the Stock screen
              and the daily &ldquo;still on the shelf&rdquo; alert.</div>
            <div class="field"><label>Company name (shown in emails)</label><input id="company-name" value="${esc(settings.company_name)}" ${isAdmin ? "" : "disabled"}></div>
            <div class="field"><label>Public base URL (for client links)</label><input id="public-url" value="${esc(settings.public_base_url)}" ${isAdmin ? "" : "disabled"}></div>
            ${isAdmin ? '<button class="btn primary" id="save-settings">Save settings</button>' : ""}
            <div class="row" style="margin-top:14px"><button class="btn" id="run-sync">${icon("refresh")} Run full carrier sync now</button></div>
          </div></div>
          <div class="card"><div class="card-head"><h2>Sync history</h2></div><div class="table-wrap">
            <table><thead><tr><th>Started</th><th>Trigger</th><th>Checked</th><th>New events</th><th>Errors</th></tr></thead><tbody>
            ${runs.length ? runs.map((r) => `<tr>
              <td class="small nowrap">${fmtDate(r.started_at)}</td><td class="small">${esc(r.trigger)}</td>
              <td>${r.parcels_checked}</td><td>${r.events_added}</td>
              <td>${r.errors ? `<span style="color:var(--red)">${r.errors}</span>` : "0"}</td></tr>`).join("")
              : '<tr><td colspan="5" class="muted small" style="padding:20px">No sync runs yet.</td></tr>'}
            </tbody></table></div></div>
        </div>
      </div>

      ${isAdmin ? `<div id="t-users" style="display:none">
        <div class="row" style="justify-content:space-between;margin-bottom:14px">
          <div class="muted small">Roles: <b>admin</b> full control · <b>operator</b> add/edit parcels · <b>viewer</b> read-only.</div>
          <button class="btn primary" id="add-user">${icon("plus")} Add user</button></div>
        <div class="card"><div class="table-wrap">
          <table><thead><tr><th>User</th><th>Role</th><th>Phone</th><th>Email</th><th>SMS/WA</th><th>Status</th><th></th></tr></thead><tbody>
          ${users.map((u) => `<tr>
            <td><b>${esc(u.name || u.email)}</b><div class="muted small">${esc(u.email)}</div></td>
            <td><select data-role="${u.id}" style="width:auto">${["admin", "operator", "viewer"].map((r) => `<option ${u.role === r ? "selected" : ""}>${r}</option>`).join("")}</select></td>
            <td><input data-phone="${u.id}" value="${esc(u.phone || "")}" placeholder="+261…" style="width:130px"></td>
            <td><input type="checkbox" data-notify="${u.id}" ${u.notify_email ? "checked" : ""} style="width:auto"></td>
            <td><input type="checkbox" data-notify-sms="${u.id}" ${u.notify_sms ? "checked" : ""} style="width:auto"></td>
            <td>${u.is_active ? '<span class="chip s-delivered"><span class="dot"></span>active</span>' : '<span class="chip s-cancelled"><span class="dot"></span>disabled</span>'}</td>
            <td class="nowrap">
              <button class="btn sm" data-toggle-active="${u.id}" data-active="${u.is_active}">${u.is_active ? "Disable" : "Enable"}</button>
              <button class="btn sm" data-reset-pw="${u.id}">Reset password</button>
            </td></tr>`).join("")}
          </tbody></table></div></div>
      </div>` : ""}`;

    shell("/settings", "Settings", content);
    document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      ["carriers", "alerts", "automation", "users"].forEach((name) => {
        const el = $(`#t-${name}`); if (el) el.style.display = tab.dataset.tab === name ? "" : "none";
      });
    }));

    $("#test-email")?.addEventListener("click", async () => {
      try { const r = await api("/api/notifications/test", { method: "POST", body: {} });
        toast(`Test email sent to ${r.to}`, "ok"); }
      catch (err) { toast(err.message, "err"); }
    });
    $("#test-msg")?.addEventListener("click", async () => {
      const to = $("#msg-to").value.trim();
      try { const r = await api("/api/messaging/test", { method: "POST", body: { to: to || null } });
        toast(`Test ${r.channel} message sent to ${r.to}`, "ok"); }
      catch (err) { toast(err.message, "err"); }
    });
    $("#digest")?.addEventListener("click", async () => {
      try { const r = await api("/api/notifications/digest", { method: "POST" });
        toast(`Digest created (${r.open_parcels} open parcels)`, "ok"); renderSettings(); }
      catch (err) { toast(err.message, "err"); }
    });
    $("#stuck-now")?.addEventListener("click", async () => {
      try { const r = await api("/api/notifications/stuck", { method: "POST" });
        toast(`${r.alerts_created} stuck-parcel alert(s) created`, "ok"); renderSettings(); }
      catch (err) { toast(err.message, "err"); }
    });
    $("#alerts-enabled")?.addEventListener("change", async (e) => {
      try { await api("/api/settings", { method: "PUT", body: { alerts_enabled: e.target.checked } });
        toast("Saved", "ok"); } catch (err) { toast(err.message, "err"); }
    });
    $("#save-settings")?.addEventListener("click", async () => {
      try {
        await api("/api/settings", { method: "PUT", body: {
          sync_interval_minutes: parseInt($("#sync-interval").value, 10),
          daily_digest_hour: parseInt($("#digest-hour").value, 10),
          stuck_customs_days: parseInt($("#stuck-customs").value, 10),
          stuck_transit_days: parseInt($("#stuck-transit").value, 10),
          ofd_sync_enabled: $("#ofd-enabled").value === "1",
          ofd_sync_minutes: Math.max(10, parseInt($("#ofd-minutes").value, 10) || 60),
          warehouse_stale_days: Math.max(1, parseInt($("#stale-days").value, 10) || 7),
          company_name: $("#company-name").value,
          public_base_url: $("#public-url").value,
        } });
        toast("Settings saved", "ok"); await loadRefData(); renderSettings();
      } catch (err) { toast(err.message, "err"); }
    });
    $("#run-sync")?.addEventListener("click", async (e) => {
      e.target.disabled = true;
      try { toast((await api("/api/sync/run", { method: "POST" })).message); setTimeout(renderSettings, 2500); }
      catch (err) { toast(err.message, "err"); e.target.disabled = false; }
    });
    $("#add-user")?.addEventListener("click", () => modal({
      title: "Add user", submitLabel: "Create user",
      body: `<div class="grid2">
          <div class="field"><label>Name</label><input name="name"></div>
          <div class="field"><label>Email *</label><input name="email" type="email" required></div></div>
        <div class="grid2">
          <div class="field"><label>Password *</label><input name="password" type="password" minlength="6" required></div>
          <div class="field"><label>Role</label><select name="role">
            <option value="operator">operator</option><option value="viewer">viewer</option><option value="admin">admin</option></select></div></div>
        <div class="checkbox" style="margin-bottom:6px"><input type="checkbox" name="notify_email" id="un" checked><label for="un" style="margin:0">Receive email alerts</label></div>
        <div class="grid2">
          <div class="field"><label>Phone (WhatsApp/SMS)</label><input name="phone" placeholder="+261 34 000 0000"></div>
          <div class="field" style="display:flex;align-items:flex-end"><div class="checkbox"><input type="checkbox" name="notify_sms" id="un2"><label for="un2" style="margin:0">Receive WhatsApp/SMS alerts</label></div></div>
        </div>`,
      onSubmit: async (fd) => {
        await api("/api/users", { method: "POST", body: {
          name: fd.get("name"), email: fd.get("email"), password: fd.get("password"),
          role: fd.get("role"), phone: fd.get("phone"),
          notify_email: !!fd.get("notify_email"), notify_sms: !!fd.get("notify_sms") } });
        toast("User created", "ok"); renderSettings();
      },
    }));
    document.querySelectorAll("[data-role]").forEach((sel) => sel.addEventListener("change", async () => {
      try { await api(`/api/users/${sel.dataset.role}`, { method: "PATCH", body: { role: sel.value } });
        toast("Role updated", "ok"); } catch (err) { toast(err.message, "err"); renderSettings(); }
    }));
    document.querySelectorAll("[data-notify]").forEach((cb) => cb.addEventListener("change", async () => {
      await api(`/api/users/${cb.dataset.notify}`, { method: "PATCH", body: { notify_email: cb.checked } });
    }));
    document.querySelectorAll("[data-notify-sms]").forEach((cb) => cb.addEventListener("change", async () => {
      await api(`/api/users/${cb.dataset.notifySms}`, { method: "PATCH", body: { notify_sms: cb.checked } });
    }));
    document.querySelectorAll("[data-phone]").forEach((inp) => inp.addEventListener("change", async () => {
      try { await api(`/api/users/${inp.dataset.phone}`, { method: "PATCH", body: { phone: inp.value } });
        toast("Phone saved", "ok"); } catch (err) { toast(err.message, "err"); }
    }));
    document.querySelectorAll("[data-toggle-active]").forEach((b) => b.addEventListener("click", async () => {
      await api(`/api/users/${b.dataset.toggleActive}`, { method: "PATCH", body: { is_active: b.dataset.active === "false" } });
      renderSettings();
    }));
    document.querySelectorAll("[data-reset-pw]").forEach((b) => b.addEventListener("click", () => modal({
      title: "Reset password", submitLabel: "Set password",
      body: `<div class="field"><label>New password</label><input name="password" type="password" minlength="6" required></div>`,
      onSubmit: async (fd) => {
        await api(`/api/users/${b.dataset.resetPw}`, { method: "PATCH", body: { password: fd.get("password") } });
        toast("Password updated", "ok");
      },
    })));
  } catch (err) { $("#root").innerHTML = `<div class="content"><div class="banner err">${esc(err.message)}</div></div>`; }
}

/* ------------------------------------------------------------------ receiving */
function receiveModal(parcel, onDone) {
  modal({
    title: `Check in ${parcel.tracking_number}`,
    submitLabel: "Confirm receipt",
    body: `<p class="small muted">Marks the parcel as physically received at your warehouse: timestamp, who received it and where it is stored.</p>
      <div class="grid2">
        <div class="field"><label>Storage location</label><input name="storage_location" value="${esc(parcel.storage_location || "")}" placeholder="Rack B3 / Bin 12" autofocus></div>
        <div class="field"><label>Note (optional)</label><input name="note" placeholder="e.g. 2 of 2 cartons, box dented"></div>
      </div>
      <div class="checkbox"><input type="checkbox" name="mark_received" id="mr" checked>
        <label for="mr" style="margin:0">Set status to &ldquo;Received at warehouse&rdquo;</label></div>`,
    onSubmit: async (fd) => {
      await api(`/api/receiving/${parcel.id}/receive`, { method: "POST", body: {
        code: parcel.tracking_number,
        storage_location: fd.get("storage_location"),
        note: fd.get("note"),
        mark_received: !!fd.get("mark_received"),
      } });
      toast("Parcel checked in", "ok");
      onDone?.();
    },
  });
}

async function renderReceiving() {
  loading();
  try {
    const [pending, recent] = await Promise.all([
      api("/api/receiving/pending?limit=15"), api("/api/receiving/recent?limit=15"),
    ]);
    const content = `
      <div class="card" style="margin-bottom:18px">
        <div class="card-body">
          <div class="row" style="align-items:flex-end">
            <div style="flex:2;min-width:260px">
              <label>Scan or type tracking number / barcode</label>
              <input id="scan-input" class="scan-input" placeholder="Point the barcode reader here and scan&hellip;" autocomplete="off" autofocus>
            </div>
            <div style="flex:1;min-width:180px">
              <label>Storage location</label>
              <input id="scan-loc" placeholder="Rack B3 / Bin 12">
            </div>
            <button class="btn primary" id="scan-go" style="height:42px">${icon("scan")} Check in</button>
          </div>
          <div class="help">Barcode readers work like keyboards &mdash; scan and the parcel is found, checked in, and the field is
            cleared for the next one. Multi-carton shipments are checked in one carton at a time.&nbsp;
            <a href="/stock" data-nav-stock>Open the stock list →</a></div>
          <div id="scan-result" style="margin-top:14px"></div>
        </div>
      </div>
      <div class="cols">
        <div class="card">
          <div class="card-head"><h2>Expected inbound (not yet received)</h2><div style="flex:1"></div>
            <span class="muted small">${pending.length}</span></div>
          <div class="table-wrap">${pending.length ? `<table><thead><tr><th>Tracking</th><th>Carrier</th><th>Client</th><th>Status</th><th>ETA</th></tr></thead><tbody>
            ${pending.map((p) => `<tr class="clickable" data-parcel="${p.id}">
              <td class="mono">${esc(p.tracking_number)}</td><td>${carrierCell(p.carrier)}</td>
              <td class="truncate small">${esc(p.client_name || "—")}</td>
              <td>${statusChip(p.status)}</td><td class="small nowrap">${fmtDate(p.eta, false)}</td></tr>`).join("")}
          </tbody></table>` : '<div class="empty"><p>Nothing pending &mdash; every parcel has been checked in.</p></div>'}
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h2>Recently received</h2><div style="flex:1"></div>
            <a class="btn sm" href="/stock">All stock →</a></div>
          <div class="table-wrap">${recent.length ? `<table><thead><tr><th>Tracking</th><th>Cartons</th><th>Location</th><th>Received</th><th></th></tr></thead><tbody>
            ${recent.map((p) => `<tr>
              <td class="mono clickable" data-parcel="${p.id}">${esc(p.tracking_number)}<div class="muted small">${esc(p.client_name || "")}</div></td>
              <td class="small">${p.cartons_expected > 1 ? `${p.cartons_received || 0}/${p.cartons_expected}` : "1"}</td>
              <td class="small">${esc(p.storage_location || "—")}</td>
              <td class="small muted nowrap">${fmtRel(p.received_at)}<div>${esc(p.received_by || "")}</div></td>
              <td class="nowrap"><button class="btn sm" data-label="${p.id}">${icon("printer")}</button>
                ${p.complete ? `<button class="btn sm" data-release="${p.id}">Release</button>` : ""}</td></tr>`).join("")}
          </tbody></table>` : '<div class="empty"><p>No parcels checked in yet.</p></div>'}
          </div>
        </div>
      </div>`;

    shell("/receiving", "Warehouse receiving", content);
    const input = $("#scan-input");
    const boxes = () => $("#scan-result");

    const doScan = async () => {
      const code = input.value.trim();
      if (!code) return;
      boxes().innerHTML = '<div class="row"><span class="spinner"></span> Looking up&hellip;</div>';
      let res = null;
      try {
        res = await api("/api/receiving/scan", { method: "POST", body: {
          code, storage_location: $("#scan-loc").value.trim(), mark_received: true } });
        if (!res.found) {
          boxes().innerHTML = `<div class="banner warn">No parcel found for <b class="mono">${esc(code)}</b>.
            <button class="btn sm" id="scan-add" style="margin-left:10px">${icon("plus")} Add it as a new parcel</button></div>`;
          $("#scan-add").addEventListener("click", () => {
            parcelModal();
            setTimeout(() => { const f = document.querySelector('input[name="tracking_number"]'); if (f) f.value = code; }, 60);
          });
        } else {
          const pp = res.parcel;
          const expected = pp.cartons_expected || 1;
          const have = pp.cartons_received || 0;
          const complete = pp.complete !== undefined ? pp.complete : have >= expected;
          const cartonLine = expected > 1
            ? `<div class="small" style="margin-top:4px">Carton <b>${have}</b> of <b>${expected}</b>
               ${complete ? "&mdash; shipment complete ✓"
                          : "&mdash; " + (expected - have) + " carton(s) still to arrive"}</div>`
            : "";
          boxes().innerHTML = `<div class="banner ${res.already_received ? "info" : "ok-banner"}">
            <b>${res.already_received ? "Already received earlier &mdash; receipt refreshed" : "&#10003; Checked in"}:</b>
            <span class="mono">${esc(pp.tracking_number)}</span> &middot; ${esc(CARRIER_LABEL[pp.carrier])}
            ${pp.client_name ? " &middot; " + esc(pp.client_name) : ""}
            ${pp.storage_location ? ` &middot; stored at <b>${esc(pp.storage_location)}</b>` : ""}
            ${cartonLine}
            <div class="small" style="margin-top:4px">${esc(pp.status_text || "")}</div>
            <div class="row" style="margin-top:10px">
              <button class="btn sm" id="scan-label">${icon("printer")} Print label</button>
              <a class="btn sm" href="/parcels/${pp.id}">Open parcel</a>
              ${complete ? `<button class="btn sm primary" id="scan-release">Release from warehouse</button>` : ""}
            </div></div>`;
          const labelBtn = $("#scan-label");
          if (labelBtn) labelBtn.addEventListener("click", () => openPage(`/labels/${pp.id}`));
          const relBtn = $("#scan-release");
          if (relBtn) relBtn.addEventListener("click", () => releaseModal(
            { id: pp.id, tracking_number: pp.tracking_number, client_name: pp.client_name || "" },
            () => renderReceiving()));
          toast(`Checked in ${pp.tracking_number}`, "ok");
        }
      } catch (err) { boxes().innerHTML = `<div class="banner err">${esc(err.message)}</div>`; }
      input.value = "";
      if (input.focus) input.focus();
      if (res && res.found) {
        const [pend, rec] = await Promise.all([
          api("/api/receiving/pending?limit=15"), api("/api/receiving/recent?limit=15")]);
        if (pend.length !== pending.length || rec.length !== recent.length) renderReceiving();
      }
    };

    $("#scan-go").addEventListener("click", doScan);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); doScan(); }
    });
    document.querySelectorAll("[data-parcel]").forEach((el) =>
      el.addEventListener("click", () => navigate(`/parcels/${el.dataset.parcel}`)));
    document.querySelectorAll("[data-label]").forEach((b) => b.addEventListener("click", () =>
      openPage(`/labels/${b.dataset.label}`)));
    document.querySelectorAll("[data-release]").forEach((b) => b.addEventListener("click", () =>
      releaseModal(recent.find((r) => r.id === parseInt(b.dataset.release, 10)), renderReceiving)));
  } catch (err) {
    $("#root").innerHTML = `<div class="content"><div class="banner err">${esc(err.message)}</div></div>`;
  }
}

/* ------------------------------------------------------------------ warehouse stock */
function cartonChip(row) {
  const expected = row.cartons_expected || 1;
  if (expected <= 1) return '<span class="muted small">1 carton</span>';
  const have = row.cartons_received || 0;
  const cls = have >= expected ? "s-delivered" : have > 0 ? "s-customs" : "s-cancelled";
  return `<span class="chip ${cls}"><span class="dot"></span>${have} / ${expected} cartons</span>`;
}

function releaseModal(row, onDone) {
  modal({
    title: `Release ${row.tracking_number}`,
    submitLabel: "Release from warehouse",
    body: `<p class="small muted">Records that the shipment left the warehouse — who collected it and when.
        The action is reversible: the parcel keeps its full history.</p>
      <div class="field"><label>Released to *</label><input name="released_to" required value="${esc(row.client_name || row.released_to || "")}" autofocus></div>
      <div class="field"><label>Note (optional)</label><input name="note" placeholder="e.g. collected by driver, ID checked"></div>`,
    onSubmit: async (fd) => {
      await api(`/api/receiving/${row.id}/release`, { method: "POST", body: {
        released_to: fd.get("released_to"), note: fd.get("note") } });
      toast(`${row.tracking_number} released`, "ok");
      onDone?.();
    },
  });
}

async function renderStock() {
  loading();
  S.stockFilters = S.stockFilters || { q: "", location: "", include_released: false };
  const f = S.stockFilters;
  const params = new URLSearchParams();
  if (f.q) params.set("q", f.q);
  if (f.location) params.set("location", f.location);
  if (f.include_released) params.set("include_released", "1");
  try {
    const data = await api(`/api/receiving/stock?${params.toString()}`);
    const rows = data.items || [];
    const sum = data.summary || {};
    const staleDays = sum.stale_after_days ?? 7;
    const printable = rows.filter((r) => !r.released_at).map((r) => r.id);
    const content = `
      <div class="grid4" style="margin-bottom:18px">
        <div class="card"><div class="card-body"><div class="muted small">Parcels on the shelves</div><div class="stat">${sum.in_warehouse ?? 0}</div></div></div>
        <div class="card"><div class="card-body"><div class="muted small">Cartons on the shelves</div><div class="stat">${sum.cartons_on_shelf ?? 0}</div></div></div>
        <div class="card"><div class="card-body"><div class="muted small">Ageing &gt; ${staleDays} days</div><div class="stat" style="color:var(--amber)">${sum.stale ?? 0}</div></div></div>
        <div class="card"><div class="card-body"><div class="muted small">Released to date</div><div class="stat">${sum.released_total ?? 0}</div></div></div>
      </div>
      <div class="card" style="margin-bottom:18px"><div class="card-body">
        <div class="row" style="align-items:flex-end">
          <div style="flex:2;min-width:220px"><label>Search</label>
            <input id="stock-q" value="${esc(f.q)}" placeholder="Tracking number, client or reference&hellip;"></div>
          <div style="flex:1;min-width:170px"><label>Storage location</label>
            <select id="stock-loc"><option value="">All locations</option>
              ${(sum.locations || []).map((l) => `<option ${f.location === l ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
          <div style="display:flex;align-items:flex-end;padding-bottom:4px">
            <div class="checkbox"><input type="checkbox" id="stock-released" ${f.include_released ? "checked" : ""}>
              <label for="stock-released" style="margin:0">Include released</label></div></div>
          <a class="btn" href="/api/receiving/stock.xlsx">${icon("download")} Export Excel</a>
          ${printable.length ? `<a class="btn" id="stock-print" target="_blank" rel="noopener"
              href="/labels/print?ids=${printable.join(",")}">${icon("printer")} Print ${printable.length} label(s)</a>` : ""}
        </div>
        <div class="help">Stock is every parcel checked in at the warehouse and not yet released.
          Ageing stock is highlighted after ${staleDays} days.</div>
      </div></div>
      <div class="card"><div class="table-wrap">
        ${rows.length ? `<table><thead><tr><th>Tracking</th><th>Client</th><th>Cartons</th>
            <th>Days on shelf</th><th>Location</th><th>Received</th><th>Released</th><th></th></tr></thead><tbody>
          ${rows.map((r) => `<tr>
            <td class="mono clickable" data-parcel="${r.id}">${esc(r.tracking_number)}
              ${r.client_reference ? `<div class="muted small">${esc(r.client_reference)}</div>` : ""}</td>
            <td class="small">${esc(r.client_name || "—")}</td>
            <td>${cartonChip(r)}</td>
            <td>${r.released_at ? '<span class="muted small">—</span>'
              : r.stale ? `<span class="chip s-exception"><span class="dot"></span>${r.days_on_shelf} days</span>`
                        : `<span class="small">${r.days_on_shelf} days</span>`}</td>
            <td class="small">${esc(r.storage_location || "—")}</td>
            <td class="small muted nowrap">${fmtDate(r.received_at)}${r.received_by ? `<div>${esc(r.received_by)}</div>` : ""}</td>
            <td class="small nowrap">${r.released_at ? `${fmtDate(r.released_at)}<div class="muted">${esc(r.released_to || "")}</div>` : "—"}</td>
            <td class="nowrap">
              <button class="btn sm" data-label="${r.id}">${icon("printer")} Label</button>
              ${r.released_at
                ? `<button class="btn sm" data-unrelease="${r.id}">Undo release</button>`
                : r.complete ? `<button class="btn sm primary" data-release="${r.id}">Release</button>`
                             : `<span class="pill" title="All cartons must arrive before release">awaiting cartons</span>`}
            </td></tr>`).join("")}
        </tbody></table>` : '<div class="empty"><h3>Nothing on the shelves</h3><p>Check parcels in from the Receiving screen and they appear here.</p></div>'}
      </div></div>`;

    shell("/stock", "Warehouse stock", content);
    $("a[href='/api/receiving/stock.xlsx']")?.addEventListener("click", (e) => {
      e.preventDefault(); downloadFile("/api/receiving/stock.xlsx");
    });
    $("#stock-print")?.addEventListener("click", (e) => {
      e.preventDefault();
      openPage(e.currentTarget.getAttribute("href"));
    });
    $("#stock-q").addEventListener("input", (e) => {
      clearTimeout(window.__stockT);
      window.__stockT = setTimeout(() => { f.q = e.target.value.trim(); renderStock(); }, 350);
    });
    $("#stock-loc").addEventListener("change", (e) => { f.location = e.target.value; renderStock(); });
    $("#stock-released").addEventListener("change", (e) => { f.include_released = e.target.checked; renderStock(); });
    document.querySelectorAll("[data-parcel]").forEach((el) =>
      el.addEventListener("click", () => navigate(`/parcels/${el.dataset.parcel}`)));
    document.querySelectorAll("[data-label]").forEach((b) => b.addEventListener("click", () =>
      openPage(`/labels/${b.dataset.label}`)));
    document.querySelectorAll("[data-release]").forEach((b) => b.addEventListener("click", () =>
      releaseModal(rows.find((r) => r.id === parseInt(b.dataset.release, 10)), renderStock)));
    document.querySelectorAll("[data-unrelease]").forEach((b) => b.addEventListener("click", async () => {
      const row = rows.find((r) => r.id === parseInt(b.dataset.unrelease, 10));
      try {
        await api(`/api/receiving/${row.id}/release/undo`, { method: "POST" });
        toast(`${row.tracking_number} is back on the shelf`, "ok");
        renderStock();
      } catch (err) { toast(err.message, "err"); }
    }));
  } catch (err) {
    $("#root").innerHTML = `<div class="content"><div class="banner err">${esc(err.message)}</div></div>`;
  }
}

/* ------------------------------------------------------------------ diagnostics & tests */
const DIAG_GROUP_LABEL = {
  core: "Core", database: "Database & storage", scheduler: "Scheduler", barcode: "Barcode engine",
  carriers: "Carrier connections", alerts: "Email alerts", messaging: "WhatsApp / SMS",
  warehouse: "Warehouse", sla: "Service levels", quota: "Cost efficiency",
};
const DIAG_TIP = {
  pass: '<span class="chip s-delivered"><span class="dot"></span>pass</span>',
  warn: '<span class="chip s-customs"><span class="dot"></span>warn</span>',
  fail: '<span class="chip s-exception"><span class="dot"></span>fail</span>',
};

async function renderDiagnostics(probes) {
  loading();
  const runProbes = probes === undefined ? !!S.diagProbes : probes;
  S.diagProbes = runProbes;
  try {
    const report = await api(`/api/diagnostics?run_probes=${runProbes ? "true" : "false"}`);
    const tone = report.verdict === "healthy" ? "ok-banner"
      : report.verdict === "working with warnings" ? "warn" : "err";
    const groups = {};
    report.checks.forEach((c) => { (groups[c.group] = groups[c.group] || []).push(c); });
    const content = `
      <div class="banner ${tone}" style="margin-bottom:18px"><div class="row" style="justify-content:space-between">
        <div>
          <b style="font-size:1.05rem">${report.verdict === "healthy" ? "All systems go"
            : report.verdict === "working with warnings" ? "Working — review the warnings"
            : "Needs attention"}</b>
          <div class="small">${report.summary.pass} passed · ${report.summary.warn} warning(s) · ${report.summary.fail} failed
            &nbsp;·&nbsp; ${esc(report.app.name)} ${esc(report.app.version)}${report.app.demo_mode ? " (demo mode)" : ""}
            &nbsp;·&nbsp; checked ${fmtDate(report.generated_at)}</div>
        </div>
        <div class="row">
          <div class="checkbox" style="margin:0"><input type="checkbox" id="diag-probes" ${runProbes ? "checked" : ""}>
            <label for="diag-probes" style="margin:0">Ping live carrier APIs</label></div>
          <button class="btn primary" id="diag-run">${icon("refresh")} Re-run checks</button>
        </div></div></div>
      ${Object.entries(groups).map(([group, checks]) => `
        <div class="card" style="margin-bottom:16px">
          <div class="card-head"><h2>${esc(DIAG_GROUP_LABEL[group] || group)}</h2></div>
          <div class="table-wrap"><table><thead><tr><th style="width:34%">Check</th>
            <th style="width:12%">Result</th><th>Detail</th></tr></thead>
          <tbody>${checks.map((c) => `<tr>
            <td class="small"><b>${esc(c.name)}</b></td>
            <td>${DIAG_TIP[c.status] || esc(c.status)}</td>
            <td class="small muted">${esc(c.detail || "")}</td></tr>`).join("")}</tbody></table></div>
        </div>`).join("")}
      <div class="card"><div class="card-head"><h2>Automated test suites</h2></div><div class="card-body">
        <p class="small muted">The same checks also run from a terminal — useful after an upgrade, before switching
          on live carrier APIs, or when you move the app to another server. Both suites use their own throwaway
          database, so they never touch your live data.</p>
        <div class="code">python tests/test_all_features.py    # 62 checks: barcodes, labels, portal, stock, cartons, sync
python tests/smoke_test.py           # 41 checks: logins, parcels, alerts, carriers, labels</div>
        <p class="small muted" style="margin-top:10px">Run them from the folder that contains <span class="mono">run.py</span>
          (on Windows: <span class="mono">py tests\\test_all_features.py</span>).</p>
      </div></div>`;
    shell("/diagnostics", "Diagnostics &amp; self-test", content);
    $("#diag-run").addEventListener("click", () => renderDiagnostics($("#diag-probes").checked));
  } catch (err) {
    $("#root").innerHTML = `<div class="content"><div class="banner err">${esc(err.message)}</div></div>`;
  }
}

/* ------------------------------------------------------------------ client portal (password login) */
function portalShell(inner) {
  return `<div class="public-shell" style="max-width:1000px">
    <div class="public-head">
      <div class="brand-logo">PD</div>
      <div><div style="font-weight:700;font-size:1.1rem">Client portal</div>
      <div class="muted small">${esc(S.settings.company_name || "Shipment tracking")}</div></div>
    </div>${inner}
    <p class="muted small" style="text-align:center;margin-top:20px">
      Shipment status, cartons and warehouse releases — updated automatically.
      Team member? <a href="/login">Sign in to the control tower</a>.</p></div>`;
}

async function renderClientPortalLogin(error = "") {
  loading();
  if (S.clientToken) {
    try { return await renderClientPortal(); }
    catch { S.clientToken = ""; S.client = null; store.removeItem("pd_client_token"); }
  }
  if (!Object.keys(S.settings || {}).length) { try { await loadRefData(); } catch { /* offline ok */ } }
  $("#root").innerHTML = portalShell(`
    <div class="card"><div class="card-body" style="max-width:430px;margin:0 auto">
      ${error ? `<div class="banner err">${esc(error)}</div>` : ""}
      <h2 style="margin:0 0 6px">Your shipments</h2>
      <p class="small muted">Sign in with the email address your forwarder registered for you.</p>
      <div class="field"><label>Email</label><input id="cp-email" type="email" autocomplete="username" autofocus></div>
      <div class="field"><label>Password</label><input id="cp-pass" type="password" autocomplete="current-password"></div>
      <button class="btn primary" id="cp-go" style="width:100%">Sign in</button>
      <div class="small muted" style="margin-top:10px">Forgot your password? Ask your forwarder to reset it from
        the Clients screen.</div>
    </div></div>`);
  const submit = async () => {
    const btn = $("#cp-go");
    const email = $("#cp-email").value.trim();
    const password = $("#cp-pass").value;
    if (!email || !password) { toast("Enter your email and password", "err"); return; }
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Signing in…';
    try {
      const r = await api("/api/portal/login", { method: "POST", token: "", body: { email, password } });
      S.clientToken = r.token; S.client = r.client;
      store.setItem("pd_client_token", r.token);
      setPath("/portal", true);
      renderClientPortal();
    } catch (err) { renderClientPortalLogin(err.message); }
  };
  $("#cp-go").addEventListener("click", submit);
  $("#cp-pass").addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  $("#cp-email").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#cp-pass").focus(); });
}

async function renderClientPortal() {
  loading();
  if (!Object.keys(S.settings || {}).length) { try { await loadRefData(); } catch { /* offline ok */ } }
  const [me, list] = await Promise.all([api("/api/portal/me"), api("/api/portal/parcels")]);
  const parcels = list.parcels || [];
  S.client = me.client;
  const content = `
    <div class="card" style="margin-bottom:16px"><div class="card-body">
      <div class="row" style="justify-content:space-between">
        <div>
          <h2 style="margin:0">${esc(me.client.name)}</h2>
          <div class="small muted">${me.open_count} shipment(s) in progress · ${me.total} total
            ${me.client.email ? " · " + esc(me.client.email) : ""}</div>
        </div>
        <div class="row">
          <button class="btn sm" id="cp-pw">${icon("key")} Change password</button>
          <button class="btn sm" id="cp-out">${icon("logout")} Sign out</button>
        </div>
      </div>
    </div></div>
    <div class="card"><div class="table-wrap">
      ${parcels.length ? `<table><thead><tr><th>Tracking</th><th>Carrier</th><th>Description</th><th>Status</th>
        <th>Warehouse</th><th>ETA</th><th>Last update</th></tr></thead><tbody>
        ${parcels.map((p) => `<tr>
          <td class="mono">${esc(p.tracking_number)}${p.client_reference ? `<div class="muted small">${esc(p.client_reference)}</div>` : ""}</td>
          <td>${carrierCell(p.carrier)}</td>
          <td class="small truncate">${esc(p.description || "—")}</td>
          <td>${statusChip(p.status)}${p.cartons_expected > 1 ? `<div class="small muted">${p.cartons_received || 0} / ${p.cartons_expected} cartons</div>` : ""}</td>
          <td class="small">${p.released_at
            ? `<span class="chip s-delivered"><span class="dot"></span>released</span>`
            : p.storage_location ? `On shelf · ${esc(p.storage_location)}` : "—"}</td>
          <td class="small nowrap">${p.eta || "—"}</td>
          <td class="small muted nowrap">${p.events && p.events.length ? fmtDate(p.events[0].occurred_at) : "—"}</td>
        </tr>`).join("")}</tbody></table>`
        : '<div class="empty"><h3>No shipments yet</h3><p>Shipments appear here as soon as your forwarder books them.</p></div>'}
    </div></div>`;
  $("#root").innerHTML = portalShell(content);

  $("#cp-out").addEventListener("click", () => {
    S.clientToken = ""; S.client = null; store.removeItem("pd_client_token");
    renderClientPortalLogin();
  });
  $("#cp-pw").addEventListener("click", () => modal({
    title: "Change your password", submitLabel: "Save new password",
    body: `<div class="field"><label>Current password</label><input name="current_password" type="password" required></div>
           <div class="field"><label>New password (at least 6 characters)</label><input name="new_password" type="password" minlength="6" required></div>`,
    onSubmit: async (fd) => {
      await api("/api/portal/change-password", { method: "POST", body: {
        current_password: fd.get("current_password"), new_password: fd.get("new_password") } });
      toast("Password changed — please sign in again", "ok");
      S.clientToken = ""; S.client = null; store.removeItem("pd_client_token");
      setTimeout(renderClientPortalLogin, 700);
    },
  }));
}

/* ------------------------------------------------------------------ public pages */
async function renderTrack(token) {
  loading();
  try {
    const p = await api(`/api/public/track/${token}`);
    $("#root").innerHTML = `
    <div class="public-shell">
      <div class="public-head">
        <div class="brand-logo">PD</div>
        <div><div style="font-weight:700;font-size:1.1rem">Shipment tracking</div>
        <div class="muted small">${esc(p.company_name || S.settings.company_name || "")}</div></div>
      </div>
      <div class="card" style="margin-bottom:18px"><div class="card-body">
        <div class="row" style="justify-content:space-between;align-items:flex-start">
          <div>
            <div class="tag">${esc(CARRIER_LABEL[p.carrier] || p.carrier)}</div>
            <h1 class="mono" style="font-size:1.5rem;margin:4px 0 10px">${esc(p.tracking_number)}</h1>
            ${statusChip(p.status)}
            <div class="muted small" style="margin-top:8px">${esc(p.status_text || "")}</div>
          </div>
          <div style="text-align:right" class="small">
            ${p.eta ? `<div><span class="muted">Estimated delivery</span><br><b>${fmtDate(p.eta, false)}</b></div>` : ""}
            ${p.delivered_at ? `<div style="margin-top:8px"><span class="muted">Delivered</span><br><b>${fmtDate(p.delivered_at, false)}</b></div>` : ""}
          </div>
        </div>
      </div></div>
      <div class="card"><div class="card-head"><h2>History</h2></div><div class="card-body">
        <ul class="timeline">${p.events.map((e, i) => `<li class="${i === 0 ? "now" : ""}">
          <div class="t-title">${esc(e.status_text || STATUS_LABEL[e.status] || e.status)}</div>
          <div class="t-meta">${fmtDate(e.occurred_at)}${e.location ? " · " + esc(e.location) : ""}</div>
        </li>`).join("")}</ul>
      </div></div>
      <p class="muted small" style="text-align:center;margin-top:20px">
        This page updates in real time from the carrier network.
        ${p.tracking_url ? ` Also <a href="${esc(p.tracking_url)}" target="_blank" rel="noopener">track on the carrier site</a>.` : ""}
      </p>
    </div>`;
  } catch (err) {
    $("#root").innerHTML = `<div class="public-shell"><div class="banner err">${esc(err.message)}</div>
      <p class="muted small">Ask your forwarder for a new tracking link.</p></div>`;
  }
}

async function renderPortal(token) {
  loading();
  try {
    const data = await api(`/api/public/client/${token}`);
    const open = data.parcels.filter((p) => p.status !== "delivered");
    $("#root").innerHTML = `
    <div class="public-shell" style="max-width:1120px">
      <div class="public-head">
        <div class="brand-logo">PD</div>
        <div><div style="font-weight:700;font-size:1.1rem">${esc(data.client.name)} — shipments</div>
        <div class="muted small">${esc(data.company_name || S.settings.company_name || "")} · ${data.open_count} parcel(s) in progress</div></div>
      </div>
      <div class="card"><div class="table-wrap">
        ${data.parcels.length ? `<table><thead><tr><th>Tracking</th><th>Carrier</th><th>Description</th><th>Status</th><th>ETA</th><th>Last update</th></tr></thead><tbody>
          ${data.parcels.map((p) => `<tr>
            <td class="mono">${esc(p.tracking_number)}${p.client_reference ? `<div class="muted small">${esc(p.client_reference)}</div>` : ""}</td>
            <td>${carrierCell(p.carrier)}</td>
            <td class="small truncate">${esc(p.description || "—")}</td>
            <td>${statusChip(p.status)}</td>
            <td class="small nowrap">${p.eta || "—"}</td>
            <td class="small muted nowrap">${p.events.length ? fmtDate(p.events[0].occurred_at) : "—"}</td>
          </tr>`).join("")}
        </tbody></table>` : '<div class="empty"><h3>No shipments yet</h3></div>'}
      </div></div>
      <p class="muted small" style="text-align:center;margin-top:20px">Live status, updated automatically. Contact your forwarder for details.</p>
    </div>`;
  } catch (err) {
    $("#root").innerHTML = `<div class="public-shell"><div class="banner err">${esc(err.message)}</div></div>`;
  }
}

/* ------------------------------------------------------------------ boot */
(async function boot() {
  if (currentPath() === "/portal") { setPath("/portal", true); router(); return; }
  if (S.token) {
    try {
      S.user = await api("/api/auth/me");
      await loadRefData();
    } catch { S.token = ""; store.removeItem("pd_token"); S.user = null; }
  }
  router();
})();
