#!/usr/bin/env python3
"""스토리라인 → 장면 자동 구성 — 웹 스튜디오와 CLI 가 공유하는 단일 구현.

CLI 사용법:
  python tools/vn_compose.py 10               # 장면 10개 구성
  python tools/vn_compose.py 10 --force       # 기존 장면 백업 후 재구성
  python tools/vn_compose.py 10 --branching   # 선택지·분기 형식까지 요청(기본은 선형)

입력:  project/story/storyline.md
출력:  project/scenes/SCENE-XXX.json (상태 PROMPT, 이미지 프롬프트에 앵커 포함)
백업:  backups/scenes_backup_<시각>/ (--force 재구성 시, 최신 5벌만 보존)

장면을 만드는 경로는 두 갈래이고 둘 다 여기 있다(웹 라우트에는 도메인 로직을 두지 않는다):
  compose_scenes / compose_from_json   스토리라인 → 장면 N개
  scene_from_talk                      인물과 나눈 대화 → 장면 1개 + 이미지 프롬프트

다만 **장면 파일을 만드는 일 자체는 여기 없다** — 템플릿 적재·번호 확정·화 승계·존재
확인·저장은 scene_ops.create_scene 하나가 한다. 이 파일이 하는 일은 모델의 자유 형식
출력을 저장소 규약의 필드로 번역하는 것까지다(build_scene).

분기 지시문은 **manifest.dating 의 눈금 위에서** 만들어진다. 호감도 범위와 branch.min
예시를 리터럴로 박아 두면(예전의 -2~2 · min:3) start_affection 이 30 인 작품에서는
두 번째 엔딩에 영영 도달하지 못한다 — 눈금은 작품마다 다르므로 매번 계산한다.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_llm  # noqa: E402
import prompt_build  # noqa: E402  (이미지 프롬프트 조립 — 대화→장면 경로가 바로 이어 쓴다)
import scene_ops  # noqa: E402   (장면 상태 전이의 유일한 구현)
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

ROOT = vn_core.ROOT
MANIFEST = vn_core.MANIFEST
STORY_DIR = vn_core.STORY
BACKUPS = vn_core.BACKUPS
COMPOSE_MARK = "SCENES_JSON_ONLY"

MAX_SCENES = 50        # 1회 구성 상한 — 통제 없는 호출 확대와 대량 파일 생성을 막는다
BACKUP_KEEP = 5        # scenes_backup_* 보존 벌 수
# 화풍 문구의 단일 출처는 vn_core 다(프롬프트 조립·웹 생성과 같은 문구여야 컷 화풍이 안 흔들린다).
DEFAULT_VISUAL_STYLE = vn_core.DEFAULT_VISUAL_STYLE
# 호감도 기본 눈금의 정본은 **배포 기본 매니페스트**다(린터 scene_lint 도 같은 파일을 읽는다).
# 예전에는 30/100 리터럴이 여기와 린터에 한 벌씩 있었다 — 작품이 눈금을 바꾸면 한쪽만 옛
# 값으로 계산해서, 실제로 닿는 분기를 린터가 '도달 불가'라고 불렀다.
DEFAULT_DATING_SOURCE = vn_core.TEMPLATES / "manifest.json"
FALLBACK_AFF_MAX = 100   # 그 파일에도 dating 이 없을 때만 쓰는 마지막 그물(지시문에는 숫자가 필요하다)


# 저장소 전역 쓰기 잠금 — 정본은 vn_core 하나다(RLock 이라 scene_ops 안에서 겹쳐 잡아도 안전).
WRITE_LOCK = vn_core.WRITE_LOCK


# 모델이 배열에 씌우는 이름들 — {"scenes":[...]} 처럼 한 겹 포장해서 주는 경우가 잦다.
_WRAP_KEYS = ("scenes", "items", "data", "result", "list", "장면")
# 장면 원소를 알아보는 열쇠. 대사 원소({speaker_id,text})와 갈라내는 것이 유일한 목적이라
# 두 개만 맞으면 장면으로 본다(모델이 한두 칸을 빠뜨려도 원소 자체는 알아봐야 한다).
_SCENE_KEYS = ("order", "purpose", "action_beat", "emotion", "time",
               "location_id", "camera", "dialogue", "image_prompt")


def _json_values(body: str) -> list:
    """텍스트에 흩어진 **최상위** JSON 값을 나온 순서대로 모두 꺼낸다.

    예전에는 ``find("[")`` 와 ``rfind("]")`` 로 잘랐다. 그 방식은 모델이 배열로 감싸지
    않고 객체를 줄줄이 흘렸을 때 **첫 객체 안의 ``"dialogue": [...]`` 를 배열로 착각**한다 —
    그리고 그 조각이 문법적으로 온전하면 파싱이 **성공한다**. 실측(Qwen3.6-35B-A3B)에서
    대사 두 줄이 장면 두 개로 저장됐고, 화면에는 "2개 장면 생성 · 검사 통과" 만 떴다.
    터지는 것보다 나쁜 고장이라 자르는 방식 자체를 바꾼다: ``raw_decode`` 는 값 하나를
    끝까지 소비하므로 안쪽 배열이 후보로 올라올 길이 없다.
    """
    dec = json.JSONDecoder()
    out, i, n = [], 0, len(body)
    while i < n:
        if body[i] not in "[{":
            i += 1
            continue
        try:
            val, end = dec.raw_decode(body, i)
        except ValueError:
            i += 1          # 여는 괄호처럼 생긴 산문 — 다음 후보로 넘어간다
            continue
        out.append(val)
        i = end
    return out


def _looks_like_scene(v) -> bool:
    """이 객체가 장면 원소인가 — 포장 객체·대사 원소와 구별하는 최소 판정."""
    return isinstance(v, dict) and sum(1 for k in _SCENE_KEYS if k in v) >= 2


def _extract_json_array(text: str):
    """LLM 응답 → 장면 원소 리스트. **배열로 오지 않아도 알아본다.**

    지시문이 "다른 말 없이 JSON 배열만" 이라고 못박아도 실제로 오는 모양은 세 가지다
    — ``[...]`` 배열 · ``{"scenes":[...]}`` 포장 · **배열 없이 객체만 줄줄이**. 같은 지시문
    7회에서 각각 3 · 2 · 2 였다. 셋을 모두 받는다. 형식을 고쳐 달라고 다시 부르는 것은 이
    모델에서 100초짜리 재시도라, 받을 수 있는 모양을 넓히는 쪽이 사람의 시간을 아낀다.
    """
    body = re.sub(r"```(?:json)?", "", str(text)).strip()
    vals = _json_values(body)
    if not vals:
        raise ValueError("JSON 배열 없음")
    for v in vals:                                   # ① 진짜 배열
        if isinstance(v, list):
            return v
    for v in vals:                                   # ② 한 겹 포장된 배열
        if isinstance(v, dict) and not _looks_like_scene(v):
            for k in _WRAP_KEYS:
                if isinstance(v.get(k), list):
                    return v[k]
            lists = [x for x in v.values() if isinstance(x, list)]
            if len(lists) == 1:                      # 이름이 무엇이든 배열이 하나뿐이면 그것
                return lists[0]
    scenes = [v for v in vals if _looks_like_scene(v)]   # ③ 배열 없이 객체만 줄줄이
    if scenes:
        return scenes
    raise ValueError("JSON 배열 없음")


def extract_json_object(text: str) -> dict:
    """LLM 응답 → 최상위 JSON 객체 하나. 코드펜스·앞뒤 잡담을 걷어낸다.

    (장면 1개를 받는 경로의 단일 구현 — 배열을 받는 _extract_json_array 와 짝이다.)
    """
    body = re.sub(r"```(?:json)?", "", str(text)).strip()
    s_i, e_i = body.find("{"), body.rfind("}")
    if s_i < 0 or e_i <= s_i:
        raise VNError("장면 JSON 을 찾지 못했습니다. 대화를 조금 더 이어간 뒤 다시 시도하세요.")
    try:
        d = json.loads(body[s_i:e_i + 1])
    except ValueError as exc:
        raise VNError(f"장면 JSON 해석 실패({exc}). 다시 시도해 주세요.")
    if not isinstance(d, dict):
        raise VNError("장면 JSON 최상위가 객체가 아닙니다.")
    return d


def _as_order(v, fallback: int) -> int:
    """정수로 안전 변환 — 문자열/누락/타입혼합이 sorted() 나 계산을 크래시시키지 않게 한다."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return fallback


