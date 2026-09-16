#!/usr/bin/env python3
"""작품 전환 — 대화마다 자기 장면과 자기 그림을 갖게 한다.

왜 필요한가: 통합 화면의 '목록' 은 대화를 여러 갈래로 갈라 주는데, **입력만 갈라지고
출력은 하나였다.** 장면은 ``project/scenes/`` 한 폴더에 살고 ``/api/state`` 는 chat_id 를
받지도 않아서, 어느 대화를 열든 같은 장면이 보였다. 대화 2에서 조립하면 "이미 장면이
있습니다" 로 막히고, 덮어쓰면 대화 1의 작품이 사라졌다. 절반만 만든 기능이었다.

왜 하위 폴더로 나누지 않는가: 판정자 ``tools/check_protocol.py`` 가 **수정 금지 파일**이고
``project/scenes/*.json`` 을 하드코딩으로 훑는다. 장면을 ``scenes/<chat>/`` 로 내리면 그
검사기가 장면을 못 찾는데, 고칠 수가 없다. 그래서 반대로 간다 — 장면이 사는 자리는 늘
``project/scenes/`` 하나로 두고, **거기 올라와 있는 작품을 갈아 끼운다.**

  project/works/<chat_id>/scenes/       쉬고 있는 작품의 장면
  project/works/<chat_id>/images_raw/   그 작품의 그림
  project/scenes/ · images/raw/         지금 열려 있는 작품 (검사기·도구가 보는 자리)
  project/works_state.json              지금 올라와 있는 것이 누구 것인가

옮기는 방법은 **폴더 이름 바꾸기**다. 복사가 아니다 — 그림이 150MB 라 복사하면 전환마다
몇 초씩 걸리고 디스크도 두 배로 먹는다. 같은 볼륨 안의 디렉터리 rename 은 크기와 무관하게
즉시 끝난다.

이 파일이 지키는 약속은 하나다: **어떤 경우에도 장면과 그림을 잃지 않는다.**
  * 옮기기 전에 **무엇을 하려는지 먼저 적는다**(works_state.json). 도중에 죽어도 다음
    실행이 그 기록을 보고 마무리하거나 되돌린다(:func:`repair`).
  * 목적지가 이미 있으면 **덮지 않고 거절한다.** 덮어쓰기는 이 파일에 없다.
  * 굽는 중·조립 중에는 전환하지 않는다(부르는 쪽이 확인한다 — :func:`busy_reason`).

Python 3.9+ · 표준 라이브러리만. vn_core 하나만 본다(계층 1).
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

WORKS = vn_core.PROJECT / "works"
STATE = vn_core.PROJECT / "works_state.json"
SCENES = vn_core.SCENES
IMAGES_RAW = vn_core.IMAGES_RAW

# 보관소 안에서 쓰는 이름. 바깥 이름(scenes / images/raw)과 한 쌍으로 묶여 있다.
_PAIRS = (("scenes", lambda: SCENES), ("images_raw", lambda: IMAGES_RAW))


def _slug(chat_id: Any) -> str:
    """대화 id → 폴더 이름. 기본 갈래('')는 ``_default`` 로 둔다.

    빈 문자열을 폴더 이름으로 쓸 수 없어서 이름을 하나 준다. 밑줄로 시작하는 것은
    대화 id 규칙(첫 글자는 영숫자)에 걸리지 않으므로 진짜 대화와 절대 겹치지 않는다.
    """
    s = str(chat_id or "").strip()
    if not s:
        return "_default"
    safe = vn_core.safe_slug(s, "chat", maxlen=40)
    return safe or "chat"


def work_dir(chat_id: Any) -> Path:
    return WORKS / _slug(chat_id)


def _state() -> dict:
    d = vn_core.load_json_safe(STATE, {})
    return d if isinstance(d, dict) else {}


def _write_state(d: dict) -> None:
    vn_core.atomic_write_json(STATE, d)


def current() -> str:
    """지금 project/scenes/ 에 올라와 있는 작품의 대화 id. 기록이 없으면 기본 갈래('')."""
    return str(_state().get("current", "") or "")


def _count(folder: Path) -> int:
    try:
        return sum(1 for f in folder.glob("*.json") if f.is_file())
    except OSError:
        return 0


def list_works() -> list[dict]:
    """보관된 작품 + 지금 올라와 있는 것 → [{chat_id, scenes, live}]."""
    cur = current()
    out = [{"chat_id": cur, "scenes": _count(SCENES), "live": True}]
    seen = {_slug(cur)}
    if WORKS.is_dir():
        for d in sorted(WORKS.iterdir()):
            if not d.is_dir() or d.name in seen:
                continue
            seen.add(d.name)
            cid = "" if d.name == "_default" else d.name
            out.append({"chat_id": cid, "scenes": _count(d / "scenes"), "live": False})
    return out


def _park(cid: str) -> None:
    """지금 올라와 있는 것을 보관소로 내린다(이름 바꾸기)."""
    home = work_dir(cid)
    home.mkdir(parents=True, exist_ok=True)
    for name, live in _PAIRS:
        src, dst = live(), home / name
        if not src.exists():
            continue
        if dst.exists():
            # 덮지 않는다. 보관소에 이미 무언가 있다는 것은 지난 전환이 덜 끝났다는 뜻이고,
            # 그 위에 쓰면 그쪽 작품이 사라진다.
            raise VNError(f"보관소가 이미 차 있습니다: {dst} — 정리 전에는 전환하지 않습니다.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)


def _unpark(cid: str) -> None:
    """보관소의 작품을 올린다. 없으면 빈 자리를 만들어 준다(새 작품)."""
    home = work_dir(cid)
    for name, live in _PAIRS:
        src, dst = home / name, live()
        if dst.exists():
            if src.exists():
                raise VNError(f"올릴 자리가 비어 있지 않습니다: {dst}")
            continue          # 이미 올라와 있다(반쪽만 내려간 상태의 복구)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            src.replace(dst)
        else:
            dst.mkdir(parents=True, exist_ok=True)


def repair() -> dict:
    """중간에 끊긴 전환을 마무리한다. 시작할 때와 전환 전에 부른다.

    두 가지를 본다.
      1. 이동 중 표시(moving)가 남아 있다 → 내렸으면 마저 올리고, 안 내렸으면 되돌린다.
      2. 표시는 없는데 **자리가 비어 있다** → 기록된 주인의 것을 올린다.
         이 안전망이 있어야 어떤 경로로 비었든 화면이 빈 채로 남지 않는다.
    """
    st = _state()
    cur = str(st.get("current", "") or "")
    if st.get("moving"):
        want = str(st.get("to", "") or "")
        if SCENES.exists():
            _write_state({"current": cur})          # 아직 안 내렸다 → 없던 일로
            return {"repaired": True, "action": "rolled_back", "current": cur}
        _unpark(want)                               # 내린 뒤 죽었다 → 마저 올린다
        _write_state({"current": want})
        return {"repaired": True, "action": "finished", "current": want}
    if not SCENES.exists():
        _unpark(cur)
        _write_state({"current": cur})
        return {"repaired": True, "action": "remounted", "current": cur}
    return {"repaired": False, "current": cur}


def switch(chat_id: Any) -> dict:
    """그 대화의 작품을 올린다. 지금 것은 보관소로 내린다.

    같은 작품이면 아무것도 하지 않는다 — 대화를 열 때마다 불리는 함수라, 파일을 건드리지
    않는 것이 기본 동작이어야 한다.
    """
    want = str(chat_id or "")
    repair()
    cur = current()
    if _slug(cur) == _slug(want):
        return {"switched": False, "current": cur, "scenes": _count(SCENES)}

    with vn_core.WRITE_LOCK:
        # 하려는 일을 **먼저 적는다.** 이 한 줄이 중간에 죽었을 때 되살릴 유일한 단서다.
        # 불리언 moving 을 따로 둔다. 기본 대화의 id 는 **빈 문자열**이라,
        # 목적지 값만 보면 "기본으로 이동 중" 과 "이동 중 아님" 이 같아진다 —
        # 실제로 그것 때문에 중단 복구가 안 돌았다(샌드박스 시험에서 잡았다).
        _write_state({"current": cur, "moving": True, "to": want, "at": int(time.time())})
        _park(cur)
        try:
            _unpark(want)
        except Exception:
            # 올리다 실패하면 방금 내린 것을 도로 올린다 — 빈 화면으로 끝내지 않는다.
            _unpark(cur)
            _write_state({"current": cur})
            raise
        _write_state({"current": want})
    return {"switched": True, "from": cur, "current": want, "scenes": _count(SCENES)}


def forget(chat_id: Any) -> bool:
    """그 대화의 **보관된** 작품을 지운다(대화를 지울 때). 올라와 있는 것은 건드리지 않는다.

    장면과 그림은 다시 만들 수 없으므로 지우지 않고 ``.deleted`` 로 이름만 바꾼다 —
    대화 로그를 지울 때와 같은 규칙이다.
    """
    cid = str(chat_id or "")
    if _slug(cid) == _slug(current()):
        return False                      # 지금 보고 있는 작품은 이 함수가 건드리지 않는다
    home = work_dir(cid)
    if not home.is_dir():
        return False
    dest = home.with_name(home.name + ".deleted")
    n = 2
    while dest.exists() and n < 100:
        dest = home.with_name("%s.deleted-%d" % (home.name, n))
        n += 1
    home.replace(dest)
    return True


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="작품 전환 — 대화마다 자기 장면·그림")
    ap.add_argument("--list", action="store_true", help="보관된 작품 목록")
    ap.add_argument("--switch", metavar="CHAT_ID", help="그 대화의 작품을 올린다('' = 기본)")
    ap.add_argument("--repair", action="store_true", help="끊긴 전환 마무리")
    a = ap.parse_args()
    if a.repair:
        print(repair())
        return 0
    if a.switch is not None:
        print(switch(a.switch))
        return 0
    print(f"지금 올라와 있는 작품: {current() or '(기본 대화)'} · 장면 {_count(SCENES)}개")
    for w in list_works():
        mark = "→" if w["live"] else " "
        print(f"  {mark} {w['chat_id'] or '(기본 대화)':24s} 장면 {w['scenes']}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
