/** 스토어 상태의 타입 — 슬라이스 인터페이스와 그 합집합(StudioState). */
import type { StoreApi } from "zustand";
import type {
  ProjectListEntry,
  ProjectRecord,
  SaveSlot,
  Scene,
  SizeKey,
  TroupeActor,
} from "../types";

export type Tab = "script" | "stage" | "screening";

export interface ToastItem {
  id: number;
  text: string;
  kind: "info" | "ok" | "ng";
}

export interface ConfirmRequest {
  id: number;
  title: string;
  body?: string;
  okLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  resolve: (ok: boolean) => void;
}

export interface PromptRequest {
  id: number;
  title: string;
  body?: string;
  placeholder?: string;
  initial?: string;
  okLabel?: string;
  multiline?: boolean;
  resolve: (v: string | null) => void;
}

export interface BatchState {
  running: boolean;
  done: number;
  total: number;
  /** image = 스틸 촬영 배치, video = 컷씬 영상화 배치 */
  kind: "image" | "video";
}

/* ---------------- 슬라이스 ---------------- */

export interface UiSlice {
  tab: Tab;
  toasts: ToastItem[];
  confirmReq: ConfirmRequest | null;
  promptReq: PromptRequest | null;
  settingsOpen: boolean;
  advancedOpen: boolean;
  /** 인쇄본(웹툰) 조판 창 */
  printOpen: boolean;
  /**
   * 대본실 정리대가 고른 장의 «첫 컷 id». 방을 넘나드는 안내(캐스팅의 「이 배우가 나온 장」 등)가
   * 정리대를 그 장으로 맞출 수 있어야 하므로 스토어에 둔다. ""이면 전부.
   */
  deskChapter: string;
  /** 촬영장이 고른 장의 «첫 컷 id» — 콜시트의 「이 장부터」가 여기로 데려온다. ""이면 전부 */
  stageChapter: string;
  token: string;

  setTab: (tab: Tab) => void;
  /** 정리대의 장 필터를 맞춘다 (""=전부) */
  setDeskChapter: (firstSceneId: string) => void;
  /** 촬영장의 장 필터를 맞춘다 (""=전부) */
  setStageChapter: (firstSceneId: string) => void;
  toast: (text: string, kind?: ToastItem["kind"]) => void;
  dismissToast: (id: number) => void;
  confirm: (opts: Omit<ConfirmRequest, "id" | "resolve">) => Promise<boolean>;
  promptText: (opts: Omit<PromptRequest, "id" | "resolve">) => Promise<string | null>;
  answerConfirm: (ok: boolean) => void;
  answerPrompt: (v: string | null) => void;
  setSettingsOpen: (open: boolean) => void;
  setAdvancedOpen: (open: boolean) => void;
  setPrintOpen: (open: boolean) => void;
  setToken: (token: string) => void;
}

export interface ProjectSlice {
  booted: boolean;
  project: ProjectRecord | null;
  blobs: Record<string, Blob>;
  dirtyAssets: string[];
  unsaved: boolean;
  /** 마지막 저장이 «공간이 없어» 실패했나 — 머리의 점이 이유를 말하게 한다 */
  saveFailed: boolean;
  projectList: ProjectListEntry[];