# 화 번호·엔딩 표기 규칙의 정본은 vn_core 하나다 — 여기서는 이름만 이어 준다.
# (예전에는 같은 규칙이 감상본·장면 구성·스튜디오에 각각 적혀 주석으로만 동기화됐고,
#  실제로 엔딩 이름과 화 번호가 화면마다 갈렸다. 이제 갈릴 자리가 없다.)
norm_episode = vn_core.norm_episode   # 값 → 양의 정수 또는 None
ending_of = vn_core.ending_of         # 장면 → (엔딩인가, 엔딩 이름)
last_episode = vn_core.last_episode   # 디스크의 마지막 장면이 물려주는 화 번호


def _first_episode(mf: dict) -> int:
    """매니페스트가 정의한 첫 화 번호. 화를 정의하지 않은 작품이면 0(=화 표기 없음).

    화가 없는 작품에 임의로 1화를 붙이지 않는다 — 없는 정보를 만들어 내지 않는 쪽이
    감상본의 화 목록을 거짓으로 채우는 것보다 낫다.
    """
    nums = [norm_episode(e.get("episode")) for e in (mf.get("episodes") or [])
            if isinstance(e, dict)]
    nums = [n for n in nums if n]
    return min(nums) if nums else 0


def _dating_scale(mf: dict) -> dict:
    """이 작품의 호감도 눈금 → 지시문에 쓸 {start, max, step, good_min}.

    step  : 선택지 하나가 움직일 수 있는 최대 폭
    good_min: '좋은 결말' 분기의 문턱 예시 — 시작값에서 한 걸음이면 닿는 높이로 잡는다.

    작품이 눈금을 말하지 않으면 **배포 기본 매니페스트**(templates/manifest.json)를 읽는다.
    린터(scene_lint._affection_scale)도 같은 파일을 보므로, 지시문이 만든 min 과 린터가
    '도달 불가'로 경고하는 문턱이 같은 눈금 위에 놓인다. 예전에는 양쪽이 30/100 리터럴을
    각자 들고 있어서, 눈금을 바꾼 작품에서 방금 만든 분기를 린터가 죽은 분기라고 불렀다.
    """
    d = mf.get("dating") if isinstance(mf.get("dating"), dict) else {}
    base = vn_core.load_json_safe(DEFAULT_DATING_SOURCE, {})
    t = base.get("dating") if isinstance(base.get("dating"), dict) else {}
    top = _as_order(d.get("max", t.get("max")), 0) or _as_order(t.get("max"), 0)
    if top < 2:
        top = FALLBACK_AFF_MAX          # 어떤 매니페스트에도 눈금이 없을 때의 마지막 그물
    start = max(0, min(top, _as_order(d.get("start_affection", t.get("start_affection")), 0)))
    unit = max(1, round(top / 20))
    return {"start": start, "max": top, "step": unit * 2,
            "good_min": min(top, start + unit)}


def _episode_block(mf: dict) -> str:
    """작품이 화로 나뉘어 있으면 각 장면에 episode 를 달게 한다(감상본의 화 선택)."""
    eps = [e for e in (mf.get("episodes") or []) if isinstance(e, dict)
           and norm_episode(e.get("episode"))]
    if not eps:
        return ""
    lines = "\n".join(f"- {norm_episode(e.get('episode'))}화: {str(e.get('title') or '').strip()}"
                      f"{(' — ' + str(e.get('note')).strip()) if e.get('note') else ''}"
                      for e in eps)
    return f"""
[화(episode) 구분]
이 작품은 아래 화로 나뉜다. 각 장면 원소에 "episode": <번호> 를 넣어 어느 화인지 밝혀라.
{lines}
"""


