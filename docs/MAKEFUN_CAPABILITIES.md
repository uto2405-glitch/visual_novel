# MakeFun 능력 지도 — 쓰는 것 · 붙일 수 있는 것 · 못 쓰는 것

> **현황(2026-09):** 기본 이미지 엔진은 로컬 **ComfyUI**(무료, `tools/comfyui_client.py`)다. MakeFun 은 `image_generator.engine: "makefun"` 또는 스튜디오의 [MakeFun 생성(유료)] 보조 버튼으로만 생성에 쓰이고, **업스케일·크레딧 조회는 여전히 MakeFun 전용**이다(→ [SCHEMA.md](SCHEMA.md) §1.3).

이미지 공급자(MakeFun AI)가 제공하는 API 중 **이 저장소가 무엇을 쓰고, 무엇을 일부러 안 붙였고,
왜 그랬는지**를 남긴 문서다. 목적은 하나 — **다음에 같은 조사를 반복하지 않는 것.**
"이 기능 붙일 수 있나?" 라는 질문이 나오면 여기부터 본다.

기준: 공급자 OpenAPI 명세에서 직접 확인(2026-08). 접속 설정은
`project/manifest.json` 의 `image_generator.makefun` 한 블록이 전부다(→ [SCHEMA.md](SCHEMA.md) §1.3).

---

## 1. 지금 쓰는 것

| 기능 | 엔드포인트 | 우리 쪽 진입점 | 비용 |
|---|---|---|---|
| **텍스트 → 이미지** | `POST /api/v1/userText2Image/start` → `GET /api/v1/userText2Image/{id}` (폴링) | `python tools/makefun_client.py SCENE-001 --n 2` · 스튜디오 [🎨 이미지 생성] | **유료** |
| **레퍼런스 첨부** (얼굴 일관성) | 같은 요청의 `input_images` (A2E 최대 2장 · Seedream 5.0 Pro 10장) | 자동 — 매니페스트 `characters[].reference_images` (`--no-reference` 로 끔) | 생성비에 포함 |
| **업스케일** (재생성 없이 확대) | `POST /api/v1/userUpscale/start` → `GET /api/v1/userUpscale/{id}` (실패 시 `…/allRecords`) | `--upscale SCENE-001` · 스튜디오 장면 카드(`POST /api/upscale`) | **유료** |
| **R2 업로드** (로컬 파일 → 공개 URL) | `POST /api/v1/r2/get_upload_presigned_url` → 받은 URL 에 **HTTP PUT** | `--upload <파일>` · 위 두 기능이 내부적으로 사용 | 무료(스토리지) |
| **크레딧 이력 조회** | `GET /api/v1/transactionRecord/creditsHistory` | `--credits` · 스튜디오(`POST /api/credits`) | 무과금(토큰은 씀) |

업로드가 목록에 있는 이유는 그것 자체가 목적이어서가 아니다. **업스케일도 레퍼런스도 URL 만
받기 때문에**, 로컬 파일을 쓰려면 먼저 공개 주소가 있어야 한다. 이 전제가 없던 동안
`reference_images` 는 사실상 쓸 수 없는 필드였다.

세부 규약 세 가지 (다시 안 밟으려고 적어 둔다):

- **presigned PUT 에는 `Authorization` 헤더를 붙이지 않는다.** 붙이면 서명이 깨져 거부된다.
  그래서 업로드 전용 opener 를 따로 두고 토큰을 어떤 경로로도 싣지 않는다.
- **업스케일에는 배율 파라미터가 없다.** 보내는 것은 `source_url`(+선택적 `name`)뿐이고,
  결과 크기는 받아 본 파일을 직접 재서 알려 준다(→ [PRINT_ORDER_GUIDE.md](PRINT_ORDER_GUIDE.md) §1).
- **크레딧 응답 스키마는 공개돼 있지 않다.** 잔액 필드가 있다는 보장이 없어 도구는
  **잔액을 단정하지 않는다** — 보이는 값을 필드명째로 인용만 하고, 실제 잔액은 계정 화면으로 넘긴다.

---

## 2. 있지만 아직 안 붙인 것 — 왜 안 붙였나

