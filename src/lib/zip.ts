/**
 * 필름캔 — `.vnproj.zip` 입출력. ZIP이 곧 백업이다.
 *
 * /story.json
 * /meta.json          (title, updatedAt, currentSceneId)
 * /chars/*.jpg
 * /generated/<sceneId>.png    ← OK 컷만. 여기 있는 것만 OK로 복원된다
 * /saves/slot1.json … slot3.json
 *
 * v0.8.0 확장 (없어도 옛 필름캔은 그대로 열린다):
 * /cuts.json                  (컷별 status/note/customPrompt/reuseBroken/source/sourceUrl)
 * /ng/<sceneId>.png           (NG 판정 컷의 현재 그림 — OK로 승격되지 않는다)
 * /takes/<sceneId>/<n>.png    (이전 테이크, 0이 최신)
 * /video/<sceneId>.mp4        (v0.9.0 — 컷의 무빙(영상) 버전)
 * /screening.html             (v0.24.0 — 감상용 시사본, 선택)
 * /webtoon/page-NN.png        (v0.39.0 — 인쇄본 페이지, 선택)
 * /troupe/troupe.json         (v0.43.0 — 전속 배우단 명단)
 * /troupe/<ref>               (v0.43.0 — 배우단 얼굴 사진. 기기를 옮겨도 배우가 따라온다)
 *
 * API 토큰은 어떤 경우에도 ZIP에 넣지 않는다.
 */
import JSZip from "jszip";
import { chapterRanges } from "./chapters";
import type {
  CutSource,
  CutStatus,
  ProjectRecord,
  SaveSlot,
  Story,
  TroupeActor,
} from "../types";
import { isRecord, parseStory } from "./parse-story";
import { cloneImageBlob } from "./blob";

const IMAGE_EXT_RE = /\.(png|jpe?g|webp)$/i;

interface CutMetaEntry {
  status: CutStatus;
  note?: string;
  customPrompt?: string;
  reuseBroken?: boolean;
  source?: CutSource;
  /** 무빙 컷 변환용 원본 URL (약 3일 유효 — 만료돼도 무해) */
  sourceUrl?: string;
  /** 컷씬(영상화 대상) 지정 여부 */
  cutscene?: boolean;
}

export interface ExportBundle {
  project: ProjectRecord;
  /** sceneId → 현재 이미지 (OK 컷만) */
  images: ReadonlyMap<string, Blob>;
  /** sceneId → NG 판정 컷의 현재 이미지 */
  ngImages: ReadonlyMap<string, Blob>;
  /** sceneId → 이전 테이크들 (최신이 앞) */
  takes: ReadonlyMap<string, Blob[]>;
  /** sceneId → 무빙(영상) */
  videos: ReadonlyMap<string, Blob>;
  /** ref 파일명 → 배우 사진 */
  chars: ReadonlyMap<string, Blob>;
  /** 감상용 시사본 HTML — 선택. 토큰은 절대 담기지 않는다 */
  screeningHtml?: string;
  /** 인쇄본(웹툰) 페이지 PNG — 선택. 0번이 표지일 수 있다 */
  webtoonPages?: readonly Blob[];
  /** 인쇄본 PDF 한 파일 — 페이지를 이미 그렸으므로 덤으로 담는다(인쇄소·메일용) */
  webtoonPdf?: Blob;
  /** 인덱스 시트 — 모든 장을 한 장에 축소해 나열한 것(연재 전체의 리듬) */
  webtoonIndex?: Blob;
  /** 전속 배우단 — 선택. 기기를 옮겨도 배우가 따라오게 한다 */
  troupe?: readonly TroupeActor[];
  /** 슬롯 1..3 */
  saves: ReadonlyMap<number, SaveSlot>;
}

function extOf(blob: Blob): string {
  if (blob.type === "image/png") return "png";
  if (blob.type === "image/jpeg") return "jpg";
  if (blob.type === "image/webp") return "webp";
  return "png";
}

