#!/usr/bin/env python3
"""이미지 생성 작업의 진행 상태기계 — 웹 스튜디오와 CLI 가 공유하는 단일 구현.

여기 따로 있는 이유는 두 가지다.

  * **중복 과금 방지가 서버 밖에서도 걸려야 한다.** 폰과 PC 에서 같은 장면을 동시에
    누르는 경우는 웹이 막고 있었지만, 같은 장면을 CLI(makefun_client)로 한 번 더 돌리면
    그대로 두 번 과금됐다. :func:`claim` 이 두 경로가 함께 지나는 관문이다.
  * webapp 라우트에서 스레드·진행 표시 관리를 걷어내 라우트를 얇은 어댑터로 되돌린다.

선점은 두 겹이고, **각각이 무엇까지 보장하는지**를 분명히 해 둔다(거짓 보증이 가장 위험하다).

  1. **같은 프로세스 안** — :data:`_JOBS` 메모리 표시. 웹 요청 두 개(폰·PC)가 동시에
     들어와도 한쪽만 통과한다. 진행 문구도 여기서 나온다.
  2. **프로세스 경계** — ``logs/gen_locks/<scene_id>.lock`` 을 ``O_CREAT|O_EXCL`` 로 만든다.
     웹 서버와 CLI 는 서로 다른 프로세스라 (1) 을 공유하지 못한다. 스튜디오에서 생성 중인
     장면을 CLI ``--all-pending`` 이 다시 굽는 이중 과금을 막는 것은 이 파일 하나다.

     한계도 같이 적는다. 이 잠금은 **협조적**이다 — 이 모듈을 지나는 경로만 지킨다.
     프로세스가 갑자기 죽으면 파일이 남는데, Windows 에서는 pid 로 생존을 확인할 안전한
     방법이 없어(``os.kill(pid, 0)`` 이 프로세스를 죽인다) **시각 기반 만료**로만 회수한다:
     마지막 진행 갱신에서 :data:`STALE_SEC`(20분)이 지난 잠금은 좌초로 보고 회수한다.
     서버를 Ctrl+C 로 끄는 정상 경로에서는 webapp 이 :func:`release_all` 로 즉시 풀어 주므로
     기다릴 일이 없다. logs/ 에 쓸 수 없는 환경이면 잠금 파일을 만들지 못하고 (1) 만 남는다
     — 그때는 경고를 로그에 남긴다(보호가 조용히 사라지지 않게).

공개 API
  claim(sid, label="생성")         생성 선점 — 이미 진행 중이면 VNError
  release(sid, message="")        선점 해제(진행 표시 종료 + 잠금 파일 삭제)
  release_all(message="")         이 프로세스가 잡은 잠금 전부 해제(서버 종료 경로)
  claimed(sid, label="생성")       with 문용 — 성공/실패 어느 쪽이든 반드시 해제
  note(sid, message, running=True) 진행 문구 갱신(+ 잠금 만료 시계 연장)
  run(sid, fn, label)             동기 실행틀(수신 → 후보 등록 → 자동 검사 → 해제)
  start(sid, fn, label, ...)      기본은 백그라운드, sync=True 면 동기
  status(sid)                     {running, message, scene_id} — 다른 프로세스의 잠금도 본다
  running()                       **이 프로세스에서** 아직 끝나지 않은 장면 목록

진행 문구는 메모리에만 있다(프로세스 수명). 진행 중에 프로세스가 꺼지면 문구는 사라지지만,
MakeFun 에 이미 만들어진 결과는 재수령(무과금) 경로로 회수할 수 있다.

Python 3.9+ · 표준 라이브러리만. (makefun_client 를 import 하지 않는다 — CLI 쪽에서
이 모듈을 불러도 순환 import 가 생기지 않게 하는 것이 이 파일의 의존 규약이다.)
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_ops  # noqa: E402
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

STALE_SEC = 1200      # 이 시간을 넘긴 '진행 중' 표시·잠금은 죽은 작업으로 본다(20분)
LOCK_DIR = vn_core.LOGS / "gen_locks"     # 프로세스 경계 잠금 파일이 사는 곳

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}     # scene_id → {running, message, ts}
_OWNED: dict[str, str] = {}     # scene_id → 이 프로세스가 잠금 파일에 적은 토큰

# webapp 이 setup_logging 에서 같은 회전 로그 파일에 물린다. 라이브러리로 쓰일 때는 조용히.
log = logging.getLogger("vn.gen")
log.addHandler(logging.NullHandler())


def _require_sid(sid) -> str:
    if not vn_core.is_scene_id(sid):
        raise VNError(f"장면 ID 형식이 올바르지 않습니다(SCENE-001 형식): {sid!r}")
    return sid


# --- 프로세스 경계 잠금(logs/gen_locks/<scene_id>.lock) -----------------------
# 파일 하나가 곧 "이 장면은 지금 어딘가에서 굽고 있다"는 표시다. 만드는 것은 O_EXCL 이라
# 두 프로세스가 동시에 열어도 하나만 성공한다. 나이(mtime)가 잠금의 생사 판정 기준이고,
# note() 가 그 시계를 뒤로 밀어 오래 걸리는 생성이 스스로 좌초 판정을 받지 않게 한다.

def _lock_path(sid: str) -> Path:
    return LOCK_DIR / f"{sid}.lock"


def _read_lock(path: Path) -> dict:
    """잠금 파일 내용(pid·시각·라벨·토큰). 못 읽으면 빈 dict — 판정은 존재·나이로 한다."""
    info = vn_core.load_json_safe(path, {})
    return info if isinstance(info, dict) else {}


def _lock_age(path: Path) -> float | None:
    """잠금이 마지막으로 '살아 있다'고 알린 뒤 흐른 시간(초). 파일이 없으면 None."""
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _owner(info: dict) -> str:
    """잠금 주인 설명 — 어느 창·터미널을 봐야 하는지 사람에게 알려 주는 문구."""
    bits = [str(info.get("label") or "생성")]
    if info.get("pid"):
        bits.append(f"pid {info['pid']}")
    if info.get("started_at"):
        bits.append(f"{info['started_at']} 시작")
    return " · ".join(bits)


def _acquire_file(sid: str, label: str) -> str:
    """잠금 파일을 잡는다 → 토큰. 파일 잠금을 쓸 수 없는 환경이면 빈 문자열.

    살아 있는 잠금이면 VNError(=중복 과금 차단). 좌초 잠금(STALE_SEC 초과)은 회수한다.
    """
    path = _lock_path(sid)
    try:
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("생성 잠금 폴더를 만들 수 없습니다(%s) — 이 프로세스 안에서만 중복을 막습니다.", exc)
        return ""
    for _ in range(3):        # 좌초 잠금을 회수한 직후의 경합만큼만 다시 시도한다
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            age = _lock_age(path)
            if age is None:   # 방금 풀렸다 — 곧바로 다시 잡아 본다
                continue
            info = _read_lock(path)
            if age < STALE_SEC:
                raise VNError(f"{sid} 이미지를 이미 생성 중입니다({_owner(info)}). "
                              f"끝난 뒤 다시 시도하세요.")
            log.warning("좌초된 생성 잠금 회수 %s — %.0f초 방치(%s)", sid, age, _owner(info))
            with contextlib.suppress(OSError):
                os.unlink(path)
            continue
        except OSError as exc:
            log.warning("생성 잠금 파일을 만들 수 없습니다(%s) — 이 프로세스 안에서만 중복을 막습니다.", exc)
            return ""
        token = secrets.token_hex(8)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"scene_id": sid, "pid": os.getpid(), "label": str(label),
                           "started_at": datetime.now().isoformat(timespec="seconds"),
                           "token": token}, fh, ensure_ascii=False)
        except OSError as exc:   # 내용은 설명일 뿐 — 파일이 있다는 사실이 잠금이다
            log.warning("생성 잠금 설명을 쓰지 못했습니다(%s) — 잠금 자체는 유효합니다.", exc)
        return token
    raise VNError(f"{sid} 생성 잠금을 잡지 못했습니다. 잠시 뒤 다시 시도하세요.")


def _release_file(sid: str, token: str) -> None:
    """내가 잡은 잠금만 지운다 — 좌초로 회수돼 주인이 바뀐 잠금은 건드리지 않는다."""
    path = _lock_path(sid)
    info = _read_lock(path)
    if info.get("token") and info["token"] != token:
        log.warning("생성 잠금 주인이 바뀌어 해제를 건너뜁니다 %s (%s)", sid, _owner(info))
        return
    with contextlib.suppress(OSError):
        os.unlink(path)


def _touch_lock(sid: str) -> None:
    """진행 중 신호 — 잠금의 만료 시계를 지금으로 되돌린다(긴 생성이 회수당하지 않게)."""
    with contextlib.suppress(OSError):
        os.utime(_lock_path(sid), None)


# --- 선점 · 진행 표시 --------------------------------------------------------

def claim(sid: str, label: str = "생성") -> None:
    """같은 장면의 동시 생성을 막는다 — 어느 경로에서 눌러도 과금은 한 번만.

    같은 프로세스는 메모리 표시가, 다른 프로세스(웹 ↔ CLI)는 잠금 파일이 막는다.
    """
    _require_sid(sid)
    with _LOCK:
        job = _JOBS.get(sid)
        if job and job.get("running") and time.time() - float(job.get("ts") or 0) < STALE_SEC:
            raise VNError(f"{sid} 이미지를 이미 생성 중입니다. 끝난 뒤 다시 시도하세요.")
        _JOBS[sid] = {"running": True, "message": "생성 준비 중…", "ts": time.time()}
    try:
        token = _acquire_file(sid, label)
    except BaseException:
        with _LOCK:
            _JOBS.pop(sid, None)     # 잡지 못했으면 진행 표시도 남기지 않는다
        raise
    if token:
        with _LOCK:
            _OWNED[sid] = token


def note(sid: str, message: str, running: bool = True) -> None:
    """진행 문구 갱신. running=False 면 그 작업은 끝난 것으로 표시된다.

    잠금 파일은 여기서 지우지 않는다(그건 release 의 일) — 대신 만료 시계만 밀어 준다.
    """
    with _LOCK:
        _JOBS[sid] = {"running": bool(running), "message": str(message), "ts": time.time()}
        owned = sid in _OWNED
    if owned and running:
        _touch_lock(sid)


def release(sid: str, message: str = "") -> None:
    """선점 해제 — 진행 표시를 끝내고 잠금 파일을 지운다(문구를 주면 마지막 상태로 남긴다)."""
    with _LOCK:
        prev = _JOBS.get(sid) or {}
        _JOBS[sid] = {"running": False,
                      "message": str(message or prev.get("message", "") or "완료"),
                      "ts": time.time()}
        token = _OWNED.pop(sid, "")
    if token:
        _release_file(sid, token)


def release_all(message: str = "") -> list[str]:
    """이 프로세스가 잡고 있는 잠금을 전부 해제한다 — 서버 종료 경로용.

    Ctrl+C 로 끄면 생성 스레드는 daemon 이라 그 자리에서 끊긴다. 잠금 파일을 그대로 두면
    다음 실행이 최대 STALE_SEC 동안 같은 장면을 거절하므로, 정상 종료에서는 즉시 푼다.
    """
    with _LOCK:
        sids = sorted(_OWNED)
    for sid in sids:
        release(sid, message or "서버 종료로 중단됨")
    return sids


@contextlib.contextmanager
def claimed(sid: str, label: str = "생성"):
    """CLI 용 선점 블록 — 성공/실패 어느 쪽이든 표시를 반드시 해제한다.

        with gen_jobs.claimed(sid, "생성"):
            files = makefun_client.generate_for_scene(sid)
    """
    claim(sid, label)
    try:
        yield
    except BaseException as exc:
        release(sid, f"{label} 실패: {exc}")
        raise
    else:
        release(sid, f"{label} 완료")


def status(sid: str) -> dict:
    """생성 진행 조회 — {running, message, scene_id}.

    이 프로세스에 표시가 없으면 잠금 파일도 본다 — 서버 밖(CLI)에서 굽고 있는 장면을
    스튜디오가 '대기 중' 으로 잘못 보여 주고 사용자가 한 번 더 누르는 일이 없게.
    """
    _require_sid(sid)
    with _LOCK:
        job = dict(_JOBS.get(sid) or {})
        owned = sid in _OWNED
    running_now = bool(job.get("running")) and \
        time.time() - float(job.get("ts") or 0) < STALE_SEC
    if not running_now and not owned:
        path = _lock_path(sid)
        age = _lock_age(path)
        if age is not None and age < STALE_SEC:
            return {"running": True, "scene_id": sid,
                    "message": f"다른 곳에서 생성 중입니다({_owner(_read_lock(path))})."}
    return {"running": running_now, "message": str(job.get("message", "")), "scene_id": sid}


def running() -> list[str]:
    """**이 프로세스에서** 아직 끝나지 않은 생성 작업 — 종료 시 사용자에게 알려 주는 목록."""
    now = time.time()
    with _LOCK:
        return sorted(sid for sid, j in _JOBS.items()
                      if j.get("running") and now - float(j.get("ts") or 0) < STALE_SEC)


def run(sid: str, fn, label: str) -> dict:
    """생성/재수령 공통 실행틀 — 성공/실패 어느 쪽이든 선점을 반드시 해제한다.

    fn() 은 저장된 파일 경로 목록을 돌려준다. 수신 후 후보 등록·자동 검사까지 여기서 한다.
    (끝맺음은 note 가 아니라 release 다 — 잠금 파일까지 같이 풀려야 다음 실행이 막히지 않는다.)
    """
    try:
        files = list(fn())
        note(sid, f"{len(files)}장 수신 · 등록·검사 중…")
        reg = scene_ops.register_images(sid)
        reg["generated"] = [f.name for f in files]
        release(sid, f"완료 — {len(files)}장 {label} · 자동검사 {reg.get('auto', '')}")
        log.info("%s 완료 %s (%d장)", label, sid, len(files))
        return reg
    except Exception as exc:
        log.warning("%s 실패 %s: %s", label, sid, exc)
        release(sid, f"실패: {exc}")
        raise


def start(sid: str, fn, label: str, *, sync: bool = False, message: str = "",
          count: int = 0) -> dict:
    """백그라운드 기본 + sync=True 면 동기 — 폰 브라우저가 기다리다 끊기지 않게 한다."""
    claim(sid, label)
    if sync:
        return run(sid, fn, label)

    def _bg():
        try:
            run(sid, fn, label)
        except Exception:
            pass   # 사유는 run() 이 로그·진행 문구에 남긴다(스레드는 조용히 종료)

    try:
        threading.Thread(target=_bg, daemon=True).start()
    except RuntimeError:      # 스레드를 못 만들었다 — 잡아 둔 선점을 그대로 두면 영구 잠금
        release(sid, "생성을 시작하지 못했습니다.")
        raise
    return {"started": True, "running": True, "scene_id": sid,
            "message": message or f"{label} 중…", "generated": [], "auto": "진행 중",
            "count": int(count)}
