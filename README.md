# AI 비주얼노벨 제작 스튜디오 (v5.x — 웹 스튜디오)

스토리 → 장면 설계 → 이미지 프롬프트 → 이미지 생성 → 검수 → 비주얼 노벨 감상본 → 실물 인화까지,
한 저장소에서 굴리는 개인 제작 파이프라인. 브라우저 하나로 쓰고, 폰에서도 그대로 쓴다.

## 지금 쓰는 엔진

| 역할 | 무엇 | 비용 | 어디 |
|---|---|---|---|
| **스토리 · 장면 구성 · 이미지 프롬프트 · 인물 대화** | **로컬 LLM** (llama.cpp, OpenAI 호환 `http://127.0.0.1:8080/v1`) | **0원** | 내 PC (`c:\Users\USER\claude\local_llm`) |
| **이미지 생성** | **MakeFun AI** (`tools/makefun_client.py`) | **유료 종량제** | `MAKEFUN_API_TOKEN` 환경변수 |
| 그록(xAI) | **예비 경로** — grok.com 수동 복붙 또는 API | 구독/종량제 | `XAI_API_KEY` (선택) |

창작 텍스트와 인물 대화는 **내 PC 를 벗어나지 않는다.** 외부로 나가는 건 이미지 생성 프롬프트뿐이다.
엔진 교체는 `project/manifest.json` 의 `orchestrator` / `image_generator` 만 바꾸면 된다.

> **이미지 생성은 호출 1회가 곧 과금이다.** 자동으로 돌리지 않는다 — 사람이 버튼을 누를 때만 생성한다.

## 시작하기

```powershell
# 0) 환경 점검 (읽기 전용, 30초)
python tools/doctor.py

# 1) 로컬 LLM + 웹 스튜디오를 한 번에
powershell -ExecutionPolicy Bypass -File start_studio.ps1

#    폰에서도 쓰려면 (접속 PIN 이 자동으로 켜지고 콘솔에 표시된다)
powershell -ExecutionPolicy Bypass -File start_studio.ps1 -Lan
```

`-Lan` 은 `0.0.0.0` 에 바인딩하므로 같은 와이파이의 다른 기기도 보인다. 그래서 외부 기기
접속에는 **6자리 PIN 이 기본으로 요구된다**(이 PC 의 `127.0.0.1` 접속은 면제). PIN 은 기동할
때마다 새로 뽑혀 콘솔과 `logs/lan_pin.txt` 에 뜬다 — 자세한 건
[docs/PHONE_TUTORIAL.md](docs/PHONE_TUTORIAL.md).

스튜디오만 따로 띄우려면 `python tools/webapp.py` (기본 `http://127.0.0.1:8765/`).
이미 떠 있는 서버는 `start_studio.ps1` 이 다시 켜지 않는다(모델 재적재 방지).
요구사항: **Python 3.9+**. Pillow 는 인화 마스터·감상본 최적화에만 쓰인다(없어도 나머지는 동작).

## 워크플로우

| 단계 | 하는 일 | 어디서 | 담당 |
|---|---|---|---|
| 1 | 스토리라인 작성 | [스토리] 탭 — 로컬 LLM 과 대화 | 나 + 로컬 LLM |
| 2 | VN 텍스트 + 장면 분해 | [장면] 탭 — [스토리라인 → 장면 구성] | 로컬 LLM |
| 3 | 이미지 프롬프트 생성 | [장면] 탭 — 장면 카드의 프롬프트 버튼 | 로컬 LLM (앵커는 코드가 조립) |
| 4 | 이미지 생성 | [장면] 탭 — MakeFun 생성 / 📤 업로드 / `images/raw/<장면ID>/` 폴더 스캔 | 나 + 이미지 AI |
| 5 | 선택 · 승인 | [장면] 탭 — 후보 선택 → 승인 도장 | 나 + 자동 검사기 |
| 6 | 감상 | [뷰어] · [갤러리] · [대화] 탭 | 나 |
| 7 | 내보내기 | 단일 HTML 감상본 · PWA · 인화 마스터 | 도구 |

내부 상태 흐름: `SCENE_PLAN → PROMPT → IMAGE → REVIEW_HUMAN → APPROVED`
(되돌리기: `advance_scene revise <ID> SCENE_PLAN|PROMPT|IMAGE`)
자동 검사는 후보 등록·선택 시점에 그 자리에서 돌고 `review.auto` 에 남는다 — 머무는 단계가 아니다.
검사기는 **상태에 맞는 항목만** 본다. `SCENE_PLAN` 장면은 이미지가 없어도 FAIL 이 아니다.

> `status` 를 손으로 `REVIEW_AUTO` 라고 적지 마라. 검사기 열거값에만 남은 미사용 상태라
> **검사는 통과하지만 승격·승인이 모두 막힌다** — 자세한 건 [docs/SCHEMA.md](docs/SCHEMA.md) §2.1.

