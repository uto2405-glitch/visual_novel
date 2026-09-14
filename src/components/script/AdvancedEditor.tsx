/** 고급 — story.json 전체 편집. 손대지 않은 동안에만 최신 대본을 따라간다. */
import { useEffect, useMemo, useState } from "react";
import { useStudio } from "../../store/useStudio";
import { useProject } from "../hooks";
import { nextPaint } from "../../lib/hooks";

export function AdvancedEditor() {
  const project = useProject();
  const advancedOpen = useStudio((s) => s.advancedOpen);
  const setAdvancedOpen = useStudio((s) => s.setAdvancedOpen);
  const replaceStoryJson = useStudio((s) => s.replaceStoryJson);
  const cleanStorage = useStudio((s) => s.cleanStorage);
  const cur = useMemo(() => JSON.stringify(project.story, null, 2), [project.story]);
  const [text, setText] = useState(cur);
  const [snapshot, setSnapshot] = useState(cur);
  /* 반영은 컷 수만큼 무겁다 — 600컷이면 화면이 1.5초 멈춘다(실측).
     멈추기 «전에» 「반영 중」을 찍어 두어야 감독이 앱이 죽었다고 읽지 않는다. */
  const [applying, setApplying] = useState(false);

  // 카드에서 편집이 일어나면, textarea가 손대지 않은 상태일 때만 따라간다.
  // (손댄 상태에서 최신화하면 사용자의 JSON 편집을 날리게 된다) — 렌더 중 상태 조정.
  if (text === snapshot && cur !== snapshot) {
    setText(cur);
    setSnapshot(cur);
  }

  return (
    <section className="panel advanced">
      <div className="panel-head">
        <h2>고급 — story.json 전체 편집</h2>
        <div className="panel-actions">
          <button className="btn btn-ghost" onClick={() => setAdvancedOpen(!advancedOpen)}>
            {advancedOpen ? "닫기" : "열기"}
          </button>
        </div>
      </div>
      {advancedOpen && (
        <>
          <textarea
            className="mono json-editor"
            rows={20}
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
          />
          <div className="panel-actions">
            <button
              className="btn"
              onClick={() => {
                const cur = JSON.stringify(project.story, null, 2);
                setText(cur);
                setSnapshot(cur);
              }}
            >
              현재 대본 다시 불러오기
            </button>
            <button
              className="btn btn-primary"
              disabled={applying}
              onClick={async () => {
                setApplying(true);
                await nextPaint(); // 「반영 중…」이 화면에 찍힌 다음에 무거운 일을 시작한다
                try {
                  if (replaceStoryJson(text)) {
                    setSnapshot(text); // 다음에 열 때 최신 대본으로 새로고침되게
                    setAdvancedOpen(false);
                  }
                } finally {
                  setApplying(false);
                }
              }}
            >
              {applying ? "반영 중…" : "반영하기"}
            </button>
            <span className="spacer" />
            <button
              className="btn btn-ghost"
              title="저장된 작품 전부를 훑어, 어느 컷도 참조하지 않는 고아 그림/영상만 지웁니다 — 목록에서 지운 작품이 남긴 그림도 여기서 잡힙니다"
              onClick={() => void cleanStorage()}
            >
              🧹 저장소 청소
            </button>
            <StorageGauge />
          </div>
          <p className="fine">
            같은 id의 컷은 생성 이미지와 테이크를 그대로 유지합니다. 장면을 지우면 그 컷의 그림도
            목록에서 빠집니다.
          </p>
        </>
      )}
    </section>
  );
}

/** 브라우저 저장소 게이지 — 열 때 한 번 잰다. 실패해도 조용히. */
function StorageGauge() {
  const [line, setLine] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const est = await navigator.storage?.estimate?.();
        if (!alive || !est) return;
        const used = (est.usage ?? 0) / 1024 / 1024;
        const quota = (est.quota ?? 0) / 1024 / 1024 / 1024;
        setLine(`저장소 ${used.toFixed(1)}MB 사용 · 여유 약 ${quota.toFixed(1)}GB`);
      } catch {
        /* 게이지는 장식 — 못 재면 그냥 숨긴다 */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);
  if (!line) return null;
  return <span className="fine storage-gauge">{line}</span>;
}