def build_compose_instruction(count: int, branching: bool = False) -> str:
    """스토리라인 → 장면 분해 지시문을 조립한다. (API 호출용·수동 복붙용 공용)

    branching=True 면 선택지/분기 출력 형식을 추가로 요청한다(기본은 선형 작품).
    분기 수치는 manifest.dating 의 눈금에서 계산한다.
    """
    if not isinstance(count, int) or count < 1:
        raise VNError("장면 수는 1 이상의 정수여야 합니다.")
    if count > MAX_SCENES:
        raise VNError(f"장면 수는 한 번에 최대 {MAX_SCENES}개입니다(요청 {count}개). "
                      "나눠서 구성하세요.")
    storyline = ""
    if (STORY_DIR / "storyline.md").exists():
        storyline = (STORY_DIR / "storyline.md").read_text(encoding="utf-8").strip()
    if not storyline:
        raise VNError("스토리라인이 비어 있습니다. 스토리 탭(또는 project/story/storyline.md)에서 먼저 저장하세요.")

    mf = vn_core.load_json_safe(MANIFEST, {})
    if not mf:
        raise VNError("project/manifest.json 이 없거나 읽을 수 없습니다. 작품 설정을 먼저 저장하세요.")
    chars, locs = mf.get("characters", []), mf.get("locations", [])
    # 말투 규칙을 함께 싣는다. 대화 탭은 이미 같은 칸(profile.speech_style)을 읽어 페르소나를
    # 만드는데 장면 구성만 그것을 몰라서, 반말로 말하는 인물이 새 장면에서 "고마워요" 라고
    # 존댓말을 썼다(실측). 같은 작품의 기존 12장과 새로 만든 3장이 말투부터 갈린다.
    char_block = "\n".join(
        f"- {c.get('character_id')} {c.get('name','')}: anchor=\"{c.get('prompt_anchor','')}\""
        + (f"\n  말투: {str((c.get('profile') or {}).get('speech_style','')).strip()}"
           if str((c.get('profile') or {}).get('speech_style', '')).strip() else "")
        for c in chars)
    loc_block = "\n".join(f"- {l.get('location_id')} {l.get('name','')}: anchor=\"{l.get('prompt_anchor','')}\"" for l in locs)
    style = vn_core.visual_style(mf)
    shot_vocab = " / ".join(vn_core.STD_SHOTS)      # 어휘 정본은 vn_core(린터도 같은 목록을 본다)
    angle_vocab = " / ".join(vn_core.STD_ANGLES)
    aff = _dating_scale(mf)
    # 분기는 요청할 때만 — 기본 지시문은 선형 작품이 깨끗하게 나오도록 분기 필드를 금지한다.
    branch_block = f"""
[분기 출력 형식 (선택 필드)]
필요한 장면에만 아래 필드를 추가하라. 넣지 않으면 그 장면은 선형으로 진행된다.
 "choices":[{{"text":"같이 걷자고 한다","affection":{aff['step']},"goto":"SCENE-005"}}],
 "branch":[{{"min":{aff['good_min']},"goto":"SCENE-009"}},{{"min":0,"goto":"SCENE-010"}}],
 "ending":true, "ending_label":"호감 엔딩"
- 이 작품의 호감도는 {aff['start']} 에서 시작하고 최대 {aff['max']} 까지 오른다.
  branch 의 min 은 **이 눈금 위의 절대값**이지 선택지 합계가 아니다.
- choices 는 2~3개, text 는 한국어 한 줄(20자 내외). affection 은 -{aff['step']}~{aff['step']} 정수.
- min 은 반드시 도달 가능해야 한다 — 시작값 {aff['start']} 에 그 장면까지의 선택지 최대 합계를
  더해도 넘지 못하는 min 은 아무도 갈 수 없는 죽은 분기다. 좋은 결말은 min {aff['good_min']} 안팎,
  마지막 항목은 min 0 (어떤 경우에도 걸리는 폴백)으로 둘 것.
- goto 는 이 배열 안에 있는 order 를 가리키는 SCENE-XXX 형식(order N → SCENE-{{N:03d}} 규칙).
- branch 는 호감도가 min 이상인 **첫** 항목으로 이동하므로 min 이 큰 것을 먼저 쓸 것(내림차순).
- ending:true 는 이야기가 끝나는 장면에만 (분기당 1개). 갈라진 경로마다 각자 ending 을 둘 것 —
  한쪽에 ending 이 없으면 그 경로가 다른 쪽 엔딩으로 흘러 들어가 두 결말이 하나로 붙는다.
- ending_label 은 그 결말의 이름이다(한국어 8자 내외: "호감 엔딩" / "엇갈린 결말").
  감상본 엔딩 카드와 스튜디오 장면 목록이 이 이름을 그대로 보여 주므로, 결말마다 다르게 붙일 것.
- 분기는 전체의 20% 이하 장면에만 넣고, 갈라진 길은 다시 합류시키거나 엔딩으로 닫을 것.
""" if branching else """
[분기]
이 작품은 선형이다. choices / branch / ending 필드는 넣지 말 것.
"""

    return f"""너는 비주얼 노벨 연출가다. 아래 스토리라인을 정확히 {count}개 장면으로 분해하라.

[스토리라인]
{storyline}

[캐릭터 (speaker_id 는 반드시 이 목록의 id)]
{char_block}

[장소]
{loc_block}

[규칙]
1. image_prompt 는 영어. 등장 캐릭터와 장소의 anchor 문구를 원문 그대로 포함할 것.
2. image_prompt 는 화풍 문구로 시작할 것: "{style}"
3. 이미지 안에 글자/말풍선이 생기지 않도록 image_prompt 에 텍스트 요소를 넣지 말 것.
4. dialogue 는 한국어, 장면당 1~4줄. 한 줄은 60자 이내. **위에 적힌 각 인물의 말투를 지킬 것**
   (반말인 인물에게 존댓말을 쓰지 말 것 — 기존 장면과 말투가 갈린다).
5. location_id 는 장소 목록의 id 중 하나.
6. 그 장면 dialogue 에 등장하지 않는 인물의 anchor 는 image_prompt 에 넣지 말 것
   (등장 인물은 dialogue 화자로 정해진다. 말없이 함께 있는 인물은 짧은 대사를 1줄 주어라).

[연출 규칙]
1. 같은 camera.shot 을 3장면 연속 쓰지 말 것 — wide / medium / close-up 을 교차할 것.
2. 첫 장면은 wide 계열로 상황을 열고, 감정이 가장 높은 장면에는 close-up 을 최소 1컷 둘 것.
3. 같은 emotion 을 3장면 연속 쓰지 말 것. 전체 감정선에 하강(망설임·아쉬움·불안)을 최소 1번 넣고 다시 올릴 것.
4. 같은 location_id 가 5장면 이상 연속되지 않게 장소나 앵글을 바꿀 것.
5. camera.shot / camera.angle 은 아래 표준 어휘에서만 고를 것(표기까지 그대로).
   shot : {shot_vocab}
   angle: {angle_vocab}
6. time 과 image_prompt 의 시간대 표현을 일치시킬 것
   (time 이 '밤'이면 image_prompt 에 sunset·afternoon 같은 다른 시간대 표현을 쓰지 말 것).
{_episode_block(mf)}{branch_block}
[출력 형식 — {COMPOSE_MARK}]
다른 말 없이 JSON 배열만 출력하라. 각 원소:
{{"order":1,"purpose":"...","action_beat":"...","emotion":"...","time":"...",
 "location_id":"LOC-001",
 "camera":{{"shot":"...","angle":"...","framing":"...","focus":"..."}},
 "dialogue":[{{"speaker_id":"CHAR-001","text":"..."}}],
 "image_prompt":"..."}}"""


def norm_choices(v) -> list:
    """선택지 정규화 — [{text, affection(int), goto(scene_id)}]. (연애 시뮬 등 분기용)"""
    out = []
    for c in v if isinstance(v, list) else []:
        if isinstance(c, dict) and str(c.get("text", "")).strip():
            out.append({"text": str(c["text"]), "affection": _as_order(c.get("affection", 0), 0),
                        "goto": str(c.get("goto", ""))})
    return out


def norm_branch(v) -> list:
    """호감도 분기 정규화 — [{min(int), goto(scene_id)}]. 첫 조건 만족으로 이동."""
    out = []
    for b in v if isinstance(v, list) else []:
        if isinstance(b, dict) and str(b.get("goto", "")).strip():
            out.append({"min": _as_order(b.get("min", 0), 0), "goto": str(b["goto"])})
    return out


def build_scene(it: dict, index: int, char_ids: list, loc_ids: set, locs: list,
                episode=None) -> dict:
    """LLM 이 준 장면 원소 1개 → **scene_ops.create_scene 에 넘길 필드 dict**.

    어떤 필드가 잘못된 타입이어도 기본값으로 흡수한다(원소 하나가 구성 전체를 깨지 않는다).
    여기가 하는 일은 '모델의 자유 형식 → 저장소 규약'의 번역뿐이다 — 템플릿 적재·번호
    확정·존재 확인·저장은 하지 않는다. 그 다섯은 장면 생성의 유일한 구현(scene_ops.
    create_scene)이 한다. 예전에는 이 함수가 템플릿까지 읽어 완성된 장면 dict 를 만들고
    호출부가 직접 저장해서, 저장소에 장면을 만드는 코드가 세 벌이었다.

    scene_id·scene_order 도 함께 담지만 **최종 판정은 create_scene** 이다(빈 폴더에
    순서대로 저장하므로 결과는 같고, 손상 파일이 낀 경우에는 그쪽이 더 안전하다).

    episode: 이어받을 화 번호. 원소가 스스로 episode 를 말하면 그쪽이 우선이다.
             None 이면 디스크의 마지막 장면에서 승계한다(웹의 '장면 하나 추가' 경로).
             0 은 '화 표기 없음' — 재구성 중이라 디스크를 보면 안 될 때 쓴다.
    """
    f: dict = {"scene_id": f"SCENE-{index:03d}", "scene_order": index, "status": "PROMPT"}
    loc = it.get("location_id")
    f["location_id"] = loc if loc in loc_ids else ((locs[0].get("location_id") or "") if locs else "")
    dialogue, speakers = [], []
    for d in (it.get("dialogue") if isinstance(it.get("dialogue"), list) else []):
        if not isinstance(d, dict):
            continue
        spk = d.get("speaker_id") if d.get("speaker_id") in char_ids else (char_ids[0] if char_ids else "")
        dialogue.append({"speaker_id": spk, "text": str(d.get("text", "")), "placement": "bottom"})
        if spk and spk not in speakers:
            speakers.append(spk)
    if dialogue:
        f["dialogue"] = dialogue      # 비면 키를 두지 않는다 → 템플릿의 빈 대사 한 줄이 남는다
    f["characters"] = speakers or (char_ids[:1] if char_ids else [])
    for k in ("purpose", "action_beat", "emotion", "time"):
        f[k] = str(it.get(k, ""))
    cam = it.get("camera") if isinstance(it.get("camera"), dict) else {}
    f["camera"] = {k: str(cam.get(k, "")) for k in ("shot", "angle", "framing", "focus")}
    f["prompt"] = {"grok_output": str(it.get("image_prompt", ""))}
    ep = norm_episode(it.get("episode"))
    if ep is None:
        ep = norm_episode(episode) if episode is not None else last_episode()
    if ep is not None:
        f["episode"] = ep
    # 분기 엔진(선택) — 있을 때만 실어 나른다(선형 작품은 깨끗하게 유지). 검사기는 이 필드를 무시.
    ch = norm_choices(it.get("choices"))
    if ch:
        f["choices"] = ch
    br = norm_branch(it.get("branch"))
    if br:
        f["branch"] = br
    is_end, label = ending_of(it)
    if is_end:
        f["ending"] = True             # 규약: 참/거짓만. 결말의 이름은 ending_label 로.
        if label:
            f["ending_label"] = label
    return f


