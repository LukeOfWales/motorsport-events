"use strict";

const state = {
  disciplines: [],       // [{value,label}]
  activeDisciplines: new Set(),
  sources: [],           // [{value,label}]
  activeSources: new Set(),
  radius: "150",
  postcode: "",          // user origin postcode ('' = use home default)
  search: "",
  weekend: false,
  savedOnly: false,
  smartRadius: false,
  view: "list",
  monthCursor: null,     // Date for the month shown in month view (null=today)
  config: null,
  lastEvents: [],        // most recent fetch, for the map/detail lookups
  map: null,             // Leaflet map instance (lazy)
  mapLayer: null,        // marker layer group
};

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DOW = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

const SOURCE_LABELS = {
  awdc: "AWDC", alrc: "ALRC", swlrc: "SWLRC", hillclimb_uk: "hillclimb.uk",
  msuk: "Motorsport UK", msv: "MSV", pembrey: "Pembrey",
};
function sourceLabel(key) { return SOURCE_LABELS[key] || key; }

// --- saved (starred) events, persisted in localStorage ------------------
const SAVED_KEY = "mse.saved";
function loadSaved() {
  try { return new Set(JSON.parse(localStorage.getItem(SAVED_KEY) || "[]")); }
  catch { return new Set(); }
}
let savedIds = loadSaved();
function eventKey(ev) { return `${ev.source}:${ev.source_id}`; }
function isSaved(ev) { return savedIds.has(eventKey(ev)); }
function toggleSaved(ev) {
  const k = eventKey(ev);
  if (savedIds.has(k)) savedIds.delete(k); else savedIds.add(k);
  localStorage.setItem(SAVED_KEY, JSON.stringify([...savedIds]));
}

