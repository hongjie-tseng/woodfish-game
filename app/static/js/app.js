const playerKey = "woodfish-player-id";
const playerId = localStorage.getItem(playerKey) || crypto.randomUUID();
localStorage.setItem(playerKey, playerId);
const pending = [];
let sending = false;
let muted = false;
let audioContext;
let noiseBuffer;
let meritSequence = 0;
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
    if (!noiseBuffer) {
      noiseBuffer = audioContext.createBuffer(1, audioContext.sampleRate * .22, audioContext.sampleRate);
      const samples = noiseBuffer.getChannelData(0);
      for (let index = 0; index < samples.length; index += 1) {
        samples[index] = (Math.random() * 2 - 1) * Math.exp(-index / (audioContext.sampleRate * .018));
      }
    }
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
  } catch {
    // Audio is an enhancement; it must never block a tap request.
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

$("tap-area").addEventListener("pointerdown", () => {
  $("tap-area").classList.remove("is-hitting");
  void $("tap-area").offsetWidth;
  $("tap-area").classList.add("is-hitting");
  setTimeout(playWoodfishSound, 155);
  showMerit();
  pending.push({ tap_id: crypto.randomUUID(), player_id: playerId });
  drain();
});
$("sound-toggle").addEventListener("click", () => {
  muted = !muted;
  $("sound-toggle").querySelector("span").textContent = muted ? "音效關" : "音效開";
  $("sound-toggle").setAttribute("aria-pressed", String(muted));
});
refresh();
setInterval(refresh, 2000);
