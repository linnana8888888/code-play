// audio.mjs — WebAudio SFX + procedural music
// No external files, no imports. Works from file:// and localhost.

let AC = null;          // AudioContext, created lazily on init()
let masterGain = null;  // master bus
let musicBus = null;    // sub-bus for music (lower gain)
let noiseBuffer = null; // pre-baked 1s white noise buffer
let _muted = false;
let musicState = null;  // { intervalId, padGain, stopFn }

// ─── guard: return true if audio not ready ───────────────────────────────────
const noop = () => {};
function notReady() { return AC === null; }

// ─── noise buffer factory (generated once at init) ───────────────────────────
function makeNoise(ac) {
  const len = ac.sampleRate;
  const buf = ac.createBuffer(1, len, ac.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
  return buf;
}

// ─── helper: one-shot oscillator with gain envelope ──────────────────────────
// type: 'sine'|'square'|'sawtooth'|'triangle'
// attack/decay in seconds, freqEnd optional for sweep
function tone(freq, dur, type = 'sine', vol = 0.3, freqEnd = null) {
  if (notReady()) return;
  const t = AC.currentTime;
  const osc = AC.createOscillator();
  const g = AC.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t);
  if (freqEnd !== null) osc.frequency.exponentialRampToValueAtTime(freqEnd, t + dur);
  g.gain.setValueAtTime(0.001, t);
  g.gain.linearRampToValueAtTime(vol, t + 0.005);
  g.gain.exponentialRampToValueAtTime(0.001, t + dur);
  osc.connect(g); g.connect(masterGain);
  osc.start(t); osc.stop(t + dur + 0.01);
  osc.onended = () => { osc.disconnect(); g.disconnect(); };
}

// ─── helper: noise burst through a biquad filter ────────────────────────────
function noise(dur, filterType, freqStart, freqEnd, vol = 0.3) {
  if (notReady()) return;
  const t = AC.currentTime;
  const src = AC.createBufferSource();
  src.buffer = noiseBuffer;
  src.loop = true;
  const filt = AC.createBiquadFilter();
  filt.type = filterType;
  filt.frequency.setValueAtTime(freqStart, t);
  if (freqEnd !== null) filt.frequency.exponentialRampToValueAtTime(freqEnd, t + dur);
  const g = AC.createGain();
  g.gain.setValueAtTime(vol, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + dur);
  src.connect(filt); filt.connect(g); g.connect(masterGain);
  src.start(t); src.stop(t + dur + 0.01);
  src.onended = () => { src.disconnect(); filt.disconnect(); g.disconnect(); };
}

// ─── SFX implementations ─────────────────────────────────────────────────────

function shot() {
  if (notReady()) return;
  // airy fart plop: noise lowpass sweep + 140Hz sine pluck
  noise(0.08, 'lowpass', 800, 200, 0.25);
  tone(140, 0.06, 'sine', 0.15);
}

function impact() {
  if (notReady()) return;
  // splat: noise click + 300Hz square blip
  noise(0.06, 'lowpass', 1200, 400, 0.2);
  tone(300, 0.06, 'square', 0.12);
}

function reload() {
  if (notReady()) return;
  // rising triad: 440→660→880 sine, 100ms each
  const steps = [440, 660, 880];
  steps.forEach((f, i) => {
    setTimeout(() => tone(f, 0.09, 'sine', 0.18), i * 100);
  });
}

function dash() {
  if (notReady()) return;
  // whoosh: noise with high-pass opening up
  noise(0.18, 'highpass', 200, 3000, 0.22);
  tone(180, 0.18, 'sine', 0.08, 80);
}

function hurt() {
  if (notReady()) return;
  // descending square 400→200Hz over 150ms
  tone(400, 0.15, 'square', 0.2, 200);
  noise(0.1, 'bandpass', 600, 300, 0.1);
}

function pickup() {
  if (notReady()) return;
  // classic blip: 880 then 1320Hz
  tone(880, 0.06, 'sine', 0.2);
  setTimeout(() => tone(1320, 0.06, 'sine', 0.2), 70);
}

function levelUp() {
  if (notReady()) return;
  // C-E-G-C' arpeggio with harmonics, ~175ms per note
  const notes = [261.63, 329.63, 392, 523.25];
  notes.forEach((f, i) => {
    setTimeout(() => {
      tone(f, 0.16, 'sine', 0.2);
      tone(f * 2, 0.12, 'triangle', 0.07); // harmonic
    }, i * 175);
  });
}

function waveStart() {
  if (notReady()) return;
  // low drone sweep
  tone(80, 0.4, 'sawtooth', 0.15, 160);
  noise(0.35, 'lowpass', 400, 800, 0.1);
}