// --- helpers ------------------------------------------------------------
async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function fmtDateRange(startISO, endISO) {
  const s = new Date(startISO + "T00:00:00");
  if (!endISO) return s.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const e = new Date(endISO + "T00:00:00");
  return `${s.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} \u2013 ${e.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
}

function isoDate(d) {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function disciplineLabel(value) {
  const d = state.disciplines.find((x) => x.value === value);
  return d ? d.label : value;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function buildQuery() {
  const params = new URLSearchParams();
  if (state.smartRadius) {
    params.set("per_discipline_radius", "true");
  } else if (state.radius) {
    params.set("max_distance_km", state.radius);
  }
  if (state.postcode) params.set("postcode", state.postcode);
  if (state.search) params.set("search", state.search);
  if (state.weekend) params.set("weekend", "true");
  for (const d of state.activeDisciplines) params.append("discipline", d);
  for (const s of state.activeSources) params.append("source", s);
  if (state.view === "month" && state.monthCursor) {
    const y = state.monthCursor.getFullYear();
    const m = state.monthCursor.getMonth();
    params.set("start", isoDate(new Date(y, m, 1)));
    params.set("end", isoDate(new Date(y, m + 1, 0)));
  }
  return params.toString();
}

// Apply the "saved only" client-side filter (server doesn't know saved ids).
function visibleEvents() {
  if (!state.savedOnly) return state.lastEvents;
  return state.lastEvents.filter(isSaved);
}

// --- event card / detail ------------------------------------------------
function eventCard(ev) {
  const d = new Date(ev.start_date + "T00:00:00");
  const dist = ev.distance_km != null ? `${Math.round(ev.distance_km)} km` : "location TBC";
  const loc = [ev.venue, ev.town].filter(Boolean).join(", ") || "";
  const sources = sourceLabel(ev.source)
    + (ev.alt_sources && ev.alt_sources.length
        ? " \u00b7 also on " + ev.alt_sources.map(sourceLabel).join(", ")
        : "");
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
      <p class="event-title">
        ${ev.is_new ? '<span class="new-badge">NEW</span> ' : ""}${escapeHtml(ev.title)}
      </p>
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
    if (state.savedOnly) refreshRender();
  });
  const open = () => openDetail(ev);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return card;
}

function openDetail(ev) {
  const modal = document.getElementById("modal");
  document.getElementById("modal-title").textContent = ev.title;
  const body = document.getElementById("modal-body");
  const loc = [ev.venue, ev.postcode].filter(Boolean).join(", ");
  const mapsUrl = ev.postcode
    ? `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(ev.postcode)}`
    : (ev.latitude != null
        ? `https://www.google.com/maps/dir/?api=1&destination=${ev.latitude},${ev.longitude}`
        : null);
  const rows = [];
  rows.push(`<span class="badge ${ev.discipline}">${disciplineLabel(ev.discipline)}</span>`);
  rows.push(`<p><strong>When:</strong> ${fmtDateRange(ev.start_date, ev.end_date)}</p>`);
  if (loc) rows.push(`<p><strong>Where:</strong> ${escapeHtml(loc)}</p>`);
  if (ev.distance_km != null) rows.push(`<p><strong>Distance:</strong> ${Math.round(ev.distance_km)} km</p>`);
  if (ev.organiser) rows.push(`<p><strong>Organiser:</strong> ${escapeHtml(ev.organiser)}</p>`);
  const srcLine = sourceLabel(ev.source)
    + (ev.alt_sources && ev.alt_sources.length ? " (also on " + ev.alt_sources.map(sourceLabel).join(", ") + ")" : "");
  rows.push(`<p><strong>Source:</strong> ${escapeHtml(srcLine)}</p>`);
  if (ev.description) rows.push(`<p class="detail-desc">${escapeHtml(ev.description)}</p>`);

  const actions = [];
  if (ev.url) actions.push(`<a class="btn" href="${escapeHtml(ev.url)}" target="_blank" rel="noopener">Event page ↗</a>`);
  if (mapsUrl) actions.push(`<a class="btn" href="${mapsUrl}" target="_blank" rel="noopener">Directions ↗</a>`);
  actions.push(`<a class="btn" href="/api/event/${encodeURIComponent(ev.source)}/${encodeURIComponent(ev.source_id)}.ics">Add to calendar</a>`);
  const saved = isSaved(ev);
  actions.push(`<button class="btn btn-save ${saved ? "on" : ""}" id="modal-save">${saved ? "★ Saved" : "☆ Save"}</button>`);

  body.innerHTML = rows.join("") + `<div class="modal-actions">${actions.join("")}</div>`;
  body.querySelector("#modal-save").addEventListener("click", (e) => {
    toggleSaved(ev);
    const on = isSaved(ev);
    e.target.classList.toggle("on", on);
    e.target.textContent = on ? "★ Saved" : "☆ Save";
    if (state.savedOnly) { closeModal(); refreshRender(); }
  });
  modal.hidden = false;
}

function closeModal() { document.getElementById("modal").hidden = true; }

// --- views --------------------------------------------------------------
function renderList(events) {
  const content = document.getElementById("content");
  content.innerHTML = "";
  if (!events.length) {
    content.innerHTML = emptyMsg();
    return;
  }
  let currentKey = null;
  for (const ev of events) {
    const d = new Date(ev.start_date + "T00:00:00");
    const key = `${d.getFullYear()}-${d.getMonth()}`;
    if (key !== currentKey) {
      currentKey = key;
      const h = document.createElement("div");
      h.className = "date-header";
      h.textContent = d.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
      content.appendChild(h);
    }
    content.appendChild(eventCard(ev));
  }
}

function emptyMsg() {
  if (state.savedOnly) return `<p class="empty-msg">No saved events match your filters.</p>`;
  return `<p class="empty-msg">No events match your filters.<br>Try widening the distance, clearing the search, or removing filters.</p>`;
}

