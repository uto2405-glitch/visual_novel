#!/usr/bin/env python3
"""연출 리듬 + 분기 무결성 린터 — 검사기(A1~A8)와 별개의 '자문' 도구.

세 가지를 본다.
  1) 연출 리듬: 컷 연속성·감정 단조로움·대사 길이·시간대/등장인물/카메라 표기의 흔들림.
     '틀렸다'가 아니라 '단조롭다/어색하다/표기가 섞였다'를 경고한다.
  2) 분기 무결성: 감상본(export_viewer)의 분기 엔진이 실제로 어떻게 도는지를 그대로
     모사해, 절대 도달할 수 없는 길과 끝이 닫히지 않은 길을 찾는다.
     dangling-goto / branch-order / unreachable-scene / open-branch / affection-unreachable.
  3) 프롬프트 상태: 되돌림(revise) 뒤에 남은 프롬프트와 그 때문에 지금 A6 가 FAIL 을 내는
     장면 — '고장'과 '아직 다시 만들지 않은 중간 상태'를 구분해 준다.
     stale-prompt / anchor-missing.

검사기(check_protocol)는 분기 필드를 보지 않는다 — 분기는 '규격 위반'이 아니라 '설계
오류'라서 자문 계층이 올바른 위치다. 그래서 여기서는 어떤 경우에도 PASS/FAIL 을 만들지
않고 종료 코드는 항상 0 이다(SCORECARD·검사기 불침범).

사용법:
  python tools/scene_lint.py            # 전체 장면 연출 리듬 + 분기 점검
읽기 전용. 표준 라이브러리만.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core  # noqa: E402

ROOT = vn_core.ROOT
SCENES = vn_core.SCENES
MANIFEST = vn_core.MANIFEST

RUN_LIMIT = 3          # 같은 값 연속 허용 한도
LONG_LINE = 60         # 대사 한 줄 권장 상한(글자)
DEFAULT_START_AFFECTION = 30   # manifest.dating.start_affection 이 없을 때(감상본 뷰어와 동일)
DEFAULT_MAX_AFFECTION = 100

# 카메라 표준 어휘 — 표기가 흔들리면 같은 샷 연속 감지(_runs)도, 프롬프트 문구도 함께 흔들린다.
STD_SHOTS = ("extreme-wide", "wide", "full", "medium-wide", "medium",
             "medium-close-up", "close-up", "extreme-close-up", "two-shot",
             "over-the-shoulder", "pov", "insert")
STD_ANGLES = ("eye-level", "high-angle", "low-angle", "overhead",
              "birds-eye", "worms-eye", "dutch-angle", "front", "side", "rear")
# 흔한 약칭 → 표준 어휘. 해당 필드의 표준 목록에 있을 때만 채택하므로 shot/angle 이 섞이지 않는다.
CAM_SHORTHAND = {"close": "close-up", "cu": "close-up", "ecu": "extreme-close-up",
                 "mcu": "medium-close-up", "ots": "over-the-shoulder",
                 "pointofview": "pov", "eye": "eye-level", "high": "high-angle",
                 "low": "low-angle", "dutch": "dutch-angle", "back": "rear",
                 "behind": "rear", "overthehead": "overhead"}
SHOT_HINT = "표준: wide / medium / close-up / two-shot / over-the-shoulder 등"
ANGLE_HINT = "표준: eye-level / high-angle / low-angle / overhead / dutch-angle 등"

# 시간대 버킷 — time 필드(한국어·영어)와 영어 프롬프트를 같은 축에 놓고 비교한다.
# prompt 키워드는 단어 경계로 찾는다("afternoon" 안의 noon 같은 오탐 방지).
TIME_BUCKETS = {
    "morning": {"label": "아침",
                "prompt": ("morning", "sunrise", "dawn", "daybreak", "early light"),
                "field": ("아침", "새벽", "오전", "등굣길", "morning", "dawn", "sunrise")},
    "day": {"label": "낮",
            "prompt": ("noon", "midday", "daytime", "daylight", "afternoon", "bright sunlight"),
            "field": ("낮", "한낮", "정오", "점심", "오후", "방과 후", "방과후",
                      "day", "noon", "afternoon")},
    "evening": {"label": "저녁·노을",
                "prompt": ("sunset", "sundown", "dusk", "twilight", "golden hour", "evening"),
                "field": ("저녁", "노을", "해질녘", "해 질 녘", "해질 녘", "황혼", "일몰",
                          "sunset", "dusk", "twilight", "evening")},
    "night": {"label": "밤",
              "prompt": ("night", "nighttime", "midnight", "moonlight", "moonlit",
                         "starry", "starlight"),
              "field": ("밤", "한밤", "자정", "심야", "야간", "night", "midnight")},
}
for _spec in TIME_BUCKETS.values():
    _spec["re"] = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in _spec["prompt"]) + r")\b",
                             re.IGNORECASE)


def _s(v):  # 어떤 타입이 와도 문자열로 (손편집 JSON 방탄)
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _i(v, default: int = 0) -> int:
    """정수로 (손편집 JSON 의 "3" 이나 null 이 정렬·비교를 크래시시키지 않게)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _load_scenes():
    out = []
    for f in sorted(SCENES.glob("SCENE-*.json")) if SCENES.exists() else []:
        sc = vn_core.load_json_safe(f, {})
        if sc:
            out.append(sc)
    out.sort(key=lambda s: _i(s.get("scene_order")))
    return out