def _unique_dir(parent: Path, name: str) -> Path:
    dest, n = parent / name, 2
    while dest.exists():
        dest = parent / f"{name}_{n}"
        n += 1
    return dest


def migrate_legacy_backups() -> list[str]:
    """과거 project/scenes_backup_* 을 backups/ 로 이관 — project/ 에는 작품 데이터만 남긴다.

    이관 실패(파일 잠금 등)는 건너뛴다: 백업 이사 때문에 재구성이 막히면 안 된다.
    """
    legacy = sorted(d for d in vn_core.PROJECT.glob("scenes_backup_*") if d.is_dir())
    if not legacy:
        return []
    BACKUPS.mkdir(parents=True, exist_ok=True)
    moved = []
    for d in legacy:
        dest = _unique_dir(BACKUPS, d.name)
        try:
            shutil.move(str(d), str(dest))  # 같은 드라이브면 rename, 아니면 복사 후 삭제
        except (OSError, shutil.Error):
            continue
        moved.append(dest.name)
    return moved


def prune_backups(keep: int = BACKUP_KEEP) -> list[str]:
    """scenes_backup_* 을 최신 keep 벌만 남기고 정리(이름이 시각이라 이름순=시간순)."""
    keep = max(1, int(keep))
    if not BACKUPS.exists():
        return []
    dirs = sorted((d for d in BACKUPS.glob("scenes_backup_*") if d.is_dir()), key=lambda p: p.name)
    removed = []
    for d in dirs[:max(0, len(dirs) - keep)]:
        try:
            shutil.rmtree(d)
        except OSError:
            continue
        removed.append(d.name)
    return removed


_EXISTS_MSG = "이미 장면이 있습니다. '기존 장면 백업 후 재구성'(--force) 으로 다시 실행하세요."


def _create_scenes_from_items(items, force: bool, expected: int | None = None) -> dict:
    """파싱된 장면 배열 → SCENE-XXX.json 생성 + 자동 검사. (API·수동 공용)

    원자성: 모든 장면을 먼저 메모리에서 구성·검증한 뒤 WRITE_LOCK 안에서 일괄 저장한다.
    **기존 장면 조회와 force 가드도 그 잠금 안에서** 다시 한다 — 두 요청이 동시에 들어와도
    한쪽이 다른 쪽이 막 만든 장면을 백업 없이 덮어쓰는 창(TOCTOU)이 남지 않는다.
    기존 장면은 force 일 때만 고유 백업 폴더로 옮긴다. 어떤 원소가 스키마를 위반해도
    개별 필드는 기본값으로 흡수되어 중간 크래시로 프로젝트가 반쯤 구성되는 일이 없다.
    """
    if not isinstance(items, list) or not items:
        raise VNError("장면 배열이 비어 있거나 형식이 올바르지 않습니다.")
    if not force and vn_core.scene_files():
        raise VNError(_EXISTS_MSG)          # 값싼 선차단 — 확정 판정은 잠금 안에서 다시 한다

    mf = vn_core.load_json_safe(MANIFEST, {})
    chars, locs = mf.get("characters", []), mf.get("locations", [])
    char_ids = [c.get("character_id") for c in chars]
    loc_ids = {l.get("location_id") for l in locs}

    # 1) 전부 메모리에서 구성 (디스크 변경 전에 완료 — 여기서 실패하면 기존 장면 불변)
    dict_items = [it for it in items if isinstance(it, dict)]
    if not dict_items:
        raise VNError("붙여넣은 JSON 배열의 원소가 모두 객체({...})가 아닙니다.")
    if len(dict_items) > MAX_SCENES:
        raise VNError(f"장면이 {len(dict_items)}개입니다 — 한 번에 최대 {MAX_SCENES}개까지 "
                      "구성할 수 있습니다. 나눠서 진행하세요.")
    ordered = sorted(enumerate(dict_items), key=lambda p: _as_order(p[1].get("order"), p[0]))
    built, prev_ep = [], _first_episode(mf)      # 화 승계: 원소가 말하지 않으면 앞 장면을 따른다
    fixed_anchors: list[str] = []
    for i, (_, it) in enumerate(ordered, 1):
        sc = build_scene(it, i, char_ids, loc_ids, locs, episode=prev_ep)
        # 앵커 보정 — 붙여넣기 경로가 이미 하던 일을 자동 경로도 한다.
        # 지시문 1번은 "앵커 문구를 원문 그대로 포함하라" 지만 실측에서 장면 3개 중 2개가
        # 앵커 **중간에 말을 끼워 넣어**("...Korean girl holding hands with boy, light brown...")
        # 검사기 A6 를 떨어뜨렸다. 그대로 저장하면 방금 만든 작품이 저장소의 게이트에서
        # 빨간불이고, 사람은 장면마다 손으로 프롬프트를 고쳐야 한다 — 스튜디오의 [프롬프트
        # 저장]은 '앵커 자동 보정' 이 기본으로 켜져 있는데 자동 경로만 그 보정을 건너뛰었다.
        text = str(sc.get("prompt", {}).get("grok_output", "") or "")
        if text:
            text, touched = scene_ops.fix_anchor_text(sc, text)
            if touched:
                sc["prompt"]["grok_output"] = text
                fixed_anchors.append(sc["scene_id"])
        prev_ep = norm_episode(sc.get("episode")) or prev_ep
        built.append(sc)

    # 2) WRITE_LOCK 안에서 재확인 + 백업 + 일괄 저장
    created, backup, pruned = [], None, []
    with WRITE_LOCK:
        existing = vn_core.scene_files()   # 손상 파일도 포함 — 백업에서 빠지면 그대로 사라진다
        if existing and not force:
            raise VNError(_EXISTS_MSG)
        if existing:  # force 확정 — 덮어쓰지 않고 backups/ 아래 고유 폴더로 이동
            migrate_legacy_backups()  # 과거 project/ 잔재부터 이사시킨 뒤 새 백업을 쌓는다
            BACKUPS.mkdir(parents=True, exist_ok=True)
            backup = _unique_dir(BACKUPS, f"scenes_backup_{datetime.now():%Y%m%d_%H%M%S}")
            backup.mkdir(parents=True)
            for f in existing:
                f.rename(backup / f.name)
            pruned = prune_backups()
        for f in built:
            # 저장은 장면 생성의 유일한 구현에 맡긴다 — 존재 확인(덮어쓰기 금지)과 정규화가
            # 여기서도 그대로 걸린다. 화는 위에서 계산한 값을 명시적으로 넘겨, 재구성 중에
            # 디스크에 남은 장면에서 엉뚱하게 승계하지 않게 한다.
            sc = scene_ops.create_scene(f["scene_id"], fields=f, episode=f.get("episode"))
            created.append(sc["scene_id"])

    code, chk = vn_core.run_checker()
    result = {"created": created, "checker_pass": code == 0,
              "checker": "\n".join(l for l in chk.splitlines() if "FAIL" in l) or "자동 검사 통과"}
    if fixed_anchors:
        result["fixed_anchors"] = fixed_anchors
    if backup is not None:
        result["backup"] = backup.relative_to(ROOT).as_posix()
        if pruned:
            result["pruned"] = pruned
    if expected is not None and len(created) != expected:
        result["warning"] = f"요청 {expected}개 / 생성 {len(created)}개 — 개수가 일치하지 않습니다."
    return result


