/** 촬영장 슬라이스 — 카메라 설정, 프롬프트, 감독 판정, 큐. 「전부 다시」는 없다. */
import * as db from "../../lib/db";
import { cloneImageBlob } from "../../lib/blob";
import { assemblePrompt } from "../../lib/prompt";
import {
  CAMERA_MODELS,
  MakefunError,
  creditLine,
  downloadResultImage,
  findRecentRecord,
  makeMovingVideo,
  modelById,
} from "../../lib/makefun";
import { isApiCut, pushCurrentToTakes, reuseTarget, type SizeKey } from "../../types";
import { genKey } from "../project-utils";
import type { Get, Set, StageSlice } from "../types";
import type { Engine } from "../engine";

/**
 * 저장이 «가득 차서» 막힌 상태에서만 붙이는 꼬리말.
 *
 * 브라우저는 지운 자리를 곧바로 돌려주지 않는다 — 실측(v1.3.0, 할당량 4MB)에서 테이크 16장을
 * 지워 저장소에 0장이 됐는데도 사용량은 3,825KB 그대로였고, 8초 뒤에도 새로고침 뒤에도 같았다.
 * 그러니 「3.7MB 확보」만 말하고 끝내면 감독은 「이제 저장되겠지」라고 믿고 창을 닫는다.
 */
function spaceCaveat(get: Get): string {
  return get().saveFailed
    ? " 다만 브라우저가 그 자리를 곧바로 돌려주지 않을 수 있습니다 — 저장이 계속 안 되면 «내 기기로 내보내기»로 먼저 챙겨두세요."
    : "";
}

