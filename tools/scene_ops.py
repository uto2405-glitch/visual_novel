#!/usr/bin/env python3
"""장면 상태 전이의 **유일한 구현** — 웹 스튜디오와 CLI 가 같은 규칙 아래 움직이게 한다.

지금까지 같은 전이가 두 벌(webapp 의 set_scene_prompt/register_images/select_image,
advance_scene 의 apply_prompt/cmd_add_images/cmd_select/do_approve/cmd_revise)로 있었고,
그 사이에 실제 구멍이 있었다:

  * CLI 의 set-prompt·add-images 에는 APPROVED 가드가 없어 **승인된 장면을 덮어쓰고**
    status 를 되돌릴 수 있었다 — 사람 승인 게이트(SCORECARD C)를 우회하는 경로였다.
  * 쓰기 잠금(WRITE_LOCK)도 approve 에만 걸려 있어, 나머지 전이는 동시에 들어오면
    read-modify-write 가 겹칠 수 있었다.

여기서는 **모든 쓰기 경로**가 같은 잠금 안에서 같은 가드를 통과한다.
webapp 의 r_* 와 advance_scene 의 cmd_* 는 이 함수들을 부르는 얇은 어댑터만 남긴다.

공개 API
  set_prompt(sid, text, fix_anchors=False)        프롬프트 저장 → PROMPT + 자동 검사
  register_images(sid, run_check=True)            images/raw/<sid>/ 스캔 → 후보 등록·검사
  select_image(sid, rel)                          후보 1장을 selected_image 로
  approve(sid)                                    REVIEW_HUMAN → APPROVED (FAIL 시 롤백)
  revise(sid, stage, note="")                     이전 단계로 되돌림(자료 보존)

CLI 어댑터를 위한 보조(웹은 쓰지 않는다)
  import_image_files(sid, paths, run_check=True)  외부 파일을 후보 폴더로 복사 후 등록
  resolve_candidate(sid, key)                     '3' 또는 파일명 → raw_images 의 항목
  missing_anchors(sc, text)                       프롬프트에 빠진 앵커 원문 목록

오류는 모두 vn_core.VNError(RuntimeError 파생)다. 종료 코드 변환은 각 도구의 main() 몫.
"""
from __future__ import annotations

import contextlib
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advance_scene as adv   # noqa: E402  저장소 계층(load/save/scene_path/run_checker) 재사용
import vn_core                # noqa: E402
from vn_core import VNError   # noqa: E402

# 되돌릴 수 있는 단계 — revise 의 유일한 허용 집합.
BACK_STATES = ("SCENE_PLAN", "PROMPT", "IMAGE")

_REVISE_HINT = "  python tools/advance_scene.py revise {sid} IMAGE --note \"사유\""


# ---------------------------------------------------------------- 잠금
@contextlib.contextmanager
def _lock():
    """전역 쓰기 잠금.

    vn_core.WRITE_LOCK 이 정본이다. advance_scene 이 아직 자기 잠금을 따로 갖고 있는
    동안에는(이관 과도기) 그것도 같이 잡아 webapp 의 기존 ``with adv.WRITE_LOCK`` 블록과
    상호배제를 보장한다. 순서는 항상 vn_core → advance_scene 하나뿐이라 교착이 없다.
    두 잠금이 같은 객체가 되면(이관 완료) 한 번만 잡는다.
    """
    other = getattr(adv, "WRITE_LOCK", None)
    with vn_core.WRITE_LOCK:
        if other is None or other is vn_core.WRITE_LOCK:
            yield
        else:
            with other:
                yield


# ---------------------------------------------------------------- 저장소 접근
def _scene_path(sid: Any) -> Path:
    """형식 검증 후 장면 파일 경로. 검증이 먼저인 이유는 '../..' 같은 값이 장면 폴더
    밖의 파일에 닿는 것을 원천 차단하기 위해서다."""
    if not vn_core.is_scene_id(sid):
        raise VNError(f"장면 ID 형식이 올바르지 않습니다(SCENE-001 형식): {sid!r}")
    return adv.scene_path(sid)


def _require(sid: Any) -> Path:
    path = _scene_path(sid)
    if not path.exists():
        raise VNError(f"장면을 찾을 수 없습니다: {sid}")
    return path


def _norm(sc: dict) -> dict:
    """장면 dict 의 필수 하위 구조를 보장한다 — 낡거나 손상된 파일에서 KeyError 로
    요청 스레드가 죽는 대신, 빈 값으로 정상 흐름을 타게 한다."""
    assets = sc.get("assets")
    if not isinstance(assets, dict):
        assets = {}
    if not isinstance(assets.get("raw_images"), list):
        assets["raw_images"] = []
    if not isinstance(assets.get("selected_image"), str):
        assets["selected_image"] = ""
    sc["assets"] = assets
    review = sc.get("review")
    if not isinstance(review, dict):
        review = {}
    if not isinstance(review.get("notes"), list):
        review["notes"] = []
    sc["review"] = review
    if not isinstance(sc.get("prompt"), dict):
        sc["prompt"] = {}
    return sc


