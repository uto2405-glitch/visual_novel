/** 대본실 — 한 카드 = 한 컷. JSON 전체 편집은 「고급」 뒤에. */
import { Fragment, useEffect, useMemo, useState } from "react";
import { anyModalOpen, useStudio } from "../../store/useStudio";
import { countCutStatus, type CutStatus } from "../../types";
import { chapterRanges } from "../../lib/chapters";
import { buildBlankPrompt, buildContinuePrompt } from "../../lib/aiPrompt";
import { useProject } from "../hooks";
import { ProjectBar } from "./ProjectBar";
import { AssistantReport } from "./AssistantReport";
import { CallSheet } from "./CallSheet";
import { ChapterBoard } from "./ChapterBoard";
import { SerialSearch } from "./SerialSearch";
import { FilmMap } from "./FilmMap";
import { Casting } from "./Casting";
import { CutScriptCard } from "./CutScriptCard";
import { AdvancedEditor } from "./AdvancedEditor";
import { TitleStylePanel } from "./TitleStylePanel";

/** 이 수를 넘는 편은 가벼운 보기로 연다 — 4배 느린 기계에서 카드 보기의 반영 막힘이
 *  240컷 1.7초 → 600컷 8.5초로 급히 나빠졌다(한 줄 보기는 0.3초). 그 사이에 선을 긋는다. */
const BIG_EPISODE_CUTS = 300;

export function ScriptRoom() {
  const hasProject = useStudio((s) => s.project !== null);
  return (
    <div className="room">
      <ProjectBar />
      <p className="notice">
        작업본은 이 브라우저(IndexedDB)에만 있습니다. 시크릿 모드나 다른 브라우저에서는 비어
        있어요 — 중요한 작품은 <b>내 기기로 내보내기</b>로 필름캔(ZIP)을 내 폴더에 두세요. ZIP이
        곧 백업입니다.
      </p>
      {hasProject && <ExportReminder />}
      {hasProject ? <ProjectEditor /> : <EmptyState />}
    </div>
  );
}

/** 필름캔 리마인더 — OK 컷이 있는데 백업이 오래됐으면 조용히 알린다. */
function ExportReminder() {
  const project = useProject();
  // 마운트 시각 기준으로 계산 — 렌더 순수성 유지 (탭을 오갈 때마다 갱신된다)
  const [now] = useState(() => Date.now());
  if (countCutStatus(project).ok === 0) return null;
  const last = project.lastExportAt;
  const days = last ? Math.floor((now - last) / 86_400_000) : null;
  if (last && days !== null && days < 3) return null;
  return (
    <p className="notice notice-warn">
      🎞{" "}
      {last
        ? `마지막 필름캔이 ${days}일 전입니다`
        : "이 작품은 아직 필름캔(ZIP)이 없습니다"}{" "}
      — 브라우저 저장소는 영원하지 않아요. <b>내 기기로 내보내기</b>로 오늘 밤 촬영분을 내
      폴더에 두세요.
    </p>
  );
}

