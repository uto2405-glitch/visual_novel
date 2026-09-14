/** 컴포넌트 계층 훅 — 스토어를 아는 훅은 lib/이 아니라 여기에 둔다.
 *  카드류가 쓰는 훅은 협소 구독: 다른 컷이 바뀌어도 리렌더되지 않는다. */
import { useStudio } from "../store/useStudio";
import { useObjectUrl } from "../lib/hooks";
import type { ProjectRecord, StoryCharacter } from "../types";

/**
 * 열려 있는 프로젝트. 각 방의 루트가 null을 걸러낸 다음에만 쓴다 —
 * 여기서 던지면 가드가 빠진 것이므로 조용한 undefined 접근보다 낫다.
 * 주의: 프로젝트 전체를 구독하므로 모든 변경에 리렌더된다 — 목록/패널용.
 * 카드류는 아래의 협소 훅을 쓸 것.
 */
export function useProject(): ProjectRecord {
  const project = useStudio((s) => s.project);
  if (!project) {
    throw new Error("useProject: 프로젝트가 열려 있지 않습니다 (가드 컴포넌트 누락).");
  }
  return project;
}

/** 배우의 캐스팅 사진 — CastRow/FaceCheck/크레딧이 공유한다. (협소 구독) */
export function useCharPhoto(charId: string): {
  char: StoryCharacter | undefined;
  url: string | null;
} {
  const char = useStudio((s) =>
    s.project?.story.characters.find((c) => c.id === charId),
  );
  const key = useStudio((s) => {
    const c = s.project?.story.characters.find((x) => x.id === charId);
    return c?.ref ? s.project?.charAssets[c.ref] : undefined;
  });
  const blob = useStudio((s) => (key ? s.blobs[key] : undefined));
  const url = useObjectUrl(blob);
  return { char, url };
}

/** 컷의 현재 이미지 Blob → object URL. (협소 구독 — 그 컷의 키가 바뀔 때만) */
export function useCutImageUrl(sceneId: string): string | null {
  const key = useStudio((s) => s.project?.cuts[sceneId]?.imageKey);
  const blob = useStudio((s) => (key ? s.blobs[key] : undefined));
  return useObjectUrl(blob);
}

/** 컷의 무빙(영상) Blob → object URL. 없으면 null — 시사실은 이미지로 폴백. */
export function useCutVideoUrl(sceneId: string): string | null {
  const key = useStudio((s) => s.project?.cuts[sceneId]?.videoKey);
  const blob = useStudio((s) => (key ? s.blobs[key] : undefined));
  return useObjectUrl(blob);
}
