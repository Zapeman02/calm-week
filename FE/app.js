import { api } from "./api.js";

const SNAP = 15;
const DAY_MS = 864e5;
const HEARTBEAT_MS = 15000;
const TRAVEL_STEP = 15;
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const $ = (id) => document.getElementById(id);
const els = {
  label: $("week-label"), status: $("status"), tray: $("tray-items"), head: $("days-head"),
  gutter: $("gutter"), days: $("days"), layer: $("layer"), scroll: $("scroll"), popover: $("popover"),
  undo: $("undo"), arrange: $("arrange"),
};

let week = null;
let undoStack = [];
let drag = null;
let openId = null;
let ppm = 1;
let offline = false;
const nodes = new Map();

const pad = (n) => String(n).padStart(2, "0");
const hm = (text) => { const [h, m] = text.split(":").map(Number); return h * 60 + m; };
const clock = (min) => `${pad(Math.floor(min / 60) % 24)}:${pad(min % 60)}`;
const snap = (min) => Math.round(min / SNAP) * SNAP;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const duration = (min) => (min % 60 ? `${Math.floor(min / 60)}h${pad(min % 60)}` : `${min / 60}h`).replace(/^0h/, "");
const mondayMs = () => Date.parse(`${week.monday}T00:00Z`);
const gridStart = () => hm(week.template.gridStart);
const gridEnd = () => hm(week.template.gridEnd);
const category = (b) => week.template.categories[b.category] || week.template.categories.other;
const findBlock = (id) => week.blocks.find((b) => b.id === id);

function pos(start) {
  const [date, time] = start.split("T");
  return { day: Math.round((Date.parse(`${date}T00:00Z`) - mondayMs()) / DAY_MS), min: hm(time) };
}

function startOf(day, min) {
  const date = new Date(mondayMs() + day * DAY_MS).toISOString().slice(0, 10);
  return `${date}T${clock(min)}`;
}

function todayIndex() {
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const i = Math.round((today - mondayMs()) / DAY_MS);
  return i >= 0 && i < 7 ? i : -1;
}

// ---------- data changes ----------

function change(mutate) {
  undoStack.push(JSON.stringify(week.blocks));
  if (undoStack.length > 50) undoStack.shift();
  mutate();
  render();
  persist();
}

function persist() {
  api.save(week.id, week.blocks).then((res) => { week.sync = res.sync; renderStatus(); }).catch(goOffline);
}

function undo() {
  if (!undoStack.length) return;
  week.blocks = JSON.parse(undoStack.pop());
  openId = null;
  render();
  persist();
}

async function rearrange() {
  undoStack.push(JSON.stringify(week.blocks));
  openId = null;
  try {
    const res = await api.arrange(week.id);
    week.blocks = res.blocks;
    week.sync = res.sync;
    render();
  } catch (e) {
    goOffline();
  }
}

async function load(id) {
  try {
    week = await api.week(id || "current");
  } catch (e) {
    return goOffline();
  }
  undoStack = [];
  openId = null;
  nodes.forEach((n) => n.remove());
  nodes.clear();
  history.replaceState(null, "", `?week=${week.id}`);
  renderHeader();
  layout();
  render();
}

function goOffline() {
  offline = true;
  renderStatus();
}

// ---------- rendering ----------

function layout() {
  const total = gridEnd() - gridStart();
  const available = els.scroll.clientHeight - 16;
  ppm = Math.max(0.6, available / total);
  document.documentElement.style.setProperty("--ppm", `${ppm}px`);
  els.days.style.height = `${total * ppm}px`;
  els.gutter.innerHTML = "";
  for (let h = Math.ceil(gridStart() / 60) + 1; h < gridEnd() / 60; h++) {
    const label = document.createElement("div");
    label.style.top = `${(h * 60 - gridStart()) * ppm}px`;
    label.textContent = pad(h);
    els.gutter.append(label);
  }
}

function render() {
  renderHeader();
  renderTray();
  renderBlocks();
  renderPopover();
  renderStatus();
}

