/**
 * 오늘 밤의 콜시트 — 촬영 현장의 콜시트는 「오늘 찍을 것」 한 장이다.
 *
 * 정보는 이미 앱 곳곳에 있다(촬영 큐·조감독 리포트·필름캔 리마인더). 흩어져 있어서
 * 앱을 열 때마다 «어디서 이어가지»를 감독이 매번 판단해야 했다 — 그 판단을 앱이 대신한다.
 *
 * 톤 규칙: 「해야 한다」가 아니라 「여기서 이어갈 수 있어요」. 남은 개수를 붉게 강조하지 않고,
 * 할 일이 없으면 배웅하는 문장으로 바뀐다. 연속 출석·스트릭 같은 압박 장치는 넣지 않는다.
 */
import { useEffect, useMemo, useState } from "react";
import { useStudio } from "../../store/useStudio";
import { chapterRanges } from "../../lib/chapters";
import { continuityReport } from "../../lib/continuity";
import { countCutStatus, emptyCut } from "../../types";
import { useProject } from "../hooks";

interface Line {
  key: string;
  icon: string;
  text: string;
  /** 누르면 데려갈 곳 */
  go: () => void;
  goLabel: string;
}

export function CallSheet() {
  const project = useProject();
  const setTab = useStudio((s) => s.setTab);
  const setStageChapter = useStudio((s) => s.setStageChapter);
  const enterScreening = useStudio((s) => s.enterScreening);
  const startBatch = useStudio((s) => s.startBatch);
  const startPrint = useStudio((s) => s.setPrintOpen);
  const troupe = useStudio((s) => s.troupe);
  const projectList = useStudio((s) => s.projectList);
  const loadTroupe = useStudio((s) => s.loadTroupe);
  const counts = countCutStatus(project);
  // 마운트 시각 기준 — 렌더 중 Date.now()는 순수성을 깬다 (탭을 오갈 때마다 갱신된다)
  const [now] = useState(() => Date.now());
  const setAdvancedOpen = useStudio((s) => s.setAdvancedOpen);
  /** 저장소 사용량(MB) — 한 번만 잰다. 못 재는 브라우저에서는 이 줄이 아예 나오지 않는다. */
  const [storageMb, setStorageMb] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const est = await navigator.storage?.estimate?.();
        if (alive && est?.usage) setStorageMb(est.usage / 1024 / 1024);
      } catch {
        /* 못 재면 조용히 넘어간다 — 콜시트의 일이 아니다 */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // 배우단은 선반을 열 때만 읽혔다 — 콜시트가 배우단을 말하려면 여기서도 한 번 읽어야 한다.
  // (set은 await 뒤에서 일어나므로 effect 동기 구간의 상태 갱신이 아니다)
  useEffect(() => {
    void loadTroupe();
  }, [loadTroupe]);

  const lines = useMemo(() => {
    const out: Line[] = [];
    const issues = continuityReport(project);
    const warns = issues.filter((i) => i.severity === "warn");

    // 1) 얼굴 없는 배우 — 촬영보다 먼저 해결해야 얼굴이 흔들리지 않는다
    const facelessWarn = warns.filter((w) => /얼굴 없음|ref 파일명/.test(w.message));
    if (facelessWarn.length > 0) {
      out.push({
        key: "faceless",
        icon: "🎭",
        text: `캐스팅 사진이 없는 배우 ${facelessWarn.length}명 — 먼저 걸어두면 얼굴이 흔들리지 않아요`,
        go: () => setTab("script"),
        goLabel: "캐스팅으로",
      });
    }

    // 2) 지연된 컷 — NG가 아니라 아직 만드는 중일 수 있다 (회수 가능)
    const delayed = project.story.scenes.filter((sc) => project.cuts[sc.id]?.delayed);
    if (delayed.length > 0) {
      out.push({
        key: "delayed",
        icon: "⏳",
        text: `생성이 지연된 컷 ${delayed.length}개 — 「결과 찾아오기」로 무과금 회수할 수 있어요`,
        go: () => setTab("stage"),
        goLabel: "촬영장으로",
      });
    }

    // 3) 대기 컷 — 오늘 찍을 것
    if (counts.wait > 0) {
      out.push({
        key: "wait",
        icon: "🎬",
        text: `아직 찍지 않은 컷 ${counts.wait}개`,
        go: () => void startBatch("pending"),
        goLabel: "촬영 시작",
      });
    }

    // 4) NG 컷 — 다시 찍을 것
    if (counts.ng > 0) {
      out.push({
        key: "ng",
        icon: "🔁",
        text: `NG 판정된 컷 ${counts.ng}개`,
        go: () => void startBatch("ng"),
        goLabel: "NG만 다시",
      });
    }

    // 4.3) 장별 진행 — 연재에서는 «어느 장이 덜 찍혔나»가 오늘의 판단이다.
    //      장이 둘 이상이고 찍을 게 남아 있을 때만, 한 줄로 «가장 덜 된 장»을 가리킨다.
    if (counts.wait > 0) {
      const chapters = chapterRanges(project.story.scenes);
      if (chapters.length >= 2) {
        const stat = chapters.map((c) => ({
          title: c.title,
          firstId: c.firstId,
          wait: c.ids.filter((id) => (project.cuts[id]?.status ?? "wait") === "wait").length,
          total: c.ids.length,
        }));
        const behind = stat.filter((c) => c.wait > 0);
        // 마지막 한 장만 남았을 때는 «남은 장 나열»보다 «끝이 보인다»가 힘이 된다.
        // 연재를 오래 끌고 온 뒤의 한 줄이므로 다른 안내들보다 앞에 세운다.
        if (behind.length === 1 && chapters.length >= 2) {
          const last = behind[0];
          out.unshift({
            key: "lastchapter",
            icon: "🏁",
            text: `「${last.title}」만 남았습니다 — ${last.total}컷 중 ${last.wait}컷을 찍으면 이 작품은 끝납니다.`,
            go: () => {
              setStageChapter(last.firstId);
              setTab("stage");
            },
            goLabel: `${last.title} 찍기`,
          });
        } else if (behind.length > 0) {
          const worst = behind.reduce((a, b) => (b.wait > a.wait ? b : a));
          out.push({
            key: "chapters",
            icon: "📖",
            text: `장별로 남은 컷 — ${behind
              .slice(0, 4)
              .map((c) => `${c.title} ${c.wait}`)
              .join(" · ")}${behind.length > 4 ? " …" : ""} (가장 많이 남은 건 ${worst.title})`,
            // 「가장 많이 남은 장」을 가리켜 놓고 전체 촬영장으로 보내면 다시 그 장을 찾아야 한다
            go: () => {
              setStageChapter(worst.firstId);
              setTab("stage");
            },
            goLabel: `${worst.title}만 보기`,
          });
        }
      }
    }

    // 4.5) 카메라 고정 + reuse — v0.45까지 앱이 권했던 조합인데 실제로는 자세가 바뀌지 않는다.
    //      찍기 전에 알아야 크레딧이 헛되지 않으므로 대기·NG 다음에 바로 알린다.
    const holdReuse = warns.filter((w) => /카메라 고정과 배경 reuse/.test(w.message));
    if (holdReuse.length > 0) {
      out.push({
        key: "holdreuse",
        icon: "🔒",
        text: `카메라 고정 + 배경 reuse가 겹친 컷 ${holdReuse.length}개 — reuse는 그림을 복사해서 자세가 안 바뀝니다`,
        go: () => setTab("script"),
        goLabel: "대본실으로",
      });
    }

    // 4.7) 컷씬으로 지정만 해두고 영상화하지 않은 컷 — 지정은 «하겠다는 표시»이므로 잊기 쉽다.
    //      크레딧이 드는 일이라 재촉하지 않고, 남아 있다는 사실만 알린다.
    const pendingCutscene = project.story.scenes.filter((sc) => {
      const cut = project.cuts[sc.id];
      return cut?.cutscene && cut.status === "ok" && !cut.videoKey;
    });
    if (pendingCutscene.length > 0) {
      out.push({
        key: "cutscene",
        icon: "🎬",
        // 연재가 길어지면 지정만 해둔 컷이 쌓인다 — 한 컷 값이 아니라 «총액»을 말해야 판단이 된다
        text:
          pendingCutscene.length === 1
            ? "컷씬으로 지정해둔 컷 1개가 아직 영상이 아니에요 (약 30크레딧)"
            : `컷씬으로 지정해둔 컷 ${pendingCutscene.length}개가 아직 영상이 아니에요 (다 만들면 약 ${pendingCutscene.length * 30}크레딧)`,
        go: () => setTab("stage"),
        goLabel: "촬영장으로",
      });
    }

    // 5) 끊어진 연결 — 시사가 중간에 멈춘다
    const brokenLinks = warns.filter((w) => /next가 가리키는|선택지가 가리키는|없는 컷/.test(w.message));
    if (brokenLinks.length > 0) {
      out.push({
        key: "links",
        icon: "🔗",
        text: `이어지지 않는 연결 ${brokenLinks.length}곳 — 시사가 거기서 멈춥니다`,
        go: () => setTab("script"),
        goLabel: "대본실으로",
      });
    }

    // 6) 필름캔 — 브라우저 저장소는 영원하지 않다
    if (counts.ok > 0) {
      const last = project.lastExportAt;
      const days = last ? Math.floor((now - last) / 86_400_000) : null;
      if (!last) {
        out.push({
          key: "backup",
          icon: "🎞",
          text: "이 작품은 아직 필름캔(ZIP)이 없어요",
          go: () => setTab("script"),
          goLabel: "내보내기로",
        });
      } else if (days !== null && days >= 3) {
        out.push({
          key: "backup",
          icon: "🎞",
          text: `마지막 필름캔이 ${days}일 전이에요`,
          go: () => setTab("script"),
          goLabel: "내보내기로",
        });
      }
    }

    // 6.5) 작품이 여러 편 쌓였는데 필름캔 없는 작품이 있으면 «한 번에 챙기는 길»을 알려준다.
    //      작품마다 따로 내보내라고 잔소리하지 않는다 — 한 줄로 끝나는 방법만 말한다.
    const neverExported = projectList.filter((e) => !e.lastExportAt && e.okCount > 0).length;
    if (projectList.length >= 3 && neverExported >= 2) {
      out.push({
        key: "bulk",
        icon: "🎞",
        text: `필름캔 기록이 없는 작품 ${neverExported}편 — 「최근 프로젝트 → 모두 내보내기」로 한 번에 챙길 수 있어요`,
        go: () => setTab("script"),
        goLabel: "목록 열기",
      });
    }

    // 7) 배우단 배웅 — 얼굴을 어렵게 구했는데 이 작품에서만 살고 사라지는 배우가 있다.
    //    «해야 할 일»이 아니라 «데려갈 수 있다»는 안내라서, 촬영이 급할 땐(대기·NG) 말하지 않는다.
    if (counts.wait === 0 && counts.ng === 0) {
      const casted = new Set(troupe.map((a) => a.name));
      const unsaved = project.story.characters.filter(
        (c) => c.ref && project.charAssets[c.ref] && !casted.has(c.name),
      );
      if (unsaved.length > 0) {
        out.push({
          key: "troupe",
          icon: "⭐",
          text:
            unsaved.length === 1
              ? `「${unsaved[0].name}」의 얼굴은 이 작품에만 있어요 — 배우단에 올리면 다음 작품에도 데려갑니다`
              : `배우단에 없는 얼굴 ${unsaved.length}명 — 올려두면 다음 작품에도 데려갑니다`,
          go: () => setTab("script"),
          goLabel: "캐스팅으로",
        });
      }
    }

    // 8) 인쇄본 — 찍어둔 컷이 제법 쌓였는데 한 번도 조판해보지 않았다면 그런 게 있다고만 알린다
    const hasWebtoon = project.story.scenes.some((sc) => {
      const w = sc.webtoon;
      return Boolean(
        w && (w.caption || w.line || w.fx || w.pos || w.kind || w.crop || w.tail || w.pageBreak),
      );
    });
    if (counts.ok >= 4 && counts.wait === 0 && !hasWebtoon) {
      out.push({
        key: "print",
        icon: "🖨",
        text: "찍은 컷을 만화처럼 조판해 한 장으로 뽑을 수 있어요",
        go: () => startPrint(true),
        goLabel: "인쇄본 열기",
      });
    }

    // 9) 이어볼 곳 — 찍은 게 있으면 시사실로 배웅
    if (counts.ok > 0 && counts.wait === 0 && counts.ng === 0) {
      const cursor = project.currentSceneId;
      const cut = cursor ? (project.cuts[cursor] ?? emptyCut()) : null;
      out.push({
        key: "screen",
        icon: "▶",
        text:
          cursor && cut?.status === "ok"
            ? `${cursor}까지 봤어요 — 이어서 볼까요?`
            : "오늘 밤 촬영분을 처음부터 볼 수 있어요",
        go: enterScreening,
        goLabel: "시사실로",
      });
    }
    /**
     * 10) 저장소 — 연재를 오래 하면 그림이 쌓인다(실측: 컷 한 장 ≈ 320KB, 캐스팅 사진 ≈ 2.6MB.
     *     20편 × 12컷 + 테이크면 수백 MB). 청소는 「고급」 안에만 있어 눈에 띄지 않으므로,
     *     실제로 쌓였을 때만(200MB 넘을 때) 맨 아래에 문 하나를 만들어 준다. 재촉하지 않는다.
     */
    if (storageMb !== null && storageMb > 200) {
      out.push({
        key: "storage",
        icon: "💾",
        text: `저장소를 ${storageMb.toFixed(0)}MB 쓰고 있어요 — 아무 컷도 안 쓰는 그림은 청소할 수 있습니다`,
        go: () => setAdvancedOpen(true),
        goLabel: "고급 열기",
      });
    }
    return out;
  }, [
    project,
    counts,
    now,
    troupe,
    projectList,
    storageMb,
    setTab,
    setStageChapter,
    setAdvancedOpen,
    enterScreening,
    startBatch,
    startPrint,
  ]);

  const allClear = lines.length === 0;
  /**
   * 콜시트는 «오늘 밤 한 장»이다. 줄이 늘어 아홉 가지까지 나오면 그 약속이 깨진다.
   * 위 다섯 줄만 펼쳐 두고 나머지는 접는다 — 목록의 순서가 곧 급한 순서다.
   */
  const HEAD = 5;
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? lines : lines.slice(0, HEAD);
  const hidden = lines.length - shown.length;

  return (
    <section className="panel callsheet">
      <div className="panel-head">
        <h2>
          오늘 밤의 콜시트{" "}
          <span className="fine">
            {allClear ? "걸리는 것 없음" : `이어갈 일 ${lines.length}가지`}
          </span>
        </h2>
      </div>
      {allClear ? (
        <p className="fine">
          오늘 밤은 걸리는 것이 없습니다 — 대본을 더 써도 좋고, 시사실에서 지금까지 찍은 것을
          처음부터 봐도 좋아요.
        </p>
      ) : (
        <ul className="cs-list">
          {shown.map((l) => (
            <li key={l.key} className="cs-line">
              <span className="cs-icon">{l.icon}</span>
              <span className="cs-text">{l.text}</span>
              <button className="btn btn-small btn-ghost" onClick={l.go}>
                {l.goLabel}
              </button>
            </li>
          ))}
          {hidden > 0 && (
            <li className="cs-line cs-more">
              <span className="cs-icon">⋯</span>
              <span className="cs-text fine">덜 급한 일 {hidden}가지가 더 있어요</span>
              <button className="btn btn-small btn-ghost" onClick={() => setShowAll(true)}>
                모두 보기
              </button>
            </li>
          )}
          {showAll && lines.length > HEAD && (
            <li className="cs-line cs-more">
              <span className="cs-icon">⋯</span>
              <span className="cs-text fine">위 {HEAD}가지만 보기</span>
              <button className="btn btn-small btn-ghost" onClick={() => setShowAll(false)}>
                접기
              </button>
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
