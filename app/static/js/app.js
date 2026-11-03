const playerKey = "woodfish-player-id";
const playerId = localStorage.getItem(playerKey) || crypto.randomUUID();
localStorage.setItem(playerKey, playerId);
const pending = [];
let sending = false;
let muted = false;
let audioContext;
const monkQuotes = ["你笑甚麼？", "好玩嗎？", "敲慢一點，老衲頭很暈", "功德不是這樣刷的喔", "施主，手下留情！", "又來？"];
const $ = (id) => document.getElementById(id);

async function loadScene() {
  const response = await fetch("/static/assets/monk-scene.svg", { signal: AbortSignal.timeout(10000) });
  if (!response.ok) {
    throw new Error(`Scene asset failed: ${response.status}`);
  }
  $("scene-mount").innerHTML = await response.text();
}

function setConnection(text, status) {
  $("connection").textContent = text;
  $("connection").className = `connection connection--${status}`;
}

function render(stats) {
  $("personal-taps").textContent = stats.personal_taps;
  $("team-taps").textContent = stats.team_taps;
  $("round-taps").textContent = stats.round_taps;
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
  } catch {
    setConnection("暫時離線", "error");
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
    $("tap-area").setAttribute("aria-label", monkQuotes[Math.floor(Math.random() * monkQuotes.length)]);
  }
  pending.push({ tap_id: crypto.randomUUID(), player_id: playerId });
  drain();
});
$("sound-toggle").addEventListener("click", () => {
  muted = !muted;
  $("sound-toggle").textContent = muted ? "🔇 音效關" : "🔊 音效開";
  $("sound-toggle").setAttribute("aria-pressed", String(muted));
});
loadScene().catch((error) => {
  console.error(error);
  setConnection("畫面載入異常", "error");
});
refresh();
setInterval(refresh, 2000);
