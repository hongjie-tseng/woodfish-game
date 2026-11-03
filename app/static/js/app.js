const playerKey = "woodfish-player-id";
const playerId = localStorage.getItem(playerKey) || crypto.randomUUID();
localStorage.setItem(playerKey, playerId);
const pending = [];
let sending = false;
const $ = (id) => document.getElementById(id);

function setConnection(text, status) {
  $("connection").textContent = text;
  $("connection").className = `status status--${status}`;
}

function render(stats) {
  $("personal-taps").textContent = stats.personal_taps;
  $("team-taps").textContent = stats.team_taps;
  $("round-taps").textContent = stats.round_taps;
  $("round-label").textContent = `${stats.round_name} · ${stats.round_status === "active" ? "進行中" : "已結束"}`;
}

async function load(url, options = {}) {
  const response = await fetch(url, { ...options, signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function refresh() {
  try {
    const [config, stats] = await Promise.all([
      load("/api/config"),
      load(`/api/stats?player_id=${encodeURIComponent(playerId)}`),
    ]);
    $("team-name").textContent = config.team_name;
    document.documentElement.style.setProperty("--team-color", config.theme_color);
    render(stats);
    setConnection("已連線", "ok");
  } catch {
    setConnection("連線異常", "error");
  }
}

async function drain() {
  if (sending || pending.length === 0) return;
  sending = true;
  const item = pending[0];
  try {
    const result = await load("/api/tap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(item),
    });
    pending.shift();
    render(result);
    setConnection("已連線", "ok");
    $("message").textContent = pending.length ? `已確認，還有 ${pending.length} 次等待中` : "敲擊已確認";
  } catch {
    setConnection("暫時離線", "error");
    $("message").textContent = "敲擊尚未確認，將自動重試";
    await new Promise((resolve) => setTimeout(resolve, 1000));
  } finally {
    sending = false;
    drain();
  }
}

$("woodfish").addEventListener("pointerdown", () => {
  $("woodfish").classList.add("is-tapped");
  setTimeout(() => $("woodfish").classList.remove("is-tapped"), 100);
  pending.push({ tap_id: crypto.randomUUID(), player_id: playerId });
  drain();
});
refresh();
setInterval(refresh, 2000);
