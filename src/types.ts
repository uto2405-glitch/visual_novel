/** story.json 스키마, 프로젝트/세이브 레코드 타입, 그리고 컷 불변식 헬퍼.
 *  검증(parseStory)은 lib/parse-story.ts에 있다. */

export interface StoryCharacter {
  id: string;
  name: string;
  /** 캐스팅 사진 파일명. characters[].ref 와 업로드 파일명을 매칭한다. */
  ref?: string;
  look?: string;
  /**
   * 인쇄본 「등장인물」 장에서 사진을 정사각으로 자를 때 어디를 남길지.
   *
   * 비율로 자동 판정해봤지만(«긴 세로 사진은 얼굴이 위에 있다») 인물이 세로 가운데 있는
   * 사진에서 얼굴이 잘렸다 — 얼굴 검출 없이는 어느 쪽도 항상 옳지 않아 감독이 고른다.
   * 기본(없음)은 가로 가운데 · 세로 위쪽 35%.
   */
  castCrop?: { x?: "left" | "center" | "right"; y?: "top" | "center" | "bottom" };
}

export interface Choice {
  label: string;
  next: string;
}

/**
 * 샷 — 만화의 리듬은 시점 변화에서 나온다.
 * 실측(2026-08-31): 얼굴 레퍼런스는 구도까지 끌어당긴다. "back view"·"close-up"처럼
 * 강한 지시는 이기고, 약한 "medium"류는 ref 구도에 밀린다 → wide는 문구를 세게 쓴다.
 */
export type ShotType = "full" | "focus" | "back" | "wide" | "action" | "portrait";

export interface Scene {
  id: string;
  bg_prompt?: string;
  /** "reuse:장면ID" — API 호출 없이 원본 컷의 Blob을 복사한다. */
  bg?: string;
  shot?: ShotType;
  chars?: string[];
  pose?: string;
  emotion?: string;
  text?: string;
  /** "narration" 또는 캐릭터 id */
  speaker?: string;
  /** 장면 앰비언스: "rain" | "wind" | "night" — 시사실이 자동으로 따라간다 */
  sfx?: string;
  /** 장면별 음악 제어: true = 이 컷부터 🎵 시작, false = 정지, 생략 = 그대로 */
  bgm?: boolean;
  next?: string;
  choices?: Choice[];
  /**
   * 카메라 고정 — 직전 컷과 같은 앵글·프레이밍을 유지하고 자세만 바꾼다.
   * 연속 동작(같은 자리에서 A→B로 움직이는 컷들)을 만들 때 쓴다. 배경은 같은 bg_prompt를 반복해 적는다
   * — bg:"reuse:…"는 그림을 그대로 복사하므로 자세가 바뀌는 컷에는 쓰면 안 된다.
   */
  hold?: boolean;
  /** true면 단색 플레이스홀더. 「이 컷만 다시」로만 API 촬영 가능. */
  placeholder?: boolean;
  /** 인쇄본(웹툰) 조판 — 말풍선 자리·종류·컷 제목. 촬영에는 영향 없다. */
  webtoon?: WebtoonCut;
}

/** 말풍선 자리 — 컷의 네 귀퉁이. 인물을 가리지 않는 쪽을 감독이 고른다. */
export type BalloonPos = "tl" | "tr" | "bl" | "br";
/** 말풍선 종류 — 대사 / 생각(점꼬리) / 외침(뾰족). 내레이션은 꼬리 없는 캡션 박스. */
export type BalloonKind = "say" | "think" | "shout";
/**
 * 말풍선 꼬리가 가리킬 쪽 — 왼쪽 / 가운데(기본) / 오른쪽 / 없음.
 *
 * 그림에서 인물 위치를 자동으로 찾으려 해봤지만 야간 실사에서는 전광판·네온을 인물로 오판했다
 * (실측 오차 0.47). 그래서 4귀퉁이(pos)처럼 감독이 고른다. "none"은 화면 밖 화자·독백.
 */
