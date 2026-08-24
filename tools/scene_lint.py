#!/usr/bin/env python3
"""연출 리듬 린터 — 검사기(A1~A8)와 별개의 '연출 자문' 도구.

컷 연속성·감정 단조로움·대사 길이 등 '틀렸다'가 아니라 '단조롭다/어색하다'를 경고한다.
품질 판정이 아니라 리듬 신호이며 PASS/FAIL 을 만들지 않는다(SCORECARD·검사기 불침범).

사용법:
  python tools/scene_lint.py            # 전체 장면 연출 리듬 점검
읽기 전용. 표준 라이브러리만.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "project" / "scenes"

RUN_LIMIT = 3          # 같은 값 연속 허용 한도
LONG_LINE = 60         # 대사 한 줄 권장 상한(글자)


def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


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


def lint_scenes() -> dict:
    """장면 연출 리듬 점검 → {findings:[{scene_id,level,rule,message}], summary}."""
    scenes = _load_scenes()
    findings = []

    def add(level, rule, msg, sid="-"):
        findings.append({"scene_id": sid, "level": level, "rule": rule, "message": msg})

    if len(scenes) < 2:
        return {"findings": findings, "summary": "장면이 부족해 리듬 점검 생략.",
                "scene_count": len(scenes)}

    def _s(v):  # 어떤 타입이 와도 문자열로 (손편집 JSON 방탄)
        return v if isinstance(v, str) else ("" if v is None else str(v))

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

    warn = sum(1 for f in findings if f["level"] == "warn")
    info = sum(1 for f in findings if f["level"] == "info")
    summary = (f"연출 리듬: 경고 {warn} · 참고 {info}" if findings else "연출 리듬 양호 — 특이사항 없음")
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
    print(r["summary"])
    print("주의: 이는 리듬 자문일 뿐 PASS/FAIL 이 아닙니다(최종 판단은 사람).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
