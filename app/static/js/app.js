const playerKey = "woodfish-player-id";
const playerId = localStorage.getItem(playerKey) || crypto.randomUUID();
localStorage.setItem(playerKey, playerId);
const woodfishAudioUrl = "/static/assets/woodfish-hit.wav";
const woodfishAudioPool = [];
let woodfishAudioIndex = 0;
let meritSequence = 0;
const tapAttempts = new Map();
const tapMetrics = [];
const maxTapAttempts = 3;
let audioWarningShown = false;
const $ = (id) => document.getElementById(id);

function setConnection(text, status) {
  $("connection").textContent = text;
  $("connection").className = `connection connection--${status}`;
}

function setServerState(roundStatus) {
  if (roundStatus === "active") {
    setConnection("已連線", "ok");
  } else if (roundStatus === "paused") {
    setConnection("未開始", "pending");
  } else if (roundStatus === "ended") {
    setConnection("已結束", "pending");
  } else {
    setConnection("狀態未知", "pending");
  }
}

function render(stats) {
  $("personal-taps").textContent = stats.personal_taps;
  $("team-taps").textContent = stats.team_taps;
}

async function load(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  } finally {
    clearTimeout(timeout);
  }
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
    setServerState(config.round_status);
  } catch {
    setConnection("連線異常", "error");
  }

}

async function loadVersion() {
  try {
    const version = await load("/api/version", { cache: "no-store" });
    $("version-info").textContent = `v${version.version} · ${version.commit}`;
  } catch {
    $("version-info").textContent = "vunknown · unknown";
  }
}

async function sendTap(item) {
  const startedAt = performance.now();
  item.attempt = (tapAttempts.get(item.tap_id) || 0) + 1;
  tapAttempts.set(item.tap_id, item.attempt);
  try {
    const result = await load("/api/tap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tap_id: item.tap_id, player_id: item.player_id }),
    });
    tapAttempts.delete(item.tap_id);
    item.responseAt = performance.now();
    tapMetrics.push({
      tapId: item.tap_id,
      animationDelay: item.animationAt - item.startedAt,
      soundDelay: item.soundAt - item.startedAt,
      requestRoundTrip: item.responseAt - startedAt,
      confirmationDelay: item.responseAt - item.startedAt,
    });
    window.__woodfishTapMetrics = tapMetrics.slice(-20);
    render(result);
    setServerState(result.round_status);
  } catch {
    setConnection("暫時離線", "error");
    if (item.attempt < maxTapAttempts) {
      setTimeout(() => sendTap(item), 500 * item.attempt);
    } else {
      tapAttempts.delete(item.tap_id);
      console.warn("Woodfish tap request failed after retries", item.tap_id);
    }
  }
}

function prepareAudio() {
  if (woodfishAudioPool.length) return true;
  try {
    for (let index = 0; index < 4; index += 1) {
      const audio = new Audio(woodfishAudioUrl);
      audio.preload = "auto";
      audio.playsInline = true;
      audio.volume = .65;
      audio.setAttribute("aria-hidden", "true");
      woodfishAudioPool.push(audio);
    }
    return true;
  } catch {
    if (!audioWarningShown) {
      console.warn("Woodfish audio is unavailable");
      audioWarningShown = true;
    }
    return false;
  }
}

function playWoodfishSound() {
  if (!prepareAudio()) return null;
  try {
    const audio = woodfishAudioPool[woodfishAudioIndex];
    woodfishAudioIndex = (woodfishAudioIndex + 1) % woodfishAudioPool.length;
    audio.pause();
    audio.currentTime = 0;
    const playback = audio.play();
    if (playback) {
      void playback.catch(() => {
        if (!audioWarningShown) {
          console.warn("Woodfish audio could not be started");
          audioWarningShown = true;
        }
      });
    }
    return performance.now();
  } catch {
    if (!audioWarningShown) {
      console.warn("Woodfish audio could not be started");
      audioWarningShown = true;
    }
    return null;
  }
}

function showMerit() {
  const merit = document.createElement("span");
  merit.className = "merit";
  merit.textContent = "功德 +1";
  merit.style.fontSize = `${1.98 + Math.random() * (5.94 - 1.98)}rem`;
  merit.style.setProperty("--merit-rise", `${67.5 + Math.random() * 157.5}px`);
  merit.style.left = `${26 + (meritSequence++ % 3) * 9}%`;
  $("merit-layer").appendChild(merit);
  setTimeout(() => merit.remove(), 700);
}

$("tap-area").addEventListener("pointerdown", (event) => {
  event.preventDefault();
  const startedAt = performance.now();
  $("tap-area").classList.remove("is-hitting");
  void $("tap-area").offsetWidth;
  $("tap-area").classList.add("is-hitting");
  const animationAt = performance.now();
  const soundAt = playWoodfishSound() || performance.now();
  const item = {
    tap_id: crypto.randomUUID(),
    player_id: playerId,
    startedAt,
    animationAt,
    soundAt,
  };
  showMerit();
  sendTap(item);
});
refresh();
loadVersion();
setInterval(refresh, 2000);
prepareAudio();