  boot: () => Promise<void>;
  newProject: () => Promise<void>;
  /** 다음 화 만들기 — 화풍·노트·배우(사진째)를 물려받은 새 작품 */
  nextEpisode: () => Promise<void>;
  /** 아직 안 찍은 장을 통째로 새 화로 옮긴다 — firstSceneId는 그 장의 첫 컷 */
  pushChapterToNextEpisode: (firstSceneId: string) => Promise<void>;
  openSample: () => Promise<void>;
  openProject: (id: string) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  saveNow: (silent?: boolean) => Promise<void>;
  saveAsNew: () => Promise<void>;
  scheduleAutosave: () => void;
  exportProject: () => Promise<void>;
  /** 이 브라우저의 모든 작품을 각자의 필름캔 ZIP으로 (기기 이사용) */
  exportAllProjects: () => Promise<void>;
  /** 이 연재의 여러 화를 «한 권»으로 조판해 PDF 한 파일로 내보낸다 (크레딧 0) */
  exportOmnibus: () => Promise<void>;
  /** 저장된 작품 전체에서 대사·컷 제목·말풍선을 찾는다 — 20편에서 «그 대사가 몇 화였지» */
  searchAllProjects: (query: string) => Promise<SearchHit[]>;
  exportGeneratedImages: () => Promise<void>;
  /** 시사본 HTML — 장의 첫 컷 id를 주면 그 장만 담는다 */
  exportScreeningHtml: (onlyChapter?: string) => Promise<void>;
  /** 인쇄본(웹툰) 조판 — OK 컷을 만화 페이지 PNG로. 이미지 생성 없음(무과금) */
  exportWebtoon: (options?: {
    layout?: "strip" | "grid";
    perPage?: number;
    cover?: boolean;
    gutter?: number;
    textScale?: number;
    castPage?: boolean;
    paper?: "white" | "black";
    /** 여러 장을 세로로 이어 한 장으로 (웹툰 플랫폼 업로드용) */
    strip?: boolean;
    /** 한 파일 PDF로 (인쇄·문서 첨부용) */
    pdf?: boolean;
    /** 컷 제목 앞의 번호 */
    captionNumbers?: boolean;
    /** 장이 시작되는 페이지의 장 제목 띠 */
    chapterBand?: boolean;
    /** 장이 다섯을 넘으면 표지 다음에 목차 한 장 */
    contents?: boolean;
    /** 모든 장을 한 장에 축소해 나열한 인덱스 시트로 (연재 전체의 리듬 보기) */
    indexSheet?: boolean;
    /** 이 장(챕터)의 컷만 담는다 — 값은 그 장 첫 컷의 id. 표지·목차·등장인물 장은 빠진다 */
    onlyChapter?: string;
  }) => Promise<void>;
  /** quiet=true면 편마다 토스트를 띄우지 않는다(여럿 들여올 때) */
  importFromFile: (
    file: File,
    quiet?: boolean,
    /** 여러 개를 들여올 때 이미 물어본 결정 — 편마다 다시 묻지 않는다 */
    dupPolicy?: "replace" | "copy",
  ) => Promise<void>;
  /** 필름캔 여럿을 한 번에 — 「🎞 모두 내보내기」의 반대편 */
  importManyFromFiles: (files: readonly File[]) => Promise<void>;
  /** 저장소 청소 — 어떤 컷·테이크·캐스팅도 참조하지 않는 고아 그림을 지운다 */
  cleanStorage: () => Promise<void>;
}

/** 배우가 나온 작품 한 편 — 배우단 선반의 「어디에 나왔나」 */
/** 연재 검색의 결과 한 줄 */
export interface SearchHit {
  projectId: string;
  projectTitle: string;
  sceneId: string;
  /** 그 컷이 속한 장 이름 — 장이 하나뿐이면 빈 문자열 */
  chapter: string;
  /** 어디서 걸렸나 — 대사/컷 제목/말풍선 */
  where: "대사" | "컷 제목" | "말풍선";
  /**
   * 그 컷을 찍었나 — 찾은 다음의 손짓은 «고치기»거나 «찍기»다.
   * 20편 240컷에서 찾아 놓고 그 편을 열어 상태를 확인하는 걸음을 없앤다.
   */
  status: "ok" | "ng" | "wait";
  /** 앞뒤를 조금 붙인 발췌 */
  excerpt: string;
}

export interface ActorWork {
  /** 그 작품의 id — 선반에서 바로 열기 위해(제목만으로는 열 수 없다) */
  id: string;
  title: string;
  /** 그 작품에서 나온 장 이름들 (장이 하나면 비어 있다) */
  chapters: string[];
  cuts: number;
}

