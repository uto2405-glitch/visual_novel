/** story.json 검증. 구조 파손만 에러, 나머지는 경고. (타입은 ../types) */
import {
  reuseTarget,
  type Choice,
  type Scene,
  type Story,
  type StoryCharacter,
  type WebtoonCut,
} from "../types";

export interface ParseResult {
  story?: Story;
  errors: string[];
  warnings: string[];
}

export function isRecord(v: unknown): v is Record<string, unknown> {
  return Boolean(v) && typeof v === "object" && !Array.isArray(v);
}

/** 인쇄본 조판 설정 파싱 — 값이 이상하면 그 항목만 버리고 나머지는 살린다. */
/** 등장인물 장의 사진 크롭 위치 — 없거나 값이 이상하면 undefined(기본 크롭) */
function parseCastCrop(raw: unknown): { x?: "left" | "center" | "right"; y?: "top" | "center" | "bottom" } | undefined {
  if (!isRecord(raw)) return undefined;
  const x = (["left", "center", "right"] as const).find((v) => v === raw.x);
  const y = (["top", "center", "bottom"] as const).find((v) => v === raw.y);
  return x || y ? { ...(x ? { x } : {}), ...(y ? { y } : {}) } : undefined;
}

/**
 * 「이 컷부터 새 장」 — 이 한 글자에 장 전부가 달려 있다.
 *
 * 프롬프트는 `pageBreak:true`를 요구하지만 LLM은 쪽 번호처럼 `1`을 쓰거나 `"true"`로 써 보낸다.
 * 예전에는 `=== true`가 아니면 조용히 버렸다 — 20장짜리 대본이 한 장으로 들어와도
 * 아무 말이 없었고, 감독은 «장이 왜 안 나뉘지»만 남았다. 켜려는 뜻이 분명한 값은 받아 준다.
 * 끄는 값(false·0·"no"·"off"·빈 문자열)은 그대로 끈다 — 없는 장을 만들어 내면 더 나쁘다.
 * @returns [켜짐, 값을 고쳐 읽었는지]
 */
export function readPageBreak(v: unknown): [true | undefined, boolean] {
  if (v === true) return [true, false];
  if (v === undefined || v === null || v === false) return [undefined, false];
  if (typeof v === "number") return Number.isFinite(v) && v !== 0 ? [true, true] : [undefined, false];
  if (typeof v === "string") {
    const s = v.trim().toLowerCase();
    if (!s || ["false", "0", "no", "off", "n", "아니오", "없음"].includes(s)) return [undefined, false];
    return [true, true];
  }
  return [undefined, false];
}

function parseWebtoon(raw: unknown, tally?: { pageBreakFixed: number }): WebtoonCut | undefined {
  if (!isRecord(raw)) return undefined;
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : undefined);
  const pick = <T extends string>(v: unknown, allowed: readonly T[]): T | undefined =>
    allowed.find((a) => a === v);
  const [pageBreak, fixed] = readPageBreak(raw.pageBreak);
  if (fixed && tally) tally.pageBreakFixed += 1;
  const out: WebtoonCut = {
    caption: str(raw.caption),
    line: str(raw.line),
    pos: pick(raw.pos, ["tl", "tr", "bl", "br"] as const),
    kind: pick(raw.kind, ["say", "think", "shout"] as const),
    tail: pick(raw.tail, ["l", "c", "r", "none"] as const),
    pageBreak,
    textScale: [0.8, 1, 1.25].includes(Number(raw.textScale)) ? Number(raw.textScale) : undefined,
    crop: pick(raw.crop, ["left", "center", "right"] as const),
    fx: pick(raw.fx, ["speed", "focus", "flash"] as const),
  };
  return Object.values(out).some((v) => v !== undefined) ? out : undefined;
}

