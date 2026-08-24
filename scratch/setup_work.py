"""샘플 작품 '비 그친 우산 가게' 세팅 — 스토리라인 저장 + 6장면 구성(수동 모드 대역).

manual 모드라 grok API 를 안 쓰고, 여기서 저자 역할로 SCENES_JSON 을 직접 넣어
vn_compose.compose_from_json 으로 장면 생성 + 검사기 통과까지 만든다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import vn_compose  # noqa: E402

A_HARAM = "17-year-old Korean girl, long black hair in a low ponytail, big round eyes, yellow raincoat"
A_SEO = "60-year-old Korean woman, short silver hair, round glasses, work apron"
A_SHOP = "cozy old umbrella repair shop, dozens of umbrellas hanging from a wooden ceiling, warm incandescent light"
A_ALLEY = "rain-soaked alley after the rain, puddles reflecting the sky, faint rainbow"
STYLE = "warm cel-shaded Korean webtoon, soft rainy-day palette, clean line art, portrait 2:3"

STORYLINE = (
    "비 오는 날 오후, 하람은 돌아가신 아버지가 남긴 부러진 파란 우산을 들고 오래된 우산 수선집을 찾는다. "
    "가게 주인 서씨 아주머니는 낡은 우산을 살피며 하람의 이야기를 듣는다. 하람은 비 오는 날마다 그 우산을 들고 "
    "자신을 마중 나오던 아버지를 떠올린다. 우산은 살이 여럿 부러져 고치기 어려워 보였지만, 서씨는 정성껏 살을 갈아 "
    "우산을 되살린다. 가게를 나서자 비가 막 그쳐 있고, 하람은 되살아난 파란 우산을 펴 든 채 옅은 무지개가 걸린 "
    "젖은 골목을 걷는다. 슬픔은 사라지지 않지만, 우산처럼 다시 펼 수 있음을 안고서."
)

SCENES = [
    {"order": 1, "purpose": "하람이 부러진 파란 우산을 수선집 카운터에 올리며 이야기가 시작된다",
     "action_beat": "젖은 노란 우비 차림으로 부러진 파란 우산을 카운터에 조심스레 올려놓는다",
     "emotion": "머뭇거림과 옅은 기대", "time": "비 오는 오후", "location_id": "LOC-001",
     "camera": {"shot": "medium shot", "angle": "eye level", "framing": "우측 인물, 좌측 카운터", "focus": "우산과 표정"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "저기… 이 우산, 고칠 수 있을까요?"}],
     "image_prompt": f"{STYLE}, medium shot, {A_HARAM}, placing an old broken blue umbrella on the counter of a {A_SHOP}, hesitant and hopeful"},

    {"order": 2, "purpose": "서씨가 우산을 살피고, 하람이 우산의 사연을 꺼낸다",
     "action_beat": "돋보기 안경 너머로 부러진 살을 짚어보고, 하람이 조심스레 말을 잇는다",
     "emotion": "잔잔한 온기", "time": "비 오는 오후", "location_id": "LOC-001",
     "camera": {"shot": "two shot", "angle": "eye level", "framing": "마주 선 두 인물", "focus": "우산을 든 손"},
     "dialogue": [{"speaker_id": "CHAR-002", "text": "허어… 오래 함께한 녀석이구나."},
                  {"speaker_id": "CHAR-001", "text": "아빠가 쓰시던 거예요. 이젠 제가 들고요."}],
     "image_prompt": f"{STYLE}, two shot, {A_SEO} and {A_HARAM}, examining a broken blue umbrella together in a {A_SHOP}, gentle warmth"},

    {"order": 3, "purpose": "하람이 아버지와의 비 오는 날 기억을 떠올린다(감정 절정 도입)",
     "action_beat": "빗소리에 잠겨 눈을 내리깔고 옛 기억을 더듬는다",
     "emotion": "그리움", "time": "비 오는 오후", "location_id": "LOC-001",
     "camera": {"shot": "close-up", "angle": "slightly high", "framing": "얼굴 클로즈업", "focus": "눈가"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "비 오는 날이면, 늘 이 우산을 들고 마중 나오셨어요."}],
     "image_prompt": f"{STYLE}, close-up, {A_HARAM}, eyes lowered remembering, rain streaks on the window of a {A_SHOP}, wistful"},

    {"order": 4, "purpose": "서씨가 부러진 살을 정성껏 갈아 우산을 되살린다",
     "action_beat": "작업대에서 우산살을 하나씩 갈고 맞춰 끼운다",
     "emotion": "묵묵한 정성", "time": "저녁 무렵", "location_id": "LOC-001",
     "camera": {"shot": "close-up", "angle": "top-down", "framing": "손과 우산살", "focus": "수리하는 손"},
     "dialogue": [{"speaker_id": "CHAR-002", "text": "살 몇 개만 갈면… 아직 멀쩡해. 우산도, 사람도."}],
     "image_prompt": f"{STYLE}, close-up of hands repairing umbrella ribs at a workbench, {A_SEO}, in a {A_SHOP}, focused and tender"},

    {"order": 5, "purpose": "가게를 나서니 비가 그쳐 있고, 하람이 되살아난 우산을 편다",
     "action_beat": "가게 문을 나서며 파란 우산을 활짝 펴 든다",
     "emotion": "옅은 놀라움과 후련함", "time": "비 그친 직후", "location_id": "LOC-002",
     "camera": {"shot": "wide shot", "angle": "eye level", "framing": "젖은 골목 속 인물", "focus": "펼친 파란 우산"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "…어느새 비가 그쳤네."}],
     "image_prompt": f"{STYLE}, wide shot, {A_HARAM}, opening a repaired blue umbrella just outside a shop, {A_ALLEY}, quiet relief"},

    {"order": 6, "purpose": "무지개가 걸린 젖은 골목을 걸으며 하람이 작별과 감사를 건넨다(엔딩)",
     "action_beat": "파란 우산을 든 채 옅은 미소로 골목을 걸어간다",
     "emotion": "벅찬 여운", "time": "비 그친 직후", "location_id": "LOC-002",
     "camera": {"shot": "medium wide", "angle": "low angle", "framing": "좌측 인물, 우측 무지개", "focus": "실루엣과 우산"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "고마워요, 아빠. 그리고… 아주머니도."}],
     "image_prompt": f"{STYLE}, medium wide low angle, {A_HARAM}, walking with the blue umbrella under a faint rainbow, {A_ALLEY}, hopeful afterglow"},
]


def main():
    story_dir = ROOT / "project" / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "storyline.md").write_text(STORYLINE, encoding="utf-8")
    print("스토리라인 저장 완료.")

    fenced = "```json\n" + json.dumps(SCENES, ensure_ascii=False) + "\n```"
    r = vn_compose.compose_from_json(fenced, force=True, expected=6)
    print(f"{len(r['created'])}개 장면 생성: {', '.join(r['created'])}")
    print("검사:", r["checker"])
    print("warning:", r.get("warning", "없음"))


if __name__ == "__main__":
    main()