def _load(path: Path) -> dict:
    """장면 읽기 — advance_scene 의 로더를 재사용하되, 그 안의 die()/SystemExit 가
    웹 요청 스레드를 죽이지 못하게 VNError 로 바꾼다(이관 전후 모두 안전)."""
    try:
        sc = adv.load(path)
    except SystemExit as exc:
        raise VNError(f"장면 파일을 읽을 수 없습니다: {path.name} "
                      "(JSON 형식이 깨졌는지 확인하세요)") from exc
    if not isinstance(sc, dict):
        raise VNError(f"{path.name}: JSON 최상위가 객체({{...}})가 아닙니다.")
    return _norm(sc)


def _save(path: Path, sc: dict) -> None:
    adv.save(path, sc)          # 원자적 저장(임시 파일 → 교체)


def _fails(out: str) -> str:
    return "\n".join(l for l in (out or "").splitlines() if "FAIL" in l)


def _deny_if_approved(sc: dict, sid: str, what: str) -> None:
    """승인 잠금 장면의 변경 금지 — 사람 승인을 거치지 않은 결과물이 완성본 자리를
    차지하는 것을 막는다. 되돌리려면 revise 를 거쳐야 한다(그 자체가 기록으로 남는다)."""
    if sc.get("status") == "APPROVED":
        raise VNError(f"{sid} 는 APPROVED 입니다. {what} 먼저 되돌리세요:\n"
                      + _REVISE_HINT.format(sid=sid))


# ---------------------------------------------------------------- 프롬프트
def missing_anchors(sc: dict, text: str) -> list[str]:
    """장면에 필요한 인물/장소 앵커 중 프롬프트에 빠진 원문 목록.

    앵커가 빠지면 검사기 A6 가 FAIL 이고, 무엇보다 컷마다 인물 얼굴이 달라진다.
    """
    mf = vn_core.load_manifest()
    low = (text or "").lower()
    out: list[str] = []
    chars = {c.get("character_id"): c for c in mf.get("characters", []) if isinstance(c, dict)}
    for cid in sc.get("characters", []) or []:
        a = str((chars.get(cid) or {}).get("prompt_anchor", "") or "").strip()
        if a and a.lower() not in low:
            out.append(a)
    for loc in mf.get("locations", []) or []:
        if isinstance(loc, dict) and loc.get("location_id") == sc.get("location_id"):
            a = str(loc.get("prompt_anchor", "") or "").strip()
            if a and a.lower() not in low:
                out.append(a)
    return out


def set_prompt(sid: str, text: str, fix_anchors: bool = False) -> dict:
    """이미지 프롬프트를 장면에 저장 → 상태 PROMPT + 자동 검사.

    (로컬 LLM 생성·그록 수동 붙여넣기·API 모드가 모두 이 하나를 쓴다.)
    fix_anchors=True 면 외부 AI 출력에 빠진 앵커 원문을 뒤에 이어붙여 A6 를 보장한다.
    """
    text = str(text or "").strip()
    if not text:
        raise VNError("이미지 프롬프트가 비어 있습니다.")
    path = _require(sid)
    with _lock():
        sc = _load(path)
        _deny_if_approved(sc, sid, "프롬프트를 바꾸려면")
        if fix_anchors:
            miss = missing_anchors(sc, text)
            if miss:
                text = text.rstrip(" .,") + ", " + ", ".join(miss)
        sc["prompt"]["grok_output"] = text
        sc["status"] = "PROMPT"
        _save(path, sc)
        code, out = adv.run_checker(sid)
    return {"scene_id": sid, "status": "PROMPT", "checker_pass": code == 0,
            "fails": _fails(out)}


# ---------------------------------------------------------------- 후보 이미지
def _scan(sid: str) -> tuple[list[Path], list[str]]:
    folder = vn_core.IMAGES_RAW / sid
    files = sorted(f for f in folder.glob("*")
                   if f.is_file() and f.suffix.lower() in vn_core.IMAGE_EXTS) \
        if folder.is_dir() else []
    return files, [f.relative_to(vn_core.ROOT).as_posix() for f in files]