| 기능 | 엔드포인트 | 안 붙인 이유 | 붙이려면 먼저 필요한 것 |
|---|---|---|---|
| **의상 교체** | `virtualTryOn` | 사람 사진 + **옷 사진** 2장의 URL 이 필요한데, 이 저장소에는 "옷 이미지"라는 자산 개념이 없다. 의상은 텍스트 앵커(`wardrobe_variants`)로 다루고 그것조차 장면에 연결되지 않은 상태다 | 옷 이미지 자산 + 장면에서 배리에이션을 가리키는 규약(→ [SCHEMA.md](SCHEMA.md) §1.6) |
| **이미지 편집** | `userImageEdit` (`edit_type` 은 `clothing` 또는 `product`, 이미지 2장 이상) | 편집 종류가 **의상·제품 둘뿐**이다. 승인 직전 컷에서 고치고 싶은 건 대개 표정·손·구도·배경이라 대상이 어긋난다 | 편집 종류가 늘어나거나, 의상 교체를 실제로 쓰기로 결정할 때 |
| **말하는 사진** | `talkingPhoto` (`image_url` + `prompt` + `negative_prompt`) | 산출물이 **동영상**이다. 감상본은 정지 컷 + 말풍선 구조이고 목적의 절반이 **인화**라 결과가 들어갈 자리가 없다 | 영상 산출물을 감상본·내보내기에 넣겠다는 결정 |
| **대체 이미지 모델 7종** | Flux2 · GptImage · NanoBanana · Qwen · Kling · Wan26 · Wan27 | 모델마다 **별도 start 경로 = 별도 파라미터·응답**이다. 지금은 `image_generator.model` 한 값으로 크기·레퍼런스 상한 규칙이 정해지는데, 경로를 늘리면 그 규칙이 모델 수만큼 갈라진다 | 화풍 비교가 실제로 필요해질 때. 모델별 상한(픽셀·레퍼런스 장수) 표를 먼저 만든다 |
| **음성 학습** | `userVoice` | TTS 경로는 **있다**(`/api/v1/video/send_tts` · §3 정정). 보류 이유는 이제 감상본이 정지 컷 구조라는 것뿐이다 | 감상본에 소리를 넣겠다는 결정 |

공통 판단 기준: **감상본(정지 컷 + 대사)과 인화, 이 두 산출물에 닿지 않는 기능은 붙이지 않는다.**
유료 경로가 늘어날수록 중복 과금·조용한 실패를 막는 관문도 같이 늘어나야 한다.

---

## 3. 명세를 다시 읽고 고친 것 (2026-09 정정)

이 절은 원래 "스펙에 생성 경로가 아예 없는 것" 이었다. **그 서술이 틀렸다.**
경로를 `…/start` 로만 찾다가 이름이 다른 것들을 통째로 놓쳤다.

> 출처: 노트북 보존본 `scratch/makefun_spec.json` — **A2E Developer API v1.0.0**
> (openapi 3.0.0), paths 206, 2026-08 수집본. 아래 인용은 그 파일의 원문이다.
> 이 저장소는 실호출을 하지 않으므로(유료), **응답 쪽은 여전히 확인되지 않았다**.

**TTS(대사 음성 합성) — 경로가 있다.** `POST /api/v1/video/send_tts`.
`tts_id` 또는 `user_voice_id` 중 하나가 필수이고, API 사용자 상한은 1000자,
`speechRate` 는 0.5~2.0 이다. 이름이 `…/start` 가 아니라서 예전 검색에서 빠졌다.
따라서 `userVoice`(음성 학습)도 "재생할 자리가 없다" 는 이유로는 더 이상 보류가 아니다 —
보류 이유는 이제 **감상본이 정지 컷 구조라는 것 하나뿐**이다.

**영상 — `start` 경로만 12개다.** `talkingPhoto` 하나가 아니었다.

| 경로 | 비고 |
|---|---|
| `/api/v1/userImage2Video/start` | **컷 한 장 → 움직이는 컷.** 이 프로젝트에 가장 가까운 것 |
| `/api/v1/soraVideo/start` · `/veoVideo/start` · `/klingVideo/start` | 외부 모델 계열 |
| `/api/v1/grokVideo/start` · `/hailuoVideo/start` · `/minimaxH3Video/start` | |
| `/api/v1/seedanceVideo/start` · `/seedance2Video/start` | |
| `/api/v1/userHappyhorseVideo/start` | T2V/I2V/R2V/Video-Edit |
| `/api/v1/talkingPhoto/start` · `/talkingVideo/start` | 말하는 사진·영상 |

각 경로에 `/allRecords` · `/batchDetail` · `/{_id}` 가 붙는 같은 모양이라 폴링은
지금 쓰는 것과 동일하다. `userKlingImage` · `userWan26Image` 는 **이미지** 경로이고
영상은 `klingVideo` 로 따로 있다 — 이름이 비슷해 헷갈리기 쉽다.

`/api/v1/userImage2Video/start` 의 요청 쪽은 명세로 확정된다:

