/**
 * 스토어 엔진 — 슬라이스들이 공유하는 내부 기계.
 * 저장(디바운스 자동저장 포함), 프로젝트 적재, 한 컷 촬영, 배치 큐, 중단 관리.
 *
 * 불변식:
 *  - 이미지는 절대 덮어쓰지 않는다 (commitImage가 이전 그림을 takes로 민다)
 *  - 프로젝트가 바뀌면 어떤 진행 중 촬영도 그 프로젝트에 커밋되지 않는다
 *    (stopAllShooting + stillOnProject 가드)
 *  - 시사(플레이) 경로는 이 파일의 촬영 함수를 호출하지 않는다
 */
import * as db from "../lib/db";
import { cloneImageBlob } from "../lib/blob";
import { assemblePrompt } from "../lib/prompt";
import { makePlaceholderBlob } from "../lib/placeholder";
import {
  MakefunError,
  makeMovingVideo,
  modelById,
  shootCut,
  type ErrorKind,
} from "../lib/makefun";
import {
  emptyCut,
  pushCurrentToTakes,
  reuseTarget,
  type CutRecord,
  type ProjectRecord,
  type SaveSlot,
  type Scene,
} from "../types";
import { listEntryOf, genKey } from "./project-utils";
import type { Get, Set } from "./types";

const BATCH_CONCURRENCY = 2;
const AUTOSAVE_DEBOUNCE_MS = 1000;

export interface Engine {
  /* 상태 조회 */
  sceneOf(sceneId: string): Scene | undefined;
  hasImage(sceneId: string): boolean;
  effectivePrompt(scene: Scene): string;
  referenceBlobsOf(scene: Scene): Blob[];
  stillOnProject(pid: string | undefined): boolean;

  /* 상태 변형 */
  markDirty(keys: string[]): void;
  patchProject(fn: (p: ProjectRecord) => ProjectRecord): void;
  patchCut(sceneId: string, fn: (c: CutRecord) => CutRecord): void;
  commitImage(
    sceneId: string,
    blob: Blob,
    source: CutRecord["source"],
    sourceUrl?: string | null,
  ): void;
  /** 제작비 장부 — MakeFun 응답의 실제 coins를 프로젝트에 누적 */
  addCoins(n: number | null): void;
  /** 그 편의 장부에 크레딧을 남긴다 — 편을 옮긴 뒤 도착한 과금도 잃지 않게 */
  addCoinsTo(projectId: string, n: number | null | undefined): Promise<void>;
  setShooting(sceneId: string, on: boolean): void;

  /* 저장/적재 */
  performSave(silent: boolean): Promise<void>;
  scheduleAutosave(): void;
  loadProjectIntoMemory(rec: ProjectRecord): Promise<void>;
  autosaveBeforeLeave(): Promise<void>;

  /* 촬영 */
  shootOne(sceneId: string, signal: AbortSignal): Promise<"ok" | "aborted" | ErrorKind>;
  runBatch(sceneIds: string[]): Promise<void>;
  /** 컷씬 영상화 배치 — sourceUrl 있는 컷들을 이미지→영상 변환 (동시 2) */
  runVideoBatch(sceneIds: string[]): Promise<void>;
  registerSingleAbort(key: string, abort: AbortController): void;
  removeSingleAbort(key: string): void;
  /** 진행 중인 모든 촬영을 중단만 한다 (상태는 각 촬영의 정리 경로가 처리) */
  abortAll(): void;
  /** 프로젝트 전환 등 — 중단 + 촬영/배치 상태 초기화 */
  stopAllShooting(): void;
  /** 편을 옮기기 직전, 찍는 중이던 컷에 «지연(회수 가능)» 표시를 남긴다 */
  markInFlightDelayed(): number;
  /**
   * 컷씬 변환을 중단했지만 «시작은 접수돼» 코인이 나간 컷에 그 사실을 적는다.
   *
   * 스틸은 MakeFun 기록에서 「결과 찾아오기」로 회수할 수 있지만, 영상에는 그 기록 API가 없다 —
   * 앱이 대신 가져올 방법이 아예 없으므로, 돈이 나갔다는 사실과 «사람이 할 수 있는 길»을 적어 준다
   * (MakeFun 사이트에서 내려받아 「🎞 영상 걸기」로 걸면 다시 과금되지 않는다).
   * 예전에는 장부에만 숫자가 늘고 컷에는 아무 말이 없었다. 컷씬은 컷당 수십 코인이다.
   */
  noteVideoBillingOnAbort(sceneId: string, coins: number | null): void;
}

