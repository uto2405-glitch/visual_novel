# 데이터 스키마 — 단일 출처

이 저장소가 읽고 쓰는 **모든 필드**의 정본이다. `templates/` 는 이 표와 같은 모양을 유지하고,
스키마를 바꿀 때는 **이 문서를 먼저** 고친다.

표 읽는 법

| 열 | 뜻 |
|---|---|
| **필수** | ✅ 없으면 검사기 FAIL · ⬜ 선택(없어도 됨) · ⚠ 특정 단계 이상에서만 필수 |
| **쓰는 쪽** | 이 값을 파일에 기록하는 주체 (사람 = 직접 편집 또는 스튜디오 UI) |
| **읽는 쪽** | 이 값을 실제로 소비하는 코드 |
| **검사기** | `tools/check_protocol.py` 가 보는가 (A1~A8 중 어느 항목인지) |

> **읽는 쪽이 "(없음)" 인 필드는 어떤 코드도 소비하지 않는다.** 기록용이거나, 아직 연결되지
> 않은 스키마다. 해당 칸에 이유를 적어 두었다.

---

## 1. `project/manifest.json` — 프로젝트 + 기준정보

작품당 **하나**. 프로젝트 설정과 캐릭터/장소/소품 기준정보를 전부 여기에 둔다.

### 1.1 최상위

| 필드 | 타입 | 필수 | 쓰는 쪽 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|---|
| `project_id` | str | ✅ | 사람 | (식별용) | **A1** 키 존재 |
| `title` | str | ✅ | 사람 | 감상본 제목 · 컨택트시트 제목 · 스튜디오 헤더 | **A1** 키 존재 |
| `language` | str | ⬜ | 사람 | (없음) — 표기용 | — |
| `orchestrator` | obj | ⬜ | 사람 | `local_llm` · `grok_api` · 스튜디오(모드 표시) | — |
| `image_generator` | obj | ⬜ | 사람 | `makefun_client` | — |
| `output` | obj | ⬜ | 사람 | 프롬프트 조립 · 검사기 · 인화 | **A3** (`min_long_edge_px`) |
| `dating` | obj | ⬜ | 사람 | 뷰어·감상본 호감도 미터 | — |
| `episodes` | list | ⬜ | 사람 | 스튜디오 `/api/state` (화 단위 선택) | — |
| `talk` | obj | ⬜ | 사람 | `local_llm` 인물 대화 | — |
| `workflow` | obj | ⬜ | 사람 | (없음) — 사람이 지킬 게이트 선언 | — |
| `characters` | list | ✅ | 사람 | 프롬프트 앵커 · 대사 화자 · 대화 페르소나 | **A1 A2 A4 A6** |
| `locations` | list | ✅ | 사람 | 프롬프트 앵커 | **A1 A2 A6** |
| `props` | list | ⬜ | 사람 | 프롬프트 앵커 | **A2** |

`project_id` / `title` / `characters` / `locations` **네 개가 없으면 A1 이 즉시 FAIL** 하고
나머지 검사를 하지 않는다.

### 1.2 `orchestrator` — 스토리·프롬프트 담당

| 필드 | 타입 | 필수 | 읽는 쪽 |
|---|---|---|---|
| `provider` | str | ⬜ | 표기용 |
| `mode` | `"local"` \| `"api"` \| `"manual"` | ⬜ | 스튜디오가 `local` 일 때 로컬 LLM 경로를 켠다 |
| `api.base_url` | str | ⬜ | `local_llm` · `grok_api` 접속 주소 |
| `api.model` | str | ⬜ | 요청 모델명 · 스튜디오 표시 |
| `api.key_env` | str | ⬜ | 키를 담은 **환경변수 이름**. 로컬은 빈 문자열 |
| `api.note` | str | ⬜ | 사람용 메모 |

> `key_env` 에 적는 건 **변수 이름**이지 값이 아니다. 값을 적으면 A8/`secret_scan` 이 잡는다.

### 1.3 `image_generator` — 이미지 생성 담당