function ProjectEditor() {
  const project = useProject();
  const appendStoryJson = useStudio((s) => s.appendStoryJson);
  const undoDepth = useStudio((s) => s.undoDepth);
  const undoScript = useStudio((s) => s.undoScript);

  // Ctrl+Z — 입력창 밖에서만. 입력창 안은 브라우저 자체 undo가 맡는다.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.shiftKey || e.altKey || e.key.toLowerCase() !== "z") return;
      if (anyModalOpen()) return;
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      e.preventDefault();
      undoScript();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undoScript]);
  const promptText = useStudio((s) => s.promptText);
  const toast = useStudio((s) => s.toast);

  // 대본이 사실상 비어 있으면(배우 0, 컷 1개, 대사 없음) 「처음부터」 모드로 프롬프트를 바꾼다
  const isBlankStory =
    project.story.characters.length === 0 &&
    project.story.scenes.length <= 1 &&
    !(project.story.scenes[0]?.text ?? "").trim();

  const openAiPrompt = async () => {
    // 프롬프트 문장은 lib/aiPrompt.ts 한 곳에 있다 — 장별 「다시 쓰기」와 같은 규칙을 써야 한다
    const prompt = isBlankStory ? buildBlankPrompt() : buildContinuePrompt(project.story);

    const label = isBlankStory ? "AI로 초안 만들기 프롬프트" : "AI 이어쓰기 프롬프트";
    const where = isBlankStory
      ? "받은 JSON 전체를 「고급 → story.json 전체 편집」에 붙여넣고 반영하세요."
      : "받은 JSON을 「스토리 이어서 만들기」에 넣으세요.";
    let copied = false;
    try {
      await navigator.clipboard.writeText(prompt);
      copied = true;
      toast(`${label}을 클립보드에 복사했습니다.`, "ok");
    } catch {
      /* http(폰) 환경에서는 클립보드 API가 막힌다 — 아래 창에서 직접 복사 */
    }
    await promptText({
      title: label,
      body:
        `아래 전체를 그록/ChatGPT/Claude에 붙여넣고, ${where}` +
        (isBlankStory ? " (맨 위 [소재] 줄만 원하는 이야기로 바꾸세요)" : "") +
        (copied ? " (클립보드에도 복사돼 있어요)" : " (길게 눌러 전체 선택 → 복사)"),
      initial: prompt,
      multiline: true,
      okLabel: "닫기",
    });
  };

  return (
    <div className="editor">
      <CallSheet />
      <TitleStylePanel />
      <AssistantReport />
      <ChapterBoard />
      <SerialSearch />
      <FilmMap />
      <Casting />
      {/* 건너뛰기 링크의 도착지 — 방마다 «일하는 자리»가 #work다(대본실은 컷 목록).
          방 전체(main)로 보내면 판 다섯 개를 지나 35탭이 남았다(실측). */}
      <section className="panel">
        <div className="panel-head">
          <h2>컷 목록</h2>
          <div className="panel-actions">
            <button
              className="btn btn-ghost"
              disabled={undoDepth === 0}
              title="마지막 대본 변경(수정·추가·삭제·이동·이어 붙이기)을 되돌립니다 — 그림은 그대로"
              onClick={undoScript}
            >
              ↩ 되돌리기{undoDepth > 0 ? ` (${undoDepth})` : ""}
            </button>
            <button
              className="btn btn-ghost"
              title={
                isBlankStory
                  ? "소재만 적으면 그록/ChatGPT/Claude에 붙여넣을 「처음부터 만들기」 프롬프트를 만들어 줍니다 — 받은 JSON을 「고급 → 전체 편집」에 붙이면 끝"
                  : "현재 대본을 넣은 이어쓰기 프롬프트를 만들어 줍니다 — LLM의 답(JSON)을 「스토리 이어서 만들기」에 붙이면 끝"
              }
              onClick={() => void openAiPrompt()}
            >
              {isBlankStory ? "✨ AI로 초안 만들기" : "✨ AI 이어쓰기 프롬프트"}
            </button>
            <button className="btn" onClick={() => void appendStoryJson()}>
              스토리 이어서 만들기
            </button>
          </div>
        </div>
        <CardsList project={project} />
      </section>
      <AdvancedEditor />
    </div>
  );
}

type StatusFilter = "all" | CutStatus;

