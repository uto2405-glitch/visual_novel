/** 시사실 슬라이스 — 재생 커서, 히스토리, 세이브 슬롯, 엔딩. API 호출 없음. */
import * as db from "../../lib/db";
import { setAmbienceMaster } from "../../lib/ambience";
import { startMusic, stopMusic } from "../../lib/music";
import type { SaveSlot, Scene } from "../../types";
import type { Get, PlaySlice, Set } from "../types";
import type { Engine } from "../engine";

const LS_TYPE = "vn-studio:typeMs";
const LS_FONT = "vn-studio:fontScale";
function readNum(key: string, fallback: number, allowed: number[]): number {
  try {
    const v = Number(localStorage.getItem(key));
    return allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

export function createPlaySlice(set: Set, get: Get, engine: Engine): PlaySlice {
  return {
    playSceneId: null,
    playHistory: [],
    choiceHistory: [],
    playBlockedAt: null,
    playEnded: false,
    playStop: null,
    playChapterEnd: null,
    autoPlay: false,
    playEpoch: 0,
    ambienceOn: false,
    musicOn: false,
    saveSlots: [null, null, null],
    typeMs: readNum(LS_TYPE, 26, [40, 26, 12]),
    fontScale: readNum(LS_FONT, 1, [1, 1.25]),

    setTypeMs: (ms) => {
      set({ typeMs: ms });
      try {
        localStorage.setItem(LS_TYPE, String(ms));
      } catch {
        /* 취향 기억은 장식 */
      }
    },

    setFontScale: (f) => {
      set({ fontScale: f });
      try {
        localStorage.setItem(LS_FONT, String(f));
      } catch {
        /* 취향 기억은 장식 */
      }
    },

    enterScreening: () => {
      // 다른 방에서 건너올 때(「▶ 여기부터 시사」 등)는 장 단위 멈춤을 들고 오지 않는다
      set({ tab: "screening", playBlockedAt: null, playStop: null, playChapterEnd: null });
    },

    showScene: (sceneId) => {
      if (!engine.sceneOf(sceneId)) {
        // 대본에 없는 컷으로 이어지는 next — 도달 가능한 필름은 여기서 끝난 것이다
        set({ playEnded: true });
        return;
      }
      if (!engine.hasImage(sceneId)) {
        // 빈 컷에 닿았다 — 자동 상영도 여기서 멈춰야 안내가 반복되지 않는다
        set({ playBlockedAt: sceneId, autoPlay: false });
        return;
      }
      set((s) => ({
        playSceneId: sceneId,
        playHistory:
          s.playSceneId && s.playSceneId !== sceneId
            ? [...s.playHistory, s.playSceneId]
            : s.playHistory,
        playBlockedAt: null,
        playEnded: false,
        playEpoch: s.playEpoch + 1,
      }));
      engine.patchProject((p) => ({ ...p, currentSceneId: sceneId }));
      engine.scheduleAutosave();
    },

    /**
     * 이 장까지만 상영 — 「장부터」는 있었는데 「장까지」가 없었다.
     * 연재를 장 단위로 검토할 때는 다음 장으로 넘어가 버리면 흐름이 끊긴다.
     * 멈춤은 «막이 내린 것»(엔딩 크레딧)이 아니라 «여기까지 봤다»이므로 따로 알린다.
     */
    playChapter: (firstId, lastId, title) => {
      get().showScene(firstId);
      set({ playStop: { id: lastId, title }, playChapterEnd: null });
    },

    clearChapterStop: () => set({ playStop: null, playChapterEnd: null }),

    /** 장 끝에서 멈춘 뒤 «이어서 보기» — 멈춤을 풀고 다음 컷으로 */
    resumePastChapter: () => {
      set({ playStop: null, playChapterEnd: null });
      get().advancePlay();
    },

    advancePlay: () => {
      const s = get();
      if (s.playEnded) return; // 크레딧이 흐르는 중 — 클릭은 dismissEnd가 받는다
      // 장의 마지막 컷에서 한 번 더 넘기면 «여기까지»를 알리고 멈춘다.
      // 안내가 떠 있는데 또 넘기면(Space 등) 그건 «이어서 보기»다 — 안내를 걷고 이어 간다.
      // (걷지 않으면 다음 장이 흐르는 동안 안내가 화면에 남는다)
      if (s.playStop && s.playSceneId === s.playStop.id) {
        if (!s.playChapterEnd) {
          set({ playChapterEnd: s.playStop.title, autoPlay: false });
          return;
        }
        set({ playStop: null, playChapterEnd: null });
      }
      const scene = s.playSceneId ? engine.sceneOf(s.playSceneId) : undefined;
      if (!scene) {
        // 처음부터
        const first = s.project?.story.scenes[0];
        if (first) get().showScene(first.id);
        return;
      }
      if (scene.choices?.length) return; // 선택지는 버튼으로만
      if (scene.next) {
        get().showScene(scene.next);
      } else {
        set({ playEnded: true }); // 막이 내렸다 — 엔딩 크레딧
      }
    },

    backPlay: () => {
      set((s) => {
        // 크레딧이 흐르는 중의 「이전」은 크레딧만 걷고 마지막 컷으로 돌아간다
        if (s.playEnded) return { playEnded: false, playEpoch: s.playEpoch + 1 };
        if (s.playHistory.length === 0) return {};
        const prev = s.playHistory[s.playHistory.length - 1];
        return {
          playSceneId: prev,
          playHistory: s.playHistory.slice(0, -1),
          playBlockedAt: null,
          playEpoch: s.playEpoch + 1,
        };
      });
    },

    restartPlay: () => {
      const first = get().project?.story.scenes[0];
      set({
        playHistory: [],
        choiceHistory: [],
        playSceneId: null,
        playBlockedAt: null,
        playEnded: false,
        playStop: null,
        playChapterEnd: null,
      });
      if (first) get().showScene(first.id);
    },

    /** 이어하기 — 시사 커서(마지막 OK 장면)부터. 이미지 없으면 촬영장으로 안내. */
    continuePlay: () => {
      const s = get();
      const p = s.project;
      if (!p) return;
      const cursor = p.currentSceneId;
      if (cursor && engine.hasImage(cursor)) {
        // 이어하기는 «작품을 이어 본다»는 뜻이다 — 장 단위 멈춤은 여기서 푼다
        set({
          playHistory: [],
          choiceHistory: [],
          playSceneId: null,
          playEnded: false,
          playStop: null,
          playChapterEnd: null,
        });
        get().showScene(cursor);
        return;
      }
      // 커서가 없거나 이미지가 없으면: 처음부터 이어지는 OK 구간의 마지막
      let cur = p.story.scenes[0];
      let lastOk: Scene | null = null;
      const guard = new Set<string>();
      while (cur && !guard.has(cur.id)) {
        guard.add(cur.id);
        if (!engine.hasImage(cur.id)) break;
        lastOk = cur;
        if (cur.choices?.length || !cur.next) break;
        const nxt = p.story.scenes.find((sc) => sc.id === cur.next);
        if (!nxt) break;
        cur = nxt;
      }
      if (lastOk) {
        set({ playHistory: [], choiceHistory: [], playSceneId: null, playEnded: false });
        get().showScene(lastOk.id);
      } else {
        set({ playBlockedAt: cursor ?? p.story.scenes[0]?.id ?? null });
      }
    },

    clearBlocked: () => set({ playBlockedAt: null }),

    dismissEnd: () => {
      set({ playEnded: false, playSceneId: null, playHistory: [], choiceHistory: [] });
    },

    setAutoPlay: (on) => set({ autoPlay: on }),

    setAmbienceOn: (on) => {
      setAmbienceMaster(on); // 사용자 제스처 안에서 호출되므로 AudioContext 시작 가능
      set({ ambienceOn: on });
    },

    setMusicOn: (on) => {
      if (on) startMusic();
      else stopMusic();
      set({ musicOn: on });
    },

    saveToSlot: async (slot) => {
      const s = get();
      const p = s.project;
      if (!p || !s.playSceneId) {
        get().toast("지금 보고 있는 장면이 없어 저장할 수 없습니다.");
        return;
      }
      const existing = s.saveSlots[slot - 1];
      if (existing) {
        const ok = await get().confirm({
          title: `슬롯 ${slot} 덮어쓰기`,
          body: "이 슬롯의 이전 세이브를 덮어씁니다.",
          okLabel: "덮어쓰기",
          danger: true,
        });
        if (!ok) return;
      }
      const data: SaveSlot = {
        projectId: p.id,
        sceneId: s.playSceneId,
        choiceHistory: [...s.choiceHistory],
        timestamp: Date.now(),
      };
      await db.putSaveSlot(slot, data);
      set((cur) => {
        const slots = [...cur.saveSlots];
        slots[slot - 1] = data;
        return { saveSlots: slots };
      });
      get().toast(`슬롯 ${slot}에 저장했습니다.`, "ok");
    },

    loadFromSlot: async (slot) => {
      const s = get();
      const data = s.saveSlots[slot - 1];
      if (!data) {
        get().toast("빈 슬롯입니다.");
        return;
      }
      if (!engine.hasImage(data.sceneId)) {
        set({ playBlockedAt: data.sceneId });
        get().toast("이 세이브의 장면은 아직 촬영 전입니다. 촬영장에서 찍어주세요.");
        return;
      }
      set({
        playHistory: [],
        choiceHistory: [...data.choiceHistory],
        playSceneId: null,
        playEnded: false,
      });
      get().showScene(data.sceneId);
      get().toast(`슬롯 ${slot}에서 이어봅니다.`);
    },

    deleteSlot: async (slot) => {
      const s = get();
      const p = s.project;
      if (!p) return;
      if (!s.saveSlots[slot - 1]) return;
      const ok = await get().confirm({
        title: `슬롯 ${slot} 지우기`,
        body: "이 세이브를 지웁니다.",
        okLabel: "지우기",
        danger: true,
      });
      if (!ok) return;
      await db.deleteSaveSlot(p.id, slot);
      set((cur) => {
        const slots = [...cur.saveSlots];
        slots[slot - 1] = null;
        return { saveSlots: slots };
      });
      get().toast(`슬롯 ${slot}을 비웠습니다.`);
    },
  };
}
