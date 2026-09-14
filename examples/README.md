# story.json 예시 모음

비주얼노벨 스튜디오가 읽는 `story.json` 형식 예시입니다. 세 파일 모두 **실제 앱 파서로 검증**되어
있습니다 — `npm run verify:examples` 로 언제든 다시 확인할 수 있어요 (에러·경고 0이면 통과).

| 파일 | 용도 | 넣는 곳 |
| --- | --- | --- |
| [`story.full.example.json`](story.full.example.json) | 배우 + 6컷 + 분기 + reuse + 소리/음악 — 완전한 새 작품 | 대본실 상단 **내 기기에서 불러오기** (`.json` 그대로) |
| [`story.append.example.json`](story.append.example.json) | 뒤에 이어 붙일 장면만 (`{ "scenes": [...] }`) | 컷 목록의 **스토리 이어서 만들기** |
| [`story.minimal.example.json`](story.minimal.example.json) | 꼭 필요한 최소 필드만 | 어느 쪽이든 |
| [`story.novel.example.json`](story.novel.example.json) | **소설 각색본** — 장 나누기·분기·shot 여섯 종을 실제 원고에서 옮긴 예 | 대본실 상단 **내 기기에서 불러오기** |

LLM에게 콘티를 맡기려면 [`grok-skill.ko.md`](grok-skill.ko.md)(그록 스킬로 등록하는 지시문 전문)나
[`grok-prompt.ko.md`](grok-prompt.ko.md)(손으로 복사하는 짧은 템플릿)를 쓰세요. 받은 JSON은
`npm run lint:story -- 파일.json`으로 검사할 수 있습니다(파서 검증 + 프롬프트·조판이 조용히 버리는 자리).

## 최상위 구조

```json
{
  "title": "작품 제목",
  "style": "모든 컷의 밑그림이 되는 화풍(영어 권장)",
  "note": "감독 노트 — 선택. 나만 보는 메모이자 AI 이어쓰기에 함께 전달",
  "characters": [ /* 배우 명단 */ ],
  "scenes":     [ /* 컷 목록 — 순서가 곧 표시 순서 */ ]
}
```

- **필수는 `scenes` 하나뿐**입니다. `title`이 없으면 「무제」, `style`이 비면 경고만 나고 진행됩니다.
- 이어쓰기 fragment는 `{ "scenes": [...] }` 만 있으면 됩니다 — `title`/`style`/`characters`는
  기존 작품 것을 그대로 물려받습니다.

## characters[] — 배우

```json
{ "id": "jun", "name": "준", "ref": "jun.jpg", "look": "20s man, short black hair, navy hoodie" }
```

| 필드 | 의미 |
| --- | --- |
| `id` | **필수.** 장면의 `chars`·`speaker`가 이 id로 배우를 가리킵니다. |
| `name` | 화면에 보이는 이름. 없으면 `id`를 씁니다. |
| `ref` | 캐스팅 사진 **파일명**. 같은 이름 사진을 올리면 자동으로 걸립니다(달라도 배우 카드에서 직접 지정 가능). |
| `look` | 외모 묘사(영어). 프롬프트에 실려 얼굴·복장을 고정하는 데 돕습니다. |

## scenes[] — 컷

```json
{
  "id": "s01",
  "shot": "full",
  "bg_prompt": "empty convenience store at 3am, rain on the window",
  "chars": ["jun"],
  "pose": "leaning on the counter",
  "emotion": "bored, sleepy",
  "text": "새벽 3시. 오늘도 손님은 없다.",
  "speaker": "jun",
  "sfx": "rain",
  "bgm": true,
  "next": "s02"
}
```

| 필드 | 의미 |
| --- | --- |
| `id` | **필수.** 장면마다 유일해야 합니다(중복은 에러). 관례상 `s01`, `s02`, 분기는 `s04a`/`s04b`. |
| `shot` | `full`(전체 장면) 또는 `focus`(얼굴 클로즈업). 생략 시 앱 기본값. |
| `bg_prompt` | 배경 묘사(영어, cinematic). `full` 컷에 씁니다. |
| `bg` | `"reuse:s01"` 형태면 s01의 그림을 **크레딧 없이 그대로 복사**합니다 — 같은 그림을 다시 쓸 때만. 자세가 바뀌는 연속 동작에는 쓰지 말고 `hold:true` + 같은 `bg_prompt`를 쓰세요. |
| `chars` | 이 컷에 등장하는 배우 `id` 배열. 켜진 배우의 캐스팅 사진이 얼굴 레퍼런스로 전달됩니다. |
| `pose` / `emotion` | 자세·표정(영어). 선택. |
| `text` | 이 컷에 흐르는 대사(한국어). |
| `speaker` | `"narration"` 또는 배우 `id`. |
| `sfx` | 분위기 소리 — `"rain"` \| `"wind"` \| `"night"` 중 하나. 선택. |
| `bgm` | `true`=이 컷부터 음악 시작 / `false`=정지 / 생략=그대로. |
| `next` | 다음 컷 `id`. 없으면 그 컷이 **엔딩**(크레딧). |
| `choices` | 갈림길. `[{ "label": "선택지 문구", "next": "s04a" }]` — `next`와 함께 쓰지 않습니다. |
| `placeholder` | `true`면 「자리표시」 컷. 이어쓰기로 같은 id가 오면 그때 교체됩니다. |

## 분기 (choices)

```json
{
  "id": "s03",
  "text": "「…따뜻한 거, 있어요?」",
  "speaker": "guest",
  "choices": [
    { "label": "따뜻한 커피를 건넨다",   "next": "s04a" },
    { "label": "말없이 온장고를 가리킨다", "next": "s04b" }
  ]
}
```

`choices`가 있으면 `next`는 무시됩니다. 각 갈래의 `next`는 실제 장면 id를 가리켜야 하며,
없는 id를 가리키면 조감독 리포트가 경고합니다(에러는 아님).

## 검증

```bash
npm run verify:examples
```

이 폴더의 `*.example.json`을 실제 앱 파서로 돌려 **에러·경고 0**인지 확인합니다. 직접 만든
`story.json`이 걱정되면 이 폴더에 넣고 돌려보거나, 앱의 **고급 → story.json 전체 편집**에
붙여넣으면 파서 경고를 그 자리에서 볼 수 있습니다.