export function createStageSlice(set: Set, get: Get, engine: Engine): StageSlice {
  const openSettingsForToken = () => {
    get().toast("카메라 토큰이 없습니다. 설정에서 MakeFun 토큰을 넣어주세요.", "ng");
    set({ settingsOpen: true });
  };

  return {
    shooting: {},
    batch: null,

    setCamera: (model, size) => {
      const m = modelById(model);
      const s: SizeKey = m.sizes.includes(size) ? size : m.sizes[0];
      engine.patchProject((p) => ({ ...p, camera: { model: m.id, size: s } }));
      engine.scheduleAutosave();
    },

    setCustomPrompt: (sceneId, text) => {
      /* 상자는 조립본 전문으로 채워져 있어, 한 글자만 쳐도 그 전문이 customPrompt로 굳는다 —
         그 뒤로 이 컷은 화풍·배우 외모·장소 변경에서 떨어져 나간다(effectivePrompt가 조립을 건너뛴다).
         고쳤다가 «원래 글자로 되돌려 놓은» 컷까지 굳어 있을 이유는 없다: 글자가 조립본과 같아지면
         직접 쓴 상태를 스스로 푼다(✎ 칩도 사라진다). 손으로 되돌리기를 찾지 않아도 되는 자리. */
      const scene = get().project?.story.scenes.find((sc) => sc.id === sceneId);
      const story = get().project?.story;
      const same = scene && story && text.trim() === assemblePrompt(story, scene).trim();
      engine.patchCut(sceneId, (c) => ({ ...c, customPrompt: same ? undefined : text }));
      engine.scheduleAutosave();
    },

    /**
     * 이 컷의 프롬프트를 조립본으로 되돌린다 — 감독이 직접 쓴 글을 버리는 일이므로 먼저 묻는다.
     *
     * 되돌리기(⤺)는 대본 변경만 담고 컷 기록은 «현재»가 우선이라(scriptSlice의 병합 규칙)
     * 이 글은 Ctrl+Z로도 돌아오지 않는다. 앱의 다른 파괴적 문들(테이크 비우기·저장소 청소)은
     * 모두 확인창을 세우는데 이 단추만 조용히 지웠다.
     */
    resetPrompt: async (sceneId) => {
      const cur = get().project?.cuts[sceneId]?.customPrompt ?? "";
      if (cur.trim()) {
        const ok = await get().confirm({
          title: "기본 프롬프트로 되돌리기",
          body:
            `${sceneId} 컷의 «직접 쓴 프롬프트»를 버리고 대본에서 다시 조립합니다.\n` +
            "그러면 화풍·배우 외모·장소·카메라 고정이 다시 이 컷에 흐릅니다.\n" +
            "(직접 쓴 글은 되돌릴 수 없어요)",
          okLabel: "되돌리기",
          danger: true,
        });
        if (!ok) return;
      }
      engine.patchCut(sceneId, (c) => ({ ...c, customPrompt: undefined }));
      get().toast("기본 프롬프트(조립본)로 되돌렸습니다 — 화풍·배우·장소가 다시 흐릅니다.", "ok");
      engine.scheduleAutosave();
    },

    /**
     * 직접 쓴 프롬프트를 전부 되돌린다 — 화풍을 갈아입힌 뒤 «닿지 않는 컷»을 한 번에 푸는 문.
     *
     * 컷 프롬프트를 손대면 그 컷은 조립을 건너뛰므로(engine.effectivePrompt) 대본의 어떤 변경도
     * 그 컷에 닿지 않는다. 60컷 편에서 카드를 하나씩 눌러 되돌리게 두는 것은 길이 없는 것과 같다.
     */
    resetPromptsAll: async () => {
      const p = get().project;
      if (!p) return;
      const ids = p.story.scenes.map((s) => s.id).filter((id) => (p.cuts[id]?.customPrompt ?? "").trim());
      if (ids.length === 0) {
        get().toast("직접 쓴 프롬프트가 없습니다 — 모든 컷이 이미 대본을 따릅니다.");
        return;
      }
      const ok = await get().confirm({
        title: `직접 쓴 프롬프트 ${ids.length}컷 되돌리기`,
        body:
          `컷 ${ids.length}개의 직접 쓴 프롬프트를 버리고 대본에서 다시 조립합니다.\n` +
          "그 컷들에 화풍·배우 외모·장소·카메라 고정이 다시 흐릅니다.\n" +
          "(직접 쓴 글은 되돌릴 수 없어요 — 남기고 싶은 문장이 있으면 먼저 옮겨 적어 두세요)",
        okLabel: "전부 되돌리기",
        cancelLabel: "그만두기",
        danger: true,
      });
      if (!ok) return;
      for (const id of ids) engine.patchCut(id, (c) => ({ ...c, customPrompt: undefined }));
      get().toast(`${ids.length}컷을 기본 프롬프트로 되돌렸습니다 — 화풍·배우·장소가 다시 흐릅니다.`, "ok");
      engine.scheduleAutosave();
    },

    markNg: (sceneId) => {
      engine.patchCut(sceneId, (c) => ({
        ...c,
        status: "ng",
        delayed: false,
        note: "감독 판정 NG — 다시 찍기로 한 컷입니다. 그림은 테이크로 남습니다.",
      }));
      get().toast(`${sceneId} — NG 판정. 「NG만 다시」에 들어갑니다.`);
      engine.scheduleAutosave();
    },

    markOk: (sceneId) => {
      engine.patchCut(sceneId, (c) =>
        c.imageKey ? { ...c, status: "ok", note: undefined, delayed: false } : c,
      );
      get().toast(`${sceneId} — OK로 되돌렸습니다.`);
      engine.scheduleAutosave();
    },

    /** 내 파일에서 장면 이미지 등록 → OK. */
    uploadSceneImage: async (sceneId, file) => {
      const pid = get().project?.id;
      if (!pid) return;
      try {
        const blob = await cloneImageBlob(file, "image/png");
        if (!engine.stillOnProject(pid)) return; // 읽는 사이 프로젝트가 바뀌면 커밋 금지
        engine.commitImage(sceneId, blob, "upload");
        get().toast(`${sceneId} 컷에 내 이미지를 걸었습니다 — OK.`, "ok");
      } catch (err) {
        get().toast(err instanceof Error ? err.message : "이미지를 읽지 못했습니다.", "ng");
      }
    },

    /** MakeFun 사이트에는 나왔는데 앱이 못 받은 경우 — URL로 가져온다. */
    registerUrlImage: async (sceneId) => {
      const pid = get().project?.id;
      if (!pid) return;
      const url = await get().promptText({
        title: "MakeFun URL 붙이기",
        body: "MakeFun 사이트에 나온 그림 주소를 붙여넣으면 이 컷의 이미지로 가져옵니다.",
        placeholder: "https://…",
        okLabel: "가져오기",
      });
      if (url === null || !url.trim()) return;
      if (!engine.stillOnProject(pid)) return; // 대화상자 사이 전환 방지
      const abort = new AbortController();
      const abortKey = `url:${sceneId}`;
      engine.registerSingleAbort(abortKey, abort); // 프로젝트 전환 시 함께 중단되게
      try {
        engine.setShooting(sceneId, true);
        const blob = await downloadResultImage(url.trim(), abort.signal);
        if (!engine.stillOnProject(pid)) return; // 다운로드 사이 전환 방지
        engine.commitImage(sceneId, blob, "url");
        get().toast(`${sceneId} 컷에 가져온 그림을 걸었습니다 — OK.`, "ok");
      } catch (err) {
        if (!(err instanceof MakefunError && err.kind === "aborted")) {
          get().toast(err instanceof Error ? err.message : "가져오지 못했습니다.", "ng");
        }
      } finally {
        engine.removeSingleAbort(abortKey);
        engine.setShooting(sceneId, false);
      }
    },

    /** 이미지 빼기 — 그림은 지우지 않고 테이크로 남긴다. */
    removeImage: (sceneId) => {
      engine.patchCut(sceneId, (c) => ({
        ...c,
        status: "wait",
        imageKey: undefined,
        takeKeys: pushCurrentToTakes(c),
      }));
      get().toast("이미지를 뺐습니다. 이전 그림은 테이크로 남아 있습니다.");
      engine.scheduleAutosave();
    },

    /** 내 영상 걸기 — 시사실은 이미지 대신 이 영상을 재생한다. 교체는 확인창. */
    attachVideo: async (sceneId, file) => {
      const pid = get().project?.id;
      if (!pid) return;
      const looksVideo = file.type.startsWith("video/") || /\.(mp4|webm|mov)$/i.test(file.name);
      if (!looksVideo) {
        get().toast("영상 파일(mp4/webm)이 아닙니다.", "ng");
        return;
      }
      if (file.size > 80 * 1024 * 1024) {
        get().toast("영상이 너무 큽니다 (80MB 이하).", "ng");
        return;
      }
      const oldKey = get().project?.cuts[sceneId]?.videoKey;
      if (oldKey) {
        /* 이전 영상은 컷에서 빠지지만 «저장소에서 사라지지는 않는다» — 키가 매번 새로 만들어지므로
           앞 영상은 고아로 남고, 🧹 저장소 청소가 지우는 문이다(실측: 다섯 번 걸면 영상 5개가 남고
           청소가 고아 4개를 잡았다). 영상은 수십 MB짜리라 그 사실을 숨기면 저장소가 조용히 찬다. */
        const oldMb = (get().blobs[oldKey]?.size ?? 0) / 1024 / 1024;
        const howBig = oldMb >= 0.1 ? `(약 ${oldMb.toFixed(1)}MB)` : "";
        const ok = await get().confirm({
          title: "무빙 컷 교체",
          body:
            "이 컷에 이미 영상이 걸려 있습니다. 새 영상으로 바꿀까요?\n" +
            `이전 영상${howBig}은 이 컷에서 빠지고, 🧹 저장소 청소를 누를 때까지 저장소에 남습니다.`,
          okLabel: "바꾸기",
          danger: true,
        });
        if (!ok) return;
      }
      try {
        const buf = await file.arrayBuffer(); // Blob 복제 — 참조 소실 대비
        if (buf.byteLength === 0) throw new Error("파일 내용이 비어 있습니다.");
        if (!engine.stillOnProject(pid)) return;
        const type = file.type.startsWith("video/") ? file.type : "video/mp4";
        const blob = new Blob([buf], { type });
        const key = genKey(pid, `${sceneId}:video`);
        set((s) => ({ blobs: { ...s.blobs, [key]: blob } }));
        engine.patchCut(sceneId, (c) => ({ ...c, videoKey: key }));
        engine.markDirty([key]);
        engine.scheduleAutosave();
        get().toast(`${sceneId} 컷에 무빙(영상)을 걸었습니다. 시사실에서 재생됩니다.`, "ok");
      } catch (err) {
        get().toast(err instanceof Error ? err.message : "영상을 읽지 못했습니다.", "ng");
      }
    },

    removeVideo: (sceneId) => {
      engine.patchCut(sceneId, (c) => ({ ...c, videoKey: undefined }));
      get().toast("무빙(영상)을 뺐습니다. 시사실은 다시 스틸 이미지를 보여줍니다.");
      engine.scheduleAutosave();
    },

    /** 무빙 컷 (실험) — 촬영 직후 보관한 원본 URL로 이미지→영상 변환. */
    makeMovingCut: async (sceneId) => {
      const s = get();
      const p = s.project;
      const scene = engine.sceneOf(sceneId);
      if (!p || !scene || s.shooting[sceneId]) return;
      if (!s.token) {
        openSettingsForToken();
        return;
      }
      const cut = p.cuts[sceneId];
      if (!cut?.sourceUrl) {
        get().toast(
          "이 컷에는 변환에 쓸 원본 URL이 없습니다. MakeFun으로 새로 찍은 컷(약 3일 이내)에서만 무빙 컷을 만들 수 있어요.",
          "ng",
        );
        return;
      }
      const ok = await get().confirm({
        title: "무빙 컷 만들기 (실험)",
        body: `이 컷의 그림을 짧은 영상으로 바꿔 찍습니다.\n예상 약 30 크레딧 · 수 분이 걸릴 수 있습니다.`,
        okLabel: "변환 시작",
      });
      if (!ok) return;
      const pid = p.id;
      const abort = new AbortController();
      const abortKey = `video:${sceneId}`;
      engine.registerSingleAbort(abortKey, abort);
      try {
        engine.setShooting(sceneId, true);
        const { blob, coins } = await makeMovingVideo({
          token: s.token,
          sceneId,
          imageUrl: cut.sourceUrl,
          prompt: engine.effectivePrompt(scene),
          signal: abort.signal,
        });
        if (!engine.stillOnProject(pid)) {
          // 편이 바뀌었다 — 영상은 못 쓰지만 돈은 나갔다(컷당 수십 코인)
          await engine.addCoinsTo(pid, coins);
          return;
        }
        const key = genKey(pid, `${sceneId}:video`);
        set((cur) => ({ blobs: { ...cur.blobs, [key]: blob } }));
        engine.patchCut(sceneId, (c) => ({ ...c, videoKey: key }));
        engine.markDirty([key]);
        engine.addCoins(coins);
        engine.scheduleAutosave();
        get().toast(`${sceneId} — 무빙 컷 완성. 시사실에서 움직입니다.`, "ok");
      } catch (err) {
        // 실패해도 과금은 기록 — 편이 바뀌었더라도 그 편의 장부에 남긴다
        if (err instanceof MakefunError) await engine.addCoinsTo(pid, err.coins);
        if (err instanceof MakefunError && err.kind === "aborted") {
          // 중단이라도 접수된 뒤라면 코인은 나갔다 — 컷에 그 사실과 사람이 할 수 있는 길을 남긴다
          engine.noteVideoBillingOnAbort(sceneId, err.coins);
          if ((err.coins ?? 0) > 0) {
            get().toast(
              `변환을 중단했지만 ${err.coins}코인은 이미 나갔습니다 — 컷 메모에 회수 방법을 적어 두었습니다.`,
              "info",
            );
          }
        } else {
          get().toast(err instanceof Error ? err.message : "무빙 컷을 만들지 못했습니다.", "ng");
        }
      } finally {
        engine.removeSingleAbort(abortKey);
        engine.setShooting(sceneId, false);
      }
    },

    /** 이 컷을 컷씬(영상화 대상)으로 지정/해제. */
    toggleCutscene: (sceneId) => {
      const was = get().project?.cuts[sceneId]?.cutscene;
      engine.patchCut(sceneId, (c) => ({ ...c, cutscene: !c.cutscene || undefined }));
      get().toast(
        was
          ? `${sceneId} — 컷씬 지정을 풀었습니다.`
          : `${sceneId} — 컷씬으로 지정했습니다. 「컷씬 영상화」가 이 컷을 변환합니다.`,
      );
      engine.scheduleAutosave();
    },

    /** 지정된 컷씬들을 한 번에 영상화 — 원본 URL 있는 컷만. */
    startVideoBatch: async () => {
      const s = get();
      const p = s.project;
      if (!p || s.batch?.running) return;
      const marked = p.story.scenes.filter(
        (sc) => p.cuts[sc.id]?.cutscene && !p.cuts[sc.id]?.videoKey,
      );
      if (marked.length === 0) {
        get().toast(
          "영상화할 컷씬이 없습니다. 컷 카드의 「🎬 컷씬」 버튼으로 지정해 주세요 (이미 완성된 컷씬은 제외됩니다).",
        );
        return;
      }
      const ready = marked.filter((sc) => p.cuts[sc.id]?.sourceUrl);
      const skipped = marked.length - ready.length;
      if (ready.length === 0) {
        get().toast(
          "지정한 컷씬에 변환용 원본 URL이 없습니다. MakeFun으로 새로 찍은 컷(약 3일 이내)만 영상화할 수 있어요 — 해당 컷을 「이 컷만 다시」로 찍은 뒤 시도해 주세요.",
          "ng",
        );
        return;
      }
      if (!s.token) {
        openSettingsForToken();
        return;
      }
      const ok = await get().confirm({
        title: "컷씬 영상화",
        body:
          `${ready.length}컷 × 약 30 크레딧 ≈ ${ready.length * 30} 크레딧\n` +
          `영상은 컷당 수 분이 걸릴 수 있습니다. 완성되면 시사실에서 그 컷이 움직입니다.` +
          (skipped > 0
            ? `\n원본 URL이 없는 ${skipped}컷은 건너뜁니다 (새로 찍은 컷만 가능).`
            : ""),
        okLabel: "영상화 시작",
      });
      if (!ok) return;
      await engine.runVideoBatch(ready.map((sc) => sc.id));
    },

    /**
     * MakeFun 기록에서 이 컷(name === sceneId)의 최근 24시간 내 완성본을 찾아온다.
     * 서버가 잠깐 꺼졌거나 연결이 끊겨 앱이 결과를 놓쳤을 때 — 추가 과금 없이 회수.
     * 지금 카메라 계열부터 보고, 없으면 모든 이미지 계열을 훑는다.
     */
    pullResultFor: async (sceneId) => {
      const s = get();
      const p = s.project;
      if (!p || s.shooting[sceneId]) return;
      if (!s.token) {
        openSettingsForToken();
        return;
      }
      const pid = p.id;
      const abort = new AbortController();
      const abortKey = `pull:${sceneId}`;
      engine.registerSingleAbort(abortKey, abort);
      engine.setShooting(sceneId, true);
      try {
        const minTs = Date.now() - 24 * 3600_000;
        const current = modelById(p.camera.model);
        const seen = new Set<string>();
        const candidates = [current, ...CAMERA_MODELS.filter((m) => m.group === "image")].filter(
          (m) => {
            if (seen.has(m.family)) return false;
            seen.add(m.family);
            return true;
          },
        );
        /* 기록은 «name === 컷 id»로만 찾을 수 있는데 컷 id는 편마다 다시 시작한다 —
           거의 모든 작품에 s01이 있으므로 다른 편의 같은 번호를 물어 올 수 있다.
           그러면 남의 그림이 「추가 과금 없이 OK」라는 말과 함께 이 컷에 걸린다.
           그래서 찾은 기록의 프롬프트를 이 컷의 것과 맞대어 보고, 다르면 «묻고» 건다.
           (조회는 공짜라 한 번 더 보는 데 드는 값이 없다.) */
        const scene = engine.sceneOf(sceneId);
        const want = scene ? engine.effectivePrompt(scene) : undefined;
        let url: string | null = null;
        let found: { url: string; prompt: string | null; samePrompt: boolean | null } | null = null;
        for (const model of candidates) {
          found = await findRecentRecord(s.token, model, sceneId, minTs, abort.signal, want);
          if (found) {
            url = found.url;
            break;
          }
        }
        if (url && found && found.samePrompt === false) {
          const mine = (want ?? "").replace(/\s+/g, " ").slice(0, 70);
          const theirs = (found.prompt ?? "").replace(/\s+/g, " ").slice(0, 70);
          const go = await get().confirm({
            title: "다른 촬영의 결과일 수 있습니다",
            body:
              `MakeFun 기록에서 「${sceneId}」이라는 이름의 결과를 찾았지만, 프롬프트가 이 컷과 다릅니다 — ` +
              `컷 번호는 편마다 다시 시작하니 «다른 편의 ${sceneId}»일 수 있어요.\n\n` +
              `이 컷: ${mine}…\n찾은 결과: ${theirs}…\n\n그래도 이 컷에 걸까요?`,
            okLabel: "그래도 걸기",
            danger: true,
          });
          if (!go) {
            get().toast("가져오지 않았습니다 — 이 컷은 그대로 둡니다.");
            return;
          }
        }
        if (!url) {
          get().toast(
            `${sceneId}: 최근 24시간 MakeFun 기록에서 완성본을 찾지 못했습니다. MakeFun 사이트에 보인다면 「MakeFun URL 붙이기」로 가져올 수 있어요.`,
            "ng",
          );
          return;
        }
        const blob = await downloadResultImage(url, abort.signal);
        if (!engine.stillOnProject(pid)) return;
        engine.commitImage(sceneId, blob, "shoot", url);
        get().toast(`${sceneId} — MakeFun에서 결과를 찾아왔습니다. 추가 과금 없이 OK.`, "ok");
      } catch (err) {
        if (!(err instanceof MakefunError && err.kind === "aborted")) {
          get().toast(err instanceof Error ? err.message : "결과를 찾아오지 못했습니다.", "ng");
        }
      } finally {
        engine.removeSingleAbort(abortKey);
        engine.setShooting(sceneId, false);
      }
    },

    /** 이 컷을 표지로 지정/해제 — 시사실 포스터의 배경이 된다. */
    setPoster: (sceneId) => {
      const was = get().project?.posterSceneId === sceneId;
      engine.patchProject((p) => ({ ...p, posterSceneId: was ? null : sceneId }));
      get().toast(
        was ? "표지 지정을 풀었습니다." : `${sceneId} — 이 컷이 작품의 표지가 됐습니다.`,
        was ? "info" : "ok",
      );
      engine.scheduleAutosave();
    },

    /** 이전 테이크로 복귀 — 현재 그림과 자리만 바꾼다. */
    revertTake: (sceneId, takeIndex) => {
      engine.patchCut(sceneId, (c) => {
        const chosen = c.takeKeys[takeIndex];
        if (!chosen) return c;
        const rest = c.takeKeys.filter((_, i) => i !== takeIndex);
        return {
          ...c,
          status: "ok",
          imageKey: chosen,
          takeKeys: c.imageKey ? [c.imageKey, ...rest] : rest,
          note: undefined,
        };
      });
      get().toast("이전 테이크로 되돌렸습니다.");
      engine.scheduleAutosave();
    },

    /**
     * 이 컷의 옛 테이크 비우기 — 다시 찍기를 반복한 컷이 저장소를 붙들고 있는 것을 푼다.
     *
     * 실측: 한 컷을 여섯 번 다시 걸면 그림 여섯 장(약 1.9MB)을 들고 있다. 60컷 × 평균 3번이면
     * 한 장(chapter)에 57MB, 20장이면 1GB가 넘는다. 테이크는 «참조되는 자산»이라 저장소 청소로는
     * 잡히지 않으므로(그게 옳다 — 되돌릴 수 있어야 한다) 감독이 컷 단위로 비울 자리가 필요하다.
     * 지금 그림은 건드리지 않는다.
     */
    clearTakes: async (sceneId) => {
      const cut = get().project?.cuts[sceneId];
      const keys = cut?.takeKeys ?? [];
      if (keys.length === 0) {
        get().toast("이 컷에는 이전 테이크가 없습니다.");
        return;
      }
      const ok = await get().confirm({
        title: `${sceneId} — 옛 테이크 비우기`,
        body:
          `이 컷의 이전 테이크 ${keys.length}장을 저장소에서 지웁니다.
` +
          "지금 걸려 있는 그림과 판정은 그대로입니다. (지운 테이크는 되돌릴 수 없어요)",
        okLabel: "비우기",
        danger: true,
      });
      if (!ok) return;
      // 순서가 중요하다: 먼저 저장을 흘려보내고(대기 중 쓰기가 뒤늦게 되살아나지 않게),
      // 저장소에서 지우고, 메모리 사본(blobs·dirty)까지 치운다. 메모리에 남기면 다음 저장이
      // 그대로 다시 써 넣어서 «약 N MB 확보»가 거짓말이 된다(실측으로 잡았다: 6 → 6).
      await engine.performSave(true);
      const bytes = await db.deleteAssetsMeasured(keys);
      const gone = new Set(keys);
      set((st) => {
        const blobs = { ...st.blobs };
        for (const k of keys) delete blobs[k];
        return { blobs, dirtyAssets: st.dirtyAssets.filter((k) => !gone.has(k)) };
      });
      engine.patchCut(sceneId, (c) => ({ ...c, takeKeys: [] }));
      await engine.performSave(true);
      const mb = (bytes / 1024 / 1024).toFixed(1);
      get().toast(`옛 테이크 ${keys.length}장을 비웠습니다 — 약 ${mb}MB 확보.${spaceCaveat(get)}`, "ok");
    },

    /**
     * 여러 컷의 옛 테이크를 한 번에 — 「이 장」을 다 다시 찍은 뒤를 위한 문.
     *
     * 실측(2026-09-07): 12컷을 세 번씩 다시 걸면 자산 36개·11.2MB이고, 컷마다 비우려면
     * «컷 열기 → 🧹 → 확인» 세 번씩 36번을 눌러야 했다(60컷 화면 180번). 그래서 한 번으로 묶는다.
     * 지우는 것은 여전히 «옛 테이크»뿐 — 지금 걸린 그림과 판정은 건드리지 않는다.
     */
    clearTakesMany: async (sceneIds) => {
      const p = get().project;
      if (!p) return;
      const pairs = sceneIds
        .map((id) => ({ id, keys: p.cuts[id]?.takeKeys ?? [] }))
        .filter((x) => x.keys.length > 0);
      const keys = pairs.flatMap((x) => x.keys);
      if (keys.length === 0) {
        get().toast("비울 옛 테이크가 없습니다.");
        return;
      }
      const ok = await get().confirm({
        title: `옛 테이크 ${keys.length}장 비우기`,
        body:
          `컷 ${pairs.length}개에 쌓인 이전 테이크 ${keys.length}장을 저장소에서 지웁니다.
` +
          "지금 걸려 있는 그림과 판정은 그대로입니다. (지운 테이크는 되돌릴 수 없어요)",
        okLabel: "비우기",
        danger: true,
      });
      if (!ok) return;
      // 순서는 clearTakes와 같다(그 이유도 같다 — 메모리 사본을 남기면 다음 저장이 되살린다)
      await engine.performSave(true);
      const bytes = await db.deleteAssetsMeasured(keys);
      const gone = new Set(keys);
      set((st) => {
        const blobs = { ...st.blobs };
        for (const k of keys) delete blobs[k];
        return { blobs, dirtyAssets: st.dirtyAssets.filter((k) => !gone.has(k)) };
      });
      for (const { id } of pairs) engine.patchCut(id, (c) => ({ ...c, takeKeys: [] }));
      await engine.performSave(true);
      const mb = (bytes / 1024 / 1024).toFixed(1);
      get().toast(
        `컷 ${pairs.length}개의 옛 테이크 ${keys.length}장을 비웠습니다 — 약 ${mb}MB 확보.${spaceCaveat(get)}`,
        "ok",
      );
    },

    /** 대기 컷 촬영 / NG만 다시 — 「전부 다시」는 없다. */
    startBatch: async (scope, onlyIds) => {
      const s = get();
      const p = s.project;
      if (!p || s.batch?.running) return;
      const only = onlyIds ? new Set(onlyIds) : null;
      const targets = p.story.scenes.filter((sc) => {
        if (only && !only.has(sc.id)) return false;
        const cut = p.cuts[sc.id];
        const status = cut?.status ?? "wait";
        if (s.shooting[sc.id]) return false;
        return scope === "pending" ? status === "wait" : status === "ng";
      });
      if (targets.length === 0) {
        get().toast(
          only
            ? "이 장에는 찍을 컷이 없습니다."
            : scope === "pending"
              ? "대기 중인 컷이 없습니다."
              : "NG 컷이 없습니다.",
        );
        return;
      }
      const apiCount = targets.filter((sc) => isApiCut(sc, p.cuts[sc.id])).length;
      if (!s.token && apiCount > 0) {
        openSettingsForToken();
        return;
      }
      const model = modelById(p.camera.model);
      const freeCount = targets.length - apiCount;
      const ok = await get().confirm({
        title:
          (only ? "이 장만 · " : "") + (scope === "pending" ? "대기 컷 촬영" : "NG만 다시 촬영"),
        body:
          `${creditLine(model, p.camera.size, apiCount)}` +
          (freeCount > 0 ? `\nreuse·플레이스홀더 ${freeCount}컷은 크레딧을 쓰지 않습니다.` : ""),
        okLabel: "촬영 시작",
      });
      if (!ok) return;
      await engine.runBatch(targets.map((sc) => sc.id));
    },

    /** 이 컷만 생성/다시. reuse 컷이면 reuse를 끊고 API로 새로 찍는다. */
    shootSingle: async (sceneId) => {
      const s = get();
      const p = s.project;
      const scene = engine.sceneOf(sceneId);
      if (!p || !scene || s.shooting[sceneId]) return;
      if (s.batch?.running) {
        get().toast("배치 촬영이 돌고 있습니다. 중단한 뒤 이 컷만 다시 찍어주세요.");
        return;
      }
      if (!s.token) {
        openSettingsForToken();
        return;
      }
      if (reuseTarget(scene) && !p.cuts[sceneId]?.reuseBroken) {
        engine.patchCut(sceneId, (c) => ({ ...c, reuseBroken: true }));
      }
      const abort = new AbortController();
      engine.registerSingleAbort(sceneId, abort);
      try {
        await engine.shootOne(sceneId, abort.signal);
      } finally {
        engine.removeSingleAbort(sceneId);
      }
    },

    stopBatch: () => engine.abortAll(),
  };
}
