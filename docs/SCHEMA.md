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
| `talk` | obj | ⬜ | 사람 | 인물 대화 — 페르소나 조립 `prompt_build` · 전송 `local_llm` | — |
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
| `max_long_edge_px` | int | ⬜ | `makefun_client` **생성 크기 상한** (기본 2048 · 하드 상한 4096) |
| `api.base_url` | str | ⬜ | `makefun_client` 접속 주소 |
| `api.token_env` | str | ⬜ | 토큰을 담은 **환경변수 이름** (`MAKEFUN_API_TOKEN`) |
| `note` | str | ⬜ | 사람용 메모 |

> ### ⚠ `max_long_edge_px` — 인화 해상도의 함정
> `makefun_client` 는 요청 픽셀을 **이 값으로 잘라 낸다**(`_cap_px()` → `_align8()`).
> 기본값이 2048 이므로 `output.min_long_edge_px` 만 2250·3600 으로 올리면
> **요청이 조용히 2048 로 깎여 검사기 A3 가 그 장면을 FAIL 시킨다** — 돈은 쓰고 규격은 못 맞춘다.
> 인화용으로 올릴 때는 **두 값을 함께** 올린다:
>
> ```json
> "output":          { "min_long_edge_px": 2250 },
> "image_generator": { "max_long_edge_px": 2560 }
> ```
>
> 실제로 몇 px 로 요청되는지는 과금 없이 확인할 수 있다:
> `python tools/makefun_client.py --check` → `생성 크기 1500x2250 (긴 변 2250px · 상한 2560px)`
> 하드 상한은 4096 이며, 이보다 큰 값을 적어도 4096 으로 잘린다.
> 공급자가 실제로 받아 주는 크기는 별개다 — 큰 값은 1장으로 먼저 시험한다.

### 1.4 `output`

| 필드 | 타입 | 필수 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|
| `mode` | str | ⬜ | (없음) — 표기용 | — |
| `print_ready` | bool | ⬜ | (없음) — 표기용 | — |
| `aspect_ratio` | str | ⬜ | `makefun_client` 생성 크기(`W:H`) · 프롬프트 입력 조립(`make_grok_input`) | — |
| `min_long_edge_px` | int | ⬜ | 검사기 해상도 기준 · `makefun_client` 생성 크기 · `print_preflight` | **A3** (기본 1024) |
| `visual_style` | str | ⬜ | 프롬프트 조립의 **작품 전체 화풍** (최우선) | — |

**화풍 우선순위**: `output.visual_style` → 장면의 `visual_style` → 코드 기본값
(`vn_core.DEFAULT_VISUAL_STYLE`). 매니페스트에 값이 있으면 장면 오버라이드는 무시된다.

**`aspect_ratio` 는 아직 완전히 배선되지 않았다.** `makefun_client` 는 이 값으로 생성 크기를
계산하고 `make_grok_input` 은 지시서에 적어 주지만, **`prompt_build` 는 `"portrait 2:3"` 을
하드코딩**한다(로컬 LLM 경로로 만든 프롬프트 문자열). 2:3 이 아닌 작품을 하려면 그 한 줄도
함께 고쳐야 한다.

**`min_long_edge_px` 는 화면 감상 기준이다.** 실물 인화를 하려면 올려야 한다 —
4×6 엽서 1800px, 5×7 2250px, 8×10 3600px.
**올릴 때는 `image_generator.max_long_edge_px`(기본 2048)도 함께 올린다.** 그러지 않으면
생성 요청이 2048 로 깎이고, 올려 둔 기준 때문에 오히려 A3 가 FAIL 한다(§1.3 경고 참조).
→ [PRINT_ORDER_GUIDE.md](PRINT_ORDER_GUIDE.md)

### 1.5 `dating` · `episodes` · `talk`

