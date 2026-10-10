// Market Dashboard client.
//
// Groups come from /api/groups (Neon). Values come from /api/quotes, which the
// page asks for with its own Symbol list so Vercel's CDN can serve every tab
// and device from one upstream fetch. Prices refresh every 60s during US
// market hours and every 5 minutes otherwise, only while the page is visible.

const MINUS = "−";
const ET = "America/New_York";
const OPEN_POLL = 60_000;
const CLOSED_POLL = 5 * 60_000;
const HEADLINE_POLL = 5 * 60_000;
const STALE_AFTER = 5 * 60_000;
const SUB_LABELS = { indices: "Indices", rates: "Rates", fx: "FX", commodities: "Commodities", crypto: "Crypto" };
const CACHE_KEY = "md.v1.cache";
const COLLAPSE_KEY = "md.v1.collapsed";
// The one-line summary under the header: Symbol key and how to show it.
const SUMMARY = ["yahoo:^GSPC", "yahoo:^TNX", "yahoo:^VIX"];

const state = {
  groups: null,
  subsections: Object.keys(SUB_LABELS),
  groupsError: null,
  quotes: {},
  quotesAsOf: null,
  market: null,
  stale: [],
  errors: {},
  quotesError: null,
  headlines: null,
  headlinesAsOf: null,
  headlinesError: null,
  editor: false,
  editingEnabled: false,
  editing: false,
  sort: {}, // group id -> { col, dir }
  collapsed: readJSON(COLLAPSE_KEY, {}), // Theme id -> true
  open: new Set(), // expanded rows and tiles, "groupId:itemId"
};
const meta = new Map(); // "source:symbol" -> item (kind, decimals, label, band...)

// --- Small helpers -------------------------------------------------------------

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style") el.style.cssText = v;
    else if (k === "hidden") el.hidden = true;
    else if (k === "value") el.value = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}

function svg(tag, attrs = {}, ...kids) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...kids);
  return el;
}

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode or full: the page works without it */
  }
}

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-MD"] = "1";
  const r = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try {
    data = await r.json();
  } catch {
    /* empty or non-JSON body */
  }
  if (!r.ok) {
    let msg = data?.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    const err = new Error(msg || `Request failed (${r.status})`);
    err.status = r.status;
    err.data = data;
    throw err;
  }
  return data;
}

// --- Formatting ------------------------------------------------------------------

