# AI Webtoon Production Protocol (v5.x)

## 목적
로컬 LLM 오케스트레이터로 스토리를 씬/행동 비트/장면으로 분해하고, 이미지 생성기용 프롬프트를 만든 뒤 최종 이미지를 비주얼 노벨형 디지털 감상물과 실제 사진 출력물로 구성한다. 스토리 → 이미지 → 감상이 **내 집 안에서** 닫히는 것이 기본 구성이다(한 대여도 되고, LLM 만 같은 공유기의 다른 기기여도 된다).

## 현행 엔진 (2026-09 기준)
- **오케스트레이터 = 로컬 LLM** — llama.cpp 서버(OpenAI 호환, 기본 `http://127.0.0.1:8080/v1`). 스토리·장면 구성·이미지 프롬프트·인물 대화를 담당한다. 비용 0·사적 대화가 집 밖으로 나가지 않는다(`local_llm._validate` 가 루프백·사설망 외 주소를 거부한다).
  - **이 PC 일 필요는 없다.** 지금 이 저장소는 같은 공유기의 노트북(`http://192.168.219.182:8080/v1`)을 본다. 주소가 적히는 곳은 `project/manifest.json` 의 `talk.base_url` · `orchestrator.api.base_url` **두 줄**뿐이고, 환경변수 `LOCAL_LLM_URL` 이 그 둘을 덮는다(IP 가 DHCP 로 바뀔 때 고치는 자리도 여기다).
  - 서버가 `--api-key` 로 떠 있으면 키가 필요하다 — `orchestrator.api.api_key`(또는 `key_env` 가 가리키는 환경변수, 또는 `LOCAL_LLM_KEY`). **`/v1/models` 는 키 없이 열려 있어서** 키가 틀리면 상태는 "연결됨" 인데 네 기능만 401 로 죽는다. 그래서 `local_llm.status()` 가 키까지 따로 확인하고 `reason: unreachable|auth|ok` 로 갈라 준다.
  - `LOCAL_LLM_HOME` 은 **이 PC 에 서버를 띄울 때만** 쓰는 설치 폴더(`runtime\serve.ps1`)다. 원격 주소면 `start_studio.ps1` 은 아무것도 띄우지 않고 응답만 확인한다.
  - **장면 구성은 느리고, 모델은 출력 형식을 자주 어긴다**(Qwen3.6-35B-A3B 실측 · 출력 12~14 tok/s). 장면 1개당 ~30초라 3개가 95~115초, 12개는 7분이 넘는다 — 그래서 `orch_chat` 은 **스트리밍**으로 받는다(`TIMEOUT` 120초는 소켓 하나의 상한이지 총 시간이 아니고, 비스트리밍이면 그것이 총 상한이 되어 기본값 10개는 언제나 시간초과였다). 같은 지시문 7회 중 진짜 JSON 배열은 3회뿐이었고(`{"scenes":[…]}` 포장 2 · 객체 나열 2) 요청 개수를 안 맞추는 경우도 있다 — `_extract_json_array` 가 세 모양을 모두 받고, 개수가 다르면 `compose_scenes` 가 한 번 더 물은 뒤 **디스크를 건드리기 전에** 멈춘다. 자세한 건 docs/SCHEMA.md §1.2.
- **이미지 생성 = ComfyUI(로컬, 기본)** — `tools/comfyui_client.py`. 매니페스트 `image_generator.engine: "comfyui"`, 주소는 `comfyui.api.base_url`(환경변수 `COMFYUI_URL` 이 우선, 기본 `http://127.0.0.1:8188`). 무료·토큰 없음. 엔진 위의 공통 진입점은 `tools/image_gen.py`(웹·doctor 는 이것만 부른다).
- **MakeFun AI 는 보조(유료 종량제)** — `tools/makefun_client.py`, 토큰은 `MAKEFUN_API_TOKEN` 환경변수. `engine: "makefun"` 이거나 스튜디오의 [MakeFun 생성(유료)] 보조 버튼을 눌렀을 때만 쓰이고, 업스케일·크레딧 조회는 MakeFun 전용이다.
- **로컬 LLM 이 꺼져 있을 때의 경로 = 직접 입력(붙여넣기)** — `tools/scene_brief.py`(장면 브리프) 또는 스튜디오의 [✍ 직접 입력]. 브리프 조립에는 모델이 필요 없으므로 **LLM 이 죽어 있어도 이 경로는 산다**. 어디서(직접 작성·다른 AI·폰) 받아 왔든 붙여넣으면 앵커 자동 보정까지 같은 관문(`scene_ops.set_prompt`)을 지난다. 원격 오케스트레이터 API 경로는 없다.