function renderHeader() {
  const first = new Date(mondayMs());
  const last = new Date(mondayMs() + 6 * DAY_MS);
  const fmt = (d, opts) => d.toLocaleDateString("en-GB", { timeZone: "UTC", ...opts });
  const range = first.getUTCMonth() === last.getUTCMonth()
    ? `${first.getUTCDate()}–${fmt(last, { day: "numeric", month: "short" })}`
    : `${fmt(first, { day: "numeric", month: "short" })} – ${fmt(last, { day: "numeric", month: "short" })}`;
  els.label.textContent = `Week ${Number(week.id.split("W")[1])} · ${range}`;

  const today = todayIndex();
  els.head.innerHTML = "<div></div>" + DAY_NAMES.map((name, i) => {
    const date = new Date(mondayMs() + i * DAY_MS).getUTCDate();
    const light = i === week.template.lightDay ? "<small>light day</small>" : "<small>&nbsp;</small>";
    return `<div class="${i === today ? "today" : ""}">${name} ${date}${light}</div>`;
  }).join("");

  [...els.days.querySelectorAll(".day-col")].forEach((c) => c.remove());
  for (let i = 0; i < 7; i++) {
    const col = document.createElement("div");
    col.className = "day-col" + (i === week.template.lightDay ? " light" : "") + (i === today ? " today" : "");
    col.dataset.day = i;
    els.days.insertBefore(col, els.layer);
  }
  els.undo.disabled = !undoStack.length;
  els.arrange.disabled = week.isPast;
  $("claude-open").disabled = week.isPast;
}

function renderTray() {
  const loose = week.blocks.filter((b) => b.type === "flexible" && !b.start && !(drag && drag.id === b.id && drag.start));
  els.tray.innerHTML = loose.length
    ? loose.map((b) => `<div class="tray-item" data-id="${b.id}" style="--c:${category(b).color}">${escapeHtml(b.title)}<span>${duration(b.minutes)}<button class="tray-x" data-drop aria-label="Remove from this week" title="Remove from this week">×</button></span></div>`).join("")
    : `<p class="tray-empty">Everything has a place.</p>`;
}

function effectiveBlocks() {
  const list = week.blocks.map((b) => (drag && drag.id === b.id ? { ...b, start: drag.start, minutes: drag.minutes } : b));
  if (drag && drag.mode === "create" && drag.moved) list.push(drag.preview);
  return list.filter((b) => b.start);
}

function lanes(blocks) {
  const byDay = new Map();
  for (const b of blocks) {
    const p = pos(b.start);
    const item = { b, day: p.day, lo: p.min, hi: p.min + b.minutes };
    if (!byDay.has(p.day)) byDay.set(p.day, []);
    byDay.get(p.day).push(item);
  }
  const result = [];
  for (const items of byDay.values()) {
    items.sort((a, b) => a.lo - b.lo || b.hi - a.hi);
    let cluster = [];
    let clusterEnd = -1;
    const flush = () => {
      const ends = [];
      for (const it of cluster) {
        let lane = ends.findIndex((end) => end <= it.lo);
        if (lane < 0) lane = ends.length;
        ends[lane] = it.hi;
        it.lane = lane;
      }
      cluster.forEach((it) => { it.lanes = ends.length; result.push(it); });
      cluster = [];
    };
    for (const it of items) {
      if (it.lo >= clusterEnd && cluster.length) flush();
      cluster.push(it);
      clusterEnd = Math.max(clusterEnd, it.hi);
    }
    if (cluster.length) flush();
  }
  return result;
}

function renderBlocks() {
  const seen = new Set();
  for (const { b, day, lo, lane, lanes: count } of lanes(effectiveBlocks())) {
    if (day < 0 || day > 6) continue;
    seen.add(b.id);
    let node = nodes.get(b.id);
    if (!node) {
      node = document.createElement("div");
      node.dataset.id = b.id;
      node.innerHTML = `<div class="travel before"></div><div class="body"><span class="title"></span><span class="time"></span></div><div class="resize"></div><div class="travel after"></div>`;
      els.layer.append(node);
      nodes.set(b.id, node);
    }
    const top = (lo - gridStart()) * ppm;
    const height = b.minutes * ppm;
    node.className = `block type-${b.type}` + (b.skipped ? " skipped" : "") + (b.id === openId ? " open" : "") + (height < 40 ? " short" : "");
    node.style.cssText = `--c:${category(b).color};top:${top}px;height:${height}px;` +
      `left:calc(${((day + lane / count) / 7) * 100}%);width:calc(${100 / 7 / count}%);`;
    node.querySelector(".title").textContent = b.title;
    node.querySelector(".time").textContent = `${clock(lo)}–${clock(lo + b.minutes)}${fitNote(b)}`;
    node.querySelector(".before").style.height = `${b.travelBefore * ppm}px`;
    node.querySelector(".after").style.height = `${b.travelAfter * ppm}px`;
  }
  for (const [id, node] of nodes) {
    if (!seen.has(id)) { node.remove(); nodes.delete(id); }
  }
  renderNowLine();
}

