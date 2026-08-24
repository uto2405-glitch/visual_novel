#!/usr/bin/env python3
"""AI 웹툰 프로토콜 자동 검사기 — SCORECARD v2 의 A1~A7 을 구현한다.

검사 대상:
  project/manifest.json        프로젝트 설정 + 캐릭터/장소/소품 기준정보
  project/scenes/SCENE-*.json  장면 파일 (templates/scene.json 스키마)
  images/                      생성 이미지 (A3, 장면 파일이 경로를 가리킴)

예술적 품질은 판단하지 않는다. 그것은 SCORECARD C 항목(사람 시사)의 몫이다.
이 파일은 에이전트가 수정할 수 없다(.claude/settings.json deny).
개정이 필요하면 CLAUDE.md 의 "채점표·검사기 개정 절차"를 따른다.

의존성: 표준 라이브러리만 사용. Pillow 가 설치되어 있으면 이미지 판독에 우선 사용.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project" / "manifest.json"
SCENES_DIR = ROOT / "project" / "scenes"

SCENE_STATES = ["SCENE_PLAN", "PROMPT", "IMAGE", "REVIEW_AUTO",
                "REVIEW_HUMAN", "REVISE", "APPROVED"]
REVIEW_STATES = {"PENDING", "PASS", "REVISE", "REGENERATE", "FAIL"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
DEFAULT_MIN_LONG_EDGE = 1024

_results: list[tuple[str, str]] = []

def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


def report(code: str, status: str, msg: str) -> None:
    _results.append((code, status))
    print(f"[{code}] {status}: {msg}")


# ---------------------------------------------------------------- 이미지 판독
def _png_size(path: Path):
    with path.open("rb") as f:
        head = f.read(24)
    if len(head) == 24 and head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        w, h = struct.unpack(">II", head[16:24])
        return w, h
    return None


def _jpeg_size(path: Path):
    with path.open("rb") as f:
        if f.read(2) != b"\xff\xd8":
            return None
        while True:
            b = f.read(1)
            if not b:
                return None
            if b != b"\xff":
                continue
            marker = f.read(1)
            while marker == b"\xff":
                marker = f.read(1)
            if not marker:
                return None
            m = marker[0]
            if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                f.read(3)  # length(2) + precision(1)
                h, w = struct.unpack(">HH", f.read(4))
                return w, h
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                continue
            seg = f.read(2)
            if len(seg) != 2:
                return None
            f.seek(struct.unpack(">H", seg)[0] - 2, 1)


def image_size(path: Path):
    """(width, height) 를 돌려준다. 판독 불가면 None."""
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as im:
            return im.size
    except Exception:
        pass
    try:
        ext = path.suffix.lower()
        if ext == ".png":
            return _png_size(path)
        if ext in (".jpg", ".jpeg"):
            return _jpeg_size(path)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------- 로딩
def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def state_at_least(status: str, target: str) -> bool:
    if status not in SCENE_STATES or target not in SCENE_STATES:
        return False
    if status == "REVISE":
        return False  # 되돌아간 장면은 이후 단계 검사를 강제하지 않는다
    return SCENE_STATES.index(status) >= SCENE_STATES.index(target)


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 웹툰 프로토콜 자동 검사기")
    ap.add_argument("--scene", help="장면 단위 검사: 해당 scene_id 의 장면 검사 + 전역 무결성(A1/A5)")
    args = ap.parse_args()

    # ---- A1: 매니페스트 구조 -------------------------------------------------
    if not MANIFEST.exists():
        print("INFO: project/manifest.json 이 아직 없습니다. 첫 설정 전에는 RED 가 정상입니다.")
        print("      templates/manifest.json 을 project/manifest.json 으로 복사해 시작하세요.")
        return 1
    try:
        manifest = load_json(MANIFEST)
    except Exception as exc:
        report("A1", "FAIL", f"manifest.json 파싱 실패: {exc}")
        return finish()

    required = {"project_id", "title", "characters", "locations"}
    missing = required - set(manifest)
    if missing:
        report("A1", "FAIL", f"manifest 필수 키 누락: {sorted(missing)}")
        return finish()
    report("A1", "PASS", "매니페스트 구조 정상")

    # 기준정보 사전
    a2_ok = a4_ok = True

    def master(kind: str, key: str):
        nonlocal a2_ok
        table = {}
        for item in manifest.get(kind, []):
            mid = item.get(key)
            if not mid:
                report("A2", "FAIL", f"{kind} 항목에 {key} 없음: {item}")
                a2_ok = False
            elif mid in table:
                report("A2", "FAIL", f"{kind} {key} 중복: {mid}")
                a2_ok = False
            else:
                table[mid] = item
        return table

    characters = master("characters", "character_id")
    locations = master("locations", "location_id")
    props = master("props", "prop_id")

    min_edge = manifest.get("output", {}).get("min_long_edge_px", DEFAULT_MIN_LONG_EDGE)

    # ---- 장면 파일 수집 ------------------------------------------------------
    scene_files = sorted(SCENES_DIR.glob("*.json")) if SCENES_DIR.exists() else []
    if not scene_files:
        print("NOTE: project/scenes/ 에 장면이 아직 없습니다. 구조 검사만 수행했습니다.")
        return finish()

    scenes = []
    for sf in scene_files:
        try:
            sc = load_json(sf)
        except Exception as exc:
            report("A1", "FAIL", f"{sf.name} 파싱 실패: {exc}")
            continue
        if sc.get("scene_id") != sf.stem:
            report("A2", "FAIL", f"{sf.name}: scene_id({sc.get('scene_id')}) 와 파일명이 다름")
            a2_ok = False
        scenes.append(sc)

    # --scene 필터: 장면 단위 검사는 대상 장면만, A5/파일명 검사는 전체 유지
    if args.scene:
        target = [s for s in scenes if s.get("scene_id") == args.scene]
        if not target:
            report("A1", "FAIL", f"--scene 대상 없음: {args.scene}")
            return finish()
    else:
        target = scenes

    # ---- A2 / A4: 참조 무결성 ------------------------------------------------
    for sc in target:
        sid = sc.get("scene_id", "?")
        status = sc.get("status", "")
        if status not in SCENE_STATES:
            report("A2", "FAIL", f"{sid}: status 값이 유효하지 않음: {status!r}")
            a2_ok = False
        for key in ("scene_id", "scene_order", "location_id", "characters",
                    "dialogue", "assets", "review"):
            if key not in sc:
                report("A2", "FAIL", f"{sid}: 필수 키 없음: {key}")
                a2_ok = False
        if sc.get("location_id") not in locations:
            report("A2", "FAIL", f"{sid}: 미등록 location_id {sc.get('location_id')!r}")
            a2_ok = False
        if not sc.get("characters"):
            report("A2", "FAIL", f"{sid}: characters 목록이 비어 있음")
            a2_ok = False
        for cid in sc.get("characters", []):
            if cid not in characters:
                report("A2", "FAIL", f"{sid}: 미등록 character_id {cid!r}")
                a2_ok = False
        for pid in sc.get("props", []):
            if pid not in props:
                report("A2", "FAIL", f"{sid}: 미등록 prop_id {pid!r}")
                a2_ok = False
        for i, line in enumerate(sc.get("dialogue", [])):
            spk = line.get("speaker_id")
            if "text" not in line:
                report("A2", "FAIL", f"{sid}: dialogue[{i}] 에 text 키 없음")
                a2_ok = False
            if spk not in characters:
                report("A4", "FAIL", f"{sid}: dialogue[{i}] speaker_id {spk!r} 미등록")
                a4_ok = False
            elif spk not in sc.get("characters", []):
                report("A4", "FAIL", f"{sid}: dialogue[{i}] speaker_id {spk!r} 는 이 장면 등장 목록에 없음")
                a4_ok = False
    if a2_ok:
        report("A2", "PASS", "장면 필수 데이터·참조 무결성 정상")
    if a4_ok:
        report("A4", "PASS", "대사 화자 ID 모두 등장 캐릭터와 일치")

    # ---- A5: 장면 순서 -------------------------------------------------------
    orders = [sc.get("scene_order") for sc in scenes]
    if any(not isinstance(o, int) for o in orders):
        report("A5", "FAIL", "scene_order 가 정수가 아닌 장면이 있음")
    elif len(set(orders)) != len(orders):
        report("A5", "FAIL", f"scene_order 중복: {sorted(orders)}")
    elif sorted(orders) != list(range(1, len(orders) + 1)):
        report("A5", "FAIL", f"scene_order 가 1부터 연속이 아님: {sorted(orders)}")
    else:
        report("A5", "PASS", f"장면 {len(orders)}개, 순서 1~{len(orders)} 연속")

    # ---- A6: 프롬프트 앵커 ---------------------------------------------------
    a6_ok, a6_checked = True, 0
    for sc in target:
        sid = sc.get("scene_id", "?")
        prompt = sc.get("prompt", {}) or {}
        out = (prompt.get("grok_output") or "").strip()
        if not (state_at_least(sc.get("status", ""), "IMAGE") or out):
            continue  # PROMPT 이전 단계는 검사하지 않는다
        a6_checked += 1
        if not out:
            report("A6", "FAIL", f"{sid}: 상태가 IMAGE 이상인데 prompt.grok_output 이 비어 있음")
            a6_ok = False
            continue
        for cid in sc.get("characters", []):
            anchor = (characters.get(cid, {}).get("prompt_anchor") or "").strip()
            if not anchor:
                report("A6", "FAIL", f"{sid}: {cid} 의 prompt_anchor 가 기준정보에 없음")
                a6_ok = False
            elif anchor not in out and cid not in out:
                report("A6", "FAIL", f"{sid}: 프롬프트에 {cid} 앵커가 포함되지 않음")
                a6_ok = False
        lid = sc.get("location_id")
        lanchor = (locations.get(lid, {}).get("prompt_anchor") or "").strip()
        if lanchor and lanchor not in out and (lid or "") not in out:
            report("A6", "FAIL", f"{sid}: 프롬프트에 장소 앵커({lid})가 포함되지 않음")
            a6_ok = False
    if a6_checked == 0:
        report("A6", "SKIP", "PROMPT 단계 이후 장면이 없어 검사 생략")
    elif a6_ok:
        report("A6", "PASS", f"프롬프트 앵커 정상 (장면 {a6_checked}개)")

    # ---- A3: 이미지 규격 -----------------------------------------------------
    a3_ok, a3_checked = True, 0
    for sc in target:
        sid = sc.get("scene_id", "?")
        if not state_at_least(sc.get("status", ""), "IMAGE"):
            continue
        a3_checked += 1
        assets = sc.get("assets", {}) or {}
        raws = assets.get("raw_images", []) or []
        selected = (assets.get("selected_image") or "").strip()
        if not raws and not selected:
            report("A3", "FAIL", f"{sid}: 상태가 IMAGE 이상인데 이미지 경로가 없음")
            a3_ok = False
            continue
        for rel in raws:
            if not (ROOT / rel).exists():
                report("A3", "FAIL", f"{sid}: 후보 이미지 파일 없음: {rel}")
                a3_ok = False
        if selected:
            p = ROOT / selected
            if not p.exists():
                report("A3", "FAIL", f"{sid}: selected_image 파일 없음: {selected}")
                a3_ok = False
                continue
            if p.suffix.lower() not in IMAGE_EXTS:
                report("A3", "FAIL", f"{sid}: 허용되지 않는 파일 형식: {p.suffix}")
                a3_ok = False
                continue
            size = image_size(p)
            if size is None:
                report("A3", "SKIP", f"{sid}: {p.name} 픽셀 크기 판독 불가 — 수동 확인 필요")
            elif max(size) < min_edge:
                report("A3", "FAIL", f"{sid}: {p.name} 긴 변 {max(size)}px < 기준 {min_edge}px")
                a3_ok = False
        elif state_at_least(sc.get("status", ""), "REVIEW_HUMAN"):
            report("A3", "FAIL", f"{sid}: REVIEW_HUMAN 이상 단계는 selected_image 가 필요함")
            a3_ok = False
    if a3_checked == 0:
        report("A3", "SKIP", "IMAGE 단계 이후 장면이 없어 검사 생략")
    elif a3_ok:
        report("A3", "PASS", f"이미지 존재·형식·해상도 기준 충족 (장면 {a3_checked}개)")

    # ---- A7: 검수 상태 기록 --------------------------------------------------
    a7_ok = True
    for sc in target:
        sid = sc.get("scene_id", "?")
        rv = sc.get("review", {}) or {}
        auto, human = rv.get("auto"), rv.get("human")
        for label, val in (("auto", auto), ("human", human)):
            if val not in REVIEW_STATES:
                report("A7", "FAIL", f"{sid}: review.{label} 값이 유효하지 않음: {val!r}")
                a7_ok = False
        if sc.get("status") == "APPROVED" and not (auto == "PASS" and human == "PASS"):
            report("A7", "FAIL", f"{sid}: APPROVED 인데 auto/human 이 모두 PASS 가 아님")
            a7_ok = False
        if sc.get("status") == "REVIEW_HUMAN" and auto != "PASS":
            report("A7", "FAIL", f"{sid}: REVIEW_HUMAN 단계는 auto=PASS 가 선행되어야 함")
            a7_ok = False
    if a7_ok:
        report("A7", "PASS", "검수 상태 기록 정상")

    # ---- A8: API 키 유출 스캔 ----------------------------------------------
    key_pat = re.compile(rb"xai-[A-Za-z0-9_-]{20,}")
    text_exts = {".json", ".md", ".py", ".txt", ".cfg", ".ini", ".yaml", ".yml"}
    skip_parts = {".git", "__pycache__", "images"}
    leaks = []
    for f in ROOT.rglob("*"):
        if not f.is_file() or set(f.parts) & skip_parts:
            continue
        if f.suffix.lower() not in text_exts and not f.name.startswith(".env"):
            continue
        try:
            if f.stat().st_size > 2_000_000:
                continue
            if key_pat.search(f.read_bytes()):
                leaks.append(f.relative_to(ROOT).as_posix())
        except OSError:
            continue
    if leaks:
        for path_str in leaks:
            report("A8", "FAIL", f"API 키 패턴 발견: {path_str} — 파일에서 제거하고 해당 키를 즉시 폐기·재발급하세요")
    else:
        report("A8", "PASS", "저장소 내 API 키 패턴 없음 (키는 환경변수로만)")

    return finish()


def finish() -> int:
    fails = sum(1 for _, s in _results if s == "FAIL")
    skips = sum(1 for _, s in _results if s == "SKIP")
    print("-" * 56)
    if fails:
        print(f"RESULT: FAIL — 실패 {fails}건, 생략 {skips}건")
        return 1
    print(f"RESULT: PASS — 자동 검사 통과 (생략 {skips}건)")
    print("NOTE: 화풍 일관성·연출·인쇄 발색은 SCORECARD C 항목의 사람 시사로 판정합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