def _orch_local() -> bool:
    """오케스트레이터 모드 — manifest.orchestrator.mode 가 local 이면 로컬 LLM 사용."""
    mf = vn_core.load_json_safe(MANIFEST, {})
    orch = mf.get("orchestrator") if isinstance(mf.get("orchestrator"), dict) else {}
    return str(orch.get("mode", "")) == "local"


def orch_chat(messages: list, temperature: float = 0.6, max_tokens: int = 8192,
              on_token=None) -> str:
    """장면 구성용 LLM 호출 — 오케스트레이터는 로컬 LLM 하나뿐이다.

    예전에는 mode 가 local 이 아니면 외부 API 클라이언트로 넘어갔다. 그 경로는 은퇴했으므로
    **여기서 멈추고 사람이 실제로 쓸 수 있는 경로를 이름으로 말한다.** 그냥 지우면 예전
    매니페스트(mode:"api")를 그대로 쓰는 프로젝트가 NameError 역추적을 보게 되고, 웹에서는
    그것이 500 이 된다 — 무엇을 해야 하는지는 한 글자도 나오지 않는다.

    **스트리밍으로 받는다.** 이유는 속도가 아니라 시간제한이다: 비스트리밍이면 서버는
    답을 다 만들 때까지 한 바이트도 보내지 않으므로 첫 recv 가 생성 시간 전체를 기다리고,
    ``local_llm.TIMEOUT``(120초)이 그대로 총 시간 상한이 된다. 실측(Qwen3.6-35B-A3B,
    노트북, 13~14 tok/s)에서 장면 3개가 이미 95~115초라 **기본값 10개는 언제나 시간초과**였다.
    스트리밍이면 조각이 ~75ms 마다 오므로 그 상한은 '조각 사이의 침묵' 상한이 되고,
    진짜로 멈춘 서버는 여전히 120초에 걸린다 — 숫자를 키우지 않고 고친다.
    (on_token 을 주면 그 조각을 그대로 흘려 준다. 지금 호출부는 쓰지 않는다.)
    """
    if not _orch_local():
        raise VNError('오케스트레이터가 로컬 LLM 이 아닙니다(manifest.orchestrator.mode). '
                      '원격 API 경로는 더 이상 없습니다 — mode 를 "local" 로 두거나 '
                      '직접 입력(붙여넣기) 경로를 쓰세요.')
    return local_llm.chat(messages, temperature=temperature, max_tokens=max_tokens,
                          on_token=on_token or (lambda _piece: None))


def _scene_count(items) -> int:
    return sum(1 for it in items if isinstance(it, dict))


def compose_scenes(count: int, force: bool, branching: bool = False) -> dict:
    """스토리라인 → 장면 자동 구성 (로컬 LLM). 직접 입력 경로는 compose_from_json 사용.

    재시도가 걸리는 조건이 둘이다: **파싱 실패**와 **개수 불일치**. 두 번째가 뒤늦게
    추가된 이유는 실측이다 — 3개를 시켰는데 1개만 돌려주는 일이 일곱 번 중 한 번 있었다.
    개수가 어긋난 채로 그냥 저장하면 force 재구성에서 12장짜리 앨범이 1장으로 갈리고,
    화면에는 "1개 장면 생성 · 검사 통과" 만 뜬다(자동 경로는 warning 을 보여 주지도
    않았다). 백업은 남지만 사람은 무엇이 잘못됐는지 모른다. 그래서 **디스크를 건드리기
    전에** 한 번 더 묻고, 그래도 어긋나면 숫자를 말하며 멈춘다.
    """
    if not force and vn_core.scene_files():
        raise VNError(_EXISTS_MSG)          # 호출 낭비 방지 — 미리 막는다
    instruction = build_compose_instruction(count, branching)
    out = orch_chat([{"role": "user", "content": instruction}], temperature=0.6)
    try:
        items = _extract_json_array(out)
    except (ValueError, json.JSONDecodeError):
        items = None
    if items is None or _scene_count(items) != count:
        got = "없음" if items is None else f"{_scene_count(items)}개"
        # 1회 재시도: 무엇이 틀렸는지 숫자로 말한다(형식 교정 + 개수 교정 공용).
        retry = orch_chat([
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": out},
            {"role": "user", "content": f"장면이 정확히 {count}개여야 하는데 {got}이다. "
                                        f"빠진 장면을 채워 {count}개짜리 JSON 배열 하나만, "
                                        "다른 텍스트 없이 다시 출력하라."},
        ], temperature=0.2)
        try:
            items = _extract_json_array(retry)
        except (ValueError, json.JSONDecodeError):
            raise VNError("장면 JSON 파싱 실패 — 스토리라인을 조금 더 구체화해 다시 시도하세요. "
                          "또는 [✍ 직접 입력]에서 지시문을 복사해 쓰세요.")
    got = _scene_count(items)
    if got != count:
        raise VNError(f"모델이 {count}개 중 {got}개만 돌려줬습니다 — 장면을 바꾸지 않았습니다. "
                      "다시 시도하거나, [✍ 직접 입력]에서 지시문을 복사해 받은 JSON 을 "
                      "붙여넣으세요(개수를 눈으로 확인할 수 있습니다).")
    return _create_scenes_from_items(items, force, expected=count)


class _ComposeStop(Exception):
    """사람이 멈춤을 눌렀다 — 스트림 한가운데서 빠져나오기 위한 신호.

    배치 경계에서만 보면 3장면 배치가 끝날 때까지 최대 100초를 더 기다려야 한다.
    장면이 하나 완성될 때마다 보면 그 대기가 30초로 줄고, 이미 받은 장면은 그대로 남는다.
    """


class _SceneStream:
    """흐르는 글자에서 **장면 하나가 끝나는 순간**을 잡아낸다.

    왜 필요한가: 배치가 다 올 때까지 기다리면 첫 보상이 100초 뒤다. 실측에서 3장면 배치가
    95~118초인데 그 사이 화면에는 아무것도 없었다. 장면 1개는 약 30초이므로, 경계를 잡으면
    첫 보상이 30초로 당겨진다 — 기다림이 불안에서 기대로 바뀌는 지점이 거기다.

    방법은 단순하다. 중괄호 깊이를 세다가 최상위 객체가 닫히면 그 조각만 파싱해 본다.
    문자열 안의 괄호와 이스케이프를 건너뛰므로 대사에 '{' 가 들어 있어도 어긋나지 않는다.
    실패하면 그냥 넘긴다 — 최종 파싱은 _extract_json_array 가 전문을 놓고 다시 한다.
    """

    def __init__(self, on_scene):
        self.on_scene = on_scene
        self.buf: list[str] = []
        self.depth = 0
        self.start = -1
        self.in_str = False
        self.esc = False

    def feed(self, piece: str) -> None:
        for ch in str(piece or ""):
            self.buf.append(ch)
            i = len(self.buf) - 1
            if self.in_str:
                if self.esc:
                    self.esc = False
                elif ch == "\\":
                    self.esc = True
                elif ch == '"':
                    self.in_str = False
                continue
            if ch == '"':
                self.in_str = True
            elif ch == "{":
                if self.depth == 0:
                    self.start = i
                self.depth += 1
            elif ch == "}":
                if self.depth > 0:
                    self.depth -= 1
                    if self.depth == 0 and self.start >= 0:
                        self._try("".join(self.buf[self.start:i + 1]))
                        self.start = -1

    def _try(self, chunk: str) -> None:
        try:
            obj = json.loads(chunk)
        except ValueError:
            return
        if _looks_like_scene(obj):
            try:
                self.on_scene(obj)
            except _ComposeStop:
                raise                 # 멈춤은 신호다 — 삼키면 멈출 수 없다
            except Exception:
                pass      # 화면 갱신 실패가 조립을 멈추게 두지 않는다