function fitNote(b) {
  if (b.partOf) return " · part 2";
  if (b.fullMinutes && week.blocks.some((x) => x.partOf === b.id)) return " · part 1";
  if (b.fullMinutes) return ` · shortened from ${duration(b.fullMinutes)}`;
  return "";
}

function renderNowLine() {
  let line = els.layer.querySelector(".now");
  const day = todayIndex();
  const now = new Date();
  const min = now.getHours() * 60 + now.getMinutes();
  if (day < 0 || min < gridStart()) return line && line.remove();
  if (!line) {
    line = document.createElement("div");
    line.className = "now";
    els.layer.append(line);
  }
  line.style.cssText = `top:${(min - gridStart()) * ppm}px;left:${(day / 7) * 100}%;width:${100 / 7}%`;
}

function overlaps(a, b) {
  const pa = pos(a.start), pb = pos(b.start);
  return pa.day === pb.day && pa.min < pb.min + b.minutes && pb.min < pa.min + a.minutes;
}

function renderStatus() {
  if (offline) {
    els.status.innerHTML = `<span class="soft-warn">Calm Week closed in the background. Reopen it to keep editing.</span>`;
    return;
  }
  if (week.isPast) {
    els.status.textContent = "Past week";
    return;
  }
  const flexible = week.blocks.filter((b) => b.type === "flexible" && !b.partOf);
  const placed = flexible.filter((b) => b.start).length;
  const busy = week.blocks.filter((b) => b.start && !b.skipped && b.type !== "protected");
  const free = week.blocks.filter((b) => b.start && b.category === "free");
  const freeOk = !free.some((f) => busy.some((b) => overlaps(f, b)));
  const parts = [
    `${placed}/${flexible.length} goals placed`,
    freeOk ? "free time protected" : `<span class="soft-warn">something overlaps free time</span>`,
    syncText(),
  ];
  const prefix = week.id === week.current ? "This week: " : "";
  els.status.innerHTML = prefix + parts.join(" · ");
}

function syncText() {
  const s = week.sync;
  if (!s.enabled) return "sync off";
  if (s.error) return "sync paused, will retry";
  if (!s.last) return "not synced yet";
  const minutes = Math.round((Date.now() - Date.parse(s.last)) / 60000);
  return minutes < 1 ? "synced just now" : `synced ${minutes} min ago`;
}

// ---------- popover ----------

