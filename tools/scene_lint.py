#!/usr/bin/env python3
"""연출 리듬 린터 — 검사기(A1~A8)와 별개의 '연출 자문' 도구.

컷 연속성·감정 단조로움·대사 길이·시간대/등장인물/카메라 표기의 흔들림처럼
'틀렸다'가 아니라 '단조롭다/어색하다/표기가 섞였다'를 경고한다.
품질 판정이 아니라 리듬 신호이며 PASS/FAIL 을 만들지 않는다(SCORECARD·검사기 불침범).

사용법:
  python tools/scene_lint.py            # 전체 장면 연출 리듬 점검
읽기 전용. 표준 라이브러리만.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "project" / "scenes"
MANIFEST = ROOT / "project" / "manifest.json"

RUN_LIMIT = 3          # 같은 값 연속 허용 한도
LONG_LINE = 60         # 대사 한 줄 권장 상한(글자)

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


def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


def _s(v):  # 어떤 타입이 와도 문자열로 (손편집 JSON 방탄)
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _load_scenes():
    out = []
    for f in sorted(SCENES.glob("SCENE-*.json")) if SCENES.exists() else []:
        try:
            sc = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(sc, dict):
            out.append(sc)
    out.sort(key=lambda s: s.get("scene_order") or 0)
    return out


def _load_manifest() -> dict:
    """기준정보 — 없거나 깨져도 린터는 계속 돈다(자문 도구는 멈추지 않는다)."""
    try:
        mf = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return mf if isinstance(mf, dict) else {}


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


def lint_scenes() -> dict:
    """장면 연출 리듬 점검 → {findings:[{scene_id,level,rule,message}], summary}."""
    scenes = _load_scenes()
    mf = _load_manifest()
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
    _check_camera_vocab(scenes, add)

    warn = sum(1 for f in findings if f["level"] == "warn")
    info = sum(1 for f in findings if f["level"] == "info")
    summary = (f"연출 리듬: 경고 {warn} · 참고 {info}" if findings else "연출 리듬 양호 — 특이사항 없음")
    if len(scenes) < 2:
        summary += " (장면 1개 — 연속성 점검 생략)"
    return {"findings": findings, "summary": summary, "scene_count": len(scenes)}


def main() -> int:
    r = lint_scenes()
    print("=" * 56)
    print(f"연출 리듬 린터 — 장면 {r['scene_count']}개  (연출 자문 · 검사기와 별개)")
    print("=" * 56)
    if not r["findings"]:
        print("특이사항 없음. 연출 리듬 양호.")
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
    print(r["summary"])
    print("주의: 이는 리듬 자문일 뿐 PASS/FAIL 이 아닙니다(최종 판단은 사람).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