export type BalloonTail = "l" | "c" | "r" | "none";

/**
 * 만화 효과선 — 정적인 사진을 «움직이게» 읽히게 만드는 장치.
 * speed(평행 속도선) = 이동 / focus(방사 집중선) = 놀람·강조 / flash(섬광) = 충격.
 * 생성 모델이 못 만드는 동세를 조판에서 만든다 — 크레딧이 들지 않고 실패하지 않는다.
 */
export type WebtoonFx = "speed" | "focus" | "flash";

/** 인쇄본(웹툰) 조판 설정 — 컷마다. 없으면 기본값으로 조판된다. */
export interface WebtoonCut {
  /** 효과선 — 액션·충격 컷에 얹는다 */
  fx?: WebtoonFx;
  /** 컷 제목 라벨 (「1. 등교하는 길」의 뒷부분). 비우면 라벨을 그리지 않는다 */
  caption?: string;
  pos?: BalloonPos;
  kind?: BalloonKind;
  /** 꼬리가 가리킬 쪽 (기본 가운데) */
  tail?: BalloonTail;
  /** 말풍선에 넣을 짧은 대사. 비우면 scene.text를 쓴다 */
  line?: string;
  /** 1:1 그리드로 자를 때 어디를 남길지 (기본 중앙) */
  crop?: "left" | "center" | "right";
  /**
   * 이 컷만 말풍선 글자 배율 (0.8 / 1 / 1.25). 긴 대사 한 컷 때문에 페이지 전체 글자를
   * 줄일 이유는 없다 — 그 컷만 작게 한다.
   */
  textScale?: number;
  /**
   * 이 컷부터 새 장 — 만화의 «장 넘김». 절정 컷을 페이지 첫 칸에 두면 넘기는 손맛이 생긴다.
   * (읽는 순서 자체는 대본의 연결을 따른다 — 조판이 순서를 바꾸면 시사와 조용히 어긋난다)
   */
  pageBreak?: boolean;
}

export interface Story {
  title: string;
  style: string;
  /**
   * 표지 부제 — 비우면 「N컷」이 들어간다.
   * 단행본 표지의 한 줄(부제·연재 회차·작가명)은 제목만큼 분위기를 정한다.
   */
  coverSubtitle?: string;
  /**
   * 표지 아래 한 줄 — 지은이·발행일 같은 판권면 문구. 비우면 아무것도 그리지 않는다.
   * 사람 이름이 들어갈 수 있으므로 앱이 자동으로 채우지 않는다(감독이 직접 적는다).
   */
  coverByline?: string;
  /** 감독 노트 — 전개 아이디어·유의사항. AI 이어쓰기 프롬프트에도 함께 전달된다. */
  note?: string;
  characters: StoryCharacter[];
  scenes: Scene[];
}

/** 컷 상태 언어: 대기 / 촬영 중 / OK / NG (완료·실패라는 말은 쓰지 않는다) */
export type CutStatus = "wait" | "ok" | "ng";

export type CutSource = "shoot" | "upload" | "url" | "reuse" | "placeholder";

