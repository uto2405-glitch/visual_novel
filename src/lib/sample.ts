/**
 * 샘플 프로젝트 「비 오는 역의 약속」.
 * 일반 프로젝트와 똑같이 저장 시스템(IndexedDB)을 탄다.
 * 기본 얼굴 사진은 bundling하지 않는다 — 배우 사진이 없으면 「얼굴 없음」.
 */
import type { Story } from "../types";

export const SAMPLE_STORY: Story = {
  title: "비 오는 역의 약속",
  style:
    "cinematic realistic photo, soft indoor lighting, visual novel still, consistent face matching reference, 16:9",
  characters: [
    { id: "hana", name: "하나", ref: "hana.jpg", look: "20대 한국 여성, 단발, 베이지 코트" },
  ],
  scenes: [
    {
      id: "s01",
      sfx: "rain",
      bgm: true,
      bg_prompt: "rainy night train station platform, neon signs, puddles reflecting light, cinematic",
      shot: "full",
      chars: ["hana"],
      pose: "standing under a transparent umbrella, side profile",
      emotion: "lonely",
      text: "마지막 열차는 이미 지나간 뒤였다.",
      speaker: "narration",
      next: "s02",
    },
    {
      id: "s02",
      sfx: "rain",
      bg: "reuse:s01",
      shot: "focus",
      chars: ["hana"],
      pose: "close-up, wet hair, faint bitter smile",
      emotion: "bitter smile",
      text: "그래도… 기다릴게.",
      speaker: "hana",
      choices: [
        { label: "우산을 건넨다", next: "s03a" },
        { label: "아무 말 없이 옆에 선다", next: "s03b" },
      ],
    },
    {
      id: "s03a",
      sfx: "rain",
      bg_prompt:
        "rainy night train station platform, one person handing over an umbrella, warm lamp light, cinematic",
      shot: "full",
      chars: ["hana"],
      pose: "receiving an umbrella, hesitating, then smiling softly",
      emotion: "surprised warmth",
      text: "우산을 건네자, 하나는 잠시 망설이다 웃었다.",
      speaker: "narration",
      next: "s04",
    },
    {
      id: "s03b",
      sfx: "rain",
      bg_prompt:
        "rainy night train station platform, two silhouettes standing side by side under the awning, cinematic",
      shot: "full",
      chars: ["hana"],
      pose: "standing side by side, looking at the rain",
      emotion: "quiet comfort",
      text: "아무 말도 하지 않았다. 빗소리가 대신 말했다.",
      speaker: "narration",
      next: "s04",
    },
    {
      id: "s04",
      sfx: "rain",
      bg: "reuse:s01",
      shot: "focus",
      chars: ["hana"],
      pose: "close-up, looking slightly up, small genuine smile",
      emotion: "grateful",
      text: "…고마워. 이런 밤에.",
      speaker: "hana",
      next: "s05",
    },
    {
      id: "s05",
      sfx: "night",
      bg_prompt:
        "small late-night convenience store near the station, warm fluorescent glow in the rain, cinematic",
      shot: "full",
      chars: ["hana"],
      pose: "holding two warm canned coffees, standing by the window",
      emotion: "soft",
      text: "따뜻한 캔커피 두 개를 샀다. 하나가 하나를 골랐다.",
      speaker: "narration",
      next: "s06",
    },
    {
      id: "s06",
      sfx: "night",
      bg: "reuse:s05",
      shot: "focus",
      chars: ["hana"],
      pose: "close-up, holding the warm can with both hands, eyes closed",
      emotion: "content",
      text: "다음 열차가 올 때까지, 우리는 나란히 앉아 있었다.",
      speaker: "narration",
      next: "s07",
    },
    {
      id: "s07",
      sfx: "wind",
      bgm: false,
      bg_prompt:
        "train station platform at dawn, rain has stopped, pale blue sky, first train arriving, cinematic",
      shot: "full",
      chars: ["hana"],
      pose: "standing on the platform, coat draped, looking at the horizon",
      emotion: "hopeful",
      text: "첫차가 들어올 무렵, 비가 그쳤다.",
      speaker: "narration",
      next: "s08",
    },
    {
      id: "s08",
      sfx: "wind",
      bg: "reuse:s07",
      shot: "focus",
      chars: ["hana"],
      pose: "close-up, bright wide smile, waving hand",
      emotion: "bright promise",
      text: "또 만나러 올게. 약속.",
      speaker: "hana",
    },
  ],
};
