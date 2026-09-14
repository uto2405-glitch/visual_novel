/** 촬영 큐 — 대기 컷 촬영 / NG만 다시 / 중단 / 생성 이미지 ZIP. 「전부 다시」는 없다. */
import { useStudio } from "../../store/useStudio";
import { countCutStatus } from "../../types";
import { useProject } from "../hooks";

export function QueuePanel() {
  const project = useProject();
  const batch = useStudio((s) => s.batch);
  const shooting = useStudio((s) => s.shooting);
  const startBatch = useStudio((s) => s.startBatch);
  const startVideoBatch = useStudio((s) => s.startVideoBatch);
  const stopBatch = useStudio((s) => s.stopBatch);
  const exportGeneratedImages = useStudio((s) => s.exportGeneratedImages);

  const { ok: okCount, ng: ngCount, wait: waitCount } = countCutStatus(project);
  const anyShooting = Boolean(batch?.running) || Object.keys(shooting).length > 0;
  const cutsceneCount = project.story.scenes.filter(
    (sc) => project.cuts[sc.id]?.cutscene && !project.cuts[sc.id]?.videoKey,
  ).length;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>촬영 큐</h2>
        <span className="fine">
          OK {okCount} · NG {ngCount} · 대기 {waitCount} / 전체 {project.story.scenes.length}컷
          {(project.coinsSpent ?? 0) > 0 && (
            <>
              {" "}
              · <b className="ledger">제작비 {project.coinsSpent}코인</b>
            </>
          )}
        </span>
      </div>
      <div className="panel-actions wrap">
        <button
          className="btn btn-primary"
          disabled={anyShooting || waitCount === 0}
          onClick={() => void startBatch("pending")}
        >
          대기 컷 촬영 ({waitCount})
        </button>
        <button
          className="btn"
          disabled={anyShooting || ngCount === 0}
          onClick={() => void startBatch("ng")}
        >
          NG만 다시 ({ngCount})
        </button>
        <button
          className="btn"
          disabled={anyShooting || cutsceneCount === 0}
          title="🎬 컷씬으로 지정한 컷들을 MakeFun 영상(무빙 컷)으로 변환합니다 — 컷당 약 30크레딧"
          onClick={() => void startVideoBatch()}
        >
          🎬 컷씬 영상화 ({cutsceneCount})
        </button>
        {anyShooting && (
          <button className="btn btn-danger" onClick={stopBatch}>
            중단
          </button>
        )}
        <span className="spacer" />
        <button
          className="btn btn-ghost"
          disabled={okCount === 0}
          onClick={() => void exportGeneratedImages()}
        >
          생성 이미지 ZIP 다운로드
        </button>
      </div>
      {batch?.running && (
        <div className="progressline">
          <div className="progressbar">
            <div
              className="progressfill"
              style={{ width: `${batch.total ? Math.round((batch.done / batch.total) * 100) : 0}%` }}
            />
          </div>
          <span className="fine">
            {batch.kind === "video" ? "영상 변환 중" : "촬영 중"} — {batch.done}/{batch.total}컷
            (동시 2컷)
          </span>
        </div>
      )}
      <p className="fine">
        reuse 컷은 배치에서 API를 부르지 않고 원본 그림을 복사합니다. 개별 「이 컷만 다시」는
        reuse를 끊고 새로 찍습니다. 컷 미리보기를 클릭하면 페이스 체크 모니터가 열립니다.
      </p>
    </section>
  );
}