function renderPopover() {
  const b = openId && findBlock(openId);
  const node = b && nodes.get(b.id);
  if (!b || !node) {
    els.popover.hidden = true;
    return;
  }
  const cats = Object.entries(week.template.categories)
    .map(([key, c]) => `<button class="chip ${key === b.category ? "on" : ""}" data-cat="${key}" style="--c:${c.color}">${c.name}</button>`).join("");
  const kind = {
    fixed: `<div class="seg"><button class="on">Fixed</button><button data-type="flexible">Flexible</button></div><p class="note">Fixed: Rearrange never moves it.</p>`,
    flexible: `<div class="seg"><button data-type="fixed">Fixed</button><button class="on">Flexible</button></div><p class="note">Flexible: Rearrange may move it.</p>`,
    suggested: `<button class="ghost" data-skip>${b.skipped ? "Bring it back" : "Skip this one"}</button><p class="note">From TimeEdit.</p>`,
    protected: `<p class="note">Protected. Rearrange never touches it.</p>`,
  }[b.type];
  const cap = b.type === "protected" ? "" : `<div class="row">Daily cap<div class="seg small">
      <button class="${b.noCap ? "" : "on"}" data-nocap="0">Counts</button><button class="${b.noCap ? "on" : ""}" data-nocap="1">Free time</button></div></div>`;
  const stepper = (key, label) =>
    `<div class="row">${label}<div class="stepper"><button data-step="${key}" data-d="-1">−</button><span>${b[key]} min</span><button data-step="${key}" data-d="1">+</button></div></div>`;
  els.popover.innerHTML = `
    <input value="${escapeHtml(b.title)}" ${b.type === "suggested" ? "readonly" : ""} aria-label="Title">
    ${b.type === "suggested" ? "" : `<div class="chips">${cats}</div>`}
    ${kind}
    ${cap}
    ${stepper("travelBefore", "Travel before")}
    ${stepper("travelAfter", "Travel after")}
    ${b.type === "fixed" || b.type === "flexible" ? `<div class="row">${canSplit(b) ? `<button class="ghost" data-split>Split in two</button>` : "<span></span>"}<button class="ghost" data-duplicate>Duplicate</button></div>` : ""}
    <div class="foot">${b.type === "suggested" ? "<span></span>" : `<button class="ghost" data-delete>Delete</button>`}<button data-close>Done</button></div>`;
  els.popover.hidden = false;

  const rect = node.getBoundingClientRect();
  const width = 260;
  const left = rect.right + 8 + width < innerWidth ? rect.right + 8 : rect.left - width - 8;
  els.popover.style.left = `${clamp(left, 8, innerWidth - width - 8)}px`;
  els.popover.style.top = `${clamp(rect.top, 8, innerHeight - els.popover.offsetHeight - 8)}px`;
}

els.popover.addEventListener("click", (e) => {
  const b = findBlock(openId);
  const t = e.target.closest("button");
  if (!b || !t) return;
  if (t.dataset.cat) change(() => { b.category = t.dataset.cat; });
  else if (t.dataset.type) change(() => { b.type = t.dataset.type; });
  else if ("skip" in t.dataset) change(() => { b.skipped = !b.skipped; });
  else if (t.dataset.nocap) change(() => { if (t.dataset.nocap === "1") b.noCap = true; else delete b.noCap; });
  else if (t.dataset.step) change(() => { b[t.dataset.step] = clamp(b[t.dataset.step] + Number(t.dataset.d) * TRAVEL_STEP, 0, 120); });
  else if ("split" in t.dataset) change(() => split(b));
  else if ("duplicate" in t.dataset) change(() => { openId = duplicate(b).id; });
  else if ("delete" in t.dataset) { openId = null; change(() => { week.blocks = week.blocks.filter((x) => x !== b); }); }
  else if ("close" in t.dataset) { openId = null; render(); }
});

function canSplit(b) {
  return (b.type === "fixed" || b.type === "flexible") && b.minutes >= 2 * SNAP && !b.partOf && !week.blocks.some((x) => x.partOf === b.id);
}

function split(b) {
  const first = Math.ceil(b.minutes / 2 / SNAP) * SNAP;
  const p = pos(b.start);
  week.blocks.push({ ...b, id: crypto.randomUUID().slice(0, 8), start: startOf(p.day, p.min + first), minutes: b.minutes - first, travelBefore: 0, partOf: b.id });
  b.fullMinutes = b.fullMinutes || b.minutes;
  b.minutes = first;
  b.travelAfter = 0;
}

function duplicate(b) {
  const p = pos(b.start);
  const { partOf, fullMinutes, ...rest } = b;
  const minutes = fullMinutes || b.minutes;
  const copy = { ...rest, id: crypto.randomUUID().slice(0, 8), minutes, start: startOf(p.day, clamp(p.min + b.minutes, gridStart(), gridEnd() - minutes)) };
  week.blocks.push(copy);
  return copy;
}

els.popover.addEventListener("change", (e) => {
  const b = findBlock(openId);
  const title = e.target.value.trim();
  if (b && title && title !== b.title) change(() => { b.title = title; });
});

els.popover.addEventListener("keydown", (e) => {
  if (e.key === "Enter") e.target.blur();
});

// ---------- dragging ----------

