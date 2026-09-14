/** 프로젝트 수명 슬라이스 — 부팅, 생성/전환/삭제, 저장, 필름캔 입출력. */
import * as db from "../../lib/db";
import { downloadBlob, safeFileName, blobToDataUrl } from "../../lib/blob";
import { chapterRanges } from "../../lib/chapters";
import { parseStory } from "../../lib/parse-story";
import { nextPaint } from "../../lib/hooks";
import { nextEpisodeTitle, parseEpisode } from "../../lib/episodes";
import {
  buildGeneratedZip,
  buildVnprojZip,
  readFilmcanProjectId,
  readVnprojZip,
} from "../../lib/zip";
import { buildScreeningHtml } from "../../lib/exportHtml";
import {
  buildIndexSheet,
  buildOmnibus,
  buildWebtoon,
  stitchPages,
  thumbDataUrl,
  type CastCard,
  type OmnibusVolume,
  type WebtoonPanel,
} from "../../lib/webtoon";
import { buildPdf } from "../../lib/pdf";
import { speakerName } from "../../lib/story";
import { SAMPLE_STORY } from "../../lib/sample";
import {
  collectCastPhotos,
  collectOkImages,
  type CutRecord,
  type ProjectRecord,
  type SaveSlot,
  type Story,
} from "../../types";
import { genKey, listEntryOf, makeProject, newProjectId } from "../project-utils";
import type { Get, ProjectSlice, SearchHit, Set } from "../types";
import type { Engine } from "../engine";

/**
 * 인쇄본용 컷 순서와 패널 — 읽는 순서(next, 갈림길은 첫 갈래)로 선형화한다.
 * 경로에서 빠진 OK 컷은 뒤에 순서대로 붙인다(버리지 않는다).
 */
async function collectWebtoonPanels(
  p: ProjectRecord,
  blobs: Record<string, Blob>,
): Promise<WebtoonPanel[]> {
  const ok = collectOkImages(p, blobs);
  if (ok.size === 0) return [];
  const byId = new Map(p.story.scenes.map((sc) => [sc.id, sc] as const));
  const order: string[] = [];
  const seen = new Set<string>();
  let cur = p.story.scenes[0];
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    if (ok.has(cur.id)) order.push(cur.id);
    const nextId = cur.choices?.length ? cur.choices[0].next : cur.next;
    const nxt = nextId ? byId.get(nextId) : undefined;
    if (!nxt) break;
    cur = nxt;
  }
  for (const sc of p.story.scenes) {
    if (ok.has(sc.id) && !order.includes(sc.id)) order.push(sc.id);
  }
  const panels: WebtoonPanel[] = [];
  for (let i = 0; i < order.length; i++) {
    const scene = byId.get(order[i]);
    const blob = ok.get(order[i]);
    if (!scene || !blob) continue;
    panels.push({
      scene,
      bitmap: await createImageBitmap(blob),
      index: i + 1,
      speaker: speakerName(p.story, scene),
      isNarration: !scene.speaker || scene.speaker === "narration",
    });
  }
  return panels;
}

/**
 * 감독 노트에 자동으로 붙은 «앞 화 요약» 블록을 걷어낸다 — 가장 최근 것만 남기려고.
 *
 * 예전에는 화를 물려줄 때마다 요약을 덧붙여 6화 노트에 블록이 다섯 개(328자·22줄) 쌓였다(실측).
 * 20화면 열아홉 개다 — 노트 칸도 AI 이어쓰기 프롬프트도 지난 화의 대사로 채워진다.
 * 감독이 손으로 쓴 부분은 그대로 두고, 자동 블록만 지운다.
 */
function stripRecaps(text: string): string {
  return text.replace(/\n*\[앞 화 「[^」]*」의 끝\]\n(?:· [^\n]*\n?)*/g, "").trim();
}

/** 감독이 인쇄본을 손댄 적이 있는지 — 그럴 때만 필름캔에 함께 담을지 묻는다. */
function hasWebtoonSetup(p: ProjectRecord): boolean {
  return p.story.scenes.some((sc) => {
    const w = sc.webtoon;
    return Boolean(
      w && (w.caption || w.line || w.fx || w.pos || w.kind || w.crop || w.tail || w.pageBreak),
    );
  });
}

/**
 * 인쇄본 등장인물 장의 「출연」 칸에 적을 «다른 작품 이름»을 배우 이름으로 찾아 주는 함수를 만든다.
 *
 * 근거는 배우단 선반과 같다(저장된 작품 전체를 훑은 troupeWorks) — 두 곳이 각자 세면 언젠가 어긋난다.
 * 선반을 한 번도 열지 않았으면 비어 있으므로 여기서 한 번 훑는다(내보내기 한 번에 한 번).
 */
async function otherFilmTitles(get: Get, ...mine: string[]): Promise<(name: string) => string[]> {
  if (Object.keys(get().troupeWorks).length === 0) await get().loadTroupeWorks();
  const works = get().troupeWorks;
  const skip = new Set(mine);
  return (name: string) => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const w of works[name] ?? []) {
      if (skip.has(w.title) || seen.has(w.title)) continue;
      seen.add(w.title);
      out.push(w.title);
    }
    return out;
  };
}