| 필드 | 타입 | 필수 | 읽는 쪽 |
|---|---|---|---|
| `provider` | str | ⬜ | 표기용 |
| `model` | str | ⬜ | `makefun_client` 의 `model_type` (기본 `a2e`) |
| `api.base_url` | str | ⬜ | `makefun_client` 접속 주소 |
| `api.token_env` | str | ⬜ | 토큰을 담은 **환경변수 이름** (`MAKEFUN_API_TOKEN`) |
| `note` | str | ⬜ | 사람용 메모 |

### 1.4 `output`

| 필드 | 타입 | 필수 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|
| `mode` | str | ⬜ | (없음) — 표기용 | — |
| `print_ready` | bool | ⬜ | (없음) — 표기용 | — |
| `aspect_ratio` | str | ⬜ | 프롬프트 입력 조립(`make_grok_input`) | — |
| `min_long_edge_px` | int | ⬜ | 검사기 해상도 기준 · `makefun_client` 생성 크기 · `print_preflight` | **A3** (기본 1024) |
| `visual_style` | str | ⬜ | 프롬프트 조립의 **작품 전체 화풍** (최우선) | — |

**화풍 우선순위**: `output.visual_style` → 장면의 `visual_style` → 코드 기본값
(`vn_core.DEFAULT_VISUAL_STYLE`). 매니페스트에 값이 있으면 장면 오버라이드는 무시된다.

**`min_long_edge_px` 는 화면 감상 기준이다.** 실물 인화를 하려면 올려야 한다 —
4×6 엽서 1800px, 5×7 2250px. → [PRINT_ORDER_GUIDE.md](PRINT_ORDER_GUIDE.md)

### 1.5 `dating` · `episodes` · `talk`

| 필드 | 타입 | 필수 | 읽는 쪽 |
|---|---|---|---|
| `dating.max` | int | ⬜ | 뷰어·감상본 호감도 상한 (기본 100) |
| `dating.start_affection` | int | ⬜ | 시작 호감도 (기본 30) |
| `episodes[].episode` | int | ⬜ | 스튜디오 `/api/state` — 화 목록 |
| `episodes[].title` | str | ⬜ | 화 이름 |
| `episodes[].note` | str | ⬜ | 사람용 메모 |
| `talk.character_id` | str | ⬜ | 인물 대화의 기본 상대. 없으면 첫 캐릭터 |
| `talk.relationship` | str | ⬜ | 페르소나 관계 설정 (기본 `"다정한 여자친구"`) |
| `talk.base_url` | str | ⬜ | 대화용 LLM 주소 |

`dating` 이 **없으면** 뷰어·감상본에서 호감도 미터 자체가 숨는다(선형 작품).

### 1.6 `characters[]`

| 필드 | 타입 | 필수 | 쓰는 쪽 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|---|
| `character_id` | str | ✅ | 사람 | 장면 참조 · 대사 화자 | **A2** 존재·중복 |
| `name` | str | ⬜ | 사람 | 감상본 화자 이름 · 대화 페르소나 | — |
| `version` | int | ⬜ | 사람 | 프롬프트 입력 표기 | — |
| `profile.age` | str | ⬜ | 사람 | 프롬프트 입력 · 대화 페르소나 | — |
| `profile.gender_presentation` | str | ⬜ | 사람 | 프롬프트 입력 · 대화 페르소나 | — |
| `profile.hair` / `eyes` | str | ⬜ | 사람 | 프롬프트 입력 · 대화 페르소나 | — |
| `profile.build` | str | ⬜ | 사람 | 프롬프트 입력 | — |
| `profile.wardrobe` | str | ⬜ | 사람 | 프롬프트 입력 · 대화 페르소나 | — |
| `profile.signature_props` | list[str] | ⬜ | 사람 | 프롬프트 입력 · 대화 페르소나 | — |
| `profile.personality` | str | ⬜ | 사람 | **대화 페르소나**(`local_llm`) `[너의 성격]` | — |
| `profile.speech_style` | str | ⬜ | 사람 | **대화 페르소나**(`local_llm`) `[말투 규칙]` | — |
| `reference_images` | list[str] | ⬜ | 사람 | 프롬프트 입력의 첨부 안내 | — |
| `prompt_anchor` | str | ⚠ | 사람 | 프롬프트 조립 · `scene_lint` 역방향 검사 | **A6 필수** |
| `wardrobe_default` | str | ⬜ | 사람 | **(없음)** — 아래 참조 | — |
| `wardrobe_variants[]` | list[obj] | ⬜ | 사람 | **(없음)** — 아래 참조 | — |

