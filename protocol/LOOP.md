# 작업 루프 — AI 웹툰 제작 시스템 (v5)

## 표준 흐름: 웹 스튜디오 (`python tools/webapp.py`)
1. **[스토리]** Grok 과 대화 → 오른쪽 스토리라인 정리 → 저장 (`project/story/`)
2. **[장면]** 장면 수 지정 → [스토리라인 → 장면 구성] → Grok 이 VN 대사+이미지 프롬프트 생성 (`project/scenes/`, 상태 PROMPT)
3. **(외부·수동)** 각 장면의 프롬프트 복사 → 외부 이미지 AI(레퍼런스 첨부) → 결과 다운로드
4. **[장면]** `images/raw/장면ID/` 에 넣고 [폴더 스캔](자동검사) → 썸네일 클릭으로 선택 → [승인 도장]
5. **[뷰어]** 처음부터 감상 — 승인 여부와 무관하게 미리보기 가능, 최종 전달물엔 APPROVED 만

웹과 CLI 는 같은 파일을 읽고 쓰므로 언제든 혼용 가능하다.

# (대안) CLI 루프 — 명령어 자동화

## 핵심 원칙
한 번에 전체 작품을 생성하지 않는다. Scene 하나씩 통과시킨다.
장면 JSON 은 손으로 편집하지 않는다 — 상태 전이는 전부 `tools/advance_scene.py` 가 처리한다.
사람이 직접 하는 것은 세 가지뿐: **장면 계획 작성, 외부 AI에서 이미지 생성, 시사·선택**.

## 루프 상태
프로젝트 단계: `BRIEF` → `STORY` → `CAST`
장면 단계(status): `SCENE_PLAN` → `PROMPT` → `IMAGE` → `REVIEW_HUMAN` → `APPROVED`, 실패 시 `REVISE`
(REVIEW_AUTO 는 add-images 시 자동 실행되어 별도 상태로 머물지 않는다)
전체 마감: `DELIVER`

## 반복 1회 실행 순서 (Scene 1개)
```bash
# 1. 장면 생성 (scene_id·order 자동)
python tools/advance_scene.py new

# 2. project/scenes/SCENE-XXX.json 의 계획만 채운다
#    (purpose / action_beat / emotion / camera / dialogue / visual_style)

# 3~4. Grok 프롬프트 생성 — 모드 택1
#   [수동 모드 · 기본] SuperGrok 구독만으로:
python tools/make_grok_input.py SCENE-XXX          # 출력 통째로 grok.com 에 붙여넣기
python tools/advance_scene.py set-prompt SCENE-XXX --file grok_out.txt
#   [API 모드 · 선택] XAI_API_KEY 환경변수 설정 후 한 줄:
python tools/grok_api.py SCENE-XXX

# 5. 외부 이미지 AI에서 후보 1~4장 생성
#    ※ 캐릭터/장소 레퍼런스 이미지를 반드시 함께 첨부 (일관성 1차 수단)

# 6. 후보 등록 → 자동 검사 → PASS 시 상태 REVIEW_HUMAN 까지 자동
python tools/advance_scene.py add-images SCENE-XXX 다운로드1.png 다운로드2.png

# 7. 시사 후 1장 선택
python tools/advance_scene.py select SCENE-XXX 2

# 8. 승인 → 장면 잠금 (검사 FAIL 이면 자동 롤백)
python tools/advance_scene.py approve SCENE-XXX
```
실패 시: `python tools/advance_scene.py revise SCENE-XXX <SCENE_PLAN|PROMPT|IMAGE> --note "사유"`
진행 확인: `python tools/advance_scene.py status`

## 회귀 방지 규칙
- APPROVED Scene의 캐릭터/장소/소품 기준정보는 이후 장면 수정 때문에 변경하지 않는다.
- 기준정보 변경이 필요하면 version 을 올린 새 항목을 만든다. 예: `CHAR-001` version 2.
- revise 는 기존 이미지·프롬프트를 지우지 않고 장면 version 을 올린다.
- APPROVED 가 아닌 장면은 최종 출력에 포함하지 않는다.

## 승인 게이트
### Gate A — 이야기
스토리/장면 목적이 명확하고 사용자가 승인.
### Gate B — 비주얼 기준 (캐릭터 시트 의무)
주요 캐릭터마다 **3면도+표정 시트**를 먼저 생성·승인하고 매니페스트 `reference_images` 에 등록.
이후 모든 이미지 생성에서 이 레퍼런스를 외부 AI에 첨부한다. prompt_anchor 는 2차 보조 수단.
### Gate C — 콘티/구도
각 Scene의 행동과 카메라 설계가 승인.
### Gate D — 이미지
자동 검사 PASS + 사용자 시사 PASS (approve 명령이 강제).
### Gate E — 출력
비주얼 노벨 감상본과 인화본 샘플 검수.

## 파일럿 규칙
본편 확정 전, 실제 작품의 첫 3장면을 파일럿으로 돌려 레퍼런스 첨부 방식·화풍 프롬프트를 보정한 뒤 계속 진행한다.

## 기본 작업 단위
- 1회 작업: 1 Scene / 후보 1~4장 / 선택 1장
- APPROVED 이후 다음 Scene