const numberFormats = new Map();
function nf(dec) {
  if (!numberFormats.has(dec)) {
    numberFormats.set(dec, new Intl.NumberFormat("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }));
  }
  return numberFormats.get(dec);
}

function signed(x, dec, unit = "") {
  const body = nf(dec).format(Math.abs(x));
  const zero = Number(body.replace(/,/g, "")) === 0;
  return (zero ? "" : x > 0 ? "+" : MINUS) + body + unit;
}

function direction(x, dec) {
  if (x == null || !Number.isFinite(x) || Number(Math.abs(x).toFixed(dec)) === 0) return "flat";
  return x > 0 ? "up" : "down";
}

// A change in the unit the Symbol's kind calls for: % for prices, bp for rates, points for vol.
function fmtChange(kind, x) {
  if (x == null || !Number.isFinite(x)) return { text: "–", cls: "flat" };
  if (kind === "rate" || kind === "spread") {
    const dec = Math.abs(x) > 0 && Math.abs(x) < 1 ? 1 : 0;
    return { text: signed(x, dec, "bp"), cls: direction(x, dec) };
  }
  if (kind === "vol") return { text: signed(x, 2), cls: direction(x, 2) };
  const a = Math.abs(x);
  const dec = a >= 100 ? 0 : a >= 10 ? 1 : 2;
  return { text: signed(x, dec, "%"), cls: direction(x, dec) };
}

function fmtLevel(item, x) {
  if (x == null || !Number.isFinite(x)) return "–";
  if (item.kind === "rate") return `${nf(2).format(x)}%`;
  if (item.kind === "spread") {
    const bp = Math.round(x * 100);
    return `${bp < 0 ? MINUS : ""}${nf(0).format(Math.abs(bp))}bp`;
  }
  if (item.kind === "vol") return nf(2).format(x);
  return `${x < 0 ? MINUS : ""}${nf(item.decimals ?? 2).format(Math.abs(x))}`;
}

const etTime = new Intl.DateTimeFormat("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
const etDayTime = new Intl.DateTimeFormat("en-US", { timeZone: ET, weekday: "short", hour: "numeric", minute: "2-digit" });
const etDayKey = new Intl.DateTimeFormat("en-CA", { timeZone: ET, year: "numeric", month: "2-digit", day: "2-digit" });
const etLongDate = new Intl.DateTimeFormat("en-US", { timeZone: ET, weekday: "long", month: "long", day: "numeric" });
const etShortDate = new Intl.DateTimeFormat("en-US", { timeZone: ET, weekday: "short", month: "short", day: "numeric" });
const etShortDateTime = new Intl.DateTimeFormat("en-US", { timeZone: ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const utcShortDate = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });

const ampm = (s) => s.replace(/\s*([AP])M/, (_, p) => `${p.toLowerCase()}m`);
const timeET = (d) => `${ampm(etTime.format(d))} ET`;
const shortDate = (iso) => utcShortDate.format(new Date(`${iso}T12:00:00Z`)); // a session date, no clock time

function whenET(d) {
  // "9:30am ET" today, "Mon 9:30am ET" another day
  const sameDay = etDayKey.format(d) === etDayKey.format(new Date());
  return sameDay ? timeET(d) : `${ampm(etDayTime.format(d))} ET`;
}

function age(iso) {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60_000));
  if (mins < 60) return `${mins}m`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)}h`;
  return `${Math.round(mins / 1440)}d`;
}

const displayName = (item) => (item.label && item.label !== item.symbol ? item.label : item.name || "");

// --- State helpers ---------------------------------------------------------------

function indexMeta() {
  meta.clear();
  for (const g of state.groups ?? []) for (const item of g.items) meta.set(item.key, item);
}

const groupById = (id) => state.groups?.find((g) => g.id === id);
const marketGroup = () => state.groups?.find((g) => g.kind === "market");
const watchlistGroup = () => state.groups?.find((g) => g.kind === "watchlist");

function quoteRefs() {
  const refs = new Set();
  for (const g of state.groups ?? []) for (const i of g.items) refs.add(`${i.source}:${i.symbol}:${i.kind}`);
  return [...refs].sort();
}

function persist() {
  const keep = new Set(meta.keys());
  const quotes = Object.fromEntries(Object.entries(state.quotes).filter(([k]) => keep.has(k)));
  writeJSON(CACHE_KEY, {
    groups: state.groups,
    subsections: state.subsections,
    quotes,
    quotesAsOf: state.quotesAsOf,
    market: state.market,
    headlines: state.headlines,
    headlinesAsOf: state.headlinesAsOf,
  });
}

function restore() {
  const c = readJSON(CACHE_KEY, null);
  if (!c || !Array.isArray(c.groups)) return;
  Object.assign(state, {
    groups: c.groups,
    subsections: c.subsections ?? state.subsections,
    quotes: c.quotes ?? {},
    quotesAsOf: c.quotesAsOf ?? null,
    market: c.market ?? null,
    headlines: c.headlines ?? null,
    headlinesAsOf: c.headlinesAsOf ?? null,
  });
  indexMeta();
}

// --- Header ----------------------------------------------------------------------

function renderHeader() {
  const now = new Date();
  $("#today").replaceChildren(h("span", { class: "long" }, etLongDate.format(now)), h("span", { class: "short" }, etShortDate.format(now)));

  const status = $("#status");
  status.replaceChildren();
  const m = state.market;
  if (m) {
    const label = {
      open: "Market open",
      pre: "Pre-market",
      post: "After hours",
      closed: m.holiday ? `Closed for ${m.holiday}` : "Market closed",
    }[m.state];
    status.append(h("span", {}, h("span", { class: `dot ${m.state}`, "aria-hidden": "true" }), h("span", { class: "state" }, label)));
    if (m.state === "open" && m.closes_at) {
      status.append(h("span", {}, `closes ${timeET(new Date(m.closes_at))}${m.early_close ? " (early close)" : ""}`));
    } else if (m.next_open) {
      status.append(h("span", {}, `opens ${whenET(new Date(m.next_open))}`));
    }
  }
  if (state.quotesAsOf) status.append(h("span", { class: "asof" }, `as of ${timeET(new Date(state.quotesAsOf))}`));

  const summary = $("#summary");
  summary.replaceChildren();
  for (const key of SUMMARY) {
    const item = meta.get(key);
    const q = state.quotes[key];
    if (!item || !q) continue;
    const c = fmtChange(item.kind, q.d);
    const showLevel = item.kind !== "price";
    summary.append(h("span", {},
      h("b", {}, item.label || item.symbol),
      showLevel ? `${fmtLevel(item, q.last)} ` : "",
      h("span", { class: c.cls }, c.text)));
  }

  const notice = $("#notice");
  const asOf = state.quotesAsOf ? new Date(state.quotesAsOf) : null;
  let msg = null;
  if (state.groupsError && !state.groups) msg = `Couldn't load your Groups: ${state.groupsError}`;
  else if (state.quotesError) {
    msg = asOf
      ? `Couldn't refresh prices (${state.quotesError}). Showing prices from ${timeET(asOf)}.`
      : `Couldn't load prices: ${state.quotesError}`;
  } else if (m?.state === "open" && asOf && Date.now() - asOf > STALE_AFTER) {
    msg = `Prices are ${Math.round((Date.now() - asOf) / 60_000)} min old.`;
  } else if (state.stale.length) {
    const n = state.stale.length;
    msg = `${n} Symbol${n > 1 ? "s" : ""} couldn't be refreshed; showing the last saved price${n > 1 ? "s" : ""}.`;
  }
  notice.hidden = !msg;
  notice.textContent = msg ?? "";

  const bad = Object.keys(state.errors);
  const metaEl = $("#market-meta");
  metaEl.textContent = bad.length ? `${bad.length} unavailable` : "";
  metaEl.title = bad.length ? bad.map((k) => `${k}: ${state.errors[k]}`).join("\n") : "";

  renderControls();
}

function renderControls() {
  $("#login-btn").hidden = state.editor || !state.editingEnabled;
  $("#edit-btn").hidden = !state.editor;
  $("#edit-btn").setAttribute("aria-pressed", String(state.editing));
  $("#edit-btn").textContent = state.editing ? "Done" : "Edit";
  $("#logout-btn").hidden = !state.editing;
  document.body.classList.toggle("editing", state.editing);
}

// --- Values: sparkline, range bar, changes ---------------------------------------------

function dayChange(item, q) {
  const c = fmtChange(item.kind, q?.d);
  const unusual = q?.unusual && c.cls !== "flat";
  const out = [h("span", { class: `chg ${c.cls}${unusual ? " unusual" : ""}` }, c.text)];
  if (unusual && q.z != null) {
    const z = Math.abs(q.z).toFixed(1);
    out.push(h("span", { class: "sigma", title: `${z}× its typical daily move (RMS of the last 20)` }, `${z}σ`));
  }
  return out;
}

