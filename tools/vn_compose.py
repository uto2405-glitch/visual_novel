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

분기 지시문은 **manifest.dating 의 눈금 위에서** 만들어진다. 호감도 범위와 branch.min
예시를 리터럴로 박아 두면(예전의 -2~2 · min:3) start_affection 이 30 인 작품에서는
두 번째 엔딩에 영영 도달하지 못한다 — 눈금은 작품마다 다르므로 매번 계산한다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advance_scene as adv  # noqa: E402
import local_llm  # noqa: E402
import prompt_build  # noqa: E402  (이미지 프롬프트 조립 — 대화→장면 경로가 바로 이어 쓴다)
import scene_lint  # noqa: E402  (연출 규칙·카메라 표준 어휘의 단일 출처)
import scene_ops  # noqa: E402   (장면 상태 전이의 유일한 구현)
import vn_core  # noqa: E402
import xai_client  # noqa: E402
from vn_core import VNError  # noqa: E402

ROOT = vn_core.ROOT
SCENES = vn_core.SCENES
MANIFEST = vn_core.MANIFEST
STORY_DIR = vn_core.STORY
BACKUPS = vn_core.BACKUPS
TEMPLATE = vn_core.TEMPLATES / "scene.json"
COMPOSE_MARK = "SCENES_JSON_ONLY"

MAX_SCENES = 50        # 1회 구성 상한 — 통제 없는 호출 확대와 대량 파일 생성을 막는다
BACKUP_KEEP = 5        # scenes_backup_* 보존 벌 수
# 화풍 문구의 단일 출처는 vn_core 다(프롬프트 조립·웹 생성과 같은 문구여야 컷 화풍이 안 흔들린다).
DEFAULT_VISUAL_STYLE = vn_core.DEFAULT_VISUAL_STYLE
# 감상본 뷰어가 dating 없이도 쓰는 기본 눈금 — 지시문 계산의 출발점도 같아야 한다.
DEFAULT_AFF_START = 30
DEFAULT_AFF_MAX = 100


# 저장소 전역 쓰기 잠금 — 정본은 vn_core 하나다(advance_scene.WRITE_LOCK 도 같은 객체다).
WRITE_LOCK = vn_core.WRITE_LOCK