export function createEngine(set: Set, get: Get): Engine {
  /* 모듈 전역이던 가변 상태 — 엔진 클로저 안으로 */
  let autosaveTimer: ReturnType<typeof setTimeout> | null = null;
  /**
   * 이 창이 «알고 있는» 그 작품 기록의 시각. 저장 직전에 저장소의 것과 비교한다.
   *
   * 저장소는 브라우저 하나에 하나뿐이라 두 창이 같은 작품을 열면 나중에 저장한 창이
   * 기록 전체를 덮어쓴다 — 다른 창의 편집이 아무 말 없이 사라졌다(실측: A의 컷 수정이 증발).
   * 그래서 «내가 마지막으로 본 시각»보다 저장소가 새로우면 덮어쓰지 않고 멈춰 알린다.
   */
  let knownSavedAt = 0;
  let conflictWarned = false;
  let batchAbort: AbortController | null = null;
  const singleAborts = new Map<string, AbortController>();
  /** 이번 배치에서 «중단했지만 이미 접수돼 코인이 나간» 컷 수 — 중단 알림이 이 수를 말한다 */
  let paidOnAbort = 0;
  /** 같은 것의 컷씬(영상) 쪽 — 컷당 수십 코인이라 따로 센다 */
  let paidVideoOnAbort = 0;

  /* ---------- 상태 조회 ---------- */

  const sceneOf = (sceneId: string): Scene | undefined =>
    get().project?.story.scenes.find((sc) => sc.id === sceneId);

  const hasImage = (sceneId: string): boolean => {
    const s = get();
    const cut = s.project?.cuts[sceneId];
    return Boolean(cut?.status === "ok" && cut.imageKey && s.blobs[cut.imageKey]);
  };

  const effectivePrompt = (scene: Scene): string => {
    const p = get().project;
    if (!p) return "";
    const custom = p.cuts[scene.id]?.customPrompt?.trim();
    return custom ? custom : assemblePrompt(p.story, scene);
  };

  /** 배우 캐스팅 사진 Blob들 (scene.chars 순서) */
  const referenceBlobsOf = (scene: Scene): Blob[] => {
    const s = get();
    const p = s.project;
    if (!p) return [];
    const out: Blob[] = [];
    for (const cid of scene.chars ?? []) {
      const ch = p.story.characters.find((c) => c.id === cid);
      if (!ch?.ref) continue;
      const key = p.charAssets[ch.ref];
      const blob = key ? s.blobs[key] : undefined;
      if (blob) out.push(blob);
    }
    return out;
  };

  /** 이 컷에서 «얼굴 없이» 찍히는 배우 이름들 — ref가 없거나, 사진이 안 걸렸거나, 저장소에서 사라진 경우 */
  const missingFacesOf = (scene: Scene): string[] => {
    const s = get();
    const p = s.project;
    if (!p) return [];
    const out: string[] = [];
    for (const cid of scene.chars ?? []) {
      const ch = p.story.characters.find((c) => c.id === cid);
      if (!ch) continue; // 캐스팅에 없는 id는 조감독 리포트가 따로 말한다
      const key = ch.ref ? p.charAssets[ch.ref] : undefined;
      if (!key || !s.blobs[key]) out.push(ch.name);
    }
    return out;
  };

  /* 같은 배우 조합의 경고는 1분에 한 번만 — 배치 20컷이 스무 번 외치면 소음이다 */
  const facelessWarnedAt = new Map<string, number>();
  const warnFaceless = (sceneId: string, names: string[]) => {
    const key = names.join("|");
    const now = Date.now();
    if ((facelessWarnedAt.get(key) ?? 0) > now - 60_000) return;
    facelessWarnedAt.set(key, now);
    /* 예전에는 사진 없는 배우가 레퍼런스에서 «조용히» 빠졌다 — 감독은 결과 그림을 보고서야
       「얼굴이 전송이 안 된다」고 알았다(사용자 보고). 찍기 전에 누가 빠지는지 말한다. */
    get().toast(
      `${sceneId}: 배우 ${names.map((n) => `「${n}」`).join("·")}의 얼굴 사진이 없어 얼굴 없이 찍습니다 — 대본실 캐스팅에서 사진을 걸면 얼굴이 고정됩니다.`,
      "info",
    );
  };

  const stillOnProject = (pid: string | undefined): boolean => get().project?.id === pid;

  /* ---------- 상태 변형 ---------- */

  const markDirty = (keys: string[]) => {
    if (keys.length === 0) return;
    set((s) => ({
      dirtyAssets: Array.from(new Set([...s.dirtyAssets, ...keys])),
      unsaved: true,
    }));
  };

  const patchProject = (fn: (p: ProjectRecord) => ProjectRecord) => {
    const p = get().project;
    if (!p) return;
    set({ project: { ...fn(p), updatedAt: Date.now() }, unsaved: true });
  };

  const patchCut = (sceneId: string, fn: (c: CutRecord) => CutRecord) => {
    patchProject((p) => ({
      ...p,
      cuts: { ...p.cuts, [sceneId]: fn(p.cuts[sceneId] ?? emptyCut()) },
    }));
  };

  /** 현재 이미지를 takes로 밀고 새 이미지를 올린다. 덮어쓰기 금지.
   *  sourceUrl은 MakeFun 촬영일 때만 — 무빙 컷 변환의 원본 (약 3일 유효).
   *  새 이미지가 걸리면 이전 이미지 기준의 무빙 컷은 더 이상 맞지 않으므로 해제한다. */
  const commitImage = (
    sceneId: string,
    blob: Blob,
    source: CutRecord["source"],
    sourceUrl?: string | null,
  ) => {
    const p = get().project;
    if (!p) return;
    const key = genKey(p.id, sceneId);
    set((s) => ({ blobs: { ...s.blobs, [key]: blob } }));
    patchCut(sceneId, (c) => ({
      ...c,
      status: "ok",
      imageKey: key,
      takeKeys: pushCurrentToTakes(c),
      note: undefined,
      delayed: false,
      source,
      sourceUrl: sourceUrl ?? undefined,
      videoKey: undefined,
    }));
    markDirty([key]);
    scheduleAutosave();
  };

  const addCoins = (n: number | null) => {
    if (!n || n <= 0) return;
    patchProject((p) => ({ ...p, coinsSpent: (p.coinsSpent ?? 0) + n }));
  };

  /**
   * 크레딧을 «그 편의 장부»에 남긴다 — 편을 옮긴 뒤에 결과(실패·중단)가 도착해도 잃지 않게.
   *
   * MakeFun은 시작 순간 과금한다. 그런데 편을 옮기는 동안 도착한 오류의 coins는
   * 메모리의 project가 곧 새 편으로 교체되면서 통째로 사라졌다(24코인이 장부에서 없어졌다 — 실측).
   * 지금 열린 편이면 메모리에, 아니면 저장된 기록에 직접 더한다. 돈은 화면 밖에서도 나갔다.
   */
  const addCoinsTo = async (pid: string, n: number | null | undefined) => {
    if (!n || n <= 0) return;
    const cur = get().project;
    if (cur?.id === pid) {
      addCoins(n);
      /* 메모리에만 더하면 «편을 옮기는 중»에 그 값이 통째로 사라진다(적재가 project를 갈아끼운다).
         그래서 그 자리에서 기록에도 남긴다 — 총액을 그대로 쓰므로 자동저장과 겹쳐도 두 번 세지 않는다. */
      const now = get().project;
      if (now && now.id === pid) {
        void (async () => {
          try {
            await db.putProjectRecord(now);
            // 우리가 쓴 시각을 기준으로 올린다 — 안 그러면 다음 저장이 «다른 창»으로 오해한다
            knownSavedAt = now.updatedAt;
            db.upsertProjectListEntry(listEntryOf(now));
            set({ projectList: db.readProjectList() });
          } catch {
            /* 장부는 최선으로 */
          }
        })();
      }
      return;
    }
    try {
      const rec = await db.getProjectRecord(pid);
      if (!rec) return;
      const next = { ...rec, coinsSpent: (rec.coinsSpent ?? 0) + n };
      await db.putProjectRecord(next);
      db.upsertProjectListEntry(listEntryOf(next));
      set({ projectList: db.readProjectList() });
    } catch {
      /* 장부는 최선으로 — 실패해도 촬영을 막지 않는다 */
    }
  };

  const setShooting = (sceneId: string, on: boolean) => {
    set((s) => {
      const next = { ...s.shooting };
      if (on) next[sceneId] = true;
      else delete next[sceneId];
      return { shooting: next };
    });
  };

  /* ---------- 저장/적재 ---------- */

  const performSave = async (silent: boolean) => {
    const s = get();
    const p = s.project;
    if (!p) return;
    if (autosaveTimer) {
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
    }
    const dirty = new Map<string, Blob>();
    for (const key of s.dirtyAssets) {
      const b = s.blobs[key];
      if (b) dirty.set(key, b);
    }
    try {
      // 다른 창이 먼저 저장했는가 — 덮어쓰기 전에 기록의 시각을 본다
      const stored = await db.getProjectRecord(p.id);
      if (stored && knownSavedAt && stored.updatedAt > knownSavedAt) {
        if (!conflictWarned) {
          conflictWarned = true;
          get().toast(
            "다른 창에서 이 작품이 저장됐습니다 — 이 창의 변경을 덮어쓰지 않았어요. " +
              "「다른 이름으로 저장」으로 이 창의 것을 남기거나, 새로고침해서 최신본을 여세요.",
            "ng",
          );
        }
        set({ unsaved: true });
        return;
      }
      await db.putAssets(dirty);
      await db.putProjectRecord(p);
      knownSavedAt = p.updatedAt;
      conflictWarned = false;
      const entry = listEntryOf(p);
      db.upsertProjectListEntry(entry);
      db.setLastProjectId(p.id);
      set((cur) => {
        const remaining = cur.dirtyAssets.filter((k) => !dirty.has(k));
        return {
          dirtyAssets: remaining,
          // 저장 도중 새 편집/커밋이 끼어들었으면 unsaved를 유지한다 (beforeunload 경고 보존)
          unsaved: cur.project !== p || remaining.length > 0,
          projectList: [entry, ...cur.projectList.filter((e) => e.id !== p.id)].sort(
            (a, b) => b.updatedAt - a.updatedAt,
          ),
        };
      });
      if (get().saveFailed) set({ saveFailed: false });
      if (!silent) get().toast("오늘 촬영분을 넣어두었습니다.", "ok");
    } catch (err) {
      /* 저장소가 가득 찬 순간이 가장 위험하다: 컷을 걸 때마다 「걸었습니다 — OK」라고 말해 놓고
         (그건 «메모리에 걸렸다»는 뜻이다) 정작 저장은 안 된다. 실측(v1.2.0, 할당량 4MB)에서
         그림 마흔 장을 걸었는데 저장소에는 0장이었다. 그러니 여기서는
         ① 무엇이 잘못됐는지, ② 지금 무엇을 잃을 수 있는지, ③ 어디를 눌러 자리를 만드는지를 말한다.
         브라우저마다 오류 이름이 다르고 message가 비어 있기도 하다(빈 괄호를 찍지 않는다). */
      const name = err instanceof Error ? err.name : "";
      const msg = err instanceof Error ? err.message : String(err);
      const full = /quota|storage/i.test(`${name} ${msg}`);
      const detail = msg ? ` (${msg})` : "";
      /* 일부는 들어갔다면 그 사실을 먼저 말한다 — 「하나도 안 됐다」와 「열두 장까지는 됐다」는
         감독이 다음에 할 일이 다르다(자리를 만들고 다시 저장하면 남은 것만 채워진다). */
      const partial = err instanceof db.PartialAssetsError && err.saved > 0 ? ` 지금까지 ${err.total}장 중 ${err.saved}장은 저장했습니다.` : "";
      get().toast(
        full
          ? `저장 공간이 가득 찼습니다 — 오늘 촬영분이 아직 저장되지 않았습니다.${partial} 🧹 저장소 청소나 페이스 체크의 「옛 테이크 비우기」로 자리를 만들거나, 먼저 «내 기기로 내보내기»로 필름캔을 챙겨두세요.`
          : `저장하지 못했습니다. 브라우저 저장 공간을 확인해 주세요.${detail}`,
        "ng",
      );
      set({ saveFailed: true });
    }
  };

  const scheduleAutosave = () => {
    if (autosaveTimer) clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(() => {
      autosaveTimer = null;
      void performSave(true);
    }, AUTOSAVE_DEBOUNCE_MS);
  };

  /**
   * 지금 찍는 중이던 컷들에 «지연» 표시를 남긴다 — 다른 편으로 옮기기 «직전»에 부른다.
   *
   * MakeFun은 시작이 접수된 순간 과금한다. 편을 옮기면 촬영은 멈추지만(stopAllShooting)
   * 카메라 쪽 작업은 계속 돌아가고 결과가 서버에 남는다. 아무 표시도 없으면 감독은
   * 돌아와서 그 컷을 «대기»로 보고 다시 찍는다 — 같은 그림에 두 번 낸다.
   * 「결과 찾아오기」는 조회(GET)라 공짜이므로, 시작이 접수되지 않았더라도 손해가 없다.
   * @returns 표시를 남긴 컷 수
   */
  const markInFlightDelayed = (): number => {
    const ids = Object.keys(get().shooting);
    for (const id of ids) {
      patchCut(id, (c) => ({
        ...c,
        delayed: true,
        note: "다른 편으로 옮기며 촬영을 멈췄습니다. 시작된 촬영은 과금되고 카메라가 계속 만들 수 있어요 — 「결과 찾아오기」로 가져오세요(다시 찍으면 두 번 냅니다).",
      }));
    }
    return ids.length;
  };

  const stopAllShooting = () => {
    batchAbort?.abort();
    batchAbort = null;
    for (const a of singleAborts.values()) a.abort();
    singleAborts.clear();
    set({ batch: null, shooting: {} });
  };

  const loadProjectIntoMemory = async (rec: ProjectRecord) => {
    stopAllShooting();
    // 이 기록을 «본 시각»으로 기준을 잡는다 — 여기서부터 다른 창의 저장을 알아본다
    knownSavedAt = rec.updatedAt;
    conflictWarned = false;
    const keys: string[] = [];
    for (const key of Object.values(rec.charAssets)) keys.push(key);
    for (const cut of Object.values(rec.cuts)) {
      if (cut.imageKey) keys.push(cut.imageKey);
      if (cut.videoKey) keys.push(cut.videoKey);
      keys.push(...cut.takeKeys);
    }
    const blobs = await db.getAssets(keys);
    const slots: (SaveSlot | null)[] = [];
    for (const n of [1, 2, 3]) {
      slots.push((await db.getSaveSlot(rec.id, n)) ?? null);
    }
    const blobMap: Record<string, Blob> = {};
    for (const [k, v] of blobs) blobMap[k] = v;
    set({
      project: rec,
      blobs: blobMap,
      dirtyAssets: [],
      unsaved: false,
      saveFailed: false,
      saveSlots: slots,
      playSceneId: null,
      playHistory: [],
      choiceHistory: [],
      playBlockedAt: null,
      // 엔딩·장 끝 표시도 함께 걷는다 — 크레딧이 뜬 채로 다른 편을 열면
      // 새 편에서 「막이 내렸습니다 · OK 0컷」이 그대로 남았다(실측)
      playEnded: false,
      playChapterEnd: null,
      playStop: null,
      shooting: {},
      batch: null,
    });
    /* 지난번에 «찍는 중»이던 컷 — 창을 닫거나 새로 고쳐서 끝을 못 본 촬영이다.
       MakeFun은 시작이 접수된 순간 과금하고 그 뒤로도 계속 만든다. 표시가 없으면 감독은
       돌아와서 그 컷을 대기로 보고 다시 찍는다(같은 그림에 두 번). 조회(GET)는 공짜이므로
       접수 전에 끊겼더라도 손해가 없다 — 지연으로 바꿔 「결과 찾아오기」 문을 열어 둔다. */
    const stranded = Object.keys(rec.cuts).filter((id) => rec.cuts[id]?.inflight);
    if (stranded.length > 0) {
      for (const id of stranded) {
        patchCut(id, (c) => ({
          ...c,
          inflight: undefined,
          delayed: true,
          note:
            "지난번에 이 컷을 찍는 중에 창이 닫혔습니다. 시작된 촬영은 과금되고 카메라가 계속 만들 수 있어요 — " +
            "「결과 찾아오기」로 가져오세요(다시 찍으면 두 번 냅니다).",
        }));
      }
      get().toast(
        `지난번에 찍는 중이던 ${stranded.length}컷을 지연으로 표시했습니다 — 「결과 찾아오기」로 추가 과금 없이 가져올 수 있어요.`,
        "info",
      );
      scheduleAutosave();
    }
    /* 되돌리기 수도 이 편의 것으로 다시 센다 — 스택은 편을 가리지 않고 쌓이므로
       옮긴 직후의 「↩ 되돌리기 (2)」는 남의 걸음이다(실측 v0.97). */
    get().recountUndo();
    db.setLastProjectId(rec.id);
  };

  /** 전환/가져오기 전에 현재 작업본을 자동저장한다. */
  const autosaveBeforeLeave = async () => {
    const s = get();
    if (s.project && s.unsaved) {
      await performSave(true);
    }
  };

  /* ---------- 촬영 ---------- */

  /** 한 컷 촬영 (API). 상태 전이·NG 번역·실패 과금 기록까지 책임진다. */
  const shootOne = async (
    sceneId: string,
    signal: AbortSignal,
  ): Promise<"ok" | "aborted" | ErrorKind> => {
    const s = get();
    const p = s.project;
    const scene = sceneOf(sceneId);
    if (!p || !scene) return "unknown";
    const pid = p.id;
    const prevStatus = (p.cuts[sceneId] ?? emptyCut()).status;
    {
      const missing = missingFacesOf(scene);
      if (missing.length > 0) warnFaceless(sceneId, missing);
    }
    setShooting(sceneId, true);
    /* «접수 중»을 기록에 남긴다 — shooting은 메모리에만 있어서 창을 닫으면 사라진다.
       그러면 돌아온 감독에게 그 컷은 그냥 «대기»로 보이고, 이미 나간 코인을 회수할 문
       (「결과 찾아오기」는 NG·지연 컷에만 붙는다)이 없어 같은 그림에 두 번 낸다.
       성공·NG·중단 어느 경로든 아래 finally가 이 표시를 지운다 — 끝을 못 본 촬영만 남는다. */
    patchCut(sceneId, (c) => ({ ...c, inflight: true }));
    scheduleAutosave();
    try {
      const { blob, sourceUrl, coins } = await shootCut({
        token: s.token,
        model: modelById(p.camera.model),
        size: p.camera.size,
        sceneId,
        prompt: effectivePrompt(scene),
        referenceBlobs: referenceBlobsOf(scene),
        signal,
      });
      if (!stillOnProject(pid)) {
        // 프로젝트가 바뀌었다 — 그림은 커밋하지 않지만 «돈은 나갔다». 그 편의 장부에 남긴다.
        await addCoinsTo(pid, coins);
        return "aborted";
      }
      commitImage(sceneId, blob, "shoot", sourceUrl);
      addCoins(coins);
      return "ok";
    } catch (err) {
      // 시작이 접수됐다면 실패·중단이어도 이미 과금됐다 — 장부에 «먼저» 남긴다.
      // 편을 옮기는 중에 도착한 오류라면 그 편의 기록에 직접 더한다(안 그러면 사라진다).
      if (err instanceof MakefunError) await addCoinsTo(pid, err.coins);
      if (!stillOnProject(pid)) return "aborted";
      if (err instanceof MakefunError && err.kind === "aborted") {
        /* 중단은 status를 건드리지 않으므로 복원할 것이 없다(촬영 중 내린 감독 판정도 지킨다).
           그러나 «시작이 접수된 뒤» 중단했다면 코인은 이미 나갔고, MakeFun 쪽에서는 그림이
           계속 만들어진다 — 예전에는 그 컷에 아무 표시도 남기지 않아 「결과 찾아오기」 단추가
           뜨지 않았다(그 단추는 NG·지연 컷에만 붙는다). 장부에는 돈이 찍혔는데 회수할 문이
           없었던 셈이다. 코인이 나갔다면 지연으로 표시해 문을 열어 둔다. */
        /* 코인 액수를 «아는» 경우와 «모르는» 경우를 나눠 적는다. 시작 응답을 받기 전에 끊기면
           접수됐는지조차 알 수 없다 — 그때도 문은 열어 둔다(조회는 공짜라 헛걸음이 손해가 아니다).
           숫자를 아는 컷만 중단 알림에서 «몇 컷»으로 센다(모르는 것을 세면 거짓말이 된다). */
        const paid = (err.coins ?? 0) > 0;
        if (paid) paidOnAbort += 1;
        patchCut(sceneId, (c) => {
          if (c.status !== prevStatus) return c;
          return {
            ...c,
            delayed: true,
            note: paid
              ? `촬영을 중단했지만 이 컷은 카메라에 이미 접수돼 ${err.coins}코인이 나갔습니다 — ` +
                "NG가 아니라 만들던 중입니다. 잠시 후 「결과 찾아오기」를 누르면 추가 과금 없이 가져옵니다."
              : "촬영을 중단했습니다 — 카메라에 접수됐는지는 알 수 없습니다(응답을 받기 전에 끊었습니다). " +
                "접수됐다면 코인은 이미 나갔으니, 조회는 공짜인 「결과 찾아오기」로 한 번 확인해 보세요.",
          };
        });
        scheduleAutosave();
        return "aborted";
      }
      const kind = err instanceof MakefunError ? err.kind : "unknown";
      const msg = err instanceof Error ? err.message : "알 수 없는 문제로 이 컷은 NG가 났습니다.";
      // 지연·연결 끊김은 「거부」가 아니다 — MakeFun이 아직 만들고 있을 수 있으므로 NG로 규정하지 않는다.
      // 상태는 그대로 두고(대기면 대기, OK 재촬영이면 OK 유지) 지연 표시만 남긴다. 「결과 찾아오기」로 회수 가능.
      // 명확한 거부(저작권·검열·잘못된 요청 등)만 지금처럼 NG로 분류한다.
      const isDelay = kind === "timeout" || kind === "network";
      // network는 원인 메시지에 「NG 아님·회수 가능」 안내가 없으니 여기서 덧붙인다.
      // timeout 메시지(client.ts)에는 이미 그 안내가 들어 있어 그대로 쓴다.
      const delayNote =
        kind === "network"
          ? "카메라와 연결이 잠시 끊겼습니다. NG가 아니라 아직 만드는 중일 수 있어요 — 잠시 후 「결과 찾아오기」로 가져오거나 이 컷만 다시 찍어보세요."
          : msg;
      // 촬영 중 감독 판정으로 status가 바뀌었다면 그 판정이 우선한다.
      patchCut(sceneId, (c) => {
        if (c.status !== prevStatus) return c;
        if (isDelay) return { ...c, delayed: true, note: delayNote };
        return {
          ...c,
          status: prevStatus === "ok" && c.imageKey ? "ok" : "ng",
          delayed: false,
          note: msg,
        };
      });
      scheduleAutosave();
      return kind;
    } finally {
      // 어떤 경로로 끝났든 «접수 중» 표시는 지운다 — 끝까지 못 간 촬영만 그 표시를 남긴다
      patchCut(sceneId, (c) => (c.inflight ? { ...c, inflight: undefined } : c));
      setShooting(sceneId, false);
    }
  };

  /** 배치 실행: 동시 2. reuse/placeholder는 API를 부르지 않는다. */
  const runBatch = async (sceneIds: string[]) => {
    const abort = new AbortController();
    batchAbort = abort;
    const pid = get().project?.id;
    paidOnAbort = 0;
    set({ batch: { running: true, done: 0, total: sceneIds.length, kind: "image" } });

    const apiCuts: string[] = [];
    const placeholderCuts: string[] = [];
    const reuseCuts: string[] = [];
    for (const id of sceneIds) {
      const scene = sceneOf(id);
      if (!scene) continue;
      const cut = get().project?.cuts[id];
      if (scene.placeholder && !cut?.imageKey) placeholderCuts.push(id);
      else if (reuseTarget(scene) && !cut?.reuseBroken) reuseCuts.push(id);
      else apiCuts.push(id);
    }

    const bump = () =>
      set((cur) => (cur.batch ? { batch: { ...cur.batch, done: cur.batch.done + 1 } } : {}));

    // 플레이스홀더 먼저 (즉시, 크레딧 없음)
    for (const id of placeholderCuts) {
      if (abort.signal.aborted || !stillOnProject(pid)) break;
      try {
        const blob = await makePlaceholderBlob(id);
        if (abort.signal.aborted || !stillOnProject(pid)) break; // await 사이 전환 방지
        commitImage(id, blob, "placeholder");
      } catch {
        patchCut(id, (c) => ({ ...c, status: "ng", note: "플레이스홀더를 만들지 못했습니다." }));
      }
      bump();
    }

    // API 컷: 동시 BATCH_CONCURRENCY.
    // 같은 사유(검열·저작권)로 연속 NG면 남은 컷을 멈춰 코인 낭비를 막는다.
    let cursor = 0;
    let censoredStreak = 0;
    let autoStopped = false;
    const worker = async () => {
      while (!abort.signal.aborted) {
        const idx = cursor++;
        if (idx >= apiCuts.length) return;
        const id = apiCuts[idx];
        const cur = get();
        if (cur.project?.id !== pid) return;
        // 배치 도중 개별 촬영/업로드로 이미 OK가 됐거나 촬영 중이면 건너뛴다 (이중 크레딧 방지)
        if (cur.shooting[id] || cur.project?.cuts[id]?.status === "ok") {
          bump();
          continue;
        }
        const outcome = await shootOne(id, abort.signal);
        if (outcome === "ok") censoredStreak = 0;
        else if (outcome === "censored") {
          censoredStreak += 1;
          if (censoredStreak >= 2 && !abort.signal.aborted) {
            autoStopped = true;
            abort.abort();
            get().toast(
              "같은 사유(검열·저작권)로 연속 NG — 코인 낭비를 막기 위해 남은 컷 촬영을 멈췄습니다. " +
                "카메라를 바꾸거나 캐스팅 사진을 확인한 뒤 「NG만 다시」를 눌러주세요.",
              "ng",
            );
          }
        }
        bump();
      }
    };
    await Promise.all(Array.from({ length: BATCH_CONCURRENCY }, () => worker()));

    // reuse는 원본이 끝난 뒤에 복사 — reuse→reuse 체인도 풀릴 때까지 반복
    let pendingReuse = reuseCuts;
    while (pendingReuse.length > 0) {
      if (abort.signal.aborted || !stillOnProject(pid)) break;
      const remain: string[] = [];
      let progressed = false;
      for (const id of pendingReuse) {
        const scene = sceneOf(id);
        const target = scene ? reuseTarget(scene) : null;
        if (!scene || !target) {
          bump();
          progressed = true;
          continue;
        }
        const st = get();
        const srcCut = st.project?.cuts[target];
        const srcBlob = srcCut?.imageKey ? st.blobs[srcCut.imageKey] : undefined;
        if (!srcBlob) {
          remain.push(id);
          continue;
        }
        try {
          const copy = await cloneImageBlob(srcBlob, "image/png");
          if (abort.signal.aborted || !stillOnProject(pid)) break; // await 사이 전환 방지
          commitImage(id, copy, "reuse");
        } catch {
          patchCut(id, (c) => ({ ...c, status: "ng", note: "원본 그림을 복사하지 못했습니다." }));
        }
        bump();
        progressed = true;
      }
      // 중단/전환 중이면 남은 컷을 NG로 몰지 않고 그대로 끝낸다
      if (abort.signal.aborted || !stillOnProject(pid)) break;
      if (!progressed) {
        for (const id of remain) {
          const scene = sceneOf(id);
          const target = scene ? reuseTarget(scene) : "?";
          patchCut(id, (c) => ({
            ...c,
            status: "ng",
            note: `원본 컷(${target})이 아직 OK가 아닙니다. 원본을 먼저 찍어주세요.`,
          }));
          bump();
        }
        break;
      }
      pendingReuse = remain;
    }

    set({ batch: null });
    if (batchAbort === abort) batchAbort = null;
    if (!stillOnProject(pid)) return; // 프로젝트가 바뀌었다 — 마무리 알림 생략
    if (abort.signal.aborted) {
      if (!autoStopped) {
        get().toast(
          "촬영을 중단했습니다. 지금까지의 OK 컷은 그대로 남습니다." +
            (paidOnAbort > 0
              ? ` 다만 접수된 ${paidOnAbort}컷은 코인이 이미 나갔습니다 — 그 컷의 「결과 찾아오기」로 추가 과금 없이 가져올 수 있어요.`
              : ""),
          paidOnAbort > 0 ? "info" : undefined,
        );
      }
    } else {
      const p = get().project;
      const ok = p ? sceneIds.filter((id) => p.cuts[id]?.status === "ok").length : 0;
      get().toast(
        `촬영 종료 — OK ${ok} / ${sceneIds.length}컷`,
        ok === sceneIds.length ? "ok" : "info",
      );
    }
    scheduleAutosave();
  };

  /** 컷씬 영상화 배치 — 이미지 배치와 동일한 중단/전환 규율, 동시 2. */
  const noteVideoBillingOnAbort = (sceneId: string, coins: number | null) => {
    if (!coins || coins <= 0) return;
    paidVideoOnAbort += 1;
    patchCut(sceneId, (c) => ({
      ...c,
      note:
        `컷씬 변환을 중단했지만 이 컷은 카메라에 이미 접수돼 ${coins}코인이 나갔습니다 — ` +
        "영상은 앱이 대신 가져올 수 없습니다. MakeFun 기록에 영상이 올라오면 내려받아 「🎞 영상 걸기」로 걸어주세요(추가 과금 없음).",
    }));
    scheduleAutosave();
  };

  const runVideoBatch = async (sceneIds: string[]) => {
    const abort = new AbortController();
    batchAbort = abort;
    const pid = get().project?.id;
    paidVideoOnAbort = 0;
    set({ batch: { running: true, done: 0, total: sceneIds.length, kind: "video" } });

    const bump = () =>
      set((cur) => (cur.batch ? { batch: { ...cur.batch, done: cur.batch.done + 1 } } : {}));

    let okCount = 0;
    let cursor = 0;
    const worker = async () => {
      while (!abort.signal.aborted) {
        const idx = cursor++;
        if (idx >= sceneIds.length) return;
        const id = sceneIds[idx];
        const cur = get();
        if (cur.project?.id !== pid) return;
        const scene = sceneOf(id);
        const cut = cur.project?.cuts[id];
        // 그 사이 영상이 생겼거나 원본이 사라졌으면 건너뛴다 (이중 과금 방지)
        if (!scene || !cut?.sourceUrl || cut.videoKey || cur.shooting[id]) {
          bump();
          continue;
        }
        setShooting(id, true);
        try {
          const { blob, coins } = await makeMovingVideo({
            token: cur.token,
            sceneId: id,
            imageUrl: cut.sourceUrl,
            prompt: effectivePrompt(scene),
            signal: abort.signal,
          });
          if (!stillOnProject(pid)) return;
          const key = genKey(pid as string, `${id}:video`);
          set((s) => ({ blobs: { ...s.blobs, [key]: blob } }));
          patchCut(id, (c) => ({ ...c, videoKey: key }));
          markDirty([key]);
          addCoins(coins);
          okCount += 1;
          scheduleAutosave();
        } catch (err) {
          // 이미지 배치와 같은 규율: 과금은 «편이 바뀌었는지 보기 전에» 그 편의 장부에 남긴다.
          // 컷씬은 컷당 수십 코인이라 잃으면 더 아프다(v0.87에서 이미지 쪽을 고치며 함께 발견).
          if (err instanceof MakefunError) await addCoinsTo(pid as string, err.coins);
          if (!stillOnProject(pid)) return;
          if (err instanceof MakefunError && err.kind === "aborted") {
            noteVideoBillingOnAbort(id, err.coins);
          } else {
            const msg = err instanceof Error ? err.message : "실패";
            // 스틸의 OK/NG 판정은 건드리지 않는다 — 컷씬 변환 실패는 사유만 남긴다
            patchCut(id, (c) => ({ ...c, note: `컷씬 변환 NG — ${msg}` }));
          }
        } finally {
          setShooting(id, false);
        }
        bump();
      }
    };
    await Promise.all(Array.from({ length: BATCH_CONCURRENCY }, () => worker()));

    set({ batch: null });
    if (batchAbort === abort) batchAbort = null;
    if (!stillOnProject(pid)) return;
    if (abort.signal.aborted) {
      /* 스틸의 중단 알림과 같은 규율 — 나간 돈을 숨기지 않는다. 다만 영상은 앱이 대신
         가져올 수 없으므로(기록 API가 없다) 회수 방법 대신 «컷 메모를 보라»고 가리킨다. */
      get().toast(
        "영상화를 중단했습니다. 완성된 컷씬은 그대로 남습니다." +
          (paidVideoOnAbort > 0
            ? ` 다만 접수된 ${paidVideoOnAbort}컷은 코인이 이미 나갔습니다 — 그 컷 메모에 회수 방법을 적어 두었습니다.`
            : ""),
        paidVideoOnAbort > 0 ? "info" : undefined,
      );
    } else {
      get().toast(
        `컷씬 영상화 종료 — 완성 ${okCount} / ${sceneIds.length}컷`,
        okCount === sceneIds.length ? "ok" : "info",
      );
    }
    scheduleAutosave();
  };

  const registerSingleAbort = (key: string, abort: AbortController) => {
    singleAborts.set(key, abort);
  };

  const removeSingleAbort = (key: string) => {
    singleAborts.delete(key);
  };

  const abortAll = () => {
    batchAbort?.abort();
    for (const a of singleAborts.values()) a.abort();
    singleAborts.clear();
  };

  return {
    sceneOf,
    hasImage,
    effectivePrompt,
    referenceBlobsOf,
    stillOnProject,
    markDirty,
    patchProject,
    patchCut,
    commitImage,
    addCoins,
    addCoinsTo,
    setShooting,
    performSave,
    scheduleAutosave,
    loadProjectIntoMemory,
    autosaveBeforeLeave,
    shootOne,
    noteVideoBillingOnAbort,
    runBatch,
    runVideoBatch,
    registerSingleAbort,
    removeSingleAbort,
    abortAll,
    stopAllShooting,
    markInFlightDelayed,
  };
}
