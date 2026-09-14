/**
 * story.json 린터 — 그록·LLM이 만든 콘티를 «앱에 붙여넣기 전에» 검사한다.
 *
 * 실행: npm run lint:story -- 파일경로.json   (여러 개 줄 수 있다)
 *
 * 두 겹으로 본다:
 *  (1) 앱 파서(parseStory)의 에러·경고 — 앱이 실제로 뭐라고 할지
 *  (2) 프롬프트 조립·조판이 «조용히 버리거나 망가지는» 자리 — 파서는 통과하지만 결과가 상한다.
 *      (grok-skill.ko.md의 자기검사 목록과 같은 규칙이다)
 */
import { parseStory } from "../src/lib/parse-story.ts";
import fs from "node:fs";
import path from "node:path";

const SHOTS = ["full", "focus", "portrait", "wide", "back", "action"];
const SFX = ["rain", "wind", "night"];
const SCENE_FIELDS = new Set([
  "id",
  "shot",
  "bg_prompt",
  "bg",
  "chars",
  "pose",
  "emotion",
  "hold",
  "text",
  "speaker",
  "sfx",
  "bgm",
  "next",
  "choices",
  "placeholder",
  "webtoon",
]);
const WEBTOON_FIELDS = new Set([
  "caption",
  "line",
  "pos",
  "kind",
  "tail",
  "pageBreak",
  "textScale",
  "crop",
  "fx",
]);
const CHAR_FIELDS = new Set(["id", "name", "ref", "look", "castCrop"]);
/**
 * bg_prompt는 여섯 shot 모두에서 쓰인다 — focus·portrait에서는 «흐린 배경»으로 얹힌다.
 * (v2.1.0 실촬영 A/B: 장소를 안 적은 반신 컷은 같은 교실이 밤거리로 바뀌었다.)
 */
const BG_SHOTS = new Set(["full", "action", "back", "wide", "focus", "portrait"]);

/**
 * 규칙 검사 — 파서는 통과하지만 «결과가 상하는» 자리를 잡는다.
 *
 * fragment(이어쓰기 조각, `{"scenes":[…]}`)는 제목·화풍·배우를 «기존 작품에서 물려받는다» —
 * 그러니 조각을 검사할 때 배우·화풍이 없다고 나무라면 거짓 경고가 된다(실측으로 잡았다).
 */
