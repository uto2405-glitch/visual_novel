/**
 * AI 프롬프트 조립 — 대본실의 「✨ AI 이어쓰기」와 장별 「✎ 다시 쓰기」가 같은 규칙을 쓴다.
 * 규칙 문장이 두 군데로 갈라지면 한쪽만 낡는다.
 */
import type { Scene, Story } from "../types";

/** 형식을 틀리지 않게 주는 미니 예시 — 핵심 필드가 모두 나온다 */
export const FORMAT_EXAMPLE = `{"title":"막차 지난 역","style":"cinematic realistic photo, soft lighting, visual novel still, consistent face matching reference, 16:9","characters":[{"id":"jun","name":"준","ref":"jun.jpg","look":"20s korean man, short black hair, navy coat"}],"scenes":[{"id":"s01","shot":"full","bg_prompt":"rainy night train station, neon signs","chars":["jun"],"emotion":"lonely","text":"막차는 이미 떠난 뒤였다.","speaker":"jun","sfx":"rain","bgm":true,"next":"s02"},{"id":"s02","shot":"focus","chars":["jun"],"emotion":"hesitant","text":"「…조금만 더 기다려 볼까.」","speaker":"jun","choices":[{"label":"돌아선다","next":"s03a"},{"label":"벤치에 앉는다","next":"s03b"}]},{"id":"s03a","shot":"full","bg":"reuse:s01","text":"발길을 돌렸다.","speaker":"narration"}]}`;

/** 컷 작성 규칙 — 실측으로 얻은 것들(연속 동작·reuse·shot 종류)이 여기 모여 있다 */
export const RULES = `- id는 유일하게(s01, s02 …). 분기 갈래는 s03a/s03b 식
- shot은 "full"(전체) / "focus"(얼굴 클로즈업) / "back"(뒷모습·얼굴 안 보임) / "wide"(멀리서 넓게) / "action"(동세·모션블러) / "portrait"(반신 인물묘사) — 시점을 바꿔 리듬을 만들어라
- 같은 자리에서 이어지는 동작(연속 동작)은 hold:true 로 묶고, bg_prompt를 「똑같은 문장으로 다시」 적고 pose만 바꿔라. 들고 있는 물건(우산 등)은 컷마다 pose에 다시 적어라 — 안 적으면 사라진다
- 연속 동작의 pose는 «몸»만 바꿔라. 「문을 열고 들어간다」처럼 인물이 이동하면 카메라가 따라가서 앵글이 흔들린다(실측) — 이동은 컷을 나눠라
- bg:"reuse:…"는 «완전히 같은 그림»을 다시 쓸 때만 (그림을 복사하므로 자세가 바뀌지 않는다). 자세가 바뀌는 컷에는 절대 쓰지 마라
- 액션 컷에서 얼굴이 중요하지 않으면 shot:"back"이 더 안정적이다 (얼굴 일관성 부담이 없다)
- full 컷엔 bg_prompt(영어, cinematic). 그림까지 완전히 같아도 되는 컷만 bg:"reuse:그 컷 id"
- 인물이 보이는 컷은 chars:["캐릭터 id"], pose·emotion(영어)도 함께
- text는 한국어 대사, speaker는 "narration" 또는 캐릭터 id
- 이어짐은 next:"다음 컷 id". 갈림길은 choices:[{label,next}] (next와 같이 쓰지 마라)
- 선택: sfx는 "rain"|"wind"|"night", bgm은 true(음악 시작)/false(정지) — 꼭 필요한 곳에만
- 마지막 컷은 next 없이 끝(엔딩)
- 인쇄본(웹툰)까지 바로 뽑고 싶으면 컷마다 webtoon:{caption:"컷 제목", line:"말풍선용 짧은 대사", kind:"say|think|shout", tail:"l|c|r|none"(꼬리가 인물 쪽), pageBreak:true(이 컷부터 새 장)} 를 덧붙여라 (선택)`;

