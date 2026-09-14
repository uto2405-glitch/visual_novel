/** 촬영장 컷 카드 — 미리보기(클릭=페이스 체크), 프롬프트, 개별 촬영/등록, 테이크.
 *  협소 구독 + memo: 다른 컷의 프롬프트를 쳐도 이 카드는 리렌더되지 않는다. */
import { memo, useMemo, useState } from "react";
import { useStudio } from "../../store/useStudio";
import { takeFiles } from "../../lib/blob";
import { assemblePrompt } from "../../lib/prompt";
import { speakerName } from "../../lib/story";
import { emptyCut, reuseTarget, type Scene, type Story } from "../../types";
import { useCutImageUrl } from "../hooks";
import { StatusBadge } from "../StatusBadge";
import { TakeThumb } from "./TakeThumb";

const FALLBACK_STORY: Story = { title: "", style: "", characters: [], scenes: [] };

export const CutCard = memo(function CutCard({
  scene,
  index,
  onFaceCheck,
}: {
  scene: Scene;
  index: number;
  onFaceCheck: (id: string) => void;
}) {
  // 촬영장에서는 story/charAssets가 거의 안 바뀐다 — 협소 구독으로 카드 간 격리
  const story = useStudio((s) => s.project?.story ?? FALLBACK_STORY);
  const shooting = useStudio((s) => Boolean(s.shooting[scene.id]));
  const batchRunning = useStudio((s) => Boolean(s.batch?.running));
  const cutRec = useStudio((s) => s.project?.cuts[scene.id]);
  const cut = cutRec ?? emptyCut();
  const url = useCutImageUrl(scene.id);
  const setCustomPrompt = useStudio((s) => s.setCustomPrompt);
  const resetPrompt = useStudio((s) => s.resetPrompt);
  const shootSingle = useStudio((s) => s.shootSingle);
  const uploadSceneImage = useStudio((s) => s.uploadSceneImage);
  const registerUrlImage = useStudio((s) => s.registerUrlImage);
  const removeImage = useStudio((s) => s.removeImage);
  const toggleCutscene = useStudio((s) => s.toggleCutscene);
  const pullResultFor = useStudio((s) => s.pullResultFor);
  const toast = useStudio((s) => s.toast);
  const [dragOver, setDragOver] = useState(false);

  const reuse = reuseTarget(scene);
  const assembled = useMemo(() => assemblePrompt(story, scene), [story, scene]);
  const promptValue = cut.customPrompt !== undefined ? cut.customPrompt : assembled;

  const cast = (scene.chars ?? [])
    .map((cid) => story.characters.find((c) => c.id === cid))
    .filter(Boolean);
  /* 얼굴이 «실제로 카메라에 실리는가» — ref와 열쇠만 보면 사진이 저장소에서 사라진 배우도 「얼굴」로
     보였다(그러면 카메라에는 아무것도 안 간다). 블롭까지 있어야 얼굴이다. 불리언 셀렉터라 값이 바뀔 때만 다시 그린다. */
  const hasFace = useStudio((s) => {
    const p = s.project;
    const ids = scene.chars ?? [];
    if (!p || ids.length === 0) return false;
    return ids.every((cid) => {
      const c = p.story.characters.find((x) => x.id === cid);
      const key = c?.ref ? p.charAssets[c.ref] : undefined;
      return Boolean(key && s.blobs[key]);
    });
  });

  const speaker = speakerName(story, scene) || "내레이션";

  const onDropFiles = (files: File[]) => {
    if (files.length === 0) return;
    const img = files.find(
      (f) => f.type.startsWith("image/") || /\.(png|jpe?g|webp)$/i.test(f.name),
    );
    if (!img) {
      toast("이미지 파일이 아닙니다.", "ng");
      return;
    }
    void uploadSceneImage(scene.id, img);
  };

  return (
    <div
      className={`cutcard status-${shooting ? "shoot" : cut.status}`}
      id={`stagecut-${scene.id}`}
    >
      <div
        className={`cutcard-preview ${dragOver ? "dragover" : ""}`}
        onClick={() => onFaceCheck(scene.id)}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onDropFiles(Array.from(e.dataTransfer.files)); // FileList 즉시 복사
        }}
        title="클릭하면 페이스 체크 모니터가 열립니다. 이미지를 끌어다 놓으면 이 컷에 등록됩니다"
      >
        {url ? (
          <img src={url} alt={scene.id} />
        ) : (
          <div className="cutcard-empty">
            <span>
              {scene.placeholder
                ? "플레이스홀더 컷"
                : reuse
                  ? `배경 reuse:${reuse}`
                  : "아직 필름이 없습니다"}
            </span>
            <small>드래그해서 내 이미지를 걸 수도 있어요</small>
          </div>
        )}
        <div className="cutcard-badges">
          <StatusBadge status={cut.status} shooting={shooting} delayed={cut.delayed} />
          {cast.length > 0 &&
            (hasFace ? (
              <span className="badge badge-face">얼굴</span>
            ) : (
              <span className="badge badge-noface">얼굴 없음</span>
            ))}
        </div>
      </div>

      <div className="cutcard-body">
        <div className="card-head">
          <span className="chip chip-strong">#{index + 1}</span>
          <span className="chip">{scene.id}</span>
          {/* 실제 shot을 그대로 적는다 — 예전에는 «focus 아니면 full»로만 찍어서 wide·portrait·back·action
              컷이 전부 「full」로 보였다(감독이 줌 사다리를 짜 놓고도 카드에서는 알 수 없었다). */}
          <span className="chip">{scene.shot ?? "full"}</span>
          {/* 직접 쓴 프롬프트 — 이 컷은 조립을 건너뛰므로 화풍·배우·장소 변경이 닿지 않는다.
              카드에 그 사실을 적어 둔다(예전에는 상자 위의 되돌리기 링크가 유일한 단서였다). */}
          {(cut.customPrompt ?? "").trim() && (
            <span
              className="chip chip-strong"
              title="이 컷은 프롬프트를 직접 고쳐 두었습니다 — 화풍·배우 외모·장소·카메라 고정 변경이 닿지 않습니다"
            >
              ✎ 직접 쓴 프롬프트
            </span>
          )}
          {cut.source === "upload" && <span className="chip">내 파일</span>}
          {cut.source === "url" && <span className="chip">URL</span>}
          {cut.source === "reuse" && <span className="chip">reuse</span>}
          {cut.videoKey && <span className="chip chip-strong">🎞 무빙</span>}
        </div>
        <p className="cutcard-line">
          <b>{speaker}</b> {scene.text || <em className="fine">(대사 없음)</em>}
        </p>

        <label className="field">
          <span>
            프롬프트{" "}
            {cut.customPrompt !== undefined && (
              <button className="linkbtn" onClick={() => resetPrompt(scene.id)}>
                기본 프롬프트로
              </button>
            )}
          </span>
          <textarea
            rows={3}
            value={promptValue}
            placeholder="비워두면 기본 프롬프트(조립본)로 촬영합니다"
            onChange={(e) => setCustomPrompt(scene.id, e.target.value)}
            spellCheck={false}
          />
        </label>

        {cut.note && <p className="ngnote">{cut.note}</p>}

        <div className="cutcard-actions">
          <button
            className="btn btn-small btn-primary"
            disabled={shooting || batchRunning}
            title={batchRunning ? "배치 촬영 중에는 개별 촬영을 잠급니다 (이중 크레딧 방지)" : undefined}
            onClick={() => void shootSingle(scene.id)}
          >
            {cut.imageKey || cut.status === "ng" ? "이 컷만 다시" : "이 컷만 촬영"}
          </button>
          <FilePickButton sceneId={scene.id} disabled={shooting} />
          {(cut.status === "ng" || cut.delayed) && (
            <button
              className="btn btn-small"
              disabled={shooting}
              title="MakeFun에는 결과가 나왔는데 앱이 못 받았을 때 — 기록에서 완성본을 추가 과금 없이 가져옵니다"
              onClick={() => void pullResultFor(scene.id)}
            >
              결과 찾아오기
            </button>
          )}
          <button
            className="btn btn-small"
            disabled={shooting}
            onClick={() => void registerUrlImage(scene.id)}
          >
            MakeFun URL 붙이기
          </button>
          <button
            className={`btn btn-small ${cut.cutscene ? "btn-toggled" : ""}`}
            disabled={shooting}
            title="이 컷을 영상 컷씬으로 지정합니다 — 촬영 큐의 「컷씬 영상화」가 지정된 컷들을 MakeFun 영상으로 변환합니다"
            onClick={() => toggleCutscene(scene.id)}
          >
            🎬 컷씬{cut.cutscene ? " ✓" : ""}
          </button>
          <VideoPickButton sceneId={scene.id} disabled={shooting} hasVideo={Boolean(cut.videoKey)} />
          {cut.imageKey && (
            <button
              className="btn btn-small btn-ghost"
              disabled={shooting}
              onClick={() => removeImage(scene.id)}
            >
              이미지 빼기
            </button>
          )}
        </div>

        {cut.takeKeys.length > 0 && (
          <div className="takes">
            <span className="fine">이전 테이크</span>
            {cut.takeKeys.map((key, i) => (
              <TakeThumb key={key} sceneId={scene.id} takeKey={key} index={i} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
});

function VideoPickButton({
  sceneId,
  disabled,
  hasVideo,
}: {
  sceneId: string;
  disabled: boolean;
  hasVideo: boolean;
}) {
  const attachVideo = useStudio((s) => s.attachVideo);
  const removeVideo = useStudio((s) => s.removeVideo);
  const [inputEl, setInputEl] = useState<HTMLInputElement | null>(null);
  return (
    <>
      <button
        className="btn btn-small"
        disabled={disabled}
        title="mp4/webm 영상을 이 컷에 겁니다 — 시사실에서 이미지 대신 재생됩니다"
        onClick={() => inputEl?.click()}
      >
        🎞 영상 걸기
      </button>
      {hasVideo && (
        <button
          className="btn btn-small btn-ghost"
          disabled={disabled}
          onClick={() => removeVideo(sceneId)}
        >
          영상 빼기
        </button>
      )}
      <input
        ref={setInputEl}
        type="file"
        accept="video/mp4,video/webm,video/*"
        style={{ display: "none" }}
        onChange={(e) => {
          const files = takeFiles(e.currentTarget); // FileList 즉시 복사 → 그 다음 리셋
          if (files[0]) void attachVideo(sceneId, files[0]);
        }}
      />
    </>
  );
}

function FilePickButton({ sceneId, disabled }: { sceneId: string; disabled: boolean }) {
  const uploadSceneImage = useStudio((s) => s.uploadSceneImage);
  const [inputEl, setInputEl] = useState<HTMLInputElement | null>(null);
  return (
    <>
      <button className="btn btn-small" disabled={disabled} onClick={() => inputEl?.click()}>
        내 파일에서 등록
      </button>
      <input
        ref={setInputEl}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={(e) => {
          const files = takeFiles(e.currentTarget); // FileList 즉시 복사 → 그 다음 리셋
          if (files[0]) void uploadSceneImage(sceneId, files[0]);
        }}
      />
    </>
  );
}