function videoExtOf(blob: Blob): string {
  if (blob.type === "video/webm") return "webm";
  if (blob.type === "video/quicktime") return "mov";
  return "mp4";
}

/**
 * 필름캔 안내문 — ZIP을 몇 달 뒤에 열었을 때 «이게 뭐고 어디에 뭐가 있나»를 그 안에서 알게 한다.
 * 장 목록도 함께 적는다(연재는 장으로 기억한다 — 「2장이 어디부터였지」).
 * 토큰·비밀은 절대 담지 않는다.
 */
function buildReadme(project: ProjectRecord, bundle: ExportBundle): string {
  const when = new Date(project.updatedAt || Date.now());
  const two = (n: number) => String(n).padStart(2, "0");
  const stamp = `${when.getFullYear()}-${two(when.getMonth() + 1)}-${two(when.getDate())} ${two(when.getHours())}:${two(when.getMinutes())}`;
  const ranges = chapterRanges(project.story.scenes);
  const shotOf = (ids: readonly string[]) =>
    ids.filter((id) => project.cuts[id]?.status === "ok").length;
  const lines = [
    `비주얼노벨 스튜디오 필름캔 — 「${project.title}」`,
    `내보낸 시각: ${stamp} · 컷 ${project.story.scenes.length}개 · 배우 ${project.story.characters.length}명`,
    "",
    "[이 안에 무엇이 있나]",
    "  story.json      대본(컷·배우·화풍·조판) — 이 파일이 원본입니다",
    "  cuts.json       컷마다의 판정·프롬프트·테이크 기록",
    "  generated/      OK 컷 그림 (파일명 = 컷 id)",
    "  ng/             NG 받은 그림 (지우지 않고 남겨 둡니다)",
    "  takes/<컷>/     그 컷의 이전 테이크 (0이 가장 최근)",
    "  chars/          캐스팅 사진 (얼굴을 고정하는 기준)",
    bundle.troupe && bundle.troupe.length > 0
      ? "  troupe/         전속 배우단 — 다른 작품에도 데려가는 배우와 얼굴"
      : null,
    "  video/          무빙 컷(영상)",
    bundle.webtoonPages && bundle.webtoonPages.length > 0
      ? "  webtoon/        인쇄본 — 쪽마다 PNG, 있으면 PDF·인덱스 시트도"
      : null,
    bundle.screeningHtml ? "  screening.html  시사본 — 브라우저로 그냥 열면 재생됩니다" : null,
    "  saves/          시사실 세이브 슬롯",
    "",
    "[장 목록]  기준: 컷의 「⏎ 새 장에서 시작」",
    ...(ranges.length >= 2
      ? ranges.map(
          (c, i) =>
            `  ${i + 1}장 「${c.title}」  ${c.ids[0]}~${c.ids[c.ids.length - 1]}  ${c.ids.length}컷 중 ${shotOf(c.ids)}컷 찍음`,
        )
      : [`  장을 나누지 않은 작품입니다 (컷 ${project.story.scenes.length}개)`]),
    "",
    "[다시 여는 법]",
    "  앱(VN-Studio)의 「불러오기」에 이 ZIP을 그대로 넣으세요. 같은 작품이 이미 있으면 교체할지 묻습니다.",
    "  카메라 토큰은 이 파일에 담기지 않습니다 — 새 기기에서는 설정에서 다시 넣어주세요.",
  ];
  return lines.filter((l): l is string => l !== null).join("\n") + "\n";
}

