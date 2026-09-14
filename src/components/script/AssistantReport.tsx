/** 조감독 리포트 — 연속성 검사 결과. 아무것도 자동으로 고치지 않는다. */
import { useMemo, useState } from "react";
import { continuityReport } from "../../lib/continuity";
import { chapterOf, chapterRanges } from "../../lib/chapters";
import { useStudio } from "../../store/useStudio";
import { useProject } from "../hooks";

export function AssistantReport() {
  const project = useProject();
  const issues = useMemo(() => continuityReport(project), [project]);
  const setDeskChapter = useStudio((s) => s.setDeskChapter);
  const [open, setOpen] = useState(false);
  const warns = issues.filter((i) => i.severity === "warn").length;
  /* 보여줄 때는 «확인(warn)»을 먼저 세운다 — 접힌 리포트는 맨 앞 한 줄만 보이므로, 참고 줄이
     앞에 오면 끊어진 연결·얼굴 없는 배우가 「외 N건」 뒤로 숨는다(검사 순서는 검사의 일이 아니다).
     같은 등급 안에서는 검사가 찾은 순서를 지킨다(안정 정렬). */
  const ordered = useMemo(
    () =>
      [...issues].sort((a, b) =>
        a.severity === b.severity ? 0 : a.severity === "warn" ? -1 : 1,
      ),
    [issues],
  );
  /**
   * 어느 «장»의 문제인지 — 60컷 연재에서 「s37의 연결이 끊겼다」만으로는 어디인지 감이 없다.
   * 검사 자체(continuity.ts)는 장을 모르는 순수 검사로 두고, 보여줄 때만 장을 붙인다.
   */
  const chapters = chapterRanges(project.story.scenes);
  const goTo = (sceneId: string) => {
    const ch = chapterOf(chapters, sceneId);
    if (ch) setDeskChapter(ch.firstId);
    // 필터가 적용된 뒤에 스크롤해야 그 컷이 화면에 있다
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        document
          .getElementById(`cut-${sceneId}`)
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
  };

  if (issues.length === 0) {
    return (
      <section className="panel report">
        <div className="panel-head">
          <h2>조감독 리포트</h2>
          <span className="fine">오늘 밤 촬영에 걸리는 것 없음 ✓</span>
        </div>
      </section>
    );
  }
  return (
    <section className="panel report">
      <div className="panel-head">
        <h2>
          조감독 리포트{" "}
          {warns > 0 ? (
            <span className="badge badge-ng">확인 {warns}</span>
          ) : (
            <span className="badge badge-wait">참고 {issues.length}</span>
          )}
        </h2>
        <button className="btn btn-ghost btn-small" onClick={() => setOpen((v) => !v)}>
          {open ? "접기" : "펼치기"}
        </button>
      </div>
      {open && (
        <ul className="report-list">
          {ordered.map((it, i) => {
            const ch = it.sceneId ? chapterOf(chapters, it.sceneId) : undefined;
            return (
              <li key={i} className={`report-item report-${it.severity}`}>
                {it.severity === "warn" ? "⚠" : "·"} {it.message}
                {it.sceneId && (
                  <button
                    type="button"
                    className="report-go"
                    title={`정리대를 ${ch ? `「${ch.title}」로 맞추고 ` : ""}${it.sceneId} 컷으로 데려갑니다`}
                    onClick={() => goTo(it.sceneId as string)}
                  >
                    {ch && chapters.length >= 2 ? `${ch.title} · ` : ""}
                    {it.sceneId} 보기
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {!open && (
        <p className="fine">
          {/* 접힌 줄은 «가장 급한 것»이어야 한다 — 정렬한 목록의 첫 줄을 쓴다 */}
          {ordered[0].message}
          {ordered.length > 1 && ` … 외 ${ordered.length - 1}건`}
        </p>
      )}
    </section>
  );
}
