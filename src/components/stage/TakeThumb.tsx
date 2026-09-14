/** 이전 테이크 썸네일 — 클릭하면 그 테이크로 복귀. CutCard와 FaceCheck가 공유. */
import { useStudio } from "../../store/useStudio";
import { useObjectUrl } from "../../lib/hooks";

export function TakeThumb({
  sceneId,
  takeKey,
  index,
}: {
  sceneId: string;
  takeKey: string;
  index: number;
}) {
  const blob = useStudio((s) => s.blobs[takeKey]);
  const revertTake = useStudio((s) => s.revertTake);
  const url = useObjectUrl(blob);
  if (!url) return null;
  return (
    <button
      className="take"
      title="클릭하면 이 테이크로 되돌립니다"
      onClick={() => revertTake(sceneId, index)}
    >
      <img src={url} alt={`take ${index + 1}`} />
    </button>
  );
}
