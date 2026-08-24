#!/usr/bin/env python3
"""장면 상태 전이 자동화 도구 — JSON 수동 편집을 없앤다.

각 명령의 상세 옵션: python tools/advance_scene.py <명령> --help

  status                          전체 진행 현황표 + 다음 할 일
  new [SCENE-ID]                  다음 번호 장면 생성 (id·order 자동, 화는 마지막 장면에서 승계)
  set-prompt SID [--file F]       Grok 출력 저장, 상태 → PROMPT (미지정 시 붙여넣기,
                                  종료: Windows Ctrl+Z+Enter / mac·Linux Ctrl+D)
  add-images SID 파일...           후보 복사·기록 → 자동 검사 → PASS 시 REVIEW_HUMAN
  select SID <번호|파일명>          후보 1장을 selected_image 로 지정
  approve SID                     검사 PASS 확인 후 APPROVED 잠금 (FAIL 시 롤백)
  revise SID <단계> [--note 사유]   SCENE_PLAN/PROMPT/IMAGE 로 되돌림 (자료 보존)

이 파일의 자리(계층)
  * **순수 CLI 어댑터**다. 아래 cmd_* 는 scene_ops 의 전이 함수를 부르고 결과를 사람이
    읽을 문장으로 옮기기만 한다. 웹 스튜디오도 같은 함수를 부르므로 CLI 와 웹이 서로 다른
    규칙으로 움직일 수 없다(예: 승인 잠금은 양쪽 모두 적용).
  * **상태 전이 규칙은 여기 없다**(scene_ops). **저장소 계층도 여기 없다**(vn_core).
    예전에는 저장소 계층이 이 파일에 있어서 scene_ops 가 CLI 를 import 하고 CLI 가 다시
    scene_ops·vn_compose 를 지연 import 하는 순환이었다. 지금은 한 방향이다:
    vn_core ← scene_ops ← 이 파일.
  * 아래 재수출 이름(load·save·scene_path·run_checker·all_scenes·WRITE_LOCK)은 기존
    호출부(webapp·vn_compose·grok_api)를 위한 얇은 별칭이다. 구현은 vn_core 한 곳뿐이다.

오류 규약: 라이브러리 함수는 VNError 를 던지고, 종료 코드 변환은 main() 에서만 한다.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_ops  # noqa: E402
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

# 경로·잠금은 vn_core 가 정본이다. 아래 이름들은 기존 호출부(webapp·vn_compose)를 위한 별칭.
ROOT = vn_core.ROOT
SCENES = vn_core.SCENES
MANIFEST = vn_core.MANIFEST
RAW_DIR = vn_core.IMAGES_RAW
CHECKER = vn_core.CHECKER
TEMPLATE = vn_core.TEMPLATES / "scene.json"
WRITE_LOCK = vn_core.WRITE_LOCK   # 저장소 전역 단일 쓰기 잠금(웹의 동시 요청 직렬화)

# 저장소 계층 재수출 — 구현은 vn_core, 여기는 이름만 유지한다(하위호환).
load = vn_core.load_dict
save = vn_core.atomic_write_json
scene_path = vn_core.scene_path
run_checker = vn_core.run_checker
all_scenes = vn_core.all_scenes

# 되돌릴 수 있는 단계 — 정본은 scene_ops.revise 가 검사하는 그 집합 하나다.
# (예전에는 여기 따로 적어 둬서 두 벌이었고, 한쪽만 늘리면 CLI 와 웹의 허용 단계가 갈렸다.)
BACK_STATES = scene_ops.BACK_STATES

_console_guard = vn_core.console_guard   # 예전 이름 유지(호출부 호환). import 시 이미 적용됨.


def die(msg: str) -> NoReturn:
    """사용자에게 보여줄 오류 — 예전에는 sys.exit(2) 였다.

    라이브러리 코드에서 프로세스를 죽이면 웹 스튜디오의 요청 스레드가 응답 없이 끊긴다.
    이제는 VNError 를 던지고, 종료 코드 2 로의 변환은 main() 한 곳에서만 한다.
    """
    raise VNError(msg)


def _print_fails(fails: str) -> None:
    if fails.strip():
        print(fails)


def apply_prompt(sid: str, text: str) -> None:
    """Grok 출력을 장면에 반영하고 상태를 PROMPT 로 올린다. (수동/API 모드 공용)"""
    res = scene_ops.set_prompt(sid, text)
    print("상태 → PROMPT")
    if res["checker_pass"]:
        print("앵커 검사 포함 자동 검사 통과. 다음: 외부 이미지 AI에서 후보 생성")
        print("  (레퍼런스 이미지 첨부를 잊지 마세요 → manifest 의 reference_images)")
        print(f"  python tools/advance_scene.py add-images {sid} <파일...>")
    else:
        print("자동 검사 경고:")
        _print_fails(res["fails"])


# ---------------------------------------------------------------- 명령들
def cmd_new(args: argparse.Namespace) -> None:
    scenes = all_scenes()
    nums = [int(m.group(1)) for s in scenes
            if (m := re.fullmatch(r"SCENE-(\d+)", s.get("scene_id", "")))]
    sid = args.scene_id or f"SCENE-{(max(nums) + 1 if nums else 1):03d}"
    # 형식 판정의 정본은 vn_core.is_scene_id 하나다. 예전에는 여기만 두 자리를 허용해
    # 'SCENE-1' 장면이 만들어졌고(검사기도 통과), 정작 웹 스튜디오·scene_ops 가 그 id 를
    # 거부해서 **영영 진행시킬 수 없는 장면**이 생겼다.
    if not vn_core.is_scene_id(sid):
        die(f"scene_id 는 SCENE-001 처럼 'SCENE-' + 3자리 이상 숫자여야 합니다: {sid!r} "
            "(SCENE-1 같은 이름은 웹 스튜디오가 거부해 그 장면을 진행시킬 수 없습니다).")
    path = scene_path(sid)
    if path.exists():
        die(f"{sid} 는 이미 존재합니다.")
    sc = load(TEMPLATE)
    sc["scene_id"] = sid
    sc["scene_order"] = max((s.get("scene_order", 0) for s in scenes), default=0) + 1
    # 화(episode)는 지금 작업 중인 마지막 장면에서 이어받는다(templates/scene.json 에는
    # episode 키가 없다 — 없는 값을 임의로 붙이지 않는다). 승계하지 않으면 3화를 쓰는
    # 중에 만든 장면에 화가 아예 붙지 않아 감상본의 화 선택에서 통째로 빠진다.
    ep = vn_core.last_episode()
    if ep is None:
        sc.pop("episode", None)     # 화를 쓰지 않는 작품 — 없는 정보를 만들어 붙이지 않는다
    else:
        sc["episode"] = ep
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
    with WRITE_LOCK:
        if path.exists():          # 잠금 안에서 다시 확인(동시 new 로 덮어쓰지 않게)
            die(f"{sid} 는 이미 존재합니다.")
        SCENES.mkdir(parents=True, exist_ok=True)
        save(path, sc)
    print(f"생성: project/scenes/{sid}.json (scene_order={sc['scene_order']}"
          + (f", {sc['episode']}화" if sc.get("episode") else "") + ")")
    print("다음: 장면 계획(purpose/action_beat/emotion/camera/dialogue)을 채운 뒤")
    print(f"      python tools/make_grok_input.py {sid}")


def cmd_set_prompt(args: argparse.Namespace) -> None:
    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8")
        except OSError as exc:
            die(f"파일을 읽을 수 없습니다: {args.file} ({exc})")
    else:
        print("Grok 출력 전체를 붙여넣으세요. (종료: Windows Ctrl+Z+Enter / mac·Linux Ctrl+D)")
        text = sys.stdin.read()
    print("저장 완료.", end=" ")
    apply_prompt(args.scene_id, text)


def cmd_add_images(args: argparse.Namespace) -> None:
    sid = args.scene_id
    res = scene_ops.import_image_files(sid, args.files)
    print(f"후보 {len(res.get('imported', []))}장 등록 (폴더 전체 {res['count']}장):")
    for i, r in enumerate(res.get("imported", []), 1):
        print(f"  [{i}] {r}")
    if res["auto"] == "PASS":
        print("자동 검사 PASS → 상태 REVIEW_HUMAN")
        print(f"다음: 시사 후  python tools/advance_scene.py select {sid} <번호>")
    else:
        print("자동 검사 FAIL — 아래 원인을 해결하세요:")
        _print_fails(res["fails"])


def cmd_select(args: argparse.Namespace) -> None:
    sid = args.scene_id
    chosen = scene_ops.resolve_candidate(sid, args.candidate)
    res = scene_ops.select_image(sid, chosen)
    print(f"선택: {res['selected']}")
    if res["auto_pass"]:
        print(f"다음: python tools/advance_scene.py approve {sid}")
    else:
        _print_fails(res["fails"])


def do_approve(sid: str) -> None:
    """승인 잠금 — 검사 FAIL 시 원상 복구 후 VNError. (웹 스튜디오도 이 경로를 쓴다)"""
    scene_ops.approve(sid)


def cmd_approve(args: argparse.Namespace) -> None:
    sid = args.scene_id
    try:
        do_approve(sid)
    except RuntimeError as exc:     # VNError 포함
        print(f"승인 불가 — {exc}")
        sys.exit(1)
    print(f"{sid} APPROVED — 장면 잠금 완료.")
    print("사람 시사에서 확인했어야 하는 항목(SCORECARD C):")
    print("  캐릭터 일관성 / 연출 흐름 / 대사 자연스러움 / 몰입 / 인화 품질 / 화풍 일치")
    print("다음: python tools/advance_scene.py new")


def cmd_revise(args: argparse.Namespace) -> None:
    res = scene_ops.revise(args.scene_id, args.target, args.note)
    print(f"{args.scene_id} → {res['status']} (version {res['version']}). "
          "기존 이미지·프롬프트는 보존됨.")


def cmd_status(args: argparse.Namespace) -> None:
    scenes = sorted(all_scenes(), key=lambda s: s.get("scene_order", 0))
    if not scenes:
        print("장면 없음. 시작:  python tools/advance_scene.py new")
        return
    print(f"{'순서':<4} {'scene_id':<12} {'상태':<14} {'auto':<8} {'human':<8} 선택본")
    print("-" * 64)
    for s in scenes:
        assets = s.get("assets") if isinstance(s.get("assets"), dict) else {}
        review = s.get("review") if isinstance(s.get("review"), dict) else {}
        sel = Path(str(assets.get("selected_image", ""))).name or "-"
        print(f"{s.get('scene_order','?'):<4} {s.get('scene_id','?'):<12} "
              f"{s.get('status','?'):<14} {review.get('auto','?'):<8} "
              f"{review.get('human','?'):<8} {sel}")
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


def main() -> int:
    """종료 코드 변환은 여기 한 곳에서만 한다: 정상 0 · 사용자 오류 2 · 승인 거부 1."""
    args = build_parser().parse_args()
    try:
        args.fn(args)
    except VNError as exc:
        print(f"오류: {exc}")
        return 2
    except KeyboardInterrupt:
        print("\n중단했습니다.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
