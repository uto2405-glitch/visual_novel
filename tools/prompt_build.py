#!/usr/bin/env python3
"""장면 → 이미지 프롬프트 조립.

역할 분담이 이 파일의 전부다:

  * **앵커(인물·장소 원문)는 코드가 조립한다** — 검사기 A6 를 구조적으로 보장하고,
    컷마다 얼굴·배경이 흔들리지 않게 한다.
  * **LLM 은 동작·구도 한 문장만 만든다** — 외모·장소를 다시 묘사하면 앵커와 충돌한다.

화풍 문자열의 단일 출처는 vn_core.visual_style(매니페스트 → 장면 → 기본값)이다.

Python 3.9+ · 표준 라이브러리만(로컬 LLM 호출은 local_llm 경유).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_llm  # noqa: E402
import vn_core  # noqa: E402

# 한국어 시간대 → 영어(이미지 AI 가 알아듣는 단어). 없는 값은 원문을 그대로 넘긴다.
TIME_EN = {"밤": "night", "낮": "daytime", "아침": "morning", "저녁": "evening",
           "노을": "sunset", "새벽": "dawn", "오후": "afternoon"}


def visual_style(sc: dict | None = None) -> str:
    """작품 화풍 — manifest.output.visual_style → 장면 visual_style → 기본 문구."""
    return vn_core.visual_style(None, sc)


def compose_image_prompt(sc: dict) -> str:
    """장면 dict → 이미지 프롬프트 문자열.

    LLM 응답이 비거나 이상해도 앵커·화풍·구도는 코드가 넣으므로 프롬프트가 무너지지 않는다.
    """
    mf = vn_core.load_manifest()
    chars = {c.get("character_id"): c for c in mf.get("characters", []) if isinstance(c, dict)}
    locs = {l.get("location_id"): l for l in mf.get("locations", []) if isinstance(l, dict)}
    ask = ("아래 장면을 그림으로 그릴 때의 '동작과 구도'만 영어 한 문장(20단어 이내)으로 써라. "
           "인물 외모나 장소 묘사는 쓰지 마라. 설명 없이 그 문장만 출력하라.\n"
           f"목적: {sc.get('purpose', '')}\n동작: {sc.get('action_beat', '')}\n"
           f"감정: {sc.get('emotion', '')}\n시간: {sc.get('time', '')}")
    action = local_llm.chat([{"role": "user", "content": ask}], temperature=0.4, max_tokens=120)
    action = " ".join(str(action).strip().splitlines()).strip().strip('"')[:220]
    cam = sc.get("camera", {}) if isinstance(sc.get("camera"), dict) else {}
    parts = [visual_style(sc) + ", portrait 2:3", f"{cam.get('shot', 'medium')} shot"]
    ids = [c for c in sc.get("characters", []) if c in chars]
    if ids:
        parts.append(chars[ids[0]].get("prompt_anchor", ""))
    parts.append(action)
    for cid in ids[1:]:
        parts.append("with " + str(chars[cid].get("prompt_anchor", "")))
    if sc.get("location_id") in locs:
        parts.append(locs[sc["location_id"]].get("prompt_anchor", ""))
    t = str(sc.get("time", "")).strip()
    if t:
        parts.append(TIME_EN.get(t, t))
    return ", ".join(str(p).strip() for p in parts if p and str(p).strip())