**`prompt_anchor` 는 사실상 필수다.** 장면이 `IMAGE` 단계에 오르면 A6 이 "그 캐릭터의
`prompt_anchor` 가 기준정보에 없음"으로 FAIL 한다. 컷 간 얼굴·의상 일관성의 유일한 근거다.

#### 의상 배리에이션 — 정의만 있고 **아직 연결되지 않았다**

`wardrobe_default` 와 `wardrobe_variants[]` 는 **어떤 코드도 읽지 않는다.** 장면에서
어느 배리에이션을 쓸지 지정할 방법이 없어 연결 자체가 불가능한 상태다.

배리에이션 항목의 모양(작성해 두면 나중에 그대로 쓰인다):

| 필드 | 타입 | 뜻 |
|---|---|---|
| `variant_id` | str | 장면에서 가리킬 키 (`"default"`, `"summer_festival"` …) |
| `label` | str | 사람이 보는 이름 (`"여름 축제"`) |
| `season` | str | 계절 힌트 (`"봄"` · `"공용"`) |
| `anchor` | str | 프롬프트에 그대로 들어갈 영문 구절 |

연결될 때 장면 쪽에 붙을 규약(**지금은 쓰지 마라**):

```json
"wardrobe": { "CHAR-001": "summer_festival" }
```

장면의 선택 필드로 두고, 프롬프트 조립 시 그 캐릭터의 `prompt_anchor` 안 의상 구절을 해당
`anchor` 로 갈아 끼우는 방식이다. **이 연결은 A6(앵커 포함 검사)의 판정 대상과 직접 맞물리므로**
— 앵커 원문이 바뀌면 A6 이 "앵커가 프롬프트에 없음"으로 FAIL 할 수 있다 — 별도 작업으로
A6 상호작용을 확인한 뒤에 구현한다. 그때까지 **장면 데이터에 `wardrobe` 를 넣지 않는다.**

### 1.7 `locations[]` · `props[]`

| 필드 | 타입 | 필수 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|
| `location_id` | str | ✅ | 장면 참조 | **A2** 존재·중복 |
| `name` · `description` | str | ⬜ | 프롬프트 입력 | — |
| `reference_images` | list[str] | ⬜ | 프롬프트 입력의 첨부 안내 | — |
| `prompt_anchor` | str | ⚠ | 프롬프트 조립 | **A6** (값이 있으면 프롬프트 포함을 강제) |
| `prop_id` | str | ✅(props) | 장면 참조 | **A2** 존재·중복 |

> **장소 앵커에 시간대를 넣지 마라.** `"at sunset"` 이 앵커에 박혀 있으면 밤 장면 프롬프트에도
> 따라 들어간다. 시간대는 장면의 `time` 필드가 담당하고, `scene_lint` 의 `time-mismatch` ·
> `time-mixed` 경고가 이 혼재를 잡는다.

---

## 2. `project/scenes/SCENE-XXX.json` — 장면

파일 1개 = 장면 1개. **파일명(stem)과 `scene_id` 가 반드시 같아야 한다**(A2).
ID 형식은 `SCENE-` + 3자리 이상 숫자 (`^SCENE-\d{3,}$`).

### 2.1 필수 · 식별

| 필드 | 타입 | 필수 | 쓰는 쪽 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|---|
| `scene_id` | str | ✅ | `advance_scene new` | 전 도구 | **A2** 파일명 일치 |
| `scene_order` | int | ✅ | `advance_scene new` | 재생 순서 · 인화 파일명 접두사 | **A5** 1부터 연속·중복 금지 |
| `status` | enum | ✅ | `scene_ops` (사람이 전이) | 검사기 게이트 · 감상본 포함 여부 | **A2 A3 A6 A7** |
| `episode` | int | ⬜ | 사람 | 스튜디오 `/api/state` (화 단위 선택) | — |
| `version` | int | ⬜ | 사람 | (없음) — 기록용 | — |

`status` 값과 그 의미:

```
SCENE_PLAN → PROMPT → IMAGE → REVIEW_AUTO → REVIEW_HUMAN → APPROVED
                                        되돌리기 ↘ REVISE
```

