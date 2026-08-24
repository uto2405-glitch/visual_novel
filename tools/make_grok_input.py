#!/usr/bin/env python3
"""Grok 입력 패키지 자동 조립 — 매번 손으로 붙여넣던 컨텍스트를 한 파일로 만든다.

사용법:
  python tools/make_grok_input.py SCENE-001

동작:
  지시서(templates/grok-prompt-brief.md) + 프로젝트 정보 + 등장 캐릭터/장소
  기준정보(prompt_anchor, 레퍼런스 목록) + 장면 계획 + 직전 장면 연속성 +
  대사 배치 요구를 하나의 텍스트로 조립해
  project/grok_inputs/<scene_id>.txt 로 저장하고 화면에도 출력한다.
  이 내용을 그대로 Grok 에 붙여넣으면 된다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project" / "manifest.json"
SCENES = ROOT / "project" / "scenes"
BRIEF = ROOT / "templates" / "grok-prompt-brief.md"
OUT_DIR = ROOT / "project" / "grok_inputs"

def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def kv(label: str, value) -> str:
    return f"- {label}: {value}" if value not in ("", None, []) else ""


def build_input(sid: str) -> str:
    """장면 sid 의 Grok 입력 패키지를 조립해 문자열로 돌려준다. (API 모드에서도 사용)"""
    scene_file = SCENES / f"{sid}.json"
    if not MANIFEST.exists():
        raise FileNotFoundError("project/manifest.json 이 없습니다.")
    if not scene_file.exists():
        raise FileNotFoundError(f"{scene_file.relative_to(ROOT)} 이 없습니다.")

    mf = load(MANIFEST)
    sc = load(scene_file)
    chars = {c.get("character_id"): c for c in mf.get("characters", [])}
    locs = {l.get("location_id"): l for l in mf.get("locations", [])}
    props = {p.get("prop_id"): p for p in mf.get("props", [])}

    lines: list[str] = []
    add = lines.append

    # 1) 역할 지시서
    add(BRIEF.read_text(encoding="utf-8").strip())
    add("")

    # 2) 프로젝트
    add("==== 프로젝트 ====")
    add(kv("제목", mf.get("title")))
    add(kv("출력 비율", mf.get("output", {}).get("aspect_ratio")))
    add(kv("작품 전체 화풍", sc.get("visual_style") or "장면 파일 visual_style 참고"))
    add("")

    # 3) 등장 캐릭터 기준정보
    add("==== 등장 캐릭터 (기준정보 유지 필수) ====")
    for cid in sc.get("characters", []):
        c = chars.get(cid, {})
        add(f"[{cid}] {c.get('name', '')} (version {c.get('version', 1)})")
        prof = c.get("profile", {})
        for k, label in (("age", "나이"), ("gender_presentation", "성별 표현"),
                         ("hair", "머리"), ("eyes", "눈"), ("build", "체형"),
                         ("wardrobe", "복장")):
            line = kv(label, prof.get(k))
            if line:
                add(line)
        if prof.get("signature_props"):
            add(kv("시그니처 소품", ", ".join(prof["signature_props"])))
        add(f"- prompt_anchor (SCENE_PROMPT 에 원문 그대로 포함): {c.get('prompt_anchor', '')}")
        if c.get("reference_images"):
            add("- 레퍼런스 이미지 (외부 이미지 AI에 반드시 함께 첨부):")
            for r in c["reference_images"]:
                add(f"    * {r}")
        add("")

    # 4) 장소
    lid = sc.get("location_id")
    l = locs.get(lid, {})
    add("==== 장소 ====")
    add(f"[{lid}] {l.get('name', '')}")
    for line in (kv("설명", l.get("description")),
                 f"- prompt_anchor (원문 그대로 포함): {l.get('prompt_anchor', '')}"):
        if line:
            add(line)
    if l.get("reference_images"):
        add("- 레퍼런스 이미지 (외부 이미지 AI에 함께 첨부):")
        for r in l["reference_images"]:
            add(f"    * {r}")
    add("")

    # 5) 소품
    if sc.get("props"):
        add("==== 소품 ====")
        for pid in sc["props"]:
            p = props.get(pid, {})
            add(f"[{pid}] {p.get('name', '')} — {p.get('description', '')}")
            if p.get("prompt_anchor"):
                add(f"- prompt_anchor: {p['prompt_anchor']}")
        add("")

    # 6) 이번 장면 계획
    add(f"==== 이번 장면: {sid} (order {sc.get('scene_order')}) ====")
    for line in (kv("목적", sc.get("purpose")),
                 kv("행동 비트", sc.get("action_beat")),
                 kv("감정", sc.get("emotion")),
                 kv("시간대", sc.get("time")),
                 kv("화풍", sc.get("visual_style"))):
        if line:
            add(line)
    cam = sc.get("camera", {})
    add(f"- 카메라: shot={cam.get('shot','')} / angle={cam.get('angle','')} / "
        f"framing={cam.get('framing','')} / focus={cam.get('focus','')}")
    add("")

    # 7) 직전 장면 연속성
    prev = None
    for f in SCENES.glob("SCENE-*.json"):
        try:
            s = load(f)
        except (ValueError, OSError):
            continue  # 무관한 형제 장면이 손상돼도 이번 장면 조립은 계속된다
        if isinstance(s, dict) and s.get("scene_order") == sc.get("scene_order", 0) - 1:
            prev = s
            break
    add("==== 직전 장면 연속성 ====")
    if prev:
        add(f"직전 장면 {prev.get('scene_id')}:")
        for line in (kv("행동", prev.get("action_beat")),
                     kv("감정", prev.get("emotion")),
                     kv("화풍", prev.get("visual_style"))):
            if line:
                add(line)
        sel = prev.get("assets", {}).get("selected_image", "")
        if sel:
            add(f"- 확정 이미지: {Path(sel).name} (이 장면과 시각적으로 이어져야 함)")
    else:
        add("첫 장면 — 연속성 제약 없음. CONTINUITY_NOTES 에는 다음 장면으로 넘길 요소를 적을 것.")
    add("")

    # 8) 대사 배치 (원문 금지)
    add("==== 대사 배치 요구 ====")
    add("대사 원문은 프롬프트에 절대 넣지 말 것. 아래 위치에 빈 공간만 확보:")
    for i, d in enumerate(sc.get("dialogue", []), 1):
        spk = chars.get(d.get("speaker_id"), {}).get("name", d.get("speaker_id"))
        add(f"- 대사 {i}: 화자 {spk} / 위치 {d.get('placement', 'bottom')}")
    add("")
    add("위 정보로 SCENE_PROMPT / NEGATIVE_PROMPT / CONTINUITY_NOTES / DIALOGUE_PLACEMENT 를 출력하라.")

    return "\n".join(line for line in lines if line is not None)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    sid = sys.argv[1]
    try:
        text = build_input(sid)
    except FileNotFoundError as exc:
        print(f"오류: {exc}")
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / f"{sid}.txt"
    out_file.write_text(text + "\n", encoding="utf-8")

    try:
        print(text)
        print("-" * 56)
        print(f"저장됨: {out_file.relative_to(ROOT)}")
        print(f"다음: 위 내용을 Grok 에 붙여넣고, 출력을 받아서")
        print(f"      python tools/advance_scene.py set-prompt {sid} --file <저장한파일>")
    except BrokenPipeError:
        pass  # head 등으로 파이프가 먼저 닫혀도 파일 저장은 완료됨
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
