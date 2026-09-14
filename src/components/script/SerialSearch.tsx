/**
 * 연재 검색 — 20편 240컷에서 「그 대사가 몇 화였지」에 답하는 곳.
 *
 * 편마다 컷 목록은 있지만 «편을 넘어» 찾을 곳이 없었다. 저장된 작품 전부를 훑어
 * 대사·컷 제목·말풍선에서 찾고, 누르면 그 편을 열어 그 장으로 맞추고 컷까지 데려간다.
 * 찾기는 그림을 건드리지 않는다 — 읽기만 하므로 크레딧도 저장도 없다.
 */
import { useEffect, useRef, useState } from "react";
import { useStudio } from "../../store/useStudio";
import { chapterOf, chapterRanges } from "../../lib/chapters";
import type { SearchHit } from "../../store/types";

export function SerialSearch() {
  const searchAllProjects = useStudio((s) => s.searchAllProjects);
  const openProject = useStudio((s) => s.openProject);
  const setDeskChapter = useStudio((s) => s.setDeskChapter);
  const projectId = useStudio((s) => s.project?.id);
  const listCount = useStudio((s) => s.projectList.length);
  const [q, setQ] = useState("");
  /* 결과는 «어느 말로 찾은 것인지»와 함께 들고 있는다 — 그러면 「찾는 중」도 파생으로 읽힌다
     (효과 안에서 setState를 부르지 않게 된다: 그건 연쇄 렌더를 부르고 목록을 깜빡이게 한다). */
  const [res, setRes] = useState<{ key: string; hits: SearchHit[] } | null>(null);
  const seq = useRef(0);

  /* 두 글자 미만이면 «결과 없음»이다 — 상태를 지우는 대신 그렇게 읽는다.
     효과 안에서 setState를 부르면 연쇄 렌더가 되고(react-hooks/set-state-in-effect),
     지운 뒤 다시 채우는 한 박자가 목록을 깜빡이게 한다. seq만 올려 늦게 오는 답을 버린다. */
  const term = q.trim();
  const short = term.length < 2;
  /* 결과의 «열쇠»에는 찾은 말과 함께 어느 작품·몇 편이었는지를 넣는다 — 편을 옮기거나 편이
     늘면 같은 말이라도 답이 달라지므로, 그 사이에는 옛 결과를 «최신»으로 보여주지 않는다. */
  const key = `${term}|${projectId ?? ""}|${listCount}`;
  const fresh = res !== null && res.key === key;
  const searching = !short && !fresh;
  const shown = short ? null : fresh ? res.hits : [];

  // 타자를 멈추면 찾는다 — 글자마다 저장소를 훑으면 스무 편에서 손이 무거워진다
  useEffect(() => {
    const text = q.trim();
    if (text.length < 2) {
      seq.current += 1; // 앞선 검색의 늦은 답이 빈 칸에 내려앉지 않게
      return;
    }
    const mine = ++seq.current;
    const t = setTimeout(() => {
      void (async () => {
        const found = await searchAllProjects(text);
        if (seq.current === mine) setRes({ key, hits: found });
      })();
    }, 300);
    return () => clearTimeout(t);
  }, [q, key, searchAllProjects, projectId, listCount]);

  /** 그 컷으로 — 다른 편이면 열고, 장 필터를 맞춘 뒤 카드로 스크롤한다 */
  const goTo = async (hit: SearchHit) => {
    if (hit.projectId !== projectId) await openProject(hit.projectId);
    const p = useStudio.getState().project;
    if (p) {
      const ranges = chapterRanges(p.story.scenes);
      const ch = chapterOf(ranges, hit.sceneId);
      if (ranges.length >= 2 && ch) setDeskChapter(ch.firstId);
    }
    // 필터가 적용된 뒤에 스크롤해야 그 컷이 화면에 있다(조감독 리포트와 같은 방식)
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        document.getElementById(`cut-${hit.sceneId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
  };

  if (listCount < 2) return null; // 한 편뿐이면 컷 목록으로 충분하다

  return (
    <section className="panel serialsearch">
      <div className="panel-head">
        <h2>
          연재에서 찾기{" "}
          <span className="fine">저장된 {listCount}편의 대사·컷 제목·말풍선</span>
        </h2>
      </div>
      <input
        className="serialsearch-input"
        value={q}
        placeholder="두 글자 이상 — 예: 우산"
        onChange={(e) => setQ(e.target.value)}
      />
      {shown !== null && (
        <div className="fine serialsearch-list">
          {searching && <div>찾는 중…</div>}
          {!searching && shown.length === 0 && <div>찾지 못했습니다.</div>}
          {!searching &&
            shown.map((h) => (
              <button
                key={`${h.projectId}:${h.sceneId}:${h.where}`}
                type="button"
                className="serialsearch-hit"
                title={`「${h.projectTitle}」의 ${h.sceneId}로 갑니다`}
                onClick={() => void goTo(h)}
              >
                <span className="serialsearch-where">
                  {h.projectId === projectId ? "이 편" : h.projectTitle}
                  {h.chapter ? ` · ${h.chapter}` : ""} · {h.where}
                  {/* 찾은 다음의 손짓은 «고치기»거나 «찍기»다 — 그 컷의 판정을 함께 적는다.
                      가운뎃점을 글자로 넣는다: 여백은 눈에만 보이고 복사한 글에는 남지 않는다 */}
                  {" · "}
                  <span className={`serialsearch-status st-${h.status}`}>
                    {h.status === "ok" ? "✓ 찍음" : h.status === "ng" ? "NG" : "대기"}
                  </span>
                </span>
                <span className="serialsearch-text">{h.excerpt}</span>
              </button>
            ))}
          {!searching && shown.length >= 60 && (
            <div>예순 줄까지만 보여줍니다 — 더 좁혀 찾아보세요.</div>
          )}
        </div>
      )}
    </section>
  );
}
