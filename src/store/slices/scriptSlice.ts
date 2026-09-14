/** 대본실 슬라이스 — 컷 편집, 이어 붙이기, 고급 JSON, 캐스팅. */
import * as db from "../../lib/db";
import { cloneImageBlob } from "../../lib/blob";
import { chapterRanges } from "../../lib/chapters";
import { isRecord, parseStory } from "../../lib/parse-story";
import { pushCurrentToTakes, type Scene, type Story } from "../../types";
import type { ActorWork } from "../types";
import type { Get, ScriptSlice, Set } from "../types";
import type { Engine } from "../engine";

/** 새 배우 id — 영문 이름은 그대로, 아니면 actor/actor2… */
function makeCharId(story: Story, name: string): string {
  const trimmed = name.trim();
  const base = trimmed && /^[a-z0-9_-]+$/i.test(trimmed) ? trimmed.toLowerCase() : "actor";
  const ids = new Set(story.characters.map((c) => c.id));
  if (!ids.has(base)) return base;
  let n = 2;
  while (ids.has(`${base}${n}`)) n += 1;
  return `${base}${n}`;
}

interface UndoEntry {
  pid: string;
  label: string;
  story: Story;
  cuts: Record<string, import("../../types").CutRecord>;
  charAssets: Record<string, string>;
  posterSceneId: string | null;
  currentSceneId: string | null;
}

