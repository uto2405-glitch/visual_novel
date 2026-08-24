# 작업 루프 — AI 비주얼노벨 제작 (v5.x · 현행 엔진)

## 지금 쓰는 엔진

| 역할 | 무엇 | 비용 |
|---|---|---|
| 스토리 · 장면 구성 · 이미지 프롬프트 · 인물 대화 | **로컬 LLM** (llama.cpp, `http://127.0.0.1:8080/v1`) | 0원 |
| 이미지 생성 | **MakeFun AI** (`tools/makefun_client.py`, `MAKEFUN_API_TOKEN`) | **유료 종량제 — 호출 1회 = 과금** |
| 그록(xAI) | **예비 경로** — grok.com 수동 복붙 또는 `tools/grok_api.py` | 구독/종량제 |

교체는 매니페스트 `orchestrator` / `image_generator` 만 바꾸면 된다.

---

## 표준 흐름: 웹 스튜디오

```
powershell -ExecutionPolicy Bypass -File start_studio.ps1     # 로컬 LLM + 스튜디오
```

1. **[스토리]** 로컬 LLM 과 대화 → 오른쪽 스토리라인 정리 → 저장 (`project/story/storyline.md`)
2. **[장면]** 장면 수 지정 → [스토리라인 → 장면 구성] → 로컬 LLM 이 VN 대사 + 이미지 프롬프트 생성
   (`project/scenes/`, 상태 `PROMPT`). 앵커는 **코드가 조립**하므로 A6 가 구조적으로 지켜진다.
3. **장면 다듬기** — 카드에서 목적·동작·감정·카메라·대사·분기를 고친다.
   (**사람이 승인한다**: 이야기의 리듬은 자동 검사 대상이 아니다. `python tools/scene_lint.py` 는 자문만.)
4. **이미지** — 셋 중 하나. **자동으로 돌리지 않는다. 사람이 버튼을 누를 때만 생성한다.**
   - [MakeFun 생성] (유료) — 버튼 1회 = 과금 1회
   - 📤 업로드 — 다른 이미지 AI 에서 만든 결과를 올린다
   - `images/raw/<장면ID>/` 에 넣고 [폴더 스캔]
5. **선택 · 승인** — 후보 썸네일 클릭 → 자동 검사 PASS → **[승인 도장]** (사람만 찍는다)
6. **감상 · 내보내기** — [뷰어]·[갤러리]·[대화] / 단일 HTML 감상본 · PWA · 인화 마스터

웹과 CLI 는 **같은 파일**을 읽고 쓰므로 언제든 혼용할 수 있다.

---

## 핵심 원칙

한 번에 전체 작품을 생성하지 않는다. 장면 하나씩 통과시킨다.

**장면 파일에서 손대는 것과 손대지 않는 것이 나뉜다.**

| | 필드 | 어떻게 |
|---|---|---|
| 손대지 않는다 | `status` · `review` · `assets` · `scene_id` · `scene_order` | 도구만 쓴다(`advance_scene`·`scene_ops`). 상태 전이·승인 잠금·과금 복구 기록이 걸려 있다 |
| 직접 고친다 | `purpose` · `action_beat` · `emotion` · `time` · `camera` · `dialogue` · `characters` · `location_id` · `episode` · `choices` · `branch` · `ending`(+`ending_label`) · `print` | **스튜디오 장면 편집이 정식 경로**(`POST /api/set-scene` — 이 목록만 병합 저장). 에디터로 직접 고쳐도 된다 |

승인(APPROVED)된 장면은 어느 경로로도 편집이 거부된다. 고치려면 먼저 `revise` 로 되돌린다.
필드별 규약은 **[docs/SCHEMA.md](../docs/SCHEMA.md)** 가 정본이다.

사람이 직접 하는 일은 넷이다: **이야기 결정 · 장면 다듬기 · 이미지 생성 승인 · 시사와 선택.**

## 루프 상태

장면 단계(`status`): `SCENE_PLAN` → `PROMPT` → `IMAGE` → `REVIEW_HUMAN` → `APPROVED`, 되돌리기 `REVISE`
(`REVIEW_AUTO` 는 후보 등록 시 자동 실행되어 별도 상태로 머물지 않는다)

---

## (대안) CLI 루프 — 장면 1개

