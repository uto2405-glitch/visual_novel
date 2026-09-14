/** 카메라 — 필름(모델)·크기 선택과 크레딧 슬레이트. */
import { useStudio } from "../../store/useStudio";
import { CAMERA_MODELS, SIZES, creditLine, creditsOf, modelById } from "../../lib/makefun";
import { isApiCut, type SizeKey } from "../../types";
import { useProject } from "../hooks";

export function CameraPanel() {
  const project = useProject();
  const setCamera = useStudio((s) => s.setCamera);
  const token = useStudio((s) => s.token);
  const setSettingsOpen = useStudio((s) => s.setSettingsOpen);

  const model = modelById(project.camera.model);
  const size: SizeKey = model.sizes.includes(project.camera.size)
    ? project.camera.size
    : model.sizes[0];

  const pendingApi = project.story.scenes.filter((sc) => {
    const cut = project.cuts[sc.id];
    return (cut?.status ?? "wait") === "wait" && isApiCut(sc, cut);
  }).length;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>카메라</h2>
        {!token && (
          <button className="btn btn-small" onClick={() => setSettingsOpen(true)}>
            토큰 넣기
          </button>
        )}
      </div>
      <div className="fieldrow">
        <label className="field grow">
          <span>필름 (모델)</span>
          <select value={model.id} onChange={(e) => setCamera(e.target.value, size)}>
            <optgroup label="장면 촬영">
              {CAMERA_MODELS.filter((m) => m.group === "image").map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} — {m.hint}
                </option>
              ))}
            </optgroup>
            <optgroup label="편집 (비권장)">
              {CAMERA_MODELS.filter((m) => m.group === "edit").map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} — {m.hint}
                </option>
              ))}
            </optgroup>
          </select>
        </label>
        <label className="field">
          <span>크기</span>
          <select value={size} onChange={(e) => setCamera(model.id, e.target.value as SizeKey)}>
            {model.sizes.map((k) => (
              <option key={k} value={k}>
                {SIZES[k].label} = {SIZES[k].w}×{SIZES[k].h}
                {creditsOf(model, k) != null ? ` · ${creditsOf(model, k)}크레딧` : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="creditline">{creditLine(model, size, pendingApi)}</p>
      <p className="fine">
        기본은 Seedream 5 Pro — 검열에 가장 강합니다. 얼굴이 깨진 컷만 Wan 2.7 / Wan 2.7 Pro /
        Flux 2 / Nano Banana Pro로 그 컷만 다시 찍으세요. 크레딧은 MakeFun 크레딧이며 LLM 토큰이
        아닙니다.
      </p>
    </section>
  );
}