## 화면

**소설 만들기** — 스토리 / 장면 / 검사
**감상** — 뷰어 / 갤러리 / 대화

폰에서 쓰는 법(LAN 접속·이미지 업로드·홈 화면 추가)은 **[docs/PHONE_TUTORIAL.md](docs/PHONE_TUTORIAL.md)**.

## 디렉터리

```
project/manifest.json          프로젝트 설정 + 캐릭터/장소/소품 기준정보 (단일 매니페스트)
project/scenes/SCENE-XXX.json  장면 파일 1개 = 장면 1개 (파일명 = scene_id)
project/story/                 storyline.md · 대화 로그(개인 기록, git 제외)
images/raw/<scene_id>/         후보 이미지 보관
output/viewer/ · output/pwa/   감상본 · 설치형 번들
output/print/<규격>/           인화 마스터 (TIFF + JPEG + spec_sheet.json)
backups/                       project zip + sha256 체크섬
templates/ · examples/         빈 템플릿 + 프롬프트 틀·에셋 가이드 · 복사만 하면 PASS 나는 데모
docs/                          운영 문서
```

## 새 작품 시작

```powershell
copy templates\manifest.json project\manifest.json
# manifest 에 제목·캐릭터·장소를 채운다 (prompt_anchor 는 필수 — 컷 간 일관성의 근거)
# output.visual_style 에 작품 화풍을 적는다
# 분기 없는 선형 작품이면 dating 블록을 지운다 (지우면 호감도 미터가 숨는다)
# 실물 인화를 할 작품이면 output.min_long_edge_px 와 image_generator.max_long_edge_px 를 함께 올린다 (아래 ⚠)
python tools/check_protocol.py
```

필드별 규약(필수/선택·누가 쓰고 누가 읽는지·검사기가 보는지)은 **[docs/SCHEMA.md](docs/SCHEMA.md)** 가 정본이다.

데모로 먼저 초록불을 보고 싶다면 `examples\manifest.json` · `examples\scenes\SCENE-001.json` 을 복사한다.

## CLI (웹과 같은 파일을 공유 — 터미널로도 동일 작업)

| 단계 | 명령 |
|---|---|
| 환경 점검 | `python tools/doctor.py` |
| 장면 구성 | `python tools/vn_compose.py 10` (스토리라인 → 장면 10개) |
| 장면 생성 | `python tools/advance_scene.py new` |
| 프롬프트 (수동) | `python tools/make_grok_input.py SCENE-001` → 붙여넣기 → `advance_scene.py set-prompt SCENE-001 --file out.txt` |
| 프롬프트 (그록 API) | `python tools/grok_api.py SCENE-001` |
| **이미지 생성 (유료)** | `python tools/makefun_client.py SCENE-001 --n 2` — **호출 1회 = 과금** |
| 후보 등록 + 자동검사 | `python tools/advance_scene.py add-images SCENE-001 a.png b.png` |
| 선택 / 승인 | `python tools/advance_scene.py select SCENE-001 1` → `approve SCENE-001` |
| 되돌리기 | `python tools/advance_scene.py revise SCENE-001 IMAGE --note "사유"` |
| 진행 현황 | `python tools/advance_scene.py status` |
| 연출 리듬 자문 | `python tools/scene_lint.py` (경고만, PASS/FAIL 아님) |
| 인물과 대화 | `python tools/local_llm.py "지혜야 안녕"` |
| 감상본 내보내기 | `python tools/export_viewer.py` / `python tools/export_pwa.py` |
| 인화 규격 판정 | `python tools/print_preflight.py` |
| 인화 마스터 굽기 | `python tools/print_export.py --size 4x6 --contact` (Pillow 필요) |
| 백업 (이미지 포함) | `python tools/backup_project.py snapshot --with-images --dest D:/backup` |
| 무결성 · 복원 | `python tools/backup_project.py verify` / `restore --dry-run` → `restore` |
| 비밀값 스캔 | `python tools/secret_scan.py` |
| 자가진단(회귀) | `python tools/selftest.py` — **전체 통과**를 확인한다 (서버 포트를 쓰므로 스튜디오는 끄고 실행) |

## 검사와 승인

- **자동 검사기** `python tools/check_protocol.py` — SCORECARD **A1~A8** 판정
  (스키마·ID 정합·해상도·화자·순서·프롬프트 앵커·검수 상태·키 유출).
- **사람 시사** — SCORECARD C (캐릭터 일관성·연출 흐름·대사·몰입·인화 품질·화풍).
  자동으로 대체할 수 없다. 승인 도장은 사람만 찍는다.
- `protocol/SCORECARD.md` 와 `tools/check_protocol.py` 는 **에이전트가 수정할 수 없다.**
  개정이 필요하면 사용자에게 제안만 한다(CLAUDE.md "채점표·검사기 개정 절차").