def _extract_json_array(text: str):
    body = re.sub(r"```(?:json)?", "", text).strip()
    s_i, e_i = body.find("["), body.rfind("]")
    if s_i < 0 or e_i <= s_i:
        raise ValueError("JSON 배열 없음")
    return json.loads(body[s_i:e_i + 1])


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
    """
    d = mf.get("dating") if isinstance(mf.get("dating"), dict) else {}
    top = _as_order(d.get("max", DEFAULT_AFF_MAX), DEFAULT_AFF_MAX)
    if top < 2:
        top = DEFAULT_AFF_MAX
    start = max(0, min(top, _as_order(d.get("start_affection", DEFAULT_AFF_START),
                                     DEFAULT_AFF_START)))
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
    char_block = "\n".join(f"- {c.get('character_id')} {c.get('name','')}: anchor=\"{c.get('prompt_anchor','')}\"" for c in chars)
    loc_block = "\n".join(f"- {l.get('location_id')} {l.get('name','')}: anchor=\"{l.get('prompt_anchor','')}\"" for l in locs)
    style = vn_core.visual_style(mf)
    shot_vocab = " / ".join(scene_lint.STD_SHOTS)
    angle_vocab = " / ".join(scene_lint.STD_ANGLES)
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
4. dialogue 는 한국어, 장면당 1~4줄. 한 줄은 60자 이내.
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
    """장면 원소 1개 → 장면 dict. 어떤 필드가 잘못된 타입이어도 기본값으로 흡수(크래시 없음).

    episode: 이어받을 화 번호. 원소가 스스로 episode 를 말하면 그쪽이 우선이다.
             None 이면 디스크의 마지막 장면에서 승계한다(웹의 '장면 하나 추가' 경로).
             0 은 '화 표기 없음' — 재구성 중이라 디스크를 보면 안 될 때 쓴다.
    """
    sc = vn_core.load_json(TEMPLATE)
    sid = f"SCENE-{index:03d}"
    sc["scene_id"], sc["scene_order"], sc["status"] = sid, index, "PROMPT"
    sc["location_id"] = it.get("location_id") if it.get("location_id") in loc_ids else (locs[0].get("location_id") if locs else "")
    dialogue, speakers = [], []
    for d in (it.get("dialogue") if isinstance(it.get("dialogue"), list) else []):
        if not isinstance(d, dict):
            continue
        spk = d.get("speaker_id") if d.get("speaker_id") in char_ids else (char_ids[0] if char_ids else "")
        dialogue.append({"speaker_id": spk, "text": str(d.get("text", "")), "placement": "bottom"})
        if spk and spk not in speakers:
            speakers.append(spk)
    sc["dialogue"] = dialogue or sc["dialogue"]
    sc["characters"] = speakers or (char_ids[:1] if char_ids else [])
    for k in ("purpose", "action_beat", "emotion", "time"):
        sc[k] = str(it.get(k, ""))
    cam = it.get("camera") if isinstance(it.get("camera"), dict) else {}
    sc["camera"] = {k: str(cam.get(k, "")) for k in ("shot", "angle", "framing", "focus")}
    sc["prompt"]["grok_output"] = str(it.get("image_prompt", ""))
    ep = norm_episode(it.get("episode"))
    if ep is None:
        ep = norm_episode(episode) if episode is not None else last_episode()
    if ep is not None:
        sc["episode"] = ep
    # 분기 엔진(선택) — 있을 때만 실어 나른다(선형 작품은 깨끗하게 유지). 검사기는 이 필드를 무시.
    ch = norm_choices(it.get("choices"))
    if ch:
        sc["choices"] = ch
    br = norm_branch(it.get("branch"))
    if br:
        sc["branch"] = br
    is_end, label = ending_of(it)
    if is_end:
        sc["ending"] = True            # 규약: 참/거짓만. 결말의 이름은 ending_label 로.
        if label:
            sc["ending_label"] = label
    return sc


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
    if not force and SCENES.exists() and any(SCENES.glob("SCENE-*.json")):
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
    for i, (_, it) in enumerate(ordered, 1):
        sc = build_scene(it, i, char_ids, loc_ids, locs, episode=prev_ep)
        prev_ep = norm_episode(sc.get("episode")) or prev_ep
        built.append(sc)

    # 2) WRITE_LOCK 안에서 재확인 + 백업 + 일괄 저장
    created, backup, pruned = [], None, []
    with WRITE_LOCK:
        existing = sorted(SCENES.glob("SCENE-*.json")) if SCENES.exists() else []
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
        SCENES.mkdir(parents=True, exist_ok=True)
        for sc in built:
            vn_core.atomic_write_json(adv.scene_path(sc["scene_id"]), sc)
            created.append(sc["scene_id"])

    code, chk = adv.run_checker()
    result = {"created": created, "checker_pass": code == 0,
              "checker": "\n".join(l for l in chk.splitlines() if "FAIL" in l) or "자동 검사 통과"}
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


def orch_chat(messages: list, temperature: float = 0.6, max_tokens: int = 8192) -> str:
    """장면 구성용 LLM 호출 — 로컬 LLM(기본) 또는 xAI(mode=api)."""
    if _orch_local():
        return local_llm.chat(messages, temperature=temperature, max_tokens=max_tokens)
    return xai_client.chat(messages, temperature=temperature)


def compose_scenes(count: int, force: bool, branching: bool = False) -> dict:
    """스토리라인 → 장면 자동 구성 (로컬 LLM/API). 수동 모드는 compose_from_json 사용."""
    if not force and SCENES.exists() and any(SCENES.glob("SCENE-*.json")):
        raise VNError(_EXISTS_MSG)          # 호출 낭비 방지 — 미리 막는다
    instruction = build_compose_instruction(count, branching)
    out = orch_chat([{"role": "user", "content": instruction}], temperature=0.6)
    try:
        items = _extract_json_array(out)
    except (ValueError, json.JSONDecodeError):
        # 1회 재시도: 형식 교정 요청
        retry = orch_chat([
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": out},
            {"role": "user", "content": "위 응답에서 JSON 배열만, 다른 텍스트 없이 다시 출력하라."},
        ], temperature=0.2)
        try:
            items = _extract_json_array(retry)
        except (ValueError, json.JSONDecodeError):
            raise VNError("장면 JSON 파싱 실패 — 스토리라인을 조금 더 구체화해 다시 시도하세요.")
    return _create_scenes_from_items(items, force, expected=count)


def compose_from_json(text: str, force: bool, expected: int | None = None) -> dict:
    """수동 모드: grok.com 에서 받아 붙여넣은 SCENES_JSON 배열 → 장면 생성 (API 불필요)."""
    if not (text or "").strip():
        raise VNError("붙여넣은 내용이 비어 있습니다.")
    try:
        items = _extract_json_array(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise VNError(f"JSON 배열을 찾지 못했습니다({exc}). grok.com 응답에서 [ ... ] 배열 전체를 붙여넣으세요.")
    return _create_scenes_from_items(items, force, expected=expected)


# ---------------------------------------------------------------- 대화 → 장면 1개
def next_scene_slot() -> tuple:
    """다음 scene_id 와 scene_order (order 는 1부터 연속을 유지).

    호출부는 **쓰기 잠금 안에서** 이 값을 받아 그대로 저장해야 한다 — 슬롯을 고른 뒤
    저장 전에 다른 요청이 같은 슬롯을 가져가면 scene_order 가 겹친다(검사기 A5 FAIL).
    """
    nums, order = [], 0
    for f in (sorted(SCENES.glob("SCENE-*.json")) if SCENES.exists() else []):
        sc = vn_core.load_json_safe(f, {})
        m = re.fullmatch(r"SCENE-(\d+)", str(sc.get("scene_id", "")))
        if m:
            nums.append(int(m.group(1)))
        order = max(order, _as_order(sc.get("scene_order"), 0))
    return f"SCENE-{(max(nums) + 1 if nums else 1):03d}", order + 1


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
    with WRITE_LOCK:
        sid, order = next_scene_slot()
        idx = int(re.sub(r"\D", "", sid) or 1)
        sc = build_scene(item, idx, char_ids, loc_ids, locs)
        sc["scene_id"], sc["scene_order"] = sid, order
        sc["status"] = "SCENE_PLAN"
        sc["prompt"]["grok_output"] = ""
        SCENES.mkdir(parents=True, exist_ok=True)
        adv.save(adv.scene_path(sid), sc)
    # 프롬프트까지만(생성은 사용자 몫) — 앵커·화풍은 prompt_build 가 코드로 넣는다.
    res = scene_ops.set_prompt(sid, prompt_build.compose_image_prompt(sc))
    saved = vn_core.load_json_safe(adv.scene_path(sid), {})
    res.update({"scene_id": sid, "scene_order": order, "purpose": saved.get("purpose", ""),
                "prompt": (saved.get("prompt") or {}).get("grok_output", "")})
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="스토리라인 → 장면 자동 구성 (로컬 LLM 또는 xAI API)")
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