export interface CutRecord {
  status: CutStatus;
  /** 현재 그림의 asset 키 */
  imageKey?: string;
  /** 이전 테이크 asset 키 (최신이 앞) — 덮어쓰기 금지, 복귀 가능 */
  takeKeys: string[];
  /** 프롬프트 수정본. 비우면 조립 프롬프트 사용 */
  customPrompt?: string;
  /** 마지막 NG 사유 (번역된 문장) */
  note?: string;
  /** 생성이 지연되거나 연결이 끊겨 결과를 아직 못 받은 상태 — NG(거부)가 아니다.
   *  MakeFun이 계속 만들고 있을 수 있으므로 「결과 찾아오기」로 회수하거나 다시 찍을 수 있다. */
  delayed?: boolean;
  /** 촬영을 시작해 «카메라에 접수된» 상태 — 저장되는 표시다(shooting은 메모리에만 있다).
   *  창을 닫거나 새로 고치면 촬영은 사라지지만 MakeFun은 계속 만들고 돈은 이미 나갔다.
   *  다음에 이 편을 열 때 이 표시가 남아 있으면 «지연»으로 바꿔 「결과 찾아오기」 문을 열어 준다.
   *  정상 종료(성공·NG·중단) 경로는 모두 이 표시를 지운다. */
  inflight?: boolean;
  /** reuse 컷을 「이 컷만 다시」로 끊었는지 */
  reuseBroken?: boolean;
  source?: CutSource;
  /** 감독이 컷씬(영상화 대상)으로 지정한 컷 — 「컷씬 영상화」 배치가 변환한다 */
  cutscene?: boolean;
  /** 무빙(영상) 버전 asset 키 — 있으면 시사실은 이미지 대신 영상을 재생한다 */
  videoKey?: string;
  /** 촬영 직후의 MakeFun 결과 URL (약 3일 유효) — 무빙 컷 변환의 원본 */
  sourceUrl?: string;
}

/** 촬영 해상도. sq(1:1)는 인쇄본 2×2 그리드용 — Seedream 계열에서 실측 지원 확인(2026-08-31). */
export type SizeKey = "1k" | "2k" | "sq";

export interface CameraConfig {
  model: string;
  size: SizeKey;
}

export interface ProjectRecord {
  id: string;
  title: string;
  story: Story;
  cuts: Record<string, CutRecord>;
  /** characters[].ref 파일명 → asset 키 */
  charAssets: Record<string, string>;
  camera: CameraConfig;
  /** 시사 커서 — 마지막으로 본 장면 */
  currentSceneId: string | null;
  /** 표지 컷 — 시사실 포스터 화면의 배경이 되는 장면 */
  posterSceneId?: string | null;
  /** 제작비 장부 — MakeFun 응답의 실제 coins 누적 */
  coinsSpent?: number;
  /** 마지막 필름캔(ZIP) 내보내기 시각 — 백업 리마인더용 */
  lastExportAt?: number;
  createdAt: number;
  updatedAt: number;
}

export interface SaveSlot {
  projectId: string;
  sceneId: string;
  choiceHistory: string[];
  timestamp: number;
}

/** localStorage에는 목록만 둔다. */
export interface ProjectListEntry {
  id: string;
  title: string;
  sceneCount: number;
  okCount: number;
  updatedAt: number;
  /**
   * 마지막 필름캔 시각 — 목록에서 «백업 기록이 없는 작품»을 알아보기 위한 사본.
   * 이 필드가 생기기 전에 저장된 목록에는 없다(그래서 «기록이 없다»고만 말하고 단정하지 않는다).
   */
  lastExportAt?: number;
  /**
   * 그 편에 들어간 크레딧 — 목록에서 연재 전체의 제작비를 더하기 위한 사본.
   * 이 필드가 생기기 전 목록에는 없다(그래서 «아직 모르는 편»은 합계에서 빼고 그 수를 밝힌다).
   */
  coinsSpent?: number;
}

/* ---------------- 컷 불변식 헬퍼 ---------------- */

export function emptyCut(): CutRecord {
  return { status: "wait", takeKeys: [] };
}

/** scene.bg 의 reuse 대상 장면 id. 없으면 null */
export function reuseTarget(scene: Scene): string | null {
  if (typeof scene.bg === "string" && scene.bg.startsWith("reuse:")) {
    const id = scene.bg.slice("reuse:".length).trim();
    return id || null;
  }
  return null;
}

/** API를 실제로 부르게 될 컷인지 (플레이스홀더·안 끊긴 reuse 제외) */
export function isApiCut(
  scene: Scene,
  cut: Pick<CutRecord, "imageKey" | "reuseBroken"> | undefined,
): boolean {
  if (scene.placeholder && !cut?.imageKey) return false;
  if (reuseTarget(scene) && !cut?.reuseBroken) return false;
  return true;
}

