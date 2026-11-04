const playerKey = "woodfish-player-id";
const playerId = localStorage.getItem(playerKey) || crypto.randomUUID();
localStorage.setItem(playerKey, playerId);
let audioContext;
let woodfishBuffer;
const soundKey = "woodfish-sound";
// Temporary picker so testers can compare the synthesized woodfish sounds before one is chosen.
const soundFiles = {
  small: "woodfish-small.wav",
  medium: "woodfish-medium.wav",
  large: "woodfish-large.wav",
  original: "woodfish-hit.wav",
};
const soundBuffers = new Map();
let soundChoice = readSoundChoice();
let previewChoice = null;
let meritSequence = 0;
const tapAttempts = new Map();
const tapMetrics = [];
const maxTapAttempts = 3;
let audioWarningShown = false;
const $ = (id) => document.getElementById(id);
const personalKey = "woodfish-personal-taps";
// Several server workers answer from slightly different snapshots and responses can arrive out of
// order, so the phone counts its own taps and keeps the team total from moving backwards.
// reset_marker only grows, and grows on every merit reset, which clears the local count.
let personal = loadPersonal();
let teamShown = 0;
let roundStatus = null;

function loadPersonal() {
  try {
    const saved = JSON.parse(localStorage.getItem(personalKey));
    if (saved && Number.isInteger(saved.count) && Number.isInteger(saved.marker)) return saved;
  } catch {}
  return { marker: null, count: 0 };
}

function savePersonal() {
  try {
    localStorage.setItem(personalKey, JSON.stringify(personal));
  } catch {}
}

function showPersonal() {
  $("personal-taps").textContent = personal.count;
}

function setConnection(text, status) {
  $("connection").textContent = text;
  $("connection").className = `connection connection--${status}`;
}

function setServerState(status) {
  roundStatus = status;
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
  if (personal.marker === null || stats.reset_marker > personal.marker) {
    // The first visit keeps the score the server already has; a later reset starts from zero.
    personal = { marker: stats.reset_marker, count: personal.marker === null ? stats.personal_taps : 0 };
    teamShown = 0;
    savePersonal();
  }
  if (stats.reset_marker === personal.marker) teamShown = Math.max(teamShown, stats.team_taps);
  showPersonal();
  $("team-taps").textContent = teamShown;
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
      if (item.countedMarker !== undefined && item.countedMarker === personal.marker && personal.count > 0) {
        personal.count -= 1;
        savePersonal();
        showPersonal();
      }
    }
  }
}

function prepareAudio() {
  if (audioContext) return true;
  try {
    // iOS 17+: use the media channel so the ringer switch and ringer volume no longer mute Web Audio.
    if (navigator.audioSession) navigator.audioSession.type = "playback";
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("Web Audio API is unavailable");
    audioContext = new AudioContextClass();
    loadSound(soundChoice);
    return true;
  } catch {
    if (!audioWarningShown) {
      console.warn("Woodfish audio is unavailable");
      audioWarningShown = true;
    }
    return false;
  }
}

function readSoundChoice() {
  try {
    const saved = localStorage.getItem(soundKey);
    if (saved && saved in soundFiles) return saved;
  } catch {}
  return "medium";
}

function loadSound(choice) {
  if (soundBuffers.has(choice)) {
    if (choice === soundChoice) woodfishBuffer = soundBuffers.get(choice);
    return;
  }
  soundBuffers.set(choice, null);
  fetch(`/static/assets/${soundFiles[choice]}`)
    .then((response) => {
      if (!response.ok) throw new Error(`Audio HTTP ${response.status}`);
      return response.arrayBuffer();
    })
    .then((data) => audioContext.decodeAudioData(data))
    .then((buffer) => {
      soundBuffers.set(choice, buffer);
      if (choice !== soundChoice) return;
      woodfishBuffer = buffer;
      if (previewChoice === choice) {
        previewChoice = null;
        playWoodfishSound();
      }
    })
    .catch(() => {
      soundBuffers.delete(choice);
      if (!audioWarningShown) {
        console.warn("Woodfish audio could not be decoded");
        audioWarningShown = true;
      }
    });
}

function selectSound(choice) {
  if (!(choice in soundFiles)) return;
  soundChoice = choice;
  try {
    localStorage.setItem(soundKey, choice);
  } catch {}
  woodfishBuffer = soundBuffers.get(choice) || null;
  if (!prepareAudio()) return;
  resumeAudio();
  if (woodfishBuffer) {
    playWoodfishSound();
  } else {
    previewChoice = choice;
    loadSound(choice);
  }
}

function resumeAudio() {
  if (!prepareAudio()) return;
  // iOS reports "interrupted" after locking the screen, switching apps or notifications, not only "suspended".
  if (audioContext.state === "running") return;
  audioContext.resume().catch(() => {
    if (audioContext && audioContext.state !== "running") audioContext.close().catch(() => {});
    audioContext = null;
  });
}

function playWoodfishSound() {
  if (!prepareAudio()) return null;
  try {
    resumeAudio();
    if (!woodfishBuffer || !audioContext) return null;
    const source = audioContext.createBufferSource();
    const gain = audioContext.createGain();
    source.buffer = woodfishBuffer;
    gain.gain.value = .65;
    source.connect(gain).connect(audioContext.destination);
    source.start();
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
  if (roundStatus !== "paused" && roundStatus !== "ended") {
    // Counted right away; taken back if the server finally rejects this tap.
    personal.count += 1;
    item.countedMarker = personal.marker;
    savePersonal();
    showPersonal();
  }
  showMerit();
  sendTap(item);
});
refresh();
loadVersion();
setInterval(refresh, 2000);
prepareAudio();
$("sound-choice").value = soundChoice;
$("sound-choice").addEventListener("change", (event) => selectSound(event.target.value));
// iOS only unlocks audio on some gesture events, so retry on every one of them.
for (const type of ["touchend", "pointerup", "click", "keydown"]) {
  document.addEventListener(type, resumeAudio, { passive: true });
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") resumeAudio();
});
