# AI 비주얼노벨 제작 스튜디오 (v5.x — 웹 스튜디오)

스토리 → 장면 설계 → 이미지 프롬프트 → 이미지 생성 → 검수 → 비주얼 노벨 감상본 → 실물 인화까지,
한 저장소에서 굴리는 개인 제작 파이프라인. 브라우저 하나로 쓰고, 폰에서도 그대로 쓴다.

## 지금 쓰는 엔진

| 역할 | 무엇 | 비용 | 어디 |
|---|---|---|---|
| **스토리 · 장면 구성 · 이미지 프롬프트 · 인물 대화** | **로컬 LLM** (llama.cpp, OpenAI 호환) | **0원** | 내 **집 안**의 PC 한 대. 지금은 같은 공유기의 노트북(`http://192.168.219.182:8080/v1`) — 이 PC 여도 되고 다른 기기여도 된다 |
| **이미지 생성 (기본)** | **ComfyUI** — 내 PC 의 로컬 서버 (`tools/comfyui_client.py`) | **0원** | `http://127.0.0.1:8188` (`COMFYUI_URL` 로 변경) |
| 이미지 생성 (보조) · 업스케일 · 크레딧 | **MakeFun AI** (`tools/makefun_client.py`) | **유료 종량제** | `MAKEFUN_API_TOKEN` 환경변수 |
| 로컬 LLM 이 꺼져 있을 때 | **직접 입력(붙여넣기)** — 브리프를 복사해 직접 쓰거나 다른 AI 에 물어보고, 받은 결과를 붙여넣는다 | **0원** | 키·계정 불필요 |

창작 텍스트와 인물 대화는 **내 집 밖으로 나가지 않는다** — LLM 은 내가 켠 기기(이 PC 또는 같은
공유기의 노트북)에서만 돌고, 주소 검증이 루프백·사설망 외의 주소를 거부한다. 외부로 나가는 것은 이미지 생성 프롬프트와,
**이미지 쪽 기능을 쓸 때의 이미지 파일**이다 — 캐릭터 레퍼런스(로컬 파일일 때)와 업스케일할
원본 컷은 공급자 스토리지에 업로드된다(→ [docs/PRIVACY_HOSTING.md](docs/PRIVACY_HOSTING.md) §1).
엔진 교체는 `project/manifest.json` 의 `orchestrator` / `image_generator` 만 바꾸면 된다
(이미지는 `image_generator.engine` 을 `comfyui` ↔ `makefun` 으로 — 두 블록의 설정은 각자 남는다).

> **MakeFun 이미지 생성은 호출 1회가 곧 과금이다.** 자동으로 돌리지 않는다 — 사람이 버튼을 누를 때만 생성한다.
> 기본 엔진 ComfyUI 는 내 PC 에서 돌아 무료다.

## 시작하기

> **두 기계를 꺼다 켜고 다시 켜려면** → [docs/START_HERE.md](docs/START_HERE.md)
> (노트북 원클릭 · 그림 PC 깨우기 · 주소가 바뀜을 때 · 안 될 때의 순서)


```powershell
# 0) 환경 점검 (읽기 전용, 30초) — 이미지를 만들 거면 ComfyUI(기본 http://127.0.0.1:8188)를 먼저 켜 둔다
python tools/doctor.py

# 1) 로컬 LLM + 웹 스튜디오를 한 번에
powershell -ExecutionPolicy Bypass -File start_studio.ps1

#    폰에서도 쓰려면 (접속 PIN 이 자동으로 켜지고 콘솔에 표시된다)
powershell -ExecutionPolicy Bypass -File start_studio.ps1 -Lan
```