function pointerSpot(e) {
  const rect = els.days.getBoundingClientRect();
  const inside = e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top - 20 && e.clientY <= rect.bottom;
  return {
    inside,
    day: clamp(Math.floor(((e.clientX - rect.left) / rect.width) * 7), 0, 6),
    min: gridStart() + (e.clientY - rect.top) / ppm,
  };
}

function beginDrag(e, mode, b, extra = {}) {
  e.preventDefault();
  drag = { mode, id: b && b.id, x: e.clientX, y: e.clientY, moved: false, start: b && b.start, minutes: b ? b.minutes : 60, ...extra };
}

els.layer.addEventListener("pointerdown", (e) => {
  const node = e.target.closest(".block");
  if (!node || week.isPast) return;
  const b = findBlock(node.dataset.id);
  if (b.type === "suggested") return beginDrag(e, "click", b);
  const spot = pointerSpot(e);
  const mode = e.target.classList.contains("resize") ? "resize" : "move";
  beginDrag(e, mode, b, { grab: spot.min - pos(b.start).min });
});

els.days.addEventListener("pointerdown", (e) => {
  if (!e.target.classList.contains("day-col") || week.isPast || openId) return;
  const spot = pointerSpot(e);
  const anchor = clamp(Math.floor(spot.min / SNAP) * SNAP, gridStart(), gridEnd() - 30);
  beginDrag(e, "create", null, { day: spot.day, anchor });
});

els.tray.addEventListener("pointerdown", (e) => {
  const item = e.target.closest(".tray-item");
  if (!item || week.isPast) return;
  if (e.target.closest("[data-drop]")) {
    const b = findBlock(item.dataset.id);
    return change(() => { week.blocks = week.blocks.filter((x) => x !== b); });
  }
  const b = findBlock(item.dataset.id);
  const ghost = item.cloneNode(true);
  ghost.classList.add("ghost-item");
  ghost.style.width = `${item.offsetWidth}px`;
  document.body.append(ghost);
  beginDrag(e, "move", b, { grab: 30, ghost });
  moveGhost(e);
});

function moveGhost(e) {
  if (!drag.ghost) return;
  drag.ghost.style.left = `${e.clientX}px`;
  drag.ghost.style.top = `${e.clientY}px`;
  drag.ghost.style.display = drag.start ? "none" : "";
}

document.addEventListener("pointermove", (e) => {
  if (!drag) return;
  if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 4) return;
  drag.moved = true;
  document.body.classList.add("dragging");
  const spot = pointerSpot(e);
  if (drag.mode === "move") {
    const min = clamp(snap(spot.min - drag.grab), gridStart(), gridEnd() - drag.minutes);
    drag.start = spot.inside ? startOf(spot.day, min) : null;
  } else if (drag.mode === "resize") {
    const startMin = pos(drag.start).min;
    drag.minutes = clamp(snap(spot.min) - startMin, SNAP, gridEnd() - startMin);
  } else if (drag.mode === "create") {
    const end = clamp(snap(spot.min), gridStart(), gridEnd());
    const lo = Math.min(drag.anchor, end);
    const minutes = Math.max(30, Math.abs(end - drag.anchor));
    drag.preview = { id: "new", title: "New", category: "other", type: "fixed", start: startOf(drag.day, lo), minutes, travelBefore: 0, travelAfter: 0, skipped: false };
  }
  moveGhost(e);
  renderBlocks();
  renderTray();
});

document.addEventListener("pointerup", () => {
  if (!drag) return;
  const d = drag;
  drag = null;
  document.body.classList.remove("dragging");
  if (d.ghost) d.ghost.remove();
  const b = d.id && findBlock(d.id);

  if (!d.moved) {
    if (d.mode === "create") {
      const block = newBlock(startOf(d.day, d.anchor), 60);
      openId = block.id;
      change(() => week.blocks.push(block));
      focusTitle();
    } else if (b && b.start) {
      openId = openId === b.id ? null : b.id;
      render();
    } else {
      render();
    }
    return;
  }
  if (d.mode === "create") {
    const block = newBlock(d.preview.start, d.preview.minutes);
    openId = block.id;
    change(() => week.blocks.push(block));
    return focusTitle();
  }
  const unchanged = d.start === b.start && d.minutes === b.minutes;
  const toTray = d.mode === "move" && !d.start;
  if (unchanged || (toTray && b.type !== "flexible")) return render();
  change(() => {
    b.start = d.start;
    b.minutes = d.minutes;
  });
});

