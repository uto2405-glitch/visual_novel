# AI Webtoon Production Protocol (v4)

## 목적
LLM 오케스트레이터로 스토리를 씬/행동 비트/장면으로 분해하고, 외부 상용 이미지 AI용 프롬프트를 생성한 뒤 최종 이미지를 비주얼 노벨형 디지털 감상물과 실제 사진 출력물로 구성한다.

## 현행 엔진 (2026-08 기준)
- **오케스트레이터 = 로컬 LLM** — `c:\Users\USER\claude\local_llm` 의 llama.cpp 서버(OpenAI 호환, 기본 `http://127.0.0.1:8080/v1`). 스토리·장면 구성·이미지 프롬프트·인물 대화를 담당한다. 로컬이므로 키 불필요·비용 0·사적 대화가 외부로 나가지 않는다.
- **이미지 생성 = MakeFun AI** (`tools/makefun_client.py`, 토큰은 `MAKEFUN_API_TOKEN` 환경변수). **유료 종량제**다.
- **그록(xAI)은 예비 경로** — 수동 복붙(`make_grok_input.py`) 또는 API(`tools/grok_api.py`, `XAI_API_KEY`). 매니페스트 `orchestrator` 만 바꾸면 전환된다.

## 기본 흐름
1. Story
2. Scene decomposition
3. Motion/action beats
4. Camera/composition design
5. Image prompt package (로컬 LLM 생성 · 그록 수동 복붙 가능)
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
- LLM 은 연출/분석/프롬프트 생성 계층이다. 실제 이미지 생성은 외부 상용 AI를 사용한다.
- **오케스트레이터는 로컬 LLM 을 기본으로 한다.** 창작 텍스트와 인물 대화는 사적 자료이므로 로컬 처리를 우선하고, 외부 API 는 선택지로만 둔다. `--lan` 으로 열어도 키·토큰은 서버에만 남는다.
- 표준 UI 는 로컬 웹 스튜디오(webapp.py): 기본 127.0.0.1 전용 바인딩(`--lan` 시 LAN Host 만 추가 허용), API 키는 서버 환경변수에서만 사용하고 브라우저로 전달하지 않는다. CLI 도구는 동일 파일을 쓰는 대안 경로다.
- Grok 연동은 이중 모드: **수동 모드**(SuperGrok 구독, grok.com 복붙, 비용 0)와 **API 모드**(console.x.ai 키 발급 후 `tools/grok_api.py`) — 구독과 API 는 별도 결제 트랙이다.
- 이미지 공급자는 교체 가능해야 한다. 공급자 정보는 매니페스트 `image_generator` 에만 두고 코드에 하드코딩하지 않는다.
- 디지털 감상과 실물 출력은 같은 장면 원본에서 파생한다.
- 사람이 승인하는 핵심 게이트(SCORECARD C)를 자동 검사(A1~A8)와 분리한다.

## 금지
- 사용자 승인 전 제품 기능 구현 금지.
- **API 키를 저장소의 어떤 파일에도 기록 금지** (.env 포함). 키는 환경변수 `XAI_API_KEY` 로만 주입한다.
- **MakeFun 토큰(`MAKEFUN_API_TOKEN`)도 환경변수 전용.** 저장소의 어떤 파일(매니페스트·문서·스크립트·주석·테스트·로그)에도 값을 기록 금지. 매니페스트에는 값이 아니라 변수 이름(`token_env`)만 적는다. 콘솔·오류 메시지·커밋 메시지에도 값을 출력하지 않는다. 영구 등록은 `setx` 로 사용자 환경에만 (`docs/ENV_SETUP.md`).
- **사용자의 명시적 허가 없이 이미지 생성 API 호출 금지.** MakeFun 은 유료 종량제라 호출 1회가 곧 과금이다. `tools/makefun_client.py` 실행, `/api/gen-image` 호출, 그 외 어떤 경로로도 에이전트가 스스로 이미지를 생성하지 않는다. 코드 작성·모의(mock) 서버 테스트까지만 하고, 실호출 검증은 사용자가 그 시점에 허가한 만큼만 한다.
- **서드파티 CLI/에이전트 도구에 xAI 키 제공 금지.** 근거: 2026-07 Grok Build CLI 가 .env 의 키를 평문으로 xAI 서버에 전송한 사고. MakeFun 토큰도 동일하게 취급한다.
- **SuperGrok OAuth 우회 경로 사용 금지.** 정상 구독자도 403 거부가 보고되는 비공식 표면이다. 수동 모드 또는 console.x.ai 정식 API 키만 사용한다.
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
- 비밀값 점검: `python tools/secret_scan.py` (검사기 A8 의 xai- 단일 패턴을 보완 — MakeFun `sk_`·Bearer·JWT 등. 실제 값은 출력하지 않고 마스킹한다.)
- 환경 점검: `python tools/doctor.py` (파이썬·Pillow·환경변수 설정 여부·로컬 LLM 응답·디스크·프로젝트 구조. 읽기 전용.)

## 완료의 의미
작업은 기능 구현 자체가 아니라 승인된 SCORECARD 항목을 만족할 때 완료된 것으로 본다.
같은 지점에서 3회 연속 실패하면 중단하고 시도/가설/막힘을 보고한다.