> **ComfyUI 가 아직 없다면**: github.com/comfyanonymous/ComfyUI 의 Windows 포터블을 받아 아무 폴더에 풀고,
> 체크포인트 `waiIllustriousSDXL_v170.safetensors` 를 `models\checkpoints\` 에 넣는다(매니페스트 `image_generator.comfyui.checkpoint`).
> 저장소 **옆**(`..\ComfyUI`)에 두면 `start_studio.ps1` 이 알아서 켜고, 다른 곳이면 `setx COMFYUI_HOME "D:\ComfyUI"` 한 번이면 된다.
> 확인: `python tools/comfyui_client.py --check --online`
>
> 로컬 LLM(llama.cpp)을 저장소 밖 다른 경로에 설치했다면 `setx LOCAL_LLM_HOME "D:\llm\local_llm"`
> 또는 `start_studio.ps1 -LlmRoot D:\llm\local_llm`. 아직 없으면 `-NoLlm` 으로 스튜디오만 켜도 된다.
>
> **LLM 이 이 PC 가 아니라 다른 기기(노트북 등)에 있다면** 켜 줄 것이 없다 — 주소만 알려 주면 된다.
> `project/manifest.json` 의 `talk.base_url` 과 `orchestrator.api.base_url` **두 줄**이 그 자리이고,
> `start_studio.ps1` 은 그 주소가 루프백이 아니면 **여기서 서버를 띄우려 하지 않고 응답만 확인한다**.
> 그 기기의 IP 가 DHCP 로 바뀌었을 때 고치는 곳도 같은 두 줄이다(한 줄로 끝내려면
> `setx LOCAL_LLM_URL "http://새IP:8080/v1"` — 환경변수가 매니페스트보다 우선한다).
> 서버를 `--api-key` 로 띄웠다면 그 값을 `orchestrator.api.api_key` 에 적는다(없으면 대화만 401 로 죽는다).

`-Lan` 은 `0.0.0.0` 에 바인딩하므로 같은 와이파이의 다른 기기도 보인다. 그래서 외부 기기
접속에는 **6자리 PIN 이 기본으로 요구된다**(이 PC 의 `127.0.0.1` 접속은 면제). PIN 은 기동할
때마다 새로 뽑혀 콘솔과 `logs/lan_pin.txt` 에 뜬다 — 자세한 건
[docs/PHONE_TUTORIAL.md](docs/PHONE_TUTORIAL.md).

스튜디오만 따로 띄우려면 `python tools/webapp.py` (기본 `http://127.0.0.1:8765/`).
이미 떠 있는 서버는 `start_studio.ps1` 이 다시 켜지 않는다(모델 재적재 방지).
요구사항: **Python 3.9+**. 도구(`tools/*.py`)는 표준 라이브러리만 쓰므로 그 자체로는 설치할 것이 없다.