export async function buildVnprojZip(bundle: ExportBundle): Promise<Blob> {
  const zip = new JSZip();
  const { project } = bundle;
  zip.file("story.json", JSON.stringify(project.story, null, 2));
  // 안내문 — ZIP 안에서 스스로를 설명한다(장 목록 포함). 파생물이지만 몇 달 뒤의 나를 돕는다.
  zip.file("읽어보기.txt", buildReadme(project, bundle));
  // 감상용 시사본 — 있으면 필름캔 하나로 「보관 + 감상」이 다 된다 (토큰 없음)
  if (bundle.screeningHtml) zip.file("screening.html", bundle.screeningHtml);
  // 인쇄본 — webtoon/ 폴더에 페이지 순서대로. 다시 만들 수 있는 파생물이지만
  // 「ZIP 하나로 보관·감상·인쇄」가 되면 백업의 값이 커진다.
  // 전속 배우단 — 명단(JSON) + 얼굴 사진. 프로젝트 자산과 별도 폴더에 둔다.
  if (bundle.troupe?.length) {
    const roster = bundle.troupe.map((a) => ({
      id: a.id,
      name: a.name,
      look: a.look,
      ref: a.ref,
      appearances: a.appearances,
      createdAt: a.createdAt,
      updatedAt: a.updatedAt,
    }));
    zip.file("troupe/troupe.json", JSON.stringify(roster, null, 2));
    for (const a of bundle.troupe) {
      zip.file(`troupe/${a.ref}`, a.photo);
    }
  }
  if (bundle.webtoonPages?.length) {
    bundle.webtoonPages.forEach((blob, i) => {
      zip.file(`webtoon/page-${String(i).padStart(2, "0")}.png`, blob);
    });
  }
  if (bundle.webtoonPdf) {
    zip.file("webtoon/인쇄본.pdf", bundle.webtoonPdf);
  }
  if (bundle.webtoonIndex) {
    zip.file("webtoon/인덱스시트.png", bundle.webtoonIndex);
  }
  zip.file(
    "meta.json",
    JSON.stringify(
      {
        // projectId — 같은 필름캔을 다시 가져올 때 중복 프로젝트를 만들지 않기 위한 지문
        projectId: project.id,
        title: project.title,
        updatedAt: project.updatedAt,
        currentSceneId: project.currentSceneId,
        posterSceneId: project.posterSceneId,
        coinsSpent: project.coinsSpent,
        lastExportAt: project.lastExportAt,
      },
      null,
      2,
    ),
  );
  for (const [ref, blob] of bundle.chars) {
    zip.file(`chars/${ref}`, blob);
  }
  for (const [sceneId, blob] of bundle.images) {
    zip.file(`generated/${sceneId}.${extOf(blob)}`, blob);
  }
  for (const [sceneId, blob] of bundle.ngImages) {
    zip.file(`ng/${sceneId}.${extOf(blob)}`, blob);
  }
  for (const [sceneId, blobs] of bundle.takes) {
    blobs.forEach((blob, i) => {
      zip.file(`takes/${sceneId}/${i}.${extOf(blob)}`, blob);
    });
  }
  for (const [sceneId, blob] of bundle.videos) {
    zip.file(`video/${sceneId}.${videoExtOf(blob)}`, blob);
  }
  const cutsMeta: Record<string, CutMetaEntry> = {};
  for (const [sceneId, cut] of Object.entries(bundle.project.cuts)) {
    cutsMeta[sceneId] = {
      status: cut.status,
      note: cut.note,
      customPrompt: cut.customPrompt,
      reuseBroken: cut.reuseBroken,
      source: cut.source,
      sourceUrl: cut.sourceUrl,
      cutscene: cut.cutscene,
    };
  }
  zip.file("cuts.json", JSON.stringify(cutsMeta, null, 2));
  for (const [slot, save] of bundle.saves) {
    zip.file(`saves/slot${slot}.json`, JSON.stringify(save, null, 2));
  }
  return zip.generateAsync({ type: "blob", compression: "DEFLATE" });
}