function renderMonth(events) {
  const content = document.getElementById("content");
  content.innerHTML = "";
  if (!state.monthCursor) {
    const now = new Date();
    state.monthCursor = new Date(now.getFullYear(), now.getMonth(), 1);
  }
  const year = state.monthCursor.getFullYear();
  const month = state.monthCursor.getMonth();

  const nav = document.createElement("div");
  nav.className = "month-nav";
  const prev = document.createElement("button");
  prev.type = "button"; prev.textContent = "\u2039"; prev.title = "Previous month";
  prev.setAttribute("aria-label", "Previous month");
  prev.addEventListener("click", () => shiftMonth(-1));
  const next = document.createElement("button");
  next.type = "button"; next.textContent = "\u203a"; next.title = "Next month";
  next.setAttribute("aria-label", "Next month");
  next.addEventListener("click", () => shiftMonth(1));
  const label = document.createElement("h2");
  label.className = "month-title";
  label.textContent = state.monthCursor.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  const today = document.createElement("button");
  today.type = "button"; today.textContent = "Today"; today.className = "month-today";
  today.addEventListener("click", goToToday);
  nav.append(prev, label, next, today);
  content.appendChild(nav);

  // Map each day-of-month to the events that fall on OR span it.
  const byDay = {};
  const lastDay = new Date(year, month + 1, 0).getDate();
  for (const ev of events) {
    const s = new Date(ev.start_date + "T00:00:00");
    const e = ev.end_date ? new Date(ev.end_date + "T00:00:00") : s;
    for (let day = 1; day <= lastDay; day++) {
      const cell = new Date(year, month, day);
      if (cell >= new Date(s.getFullYear(), s.getMonth(), s.getDate())
          && cell <= new Date(e.getFullYear(), e.getMonth(), e.getDate())) {
        (byDay[day] ||= []).push(ev);
      }
    }
  }

  const grid = document.createElement("div");
  grid.className = "month-grid";
  for (const dow of DOW) {
    const el = document.createElement("div");
    el.className = "dow"; el.textContent = dow;
    grid.appendChild(el);
  }
  const firstOfMonth = new Date(year, month, 1);
  let lead = (firstOfMonth.getDay() + 6) % 7;
  for (let i = 0; i < lead; i++) {
    const c = document.createElement("div"); c.className = "cell empty";
    grid.appendChild(c);
  }
  const todayDate = new Date();
  for (let day = 1; day <= lastDay; day++) {
    const c = document.createElement("div");
    c.className = "cell";
    if (year === todayDate.getFullYear() && month === todayDate.getMonth() && day === todayDate.getDate()) {
      c.classList.add("is-today");
    }
    c.innerHTML = `<span class="num">${day}</span>`;
    for (const ev of byDay[day] || []) {
      const s = document.createElement("span");
      s.className = `ev disc-${ev.discipline}`;
      s.textContent = ev.title;
      s.title = ev.title;
      s.addEventListener("click", () => openDetail(ev));
      c.appendChild(s);
    }
    grid.appendChild(c);
  }
  content.appendChild(grid);
  if (!events.length) {
    const note = document.createElement("p");
    note.className = "empty-msg"; note.textContent = "No events this month match your filters.";
    content.appendChild(note);
  }
}

function renderMap(events) {
  const content = document.getElementById("content");
  content.innerHTML = `<div id="map"></div>`;
  const located = events.filter((e) => e.latitude != null && e.longitude != null);

  // (Re)create the map each render; Leaflet needs a live container.
  const el = document.getElementById("map");
  const map = L.map(el);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  const markers = [];
  for (const ev of located) {
    const m = L.marker([ev.latitude, ev.longitude]);
    const dist = ev.distance_km != null ? ` · ${Math.round(ev.distance_km)} km` : "";
    m.bindPopup(
      `<strong>${escapeHtml(ev.title)}</strong><br>${fmtDateRange(ev.start_date, ev.end_date)}${dist}` +
      `<br><a href="#" class="popup-more">details</a>`
    );
    m.on("popupopen", (e) => {
      const link = e.popup.getElement().querySelector(".popup-more");
      if (link) link.addEventListener("click", (ev2) => { ev2.preventDefault(); openDetail(ev); });
    });
    m.addTo(map);
    markers.push(m);
  }

  // Add a home/origin marker.
  const originLat = state.originLat, originLon = state.originLon;
  if (originLat != null) {
    L.circleMarker([originLat, originLon], { radius: 7, color: "#ff5a1f", fillOpacity: 0.9 })
      .bindPopup("You are here").addTo(map);
  }

  if (markers.length) {
    const group = L.featureGroup(markers);
    map.fitBounds(group.getBounds().pad(0.2));
  } else if (originLat != null) {
    map.setView([originLat, originLon], 9);
  } else {
    map.setView([52.5, -3.5], 6); // UK-ish
  }

  if (!located.length) {
    const note = document.createElement("p");
    note.className = "empty-msg";
    note.textContent = "No mappable events match your filters.";
    content.appendChild(note);
  }
  // Leaflet sometimes needs a nudge once the container has its size.
  setTimeout(() => map.invalidateSize(), 100);
}

