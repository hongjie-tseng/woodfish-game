const actions = [
  ["start", "開始"],
  ["pause", "暫停"],
  ["resume", "繼續"],
  ["end", "結束"],
  ["reset", "重設功德"],
];
const statusLabels = { active: "進行中", paused: "暫停中", ended: "已結束" };
const HISTORY_POINTS = 60;
const history = { A: [], B: [] };
const counters = {};
const numberFormat = new Intl.NumberFormat("zh-TW");

function fmt(value) {
  return value == null ? "—" : numberFormat.format(value);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[character]));
}

function actionButtons(target) {
  return actions.map(([action, label]) =>
    `<button type="button" data-action="${action}" data-target="${target}">${label}</button>`
  ).join("");
}

/* ---------- Animated big numbers ---------- */
function showCount(element, value) {
  const text = fmt(Math.round(value));
  if (element.textContent === text) return;
  element.textContent = text;
  // CSS shrinks the font as the number gets longer so it always fits its card.
  element.style.setProperty("--len", Math.max(6, text.length));
}

function setCounter(element, key, target) {
  const counter = counters[key] ||= { shown: target, from: target, to: target, start: 0 };
  if (counter.element !== element) {
    counter.element = element;
    showCount(element, counter.shown);
  }
  if (target === counter.to) return;
  // A reset (number goes down) jumps immediately; increases count up smoothly.
  if (target < counter.shown) {
    Object.assign(counter, { shown: target, from: target, to: target });
    showCount(element, target);
    return;
  }
  Object.assign(counter, { from: counter.shown, to: target, start: performance.now() });
  element.classList.remove("bump");
  void element.offsetWidth;
  element.classList.add("bump");
  requestAnimationFrame(tickCounters);
}

function tickCounters(now) {
  let running = false;
  for (const counter of Object.values(counters)) {
    if (counter.shown === counter.to) continue;
    // The frame timestamp can be slightly older than counter.start, so clamp to 0..1.
    const progress = Math.min(1, Math.max(0, (now - counter.start) / 900));
    const eased = 1 - (1 - progress) ** 3;
    counter.shown = progress >= 1 ? counter.to : counter.from + (counter.to - counter.from) * eased;
    if (counter.element) showCount(counter.element, counter.shown);
    if (progress < 1) running = true;
  }
  if (running) requestAnimationFrame(tickCounters);
}

/* ---------- Sparkline ---------- */
function sparkPath(points) {
  if (points.length < 2) return { line: "", area: "" };
  const max = Math.max(5, ...points) * 1.15;
  const step = 100 / (HISTORY_POINTS - 1);
  const offset = (HISTORY_POINTS - points.length) * step;
  const coords = points.map((value, index) => [offset + index * step, 40 - (value / max) * 38]);
  const line = coords.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const area = `${line} L${coords.at(-1)[0].toFixed(2)},40 L${coords[0][0].toFixed(2)},40 Z`;
  return { line, area };
}

/* ---------- Team cards ---------- */
function teamCard(team) {
  const letter = escapeHtml(team.target);
  const name = escapeHtml(team.team_name || `${team.target} 隊`);
  if (!team.online) {
    return `<article class="team" data-team="${letter}" data-online="false">
      <div class="team__head">
        <h2 class="team__name"><span class="team__letter">${letter}</span>${name}</h2>
        <span class="pill pill--offline">連線失敗</span>
      </div>
      <p class="offline-detail">${escapeHtml(team.detail || "無法取得伺服器狀態")}</p>
    </article>`;
  }
  return `<article class="team" data-team="${letter}" data-online="true">
    <div class="team__head">
      <h2 class="team__name"><span class="team__letter">${letter}</span>${name}<span class="crown">領先</span></h2>
      <span class="pill" data-field="pill"></span>
    </div>
    <div class="team__round" data-field="round"></div>
    <div class="score"><small>全隊功德</small><strong data-field="team_taps">0</strong></div>
    <div class="live">
      <div class="live__rate"><small>即時敲擊</small><strong data-field="tps">—</strong><span>下/秒</span></div>
      <svg class="spark" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
        <path class="area" data-field="spark-area"></path><path class="line" data-field="spark-line"></path>
      </svg>
    </div>
    <div class="metrics">
      <div class="metric"><small>本回合功德</small><strong data-field="round_taps"></strong></div>
      <div class="metric"><small>近 60 秒</small><strong data-field="per_minute"></strong></div>
      <div class="metric"><small>請求（近 5 秒）</small><strong data-field="rps"></strong></div>
      <div class="metric"><small>累計請求</small><strong data-field="requests"></strong></div>
    </div>
    <p class="team__meta" data-field="meta"></p>
  </article>`;
}