| 필드 | 타입 | 필수 | 읽는 쪽 |
|---|---|---|---|
| `dating.max` | int | ⬜ | 뷰어·감상본 호감도 상한 (기본 100) |
| `dating.start_affection` | int | ⬜ | 시작 호감도 (기본 30) |
| `episodes[].episode` | int | ⬜ | 스튜디오 `/api/state` — 화 목록 |
| `episodes[].title` | str | ⬜ | 화 이름 |
| `episodes[].note` | str | ⬜ | 사람용 메모 |
| `talk.character_id` | str | ⬜ | 인물 대화의 기본 상대. 없으면 첫 캐릭터 |
| `talk.relationship` | str | ⬜ | 페르소나 `[관계]` 한 줄 (기본 `"다정한 여자친구"`) |
| `talk.base_url` | str | ⬜ | 대화용 LLM 주소 |

`dating` 이 **없으면** 뷰어·감상본에서 호감도 미터 자체가 숨는다(선형 작품).

> **`relationship` 은 비워 두지 마라 — 키를 지워라.** 기본값은 `talk.get("relationship", …)`,
> 즉 **키가 없을 때만** 적용된다. `""` 는 '존재하는 값'이라 그대로 문장에 박혀
> `[관계] 상대는 너의 . 편하고 다정한 반말로…` 가 되고, 페르소나의 관계 설정이 통째로 빈다.
> 관계를 따로 정하지 않을 거면 **키 자체를 삭제**한다. (`dating` 처럼 "없으면 기능이 꺼지는"
> 블록과 달리, 여기서 빈 문자열은 기능을 끄는 게 아니라 **깨뜨린다**.)

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
| `profile.personality` | str | ⬜ | 사람 | **대화 페르소나**(`prompt_build`) `[너의 성격]` | — |
| `profile.speech_style` | str | ⬜ | 사람 | **대화 페르소나**(`prompt_build`) `[말투 규칙]` | — |
| `reference_images` | list[str] | ⬜ | 사람 | 프롬프트 입력의 첨부 안내 | — |
| `prompt_anchor` | str | ⚠ | 사람 | 프롬프트 조립 · `scene_lint` 역방향 검사 | **A6 필수** |
| `wardrobe_default` | str | ⬜ | 사람 | **(없음)** — 아래 참조 | — |
| `wardrobe_variants[]` | list[obj] | ⬜ | 사람 | **(없음)** — 아래 참조 | — |

**`prompt_anchor` 는 사실상 필수다.** 장면이 `IMAGE` 단계에 오르면 A6 이 "그 캐릭터의
`prompt_anchor` 가 기준정보에 없음"으로 FAIL 한다. 컷 간 얼굴·의상 일관성의 유일한 근거다.

**이 표가 캐릭터 스키마의 정본이다.** 캐릭터는 별도 파일이 아니라 `manifest.characters[]`
안에 산다. `templates/character.json` 은 여기에 붙여넣을 항목 1개짜리 조각일 뿐이다(§4).

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

`locations[]`

| 필드 | 타입 | 필수 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|
| `location_id` | str | ✅ | 장면 참조 | **A2** 존재·중복 |
| `name` · `description` | str | ⬜ | 프롬프트 입력 | — |
| `version` | int | ⬜ | **(없음)** — 템플릿에는 있지만 어떤 코드도 읽지 않는다. 캐릭터 쪽 `version` 만 프롬프트 입력에 찍힌다(`make_grok_input`) | — |
| `reference_images` | list[str] | ⬜ | 프롬프트 입력의 첨부 안내 | — |
| `prompt_anchor` | str | ⚠ | 프롬프트 조립 | **A6** (값이 있으면 프롬프트 포함을 강제) |

`props[]`

| 필드 | 타입 | 필수 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|
| `prop_id` | str | ✅ | 장면 참조 | **A2** 존재·중복 |
| `name` · `description` | str | ⬜ | 프롬프트 입력 (`[PROP-001] 이름 — 설명`) | — |
| `prompt_anchor` | str | ⬜ | 프롬프트 입력 (값이 있을 때만 한 줄 추가) | — |
| `reference_images` | list[str] | ⬜ | **(없음)** — 소품에는 첨부 안내가 없다. 캐릭터·장소만 읽는다 | — |

