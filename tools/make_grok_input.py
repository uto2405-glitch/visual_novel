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

경로·JSON·화풍 문구는 vn_core 하나에서 온다(같은 문구를 여러 도구가 복제하면
컷 사이 화풍이 갈린다). 오류 타입은 기존 호출부(grok_api·webapp)와의 호환을 위해
FileNotFoundError 를 유지한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core  # noqa: E402

ROOT = vn_core.ROOT
MANIFEST = vn_core.MANIFEST
SCENES = vn_core.SCENES
BRIEF = vn_core.TEMPLATES / "grok-prompt-brief.md"
OUT_DIR = vn_core.PROJECT / "grok_inputs"

# 화풍 문구·JSON 로딩은 vn_core 가 유일한 출처다. (기존 이름은 호출 호환을 위해 남긴다.)
DEFAULT_VISUAL_STYLE = vn_core.DEFAULT_VISUAL_STYLE
load = vn_core.load_json
visual_style = vn_core.visual_style


def kv(label: str, value) -> str:
    return f"- {label}: {value}" if value not in ("", None, []) else ""


def _prev_scene(sc: dict) -> dict | None:
    """직전 order 의 장면 — 이름 규칙으로 먼저 찍고, 어긋날 때만 폴더를 훑는다.

    장면이 늘어날수록 '전부 읽어서 하나 고르기'는 그대로 비용이 된다. 대부분의 작품은
    SCENE-00N 과 order 가 나란하므로 한 번의 파일 읽기로 끝난다.
    """
    try:
        want = int(sc.get("scene_order") or 0) - 1
    except (TypeError, ValueError):
        return None
    if want < 1:
        return None
    guess = SCENES / f"SCENE-{want:03d}.json"
    if guess.exists():
        s = vn_core.load_json_safe(guess, {})
        if s.get("scene_order") == want:
            return s
    for f in sorted(SCENES.glob("SCENE-*.json")):
        s = vn_core.load_json_safe(f, {})   # 무관한 형제 장면이 손상돼도 조립은 계속된다
        if s.get("scene_order") == want:
            return s
    return None