## 기본 흐름
1. Story
2. Scene decomposition
3. Motion/action beats
4. Camera/composition design
5. Image prompt package (로컬 LLM 생성 · 직접 입력 붙여넣기 가능)
6. External image generation
7. Consistency review
8. Dialogue / balloon composition
9. Visual-novel scene package
10. Print-ready export

## 데이터 원칙 (v2 스키마 규약)
- 단일 매니페스트: `project/manifest.json` 하나에 프로젝트 설정과 캐릭터/장소/소품 기준정보를 모두 둔다.
- 장면은 `project/scenes/<scene_id>.json` 파일 1개씩. 파일명과 `scene_id` 는 반드시 일치.
- ID 필드명은 전 파일에서 통일한다: `scene_id` / `character_id` / `location_id` / `prop_id`, 대사 화자는 `speaker_id`(character_id 를 참조).
- `scene_order` 는 1부터 연속하는 정수.
- 이미지 파일, 프롬프트, 대사, 검수 결과가 scene_id 로 추적 가능해야 한다.
- 이미지 안에 대사를 직접 생성하는 것을 기본 경로로 사용하지 않는다.
- **장면 파일의 `status`·`review`·`assets`·`scene_id`·`scene_order` 는 도구(`scene_ops`/`advance_scene`)만 쓴다.** 상태 전이·승인 잠금·과금 복구 기록(`makefun_tasks`)이 걸려 있어 손편집하면 불변식이 깨진다. 반대로 장면 계획·대사·분기 필드(`purpose`·`action_beat`·`emotion`·`time`·`camera`·`dialogue`·`characters`·`location_id`·`episode`·`choices`·`branch`·`ending`·`ending_label`·`print`)는 **스튜디오 장면 편집(`POST /api/set-scene`) 또는 직접 편집이 정식 경로**다.
- **필드 단위 규약의 단일 출처는 [docs/SCHEMA.md](docs/SCHEMA.md)** 다. 필수/선택·누가 쓰고 누가 읽는지·검사기가 보는지를 그 표에 적고, `templates/` 는 그 표와 같은 모양을 유지한다. 스키마를 바꿀 때는 SCHEMA.md 를 먼저 고친다.

## 아키텍처 원칙
- LLM 은 연출/분석/프롬프트 생성 계층이다. 실제 이미지 생성은 이미지 생성기(기본: 로컬 ComfyUI)가 한다.
- **오케스트레이터는 로컬 LLM 이다.** 창작 텍스트와 인물 대화는 사적 자료이므로 로컬에서만 처리한다. 밖으로 나가는 선택지는 유료 보조 이미지 엔진 하나뿐이고 그것도 사람이 그때 눌러야 한다. `--lan` 으로 열어도 토큰은 서버에만 남는다.
- 표준 UI 는 로컬 웹 스튜디오(webapp.py): 기본 127.0.0.1 전용 바인딩(`--lan` 시 LAN Host 만 추가 허용), 토큰은 서버 환경변수에서만 사용하고 브라우저로 전달하지 않는다. CLI 도구는 동일 파일을 쓰는 대안 경로다.
- 오케스트레이터는 **로컬 LLM 하나뿐이다**(원격 API 경로 없음). 대신 **직접 입력 경로를 항상 유지한다** — 공급자를 이름으로 지목하지 않고, 사람이 어디서 받아 왔든(직접 작성·다른 AI·폰) 붙여넣을 수 있어야 한다. 이것이 LLM 이 꺼진 날의 유일한 작성 경로이므로 기능 정리 때 먼저 지워지지 않게 한다.
- 이미지 공급자는 교체 가능해야 한다. 공급자 정보는 매니페스트 `image_generator` 에만 두고 코드에 하드코딩하지 않는다.
- 디지털 감상과 실물 출력은 같은 장면 원본에서 파생한다.
- 사람이 승인하는 핵심 게이트(SCORECARD C)를 자동 검사(A1~A8)와 분리한다.

