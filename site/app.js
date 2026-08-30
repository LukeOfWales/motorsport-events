"use strict";

// Pure client-side SPA: loads events.json once, does all filtering, distance
// ranking, search, and rendering in the browser. Postcode geocoding calls
// postcodes.io directly (keyless, CORS-friendly).

const state = {
  data: null,            // parsed events.json
  events: [],            // all events (with computed distance)
  activeDisciplines: new Set(),
  activeSources: new Set(),
  radius: "150",
  postcode: "",
  origin: null,          // {lat, lon} used for distance
  search: "",
  weekend: false,
  savedOnly: false,
  smartRadius: false,
  view: "list",
  monthCursor: null,
  map: null,             // live Leaflet map instance (destroyed between renders)
};

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DOW = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const DISCIPLINE_LABELS = {
  trials: "Trials / RTV", rally: "Rally", hillclimb: "Hill Climb",
  off_road: "Off-Road", other: "Other",
};
const SOURCE_LABELS = {
  awdc: "AWDC", alrc: "ALRC", swlrc: "SWLRC", hillclimb_uk: "hillclimb.uk",
  msuk: "Motorsport UK", msv: "MSV", pembrey: "Pembrey",
};
function disciplineLabel(v) { return DISCIPLINE_LABELS[v] || v; }
function sourceLabel(v) { return SOURCE_LABELS[v] || v; }

// --- URL state (deep-linkable filters/view/postcode) --------------------
// Reflect the current filters in the query string so views are bookmarkable
// and shareable, and restore them on load.
function syncUrl() {
  const p = new URLSearchParams();
  if (state.view !== "list") p.set("view", state.view);
  if (state.postcode) p.set("pc", state.postcode);
  if (state.smartRadius) p.set("smart", "1");
  else if (state.radius && String(state.radius) !== String(state.data.default_radius_km))
    p.set("radius", state.radius);
  if (state.search) p.set("q", state.search);
  if (state.weekend) p.set("weekend", "1");
  if (state.savedOnly) p.set("saved", "1");
  if (state.activeDisciplines.size) p.set("disc", [...state.activeDisciplines].join(","));
  if (state.activeSources.size) p.set("src", [...state.activeSources].join(","));
  const qs = p.toString();
  const url = qs ? `?${qs}` : location.pathname;
  history.replaceState(null, "", url);
}

function readUrl() {
  const p = new URLSearchParams(location.search);
  if (p.get("view")) state.view = p.get("view");
  if (p.get("pc")) state.postcode = normalisePostcode(p.get("pc"));
  if (p.get("smart") === "1") state.smartRadius = true;
  if (p.get("radius")) state.radius = p.get("radius");
  if (p.get("q")) state.search = p.get("q");
  if (p.get("weekend") === "1") state.weekend = true;
  if (p.get("saved") === "1") state.savedOnly = true;
  if (p.get("disc")) state.activeDisciplines = new Set(p.get("disc").split(",").filter(Boolean));
  if (p.get("src")) state.activeSources = new Set(p.get("src").split(",").filter(Boolean));
}

// --- saved events -------------------------------------------------------
const SAVED_KEY = "mse.saved";
let savedIds = (() => {
  try { return new Set(JSON.parse(localStorage.getItem(SAVED_KEY) || "[]")); }
  catch { return new Set(); }
})();
function eventKey(ev) { return `${ev.source}:${ev.source_id}`; }
function isSaved(ev) { return savedIds.has(eventKey(ev)); }
function toggleSaved(ev) {
  const k = eventKey(ev);
  if (savedIds.has(k)) savedIds.delete(k); else savedIds.add(k);
  localStorage.setItem(SAVED_KEY, JSON.stringify([...savedIds]));
}