def _prompt_of(sc: dict) -> str:
    p = sc.get("prompt") if isinstance(sc.get("prompt"), dict) else {}
    return _s(p.get("grok_output", "")).strip()


def _runs(values):
    """(값, 시작index, 길이) 중 길이>=RUN_LIMIT 인 연속 구간."""
    runs, i = [], 0
    n = len(values)
    while i < n:
        j = i
        while j + 1 < n and values[j + 1] == values[i] and values[i]:
            j += 1
        if j - i + 1 >= RUN_LIMIT:
            runs.append((values[i], i, j - i + 1))
        i = j + 1
    return runs


def _loose(v: str) -> str:
    """표기 흔들림을 지운 비교용 키 — 'Eye Level' / 'eye-level' → 'eyelevel'."""
    return re.sub(r"[^a-z0-9]+", "", v.lower())


def _cam_canon(value: str, std: tuple) -> str | None:
    """카메라 표기를 표준 어휘로 정규화. 표준 밖이면 None."""
    std_map = {_loose(s): s for s in std}
    key = _loose(value)
    cands = [key]
    for suffix in ("shot", "angle", "view"):  # 'medium shot' 같은 군더더기 접미 제거
        if key.endswith(suffix) and len(key) > len(suffix):
            cands.append(key[:-len(suffix)])
    for c in cands:
        if c in std_map:
            return std_map[c]
        alias = CAM_SHORTHAND.get(c)
        if alias and _loose(alias) in std_map:
            return std_map[_loose(alias)]
    return None


def _field_buckets(text: str) -> set:
    """time 필드 문자열 → 시간대 버킷 집합(한국어는 부분일치, 영어도 포함)."""
    t = text.strip().lower()
    if not t:
        return set()
    return {b for b, spec in TIME_BUCKETS.items() if any(w.lower() in t for w in spec["field"])}


def _prompt_hits(prompt: str) -> dict:
    """프롬프트 → {버킷: [발견된 키워드]} (단어 경계 기준)."""
    hits = {}
    for b, spec in TIME_BUCKETS.items():
        found = sorted({m.group(0).lower() for m in spec["re"].finditer(prompt)})
        if found:
            hits[b] = found
    return hits


def _labels(buckets) -> str:
    return "/".join(TIME_BUCKETS[b]["label"] for b in sorted(buckets))