def compose_batch(total: int, branching: bool, start: int, end: int,
                  made: list | None = None, on_scene=None) -> str:
    """장면 구성을 **구간으로 나눠** 한 번 부른다 → 모델의 원문 응답 그대로.

    왜 나누는가: 장면 1개에 약 30초다(실측 12~14 tok/s). 10개를 한 번에 시키면 254초가
    걸리고 출력이 4천 토큰을 넘는다. 3개씩이면 95~115초·1천여 토큰이라 양쪽 다 여유가 있다.

    왜 /api/chat 을 쓰지 않는가 — 두 가지가 조용히 망가진다:
      * 그 경로는 max_tokens=1000 으로 묶여 있다(webapp.do_chat). 장면 3개는 그보다 크고,
        넘치면 배열이 중간에서 잘린 채 200 으로 온다. 사용자에게는 "읽지 못했습니다" 로만
        보이고 원인이 보이지 않는다.
      * 그 경로는 주고받은 것을 스토리 챗로그에 병합 저장한다. 조립 지시문은 수천 자라,
        사용자가 쓰던 대화창이 기계용 지시문으로 뒤덮인다.
    그래서 여기서 직접 부른다. 저장은 하지 않는다 — 이 함수는 글자만 돌려준다.

    made 는 앞 구간에서 이미 만든 장면 요약([{order, purpose}, …])이다. 이게 없으면 매 구간이
    이야기를 처음부터 다시 시작해 도입부만 여러 벌 나온다.
    """
    if not isinstance(total, int) or total < 1:
        raise VNError("전체 장면 수는 1 이상의 정수여야 합니다.")
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        raise VNError(f"구간이 올바르지 않습니다: {start}~{end}")
    if end > total:
        raise VNError(f"구간 끝({end})이 전체({total})보다 큽니다.")

    want = end - start + 1
    lines = [build_compose_instruction(total, branching), "", "[이번 요청]",
             f"전체 {total}개 장면 중 {start}번째부터 {end}번째까지, {want}개만 출력하라.",
             f"order 에는 전체 기준 번호({start}~{end})를 그대로 넣어라. 1 부터 다시 세지 마라.",
             f"{want}개보다 많이도 적게도 쓰지 마라."]
    prev = [m for m in (made or []) if isinstance(m, dict)]
    if prev:
        lines += ["", "[앞 구간에서 이미 만든 장면 — 이어서 쓰되 같은 장면을 다시 쓰지 마라]"]
        for m in prev[-24:]:          # 앞이 길어져도 지시문이 무한정 커지지 않게 최근 것만
            order = m.get("order")
            purpose = str(m.get("purpose") or "").strip().replace("\n", " ")[:80]
            lines.append(f"  {order if order is not None else '?'}. {purpose}")
    stream = _SceneStream(on_scene) if on_scene else None
    return orch_chat([{"role": "user", "content": "\n".join(lines)}], temperature=0.6,
                     on_token=(stream.feed if stream else None))


# ---------------------------------------------------------------- 서버가 들고 도는 조립
# 조립이 브라우저 안에서 돌면 탭을 닫거나 폰을 잠그는 순간 7분짜리 작업이 죽는다.
# 이 프로젝트에서 "맡겨 두고 자리를 뜬다"를 물리적으로 가능하게 하는 유일한 변경이라
# 작업을 서버로 내린다. 모델이 --parallel 1 이라 동시에 돌 수 있는 조립은 하나뿐이고,
# 그래서 슬롯도 하나면 충분하다(장면별로 나뉘는 gen_jobs 와 다른 점).
_JOB_LOCK = threading.Lock()
_JOB: dict = {"running": False}


def _job_snapshot() -> dict:
    with _JOB_LOCK:
        return dict(_JOB)


def compose_job_status() -> dict:
    """조립 진행 → {running, total, batch, done, scenes, message, error, raw, finished_at}.

    scenes 는 지금까지 받아 둔 장면의 요약이다(order·purpose). 화면은 이걸 폴링해서
    **장면이 도착하는 대로** 한 줄씩 보여 준다 — 배치가 다 모일 때까지 기다리지 않는다.
    """
    job = _job_snapshot()
    items = job.get("items") or []
    return {
        "running": bool(job.get("running")),
        "total": int(job.get("total") or 0),
        "batch": int(job.get("batch") or 0),
        "done": len(items),
        "scenes": [{"order": it.get("order"), "purpose": str(it.get("purpose") or "")[:80]}
                   for it in items],
        "message": str(job.get("message") or ""),
        "error": str(job.get("error") or ""),
        "raw": str(job.get("raw") or ""),
        "failed_from": job.get("failed_from"),
        "failed_to": job.get("failed_to"),
        "finished_at": job.get("finished_at"),
        "cancelled": bool(job.get("cancelled")),
    }


def compose_job_items() -> list:
    """지금까지 받아 둔 장면 원본(저장에 쓴다)."""
    return list(_job_snapshot().get("items") or [])


def compose_job_save(force: bool = False) -> dict:
    """모아 둔 장면을 저장하고 작업을 비운다 — **한 번만** 일어나게 묶어서 한다.

    따로 두면 두 가지가 깨진다.
      * 아직 돌고 있는 작업에 저장이 끼어들면, 반쯤 모인 장면이 디스크에 박히고 그 뒤
        끝난 본 작업은 "이미 장면이 있습니다" 로 영영 저장하지 못한다.
      * 화면 두 개(폰·PC)가 같은 2.5초 안에 끝을 보면 둘 다 저장을 부른다. 둘째는
        같은 이유로 실패 문구를 띄우는데, 사실 저장은 성공한 상태다 — 그 문구를 읽고
        --force 로 다시 구성하면 방금 저장한 앨범이 백업으로 밀려난다.
    그래서 '누가 저장할 자격이 있나' 를 잠금 안에서 한 번에 정한다.
    """
    with _JOB_LOCK:
        if _JOB.get("running"):
            raise VNError("조립이 아직 돌고 있습니다 — 끝나면 저장됩니다.")
        items = [dict(it) for it in (_JOB.get("items") or []) if isinstance(it, dict)]
        if not items:
            raise VNError("저장할 장면이 없습니다. 이미 저장되었을 수 있습니다.")
        total = int(_JOB.get("total") or 0)
        _JOB["items"] = []          # 자격을 여기서 가져간다 — 둘째 요청은 위에서 걸린다
        _JOB["message"] = "저장 중…"
    try:
        for i, it in enumerate(items):
            it["order"] = i + 1     # 배치마다 1부터 다시 세는 일이 흔하다
        res = compose_from_json(json.dumps(items, ensure_ascii=False), force,
                                expected=total or len(items))
    except Exception:
        with _JOB_LOCK:             # 실패하면 자격을 돌려준다 — 다시 누를 수 있어야 한다
            if not _JOB.get("items"):
                _JOB["items"] = items
                _JOB["message"] = ""
        raise
    with _JOB_LOCK:
        _JOB.clear()
        _JOB["running"] = False
    return res