def register_images(sid: str, run_check: bool = True) -> dict:
    """images/raw/<scene_id>/ 를 스캔해 후보 목록을 갱신하고 자동 검사를 돌린다.

    반환: {count, auto, fails, locked}
    APPROVED 장면은 **바뀔 것이 없을 때만** 조용히 통과한다(재스캔이 승인 상태를
    훼손하지 못하게 하는 불변식). 후보가 실제로 달라졌다면 VNError 로 막는다 —
    승인된 컷을 사람 확인 없이 교체하는 유일한 통로였기 때문이다.
    """
    path = _require(sid)
    with _lock():
        sc = _load(path)
        files, rels = _scan(sid)
        cur = list(sc["assets"]["raw_images"])
        sel = sc["assets"]["selected_image"].strip()
        sel_gone = bool(sel) and not (vn_core.ROOT / sel).exists()

        if sc.get("status") == "APPROVED":
            if rels != cur:
                raise VNError(
                    f"{sid} 는 APPROVED 입니다. 후보 이미지를 바꾸려면 먼저 되돌리세요:\n"
                    + _REVISE_HINT.format(sid=sid))
            note = "APPROVED 장면은 재스캔하지 않습니다. 되돌리려면 revise 를 사용하세요."
            if sel_gone:
                note = f"경고: 선택된 이미지 파일이 없습니다({sel}). 확인이 필요합니다."
            return {"count": len(cur), "auto": sc["review"].get("auto", "PASS"),
                    "fails": "", "locked": True, "note": note}

        sc["assets"]["raw_images"] = rels
        if sel_gone:
            sc["assets"]["selected_image"] = ""   # 사라진 파일이 선택본으로 남지 않게
        if files and sc.get("status") in ("SCENE_PLAN", "PROMPT"):
            sc["status"] = "IMAGE"
        _save(path, sc)
        if not run_check:
            return {"count": len(rels), "auto": sc["review"].get("auto", "PENDING"),
                    "fails": "", "locked": False}
        code, out = adv.run_checker(sid)
        sc = _load(path)
        sc["review"]["auto"] = "PASS" if code == 0 else "FAIL"
        if code == 0 and sc.get("status") == "IMAGE":
            sc["status"] = "REVIEW_HUMAN"
        _save(path, sc)
    return {"count": len(rels), "auto": sc["review"]["auto"], "fails": _fails(out),
            "locked": False}


def import_image_files(sid: str, paths: Iterable[Any], run_check: bool = True) -> dict:
    """외부 파일들을 images/raw/<scene_id>/ 로 복사한 뒤 등록한다(CLI add-images 용).

    원자성: 하나라도 없거나 형식이 아니면 **아무것도 복사하지 않는다**. 복사 도중
    실패해도 그때까지 복사한 것을 되돌린다 — 등록되지 않은 고아 파일을 남기지 않는다.
    """
    path = _require(sid)
    srcs = [Path(str(p)).expanduser() for p in (paths or [])]
    if not srcs:
        raise VNError("등록할 이미지 파일을 지정하세요.")
    missing = [str(s) for s in srcs if not s.is_file()]
    if missing:
        raise VNError("파일 없음: " + ", ".join(missing))
    bad = [s.name for s in srcs if s.suffix.lower() not in vn_core.IMAGE_EXTS]
    if bad:
        raise VNError(f"허용되지 않는 파일 형식: {', '.join(bad)} "
                      f"(허용: {', '.join(sorted(vn_core.IMAGE_EXTS))})")
    with _lock():
        sc = _load(path)
        _deny_if_approved(sc, sid, "후보 이미지를 추가하려면")
        dest = vn_core.IMAGES_RAW / sid
        dest.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        try:
            for src in srcs:
                target = dest / src.name
                n = 2
                while target.exists():
                    target = dest / f"{src.stem}-{n}{src.suffix}"
                    n += 1
                shutil.copy2(src, target)
                copied.append(target)
        except OSError as exc:
            for c in copied:            # 부분 복사 되돌리기
                try:
                    c.unlink()
                except OSError:
                    pass
            raise VNError(f"이미지 복사 실패: {exc}") from exc
        res = register_images(sid, run_check=run_check)
    res["imported"] = [c.relative_to(vn_core.ROOT).as_posix() for c in copied]
    return res


def resolve_candidate(sid: str, key: Any) -> str:
    """후보 지시자('3' 또는 파일명) → raw_images 의 실제 항목. (CLI select 용)

    '²' 처럼 isdecimal 은 True 지만 int() 가 실패하는 입력도 크래시 없이 안내로 끝낸다.
    """
    path = _require(sid)
    raws = _load(path)["assets"]["raw_images"]
    if not raws:
        raise VNError("등록된 후보 이미지가 없습니다. add-images 를 먼저 실행하세요.")
    k = str(key or "").strip()
    if k.isdecimal():
        try:
            idx = int(k)
        except ValueError:
            idx = None
        if idx is not None:
            if not 1 <= idx <= len(raws):
                raise VNError(f"번호 범위는 1~{len(raws)} 입니다.")
            return raws[idx - 1]
    matches = [r for r in raws if Path(r).name == k or r == k]
    if len(matches) != 1:
        raise VNError(f"'{k}' 와 일치하는 후보가 {len(matches)}개입니다.")
    return matches[0]


