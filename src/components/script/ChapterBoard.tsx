/**
 * 장별 진도 — 연재가 길어지면 「어느 장이 어디까지 됐나」가 오늘의 판단이다.
 *
 * 콜시트의 한 줄은 «가장 덜 된 장»만 가리키고 네 장까지만 적는다(그게 콜시트의 일이다).
 * 20장짜리 연재에서는 전체 판이 필요하다 — 여기서 장마다 OK/대기/NG를 한 줄로 본다.
 * 장을 누르면 정리대가 그 장만 보여주고, 「촬영장에서」로 그 장만 찍으러 갈 수 있다.
 */
import { memo, useState } from "react";
import { useStudio } from "../../store/useStudio";
import { chapterRanges } from "../../lib/chapters";
import { buildChapterRewritePrompt } from "../../lib/aiPrompt";
import { useProject } from "../hooks";

const LS_OPEN = "vn-studio:chapterBoardOpen";

export const ChapterBoard = memo(function ChapterBoard() {
  const project = useProject();
  const setDeskChapter = useStudio((s) => s.setDeskChapter);
  const setStageChapter = useStudio((s) => s.setStageChapter);
  const setTab = useStudio((s) => s.setTab);
  const deskChapter = useStudio((s) => s.deskChapter);
  const promptText = useStudio((s) => s.promptText);
  const toast = useStudio((s) => s.toast);
  const rewriteScenesJson = useStudio((s) => s.rewriteScenesJson);
  /**
   * 펼침 여부는 기억한다 — 방을 옮기면(촬영장 ↔ 대본실) 이 컴포넌트가 사라지므로
   * 지역 상태로 두면 «펼치기»를 매번 다시 눌러야 한다. 연재 중에는 계속 들여다보는 판이다.
   */
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(LS_OPEN) === "1";
    } catch {
      return false;
    }
  });
  const toggle = () => {
    setOpen((v) => {
      try {
        localStorage.setItem(LS_OPEN, v ? "0" : "1");
      } catch {
        /* 취향 기억은 장식 */
      }
      return !v;
    });
  };

  /**
   * 이 장만 다시 쓰기 — 프롬프트를 만들어 클립보드에 담는다.
   * 같은 id로 돌려받아야 그림을 지키면서 대본만 갈아끼울 수 있으므로 규칙에 못박아 둔다.
   */
  const askRewrite = async (title: string, ids: string[]) => {
    const scenes = project.story.scenes.filter((sc) => ids.includes(sc.id));
    const text = buildChapterRewritePrompt(project.story, title, scenes);
    let copied = false;
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
      toast(`「${title}」 다시 쓰기 프롬프트를 복사했습니다 (${scenes.length}컷).`, "ok");
    } catch {
      /* 폰의 http 환경에서는 클립보드가 막힌다 — 아래 창에서 직접 복사 */
    }
    await promptText({
      title: `「${title}」 다시 쓰기`,
      body:
        `아래 전체를 그록/ChatGPT/Claude에 붙여넣고, 받은 JSON을 「다시 쓴 대본 넣기」에 넣으세요.` +
        (copied ? " (클립보드에도 복사돼 있어요)" : " (길게 눌러 전체 선택 → 복사)"),
      initial: text,
      multiline: true,
      okLabel: "닫기",
    });
  };

  const chapters = chapterRanges(project.story.scenes);
  if (chapters.length < 2) return null; // 한 장짜리 작품에 진도표는 군더더기다

  const rows = chapters.map((c) => {
    let ok = 0;
    let ng = 0;
    for (const id of c.ids) {
      const st = project.cuts[id]?.status ?? "wait";
      if (st === "ok") ok += 1;
      else if (st === "ng") ng += 1;
    }
    return { ...c, ok, ng, total: c.ids.length };
  });
  const doneAll = rows.filter((r) => r.ok === r.total).length;

  return (
    <section className="panel chapterboard">
      <div className="panel-head">
        <h2>
          장별 진도{" "}
          <span className="fine">
            {chapters.length}장 중 {doneAll}장 완료
          </span>
        </h2>
        <div className="panel-actions">
          <button className="btn btn-ghost btn-small" onClick={toggle}>
            {open ? "접기" : "펼치기"}
          </button>
        </div>
      </div>
      {open && (
        <div className="chapboard-list">
          <p className="fine">
            장을 누르면 정리대가 그 장만 보여줍니다. <b>✎ 다시 쓰기</b>로 만든 프롬프트의 답(JSON)은{" "}
            <button type="button" className="chapboard-name" onClick={() => void rewriteScenesJson()}>
              다시 쓴 대본 넣기
            </button>
            에 넣으세요 — 같은 id의 컷만 덮어쓰고 그림·판정은 그대로입니다.
          </p>
          {rows.map((r) => (
            <div key={r.firstId} className={`chapboard-row ${deskChapter === r.firstId ? "on" : ""}`}>
              <button
                type="button"
                className="chapboard-name"
                title={`정리대를 「${r.title}」만 보이게 맞춥니다`}
                onClick={() => setDeskChapter(r.firstId)}
              >
                {r.title}
              </button>
              <span className="chapboard-bar" aria-hidden>
                <span
                  className="chapboard-fill"
                  style={{ width: `${Math.round((r.ok / Math.max(1, r.total)) * 100)}%` }}
                />
              </span>
              <span className="fine chapboard-count">
                {r.ok}/{r.total}
                {r.ng > 0 ? ` · NG ${r.ng}` : ""}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-small"
                title="이 장의 컷들을 LLM에게 다시 쓰게 하는 프롬프트를 만듭니다 — 같은 id로 돌려받아 그림은 그대로 두고 대본만 갈아끼웁니다"
                onClick={() => void askRewrite(r.title, r.ids)}
              >
                ✎ 다시 쓰기
              </button>
              {r.ok < r.total && (
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  title="촬영장을 이 장만 보이게 맞추고 넘어갑니다"
                  onClick={() => {
                    setStageChapter(r.firstId);
                    setTab("stage");
                  }}
                >
                  촬영장에서
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
});
