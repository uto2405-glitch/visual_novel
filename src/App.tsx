import { useEffect, useState } from "react";
import { useStudio } from "./store/useStudio";
import { VERSION } from "./version";
import { ScriptRoom } from "./components/script/ScriptRoom";
import { Stage } from "./components/stage/Stage";
import { Screening } from "./components/screening/Screening";
import { PrintRoom } from "./components/screening/PrintRoom";
import { ScrollJump } from "./components/ScrollJump";
import {
  ConfirmModal,
  HelpModal,
  PromptModal,
  SettingsModal,
  ToastHost,
} from "./components/Modals";

/** 방 이름 — 낭독기용 제목에 쓴다(탭에 적힌 말과 같아야 «여기»를 알 수 있다) */
const ROOM_NAMES: Record<string, string> = { script: "대본실", stage: "촬영장", screening: "시사실" };

export default function App() {
  const tab = useStudio((s) => s.tab);
  const setTab = useStudio((s) => s.setTab);
  const enterScreening = useStudio((s) => s.enterScreening);
  const boot = useStudio((s) => s.boot);
  const project = useStudio((s) => s.project);
  const saveFailed = useStudio((s) => s.saveFailed);
  const unsaved = useStudio((s) => s.unsaved);
  const setSettingsOpen = useStudio((s) => s.setSettingsOpen);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    void boot();
  }, [boot]);

  // 닫기/새로고침 전 미저장 경고
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (useStudio.getState().unsaved) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);

  return (
    <div className="app">
      {/* 본문으로 건너뛰기 — 대본실에는 보이는 단추가 77개고, 키보드로 첫 컷까지 탭 42번이었다(실측).
          평소에는 화면 밖에 있고 키보드 초점이 오면 나타난다(마우스 쓰는 사람에게는 보이지 않는다). */}
      <a className="skiplink" href="#work">
        작업 영역으로 건너뛰기
      </a>
      <header className="header">
        <div className="brand" title="잠들기 전, 책상 위의 야간 촬영장">
          <span className="brand-mark">🎬</span>
          <span className="brand-name">비주얼노벨 스튜디오</span>
          {project && (
            <span className="brand-project" title={project.title}>
              {project.title}
              {unsaved && (
                <em
                  className={`unsaved-dot ${saveFailed ? "unsaved-fail" : ""}`}
                  title={
                    saveFailed
                      ? "저장 공간이 가득 차 저장하지 못했습니다 — 필름캔으로 내보내 두세요"
                      : "아직 넣지 않은 촬영분이 있습니다"
                  }
                />
              )}
            </span>
          )}
        </div>
        <nav className="tabs">
          <button className={`tab ${tab === "script" ? "active" : ""}`} onClick={() => setTab("script")}>
            대본실
          </button>
          <button className={`tab ${tab === "stage" ? "active" : ""}`} onClick={() => setTab("stage")}>
            촬영장
          </button>
          <button
            className={`tab ${tab === "screening" ? "active" : ""}`}
            onClick={() => setTab("screening")}
          >
            시사실
          </button>
        </nav>
        <div className="header-right">
          <button className="btn btn-primary" onClick={enterScreening} title="시사실로 갑니다">
            ▶ 시사
          </button>
          <span className="ver">{VERSION}</span>
          <button className="btn btn-ghost" onClick={() => setSettingsOpen(true)}>
            카메라 설정
          </button>
          <button
            className="btn btn-ghost btn-help"
            title="감독 수첩 — 흐름·비용·팁"
            onClick={() => setHelpOpen(true)}
          >
            ?
          </button>
        </div>
      </header>

      <main className="main" id="room-main" tabIndex={-1}>
        {/* 낭독기용 방 제목 — 작품을 열면 화면의 제목들이 모두 h2로 시작해 «제목 1»로 갈 곳이 없었다
            (폰 390px 실측: h2 여섯 개, h1 0개). 눈에는 보이지 않고 낭독 순서에만 놓인다. */}
        <h1 className="sronly">
          {project ? `${project.title} — ${ROOM_NAMES[tab]}` : ROOM_NAMES[tab]}
        </h1>
        {tab === "script" && <ScriptRoom />}
        {tab === "stage" && <Stage />}
        {tab === "screening" && <Screening />}
      </main>

      {/* 긴 목록의 끝과 끝 — 문서가 한 화면 넘게 길 때만 나온다 */}
      <ScrollJump />
      <SettingsModal />
      <PrintRoom />
      <ConfirmModal />
      <PromptModal />
      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />
      <ToastHost />
    </div>
  );
}
