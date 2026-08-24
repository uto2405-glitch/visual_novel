# 무료 에셋 소스 가이드 (한글)

이 프로젝트의 **그림은 외부 이미지 AI로 생성**하므로, 여기서 "에셋"은 주로
**배경 참고·BGM·효과음·폰트·UI·질감**을 말합니다. 아래는 **합법적으로 무료**인 소스만 모았습니다.

> ⚠️ 중요: "개인·비상업 용도"라도 **라이선스는 지켜야 합니다.** 그래서 아래를 **라이선스 등급**으로 나눴습니다.
> **CC0/퍼블릭도메인** = 출처표기도 필요 없이 무엇이든 자유. 이게 "마음껏 끌어다 쓰기"에 가장 안전한 바구니입니다.
> CC-BY 등은 무료지만 **출처(만든 사람) 표기**가 조건입니다 → `assets/CREDITS.md` 에 적어두면 됩니다.

---

## 1) CC0 / 퍼블릭도메인 — 출처표기 불필요, 자유 (권장)
| 소스 | 뭐가 있나 | 비고 |
|---|---|---|
| **Kenney** (kenney.nl) | 게임 UI·아이콘·효과음·2D/3D 에셋 | 전부 CC0. VN UI·버튼·SFX에 최적 |
| **OpenGameArt** (opengameart.org) | 배경·스프라이트·음악·SFX | 반드시 **License 필터를 CC0**로 |
| **Pixabay** (pixabay.com) | 사진·일러스트·영상·음악·SFX | Pixabay License = 출처표기 불필요, 상업까지 무료 |
| **Pexels** (pexels.com) | 사진·영상 | 무료, 출처표기 불필요 |
| **Unsplash** (unsplash.com) | 고해상 사진(배경 참고·질감) | Unsplash License |
| **Freesound** (freesound.org) | 효과음·앰비언스(빗소리 등) | **CC0 필터** 사용(일부는 CC-BY) |
| **unDraw** (undraw.co) | 벡터 일러스트 | 무료, 출처표기 불필요 |
| **SVG Repo** (svgrepo.com) | 아이콘·SVG | CC0 컬렉션 다수 |
| **Public Domain**: Wikimedia Commons, archive.org, Old Book Illustrations | 명화·고서 삽화·질감 | PD 표시 확인 |

## 2) 음악(BGM) — 대부분 CC-BY(출처표기 필요) 또는 CC0
| 소스 | 비고 |
|---|---|
| **Incompetech** (Kevin MacLeod) | CC-BY, 표기하면 무료. VN 분위기 곡 풍부 |
| **Free Music Archive** (freemusicarchive.org) | 라이선스별 필터 |
| **Pixabay Music / Bensound(무료 티어)** | 표기 불필요/필요 확인 |
| **YouTube 오디오 보관함** | 저작권 free 필터 |

## 3) 폰트 — SIL OFL / Apache (무료, 상업까지)
| 폰트 | 용도 |
|---|---|
| **Pretendard** | 본문 산세리프(이미 뷰어 기본) |
| **Noto Sans/Serif KR** (Google Fonts) | 범용 한글 |
| **나눔(Nanum) 계열** | 손글씨·명조 등 다양 |
| **Gowun Batang / Dodum** (Google Fonts) | 따뜻한 명조·산세(감성 VN) |

→ Google Fonts는 전부 OFL/Apache로 자유. 감상본 HTML에 서브셋 임베드하면 기기 무관 동일 조판.

## 4) VN 전용 에셋 팩
- **itch.io** → 태그 `visual novel assets` / `game assets` → **각 팩의 라이선스 개별 확인**(무료라도 조건 상이)
- **VNDB / Ren'Py 커뮤니티**의 free asset 목록
- 캐릭터 **스프라이트 베이스**(CC0)로 표정·포즈 변형 → 이 프로젝트에선 보통 AI 생성이 더 일관적

---

## 이 프로젝트에 붙이는 법
- **배경 참고 이미지**: Unsplash/Pixabay 사진을 이미지 AI에 레퍼런스로 첨부(화풍 통일에 도움).
- **효과음·BGM**: 지금은 오디오 레이어가 없지만, 추가하면 `assets/audio/` 에 CC0 파일을 두고 장면별로 연결(로드맵의 오디오 클러스터).
- **폰트**: 뷰어/감상본에 Google Fonts 임베드(자유).
- **UI 아이콘**: Kenney/SVG Repo(CC0).

## 출처 기록 (CC-BY 등 표기 조건일 때)
`assets/CREDITS.md` 를 만들어 아래처럼 적어두면 조건 충족 + 나중에 정리 편함:
```
- BGM "Rainy Day" — Kevin MacLeod (incompetech.com) — CC BY 4.0
- SFX 빗소리 — freesound user xxx — CC0
- 배경사진 — Unsplash / photographer name — Unsplash License
```

---
### 한 줄 요약
**CC0(Kenney·Pixabay·Freesound CC0·OpenGameArt CC0)** 를 기본으로 쓰면 출처표기 걱정 없이 자유롭게 끌어다 쓸 수 있고,
**CC-BY(Incompetech BGM 등)** 는 `assets/CREDITS.md` 한 줄이면 합법입니다. 비상업이라도 이 원칙만 지키면 안전합니다.