function setText(card, name, value) {
  const element = card.querySelector(`[data-field="${name}"]`);
  if (element && element.textContent !== String(value)) element.textContent = value;
  return element;
}

function updateCard(card, team) {
  const status = team.round_status in statusLabels ? team.round_status : "unknown";
  const pill = setText(card, "pill", statusLabels[status] || team.round_status);
  pill.className = `pill pill--${status}`;
  setText(card, "round", team.round_name || "");
  setCounter(card.querySelector('[data-field="team_taps"]'), team.target, team.team_taps);
  setText(card, "tps", team.taps_per_second == null ? "—" : fmt(Math.round(team.taps_per_second)));
  setText(card, "round_taps", fmt(team.round_taps));
  setText(card, "per_minute", team.recent_rate_per_minute == null ? "測量中" : `${fmt(Math.round(team.recent_rate_per_minute))} 下`);
  setText(card, "rps", team.requests_per_second == null ? "測量中" : `${fmt(Math.round(team.requests_per_second))}/秒`);
  setText(card, "requests", fmt(team.tap_requests_since_reset ?? team.tap_requests_total));
  setText(card, "meta", `版本 v${team.version} · ${team.commit}`);
  const { line, area } = sparkPath(history[team.target] || []);
  card.querySelector('[data-field="spark-line"]').setAttribute("d", line);
  card.querySelector('[data-field="spark-area"]').setAttribute("d", area);
}

function renderTeams(teams) {
  const container = document.querySelector("#teams");
  let cards = [...container.querySelectorAll(".team")];
  const sameLayout = cards.length === teams.length && teams.every((team, index) =>
    cards[index].dataset.team === team.target && cards[index].dataset.online === String(team.online)
  );
  if (!sameLayout) {
    container.innerHTML = teams.map(teamCard).join("");
    cards = [...container.querySelectorAll(".team")];
  }
  teams.forEach((team, index) => { if (team.online) updateCard(cards[index], team); });
}

function recordHistory(teams) {
  for (const team of teams) {
    const points = history[team.target] ||= [];
    points.push(team.online ? Math.max(0, team.taps_per_second ?? 0) : 0);
    if (points.length > HISTORY_POINTS) points.shift();
  }
}

function renderTug(teams) {
  const byTarget = Object.fromEntries(teams.map((team) => [team.target, team]));
  const a = byTarget.A?.online ? byTarget.A.team_taps : 0;
  const b = byTarget.B?.online ? byTarget.B.team_taps : 0;
  const total = a + b;
  const shareA = total ? (a / total) * 100 : 50;
  document.querySelector("#tug-fill").style.width = `${shareA}%`;
  document.querySelector("#share-a").textContent = `A ${Math.round(shareA)}%`;
  document.querySelector("#share-b").textContent = `${Math.round(100 - shareA)}% B`;
  const lead = document.querySelector("#lead-text");
  lead.textContent = !total ? "尚未開始敲擊" : a === b ? "目前平手" : `${a > b ? "A" : "B"} 隊領先 ${fmt(Math.abs(a - b))} 功德`;
  lead.style.color = !total || a === b ? "" : `var(--${a > b ? "a" : "b"})`;
  document.querySelectorAll(".team").forEach((card) => {
    const leading = total > 0 && a !== b && card.dataset.team === (a > b ? "A" : "B");
    card.classList.toggle("is-leading", leading);
  });
  setCounter(document.querySelector("#grand-total"), "total", total);
}

