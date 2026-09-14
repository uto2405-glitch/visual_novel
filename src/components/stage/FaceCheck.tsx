/** 페이스 체크 모니터 — 「이 사람이 오늘 밤에도 같은 얼굴인가」를 캐스팅 사진과
 *  나란히 놓고 확인하는 감독의 모니터. 판정(OK/NG)도 여기서 내린다.
 *  모바일: 좌우 스와이프로 컷 이동. */
import { useEffect, useRef, useState } from "react";
import { anyModalOpen, useStudio } from "../../store/useStudio";
import { emptyCut } from "../../types";
import { useEscapeClose, useObjectUrl, useFocusTrap } from "../../lib/hooks";
import { useCharPhoto, useCutImageUrl, useCutVideoUrl, useProject } from "../hooks";
import { StatusBadge } from "../StatusBadge";

/** 처음에 펼쳐 두는 테이크 수 — 네 줄이면 아래 단추가 화면에 남는다(실측: 99장이면 33줄). */
const TAKES_SHOWN = 12;

export function FaceCheck({
  sceneId,
  onClose,
  onNav,
}: {
  sceneId: string;
  onClose: () => void;
  onNav: (dir: number) => void;
}) {
  const project = useProject();
  const scene = project.story.scenes.find((sc) => sc.id === sceneId);
  const cut = project.cuts[sceneId] ?? emptyCut();
  const url = useCutImageUrl(sceneId);
  const shooting = useStudio((s) => Boolean(s.shooting[sceneId]));
  const batchRunning = useStudio((s) => Boolean(s.batch?.running));
  const shootSingle = useStudio((s) => s.shootSingle);
  const markNg = useStudio((s) => s.markNg);
  const markOk = useStudio((s) => s.markOk);
  const makeMovingCut = useStudio((s) => s.makeMovingCut);
  const pullResultFor = useStudio((s) => s.pullResultFor);
  const setPoster = useStudio((s) => s.setPoster);
  const enterScreening = useStudio((s) => s.enterScreening);
  const showScene = useStudio((s) => s.showScene);
  const isPoster = useStudio((s) => s.project?.posterSceneId === sceneId);
  const videoUrl = useCutVideoUrl(sceneId);
  const revertTake = useStudio((s) => s.revertTake);
  const clearTakes = useStudio((s) => s.clearTakes);
  const touchX = useRef<number | null>(null);

  // 테이크 A/B 비교 — 「같은 얼굴인가」를 슬라이더로 겹쳐 본다
  const [compare, setCompare] = useState<{ key: string; index: number } | null>(null);
  const [slider, setSlider] = useState(50);
  /* 테이크가 많이 쌓인 컷은 «벽»이 된다: 99장이면 33줄 1,529px이 되어
     아래에 있는 「이 컷만 다시」·NG 판정이 화면 밖(y 1,779px)으로 밀렸다(실측 v1.0.0).
     그래서 최근 것만 펼쳐 두고 나머지는 접는다 — 배우단 선반의 「외 N편 ▾」과 같은 규칙. */
  const [allTakes, setAllTakes] = useState(false);
  const compareBlob = useStudio((s) => (compare ? s.blobs[compare.key] : undefined));
  const compareUrl = useObjectUrl(compareBlob);
  // 컷을 넘기면 비교를 접는다 — 렌더 중 상태 조정 (effect-setState 금지 규칙 준수)
  const [lastScene, setLastScene] = useState(sceneId);
  if (lastScene !== sceneId) {
    setLastScene(sceneId);
    setCompare(null);
    setSlider(50);
    setAllTakes(false); // 컷을 넘기면 다시 접는다
  }

  // 닫기는 공용 Escape 스택에 맡긴다 — 위에 확인창이 겹치면 그쪽이 먼저 먹는다
  useEscapeClose(true, onClose);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 위에 다른 모달(설정·확인·입력)이 떠 있으면 건드리지 않는다
      if (anyModalOpen()) return;
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (e.key === "ArrowLeft") onNav(-1);
      if (e.key === "ArrowRight") onNav(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onNav]);

  // 초점은 이 창 안에 머문다 — 뒤의 컷 카드들을 키보드로 만지게 되면 안 된다
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box, Boolean(scene));
  if (!scene) return null;

  const idx = project.story.scenes.findIndex((sc) => sc.id === sceneId);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="facecheck"
        ref={box}
        onClick={(e) => e.stopPropagation()}
        onTouchStart={(e) => {
          touchX.current = e.touches[0]?.clientX ?? null;
        }}
        onTouchEnd={(e) => {
          const x0 = touchX.current;
          touchX.current = null;
          if (x0 === null) return;
          const dx = (e.changedTouches[0]?.clientX ?? x0) - x0;
          if (Math.abs(dx) > 60) onNav(dx < 0 ? 1 : -1); // 왼쪽으로 밀면 다음 컷
        }}
      >
        <div className="fc-main">
          <div className="fc-stage">
            {compare && url && compareUrl ? (
              <div className="fc-compare">
                <img src={url} alt="현재" />
                <img
                  src={compareUrl}
                  alt="테이크"
                  className="fc-compare-top"
                  style={{ clipPath: `inset(0 ${100 - slider}% 0 0)` }}
                />
                <span className="fc-ab fc-ab-a">테이크</span>
                <span className="fc-ab fc-ab-b">현재</span>
              </div>
            ) : videoUrl ? (
              <video src={videoUrl} autoPlay loop muted playsInline controls />
            ) : url ? (
              <img src={url} alt={scene.id} />
            ) : (
              <div className="fc-empty">아직 이 컷의 필름이 없습니다</div>
            )}
            <button className="fc-nav fc-prev" onClick={() => onNav(-1)} title="이전 컷 (←)">
              ‹
            </button>
            <button className="fc-nav fc-next" onClick={() => onNav(1)} title="다음 컷 (→)">
              ›
            </button>
            <div className="cutcard-badges">
              <StatusBadge status={cut.status} shooting={shooting} delayed={cut.delayed} />
            </div>
          </div>
          {compare && (
            <div className="fc-compare-bar">
              <input
                type="range"
                min={0}
                max={100}
                value={slider}
                onChange={(e) => setSlider(Number(e.target.value))}
              />
              <button
                className="btn btn-small"
                onClick={() => {
                  revertTake(sceneId, compare.index);
                  setCompare(null);
                }}
              >
                ← 이 테이크로 복귀
              </button>
              <button className="btn btn-small btn-ghost" onClick={() => setCompare(null)}>
                비교 닫기
              </button>
            </div>
          )}
          <p className="fc-line">
            <span className="chip chip-strong">#{idx + 1}</span>{" "}
            <span className="chip">{scene.id}</span> {scene.text || ""}
          </p>
        </div>
        <div className="fc-side">
          <h3>캐스팅 대조</h3>
          {(scene.chars ?? []).length === 0 && (
            <p className="fine">이 컷에는 등장 배우가 없습니다.</p>
          )}
          {(scene.chars ?? []).map((cid) => (
            <FaceCheckCast key={cid} charId={cid} />
          ))}
          {cut.takeKeys.length > 0 && (
            <>
              <h3>
                이전 테이크 — 클릭하면 A/B 비교{" "}
                {/* 다시 찍기를 반복한 컷은 그림을 여러 장 붙들고 있다(실측: 여섯 번 = 약 1.9MB).
                    테이크는 «되돌릴 수 있는 자산»이라 저장소 청소로는 안 지워진다 — 여기서 비운다 */}
                <button
                  className="btn btn-ghost btn-small"
                  title="이 컷의 이전 테이크를 저장소에서 비웁니다 — 지금 그림과 판정은 그대로입니다"
                  onClick={() => void clearTakes(sceneId)}
                >
                  🧹 옛 테이크 비우기 ({cut.takeKeys.length})
                </button>
              </h3>
              <div className="takes">
                {(allTakes ? cut.takeKeys : cut.takeKeys.slice(0, TAKES_SHOWN)).map((key, i) => (
                  <FcTake
                    key={key}
                    takeKey={key}
                    active={compare?.key === key}
                    onPick={() => setCompare({ key, index: i })}
                  />
                ))}
              </div>
              {cut.takeKeys.length > TAKES_SHOWN && (
                <button
                  className="btn btn-ghost btn-small takes-more"
                  onClick={() => setAllTakes((v) => !v)}
                  title="테이크는 최신순입니다 — 가까운 것부터 보여줍니다"
                >
                  {allTakes ? "접기 ▴" : `+ ${cut.takeKeys.length - TAKES_SHOWN}장 더 보기 ▾`}
                </button>
              )}
            </>
          )}
          <div className="fc-actions">
            <button
              className="btn btn-primary"
              disabled={shooting || batchRunning}
              onClick={() => void shootSingle(sceneId)}
            >
              이 컷만 다시
            </button>
            {cut.status === "ok" && (
              <button className="btn btn-danger" disabled={shooting} onClick={() => markNg(sceneId)}>
                NG 판정
              </button>
            )}
            {cut.status === "ng" && cut.imageKey && (
              <button className="btn" disabled={shooting} onClick={() => markOk(sceneId)}>
                OK로 되돌리기
              </button>
            )}
            {(cut.status === "ng" || cut.delayed) && (
              <button
                className="btn"
                disabled={shooting}
                title="MakeFun 기록에서 완성본을 추가 과금 없이 회수합니다"
                onClick={() => void pullResultFor(sceneId)}
              >
                결과 찾아오기
              </button>
            )}
            {cut.status === "ok" && (
              <button
                className={`btn ${isPoster ? "btn-toggled" : ""}`}
                disabled={shooting}
                title="이 컷을 작품 표지로 — 시사실 포스터의 배경이 됩니다"
                onClick={() => setPoster(sceneId)}
              >
                {isPoster ? "🖼 표지 ✓" : "🖼 표지로"}
              </button>
            )}
            {cut.status === "ok" && (
              <button
                className="btn"
                title="시사실로 건너가 이 컷부터 흐름을 봅니다 — 검수 중 문맥 확인용"
                onClick={() => {
                  onClose();
                  enterScreening();
                  showScene(sceneId);
                }}
              >
                ▶ 여기부터 시사
              </button>
            )}
            {cut.status === "ok" && cut.sourceUrl && !cut.videoKey && (
              <button
                className="btn"
                disabled={shooting}
                title="이 컷의 그림을 짧은 영상으로 바꿔 찍습니다 (실험 · 약 30크레딧)"
                onClick={() => void makeMovingCut(sceneId)}
              >
                🎞 무빙 컷 만들기 (실험)
              </button>
            )}
            {cut.status === "ok" &&
              !cut.sourceUrl &&
              !cut.videoKey &&
              (cut.source === "upload" || cut.source === "url") && (
                <p className="fine">
                  🎞 무빙 컷은 카메라로 찍은 그림에서만 만들 수 있어요. 이 컷은 올린 그림이라,
                  「이 컷만 다시」로 한 번 촬영하면 무빙화할 수 있습니다.
                </p>
              )}
            <button className="btn btn-ghost" onClick={onClose}>
              닫기 (Esc)
            </button>
          </div>
          <p className="fine">
            ← → 로 컷을 넘기며 밤사이 얼굴이 흔들리지 않았는지 확인하세요. NG 판정해도 그림은
            테이크로 남습니다.
          </p>
        </div>
      </div>
    </div>
  );
}

function FcTake({
  takeKey,
  active,
  onPick,
}: {
  takeKey: string;
  active: boolean;
  onPick: () => void;
}) {
  const blob = useStudio((s) => s.blobs[takeKey]);
  const url = useObjectUrl(blob);
  if (!url) return null;
  return (
    <button
      className={`take ${active ? "take-active" : ""}`}
      title="클릭하면 현재 그림과 A/B 비교합니다"
      onClick={onPick}
    >
      <img src={url} alt="take" />
    </button>
  );
}

function FaceCheckCast({ charId }: { charId: string }) {
  const { char: c, url } = useCharPhoto(charId);
  if (!c) return null;
  return (
    <div className="fc-cast">
      <div className="fc-cast-photo">
        {url ? <img src={url} alt={c.name} /> : <span className="cast-nophoto">얼굴 없음</span>}
      </div>
      <div>
        <div className="cast-name">{c.name}</div>
        {c.look && <div className="fine">{c.look}</div>}
      </div>
    </div>
  );
}
