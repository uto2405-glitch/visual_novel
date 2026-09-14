/**
 * 밤의 음악 — WebAudio 즉석 생성 BGM. 외부 파일·네트워크 없음.
 * 낮게 숨쉬는 드론 + 이따금의 펜타토닉 플럭(랜덤 워크) + 옅은 딜레이 공간감.
 * 앰비언스와 독립 토글 — 함께 켜면 비 오는 밤의 왈츠가 된다.
 */

let ctx: AudioContext | null = null;
let running: { stop: () => void } | null = null;

export function isMusicOn(): boolean {
  return running !== null;
}

export function stopMusic(): void {
  running?.stop();
  running = null;
}

/** 이미 켜져 있으면 무시하고 시작. 전 구간 동기 — 더블클릭 경합 없음. */
export function startMusic(): void {
  if (running) return;
  ctx = ctx ?? new AudioContext();
  void ctx.resume();
  const ac = ctx;

  const master = ac.createGain();
  master.gain.value = 0;
  master.connect(ac.destination);
  master.gain.linearRampToValueAtTime(1, ac.currentTime + 2.0);

  // 공간감 — 딜레이 + 피드백
  const delay = ac.createDelay(1.0);
  delay.delayTime.value = 0.42;
  const feedback = ac.createGain();
  feedback.gain.value = 0.32;
  const wet = ac.createGain();
  wet.gain.value = 0.35;
  delay.connect(feedback).connect(delay);
  delay.connect(wet).connect(master);

  // 드론 — 낮은 A, 살짝 어긋난 두 겹이 천천히 숨쉰다
  const droneGain = ac.createGain();
  droneGain.gain.value = 0.045;
  const droneLp = ac.createBiquadFilter();
  droneLp.type = "lowpass";
  droneLp.frequency.value = 320;
  const d1 = ac.createOscillator();
  d1.type = "triangle";
  d1.frequency.value = 110; // A2
  const d2 = ac.createOscillator();
  d2.type = "triangle";
  d2.frequency.value = 164.81; // E3
  d2.detune.value = 4;
  const breath = ac.createOscillator();
  breath.frequency.value = 0.05;
  const breathGain = ac.createGain();
  breathGain.gain.value = 0.018;
  breath.connect(breathGain).connect(droneGain.gain);
  d1.connect(droneLp);
  d2.connect(droneLp);
  droneLp.connect(droneGain);
  droneGain.connect(master);
  droneGain.connect(delay);
  d1.start();
  d2.start();
  breath.start();

  // 플럭 — A 마이너 펜타토닉 랜덤 워크
  const SCALE = [220.0, 261.63, 293.66, 329.63, 392.0, 440.0]; // A3 C4 D4 E4 G4 A4
  let step = 3;
  let alive = true;
  let timer: ReturnType<typeof setTimeout>;
  const pluck = () => {
    if (!alive) return;
    step = Math.min(SCALE.length - 1, Math.max(0, step + (Math.random() < 0.5 ? -1 : 1)));
    const freq = SCALE[step] * (Math.random() < 0.15 ? 2 : 1); // 가끔 한 옥타브 위
    const t = ac.currentTime;
    const osc = ac.createOscillator();
    osc.type = "triangle";
    osc.frequency.value = freq;
    const g = ac.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.07, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.8);
    osc.connect(g);
    g.connect(master);
    g.connect(delay);
    osc.start(t);
    osc.stop(t + 2.0);
    timer = setTimeout(pluck, 2400 + Math.random() * 3600);
  };
  timer = setTimeout(pluck, 1200);

  running = {
    stop: () => {
      alive = false;
      clearTimeout(timer);
      const now = ac.currentTime;
      try {
        master.gain.cancelScheduledValues(now);
        master.gain.setValueAtTime(master.gain.value, now);
        master.gain.linearRampToValueAtTime(0, now + 0.8);
      } catch {
        /* noop */
      }
      setTimeout(() => {
        try {
          d1.stop();
          d2.stop();
          breath.stop();
        } catch {
          /* noop */
        }
        try {
          master.disconnect();
        } catch {
          /* noop */
        }
      }, 900);
    },
  };
}