export interface StatusCounts {
  ok: number;
  ng: number;
  wait: number;
}

/** 장면 순서 기준의 OK/NG/대기 집계 (컷 기록이 없으면 대기) */
export function countCutStatus(p: ProjectRecord): StatusCounts {
  const counts: StatusCounts = { ok: 0, ng: 0, wait: 0 };
  for (const sc of p.story.scenes) {
    counts[p.cuts[sc.id]?.status ?? "wait"] += 1;
  }
  return counts;
}

/** OK 컷의 현재 이미지들 (sceneId → Blob). 내보내기·시사본이 공유하는 기준. */
export function collectOkImages(
  p: ProjectRecord,
  blobs: Record<string, Blob>,
): Map<string, Blob> {
  const images = new Map<string, Blob>();
  for (const scene of p.story.scenes) {
    const cut = p.cuts[scene.id];
    if (cut?.status === "ok" && cut.imageKey) {
      const b = blobs[cut.imageKey];
      if (b) images.set(scene.id, b);
    }
  }
  return images;
}

/** 캐스팅 사진이 걸린 배우들 (인쇄본 「등장인물」 장이 쓴다). 사진 없는 배우는 빠진다. */
export function collectCastPhotos(
  p: ProjectRecord,
  blobs: Record<string, Blob>,
): {
  name: string;
  look?: string;
  blob: Blob;
  cuts: number;
  crop?: StoryCharacter["castCrop"];
  charId: string;
}[] {
  const out: {
    name: string;
    look?: string;
    blob: Blob;
    cuts: number;
    crop?: StoryCharacter["castCrop"];
    charId: string;
  }[] = [];
  for (const c of p.story.characters) {
    if (!c.ref) continue;
    const key = p.charAssets[c.ref];
    const b = key ? blobs[key] : undefined;
    if (!b) continue;
    // 몇 컷에 등장하는가 — 찍힌 컷(OK)만 센다. 단행본 인물 소개의 「출연」 칸.
    let cuts = 0;
    for (const sc of p.story.scenes) {
      if (p.cuts[sc.id]?.status !== "ok") continue;
      if (sc.chars?.includes(c.id) || sc.speaker === c.id) cuts += 1;
    }
    out.push({ name: c.name, look: c.look, blob: b, cuts, crop: c.castCrop, charId: c.id });
  }
  return out;
}

/** 현재 그림을 테이크 맨 앞으로 — 덮어쓰기 금지 불변식의 이름. */
export function pushCurrentToTakes(c: CutRecord): string[] {
  return c.imageKey ? [c.imageKey, ...c.takeKeys] : c.takeKeys;
}

/**
 * 전속 배우단 — 프로젝트 밖에 사는 배우.
 *
 * 오래된 스튜디오는 전속 배우를 데리고 여러 작품을 찍는다. 이 앱의 고유 자산은
 * 「같은 얼굴」이고, 그게 작품 경계에서 끊기면 새 작품마다 캐스팅을 처음부터 다시 해야 한다.
 * 배우단은 얼굴 사진과 외모 메모를 프로젝트 밖에 보관해 다음 작품에 데려갈 수 있게 한다.
 */
export interface TroupeActor {
  id: string;
  name: string;
  /** 외모 메모(영어) — 프롬프트에 실린다 */
  look?: string;
  /** 캐스팅 사진 파일명 (프로젝트에 데려갈 때 ref로 쓴다) */
  ref: string;
  /** 얼굴 사진 — 프로젝트 자산과 독립적으로 배우단이 직접 들고 있는다 */
  photo: Blob;
  /** 출연한 작품 수 (데려갈 때마다 늘어난다) */
  appearances: number;
  createdAt: number;
  updatedAt: number;
}
