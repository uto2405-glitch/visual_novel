/** 촬영장 — 카메라, 큐, 컷 카드, 페이스 체크 모니터. 「전부 다시」는 없다. */
import { useState } from "react";
import { useStudio } from "../../store/useStudio";
import { chapterRanges } from "../../lib/chapters";
import { creditsOf, modelById } from "../../lib/makefun";
import { isApiCut, type SizeKey } from "../../types";
import { CameraPanel } from "./CameraPanel";
import { QueuePanel } from "./QueuePanel";
import { CutCard } from "./CutCard";
import { FaceCheck } from "./FaceCheck";

type StageFilter = "all" | "wait" | "ng" | "cutscene" | "custom";

export function Stage() {
  const project = useStudio((s) => s.project);
  const [faceCheckId, setFaceCheckId] = useState<string | null>(null);
  const [rawFilter, setFilter] = useState<StageFilter>("all");
  // 연재에서는 «3장만 골라 찍기»가 실제 흐름이다 — 장이 여럿일 때만 이 줄이 나온다.
  // 고른 장은 스토어가 들고 있다 — 콜시트의 「장별로 남은 컷」이 그 장으로 데려올 수 있게.
  const chapter = useStudio((st) => st.stageChapter);
  const setChapter = useStudio((st) => st.setStageChapter);
  const startBatch = useStudio((st) => st.startBatch);
  const batchRunning = useStudio((st) => st.batch?.running);
  const updateScene = useStudio((st) => st.updateScene);
  const promptText = useStudio((st) => st.promptText);
  const clearTakesMany = useStudio((st) => st.clearTakesMany);
  const resetPromptsAll = useStudio((st) => st.resetPromptsAll);

  if (!project) {
    return (
      <div className="room">
        <p className="notice">촬영할 프로젝트가 없습니다. 대본실에서 먼저 대본을 열어주세요.</p>
      </div>
    );
  }

  const navFaceCheck = (dir: number) => {
    if (!faceCheckId) return;
    const scenes = project.story.scenes;
    const idx = scenes.findIndex((sc) => sc.id === faceCheckId);
    if (idx < 0) return;
    const next = scenes[(idx + dir + scenes.length) % scenes.length];
    setFaceCheckId(next.id);
  };

  /**
   * 장 구간 — 「⏎ 새 장에서 시작」이 켜진 컷에서 다음 장이 열린다고 본다.
   * 조판(인쇄본)과 같은 기준을 쓰므로 «인쇄본의 3장»과 «촬영장의 3장»이 어긋나지 않는다.
   */
  const chapters = chapterRanges(project.story.scenes);
  const hasChapters = chapters.length >= 2;
  // 고른 장은 «첫 컷 id»로 기억한다 — 장 이름을 고쳐도 고른 장이 그대로 남는다
  const chosen = chapters.find((c) => c.firstId === chapter);
  // 고른 장이 사라졌으면(작품 전환·장 합치기) 필터를 스스로 푼다 — 빈 촬영장으로 보이면 안 된다
  if (chapter !== "" && !chosen) setChapter("");

  /* 프롬프트를 직접 고친 컷 수 — ✎ 필터는 이 수가 0보다 클 때만 존재한다.
     마지막 컷을 되돌리면 칩이 사라지는데 고른 필터가 그대로 남아, 빈 촬영장에
     「이 컷들은 프롬프트를 직접 고쳐 두어…」라는 이제 거짓인 문장만 걸려 있었다(스위트가 잡았다).
     상태를 효과로 고치지 않고(그건 훅 순서와 연쇄 렌더를 부른다) «파생»으로 읽는다 —
     사라진 필터에 서 있으면 전체로 본다. */
  const customCount = project.story.scenes.filter((sc) =>
    (project.cuts[sc.id]?.customPrompt ?? "").trim(),
  ).length;
  const filter: StageFilter = rawFilter === "custom" && customCount === 0 ? "all" : rawFilter;

  const matches = (id: string): boolean => {
    if (chapter && !chosen?.ids.includes(id)) return false;
    const cut = project.cuts[id];
    if (filter === "wait") return (cut?.status ?? "wait") === "wait";
    if (filter === "ng") return cut?.status === "ng";
    if (filter === "cutscene") return Boolean(cut?.cutscene || cut?.videoKey);
    // 직접 쓴 프롬프트 — 이 컷들은 조립을 건너뛰므로 화풍·배우·장소 변경이 닿지 않는다
    if (filter === "custom") return Boolean((cut?.customPrompt ?? "").trim());
    return true;
  };
  const counts = {
    all: project.story.scenes.length,
    wait: project.story.scenes.filter((sc) => (project.cuts[sc.id]?.status ?? "wait") === "wait")
      .length,
    ng: project.story.scenes.filter((sc) => project.cuts[sc.id]?.status === "ng").length,
    cutscene: project.story.scenes.filter((sc) => {
      const c = project.cuts[sc.id];
      return Boolean(c?.cutscene || c?.videoKey);
    }).length,
    custom: customCount,
  };
  const visible = project.story.scenes
    .map((scene, i) => ({ scene, i }))
    .filter(({ scene }) => matches(scene.id));

  const FILTERS: { id: StageFilter; label: string }[] = [
    { id: "all", label: `전체 ${counts.all}` },
    { id: "wait", label: `대기 ${counts.wait}` },
    { id: "ng", label: `NG ${counts.ng}` },
    { id: "cutscene", label: `🎬 컷씬 ${counts.cutscene}` },
    /* 프롬프트를 직접 고친 컷 — 그 컷들은 조립을 건너뛰어 화풍·배우·장소 변경이 닿지 않는다.
       예전에는 그런 컷을 세거나 골라낼 방법이 없어, 60컷 편에서 어느 컷이 굳었는지 알 수 없었다. */
    ...(counts.custom > 0
      ? [{ id: "custom" as StageFilter, label: `✎ 직접 쓴 ${counts.custom}` }]
      : []),
  ];

  return (
    <div className="room">
      <CameraPanel />
      <QueuePanel />
      <div className="stagefilter">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            className={`chip chipbtn ${filter === f.id ? "chip-on" : ""}`}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
        {filter !== "all" && visible.length === 0 && (
          <span className="fine">이 필터에 걸리는 컷이 없습니다.</span>
        )}
        {/* 직접 쓴 프롬프트를 한 번에 되돌리는 문 — 화풍을 갈아입힌 뒤 «닿지 않는 컷»을 푸는 자리.
            ✎ 필터를 골랐을 때만 보인다(평소에 재촉할 일은 아니다). 확인창은 슬라이스가 세운다. */}
        {filter === "custom" && counts.custom > 0 && (
          <button
            className="chip chipbtn stage-sweep"
            title={`컷 ${counts.custom}개의 직접 쓴 프롬프트를 버리고 대본에서 다시 조립합니다 — 화풍·배우 외모·장소·카메라 고정이 다시 흐릅니다`}
            onClick={() => void resetPromptsAll()}
          >
            ↩ 전부 기본 프롬프트로 ({counts.custom})
          </button>
        )}
        {filter === "custom" && (
          <span className="fine">
            이 컷들은 프롬프트를 직접 고쳐 두어 화풍·배우 외모·장소·카메라 고정 변경이 닿지 않습니다.
          </span>
        )}
        {/* 옛 테이크 비우기 — «지금 보이는 컷»(장·필터가 걸린 그대로)이 붙들고 있는 것만.
            컷마다 열어 누르면 12컷 장이 서른여섯 번이었다(실측) — 한 번으로 묶는다.
            쌓인 게 두 장 미만이면 아예 나오지 않는다(청소를 재촉할 일은 아니다). */}
        {(() => {
          const withTakes = visible.filter(
            ({ scene }) => (project.cuts[scene.id]?.takeKeys?.length ?? 0) > 0,
          );
          const takes = withTakes.reduce(
            (n, { scene }) => n + (project.cuts[scene.id]?.takeKeys?.length ?? 0),
            0,
          );
          if (takes < 2) return null;
          const ids = withTakes.map(({ scene }) => scene.id);
          return (
            <button
              className="chip chipbtn stage-sweep"
              title={`지금 보이는 컷 ${withTakes.length}개에 쌓인 이전 테이크 ${takes}장을 저장소에서 지웁니다 — 걸려 있는 그림과 판정은 그대로입니다`}
              onClick={() => void clearTakesMany(ids)}
            >
              🧹 옛 테이크 {takes}장
            </button>
          );
        })()}
      </div>
      {hasChapters && (
        <div className="stagefilter chapterfilter">
          <span className="fine">장</span>
          <button
            className={`chip chipbtn ${chapter === "" ? "chip-on" : ""}`}
            onClick={() => setChapter("")}
          >
            전부
          </button>
          {chapters.map((c) => (
            <button
              key={c.firstId}
              className={`chip chipbtn ${chapter === c.firstId ? "chip-on" : ""}`}
              title={`${c.title} — ${c.ids.length}컷`}
              onClick={() => setChapter(c.firstId)}
            >
              {c.title} {c.ids.length}
            </button>
          ))}
          {/* 장 이름은 그 장 첫 컷의 «컷 제목»이다 — 그 컷을 찾아 들어가지 않고 여기서 고친다 */}
          {chosen &&
            (() => {
              const firstId = chosen.firstId;
              return (
                <button
                  className="chip chipbtn"
                  title="이 장의 이름을 고칩니다 — 인쇄본의 장 제목 띠·목차에도 같이 반영됩니다"
                  onClick={() => {
                    void (async () => {
                      const scene = project.story.scenes.find((sc) => sc.id === firstId);
                      const next = await promptText({
                        title: "장 이름",
                        body: "이 장의 첫 컷 제목입니다 — 인쇄본의 장 제목 띠와 목차가 이 이름을 씁니다.",
                        initial: (scene?.webtoon?.caption ?? "").trim() || chosen.title,
                        okLabel: "반영",
                      });
                      if (next === null) return;
                      const name = next.trim();
                      updateScene(firstId, {
                        webtoon: { ...(scene?.webtoon ?? {}), caption: name || undefined },
                      });
                    })();
                  }}
                >
                  ✎ 장 이름
                </button>
              );
            })()}
          {/* 장을 고른 상태에서는 «그 장만» 찍는 것이 연재의 실제 흐름이다.
              연재는 «이번 장에 얼마 드나»로 예산을 가늠하므로 누르기 전에 값을 보여준다 */}
          {chosen &&
            (() => {
              const waitInChapter = chosen.ids.filter(
                (id) => (project.cuts[id]?.status ?? "wait") === "wait",
              );
              return (
                <button
                  className="btn btn-small btn-primary"
                  disabled={waitInChapter.length === 0 || Boolean(batchRunning)}
                  title="이 장의 대기 컷만 차례로 찍습니다 — 크레딧 안내가 먼저 나옵니다"
                  onClick={() => void startBatch("pending", waitInChapter)}
                >
                  이 장만 촬영 ({waitInChapter.length})
                </button>
              );
            })()}
          {/* 장 단위 재촬영 — 연재에서 「3장의 NG만 다시」는 흔하다. 대기 컷은 건드리지 않는다 */}
          {chosen &&
            (() => {
              const ngInChapter = chosen.ids.filter((id) => project.cuts[id]?.status === "ng");
              if (ngInChapter.length === 0) return null;
              return (
                <button
                  className="btn btn-small"
                  disabled={Boolean(batchRunning)}
                  title="이 장에서 NG 받은 컷만 다시 찍습니다 — 대기 컷은 그대로 둡니다"
                  onClick={() => void startBatch("ng", ngInChapter)}
                >
                  이 장 NG만 다시 ({ngInChapter.length})
                </button>
              );
            })()}
          {/* 값은 버튼 밖에 둔다 — 버튼 이름이 길어지면 «무엇을 누르는지»가 흐려진다 */}
          {chosen &&
            (() => {
              const waitInChapter = chosen.ids.filter(
                (id) => (project.cuts[id]?.status ?? "wait") === "wait",
              );
              if (waitInChapter.length === 0) return null;
              const model = modelById(project.camera.model);
              const size: SizeKey = model.sizes.includes(project.camera.size)
                ? project.camera.size
                : model.sizes[0];
              const per = creditsOf(model, size);
              const paid = waitInChapter.filter((id) => {
                const sc = project.story.scenes.find((x) => x.id === id);
                return sc ? isApiCut(sc, project.cuts[id]) : false;
              }).length;
              const free = waitInChapter.length - paid;
              return (
                <span
                  className="fine chapter-cost"
                  title="지금 카메라(모델·해상도) 기준입니다 — 실패해도 시작 시점에 과금되니 어림값으로 보세요"
                >
                  {per == null
                    ? "크레딧 정보 없음"
                    : `약 ${per * paid} 크레딧${free > 0 ? ` · reuse·내 파일 ${free}컷은 0` : ""}`}
                </span>
              );
            })()}
        </div>
      )}
      {/* 건너뛰기 링크의 도착지 — 촬영장의 «일하는 자리»는 컷 카드들이다 */}
      <div className="stagegrid" id="work" tabIndex={-1}>
        {visible.map(({ scene, i }) => (
          <CutCard key={scene.id} scene={scene} index={i} onFaceCheck={setFaceCheckId} />
        ))}
      </div>
      {faceCheckId && (
        <FaceCheck
          sceneId={faceCheckId}
          onClose={() => setFaceCheckId(null)}
          onNav={navFaceCheck}
        />
      )}
    </div>
  );
}