function death() {
  if (notReady()) return;
  // descending sad saw C-B-A-F#, 200ms per note
  const notes = [261.63, 246.94, 220, 185.00];
  notes.forEach((f, i) => {
    setTimeout(() => tone(f, 0.19, 'sawtooth', 0.18), i * 200);
  });
}

function comboTier(n) {
  if (notReady()) return;
  // bell: sine with short attack, exp decay; freq rises with tier
  const base = 660;
  const freq = Math.min(base + 220 * n, 2500);
  const fifth = freq * 1.5;
  const t = AC.currentTime;
  [freq, fifth].forEach((f, idx) => {
    const osc = AC.createOscillator();
    const g = AC.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(f, t);
    g.gain.setValueAtTime(0.001, t);
    g.gain.linearRampToValueAtTime(idx === 0 ? 0.22 : 0.1, t + 0.01);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
    osc.connect(g); g.connect(masterGain);
    osc.start(t); osc.stop(t + 0.52);
    osc.onended = () => { osc.disconnect(); g.disconnect(); };
  });
}

// ─── MUSIC ────────────────────────────────────────────────────────────────────
// Chord data: [root Hz, ...interval ratios] for each chord in progression
// Scheduling: AudioContext.currentTime-based, loop repeating every 4 bars

const MUSIC_CONFIGS = [
  // Level 0 – Desert Dunes: I–V–vi–IV in C major, 110 BPM
  {
    bpm: 110,
    chords: [
      [261.63, 1, 1.25, 1.5],   // C maj
      [392.00, 1, 1.25, 1.5],   // G maj
      [220.00, 1, 1.2, 1.5],    // A min
      [349.23, 1, 1.25, 1.5],   // F maj
    ],
    bassNotes: [130.81, 196.00, 110.00, 174.61],
    padType: 'triangle',
    filterFreq: 2000,
    kick: false,
    bassBeats: [0], // beat indices per bar to play bass
  },
  // Level 1 – Porcelain Lab: I–iii–IV–V in F major, 120 BPM
  {
    bpm: 120,
    chords: [
      [349.23, 1, 1.25, 1.5],   // F maj
      [440.00, 1, 1.2, 1.5],    // A min
      [466.16, 1, 1.25, 1.5],   // Bb maj
      [523.25, 1, 1.25, 1.5],   // C maj
    ],
    bassNotes: [174.61, 220.00, 233.08, 261.63],
    padType: 'sine',
    filterFreq: 3500,
    kick: false,
    bassBeats: [0],
  },
  // Level 2 – Sewer Depths: i–VI–III–VII in A minor, 100 BPM
  {
    bpm: 100,
    chords: [
      [220.00, 1, 1.2, 1.5],    // A min
      [349.23, 1, 1.25, 1.5],   // F maj
      [261.63, 1, 1.25, 1.5],   // C maj
      [392.00, 1, 1.25, 1.5],   // G maj
    ],
    bassNotes: [110.00, 174.61, 130.81, 196.00],
    padType: 'sawtooth',
    filterFreq: 800,
    kick: true,
    bassBeats: [0, 2], // beats 0 and 2 per bar
  },
];

