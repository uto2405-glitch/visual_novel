# 채점표 — AI 웹툰 제작 시스템 (v5, 승인)

## A. 자동 판정 항목 (`python tools/check_protocol.py` 가 [A1]~[A7] 라벨로 출력)
| # | 기준 (X하면 Y가 관찰된다) |
|---|---|
| A1 | `project/manifest.json` 과 장면 파일이 유효한 JSON 이고 필수 키를 갖추면 PASS. |
| A2 | 각 장면에 scene_id·scene_order·location_id·characters·dialogue·assets·review 가 있고 모든 ID 가 기준정보에 존재하면 PASS. 파일명과 scene_id 일치 포함. |
| A3 | 상태가 IMAGE 이상인 장면의 이미지가 존재하고, selected_image 의 긴 변이 `output.min_long_edge_px` 이상·허용 형식이면 PASS. 그 이전 상태는 검사 생략(SKIP). |
| A4 | 각 대사의 speaker_id 가 해당 장면의 등장 캐릭터 목록과 기준정보에 모두 존재하면 PASS. |
| A5 | scene_order 가 중복 없이 1부터 연속하면 PASS. |
| A6 | 상태가 IMAGE 이상(또는 프롬프트 작성 완료)인 장면의 grok_output 에 등장 캐릭터·장소의 prompt_anchor 가 포함되면 PASS. |
| A7 | review.auto / review.human 이 PENDING·PASS·REVISE·REGENERATE·FAIL 중 하나이고, APPROVED 장면은 둘 다 PASS 이면 PASS. |
| A8 | 저장소 텍스트 파일 어디에도 xAI API 키 패턴(`xai-…`)이 없으면 PASS. 발견 시 해당 키는 즉시 폐기·재발급. |

### 출력 기본 기준 (개인 소장 인화 용도)
- 기본 최소: 긴 변 1024px (매니페스트 `output.min_long_edge_px` 로 프로젝트별 조정)
- 참고: 10×15cm(4×6") 300dpi 인화 ≈ 긴 변 1800px — 큰 인화가 필요하면 프로젝트에서 상향
- 허용 형식: png / jpg / jpeg / tif / tiff / webp — 압축 손실이 적은 형식 우선 보존
- 기본 색상: RGB 원본 보존, 최종 인쇄 변환은 출력 장비/현상소 기준에 따름
- 출력 비율은 프로젝트별로 고정하고, 승인 이후 변경하지 않음

## B. 금지 조항
- Grok 결과만으로 이미지가 완성되었다고 간주하지 않는다. 외부 이미지 생성 단계를 반드시 거친다.
- 이미지 생성 프롬프트와 최종 이미지 파일의 대응 관계를 잃어버리지 않는다.
- Scene ID를 재사용하지 않는다.
- Character ID/Location ID/Prop ID를 장면마다 임의 변경하지 않는다.
- 검수 결과가 없는 장면은 최종 출력 대상으로 간주하지 않는다.
- 대사 원문을 이미지 생성 프롬프트에 합쳐서 이미지 속 글자로 직접 생성하는 것을 기본 경로로 사용하지 않는다.
- 채점 기준 파일과 검사기를 에이전트가 스스로 수정하여 PASS를 만들 수 있도록 하지 않는다. (개정은 CLAUDE.md "채점표·검사기 개정 절차"를 따른다)
- API 키를 저장소 파일에 기록하지 않는다. 키는 환경변수로만 주입하고, 서드파티 CLI/에이전트에 제공하지 않는다.
- 사용자 승인 없이 실제 제품 기능 구현으로 확장하지 않는다.

## C. 사람 시사 항목 (자동 판정 불가 — 사용자의 눈, review-report.json 의 human.checks 키와 1:1 대응)
| 검수 키 | 질문 |
|---|---|
| character_consistency | 캐릭터의 얼굴/표정/복장/분위기가 작품 전체에서 자연스럽게 이어지는가. |
| direction_flow | 장면 전환과 카메라 연출이 감정선을 강화하는가. |
| dialogue_naturalness | 대사가 실제 캐릭터의 입에서 나온 것처럼 느껴지는가. |
| visual_novel_immersion | 비주얼 노벨 방식으로 한 장면씩 봤을 때 몰입이 유지되는가. |
| print_quality | 실제 사진 출력물에서 피부/색/선명도/여백이 만족스러운가. |
| style_match | 전체 작품의 화풍이 사용자가 의도한 스타일과 일치하는가. |

## D. 굿하트 점검 (기준을 통과하며 의도를 배반하는 경로)
| 배반 경로 | 차단 조항 |
|---|---|
| 1. 이미지 파일은 고해상도지만 다른 캐릭터를 생성해 A3를 통과시킴 | C.character_consistency 에서 Character ID별 기준 이미지 대비 검수를 의무화한다. |
| 2. 대사/씬 메타데이터만 완벽하게 채워 실제 이미지는 저품질인데 구조 검사만 통과함 | A3와 C의 실제 출력 시사 없이는 최종 PASS를 허용하지 않는다 (A7이 APPROVED 조건을 강제). |
| 3. 장면마다 서로 다른 화풍/구도를 사용해 형식상 일관성을 만족시키지만 작품의 연출이 깨짐 | C.direction_flow / style_match 에 장면 연속성 검수를 명시하고, REVISE/REGENERATE 상태를 허용한다. |

## 개정 이력
- v1 (2026-08-24): 최초 승인
- v2 (2026-08-24): 스키마 통일(단일 매니페스트, ID 필드명 규약), 검사기 A1~A7 전체 구현, C 항목 검수 키 부여, 상태 기반 검사(SKIP) 도입 — 사용자 지시로 개정
- v3 (2026-08-24): 개인 소장 용도 확정에 따라 해상도 기준 완화(기본 1024px), 검사기 --scene 필터 추가, 자동화 도구(advance_scene / make_grok_input) 도입, Gate B 에 캐릭터 시트·레퍼런스 등록 의무화 — 사용자 지시로 개정
- v4 (2026-08-24): Grok 연동 이중 모드(수동 기본/API 선택) 도입, xAI API·SuperGrok 별도 결제 확인 반영, 키 보안 조항 및 A8 키 유출 스캔 추가, OAuth 우회 미채택 확정 — 사용자 지시로 개정
- v5 (2026-08-24): 웹 스튜디오(webapp.py) 도입 — 스토리 대화·장면 구성·이미지 등록·뷰어를 브라우저로 통합. 판정 기준(A1~A8, B, C)은 불변, 웹도 동일 스키마·검사기를 사용 — 사용자 워크플로우 확정에 따른 개정
- v5.1 (2026-08-24): 구현 보안·품질 개정(판정 기준 불변) — 프론트 분리(studio.html) 및 서버 데이터의 HTML 문자열 삽입 전면 금지(주입 구조적 차단), compose 공용 모듈화(vn_compose, 웹·CLI 동일 구현), xai_client 단일 호출 경로, WRITE_LOCK 직렬화, Host 헤더 검증, 채팅 전송창 제한, compose JSON 1회 자동 재시도, 자가진단 23종 확장