```bash
# 1. 장면 생성 (scene_id·order 자동)
python tools/advance_scene.py new

# 2. 장면 계획을 채운다 — 스튜디오 장면 편집 또는 파일 직접 편집
#    (purpose / action_beat / emotion / time / camera / dialogue)

# 3. 이미지 프롬프트 — 셋 중 하나
#   [로컬 LLM · 기본] 스튜디오 장면 카드의 프롬프트 버튼 (앵커는 코드가 조립)
#   [수동 · 그록] 출력 통째로 grok.com 에 붙여넣기
python tools/make_grok_input.py SCENE-XXX
python tools/advance_scene.py set-prompt SCENE-XXX --file grok_out.txt
#   [API · 그록] XAI_API_KEY 환경변수 설정 후
python tools/grok_api.py SCENE-XXX

# 4. 이미지 — 유료. 사용자가 그 시점에 허가한 만큼만.
python tools/makefun_client.py SCENE-XXX --n 2
#   다운로드만 실패했을 때는 재생성하지 말고 재수령(무과금):
python tools/makefun_client.py SCENE-XXX --refetch
#   외부 이미지 AI 를 쓴다면 캐릭터·장소 레퍼런스를 반드시 첨부하고 결과를 등록:
python tools/advance_scene.py add-images SCENE-XXX 다운로드1.png 다운로드2.png

# 5. 시사 후 1장 선택 → 승인 (검사 FAIL 이면 자동 롤백)
python tools/advance_scene.py select SCENE-XXX 2
python tools/advance_scene.py approve SCENE-XXX
```

되돌리기: `python tools/advance_scene.py revise SCENE-XXX <SCENE_PLAN|PROMPT|IMAGE> --note "사유"`
진행 확인: `python tools/advance_scene.py status`
여러 장면 일괄 구성: `python tools/vn_compose.py 10` (스토리라인 → 장면 10개, 상태 `PROMPT`)

## 회귀 방지 규칙

- APPROVED 장면의 캐릭터/장소/소품 기준정보는 이후 장면 수정 때문에 변경하지 않는다.
- 기준정보 변경이 필요하면 version 을 올린 새 항목을 만든다. 예: `CHAR-001` version 2.
- `revise` 는 기존 이미지·프롬프트를 지우지 않고 되돌린다(선택만 무효화).
- `assets.makefun_tasks[]` 는 **지우지 않는다** — 과금된 작업을 무과금으로 다시 받는 유일한 열쇠다.
- APPROVED 가 아닌 장면은 최종 출력(감상본·인화)에 포함하지 않는다.
- 승인 컷이 늘면 백업에 이미지를 포함한다:
  `python tools/backup_project.py snapshot --with-images --dest D:/backup`

## 승인 게이트

### Gate A — 이야기
스토리/장면 목적이 명확하고 사용자가 승인.
### Gate B — 비주얼 기준 (캐릭터 시트 의무)
주요 캐릭터마다 **3면도+표정 시트**를 먼저 생성·승인하고 매니페스트 `reference_images` 에 등록.
이후 이미지 생성에서 이 레퍼런스를 참조한다. `prompt_anchor` 는 코드가 프롬프트에 넣는 2차 보조 수단이다.
### Gate C — 콘티/구도
각 장면의 행동과 카메라 설계가 승인.
### Gate D — 이미지
자동 검사 PASS + 사용자 시사 PASS (`approve` 명령이 강제).
### Gate E — 출력
감상본과 인화본 샘플 검수. 인화 전 `print_preflight` 판정과 `backup_project verify` 를 통과할 것.

## 파일럿 규칙

본편 확정 전, 실제 작품의 첫 3장면을 파일럿으로 돌려 화풍 프롬프트·레퍼런스 방식·인화 규격을
보정한 뒤 계속 진행한다. 인화까지 갈 작품이면 **파일럿에서 인화 해상도부터 맞춘다**
(`min_long_edge_px` 와 `max_long_edge_px` 를 함께 — [docs/PRINT_ORDER_GUIDE.md](../docs/PRINT_ORDER_GUIDE.md)).

## 기본 작업 단위

- 1회 작업: 1장면 / 후보 1~4장 / 선택 1장
- APPROVED 이후 다음 장면