// --- helpers ------------------------------------------------------------
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}
function isoDate(d) {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}
function fmtDateRange(startISO, endISO) {
  const s = new Date(startISO + "T00:00:00");
  if (!endISO) return s.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const e = new Date(endISO + "T00:00:00");
  return `${s.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} \u2013 ${e.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
}

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371, rad = Math.PI / 180;
  const dphi = (lat2 - lat1) * rad, dl = (lon2 - lon1) * rad;
  const a = Math.sin(dphi/2)**2 +
    Math.cos(lat1*rad) * Math.cos(lat2*rad) * Math.sin(dl/2)**2;
  return Math.round(2 * R * Math.asin(Math.sqrt(a)) * 10) / 10;
}

function normalisePostcode(pc) {
  pc = pc.replace(/\s+/g, "").toUpperCase();
  return pc.length > 3 ? pc.slice(0, -3) + " " + pc.slice(-3) : pc;
}

async function geocode(pc) {
  const compact = pc.replace(/\s+/g, "");
  // Full postcode, then outcode fallback.
  try {
    let r = await fetch(`https://api.postcodes.io/postcodes/${encodeURIComponent(compact)}`);
    if (r.ok) {
      const j = await r.json();
      if (j.result) return { lat: j.result.latitude, lon: j.result.longitude };
    }
  } catch (_) {}
  const outcode = (compact.match(/^[A-Z]{1,2}\d[A-Z\d]?/) || [compact])[0];
  try {
    let r = await fetch(`https://api.postcodes.io/outcodes/${encodeURIComponent(outcode)}`);
    if (r.ok) {
      const j = await r.json();
      if (j.result) return { lat: j.result.latitude, lon: j.result.longitude };
    }
  } catch (_) {}
  return null;
}

// --- distance + filtering ----------------------------------------------
function applyDistances() {
  const o = state.origin;
  for (const ev of state.events) {
    ev.distance_km = (o && ev.latitude != null && ev.longitude != null)
      ? haversineKm(o.lat, o.lon, ev.latitude, ev.longitude)
      : null;
  }
}

function spansWeekend(ev) {
  const s = new Date(ev.start_date + "T00:00:00");
  const e = ev.end_date ? new Date(ev.end_date + "T00:00:00") : s;
  for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
    if (d.getDay() === 0 || d.getDay() === 6) return true;
  }
  return false;
}

function visibleEvents() {
  const today = isoDate(new Date());
  let evs = state.events;

  // Month view shows the whole displayed month (past or future); otherwise
  // only upcoming.
  if (state.view === "month" && state.monthCursor) {
    const y = state.monthCursor.getFullYear(), m = state.monthCursor.getMonth();
    const from = isoDate(new Date(y, m, 1)), to = isoDate(new Date(y, m + 1, 0));
    evs = evs.filter((e) => (e.end_date || e.start_date) >= from && e.start_date <= to);
  } else {
    evs = evs.filter((e) => (e.end_date || e.start_date) >= today);
  }

  if (state.activeDisciplines.size)
    evs = evs.filter((e) => state.activeDisciplines.has(e.discipline));
  if (state.activeSources.size)
    evs = evs.filter((e) => state.activeSources.has(e.source));
  if (state.search) {
    const q = state.search.toLowerCase();
    evs = evs.filter((e) =>
      e.title.toLowerCase().includes(q) ||
      (e.venue || "").toLowerCase().includes(q) ||
      (e.organiser || "").toLowerCase().includes(q));
  }
  if (state.weekend) evs = evs.filter(spansWeekend);
  if (state.savedOnly) evs = evs.filter(isSaved);

  // Distance filtering.
  if (state.smartRadius) {
    const limits = state.data.discipline_radius_km || {};
    evs = evs.filter((e) => {
      const lim = limits[e.discipline];
      if (lim == null) return true;
      return e.distance_km != null && e.distance_km <= lim;
    });
  } else if (state.radius) {
    const lim = Number(state.radius);
    evs = evs.filter((e) => e.distance_km != null && e.distance_km <= lim);
  }

  // Sort by date then distance.
  evs = evs.slice().sort((a, b) => {
    if (a.start_date !== b.start_date) return a.start_date < b.start_date ? -1 : 1;
    const da = a.distance_km == null ? 1e9 : a.distance_km;
    const db = b.distance_km == null ? 1e9 : b.distance_km;
    return da - db;
  });
  return evs;
}