function sparkline(el, item, points) {
  el.replaceChildren();
  el._spark = null;
  if (!points || points.length < 2) return;
  const vals = points.map((p) => p[1]);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (hi === lo) {
    hi += 1;
    lo -= 1;
  }
  const n = points.length;
  const x = (i) => (i / (n - 1)) * 100;
  const y = (v) => 3 + (1 - (v - lo) / (hi - lo)) * 24; // viewBox height 30, 3 of padding
  const d = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join("");
  el.append(
    svg("svg", { viewBox: "0 0 100 30", preserveAspectRatio: "none", "aria-hidden": "true" },
      svg("path", { d, "vector-effect": "non-scaling-stroke" })),
    h("span", { class: "spark-dot", style: `left:100%;top:${((y(vals[n - 1]) / 30) * 100).toFixed(1)}%` }),
  );
  el._spark = { points, item, top: (v) => (y(v) / 30) * 100 };
  el.setAttribute("role", "img");
  const first = points[0];
  const change = fmtChange(item.kind, kindChange(item.kind, vals[n - 1], first[1]));
  el.setAttribute("aria-label", `1 month: ${fmtLevel(item, first[1])} on ${shortDate(first[0])} to ${fmtLevel(item, vals[n - 1])}, ${change.text}`);
}

function kindChange(kind, now, then) {
  if (now == null || then == null) return null;
  if (kind === "rate" || kind === "spread") return (now - then) * 100;
  if (kind === "vol") return now - then;
  return then ? (now / then - 1) * 100 : null;
}

function rangeBar(el, item, q) {
  el.replaceChildren();
  el.removeAttribute("title");
  const peg = Array.isArray(item.band);
  const [lo, hi] = peg ? item.band : [q?.lo, q?.hi];
  if (q?.last == null || lo == null || hi == null || hi <= lo) return;
  const pos = clamp((q.last - lo) / (hi - lo), 0, 1);
  el.classList.toggle("peg", peg);
  el.append(h("span", { class: "range-track" }), h("span", { class: "range-dot", style: `left:${(pos * 100).toFixed(1)}%` }));
  const label = peg
    ? `Peg band ${lo}–${hi}; now ${fmtLevel(item, q.last)}`
    : `52-week range ${fmtLevel(item, lo)} – ${fmtLevel(item, hi)}; now ${fmtLevel(item, q.last)}`;
  el.title = label;
  el.setAttribute("role", "img");
  el.setAttribute("aria-label", label);
}

function details(el, item, q, { withChanges }) {
  el.replaceChildren();
  if (!q) {
    el.append(h("span", {}, state.errors[item.key] === "not_found" ? "The source has no data for this Symbol." : "No data yet."));
    return;
  }
  const fact = (label, value, cls) => h("span", { class: cls }, label ? h("span", { class: "lbl" }, label) : null, value);
  if (withChanges) {
    for (const [label, key] of [["1W", "w"], ["YTD", "ytd"]]) {
      const c = fmtChange(item.kind, q[key]);
      el.append(fact(label, h("span", { class: c.cls }, c.text), "detail-only"));
    }
  }
  if (Array.isArray(item.band)) {
    el.append(fact("Peg band", `${item.band[0]}–${item.band[1]}`));
  } else if (q.lo != null) {
    el.append(fact("52W", `${fmtLevel(item, q.lo)} – ${fmtLevel(item, q.hi)}`));
    if (item.kind === "price" && q.hi) el.append(fact("From high", fmtChange("price", (q.last / q.hi - 1) * 100).text));
  }
  if (q.typical != null) el.append(fact("Typical day", `±${fmtChange(item.kind, q.typical).text.replace(/^[+−]/, "")}`));
  if (item.source === "fred") el.append(fact("As of", shortDate(q.date)));
  else if (q.time) el.append(fact("Last trade", `${ampm(etShortDateTime.format(new Date(q.time)))} ET`));
  if (q.stale && q.fetched) el.append(fact("Saved", `${ampm(etShortDateTime.format(new Date(q.fetched)))} ET (not refreshed)`));
  if (item.name && item.name !== displayName(item)) el.append(fact("", item.name));
}

function fillField(el, field, item, q) {
  switch (field) {
    case "last":
      el.replaceChildren(q ? fmtLevel(item, q.last) : state.errors[item.key] ? "n/a" : "–");
      if (q?.stale) el.append(h("span", { class: "stale-mark", title: "Not refreshed; showing the last saved price" }, "•"));
      break;
    case "day":
      el.replaceChildren(...dayChange(item, q));
      break;
    case "w":
    case "ytd": {
      const c = fmtChange(item.kind, q?.[field]);
      el.textContent = c.text;
      el.classList.remove("up", "down", "flat");
      el.classList.add(c.cls);
      break;
    }
    case "spark":
      sparkline(el, item, q?.spark);
      break;
    case "range":
      rangeBar(el, item, q);
      break;
    case "asof":
      el.textContent = item.source === "fred" && q?.date ? shortDate(q.date) : "";
      break;
    case "detail":
      details(el, item, q, { withChanges: el.dataset.changes === "1" });
      break;
  }
}

function themeAverage(g) {
  const moves = g.items
    .filter((i) => i.kind === "price" || i.kind === "peg")
    .map((i) => state.quotes[i.key]?.d)
    .filter((d) => d != null && Number.isFinite(d));
  if (!moves.length) return { text: "", cls: "flat" };
  return fmtChange("price", moves.reduce((a, b) => a + b, 0) / moves.length);
}