def _check_offcast(scenes, mf, add) -> None:
    """등장 목록(characters) 밖 인물의 앵커가 프롬프트에 섞였는지 — 검사기 A6 의 역방향."""
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    if not chars:
        return
    for sc in scenes:
        prompt = _prompt_of(sc)
        if not prompt:
            continue
        sid = _s(sc.get("scene_id", "?"))
        raw = sc.get("characters")
        listed = [_s(c) for c in raw] if isinstance(raw, list) else []
        listed_anchors = [_s(c.get("prompt_anchor")).strip() for c in chars
                          if _s(c.get("character_id")) in listed]
        for c in chars:
            cid, anchor = _s(c.get("character_id")), _s(c.get("prompt_anchor")).strip()
            if not cid or not anchor or cid in listed:
                continue
            if anchor not in prompt:
                continue
            # 등장 인물 앵커에 통째로 포함되는 문구면 오탐(두 인물 앵커가 겹치는 경우)
            if any(anchor in la for la in listed_anchors):
                continue
            add("warn", "offcast-anchor",
                f"등장 목록에 없는 {cid}({_s(c.get('name'))}) 앵커가 프롬프트에 있음 — "
                "characters 에 추가하거나 프롬프트에서 빼야 인물 수가 어긋나지 않음", sid)


def _check_time(scenes, add) -> None:
    """time 필드와 프롬프트 시간대 표현의 불일치·혼재 — 장소 앵커의 시간대 묘사가 흔한 원인."""
    for sc in scenes:
        prompt = _prompt_of(sc)
        if not prompt:
            continue
        sid = _s(sc.get("scene_id", "?"))
        tval = _s(sc.get("time", "")).strip()
        fb, hits = _field_buckets(tval), _prompt_hits(prompt)
        words = ", ".join(w for ws in hits.values() for w in ws)
        if fb and hits and not (fb & set(hits)):
            add("warn", "time-mismatch",
                f"time '{tval}'({_labels(fb)}) 과 프롬프트 시간대 표현 '{words}'({_labels(hits)}) 불일치", sid)
        if len(hits) >= 2:
            add("warn", "time-mixed",
                f"프롬프트에 서로 다른 시간대 표현이 섞임({words}) — "
                "장소 앵커에 시간대 묘사가 박혀 있는지 확인", sid)


def _check_prompt_state(scenes, add) -> None:
    """되돌림 이후 남은 프롬프트 · 지금 A6 가 FAIL 을 낼 앵커 — '정상적인 중간 상태'의 설명.

    검사기 A6 는 status 와 무관하게 prompt.grok_output 이 있으면 검사한다. revise 는
    자료를 보존하므로(그게 의도다) SCENE_PLAN 으로 되돌린 장면에도 프롬프트가 남고,
    그 사이에 등장인물·장소를 고쳤다면 옛 프롬프트에는 새 앵커가 없다 → A6 FAIL.
    잘못된 상태가 아니라 '아직 프롬프트를 다시 만들지 않은 상태'인데 화면에는 FAIL 로만
    보인다. 그 둘을 사람이 구분할 수 있게 이유와 다음 할 일을 여기서 말해 준다.
    """
    import scene_ops   # 앵커 추출 규칙의 단일 출처(지연 import — 린터는 위층을 모듈 수준에서 안 쓴다)
    for sc in scenes:
        prompt = _prompt_of(sc)
        if not prompt:
            continue
        sid = _s(sc.get("scene_id", "?"))
        status = _s(sc.get("status"))
        # A6 와 같은 판정: 앵커 원문이나 그 id 중 하나라도 프롬프트에 있으면 통과.
        missing = [ref or "?" for ref, anchor in scene_ops.scene_anchors(sc)
                   if anchor not in prompt and (ref or "") not in prompt]
        if status == "SCENE_PLAN":
            add("warn", "stale-prompt",
                "계획 단계로 되돌렸는데 이전 프롬프트가 남아 있음(revise 의 자료 보존) — "
                "검사기 A6 는 상태와 무관하게 프롬프트가 있으면 검사하므로, 프롬프트를 "
                "다시 만들기 전까지 이 장면은 옛 프롬프트로 계속 채점된다", sid)
        if missing:
            tail = (" 되돌린 뒤 등장인물·장소를 바꾼 정상적인 중간 상태일 수 있다 — "
                    "프롬프트를 다시 만들면 사라진다." if status in ("SCENE_PLAN", "PROMPT") else
                    " 이미지 단계 이후이므로 프롬프트를 고치거나 되돌려야 한다.")
            add("warn", "anchor-missing",
                f"프롬프트에 {', '.join(missing)} 의 앵커가 없어 지금 검사기 A6 가 FAIL 이다 —"
                + tail + " (스튜디오의 '앵커 자동 보정'이 원문 그대로 채워 준다)", sid)


