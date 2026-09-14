/** UI 슬라이스 — 탭, 토스트, 확인/입력 모달, 설정(토큰). */
import * as db from "../../lib/db";
import type { Get, Set, UiSlice } from "../types";
import type { Engine } from "../engine";

let idCounter = 1;
const nextId = () => idCounter++;

const TOAST_MS = 4200;

export function createUiSlice(set: Set, get: Get, _engine: Engine): UiSlice {
  void _engine;
  return {
    tab: "script",
    toasts: [],
    confirmReq: null,
    promptReq: null,
    settingsOpen: false,
    advancedOpen: false,
    printOpen: false,
    deskChapter: "",
    stageChapter: "",
    token: db.getToken(),

    setTab: (tab) => set({ tab }),
    setDeskChapter: (firstSceneId) => set({ deskChapter: firstSceneId }),
    setStageChapter: (firstSceneId) => set({ stageChapter: firstSceneId }),

    toast: (text, kind = "info") => {
      const id = nextId();
      set((s) => ({ toasts: [...s.toasts, { id, text, kind }] }));
      setTimeout(() => get().dismissToast(id), TOAST_MS);
    },

    dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

    confirm: (opts) =>
      new Promise<boolean>((resolve) => {
        set({ confirmReq: { ...opts, id: nextId(), resolve } });
      }),

    promptText: (opts) =>
      new Promise<string | null>((resolve) => {
        set({ promptReq: { ...opts, id: nextId(), resolve } });
      }),

    answerConfirm: (ok) => {
      const req = get().confirmReq;
      set({ confirmReq: null });
      req?.resolve(ok);
    },

    answerPrompt: (v) => {
      const req = get().promptReq;
      set({ promptReq: null });
      req?.resolve(v);
    },

    setSettingsOpen: (open) => set({ settingsOpen: open }),
    setAdvancedOpen: (open) => set({ advancedOpen: open }),
    setPrintOpen: (open) => set({ printOpen: open }),

    setToken: (token) => {
      db.setToken(token.trim());
      set({ token: token.trim() });
    },
  };
}
