/** 스테이지 — 타자기 대사, 페이드 전환, 선택지, 자동 상영, 안내/크레딧 오버레이. */
import { useEffect, useRef, useState } from "react";
import { anyModalOpen, chooseNext, useStudio } from "../../store/useStudio";
import { isSfxKind, typeTick, updateAmbience } from "../../lib/ambience";
import { isMusicOn, startMusic } from "../../lib/music";
import { speakerName } from "../../lib/story";
import { useCutImageUrl, useCutVideoUrl, useProject } from "../hooks";
import { CreditsRoll } from "./CreditsRoll";

const AUTOPLAY_DELAY_MS = 2400;

export function ScreenStage() {
  const project = useProject();
  const playSceneId = useStudio((s) => s.playSceneId);
  const playBlockedAt = useStudio((s) => s.playBlockedAt);
  const playChapterEnd = useStudio((s) => s.playChapterEnd);
  const resumePastChapter = useStudio((s) => s.resumePastChapter);
  const clearChapterStop = useStudio((s) => s.clearChapterStop);
  const playEnded = useStudio((s) => s.playEnded);
  const playEpoch = useStudio((s) => s.playEpoch);
  const autoPlay = useStudio((s) => s.autoPlay);
  const ambienceOn = useStudio((s) => s.ambienceOn);
  const advancePlay = useStudio((s) => s.advancePlay);
  const restartPlay = useStudio((s) => s.restartPlay);
  const continuePlay = useStudio((s) => s.continuePlay);
  const clearBlocked = useStudio((s) => s.clearBlocked);
  const dismissEnd = useStudio((s) => s.dismissEnd);
  const backPlay = useStudio((s) => s.backPlay);
  const setTab = useStudio((s) => s.setTab);

  const scene = playSceneId
    ? project.story.scenes.find((sc) => sc.id === playSceneId)
    : null;
  const url = useCutImageUrl(playSceneId ?? "");
  const videoUrl = useCutVideoUrl(playSceneId ?? "");
  const posterUrl = useCutImageUrl(project.posterSceneId ?? "");

  // 타자기 — 대사가 한 글자씩 흐른다. 클릭하면 문장 완성, 한 번 더 클릭하면 다음 컷.
  // epoch가 바뀌면 렌더 중 상태 조정으로 0에서 재시작한다 (같은 컷 재상영 포함).
  const text = scene?.text ?? "";
  const typeMs = useStudio((s) => s.typeMs);
  const fontScale = useStudio((s) => s.fontScale);
  const [typedLen, setTypedLen] = useState(0);
  const [lastEpoch, setLastEpoch] = useState(playEpoch);
  if (lastEpoch !== playEpoch) {
    setLastEpoch(playEpoch);
    setTypedLen(0);
  }
  useEffect(() => {
    if (typedLen >= text.length) return;
    const t = setTimeout(() => {
      if (typedLen % 2 === 0) typeTick(); // 앰비언스 켜짐일 때만 소리 남 (내부 가드)
      setTypedLen((n) => Math.min(n + 1, text.length));
    }, typeMs);
    return () => clearTimeout(t);
  }, [typedLen, text, typeMs]);

  // 장면 앰비언스 — sfx를 따라 크로스페이드. 꺼져 있으면 침묵.
  const sfx = scene?.sfx;
  useEffect(() => {
    updateAmbience(ambienceOn && isSfxKind(sfx) ? sfx : null);
  }, [ambienceOn, sfx]);

  // 장면별 음악 — bgm:true면 이 컷부터 시작, false면 정지, 생략이면 그대로
  const musicOn = useStudio((s) => s.musicOn);
  const setMusicOn = useStudio((s) => s.setMusicOn);
  const bgm = scene?.bgm;
  useEffect(() => {
    if (bgm === true) setMusicOn(true);
    else if (bgm === false) setMusicOn(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playEpoch]);
  // 시사실 재진입 시 — 마스터가 켜져 있던 상태면 음악을 다시 잇는다
  useEffect(() => {
    if (musicOn && !isMusicOn()) startMusic();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleAdvance = () => {
    if (playEnded) {
      dismissEnd();
      return;
    }
    if (scene && typedLen < text.length) {
      setTypedLen(text.length); // 먼저 문장을 끝까지
      return;
    }
    advancePlay();
  };
  // 스와이프 — 왼쪽으로 밀면 다음, 오른쪽으로 밀면 되감기. 스와이프 뒤의 유령 click은 무시.
  const touchX = useRef<number | null>(null);
  const swiped = useRef(false);
  const advanceRef = useRef(handleAdvance);
  useEffect(() => {
    advanceRef.current = handleAdvance; // 렌더 밖에서 최신 핸들러를 유지
  });

  // Space / Enter → 다음. 모달이 떠 있거나 버튼(선택지·슬롯)이 포커스면 건드리지 않는다.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (anyModalOpen()) return;
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(target.tagName)) return;
      if (target?.closest?.(".modal-backdrop")) return;
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        advanceRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // 자동 상영 — 문장이 다 흐르고 잠시 뒤 다음 컷 (선택지·엔딩·안내에서는 멈춘다)
  useEffect(() => {
    if (!autoPlay || !scene || playEnded || playBlockedAt || playChapterEnd) return;
    if (typedLen < text.length) return;
    if (scene.choices?.length) return;
    const t = setTimeout(() => advancePlay(), AUTOPLAY_DELAY_MS);
    return () => clearTimeout(t);
  }, [autoPlay, scene, playEnded, playBlockedAt, playChapterEnd, typedLen, text, advancePlay]);

  const speaker = scene ? speakerName(project.story, scene) : "";

  return (
    <div className="screen-wrap">
      <div
        className="screen-stage"
        onClick={() => {
          if (swiped.current) {
            swiped.current = false; // 방금 스와이프였다 — 이 클릭은 무시
            return;
          }
          handleAdvance();
        }}
        onTouchStart={(e) => {
          touchX.current = e.touches[0]?.clientX ?? null;
        }}
        onTouchEnd={(e) => {
          const x0 = touchX.current;
          touchX.current = null;
          if (x0 === null) return;
          const dx = (e.changedTouches[0]?.clientX ?? x0) - x0;
          if (Math.abs(dx) <= 60) return;
          swiped.current = true;
          if (dx < 0) handleAdvance();
          else backPlay();
        }}
      >
        {scene && !playEnded && (
          <div className="screen-progress" title="지금 흐르는 컷 / 전체 컷">
            {project.story.scenes.findIndex((sc) => sc.id === scene.id) + 1}/
            {project.story.scenes.length}
          </div>
        )}
        {scene && videoUrl ? (
          <video
            key={playEpoch}
            className="screen-bg fade-in"
            src={videoUrl}
            autoPlay
            loop
            muted
            playsInline
          />
        ) : scene && url ? (
          <img key={playEpoch} className="screen-bg fade-in" src={url} alt={scene.id} />
        ) : (
          !playEnded && (
            <div className="screen-poster">
              {posterUrl && <img className="poster-bg" src={posterUrl} alt="" />}
              <div className="poster-front">
                <h1>{project.title}</h1>
                <p className="fine">클릭하거나 아래에서 시작해 주세요.</p>
              </div>
            </div>
          )
        )}

        {scene && !playEnded && (
          <div className="dialogue" style={fontScale !== 1 ? { fontSize: `${fontScale}em` } : undefined}>
            {speaker && <div className="who">{speaker}</div>}
            <div className="line">
              {text.slice(0, typedLen)}
              {typedLen < text.length && <span className="caret">▌</span>}
            </div>
          </div>
        )}

        {scene?.choices && typedLen >= text.length && !playEnded && (
          <div className="choices" onClick={(e) => e.stopPropagation()}>
            {scene.choices.map((c) => (
              <button key={c.next} className="choice" onClick={() => chooseNext(c.label, c.next)}>
                {c.label}
              </button>
            ))}
          </div>
        )}

        {!scene && !playBlockedAt && !playEnded && (
          <div className="choices" onClick={(e) => e.stopPropagation()}>
            <button className="choice" onClick={restartPlay}>
              처음부터
            </button>
            <button className="choice" onClick={continuePlay}>
              이어하기
            </button>
          </div>
        )}

        {playEnded && <CreditsRoll />}

        {/* 장 끝 — «막이 내린 것»이 아니라 «여기까지 봤다»이므로 크레딧이 아니라 안내를 낸다 */}
        {playChapterEnd && !playBlockedAt && (
          <div className="blocked chapend" onClick={(e) => e.stopPropagation()}>
            <p>
              「<b>{playChapterEnd}</b>」 여기까지입니다.
            </p>
            <p className="fine">
              이 장만 상영하도록 골랐어요. 이어서 보면 다음 장으로 넘어갑니다.
            </p>
            <div className="blocked-actions">
              <button className="btn btn-primary" onClick={resumePastChapter}>
                이어서 보기
              </button>
              <button className="btn btn-ghost" onClick={clearChapterStop}>
                여기서 멈추기
              </button>
            </div>
          </div>
        )}

        {playBlockedAt && (
          <div className="blocked" onClick={(e) => e.stopPropagation()}>
            <p>
              <b>{playBlockedAt}</b> 컷은 아직 촬영 전입니다.
            </p>
            <p className="fine">
              시사는 이어진 OK 구간까지만 흐릅니다. 촬영장에서 이 컷을 찍고 돌아오세요.
            </p>
            <div className="blocked-actions">
              <button
                className="btn btn-primary"
                onClick={() => {
                  clearBlocked();
                  setTab("stage");
                }}
              >
                촬영장으로
              </button>
              <button className="btn btn-ghost" onClick={clearBlocked}>
                닫기
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
