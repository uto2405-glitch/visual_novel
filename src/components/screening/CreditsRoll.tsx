/** 엔딩 크레딧 — 막이 내린 뒤. 클릭하면 포스터로. */
import { useEffect, useState } from "react";
import { useStudio } from "../../store/useStudio";
import { modelById } from "../../lib/makefun";
import { findNextEpisode } from "../../lib/episodes";
import { countCutStatus } from "../../types";
import { VERSION } from "../../version";
import { useCharPhoto, useProject } from "../hooks";

export function CreditsRoll() {
  const project = useProject();
  const choiceHistory = useStudio((s) => s.choiceHistory);
  const okCount = countCutStatus(project).ok;
  const model = modelById(project.camera.model);
  /**
   * 연재의 막이 내렸으면 관객의 다음 손짓은 «다음 화»다.
   * 지금까지는 시사실을 나가 목록을 열고 다음 화를 찾아 다시 시사를 눌러야 했다.
   * 찍은 컷이 하나도 없는 화는 보여줄 것이 없으므로 조용히 둔다.
   */
  const projectList = useStudio((s) => s.projectList);
  const openProject = useStudio((s) => s.openProject);
  const restartPlay = useStudio((s) => s.restartPlay);
  const next = findNextEpisode(projectList, project);
  const nextReady = next && next.okCount > 0 ? next : undefined;
  /**
   * 자동 상영으로 보고 있었다면 관객은 손을 놓고 있다 — 막이 내렸다고 거기서 끊지 않는다.
   * 다섯을 세어 주고 스스로 다음 화로 넘어가되, 「여기서 멈추기」로 언제든 세는 것을 끊을 수 있다.
   * (자동 상영을 끈 사람에게는 세지 않는다 — 재촉이 아니라 이어보기다.)
   */
  const autoPlay = useStudio((s) => s.autoPlay);
  const [left, setLeft] = useState(5);
  const [stopped, setStopped] = useState(false);
  const counting = Boolean(nextReady) && autoPlay && !stopped;
  const goNext = () => {
    if (!nextReady) return;
    void (async () => {
      await openProject(nextReady.id);
      restartPlay();
    })();
  };
  useEffect(() => {
    if (!counting) return;
    if (left <= 0) {
      goNext();
      return;
    }
    const t = setTimeout(() => setLeft((v) => v - 1), 1000);
    return () => clearTimeout(t);
    // goNext는 렌더마다 새로 만들어지지만 세는 동안 대상(nextReady)은 바뀌지 않는다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [counting, left]);
  return (
    <div className="credits">
      <div className="credits-inner">
        <div className="credits-end">— 막이 내렸습니다 —</div>
        <h1 className="credits-title">{project.title}</h1>
        <div className="credits-row">
          <span className="credits-role">감독</span>
          <span>나</span>
        </div>
        {project.story.characters.length > 0 && (
          <div className="credits-cast">
            <span className="credits-role">출연</span>
            <div className="credits-cast-list">
              {project.story.characters.map((c) => (
                <CreditsCast key={c.id} charId={c.id} />
              ))}
            </div>
          </div>
        )}
        <div className="credits-row">
          <span className="credits-role">카메라</span>
          <span>{model.label}</span>
        </div>
        <div className="credits-row">
          <span className="credits-role">필름</span>
          <span>
            총 {project.story.scenes.length}컷 · OK {okCount}컷
          </span>
        </div>
        {choiceHistory.length > 0 && (
          <div className="credits-row">
            <span className="credits-role">지나온 갈래</span>
            <span>{choiceHistory.filter(Boolean).join(" → ") || "…"}</span>
          </div>
        )}
        {(project.coinsSpent ?? 0) > 0 && (
          <div className="credits-row">
            <span className="credits-role">제작비</span>
            <span>{project.coinsSpent} 코인</span>
          </div>
        )}
        {nextReady && (
          <div className="credits-next" onClick={(e) => e.stopPropagation()}>
            <button
              className="btn btn-primary"
              title={`「${nextReady.title}」을 열고 처음부터 상영합니다`}
              onClick={goNext}
            >
              ▶ 다음 화 보기 — 「{nextReady.title}」
              {counting ? ` (${left}초 뒤 자동)` : ""}
            </button>
            <span className="fine">
              찍은 컷 {nextReady.okCount} / {nextReady.sceneCount}
            </span>
            {counting && (
              <button className="btn btn-ghost btn-small" onClick={() => setStopped(true)}>
                여기서 멈추기
              </button>
            )}
          </div>
        )}
        <div className="credits-studio">비주얼노벨 스튜디오 {VERSION}</div>
        <div className="credits-tagline">오늘 밤도, 같은 얼굴.</div>
        <div className="fine credits-hint">클릭하면 포스터로 돌아갑니다</div>
      </div>
    </div>
  );
}

function CreditsCast({ charId }: { charId: string }) {
  const { char: c, url } = useCharPhoto(charId);
  if (!c) return null;
  return (
    <div className="credits-cast-item">
      {url && <img src={url} alt={c.name} />}
      <span>{c.name}</span>
    </div>
  );
}