export function parseStory(input: unknown): ParseResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  if (!isRecord(input)) {
    return { errors: ["story.json 최상위는 객체여야 합니다."], warnings };
  }
  const raw = input;
  const title = typeof raw.title === "string" && raw.title.trim() ? raw.title.trim() : "";
  if (!title) warnings.push("title이 비어 있어 「무제」로 둡니다.");
  const style = typeof raw.style === "string" ? raw.style : "";
  const note = typeof raw.note === "string" && raw.note.trim() ? raw.note : undefined;
  const coverSubtitle =
    typeof raw.coverSubtitle === "string" && raw.coverSubtitle.trim()
      ? raw.coverSubtitle.trim()
      : undefined;
  const coverByline =
    typeof raw.coverByline === "string" && raw.coverByline.trim()
      ? raw.coverByline.trim()
      : undefined;
  if (!style) warnings.push("style이 비어 있습니다. 화풍을 정하면 얼굴이 더 안정됩니다.");

  const characters: StoryCharacter[] = [];
  if (raw.characters !== undefined) {
    if (!Array.isArray(raw.characters)) {
      errors.push("characters는 배열이어야 합니다.");
    } else {
      for (const cRaw of raw.characters) {
        // v0.8.0과 동일: 배열 요소도 통과시켜 id 검사에서 걸리게 한다
        if (!cRaw || typeof cRaw !== "object") {
          warnings.push("characters에 객체가 아닌 항목이 있어 건너뜁니다.");
          continue;
        }
        const c = cRaw as Record<string, unknown>;
        const id = typeof c.id === "string" ? c.id.trim() : "";
        if (!id) {
          warnings.push("id 없는 캐릭터를 건너뜁니다.");
          continue;
        }
        characters.push({
          id,
          name: typeof c.name === "string" && c.name ? c.name : id,
          ref: typeof c.ref === "string" && c.ref ? c.ref : undefined,
          look: typeof c.look === "string" && c.look ? c.look : undefined,
          castCrop: parseCastCrop(c.castCrop),
        });
      }
    }
  }

  /* 같은 ref를 적은 배우들 — ref는 캐스팅 사진의 열쇠라 겹치면 사진이 서로 덮어쓴다.
     읽기는 그대로 하고(대본을 고치는 일은 감독의 몫) 경고만 한다. 사진을 걸 때는 앱이 뒤의 배우를
     id 이름으로 갈라 둔다(scriptSlice.bindPhotoToChar). */
  {
    const byRef = new Map<string, string[]>();
    for (const c of characters) if (c.ref) byRef.set(c.ref, [...(byRef.get(c.ref) ?? []), c.name]);
    for (const [ref, names] of byRef) {
      if (names.length > 1) {
        warnings.push(
          `배우 ${names.map((n) => `「${n}」`).join("·")}의 ref가 같습니다(${ref}) — 캐스팅 사진이 서로 덮어씁니다. 사진을 걸 때 뒤의 배우는 id 이름으로 갈라 둡니다.`,
        );
      }
    }
  }

  if (!Array.isArray(raw.scenes)) {
    errors.push("scenes 배열이 필요합니다.");
    return { errors, warnings };
  }
  const scenes: Scene[] = [];
  const seen = new Set<string>();
  /** 고쳐 읽은 「새 장」 값의 수 — 컷마다 경고하면 스무 줄이 되므로 한 줄로 모은다 */
  const tally = { pageBreakFixed: 0 };
  for (const sRaw of raw.scenes) {
    // v0.8.0과 동일: 배열 요소는 건너뛰지 않고 id 검사(하드 에러)로 흘려보낸다 —
    // 잘려나간 대본이 경고만 띄우고 기존 대본을 덮어쓰는 일을 막는다
    if (!sRaw || typeof sRaw !== "object") {
      warnings.push("scenes에 객체가 아닌 항목이 있어 건너뜁니다.");
      continue;
    }
    const s = sRaw as Record<string, unknown>;
    const id = typeof s.id === "string" ? s.id.trim() : "";
    if (!id) {
      errors.push("id 없는 장면이 있습니다. 모든 장면에는 id가 필요합니다.");
      continue;
    }
    if (seen.has(id)) {
      errors.push(`장면 id가 중복됩니다: ${id}`);
      continue;
    }
    seen.add(id);
    const SHOTS = ["full", "focus", "back", "wide", "action", "portrait"] as const;
    const shot = SHOTS.find((x) => x === s.shot);
    if (s.shot !== undefined && !shot) {
      warnings.push(`${id}: shot은 full/focus/back/wide/action/portrait 중 하나만 씁니다.`);
    }
    let choices: Choice[] | undefined;
    if (Array.isArray(s.choices)) {
      choices = [];
      for (const ch of s.choices) {
        if (!isRecord(ch)) continue;
        if (typeof ch.label === "string" && typeof ch.next === "string") {
          choices.push({ label: ch.label, next: ch.next });
        }
      }
      if (choices.length === 0) choices = undefined;
    }
    scenes.push({
      id,
      bg_prompt: typeof s.bg_prompt === "string" ? s.bg_prompt : undefined,
      bg: typeof s.bg === "string" ? s.bg : undefined,
      shot,
      chars: Array.isArray(s.chars)
        ? s.chars.filter((x): x is string => typeof x === "string")
        : undefined,
      pose: typeof s.pose === "string" ? s.pose : undefined,
      emotion: typeof s.emotion === "string" ? s.emotion : undefined,
      text: typeof s.text === "string" ? s.text : undefined,
      speaker: typeof s.speaker === "string" ? s.speaker : undefined,
      sfx: typeof s.sfx === "string" ? s.sfx : undefined,
      bgm: typeof s.bgm === "boolean" ? s.bgm : undefined,
      next: typeof s.next === "string" ? s.next : undefined,
      choices,
      hold: s.hold === true ? true : undefined,
      placeholder: s.placeholder === true ? true : undefined,
      // 인쇄본 조판 설정 — 왕복 보존해야 고급 JSON 편집·AI 초안이 살아남는다
      webtoon: parseWebtoon(s.webtoon, tally),
    });
  }
  if (scenes.length === 0) errors.push("장면이 하나도 없습니다.");
  if (tally.pageBreakFixed > 0) {
    warnings.push(
      `webtoon.pageBreak가 true가 아닌 값(예: 1, "true")으로 적힌 컷 ${tally.pageBreakFixed}개를 ` +
        "「이 컷부터 새 장」으로 읽었습니다. 장이 잘못 나뉘면 컷 카드의 ⏎ 로 끄세요.",
    );
  }

  const charIds = new Set(characters.map((c) => c.id));
  for (const sc of scenes) {
    if (sc.next && !seen.has(sc.next)) {
      warnings.push(`${sc.id}: next가 가리키는 장면이 없습니다 (${sc.next}).`);
    }
    for (const ch of sc.choices ?? []) {
      if (!seen.has(ch.next)) {
        warnings.push(`${sc.id}: 선택지가 가리키는 장면이 없습니다 (${ch.next}).`);
      }
    }
    const target = reuseTarget(sc);
    if (target && !seen.has(target)) {
      warnings.push(`${sc.id}: reuse 원본 장면이 없습니다 (${target}).`);
    }
    for (const cid of sc.chars ?? []) {
      if (!charIds.has(cid)) {
        warnings.push(`${sc.id}: 캐스팅되지 않은 배우 id입니다 (${cid}).`);
      }
    }
  }

  if (errors.length > 0) return { errors, warnings };
  return {
    story: {
      title: title || "무제",
      style,
      ...(note ? { note } : {}),
      ...(coverSubtitle ? { coverSubtitle } : {}),
      ...(coverByline ? { coverByline } : {}),
      characters,
      scenes,
    },
    errors,
    warnings,
  };
}