function CardsList({ project }: { project: ReturnType<typeof useProject> }) {
  // 연결 셀렉트용 id 목록 — 내용이 같으면 identity를 고정해 카드 memo를 지킨다
  const idsKey = project.story.scenes.map((s) => s.id).join(" ");
  const sceneIds = useMemo(() => idsKey.split(" "), [idsKey]);

  // 정리대 — 검색·상태 필터는 표시만 좁힌다. 연결 셀렉트는 늘 전체 컷을 안다.
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  // 고른 장은 스토어가 들고 있다 — 캐스팅의 「이 배우가 나온 장」에서 여기로 건너올 수 있게
  const chapter = useStudio((st) => st.deskChapter);
  const setChapter = useStudio((st) => st.setDeskChapter);
  const moveChapter = useStudio((st) => st.moveChapter);
  const updateScene = useStudio((st) => st.updateScene);
  const pushChapterToNextEpisode = useStudio((st) => st.pushChapterToNextEpisode);
  const toast = useStudio((st) => st.toast);
  // 보기 — 카드(전체 편집) / 목록(한 줄 요약, 탭하면 그 자리 펼침). 폰에서는 목록이 빠르다.
  const [view, setView] = useState<"card" | "list">(() => {
    try {
      return localStorage.getItem("vn-studio:scriptView") === "list" ? "list" : "card";
    } catch {
      return "card";
    }
  });
  const [expanded, setExpanded] = useState<string | null>(null);
  const pickView = (v: "card" | "list") => {
    setView(v);
    try {
      localStorage.setItem("vn-studio:scriptView", v);
    } catch {
      /* 보기 기억은 장식 */
    }
  };
  /**
   * 아주 긴 편은 «한 줄 요약»으로 연다 — 카드 보기는 컷당 DOM 노드가 658개다.
   *
   * 실측(v1.8.0, CPU 4배 느린 기계 · 600컷): 카드 보기는 반영이 **8.5초** 멈추고 훑기 끊김이
   * 17회였는데, 한 줄 보기는 **0.2초**(막힘 315ms)·끊김 0에 문서 노드 3,286개(카드 394,508개)였다.
   * 그래서 컷이 많은 편을 열 때는 가벼운 쪽으로 시작한다 — 카드 보기 문은 바로 옆에 있고,
   * 감독이 기억시킨 보기(localStorage)는 덮지 않는다(이 편에서만 가볍게 연다).
   */
  const cutCount = project.story.scenes.length;
  const [lightFor, setLightFor] = useState<string | null>(null);
  if (cutCount >= BIG_EPISODE_CUTS && view === "card" && lightFor !== project.id) {
    setLightFor(project.id);
    setView("list"); // pickView가 아니다 — 기억은 감독의 것이다
  }
  useEffect(() => {
    if (lightFor && lightFor === project.id)
      toast(`컷이 ${cutCount}개라 「☰ 목록」 보기로 열었습니다 — 카드 보기로 바꿀 수 있어요.`);
  }, [lightFor, project.id, cutCount, toast]);

  const q = query.trim().toLowerCase();
  const speakerNameOf = (id: string | undefined) =>
    project.story.characters.find((c) => c.id === id)?.name ?? "";
  /**
   * 장 구간 — 인쇄본·촬영장·콜시트와 같은 기준(webtoon.pageBreak)으로 센다.
   * 대본실만 장을 모르면 «3장을 고쳐 쓰자»가 여기서 끊긴다.
   */
  const chapters = chapterRanges(project.story.scenes);
  const hasChapters = chapters.length >= 2;
  // 고른 장은 «첫 컷 id»로 기억한다 — 이름이 같은 장이 둘 있어도, 장을 옮겨도 고른 장이 따라간다
  const chosen = chapters.find((c) => c.firstId === chapter);
  // 고른 장이 사라졌으면(작품을 바꿨거나 그 장을 합쳤거나) 필터를 스스로 푼다 —
  // 한 컷도 안 보이는 정리대는 «대본이 비었다»로 읽힌다 (렌더 중 상태 조정)
  if (chapter !== "" && !chosen) setChapter("");
  const visible = project.story.scenes.filter((sc) => {
    if (chapter && !chosen?.ids.includes(sc.id)) return false;
    if (status !== "all" && (project.cuts[sc.id]?.status ?? "wait") !== status) return false;
    if (!q) return true;
    return (
      sc.id.toLowerCase().includes(q) ||
      (sc.text ?? "").toLowerCase().includes(q) ||
      speakerNameOf(sc.speaker).toLowerCase().includes(q) ||
      (sc.choices ?? []).some((c) => c.label.toLowerCase().includes(q))
    );
  });
  const filtered = q !== "" || status !== "all" || chapter !== "";
  // 컷이 늘어나면(새 컷·이어 붙이기) 필터를 풀어 새 컷이 바로 보이게 — 렌더 중 상태 조정
  const [lastCount, setLastCount] = useState(project.story.scenes.length);
  if (project.story.scenes.length !== lastCount) {
    const grew = project.story.scenes.length > lastCount;
    setLastCount(project.story.scenes.length);
    if (grew && filtered) {
      setQuery("");
      setStatus("all");
    }
  }
  const indexOf = new Map(project.story.scenes.map((sc, i) => [sc.id, i]));
  /**
   * 장 머리글 — 60컷 목록에서는 «몇 번째 컷»보다 «몇 장»으로 찾는다.
   * 내보낸 시사본 목록에도 같은 머리글이 들어간다(같은 기준, 같은 이름).
   */
  const chapterAt = new Map(hasChapters ? chapters.map((c) => [c.firstId, c] as const) : []);
  const chapterHead = (id: string) => {
    const c = chapterAt.get(id);
    if (!c) return null;
    return (
      <div className="cutlist-chap">
        <span className="chap-name">{c.title}</span>
        <span className="fine">{c.ids.length}컷</span>
      </div>
    );
  };
  // 분량 — 총 글자 수와 타자기 기준 예상 상영 시간 (컷당 여백 1.5초)
  const totalChars = project.story.scenes.reduce((n, sc) => n + (sc.text?.length ?? 0), 0);
  const estSec = Math.round((totalChars * 26) / 1000 + project.story.scenes.length * 1.5);
  const estLabel = estSec >= 60 ? `${Math.floor(estSec / 60)}분 ${estSec % 60}초` : `${estSec}초`;

  return (
    /* 건너뛰기 링크의 도착지 — 판 머리(되돌리기·AI 프롬프트…)가 아니라 «일하는 자리»다.
       방 전체로 보내면 35탭, 판으로 보내면 10탭이 남았다(실측). 판 머리는 Shift+Tab으로 닿는다. */
    <div id="work" tabIndex={-1}>
      <div className="deskbar">
        <input
          className="desk-search"
          value={query}
          placeholder="🔍 대사·컷 id·화자·선택지 검색"
          onChange={(e) => setQuery(e.target.value)}
        />
        {(
          [
            ["all", "전체"],
            ["wait", "대기"],
            ["ok", "OK"],
            ["ng", "NG"],
          ] as [StatusFilter, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`chip chipbtn ${status === id ? "chip-on" : ""}`}
            onClick={() => setStatus(id)}
          >
            {label}
          </button>
        ))}
        {hasChapters && (
          <span className="desk-chapters">
            <span className="fine">장</span>
            <button
              type="button"
              className={`chip chipbtn ${chapter === "" ? "chip-on" : ""}`}
              onClick={() => setChapter("")}
            >
              전부
            </button>
            {chapters.map((c) => (
              <button
                key={c.firstId}
                type="button"
                className={`chip chipbtn ${chapter === c.firstId ? "chip-on" : ""}`}
                title={`${c.title} — ${c.ids.length}컷`}
                onClick={() => setChapter(c.firstId)}
              >
                {c.title}
              </button>
            ))}
            {/* 장 옮기기 — 컷 ▲▼로 스무 번 누르던 일을 한 번에. 그림·대사는 그대로다 */}
            {chosen && (
              <span className="chapter-move">
                <button
                  type="button"
                  className="chip chipbtn"
                  disabled={chosen.index === 0}
                  title={`${chosen.title}(${chosen.ids.length}컷)을 앞 장과 맞바꿉니다`}
                  onClick={() => moveChapter(chosen.firstId, -1)}
                >
                  ▲ 장 앞으로
                </button>
                <button
                  type="button"
                  className="chip chipbtn"
                  disabled={chosen.index === chapters.length - 1}
                  title={`${chosen.title}(${chosen.ids.length}컷)을 뒤 장과 맞바꿉니다`}
                  onClick={() => moveChapter(chosen.firstId, 1)}
                >
                  ▼ 장 뒤로
                </button>
                {/* 합치기 — 장을 여는 표시는 조판실에만 있었다. 「이 장은 너무 짧다」는
                    판단은 대본을 보며 내리므로 여기서도 뗄 수 있어야 한다 */}
                {chosen.index > 0 && (
                  <button
                    type="button"
                    className="chip chipbtn"
                    title={`${chosen.title}의 「⏎ 새 장에서 시작」을 떼어 앞 장에 붙입니다 — 컷은 그대로입니다`}
                    onClick={() => {
                      const sc = project.story.scenes.find((x) => x.id === chosen.firstId);
                      const w = { ...(sc?.webtoon ?? {}) };
                      delete w.pageBreak;
                      updateScene(chosen.firstId, {
                        webtoon: Object.keys(w).length ? w : undefined,
                      });
                      setChapter("");
                      toast(
                        `「${chosen.title}」을 앞 장에 붙였습니다 — 컷은 그대로고 장 나누기만 없앴어요.`,
                        "ok",
                      );
                    }}
                  >
                    ⤺ 앞 장과 합치기
                  </button>
                )}
                {/* 다음 화로 — 「이 장은 이번 화에 안 들어가겠다」. 찍은 컷이 있으면 막는다:
                    필름이 화를 넘어가면 그림·테이크가 어느 작품에 있는지 헷갈린다 */}
                {chapters.length >= 2 &&
                  (() => {
                    const shot = chosen.ids.filter((id) => {
                      const c = project.cuts[id];
                      return Boolean(
                        c &&
                          (c.imageKey ||
                            c.videoKey ||
                            (c.takeKeys?.length ?? 0) > 0 ||
                            c.status !== "wait"),
                      );
                    }).length;
                    return (
                      <button
                        type="button"
                        className="chip chipbtn"
                        disabled={shot > 0}
                        title={
                          shot > 0
                            ? `이미 찍은 컷이 ${shot}개 있어 보낼 수 없습니다 — 찍은 필름은 화를 넘기지 않습니다. 순서만 바꾸려면 ▲▼를 쓰세요`
                            : `${chosen.title}의 ${chosen.ids.length}컷을 새 화의 첫 장으로 옮깁니다 — 화풍·노트·배우가 함께 갑니다`
                        }
                        onClick={() => void pushChapterToNextEpisode(chosen.firstId)}
                      >
                        ▶ 다음 화로
                      </button>
                    );
                  })()}
              </span>
            )}
          </span>
        )}
        <span className="desk-view">
          <button
            type="button"
            className={`chip chipbtn ${view === "card" ? "chip-on" : ""}`}
            title="컷마다 전체 편집 카드"
            onClick={() => pickView("card")}
          >
            🗂 카드
          </button>
          <button
            type="button"
            className={`chip chipbtn ${view === "list" ? "chip-on" : ""}`}
            title="한 줄 요약 목록 — 탭하면 그 자리에서 펼쳐집니다"
            onClick={() => pickView("list")}
          >
            ☰ 목록
          </button>
        </span>
        <span className="fine desk-length" title="타자기 속도 기준 대략치 — 선택지 대기 시간은 빼고">
          {totalChars.toLocaleString()}자 · 약 {estLabel}
        </span>
        {filtered && (
          <span className="fine desk-count">
            {visible.length}/{project.story.scenes.length}컷
            <button
              className="btn btn-ghost btn-small"
              onClick={() => {
                setQuery("");
                setStatus("all");
                setChapter("");
              }}
            >
              초기화
            </button>
          </span>
        )}
      </div>
      {visible.length === 0 && (
        <p className="fine">조건에 맞는 컷이 없습니다 — 검색어나 필터를 풀어보세요.</p>
      )}
      {view === "card" ? (
        <div className="cards">
          {visible.map((scene) => (
            <Fragment key={scene.id}>
              {chapterHead(scene.id)}
              <CutScriptCard
                scene={scene}
                index={indexOf.get(scene.id) ?? 0}
                total={project.story.scenes.length}
                sceneIds={sceneIds}
              />
            </Fragment>
          ))}
        </div>
      ) : (
        <div className="cutlist">
          {visible.map((scene) => {
            const cut = project.cuts[scene.id];
            const isOpen = expanded === scene.id;
            return (
              <div key={scene.id} id={isOpen ? undefined : `cut-${scene.id}`}>
                {chapterHead(scene.id)}
                <button
                  type="button"
                  className={`cutlist-row ${isOpen ? "row-on" : ""}`}
                  onClick={() => setExpanded((e) => (e === scene.id ? null : scene.id))}
                >
                  <span className="chip chip-strong">#{(indexOf.get(scene.id) ?? 0) + 1}</span>
                  <span className="chip">{scene.id}</span>
                  {cut?.status === "ok" && <span className="badge badge-ok">OK</span>}
                  {cut?.status === "ng" && <span className="badge badge-ng">NG</span>}
                  {scene.choices && scene.choices.length > 0 && (
                    <span className="chip" title="선택지 갈래">
                      ⑂{scene.choices.length}
                    </span>
                  )}
                  {scene.bgm !== undefined && <span className="chip">🎵</span>}
                  <span className="row-text">{scene.text?.trim() || "—"}</span>
                </button>
                {isOpen && (
                  <CutScriptCard
                    scene={scene}
                    index={indexOf.get(scene.id) ?? 0}
                    total={project.story.scenes.length}
                    sceneIds={sceneIds}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function EmptyState() {
  const newProject = useStudio((s) => s.newProject);
  const openSample = useStudio((s) => s.openSample);
  return (
    <div className="empty">
      <div className="empty-inner">
        <h1>잠들기 전, 책상 위의 야간 촬영장</h1>
        <p>
          당신은 혼자 찍는 감독입니다. 대본실에서 컷을 쓰고, 배우를 캐스팅하고, 촬영장에서 같은
          얼굴을 찍고, 시사실에서 혼자 봅니다. 전부 이 기기 안에서.
        </p>
        <div className="empty-actions">
          <button className="btn btn-primary" onClick={() => void newProject()}>
            새 프로젝트
          </button>
          <button className="btn" onClick={() => void openSample()}>
            샘플 「비 오는 역의 약속」 열기
          </button>
        </div>
      </div>
    </div>
  );
}