function fillValues(root = document) {
  for (const el of $$("[data-key]", root)) {
    const item = meta.get(el.dataset.key);
    if (!item) continue;
    const q = state.quotes[el.dataset.key];
    for (const f of $$("[data-f]", el)) fillField(f, f.dataset.f, item, q);
  }
  for (const el of $$("[data-f='avg']", root)) {
    const g = groupById(Number(el.dataset.gid));
    if (!g) continue;
    const avg = themeAverage(g);
    el.textContent = avg.text;
    el.classList.remove("up", "down", "flat");
    el.classList.add(avg.cls);
  }
}

// After new quotes: refill in place, but re-render sorted tables since their order may change.
function updateValues() {
  const sortedGroups = Object.keys(state.sort).map(Number);
  for (const gid of sortedGroups) {
    const g = groupById(gid);
    if (g) renderGroup(g);
  }
  fillValues();
  renderHeader();
}

// --- Sparkline hover (mouse only; every value is also on the page) -----------------------

let hovered = null;
function clearHover() {
  if (!hovered) return;
  $$(".spark-cursor, .spark-hover", hovered).forEach((n) => n.remove());
  hovered = null;
  $("#tip").hidden = true;
}

document.addEventListener("pointermove", (e) => {
  if (e.pointerType !== "mouse") return;
  const el = e.target.closest?.(".spark");
  if (!el?._spark) return clearHover();
  if (hovered !== el) {
    clearHover();
    hovered = el;
    el.append(h("span", { class: "spark-cursor" }), h("span", { class: "spark-hover" }));
  }
  const { points, item, top } = el._spark;
  const r = el.getBoundingClientRect();
  const i = Math.round(clamp((e.clientX - r.left) / r.width, 0, 1) * (points.length - 1));
  const [day, value] = points[i];
  const left = `${((i / (points.length - 1)) * 100).toFixed(2)}%`;
  $(".spark-cursor", el).style.left = left;
  Object.assign($(".spark-hover", el).style, { left, top: `${top(value).toFixed(1)}%` });
  const tip = $("#tip");
  tip.replaceChildren(h("div", { class: "v" }, fmtLevel(item, value)), h("div", { class: "l" }, shortDate(day)));
  tip.hidden = false;
  const tw = tip.offsetWidth;
  tip.style.left = `${clamp(e.clientX - tw / 2, 8, window.innerWidth - tw - 8)}px`;
  tip.style.top = `${Math.max(8, r.top - tip.offsetHeight - 8)}px`;
});
document.addEventListener("scroll", clearHover, { passive: true });

// --- Market ------------------------------------------------------------------------

function gripIcon() {
  return svg("svg", { width: "10", height: "14", viewBox: "0 0 10 14", "aria-hidden": "true" },
    ...[2, 7, 12].flatMap((cy) => [svg("circle", { cx: "2.5", cy: String(cy), r: "1.3", fill: "currentColor" }),
      svg("circle", { cx: "7.5", cy: String(cy), r: "1.3", fill: "currentColor" })]));
}

const handle = (extra = "", label = "Drag to reorder") => h("button", { class: `handle ${extra}`.trim(), type: "button", "aria-label": label, title: label }, gripIcon());

function toggleOpen(id) {
  if (state.open.has(id)) state.open.delete(id);
  else state.open.add(id);
  const g = groupById(Number(id.split(":")[0]));
  if (g) renderGroup(g);
}

function onActivate(el, fn) {
  el.addEventListener("click", (e) => {
    if (e.target.closest("button, a, input, select")) return;
    fn();
  });
  el.addEventListener("keydown", (e) => {
    if (e.target !== el) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fn();
    }
  });
}

function tile(g, item) {
  const id = `${g.id}:${item.id}`;
  const open = state.open.has(id);
  const el = h("div", {
    class: `tile${open ? " open" : ""}`,
    tabindex: "0",
    "aria-expanded": String(open),
    "aria-label": `${item.label || item.symbol}, details`,
    dataset: { key: item.key, id: item.id },
  },
    h("div", { class: "tile-head" },
      h("span", { class: "tile-label", title: `${item.symbol} · ${item.name}` }, item.label || item.symbol),
      h("span", { class: "tile-asof", dataset: { f: "asof" }, title: "FRED publishes with a lag; this is the latest date" })),
    h("div", { class: "tile-main" },
      h("span", { class: "tile-last", dataset: { f: "last" } }),
      h("span", { class: "tile-day", dataset: { f: "day" } })),
    h("div", { class: "spark", dataset: { f: "spark" } }),
    h("div", { class: "tile-foot" },
      h("span", {}, h("span", { class: "lbl" }, "1W"), h("span", { dataset: { f: "w" } })),
      h("span", {}, h("span", { class: "lbl" }, "YTD"), h("span", { dataset: { f: "ytd" } })),
      h("div", { class: "range", dataset: { f: "range" } })),
    open ? h("div", { class: "tile-detail", dataset: { f: "detail" } }) : null,
    state.editing ? h("div", { class: "tile-tools" }, handle(), removeButton(g, item)) : null,
  );
  onActivate(el, () => toggleOpen(id));
  return el;
}

