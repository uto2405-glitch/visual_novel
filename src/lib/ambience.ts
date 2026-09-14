/**
 * 앰비언스 — 전부 WebAudio 즉석 합성. 외부 파일·네트워크 요청 없음.
 *
 * 장면의 sfx("rain" | "wind" | "night")를 시사실이 따라가며 크로스페이드한다.
 * 마스터 토글이 꺼져 있으면 아무 소리도 내지 않는다.
 */

export type SfxKind = "rain" | "wind" | "night";

export const SFX_KINDS: { id: SfxKind; label: string }[] = [
  { id: "rain", label: "🌧 비" },
  { id: "wind", label: "🍃 바람" },
  { id: "night", label: "🌙 밤" },
];

export function isSfxKind(v: unknown): v is SfxKind {
  return v === "rain" || v === "wind" || v === "night";
}

interface Layer {
  kind: SfxKind;
  stop: () => void;
}

let ctx: AudioContext | null = null;
let current: Layer | null = null;
let masterOn = false;

function audio(): AudioContext {
  ctx = ctx ?? new AudioContext();
  void ctx.resume();
  return ctx;
}

function noiseBuffer(ac: AudioContext, brown: boolean): AudioBuffer {
  const len = ac.sampleRate * 2;
  const buf = ac.createBuffer(1, len, ac.sampleRate);
  const d = buf.getChannelData(0);
  let last = 0;
  for (let i = 0; i < len; i++) {
    const white = Math.random() * 2 - 1;
    if (brown) {
      last = (last + 0.02 * white) / 1.02;
      d[i] = last * 3.2;
    } else {
      d[i] = white;
    }
  }
  return buf;
}

/** 비 — 낮은 웅웅거림 + 옅은 빗발 */
function buildRain(ac: AudioContext, out: GainNode): () => void {
  const low = ac.createBufferSource();
  low.buffer = noiseBuffer(ac, true);
  low.loop = true;
  const lp = ac.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 620;
  const lg = ac.createGain();
  lg.gain.value = 0.16;
  low.connect(lp).connect(lg).connect(out);

  const high = ac.createBufferSource();
  high.buffer = noiseBuffer(ac, false);
  high.loop = true;
  const hp = ac.createBiquadFilter();
  hp.type = "highpass";
  hp.frequency.value = 3200;
  const hg = ac.createGain();
  hg.gain.value = 0.03;
  high.connect(hp).connect(hg).connect(out);

  low.start();
  high.start();
  return () => {
    try {
      low.stop();
      high.stop();
    } catch {
      /* noop */
    }
  };
}

/** 바람 — 브라운 노이즈 + 천천히 흔들리는 밴드패스 */
function buildWind(ac: AudioContext, out: GainNode): () => void {
  const src = ac.createBufferSource();
  src.buffer = noiseBuffer(ac, true);
  src.loop = true;
  const bp = ac.createBiquadFilter();
  bp.type = "bandpass";
  bp.frequency.value = 400;
  bp.Q.value = 0.6;
  const g = ac.createGain();
  g.gain.value = 0.22;
  // LFO가 바람의 숨결을 만든다
  const lfo = ac.createOscillator();
  lfo.frequency.value = 0.13;
  const lfoGain = ac.createGain();
  lfoGain.gain.value = 220;
  lfo.connect(lfoGain).connect(bp.frequency);
  const lfo2 = ac.createOscillator();
  lfo2.frequency.value = 0.07;
  const lfo2Gain = ac.createGain();
  lfo2Gain.gain.value = 0.08;
  lfo2.connect(lfo2Gain).connect(g.gain);
  src.connect(bp).connect(g).connect(out);
  src.start();
  lfo.start();
  lfo2.start();
  return () => {
    try {
      src.stop();
      lfo.stop();
      lfo2.stop();
    } catch {
      /* noop */
    }
  };
}

/** 밤 — 아주 낮은 바탕 + 이따금의 풀벌레 */
function buildNight(ac: AudioContext, out: GainNode): () => void {
  const base = ac.createBufferSource();
  base.buffer = noiseBuffer(ac, true);
  base.loop = true;
  const lp = ac.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 260;
  const bg = ac.createGain();
  bg.gain.value = 0.05;
  base.connect(lp).connect(bg).connect(out);
  base.start();

  let alive = true;
  const chirp = () => {
    if (!alive) return;
    const t = ac.currentTime;
    const osc = ac.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 4200 + Math.random() * 400;
    const g = ac.createGain();
    g.gain.setValueAtTime(0, t);
    // 짧은 트릴 3~5회
    const n = 3 + Math.floor(Math.random() * 3);
    for (let i = 0; i < n; i++) {
      const s = t + i * 0.07;
      g.gain.setValueAtTime(0.0001, s);
      g.gain.exponentialRampToValueAtTime(0.02, s + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, s + 0.06);
    }
    osc.connect(g).connect(out);
    osc.start(t);
    osc.stop(t + n * 0.07 + 0.1);
    timer = setTimeout(chirp, 1200 + Math.random() * 2600);
  };
  let timer = setTimeout(chirp, 600);
  return () => {
    alive = false;
    clearTimeout(timer);
    try {
      base.stop();
    } catch {
      /* noop */
    }
  };
}

function startLayer(kind: SfxKind): Layer {
  const ac = audio();
  const out = ac.createGain();
  out.gain.value = 0;
  out.connect(ac.destination);
  const stopSources =
    kind === "rain" ? buildRain(ac, out) : kind === "wind" ? buildWind(ac, out) : buildNight(ac, out);
  out.gain.linearRampToValueAtTime(1, ac.currentTime + 1.2);
  return {
    kind,
    stop: () => {
      const now = ac.currentTime;
      try {
        out.gain.cancelScheduledValues(now);
        out.gain.setValueAtTime(out.gain.value, now);
        out.gain.linearRampToValueAtTime(0, now + 0.6);
      } catch {
        /* noop */
      }
      setTimeout(stopSources, 700);
    },
  };
}

function stopCurrent() {
  current?.stop();
  current = null;
}

/**
 * 시사실이 장면마다 부른다. 마스터가 꺼져 있거나 kind가 null이면 침묵으로,
 * 같은 kind면 그대로, 다르면 크로스페이드.
 */
export function updateAmbience(kind: SfxKind | null): void {
  if (!masterOn || !kind) {
    stopCurrent();
    return;
  }
  if (current?.kind === kind) return;
  stopCurrent();
  current = startLayer(kind);
}

export function setAmbienceMaster(on: boolean): void {
  masterOn = on;
  if (!on) stopCurrent();
}

export function isAmbienceMasterOn(): boolean {
  return masterOn;
}

/** 시사실을 떠날 때 — 마스터 설정은 남기고 소리만 멈춘다. */
export function stopAmbience(): void {
  stopCurrent();
}

/** 타자기 틱 — 마스터가 켜져 있을 때만, 아주 짧고 조용하게. */
export function typeTick(): void {
  if (!masterOn) return;
  const ac = audio();
  const t = ac.currentTime;
  const osc = ac.createOscillator();
  osc.type = "square";
  osc.frequency.value = 950 + Math.random() * 180;
  const g = ac.createGain();
  g.gain.setValueAtTime(0.012, t);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
  osc.connect(g).connect(ac.destination);
  osc.start(t);
  osc.stop(t + 0.04);
}
