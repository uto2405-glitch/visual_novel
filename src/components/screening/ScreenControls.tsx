/** 시사실 조작부 — 재생/슬롯/자동 상영/앰비언스/음악/컷 목록/시사만 보내기. */
import { useState } from "react";
import { useStudio } from "../../store/useStudio";
import { chapterOf, chapterRanges } from "../../lib/chapters";
import { fmtTime } from "../../lib/format";
import { speakerName } from "../../lib/story";
import { useCutImageUrl } from "../hooks";

/** 세이브 슬롯의 장면 미리보기 — 어디서 멈췄는지 한눈에. */
function SlotThumb({ sceneId }: { sceneId: string }) {
  const url = useCutImageUrl(sceneId);
  if (!url) return null;
  return <img className="slot-thumb" src={url} alt="" />;
}

export function ScreenControls() {
  const restartPlay = useStudio((s) => s.restartPlay);
  const continuePlay = useStudio((s) => s.continuePlay);
  const backPlay = useStudio((s) => s.backPlay);
  const showScene = useStudio((s) => s.showScene);
  const playChapter = useStudio((s) => s.playChapter);
  const clearChapterStop = useStudio((s) => s.clearChapterStop);
  const scenes = useStudio((s) => s.project?.story.scenes ?? []);
  const story = useStudio((s) => s.project?.story);
  const cuts = useStudio((s) => s.project?.cuts ?? {});
  const [tocOpen, setTocOpen] = useState(false);
  // 컷이 많아지면 목록만으로도 스크롤이 몇 화면이 된다(60컷 ≈ 5화면) — 그때만 걸러내기를 준다
  const [tocQuery, setTocQuery] = useState("");
  /** 장의 첫 컷들 — 인쇄본과 같은 기준(webtoon.pageBreak)으로 센다 */
  const chapterStarts = chapterRanges(scenes).map((c) => ({
    id: c.firstId,
    lastId: c.ids[c.ids.length - 1],
    title: c.title,
    ok: cuts[c.firstId]?.status === "ok" && Boolean(cuts[c.firstId]?.imageKey),
  }));
  // 「장부터」만 있고 「장까지」가 없었다 — 연재를 장 단위로 검토할 때는 끝에서 멈춰야 한다
  const [stopAtChapterEnd, setStopAtChapterEnd] = useState(false);
  const playHistory = useStudio((s) => s.playHistory);
  const autoPlay = useStudio((s) => s.autoPlay);
  const setAutoPlay = useStudio((s) => s.setAutoPlay);
  const exportScreeningHtml = useStudio((s) => s.exportScreeningHtml);
  const saveSlots = useStudio((s) => s.saveSlots);
  const saveToSlot = useStudio((s) => s.saveToSlot);
  const loadFromSlot = useStudio((s) => s.loadFromSlot);
  const deleteSlot = useStudio((s) => s.deleteSlot);
  const playSceneId = useStudio((s) => s.playSceneId);
  /** 지금 보고 있는 컷이 속한 장 — 「이 장만 시사본으로」의 대상 (아직 안 봤으면 첫 장) */
  const hereChapter = (() => {
    const ranges = chapterRanges(scenes);
    if (ranges.length < 2) return undefined;
    return (playSceneId ? chapterOf(ranges, playSceneId) : undefined) ?? ranges[0];
  })();
  const ambienceOn = useStudio((s) => s.ambienceOn);
  const setAmbienceOn = useStudio((s) => s.setAmbienceOn);
  const musicOn = useStudio((s) => s.musicOn);
  const setMusicOn = useStudio((s) => s.setMusicOn);
  const typeMs = useStudio((s) => s.typeMs);
  const setTypeMs = useStudio((s) => s.setTypeMs);
  const fontScale = useStudio((s) => s.fontScale);
  const setFontScale = useStudio((s) => s.setFontScale);
  const setPrintOpen = useStudio((s) => s.setPrintOpen);

  const fullscreen = () => {
    const el = document.querySelector(".screen-stage");
    if (el && document.fullscreenElement == null) {
      void (el as HTMLElement).requestFullscreen?.();
    } else if (document.fullscreenElement) {
      void document.exitFullscreen();
    }
  };

  return (
    <section className="panel">
      <div className="panel-actions wrap">
        <button className="btn" onClick={restartPlay}>
          처음부터
        </button>
        <button className="btn btn-primary" onClick={continuePlay}>
          이어하기
        </button>
        <button className="btn" disabled={playHistory.length === 0} onClick={backPlay}>
          이전
        </button>
        {/* 컷 목록 — 내보낸 시사본에는 있는데 앱 안에는 없었다. 긴 작품에서 되감기만으로
            돌아가려면 수십 번 눌러야 한다. 기본은 접혀 있다(선형 감상을 방해하지 않게). */}
        <button
          className={`btn ${tocOpen ? "btn-toggled" : ""}`}
          title="컷 목록 — 보고 싶은 데로 바로"
          onClick={() => setTocOpen((v) => !v)}
        >
          ☰ 목록
        </button>
        <button className="btn" onClick={fullscreen}>
          풀스크린
        </button>
        <button
          className={`btn ${autoPlay ? "btn-toggled" : ""}`}
          onClick={() => setAutoPlay(!autoPlay)}
          title="문장이 다 흐르면 2.4초 뒤 다음 컷으로 넘어갑니다"
        >
          {autoPlay ? "⏸ 자동 상영 중" : "▶ 자동 상영"}
        </button>
        <button
          className={`btn ${ambienceOn ? "btn-toggled" : ""}`}
          onClick={() => setAmbienceOn(!ambienceOn)}
          title="장면의 소리(비·바람·밤)와 타자기 틱 — 전부 즉석 합성, 외부 파일 없음. 장면의 「소리」 설정을 따라갑니다"
        >
          {ambienceOn ? "🔊 앰비언스 중" : "🔊 앰비언스"}
        </button>
        <button
          className={`btn ${musicOn ? "btn-toggled" : ""}`}
          onClick={() => setMusicOn(!musicOn)}
          title="밤의 음악 — 즉석 생성 BGM. 컷의 🎵 설정(시작/정지)이 자동으로 켜고 끄기도 합니다"
        >
          {musicOn ? "🎵 음악 중" : "🎵 음악"}
        </button>
        <label className="screen-pref" title="대사가 흐르는 속도">
          <span className="fine">타자</span>
          <select value={typeMs} onChange={(e) => setTypeMs(Number(e.target.value))}>
            <option value={40}>느긋</option>
            <option value={26}>보통</option>
            <option value={12}>빠름</option>
          </select>
        </label>
        <label className="screen-pref" title="대사 글자 크기">
          <span className="fine">글자</span>
          <select value={fontScale} onChange={(e) => setFontScale(Number(e.target.value))}>
            <option value={1}>보통</option>
            <option value={1.25}>크게</option>
          </select>
        </label>
        <span className="spacer" />
        <button
          className="btn btn-ghost"
          title="찍어둔 OK 컷을 말풍선 붙인 만화 페이지(PNG)로 옮깁니다 — 크레딧을 쓰지 않습니다"
          onClick={() => setPrintOpen(true)}
        >
          🖨 인쇄본 만들기
        </button>
        <button className="btn btn-ghost" onClick={() => void exportScreeningHtml()}>
          시사만 보내기 (HTML)
        </button>
        {/* 이 장만 — 연재는 화마다 파일 하나로 준다. 지금 보고 있는 컷이 속한 장을 담는다 */}
        {hereChapter && (
          <button
            className="btn btn-ghost"
            title={`지금 보고 있는 컷이 속한 장만 담습니다 — 「${hereChapter.title}」의 찍은 컷과 그림만 들어가고, 장 밖으로 이어지는 연결은 끊깁니다`}
            onClick={() => void exportScreeningHtml(hereChapter.firstId)}
          >
            📄 「{hereChapter.title}」만
          </button>
        )}
      </div>
      {/* 장별 상영 — 연재 합본을 장 단위로 본다. 장이 둘 이상일 때만 나온다. */}
      {tocOpen && chapterStarts.length >= 2 && (
        <div className="chiprow screen-chapters">
          <span className="fine">{stopAtChapterEnd ? "이 장만" : "장부터"}</span>
          {chapterStarts.map((c) => (
            <button
              key={c.id}
              type="button"
              // chapchip — 이 줄에는 장 칩 말고 토글도 산다. 「장이 몇 개냐」를 세는 쪽이
              // 토글까지 세지 않도록 장 칩에만 이름을 붙인다
              className="chip chipbtn chapchip"
              disabled={!c.ok}
              title={
                !c.ok
                  ? `${c.title} — 첫 컷을 아직 찍지 않았습니다`
                  : stopAtChapterEnd
                    ? `${c.title}만 상영 — 그 장 끝에서 멈춥니다`
                    : `${c.title}부터 상영`
              }
              onClick={() => {
                setTocOpen(false);
                if (stopAtChapterEnd) playChapter(c.id, c.lastId, c.title);
                else {
                  clearChapterStop();
                  showScene(c.id);
                }
              }}
            >
              {c.title}
            </button>
          ))}
          <button
            type="button"
            className={`chip chipbtn ${stopAtChapterEnd ? "chip-on" : ""}`}
            aria-pressed={stopAtChapterEnd}
            title="켜면 고른 장의 마지막 컷에서 멈춥니다 — 다음 장으로 넘어가지 않아요"
            onClick={() => setStopAtChapterEnd((v) => !v)}
          >
            ⏹ 장 끝에서 멈춤
          </button>
        </div>
      )}
      {tocOpen && (
        <div className="screen-toc">
          {scenes.length > 20 && (
            <input
              className="toc-search"
              value={tocQuery}
              placeholder="대사·화자·컷 제목으로 찾기"
              onChange={(e) => setTocQuery(e.target.value)}
            />
          )}
          {scenes.map((sc, i) => {
            // 대사·컷 id·화자 이름으로 찾는다 — 「하나가 말하는 컷」을 떠올려 찾는 일이 잦다
            const q = tocQuery.trim();
            if (q) {
              const who = story && sc.speaker && sc.speaker !== "narration" ? speakerName(story, sc) : "내레이션";
              // 컷 제목(장 제목)까지 본다 — 연재에서 「3장」으로 찾는 일이 잦다
              const cap = sc.webtoon?.caption ?? "";
              const hay = `${sc.text ?? ""} ${sc.id} ${who} ${cap}`;
              if (!hay.includes(q)) return null;
            }
            const cut = cuts[sc.id];
            const okCut = cut?.status === "ok" && Boolean(cut.imageKey);
            return (
              <TocRow
                key={sc.id}
                scene={sc}
                index={i + 1}
                okCut={okCut}
                current={sc.id === playSceneId}
                onJump={() => {
                  setTocOpen(false);
                  // 목록에서 아무 컷으로나 건너뛰면 장 단위 멈춤은 푼다 — 어디서 멈출지 알 수 없다
                  clearChapterStop();
                  showScene(sc.id);
                }}
              />
            );
          })}
        </div>
      )}
      <div className="slots">
        {[1, 2, 3].map((n) => {
          const slot = saveSlots[n - 1];
          return (
            <div key={n} className="slot">
              <div className="slot-head">
                {slot && <SlotThumb sceneId={slot.sceneId} />}
                슬롯 {n}
                <span className="fine">
                  {slot ? ` · ${slot.sceneId} · ${fmtTime(slot.timestamp)}` : " · 비어 있음"}
                </span>
              </div>
              <div className="slot-actions">
                <button
                  className="btn btn-small"
                  disabled={!playSceneId}
                  onClick={() => void saveToSlot(n)}
                >
                  저장
                </button>
                <button className="btn btn-small" disabled={!slot} onClick={() => void loadFromSlot(n)}>
                  불러오기
                </button>
                <button
                  className="btn btn-small btn-ghost"
                  disabled={!slot}
                  onClick={() => void deleteSlot(n)}
                >
                  삭제
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <p className="fine">
        클릭 / Space / Enter — 문장이 흐르는 중이면 끝까지, 다 흐른 뒤면 다음 컷. 시사 중에는
        카메라(MakeFun)를 부르지 않습니다 — 이미 찍힌 필름만 흐릅니다.
      </p>
    </section>
  );
}

/** 컷 목록의 한 줄 — 작은 그림이 있으면 대사보다 빨리 찾는다. */
function TocRow({
  scene,
  index,
  okCut,
  current,
  onJump,
}: {
  scene: { id: string; text?: string };
  index: number;
  okCut: boolean;
  current: boolean;
  onJump: () => void;
}) {
  const url = useCutImageUrl(scene.id);
  const txt = (scene.text ?? "").trim().slice(0, 24);
  return (
    <button
      type="button"
      className={`chip chipbtn toc-row ${current ? "chip-on" : ""}`}
      disabled={!okCut}
      title={okCut ? scene.id : `${scene.id} — 아직 찍지 않은 컷`}
      onClick={onJump}
    >
      {url ? <img className="toc-thumb" src={url} alt="" /> : <span className="toc-thumb" />}
      <span className="fine">{index}</span> {txt || "(대사 없음)"}
    </button>
  );
}