**검사기는 상태에 맞는 항목만 본다.** `SCENE_PLAN` 장면은 이미지도 프롬프트도 없어야 정상이고
FAIL 이 아니다. `REVISE` 는 이후 단계 검사를 강제하지 않는다.

| 단계 | 그 단계부터 강제되는 것 |
|---|---|
| `PROMPT` | `prompt.grok_output` 이 있으면 A6 앵커 검사 대상 |
| `IMAGE` 이상 | A6 프롬프트 필수 · A3 이미지 경로/존재/해상도 |
| `REVIEW_HUMAN` 이상 | A3 `selected_image` 필수 · A7 `review.auto == "PASS"` |
| `APPROVED` | A7 `review.auto == review.human == "PASS"` |

### 2.2 장면 계획 (사람이 채운다 · 프롬프트의 재료)

| 필드 | 타입 | 필수 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|
| `location_id` | str | ✅ | 프롬프트 장소 앵커 | **A2** 매니페스트 등록 확인 |
| `characters` | list[str] | ✅ (비면 FAIL) | 프롬프트 인물 앵커 | **A2** 등록 확인 · **A4** 화자 대조 |
| `props` | list[str] | ⬜ | 프롬프트 소품 앵커 | **A2** 등록 확인 |
| `time` | str | ⬜ | 프롬프트 입력 · `scene_lint` 시간대 대조 | — |
| `purpose` | str | ⬜ | 프롬프트 입력 · 스튜디오 카드 · 컨택트시트 라벨 · 감상본 | — |
| `action_beat` | str | ⬜ | 프롬프트 입력 · 직전 장면 연속성 | — |
| `emotion` | str | ⬜ | 프롬프트 입력 · `scene_lint` 감정 반복 | — |
| `camera.shot` | str | ⬜ | 프롬프트 입력 · `scene_lint` 컷 반복·어휘 | — |
| `camera.angle` | str | ⬜ | 프롬프트 입력 · `scene_lint` 어휘 | — |
| `camera.framing` | str | ⬜ | 프롬프트 입력 | — |
| `camera.focus` | str | ⬜ | 프롬프트 입력 | — |
| `visual_style` | str | ⬜ | 프롬프트 화풍 (매니페스트 값이 있으면 무시됨) | — |

#### 카메라 표준 어휘 (`scene_lint` 권고 — PASS/FAIL 아님)

표기가 흔들리면(`"eye level"` vs `"eye-level"`) 컷 반복 감지가 무력화되므로 통일한다.

```
shot : extreme-wide / wide / full / medium-wide / medium /
       medium-close-up / close-up / extreme-close-up / two-shot / over-the-shoulder / pov
angle: eye-level / high-angle / low-angle / overhead /
       birds-eye / worms-eye / dutch-angle / front / side / rear
```

`"medium shot"` → `"medium"`, `"eye level"` → `"eye-level"` 처럼 **군더더기 접미와 공백을 뺀
형태**가 표준이다. 표준 어휘 밖 값은 `info`, 표준으로 정규화 가능한 흔들림은 `warn` 이 뜬다.

### 2.3 `prompt`

| 필드 | 타입 | 필수 | 쓰는 쪽 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|---|
| `grok_input_version` | int | ⬜ | 템플릿 | (없음) — 기록용 | — |
| `grok_output` | str | ⚠ | `scene_ops.set_prompt` | 이미지 생성 · 스튜디오 · `scene_lint` | **A6** IMAGE 이상 필수 |
| `external_generator` | str | ⬜ | 사람 | (없음) — 기록용 | — |
| `external_model` | str | ⬜ | 사람 | (없음) — 기록용 | — |

**A6 이 보는 것**: `grok_output` 안에 이 장면 `characters` 전원의 `prompt_anchor` **원문**이
(또는 `character_id` 문자열이) 들어 있는가, 장소 앵커가 들어 있는가. 이게 컷 간 일관성의 근거다.
`scene_lint` 는 그 역방향 — **등장 목록에 없는** 인물의 앵커가 섞였는지도 경고한다.

### 2.4 `dialogue[]`

