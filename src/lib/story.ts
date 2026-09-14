/** 대본 조회 유틸 — 여러 컴포넌트가 공유한다. */
import type { Scene, Story } from "../types";

/**
 * 화자 표시 이름. 내레이션(또는 비어 있음)이면 "".
 * 명단에 없는 id는 id 그대로 보여준다 (조감독 리포트가 따로 경고한다).
 */
export function speakerName(story: Story, scene: Scene): string {
  if (!scene.speaker || scene.speaker === "narration") return "";
  return story.characters.find((c) => c.id === scene.speaker)?.name ?? scene.speaker;
}