export interface ScriptSlice {
  /** 되돌리기 가능한 대본 변경 수 — «지금 열린 편»의 것만 센다(스택은 편을 가리지 않고 쌓인다) */
  undoDepth: number;
  /** 편이 바뀐 뒤 되돌리기 수를 다시 센다 — 엔진이 작품을 메모리에 올릴 때 부른다 */
  recountUndo: () => void;
  /**
   * 배우 이름 → 나온 작품들. 배우단 선반을 열 때 저장된 작품을 훑어 만든다
   * (「N편 출연」 숫자만으로는 «어느 작품 몇 장»을 알 수 없다).
   */
  troupeWorks: Record<string, ActorWork[]>;
  /** 저장소의 모든 작품을 훑어 배우별 출연 작품·장을 모은다 */
  loadTroupeWorks: () => Promise<void>;
  /** 마지막 대본 변경을 되돌린다 — 그림·테이크 저장소는 건드리지 않는다 */
  undoScript: () => void;
  updateScene: (sceneId: string, patch: Partial<Scene>) => void;
  addSceneAfter: (sceneId: string) => void;
  /** 표시 순서만 위/아래로 — 연결(next)은 건드리지 않는다 */
  moveScene: (sceneId: string, dir: -1 | 1) => void;
  /** 장을 통째로 앞/뒤 장과 맞바꾼다 — firstSceneId는 그 장의 첫 컷 */
  moveChapter: (firstSceneId: string, dir: -1 | 1) => void;
  /** 연속 동작 — 이 컷을 A로 두고 카메라 고정·배경 재사용된 B·C를 뒤에 만들어 잇는다 */
  expandSequence: (sceneId: string) => void;
  /** 빈 컷을 이 컷 뒤에 만들고 id를 돌려준다 — 연결은 호출자가 정한다 (「+ 새 컷 만들기」) */
  spawnSceneAfter: (sceneId: string) => string | null;
  /** 컷을 대본에서 뺀다 (확인창) — 그림·테이크는 저장소에 남는다 */
  deleteScene: (sceneId: string) => Promise<void>;
  setStyle: (style: string) => void;
  setNote: (note: string) => void;
  /** 인쇄본 표지의 부제 — 비우면 「N컷」 */
  setCoverSubtitle: (text: string) => void;
  /** 표지 아래 한 줄 — 지은이·발행일 (비우면 그리지 않는다) */
  setCoverByline: (text: string) => void;
  setTitle: (title: string) => void;
  appendStoryJson: () => Promise<void>;
  /** 같은 id의 컷을 다시 쓴 대본으로 덮어쓴다 — 그림·판정은 그대로 */
  rewriteScenesJson: () => Promise<void>;
  replaceStoryJson: (text: string) => boolean;
  /** 배우 이름·외모 메모 수정 (되돌리기 지원) */
  updateCharacter: (
    charId: string,
    patch: {
      name?: string;
      look?: string;
      /** 인쇄본 등장인물 장에서 사진을 자를 위치 (null = 기본으로 되돌리기) */
      castCrop?: { x?: "left" | "center" | "right"; y?: "top" | "center" | "bottom" } | null;
    },
  ) => void;
  /** 배우 하차 — 명단·등장 표시·화자에서 뺀다. 사진 자산은 저장소 청소 전까지 남는다 */
  removeCharacter: (charId: string) => Promise<void>;
  /** 전속 배우단 목록 (프로젝트 밖) */
  troupe: TroupeActor[];
  loadTroupe: () => Promise<void>;
  /** 이 배우를 배우단에 등록/갱신 — 다음 작품에 데려갈 수 있게 된다 */
  saveToTroupe: (charId: string) => Promise<void>;
  /** 배우단에서 이 작품으로 데려온다 (사진까지 함께) */
  castFromTroupe: (actorId: string) => Promise<void>;
  /** 배우단에서 완전히 지운다 (작품 안 배우는 그대로) */
  removeFromTroupe: (actorId: string) => Promise<void>;
  /** 배우단 배우의 얼굴 사진만 더 좋은 것으로 갈아끼운다 (작품을 열지 않아도 된다) */
  replaceTroupePhoto: (actorId: string, file: File) => Promise<void>;
  /** 배우단 배우의 이름·외모 메모 수정 */
  editTroupeProfile: (actorId: string) => Promise<void>;
  uploadCharFiles: (files: File[]) => Promise<void>;
  /** 파일명과 무관하게 특정 배우에게 사진을 건다 (배우 카드의 「사진 올리기」) */
  uploadCharPhotoFor: (charId: string, file: File) => Promise<void>;
  removeCharImage: (ref: string) => void;
}

export interface StageSlice {
  shooting: Record<string, boolean>;
  batch: BatchState | null;