def _check_camera_vocab(scenes, add) -> None:
    """카메라 shot/angle 표기 표준화 — 'eye level' 과 'eye-level' 이 섞이면 컷 반복 감지가 무력화된다."""
    for field, std, hint in (("shot", STD_SHOTS, SHOT_HINT), ("angle", STD_ANGLES, ANGLE_HINT)):
        seen = {}
        for sc in scenes:
            cam = sc.get("camera") if isinstance(sc.get("camera"), dict) else {}
            val = _s(cam.get(field, "")).strip()
            if val:
                seen.setdefault(val, []).append(_s(sc.get("scene_id", "?")))
        for val, sids in seen.items():
            where = f"{len(sids)}장: {', '.join(sids[:3])}" + (" …" if len(sids) > 3 else "")
            canon = _cam_canon(val, std)
            if canon is None:
                add("info", "camera-vocab",
                    f"camera.{field} '{val}' 은 표준 어휘 밖 ({where}) — {hint}", sids[0])
            elif val.lower() != canon:
                add("warn", "camera-vocab",
                    f"camera.{field} 표기 '{val}' → 표준 '{canon}' 으로 통일 권장 ({where})", sids[0])


# ------------------------------------------------------------------ 분기 무결성
# 감상본(export_viewer)의 진행 규칙을 그대로 모사한다:
#   장면 끝 → choices 가 있으면 선택지 / 없고 ending 이면 종료 /
#            branch 가 있으면 조건(aff >= min) 만족하는 **첫** 항목 / 그 외 다음 순서.
def _choices(sc) -> list:
    v = sc.get("choices")
    return [c for c in v if isinstance(c, dict)] if isinstance(v, list) else []


def _branch(sc) -> list:
    v = sc.get("branch")
    return [b for b in v if isinstance(b, dict)] if isinstance(v, list) else []


def _has_flow(scenes) -> bool:
    """분기 작품인지 — 선형 작품에 '엔딩이 없다'고 잔소리하지 않기 위한 관문."""
    return any(_choices(sc) or _branch(sc) or sc.get("ending") for sc in scenes)


def _edges(scenes, idx: dict, i: int) -> list:
    """장면 i 에서 나가는 (다음 index, 호감도 증감) 목록. 빈 목록이면 그 자리에서 이야기가 끝난다."""
    sc = scenes[i]
    nxt = i + 1 if i + 1 < len(scenes) else None
    out = []
    ch = _choices(sc)
    if ch:
        for c in ch:
            goto = _s(c.get("goto")).strip()
            j = idx.get(goto) if goto else nxt
            if j is not None:
                out.append((j, _i(c.get("affection"))))
        return out
    if sc.get("ending"):
        return []
    br = _branch(sc)
    if br:
        for b in br:
            j = idx.get(_s(b.get("goto")).strip())
            if j is not None:
                out.append((j, 0))
        return out
    return [(nxt, 0)] if nxt is not None else []


def _reach(scenes, idx: dict, start_aff: int, aff_max: int):
    """도달 가능성 + 각 장면에 **도달할 수 있는 최고/최저 호감도**.

    선택지의 증감을 따라 앞으로 전파한다(감상본과 같은 0~max 클램프). 값이 유한하고
    단조로워서 장면 수만큼 완화하면 수렴한다 — 순환 분기가 있어도 멈춘다.
    반환: (best, worst) — 도달 불가 장면은 None.
    """
    n = len(scenes)
    best: list = [None] * n
    worst: list = [None] * n
    if not n:
        return best, worst
    best[0] = worst[0] = max(0, min(aff_max, start_aff))
    for _ in range(n + 1):
        changed = False
        for i in range(n):
            if best[i] is None:
                continue
            for j, d in _edges(scenes, idx, i):
                hi = max(0, min(aff_max, best[i] + d))
                lo = max(0, min(aff_max, worst[i] + d))
                if best[j] is None or hi > best[j]:
                    best[j], changed = hi, True
                if worst[j] is None or lo < worst[j]:
                    worst[j], changed = lo, True
        if not changed:
            break
    return best, worst