| 필드 | 타입 | 필수 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|
| `speaker_id` | str | ✅ | 감상본 화자 이름·색 | **A4** 등록 + **이 장면 `characters` 에 포함**되어야 함 |
| `text` | str | ✅ | 감상본 대사 · 스튜디오 | **A2** 키 존재 |
| `placement` | `"bottom"` \| `"top"` … | ⬜ | 감상본 대사창 위치 · 프롬프트 여백 지시 (기본 `bottom`) | — |

**대사 원문은 이미지 프롬프트에 넣지 않는다.** 프롬프트 입력에는 "여기에 빈 공간을 확보하라"는
배치 지시만 들어간다(CLAUDE.md 데이터 원칙).

속마음은 **괄호**로 감싼다: `"(오늘 하루, 오래 기억에 남을 것 같아.)"`

### 2.5 분기 · 엔딩 (선택 — 연애 시뮬용)

| 필드 | 타입 | 필수 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|
| `choices[].text` | str | ⬜ | 뷰어·감상본 선택지 버튼 | — |
| `choices[].affection` | int | ⬜ | 호감도 증감 | — |
| `choices[].goto` | scene_id | ⬜ | 이동할 장면. 없으면 다음 순서로 | — |
| `branch[].min` | int | ⬜ | 이 호감도 이상이면 | — |
| `branch[].goto` | scene_id | ⬜ | 그 장면으로 (위에서부터 첫 일치) | — |
| `ending` | bool \| str | ⬜ | 참이면 재생을 멈추고 엔딩 카드 | — |
| `ending_label` | str | ⬜ | 엔딩 이름 (`"호감 엔딩"`) | — |

**`ending_label` 규약**: `ending: true` 인 장면의 엔딩 이름은 `purpose` 안 괄호가 아니라
**이 필드**에 둔다. `purpose` 는 장면 설명(프롬프트 재료)이고 엔딩 이름은 감상자에게 보여 줄
라벨이라 쓰임이 다르다. 감상본은 `ending` 이 **문자열**이면 그 값을 엔딩 카드 이름으로 쓰는
경로도 갖고 있다 — 내보내기 쪽이 `ending_label` 을 우선 사용하도록 잇는다.

**`goto` 는 감상본에서 정리된다.** 이미지가 없어 감상본에 실리지 않은 장면을 가리키는 `goto` 는
`export_viewer` 가 경고와 함께 떼어 내고 선형 진행으로 폴백시킨다(선택지 자체는 살린다).

### 2.6 `assets`

`assets` **블록 자체는 필수 키**다(A2). 그 안의 필드는 단계에 따라 달라진다.

| 필드 | 타입 | 필수 | 쓰는 쪽 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|---|
| `raw_images` | list[str] | ⚠ | `scene_ops.register_images` | 스튜디오 후보 썸네일 | **A3** 나열된 파일이 실제로 있어야 함 |
| `selected_image` | str | ⚠ | `scene_ops.select_image` | 감상본 · 인화 · 갤러리 · 앨범 | **A3** REVIEW_HUMAN 이상 필수 |
| `makefun_tasks[]` | list[obj] | ⬜ | `makefun_client` (자동) | **재과금 없이 재수령** | — |

`IMAGE` 이상 단계에서는 `raw_images` 와 `selected_image` 중 **최소 하나**에 값이 있어야 하고
(둘 다 비면 A3 FAIL), `REVIEW_HUMAN` 이상에서는 `selected_image` 가 반드시 있어야 한다.

경로는 저장소 루트 기준 상대경로(`images/raw/SCENE-001/xxx.png`).
허용 확장자: `.png` `.jpg` `.jpeg` `.tif` `.tiff` `.webp` (A3 · `vn_core.IMAGE_EXTS`).
`selected_image` 는 존재·확장자에 더해 **긴 변이 `output.min_long_edge_px` 이상**이어야 한다.

#### `makefun_tasks[]` — 과금 복구 수단

유료 생성은 **task 를 만드는 순간 과금**된다. 다운로드만 실패했을 때 재생성(=재과금) 없이
다시 받기 위해 task id 를 장면에 남긴다. **지우지 마라.**

| 필드 | 타입 | 뜻 |
|---|---|---|
| `task_id` | str | MakeFun 작업 id — 이걸로 결과 이미지를 다시 받는다 |
| `created_at` | str | 생성 시각 |
| `width` · `height` | int | 요청한 픽셀 크기 |

