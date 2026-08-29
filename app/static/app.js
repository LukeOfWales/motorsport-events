"use strict";

const state = {
  disciplines: [],       // [{value,label}]
  activeDisciplines: new Set(),
  sources: [],           // [{value,label}]
  activeSources: new Set(),
  radius: "150",
  postcode: "",          // user origin postcode ('' = use home default)
  view: "list",
  monthCursor: null,     // Date for the month shown in month view (null=today)
  config: null,
};

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DOW = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function fmtDateRange(startISO, endISO) {
  const s = new Date(startISO + "T00:00:00");
  if (!endISO) return s.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const e = new Date(endISO + "T00:00:00");
  return `${s.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} – ${e.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
}

function buildQuery() {
  const params = new URLSearchParams();
  if (state.radius) params.set("max_distance_km", state.radius);
  if (state.postcode) params.set("postcode", state.postcode);
  for (const d of state.activeDisciplines) params.append("discipline", d);
  for (const s of state.activeSources) params.append("source", s);
  // In month view, fetch just the displayed month (which may be in the past
  // or far future) rather than the default "today onward".
  if (state.view === "month" && state.monthCursor) {
    const y = state.monthCursor.getFullYear();
    const m = state.monthCursor.getMonth();
    params.set("start", isoDate(new Date(y, m, 1)));
    params.set("end", isoDate(new Date(y, m + 1, 0)));
  }
  return params.toString();
}

function isoDate(d) {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function eventCard(ev) {
  const d = new Date(ev.start_date + "T00:00:00");
  const dist = ev.distance_km != null ? `${Math.round(ev.distance_km)} km` : "location TBC";
  const loc = [ev.venue, ev.town].filter(Boolean).join(", ") || "";
  const sources = sourceLabel(ev.source)
    + (ev.alt_sources && ev.alt_sources.length
        ? " · also on " + ev.alt_sources.map(sourceLabel).join(", ")
        : "");
  const a = document.createElement("a");
  a.className = "event";
  a.href = ev.url || "#";
  if (ev.url) { a.target = "_blank"; a.rel = "noopener"; }
  a.innerHTML = `
    <div class="event-date">
      <div class="day">${d.getDate()}</div>
      <div class="mon">${MONTHS[d.getMonth()]}</div>
    </div>
    <div class="event-body">
      <p class="event-title">${escapeHtml(ev.title)}</p>
      <div class="event-meta">
        <span class="badge ${ev.discipline}">${disciplineLabel(ev.discipline)}</span>
        ${loc ? `<span>${escapeHtml(loc)}</span>` : ""}
        <span class="dist">${dist}</span>
        ${ev.end_date ? `<span>${fmtDateRange(ev.start_date, ev.end_date)}</span>` : ""}
        <span class="source">${escapeHtml(sources)}</span>
      </div>
    </div>`;
  return a;
}

function disciplineLabel(value) {
  const d = state.disciplines.find((x) => x.value === value);
  return d ? d.label : value;
}

const SOURCE_LABELS = {
  awdc: "AWDC",
  alrc: "ALRC",
  swlrc: "SWLRC",
  hillclimb_uk: "hillclimb.uk",
  msuk: "Motorsport UK",
  msv: "MSV",
};
function sourceLabel(key) {
  return SOURCE_LABELS[key] || key;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function renderList(events) {
  const content = document.getElementById("content");
  content.innerHTML = "";
  if (!events.length) {
    content.innerHTML = `<p class="empty-msg">No upcoming events match your filters.<br>Try widening the distance or clearing disciplines.</p>`;
    return;
  }
  // Group by month.
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

function renderMonth(events) {
  const content = document.getElementById("content");
  content.innerHTML = "";

  // The displayed month comes from the cursor (defaults to today's month).
  if (!state.monthCursor) {
    const now = new Date();
    state.monthCursor = new Date(now.getFullYear(), now.getMonth(), 1);
  }
  const year = state.monthCursor.getFullYear();
  const month = state.monthCursor.getMonth();

  // Navigation bar: prev / label / next, plus a Today reset.
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

  const byDay = {};
  for (const ev of events) {
    const d = new Date(ev.start_date + "T00:00:00");
    if (d.getFullYear() === year && d.getMonth() === month) {
      (byDay[d.getDate()] ||= []).push(ev);
    }
  }

  const grid = document.createElement("div");
  grid.className = "month-grid";
  for (const dow of DOW) {
    const el = document.createElement("div");
    el.className = "dow";
    el.textContent = dow;
    grid.appendChild(el);
  }

  const firstOfMonth = new Date(year, month, 1);
  // Monday=0 offset
  let lead = (firstOfMonth.getDay() + 6) % 7;
  for (let i = 0; i < lead; i++) {
    const c = document.createElement("div");
    c.className = "cell empty";
    grid.appendChild(c);
  }
  const todayDate = new Date();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  for (let day = 1; day <= daysInMonth; day++) {
    const c = document.createElement("div");
    c.className = "cell";
    if (year === todayDate.getFullYear() && month === todayDate.getMonth()
        && day === todayDate.getDate()) {
      c.classList.add("is-today");
    }
    c.innerHTML = `<span class="num">${day}</span>`;
    for (const ev of byDay[day] || []) {
      const s = document.createElement("span");
      s.className = "ev";
      s.textContent = ev.title;
      s.title = ev.title;
      c.appendChild(s);
    }
    grid.appendChild(c);
  }
  content.appendChild(grid);

  if (!events.length) {
    const note = document.createElement("p");
    note.className = "empty-msg";
    note.textContent = "No events this month match your filters.";
    content.appendChild(note);
  }
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

async function refresh() {
  const data = await getJSON(`/api/events?${buildQuery()}`);
  if (state.view === "month") renderMonth(data.events);
  else renderList(data.events);
  refreshSummary();
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
      ? `Nearest: <strong>${escapeHtml(n.title)}</strong> · ${Math.round(n.distance_km)} km`
      : "No geolocated events yet";
  } catch (_) { /* ignore */ }
}

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

const POSTCODE_KEY = "mse.postcode";

async function applyPostcode(raw) {
  const status = document.getElementById("postcode-status");
  const pc = (raw || "").trim();
  if (!pc) {
    // Cleared -> fall back to the home default.
    state.postcode = "";
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

async function init() {
  state.config = await getJSON("/api/config");

  // Restore a previously chosen postcode, else use the home default.
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

  document.getElementById("postcode-form").addEventListener("submit", (e) => {
    e.preventDefault();
    applyPostcode(pcInput.value);
  });

  document.getElementById("radius").addEventListener("change", (e) => {
    state.radius = e.target.value;
    refresh();
  });
  document.getElementById("view").addEventListener("change", (e) => {
    state.view = e.target.value;
    refresh();
  });

  await refresh();
}

init().catch((err) => {
  document.getElementById("content").innerHTML =
    `<p class="empty-msg">Failed to load: ${escapeHtml(err.message)}</p>`;
});