function shiftMonth(delta) {
  const c = state.monthCursor || new Date();
  state.monthCursor = new Date(c.getFullYear(), c.getMonth() + delta, 1);
  refresh();
}
function goToToday() {
  const now = new Date();
  state.monthCursor = new Date(now.getFullYear(), now.getMonth(), 1);
  refresh();
}

// Re-render the current view from the last fetch (no network).
function refreshRender() {
  const events = visibleEvents();
  if (state.view === "month") renderMonth(events);
  else if (state.view === "map") renderMap(events);
  else renderList(events);
}

async function refresh() {
  const data = await getJSON(`/api/events?${buildQuery()}`);
  state.lastEvents = data.events;
  refreshRender();
  refreshSummary();
  updateSubscribeLink();
}

function updateSubscribeLink() {
  document.getElementById("subscribe-link").href = `/api/events.ics?${buildQuery()}`;
}

async function refreshSummary() {
  try {
    const params = new URLSearchParams({ days: "30" });
    if (state.postcode) params.set("postcode", state.postcode);
    const s = await getJSON(`/api/summary?${params.toString()}`);
    const sec = document.getElementById("summary");
    sec.hidden = false;
    document.getElementById("summary-total").innerHTML =
      `<strong>${s.total}</strong> events in the next ${s.days} days`;
    const n = s.nearest;
    document.getElementById("summary-nearest").innerHTML = n
      ? `Nearest: <strong>${escapeHtml(n.title)}</strong> \u00b7 ${Math.round(n.distance_km)} km`
      : "No geolocated events yet";
  } catch (_) { /* ignore */ }
}

// --- filter chips -------------------------------------------------------
function renderDisciplineChips() {
  const box = document.getElementById("disciplines");
  box.innerHTML = "";
  for (const d of state.disciplines) {
    const chip = document.createElement("span");
    chip.className = "chip" + (state.activeDisciplines.has(d.value) ? " active" : "");
    chip.textContent = d.label;
    chip.addEventListener("click", () => {
      if (state.activeDisciplines.has(d.value)) state.activeDisciplines.delete(d.value);
      else state.activeDisciplines.add(d.value);
      renderDisciplineChips();
      refresh();
    });
    box.appendChild(chip);
  }
}