function renderMarket() {
  const body = $("#market-body");
  body.replaceChildren();
  const g = marketGroup();
  if (!g) {
    body.append(placeholder("Market"));
    return;
  }
  for (const sub of state.subsections) {
    const items = g.items.filter((i) => i.subsection === sub);
    if (!items.length && !state.editing) continue;
    const grid = h("div", { class: "tiles", dataset: { sub } }, items.map((i) => tile(g, i)));
    body.append(h("div", { class: "subsection" }, h("h3", {}, SUB_LABELS[sub] ?? sub), grid));
    makeSortable(grid, { group: "market", draggable: ".tile", onEnd: () => saveMarketOrder(g) });
  }
  if (state.editing) body.append(addForm(g));
  fillValues(body);
}

async function saveMarketOrder(g) {
  const order = [];
  for (const grid of $$("#market-body .tiles")) {
    for (const t of $$(".tile", grid)) order.push({ id: Number(t.dataset.id), subsection: grid.dataset.sub });
  }
  const byId = new Map(g.items.map((i) => [i.id, i]));
  g.items = order.map((o) => Object.assign(byId.get(o.id), { subsection: o.subsection }));
  indexMeta();
  persist();
  renderMarket();
  try {
    await api(`/api/groups/${g.id}/symbols/order`, { method: "PUT", body: { items: order } });
  } catch (err) {
    flash(err.message);
    loadGroups();
  }
}

// --- Tables (Watchlist and Themes) ----------------------------------------------------

const COLUMNS = [
  { key: "sym", label: "Symbol", cls: "c-sym", sort: "asc" },
  { key: "last", label: "Last", cls: "c-last" },
  { key: "d", label: "Day", cls: "c-day", sort: "desc" },
  { key: "w", label: "1W", cls: "c-w", sort: "desc" },
  { key: "ytd", label: "YTD", cls: "c-ytd", sort: "desc" },
  { key: "spark", label: "1M", cls: "c-spark" },
  { key: "range", label: "52W", cls: "c-range", sort: "desc" },
];

function rangePosition(item, q) {
  const [lo, hi] = Array.isArray(item.band) ? item.band : [q?.lo, q?.hi];
  if (q?.last == null || lo == null || hi == null || hi <= lo) return null;
  return (q.last - lo) / (hi - lo);
}

function sortedItems(g) {
  const s = state.sort[g.id];
  if (!s) return g.items;
  const value = (item) => {
    if (s.col === "sym") return item.symbol;
    const q = state.quotes[item.key];
    return s.col === "range" ? rangePosition(item, q) : q?.[s.col];
  };
  return [...g.items].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    if (va == null || vb == null) return va == null ? (vb == null ? 0 : 1) : -1; // missing values last
    const c = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return s.dir === "asc" ? c : -c;
  });
}

function cycleSort(g, col) {
  const first = COLUMNS.find((c) => c.key === col).sort;
  const second = first === "asc" ? "desc" : "asc";
  const cur = state.sort[g.id];
  if (!cur || cur.col !== col) state.sort[g.id] = { col, dir: first };
  else if (cur.dir === first) state.sort[g.id] = { col, dir: second };
  else delete state.sort[g.id]; // third click: back to Jack's order
  renderGroup(g);
  $(`table[data-gid="${g.id}"] th[data-col="${col}"] button`)?.focus();
}

function headerCell(g, col) {
  const s = state.sort[g.id];
  const active = s?.col === col.key;
  const th = h("th", {
    class: col.cls,
    scope: "col",
    dataset: { col: col.key },
    "aria-sort": active ? (s.dir === "asc" ? "ascending" : "descending") : null,
  });
  if (!col.sort) {
    th.append(col.label);
    return th;
  }
  th.append(h("button", { type: "button", title: "Sort; a third click restores your order", onclick: () => cycleSort(g, col.key) },
    col.label, h("span", { class: "arrow", "aria-hidden": "true" }, active ? (s.dir === "asc" ? "▲" : "▼") : "")));
  return th;
}

function itemBody(g, item, ncols) {
  const id = `${g.id}:${item.id}`;
  const open = state.open.has(id);
  const tbody = h("tbody", { class: `item${open ? " open" : ""}`, dataset: { key: item.key, id: item.id } });
  const main = h("tr", { class: "main", tabindex: "0", "aria-expanded": String(open) },
    state.editing ? h("td", { class: "c-handle" }, handle()) : null,
    h("td", { class: "c-sym" }, h("span", { class: "cell", title: item.name },
      h("span", { class: "sym" }, item.symbol), h("span", { class: "name" }, displayName(item)))),
    h("td", { class: "c-last num", dataset: { f: "last" } }),
    h("td", { class: "c-day num", dataset: { f: "day" } }),
    h("td", { class: "c-w num", dataset: { f: "w" } }),
    h("td", { class: "c-ytd num", dataset: { f: "ytd" } }),
    h("td", { class: "c-spark" }, h("div", { class: "spark", dataset: { f: "spark" } })),
    h("td", { class: "c-range" }, h("div", { class: "range", dataset: { f: "range" } })),
    state.editing ? h("td", { class: "c-del" }, removeButton(g, item)) : null,
  );
  onActivate(main, () => toggleOpen(id));
  tbody.append(main);
  if (open) {
    tbody.append(h("tr", { class: "detail" },
      h("td", { colspan: String(ncols) }, h("div", { class: "facts", dataset: { f: "detail", changes: "1" } }))));
  }
  return tbody;
}