/** 생성 이미지들만 담은 ZIP (촬영장 다운로드). */
export async function buildGeneratedZip(images: ReadonlyMap<string, Blob>): Promise<Blob> {
  const zip = new JSZip();
  for (const [sceneId, blob] of images) {
    zip.file(`generated/${sceneId}.${extOf(blob)}`, blob);
  }
  return zip.generateAsync({ type: "blob" });
}

export interface ImportedVnproj {
  story: Story;
  warnings: string[];
  meta: {
    projectId?: string;
    title?: string;
    updatedAt?: number;
    currentSceneId?: string | null;
    posterSceneId?: string | null;
    coinsSpent?: number;
    lastExportAt?: number;
  };
  /** 전속 배우단 — 없으면 빈 배열 (옛 필름캔은 이 폴더가 없다) */
  troupe: TroupeActor[];
  /** ref 파일명 → 배우 사진 */
  chars: Map<string, Blob>;
  /** sceneId → 생성 이미지 (OK 컷) */
  generated: Map<string, Blob>;
  /** sceneId → NG 컷의 현재 이미지 (v0.8.0 필름캔) */
  ngImages: Map<string, Blob>;
  /** sceneId → 이전 테이크들, 최신이 앞 (v0.8.0 필름캔) */
  takes: Map<string, Blob[]>;
  /** sceneId → 무빙(영상) (v0.9.0 필름캔) */
  videos: Map<string, Blob>;
  /** 컷 메타 (v0.8.0 필름캔) — 없으면 옛 포맷 */
  cutsMeta: Map<string, CutMetaEntry> | null;
  /** 슬롯 번호 → 세이브 */
  saves: Map<number, SaveSlot>;
}

/**
 * 필름캔의 지문(projectId)만 싸게 읽는다 — meta.json 한 조각.
 * 여러 개를 들여올 때 «이미 있는 것이 몇 개인가»를 먼저 알아야 한 번만 물어볼 수 있다.
 */
export async function readFilmcanProjectId(file: Blob): Promise<string | null> {
  try {
    const zip = await JSZip.loadAsync(file);
    const entry = zip.file("meta.json");
    if (!entry) return null;
    const meta: unknown = JSON.parse(await entry.async("string"));
    const id = isRecord(meta) ? meta.projectId : undefined;
    return typeof id === "string" && id ? id : null;
  } catch {
    return null; // 못 읽으면 «모른다» — 들여오기 자체는 그대로 시도한다
  }
}