> **장소 앵커에 시간대를 넣지 마라.** `"at sunset"` 이 앵커에 박혀 있으면 밤 장면 프롬프트에도
> 따라 들어간다. 시간대는 장면의 `time` 필드가 담당하고, `scene_lint` 의 `time-mismatch` ·
> `time-mixed` 경고가 이 혼재를 잡는다.

---

## 2. `project/scenes/SCENE-XXX.json` — 장면

파일 1개 = 장면 1개. **파일명(stem)과 `scene_id` 가 반드시 같아야 한다**(A2).
ID 형식은 `SCENE-` + 3자리 이상 숫자 (`^SCENE-\d{3,}$`).

> ### ⚠ ID 형식은 **검사기가 보지 않는다**
> `check_protocol` 이 확인하는 건 "scene_id 와 파일명이 같은가" 뿐이다. 형식의 정본은
> **`vn_core.is_scene_id`** 이고, 이걸 관문으로 쓰는 쪽은 도구 전체다 —
> `advance_scene` · `scene_ops` · `make_grok_input` · `makefun_client` · `gen_jobs` · `webapp`.
> 그래서 손으로 만든 `SCENE-1.json`(또는 `SCENE-01`)은 **검사기 RESULT: PASS 를 받은 뒤**
> 프롬프트 생성·이미지 생성·상태 전이·웹 편집이 전부 "잘못된 scene_id" 로 거부된다.
> 되살릴 방법은 파일명과 `scene_id` 를 세 자리로 고쳐 쓰는 것뿐이니, 장면은
> **`advance_scene new` 나 `vn_compose` 로 만든다**(둘 다 형식을 보장한다).

### 2.1 필수 · 식별

| 필드 | 타입 | 필수 | 쓰는 쪽 | 읽는 쪽 | 검사기 |
|---|---|---|---|---|---|
| `scene_id` | str | ✅ | `advance_scene new` | 전 도구 | **A2** 파일명 일치 |
| `scene_order` | int | ✅ | `advance_scene new` | 재생 순서 · 인화 파일명 접두사 | **A5** 1부터 연속·중복 금지 |
| `status` | enum | ✅ | `scene_ops` (사람이 전이) | 검사기 게이트 · 감상본 포함 여부 | **A2 A3 A6 A7** |
| `episode` | int | ⬜ | 사람 | 스튜디오 `/api/state` (화 단위 선택) | — |
| `version` | int | ⬜ | **`scene_ops.revise`** (되돌릴 때마다 +1) | `revise` 결과 표시 — 그 밖엔 기록용 | — |

`status` 값과 그 의미:

```
SCENE_PLAN → PROMPT → IMAGE → REVIEW_HUMAN → APPROVED
     ↑__________________|  되돌리기: advance_scene revise <SCENE_PLAN|PROMPT|IMAGE>
```

자동 검사는 **후보 등록·이미지 선택 시점에 그 자리에서 실행**되고 결과는 `review.auto` 에 적힌다.
따로 머무는 단계가 아니다 — 검사가 PASS 면 `IMAGE` 가 곧바로 `REVIEW_HUMAN` 으로 올라간다
(`scene_ops.register_images` · `select_image`).