function table(g) {
  const sorted = Boolean(state.sort[g.id]);
  const ncols = COLUMNS.length + (state.editing ? 2 : 0);
  const t = h("table", { class: `table${sorted ? " sorted" : ""}`, dataset: { gid: g.id } },
    h("caption", { class: "sr-only" }, `${g.name}. Select a row for details.`),
    h("thead", {}, h("tr", {},
      state.editing ? h("th", { class: "c-handle" }, h("span", { class: "sr-only" }, "Reorder")) : null,
      COLUMNS.map((c) => headerCell(g, c)),
      state.editing ? h("th", { class: "c-del" }, h("span", { class: "sr-only" }, "Remove")) : null)),
    sortedItems(g).map((item) => itemBody(g, item, ncols)));
  if (!sorted) makeSortable(t, { draggable: "tbody.item", onEnd: () => saveTableOrder(g, t) });
  return t;
}

async function saveTableOrder(g, t) {
  const ids = $$("tbody.item", t).map((tb) => Number(tb.dataset.id));
  const byId = new Map(g.items.map((i) => [i.id, i]));
  g.items = ids.map((id) => byId.get(id));
  persist();
  try {
    await api(`/api/groups/${g.id}/symbols/order`, { method: "PUT", body: { items: ids.map((id) => ({ id })) } });
  } catch (err) {
    flash(err.message);
    loadGroups();
  }
}

function renderWatchlist() {
  const body = $("#watchlist-body");
  body.replaceChildren();
  const g = watchlistGroup();
  if (!g) {
    body.append(placeholder("Watchlist"));
    return;
  }
  body.append(g.items.length ? table(g) : h("p", { class: "empty" }, "No Symbols yet."));
  if (state.editing) body.append(addForm(g));
  fillValues(body);
}

// --- Themes ------------------------------------------------------------------------

function chevron() {
  return svg("svg", { class: "chev", viewBox: "0 0 12 12", "aria-hidden": "true" },
    svg("path", { d: "M2.5 4.5 6 8l3.5-3.5", fill: "none", stroke: "currentColor", "stroke-width": "1.6", "stroke-linecap": "round", "stroke-linejoin": "round" }));
}

function toggleCollapse(g) {
  if (state.collapsed[g.id]) delete state.collapsed[g.id];
  else state.collapsed[g.id] = true;
  writeJSON(COLLAPSE_KEY, state.collapsed);
  renderGroup(g);
}

function themeSection(g) {
  const collapsed = Boolean(state.collapsed[g.id]);
  const sec = h("section", { class: "theme", dataset: { gid: g.id }, "aria-label": g.name });
  const avg = h("span", { class: "theme-avg num", dataset: { f: "avg", gid: g.id }, title: "Equal-weighted average day move" });
  const n = g.items.length;
  const count = h("span", { class: "theme-count" }, `${n} Symbol${n === 1 ? "" : "s"}`);
  if (state.editing) {
    const name = h("input", { class: "name", value: g.name, maxlength: "60", "aria-label": "Theme name" });
    const note = h("input", { class: "note", value: g.note, maxlength: "500", placeholder: "Why it matters (optional)", "aria-label": `Note for ${g.name}` });
    const save = async () => {
      const newName = name.value.trim();
      const newNote = note.value.trim();
      if (!newName) {
        name.value = g.name;
        return;
      }
      if (newName === g.name && newNote === g.note) return;
      try {
        const r = await api(`/api/groups/${g.id}`, { method: "PATCH", body: { name: newName, note: newNote } });
        Object.assign(g, { name: r.group.name, note: r.group.note });
        persist();
      } catch (err) {
        name.value = g.name;
        note.value = g.note;
        flash(err.message);
      }
    };
    for (const input of [name, note]) {
      input.addEventListener("change", save);
      input.addEventListener("keydown", (e) => e.key === "Enter" && input.blur());
    }
    sec.append(
      h("div", { class: "theme-head" }, handle("theme-handle", `Drag to reorder ${g.name}`), name, avg, count,
        h("button", { class: "del", type: "button", title: "Delete Theme", "aria-label": `Delete the ${g.name} Theme`, onclick: () => deleteTheme(g) }, "×")),
      h("div", { class: "theme-edit" }, note));
  } else {
    sec.append(h("div", { class: "theme-head" },
      h("h3", {}, h("button", { class: "theme-toggle", type: "button", "aria-expanded": String(!collapsed), onclick: () => toggleCollapse(g) }, chevron(), g.name)),
      avg, count));
    if (g.note) sec.append(h("p", { class: "theme-note" }, g.note));
  }
  const body = h("div", { class: "theme-body", hidden: collapsed && !state.editing });
  body.append(g.items.length ? table(g) : h("p", { class: "empty" }, "No Symbols yet."));
  if (state.editing) body.append(addForm(g));
  sec.append(body);
  return sec;
}

function renderThemes() {
  const body = $("#themes-body");
  body.replaceChildren();
  if (!state.groups) {
    body.append(placeholder("Themes"));
    return;
  }
  const themes = state.groups.filter((g) => g.kind === "theme");
  const list = h("div", { class: "theme-list" }, themes.map(themeSection));
  body.append(list);
  if (!themes.length) {
    body.append(h("p", { class: "empty" }, state.editor ? "No Themes yet. Press Edit to add one." : "No Themes yet."));
  }
  if (state.editing) body.append(newThemeForm());
  makeSortable(list, { draggable: ".theme", handle: ".theme-handle", onEnd: saveThemeOrder });
  fillValues(body);
}

async function saveThemeOrder() {
  const ids = $$("#themes-body .theme").map((s) => Number(s.dataset.gid));
  const themes = new Map(state.groups.filter((g) => g.kind === "theme").map((g) => [g.id, g]));
  state.groups = [...state.groups.filter((g) => g.kind !== "theme"), ...ids.map((id) => themes.get(id))];
  persist();
  try {
    await api("/api/themes/order", { method: "PUT", body: { ids } });
  } catch (err) {
    flash(err.message);
    loadGroups();
  }
}

