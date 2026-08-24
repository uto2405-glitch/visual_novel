# 프로토콜 상태 — AI 웹툰 제작 시스템 (이력 보관용)

> ## 📌 이 문서는 v5 이전 이력 보관용이다
> **현재 상태·다음 할 일의 단일 출처는 [NO_TOKEN_TASKS.md](../NO_TOKEN_TASKS.md)** 이고,
> 항목 정의는 [BACKLOG.md](../BACKLOG.md), 현행 엔진 구성은
> [README.md](../README.md) · [CLAUDE.md](../CLAUDE.md) 에 있다.
>
> 아래 "완료됨 / 단계 이력 / 열린 질문" 은 **2026-08-24 시점의 기록을 그대로 둔 것**이라
> 지금 구성과 다르다. 특히 **오케스트레이터는 그록(API)이 아니라 로컬 LLM 이다**
> (`mode: local` · `model: local-qwen`), 이미지 생성은 MakeFun 이고, 그록은 예비 경로다.
> 그록 관련 기록(크레딧 충전·`grok-4.6` 기입 등)은 **당시 이력이지 현재 지시가 아니다.**

최종 갱신: 2026-08-25 (이력 보관 배너 + 액션 아이템 현행화)

## 목적 (확정문)
LLM 오케스트레이터가 스토리를 씬·행동 비트·장면으로 분해하고, 각 장면의 연출/구도와 외부 상용 이미지 AI용 프롬프트를 생성한다. 생성된 이미지는 캐릭터·배경·소품의 일관성과 인쇄 품질을 검수한 뒤 대사/말풍선과 함께 비주얼 노벨처럼 한 장면씩 감상할 수 있는 결과물로 구성한다. 최종 산출물은 디지털 감상용 장면 묶음과 실제 사진 출력에 적합한 고해상도 이미지다.
(확정 당시 오케스트레이터는 Grok 이었고, 2026-08 에 로컬 LLM 으로 교체됐다. 역할 정의는 그대로다.)

## 현재 위치
- 단계: 3 완료 + v2 정비 완료 → 이후 진행은 NO_TOKEN_TASKS.md
- 상태: 첫 작품 투입 대기 (`project/` 는 데모 데이터)

## 사용자 액션 아이템 (사람만 할 수 있는 것)
- [ ] **인화 해상도 상향** — 4×6 1800px · 5×7 2250px · 8×10 3600px.
      매니페스트 `output.min_long_edge_px` **와** `image_generator.max_long_edge_px`(기본 2048)를
      **함께** 올린다. 한쪽만 올리면 요청이 2048 로 깎여 A3 가 FAIL 한다
      (→ [docs/PRINT_ORDER_GUIDE.md](../docs/PRINT_ORDER_GUIDE.md) §1).
      확인: `python tools/print_preflight.py` · `python tools/makefun_client.py --check`
- [ ] Gate B: 캐릭터 시트(3면도+표정) 생성·승인 → 매니페스트 `reference_images` 등록
- [ ] 웹 스튜디오로 첫 작품: 스토리라인 → 장면 구성 → 파일럿 3장면 보정
- [ ] 승인 컷이 쌓이면 이미지 포함 백업을 습관화
      (`python tools/backup_project.py snapshot --with-images --dest D:/backup`)

> 그록 API 크레딧 충전은 **더 이상 필수가 아니다** — 예비 경로가 필요해질 때만 한다.
> 이미지 공급자(MakeFun)는 이미 매니페스트 `image_generator` 에 기입돼 있다.