def _walk_to_other_target(scenes, idx: dict, start: int, targets: set) -> int | None:
    """start 에서 선형으로 흘러가다 같은 분기의 **다른** 목적지에 닿으면 그 index.

    분기로 갈라놓고 한쪽 경로에 ending 을 안 달면, 그 경로가 다른 쪽 엔딩 장면으로
    그대로 흘러 들어가 두 결말이 하나로 붙어버린다. 그 사고만 정확히 잡는다.
    """
    cur, seen = start, {start}
    for _ in range(len(scenes) + 1):
        sc = scenes[cur]
        if sc.get("ending") or _choices(sc) or _branch(sc):
            return None                     # 제 갈 길로 닫히거나 다시 갈라진다
        nxt = _edges(scenes, idx, cur)
        if len(nxt) != 1:
            return None
        cur = nxt[0][0]
        if cur in seen:
            return None
        seen.add(cur)
        if cur in targets:
            return cur
    return None


def _check_branching(scenes, mf, add) -> None:
    """분기 무결성 — 감상본에서 '갈 수 없는 길'과 '닫히지 않은 끝'을 미리 찾는다."""
    idx = {}
    for i, sc in enumerate(scenes):
        sid = _s(sc.get("scene_id")).strip()
        if sid and sid not in idx:
            idx[sid] = i

    # 1) dangling-goto — 존재하지 않는 장면을 가리키는 goto (감상본에서는 그 자리에서 끝난다)
    for i, sc in enumerate(scenes):
        sid = _s(sc.get("scene_id", "?"))
        for k, c in enumerate(_choices(sc), 1):
            goto = _s(c.get("goto")).strip()
            if goto and goto not in idx:
                add("warn", "dangling-goto",
                    f"선택지 {k}('{_s(c.get('text'))[:20]}')의 goto '{goto}' 인 장면이 없음 — "
                    "감상본에서 그 선택은 이야기를 그 자리에서 끝낸다", sid)
        for k, b in enumerate(_branch(sc), 1):
            goto = _s(b.get("goto")).strip()
            if not goto or goto not in idx:
                add("warn", "dangling-goto",
                    f"branch {k}(min {_i(b.get('min'))})의 goto '{goto}' 인 장면이 없음 — "
                    "그 조건에 걸리면 이야기가 끊긴다", sid)

    if not _has_flow(scenes):
        return          # 선형 작품 — 아래 규칙(엔딩·호감도)은 분기 작품에만 의미가 있다

    dating = mf.get("dating") if isinstance(mf.get("dating"), dict) else {}
    start_aff = _i(dating.get("start_affection"), DEFAULT_START_AFFECTION)
    aff_max = _i(dating.get("max"), DEFAULT_MAX_AFFECTION) or DEFAULT_MAX_AFFECTION
    best, worst = _reach(scenes, idx, start_aff, aff_max)

    for i, sc in enumerate(scenes):
        sid = _s(sc.get("scene_id", "?"))
        br = _branch(sc)

        # 2) branch-order — min 이 내림차순이 아니면 앞 조건이 뒤를 가려 버린다
        if br:
            mins = [_i(b.get("min")) for b in br]
            disordered = False
            for k in range(len(mins) - 1):
                if mins[k] < mins[k + 1]:
                    disordered = True
                    add("warn", "branch-order",
                        f"branch min 이 내림차순이 아님({mins}) — 감상본은 위에서부터 첫 조건으로 "
                        f"이동하므로 {k + 1}번째(min {mins[k]})가 {k + 2}번째(min {mins[k + 1]})를 "
                        "영영 가린다. 큰 min 을 먼저 쓸 것", sid)
                    break
            # 언제나 성립하는 조건이 마지막이 아니면 그 뒤는 죽은 길이다
            # (순서가 이미 뒤집혔다면 위 경고로 충분하므로 겹쳐 말하지 않는다)
            w = worst[i]
            if w is not None and not disordered:
                for k, m in enumerate(mins[:-1]):
                    if m <= w:
                        add("warn", "branch-order",
                            f"{k + 1}번째 branch(min {m})는 최저 호감도 {w} 에서도 항상 성립 — "
                            f"뒤의 {len(mins) - k - 1}개 분기는 실행되지 않는다", sid)
                        break

            # 5) affection-unreachable — 도달 가능한 최고 호감도로도 넘길 수 없는 문턱
            hi = best[i]
            if hi is not None:
                for k, b in enumerate(br, 1):
                    m = _i(b.get("min"))
                    if m > hi:
                        add("warn", "affection-unreachable",
                            f"branch {k}(min {m} → {_s(b.get('goto'))})에 절대 도달할 수 없음 — "
                            f"시작 호감도 {start_aff} 에서 여기까지 올 수 있는 최대치가 {hi}. "
                            "선택지 affection 을 키우거나 min 을 낮출 것", sid)

        # 4) open-branch — 여기서 이야기가 멈추는데 ending 표시가 없다
        if not _edges(scenes, idx, i) and not sc.get("ending") and best[i] is not None:
            add("warn", "open-branch",
                "이 장면에서 이야기가 끝나지만 ending 표시가 없음 — "
                '"ending": true 를 넣어야 감상본이 엔딩으로 닫힌다', sid)

        # 4b) 갈라놓은 경로가 다른 분기의 엔딩으로 흘러 들어가 두 결말이 붙는 경우
        targets = {j for j, _ in _edges(scenes, idx, i)}
        if len(targets) >= 2:
            for t in sorted(targets):
                other = _walk_to_other_target(scenes, idx, t, targets - {t})
                if other is not None:
                    add("warn", "open-branch",
                        f"{sid} 에서 갈라진 경로 {_s(scenes[t].get('scene_id'))} 가 "
                        f"다른 갈래 {_s(scenes[other].get('scene_id'))} 로 그대로 이어짐 — "
                        "경로 끝에 ending 을 두지 않으면 두 결말이 하나로 붙는다",
                        _s(scenes[t].get("scene_id", "?")))

    # 3) unreachable-scene — 어느 경로로도 닿지 않는 장면(작업해도 감상본에 안 나온다)
    for i, sc in enumerate(scenes):
        if best[i] is None:
            add("warn", "unreachable-scene",
                "choices/branch/선형 어느 경로로도 닿지 않는 장면 — "
                "goto 로 연결하거나 순서를 조정할 것", _s(sc.get("scene_id", "?")))