/** 빈 대본에서 처음부터 만들기 */
export function buildBlankPrompt(): string {
  return `너는 비주얼노벨 시나리오 작가다. 아래 소재로 story.json 한 벌을 처음부터 만들어라.

[소재를 여기에 한두 줄로 적어라. 예: 비 오는 밤, 편의점에서 오래 못 본 친구를 우연히 만나는 이야기]

출력 규칙 (반드시 지켜라):
- 출력은 JSON 객체 하나만. 코드펜스(백틱)·설명·인사말 전부 금지.
- 최상위: { "title": 한국어 제목, "style": 화풍(영어, cinematic), "characters": [...], "scenes": [...] }
- characters[]: { "id": 영문소문자, "name": 한국어 이름, "ref": "id.jpg", "look": 외모(영어) } — 인쇄본 인물 소개에서 사진을 자를 위치는 앱에서 고르니 castCrop은 넣지 마라
${RULES}
- 배우 2~3명, 8~12컷, 선택지 갈래 최소 1개.

형식이 헷갈리면 아래 예시와 똑같은 구조로 만들어라 (내용은 새로):
${FORMAT_EXAMPLE}`;
}

/**
 * 이어쓰기 — 연재가 길어지면 대본 전체를 붙일 수 없다.
 * 실측: 10장 120컷 = 30KB(약 1.2만 토큰), 20장 240컷 = 60KB(약 2.5만 토큰).
 * 뒤 18컷만 싣고 앞은 몇 컷이 있었는지만 알린다.
 */
export function buildContinuePrompt(story: Story, tail = 18): string {
  const all = story.scenes;
  const cut = all.length > tail;
  const tailStory = cut ? { ...story, scenes: all.slice(-tail) } : story;
  const tailNote = cut
    ? ` (전체 ${all.length}컷 중 마지막 ${tail}컷만 실었다 — 앞 이야기는 이미 끝났다고 보고 이어서만 써라)`
    : "";
  return `너는 비주얼노벨 시나리오 작가다. 아래 대본(JSON)의 이야기를 자연스럽게 이어서 새 장면들만 만들어라.

출력 규칙 (반드시 지켜라):
- 출력은 JSON 하나만: {"scenes":[ … ]} (코드펜스·설명 금지)
- 새 장면 id는 기존과 겹치지 않게 (예: s09, s10 …)
${RULES}
- 새 인물은 만들지 말고 기존 캐릭터 id만 써라
- 5~8컷, 선택지 갈래 1개 이상
- 새 «장»을 시작하려면 그 첫 컷에 webtoon:{pageBreak:true, caption:"N장"}을 넣어라 (인쇄본이 장마다 나뉜다)

현재 대본${tailNote}:
${JSON.stringify(tailStory, null, 2)}`;
}

/**
 * 이 장만 다시 쓰기 — 연재에서 「3장의 대사를 다시 써보자」는 흔한 판단이다.
 * 같은 id로 돌려받아야 그림·판정·조판을 지키면서 대본만 갈아끼울 수 있다.
 */
export function buildChapterRewritePrompt(
  story: Story,
  chapterTitle: string,
  scenes: Scene[],
): string {
  return `너는 비주얼노벨 시나리오 작가다. 아래는 한 작품의 «${chapterTitle}» 부분이다.
이 장의 컷들을 더 좋게 «다시 써라» — 새 컷을 만들지 말고, 있는 컷의 내용만 고쳐라.

출력 규칙 (반드시 지켜라):
- 출력은 JSON 하나만: {"scenes":[ … ]} (코드펜스·설명 금지)
- **id는 그대로 두어라** — id가 같아야 이미 찍어둔 그림을 지키면서 대본만 갈아끼울 수 있다
- 컷 수를 늘리거나 줄이지 마라 (${scenes.length}컷 그대로)
- next·choices의 연결 구조도 그대로 두어라 (이야기 뼈대는 유지)
${RULES}
- 새 인물은 만들지 말고 기존 캐릭터 id만 써라
- 화풍: ${story.style}
${story.note ? `- 감독 노트: ${story.note.replace(/\n/g, " ")}\n` : ""}
다시 쓸 부분:
${JSON.stringify({ scenes }, null, 2)}`;
}