function newBlock(start, minutes) {
  return { id: crypto.randomUUID().slice(0, 8), title: "New", category: "other", type: "fixed", start, minutes, travelBefore: 0, travelAfter: 0, skipped: false, goal: null };
}

function focusTitle() {
  const input = els.popover.querySelector("input");
  if (input) { input.focus(); input.select(); }
}

// ---------- settings ----------

let goals = [];
let cap = 420;
let protectedTimes = [];
let openGoal = -1;
const FIT = { flex: "Split or shorten", shorten: "Only shorten", whole: "Keep whole" };
const PRIORITY = { 1: "High", 2: "Normal", 3: "Low" };
const PRESETS = { any: "Any time", morning: "Morning 08:30–12", afternoon: "Afternoon 12–17", evening: "Evening 17–21" };

function daysText(days) {
  const key = [...days].sort().join("");
  return { "0123456": "every day", "01234": "weekdays", "56": "weekends", "012345": "Mon–Sat" }[key]
    || days.map((d) => DAY_NAMES[d]).join(" ");
}

function goalSummary(g) {
  const time = g.prefer in PRESETS ? PRESETS[g.prefer].split(" ")[0].toLowerCase() : g.prefer.replace("-", "–");
  const travel = (g.travelBefore || 0) + (g.travelAfter || 0);
  const parts = [`${g.count}× ${duration(g.minutes)}`, daysText(g.days), g.prefer === "any" ? "any time" : time, ...(travel ? [`+${travel}m travel`] : [])];
  return parts.join(" · ");
}

function goalEditor(g) {
  const custom = !(g.prefer in PRESETS);
  const [from, to] = custom ? g.prefer.split("-") : ["14:00", "18:00"];
  const options = Object.entries(PRESETS).map(([k, label]) => `<option value="${k}" ${k === g.prefer ? "selected" : ""}>${label}</option>`).join("")
    + `<option value="custom" ${custom ? "selected" : ""}>Custom…</option>`;
  const days = DAY_NAMES.map((name, d) => `<button type="button" class="day ${g.days.includes(d) ? "on" : ""}" data-day="${d}">${name[0]}</button>`).join("");
  const priority = Object.entries(PRIORITY).map(([k, label]) => `<button type="button" class="${Number(k) === g.priority ? "on" : ""}" data-priority="${k}">${label}</button>`).join("");
  return `
    <div class="goal-edit">
      <div class="goal-row"><input value="${escapeHtml(g.title)}" placeholder="Activity name" aria-label="Activity name"><button type="button" class="ghost" data-remove>Remove</button></div>
      <div class="goal-row"><span class="label">Sessions</span>
        <div class="stepper"><button type="button" data-k="count" data-d="-1">−</button><span>${g.count}×</span><button type="button" data-k="count" data-d="1">+</button></div>
        <div class="stepper"><button type="button" data-k="minutes" data-d="-30">−</button><span>${duration(g.minutes)}</span><button type="button" data-k="minutes" data-d="30">+</button></div>
      </div>
      <div class="goal-row"><span class="label">Days</span><div class="days-pick">${days}</div></div>
      <div class="goal-row"><span class="label">Time</span><select aria-label="Preferred time">${options}</select>
        ${custom ? `<input type="time" step="1800" data-edge="0" value="${from}" aria-label="From"><span>–</span><input type="time" step="1800" data-edge="1" value="${to}" aria-label="To">` : ""}
      </div>
      <div class="goal-row"><span class="label">Priority</span><div class="seg">${priority}</div></div>
      <div class="goal-row"><span class="label">Travel</span>
        <div class="stepper"><button type="button" data-k="travelBefore" data-d="-15">−</button><span>${g.travelBefore || 0}m before</span><button type="button" data-k="travelBefore" data-d="15">+</button></div>
        <div class="stepper"><button type="button" data-k="travelAfter" data-d="-15">−</button><span>${g.travelAfter || 0}m after</span><button type="button" data-k="travelAfter" data-d="15">+</button></div>
      </div>
      <div class="goal-row"><span class="label">Daily cap</span><div class="seg">
        <button type="button" class="${g.noCap ? "" : "on"}" data-nocap="0">Counts</button>
        <button type="button" class="${g.noCap ? "on" : ""}" data-nocap="1">Free time</button></div></div>
      <div class="goal-row"><span class="label">If full</span><div class="seg">${Object.entries(FIT).map(([k, label]) =>
        `<button type="button" class="${k === g.fit ? "on" : ""}" data-fit="${k}">${label}</button>`).join("")}</div></div>
    </div>`;
}