def lint_scenes() -> dict:
    """장면 연출 리듬 + 분기 무결성 점검 → {findings:[{scene_id,level,rule,message}], summary}."""
    scenes = _load_scenes()
    mf = vn_core.load_json_safe(MANIFEST, {})   # 기준정보가 깨져도 린터는 계속 돈다
    findings = []

    def add(level, rule, msg, sid="-"):
        findings.append({"scene_id": sid, "level": level, "rule": rule, "message": msg})

    if not scenes:
        return {"findings": findings, "summary": "장면이 없어 리듬 점검 생략.", "scene_count": 0}

    if len(scenes) >= 2:  # 연속성 리듬은 장면이 2개 이상일 때만 의미가 있다
        shots, emotions, locs = [], [], []
        for sc in scenes:
            cam = sc.get("camera") if isinstance(sc.get("camera"), dict) else {}
            shots.append(_s(cam.get("shot", "")))
            emotions.append(_s(sc.get("emotion", "")))
            locs.append(_s(sc.get("location_id", "")))

        for val, start, length in _runs(shots):
            sid = scenes[start].get("scene_id", "?")
            add("warn", "same-shot-run",
                f"같은 샷 '{val}' 이 {length}장 연속(order {start + 1}~{start + length}) — 컷 변주 권장", sid)
        for val, start, length in _runs(emotions):
            sid = scenes[start].get("scene_id", "?")
            add("warn", "same-emotion-run",
                f"같은 감정 '{val}' 이 {length}장 연속 — 감정선 기복 권장", sid)
        for val, start, length in _runs(locs):
            if length >= RUN_LIMIT + 2:  # 장소는 좀 더 관대
                sid = scenes[start].get("scene_id", "?")
                add("info", "same-location-run",
                    f"같은 장소가 {length}장 연속 — 배경 전환/앵글 변화 고려", sid)

        # 절정 클로즈업 부재
        if not any("close" in s.lower() for s in shots):
            add("info", "no-closeup", "전체에 클로즈업이 없음 — 감정 절정에 close-up 한 컷 권장")

    # 대사 점검
    for sc in scenes:
        sid = sc.get("scene_id", "?")
        dlg = sc.get("dialogue", []) if isinstance(sc.get("dialogue"), list) else []
        if not dlg:
            add("info", "no-dialogue", "대사가 없음 — 나레이션 장면이면 무시", sid)
        for i, line in enumerate(dlg, 1):
            if not isinstance(line, dict):
                continue
            txt = _s(line.get("text", ""))
            if len(txt) > LONG_LINE:
                add("warn", "long-line",
                    f"{i}번째 대사가 {len(txt)}자 — 카드 한 장에 길다(≤{LONG_LINE}자 권장)", sid)

    _check_offcast(scenes, mf, add)
    _check_time(scenes, add)
    _check_prompt_state(scenes, add)
    _check_camera_vocab(scenes, add)
    _check_branching(scenes, mf, add)

    warn = sum(1 for f in findings if f["level"] == "warn")
    info = sum(1 for f in findings if f["level"] == "info")
    summary = (f"연출 리듬: 경고 {warn} · 참고 {info}" if findings else "연출 리듬 양호 — 특이사항 없음")
    if len(scenes) < 2:
        summary += " (장면 1개 — 연속성 점검 생략)"
    return {"findings": findings, "summary": summary, "scene_count": len(scenes)}