def compose_job_cancel() -> dict:
    """지금 배치가 끝나면 멈춘다. 받아 둔 장면은 그대로 둔다(버리지 않는다)."""
    with _JOB_LOCK:
        if _JOB.get("running"):
            _JOB["cancel"] = True
            _JOB["message"] = "이번 구간이 끝나면 멈춥니다…"
    return compose_job_status()


def compose_job_clear() -> dict:
    """끝난 작업의 흔적을 지운다(저장을 마친 뒤 부른다)."""
    with _JOB_LOCK:
        if _JOB.get("running"):
            raise VNError("조립이 아직 돌고 있습니다.")
        _JOB.clear()
        _JOB["running"] = False
    return compose_job_status()


def _compose_worker(total: int, batch: int, branching: bool) -> None:
    """배치를 돌며 장면을 모은다. 실패해도 **이미 받은 것은 버리지 않는다.**"""
    try:
        # 이어받기: 이미 들고 있는 장면 다음부터 시작한다. 1 로 고정하면 [이어서 다시] 가
        # 이미 받은 구간을 다시 굽고(장면당 30초) 그 사이 사본이 하나뿐인 장면들이 날아간다.
        with _JOB_LOCK:
            start = len(_JOB.get("items") or []) + 1
        while start <= total:
            with _JOB_LOCK:
                if _JOB.get("cancel"):
                    _JOB["message"] = "멈췄습니다. 받아 둔 장면은 그대로 있습니다."
                    _JOB["cancelled"] = True
                    break
                made = list(_JOB.get("items") or [])
            end = min(start + batch - 1, total)
            with _JOB_LOCK:
                _JOB["message"] = f"장면 {start}~{end} 현상 중…"
            seen: list = []

            def _arrived(obj, _seen=seen):
                # 장면 하나가 끝난 이 순간이 배치 안에서 멈출 수 있는 유일한 자리다.
                with _JOB_LOCK:
                    if _JOB.get("cancel"):
                        raise _ComposeStop()
                """장면 하나가 완성되는 즉시 화면이 볼 수 있게 올린다.

                최종 목록은 배치가 끝난 뒤 _extract_json_array 가 다시 만든다 — 여기서
                올리는 것은 '도착했다'는 신호이고, 아래에서 정본으로 교체된다.
                """
                _seen.append(obj)
                with _JOB_LOCK:
                    got = list(_JOB.get("items") or [])
                    _JOB["items"] = got + [obj]
                    _JOB["message"] = f"{len(got) + 1}컷째 나오는 중…"

            try:
                raw = compose_batch(total, branching, start, end,
                                    [{"order": m.get("order"), "purpose": m.get("purpose")}
                                     for m in made],
                                    on_scene=_arrived)
            except _ComposeStop:              # 사람이 멈췄다 — 지금까지 받은 것은 그대로 둔다
                with _JOB_LOCK:
                    kept = len(_JOB.get("items") or [])
                    _JOB["cancelled"] = True
                    _JOB["message"] = f"멈췄습니다. 받아 둔 {kept}개는 그대로 있습니다."
                break
            except Exception as exc:          # 모델·네트워크 실패 — 받은 것은 지키고 멈춘다
                with _JOB_LOCK:
                    _JOB["error"] = str(exc)
                    _JOB["failed_from"], _JOB["failed_to"] = start, end
                    _JOB["message"] = ""
                break
            if local_llm.TRUNCATED_MARK in (raw or ""):
                # 끊긴 응답은 성공으로 치지 않는다. 앞부분이 문법적으로 온전하면
                # 파싱이 '성공' 해 버려서, 모자란 장면이 조용히 빈자리로 남는다.
                with _JOB_LOCK:
                    _JOB["error"] = ("답이 중간에서 끊겼습니다(연결). 받은 데까지는 그대로 두고 멈춥니다.")
                    _JOB["raw"] = raw
                    _JOB["failed_from"], _JOB["failed_to"] = start, end
                    _JOB["message"] = ""
                break
            try:
                items = _extract_json_array(raw)
            except (ValueError, json.JSONDecodeError):
                items = None
            if not items:
                with _JOB_LOCK:
                    _JOB["error"] = (f"장면 {start}~{end} 는 형식을 못 맞췄습니다. "
                                     "모델 쪽 문제이고, 같은 지시문으로 7번 중 4번은 이렇게 됩니다.")
                    _JOB["raw"] = raw
                    _JOB["failed_from"], _JOB["failed_to"] = start, end
                    _JOB["message"] = ""
                break
            fresh = [it for it in items if isinstance(it, dict)]
            want = end - start + 1
            with _JOB_LOCK:
                # 스트림으로 미리 올린 것을 걷어내고 정본(파싱 결과)으로 갈아 끼운다.
                # 미리 올리는 목적은 도착을 빨리 보여 주는 것이지 저장이 아니다.
                got = list(_JOB.get("items") or [])
                if seen:
                    got = got[:max(0, len(got) - len(seen))]
                got.extend(fresh)
                _JOB["items"] = got
                _JOB["message"] = f"장면 {start}~{end} 나왔습니다 — 지금까지 {len(got)}개"

            if len(fresh) < want:
                # 개수가 모자란 채로 다음 구간으로 넘어가면 그 자리가 영영 빈다 — 다음
                # 구간의 '앞에서 만든 것' 요약이 이미 채워진 것처럼 말하기 때문이다.
                # 저장까지 가면 번호가 1..N 으로 다시 매겨져 구멍의 흔적도 사라진다.
                with _JOB_LOCK:
                    _JOB["error"] = (f"장면 {start}~{end} 를 {want}개 시켰는데 {len(fresh)}개만 왔습니다. "
                                     "모자란 자리를 비워 둔 채로 넘어가지 않고 여기서 멈춥니다.")
                    _JOB["raw"] = raw
                    _JOB["failed_from"], _JOB["failed_to"] = start + len(fresh), end
                    _JOB["message"] = ""
                break
            start = end + 1
        else:
            with _JOB_LOCK:
                _JOB["message"] = f"{len(_JOB.get('items') or [])}개를 다 받았습니다."
    finally:
        with _JOB_LOCK:
            _JOB["running"] = False
            _JOB["finished_at"] = int(time.time())


def compose_job_start(total: int, batch: int = 3, branching: bool = False,
                      resume: bool = False) -> dict:
    """조립을 서버에서 시작한다. 화면을 닫아도 계속 돈다.

    resume=True 면 **이미 받아 둔 장면을 지우지 않고 그 다음부터** 이어서 받는다.
    이 갈래가 없던 동안 화면의 [이어서 다시] 버튼은 _JOB.clear() 를 거쳐 1번 장면부터
    다시 시작했다 — 화면은 "버리지 않았습니다" 라고 적어 두고 실제로는 버렸고, 남은
    유일한 사본이던 그 장면들이 사라졌다. 라벨이 하는 약속을 코드가 지키게 한다.
    """
    total = max(1, min(int(total or 1), MAX_SCENES))
    batch = max(1, min(int(batch or 3), 6))
    if vn_core.scene_files():
        raise VNError(_EXISTS_MSG)
    with _JOB_LOCK:
        if _JOB.get("running"):
            raise VNError("이미 조립이 돌고 있습니다 — 진행 상황을 확인하세요.")
        kept = list(_JOB.get("items") or []) if resume else []
        if not resume and _JOB.get("items"):
            # 새로 시작하는데 받아 둔 것이 있으면 조용히 지우지 않는다. 지우는 것이
            # 맞는 경우라도 사람이 알고 지워야 한다.
            raise VNError(f"받아 둔 장면 {len(_JOB['items'])}개가 아직 있습니다 — "
                          "먼저 저장하거나 [받은 것 버리기] 로 비운 뒤에 새로 시작하세요.")
        _JOB.clear()
        _JOB.update({"running": True, "total": total, "batch": batch, "items": kept,
                     "message": ("이어서 받습니다…" if kept else "조립을 시작합니다…"),
                     "started_at": int(time.time())})
    threading.Thread(target=_compose_worker, args=(total, batch, branching),
                     daemon=True).start()
    return compose_job_status()


