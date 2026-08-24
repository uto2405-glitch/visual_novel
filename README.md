# AI Webtoon Protocol (v5.1 — 웹 스튜디오)

Grok AI를 오케스트레이터로 사용하여 스토리부터 씬 설계, 외부 이미지 AI용 프롬프트, 검수, 비주얼 노벨형 감상본, 실제 사진 출력용 이미지까지 관리하는 반복 제작 프로토콜.

## 확정 워크플로우 (v5)
| 단계 | 하는 일 | 어디서 | 담당 |
|---|---|---|---|
| 1 | 스토리라인 작성 | 웹페이지 [스토리] 탭 — Grok 과 대화 | 나 + Grok(API) |
| 2 | VN 텍스트 + 이미지 프롬프트 구성 | [장면] 탭 — [스토리라인 → 장면 구성] 버튼 | Grok(API) |
| 3 | 이미지 생성 | 외부 이미지 AI (수동, 레퍼런스 첨부) | 나 + 그림 AI |
| 4 | 이미지 폴더 투입 | `images/raw/장면ID/` 에 넣고 [폴더 스캔]→선택→승인 도장 | 나 + 검사기 |
| 5 | 감상 | [뷰어] 탭 — 비주얼 노벨 재생 | 나 |

## 웹 스튜디오 시작
```bash
# 키 설정 (console.x.ai 발급 — SuperGrok 구독과 별개)
#   Windows cmd: set XAI_API_KEY=발급키   /  PowerShell: $env:XAI_API_KEY="발급키"
# 모델명 기입: project/manifest.json → orchestrator.api.model (docs.x.ai 참고)
python tools/webapp.py        # 브라우저 자동 오픈 (127.0.0.1 전용)
```
키는 서버 환경변수에서만 쓰이고 **브라우저로는 절대 전달되지 않는다.** 키 없이 실행하면 뷰어·검사 탭은 그대로 쓸 수 있다. 요구사항: Python 3.9+.

## 권장 흐름 (내부 상태)
`BRIEF → STORY → CAST → SCENE_PLAN → PROMPT(Grok) → IMAGE(외부 AI) → REVIEW_AUTO → REVIEW_HUMAN → APPROVED → DELIVER`

## 역할 분리
- **Grok AI:** 스토리 분석, 연출 설계, 이미지 생성 프롬프트 제작
- **외부 상용 이미지 AI:** 실제 이미지 생성
- **후처리/편집 도구:** 대사, 말풍선, 장면 배열, 인쇄용 출력
- **자동 검사기:** `tools/check_protocol.py` — SCORECARD A1~A7 자동 판정
- **자동화 도구:** `webapp.py`(서버)+`studio.html`(화면) / `vn_compose.py`(장면 구성, 웹·CLI 공용) / `xai_client.py`(단일 API 경로) / `advance_scene.py` / `make_grok_input.py` / `selftest.py`(23종 자가진단)
- **사람:** 최종 미적 판단 및 승인 (SCORECARD C 항목)

## 디렉터리 구조
```
project/manifest.json        프로젝트 설정 + 캐릭터/장소/소품 기준정보 (단일 매니페스트)
project/scenes/SCENE-XXX.json  장면 파일 1개 = Scene 1개 (파일명 = scene_id)
images/raw/<scene_id>/       외부 AI가 생성한 후보 이미지 보관
templates/                   위 파일들의 빈 템플릿
examples/                    복사만 하면 검사기 PASS 가 나오는 데모
```

## 첫 실행 (5분 안에 초록불 보기)
```bash
# 0) 자가진단 — 파이프라인 전체(13개 시나리오)가 이 PC에서 도는지 확인
python tools/selftest.py

# 1) 데모로 검사기가 도는지 먼저 확인
cp examples/manifest.json project/manifest.json
cp examples/scenes/SCENE-001.json project/scenes/
python tools/check_protocol.py        # → RESULT: PASS

# 2) 내 작품 시작: 데모를 지우고 템플릿으로 교체
cp templates/manifest.json project/manifest.json
# project/manifest.json 에 제목·캐릭터·장소 기준정보 채우기 (prompt_anchor 필수)
# templates/scene.json 을 project/scenes/SCENE-001.json 으로 복사해 장면 작성
python tools/check_protocol.py
```
Windows(cmd)는 `cp` 대신 `copy`, 경로 구분자는 `\` 를 사용하면 된다.

## 장면 상태 값
`SCENE_PLAN → PROMPT → IMAGE → REVIEW_AUTO → REVIEW_HUMAN → APPROVED` (실패 시 `REVISE`)
검사기는 상태에 맞는 항목만 검사한다. 예: `SCENE_PLAN` 장면은 이미지가 없어도 FAIL 이 아니다.

## Grok 연동 모드 (중요)
SuperGrok 구독과 xAI API 는 **별도 결제 트랙**이다. 구독에 API 크레딧이 포함되지 않는다.

| 모드 | 조건 | 비용 | 방법 |
|---|---|---|---|
| **수동 (기본)** | SuperGrok 구독만 | 추가 비용 0 | `make_grok_input.py` 출력 → grok.com 붙여넣기 → `set-prompt` |
| **API (선택)** | console.x.ai 키 발급 | 토큰 종량제(프롬프트 생성 용도는 미미) | `python tools/grok_api.py SCENE-001` 한 줄로 조립→호출→저장→전이 |

**키 보안 3원칙** — ① 키는 환경변수 `XAI_API_KEY` 로만 (`set`/`$env:`/`export`), 파일 저장 금지 ② 서드파티 CLI에 키 제공 금지(2026-07 유출 사고) ③ SuperGrok OAuth 우회 미사용(403 불안정). 검사기 A8 이 저장소 내 키 패턴을 자동 탐지한다.

## CLI 치트시트 (웹 대신 터미널로도 동일 작업 가능 — 같은 파일을 공유)
| 단계 | 명령 |
|---|---|
| 장면 생성 | `python tools/advance_scene.py new` |
| 계획 작성 | 장면 파일의 purpose/action/camera/dialogue 채우기 (유일한 창작 수작업) |
| Grok 프롬프트 (수동) | `make_grok_input.py SCENE-001` → grok.com 붙여넣기 → `advance_scene.py set-prompt SCENE-001 --file grok_out.txt` |
| Grok 프롬프트 (API) | `python tools/grok_api.py SCENE-001` (위 두 단계를 한 줄로) |
| 이미지 생성 | 외부 AI에서 후보 1~4장 (레퍼런스 이미지 첨부 필수) |
| 후보 등록+자동검사 | `python tools/advance_scene.py add-images SCENE-001 a.png b.png` |
| 선택 | `python tools/advance_scene.py select SCENE-001 1` |
| 승인·잠금 | `python tools/advance_scene.py approve SCENE-001` |
| 진행 현황 | `python tools/advance_scene.py status` |
| 인화 규격 판정 | `python tools/print_preflight.py` (선택 이미지가 실물 인화에 적합한지 규격별 DPI/크롭) |
| 자가진단(수정 후 회귀) | `python tools/selftest.py` |

APPROVED 장면만 출력 패키지(DELIVERY.md)에 넣는다. 출력 기준은 개인 소장 인화 기본(긴 변 1024px, 매니페스트에서 조정).