def select_image(sid: str, rel: str) -> dict:
    """후보 1장을 selected_image 로 지정한다. 반환: {selected, auto_pass, fails}"""
    path = _require(sid)
    with _lock():   # 검사~저장을 한 잠금 안에 둬 승인 직후의 교체(경쟁 상태)까지 막는다
        _deny_if_approved(_load(path), sid, "선택 이미지를 바꾸려면")
        # 후보 목록만 최신화하고 검사는 돌리지 않는다 — 아래에서 어차피 한 번 돌리므로,
        # 여기서도 돌리면 선택 1회에 검사기 서브프로세스가 2번 뜬다(승격은 아래에서 직접 한다).
        register_images(sid, run_check=False)
        sc = _load(path)
        rel = str(rel or "")
        if rel not in sc["assets"]["raw_images"]:
            raise VNError("해당 파일이 후보 목록에 없습니다. 폴더 스캔을 먼저 하세요.")
        sc["assets"]["selected_image"] = rel
        # 선택 반영을 auto=PASS 로 낙관적 기록 후 검사로 확정한다. (REVIEW_HUMAN 단계는
        # A7 이 auto=PASS 선행을 요구하므로, 먼저 PASS 로 두지 않으면 정상 선택도 FAIL 이 된다.)
        sc["review"]["auto"] = "PASS"
        _save(path, sc)
        code, out = adv.run_checker(sid)
        sc = _load(path)
        if code == 0:
            if sc.get("status") == "IMAGE":     # register_images(run_check=True) 가 하던 승격
                sc["status"] = "REVIEW_HUMAN"
                _save(path, sc)
        else:
            sc["review"]["auto"] = "FAIL"
            _save(path, sc)
    return {"scene_id": sid, "selected": rel, "auto_pass": code == 0, "fails": _fails(out)}


# ---------------------------------------------------------------- 승인·되돌림
def approve(sid: str) -> dict:
    """사람 시사 통과 → APPROVED 잠금. 자동 검사 FAIL 이면 원상 복구하고 VNError.

    승인은 되돌리기 어려운 게이트라, 저장 후 검사가 어긋나면 **파일 원문 그대로**
    되돌린다(부분 승인 상태를 남기지 않는다).
    """
    path = _require(sid)
    with _lock():
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise VNError(f"장면 파일을 읽을 수 없습니다: {path.name}") from exc
        sc = _load(path)
        if sc.get("status") != "REVIEW_HUMAN":
            raise VNError(
                f"REVIEW_HUMAN 단계에서만 승인할 수 있습니다(현재: {sc.get('status')}). "
                "add-images → select 를 먼저 완료하세요.")
        if not sc["assets"]["selected_image"].strip():
            raise VNError("selected_image 가 없습니다. 이미지를 먼저 선택하세요.")
        sc["review"]["auto"] = "PASS"
        sc["review"]["human"] = "PASS"
        sc["status"] = "APPROVED"
        _save(path, sc)
        code, out = adv.run_checker(sid)
        if code != 0:
            vn_core.atomic_write_text(path, original)      # 롤백
            raise VNError("자동 검사 FAIL — 승인을 되돌렸습니다.\n" + _fails(out))
    return {"scene_id": sid, "status": "APPROVED"}


def revise(sid: str, stage: str, note: str = "") -> dict:
    """이전 단계로 되돌린다(이미지·프롬프트 자료는 보존).

    선택본은 비운다 — 오래된 이미지가 재선택 없이 다시 승인되는 것을 막는다.
    APPROVED 장면을 푸는 유일한 정식 경로이므로 여기에는 승인 가드가 없다(사유는 기록된다).
    """
    if stage not in BACK_STATES:
        raise VNError(f"되돌릴 단계는 {'/'.join(BACK_STATES)} 중 하나여야 합니다: {stage!r}")
    path = _require(sid)
    with _lock():
        sc = _load(path)
        sc["status"] = stage
        sc["review"]["auto"] = "PENDING"
        sc["review"]["human"] = "PENDING"
        sc["assets"]["selected_image"] = ""
        note = str(note or "").strip()
        sc["review"]["notes"].append(
            f"[{date.today()}] REVISE → {stage}" + (f": {note}" if note else ""))
        try:
            sc["version"] = int(sc.get("version", 1) or 1) + 1
        except (TypeError, ValueError):
            sc["version"] = 2          # 손상된 version 값은 정상 정수로 되돌린다
        _save(path, sc)
    return {"scene_id": sid, "status": stage, "version": sc["version"]}