> ### ⚠ `REVIEW_AUTO` 는 **쓰면 안 되는 값**이다
> `check_protocol.SCENE_STATES` 열거에 이름만 남아 있어서 **검사기는 통과시킨다.** 그런데
> 이 값을 만드는 도구도, 이 값에서 다음 단계로 올려 주는 도구도 **없다** — 승격은 `IMAGE`
> 에서만 일어나고(`register_images`/`select_image`), `approve` 는 `REVIEW_HUMAN` 만 받는다.
> 손으로 `status: "REVIEW_AUTO"` 라고 적으면 그 장면은 초록불인 채로 **승인까지 영영 못 간다.**
> 빠져나오는 길은 `advance_scene revise <ID> IMAGE` 뿐이고, 그때 `selected_image` 는 비워진다.
>
> 같은 이유로 `status: "REVISE"` 도 직접 적지 않는다. `revise` 명령은 status 를 `REVISE` 가
> 아니라 **되돌아간 단계 이름**(`SCENE_PLAN`/`PROMPT`/`IMAGE`)으로 적는다. 열거값 `REVISE` 는
> 옛 데이터를 읽어 주기 위한 호환 항목이다.

**검사기는 상태에 맞는 항목만 본다.** `SCENE_PLAN` 장면은 이미지도 프롬프트도 없어야 정상이고
FAIL 이 아니다.

**status 값이 `REVISE` 인 옛 장면의 면제 범위는 A3 까지다.** 그런 장면은 이미지 검사(A3)에서 빠지지만,
**`prompt.grok_output` 이 남아 있으면 A6 앵커 검사는 계속 적용된다**
(`check_protocol` 은 A6 대상을 "IMAGE 이상 **또는** 프롬프트가 있는 장면"으로 잡는다).
즉 되돌려 놓은 장면이라도 프롬프트에서 앵커를 지우면 그 순간 A6 FAIL 이다.

| 단계 | 그 단계부터 강제되는 것 |
|---|---|
| `PROMPT` | `prompt.grok_output` 이 있으면 A6 앵커 검사 대상 |
| `IMAGE` 이상 | A6 프롬프트 필수 · A3 이미지 경로/존재/해상도 |
| `REVIEW_HUMAN` 이상 | A3 `selected_image` 필수 · A7 `review.auto == "PASS"` |
| `APPROVED` | A7 `review.auto == review.human == "PASS"` |

#### 손으로 고쳐도 되는 필드 / 도구만 쓰는 필드

세 갈래다. 정본은 `scene_ops` 의 두 상수 — `EDITABLE_FIELDS` 와 `PROTECTED_FIELDS` 다.

| | 필드 | 쓰는 방법 |
|---|---|---|
| **편집 가능** | `purpose` · `action_beat` · `emotion` · `time` · `camera` · `dialogue` · `characters` · `location_id` · `episode` · `choices` · `branch` · `ending` · `ending_label` · `print` | 스튜디오 장면 편집(`POST /api/set-scene` — 이 목록만 병합) 또는 직접 편집 |
| **도구 전용** (`PROTECTED_FIELDS` 7개) | `status` · `review` · `assets` · `prompt` · `scene_id` · `scene_order` · `version` | `scene_ops`/`advance_scene` 만. 편집 경로는 **"건드리면 안 되는 필드"** 로 거부한다 |
| **직접 편집만** | `props` · `visual_style` | 편집 경로의 화이트리스트에 **없어서** `set-scene` 이 "모르는 필드" 로 거부한다. 파일을 직접 고친다 |

`status`·`review`·`assets` 는 상태 전이·승인 잠금·과금 복구(`makefun_tasks`)가 걸려 있어
손으로 고치면 불변식이 깨진다. APPROVED 장면은 편집 경로에서도 거부되고, 먼저 `revise` 로
되돌려야 한다.
`prompt` 는 `scene_ops.set_prompt` 가 A6 앵커를 확인하며 쓰는 값이고,
`version` 은 `scene_ops.revise` 가 되돌릴 때마다 1씩 올린다(그래서 편집 경로가 막혀 있다).

### 2.2 장면 계획 (프롬프트의 재료)

**쓰는 쪽**: 사람(스튜디오 장면 편집 또는 직접 편집) · `vn_compose`(스토리라인 → 장면 구성).
단 **`props` 와 `visual_style` 은 스튜디오 편집으로 못 바꾼다** — `EDITABLE_FIELDS` 밖이라
`set-scene` 이 거부한다. 이 둘은 파일을 직접 고친다(앞의 세 갈래 표 참조).

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
       medium-close-up / close-up / extreme-close-up / two-shot /
       over-the-shoulder / pov / insert