async function openSettings() {
  try {
    const data = await api.settings();
    $("timeedit").value = data.timeeditUrl;
    goals = data.goals;
    cap = data.dailyCapMinutes;
    protectedTimes = data.protected;
    openGoal = -1;
    $("place-start").value = data.placeStart;
    $("place-end").value = data.placeEnd;
    delete $("settings-reset").dataset.armed;
    $("settings-reset").textContent = "Reset this week";
    $("settings-reset").disabled = week.isPast;
    $("claude-wishes").value = data.claudeWishes;
  } catch (e) {
    return goOffline();
  }
  openId = null;
  render();
  renderGoals();
  $("settings").hidden = false;
}

function renderGoals() {
  $("cap").textContent = duration(cap);
  $("protected-rows").innerHTML = protectedTimes.map((p, i) => `
    <div class="goal-row" data-i="${i}">
      <span class="name">${escapeHtml(p.title)}</span>
      <input type="time" step="900" value="${p.start}" aria-label="${escapeHtml(p.title)} start">
      <div class="stepper"><button type="button" data-d="-15">−</button><span>${duration(p.minutes)}</span><button type="button" data-d="15">+</button></div>
    </div>`).join("");
  $("goal-rows").innerHTML = goals.map((g, i) => `
    <div class="goal ${i === openGoal ? "open" : ""}" data-i="${i}">
      <button type="button" class="goal-head" data-toggle>
        <span class="dot" style="--c:${g.color || "var(--muted)"}"></span>
        <span class="name">${escapeHtml(g.title) || "New activity"}</span>
        <span class="summary">${goalSummary(g)}</span>
        ${g.priority === 2 ? "" : `<span class="badge">${PRIORITY[g.priority]}</span>`}
      </button>
      ${i === openGoal ? goalEditor(g) : ""}
    </div>`).join("");
}

$("goal-rows").addEventListener("click", (e) => {
  const t = e.target.closest("button");
  const row = e.target.closest(".goal");
  if (!t || !row) return;
  const g = goals[row.dataset.i];
  if ("toggle" in t.dataset) openGoal = openGoal === Number(row.dataset.i) ? -1 : Number(row.dataset.i);
  else if ("remove" in t.dataset) { goals.splice(row.dataset.i, 1); openGoal = -1; }
  else if (t.dataset.priority) g.priority = Number(t.dataset.priority);
  else if (t.dataset.fit) g.fit = t.dataset.fit;
  else if (t.dataset.nocap) g.noCap = t.dataset.nocap === "1";
  else if (t.dataset.day) {
    const d = Number(t.dataset.day);
    g.days = g.days.includes(d) ? g.days.filter((x) => x !== d) : [...g.days, d].sort();
  }
  else if (t.dataset.k === "count") g.count = clamp(g.count + Number(t.dataset.d), 1, 14);
  else if (t.dataset.k?.startsWith("travel")) g[t.dataset.k] = clamp((g[t.dataset.k] || 0) + Number(t.dataset.d), 0, 120);
  else g.minutes = clamp(g.minutes + Number(t.dataset.d), 30, 480);
  renderGoals();
});

$("goal-rows").addEventListener("input", (e) => {
  const g = goals[e.target.closest(".goal").dataset.i];
  if (e.target.tagName === "SELECT") {
    g.prefer = e.target.value === "custom" ? "14:00-18:00" : e.target.value;
    renderGoals();
  } else if (e.target.dataset.edge) {
    const edges = g.prefer.split("-");
    edges[e.target.dataset.edge] = e.target.value || edges[e.target.dataset.edge];
    g.prefer = edges.join("-");
  } else {
    g.title = e.target.value;
    e.target.closest(".goal").querySelector(".goal-head .name").textContent = g.title || "New activity";
  }
});

