#!/usr/bin/env python3
"""장면 상태 전이 자동화 도구 — JSON 수동 편집을 없앤다.

각 명령의 상세 옵션: python tools/advance_scene.py <명령> --help

  status                          전체 진행 현황표 + 다음 할 일
  new [SCENE-ID]                  다음 번호 장면 생성 (id·order 자동)
  set-prompt SID [--file F]       Grok 출력 저장, 상태 → PROMPT (미지정 시 붙여넣기,
                                  종료: Windows Ctrl+Z+Enter / mac·Linux Ctrl+D)
  add-images SID 파일...           후보 복사·기록 → 자동 검사 → PASS 시 REVIEW_HUMAN
  select SID <번호|파일명>          후보 1장을 selected_image 로 지정
  approve SID                     검사 PASS 확인 후 APPROVED 잠금 (FAIL 시 롤백)
  revise SID <단계> [--note 사유]   SCENE_PLAN/PROMPT/IMAGE 로 되돌림 (자료 보존)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "project" / "scenes"
TEMPLATE = ROOT / "templates" / "scene.json"
MANIFEST = ROOT / "project" / "manifest.json"
RAW_DIR = ROOT / "images" / "raw"
CHECKER = ROOT / "tools" / "check_protocol.py"

BACK_STATES = ("SCENE_PLAN", "PROMPT", "IMAGE")
WRITE_LOCK = threading.RLock()  # 웹 스튜디오의 동시 요청에서 read-modify-write 를 직렬화


def _console_guard() -> None:
    """비 UTF-8 콘솔(cp437 등)에서 한글 출력이 크래시하지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


def die(msg: str) -> NoReturn:
    print(f"오류: {msg}")
    sys.exit(2)


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"파일 없음: {path.relative_to(ROOT)}")
    except Exception as exc:
        die(f"{path.name} 파싱 실패: {exc}")
    if not isinstance(data, dict):
        die(f"{path.name}: JSON 최상위가 객체({{...}})가 아닙니다. 파일을 확인하세요.")
    return data