// --- event card / detail ------------------------------------------------
function eventCard(ev) {
  const d = new Date(ev.start_date + "T00:00:00");
  const dist = ev.distance_km != null ? `${Math.round(ev.distance_km)} km` : "location TBC";
  const loc = ev.venue || "";
  const sources = sourceLabel(ev.source) +
    (ev.alt_sources && ev.alt_sources.length
      ? " \u00b7 also on " + ev.alt_sources.map(sourceLabel).join(", ") : "");
  const card = document.createElement("div");
  card.className = "event";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.innerHTML = `
    <div class="event-date">
      <div class="day">${d.getDate()}</div>
      <div class="mon">${MONTHS[d.getMonth()]}</div>
    </div>
    <div class="event-body">
      <p class="event-title">${ev.is_new ? '<span class="new-badge">NEW</span> ' : ""}${escapeHtml(ev.title)}</p>
      <div class="event-meta">
        <span class="badge ${ev.discipline}">${disciplineLabel(ev.discipline)}</span>
        ${loc ? `<span>${escapeHtml(loc)}</span>` : ""}
        <span class="dist">${dist}</span>
        ${ev.end_date ? `<span>${fmtDateRange(ev.start_date, ev.end_date)}</span>` : ""}
        <span class="source">${escapeHtml(sources)}</span>
      </div>
    </div>
    <button class="star ${isSaved(ev) ? "on" : ""}" title="Save" aria-label="Save event">★</button>`;
  card.querySelector(".star").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleSaved(ev);
    e.target.classList.toggle("on");
    if (state.savedOnly) render();
  });
  const open = () => openDetail(ev);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return card;
}

function openDetail(ev) {
  const modal = document.getElementById("modal");
  document.getElementById("modal-title").textContent = ev.title;
  const loc = [ev.venue, ev.postcode].filter(Boolean).join(", ");
  const dest = ev.postcode || (ev.latitude != null ? `${ev.latitude},${ev.longitude}` : null);
  const mapsUrl = dest ? `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(dest)}` : null;
  const rows = [`<span class="badge ${ev.discipline}">${disciplineLabel(ev.discipline)}</span>`,
    `<p><strong>When:</strong> ${fmtDateRange(ev.start_date, ev.end_date)}</p>`];
  if (loc) rows.push(`<p><strong>Where:</strong> ${escapeHtml(loc)}</p>`);
  if (ev.distance_km != null) rows.push(`<p><strong>Distance:</strong> ${Math.round(ev.distance_km)} km</p>`);
  if (ev.organiser) rows.push(`<p><strong>Organiser:</strong> ${escapeHtml(ev.organiser)}</p>`);
  const srcLine = sourceLabel(ev.source) +
    (ev.alt_sources && ev.alt_sources.length ? " (also on " + ev.alt_sources.map(sourceLabel).join(", ") + ")" : "");
  rows.push(`<p><strong>Source:</strong> ${escapeHtml(srcLine)}</p>`);
  if (ev.description) rows.push(`<p class="detail-desc">${escapeHtml(ev.description)}</p>`);

  const actions = [];
  if (ev.url) actions.push(`<a class="btn" href="${escapeHtml(ev.url)}" target="_blank" rel="noopener">Event page \u2197</a>`);
  if (mapsUrl) actions.push(`<a class="btn" href="${mapsUrl}" target="_blank" rel="noopener">Directions \u2197</a>`);
  actions.push(`<a class="btn" id="modal-ics" href="#">Add to calendar</a>`);
  const saved = isSaved(ev);
  actions.push(`<button class="btn btn-save ${saved ? "on" : ""}" id="modal-save">${saved ? "★ Saved" : "☆ Save"}</button>`);

  document.getElementById("modal-body").innerHTML =
    rows.join("") + `<div class="modal-actions">${actions.join("")}</div>`;
  document.getElementById("modal-save").addEventListener("click", (e) => {
    toggleSaved(ev);
    const on = isSaved(ev);
    e.target.classList.toggle("on", on);
    e.target.textContent = on ? "★ Saved" : "☆ Save";
    if (state.savedOnly) { closeModal(); render(); }
  });
  document.getElementById("modal-ics").addEventListener("click", (e) => {
    e.preventDefault();
    downloadICS(ev);
  });
  modal.hidden = false;
}
function closeModal() { document.getElementById("modal").hidden = true; }