최근 **20개**까지 보관하고 오래된 것부터 밀려난다. 기록 실패가 생성을 막지는 않는다
(이미 과금된 작업을 중단시키지 않기 위해).

### 2.7 `review`

| 필드 | 타입 | 필수 | 쓰는 쪽 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|---|
| `auto` | enum | ✅ | 자동 검사기 결과 | 상태 전이 게이트 | **A7** |
| `human` | enum | ✅ | **사람만** (승인 도장) | 상태 전이 게이트 | **A7** |
| `score` | int \| null | ⬜ | 사람 | (없음) — 기록용 | — |
| `notes` | list | ⬜ | `scene_ops.revise` · 사람 | 스튜디오 표시 | — |

허용 값: `PENDING` · `PASS` · `REVISE` · `REGENERATE` · `FAIL`

**`human` 은 자동으로 채우지 않는다.** SCORECARD C(캐릭터 일관성·연출·대사·몰입·인화 품질·화풍)는
사람 시사의 몫이고, 승인 도장은 사람만 찍는다. `APPROVED` 장면의 `status`·`selected_image` 를
바꾸려면 먼저 `revise` 로 되돌려야 한다 — `scene_ops` 가 모든 쓰기 경로에서 이를 막는다.

### 2.8 `print` — 인화 규칙 (선택)

명령행 값을 **장면 단위로 덮어쓴다**. 한 번 정해 두면 다음 주문에서도 그 컷만 그 규칙으로 굽는다.

| 필드 | 타입 | 필수 | 읽는 쪽 | 기본값 |
|---|---|---|---|---|
| `crop_anchor` | `center`\|`top`\|`bottom`\|`left`\|`right` | ⬜ | `print_export` 크롭 기준 · 스튜디오 크롭 미리보기 | `--anchor` 값 |
| `crop_mode` | `cover` \| `fit` | ⬜ | `print_export` — 채움 크롭 / 여백 채움 | `--mode` 값 |
| `pad_color` | str | ⬜ | `fit` 여백 색 (`"#f5f0e4"` · `"white"` · `"245,240,228"`) | `--bg` 값 |

```json
"print": { "crop_anchor": "top", "crop_mode": "fit", "pad_color": "#f5f0e4" }
```

얼굴이 프레임 위쪽에 있는 컷은 `crop_anchor: "top"`, 가장자리에 중요한 게 붙은 컷은
`crop_mode: "fit"`. → [PRINT_ORDER_GUIDE.md](PRINT_ORDER_GUIDE.md)

---

## 3. 파생 데이터 — 코드가 만들고 사람이 안 고치는 파일

여기 있는 파일은 **손으로 편집하는 대상이 아니다.** 지워도 기능은 살지만, 표의
"잃는 것"에 적힌 게 사라진다.

| 경로 | 만드는 쪽 | 읽는 쪽 | git | 지우면 잃는 것 |
|---|---|---|---|---|
| `images/raw/<scene_id>/` | 업로드 · MakeFun · 폴더 스캔 | 검사기 A3 · 감상본 · 인화 | ✂ 제외 | **원본 컷** — 되돌릴 수 없다 |
| `images/raw/<scene_id>/_gen_meta.json` | `makefun_client` | (없음) — 사람이 읽는 감사 기록 | ✂ 제외 | 어떤 프롬프트로 뽑았는지의 이력 |
| `project/favorites.json` | 스튜디오 갤러리 ★ | `print_export --only` · 스튜디오 | ✔ 추적 | 인화 후보 ★ 목록 |
| `logs/makefun_usage.jsonl` | `makefun_client` | 사람 (비용 추적) | ✂ 제외 | **종량제 지출 이력** |
| `logs/webapp.log` | 스튜디오 서버 | 사람 (장애 추적) | ✂ 제외 | 오류·생성 실패 기록 |
| `logs/lan_pin.txt` | 스튜디오 `--lan` | 사람 (PIN 확인) | ✂ 제외 | 이번 실행의 접속 PIN |
| `project/story/storyline.md` | 사람 + 로컬 LLM | 프롬프트 맥락 · 대화 페르소나 | ✔ 추적 | 작품 줄거리 |
| `project/story/character_bible.md` | 사람 | 대화 페르소나 `[너에 대한 기록]` | ✔ 추적 | 인물의 취향·기념일·기억 |
| `project/story/chatlog.json` | 스튜디오 스토리 탭 | 스토리 탭 이어하기 | ✂ **제외** | 기획 대화 |
| `project/story/talk_<CID>.json` | 인물 대화 | 대화 이어하기 · 기억 요약 | ✂ **제외** | 인물과 나눈 대화 |
| `project/story/memory_<CID>.json` | `local_llm` 요약 | 창 밖 맥락 주입 | ✂ **제외** | 압축된 장기 기억 |
| `output/` · `backups/` | 내보내기 · 백업 도구 | 사람 | ✂ 제외 | 재생성 가능 |

