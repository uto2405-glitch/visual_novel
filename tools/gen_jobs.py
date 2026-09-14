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
     logs/ 에 쓸 수 없는 환경이면 잠금 파일을 만들지 못하고 (1) 만 남는다 — 그때는 경고를
     로그에 남긴다(보호가 조용히 사라지지 않게).

남은 잠금을 되찾는 규칙은 **두 겹**이고, 각 겹이 무엇을 보장하는지가 이 파일의 핵심이다.
어느 겹도 "살아 있을지도 모르는" 잠금은 절대 회수하지 않는다 — 회수 = 같은 이미지 2회 과금.

  a. **pid 겹(즉시·확실)** — 잠금에 적힌 주인이 *이 기기의 죽은 프로세스*임이 **확실할 때만**
     곧바로 회수한다. 판정은 `host` 가 이 기기와 같고, `pid` 가 살아 있지 않다고 OS 가
     단언할 때뿐이다. 모르겠으면(다른 기기·옛 형식 잠금·권한 거부·조회 실패) 회수하지 않고
     b 로 넘긴다. Windows 에서 ``os.kill(pid, 0)`` 은 조회가 아니라 TerminateProcess 라
     **부르면 그 프로세스가 죽는다** — 그래서 조회 전용 핸들(OpenProcess)만 연다.
     이 겹이 있어서 렌더를 죽인 뒤 20분을 기다리지 않아도 된다.
  b. **시각 겹(보수적·최후)** — 마지막 진행 갱신에서 :data:`STALE_SEC`(20분)이 지난 잠금은
     좌초로 보고 회수한다. pid 를 믿을 수 없는 모든 경우에 남는 그물이고, 예전부터 있던
     유일한 규칙이다. :func:`note` 가 시계를 밀어 주므로 오래 걸리는 생성은 스스로 늙지 않는다.

  서버를 Ctrl+C 로 끄는 정상 경로에서는 webapp 이 :func:`release_all` 로 즉시 풀어 주므로
  어느 겹도 기다릴 일이 없다.

잠금이 사는 폴더는 :data:`LOCK_DIR` 이고 기본값은 ``logs/gen_locks`` 다. 환경변수
``VN_GEN_LOCK_DIR`` 로 **명시적으로** 옮길 수 있다 — 샌드박스(selftest)가 살아 있는
저장소에 잠금을 떨어뜨리지 않게 하는 장치다. 예전에는 샌드박스가 sys.path 를 갈아끼운
덕에 *우연히* 자기 트리를 봤다. 우연은 규약이 아니므로 이제 대놓고 지정한다.

공개 API
  claim(sid, label="생성")         생성 선점 — 이미 진행 중이면 VNError
  release(sid, message="", result=None, error="")  선점 해제(진행 표시 종료 + 잠금 파일 삭제)
  release_all(message="")         이 프로세스가 잡은 잠금 전부 해제(서버 종료 경로)
  claimed(sid, label="생성")       with 문용 — 성공/실패 어느 쪽이든 반드시 해제
  note(sid, message, running=True) 진행 문구 갱신(+ 잠금 만료 시계 연장)
  run(sid, fn, label, register=True)  동기 실행틀(수신 → 후보 등록 → 자동 검사 → 해제)
  start(sid, fn, label, ...)      기본은 백그라운드, sync=True 면 동기
  status(sid)                     {running, message, scene_id, result?, error?} — 다른 프로세스의 잠금도 본다
  running()                       **이 프로세스에서** 아직 끝나지 않은 장면 목록

진행 문구는 메모리에만 있다(프로세스 수명). 진행 중에 프로세스가 꺼지면 문구는 사라지지만,
MakeFun 에 이미 만들어진 결과는 재수령(무과금) 경로로 회수할 수 있다.