### .venv — Pillow 하나를 위한 저장소 전용 가상환경 (선택)
Pillow 가 없는 파이썬으로 스튜디오를 띄우면 `/img?w=224` 가 썸네일 대신 **원본 PNG 를 그대로 보낸다**
— 장면 탭 한 번에 수십 MB, 폰에서는 그대로 데이터 요금이다. 인화 마스터 굽기·컨택트시트·PWA 컷 아이콘도 함께 막힌다.
그래서 시스템 파이썬은 건드리지 않고 저장소 안에만 Pillow 를 둔다:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install Pillow
```

`start_studio.ps1` 은 `.venv\Scripts\python.exe` 가 있으면 그쪽으로, 없으면 그냥 `python` 으로 스튜디오를
띄우고 어느 쪽을 썼는지 기동 로그에 한 줄로 알린다. **없어도 감상·검사·생성은 전부 동작한다** — 선택사항이다.
`.venv/` 는 git 제외 대상이라 기기마다 위 두 줄로 다시 만든다. 지금 상태는 `python tools/doctor.py` 가 알려 준다.

### 방금 clone 했다면 — 그림은 따라오지 않는다
`images/raw/` · `output/` · `backups/` · `logs/` 는 `.gitignore` 대상이다. **clone 에는 그림이 한 장도 없다.**
그래서 새 클론에서 `python tools/check_protocol.py` 는 `RESULT: FAIL — 실패 72건`(A3 이미지 없음)이 정상이다 — 코드 문제가 아니다.

- 내 작품을 옮겨 온 것이라면 → `python tools/backup_project.py list` 로 스냅샷을 보고
  `restore --snapshot <스탬프>` 로 `images/` 를 되돌린다(→ [docs/RECOVERY_RUNBOOK.md](docs/RECOVERY_RUNBOOK.md) §1·§3).
  **이미지가 든 스냅샷**이어야 한다(`list` 가 "이미지 포함" 이라고 표시해 준다).
- 백업이 없다면 → 장면을 되돌리고 다시 그린다(무료):
  `python tools/advance_scene.py revise SCENE-001 IMAGE --note "원본 없음"` → `python tools/comfyui_client.py SCENE-001 --n 2`
- 남의 저장소를 구경만 할 거라면 → 데모로 초록불부터 본다:
  `copy examples\manifest.json project\manifest.json` · `copy examples\scenes\SCENE-001.json project\scenes\` → `check_protocol` 이 `RESULT: PASS`.

## 워크플로우

| 단계 | 하는 일 | 어디서 | 담당 |
|---|---|---|---|
| 1 | 스토리라인 작성 | [스토리] 탭 — 로컬 LLM 과 대화 | 나 + 로컬 LLM |
| 2 | VN 텍스트 + 장면 분해 | [장면] 탭 — [스토리라인 → 장면 구성] | 로컬 LLM ([⏱ 느리다](#장면-구성은-오래-걸린다)) |
| 3 | 이미지 프롬프트 생성 | [장면] 탭 — 장면 카드의 프롬프트 버튼 | 로컬 LLM (앵커는 코드가 조립) |
| 4 | 이미지 생성 | [장면] 탭 — [🎨 이미지 생성] = ComfyUI(로컬·무료) · 보조 [MakeFun 생성(유료)](캐릭터 레퍼런스 자동 첨부) / 📤 업로드 / `images/raw/<장면ID>/` 폴더 스캔 | 나 + 이미지 AI |
| 5 | 선택 · 승인 | [장면] 탭 — 후보 선택 → 승인 도장 | 나 + 자동 검사기 |
| 6 | 감상 | [뷰어] · [갤러리] · [대화] 탭 | 나 |
| 7 | 내보내기 | 단일 HTML 감상본 · PWA · 인화 마스터 | 도구 |

내부 상태 흐름: `SCENE_PLAN → PROMPT → IMAGE → REVIEW_HUMAN → APPROVED`
(되돌리기: `advance_scene revise <ID> SCENE_PLAN|PROMPT|IMAGE`)
자동 검사는 후보 등록·선택 시점에 그 자리에서 돌고 `review.auto` 에 남는다 — 머무는 단계가 아니다.
`IMAGE` 는 **후보만 있고 아직 안 고른 상태**다. `REVIEW_HUMAN` 으로 올리는 것은 **후보 선택 하나뿐**이다
(렌더가 끝난 것만으로는 올라가지 않는다 — 선택 없이 올리면 검사기 A3 가 `selected_image` 를 요구해 FAIL 이다).
검사기는 **상태에 맞는 항목만** 본다. `SCENE_PLAN` 장면은 이미지가 없어도 FAIL 이 아니다.

> `status` 를 손으로 `REVIEW_AUTO` 라고 적지 마라. 검사기 열거값에만 남은 미사용 상태라
> **검사는 통과하지만 승격·승인이 모두 막힌다** — 자세한 건 [docs/SCHEMA.md](docs/SCHEMA.md) §2.1.

### 장면 구성은 오래 걸린다

노트북의 Qwen3.6-35B-A3B(MoE 35B/3B · Q4_K_M)에서 실측한 값이다. **멈춘 게 아니다**:

| 기능 | 출력 상한 | 실측 시간 |
|---|---|---|
| 이미지 프롬프트 (장면 1개) | 120 토큰 | **3~10초** |
| 인물 대화 (1턴) | 320 토큰 | **20~30초** |
| 스토리 채팅 (1턴) | 1000 토큰 | **5~12초** (짧게 답할 때) |
| **장면 구성 3개** | 8192 토큰 | **95~115초** |
| **장면 구성 12개** | 8192 토큰 | **7분 이상** |

출력 속도는 12~14 tok/s 다 — 장면 하나가 대략 400 토큰이니 **장면 1개당 30초**로 잡으면 된다.
그래서 [장면 구성]은 스트리밍으로 받는다(자세한 이유는 [docs/SCHEMA.md](docs/SCHEMA.md) §1.2).
문맥(32K)은 넉넉하다 — 지시문은 개수와 무관하게 3,297토큰이고 장면 12개를 실은 스토리 챗도 1,409토큰이다.

앵커와 말투도 지시만으로는 안 지켜진다. 장면 3개 중 2개가 **앵커 중간에 제 말을 끼워 넣어**
검사기 A6 에서 떨어졌고(이제 붙여넣기 경로와 같은 앵커 보정을 자동으로 건다 — 보정하면
결과 줄에 "앵커 보정 N장" 이 붙는다), 반말로 말하는 인물이 새 장면에서 존댓말을 썼다
(이제 지시문이 `profile.speech_style` 을 함께 싣는다).

그리고 이 모델은 **"JSON 배열만 출력하라"를 자주 어긴다** — 같은 지시문 7회에서 배열 3 ·
`{"scenes":[…]}` 포장 2 · 배열 없이 객체 나열 2 였다. 세 모양 모두 읽도록 고쳐 뒀지만,
**요청한 개수를 안 맞추는 경우가 따로 있다**(3개를 시켰는데 1개). 그때는 한 번 더 물어보고,
그래도 어긋나면 장면을 건드리지 않고 멈춘다 — 다시 누르거나 [✍ 직접 입력]을 쓰면 된다.

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
# 캐릭터 시트를 먼저 뽑아 characters[].reference_images 에 등록한다 (생성마다 자동 첨부된다)
#   — 컷을 다 뽑은 뒤에 등록하면 앞서 만든 컷은 얼굴이 달라 다시 뽑아야 한다 = 재과금
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
| 프롬프트 (직접 입력) | `python tools/scene_brief.py SCENE-001` → 받은 출력을 `advance_scene.py set-prompt SCENE-001 --file out.txt` |
| **이미지 생성 (무료 · ComfyUI)** | `python tools/comfyui_client.py SCENE-001 --n 2` — `--seed` 로 재현 · `--check --online` 으로 연결·체크포인트 확인 |
| **이미지 생성 (유료 · MakeFun)** | `python tools/makefun_client.py SCENE-001 --n 2` — **호출 1회 = 과금** |
| **인화용 확대 (유료)** | `python tools/makefun_client.py --upscale SCENE-001` — 승인한 그림 그대로 픽셀만 키워 **새 후보로** 저장 |
| 레퍼런스 URL 만들기 | `python tools/makefun_client.py --upload images/ref/시트.png` → 출력된 URL 을 `reference_images` 에 등록 |
| 생성 설정 점검 / 크레딧 | `python tools/makefun_client.py --check` (무호출) · `--credits` (이력 조회, 생성 과금 없음) |
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
| 자가진단(회귀) | `python tools/selftest.py` — **전체 통과**를 확인한다 (빈 포트를 알아서 잡으므로 스튜디오를 끄지 않아도 된다) |

## 검사와 승인

- **자동 검사기** `python tools/check_protocol.py` — SCORECARD **A1~A8** 판정
  (스키마·ID 정합·해상도·화자·순서·프롬프트 앵커·검수 상태·키 유출).
- **사람 시사** — SCORECARD C (캐릭터 일관성·연출 흐름·대사·몰입·인화 품질·화풍).
  자동으로 대체할 수 없다. 승인 도장은 사람만 찍는다.
- `protocol/SCORECARD.md` 와 `tools/check_protocol.py` 는 **에이전트가 수정할 수 없다.**
  개정이 필요하면 사용자에게 제안만 한다(CLAUDE.md "채점표·검사기 개정 절차").

APPROVED 장면만 감상본·인화 대상이 된다.

## 키·토큰 보안 (3원칙)

1. **환경변수 전용.** `MAKEFUN_API_TOKEN` 을 저장소의 어떤 파일에도 쓰지 않는다
   (`.env` 포함 금지). 매니페스트에는 값이 아니라 변수 이름(`token_env`)만 적는다.
   오케스트레이터는 로컬이라 키 자체가 없다 — 지금 남은 비밀값은 이 토큰 하나뿐이다.
2. **서드파티 CLI·에이전트에 제공 금지.** 근거: 2026-07 Grok Build CLI 가 `.env` 의 키를
   평문으로 서버에 전송한 사고. 공급자가 바뀌어도 조항은 남는다.
3. **브라우저로 전달 금지.** 서버가 알려주는 건 "설정됨/미설정" 불리언뿐이다.

검사기 **A8** 이 저장소 내 `xai-` 패턴을 판정하고(유출 탐지기라 공급자 은퇴와 무관하게 남는다),
`python tools/secret_scan.py` 가
MakeFun `sk_`·Bearer·JWT·클라우드 키까지 넓게 훑는다(**발견해도 실제 값은 출력하지 않는다**).
영구 등록 방법은 **[docs/ENV_SETUP.md](docs/ENV_SETUP.md)**.

## 인화 (실물 출력)

같은 장면 원본에서 감상본과 인화물이 함께 파생된다.
매니페스트 기본 `min_long_edge_px: 1024` 는 화면 감상 기준이라 **엽서 인화에는 부족하다**
(300DPI 에서 긴 변 약 3.4인치). 4×6 엽서에 1200×1800px, 5×7 에 1500×2250px 이 필요하다.

> **⚠ 값을 올릴 때는 두 개를 함께 올린다.** `output.min_long_edge_px` 만 2250·3600 으로 올리면
> 생성 요청이 `image_generator.max_long_edge_px`(기본 **2048**)에서 잘려 나가고,
> 올려 둔 기준 때문에 그 장면이 검사기 **A3 FAIL** 이 된다 — 돈은 쓰고 규격은 못 맞춘다.
> 확인은 과금 없이 **지금 쓰는 엔진**으로: `python tools/comfyui_client.py --check`
> → `생성 크기 … · 상한 …px · hires 상한 …px`. (MakeFun 을 쓸 때만 `python tools/makefun_client.py --check`
> — 토큰이 없으면 FAIL 한 줄이 먼저 뜨는데 그건 정상이고, 찍히는 크기도 MakeFun 것이라 기본 엔진과 다르다.)
>
> **ComfyUI 에는 올려야 할 값이 하나 더 있다.** hires 확대는 1차 캔버스의 2배까지라
> 기본 `comfyui.base_long_edge_px: 1248` 에서는 **2496px 이 천장**이다 — 8×10(3600px)은 앞의 두 값을
> 아무리 올려도 나오지 않는다. 규격별로 바꿀 키와 값은 `python tools/print_preflight.py` 가 그대로 찍어 준다.
> (→ [docs/SCHEMA.md](docs/SCHEMA.md) §1.3·§1.4)

**이미 승인한 컷은 다시 만들지 말고 키운다.** 재생성은 그림 자체가 달라져(구도·표정) 사람이
승인한 컷이 사라지고 과금도 장수만큼 다시 든다. `--upscale` 은 **그 그림 그대로 픽셀만** 키워
새 후보로 저장하고 선택·승인 상태를 건드리지 않는다 — 1200×1800(엽서 한계)에서 8×10 으로
가는 길이 이것이다.

```powershell
python tools/makefun_client.py --upscale SCENE-001   # 유료 · 한 장으로 먼저 시험한다
```

`python tools/print_preflight.py` 로 컷별 판정 후 주문한다 — 절차(승인 컷을 확대해서
다시 고르기까지)는 **[docs/PRINT_ORDER_GUIDE.md](docs/PRINT_ORDER_GUIDE.md)** §1.

## 문서

| 문서 | 언제 |
|---|---|
| [docs/SCHEMA.md](docs/SCHEMA.md) | 매니페스트·장면 파일의 필드를 확인할 때 (스키마 단일 출처) |
| [docs/PHONE_TUTORIAL.md](docs/PHONE_TUTORIAL.md) | 폰에서 쓰고 싶을 때 (LAN 접속·PIN·업로드·홈 화면) |
| [docs/ENV_SETUP.md](docs/ENV_SETUP.md) | 토큰을 영구 등록할 때, 재부팅 후 401 이 날 때 |
| [docs/PRINT_ORDER_GUIDE.md](docs/PRINT_ORDER_GUIDE.md) | 실물 인화를 주문할 때 · 승인한 컷을 인화 규격으로 키울 때 |
| [docs/MAKEFUN_CAPABILITIES.md](docs/MAKEFUN_CAPABILITIES.md) | "이미지 AI 로 이것도 되나?" — 쓰는 API·안 붙인 API 와 그 이유 |
| [docs/PRIVACY_HOSTING.md](docs/PRIVACY_HOSTING.md) | 감상본을 인터넷에 올릴까 고민될 때 |
| [docs/RECOVERY_RUNBOOK.md](docs/RECOVERY_RUNBOOK.md) | 뭔가 깨졌을 때, PC 를 새로 세팅할 때 (백업·복원 절차) |
| [templates/free-assets-ko.md](templates/free-assets-ko.md) | 폰트·BGM·효과음을 무료로 구할 때 (라이선스 등급별) |
| [templates/prompt-frames-ko.md](templates/prompt-frames-ko.md) | 직접 쓰거나 다른 AI 에 물어볼 한글 프롬프트 틀이 필요할 때 |
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