angle: eye-level / high-angle / low-angle / overhead /
       birds-eye / worms-eye / dutch-angle / front / side / rear
```

> **정본은 코드다** — `scene_lint.STD_SHOTS` / `STD_ANGLES`. 위 목록은 그 사본이므로,
> 어휘를 늘릴 때는 코드를 먼저 고치고 이 표를 맞춘다.
> (`insert` = 손·시계·쪽지 같은 사물만 채우는 삽입 컷.)

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

`dialogue` **배열 자체가 A2 필수 키**다. `assets`·`review` 와 같은 취급이라, 대사 없는 컷이라도
키를 빼면 `필수 키 없음: dialogue` 로 FAIL 한다. 대사가 없으면 **빈 배열**을 둔다:

```json
"dialogue": []
```

(A2 가 키 존재를 요구하는 7개: `scene_id` · `scene_order` · `location_id` · `characters` ·
`dialogue` · `assets` · `review`.)

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
| `ending_label` | str | ⬜ | 엔딩 이름 (`"호감 엔딩"`) — 감상본·스튜디오 엔딩 카드 | — |

**`ending_label` 규약**: `ending: true` 인 장면의 엔딩 이름은 `purpose` 안 괄호가 아니라
**이 필드**에 둔다. `purpose` 는 장면 설명(프롬프트 재료)이고 엔딩 이름은 감상자에게 보여 줄
라벨이라 쓰임이 다르다.

**엔딩 카드 이름의 우선순위는 한 곳에 있다** — `vn_runtime.js` 의 `endLabelOf()`.
스튜디오 뷰어와 감상본이 같은 재생 엔진을 쓰므로 **양쪽이 같은 순서**로 고른다:

```
ending_label  →  (옛 데이터의 문자열 ending — 적재할 때 ending_label 로 정규화)  →  purpose
```

`ending: "호감 엔딩"` 처럼 이름을 문자열로 넣은 옛 데이터도 그대로 재생된다
(`vn_runtime` 의 `normScene()` · `export_viewer.ending_of()` 가 label 로 옮긴다).
새로 쓰는 데이터는 `ending: true` + `ending_label` 로 통일한다 — `vn_compose` 의 분기
지시문이 그 형태를 만들고, `/api/state` 도 장면마다 `ending_label` 을 함께 실어 보낸다.

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
사람 시사의 몫이고, 승인 도장은 사람만 찍는다. 그 6개 항목을 하나씩 적어 두고 싶을 때 쓰는
서식이 `templates/review-report.json` 이다 — **장면 파일에는 들어가지 않는** 별도 기록이고,
장면에 남는 것은 위 표의 `review` 블록뿐이다. `APPROVED` 장면의 `status`·`selected_image` 를
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

> **적어 둔 값은 명령행보다 세다.** `print_export` 는 장면 값이 있으면 그것을 쓰고 없을 때만
> `--anchor`/`--mode`/`--bg` 를 쓴다(`export_batch`: `pol.get("crop_anchor", anchor)`).
> 그래서 **필요한 컷에만** 적는다 — 모든 장면에 `"crop_anchor": "center"` 같은 기본값이
> 박혀 있으면 `--anchor top` 이 아무 말 없이 무시된다. 같은 이유로
> `templates/scene.json` 에는 `print` 블록을 두지 않는다(새 장면 전부에 복사되므로).

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
| `project/grok_inputs/<scene_id>.txt` | `make_grok_input` | 사람 (grok.com 에 붙여넣는 입력) | ✂ 제외 | 없음 — 언제든 다시 만든다 |
| `project/story/storyline.md` | 사람 + 로컬 LLM | 프롬프트 맥락 · 대화 페르소나 | ✔ 추적 | 작품 줄거리 |
| `project/story/character_bible.md` | 사람 | 대화 페르소나 `[너에 대한 기록]` | ✔ 추적 | 인물의 취향·기념일·기억 |
| `project/story/chatlog.json` | 스튜디오 스토리 탭 | 스토리 탭 이어하기 | ✂ **제외** | 기획 대화 |
| `project/story/talk_<CID>.json` | 인물 대화 | 대화 이어하기 · 기억 요약 | ✂ **제외** | 인물과 나눈 대화 |
| `project/story/*.archive.jsonl` | `talk_store` 상한 이관 | (없음) — 사람이 직접 열어 보는 보관본 | ✂ **제외** | **상한을 넘겨 밀려난 옛 대화 원문** |
| `project/story/memory_<CID>.json` | `prompt_build.save_memory_summary` | 창 밖 맥락 주입(`memory_digest`) | ✂ **제외** | 압축된 장기 기억 |
| `output/` · `backups/` | 내보내기 · 백업 도구 | 사람 | ✂ 제외 | 재생성 가능 |

### 3.1 사적 데이터 — git 에서 제외되는 이유

`chatlog.json` · `talk_*.json` · `*.archive.jsonl` · `memory_*.json` 은 **인물과 나눈 사적 대화**이고
그 보관본·압축본이다. 원격 저장소에 올라가서는 안 되므로 `.gitignore` 가 넷 다 제외한다.
감상본 HTML 에도 들어가지 않는다 — 감상본에 실리는 건 제목·캐릭터 이름·대사·승인된 이미지뿐이다.
→ [PRIVACY_HOSTING.md](PRIVACY_HOSTING.md)

> **아카이브(`.jsonl`)를 빠뜨리기 쉬운 이유.** 대화 로그가 상한(`talk_store.LOG_CAP`, 1.5MB)을
> 넘으면 오래된 구간이 **삭제되지 않고** 옆 파일로 옮겨진다 —
> `talk_CHAR-001.json` → `talk_CHAR-001.archive.jsonl`, `chatlog.json` → `chatlog.archive.jsonl`.
> 내용은 원문 그대로인데 확장자가 `.json` 이 아니라서 `talk_*.json` 패턴에 걸리지 않는다.
> 제외 규칙을 손볼 때 **`.json` 과 `.jsonl` 을 함께** 본다.

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
| `billable` | **과금 대상인가** — 재수령은 `false` |
| `refetch` | 재수령(`--refetch`)일 때만 `true`. 과금 없이 이미 만든 task 를 다시 받은 줄이다 |
| `capped` · `want_px` · `cap_px` | **규격이 깎였을 때만** 붙는 세 필드 — 요청하려던 긴 변(`want_px`)이 `image_generator.max_long_edge_px`(`cap_px`)에 잘렸다는 표시 |
| `error` | 실패 사유(200자로 자름) |

> **`capped` 를 흘려보내지 마라.** 이 세 필드는 "**돈은 썼는데 규격은 못 맞췄다**"를 나중에
> 식별하는 유일한 흔적이다(§1.3 의 함정이 실제로 발생한 줄). 붙어 있으면 그 장면의 이미지는
> 인화 기준에 미달일 수 있으니, 두 상한을 올린 뒤 **다시 생성**해야 한다 — 재수령(`--refetch`)은
> 같은 작은 이미지를 다시 받을 뿐이다. `_gen_meta.json` 항목에도 같은 세 필드가 들어간다.
>
> 깎였는지 훑어보기: `python -c "[print(l) for l in open('logs/makefun_usage.jsonl',encoding='utf-8') if 'capped' in l]"`

### 3.4 `project/favorites.json`

갤러리에서 ★ 로 고른 인화 후보. **서버가 정본**이라 폰과 PC 가 같은 목록을 본다
(서버 응답이 없으면 브라우저 `localStorage` 로 폴백).

```json
{ "scene_ids": ["SCENE-003", "SCENE-007"] }
```

`print_export --only SCENE-003,SCENE-007` 로 이어진다. 형식이 깨져도 빈 목록으로 살아남고,
`SCENE-\d{3,}` 형식이 아닌 값은 걸러진다.

---

## 4. `templates/` — 어떤 파일이 무엇인가

| 파일 | 정체 | 코드가 읽는가 |
|---|---|---|
| `manifest.json` | **새 작품의 시작점.** 캐릭터·장소 기준정보의 정본 모양 | 사람이 `project/` 로 복사 |
| `scene.json` | 새 장면의 기본형 | ✔ `advance_scene new` · `vn_compose` 가 그대로 읽는다 |
| `character.json` | `manifest.characters[]` 에 **붙여넣는 항목 1개 조각** (§1.6) | ✗ |
| `review-report.json` | **SCORECARD C 사람 시사 서식** — 장면 파일에 들어가지 않는다 | ✗ |
| `grok-prompt-brief.md` | 프롬프트 지시서 원문 | ✔ `make_grok_input` |
| `grok-prompts-ko.md` | 그록 한글 프롬프트 틀 모음 (스튜디오가 요약본을 표시) | ✗ |
| `free-assets-ko.md` | 무료 폰트·BGM·효과음 소스 목록(라이선스 등급별) | ✗ |

**캐릭터는 별도 파일에 살지 않는다.** `character.json` 은 편의용 조각이고, 실제 기준정보는
전부 `project/manifest.json` 안에 있다(CLAUDE.md "단일 매니페스트"). 두 파일의 필드 모양이
어긋나면 매니페스트 쪽이 정본이다 — §1.6 이 그 표다.

`scene.json` 은 **코드가 직접 읽는 유일한 JSON 템플릿**이라 여기에 넣은 값이 그대로 새 장면에
박힌다. 선택 필드(`episode` 등)를 기본값으로 넣어 두면 그 필드가 필요 없는 작품에도 붙는다.

그래서 **"기본값처럼 보이는 값"을 여기 두지 않는다.** 실제로 두 번 겪은 형태다:

| 두면 생기는 일 | 결론 |
|---|---|
| `"print": {"crop_anchor": "center"}` | 새 장면 전부가 장면 값을 갖게 되고, 장면 값이 명령행보다 세므로 `print_export --anchor top` 이 **조용히 무시된다**(§2.8) → **`print` 블록 없음** |
| `"episode": 1` | 화를 안 쓰는 작품에도 1화가 붙는다 → 템플릿에 두지 않고 `advance_scene new` 가 직전 장면에서 승계 |
| `talk.relationship: ""`(manifest 쪽) | 빈 문자열이 기본값을 이겨 페르소나가 깨진다(§1.5) → 값을 채우거나 키를 삭제 |

`review-report.json` 은 이 세 파일과 성격이 다르다 — 사람이 시사하며 채우는 서식이고
장면 파일에 병합되지 않는다(§2.7).

---

## 5. 스키마를 바꿀 때

1. **이 문서를 먼저 고친다** — 필수/선택 · 쓰는 쪽 · 읽는 쪽 · 검사기 열까지.
2. `templates/scene.json` · `templates/manifest.json` 을 같은 모양으로 맞춘다
   (새 작품이 구스키마로 시작되지 않도록). 캐릭터 필드를 바꿨다면 `templates/character.json` 도.
3. `examples/` 도 맞춘다 — README 가 "데모로 초록불을 보라"고 안내하는 파일이고,
   `selftest` 가 이걸 복사해 검사기 PASS 를 확인한다.
4. `python tools/check_protocol.py` → **RESULT: PASS**, `python tools/selftest.py` → 전체 통과.

`protocol/SCORECARD.md` 와 `tools/check_protocol.py` 는 에이전트가 수정할 수 없다.
검사 기준 자체의 개정이 필요하면 CLAUDE.md 의 "채점표·검사기 개정 절차"를 따른다.