def build_input(sid: str) -> str:
    """장면 sid 의 Grok 입력 패키지를 조립해 문자열로 돌려준다. (API 모드에서도 사용)"""
    if not vn_core.is_scene_id(sid):
        # 형식 검증이 파일 접근보다 먼저다 — '../x' 같은 값이 장면 폴더 밖에 닿지 못하게 한다.
        raise FileNotFoundError(f"장면 ID 는 SCENE-001 형식이어야 합니다: {sid!r}")
    scene_file = SCENES / f"{sid}.json"
    if not MANIFEST.exists():
        raise FileNotFoundError("project/manifest.json 이 없습니다.")
    if not scene_file.exists():
        raise FileNotFoundError(f"project/scenes/{sid}.json 이 없습니다.")
    if not BRIEF.exists():
        raise FileNotFoundError("templates/grok-prompt-brief.md 가 없습니다(지시서 원본).")

    mf = load(MANIFEST)
    sc = load(scene_file)
    if not isinstance(mf, dict) or not isinstance(sc, dict):
        raise FileNotFoundError("manifest 또는 장면 파일의 최상위가 객체({...})가 아닙니다.")
    chars = {c.get("character_id"): c for c in mf.get("characters", []) if isinstance(c, dict)}
    locs = {l.get("location_id"): l for l in mf.get("locations", []) if isinstance(l, dict)}
    props = {p.get("prop_id"): p for p in mf.get("props", []) if isinstance(p, dict)}

    lines: list[str] = []
    add = lines.append

    def add_kv(label: str, value) -> None:
        """값이 있을 때만 한 줄 추가 — 빈 항목이 빈 줄로 남아 절 사이 여백을 흐리지 않게."""
        line = kv(label, value)
        if line:
            add(line)

    # 1) 역할 지시서
    add(BRIEF.read_text(encoding="utf-8").strip())
    add("")

    # 2) 프로젝트
    add("==== 프로젝트 ====")
    add_kv("제목", mf.get("title"))
    out = mf.get("output") if isinstance(mf.get("output"), dict) else {}
    add_kv("출력 비율", out.get("aspect_ratio"))
    add_kv("작품 전체 화풍", visual_style(mf, sc))
    add("")

    # 3) 등장 캐릭터 기준정보
    add("==== 등장 캐릭터 (기준정보 유지 필수) ====")
    for cid in (sc.get("characters") if isinstance(sc.get("characters"), list) else []):
        c = chars.get(cid) or {}
        add(f"[{cid}] {c.get('name', '')} (version {c.get('version', 1)})")
        prof = c.get("profile") if isinstance(c.get("profile"), dict) else {}
        for k, label in (("age", "나이"), ("gender_presentation", "성별 표현"),
                         ("hair", "머리"), ("eyes", "눈"), ("build", "체형"),
                         ("wardrobe", "복장")):
            add_kv(label, prof.get(k))
        if prof.get("signature_props"):
            add_kv("시그니처 소품", ", ".join(str(p) for p in prof["signature_props"]))
        add(f"- prompt_anchor (SCENE_PROMPT 에 원문 그대로 포함): {c.get('prompt_anchor', '')}")
        if c.get("reference_images"):
            add("- 레퍼런스 이미지 (외부 이미지 AI에 반드시 함께 첨부):")
            for r in c["reference_images"]:
                add(f"    * {r}")
        add("")

    # 4) 장소
    lid = sc.get("location_id")
    l = locs.get(lid) or {}
    add("==== 장소 ====")
    add(f"[{lid}] {l.get('name', '')}")
    add_kv("설명", l.get("description"))
    add(f"- prompt_anchor (원문 그대로 포함): {l.get('prompt_anchor', '')}")
    if l.get("reference_images"):
        add("- 레퍼런스 이미지 (외부 이미지 AI에 함께 첨부):")
        for r in l["reference_images"]:
            add(f"    * {r}")
    add("")

    # 5) 소품
    if sc.get("props"):
        add("==== 소품 ====")
        for pid in sc["props"]:
            p = props.get(pid) or {}
            add(f"[{pid}] {p.get('name', '')} — {p.get('description', '')}")
            if p.get("prompt_anchor"):
                add(f"- prompt_anchor: {p['prompt_anchor']}")
        add("")

    # 6) 이번 장면 계획
    add(f"==== 이번 장면: {sid} (order {sc.get('scene_order')}) ====")
    add_kv("목적", sc.get("purpose"))
    add_kv("행동 비트", sc.get("action_beat"))
    add_kv("감정", sc.get("emotion"))
    add_kv("시간대", sc.get("time"))
    add_kv("화풍", sc.get("visual_style"))
    cam = sc.get("camera") if isinstance(sc.get("camera"), dict) else {}
    add(f"- 카메라: shot={cam.get('shot','')} / angle={cam.get('angle','')} / "
        f"framing={cam.get('framing','')} / focus={cam.get('focus','')}")
    add("")

    # 7) 직전 장면 연속성
    prev = _prev_scene(sc)
    add("==== 직전 장면 연속성 ====")
    if prev:
        add(f"직전 장면 {prev.get('scene_id')}:")
        add_kv("행동", prev.get("action_beat"))
        add_kv("감정", prev.get("emotion"))
        add_kv("화풍", prev.get("visual_style"))
        assets = prev.get("assets") if isinstance(prev.get("assets"), dict) else {}
        sel = str(assets.get("selected_image", "") or "").strip()
        if sel:
            add(f"- 확정 이미지: {Path(sel).name} (이 장면과 시각적으로 이어져야 함)")
    else:
        add("첫 장면 — 연속성 제약 없음. CONTINUITY_NOTES 에는 다음 장면으로 넘길 요소를 적을 것.")
    add("")

    # 8) 대사 배치 (원문 금지)
    add("==== 대사 배치 요구 ====")
    add("대사 원문은 프롬프트에 절대 넣지 말 것. 아래 위치에 빈 공간만 확보:")
    dialogue = sc.get("dialogue") if isinstance(sc.get("dialogue"), list) else []
    for i, d in enumerate((d for d in dialogue if isinstance(d, dict)), 1):
        spk = (chars.get(d.get("speaker_id")) or {}).get("name") or d.get("speaker_id")
        add(f"- 대사 {i}: 화자 {spk} / 위치 {d.get('placement', 'bottom')}")
    add("")
    add("위 정보로 SCENE_PROMPT / NEGATIVE_PROMPT / CONTINUITY_NOTES / DIALOGUE_PLACEMENT 를 출력하라.")

    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    sid = sys.argv[1]
    try:
        text = build_input(sid)
    except (FileNotFoundError, vn_core.VNError) as exc:
        print(f"오류: {exc}")
        return 2
    out_file = OUT_DIR / f"{sid}.txt"
    vn_core.atomic_write_text(out_file, text + "\n")   # 저장 중 중단돼도 반쪽 파일이 남지 않는다

    try:
        print(text)
        print("-" * 56)
        print(f"저장됨: {out_file.relative_to(ROOT).as_posix()}")
        print("다음: 위 내용을 Grok 에 붙여넣고, 출력을 받아서")
        print(f"      python tools/advance_scene.py set-prompt {sid} --file <저장한파일>")
    except BrokenPipeError:
        pass  # head 등으로 파이프가 먼저 닫혀도 파일 저장은 완료됨
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