### 3.1 사적 데이터 — git 에서 제외되는 이유

`chatlog.json` · `talk_*.json` · `memory_*.json` 은 **인물과 나눈 사적 대화**이고 그 압축본이다.
원격 저장소에 올라가서는 안 되므로 `.gitignore` 가 셋 다 제외한다. 감상본 HTML 에도 들어가지
않는다 — 감상본에 실리는 건 제목·캐릭터 이름·대사·승인된 이미지뿐이다.
→ [PRIVACY_HOSTING.md](PRIVACY_HOSTING.md)

`logs/` 전체도 제외 대상이다. `makefun_usage.jsonl` 은 비용 이력이고 `lan_pin.txt` 는
이번 실행의 접속 PIN 이라 둘 다 기기 로컬에 남아야 한다.

### 3.2 `_gen_meta.json`

`images/raw/<scene_id>/` 안에 누적되는 생성 이력. 최근 **200건**까지 보관한다.

```json
{ "scene_id": "SCENE-007", "updated_at": "...",
  "entries": [ { "created_at": "...", "task_id": "...", "prompt": "...", "model": "a2e",
                 "width": 832, "height": 1248, "files": ["mf_424c98_1.jpg"],
                 "status": "ok", "error": "" } ] }
```

`status` 는 `ok` · `partial` · `failed` · `refetch`. 이미지 폴더 안에 있지만 후보 스캔은
**허용 확장자(§2.6)만** 집어 가므로 `.json` 인 이 파일은 후보로 잡히지 않는다.

### 3.3 `logs/makefun_usage.jsonl`

**append-only** 한 줄 = 한 요청. 종량제 지출을 되짚는 유일한 기록이다.

| 필드 | 뜻 |
|---|---|
| `ts` | 시각 |
| `scene_id` · `task_id` | 어떤 장면의 어느 작업인가 |
| `requested` · `saved` | 요청 장수 / 실제 저장된 장수 |
| `ok` | 완전 성공 여부 |
| `model` · `width` · `height` | 생성 파라미터 |
| `billable` | **과금 대상인가** — 재수령(`refetch: true`)은 `false` |
| `error` | 실패 사유(200자로 자름) |

### 3.4 `project/favorites.json`

갤러리에서 ★ 로 고른 인화 후보. **서버가 정본**이라 폰과 PC 가 같은 목록을 본다
(서버 응답이 없으면 브라우저 `localStorage` 로 폴백).

```json
{ "scene_ids": ["SCENE-003", "SCENE-007"] }
```

`print_export --only SCENE-003,SCENE-007` 로 이어진다. 형식이 깨져도 빈 목록으로 살아남고,
`SCENE-\d{3,}` 형식이 아닌 값은 걸러진다.

---

## 4. 스키마를 바꿀 때

1. **이 문서를 먼저 고친다** — 필수/선택 · 쓰는 쪽 · 읽는 쪽 · 검사기 열까지.
2. `templates/scene.json` · `templates/manifest.json` 을 같은 모양으로 맞춘다
   (새 작품이 구스키마로 시작되지 않도록).
3. `examples/` 도 맞춘다 — README 가 "데모로 초록불을 보라"고 안내하는 파일이고,
   `selftest` 가 이걸 복사해 검사기 PASS 를 확인한다.
4. `python tools/check_protocol.py` → **RESULT: PASS**, `python tools/selftest.py` → 전체 통과.

`protocol/SCORECARD.md` 와 `tools/check_protocol.py` 는 에이전트가 수정할 수 없다.
검사 기준 자체의 개정이 필요하면 CLAUDE.md 의 "채점표·검사기 개정 절차"를 따른다.
