const actions = [
  ["start", "開始"],
  ["pause", "暫停"],
  ["resume", "繼續"],
  ["end", "結束"],
  ["reset", "重設功德"],
];

function actionButtons(target) {
  return actions.map(([action, label]) =>
    `<button type="button" data-action="${action}" data-target="${target}">${label}</button>`
  ).join("");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[character]));
}

function teamCard(team) {
  const online = team.online;
  return `<article class="team-card">
    <div class="team-card__head">
      <h2>${escapeHtml(team.team_name || `${team.target} 隊`)}</h2>
      <span class="status ${online ? "status--ok" : "status--error"}">${online ? "已連線" : "連線失敗"}</span>
    </div>
    ${online ? `<div class="team-card__state">${escapeHtml(team.round_name)} · ${escapeHtml(team.round_status)}</div>
      <div class="metrics">
        <div class="metric"><small>全隊功德</small><strong>${team.team_taps}</strong></div>
        <div class="metric"><small>本回合</small><strong>${team.round_taps}</strong></div>
        <div class="metric"><small>近 60 秒</small><strong>${team.recent_rate_per_minute == null ? "待測量" : `${team.recent_rate_per_minute}/分`}</strong></div>
      </div>
      <div class="meta">版本 v${escapeHtml(team.version)} · ${escapeHtml(team.commit)}</div>` :
      `<div class="meta">${escapeHtml(team.detail || "無法取得伺服器狀態")}</div>`}
    <div class="actions" data-target="${team.target}">${actionButtons(team.target)}</div>
  </article>`;
}

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

async function refresh() {
  const status = document.querySelector("#overall-status");
  try {
    const response = await fetch("/api/admin/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const online = data.teams.filter((team) => team.online).length;
    document.querySelector("#teams").innerHTML = data.teams.map(teamCard).join("");
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

document.querySelector('[data-target="ALL"]').innerHTML = actionButtons("ALL");
document.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  control(button.dataset.target, button.dataset.action).catch((error) => window.alert(`操作失敗：${error.message}`));
});

refresh();
refreshAuditLogs();
setInterval(refresh, 5000);
setInterval(refreshAuditLogs, 5000);