APPROVED 장면만 감상본·인화 대상이 된다.

## 키·토큰 보안 (3원칙)

1. **환경변수 전용.** `MAKEFUN_API_TOKEN` · `XAI_API_KEY` 를 저장소의 어떤 파일에도 쓰지 않는다
   (`.env` 포함 금지). 매니페스트에는 값이 아니라 변수 이름(`token_env`)만 적는다.
2. **서드파티 CLI·에이전트에 제공 금지.** 근거: 2026-07 Grok Build CLI 가 `.env` 의 키를
   평문으로 서버에 전송한 사고.
3. **브라우저로 전달 금지.** 서버가 알려주는 건 "설정됨/미설정" 불리언뿐이다.

검사기 **A8** 이 저장소 내 `xai-` 패턴을 판정하고, `python tools/secret_scan.py` 가
MakeFun `sk_`·Bearer·JWT·클라우드 키까지 넓게 훑는다(**발견해도 실제 값은 출력하지 않는다**).
영구 등록 방법은 **[docs/ENV_SETUP.md](docs/ENV_SETUP.md)**.

## 인화 (실물 출력)

같은 장면 원본에서 감상본과 인화물이 함께 파생된다.
매니페스트 기본 `min_long_edge_px: 1024` 는 화면 감상 기준이라 **엽서 인화에는 부족하다**
(300DPI 에서 긴 변 약 3.4인치). 4×6 엽서에 1200×1800px, 5×7 에 1500×2250px 이 필요하다.

> **⚠ 값을 올릴 때는 두 개를 함께 올린다.** `output.min_long_edge_px` 만 2250·3600 으로 올리면
> 생성 요청이 `image_generator.max_long_edge_px`(기본 **2048**)에서 잘려 나가고,
> 올려 둔 기준 때문에 그 장면이 검사기 **A3 FAIL** 이 된다 — 돈은 쓰고 규격은 못 맞춘다.
> 확인은 과금 없이: `python tools/makefun_client.py --check` → `생성 크기 … · 상한 …px`.
> (→ [docs/SCHEMA.md](docs/SCHEMA.md) §1.3)

`python tools/print_preflight.py` 로 컷별 판정 후 주문한다 — 실무 절차는
**[docs/PRINT_ORDER_GUIDE.md](docs/PRINT_ORDER_GUIDE.md)**.

## 문서

| 문서 | 언제 |
|---|---|
| [docs/SCHEMA.md](docs/SCHEMA.md) | 매니페스트·장면 파일의 필드를 확인할 때 (스키마 단일 출처) |
| [docs/PHONE_TUTORIAL.md](docs/PHONE_TUTORIAL.md) | 폰에서 쓰고 싶을 때 (LAN 접속·PIN·업로드·홈 화면) |
| [docs/ENV_SETUP.md](docs/ENV_SETUP.md) | 토큰을 영구 등록할 때, 재부팅 후 401 이 날 때 |
| [docs/PRINT_ORDER_GUIDE.md](docs/PRINT_ORDER_GUIDE.md) | 실물 인화를 주문할 때 |
| [docs/PRIVACY_HOSTING.md](docs/PRIVACY_HOSTING.md) | 감상본을 인터넷에 올릴까 고민될 때 |
| [docs/RECOVERY_RUNBOOK.md](docs/RECOVERY_RUNBOOK.md) | 뭔가 깨졌을 때, PC 를 새로 세팅할 때 (백업·복원 절차) |
| [templates/free-assets-ko.md](templates/free-assets-ko.md) | 폰트·BGM·효과음을 무료로 구할 때 (라이선스 등급별) |
| [templates/grok-prompts-ko.md](templates/grok-prompts-ko.md) | 그록에 붙여넣을 한글 프롬프트 틀이 필요할 때 |
| [CLAUDE.md](CLAUDE.md) | 제작 프로토콜 원칙·금지 조항 |
| [protocol/SCORECARD.md](protocol/SCORECARD.md) | 판정 기준 원문 (수정 금지) |
| [NO_TOKEN_TASKS.md](NO_TOKEN_TASKS.md) | **다음에 할 일 · 진행 상태** (상태의 단일 출처) |
| [BACKLOG.md](BACKLOG.md) | 백로그 번호가 무엇이고 왜 필요한지 (항목 정의) |

## 프라이버시

인물과 나눈 대화(`project/story/chatlog.json`, `talk_*.json`, 상한을 넘겨 밀려난
`*.archive.jsonl`, 요약본 `memory_*.json`)는 **git 에서 제외**된다.
감상본 HTML 에도 포함되지 않는다 — 들어가는 건 제목·캐릭터 이름·대사·승인된 이미지다.
그 파일 하나에 작품 전체가 들어 있으므로, 공개 호스팅 전에
**[docs/PRIVACY_HOSTING.md](docs/PRIVACY_HOSTING.md)** 를 먼저 읽는다.
