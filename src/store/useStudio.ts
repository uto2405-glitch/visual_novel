/**
 * 스튜디오 전역 상태 — 단일 zustand 스토어의 조립 지점.
 *
 * 내부 기계는 engine.ts, 액션은 slices/*에 있다. set/get은 전부 같은 스토어를
 * 가리키므로 원자성은 분할 전과 동일하다.
 *
 * 계약 요약:
 *  - 「오늘 촬영분 넣기」= story + 배우 사진 + 생성 이미지 + 컷 상태 + 시사 커서 한 묶음
 *  - 1초 디바운스 자동저장, 전환 전 자동저장
 *  - 「전부 다시」는 존재하지 않는다. 재촬영·판정은 이전 그림을 takes로 남긴다
 *  - 시사(플레이) 경로는 MakeFun API를 호출하지 않는다
 */
import { create } from "zustand";
import { createEngine } from "./engine";
import { createUiSlice } from "./slices/uiSlice";
import { createProjectSlice } from "./slices/projectSlice";
import { createScriptSlice } from "./slices/scriptSlice";
import { createStageSlice } from "./slices/stageSlice";
import { createPlaySlice } from "./slices/playSlice";
import type { StudioState } from "./types";

export type {
  BatchState,
  ConfirmRequest,
  PromptRequest,
  StudioState,
  Tab,
  ToastItem,
} from "./types";

export const useStudio = create<StudioState>((set, get) => {
  const engine = createEngine(set, get);
  return {
    ...createUiSlice(set, get, engine),
    ...createProjectSlice(set, get, engine),
    ...createScriptSlice(set, get, engine),
    ...createStageSlice(set, get, engine),
    ...createPlaySlice(set, get, engine),
  };
});

/** 선택지 클릭 — choiceHistory에 기록하고 다음 장면으로. */
export function chooseNext(label: string, next: string) {
  const s = useStudio.getState();
  useStudio.setState({ choiceHistory: [...s.choiceHistory, label] });
  s.showScene(next);
}

/** 확인/입력/설정 중 하나라도 떠 있는가 — 전역 키 핸들러의 공용 가드. */
export function anyModalOpen(): boolean {
  const s = useStudio.getState();
  return Boolean(s.confirmReq || s.promptReq || s.settingsOpen || s.printOpen);
}