* `image_url` (필수) · `prompt` · `negative_prompt`
* `model_type` `[GENERAL|FLF2V]` · `end_image_url` (FLF2V 에서 필수)
* `video_time` — *"Video time in seconds (5, 10, 15, or 20 seconds)"* · min 5 · max 20 · **기본 5**
* `number_of_images` — min 1 · max 8 · 기본 1
* `skip_face_enhance` — 기본 **false**(= 얼굴 유사도 보정 켬)
* `model_version` `[a2e|a2e-v2|a2e-v2-flash]` — **과금과 직결된다.** 원문:
  *"Ultra users default to a2e-v2 and other roles default to a2e. a2e-v2 costs more per
  second; a2e-v2-flash uses a2e pricing."* → 값을 안 보내면 **계정 등급에 따라 단가가
  달라진다.** 비용을 예측 가능하게 하려면 명시해서 보낸다.
* `video_length` 는 Deprecated(프레임 단위) — 쓰지 않는다.
* `webhook_url` / `webhook_token` · `mask_face` · `minor_suspected_skip`

**응답 쪽은 명세에 비어 있다.** `start` 200 은 `{"type":"object"}` · example `{}`,
`GET /{_id}` 200 도 같다. 즉 **작업 id 가 어느 필드인지, mp4 URL 이 어느 필드인지
명세로는 알 수 없다.** 업스케일·크레딧과 같은 상황이므로 같은 방식으로 간다:
관용 파서(`_ID_FIELDS` · `_urls_in`)로 찾고, **모르는 형태면 조용히 실패하지 않고
응답 일부를 담아 던진다**(§4). `avgProcessingTime` 도 알맹이가 비어 있어
"약 N초" 를 띄우려면 실측이 필요하다.

**견적 — `POST /api/v1/generation/quote` (무과금).** 원문:
*"Returns a credit estimate without creating a task, calling a generation provider, or
charging credits."* 요청은 `endpoint`(경로 문자열, 앞의 `POST ` 는 선택) +
`requestBody`(**그 생성 요청에 보낼 바로 그 JSON**). 응답 스키마는 비어 있지만
200 설명에 이름 하나가 확정돼 있다: `generationRequestValidated=false` 는
**가격 입력만 확인했다**는 뜻이다. 명세가 직접 *"Do not infer undocumented fields"* 라고
적었으므로, 이 저장소는 숫자를 **필드명째** 인용만 한다(`quote_numbers`).

**NSFW 안전장치 — `force_generate`.** 다섯 경로가 이 파라미터를 받는다:
`userFlux2` · `userNanoBanana` · `userGptImage` · `userWan26Image` · `userWan27Image`.
앞의 둘은 원문이 이렇다: *"Force generation even if NSFW content is detected.
**Defaults to true for API users**, false for web users"*. 우리는 API 토큰 사용자다 —
**값을 안 보내면 그쪽 안전장치가 꺼진 채로 돈다.** 이 프로젝트는 `input_images` 로
실존 인물의 얼굴 사진을 싣기 때문에 그 조합은 사고가 나면 되돌릴 수 없다.
그래서 `makefun_client._call` 이 저 다섯 경로로 나가는 요청에 `force_generate: false` 를
**자동으로 채운다**(`NSFW_FORCE_PATHS` · `with_safety`). 규칙이 아니라 구조로 둔 이유는,
규칙은 새 경로를 붙이는 사람이 한 번 잊는 것으로 무력해지기 때문이다.
지금 이 저장소가 부르는 `userText2Image/start` 에는 이 파라미터가 **없다**(명세 확인) —
즉 지금까지 안전장치가 꺼진 채로 돈 적은 없다.

### 크레딧을 **재는** 방법 (실측 단가)

장당 몇 크레딧인지는 공급자가 공개하지 않는다. 그래서 묻는 대신 **잰다.**
`GET /api/v1/transactionRecord/creditsHistory` 의 쿼리 파라미터가 명세로 확정된다:

* `pageNum`(기본 1) · `pageSize`(기본 10)
* `is_consumption` — *"When true, only returns consumption records"*
* `startDate` / `endDate` — ISO date-time, `createdAt` 기준, **양끝 포함**

그리고 부호 규약이 명세에 있다 — 이건 응답 스키마가 비어 있어도 확정이다:

> *"Positive amounts are credit grants or purchases; negative amounts are credit consumption."*

절차(`makefun_client.record_spend`):

1. 굽기 **직전** 시각 T 를 UTC 로 적어 둔다(`now_iso`).
2. 생성을 호출한다.
3. `?is_consumption=true&pageSize=5&startDate=T` 로 그 뒤의 소비만 읽는다.
4. **음수만** 더해서 대장(`logs/makefun_usage.jsonl`)에 `kind:"spend"` 한 줄로 남긴다.

UTC 로 보내는 이유는 공급자 시각대를 모르기 때문이다 — 로컬 시각을 보내면 시차만큼
남의 기록이 섞이거나 내 기록이 빠진다.