/* ---------- Audit log ---------- */
function auditRow(entry) {
  const result = entry.success ? "成功" : `失敗：${entry.error_message || "未知錯誤"}`;
  return `<tr>
    <td>${escapeHtml(entry.timestamp)}</td>
    <td>${escapeHtml(entry.target)} / ${escapeHtml(entry.action)}</td>
    <td>${escapeHtml(entry.previous_status)} → ${escapeHtml(entry.new_status)}</td>
    <td>${escapeHtml(result)}</td>
    <td>${escapeHtml(entry.source)}</td>
  </tr>`;
}

async function refreshAuditLogs() {
  if (document.querySelector("#control-panel").hidden) return;
  const container = document.querySelector("#audit-logs");
  try {
    const response = await fetch("/api/admin/audit-logs?limit=50", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    container.innerHTML = data.records.length
      ? `<div class="audit-table-wrap"><table><thead><tr><th>時間</th><th>隊伍 / 操作</th><th>狀態</th><th>結果</th><th>來源</th></tr></thead><tbody>${data.records.map(auditRow).join("")}</tbody></table></div>`
      : "<p>尚無操作紀錄</p>";
  } catch (error) {
    container.textContent = `無法取得操作紀錄：${error.message}`;
  }
}

/* ---------- Polling ---------- */
async function refresh() {
  const status = document.querySelector("#overall-status");
  try {
    const response = await fetch("/api/admin/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const online = data.teams.filter((team) => team.online).length;
    recordHistory(data.teams);
    renderTeams(data.teams);
    renderTug(data.teams);
    status.textContent = online === 2 ? "A、B 已連線" : online === 1 ? "部分連線" : "兩隊皆離線";
    status.className = `status ${online === 2 ? "status--ok" : "status--error"}`;
  } catch (error) {
    status.textContent = "管理服務異常";
    status.className = "status status--error";
    document.querySelector("#teams").innerHTML = `<p>無法取得管理狀態：${escapeHtml(error.message)}</p>`;
  }
}

async function control(target, action) {
  if (action === "reset" && !window.confirm(`確定要清除${target === "ALL" ? " A、B 兩隊" : `${target} 隊`}的全隊功德與所有玩家個人功德嗎？`)) return;
  const response = await fetch(`/api/admin/control/${target}/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
  });
  const data = await response.json();
  const summary = data.results.map((result) =>
    `${result.target}：${result.success ? "成功" : `失敗（${result.detail || "未知錯誤"}）`}`
  ).join("\n");
  window.alert(`${data.overall === "success" ? "操作完成" : data.overall === "partial" ? "部分成功" : "操作失敗"}\n${summary}`);
  await refresh();
  await refreshAuditLogs();
}

/* ---------- Presentation controls ---------- */
function togglePanel(force) {
  const panel = document.querySelector("#control-panel");
  const open = force ?? panel.hidden;
  panel.hidden = !open;
  document.querySelector("#panel-toggle").setAttribute("aria-expanded", String(open));
  if (open) {
    refreshAuditLogs();
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.().catch(() => {});
}

function tickClock() {
  document.querySelector("#clock").textContent = new Date().toLocaleTimeString("zh-TW", { hour12: false });
}

document.querySelectorAll(".actions[data-target]").forEach((element) => {
  element.innerHTML = actionButtons(element.dataset.target);
});
document.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  control(button.dataset.target, button.dataset.action).catch((error) => window.alert(`操作失敗：${error.message}`));
});
document.querySelector("#panel-toggle").addEventListener("click", () => togglePanel());
document.querySelector("#fullscreen-toggle").addEventListener("click", toggleFullscreen);
document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest("input, textarea, select")) return;
  if (event.key === "c" || event.key === "C") togglePanel();
  if (event.key === "f" || event.key === "F") toggleFullscreen();
});

let refreshing = false;
async function refreshLive() {
  // Skip a tick instead of piling up requests when a game server is slow.
  if (refreshing || document.hidden) return;
  refreshing = true;
  try {
    await refresh();
  } finally {
    refreshing = false;
  }
}

tickClock();
refresh();
setInterval(tickClock, 1000);
setInterval(refreshLive, 1000);
setInterval(refreshAuditLogs, 5000);
