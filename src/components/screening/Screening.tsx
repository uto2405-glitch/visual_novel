/** 시사실 — 이어진 OK 구간만 재생. 플레이 중 API 호출 없음. */
import { useEffect } from "react";
import { useStudio } from "../../store/useStudio";
import { stopAmbience } from "../../lib/ambience";
import { stopMusic } from "../../lib/music";
import { ScreenStage } from "./ScreenStage";
import { ScreenControls } from "./ScreenControls";

export function Screening() {
  const project = useStudio((s) => s.project);
  // 시사실을 떠나면 소리도 음악도 그친다
  useEffect(() => {
    return () => {
      stopAmbience();
      stopMusic();
    };
  }, []);
  if (!project) {
    return (
      <div className="room">
        <p className="notice">시사할 프로젝트가 없습니다. 대본실에서 먼저 대본을 열어주세요.</p>
      </div>
    );
  }
  return (
    <div className="room">
      {/* 건너뛰기 링크의 도착지 — 시사실의 «일하는 자리»는 화면 자체다 */}
      <div id="work" tabIndex={-1}>
        <ScreenStage />
      </div>
      <ScreenControls />
    </div>
  );
}