**페이지를 한 장만 읽으면 안 된다.** 한 번의 생성이 여러 줄을 만든다(장수 최대 8 ·
업스케일이 같은 창에 끼기도 한다). 기록이 6줄인데 5줄만 세면 평균 단가가 **실제보다
싸게** 나오고, 그건 화면이 사람에게 '덜 든다' 고 말하는 쪽의 오류라 더 나쁘다.
그래서 받은 줄 수가 요청한 크기와 같으면 다음 장이 있다고 보고 이어 읽는다
(`SPEND_PAGE` 50 · `SPEND_MAX_PAGES` 5 에서 끊는다).

**과금은 보통 제출이 아니라 완료 시점에 확정된다.** 끝나자마자 재면 아직 줄이 안
올라와 있을 수 있어서, 빈손이면 몇 초 뒤 한 번만 더 본다(`SPEND_RETRY_SEC`).
그래도 없으면 '못 쟀음' 이다 — '0 크레딧을 썼다' 가 아니다.

**충분히 쌓이면 그만 잰다**(`SPEND_SAMPLE_CAP` 10). 이 조회도 무과금이지만 실호출이라,
생성마다 계속 재면 덤이 세금이 된다.

**못 쟀으면 대장에 남기지 않는다.** 빈 줄은 나중에 읽는 사람에게 "0 크레딧이 나갔다"
로 보이는데 그건 잰 것이 아니라 못 잰 것이다. 그 둘을 같은 모양으로 적으면 실측이
오염된다. 조회가 실패해도 예외를 위로 올리지 않는다 — 재는 일은 덤이고, 여기서
던지면 이미 성공한 생성이 실패로 뒤집힌다.

두세 번 쌓이면 화면이 "지난 N번 실측: 평균 X 크레딧" 을 보여 준다(`measured_spend`).
**실패도 과금되는가** 역시 이 기록으로만 답이 나온다 — 실패한 작업 뒤에 소비 기록이
생기는지 보면 된다.

### 음성(TTS) — 경로와 필드는 확인했고, 아직 안 붙였다

`POST /api/v1/video/send_tts`. 스키마상 required 는 `msg` 하나지만, 설명이
*"Must provide either `tts_id` (system voice) or `user_voice_id` (custom cloned voice)"*
를 요구한다 — **스키마 검증에 안 걸리고 서버가 400 을 준다.** 붙이면 클라이언트에서 먼저 막아야 한다.

* `msg` — 스키마 maxLength 는 3000 이지만 설명이 *"API users: Maximum 1000 characters"* 다.
  **우리는 API 사용자라 1000 이 실제 상한**이다(유니코드 전부 셈).
* `tts_id`(시스템 음성 · 400+종) 또는 `user_voice_id`(학습한 목소리 · country/region 필요)
* `country`(기본 en) / `region`(기본 US) → 'en-US' 같은 로케일. 값의 출처는
  `POST /api/v1/anchor/language_list`
* `speechRate` — 기본 1 · 0.5~2.0
* 캡차 관련 필드(`type` · `turnstile_token` · `captchaVerifyParam`)는
  *"For non-API users"* 라 **토큰 사용자는 안 보내도 된다.**

응답은 또 비어 있다 — 오디오 URL 필드명은 실호출로만 안다. 한국어 음성이 있는지도
명세로는 모른다(`anchor/tts_list` · `anchor/language_list` 를 찍어 봐야 한다).
붙이지 않은 이유는 기술이 아니라 **감상본이 정지 컷 구조**라는 것 하나다.

---

## 4. 새 경로를 붙일 때의 관례

유료 API 를 하나 붙인다는 것은 기능 하나가 아니라 **안전장치 한 벌**을 붙이는 일이다.
지금 있는 두 유료 경로(생성·업스케일)가 공통으로 지키는 것:

1. **중복 방지 관문을 탄다** — 같은 장면을 두 번 굽지 못하게 `gen_jobs` 의 잠금을 통과한다.
   웹과 CLI 가 다른 프로세스라도 막힌다(→ [SCHEMA.md](SCHEMA.md) §3.5).
2. **대장에 남긴다** — `logs/makefun_usage.jsonl` 에 `kind`·`billable` 로 한 줄
   (→ [SCHEMA.md](SCHEMA.md) §3.3).
3. **조용히 실패하지 않는다** — 응답 형태를 모르겠으면 응답 일부를 담아 오류로 던진다.
   시작된 뒤 실패했다면 **작업 id 와 결과 URL 을 남겨** 재결제 없이 회수할 수 있게 한다.
4. **사람 승인 상태를 건드리지 않는다** — 도구는 후보를 만들 뿐, 고르는 것은 사람이다.
5. 새 `tools/*.py` 를 만들었다면 `selftest` 의 모듈·계층 목록에 등록한다.

그리고 실호출은 **사용자가 건별로 허가할 때만** 한다. 이 저장소의 API 는 전부 종량제다.