function scheduleBar(cfg, padGain, barStart, chordIdx) {
  if (notReady() || !padGain) return;
  const beatsPerBar = 4;
  const secPerBeat = 60 / cfg.bpm;
  const secPerBar = beatsPerBar * secPerBeat;
  const chord = cfg.chords[chordIdx % cfg.chords.length];
  const bassHz = cfg.bassNotes[chordIdx % cfg.bassNotes.length];

  // Pad: two oscillators (detuned) through shared filter
  chord.slice(1).forEach((ratio, idx) => {
    const freq = chord[0] * ratio;
    [0, 7].forEach(detune => {          // slight detune for warmth
      const osc = AC.createOscillator();
      const g = AC.createGain();
      const filt = AC.createBiquadFilter();
      filt.type = 'lowpass';
      filt.frequency.value = cfg.filterFreq;
      osc.type = idx === 0 ? cfg.padType : 'triangle';
      osc.frequency.value = freq;
      osc.detune.value = detune;
      g.gain.setValueAtTime(0.001, barStart);
      g.gain.linearRampToValueAtTime(0.35, barStart + 0.05);
      g.gain.setValueAtTime(0.35, barStart + secPerBar - 0.08);
      g.gain.linearRampToValueAtTime(0.001, barStart + secPerBar);
      osc.connect(filt); filt.connect(g); g.connect(padGain);
      osc.start(barStart); osc.stop(barStart + secPerBar + 0.02);
      osc.onended = () => { osc.disconnect(); filt.disconnect(); g.disconnect(); };
    });
  });

  // Bass on configured beats
  cfg.bassBeats.forEach(beat => {
    const bt = barStart + beat * secPerBeat;
    const osc = AC.createOscillator();
    const g = AC.createGain();
    osc.type = 'sine';
    osc.frequency.value = bassHz;
    g.gain.setValueAtTime(0.001, bt);
    g.gain.linearRampToValueAtTime(0.5, bt + 0.02);
    g.gain.exponentialRampToValueAtTime(0.001, bt + secPerBeat * 0.8);
    osc.connect(g); g.connect(padGain);
    osc.start(bt); osc.stop(bt + secPerBeat);
    osc.onended = () => { osc.disconnect(); g.disconnect(); };
  });

  // Kick on beat 0 for sewer level
  if (cfg.kick) {
    const kt = barStart;
    const osc = AC.createOscillator();
    const g = AC.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(150, kt);
    osc.frequency.exponentialRampToValueAtTime(40, kt + 0.08);
    g.gain.setValueAtTime(0.6, kt);
    g.gain.exponentialRampToValueAtTime(0.001, kt + 0.12);
    osc.connect(g); g.connect(padGain);
    osc.start(kt); osc.stop(kt + 0.13);
    osc.onended = () => { osc.disconnect(); g.disconnect(); };
  }
}

function startMusic(levelIdx) {
  if (notReady()) return;
  stopMusic(); // stop any current track first

  const cfg = MUSIC_CONFIGS[levelIdx] || MUSIC_CONFIGS[0];
  const beatsPerBar = 4;
  const secPerBar = (60 / cfg.bpm) * beatsPerBar;

  const padGain = AC.createGain();
  padGain.gain.value = 1.0;
  padGain.connect(musicBus);

  let chordIdx = 0;
  let nextBarStart = AC.currentTime;

  function tick() {
    // Schedule ahead: 2 bars at a time
    while (nextBarStart < AC.currentTime + secPerBar * 2) {
      scheduleBar(cfg, padGain, nextBarStart, chordIdx);
      chordIdx = (chordIdx + 1) % cfg.chords.length;
      nextBarStart += secPerBar;
    }
  }

  tick();
  const intervalId = setInterval(tick, secPerBar * 1000 * 0.5);

  musicState = {
    intervalId,
    padGain,
    stopFn: () => {
      clearInterval(intervalId);
      const t = AC.currentTime;
      padGain.gain.setValueAtTime(padGain.gain.value, t);
      padGain.gain.linearRampToValueAtTime(0, t + 0.2);
      setTimeout(() => { try { padGain.disconnect(); } catch (_) {} }, 300);
    },
  };
}

function stopMusic() {
  if (musicState) {
    musicState.stopFn();
    musicState = null;
  }
}

// ─── MUTE ─────────────────────────────────────────────────────────────────────
function setMuted(bool) {
  _muted = bool;
  localStorage.setItem('bsg_mute', bool ? '1' : '0');
  if (!masterGain) return;
  const t = AC.currentTime;
  masterGain.gain.cancelScheduledValues(t);
  masterGain.gain.setValueAtTime(masterGain.gain.value, t);
  masterGain.gain.linearRampToValueAtTime(bool ? 0 : 0.25, t + 0.04);
}

function isMuted() { return _muted; }

// ─── INIT ─────────────────────────────────────────────────────────────────────
function init() {
  if (AC) return; // already initialised
  AC = new (window.AudioContext || window.webkitAudioContext)();
  masterGain = AC.createGain();
  masterGain.gain.value = 0.25;
  masterGain.connect(AC.destination);
  musicBus = AC.createGain();
  musicBus.gain.value = 0.08;
  musicBus.connect(masterGain);
  noiseBuffer = makeNoise(AC);

  // restore mute state
  const saved = localStorage.getItem('bsg_mute');
  if (saved === '1') {
    _muted = true;
    masterGain.gain.value = 0;
  }
}

// ─── EXPORT ───────────────────────────────────────────────────────────────────
export const sfx = {
  init,
  shot, impact, reload, dash, hurt,
  pickup, levelUp, waveStart, death,
  comboTier,
  startMusic, stopMusic,
  setMuted, isMuted,
};

// dev smoke test (uncomment to test in browser console):
// sfx.init(); sfx.shot(); setTimeout(() => sfx.levelUp(), 500);
// setTimeout(() => sfx.startMusic(0), 1000); setTimeout(() => sfx.stopMusic(), 8000);