export function createScriptSlice(set: Set, get: Get, engine: Engine): ScriptSlice {
  // 되돌리기 스택 — 저장되지 않는 세션 메모리. 같은 컷 연속 타이핑은 2초 안에서 합쳐진다.
  const undoStack: UndoEntry[] = [];
  let lastKey: string | null = null;
  let lastAt = 0;
  /**
   * 지금 열린 편에 남은 걸음 수 — 화면의 「↩ 되돌리기 (2)」는 이 수다.
   *
   * 스택 전체 길이를 적으면 «가 편»에서 두 번 고치고 «나 편»으로 옮긴 감독에게
   * 「(2)」가 그대로 떠 있다. 눌러 봐야 「되돌릴 대본 변경이 없습니다」이니 거짓말이 된다.
   */
  const depthOf = () => {
    const pid = get().project?.id;
    return pid ? undoStack.filter((e) => e.pid === pid).length : 0;
  };
  const pushUndo = (label: string, coalesceKey?: string) => {
    const p = get().project;
    if (!p) return;
    const now = Date.now();
    if (coalesceKey && coalesceKey === lastKey && now - lastAt < 2000) {
      lastAt = now;
      return;
    }
    lastKey = coalesceKey ?? null;
    lastAt = now;
    undoStack.push({
      pid: p.id,
      label,
      story: p.story,
      cuts: p.cuts,
      charAssets: p.charAssets,
      posterSceneId: p.posterSceneId ?? null,
      currentSceneId: p.currentSceneId ?? null,
    });
    if (undoStack.length > 30) undoStack.shift();
    set({ undoDepth: depthOf() });
  };
  /**
   * 사진을 특정 배우에게 건다 — 파일명은 상관없다.
   * ref가 비어 있으면 파일명을 ref로 삼는다 (필름캔 chars/에 그 이름으로 들어간다).
   */
  const bindPhotoToChar = async (charId: string, file: File): Promise<boolean> => {
    const p0 = get().project;
    if (!p0) return false;
    const pid = p0.id;
    try {
      const blob = await cloneImageBlob(file, "image/jpeg");
      if (!engine.stillOnProject(pid)) return false;
      const p = get().project;
      const ch = p?.story.characters.find((c) => c.id === charId);
      if (!p || !ch) return false;
      /* ref는 사진의 «신원»이다 — charAssets의 열쇠이자 저장 키의 재료다. 그래서 배우마다 유일해야 한다.
         예전에는 ref 없는 배우에게 걸면 «파일명»이 ref가 됐는데, 폰 갤러리·카메라는 사진마다 같은
         이름(image.jpg)을 주는 일이 흔하다 → 두 배우가 같은 ref·같은 키를 갖고 두 번째 사진이 첫 번째를
         덮어썼다(실측: 둘 다 두 번째 그림 — 사용자 보고 「1명만 캐스팅된다」). story.json이 두 배우에
         같은 ref를 적어 온 경우도 같았다. 이제 ref가 없거나 다른 배우와 겹치면 배우 id로 짓는다(권장 형식 id.jpg). */
      const taken = new Set(
        p.story.characters.filter((c) => c.id !== charId && c.ref).map((c) => c.ref as string),
      );
      const given = ch.ref && ch.ref.trim() ? ch.ref.trim() : "";
      let ref = given;
      if (!ref || taken.has(ref)) {
        const m = /\.(jpe?g|png|webp)$/i.exec(file.name);
        const ext = m ? m[1].toLowerCase() : "jpg";
        ref = `${charId}.${ext}`;
        for (let n = 2; taken.has(ref); n += 1) ref = `${charId}-${n}.${ext}`;
        if (given) {
          const other = p.story.characters.find((c) => c.id !== charId && c.ref === given);
          get().toast(
            `「${ch.name}」의 ref(${given})가 「${other?.name ?? "다른 배우"}」와 같아 ${ref}로 갈라 걸었습니다 — 안 그러면 사진이 서로 덮어씁니다.`,
          );
        }
      }
      const key = db.assetKey(pid, "char", ref);
      set((s) => ({ blobs: { ...s.blobs, [key]: blob } }));
      engine.patchProject((cur) => ({
        ...cur,
        story:
          ch.ref === ref
            ? cur.story
            : {
                ...cur.story,
                characters: cur.story.characters.map((c) =>
                  c.id === charId ? { ...c, ref } : c,
                ),
              },
        charAssets: { ...cur.charAssets, [ref]: key },
      }));
      engine.markDirty([key]);
      return true;
    } catch (err) {
      get().toast(
        `${file.name}: ${err instanceof Error ? err.message : "읽지 못했습니다."}`,
        "ng",
      );
      return false;
    }
  };

  return {
    undoDepth: 0,
    troupe: [],
    troupeWorks: {},

    /**
     * 배우별 출연 작품·장 — 저장된 작품 전체를 한 번 훑는다(배우단을 열 때만).
     * 배우단은 이름으로 이어진다(사진은 배우단이 따로 들고 있다) — 그래서 이름으로 맞춘다.
     */
    loadTroupeWorks: async () => {
      try {
        // 저장된 기록만 훑으면 «방금 반영한 이번 화»가 빠진다(저장은 잠시 뒤에 흘러간다).
        // 지금 열린 편은 메모리의 것으로 덮어 센다 — 화면에 보이는 것과 셈이 어긋나지 않게.
        const cur = get().project;
        const stored = await db.listProjectRecords();
        const recs = cur
          ? stored.some((r) => r.id === cur.id)
            ? stored.map((r) => (r.id === cur.id ? cur : r))
            : [...stored, cur]
          : stored;
        const works: Record<string, ActorWork[]> = {};
        for (const rec of recs) {
          const ranges = chapterRanges(rec.story.scenes);
          for (const ch of rec.story.characters) {
            const scenes = rec.story.scenes.filter((sc) => sc.chars?.includes(ch.id));
            if (scenes.length === 0) continue;
            const names =
              ranges.length >= 2
                ? ranges.filter((r) => scenes.some((sc) => r.ids.includes(sc.id))).map((r) => r.title)
                : [];
            const list = works[ch.name] ?? [];
            list.push({ id: rec.id, title: rec.title, chapters: names, cuts: scenes.length });
            works[ch.name] = list;
          }
        }
        set({ troupeWorks: works });
      } catch {
        /* 선반의 «어디에 나왔나»는 장식이 아니지만, 실패해도 배우단은 쓸 수 있다 */
      }
    },

    loadTroupe: async () => {
      try {
        set({ troupe: await db.listTroupe() });
      } catch {
        /* 배우단 목록은 장식이 아니지만, 실패해도 작업은 계속된다 */
      }
    },

    /** 이 작품의 배우를 배우단에 올린다 — 사진은 배우단이 직접 들고 있는다(프로젝트와 독립) */
    saveToTroupe: async (charId) => {
      const s0 = get();
      const p = s0.project;
      const ch = p?.story.characters.find((c) => c.id === charId);
      if (!p || !ch) return;
      if (!ch.ref || !p.charAssets[ch.ref]) {
        get().toast("먼저 이 배우에게 캐스팅 사진을 걸어주세요 — 얼굴이 배우단의 핵심입니다.");
        return;
      }
      const blob = s0.blobs[p.charAssets[ch.ref]];
      if (!blob) {
        get().toast("사진을 읽지 못했습니다. 다시 걸어주세요.", "ng");
        return;
      }
      const existing = s0.troupe.find((a) => a.name === ch.name && a.ref === ch.ref);
      const now = Date.now();
      const actor = {
        id: existing?.id ?? `actor_${now.toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
        name: ch.name,
        look: ch.look,
        ref: ch.ref,
        photo: blob,
        appearances: existing?.appearances ?? 1,
        createdAt: existing?.createdAt ?? now,
        updatedAt: now,
      };
      await db.putTroupeActor(actor);
      await get().loadTroupe();
      get().toast(
        existing
          ? `「${ch.name}」 배우단 정보를 갱신했습니다.`
          : `「${ch.name}」을 배우단에 올렸습니다 — 다음 작품에 데려갈 수 있어요.`,
        "ok",
      );
    },

    /** 배우단에서 이 작품으로 — 사진과 외모 메모가 함께 온다 */
    castFromTroupe: async (actorId) => {
      const s0 = get();
      const p = s0.project;
      if (!p) return;
      const actor = await db.getTroupeActor(actorId);
      if (!actor) {
        get().toast("그 배우를 배우단에서 찾지 못했습니다.", "ng");
        await get().loadTroupe();
        return;
      }
      const pid = p.id;
      // 이름이 같은 배우가 이미 있으면 새로 만들지 않고 사진만 갱신한다
      const dupe = p.story.characters.find((c) => c.name === actor.name);
      const charId = dupe?.id ?? makeCharId(p.story, actor.name);
      const key = db.assetKey(pid, "char", actor.ref);
      set((st) => ({ blobs: { ...st.blobs, [key]: actor.photo } }));
      pushUndo(`배우 ${actor.name} 데려오기`);
      engine.patchProject((cur) => ({
        ...cur,
        story: {
          ...cur.story,
          characters: dupe
            ? cur.story.characters.map((c) =>
                c.id === charId ? { ...c, ref: actor.ref, look: actor.look ?? c.look } : c,
              )
            : [
                ...cur.story.characters,
                { id: charId, name: actor.name, ref: actor.ref, look: actor.look },
              ],
        },
        charAssets: { ...cur.charAssets, [actor.ref]: key },
      }));
      engine.markDirty([key]);
      engine.scheduleAutosave();
      // 출연 횟수는 «데려온 작품 수» — 같은 작품에 두 번 데려와도 한 번만 센다
      if (!dupe) {
        await db.putTroupeActor({
          ...actor,
          appearances: actor.appearances + 1,
          updatedAt: Date.now(),
        });
        await get().loadTroupe();
      }
      get().toast(
        dupe
          ? `「${actor.name}」의 캐스팅 사진을 배우단 것으로 맞췄습니다.`
          : `「${actor.name}」을 이 작품에 데려왔습니다. 컷의 등장 배우로 켜주세요.`,
        "ok",
      );
    },

    /** 배우단 선반 위에서 바로 얼굴을 갈아끼운다.
     *  더 잘 나온 사진을 나중에 구하는 일이 흔한데, 그때마다 작품을 열어 다시 ⭐를 누르는 건
     *  «선반»이라는 은유를 배신한다. 지금 이 작품에 같은 배우가 서 있으면 함께 맞춰준다. */
    replaceTroupePhoto: async (actorId, file) => {
      const actor = await db.getTroupeActor(actorId);
      if (!actor) {
        get().toast("그 배우를 배우단에서 찾지 못했습니다.", "ng");
        await get().loadTroupe();
        return;
      }
      if (!file.type.startsWith("image/")) {
        get().toast("사진 파일(JPG·PNG)만 걸 수 있습니다.", "ng");
        return;
      }
      const photo = file.slice(0, file.size, file.type); // File → 순수 Blob (파일 핸들 붙잡지 않게)
      await db.putTroupeActor({ ...actor, photo, updatedAt: Date.now() });
      await get().loadTroupe();

      // 이 작품에도 같은 이름의 배우가 서 있으면 같은 얼굴로 맞춘다 — 두 곳이 어긋나면 혼란스럽다
      const p = get().project;
      const here = p?.story.characters.find((c) => c.name === actor.name);
      if (p && here) {
        const ref = here.ref ?? actor.ref;
        const key = db.assetKey(p.id, "char", ref);
        set((st) => ({ blobs: { ...st.blobs, [key]: photo } }));
        engine.patchProject((cur) => ({
          ...cur,
          story: {
            ...cur.story,
            characters: cur.story.characters.map((c) => (c.id === here.id ? { ...c, ref } : c)),
          },
          charAssets: { ...cur.charAssets, [ref]: key },
        }));
        engine.markDirty([key]);
        engine.scheduleAutosave();
      }
      get().toast(
        here
          ? `「${actor.name}」의 얼굴을 바꿨습니다 — 이 작품의 캐스팅 사진도 함께 맞췄어요.`
          : `「${actor.name}」의 얼굴을 바꿨습니다. 다음에 데려올 때 이 사진이 따라옵니다.`,
        "ok",
      );
    },

    editTroupeProfile: async (actorId) => {
      const actor = await db.getTroupeActor(actorId);
      if (!actor) {
        get().toast("그 배우를 배우단에서 찾지 못했습니다.", "ng");
        await get().loadTroupe();
        return;
      }
      const text = await get().promptText({
        title: `배우단 「${actor.name}」 프로필`,
        body: "첫 줄 = 이름, 둘째 줄 = 외모 메모(영어, 프롬프트에 실립니다).",
        initial: actor.look ? `${actor.name}\n${actor.look}` : actor.name,
        multiline: true,
        okLabel: "반영",
      });
      if (text === null) return;
      const [nameLine, ...rest] = text.split("\n");
      const name = nameLine.trim();
      if (!name) return;
      const look = rest.join(" ").trim() || undefined;
      await db.putTroupeActor({ ...actor, name, look, updatedAt: Date.now() });
      await get().loadTroupe();
      get().toast(`배우단 프로필을 고쳤습니다 — 「${name}」.`, "ok");
    },

    removeFromTroupe: async (actorId) => {
      const actor = get().troupe.find((a) => a.id === actorId);
      const ok = await get().confirm({
        title: `배우단에서 빼기`,
        body: `「${actor?.name ?? actorId}」을 배우단에서 지웁니다. 지금 작품 안의 배우와 사진은 그대로 남습니다.`,
        okLabel: "배우단에서 빼기",
        danger: true,
      });
      if (!ok) return;
      await db.deleteTroupeActor(actorId);
      await get().loadTroupe();
      get().toast("배우단에서 뺐습니다.");
    },

    undoScript: () => {
      const p = get().project;
      if (!p) return;
      const st = get();
      if (st.batch?.running || Object.values(st.shooting).some(Boolean)) {
        get().toast("촬영이 도는 중에는 대본을 되돌릴 수 없습니다 — 끝나면 다시 눌러주세요.");
        return;
      }
      /* 이 편의 «마지막 걸음»만 꺼낸다 — 다른 편의 걸음은 남긴다.
         예전에는 위에 쌓인 남의 걸음을 버리며 내려왔다: 가↔나를 오가며 일하면
         돌아온 편의 되돌리기가 조용히 사라졌다. */
      let at = undoStack.length - 1;
      while (at >= 0 && undoStack[at].pid !== p.id) at -= 1;
      const entry = at >= 0 ? undoStack.splice(at, 1)[0] : undefined;
      set({ undoDepth: depthOf() });
      if (!entry) {
        get().toast("되돌릴 대본 변경이 없습니다.");
        return;
      }
      lastKey = null; // 되돌린 직후의 타이핑은 새 변경으로 취급
      engine.patchProject((cur) => {
        // 병합 복원 — 대본(story)은 엔트리로 완전 복원하되, 컷 기록은 「현재」가 우선.
        // 이유: 스냅샷 뒤에 촬영/판정이 있었으면 그 필름·판정을 undo가 지우면 안 된다(과금 낭비).
        // 엔트리에만 있는 키(방금 삭제한 컷)는 복원되고, 복원된 대본에 없는 컷 키는 떨어져 나간다.
        const sceneIds = new Set(entry.story.scenes.map((sc) => sc.id));
        const cuts: typeof cur.cuts = {};
        for (const [k, v] of Object.entries(entry.cuts)) if (sceneIds.has(k)) cuts[k] = v;
        for (const [k, v] of Object.entries(cur.cuts)) if (sceneIds.has(k)) cuts[k] = v;
        const pick = (now: string | null, then: string | null) =>
          now && sceneIds.has(now) ? now : then && sceneIds.has(then) ? then : null;
        return {
          ...cur,
          story: entry.story,
          cuts,
          charAssets: { ...entry.charAssets, ...cur.charAssets },
          posterSceneId: pick(cur.posterSceneId ?? null, entry.posterSceneId),
          currentSceneId: pick(cur.currentSceneId ?? null, entry.currentSceneId),
        };
      });
      engine.scheduleAutosave();
      get().toast(`되돌렸습니다 — ${entry.label}`, "ok");
    },

    recountUndo: () => set({ undoDepth: depthOf() }),

    updateScene: (sceneId, patch) => {
      pushUndo(`컷 ${sceneId} 수정`, `upd:${sceneId}`);
      engine.patchProject((p) => ({
        ...p,
        story: {
          ...p.story,
          scenes: p.story.scenes.map((sc) => (sc.id === sceneId ? { ...sc, ...patch } : sc)),
        },
      }));
      engine.scheduleAutosave();
    },

    updateCharacter: (charId, patch) => {
      pushUndo("배우 프로필 수정", `char:${charId}`);
      engine.patchProject((p) => ({
        ...p,
        story: {
          ...p.story,
          characters: p.story.characters.map((c) =>
            c.id === charId
              ? // castCrop: null = «기본으로 되돌리기» (필드를 지운다)
                { ...c, ...patch, castCrop: patch.castCrop === null ? undefined : (patch.castCrop ?? c.castCrop) }
              : c,
          ),
        },
      }));
      engine.scheduleAutosave();
    },

    removeCharacter: async (charId) => {
      const p = get().project;
      const ch = p?.story.characters.find((c) => c.id === charId);
      if (!p || !ch) return;
      const ok = await get().confirm({
        title: `배우 「${ch.name}」 하차`,
        body:
          "명단에서 빠지고, 컷의 등장 표시와 화자(→내레이션)에서도 빠집니다.\n" +
          "캐스팅 사진 파일은 저장소 청소 전까지 남아 있어 되돌리기(↩)로 복귀할 수 있어요.",
        okLabel: "하차",
        danger: true,
      });
      if (!ok) return;
      pushUndo(`배우 ${ch.name} 하차`);
      engine.patchProject((cur) => ({
        ...cur,
        story: {
          ...cur.story,
          characters: cur.story.characters.filter((c) => c.id !== charId),
          scenes: cur.story.scenes.map((sc) => {
            const chars = sc.chars?.filter((cid) => cid !== charId);
            const speaker = sc.speaker === charId ? "narration" : sc.speaker;
            if ((sc.chars?.length ?? 0) === (chars?.length ?? 0) && speaker === sc.speaker)
              return sc;
            return { ...sc, chars: chars && chars.length > 0 ? chars : undefined, speaker };
          }),
        },
      }));
      get().toast(`「${ch.name}」이 하차했습니다.`);
      engine.scheduleAutosave();
    },

    addSceneAfter: (sceneId) => {
      pushUndo("컷 추가");
      engine.patchProject((p) => {
        const idx = p.story.scenes.findIndex((sc) => sc.id === sceneId);
        if (idx < 0) return p;
        const prev = p.story.scenes[idx];
        let n = p.story.scenes.length + 1;
        let newId = `s${String(n).padStart(2, "0")}`;
        const ids = new Set(p.story.scenes.map((sc) => sc.id));
        while (ids.has(newId)) {
          n += 1;
          newId = `s${String(n).padStart(2, "0")}`;
        }
        const fresh: Scene = {
          id: newId,
          shot: prev.shot ?? "full",
          chars: prev.chars ? [...prev.chars] : undefined,
          text: "",
          speaker: "narration",
          next: prev.choices ? undefined : prev.next,
        };
        const scenes = [...p.story.scenes];
        scenes.splice(idx + 1, 0, fresh);
        if (!prev.choices) {
          scenes[idx] = { ...prev, next: newId };
        }
        return { ...p, story: { ...p.story, scenes } };
      });
      engine.scheduleAutosave();
    },

    /** 빈 컷을 뒤에 만들고 id 반환 — 연결은 호출자(연결 셀렉트)가 정한다. */
    spawnSceneAfter: (sceneId) => {
      const p = get().project;
      if (!p) return null;
      const idx = p.story.scenes.findIndex((sc) => sc.id === sceneId);
      if (idx < 0) return null;
      const ids = new Set(p.story.scenes.map((sc) => sc.id));
      let n = p.story.scenes.length + 1;
      let newId = `s${String(n).padStart(2, "0")}`;
      while (ids.has(newId)) {
        n += 1;
        newId = `s${String(n).padStart(2, "0")}`;
      }
      const prev = p.story.scenes[idx];
      pushUndo("새 컷 만들기");
      engine.patchProject((cur) => {
        const scenes = [...cur.story.scenes];
        scenes.splice(idx + 1, 0, {
          id: newId,
          shot: prev.shot ?? "full",
          chars: prev.chars ? [...prev.chars] : undefined,
          sfx: prev.sfx,
          text: "",
          speaker: "narration",
        });
        return { ...cur, story: { ...cur.story, scenes } };
      });
      engine.scheduleAutosave();
      return newId;
    },

    /**
     * 연속 동작 펼치기 — 이 컷을 A로 두고 B·C를 뒤에 만든다.
     *
     * 액션은 한 컷으로 안 된다. 「팔을 들었다 → 휘둘렀다 → 멈췄다」처럼 같은 자리에서
     * 자세만 바뀌는 컷이 이어져야 움직임으로 읽힌다. 손으로 짜면 매번 같은 일을 한다:
     * 같은 배경(reuse), 같은 옷·소품, 카메라 고정(hold), pose만 교체. 그걸 앱이 만든다.
     *
     * 배경은 A를 reuse — 새 배경을 뽑지 않으니 컷이 흔들리지 않고 크레딧도 아낀다.
     */
    expandSequence: (sceneId) => {
      const p = get().project;
      if (!p) return;
      const idx = p.story.scenes.findIndex((sc) => sc.id === sceneId);
      if (idx < 0) return;
      const base = p.story.scenes[idx];
      const ids = new Set(p.story.scenes.map((sc) => sc.id));
      const newIds: string[] = [];
      let n = p.story.scenes.length + 1;
      while (newIds.length < 2) {
        const id = `s${String(n).padStart(2, "0")}`;
        if (!ids.has(id)) {
          ids.add(id);
          newIds.push(id);
        }
        n += 1;
      }
      // 배경은 «문구»를 물려준다. bg:"reuse:…"를 주면 그림을 그대로 복사해버려서
      // 자세가 바뀌지 않는다 — 연속 동작은 같은 배경에서 «다시 찍는» 것이다.
      let bgText = base.bg_prompt ?? "";
      let hop: Scene | undefined = base;
      for (let i = 0; i < 8 && hop && !bgText; i++) {
        const b: string | undefined = hop.bg;
        const t: string | null = b && b.startsWith("reuse:") ? b.slice("reuse:".length).trim() : null;
        hop = t ? p.story.scenes.find((sc) => sc.id === t) : undefined;
        bgText = hop?.bg_prompt ?? "";
      }
      pushUndo("연속 동작 펼치기");
      engine.patchProject((cur) => {
        const scenes = [...cur.story.scenes];
        const at = scenes.findIndex((sc) => sc.id === sceneId);
        if (at < 0) return cur;
        const a = scenes[at];
        // A가 가리키던 곳(또는 갈림길)은 마지막 컷이 물려받는다 — 동작이 끝난 뒤에 갈라져야
        // 자연스럽고, next와 choices를 한 컷에 같이 두는 금기도 피한다.
        const tail = a.next;
        const forks = a.choices;
        const made: Scene[] = newIds.map((id) => ({
          id,
          shot: a.shot ?? "action",
          chars: a.chars ? [...a.chars] : undefined,
          bg_prompt: bgText || undefined,
          hold: true,
          sfx: a.sfx,
          text: "",
          speaker: "narration",
        }));
        scenes[at] = { ...a, next: newIds[0], choices: undefined };
        made[0] = { ...made[0], next: newIds[1] };
        made[1] = forks?.length
          ? { ...made[1], choices: forks.map((c) => ({ ...c })) }
          : { ...made[1], next: tail };
        scenes.splice(at + 1, 0, ...made);
        return { ...cur, story: { ...cur.story, scenes } };
      });
      engine.scheduleAutosave();
      get().toast(
        `${sceneId} 뒤에 연속 동작 두 컷(${newIds.join(", ")})을 펼쳤습니다 — 같은 배경·같은 앵글(🔒 고정)로 맞춰 뒀으니 «자세»만 채우세요.` +
          (base.choices?.length ? ` 갈림길은 마지막 컷(${newIds[1]})으로 옮겼습니다.` : ""),
        "ok",
      );
    },

    /** 표시 순서만 이동 — 연결(next/choices)은 그대로라 이야기가 깨지지 않는다. */
    moveScene: (sceneId, dir) => {
      pushUndo("순서 이동", "move");
      engine.patchProject((p) => {
        const idx = p.story.scenes.findIndex((sc) => sc.id === sceneId);
        const to = idx + dir;
        if (idx < 0 || to < 0 || to >= p.story.scenes.length) return p;
        const scenes = [...p.story.scenes];
        [scenes[idx], scenes[to]] = [scenes[to], scenes[idx]];
        return { ...p, story: { ...p.story, scenes } };
      });
      engine.scheduleAutosave();
    },

    /**
     * 장을 통째로 앞뒤로 옮긴다 — 연재에서 「3장을 4장 뒤로 미루자」는 흔한 판단인데,
     * 컷 단위 ▲▼로는 스무 번을 눌러야 했다. 옮긴 뒤 「⏎ 새 장에서 시작」 표시를
     * 다시 매겨 첫 장에는 표시가 남지 않게 한다(첫 장은 표시 없이도 장이다).
     */
    moveChapter: (firstSceneId, dir) => {
      const p = get().project;
      if (!p) return;
      const ranges = chapterRanges(p.story.scenes);
      const at = ranges.findIndex((c) => c.firstId === firstSceneId);
      const to = at + dir;
      if (at < 0 || to < 0 || to >= ranges.length) {
        get().toast(
          at < 0 ? "옮길 장을 찾지 못했습니다." : "여기가 끝입니다 — 더 옮길 자리가 없어요.",
        );
        return;
      }
      const moved = ranges[at];
      const other = ranges[to];
      // 되돌리기 합치기 키는 «그 장»으로 — 2초 안에 같은 장을 두 칸 밀면 한 걸음으로 묶이지만,
      // 다른 장을 옮긴 것까지 한꺼번에 되돌아가면 «무엇이 되돌아갔는지» 알 수 없다
      pushUndo(`${moved.title} 옮기기`, `chap:${firstSceneId}`);
      engine.patchProject((cur) => {
        const blocks = chapterRanges(cur.story.scenes).map((c) =>
          cur.story.scenes.slice(c.start, c.end),
        );
        if (at >= blocks.length || to >= blocks.length) return cur;
        [blocks[at], blocks[to]] = [blocks[to], blocks[at]];
        const scenes = blocks.flatMap((block, j) =>
          block.map((sc, k) => {
            if (k !== 0) return sc;
            const w = { ...(sc.webtoon ?? {}) };
            if (j === 0) delete w.pageBreak;
            else w.pageBreak = true;
            return { ...sc, webtoon: Object.keys(w).length ? w : undefined };
          }),
        );
        return { ...cur, story: { ...cur.story, scenes } };
      });
      engine.scheduleAutosave();
      get().toast(
        `${moved.title}(${moved.ids.length}컷)을 ${other.title} ${dir < 0 ? "앞" : "뒤"}으로 옮겼습니다 — 그림·대사는 그대로고 순서만 바뀌었어요.`,
        "ok",
      );
    },

    deleteScene: async (sceneId) => {
      const p = get().project;
      const scene = p?.story.scenes.find((sc) => sc.id === sceneId);
      if (!p || !scene) return;
      if (p.story.scenes.length <= 1) {
        get().toast("마지막 한 컷은 지울 수 없습니다.");
        return;
      }
      const preview = (scene.text ?? "").slice(0, 30);
      const ok = await get().confirm({
        title: `컷 ${sceneId} 지우기`,
        body:
          (preview ? `「${preview}${(scene.text ?? "").length > 30 ? "…" : ""}」\n` : "") +
          "이 컷을 대본에서 뺍니다. 그림과 테이크는 저장소에 남지만 목록에서 사라지고,\n" +
          "이 컷을 가리키던 연결(next/선택지)은 조감독 리포트에 경고로 표시됩니다.",
        okLabel: "지우기",
        danger: true,
      });
      if (!ok) return;
      pushUndo(`컷 ${sceneId} 삭제`);
      engine.patchProject((cur) => {
        const cuts = { ...cur.cuts };
        delete cuts[sceneId];
        return {
          ...cur,
          story: { ...cur.story, scenes: cur.story.scenes.filter((sc) => sc.id !== sceneId) },
          cuts,
          posterSceneId: cur.posterSceneId === sceneId ? null : cur.posterSceneId,
          currentSceneId: cur.currentSceneId === sceneId ? null : cur.currentSceneId,
        };
      });
      get().toast(`${sceneId} 컷을 뺐습니다.`);
      engine.scheduleAutosave();
    },

    setStyle: (style) => {
      engine.patchProject((p) => ({ ...p, story: { ...p.story, style } }));
      engine.scheduleAutosave();
    },

    setNote: (note) => {
      engine.patchProject((p) => ({
        ...p,
        story: { ...p.story, note: note.trim() ? note : undefined },
      }));
      engine.scheduleAutosave();
    },

    /** 표지 부제 — 비우면 인쇄본 표지에 「N컷」이 들어간다 */
    setCoverSubtitle: (text) => {
      engine.patchProject((p) => ({
        ...p,
        story: { ...p.story, coverSubtitle: text.trim() ? text.trim() : undefined },
      }));
      engine.scheduleAutosave();
    },

    /** 표지 아래 한 줄 — 사람 이름이 들어갈 수 있어 앱이 자동으로 채우지 않는다 */
    setCoverByline: (text) => {
      engine.patchProject((p) => ({
        ...p,
        story: { ...p.story, coverByline: text.trim() ? text.trim() : undefined },
      }));
      engine.scheduleAutosave();
    },

    setTitle: (title) => {
      engine.patchProject((p) => ({
        ...p,
        title: title.trim() || p.title,
        story: { ...p.story, title: title.trim() || p.story.title },
      }));
      engine.scheduleAutosave();
    },

    /** 「스토리 이어서 만들기」 — 기존 장면·캐릭터·이미지는 유지, 새 장면만 append. */
    appendStoryJson: async () => {
      const text = await get().promptText({
        title: "스토리 이어서 만들기",
        body:
          "이어질 story JSON을 붙여넣어 주세요. 기존 장면·배우·생성 이미지는 그대로 두고 새 장면만 뒤에 붙입니다. " +
          "같은 id의 장면은 플레이스홀더일 때만 교체합니다.",
        placeholder: '{ "scenes": [ … ] } 또는 story.json 전체',
        okLabel: "이어 붙이기",
        multiline: true,
      });
      if (text === null) return;
      let json: unknown;
      try {
        json = JSON.parse(text);
      } catch {
        get().toast("JSON을 읽을 수 없습니다.", "ng");
        return;
      }
      const raw = isRecord(json) ? json : {};
      const fragment = {
        title: "무제",
        style: "-",
        characters: raw.characters ?? [],
        scenes: raw.scenes ?? [],
      };
      const parsed = parseStory(fragment);
      if (!parsed.story || parsed.story.scenes.length === 0) {
        get().toast(
          `이어 붙일 장면을 찾지 못했습니다. ${parsed.errors.join(" / ")}`.trim(),
          "ng",
        );
        return;
      }
      const incoming = parsed.story;
      let appended = 0;
      let replaced = 0;
      let skipped = 0;
      pushUndo("스토리 이어 붙이기");
      engine.patchProject((p) => {
        const scenes = [...p.story.scenes];
        const cuts = { ...p.cuts };
        const byId = new Map(scenes.map((sc, i) => [sc.id, i] as const));
        const newOnes: Scene[] = [];
        for (const sc of incoming.scenes) {
          const idx = byId.get(sc.id);
          if (idx === undefined) {
            newOnes.push(sc);
            appended += 1;
          } else if (scenes[idx].placeholder) {
            scenes[idx] = sc; // 플레이스홀더만 교체 가능
            // 자동 생성된 단색 이미지가 걸려 있으면 대기로 되돌려 촬영 큐에 들어가게 한다
            const old = cuts[sc.id];
            if (old && old.source === "placeholder") {
              cuts[sc.id] = {
                ...old,
                status: "wait",
                imageKey: undefined,
                takeKeys: pushCurrentToTakes(old),
                source: undefined,
                note: undefined,
              };
            }
            replaced += 1;
          } else {
            skipped += 1;
          }
        }
        if (newOnes.length > 0) {
          // 마지막 장면(다음/선택지 없는)의 next를 첫 새 장면으로 자동 연결
          for (let i = scenes.length - 1; i >= 0; i--) {
            const sc = scenes[i];
            if (!sc.next && !sc.choices) {
              scenes[i] = { ...sc, next: newOnes[0].id };
              break;
            }
          }
          scenes.push(...newOnes);
        }
        const knownChars = new Set(p.story.characters.map((c) => c.id));
        const characters = [
          ...p.story.characters,
          ...incoming.characters.filter((c) => !knownChars.has(c.id)),
        ];
        return { ...p, story: { ...p.story, characters, scenes }, cuts };
      });
      for (const w of parsed.warnings) get().toast(w);
      get().toast(
        `이어 붙였습니다 — 새 장면 ${appended}${replaced ? ` · 플레이스홀더 교체 ${replaced}` : ""}${skipped ? ` · 같은 id라 건너뜀 ${skipped}` : ""}`,
        "ok",
      );
      engine.scheduleAutosave();
    },

    /**
     * 이 장 다시 쓰기 — 같은 id로 돌려받은 대본을 «덮어쓴다».
     *
     * 「이어 붙이기」는 같은 id를 건너뛴다(있는 컷을 지키는 게 기본이다). 하지만 연재에서는
     * 「3장 대사를 다시 써보자」가 흔하고, 그때 필요한 것은 «그림은 두고 대본만 갈아끼우기»다.
     * 그림·판정·테이크는 컷 기록(cuts)에 따로 있으므로 장면만 바꾸면 그대로 남는다.
     * 감독이 조판실에서 손댄 말풍선(webtoon)은 새 대본이 따로 주지 않으면 지킨다.
     */
    rewriteScenesJson: async () => {
      const text = await get().promptText({
        title: "다시 쓴 대본 넣기",
        body:
          "LLM이 돌려준 JSON을 붙여넣어 주세요. 같은 id의 컷을 «덮어씁니다» — 찍어둔 그림·OK/NG 판정·테이크는 그대로 남고, 조판실에서 손댄 말풍선도 새 대본이 주지 않으면 지킵니다.\n" +
          "대본에 없는 id는 넣지 않습니다(새 컷을 만들려면 「스토리 이어서 만들기」를 쓰세요). ↩ 되돌리기로 한 번에 취소할 수 있어요.",
        placeholder: '{ "scenes": [ … ] }',
        okLabel: "덮어쓰기",
        multiline: true,
      });
      if (text === null) return;
      let json: unknown;
      try {
        json = JSON.parse(text);
      } catch {
        get().toast("JSON을 읽을 수 없습니다.", "ng");
        return;
      }
      const raw = isRecord(json) ? json : {};
      const parsed = parseStory({
        title: "무제",
        style: "-",
        characters: raw.characters ?? [],
        scenes: raw.scenes ?? [],
      });
      if (!parsed.story || parsed.story.scenes.length === 0) {
        get().toast(
          `덮어쓸 장면을 찾지 못했습니다. ${parsed.errors.join(" / ")}`.trim(),
          "ng",
        );
        return;
      }
      const incoming = new Map(parsed.story.scenes.map((sc) => [sc.id, sc] as const));
      let rewritten = 0;
      let unknown = 0;
      for (const id of incoming.keys()) {
        if (!get().project?.story.scenes.some((sc) => sc.id === id)) unknown += 1;
      }
      pushUndo("장 다시 쓰기");
      engine.patchProject((p) => ({
        ...p,
        story: {
          ...p.story,
          scenes: p.story.scenes.map((sc) => {
            const next = incoming.get(sc.id);
            if (!next) return sc;
            rewritten += 1;
            return { ...next, webtoon: next.webtoon ?? sc.webtoon };
          }),
        },
      }));
      engine.scheduleAutosave();
      if (rewritten === 0) {
        get().toast(
          "대본에 있는 id가 하나도 없어 아무것도 바꾸지 않았습니다 — id를 그대로 돌려받아야 합니다.",
          "ng",
        );
        return;
      }
      get().toast(
        `${rewritten}컷을 다시 쓴 대본으로 덮어썼습니다 — 그림·판정은 그대로예요.` +
          (unknown > 0 ? ` (대본에 없는 id ${unknown}개는 넣지 않았습니다)` : ""),
        "ok",
      );
    },

    /** 고급 — story.json 전체 교체. 같은 id 컷의 이미지는 유지. */
    replaceStoryJson: (text) => {
      let json: unknown;
      try {
        json = JSON.parse(text);
      } catch {
        get().toast("JSON을 읽을 수 없습니다.", "ng");
        return false;
      }
      const parsed = parseStory(json);
      if (!parsed.story) {
        get().toast(`story.json에 문제가 있습니다: ${parsed.errors.join(" / ")}`, "ng");
        return false;
      }
      const story = parsed.story;
      pushUndo("JSON 전체 교체");
      engine.patchProject((p) => {
        const cuts: typeof p.cuts = {};
        for (const sc of story.scenes) {
          if (p.cuts[sc.id]) cuts[sc.id] = p.cuts[sc.id];
        }
        return { ...p, title: story.title, story, cuts };
      });
      for (const w of parsed.warnings) get().toast(w);
      get().toast("대본 전체를 반영했습니다.", "ok");
      engine.scheduleAutosave();
      return true;
    },

    /**
     * 배우 사진 업로드. ref 파일명이 맞으면 바로 걸고,
     * 안 맞아도 막다른 길로 두지 않는다 — 폰 갤러리 파일명(1000008977.jpg 등) 대응:
     *  - 배우가 없으면: 사진으로 새 배우를 만든다
     *  - 얼굴 없는 배우가 있으면: 누구의 사진인지 묻고, «새 배우 만들기»도 함께 고를 수 있다
     *  - 모두 얼굴이 있으면: 새 배우를 만들지 묻는다
     * 예전에는 배우가 하나라도 있으면 새 배우를 만들 길이 없어서, 폰에서 첫 사진으로 배우를 만든 뒤
     * 둘째 사진은 「파일명이 맞는 배우가 없습니다」로 끝났다(사용자 보고 「1명만 캐스팅된다」의 실제 원인).
     */
    uploadCharFiles: async (files) => {
      const p = get().project;
      if (!p || files.length === 0) return;
      let bound = 0;

      /** 사진 한 장으로 새 배우를 세운다 — ref는 파일명이 아니라 배우 id로 짓는다(폰은 사진마다 같은 이름을 준다) */
      const createActorFromPhoto = async (file: File, presetName?: string): Promise<boolean> => {
        const cur = get().project;
        if (!cur) return false;
        const name =
          presetName ??
          (await get().promptText({
            title: "배우 이름",
            body: `이 사진(${file.name})의 배우 이름을 정해주세요. 컷의 화자로 고를 수 있게 됩니다.`,
            placeholder: "하나",
            okLabel: "캐스팅",
          }));
        if (name === null) return false;
        const id = makeCharId(cur.story, name);
        const display = name.trim() || id;
        const m = /\.(jpe?g|png|webp)$/i.exec(file.name);
        const ref = `${id}.${m ? m[1].toLowerCase() : "jpg"}`;
        engine.patchProject((pp) => ({
          ...pp,
          story: { ...pp.story, characters: [...pp.story.characters, { id, name: display, ref }] },
        }));
        if (!(await bindPhotoToChar(id, file))) return false;
        get().toast(`「${display}」를 캐스팅했습니다. 컷의 화자로 고를 수 있어요.`, "ok");
        return true;
      };

      const unmatched: File[] = [];
      for (const file of files) {
        const ch = p.story.characters.find(
          (c) => c.ref && c.ref.toLowerCase() === file.name.toLowerCase(),
        );
        if (ch) {
          if (await bindPhotoToChar(ch.id, file)) bound += 1;
        } else {
          unmatched.push(file);
        }
      }
      for (const file of unmatched) {
        const cur = get().project;
        if (!cur) break;
        const chars = cur.story.characters;
        const photoless = chars.filter((c) => !(c.ref && cur.charAssets[c.ref]));

        if (photoless.length === 0) {
          // 배우가 없거나 모두 얼굴이 있다 — 이 사진은 새 배우다(예전에는 배우가 있으면 여기서 막혔다)
          const ok = await get().confirm({
            title: "새 배우 캐스팅",
            body:
              chars.length === 0
                ? `아직 배우가 없습니다.\n이 사진(${file.name})으로 새 배우를 만들까요?`
                : `파일명(${file.name})이 어느 배우의 ref와도 다르고, 배우 ${chars.length}명은 모두 얼굴이 있습니다.\n이 사진으로 새 배우를 만들까요? (기존 배우의 사진을 바꾸려면 그 배우 카드의 「사진 바꾸기」)`,
            okLabel: "새 배우 만들기",
          });
          if (!ok) continue;
          if (await createActorFromPhoto(file)) bound += 1;
          continue;
        }

        /* 얼굴 없는 배우가 있다 — 누구의 사진인지 번호나 이름으로 묻고, 새 배우도 고를 수 있게 한다.
           파일명은 폰에서 아무 말도 안 해 준다(image.jpg·1000009203.webp). */
        const menu = [
          ...photoless.map((c, i) => `${i + 1}) ${c.name} (${c.id})`),
          `${photoless.length + 1}) 새 배우 만들기`,
        ].join("\n");
        /* 얼굴 없는 배우가 «하나»면 그 번호를 미리 채워 한 번 누르면 끝나게 한다(예전 확인창의 손맛) —
           그래도 이름을 고쳐 적으면 새 배우가 된다. 여럿이면 골라야 하니 비워 둔다. */
        const only = photoless.length === 1 ? photoless[0] : null;
        const answer = await get().promptText({
          title: "누구의 사진인가요?",
          body:
            `${file.name} — 파일명이 어느 배우의 ref와도 다릅니다.\n` +
            (only
              ? `그대로 두면 얼굴 없는 배우 「${only.name}」에게 걸립니다. 새 배우로 세우려면 그 이름을 적어주세요.\n`
              : "얼굴 없는 배우:\n") +
            `${menu}\n번호나 이름을 적어주세요. 새 배우면 그 이름을 적어도 됩니다.`,
          initial: only ? "1" : undefined,
          placeholder: "1",
          okLabel: only ? `「${only.name}」에게 걸기` : "이 배우에게 걸기",
        });
        if (answer === null) continue;
        const a = answer.trim();
        const al = a.toLowerCase();
        const num = /^\d+$/.test(al) ? Number(al) : NaN;
        const target = Number.isFinite(num)
          ? photoless[num - 1]
          : (photoless.find((c) => c.name.toLowerCase() === al || c.id.toLowerCase() === al) ??
            photoless.find((c) => al !== "" && (c.name.toLowerCase().includes(al) || c.id.toLowerCase().includes(al))));
        if (target) {
          if (await bindPhotoToChar(target.id, file)) bound += 1;
          continue;
        }
        if (num === photoless.length + 1 || /^새\s*배우/.test(al)) {
          if (await createActorFromPhoto(file)) bound += 1;
          continue;
        }
        if (Number.isFinite(num) || a === "") {
          get().toast(`「${a}」에 맞는 배우가 없습니다 — 번호를 다시 보거나 배우 카드의 「사진 올리기」로 직접 걸어주세요.`, "ng");
          continue;
        }
        // 이름을 적었는데 아무와도 맞지 않는다 — 그 이름의 새 배우로 세울지 묻는다
        const mk = await get().confirm({
          title: "새 배우 캐스팅",
body:
            `「${a}」라는 배우가 없습니다.\n이 사진(${file.name})으로 새 배우 「${a}」를 만들까요?\n` +
            `(얼굴 없는 배우 ${photoless.map((c) => `「${c.name}」`).join("·")}은 그대로 얼굴 없음으로 남습니다 — 그중 한 명의 사진이라면 그만두고 번호를 골라주세요)`,
          okLabel: "새 배우 만들기",
        });
        if (mk && (await createActorFromPhoto(file, a))) bound += 1;
      }
      if (bound > 0) {
        get().toast(`배우 사진 ${bound}장을 캐스팅했습니다.`, "ok");
        engine.scheduleAutosave();
      }
    },
    /** 배우 카드에서 직접 — 파일명과 무관하게 이 배우에게 건다. */
    uploadCharPhotoFor: async (charId, file) => {
      const ch = get().project?.story.characters.find((c) => c.id === charId);
      if (!ch) return;
      if (await bindPhotoToChar(charId, file)) {
        get().toast(`「${ch.name}」의 캐스팅 사진을 걸었습니다 — 얼굴 고정 기준이 됩니다.`, "ok");
        engine.scheduleAutosave();
      }
    },

    removeCharImage: (ref) => {
      engine.patchProject((p) => {
        const next = { ...p.charAssets };
        delete next[ref];
        return { ...p, charAssets: next };
      });
      get().toast("캐스팅 사진을 뺐습니다. 이 배우는 「얼굴 없음」이 됩니다.");
      engine.scheduleAutosave();
    },
  };
}
