#!/usr/bin/env python3
"""이미지 생성 작업의 진행 상태기계 — 웹 스튜디오와 CLI 가 공유하는 단일 구현.

여기 따로 있는 이유는 두 가지다.

  * **중복 과금 방지가 서버 밖에서도 걸려야 한다.** 폰과 PC 에서 같은 장면을 동시에
    누르는 경우는 웹이 막고 있었지만, 같은 장면을 CLI(makefun_client)로 한 번 더 돌리면
    그대로 두 번 과금됐다. :func:`claim` 은 **이 프로세스의 모든 생성 경로가 통과하는
    하나의 관문**이다(웹 라우트·CLI 어느 쪽이 먼저 잡든 나머지는 거절된다).
  * webapp 라우트에서 스레드·진행 표시 관리를 걷어내 라우트를 얇은 어댑터로 되돌린다.

공개 API
  claim(sid)                      생성 선점 — 이미 진행 중이면 VNError
  release(sid, message="")        선점 해제(진행 표시 종료)
  claimed(sid, label="생성")       with 문용 — 성공/실패 어느 쪽이든 반드시 해제
  note(sid, message, running=True) 진행 문구 갱신
  run(sid, fn, label)             동기 실행틀(수신 → 후보 등록 → 자동 검사)
  start(sid, fn, label, ...)      기본은 백그라운드, sync=True 면 동기
  status(sid)                     {running, message, scene_id}
  running()                       아직 끝나지 않은 장면 목록

작업 표시는 메모리에만 있다(서버·프로세스 수명). 진행 중에 프로세스가 꺼지면 표시도
사라지지만, MakeFun 에 이미 만들어진 결과는 재수령(무과금) 경로로 회수할 수 있다.
20분 넘게 끝나지 않은 표시는 죽은 작업으로 보고 풀어 준다(영구 잠금 방지).

Python 3.9+ · 표준 라이브러리만. (makefun_client 를 import 하지 않는다 — CLI 쪽에서
이 모듈을 불러도 순환 import 가 생기지 않게 하는 것이 이 파일의 의존 규약이다.)
"""
from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_ops  # noqa: E402
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

STALE_SEC = 1200      # 이 시간을 넘긴 '진행 중' 표시는 죽은 작업으로 본다(20분)

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}     # scene_id → {running, message, ts}

# webapp 이 setup_logging 에서 같은 회전 로그 파일에 물린다. 라이브러리로 쓰일 때는 조용히.
log = logging.getLogger("vn.gen")
log.addHandler(logging.NullHandler())


def _require_sid(sid) -> str:
    if not vn_core.is_scene_id(sid):
        raise VNError(f"장면 ID 형식이 올바르지 않습니다(SCENE-001 형식): {sid!r}")
    return sid


def claim(sid: str) -> None:
    """같은 장면의 동시 생성을 막는다 — 어느 경로에서 눌러도 과금은 한 번만."""
    _require_sid(sid)
    with _LOCK:
        job = _JOBS.get(sid)
        if job and job.get("running") and time.time() - float(job.get("ts") or 0) < STALE_SEC:
            raise VNError(f"{sid} 이미지를 이미 생성 중입니다. 끝난 뒤 다시 시도하세요.")
        _JOBS[sid] = {"running": True, "message": "생성 준비 중…", "ts": time.time()}


def note(sid: str, message: str, running: bool = True) -> None:
    """진행 문구 갱신. running=False 면 그 작업은 끝난 것으로 표시된다."""
    with _LOCK:
        _JOBS[sid] = {"running": bool(running), "message": str(message), "ts": time.time()}


def release(sid: str, message: str = "") -> None:
    """선점 해제 — 진행 표시를 끝낸다(문구를 주면 마지막 상태로 남긴다)."""
    with _LOCK:
        prev = _JOBS.get(sid) or {}
        _JOBS[sid] = {"running": False,
                      "message": str(message or prev.get("message", "") or "완료"),
                      "ts": time.time()}


@contextlib.contextmanager
def claimed(sid: str, label: str = "생성"):
    """CLI 용 선점 블록 — 성공/실패 어느 쪽이든 표시를 반드시 해제한다.

        with gen_jobs.claimed(sid, "생성"):
            files = makefun_client.generate_for_scene(sid)
    """
    claim(sid)
    try:
        yield
    except BaseException as exc:
        release(sid, f"{label} 실패: {exc}")
        raise
    else:
        release(sid, f"{label} 완료")


def status(sid: str) -> dict:
    """생성 진행 조회 — {running, message, scene_id}."""
    _require_sid(sid)
    with _LOCK:
        job = dict(_JOBS.get(sid) or {})
    running_now = bool(job.get("running")) and \
        time.time() - float(job.get("ts") or 0) < STALE_SEC
    return {"running": running_now, "message": str(job.get("message", "")), "scene_id": sid}


def running() -> list[str]:
    """아직 끝나지 않은 생성 작업 — 종료 시 사용자에게 알려 주기 위한 목록."""
    now = time.time()
    with _LOCK:
        return sorted(sid for sid, j in _JOBS.items()
                      if j.get("running") and now - float(j.get("ts") or 0) < STALE_SEC)


def run(sid: str, fn, label: str) -> dict:
    """생성/재수령 공통 실행틀 — 성공/실패 어느 쪽이든 in-flight 표시를 반드시 해제한다.

    fn() 은 저장된 파일 경로 목록을 돌려준다. 수신 후 후보 등록·자동 검사까지 여기서 한다.
    """
    try:
        files = list(fn())
        note(sid, f"{len(files)}장 수신 · 등록·검사 중…")
        reg = scene_ops.register_images(sid)
        reg["generated"] = [f.name for f in files]
        note(sid, f"완료 — {len(files)}장 {label} · 자동검사 {reg.get('auto', '')}",
             running=False)
        log.info("%s 완료 %s (%d장)", label, sid, len(files))
        return reg
    except Exception as exc:
        log.warning("%s 실패 %s: %s", label, sid, exc)
        note(sid, f"실패: {exc}", running=False)
        raise


def start(sid: str, fn, label: str, *, sync: bool = False, message: str = "",
          count: int = 0) -> dict:
    """백그라운드 기본 + sync=True 면 동기 — 폰 브라우저가 기다리다 끊기지 않게 한다."""
    claim(sid)
    if sync:
        return run(sid, fn, label)

    def _bg():
        try:
            run(sid, fn, label)
        except Exception:
            pass   # 사유는 run() 이 로그·진행 문구에 남긴다(스레드는 조용히 종료)

    threading.Thread(target=_bg, daemon=True).start()
    return {"started": True, "running": True, "scene_id": sid,
            "message": message or f"{label} 중…", "generated": [], "auto": "진행 중",
            "count": int(count)}
