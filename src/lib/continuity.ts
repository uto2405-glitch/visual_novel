/**
 * 조감독 리포트 — 대본의 연속성 검사.
 * 촬영 전에 잡아야 할 것들: 끊어진 연결, 도달 불가 컷, 얼굴 없는 배우, reuse 오류.
 * 전부 읽기 전용 검사이며 아무것도 자동으로 고치지 않는다 — 판정은 감독의 몫.
 */
import { reuseTarget, type ProjectRecord } from "../types";

export interface ContinuityIssue {
  /** 관련 컷 id (전역 이슈면 null) */
  sceneId: string | null;
  severity: "warn" | "info";
  message: string;
}

export function continuityReport(p: ProjectRecord): ContinuityIssue[] {
  const issues: ContinuityIssue[] = [];
  const { story } = p;
  const ids = new Set(story.scenes.map((s) => s.id));
  const byId = new Map(story.scenes.map((s) => [s.id, s] as const));
  const charIds = new Set(story.characters.map((c) => c.id));

  /* 직접 쓴 프롬프트 — 그 컷은 조립을 건너뛰므로(engine.effectivePrompt) 대본의 어떤 변경도
     닿지 않는다: 화풍(프리셋 포함)·배우 외모·장소·카메라 고정·얼굴 고정 문구 전부.
     예전에는 이 사실을 세거나 알려 주는 자리가 앱에 없어서, 화풍을 갈아입힌 감독이 «왜 이 컷만
     옛 톤인가»를 스스로 알아낼 방법이 없었다(실측으로 잡았다). 리포트가 먼저 말한다. */
  const frozen = story.scenes.filter((s) => (p.cuts[s.id]?.customPrompt ?? "").trim()).map((s) => s.id);
  if (frozen.length > 0) {
    issues.push({
      sceneId: frozen[0],
      severity: "info",
      message:
        `프롬프트를 직접 고친 컷이 ${frozen.length}개 있습니다(${frozen.slice(0, 3).join(", ")}${frozen.length > 3 ? " 외" : ""}) — ` +
        "그 컷들에는 화풍·배우 외모·장소·카메라 고정 변경이 닿지 않습니다. 촬영장의 「✎ 직접 쓴」 필터에서 되돌릴 수 있어요.",
    });
  }

  // 배우: 등장하는데 캐스팅 사진이 없는 경우 — 얼굴 고정이 안 된다
  const appearing = new Set<string>();
  for (const sc of story.scenes) for (const cid of sc.chars ?? []) appearing.add(cid);
  for (const c of story.characters) {
    if (!appearing.has(c.id)) continue;
    if (!c.ref) {
      issues.push({
        sceneId: null,
        severity: "warn",
        message: `배우 「${c.name}」에게 ref 파일명이 없습니다 — 캐스팅 사진을 걸 수 없어 얼굴이 컷마다 달라질 수 있어요.`,
      });
    } else if (!p.charAssets[c.ref]) {
      issues.push({
        sceneId: null,
        severity: "warn",
        message: `배우 「${c.name}」이 얼굴 없음 상태입니다 — ${c.ref} 사진을 캐스팅하면 얼굴이 고정됩니다.`,
      });
    }
  }

  for (const sc of story.scenes) {
    if (sc.next && !ids.has(sc.next)) {
      issues.push({
        sceneId: sc.id,
        severity: "warn",
        message: `${sc.id}: next가 가리키는 컷(${sc.next})이 대본에 없습니다 — 시사가 여기서 끊깁니다.`,
      });
    }
    if (sc.next === sc.id) {
      issues.push({
        sceneId: sc.id,
        severity: "warn",
        message: `${sc.id}: next가 자기 자신입니다 — 시사가 이 컷에서 맴돕니다.`,
      });
    }
    for (const ch of sc.choices ?? []) {
      if (!ch.label.trim()) {
        issues.push({
          sceneId: sc.id,
          severity: "info",
          message: `${sc.id}: 문구가 빈 선택지가 있습니다 — 시사에서 「…」로 표시됩니다.`,
        });
      }
      if (!ids.has(ch.next)) {
        issues.push({
          sceneId: sc.id,
          severity: "warn",
          message: `${sc.id}: 선택지 「${ch.label}」이 없는 컷(${ch.next})으로 이어집니다.`,
        });
      }
    }
    for (const cid of sc.chars ?? []) {
      if (!charIds.has(cid)) {
        issues.push({
          sceneId: sc.id,
          severity: "warn",
          message: `${sc.id}: 캐스팅되지 않은 배우 id(${cid})가 등장합니다.`,
        });
      }
    }
    if (sc.speaker && sc.speaker !== "narration" && !charIds.has(sc.speaker)) {
      issues.push({
        sceneId: sc.id,
        severity: "warn",
        message: `${sc.id}: 화자(${sc.speaker})가 배우 명단에 없습니다.`,
      });
    }
    const target = reuseTarget(sc);
    // 카메라 고정 + reuse는 서로를 무효로 만든다: reuse는 원본 그림을 그대로 복사하므로
    // 자세가 바뀌지 않는다. v0.45까지 앱이 이 조합을 권했으니(오류), 남아 있는 대본에 알려준다.
    if (target && sc.hold) {
      issues.push({
        sceneId: sc.id,
        severity: "warn",
        message: `${sc.id}: 🔒 카메라 고정과 배경 reuse를 함께 썼습니다 — reuse는 ${target}의 그림을 그대로 복사하므로 자세가 바뀌지 않습니다. 배경 문구(bg_prompt)를 같게 적고 reuse를 비우세요.`,
      });
    }
    if (target) {
      if (!ids.has(target)) {
        issues.push({
          sceneId: sc.id,
          severity: "warn",
          message: `${sc.id}: reuse 원본 컷(${target})이 대본에 없습니다.`,
        });
      } else {
        // reuse 사슬에 고리가 있는지 (자기 자신 포함).
        // seen에는 매번 새 컷이 들어가므로 N번 안에 반드시 끝난다 — 길이 제한 없음.
        const seen = new Set<string>([sc.id]);
        let cur = target;
        let looped = false;
        for (let i = 0; i <= story.scenes.length; i++) {
          if (seen.has(cur)) {
            looped = true;
            break;
          }
          seen.add(cur);
          const nextScene = byId.get(cur);
          const nextTarget = nextScene ? reuseTarget(nextScene) : null;
          if (!nextTarget) break;
          cur = nextTarget;
        }
        if (looped) {
          issues.push({
            sceneId: sc.id,
            severity: "warn",
            message: `${sc.id}: reuse가 고리를 이룹니다 — 어느 컷도 원본이 될 수 없어 촬영이 막힙니다.`,
          });
        }
      }
    }
    if (!sc.text?.trim() && !sc.placeholder) {
      issues.push({
        sceneId: sc.id,
        severity: "info",
        message: `${sc.id}: 대사가 비어 있는 컷입니다.`,
      });
    }
  }

  // 시작점에서 도달할 수 없는 컷 (next + choices를 따라 BFS)
  if (story.scenes.length > 0) {
    const reached = new Set<string>();
    const queue = [story.scenes[0].id];
    while (queue.length > 0) {
      const id = queue.pop() as string;
      if (reached.has(id)) continue;
      reached.add(id);
      const sc = byId.get(id);
      if (!sc) continue;
      if (sc.next && ids.has(sc.next)) queue.push(sc.next);
      for (const ch of sc.choices ?? []) if (ids.has(ch.next)) queue.push(ch.next);
    }
    for (const sc of story.scenes) {
      if (!reached.has(sc.id)) {
        issues.push({
          sceneId: sc.id,
          severity: "info",
          message: `${sc.id}: 첫 컷에서 이어지지 않는 컷입니다 — 시사에서는 나오지 않아요.`,
        });
      }
    }
  }

  return issues;
}
