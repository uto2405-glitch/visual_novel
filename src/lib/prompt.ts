/**
 * 프롬프트 조립 — API 호출 직전에만 쓴다. 시사(플레이) 중에는 절대 호출하지 않는다.
 *
 * shot === "full"  → style + bg_prompt + 캐릭터 look + pose + emotion
 *                    + "visual novel still" + "keep the same face as the reference photo"
 * shot === "focus" → style + close-up of 캐릭터 + pose + emotion
 *                    + "simple blurred background" + keep the same face
 */
import { reuseTarget, type Scene, type Story } from "../types";

function joinParts(parts: Array<string | undefined>): string {
  return parts
    .map((p) => (p ?? "").trim())
    .filter(Boolean)
    .join(", ");
}

/** reuse 체인을 따라가 실제 bg_prompt를 찾는다. */
function resolveBgPrompt(story: Story, scene: Scene, depth = 0): string {
  if (scene.bg_prompt) return scene.bg_prompt;
  const target = reuseTarget(scene);
  if (target && depth < 8) {
    const src = story.scenes.find((s) => s.id === target);
    if (src) return resolveBgPrompt(story, src, depth + 1);
  }
  return "";
}

/**
 * 클로즈업·반신 컷에 «장소»를 흐린 배경으로 얹는다 — 줌인·줌아웃이 한 장면으로 읽히게 하는 문구.
 *
 * 예전에는 focus·portrait가 bg_prompt를 아예 쓰지 않았다(배경을 날리는 것이 목적이었으니까).
 * 그런데 그러면 줌 사다리(wide → full → portrait → focus)의 뒤쪽 컷에서 장소가 사라지고
 * 카메라가 배경을 새로 지어낸다 — 실촬영 A/B(2026-09-08 · 6컷 · 72크레딧)에서 그 일이 실제로 났다:
 * 같은 교실을 당겨 찍은 portrait 컷이 «밤거리 상점 유리»로 바뀌어 줌인이 장면 전환처럼 보였다.
 * 같은 컷에 이 문구를 붙인 쪽은 교실이 흐리게 남아 이어졌고, focus도 마찬가지였다
 * (대가는 프레이밍이 조금 넓어지는 것). 문구는 «프레이밍 지시 뒤»에 붙인다 — 앞에 두면 구도를 밀어낸다.
 *
 * 장소를 일부러 지우고 싶은 클로즈업은 그 컷의 bg_prompt를 비우면 된다(그러면 예전 그대로다).
 */
function placeBehind(story: Story, scene: Scene): string | undefined {
  const place = resolveBgPrompt(story, scene);
  return place ? `same place as the previous shot: ${place}, softly blurred behind the subject` : undefined;
}

export function assemblePrompt(story: Story, scene: Scene): string {
  const cast = (scene.chars ?? [])
    .map((cid) => story.characters.find((c) => c.id === cid))
    .filter((c): c is NonNullable<typeof c> => Boolean(c));
  const looks = cast.map((c) => c.look ?? c.name);
  const hasCast = cast.length > 0;

  // 카메라 고정 — 연속 동작. 앵글이 튀면 이어지는 컷으로 안 읽히므로 style 바로 뒤에 세게 붙인다.
  // 실측(2026-09-06): 앵글 고정은 이 문구로 확실히 되지만, 소품(우산 등)이 컷마다 사라졌다.
  // 그래서 의상·소품 유지도 함께 못박는다.
  // 또 하나(정사각 3컷 실측): 인물이 «이동»하는 pose(문을 열고 들어간다 등)에서는 카메라가
  // 따라가 앵글이 흔들린다. 그래서 «서 있는 자리는 그대로»라는 조건도 함께 적는다.
  const hold = scene.hold
    ? "identical camera angle, camera position and framing as the previous shot, same clothing and same props kept exactly, the subject stays in the same spot in the frame, only the subject's pose changes"
    : undefined;

  // 액션 — 정적 레퍼런스를 이기려면 동세 어휘를 촘촘히 쌓아야 한다(실측: 약한 지시는 ref 구도에 밀린다).
  // 얼굴이 흔들리면 이 컷을 back(뒷모습)으로 바꾸는 것이 더 확실하다.
  if (scene.shot === "action") {
    return joinParts([
      story.style,
      hold,
      "dynamic action shot caught mid-motion, motion blur on the moving limbs, windblown hair and clothes, low dramatic angle, strong sense of speed",
      resolveBgPrompt(story, scene),
      ...looks,
      scene.pose,
      scene.emotion,
      "visual novel still",
      hasCast ? "keep the same face as the reference photo" : undefined,
    ]);
  }
  // 인물묘사 — 얼굴만이 아니라 자세·옷·손까지 보여주는 반신. 배경은 얕은 심도로 물러난다.
  if (scene.shot === "portrait") {
    return joinParts([
      story.style,
      hold,
      hasCast ? `waist-up portrait of ${looks.join(" and ")}` : "waist-up portrait",
      scene.pose,
      scene.emotion,
      "shallow depth of field, background softly blurred, careful detail on the face, hands and clothing texture",
      hasCast ? "keep the same face as the reference photo" : undefined,
      placeBehind(story, scene),
    ]);
  }
  if (scene.shot === "focus") {
    return joinParts([
      story.style,
      hold,
      hasCast ? `close-up of ${looks.join(" and ")}` : "close-up shot",
      scene.pose,
      scene.emotion,
      "simple blurred background",
      hasCast ? "keep the same face as the reference photo" : undefined,
      placeBehind(story, scene),
    ]);
  }
  // 뒷모습 — 얼굴이 보이지 않으니 얼굴 일관성 부담이 없다. 시퀀스의 시작·끝에 좋다.
  if (scene.shot === "back") {
    return joinParts([
      story.style,
      hold,
      "seen from behind, back view, we do not see the face",
      resolveBgPrompt(story, scene),
      ...looks,
      scene.pose,
      "visual novel still",
    ]);
  }
  // 와이드 — 약한 지시는 레퍼런스 구도에 밀린다(실측). 그래서 세게 쓴다.
  if (scene.shot === "wide") {
    return joinParts([
      story.style,
      hold,
      "extreme wide establishing shot, the figure is small and far away in the frame, vast space around",
      resolveBgPrompt(story, scene),
      ...looks,
      scene.emotion,
      "visual novel still",
      hasCast ? "keep the same face as the reference photo" : undefined,
    ]);
  }
  return joinParts([
    story.style,
    hold,
    resolveBgPrompt(story, scene),
    ...looks,
    scene.pose,
    scene.emotion,
    "visual novel still",
    hasCast ? "keep the same face as the reference photo" : undefined,
  ]);
}
