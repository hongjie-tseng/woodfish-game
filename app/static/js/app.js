const playerKey = "woodfish-player-id";
const playerId = localStorage.getItem(playerKey) || crypto.randomUUID();
localStorage.setItem(playerKey, playerId);
const pending = [];
let sending = false;
let muted = false;
let audioContext;
const monkQuotes = ["你笑甚麼？", "好玩嗎？", "敲慢一點，老衲頭很暈", "功德不是這樣刷的喔", "施主，手下留情！", "又來？"];
const $ = (id) => document.getElementById(id);

function setConnection(text, status) {
  $("connection").textContent = text;
  $("connection").className = `connection connection--${status}`;
}

function render(stats) {
  $("personal-taps").textContent = stats.personal_taps;
  $("team-taps").textContent = stats.team_taps;
  $("round-taps").textContent = stats.round_taps;
  if (stats.round_name) {
    $("round-label").dataset.roundName = stats.round_name;
  }
  const roundName = $("round-label").dataset.roundName || "目前回合";
  $("round-label").textContent = `${roundName} · ${stats.round_status === "active" ? "進行中" : "已結束"}`;
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

function playWoodfishSound() {
  if (muted) return;
  try {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    audioContext.resume();
    const now = audioContext.currentTime;
    [145, 215].forEach((frequency, index) => {
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      oscillator.type = index ? "triangle" : "sine";
      oscillator.frequency.setValueAtTime(frequency, now);
      oscillator.frequency.exponentialRampToValueAtTime(frequency * .48, now + .22);
      gain.gain.setValueAtTime(index ? .12 : .2, now);
      gain.gain.exponentialRampToValueAtTime(.001, now + .24);
      oscillator.connect(gain).connect(audioContext.destination);
      oscillator.start(now);
      oscillator.stop(now + .26);
    });
  } catch {
    // Audio is an enhancement; it must never block a tap request.
  }
}

function showMerit() {
  const merit = document.createElement("span");
  merit.className = "merit";
  merit.textContent = "功德 +1";
  merit.style.left = `${35 + Math.random() * 30}%`;
  $("merit-layer").appendChild(merit);
  setTimeout(() => merit.remove(), 950);
}

$("tap-area").addEventListener("pointerdown", () => {
  $("tap-area").classList.remove("is-hitting");
  void $("tap-area").offsetWidth;
  $("tap-area").classList.add("is-hitting");
  playWoodfishSound();
  showMerit();
  if (pending.length >= 8 && (pending.length % 5 === 0 || Math.random() < .18)) {
    $("message").textContent = monkQuotes[Math.floor(Math.random() * monkQuotes.length)];
  } else {
    $("message").textContent = "功德 +1，和尚表示頭很痛";
  }
  pending.push({ tap_id: crypto.randomUUID(), player_id: playerId });
  drain();
});
$("sound-toggle").addEventListener("click", () => {
  muted = !muted;
  $("sound-toggle").textContent = muted ? "🔇 音效關" : "🔊 音效開";
  $("sound-toggle").setAttribute("aria-pressed", String(muted));
});
refresh();
setInterval(refresh, 2000);