// --- ICS (built client-side) --------------------------------------------
function icsDate(iso, addDays = 0) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + addDays);
  return isoDate(d).replace(/-/g, "");
}
function icsEscape(s) { return String(s).replace(/([,;\\])/g, "\\$1").replace(/\n/g, "\\n"); }
function buildICS(events, name) {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//motorsport-events//EN",
    "CALSCALE:GREGORIAN", "METHOD:PUBLISH", `X-WR-CALNAME:${icsEscape(name)}`];
  for (const ev of events) {
    const endEx = icsDate(ev.end_date || ev.start_date, 1);
    lines.push("BEGIN:VEVENT", `UID:${ev.source}:${ev.source_id}@motorsport-events`,
      `DTSTAMP:${icsDate(isoDate(new Date()))}T000000Z`,
      `DTSTART;VALUE=DATE:${icsDate(ev.start_date)}`,
      `DTEND;VALUE=DATE:${endEx}`, `SUMMARY:${icsEscape(ev.title)}`);
    const loc = [ev.venue, ev.postcode].filter(Boolean).join(", ");
    if (loc) lines.push(`LOCATION:${icsEscape(loc)}`);
    if (ev.url) lines.push(`URL:${icsEscape(ev.url)}`);
    lines.push("END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n") + "\r\n";
}
function downloadICS(ev) {
  const blob = new Blob([buildICS([ev], ev.title)], { type: "text/calendar" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${ev.source}-${ev.source_id}.ics`.replace(/[^a-z0-9.\-]/gi, "-");
  a.click();
  URL.revokeObjectURL(a.href);
}

// --- views --------------------------------------------------------------
function render() {
  const events = visibleEvents();
  // Leaving map view: destroy the live map so it doesn't leak.
  if (state.view !== "map") destroyMap();
  if (state.view === "month") renderMonth(events);
  else if (state.view === "map") renderMap(events);
  else renderList(events);
  renderResultCount(events);
  renderSummary();
  syncUrl();
}

function renderResultCount(events) {
  const el = document.getElementById("result-count");
  if (!el) return;
  const n = events.length;
  el.textContent = n === 1 ? "1 event" : `${n} events`;
}

function emptyMsg() {
  if (state.savedOnly) return `<p class="empty-msg">No saved events match your filters.</p>`;
  const hints = [];
  if (state.radius && !state.smartRadius) hints.push("widening the distance");
  if (state.search) hints.push("clearing the search");
  if (state.activeSources.size) hints.push("removing the source filter");
  if (state.activeDisciplines.size) hints.push("removing a discipline filter");
  if (state.weekend) hints.push("turning off weekends-only");
  const tip = hints.length ? `Try ${hints.slice(0, 2).join(" or ")}.` : "Try broadening your filters.";
  return `<p class="empty-msg">No events match your filters.<br>${tip}</p>`;
}

function renderList(events) {
  const content = document.getElementById("content");
  content.innerHTML = "";
  if (!events.length) { content.innerHTML = emptyMsg(); return; }
  let key = null;
  for (const ev of events) {
    const d = new Date(ev.start_date + "T00:00:00");
    const k = `${d.getFullYear()}-${d.getMonth()}`;
    if (k !== key) {
      key = k;
      const h = document.createElement("div");
      h.className = "date-header";
      h.textContent = d.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
      content.appendChild(h);
    }
    content.appendChild(eventCard(ev));
  }
}

function renderMonth(events) {
  const content = document.getElementById("content");
  content.innerHTML = "";
  if (!state.monthCursor) {
    const n = new Date();
    state.monthCursor = new Date(n.getFullYear(), n.getMonth(), 1);
  }
  const year = state.monthCursor.getFullYear(), month = state.monthCursor.getMonth();

  const nav = document.createElement("div");
  nav.className = "month-nav";
  const mk = (txt, title, fn, cls) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = txt; b.title = title || "";
    if (cls) b.className = cls;
    b.addEventListener("click", fn);
    return b;
  };
  const label = document.createElement("h2");
  label.className = "month-title";
  label.textContent = state.monthCursor.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  nav.append(mk("\u2039", "Previous month", () => shiftMonth(-1)), label,
    mk("\u203a", "Next month", () => shiftMonth(1)),
    mk("Today", "", goToToday, "month-today"));
  content.appendChild(nav);

  const byDay = {};
  const lastDay = new Date(year, month + 1, 0).getDate();
  for (const ev of events) {
    const s = new Date(ev.start_date + "T00:00:00");
    const e = ev.end_date ? new Date(ev.end_date + "T00:00:00") : s;
    for (let day = 1; day <= lastDay; day++) {
      const cell = new Date(year, month, day);
      if (cell >= new Date(s.getFullYear(), s.getMonth(), s.getDate()) &&
          cell <= new Date(e.getFullYear(), e.getMonth(), e.getDate()))
        (byDay[day] ||= []).push(ev);
    }
  }

  const grid = document.createElement("div");
  grid.className = "month-grid";
  for (const dow of DOW) {
    const el = document.createElement("div"); el.className = "dow"; el.textContent = dow;
    grid.appendChild(el);
  }
  let lead = (new Date(year, month, 1).getDay() + 6) % 7;
  for (let i = 0; i < lead; i++) {
    const c = document.createElement("div"); c.className = "cell empty"; grid.appendChild(c);
  }
  const today = new Date();
  for (let day = 1; day <= lastDay; day++) {
    const c = document.createElement("div");
    c.className = "cell";
    if (year === today.getFullYear() && month === today.getMonth() && day === today.getDate())
      c.classList.add("is-today");
    c.innerHTML = `<span class="num">${day}</span>`;
    for (const ev of byDay[day] || []) {
      const s = document.createElement("span");
      s.className = `ev disc-${ev.discipline}`;
      s.textContent = ev.title; s.title = ev.title;
      s.addEventListener("click", () => openDetail(ev));
      c.appendChild(s);
    }
    grid.appendChild(c);
  }
  content.appendChild(grid);
  if (!events.length) {
    const p = document.createElement("p");
    p.className = "empty-msg"; p.textContent = "No events this month match your filters.";
    content.appendChild(p);
  }
}

// --- Leaflet: loaded lazily only when the map view is first used ----------
let _leafletPromise = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (_leafletPromise) return _leafletPromise;
  _leafletPromise = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    css.integrity = "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=";
    css.crossOrigin = "";
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    js.integrity = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
    js.crossOrigin = "";
    js.onload = () => resolve();
    js.onerror = () => reject(new Error("Failed to load the map library."));
    document.head.appendChild(js);
  });
  return _leafletPromise;
}

// Tear down any live map before we replace #content, to avoid Leaflet leaks
// and "container already initialized" errors.
function destroyMap() {
  if (state.map) {
    state.map.remove();
    state.map = null;
  }
}

function renderMap(events) {
  const content = document.getElementById("content");
  content.innerHTML = `<div id="map"></div>`;
  const located = events.filter((e) => e.latitude != null && e.longitude != null);

  loadLeaflet().then(() => {
    // The user may have navigated away while Leaflet loaded.
    if (state.view !== "map") return;
    destroyMap();
    const map = L.map(document.getElementById("map"));
    state.map = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    const markers = [];
    for (const ev of located) {
      const m = L.marker([ev.latitude, ev.longitude]);
      const dist = ev.distance_km != null ? ` \u00b7 ${Math.round(ev.distance_km)} km` : "";
      m.bindPopup(`<strong>${escapeHtml(ev.title)}</strong><br>${fmtDateRange(ev.start_date, ev.end_date)}${dist}<br><a href="#" class="popup-more">details</a>`);
      m.on("popupopen", (e) => {
        const link = e.popup.getElement().querySelector(".popup-more");
        if (link) link.addEventListener("click", (ev2) => { ev2.preventDefault(); openDetail(ev); });
      });
      m.addTo(map); markers.push(m);
    }
    if (state.origin) {
      L.circleMarker([state.origin.lat, state.origin.lon],
        { radius: 7, color: "#ff5a1f", fillOpacity: 0.9 }).bindPopup("You are here").addTo(map);
    }
    if (markers.length) map.fitBounds(L.featureGroup(markers).getBounds().pad(0.2));
    else if (state.origin) map.setView([state.origin.lat, state.origin.lon], 9);
    else map.setView([52.5, -3.5], 6);
    setTimeout(() => map.invalidateSize(), 100);
    if (!located.length) {
      const p = document.createElement("p");
      p.className = "empty-msg"; p.textContent = "No mappable events match your filters.";
      content.appendChild(p);
    }
  }).catch((err) => {
    content.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  });
}

function shiftMonth(delta) {
  const c = state.monthCursor || new Date();
  state.monthCursor = new Date(c.getFullYear(), c.getMonth() + delta, 1);
  render();
}
function goToToday() {
  const n = new Date();
  state.monthCursor = new Date(n.getFullYear(), n.getMonth(), 1);
  render();
}

function renderSummary() {
  const today = isoDate(new Date());
  const horizon = new Date(); horizon.setDate(horizon.getDate() + 30);
  const to = isoDate(horizon);
  const upcoming = state.events.filter((e) =>
    (e.end_date || e.start_date) >= today && e.start_date <= to);
  const sec = document.getElementById("summary");
  sec.hidden = false;
  document.getElementById("summary-total").innerHTML =
    `<strong>${upcoming.length}</strong> events in the next 30 days`;
  let nearest = null;
  for (const e of upcoming)
    if (e.distance_km != null && (!nearest || e.distance_km < nearest.distance_km)) nearest = e;
  document.getElementById("summary-nearest").innerHTML = nearest
    ? `Nearest: <strong>${escapeHtml(nearest.title)}</strong> \u00b7 ${Math.round(nearest.distance_km)} km`
    : "Set your postcode to see distances";
}

// --- chips --------------------------------------------------------------
function chipRow(boxId, items, activeSet, labelFn) {
  const box = document.getElementById(boxId);
  box.innerHTML = "";
  for (const v of items) {
    const active = activeSet.has(v);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip" + (active ? " active" : "");
    chip.textContent = labelFn(v);
    chip.setAttribute("aria-pressed", active ? "true" : "false");
    chip.addEventListener("click", () => {
      if (activeSet.has(v)) activeSet.delete(v); else activeSet.add(v);
      chipRow(boxId, items, activeSet, labelFn);
      render();
    });
    box.appendChild(chip);
  }
}

// --- postcode -----------------------------------------------------------
const POSTCODE_KEY = "mse.postcode";
async function applyPostcode(raw) {
  const status = document.getElementById("postcode-status");
  const pc = (raw || "").trim();
  if (!pc) {
    state.postcode = "";
    state.origin = { lat: state.data.home.lat, lon: state.data.home.lon };
    localStorage.removeItem(POSTCODE_KEY);
    status.textContent = `Using default (${state.data.home.postcode})`;
    status.classList.remove("error");
    setHomeLabel(); applyDistances(); render();
    return;
  }
  status.textContent = "Locating\u2026"; status.classList.remove("error");
  const coords = await geocode(pc);
  if (!coords) {
    status.textContent = `Couldn't find "${pc}"`; status.classList.add("error");
    return;
  }
  state.postcode = normalisePostcode(pc);
  state.origin = coords;
  localStorage.setItem(POSTCODE_KEY, state.postcode);
  status.textContent = `Showing distances from ${state.postcode}`;
  status.classList.remove("error");
  setHomeLabel(); applyDistances(); render();
}
function setHomeLabel() {
  document.getElementById("home-label").textContent =
    `near ${state.postcode || state.data.home.postcode}`;
}

// --- health -------------------------------------------------------------
function showHealth() {
  document.getElementById("modal-title").textContent = "Source status";
  const rows = (state.data.sources || []).map((s) => {
    const cls = s.ok ? "ok" : "bad";
    return `<tr><td>${escapeHtml(sourceLabel(s.source))}</td>` +
      `<td class="${cls}">${s.ok ? "OK" : "FAILED"}</td><td>${s.event_count}</td></tr>` +
      (s.error ? `<tr><td colspan="3" class="bad small">${escapeHtml(s.error)}</td></tr>` : "");
  }).join("");
  document.getElementById("modal-body").innerHTML =
    `<p>${state.data.count} events, generated ${new Date(state.data.generated_at).toLocaleString("en-GB")}.</p>` +
    `<table class="health"><thead><tr><th>Source</th><th>Status</th><th>Events</th></tr></thead><tbody>${rows}</tbody></table>`;
  document.getElementById("modal").hidden = false;
}

// --- init ---------------------------------------------------------------
async function init() {
  const resp = await fetch("./events.json");
  if (!resp.ok) throw new Error(`Couldn't load event data (${resp.status})`);
  state.data = await resp.json();
  state.events = state.data.events;

  document.getElementById("generated").textContent =
    "updated " + new Date(state.data.generated_at).toLocaleDateString("en-GB");
  document.getElementById("radius").value = String(state.data.default_radius_km);
  state.radius = String(state.data.default_radius_km);

  // Restore state from the URL (deep links) before building the UI.
  readUrl();

  // Disciplines/sources present in the data.
  const disciplines = [...new Set(state.events.map((e) => e.discipline))]
    .sort((a, b) => disciplineLabel(a).localeCompare(disciplineLabel(b)));
  const sources = (state.data.sources || []).filter((s) => s.event_count > 0).map((s) => s.source);
  chipRow("disciplines", disciplines, state.activeDisciplines, disciplineLabel);
  chipRow("sources", sources, state.activeSources, sourceLabel);

  // Reflect restored control state in the widgets.
  document.getElementById("view").value = state.view;
  document.getElementById("radius").value = state.radius;
  document.getElementById("radius").disabled = state.smartRadius;
  document.getElementById("search").value = state.search;
  document.getElementById("toggle-weekend").classList.toggle("active", state.weekend);
  document.getElementById("toggle-saved").classList.toggle("active", state.savedOnly);
  document.getElementById("toggle-smart").classList.toggle("active", state.smartRadius);

  // Restore postcode: URL takes priority, then localStorage, then home.
  const saved = state.postcode || localStorage.getItem(POSTCODE_KEY) || "";
  const pcInput = document.getElementById("postcode");
  if (saved) {
    pcInput.value = saved;
    const coords = await geocode(saved);
    state.postcode = saved;
    state.origin = coords || { lat: state.data.home.lat, lon: state.data.home.lon };
  } else {
    state.origin = { lat: state.data.home.lat, lon: state.data.home.lon };
  }
  setHomeLabel();
  applyDistances();

  document.getElementById("postcode-form").addEventListener("submit", (e) => {
    e.preventDefault(); applyPostcode(pcInput.value);
  });
  document.getElementById("radius").addEventListener("change", (e) => {
    state.radius = e.target.value; render();
  });
  document.getElementById("view").addEventListener("change", (e) => {
    state.view = e.target.value; render();
  });
  let timer = null;
  document.getElementById("search").addEventListener("input", (e) => {
    clearTimeout(timer);
    const v = e.target.value.trim();
    timer = setTimeout(() => { state.search = v; render(); }, 200);
  });
  document.getElementById("toggle-weekend").addEventListener("click", (e) => {
    state.weekend = !state.weekend; e.target.classList.toggle("active", state.weekend); render();
  });
  document.getElementById("toggle-saved").addEventListener("click", (e) => {
    state.savedOnly = !state.savedOnly; e.target.classList.toggle("active", state.savedOnly); render();
  });
  document.getElementById("toggle-smart").addEventListener("click", (e) => {
    state.smartRadius = !state.smartRadius;
    e.target.classList.toggle("active", state.smartRadius);
    document.getElementById("radius").disabled = state.smartRadius;
    render();
  });
  document.getElementById("health-link").addEventListener("click", (e) => {
    e.preventDefault(); showHealth();
  });
  document.getElementById("modal").addEventListener("click", (e) => {
    if (e.target.hasAttribute("data-close")) closeModal();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  render();
}

init().catch((err) => {
  document.getElementById("content").innerHTML =
    `<p class="empty-msg">Couldn't load events.<br>${escapeHtml(err.message)}<br>` +
    `<small>If this persists, the daily data build may not have run yet.</small></p>`;
});