끝난 작업의 **결과**(저장된 파일 이름·경고)도 같은 표시에 남겨 :func:`status` 가 함께
돌려준다. 백그라운드로 돌린 작업은 요청이 끝난 뒤에 결과가 나오므로, 진행 조회 말고는
"무엇이 저장됐는지" 를 화면에 알려 줄 통로가 없다(확대본 파일 이름이 그 예다).

Python 3.9+ · 표준 라이브러리만. (makefun_client 를 import 하지 않는다 — CLI 쪽에서
이 모듈을 불러도 순환 import 가 생기지 않게 하는 것이 이 파일의 의존 규약이다.)
"""
from __future__ import annotations

import contextlib
import ctypes
import json
import logging
import os
import secrets
import socket
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

# 잠금 파일이 사는 곳. 기본은 저장소의 logs/gen_locks 이고, VN_GEN_LOCK_DIR 로 옮길 수 있다.
# 옮길 이유는 하나뿐이다 — **샌드박스가 살아 있는 저장소를 건드리지 않게** 하는 것.
# (selftest 가 이 값을 지정한다. 사람이 쓸 일은 없다.)
_LOCK_DIR_ENV = (os.environ.get("VN_GEN_LOCK_DIR") or "").strip()
LOCK_DIR = Path(_LOCK_DIR_ENV) if _LOCK_DIR_ENV else vn_core.LOGS / "gen_locks"

# 잠금에 적어 두는 기기 이름. pid 는 기기 안에서만 뜻이 있으므로, 이 값이 다르면
# (예: 공유 폴더에 올린 저장소) pid 판정을 아예 하지 않는다.
_HOST = socket.gethostname()

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


_STILL_ACTIVE = 259                          # Windows GetExitCodeProcess: 아직 돌고 있다
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # 조회 전용 — 죽일 권한은 요구하지 않는다
_ERROR_INVALID_PARAMETER = 87                # OpenProcess 가 이걸 주면 그런 pid 가 없다는 뜻


def _pid_alive(pid: int) -> bool | None:
    """이 기기에서 pid 가 살아 있는가. **확실할 때만** True/False, 모르면 None.

    None 을 돌리는 경우가 이 함수의 존재 이유다 — 모르면 부르는 쪽이 잠금을 회수하지
    않고 시각 규칙으로 넘어간다. "아마 죽었을 것" 으로 회수하면 중복 과금이 된다.

    Windows 에서는 ``os.kill(pid, 0)`` 을 쓰지 않는다. POSIX 와 달리 그 호출은
    TerminateProcess 로 내려가 **묻는 순간 그 프로세스를 죽인다** — 남의 렌더를 죽여 놓고
    "죽어 있더라" 고 답하는 셈이다. 그래서 조회 전용 핸들만 연다.
    """
    if os.name == "nt":
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = ctypes.c_void_p      # HANDLE — 기본 c_int 면 64비트에서 잘린다
            k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
        except (AttributeError, OSError):                  # ctypes 를 못 쓰는 환경
            return None
        handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if not handle:
            # 87 = 그런 pid 가 없다(확실히 죽음). 5(접근 거부) 등은 '있는데 못 본다' 일 수 있다.
            return False if ctypes.get_last_error() == _ERROR_INVALID_PARAMETER else None
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            # 종료 코드 259 로 정상 종료한 프로세스도 여기서는 '살아 있음' 으로 보인다.
            # 그 착각의 대가는 '조금 늦게 회수' 뿐이다 — 안전한 쪽으로 틀린다.
            return code.value == _STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)                # POSIX 에서는 이것이 진짜 조회다
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                    # 있는데 내 것이 아니다 = 살아 있다
    except OSError:
        return None
    return True


def _is_dead_owner(info: dict) -> bool:
    """잠금 주인이 **이 기기의 죽은 프로세스**임이 확실할 때만 True.

    확실하지 않은 모든 경우는 False 다(= 회수하지 않는다). 그래서 이 함수는 중복 과금을
    새로 만들 수 없다 — 기껏해야 시각 규칙이 원래 하던 일을 그대로 하게 둘 뿐이다:

      * ``host`` 가 없다(옛 형식 잠금) 또는 이 기기가 아니다 → pid 는 남의 번호다
      * pid 가 없거나 정수가 아니다 → 판정할 것이 없다
      * pid 가 나 자신이다 → 같은 프로세스의 경합이라 메모리 표시(_JOBS)가 판단할 몫
      * :func:`_pid_alive` 가 True 나 None → 살아 있거나 모른다
    """
    if not isinstance(info, dict) or info.get("host") != _HOST:
        return False
    pid = info.get("pid")
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return False
    return _pid_alive(pid) is False


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
            # (a) pid 겹 — 주인이 이 기기의 죽은 프로세스라고 OS 가 단언하면 즉시 회수한다.
            #     렌더를 죽였을 때 같은 장면이 20분간 잠기던 것이 이 줄로 사라진다.
            if _is_dead_owner(info):
                log.warning("죽은 생성 잠금 회수 %s — 주인 프로세스가 없습니다(%s)", sid, _owner(info))
                with contextlib.suppress(OSError):
                    os.unlink(path)
                continue
            # (b) 시각 겹 — pid 를 믿을 수 없는 나머지 전부. 살아 있을 가능성이 남아 있으면 막는다.
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
                json.dump({"scene_id": sid, "pid": os.getpid(), "host": _HOST,
                           "label": str(label),
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


def release(sid: str, message: str = "", result: dict | None = None,
            error: str = "") -> None:
    """선점 해제 — 진행 표시를 끝내고 잠금 파일을 지운다(문구를 주면 마지막 상태로 남긴다).

    result 는 끝난 작업이 남긴 구조화된 결과(저장 파일 이름 등)다. 문구는 사람이 읽는
    한 줄이고, 이쪽은 화면이 파싱 없이 쓸 수 있는 형태로 :func:`status` 에 함께 실린다.

    error 는 **실패했다는 사실 자체**다. 예전에는 실패가 문구 안에("실패: …") 만 남아서,
    화면(studio.js pollGenUntilDone)이 보는 error 키가 영영 오지 않았다 — 토큰 없는
    업스케일이 "확대본을 저장했습니다" 로 끝났다. 문구는 사람이 읽고 이 키는 기계가 읽는다.
    """
    with _LOCK:
        prev = _JOBS.get(sid) or {}
        _JOBS[sid] = {"running": False,
                      "message": str(message or prev.get("message", "") or "완료"),
                      "ts": time.time()}
        if error:
            _JOBS[sid]["error"] = str(error)
        if isinstance(result, dict):
            _JOBS[sid]["result"] = dict(result)   # 사본 — 호출부가 나중에 고쳐도 표시는 그대로
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
        release(sid, f"{label} 실패: {exc}", error=str(exc))
        raise
    else:
        release(sid, f"{label} 완료")


def status(sid: str) -> dict:
    """생성 진행 조회 — {running, message, scene_id, error?}.

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
            # 회수 규칙과 같은 두 겹을 본다. 그러지 않으면 죽은 잠금을 두고 화면은
            # "다른 곳에서 생성 중" 이라 말하는데 [생성] 버튼은 통과하는 모순이 생긴다.
            info = _read_lock(path)
            if not _is_dead_owner(info):
                return {"running": True, "scene_id": sid,
                        "message": f"다른 곳에서 생성 중입니다({_owner(info)})."}
    out = {"running": running_now, "message": str(job.get("message", "")), "scene_id": sid}
    err = str(job.get("error", "") or "")
    if err and not running_now:
        out["error"] = err                 # 실패는 문구가 아니라 이 키로 말한다(화면이 보는 자리)
    if isinstance(job.get("result"), dict):
        out["result"] = job["result"]      # 끝난 작업이 남긴 것(저장 파일 이름·경고)
    return out