### 완료됨 (2026-08-24 시점 기록 — 이후 이력은 NO_TOKEN_TASKS.md)
- [x] v5.6 대규모 개선 라운드 + 울트라 검증: webapp POST_ROUTES 라우팅 리팩토링(404/비-dict 400/10MB 상한), 신규 도구 scene_lint(연출 리듬 자문, /api/lint)·backup_project(sha256 스냅/verify), 뷰어 회상 갤러리+즐겨찾기·백로그 영속화·시네마틱 모드·엔딩 크레딧·2모드 nav·그록 한글 프롬프트 틀 7종. 울트라 검증(5렌즈+비평가) 확정 9건 수정 — 디스패처 SystemExit 포착, state 관용 로더(손상 장면 스킵), 린터 방탄화, playFrom scene_id화. selftest 43종. GitHub 3커밋 푸시 (2026-08-24)
- [x] v5.5 인화 파이프라인 + 모바일 + 적대적 리뷰: **인화 마스터 익스포트**(tools/print_export.py — Pillow, 목표 규격 300DPI cover-크롭·LANCZOS·블리드·sRGB TIFF/JPEG + spec_sheet + 컨택트시트) + /api/export + 장면탭 UI. 4렌즈 적대적 리뷰로 확정 결함 수정(최대규격 면적기준 오보고·parse_size 음수/0·scene_id 경로탈출·eff_dpi_src 정의·0px 가드·표시/판정 일치). **스튜디오+데모 모바일 반응형**(nav 가로바·세로스택·터치타깃·뷰어 컨트롤 wrap·iOS 확대방지). selftest 39종 (2026-08-24)
- [x] v5.4 VN 뷰어 전문가 채점(6.17/10)·개선 + 인화 프리플라이트: 뷰어 P0/P1(긴대사 클램프·한국어 조판·포커스 트랩·이름표 대비·onerror·skip-미열람·글자크기·aria) 반영, 회상/장면점프/UI숨김/전체화면/스와이프 포함. tools/print_preflight.py(규격별 DPI/크롭 판정) + /api/preflight + 카드 배지. VN 데모 아티팩트(📻). (2026-08-24)
- [x] v5.2 수동 모드 웹 통합 + 적대적 감사: 장면 탭에 grok.com 복붙 경로(compose-input/compose-manual/grok-input/set-prompt) 추가, 6렌즈 감사로 21건 CONFIRMED, 편집가능 결함 15종 수정(critical 키유출 리다이렉트 포함) + 회귀 T26~T34, selftest 37건. check_protocol 제안 9종은 protocol/AUDIT-2026-08-24.md 에 기록(수정 금지라 보고만) (2026-08-24)
- [x] console.x.ai API 키 발급·검증 및 서버 주입 — 인증 통과 확인, 크레딧 충전만 남음 (2026-08-24)
- [x] docs.x.ai 모델 확인 → manifest `orchestrator.api.model` = `grok-4.6`, mode = `api` (project+templates, 2026-08-24)
- [x] 자동화 프로토콜 발동 (2026-08-24)
- [x] 0단계 번역 인터뷰 및 목적 확정 (2026-08-24)
- [x] 1단계 채점표 승인 (2026-08-24)
- [x] 2단계 인프라 승인 (2026-08-24)
- [x] 3단계 작업 루프 초안 구현 (2026-08-24)
- [x] 3단계 루프 승인 (2026-08-24)
- [x] v2 정비: 스키마 통일·검사기 A1~A7 구현·문서 정합화 (2026-08-24)
- [x] v3 자동화: advance_scene / make_grok_input 도구, --scene 검사, 캐릭터 시트 게이트, 해상도 기준 개인용 완화 (2026-08-24)
- [x] v4 Grok 연동: 수동/API 이중 모드, grok_api.py(키는 환경변수 전용), A8 키 유출 스캔, OAuth 우회 미채택 결정 (2026-08-24)
- [x] v4.1 견고성: 원자적 저장(tmp+rename), 자가진단 13종(selftest.py) 동봉, advance_scene argparse 전환, set-prompt 로직 단일화(apply_prompt), 비UTF-8 콘솔 방어 (2026-08-24)
- [x] v5 웹 스튜디오: 사용자 확정 5단계 워크플로우 구현 — 스토리(Grok 채팅)·장면 구성·폴더 등록/선택/승인·VN 뷰어를 로컬 웹으로 통합, 자가진단 19종으로 확장(모의 xAI 서버 포함) (2026-08-24)
- [x] v5.1 점검·보완: 주입 구조적 차단(DOM 전용 렌더링)+회귀 감시, 모듈 분리(studio.html/vn_compose/xai_client), 쓰기 락, Host 검증, 채팅 윈도우, JSON 재시도, 병렬·주입·Host·CLI공유 테스트 포함 자가진단 23종 (2026-08-24)

## 단계 이력
- [x] 0단계 번역 인터뷰 — 2026-08-24
- [x] 1단계 채점표 승인 — 2026-08-24
- [x] 2단계 인프라 승인 — 2026-08-24
- [x] 3단계 루프 승인 — 2026-08-24
- [x] v2 정비 — 2026-08-24

## 채점표 개정 이력
- v1 (2026-08-24): 최초 승인
- v2 (2026-08-24): 스키마 통일·검사기 구현·C 항목 키 부여

## 열린 질문 / 보류 결정 (당시 기록 · 괄호는 이후 결과)
- 외부 상용 이미지 생성 AI: 사용자 보유 제품 있음(정보 제공 대기). Grok은 오케스트레이션 및 프롬프트 설계 역할로 고정.
  → **해소**: 이미지 = MakeFun AI, 오케스트레이터 = 로컬 LLM(llama.cpp). 그록은 예비.
- 출력 용도: 개인 소장 인화로 확정(출간 아님). 인화 크기는 작품별 지정, 기본 기준 긴 변 1024px. → 유효.
- Grok 연동: 수동 모드로 확정 시작(SuperGrok 구독, 비용 0). API 모드 스크립트(grok_api.py)는 준비 완료.
  → 두 경로 모두 **예비**로 남아 있다. 상시 경로는 로컬 LLM.
- SuperGrok OAuth 우회 경로는 403 불안정으로 채택하지 않음 (기록). → 유효(금지 유지).
- 디지털 감상용 런타임(HTML/영상/앱)은 추후 선택.
  → **해소**: 단일 HTML 감상본(`export_viewer`) · PWA(`export_pwa`) · 인화 마스터(`print_export`).
