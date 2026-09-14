/**
 * 장(chapter) — 한 곳에서만 센다.
 *
 * 기준은 컷의 「⏎ 새 장에서 시작」(`webtoon.pageBreak`) 하나뿐이고,
 * 장 이름은 그 장 첫 컷의 「컷 제목」(`webtoon.caption`)이다.
 * 대본실·촬영장·시사실·콜시트·인쇄본이 각자 세던 것을 여기로 모았다 —
 * 같은 규칙을 네 군데에 베껴 두면 «인쇄본의 3장»과 «촬영장의 3장»이 언젠가 어긋난다.
 */
import type { Scene } from "../types";

export interface ChapterRange {
  /** 0부터 — 화면에 보이는 「3장」은 index 2 */
  index: number;
  /** 장 이름(첫 컷 제목) 또는 「N장」 */
  title: string;
  /** 이 장에 속한 컷 id, 대본 순서대로 */
  ids: string[];
  /** 장의 첫 컷 id */
  firstId: string;
  /** scenes 배열에서 이 장이 시작하는 자리 */
  start: number;
  /** scenes 배열에서 이 장이 끝나는 자리(다음 장의 start) */
  end: number;
}

/** 대본 순서대로 장을 끊는다. 컷이 하나라도 있으면 장은 최소 하나. */
export function chapterRanges(scenes: Scene[]): ChapterRange[] {
  const out: ChapterRange[] = [];
  scenes.forEach((sc, i) => {
    const opens = sc.webtoon?.pageBreak === true;
    if (opens || out.length === 0) {
      out.push({
        index: out.length,
        title: (sc.webtoon?.caption ?? "").trim() || `${out.length + 1}장`,
        ids: [sc.id],
        firstId: sc.id,
        start: i,
        end: i + 1,
      });
    } else {
      const cur = out[out.length - 1];
      cur.ids.push(sc.id);
      cur.end = i + 1;
    }
  });
  return out;
}

/** 이 컷이 속한 장 */
export function chapterOf(ranges: ChapterRange[], sceneId: string): ChapterRange | undefined {
  return ranges.find((c) => c.ids.includes(sceneId));
}

/** 장이 둘 이상일 때만 화면에 「장」 줄을 낸다 — 한 장짜리 작품에 장 UI는 군더더기다 */
export function hasChapters(ranges: ChapterRange[]): boolean {
  return ranges.length >= 2;
}