export async function readVnprojZip(file: Blob): Promise<ImportedVnproj> {
  let zip: JSZip;
  try {
    zip = await JSZip.loadAsync(file);
  } catch {
    throw new Error("ZIP을 열 수 없습니다. .vnproj.zip 파일이 맞는지 확인해 주세요.");
  }
  const storyEntry = zip.file("story.json");
  if (!storyEntry) {
    throw new Error("ZIP 안에 story.json이 없습니다. 필름캔이 아닌 것 같습니다.");
  }
  let storyJson: unknown;
  try {
    storyJson = JSON.parse(await storyEntry.async("string"));
  } catch {
    throw new Error("story.json이 올바른 JSON이 아닙니다.");
  }
  const parsed = parseStory(storyJson);
  if (!parsed.story) {
    throw new Error(`story.json에 문제가 있습니다: ${parsed.errors.join(" / ")}`);
  }
  const warnings = [...parsed.warnings];

  const meta: ImportedVnproj["meta"] = {};
  const metaEntry = zip.file("meta.json");
  if (metaEntry) {
    try {
      const m = JSON.parse(await metaEntry.async("string")) as Record<string, unknown>;
      if (typeof m.title === "string") meta.title = m.title;
      if (typeof m.updatedAt === "number") meta.updatedAt = m.updatedAt;
      if (typeof m.currentSceneId === "string" || m.currentSceneId === null) {
        meta.currentSceneId = m.currentSceneId as string | null;
      }
      if (typeof m.projectId === "string" && m.projectId) meta.projectId = m.projectId;
      if (typeof m.posterSceneId === "string") meta.posterSceneId = m.posterSceneId;
      if (typeof m.coinsSpent === "number" && m.coinsSpent >= 0) meta.coinsSpent = m.coinsSpent;
      if (typeof m.lastExportAt === "number") meta.lastExportAt = m.lastExportAt;
    } catch {
      warnings.push("meta.json을 읽지 못해 건너뜁니다.");
    }
  }

  const chars = new Map<string, Blob>();
  const generated = new Map<string, Blob>();
  const ngImages = new Map<string, Blob>();
  const takesRaw = new Map<string, Map<number, Blob>>();
  const videos = new Map<string, Blob>();
  const saves = new Map<number, SaveSlot>();
  const troupe: TroupeActor[] = [];

  // 전속 배우단 — 명단과 사진을 짝지어 되살린다. 사진이 없는 항목은 조용히 건너뛴다.
  const rosterEntry = zip.file("troupe/troupe.json");
  if (rosterEntry) {
    try {
      const roster: unknown = JSON.parse(await rosterEntry.async("string"));
      if (Array.isArray(roster)) {
        for (const raw of roster) {
          if (!raw || typeof raw !== "object") continue;
          const r = raw as Record<string, unknown>;
          const id = typeof r.id === "string" ? r.id : "";
          const name = typeof r.name === "string" ? r.name : "";
          const ref = typeof r.ref === "string" ? r.ref : "";
          if (!id || !name || !ref) continue;
          const photoEntry = zip.file(`troupe/${ref}`);
          if (!photoEntry) {
            warnings.push(`배우단 「${name}」의 사진을 필름캔에서 찾지 못해 건너뜁니다.`);
            continue;
          }
          troupe.push({
            id,
            name,
            ref,
            look: typeof r.look === "string" && r.look ? r.look : undefined,
            photo: await cloneImageBlob(await photoEntry.async("blob"), "image/jpeg"),
            appearances: typeof r.appearances === "number" ? r.appearances : 1,
            createdAt: typeof r.createdAt === "number" ? r.createdAt : Date.now(),
            updatedAt: typeof r.updatedAt === "number" ? r.updatedAt : Date.now(),
          });
        }
      }
    } catch {
      warnings.push("배우단 명단을 읽지 못했습니다 — 작품은 그대로 복원됩니다.");
    }
  }

  let cutsMeta: Map<string, CutMetaEntry> | null = null;
  const cutsEntry = zip.file("cuts.json");
  if (cutsEntry) {
    try {
      const raw = JSON.parse(await cutsEntry.async("string")) as Record<string, unknown>;
      cutsMeta = new Map();
      for (const [sceneId, v] of Object.entries(raw)) {
        if (!v || typeof v !== "object") continue;
        const m = v as Record<string, unknown>;
        const status: CutStatus =
          m.status === "ok" || m.status === "ng" ? (m.status as CutStatus) : "wait";
        cutsMeta.set(sceneId, {
          status,
          note: typeof m.note === "string" ? m.note : undefined,
          customPrompt: typeof m.customPrompt === "string" ? m.customPrompt : undefined,
          reuseBroken: m.reuseBroken === true ? true : undefined,
          source:
            m.source === "shoot" ||
            m.source === "upload" ||
            m.source === "url" ||
            m.source === "reuse" ||
            m.source === "placeholder"
              ? (m.source as CutSource)
              : undefined,
          sourceUrl:
            typeof m.sourceUrl === "string" && /^https?:\/\//i.test(m.sourceUrl)
              ? m.sourceUrl
              : undefined,
          cutscene: m.cutscene === true ? true : undefined,
        });
      }
    } catch {
      warnings.push("cuts.json을 읽지 못해 컷 상태는 그림 기준으로 복원합니다.");
      cutsMeta = null;
    }
  }

  const entries = Object.values(zip.files);
  for (const entry of entries) {
    if (entry.dir) continue;
    const path = entry.name.replace(/\\/g, "/");
    if (path.startsWith("chars/")) {
      const name = path.slice("chars/".length);
      if (!name) continue;
      const raw = await entry.async("blob");
      try {
        chars.set(name, await cloneImageBlob(raw, "image/jpeg"));
      } catch {
        warnings.push(`배우 사진을 읽지 못했습니다: ${name}`);
      }
    } else if (path.startsWith("generated/")) {
      const base = path.slice("generated/".length);
      const sceneId = base.replace(IMAGE_EXT_RE, "");
      if (!sceneId) continue;
      const raw = await entry.async("blob");
      try {
        generated.set(sceneId, await cloneImageBlob(raw, "image/png"));
      } catch {
        warnings.push(`생성 이미지를 읽지 못했습니다: ${base}`);
      }
    } else if (path.startsWith("ng/")) {
      const base = path.slice("ng/".length);
      const sceneId = base.replace(IMAGE_EXT_RE, "");
      if (!sceneId) continue;
      try {
        ngImages.set(sceneId, await cloneImageBlob(await entry.async("blob"), "image/png"));
      } catch {
        warnings.push(`NG 컷 이미지를 읽지 못했습니다: ${base}`);
      }
    } else if (path.startsWith("video/")) {
      const m = /^video\/([^/]+)\.(mp4|webm|mov)$/i.exec(path);
      if (!m) continue;
      const sceneId = m[1];
      const ext = m[2].toLowerCase();
      const type = ext === "webm" ? "video/webm" : ext === "mov" ? "video/quicktime" : "video/mp4";
      try {
        const raw = await entry.async("blob");
        const buf = await raw.arrayBuffer();
        if (buf.byteLength > 0) videos.set(sceneId, new Blob([buf], { type }));
      } catch {
        warnings.push(`무빙(영상)을 읽지 못했습니다: ${path}`);
      }
    } else if (path.startsWith("takes/")) {
      const m = /^takes\/([^/]+)\/(\d+)\.(png|jpe?g|webp)$/i.exec(path);
      if (!m) continue;
      const sceneId = m[1];
      const order = Number(m[2]);
      try {
        const blob = await cloneImageBlob(await entry.async("blob"), "image/png");
        if (!takesRaw.has(sceneId)) takesRaw.set(sceneId, new Map());
        takesRaw.get(sceneId)!.set(order, blob);
      } catch {
        warnings.push(`테이크를 읽지 못했습니다: ${path}`);
      }
    } else if (/^saves\/slot[123]\.json$/.test(path)) {
      const slot = Number(path.replace(/^saves\/slot([123])\.json$/, "$1"));
      try {
        const s = JSON.parse(await entry.async("string")) as Record<string, unknown>;
        if (typeof s.sceneId === "string") {
          saves.set(slot, {
            projectId: typeof s.projectId === "string" ? s.projectId : "",
            sceneId: s.sceneId,
            choiceHistory: Array.isArray(s.choiceHistory)
              ? s.choiceHistory.filter((x): x is string => typeof x === "string")
              : [],
            timestamp: typeof s.timestamp === "number" ? s.timestamp : Date.now(),
          });
        }
      } catch {
        warnings.push(`세이브 슬롯 ${slot}을 읽지 못했습니다.`);
      }
    }
  }

  // takes/<sceneId>/<n> — n 오름차순(0이 최신)으로 정렬해 배열로
  const takes = new Map<string, Blob[]>();
  for (const [sceneId, byOrder] of takesRaw) {
    const ordered = Array.from(byOrder.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([, blob]) => blob);
    if (ordered.length > 0) takes.set(sceneId, ordered);
  }

  return {
    story: parsed.story,
    warnings,
    meta,
    troupe,
    chars,
    generated,
    ngImages,
    takes,
    videos,
    cutsMeta,
    saves,
  };
}