## 금지
- 사용자 승인 전 제품 기능 구현 금지.
- **API 키·토큰을 저장소의 어떤 파일에도 기록 금지** (.env 포함). 오케스트레이터는 로컬이라 키가 없고, 지금 남은 비밀값은 보조 이미지 엔진 토큰 하나뿐이다(아래 줄).
- **MakeFun 토큰(`MAKEFUN_API_TOKEN`)도 환경변수 전용.** 저장소의 어떤 파일(매니페스트·문서·스크립트·주석·테스트·로그)에도 값을 기록 금지. 매니페스트에는 값이 아니라 변수 이름(`token_env`)만 적는다. 콘솔·오류 메시지·커밋 메시지에도 값을 출력하지 않는다. 영구 등록은 `setx` 로 사용자 환경에만 (`docs/ENV_SETUP.md`).
- **사용자의 명시적 허가 없이 이미지 생성 API 호출 금지.** MakeFun 은 유료 종량제라 호출 1회가 곧 과금이다. `tools/makefun_client.py` 실행, `/api/gen-image` 호출, 그 외 어떤 경로로도 에이전트가 스스로 이미지를 생성하지 않는다. 코드 작성·모의(mock) 서버 테스트까지만 하고, 실호출 검증은 사용자가 그 시점에 허가한 만큼만 한다. 로컬 ComfyUI(무료)는 이 금지의 대상이 아니다 — 켜져 있으면 실호출로 검증해도 된다.
- **서드파티 CLI/에이전트 도구에 어떤 키도 제공 금지.** 근거: 2026-07 Grok Build CLI 가 .env 의 키를 평문으로 외부 서버에 전송한 사고. 공급자가 바뀌어도 조항은 남는다 — MakeFun 토큰도 동일하게 취급한다.
- **비공식 OAuth 우회 표면 사용 금지.** 근거: SuperGrok OAuth 우회는 정상 구독자에게도 403 이 보고됐다. 정식 발급 경로가 아닌 인증 표면은 쓰지 않는다.
- 채점표/검사기를 수정해 PASS를 만드는 행위 금지.
- git push, destructive delete, 임의 시스템 변경 금지.
- Scene/Character/Location ID 임의 재사용 금지.

## 채점표·검사기 개정 절차 (교착 방지)
`protocol/SCORECARD.md` 와 `tools/check_protocol.py` 는 에이전트가 수정할 수 없다(.claude/settings.json deny).
정당한 개정이 필요한 경우:
1. 에이전트는 변경 제안(무엇을·왜)을 사용자에게 보고만 한다.
2. 사용자가 직접 수정하거나, 사용자가 해당 deny 항목을 임시 해제한 뒤 에이전트에게 지시한다.
3. 개정 후 SCORECARD의 "개정 이력"에 버전과 사유를 기록하고 deny 를 복구한다.

## 회귀 확인 관례
도구·스키마를 수정한 뒤에는 `python tools/selftest.py` 전체 통과를 확인한 후에만 완료로 간주한다.
- 비밀값 점검: `python tools/secret_scan.py` (검사기 A8 의 `xai-` 단일 패턴을 보완 — MakeFun `sk_`·Bearer·JWT 등. 실제 값은 출력하지 않고 마스킹한다. A8 은 **유출 탐지기**라 공급자 은퇴와 무관하게 남는다 — 유출된 키는 공급자를 안 쓴다고 무해해지지 않는다.)
- 환경 점검: `python tools/doctor.py` (파이썬·Pillow·환경변수 설정 여부·로컬 LLM 응답·디스크·프로젝트 구조. 읽기 전용.)

## 완료의 의미
작업은 기능 구현 자체가 아니라 승인된 SCORECARD 항목을 만족할 때 완료된 것으로 본다.
같은 지점에서 3회 연속 실패하면 중단하고 시도/가설/막힘을 보고한다.
