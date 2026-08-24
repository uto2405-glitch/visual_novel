"""『이지혜와의 하루』 — 선형 감상형 로맨스 VN 세팅 (분기 없음, 쭉 감상).

6장면: 카페 만남 → 음료 → 벚꽃길 → 넘어질 뻔 잡아줌 → 노을 강변 → 여운 엔딩.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import vn_compose  # noqa: E402

JI = "18-year-old Korean girl, light brown semi-long hair in a half-up style, bright brown eyes, pastel knit cardigan, small star earrings"
ME = "18-year-old Korean boy, neat black hair, casual shirt"
CAFE = "cozy warm wood-toned cafe near a school, afternoon sunlight through the window"
PARK = "spring park path with cherry blossoms falling, soft pink petals in the air"
RIVER = "riverside walkway at sunset, orange and violet sky reflecting on the water"
STYLE = "bright cel-shaded Korean romance webtoon, soft warm palette, clean line art, portrait 2:3"

STORYLINE = (
    "'나'는 오후, 이지혜와 함께 하루를 보낸다. 학교 앞 카페에서 만나 음료를 나누고, 벚꽃 공원을 걷다가 "
    "지혜가 넘어질 뻔한 걸 붙잡아 준다. 노을 지는 강변에 다다랐을 때, 두 사람 사이의 마음이 조용히 가까워진다. "
    "선택 없이 쭉 감상하는 잔잔한 로맨스."
)

SCENES = [
    {"order": 1, "purpose": "카페에서 이지혜와 만나 하루가 시작된다", "action_beat": "창가에서 지혜가 밝게 손을 흔든다",
     "emotion": "설렘", "time": "오후", "location_id": "LOC-001",
     "camera": {"shot": "medium", "angle": "eye level", "framing": "창가 지혜", "focus": "지혜의 미소"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "여기야 여기~ 오래 기다렸어?"},
                  {"speaker_id": "CHAR-002", "text": "(오늘 하루, 오래 기억에 남을 것 같아.)"}],
     "image_prompt": f"{STYLE}, medium shot, {JI}, waving brightly at a window seat in a {CAFE}, seen over the shoulder of {ME}"},

    {"order": 2, "purpose": "마주 앉아 음료를 나누며 이야기한다", "action_beat": "따뜻한 음료를 사이에 두고 웃는다",
     "emotion": "포근함", "time": "오후", "location_id": "LOC-001",
     "camera": {"shot": "two shot", "angle": "eye level", "framing": "마주 앉은 둘", "focus": "웃는 표정"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "네가 골라준 딸기라떼, 역시 맛있다."},
                  {"speaker_id": "CHAR-002", "text": "취향 기억하고 있었거든."}],
     "image_prompt": f"{STYLE}, two shot, {JI} and {ME}, sharing warm drinks across a table in a {CAFE}"},

    {"order": 3, "purpose": "벚꽃 공원을 나란히 걷는다", "action_beat": "흩날리는 벚꽃 아래를 걷는다",
     "emotion": "설렘과 평온", "time": "오후", "location_id": "LOC-002",
     "camera": {"shot": "wide", "angle": "eye level", "framing": "벚꽃길의 두 사람", "focus": "나란한 실루엣"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "벚꽃 진짜 예쁘다… 같이 오길 잘했어."}],
     "image_prompt": f"{STYLE}, wide shot, {JI} and {ME}, walking side by side on a {PARK}"},

    {"order": 4, "purpose": "지혜가 넘어질 뻔한 걸 붙잡아 준다", "action_beat": "휘청이는 지혜의 팔을 재빨리 받쳐 준다",
     "emotion": "두근거림", "time": "오후", "location_id": "LOC-002",
     "camera": {"shot": "medium", "angle": "eye level", "framing": "맞닿은 두 사람", "focus": "붙잡은 손"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "앗-! …고마워. 놀랐잖아."},
                  {"speaker_id": "CHAR-002", "text": "(가까워진 거리에, 심장이 빨라진다.)"}],
     "image_prompt": f"{STYLE}, medium shot, {ME} catching {JI} by the arm as she stumbles on a {PARK}, petals swirling"},

    {"order": 5, "purpose": "노을 강변에서 조용히 마음이 가까워진다", "action_beat": "노을을 나란히 바라본다",
     "emotion": "잔잔한 두근거림", "time": "해질녘", "location_id": "LOC-003",
     "camera": {"shot": "two shot", "angle": "eye level", "framing": "노을 속 둘", "focus": "마주보는 눈"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "오늘… 참 좋았다. 그치?"},
                  {"speaker_id": "CHAR-002", "text": "응. 다음에도, 또 같이 오자."}],
     "image_prompt": f"{STYLE}, two shot, {JI} and {ME}, standing close watching the sunset on a {RIVER}"},

    {"order": 6, "purpose": "여운을 남기며 하루가 저문다 (엔딩)", "action_beat": "지혜가 환하게 웃으며 손을 내민다",
     "emotion": "따뜻한 여운", "time": "해질녘", "location_id": "LOC-003",
     "camera": {"shot": "close-up", "angle": "eye level", "framing": "내민 손과 미소", "focus": "지혜의 미소"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "그럼… 갈까? 같이."},
                  {"speaker_id": "CHAR-002", "text": "(이 하루가, 시작이었으면 좋겠다.)"}],
     "image_prompt": f"{STYLE}, close-up, {JI} reaching out her hand with a bright warm smile toward {ME} on a {RIVER}"},
]


def main():
    story_dir = ROOT / "project" / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "storyline.md").write_text(STORYLINE, encoding="utf-8")
    fenced = "```json\n" + json.dumps(SCENES, ensure_ascii=False) + "\n```"
    r = vn_compose.compose_from_json(fenced, force=True, expected=6)
    print(f"{len(r['created'])}개 장면: {', '.join(r['created'])}")
    print("검사:", r["checker"])


if __name__ == "__main__":
    main()
