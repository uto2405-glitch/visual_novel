# 그록(또는 ChatGPT/Claude)에게 story.json 부탁하기

> **앱 안에서 자동으로도 됩니다.** 대본실 컷 목록의 **✨ 버튼**을 누르면 프롬프트가 만들어져요.
> - 새 프로젝트(빈 대본) → **✨ AI로 초안 만들기** (소재만 채우면 됨)
> - 대본이 있으면 → **✨ AI 이어쓰기 프롬프트** (현재 대본까지 담아서 만들어 줌)
>
> 손으로 부탁하고 싶을 때 아래 템플릿을 그대로 복사해 쓰세요.

---

## A. 처음부터 새로 만들 때

아래를 그록에 붙여넣고 **맨 위 `[소재]` 한 줄만** 원하는 이야기로 바꾸세요. 받은 JSON 전체를
앱의 **고급 → story.json 전체 편집**에 붙여넣고 「반영하기」를 누르면 됩니다.

```text
너는 비주얼노벨 시나리오 작가다. 아래 소재로 story.json 한 벌을 처음부터 만들어라.

[소재: 비 오는 밤, 편의점에서 오래 못 본 친구를 우연히 만나는 이야기]

출력 규칙 (반드시 지켜라):
- 출력은 JSON 객체 하나만. 코드펜스(```)·설명·인사말 전부 금지.
- 최상위: { "title": 한국어 제목, "style": 화풍(영어, cinematic), "characters": [...], "scenes": [...] }
- characters[]: { "id": 영문소문자, "name": 한국어 이름, "ref": "id.jpg", "look": 외모(영어) }
- id는 유일하게(s01, s02 …). 분기 갈래는 s03a/s03b 식
- shot은 "full"(전체 장면) 또는 "focus"(얼굴 클로즈업)
- full 컷엔 bg_prompt(영어, cinematic). 그림까지 완전히 같아도 되는 컷만 bg:"reuse:그 컷 id"
- 같은 자리에서 자세만 바뀌는 연속 동작은 hold:true + 같은 bg_prompt를 다시 적어라. bg:"reuse:…"는 그림을 복사하므로 연속 동작에는 쓰지 마라
- 인물이 보이는 컷은 chars:["캐릭터 id"], pose·emotion(영어)도 함께
- text는 한국어 대사, speaker는 "narration" 또는 캐릭터 id
- 이어짐은 next:"다음 컷 id". 갈림길은 choices:[{label,next}] (next와 같이 쓰지 마라)
- 선택: sfx는 "rain"|"wind"|"night", bgm은 true(음악 시작)/false(정지) — 꼭 필요한 곳에만
- 마지막 컷은 next 없이 끝(엔딩)
- 배우 2~3명, 8~12컷, 선택지 갈래 최소 1개.

형식이 헷갈리면 아래 예시와 똑같은 구조로 만들어라 (내용은 새로):
{"title":"막차 지난 역","style":"cinematic realistic photo, soft lighting, visual novel still, consistent face matching reference, 16:9","characters":[{"id":"jun","name":"준","ref":"jun.jpg","look":"20s korean man, short black hair, navy coat"}],"scenes":[{"id":"s01","shot":"full","bg_prompt":"rainy night train station, neon signs","chars":["jun"],"emotion":"lonely","text":"막차는 이미 떠난 뒤였다.","speaker":"jun","sfx":"rain","bgm":true,"next":"s02"},{"id":"s02","shot":"focus","chars":["jun"],"emotion":"hesitant","text":"「…조금만 더 기다려 볼까.」","speaker":"jun","choices":[{"label":"돌아선다","next":"s03a"},{"label":"벤치에 앉는다","next":"s03b"}]},{"id":"s03a","shot":"full","bg":"reuse:s01","text":"발길을 돌렸다.","speaker":"narration"}]}
```

## B. 이미 있는 대본을 이어쓸 때

`[여기에 현재 story.json 붙여넣기]` 자리에 지금 대본을 넣으세요. 받은 JSON(`{"scenes":[…]}`)을
앱의 **스토리 이어서 만들기**에 붙여넣으면 됩니다. (앱 ✨ 버튼을 쓰면 이 붙여넣기까지 자동입니다.)

```text
너는 비주얼노벨 시나리오 작가다. 아래 대본(JSON)의 이야기를 자연스럽게 이어서 새 장면들만 만들어라.

출력 규칙 (반드시 지켜라):
- 출력은 JSON 하나만: {"scenes":[ … ]} (코드펜스·설명 금지)
- 새 장면 id는 기존과 겹치지 않게 (예: s09, s10 …). 분기 갈래는 s10a/s10b 식
- shot은 "full" 또는 "focus". full 컷엔 bg_prompt(영어). bg:"reuse:그 컷 id"는 그림을 그대로 복사할 때만
- 인물이 보이는 컷은 chars:["기존 캐릭터 id"], pose·emotion(영어)
- text는 한국어 대사, speaker는 "narration" 또는 기존 캐릭터 id
- 이어짐은 next, 갈림길은 choices:[{label,next}]
- 선택: sfx는 "rain"|"wind"|"night", bgm은 true/false
- 새 인물은 만들지 말고 기존 캐릭터 id만 써라
- 5~8컷, 선택지 갈래 1개 이상

현재 대본:
[여기에 현재 story.json 붙여넣기]
```

---

## 그록이 자주 하는 실수와 대처

- **답을 ```json … ``` 코드블록으로 감쌈** → 앱이 `{` 부터 `}` 까지만 붙여넣으면 읽습니다. 위
  규칙의 "코드펜스 금지"가 대부분 막아줍니다.
- **`next`와 `choices`를 같이 씀** → `choices`가 있으면 `next`는 무시됩니다(문제는 없지만 지저분).
- **없는 컷/배우를 가리킴** → 앱의 **조감독 리포트**가 경고로 짚어줍니다. 치명적이지 않아요.
- **형식이 의심스러우면** → 앱 **고급 → story.json 전체 편집**에 붙여넣으면 파서 경고가 그 자리에
  뜹니다. 또는 [`story.full.example.json`](story.full.example.json)을 그록에게 함께 주며
  "이 형식 그대로" 라고 하면 정확도가 크게 올라갑니다.