def running() -> list[str]:
    """**이 프로세스에서** 아직 끝나지 않은 생성 작업 — 종료 시 사용자에게 알려 주는 목록."""
    now = time.time()
    with _LOCK:
        return sorted(sid for sid, j in _JOBS.items()
                      if j.get("running") and now - float(j.get("ts") or 0) < STALE_SEC)


def run(sid: str, fn, label: str, *, register: bool = True) -> dict:
    """생성/재수령/확대 공통 실행틀 — 성공/실패 어느 쪽이든 선점을 반드시 해제한다.

    fn() 은 저장된 파일 경로 목록을 돌려준다(경고를 함께 실은 makefun_client.GenResult 도
    list 라 그대로 받는다 — 경고는 결과·문구에 옮겨 싣는다). 수신 후 후보 등록·자동 검사까지
    여기서 한다.
    (끝맺음은 note 가 아니라 release 다 — 잠금 파일까지 같이 풀려야 다음 실행이 막히지 않는다.)

    **register=False 는 fn() 이 등록까지 스스로 책임진 경우다**(확대 경로). 여기서 한 번 더
    scene_ops.register_images 를 부르면 APPROVED 장면에서 VNError 가 나고, **이미 과금돼
    파일까지 저장된 작업이 '실패' 로 보고된다** — 돈은 나갔는데 화면은 실패인 최악의 조합이다.
    (확대는 그림을 바꾸지 않으므로 승인 장면에서도 허용되는 대신, 후보 목록을 건드릴지는
     makefun_client 가 판단해 경고로 알린다.)
    """
    try:
        res = fn()
        files = list(res)
        names = [Path(f).name for f in files]
        # 경고는 화면 한 줄에 실리므로 줄바꿈만 편다(내용은 자르지 않는다 — "결과가 원본보다
        # 크지 않습니다" 처럼 돈이 걸린 문장이 여기 온다).
        warns = [" ".join(str(w).split()) for w in (getattr(res, "warnings", None) or ())]
        if not register:
            out = {"scene_id": sid, "generated": names, "count": len(names),
                   "auto": "", "warnings": warns, "locked": False}
            release(sid, " · ".join([f"완료 — {label} {len(names)}장"] + names + warns),
                    result=out)
            log.info("%s 완료 %s (%s)", label, sid, ", ".join(names) or "0장")
            return out
        note(sid, f"{len(files)}장 수신 · 등록·검사 중…")
        reg = scene_ops.register_images(sid)
        reg["generated"] = names
        if warns:
            reg["warnings"] = warns
        release(sid, f"완료 — {len(files)}장 {label} · 자동검사 {reg.get('auto', '')}",
                result=reg)
        log.info("%s 완료 %s (%d장)", label, sid, len(files))
        return reg
    except Exception as exc:
        log.warning("%s 실패 %s: %s", label, sid, exc)
        release(sid, f"실패: {exc}", error=str(exc))
        raise


def start(sid: str, fn, label: str, *, sync: bool = False, message: str = "",
          count: int = 0, register: bool = True) -> dict:
    """백그라운드 기본 + sync=True 면 동기 — 폰 브라우저가 기다리다 끊기지 않게 한다."""
    claim(sid, label)
    if sync:
        return run(sid, fn, label, register=register)

    def _bg():
        try:
            run(sid, fn, label, register=register)
        except Exception:
            pass   # 사유는 run() 이 로그·진행 문구에 남긴다(스레드는 조용히 종료)

    try:
        threading.Thread(target=_bg, daemon=True).start()
    except RuntimeError:      # 스레드를 못 만들었다 — 잡아 둔 선점을 그대로 두면 영구 잠금
        release(sid, "생성을 시작하지 못했습니다.", error="생성을 시작하지 못했습니다.")
        raise
    return {"started": True, "running": True, "scene_id": sid,
            "message": message or f"{label} 중…", "generated": [], "auto": "진행 중",
            "count": int(count)}