def save(path: Path, data: dict) -> None:
    """원자적 저장: 임시 파일에 쓴 뒤 교체 — 저장 중 강제 종료돼도 원본이 깨지지 않는다."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def scene_path(sid: str) -> Path:
    return SCENES / f"{sid}.json"


def run_checker(sid: str | None = None) -> tuple[int, str]:
    cmd = [sys.executable, str(CHECKER)]
    if sid:
        cmd += ["--scene", sid]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr)


def all_scenes() -> list[dict]:
    out = []
    if SCENES.exists():
        for f in sorted(SCENES.glob("SCENE-*.json")):
            out.append(load(f))
    return out


def apply_prompt(sid: str, text: str) -> None:
    """Grok 출력을 장면에 반영하고 상태를 PROMPT 로 올린다. (수동/API 모드 공용)"""
    text = text.strip()
    if not text:
        die("입력이 비어 있습니다.")
    path = scene_path(sid)
    sc = load(path)
    sc["prompt"]["grok_output"] = text
    sc["status"] = "PROMPT"
    save(path, sc)
    print("상태 → PROMPT")
    code, out = run_checker(sid)
    fails = [l for l in out.splitlines() if "FAIL" in l]
    if fails:
        print("자동 검사 경고:")
        print("\n".join(fails))
    else:
        print("앵커 검사 포함 자동 검사 통과. 다음: 외부 이미지 AI에서 후보 생성")
        print("  (레퍼런스 이미지 첨부를 잊지 마세요 → manifest 의 reference_images)")
        print(f"  python tools/advance_scene.py add-images {sid} <파일...>")


# ---------------------------------------------------------------- 명령들
def cmd_new(args: argparse.Namespace) -> None:
    scenes = all_scenes()
    nums = [int(m.group(1)) for s in scenes
            if (m := re.fullmatch(r"SCENE-(\d+)", s.get("scene_id", "")))]
    sid = args.scene_id or f"SCENE-{(max(nums) + 1 if nums else 1):03d}"
    if not re.fullmatch(r"SCENE-\d+", sid):
        die(f"scene_id 는 SCENE-<숫자> 형식이어야 합니다: {sid!r} "
            "(비표준 이름은 검사기·진행표에서 누락되어 order 무결성을 깹니다).")
    path = scene_path(sid)
    if path.exists():
        die(f"{sid} 는 이미 존재합니다.")
    sc = load(TEMPLATE)
    sc["scene_id"] = sid
    sc["scene_order"] = max((s.get("scene_order", 0) for s in scenes), default=0) + 1
    if MANIFEST.exists():
        mf = load(MANIFEST)
        chars = [c.get("character_id") for c in mf.get("characters", []) if c.get("character_id")]
        locs = [l.get("location_id") for l in mf.get("locations", []) if l.get("location_id")]
        if chars:
            sc["characters"] = chars[:1]
            for line in sc.get("dialogue", []):
                line["speaker_id"] = chars[0]
        if locs:
            sc["location_id"] = locs[0]
    SCENES.mkdir(parents=True, exist_ok=True)
    save(path, sc)
    print(f"생성: project/scenes/{sid}.json (scene_order={sc['scene_order']})")
    print("다음: 장면 계획(purpose/action_beat/emotion/camera/dialogue)을 채운 뒤")
    print(f"      python tools/make_grok_input.py {sid}")


def cmd_set_prompt(args: argparse.Namespace) -> None:
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        print("Grok 출력 전체를 붙여넣으세요. (종료: Windows Ctrl+Z+Enter / mac·Linux Ctrl+D)")
        text = sys.stdin.read()
    print("저장 완료.", end=" ")
    apply_prompt(args.scene_id, text)


def cmd_add_images(args: argparse.Namespace) -> None:
    sid = args.scene_id
    path = scene_path(sid)
    sc = load(path)
    dest = RAW_DIR / sid
    # 부분 복사 방지: 하나라도 없으면 아무것도 복사하지 않고 종료(고아 파일 방지)
    srcs = [Path(f).expanduser() for f in args.files]
    missing = [str(s) for s in srcs if not s.exists()]
    if missing:
        die("파일 없음: " + ", ".join(missing))
    dest.mkdir(parents=True, exist_ok=True)
    for src in srcs:
        target = dest / src.name
        n = 2
        while target.exists():
            target = dest / f"{src.stem}-{n}{src.suffix}"
            n += 1
        shutil.copy2(src, target)
        sc["assets"]["raw_images"].append(target.relative_to(ROOT).as_posix())
    sc["status"] = "IMAGE"
    save(path, sc)
    print(f"후보 {len(args.files)}장 등록:")
    for i, r in enumerate(sc["assets"]["raw_images"], 1):
        print(f"  [{i}] {r}")
    code, out = run_checker(sid)
    sc = load(path)
    if code == 0:
        sc["review"]["auto"] = "PASS"
        sc["status"] = "REVIEW_HUMAN"
        save(path, sc)
        print("자동 검사 PASS → 상태 REVIEW_HUMAN")
        print(f"다음: 시사 후  python tools/advance_scene.py select {sid} <번호>")
    else:
        sc["review"]["auto"] = "FAIL"
        save(path, sc)
        print("자동 검사 FAIL — 아래 원인을 해결하세요:")
        print("\n".join(l for l in out.splitlines() if "FAIL" in l))


def cmd_select(args: argparse.Namespace) -> None:
    sid = args.scene_id
    path = scene_path(sid)
    sc = load(path)
    raws = sc["assets"].get("raw_images", [])
    if not raws:
        die("등록된 후보 이미지가 없습니다. add-images 를 먼저 실행하세요.")
    key = args.candidate
    idx = None
    if key.isdecimal():
        try:
            idx = int(key)  # isdecimal 이라도 int() 실패 가능(위첨자 등) → 방어
        except ValueError:
            idx = None
    if idx is not None:
        if not 1 <= idx <= len(raws):
            die(f"번호 범위는 1~{len(raws)} 입니다.")
        chosen = raws[idx - 1]
    else:
        matches = [r for r in raws if Path(r).name == key or r == key]
        if len(matches) != 1:
            die(f"'{key}' 와 일치하는 후보가 {len(matches)}개입니다.")
        chosen = matches[0]
    sc["assets"]["selected_image"] = chosen
    save(path, sc)
    print(f"선택: {chosen}")
    code, out = run_checker(sid)
    if code == 0:
        print(f"다음: python tools/advance_scene.py approve {sid}")
    else:
        print("\n".join(l for l in out.splitlines() if "FAIL" in l))


def do_approve(sid: str) -> None:
    """승인 잠금 공용 로직 — 검사 FAIL 시 원상 복구 후 RuntimeError."""
    with WRITE_LOCK:
        path = scene_path(sid)
        original = path.read_text(encoding="utf-8")
        sc = json.loads(original)
        if sc.get("status") != "REVIEW_HUMAN":
            raise RuntimeError(
                f"REVIEW_HUMAN 단계에서만 승인할 수 있습니다(현재: {sc.get('status')}). "
                "add-images → select 를 먼저 완료하세요.")
        if not (sc["assets"].get("selected_image") or "").strip():
            raise RuntimeError("selected_image 가 없습니다. 이미지를 먼저 선택하세요.")
        sc["review"]["auto"] = "PASS"
        sc["review"]["human"] = "PASS"
        sc["status"] = "APPROVED"
        save(path, sc)
        code, out = run_checker(sid)
        if code != 0:
            path.write_text(original, encoding="utf-8")  # 롤백
            raise RuntimeError("자동 검사 FAIL — 승인을 되돌렸습니다.\n"
                               + "\n".join(l for l in out.splitlines() if "FAIL" in l))


def cmd_approve(args: argparse.Namespace) -> None:
    sid = args.scene_id
    try:
        do_approve(sid)
    except RuntimeError as exc:
        print(f"승인 불가 — {exc}")
        sys.exit(1)
    print(f"{sid} APPROVED — 장면 잠금 완료.")
    print("사람 시사에서 확인했어야 하는 항목(SCORECARD C):")
    print("  캐릭터 일관성 / 연출 흐름 / 대사 자연스러움 / 몰입 / 인화 품질 / 화풍 일치")
    print("다음: python tools/advance_scene.py new")


def cmd_revise(args: argparse.Namespace) -> None:
    sid = args.scene_id
    path = scene_path(sid)
    sc = load(path)
    sc["status"] = args.target
    sc["review"]["auto"] = "PENDING"
    sc["review"]["human"] = "PENDING"
    # 되돌리면 선택을 무효화한다 — 오래된 이미지가 재선택 없이 다시 승인되는 것을 막는다.
    sc["assets"]["selected_image"] = ""
    sc["review"]["notes"].append(
        f"[{date.today()}] REVISE → {args.target}" + (f": {args.note}" if args.note else ""))
    sc["version"] = int(sc.get("version", 1)) + 1
    save(path, sc)
    print(f"{sid} → {args.target} (version {sc['version']}). 기존 이미지·프롬프트는 보존됨.")


def cmd_status(args: argparse.Namespace) -> None:
    scenes = sorted(all_scenes(), key=lambda s: s.get("scene_order", 0))
    if not scenes:
        print("장면 없음. 시작:  python tools/advance_scene.py new")
        return
    print(f"{'순서':<4} {'scene_id':<12} {'상태':<14} {'auto':<8} {'human':<8} 선택본")
    print("-" * 64)
    for s in scenes:
        sel = Path(s["assets"].get("selected_image", "")).name or "-"
        print(f"{s.get('scene_order','?'):<4} {s.get('scene_id','?'):<12} "
              f"{s.get('status','?'):<14} {s['review'].get('auto','?'):<8} "
              f"{s['review'].get('human','?'):<8} {sel}")
    nxt = {"SCENE_PLAN": "계획 작성 후 make_grok_input.py 실행",
           "PROMPT": "외부 AI 생성 → add-images",
           "IMAGE": "자동 검사 원인 해결 또는 add-images 재실행",
           "REVIEW_HUMAN": "시사 → select → approve",
           "REVISE": "지정 단계 작업 재개",
           "APPROVED": None}
    for s in scenes:
        hint = nxt.get(s.get("status"))
        if hint:
            print(f"\n다음 할 일: {s.get('scene_id')} — {hint}")
            break
    else:
        print("\n모든 장면 APPROVED. 다음: new 로 장면 추가 또는 DELIVERY.md 절차 진행")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="advance_scene.py",
        description="장면 상태 전이 자동화 (JSON 손편집 불필요)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="전체 진행 현황표").set_defaults(fn=cmd_status)

    p = sub.add_parser("new", help="다음 번호 장면 생성")
    p.add_argument("scene_id", nargs="?", help="생략 시 자동 번호 (SCENE-00N)")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("set-prompt", help="Grok 출력 저장 → 상태 PROMPT")
    p.add_argument("scene_id")
    p.add_argument("--file", help="Grok 출력이 담긴 텍스트 파일 (생략 시 붙여넣기 입력)")
    p.set_defaults(fn=cmd_set_prompt)

    p = sub.add_parser("add-images", help="후보 이미지 등록 → 자동 검사")
    p.add_argument("scene_id")
    p.add_argument("files", nargs="+", help="외부 AI에서 받은 이미지 파일들")
    p.set_defaults(fn=cmd_add_images)

    p = sub.add_parser("select", help="후보 1장 선택")
    p.add_argument("scene_id")
    p.add_argument("candidate", help="status 표의 후보 번호 또는 파일명")
    p.set_defaults(fn=cmd_select)

    p = sub.add_parser("approve", help="사람 시사 통과 → APPROVED 잠금")
    p.add_argument("scene_id")
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("revise", help="이전 단계로 되돌림 (자료 보존)")
    p.add_argument("scene_id")
    p.add_argument("target", choices=BACK_STATES, help="되돌릴 단계")
    p.add_argument("--note", default="", help="사유 (review.notes 에 기록)")
    p.set_defaults(fn=cmd_revise)
    return ap


def main() -> None:
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