$("protected-rows").addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  const p = protectedTimes[t.closest(".goal-row").dataset.i];
  p.minutes = clamp(p.minutes + Number(t.dataset.d), 15, 360);
  renderGoals();
});

$("protected-rows").addEventListener("input", (e) => {
  if (e.target.value) protectedTimes[e.target.closest(".goal-row").dataset.i].start = e.target.value;
});

$("cap-steps").addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  cap = clamp(cap + Number(t.dataset.d), 60, 900);
  renderGoals();
});

$("goal-add").addEventListener("click", () => {
  goals.push({ title: "", count: 1, minutes: 60, days: [0, 1, 2, 3, 4, 5, 6], prefer: "any", priority: 2, fit: "flex", travelBefore: 0, travelAfter: 0 });
  openGoal = goals.length - 1;
  renderGoals();
  $("goal-rows").querySelector(".goal:last-child input").focus();
});

function settingsData() {
  return { timeeditUrl: $("timeedit").value, dailyCapMinutes: cap, claudeWishes: $("claude-wishes").value, protected: protectedTimes, goals,
    placeStart: $("place-start").value, placeEnd: $("place-end").value };
}

$("settings-reset").addEventListener("click", async (e) => {
  const button = e.currentTarget;
  if (!button.dataset.armed) {
    button.dataset.armed = "1";
    button.textContent = "Click again to reset";
    return;
  }
  try {
    await api.saveSettings(settingsData());
    await api.resetWeek(week.id);
  } catch (err) {
    return goOffline();
  }
  await load(week.id);
  $("settings").hidden = true;
});

$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api.saveSettings(settingsData());
  } catch (err) {
    return goOffline();
  }
  await load(week.id);
  $("settings").hidden = true;
});

$("settings-cancel").addEventListener("click", () => { $("settings").hidden = true; });

// ---------- claude ----------

const CLAUDE_NOTE = $("claude-note").textContent;

function openClaude() {
  openId = null;
  render();
  $("claude-note").textContent = CLAUDE_NOTE;
  $("claude").hidden = false;
  $("wish").focus();
}

$("claude-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ask = $("claude-ask");
  ask.disabled = true;
  $("claude-note").textContent = "Claude is thinking. This can take a minute…";
  try {
    const res = await api.claude(week.id, $("wish").value.trim());
    if ($("claude").hidden) return;
    change(() => { week.blocks = res.blocks; });
    $("claude").hidden = true;
    $("wish").value = "";
  } catch (err) {
    $("claude-note").textContent = "Claude couldn't answer right now. Your week is unchanged.";
  }
  ask.disabled = false;
});

$("claude-cancel").addEventListener("click", () => { $("claude").hidden = true; });

// ---------- wiring ----------

$("prev").addEventListener("click", () => load(week.prev));
$("next").addEventListener("click", () => load(week.next));
$("today").addEventListener("click", () => load("current"));
els.undo.addEventListener("click", undo);
els.arrange.addEventListener("click", rearrange);
$("settings-open").addEventListener("click", openSettings);
$("claude-open").addEventListener("click", openClaude);

document.addEventListener("pointerdown", (e) => {
  if (openId && !els.popover.contains(e.target) && !e.target.closest(".block")) {
    openId = null;
    render();
  }
});

document.addEventListener("keydown", (e) => {
  const sheet = document.querySelector(".sheet-backdrop:not([hidden])");
  if (sheet) { if (e.key === "Escape" && !$("claude-ask").disabled) sheet.hidden = true; return; }
  const typing = e.target.tagName === "INPUT";
  if ((e.metaKey || e.ctrlKey) && e.key === "z" && !typing) { e.preventDefault(); undo(); }
  else if (e.key === "Escape") { openId = null; render(); }
  else if (!typing && !openId && e.key === "ArrowLeft") load(week.prev);
  else if (!typing && !openId && e.key === "ArrowRight") load(week.next);
});

window.addEventListener("resize", () => { if (week) { layout(); render(); } });

setInterval(() => {
  api.heartbeat()
    .then((sync) => { offline = false; if (week) { week.sync = sync; renderStatus(); renderNowLine(); } })
    .catch(goOffline);
}, HEARTBEAT_MS);

load(new URLSearchParams(location.search).get("week"));