function lintRules(story, isFragment) {
  const bad = [];
  const warn = [];
  const scenes = Array.isArray(story.scenes) ? story.scenes : [];
  const chars = Array.isArray(story.characters) ? story.characters : [];
  const charById = new Map(chars.map((c) => [c && c.id, c]));
  const ids = new Set(scenes.map((s) => s && s.id));

  if (isFragment) {
    // 조각은 화풍·배우를 물려받는다 — 여기서는 컷의 문법만 본다
  } else if (typeof story.style !== "string" || !story.style.trim()) {
    warn.push("style이 비었다 — 화풍(장르)이 모든 컷 프롬프트의 첫머리에 실리는 자리다");
  } else if (!/[a-zA-Z]/.test(story.style)) {
    warn.push("style에 영어가 없다 — 프롬프트는 영어로 조립된다");
  }
  for (const c of chars) {
    if (!c || typeof c !== "object") continue;
    for (const k of Object.keys(c)) if (!CHAR_FIELDS.has(k)) warn.push(`배우 ${c.id}: 스키마에 없는 필드 「${k}」`);
  }
  // chars에 켜지는 배우에게 look이 없으면 한국어 name이 영어 프롬프트에 그대로 들어간다
  const used = new Set();
  for (const s of scenes) for (const id of (s && s.chars) || []) used.add(id);
  for (const id of used) {
    const c = charById.get(id);
    if (!c) continue; // 조각이면 부모 작품의 배우다 — 여기서 판단하지 않는다
    if (typeof c.look !== "string" || !c.look.trim()) {
      bad.push(`배우 ${id}: chars에 켜지는데 look이 없다 — 한국어 이름이 영어 프롬프트에 실린다`);
    } else if (!/[a-zA-Z]/.test(c.look)) {
      bad.push(`배우 ${id}: look에 영어가 없다 — 프롬프트가 한국어로 섞인다`);
    }
  }

  let endings = 0;
  const prevShot = new Map();
  scenes.forEach((s, i) => {
    if (!s || typeof s !== "object") return;
    const at = `${s.id ?? `#${i + 1}`}`;
    for (const k of Object.keys(s)) if (!SCENE_FIELDS.has(k)) warn.push(`${at}: 스키마에 없는 필드 「${k}」 (버려진다)`);
    if (s.shot !== undefined && !SHOTS.includes(s.shot)) bad.push(`${at}: shot 「${s.shot}」은 허용값이 아니다 (${SHOTS.join("|")})`);
    const shot = SHOTS.includes(s.shot) ? s.shot : "full";
    const hasBg = (typeof s.bg_prompt === "string" && s.bg_prompt.trim()) || /^reuse:/.test(String(s.bg ?? ""));
    if (!hasBg) {
      // 클로즈업·반신은 «장소를 일부러 지우는» 연출일 수 있다 — 그래서 위반이 아니라 주의로 본다
      const soft = shot === "focus" || shot === "portrait";
      const msg = `${at}: ${shot} 컷에 bg_prompt(또는 bg:"reuse:…")가 없다 — 그 컷에서 장소가 사라져 카메라가 배경을 새로 지어낸다`;
      if (soft) warn.push(`${msg} (장소를 일부러 지우는 연출이라면 정상)`);
      else bad.push(msg);
    }
    if (shot === "wide" && s.pose) warn.push(`${at}: wide 컷의 pose는 프롬프트에 실리지 않는다 — 동작은 bg_prompt에 적어라`);
    if (shot === "back" && s.emotion) warn.push(`${at}: back 컷의 emotion은 실리지 않는다`);
    if (s.hold === true) {
      const p = prevShot.get(i - 1);
      if (p && p !== shot) bad.push(`${at}: hold:true인데 앞 컷의 shot(${p})과 다르다 — 앵글 지시가 충돌한다`);
    }
    prevShot.set(i, shot);
    /* 같은 장면이 이어지는데 장소 «문구»가 달라지면 카메라는 다른 방으로 읽는다 —
       장면이 바뀌는 자리면 webtoon.pageBreak를 주고, 같은 장면이면 문구를 그대로 복사해야 한다. */
    if (i > 0) {
      const prev = scenes[i - 1];
      const newScene = Boolean(s.webtoon && s.webtoon.pageBreak);
      const a = (prev && typeof prev.bg_prompt === "string" && prev.bg_prompt.trim()) || "";
      const b = (typeof s.bg_prompt === "string" && s.bg_prompt.trim()) || "";
      if (!newScene && a && b && a !== b)
        warn.push(
          `${at}: 앞 컷과 장소 문구가 다르다(같은 장면이면 한 글자도 바꾸지 말고 복사, 장면이 바뀌면 webtoon.pageBreak를 줘라)`,
        );
    }
    if (s.sfx !== undefined && !SFX.includes(s.sfx)) bad.push(`${at}: sfx 「${s.sfx}」는 허용값이 아니다 (${SFX.join("|")})`);
    if (typeof s.text === "string" && [...s.text].length > 60)
      bad.push(`${at}: text가 ${[...s.text].length}자다 — 인쇄본에서 뒤가 «…»로 잘린다(60자 안쪽으로 쪼개라)`);
    if (!isFragment) {
      if (s.speaker !== undefined && s.speaker !== "narration" && !charById.has(s.speaker))
        bad.push(`${at}: speaker 「${s.speaker}」가 characters에 없다`);
      for (const id of s.chars || []) if (!charById.has(id)) bad.push(`${at}: chars의 「${id}」가 characters에 없다`);
    }
    const w = s.webtoon;
    if (w && typeof w === "object") {
      for (const k of Object.keys(w)) if (!WEBTOON_FIELDS.has(k)) warn.push(`${at}: webtoon에 없는 필드 「${k}」`);
      if (w.pageBreak && !(typeof w.caption === "string" && w.caption.trim()))
        warn.push(`${at}: pageBreak가 있는데 caption이 없다 — 장 이름이 목차에 안 나온다`);
      if (typeof w.line === "string" && w.line.trim())
        warn.push(
          `${at}: webtoon.line은 인쇄본에서 text «대신» 그려진다 — 손으로 고른 문구라면 정상이지만, ` +
            `소설 각색이라면 시사와 만화판의 대사가 갈린다`,
        );
      if (s.speaker === "narration" && (w.kind || w.tail))
        warn.push(`${at}: narration 컷의 kind·tail은 버려진다(꼬리 없는 캡션으로 조판된다)`);
    }
    const hasChoices = Array.isArray(s.choices) && s.choices.length > 0;
    if (hasChoices && s.next) bad.push(`${at}: choices와 next를 함께 썼다 — next는 무시된다`);
    if (hasChoices) for (const c of s.choices) if (!ids.has(c && c.next)) bad.push(`${at}: 선택지가 없는 컷 「${c && c.next}」을 가리킨다`);
    if (s.next && !ids.has(s.next)) bad.push(`${at}: next가 없는 컷 「${s.next}」을 가리킨다`);
    if (!s.next && !hasChoices) endings += 1;
  });
  if (!isFragment && scenes.length && endings === 0)
    bad.push("엔딩이 없다 — next가 없는 컷이 하나는 있어야 크레딧이 오른다");

  // 첫 컷에서 닿지 않는 컷 — 시사에서 나오지 않는다
  if (!isFragment && scenes.length) {
    const byId = new Map(scenes.map((s) => [s && s.id, s]));
    const seen = new Set();
    const stack = [scenes[0].id];
    while (stack.length) {
      const id = stack.pop();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      const s = byId.get(id);
      if (!s) continue;
      if (s.next) stack.push(s.next);
      for (const c of s.choices || []) stack.push(c && c.next);
    }
    const orphans = scenes.map((s) => s && s.id).filter((id) => id && !seen.has(id));
    if (orphans.length) warn.push(`첫 컷에서 닿지 않는 컷 ${orphans.length}개: ${orphans.slice(0, 6).join(", ")}`);
  }
  return { bad, warn };
}