function newThemeForm() {
  const name = h("input", { name: "name", placeholder: "New Theme name", maxlength: "60", required: true, "aria-label": "New Theme name" });
  const note = h("input", { name: "note", placeholder: "Why it matters (optional)", maxlength: "500", "aria-label": "New Theme note" });
  const form = h("form", { class: "new-theme" }, name, note, h("button", { class: "btn", type: "submit" }, "Add Theme"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/themes", { method: "POST", body: { name: name.value, note: note.value } });
      state.groups.push(r.group);
      persist();
      renderThemes();
      $(`form.add[data-gid="${r.group.id}"] input`)?.focus();
    } catch (err) {
      flash(err.message);
    }
  });
  return form;
}

async function deleteTheme(g) {
  if (!confirm(`Delete the ${g.name} Theme and its ${g.items.length} Symbol${g.items.length === 1 ? "" : "s"}?`)) return;
  try {
    await api(`/api/groups/${g.id}`, { method: "DELETE" });
    state.groups = state.groups.filter((x) => x !== g);
    indexMeta();
    persist();
    renderThemes();
  } catch (err) {
    flash(err.message);
  }
}

// --- Editing Symbols ----------------------------------------------------------------

function removeButton(g, item) {
  return h("button", {
    class: "del",
    type: "button",
    title: `Remove ${item.symbol}`,
    "aria-label": `Remove ${item.symbol} from ${g.name}`,
    onclick: async (e) => {
      e.stopPropagation();
      const idx = g.items.indexOf(item);
      if (idx < 0) return;
      g.items.splice(idx, 1);
      indexMeta();
      renderGroup(g);
      try {
        await api(`/api/groups/${g.id}/symbols/${item.id}`, { method: "DELETE" });
        persist();
      } catch (err) {
        g.items.splice(idx, 0, item);
        indexMeta();
        renderGroup(g);
        flash(err.message);
      }
    },
  }, "×");
}

function addForm(g) {
  const input = h("input", {
    name: "symbol",
    placeholder: "Yahoo symbol or FRED series ID",
    autocomplete: "off",
    autocapitalize: "characters",
    spellcheck: "false",
    maxlength: "24",
    "aria-label": `Add a Symbol to ${g.name}`,
  });
  const sub = g.kind === "market"
    ? h("select", { name: "subsection", "aria-label": "Market subsection" },
      h("option", { value: "" }, "Auto"), state.subsections.map((s) => h("option", { value: s }, SUB_LABELS[s] ?? s)))
    : null;
  const button = h("button", { class: "btn", type: "submit" }, "Add");
  const msg = h("p", { class: "add-msg", role: "status" });
  const suggestions = h("div", { class: "suggestions" });
  const form = h("form", { class: "add", dataset: { gid: g.id } }, input, sub, button, msg, suggestions);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const symbol = input.value.trim();
    if (!symbol) return;
    input.disabled = button.disabled = true;
    msg.className = "add-msg";
    msg.textContent = `Checking ${symbol.toUpperCase()} on Yahoo, then FRED…`;
    suggestions.replaceChildren();
    try {
      const r = await api(`/api/groups/${g.id}/symbols`, { method: "POST", body: { symbol, subsection: sub?.value || null } });
      g.items.push(r.item);
      if (r.quote) state.quotes[r.item.key] = r.quote;
      indexMeta();
      persist();
      renderGroup(g);
      const fresh = $(`form.add[data-gid="${g.id}"]`);
      if (fresh) {
        $(".add-msg", fresh).textContent = `Added ${r.item.symbol} (${r.item.source === "fred" ? "FRED" : "Yahoo"}).`;
        $("input", fresh).focus();
      }
      loadQuotes(); // new Symbol list -> new quotes URL -> fresh fetch
    } catch (err) {
      input.disabled = button.disabled = false;
      input.focus();
      msg.className = "add-msg error";
      msg.textContent = err.message;
      for (const s of err.data?.suggestions ?? []) {
        suggestions.append(h("button", {
          type: "button",
          onclick: () => {
            input.value = s.symbol;
            form.requestSubmit();
          },
        }, h("span", { class: "sym" }, s.symbol), [s.name, s.exchange].filter(Boolean).join(" · ")));
      }
    }
  });
  return form;
}

let sortables = [];
function makeSortable(el, opts) {
  sortables = sortables.filter((s) => {
    if (s.el?.isConnected) return true;
    s.destroy();
    return false;
  });
  if (!state.editing || !window.Sortable) return;
  sortables.push(window.Sortable.create(el, { animation: 150, handle: ".handle", ...opts }));
}

// --- Headlines -----------------------------------------------------------------------

