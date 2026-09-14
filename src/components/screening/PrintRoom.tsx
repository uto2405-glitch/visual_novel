/** 인쇄본(웹툰) 조판실 — 찍어둔 컷을 만화 페이지로 옮긴다. 크레딧을 쓰지 않는다.
 *  미리보기를 보면서 말풍선 자리를 옮기는 것이 이 창의 전부다. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStudio } from "../../store/useStudio";
import {
  buildCastPage,
  buildContentsPage,
  buildCoverPage,
  buildWebtoon,
  chunkByPage,
  suggestBalloonPos,
  type CastCard,
  type Layout,
  type WebtoonPanel,
} from "../../lib/webtoon";
import { speakerName } from "../../lib/story";
import { chapterOf, chapterRanges } from "../../lib/chapters";
import {
  collectCastPhotos,
  collectOkImages,
  type BalloonKind,
  type BalloonPos,
  type WebtoonFx,
} from "../../types";
import { useProject } from "../hooks";
import { useEscapeClose } from "../../lib/hooks";

const POS_LABEL: Record<BalloonPos, string> = {
  tl: "↖",
  tr: "↗",
  bl: "↙",
  br: "↘",
};
const KIND_LABEL: Record<BalloonKind, string> = {
  say: "💬 대사",
  think: "💭 생각",
  shout: "❗ 외침",
};

export function PrintRoom() {
  const open = useStudio((s) => s.printOpen);
  if (!open) return null;
  return <PrintRoomInner />;
}

function PrintRoomInner() {
  const project = useProject();
  const blobs = useStudio((s) => s.blobs);
  const setPrintOpen = useStudio((s) => s.setPrintOpen);
  const setTab = useStudio((s) => s.setTab);
  const updateScene = useStudio((s) => s.updateScene);
  const undoScript = useStudio((s) => s.undoScript);
  const undoDepth = useStudio((s) => s.undoDepth);
  const exportWebtoon = useStudio((s) => s.exportWebtoon);
  const toast = useStudio((s) => s.toast);

  const [layout, setLayout] = useState<Layout>("strip");
  const [perPage, setPerPage] = useState(4);
  const [page, setPage] = useState(0);
  const [cover, setCover] = useState(true);
  const [castPage, setCastPage] = useState(false);
  const [chapterBand, setChapterBand] = useState(() => {
    try {
      return localStorage.getItem("vn-studio:printChapterBand") !== "off";
    } catch {
      return true;
    }
  });
  const pickBand = (v: boolean) => {
    setChapterBand(v);
    try {
      localStorage.setItem("vn-studio:printChapterBand", v ? "on" : "off");
    } catch {
      /* 사생활 보호 모드에서도 조판은 계속된다 */
    }
  };
  const [contents, setContents] = useState(() => {
    try {
      return localStorage.getItem("vn-studio:printContents") !== "off";
    } catch {
      return true;
    }
  });
  const pickContents = (v: boolean) => {
    setContents(v);
    try {
      localStorage.setItem("vn-studio:printContents", v ? "on" : "off");
    } catch {
      /* 사생활 보호 모드에서도 조판은 계속된다 */
    }
  };
  const [capNums, setCapNums] = useState(() => {
    try {
      return localStorage.getItem("vn-studio:printCapNums") !== "off";
    } catch {
      return true;
    }
  });
  const pickCapNums = (v: boolean) => {
    setCapNums(v);
    try {
      localStorage.setItem("vn-studio:printCapNums", v ? "on" : "off");
    } catch {
      /* 사생활 보호 모드에서도 조판은 계속된다 */
    }
  };
  const [paper, setPaper] = useState<"white" | "black">(() => {
    try {
      return localStorage.getItem("vn-studio:printPaper") === "black" ? "black" : "white";
    } catch {
      return "white";
    }
  });
  const pickPaper = (v: "white" | "black") => {
    setPaper(v);
    try {
      localStorage.setItem("vn-studio:printPaper", v);
    } catch {
      /* 사생활 보호 모드에서도 조판은 계속된다 */
    }
  };
  // 조판 취향 — 시사실 취향과 같은 방식으로 이 브라우저에 기억한다
  const [textScale, setTextScale] = useState(() => {
    try {
      const v = Number(localStorage.getItem("vn-studio:printTextScale"));
      return [0.85, 1, 1.2].includes(v) ? v : 1;
    } catch {
      return 1;
    }
  });
  const [gutter, setGutter] = useState(() => {
    try {
      const v = Number(localStorage.getItem("vn-studio:printGutter"));
      return [0, 10, 22].includes(v) ? v : 10;
    } catch {
      return 10;
    }
  });
  const pickScale = (v: number) => {
    setTextScale(v);
    try {
      localStorage.setItem("vn-studio:printTextScale", String(v));
    } catch {
      /* 취향 기억은 장식 */
    }
  };
  const pickGutter = (v: number) => {
    setGutter(v);
    try {
      localStorage.setItem("vn-studio:printGutter", String(v));
    } catch {
      /* 취향 기억은 장식 */
    }
  };
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // 읽는 순서 = 시사 경로 (갈림길은 첫 갈래). exportWebtoon과 같은 규칙.
  const order = useMemo(() => {
    const ok = collectOkImages(project, blobs);
    const byId = new Map(project.story.scenes.map((sc) => [sc.id, sc] as const));
    const out: string[] = [];
    const seen = new Set<string>();
    let cur = project.story.scenes[0];
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id);
      if (ok.has(cur.id)) out.push(cur.id);
      const nextId = cur.choices?.length ? cur.choices[0].next : cur.next;
      const nxt = nextId ? byId.get(nextId) : undefined;
      if (!nxt) break;
      cur = nxt;
    }
    for (const sc of project.story.scenes) {
      if (ok.has(sc.id) && !out.includes(sc.id)) out.push(sc.id);
    }
    return out;
  }, [project, blobs]);

  const per = layout === "grid" ? 4 : perPage;
  // 내보내기와 같은 규칙으로 장을 나눈다 — 미리보기가 결과와 다르면 조판실은 쓸모가 없다
  const bodyChunks = useMemo(() => {
    const byIdLocal = new Map(project.story.scenes.map((sc) => [sc.id, sc] as const));
    const chunks = chunkByPage(
      order,
      per,
      (id) => byIdLocal.get(id)?.webtoon?.pageBreak === true,
    );
    return chunks.length > 0 ? chunks : [[]];
  }, [project.story.scenes, order, per]);
  const pageTotal = bodyChunks.length;
  const castPhotos = useMemo(() => collectCastPhotos(project, blobs), [project, blobs]);
  // 전속 배우단 — 「N편 출연」을 등장인물 장에 함께 적기 위해 이름으로 맞춘다
  const troupe = useStudio((s) => s.troupe);
  const loadTroupe = useStudio((s) => s.loadTroupe);
  // 출연 «작품 이름»은 저장된 작품 전체를 훑어야 안다 — 인쇄실을 열 때 한 번만
  const troupeWorks = useStudio((s) => s.troupeWorks);
  const loadTroupeWorks = useStudio((s) => s.loadTroupeWorks);
  useEffect(() => {
    void loadTroupe();
    void loadTroupeWorks();
  }, [loadTroupe, loadTroupeWorks]);
  /** 이 배우가 나온 «다른» 작품 이름들 — 이 책은 뺀다 */
  const otherFilms = useCallback(
    (name: string) => {
      const seen = new Set<string>();
      const out: string[] = [];
      for (const w of troupeWorks[name] ?? []) {
        if (w.title === project.title || w.title === project.story.title || seen.has(w.title)) continue;
        seen.add(w.title);
        out.push(w.title);
      }
      return out;
    },
    [troupeWorks, project.title, project.story.title],
  );
  const castCount = castPhotos.length;
  // 등장인물 장은 본문 뒤에 한 장 더 붙는다 — 미리보기에서도 넘겨볼 수 있어야 한다
  // 장 목차 — 장이 다섯을 넘는 합본에서만. 조판 엔진과 «같은 기준»으로 세어야 장수가 맞는다.
  const chapters = useMemo(() => {
    const byIdLocal = new Map(project.story.scenes.map((sc) => [sc.id, sc] as const));
    // 조판 엔진과 «같은 규칙»: 장을 여는 쪽만, 첫 쪽은 표시 없이도 1장, 이름 없으면 「N장」.
    // 장 번호는 지금까지 담은 개수로 센다 — 바깥 변수를 고쳐 쓰면 렌더 규칙에 걸린다.
    const out: { title: string; page: number; cuts: number }[] = [];
    for (let i = 0; i < bodyChunks.length; i++) {
      const first = bodyChunks[i][0] ? byIdLocal.get(bodyChunks[i][0]) : undefined;
      if (i !== 0 && first?.webtoon?.pageBreak !== true) {
        // 한 장이 여러 쪽에 걸치면 그 쪽의 컷도 그 장의 두께다 (조판 엔진과 같은 셈)
        if (out.length > 0) out[out.length - 1].cuts += bodyChunks[i].length;
        continue;
      }
      out.push({
        title: (first?.webtoon?.caption ?? "").trim() || `${out.length + 1}장`,
        page: i + 1,
        cuts: bodyChunks[i].length,
      });
    }
    return out;
  }, [bodyChunks, project.story.scenes]);
  const withContents = contents && chapters.length >= 5;
  const withCast = castPage && castCount > 0;
  // 표지는 «내보내야만 보이는 것»이었다 — 미리보기에서도 0번 장으로 넘겨볼 수 있게 한다
  const withCover = cover && order.length > 0;
  const viewTotal = pageTotal + (withCover ? 1 : 0) + (withContents ? 1 : 0) + (withCast ? 1 : 0);
  const bodyPage = page - (withCover ? 1 : 0) - (withContents ? 1 : 0);
  /**
   * 지금 보고 있는 쪽이 속한 «장(챕터)» — 연재는 화마다 파일 하나로 올리므로
   * 「전체」 말고 이 장만 뽑을 수 있어야 한다. 장이 둘 이상일 때만 나온다.
   */
  const storyChapters = useMemo(() => chapterRanges(project.story.scenes), [project.story.scenes]);
  const hereChapter =
    storyChapters.length >= 2
      ? // bodyPage는 0부터다(표지·목차 장을 뺀 본문 인덱스) — 1을 빼면 한 쪽 뒤처진 장을 가리킨다
        chapterOf(
          storyChapters,
          (bodyPage >= 0 && bodyPage < bodyChunks.length
            ? bodyChunks[bodyPage]
            : bodyChunks[0])?.[0] ?? "",
        )
      : undefined;
  const isCoverView = withCover && page === 0;
  const isContentsView = withContents && page === (withCover ? 1 : 0);
  // 조판실은 «말풍선을 고치는 곳»이다 — 표지 장에서 열면 고칠 컷이 없는 화면이 먼저 나온다.
  // 그래서 처음에는 본문 첫 장을 보여주고, 표지는 「‹ 이전 장」으로 넘겨보게 한다.
  const [landed, setLanded] = useState(false);
  if (!landed) {
    setLanded(true);
    if (withCover && page === 0) setPage(1 + (withContents ? 1 : 0));
  }
  const isCastView = bodyPage >= pageTotal;
  const pageIds = useMemo(
    () => (bodyPage < 0 || bodyPage >= bodyChunks.length ? [] : bodyChunks[bodyPage]),
    [bodyChunks, bodyPage],
  );
  const pageKey = pageIds.join(" ");
  // 컷 번호(#N)는 앞 장들의 컷 수를 더해 센다 — 장 나누기로 페이지당 컷 수가 달라지기 때문
  const cutNoBase = bodyChunks
    .slice(0, Math.max(0, bodyPage))
    .reduce((a, c) => a + c.length, 0);
  /**
   * 장 미리보기 캐시 — 장을 넘길 때마다 1.5초씩 다시 그리던 것을 즉시 보여준다.
   *
   * 캐시는 «틀린 그림을 보여줄» 위험이 있으므로, 그리는 데 쓰이는 값 전부를 지문에 넣는다:
   * 조판 설정(전역) + 그 장의 컷 id·조판 설정·그림 키·대사. 하나라도 다르면 다시 그린다.
   */
  const cacheRef = useRef<Map<string, string>>(new Map());
  const globalSig = JSON.stringify([layout, per, textScale, gutter, paper, cover, castPage, capNums, chapterBand, contents]);
  // 전역 설정이 바뀌면 모든 장이 낡는다 — 통째로 버린다(URL도 되돌려준다).
  // 이 effect가 미리보기 effect보다 «먼저» 선언돼 있어야 같은 커밋에서 비운 뒤 다시 그린다.
  useEffect(() => {
    const cache = cacheRef.current;
    for (const url of cache.values()) URL.revokeObjectURL(url);
    cache.clear();
  }, [globalSig]);
  const viewSig = useMemo(() => {
    if (isCoverView) {
      const id =
        project.posterSceneId && project.cuts[project.posterSceneId]?.status === "ok"
          ? project.posterSceneId
          : order[0];
      const key = id ? project.cuts[id]?.imageKey : undefined;
      return `cover|${id}|${key}|${project.story.title}|${order.length}`;
    }
    if (isCastView) {
      // 출연 작품 이름도 서명에 넣는다 — 저장된 작품을 훑는 일은 비동기라
      // 먼저 그린 판이 캐시에 남으면 「출연」 칸이 영원히 빈 채로 굳는다
      return `cast|${castPhotos
        .map(
          (c) =>
            `${c.name}~${c.look ?? ""}~${c.cuts}~${c.blob.size}~${c.crop?.x ?? ""}${c.crop?.y ?? ""}~${
              troupe.find((a) => a.name === c.name)?.appearances ?? ""
            }~${otherFilms(c.name).join("/")}`,
        )
        .join(",")}`;
    }
    const parts = pageIds.map((id) => {
      const sc = project.story.scenes.find((x) => x.id === id);
      const cut = project.cuts[id];
      return `${id}~${JSON.stringify(sc?.webtoon ?? {})}~${cut?.imageKey ?? ""}~${sc?.text ?? ""}~${sc?.speaker ?? ""}`;
    });
    return `body|${cutNoBase}|${parts.join(",")}`;
  }, [isCoverView, isCastView, pageIds, project, order, castPhotos, troupe, cutNoBase, otherFilms]);
  const cacheKey = `${globalSig}::${isContentsView ? `toc|${chapters.map((c) => `${c.title}~${c.page}`).join(",")}` : viewSig}`;
  // 미리보기 — 설정이나 대본이 바뀌면 다시 그린다 (전부 로컬 Canvas)
  useEffect(() => {
    let alive = true;
    const ok = collectOkImages(project, blobs);
    const byId = new Map(project.story.scenes.map((sc) => [sc.id, sc] as const));
    void (async () => {
      // setState는 첫 await 뒤에만 — effect 동기 구간에서 상태를 건드리지 않는다
      await Promise.resolve();
      if (!alive) return;
      const hit = cacheRef.current.get(cacheKey);
      if (hit) {
        setPreviewUrl(hit);
        setBusy(false);
        setErr(null);
        return;
      }
      setBusy(true);
      setErr(null);
      const panels: WebtoonPanel[] = [];
      /** 그린 장을 캐시에 넣고 화면에 올린다 — URL의 주인은 캐시다(여기서 revoke하지 않는다) */
      const publish = (blob: Blob) => {
        const url = URL.createObjectURL(blob);
        cacheRef.current.set(cacheKey, url);
        setPreviewUrl(url);
      };
      try {
        // 표지를 보는 중 — 본문 컷 한 장만 읽어 표지를 그린다
        if (isCoverView) {
          const coverId = project.posterSceneId && ok.has(project.posterSceneId)
            ? project.posterSceneId
            : order[0];
          const scene = byId.get(coverId);
          const blob = ok.get(coverId);
          if (scene && blob) {
            const bmp = await createImageBitmap(blob);
            const blobOut = await buildCoverPage(
              project.story,
              {
                scene,
                bitmap: bmp,
                index: 1,
                speaker: speakerName(project.story, scene),
                isNarration: !scene.speaker || scene.speaker === "narration",
              },
              order.length,
              { layout, perPage: per, textScale, gutter, paper, captionNumbers: capNums, chapterBand, contents },
            );
            bmp.close?.();
            if (!alive) return;
            publish(blobOut);
            setBusy(false);
            return;
          }
        }
        // 목차 장을 보는 중
        if (isContentsView && chapters.length > 0) {
          const blob = await buildContentsPage(project.story, chapters, {
            layout,
            perPage: per,
            textScale,
            gutter,
            paper,
          });
          if (!alive) return;
          publish(blob);
          setBusy(false);
          return;
        }
        // 등장인물 장을 보는 중이면 본문을 다시 그리지 않는다
        if (isCastView && castPhotos.length > 0) {
          const cards: CastCard[] = [];
          for (const c of castPhotos) {
            cards.push({
              name: c.name,
              look: c.look,
              cuts: c.cuts,
              crop: c.crop,
              films: troupe.find((a) => a.name === c.name)?.appearances,
              filmTitles: otherFilms(c.name),
              bitmap: await createImageBitmap(c.blob),
            });
          }
          const blob = await buildCastPage(
            project.story,
            cards,
            { layout, perPage: per, textScale, gutter, paper, captionNumbers: capNums, chapterBand, contents },
            viewTotal,
            viewTotal,
          );
          for (const c of cards) c.bitmap.close?.();
          if (!alive) return;
          publish(blob);
          setBusy(false);
          return;
        }
        for (let i = 0; i < pageIds.length; i++) {
          const scene = byId.get(pageIds[i]);
          const blob = ok.get(pageIds[i]);
          if (!scene || !blob) continue;
          panels.push({
            scene,
            bitmap: await createImageBitmap(blob),
            index: cutNoBase + i + 1,
            speaker: speakerName(project.story, scene),
            isNarration: !scene.speaker || scene.speaker === "narration",
          });
        }
        if (panels.length === 0) {
          if (alive) {
            setPreviewUrl(null);
            setBusy(false);
          }
          return;
        }
        const { pages } = await buildWebtoon(project.story, panels, {
          layout,
          perPage: per,
          cover: false, // 미리보기는 본문 페이지만 — 표지는 내보낼 때 붙는다
          textScale,
          gutter,
          paper,
          captionNumbers: capNums,
          chapterBand,
          contents,
        });
        if (!alive) return;
        publish(pages[0]);
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : "미리보기를 그리지 못했습니다.");
      } finally {
        for (const p of panels) p.bitmap.close?.();
        if (alive) setBusy(false);
      }
    })();
    return () => {
      alive = false;
    };
    // pageKey는 pageIds의 내용 지문 — 내용이 같으면 다시 그리지 않는다
  }, [
    project,
    blobs,
    layout,
    per,
    page,
    pageIds,
    pageKey,
    textScale,
    gutter,
    cacheKey,
    isCastView,
    isCoverView,
    isContentsView,
    chapters,
    castPhotos,
    troupe,
    otherFilms,
    viewTotal,
    bodyPage,
    order,
    cutNoBase,
    paper,
    capNums,
    chapterBand,
    contents,
  ]);

  // 등장인물 장을 보다가 그 장을 끄면 갈 곳이 없어진다 — 마지막 본문 장으로 되돌린다
  if (page >= viewTotal && page !== 0) setPage(Math.max(0, viewTotal - 1));

  // 창을 닫을 때 캐시가 들고 있던 URL을 전부 되돌려준다 (그 URL들의 주인은 캐시다)
  useEffect(() => {
    const cache = cacheRef.current;
    return () => {
      for (const url of cache.values()) URL.revokeObjectURL(url);
      cache.clear();
    };
  }, []);

  // Escape로 닫는다 — 다른 창과 같은 감각. 이 창의 입력은 타이핑 즉시 저장되므로 잃는 것이 없다.
  // 위에 확인창이 겹쳐 뜬 동안에는 그쪽이 먼저 먹는다(공용 스택).
  useEscapeClose(true, () => setPrintOpen(false));

  /** 이 페이지의 인물 대사 컷들을 그림이 비어 있는 귀퉁이로 옮긴다 (얼굴 가림 최소화) */
  const autoPlace = async () => {
    const ok = collectOkImages(project, blobs);
    const byId = new Map(project.story.scenes.map((sc) => [sc.id, sc] as const));
    let moved = 0;
    for (const sceneId of pageIds) {
      const scene = byId.get(sceneId);
      const blob = ok.get(sceneId);
      if (!scene || !blob) continue;
      const isNarr = !scene.speaker || scene.speaker === "narration";
      if (isNarr) continue; // 내레이션은 가로로 눕는 캡션 — 귀퉁이 개념이 없다
      const bmp = await createImageBitmap(blob);
      try {
        const pos = suggestBalloonPos(
          bmp,
          Boolean((scene.webtoon?.caption ?? "").trim()),
          scene.webtoon?.tail,
        );
        patchWebtoon(sceneId, { pos });
        moved += 1;
      } finally {
        bmp.close?.();
      }
    }
    toast(
      moved > 0
        ? `말풍선 ${moved}개를 그림이 빈 쪽으로 옮겼습니다. (꼬리 방향을 정해둔 컷은 인물 반대쪽으로)`
        : "이 페이지에는 옮길 인물 대사가 없습니다 (내레이션은 위/아래로 고르세요).",
      moved > 0 ? "ok" : "info",
    );
  };

  /**
   * 컷 제목 일괄 채우기 — 조판실에서 가장 손이 많이 가는 일이 컷마다 제목을 적는 것이다.
   *
   * 내레이션 컷은 그 문장이 곧 제목감이고, 인물 대사 컷은 «누가 말하는 장면인지»가 제목감이다.
   * 이미 적어둔 제목은 감독의 판단이므로 절대 덮지 않는다.
   */
  const fillCaptions = (all = false) => {
    const byId = new Map(project.story.scenes.map((sc) => [sc.id, sc] as const));
    const targets = all ? order : pageIds;
    let filled = 0;
    for (const sceneId of targets) {
      const scene = byId.get(sceneId);
      if (!scene) continue;
      if ((scene.webtoon?.caption ?? "").trim()) continue; // 이미 적힌 제목은 그대로
      const isNarr = !scene.speaker || scene.speaker === "narration";
      const text = (scene.text ?? "").trim();
      const caption = isNarr
        ? text.slice(0, 14)
        : `${speakerName(project.story, scene)}${text ? "" : " (무언)"}`;
      if (!caption.trim()) continue;
      patchWebtoon(sceneId, { caption: caption.trim() });
      filled += 1;
    }
    toast(
      filled > 0
        ? `컷 제목 ${filled}개를 채웠습니다${all ? " (모든 장)" : ""}. 마음에 안 들면 그대로 고쳐 쓰세요.`
        : "채울 컷이 없습니다 — 이미 제목이 있거나, 제목으로 쓸 문장이 없어요.",
      filled > 0 ? "ok" : "info",
    );
  };

  /** 이 장의 컷 제목을 비운다 — 「채우기」만 있고 되돌릴 길이 ↩ 한 단계뿐이면 시험해보기 어렵다 */
  const clearCaptions = () => {
    const byId = new Map(project.story.scenes.map((sc) => [sc.id, sc] as const));
    let cleared = 0;
    for (const sceneId of pageIds) {
      const scene = byId.get(sceneId);
      if (!scene || !(scene.webtoon?.caption ?? "").trim()) continue;
      patchWebtoon(sceneId, { caption: undefined });
      cleared += 1;
    }
    toast(
      cleared > 0 ? `컷 제목 ${cleared}개를 지웠습니다.` : "이 장에는 지울 제목이 없습니다.",
      cleared > 0 ? "ok" : "info",
    );
  };

  /** 이 컷의 조판 설정을 통째로 비운다 — 칩이 여섯 줄까지 늘어 하나씩 되돌리기 어렵다 */
  const resetCut = (sceneId: string) => {
    updateScene(sceneId, { webtoon: undefined });
    toast("이 컷의 조판 설정을 기본값으로 되돌렸습니다. (↩ 되돌리기로 취소할 수 있어요)", "ok");
  };

  const patchWebtoon = (sceneId: string, patch: Record<string, unknown>) => {
    const scene = project.story.scenes.find((sc) => sc.id === sceneId);
    if (!scene) return;
    updateScene(sceneId, { webtoon: { ...(scene.webtoon ?? {}), ...patch } });
  };

  return (
    <div className="modal-backdrop" onClick={() => setPrintOpen(false)}>
      <div className="printroom" onClick={(e) => e.stopPropagation()}>
        <div className="print-head">
          <h2>🖨 인쇄본 만들기</h2>
          <span className="fine">
            찍어둔 OK 컷 {order.length}개 · 말풍선은 이 앱이 그립니다(크레딧 0)
          </span>
          <span className="spacer" />
          {/* 조판 수정은 이미 대본 되돌리기 스택에 쌓인다(updateScene). 다만 Ctrl+Z 핸들러가
              대본실에만 있어 시사실에서 열면 손이 닿지 않았다 — 여기에 버튼을 둔다. */}
          <button
            className="btn btn-ghost btn-small"
            disabled={undoDepth === 0}
            title="말풍선 자리·꼬리·컷 제목을 되돌립니다 (찍어둔 그림은 건드리지 않아요)"
            onClick={undoScript}
          >
            ↩ 되돌리기{undoDepth > 0 ? ` (${undoDepth})` : ""}
          </button>
          <button className="btn btn-ghost btn-small" onClick={() => setPrintOpen(false)}>
            닫기
          </button>
        </div>

        {order.length === 0 ? (
          <p className="fine print-empty">
            아직 OK 컷이 없습니다. 촬영장에서 먼저 찍어주세요 — 인쇄본은 찍어둔 그림을 그대로
            씁니다.
          </p>
        ) : (
          <div className="print-body">
            <div className="print-side">
              <div className="field">
                <span>조판</span>
                <div className="chiprow">
                  <button
                    type="button"
                    className={`chip chipbtn ${layout === "strip" ? "chip-on" : ""}`}
                    title="컷을 위아래로 쌓습니다 — 스크롤 웹툰 형식, 그림을 자르지 않습니다"
                    onClick={() => {
                      setLayout("strip");
                      setPage((withCover ? 1 : 0) + (withContents ? 1 : 0));
                    }}
                  >
                    ▤ 세로 스트립
                  </button>
                  <button
                    type="button"
                    className={`chip chipbtn ${layout === "grid" ? "chip-on" : ""}`}
                    title="2×2 네 컷 — 정사각으로 잘리므로 컷마다 남길 쪽을 고르세요"
                    onClick={() => {
                      setLayout("grid");
                      setPage((withCover ? 1 : 0) + (withContents ? 1 : 0));
                    }}
                  >
                    ▦ 2×2 그리드
                  </button>
                </div>
              </div>
              <div className="chiprow scalerow">
                <span className="fine">글자</span>
                {(
                  [
                    [0.85, "작게"],
                    [1, "보통"],
                    [1.2, "크게"],
                  ] as [number, string][]
                ).map(([v, label]) => (
                  <button
                    key={label}
                    type="button"
                    className={`chip chipbtn ${textScale === v ? "chip-on" : ""}`}
                    title="말풍선·캡션 글자 크기 — 폰에서 볼 거면 크게"
                    onClick={() => pickScale(v)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="chiprow gutterrow">
                <span className="fine">칸 간격</span>
                {(
                  [
                    [0, "붙임"],
                    [10, "보통"],
                    [22, "넉넉"],
                  ] as [number, string][]
                ).map(([v, label]) => (
                  <button
                    key={label}
                    type="button"
                    className={`chip chipbtn ${gutter === v ? "chip-on" : ""}`}
                    title="컷 사이 간격"
                    onClick={() => pickGutter(v)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="chiprow bandrow">
                <button
                  type="button"
                  className={`chip chipbtn ${chapterBand ? "chip-on" : ""}`}
                  title="장이 시작되는 페이지 맨 위에 장 제목을 큰 띠로 얹습니다 — 연재 합본에서 장 구분이 살아납니다. 「⏎ 새 장에서 시작」 + 컷 제목이 있는 컷에만 나옵니다"
                  onClick={() => pickBand(!chapterBand)}
                >
                  {chapterBand ? "📖 장 제목 띠 ✓" : "📖 장 제목 띠"}
                </button>
                <button
                  type="button"
                  className={`chip chipbtn ${contents ? "chip-on" : ""}`}
                  title="장이 다섯을 넘으면 표지 다음에 목차 한 장을 붙입니다 — 종이에서 장을 찾아갈 수 있게"
                  onClick={() => pickContents(!contents)}
                >
                  {contents ? "🗂 목차 ✓" : "🗂 목차"}
                </button>
              </div>
              <div className="chiprow capnumrow">
                <span className="fine">컷 번호</span>
                {(
                  [
                    [true, "1. 제목"],
                    [false, "제목만"],
                  ] as const
                ).map(([v, label]) => (
                  <button
                    key={label}
                    type="button"
                    className={`chip chipbtn ${capNums === v ? "chip-on" : ""}`}
                    title="컷 제목 앞에 번호를 붙일지 — 만화는 번호 없는 라벨이 흔합니다"
                    onClick={() => pickCapNums(v)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="chiprow paperrow">
                <span className="fine">종이</span>
                {(
                  [
                    ["white", "흰 여백"],
                    ["black", "검은 여백"],
                  ] as const
                ).map(([v, label]) => (
                  <button
                    key={v}
                    type="button"
                    className={`chip chipbtn ${paper === v ? "chip-on" : ""}`}
                    title="컷 사이 여백과 페이지 바탕 색 — 야간 실사 컷은 검은 여백이 어울립니다"
                    onClick={() => pickPaper(v)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="chiprow">
                <button
                  type="button"
                  className={`chip chipbtn ${cover ? "chip-on" : ""}`}
                  title="첫 장에 제목과 표지 컷을 넣습니다 — 촬영장에서 「🖼 표지로」 지정한 컷을 씁니다"
                  onClick={() => setCover((v) => !v)}
                >
                  {cover ? "📔 표지 넣기 ✓" : "📔 표지 없음"}
                </button>
                <button
                  type="button"
                  className={`chip chipbtn ${castPage ? "chip-on" : ""}`}
                  title="맨 뒤에 캐스팅 사진으로 인물 소개 장을 붙입니다 — 단행본 관례"
                  disabled={castCount === 0}
                  onClick={() => setCastPage((v) => !v)}
                >
                  {castPage ? "👥 등장인물 ✓" : "👥 등장인물"}
                </button>
              </div>
              {castCount === 0 && (
                <p className="fine">
                  등장인물 장은 <b>캐스팅 사진이 걸린 배우</b>가 있어야 붙습니다.
                </p>
              )}
              {cover && (
                <p className="fine">
                  표지가 아쉬우면 <b>표지 전용으로 한 컷</b> 찍어보세요 (실측 확인) — 샷을{" "}
                  <b>portrait</b>, 해상도를 <b>1:1 정사각</b>으로 두고 「카메라를 보는」 자세를
                  적으면 표지다운 그림이 나옵니다(실측). 제목 자리는 이 창이 만드니 프롬프트에
                  여백을 요청하지 마세요. 다만 portrait은 배경을 흐리게 날려 «장소»가 거의
                  사라집니다 — 장소를 보여주는 표지라면 full이나 wide로 찍으세요.
                </p>
              )}
              {layout === "grid" && (
                <p className="fine">
                  2×2는 컷을 1:1로 자릅니다. 잘림이 싫으면 촬영장에서 해상도를{" "}
                  <b>1:1 정사각</b>으로 두고 찍으세요 (Seedream 계열, 크레딧은 1K와 같습니다).
                </p>
              )}
              {layout === "strip" && (
                <label className="field">
                  <span>페이지당 컷</span>
                  <select
                    value={perPage}
                    onChange={(e) => {
                      setPerPage(Number(e.target.value));
                      setPage((withCover ? 1 : 0) + (withContents ? 1 : 0));
                    }}
                  >
                    {[2, 3, 4, 5, 6].map((n) => (
                      <option key={n} value={n}>
                        {n}컷
                      </option>
                    ))}
                  </select>
                </label>
              )}

              <button
                className="btn btn-small"
                title="그림에서 가장 비어 있는 귀퉁이를 찾아 말풍선을 옮깁니다 — 얼굴을 덜 가립니다"
                onClick={() => void autoPlace()}
                disabled={pageIds.length === 0}
              >
                🎯 말풍선 자동 배치
              </button>
              <button
                className="btn btn-small"
                disabled={pageIds.length === 0}
                title="이 장의 컷 제목을 한 번에 채웁니다 — 내레이션은 그 문장을, 대사 컷은 화자 이름을 씁니다. 이미 적어둔 제목은 건드리지 않아요"
                onClick={() => fillCaptions(false)}
              >
                🏷 컷 제목 채우기
              </button>
              {viewTotal > 2 && (
                <button
                  className="btn btn-small btn-ghost"
                  title="모든 장의 빈 컷 제목을 한 번에 채웁니다 — 장마다 넘기며 누르지 않아도 되게"
                  onClick={() => fillCaptions(true)}
                >
                  모든 장
                </button>
              )}
              <button
                className="btn btn-small btn-ghost"
                disabled={pageIds.length === 0}
                title="이 장의 컷 제목을 모두 지웁니다 — 채우기가 마음에 안 들 때. 되돌리기(↩)로도 돌아올 수 있어요"
                onClick={clearCaptions}
              >
                제목 지우기
              </button>
              {pageIds.length === 0 && (
                <p className="fine">
                  {isCoverView
                    ? "표지 장입니다 — 제목·부제는 작품 제목에서 만들어지고, 표지 컷은 촬영장의 「🖼 표지로」로 고릅니다."
                    : "등장인물 장입니다 — 캐스팅 사진·이름·외모 메모에서 만들어집니다."}{" "}
                  고칠 컷은 <b>다음 장</b>으로 넘기면 나옵니다.
                </p>
              )}
              <div className="print-cuts">
                {pageIds.map((sceneId, i) => {
                  const scene = project.story.scenes.find((sc) => sc.id === sceneId);
                  if (!scene) return null;
                  const w = scene.webtoon ?? {};
                  const isNarr = !scene.speaker || scene.speaker === "narration";
                  return (
                    <div className="print-cut" key={sceneId}>
                      <div className="card-head">
                        <span className="chip chip-strong">#{cutNoBase + i + 1}</span>
                        <span className="chip">{sceneId}</span>
                        {isNarr && <span className="chip">내레이션</span>}
                        <span className="spacer" />
                        {Object.values(w).some((v) => v !== undefined) && (
                          <button
                            className="btn btn-ghost btn-small"
                            title="이 컷의 조판 설정(제목·말풍선·꼬리·효과선·크롭·글자·장 나누기)을 모두 기본값으로 되돌립니다"
                            onClick={() => resetCut(sceneId)}
                          >
                            ↺ 기본값
                          </button>
                        )}
                      </div>
                      <input
                        className="print-caption"
                        value={w.caption ?? ""}
                        placeholder={`컷 제목 (비우면 라벨 없음 · 앞에 「${cutNoBase + i + 1}.」이 붙습니다)`}
                        onChange={(e) => patchWebtoon(sceneId, { caption: e.target.value })}
                      />
                      <input
                        className="print-line"
                        value={w.line ?? ""}
                        placeholder={scene.text ? `말풍선 대사 (기본: ${scene.text.slice(0, 18)}…)` : "말풍선 대사"}
                        onChange={(e) => patchWebtoon(sceneId, { line: e.target.value })}
                      />
                      {isNarr ? (
                        <div className="chiprow">
                          <span className="fine" title="인물 대사로 바꾸려면 대본실에서 이 컷의 화자를 지정하세요">
                            캡션 자리
                          </span>
                          {(
                            [
                              ["tl", "↑ 위"],
                              ["bl", "↓ 아래"],
                            ] as [BalloonPos, string][]
                          ).map(([pos, label]) => (
                            <button
                              key={pos}
                              type="button"
                              className={`chip chipbtn ${(w.pos ?? "bl") === pos ? "chip-on" : ""}`}
                              title="내레이션은 가로로 눕는 캡션 — 위/아래만 고릅니다"
                              onClick={() => patchWebtoon(sceneId, { pos })}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <div className="chiprow">
                          {(["tl", "tr", "bl", "br"] as BalloonPos[]).map((pos) => (
                            <button
                              key={pos}
                              type="button"
                              className={`chip chipbtn ${(w.pos ?? "tr") === pos ? "chip-on" : ""}`}
                              title="말풍선 자리 — 얼굴을 가리지 않는 쪽으로"
                              onClick={() => patchWebtoon(sceneId, { pos })}
                            >
                              {POS_LABEL[pos]}
                            </button>
                          ))}
                          {(["say", "think", "shout"] as BalloonKind[]).map((kind) => (
                            <button
                              key={kind}
                              type="button"
                              className={`chip chipbtn ${(w.kind ?? "say") === kind ? "chip-on" : ""}`}
                              onClick={() => patchWebtoon(sceneId, { kind })}
                            >
                              {KIND_LABEL[kind]}
                            </button>
                          ))}
                        </div>
                      )}
                      <div className="chiprow fxrow">
                        <span className="fine" title="정적인 사진에 만화식 동세를 얹습니다 — 액션·충격 컷에">
                          효과선
                        </span>
                        {(
                          [
                            [undefined, "없음"],
                            ["speed", "≡ 속도"],
                            ["focus", "✳ 집중"],
                            ["flash", "✺ 섬광"],
                          ] as [WebtoonFx | undefined, string][]
                        ).map(([fx, label]) => (
                          <button
                            key={label}
                            type="button"
                            className={`chip chipbtn ${(w.fx ?? undefined) === fx ? "chip-on" : ""}`}
                            onClick={() => patchWebtoon(sceneId, { fx })}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                      {!isNarr && (
                        <div className="chiprow tailrow">
                          <span className="fine">꼬리</span>
                          {(
                            [
                              ["l", "◀ 왼쪽"],
                              ["c", "가운데"],
                              ["r", "오른쪽 ▶"],
                              ["none", "없음"],
                            ] as const
                          ).map(([v, label]) => (
                            <button
                              key={v}
                              type="button"
                              className={`chip chipbtn ${(w.tail ?? "c") === v ? "chip-on" : ""}`}
                              title="말풍선 꼬리가 가리킬 쪽 — 인물이 있는 쪽으로 두세요. 「없음」은 화면 밖 화자·독백"
                              onClick={() => patchWebtoon(sceneId, { tail: v })}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      )}
                      <div className="chiprow cutscalerow">
                        <span className="fine">이 컷 글자</span>
                        {(
                          [
                            [0.8, "작게"],
                            [1, "보통"],
                            [1.25, "크게"],
                          ] as const
                        ).map(([v, label]) => (
                          <button
                            key={label}
                            type="button"
                            className={`chip chipbtn ${(w.textScale ?? 1) === v ? "chip-on" : ""}`}
                            title="이 컷의 말풍선 글자만 조절합니다 — 긴 대사 한 컷 때문에 페이지 전체를 줄이지 않게"
                            onClick={() =>
                              patchWebtoon(sceneId, { textScale: v === 1 ? undefined : v })
                            }
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                      <div className="chiprow gorow">
                        <button
                          type="button"
                          className="chip chipbtn"
                          title="이 컷을 촬영장에서 엽니다 — 다시 찍거나 다른 그림을 걸 때. 조판실에서는 크레딧을 쓰지 않습니다"
                          onClick={() => {
                            setPrintOpen(false);
                            setTab("stage");
                            // 탭이 그려진 뒤에 스크롤해야 그 카드가 화면에 있다
                            window.setTimeout(() => {
                              document
                                .getElementById(`stagecut-${sceneId}`)
                                ?.scrollIntoView({ block: "center", behavior: "smooth" });
                            }, 220);
                          }}
                        >
                          🎬 촬영장에서 열기
                        </button>
                      </div>
                      <div className="chiprow breakrow">
                        <button
                          type="button"
                          className={`chip chipbtn ${w.pageBreak ? "chip-on" : ""}`}
                          title="이 컷부터 새 장에서 시작합니다 — 절정 컷을 페이지 첫 칸에 두면 넘기는 손맛이 생깁니다"
                          onClick={() =>
                            patchWebtoon(sceneId, { pageBreak: w.pageBreak ? undefined : true })
                          }
                        >
                          {w.pageBreak ? "⏎ 새 장에서 시작 ✓" : "⏎ 새 장에서 시작"}
                        </button>
                      </div>
                      {layout === "grid" && (
                        <div className="chiprow croprow">
                          <span className="fine">자를 쪽</span>
                          {(["left", "center", "right"] as const).map((c) => (
                            <button
                              key={c}
                              type="button"
                              className={`chip chipbtn ${(w.crop ?? "center") === c ? "chip-on" : ""}`}
                              onClick={() => patchWebtoon(sceneId, { crop: c })}
                            >
                              {c === "left" ? "왼쪽" : c === "center" ? "가운데" : "오른쪽"}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="print-preview">
              <div className="print-pager">
                <button
                  className="btn btn-ghost btn-small"
                  disabled={page === 0}
                  onClick={() => setPage((v) => Math.max(0, v - 1))}
                >
                  ‹ 이전 장
                </button>
                <span className="fine">
                  {page + 1} / {viewTotal} 장
                  {isCoverView
                    ? " · 표지"
                    : isContentsView
                      ? " · 목차"
                      : isCastView
                        ? " · 등장인물"
                        : ""}{" "}
                  {busy && "· 그리는 중…"}
                </span>
                <button
                  className="btn btn-ghost btn-small"
                  disabled={page >= viewTotal - 1}
                  onClick={() => setPage((v) => Math.min(viewTotal - 1, v + 1))}
                >
                  다음 장 ›
                </button>
              </div>
              {/* 장 바로가기 — 「하나씩 넘기기»가 불편한 것이 문제였다. 썸네일 격자는 모든 장을
                  미리 그려야 해서(20장이면 30초) 오히려 느려진다. 캐시가 있으니 점프는 즉시다. */}
              {viewTotal > 2 && (
                <div className="chiprow pagejump">
                  {Array.from({ length: viewTotal }, (_, i) => {
                    const isCov = withCover && i === 0;
                    const isToc = withContents && i === (withCover ? 1 : 0);
                    const isCst = withCast && i === viewTotal - 1;
                    const label = isCov
                      ? "📔"
                      : isToc
                        ? "🗂"
                        : isCst
                          ? "👥"
                          : String(i + 1 - (withCover ? 1 : 0) - (withContents ? 1 : 0));
                    return (
                      <button
                        key={i}
                        type="button"
                        className={`chip chipbtn ${page === i ? "chip-on" : ""}`}
                        title={
                          isCov
                            ? "표지"
                            : isToc
                              ? "목차"
                              : isCst
                                ? "등장인물"
                                : `${i + 1 - (withCover ? 1 : 0) - (withContents ? 1 : 0)}번째 본문 장`
                        }
                        onClick={() => setPage(i)}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              )}
              {err && <p className="ngnote">{err}</p>}
              {previewUrl ? (
                <img
                  className="print-sheet"
                  src={previewUrl}
                  alt="인쇄본 미리보기"
                  title="누르면 원본 크기로 엽니다 — 폰에서 글자를 확인할 때"
                  onClick={() => window.open(previewUrl, "_blank", "noopener")}
                />
              ) : (
                <p className="fine">미리보기를 그리고 있습니다…</p>
              )}
              <p className="fine">
                내보내기 — 지금 설정({layout === "grid" ? "2×2" : "세로 스트립"} ·{" "}
                {paper === "black" ? "검은 여백" : "흰 여백"}
                {cover ? " · 표지" : ""}
                {withContents ? " · 목차" : ""}
                {withCast ? " · 등장인물" : ""})으로 <b>{viewTotal}장</b>이 나옵니다. 크레딧은
                들지 않아요.
                {hereChapter && (
                  <>
                    {" "}
                    「{hereChapter.title}」만 낼 수도 있습니다(표지·목차 없이 그 장의 쪽만) — 연재는
                    화마다 파일 하나로 올리니까요.
                  </>
                )}
              </p>
              <div className="print-exports">
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={() =>
                  void exportWebtoon({
                    layout,
                    perPage: per,
                    cover,
                    textScale,
                    gutter,
                    castPage,
                    paper,
                    captionNumbers: capNums,
                    chapterBand,
                    contents,
                  })
                }
              >
                전체 {viewTotal}장 PNG로 내보내기
              </button>
              <button
                className="btn"
                disabled={busy}
                title="장들을 세로로 이어 한 장으로 만듭니다 — 웹툰 플랫폼은 긴 이미지 한 장을 받습니다. 너무 길면 나눠서 여러 장이 됩니다"
                onClick={() =>
                  void exportWebtoon({
                    layout,
                    perPage: per,
                    cover,
                    textScale,
                    gutter,
                    castPage,
                    paper,
                    captionNumbers: capNums,
                    chapterBand,
                    contents,
                    strip: true,
                  })
                }
              >
                📜 긴 스크롤 한 장으로
              </button>
              <button
                className="btn"
                disabled={busy}
                title="장들을 PDF 한 파일로 묶습니다 — 인쇄소에 넘기거나 메일에 붙일 때"
                onClick={() =>
                  void exportWebtoon({
                    layout,
                    perPage: per,
                    cover,
                    textScale,
                    gutter,
                    castPage,
                    paper,
                    captionNumbers: capNums,
                    chapterBand,
                    contents,
                    pdf: true,
                  })
                }
              >
                📄 PDF 한 파일로
              </button>
              {/* 장 단위 산출물 셋 — 「전체」와 눈으로 갈리게 한 덩어리로 묶는다
                  (폭은 이미 넘치지 않는다: 폰 390px에서 일곱 개가 줄바꿈으로 다 들어감을 실측) */}
              <span className="print-exports-chap">
              {hereChapter && (
                <button
                  className="btn"
                  disabled={busy}
                  title={`지금 보고 있는 쪽이 속한 장(챕터)만 내보냅니다 — 표지·목차·등장인물 장은 빼고 「${hereChapter.title}」의 쪽만 나옵니다. 연재는 화마다 파일 하나로 올리니까요`}
                  onClick={() =>
                    void exportWebtoon({
                      layout,
                      perPage: per,
                      cover,
                      textScale,
                      gutter,
                      castPage,
                      paper,
                      captionNumbers: capNums,
                      chapterBand,
                      contents,
                      onlyChapter: hereChapter.firstId,
                    })
                  }
                >
                  📖 「{hereChapter.title}」만
                </button>
              )}
              {/* 연재 업로드의 실제 형태는 «그 장의 긴 스크롤 한 장»이다 — 플랫폼은 긴 이미지를 받는다 */}
              {hereChapter && (
                <button
                  className="btn"
                  disabled={busy}
                  title={`「${hereChapter.title}」의 쪽만 세로로 이어 한 장으로 만듭니다 — 웹툰 플랫폼에 화마다 올릴 때 씁니다`}
                  onClick={() =>
                    void exportWebtoon({
                      layout,
                      perPage: per,
                      cover,
                      textScale,
                      gutter,
                      castPage,
                      paper,
                      captionNumbers: capNums,
                      chapterBand,
                      contents,
                      onlyChapter: hereChapter.firstId,
                      strip: true,
                    })
                  }
                >
                  📜 「{hereChapter.title}」만 긴 스크롤
                </button>
              )}
              {/* 장별 PDF — 인쇄소·메일에 «이번 화»만 넘길 때. 책 한 권 PDF와 따로 있어야 한다 */}
              {hereChapter && (
                <button
                  className="btn"
                  disabled={busy}
                  title={`「${hereChapter.title}」의 쪽만 PDF 한 파일로 묶습니다 — 인쇄소·메일에 이번 화만 넘길 때`}
                  onClick={() =>
                    void exportWebtoon({
                      layout,
                      perPage: per,
                      cover,
                      textScale,
                      gutter,
                      castPage,
                      paper,
                      captionNumbers: capNums,
                      chapterBand,
                      contents,
                      onlyChapter: hereChapter.firstId,
                      pdf: true,
                    })
                  }
                >
                  📄 「{hereChapter.title}」만 PDF
                </button>
              )}
              </span>
              {viewTotal >= 4 && (
                <button
                  className="btn"
                  disabled={busy}
                  title="모든 장을 한 장에 축소해 나열합니다 — 글자를 읽는 게 아니라 연재 전체의 리듬(어느 장이 길고 짧은지)을 한눈에 보는 시트입니다"
                  onClick={() =>
                    void exportWebtoon({
                      layout,
                      perPage: per,
                      cover,
                      textScale,
                      gutter,
                      castPage,
                      paper,
                      captionNumbers: capNums,
                      chapterBand,
                      contents,
                      indexSheet: true,
                    })
                  }
                >
                  🗒 인덱스 시트
                </button>
              )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
