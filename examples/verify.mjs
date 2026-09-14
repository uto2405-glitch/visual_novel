/**
 * 예시 JSON 검증 — 실제 앱 파서(parseStory)로 확인한다. 실행: npm run verify:examples
 * append(이어쓰기) fragment는 full 예시의 배우를 물려받는 실제 시나리오로 검증한다.
 */
import { parseStory } from "../src/lib/parse-story.ts";
import fs from "node:fs";
import path from "node:path";

// 번들되어 data: URL로 실행되므로 import.meta.url이 아니라 cwd 기준으로 examples를 찾는다
const dir = path.resolve(process.cwd(), "examples");
const full = JSON.parse(fs.readFileSync(path.join(dir, "story.full.example.json"), "utf-8"));
let bad = 0;

for (const f of fs.readdirSync(dir).filter((n) => n.endsWith(".example.json")).sort()) {
  const raw = JSON.parse(fs.readFileSync(path.join(dir, f), "utf-8"));
  const isFragment = !("title" in raw);
  // 이어쓰기 fragment는 full의 배우 명단을 물려받아 병합된다 (appendStoryJson과 동일)
  const input = isFragment
    ? { title: full.title, style: full.style, characters: full.characters, scenes: raw.scenes }
    : raw;
  const r = parseStory(input);
  const ok = Boolean(r.story) && r.errors.length === 0 && r.warnings.length === 0;
  if (!ok) bad++;
  console.log(
    `${ok ? "PASS" : "FAIL"} | ${f} | scenes=${r.story?.scenes.length ?? 0} errors=${r.errors.length} warnings=${r.warnings.length}`,
  );
  for (const e of r.errors) console.log("   ✗ error:", e);
  for (const w of r.warnings) console.log("   ! warning:", w);

  // 필드 왕복 보존 — 파서가 조용히 버리는 필드가 없어야 한다
  if (!isFragment && r.story) {
    const src = raw.scenes ?? [];
    const got = r.story.scenes;
    const lost = [];
    for (let i = 0; i < src.length; i++) {
      for (const key of ["webtoon", "sfx", "bgm", "shot", "hold", "chars", "pose", "emotion", "bg", "bg_prompt"]) {
        if (src[i][key] !== undefined && got[i]?.[key] === undefined) lost.push(`${src[i].id}.${key}`);
      }
      if (src[i].webtoon?.caption && got[i]?.webtoon?.caption !== src[i].webtoon.caption) {
        lost.push(`${src[i].id}.webtoon.caption(값 불일치)`);
      }
      // 꼬리 방향은 감독의 판정이다 — 왕복에서 사라지면 조판이 달라진다
      if (src[i].webtoon?.tail && got[i]?.webtoon?.tail !== src[i].webtoon.tail) {
        lost.push(`${src[i].id}.webtoon.tail(값 불일치)`);
      }
    }
    // 표지 부제가 사라지면 표지가 「N컷」으로 되돌아간다
    if (raw.coverSubtitle && r.story.coverSubtitle !== raw.coverSubtitle) {
      lost.push(`coverSubtitle(${raw.coverSubtitle} → ${r.story.coverSubtitle})`);
    }
    // 배우의 크롭 위치도 감독의 판정이다 (등장인물 장에서 얼굴이 어디 남는지가 달라진다)
    const srcChars = raw.characters ?? [];
    const gotChars = r.story.characters ?? [];
    for (let i = 0; i < srcChars.length; i++) {
      const want = JSON.stringify(srcChars[i]?.castCrop ?? null);
      const has = JSON.stringify(gotChars[i]?.castCrop ?? null);
      if (want !== has) lost.push(`characters[${i}].castCrop(${want} → ${has})`);
    }
    if (lost.length) {
      bad++;
      console.log("FAIL | 필드 왕복 보존 |", lost.join(", "));
    } else {
      console.log("     | 필드 왕복 보존 OK (webtoon·sfx·bgm·shot 등)");
    }
  }
}
console.log(bad ? `\n${bad}개 예시가 검증에 실패했습니다.` : "\n모든 예시가 파서 검증을 통과했습니다 (에러·경고 0).");
process.exit(bad ? 1 : 0);