  setCamera: (model: string, size: SizeKey) => void;
  setCustomPrompt: (sceneId: string, text: string) => void;
  resetPrompt: (sceneId: string) => Promise<void>;
  /** 직접 쓴 프롬프트를 «전부» 조립본으로 되돌린다 — 화풍·배우·장소 변경이 다시 흐르게 하는 문 */
  resetPromptsAll: () => Promise<void>;
  markNg: (sceneId: string) => void;
  markOk: (sceneId: string) => void;
  uploadSceneImage: (sceneId: string, file: File) => Promise<void>;
  registerUrlImage: (sceneId: string) => Promise<void>;
  removeImage: (sceneId: string) => void;
  revertTake: (sceneId: string, takeIndex: number) => void;
  /** 이 컷의 이전 테이크를 저장소에서 비운다 (지금 그림은 그대로) */
  clearTakes: (sceneId: string) => Promise<void>;
  /** 여러 컷의 옛 테이크를 한 번에 비운다 — 「이 장」을 다 다시 찍은 뒤 */
  clearTakesMany: (sceneIds: string[]) => Promise<void>;
  /** MakeFun 기록에서 이 컷의 완성본을 찾아온다 — 추가 과금 없음 (놓친 결과 회수) */
  pullResultFor: (sceneId: string) => Promise<void>;
  /** 이 컷을 표지로 지정/해제 — 시사실 포스터 배경이 된다 */
  setPoster: (sceneId: string) => void;
  /** 내 영상 파일(mp4/webm)을 컷에 건다 — 시사실은 이미지 대신 이 영상을 재생 */
  attachVideo: (sceneId: string, file: File) => Promise<void>;
  removeVideo: (sceneId: string) => void;
  /** 무빙 컷 (실험): OK 컷의 원본 URL(3일 유효)로 MakeFun 이미지→영상 변환 (~30코인) */
  makeMovingCut: (sceneId: string) => Promise<void>;
  /** 이 컷을 컷씬(영상화 대상)으로 지정/해제 */
  toggleCutscene: (sceneId: string) => void;
  /** 지정된 컷씬들을 한 번에 영상화 — 원본 URL 있는 컷만, 확인창 후 */
  startVideoBatch: () => Promise<void>;
  /**
   * 배치 촬영. onlyIds를 주면 그 컷들 안에서만 고른다 —
   * 연재에서 «3장만 골라 찍기»가 실제 흐름이라 촬영장의 장별 필터와 짝을 이룬다.
   */
  startBatch: (scope: "pending" | "ng", onlyIds?: readonly string[]) => Promise<void>;
  shootSingle: (sceneId: string) => Promise<void>;
  stopBatch: () => void;
}

export interface PlaySlice {
  playSceneId: string | null;
  playHistory: string[];
  choiceHistory: string[];
  /** 이미지 없는 컷에 닿았을 때의 안내 대상 장면 */
  playBlockedAt: string | null;
  playEnded: boolean;
  /** 「이 장까지만」 상영 중이면 그 장의 마지막 컷과 이름 */
  playStop: { id: string; title: string } | null;
  /** 장 끝에 닿아 멈춘 상태 — 값은 그 장 이름 (엔딩 크레딧과는 다르다) */
  playChapterEnd: string | null;
  autoPlay: boolean;
  /** showScene마다 증가 — 같은 컷을 다시 보여줄 때도 타자기/페이드가 재시작되게 */
  playEpoch: number;
  /** 앰비언스 마스터 — 켜면 장면의 sfx(비/바람/밤)와 타자기 틱이 소리를 낸다 */
  ambienceOn: boolean;
  /** 🎵 음악 — 수동 토글 + 장면의 bgm(true/false)이 자동으로 켜고 끈다 */
  musicOn: boolean;
  saveSlots: (SaveSlot | null)[];
  /** 타자기 간격 ms — 취향 설정, localStorage 기억 */
  typeMs: number;
  /** 대사 글자 배율 — 1 | 1.25, localStorage 기억 */
  fontScale: number;

  enterScreening: () => void;
  setTypeMs: (ms: number) => void;
  setFontScale: (f: number) => void;
  showScene: (sceneId: string) => void;
  advancePlay: () => void;
  /** 한 장만 상영 — 첫 컷부터 시작해 마지막 컷에서 멈춘다 */
  playChapter: (firstId: string, lastId: string, title: string) => void;
  /** 장 단위 멈춤을 푼다 (다른 컷으로 건너뛸 때) */
  clearChapterStop: () => void;
  /** 장 끝에서 «이어서 보기» */
  resumePastChapter: () => void;
  backPlay: () => void;
  restartPlay: () => void;
  continuePlay: () => void;
  clearBlocked: () => void;
  dismissEnd: () => void;
  setAutoPlay: (on: boolean) => void;
  setAmbienceOn: (on: boolean) => void;
  setMusicOn: (on: boolean) => void;
  saveToSlot: (slot: number) => Promise<void>;
  loadFromSlot: (slot: number) => Promise<void>;
  deleteSlot: (slot: number) => Promise<void>;
}

export type StudioState = UiSlice & ProjectSlice & ScriptSlice & StageSlice & PlaySlice;

export type Set = StoreApi<StudioState>["setState"];
export type Get = StoreApi<StudioState>["getState"];