function renderSourceChips() {
  const box = document.getElementById("sources");
  box.innerHTML = "";
  for (const s of state.sources) {
    const chip = document.createElement("span");
    chip.className = "chip" + (state.activeSources.has(s.value) ? " active" : "");
    chip.textContent = sourceLabel(s.value);
    chip.title = s.label;
    chip.addEventListener("click", () => {
      if (state.activeSources.has(s.value)) state.activeSources.delete(s.value);
      else state.activeSources.add(s.value);
      renderSourceChips();
      refresh();
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
    state.originLat = state.config.home_lat;
    state.originLon = state.config.home_lon;
    localStorage.removeItem(POSTCODE_KEY);
    status.textContent = `Using default (${state.config.home_postcode})`;
    status.classList.remove("error");
    setHomeLabel();
    await refresh();
    return;
  }
  status.textContent = "Locating\u2026";
  status.classList.remove("error");
  try {
    const res = await getJSON(`/api/geocode?postcode=${encodeURIComponent(pc)}`);
    if (!res.found) {
      status.textContent = `Couldn't find "${pc}"`;
      status.classList.add("error");
      return;
    }
    state.postcode = res.postcode;
    state.originLat = res.latitude;
    state.originLon = res.longitude;
    localStorage.setItem(POSTCODE_KEY, res.postcode);
    status.textContent = `Showing distances from ${res.postcode}`;
    status.classList.remove("error");
    setHomeLabel();
    await refresh();
  } catch (err) {
    status.textContent = "Lookup failed";
    status.classList.add("error");
  }
}

function setHomeLabel() {
  const pc = state.postcode || state.config.home_postcode;
  document.getElementById("home-label").textContent = `near ${pc}`;
}

// --- health panel -------------------------------------------------------
async function showHealth() {
  const data = await getJSON("/api/health");
  const modal = document.getElementById("modal");
  document.getElementById("modal-title").textContent = "Source status";
  const rows = data.sources.map((s) => {
    const when = s.run_at ? new Date(s.run_at).toLocaleString("en-GB") : "never";
    const cls = s.ok ? "ok" : "bad";
    return `<tr><td>${escapeHtml(sourceLabel(s.source))}</td>` +
      `<td class="${cls}">${s.ok ? "OK" : "FAILED"}</td>` +
      `<td>${s.event_count}</td><td>${escapeHtml(when)}</td></tr>` +
      (s.error ? `<tr><td colspan="4" class="bad small">${escapeHtml(s.error)}</td></tr>` : "");
  }).join("");
  document.getElementById("modal-body").innerHTML =
    `<p>${data.total_events} events in the database.</p>` +
    `<table class="health"><thead><tr><th>Source</th><th>Status</th><th>Events</th><th>Last run</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`;
  modal.hidden = false;
}

// --- init ---------------------------------------------------------------
async function init() {
  state.config = await getJSON("/api/config");
  state.originLat = state.config.home_lat;
  state.originLon = state.config.home_lon;

  const saved = localStorage.getItem(POSTCODE_KEY) || "";
  state.postcode = saved;
  const pcInput = document.getElementById("postcode");
  pcInput.value = saved;
  setHomeLabel();

  document.getElementById("radius").value = String(state.config.default_radius_km);
  state.radius = String(state.config.default_radius_km);

  state.disciplines = await getJSON("/api/disciplines");
  renderDisciplineChips();
  state.sources = await getJSON("/api/sources");
  renderSourceChips();

  // If a saved postcode exists, resolve its coords for the map origin.
  if (saved) {
    try {
      const res = await getJSON(`/api/geocode?postcode=${encodeURIComponent(saved)}`);
      if (res.found) { state.originLat = res.latitude; state.originLon = res.longitude; }
    } catch (_) { /* ignore */ }
  }

  document.getElementById("postcode-form").addEventListener("submit", (e) => {
    e.preventDefault(); applyPostcode(pcInput.value);
  });
  document.getElementById("radius").addEventListener("change", (e) => {
    state.radius = e.target.value; refresh();
  });
  document.getElementById("view").addEventListener("change", (e) => {
    state.view = e.target.value; refresh();
  });

  // Debounced search.
  let searchTimer = null;
  document.getElementById("search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    const v = e.target.value.trim();
    searchTimer = setTimeout(() => { state.search = v; refresh(); }, 250);
  });

  document.getElementById("toggle-weekend").addEventListener("click", (e) => {
    state.weekend = !state.weekend;
    e.target.classList.toggle("active", state.weekend);
    refresh();
  });
  document.getElementById("toggle-saved").addEventListener("click", (e) => {
    state.savedOnly = !state.savedOnly;
    e.target.classList.toggle("active", state.savedOnly);
    refreshRender();
  });
  document.getElementById("toggle-smart").addEventListener("click", (e) => {
    state.smartRadius = !state.smartRadius;
    e.target.classList.toggle("active", state.smartRadius);
    document.getElementById("radius").disabled = state.smartRadius;
    refresh();
  });

  document.getElementById("health-link").addEventListener("click", (e) => {
    e.preventDefault(); showHealth();
  });

  // Modal close handlers.
  document.getElementById("modal").addEventListener("click", (e) => {
    if (e.target.hasAttribute("data-close")) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  await refresh();
}

init().catch((err) => {
  document.getElementById("content").innerHTML =
    `<p class="empty-msg">Failed to load: ${escapeHtml(err.message)}</p>`;
});