function renderHeadlines() {
  const body = $("#headlines-body");
  body.replaceChildren();
  if (!state.headlines?.length) {
    body.append(state.headlinesError
      ? h("p", { class: "error-box" }, `Couldn't load headlines: ${state.headlinesError}`)
      : h("p", { class: "empty" }, "Loading headlines…"));
    return;
  }
  body.append(h("ol", { class: "news" }, state.headlines
    .filter((n) => /^https?:\/\//i.test(n.url))
    .map((n) => h("li", {},
      h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer" }, n.title),
      h("span", { class: "news-meta" }, `${n.sources.join(" · ")} · ${age(n.published)}`)))));
}

// --- Rendering and loading --------------------------------------------------------------

function placeholder(what) {
  return state.groupsError
    ? h("p", { class: "error-box" }, `Couldn't load the ${what}: ${state.groupsError}`)
    : h("p", { class: "empty" }, "Loading…");
}

function renderGroup(g) {
  if (g.kind === "market") renderMarket();
  else if (g.kind === "watchlist") renderWatchlist();
  else {
    const old = $(`#themes-body .theme[data-gid="${g.id}"]`);
    if (!old) return renderThemes();
    const fresh = themeSection(g);
    old.replaceWith(fresh);
    fillValues(fresh);
  }
}

function renderAll() {
  renderHeader();
  renderMarket();
  renderHeadlines();
  renderWatchlist();
  renderThemes();
}

function setEditing(on) {
  state.editing = Boolean(on && state.editor);
  renderAll();
}

let flashTimer;
function flash(message) {
  const notice = $("#notice");
  notice.hidden = false;
  notice.textContent = message;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(renderHeader, 6000);
}

async function loadGroups() {
  try {
    const r = await api("/api/groups");
    state.groups = r.groups;
    state.subsections = r.subsections ?? state.subsections;
    state.groupsError = null;
    indexMeta();
    persist();
  } catch (err) {
    state.groupsError = err.message;
  }
  renderAll();
}

let quotesSeq = 0;
let quotesTimer;
let lastQuotesAt = 0;
async function loadQuotes() {
  const refs = quoteRefs();
  if (!refs.length) return;
  const seq = ++quotesSeq;
  $("#refresh").classList.add("busy");
  try {
    const r = await api(`/api/quotes?${new URLSearchParams({ s: refs.join(",") })}`);
    if (seq !== quotesSeq) return;
    state.quotes = { ...state.quotes, ...r.quotes }; // keep a just-added Symbol's quote if this copy predates it
    state.quotesAsOf = r.as_of;
    state.market = r.market;
    state.stale = r.stale ?? [];
    state.errors = r.errors ?? {};
    state.quotesError = null;
    lastQuotesAt = Date.now();
    persist();
  } catch (err) {
    if (seq !== quotesSeq) return;
    state.quotesError = err.status === 503 ? "Yahoo and FRED didn't respond" : err.message || "network error";
    lastQuotesAt = Date.now() - OPEN_POLL / 2; // retry sooner
  } finally {
    if (seq === quotesSeq) $("#refresh").classList.remove("busy");
  }
  updateValues();
  scheduleQuotes();
}

function scheduleQuotes() {
  clearTimeout(quotesTimer);
  if (document.hidden) return;
  const every = state.market?.state === "open" ? OPEN_POLL : CLOSED_POLL;
  let wait = Math.max(5_000, every - (Date.now() - lastQuotesAt));
  const untilOpen = state.market?.next_open ? new Date(state.market.next_open) - Date.now() + 5_000 : Infinity;
  if (untilOpen > 0 && untilOpen < wait) wait = untilOpen; // catch the open
  quotesTimer = setTimeout(loadQuotes, wait);
}

let headlinesTimer;
let lastHeadlinesAt = 0;
async function loadHeadlines() {
  try {
    const r = await api("/api/headlines");
    state.headlines = r.items;
    state.headlinesAsOf = r.as_of;
    state.headlinesError = null;
    persist();
  } catch (err) {
    state.headlinesError = err.message;
  }
  lastHeadlinesAt = Date.now();
  renderHeadlines();
  clearTimeout(headlinesTimer);
  if (!document.hidden) headlinesTimer = setTimeout(loadHeadlines, HEADLINE_POLL);
}

function wire() {
  $("#refresh").addEventListener("click", () => {
    loadQuotes();
    loadHeadlines();
  });
  const dialog = $("#login");
  const form = $("#login-form");
  $("#login-btn").addEventListener("click", () => {
    $("#login-error").hidden = true;
    dialog.showModal();
    form.password.focus();
  });
  $("#login-cancel").addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/login", { method: "POST", body: { password: form.password.value } });
      form.reset();
      dialog.close();
      state.editor = true;
      setEditing(true);
    } catch (err) {
      const box = $("#login-error");
      box.textContent = err.message;
      box.hidden = false;
      form.password.select();
    }
  });
  $("#edit-btn").addEventListener("click", () => setEditing(!state.editing));
  $("#logout-btn").addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST" });
    } finally {
      state.editor = false;
      setEditing(false);
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      clearTimeout(quotesTimer);
      clearTimeout(headlinesTimer);
      return;
    }
    const every = state.market?.state === "open" ? OPEN_POLL : CLOSED_POLL;
    if (Date.now() - lastQuotesAt >= every) loadQuotes();
    else scheduleQuotes();
    if (Date.now() - lastHeadlinesAt >= HEADLINE_POLL) loadHeadlines();
    else headlinesTimer = setTimeout(loadHeadlines, HEADLINE_POLL - (Date.now() - lastHeadlinesAt));
  });
  // Relative times ("2h", "prices 6 min old") age while the page sits open.
  setInterval(() => {
    renderHeader();
    renderHeadlines();
  }, 60_000);
}

async function boot() {
  restore();
  wire();
  renderAll();
  api("/api/me")
    .then((r) => {
      state.editor = r.editor;
      state.editingEnabled = r.editing_enabled;
      renderControls();
    })
    .catch(() => {});
  const cachedRefs = quoteRefs().join(",");
  if (cachedRefs) loadQuotes(); // start with the cached Symbol list while Groups load
  loadHeadlines();
  await loadGroups();
  if (quoteRefs().join(",") !== cachedRefs) loadQuotes();
}

boot();
