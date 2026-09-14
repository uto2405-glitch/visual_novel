/** 작품 제목 + 화풍(style) 패널. 제목은 로컬 초안으로 편집하고 확정 때만 반영. */
import { useState } from "react";
import { useStudio } from "../../store/useStudio";
import { useProject } from "../hooks";

/** 화풍 프리셋 — 한 번에 밤의 톤을 갈아입는다. 얼굴 고정 문구는 공통 유지. */
const STYLE_PRESETS: { id: string; label: string; style: string }[] = [
  {
    id: "cinema",
    label: "🎬 시네마 실사",
    style:
      "cinematic realistic photo, soft lighting, visual novel still, consistent face matching reference, 16:9",
  },
  {
    id: "water",
    label: "🎨 수채화",
    style:
      "delicate watercolor illustration, soft washes, gentle light, visual novel still, consistent face matching reference, 16:9",
  },
  {
    id: "anime",
    label: "✨ 애니메이션",
    style:
      "high quality anime style illustration, cel shading, expressive lighting, visual novel still, consistent face matching reference, 16:9",
  },
  {
    id: "noir",
    label: "🌑 필름 누아르",
    style:
      "black and white film noir photography, dramatic shadows, rain and neon, visual novel still, consistent face matching reference, 16:9",
  },
];

export function TitleStylePanel() {
  const project = useProject();
  const setTitle = useStudio((s) => s.setTitle);
  const setStyle = useStudio((s) => s.setStyle);
  const toast = useStudio((s) => s.toast);
  /* 프롬프트를 직접 고친 컷들 — 이 컷들은 조립을 건너뛰므로 화풍·배우·장소 변경이 닿지 않는다 */
  const custom = project.story.scenes.filter((s) => (project.cuts[s.id]?.customPrompt ?? "").trim());
  const setNote = useStudio((s) => s.setNote);
  const setCoverSubtitle = useStudio((s) => s.setCoverSubtitle);
  const setCoverByline = useStudio((s) => s.setCoverByline);
  // 입력 중에는 빈 문자열도 보이게 로컬 초안을 쓰고, 확정(blur/Enter) 때만 스토어에 반영
  const [titleDraft, setTitleDraft] = useState<string | null>(null);
  const commitTitle = () => {
    if (titleDraft !== null) {
      setTitle(titleDraft);
      setTitleDraft(null);
    }
  };

  return (
    <section className="panel">
      <div className="fieldrow">
        <label className="field grow">
          <span>작품 제목</span>
          <input
            value={titleDraft ?? project.title}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={commitTitle}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) commitTitle();
            }}
          />
        </label>
      </div>
      <label className="field">
        <span>화풍 (style) — 모든 컷의 밑그림이 됩니다</span>
        <textarea rows={2} value={project.story.style} onChange={(e) => setStyle(e.target.value)} />
      </label>
      <label className="field">
        <span>표지 부제 — 인쇄본 표지 제목 아래 한 줄 (비우면 「N컷」)</span>
        <input
          className="cover-subtitle"
          value={project.story.coverSubtitle ?? ""}
          placeholder="어느 비 오는 밤의 이야기"
          onChange={(e) => setCoverSubtitle(e.target.value)}
        />
      </label>
      <label className="field">
        <span>표지 아래 한 줄 — 지은이·발행일 (비우면 안 그립니다)</span>
        <input
          className="cover-byline"
          value={project.story.coverByline ?? ""}
          placeholder="지은이 · 2026 가을"
          onChange={(e) => setCoverByline(e.target.value)}
        />
      </label>
      <label className="field">
        <span>감독 노트 — 나만 보는 메모 (✨ AI 이어쓰기 프롬프트에도 함께 전달)</span>
        <textarea
          rows={2}
          value={project.story.note ?? ""}
          placeholder="다음 밤의 전개 아이디어, 촬영 유의사항…"
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <div className="style-presets">
        {STYLE_PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`chip chipbtn ${project.story.style === p.style ? "chip-on" : ""}`}
            title={p.style}
            onClick={() => {
              setStyle(p.style);
              /* 컷 프롬프트를 손댄 컷은 조립을 건너뛰므로(engine.effectivePrompt) 새 화풍이 닿지 않는다.
                 예전에는 잔글씨가 「다음 촬영부터 적용돼요」라고만 약속해 거짓말이 됐다 — 이제 몇 컷이
                 닿지 않는지 세어 말하고, 촬영장의 「✎ 직접 쓴 N」에서 한 번에 되돌릴 수 있다. */
              const frozen = custom.length;
              if (frozen > 0) {
                toast(
                  `${frozen}컷은 프롬프트를 직접 고쳐 두어 이 화풍이 닿지 않습니다 — 촬영장의 「✎ 직접 쓴 ${frozen}」에서 되돌릴 수 있어요.`,
                );
              }
            }}
          >
            {p.label}
          </button>
        ))}
        <span className="fine">
          프리셋은 화풍만 바꿉니다 — 이미 찍은 컷은 그대로, 다음 촬영부터 적용돼요.
          {custom.length > 0 && (
            <>
              {" "}
              단, <b>프롬프트를 직접 고친 {custom.length}컷</b>에는 화풍·배우·장소 변경이 닿지 않습니다
              (촬영장의 「✎ 직접 쓴 {custom.length}」에서 되돌리기).
            </>
          )}
        </span>
      </div>
    </section>
  );
}
