const playerKey = "woodfish-player-id";
const playerId = localStorage.getItem(playerKey) || crypto.randomUUID();
localStorage.setItem(playerKey, playerId);
let muted = false;
let audioContext;
let noiseBuffer;
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
    setConnection("已連線", "ok");
  } catch {
    setConnection("連線異常", "error");
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
    setConnection("已連線", "ok");
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
  if (audioContext) return true;
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("Web Audio API is unavailable");
    audioContext = new AudioContextClass();
    noiseBuffer = audioContext.createBuffer(1, audioContext.sampleRate * .22, audioContext.sampleRate);
    const samples = noiseBuffer.getChannelData(0);
    for (let index = 0; index < samples.length; index += 1) {
      samples[index] = (Math.random() * 2 - 1) * Math.exp(-index / (audioContext.sampleRate * .018));
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
  if (muted) return null;
  if (!prepareAudio()) return null;
  try {
    if (audioContext.state === "suspended") {
      audioContext.resume().catch(() => {
        if (!audioWarningShown) {
          console.warn("Woodfish audio context could not resume");
          audioWarningShown = true;
        }
      });
    }
    window.__woodfishAudioState = audioContext.state;
    const now = audioContext.currentTime + .005;
    const output = audioContext.createGain();
    const compressor = audioContext.createDynamicsCompressor();
    compressor.threshold.setValueAtTime(-18, now);
    compressor.knee.setValueAtTime(12, now);
    compressor.ratio.setValueAtTime(5, now);
    compressor.attack.setValueAtTime(.001, now);
    compressor.release.setValueAtTime(.08, now);
    output.gain.setValueAtTime(.8, now);
    output.connect(compressor).connect(audioContext.destination);

    const transient = audioContext.createBufferSource();
    const transientFilter = audioContext.createBiquadFilter();
    const transientGain = audioContext.createGain();
    transient.buffer = noiseBuffer;
    transientFilter.type = "bandpass";
    transientFilter.frequency.setValueAtTime(1800, now);
    transientFilter.Q.setValueAtTime(.9, now);
    transientGain.gain.setValueAtTime(.001, now);
    transientGain.gain.linearRampToValueAtTime(.22, now + .002);
    transientGain.gain.exponentialRampToValueAtTime(.001, now + .095);
    transient.connect(transientFilter).connect(transientGain).connect(output);
    transient.start(now);
    transient.stop(now + .11);

    [520, 840, 1320].forEach((frequency, index) => {
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      oscillator.type = index === 2 ? "sine" : "triangle";
      oscillator.frequency.setValueAtTime(frequency * (1 + (Math.random() - .5) * .025), now);
      gain.gain.setValueAtTime(.001, now);
      gain.gain.linearRampToValueAtTime([.16, .1, .055][index], now + .003);
      gain.gain.exponentialRampToValueAtTime(.001, now + [.19, .16, .13][index]);
      oscillator.connect(gain).connect(output);
      oscillator.start(now);
      oscillator.stop(now + .21);
    });
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
$("sound-toggle").addEventListener("click", () => {
  muted = !muted;
  $("sound-toggle").querySelector("span").textContent = muted ? "音效關" : "音效開";
  $("sound-toggle").setAttribute("aria-pressed", String(muted));
});
refresh();
setInterval(refresh, 2000);
prepareAudio();
