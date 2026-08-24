#!/usr/bin/env python3
"""프롬프트 조립 — 장면 이미지 프롬프트와 스토리 챗 시스템 프롬프트.

역할 분담이 이 파일의 전부다:

  * **앵커(인물·장소 원문)는 코드가 조립한다** — 검사기 A6 를 구조적으로 보장하고,
    컷마다 얼굴·배경이 흔들리지 않게 한다.
  * **LLM 은 동작·구도 한 문장만 만든다** — 외모·장소를 다시 묘사하면 앵커와 충돌한다.

저장소 규약: **모델에 보내는 프롬프트 문자열은 prompt_build 와 vn_compose 에만 있다.**
HTTP 라우트(webapp)는 여기서 조립된 것을 넘기기만 한다 — 같은 프롬프트가 웹·CLI 로
갈라져 서로 다른 말을 하게 되는 것을 막는 경계다.

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

STORYLINE_CHARS = 1500   # 컨텍스트에 싣는 스토리라인 길이 상한(토큰·비용 관리)
CONTEXT_SCENES = 40      # 컨텍스트에 싣는 장면 요약 수 상한

STORY_SYSTEM_HEAD = (
    "너는 비주얼 노벨/웹툰 스토리 기획 파트너다. 한국어로 간결하고 구체적으로 답한다.\n"
    "아래는 지금 작업 중인 작품의 현재 상태다. 이 설정과 이어지도록 제안하고, "
    "새 인물·장소를 만들 때만 새로 제안하라.\n\n")


def visual_style(sc: dict | None = None) -> str:
    """작품 화풍 — manifest.output.visual_style → 장면 visual_style → 기본 문구."""
    return vn_core.visual_style(None, sc)


def storyline_text() -> str:
    """project/story/storyline.md — 없거나 읽을 수 없으면 빈 문자열(대화를 막지 않는다)."""
    try:
        return (vn_core.STORY / "storyline.md").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def story_context() -> str:
    """스토리 챗이 '지금 이 작품'을 알고 답하도록 붙이는 요약 컨텍스트.

    작품 제목 · 등장인물 · 장소 · 현재 스토리라인 · 구성된 장면 목록을 한 덩어리로 만든다.
    (사람이 읽어도 이해되는 형태 그대로 — 모델이 이 형식을 가장 잘 따라 온다.)
    """
    mf = vn_core.load_manifest()
    out = []
    if str(mf.get("title", "")).strip():
        out.append(f"[작품] {mf['title']}")
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    if chars:
        out.append("[등장인물] " + " / ".join(
            f"{c.get('character_id')} {c.get('name', '')}"
            + (f"({(c.get('profile') or {}).get('age', '')}세)"
               if (c.get('profile') or {}).get('age') else "")
            for c in chars))
    locs = [l for l in mf.get("locations", []) if isinstance(l, dict)]
    if locs:
        out.append("[장소] " + " / ".join(
            f"{l.get('location_id')} {l.get('name', '')}" for l in locs))
    sl = storyline_text()
    if sl:
        out.append("[현재 스토리라인]\n" + sl[:STORYLINE_CHARS])
    lines = []
    scene_files = sorted(vn_core.SCENES.glob("SCENE-*.json")) if vn_core.SCENES.exists() else []
    for f in scene_files[:CONTEXT_SCENES]:
        sc = vn_core.load_json_safe(f, {})
        lines.append(f"- {sc.get('scene_id')} [{sc.get('status', '')}] "
                     f"{str(sc.get('purpose', ''))[:40]}")
    if lines:
        out.append("[구성된 장면]\n" + "\n".join(lines))
    return "\n".join(out)


def story_system_message() -> dict:
    """스토리 챗의 system 메시지 — 역할 지시 + 현재 작품 컨텍스트."""
    return {"role": "system", "content": STORY_SYSTEM_HEAD + story_context()}


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
