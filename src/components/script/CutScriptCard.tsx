/** 대본실 컷 카드 — 대사/화자/샷/장소/소리/등장 배우.
 *  협소 구독 + memo: 다른 컷을 편집해도 이 카드는 리렌더되지 않는다. */
import { memo } from "react";
import { useStudio } from "../../store/useStudio";
import { SFX_KINDS, isSfxKind } from "../../lib/ambience";
import { reuseTarget, type Scene, type StoryCharacter } from "../../types";

const EMPTY_CHARS: StoryCharacter[] = [];

export const CutScriptCard = memo(function CutScriptCard({
  scene,
  index,
  total,
  sceneIds,
}: {
  scene: Scene;
  index: number;
  total: number;
  /** 연결 셀렉트용 — 부모가 useMemo로 identity를 고정해 넘긴다 */
  sceneIds: string[];
}) {
  const characters = useStudio((s) => s.project?.story.characters ?? EMPTY_CHARS);
  const cut = useStudio((s) => s.project?.cuts[scene.id]);
  const updateScene = useStudio((s) => s.updateScene);
  const addSceneAfter = useStudio((s) => s.addSceneAfter);
  const moveScene = useStudio((s) => s.moveScene);
  const deleteScene = useStudio((s) => s.deleteScene);
  const spawnSceneAfter = useStudio((s) => s.spawnSceneAfter);
  const expandSequence = useStudio((s) => s.expandSequence);
  const reuse = reuseTarget(scene);
  /** 이 컷에서 새 장이 열리는가 — 장의 기준은 앱 전체에서 이것 하나다 */
  const isChapterStart = scene.webtoon?.pageBreak === true;

  const NEW = "__new__";
  const handleNext = (v: string) => {
    if (v === NEW) {
      const id = spawnSceneAfter(scene.id);
      if (id) updateScene(scene.id, { next: id });
      return;
    }
    updateScene(scene.id, { next: v || undefined });
  };
  const handleChoiceNext = (i: number, v: string) => {
    if (v === NEW) {
      const id = spawnSceneAfter(scene.id);
      if (id) patchChoice(i, { next: id });
      return;
    }
    patchChoice(i, { next: v });
  };

  const toggleChar = (cid: string) => {
    const cur = scene.chars ?? [];
    const next = cur.includes(cid) ? cur.filter((x) => x !== cid) : [...cur, cid];
    updateScene(scene.id, { chars: next.length > 0 ? next : undefined });
  };

  const setChoices = (choices: { label: string; next: string }[] | undefined) => {
    updateScene(scene.id, { choices: choices && choices.length > 0 ? choices : undefined });
  };
  const addChoice = () => {
    const firstOther = sceneIds.find((id) => id !== scene.id) ?? scene.id;
    setChoices([...(scene.choices ?? []), { label: "", next: firstOther }]);
  };
  const patchChoice = (i: number, patch: Partial<{ label: string; next: string }>) => {
    setChoices((scene.choices ?? []).map((c, j) => (j === i ? { ...c, ...patch } : c)));
  };
  const removeChoice = (i: number) => {
    setChoices((scene.choices ?? []).filter((_, j) => j !== i));
  };

  return (
    <div className="card" id={`cut-${scene.id}`}>
      <div className="card-head">
        <span className="chip chip-strong">#{index + 1}</span>
        <span className="chip">{scene.id}</span>
        {scene.placeholder && <span className="chip">플레이스홀더</span>}
        {reuse && <span className="chip">배경 reuse:{reuse}</span>}
        {cut?.status === "ok" && <span className="badge badge-ok">OK</span>}
        {cut?.status === "ng" && <span className="badge badge-ng">NG</span>}
      </div>
      <label className="field">
        <span>대사</span>
        <textarea
          rows={2}
          value={scene.text ?? ""}
          placeholder="이 컷에서 흐르는 문장"
          onChange={(e) => updateScene(scene.id, { text: e.target.value })}
        />
      </label>
      <div className="fieldrow">
        <label className="field">
          <span>화자</span>
          <select
            value={scene.speaker ?? "narration"}
            onChange={(e) => updateScene(scene.id, { speaker: e.target.value })}
          >
            <option value="narration">내레이션</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>샷</span>
          <select
            value={scene.shot ?? "full"}
            onChange={(e) => updateScene(scene.id, { shot: e.target.value as Scene["shot"] })}
          >
            <option value="full">full — 전체 장면</option>
            <option value="focus">focus — 얼굴 클로즈업</option>
            <option value="back">back — 뒷모습 (얼굴 안 보임)</option>
            <option value="wide">wide — 멀리서 넓게</option>
            <option value="action">action — 액션(동세·모션블러)</option>
            <option value="portrait">portrait — 인물묘사(반신)</option>
          </select>
        </label>
        <label className="field grow">
          <span>장소 (bg_prompt)</span>
          <input
            value={scene.bg_prompt ?? ""}
            placeholder={reuse ? `비우면 reuse:${reuse}의 배경을 씁니다` : "rainy night station…"}
            onChange={(e) => updateScene(scene.id, { bg_prompt: e.target.value })}
          />
        </label>
        <label className="field">
          <span>소리</span>
          <select
            value={isSfxKind(scene.sfx) ? scene.sfx : ""}
            onChange={(e) => updateScene(scene.id, { sfx: e.target.value || undefined })}
          >
            <option value="">없음</option>
            {SFX_KINDS.map((k) => (
              <option key={k.id} value={k.id}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <div className="field">
          <span>카메라</span>
          <button
            type="button"
            className={`chip chipbtn ${scene.hold ? "chip-on" : ""}`}
            title="직전 컷과 같은 앵글·프레이밍·의상·소품을 유지하고 자세만 바꿉니다 — 연속 동작을 만들 때. 배경 문구를 똑같이 적고, 들고 있는 물건은 자세에도 다시 적으세요. 「문을 열고 들어간다」처럼 인물이 이동하면 카메라가 따라가 앵글이 흔들립니다(실측) — 이동은 컷을 나누세요"
            onClick={() => updateScene(scene.id, { hold: scene.hold ? undefined : true })}
          >
            {scene.hold ? "🔒 고정" : "— 자유"}
          </button>
        </div>
        <div className="field">
          <span>음악</span>
          <button
            type="button"
            className={`chip chipbtn bgm-chip ${scene.bgm === true ? "chip-on" : ""}`}
            title="이 컷에 닿았을 때: 시작=🎵 켜기, 정지=끄기, 그대로=변화 없음"
            onClick={() =>
              updateScene(scene.id, {
                bgm: scene.bgm === undefined ? true : scene.bgm === true ? false : undefined,
              })
            }
          >
            {scene.bgm === true ? "🎵 시작" : scene.bgm === false ? "🛑 정지" : "— 그대로"}
          </button>
        </div>
      </div>
      <div className="field">
        <span>연결 — 이 컷 다음에 무엇이 오나</span>
        {!scene.choices || scene.choices.length === 0 ? (
          <div className="linkrow">
            <select value={scene.next ?? ""} onChange={(e) => handleNext(e.target.value)}>
              <option value="">(끝 — 엔딩 크레딧)</option>
              {sceneIds
                .filter((id) => id !== scene.id)
                .map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              <option value="__new__">＋ 새 컷 만들기…</option>
            </select>
            <button className="btn btn-ghost btn-small" onClick={addChoice}>
              + 선택지로 전환
            </button>
          </div>
        ) : (
          <div className="choices-edit">
            {scene.choices.map((c, i) => (
              <div className="choice-row" key={i}>
                <input
                  value={c.label}
                  placeholder={`선택지 ${i + 1} 문구`}
                  onChange={(e) => patchChoice(i, { label: e.target.value })}
                />
                <span className="fine">→</span>
                <select value={c.next} onChange={(e) => handleChoiceNext(i, e.target.value)}>
                  {sceneIds.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                  <option value="__new__">＋ 새 컷 만들기…</option>
                </select>
                <button
                  className="btn btn-ghost btn-small"
                  title="이 선택지 빼기"
                  onClick={() => removeChoice(i)}
                >
                  ✕
                </button>
              </div>
            ))}
            <div className="linkrow">
              <button className="btn btn-ghost btn-small" onClick={addChoice}>
                + 선택지
              </button>
              <span className="fine">선택지를 모두 빼면 다시 next 연결로 돌아갑니다</span>
            </div>
          </div>
        )}
      </div>
      {characters.length > 0 && (
        <div className="field">
          <span>
            등장 배우 — 켠 배우의 캐스팅 사진이 이 컷의 얼굴 레퍼런스로 전달됩니다
          </span>
          <div className="charchips">
            {characters.map((c) => {
              const on = scene.chars?.includes(c.id) ?? false;
              return (
                <button
                  key={c.id}
                  type="button"
                  className={`chip chipbtn ${on ? "chip-on" : ""}`}
                  onClick={() => toggleChar(c.id)}
                >
                  {c.name}
                  {on ? " ✓" : ""}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <div className="card-foot">
        <button className="btn btn-ghost btn-small" onClick={() => addSceneAfter(scene.id)}>
          뒤에 한 컷 붙이기
        </button>
        <button
          className="btn btn-ghost btn-small"
          title="이 컷을 A로 두고 B·C를 만들어 잇습니다 — 같은 배경 문구와 카메라 고정(🔒)이 켜진 채로 나오니 자세(pose)만 채우면 움직임이 됩니다"
          onClick={() => expandSequence(scene.id)}
        >
          🎞 연속 동작 3컷
        </button>
        {/* 장 나누기는 조판실에만 있었다. 그런데 장은 인쇄본만의 것이 아니라
            촬영·시사·콜시트가 함께 쓰는 단위다 — 이야기를 쓰는 자리에서도 나눌 수 있어야 한다 */}
        <button
          className={`btn btn-ghost btn-small ${isChapterStart ? "btn-toggled" : ""}`}
          disabled={index === 0}
          aria-pressed={isChapterStart}
          title={
            index === 0
              ? "첫 컷은 표시가 없어도 1장입니다"
              : isChapterStart
                ? "이 컷에서 새 장이 열립니다 — 다시 누르면 앞 장에 붙습니다"
                : "이 컷부터 새 장으로 나눕니다 — 인쇄본은 여기서 페이지가 넘어가고, 촬영장·시사실·콜시트도 같은 기준으로 셉니다"
          }
          onClick={() =>
            updateScene(scene.id, {
              webtoon: { ...(scene.webtoon ?? {}), pageBreak: isChapterStart ? undefined : true },
            })
          }
        >
          {isChapterStart ? "⏎ 새 장 ✓" : "⏎ 새 장"}
        </button>
        <button
          className="btn btn-ghost btn-small"
          disabled={index === 0}
          title="표시 순서를 위로 — 연결(next)은 그대로입니다"
          onClick={() => moveScene(scene.id, -1)}
        >
          ↑
        </button>
        <button
          className="btn btn-ghost btn-small"
          disabled={index >= total - 1}
          title="표시 순서를 아래로 — 연결(next)은 그대로입니다"
          onClick={() => moveScene(scene.id, 1)}
        >
          ↓
        </button>
        <button
          className="btn btn-ghost btn-small btn-danger-ghost"
          title="이 컷을 대본에서 뺍니다 (확인창)"
          onClick={() => void deleteScene(scene.id)}
        >
          지우기
        </button>
      </div>
    </div>
  );
});