def compose_job_discard() -> dict:
    """받아 둔 장면을 버린다 — 사람이 명시적으로 눌렀을 때만."""
    with _JOB_LOCK:
        if _JOB.get("running"):
            raise VNError("조립이 아직 돌고 있습니다 — 먼저 멈추세요.")
        _JOB.clear()
        _JOB["running"] = False
    return compose_job_status()


def compose_from_json(text: str, force: bool, expected: int | None = None) -> dict:
    """직접 입력: 어디서 받았든 붙여넣은 SCENES_JSON 배열 → 장면 생성 (LLM 불필요)."""
    if not (text or "").strip():
        raise VNError("붙여넣은 내용이 비어 있습니다.")
    try:
        items = _extract_json_array(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise VNError(f"JSON 배열을 찾지 못했습니다({exc}). 응답에서 [ ... ] 배열 전체를 붙여넣으세요.")
    return _create_scenes_from_items(items, force, expected=expected)


# ---------------------------------------------------------------- 대화 → 장면 1개
# 다음 장면 번호를 고르는 계산기는 여기 없다 — scene_ops.create_scene 안에 하나뿐이다.
# (예전에는 이 파일의 next_scene_slot 과 CLI 의 cmd_new 가 각자 셌고, 파일명이 아니라
#  파일 **안의** scene_id 만 봐서 손상된 장면 파일의 번호가 다시 뽑혔다.)


def build_talk_scene_instruction(talk: list, chars: list, locs: list, who=None) -> str:
    """방금 나눈 대화 → 장면 1개를 만들라는 지시문.

    who(대화 상대의 character_id)를 표시해 '상대' 발화가 엉뚱한 인물에게 배정되지 않게 한다.
    """
    char_block = "\n".join(
        f"- {c.get('character_id')} {c.get('name', '')}"
        + ("  ← '상대' 는 이 인물" if c.get("character_id") == who else "")
        for c in chars)
    loc_block = "\n".join(
        f"- {l.get('location_id')} {l.get('name', '')}: {l.get('description', '')}" for l in locs)
    return ("아래는 두 사람이 방금 나눈 대화다. 이 순간을 한 컷의 장면으로 만들어라.\n"
            "다른 말 없이 JSON 객체 하나만 출력하라.\n\n"
            f"[대화]\n{chr(10).join(talk)}\n\n[캐릭터]\n{char_block}\n\n[장소]\n{loc_block}\n\n"
            '{"purpose":"장면 목적(한국어)","action_beat":"동작(한국어)","emotion":"감정(한국어)",'
            '"time":"시간대(한국어)","location_id":"위 목록의 id",'
            '"camera":{"shot":"medium","angle":"eye","framing":"center","focus":"face"},'
            '"dialogue":[{"speaker_id":"위 목록의 id","text":"대사(한국어)"}]}')


def scene_from_talk(messages, character_id=None) -> dict:
    """'이 순간을 사진으로' — 최근 대화 → 새 장면(계획) + 이미지 프롬프트까지.

    이미지 생성은 하지 않는다(과금 대상). 만들어진 장면은 PROMPT 상태로 남고, 사용자가
    장면 탭에서 확인한 뒤 직접 생성 버튼을 누른다.

    반환: scene_ops.set_prompt 의 결과에 {scene_id, scene_order, purpose, prompt} 를 얹은 dict.
    """
    msgs = messages if isinstance(messages, list) else []
    talk = [f"{'나' if m.get('role') == 'user' else '상대'}: {str(m.get('content', ''))[:300]}"
            for m in msgs[-12:] if isinstance(m, dict) and str(m.get("content", "")).strip()]
    if not talk:
        raise VNError("장면으로 만들 대화가 없습니다. 먼저 대화를 나눠 주세요.")

    mf = vn_core.load_json_safe(MANIFEST, {})
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    locs = [l for l in mf.get("locations", []) if isinstance(l, dict)]
    if not chars:
        raise VNError("매니페스트에 캐릭터가 없습니다. 먼저 작품을 세팅하세요.")
    ask = build_talk_scene_instruction(talk, chars, locs, character_id)
    item = extract_json_object(local_llm.chat([{"role": "user", "content": ask}],
                                              temperature=0.6, max_tokens=700))

    char_ids = [c.get("character_id") for c in chars]
    loc_ids = {l.get("location_id") for l in locs}
    # 번호는 create_scene 이 쓰기 잠금 안에서 정한다 — build_scene 이 매긴 자리표시자는 버린다.
    # (슬롯을 미리 골라 두면 고른 뒤 저장 전에 다른 요청이 같은 번호를 가져갈 수 있다.)
    fields = build_scene(item, 1, char_ids, loc_ids, locs)
    for placeholder in ("scene_id", "scene_order"):
        fields.pop(placeholder, None)
    fields["status"] = "SCENE_PLAN"     # 프롬프트는 아래 set_prompt 가 넣는다(앵커 보정 포함)
    fields["prompt"] = {"grok_output": ""}
    sc = scene_ops.create_scene(fields=fields)
    sid, order = sc["scene_id"], sc["scene_order"]
    # 프롬프트까지만(생성은 사용자 몫) — 앵커·화풍은 prompt_build 가 코드로 넣는다.
    res = scene_ops.set_prompt(sid, prompt_build.compose_image_prompt(sc))
    saved = vn_core.load_json_safe(vn_core.scene_path(sid), {})
    res.update({"scene_id": sid, "scene_order": order, "purpose": saved.get("purpose", ""),
                "prompt": (saved.get("prompt") or {}).get("grok_output", "")})
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="스토리라인 → 장면 자동 구성 (로컬 LLM)")
    ap.add_argument("count", type=int, nargs="?", default=10,
                    help=f"장면 수 (기본 10, 최대 {MAX_SCENES})")
    ap.add_argument("--force", action="store_true", help="기존 장면을 backups/ 로 옮기고 재구성")
    ap.add_argument("--branching", action="store_true",
                    help="선택지·분기(choices/branch) 형식까지 요청 (기본은 선형)")
    args = ap.parse_args()
    moved = migrate_legacy_backups()  # 과거 project/scenes_backup_* 잔재 정리
    if moved:
        print(f"과거 백업 {len(moved)}벌을 backups/ 로 옮겼습니다: {', '.join(moved)}")
    try:
        r = compose_scenes(args.count, args.force, args.branching)
    except RuntimeError as exc:      # VNError 포함
        print(f"오류: {exc}")
        return 1
    print(f"{len(r['created'])}개 장면 생성: {', '.join(r['created'])}")
    if r.get("backup"):
        print(f"기존 장면 백업: {r['backup']}")
    if r.get("pruned"):
        print(f"오래된 백업 {len(r['pruned'])}벌 정리(최신 {BACKUP_KEEP}벌 보존)")
    if r.get("warning"):
        print(f"경고: {r['warning']}")
    print(r["checker"])
    return 0 if r["checker_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