const files = process.argv.slice(2).filter((a) => !a.startsWith("-"));
if (files.length === 0) {
  console.log("사용법: npm run lint:story -- 콘티.json [다른.json …]");
  process.exit(0);
}
let failed = 0;
for (const f of files) {
  const p = path.resolve(process.cwd(), f);
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(p, "utf-8"));
  } catch (e) {
    console.log(`✗ ${f} | JSON을 읽을 수 없다: ${String(e.message).slice(0, 90)}`);
    failed += 1;
    continue;
  }
  // 조각 판정: title이 없으면 이어쓰기 조각으로 본다(앱의 「스토리 이어서 만들기」가 받는 모양)
  const isFragment = "scenes" in raw && !("title" in raw);
  const parsed = parseStory(isFragment ? { title: "조각", style: "x", characters: [], scenes: raw.scenes } : raw);
  const rules = lintRules(raw.scenes ? raw : { scenes: [] }, isFragment);
  const nErr = parsed.errors.length + rules.bad.length;
  const nWarn = parsed.warnings.length + rules.warn.length;
  console.log(
    `${nErr ? "✗" : "○"} ${f}${isFragment ? " (이어쓰기 조각)" : ""} | 컷 ${(raw.scenes || []).length}개 · 파서 에러 ${parsed.errors.length} 경고 ${parsed.warnings.length} · 규칙 위반 ${rules.bad.length} 주의 ${rules.warn.length}`,
  );
  for (const e of parsed.errors) console.log(`   [파서·에러] ${e}`);
  for (const w of parsed.warnings) {
    // 조각은 배우를 부모 작품에서 물려받으므로 이 경고는 정상이다
    const okForFragment = isFragment && /캐스팅되지 않은 배우/.test(w);
    console.log(`   [파서·경고] ${w}${okForFragment ? " (조각이라면 정상 — 부모 작품의 배우)" : ""}`);
  }
  for (const b of rules.bad) console.log(`   [규칙·위반] ${b}`);
  for (const w of rules.warn) console.log(`   [규칙·주의] ${w}`);
  if (nErr) failed += 1;
  else if (!nWarn) console.log("   깨끗합니다 — 앱에 그대로 붙여넣어도 됩니다.");
}
if (failed) {
  console.log(`\n${failed}개 파일에 고칠 것이 있습니다.`);
  process.exit(1);
}
console.log("\n모두 통과했습니다.");