export function createProjectSlice(set: Set, get: Get, engine: Engine): ProjectSlice {
  return {
    booted: false,
    project: null,
    blobs: {},
    dirtyAssets: [],
    unsaved: false,
    saveFailed: false,
    projectList: [],

    boot: async () => {
      if (get().booted) return;
      set({ booted: true, projectList: db.readProjectList() });
      // .env.local의 토큰을 최초 1회 기본값으로 심는다 (소스 하드코딩 금지 원칙 유지).
      // 어떤 await보다 먼저, 동기적으로 — localStorage에 이미 토큰이 있으면 절대 덮어쓰지 않는다.
      const envToken = String(import.meta.env.VITE_MAKEFUN_TOKEN ?? "").trim();
      if (envToken && !db.getToken()) {
        db.setToken(envToken);
        set({ token: envToken });
        get().toast("기본 카메라 토큰을 넣어두었습니다. 설정에서 바꿀 수 있어요.");
      }
      // localStorage 목록이 지워져도 IndexedDB의 소설이 고아가 되지 않게 대조 복원
      try {
        const recs = await db.listProjectRecords();
        const known = new Set(db.readProjectList().map((e) => e.id));
        let restored = 0;
        for (const rec of recs) {
          if (!known.has(rec.id)) {
            db.upsertProjectListEntry(listEntryOf(rec));
            restored += 1;
          }
        }
        if (restored > 0) {
          set({ projectList: db.readProjectList() });
          get().toast(`목록에서 빠져 있던 프로젝트 ${restored}개를 되찾았습니다.`);
        }
      } catch {
        /* 목록 복원에 실패해도 부팅은 계속 */
      }
      const last = db.getLastProjectId();
      if (last) {
        const rec = await db.getProjectRecord(last);
        if (rec) {
          await engine.loadProjectIntoMemory(rec);
          return;
        }
      }
    },

    newProject: async () => {
      const title = await get().promptText({
        title: "새 프로젝트",
        body: "작품 제목을 정해주세요. 나중에 바꿀 수 있습니다.",
        placeholder: "무제",
        okLabel: "만들기",
      });
      if (title === null) return;
      await engine.autosaveBeforeLeave();
      const story: Story = {
        title: title.trim() || "무제",
        style:
          "cinematic realistic photo, soft lighting, visual novel still, consistent face matching reference, 16:9",
        characters: [],
        scenes: [{ id: "s01", shot: "full", text: "", speaker: "narration" }],
      };
      const rec = makeProject(story, story.title);
      await engine.loadProjectIntoMemory(rec);
      set({ unsaved: true });
      await engine.performSave(true);
      get().toast(`「${rec.title}」 대본실을 열었습니다.`);
    },

    /**
     * 이 장을 다음 화로 — 연재에서 「이 장은 이번 화에 안 들어가겠다」는 흔한 판단이다.
     * 지금까지는 컷을 하나하나 새 화에 옮겨 적어야 했다.
     *
     * 아직 «찍지 않은» 장만 보낸다. 찍은 필름이 화를 넘어가면 그림·테이크·판정이
     * 어느 작품에 있는지 헷갈리고, 되돌릴 방법이 마땅치 않다 — 그건 순서 옮기기(▲▼)의 일이다.
     */
    pushChapterToNextEpisode: async (firstSceneId) => {
      const cur = get().project;
      if (!cur) return;
      const ranges = chapterRanges(cur.story.scenes);
      const at = ranges.findIndex((c) => c.firstId === firstSceneId);
      if (at < 0) return;
      if (ranges.length < 2) {
        get().toast("장이 하나뿐입니다 — 보낼 장을 먼저 나눠주세요(컷의 ⏎ 새 장에서 시작).");
        return;
      }
      const block = ranges[at];
      const movedIds = new Set(block.ids);
      const shot = block.ids.filter((id) => {
        const c = cur.cuts[id];
        return Boolean(
          c && (c.imageKey || c.videoKey || (c.takeKeys?.length ?? 0) > 0 || c.status !== "wait"),
        );
      });
      if (shot.length > 0) {
        get().toast(
          `「${block.title}」에는 이미 찍은 컷이 ${shot.length}개 있습니다 — 찍은 필름이 화를 넘어가면 어디 있는지 헷갈려서 보내지 않습니다. 순서만 바꾸려면 ▲▼ 장 옮기기를 쓰세요.`,
          "ng",
        );
        return;
      }
      const ok = await get().confirm({
        title: `「${block.title}」을 다음 화로`,
        body:
          `아직 찍지 않은 ${block.ids.length}컷을 이 작품에서 빼서 새 화의 첫 장으로 옮깁니다.\n` +
          "화풍·감독 노트·배우(캐스팅 사진째)는 함께 갑니다. 이 작품은 그대로 남고, 찍어둔 컷은 건드리지 않습니다.",
        okLabel: "보내기",
      });
      if (!ok) return;
      /* 이름 규칙은 「다음 화 만들기」와 같은 한 곳(lib/episodes)을 쓴다 — 여기에 정규식을 한 벌
         더 두었더니 「1편」·「01화」를 넓혀 읽게 된 v0.97에서 곧바로 어긋났다(「… 1편 2화」). */
      const guess = nextEpisodeTitle(cur.title);
      const title = await get().promptText({
        title: "다음 화 제목",
        body: `「${block.title}」이 이 새 화의 첫 장이 됩니다.`,
        initial: guess,
        okLabel: "만들기",
      });
      if (title === null) return;

      const moved = cur.story.scenes.filter((sc) => movedIds.has(sc.id));
      const stay = cur.story.scenes.filter((sc) => !movedIds.has(sc.id));
      // 빠진 장을 가리키던 연결은 «그 장 다음»으로 넘긴다 — 끊어진 채 두면 이야기가 멈춘다
      const afterId = cur.story.scenes[block.end]?.id;
      let relinked = 0;
      const stayFixed = stay.map((sc, i) => {
        let next = sc.next;
        if (next && movedIds.has(next)) {
          next = afterId && !movedIds.has(afterId) ? afterId : undefined;
          relinked += 1;
        }
        const choices = sc.choices?.map((c) => {
          if (c.next && movedIds.has(c.next) && afterId && !movedIds.has(afterId)) {
            relinked += 1;
            return { ...c, next: afterId };
          }
          return c;
        });
        // 남은 대본의 첫 컷에는 장 나누기 표시가 남지 않아야 한다(첫 장은 표시 없이도 장이다)
        const w = i === 0 && sc.webtoon?.pageBreak ? { ...sc.webtoon } : null;
        if (w) delete w.pageBreak;
        return {
          ...sc,
          ...(next === sc.next ? {} : { next }),
          ...(choices ? { choices } : {}),
          ...(w ? { webtoon: Object.keys(w).length ? w : undefined } : {}),
        };
      });
      const tailLines = stayFixed
        .slice(0, block.start)
        .slice(-3)
        .map((sc) => (sc.text ?? "").trim())
        .filter(Boolean);

      engine.patchProject((p) => {
        const cuts = { ...p.cuts };
        for (const id of movedIds) delete cuts[id];
        return {
          ...p,
          story: { ...p.story, scenes: stayFixed },
          cuts,
          posterSceneId: p.posterSceneId && movedIds.has(p.posterSceneId) ? null : p.posterSceneId,
          currentSceneId:
            p.currentSceneId && movedIds.has(p.currentSceneId) ? null : p.currentSceneId,
        };
      });
      set({ unsaved: true });
      await engine.performSave(true);
      await engine.autosaveBeforeLeave();

      const source = cur;
      const recap = tailLines.length
        ? `[앞 화 「${source.title}」의 끝]\n${tailLines.map((t) => `· ${t}`).join("\n")}`
        : "";
      // 요약 블록은 «가장 최근 것 하나»만 — 쌓이면 프롬프트가 지난 화 대사로 찬다(실측)
      const note = [stripRecaps(source.story.note ?? ""), recap].filter(Boolean).join("\n\n");
      // 새 화 안에서 밖을 가리키는 연결은 끊어 둔다 — 옮겨간 대본에는 그 컷이 없다.
      // (마지막 컷만이 아니다. 갈림길이 뒤 장을 가리키는 일도 있다)
      let cutLinks = 0;
      const story: Story = {
        title: title.trim() || guess,
        style: source.story.style,
        ...(note ? { note } : {}),
        ...(source.story.coverByline ? { coverByline: source.story.coverByline } : {}),
        characters: source.story.characters.map((c) => ({ ...c })),
        scenes: moved.map((sc) => {
          const first = sc.id === block.firstId;
          const w = first && sc.webtoon?.pageBreak ? { ...sc.webtoon } : null;
          if (w) delete w.pageBreak;
          const outside = Boolean(sc.next && !movedIds.has(sc.next));
          if (outside) cutLinks += 1;
          const choices = sc.choices?.filter((c) => {
            const keep = movedIds.has(c.next);
            if (!keep) cutLinks += 1;
            return keep;
          });
          return {
            ...sc,
            ...(outside ? { next: undefined } : {}),
            ...(sc.choices ? { choices: choices?.length ? choices : undefined } : {}),
            ...(w ? { webtoon: Object.keys(w).length ? w : undefined } : {}),
          };
        }),
      };
      const rec = makeProject(story, story.title);
      const carried = new Map<string, Blob>();
      const charAssets: Record<string, string> = {};
      for (const [ref, key] of Object.entries(source.charAssets)) {
        const blob = get().blobs[key];
        if (!blob) continue;
        const nk = db.assetKey(rec.id, "char", ref);
        carried.set(nk, blob);
        charAssets[ref] = nk;
      }
      rec.charAssets = charAssets;
      await engine.loadProjectIntoMemory(rec);
      if (carried.size > 0) {
        set((st) => ({
          blobs: { ...st.blobs, ...Object.fromEntries(carried) },
        }));
        engine.markDirty([...carried.keys()]);
      }
      set({ unsaved: true });
      await engine.performSave(true);
      get().toast(
        `「${block.title}」의 ${moved.length}컷을 「${rec.title}」으로 옮겼습니다` +
          (relinked > 0 ? ` — 앞 작품의 연결 ${relinked}곳은 그 다음 컷으로 이어 뒀고` : " —") +
          (cutLinks > 0
            ? ` 새 화에서 앞 작품을 가리키던 연결 ${cutLinks}곳은 끊어 뒀어요(그 컷이 여기엔 없으니까요).`
            : " 연결은 그대로입니다."),
        "ok",
      );
    },

    /**
     * 다음 화 만들기 — 연재의 «이어서 쓰기»를 한 번에.
     *
     * 지금까지는 새 프로젝트 → 제목 입력 → 배우단 열기 → 데려오기(네 걸음)였다.
     * 연재는 그 걸음을 매 화 반복하므로, 제목을 이어 붙이고(「…2화」) 화풍·감독 노트를
     * 물려주고 지금 작품의 배우를 그대로 데려온다. 컷은 빈 한 컷만 — 이야기는 감독이 쓴다.
     */
    nextEpisode: async () => {
      const cur = get().project;
      if (!cur) {
        get().toast("먼저 작품을 열어주세요 — 그 작품의 다음 화를 만듭니다.");
        return;
      }
      // 「역의 우산 3화」 → 「역의 우산 4화」 / 화 표기가 없으면 「… 2화」 (규칙은 lib/episodes 한 곳)
      const guess = nextEpisodeTitle(cur.title);
      const title = await get().promptText({
        title: "다음 화 만들기",
        body:
          "지금 작품의 화풍·감독 노트와 배우(캐스팅 사진까지)를 그대로 물려받은 새 화를 만듭니다.\n" +
          "지금 작품은 그대로 남습니다.",
        initial: guess,
        okLabel: "만들기",
      });
      if (title === null) return;
      await engine.performSave(true);
      await engine.autosaveBeforeLeave();

      const source = get().project ?? cur;
      /**
       * 앞 화의 끝을 감독 노트에 남긴다 — 다음 화를 쓸 때 «어디서 끝났지»를 되짚으러
       * 앞 화를 다시 열지 않아도 되고, AI 이어쓰기 프롬프트에도 노트가 함께 실린다.
       */
      const tailLines = source.story.scenes
        .slice(-3)
        .map((sc) => (sc.text ?? "").trim())
        .filter(Boolean);
      const recap = tailLines.length
        ? `[앞 화 「${source.title}」의 끝]\n${tailLines.map((t) => `· ${t}`).join("\n")}`
        : "";
      // 요약 블록은 «가장 최근 것 하나»만 — 쌓이면 프롬프트가 지난 화 대사로 찬다(실측)
      const note = [stripRecaps(source.story.note ?? ""), recap].filter(Boolean).join("\n\n");
      const story: Story = {
        title: title.trim() || guess,
        style: source.story.style,
        ...(note ? { note } : {}),
        ...(source.story.coverByline ? { coverByline: source.story.coverByline } : {}),
        // 배우 명단은 그대로 — 사진은 아래에서 자산째로 복사한다
        characters: source.story.characters.map((c) => ({ ...c })),
        scenes: [{ id: "s01", shot: "full", text: "", speaker: "narration" }],
      };
      const rec = makeProject(story, story.title);
      // 캐스팅 사진을 새 프로젝트 키로 복사 — 배우단을 거치지 않아도 얼굴이 이어진다
      const carried = new Map<string, Blob>();
      const charAssets: Record<string, string> = {};
      for (const [ref, key] of Object.entries(source.charAssets)) {
        const blob = get().blobs[key];
        if (!blob) continue;
        const nk = db.assetKey(rec.id, "char", ref);
        carried.set(nk, blob);
        charAssets[ref] = nk;
      }
      rec.charAssets = charAssets;
      await engine.loadProjectIntoMemory(rec);
      if (carried.size > 0) {
        set((st) => ({
          blobs: { ...st.blobs, ...Object.fromEntries(carried) },
        }));
        engine.markDirty([...carried.keys()]);
      }
      set({ unsaved: true });
      await engine.performSave(true);
      get().toast(
        carried.size > 0
          ? `「${rec.title}」을 열었습니다. 배우 ${carried.size}명이 얼굴째로 따라왔어요.`
          : `「${rec.title}」을 열었습니다. 배우 명단은 물려받았고, 캐스팅 사진은 걸어주세요.`,
        "ok",
      );
    },

    openSample: async () => {
      await engine.autosaveBeforeLeave();
      const rec = makeProject(SAMPLE_STORY);
      await engine.loadProjectIntoMemory(rec);
      set({ unsaved: true });
      await engine.performSave(true);
      get().toast("샘플 「비 오는 역의 약속」을 열었습니다. 배우 사진을 캐스팅해 주세요.");
    },

    openProject: async (id) => {
      const cur = get().project;
      if (cur?.id === id) return;
      // 찍는 중이던 컷은 이 편에 «회수 가능» 표시를 남기고 떠난다 — 저장 «전»이어야 남는다
      const inFlight = engine.markInFlightDelayed();
      const leaving = cur?.title;
      await engine.autosaveBeforeLeave(); // 전환 전 자동저장
      const rec = await db.getProjectRecord(id);
      if (!rec) {
        get().toast("이 프로젝트를 찾을 수 없습니다. 필름캔(ZIP)에서 불러와 주세요.", "ng");
        db.removeProjectListEntry(id);
        set({ projectList: db.readProjectList() });
        return;
      }
      await engine.loadProjectIntoMemory(rec);
      get().toast(`「${rec.title}」을 열었습니다.`);
      if (inFlight > 0) {
        get().toast(
          `「${leaving}」에서 찍던 ${inFlight}컷은 이미 시작돼 과금됐습니다 — 그 편의 「결과 찾아오기」로 가져오세요.`,
          "info",
        );
      }
    },

    deleteProject: async (id) => {
      const entry = get().projectList.find((e) => e.id === id);
      const ok = await get().confirm({
        title: "프로젝트 지우기",
        body: `「${entry?.title ?? id}」을 이 브라우저에서 지웁니다. 필름캔(ZIP)으로 내보내지 않았다면 되돌릴 수 없습니다.`,
        okLabel: "지우기",
        danger: true,
      });
      if (!ok) return;
      await db.deleteProjectDeep(id);
      db.removeProjectListEntry(id);
      if (get().project?.id === id) {
        engine.stopAllShooting();
        set({ project: null, blobs: {}, dirtyAssets: [], unsaved: false });
        db.setLastProjectId(null);
      }
      set({ projectList: db.readProjectList() });
      get().toast("지웠습니다.");
    },

    saveNow: async (silent = false) => {
      await engine.performSave(silent);
    },

    saveAsNew: async () => {
      const p = get().project;
      if (!p) return;
      const title = await get().promptText({
        title: "다른 이름으로 저장",
        body: "새 복사본의 제목을 정해주세요. 지금 프로젝트는 그대로 남습니다.",
        initial: `${p.title} 사본`,
        okLabel: "복사본 만들기",
      });
      if (title === null) return;
      await engine.performSave(true);
      engine.stopAllShooting(); // 복사본으로 갈아타기 전, 진행 중 촬영이 엉뚱한 곳에 커밋되지 않게
      const s = get();
      const cur = s.project; // 대화상자 동안의 커밋까지 반영된 최신 상태에서 복사한다
      if (!cur) return;
      const newId = newProjectId();
      const remap = new Map<string, string>(); // oldKey -> newKey
      const rekey = (oldKey: string): string => {
        const found = remap.get(oldKey);
        if (found) return found;
        const nk = `${newId}${oldKey.slice(oldKey.indexOf(":"))}`;
        remap.set(oldKey, nk);
        return nk;
      };
      const cuts: Record<string, CutRecord> = {};
      for (const [sid, cut] of Object.entries(cur.cuts)) {
        cuts[sid] = {
          ...cut,
          imageKey: cut.imageKey ? rekey(cut.imageKey) : undefined,
          takeKeys: cut.takeKeys.map(rekey),
        };
      }
      const charAssets: Record<string, string> = {};
      for (const [ref, key] of Object.entries(cur.charAssets)) charAssets[ref] = rekey(key);
      const now = Date.now();
      const copy: ProjectRecord = {
        ...cur,
        id: newId,
        title: title.trim() || `${cur.title} 사본`,
        story: { ...cur.story, title: title.trim() || cur.story.title },
        cuts,
        charAssets,
        createdAt: now,
        updatedAt: now,
      };
      const newBlobs: Record<string, Blob> = {};
      for (const [oldKey, newKey] of remap) {
        const b = s.blobs[oldKey];
        if (b) newBlobs[newKey] = b;
      }
      set({
        project: copy,
        blobs: newBlobs,
        dirtyAssets: Object.keys(newBlobs),
        unsaved: true,
        saveSlots: [null, null, null],
        playSceneId: null,
        playHistory: [],
        choiceHistory: [],
      });
      await engine.performSave(true);
      get().toast(`「${copy.title}」 복사본으로 작업합니다.`, "ok");
    },

    scheduleAutosave: () => engine.scheduleAutosave(),

    /**
     * 저장소 청소 — 아무 작품도 참조하지 않는 그림·영상을 지운다.
     *
     * 예전에는 «지금 열린 작품»만 훑었다(`<id>:` 접두어). 20편을 쓰는 사람에게 그건 스무 번
     * 열어 스무 번 청소하라는 뜻이고, 목록에서 지운 작품이 남긴 그림은 영원히 안 잡혔다.
     * 이제 저장된 작품 전부의 참조를 모아 «아무도 안 쓰는 것»만 센다.
     * 다른 작품을 읽지 못하면(저장소 오류) 지금 작품 범위로 좁힌다 — 모르는 것을 지우지 않는다.
     */
    cleanStorage: async () => {
      const s = get();
      const p = s.project;
      if (!p) return;
      await engine.performSave(true); // 미저장분 먼저 안전하게
      const referenced = new Set<string>();
      const collect = (rec: ProjectRecord) => {
        for (const key of Object.values(rec.charAssets)) referenced.add(key);
        for (const cut of Object.values(rec.cuts)) {
          if (cut.imageKey) referenced.add(cut.imageKey);
          if (cut.videoKey) referenced.add(cut.videoKey);
          for (const k of cut.takeKeys) referenced.add(k);
        }
      };
      collect(p); // 지금 열린 작품은 방금 저장했지만 메모리 쪽이 가장 최신이다
      let works = 1;
      let allWorks = true;
      try {
        for (const rec of await db.listProjectRecords()) {
          if (rec.id === p.id) continue;
          collect(rec);
          works += 1;
        }
      } catch {
        allWorks = false;
      }
      const stored = await db.listAssetKeysByPrefix(allWorks ? "" : `${p.id}:`);
      const orphans = stored.filter((k) => !referenced.has(k));
      if (orphans.length === 0) {
        get().toast("청소할 것이 없습니다 — 저장소가 깨끗해요.", "ok");
        return;
      }
      const ok = await get().confirm({
        title: "저장소 청소",
        body:
          `작품 ${works}편을 훑어, 아무 컷도 참조하지 않는 고아 그림/영상 ${orphans.length}개를 지웁니다.\n` +
          "어느 작품의 컷·테이크·캐스팅 사진도 건드리지 않습니다. (지운 뒤 되돌릴 수 없어요)",
        okLabel: "청소하기",
        danger: true,
      });
      if (!ok) return;
      const bytes = await db.deleteAssetsMeasured(orphans);
      // 메모리 사본도 함께 치운다 — 남겨두면 다음 저장이 다시 써 넣어 «확보»가 거짓이 된다
      const gone = new Set(orphans);
      set((st) => {
        const blobs = { ...st.blobs };
        for (const k of orphans) delete blobs[k];
        return { blobs, dirtyAssets: st.dirtyAssets.filter((k) => !gone.has(k)) };
      });
      const mb = (bytes / 1024 / 1024).toFixed(1);
      get().toast(
        `저장소 청소 완료 — ${orphans.length}개, 약 ${mb}MB 확보 (작품 ${works}편 기준).${
          get().saveFailed
            ? " 다만 브라우저가 그 자리를 곧바로 돌려주지 않을 수 있습니다 — 저장이 계속 안 되면 «내 기기로 내보내기»로 먼저 챙겨두세요."
            : ""
        }`,
        "ok",
      );
    },

    exportProject: async () => {
      if (!get().project) return;
      // 필름캔 리마인더의 기준 시각 — 내보내기와 함께 저장된다
      engine.patchProject((cur) => ({ ...cur, lastExportAt: Date.now() }));
      await engine.performSave(true);
      const s = get();
      const p = s.project;
      if (!p) return;
      // OK 컷만 generated/로 — NG 컷의 이전 그림이 재가져오기에서 OK로 둔갑하지 않게
      const images = collectOkImages(p, s.blobs);
      const chars = new Map<string, Blob>();
      for (const [ref, key] of Object.entries(p.charAssets)) {
        const b = s.blobs[key];
        if (b) chars.set(ref, b);
      }
      const saves = new Map<number, SaveSlot>();
      s.saveSlots.forEach((slot, i) => {
        if (slot) saves.set(i + 1, slot);
      });
      // NG 판정 컷의 현재 그림, 모든 테이크, 무빙(영상)도 필름캔에 담는다 (ZIP이 곧 백업)
      const ngImages = new Map<string, Blob>();
      const takes = new Map<string, Blob[]>();
      const videos = new Map<string, Blob>();
      for (const scene of p.story.scenes) {
        const cut = p.cuts[scene.id];
        if (!cut) continue;
        if (cut.status === "ng" && cut.imageKey) {
          const b = s.blobs[cut.imageKey];
          if (b) ngImages.set(scene.id, b);
        }
        if (cut.takeKeys.length > 0) {
          const blobs = cut.takeKeys.map((k) => s.blobs[k]).filter((b): b is Blob => Boolean(b));
          if (blobs.length > 0) takes.set(scene.id, blobs);
        }
        if (cut.videoKey) {
          const b = s.blobs[cut.videoKey];
          if (b) videos.set(scene.id, b);
        }
      }
      // 시사본 동봉 — OK 컷이 있으면 물어본다. 그림이 HTML 안에 한 번 더 담겨 파일이 커진다.
      // 묻는 순서는 시사본 → 인쇄본이지만, HTML은 «인쇄본이 함께 담기는지»를 알아야 크레딧
      // 끝에 그 위치를 적을 수 있어서 실제 생성은 아래로 미룬다.
      let screeningHtml: string | undefined;
      let wantHtml = false;
      if (images.size > 0) {
        const withHtml = await get().confirm({
          title: "시사본도 함께 넣을까요?",
          body:
            "필름캔 안에 감상용 screening.html을 함께 담습니다 — ZIP 하나로 보관과 감상이 다 돼요.\n" +
            "(그림이 HTML에 한 번 더 담겨 파일이 커집니다. 토큰은 담기지 않습니다)",
          okLabel: "함께 넣기",
          cancelLabel: "그림만",
        });
        wantHtml = withHtml;
      }
      // 인쇄본 동봉 — 감독이 조판을 손댄 적이 있을 때만 묻는다(안 쓰는 사람에게 창을 띄우지 않는다)
      let webtoonPages: Blob[] | undefined;
      let webtoonPdf: Blob | undefined;
      let webtoonIndex: Blob | undefined;
      if (images.size > 0 && hasWebtoonSetup(p)) {
        const withToon = await get().confirm({
          title: "인쇄본도 함께 넣을까요?",
          body:
            "필름캔 안 webtoon/ 폴더에 만화 페이지 PNG·PDF 한 부·인덱스 시트를 담습니다 — ZIP 하나로 보관·감상·인쇄가 다 돼요.\n" +
            "(페이지를 다시 그리는 데 크레딧은 들지 않습니다)",
          okLabel: "함께 넣기",
          cancelLabel: "넣지 않기",
        });
        if (withToon) {
          const panels = await collectWebtoonPanels(p, s.blobs);
          try {
            if (panels.length > 0) {
              const coverIndex = p.posterSceneId
                ? Math.max(
                    0,
                    panels.findIndex((pl) => pl.scene.id === p.posterSceneId),
                  )
                : 0;
              // 등장인물 장도 함께 — 필름캔은 «완성본»이므로 단행본 한 벌이 다 들어가야 한다
              const cards: CastCard[] = [];
              const shelf = get().troupe;
              const others = await otherFilmTitles(get, p.title, p.story.title);
              for (const c of collectCastPhotos(p, s.blobs)) {
                cards.push({
                  name: c.name,
                  look: c.look,
                  cuts: c.cuts,
                  crop: c.crop,
                  films: shelf.find((a) => a.name === c.name)?.appearances,
                  filmTitles: others(c.name),
                  bitmap: await createImageBitmap(c.blob),
                });
              }
              const built = await buildWebtoon(
                p.story,
                panels,
                { coverIndex, castPage: cards.length > 0 },
                cards,
              );
              for (const c of cards) c.bitmap.close?.();
              webtoonPages = built.pages;
              // 같은 페이지로 PDF도 한 부 — 인쇄소에 넘기거나 메일에 붙일 때 그대로 쓴다
              try {
                webtoonPdf = await buildPdf(built.pages, p.title);
              } catch {
                /* PDF는 덤이다 — 실패해도 PNG 인쇄본은 그대로 담긴다 */
              }
              // 인덱스 시트도 덤 — 장이 넷 이상일 때만(둘셋짜리에 시트는 뜻이 없다)
              if (built.pages.length >= 4) {
                try {
                  // 표지·목차가 앞에 붙은 만큼(lead) 장 쪽번호를 밀어야 칸이 맞는다
                  webtoonIndex = await buildIndexSheet(
                    built.pages,
                    p.title,
                    undefined,
                    4,
                    built.chapters.map((c) => ({
                      ...c,
                      page: c.page + built.lead,
                    })),
                  );
                } catch {
                  /* 시트도 덤이다 */
                }
              }
            }
          } catch (err) {
            get().toast(
              `인쇄본을 만들지 못해 그림만 담습니다. (${err instanceof Error ? err.message : "알 수 없는 문제"})`,
              "ng",
            );
          } finally {
            for (const pl of panels) pl.bitmap.close?.();
          }
        }
      }
      // 시사본 HTML은 여기서 만든다 — 인쇄본이 함께 담기는지 알아야 크레딧 끝에 그 위치를 적는다
      if (wantHtml) {
        const dataUrls = new Map<string, string>();
        for (const [sceneId, blob] of images) dataUrls.set(sceneId, await blobToDataUrl(blob));
        const posterUrl = p.posterSceneId ? (dataUrls.get(p.posterSceneId) ?? null) : null;
        screeningHtml = buildScreeningHtml(p.story, dataUrls, posterUrl, {
          coinsSpent: p.coinsSpent,
          typeMs: s.typeMs,
          fontScale: s.fontScale,
          hasPrintBook: Boolean(webtoonPages?.length),
          // 작은 미리보기 (수십 KB) — 표지에서 «만화판도 있다»를 보여준다.
          // 0번은 인쇄본 «표지»라 아래 절반이 검은 제목 띠다 → 54px로 줄이면 빈 상자로 보인다.
          // 컷이 들어 있는 본문 첫 장을 쓴다.
          printThumb: webtoonPages?.length
            ? await thumbDataUrl(webtoonPages[webtoonPages.length > 1 ? 1 : 0])
            : null,
        });
      }

      // 전속 배우단 — 기기를 옮겨도 배우가 따라오도록 함께 담는다(있을 때만)
      let troupe: Awaited<ReturnType<typeof db.listTroupe>> = [];
      try {
        troupe = await db.listTroupe();
      } catch {
        /* 배우단을 못 읽어도 작품 백업은 계속한다 */
      }
      // 토큰은 절대 포함하지 않는다.
      const zip = await buildVnprojZip({
        project: p,
        images,
        ngImages,
        takes,
        videos,
        chars,
        saves,
        screeningHtml,
        webtoonPages,
        webtoonPdf,
        webtoonIndex,
        troupe,
      });
      downloadBlob(`${safeFileName(p.title)}.vnproj.zip`, zip);
      get().toast("필름캔을 내보냈습니다. 내 폴더의 ZIP이 곧 백업입니다.", "ok");
    },

    /**
     * 필름캔 일괄 내보내기 — 이 브라우저의 모든 작품을 각자의 필름캔 ZIP으로.
     *
     * 여러 작품을 «작품집» 하나로 묶는 안도 있었지만 새 ZIP 구조와 새 가져오기 경로가 필요해
     * 위험만 늘어난다. 기기를 옮길 때 필요한 건 «전부 다 챙기기»이므로, 이미 검증된 필름캔
     * 형식을 작품마다 하나씩 낸다 — 가져오기는 지금 그대로 쓰면 된다.
     * 시사본·인쇄본은 넣지 않는다(작품마다 확인창을 두 번 띄우게 되고, 파일이 몇 배로 커진다).
     */
    /**
     * 합본 — 이 연재의 화들을 «한 권»으로 묶어 PDF 한 파일로 낸다. 크레딧은 들지 않는다.
     *
     * 연재의 끝에 오는 일이다. 지금까지는 화마다 인쇄본을 뽑아야 했고, 그러면 표지도 목차도
     * 쪽 번호도 다섯 벌이 되어 «책장에 꽂을 한 권»이 없었다. 같은 앞머리를 가진 화들을
     * 번호 순서로 모아 표지 한 장·목차 한 장·등장인물 한 장을 책 전체에 두고 쪽 번호를 이어 센다.
     * 한 컷도 안 찍은 화는 조용히 건너뛴다(빈 쪽을 넣는 것보다 낫다).
     */
    exportOmnibus: async () => {
      const cur = get().project;
      if (!cur) {
        get().toast("먼저 작품을 열어주세요 — 그 작품이 속한 연재를 묶습니다.");
        return;
      }
      const here = parseEpisode(cur.title);
      if (!here) {
        get().toast(
          "이 작품에는 화 번호가 없습니다 — 「우산 3화」·「우산 1편」·「우산 (상)」처럼 번호로 끝나는 제목들을 한 권으로 묶습니다.",
          "ng",
        );
        return;
      }
      const stem = here.stem.trim();
      const mates = get()
        .projectList.map((e) => ({ e, p: parseEpisode(e.title) }))
        .filter((x) => x.p && x.p.key === here.key && x.e.okCount > 0)
        .sort((a, b) => (a.p?.num ?? 0) - (b.p?.num ?? 0));
      if (mates.length === 0) {
        get().toast("묶을 화가 없습니다 — 적어도 한 컷은 찍힌 화가 필요해요.");
        return;
      }
      const seriesTitle = stem || cur.title;
      const skipped = get().projectList.filter(
        (e) => parseEpisode(e.title)?.key === here.key && e.okCount === 0,
      ).length;
      /**
       * 얼마나 큰 책이 되는지 미리 말한다 — 실측(20편 160컷)이 43쪽·35.3MB·10초였다.
       * 쪽은 «컷 ÷ 한 쪽 4컷 + 화마다 한 번 끊기 + 표지·목차·등장인물»,
       * 크기는 쪽당 0.82MB, 시간은 쪽당 0.23초로 어림한다(폰에서 누르기 전에 알 만한 값).
       */
      const okCuts = mates.reduce((n, m) => n + m.e.okCount, 0);
      /* 쪽은 «편마다» 센다 — 화가 바뀌는 자리에서 쪽이 끊기므로 전체를 한 번에 나누면 과대평가된다
         (2편 4컷에서 6쪽이라 했는데 실제는 4쪽이었다 — 실측으로 잡은 어림의 오차).
         여기에 표지·목차 두 쪽을 더한다(등장인물 장은 사진이 걸린 배우가 있을 때만 한 쪽 더). */
      const estPages =
        mates.reduce((n, m) => n + Math.max(1, Math.ceil(m.e.okCount / 4)), 0) + 2;
      /* 용량은 «쪽»이 아니라 «컷» 수를 따른다 — 한 쪽에 컷이 둘이면 넷일 때의 절반이다.
         두 번의 실측에서 나온 상수: 20편 160컷 = 35.3MB(0.22MB/컷), 50편 100컷 = 22.8MB(0.23MB/컷).
         시간도 두 점에 맞췄다: 20편 43쪽·160컷 = 10초, 50편 52쪽·100컷 = 7초. */
      const estMb = Math.max(1, Math.round(okCuts * 0.22));
      const estSec = Math.max(1, Math.round(estPages * 0.05 + okCuts * 0.045));
      const ok = await get().confirm({
        title: `「${seriesTitle}」 합본 만들기`,
        body:
          `${mates.map((m) => m.e.title).join(" · ")}
` +
          `${mates.length}편 ${okCuts}컷을 한 권으로 묶습니다 — 표지·목차·등장인물 장은 한 번만 들어가고 쪽 번호가 이어집니다.
` +
          (skipped > 0 ? `아직 한 컷도 안 찍은 ${skipped}편은 건너뜁니다.
` : "") +
          `대략 ${estPages}쪽 · ${estMb}MB · ${estSec}초쯤 걸립니다. PDF 한 파일로 나옵니다. (크레딧은 들지 않아요)`,
        okLabel: "묶기",
      });
      if (!ok) return;
      await engine.performSave(true);
      get().toast(`「${seriesTitle}」 ${mates.length}편을 조판하는 중입니다…`);

      const volumes: OmnibusVolume[] = [];
      const cards: CastCard[] = [];
      const castSeen = new Map<string, CastCard>();
      const others = await otherFilmTitles(get, ...get().projectList.filter((e) => parseEpisode(e.title)?.stem.trim() === stem).map((e) => e.title));
      try {
        for (const m of mates) {
          // 지금 열린 편은 메모리의 것을 쓴다(방금 찍은 컷까지 들어간다)
          const rec = m.e.id === cur.id ? cur : await db.getProjectRecord(m.e.id);
          if (!rec) continue;
          let blobs: Record<string, Blob>;
          if (m.e.id === cur.id) {
            blobs = get().blobs;
          } else {
            const keys: string[] = [];
            for (const key of Object.values(rec.charAssets)) keys.push(key);
            for (const c of Object.values(rec.cuts)) if (c.imageKey) keys.push(c.imageKey);
            const loaded = await db.getAssets(keys);
            blobs = {};
            for (const [k, v] of loaded) blobs[k] = v;
          }
          const panels = await collectWebtoonPanels(rec, blobs);
          if (panels.length === 0) continue;
          volumes.push({ title: rec.title, story: rec.story, panels });
          // 등장인물은 이름으로 합친다 — 같은 배우가 여러 화에 나오면 컷 수를 더한다
          for (const c of collectCastPhotos(rec, blobs)) {
            const had = castSeen.get(c.name);
            if (had) {
              had.cuts = (had.cuts ?? 0) + c.cuts;
              continue;
            }
            const card: CastCard = {
              name: c.name,
              look: c.look,
              cuts: c.cuts,
              crop: c.crop,
              filmTitles: others(c.name),
              bitmap: await createImageBitmap(c.blob),
            };
            castSeen.set(c.name, card);
            cards.push(card);
          }
        }
        if (volumes.length === 0) {
          get().toast("묶을 그림이 없습니다 — 찍은 컷이 있는 화가 필요해요.", "ng");
          return;
        }
        const t0 = Date.now();
        const { pages, entries } = await buildOmnibus(
          seriesTitle,
          volumes,
          { castPage: cards.length > 0, contents: true, cover: true },
          cards,
        );
        const pdf = await buildPdf(pages, `${seriesTitle} 합본`);
        downloadBlob(`${safeFileName(seriesTitle)}-합본.pdf`, pdf);
        const cuts = volumes.reduce((n, v) => n + v.panels.length, 0);
        get().toast(
          `「${seriesTitle}」 합본 ${pages.length}쪽(${entries.length}편 · ${cuts}컷)을 PDF로 내보냈습니다 — ${Math.round((Date.now() - t0) / 1000)}초. 크레딧은 쓰지 않았어요.`,
          "ok",
        );
      } catch (err) {
        get().toast(
          `합본을 만들지 못했습니다. (${err instanceof Error ? err.message : String(err)})`,
          "ng",
        );
      } finally {
        for (const v of volumes) for (const pl of v.panels) pl.bitmap.close?.();
        for (const c of cards) c.bitmap.close?.();
      }
    },

    /**
     * 연재 검색 — 저장된 작품 전부에서 대사·컷 제목·말풍선을 찾는다.
     *
     * 20편 240컷이 쌓이면 「그 대사가 몇 화였지」가 실제 질문이 된다. 지금까지 답할 곳이 없었다.
     * 지금 열린 편은 메모리의 것으로 본다(방금 고친 대사도 찾힌다). 대소문자·공백은 느슨하게.
     */
    searchAllProjects: async (query) => {
      const q = query.trim().toLowerCase();
      if (q.length < 2) return [];
      const cur = get().project;
      let recs: ProjectRecord[] = [];
      try {
        const stored = await db.listProjectRecords();
        recs = cur
          ? stored.some((r) => r.id === cur.id)
            ? stored.map((r) => (r.id === cur.id ? cur : r))
            : [...stored, cur]
          : stored;
      } catch {
        if (cur) recs = [cur];
      }
      const hits: SearchHit[] = [];
      const cut = (text: string) => {
        const at = text.toLowerCase().indexOf(q);
        if (at < 0) return "";
        const from = Math.max(0, at - 18);
        const to = Math.min(text.length, at + q.length + 22);
        return `${from > 0 ? "…" : ""}${text.slice(from, to)}${to < text.length ? "…" : ""}`;
      };
      for (const rec of recs) {
        const ranges = chapterRanges(rec.story.scenes);
        const named = ranges.length >= 2;
        for (const sc of rec.story.scenes) {
          const where: [SearchHit["where"], string][] = [
            ["대사", sc.text ?? ""],
            ["컷 제목", sc.webtoon?.caption ?? ""],
            ["말풍선", sc.webtoon?.line ?? ""],
          ];
          for (const [kind, text] of where) {
            if (!text || !text.toLowerCase().includes(q)) continue;
            hits.push({
              projectId: rec.id,
              projectTitle: rec.title,
              sceneId: sc.id,
              chapter: named ? (ranges.find((r) => r.ids.includes(sc.id))?.title ?? "") : "",
              where: kind,
              status: rec.cuts[sc.id]?.status ?? "wait",
              excerpt: cut(text),
            });
            break; // 한 컷은 한 줄로 — 같은 컷이 세 번 나오면 목록이 흐려진다
          }
        }
      }
      return hits.slice(0, 60); // 예순 줄이면 충분하다 — 더 좁혀 찾는 편이 빠르다
    },

    exportAllProjects: async () => {
      const list = get().projectList;
      if (list.length === 0) {
        get().toast("내보낼 작품이 없습니다.");
        return;
      }
      const ok = await get().confirm({
        title: `작품 ${list.length}편을 모두 내보낼까요?`,
        body:
          "작품마다 필름캔(ZIP) 하나씩, 모두 " +
          `${list.length}개 파일이 저장됩니다 — 새 기기로 옮길 때 쓰세요.
` +
          "시사본·인쇄본은 넣지 않습니다(파일이 몇 배로 커지고 작품마다 물어야 합니다).",
        okLabel: "모두 내보내기",
      });
      if (!ok) return;
      await engine.performSave(true); // 지금 열려 있는 작품의 마지막 변경까지 담는다
      // 배우단 명단은 한 번만 읽어 모든 필름캔에 같이 담는다
      let shelf: Awaited<ReturnType<typeof db.listTroupe>> = [];
      try {
        shelf = await db.listTroupe();
      } catch {
        /* 배우단을 못 읽어도 작품 자체는 내보낸다 */
      }
      let done = 0;
      const failed: string[] = [];
      for (const entry of list) {
        try {
          const rec = await db.getProjectRecord(entry.id);
          if (!rec) {
            failed.push(entry.title);
            continue;
          }
          // 이 작품의 자산 전부를 저장소에서 직접 읽는다 (메모리에 올리지 않는다)
          const keys = await db.listAssetKeysByPrefix(`${rec.id}:`);
          const assets = await db.getAssets(keys);
          const images = new Map<string, Blob>();
          const ngImages = new Map<string, Blob>();
          const takes = new Map<string, Blob[]>();
          const videos = new Map<string, Blob>();
          const chars = new Map<string, Blob>();
          for (const scene of rec.story.scenes) {
            const cut = rec.cuts[scene.id];
            if (!cut) continue;
            const img = cut.imageKey ? assets.get(cut.imageKey) : undefined;
            if (img) (cut.status === "ng" ? ngImages : images).set(scene.id, img);
            const ts = cut.takeKeys.map((k) => assets.get(k)).filter((b): b is Blob => Boolean(b));
            if (ts.length) takes.set(scene.id, ts);
            const vid = cut.videoKey ? assets.get(cut.videoKey) : undefined;
            if (vid) videos.set(scene.id, vid);
          }
          for (const [ref, key] of Object.entries(rec.charAssets)) {
            const b = assets.get(key);
            if (b) chars.set(ref, b);
          }
          const saves = new Map<number, SaveSlot>();
          for (const slot of [1, 2, 3]) {
            const sv = await db.getSaveSlot(rec.id, slot);
            if (sv) saves.set(slot, sv);
          }
          const zip = await buildVnprojZip({
            project: rec,
            images,
            ngImages,
            takes,
            videos,
            chars,
            saves,
            // 배우단은 프로젝트 밖에 산다 — 이걸 빼면 새 기기에서 «다음 화»를 이어 쓸 때
            // 같은 얼굴을 데려올 수 없다. 어느 파일을 먼저 가져올지 모르므로 전부에 담는다.
            troupe: shelf,
          });
          downloadBlob(`${safeFileName(rec.title)}.vnproj.zip`, zip);
          // 백업 기록을 남긴다 — 없으면 콜시트가 계속 «필름캔이 없다»고 말한다
          const stamped: ProjectRecord = { ...rec, lastExportAt: Date.now() };
          await db.putProjectRecord(stamped);
          db.upsertProjectListEntry(listEntryOf(stamped));
          if (get().project?.id === stamped.id) {
            engine.patchProject((cur) => ({
              ...cur,
              lastExportAt: stamped.lastExportAt,
            }));
          }
          done += 1;
        } catch {
          failed.push(entry.title);
        }
      }
      set({ projectList: db.readProjectList() });
      get().toast(
        failed.length === 0
          ? `작품 ${done}편을 모두 내보냈습니다. 새 기기에서 「내 기기에서 불러오기」로 하나씩 넣으세요.`
          : `${done}편을 내보냈습니다. 실패: ${failed.join(", ")}`,
        failed.length === 0 ? "ok" : "ng",
      );
    },

    exportGeneratedImages: async () => {
      const s = get();
      const p = s.project;
      if (!p) return;
      const images = collectOkImages(p, s.blobs);
      if (images.size === 0) {
        get().toast("아직 내보낼 생성 이미지가 없습니다.");
        return;
      }
      downloadBlob(`${safeFileName(p.title)}-generated.zip`, await buildGeneratedZip(images));
      get().toast(`생성 이미지 ${images.size}장을 ZIP으로 내보냈습니다.`, "ok");
    },

    exportWebtoon: async (options) => {
      const s = get();
      const p = s.project;
      if (!p) return;
      const okBlobs = collectOkImages(p, s.blobs);
      if (okBlobs.size === 0) {
        get().toast("아직 OK 컷이 없습니다. 촬영장에서 먼저 찍어주세요.");
        return;
      }
      const panels = await collectWebtoonPanels(p, s.blobs);
      /**
       * 「이 장만」 — 연재는 화마다 파일 하나로 올린다. 표지·목차·등장인물 장은
       * «책 전체»의 것이라 한 장만 낼 때는 뺀다(장 제목 띠가 표제 노릇을 한다).
       */
      let scope = panels;
      let chapterName = "";
      if (options?.onlyChapter) {
        const range = chapterRanges(p.story.scenes).find((c) => c.firstId === options.onlyChapter);
        const ids = new Set(range?.ids ?? []);
        scope = panels.filter((pl) => ids.has(pl.scene.id));
        chapterName = range?.title ?? "";
        if (!range || scope.length === 0) {
          for (const pl of panels) pl.bitmap.close?.();
          get().toast(
            range
              ? `「${range.title}」에는 아직 찍은 컷이 없습니다 — 인쇄본에는 찍은 컷만 담깁니다.`
              : "그 장을 찾지 못했습니다. 장 나누기를 다시 확인해 주세요.",
          );
          return;
        }
      }
      const fileBase = chapterName
        ? `${safeFileName(p.title)}-${safeFileName(chapterName)}`
        : safeFileName(p.title);
      try {
        // 표지 컷 — 감독이 지정한 표지가 인쇄본에 있으면 그것을, 없으면 첫 컷
        const coverIndex = p.posterSceneId
          ? Math.max(
              0,
              panels.findIndex((pl) => pl.scene.id === p.posterSceneId),
            )
          : 0;
        // 등장인물 장 — 캐스팅 사진이 걸린 배우만 실린다
        const cards: CastCard[] = [];
        if (options?.castPage) {
          const others = await otherFilmTitles(get, p.title, p.story.title);
          for (const c of collectCastPhotos(p, s.blobs)) {
            cards.push({
              name: c.name,
              look: c.look,
              cuts: c.cuts,
              crop: c.crop,
              films: get().troupe.find((a) => a.name === c.name)?.appearances,
              filmTitles: others(c.name),
              bitmap: await createImageBitmap(c.blob),
            });
          }
        }
        const { pages, panelCount, chapters, lead } = await buildWebtoon(
          p.story,
          scope,
          chapterName
            ? {
                ...options,
                coverIndex,
                cover: false,
                contents: false,
                castPage: false,
              }
            : { ...options, coverIndex },
          cards,
        );
        for (const c of cards) c.bitmap.close?.();

        // 연재 전체의 리듬 보기 — 모든 장을 한 장에 축소해 나열
        if (options?.indexSheet) {
          const sheet = await buildIndexSheet(
            pages,
            p.title,
            options,
            4,
            chapters.map((c) => ({ ...c, page: c.page + lead })),
          );
          downloadBlob(`${fileBase}-인덱스시트.png`, sheet);
          get().toast(`${pages.length}장을 한 장에 나열한 인덱스 시트를 내보냈습니다.`, "ok");
          return;
        }

        // 인쇄·문서 첨부용 — 한 파일 PDF (라이브러리 없이 직접 쓴다)
        if (options?.pdf) {
          const pdf = await buildPdf(pages, p.title);
          downloadBlob(`${fileBase}-인쇄본.pdf`, pdf);
          get().toast(
            `인쇄본 ${pages.length}장을 PDF 한 파일로 내보냈습니다 (${panelCount}컷).`,
            "ok",
          );
          return;
        }

        // 웹툰 업로드용 — 여러 장을 세로로 이어 한 장으로 (너무 길면 나눠서 여러 장)
        if (options?.strip) {
          const strips = await stitchPages(pages);
          const base = fileBase;
          strips.forEach((b, i) => {
            downloadBlob(
              strips.length === 1
                ? `${base}-인쇄본-긴스크롤.png`
                : `${base}-인쇄본-긴스크롤-${i + 1}.png`,
              b,
            );
          });
          get().toast(
            strips.length === 1
              ? `인쇄본 ${pages.length}장을 긴 스크롤 한 장으로 이어 붙였습니다 (${panelCount}컷).`
              : `너무 길어 ${strips.length}장으로 나눠 이어 붙였습니다 (${pages.length}장 · ${panelCount}컷).`,
            "ok",
          );
          return;
        }
        if (pages.length === 1) {
          downloadBlob(`${fileBase}-인쇄본.png`, pages[0]);
        } else {
          // 표지가 있으면 0번이 표지 — 파일명으로 구분해 순서가 헷갈리지 않게
          const hasCover = !chapterName && options?.cover !== false;
          for (let i = 0; i < pages.length; i++) {
            const name = hasCover
              ? i === 0
                ? `${fileBase}-인쇄본-00-표지.png`
                : `${fileBase}-인쇄본-${String(i).padStart(2, "0")}.png`
              : `${fileBase}-인쇄본-${String(i + 1).padStart(2, "0")}.png`;
            downloadBlob(name, pages[i]);
          }
        }
        get().toast(
          chapterName
            ? `「${chapterName}」만 ${pages.length}장(${panelCount}컷) 내보냈습니다 — 표지·목차·등장인물 장은 빼고 그 장만 담았어요.`
            : `인쇄본 ${pages.length}장(${panelCount}컷)을 내보냈습니다. 크레딧은 쓰지 않았어요.`,
          "ok",
        );
      } catch (err) {
        get().toast(err instanceof Error ? err.message : "인쇄본을 만들지 못했습니다.", "ng");
      } finally {
        for (const pl of panels) pl.bitmap.close?.();
      }
    },

    exportScreeningHtml: async (onlyChapter) => {
      const s = get();
      const p = s.project;
      if (!p) return;
      /**
       * 「이 장만」 — 인쇄본에는 있는데 시사본에는 없었다. 연재는 화마다 파일 하나로 준다.
       * 그 장의 컷만 담고, 장 밖을 가리키는 연결은 끊는다(그 컷이 이 파일에는 없으니까).
       * 그림도 그 장 것만 담는다 — 안 그러면 파일이 책 한 권 무게로 나간다.
       */
      const range = onlyChapter
        ? chapterRanges(p.story.scenes).find((c) => c.firstId === onlyChapter)
        : undefined;
      if (onlyChapter && !range) {
        get().toast("그 장을 찾지 못했습니다. 장 나누기를 다시 확인해 주세요.");
        return;
      }
      const keep = range ? new Set(range.ids) : null;
      const okBlobs = collectOkImages(p, s.blobs);
      const images = new Map<string, string>();
      for (const [sceneId, blob] of okBlobs) {
        if (keep && !keep.has(sceneId)) continue;
        images.set(sceneId, await blobToDataUrl(blob));
      }
      if (images.size === 0) {
        get().toast(
          range
            ? `「${range.title}」에는 찍어둔 컷이 없습니다 — 시사본에는 찍은 컷만 담깁니다.`
            : "OK 컷이 아직 없습니다. 촬영장에서 먼저 찍어주세요.",
        );
        return;
      }
      const story: Story = keep
        ? {
            ...p.story,
            title: `${p.story.title} — ${range?.title ?? ""}`,
            scenes: p.story.scenes
              .filter((sc) => keep.has(sc.id))
              .map((sc) => ({
                ...sc,
                ...(sc.next && !keep.has(sc.next) ? { next: undefined } : {}),
                ...(sc.choices
                  ? {
                      choices: sc.choices.filter((c) => keep.has(c.next)),
                    }
                  : {}),
              })),
          }
        : p.story;
      // 표지는 그 장 안의 컷이어야 한다 — 감독이 지정한 표지가 다른 장이면 그 장 첫 컷을 쓴다
      const posterId =
        p.posterSceneId && images.has(p.posterSceneId)
          ? p.posterSceneId
          : keep
            ? (story.scenes.find((sc) => images.has(sc.id))?.id ?? null)
            : null;
      const posterUrl = posterId ? (images.get(posterId) ?? null) : null;
      const html = buildScreeningHtml(story, images, posterUrl, {
        coinsSpent: p.coinsSpent,
        typeMs: s.typeMs,
        fontScale: s.fontScale,
      });
      const base = range
        ? `${safeFileName(p.title)}-${safeFileName(range.title)}`
        : safeFileName(p.title);
      downloadBlob(`${base}-screening.html`, new Blob([html], { type: "text/html;charset=utf-8" }));
      get().toast(
        range
          ? `「${range.title}」만 담은 시사본을 내보냈습니다 (${images.size}컷). 공개용이 아닌 내 기기용입니다.`
          : "시사본 HTML을 내보냈습니다. 공개용이 아닌 내 기기용입니다.",
        "ok",
      );
    },

    /**
     * 필름캔 여럿을 한 번에 들여온다 — 「🎞 모두 내보내기」의 반대편.
     *
     * 20화를 한 번에 꺼내 놓고 돌아올 때 스무 번 클릭해야 하면 그건 이사가 아니다.
     * 한 편씩 순서대로 들여오고(마지막 편이 열린 상태로 남는다), 편마다 토스트를 띄우는
     * 대신 끝에 한 줄로 요약한다 — 스무 줄이 쌓이면 아무도 읽지 않는다.
     */
    importManyFromFiles: async (files) => {
      const list = [...files];
      if (list.length === 0) return;
      if (list.length === 1) {
        await get().importFromFile(list[0]);
        return;
      }
      /**
       * 이미 있는 필름캔이 섞여 있으면 «한 번만» 묻는다 — 스무 편마다 물으면 이사가 막힌다.
       * 지문(meta.json의 projectId)만 싸게 먼저 읽어 몇 개가 겹치는지 센다.
       */
      let policy: "replace" | "copy" = "copy";
      let dupes = 0;
      for (const f of list) {
        const pid = await readFilmcanProjectId(f);
        if (pid && (await db.getProjectRecord(pid))) dupes += 1;
      }
      if (dupes > 0) {
        const replaceAll = await get().confirm({
          title: `이미 있는 필름캔 ${dupes}개`,
          body:
            `들여올 ${list.length}개 중 ${dupes}개는 이 브라우저에 이미 있는 작품과 같은 필름캔입니다.\n` +
            "「전부 교체」는 이 브라우저의 그 작품들을 필름캔 내용으로 바꿉니다(지금 내용은 사라집니다).\n" +
            "「전부 사본으로」는 둘 다 남깁니다.",
          okLabel: "전부 교체",
          cancelLabel: "전부 사본으로",
          danger: true,
        });
        policy = replaceAll ? "replace" : "copy";
      }
      let done = 0;
      const failed: string[] = [];
      for (const f of list) {
        try {
          await get().importFromFile(f, true, policy);
          done += 1;
        } catch {
          failed.push(f.name);
        }
      }
      set({ projectList: db.readProjectList() });
      get().toast(
        `필름캔 ${done}개를 들여왔습니다 — 「최근 프로젝트」에서 골라 여세요.` +
          (failed.length > 0 ? ` (${failed.length}개는 읽지 못했습니다: ${failed[0]}…)` : ""),
        failed.length > 0 ? "ng" : "ok",
      );
    },

    importFromFile: async (file, quiet, dupPolicy) => {
      const isZip =
        /\.zip$/i.test(file.name) ||
        file.type === "application/zip" ||
        file.type === "application/x-zip-compressed";
      try {
        /* 큰 필름캔은 화면을 오래 막는다 — 실측(v1.6.0): 17.7MB(600컷·그림 60장) 캔에서
           2,271ms 동안 아무 말 없이 멈췄고, 끝나서야 「열었습니다」가 떴다. 새 기기에서
           «내 작품이 살아 있나»를 확인하는 순간이라 그 침묵이 가장 무섭다.
           그래서 무거운 일 «전에» 한 번 말하고 그리게 한다(반영과 같은 규칙). */
        if (!quiet) {
          const mb = file.size / 1024 / 1024;
          get().toast(`필름캔 「${file.name}」을 여는 중… (${mb >= 0.1 ? `${mb.toFixed(1)}MB` : "작은 캔"})`);
          await nextPaint();
        }
        await engine.autosaveBeforeLeave();
        if (isZip) {
          const imported = await readVnprojZip(file);
          // 같은 필름캔의 프로젝트가 이미 있으면 — 교체할지, 사본으로 열지 묻는다
          let replaceId: string | null = null;
          /**
           * 지문 물려받기 — 예전에는 들여올 때 새 id를 발급해서, 같은 필름캔을 다시 넣으면
           * «이미 있다»를 알아채지 못하고 조용히 사본이 쌓였다(실측: 3개 → 6개).
           * 겹치는 기록이 없으면 필름캔의 projectId를 그대로 쓴다 — 그러면 다음에 다시 넣을 때
           * 같은 작품임을 알아본다(다른 기기에서 내보낸 필름캔도 마찬가지).
           */
          let adoptId: string | null = null;
          if (imported.meta.projectId) {
            const existing = await db.getProjectRecord(imported.meta.projectId);
            if (!existing) {
              adoptId = imported.meta.projectId;
            } else if (dupPolicy === "replace") {
              replaceId = existing.id;
            } else if (dupPolicy === "copy") {
              /* 여러 개를 들여오는 중 — 이미 한 번 물었다. 사본으로 둔다 */
            } else {
              const replace = await get().confirm({
                title: "이미 있는 필름캔",
                body:
                  `이 필름캔의 프로젝트 「${existing.title}」이 이 브라우저에 이미 있습니다.\n` +
                  "필름캔 내용으로 교체할까요? (교체하면 이 브라우저의 현재 내용은 사라집니다)\n" +
                  "「사본으로 열기」를 고르면 둘 다 남습니다.",
                okLabel: "교체하기",
                cancelLabel: "사본으로 열기",
                danger: true,
              });
              if (replace) replaceId = existing.id;
            }
          }
          const rec = makeProject(imported.story, imported.meta.title ?? imported.story.title);
          if (replaceId) {
            await db.deleteProjectDeep(replaceId);
            db.removeProjectListEntry(replaceId);
            rec.id = replaceId; // 같은 지문 유지 — 목록·세이브가 한 자리를 지킨다
          } else if (adoptId) {
            rec.id = adoptId; // 필름캔의 지문을 그대로 — 다시 넣을 때 같은 작품임을 알아본다
          } else {
            /**
             * 사본으로 열었다 — 제목까지 같으면 목록에서 어느 쪽이 어느 쪽인지 알 수 없다
             * (실측: 세 편을 사본으로 넣으니 같은 제목이 여섯 줄이 됐다).
             * 「(사본)」을 붙이고, 이미 있으면 번호를 올린다. 대본의 제목은 감독이 언제든 고친다.
             */
            const taken = new Set(db.readProjectList().map((e) => e.title));
            if (taken.has(rec.title)) {
              const base = rec.title;
              let name = `${base} (사본)`;
              let n = 2;
              while (taken.has(name)) name = `${base} (사본 ${n++})`;
              rec.title = name;
              rec.story = { ...rec.story, title: name };
            }
          }
          if (imported.meta.currentSceneId !== undefined) {
            rec.currentSceneId = imported.meta.currentSceneId;
          }
          if (imported.meta.posterSceneId !== undefined) {
            rec.posterSceneId = imported.meta.posterSceneId;
          }
          if (imported.meta.coinsSpent !== undefined) rec.coinsSpent = imported.meta.coinsSpent;
          if (imported.meta.lastExportAt !== undefined) {
            rec.lastExportAt = imported.meta.lastExportAt;
          }
          const blobMap: Record<string, Blob> = {};
          for (const [ref, blob] of imported.chars) {
            const key = db.assetKey(rec.id, "char", ref);
            rec.charAssets[ref] = key;
            blobMap[key] = blob;
          }
          // 전속 배우단 — 필름캔에 실려 왔으면 이 기기의 배우단에 합친다.
          // 같은 배우(이름+ref)가 이미 있으면 출연 편수가 많은 쪽을 남긴다(덮어써서 잃지 않게).
          if (imported.troupe.length > 0) {
            try {
              const mine = await db.listTroupe();
              let added = 0;
              for (const a of imported.troupe) {
                const dupe = mine.find((m) => m.name === a.name && m.ref === a.ref);
                if (dupe) {
                  if (a.appearances > dupe.appearances) {
                    await db.putTroupeActor({ ...dupe, ...a, id: dupe.id });
                  }
                  continue;
                }
                await db.putTroupeActor(a);
                added += 1;
              }
              await get().loadTroupe();
              if (added > 0) {
                get().toast(`필름캔에서 전속 배우 ${added}명을 배우단에 합쳤습니다.`, "ok");
              }
            } catch {
              /* 배우단 합치기에 실패해도 작품 복원은 계속한다 */
            }
          }
          const sceneIds = new Set(rec.story.scenes.map((sc) => sc.id));
          // OK는 generated/에서만 나온다 — NG 그림이 OK로 승격되는 일은 없다
          for (const [sceneId, blob] of imported.generated) {
            if (!sceneIds.has(sceneId)) continue;
            const key = genKey(rec.id, sceneId);
            const cm = imported.cutsMeta?.get(sceneId);
            rec.cuts[sceneId] = {
              status: "ok",
              imageKey: key,
              takeKeys: [],
              source: cm?.source ?? "shoot",
              note: cm?.status === "ok" ? cm.note : undefined,
              customPrompt: cm?.customPrompt,
              reuseBroken: cm?.reuseBroken,
              sourceUrl: cm?.sourceUrl,
              cutscene: cm?.cutscene,
            };
            blobMap[key] = blob;
          }
          // NG 판정 컷 (v0.8.0 필름캔) — 그림과 사유를 그대로 복원
          for (const [sceneId, blob] of imported.ngImages) {
            if (!sceneIds.has(sceneId) || rec.cuts[sceneId]) continue;
            const key = genKey(rec.id, sceneId);
            const cm = imported.cutsMeta?.get(sceneId);
            rec.cuts[sceneId] = {
              status: "ng",
              imageKey: key,
              takeKeys: [],
              note: cm?.note,
              customPrompt: cm?.customPrompt,
              reuseBroken: cm?.reuseBroken,
              source: cm?.source,
            };
            blobMap[key] = blob;
          }
          // 그림 없는 컷의 메타 (NG 사유·프롬프트 수정본·reuse 끊김)
          if (imported.cutsMeta) {
            for (const [sceneId, cm] of imported.cutsMeta) {
              if (!sceneIds.has(sceneId) || rec.cuts[sceneId]) continue;
              if (cm.status === "ng" || cm.customPrompt || cm.reuseBroken || cm.cutscene) {
                rec.cuts[sceneId] = {
                  status: cm.status === "ng" ? "ng" : "wait",
                  takeKeys: [],
                  note: cm.note,
                  customPrompt: cm.customPrompt,
                  reuseBroken: cm.reuseBroken,
                  source: cm.source,
                  cutscene: cm.cutscene,
                };
              }
            }
          }
          // 테이크 복원 (최신이 앞)
          for (const [sceneId, blobs] of imported.takes) {
            if (!sceneIds.has(sceneId)) continue;
            if (!rec.cuts[sceneId]) rec.cuts[sceneId] = { status: "wait", takeKeys: [] };
            for (const blob of blobs) {
              const key = genKey(rec.id, sceneId);
              rec.cuts[sceneId].takeKeys.push(key);
              blobMap[key] = blob;
            }
          }
          // 무빙(영상) 복원 (v0.9.0 필름캔)
          for (const [sceneId, blob] of imported.videos) {
            if (!sceneIds.has(sceneId)) continue;
            if (!rec.cuts[sceneId]) rec.cuts[sceneId] = { status: "wait", takeKeys: [] };
            const key = genKey(rec.id, `${sceneId}:video`);
            rec.cuts[sceneId].videoKey = key;
            blobMap[key] = blob;
          }
          await engine.loadProjectIntoMemory(rec);
          const slots: (SaveSlot | null)[] = [null, null, null];
          for (const [n, save] of imported.saves) {
            const fixed: SaveSlot = { ...save, projectId: rec.id };
            slots[n - 1] = fixed;
            await db.putSaveSlot(n, fixed);
          }
          set({
            blobs: blobMap,
            dirtyAssets: Object.keys(blobMap),
            unsaved: true,
            saveSlots: slots,
          });
          await engine.performSave(true);
          for (const w of imported.warnings) get().toast(w);
          if (!quiet) {
            get().toast(
              `필름캔 「${rec.title}」을 열었습니다. 장면 ${rec.story.scenes.length} · OK ${imported.generated.size}`,
              "ok",
            );
          }
        } else {
          const text = await file.text();
          let json: unknown;
          try {
            json = JSON.parse(text);
          } catch {
            throw new Error("JSON을 읽을 수 없습니다. story.json 또는 .vnproj.zip을 골라주세요.");
          }
          const parsed = parseStory(json);
          if (!parsed.story) {
            throw new Error(`story.json에 문제가 있습니다: ${parsed.errors.join(" / ")}`);
          }
          const rec = makeProject(parsed.story);
          await engine.loadProjectIntoMemory(rec);
          set({ unsaved: true });
          await engine.performSave(true);
          for (const w of parsed.warnings) get().toast(w);
          get().toast(`「${rec.title}」 대본만 불러왔습니다. 이미지는 없음으로 표시됩니다.`, "ok");
        }
      } catch (err) {
        get().toast(err instanceof Error ? err.message : "불러오지 못했습니다.", "ng");
      }
    },
  };
}