BRANCH_RULES = ("dangling-goto", "branch-order", "unreachable-scene",
                "open-branch", "affection-unreachable")


def main() -> int:
    r = lint_scenes()
    print("=" * 56)
    print(f"연출 리듬·분기 린터 — 장면 {r['scene_count']}개  (자문 · 검사기와 별개)")
    print("=" * 56)
    if not r["findings"]:
        print("특이사항 없음. 연출 리듬·분기 구조 양호.")
        return 0
    mark = {"warn": "⚠", "info": "·"}
    for f in r["findings"]:
        print(f"  {mark.get(f['level'], '-')} [{f['scene_id']}] {f['message']}")
    print("-" * 56)
    if any(f["rule"] == "camera-vocab" for f in r["findings"]):
        print("카메라 표준 어휘")
        print("  shot : " + " / ".join(STD_SHOTS))
        print("  angle: " + " / ".join(STD_ANGLES))
        print("-" * 56)
    if any(f["rule"] in ("stale-prompt", "anchor-missing") for f in r["findings"]):
        print("참고: 검사기 A6 는 status 와 무관하게 prompt.grok_output 이 있으면 검사한다.")
        print("  되돌린(revise) 장면에 남은 프롬프트도 계속 채점 대상이다 — 자료 보존의 대가다.")
        print("-" * 56)
    if any(f["rule"] in BRANCH_RULES for f in r["findings"]):
        print("분기 점검 기준: choices→선택지 / ending→종료 / branch→조건 만족 첫 항목 / 그 외 다음 순서")
        print("  (감상본 export_viewer 의 진행 규칙과 동일)")
        print("-" * 56)
    print(r["summary"])
    print("주의: 이는 자문일 뿐 PASS/FAIL 이 아닙니다(최종 판단은 사람).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
