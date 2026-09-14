/**
 * 「시사만 보내기」 — OK 컷만 담은 로컬 HTML 한 장.
 * 공개용이 아니라 내 기기에 두는 시사본이다. 토큰·외부 요청 없음.
 * v0.13: 표지 포스터 + 타자기 대사 + 컷 페이드.
 * v0.16: 소리 나는 시사본 — 앰비언스·음악(전부 WebAudio 즉석 합성) + 엔딩 크레딧 롤.
 */
import type { Scene, Story } from "../types";
import { isSfxKind } from "./ambience";
import { chapterRanges } from "./chapters";
import { speakerName } from "./story";

interface ScreeningScene {
  id: string;
  text: string;
  speaker: string;
  next?: string;
  choices?: { label: string; next: string }[];
  sfx?: string;
  bgm?: boolean;
}

/** OK 컷(dataUrl 보유)만 담는다. next가 시사본 밖이면 거기서 막을 내린다. */
export function buildScreeningHtml(
  story: Story,
  images: ReadonlyMap<string, string>,
  posterUrl?: string | null,
  extra?: {
    coinsSpent?: number;
    typeMs?: number;
    fontScale?: number;
    /** 같은 필름캔에 인쇄본이 함께 담겼는지 — 크레딧 끝에서 어디 있는지 알려준다 */
    hasPrintBook?: boolean;
    /** 인쇄본 첫 장의 작은 미리보기(data URL) — 표지에 「만화판도 있다」로 보여준다 */
    printThumb?: string | null;
  },
): string {
  const okScenes: ScreeningScene[] = story.scenes
    .filter((s: Scene) => images.has(s.id))
    .map((s) => ({
      id: s.id,
      text: s.text ?? "",
      speaker: speakerName(story, s),
      next: s.next,
      choices: s.choices?.map((c) => ({ label: c.label, next: c.next })),
      ...(isSfxKind(s.sfx) ? { sfx: s.sfx } : {}),
      ...(s.bgm !== undefined ? { bgm: s.bgm } : {}),
    }));
  /**
   * 장 — 앱의 시사실에는 「장부터」가 있는데 내보낸 시사본에는 없었다.
   * 시사본에는 «찍은 컷»만 담기므로, 장의 첫 컷이 아직 안 찍혔으면
   * 그 장에서 처음 찍힌 컷에 장 이름을 건다(없는 장은 목록에 나오지 않는다).
   */
  const okIds = new Set(okScenes.map((s) => s.id));
  const chapterMarks = chapterRanges(story.scenes)
    .map((c) => ({ id: c.ids.find((id) => okIds.has(id)) ?? null, title: c.title }))
    .filter((c): c is { id: string; title: string } => c.id !== null);

  const imageEntries: Record<string, string> = {};
  for (const [id, url] of images) imageEntries[id] = url;

  const payload = JSON.stringify({
    title: story.title,
    scenes: okScenes,
    images: imageEntries,
    poster: posterUrl ?? null,
    cast: story.characters.map((c) => c.name).filter(Boolean),
    coins: extra?.coinsSpent ?? null,
    typeMs: extra?.typeMs ?? 26,
    fontScale: extra?.fontScale ?? 1,
    printBook: extra?.hasPrintBook === true,
    printThumb: extra?.printThumb ?? null,
    chapters: chapterMarks.length >= 2 ? chapterMarks : [],
  }).replace(/</g, "\\u003c");

  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(story.title)} — 시사본</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; }
  body { background: #0b0a09; color: #efe8dc; font-family: Pretendard, "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
         min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px; }
  .stage { width: min(1100px, 100%); aspect-ratio: 16/9; position: relative; background: #000;
           border-radius: 10px; overflow: hidden; box-shadow: 0 24px 80px rgba(0,0,0,.6); cursor: pointer; }
  .stage img.bg { width: 100%; height: 100%; object-fit: contain; display: block; opacity: 1; }
  .bg.fadein { animation: f .45s ease-out; }
  @keyframes f { from { opacity: 0; } to { opacity: 1; } }
  .box { position: absolute; left: 0; right: 0; bottom: 0; padding: 18px 24px 22px;
         background: linear-gradient(transparent, rgba(8,6,4,.55) 18%, rgba(8,6,4,.88));
         min-height: 30%; display: flex; flex-direction: column; justify-content: flex-end; gap: 8px; }
  .who { color: #f0b45e; font-weight: 700; font-size: 15px; }
  .line { font-size: 18px; line-height: 1.7; text-shadow: 0 1px 2px rgba(0,0,0,.8); white-space: pre-wrap; }
  .caret { color: #f0b45e; animation: blink .9s ease-in-out infinite; }
  @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: .3; } }
  .choices { position: absolute; inset: 0; display: flex; flex-direction: column; gap: 12px;
             align-items: center; justify-content: center; background: rgba(8,6,4,.55); }
  .choices button { font: inherit; font-size: 17px; color: #efe8dc; background: rgba(24,20,16,.92);
                    border: 1px solid rgba(240,180,94,.5); border-radius: 10px; padding: 12px 28px;
                    cursor: pointer; min-width: 60%; }
  .choices button:hover { background: rgba(240,180,94,.18); }
  .cover { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }
  /* 표지 배경 그림 — «.cover img»로 두면 표지 안의 다른 그림(만화판 미리보기)까지 절대 위치로
     끌려가 왼쪽 위 구석에 박힌다. 배경은 그 한 장뿐이므로 id로 정확히 지목한다. */
  #coverimg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .45; }
  .toonpeek { display: flex; align-items: center; gap: 10px; justify-content: center;
    margin-top: 14px; padding: 8px 10px; border: 1px solid #3a342c; border-radius: 10px;
    background: rgba(12,10,8,.55); color: #a89f90; font-size: 12px; }
  /* 본문 장은 세로로 길다 — 높이를 묶고 위쪽만 잘라 «작은 타일»로 보여준다
     (height:auto로 두면 460px짜리 그림이 띠 밖으로 넘쳤다) */
  .toonpeek img { width: 42px; height: 54px; object-fit: cover; object-position: top center;
    border-radius: 4px; display: block; border: 1px solid #4a4238; }
  .toonpeek code { color: #f0b45e; }
  .cover .front { position: relative; text-align: center; padding: 18px 28px; border-radius: 14px;
                  background: rgba(8,6,4,.45); }
  .cover h1 { font-size: 30px; background: linear-gradient(180deg,#f7dfae,#f0b45e);
              -webkit-background-clip: text; background-clip: text; color: transparent; }
  .cover small { color: #a89f90; }
  .end { position: absolute; inset: 0; overflow: hidden; background: rgba(8,6,4,.86); }
  .credits-roll { position: absolute; left: 0; right: 0; text-align: center; display: flex;
                  flex-direction: column; gap: 14px; animation: roll 20s linear forwards; }
  @keyframes roll { from { top: 100%; } to { top: -160%; } }
  .credits-roll h2 { font-size: 26px; background: linear-gradient(180deg,#f7dfae,#f0b45e);
                     -webkit-background-clip: text; background-clip: text; color: transparent; }
  .credits-roll .role { color: #a89f90; font-size: 12px; letter-spacing: .18em; margin-top: 10px; }
  .credits-roll .name { font-size: 17px; }
  .credits-roll .fin { margin-top: 26px; color: #f0b45e; font-size: 20px; letter-spacing: .3em; }
  .credits-roll small { color: #877f72; }
  .hint { position: absolute; top: 10px; right: 14px; font-size: 12px; color: rgba(239,232,220,.55); }
  .ctl { position: absolute; top: 8px; left: 12px; display: flex; gap: 6px; z-index: 5; }
  /* 컷 목록 — 기본은 접혀 있다. 선형 감상의 흐름을 깨지 않도록 «찾을 때만» 연다 */
  .toc { position: absolute; top: 44px; left: 12px; z-index: 6; max-height: 62%; overflow: auto;
         background: rgba(8,6,4,.92); border: 1px solid rgba(239,232,220,.22); border-radius: 10px;
         padding: 6px; display: flex; flex-direction: column; gap: 2px; min-width: 220px; }
  .toc button { font: inherit; font-size: 12px; text-align: left; color: rgba(239,232,220,.86);
         background: transparent; border: 0; border-radius: 6px; padding: 5px 8px; cursor: pointer; }
  .toc button:hover { background: rgba(239,232,220,.12); }
  .toc button.on { color: #f0b45e; }
  .toc .tocid { color: rgba(239,232,220,.45); margin-right: 6px; }
  /* 장 머리 — 60컷짜리 목록은 «몇 번째 컷»보다 «몇 장»으로 찾는다 */
  .toc .tocchap { color: #f0b45e; font-size: 11px; letter-spacing: .12em; padding: 7px 8px 3px;
         border-top: 1px solid rgba(239,232,220,.16); margin-top: 3px; }
  .toc .tocchap:first-child { border-top: 0; margin-top: 0; }
  .snd { position: relative; font: inherit; font-size: 13px; color: rgba(239,232,220,.8);
         background: rgba(8,6,4,.5); border: 1px solid rgba(239,232,220,.25); border-radius: 8px;
         padding: 4px 10px; cursor: pointer; }
</style>
</head>
<body>
<div class="stage" id="stage">
  <img id="bg" class="bg" alt="">
  <div class="box" id="box" style="display:none"><div class="who" id="who"></div><div class="line" id="line"></div></div>
  <div class="choices" id="choices" style="display:none"></div>
  <div class="cover" id="cover">
    <img id="coverimg" alt="" style="display:none">
    <div class="front"><h1 id="covertitle"></h1><small>클릭하면 시사가 시작됩니다 · 소리 있음</small>
      <div class="toonpeek" id="toonpeek" style="display:none">
        <img id="toonthumb" alt="">
        <span>만화판도 함께 — 필름캔의 <code>webtoon/</code></span>
      </div>
    </div>
  </div>
  <div class="end" id="end" style="display:none"><div class="credits-roll" id="credits"></div></div>
  <div class="ctl">
    <button class="snd" id="snd" title="앰비언스·음악 켜고 끄기">🔊 소리</button>
    <button class="snd" id="back" title="한 컷 뒤로 (←)">◀ 되감기</button>
    <button class="snd" id="auto" title="자동 상영 켜고 끄기">▶ 자동</button>
    <button class="snd" id="toc" title="컷 목록 — 보고 싶은 데로 바로">☰ 목록</button>
  </div>
  <div class="toc" id="toclist" style="display:none"></div>
  <div class="hint">클릭 / Space / ← →</div>
</div>
<script>
var DATA = ${payload};
if (DATA.fontScale && DATA.fontScale !== 1) {
  document.getElementById("box").style.fontSize = DATA.fontScale + "em";
}
var byId = {};
DATA.scenes.forEach(function (s) { byId[s.id] = s; });
var startId = DATA.scenes.length ? DATA.scenes[0].id : null;
var cur = null, typed = 0, timer = null, started = false;
var hist = [], auto = false, autoTimer = null;
document.getElementById("covertitle").textContent = DATA.title;
if (DATA.poster) { var ci = document.getElementById("coverimg"); ci.src = DATA.poster; ci.style.display = "block"; }
if (DATA.printThumb) {
  document.getElementById("toonthumb").src = DATA.printThumb;
  document.getElementById("toonpeek").style.display = "flex";
}

/* ── 소리 — 전부 WebAudio 즉석 합성, 파일·네트워크 없음 ───────────── */
var SND = { on: true, ctx: null, amb: null, ambKind: null, music: null, musicWanted: false };
function ac() {
  if (!SND.ctx) SND.ctx = new (window.AudioContext || window.webkitAudioContext)();
  SND.ctx.resume();
  return SND.ctx;
}
function noiseBuf(a, brown) {
  var len = a.sampleRate * 2, buf = a.createBuffer(1, len, a.sampleRate), d = buf.getChannelData(0), last = 0;
  for (var i = 0; i < len; i++) {
    var w = Math.random() * 2 - 1;
    if (brown) { last = (last + 0.02 * w) / 1.02; d[i] = last * 3.2; } else { d[i] = w; }
  }
  return buf;
}
function startAmb(kind) {
  var a = ac(), out = a.createGain(), stops = [], timers = [];
  out.gain.value = 0; out.connect(a.destination);
  function noise(brown, mk) {
    var src = a.createBufferSource(); src.buffer = noiseBuf(a, brown); src.loop = true;
    mk(src); src.start(); stops.push(function () { try { src.stop(); } catch (e) {} });
  }
  if (kind === "rain") {
    noise(true, function (s) { var lp = a.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 620;
      var g = a.createGain(); g.gain.value = 0.16; s.connect(lp).connect(g).connect(out); });
    noise(false, function (s) { var hp = a.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 3200;
      var g = a.createGain(); g.gain.value = 0.03; s.connect(hp).connect(g).connect(out); });
  } else if (kind === "wind") {
    noise(true, function (s) {
      var bp = a.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = 400; bp.Q.value = 0.6;
      var g = a.createGain(); g.gain.value = 0.22;
      var lfo = a.createOscillator(); lfo.frequency.value = 0.13;
      var lg = a.createGain(); lg.gain.value = 220; lfo.connect(lg).connect(bp.frequency); lfo.start();
      stops.push(function () { try { lfo.stop(); } catch (e) {} });
      s.connect(bp).connect(g).connect(out);
    });
  } else { /* night */
    noise(true, function (s) { var lp = a.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 260;
      var g = a.createGain(); g.gain.value = 0.05; s.connect(lp).connect(g).connect(out); });
    var alive = true;
    var chirp = function () {
      if (!alive) return;
      var t = a.currentTime, osc = a.createOscillator(), g = a.createGain();
      osc.type = "sine"; osc.frequency.value = 4200 + Math.random() * 400;
      var n = 3 + Math.floor(Math.random() * 3);
      g.gain.setValueAtTime(0, t);
      for (var i = 0; i < n; i++) {
        var st = t + i * 0.07;
        g.gain.setValueAtTime(0.0001, st);
        g.gain.exponentialRampToValueAtTime(0.02, st + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, st + 0.06);
      }
      osc.connect(g).connect(out); osc.start(t); osc.stop(t + n * 0.07 + 0.1);
      timers.push(setTimeout(chirp, 1200 + Math.random() * 2600));
    };
    timers.push(setTimeout(chirp, 600));
    stops.push(function () { alive = false; });
  }
  out.gain.linearRampToValueAtTime(1, a.currentTime + 1.2);
  return { stop: function () {
    var now = a.currentTime;
    try { out.gain.cancelScheduledValues(now); out.gain.setValueAtTime(out.gain.value, now);
          out.gain.linearRampToValueAtTime(0, now + 0.6); } catch (e) {}
    timers.forEach(clearTimeout);
    setTimeout(function () { stops.forEach(function (f) { f(); }); try { out.disconnect(); } catch (e) {} }, 700);
  } };
}
function updateAmb(kind) {
  if (!SND.on || !kind) { if (SND.amb) SND.amb.stop(); SND.amb = null; SND.ambKind = null; return; }
  if (SND.ambKind === kind) return;
  if (SND.amb) SND.amb.stop();
  SND.ambKind = kind; SND.amb = startAmb(kind);
}
function startMusic() {
  if (SND.music) return;
  var a = ac(), master = a.createGain();
  master.gain.value = 0; master.connect(a.destination);
  master.gain.linearRampToValueAtTime(1, a.currentTime + 2.0);
  var delay = a.createDelay(1.0); delay.delayTime.value = 0.42;
  var fb = a.createGain(); fb.gain.value = 0.32; delay.connect(fb).connect(delay);
  var wet = a.createGain(); wet.gain.value = 0.35; delay.connect(wet).connect(master);
  var dg = a.createGain(); dg.gain.value = 0.045;
  var lp = a.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 320;
  var d1 = a.createOscillator(); d1.type = "triangle"; d1.frequency.value = 110;
  var d2 = a.createOscillator(); d2.type = "triangle"; d2.frequency.value = 164.81; d2.detune.value = 4;
  d1.connect(lp); d2.connect(lp); lp.connect(dg); dg.connect(master); dg.connect(delay);
  d1.start(); d2.start();
  var SCALE = [220.0, 261.63, 293.66, 329.63, 392.0, 440.0];
  var step = 3, alive = true, t2;
  var pluck = function () {
    if (!alive) return;
    step = Math.min(SCALE.length - 1, Math.max(0, step + (Math.random() < 0.5 ? -1 : 1)));
    var t = a.currentTime, osc = a.createOscillator(), g = a.createGain();
    osc.type = "triangle"; osc.frequency.value = SCALE[step] * (Math.random() < 0.15 ? 2 : 1);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.07, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.8);
    osc.connect(g); g.connect(master); g.connect(delay);
    osc.start(t); osc.stop(t + 2.0);
    t2 = setTimeout(pluck, 2400 + Math.random() * 3600);
  };
  t2 = setTimeout(pluck, 1200);
  SND.music = { stop: function () {
    alive = false; clearTimeout(t2);
    var now = a.currentTime;
    try { master.gain.cancelScheduledValues(now); master.gain.setValueAtTime(master.gain.value, now);
          master.gain.linearRampToValueAtTime(0, now + 0.8); } catch (e) {}
    setTimeout(function () { try { d1.stop(); d2.stop(); } catch (e) {} try { master.disconnect(); } catch (e) {} }, 900);
  } };
}
function stopMusic() { if (SND.music) SND.music.stop(); SND.music = null; }
function tick() {
  if (!SND.on || !SND.ctx) return; /* 컨텍스트가 아직 없으면 조용히 — 첫 클릭 후부터 */
  var a = SND.ctx, t = a.currentTime, osc = a.createOscillator(), g = a.createGain();
  osc.type = "square"; osc.frequency.value = 950 + Math.random() * 180;
  g.gain.setValueAtTime(0.012, t);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
  osc.connect(g).connect(a.destination); osc.start(t); osc.stop(t + 0.04);
}
function applyAudio() {
  if (!SND.on) { updateAmb(null); stopMusic(); return; }
  updateAmb(cur && cur.sfx ? cur.sfx : null);
  if (SND.musicWanted) startMusic(); else stopMusic();
}
document.getElementById("snd").addEventListener("click", function (e) {
  e.stopPropagation();
  SND.on = !SND.on;
  this.textContent = SND.on ? "\\uD83D\\uDD0A 소리" : "\\uD83D\\uDD07 무음";
  applyAudio();
});

/* ── 플레이어 ───────────────────────────────────────────── */
function typeLoop() {
  if (!cur) return;
  var full = cur.text || "";
  if (typed >= full.length) { renderLine(full, false); maybeChoices(); armAuto(); return; }
  typed++;
  renderLine(full.slice(0, typed), true);
  if (typed % 2 === 0) tick();
  timer = setTimeout(typeLoop, DATA.typeMs || 26);
}
function renderLine(text, caret) {
  var el = document.getElementById("line");
  el.textContent = text;
  if (caret) { var c = document.createElement("span"); c.className = "caret"; c.textContent = "\\u258c"; el.appendChild(c); }
}
function maybeChoices() {
  var choices = document.getElementById("choices");
  if (cur && cur.choices && cur.choices.length) {
    choices.innerHTML = "";
    cur.choices.forEach(function (c) {
      var b = document.createElement("button");
      b.textContent = c.label || "…";
      b.onclick = function (e) { e.stopPropagation(); show(c.next); };
      choices.appendChild(b);
    });
    choices.style.display = "flex";
  } else {
    choices.style.display = "none";
  }
}
function rollCredits() {
  clearTimeout(autoTimer);
  cur = null;
  document.getElementById("box").style.display = "none";
  document.getElementById("choices").style.display = "none";
  var end = document.getElementById("end");
  var roll = document.getElementById("credits");
  roll.innerHTML = "";
  function add(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    el.textContent = text;
    roll.appendChild(el);
  }
  add("h2", "", DATA.title);
  add("div", "role", "각본 · 감독");
  add("div", "name", "나");
  if (DATA.cast && DATA.cast.length) {
    add("div", "role", "출연");
    DATA.cast.forEach(function (n) { add("div", "name", n); });
  }
  add("div", "role", "촬영");
  add("div", "name", "MakeFun");
  add("div", "role", "편집");
  add("div", "name", "비주얼노벨 스튜디오");
  add("div", "role", "이 밤의 기록");
  add("div", "name", DATA.scenes.length + "컷");
  if (DATA.coins) add("small", "", "제작비 " + DATA.coins + " 크레딧");
  if (DATA.printBook) add("small", "", "만화로 조판한 인쇄본은 필름캔 ZIP의 webtoon/ 폴더에 있습니다.");
  add("small", "", "이 시사본은 이 기기 밖으로 나가지 않았습니다.");
  add("div", "fin", "fin.");
  /* 애니메이션 재시작 */
  var fresh = roll.cloneNode(true);
  roll.parentNode.replaceChild(fresh, roll);
  fresh.id = "credits";
  end.style.display = "block";
  updateAmb(null); /* 크레딧은 음악만 남기고 조용히 */
}
function show(id, back) {
  clearTimeout(timer);
  clearTimeout(autoTimer);
  var s = byId[id];
  if (!back && cur && s) hist.push(cur.id);
  document.getElementById("choices").style.display = "none";
  if (!s) { rollCredits(); return; }
  cur = s; typed = 0;
  document.getElementById("end").style.display = "none";
  document.getElementById("cover").style.display = "none";
  document.getElementById("box").style.display = "flex";
  var bg = document.getElementById("bg");
  bg.classList.remove("fadein");
  void bg.offsetWidth; /* 리플로우로 페이드 재시작 */
  bg.src = DATA.images[s.id] || "";
  bg.classList.add("fadein");
  document.getElementById("who").textContent = s.speaker || "";
  if (s.bgm === true) SND.musicWanted = true;
  if (s.bgm === false) SND.musicWanted = false;
  applyAudio();
  renderLine("", true);
  timer = setTimeout(typeLoop, 60);
}
function advance() {
  if (!started) { started = true; if (startId) show(startId); return; }
  if (!cur) { if (startId) { SND.musicWanted = false; show(startId); } return; }
  var full = cur.text || "";
  if (typed < full.length) { clearTimeout(timer); typed = full.length; renderLine(full, false); maybeChoices(); armAuto(); return; }
  if (cur.choices && cur.choices.length) return;
  if (cur.next) show(cur.next);
  else rollCredits();
}
function armAuto() {
  clearTimeout(autoTimer);
  if (!auto || !cur) return;
  if (cur.choices && cur.choices.length) return; /* 갈림길에서는 손을 기다린다 */
  autoTimer = setTimeout(function () {
    if (!auto || !cur) return;
    if (cur.next) show(cur.next); else rollCredits();
  }, 1600);
}
function goBack() {
  clearTimeout(autoTimer);
  var endEl = document.getElementById("end");
  if (endEl.style.display !== "none" && endEl.style.display !== "") {
    /* 크레딧에서 되감기 → 마지막 컷으로 */
    if (cur === null && hist.length) { var last = hist.pop(); endEl.style.display = "none"; show(last, true); return; }
  }
  if (!hist.length) return;
  show(hist.pop(), true);
}
document.getElementById("back").addEventListener("click", function (e) { e.stopPropagation(); goBack(); });
/* 컷 목록 — 긴 작품에서 되감기만으로 돌아가려면 수십 번 눌러야 한다 */
var tocEl = document.getElementById("toclist");
function buildToc() {
  tocEl.innerHTML = "";
  var chapAt = {};
  (DATA.chapters || []).forEach(function (c) { chapAt[c.id] = c.title; });
  DATA.scenes.forEach(function (s2, i) {
    if (chapAt[s2.id]) {
      var h = document.createElement("div");
      h.className = "tocchap";
      h.textContent = chapAt[s2.id];
      tocEl.appendChild(h);
    }
    var b = document.createElement("button");
    /* 대사는 한 줄이라 공백 정리는 trim으로 충분하다 (이 파일은 JS 소스를 담은 템플릿
       문자열이어서 정규식의 백슬래시가 한 겹 더 필요해진다 — 안 쓰는 편이 안전하다) */
    var txt = (s2.text || "").trim().slice(0, 20);
    b.innerHTML = '<span class="tocid">' + (i + 1) + "</span>" + (txt || "(대사 없음)");
    if (cur && s2.id === cur.id) b.className = "on";
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      tocEl.style.display = "none";
      var endBox = document.getElementById("end");
      if (endBox) endBox.style.display = "none";
      started = true;
      if (cur) hist.push(cur.id); // hist는 id 목록이다 — 객체를 넣으면 되감기가 크레딧으로 튄다
      show(s2.id, true);
    });
    tocEl.appendChild(b);
  });
}
document.getElementById("toc").addEventListener("click", function (e) {
  e.stopPropagation();
  if (tocEl.style.display === "flex") { tocEl.style.display = "none"; return; }
  buildToc();
  tocEl.style.display = "flex";
});
document.getElementById("auto").addEventListener("click", function (e) {
  e.stopPropagation();
  auto = !auto;
  this.textContent = auto ? "⏸ 자동 중" : "▶ 자동";
  if (auto) { if (!started) { started = true; if (startId) show(startId); } else armAuto(); }
  else clearTimeout(autoTimer);
});
document.getElementById("stage").addEventListener("click", advance);
document.addEventListener("keydown", function (e) {
  if (e.key === " " || e.key === "Enter" || e.key === "ArrowRight") { e.preventDefault(); advance(); }
  if (e.key === "ArrowLeft" || e.key === "Backspace") { e.preventDefault(); goBack(); }
});
if (!startId) { document.getElementById("cover").style.display = "none"; rollCredits(); }
</script>
</body>
</html>`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
