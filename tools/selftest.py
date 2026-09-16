#!/usr/bin/env python3
"""패키지 자가진단 — 임시 샌드박스 사본에서 전체 파이프라인을 검증한다.

사용법:
  python tools/selftest.py                전체 실행
  python tools/selftest.py --list         테스트 목록(그룹별)만 보기
  python tools/selftest.py -k webapp      이름·그룹에 'webapp' 이 든 것만 실행 (여러 번 지정 가능)
  python tools/selftest.py -k P03 -k B02  개별 테스트만
  python tools/selftest.py --keep         실패했을 때 샌드박스를 지우지 않고 경로 출력
  python tools/selftest.py --strict       구조적 공백(GAP)도 실패로 취급 (계약 도착 확인용)

판정 네 가지 — SKIP 하나로 뭉뚱그리지 않는다
  PASS  검증됨.
  FAIL  계약 위반. 고쳐야 한다.
  SKIP  **이 환경에서 검사할 수 없음**(Pillow·node 부재). 코드에는 문제가 없다.
  GAP   **구조적 공백**: 검사할 대상(모듈·라우트·필드)이 아직 저장소에 없다.
        SKIP 과 섞으면 커버리지 구멍이 조용해진다 — 그래서 따로 세고 따로 보여 준다.
        대상이 도착하는 순간 같은 테스트가 저절로 회귀 잠금이 된다(코드 수정 불필요).
        GAP 은 "아직 없다"에만 쓴다. 있는데 동작이 틀리면 그것은 FAIL 이다.

설계 원칙
  * 사용자의 project/ · images/ 원본은 절대 건드리지 않는다 — 모든 실행은 샌드박스 사본에서.
  * 유료 API(MakeFun)는 절대 호출하지 않는다. 네트워크가 나가는 지점만 스텁으로 막는다.
    MakeFun 은 REST(_once)·결과 다운로드(_fetch_bytes)·R2 업로드(_UP) 세 곳을 스텁으로 막고,
    남은 opener(_API·_DL)는 **열리는 순간 그 테스트를 실패**시킨다 — 스텁을 우회하는 전송
    경로가 새로 생기면 조용히 통과하지 못한다(mf_stub). 응답 정규화처럼 _once 안에 있는
    동작은 한 겹 아래(mf_raw)에서 진짜 _once 를 지나가며 검사한다.
    ComfyUI 는 무료·로컬이지만 이 PC 에 켜져 있든 말든 결과가 같아야 하므로 HTTP 계약을
    흉내내는 모의 서버(ComfyMock)를 띄우고 샌드박스 매니페스트 주소만 그쪽으로 돌린다.
  * 웹 스튜디오는 **첫 web=True 테스트에서 한 번만** 뜨고 나머지 웹 테스트가 그 서버를 그대로
    쓴다(Box._web 재사용). 그래서 기동 비용은 실행당 한 번뿐이고, 러너는 그 시간을 테스트
    시간에서 빼서 따로 보여 준다 — 첫 웹 테스트가 느린 것처럼 보이던 착시를 없앤다.
  * 확실히 존재하는 모듈은 optional 로 눅이지 않는다(REQUIRED_MODULES · meta T01 이 감시).
  * 코드만 검사 대상이 아니다 — 문서가 코드 상수를 복제한 자리(SCHEMA.md)도 기계가 대조한다
    (arch L06). 산문은 조용히 거짓말을 시작하고, 사용자는 그 산문대로 손을 댄다.
  * 테스트는 서로의 뒷정리에 기대지 않는다 — 상태를 바꾸면 픽스처가 반드시 원상 복구한다.
  * 한 테스트에서 난 예외는 그 테스트의 FAIL 로만 귀속된다(전체 실행이 멈추지 않는다).

수정 후에는 반드시 이 스크립트로 회귀를 확인한다.
"""
from __future__ import annotations

import argparse
import ast
import base64
import concurrent.futures
import contextlib
import datetime as dt
import fnmatch
import http.server
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request as ur
import uuid
import zipfile
import zlib
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
PY = sys.executable
ADV = "tools/advance_scene.py"
CHK = "tools/check_protocol.py"

# studio.html / 감상본 HTML / 공용 런타임이 절대 쓰면 안 되는 DOM API (문자열 주입 경로)
BANNED_DOM = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")

# 이 저장소에 **확실히 있는** 모듈 — 없거나 적재에 실패하면 SKIP 이 아니라 FAIL 이다.
# (새 모듈이 생길 때마다 optional=True 로 눅이면 커버리지 공백이 조용히 늘어난다.
#  meta T01 이 이 목록을 두 방향으로 감시한다: 파일 존재·적재 + optional 되돌림 금지.)
REQUIRED_MODULES = (
    "vn_core", "advance_scene", "scene_ops", "talk_store", "prompt_build", "local_llm",
    "works", "characters",
    "webapp", "vn_compose", "export_viewer", "makefun_client", "scene_lint",
    "secret_scan", "backup_project", "print_preflight", "gen_jobs",
    # 여기 없으면 '구문 검사만 받고 아무도 부르지 않는' 상태가 조용히 유지된다.
    # doctor 는 README·start_studio.ps1·복구 런북이 안내하는 1차 진단 도구이고,
    # export_pwa 는 살아 있는 라우트(/api/export-pwa)가 직접 부른다.
    "doctor", "export_pwa", "scene_brief", "print_export",
    # 이미지 엔진이 둘이 되면서 생긴 세 모듈 — 공용 조각·로컬 클라이언트·선택기.
    "gen_common", "comfyui_client", "image_gen",
)

# REQUIRED_MODULES 밖에 있어도 되는 유일한 목록 — 이유를 함께 적는다(T01 이 나머지를 잡는다).
NOT_IMPORTED = {
    "check_protocol": "도구가 고칠 수 없는 판정자 — 자가진단도 서브프로세스로만 부른다"
                      "(P01·P02·C01~C06). 소스는 읽되 import 하지 않는다.",
}

# 저장소가 선언한 계층(vn_core.py 머리말: vn_core ← scene_ops ← advance_scene ← webapp).
# 숫자가 작을수록 아래층이고, **아래층은 위층을 import 하지 않는다** — 함수 본문의 지연
# import 도 같은 무게로 센다(예외는 그 도구의 CLI 진입점뿐이다. CLI_ENTRY 참조).
#
# 예전에는 다섯 모듈만 여기 있었다 — 나머지 그래프는 '순환이 되어야만' 걸렸고, 순환이 아닌
# 역방향 의존(예: export_viewer 가 webapp 을 부르는 식)은 아무 검사도 받지 않았다.
# 이제 모든 도구가 위치를 갖고(L01 이 미부여를 잡는다), 방향이 기계로 강제된다.
LAYER = {
    # 0 기반 — 도구를 부르지 않는다. 검사기(check_protocol)가 여기 있는 이유는 그것이
    #   도구가 고칠 수 없는 판정자이기 때문이다(도구를 import 하면 도구 쪽 전역 상태가
    #   판정에 섞인다 — 그래서 부르는 쪽도 서브프로세스로만 부른다).
    "vn_core": 0, "check_protocol": 0,
    # 1 저장소·전송 계층 — vn_core 만 본다. gen_common 은 두 이미지 클라이언트가 함께 쓰는
    #   결과형·메타·대장 조각이라 클라이언트보다 아래에 있어야 한다.
    "talk_store": 1, "scene_ops": 1, "local_llm": 1, "secret_scan": 1, "works": 1, "characters": 1,
    "scene_brief": 1, "export_viewer": 1, "print_export": 1, "backup_project": 1,
    "gen_common": 1,
    # 2 조립·전이 계층
    "advance_scene": 2, "prompt_build": 2, "gen_jobs": 2, "export_pwa": 2,
    # 3 외부 연동·오케스트레이션 — 두 이미지 클라이언트는 서로를 모른다(고르는 것은 image_gen).
    #   scene_lint 가 여기 있는 이유는 **조립부 위**여야 하기 때문이다: 저장된 프롬프트를
    #   지금 조립부가 내는 것과 비교하려면(prompt-drift) prompt_build 를 부른다. 그래서
    #   어휘·정규화 같은 공유 규칙은 vn_core 로 내려가 있다(양방향 import 가 되지 않게).
    "makefun_client": 3, "comfyui_client": 3, "vn_compose": 3, "scene_lint": 3,
    # 4 엔진 선택기 — 두 클라이언트 위에 서고, webapp·doctor 만 부른다.
    "image_gen": 4,
    # 5 최상위 진입점 — 아무도 이들을 import 하지 않는다.
    "webapp": 5, "doctor": 5,
}

# 계층을 부여하지 않는 모듈과 그 이유. 비워 두면(=이름을 안 적으면) L01 이 미부여로 잡는다.
UNLAYERED = {
    "print_preflight": "makefun_client 와 서로를 안내문으로만 인용하는 지연 고리가 남아 있다"
                       "(LAZY_CYCLE_OK 참조) — 둘 중 어느 쪽도 위에 놓을 수 없다.",
}

# 서로를 함수 본문에서 지연 import 하는 것이 **설계인** 쌍. 양쪽 다 상대의 판정을 안내문으로
# 인용할 뿐이고(크기 상한 ↔ 인화 규격), import 시점 고리를 만들지 않는다. 여기 없는 새 고리는
# L02 가 떨어뜨린다 — 허용 목록은 이 한 쌍뿐이다.
LAZY_CYCLE_OK = {frozenset({"makefun_client", "print_preflight"})}

# 그 모듈의 CLI 진입점 — 라이브러리 경로가 아니라 '그 도구를 직접 실행한 사람'이다.
# 여기 안의 import 는 계층·순환 판정에서 뺀다(모듈을 import 해도 실행되지 않으므로
# import 시점 고리를 만들 수 없다). 대신 최상위·다른 함수 본문의 import 는 전부 센다.
CLI_ENTRY = ("main",)

# 새 장면을 만들며 찍는 초기 상태. 이 두 값에는 사람 승인 게이트가 걸려 있지 않다.
# 나머지 상태(IMAGE·REVIEW_HUMAN·REVISE·APPROVED)는 scene_ops 만 쓸 수 있다(L03).
AUTHORING_STATES = ("SCENE_PLAN", "PROMPT")


def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


# ============================================================ 판정 · 레지스트리
class Skip(Exception):
    """이 환경에서는 검사할 수 없음(Pillow·node 부재) — 통과로 집계하지 않는다."""


class Gap(Skip):
    """검사 대상이 아직 저장소에 없음 — '환경 탓 SKIP' 과 구분해서 집계한다.

    Skip 을 상속하므로 러너를 거치지 않고 도는 코드에서도 안전하게 취급되지만,
    러너는 Gap 을 먼저 잡아 GAP 으로 따로 센다(--strict 면 FAIL).
    """


class Failed(AssertionError):
    """검사 실패."""


def ok(cond, detail: str = "") -> None:
    if not cond:
        raise Failed(detail or "조건이 성립하지 않음")


def eq(got, want, label: str = "") -> None:
    if got != want:
        raise Failed(f"{label + ': ' if label else ''}{got!r} != 기대 {want!r}")


def has(text: str, needle: str, label: str = "") -> None:
    if needle not in (text or ""):
        raise Failed(f"{label + ': ' if label else ''}{needle!r} 없음 — {(text or '')[:200]!r}")


def hasnt(text: str, needle: str, label: str = "") -> None:
    if needle in (text or ""):
        raise Failed(f"{label + ': ' if label else ''}{needle!r} 가 들어 있음 — {(text or '')[:200]!r}")


def raises(fn, exc=Exception, label: str = "") -> BaseException:
    """fn 이 exc 를 던져야 한다. 던지지 않으면 실패."""
    try:
        fn()
    except exc as e:            # noqa: B902 — 기대한 예외
        return e
    except Exception as e:      # 다른 예외는 실패로 본다(크래시 방지 검증)
        raise Failed(f"{label + ': ' if label else ''}{type(e).__name__} 발생(기대: {exc.__name__}) — {e}")
    raise Failed(f"{label + ': ' if label else ''}{exc.__name__} 가 발생하지 않음")


_REG: list[dict] = []


def test(group: str, name: str, web: bool = False):
    """테스트 등록 데코레이터. web=True 면 러너가 웹 스튜디오를 먼저 띄운다."""
    def deco(fn):
        _REG.append({"group": group, "name": name, "fn": fn, "web": web})
        return fn
    return deco


# ============================================================ 공용 픽스처
def write_png(path: Path, w: int, h: int, rgb=(210, 180, 150)) -> None:
    """Pillow 없이 유효한 RGB PNG 생성 (검사기 A3 의 크기 판독 대상)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * w
    idat = zlib.compress(row * h, 6)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def edit_json(path: Path, fn) -> None:
    d = read_json(path)
    fn(d)
    write_json(path, d)


@contextlib.contextmanager
def patched(obj, name: str, value):
    """속성 임시 교체 — 스텁·격리용. 예외가 나도 반드시 되돌린다."""
    missing = object()
    old = getattr(obj, name, missing)
    setattr(obj, name, value)
    try:
        yield value
    finally:
        if old is missing:
            try:
                delattr(obj, name)
            except AttributeError:
                pass
        else:
            setattr(obj, name, old)


@contextlib.contextmanager
def replaced_text(path: Path, text: str):
    """파일 내용을 잠시 바꾸고 반드시 원상 복구한다(테스트 간 상태 결합 차단)."""
    path = Path(path)
    orig = path.read_text(encoding="utf-8") if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        yield path
    finally:
        if orig is None:
            with contextlib.suppress(OSError):
                path.unlink()
        else:
            path.write_text(orig, encoding="utf-8")


def corrupted(path: Path, text: str = '[{"scene_id":"BROKEN"}]'):
    """파일을 '손상 상태'로 만들고 블록을 벗어나면 되돌린다.

    손상 관용성 테스트가 앞 테스트의 복구에 기대던 결합(구 T52 사고)을 없앤다.
    """
    return replaced_text(path, text)


@contextlib.contextmanager
def hidden(path: Path):
    """파일을 잠시 없앤 것처럼 만든다(이름 변경) — 첫 실행 안내 검증용."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".selftest-hidden")
    existed = path.exists()
    if existed:
        os.replace(path, tmp)
    try:
        yield path
    finally:
        if existed:
            os.replace(tmp, path)


@contextlib.contextmanager
def env_var(name: str, value: str | None):
    old = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


@contextlib.contextmanager
def quiet():
    """도구의 print 를 삼켜 자가진단 출력이 지저분해지지 않게 한다. 버퍼를 돌려준다."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


# ============================================================ 샌드박스
_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".git", ".claude", "scene_briefs",
    "backups", "output", "logs", "scratch", "*.zip", ".venv", "node_modules")


class Box:
    """샌드박스 저장소 + 실행 도우미. 모든 테스트가 이 하나를 공유한다."""

    def __init__(self, root: Path):
        self.root = root
        self.env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        self._mods: dict[str, object] = {}
        self._syspath: list[str] | None = None
        self._lockdir_keep: str | None = None      # VN_GEN_LOCK_DIR 원래 값
        self._lockdir_had = False                  # 원래 설정돼 있었는가(복원용)
        self._web: subprocess.Popen | None = None
        self._web_error: str | None = None
        self._mock = None
        self.web_port = 0
        self.boot_secs = 0.0        # 웹 스튜디오 기동에 쓴 시간(실행당 한 번) — 러너가 따로 센다
        self._opener = ur.build_opener(ur.ProxyHandler({}))

    # -------------------------------------------------- 준비 · 정리
    def build(self) -> None:
        shutil.copytree(SRC, self.root, ignore=_IGNORE)
        # 작업 영역을 빈 상태로 초기화 (사용자 데이터가 복사돼 왔어도 원본은 불변)
        shutil.rmtree(self.root / "project", ignore_errors=True)
        (self.root / "project" / "scenes").mkdir(parents=True)
        shutil.rmtree(self.root / "images" / "raw", ignore_errors=True)
        (self.root / "images" / "raw").mkdir(parents=True)
        (self.root / "logs").mkdir(exist_ok=True)
        # 데모 기준 상태 — 모든 테스트의 공통 출발점(검사기 GREEN)
        shutil.copy(self.root / "examples" / "manifest.json", self.root / "project" / "manifest.json")
        shutil.copy(self.root / "examples" / "scenes" / "SCENE-001.json",
                    self.root / "project" / "scenes" / "SCENE-001.json")
        # in-process 로 적재하는 모듈이 원본 저장소 대신 반드시 샌드박스를 보게 한다.
        self._syspath = list(sys.path)
        real = str((SRC / "tools").resolve())
        sys.path[:] = [p for p in sys.path if str(Path(p or ".").resolve()) != real]
        sys.path.insert(0, str(self.root / "tools"))
        # 생성 잠금도 샌드박스 안에서만 떨어지게 **명시**한다. 예전에도 결과는 같았지만
        # 그건 위의 sys.path 교체가 만든 부수효과였다(gen_jobs → import vn_core → 샌드박스
        # 사본 → ROOT 가 샌드박스). vn_core 가 먼저 sys.modules 에 실리는 경로가 하나만
        # 생겨도 조용히 깨지고, 그때는 사람이 쓰는 저장소의 장면이 최대 STALE_SEC 동안
        # 잠긴다. 우연 대신 계약으로 바꾼다 — U11b 가 이 계약을 지킨다.
        lock_dir = str(self.root / "logs" / "gen_locks")
        self._lockdir_had = "VN_GEN_LOCK_DIR" in os.environ
        self._lockdir_keep = os.environ.get("VN_GEN_LOCK_DIR")
        os.environ["VN_GEN_LOCK_DIR"] = lock_dir     # in-process 로 적재하는 사본
        self.env["VN_GEN_LOCK_DIR"] = lock_dir       # b.run 으로 띄우는 하위 프로세스

    def close(self) -> None:
        if self._web is not None:
            with contextlib.suppress(Exception):
                self._web.terminate()
                self._web.wait(timeout=10)
            self._web = None
        if self._mock is not None:
            with contextlib.suppress(Exception):
                self._mock.shutdown()
                self._mock.server_close()
            self._mock = None
        if self._syspath is not None:
            sys.path[:] = self._syspath
            self._syspath = None
        if self._lockdir_had:
            os.environ["VN_GEN_LOCK_DIR"] = self._lockdir_keep or ""
        else:
            os.environ.pop("VN_GEN_LOCK_DIR", None)

    # -------------------------------------------------- 경로 · 데이터
    def p(self, rel: str) -> Path:
        return self.root / rel

    def scene_path(self, sid: str) -> Path:
        return self.root / "project" / "scenes" / f"{sid}.json"

    def scene(self, sid: str) -> dict:
        return read_json(self.scene_path(sid))

    def manifest(self) -> dict:
        return read_json(self.root / "project" / "manifest.json")

    def anchors(self) -> tuple[str, str]:
        mf = self.manifest()
        return (mf["characters"][0]["prompt_anchor"], mf["locations"][0]["prompt_anchor"])

    def next_ids(self) -> tuple[str, int]:
        """(다음 scene_id, 다음 scene_order) — A5(1..N 연속)를 깨지 않는 값."""
        nums, orders = [], []
        for p in (self.root / "project" / "scenes").glob("*.json"):
            m = re.fullmatch(r"SCENE-(\d+)", p.stem)
            if m:
                nums.append(int(m.group(1)))
            try:
                v = read_json(p).get("scene_order")
            except Exception:
                v = None
            if isinstance(v, int):
                orders.append(v)
        return f"SCENE-{(max(nums) + 1 if nums else 1):03d}", (max(orders) + 1 if orders else 1)

    # -------------------------------------------------- 서브프로세스
    def run(self, *args: str, env: dict | None = None) -> tuple[int, str]:
        e = dict(env if env is not None else self.env)
        p = subprocess.run([PY, *args], cwd=self.root, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=e)
        return p.returncode, p.stdout + p.stderr

    def checker(self, *args: str) -> tuple[int, str]:
        return self.run(CHK, *args)

    # -------------------------------------------------- in-process 모듈
    def mod(self, name: str, optional: bool = False):
        """tools/<name>.py 를 샌드박스에서 in-process 로 적재(캐시).

        기본은 **필수**다 — 없거나 적재 실패면 FAIL. 아직 도착하지 않은 모듈에는
        optional 대신 :func:`need_mod` 를 쓴다(GAP 으로 따로 집계된다).
        optional=True 는 REQUIRED_MODULES 에 없는 모듈에만 허용된다(meta T01 이 감시).
        """
        if name in self._mods:
            return self._mods[name]
        path = self.root / "tools" / f"{name}.py"
        if not path.exists():
            raise Skip(f"tools/{name}.py 없음")
        spec = importlib.util.spec_from_file_location(f"box_{name}", str(path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            sys.modules.pop(spec.name, None)
            if optional:
                raise Skip(f"{name} 적재 실패(이관 중일 수 있음): {type(e).__name__}: {e}")
            raise Failed(f"{name} 적재 실패: {type(e).__name__}: {e}")
        self._mods[name] = mod
        return mod

    # -------------------------------------------------- 웹 스튜디오
    def ensure_web(self) -> None:
        if self._web is not None and self._web.poll() is None:
            return
        if self._web_error:      # 한 번 실패했으면 나머지 웹 테스트는 즉시 실패시킨다(재시도 대기 낭비 방지)
            raise Failed(self._web_error)
        t0 = time.perf_counter()
        try:
            self._start_web()
        except Failed as e:
            self._web_error = str(e)
            raise
        finally:
            self.boot_secs += time.perf_counter() - t0

    def _start_web(self) -> None:
        anchor_c, anchor_l = self.anchors()
        scenes_json = json.dumps([
            {"order": 1, "purpose": "도입", "action_beat": "창밖 응시", "emotion": "긴장",
             "time": "방과 후", "location_id": "LOC-001",
             "camera": {"shot": "medium", "angle": "eye", "framing": "left", "focus": "face"},
             "dialogue": [{"speaker_id": "CHAR-001", "text": "오늘은 꼭 말할 거야."}],
             "image_prompt": f"medium shot, {anchor_c}, {anchor_l}, cel shading"},
            {"order": 2, "purpose": "결심", "action_beat": "복도에서 주먹", "emotion": "떨림",
             "time": "방과 후", "location_id": "LOC-001",
             "camera": {"shot": "close-up", "angle": "low", "framing": "center", "focus": "fist"},
             "dialogue": [{"speaker_id": "CHAR-001", "text": "지금이야."}],
             "image_prompt": f"close-up, {anchor_c}, {anchor_l}, cel shading"},
        ], ensure_ascii=False)

        class MockLLM(http.server.BaseHTTPRequestHandler):
            """OpenAI 호환 최소 서버 — 오케스트레이터(장면 구성)와 인물 대화가 함께 쓴다.

            실제 로컬 LLM(:8080)이 떠 있든 말든 자가진단 결과가 같아야 한다. 이 모의 서버가
            있기 때문에 **LLM 이 꺼진 PC 에서도 LLM-켜짐 경로가 검증된다**(W02·W12 등).
            """
            payload = scenes_json

            def log_message(self, *a):
                pass

            def _send(self, obj):
                raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):                     # /models — 서버 살아있음 확인용
                self._send({"data": [{"id": "mock-model"}]})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                last = (body.get("messages") or [{}])[-1].get("content", "")
                content = self.payload if "SCENES_JSON_ONLY" in last else "모의 응답: 좋은 방향이에요."
                self._send({"choices": [{"message": {"content": content}}]})

        self._mock = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockLLM)
        threading.Thread(target=self._mock.serve_forever, daemon=True).start()
        mock_url = f"http://127.0.0.1:{self._mock.server_address[1]}/v1"
        self.set_api(mock_url, "mock-model")
        # 오케스트레이터가 로컬 LLM 으로 설정돼 있어도(manifest mode=local) 같은 모의 서버를 쓴다.
        self.env["LOCAL_LLM_URL"] = mock_url

        with socket.socket() as s0:
            s0.bind(("127.0.0.1", 0))
            self.web_port = s0.getsockname()[1]
        wenv = dict(self.env)
        wenv["NO_PROXY"] = wenv["no_proxy"] = "127.0.0.1,localhost"
        self._web = subprocess.Popen(
            [PY, "tools/webapp.py", "--port", str(self.web_port), "--no-browser"],
            cwd=self.root, env=wenv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 처음 1초는 촘촘히(50ms) 물어본다 — 보통 여기서 끝난다. 그 뒤에는 느슨하게(200ms)
        # 최대 17초까지 기다린다(느린 PC 의 첫 import·백신 검사 몫).
        for i in range(100):
            if self._web.poll() is not None:
                raise Failed("웹 스튜디오가 기동 직후 종료했습니다.")
            code, _h, _b = self.raw("/api/state")
            if code == 200:
                return
            time.sleep(0.05 if i < 20 else 0.2)
        raise Failed(f"웹 스튜디오가 기동하지 않았습니다(port {self.web_port}).")

    def set_api(self, base_url: str, model: str) -> None:
        edit_json(self.root / "project" / "manifest.json",
                  lambda d: d.setdefault("orchestrator", {}).setdefault("api", {}).update(
                      {"base_url": base_url, "model": model}))

    @contextlib.contextmanager
    def api_pointed_at(self, base_url: str, model: str = "m"):
        """orchestrator.api 를 잠시 다른 서버로 돌리고 반드시 되돌린다."""
        mf = self.manifest()
        api = dict((mf.get("orchestrator") or {}).get("api") or {})
        self.set_api(base_url, model)
        try:
            yield
        finally:
            self.set_api(api.get("base_url", "http://127.0.0.1:8080/v1"), api.get("model", "TBD"))

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.web_port}{path}"

    def raw(self, path: str, data: bytes | None = None, headers: dict | None = None,
            timeout: int = 20) -> tuple[int, dict, bytes]:
        """(status, headers, body). HTTPError 도 상태코드로 돌려준다. 연결 절단은 -1."""
        req = ur.Request(self.url(path), data=data, headers=headers or {})
        try:
            with self._opener.open(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            body = b""
            with contextlib.suppress(Exception):
                body = e.read()
            return e.code, dict(e.headers or {}), body
        except Exception as e:
            return -1, {}, str(e).encode("utf-8", "replace")

    def wapi(self, path: str, payload=None, headers: dict | None = None,
             timeout: int = 20) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        h = dict(headers or {})
        if data:
            h.setdefault("Content-Type", "application/json")
        code, _hd, body = self.raw(path, data, h, timeout)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            parsed = {}
        return code, (parsed if isinstance(parsed, dict) else {"_list": parsed})

    def code(self, path: str, payload=None, headers: dict | None = None) -> int:
        return self.wapi(path, payload, headers)[0]


# ------------------------------------------------------------ 계약 도착 확인
def need_mod(b: Box, name: str):
    """이번 라운드에 **도착해야 하는** 모듈 — 없으면 GAP, 있는데 적재 실패면 FAIL.

    "아직 없다"(GAP)와 "있는데 깨졌다"(FAIL)를 갈라 두는 지점이다.
    """
    if not b.p(f"tools/{name}.py").exists():
        raise Gap(f"tools/{name}.py 아직 없음 — 이번 라운드 이관 대기")
    return b.mod(name)


def need_attr(mod, name: str, what: str):
    """모듈에 아직 없는 공개 API — GAP. (있으면 그 자리에서 돌려준다.)"""
    fn = getattr(mod, name, None)
    if fn is None:
        raise Gap(f"{getattr(mod, '__name__', '?').replace('box_', '')}.{name} 아직 없음 — {what}")
    return fn


def csp_directive(csp: str, name: str) -> str:
    """CSP 헤더에서 지시문 하나의 값만 뽑는다. 없으면 빈 문자열.

    (헤더 전체를 문자열로 훑으면 style-src 의 'unsafe-inline' 이 script-src 검사에
     걸려 통과/실패가 뒤집힌다. 그래서 지시문 단위로 자른다.)
    """
    for part in str(csp or "").split(";"):
        bits = part.strip().split()
        if bits and bits[0].lower() == name.lower():
            return " ".join(bits[1:])
    return ""


# ------------------------------------------------------------ 장면 픽스처
@contextlib.contextmanager
def fresh_scene(b: Box, **over):
    """검사기가 통과하는 새 장면을 하나 만들고, 블록을 벗어나면 흔적 없이 지운다.

    scene_order 는 마지막 번호 다음을 쓰고 정리도 LIFO 라 A5(1..N 연속)가 유지된다.
    """
    sid, order = b.next_ids()
    data = read_json(b.root / "examples" / "scenes" / "SCENE-001.json")
    data["scene_id"] = sid
    data["scene_order"] = order
    data.update(over)
    write_json(b.scene_path(sid), data)
    try:
        yield sid
    finally:
        with contextlib.suppress(OSError):
            b.scene_path(sid).unlink()
        shutil.rmtree(b.root / "images" / "raw" / sid, ignore_errors=True)


@contextlib.contextmanager
def cli_scene(b: Box, stage: str = "PLAN", images: int = 2):
    """advance_scene CLI 로 장면을 만들어 원하는 단계까지 올린다.

    stage: PLAN → PROMPT → REVIEW(후보 등록까지 — 상태는 IMAGE) → APPROVED
    각 테스트가 자기 장면을 갖게 해 앞 테스트의 잔여 상태에 기대지 않는다.
    """
    before = {p.name for p in (b.root / "project" / "scenes").glob("*.json")}
    rc, out = b.run(ADV, "new")
    after = {p.name for p in (b.root / "project" / "scenes").glob("*.json")}
    new = sorted(after - before)
    if rc != 0 or len(new) != 1:
        raise Failed(f"new 실패(rc={rc}) {out[:200]}")
    sid = new[0][:-len(".json")]
    try:
        def plan(d):
            d.update(purpose="셀프테스트", action_beat="정면 응시", emotion="긴장",
                     visual_style="셀 셰이딩")
            d["dialogue"][0]["text"] = "테스트 대사"
        edit_json(b.scene_path(sid), plan)

        if stage in ("PROMPT", "REVIEW", "APPROVED"):
            anchor_c, anchor_l = b.anchors()
            gp = b.root / f"_prompt_{sid}.txt"
            gp.write_text(f"SCENE_PROMPT: medium shot, {anchor_c}, {anchor_l}, cel shading\n"
                          "NEGATIVE_PROMPT: text\nCONTINUITY_NOTES: -\n"
                          "DIALOGUE_PLACEMENT: bottom\n", encoding="utf-8")
            rc, out = b.run(ADV, "set-prompt", sid, "--file", str(gp))
            gp.unlink(missing_ok=True)
            if rc != 0:
                raise Failed(f"set-prompt 실패(rc={rc}) {out[:200]}")

        if stage in ("REVIEW", "APPROVED"):
            srcs = []
            for i in range(images):
                q = b.root / f"_cand_{sid}_{i}.png"
                write_png(q, 1400, 1000, (150 + i * 20, 190, 230))
                srcs.append(str(q))
            rc, out = b.run(ADV, "add-images", sid, *srcs)
            for q in srcs:
                Path(q).unlink(missing_ok=True)
            if rc != 0:
                raise Failed(f"add-images 실패(rc={rc}) {out[:200]}")

        if stage == "APPROVED":
            rc1, o1 = b.run(ADV, "select", sid, "1")
            rc2, o2 = b.run(ADV, "approve", sid)
            if rc1 != 0 or rc2 != 0:
                raise Failed(f"select/approve 실패({rc1}/{rc2}) {(o1 + o2)[:200]}")
        yield sid
    finally:
        with contextlib.suppress(OSError):
            b.scene_path(sid).unlink()
        shutil.rmtree(b.root / "images" / "raw" / sid, ignore_errors=True)


# ============================================================ meta (자가진단 자신)
@test("meta", "T01 필수 모듈은 전부 존재·적재되고, SKIP 으로 되돌아가지 않는다")
def t01(b: Box):
    """커버리지 공백을 조용하게 만드는 세 경로를 동시에 막는다.

    (1) 파일이 사라지거나 import 가 깨져도 '없으니 SKIP' 으로 넘어가는 것,
    (2) 이관이 끝난 모듈을 optional=True 로 되돌려 놓는 것,
    (3) **새 도구가 목록 밖에서 태어나는 것** — 적재조차 되지 않으면 그 파일이 받는 검사는
        구문 오류 확인(T02)뿐이다. 실제로 doctor(507줄)가 그 상태로 오래 있었다.
    """
    absent = [n for n in REQUIRED_MODULES if not b.p(f"tools/{n}.py").exists()]
    eq(absent, [], "필수 모듈 파일 누락")
    uncovered = sorted(n for n in tool_names(b)
                       if n not in REQUIRED_MODULES and n not in NOT_IMPORTED)
    eq(uncovered, [], "REQUIRED_MODULES 밖의 도구 — 목록에 넣거나 NOT_IMPORTED 에 이유를 남긴다")
    for n in REQUIRED_MODULES:
        ok(b.mod(n) is not None, f"{n} 적재 결과가 비어 있음")   # 적재 실패는 mod() 가 FAIL
    src = b.p("tools/selftest.py").read_text(encoding="utf-8")
    soft = set(re.findall(r'mod\(\s*"([A-Za-z_]+)"\s*,\s*optional\s*=\s*True', src))
    eq(sorted(soft & set(REQUIRED_MODULES)), [], "확실히 있는 모듈이 optional SKIP 으로 되돌아감")


@test("meta", "T02 tools/*.py 전부 구문 오류 없음(동시 편집 회귀 조기 검출)")
def t02(b: Box):
    files = sorted((b.root / "tools").glob("*.py"))
    ok(len(files) >= 15, f"도구 파일이 {len(files)}개뿐 — 패키지가 잘렸습니다")
    bad = []
    for p in files:
        try:
            compile(p.read_text(encoding="utf-8"), p.name, "exec")
        except SyntaxError as e:
            bad.append(f"{p.name}:{e.lineno} {e.msg}")
        except (OSError, ValueError) as e:
            bad.append(f"{p.name}: {type(e).__name__}: {e}")
    eq(bad, [], "구문 오류")


# ============================================================ arch (계층 불변식)
# 계층 규약은 지금까지 주석으로만 있었다 — 어기는 코드가 자가진단 전체를 그대로 통과했다.
# 여기서부터는 ast 로 소스를 읽어 기계가 판정한다(JS 쪽 J01·J03 과 같은 방식).
_AST_CACHE: dict[str, ast.Module] = {}


def tool_names(b: Box) -> list[str]:
    """tools/ 안의 파이썬 모듈 이름(자기 자신 제외)."""
    return sorted(p.stem for p in (b.root / "tools").glob("*.py") if p.stem != "selftest")


def tool_ast(b: Box, name: str) -> ast.Module:
    if name not in _AST_CACHE:
        _AST_CACHE[name] = ast.parse(b.p(f"tools/{name}.py").read_text(encoding="utf-8"),
                                     f"{name}.py")
    return _AST_CACHE[name]


def _import_sites(tree: ast.Module) -> dict[int, str]:
    """import 노드 id → '모듈 수준' | '함수 본문' | 'CLI 진입점'.

    바깥쪽 함수까지 따라 올라가 판정한다 — main() 안에 정의된 중첩 함수의 import 도
    'CLI 진입점' 이다(그 함수는 main 을 통해서만 도달한다).
    """
    sites: dict[int, str] = {}

    def visit(node, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                sites[id(child)] = ("모듈 수준" if not stack
                                    else "CLI 진입점" if stack[0] in CLI_ENTRY else "함수 본문")
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, stack + [child.name])
            else:
                visit(child, stack)

    visit(tree, [])
    return sites


def tool_imports(b: Box, name: str) -> dict[str, str]:
    """{불러온 도구 모듈: '모듈 수준'|'함수 본문'|'CLI 진입점'} — 지연 import 도 놓치지 않는다.

    지연 import 는 순환을 '동작하게' 만들 뿐 의존 방향을 되돌리지는 못한다. 계층 검사에서
    빼 두면 규약이 함수 본문으로 숨는다 — 그래서 같은 무게로 센다. 예외는 그 도구의 CLI
    진입점(main)뿐이다: 라이브러리로 import 될 때는 실행되지 않아 고리를 만들 수 없다.
    """
    tools = set(tool_names(b))
    tree = tool_ast(b, name)
    sites = _import_sites(tree)
    rank = {"모듈 수준": 0, "함수 본문": 1, "CLI 진입점": 2}
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [(node.module or "").split(".")[0]] if not node.level else []
        else:
            continue
        how = sites.get(id(node), "모듈 수준")
        for m in mods:
            cur = out.get(m)
            if m in tools and m != name and (cur is None or rank[how] < rank[cur]):
                out[m] = how       # 같은 모듈을 여러 번 부르면 '가장 이른 자리'가 이긴다
    return out


def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """방향 그래프의 고리 목록(노드 이름 순환 경로). 같은 고리가 여러 번 나올 수 있다."""
    cycles: list[list[str]] = []
    state: dict[str, int] = {}

    def walk(node: str, path: list[str]) -> None:
        state[node] = 1
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                cycles.append(path[path.index(nxt):] + [nxt] if nxt in path else [node, nxt])
            elif state.get(nxt, 0) == 0:
                walk(nxt, path + [nxt])
        state[node] = 2

    for m in sorted(graph):
        if state.get(m, 0) == 0:
            walk(m, [m])
    return cycles


def func_body(b: Box, mod: str, name: str) -> list:
    for node in ast.walk(tool_ast(b, mod)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return list(node.body)
    return []


def func_calls(b: Box, mod: str, name: str) -> set[str]:
    """함수가 **실제로 부르는** 이름들(`scene_ops.update_fields` 처럼 점 표기 그대로).

    원문 문자열 검색과 달리 독스트링·주석은 세지 않는다 — "예전에는 adv.save 로 썼다"
    같은 설명이 검사에 걸리면 안 된다.
    """
    out: set[str] = set()
    for node in ast.walk(tool_ast(b, mod)):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            parts, f = [], sub.func
            while isinstance(f, ast.Attribute):
                parts.append(f.attr)
                f = f.value
            if isinstance(f, ast.Name):
                parts.append(f.id)
            if parts:
                out.add(".".join(reversed(parts)))
    return out


def _status_writes(b: Box, name: str) -> list[tuple[int, Any]]:
    """장면 dict 의 status 에 쓰는 자리 → [(줄번호, 상수값 또는 None)].

    ``sc["status"] = ...`` 뿐 아니라 튜플 대입과 ``.update({"status": ...})`` 우회까지 본다.
    """
    out: list[tuple[int, Any]] = []

    def const(v):
        return v.value if isinstance(v, ast.Constant) else None

    for node in ast.walk(tool_ast(b, name)):
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Tuple):
                tgts = node.targets[0].elts
                vals = (list(node.value.elts) if isinstance(node.value, ast.Tuple)
                        and len(node.value.elts) == len(tgts) else [None] * len(tgts))
            else:
                tgts, vals = list(node.targets), [node.value] * len(node.targets)
            for t, v in zip(tgts, vals):
                if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and t.slice.value == "status"):
                    out.append((node.lineno, const(v) if v is not None else None))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "update":
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    for k, v in zip(arg.keys, arg.values):
                        if isinstance(k, ast.Constant) and k.value == "status":
                            out.append((node.lineno, const(v)))
            for kw in node.keywords:
                if kw.arg == "status":
                    out.append((node.lineno, const(kw.value)))
    return out


@test("arch", "L01 계층 방향 — 모든 도구가 층을 갖고, 아래층은 위층을 import 하지 않는다")
def l01(b: Box):
    """선언만 있고 강제가 없던 규약(vn_core ← scene_ops ← advance_scene ← webapp)을 잠근다.

    scene_ops 가 advance_scene 을 부르는 순간(과거 상태) 이 검사가 떨어진다 — 지연 import
    로 숨겨도 마찬가지다. webapp 은 아무도 import 하지 않는다(서버가 라이브러리가 되면
    라우트·인증·로깅이 CLI 에 딸려 들어온다).

    **층 미부여도 실패다.** 새 모듈이 LAYER 밖에 있으면 그 모듈의 방향은 아무 검사도 받지
    않는다(고리가 되어야만 L02 에 걸린다) — 커버리지 공백이 조용히 늘어나던 자리다.
    """
    names = tool_names(b)
    unlayered = sorted(m for m in names if m not in LAYER and m not in UNLAYERED)
    eq(unlayered, [], "계층 미부여 — selftest.LAYER 에 위치를 적거나 UNLAYERED 에 이유를 남긴다")
    bad: list[str] = []
    for m in names:
        imports = tool_imports(b, m)
        if m == "vn_core":
            bad += [f"vn_core → {t} ({how}) — 기반 모듈은 표준 라이브러리만 쓴다"
                    for t, how in sorted(imports.items())]
            continue
        if "webapp" in imports and m != "webapp":
            bad.append(f"{m} → webapp ({imports['webapp']}) — 최상위 서버를 아래에서 부른다")
        if m not in LAYER:
            continue
        for t, how in sorted(imports.items()):
            if how == "CLI 진입점":      # 그 도구를 직접 실행한 사람 — 라이브러리 경로가 아니다
                continue
            if t in LAYER and LAYER[t] >= LAYER[m]:
                bad.append(f"{m}(계층 {LAYER[m]}) → {t}(계층 {LAYER[t]}) ({how})")
    eq(sorted(set(bad)), [], "계층 위반")


@test("arch", "L02 순환 import — 모듈 수준 0 · 지연 고리는 문서화된 한 쌍만")
def l02(b: Box):
    """모든 변이 모듈 수준인 고리는 import 순서에 따라 그 자리에서 ImportError 를 내고
    스튜디오가 뜨지 않는다 — 무조건 실패다.

    한 변이 함수 본문 지연 import 인 고리도 이제 센다. 예전에는 그것이 통째로 예외였고
    (local_llm ↔ prompt_build 하위호환 통로), 그 예외 아래에서 새 고리가 얼마든지 생길 수
    있었다. 그 통로가 사라진 지금은 **LAZY_CYCLE_OK 에 적힌 한 쌍만** 허용한다.
    (CLI 진입점 안의 import 는 그래프에 넣지 않는다 — import 만으로는 실행되지 않는다.)
    """
    imports = {m: tool_imports(b, m) for m in tool_names(b)}
    hard = {m: [t for t, how in d.items() if how == "모듈 수준"] for m, d in imports.items()}
    eq(sorted({" → ".join(c) for c in _find_cycles(hard)}), [], "모듈 수준 순환")

    lazy = {m: [t for t, how in d.items() if how in ("모듈 수준", "함수 본문")]
            for m, d in imports.items()}
    unknown = {" → ".join(c) for c in _find_cycles(lazy)
               if frozenset(c) not in LAZY_CYCLE_OK}
    eq(sorted(unknown), [], "문서화되지 않은 지연 import 고리(설계라면 LAZY_CYCLE_OK 에 이유와 함께)")


@test("arch", "L03 장면 status — 승인 게이트가 걸린 상태는 scene_ops 만 쓴다")
def l03(b: Box):
    """status 를 밖에서 찍을 수 있으면 '사람이 승인한다'는 규약이 대입 한 줄로 우회된다.

    새 장면을 만들며 초기 상태(SCENE_PLAN·PROMPT)를 넣는 것은 전이가 아니라 작성이라
    허용한다 — 그 자리에는 아직 승인할 것이 없다. 그 밖의 값(IMAGE·REVIEW_HUMAN·
    REVISE·APPROVED)과 '값을 알 수 없는 대입'은 scene_ops 밖에서 전부 금지다.
    """
    bad = []
    for m in tool_names(b):
        if m == "scene_ops":
            continue
        for line, value in _status_writes(b, m):
            if value in AUTHORING_STATES:
                continue
            shown = repr(value) if value is not None else "값이 상수가 아님"
            bad.append(f"{m}.py:{line} status ← {shown}")
    eq(sorted(bad), [], "scene_ops 밖의 장면 상태 대입")


@test("arch", "L04 webapp 에 모델 프롬프트 문자열 0 — 조립은 prompt_build·vn_compose 담당")
def l04(b: Box):
    """webapp.py 머리말이 선언한 규약("모델에 보내는 프롬프트 문자열은 이 파일에 한 줄도
    없다")을 기계로 확인한다. 프롬프트가 라우트로 새면 같은 문구가 두 벌이 되고, 조용히
    갈린 쪽이 사용자 화면에 나온다."""
    bad = []
    for node in ast.walk(tool_ast(b, "webapp")):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if not {"role", "content"} <= keys:
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant) and k.value == "content"
                    and isinstance(v, ast.Constant) and str(v.value).strip()):
                bad.append(f"webapp.py:{node.lineno} {str(v.value)[:60]!r}")
    eq(bad, [], "webapp 이 모델 메시지 문자열을 직접 들고 있음")
    src = b.p("tools/webapp.py").read_text(encoding="utf-8")
    for marker in ("SCENES_JSON_ONLY", "[말투 규칙]", "NEGATIVE_PROMPT:", "1인칭으로"):
        eq(src.count(marker), 0, f"프롬프트 조각 {marker!r} 이 webapp 으로 복사됨")


@test("arch", "L05 vn_core 단일 출처 — 훑기·선택본·완성 판정을 소비자가 다시 만들지 않는다")
def l05(b: Box):
    """같은 규칙이 모듈마다 한 벌씩 있으면 주석으로만 동기화된다(엔딩 이름·화 번호가 실제로
    화면마다 갈렸던 사고). 이름을 이어 주는 별칭(`ending_of = vn_core.ending_of`)은 허용하고,
    **자체 구현**(def · 리터럴 재정의)만 떨어뜨린다.

    iter_scenes·selected_of·is_deliverable 이 여기 있는 이유: '어떤 컷이 완성본인가' 를
    export_viewer·print_export·print_preflight·prompt_build·makefun_client·webapp 이 각자
    판정하던 자리다. 조건 하나만 어긋나면 감상본에는 있는데 인화 목록에는 없는 컷이 생긴다.
    """
    vc = b.mod("vn_core")
    want = ("ending_of", "norm_episode", "CROP_ANCHORS",
            "iter_scenes", "selected_of", "is_deliverable")
    arrived = [n for n in want if hasattr(vc, n)]
    dups = []
    for m in tool_names(b):
        if m == "vn_core":
            continue
        for node in tool_ast(b, m).body:          # 최상위 정의만 본다
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in arrived:
                    dups.append(f"{m}.py:{node.lineno} def {node.name}")
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if not isinstance(t, ast.Name):
                        continue
                    if t.id.lstrip("_") in arrived and isinstance(
                            node.value, (ast.Tuple, ast.List, ast.Set, ast.Dict, ast.Lambda)):
                        dups.append(f"{m}.py:{node.lineno} {t.id} = (자체 정의)")
    eq(sorted(dups), [], "vn_core 와 같은 규칙의 두 번째 구현")
    for m in ("scene_ops", "vn_compose"):        # 별칭이 같은 값을 가리키는지(런타임 확인)
        mod = b.mod(m)
        for n in arrived:
            if hasattr(mod, n) and not callable(getattr(mod, n)):
                eq(getattr(mod, n), getattr(vc, n), f"{m}.{n} 값이 vn_core 와 다름")
    missing = [n for n in want if n not in arrived]
    if missing:
        raise Gap(f"vn_core 에 아직 없음: {', '.join(missing)} — 통합 대기(도착하면 자동 잠금)")


# ------------------------------------------------------------ 문서 판독(SCHEMA.md)
_TICK = re.compile(r"`([^`]+)`")


def doc_text(b: Box) -> str:
    p = b.p("docs/SCHEMA.md")
    if not p.exists():
        raise Failed("docs/SCHEMA.md 가 없습니다 — 스키마 문서가 사라졌습니다")
    return p.read_text(encoding="utf-8")


def doc_names(cell: str) -> set[str]:
    """표 칸(또는 문장) 안의 `백틱` 이름들."""
    return {n.strip() for n in _TICK.findall(cell) if n.strip()}


def doc_section(text: str, head: str) -> str:
    """그 제목으로 시작하는 절의 본문(다음 같은 깊이 제목 전까지). 없으면 실패."""
    if head not in text:
        raise Failed(f"SCHEMA.md 에서 {head!r} 절을 찾지 못했습니다"
                     " — 문서 구조를 바꿨다면 이 검사의 앵커도 함께 고치세요")
    body = text.split(head, 1)[1]
    depth = head.split(" ", 1)[0]           # "###" 처럼 우물정자 깊이
    cut = re.search(rf"^{re.escape(depth)} ", body, re.M)
    return body[:cut.start()] if cut else body


def doc_line(text: str, needle: str) -> str:
    """그 문구가 든 첫 줄. 없으면 실패(문서 구조가 바뀐 것)."""
    for line in text.splitlines():
        if needle in line:
            return line
    raise Failed(f"SCHEMA.md 에서 {needle!r} 줄을 찾지 못했습니다"
                 " — 문서 구조를 바꿨다면 이 검사의 앵커도 함께 고치세요")


def doc_field_row(text: str, *needles: str) -> set[str]:
    """표에서 조건에 맞는 줄을 찾아, **이름이 가장 많이 든 칸**의 백틱 이름 집합을 준다.

    한 줄을 통째로 훑으면 설명 칸의 `scene_ops` 같은 이름까지 섞인다 — 목록이 든 칸만 고른다.
    (칸 안의 이스케이프된 파이프 `\\|` 는 칸 구분자가 아니라 열거 기호다 — 먼저 지운다.)
    """
    for line in text.splitlines():
        if line.lstrip().startswith("|") and all(n in line for n in needles):
            return max((doc_names(c) for c in line.replace("\\|", " ").split("|")),
                       key=len, default=set())
    raise Failed("SCHEMA.md 에서 표 줄을 찾지 못했습니다: " + " · ".join(needles)
                 + " — 문서 구조를 바꿨다면 이 검사의 앵커도 함께 고치세요")


def a2_required_keys(b: Box) -> list[str]:
    """check_protocol 이 실제로 요구하는 A2 필수 키 목록(소스에서 읽는다)."""
    for node in ast.walk(tool_ast(b, "check_protocol")):
        if not isinstance(node, ast.For) or not isinstance(node.iter, (ast.Tuple, ast.List)):
            continue
        elts = node.iter.elts
        keys = [e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if len(keys) != len(elts) or not keys:
            continue
        said = " ".join(str(c.value) for c in ast.walk(node)
                        if isinstance(c, ast.Constant) and isinstance(c.value, str))
        if "필수 키 없음" in said:
            return keys
    raise Failed("check_protocol 에서 A2 필수 키 목록을 찾지 못했습니다(구조가 바뀌었습니다)")


# 사람이 읽는 표면과, 이름과 뜻이 갈린 것을 아는 유일한 자리(SCHEMA §2.3).
_FACING = ("tools/studio.html", "tools/studio.js", "templates/scene-brief.md",
           "templates/prompt-frames-ko.md")
_RETIRED = ("그록", "Grok", "grok.com", "grok-input", "XAI_API_KEY")


@test("arch", "L09 은퇴한 공급자 이름은 사람이 읽는 표면으로 돌아오지 않는다 · 레거시 키는 설명된다")
def l09(b: Box):
    """이 사이클은 공급자 하나를 이름까지 내렸지만, **필드 이름 하나는 남겼다** —
    `prompt.grok_output`. 검사기(`tools/check_protocol.py`)가 수정 금지 상태로 그 키를
    이름으로 읽기 때문이고(A6), 바꾸면 승인된 장면이 전부 FAIL 이 된다.

    그래서 두 방향을 함께 지킨다. ① 화면·틀 문서에는 은퇴한 이름이 다시 나타나지 않는다
    (이름이 남아 있으면 사람은 그 경로가 아직 있는 줄 안다). ② 남은 키가 **왜** 남았는지는
    SCHEMA §2.3 에 적혀 있어야 한다 — 설명이 없으면 다음 사이클이 그 줄을 살아 있는
    의존으로 읽고 이름을 고치려다 교착한다. 유출 탐지기(A8·secret_scan)의 `xai-` 패턴은
    공급자 연동이 아니라 **탐지기**이므로 이 검사의 대상이 아니다.
    """
    for rel in _FACING:
        p = b.p(rel)
        if not p.exists():
            raise Failed(f"{rel} 이 없습니다 — 이름을 바꿨다면 이 검사도 함께 고치세요")
        text = p.read_text(encoding="utf-8")
        # 파비콘 base64 안의 우연한 'XAI' 같은 것까지 잡지 않게 줄 단위로 본다.
        for i, line in enumerate(text.splitlines(), 1):
            if "base64," in line:
                continue
            for name in _RETIRED:
                ok(name not in line, f"{rel}:{i} 에 은퇴한 이름 '{name}' 이 있다 — {line.strip()[:90]}")
    doc = doc_text(b)
    row = doc_field_row(doc, "`grok_output`", "scene_ops.set_prompt")
    ok(row, "SCHEMA §2.3 에 grok_output 줄이 없다")
    has(doc, "레거시 이름", "grok_output 이 왜 그 이름인지 SCHEMA 가 설명하지 않는다")
    has(doc, "check_protocol.py", "레거시 설명이 근거(수정 금지 검사기)를 대지 않는다")
    has(doc, "이미지 프롬프트", "사람이 부르는 이름(이미지 프롬프트)이 SCHEMA 에 없다")


@test("arch", "L06 문서↔코드 상수 동기화 — SCHEMA.md 가 코드를 복제한 자리를 기계가 지킨다")
def l06(b: Box):
    """SCHEMA.md 는 코드 상수 열 몇 개를 산문으로 복제한다(편집 가능 필드·보호 필드·A2 필수
    키·카메라 표준 어휘). 지금까지 그것을 지켜 주는 기계가 없어서, 코드를 고치면 문서가 조용히
    거짓말을 시작했다 — 사용자는 문서대로 손으로 고치고 검사기 FAIL 을 만난다.

    문서를 파싱해 집합으로 비교한다. 목록을 늘릴 때 **코드를 먼저 고치고 표를 맞추면** 통과다.
    """
    doc = doc_text(b)
    so = b.mod("scene_ops")
    vc = b.mod("vn_core")
    sl = b.mod("scene_lint")

    # (1) §2.1 편집 가능 / 도구 전용 — scene_ops 의 두 상수가 정본이다
    editable = doc_field_row(doc, "편집 가능")
    missing = sorted(f for f in so.EDITABLE_FIELDS if f not in editable)
    eq(missing, [], "EDITABLE_FIELDS 인데 SCHEMA §2.1 '편집 가능' 표에 없는 필드")
    protected = doc_field_row(doc, "PROTECTED_FIELDS") - {"PROTECTED_FIELDS"}
    eq(sorted(protected), sorted(so.PROTECTED_FIELDS), "SCHEMA §2.1 '도구 전용' 목록 ≠ PROTECTED_FIELDS")

    # (2) §2.4 A2 필수 키 — 검사기 소스가 정본이다
    said = re.search(r"A2 가 키 존재를 요구하는[^)]*\)", doc, re.S)
    ok(said is not None, "SCHEMA §2.4 의 'A2 가 키 존재를 요구하는 …' 문장을 찾지 못함")
    eq(sorted(doc_names(said.group(0))), sorted(a2_required_keys(b)),
       "SCHEMA §2.4 의 A2 필수 키 목록 ≠ check_protocol 이 실제로 요구하는 키")

    # (3) §2.2 카메라 표준 어휘 — scene_lint 가 정본이다
    block = re.search(r"```[^\n]*\n(\s*shot\s*:.*?)```", doc, re.S)
    ok(block is not None, "SCHEMA §2.2 의 카메라 표준 어휘 코드블록을 찾지 못함")
    cam = re.search(r"shot\s*:(.*?)angle\s*:(.*)", block.group(1), re.S)
    ok(cam is not None, "코드블록에서 shot/angle 목록을 가르지 못함")
    for label, raw, std in (("shot", cam.group(1), sl.STD_SHOTS), ("angle", cam.group(2), sl.STD_ANGLES)):
        listed = sorted(w.strip() for w in raw.replace("\n", " ").split("/") if w.strip())
        eq(listed, sorted(std), f"SCHEMA §2.2 의 camera.{label} 표준 어휘 ≠ scene_lint.STD_{label.upper()}S")

    # (3b) §2.3 거리 태그 — prompt_build.SHOT_DISTANCE 가 정본이다
    #      표만 고치고 코드를 두면(또는 반대면) '넓게 찍으라' 는 지시가 조용히 빈말이 된다.
    dist_row = doc_line(doc, "prompt_build.SHOT_DISTANCE")
    for shot, cue in b.mod("prompt_build").SHOT_DISTANCE.items():
        has(dist_row, f"`{shot}`", f"SCHEMA §2.3 거리 태그 표에 샷 {shot!r} 가 없음")
        has(dist_row, f"`{cue}`", f"SCHEMA §2.3 거리 태그 표에 태그 {cue!r} 가 없음")

    # (4) §2.6 자산 — 확장자 목록과 task 보존 개수
    exts = {n for n in doc_names(doc_line(doc, "허용 확장자")) if n.startswith(".")}
    eq(sorted(exts), sorted(vc.IMAGE_EXTS), "SCHEMA §2.6 허용 확장자 ≠ vn_core.IMAGE_EXTS")
    kept = re.search(r"\*{0,2}(\d+)\s*개\*{0,2}\s*까지 보관", doc_line(doc, "까지 보관하고"))
    ok(kept is not None, "SCHEMA §2.6 의 makefun_tasks 보존 개수 문장을 찾지 못함")
    eq(int(kept.group(1)), int(so.GEN_TASKS_MAX), "SCHEMA §2.6 보존 개수 ≠ scene_ops.GEN_TASKS_MAX")

    # (5) §2.7 검수 값 · §2.8 인화 크롭 — 열거를 손대면 문서와 코드 중 한쪽만 바뀐다
    eq(sorted(doc_names(doc_line(doc, "허용 값:"))), sorted(checker_const(b, "REVIEW_STATES")),
       "SCHEMA §2.7 허용 값 ≠ check_protocol.REVIEW_STATES")
    eq(sorted(doc_field_row(doc, "crop_anchor") - {"crop_anchor"}), sorted(vc.CROP_ANCHORS),
       "SCHEMA §2.8 crop_anchor 열거 ≠ vn_core.CROP_ANCHORS")
    eq(sorted(doc_field_row(doc, "crop_mode") - {"crop_mode"}), sorted(vc.CROP_MODES),
       "SCHEMA §2.8 crop_mode 열거 ≠ vn_core.CROP_MODES")

    # (5b) §3.1 사적 데이터 패턴 — vn_core.PRIVATE_PATTERNS 가 정본이고, **세 곳이** 같은
    #      넷을 말해야 한다: 코드 · SCHEMA · .gitignore. 한 곳만 늘면 그 차이는 '사적 대화가
    #      클라우드로 복사됐다' 로만 드러나고, 드러났을 때는 이미 올라간 뒤다.
    has(doc, "vn_core.PRIVATE_PATTERNS", "SCHEMA §3.1 이 사적 데이터 패턴의 코드 정본을 가리키지 않음")
    ignored = (SRC / ".gitignore").read_text(encoding="utf-8")
    for pat in vc.PRIVATE_PATTERNS:
        has(doc, f"`{pat}`", f"SCHEMA §3.1 에 사적 데이터 패턴 {pat!r} 가 없음")
        ok(any(line.strip() == pat for line in ignored.splitlines()),
           f".gitignore 가 사적 데이터 패턴 {pat!r} 를 제외하지 않음")

    # (6) 나머지 산문 복제 — id 형식과 상태 열거는 이름이 문서에 그대로 있어야 한다
    has(doc, vc.SCENE_ID_RE.pattern, "SCENE_ID_RE 정규식이 문서와 다름")
    absent = [s for s in checker_const(b, "SCENE_STATES") if s not in doc]
    eq(absent, [], "check_protocol.SCENE_STATES 에 있는데 SCHEMA 가 설명하지 않는 상태")


def checker_const(b: Box, name: str) -> list[str]:
    """check_protocol 의 최상위 문자열 열거 상수(소스에서 읽는다 — import 하지 않는다).

    검사기는 도구가 고칠 수 없는 판정자라 자가진단도 그 파일을 실행하지 않고 읽기만 한다.
    """
    for node in tool_ast(b, "check_protocol").body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                return [e.value for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    raise Failed(f"check_protocol.{name} 을 찾지 못했습니다(구조가 바뀌었습니다)")


@test("arch", "L07 호감도 눈금 — 재생 엔진 폴백이 템플릿 기본값과 같다(엔딩이 갈리지 않게)")
def l07(b: Box):
    """분기 판정의 눈금(최대·시작 호감도)이 파이썬과 JS 에서 갈리면 **린터가 통과시킨 분기가
    재생에서는 다른 엔딩으로 간다.** 파이썬 쪽(vn_compose·scene_lint)은 templates/manifest.json
    의 dating 을 정본으로 읽는데, 재생 엔진은 JS 라 그 파일을 읽을 수 없어 폴백 리터럴을 갖는다.
    그 리터럴이 정본과 같은지 여기서 대조한다 — 두 값이 갈리는 순간 실패한다.
    """
    tpl = json.loads(b.p("templates/manifest.json").read_text(encoding="utf-8"))
    dating = tpl.get("dating")
    if not isinstance(dating, dict):
        raise Gap("templates/manifest.json 에 dating 이 없다 — 눈금 정본이 사라졌다")
    js = b.p("tools/vn_runtime.js").read_text(encoding="utf-8")
    m = re.search(r"AFF_MAX_FALLBACK\s*=\s*(\d+)\s*,\s*AFF_START_FALLBACK\s*=\s*(\d+)", js)
    if not m:
        raise Gap("vn_runtime.js 에서 호감도 폴백 상수를 찾지 못했습니다(이름이 바뀌었습니다)")
    eq(int(m.group(1)), int(dating.get("max", -1)),
       "엔진의 최대 호감도 폴백 ≠ templates/manifest.json 의 dating.max")
    eq(int(m.group(2)), int(dating.get("start_affection", -1)),
       "엔진의 시작 호감도 폴백 ≠ templates/manifest.json 의 dating.start_affection")
    # 리터럴이 다시 흩어지지 않게: 엔진 안에 다른 30/100 판정이 남아 있지 않은지
    ok(js.count("AFF_MAX_FALLBACK") >= 2 and js.count("AFF_START_FALLBACK") >= 2,
       "폴백 상수가 선언만 되고 쓰이지 않습니다(리터럴이 따로 남아 있을 수 있습니다)")


@test("arch", "L08 검사기 호출에 타임아웃·stdin 차단 — 잠금을 쥔 채 매달리지 않는다")
def l08(b: Box):
    """run_checker 는 거의 항상 전역 WRITE_LOCK 안에서 돈다. 검사기가 입력을 기다리거나
    멈추면 잠금이 영원히 안 풀려 스튜디오의 모든 쓰기가 함께 멈춘다 — 서버 재시작 말고는
    빠져나올 길이 없다. 멈춘 검사기는 죽이고 FAIL 로 돌려주는 편이 정직하다.
    """
    vc = b.mod("vn_core")
    body = func_body(b, "vn_core", "run_checker")
    if not body:
        raise Failed("vn_core.run_checker 가 없습니다")
    # func_body 는 AST 노드 목록이다 — 문자열 검사를 하려면 다시 소스로 편다
    # (독스트링도 함께 펴지므로, 설명이 아니라 실제 호출인지는 아래 인자 이름으로 가른다)
    src = "\n".join(ast.unparse(n) for n in body)
    ok("timeout=" in src, "run_checker 의 subprocess 호출에 timeout 이 없습니다")
    ok("DEVNULL" in src, "run_checker 가 stdin 을 막지 않습니다(입력 대기로 매달릴 수 있습니다)")
    ok("TimeoutExpired" in src, "타임아웃을 잡아 사용자에게 알리지 않습니다")
    ok(isinstance(getattr(vc, "CHECKER_TIMEOUT", None), int) and vc.CHECKER_TIMEOUT > 0,
       "CHECKER_TIMEOUT 상수가 없습니다")


# ============================================================ pipeline (CLI)
@test("pipeline", "P01 매니페스트 없으면 RED(exit 1) + 시작 안내")
def p01(b: Box):
    with hidden(b.p("project/manifest.json")):
        rc, out = b.checker()
    eq(rc, 1, "exit code")
    has(out, "manifest", "안내 문구")


@test("pipeline", "P02 데모 상태는 GREEN + A8 키스캔 PASS")
def p02(b: Box):
    rc, out = b.checker()
    eq(rc, 0, f"exit code — {out[:400]}")
    has(out, "[A8] PASS", "키 스캔")


@test("pipeline", "P03 set-prompt(--file) → 상태 PROMPT + 앵커 검사 통과")
def p03(b: Box):
    with cli_scene(b, "PLAN") as sid:
        anchor_c, anchor_l = b.anchors()
        gp = b.root / "prompt_out.txt"
        gp.write_text(f"SCENE_PROMPT: medium shot, {anchor_c}, {anchor_l}, cel shading\n"
                      "NEGATIVE_PROMPT: text\n", encoding="utf-8")
        rc, out = b.run(ADV, "set-prompt", sid, "--file", str(gp))
        gp.unlink(missing_ok=True)
        eq(rc, 0, f"rc — {out[:200]}")
        eq(b.scene(sid)["status"], "PROMPT", "status")
        hasnt(out, "FAIL", "자동 검사")


@test("pipeline", "P04 add-images → 자동검사 PASS → IMAGE 에 머문다(고르기 전에는 검사기도 초록)")
def p04(b: Box):
    """등록만으로 REVIEW_HUMAN 을 찍으면 그 순간부터 A3 가 selected_image 를 요구해
    **렌더 직후~사람이 고르기 전** 저장소가 자기 게이트에 FAIL 한다. 등록은 IMAGE 까지다."""
    with cli_scene(b, "PROMPT") as sid:
        a, c = b.root / "cand_a.png", b.root / "cand_b.png"
        write_png(a, 1400, 1000)
        write_png(c, 1400, 1000, (150, 190, 230))
        rc, out = b.run(ADV, "add-images", sid, str(a), str(c))
        a.unlink(missing_ok=True)
        c.unlink(missing_ok=True)
        st = b.scene(sid)
        eq(rc, 0, f"rc — {out[:200]}")
        eq(st["status"], "IMAGE", "status")
        eq(st["review"]["auto"], "PASS", "review.auto")
        eq(st["assets"]["selected_image"], "", "고르지도 않았는데 선택본이 생김")
        eq(len(st["assets"]["raw_images"]), 2, "후보 수")
        hasnt(out, "REVIEW_HUMAN", "등록 안내가 시사 단계로 올라갔다고 말함")
        rc_all, out_all = b.checker()
        eq(rc_all, 0, f"후보만 있고 선택이 없는 중간 상태에서 저장소 전체 검사가 FAIL — {out_all[:400]}")


@test("pipeline", "P05 select → approve → APPROVED + human PASS")
def p05(b: Box):
    with cli_scene(b, "REVIEW") as sid:
        rc1, o1 = b.run(ADV, "select", sid, "2")
        rc2, o2 = b.run(ADV, "approve", sid)
        st = b.scene(sid)
        eq(rc1, 0, f"select rc — {o1[:200]}")
        eq(rc2, 0, f"approve rc — {o2[:200]}")
        eq(st["status"], "APPROVED", "status")
        eq(st["review"]["human"], "PASS", "review.human")


@test("pipeline", "P06 저해상도 선택은 approve 가 거부하고 롤백")
def p06(b: Box):
    with cli_scene(b, "REVIEW") as sid:
        small = b.root / "small.png"
        write_png(small, 500, 400)
        b.run(ADV, "revise", sid, "IMAGE", "--note", "저해상도 테스트")
        b.run(ADV, "add-images", sid, str(small))
        b.run(ADV, "select", sid, small.name)
        rc, out = b.run(ADV, "approve", sid)
        small.unlink(missing_ok=True)
        ok(rc != 0, "저해상도인데 승인됨")
        ok(b.scene(sid)["status"] != "APPROVED", "롤백되지 않음")
        # 정상 후보로 다시 선택하면 승인된다
        b.run(ADV, "select", sid, "1")
        rc2, out2 = b.run(ADV, "approve", sid)
        eq(rc2, 0, f"재승인 rc — {out2[:200]}")


@test("pipeline", "P07 다른 장면 고장이 --scene 단위검사에 전염되지 않음")
def p07(b: Box):
    with cli_scene(b, "APPROVED") as sid:
        s1 = b.scene_path("SCENE-001")
        broken = read_json(s1)
        broken.setdefault("dialogue", []).append(
            {"speaker_id": "CHAR-999", "text": "x", "placement": "top"})
        with replaced_text(s1, json.dumps(broken, ensure_ascii=False, indent=2)):
            rc_all, _ = b.checker()
            rc_one, out_one = b.checker("--scene", sid)
        eq(rc_all, 1, "전체 검사")
        eq(rc_one, 0, f"단위 검사 — {out_one[:300]}")


@test("pipeline", "P08 오케스트레이터가 local 이 아니면 원격 API 가 아니라 직접 입력으로 안내한다")
def p08(b: Box):
    """원격 오케스트레이터 경로는 은퇴했다. 예전 매니페스트(mode:"api")를 그대로 쓰는
    프로젝트가 남아 있으므로, 그 경우 **사람이 실제로 쓸 수 있는 경로 이름**이 나와야 한다 —
    조용히 NameError 가 나면 웹에서는 그것이 본문 없는 500 이 된다."""
    vc = b.mod("vn_compose")
    err = getattr(vc, "VNError", RuntimeError)
    with manifest_patch(b, lambda d: d.setdefault("orchestrator", {}).update({"mode": "api"})):
        exc = raises(lambda: vc.orch_chat([{"role": "user", "content": "hi"}]), err, "mode=api")
        has(str(exc), "직접 입력", "무엇을 쓰면 되는지")


@test("pipeline", "P09 잘못된 인자는 크래시 대신 usage 안내")
def p09(b: Box):
    rc, out = b.run(ADV, "revise", "SCENE-001", "WRONG_STATE")
    eq(rc, 2, f"rc — {out[:200]}")
    hasnt(out, "Traceback", "traceback")
    has(out.lower(), "usage", "usage")


@test("pipeline", "P10 비표준 scene_id(new abc) 거부 — order 무결성 보호")
def p10(b: Box):
    rc, out = b.run(ADV, "new", "abc")
    eq(rc, 2, f"rc — {out[:200]}")
    hasnt(out, "Traceback", "traceback")
    ok(not b.p("project/scenes/abc.json").exists(), "abc.json 이 생성됨")


@test("pipeline", "P11 revise IMAGE → 즉시 approve 거부(오래된 이미지 재승인 차단)")
def p11(b: Box):
    with cli_scene(b, "APPROVED") as sid:
        b.run(ADV, "revise", sid, "IMAGE", "--note", "regen")
        eq(b.scene(sid)["assets"]["selected_image"], "", "선택본이 비워지지 않음")
        rc, out = b.run(ADV, "approve", sid)
        ok(rc != 0, "선택본 없이 승인됨")
        ok(b.scene(sid)["status"] != "APPROVED", "status")
        hasnt(out, "Traceback", "traceback")


@test("pipeline", "P12 add-images 부분 실패 시 고아 파일 없음(원자성)")
def p12(b: Box):
    with cli_scene(b, "PROMPT") as sid:
        good = b.root / "g1.png"
        write_png(good, 1400, 1000)
        rc, out = b.run(ADV, "add-images", sid, str(good), str(b.root / "NOPE.png"))
        good.unlink(missing_ok=True)
        folder = b.root / "images" / "raw" / sid
        orphans = list(folder.glob("*")) if folder.exists() else []
        eq(rc, 2, f"rc — {out[:200]}")
        hasnt(out, "Traceback", "traceback")
        eq(len(orphans), 0, f"고아 파일 {[o.name for o in orphans]}")


@test("pipeline", "P13 select 위첨자('²') 인자 → 크래시 대신 안내")
def p13(b: Box):
    with cli_scene(b, "REVIEW", images=1) as sid:
        rc, out = b.run(ADV, "select", sid, "²")
        eq(rc, 2, f"rc — {out[:200]}")
        hasnt(out, "Traceback", "traceback")


@test("pipeline", "P14 장면 파일이 JSON 배열이어도 status 가 크래시하지 않음")
def p14(b: Box):
    with fresh_scene(b) as sid, corrupted(b.scene_path(sid)):
        rc, out = b.run(ADV, "status")
        eq(rc, 2, f"rc — {out[:200]}")
        hasnt(out, "Traceback", "traceback")


@test("pipeline", "P15 CLI set-prompt·add-images 도 APPROVED 를 거부(승인 게이트 우회 차단)")
def p15(b: Box):
    with cli_scene(b, "APPROVED") as sid:
        before = b.scene(sid)
        gp = b.root / "late.txt"
        gp.write_text("SCENE_PROMPT: 몰래 바꾼 프롬프트\n", encoding="utf-8")
        rc_sp, out_sp = b.run(ADV, "set-prompt", sid, "--file", str(gp))
        gp.unlink(missing_ok=True)
        extra = b.root / "late.png"
        write_png(extra, 1400, 1000, (10, 20, 30))
        rc_ai, out_ai = b.run(ADV, "add-images", sid, str(extra))
        extra.unlink(missing_ok=True)
        after = b.scene(sid)
        ok(rc_sp != 0, f"set-prompt 가 APPROVED 장면을 덮어씀 — {out_sp[:200]}")
        ok(rc_ai != 0, f"add-images 가 APPROVED 장면을 바꿈 — {out_ai[:200]}")
        eq(after["status"], "APPROVED", "status 가 되돌려짐")
        eq(after["prompt"]["grok_output"], before["prompt"]["grok_output"], "프롬프트 변조")
        eq(after["assets"]["raw_images"], before["assets"]["raw_images"], "후보 목록 변조")


@test("pipeline", "P16 scene_id 형식 통일 — 세 자리 미만(new SCENE-1)도 거부")
def p16(b: Box):
    """SCENE-1 은 웹(vn_core.is_scene_id)에서는 400 인데 CLI 로는 만들어졌다.

    형식이 갈리면 그 장면은 웹 편집·이미지 생성·진행표에서 통째로 사라진다(W20 의 짝).
    """
    stray = b.p("project/scenes/SCENE-1.json")
    rc, out = b.run(ADV, "new", "SCENE-1")
    made = stray.exists()
    if made:                       # 다른 테스트의 출발점을 오염시키지 않는다
        stray.unlink()
    hasnt(out, "Traceback", "traceback")
    if rc == 0:
        raise Gap("advance_scene 이 아직 SCENE-1 을 만든다 — vn_core.is_scene_id(3자리 이상)로 통일 대기")
    eq(rc, 2, f"rc — {out[:200]}")
    ok(not made, "거부했는데 파일은 생성됨")
    rc2, out2 = b.run(ADV, "new", "SCENE-042")     # 정상 형식은 계속 만들어져야 한다
    b.p("project/scenes/SCENE-042.json").unlink(missing_ok=True)
    eq(rc2, 0, f"정상 형식까지 막힘 — {out2[:200]}")


@test("pipeline", "P17 doctor --json — 진단 구조를 내고, 읽기 전용이고, 문제를 실제로 잡는다")
def p17(b: Box):
    """doctor 는 README·start_studio.ps1·복구 런북이 여섯 곳에서 안내하는 1차 진단 도구인데
    지금까지 구문 검사 외 커버리지가 0이었다. 크래시하면 사용자는 '왜 안 되지?' 를 좁힐
    첫 수단을 잃는다.

    로컬 LLM·ComfyUI 주소는 죽은 포트로 고정한다 — 이 PC 에 모델이 떠 있든 말든 결과가 같아야
    한다. (유료 API 는 호출하지 않는다: doctor 는 토큰이 '있는지'만 본다.)
    """
    env = dict(b.env)
    env["LOCAL_LLM_URL"] = "http://127.0.0.1:59997/v1"
    env["COMFYUI_URL"] = DEAD_COMFY
    before = _tree_sums(b.root)
    rc, out = b.run("tools/doctor.py", "--json", env=env)
    after = _tree_sums(b.root)
    hasnt(out, "Traceback", "traceback")
    ok(rc in (0, 1), f"rc={rc} — {out[:300]}")
    ok("{" in out, f"JSON 이 없음 — {out[:300]}")
    data, _n = json.JSONDecoder().raw_decode(out[out.index("{"):])
    ok(isinstance(data.get("errors"), int), f"errors 구조 — {str(data)[:200]}")
    ok(isinstance(data.get("warnings"), int), "warnings 구조")
    rows = data.get("results")
    ok(isinstance(rows, list) and len(rows) >= 8, f"진단 항목 {len(rows or [])}건")
    ok(all(isinstance(r, dict) and {"section", "name", "level"} <= set(r) for r in rows),
       "항목 구조(section/name/level)")
    eq(sorted({r["level"] for r in rows} - {"OK", "경고", "문제"}), [], "알 수 없는 판정값")
    eq(data["errors"], sum(1 for r in rows if r["level"] == "문제"), "errors 집계가 항목과 다름")
    eq(after, before, "doctor 가 project/·images/ 를 건드림(진단은 읽기 전용이어야 한다)")
    # 떨어뜨리는 능력 — 매니페스트가 없으면 '문제' 로 보고하고 exit 1
    with hidden(b.p("project/manifest.json")):
        rc2, out2 = b.run("tools/doctor.py", "--json", env=env)
    bad, _n2 = json.JSONDecoder().raw_decode(out2[out2.index("{"):])
    eq(rc2, 1, "매니페스트가 없는데 exit 0")
    ok(bad["errors"] > data["errors"],
       f"매니페스트 부재를 새 문제로 잡지 못함(기준선 {data['errors']} → {bad['errors']})")
    has(out2, "manifest", "무엇이 없는지 안내")


@test("pipeline", "P18 scene_brief — 앵커를 원문 그대로 싣고 형제 장면이 손상돼도 조립된다")
def p18(b: Box):
    """직접 입력 경로의 입구다. 여기서 앵커가 빠지면 사람이 그대로 복붙하고,
    돌아온 프롬프트는 A6 FAIL 이 된다 — 원인이 두 단계 떨어져 있어 찾기 어렵다.
    브리프는 **모델을 부르지 않는다** — 로컬 LLM 이 꺼져 있어도 이 경로는 살아 있어야 한다."""
    sb = b.mod("scene_brief")
    anchor_c, anchor_l = b.anchors()
    with fresh_scene(b) as sid:
        text = sb.build_brief(sid)
        has(text, sid, "장면 id")
        has(text, anchor_c, "인물 앵커 원문")
        has(text, anchor_l, "장소 앵커 원문")
        hasnt(text, "그록", "사람이 읽는 브리프에 은퇴한 공급자 이름")
        hasnt(text, "Grok", "사람이 읽는 브리프에 은퇴한 공급자 이름")
        with fresh_scene(b) as other, corrupted(b.scene_path(other)):
            text2 = sb.build_brief(sid)
        has(text2, anchor_c, "형제 장면 하나가 손상되자 앵커가 빠짐")
    raises(lambda: sb.build_brief("SCENE-404"), FileNotFoundError, "없는 장면")


@test("pipeline", "P19 상태 계약 — 등록은 IMAGE 까지, REVIEW_HUMAN 은 선택이 찍는다(중간에 게이트가 빨개지지 않는다)")
def p19(b: Box):
    """SCHEMA §2.1 의 계약을 한 장면으로 통째로 지난다.

      · 후보만 있고 선택이 없으면 `IMAGE` — **그 사이에도 check_protocol 은 PASS** 여야 한다.
        (예전에는 등록이 곧바로 REVIEW_HUMAN 을 찍어, 렌더가 끝난 순간부터 사람이 고를 때까지
         A3 가 selected_image 를 요구하며 저장소가 자기 게이트에 FAIL 했다.)
      · `IMAGE` → `REVIEW_HUMAN` 은 select 하나만 찍는다(재스캔·자동검사 PASS 는 승격이 아니다).
      · approve 는 여전히 REVIEW_HUMAN + selected_image 둘 다 요구한다.
      · 이미 고른 REVIEW_HUMAN 장면은 재스캔이 건드리지 않는다.
      · revise 는 그대로 동작한다(상태·선택본이 함께 내려간다).
    """
    so = b.mod("scene_ops")
    with cli_scene(b, "PROMPT") as sid:
        cand = b.root / f"_p19_{sid}.png"
        write_png(cand, 1400, 1000, (170, 200, 150))
        rc, out = b.run(ADV, "add-images", sid, str(cand))
        cand.unlink(missing_ok=True)
        eq(rc, 0, f"add-images rc — {out[:200]}")
        eq(b.scene(sid)["status"], "IMAGE", "등록 뒤 상태")
        rc0, out0 = b.checker()
        eq(rc0, 0, f"고르기 전 저장소 전체 검사가 FAIL — {out0[:400]}")

        reg = so.register_images(sid)                      # 다시 스캔해도 올라가지 않는다
        eq(reg["auto"], "PASS", f"재스캔 자동 검사 — {reg}")
        eq(b.scene(sid)["status"], "IMAGE", "자동 검사 PASS 가 상태를 올림(승격 조건이 아니다)")

        rc1, out1 = b.run(ADV, "approve", sid)             # 고른 것이 없으면 승인도 막힌다
        ok(rc1 != 0, "선택 없이 승인됨")
        hasnt(out1, "Traceback", "traceback")
        eq(b.scene(sid)["status"], "IMAGE", "거절된 승인이 상태를 움직임")

        rc2, out2 = b.run(ADV, "select", sid, "1")         # 선택이 승격을 찍는다
        eq(rc2, 0, f"select rc — {out2[:200]}")
        st = b.scene(sid)
        eq(st["status"], "REVIEW_HUMAN", "선택 뒤 상태")
        eq(st["review"]["auto"], "PASS", "review.auto")
        rc3, out3 = b.checker()
        eq(rc3, 0, f"선택 뒤 저장소 전체 검사 — {out3[:400]}")

        reg2 = so.register_images(sid)                     # 고른 장면은 재스캔이 그대로 둔다
        eq(reg2["count"], 1, f"재스캔 후보 수 — {reg2}")
        st2 = b.scene(sid)
        eq(st2["status"], "REVIEW_HUMAN", "이미 고른 장면을 재스캔이 되돌림")
        eq(st2["assets"]["selected_image"], st["assets"]["selected_image"], "재스캔이 선택본을 바꿈")

        rc4, out4 = b.run(ADV, "approve", sid)
        eq(rc4, 0, f"approve rc — {out4[:200]}")
        eq(b.scene(sid)["status"], "APPROVED", "승인 상태")

        rc5, out5 = b.run(ADV, "revise", sid, "IMAGE", "--note", "상태 계약 회귀")
        eq(rc5, 0, f"revise rc — {out5[:200]}")
        st3 = b.scene(sid)
        eq(st3["status"], "IMAGE", "되돌린 뒤 상태")
        eq(st3["assets"]["selected_image"], "", "되돌렸는데 선택본이 남음")
        rc6, out6 = b.checker()
        eq(rc6, 0, f"되돌린 뒤 저장소 전체 검사 — {out6[:400]}")


@test("pipeline", "P20 선택본 파일이 사라진 시사 장면 — 재스캔이 IMAGE 로 내리고 검사기는 초록을 지킨다")
def p20(b: Box):
    """불변식의 반대쪽: 'REVIEW_HUMAN 이상 ⇔ selected_image 있음'.

    선택본 파일이 사라지면 재스캔이 선택을 비운다 — 상태만 REVIEW_HUMAN 으로 남겨 두면
    그 순간부터 A3 가 FAIL 인데, 화면에는 '시사 중' 이라고 적혀 있어 고칠 곳이 보이지 않는다.
    """
    so = b.mod("scene_ops")
    with cli_scene(b, "PROMPT") as sid:
        srcs = []
        for i in range(2):
            q = b.root / f"_p20_{sid}_{i}.png"
            write_png(q, 1400, 1000, (140 + i * 30, 180, 210))
            srcs.append(str(q))
        rc, out = b.run(ADV, "add-images", sid, *srcs)
        for q in srcs:
            Path(q).unlink(missing_ok=True)
        eq(rc, 0, f"add-images rc — {out[:200]}")
        rc, out = b.run(ADV, "select", sid, "1")
        eq(rc, 0, f"select rc — {out[:200]}")
        st = b.scene(sid)
        eq(st["status"], "REVIEW_HUMAN", "선택 뒤 상태")

        (b.root / st["assets"]["selected_image"]).unlink()      # 사람이 파일을 지웠다
        reg = so.register_images(sid)
        st2 = b.scene(sid)
        eq(st2["assets"]["selected_image"], "", "사라진 파일이 선택본으로 남음")
        eq(st2["status"], "IMAGE", "선택본이 없는데 시사 단계에 머무름(A3 가 곧바로 FAIL 이다)")
        eq(reg["auto"], "PASS", f"재스캔 자동 검사 — {reg}")
        rc2, out2 = b.checker()
        eq(rc2, 0, f"선택본 유실 뒤 저장소 전체 검사 — {out2[:400]}")


# ============================================================ template (새 작품 시작)
# 지금까지 자가진단은 examples/ 만 픽스처로 썼다 — templates/ 는 **한 번도 실행되지 않았다**.
# 그래서 templates/scene.json 에 박혀 있던 print.crop_anchor 나 talk.relationship:"" 같은
# 결함이 걸릴 자리가 없었다(사용자가 새 작품을 시작할 때만 드러난다).
@contextlib.contextmanager
def template_project(b: Box):
    """templates/ 로 새 작품을 시작한 상태를 만들고, 끝나면 원래 project/ 를 그대로 되돌린다.

    사용자가 하는 그대로다 — templates/manifest.json 을 복사해 이름·앵커만 채운다.
    (선택 항목은 템플릿이 준 값 그대로 둔다. 그래야 템플릿의 기본값이 검사 대상이 된다.)
    """
    proj, stash = b.p("project"), b.p("_project.selftest-stash")
    shutil.rmtree(stash, ignore_errors=True)
    os.replace(proj, stash)
    try:
        (proj / "scenes").mkdir(parents=True)
        mf = read_json(b.p("templates/manifest.json"))
        mf["title"] = "셀프테스트 신작"
        mf["characters"][0].update(
            name="하늘", prompt_anchor="CHAR-001 anchor: short black hair, hazel eyes")
        mf["locations"][0].update(
            name="교실", prompt_anchor="LOC-001 anchor: sunlit classroom")
        write_json(proj / "manifest.json", mf)
        yield mf
    finally:
        shutil.rmtree(proj, ignore_errors=True)
        os.replace(stash, proj)


@test("template", "TPL01 templates/ 로 시작한 새 작품 — 첫 장면 생성 + 검사기 통과")
def tpl01(b: Box):
    with template_project(b):
        rc, out = b.run(ADV, "new")
        eq(rc, 0, f"첫 장면 생성 실패 — {out[:300]}")
        sc = b.scene("SCENE-001")
        eq(sc["scene_id"], "SCENE-001", "scene_id")
        eq(sc["scene_order"], 1, "scene_order")
        rc2, out2 = b.checker()
        fails = "\n".join(l for l in out2.splitlines() if "FAIL" in l)
        eq(rc2, 0, f"새 작품이 자기 검사기를 통과하지 못함 — {fails[:400]}")


@test("template", "TPL02 새 장면에 '사람이 고른 적 없는 값'이 미리 박혀 있지 않다")
def tpl02(b: Box):
    """템플릿에 선택 필드를 박아 두면 모든 새 장면이 그 값을 갖고 태어난다 — 인화 기준점을
    한 번도 고르지 않았는데 crop_anchor 가 정해져 있는 식이다. 비어 있거나 없어야 한다."""
    optional = ("print", "episode", "ending", "ending_label", "choices", "branch",
                "intimacy", "wardrobe")

    def leaked(sc: dict) -> list[str]:
        return [k for k in optional if sc.get(k) not in (None, "", [], {}, False)]

    with template_project(b):
        eq(b.run(ADV, "new")[0], 0, "첫 장면 생성 실패")
        eq(b.run(ADV, "new")[0], 0, "둘째 장면 생성 실패")
        one, two = b.scene("SCENE-001"), b.scene("SCENE-002")
        eq(leaked(one), [], "새 장면에 미리 박힌 선택 필드")
        eq(leaked(two), [], "둘째 장면에 미리 박힌 선택 필드")
        eq(str(one.get("visual_style", "")), "", "화풍은 매니페스트가 정한다(장면에 박지 않는다)")
        eq(one.get("status"), "SCENE_PLAN", "새 장면 시작 상태")
        eq(one["review"]["human"], "PENDING", "승인 도장이 미리 찍혀 있음")
        eq(one["assets"]["selected_image"], "", "선택 이미지가 미리 지정돼 있음")


@test("template", "TPL03 templates 매니페스트로도 인물 페르소나 문장이 깨지지 않는다")
def tpl03(b: Box):
    """talk.relationship 처럼 템플릿이 빈 값으로 두면 '상대는 너의 .' 같은 문장이 모델에
    간다. 새 작품의 첫 대화가 이 문장으로 시작한다 — 자동으로 걸려야 하는 자리다."""
    pb = b.mod("prompt_build")          # 페르소나 문장의 정본(전송 계층 local_llm 이 아니다)
    with template_project(b) as mf:
        sysmsg, meta = pb.persona_prompt()
    ok(isinstance(sysmsg, str) and sysmsg.strip(), "시스템 메시지가 비어 있음")
    eq(meta.get("name"), "하늘", "인물 이름")
    has(sysmsg, "하늘", "이름이 페르소나에 반영되지 않음")
    for broken in ("너의 .", "너의 ,", "너의 \n", "None", "[관계] 상대는 너의 ."):
        hasnt(sysmsg, broken, "빈 값이 그대로 문장이 됨")
    rel = str(((mf.get("talk") or {}).get("relationship") or "")).strip()
    if rel:
        has(sysmsg, rel, "매니페스트의 관계 설정이 문장에 없음")


# ============================================================ checker 부정 픽스처
def _negative(b: Box, code: str, make):
    """한 곳만 망가뜨렸을 때 지정한 검사 항목이 '새로' FAIL 나는지 차등 확인한다.

    검사기의 '통과시키는 능력'뿐 아니라 '떨어뜨리는 능력'을 잠근다.
    """
    rc0, base = b.checker()
    hasnt(base, f"[{code}] FAIL", f"기준선이 이미 {code} FAIL")
    with make():
        rc1, out = b.checker()
    has(out, f"[{code}] FAIL", f"{code} 를 잡지 못함(rc={rc1})")
    eq(rc1, 1, "고장 상태인데 exit 0")
    rc2, back = b.checker()
    eq(rc2, rc0, "픽스처가 원상 복구되지 않음")


@test("checker", "C01 A1 — 매니페스트 필수 키 누락 검출")
def c01(b: Box):
    mf = b.manifest()
    mf.pop("title", None)
    _negative(b, "A1", lambda: replaced_text(b.p("project/manifest.json"),
                                             json.dumps(mf, ensure_ascii=False, indent=2)))


@test("checker", "C02 A2 — 미등록 location_id 검출")
def c02(b: Box):
    @contextlib.contextmanager
    def make():
        with fresh_scene(b, location_id="LOC-999") as sid:
            yield sid
    _negative(b, "A2", make)


@test("checker", "C03 A4 — 등장하지 않는 화자 speaker_id 검출")
def c03(b: Box):
    @contextlib.contextmanager
    def make():
        with fresh_scene(b, dialogue=[{"speaker_id": "CHAR-999", "text": "x",
                                       "placement": "bottom"}]) as sid:
            yield sid
    _negative(b, "A4", make)


@test("checker", "C04 A5 — scene_order 불연속 검출")
def c04(b: Box):
    @contextlib.contextmanager
    def make():
        with fresh_scene(b) as sid:
            edit_json(b.scene_path(sid), lambda d: d.update(scene_order=999))
            yield sid
    _negative(b, "A5", make)


@test("checker", "C05 A6 — 프롬프트에서 앵커가 빠진 것을 검출")
def c05(b: Box):
    @contextlib.contextmanager
    def make():
        with fresh_scene(b, status="PROMPT") as sid:
            edit_json(b.scene_path(sid),
                      lambda d: d["prompt"].update(grok_output="medium shot, cel shading"))
            yield sid
    _negative(b, "A6", make)


@test("checker", "C06 A7 — REVIEW_HUMAN 인데 auto=PASS 선행이 없는 것을 검출")
def c06(b: Box):
    @contextlib.contextmanager
    def make():
        anchor_c, anchor_l = b.anchors()
        with fresh_scene(b, status="REVIEW_HUMAN") as sid:
            rel = f"images/raw/{sid}/a.png"
            write_png(b.root / rel, 1400, 1000)
            def fix(d):
                d["prompt"]["grok_output"] = f"medium shot, {anchor_c}, {anchor_l}"
                d["assets"] = {"raw_images": [rel], "selected_image": rel}
                d["review"].update(auto="PENDING", human="PENDING")
            edit_json(b.scene_path(sid), fix)
            yield sid
    _negative(b, "A7", make)


# ============================================================ webapp
@test("webapp", "W01 기동 + 상태 API(비밀값은 불리언만 · 은퇴한 키 개념은 사라졌다)", web=True)
def w01(b: Box):
    st, d = b.wapi("/api/state")
    eq(st, 200, "status")
    ok("key_set" not in d, "은퇴한 외부 API 키 개념이 상태에 남아 있음")
    eq(d.get("orch_local"), True, "orch_local")
    eq(d.get("model"), "mock-model", "model")
    ok(isinstance(d.get("mf_token"), bool), "mf_token 이 불리언이 아님")
    # 남은 비밀값은 MakeFun 토큰 하나뿐이다 — 값이 상태에 실리는지는 심어 놓고 확인한다
    # (살아 있는 서버에 유료 토큰을 넣지 않는다. 같은 함수를 이 프로세스 안에서 부른다).
    wa = b.mod("webapp")
    with env_var(wa.makefun_client.TOKEN_ENV, "PLANTED-TOKEN-VALUE"):
        rendered = json.dumps(wa.state(), ensure_ascii=False, default=str)
    hasnt(rendered, "PLANTED-TOKEN-VALUE", "상태 API 에 토큰 원문이 실림")


@test("webapp", "W02 스토리 채팅(모의 LLM 경유) + 로그 저장", web=True)
def w02(b: Box):
    st, d = b.wapi("/api/chat", {"messages": [{"role": "user", "content": "안녕"}]})
    eq(st, 200, "status")
    has(d.get("reply", ""), "모의 응답", "응답")
    ok(b.p("project/story/chatlog.json").exists(), "chatlog.json 없음")


@test("webapp", "W03 스토리라인 저장", web=True)
def w03(b: Box):
    st, _ = b.wapi("/api/storyline", {"text": "짝사랑 고백 이야기"})
    eq(st, 200, "status")
    eq(b.p("project/story/storyline.md").read_text(encoding="utf-8").strip(),
       "짝사랑 고백 이야기", "저장 내용")


def ensure_storyline(b: Box, text: str = "짝사랑 고백 이야기") -> None:
    """장면 구성의 전제 조건 — 앞 테스트가 저장해 뒀기를 기대하지 않는다."""
    p = b.p("project/story/storyline.md")
    if not p.exists() or not p.read_text(encoding="utf-8").strip():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


@test("webapp", "W04 스토리라인 → 장면 2개 자동 구성 + 검사 통과", web=True)
def w04(b: Box):
    ensure_storyline(b)
    st, d = b.wapi("/api/compose", {"count": 2, "force": True}, timeout=60)
    eq(st, 200, f"status — {json.dumps(d, ensure_ascii=False)[:200]}")
    eq(len(d.get("created", [])), 2, "생성 수")
    eq(d.get("checker_pass"), True, f"검사 — {json.dumps(d, ensure_ascii=False)[:300]}")
    ok(b.scene_path("SCENE-002").exists(), "SCENE-002 없음")


@test("webapp", "W05 웹 경로 등록→선택→승인 → APPROVED", web=True)
def w05(b: Box):
    with fresh_scene(b, status="PROMPT") as sid:
        anchor_c, anchor_l = b.anchors()
        edit_json(b.scene_path(sid), lambda d: d["prompt"].update(
            grok_output=f"medium shot, {anchor_c}, {anchor_l}, cel shading"))
        rel = f"images/raw/{sid}/web_a.png"
        write_png(b.root / rel, 1400, 1000)
        st1, d1 = b.wapi("/api/register-images", {"scene_id": sid})
        st2, d2 = b.wapi("/api/select", {"scene_id": sid, "image": rel})
        st3, d3 = b.wapi("/api/approve", {"scene_id": sid})
        sc = b.scene(sid)
        eq(st1, 200, f"register — {d1}")
        eq(st2, 200, f"select — {d2}")
        eq(st3, 200, f"approve — {d3}")
        eq(sc["status"], "APPROVED", "status")
        eq(sc["review"]["human"], "PASS", "human")
        eq(d2.get("auto_pass"), True, "select 직후 auto_pass(등록 오염 회귀)")
        eq(sc["review"]["auto"], "PASS", "review.auto")


@test("webapp", "W06 이미지 경로 탈출(/img/../) 차단", web=True)
def w06(b: Box):
    code, _h, _b = b.raw("/img/../CLAUDE.md")
    eq(code, 404, "status")


@test("webapp", "W07 적대적 문자열이 데이터로만 왕복(원문 보존)", web=True)
def w07(b: Box):
    hostile = "</textarea><img src=x onerror=alert(1)>"
    with fresh_scene(b, purpose=hostile) as sid:
        st, d = b.wapi("/api/state")
        eq(st, 200, "status")
        sc = next((x for x in d.get("scenes", []) if x.get("scene_id") == sid), None)
        ok(sc is not None, "장면이 state 에 없음")
        eq(sc["purpose"], hostile, "왕복 중 변형됨")


@test("webapp", "W08 병렬 8회 register 후에도 장면 JSON 무결(WRITE_LOCK)", web=True)
def w08(b: Box):
    with fresh_scene(b, status="PROMPT") as sid:
        rel = f"images/raw/{sid}/p.png"
        write_png(b.root / rel, 1400, 1000)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            codes = list(ex.map(lambda _: b.code("/api/register-images", {"scene_id": sid}),
                                range(8)))
        sc = b.scene(sid)
        ok(all(c == 200 for c in codes), f"응답 코드 {codes}")
        eq(sc.get("scene_id"), sid, "scene_id 손상")
        eq(sc["assets"]["raw_images"], [rel], "후보 목록 손상")


@test("webapp", "W09 외부 Host 헤더 차단(403 · DNS 리바인딩 방어)", web=True)
def w09(b: Box):
    code, _h, _b = b.raw("/api/state", headers={"Host": "evil.example.com"})
    eq(code, 403, "status")


@test("webapp", "W10 vn_compose CLI 로도 같은 구현 재사용", web=True)
def w10(b: Box):
    ensure_storyline(b)
    cenv = dict(b.env)
    cenv["NO_PROXY"] = cenv["no_proxy"] = "127.0.0.1,localhost"
    rc, out = b.run("tools/vn_compose.py", "2", "--force", env=cenv)
    eq(rc, 0, f"rc — {out[:300]}")
    ok(b.scene_path("SCENE-002").exists(), "SCENE-002 없음")


@test("webapp", "W11 수동 compose-input 지시문 생성(앵커·출력마커 포함)", web=True)
def w11(b: Box):
    anchor_c, _ = b.anchors()
    st, d = b.wapi("/api/compose-input", {"count": 3})
    eq(st, 200, "status")
    has(d.get("instruction", ""), "SCENES_JSON_ONLY", "출력 마커")
    has(d.get("instruction", ""), anchor_c, "인물 앵커")


@test("webapp", "W12 수동 compose-manual — 코드펜스 JSON 붙여넣기 → 장면 생성", web=True)
def w12(b: Box):
    anchor_c, anchor_l = b.anchors()
    items = [
        {"order": 1, "purpose": "수동도입", "action_beat": "창밖", "emotion": "긴장",
         "time": "방과 후", "location_id": "LOC-001",
         "camera": {"shot": "medium", "angle": "eye", "framing": "left", "focus": "face"},
         "dialogue": [{"speaker_id": "CHAR-001", "text": "안녕"}],
         "image_prompt": f"medium shot, {anchor_c}, {anchor_l}, cel shading"},
        {"order": 2, "purpose": "수동결심", "action_beat": "복도", "emotion": "떨림",
         "time": "방과 후", "location_id": "LOC-001",
         "camera": {"shot": "close", "angle": "low", "framing": "center", "focus": "fist"},
         "dialogue": [{"speaker_id": "CHAR-001", "text": "지금"}],
         "image_prompt": f"close-up, {anchor_c}, {anchor_l}, cel shading"},
    ]
    fenced = "```json\n" + json.dumps(items, ensure_ascii=False) + "\n```"
    st, d = b.wapi("/api/compose-manual", {"text": fenced, "force": True}, timeout=60)
    eq(st, 200, "status")
    eq(len(d.get("created", [])), 2, "생성 수")
    eq(d.get("checker_pass"), True, json.dumps(d, ensure_ascii=False)[:300])


@test("webapp", "W13 직접 입력 scene-brief + set-prompt → PROMPT + 앵커 검사 통과", web=True)
def w13(b: Box):
    anchor_c, anchor_l = b.anchors()
    with fresh_scene(b) as sid:
        st, d = b.wapi("/api/scene-brief", {"scene_id": sid})
        eq(st, 200, "status")
        has(d.get("text", ""), anchor_c, "지시문 앵커")
        ptext = f"SCENE_PROMPT: medium shot, {anchor_c}, {anchor_l}, cel shading\nNEGATIVE_PROMPT: text"
        st2, d2 = b.wapi("/api/set-prompt", {"scene_id": sid, "text": ptext})
        sc = b.scene(sid)
        eq(st2, 200, "set-prompt status")
        eq(d2.get("checker_pass"), True, f"검사 — {d2}")
        eq(sc["status"], "PROMPT", "status")
        eq(sc["prompt"]["grok_output"], ptext, "저장 내용")


@test("webapp", "W37 로컬 LLM 켜짐/꺼짐 — 자동 경로는 되거나 안내하고, 직접 입력은 어느 쪽이든 된다", web=True)
def w37(b: Box):
    """이 사이클의 계약을 한 테스트가 통째로 지난다.

    · LLM 이 있으면 ``/api/gen-prompt`` 가 프롬프트를 만든다. 모의 서버를 쓰므로 **이 PC 에
      모델이 없어도 '켜짐' 경로가 검증된다** — 지금 이 저장소의 로컬 LLM 은 실제로 꺼져 있다.
    · LLM 이 없으면 같은 라우트는 **이름을 가진 안내**로 끝나야 한다. 조용한 500·역추적이면
      사람은 무엇을 해야 할지 모른 채 멈춘다.
    · 어느 쪽이든 직접 입력(브리프 → set-prompt)은 그대로 돈다 — 브리프 조립에는 모델이
      필요 없기 때문이다. 오늘 이것이 사람이 장면을 쓸 수 있는 **유일한** 길이라,
      기능 정리 때 먼저 지워지지 않게 여기서 잠근다.
    """
    anchor_c, anchor_l = b.anchors()
    # (1) 켜짐 — 웹 서버는 모의 LLM 을 보고 있다
    with fresh_scene(b) as sid:
        st, d = b.wapi("/api/gen-prompt", {"scene_id": sid})
        eq(st, 200, f"gen-prompt(LLM 켜짐) — {str(d)[:200]}")
        sc = b.scene(sid)
        eq(sc["status"], "PROMPT", "status")
        has(sc["prompt"]["grok_output"], anchor_c, "앵커 원문")
    # (2) 꺼짐 — 같은 라우트가 이름을 가진 안내로 끝나고, 직접 입력의 입구는 열려 있다
    wa, gen = _route(b, "/api/gen-prompt", "프롬프트 생성을 웹에서 부를 수 없다")
    _wa2, brief = _route(b, "/api/scene-brief", "브리프를 웹에서 부를 수 없다")
    err = getattr(wa, "VNError", RuntimeError)
    with fresh_scene(b) as sid, env_var("LOCAL_LLM_URL", "http://127.0.0.1:59999/v1"):
        exc = raises(lambda: gen({"scene_id": sid}), err, "LLM 꺼짐")
        has(str(exc), "로컬 LLM", "무엇이 없는지 말하지 않는다")
        text = brief({"scene_id": sid})["text"]     # 모델 없이 조립된다
        has(text, anchor_c, "브리프 앵커 — 여기가 빠지면 두 단계 뒤 A6 FAIL 이 된다")
        st2, d2 = b.wapi("/api/set-prompt", {"scene_id": sid,
                         "text": f"SCENE_PROMPT: medium shot, {anchor_c}, {anchor_l}, cel shading"})
        eq(st2, 200, f"set-prompt — {d2}")
        eq(b.scene(sid)["status"], "PROMPT", "직접 입력만으로 PROMPT 에 닿지 못한다")


@test("webapp", "W14 빈 프롬프트 set-prompt → 400 거부", web=True)
def w14(b: Box):
    with fresh_scene(b) as sid:
        eq(b.code("/api/set-prompt", {"scene_id": sid, "text": "   "}), 400, "status")


@test("webapp", "W15 없는 scene_id register → 400 + 서버 생존(SystemExit 미전파)", web=True)
def w15(b: Box):
    eq(b.code("/api/register-images", {"scene_id": "SCENE-404"}), 400, "status")
    eq(b.code("/api/state"), 200, "서버 생존")


@test("webapp", "W16 APPROVED 재스캔 잠금(불변식 보호)", web=True)
def w16(b: Box):
    with cli_scene(b, "APPROVED") as sid:
        st, d = b.wapi("/api/register-images", {"scene_id": sid})
        sc = b.scene(sid)
        eq(st, 200, f"status — {d}")
        eq(d.get("locked"), True, "locked")
        eq(sc["status"], "APPROVED", "status")
        eq(sc["review"]["auto"], "PASS", "auto")
        ok(bool(sc["assets"]["selected_image"]), "선택본이 지워짐")


@test("webapp", "W17 POST 라우터 가드(없는 경로 404 · 비-dict 본문 400)", web=True)
def w17(b: Box):
    eq(b.code("/api/does-not-exist", {}), 404, "없는 경로")
    code, _h, _b = b.raw("/api/check", data=b"[1,2]",
                         headers={"Content-Type": "application/json"})
    eq(code, 400, "비-dict 본문")


@test("webapp", "W18 손상 장면 → state 는 스킵하고 생존 · die 경로는 400(절단 아님)", web=True)
def w18(b: Box):
    with fresh_scene(b) as sid, corrupted(b.scene_path(sid)):
        st, d = b.wapi("/api/state")
        eq(st, 200, "state status")
        ok(all(s.get("scene_id") != sid for s in d.get("scenes", [])), "손상 장면이 목록에 남음")
        eq(b.code("/api/preflight", {"scene_id": sid}), 400, "die 경로가 400 이 아님(연결 절단?)")


@test("webapp", "W19 폰 이미지 업로드(base64) + 자동등록 · 잘못된 확장자 400", web=True)
def w19(b: Box):
    with fresh_scene(b, status="PROMPT") as sid:
        src = b.root / "up_src.png"
        write_png(src, 1400, 1000)
        data = base64.b64encode(src.read_bytes()).decode("ascii")
        src.unlink(missing_ok=True)
        st, d = b.wapi("/api/upload-image", {"scene_id": sid, "filename": "phone.png",
                                             "data_b64": "data:image/png;base64," + data})
        eq(st, 200, f"status — {d}")
        ok(d.get("count", 0) >= 1, "등록 수")
        ok((b.root / "images" / "raw" / sid / "phone.png").exists(), "파일 미저장")
        eq(b.code("/api/upload-image",
                  {"scene_id": sid, "filename": "x.exe", "data_b64": data}), 400, "확장자 거부")


@test("webapp", "W20 scene_id 정규식 검증 — 경로 탈출·변형 전부 400", web=True)
def w20(b: Box):
    codes = {bad: b.code("/api/register-images", {"scene_id": bad})
             for bad in ("../../templates/scene", "SCENE-001/../x", "scene-001", "SCENE-1")}
    ok(all(c == 400 for c in codes.values()), f"코드 {codes}")


@test("webapp", "W21 즐겨찾기(인화 후보) 저장·해제 + state 반영", web=True)
def w21(b: Box):
    with fresh_scene(b) as sid:
        st, d = b.wapi("/api/favorite", {"scene_id": sid, "on": True})
        _, state = b.wapi("/api/state")
        _, d2 = b.wapi("/api/favorite", {"scene_id": sid, "on": False})
        eq(st, 200, "status")
        ok(sid in d.get("scene_ids", []), "저장 응답")
        ok(sid in state.get("favorites", []), "state 반영")
        ok(sid not in d2.get("scene_ids", []), "해제")


@test("webapp", "W22 /img ETag 발급 + If-None-Match 재요청 304(폰 데이터 절약)", web=True)
def w22(b: Box):
    with fresh_scene(b) as sid:
        write_png(b.root / "images" / "raw" / sid / "etag.png", 1400, 1000)
        code, hd, body = b.raw(f"/img/raw/{sid}/etag.png")
        eq(code, 200, "첫 요청")
        etag = hd.get("ETag", "")
        ok(bool(etag) and len(body) > 0, f"ETag={etag!r} len={len(body)}")
        code2, _h2, _b2 = b.raw(f"/img/raw/{sid}/etag.png", headers={"If-None-Match": etag})
        eq(code2, 304, "재요청")


@test("webapp", "W23 CSRF — 교차 출처 POST 403 · 출처 없는 요청 200", web=True)
def w23(b: Box):
    code, _h, _b = b.raw("/api/state", data=b"{}",
                         headers={"Content-Type": "application/json",
                                  "Origin": "http://evil.example"})
    eq(code, 403, "교차 출처")
    eq(b.code("/api/state"), 200, "출처 없는 요청(CLI·자가진단)")


@test("webapp", "W24 APPROVED 장면 선택 잠금(웹 400 · CLI 비정상 종료 · 선택본 불변)", web=True)
def w24(b: Box):
    with cli_scene(b, "APPROVED") as sid:
        sel = b.scene(sid)["assets"]["selected_image"]
        other = next(r for r in b.scene(sid)["assets"]["raw_images"] if r != sel)
        code_web = b.code("/api/select", {"scene_id": sid, "image": other})
        rc_cli, out_cli = b.run(ADV, "select", sid, "2")
        after = b.scene(sid)["assets"]["selected_image"]
        eq(code_web, 400, "웹 select")
        ok(rc_cli != 0, f"CLI select 가 성공함 — {out_cli[:200]}")
        eq(after, sel, "선택본이 바뀜")


@test("webapp", "W25 연출 리듬 린터(런 감지 + /api/lint)", web=True)
def w25(b: Box):
    slm = b.mod("scene_lint")
    eq(slm._runs(["a", "a", "a", "b", "c"]), [("a", 0, 3)], "런 감지")
    st, d = b.wapi("/api/lint", {})
    eq(st, 200, "status")
    ok(isinstance(d.get("findings"), list), "findings")
    has(json.dumps(d, ensure_ascii=False), "summary", "summary")


@test("webapp", "W26 /studio/<name>.js 정적 라우트 — 파일과 동일·ETag/304·화이트리스트 밖 차단", web=True)
def w26(b: Box):
    """스튜디오와 감상본이 **같은 재생 엔진**을 쓰는지 확인하는 지점.

    스튜디오는 이 라우트로, 감상본은 인라인으로 같은 tools/vn_runtime.js 를 쓴다(J04 의 짝).
    tools/ 아래를 여는 라우트라 화이트리스트·경로 탈출 차단이 함께 잠겨야 한다.
    """
    rt = b.p("tools/vn_runtime.js")
    code, hd, body = b.raw("/studio/vn_runtime.js")
    if code != 200:
        if not rt.exists():
            raise Gap("tools/vn_runtime.js · GET /studio/<name>.js 아직 없음 — 공용 런타임 이관 대기")
        raise Failed(f"런타임 파일은 있는데 라우트가 {code} 를 돌려줍니다")
    ok(rt.exists(), "라우트는 응답하는데 tools/vn_runtime.js 가 없음(무엇을 서빙하는가?)")
    eq(body.replace(b"\r\n", b"\n"), rt.read_bytes().replace(b"\r\n", b"\n"),
       "스튜디오가 받는 런타임이 파일과 다름(감상본과 엔진이 갈림)")
    has(hd.get("Content-Type", "").lower(), "javascript", "MIME")
    tag = (hd.get("ETag") or "").strip()
    ok(bool(tag), "ETag 없음(폰에서 매번 재전송)")
    has(hd.get("Cache-Control", ""), "max-age", "Cache-Control")
    code2, _h2, _b2 = b.raw("/studio/vn_runtime.js", headers={"If-None-Match": tag})
    eq(code2, 304, "If-None-Match 재요청")
    for bad in ("/studio/../webapp.py", "/studio/..%2fwebapp.py", "/studio/webapp.py",
                "/studio/studio.html", "/studio/", "/studio/vn_runtime.js.bak"):
        c, _h, bd = b.raw(bad)
        ok(c in (400, 403, 404), f"{bad} → {c} (화이트리스트 밖이 열림)")
        # 카나리아는 **지금도 webapp.py 안에만 있는** 문자열이어야 한다. 예전 needle 은
        # 은퇴한 키 이름이었고, 그것이 파일에서 사라지자 이 단언은 영원히 참이 됐다 —
        # 진짜 소스 유출이 생겨도 초록으로 지나간다.
        hasnt(bd.decode("utf-8", "replace"), "POST_ROUTES", f"{bad} 응답에 서버 소스가 실림")


@test("webapp", "W27 스튜디오 CSP — 인라인 스크립트를 파일로 뺐다면 script-src 'unsafe-inline' 제거", web=True)
def w27(b: Box):
    code, hd, _body = b.raw("/")
    eq(code, 200, "스튜디오 페이지")
    csp = hd.get("Content-Security-Policy", "")
    ok(bool(csp), "CSP 헤더 없음")
    for token in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'"):
        has(csp, token, "CSP 기본")
    for d in ("script-src", "connect-src", "default-src"):
        hasnt(csp_directive(csp, d), "*", f"{d} 와일드카드")
    inline = _scripts(b.p("tools/studio.html").read_text(encoding="utf-8"))
    if inline:
        raise Gap(f"studio.html 에 인라인 <script> {len(inline)}개 — 파일로 빼기 전이라 "
                  "script-src 'unsafe-inline' 을 아직 뗄 수 없다")
    hasnt(csp_directive(csp, "script-src"), "unsafe-inline",
          "인라인 스크립트가 없는데 예외가 남아 있음")


@test("webapp", "W28 /api/set-scene — 화이트리스트만 병합 · 보호 필드 400 · APPROVED 400", web=True)
def w28(b: Box):
    with fresh_scene(b) as sid:
        before = b.scene(sid)
        fields = {
            "purpose": "수정된 목적", "emotion": "설렘", "time": "노을",
            "camera": {"shot": "close-up", "angle": "low", "framing": "center", "focus": "눈"},
            "episode": 2, "ending": True, "ending_label": "호감 엔딩",
            "print": {"crop_anchor": "top"},
            "choices": [{"text": "같이 걷는다", "affection": 1, "goto": sid}],
        }
        st, d = b.wapi("/api/set-scene", {"scene_id": sid, "fields": fields})
        if st == 404:
            raise Gap("POST /api/set-scene 아직 없음 — 장면 편집 라우트 대기")
        eq(st, 200, f"status — {json.dumps(d, ensure_ascii=False)[:200]}")
        sc = b.scene(sid)
        eq(sc["purpose"], "수정된 목적", "purpose 병합")
        eq(sc["emotion"], "설렘", "emotion 병합")
        eq(sc["camera"]["shot"], "close-up", "camera 병합")
        eq(sc.get("episode"), 2, "episode")
        eq(bool(sc.get("ending")), True, "ending")
        eq(sc.get("ending_label"), "호감 엔딩", "ending_label")
        eq((sc.get("print") or {}).get("crop_anchor"), "top", "print.crop_anchor")
        ok(len(sc.get("choices") or []) == 1, f"choices {sc.get('choices')}")
        eq(sc.get("action_beat"), before.get("action_beat"), "손대지 않은 필드가 지워짐")
        # 승인 게이트·추적성의 뼈대는 이 경로로 못 바꾼다(조용히 무시가 아니라 거부)
        keep = b.scene(sid)
        for bad in ({"status": "APPROVED"}, {"review": {"human": "PASS"}},
                    {"assets": {"selected_image": "images/raw/x.png"}},
                    {"scene_id": "SCENE-999"}, {"scene_order": 99},
                    {"purpose": "정상 필드에 섞어 보냄", "status": "APPROVED"},
                    {"정체불명": 1}):
            eq(b.code("/api/set-scene", {"scene_id": sid, "fields": bad}), 400,
               f"보호/미지 필드가 통과: {sorted(bad)}")
        eq(b.code("/api/set-scene", {"scene_id": "SCENE-404", "fields": {"purpose": "x"}}),
           400, "없는 장면")
        eq(b.code("/api/set-scene", {"scene_id": sid, "fields": "문자열"}), 400, "비-dict fields")
        eq(b.scene(sid), keep, "거부됐는데 파일이 바뀜")
        eq(b.code("/api/state"), 200, "서버 생존")
    with cli_scene(b, "APPROVED") as sid2:
        keep2 = b.scene(sid2)
        eq(b.code("/api/set-scene", {"scene_id": sid2, "fields": {"purpose": "몰래 수정"}}),
           400, "APPROVED 편집이 400 이 아님")
        eq(b.scene(sid2), keep2, "APPROVED 장면이 편집됨")


@test("webapp", "W29 ending_label 이 /api/state 와 스튜디오 엔딩 카드까지 이어진다", web=True)
def w29(b: Box):
    with fresh_scene(b, ending=True, ending_label="호감 엔딩") as sid:
        st, d = b.wapi("/api/state")
        eq(st, 200, "status")
        sc = next((x for x in d.get("scenes", []) if x.get("scene_id") == sid), None)
        ok(sc is not None, "장면이 state 에 없음")
        eq(bool(sc.get("ending")), True, "ending")
        if "ending_label" not in sc:
            raise Gap("/api/state 장면 항목에 ending_label 이 아직 없음 — 스튜디오가 엔딩 이름을 못 받는다")
        eq(sc["ending_label"], "호감 엔딩", "ending_label")
    html = b.p("tools/studio.html").read_text(encoding="utf-8")
    if "ending_label" not in html:
        raise Gap("studio.html 이 아직 ending_label 을 쓰지 않음 — 엔딩 카드 표기가 감상본과 갈린다")


@test("webapp", "W30 vn_compose.build_scene 이 ending_label 을 장면으로 옮긴다")
def w30(b: Box):
    vc = b.mod("vn_compose")
    args = (["CHAR-001"], {"LOC-001"}, [{"location_id": "LOC-001"}])
    item = {"order": 7, "purpose": "결말", "action_beat": "손을 잡는다", "emotion": "설렘",
            "time": "노을", "location_id": "LOC-001",
            "camera": {"shot": "medium", "angle": "eye", "framing": "center", "focus": "얼굴"},
            "dialogue": [{"speaker_id": "CHAR-001", "text": "고마워."}],
            "image_prompt": "medium shot", "ending": True, "ending_label": "호감 엔딩"}
    sc = vc.build_scene(item, 7, *args, episode=0)      # episode=0 → 디스크를 보지 않는다
    eq(sc["scene_id"], "SCENE-007", "scene_id 규칙")
    eq(bool(sc.get("ending")), True, "ending")
    if not sc.get("ending_label"):
        raise Gap("vn_compose.build_scene 이 ending_label 을 아직 옮기지 않음 — 엔딩 카드가 이름을 잃는다")
    eq(sc["ending_label"], "호감 엔딩", "ending_label")
    plain = vc.build_scene({**item, "ending": False, "ending_label": ""}, 8, *args, episode=0)
    ok(not plain.get("ending") and not plain.get("ending_label"), "엔딩이 아닌 장면에 라벨이 남음")


@test("webapp", "W31 /api/set-crop — 장면 쓰기는 scene_ops 한 곳으로(두 번째 쓰기 경로 없음)", web=True)
def w31(b: Box):
    """이 라우트는 예전에 adv.load/save 로 장면 파일을 직접 고쳐 썼다. 그러면 값 검증도
    APPROVED 가드도 없는 두 번째 쓰기 경로가 생긴다 — 승인 도장을 찍은 장면의 인화 설정이
    이 경로로만 바뀌는 상태였다.

    구현이 '거부'든 'scene_ops 안의 명시적 예외'든, 잠그는 것은 하나다:
    **webapp 이 직접 쓰지 않는다.** 그 위에서 승인 장면의 결과를 그대로 고정한다.
    """
    if not func_body(b, "webapp", "r_set_crop"):
        raise Gap("webapp.r_set_crop 이 없음 — /api/set-crop 경로가 사라졌거나 이름이 바뀌었다")
    calls = func_calls(b, "webapp", "r_set_crop")
    ok(any(c.startswith("scene_ops.") for c in calls),
       f"크롭 저장이 scene_ops 를 거치지 않음 — 부르는 것: {sorted(calls)}")
    for direct in ("adv.save", "adv.load", "atomic_write_json", "vn_core.atomic_write_json"):
        ok(direct not in calls, f"webapp 이 장면 파일을 직접 씀({direct}) — 두 번째 쓰기 경로")

    with fresh_scene(b) as sid:
        st, d = b.wapi("/api/set-crop", {"scene_id": sid, "anchor": "top"})
        eq(st, 200, f"정상 저장 — {json.dumps(d, ensure_ascii=False)[:200]}")
        eq((b.scene(sid).get("print") or {}).get("crop_anchor"), "top", "저장 값")
        eq(b.scene(sid)["status"], "SCENE_PLAN", "크롭 저장이 장면 상태를 움직임")
        keep = b.scene(sid)
        eq(b.code("/api/set-crop", {"scene_id": sid, "anchor": "옆으로"}), 400,
           "허용되지 않는 기준점이 통과")
        eq(b.scene(sid), keep, "거부됐는데 파일이 바뀜")
    eq(b.code("/api/set-crop", {"scene_id": "../etc", "anchor": "top"}), 400, "장면 ID 형식 검증")
    eq(b.code("/api/set-crop", {"scene_id": "SCENE-404", "anchor": "top"}), 400, "없는 장면")

    with cli_scene(b, "APPROVED") as sid2:
        before = b.scene(sid2)
        st2, d2 = b.wapi("/api/set-crop", {"scene_id": sid2, "anchor": "bottom"})
        after = b.scene(sid2)
        if st2 == 200:
            # 허용이 설계라면 그것은 scene_ops 안의 **명시적** 예외여야 한다(웹의 우회가 아니라).
            so = b.mod("scene_ops")
            ok(any("crop" in n for n in dir(so) if not n.startswith("_")),
               "승인 장면의 크롭이 바뀌는데 scene_ops 에 그 예외를 담당하는 API 가 없음")
            eq((after.get("print") or {}).get("crop_anchor"), "bottom", "허용했는데 저장되지 않음")
            eq(after["status"], "APPROVED", "status")
            eq(after["review"], before["review"], "승인 기록이 함께 바뀜")
        else:
            eq(st2, 400, f"거부는 400 이어야 한다 — {json.dumps(d2, ensure_ascii=False)[:200]}")
            eq(after, before, "거부됐는데 승인 장면이 바뀜")


def _route(b: Box, path: str, what: str):
    """POST 라우트 하나를 꺼낸다 — 아직 없으면 GAP(있는데 틀리면 그 자리에서 FAIL)."""
    wa = b.mod("webapp")
    routes = getattr(wa, "POST_ROUTES", {})
    fn = routes.get(path)
    if fn is None:
        raise Gap(f"{path} 라우트가 아직 없음 — {what}")
    return wa, fn


def _settle(wa, sid: str, secs: float = 3.0) -> str:
    """백그라운드 작업이 끝날 때까지 기다렸다가 마지막 진행 문구를 돌려준다.

    라우트가 동기든 백그라운드든 같은 검사가 통하게 하는 자리다(sync 지원 여부를 강요하지 않는다).
    """
    deadline = time.monotonic() + secs
    while time.monotonic() < deadline:
        st = wa.gen_jobs.status(sid)
        if not st.get("running"):
            return str(st.get("message", ""))
        time.sleep(0.02)
    return str(wa.gen_jobs.status(sid).get("message", ""))


@test("webapp", "W32 /api/upscale — 유료 경로가 gen_jobs 관문을 지난다(중복 과금 차단)")
def w32(b: Box):
    """확대는 **유료**다. 생성과 같은 관문(gen_jobs.claim)을 지나지 않으면 폰·PC·CLI 가
    같은 장면을 동시에 눌렀을 때 그대로 두 번 결제된다.

    MakeFun 은 부르지 않는다 — makefun_client.upscale_scene 을 통째로 대역으로 갈아끼우고
    **라우트의 관문 동작만** 본다(네트워크 0회).
    """
    wa, route = _route(b, "/api/upscale", "인화용 확대를 웹에서 부를 수 없다")
    calls = func_calls(b, "webapp", route.__name__)
    ok(any(c.startswith("gen_jobs.") for c in calls),
       f"업스케일이 생성 잠금(gen_jobs)을 지나지 않음 — 부르는 것: {sorted(calls)}")
    ok(any("upscale" in c for c in calls if c.startswith("makefun_client.")),
       f"라우트가 makefun_client 의 업스케일을 부르지 않음 — {sorted(calls)}")
    ok("threading.Thread" not in calls,
       "라우트가 스레드를 직접 띄운다 — 진행 표시·잠금이 gen_jobs 밖으로 새는 두 번째 경로")

    seen: list[str] = []

    def fake(sid, **kw):
        """실제 업스케일 대신 확대본 한 장을 그 자리에 만든다(과금 0)."""
        seen.append(sid)
        out = b.root / "images" / "raw" / sid / "fake_up.png"
        write_png(out, 2400, 3600)
        return [out]

    with selected_scene(b) as sid, patched(wa.makefun_client, "upscale_scene", fake):
        # (1) 이미 그 장면을 굽고 있으면 유료 호출은 시작조차 되면 안 된다
        wa.gen_jobs.claim(sid, "생성")
        try:
            raises(lambda: route({"scene_id": sid}), RuntimeError, "생성 중인데 업스케일이 통과")
            eq(seen, [], "중복 요청인데 유료 경로가 호출됐다(이중 과금)")
        finally:
            wa.gen_jobs.release(sid)
        # (2) 정상 요청 — 확대본이 저장되고 선택본·상태는 그대로다
        before = b.scene(sid)
        route({"scene_id": sid, "sync": True})
        _settle(wa, sid)
        eq(seen, [sid], "업스케일이 호출되지 않음")
        ok((b.root / "images" / "raw" / sid / "fake_up.png").exists(), "확대본 미저장")
        after = b.scene(sid)
        eq(after["assets"]["selected_image"], before["assets"]["selected_image"],
           "웹 업스케일이 사람이 고른 선택본을 바꿈")
        eq(after["status"], before["status"], "웹 업스케일이 장면 상태를 움직임")
        eq(wa.gen_jobs.status(sid)["running"], False, "작업이 끝났는데 잠금이 남음(다음 요청이 막힌다)")
        ok(not b.p(f"logs/gen_locks/{sid}.lock").exists(), "잠금 파일이 남음")

    # (3) 승인된 컷 — 이 기능이 존재하는 이유 그 자체다(1200×1800 7장을 8×10 으로).
    #     확대는 그림을 바꾸지 않으므로 APPROVED 도 지나가야 하고, 승인 기록은 그대로여야 한다.
    seen2: list[str] = []

    def fake2(sid, **kw):
        seen2.append(sid)
        out = b.root / "images" / "raw" / sid / "fake_up.png"
        write_png(out, 2400, 3600)
        return [out]

    with selected_scene(b, approve=True) as sid2, \
            patched(wa.makefun_client, "upscale_scene", fake2):
        before2 = b.scene(sid2)
        err = ""
        try:
            route({"scene_id": sid2, "sync": True})
        except Exception as exc:                      # 동기 실행이면 여기로 온다
            err = str(exc)
        msg = _settle(wa, sid2)
        ok(seen2, f"APPROVED 장면의 업스케일이 시작조차 못 했다 — {err or msg}. "
                  f"승인 컷을 인화 규격으로 키우는 것이 이 기능의 목적이다(그림은 바뀌지 않는다).")
        ok(not err and "실패" not in msg,
           f"확대는 됐는데 실패로 끝났다 — {err or msg}. gen_jobs.run 의 register_images 가 "
           f"APPROVED 의 후보 변경을 거절한다: 업스케일 경로는 후보 등록을 "
           f"makefun_client.upscale_scene 에 맡기고 그 거절을 타면 안 된다.")
        eq(b.scene(sid2), before2, "승인 장면이 웹 업스케일로 바뀜 — 승인 게이트 위반")
        ok(not b.p(f"logs/gen_locks/{sid2}.lock").exists(), "잠금 파일이 남음")


@test("webapp", "W33 /api/credits — 읽기 전용 위임(장면 잠금을 잡지 않는다)")
def w33(b: Box):
    """크레딧 조회는 이미지 과금이 아니지만 실제 토큰을 쓰는 호출이다. 라우트는 위임만 하고,
    생성 잠금을 잡아서 다른 요청을 막지 않아야 한다.
    """
    wa, route = _route(b, "/api/credits", "남은 크레딧을 스튜디오에서 볼 수 없다")
    calls = func_calls(b, "webapp", route.__name__)
    ok(any(c.startswith("makefun_client.") for c in calls),
       f"크레딧 조회가 makefun_client 로 위임되지 않음 — {sorted(calls)}")
    ok(not any(c.startswith("gen_jobs.") for c in calls),
       f"조회가 생성 잠금을 잡는다 — 그 사이 그 장면의 생성이 막힌다: {sorted(calls)}")

    got: list[dict] = []
    reply = {"ok": True, "raw": '{"list": []}', "note": "이력 0건 — 잔액은 계정 화면에서"}

    def fake(**kw):
        got.append(dict(kw))
        return reply

    with patched(wa.makefun_client, "credits", fake):
        out = route({})                    # 장면 ID 없이도 답해야 한다
    eq(len(got), 1, "credits 가 호출되지 않음")
    ok(isinstance(out, dict), f"응답형 — {type(out).__name__}")
    for key in ("ok", "raw", "note"):
        ok(key in out, f"응답에 {key} 가 없음 — {sorted(out)}")
    eq(out["note"], reply["note"], "note 가 그대로 전달되지 않음")


@test("webapp", "W34 /api/talk-status — 로컬 LLM 주소는 scheme://host:port 만(리버스 프록시 자격증명 차단)")
def w34(b: Box):
    """LOCAL_LLM_URL 은 비밀값이 아니지만 basic-auth 리버스 프록시 뒤에 두면 user:pw@ 가 붙는 자리다.
    그 응답은 브라우저(폰 포함)로 그대로 나가므로 doctor·image_gen 과 같은 규칙으로 가린다
    (vn_core.host_port). studio.js 가 읽는 것은 up 뿐이라 화면 기능은 그대로다.
    """
    wa, route = _route(b, "/api/talk-status", "로컬 LLM 상태를 스튜디오가 볼 수 없다")
    with env_var("LOCAL_LLM_URL", "http://svc:secretpw@127.0.0.1:59995/v1"):
        out = route({})
    ok(isinstance(out, dict), f"응답형 — {type(out).__name__}")
    ok("up" in out, f"studio.js 가 읽는 up 이 없음 — {sorted(out)}")
    eq(out["up"], False, "꺼진 주소인데 up=True")
    blob = json.dumps(out, ensure_ascii=False)
    hasnt(blob, "secretpw", "프록시 비밀번호가 브라우저로 나감")
    has(str(out.get("url", "")), "127.0.0.1:59995", f"어느 주소를 두드렸는지 — {out.get('url')!r}")
    has(str(out.get("url", "")), "http://", "scheme 이 사라짐")


@test("webapp", "W35 POST 본문 상한 — 위조 Content-Length(음수·초과)를 본문 읽기 전에 400", web=True)
def w35(b: Box):
    """음수 Content-Length 를 통과시키면 아래 read(length) 가 read(-1) 이 되어, 연결이
    끊길 때까지 본문을 통째로 메모리에 읽어들이고 json 파싱까지 겹친다 — 인증도 받지 않은
    LAN 기기가 서버를 메모리 고갈(OOM)로 떨굴 수 있었다. 초과·음수 모두 **본문을 읽기 전에**
    400 으로 거절하고, 서버는 그 뒤에도 살아남아야 한다. 정상 본문은 그대로 통과한다.
    """
    wa = b.mod("webapp")
    eq(int(getattr(wa, "MAX_BODY_BYTES", 0)), 10_000_000, "본문 상한 상수(MAX_BODY_BYTES)")
    # 위조 헤더 + 작은 본문으로 관문만 친다(실제로 10MB 를 보내지 않는다). urllib 은
    # 호출부가 준 Content-Length 를 그대로 실어 보낸다 — 그래서 음수도 서버까지 도달한다.
    for cl, label in (("-1", "음수"), (str(10_000_001), "상한 초과")):
        code, _h, _b = b.raw("/api/check", data=b"{}",
                             headers={"Content-Type": "application/json",
                                      "Content-Length": cl}, timeout=10)
        eq(code, 400, f"{label} Content-Length 가 400 으로 막히지 않음")
    eq(b.raw("/api/state")[0], 200, "본문 공격 뒤 서버 생존")
    st, _d = b.wapi("/api/chat-history", {})   # 본문을 실어야 POST — 정상 요청은 그대로 통과
    eq(st, 200, "위조 헤더 없는 정상 POST 회귀")


@test("webapp", "W36 /img·/dl 경로의 널바이트·잘못된 문자 → 404(500 아님)", web=True)
def w36(b: Box):
    """safe_path 래퍼는 vn_core.safe_path 가 resolve 단계에서 던지는 ValueError(널바이트 등)·
    OSError 도 삼켜 '없는 파일'(404)로 답한다. 예전에는 이런 경로가 500(서버 오류)으로 새어
    나갔다 — 잘못된 요청 경로는 사용자 잘못이지 서버 고장이 아니다.
    """
    for path in ("/img/%00CLAUDE.md", "/dl/%00x", "/img/a%00/b.png"):
        code, _h, _b = b.raw(path)
        eq(code, 404, f"{path} 가 404 가 아님(500 누출)")
    eq(b.raw("/api/state")[0], 200, "잘못된 경로 뒤 서버 생존")


# ============================================================ PIN 인증(LAN)
@contextlib.contextmanager
def auth_state(wa, pin: str = "482913"):
    """AUTH 전역을 빈 상태로 두고 테스트가 끝나면 반드시 되돌린다.

    AUTH 의 내부 모양(IP 별 dict / 단일 카운터)은 구현 사정이라 여기서 고정하지 않는다.
    """
    import copy
    old = copy.deepcopy(wa.AUTH)
    for k, v in list(wa.AUTH.items()):
        if isinstance(v, dict):
            v.clear()
        elif isinstance(v, list):
            del v[:]
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            wa.AUTH[k] = 0
    wa.AUTH["pin"] = pin
    try:
        yield wa.AUTH
    finally:
        wa.AUTH.clear()
        wa.AUTH.update(old)


def _nargs(fn) -> int:
    import inspect
    return len(inspect.signature(fn).parameters)


def _pin(wa, pin: str, ip: str = "10.0.0.9"):
    """check_pin(pin[, ip]) — IP 별 잠금이 붙기 전 서명도 그대로 받아준다."""
    return wa.check_pin(pin, ip) if _nargs(wa.check_pin) >= 2 else wa.check_pin(pin)


def _issue(wa, ip: str = "10.0.0.9"):
    return wa._issue_token(ip) if _nargs(wa._issue_token) >= 1 else wa._issue_token()


def _tok_ok(wa, tok: str, ip: str = "10.0.0.9") -> bool:
    return wa._token_ok(tok, ip) if _nargs(wa._token_ok) >= 2 else wa._token_ok(tok)


def _until(auth: dict, ip: str = "10.0.0.9") -> float:
    u = auth.get("until")
    if isinstance(u, dict):
        return float(u.get(ip, 0) or 0)
    return float(u or 0)


def _expire_tokens(auth: dict) -> None:
    """저장된 토큰을 전부 '만료됨' 으로 만든다(내부 표현 두 가지를 모두 지원)."""
    past = time.time() - 1
    toks = auth.get("tokens")
    if isinstance(toks, dict):
        for meta in toks.values():
            if isinstance(meta, dict):
                meta["exp"] = past
    elif isinstance(toks, list):
        auth["tokens"] = [(t, past) for t, _exp in toks]


@test("auth", "A01 PIN 확인 + 연속 5회 실패 → 60초 잠금(그 기기는 정답도 막힘)")
def a01(b: Box):
    wa = b.mod("webapp")
    with auth_state(wa, "482913") as auth:
        tok = _pin(wa, "482913")
        ok(isinstance(tok, str) and len(tok) > 20, f"토큰 {tok!r}")
        for i in range(5):
            raises(lambda: _pin(wa, "000000"), RuntimeError, f"{i + 1}회차 오답")
        left = _until(auth) - time.time()
        ok(left > 30, f"잠금이 60초 규모가 아님(남은 {left:.0f}초)")
        e = raises(lambda: _pin(wa, "482913"), RuntimeError, "잠금 중 정답")
        has(str(e), "시도", "잠금 안내")
        if _nargs(wa.check_pin) >= 2:   # IP 별 잠금이면 다른 기기는 계속 쓸 수 있어야 한다
            ok(isinstance(_pin(wa, "482913", "10.0.0.77"), str), "다른 기기까지 잠김")
        u = auth.get("until")
        if isinstance(u, dict):
            u.clear()
        else:
            auth["until"] = 0
        ok(isinstance(_pin(wa, "482913"), str), "잠금 해제 후 정상 인증")


@test("auth", "A02 토큰 TTL 만료 · 위조 토큰 거부 · (지원 시) 발급 기기 고정")
def a02(b: Box):
    wa = b.mod("webapp")
    with auth_state(wa) as auth:
        tok = _pin(wa, auth["pin"])
        ok(_tok_ok(wa, tok), "발급 직후인데 무효")
        ok(not _tok_ok(wa, ""), "빈 토큰 통과")
        ok(not _tok_ok(wa, tok + "x"), "위조 토큰 통과")
        if _nargs(wa._token_ok) >= 2:
            ok(not wa._token_ok(tok, "10.9.9.9"), "다른 기기에서 토큰이 통과")
        _expire_tokens(auth)
        ok(not _tok_ok(wa, tok), "만료 토큰 통과")
        eq(len(auth["tokens"]), 0, "만료 토큰이 정리되지 않음")


@test("auth", "A03 기기 상한 · compare_digest 상수시간 비교 · PIN 미설정 거부")
def a03(b: Box):
    import inspect
    wa = b.mod("webapp")
    cap = int(getattr(wa, "AUTH_MAX_TOKENS", 20))
    with auth_state(wa) as auth:
        first = _issue(wa)
        rest = [_issue(wa) for _ in range(cap + 4)]
        eq(len(auth["tokens"]), cap, "기기 상한")
        ok(not _tok_ok(wa, first), "상한을 넘겼는데 최초 토큰이 살아 있음")
        ok(_tok_ok(wa, rest[-1]), "최신 토큰이 무효")
        for fn in (wa.check_pin, wa._token_ok):
            has(inspect.getsource(fn), "compare_digest", f"{fn.__name__} 상수시간 비교")
        auth["pin"] = ""
        raises(lambda: _pin(wa, ""), RuntimeError, "PIN 미설정인데 통과")


# ============================================================ MakeFun (모의)
class _Net:
    """스텁이 본 요청 기록 — 무엇을 어디로 보냈는지(본문·헤더까지).

    유료 API 라 '무엇이 나갔는가' 자체가 검사 대상이다(레퍼런스 장수, PUT 헤더, 읽기 전용 여부).
    """

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []   # (method, path, body)
        self.puts: list[dict] = []                     # presigned PUT 요청 전문

    def paths(self) -> list[str]:
        return [p for _m, p, _b in self.calls]

    def hits(self, needle: str) -> list[tuple[str, str, dict]]:
        return [c for c in self.calls if needle in c[1]]

    def sent(self, needle: str) -> dict:
        """그 경로로 **마지막에** 보낸 본문(없으면 {})."""
        for _m, path, body in reversed(self.calls):
            if needle in path:
                return body if isinstance(body, dict) else {}
        return {}


class _PutResp:
    """presigned PUT 의 최소 응답 — `with opener.open(...) as r:` 를 그대로 흉내낸다."""

    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _PutOpener:
    """업로드 전용 가짜 opener. handler 로 실패(예외)를 흉내낼 수 있다."""

    def __init__(self, rec: _Net, handler=None):
        self.rec, self.handler = rec, handler

    def open(self, req, timeout=None):
        self.rec.puts.append({
            "url": req.full_url, "method": req.get_method(), "data": req.data,
            "headers": {str(k).lower(): str(v) for k, v in req.header_items()}})
        if self.handler is not None:
            self.handler(req)
        return _PutResp()


class _NoNet:
    """열리면 안 되는 자리. 스텁을 우회해 진짜 소켓으로 나가는 경로가 생기면 즉시 실패시킨다."""

    def __init__(self, label: str):
        self.label = label

    def open(self, *a, **kw):
        raise Failed(f"실제 네트워크 호출 시도({self.label}) — 유료 API 는 모의로만 검증한다")


@contextlib.contextmanager
def mf_stub(mk, api, fetch=None, put=None):
    """MakeFun 이 네트워크로 나가는 지점을 전부 스텁으로 막는다.

    ``_once``(REST) · ``_fetch_bytes``(결과 다운로드) · ``_UP``(R2 presigned PUT) 세 곳이
    전부이고, 남은 opener(``_API``·``_DL``)는 열리는 순간 실패시킨다 — 실제 호출은 0회다.
    대기·백오프는 0초.
    """
    rec = _Net()

    def _once(method, path, body, timeout):
        rec.calls.append((method, path, body))
        out = api(method, path, body)
        # 진짜 _once 는 최상위 배열도 dict 로 감싸 돌려준다 — 스텁이 그 보증을 깨면
        # 위층이 실제보다 까다로운 조건에서 검사받는다. (그 감싸기 자체는 mf_raw 가 본다.)
        return {"code": 0, "data": out} if isinstance(out, list) else out

    def _fetch(url, timeout):
        if fetch is None:
            raise RuntimeError("다운로드 스텁 없음")
        return fetch(url)

    stubs = {"_once": _once, "_fetch_bytes": _fetch, "POLL_SEC": 0,
             "_backoff": lambda a, ra: 0.0, "_UP": _PutOpener(rec, put),
             "_API": _NoNet("_API"), "_DL": _NoNet("_DL")}
    with contextlib.ExitStack() as stack:
        for name, value in stubs.items():
            stack.enter_context(patched(mk, name, value))
        yield rec


@contextlib.contextmanager
def mf_raw(mk, reply):
    """전송 계층 **한 겹 아래**(_API opener)만 갈아끼운다 — 진짜 ``_once`` 를 통과시킨다.

    스펙에 응답 스키마가 비어 있는 엔드포인트(업스케일 상세·크레딧·allRecords)는 최상위가
    **배열**로 오기도 한다. 그 정규화는 ``_once`` 안에 있어서 ``_once`` 를 스텁하면 검사에서
    빠진다 — 여기서만 진짜로 지나간다. 소켓은 열리지 않는다(opener 자체가 가짜다).

    reply(method, url) → bytes(JSON 본문).
    """
    class _Resp:
        def __init__(self, raw):
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.raw

    class _Opener:
        def open(self, req, timeout=None):
            return _Resp(reply(req.get_method(), req.full_url))

    with env_var(mk.TOKEN_ENV, "selftest-token"), patched(mk, "_API", _Opener()), \
            patched(mk, "POLL_SEC", 0), patched(mk, "_backoff", lambda a, ra: 0.0), \
            patched(mk, "_DL", _NoNet("_DL")), patched(mk, "_UP", _NoNet("_UP")), \
            patched(mk, "_fetch_bytes", lambda url, timeout: _fail_fetch(url)):
        yield


def _fail_fetch(url):
    raise Failed(f"이 검사에서는 다운로드가 일어나면 안 된다: {url}")


def _mf_api(task_id: str, urls: list[str]):
    """start → task_id, 조회 → completed + urls 를 돌려주는 최소 모의 서버."""
    def api(method, path, body):
        if path.endswith("/start"):
            return {"code": 0, "data": [{"_id": task_id}]}
        return {"code": 0, "data": {"current_status": "completed", "image_urls": urls}}
    return api


def _r2_reply(body: dict, host: str = "https://cdn.example") -> dict:
    """R2 서명 발급 응답 — 요청한 key 를 그대로 되돌려 준다(주소 규칙까지 검사할 수 있게)."""
    key = str((body or {}).get("key") or "vn-studio/unnamed.png")
    return {"code": 0, "data": {"uploadUrl": f"https://up.example/{key}?X-Amz-Signature=zz",
                                "cdnUrl": f"{host}/{key}", "key": key,
                                "bucket": "vn", "expiresIn": 900}}


def _mf_upscale_api(up_id: str, result_url: str, *, detail=None, presign=_r2_reply):
    """업로드(R2) → 업스케일 start → 상세 조회까지 응답하는 모의 서버.

    ``detail`` 을 주면 상세 조회 응답을 그것으로 바꾼다(스펙에 비어 있는 응답 형태 실험용).
    """
    def api(method, path, body):
        if "/r2/" in path:
            return presign(body)
        if path.endswith("/userUpscale/start"):
            return {"success": True, "data": {"_id": up_id}, "timestamp": 1}
        if "userUpscale" in path:
            if detail is not None:
                return detail(method, path, body) if callable(detail) else detail
            return {"code": 0, "data": {"_id": up_id, "current_status": "completed",
                                        "image_urls": [result_url]}}
        raise Failed(f"모의 서버가 모르는 경로: {method} {path}")
    return api


@contextlib.contextmanager
def manifest_patch(b: Box, fn):
    """매니페스트를 잠시 고치고 **원문 그대로** 되돌린다(다른 테스트와의 상태 결합 차단).

    돌려주는 것은 (경로, 이 블록이 만든 내용) 이다 — 블록 안에서 도구가 매니페스트를
    되쓰지 않았는지 대조하는 기준이 '원본' 이 아니라 '방금 내가 둔 상태' 이기 때문이다.
    """
    path = b.p("project/manifest.json")
    orig = path.read_text(encoding="utf-8")
    data = json.loads(orig)
    fn(data)
    write_json(path, data)
    try:
        yield path, path.read_text(encoding="utf-8")
    finally:
        path.write_text(orig, encoding="utf-8")


@contextlib.contextmanager
def selected_scene(b: Box, approve: bool = False, size=(1200, 1800)):
    """후보 1장을 **선택까지** 마친 장면 — 업스케일의 출발점(승인까지 갈 수도 있다).

    크기 기본값은 실제 상황과 같다(1200×1800 = 300DPI 엽서가 한계인 승인 컷).
    """
    with cli_scene(b, "PROMPT") as sid:
        cand = b.root / f"_pick_{sid}.png"      # 파일명에 'up' 을 넣지 않는다(확대본 탐색과 섞인다)
        write_png(cand, size[0], size[1], (190, 170, 210))
        rc, out = b.run(ADV, "add-images", sid, str(cand))
        cand.unlink(missing_ok=True)
        if rc != 0:
            raise Failed(f"add-images 실패(rc={rc}) {out[:200]}")
        rc, out = b.run(ADV, "select", sid, "1")
        if rc != 0:
            raise Failed(f"select 실패(rc={rc}) {out[:200]}")
        if approve:
            rc, out = b.run(ADV, "approve", sid)
            if rc != 0:
                raise Failed(f"approve 실패(rc={rc}) {out[:200]}")
        yield sid


def _png_bytes(w: int = 40, h: int = 30) -> bytes:
    buf = Path(tempfile.gettempdir()) / f"_mf_{os.getpid()}_{threading.get_ident()}.png"
    write_png(buf, w, h)
    data = buf.read_bytes()
    buf.unlink(missing_ok=True)
    return data


def _usage_tail(b: Box, since: int) -> list[dict]:
    p = b.p("logs/makefun_usage.jsonl")
    if not p.exists():
        return []
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for l in lines[since:]:
        with contextlib.suppress(ValueError):
            out.append(json.loads(l))
    return out


def _usage_len(b: Box) -> int:
    p = b.p("logs/makefun_usage.jsonl")
    if not p.exists():
        return 0
    return len([l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()])


@test("makefun", "M01 정상 생성 — 파일 저장 + 생성 메타 + 사용 대장 기록(과금 0)")
def m01(b: Box):
    mk = b.mod("makefun_client")
    png = _png_bytes()
    with fresh_scene(b) as sid:
        out_dir = b.root / "images" / "raw" / sid
        n0 = _usage_len(b)
        with mf_stub(mk, _mf_api("task_abcdef", ["https://cdn.example/a_1.png"]),
                     lambda url: png):
            res = mk.generate_to_dir("고백하는 장면", out_dir, n=1, scene_id=sid, quiet=True)
        eq(len(res), 1, "저장된 파일 수")
        eq(list(res.warnings), [], "경고")
        saved = out_dir / "mf_abcdef_1.png"
        ok(saved.exists(), f"{saved.name} 미저장 — {[p.name for p in out_dir.glob('*')]}")
        meta = read_json(out_dir / mk.META_NAME)
        eq(meta["entries"][-1]["status"], "ok", "메타 status")
        eq(meta["entries"][-1]["files"], ["mf_abcdef_1.png"], "메타 files")
        rec = _usage_tail(b, n0)
        eq(len(rec), 1, "대장 기록 수")
        eq(rec[0]["saved"], 1, "대장 saved")
        eq(rec[0]["ok"], True, "대장 ok")
        eq(rec[0]["billable"], True, "대장 billable")
        eq(mk.scene_task_ids(sid), ["task_abcdef"], "장면 task 기록")


@test("makefun", "M02 429 는 재시도하고, 생성 시작의 5xx 는 재시도하지 않는다(이중 과금 방지)")
def m02(b: Box):
    mk = b.mod("makefun_client")
    state = {"n": 0}

    def api429(method, path, body):
        state["n"] += 1
        if state["n"] <= 2:
            raise mk._Transient("MakeFun HTTP 429", 429, 0.0)
        return {"code": 0, "data": [{"_id": "task_retry1"}]}

    with mf_stub(mk, api429):
        ids = mk.start("프롬프트", n=1, quiet=True)
    eq(ids, ["task_retry1"], "재시도 후 task id")
    eq(state["n"], 3, "재시도 횟수")

    state5 = {"n": 0}

    def api500(method, path, body):
        state5["n"] += 1
        raise mk._Transient("MakeFun HTTP 500", 500, 0.0)

    with mf_stub(mk, api500):
        raises(lambda: mk.start("프롬프트", n=1, quiet=True), RuntimeError, "500")
    eq(state5["n"], 1, "start 5xx 재시도(이중 생성 위험)")


@test("makefun", "M03 부분 실패 — 성공분은 저장하고 경고로 알린다")
def m03(b: Box):
    mk = b.mod("makefun_client")
    png = _png_bytes()

    def fetch(url):
        if url.endswith("_2.png"):
            raise RuntimeError("결과 다운로드 HTTP 404")
        return png

    with fresh_scene(b) as sid:
        out_dir = b.root / "images" / "raw" / sid
        n0 = _usage_len(b)
        with mf_stub(mk, _mf_api("task_part01", ["https://cdn.example/x_1.png",
                                                 "https://cdn.example/x_2.png"]), fetch):
            res = mk.generate_to_dir("프롬프트", out_dir, n=2, scene_id=sid, quiet=True)
        eq(len(res), 1, "저장된 파일 수")
        eq(len(res.warnings), 1, f"경고 {res.warnings}")
        meta = read_json(out_dir / mk.META_NAME)
        eq(meta["entries"][-1]["status"], "partial", "메타 status")
        rec = _usage_tail(b, n0)
        eq(rec[-1]["ok"], False, "대장 ok")
        eq(rec[-1]["saved"], 1, "대장 saved")


@test("makefun", "M04 다운로드 전부 실패 → task_id 는 남고 재수령으로 복구(재과금 없음)")
def m04(b: Box):
    mk = b.mod("makefun_client")
    png = _png_bytes()

    def dead(url):
        raise RuntimeError("결과 다운로드 HTTP 500")

    with fresh_scene(b) as sid:
        out_dir = b.root / "images" / "raw" / sid
        api = _mf_api("task_lost99", ["https://cdn.example/z_1.png"])
        with mf_stub(mk, api, dead):
            raises(lambda: mk.generate_to_dir("프롬프트", out_dir, n=1, scene_id=sid, quiet=True),
                   RuntimeError, "전부 실패인데 성공 반환")
        eq(mk.scene_task_ids(sid), ["task_lost99"], "task 기록(재수령 근거)")
        n0 = _usage_len(b)
        with mf_stub(mk, api, lambda url: png):
            res = mk.fetch_task_images("task_lost99", out_dir=out_dir, scene_id=sid, quiet=True)
        eq(len(res), 1, "재수령 파일 수")
        rec = _usage_tail(b, n0)
        eq(rec[-1]["billable"], False, "재수령은 과금 대상이 아님")
        eq(rec[-1].get("refetch"), True, "refetch 표시")


@test("makefun", "M05 무토큰 안내 · http 차단 · 2:3 규격(긴 변은 매니페스트 설정)")
def m05(b: Box):
    mk = b.mod("makefun_client")
    with env_var(mk.TOKEN_ENV, None):
        e = raises(mk.token, RuntimeError, "무토큰")
        has(str(e), mk.TOKEN_ENV, "안내 문구")
    bad = b.root / "mk_bad_manifest.json"
    write_json(bad, {"image_generator": {"api": {"base_url": "http://evil.example"}}})
    with patched(mk, "MANIFEST", bad):
        e2 = raises(mk.base_url, RuntimeError, "http base_url")
        has(str(e2), "https", "https 강제 안내")
    bad.unlink(missing_ok=True)
    want = (b.manifest().get("output") or {}).get("min_long_edge_px", 1024)
    w, h = mk._size_from_manifest()
    ok(max(w, h) >= want, f"긴 변 {max(w, h)} < {want}")
    eq(max(w, h) % 8, 0, "8의 배수 정렬")
    ok(min(w, h) < max(w, h), f"2:3 세로가 아님 {w}x{h}")
    eq(mk._ext("https://x/y.jpg?a=1"), ".jpg", "확장자 판정")


@test("makefun", "M06 요청 긴 변이 상한에 깎이면 생성 전에 경고한다(조용한 절삭 = 과금 함정)")
def m06(b: Box):
    """인화용으로 min_long_edge_px 를 올려도 image_generator.max_long_edge_px 가 낮으면
    조용히 깎여 나간다 — **과금은 요청대로 되고** 결과는 인화 규격 미달에 A3 FAIL 이다.
    그 사실이 생성(=과금) 전에 사용자에게 도달하는지를 모의로만 확인한다(실호출 0)."""
    mk = b.mod("makefun_client")
    plan_of = need_attr(mk, "size_plan", "크기 계산·절삭 여부의 단일 출처")
    warn_of = need_attr(mk, "size_warnings", "생성 전 절삭 경고")
    cap = mk._cap_px()
    plan = plan_of(cap * 3)
    eq(plan["capped"], True, f"상한 초과인데 capped=False — {plan}")
    eq(plan["cap"], cap, "cap")
    ok(max(plan["width"], plan["height"]) <= cap, f"상한을 넘겨 요청 — {plan}")
    msg = " / ".join(warn_of(plan))
    has(msg, "max_long_edge_px", "고치는 방법(매니페스트 키) 안내")
    has(msg, str(cap), "실제 상한값")
    eq(list(warn_of(plan_of(mk.SIZE_MIN_PX))), [], "깎이지 않았는데 경고")
    # 권고값은 8의 배수여야 실행 가능하다 — 상한은 8의 배수로 내려 잘리므로(2250 → 2248)
    # 요청값을 그대로 권하면 "이미 그 값인데 올리라"가 되고, 고쳐도 다시 깎이고 돈만 쓴다.
    def cap8(d, minpx: int, cap: int):
        d.setdefault("output", {}).update(aspect_ratio="2:3", min_long_edge_px=minpx)
        d.setdefault("image_generator", {})["max_long_edge_px"] = cap

    with manifest_patch(b, lambda d: cap8(d, 2250, 2250)):
        plan8 = plan_of()
        eq((plan8["long"], plan8["capped"]), (2248, True), f"8의 배수가 아닌 상한 — {plan8}")
        msg8 = " / ".join(warn_of(plan8))
        has(msg8, "2256", "권고 상한이 다음 8의 배수로 올라가지 않음(이미 설정된 값을 다시 권고)")
        hasnt(msg8, "2250 이상", "이미 적혀 있는 값을 올리라고 안내")
    with manifest_patch(b, lambda d: cap8(d, 2250, 2256)):
        p8 = plan_of()
        ok(p8["long"] >= 2250, f"권고대로 올렸는데 여전히 A3 미달 — {p8}")
        eq(list(warn_of(p8)), [], "권고대로 올렸는데 경고가 남음")
    # 실제 생성 경로가 그 경고를 결과로 돌려주는지 (네트워크 지점은 전부 스텁)
    png = _png_bytes()
    with fresh_scene(b) as sid:
        out_dir = b.root / "images" / "raw" / sid
        with mf_stub(mk, _mf_api("task_cap01", ["https://cdn.example/c_1.png"]), lambda url: png):
            res = mk.generate_to_dir("프롬프트", out_dir, n=1, long_edge=cap * 3,
                                     scene_id=sid, quiet=True)
        eq(len(res), 1, "저장된 파일 수")
        ok(any("max_long_edge_px" in w for w in res.warnings),
           f"생성 결과에 절삭 경고가 없음 — {list(res.warnings)}")
        entry = read_json(out_dir / mk.META_NAME)["entries"][-1]
        eq(max(entry["width"], entry["height"]), plan["long"], "기록된 크기가 실제 요청과 다름")


@test("makefun", "M07 R2 업로드 — presigned PUT 에 토큰을 싣지 않는다(서명 파손·키 유출 차단)")
def m07(b: Box):
    """업로드는 업스케일·레퍼런스의 **전제**다(두 API 가 URL 만 받는다).

    가장 조용한 사고 둘을 잠근다:
      * presigned PUT 에 Authorization 을 붙이면 서명이 깨져 업로드가 401 로 죽는다.
        (그리고 우리 API 토큰이 스토리지 쪽으로 새 나간다.)
      * 이미지가 아닌 파일이 그대로 올라가면 매니페스트·설정이 공개 CDN 에 놓인다.
    """
    mk = b.mod("makefun_client")
    upload = need_attr(mk, "upload_file", "로컬 파일 → 공개 URL(업스케일·레퍼런스의 전제)")
    src = b.root / "scratch" / "m07_src.png"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(_png_bytes(64, 96))
    raw = src.read_bytes()

    def api(method, path, body):
        if "/r2/" in path:
            return _r2_reply(body)
        raise Failed(f"업로드가 예상 밖의 경로를 부름: {method} {path}")

    n0 = _usage_len(b)
    with mf_stub(mk, api) as net:
        url = upload(src, quiet=True)
        url2 = upload(src, quiet=True)          # 같은 파일 → 같은 주소(스토리지 복제 방지)
    ok(url.startswith("https://"), f"공개 URL 이 https 가 아님: {url[:80]}")
    eq(url2, url, "같은 파일을 다시 올렸는데 주소가 달라짐(내용 해시 key 아님)")
    eq(len(net.puts), 2, f"PUT 횟수 — {net.paths()}")
    put = net.puts[0]
    eq(put["method"], "PUT", "업로드는 PUT 이어야 한다")
    eq(put["data"], raw, "올라간 바이트가 원본과 다름")
    ok("authorization" not in put["headers"],
       f"presigned PUT 에 Authorization 이 붙었다(서명 파손·토큰 유출) — {sorted(put['headers'])}")
    ok(not any("bearer" in v.lower() for v in put["headers"].values()),
       "PUT 헤더에 토큰 문자열이 실렸다")
    eq(put["headers"].get("content-type"), "image/png", "Content-Type 이 발급 때와 달라짐")
    body = net.sent("/r2/")
    eq(str(body.get("contentType") or body.get("content_type")), "image/png", "발급 요청 contentType")
    ok(len(raw) in (body.get("fileSize"), body.get("contentLength")),
       f"발급 요청에 실제 크기가 없음 — {body}")
    rec = _usage_tail(b, n0)
    ok(rec and rec[0]["kind"] == "upload", f"대장 kind — {rec[:1]}")
    eq(rec[0]["billable"], False, "업로드가 과금으로 기록됨")

    # 이미지가 아닌 파일 — content_type 을 명시하지 않으면 올라가지 않는다
    leak = b.root / "scratch" / "m07_secret.json"
    write_json(leak, {"token": "sk-누출되면안됨"})
    with mf_stub(mk, api) as net2:
        raises(lambda: upload(leak, quiet=True), RuntimeError, "이미지가 아닌 파일이 그대로 업로드됨")
        eq(len(net2.puts), 0, "거부했는데 PUT 이 나감")
    # 평문 http 주소를 돌려주는 응답은 거부한다(그 주소가 다시 생성 API 로 들어간다)
    with mf_stub(mk, lambda m, p, bd: _r2_reply(bd, host="http://cdn.example")) as net3:
        raises(lambda: upload(src, quiet=True), RuntimeError, "http 공개 주소를 받아들임")
        eq(len(net3.puts), 0, "http 주소인데 PUT 이 나감")
    raises(lambda: upload(b.root / "scratch" / "m07_없는파일.png", quiet=True),
           RuntimeError, "없는 파일")


@test("makefun", "M08 업스케일 — 재생성 없이 확대해 새 후보로만 저장(선택·승인 불변 · 대장 기록)")
def m08(b: Box):
    """이 기능의 존재 이유는 인화다: 1200×1800(엽서 한계) 컷을 재과금 없이 8×10 로 키운다.

    그래서 잠그는 것은 세 가지다 — (1) 확대본이 실제로 저장·등록되는가,
    (2) **사람이 고른 선택본이 그대로인가**(자동으로 갈아치우면 승인 게이트가 무의미해진다),
    (3) 비용이 대장에 남는가(kind=upscale · billable).
    """
    mk = b.mod("makefun_client")
    run_up = need_attr(mk, "upscale_scene", "선택 이미지를 재생성 없이 확대")
    big = _png_bytes(2400, 3600)
    with selected_scene(b) as sid:
        before = b.scene(sid)
        sel = before["assets"]["selected_image"]
        ok(sel, "픽스처에 선택본이 없다 — 아래 '선택본 불변' 검사가 공회전한다")
        n0 = _usage_len(b)
        api = _mf_upscale_api("up_scene01", "https://cdn.example/out/up_scene01.png")
        with mf_stub(mk, api, lambda url: big) as net:
            res = run_up(sid, quiet=True)
        eq(len(res), 1, f"저장된 파일 수 — 경고 {list(getattr(res, 'warnings', []))}")
        dest = Path(res[0])
        ok(dest.exists(), f"확대본 미저장: {dest}")
        eq(dest.parent, b.root / "images" / "raw" / sid, "저장 위치")
        stem = Path(sel).stem
        ok(stem in dest.stem and dest.stem != stem,
           f"원본을 알아볼 수 없는 파일명: {dest.name} (원본 {stem})")
        # 업로드 → 시작 → 조회 순서와, 시작 요청이 방금 올린 주소를 쓰는지
        eq(len(net.puts), 1, f"원본 업로드 PUT 이 한 번이 아님 — {len(net.puts)}")
        started = net.sent("/userUpscale/start")
        ok(str(started.get("source_url", "")).startswith("https://cdn.example/"),
           f"업스케일 시작이 업로드한 주소를 쓰지 않음 — {started}")

        after = b.scene(sid)
        eq(after["assets"]["selected_image"], sel, "업스케일이 사람이 고른 선택본을 바꿈")
        eq(after["status"], before["status"], "업스케일이 장면 상태를 움직임")
        eq(after["review"], before["review"], "업스케일이 검수 기록을 건드림")
        ok(dest.name in [Path(r).name for r in after["assets"]["raw_images"]],
           f"확대본이 후보로 등록되지 않음 — {after['assets']['raw_images']}")
        ok("up_scene01" not in mk.scene_task_ids(sid),
           "업스케일 id 가 makefun_tasks 에 섞였다 — 재수령(--refetch)이 통째로 깨진다")

        rec = _usage_tail(b, n0)
        up_rows = [r for r in rec if r.get("kind") == "upscale"]
        ok(up_rows, f"대장에 kind=upscale 기록이 없음 — {[r.get('kind') for r in rec]}")
        row = up_rows[-1]
        eq(row["billable"], True, "업스케일이 무과금으로 기록됨(비용 추적 불가)")
        eq(row["ok"], True, "대장 ok")
        eq(row["saved"], 1, "대장 saved")
        eq(row.get("scene_id"), sid, "대장 scene_id")
        entry = read_json(dest.parent / mk.META_NAME)["entries"][-1]
        eq(entry["kind"], "upscale", "메타 kind")
        eq(entry["status"], "ok", "메타 status")
        eq(entry["files"], [dest.name], "메타 files")
        # 무엇이 얼마나 커졌는지가 사람에게 도달하는가(이 기능의 존재 이유 그대로)
        ok(any("2400" in w and "3600" in w for w in res.warnings),
           f"확대 결과 크기를 알리지 않음 — {list(res.warnings)}")


@test("makefun", "M09 APPROVED 장면 업스케일 — 파일만 남기고 승인 도장은 건드리지 않는다")
def m09(b: Box):
    """인화 대상은 대부분 **이미 승인된** 컷이다. 그래서 이 경로는 열려 있어야 하고,
    동시에 승인 기록·선택본·후보 목록은 한 글자도 바뀌면 안 된다(사람 게이트).
    """
    mk = b.mod("makefun_client")
    run_up = need_attr(mk, "upscale_scene", "선택 이미지를 재생성 없이 확대")
    big = _png_bytes(2400, 3600)
    with selected_scene(b, approve=True) as sid:
        before = b.scene(sid)
        eq(before["status"], "APPROVED", "픽스처가 승인 상태가 아님")
        api = _mf_upscale_api("up_appr01", "https://cdn.example/out/up_appr01.png")
        with mf_stub(mk, api, lambda url: big):
            res = run_up(sid, quiet=True)
        eq(len(res), 1, "APPROVED 장면인데 확대본이 저장되지 않음")
        ok(Path(res[0]).exists(), "확대본 파일 없음")
        eq(b.scene(sid), before, "승인 장면이 업스케일로 바뀌었다 — 승인 게이트 위반")
        joined = " ".join(res.warnings)
        ok("revise" in joined,
           f"되돌리는 방법을 알려 주지 않음(후보 등록을 건너뛴 사실이 조용하다) — {list(res.warnings)}")
        # 승인 컷 확대는 **정상 경로**다(인화의 본 목적). 예정된 건너뜀을 '실패' 로 알리면
        # 사용자는 돈이 나갔는데 실패했다고 읽는다 — 실제로는 파일이 저장돼 있다.
        ok(not any("실패" in w for w in res.warnings),
           f"예정된 건너뜀을 실패로 알림 — {list(res.warnings)}")


@test("makefun", "M10 업스케일 응답 관용성 — 필드명이 달라도 흡수, 모르면 조용히 넘어가지 않는다")
def m10(b: Box):
    """업스케일 상세 응답은 **OpenAPI 스펙에 스키마가 비어 있다.** 필드명을 하나로 단정하면
    이름이 다를 때 이미 과금된 결과를 잃고, 반대로 너무 관대하면 원본을 결과로 착각한다.
    """
    mk = b.mod("makefun_client")
    wait_up = need_attr(mk, "wait_upscale", "업스케일 폴링(관대 파싱의 단일 출처)")
    src = "https://cdn.example/src/원본.png"
    out = "https://cdn.example/out/큰그림.png"

    def run(detail, **kw):
        with mf_stub(mk, _mf_upscale_api("up_x1", out, detail=detail)):
            return wait_up("up_x1", source_url=src, quiet=True, **kw)

    # 1) 다른 이름(state/outputUrl) · 2) 상태 없이 success 만
    eq(run({"code": 0, "data": {"state": "SUCCESS", "outputUrl": out}}), out, "state/outputUrl")
    eq(run({"code": 0, "data": {"success": True, "result_url": out}}), out, "success/result_url")
    # 3) 상세가 통하지 않으면 목록(allRecords)으로 회수한다 — 과금된 결과를 조회 실패로 잃지 않게
    def detail_404(method, path, body):
        if "allRecords" in path:
            return {"code": 0, "data": {"list": [{"id": "up_x1", "status": "done",
                                                  "image_url": out}]}}
        raise mk.VNError("MakeFun HTTP 404")
    eq(run(detail_404), out, "상세 404 → allRecords 대안")
    # 4) 최상위가 **배열**인 응답 — 정규화는 _once 안에 있어서 한 겹 아래에서만 진짜로 지나간다
    arr = json.dumps([{"_id": "up_x1", "current_status": "completed",
                       "image_urls": [out]}]).encode("utf-8")
    with mf_raw(mk, lambda method, url: arr):
        eq(wait_up("up_x1", source_url=src, quiet=True), out, "배열 응답")

    # 5) **가장 나쁜 실패**: 응답이 source_url 을 되돌려 줄 때 그것을 결과로 삼는 것
    e = raises(lambda: run({"code": 0, "data": {"current_status": "completed",
                                                "source_url": src, "url": src}}),
               RuntimeError, "원본 주소를 결과로 되돌려 받았는데 성공 처리")
    has(str(e), "current_status", "실패 문구에 응답 단서가 없음(무엇이 왔는지 알 수 없다)")
    # 6) 완료라는데 주소가 없다 / 결과가 https 가 아니다
    raises(lambda: run({"code": 0, "data": {"current_status": "completed"}}),
           RuntimeError, "완료+주소 없음인데 조용히 통과")
    raises(lambda: run({"code": 0, "data": {"current_status": "completed",
                                            "image_urls": ["ftp://x/y.png"]}}),
           RuntimeError, "https 가 아닌 결과를 받아들임")
    # 7) 실패 상태는 사유와 함께 즉시 알린다
    e2 = raises(lambda: run({"code": 0, "data": {"status": "failed",
                                                 "failed_message": "차단됨"}}),
                RuntimeError, "실패 상태인데 계속 기다림")
    has(str(e2), "차단됨", "실패 사유가 전달되지 않음")
    # 8) 전혀 모르는 형태 — 조용히 성공하지 않고, 응답 단서와 과금 사실을 담아 던진다
    e3 = raises(lambda: run({"code": 0, "data": {"foo": "bar"}}, max_sec=0.05),
                RuntimeError, "모르는 형태인데 조용히 통과")
    has(str(e3), "foo", "모르는 응답의 단서를 남기지 않음")
    has(str(e3), "up_x1", "회수에 필요한 작업 id 를 남기지 않음")
    # 9) 시작 응답의 관문 — id 가 없거나 거절이면 즉시 실패(무엇이 왔는지와 함께)
    start_up = need_attr(mk, "upscale_start", "업스케일 시작")
    with mf_stub(mk, lambda m, p, bd: {"success": True, "data": {"note": "id 없음"}}):
        e4 = raises(lambda: start_up(out, quiet=True), RuntimeError, "작업 id 없음")
        has(str(e4), "note", "응답 단서 없음")
    with mf_stub(mk, lambda m, p, bd: {"success": False, "data": {}}):
        raises(lambda: start_up(out, quiet=True), RuntimeError, "success=False 를 통과시킴")
    raises(lambda: start_up("http://cdn.example/x.png", quiet=True),
           RuntimeError, "평문 http 원본을 업스케일에 넘김")


@test("makefun", "M11 업스케일 실패 — 이미 과금된 작업·결과 주소를 남겨 재결제 없이 회수한다")
def m11(b: Box):
    """업스케일도 유료다. 시작한 뒤의 실패에서 작업 id 와 결과 주소를 잃으면 **돈만 나간다.**"""
    mk = b.mod("makefun_client")
    run_up = need_attr(mk, "upscale_scene", "선택 이미지를 재생성 없이 확대")

    # (1) 시작은 됐는데 결과 대기가 실패 — task_id 가 남아야 한다
    with selected_scene(b) as sid:
        n0 = _usage_len(b)
        fail_detail = {"code": 0, "data": {"current_status": "failed",
                                           "failed_message": "엔진 오류"}}
        api = _mf_upscale_api("up_fail01", "https://cdn.example/out/x.png", detail=fail_detail)
        with mf_stub(mk, api, lambda url: b""):
            raises(lambda: run_up(sid, quiet=True), RuntimeError, "실패인데 성공 반환")
        entry = read_json(b.root / "images" / "raw" / sid / mk.META_NAME)["entries"][-1]
        eq(entry["kind"], "upscale", "메타 kind")
        eq(entry["status"], "failed", "메타 status")
        eq(entry["task_id"], "up_fail01", "과금된 작업 id 가 남지 않음(회수 불가)")
        row = [r for r in _usage_tail(b, n0) if r.get("kind") == "upscale"][-1]
        eq(row["ok"], False, "대장 ok")
        eq(row["billable"], True, "시작된 유료 작업이 무과금으로 기록됨")

    # (2) 결과는 만들어졌는데 다운로드가 실패 — 결과 주소가 남아야 다시 결제하지 않는다
    with selected_scene(b) as sid2:
        keep = b.scene(sid2)
        out_url = "https://cdn.example/out/up_dl01.png"
        api2 = _mf_upscale_api("up_dl01", out_url)

        def dead(url):
            raise RuntimeError("결과 다운로드 HTTP 500")

        with mf_stub(mk, api2, dead):
            e = raises(lambda: run_up(sid2, quiet=True), RuntimeError, "다운로드 실패인데 성공 반환")
        has(str(e), "result_url", "회수 방법(결과 주소가 어디 있는지)을 알려 주지 않음")
        entry2 = read_json(b.root / "images" / "raw" / sid2 / mk.META_NAME)["entries"][-1]
        eq(entry2.get("result_url"), out_url, "결과 주소가 남지 않음 — 재결제 없이 회수 불가")
        eq(entry2["status"], "failed", "메타 status")
        eq(b.scene(sid2)["assets"], keep["assets"], "실패했는데 장면 후보·선택본이 바뀜")
        ok(not [p for p in (b.root / "images" / "raw" / sid2).glob("*_up*")],
           "실패했는데 반쪽 파일이 후보 폴더에 남았다")


@test("makefun", "M12 레퍼런스(input_images) — 모델 상한을 지키고, 없으면 파라미터를 아예 안 보낸다")
def m12(b: Box):
    """컷마다 얼굴이 흔들리던 1차 원인은 프롬프트가 아니라 레퍼런스 미첨부였다.

    상한(A2E 2장)을 넘겨 보내면 요청이 통째로 거절되고, 빈 배열을 보내면 모델이
    '레퍼런스 있음' 으로 해석할 수 있다 — 그래서 **없을 때는 키 자체가 없어야** 한다.
    """
    mk = b.mod("makefun_client")
    ref_urls = need_attr(mk, "reference_urls", "매니페스트 레퍼런스 → 보낼 수 있는 URL")
    png = _png_bytes()
    urls = [f"https://cdn.example/ref/jihye{i}.png" for i in (1, 2, 3)]
    prompted = {"prompt": {"grok_input_version": 1, "external_generator": "", "external_model": "",
                           "grok_output": "medium shot, cel shading"}}

    def with_refs(d, value, model=None):
        for c in d.get("characters", []):
            if c.get("character_id") == "CHAR-001":
                c["reference_images"] = value
        if model:      # MakeFun 모델은 makefun 블록이 정본이다(있으면 최상위를 덮는다 — SCHEMA §1.3)
            d.setdefault("image_generator", {}).setdefault("makefun", {})["model"] = model

    # 레퍼런스가 없는 기본 상태 — input_images 키 자체가 없어야 한다
    with fresh_scene(b, **prompted) as sid:
        with mf_stub(mk, _mf_api("task_ref00", ["https://cdn.example/r_1.png"]),
                     lambda u: png) as net:
            mk.generate_for_scene(sid, n=1, quiet=True)
        ok("input_images" not in net.sent("/userText2Image/start"),
           f"레퍼런스가 없는데 input_images 를 보냄 — {net.sent('/userText2Image/start')}")

    # A2E 상한 2장 — 3장이 있어도 2장만
    with manifest_patch(b, lambda d: with_refs(d, urls)) as (mpath, orig):
        eq(ref_urls(["CHAR-001"], limit=2), urls[:2], "reference_urls 상한")
        with fresh_scene(b, **prompted) as sid2:
            with mf_stub(mk, _mf_api("task_ref01", ["https://cdn.example/r_1.png"]),
                         lambda u: png) as net2:
                res = mk.generate_for_scene(sid2, n=1, quiet=True)
            body = net2.sent("/userText2Image/start")
            eq(body.get("input_images"), urls[:2],
               f"A2E 2장 상한을 지키지 않음 — {body.get('input_images')}")
            eq(len(res), 1, "생성 결과")
            entry = read_json(b.root / "images" / "raw" / sid2 / mk.META_NAME)["entries"][-1]
            eq(entry.get("input_images"), urls[:2], "무엇을 붙여 보냈는지 메타에 남지 않음")
            # --no-reference 로 끄면 다시 키가 없다
            with mf_stub(mk, _mf_api("task_ref02", ["https://cdn.example/r_1.png"]),
                         lambda u: png) as net3:
                mk.generate_for_scene(sid2, n=1, quiet=True, reference=False)
            ok("input_images" not in net3.sent("/userText2Image/start"),
               "reference=False 인데 레퍼런스를 보냄(--no-reference 가 듣지 않는다)")
        # 직접 넘겨도 상한은 같다
        with mf_stub(mk, _mf_api("task_ref03", []), lambda u: png) as net4:
            mk.start("프롬프트", n=1, quiet=True, input_images=urls + urls)
        eq(len(net4.sent("/userText2Image/start").get("input_images", [])), 2, "직접 전달 상한")

    # 모델이 바뀌면 상한도 바뀐다(Seedream 5.0 Pro 10장) — 2 가 코드에 박혀 있지 않은지
    with manifest_patch(b, lambda d: with_refs(d, urls, model="seedream-5.0-pro")):
        with mf_stub(mk, _mf_api("task_ref04", []), lambda u: png) as net5:
            mk.start("프롬프트", n=1, quiet=True, input_images=urls)
        eq(len(net5.sent("/userText2Image/start").get("input_images", [])), 3,
           "모델 상한이 A2E 2장으로 고정돼 있음")

    # 로컬 경로 레퍼런스는 올려서 URL 로 바꾸되 **매니페스트는 고치지 않는다**
    local = b.root / "images" / "ref_jihye.png"
    local.write_bytes(png)
    with manifest_patch(b, lambda d: with_refs(d, ["images/ref_jihye.png"])) as (mpath, text):
        with mf_stub(mk, lambda m, p, bd: _r2_reply(bd)) as net6:
            got = ref_urls(["CHAR-001"], limit=2)
        eq(len(got), 1, f"로컬 레퍼런스가 URL 로 바뀌지 않음 — {got}")
        ok(got[0].startswith("https://cdn.example/"), f"업로드 주소가 아님 — {got[0]}")
        eq(len(net6.puts), 1, "로컬 레퍼런스를 올리지 않음")
        eq(read_json(mpath)["characters"][0]["reference_images"], ["images/ref_jihye.png"],
           "레퍼런스 업로드가 매니페스트를 되썼다 — 이 모듈은 매니페스트를 쓰지 않는다")
        ok(mpath.read_text(encoding="utf-8") == text, "매니페스트가 업로드 과정에서 다시 쓰였다")
    local.unlink(missing_ok=True)


@test("makefun", "M13 크레딧 조회 — 읽기 전용이고, 응답 형식을 모르므로 잔액을 단정하지 않는다")
def m13(b: Box):
    """스펙에 응답 스키마가 비어 있다. 숫자 하나를 잔액으로 단정하면 사용자는 그 숫자를
    믿고 생성을 돌린다 — 보이는 것만 인용하고 판단은 계정 화면으로 넘긴다.
    """
    mk = b.mod("makefun_client")
    credits = need_attr(mk, "credits", "크레딧 이력 조회(읽기 전용)")
    payload = {"code": 0, "data": {"list": [{"amount": -12, "type": "image"},
                                            {"amount": -12, "type": "image"}],
                                   "balance": 1234}}
    n0 = _usage_len(b)
    with mf_stub(mk, lambda m, p, bd: payload) as net:
        rep = credits(quiet=True)
    ok(isinstance(rep, dict), f"반환형 — {type(rep).__name__}")
    for key in ("ok", "raw", "note"):
        ok(key in rep, f"반환 키 {key} 없음 — {sorted(rep)}")
    eq(rep["ok"], True, "정상 응답인데 ok=False")
    ok(str(rep["note"]).strip(), "note 가 비어 있음")
    ok(not net.puts, "크레딧 조회가 파일을 올림")
    eq([m for m, _p, _b in net.calls], ["GET"], f"읽기 전용이 아님 — {net.calls}")
    ok(all("transactionRecord" in p for p in net.paths()), f"조회 경로 — {net.paths()}")
    ok(not re.search(r"잔액[^\n]{0,6}[:=]?\s*1234", str(rep["note"])),
       f"응답의 숫자를 잔액으로 단정함 — {rep['note']}")
    row = _usage_tail(b, n0)[-1]
    eq(row["kind"], "credits", "대장 kind")
    eq(row["billable"], False, "이미지 생성 과금이 아닌데 과금으로 기록됨")
    # 최상위 배열 응답(스펙이 비어 있어 실제로 온다)도 삼킨다 — 정규화는 _once 안에 있다
    with mf_raw(mk, lambda method, url: b'[{"amount": -12, "type": "image"}]'):
        eq(credits(quiet=True)["ok"], True, "배열 응답을 오류로 처리")
    # 조회 실패는 예외가 아니라 ok=False 로 — 화면 하나 때문에 스튜디오가 죽지 않게
    def boom(method, path, body):
        raise mk.VNError("MakeFun HTTP 500")
    with mf_stub(mk, boom):
        bad = credits(quiet=True)
    eq(bad["ok"], False, "실패인데 ok=True")
    ok(str(bad["note"]).strip(), "실패 사유가 비어 있음")


@test("makefun", "M14 HTTP 가 아닌 응답 — traceback 대신 주소를 담은 VNError, 그리고 재시도 0(이중 과금 차단)")
def m14(b: Box):
    """base_url 오타·사내 프록시·TLS 포트에 평문 요청이면 응답 첫 줄이 상태줄이 아니라
    ``http.client.BadStatusLine`` 이 난다. 그것은 URLError 도 OSError 도 아니라서, 잡지 않으면
    CLI 로 **traceback 이 그대로 샜다**(comfyui_client 는 이미 막았다 — CF03. 같은 구멍이
    유료 경로에 남아 있었다).

    **_Transient 로 올리면 안 된다.** 이 예외는 요청을 *보낸 뒤* 응답을 읽다가 난다 —
    생성 시작(POST start)은 task 를 만드는 순간 과금이므로, 서버가 이미 받아 처리했는지
    알 수 없는 요청을 다시 보내면 한 번 더 청구될 수 있다. 그래서 재시도 대상이 아니다.
    (이미 재시도하던 코드들 — 429·5xx·전송 전 실패 — 의 의미는 M02 가 그대로 지킨다.)

    소켓은 진짜로 연다(_rude_server = ComfyUI 검사 CF03 이 쓰는 그 헬퍼). 스텁으로는
    전송 계층에서만 나는 이 예외를 재현할 수 없기 때문이다. 본문이 있는 요청은 헤더와
    본문이 **따로** 나가서(http.client._send_output), 무례한 서버가 먼저 끊으면 같은 자리에서
    ConnectionResetError 가 되기도 한다 — 둘 다 같은 안내로 모였는지 함께 본다.
    """
    mk = b.mod("makefun_client")
    tok = "selftest-token-not-a-real-key"
    rude = b"garbage" + BAD_LINE_END

    def bad_reply(call, label, *, port_in_msg=True):
        """무례한 서버를 상대로 call() 을 돌려 예외를 돌려준다 — 공통 주장까지 여기서."""
        e = raises(call, RuntimeError, label + ": HTTP 아닌 응답이 그대로 새어 나감")
        ok(isinstance(e, mk.VNError), f"{label}: VNError 가 아님 — {type(e).__name__}")
        ok(not isinstance(e, mk._Transient),
           f"{label}: 재시도 대상(_Transient)으로 올림 — 과금됐을 수 있는 요청을 다시 보낸다")
        hasnt(str(e), "Traceback", f"{label}: traceback")
        hasnt(str(e), tok, f"{label}: 안내문에 토큰이 섞임")
        return e

    # (1) 본문 없는 요청 — BadStatusLine 이 확실히 나는 자리. 안내가 무엇을 고치라고 하는가
    with _rude_server(rude) as port, env_var(mk.TOKEN_ENV, tok), \
            patched(mk, "base_url", lambda: f"http://127.0.0.1:{port}"):
        e = bad_reply(lambda: mk._once("GET", mk.P_CREDITS, None, 5), "조회")
    has(str(e), str(port), "두드린 주소")
    has(str(e), "base_url", "무엇을 고쳐야 하는지")

    # (2) 과금되는 자리 그대로 — POST start. 끊기는 지점이 어디든 재시도 대상이 아니어야 한다
    with _rude_server(rude) as port2, env_var(mk.TOKEN_ENV, tok), \
            patched(mk, "base_url", lambda: f"http://127.0.0.1:{port2}"):
        e2 = bad_reply(lambda: mk._once("POST", mk.P_T2I_START, {"prompt": "x"}, 5), "생성 시작")
    has(str(e2), str(port2), "두드린 주소")

    # (3) _call — 재시도 가치가 있는 오류였다면 여러 번 보낸다. 한 번이어야 한다.
    #     (멱등 GET 으로 센다 — idempotent=False 는 _Transient 여도 한 번이라 구분이 안 된다.)
    calls = {"n": 0}
    real_once = mk._once

    def counting(method, path, body, timeout):
        calls["n"] += 1
        return real_once(method, path, body, timeout)

    with _rude_server(rude) as port3, env_var(mk.TOKEN_ENV, tok), \
            patched(mk, "base_url", lambda: f"http://127.0.0.1:{port3}"), \
            patched(mk, "_backoff", lambda a, ra: 0.0), patched(mk, "_once", counting):
        e3 = raises(lambda: mk._call("GET", mk.P_CREDITS, timeout=5, quiet=True),
                    RuntimeError, "HTTP 아닌 응답")
    eq(calls["n"], 1, f"멱등 GET 인데도 재시도했다(재시도 한도 {mk.RETRY_MAX}) — "
                      "같은 경로를 POST 가 타면 이중 과금이다")
    has(str(e3), str(port3), "두드린 주소")

    # (4) 업로드(PUT)·결과 다운로드도 같은 구멍이었다 — 서명 쿼리는 안내문에 남기지 않는다
    secret = "deadbeefsignature"
    with _rude_server(rude) as port4:
        up = f"http://127.0.0.1:{port4}/bucket/key.png?X-Amz-Signature={secret}"
        e4 = bad_reply(lambda: mk._put_once(up, b"", "image/png", 5), "업로드 PUT")
    has(str(e4), str(port4), "두드린 주소")
    hasnt(str(e4), secret, "안내문에 presigned 서명이 그대로 남음")
    with _rude_server(rude) as port5:
        e5 = bad_reply(lambda: mk._fetch_bytes(f"http://127.0.0.1:{port5}/a.png?sig={secret}", 5),
                       "결과 다운로드")
    hasnt(str(e5), secret, "안내문에 서명이 그대로 남음")


# ============================================================ ComfyUI (모의)
# 실제 ComfyUI 는 무료·로컬이라 불러도 되지만, 자가진단은 이 PC 에 ComfyUI 가 켜져 있든 말든
# 같은 결과를 내야 한다(P17 이 로컬 LLM 을 죽은 포트로 고정하는 것과 같은 이유). 그래서
# HTTP 계약(/prompt · /history · /view · /object_info · /system_stats · /queue · /interrupt)을
# 그대로 흉내내는 모의 서버를 띄우고 **샌드박스 매니페스트의 comfyui.api.base_url** 만 그쪽으로
# 돌린다 — comfyui_client 의 전송 계층은 스텁하지 않고 진짜 urllib 경로를 끝까지 지나간다.
# (테스트 이름은 CF 로 시작한다 — checker 그룹의 C01~C06 과 -k 패턴이 섞이지 않게.)
COMFY_CKPTS = ("waiIllustriousSDXL_v170.safetensors", "juggernautXL_ragnarok.safetensors")
DEAD_COMFY = "http://127.0.0.1:59996"      # 아무도 듣지 않는 포트 — 'ComfyUI 꺼져 있음' 을 흉내낸다
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ComfyMock:
    """모의 ComfyUI 서버. ``mode`` 로 실패를 흉내낸다.

    ok(기본) · reject(POST /prompt 400 + node_errors) · error(실행 실패 메시지) ·
    pending(영원히 진행 중 — 시간 초과 경로) · badview(/view 가 PNG 가 아닌 것을 준다).
    ``delay_polls=N`` 이면 /history 를 N 번 비운 뒤 완료로 바꾼다(진행 콜백이 실제로 불리게).
    결과 PNG 는 제출된 그래프의 캔버스 크기(hires 면 LatentUpscale 크기)로 만든다 — 검사기 A3 가
    실제와 같은 조건에서 판정하도록.
    """

    def __init__(self, checkpoints=COMFY_CKPTS, mode: str = "ok", delay_polls: int = 0):
        self.checkpoints = list(checkpoints)
        self.mode, self.delay_polls = mode, delay_polls
        self.calls: list[tuple[str, str, dict]] = []      # (method, path, body|query)
        self.graphs: dict[str, dict] = {}                 # prompt_id → 제출된 그래프
        self.order: list[str] = []                        # 제출 순서의 prompt_id
        self.polls: dict[str, int] = {}
        self.files: dict[str, tuple[int, int]] = {}       # 결과 파일명 → (w, h)
        self._png: dict[tuple[int, int], bytes] = {}
        self._lock = threading.Lock()
        mock = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, raw: bytes, ctype: str = "application/json") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                if raw:
                    self.wfile.write(raw)

            def _json(self, code: int, obj) -> None:
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                mock.calls.append(("GET", u.path, q))
                if u.path == "/system_stats":
                    self._json(200, {"system": {"comfyui_version": "0.35.0-mock", "os": "nt",
                                                "python_version": "3.12"},
                                     "devices": [{"name": "cuda:0 Mock GPU", "type": "cuda",
                                                  "vram_total": 12_000_000_000}]})
                elif u.path == "/object_info/CheckpointLoaderSimple":
                    self._json(200, {"CheckpointLoaderSimple": {"input": {"required": {
                        "ckpt_name": [list(mock.checkpoints)]}}}})
                elif u.path == "/object_info/KSampler":
                    self._json(200, {"KSampler": {"input": {"required": {
                        "sampler_name": [["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde"]],
                        "scheduler": [["normal", "karras", "exponential"]]}}}})
                elif u.path == "/queue":
                    active = [pid for pid in mock.order if not mock.done(pid)]
                    self._json(200, {"queue_running": [[0, pid, {}, {}, []] for pid in active[:1]],
                                     "queue_pending": [[i + 1, pid, {}, {}, []]
                                                       for i, pid in enumerate(active[1:])]})
                elif u.path.startswith("/history/"):
                    self._json(200, mock.history(urllib.parse.unquote(u.path[len("/history/"):])))
                elif u.path == "/view":
                    dims = mock.files.get(str(q.get("filename", "")))
                    if dims is None:
                        self._send(404, b"not found", "text/plain")
                    elif mock.mode == "badview":
                        self._send(200, b"<html>not a png</html>", "text/html")
                    else:
                        self._send(200, mock.png(*dims), "image/png")
                else:
                    self._send(404, b"not found", "text/plain")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {"_raw": raw.decode("utf-8", "replace")}
                path = urllib.parse.urlsplit(self.path).path
                mock.calls.append(("POST", path, body if isinstance(body, dict) else {"_": body}))
                if path == "/prompt":
                    if mock.mode == "reject":
                        ck = str((((body.get("prompt") or {}).get("4") or {}).get("inputs") or {})
                                 .get("ckpt_name", "?"))
                        self._json(400, {
                            "error": {"type": "prompt_outputs_failed_validation",
                                      "message": "Prompt outputs failed validation", "details": "",
                                      "extra_info": {}},
                            "node_errors": {"4": {
                                "errors": [{"type": "value_not_in_list", "message": "Value not in list",
                                            "details": f"ckpt_name: {ck!r} not in {mock.checkpoints}",
                                            "extra_info": {"input_name": "ckpt_name"}}],
                                "dependent_outputs": ["9"], "class_type": "CheckpointLoaderSimple"}}})
                        return
                    pid = mock.submit(body.get("prompt") or {})
                    self._json(200, {"prompt_id": pid, "number": len(mock.order), "node_errors": {}})
                elif path == "/interrupt":
                    self._send(200, b"")
                elif path == "/queue":
                    self._send(200, b"")
                else:
                    self._send(404, b"not found", "text/plain")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        # poll_interval 을 짧게 — 테스트마다 서버를 띄우고 내리므로 shutdown 대기(기본 0.5초)가 쌓인다
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    # -------------------------------------------------- 서버 쪽 상태
    def submit(self, graph: dict) -> str:
        pid = str(uuid.uuid4())
        with self._lock:
            self.graphs[pid] = graph
            self.order.append(pid)
            self.polls[pid] = 0
            inputs = ((graph.get("11") or graph.get("5") or {}).get("inputs") or {})
            dims = (int(inputs.get("width", 64)), int(inputs.get("height", 64)))
            prefix = str(((graph.get("9") or {}).get("inputs") or {}).get("filename_prefix", "x"))
            fname = f"{prefix.rsplit('/', 1)[-1]}_{len(self.order):05d}_.png"
            self.files[fname] = dims
            self.graphs[pid]["_file"] = fname
        return pid

    def done(self, pid: str) -> bool:
        if pid not in self.graphs or self.mode == "pending":
            return False
        return self.polls.get(pid, 0) >= self.delay_polls

    def history(self, pid: str) -> dict:
        if pid not in self.graphs or self.mode == "pending":
            return {}
        with self._lock:
            self.polls[pid] = self.polls.get(pid, 0) + 1
            n = self.polls[pid]
        if n <= self.delay_polls:
            return {}
        if self.mode == "error":
            return {pid: {"status": {"status_str": "error", "completed": True, "messages": [
                ["execution_start", {"prompt_id": pid}],
                ["execution_error", {"prompt_id": pid, "node_id": "3", "node_type": "KSampler",
                                     "exception_message": "CUDA out of memory (mock)"}]]},
                          "outputs": {}}}
        fname = self.graphs[pid]["_file"]
        prefix = str(((self.graphs[pid].get("9") or {}).get("inputs") or {}).get("filename_prefix", ""))
        sub = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
        return {pid: {"status": {"status_str": "success", "completed": True, "messages": []},
                      "outputs": {"9": {"images": [{"filename": fname, "subfolder": sub,
                                                     "type": "output"}]}}}}

    def png(self, w: int, h: int) -> bytes:
        key = (w, h)
        with self._lock:
            if key not in self._png:
                self._png[key] = _png_bytes(w, h)
            return self._png[key]

    # -------------------------------------------------- 테스트 쪽 조회
    def hits(self, needle: str) -> list[tuple[str, str, dict]]:
        return [c for c in self.calls if needle in c[1]]

    def prompts(self) -> list[dict]:
        return [c[2] for c in self.calls if c[0] == "POST" and c[1] == "/prompt"]

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.server.shutdown()
            self.server.server_close()


def _pid6(pid: str) -> str:
    return pid.replace("-", "")[:6]


@contextlib.contextmanager
def comfy_mock(b: Box, *mods, checkpoint: str | None = None, **kw):
    """모의 ComfyUI 를 띄우고 샌드박스 매니페스트 ``comfyui.api.base_url`` 을 그쪽으로 돌린다.

    ``COMFYUI_URL`` 은 비운다(이 PC 의 환경변수가 결과를 바꾸면 안 된다). ``mods`` 로 넘긴
    comfyui_client 인스턴스의 체크포인트 캐시(60초)는 들어갈 때·나올 때 비운다 — 앞 테스트가
    본 목록이 이 테스트에 남지 않게. 매니페스트는 블록을 나가면 원문 그대로 돌아간다.
    """
    mock = ComfyMock(**kw)

    def point(d):
        ig = d.setdefault("image_generator", {})
        ig["engine"] = "comfyui"
        cu = ig.setdefault("comfyui", {})
        cu.setdefault("api", {})["base_url"] = mock.url
        if checkpoint is not None:
            cu["checkpoint"] = checkpoint

    def flush():
        for m in mods:
            cache = getattr(m, "_CKPT_CACHE", None)
            if isinstance(cache, dict):
                cache.update(ts=0.0, names=[])

    try:
        with env_var("COMFYUI_URL", None), manifest_patch(b, point):
            flush()
            yield mock
    finally:
        flush()
        mock.close()


def _cf_usage(b: Box) -> list[dict]:
    p = b.p("logs/comfyui_usage.jsonl")
    if not p.exists():
        return []
    out = []
    for l in p.read_text(encoding="utf-8").splitlines():
        if l.strip():
            with contextlib.suppress(ValueError):
                out.append(json.loads(l))
    return out


def _graph_refs_ok(g: dict) -> None:
    """모든 노드가 class_type/inputs 를 갖고, 링크([노드, 출력]) 가 존재하는 노드를 가리킨다."""
    for nid, node in g.items():
        ok({"class_type", "inputs"} <= set(node), f"노드 {nid} 구조 — {sorted(node)}")
        for key, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[1], int):
                ok(v[0] in g, f"노드 {nid}.{key} 가 없는 노드 {v[0]} 를 가리킴")


@test("comfyui", "CF01 정상 렌더 — cf_<id6>_n.png 저장 + 메타(engine·seed·billable=false) + 무료 대장 · MakeFun 흔적 0")
def cf01(b: Box):
    """ComfyUI 는 과금이 없지만 기록 규약은 MakeFun 과 같아야 한다(gen_jobs·스튜디오가 한 모양만
    읽는다). 시드가 메타에 남는 것이 재현의 열쇠다 — 같은 체크포인트·프롬프트·시드면 같은 그림.
    """
    cf = b.mod("comfyui_client")
    with comfy_mock(b, cf) as mock, fresh_scene(b) as sid:
        out_dir = b.root / "images" / "raw" / sid
        n_mf, n_cf = _usage_len(b), len(_cf_usage(b))
        scene_text = b.scene_path(sid).read_text(encoding="utf-8")
        res = cf.generate_to_dir("고백하는 장면", out_dir, n=2, name=sid, scene_id=sid,
                                 quiet=True, seed=7)
        eq(len(res), 2, "저장된 파일 수")
        eq(list(res.warnings), [], "경고")
        eq(list(res.task_ids), list(mock.order), "task_ids 가 제출한 prompt_id 와 다름")
        want = sorted(f"cf_{_pid6(pid)}_{i + 1}.png" for i, pid in enumerate(mock.order))
        eq(sorted(p.name for p in out_dir.glob("*.png")), want, "파일 이름 규약 cf_<promptid6>_<n>.png")
        for p in res:
            ok(Path(p).read_bytes().startswith(PNG_MAGIC), f"{Path(p).name} 이 PNG 가 아님")
        # 제출한 그래프가 그 시드·그 체크포인트(첫 항목)·그 장면 이름을 실었다
        for i, pid in enumerate(mock.order):
            g = mock.graphs[pid]
            eq(g["4"]["inputs"]["ckpt_name"], COMFY_CKPTS[0], "체크포인트 미지정 → ComfyUI 첫 항목")
            eq(g["3"]["inputs"]["seed"], 7 + i, f"{i + 1}번째 시드(seed+i)")
            eq(g["9"]["inputs"]["filename_prefix"], f"vn_studio/{sid}", "SaveImage 접두어")
        body = mock.prompts()[0]
        ok(body.get("client_id"), "client_id 없이 제출")
        # 메타 — 엔진·시드·설정·무과금
        entries = read_json(out_dir / cf.META_NAME)["entries"]
        eq(len(entries), 2, "메타 항목 수")
        e0 = entries[0]
        for key in ("created_at", "scene_id", "task_id", "kind", "engine", "prompt", "negative",
                    "model", "seed", "steps", "cfg", "sampler", "scheduler", "clip_skip",
                    "width", "height", "hires", "files", "status", "error", "billable"):
            ok(key in e0, f"메타에 {key} 없음 — {sorted(e0)}")
        eq((e0["engine"], e0["kind"], e0["billable"], e0["status"]),
           ("comfyui", "text2image", False, "ok"), "메타 engine/kind/billable/status")
        eq((e0["seed"], entries[1]["seed"]), (7, 8), "메타 seed")
        eq(e0["task_id"], mock.order[0], "메타 task_id = prompt_id")
        eq(e0["model"], COMFY_CKPTS[0], "메타 model = 체크포인트")
        eq((e0["width"], e0["height"], e0["hires"]), (832, 1248, False), "메타 크기(2:3 · 1MP 캔버스)")
        eq(e0["files"], [f"cf_{_pid6(mock.order[0])}_1.png"], "메타 files")
        eq(e0["error"], "", "성공인데 error 가 비어 있지 않음")
        # 대장 — logs/comfyui_usage.jsonl 두 줄(billable false) · MakeFun 대장은 한 줄도 늘지 않았다
        rec = _cf_usage(b)[n_cf:]
        eq(len(rec), 2, "무료 대장 줄 수")
        eq((rec[0]["billable"], rec[0]["ok"], rec[0]["saved"], rec[0]["kind"]),
           (False, True, 1, "text2image"), "대장 billable/ok/saved/kind")
        eq((rec[0]["scene_id"], rec[0]["task_id"], rec[0]["seed"]), (sid, mock.order[0], 7), "대장 장면/작업/시드")
        eq(_usage_len(b), n_mf, "ComfyUI 렌더가 MakeFun 대장에 줄을 남김(과금 합산이 어긋난다)")
        # SCHEMA §3.3b 는 이 대장의 필드를 산문으로 복제한다 — 코드가 쓰는 키가 전부 적혀 있어야 한다
        # (빠진 필드는 "지워도 잃는 게 없다"는 안내를 조용히 거짓말로 만든다: hires·billable 이 그랬다)
        sec = doc_section(doc_text(b), "### 3.3b")
        listed = doc_names(sec)
        eq(sorted(k for k in rec[0] if k not in listed), [],
           "comfyui_usage.jsonl 에 쓰는데 SCHEMA §3.3b 가 설명하지 않는 필드")
        eq(b.scene_path(sid).read_text(encoding="utf-8"), scene_text,
           "generate_to_dir 가 장면 파일을 건드림(makefun_tasks·status 는 이 경로가 쓰지 않는다)")
        # 시드를 안 주면 무작위(0 ≤ seed < 2**53) — 그래도 메타에 남는다
        cf.generate_to_dir("두 번째", out_dir, n=1, name=sid, scene_id=sid, quiet=True)
        e2 = read_json(out_dir / cf.META_NAME)["entries"][-1]
        ok(isinstance(e2["seed"], int) and 0 <= e2["seed"] < 2 ** 53, f"무작위 시드 — {e2['seed']!r}")
        eq(mock.graphs[mock.order[-1]]["3"]["inputs"]["seed"], e2["seed"], "그래프 시드 ≠ 메타 시드")
        # 레퍼런스가 들어오면 '쓰지 않는다' 경고 — 오류도, 업로드도 아니다
        res3 = cf.generate_to_dir("셋", out_dir, n=1, scene_id=sid, quiet=True, seed=1,
                                  input_images=["https://cdn.example/ref.png"])
        eq(len(res3), 1, "레퍼런스가 있으면 렌더가 막힘")
        ok(any("레퍼런스" in w for w in res3.warnings), f"레퍼런스 미사용 경고 없음 — {list(res3.warnings)}")
        known = {"/prompt", "/queue", "/view", "/object_info/CheckpointLoaderSimple", "/system_stats"}
        odd = sorted({p for _m, p, _q in mock.calls if p not in known and not p.startswith("/history/")})
        eq(odd, [], "모르는 경로로 요청이 나감(업로드 등)")
        raises(lambda: cf.generate_to_dir("   ", out_dir, quiet=True), RuntimeError, "빈 프롬프트")
        raises(lambda: cf.generate_to_dir("p", out_dir, quiet=True, seed="x"), RuntimeError, "정수 아닌 시드")


@test("comfyui", "CF02 장면 렌더 — 생성기 기록은 scene_ops 를 거치고, 등록·상태 전이는 gen_jobs/scene_ops 만 한다")
def cf02(b: Box):
    """클라이언트 단독 호출은 파일·기록만 남기고 장면의 status·assets 를 움직이지 않는다.
    run_scene(CLI)은 gen_jobs 관문 → register_images → 자동 검사 → IMAGE 까지 한 번에 간다
    (무료라 다시 만들면 되므로). APPROVED 는 렌더 자체를 거절한다(서버 요청 0).
    """
    cf = b.mod("comfyui_client")
    with comfy_mock(b, cf) as mock, cli_scene(b, "PROMPT") as sid:
        before = b.scene(sid)
        res = cf.generate_for_scene(sid, n=1, quiet=True, seed=3)
        eq(len(res), 1, "저장된 파일 수")
        sc = b.scene(sid)
        eq(sc["prompt"]["external_generator"], "ComfyUI", "prompt.external_generator")
        eq(sc["prompt"]["external_model"], COMFY_CKPTS[0], "prompt.external_model = 체크포인트")
        eq(sc["prompt"]["grok_output"], before["prompt"]["grok_output"], "프롬프트 원문이 바뀜")
        eq(sc["status"], before["status"], "클라이언트 단독 호출이 장면 상태를 움직임")
        eq(sc["assets"]["raw_images"], [], "클라이언트가 후보 목록을 직접 등록함(등록은 gen_jobs 의 일)")
        g = mock.graphs[mock.order[-1]]
        has(g["6"]["inputs"]["text"], before["prompt"]["grok_output"], "장면 프롬프트가 그래프에 실리지 않음")
        ok(g["6"]["inputs"]["text"].lower().startswith("masterpiece"),
           f"Illustrious 프리셋 접두어가 붙지 않음 — {g['6']['inputs']['text'][:60]!r}")
        eq(g["3"]["inputs"]["sampler_name"], "euler_ancestral", "Illustrious 프리셋 샘플러")
        ok("10" in g and g["10"]["inputs"]["stop_at_clip_layer"] == -2, "clip_skip 2 → CLIPSetLastLayer -2")
        # 등록까지 — run_scene → gen_jobs.start(sync) → register_images → 자동 검사 PASS → IMAGE
        rep = cf.run_scene(sid, n=1, seed=4, quiet=True)
        eq(rep.get("auto"), "PASS", f"자동 검사 — {rep}")
        eq(rep.get("count"), 2, f"후보 수 — {rep}")
        sc = b.scene(sid)
        eq(sc["status"], "IMAGE", "등록 뒤 상태(REVIEW_HUMAN 승격은 사람이 고를 때만)")
        eq(len(sc["assets"]["raw_images"]), 2, "후보 등록 수")
        ok(all(Path(r).name.startswith("cf_") for r in sc["assets"]["raw_images"]),
           f"후보 이름 — {sc['assets']['raw_images']}")
        eq(sc["review"]["auto"], "PASS", "review.auto")
        jobs = cf._jobs()
        ok(jobs is not None, "comfyui_client 가 gen_jobs 를 찾지 못함")
        ok(sid not in jobs.running(), "끝났는데 선점 표시가 남음")
        ok(not b.p(f"logs/gen_locks/{sid}.lock").exists(), "잠금 파일이 남음")
        # 다른 곳(웹)이 굽고 있으면 CLI 도 같은 관문에서 거절 — 서버 요청 0
        n_prompt = len(mock.prompts())
        jobs.claim(sid, "생성")
        try:
            raises(lambda: cf.run_scene(sid, n=1, quiet=True), RuntimeError, "선점 중인데 렌더가 시작됨")
        finally:
            jobs.release(sid)
        eq(len(mock.prompts()), n_prompt, "거절됐는데 ComfyUI 에 그래프가 제출됨")
        # 프롬프트가 없는 장면은 안내와 함께 거절
    with comfy_mock(b, cf) as mock2, fresh_scene(b) as bare:
        e = raises(lambda: cf.generate_for_scene(bare, quiet=True), RuntimeError, "프롬프트 없는 장면")
        has(str(e), "프롬프트", "무엇이 없는지")
        eq(mock2.prompts(), [], "프롬프트가 없는데 제출됨")
    # APPROVED — 렌더 자체를 거절(표준 문구는 scene_ops 가 낸다) · 기록도 그대로
    with comfy_mock(b, cf) as mock3, cli_scene(b, "APPROVED") as sid2:
        before2 = b.scene(sid2)
        e = raises(lambda: cf.generate_for_scene(sid2, quiet=True), RuntimeError, "APPROVED 인데 렌더")
        has(str(e), "APPROVED", "무엇 때문에 막혔는지")
        has(str(e), "revise", "다음에 할 일 안내")
        eq(mock3.prompts(), [], "APPROVED 인데 ComfyUI 에 제출됨")
        eq(b.scene(sid2), before2, "거절됐는데 장면이 바뀜")
        so = b.mod("scene_ops")
        raises(lambda: so.record_external_generator(sid2, "ComfyUI", "x"), RuntimeError,
               "APPROVED 컷의 출처 기록이 덧씌워짐")
        eq(b.scene(sid2), before2, "거절됐는데 장면이 바뀜(record_external_generator)")
    # 정적 — 클라이언트는 장면 파일을 직접 쓰지 않는다: 기록은 scene_ops, 등록은 gen_jobs
    calls = func_calls(b, "comfyui_client", "_record_generator")
    ok(any(c.split(".")[-1] == "record_external_generator" for c in calls),
       f"생성기 기록이 scene_ops 를 거치지 않음 — {sorted(calls)}")
    for fn in ("generate_to_dir", "generate_for_scene", "_record_generator", "run_scene", "download"):
        calls = func_calls(b, "comfyui_client", fn)
        for direct in ("atomic_write_json", "vn_core.atomic_write_json", "_save", "register_images",
                       "scene_ops.register_images", "record_generation_tasks"):
            ok(direct not in calls, f"comfyui_client.{fn} 이 장면 파일 경로를 직접 씀({direct})")
    imports = tool_imports(b, "comfyui_client")
    ok("makefun_client" not in imports, "comfyui_client 가 makefun_client 를 import 함(엔진은 서로를 모른다)")


# HTTP 가 아닌 첫 줄 — 상태줄 자리에 아무 말이나 오면 http.client.BadStatusLine 이 난다.
# (줄끝은 소스에 직접 쓰지 않는다 — 에디터·도구가 CRLF 를 만지면 검사 자체가 흔들린다.)
BAD_LINE_END = bytes([13, 10])


@contextlib.contextmanager
def _rude_server(reply: bytes):
    """HTTP 가 아닌 답을 한 번 뱉고 끊는 소켓 — 포트를 넘겨준다(ComfyUI 아닌 것이 앉은 포트)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        with contextlib.suppress(Exception):
            conn, _ = srv.accept()
            with conn:
                conn.settimeout(2)
                with contextlib.suppress(Exception):
                    conn.recv(65536)
                conn.sendall(reply)

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    try:
        yield port
    finally:
        srv.close()
        th.join(timeout=2)


@test("comfyui", "CF03 실패 경로 — 400 node_errors 는 노드·종류를 말하고, 실행 오류·비PNG·꺼진 서버도 VNError(조용한 성공 0)")
def cf03(b: Box):
    cf = b.mod("comfyui_client")
    scratch = b.root / "scratch" / "cf03"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        with comfy_mock(b, cf, mode="reject") as mock:
            plan = cf.size_plan()
            s = cf.settings(COMFY_CKPTS[0])
            g = cf.build_graph("p", "n", ckpt="bogus.safetensors", seed=1, s=s, plan=plan, name="x")
            e = raises(lambda: cf.submit(g), RuntimeError, "400 인데 통과")
            for needle in ("노드 4", "CheckpointLoaderSimple", "Value not in list", "bogus.safetensors"):
                has(str(e), needle, "400 안내에 노드·종류·메시지")
            # generate_to_dir 로도 같은 사유가 올라오고, 실패가 메타·대장에 남는다
            n_cf = len(_cf_usage(b))
            e2 = raises(lambda: cf.generate_to_dir("p", scratch, scene_id="", quiet=True, seed=1),
                        RuntimeError, "전부 실패인데 결과를 돌려줌")
            has(str(e2), "CheckpointLoaderSimple", "실패 사유가 결과에 실리지 않음")
            eq(sorted(scratch.glob("*.png")), [], "실패인데 파일이 남음")
            entry = read_json(scratch / cf.META_NAME)["entries"][-1]
            eq((entry["status"], entry["billable"], entry["files"]), ("failed", False, []), "실패 메타")
            has(entry["error"], "노드 4", "메타 error 에 사유")
            rec = _cf_usage(b)[n_cf:]
            eq(len(rec), 1, "실패도 대장에 한 줄")
            eq((rec[0]["ok"], rec[0]["saved"], rec[0]["billable"]), (False, 0, False), "실패 대장")
            eq(mock.hits("/history/"), [], "거절됐는데 결과를 조회함")
        with comfy_mock(b, cf, mode="error"):
            e = raises(lambda: cf.generate_to_dir("p", scratch, quiet=True, seed=1), RuntimeError, "실행 오류인데 통과")
            has(str(e), "KSampler", "실행 오류의 노드 종류")
            has(str(e), "CUDA out of memory", "실행 오류 메시지")
        with comfy_mock(b, cf, mode="badview") as mock3:
            e = raises(lambda: cf.generate_to_dir("p", scratch, quiet=True, seed=1), RuntimeError, "PNG 아님인데 통과")
            has(str(e), "PNG", "PNG 판정 안내")
            eq(sorted(scratch.glob("*.png")), [], "PNG 가 아닌 것을 저장함")
            ok(mock3.hits("/view"), "다운로드를 시도하지 않음")
        # 완료라는데 결과 파일이 서버에 없다(404) — 크래시 대신 HTTP 상태를 담은 안내
        with comfy_mock(b, cf) as mock4:
            pid = cf.submit(cf.build_graph("p", "n", ckpt=COMFY_CKPTS[0], seed=1, s=s, plan=plan))
            mock4.files.clear()                       # /view 가 404 를 내게
            with patched(cf, "POLL_SEC", 0.01):
                e = raises(lambda: cf.download(cf.wait(pid, max_sec=5, quiet=True)[0], scratch / "z.png"),
                           RuntimeError, "404 다운로드가 통과")
            has(str(e), "404", "HTTP 상태가 안내에 없음")
        # 그 포트에 ComfyUI 가 아닌 것이 앉아 있다(다른 앱·프록시·TLS 포트) — 응답 첫 줄이 상태줄이
        # 아니면 http.client.BadStatusLine 이 난다. 그것은 URLError 도 OSError 도 아니라 CLI 로
        # traceback 이 그대로 샜다. 사용자가 할 일은 꺼진 서버와 같다 — 주소 확인이다.
        with _rude_server(b"garbage\r\n") as bad_port, env_var("COMFYUI_URL", f"http://127.0.0.1:{bad_port}"):
            e = raises(lambda: cf.checkpoints(refresh=True), RuntimeError,
                       "HTTP 가 아닌 응답이 VNError 로 오지 않음(traceback 이 그대로 샌다)")
            has(str(e), str(bad_port), "두드린 주소")
            hasnt(str(e), "Traceback", "traceback")
        # 서버가 꺼져 있으면 주소를 담은 연결 안내(어디를 두드렸는지 보여야 고칠 수 있다)
        with env_var("COMFYUI_URL", DEAD_COMFY):
            e = raises(lambda: cf.checkpoints(refresh=True), RuntimeError, "꺼진 서버")
            has(str(e), "연결", "연결 안내")
            has(str(e), "59996", "두드린 주소")
            hasnt(str(e), "Traceback", "traceback")
            rep = cf.check(online=True)
            eq(rep["ok"], False, "온라인 점검이 꺼진 서버를 OK 로 봄")
            ok(any("FAIL" in l and "연결" in l for l in rep["lines"]), f"점검 줄 — {rep['lines']}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@test("comfyui", "CF04 대기 시간 초과 — 끝나지 않는 작업은 중단·삭제 요청을 보내고 VNError(GPU 에 유령 작업 0)")
def cf04(b: Box):
    """폴링 간격(POLL_SEC)은 0 에 가깝게, 상한은 1초로 — 실제 600초를 기다리지 않는다.
    진행 콜백은 매 조회마다 불려야 한다(gen_jobs 의 좌초 판정이 그 심장박동을 본다)."""
    cf = b.mod("comfyui_client")
    with comfy_mock(b, cf, mode="pending") as mock:
        plan = cf.size_plan()
        s = cf.settings(COMFY_CKPTS[0])
        pid = cf.submit(cf.build_graph("p", "n", ckpt=COMFY_CKPTS[0], seed=1, s=s, plan=plan))
        beats: list[tuple[float, str]] = []
        t0 = time.monotonic()
        with patched(cf, "POLL_SEC", 0.01):
            e = raises(lambda: cf.wait(pid, on_progress=lambda el, st: beats.append((el, st)),
                                       max_sec=1, quiet=True),
                       RuntimeError, "시간 초과인데 계속 기다림")
        took = time.monotonic() - t0
        ok(took < 6, f"상한 1초인데 {took:.1f}초 걸림")
        has(str(e), "시간 초과", "시간 초과 안내")
        has(str(e), _pid6(pid), "어느 작업인지")
        has(str(e), "timeout_sec", "늘리는 방법(매니페스트 키)")
        ok(len(mock.hits("/history/")) >= 2, "조회를 반복하지 않음")
        ok(len(beats) >= 2, f"진행 콜백이 {len(beats)}회 — 매 조회마다 불려야 한다")
        ok(all(isinstance(el, float) and el >= 0 for el, _s in beats), "경과 초가 숫자가 아님")
        ok(any(st == "렌더 중" for _el, st in beats), f"큐 상태가 진행 문구에 없음 — {beats[:3]}")
        posts = [(p, body) for m, p, body in mock.calls if m == "POST" and p in ("/interrupt", "/queue")]
        ok(posts, "시간 초과 뒤 중단(/interrupt)·삭제(/queue) 요청이 없음 — GPU 에 유령 작업이 남는다")
        dels = [body.get("delete") for p, body in posts if p == "/queue"]
        ok(any(pid in (d or []) for d in dels), f"큐 삭제 요청에 그 prompt_id 가 없음 — {dels}")
        ok(any(p == "/interrupt" for p, _b in posts), "렌더 중인 작업인데 /interrupt 를 보내지 않음")
        # 이미 사라진 작업의 cancel 은 조용히 넘어간다(정리 과정이 두 번째 오류를 만들지 않게)
        cf.cancel("00000000-0000-0000-0000-000000000000")


@test("comfyui", "CF05 크기 계획·그래프 배선·프리셋 — 1MP 기본 캔버스, 큰 목표는 hires 2단(1차의 2배까지), 부정 프롬프트 \"\"=기본, 매니페스트 명시값이 프리셋을 이긴다")
def cf05(b: Box):
    cf = b.mod("comfyui_client")

    def target(d, minpx: int, cap: int | None = None):
        d.setdefault("output", {}).update(aspect_ratio="2:3", min_long_edge_px=minpx)
        ig = d.setdefault("image_generator", {})
        if cap is None:
            ig.pop("max_long_edge_px", None)
        else:
            ig["max_long_edge_px"] = cap

    with env_var("COMFYUI_URL", None), manifest_patch(b, lambda d: target(d, 1024)):
        plan = cf.size_plan()
        eq((plan["width"], plan["height"], plan["hires"]), (832, 1248, False), "2:3 · 최소 1024 → 1MP 캔버스 한 번")
        eq((plan["long"], plan["want"], plan["capped"]), (1248, 1024, False), "long/want/capped")
        eq((plan["cap"], plan["cap_is_default"]), (2048, True), "상한 기본값")
        eq((plan["base_width"], plan["base_height"]), (832, 1248), "기본 캔버스")
        eq(plan["source"], "output.min_long_edge_px", "요청 출처")
        eq(cf.size_warnings(plan), [], "깎이지 않았는데 경고")
        p2 = cf.size_plan(1536)
        eq((p2["source"], p2["hires"], p2["long"], p2["width"], p2["height"]),
           ("--long-edge", True, 1536, 1024, 1536), "--long-edge 요청 → hires")
        with manifest_patch(b, lambda d: target(d, 2250, 2560)):
            plan = cf.size_plan()
            eq(plan["hires"], True, "목표 2250 > 기본 1248 인데 hires 아님")
            ok(plan["long"] >= 2250, f"긴 변 {plan['long']} < 2250(A3 미달)")
            eq((plan["width"] % 8, plan["height"] % 8), (0, 0), "8의 배수 정렬")
            eq(plan["height"], plan["long"], "2:3 세로 — 긴 변은 높이")
            ok(plan["width"] < plan["height"], f"세로가 아님 {plan['width']}x{plan['height']}")
            eq((plan["base_width"], plan["base_height"]), (832, 1248), "hires 라도 1차는 1MP 캔버스")
            eq((plan["capped"], plan["cap"], plan["cap_is_default"]), (False, 2560, False), "상한 2560")
            eq(cf.size_warnings(plan), [], "깎이지 않았는데 경고")
        with manifest_patch(b, lambda d: target(d, 3600, 2048)):
            plan = cf.size_plan()
            eq((plan["long"], plan["capped"], plan["hires_capped"]), (2048, True, False), "공용 상한에 깎임")
            w = cf.size_warnings(plan)
            eq(len(w), 1, "절삭 경고 수")
            for needle in ("A3", "max_long_edge_px", "3600", "2048"):
                has(w[0], needle, "절삭 경고 내용")
        # hires 배수 상한 — 1248 기본 캔버스에서 3600 을 한 번에 재샘플하면(2400x3600 = 8.6MP) 12GB VRAM 이
        # 2차 KSampler 에서 OOM 으로 죽는다(VAEDecode 만 자동 타일링). 잘라 내고 무엇을 올릴지 말해야 한다.
        with manifest_patch(b, lambda d: target(d, 3600, 4096)):
            plan = cf.size_plan()
            eq((plan["long"], plan["hires"], plan["capped"], plan["hires_capped"], plan["hires_cap"]),
               (2496, True, True, True, 2496), f"hires 2배 상한이 걸리지 않음 — {plan}")
            eq((plan["width"], plan["height"]), (1664, 2496), "2배 상한 크기")
            ok(plan["width"] * plan["height"] <= 4_200_000,
               f"2차 KSampler 캔버스 {plan['width']}x{plan['height']} 가 4MP 를 크게 넘음")
            w = cf.size_warnings(plan)
            eq(len(w), 1, "hires 상한 경고 수")
            for needle in ("3600", "2496", "base_long_edge_px", "MakeFun", "A3"):
                has(w[0], needle, "hires 상한 경고 내용")
            hasnt(w[0], "max_long_edge_px", "공용 상한이 아닌데 max_long_edge_px 를 올리라고 함")
            p3 = cf.size_plan(3000)
            eq((p3["long"], p3["hires_capped"]), (2496, True), "--long-edge 도 hires 상한을 따른다")
            hasnt(cf.size_warnings(p3)[0], "A3", "--long-edge 요청에 A3 경고")
            with manifest_patch(b, lambda d: d["image_generator"]["comfyui"].__setitem__("base_long_edge_px", 1800)):
                plan = cf.size_plan()
                eq((plan["long"], plan["hires_capped"], plan["base_width"], plan["base_height"]),
                   (3600, False, 1200, 1800), "base_long_edge_px 를 올리면 3600 까지 hires 로 간다")
                eq(cf.size_warnings(plan), [], "상한 안인데 경고")
        with manifest_patch(b, lambda d: target(d, 1024, 99999)):
            eq(cf.size_plan()["cap"], cf.SIZE_HARD_MAX_PX, "하드 상한(4096)을 넘는 값이 그대로 쓰임")
        # 상한이 8의 배수가 아니면 실제 상한은 내림이다(2250 → 2248) — 그런데 "2250 이상으로
        # 올리세요" 라고 말하면 사용자는 **이미 그 값**이라 고칠 곳이 없고, 고쳐도 A3 는 계속 FAIL 한다.
        # 권고는 실행 가능해야 한다: 다음 8의 배수(2256)를 말하고, 그대로 올리면 실제로 통과해야 한다.
        with manifest_patch(b, lambda d: target(d, 2250, 2250)):
            plan = cf.size_plan()
            eq((plan["long"], plan["capped"], plan["hires_capped"]), (2248, True, False),
               f"8의 배수가 아닌 상한 — {plan}")
            w = cf.size_warnings(plan)[0]
            has(w, "2256", "권고 상한이 다음 8의 배수로 올라가지 않음(이미 설정된 값을 다시 권고)")
            hasnt(w, "2250 이상", "이미 적혀 있는 값을 올리라고 안내")
        with manifest_patch(b, lambda d: target(d, 2250, 2256)):
            p8 = cf.size_plan()
            ok(p8["long"] >= 2250, f"권고대로 올렸는데 여전히 A3 미달 — {p8}")
            eq(cf.size_warnings(p8), [], "권고대로 올렸는데 경고가 남음")
    # SCHEMA §1.4 는 이 두 값을 **누가 읽는지** 적는다 — size_plan 이 읽으므로 ComfyUI 도 그 칸에 있어야 한다
    doc = doc_text(b)
    ok("comfyui_client" in doc_field_row(doc, "`aspect_ratio`", "scene_brief"),
       "SCHEMA §1.4 aspect_ratio 의 '읽는 쪽' 에 comfyui_client 가 없음(size_plan 이 읽는다)")
    ok("comfyui_client" in doc_field_row(doc, "`min_long_edge_px`", "print_preflight"),
       "SCHEMA §1.4 min_long_edge_px 의 '읽는 쪽' 에 comfyui_client 가 없음(size_plan 이 읽는다)")
    # SCHEMA §1.3 comfyui 표 — 매니페스트로 덮을 수 있는 키는 전부 적혀 있어야 한다(코드가 정본)
    sec13 = doc_section(doc, "### 1.3")
    eq(sorted(k for k in cf.DEFAULTS if f"`{k}`" not in sec13), [],
       "comfyui 설정 키인데 SCHEMA §1.3 표에 없음(적히지 않은 키는 아무도 못 쓴다)")

    # 그래프 배선 — clip_skip 1 · 단일 패스
    s1 = dict(cf.DEFAULTS)
    plan1 = {"width": 832, "height": 1248, "base_width": 832, "base_height": 1248, "hires": False}
    g = cf.build_graph("pos", "neg", ckpt="x.safetensors", seed=11, s=s1, plan=plan1, name="SCENE-001")
    _graph_refs_ok(g)
    eq(sorted(g), ["3", "4", "5", "6", "7", "8", "9"], "단일 패스 노드 집합")
    eq(g["4"], {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}}, "체크포인트 노드")
    eq((g["6"]["inputs"]["clip"], g["7"]["inputs"]["clip"]), (["4", 1], ["4", 1]), "clip_skip 1 → CLIP 직결")
    eq((g["6"]["inputs"]["text"], g["7"]["inputs"]["text"]), ("pos", "neg"), "긍정/부정 텍스트")
    eq((g["5"]["inputs"]["width"], g["5"]["inputs"]["height"], g["5"]["inputs"]["batch_size"]),
       (832, 1248, 1), "빈 잠재 캔버스")
    k = g["3"]["inputs"]
    eq((k["seed"], k["steps"], k["cfg"], k["sampler_name"], k["scheduler"], k["denoise"]),
       (11, 30, 4.0, "dpmpp_2m", "karras", 1.0), "KSampler 기본값")
    eq((k["model"], k["positive"], k["negative"], k["latent_image"]),
       (["4", 0], ["6", 0], ["7", 0], ["5", 0]), "KSampler 배선")
    eq(g["8"]["inputs"], {"samples": ["3", 0], "vae": ["4", 2]}, "VAEDecode 배선")
    eq(g["9"]["inputs"], {"filename_prefix": "vn_studio/SCENE-001", "images": ["8", 0]}, "SaveImage")
    # clip_skip 2 · hires 2단
    s2 = {**cf.DEFAULTS, "clip_skip": 2, "hires_steps": 12, "hires_denoise": 0.35}
    plan2 = {"width": 1504, "height": 2256, "base_width": 832, "base_height": 1248, "hires": True}
    g2 = cf.build_graph("pos", "neg", ckpt="x", seed=11, s=s2, plan=plan2, name="a b/c!")
    _graph_refs_ok(g2)
    eq(sorted(g2, key=int), ["3", "4", "5", "6", "7", "8", "9", "10", "11", "12"], "hires 노드 집합")
    eq(g2["10"], {"class_type": "CLIPSetLastLayer", "inputs": {"stop_at_clip_layer": -2, "clip": ["4", 1]}},
       "CLIPSetLastLayer")
    eq((g2["6"]["inputs"]["clip"], g2["7"]["inputs"]["clip"]), (["10", 0], ["10", 0]), "clip_skip 2 → 텍스트 인코더가 10 을 본다")
    eq((g2["5"]["inputs"]["width"], g2["5"]["inputs"]["height"]), (832, 1248), "1차는 기본 캔버스")
    eq(g2["11"]["class_type"], "LatentUpscale", "업스케일 노드")
    eq(g2["11"]["inputs"], {"upscale_method": "bislerp", "width": 1504, "height": 2256,
                            "crop": "disabled", "samples": ["3", 0]}, "LatentUpscale 입력")
    k2 = g2["12"]["inputs"]
    eq((k2["latent_image"], k2["denoise"], k2["steps"], k2["seed"]), (["11", 0], 0.35, 12, 11),
       "2차 KSampler — 같은 시드·낮은 denoise")
    eq(g2["8"]["inputs"]["samples"], ["12", 0], "hires 면 VAEDecode 가 2차 결과를 받는다")
    ok(re.fullmatch(r"vn_studio/[A-Za-z0-9_-]+", g2["9"]["inputs"]["filename_prefix"]),
       f"파일 접두어에 위험 문자 — {g2['9']['inputs']['filename_prefix']!r}")
    raw = json.dumps(g2)
    ok("NaN" not in raw and "Infinity" not in raw, "그래프에 JSON 이 아닌 수")
    # 시드 범위 — KSampler 는 0 ~ 2**64-1 만 받는다. 넘는 값은 제출까지 간 뒤 400 으로 돌아오는데
    # 그때는 그래프 전체가 오류 본문이라 무엇이 문제였는지 화면에 남지 않는다. 만들 때 막는다.
    eq(cf.SEED_MAX, 2 ** 64 - 1, "KSampler 시드 상한")
    eq(cf.build_graph("p", "n", ckpt="x", seed=cf.SEED_MAX, s=s1, plan=plan1)["3"]["inputs"]["seed"],
       cf.SEED_MAX, "상한 시드가 그대로 실리지 않음")
    for bad in (cf.SEED_MAX + 1, -1, 2 ** 70, "abc"):
        e = raises(lambda bad=bad: cf.build_graph("p", "n", ckpt="x", seed=bad, s=s1, plan=plan1),
                   RuntimeError, f"범위 밖 시드 {bad!r} 가 그래프에 실림(제출 뒤에야 400)")
        has(str(e), "시드", "무엇이 문제인지")

    # 프리셋 — 매니페스트가 비운 항목만 채운다
    def silent(d):
        cu = d["image_generator"].setdefault("comfyui", {})
        for key in ("sampler", "scheduler", "cfg", "clip_skip", "prompt_prefix", "negative_prefix", "steps"):
            cu.pop(key, None)

    with manifest_patch(b, silent):
        s = cf.settings("waiIllustriousSDXL_v170.safetensors")
        eq((s["sampler"], s["scheduler"], s["cfg"], s["clip_skip"]), ("euler_ancestral", "normal", 6.0, 2),
           "Illustrious 프리셋")
        has(s["prompt_prefix"], "masterpiece", "프리셋 품질 접두어")
        has(s["negative_prefix"], "worst quality", "프리셋 부정 접두어")
        eq(s["steps"], 30, "프리셋이 건드리지 않는 항목은 기본값")
        eq(cf.preset("Illustrious-XL-v2.safetensors")["clip_skip"], 2, "이름 판별(illustrious)")
        eq(cf.preset("NoobAI-XL.safetensors")["cfg"], 6.0, "이름 판별(noobai)")
        eq(cf.preset("juggernautXL_ragnarok.safetensors"), {}, "포토리얼 체크포인트에 프리셋이 붙음")
        sj = cf.settings("juggernautXL_ragnarok.safetensors")
        eq((sj["sampler"], sj["scheduler"], sj["cfg"], sj["clip_skip"], sj["prompt_prefix"]),
           ("dpmpp_2m", "karras", 4.0, 1, ""), "기본 SDXL 설정")
        once = cf._with_prefix("medium shot, girl", s["prompt_prefix"])
        ok(once.lower().startswith("masterpiece"), f"접두어가 붙지 않음 — {once!r}")
        eq(cf._with_prefix(once, s["prompt_prefix"]), once, "접두어가 두 번 붙음(재호출 불변 아님)")
        neg = cf.negative_text(s, True)
        has(neg, "worst quality", "부정 접두어")
        eq(cf.negative_text(s, False), "", "negative=False 인데 부정 프롬프트가 남음")

    def explicit(d):
        silent(d)
        cu = d["image_generator"]["comfyui"]
        cu.update(cfg=5.5, sampler="dpmpp_2m_sde", steps=999, clip_skip="abc", negative_prompt="")

    with manifest_patch(b, explicit):
        s = cf.settings("waiIllustriousSDXL_v170.safetensors")
        eq((s["cfg"], s["sampler"]), (5.5, "dpmpp_2m_sde"), "매니페스트 명시값이 프리셋에 밀림")
        eq((s["scheduler"], s["clip_skip"]), ("normal", 2), "비워 둔 항목은 프리셋 그대로")
        eq(s["steps"], 30, "범위 밖(999) 값이 그대로 쓰임 — 기본값으로 떨어져야 한다")
        # negative_prompt "" 는 checkpoint "" 와 같은 뜻(기본값) — 배포 템플릿 세 벌이 전부 "" 라서, "" 가 '끔'이면
        # 모든 새 프로젝트가 글자·말풍선 억제 없이 렌더되고 --no-negative 는 뜻을 잃는다
        eq(s["negative_prompt"], cf.DEFAULTS["negative_prompt"], '"" 가 기본 부정 문구로 떨어지지 않음')
        neg = cf.negative_text(s, True)
        for needle in ("speech bubbles", "watermark", "worst quality"):
            has(neg, needle, "기본 부정 문구 + 프리셋 접두어")
        eq(cf.negative_text(s, False), "", "negative=False")
    for off in (False, "none", " OFF "):
        def switch(d, v=off):
            explicit(d)
            d["image_generator"]["comfyui"]["negative_prompt"] = v
        with manifest_patch(b, switch):
            s = cf.settings("waiIllustriousSDXL_v170.safetensors")
            eq(s["negative_prompt"], "", f"negative_prompt={off!r} 가 '끔'이 아님")
            neg = cf.negative_text(s, True)
            has(neg, "worst quality", "부정 프롬프트를 꺼도 프리셋 접두어는 남는다")
            hasnt(neg, "speech bubbles", "꺼도 기본 문구가 남음")
            ok(not neg.endswith((",", " ")), f"접두어만 남을 때 끝 쉼표·공백 — {neg!r}")
            eq(cf.negative_text(cf.settings("juggernautXL_ragnarok.safetensors"), True), "",
               "프리셋 없는 체크포인트에서 끔 = 빈 문자열")
    ok(cf.negative_off(False) and cf.negative_off("none") and not cf.negative_off("")
       and not cf.negative_off(None) and not cf.negative_off(True), "negative_off 판정")
    # 배포 매니페스트 세 벌 — 어느 것으로 시작해도 비-Illustrious 체크포인트에서 부정 문구가 비지 않는다
    for rel in ("templates/manifest.json", "examples/manifest.json", "project/manifest.json"):
        shipped = (read_json(SRC / rel).get("image_generator") or {}).get("comfyui")
        if shipped is None and rel.startswith("project/"):
            continue                                   # 사용자 매니페스트에 ComfyUI 블록이 없으면 볼 것이 없다
        ok(isinstance(shipped, dict), f"{rel} 에 image_generator.comfyui 블록이 없음")
        with manifest_patch(b, lambda d, blk=shipped: d["image_generator"].__setitem__("comfyui", dict(blk))):
            sj = cf.settings("juggernautXL_ragnarok.safetensors")
            has(cf.negative_text(sj, True), "speech bubbles", f"{rel} 그대로면 비-Illustrious 체크포인트의 부정 문구가 빈다")
            eq(cf.negative_text(sj, False), "", f"{rel} --no-negative")


@test("comfyui", "CF06 엔진 선택·설정 병합 — engine 없으면 MakeFun(구 매니페스트), 모르는 값은 MakeFun 폴백+로그, makefun 블록이 최상위를 덮는다")
def cf06(b: Box):
    """image_gen.active_engine 은 모르는 값을 **MakeFun 으로 떨어뜨리고 로그를 남긴다**(선택된 규칙:
    매니페스트 오타 하나로 스튜디오 전체가 뜨지 않는 것보다 예전 동작이 낫다). 반면 요청 body 로
    들어오는 엔진 이름(client(name))은 거절한다 — 사용자가 고른 값이 조용히 바뀌면 안 된다.
    """
    ig = b.mod("image_gen")
    mk = b.mod("makefun_client")
    cf = b.mod("comfyui_client")
    gc = b.mod("gen_common")
    err = ig.VNError
    eq(ig.active_engine({}), "makefun", "engine 없음 → MakeFun(구 매니페스트 호환)")
    eq(ig.active_engine({"image_generator": {"engine": "comfyui"}}), "comfyui", "engine comfyui")
    eq(ig.active_engine({"image_generator": {"engine": " ComfyUI "}}), "comfyui", "대소문자·공백 관용")
    eq(ig.active_engine({"image_generator": "broken"}), "makefun", "image_generator 가 dict 가 아님")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    ig.log.addHandler(handler)
    try:
        eq(ig.active_engine({"image_generator": {"engine": "dalle"}}), "makefun", "모르는 엔진 → MakeFun 폴백")
    finally:
        ig.log.removeHandler(handler)
    has(buf.getvalue(), "dalle", "모르는 엔진 값이 로그에 남지 않음(조용한 폴백)")
    # 같은 오타를 매번 경고하면 안 된다 — 이 함수는 webapp.state() 가 부르고 스튜디오가 주기적으로
    # 폴링한다. 오타 하나가 logs/webapp.log 를 같은 줄로 채우면 진짜 사고가 그 사이에 묻힌다.
    buf2 = io.StringIO()
    h2 = logging.StreamHandler(buf2)
    ig.log.addHandler(h2)
    try:
        for _ in range(5):
            eq(ig.active_engine({"image_generator": {"engine": "midjourney"}}), "makefun", "모르는 엔진 폴백")
        eq(ig.active_engine({"image_generator": {"engine": "stablehorde"}}), "makefun", "다른 오타도 폴백")
    finally:
        ig.log.removeHandler(h2)
    lines = [l for l in buf2.getvalue().splitlines() if l.strip()]
    eq(len([l for l in lines if "midjourney" in l]), 1,
       f"같은 값을 여러 번 경고(상태 폴링이 로그를 채운다) — {lines[:3]}")
    eq(len([l for l in lines if "stablehorde" in l]), 1, "값이 바뀌면 한 번은 말해야 한다")
    # 폴백의 방향 — 오타 하나가 **유료 엔진 호출**이 되지 않게. 옛 매니페스트(ComfyUI 블록
    # 없음)는 예전 그대로 MakeFun 으로 떨어지고(위 세 줄), 무료 엔진을 설정해 둔 작품에서는
    # 무료 쪽으로 떨어진다. `engien: "comfyui"` 같은 한 글자 오타가 과금이 되던 길이다.
    free = {"image_generator": {"comfyui": {"checkpoint": "x.safetensors"}}}
    eq(ig.active_engine(free), "comfyui", "ComfyUI 설정이 있는데 engine 없음 → 유료 폴백")
    eq(ig.active_engine({"image_generator": dict(free["image_generator"], engine="engien")}), "comfyui",
       "ComfyUI 설정이 있는데 오타 → 유료 폴백(과금)")
    eq(ig.active_engine({"image_generator": dict(free["image_generator"], engine="makefun")}), "makefun",
       "명시한 값은 언제나 이긴다 — 사용자가 고른 엔진이 조용히 바뀌면 안 된다")

    e = raises(lambda: ig.client("dalle"), err, "요청 body 의 모르는 엔진이 통과")
    has(str(e), "comfyui", "가능한 엔진 안내")
    ok(ig.client("comfyui") is ig.comfyui_client and ig.client("makefun") is ig.makefun_client, "client() 매핑")
    eq((ig.label("comfyui"), ig.label("makefun"), ig.label("")), ("ComfyUI", "MakeFun", ""), "라벨")
    eq(sorted(ig.ENGINES), ["comfyui", "makefun"], "ENGINES")
    eq(ig.configured_engines({"image_generator": {"engine": "comfyui", "comfyui": {}, "makefun": {}}}),
       ["comfyui", "makefun"], "두 블록 → 기본 엔진이 맨 앞")
    eq(ig.configured_engines({"image_generator": {"engine": "makefun", "comfyui": {"checkpoint": ""}, "makefun": {}}}),
       ["makefun", "comfyui"], "MakeFun 기본 + ComfyUI 보조")
    eq(ig.configured_engines({"image_generator": {"model": "a2e", "api": {"base_url": "https://makefun.ai"}}}),
       ["makefun"], "구 매니페스트 → MakeFun 하나")
    eq(ig.configured_engines({"image_generator": {"engine": "comfyui"}}), ["comfyui"], "ComfyUI 만")
    eq(ig.progress_text("comfyui", "생성", 12.4, "렌더 중"), "ComfyUI 생성 중… 12초 경과 · 렌더 중", "진행 문구")
    eq(ig.progress_text("makefun", "재수령", 3, ""), "MakeFun 재수령 중… 3초 경과 · 조회중", "상태 없을 때 기본 문구")
    # engine_info — 비밀값 없음 · url 은 host:port 만
    with env_var("COMFYUI_URL", None), env_var(mk.TOKEN_ENV, None):
        info = ig.engine_info(b.manifest())
        eq((info["engine"], info["billable"], info["mf_token"]), ("comfyui", False, False), "engine_info 기본")
        eq(info["url"], "127.0.0.1:8188", "url 은 host:port 만")
        eq(info["engines"], ["comfyui", "makefun"], "engines")
        eq(info["provider"], "ComfyUI", "provider 표기")
        ok(info["model"], "model 이 비어 있음")
    with env_var(mk.TOKEN_ENV, "selftest-token-value"):
        info = ig.engine_info({"image_generator": {"model": "a2e", "api": {"base_url": "https://makefun.ai"}}})
        eq((info["engine"], info["billable"], info["mf_token"], info["url"]),
           ("makefun", True, True, "makefun.ai"), "구 매니페스트 engine_info")
        hasnt(json.dumps(info), "selftest-token-value", "토큰 값이 state 로 새어 나감")
        h = ig.health("makefun")
        eq((h["ok"], h["billable"], h["checkpoints"]), (True, True, []), "MakeFun health = 토큰 유무만")
        hasnt(json.dumps(h), "selftest-token-value", "토큰 값이 health 로 새어 나감")
    # COMFYUI_URL 이 매니페스트를 이긴다 · 형식이 틀리면 VNError
    with env_var("COMFYUI_URL", "http://10.0.0.5:8188/"):
        eq(cf.base_url(), "http://10.0.0.5:8188", "환경변수 우선 + 끝 슬래시 정리")
    # basic-auth 리버스 프록시 주소(user:pw@) — 화면(state)·상태(health)·연결 오류 문구·--check 어디에도 비밀번호 0
    with env_var("COMFYUI_URL", "http://vn:secretpw@127.0.0.1:59996"):
        info = ig.engine_info(b.manifest())
        eq(info["url"], "127.0.0.1:59996", "url 에 userinfo 가 남음")
        hasnt(json.dumps(info), "secretpw", "프록시 비밀번호가 state 로 새어 나감")
        hd = ig.health("comfyui")
        eq(hd["ok"], False, "꺼진 주소인데 ok")
        hasnt(json.dumps(hd), "secretpw", "프록시 비밀번호가 health(연결 오류 문구)로 새어 나감")
        has(hd["detail"], "127.0.0.1:59996", "연결 오류 문구에 host:port")
        eq(cf.display_url(), "http://127.0.0.1:59996", "display_url")
        hasnt("\n".join(cf.check()["lines"]), "secretpw", "--check 출력에 비밀번호")
    eq(ig._netloc("https://u:p@[::1]:8188/x?y=1"), "[::1]:8188", "IPv6 host:port")
    eq(ig._netloc("not a url"), "", "주소가 아니면 빈 문자열")
    eq(b.mod("vn_core").host_port("http://a:b@h"), "h", "포트 없는 주소")
    with env_var("COMFYUI_URL", "ftp://x"):
        raises(cf.base_url, RuntimeError, "http(s) 가 아닌 주소가 통과")
    with env_var("COMFYUI_URL", None):
        eq(cf.base_url(), "http://127.0.0.1:8188", "매니페스트 주소")
        with manifest_patch(b, lambda d: d["image_generator"]["comfyui"]["api"].__setitem__("base_url", "http://192.168.0.9:8188")):
            eq(cf.base_url(), "http://192.168.0.9:8188", "매니페스트 comfyui.api.base_url 이 읽히지 않음")
    # makefun_client._cfg — 최상위 ⊕ makefun 블록(블록이 이김), comfyui 블록은 섞지 않는다
    cfg = mk._cfg()
    eq(cfg.get("model"), "a2e", "makefun.model 이 병합되지 않음")
    eq(cfg["api"]["base_url"], "https://makefun.ai", "makefun.api.base_url")
    eq(cfg["api"]["token_env"], mk.TOKEN_ENV, "makefun.api.token_env")
    ok("comfyui" not in cfg and "makefun" not in cfg, f"블록 자체가 남아 있음 — {sorted(cfg)}")
    eq(cfg.get("engine"), "comfyui", "공용 키(engine)가 병합에서 빠짐")
    eq(mk.base_url(), "https://makefun.ai", "base_url")

    def clash(d):
        top = d["image_generator"]
        top["model"] = "top-level"
        top["makefun"]["model"] = "sub-block"
        top["max_long_edge_px"] = 1600

    with manifest_patch(b, clash):
        c = mk._cfg()
        eq(c["model"], "sub-block", "makefun 블록이 최상위를 덮지 않음")
        eq(c["max_long_edge_px"], 1600, "최상위 공용 키가 사라짐")
        eq(mk._cap_px(), 1600, "MakeFun 상한이 공용 키를 보지 않음")
        eq(cf._cap_px(), 1600, "ComfyUI 상한이 공용 키를 보지 않음")

    def legacy(d):
        top = d["image_generator"]
        for key in ("makefun", "comfyui", "engine"):
            top.pop(key, None)
        top["model"] = "seedream-5.0-pro"
        top["api"] = {"base_url": "https://legacy.example", "token_env": mk.TOKEN_ENV}

    with manifest_patch(b, legacy):
        c = mk._cfg()
        eq(c["model"], "seedream-5.0-pro", "구 매니페스트 최상위 model 이 무시됨")
        eq(mk.base_url(), "https://legacy.example", "구 매니페스트 최상위 api 가 무시됨")
        eq(ig.active_engine(b.manifest()), "makefun", "구 매니페스트인데 MakeFun 이 아님")
        eq(ig.configured_engines(b.manifest()), ["makefun"], "구 매니페스트에 ComfyUI 가 끼어듦")
    # 결과형·메타 규약은 gen_common 한 벌 — 두 클라이언트가 같은 객체를 가리킨다
    ok(mk.GenResult is cf.GenResult, "두 클라이언트의 GenResult 가 다른 클래스")
    ok(mk.write_gen_meta is cf.write_gen_meta, "두 클라이언트의 write_gen_meta 가 다른 함수")
    eq((mk.META_NAME, cf.META_NAME), (gc.META_NAME, gc.META_NAME), "META_NAME")
    eq(mk.META_MAX_ENTRIES, gc.META_MAX_ENTRIES, "META_MAX_ENTRIES")
    r = gc.GenResult([Path("a.png")], warnings=["w"], task_ids=["t"])
    ok(isinstance(r, list) and len(r) == 1, "GenResult 는 list 여야 한다(gen_jobs 가 list 로 받는다)")
    eq((r.warnings, r.task_ids), (["w"], ["t"]), "GenResult 부가 정보")
    eq((cf.TOKEN_ENV, cf.ENGINE, cf.LABEL), ("", "comfyui", "ComfyUI"), "comfyui_client 상수")
    eq(cf.USAGE_LOG.name, "comfyui_usage.jsonl", "무료 대장 파일명")
    ok(cf.USAGE_LOG != mk.USAGE_LOG, "두 엔진의 대장이 같은 파일(과금 합산이 어긋난다)")


@test("comfyui", "CF07 웹 라우트 — /api/gen-image 가 image_gen 을 거쳐 엔진 이름이 든 진행 문구를 내고, 모르는 엔진은 거절 · /api/image-engine · /api/state.image")
def cf07(b: Box):
    """라우트는 in-process 로 부른다(W32·W33 과 같은 방식). 렌더는 모의 ComfyUI 가 받고,
    MakeFun 경로는 대역으로 갈아끼운다 — 네트워크로 나가는 유료 호출은 0회다.
    """
    wa, route = _route(b, "/api/gen-image", "이미지 생성을 웹에서 부를 수 없다")
    calls = func_calls(b, "webapp", route.__name__)
    ok(any(c.startswith("image_gen.") for c in calls), f"생성 라우트가 image_gen 을 거치지 않음 — {sorted(calls)}")
    for direct in ("makefun_client.", "comfyui_client."):
        ok(not any(c.startswith(direct) for c in calls),
           f"생성 라우트가 {direct}* 를 직접 부름(엔진 선택이 두 곳이 된다) — {sorted(calls)}")
    ok(any(c.startswith("gen_jobs.") for c in calls), "생성 라우트가 gen_jobs 관문을 지나지 않음")
    ok("threading.Thread" not in calls, "라우트가 스레드를 직접 띄움")
    cf = wa.image_gen.comfyui_client          # 라우트가 실제로 쓰는 인스턴스(b.mod 사본과 다르다)
    notes: list[str] = []
    real_note = wa.gen_jobs.note

    def spy(sid, message, running=True):
        notes.append(str(message))
        return real_note(sid, message, running)

    with comfy_mock(b, cf, delay_polls=2) as mock, cli_scene(b, "PROMPT") as sid, \
            patched(wa.gen_jobs, "note", spy), patched(cf, "POLL_SEC", 0.01):
        # (1) 모르는 엔진 → VNError · 선점 안 잡힘 · 서버 요청 0
        e = raises(lambda: route({"scene_id": sid, "n": 1, "engine": "bogus"}), RuntimeError, "모르는 엔진 통과")
        has(str(e), "엔진", "무엇이 틀렸는지")
        eq(wa.gen_jobs.status(sid)["running"], False, "거절됐는데 선점이 잡힘")
        eq(mock.prompts(), [], "거절됐는데 제출됨")
        # (2) engine 생략 = 매니페스트 기본(comfyui) · 동기 실행 → 등록·검사까지
        with quiet():
            out = route({"scene_id": sid, "n": 1, "sync": True})
        eq(out.get("auto"), "PASS", f"자동 검사 — {out}")
        eq(out.get("count"), 1, f"후보 수 — {out}")
        ok(all(str(n).startswith("cf_") for n in out.get("generated", [])), f"생성 파일 — {out.get('generated')}")
        sc = b.scene(sid)
        eq(sc["status"], "IMAGE", "등록 뒤 상태(고르기 전에는 시사 단계로 올리지 않는다)")
        eq(sc["prompt"]["external_generator"], "ComfyUI", "출처 기록")
        ok(any("ComfyUI 생성 중…" in n and "초 경과" in n for n in notes),
           f"진행 문구에 엔진 이름·경과가 없음 — {notes}")
        ok(any("ComfyUI" in n and "요청 중" in n for n in notes), f"요청 시작 문구 — {notes}")
        ok(not any("MakeFun" in n for n in notes), f"ComfyUI 경로인데 MakeFun 문구 — {notes}")
        eq(wa.gen_jobs.status(sid)["running"], False, "끝났는데 선점이 남음")
        # (3) engine 명시 · 백그라운드 — 즉시 응답의 문구에 엔진 라벨, 끝나면 완료
        notes.clear()
        with quiet():
            res = route({"scene_id": sid, "n": 1, "engine": "comfyui"})
            eq(res.get("started"), True, f"백그라운드 응답 — {res}")
            msg = _settle(wa, sid, 15)
        has(str(res.get("message", "")), "ComfyUI 생성 중", "즉시 응답 문구")
        has(msg, "완료", f"백그라운드 결과 문구 — {msg}")
        eq(len(b.scene(sid)["assets"]["raw_images"]), 2, "두 번째 렌더가 등록되지 않음")
        n_prompt = len(mock.prompts())
        # (4) makefun 을 고르면 MakeFun 경로(대역)로 간다 — ComfyUI 에는 아무것도 가지 않는다
        seen: list[tuple] = []

        def fake_mf(sid_, n=1, **kw):
            seen.append((sid_, n, sorted(kw)))
            out_ = b.root / "images" / "raw" / sid_ / "mf_fake00_1.png"
            write_png(out_, 832, 1248)
            return wa.makefun_client.GenResult([out_])

        with patched(wa.makefun_client, "generate_for_scene", fake_mf), \
                patched(wa.makefun_client, "_API", _NoNet("_API")), patched(wa.makefun_client, "_DL", _NoNet("_DL")),                 quiet():
            out2 = route({"scene_id": sid, "n": 1, "engine": "makefun", "sync": True})
        eq(len(seen), 1, "MakeFun 경로가 불리지 않음")
        eq((seen[0][0], seen[0][1]), (sid, 1), "MakeFun 호출 인자")
        ok("on_progress" in seen[0][2], "진행 콜백이 MakeFun 경로에 전달되지 않음")
        eq(out2.get("count"), 3, f"MakeFun 결과 등록 — {out2}")
        eq(len(mock.prompts()), n_prompt, "MakeFun 을 골랐는데 ComfyUI 에 제출됨")
        # (5) APPROVED 는 어느 엔진이든 거절(표준 문구)
    with comfy_mock(b, cf) as mock2, cli_scene(b, "APPROVED") as sid2:
        e = raises(lambda: route({"scene_id": sid2, "engine": "comfyui"}), RuntimeError, "APPROVED 인데 통과")
        has(str(e), "APPROVED", "승인 잠금 문구")
        eq(mock2.prompts(), [], "APPROVED 인데 제출됨")
        # (6) /api/image-engine — 모의 서버의 버전·체크포인트 · MakeFun 은 토큰 유무만(네트워크 0)
        wa2, health = _route(b, "/api/image-engine", "엔진 상태를 웹에서 볼 수 없다")
        h = health({"engine": "comfyui"})
        eq((h["engine"], h["ok"], h["billable"]), ("comfyui", True, False), f"ComfyUI health — {h}")
        eq(h["checkpoints"], list(COMFY_CKPTS), "체크포인트 목록")
        has(h["detail"], "0.35.0-mock", "서버 버전")
        has(h["detail"], mock2.url.split("//", 1)[1], "어느 주소인지")
        ok(h.get("model"), "model 비어 있음")
        eq(health({})["engine"], "comfyui", "engine 생략 → 매니페스트 기본")
        with env_var(wa.makefun_client.TOKEN_ENV, None), patched(wa.makefun_client, "_API", _NoNet("_API")):
            hm = health({"engine": "makefun"})
        eq((hm["engine"], hm["ok"], hm["billable"], hm["checkpoints"]), ("makefun", False, True, []), f"MakeFun health — {hm}")
        has(hm["detail"], wa.makefun_client.TOKEN_ENV, "무엇을 설정해야 하는지")
        raises(lambda: health({"engine": "bogus"}), RuntimeError, "모르는 엔진 상태 조회가 통과")
        with manifest_patch(b, lambda d: d["image_generator"]["comfyui"].__setitem__("checkpoint", "missing.safetensors")):
            hx = health({"engine": "comfyui"})
        eq(hx["ok"], False, "지정 체크포인트가 없는데 ok")
        has(hx["detail"], "missing.safetensors", "어느 체크포인트가 없는지")
        # (7) /api/state.image — 엔진·host:port·엔진 목록, mf_token 은 그대로 불리언
        st = wa.state()
        img = st.get("image")
        ok(isinstance(img, dict), f"state.image 가 없음 — {sorted(st)}")
        eq(img["engine"], "comfyui", "state.image.engine")
        eq(img["url"], mock2.url.split("//", 1)[1], "state.image.url 은 host:port 만")
        eq(img["engines"], ["comfyui", "makefun"], "state.image.engines")
        eq(img["billable"], False, "state.image.billable")
        ok(isinstance(st.get("mf_token"), bool), "mf_token 불리언이 사라짐(구 화면 호환)")
        eq(img["mf_token"], st["mf_token"], "image.mf_token ≠ mf_token")
    # 꺼진 서버 → ok=false + 연결 안내(크래시 아님)
    with env_var("COMFYUI_URL", DEAD_COMFY):
        hd = health({"engine": "comfyui"})
        eq(hd["ok"], False, "꺼진 서버인데 ok")
        has(hd["detail"], "연결", "연결 안내")


@test("comfyui", "CF08 doctor — '이미지 엔진' 절이 기본 엔진·응답·렌더 계획을 말하고, ComfyUI 가 꺼져 있어도 크래시 없이 경고로 안내한다")
def cf08(b: Box):
    env = dict(b.env)
    env["LOCAL_LLM_URL"] = "http://svc:secretpw@127.0.0.1:59997/v1"
    env["COMFYUI_URL"] = DEAD_COMFY.replace("http://", "http://vn:secretpw@")   # basic-auth 프록시 모양
    env.pop("MAKEFUN_API_TOKEN", None)

    def rows_of(out: str) -> tuple[dict, dict]:
        data, _n = json.JSONDecoder().raw_decode(out[out.index("{"):])
        return data, {(r["section"], r["name"]): r for r in data["results"]}

    rc, out = b.run("tools/doctor.py", "--json", env=env)
    hasnt(out, "Traceback", "traceback")
    ok(rc in (0, 1), f"rc={rc} — {out[:300]}")
    data, rows = rows_of(out)
    sec = {k[1]: r for k, r in rows.items() if k[0] == "이미지 엔진"}
    ok(sec, f"'이미지 엔진' 절이 없음 — 절: {sorted({k[0] for k in rows})}")
    ok("기본 엔진" in sec, f"기본 엔진 행 없음 — {sorted(sec)}")
    has(sec["기본 엔진"]["detail"], "ComfyUI", "기본 엔진 이름")
    has(sec["기본 엔진"]["detail"], "무료", "과금 여부")
    has(sec["기본 엔진"]["detail"], "MakeFun", "보조 엔진 표기")
    ok("ComfyUI 응답" in sec, f"응답 행 없음 — {sorted(sec)}")
    eq(sec["ComfyUI 응답"]["level"], "경고", "꺼진 ComfyUI 가 경고가 아님")
    has(sec["ComfyUI 응답"]["detail"], "연결", "연결 안내")
    has(sec["ComfyUI 응답"]["fix"], "comfyui_client.py --check", "고치는 방법")
    ok("렌더 계획" in sec, f"렌더 계획 행 없음 — {sorted(sec)}")
    has(sec["렌더 계획"]["detail"], "832x1248", "렌더 계획 크기")
    envs = {k[1]: r for k, r in rows.items() if k[0] == "환경변수"}
    tok = next((r for n, r in envs.items() if n.startswith("MAKEFUN_API_TOKEN")), None)
    ok(tok is not None, f"MAKEFUN_API_TOKEN 행 없음 — {sorted(envs)}")
    eq(tok["level"], "OK", "ComfyUI 가 기본인데 MakeFun 토큰 부재가 경고")
    ok("COMFYUI_URL" in envs, f"COMFYUI_URL 행 없음 — {sorted(envs)}")
    has(envs["COMFYUI_URL"]["detail"], "59996", "환경변수 주소(host:port)")
    has(envs["LOCAL_LLM_URL"]["detail"], "59997", "환경변수 주소(host:port)")
    hasnt(out, "selftest-token", "토큰 값")
    hasnt(out, "secretpw", "주소의 user:pw@ 가 진단(JSON)에 새어 나감")
    # 사람용 출력에도 절 제목과 엔진 이름이 보인다
    rc2, out2 = b.run("tools/doctor.py", env=env)
    hasnt(out2, "Traceback", "traceback(사람용)")
    hasnt(out2, "secretpw", "주소의 user:pw@ 가 진단(사람용)에 새어 나감")
    has(out2, "[이미지 엔진]", "절 제목")
    has(out2, "ComfyUI", "엔진 이름")
    # 기본 엔진이 MakeFun 인 매니페스트 → 토큰 행(경고) · ComfyUI 응답 행은 없다
    with manifest_patch(b, lambda d: d["image_generator"].__setitem__("engine", "makefun")):
        rc3, out3 = b.run("tools/doctor.py", "--json", env=env)
    hasnt(out3, "Traceback", "traceback(MakeFun)")
    _d3, rows3 = rows_of(out3)
    sec3 = {k[1]: r for k, r in rows3.items() if k[0] == "이미지 엔진"}
    has(sec3["기본 엔진"]["detail"], "MakeFun", "기본 엔진 MakeFun")
    has(sec3["기본 엔진"]["detail"], "유료", "과금 표기")
    ok("MakeFun 토큰" in sec3, f"토큰 행 없음 — {sorted(sec3)}")
    eq(sec3["MakeFun 토큰"]["level"], "경고", "토큰 없는 MakeFun 기본이 경고가 아님")
    ok("ComfyUI 응답" not in sec3, "MakeFun 기본인데 ComfyUI 를 두드림")
    envs3 = {k[1]: r for k, r in rows3.items() if k[0] == "환경변수"}
    tok3 = next((r for n, r in envs3.items() if n.startswith("MAKEFUN_API_TOKEN")), None)
    eq(tok3["level"], "경고", "MakeFun 기본인데 토큰 부재가 경고가 아님")


# ============================================================ 백업 · 복원
@contextlib.contextmanager
def bk_box(b: Box):
    """backup_project 를 저장소와 분리된 임시 트리에 붙인다.

    복원은 project/·images/ 를 통째로 되돌리는 파괴적 동작이라, 공용 샌드박스에서
    실행하면 다른 테스트의 상태를 덮어쓴다. ROOT/BACKUPS 를 갈아끼워 완전히 격리한다.
    """
    bpm = b.mod("backup_project")
    root = Path(tempfile.mkdtemp(prefix="bk-", dir=str(b.root.parent)))
    (root / "project" / "scenes").mkdir(parents=True)
    write_json(root / "project" / "manifest.json", {"project_id": "bk", "title": "백업 테스트"})
    write_json(root / "project" / "scenes" / "SCENE-001.json", {
        "scene_id": "SCENE-001", "scene_order": 1, "status": "APPROVED",
        "assets": {"raw_images": ["images/raw/SCENE-001/a.png"],
                   "selected_image": "images/raw/SCENE-001/a.png"}})
    write_png(root / "images" / "raw" / "SCENE-001" / "a.png", 60, 40)
    try:
        with patched(bpm, "ROOT", root), patched(bpm, "BACKUPS", root / "backups"):
            yield bpm, root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _tree_sums(root: Path) -> dict:
    import hashlib
    out = {}
    for top in ("project", "images"):
        base = root / top
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@test("backup", "B01 스냅샷 + sha256 무결성(변조 감지)")
def b01(b: Box):
    with bk_box(b) as (bpm, root), quiet():
        rc_snap = bpm.snapshot(dt.datetime(2026, 1, 1, 0, 0, 0))
        rc_ver = bpm.verify()
        mfp = root / "project" / "manifest.json"
        orig = mfp.read_text(encoding="utf-8")
        mfp.write_text(orig + "\n ", encoding="utf-8")
        rc_ver2 = bpm.verify()
        mfp.write_text(orig, encoding="utf-8")
        rc_ver3 = bpm.verify()
    eq(rc_snap, 0, "snapshot")
    eq(rc_ver, 0, "직후 verify")
    eq(rc_ver2, 1, "변조를 감지하지 못함")
    eq(rc_ver3, 0, "복구 후 verify")


@test("backup", "B02 왕복 — 스냅샷 → 변조·삭제 → restore → 원상 복구 일치")
def b02(b: Box):
    with bk_box(b) as (bpm, root), quiet() as log:
        before = _tree_sums(root)
        eq(bpm.snapshot(dt.datetime(2026, 2, 2, 3, 4, 5), with_images=True, images_scope="all"),
           0, "snapshot")
        (root / "project" / "manifest.json").write_text('{"project_id":"망가짐"}', encoding="utf-8")
        (root / "project" / "scenes" / "SCENE-001.json").unlink()
        (root / "images" / "raw" / "SCENE-001" / "a.png").write_bytes(b"not-a-png")
        extra = root / "project" / "scenes" / "SCENE-777.json"
        write_json(extra, {"scene_id": "SCENE-777"})
        rc = bpm.restore(assume_yes=True)
        after = _tree_sums(root)
    eq(rc, 0, f"restore rc — {log.getvalue()[-300:]}")
    for rel, sha in before.items():
        eq(after.get(rel), sha, f"복원 불일치 {rel}")
    ok("project/scenes/SCENE-777.json" in after, "스냅샷에 없던 파일을 임의로 지움")


@test("backup", "B03 악성 zip 멤버 차단(zip slip) — 저장소 밖·허용 밖 경로는 복원하지 않음")
def b03(b: Box):
    with bk_box(b) as (bpm, root), quiet():
        for bad in ("../evil.txt", "/etc/passwd", "C:/evil.txt", "project/../../evil.txt",
                    "tools/hack.py", "..\\evil.txt", "project/"):
            ok(bpm._safe_member(bad) is None, f"차단되지 않음: {bad}")
        ok(bpm._safe_member("project/scenes/SCENE-001.json") is not None, "정상 경로가 막힘")

        (root / "backups").mkdir(parents=True, exist_ok=True)
        zpath = root / "backups" / "project_99999999_000000.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("../evil.txt", "pwned")
            z.writestr("tools/hack.py", "pwned")
            z.writestr("project/manifest.json", '{"project_id":"bk","title":"복원본"}')
        _over, _new, _same, rejected = bpm._restore_plan(zpath)
        ok("../evil.txt" in rejected and "tools/hack.py" in rejected, f"거부 목록 {rejected}")
        rc = bpm.restore(stamp="99999999_000000", assume_yes=True, skip_backup=True)
        eq(rc, 0, "restore rc")
        ok(not (root.parent / "evil.txt").exists(), "상위 디렉터리에 파일이 생성됨")
        ok(not (root / "evil.txt").exists(), "저장소 루트에 파일이 생성됨")
        ok(not (root / "tools" / "hack.py").exists(), "허용 밖 폴더에 파일이 생성됨")
        has((root / "project" / "manifest.json").read_text(encoding="utf-8"), "복원본", "정상 멤버 복원")


@test("backup", "B04 prune(keep=N) 은 정확히 N 개만 남기고 복원전 보관본은 건드리지 않는다")
def b04(b: Box):
    with bk_box(b) as (bpm, root), quiet():
        for i in range(5):
            # force=True — 트리가 그대로면 2회차부터는 새 zip 을 굽지 않는다(B07).
            # 여기서 재려는 것은 '보존 개수' 하나이므로 5개를 실제로 만들어 둔다.
            bpm.snapshot(dt.datetime(2026, 3, 1 + i, 12, 0, 0), force=True)
        keeper = root / "backups" / "prerestore_20260101_000000.zip"
        keeper.write_bytes(b"PK-dummy")
        n_before = len(list((root / "backups").glob("manifest_*.json")))
        rc = bpm.prune(2, assume_yes=True)
        mans = sorted(p.name for p in (root / "backups").glob("manifest_*.json"))
        zips = sorted(p.name for p in (root / "backups").glob("project_*.zip"))
        eq(n_before, 5, "스냅샷 준비")
        eq(rc, 0, "prune rc")
        eq(len(mans), 2, f"남은 매니페스트 {mans}")
        eq(len(zips), 2, f"남은 zip {zips}")
        ok(mans[-1].endswith("20260305_120000.json"), f"최신본이 남지 않음 {mans}")
        ok(keeper.exists(), "복원 전 보관본(prerestore)이 삭제됨")


@test("backup", "B05 비대화형 restore 는 --yes 없이 진행하지 않는다")
def b05(b: Box):
    class _NotATty(io.StringIO):
        def isatty(self):
            return False

    with bk_box(b) as (bpm, root), quiet() as log:
        bpm.snapshot(dt.datetime(2026, 4, 4, 4, 4, 4), with_images=True, images_scope="all")
        mfp = root / "project" / "manifest.json"
        mfp.write_text('{"project_id":"변조본"}', encoding="utf-8")
        old_stdin = sys.stdin
        sys.stdin = _NotATty()
        try:
            rc = bpm.restore(assume_yes=False)
        finally:
            sys.stdin = old_stdin
        text = mfp.read_text(encoding="utf-8")
    eq(rc, 1, "확인 없이 복원이 진행됨")
    has(text, "변조본", "확인 없이 파일이 되돌려짐")
    has(log.getvalue(), "--yes", "안내 문구")


@test("backup", "B06 approved 스냅샷이 매니페스트가 약속한 것을 전부 담는다(_gen_meta 누락 없음)")
def b06(b: Box):
    """복원 직후 verify 가 **있지도 않은 '누락'** 을 뱉던 자리를 잠근다.

    매니페스트(_checksums)는 images/ 를 통째로 훑어 ``_gen_meta.json`` 까지 적는데
    기본 범위(approved)의 zip 은 장면 assets 에 적힌 PNG 만 담았다. 그래서 되살린 트리는
    항상 장면 수만큼 모자랐고(실측: 매니페스트 112 · zip 100 · 차이 12 = 장면 12개),
    verify 가 내미는 처방은 **같은 스냅샷을 다시 restore** 하는 것이라 무한 루프였다.

    B02 가 이것을 놓친 이유는 거기서 ``images_scope='all'`` 을 쓰기 때문이다 — 사람이
    실제로 쓰는 기본 경로(approved)는 아무도 왕복시켜 보지 않았다.
    """
    import json as _json
    with bk_box(b) as (bpm, root), quiet() as log:
        meta = root / "images" / "raw" / "SCENE-001" / bpm.vn_core.GEN_META_NAME
        write_json(meta, {"entries": [{"seed": 1}]})
        eq(bpm.snapshot(dt.datetime(2026, 5, 5, 5, 5, 5), with_images=True), 0, "snapshot")
        stamp = "20260505_050505"
        man = _json.loads((root / "backups" / f"manifest_{stamp}.json").read_text(encoding="utf-8"))
        promised = set(man["files"])
        import zipfile as _zip
        with _zip.ZipFile(root / "backups" / f"project_{stamp}.zip") as zf:
            packed = set(zf.namelist())
        shutil.rmtree(root / "images")
        rc_restore = bpm.restore(assume_yes=True)
        rc_verify = bpm.verify()
    ok("images/raw/SCENE-001/_gen_meta.json" in promised, "매니페스트가 _gen_meta 를 안 적었다")
    eq(sorted(promised - packed), [], "매니페스트가 약속했는데 zip 에 없는 파일")
    eq(rc_restore, 0, "restore")
    eq(rc_verify, 0, f"복원 직후 verify 가 누락을 보고함 — {log.getvalue()[-400:]}")


@test("backup", "B07 바뀐 것이 없으면 같은 zip 을 다시 굽지 않는다(중복 스냅샷)")
def b07(b: Box):
    """실측으로 잡힌 자리: project_20260915_075622.zip 과 082157.zip 이 **바이트 단위 동일**
    (sha256 3d361f37…, 112.9MB × 2)이었다. 백업이 둘이어도 복구력은 하나치인데 용량만 두 배다.

    세 가지를 함께 잠근다 — ① 같으면 생략하고 **있는 스냅샷을 이름으로 안내**한다,
    ② 생략된 회차에도 --dest 사본과 --force 는 사용자의 기대대로 동작한다,
    ③ **가벼운 스냅샷 뒤의 --with-images 는 생략되지 않는다**(생략하면 이미지가 든 백업이
      하나도 없는 상태가 조용히 유지된다).
    """
    with bk_box(b) as (bpm, root), quiet() as log:
        bk = root / "backups"
        eq(bpm.snapshot(dt.datetime(2026, 6, 1, 1, 0, 0), with_images=True), 0, "1회차")
        first = sorted(p.name for p in bk.glob("project_*.zip"))
        eq(bpm.snapshot(dt.datetime(2026, 6, 1, 2, 0, 0), with_images=True), 0, "2회차 rc")
        after = sorted(p.name for p in bk.glob("project_*.zip"))
        dest = root / "_dest"
        eq(bpm.snapshot(dt.datetime(2026, 6, 1, 3, 0, 0), with_images=True, dest=str(dest)),
           0, "생략 회차의 --dest rc")
        eq(bpm.snapshot(dt.datetime(2026, 6, 1, 4, 0, 0), with_images=True, force=True),
           0, "--force rc")
        forced = sorted(p.name for p in bk.glob("project_*.zip"))
        (root / "project" / "scenes" / "SCENE-001.json").write_text(
            '{"scene_id":"SCENE-001","status":"APPROVED"}', encoding="utf-8")
        eq(bpm.snapshot(dt.datetime(2026, 6, 1, 5, 0, 0), with_images=True), 0, "변경 후 rc")
        changed = sorted(p.name for p in bk.glob("project_*.zip"))
        copied = sorted(p.name for p in dest.glob("*")) if dest.exists() else []
        text = log.getvalue()
    eq(len(first), 1, f"1회차 zip {first}")
    eq(after, first, f"바뀐 것이 없는데 zip 이 새로 구워짐 — {after}")
    has(text, "백업 생략", "생략 사실을 말하지 않음")
    has(text, first[0].replace(".zip", ""), "생략하면서 기존 스냅샷 이름을 안내하지 않음")
    ok(first[0] in copied, f"생략된 회차에 외부 사본이 빠짐 — {copied}")
    eq(len(forced), 2, f"--force 가 새 zip 을 굽지 않음 — {forced}")
    eq(len(changed), 3, f"내용이 바뀌었는데 새 zip 이 없음 — {changed}")

    # ③ 가벼운 스냅샷(project 만) 다음의 --with-images 는 담는 것이 다르므로 생략 금지
    with bk_box(b) as (bpm, root), quiet():
        eq(bpm.snapshot(dt.datetime(2026, 6, 2, 1, 0, 0)), 0, "가벼운 1회차")
        eq(bpm.snapshot(dt.datetime(2026, 6, 2, 2, 0, 0), with_images=True), 0, "이미지 포함 2회차")
        zips = sorted(p.name for p in (root / "backups").glob("project_*.zip"))
        mans = sorted((root / "backups").glob("manifest_*.json"))
        with_img = json.loads(mans[-1].read_text(encoding="utf-8")).get("images_included")
    eq(len(zips), 2, f"이미지 든 스냅샷이 가벼운 스냅샷 때문에 생략됨 — {zips}")
    eq(with_img, True, "두 번째 스냅샷이 이미지를 담지 않았다")


@test("backup", "B08 prune — 이미지 든 스냅샷은 따로(짧게) 세고, 최신 이미지 스냅샷은 남긴다")
def b08(b: Box):
    """상한이 하나뿐이면 기본값 12 가 '23KB zip 열둘' 과 '118MB zip 열둘'(1.4GB)을 같은 말로
    다룬다. 무거운 쪽만 따로 세되, **되돌릴 수 있는 유일한 종류의 백업**이 0개가 되는 일은
    어떤 상한에서도 없어야 한다.
    """
    def heavy_of(bk):
        return [m.name for m in sorted(bk.glob("manifest_*.json"))
                if json.loads(m.read_text(encoding="utf-8")).get("images_included")]

    with bk_box(b) as (bpm, root), quiet() as log:
        bk = root / "backups"
        for i in range(3):
            bpm.snapshot(dt.datetime(2026, 7, 1 + i, 9, 0, 0), force=True)
            bpm.snapshot(dt.datetime(2026, 7, 1 + i, 10, 0, 0), with_images=True, force=True)
        n_all, n_heavy = len(list(bk.glob("manifest_*.json"))), len(heavy_of(bk))
        rc_noop = bpm.prune(12, assume_yes=True)                 # 기본값은 아무것도 지우지 않는다
        kept_noop = len(list(bk.glob("manifest_*.json")))
        rc = bpm.prune(6, keep_images=1, assume_yes=True)         # 전체는 다 남기되 무거운 쪽만 1개
        left = sorted(m.name for m in bk.glob("manifest_*.json"))
        heavy_left = heavy_of(bk)
        zips_left = sorted(p.name for p in bk.glob("project_*.zip"))
        text = log.getvalue()
    eq((n_all, n_heavy), (6, 3), "스냅샷 준비")
    eq(rc_noop, 0, "기본 prune rc")
    eq(kept_noop, 6, "기본값(--keep 12 · --keep-images 3)이 사용자 백업을 지웠다")
    eq(rc, 0, "prune rc")
    eq(len(left), 4, f"무거운 쪽만 줄어야 한다 — {left}")
    eq(len(heavy_left), 1, f"이미지 스냅샷 상한이 듣지 않음 — {heavy_left}")
    eq(len(zips_left), 4, f"매니페스트와 zip 이 짝이 맞지 않음 — {zips_left}")
    has(text, "이미지 포함", "무엇을 지우는지(이미지 포함 여부) 말하지 않음")

    # 안전장치 — 상한이 1이라도 '이미지가 든 최신 스냅샷' 은 남는다
    with bk_box(b) as (bpm, root), quiet():
        bk = root / "backups"
        bpm.snapshot(dt.datetime(2026, 8, 1, 9, 0, 0), with_images=True, force=True)
        bpm.snapshot(dt.datetime(2026, 8, 2, 9, 0, 0), force=True)
        eq(bpm.prune(1, keep_images=1, assume_yes=True), 0, "prune rc")
        left2 = sorted(m.name for m in bk.glob("manifest_*.json"))
        heavy2 = heavy_of(bk)
    eq(len(left2), 2, f"최신 스냅샷과 이미지 스냅샷이 함께 남아야 한다 — {left2}")
    eq(len(heavy2), 1, "이미지가 든 유일한 스냅샷이 지워졌다")


@test("backup", "B09 개인 대화 기록은 백업에 담기지 않는다(옵트인 · 외부 사본 확인)")
def b09(b: Box):
    """백업의 --dest 는 **클라우드 동기화 폴더**를 겨냥해 만들어진 옵션이다(런북의 표준 명령이
    D:/backup 을 쓴다). _project_files 가 project/ 를 통째로 담던 시절에는 그 한 줄이
    인물과 나눈 사적 대화를 제3자 서버로 올렸다 — 지금까지 잠재적 위험이었던 이유는
    로컬 LLM 이 한 번도 안 돌아 그 파일이 아직 없었기 때문일 뿐이다.

    픽스처로 넷을 다 만들어 두고 네 가지를 잠근다.
      ① 기본 스냅샷은 zip 에도 **체크섬 매니페스트에도** 사적 기록을 넣지 않는다.
      ② 그런데도 verify 는 0 이다 — 빠진 것을 '누락' 으로 뱉으면 사용자는 백업이 깨진 줄 안다.
      ③ --include-private 면 담는다(사용자가 명시했을 때만).
      ④ --include-private + --dest 인데 확인을 못 받으면 **사적 기록만 빼고** 백업은 계속한다.
    """
    class _NotATty(io.StringIO):
        def isatty(self):
            return False

    names = ("chatlog.json", "talk_CHAR-001.json", "talk_CHAR-001.archive.jsonl",
             "memory_CHAR-001.json")
    with bk_box(b) as (bpm, root), quiet() as log:
        bk, story = root / "backups", root / "project" / "story"
        story.mkdir(parents=True, exist_ok=True)
        for n in names:
            (story / n).write_text('{"사적":"대화"}', encoding="utf-8")
        (story / "storyline.md").write_text("공개 줄거리", encoding="utf-8")
        dest = root / "_dest"

        eq(bpm.snapshot(dt.datetime(2026, 9, 9, 1, 0, 0), with_images=True, dest=str(dest)),
           0, "기본 스냅샷 rc")
        stamp = "20260909_010000"
        man = json.loads((bk / f"manifest_{stamp}.json").read_text(encoding="utf-8"))
        with zipfile.ZipFile(bk / f"project_{stamp}.zip") as zf:
            packed = set(zf.namelist())
        promised = set(man["files"])
        rc_ver = bpm.verify()
        copied = sorted(p.name for p in dest.glob("*")) if dest.exists() else []

        eq(bpm.snapshot(dt.datetime(2026, 9, 9, 2, 0, 0), with_images=True,
                        include_private=True), 0, "옵트인 rc")
        stamp2 = "20260909_020000"
        with zipfile.ZipFile(bk / f"project_{stamp2}.zip") as zf:
            packed2 = set(zf.namelist())
        promised2 = set(json.loads((bk / f"manifest_{stamp2}.json").read_text(encoding="utf-8"))["files"])
        rc_ver2 = bpm.verify()

        old_stdin = sys.stdin                        # 비대화형(예약 실행)에서의 확인 요구
        sys.stdin = _NotATty()
        try:
            rc3 = bpm.snapshot(dt.datetime(2026, 9, 9, 3, 0, 0), with_images=True,
                               include_private=True, dest=str(root / "_dest2"), force=True)
        finally:
            sys.stdin = old_stdin
        with zipfile.ZipFile(bk / "project_20260909_030000.zip") as zf:
            packed3 = set(zf.namelist())
        text = log.getvalue()

    priv = [f"project/story/{n}" for n in names]
    eq([r for r in priv if r in packed], [], "기본 스냅샷 zip 에 사적 대화가 담김")
    eq([r for r in priv if r in promised], [], "체크섬 매니페스트가 사적 대화를 적었다")
    ok("project/story/storyline.md" in packed, "공개 스토리 파일까지 빠졌다")
    eq(man.get("private_skipped"), 4, f"제외 개수를 매니페스트가 적지 않음 — {man.get('private_skipped')}")
    eq(rc_ver, 0, f"사적 기록을 뺀 스냅샷의 verify 가 이상을 보고함 — {text[-400:]}")
    has(text, "개인 대화 기록", "무엇을 뺐는지 말하지 않음")
    eq(copied, sorted([f"manifest_{stamp}.json", f"project_{stamp}.zip"]), f"외부 사본 {copied}")

    eq(sorted(r for r in priv if r in packed2), sorted(priv), "--include-private 인데 안 담김")
    eq(sorted(r for r in priv if r in promised2), sorted(priv), "--include-private 인데 매니페스트에 없음")
    eq(rc_ver2, 0, "사적 기록을 담은 스냅샷의 verify 가 이상을 보고함")

    eq(rc3, 0, "확인 불가일 때 백업 자체가 멈췄다 — 작품까지 백업되지 않는다")
    eq([r for r in priv if r in packed3], [], "확인 없이 사적 대화가 외부 사본으로 나갔다")
    has(text, "빼고 나머지만 백업", "무엇을 대신 했는지 말하지 않음")


# ============================================================ 인화(print)
@test("print", "PR01 인화 프리플라이트 규격 판정 + 최대규격(면적) + CLI 무크래시")
def pr01(b: Box):
    pfm = b.mod("print_preflight")
    hi = pfm.preflight_image(1200, 1800, 300)    # 4×6 을 정확히 300DPI 로 채움
    lo = pfm.preflight_image(1000, 1400, 300)    # 엽서도 미달
    mx = pfm.preflight_image(2500, 3200, 300)    # 8×10 통과 → 면적 최대 규격
    eq(hi["printable"], True, "4×6 판정")
    eq(hi["rows"][0]["dpi"], 300, "DPI 계산")
    eq(lo["printable"], False, "미달 판정")
    eq(mx["max_size_at_target"], "8×10", "최대 규격(면적 기준)")
    rc, out = b.run("tools/print_preflight.py", "--all")
    eq(rc, 0, f"CLI rc — {out[:200]}")
    has(out, "인화 프리플라이트", "CLI 출력")
    hasnt(out, "Traceback", "traceback")


@test("print", "PR02 인화 마스터(규격·DPI 메타·업스케일·가로회전·규격검증·경로차단)")
def pr02(b: Box):
    try:
        from PIL import Image as PImg
    except Exception:
        raise Skip("Pillow 미설치")
    pem = b.mod("print_export")
    out = b.root / "_pe_out"
    with patched(pem, "OUT", out):
        big, sml, land = b.root / "pe_big.png", b.root / "pe_small.png", b.root / "pe_land.png"
        write_png(big, 1600, 2400)     # 세로, 5×7 비업스케일
        write_png(sml, 1000, 1500)     # 업스케일 필요
        write_png(land, 3000, 2000)    # 가로 → 규격 회전
        sb = pem.export_one("SCENE-BIG", big, 5.0, 7.0, 300, 0.0, "center")
        ss = pem.export_one("SCENE-SM", sml, 5.0, 7.0, 300, 0.0, "center")
        sl = pem.export_one("SCENE-LAND", land, 5.0, 7.0, 300, 0.0, "center")
        with PImg.open(b.root / sb["tiff"]) as im:
            eq(im.size, (1500, 2100), "TIFF 픽셀")
            eq(im.info.get("dpi"), (300, 300), "DPI 메타")
        raises(lambda: pem.parse_size("-4x6"), SystemExit, "음수 규격")
        pem.export_one("../../evil", big, 5.0, 7.0, 300, 0.0, "center")
        ok((out / "5x7" / "evil.tiff").exists(), "경로 정규화 실패")
        ok(not (b.root / "evil.tiff").exists(), "scene_id 경로 탈출")
    eq(sb["out_px"], [1500, 2100], "출력 픽셀")
    eq(sb["upscaled"], False, "업스케일 오판")
    eq(ss["upscaled"], True, "업스케일 미탐")
    eq(sl["out_px"], [2100, 1500], "가로 규격 회전")
    eq(sb["eff_dpi_src"], 320, "eff_dpi_src")
    shutil.rmtree(out, ignore_errors=True)


def _apply_edits(b: Box, edits) -> None:
    """size_recipe 가 돌려준 (매니페스트 경로, 값) 을 **그 경로 그대로** 적용한다.

    조치를 화면에 찍기만 하고 아무도 적용해 보지 않으면, 존재하지 않는 자리를 가리키는 안내가
    조용히 산다. 마지막 조각(잎)은 새로 생길 수 있지만(max_long_edge_px 는 기본 매니페스트에
    없다) **그 위 블록은 실제로 있어야 한다** — 틀린 잎 이름은 적용 뒤 크기 검증이 잡는다.
    """
    def fix(d):
        for path, val in edits:
            node, parts = d, str(path).split(".")
            for k in parts[:-1]:
                ok(isinstance(node.get(k), dict), f"매니페스트에 없는 경로 조각 '{k}' ({path})")
                node = node[k]
            node[parts[-1]] = val
    edit_json(b.p("project/manifest.json"), fix)


@test("print", "PR03 인화 목표 → 매니페스트 조치는 '그대로 적으면 실제로 되는' 값이어야 한다(8의 배수·hires 2배 상한)")
def pr03(b: Box):
    """"더 크게 생성하세요" 는 **어느 값을 얼마로** 까지 말해야 조언이다.

    이 자리는 두 번 틀렸다.
      * 상한은 8의 배수로 **내려** 잘리는데 요청값을 그대로 권했다(2250 → 실제 2248 → A3 계속 FAIL).
      * ComfyUI 의 hires 2배 상한(1248 → 2496px)을 몰라서 8×10(3600px)에도
        max_long_edge_px 만 올리라고 했다 — 올려도 2496px 이 나온다. 사용자는 렌더를 다 돌린
        뒤에야 그 사실을 안다.
    그래서 상한을 아는 곳(클라이언트 size_recipe)이 조치를 만들고, 인화 도구는 옮기기만 한다.
    여기서는 **조치를 실제로 적용해 보고** 그 다음에도 깎이는지 확인한다 — 말만 바꾸고 결과가
    같으면 통과하지 못한다.
    """
    cf = b.mod("comfyui_client")
    pfm = b.mod("print_preflight")

    def target(d, minpx):
        d.setdefault("output", {}).update(aspect_ratio="2:3", min_long_edge_px=minpx)
        d.setdefault("image_generator", {}).pop("max_long_edge_px", None)

    # 인화 규격이 요구하는 픽셀은 프리플라이트가 정본이다(두 도구가 다른 수를 말하면 안 된다)
    eq(pfm.needed_px("엽서 4×6")[1], 1800, "4×6 @300DPI 필요 긴 변")
    eq(pfm.needed_px("5×7")[1], 2250, "5×7 @300DPI 필요 긴 변")
    eq(pfm.needed_px("8×10")[1], 3600, "8×10 @300DPI 필요 긴 변")
    eq(pfm.needed_px_for(5.0, 7.0, 300), pfm.needed_px("5×7"), "프리셋/자유 규격 산수가 갈림")

    with env_var("COMFYUI_URL", None), manifest_patch(b, lambda d: target(d, 1024)):
        r4, r5, r8 = (cf.size_recipe(1800), cf.size_recipe(2250), cf.size_recipe(3600))
        for r, name in ((r4, "4×6"), (r5, "5×7"), (r8, "8×10")):
            eq(r["reachable"], False, f"{name}: 지금 설정으로 된다고 판정")
            eq(r["feasible"], True, f"{name}: 하드 상한 안인데 불가 판정")
        eq(dict(r4["edits"]), {"output.min_long_edge_px": 1800},
           f"4×6 은 요청 크기만 올리면 된다(기본 상한 2048·hires 천장 2496 안) — {r4['edits']}")
        eq(dict(r5["edits"]).get("image_generator.max_long_edge_px"), 2256,
           f"5×7 상한 권고가 8의 배수가 아님(2250 은 2248 로 깎인다) — {r5['edits']}")
        eq(r5["hires_note"], "", "5×7 은 hires 천장(2496) 안인데 1차 캔버스를 올리라고 함")
        keys8 = [k for k, _v in r8["edits"]]
        ok("image_generator.comfyui.base_long_edge_px" in keys8,
           f"8×10 인데 hires 2배 상한(1차 캔버스)을 말하지 않음 — {keys8}")
        has(r8["hires_note"], "2496", "hires 천장 픽셀을 말하지 않음")
        # 인화 도구는 그 조치를 그대로 옮긴다(규칙을 다시 구현하지 않는다)
        lines = "\n".join(pfm.recipe_lines(3600, ("ComfyUI", cf)))
        for needle in ("output.min_long_edge_px = 3600", "base_long_edge_px", "2496"):
            has(lines, needle, "프리플라이트가 옮긴 조치")
        eq(pfm.recipe_lines(3600, None), [], "엔진이 없는데 조치를 지어냄")

        # 조치를 **그대로 적용**하면 실제로 그 크기가 나와야 한다 — 이것이 이 테스트의 핵심이다
        _apply_edits(b, r8["edits"])
        plan = cf.size_plan()
        eq((plan["long"], plan["capped"], plan["hires_capped"]), (3600, False, False),
           f"권고대로 고쳤는데 여전히 깎인다 — {plan}")
        eq(cf.size_warnings(plan), [], "권고대로 고쳤는데 경고가 남음")
        eq(cf.size_recipe(3600)["reachable"], True, "고친 뒤에도 '조치 필요' 로 남음")

    # MakeFun 도 같은 계약을 낸다(엔진을 모르는 호출부가 그대로 옮겨 적을 수 있어야 한다)
    mk = b.mod("makefun_client")
    with manifest_patch(b, lambda d: target(d, 1024)):
        rm = mk.size_recipe(2250)
        eq(sorted(rm), sorted(cf.size_recipe(2250)), f"두 클라이언트의 size_recipe 키가 다름 — {rm}")
        eq(dict(rm["edits"]).get("image_generator.max_long_edge_px"), 2256, f"8의 배수 권고 — {rm}")
        eq(rm["hires_note"], "", "MakeFun 에는 hires 상한이 없다")


@test("print", "PR04 doctor 의 크기 조치가 제자리로 돌려보내지 않는다 + 인화 가능 규격을 말한다")
def pr04(b: Box):
    """doctor 는 판정을 클라이언트에 위임해 놓고 **조치 문구만 따로 지어 냈다.** 그 문구가
    사용자를 두 번 제자리로 보냈다: 이미 3600 인 max_long_edge_px 를 "3600 이상으로 올리세요"
    (진짜 막은 건 hires 2배 상한), 그리고 이미 2250 인 상한을 "2250 이상으로"(실제 2248).
    시키는 대로 고치고 다시 렌더해도 같은 화면이 나오는 조치는 조치가 아니다.

    함께: 인화는 이 제품의 절반인데 doctor 는 화면 기준(A3)만 봤다 — 832×1248 은 A3 를 통과하고
    감상도 멀쩡하지만 300DPI 로는 엽서에도 못 미친다. 그 사실을 굽기 전에 말해야 한다.
    """
    env = dict(b.env)
    env["COMFYUI_URL"] = DEAD_COMFY          # 상한 계산은 매니페스트만 보면 된다(네트워크 없이)
    env["LOCAL_LLM_URL"] = "http://127.0.0.1:59997/v1"      # 꺼진 포트 — 진단이 기다리지 않게

    def rows_of(out: str) -> dict:
        data, _n = json.JSONDecoder().raw_decode(out[out.index("{"):])
        return {(r["section"], r["name"]): r for r in data["results"]}

    def target(d, minpx, cap):
        d.setdefault("output", {}).update(aspect_ratio="2:3", min_long_edge_px=minpx)
        d.setdefault("image_generator", {})["max_long_edge_px"] = cap

    # 1) hires 2배 상한에 걸린 경우 — 막은 값의 이름을 대야 한다
    with manifest_patch(b, lambda d: target(d, 3600, 3600)):
        rc, out = b.run("tools/doctor.py", "--json", env=env)
    hasnt(out, "Traceback", "traceback")
    ok(rc in (0, 1), f"rc={rc} — {out[:200]}")
    row = rows_of(out).get(("프로젝트", "생성 크기 상한"))
    ok(row is not None, "'생성 크기 상한' 행이 없음")
    eq(row["level"], "문제", f"상한에 깎였는데 문제가 아님 — {row}")
    has(row["fix"], "base_long_edge_px", "hires 상한에 걸렸는데 1차 캔버스를 말하지 않음")
    hasnt(row["fix"], "max_long_edge_px 를 3600", "이미 3600 인 값을 올리라고 함(제자리 조치)")

    # 2) 상한이 8의 배수가 아닌 경우 — 다음 8의 배수를 말해야 한다
    with manifest_patch(b, lambda d: target(d, 2250, 2250)):
        rc2, out2 = b.run("tools/doctor.py", "--json", env=env)
    hasnt(out2, "Traceback", "traceback(8의 배수)")
    row2 = rows_of(out2).get(("프로젝트", "생성 크기 상한"))
    has(row2["fix"], "2256", "다음 8의 배수를 말하지 않음")
    hasnt(row2["fix"], "2250 이상", "이미 적혀 있는 값을 다시 올리라고 함")

    # 3) 기본 설정 — 인화로는 엽서에도 못 미친다는 사실을 doctor 가 말한다
    rc3, out3 = b.run("tools/doctor.py", "--json", env=env)
    hasnt(out3, "Traceback", "traceback(기본)")
    row3 = rows_of(out3).get(("프로젝트", "인화 가능 규격"))
    ok(row3 is not None, "'인화 가능 규격' 행이 없음 — 인화는 이 제품의 절반이다")
    has(row3["detail"], "300DPI", "목표 DPI 를 말하지 않음")
    has(row3["fix"] + row3["detail"], "min_long_edge_px", "무엇을 올려야 하는지 말하지 않음")


@test("print", "PR07 실효 DPI 하한 — 인화소에 보내면 안 되는 규격은 마스터를 굽지 않는다")
def pr07(b: Box):
    """실측: 이 앨범의 원본(832×1248)을 8×10 에 앉히면 104DPI 다. 예전에는 ⚠ 한 줄과 함께
    구웠고, 나온 파일은 2400×3000px 라 **파일만 보면 멀쩡했다** — 인화소도 거절하지 않는다.
    뭉개졌다는 사실은 인화비를 쓴 뒤에 도착한다(실측: output/print 의 121MB 가 그 8×10 이었다).

    막되 **과하게 막지 않는 것**이 조건이다. 4×6 208DPI 까지 거부하면 이 앨범은 아무것도
    뽑을 수 없다 — 그래서 하한은 240(감상 하한)이 아니라 150 이고, 판정하는 도구와 굽는
    도구가 vn_core 의 같은 수를 본다.
    """
    pfm, pem, vc = b.mod("print_preflight"), b.mod("print_export"), b.mod("vn_core")
    eq(pfm.DPI_FLOOR, vc.PRINT_DPI_FLOOR, "판정 도구의 하한이 vn_core 와 다름")
    eq(pem.DPI_FLOOR, vc.PRINT_DPI_FLOOR, "굽는 도구의 하한이 vn_core 와 다름 — 판정과 굽기가 갈린다")
    eq(pfm.grade(vc.PRINT_DPI_FLOOR - 1, 300), "인화불가", "하한 바로 아래")
    eq(pfm.grade(vc.PRINT_DPI_FLOOR, 300), "업스케일필요", "하한 값 자체는 통과해야 한다")
    eq(pfm.grade(240, 300), "보통", "기존 등급이 바뀌었다")
    eq(pfm.grade(300, 300), "좋음", "기존 등급이 바뀌었다")

    rep = pfm.preflight_image(832, 1248, 300)          # 이 앨범의 실제 원본 크기
    rows = {r["size"]: r for r in rep["rows"]}
    eq(rows["8×10"]["dpi"], 104, "8×10 실효 DPI")
    eq(rows["8×10"]["grade"], "인화불가", "8×10 104DPI 가 막히지 않는다")
    eq(rows["엽서 4×6"]["grade"], "업스케일필요",
       "4×6 208DPI 까지 막으면 이 앨범은 아무 규격도 뽑을 수 없다")
    ok("8×10" in (rep.get("blocked") or []), f"blocked 목록 — {rep.get('blocked')}")
    eq(rep.get("floor_dpi"), vc.PRINT_DPI_FLOOR, "보고서가 하한을 싣지 않음")

    # 거부 자체는 **Pillow 없이도** 동작해야 한다 — 돈이 나가는 것을 막는 관문이 선택
    # 의존성에 딸려 가면, 그 의존성이 없는 PC 에서만 조용히 열린다(크기는 헤더로 읽는다).
    try:
        from PIL import Image as _PImg            # noqa: F401
        have_pil = True
    except Exception:
        have_pil = False
    out = b.root / "_pe_floor"
    msgs: list[str] = []
    with approved_scene(b) as sid, patched(pem, "OUT", out):
        write_png(b.root / f"images/raw/{sid}/v.png", 832, 1248)     # 앨범과 같은 원본
        with quiet():
            s1 = pem.export_batch(8.0, 10.0, 300, 0.0, "center", scene_filter=sid, emit=msgs.append)
            s2 = s3 = None
            if have_pil:
                s2 = pem.export_batch(8.0, 10.0, 300, 0.0, "center", scene_filter=sid,
                                      emit=msgs.append, allow_lowres=True)
                s3 = pem.export_batch(4.0, 6.0, 300, 0.0, "center", scene_filter=sid,
                                      emit=msgs.append)
        baked = sorted(f.suffix for f in (out / "8x10").glob("*.tiff"))
    text = chr(10).join(msgs)
    eq(s1["count"], 0, "하한 미만인데 마스터가 구워졌다 — 그대로 인화소로 간다")
    eq([r["dpi"] for r in s1["refused"]], [104], f"거부 기록 — {s1['refused']}")
    eq(s1["needed_px"], [2400, 3600], "필요 픽셀이 없거나 프리플라이트와 수가 다름")
    has(text, "2400×3600", "몇 픽셀이 필요한지 말하지 않음")
    has(text, "--allow-lowres", "푸는 방법을 말하지 않음")
    shutil.rmtree(out, ignore_errors=True)
    if not have_pil:
        raise Skip("Pillow 미설치 — 거부는 확인했고, 굽는 쪽(--allow-lowres)은 확인 불가")
    eq(s2["count"], 1, "--allow-lowres 로 명시했는데도 굽지 못했다")
    eq(baked, [".tiff"], f"명시했을 때 실제 파일이 나와야 한다 — {baked}")
    eq(s3["count"], 1, "4×6(208DPI)까지 막혔다")
    eq(s3["refused"], [], "4×6 은 거부 대상이 아니다")


@test("print", "PR05 크롭 안내는 '어느 변이' 잘렸는지까지 말한다 · 저장소 밖 출력 경로에서 죽지 않는다")
def pr05(b: Box):
    """총 크롭률만 찍으면 사용자는 파일을 열어 봐야 머리가 잘린 걸 안다. 8×10 의 16.7% 는
    위·아래 절반씩이고, 이 작품처럼 얼굴이 프레임 위쪽인 컷은 center 크롭이 정수리를 깎는다.

    함께: 스펙시트 경로를 무조건 ROOT 기준 상대경로로 바꾸던 자리 — 출력 폴더를 저장소 밖으로
    돌려 놓고 부르면 **파일을 다 구운 뒤 마지막 한 줄에서** ValueError 로 죽었다.
    (Pillow 없이 도는 순수 계산이라 이 검사는 사용자 PC 에서도 실행된다.)
    """
    pem = b.mod("print_export")
    tall = {"crop_pct": 16.7, "src_px": [832, 1248], "out_px": [2400, 3000], "anchor": "center"}
    note = pem._crop_note(tall)
    has(note, "위·아래", f"세로가 잘리는데 방향을 말하지 않음 — {note!r}")
    has(note, "8.3", f"한쪽 몫(절반)을 말하지 않음 — {note!r}")
    top = pem._crop_note(dict(tall, anchor="top"))
    has(top, "bottom", f"top 고정이면 아래쪽만 잘린다 — {top!r}")
    hasnt(top, "각 8.3", "한쪽으로 붙였는데 양쪽이 잘린다고 함")
    wide = pem._crop_note({"crop_pct": 16.7, "src_px": [1248, 832],
                           "out_px": [2400, 3000], "anchor": "center"})
    has(wide, "좌·우", f"가로가 잘리는데 방향이 틀림 — {wide!r}")
    eq(pem._crop_note({"crop_pct": 0.0, "src_px": [832, 1248],
                       "out_px": [1200, 1800], "anchor": "center"}), "",
       "잘리지 않았는데 크롭 안내")
    eq(pem._crop_note({"crop_pct": 9.9}), "", "픽셀을 모르는데 방향을 지어냄")

    inside = pem.ROOT / "output" / "print" / "5x7" / "x.tiff"
    eq(pem._rel(inside), "output/print/5x7/x.tiff", "저장소 안 경로는 상대경로 그대로")
    outside = pem.ROOT.parent / "somewhere_else" / "x.tiff"
    eq(pem._rel(outside), outside.as_posix(), "저장소 밖 출력 경로에서 예외 대신 절대경로")


@test("print", "PR06 크롭 기준점(--anchor)이 실제로 남기는 자리를 바꾼다 — top 은 윗변(머리)을 지킨다")
def pr06(b: Box):
    """앵커는 인자만 받고 스펙시트에 받아 적힐 뿐, **픽셀이 실제로 달라지는지** 검사한 적이 없었다.

    2:3 원본을 8×10(4:5)에 채우면 16.7% 가 날아가고 center 는 그 절반씩을 위·아래에서 가져간다
    — 얼굴이 프레임 위쪽인 컷(이 작품의 대부분)은 정수리가 깎인다. 윗변에 표식을 둔 그림으로
    center/top/bottom 이 서로 다른 자리를 남기는지 확인한다.
    """
    try:
        from PIL import Image as PImg
    except Exception:
        raise Skip("Pillow 미설치")
    pem = b.mod("print_export")
    out = b.root / "_pe_anchor"
    src = b.root / "pe_band.png"
    with patched(pem, "OUT", out):
        band = PImg.new("RGB", (832, 1248), (40, 40, 40))
        band.paste(PImg.new("RGB", (832, 40), (255, 0, 0)), (0, 0))           # 윗변 3.2% 표식
        band.paste(PImg.new("RGB", (832, 40), (0, 0, 255)), (0, 1208))        # 아랫변 표식
        band.save(src)

        def corners(spec):
            with PImg.open(b.root / spec["jpg"]) as im:
                return im.convert("RGB").getpixel((im.width // 2, 2)), \
                       im.convert("RGB").getpixel((im.width // 2, im.height - 3))

        def red(px):      # JPEG 는 손실이라 정확 비교 대신 채널 우세로 본다
            return px[0] > 140 and px[0] > px[2] + 60

        def blue(px):
            return px[2] > 140 and px[2] > px[0] + 60

        cen = pem.export_one("A-CENTER", src, 8.0, 10.0, 300, 0.0, "center")
        top = pem.export_one("A-TOP", src, 8.0, 10.0, 300, 0.0, "top")
        bot = pem.export_one("A-BOTTOM", src, 8.0, 10.0, 300, 0.0, "bottom")
        eq(cen["crop_pct"], 16.7, "2:3 → 8×10 크롭률")
        eq(cen["out_px"], [2400, 3000], "출력 픽셀")
        c_top, c_bot = corners(cen)
        t_top, t_bot = corners(top)
        b_top, b_bot = corners(bot)
        ok(not red(c_top) and not blue(c_bot), f"center 인데 위·아래 표식이 남음 — {c_top} {c_bot}")
        ok(red(t_top), f"--anchor top 인데 윗변(머리)이 잘렸다 — {t_top}")
        ok(not blue(t_bot), f"--anchor top 인데 아랫변이 남았다 — {t_bot}")
        ok(blue(b_bot), f"--anchor bottom 인데 아랫변이 잘렸다 — {b_bot}")
        ok(not red(b_top), f"--anchor bottom 인데 윗변이 남았다 — {b_top}")
        # fit 은 아무것도 자르지 않는다 — 양끝 표식이 모두 살아 있어야 한다
        fit = pem.export_one("A-FIT", src, 8.0, 10.0, 300, 0.0, "center", mode="fit", bg="#ffffff")
        eq(fit["crop_pct"], 0.0, "fit 인데 크롭이 생김")
        ok(fit["pad_pct"] > 0, f"fit 인데 여백이 0 — {fit['pad_pct']}")
    shutil.rmtree(out, ignore_errors=True)
    src.unlink(missing_ok=True)


# ============================================================ 감상본(viewer)
@contextlib.contextmanager
def approved_scene(b: Box):
    """selected_image 까지 갖춘 APPROVED 장면(감상본·인화 대상) — 끝나면 지운다."""
    anchor_c, anchor_l = b.anchors()
    with fresh_scene(b) as sid:
        rel = f"images/raw/{sid}/v.png"
        write_png(b.root / rel, 1400, 1000)

        def fix(d):
            d["status"] = "APPROVED"
            d["prompt"]["grok_output"] = f"medium shot, {anchor_c}, {anchor_l}"
            d["assets"] = {"raw_images": [rel], "selected_image": rel}
            d["review"].update(auto="PASS", human="PASS")
        edit_json(b.scene_path(sid), fix)
        yield sid


@test("viewer", "V06 감상본이 떨어뜨린 컷의 이름을 돌려준다 — 조용한 누락은 없다")
def v06(b: Box):
    """스튜디오 뷰어는 승인 전 컷까지 재생하고 감상본은 승인된 컷만 싣는다. 두 목록이
    달라지는 것 자체는 정상이다 — **다르다는 사실을 말하지 않는 것**이 결함이다.
    실제로 1화 엔딩이 빠진 파일을 친구에게 보내고도 보낸 사람이 몰랐다.

    바로 아래 ``prune_dangling_gotos`` 의 docstring 이 이미 같은 규칙을 적어 두고 있었다:
    "무엇을 떨어뜨렸는지 반드시 호출자가 알리게 한다". 이 한 곳만 예외였다.
    """
    ev = b.mod("export_viewer")
    with approved_scene(b) as kept, fresh_scene(b) as dropped:
        with quiet():
            data = ev.build_data(False, 320, 60)
        sk = data.get("skipped")
        ok(isinstance(sk, list), f"skipped 가 목록이 아님 — {type(sk).__name__}")
        ok(dropped in sk, f"승인 전 컷 {dropped} 가 조용히 빠졌다 — {sk}")
        ok(kept not in sk, f"실린 컷이 빠졌다고 보고된다 — {sk}")
        ids = [s.get("id") for s in data["scenes"]]
        ok(dropped not in ids, "승인 전 컷이 감상본에 실렸다(판정이 vn_core 와 갈렸다)")
        ok(kept in ids, "승인된 컷이 감상본에 없다")
        # --all 이어도 선택 이미지가 없는 컷은 빠진다 — 그 경우에도 이름은 남아야 한다
        with quiet():
            data_all = ev.build_data(True, 320, 60)
        ok(dropped in data_all.get("skipped", []),
           "--all 경로에서는 빠진 컷의 이름이 사라진다")
        # 보고용 칸은 남에게 건네는 파일 안으로 따라가지 않는다
        with quiet():
            _d, html = ev.build_html(False, 320, 60)
        hasnt(html, dropped, "미승인 컷의 id 가 감상본 파일 안에 실렸다")


@test("viewer", "V01 타임캡슐 감상본 — 단일 HTML·이미지 내장·스크롤 모드·주입 API 0")
def v01(b: Box):
    tcm = b.mod("export_viewer")
    with approved_scene(b):
        out, data = tcm.export(False, 800, 80)
        html = out.read_text(encoding="utf-8")
    # 보고용 칸은 호출자에게는 오지만 감상본 안에는 실리지 않는다(남에게 건네는 파일이다)
    ok(isinstance(data.get("skipped"), list), "export 가 빠진 컷 목록을 돌려주지 않음")
    hasnt(html, '"skipped"', "보고용 칸이 감상본 payload 에 실림")
    ok(out.exists(), "산출물 없음")
    has(html, "data:image", "이미지 내장")
    has(html, "bScroll", "스크롤 모드")
    for api in BANNED_DOM:
        eq(html.count(api), 0, f"감상본이 {api} 사용")


@test("viewer", "V02 감상본에 분기 재생 런타임 포함(선택지·호감도·엔딩)")
def v02(b: Box):
    src = b.p("tools/export_viewer.py").read_text(encoding="utf-8")
    for token in ("choices", "branch", "ending"):
        has(src, token, f"런타임 {token}")
    has(src.lower(), "affection", "호감도")


@test("viewer", "V03 실리지 않은 장면을 가리키는 goto 는 정리된다(선택 직후 끊김 방지)")
def v03(b: Box):
    tcm = b.mod("export_viewer")
    scenes = [{"id": "SCENE-001", "choices": [{"text": "가다", "goto": "SCENE-999"}],
               "branch": [{"min": 3, "goto": "SCENE-998"}]}]
    warns = tcm.prune_dangling_gotos(scenes)
    ok(len(warns) >= 1, "경고가 없음")
    ok("goto" not in scenes[0]["choices"][0], "선택지 goto 가 남음")
    ok(not scenes[0].get("branch"), "분기 goto 가 남음")


@test("viewer", "V04 엔딩 표기 정규화 — 옛 문자열도 label 로 · build_data 가 이름을 실어 나른다")
def v04(b: Box):
    """엔딩 이름의 정본은 ending_label 하나다(ending 은 참/거짓).

    스튜디오 카드·감상본 엔딩 화면·vn_compose 지시문이 같은 규약을 써야 이름이 갈리지 않는다.
    """
    tcm = b.mod("export_viewer")
    eq(tcm.ending_of({"ending": True, "ending_label": "호감 엔딩"}), (True, "호감 엔딩"), "정규형")
    eq(tcm.ending_of({"ending": "엇갈린 결말"}), (True, "엇갈린 결말"), "옛 문자열 형식")
    eq(tcm.ending_of({"ending": False, "ending_label": "쓰지 않음"}), (False, "쓰지 않음"),
       "ending=False 는 엔딩이 아니다")
    eq(tcm.ending_of({}), (False, ""), "엔딩 아님")
    with approved_scene(b) as sid:
        edit_json(b.scene_path(sid), lambda d: d.update(ending=True, ending_label="호감 엔딩"))
        with quiet():
            data = tcm.build_data(False, 320, 60)
    entry = next((s for s in data["scenes"] if s.get("id") == sid), None)
    ok(entry is not None, "장면이 감상본 데이터에 실리지 않음")
    eq(entry.get("ending"), True, "ending")
    eq(entry.get("ending_label"), "호감 엔딩", "ending_label")


@test("viewer", "V05 export_pwa — 설치형 번들 한 벌(오프라인 자기완결 · 주입 API 0)")
def v05(b: Box):
    """살아 있는 라우트(/api/export-pwa)가 부르는데 지금까지 구문 검사 외 커버리지가 0이었다.
    이 번들은 폰 홈 화면에 설치돼 **오프라인에서** 도는 결과물이라, 외부를 한 번이라도
    참조하면 비행기 모드에서 백지가 된다."""
    ep = b.mod("export_pwa")
    out = b.p("output") / "pwa"
    try:
        with approved_scene(b), quiet():
            got = ep.export(False, 640, 70)
        eq(Path(got).resolve(), out.resolve(), "산출 폴더")
        for name in ("index.html", "manifest.webmanifest", "sw.js", "icon-192.png", "icon-512.png"):
            ok((out / name).exists(), f"{name} 없음 — {[p.name for p in out.glob('*')]}")
        for name in ("icon-192.png", "icon-512.png"):
            eq((out / name).read_bytes()[:8], b"\x89PNG\r\n\x1a\n", f"{name} 이 PNG 가 아님")
        wm = json.loads((out / "manifest.webmanifest").read_text(encoding="utf-8"))
        eq(wm.get("start_url"), "./index.html", "start_url")
        eq(wm.get("display"), "standalone", "display")
        ok(str(wm.get("name") or "").strip(), f"앱 이름이 비어 있음 — {wm}")
        ok(len(wm.get("icons") or []) >= 2, "아이콘 선언")
        html = (out / "index.html").read_text(encoding="utf-8")
        has(html, "manifest.webmanifest", "매니페스트 링크")
        has(html, "serviceWorker", "서비스워커 등록")
        # rel="icon" 이 없으면 브라우저가 서버 루트에서 /favicon.ico 를 찾는다(실측: 404).
        # 감상본이 품고 있던 data: URI 아이콘은 걷어내고 **번들의 파일 아이콘**만 남아야 한다.
        eq(len(re.findall(r'<link rel="icon"', html)), 2, "파비콘 선언(192·512)이 없다")
        eq(len(re.findall(r'<link rel="apple-touch-icon"', html)), 1, "apple-touch-icon 이 하나가 아님")
        ok('rel="icon" type="image/png" href="data:' not in html,
           "감상본의 인라인 data URI 아이콘이 번들에 남았다")
        has(html, "data:image", "이미지 내장")
        ok(not re.search(r"<script\b[^>]*\ssrc=", html, re.I),
           "외부 스크립트를 참조 — 오프라인에서 재생이 죽는다")
        for api in BANNED_DOM:
            eq(html.count(api), 0, f"PWA 번들이 {api} 사용")
        sw = (out / "sw.js").read_text(encoding="utf-8")
        hasnt(sw, "__VER__", "치환되지 않은 캐시 버전 자리표시자")
        has(sw, "index.html", "오프라인 캐시 목록")
    finally:
        shutil.rmtree(out, ignore_errors=True)


@test("viewer", "V07 PWA 아이콘 — 컷 아이콘은 any, maskable 은 여백을 준 별도 파일")
def v07(b: Box):
    """안드로이드는 maskable 아이콘을 런처 모양대로 깎는다(안전 영역은 한 변의 80% 원).
    예전에는 **어떻게 만들었든** 두 파일에 purpose "any maskable" 을 붙였다 — --icon-from-cut
    으로 만든 아이콘에서는 그 선언대로 인물의 머리와 턱이 잘린다.

    기본 아이콘(피사체 없는 그라데이션)은 잘려도 잃을 것이 없으므로 한 파일이 둘 다 맡는다.
    컷 아이콘은 "any" 로만 선언하고 maskable 은 여백본에 맡긴다 — **선언과 파일이 일치하는지**
    (선언한 src 가 실제로 있고, sizes 가 그 PNG 의 실제 크기인지)까지 본다.
    """
    ep = b.mod("export_pwa")
    out = b.p("output") / "pwa"

    def png_size(path):
        raw = path.read_bytes()
        eq(raw[:8], bytes.fromhex("89504e470d0a1a0a"), f"{path.name} 이 PNG 가 아님")
        return struct.unpack(">II", raw[16:24])

    def audit(wm, label):
        for ent in wm["icons"]:
            f = out / ent["src"]
            ok(f.is_file(), f"{label}: 선언한 아이콘 파일이 없다 — {ent['src']}")
            w, h = png_size(f)
            eq(f"{w}x{h}", ent["sizes"], f"{label}: {ent['src']} 의 sizes 선언이 실제 크기와 다름")
            ok(set(ent["purpose"].split()) <= {"any", "maskable", "monochrome"},
               f"{label}: 알 수 없는 purpose {ent['purpose']!r}")
        return {ent["src"]: ent["purpose"] for ent in wm["icons"]}

    try:
        with approved_scene(b), quiet():
            ep.export(False, 640, 70)                     # ① 기본 아이콘
            wm1 = json.loads((out / "manifest.webmanifest").read_text(encoding="utf-8"))
            files1 = sorted(p.name for p in out.glob("icon-*.png"))
            sw1 = (out / "sw.js").read_text(encoding="utf-8")
            purposes1 = audit(wm1, "기본")

            ep.export(False, 640, 70, icon_from_cut=True)  # ② 대표 컷 아이콘
            from_cut = bool(getattr(ep.export, "last_icon_from_cut", False))
            wm2 = json.loads((out / "manifest.webmanifest").read_text(encoding="utf-8"))
            files2 = sorted(p.name for p in out.glob("icon-*.png"))
            sw2 = (out / "sw.js").read_text(encoding="utf-8")
            purposes2 = audit(wm2, "컷")
            pair = [(out / n).read_bytes() if (out / n).is_file() else None
                    for n in ("icon-512.png", "icon-512-maskable.png")]

            ep.export(False, 640, 70)                      # ③ 다시 기본 — 옛 아이콘이 남지 않는다
            files3 = sorted(p.name for p in out.glob("icon-*.png"))
            wm3 = json.loads((out / "manifest.webmanifest").read_text(encoding="utf-8"))

        eq(files1, ["icon-192.png", "icon-512.png"], f"기본 아이콘 파일 {files1}")
        eq(sorted(set(purposes1.values())), ["any maskable"], f"기본 아이콘 purpose {purposes1}")
        for name in files1:
            has(sw1, name, f"서비스워커 캐시 목록에 {name} 이 없다")

        if not from_cut:
            raise Skip("Pillow 없음 — 컷 아이콘을 만들 수 없다")
        eq(files2, ["icon-192-maskable.png", "icon-192.png",
                    "icon-512-maskable.png", "icon-512.png"], f"컷 아이콘 파일 {files2}")
        eq(purposes2.get("icon-192.png"), "any", f"컷 아이콘이 maskable 을 겸함 — {purposes2}")
        eq(purposes2.get("icon-512.png"), "any", f"컷 아이콘이 maskable 을 겸함 — {purposes2}")
        eq(purposes2.get("icon-512-maskable.png"), "maskable", f"여백본 purpose — {purposes2}")
        for name in files2:
            has(sw2, name, f"서비스워커 캐시 목록에 {name} 이 없다")
        ok(pair[0] is not None and pair[1] is not None and pair[0] != pair[1],
           "maskable 판이 원본과 같은 파일이다 — 여백이 들어가지 않았다")

        eq(files3, ["icon-192.png", "icon-512.png"], f"기본으로 되돌린 뒤 남은 파일 {files3}")
        eq(sorted(e["src"] for e in wm3["icons"]), files3, "매니페스트가 없는 파일을 가리킨다")
    finally:
        shutil.rmtree(out, ignore_errors=True)


# ============================================================ JS 구문 게이트
def _scripts(html: str) -> list[str]:
    return [s for s in re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I) if s.strip()]


def _node_check_src(b: Box, code: str, label: str) -> None:
    """JS 원문을 node --check — 문법 오류로 화면이 백지가 되는 회귀를 잡는다."""
    node = shutil.which("node")
    if not node:
        raise Skip("node 없음 — JS 구문 검사 생략")
    tmp = b.root / f"_syntax_{label}.js"
    tmp.write_text(code, encoding="utf-8")
    p = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tmp.unlink(missing_ok=True)
    eq(p.returncode, 0, f"{label} JS 문법 오류 — {(p.stderr or p.stdout)[:400]}")


def _page_js(b: Box, html: str, label: str) -> list[str]:
    """그 페이지가 **실제로 실행하는 JS 전부** — 인라인 <script> + 참조하는 tools/*.js.

    스튜디오가 인라인 스크립트를 /studio/vn_runtime.js 로 빼도(=CSP 에서 'unsafe-inline'
    을 떼는 조건, W27) 문법·주입 API 검사가 빈손으로 통과해 버리지 않게 한다.
    """
    blocks = _scripts(html)
    for src in re.findall(r"<script\b[^>]*\ssrc=[\"']([^\"']+)[\"']", html, re.I):
        p = b.p(f"tools/{src.rsplit('/', 1)[-1]}")
        if p.exists():
            blocks.append(p.read_text(encoding="utf-8"))
    ok(len(blocks) >= 1, f"{label}: 실행되는 JS 를 찾지 못함")
    return blocks


def _node_check(b: Box, html: str, label: str) -> None:
    """HTML 이 실행하는 JS 를 모아 문법 검사한다."""
    _node_check_src(b, "\n;\n".join(_page_js(b, html, label)), label)


@test("js", "J01 studio.html — JS 문법 통과 + 주입 API(innerHTML 등) 0")
def j01(b: Box):
    html = b.p("tools/studio.html").read_text(encoding="utf-8")
    for src in [html] + _page_js(b, html, "studio"):
        for api in BANNED_DOM:
            eq(src.count(api), 0, f"스튜디오가 실행하는 JS 가 {api} 사용")
    _node_check(b, html, "studio")


@test("arch", "L10 사적 대화 파일은 전부 .gitignore 에 걸린다 — 저장 계층이 만드는 모든 경로")
def l10(b: Box):
    """talk_store 가 만들 수 있는 모든 대화 파일 경로가 제외 규칙에 실제로 걸리는지 본다.

    왜 기계로 확인하는가: 규칙이 `chatlog.json` 한 줄이던 시절에 쓰였고, 그 뒤 갈래 기능이
    생기며 `chat_<id>.json` 과 `chats_meta.json` 이 늘었다. 목록은 자동으로 자라지 않으므로
    새 파일이 조용히 커밋 대상이 된다 — 그게 개인 대화라면 되돌릴 수 없다.
    """
    ts = b.mod("talk_store")
    rules = (SRC / ".gitignore").read_text(encoding="utf-8")

    def covered(name: str) -> bool:
        """이 파일 이름을 덮는 줄이 있는가 — 정확한 이름 또는 그것을 포함하는 글롭."""
        for raw in rules.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            pat = line.split("/")[-1]
            if fnmatch.fnmatch(name, pat):
                return True
        return False

    made = [
        ts.story_chat_path().name,                    # 기본 갈래
        ts.story_chat_path_for("abc123").name,        # 갈래
        ts.chat_meta_path().name,                     # 갈래 설정
        ts.talk_path("CHAR-001").name,                # 인물 대화
        ts.archive_path(ts.story_chat_path_for("abc123")).name,   # 갈래 아카이브
        ts.archive_path(ts.talk_path("CHAR-001")).name,           # 인물 아카이브
    ]
    missing = [n for n in made if not covered(n)]
    eq(missing, [], "저장 계층이 만드는 사적 파일이 .gitignore 에 안 걸린다 — 커밋되면 되돌릴 수 없다")

    # 이미 추적 중인 것이 있으면 규칙이 있어도 소용없다(추적된 파일은 제외 규칙을 무시한다)
    try:
        tracked = subprocess.run([shutil.which("git") or "git", "ls-files", "project/story"],
                                 cwd=SRC, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        raise Skip("git 없음 — 추적 여부는 확인 생략")
    bad = [l for l in tracked.splitlines()
           if l.strip() and any(fnmatch.fnmatch(l.rsplit("/", 1)[-1], p)
                                for p in ("chatlog.json", "chat_*.json", "chats_meta.json",
                                          "talk_*.json", "*.archive.jsonl"))]
    eq(bad, [], "사적 대화 파일이 이미 git 에 추적되고 있다")


@test("js", "J15 통합 화면 — 모델이 꺼져도 쓸 길이 있고, 이어하기는 받은 것을 지키며, 진행은 탭 밖에 산다")
def j15(b: Box):
    """세 가지를 코드에서 확인한다. 전부 실제로 사람이 잃을 뻔한 것들이다.

    (1) **모델이 꺼졌을 때의 길** — CLAUDE.md 가 지키라고 한 유일한 경로다(붙여넣기).
        이 화면에는 그 길이 한 줄도 없었다. 노트북을 닫으면 그림 굽기 말고는 할 게 없었다.
    (2) **이어하기가 받은 것을 지키는가** — [이어서 다시] 가 라벨과 반대로 전부 버리고
        1번부터 다시 했다. resume 를 싣지 않으면 그 사고가 그대로 돌아온다.
    (3) **진행과 복구 버튼이 탭 밖에 사는가** — #stream 안에 있으면 탭 한 번에 지워지고,
        받아 둔 장면을 되살릴 방법이 화면에서 사라진다.
    """
    p = b.p("tools/chat_ui.js")
    if not p.exists():
        raise Gap("tools/chat_ui.js 아직 없음 — 통합 화면 미도입")
    js = p.read_text(encoding="utf-8")
    html = b.p("tools/chat_ui.html").read_text(encoding="utf-8")

    has(js, "/api/compose-input", "모델이 꺼졌을 때 지시문을 복사할 길이 없다")
    has(js, "/api/compose-manual", "붙여넣어 장면을 만드는 길이 없다")
    has(js, "llmDown", "모델이 꺼진 것을 화면이 알지 못한다")

    ok(re.search(r"resume:\s*true", js) is not None,
       "[이어서 다시] 가 resume 를 싣지 않는다 — 받아 둔 장면을 전부 버리고 1번부터 다시 한다")

    has(html, 'id="live"', "진행 표시가 탭 밖에 없다")
    has(js, "liveShow", "진행·복구를 고정 자리에 그리는 경로가 없다")
    # 복구 버튼이 #stream 안에서만 만들어지면 탭 한 번에 사라진다
    ok("liveShow" in js[js.index("function composeFailed"):js.index("function composeFailed") + 2000],
       "조립 실패 복구 버튼이 고정 자리에 없다 — 탭을 옮기면 사라진다")

    # 고르기는 굽는 중에도 되어야 한다(서버가 '고르세요' 라고 말하는 동안 잠겨 있었다).
    # 주석에 S.busy 를 언급할 수는 있으므로 **실행되는 줄**만 본다.
    start = js.index("async function pick(")
    body = js[start:start + 500]
    code = [l for l in body.splitlines()
            if l.strip() and not l.strip().startswith(("*", "/*", "//"))]
    ok(not any("S.busy" in l for l in code),
       "고르기가 S.busy 로 잠겨 있다 — 굽는 동안 고를 수 없다")
    ok(any("S.picking" in l for l in code),
       "고르기에 자기 잠금(S.picking)이 없다 — 두 번 누르면 겹친다")


@test("unit", "U34 생성 중단 — 장 사이에서만 멈추고, 이미 구운 장은 남고, 진행 숫자는 문구에 안 산다")
def u34(b: Box):
    """세 가지를 잠근다.

    (1) 멈춤은 **장 사이에서만** 일어난다. 굽는 도중에 끊으면 반쯤 쓰인 파일이 남는다.
    (2) 진행 숫자(done/want)는 문구와 따로 보관된다. 예전에는 문구에 "2/4장" 을 적었는데
        엔진 폴링이 1.5초마다 문구를 통째로 갈아치워 화면이 그 숫자를 볼 수 없었다 —
        그래서 '한 장씩 보여 주기'도 '중간에 그만두기'도 조용히 죽어 있었다.
    (3) 취소 표시는 새 작업을 시작할 때 지워진다. 안 그러면 지난 '그만' 이 다음 생성을
        첫 장에서 멈춰 세운다.
    """
    gj = b.mod("gen_jobs")
    sid = "SCENE-001"

    gj.clear_cancel(sid)
    ok(not gj.cancelled(sid), "표시를 지웠는데 아직 취소 상태다")
    gj.request_cancel(sid)
    ok(gj.cancelled(sid), "그만 표시가 안 걸렸다")
    gj.clear_cancel(sid)
    ok(not gj.cancelled(sid), "새 작업을 시작해도 지난 표시가 남아 있다 — 첫 장에서 멈춘다")

    # 숫자는 문구가 갈아치워져도 살아남아야 한다
    gj.note(sid, "2/4장 나왔습니다", done=2, want=4)
    gj.note(sid, "ComfyUI 생성 중… 7초 경과 · 렌더 중")      # 폴링이 문구만 갈아치운다
    st = gj.status(sid)
    eq(st.get("done"), 2, "문구가 갈아치워지며 진행 숫자가 사라졌다")
    eq(st.get("want"), 4, "요청 장수가 사라졌다")
    gj.release(sid)

    # 렌더 루프는 should_stop 을 장마다 본다 — 한 장도 굽기 전에 멈추면 명확히 말한다
    cc = b.mod("comfyui_client")
    src = b.p("tools/comfyui_client.py").read_text(encoding="utf-8")
    has(src, "should_stop", "렌더 루프에 중단 확인이 없다")
    has(src, "on_each", "장마다 알리는 콜백이 없다")
    ok(src.index("if should_stop") < src.index("sd = (base + i)"),
       "중단 확인이 굽기 시작한 뒤에 있다 — 장 중간에 끊긴다")


@test("unit", "U33 조립 스트림 — 장면이 완성되는 즉시 알아채고, 대사 속 괄호에 속지 않는다")
def u33(b: Box):
    """_SceneStream 은 흐르는 글자에서 장면 경계를 잡는다. 이게 틀리면 두 가지로 망가진다:
    못 잡으면 예전처럼 100초 동안 화면이 비고, 잘못 잡으면 대사 조각이 장면으로 올라온다.

    실측 근거: 3장면 배치가 95~118초인데 장면 1개는 약 30초다. 경계를 잡으면 첫 보상이
    100초에서 30초로 당겨진다 — 기다림이 불안에서 기대로 바뀌는 유일한 지점이다.
    """
    vc = b.mod("vn_compose")
    got = []
    st = vc._SceneStream(got.append)

    scene = ('{"order":1,"purpose":"\\ucef7","dialogue":[{"speaker_id":"CHAR-001",'
             '"text":"\\uc911\\uad04\\ud638 { \\uc640 } \\uac00 \\ub4e4\\uc5b4\\uc788\\ub2e4"}],'
             '"image_prompt":"p"}')
    # 한 글자씩 흘려보낸다 — 실제 SSE 조각 크기와 무관하게 동작해야 한다
    for ch in "[" + scene:
        st.feed(ch)
    eq(len(got), 1, "장면 하나가 끝났는데 못 알아챘다")
    eq(got[0]["order"], 1, "장면 내용이 어긋남")

    # 대사 안의 중괄호가 경계로 오인되지 않았는지 — 위에서 1개만 나왔으면 통과다
    st2 = vc._SceneStream(got.append)
    st2.feed('{"speaker_id":"CHAR-001","text":"x"}')     # 대사 원소는 장면이 아니다
    eq(len(got), 1, "대사 원소를 장면으로 올렸다 — _looks_like_scene 관문이 뚫렸다")

    # 깨진 JSON 은 조용히 넘어가야 한다(최종 파싱이 다시 본다)
    st3 = vc._SceneStream(got.append)
    st3.feed('{"order":2,"purpose":')
    eq(len(got), 1, "미완성 조각을 장면으로 올렸다")

    # 콜백이 터져도 조립이 멈추면 안 된다
    boom = vc._SceneStream(lambda _o: (_ for _ in ()).throw(RuntimeError("화면 갱신 실패")))
    boom.feed(scene)          # 예외가 밖으로 새면 이 줄에서 테스트가 죽는다


@test("unit", "U32 대화 갈래 — 설정 파일이 대화로 둔갑하지 않고, 자르기는 잘린 말을 보관한다")
def u32(b: Box):
    """두 가지를 잠근다.

    (1) 갈래 목록은 `chat_<id>.json` 을 훑는다. 설정 파일 이름이 그 규칙과 겹치면 설정
        파일 자신이 빈 대화로 목록에 뜬다 — 실제로 `chat_meta.json` 이 'meta' 라는 대화로
        나타났다. 이름 규칙을 바꿔 막았고, 여기서 되돌아오지 않는지 본다.
    (2) truncate_log 는 이 모듈에서 대화를 짧게 만드는 **유일한** 함수다. 짧게 만들되
        잘린 말은 아카이브로 옮겨야 한다. 옮기지 않고 자르면 사용자 대화가 사라진다.
    """
    ts = b.mod("talk_store")

    meta = ts.chat_meta_path()
    ok(not meta.name.startswith(ts.CHAT_PREFIX),
       f"설정 파일 이름 {meta.name!r} 이 갈래 파일 규칙({ts.CHAT_PREFIX}*.json)과 겹친다 "
       "— 설정이 빈 대화로 목록에 뜬다")

    story = b.root / "project" / "story"
    story.mkdir(parents=True, exist_ok=True)
    ts.set_chat_use_context("alpha", False)
    ids = [c["id"] for c in ts.list_story_chats()]
    eq([i for i in ids if i == "meta"], [], "설정 파일이 대화로 잡힘")

    path = ts.story_chat_path_for("trimtest")
    ts.save_log(path, [{"role": "user", "content": "1"}, {"role": "assistant", "content": "2"},
                       {"role": "user", "content": "3"}, {"role": "assistant", "content": "4"}])
    res = ts.truncate_log(path, 2)
    eq(res["kept"], 2, "자른 뒤 남은 수가 다름")
    eq(res["dropped"], 2, "옮긴 수가 다름")
    eq(len(ts.load_log(path)), 2, "실제 파일이 잘리지 않음")
    arch = ts.archive_path(path)
    ok(arch.is_file(), "잘라낸 구간이 아카이브로 옮겨지지 않음 — 사용자 대화가 사라진다")
    body = arch.read_text(encoding="utf-8")
    for want in ("3", "4"):
        has(body, want, "아카이브에 잘린 말이 없음")
    eq(ts.truncate_log(path, 99)["dropped"], 0, "남은 것보다 크게 자르라 하면 아무것도 안 해야 한다")


@test("unit", "U35 목록 요약 캐시 — 안 바뀐 대화는 다시 읽지 않고, 바뀐 것은 읽고, 지운 것은 표에서 빠진다")
def u35(b: Box):
    """목록 화면은 대화마다 제목 한 줄과 개수 하나만 쓴다. 그 둘을 얻으려고 로그 전체를
    json 으로 풀면, 대화가 50개일 때 **페이지를 열 때마다** 50개 파일을 다시 읽는다.
    실측으로 0.8초였고 폰에서 그건 '멈춘 화면'이다.

    캐시가 틀리면 더 나쁘다 — 방금 보낸 말이 목록에 안 뜨거나(안 갱신), 지운 대화가
    계속 보인다(안 지워짐). 그래서 세 가지를 다 잠근다: 안 읽는가 · 읽는가 · 잊는가.
    """
    ts = b.mod("talk_store")
    ts._SUMMARY.clear()

    reads = {"n": 0}
    real = ts.load_log

    def counting(path):
        reads["n"] += 1
        return real(path)

    made = []
    try:
        for i in range(5):
            p = ts.STORY_DIR / ("chat_u35x%d.json" % i)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"messages": [{"role": "user", "content": "첫 말 %d" % i},
                                                  {"role": "assistant", "content": "답"}]},
                                    ensure_ascii=False), encoding="utf-8")
            made.append(p)

        ts.load_log = counting
        rows = ts.list_story_chats()
        first = reads["n"]
        ok(first >= 5, "첫 훑기가 파일을 안 읽었다(%d회) — 캐시가 아니라 빈 목록이다" % first)
        got = {r["id"]: r for r in rows}
        eq(got["u35x0"]["title"], "첫 말 0", "제목을 첫 사용자 발화에서 안 가져온다")
        eq(got["u35x0"]["count"], 2, "발화 수가 틀리다")

        reads["n"] = 0
        ts.list_story_chats()
        ts.list_story_chats()
        eq(reads["n"], 0, "파일이 그대로인데 %d번 다시 읽었다 — 캐시가 안 걸렸다" % reads["n"])

        # 한 개만 고친다 → 그 하나만 다시 읽어야 한다(나머지는 표 그대로)
        made[0].write_text(json.dumps({"messages": [{"role": "user", "content": "바꾼 말"},
                                                    {"role": "assistant", "content": "답"},
                                                    {"role": "user", "content": "더"}]},
                                      ensure_ascii=False), encoding="utf-8")
        reads["n"] = 0
        rows = ts.list_story_chats()
        eq(reads["n"], 1, "바뀐 파일 하나에 %d번 읽었다 — 전부 다시 읽고 있다" % reads["n"])
        got = {r["id"]: r for r in rows}
        eq(got["u35x0"]["count"], 3, "고친 대화의 개수가 목록에 반영되지 않았다")
        eq(got["u35x0"]["title"], "바꾼 말", "고친 대화의 제목이 옛것 그대로다")

        # 지우면 표에서도 빠진다 — 안 그러면 삭제한 대화가 목록에 계속 보인다
        ts.delete_story_chat("u35x1")
        ids = {r["id"] for r in ts.list_story_chats()}
        ok("u35x1" not in ids, "지운 대화가 목록에 남아 있다")
        ok(str(ts.story_chat_path_for("u35x1")) not in ts._SUMMARY,
           "지운 대화의 요약이 표에 남아 있다 — 같은 id 를 다시 쓰면 옛 제목이 나온다")
    finally:
        ts.load_log = real
        for p in made:
            try:
                p.unlink()
            except OSError:
                pass
        ts._SUMMARY.clear()


@test("unit", "U36 대화 zip — 통째로 나갔다 돌아오고, 가져오기는 무슨 일이 있어도 덮어쓰지 않는다")
def u36(b: Box):
    """이 로그들은 이 저장소에서 사용자가 가장 아끼는 자산이다. 지금까지 백업하는 길이
    "F 드라이브를 통째로 복사한다" 하나뿐이었고, 폰에서 쓰기 시작한 뒤로는 그것도 없었다.

    그래서 두 가지를 잠근다.

    (1) **통째로** 나간다 — 본문뿐 아니라 보관 기록(사용자가 '수정'·'다시 생성' 으로 밀어낸
        말들)과 작품 설정까지. 그게 빠지면 "이 대화를 옮겼다" 가 거짓말이 된다.
    (2) **덮어쓰지 않는다** — 같은 id 가 있으면 이름을 비켜 새 갈래로 들어온다. 덮어쓰기는
        이 화면에서 유일하게 되돌릴 수 없는 동작이 됐을 것이다. 그 편함은 이 파일들에
        걸 만한 것이 아니다.

    쓰레기 입력도 함께 본다 — 가져오기는 사용자가 **다른 데서 받은 파일**을 넣는 자리라,
    이 화면에서 만들지 않은 바이트가 반드시 들어온다.
    """
    ts = b.mod("talk_store")
    msgs = [{"role": "user", "content": "비 오는 버스"},
            {"role": "assistant", "content": "좋아요. 첫 장면은…"}]
    ts.save_log(ts.story_chat_path_for("u36a"), msgs)
    ts.set_chat_use_context("u36a", False)
    ts._append_archive(ts.archive_path(ts.story_chat_path_for("u36a")),
                       [{"role": "assistant", "content": "밀려난 예전 답"}])

    name, data = ts.export_chat_bytes("u36a")
    ok(name.endswith(".zip"), "내보낸 이름이 zip 이 아니다: %s" % name)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        for want in ("meta.json", "chat.json", "archive.jsonl"):
            ok(want in names, "zip 에 %s 가 없다 — 통째로 옮겨지지 않는다 (%s)" % (want, sorted(names)))
        meta = json.loads(z.read("meta.json").decode("utf-8"))
    eq(meta.get("chat_id"), "u36a", "어느 대화인지 적혀 있지 않다")
    eq(meta.get("use_context"), False, "작품 설정이 안 실렸다 — 가져온 쪽이 다르게 답한다")

    # (2) 같은 저장소로 되돌려 넣어도 원본은 한 글자도 안 변한다
    r = ts.import_chat_bytes(data)
    ok(r["chat_id"] != "u36a", "기존 대화를 덮어썼다 — 되돌릴 수 없는 사고다")
    ok(r["renamed"] is True, "이름을 비켰는데 화면에 말해 주지 않는다")
    eq(ts.load_log(ts.story_chat_path_for("u36a")), msgs, "원본 대화가 변했다")
    eq(r["count"], 2, "옮겨진 발화 수가 다르다")
    eq(r["archived"], 1, "보관 기록이 따라오지 않았다")
    eq(ts.chat_use_context(r["chat_id"]), False, "작품 설정이 따라오지 않았다")

    # 두 번 넣어도 서로를 덮지 않는다
    r2 = ts.import_chat_bytes(data)
    ok(r2["chat_id"] not in ("u36a", r["chat_id"]), "두 번째 가져오기가 첫 번째를 덮었다")

    # 쓰레기·빈 것·zip 아닌 것은 아무것도 만들지 않는다
    before = {c["id"] for c in ts.list_story_chats()}
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("chat.json", json.dumps({"messages": []}))
    for bad, why in ((b"definitely not a zip", "zip 이 아닌 바이트"),
                     (b"", "빈 바이트"),
                     (empty.getvalue(), "대화가 없는 zip")):
        try:
            ts.import_chat_bytes(bad)
            ok(False, "%s 를 받아들였다" % why)
        except Exception as e:
            ok(not isinstance(e, (KeyError, AttributeError, TypeError)),
               "%s 에 역추적이 났다(사람이 읽을 말이 없다): %r" % (why, e))
    eq({c["id"] for c in ts.list_story_chats()}, before,
       "거절한 입력이 대화를 만들었다 — 목록에 빈 대화가 쌓인다")

    # 경로를 탈출하려는 항목이 들어 있어도 무시한다(고정된 이름만 읽는다)
    eviltmp = io.BytesIO()
    with zipfile.ZipFile(eviltmp, "w") as z:
        z.writestr("../../pwned.txt", "x")
        z.writestr("chat.json", json.dumps({"messages": msgs}, ensure_ascii=False))
    ts.import_chat_bytes(eviltmp.getvalue())
    ok(not (b.root.parent / "pwned.txt").exists() and not (b.root / "pwned.txt").exists(),
       "zip 안의 경로 탈출이 파일을 만들었다")


@test("unit", "U37 프롬프트에 남은 맨 id — 걷어내되 앵커는 지키고, 낱말 경계를 넘지 않는다")
def u37(b: Box):
    """실측(씽크북·Qwen3.6-35B, 32장면)에서 모델이 앵커를 풀어 쓰는 대신 "CHAR-001",
    "LOC-002" 를 프롬프트에 그대로 적어 넣는 경우가 있었다.

    이게 왜 조용한 사고인가: 앵커 보정이 앵커를 뒤에 붙이므로 **검사는 통과한다.** 그런데
    프롬프트에는 "CHAR-001" 이 남아 있고, SDXL 은 그것을 그려야 할 글자로 읽어 그림 안에
    글자 무늬를 넣는다. 굽기 전에는 아무도 모르고, 굽고 나면 23초와 한 장이 버려진다.

    반대 방향의 사고도 같이 잠근다 — 너무 많이 걷어내는 것. 'coat LOC-002' 의 'coat' 에서
    'at' 을 떼면 남는 것은 'co' 다. 프롬프트는 사람이 다시 읽지 않는 글이라, 조용히 망가지면
    조용히 이상한 그림이 나온다.
    """
    so = b.mod("scene_ops")
    cases = [
        # (원문, 참조 id, 기대 결과, 뺐는가)
        ("CHAR-001 standing in the rain at LOC-002, cinematic", ["CHAR-001", "LOC-002"],
         "standing in the rain, cinematic", True),
        ("a girl, CHAR-001, wet hair", ["CHAR-001"], "a girl, wet hair", True),
        ("two people in LOC-002, dusk", ["LOC-002"], "two people, dusk", True),
        # 낱말 경계 — 'coat' 의 at, 'CHAR-0012' 는 다른 토큰이다
        ("a coat LOC-002 test", ["LOC-002"], "a coat test", True),
        ("CHAR-0012 is a different token", ["CHAR-001"], "CHAR-0012 is a different token", False),
        # 대소문자만 다른 것도 같은 id 다
        ("char-001 close up", ["CHAR-001"], "close up", True),
        # 참조하지 않는 id 는 건드리지 않는다
        ("CHAR-009 somewhere", ["CHAR-001"], "CHAR-009 somewhere", False),
        # 전부 걷어내면 남는 게 없다 → 원문을 지킨다(빈 프롬프트보다 지저분한 편이 낫다)
        ("CHAR-001", ["CHAR-001"], "CHAR-001", False),
    ]
    for text, refs, want, changed in cases:
        out, dropped = so._drop_bare_ids(text, refs)
        eq(out, want, "맨 id 정리가 틀렸다: %r → %r (기대 %r)" % (text, out, want))
        eq(bool(dropped), changed, "뺐는지 여부가 틀렸다: %r → %r" % (text, dropped))

    # 실제 장면에 걸었을 때 — id 는 사라지고 앵커는 남는다(검사기 A6 는 여전히 통과)
    mf = json.loads(b.p("project/manifest.json").read_text(encoding="utf-8"))
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict) and c.get("prompt_anchor")]
    if not chars:
        raise Gap("매니페스트에 앵커가 있는 인물이 없음")
    cid = str(chars[0]["character_id"])
    anchor = str(chars[0]["prompt_anchor"])
    sc = {"characters": [cid], "location_id": ""}
    out, touched = so.fix_anchor_text(sc, cid + " walking, rain")
    ok(anchor in out, "앵커가 프롬프트에 없다 — A6 가 떨어진다: %r" % out)
    ok(cid not in out, "맨 id 가 그대로 남았다 — 그림에 글자가 그려진다: %r" % out)
    ok(cid in touched, "id 를 걷어냈는데 손댔다고 말하지 않는다")


@test("unit", "U38 소스에 보이지 않는 제어문자가 없다 — 눈에 안 보이는 글자가 정규식을 바꾼다")
def u38(b: Box):
    """이 검사가 왜 있는가: 실제로 도구가 파이썬 소스에 **백스페이스 문자(0x08)**를 써 넣은
    적이 있다. 정규식 안의 낱말 경계(백슬래시 b)를 만들려다 그것이 문자열 이스케이프로
    해석돼 제어문자 한 글자가 됐다.

    결과는 조용했다. 파일은 문법 통과, 테스트도 통과, 화면에도 아무 변화가 없다. 다만 그
    정규식이 매칭하는 대상이 달라져서 "전치사도 같이 걷는다" 는 기능이 통째로 죽어 있었다.
    사람이 sed·grep 으로 봐도 안 보인다 — 터미널이 그 글자를 그리지 않기 때문이다.

    탭·줄바꿈·캐리지리턴만 허용한다. 나머지 C0 제어문자와 BOM·제로폭 글자는 소스에 있을
    이유가 없다.
    """
    allowed = {0x09, 0x0A, 0x0D}
    bad_cp = {0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060}      # BOM · 제로폭
    hits = []
    roots = [b.p("tools"), b.p("viewer")]
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in (".py", ".js", ".html", ".css", ".json"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for ch in line:
                    cp = ord(ch)
                    if (cp < 0x20 and cp not in allowed) or cp == 0x7F or cp in bad_cp:
                        hits.append("%s:%d U+%04X" % (f.name, n, cp))
                        break
    ok(not hits, "소스에 보이지 않는 제어문자가 있다(정규식·문자열이 조용히 달라진다): "
                 + ", ".join(hits[:8]))


@test("unit", "U39 줄 서 있을 때의 상한 — 조립이 도는 동안 대화가 120초에 죽지 않는다")
def u39(b: Box):
    """씽크북 실측이 찾아낸 것이다. llama-server 는 ``--parallel 1`` 이라 조립이 도는 동안
    대화는 통째로 줄을 서는데, **줄 선 요청에는 응답 헤더조차 주지 않는다** — 슬롯이 풀려야
    그때 200 이 온다. 그래서 평소의 120초 상한이 '조각 사이의 침묵'이 아니라 '큐 대기'에
    그대로 걸린다.

      대화 단독:      첫 글자 22.5초 / 완료 27.1초
      조립 중 대화:   첫 글자 262.6초 (조립이 끝난 직후) — 벌점 +240초
      조립 275초 동안 timeout=120 으로 보낸 대화는 정확히 120.0초에 TimeoutError.

    스트리밍으로 고칠 수 있는 문제가 아니다(조립 자신은 구하지만 뒤에 선 대화는 못 구한다).
    조립을 서버 작업으로 내려 '탭을 닫아도 계속 돈다' 가 된 뒤로 사람이 그 시간에 대화를
    시도할 확률은 오히려 올라갔다.

    고치는 방향: **기본값은 그대로 두고**(그걸 키우면 진짜로 꺼진 서버를 알아차리는 데도
    15분이 걸린다), 앞에 무엇이 도는지 아는 곳 — 조립을 직접 돌리는 이 서버 — 만 상한을 푼다.
    """
    ll = b.mod("local_llm")
    eq(ll.TIMEOUT, 120, "기본 상한이 바뀌었다 — 꺼진 서버를 알아차리는 시간이 같이 늘어난다")
    ok(ll.QUEUE_TIMEOUT > ll.TIMEOUT * 2,
       "큐 대기용 상한이 기본값과 비슷하다(%s) — 5~6분짜리 조립을 못 넘긴다" % ll.QUEUE_TIMEOUT)

    # timeout 인자가 **실제로 소켓까지** 내려가는가 (서명만 있고 안 쓰면 아무 효과가 없다)
    seen = {}

    class _Fake:
        def __enter__(self):
            raise ll.VNError("여기까지면 충분하다")

        def __exit__(self, *a):
            return False

    real_open = ll._OPENER.open
    real_validate = ll._validate
    try:
        ll._validate = lambda url: None
        ll._OPENER.open = lambda req, timeout=None: seen.update(timeout=timeout) or _Fake()
        for kw, want in (({}, ll.TIMEOUT), ({"timeout": ll.QUEUE_TIMEOUT}, ll.QUEUE_TIMEOUT)):
            seen.clear()
            try:
                ll.chat([{"role": "user", "content": "x"}], **kw)
            except Exception:
                pass
            eq(seen.get("timeout"), float(want),
               "timeout=%r 를 줬는데 소켓에는 %r 가 갔다" % (kw.get("timeout"), seen.get("timeout")))
    finally:
        ll._OPENER.open = real_open
        ll._validate = real_validate

    # 서버가 '줄이 있는가' 를 판단하고, 그 판단만 상한을 푼다
    web = b.mod("webapp")
    eq(web._chat_timeout({"busy": True}), ll.QUEUE_TIMEOUT, "줄이 서 있는데 상한을 안 푼다")
    eq(web._chat_timeout({"busy": False}), None, "한가한데도 상한을 풀었다 — 꺼진 서버를 늦게 안다")
    eq(web._chat_timeout({}), None, "상태를 모를 때 기본값으로 떨어지지 않는다")

    # 두 대화 경로가 **둘 다** 그 값을 쓴다 (하나만 고치면 다른 쪽이 계속 죽는다)
    src = b.p("tools/webapp.py").read_text(encoding="utf-8")
    for fn, what in (("def do_chat(", "스토리 대화"), ("def r_talk(", "인물 대화")):
        body = src[src.index(fn):]
        body = body[:body.index("\ndef ", 10)]
        ok("_chat_timeout(" in body, "%s 경로가 큐 상한을 쓰지 않는다 — 조립 중에 120초로 죽는다" % what)


@test("js", "J17 통합 화면 — 부르는 함수가 전부 정의돼 있다(문법 통과와 '돌아간다'는 다르다)")
def j17(b: Box):
    """``node --check`` 는 **문법만** 본다. 없는 함수를 부르는 코드도 문법은 멀쩡하다 —
    그 줄에 닿는 순간에야 ReferenceError 로 죽고, 그 줄이 '내보내기 버튼' 처럼 가끔 눌리는
    자리면 며칠 뒤에 사용자가 발견한다.

    이 파일이 특히 그렇다: 1,600줄짜리 한 장이고, 기능이 붙을 때마다 중간에 끼워 넣는다.
    함수 이름 한 글자만 틀려도 나머지 전부는 멀쩡히 돌아간다.

    판정: `이름(` 꼴로 부르는 것 중 이 파일·vn_runtime.js 에 정의가 없고 브라우저 기본
    전역도 아닌 이름이 있으면 실패. 문자열·주석 안의 `rgba(` 같은 것도 같이 잡히므로,
    새로 걸리는 이름이 진짜 전역이면 아래 GLOBALS 에 적어 넣으면 된다 — 그 한 줄이
    "이건 브라우저가 주는 것" 이라는 기록이 된다.
    """
    p = b.p("tools/chat_ui.js")
    if not p.exists():
        raise Gap("tools/chat_ui.js 아직 없음 — 통합 화면 미도입")
    js = p.read_text(encoding="utf-8")
    rt = b.p("tools/vn_runtime.js")
    rtsrc = rt.read_text(encoding="utf-8") if rt.exists() else ""

    # 브라우저·언어가 주는 것 (여기 적힌 것만 '밖에서 온다'고 인정한다)
    GLOBALS = {
        "AbortController", "Array", "Blob", "Boolean", "Date", "Error", "File", "FileReader",
        "FormData", "Image", "Intl", "JSON", "Map", "Math", "Number", "Object", "Promise",
        "RegExp", "Set", "String", "Symbol", "TextEncoder", "URL", "URLSearchParams",
        "Uint8Array", "WeakMap", "alert", "atob", "btoa", "clearInterval", "clearTimeout",
        "confirm", "decodeURIComponent", "encodeURIComponent", "fetch", "isFinite", "isNaN",
        "parseFloat", "parseInt", "queueMicrotask", "requestAnimationFrame",
        "setInterval", "setTimeout",
    }
    KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "typeof",
                "await", "async", "new", "else", "do", "try", "of", "in", "case", "yield",
                "delete", "void", "instanceof", "get", "set"}

    def defined(src):
        out = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", src))
        out |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", src))
        return out

    known = defined(js) | defined(rtsrc) | GLOBALS | KEYWORDS
    called = set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", js))
    unknown = sorted(called - known)
    ok(not unknown,
       "정의를 못 찾은 호출이 있다(오타이거나, 브라우저 전역이면 J17 의 GLOBALS 에 적어라): "
       + ", ".join(unknown))

    # 이 화면이 실제로 쓰는 서버 라우트가 전부 존재하는가 — 오타 난 주소는 404 한 줄로 끝난다
    web = b.p("tools/webapp.py").read_text(encoding="utf-8")
    used = sorted(set(re.findall(r'"(/api/[a-z0-9-]+)"', js)))
    ok(used, "화면이 서버 라우트를 하나도 부르지 않는다 — 추출이 깨졌다")
    missing = [r for r in used if ('"%s"' % r) not in web]
    ok(not missing, "화면이 없는 라우트를 부른다(404 한 줄로 끝난다): " + ", ".join(missing))


def _headless_browser() -> str:
    """이 PC 에서 쓸 수 있는 헤드리스 브라우저 경로(없으면 "")."""
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in cands:
        if Path(c).is_file():
            return c
    for name in ("chromium", "google-chrome", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return ""


@test("js", "J18 통합 화면을 진짜 브라우저로 띄운다 — 문법이 아니라 '보이는가'를 본다", web=True)
def j18(b: Box):
    """정적 검사(J14·J16·J17)가 못 보는 것이 있다: **그려지는가.**

    없는 함수를 부르는 코드도 문법은 멀쩡하고, 라우트 이름이 맞아도 그 응답으로 화면을
    만드는 자리에서 죽으면 사용자가 보는 것은 빈 판이다. 실제로 이 작업 중에 openChat 이
    잘못된 화면으로 가도록 바꿔 버린 적이 있다 — 목록에서 대화를 눌러도 목록으로 되돌아오는
    상태였고, 문법 검사·정의 검사 둘 다 통과했다. 그건 띄워 봐야 안다.

    헤드리스 브라우저로 각 탭을 열고 DOM 을 받아 확인한다. 브라우저가 없는 PC 에서는
    건너뛴다(코드 문제가 아니라 이 기계에 없을 뿐이다).
    """
    exe = _headless_browser()
    if not exe:
        raise Gap("헤드리스 브라우저(Edge/Chrome)가 이 PC 에 없음")

    # 대화가 하나도 없으면 줄이 없고, 줄마다 생기는 [내보내기] 도 없다.
    # 빈 목록을 보고 "버튼이 없다" 라고 하면 엉뜬한 곳을 고치게 된다 — 한 줄 만든다.
    b.wapi("/api/chat", {"messages": [{"role": "user", "content": "목록에 한 줄"}]})

    profile = b.root / "logs" / "headless"

    seq = {"n": 0}

    def _once(hashname: str) -> str:
        # 프로필을 **매번 새 폴더로** 둔다. 같은 경로를 지우고 다시 만들면, 앞서 띄운
        # msedge 가 아직 내려가는 중일 때 새 프로세스가 그쪽에 일을 넘기고 **즉시 끝난다**
        # — 빈 DOM 이 나오고, 그것이 5회 중 2회 깜빡이던 진짜 이유였다.
        seq["n"] += 1
        prof = profile.parent / ("headless%02d" % seq["n"])
        prof.mkdir(parents=True, exist_ok=True)
        out = subprocess.run(
            [exe, "--headless", "--disable-gpu", "--no-sandbox", "--disable-extensions",
             "--no-first-run", "--no-default-browser-check",
             "--virtual-time-budget=9000", "--user-data-dir=" + str(prof), "--dump-dom",
             b.url("/chat") + "#" + hashname],
            capture_output=True, timeout=120)
        return out.stdout.decode("utf-8", "replace")

    def dom(hashname: str, must: str = "", gone: str = "", tries: int = 4) -> str:
        """DOM 을 받는다. ``must`` 를 주면 그것이 나타날 때까지 다시 띄운다.

        ``gone`` 을 주면 그 글자가 **사라질 때까지** 다시 띄운다(예: "확인 중" 은
        상태 칩의 초기값이다 — 사라졌다면 boot 이 끝까지 갔다는 뜻).

        --dump-dom 은 페이지가 끝났다고 판단한 순간 찍는다. boot 이 fetch 를 몇 번 기다리는
        화면이라 그 순간이 가끔 이르다 — 그러면 진짜 고장과 구별이 안 된다.
        깜빡이는 검사는 없는 검사보다 나쁘다(사람이 결과를 안 믿게 된다). 세 번 본다.
        """
        last = ""
        for _ in range(max(1, tries)):
            last = _once(hashname)
            if (not must or must in last) and (not gone or gone not in last):
                return last
        return last

    talk = dom("talk", "장면으로 조립", gone="글자 확인 중")
    ok(len(talk) > 2000, "대화 화면이 거의 비어 있다(%d바이트) — 스크립트가 죽었다" % len(talk))
    for probe, why in (("로컬 LLM 스튜디오", "앱 이름"), ('id="live"', "고정 진행 자리"),
                       ('id="tabList"', "목록 탭 버튼"), ('id="tabCast"', "고유캐릭터 탭 버튼"),
                       ("장면으로 조립", "조립 버튼")):
        ok(probe in talk, "대화 화면에 %s 가 없다" % why)

    # 고유캐릭터 탭도 진짜로 그려지는가 — 버튼만 있고 화면이 안 열리는 상태가 흔하다
    # 여기서 보는 것은 **화면이 열리는가** 까지다. 서랍 내용(인물·사진·얼굴 고정 안내)은
    # 화면이 뜬 뒤에 받아 오는데, --dump-dom 은 그 응답을 기다려 주지 않는다 —
    # 그걸 여기서 단정하면 검사가 기계 부하에 따라 깜빡인다. 그 내용은 W38 이 본다.
    cast = dom("cast", "대화에서 만들기")
    for probe, why in (("대화에서 만들기", "[+ 대화에서 만들기]"), ("+ 빈 인물", "[+ 빈 인물]")):
        ok(probe in cast, "고유캐릭터 화면에 %s 가 없다" % why)

    lst = dom("list", 'class="chatlist"')
    ok('class="chatlist"' in lst, "목록 화면이 안 그려졌다 — 주소창 해시로 탭이 안 열린다")
    for probe, why in (("가져오기", "[가져오기] 버튼"), ("내보내기", "[내보내기] 버튼"),
                       ('type="file"', "파일 고르기"), ("+ 새 대화", "[+ 새 대화]"),
                       ("+ 시크릿 대화", "[+ 시크릿 대화]")):
        ok(probe in lst, "목록 화면에 %s 가 없다" % why)

    # 탭마다 다른 것이 그려져야 한다 — 같은 DOM 이 나오면 해시 라우팅이 죽은 것이다
    ok(lst != talk, "목록과 대화가 같은 화면을 그린다 — 탭 전환이 동작하지 않는다")

    # 스크립트가 죽으면 이 표시들은 초기값('확인 중') 그대로 남는다(boot 이 끝까지 못 갔다는 뜻).
    #
    # **'확인 실패' 도 갱신이다.** 처음엔 연결/끊김/거부만 받았는데, 상태 조회 자체가
    # 실패하면 칩은 "글자 확인 실패" 가 된다 — 화면은 멀쩡히 끝까지 갔는데 검사만
    # 빨간불이었고, 그게 5회 중 1회씩 깜빡이던 나머지 이유였다.
    chip = ""
    at = talk.find('id="chipLlm"')
    if at >= 0:
        chip = " ".join(talk[at:at + 120].split())
    settled = any(w in talk for w in ("연결", "끊김", "거부", "확인 실패"))
    if not settled:
        # 두 가지가 같은 모습이다: **화면이 안 바꿨다**(진짜 고장)와 **상태 조회가 아직
        # 안 끝났다**(이 기계가 느리거나 모델 쪽 연결이 오래 걸린다). 둘을 가르지 않으면
        # 이 검사는 4~6회에 한 번씩 깜빡이고, 깜빡이는 검사는 없는 검사보다 나쁘다 —
        # 사람이 결과를 안 믿게 된다. 그래서 **조회에 걸리는 시간을 직접 잰다.**
        t0 = time.time()
        b.wapi("/api/talk-status", {})
        slow = time.time() - t0
        ok(slow > 3.0,
           "상태 칩이 갱신되지 않았다 — 상태 조회는 %.1f초면 끝나는데 화면이 안 바꿨다. 칩: %s"
           % (slow, chip or "(못 찾음)"))


@test("unit", "U40 남은 시간 — 절대 올라가지 않고, 배치 경계를 넘고, 멈춘 작업을 숨기지 않는다")
def u40(b: Box):
    """씽크북 실측이 톱니를 찾아냈다(total 6 · batch 3 · 실제 240.2초):

        t=3s  어림 179/실제 240   t=53s 254/190   t=73s **354**/170   t=83s 161/160

    배치 안에서 올라가고 배치 경계에서 뚝 떨어진다. 사람이 보는 것은 "3분 남음 →
    2분 남음 → **갑자기 6분 남음**" 이고, 그때 사람은 '어림이 틀렸다'로 읽지 않는다.
    '작업이 고장 났다'로 읽고 새로고침한다 — 5분짜리 작업을 사람 손으로 끊게 만든다.

    원인 둘: 장면당 시간을 작업 시작부터 나눠서(앞머리 비용이 모든 장면에 발린다)
    기다리는 동안 계속 커졌고, 남은 배치가 치를 앞머리를 세지 않았다.

    잠그는 것은 셋이다.
      (1) **절대 올라가지 않는다** — 어림이 커지면 숫자를 올리는 대신 그 자리에 멈춘다.
      (2) **배치 경계를 넘는다** — 아직 시작 안 한 배치의 앞머리를 센다.
      (3) **멈춘 작업을 숨기지 않는다** — 오래 아무것도 안 오면 '늦음'을 켠다.
          이게 없으면 진짜로 죽은 작업 위에 평평한 숫자 하나가 영원히 떠 있는다.
    """
    vc = b.mod("vn_compose")
    T0 = 1_000_000.0
    real_time = vc.time.time

    def replay(arrivals, until, total=6, batch=3):
        """도착 시각표를 재생하고 [(t, eta, late)] 를 돌려준다."""
        clock = {"t": T0}
        vc.time.time = lambda: clock["t"]
        vc._ETA.update(shown=None, at=0.0, raw=None)
        out = []
        for t in range(3, int(until) + 1, 10):
            clock["t"] = T0 + t
            done = sum(1 for a in arrivals if a <= t)
            gaps = [arrivals[k] - arrivals[k - 1] for k in range(1, done)]
            job = {"running": True, "total": total, "batch": batch, "started_at": T0,
                   "items": [{}] * done,
                   "first_at": (T0 + arrivals[0]) if done else 0,
                   "last_at": (T0 + arrivals[done - 1]) if done else 0,
                   "min_gap": min(gaps) if gaps else 0}
            eta, late = vc._eta_shown(job)
            out.append((t, eta, late))
        return out

    try:
        # (1)(2) 실측 시각표 — 한 번도 올라가지 않고, '늦음'도 뜨지 않는다(정상 실행이므로)
        rows = replay([50, 80, 90, 175, 200, 240], 240)
        ups = [r for i, r in enumerate(rows) if i and r[1] > rows[i - 1][1]]
        ok(not ups, "남은 시간이 올라갔다 — 사람은 이걸 고장으로 읽는다: %s" % ups[:3])
        ok(not any(r[2] for r in rows), "정상 실행인데 '늦음'이 떴다 — 늘 뜨면 아무 뜻이 없다")

        # 배치 경계(장면 3개째, t=93)에서 다음 배치의 앞머리를 세는가 —
        # 안 세면 여기서 숫자가 절반 아래로 뚝 떨어진다
        at83 = [r for r in rows if r[0] == 83][0][1]
        at93 = [r for r in rows if r[0] == 93][0][1]
        ok(at93 >= at83 * 0.5,
           "배치 경계에서 남은 시간이 절반 아래로 무너졌다(%d초 → %d초) — 다음 배치의 "
           "앞머리를 안 세고 있다" % (at83, at93))

        # 어림이 실제와 크게 어긋나지 않는가 (예전: -61초 ~ +184초)
        worst = 0
        for t, eta, _late in rows:
            worst = max(worst, abs(eta - (240 - t)))
        ok(worst <= 90, "어림이 실제와 %d초나 어긋난다 — 예전(184초)보다 낫지 않다" % worst)

        # (1b) **느려지는 실행** — 장면 간격이 10초에서 70초로 벌어지면
        #      어림 자체는 반드시 커진다. 그때도 화면 숫자는 올라가면 안 된다 —
        #      막아 주는 것이 단조 감소 잠금이고, 이 경우가 그 잠금이 유일하게 일하는 자리다.
        slowing = replay([40, 50, 120, 200, 290, 390], 400, total=6, batch=6)
        ups2 = [r for i, r in enumerate(slowing) if i and r[1] > slowing[i - 1][1]]
        ok(not ups2, "점점 느려지는 실행에서 남은 시간이 올라갔다: %s" % ups2[:3])
        ok(any(r[2] for r in slowing),
           "어림이 커졌는데 '늦음'을 한 번도 안 알렸다 — 숫자만 막고 입을 닫은 꼴이다")

        # (1c) **얼어 있지 않은가.** 올라가는 것을 막았더니 이번엔 장면 하나를 기다리는
        #      25~40초 동안 숫자가 그대로 멈춰 있었다(씽크북 재측정). 그것도 "작업이
        #      멈췄나" 로 읽힌다. 시계를 따라 내리되 물리적 하한(남은 장면 × 관측된 가장
        #      빠른 간격)을 바닥으로 둔다 — 바닥에서 멈춰 있는 것은 정직하다.
        healthy = replay([40, 75, 115, 145, 170, 190], 190)
        longest, run = 0, 0
        for i, r in enumerate(healthy):
            if i and r[1] == healthy[i - 1][1]:
                run += 10
                longest = max(longest, run)
            else:
                run = 0
        ok(longest <= 20,
           "정상 실행인데 남은 시간이 %d초나 멈춰 있다 — 사람은 멈춘 숫자를 "
           "'작업이 멈췄나' 로 읽는다" % longest)
        ok(not any(r[2] for r in healthy), "정상 재측정 실행에서 '늦음'이 떠 버렸다")
        ok(all(r[1] >= 0 for r in healthy), "남은 시간이 음수가 됐다")
        # (3) 3장 받고 멈춘 작업 — 언젠가는 '늦음'이 떠야 한다
        stalled = replay([50, 80, 90], 400)
        ok(any(r[2] for r in stalled),
           "작업이 멈췄는데 '늦음'이 한 번도 안 떴다 — 평평한 숫자가 영원히 떠 있는다")
        ok(all(r[1] > 0 for r in stalled),
           "멈춘 작업에서 남은 시간이 0 까지 내려앉았다 — 바닥이 없다. "
           "0 을 보여 주고도 끝나지 않는 것은 얼어붙은 숫자보다 더 나쁜 거짓말이다")
        first_late = [r[0] for r in stalled if r[2]][0]
        ok(first_late > 90, "마지막 장면이 오자마자 '늦음'이 떴다(t=%d) — 너무 성급하다" % first_late)

        # 안 도는 작업에는 숫자가 없다
        eta, late = vc._eta_shown({"running": False})
        eq(eta, None, "안 도는 작업에 남은 시간이 나온다")
        eq(late, False, "안 도는 작업이 늦다고 나온다")
    finally:
        vc.time.time = real_time
        vc._ETA.update(shown=None, at=0.0, raw=None)


@test("unit", "U41 모델을 붙잡고 있는 것을 붙잡는 곳에서 센다 — 경로가 늘어도 빠지지 않게")
def u41(b: Box):
    """U39 가 잠근 '줄 서 있을 때의 상한' 에는 구멍이 하나 있었다. 서버가 '지금 바쁘다' 를
    판단하는 근거가 **서버 조립 작업(_JOB) 하나뿐**이었는데, 스튜디오 첫 화면의
    [스토리라인 → 장면 구성](동기 ``/api/compose`` → ``compose_scenes``)은 그 작업을
    거치지 않고 여기서 바로 몇 분을 붙잡는다. 그 경로로 조립하는 동안 대화는 고친 뒤에도
    예전처럼 120초에 죽었다.

    경로마다 '나 바쁘다' 표시를 붙이는 방법도 있었지만, 그러면 **새 경로가 생길 때마다
    빠뜨린다**(이번이 정확히 그 사고다). 그래서 소켓을 들고 있는 한 군데(local_llm.chat)
    에서 센다. 앞으로 어떤 경로가 생겨도 자동으로 포함된다.

    놓는 것도 같이 잠근다 — 실패해서 빠져나가는 길에서 표시가 남으면, 그 뒤 모든 대화가
    영원히 '줄 서 있음' 으로 판단돼 죽은 서버를 15분씩 기다린다.
    """
    web = b.mod("webapp")
    # **webapp 이 실제로 잡고 있는 그 모듈**을 본다. b.mod("local_llm") 은 box_ 접두사로
    # 따로 적재되어 전역 표가 둘로 갈라진다 — 그러면 배선을 시험하는 것이 아니라 서로
    # 모르는 두 사본을 시험하게 된다(실제로 이 검사가 처음에 그렇게 틀렸다).
    ll = web.local_llm

    eq(ll.holding(), [], "시작부터 누가 붙잡고 있다고 나온다")
    eq(web.llm_queue_wait().get("busy"), False, "한가한데 바쁘다고 한다")

    k = ll._hold_begin(8192)
    try:
        held = ll.holding()
        eq(len(held), 1, "붙잡고 있는데 목록이 비어 있다")
        ok(held[0]["elapsed"] >= 0, "경과 시간이 음수다")
        eq(held[0]["max_tokens"], 8192, "요청 크기가 안 실렸다")
        eq(web.llm_queue_wait().get("busy"), True,
           "누가 모델을 붙잡고 있는데 '한가하다' 고 한다 — 뒤에 온 대화가 120초에 죽는다")
        eq(web._chat_timeout(web.llm_queue_wait()), ll.QUEUE_TIMEOUT,
           "줄이 있는데 상한을 안 푼다")
    finally:
        # 여기서 실패해도 표시를 남기지 않는다 — 남으면 뒤따르는 검사가 오염된다
        ll._hold_end(k)
    eq(ll.holding(), [], "놓았는데 표시가 남아 있다")

    # 실패로 빠져나가도 반드시 놓는다 (남으면 이후 모든 대화가 영원히 '줄 서 있음' 이 된다)
    class _Boom:
        def __enter__(self):
            raise OSError("연결 실패")

        def __exit__(self, *a):
            return False

    real_open, real_validate = ll._OPENER.open, ll._validate
    try:
        ll._validate = lambda url: None
        ll._OPENER.open = lambda req, timeout=None: _Boom()
        try:
            ll.chat([{"role": "user", "content": "x"}])
        except Exception:
            pass
    finally:
        ll._OPENER.open, ll._validate = real_open, real_validate
    eq(ll.holding(), [],
       "호출이 실패한 뒤에도 '붙잡고 있음' 이 남았다 — 다음 대화가 전부 줄을 선다")

    # 동기 조립 경로도 같은 통로를 지나는가 (여기가 원래 빠져 있던 자리다)
    vsrc = b.p("tools/vn_compose.py").read_text(encoding="utf-8")
    body = vsrc[vsrc.index("def orch_chat("):]
    body = body[:body.index("\ndef ", 10)]
    ok("local_llm.chat(" in body,
       "동기 조립(orch_chat)이 local_llm.chat 을 지나지 않는다 — 붙잡기 계산에서 빠진다")
    wsrc = b.p("tools/webapp.py").read_text(encoding="utf-8")
    qw = wsrc[wsrc.index("def llm_queue_wait("):]
    qw = qw[:qw.index("\ndef ", 10)]
    ok("local_llm.holding()" in qw,
       "바쁨 판정이 서버 작업 하나만 본다 — 스튜디오의 동기 조립 중에는 여전히 120초에 죽는다")


@test("unit", "U42 닫히지 않은 혼잣말 — 생각하다 잘린 답이 화면에 그대로 뜨지 않는다")
def u42(b: Box):
    """'모델의 사고 과정이 화면에 닿지 않는다' 는 규칙에 구멍이 있었다. 거르는 규칙이
    ``<think>…</think>`` 와 앞이 잘린 ``</think>`` 두 모양만 알고 있어서, **닫는 태그가
    아예 없는** 경우는 한 글자도 안 걸러졌다.

    이건 드문 일이 아니다. 인물 대화는 ``max_tokens`` 가 320 이라 모델이 생각을 그 안에
    못 끝내면 답이 ``<think>음 뭐라고 하지…`` 에서 잘린 채로 온다 — 그러면 인물의 첫마디
    자리에 모델의 혼잣말이 통째로 뜬다.

    그리고 걸러 놓고 **빈 문자열을 조용히 돌려주는 것**도 막는다. 그러면 부르는 쪽이 빈
    대사를 로그에 저장하고, 사람은 무엇이 잘못됐는지 알 길이 없다.
    """
    ll = b.mod("webapp").local_llm      # U41 과 같은 이유 — 사본이 아니라 진짜 배선을 본다
    cases = [
        ("<think>abc</think>Hello", "Hello", "닫힌 혼잣말"),
        ("</think>Hello", "Hello", "앞이 잘린 혼잣말"),
        ("<think>음 뭐라고 하지 계속 생각중", "", "닫히지 않은 혼잣말"),
        ("<think>a</think>Hi<think>또 생각", "Hi", "답 뒤에 또 생각이 붙은 경우"),
        ("Hello", "Hello", "혼잣말 없음"),
        ("", "", "빈 문자열"),
    ]
    for src, want, why in cases:
        eq(ll.strip_reasoning(src), want, "%s 를 잘못 걸렀다: %r" % (why, src))

    # 비었을 때의 안내가 두 사고를 구분하는가 — 같은 문구면 사람은 서버를 껐다 켠다
    thinking = ll._no_text_msg("<think>어...")
    blank = ll._no_text_msg("")
    ok(thinking != blank, "'생각만 하다 잘림' 과 '빈 응답' 이 같은 문구다")
    ok("생각" in thinking, "혼잣말 때문이라는 말이 안내에 없다: %r" % thinking)

    # chat() 이 빈 본문을 조용히 돌려주지 않는다
    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self._p).encode("utf-8")

    payload = {"choices": [{"message": {"content": "<think>생각만 하다 잘림"}}]}
    real_open, real_validate = ll._OPENER.open, ll._validate
    try:
        ll._validate = lambda url: None
        ll._OPENER.open = lambda req, timeout=None: _Resp(payload)
        got = None
        try:
            got = ll.chat([{"role": "user", "content": "x"}])
        except Exception as e:
            got = e
        ok(not isinstance(got, str),
           "생각만 담긴 응답에서 %r 를 돌려줬다 — 빈 대사가 로그에 저장된다" % got)
        ok("생각" in str(got), "무엇 때문에 비었는지 말하지 않는다: %r" % str(got)[:80])
    finally:
        ll._OPENER.open, ll._validate = real_open, real_validate
    eq(ll.holding(), [], "이 경로에서도 '붙잡고 있음' 이 남았다")


@test("unit", "U43 새 대화와 지운 대화를 구별한다 — 그리고 지워도 본문을 버리지 않는다")
def u43(b: Box):
    """이 검사가 막는 것은 **통합 화면의 [+ 새 대화] 가 통째로 죽어 있던 사고**다.

    판정 근거가 '파일이 있느냐' 였다. 그런데 '지워진 대화' 와 '아직 한 마디도 저장되지
    않은 새 대화' 는 디스크에서 완전히 같은 모습이다 — 둘 다 파일이 없다. 그래서 새로
    만든 갈래는 첫 발화마다 "이 대화는 삭제되었습니다. 목록에서 새 대화를 시작하세요"
    로 거절당했다. 시키는 대로 새 대화를 또 만들면 또 같은 거절이 나오는 막다른 골목이라,
    사용자가 요청한 '채팅 창별 문맥 관리' 가 기본 갈래 하나로만 돌아가고 있었다.

    고친 방식은 추측을 사실로 바꾼 것이다: 지웠으면 **지웠다고 적는다**(묘비).

    삭제 쪽도 같이 잠근다. 예전에는 본문을 그냥 unlink 하고 보관 기록만 남겼다 —
    '내가 지운 말'은 남고 '내가 나눈 대화'만 사라지는, 거꾸로 된 보존이었다.
    """
    ts = b.mod("talk_store")
    msgs = [{"role": "user", "content": "비 오는 버스"},
            {"role": "assistant", "content": "좋아요"}]

    # (1) 저장된 적 없는 새 갈래는 '지워진 것' 이 아니다
    ok(not ts.is_deleted_chat("u43brandnew"),
       "한 번도 저장된 적 없는 새 갈래를 '삭제됨' 으로 본다 — [+ 새 대화] 가 첫 발화에서 막힌다")
    ok(not ts.is_deleted_chat(""), "기본 갈래를 삭제됨으로 본다")

    # (2) 지우면 묘비가 선다
    ts.save_log(ts.story_chat_path_for("u43gone"), msgs)
    ts._append_archive(ts.archive_path(ts.story_chat_path_for("u43gone")),
                       [{"role": "assistant", "content": "밀려난 예전 답"}])
    ok(ts.delete_story_chat("u43gone"), "삭제가 실패했다")
    ok(ts.is_deleted_chat("u43gone"), "지웠는데 '삭제됨' 으로 안 보인다 — 지운 대화가 되살아난다")
    ok(not ts.story_chat_path_for("u43gone").exists(), "본문 파일이 남아 있다")

    # (3) 본문과 보관 기록이 **둘 다** 남아 있다
    kept = sorted(p.name for p in ts.STORY_DIR.glob("*u43gone*"))
    ok(kept, "지운 대화의 흔적이 아무것도 없다 — 되돌릴 방법이 사라졌다")
    body = "\n".join((ts.STORY_DIR / n).read_text(encoding="utf-8") for n in kept)
    ok("비 오는 버스" in body, "본문이 보관되지 않았다 — 나눈 대화가 그냥 사라졌다: %s" % kept)
    ok("밀려난 예전 답" in body, "보관 기록이 사라졌다: %s" % kept)

    # (4) **이름이 .gitignore 에 걸리는 모양인가.** 이게 틀리면 사적 대화가 커밋된다.
    for n in kept:
        ok(n.endswith(ts.ARCHIVE_SUFFIX),
           "지운 대화의 보관본 이름이 %r 다 — .gitignore 의 *%s 에 안 걸려 "
           "`git add .` 한 번에 개인 대화가 저장소에 실린다" % (n, ts.ARCHIVE_SUFFIX))

    # (5) 목록에서는 사라진다
    ok("u43gone" not in {r["id"] for r in ts.list_story_chats()}, "지운 대화가 목록에 남아 있다")

    # (6) 가져오기가 묘비 자리를 비켜 간다 (거기로 들어오면 다음 발화가 바로 거절된다)
    ok(ts.free_chat_id("u43gone") != "u43gone",
       "가져오기가 묘비가 선 id 를 그대로 쓴다 — 들어오자마자 '삭제되었습니다' 로 막힌다")


@test("unit", "U44 줄 대기 상한은 호출부가 잊어도 걸린다 — 같은 사고를 세 번 겪고 옮긴 규칙")
def u44(b: Box):
    """같은 결함을 **세 번** 고쳤다. 조립(서버 작업) → 스튜디오의 동기 조립 →
    [프롬프트 생성]·[이 순간을 사진으로]. 매번 '그 경로에도 timeout 을 넘긴다' 로 고쳤고,
    매번 다음 경로에서 다시 나왔다.

    경로마다 손으로 붙이는 규칙은 새 경로가 생길 때마다 빠진다. 그래서 규칙을 옮겼다:
    **소켓을 들고 있는 함수가 스스로 판단한다.** 자기 앞에 줄이 서 있으면(holding)
    큰 상한을 쓴다. 호출부는 아무것도 몰라도 되고, 앞으로 생길 경로도 자동으로 포함된다.

    호출부가 명시하면 그쪽이 이긴다 — 일부러 짧게 주는 곳(자가진단·상태 확인)이 있다.
    """
    ll = b.mod("local_llm")
    seen = {}

    class _Stop:
        def __enter__(self):
            raise ll.VNError("여기까지면 충분하다")

        def __exit__(self, *a):
            return False

    real_open, real_validate = ll._OPENER.open, ll._validate
    try:
        ll._validate = lambda url: None
        ll._OPENER.open = lambda req, timeout=None: seen.update(t=timeout) or _Stop()

        def call(**kw):
            seen.clear()
            try:
                ll.chat([{"role": "user", "content": "x"}], **kw)
            except Exception:
                pass
            return seen.get("t")

        eq(call(), float(ll.TIMEOUT), "한가한데 큰 상한을 쓴다 — 꺼진 서버를 늦게 알아차린다")

        k = ll._hold_begin(8192)          # 다른 호출이 모델을 붙잡고 있다
        try:
            eq(call(), float(ll.QUEUE_TIMEOUT),
               "앞에 줄이 서 있는데 기본 상한을 쓴다 — 이 경로는 120초에 죽는다")
            eq(call(timeout=30), 30.0, "호출부가 명시한 상한을 무시한다")
        finally:
            ll._hold_end(k)

        eq(call(), float(ll.TIMEOUT), "줄이 풀렸는데 계속 큰 상한을 쓴다")
    finally:
        ll._OPENER.open, ll._validate = real_open, real_validate

    # 판단이 _hold_begin **앞**에 있어야 한다 — 뒤면 자기 자신을 '앞의 줄' 로 센다
    src = b.p("tools/local_llm.py").read_text(encoding="utf-8")
    body = src[src.index("def chat("):]
    body = body[:body.index("\ndef ", 10)]
    ok(body.index("if timeout is None and holding()") < body.index("hold = _hold_begin("),
       "줄 확인이 자기 등록보다 뒤에 있다 — 모든 호출이 자기 자신 때문에 큰 상한을 쓴다")


@test("unit", "U45 조립 파서 — 혼잣말을 장면으로 세지 않고, 잘린 응답에서 대사를 장면으로 줍지 않는다")
def u45(b: Box):
    """둘 다 **가짜 장면이 진짜 파일로 저장되던** 길이다.

    (1) 스트리밍 콜백에는 날것이 흘러온다. 반환값 쪽은 strip_reasoning 이 걷어 내지만
        여기는 아니었다 — 모델이 혼잣말 안에서 장면 초안을 써 보면 그게 "3컷 나왔습니다"
        로 집계되고, [받은 것으로 마무리] 를 누르면 파일이 되고, [이어서 더 받기] 는
        start = len(items)+1 이라 **진짜 장면 한 컷을 건너뛴다.**

        판단 기준이 '여는 태그가 있는가' 면 안 된다. 이 모델은 <think> 를 프롬프트 쪽에
        붙이므로 실제로 오는 모양은 **여는 태그 없이** 혼잣말이 먼저 나오고 </think> 로
        끝나는 것이다. 그래서 앞글자를 본다: '[' 나 '{' 면 답이 바로 시작된 것이고,
        아니면 </think> 가 올 때까지 한 글자도 내보내지 않는다.

    (2) 응답이 장면 한가운데서 잘리면 바깥 객체는 파싱에 실패하고 **안쪽 dialogue 배열만**
        온전하게 남는다. 그걸 집으면 [{speaker_id, line}] 이 '장면 목록' 이 되어 purpose·
        camera·image_prompt 가 전부 빈 껍데기 장면이 저장된다. 저장할 때 order 가 1..N 으로
        다시 부여되므로 **구멍의 흔적조차 안 남는다.**
    """
    vc = b.mod("vn_compose")
    S1 = ('{"order":1,"purpose":"진짜1","dialogue":[],"camera":"medium",'
          '"image_prompt":"a girl"}')
    S2 = ('{"order":2,"purpose":"진짜2","dialogue":[],"camera":"wide",'
          '"image_prompt":"a boy"}')
    DRAFT = ('{"order":9,"purpose":"초안","dialogue":[],"camera":"wide",'
             '"image_prompt":"draft"}')

    # (1) 조각 크기를 바꿔 가며 — 실제 SSE 는 조각 경계가 어디든 올 수 있다
    cases = [
        ("여는 태그 없는 혼잣말",
         "음 뭐라 하지 " + DRAFT + " 아니고</think>[" + S1 + "," + S2 + "]",
         ["진짜1", "진짜2"]),
        ("<think> 로 시작", "<think>" + DRAFT + "</think>[" + S1 + "]", ["진짜1"]),
        ("혼잣말 없음", "[" + S1 + "," + S2 + "]", ["진짜1", "진짜2"]),
        ("코드펜스", "```json\n[" + S1 + "]", ["진짜1"]),
        ("혼잣말만(안 닫힘)", "음 생각중 " + DRAFT + " 계속", []),
    ]
    for label, text, want in cases:
        for size in (1, 7, 64, 10 ** 6):
            got = []
            st = vc._SceneStream(lambda o: got.append(o.get("purpose")))
            for i in range(0, len(text), size):
                st.feed(text[i:i + size])
            eq(got, want, "%s (조각 %s자) 에서 장면 집계가 틀렸다" % (label, size))

    # (2) 잘린 응답 — 대사 배열을 장면 목록으로 줍지 않는다
    truncated = '[' + S1[:-18] + ', "image_prompt":"a gi'
    try:
        got = vc._extract_json_array(truncated)
        ok(False, "잘린 응답에서 %r 를 장면 목록으로 집었다 — 빈 껍데기가 저장된다" % (got,))
    except ValueError:
        pass
    try:
        vc._extract_json_array('[{"speaker_id":"CHAR-001","line":"안녕"}]')
        ok(False, "대사 배열을 장면 목록으로 집었다")
    except ValueError:
        pass

    # 멀쩡한 세 모양은 그대로 읽는다 (실측에서 7회 중 3·2·2 로 나뉘던 모양들)
    eq(len(vc._extract_json_array('[' + S1 + ',' + S2 + ']')), 2, "진짜 배열을 못 읽는다")
    eq(len(vc._extract_json_array('{"scenes":[' + S1 + ']}')), 1, "포장된 배열을 못 읽는다")
    eq(len(vc._extract_json_array(S1 + "\n" + S2)), 2, "객체 나열을 못 읽는다")


@test("unit", "U46 답을 기다리는 사이 대화가 바뀌면 그 답을 붙이지 않는다")
def u46(b: Box):
    """검사가 **모델 앞에만** 있었다. 그런데 지우기·자르기는 정확히 그 1~2분 사이에
    다른 기기에서 일어난다 — 폰에서 지우고 PC 가 답을 받는 식이다.

    그러면 두 가지가 일어났다. 지운 대화가 **되살아나고**(보관 기록은 이미 떠난 반쪽으로),
    [수정]·[다시 생성] 으로 걷어낸 말이 클라이언트가 보낸 옛 목록을 통해 **다시 붙었다.**
    사용자는 지운 답이 되살아나 같은 질문에 두 개의 답이 어긋난 순서로 남은 것을 본다.

    답 하나를 버리는 쪽을 고른다 — 다시 물어보면 되지만, 되살아난 말은 손으로 지워야 하고
    그 사이 보관 기록은 이미 갈라져 있다.
    """
    import threading
    import time as _t
    web = b.mod("webapp")
    ts = b.mod("talk_store")
    vc = b.mod("vn_compose")
    web.talk_store, web.vn_compose = ts, vc

    msgs = [{"role": "user", "content": "첫 말"},
            {"role": "assistant", "content": "답1"},
            {"role": "user", "content": "둘째 말"}]
    real = vc.orch_chat
    try:
        vc.orch_chat = lambda *a, **k: (_t.sleep(0.5), "느린 답")[1]

        # (1) 기다리는 사이 삭제되면 붙이지 않는다
        ts.save_log(ts.story_chat_path_for("u46del"), msgs)
        th = threading.Timer(0.15, lambda: ts.delete_story_chat("u46del"))
        th.start()
        try:
            web.do_chat(msgs, "u46del")
            ok(False, "지워진 대화에 답을 붙였다 — 지운 대화가 되살아난다")
        except Exception as e:
            ok("삭제" in str(e), "거절 사유가 삭제라고 말하지 않는다: %s" % str(e)[:60])
        th.join()

        # (2) 기다리는 사이 짧아지면 붙이지 않는다 (옛 목록으로 되살리지 않는다)
        ts.save_log(ts.story_chat_path_for("u46trim"), msgs)
        th = threading.Timer(0.15,
                             lambda: ts.truncate_log(ts.story_chat_path_for("u46trim"), 1))
        th.start()
        try:
            web.do_chat(msgs, "u46trim")
            ok(False, "잘린 대화에 옛 목록을 병합했다 — 걷어낸 말이 되살아난다")
        except Exception as e:
            ok("바뀌" in str(e), "거절 사유를 말하지 않는다: %s" % str(e)[:60])
        th.join()
        eq(len(ts.load_log(ts.story_chat_path_for("u46trim"))), 1,
           "잘린 대화가 다시 길어졌다 — 되살아났다")

        # (3) 아무 일도 없으면 평소대로 저장된다
        ts.save_log(ts.story_chat_path_for("u46ok"), msgs)
        eq(web.do_chat(msgs, "u46ok"), "느린 답", "평범한 경우가 막혔다")
        eq(len(ts.load_log(ts.story_chat_path_for("u46ok"))), 4, "답이 저장되지 않았다")
    finally:
        vc.orch_chat = real


@test("unit", "U47 작품 전환 — 대화마다 자기 장면·그림, 그리고 어떤 경우에도 잃지 않는다")
def u47(b: Box):
    """통합 화면의 '목록' 은 대화를 갈라 주는데 **입력만 갈라지고 출력은 하나였다.**
    장면은 ``project/scenes/`` 한 폴더에 살고 ``/api/state`` 는 chat_id 를 받지도 않아서,
    어느 대화를 열든 같은 장면이 보였다. 대화 2에서 조립하면 "이미 장면이 있습니다" 로
    막히고, 덮어쓰면 대화 1의 작품이 사라졌다.

    하위 폴더로 나눌 수가 없다 — 판정자 ``check_protocol.py`` 가 수정 금지인데
    ``project/scenes/*.json`` 을 하드코딩으로 훑는다. 그래서 자리는 하나로 두고
    **올라와 있는 작품을 갈아 끼운다**(폴더 이름 바꾸기라 150MB 라도 즉시 끝난다).

    이 검사가 지키는 것은 하나다: **장면과 그림을 잃지 않는다.** 되돌릴 수 없는 자산이라
    전환 한 번의 버그가 몇 시간짜리 작업을 지운다. 그래서 왕복·중단·충돌을 다 본다.
    """
    wk = b.mod("works")
    root = b.root / "wtest"
    wk.WORKS = root / "project" / "works"
    wk.STATE = root / "project" / "works_state.json"
    wk.SCENES = root / "project" / "scenes"
    wk.IMAGES_RAW = root / "images" / "raw"
    wk._PAIRS = (("scenes", lambda: wk.SCENES), ("images_raw", lambda: wk.IMAGES_RAW))

    def make(n, tag):
        wk.SCENES.mkdir(parents=True, exist_ok=True)
        wk.IMAGES_RAW.mkdir(parents=True, exist_ok=True)
        for i in range(1, n + 1):
            sid = "SCENE-%03d" % i
            (wk.SCENES / (sid + ".json")).write_text(
                json.dumps({"scene_id": sid, "tag": tag}), encoding="utf-8")
            d = wk.IMAGES_RAW / sid
            d.mkdir(exist_ok=True)
            (d / "a.png").write_bytes(b"P" + tag.encode())

    def tag_now():
        sc = sorted(wk.SCENES.glob("*.json")) if wk.SCENES.exists() else []
        return json.loads(sc[0].read_text(encoding="utf-8"))["tag"] if sc else "-"

    def totals():
        return (sum(1 for _ in (root / "project").rglob("SCENE-*.json")),
                sum(1 for _ in root.rglob("*.png")))

    # (1) 대화마다 자기 작품을 갖는다 — 왕복해도 서로 섞이지 않는다
    make(4, "A")
    eq(wk.current(), "", "처음 올라와 있는 작품이 기본 갈래가 아니다")
    wk.switch("beta")
    eq(tag_now(), "-", "새 대화를 열었는데 앞 대화의 장면이 그대로 보인다 — 출력이 안 갈라졌다")
    make(3, "B")
    wk.switch("")
    eq(tag_now(), "A", "기본으로 돌아왔는데 A 가 없다")
    eq(len(list(wk.SCENES.glob("*.json"))), 4, "A 의 장면 수가 변했다")
    wk.switch("beta")
    eq(tag_now(), "B", "beta 로 돌아왔는데 B 가 없다")
    eq(totals(), (7, 7), "왕복하면서 파일이 사라졌다: %s" % (totals(),))

    # (2) 중단 복구 — 기본 갈래로 이동하다 죽은 경우. id 가 빈 문자열이라 여기가 함정이었다:
    #     목적지 값만으로 판단하면 "기본으로 이동 중" 과 "이동 중 아님" 이 같아진다.
    wk._write_state({"current": "beta", "moving": True, "to": "", "at": 0})
    wk._park("beta")
    ok(not wk.SCENES.exists(), "내려간 상태를 만들지 못했다 — 검사가 성립하지 않는다")
    r = wk.repair()
    eq(r.get("action"), "finished", "내린 뒤 죽은 전환을 마저 올리지 않는다: %s" % r)
    eq(tag_now(), "A", "복구했는데 엉뚱한 작품이 올라왔다")
    eq(wk.current(), "", "복구 뒤 기록된 주인이 틀렸다")

    # (3) 안전망 — 이동 표시가 없는데 자리만 비어 있어도 되살린다
    wk._park("")
    wk._write_state({"current": ""})
    r = wk.repair()
    eq(r.get("action"), "remounted", "빈 자리를 되살리지 않는다 — 화면이 빈 채로 남는다: %s" % r)
    eq(tag_now(), "A", "되살린 작품이 다르다")

    # (4) 보관소가 차 있으면 **덮지 않고 거절한다.** 덮으면 그쪽 작품이 사라진다.
    stash = wk.WORKS / "_default" / "scenes"
    stash.mkdir(parents=True, exist_ok=True)
    (stash / "SCENE-099.json").write_text('{"scene_id":"SCENE-099","tag":"Z"}', encoding="utf-8")
    try:
        wk.switch("beta")
        ok(False, "보관소가 차 있는데 전환했다 — 쉬고 있던 작품을 덮어쓴다")
    except Exception as exc:
        # 사람이 읽을 수 있는 거절이어야 한다. OS 오류가 그대로 올라오면 화면에
        # WinError 역추적이 뜨고, 사람은 무엇을 정리해야 하는지 알 수 없다.
        ok("보관소" in str(exc),
           "거절 문구가 날것이다(가드가 아니라 OS 가 막은 것): %r" % str(exc)[:80])
    ok((stash / "SCENE-099.json").exists(),
       "거절했다면서 보관소의 장면을 덮었다 — 쉬고 있던 작품이 사라졌다")
    eq(tag_now(), "A", "거절한 뒤 화면이 비었다 — 실패는 아무것도 바꾸지 않아야 한다")
    eq(totals()[0] >= 7, True, "거절 과정에서 장면이 사라졌다")

    # (5) 같은 작품으로 전환하는 것은 **아무 일도 하지 않는다**
    #     (대화를 열 때마다 불리므로, 파일을 안 건드리는 것이 기본 동작이어야 한다)
    shutil.rmtree(wk.WORKS / "_default" / "scenes", ignore_errors=True)
    r = wk.switch("")
    eq(r.get("switched"), False, "같은 작품인데 파일을 옮겼다")
    eq(tag_now(), "A", "제자리 전환이 작품을 바꿨다")


@test("unit", "U48 조립은 **지금 이 대화**를 읽는다 — 새로 쓴 대목만, 기존 장면 뒤에 이어서")
def u48(b: Box):
    """사용자 신고: "대화와 장면 만들기의 내용이 다름." 맞았다.

    ``build_compose_instruction`` 은 project/story/storyline.md 를 읽는데, 통합 화면은
    그 파일을 **한 번도 쓰지 않는다**(chat_ui.js 에 storyline 이라는 낱말이 0번 나온다).
    그래서 사람은 대화창에 이야기를 쓰고 [장면으로 조립] 을 누르는데, 조립은 엉뚱한 예전
    문서를 읽어 그걸로 장면을 만들었다. 실측: 대화는 고양이·공원인데 붙은 장면 3개가
    전부 "카페에서 지혜와…" 였다. 두 화면이 서로 다른 작품을 보고 있었다.

    같이 고친 것이 '통으로 굽지 않는다' 이다. 예전에는 누를 때마다 "총 몇 장면?" 을 묻고
    그만큼을 한 번에 만들었다(기본 6개 = 3~4분). 사람이 원한 것은 "대화하다 누르면 그
    대목이 장면이 되는 것" 이라, 새로 쓴 분량에 든 만큼만(최대 4개) 만들고 **기존 장면
    뒤에 이어 붙인다.** 이어 붙이기는 앞 장면을 한 글자도 건드리지 않는다.
    """
    vc = b.mod("vn_compose")
    ts = b.mod("talk_store")

    # (1) 지시문이 **넘겨준 이야기**를 읽는가 — 스토리라인 파일이 아니라
    (b.p("project/story")).mkdir(parents=True, exist_ok=True)
    (b.p("project/story/storyline.md")).write_text(
        "옛 문서: 지혜와 카페에서 만난다.", encoding="utf-8")
    ins = vc.build_compose_instruction(3, False, source="고양이가 공원을 산책한다.")
    ok("고양이" in ins, "넘겨준 이야기가 지시문에 없다 — 대화를 읽지 않는다")
    ok("지혜" not in ins, "넘겨준 이야기가 있는데도 예전 스토리라인이 섞였다")
    # 안 넘기면 예전대로 파일을 읽는다(스튜디오의 통짜 구성 경로는 그대로여야 한다)
    old = vc.build_compose_instruction(3, False)
    ok("지혜" in old, "source 를 안 줬는데 스토리라인 파일을 안 읽는다 — 옛 경로가 깨졌다")

    # (2) 어디까지 만들었는지 기억하는가 — 없으면 누를 때마다 처음부터 다시 만든다
    eq(ts.chat_composed_upto("u48"), 0, "처음부터 조립한 것으로 나온다")
    ts.set_chat_composed_upto("u48", 4)
    eq(ts.chat_composed_upto("u48"), 4, "조립 지점이 저장되지 않는다")
    ts.set_chat_composed_upto("u48", 2)
    eq(ts.chat_composed_upto("u48"), 4, "조립 지점이 뒤로 갔다 — 같은 대목을 두 번 만든다")

    # (3) 이어 붙이기가 **기존 장면을 건드리지 않는가**
    so = b.mod("scene_ops")
    before = [f.name for f in vn_core_files(b)]
    ok(before, "샌드박스에 기존 장면이 없다 — 이 검사가 성립하지 않는다")
    first = b.p("project/scenes") / before[0]
    keep = first.read_bytes()
    items = [{"order": 1, "purpose": "고양이가 문을 나선다", "camera": {"shot": "wide"},
              "dialogue": [], "characters": [], "location_id": "",
              "image_prompt": "a cat at the door"}]
    res = vc.append_scenes_from_items(items)
    eq(res["count"], 1, "이어 붙인 장면 수가 다르다")
    eq(res["appended_after"], len(before), "기존 장면 뒤가 아닌 자리에 붙였다")
    ok(res["created"][0] not in before, "기존 장면 번호를 다시 썼다 — 덮어쓰기 사고다")
    eq(first.read_bytes(), keep, "기존 장면 파일이 변했다 — 이어 붙이기가 앞을 건드렸다")
    after = [f.name for f in vn_core_files(b)]
    eq(len(after), len(before) + 1, "장면 수가 하나 늘지 않았다: %s" % after)


def vn_core_files(b: Box):
    """샌드박스의 장면 파일 목록 — b.mod('vn_core') 는 샌드박스를 본다."""
    return sorted(b.mod("vn_core").scene_files())


@test("unit", "U49 그림체 사전 설정 — 체크포인트까지 갈리고, 못 찾으면 조용히 다른 그림체로 굽지 않는다")
def u49(b: Box):
    """그림체를 바꾸는 진짜 레버는 **체크포인트**다. 같은 모델에 "photorealistic" 을 적어
    봐야 애니 모델은 반실사까지만 가고, 실사 모델에 "anime" 를 적으면 어색한 중간이 된다.
    그래서 프리셋은 체크포인트와 문구를 한 쌍으로 묶는다.

    체크포인트를 **파일 이름 조각으로 찾는** 이유: 사람이 모델을 새 판으로 바꾸면
    (v170 → v180) 이름이 달라지는데, 그때마다 코드를 고쳐야 하면 프리셋이 조용히 죽는다.

    못 찾았을 때가 중요하다. 그냥 아무 모델로 구우면 **고른 것과 다른 그림체**가 나오는데
    사람은 그 사실을 모른다 — 23초를 쓰고 나서야 이상하다고 느낀다. 반드시 말해야 한다.
    """
    cc = b.mod("comfyui_client")
    real = cc.checkpoints
    try:
        cc.checkpoints = lambda refresh=False: [
            "waiIllustriousSDXL_v170.safetensors",
            "juggernautXL_ragnarok.safetensors",
        ]
        r = cc.resolve_style("real")
        ok("juggernaut" in r["ckpt"].lower(), "실사풍이 실사 모델을 안 고른다: %s" % r["ckpt"])
        ok(r["found"], "찾았는데 못 찾았다고 한다")
        ok("photorealistic" in r["positive"], "실사 문구가 없다")
        for k in ("webtoon", "anime"):
            r = cc.resolve_style(k)
            ok("illustrious" in r["ckpt"].lower(), "%s 가 애니 모델을 안 고른다" % k)
        # 이름이 바뀌어도 조각으로 찾는다
        cc.checkpoints = lambda refresh=False: ["waiIllustriousSDXL_v999_final.safetensors"]
        ok(cc.resolve_style("webtoon")["found"], "판이 바뀐 이름을 못 찾는다 — 프리셋이 죽는다")

        # 못 찾으면 **말한다**
        cc.checkpoints = lambda refresh=False: ["somethingElse.safetensors"]
        r = cc.resolve_style("real")
        eq(r["found"], False, "없는데 찾았다고 한다")
        ok(r["note"], "못 찾았는데 아무 말도 안 한다 — 다른 그림체로 조용히 굽는다")
        ok("실사" in r["note"], "무엇을 못 찾았는지 말하지 않는다: %r" % r["note"])
    finally:
        cc.checkpoints = real

    # 모르는 키는 거절한다(요청 body 로 들어오는 값이다)
    try:
        cc.set_style("nosuchstyle")
        ok(False, "모르는 그림체를 저장했다")
    except Exception as exc:
        ok("nosuchstyle" in str(exc), "무엇이 잘못됐는지 말하지 않는다")

    # 그림체를 고르면 저장된 프롬프트 안의 옛 그림체 문구를 걷어낸다 —
    # 안 걷으면 한 프롬프트 안에서 "cel-shaded webtoon" 과 "photorealistic" 이 싸운다
    mf = json.loads(b.p("project/manifest.json").read_text(encoding="utf-8"))
    style = str(mf.get("visual_style") or "")
    if style:
        mixed = style + ", a cat looking up at a butterfly"
        out = cc._drop_style_words(mixed)
        ok(style.lower() not in out.lower(), "옛 그림체 문구가 남았다: %r" % out[:80])
        ok("butterfly" in out, "본문까지 지웠다: %r" % out[:80])


@test("unit", "U50 장면 추가·삭제 — 지운 장면은 버리지 않고, 승인된 장면은 지워지지 않는다")
def u50(b: Box):
    """장면과 그 그림은 다시 만들 수 없다(그림 한 장에 23초, 승인은 사람의 시간이다).
    그래서 삭제도 이 저장소의 다른 되돌릴 수 없는 동작들과 같은 규칙을 쓴다 — 지우는 대신
    옮긴다. 장면 파일과 컷 폴더가 통째로 project/scenes_deleted/ 로 간다.

    **승인된 장면은 거절한다.** 사람 승인 게이트를 '지우기' 로 우회할 수 있으면 그 게이트는
    없는 것과 같다.

    번호는 다시 매기지 않는다. SCENE-003 을 지워도 004 는 004 로 남는다 — 번호를 당기면
    이미 구운 그림 폴더(images/raw/SCENE-004)와 감상본의 이동 대상(goto)이 전부 어긋난다.
    """
    so = b.mod("scene_ops")
    vc = b.mod("vn_core")

    made = so.create_scene(fields={"purpose": "U50 시험", "status": "SCENE_PLAN"})
    sid = made["scene_id"]
    folder = vc.IMAGES_RAW / sid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "a.png").write_bytes(b"PNG")
    before = len(vc.scene_files())

    res = so.delete_scene(sid, "시험")
    eq(res["scene"], True, "장면 파일을 못 옮겼다")
    eq(res["images"], 1, "컷 폴더가 같이 가지 않았다")
    ok(not (vc.SCENES / (sid + ".json")).exists(), "지웠는데 장면 파일이 남아 있다")
    ok(not folder.exists(), "컷 폴더가 제자리에 남아 있다")
    eq(len(vc.scene_files()), before - 1, "장면 수가 하나 줄지 않았다")

    home = vc.PROJECT / "scenes_deleted" / res["archived_to"]
    ok(home.is_dir(), "보관소가 없다 — 되돌릴 방법이 사라졌다")
    kept = sorted(p.name for p in home.rglob("*") if p.is_file())
    ok(any(n.endswith(".json") for n in kept), "장면 파일이 보관되지 않았다: %s" % kept)
    ok(any(n.endswith(".png") for n in kept), "그림이 보관되지 않았다: %s" % kept)
    ok(any(n == "why.txt" for n in kept), "지운 사유가 남지 않았다: %s" % kept)

    # 승인된 장면은 거절 — 그리고 거절 뒤에도 그 장면은 그대로 있어야 한다.
    # 샌드박스에 승인된 장면이 있기를 **기다리지 않는다** — 없으면 이 가드가
    # 통째로 안 시험되고, 그걸 모른 채 통과한다(돌연변이가 그걸 드러냈다).
    made2 = so.create_scene(fields={"purpose": "U50 승인본", "status": "SCENE_PLAN"})
    appr = made2["scene_id"]
    ap_path = vc.SCENES / (appr + ".json")
    _sc = json.loads(ap_path.read_text(encoding="utf-8"))
    _sc["status"] = "APPROVED"
    ap_path.write_text(json.dumps(_sc, ensure_ascii=False), encoding="utf-8")
    if appr:
        keep = (vc.SCENES / (appr + ".json")).read_bytes()
        try:
            so.delete_scene(appr)
            ok(False, "승인된 장면을 지웠다 — 사람 승인 게이트가 우회된다")
        except Exception as exc:
            ok("APPROVED" in str(exc) or "되돌" in str(exc),
               "거절 사유가 승인 잠금이라고 말하지 않는다: %s" % str(exc)[:60])
        eq((vc.SCENES / (appr + ".json")).read_bytes(), keep, "거절했는데 장면이 변했다")
        # 샌드박스는 모든 테스트가 함께 쓴다 — 사람 손으로 APPROVED 로 놓은 이
        # 장면은 그림도 프롬프트도 없어 검사기 기준으로는 깨진 상태다.
        # 내가 만들었으니 내가 치운다 — 안 치우면 뒤에 오는 테스트가 내 쓰레기를 보고 운다.
        _sc["status"] = "SCENE_PLAN"
        ap_path.write_text(json.dumps(_sc, ensure_ascii=False), encoding="utf-8")
        so.delete_scene(appr, "U50 뒷정리")


@test("unit", "U51 고유 캐릭터 서랍 — 대화를 갈아 끼워도 남고, 사진은 그림만 받고, 지워도 매니페스트에서 빠지지 않는다")
def u51(b: Box):
    """사람이 공들여 만든 인물은 **작품보다 오래 산다.** 작품(장면·그림)은 대화마다
    갈아 끼우는데(works), 인물까지 같이 갈리면 고양이 이야기에서 만든 인물을 다음
    단편에서 쓸 수가 없다. 그래서 서랍은 works 가 건드리지 않는 자리에 있다.

    세 가지가 조용히 틀리기 쉬운 자리다.

    (1) **사진.** 사람이 자기 기기에서 고른 파일이 그대로 서버 디스크에 앉고, 나중에
        웹으로 다시 나간다. 확장자를 믿으면 그 경로가 임의 파일 배달로 변한다 —
        머리 바이트로 판정해야 한다.

    (2) **지우기.** 매니페스트에서까지 빼 버리면, 그 인물이 나오는 **다른 작품의 장면**이
        통째로 A2 FAIL 이 된다. 사람은 건드린 적도 없는 작품이 왜 빨간지 알 수 없다.
        그래서 서랍에서만 내리고 매니페스트의 사본은 남긴다.

    (3) **번호.** 지운 인물의 번호를 다시 쓰면, 보관소에서 되살렸을 때 두 사람이 같은
        id 를 갖는다 — 그때부터 어느 쪽 얼굴이 나올지는 운이다.
    """
    ch = b.mod("characters")
    vc = b.mod("vn_core")
    root = b.root / "ctest"
    keep = (ch.DIR, ch.REFS, ch.ARCHIVE)
    mf_path = vc.PROJECT / "manifest.json"
    mf_keep = mf_path.read_bytes()          # 샌드박스는 공용이다 — 매니페스트는 원상 복구한다
    ch.DIR = root / "characters"
    ch.REFS = ch.DIR / "refs"
    ch.ARCHIVE = root / "characters_deleted"
    try:
        a = ch.create("연우", profile={"age": "24", "hair": "짧은 흑발"},
                      prompt_anchor="24-year-old Korean man, short black hair",
                      prompt_tags=["short black hair", " Grey  hoodie ", "grey hoodie"])
        eq(a["character_id"], "OC-001", "첫 인물의 번호가 OC-001 이 아니다")
        eq(a["prompt_tags"], ["short black hair", "Grey hoodie"], "같은 태그가 대소문자·공백만 다르게 두 번 들어갔다")
        b2 = ch.create("도윤")
        eq(b2["character_id"], "OC-002", "두 번째 인물이 번호를 이어받지 않는다")

        # 고칠 수 없는 칸은 거절한다 — id 가 바뀌면 그 인물을 가리키던 장면이 전부 미아가 된다
        try:
            ch.update("OC-001", {"character_id": "OC-099"})
            ok(False, "id 를 고쳐 주었다 — 장면이 가리키던 인물이 사라진다")
        except Exception as exc:
            ok("character_id" in str(exc), "무엇이 거절됐는지 말하지 않는다: %s" % str(exc)[:60])
        try:
            ch.update("OC-001", {"name": "   "})
            ok(False, "이름을 비워 주었다 — 매칭 화면에서 고를 수가 없다")
        except Exception as exc:
            ok("이름" in str(exc), "거절 사유가 이름이라고 말하지 않는다")

        # (1) 사진 — 그림만 받는다. 확장자가 아니라 머리 바이트로 본다.
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        r = ch.add_reference("OC-001", png, "정면")
        ok(r["file"].startswith("project/characters/refs/OC-001/"), "사진 경로가 인물 밑이 아니다")
        ok(r["file"].endswith(".png"), "머리 바이트로 확장자를 정하지 않았다: %s" % r["file"])
        eq(len(ch.get("OC-001")["reference_images"]), 1, "사진이 인물 기록에 남지 않았다")
        for bad, why in ((b"MZ\x90\x00" + b"0" * 64, "실행 파일"),
                         (b"<?php echo 1; ?>", "스크립트"),
                         (b"", "빈 파일")):
            try:
                ch.add_reference("OC-001", bad)
                ok(False, "%s 을 사진으로 받았다 — 이 폴더는 나중에 웹으로 나간다" % why)
            except Exception:
                pass
        eq(len(ch.get("OC-001")["reference_images"]), 1, "거절했는데 목록이 늘었다")
        try:
            ch.add_reference("OC-001", png * 200000)
            ok(False, "8MB 넘는 사진을 받았다")
        except Exception as exc:
            ok("큽니다" in str(exc) or "MB" in str(exc), "크기 거절이 이유를 말하지 않는다")

        # 사진 떼기 — 목록에 없는 경로는 거절한다(경로가 곧 삭제 대상이다)
        for evil in ("../../../tools/vn_core.py", "project/characters/refs/OC-002/x.png"):
            try:
                ch.remove_reference("OC-001", evil)
                ok(False, "목록에 없는 경로를 지웠다: %s" % evil)
            except Exception:
                pass
        ok((vc.ROOT / "tools" / "vn_core.py").is_file(), "저장소 파일이 지워졌다")
        # 경로를 실제 파일로 되짚는 자리 자체를 본다 — 웹이 이 함수로 사진을 돌려준다.
        for evil in ("../../../tools/vn_core.py", "..", "OC-002/../OC-001/x.png",
                     "C:/Windows/win.ini", "/etc/passwd"):
            got = ch.ref_path("OC-001", evil)
            ok(got is None or got.parent == (ch.REFS / "OC-001"),
               "사진 경로가 서랍 밖을 가리킨다: %s → %s" % (evil, got))
        rel = ch.get("OC-001")["reference_images"][0]
        out = ch.remove_reference("OC-001", rel)
        eq(out["file_gone"], True, "사진을 뗐는데 파일이 남아 있다")

        # (2) 매니페스트 투영 — 얹기만 한다
        before = json.loads(mf_keep.decode("utf-8"))
        had = [c.get("character_id") for c in before.get("characters", [])]
        # 결과로 본다("이번에 추가됐는가" 가 아니라). 샌드박스는 모든 테스트가 함께 쓰므로,
        # 앞선 웹 검사가 이미 같은 번호를 얹어 둔 상태일 수 있다 — 그건 고장이 아니다.
        ch.sync_manifest()
        now = [c.get("character_id") for c in vc.load_manifest().get("characters", [])]
        for cid in ("OC-001", "OC-002"):
            ok(cid in now, "서랍의 %s 가 매니페스트에 얹히지 않았다" % cid)
        for cid in had:
            ok(cid in now, "원래 있던 인물 %s 가 사라졌다 — 그 작품의 장면이 A2 FAIL 이 된다" % cid)
        stamp = mf_path.stat().st_mtime_ns
        eq(ch.sync_manifest()["added"], [], "바뀐 게 없는데 또 얹었다")
        eq(mf_path.stat().st_mtime_ns, stamp, "바뀐 게 없는데 매니페스트를 다시 썼다")
        ch.update("OC-001", {"prompt_anchor": "24-year-old Korean man, buzz cut"})
        eq(ch.sync_manifest()["updated"], ["OC-001"], "고친 인물이 매니페스트에 반영되지 않았다")
        got = [c for c in vc.load_manifest()["characters"] if c.get("character_id") == "OC-001"][0]
        ok("buzz cut" in got["prompt_anchor"], "매니페스트의 앵커가 옛 문장 그대로다")
        ok("source_chat" not in got and "notes" not in got,
           "서랍 전용 칸이 매니페스트로 새어 나갔다: %s" % sorted(got))

        # (3) 지우기 — 보관하고, 매니페스트에는 남기고, 번호는 다시 쓰지 않는다
        d = ch.delete("OC-002")
        ok((ch.ARCHIVE / d["archived_to"] / "OC-002.json").is_file(),
           "지운 인물이 보관되지 않았다 — 되돌릴 방법이 사라졌다")
        eq(len(ch.list_all()), 1, "서랍에서 내려가지 않았다")
        still = [c.get("character_id") for c in vc.load_manifest().get("characters", [])]
        ok("OC-002" in still,
           "매니페스트에서까지 뺐다 — 그 인물이 나오는 다른 작품의 장면이 A2 FAIL 이 된다")
        eq(ch.create("새 사람")["character_id"], "OC-003", "지운 번호를 다시 썼다")

        # 깨진 파일은 조용히 건너뛰지 않는다 — 사라진 줄 알고 같은 사람을 또 만든다
        (ch.DIR / "OC-777.json").write_text("{ 깨진", encoding="utf-8")
        broken = [c for c in ch.list_all() if c.get("character_id") == "OC-777"]
        eq(len(broken), 1, "깨진 인물 파일이 목록에서 조용히 사라졌다")
        ok(broken[0].get("broken"), "깨졌다고 표시하지 않는다")
        last = ch.sync_manifest()["added"]
        ok("OC-777" not in last, "깨진 파일을 매니페스트에 얹었다 — 읽지도 못한 인물이다")
        ok("OC-003" in last, "멀쩡한 새 인물이 얹히지 않았다: %s" % last)

        # 작품을 갈아 끼워도 서랍은 그대로다 — works 가 바꾸는 두 자리 밖에 있어야 한다
        wk = b.mod("works")
        for moved in (wk.SCENES, wk.IMAGES_RAW):
            ok(moved not in ch.DIR.parents and ch.DIR != moved,
               "서랍이 작품과 함께 갈리는 자리에 있다: %s" % ch.DIR)
        ok(ch.DIR.name not in [n for n, _ in wk._PAIRS], "서랍 폴더 이름이 작품 폴더와 겹친다")

        # 사진으로 얼굴을 잡을 수 있는가 — **서랍은 이 질문에 답하지 않는다.**
        # 엔진마다 다르고 모델 파일이 있어야 한다. 답이 두 곳에 있으면 갈라지고,
        # 그때 사람은 '사진을 쓴다' 는 화면을 보면서 얼굴이 흔들리는 그림을 받는다.
        ok(not hasattr(ch, "face_lock_state"),
           "서랍이 얼굴 고정 여부를 따로 답한다 — 엔진(image_gen.face_state)과 갈라진다")
    finally:
        ch.DIR, ch.REFS, ch.ARCHIVE = keep
        mf_path.write_bytes(mf_keep)


@test("unit", "U52 대화에 나온 장소는 그 장소로 — 목록에 없다고 첫 장소로 떨어지지 않는다")
def u52(b: Box):
    """실측: 비 오는 **서점** 이야기를 조립했더니 네 장면이 전부 '학교 앞 카페' 였다.
    이유는 인물 쪽과 똑같다 — 판정자 A2 가 장면의 location_id 는 매니페스트에 있어야
    한다고 요구하는데 그 파일은 고칠 수 없어서, 조립이 목록에 없는 장소를 만나면
    **무조건 첫 장소로 떨어뜨렸다.** 사람이 쓴 이야기와 나온 그림이 다르다.

    그래서 모델이 새 장소를 적어 주면 그것을 등록해서 쓴다. 등록은 한 곳
    (:func:`scene_ops.ensure_location`)에서만 하고, 같은 장소를 두 번 만들지 않는다 —
    안 그러면 한 작품에 '동네 서점' 이 네 개 생기고, 넷의 앵커가 조금씩 달라서 같은
    서점이 장면마다 다르게 그려진다.
    """
    vc = b.mod("vn_core")
    so = b.mod("scene_ops")
    vcm = b.mod("vn_compose")
    mf_path = vc.PROJECT / "manifest.json"
    mf_keep = mf_path.read_bytes()          # 샌드박스는 공용이다 — 원상 복구한다
    try:
        first = vc.load_manifest()["locations"][0]["location_id"]

        # 1) 새 장소를 등록한다
        lid = so.ensure_location("동네 서점", "a small neighborhood bookstore, warm wooden shelves")
        ok(lid and lid != first, "새 장소가 만들어지지 않았다: %r" % lid)
        got = [l for l in vc.load_manifest()["locations"] if l.get("location_id") == lid][0]
        ok("bookstore" in got["prompt_anchor"], "앵커가 저장되지 않았다")

        # 2) 같은 장소를 두 번 만들지 않는다(이름으로도, 앵커로도)
        eq(so.ensure_location("동네 서점", "a totally different anchor"), lid,
           "같은 이름의 장소를 또 만들었다 — 한 작품에 같은 서점이 둘이 된다")
        eq(so.ensure_location("딴 이름", "A SMALL neighborhood bookstore,  warm wooden shelves"),
           lid, "같은 앵커의 장소를 또 만들었다")
        n_before = len(vc.load_manifest()["locations"])

        # 3) 앵커가 없으면 거절한다 — 이름만 있는 장소는 그림에 아무것도 못 준다
        try:
            so.ensure_location("이름뿐인 곳", "   ")
            ok(False, "그림 문장 없는 장소를 등록했다")
        except Exception as exc:
            ok("anchor" in str(exc) or "그림 문장" in str(exc),
               "거절 사유를 말하지 않는다: %s" % str(exc)[:60])

        # 4) 조립 경로 — 목록에 없는 장소를 적은 원소가 **첫 장소로 떨어지지 않는다**
        item = {"order": 1, "purpose": "비 오는 저녁", "location_id": "LOC-999",
                "location_new": {"name": "비 오는 골목", "anchor": "a rainy narrow alley at night"},
                "dialogue": [], "image_prompt": "x"}
        loc_ids = {l.get("location_id") for l in vc.load_manifest()["locations"]}
        built = vcm.build_scene(item, 1, [], loc_ids,
                                vc.load_manifest()["locations"])
        made = built["location_id"]
        ok(made != first, "새 장소를 적었는데 첫 장소로 떨어졌다 — 서점 이야기가 카페에서 벌어진다")
        got = [l for l in vc.load_manifest()["locations"] if l.get("location_id") == made][0]
        ok("alley" in got["prompt_anchor"], "장면이 가리키는 장소의 앵커가 다르다")

        # 4-b) 모델이 **id 자리에 장소를 통째로** 적어도 받는다.
        #      실측: 저장이 "unhashable type: 'dict'" 로 터져서, 2분 40초를 들여 받은
        #      장면 네 개가 저장 직전에 통째로 막혔다. 여기는 자유 형식을 규약으로
        #      번역하는 자리다 — 모델의 형식 하나가 사람의 작업을 날리면 안 된다.
        item3 = {"order": 1, "purpose": "x", "dialogue": [],
                 "location_id": {"name": "비 오는 옥상", "anchor": "a rooftop in the rain at night"}}
        built3 = vcm.build_scene(item3, 1, [], loc_ids, vc.load_manifest()["locations"])
        got3 = [l for l in vc.load_manifest()["locations"]
                if l.get("location_id") == built3["location_id"]][0]
        ok("rooftop" in got3["prompt_anchor"],
           "id 자리에 적힌 장소를 못 읽었다: %s" % got3.get("prompt_anchor"))

        # 5) 새 장소를 **못 적었으면** 예전 그대로(첫 장소) — 장면 하나가 통째로 날아가지 않는다
        item2 = {"order": 1, "purpose": "x", "location_id": "LOC-999", "dialogue": []}
        eq(vcm.build_scene(item2, 1, [], loc_ids, vc.load_manifest()["locations"])["location_id"],
           first, "장소를 못 정했는데 빈 값이 됐다 — 검사기 A2 가 FAIL 이다")
        eq(len(vc.load_manifest()["locations"]), n_before + 2,
           "장소가 예상보다 늘었다 — 같은 곳이 여러 개 생기고 있다")
    finally:
        mf_path.write_bytes(mf_keep)


@test("unit", "U53 얼굴 고정(PhotoMaker) — 한 사람일 때만 켜지고, 특별한 낱말이 한 번 들어가고, 없으면 조용히 끄지 않는다")
def u53(b: Box):
    """사진으로 얼굴을 잡는 길은 ComfyUI 기본 노드로 이미 있다(PhotoMakerLoader ·
    PhotoMakerEncode). 커스텀 노드도 InsightFace 도 필요 없고 모델 파일 하나면 된다 —
    이 저장소가 '부속 설치를 늘리지 않는다' 는 규칙 아래 있으므로 그 차이가 결정적이다.

    세 가지가 조용히 틀리기 쉽다.

    (1) **낱말.** 프롬프트 안의 "photomaker" 한 개가 그 사람의 자리를 대신한다
        (comfy_extras/nodes_photomaker.py 의 special_token). 낱말이 없으면 노드는 자리를
        못 찾아 **실패한다**. 두 번 들어가도 자리가 흐트러진다. 정확히 한 번이어야 한다.

    (2) **인원수.** 임베딩은 하나다. 두 사람이 나오는 장면에 먹이면 두 얼굴이 섞인다 —
        아무것도 안 하는 편이 낫다.

    (3) **없을 때.** 모델이 없거나 업로드가 실패해도 그림은 구워야 한다. 얼굴이 안 잡힌
        그림이 아무 그림도 없는 것보다 낫다. 다만 **조용히** 넘어가면 안 된다 — 사람은
        사진을 등록해 뒀으니 당연히 얼굴이 잡혔다고 믿는다.
    """
    cf = b.mod("comfyui_client")
    wb = b.mod("webapp")
    # **webapp 이 보는 그 서랍**을 쓴다. Box.mod 는 모듈을 box_<이름> 으로 따로 적재하므로
    # b.mod("characters") 와 webapp 안의 characters 는 서로 **다른 객체**다 — 앞의 것을
    # 고치면 webapp 은 여전히 진짜 서랍을 본다(그래서 이 검사가 조용히 아무것도 안 봤다).
    ch = wb.characters

    # (1) 낱말 — 사람 낱말 뒤에 정확히 한 번
    got = cf.with_face_token("a 32-year-old Korean man with short black hair")
    eq(got.count(cf.PHOTOMAKER_TOKEN), 1, "특별한 낱말이 한 번이 아니다: %r" % got)
    ok(got.startswith("a 32-year-old Korean man " + cf.PHOTOMAKER_TOKEN),
       "낱말이 사람 낱말 뒤에 붙지 않았다: %r" % got)
    eq(cf.with_face_token(got), got, "이미 있는데 또 넣었다")
    ok(cf.PHOTOMAKER_TOKEN in cf.with_face_token("rainy alley at night"),
       "사람 낱말이 없으면 낱말을 아예 안 넣는다 — 그러면 노드가 실패한다")

    # 그래프 — 얼굴을 주면 긍정 쪽만 갈린다(부정 프롬프트는 그대로)
    s = cf.settings("x.safetensors")
    plan = cf.size_plan(768)
    g = cf.build_graph("a woman in a cafe", "lowres", ckpt="x.safetensors", seed=1, s=s, plan=plan,
                       face={"model": "photomaker-v1.bin", "image": "vn_faces/a.png"})
    eq(g["3"]["inputs"]["positive"], ["22", 0], "얼굴을 줬는데 긍정 조건이 안 갈렸다")
    eq(g["3"]["inputs"]["negative"], ["7", 0], "부정 프롬프트까지 갈렸다")
    eq(g["20"]["class_type"], "PhotoMakerLoader", "PhotoMaker 를 안 실었다")
    eq(g["21"]["inputs"]["image"], "vn_faces/a.png", "올린 사진 이름이 안 들어갔다")
    ok(cf.PHOTOMAKER_TOKEN in g["22"]["inputs"]["text"], "인코드 문구에 특별한 낱말이 없다")
    eq(g["22"]["inputs"]["clip"], g["6"]["inputs"]["clip"], "인코드가 다른 CLIP 을 쓴다")

    g2 = cf.build_graph("a woman in a cafe", "lowres", ckpt="x.safetensors", seed=1, s=s, plan=plan)
    eq(g2["3"]["inputs"]["positive"], ["6", 0], "얼굴을 안 줬는데 그래프가 달라졌다")
    ok("20" not in g2 and "22" not in g2, "얼굴을 안 줬는데 PhotoMaker 노드가 실렸다")
    # 반쪽 정보로는 켜지 않는다(모델만 / 사진만)
    for half in ({"model": "photomaker-v1.bin"}, {"image": "a.png"}, {}):
        gh = cf.build_graph("x", "y", ckpt="x", seed=1, s=s, plan=plan, face=half)
        eq(gh["3"]["inputs"]["positive"], ["6", 0], "반쪽 정보로 얼굴 고정을 켰다: %s" % half)

    # 콤보 모양 두 가지 — 이 서버 안에 둘이 같이 산다(실측)
    eq(cf._combo_options([["a.bin", "b.bin"], {"tooltip": "x"}]), ["a.bin", "b.bin"],
       "예전 스키마를 못 읽는다")
    eq(cf._combo_options(["COMBO", {"options": ["a.bin"]}]), ["a.bin"],
       "새 스키마를 못 읽는다 — 모델이 있는데 '없음' 으로 보인다")
    eq(cf._combo_options([]), [], "빈 입력에서 터진다")

    # (2) 인원수 — 서랍에 사진이 있는 인물 한 명일 때만
    keep = (ch.DIR, ch.REFS, ch.ARCHIVE)
    root = b.root / "facetest"
    ch.DIR, ch.REFS, ch.ARCHIVE = root / "c", root / "c" / "refs", root / "gone"
    try:
        one = ch.create("사진 있는 사람")
        two = ch.create("사진 없는 사람")
        ch.add_reference(one["character_id"], b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        cid = one["character_id"]
        picked = wb.scene_face_photo({"scene_id": "S1", "characters": [cid]})
        ok(picked.endswith(".png"),
           "사진이 있는 한 사람인데 얼굴 고정을 안 켰다: %r (서랍=%s, 사진=%s)"
           % (picked, ch.DIR, ch.get(cid).get("reference_images")))
        eq(wb.scene_face_photo({"scene_id": "S1", "characters": [cid, two["character_id"]]}), "",
           "두 사람인데 얼굴 고정을 켰다 — 두 얼굴이 섞인다")
        eq(wb.scene_face_photo({"scene_id": "S1", "characters": []}), "",
           "사람이 없는 장면에 얼굴 고정을 켰다")
        eq(wb.scene_face_photo({"scene_id": "S1", "characters": ["CHAR-001"]}), "",
           "서랍에 없는 인물에 얼굴 고정을 켰다")
        eq(wb.scene_face_photo({"scene_id": "S1", "characters": [two["character_id"]]}), "",
           "사진이 없는 인물에 얼굴 고정을 켰다")
        # 파일이 사라졌으면(사람이 디스크에서 지웠다) 목록에 남아 있어도 켜지 않는다
        gone = ch.get(cid)["reference_images"][0]
        ch.ref_path(cid, gone).unlink()
        eq(wb.scene_face_photo({"scene_id": "S1", "characters": [cid]}), "",
           "기록만 있고 파일이 없는 사진으로 얼굴 고정을 켰다")
    finally:
        ch.DIR, ch.REFS, ch.ARCHIVE = keep

    # 그림체가 멀면 얼굴이 흐려진다 — **그 순간에** 말한다.
    # 실측: 웹툰 체크포인트로 구웠더니 사진 속 남자가 다른 사람으로 나왔는데,
    # 얼굴 고정은 분명히 켜졌고 화면도 '켜짐' 이라고 적혀 있었다.
    eq(cf.face_style_warning("juggernautXL_ragnarok.safetensors"), "",
       "실사 체크포인트인데 경고를 낸다")
    for weak in ("waiIllustriousSDXL_v170.safetensors", "lustifyNSFWCheckpoint_zenithV9.safetensors", ""):
        w = cf.face_style_warning(weak)
        ok(w and "실사" in w,
           "그림체가 멀어 얼굴이 흐려지는데 아무 말도 안 한다: %r → %r" % (weak, w))

    # (3) 없을 때 — 조용히 넘어가지 않는다
    real = cf.photomaker_models
    try:
        cf.photomaker_models = lambda refresh=False: []
        st = cf.face_ready()
        eq(st["ok"], False, "모델이 없는데 된다고 한다")
        ok("photomaker" in st["note"].lower(), "무엇이 있어야 되는지 말하지 않는다: %r" % st["note"])
        cf.photomaker_models = lambda refresh=False: ["photomaker-v1.bin"]
        st = cf.face_ready()
        eq(st["ok"], True, "모델이 있는데 안 된다고 한다")
        ok("한 사람" in st["note"], "한 장면에 한 사람이라는 한계를 말하지 않는다")
    finally:
        cf.photomaker_models = real


@test("unit", "U54 비공개 폴더 — 저장소 밖만 받고, 설정이 깨지면 조용히 안으로 돌아가지 않는다")
def u54(b: Box):
    """사람이 "아무도 안 봤으면 좋겠다" 고 말한 파일이 있다 — 자기 얼굴 사진이다.
    이 저장소는 편집기의 작업 폴더이고, 거기서 도는 에이전트는 그 안을 읽는다.
    그러니 '안 읽겠다' 는 약속은 규칙일 뿐 구조가 아니다. 폴더를 밖으로 내면 구조가 된다.

    그래서 이 검사가 지키는 것은 둘이다.

    (1) **밖만 받는다.** 저장소 안을 가리키는 설정은 거절한다 — 받아 주면 사람은 밖에
        있다고 믿는데 실제로는 안에 쌓인다. 상대경로도 거절한다(어디를 기준으로 하는지에
        따라 저장소 안이 될 수 있다).

    (2) **깨지면 말한다.** 설정이 잘못됐을 때 조용히 예전 자리로 돌아가면, 사람은 사진이
        밖에 있다고 믿고 얼굴 사진을 더 올린다. 그 믿음이 틀렸다는 것은 나중에, 다른
        사람이 저장소를 열었을 때 드러난다.
    """
    vc = b.mod("vn_core")
    ch = b.mod("characters")
    keep_env = os.environ.get(vc.PRIVATE_ENV)
    keep = (ch.REFS, ch.PRIVATE_ERROR)

    def setenv(val):
        if val is None:
            os.environ.pop(vc.PRIVATE_ENV, None)
        else:
            os.environ[vc.PRIVATE_ENV] = val

    try:
        setenv(None)
        eq(vc.private_dir(), None, "설정이 없는데 비공개 폴더가 있다고 한다")
        eq(vc.private_or(vc.PROJECT / "x", "a", "b"), vc.PROJECT / "x",
           "설정이 없는데 예전 자리를 안 쓴다")

        # 저장소 안은 거절 — 여기가 이 기능의 전부다
        for inside in (str(vc.ROOT), str(vc.PROJECT / "secret"), str(vc.ROOT / "tools" / "x")):
            setenv(inside)
            e = raises(vc.private_dir)
            ok(e and ("저장소 밖" in str(e) or "저장소 안" in str(e)),
               "저장소 안을 받아들였다: %s → %r" % (inside, e))

        # 상대경로도 거절
        setenv("private_stuff")
        e = raises(vc.private_dir)
        ok(e and "절대경로" in str(e), "상대경로를 받아들였다: %r" % e)

        # 밖이면 받는다
        out = b.root.parent / "vn_private_test"
        setenv(str(out))
        eq(vc.private_dir(), out, "저장소 밖인데 거절했다")
        eq(vc.private_or(vc.PROJECT / "x", "characters", "refs"), out / "characters" / "refs",
           "비공개 폴더 아래 자리를 안 만든다")
        made = vc.private_dir(make=True)
        ok(made.is_dir(), "make=True 인데 폴더를 안 만들었다")
        made.rmdir()

        # (2) 설정이 깨졌으면 사진을 다루지 않는다
        ch.PRIVATE_ERROR = "시험용 오류"
        e = raises(lambda: ch.add_reference("OC-001", b"\x89PNG\r\n\x1a\n" + b"0" * 32))
        ok(e and "시험용 오류" in str(e),
           "설정이 깨졌는데 사진을 받았다 — 사람은 밖에 있다고 믿고 더 올린다: %r" % e)
        ch.PRIVATE_ERROR = ""

        # 화면에 보여 줄 답은 **문구가 아니라 경로**다("밖에 있습니다" 는 확인할 수 없다)
        home = ch.photo_home()
        ok(home.get("path"), "사진이 어디 사는지 경로를 주지 않는다")
        eq(home.get("env"), vc.PRIVATE_ENV, "어느 설정으로 바꾸는지 말하지 않는다")
    finally:
        setenv(keep_env)
        ch.REFS, ch.PRIVATE_ERROR = keep


@test("makefun", "M15 견적과 NSFW 안전장치 — 숫자는 받은 것만, 안전장치는 규칙이 아니라 구조로 켜 둔다")
def m15(b: Box):
    """둘 다 **명세를 읽고** 넣은 것이라 출처를 적어 둔다:
    노트북 보존본 `scratch/makefun_spec.json` — A2E Developer API v1.0.0(openapi 3.0.0),
    paths 206, 2026-08 수집본.

    **견적**(`POST /api/v1/generation/quote`) — 명세가 "작업을 만들지도, 공급자를 부르지도,
    크레딧을 차감하지도 않는다" 고 못박은 경로다. 그래서 굽기 전에 얼마인지 물어볼 수 있다.
    두 가지를 지킨다:
      * **보낼 바로 그 본문으로 묻는다.** 본문을 두 곳에서 따로 만들면 물어본 것과 보낸
        것이 달라지고 숫자는 조용히 틀린다.
      * **응답 필드에 이름을 붙이지 않는다.** 응답 스키마가 명세에 비어 있고(`{}`),
        명세가 직접 "문서화되지 않은 필드를 추론하지 말라" 고 적었다. 그래서 숫자를
        **필드명째** 돌려준다.

    **안전장치**(`force_generate`) — 명세 원문: *"Force generation even if NSFW content is
    detected. Defaults to **true for API users**, false for web users"*. 우리는 API 토큰
    사용자다. 값을 안 보내면 그쪽 안전장치가 꺼진 채로 도는데, 이 프로젝트는 input_images 로
    **실존 인물의 얼굴 사진**을 싣는다. 그래서 끄지 않는다고 명시해서 보낸다 —
    부르는 쪽마다 챙기는 규칙이 아니라 `_call` 이 채워 넣는 **구조**로 둔다.
    (이 저장소의 "ComfyUI 에 필터를 덧대지 말 것" 규칙과 충돌하지 않는다. 그건 내 기계의
     로컬 엔진 이야기고, 이건 남의 서버가 켜 둔 것을 내가 끄지 않는다는 이야기다.)
    """
    mk = b.mod("makefun_client")

    # --- 안전장치: 다섯 경로에만, 그리고 사람이 적어 둔 값은 건드리지 않는다
    eq(mk.with_safety("/api/v1/userText2Image/start", {"prompt": "x"}), {"prompt": "x"},
       "안전장치 파라미터가 없는 경로에 값을 끼워 넣었다 — 400 을 부른다")
    for path in mk.NSFW_FORCE_PATHS:
        got = mk.with_safety(path, {"prompt": "x"})
        eq(got.get("force_generate"), False,
           "%s 로 나가면서 안전장치를 끌지 말라고 말하지 않았다 — 기본이 '끔' 인 경로다" % path)
    eq(mk.with_safety("/api/v1/userFlux2/start", {"force_generate": True})["force_generate"], True,
       "사람이 일부러 적어 둔 값을 덮었다 — 몇 번을 적어도 안 바뀌는 칸이 된다")
    ok(len(mk.NSFW_FORCE_PATHS) >= 5, "안전장치 경로 목록이 줄었다: %s" % (mk.NSFW_FORCE_PATHS,))

    # 구조인지 확인한다 — 부르는 쪽이 아무것도 안 해도 _call 이 채워야 한다
    seen = {}
    with mf_stub(mk, lambda m, p_, body: seen.update({"path": p_, "body": body}) or {"data": []}):
        try:
            mk._call("POST", "/api/v1/userFlux2/start", {"prompt": "x"}, quiet=True)
        except Exception:
            pass
    eq((seen.get("body") or {}).get("force_generate"), False,
       "_call 을 그냥 불렀는데 안전장치 표시가 안 붙었다 — 규칙이지 구조가 아니다")

    # --- 견적: 기본은 꺼져 있다(바깥 서버를 두드리는 일이다)
    eq(mk.quote_enabled(), False, "견적이 기본으로 켜져 있다 — 이 저장소의 MakeFun 규칙은 '모의만' 이다")

    # 보낼 본문 그대로 묻는가
    asked = {}

    def api(method, path, body):
        asked[path] = body
        if path == mk.P_QUOTE:
            return {"data": {"credits": 6, "detail": {"perImage": 3},
                             "generationRequestValidated": False}}
        return {"data": [{"_id": "task_x"}]}

    with mf_stub(mk, api):
        q = mk.quote_text2image("고백하는 장면", n=2, name="SCENE-001")
        sent = mk.t2i_body("고백하는 장면", n=2, name="SCENE-001")
    body = asked.get(mk.P_QUOTE) or {}
    eq(body.get("endpoint"), mk.P_T2I_START, "견적에 어느 경로를 물었는지 안 실었다")
    eq(body.get("requestBody"), sent,
       "견적에 보낸 본문이 실제로 보낼 본문과 다르다 — 그러면 숫자가 조용히 틀린다")
    eq(dict(q["numbers"]), {"credits": 6, "detail.perImage": 3},
       "견적 숫자를 필드명째 꺼내지 못했다: %s" % (q["numbers"],))
    eq(q["validated"], False,
       "명세가 이름을 확정해 준 유일한 필드(generationRequestValidated)를 안 올린다")

    # "POST /api/v1/..." 도 받는다(명세: leading POST 는 선택)
    with mf_stub(mk, api):
        mk.quote("POST /api/v1/userText2Image/start", {"prompt": "x"})
    eq((asked.get(mk.P_QUOTE) or {}).get("endpoint"), mk.P_T2I_START,
       "'POST ' 가 붙은 경로를 그대로 보냈다")
    for bad in ("", "userText2Image/start", None):
        raises(lambda bad=bad: mk.quote(bad, {"x": 1}), label="이상한 경로 %r" % bad)
    raises(lambda: mk.quote(mk.P_T2I_START, "본문아님"), label="본문이 dict 가 아닌 경우")


@test("makefun", "M16 영상 — 요청은 명세대로, 응답은 모르는 채로 안전하게, 실패해도 작업 id 는 남는다")
def m16(b: Box):
    """출처: 노트북 보존본 `scratch/makefun_spec.json` — A2E Developer API v1.0.0, 2026-08.

    이 경로는 이 저장소에서 처음으로 **요청은 확정이고 응답은 미확정**인 기능이다.
    `/api/v1/userImage2Video/start` 와 `GET /{_id}` 의 200 스키마가 둘 다 `{"type":"object"}`
    에 example `{}` 다 — 작업 id 도 mp4 URL 도 어느 필드인지 명세가 말해 주지 않는다.
    그래서 지키는 것이 셋이다.

    (1) **요청은 명세대로.** 특히 `model_version` 을 반드시 싣는다. 원문: *"Ultra users
        default to a2e-v2 … a2e-v2 costs more per second"* — 값을 비우면 계정 등급에 따라
        단가가 달라진다. 같은 버튼이 사람마다 다른 돈을 쓰면 화면은 아무것도 약속할 수 없다.

    (2) **모르는 응답에 이름을 붙이지 않는다.** 관용 파서로 찾고, 못 찾으면 **응답을 담아
        던진다.** 조용히 빈손으로 돌아가면 이미 과금된 작업을 영영 못 찾는다.

    (3) **실패해도 대장에 남는다.** 유료 경로에서 조용한 실패는 곧 잃어버린 돈이다 —
        작업 id 하나가 재과금 없이 결과를 되찾는 유일한 단서다.
    """
    mk = b.mod("makefun_client")

    # (1) 요청 본문 — 길이는 허용값으로 내리고(올리면 돈이 더 든다), 모델은 반드시 실린다
    body = mk.video_body("https://cdn.example/a.png", "달빛", seconds=7)
    eq(body["video_time"], 5, "7초를 그대로 보냈다 — 서버 처리가 미정의인 값이다")
    eq(mk.video_body("https://x/a.png", seconds=25)["video_time"], 20, "상한을 넘겨 보냈다")
    eq(mk.video_body("https://x/a.png", seconds=15)["video_time"], 15, "허용값을 바꿔 버렸다")
    ok(body.get("model_version") in mk.VIDEO_MODELS,
       "model_version 을 안 싣는다 — 계정 등급에 따라 단가가 달라진다")
    eq(mk.video_body("https://x/a.png", end_image_url="https://x/b.png")["model_type"], "FLF2V",
       "끝 컷을 줬는데 보간 모드로 안 간다")
    raises(lambda: mk.video_body("http://x/a.png"), label="평문 http 원본")
    raises(lambda: mk.video_body("https://x/a.png", model_version="gpt-5"), label="모르는 모델")

    # (2) 응답을 모를 때 — 조용히 넘어가지 않는다
    with mf_stub(mk, lambda m, p_, bd: {"data": {"nothing": 1}}):
        e = raises(lambda: mk.video_start("https://x/a.png"), label="id 없는 응답")
        ok("응답" in str(e), "id 를 못 찾았는데 응답을 안 보여 준다: %s" % str(e)[:80])

    def api_done_without_url(m, p_, bd):
        if p_.endswith("/start"):
            return {"data": {"_id": "vid_abc123"}}
        return {"data": {"_id": "vid_abc123", "current_status": "completed"}}

    with mf_stub(mk, api_done_without_url):
        e = raises(lambda: mk.video_result("vid_abc123", max_sec=30), label="주소 없는 완료")
        ok("주소" in str(e), "끝났다는데 결과가 없을 때 조용하다: %s" % str(e)[:80])

    # 정상 흐름 — URL 은 '찾아서' 쓴다(필드 이름을 코드가 단정하지 않는다)
    def api_ok(m, p_, bd):
        if "presigned" in p_:      # 컷을 올려야 주소가 생긴다(공급자는 URL 만 받는다)
            return {"data": {"uploadUrl": "https://up.example/put",
                             "cdnUrl": "https://cdn.example/in.png"}}
        if p_.endswith("/start"):
            return {"data": {"_id": "vid_abc123"}}
        # 보낸 그림이 그대로 돌아온다 — 결과로 착각하면 돈 내고 원본을 돌려받는다
        return {"data": {"_id": "vid_abc123", "current_status": "completed",
                         "source": "https://cdn.example/in.png",
                         "이상한이름": "https://cdn.example/out.mp4"}}

    with mf_stub(mk, api_ok):
        got = mk.video_result("vid_abc123", max_sec=30)
    eq(got["urls"][0], "https://cdn.example/out.mp4",
       "필드 이름이 낯설다고 결과를 못 찾는다(명세에 이름이 없다) — 또는 영상이 첫째가 아니다")
    with mf_stub(mk, api_ok):
        only = mk.video_result("vid_abc123", max_sec=30, source_url="https://cdn.example/in.png")
    ok("https://cdn.example/in.png" not in only["urls"],
       "보낸 그림이 결과 목록에 남아 있다 — 돈 내고 원본을 돌려받을 수 있다")

    # (3) 장면 경로 — 저장 + 대장, 그리고 실패해도 작업 id 가 남는다
    mp4 = b"\\x00\\x00\\x00\\x18ftypmp42" + b"0" * 64
    with fresh_scene(b) as sid:
        raw = b.root / "images" / "raw" / sid
        raw.mkdir(parents=True, exist_ok=True)
        cut = raw / "mf_pick_1.png"
        cut.write_bytes(_png_bytes())
        sc_path = b.root / "project" / "scenes" / (sid + ".json")
        sc = read_json(sc_path)
        sc.setdefault("assets", {})["raw_images"] = ["images/raw/%s/%s" % (sid, cut.name)]
        sc["assets"]["selected_image"] = "images/raw/%s/%s" % (sid, cut.name)
        sc_path.write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")

        n0 = _usage_len(b)
        with mf_stub(mk, api_ok, fetch=lambda url: mp4, put=lambda req: None):
            res = mk.video_for_scene(sid, seconds=10, quiet=True)
        ok(res["file"].endswith(".mp4"), "mp4 를 저장하지 않았다: %s" % res["file"])
        ok((b.root / res["file"]).is_file(), "저장했다는 파일이 없다")
        # 업로드(R2)도 대장에 남으므로 **영상 줄을 골라서** 본다
        rows = [r for r in _usage_tail(b, n0) if r.get("kind") == "image2video"]
        eq(len(rows), 1, "영상 한 줄이 대장에 남지 않았다: %s"
                         % [r.get("kind") for r in _usage_tail(b, n0)])
        eq(rows[0]["billable"], True, "유료인데 대장이 무료라고 한다")
        eq(rows[0]["task_id"], "vid_abc123", "대장에 작업 id 가 없다 — 되찾을 단서가 사라진다")

        # 고른 컷이 없으면 아예 시작하지 않는다(돈이 나가기 전에 멈춘다)
        sc["assets"]["selected_image"] = ""
        sc_path.write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
        e = raises(lambda: mk.video_for_scene(sid, quiet=True), label="고른 컷 없음")
        ok("고른" in str(e), "왜 못 만드는지 말하지 않는다: %s" % str(e)[:60])


@test("makefun", "M17 실측 단가 — 공급자가 안 알려 주면 재서 안다(음수만 소비 · 못 쟀으면 안 적는다)")
def m17(b: Box):
    """공급자는 장당 몇 크레딧인지 공개하지 않는다. 그래서 묻는 대신 **잰다**:
    굽기 직전 시각을 적어 두고, 구운 뒤 그 시각 이후의 소비만 조회해 대장에 남긴다.
    두세 번 쌓이면 "이 크기·이 모델이면 얼마" 가 나오고, 그때부터 화면이 **실측한** 숫자를
    보여 줄 수 있다. 추측한 숫자와 잰 숫자는 다른 물건이다.

    명세(A2E Developer API v1.0.0, 2026-08 보존본)가 확정해 준 것 둘만 믿는다:
      * 쿼리 파라미터 `is_consumption` · `startDate`(**포함 경계**) · `pageNum`/`pageSize`
      * 부호 규약 — *"Positive amounts are credit grants or purchases; negative amounts are
        credit consumption."*
    응답 스키마 자체는 여전히 비어 있어 **필드 이름은 모른다.** 그래서 이름을 해석하지 않고
    숫자만 보고, 음수만 소비로 센다.

    **못 쟀으면 대장에 남기지 않는다.** 빈 줄은 나중에 읽는 사람에게 '0 크레딧이 나갔다' 로
    보이는데, 그건 잰 것이 아니라 못 잰 것이다. 그 둘을 같은 모양으로 적으면 실측이 오염된다.
    """
    mk = b.mod("makefun_client")
    asked = {}

    def api(m, p_, bd):
        if "creditsHistory" in p_:
            asked["path"] = p_
            return {"data": [
                {"_id": "r1", "amount": -12, "createdAt": "2026-09-16T13:00:00Z"},
                {"_id": "r2", "amount": -3.5, "createdAt": "2026-09-16T13:00:05Z"},
                {"_id": "r3", "amount": 500, "createdAt": "2026-09-16T12:00:00Z"},   # 충전
            ]}
        return {"data": []}

    with mf_stub(mk, api):
        rows = mk.consumption_since("2026-09-16T12:59:00Z", limit=5)
    q = asked.get("path", "")
    ok("is_consumption=true" in q, "소비만 달라고 하지 않았다: %s" % q)
    ok("startDate=" in q, "시작 경계를 안 보냈다 — 계정 전체 이력을 끌어온다: %s" % q)
    ok("pageSize=5" in q, "가져올 개수를 안 줄였다 — 기록이 쌓이면 무거워진다: %s" % q)
    eq([r["amount"] for r in rows], [-12, -3.5],
       "충전(양수)까지 소비로 셌다 — 명세의 부호 규약과 반대다")

    # 대장 — 잰 것이 있을 때만 남기고, 합계는 절댓값이다
    n0 = _usage_len(b)
    with mf_stub(mk, api):
        rec = mk.record_spend("text2image", "SCENE-001", "2026-09-16T12:59:00Z", {"requested": 2})
    eq(rec["spent"], 15.5, "쓴 크레딧 합계가 틀리다")
    rows2 = [r for r in _usage_tail(b, n0) if r.get("kind") == "spend"]
    eq(len(rows2), 1, "실측이 대장에 남지 않았다")
    eq(rows2[0]["of"], "text2image", "무엇의 실측인지 안 적었다")
    eq(rows2[0]["billable"], False, "재는 일 자체가 과금이라고 적었다")

    n1 = _usage_len(b)
    with patched(mk, "SPEND_RETRY_SEC", 0):          # 재시도 대기는 여기서 볼 것이 아니다
        with mf_stub(mk, lambda m, p_, bd: {"data": []}):
            empty = mk.record_spend("text2image", "SCENE-001", "2026-09-16T12:59:00Z")
    eq(empty["spent"], None, "못 쟀는데 0 이라고 한다")
    eq([r for r in _usage_tail(b, n1) if r.get("kind") == "spend"], [],
       "못 쟀는데 대장에 남겼다 — 나중에 '0 크레딧' 으로 읽힌다")

    # 조회가 통째로 실패해도 생성은 안 뒤집힌다(덤으로 재는 일이다)
    def boom(m, p_, bd):
        raise RuntimeError("크레딧 서버 장애")

    with mf_stub(mk, boom):
        eq(mk.consumption_since("2026-09-16T12:59:00Z"), [],
           "조회가 실패했는데 예외가 위로 올라간다 — 이미 성공한 생성이 실패로 뒤집힌다")

    # 요약 — 화면이 숫자를 보여도 되는 유일한 근거
    got = mk.measured_spend("text2image")
    ok(got["n"] >= 1, "쌓인 실측을 못 읽는다: %s" % got)
    ok(got["avg"] is not None and got["avg"] > 0, "평균이 없다: %s" % got)
    eq(mk.measured_spend("없는종류")["n"], 0, "다른 종류의 실측까지 섞어 센다")

    # ---- 페이지가 꽉 차면 다음 장을 읽는다 --------------------------------
    # 한 번의 생성이 여러 줄을 만든다(장수 최대 8 · 업스케일이 같은 창에 끼기도 한다).
    # 한 장만 읽고 끝내면 기록이 6줄인데 5줄만 세고, 평균 단가가 **실제보다 싸게** 나온다.
    # 화면이 사람에게 '덜 든다' 고 말하는 쪽의 오류라 더 나쁘다.
    pages = {"seen": []}

    def paged(m, p_, bd):
        if "creditsHistory" not in p_:
            return {"data": []}
        num = int(re.search(r"pageNum=(\d+)", p_).group(1))
        size = int(re.search(r"pageSize=(\d+)", p_).group(1))
        pages["seen"].append(num)
        all_rows = [{"amount": -2, "createdAt": "2026-09-16T13:00:0%d" % i} for i in range(6)]
        chunk = all_rows[(num - 1) * size: num * size]
        return {"data": chunk}

    with mf_stub(mk, paged):
        many = mk.consumption_since("2026-09-16T12:59:00Z", limit=5)
    eq(len(many), 6, "꽉 찬 페이지를 보고 다음 장을 안 읽었다 — 단가가 실제보다 싸게 나온다")
    ok(len(pages["seen"]) >= 2, "페이지를 한 장만 읽었다: %s" % pages["seen"])
    eq(mk.SPEND_PAGE >= 50, True, "기본 페이지 크기가 너무 작다: %d" % mk.SPEND_PAGE)

    # 끝없이 읽지는 않는다(응답이 늘 꽉 차 있어도 멈춘다)
    with mf_stub(mk, lambda m, p_, bd: {"data": [{"amount": -1}] * 50}
                 if "creditsHistory" in p_ else {"data": []}):
        forever = mk.consumption_since("2026-09-16T12:59:00Z")
    eq(len(forever), 50 * mk.SPEND_MAX_PAGES, "페이지 상한이 안 걸린다 — 끝없이 읽는다")
    # 상한 자체도 못 박는다. 위 줄은 상수로 기대값을 계산하므로 상수가 커지면 같이 커진다
    # — 그러면 '상한이 있다' 만 보고 '상한이 쓸모 있다' 는 못 본다(돌연변이로 확인).
    ok(mk.SPEND_MAX_PAGES <= 10,
       "페이지 상한이 너무 큽니다(%d) — 계정 이력이 많으면 생성마다 수십 번 조회한다"
       % mk.SPEND_MAX_PAGES)

    # ---- 과금은 완료 뒤에 확정된다 — 한 번은 더 기다려 본다 ----------------
    tries = {"n": 0}

    def late(m, p_, bd):
        if "creditsHistory" not in p_:
            return {"data": []}
        tries["n"] += 1
        return {"data": [] if tries["n"] == 1 else [{"amount": -9}]}

    n2 = _usage_len(b)
    with patched(mk, "SPEND_RETRY_SEC", 0):
        with mf_stub(mk, late):
            late_rec = mk.record_spend("text2video", "SCENE-002", "2026-09-16T12:59:00Z")
    eq(late_rec["spent"], 9,
       "기록이 늦게 올라오는 경우를 못 잡는다 — 끝나자마자 재면 아직 0줄일 수 있다")
    eq(tries["n"], 2, "빈손이었는데 한 번 더 확인하지 않았다")

    # ---- 충분히 쌓이면 그만 잰다(이 조회도 실호출이다) --------------------
    calls = {"n": 0}

    def counting(m, p_, bd):
        if "creditsHistory" in p_:
            calls["n"] += 1
        return {"data": [{"amount": -1}] if "creditsHistory" in p_ else []}

    for _ in range(mk.SPEND_SAMPLE_CAP + 2):
        with patched(mk, "SPEND_RETRY_SEC", 0):
            with mf_stub(mk, counting):
                mk.record_spend("포화시험", "SCENE-003", "2026-09-16T12:59:00Z")
    got_n = mk.measured_spend("포화시험")["n"]
    eq(got_n, mk.SPEND_SAMPLE_CAP,
       "충분히 쟀는데 계속 잰다 — 덤이 세금이 된다(쌓인 수: %s)" % got_n)

    # UTC 로 보낸다 — 로컬 시각이면 시차만큼 남의 기록이 섞이거나 내 기록이 빠진다
    ok(mk.now_iso().endswith("Z"), "시작 경계를 UTC 로 안 보낸다: %s" % mk.now_iso())


@test("makefun", "M18 한 번의 조사 — 기본은 꺼져 있고, 켜면 시각과 응답 전문을 남긴다(돈은 더 안 쓴다)")
def m18(b: Box):
    """이 공급자는 응답 스키마를 공개하지 않아서, **실호출 한 번을 봐야만** 알 수 있는
    것이 남는다: 크레딧이 어느 필드에 오는가, 소비 기록이 완료 뒤 몇 초에 올라오는가.

    그 한 번을 위해 **돈을 따로 쓰지 않는다.** 사람이 어차피 구울 때 그 호출이 조사도
    겸한다(VN_MF_PROBE=1). 조회 자체는 무과금이라 30번을 훑어도 크레딧이 들지 않는다.

    남기는 것이 중요하다 — 응답만 남기면 나중에 그 숫자가 **무엇에 대한 견적이었는지**
    아무도 되짚지 못한다. 그래서 보낸 본문과 시각을 함께 적는다.
    """
    mk = b.mod("makefun_client")
    keep = os.environ.get(mk.PROBE_ENV)
    try:
        os.environ.pop(mk.PROBE_ENV, None)
        eq(mk.probe_on(), False, "조사가 기본으로 켜져 있다 — 생성마다 30초씩 훑는다")
        for on in ("1", "true", "ON"):
            os.environ[mk.PROBE_ENV] = on
            eq(mk.probe_on(), True, "%r 로 못 켠다" % on)
        os.environ[mk.PROBE_ENV] = "0"
        eq(mk.probe_on(), False, "0 으로 안 꺼진다")

        # 시각 조사 — 기록이 늦게 올라오는 상황을 만들어 둔다
        tries = {"n": 0}

        def late(m, p_, bd):
            if "creditsHistory" not in p_:
                return {"data": []}
            tries["n"] += 1
            return {"data": [] if tries["n"] < 3 else [{"amount": -4, "createdAt": "x"}]}

        n0 = _usage_len(b)
        with patched(mk, "PROBE_STEP_SEC", 0):
            with mf_stub(mk, late):
                rep = mk.probe_spend_timing("2026-09-16T12:59:00Z", "text2image", "SCENE-001")
        eq(rep["ok"], True, "늦게 올라온 기록을 못 봤다")
        ok(rep["seconds_to_first_record"] is not None, "몇 초 만에 보였는지 안 적었다")
        ok(rep["t0_before_generate"] and rep["t1_after_complete"],
           "두 시각(굽기 전·완료 후)을 안 적었다 — 나중에 되짚을 수 없다")
        ok(rep["raw"], "응답 전문을 안 남겼다 — 필드 이름을 확정하려고 하는 조사다")
        rows = [r for r in _usage_tail(b, n0) if r.get("kind") == "spend_probe"]
        eq(len(rows), 1, "조사 결과가 대장에 안 남았다")
        eq(rows[0]["billable"], False, "조회가 과금이라고 적었다")

        # 끝내 안 보이면 — **과금이 없었다는 뜻일 수도 있다.** 그것도 결과다
        with patched(mk, "PROBE_STEP_SEC", 0), patched(mk, "PROBE_MAX_SEC", 0.2):
            with mf_stub(mk, lambda m, p_, bd: {"data": []}):
                none = mk.probe_spend_timing("2026-09-16T12:59:00Z", "text2image")
        eq(none["ok"], False, "아무것도 못 봤는데 봤다고 한다")
        ok("과금되지 않았" in none["note"] or "늦거나" in none["note"],
           "못 본 것이 무슨 뜻일 수 있는지 말하지 않는다: %r" % none["note"])

        # 견적 조사 — 보낸 본문까지 남기고, 무과금인지 **재서** 말한다
        def api(m, p_, bd):
            if p_ == mk.P_QUOTE:
                return {"data": {"credits": 5, "generationRequestValidated": False}}
            if "creditsHistory" in p_:
                return {"data": []}
            return {"data": []}

        n1 = _usage_len(b)
        with patched(mk, "PROBE_STEP_SEC", 0):
            with mf_stub(mk, api):
                q = mk.probe_quote("시험 장면")
        ok(q["sent"], "보낸 본문을 안 남겼다 — 무엇에 대한 견적인지 되짚을 수 없다")
        ok("credits=5" in q["numbers"], "견적 숫자를 안 남겼다: %s" % q["numbers"])
        ok("무과금" in q["note"], "무과금이었는지 말하지 않는다: %r" % q["note"])
        eq(len([r for r in _usage_tail(b, n1) if r.get("kind") == "quote_probe"]), 1,
           "견적 조사가 대장에 안 남았다")

        # 견적인데 소비가 생겼다면 — **명세와 다르다.** 그 사실을 그대로 말해야 한다
        def api_charged(m, p_, bd):
            if p_ == mk.P_QUOTE:
                return {"data": {"credits": 5}}
            if "creditsHistory" in p_:
                return {"data": [{"amount": -5}]}
            return {"data": []}

        with patched(mk, "PROBE_STEP_SEC", 0):
            with mf_stub(mk, api_charged):
                bad = mk.probe_quote("시험 장면")
        ok("무과금이 아닙니다" in bad["note"],
           "견적에 돈이 나갔는데 명세대로라고 말한다: %r" % bad["note"])
    finally:
        if keep is None:
            os.environ.pop(mk.PROBE_ENV, None)
        else:
            os.environ[mk.PROBE_ENV] = keep


@test("unit", "U55 [처음부터]는 보관한 뒤에만 비우고, 모델에 넘기는 창도 서버 기록을 본다")
def u55(b: Box):
    """이 저장소의 하드 룰은 하나다: **대화 로그는 어떤 경로로도 조용히 짧아지지 않는다.**
    save_log 도, truncate_log 도, 대화 삭제도 전부 아카이브로 옮긴 **뒤에만** 자른다.
    그런데 두 곳이 그 규칙 밖에 있었다.

    (1) 인물 대화의 [처음부터]. 누른 뒤 아무 말이나 한 마디 보내면 그때까지의 대화
        전부(사진 메타까지)가 디스크에서 사라졌고, 보관본이 없어 내보내기로도 복구할 수
        없었다. 보관에 실패하면 **비우지 않는다** — 실패는 아무것도 잃지 않는 쪽으로
        넘어져야 한다.

    (2) 스토리 챗이 모델에 넘기는 창. 저장은 서버 기록과 병합해서 하는데 **전송만**
        클라이언트가 보낸 목록에서 잘랐다. 이력 로드가 한 번 실패해 화면이 빈 목록이
        되면, 그 뒤 한 마디에 모델은 진행 중이던 소설을 전혀 모르는 채 답한다.
        그 답은 병합 덕에 로그에는 제대로 붙으므로, 남는 것은 "모델이 갑자기 이야기를
        잊은" 한 턴이다 — 사람은 왜 그랬는지 알 방법이 없다.
    """
    ts = b.mod("talk_store")
    wb = b.mod("webapp")

    # (1) [처음부터] — 보관한 뒤에만 비운다
    cid = "U55인물"
    ts.save_messages(cid, [{"role": "user", "content": "지난 이야기 첫 줄"},
                           {"role": "assistant", "content": "지난 이야기 답"}])
    path = ts.talk_path(cid)
    eq(len(ts.load_messages(cid)), 2, "준비한 대화가 저장되지 않았다")
    res = ts.reset_messages(cid)
    eq(res["archived"], 2, "보관한 수가 다르다")
    eq(ts.load_messages(cid), [], "비우지 않았다")
    arch = ts.archive_path(path)
    ok(arch.is_file(), "보관 파일이 없다 — 지운 대화를 되찾을 방법이 사라졌다")
    body = arch.read_text(encoding="utf-8")
    ok("지난 이야기 첫 줄" in body and "지난 이야기 답" in body,
       "보관본에 내용이 없다: %r" % body[:120])
    eq(ts.reset_messages(cid), {"cleared": 0, "archived": 0}, "빈 대화를 또 보관한다")

    # 보관에 실패하면 비우지 않는다
    ts.save_messages(cid, [{"role": "user", "content": "두 번째 이야기"}])
    real = ts._append_archive
    try:
        def boom(*a, **k):
            raise OSError("디스크 가득")
        ts._append_archive = boom
        e = raises(lambda: ts.reset_messages(cid), label="보관 실패")
        ok("보관하지 못" in str(e), "왜 안 비웠는지 말하지 않는다: %s" % str(e)[:60])
    finally:
        ts._append_archive = real
    eq(len(ts.load_messages(cid)), 1,
       "보관에 실패했는데 비웠다 — 실패가 잃는 쪽으로 넘어졌다")

    # (2) 모델에 넘기는 창 — 화면이 빈 목록이어도 서버 기록을 본다
    chat_id = "u55chat"
    p2 = ts.story_chat_path_for(chat_id)
    ts.save_log(p2, [{"role": "user", "content": "소설 첫 문단"},
                     {"role": "assistant", "content": "이어지는 문단"}])
    seen = {}
    real_chat = wb.vn_compose.orch_chat
    try:
        def fake(msgs, **kw):
            seen["msgs"] = list(msgs)
            return "답"
        wb.vn_compose.orch_chat = fake
        # 화면이 이력을 못 받아 **빈 목록**으로 한 마디만 보내는 상황
        wb.do_chat([{"role": "user", "content": "그래서 어떻게 됐지?"}], chat_id)
    finally:
        wb.vn_compose.orch_chat = real_chat
    sent = " ".join(str(m.get("content", "")) for m in seen.get("msgs", []))
    ok("소설 첫 문단" in sent,
       "모델이 서버에 있는 지난 이야기를 못 받았다 — 그 턴만 기억을 잃는다")
    ok("그래서 어떻게 됐지?" in sent, "방금 한 말이 안 갔다")
    kept = ts.load_log(p2)
    eq(len(kept), 4, "저장본이 병합되지 않았다: %d" % len(kept))


@test("unit", "U56 장면 경계는 모델이 고른 모양과 무관하다 — 포장돼 와도 도착하는 대로 보인다")
def u56(b: Box):
    """같은 지시문에 모델이 세 가지 모양으로 답한다(실측 7회: 배열 3 · 포장 2 · 객체만 2).

        [{"order":1,…}, …]              맨 바깥이 배열
        {"scenes":[{"order":1,…}, …]}   한 겹 포장
        {"order":1,…},{"order":2,…}     배열 없이 객체만

    예전에는 **최상위 객체가 닫히는 순간**만 경계로 봤다. 포장된 모양에서는 최상위 객체가
    응답 전체 하나라서 배치가 다 올 때까지 경계가 한 번도 안 잡혔다 — 그 회차는 2분 가까이
    화면이 조용했고 [현상 멈추기]도 안 먹었다(멈춤은 장면 도착 시점에만 일어난다).
    사람은 죽은 줄 알고 새로고침하거나 다시 시작했고, 그 30~100초는 GPU 시간 그대로다.

    **같은 작업인데 그날 모델이 고른 모양에 따라 화면이 달랐다** — 그게 고쳐야 할 이유다.

    가르는 일은 한 곳에서만 한다(:func:`_looks_like_scene`). 구조만으로는 포장 안의 장면과
    장면 안의 대사 원소를 구별할 수 없어서(둘 다 '객체 하나 안의 배열 원소' 다), 판정을
    두 곳에 두면 반드시 갈라지고 그때 **대사 한 줄이 장면 한 컷으로** 집계된다.
    """
    vc = b.mod("vn_compose")
    one = ('{"order":%d,"purpose":"목적","emotion":"기쁨",'
           '"dialogue":[{"speaker_id":"CHAR-001","text":"안녕"},'
           '{"speaker_id":"CHAR-002","text":"어"}],"image_prompt":"x"}')

    def stream(text):
        got = []
        st = vc._SceneStream(lambda o: got.append(o))
        for ch in text:            # 한 글자씩 — 진짜 스트리밍과 같은 조건
            st.feed(ch)
        return [o.get("order") for o in got]

    eq(stream("[" + ",".join(one % i for i in (1, 2)) + "]"), [1, 2], "맨 바깥 배열")
    eq(stream('{"scenes":[' + ",".join(one % i for i in (1, 2, 3)) + "]}"), [1, 2, 3],
       "포장된 모양에서 장면이 도착하는 대로 안 보인다 — 배치가 다 올 때까지 화면이 조용하다")
    eq(stream(",".join(one % i for i in (1, 2))), [1, 2], "배열 없이 객체만 오는 모양")
    eq(stream("```json\n[" + (one % 9) + "]\n```"), [9], "코드펜스로 감싼 모양")
    eq(stream("생각 중… </think>" + '{"scenes":[' + (one % 4) + "]}"), [4],
       "혼잣말 뒤에 포장된 모양이 오면 못 본다")

    # **대사 원소를 장면으로 세지 않는다.** 이걸 놓치면 장면 하나가 대사 수만큼
    # 부풀고, 이어받기 번호(start = len(items)+1)가 통째로 어긋난다.
    eq(len(stream('{"scenes":[' + (one % 1) + "]}")), 1,
       "한 장면인데 여러 개로 셌다 — 대사 원소까지 장면으로 세고 있다")

    # 포장 객체 자신도 장면이 아니다
    eq(stream('{"total":3,"scenes":[]}'), [], "포장 객체를 장면으로 셌다")
    eq(stream('{"speaker_id":"A","text":"안녕"}'), [], "대사 원소 하나를 장면으로 셌다")

    # 대사에 괄호가 들어 있어도 어긋나지 않는다
    tricky = ('{"order":7,"purpose":"목적","emotion":"놀람",'
              '"dialogue":[{"speaker_id":"A","text":"이건 {중괄호} 와 \\"따옴표\\" 다"}],'
              '"image_prompt":"x"}')
    eq(stream("[" + tricky + "]"), [7], "대사 속 괄호·따옴표에 경계가 어긋난다")


@test("webapp", "W38 고유 캐릭터 — 서랍·사진·출연진이 웹으로 왕복하고, 사진 경로는 서랍 밖을 못 가리킨다", web=True)
def w38(b: Box):
    """모듈 검사(U51)가 보는 것은 함수다. 이 검사가 보는 것은 **배선**이다 —
    라우트가 등록됐는가, 화면이 받는 모양이 맞는가, 사진이 실제로 돌아오는가.

    사진 서빙을 특히 본다. ``/ref/`` 는 **사람이 올린 파일을 다시 내보내는 창구**라,
    경로 한 줄이 새면 그 자리가 저장소 파일 배달로 변한다. 그리고 그건 브라우저에서
    한 번 열어 보는 것으로는 절대 눈치챌 수 없는 종류의 구멍이다.
    """
    png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4z8AAAAMBAQAY3Y2w"
           "AAAAAElFTkSuQmCC")      # 1×1 PNG

    code, got = b.wapi("/api/oc", {})
    eq(code, 200, "서랍 목록 라우트가 없다")
    base = len(got.get("characters") or [])
    lock = got.get("face_lock") or {}
    # 값이 아니라 **모양**을 본다. 사진으로 얼굴을 잡을 수 있는지는 이 기계에 모델이
    # 깔려 있는가에 달렸고, 그건 코드의 옳고 그름이 아니다. 검사가 볼 것은 화면이
    # 언제나 '되는지 여부'와 '그 이유'를 함께 받는가이다.
    ok(isinstance(lock.get("ok"), bool), "얼굴 고정 가능 여부가 참·거짓으로 오지 않는다: %r" % lock)
    ok(str(lock.get("note") or "").strip(), "얼굴 고정 상태에 설명이 없다 — 사람이 판단할 수 없다")

    code, made = b.wapi("/api/oc-save", {"fields": {
        "name": "W38 연우", "prompt_anchor": "24-year-old Korean man, short black hair",
        "prompt_tags": ["short black hair", "grey hoodie"],
        "profile": {"age": "24", "speech_style": "담담한 반말"}}})
    eq(code, 200, "인물 저장이 200 이 아니다: %s" % str(made)[:120])
    oc = made.get("character") or {}
    cid = oc.get("id", "")
    ok(cid.startswith("OC-"), "새 인물의 id 가 이상하다: %r" % cid)
    eq(oc.get("photos"), [], "새 인물에 사진이 붙어 있다")

    # 조립이 이 인물을 쓰려면 검사기 A2 가 먼저 그를 알아야 한다 — 저장하면서 얹혀야 한다
    code, st = b.wapi("/api/state", None)
    ok(any(c.get("id") == cid for c in (st.get("characters") or [])),
       "새 인물이 매니페스트에 얹히지 않았다 — 그 인물로 만든 장면은 검사기에서 빨간불이다")

    # 사진 — 올리고, 돌려받고, 뗀다
    code, up = b.wapi("/api/oc-photo", {"id": cid, "b64": "data:image/png;base64," + png,
                                        "label": "정면"})
    eq(code, 200, "사진 등록이 200 이 아니다: %s" % str(up)[:120])
    photos = (up.get("character") or {}).get("photos") or []
    eq(len(photos), 1, "사진이 인물에 붙지 않았다")
    url = photos[0].get("url", "")
    ok(url.startswith("/ref/" + cid + "/"), "사진 주소가 이 인물 밑이 아니다: %r" % url)
    code, _hd, body = b.raw(url, None, {}, 20)
    eq(code, 200, "등록한 사진이 돌아오지 않는다")
    ok(body.startswith(b"\x89PNG"), "돌아온 것이 그 그림이 아니다")

    # 그림이 아닌 것은 애초에 못 올라간다(이 폴더는 그대로 웹으로 나간다)
    evil = base64.b64encode(b"MZ\x90\x00" + b"0" * 64).decode("ascii")
    eq(b.code("/api/oc-photo", {"id": cid, "b64": evil}), 400,
       "실행 파일을 사진으로 받았다")

    # 서랍 밖을 가리키는 주소는 404 다 — 200 이면 저장소 파일이 그대로 나간 것이다.
    #
    # **깊이를 하나로 고정하지 않는다.** 처음엔 ../ 를 세 번만 썼는데, 서랍이
    # project/characters/refs 라 세 번은 project/ 까지밖에 못 간다 — 방어를 통째로 빼도
    # 검사는 통과했다. 검사가 저장소 구조에 맞춰 조용히 무력해진 것이다.
    # (전송 중에 ../ 가 정리되지 않는다는 것은 확인했다: 서버는 원문 그대로 받는다.)
    evil_urls = ["/ref/NOT-AN-ID/x.png", "/ref/", "/ref/" + cid + "/"]
    for depth in range(1, 9):
        up_path = "../" * depth
        evil_urls.append("/ref/" + cid + "/" + up_path + "tools/vn_core.py")
        evil_urls.append("/ref/" + cid + "/" + up_path.replace("/", "%2f") + "tools%2fvn_core.py")
    for evil_url in evil_urls:
        code, _hd, body = b.raw(evil_url, None, {}, 20)
        ok(code != 200 or b"vn_core" not in body,
           "서랍 밖 파일이 나왔다: %s → %d (%d바이트)" % (evil_url, code, len(body)))

    code, off = b.wapi("/api/oc-photo-delete", {"id": cid, "rel": photos[0].get("rel")})
    eq(code, 200, "사진 떼기가 200 이 아니다")
    eq((off.get("character") or {}).get("photos"), [], "뗐는데 목록에 남아 있다")

    # 출연진 — 이 대화에 누가 나오는가
    code, cast = b.wapi("/api/cast", {"chat_id": "w38chat"})
    eq(code, 200, "출연진 라우트가 없다")
    eq(cast.get("cast"), None, "새 대화인데 출연진이 이미 정해져 있다")
    code, cast = b.wapi("/api/cast", {"chat_id": "w38chat", "ids": [cid]})
    eq(cast.get("cast"), [cid], "출연진이 저장되지 않았다")
    eq([n.get("name") for n in (cast.get("names") or [])], ["W38 연우"],
       "출연진 이름이 화면으로 돌아오지 않는다")
    # **빈 목록도 답이다** — '아무도 안 나온다'(고양이·풍경 단편)
    code, cast = b.wapi("/api/cast", {"chat_id": "w38chat", "ids": []})
    eq(cast.get("cast"), [], "'아무도 안 나온다' 가 '안 정함' 으로 뭉개졌다")
    code, cast = b.wapi("/api/cast", {"chat_id": "w38chat"})
    eq(cast.get("cast"), [], "빈 출연진이 저장되지 않았다 — 다시 읽으면 사라진다")

    # 내리기 — 보관하고, 매니페스트의 사본은 남긴다
    code, gone = b.wapi("/api/oc-delete", {"id": cid})
    eq(code, 200, "인물 내리기가 200 이 아니다: %s" % str(gone)[:120])
    code, got = b.wapi("/api/oc", {})
    eq(len(got.get("characters") or []), base, "서랍에서 내려가지 않았다")
    code, st = b.wapi("/api/state", None)
    ok(any(c.get("id") == cid for c in (st.get("characters") or [])),
       "매니페스트에서까지 뺐다 — 그 인물로 만든 장면이 검사기에서 빨간불이 된다")


@test("webapp", "W39 시크릿 대화 — 오간 말이 디스크 어디에도 남지 않는다(파일도, 로그도)", web=True)
def w39(b: Box):
    """이 기능의 약속은 하나다: **오간 말이 이 기계에 남지 않는다.**

    그 약속은 코드를 읽어서 확인할 수 있는 종류가 아니다. 남지 않는다는 것은 '어디에도'
    라는 뜻이고, 어디에는 내가 생각하지 못한 자리도 들어간다. 그래서 이 검사는 반대로 한다:
    **저장소 전체를 훑어서 그 문장이 있는지 찾는다.** 대화 폴더만 보는 것이 아니라 로그도,
    매니페스트도, 작업 폴더도 본다.

    찾는 문장은 일부러 저장소 어디에도 없을 법한 말로 짓는다 — 흔한 말이면 우연히
    걸려서 검사가 거짓 경보를 낸다.

    같이 확인하는 것:
      * 평범한 대화는 **여전히 남는다**(시크릿이 일반 경로를 망가뜨리지 않았는가).
      * 목록에 시크릿 대화가 **안 보인다**(서버는 그런 게 있었는지도 모른다).
    """
    # **조각으로 만든다.** 통짜로 적으면 이 파일 자신이 걸려서 검사가 늘 빨간불이다
    # (첫 실행에서 실제로 그랬다). 소스에는 조각만 있고, 찾는 문장은 실행 중에만 존재한다.
    needle = "요란한" + "보라색코끼리가" + "재채기를했다"
    calm = "평범한" + "대화문장하나"

    code, got = b.wapi("/api/chat", {"private": True, "use_context": False,
                                     "messages": [{"role": "user", "content": needle}]})
    eq(code, 200, "시크릿 대화가 200 이 아니다: %s" % str(got)[:160])
    ok(got.get("reply") is not None, "답이 없다")
    eq(got.get("private"), True, "시크릿으로 처리했다고 말하지 않는다")

    # 평범한 경로는 그대로 저장돼야 한다(시크릿이 일반 경로를 망가뜨리지 않았는가)
    code, _ = b.wapi("/api/chat", {"chat_id": "w39plain",
                                   "messages": [{"role": "user", "content": calm}]})
    eq(code, 200, "평범한 대화가 깨졌다")

    # **저장소 전체**를 훑는다. 텍스트로 열리는 파일만 본다(png 를 뒤질 이유는 없다).
    def hunt(word):
        hits = []
        for p in b.root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".zip", ".pyc"):
                continue
            try:
                if word in p.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(p.relative_to(b.root)))
            except OSError:
                continue
        return hits

    left = hunt(needle)
    eq(left, [], "시크릿 대화가 디스크에 남았다: %s" % left)

    kept = hunt(calm)
    ok(kept, "평범한 대화가 저장되지 않았다 — 시크릿이 일반 경로를 망가뜨렸다")

    # 서버는 시크릿 대화가 있었다는 것조차 모른다
    code, lst = b.wapi("/api/chats", {})
    ids = [c.get("id") for c in (lst.get("chats") or [])]
    ok("w39plain" in ids, "평범한 대화가 목록에 없다")
    for cid in ids:
        ok(not str(cid).startswith("s_"), "시크릿 대화가 서버 목록에 나타났다: %s" % cid)

    # 글을 들고 오는 조립 경로 — 너무 짧으면 거절한다(모델을 1~2분 붙잡지 않게)
    eq(b.code("/api/compose-text", {"text": "짧다"}), 400, "너무 짧은 글로 조립을 시작했다")


@test("webapp", "W40 MakeFun 선택 — 돈이 드는지 먼저 말하고, 얼굴 사진은 허락 없이 밖으로 나가지 않는다", web=True)
def w40(b: Box):
    """장면 탭에서 엔진을 고를 수 있게 되면 **두 가지가 한 번의 클릭 뒤로 숨는다**:
    돈과 사진.

    돈 — MakeFun 은 유료다. 엔진을 설정 화면에 숨겨 두면 사람은 [그림 뽑기] 를 누른
    **뒤에** 돈이 나갔다는 걸 안다. 그래서 누르기 전에 물어볼 수 있는 자리(/api/gen-cost)를
    두고, 거기서 **숫자를 지어내지 않는다** — 장당 크레딧은 공급자가 공개하지 않았고
    (docs/MAKEFUN_CAPABILITIES.md §1) 근거 없는 숫자를 띄우면 사람은 그걸 믿고 결정한다.

    사진 — MakeFun 의 인물 일관성은 레퍼런스를 **그쪽 저장소(R2)에 올려서** 쓴다.
    그 레퍼런스가 사람의 진짜 얼굴 사진이다. 기본을 '보낸다' 로 두면 엔진을 한 번 바꾼
    것만으로 얼굴이 이 기계 밖으로 나간다. 그래서 기본은 **안 보낸다** 이고, 화면이
    묻고 사람이 켤 때만 실린다.

    이 검사는 **실호출을 하지 않는다**(유료다). 라우트가 무엇을 말하고 무엇을 넘기는지만 본다.
    """
    code, got = b.wapi("/api/gen-cost", {"engine": "comfyui"})
    eq(code, 200, "비용 안내 라우트가 없다")
    eq(got.get("billable"), False, "이 기계에서 굽는데 유료라고 한다")
    ok(str(got.get("note") or "").strip(), "무료라는 사실만 말하고 이유를 안 말한다")

    code, got = b.wapi("/api/gen-cost", {"engine": "makefun"})
    eq(code, 200, "MakeFun 비용 안내가 없다")
    eq(got.get("billable"), True, "유료인데 유료라고 안 한다")
    eq(got.get("credits"), None,
       "장당 크레딧을 숫자로 말한다 — 근거가 없는 숫자다(공급자가 공개하지 않았다)")
    note = str(got.get("note") or "")
    ok("유료" in note, "무엇이 드는지 말하지 않는다: %r" % note[:80])
    ok(not re.search(r"\d+\s*(크레딧|credit)", note),
       "근거 없는 크레딧 숫자가 문구에 들어 있다: %r" % note[:120])

    eq(b.code("/api/gen-cost", {"engine": "nosuchengine"}), 400, "모르는 엔진을 받아들였다")

    # 얼굴 사진이 딸린 인물을 만들고, **동의 없이는 실리지 않는지** 본다
    code, made = b.wapi("/api/oc-save", {"fields": {"name": "W40 사람"}})
    cid = (made.get("character") or {}).get("id", "")
    png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4z8AAAAMBAQAY3Y2w"
           "AAAAAElFTkSuQmCC")
    eq(b.code("/api/oc-photo", {"id": cid, "b64": png}), 200, "사진 등록 실패")
    code, sc = b.wapi("/api/scene-add", {"fields": {"purpose": "W40"}})
    sid = sc.get("scene_id")
    b.wapi("/api/set-scene", {"scene_id": sid, "fields": {"characters": [cid]}})

    code, cost = b.wapi("/api/gen-cost", {"scene_id": sid, "engine": "makefun"})
    names = [f.get("id") for f in (cost.get("faces") or [])]
    eq(names, [cid], "이 장면에 사진 있는 인물이 있는데 안 알려 준다")
    ok("밖으로" in str(cost.get("face_note") or ""),
       "사진이 기계 밖으로 나간다는 사실을 말하지 않는다: %r" % str(cost.get("face_note"))[:100])

    # 라우트가 makefun 에 **무엇을 넘기는가** — 실호출 대신 가짜 엔진으로 가로채서 본다.
    #
    # 웹으로 부르지 않는 이유: 이 검사의 웹 서버는 **다른 프로세스**라 여기서 갈아 끼운
    # 가짜가 그쪽에 닿지 않는다. 라우트 함수는 평범한 파이썬이므로 같은 프로세스에서
    # 직접 부른다(디스크는 서버와 같은 것을 본다).
    wb = b.mod("webapp")
    real = wb.image_gen.generate_for_scene
    seen: dict = {}

    def fake(sid_, **kw):
        seen.clear()
        seen.update(kw)
        raise RuntimeError("여기서 멈춘다 — 유료 경로는 실호출하지 않는다")

    try:
        wb.image_gen.generate_for_scene = fake
        for body, want, why in (
                ({"scene_id": sid, "engine": "makefun", "sync": True}, False,
                 "동의하지 않았는데 레퍼런스(얼굴 사진)를 보내라고 넘겼다"),
                ({"scene_id": sid, "engine": "makefun", "sync": True, "send_face": True}, True,
                 "동의했는데 사진을 안 보낸다")):
            seen.clear()
            try:
                wb.r_gen_image(body)
            except Exception:
                pass                      # 가짜가 일부러 터뜨린다 — 우리가 볼 것은 넘긴 값이다
            eq(seen.get("reference"), want, why)
        seen.clear()
        try:
            wb.r_gen_image({"scene_id": sid, "engine": "comfyui", "sync": True})
        except Exception:
            pass
        ok("reference" not in seen,
           "이 기계로 구울 때까지 레퍼런스 스위치를 건드린다 — 예전 동작이 달라진다")
    finally:
        wb.image_gen.generate_for_scene = real
        b.wapi("/api/scene-delete", {"scene_id": sid})
        b.wapi("/api/oc-delete", {"id": cid})


@test("js", "J19 화면이 사람의 자리를 빼앗지 않는다 — 탭·잠금·복구 수단·결과 자리")
def j19(b: Box):
    """BACKLOG §U 의 네 건(160·161·162·164)을 한자리에서 잠근다. 공통점이 있다:
    **서버는 옳게 만들어져 있는데 화면이 사람이 하던 일을 덮는다.**

    브라우저로 재현하기 어려운 것들이라(여러 기기·타이밍) 소스에서 그 구조가 남아
    있는지를 본다. 약한 검사지만, 이 네 줄은 지우거나 되돌리기가 쉬운 종류다 —
    실제로 전부 한 줄씩 잘못 적혀 있었다.
    """
    NL = chr(10)
    js = (b.root / "tools" / "chat_ui.js").read_text(encoding="utf-8")
    html = (b.root / "tools" / "chat_ui.html").read_text(encoding="utf-8")

    # 161 — **배경에서 끝난 작업**이 보고 있던 탭을 빼앗지 않는다.
    # 사람이 직접 누른 흐름(장면 추가·편집·삭제·영상)에서 장면 탭으로 가는 것은 옳다 —
    # 그건 그 사람이 방금 시킨 일이다. 문제는 지켜보기만 하던 고리가 끌고 가는 것이다.
    def body(name):
        at = js.find(name)
        ok(at > 0, "%s 를 못 찾았다" % name)
        ends = [x for x in (js.find(NL + "function ", at + 10),
                            js.find(NL + "async function ", at + 10)) if x > 0]
        return js[at:min(ends) if ends else len(js)]

    for name in ("async function watchGen(", "async function watchGenAll("):
        src = body(name)
        ok('showView("scenes")' not in src,
           "%s 가 끝나면서 장면 탭으로 끌고 간다 — 갤러리·감상본을 보던 사람이 튕겨 나가고,"
           " **다른 기기에서 시작한 그림** 때문에도 똑같이 당한다" % name.strip())
        ok("showView(S.view)" in src, "%s 가 보던 탭을 다시 그리지 않는다" % name.strip())

    # 160 — 대화를 옮기면 떠나온 요청을 끊고 잠금을 푼다
    at = js.find("async function openChat(")
    head = js[at:at + 1200]
    ok("S.abort.abort()" in head,
       "대화를 옮겨도 기다리던 요청을 안 끊는다 — 새 대화에서 아무것도 못 보내고, "
       "늦게 온 오류가 남의 화면에 떨어진다")
    ok("setBusy(false)" in head, "옮긴 뒤에도 보내기 잠금이 남는다")

    # 163 — 첫 장면이 오기 전에 작업이 사라져도 알아챈다
    gone = [ln for ln in js.split(NL) if "!st.running" in ln and "st.scenes" in ln]
    eq(len(gone), 1, "'작업이 사라졌다' 판정이 한 곳이 아니다: %d" % len(gone))
    ok("S.shown" not in gone[0],
       "'장면을 하나라도 받았을 때' 만 사라짐을 판정한다 — 시작 직후에 당한 기기는 "
       "죽은 막대를 보며 7분을 기다린다: %s" % gone[0].strip())

    # 164 — 복구 수단은 '지난 제안' 과 함께 걷히지 않는다
    ok('classList.contains("keep")' in js,
       "제안을 걷어낼 때 복구 줄까지 걷는다 — 실패 직후 한 마디만 더 물으면 "
       "100초짜리 원문을 잃는다")
    ok('el("div", "offer keep")' in js, "복구 줄에 지켜야 한다는 표시가 없다")

    # 162 — 진행과 '사람이 응답해야 하는 결과' 가 다른 자리에 산다
    ok('id="keepbox"' in html, "결과 전용 자리가 없다 — 폴링이 2.5초마다 덮는다")
    ok("function keepShow(" in js and "function keepHide(" in js, "결과 자리를 쓰는 함수가 없다")
    for who in ("chat-export", "chat-import"):
        at = js.find(who)
        ok(at > 0, "%s 경로를 못 찾았다" % who)
        ok("keepShow(" in js[at:at + 1400],
           "%s 결과를 진행 자리에 띄운다 — 내려받기 링크가 폴링에 덮여 사라진다" % who)


@test("js", "J16 통합 화면 — 굽던 그림이 새로고침 뒤에도 이어지고, 거절당한 기기가 조용해지지 않는다")
def j16(b: Box):
    """전부 '데이터는 안전한데 사람이 두 번 일하게 되는' 종류다.

    (1) **새로고침** — 그림은 서버에서 계속 굽는다. 멈추는 건 화면의 폴링뿐이다. 그런데
        화면이 아무 일도 없는 얼굴이면 사람은 죽은 줄 알고 같은 장면을 한 번 더 시킨다.
        23초짜리 GPU 시간이 두 배로 든다. 그래서 서버가 /api/state 로 '지금 굽는 것'을
        말하고, 화면은 그걸 보고 다시 붙는다.
    (2) **두 번째 기기** — 폰과 PC 를 번갈아 쓰면 나중에 누른 쪽이 거절당한다. 예전에는
        빨간 줄 하나 뜨고 그대로 멈춰 있었다. 거절의 흔한 이유가 "이미 돌고 있다" 이므로
        할 일은 새로 시작이 아니라 **그 진행을 같이 보는 것**이다.
    (3) **줄어드는 목록** — S.shown 은 올라가기만 했다. 버리기·다른 기기 저장·서버 재시작
        으로 목록이 줄면 그 뒤 장면은 영원히 안 보였다(목록은 느는데 화면은 조용했다).
    """
    p = b.p("tools/chat_ui.js")
    if not p.exists():
        raise Gap("tools/chat_ui.js 아직 없음 — 통합 화면 미도입")
    js = p.read_text(encoding="utf-8")
    web = b.p("tools/webapp.py").read_text(encoding="utf-8")

    # (1) 서버가 말하고, 화면이 듣는다
    has(web, "gen_running", "/api/state 가 굽고 있는 작업을 싣지 않는다 — 새로고침하면 진행이 사라진다")
    has(js, "gen_running", "화면이 굽고 있는 작업을 묻지 않는다")
    has(js, "async function watchGen", "굽는 것을 지켜보는 고리가 genFor 안에 묻혀 있다 — 새로고침 뒤에 못 쓴다")
    boot = js[js.index("async function boot("):]
    ok("watchGen(" in boot, "boot 가 돌고 있는 그림 작업에 다시 붙지 않는다")

    # 장수를 모를 때(새로고침 뒤)는 서버의 want 를 봐야 진행 막대가 맞는다
    wg = js[js.index("async function watchGen("):]
    wg = wg[:wg.index("function genStopBtn")]
    has(wg, "st.want", "새로고침 뒤 요청 장수를 서버에서 읽지 않는다 — 진행 막대가 늘 0 이다")

    # (2) 거절 뒤에 상태를 다시 묻는가
    rc = js[js.index("async function runCompose("):]
    rc = rc[:rc.index("function liveShow")]
    ok("/api/compose-job-status" in rc,
       "조립이 거절당했을 때 상태를 다시 묻지 않는다 — 두 번째 기기가 빨간 줄 하나 보고 멈춘다")
    ok("startPolling()" in rc.split("catch (e)")[1],
       "거절당한 기기가 돌고 있는 작업을 따라가지 않는다")

    # (3) 줄어든 목록을 따라가는가
    pc = js[js.index("async function pollCompose("):]
    pc = pc[:pc.index("function showCancel")]
    ok("S.shown > scenes.length" in pc,
       "장면 목록이 줄어도 S.shown 이 따라가지 않는다 — 그 뒤 장면이 영원히 안 보인다")

    # (4) 기본 대화는 스튜디오 스토리 탭과 같은 파일이다 — 끄기 전에 말해야 한다
    cx = js[js.index("function ctxSwitch("):]
    cx = cx[:cx.index("function pasteBox")]
    ok("confirm(" in cx,
       "기본 대화의 작품 설정을 조용히 끈다 — 스튜디오 스토리 탭의 대답까지 같이 백지가 된다")
    ok("S.chatId" in cx.split("confirm(")[0].split("addEventListener")[-1],
       "확인을 새 대화에도 묻는다 — 새 대화는 이 화면 전용이라 물을 이유가 없다")


@test("js", "J14 통합 화면(/chat) — 스튜디오와 같은 강도로 잠근다(주입 API 0 · 인라인 0 · 파괴 경로 0)")
def j14(b: Box):
    """두 번째 화면이 생겼다고 규칙이 반값이 되면 안 된다.

    J01 이 studio.html 만 훑기 때문에, 새 화면은 아무 검사도 받지 않은 채 같은 서버에서
    같은 데이터를 고칠 수 있었다. 여기서 세 가지를 같은 강도로 건다.
      1) 문자열 주입 DOM API 0 — studio.html 과 같은 기준(BANNED_DOM).
      2) 인라인 스크립트 0 — 이 문서가 CSP 에서 'unsafe-inline' 을 떼는 조건이다(W27 과 같은 이유).
         한 번 깨진 적이 있다: 주석에 스크립트 여는 태그를 글자로 적었더니 has_inline_script
         가 그것을 세어 CSP 가 조용히 느슨해졌다.
      3) 파괴 경로 0 — /api/compose 의 force 는 승인된 장면을 전부 밀어낸다. 이 화면은
         대화로 굴리는 곳이라 그 버튼이 있어서는 안 된다. 조립은 compose-manual 로만 한다.
    """
    p = b.p("tools/chat_ui.html")
    if not p.exists():
        raise Gap("tools/chat_ui.html 아직 없음 — 통합 화면 미도입")
    html = p.read_text(encoding="utf-8")
    sources = [html] + _page_js(b, html, "chat_ui")

    for src in sources:
        for api in BANNED_DOM:
            eq(src.count(api), 0, f"통합 화면이 실행하는 JS 가 {api} 사용")

    eq(len(_scripts(html)), 0,
       "통합 화면에 인라인 스크립트가 있다 — csp_for 가 'unsafe-inline' 을 남긴다")

    js = "\n".join(sources)
    eq(js.count("/api/compose\""), 0, "통합 화면이 /api/compose 를 부른다(force 로 앨범이 날아간다)")
    eq(js.count("/api/compose'"), 0, "통합 화면이 /api/compose 를 부른다(force 로 앨범이 날아간다)")
    ok(not re.search(r"force\s*:\s*true", js),
       "통합 화면이 force:true 를 보낸다 — 승인된 장면을 지우는 경로다")
    has(js, "/api/compose-manual", "조립 저장 경로(compose-manual)가 없다")
    has(js, "/api/select", "사람이 고르는 경로(select)가 없다 — 자동 선택이면 A3 가 무너진다")

    _node_check(b, html, "chat_ui")


@test("js", "J02 감상본 HTML — JS 문법 통과(내보낸 결과물 그대로)")
def j02(b: Box):
    tcm = b.mod("export_viewer")
    with approved_scene(b), quiet():
        html = tcm.export(False, 640, 70)[0].read_text(encoding="utf-8")
    _node_check(b, html, "viewer")


@test("js", "J03 공용 VN 런타임 — 단일 전역·주입 지점·문법·금지 DOM API 0")
def j03(b: Box):
    """스튜디오 뷰어와 감상본이 같은 파일을 쓰는 이상, 이 파일 하나가 두 화면을 동시에
    깨뜨릴 수 있다. 그래서 감상본과 같은 강도로 잠근다."""
    p = b.p("tools/vn_runtime.js")
    if not p.exists():
        raise Gap("tools/vn_runtime.js 아직 없음 — 스튜디오·감상본 공용 재생 엔진 이관 대기")
    src = p.read_text(encoding="utf-8")
    for api in BANNED_DOM:
        eq(src.count(api), 0, f"vn_runtime.js 가 {api} 사용")
    has(src, "VNRuntime", "전역 이름(window.VNRuntime)")
    has(src, "mount", "mount(opts) 진입점")
    has(src, "imageSrc", "이미지 경로 주입 지점(감상본 data URI · 스튜디오 /img)")
    for net in ("XMLHttpRequest", "fetch("):
        eq(src.count(net), 0, f"자기완결이어야 할 런타임이 {net} 사용(감상본에서 죽는다)")
    _node_check_src(b, src, "vn_runtime")


@test("js", "J04 감상본 자기완결 — 공용 런타임이 인라인되고 외부 script src 가 없다")
def j04(b: Box):
    rt = b.p("tools/vn_runtime.js")
    if not rt.exists():
        raise Gap("tools/vn_runtime.js 아직 없음 — 감상본 인라인 대상이 없다")
    ev = b.mod("export_viewer")
    with approved_scene(b), quiet():
        html = ev.export(False, 640, 70)[0].read_text(encoding="utf-8")
    hasnt(html, "__RUNTIME__", "치환되지 않은 자리표시자가 감상본에 그대로 남음")
    if "VNRuntime" not in html:
        raise Gap("export_viewer 가 아직 tools/vn_runtime.js 를 인라인하지 않음 "
                  "— 감상본이 스튜디오와 다른 엔진으로 재생된다")
    ok(not re.search(r"<script\b[^>]*\ssrc=", html, re.I),
       "감상본이 외부 스크립트를 참조(파일 하나만 옮기면 재생이 죽는다)")
    # 인라인된 내용이 실제로 그 파일인지 — 특징 토큰 몇 개로 확인(공백·개행 차이는 무시)
    marks = [m for m in ("VNRuntime", "mount", "imageSrc") if m in rt.read_text(encoding="utf-8")]
    for m in marks:
        has(html, m, "런타임 일부만 인라인됨")
    for api in BANNED_DOM:
        eq(html.count(api), 0, f"감상본이 {api} 사용")


def _js_funcs(src: str, *names: str) -> str:
    """studio.js 에서 함수 정의 몇 개만 떼어 낸다 — 브라우저 없이 node 로 불러 보기 위해.

    이 파일의 서식 규약(정의는 열 0 에서 시작하고 이어지는 줄은 공백으로 시작한다)에 기댄다.
    앵커를 못 찾으면 조용히 통과하지 않고 실패한다(이름을 바꿨다면 이 검사도 함께 고칠 자리다).
    """
    lines = src.splitlines()
    tops = [i for i, l in enumerate(lines) if l and not l[0].isspace()]
    out = []
    for name in names:
        head = next((i for i in tops
                     if re.match(rf"(async\s+)?function\s+{re.escape(name)}\s*\(", lines[i])), None)
        if head is None:
            raise Failed(f"studio.js 에서 {name}() 정의를 찾지 못했습니다 — 이름을 바꿨다면 이 검사도 고치세요")
        end = next((i for i in tops if i > head), len(lines))
        out.append("\n".join(lines[head:end]))
    return "\n".join(out)


def _node_json(b: Box, code: str, label: str) -> dict:
    """작은 JS 조각을 node 로 실행하고 마지막 줄의 JSON 을 돌려준다(DOM 없이 함수 단위 확인)."""
    node = shutil.which("node")
    if not node:
        raise Skip("node 없음 — JS 동작 검사 생략")
    tmp = b.root / f"_run_{label}.js"
    tmp.write_text(code, encoding="utf-8")
    proc = subprocess.run([node, str(tmp)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    tmp.unlink(missing_ok=True)
    eq(proc.returncode, 0, f"{label} 실행 실패 — {(proc.stderr or proc.stdout)[:400]}")
    body = [l for l in (proc.stdout or "").splitlines() if l.strip()]
    ok(body, f"{label} 이 아무것도 내지 않음")
    return json.loads(body[-1])


@test("js", "J11 대사창·툴바의 폭 기준은 창이 아니라 그림이다(레터박스 밖으로 넘치지 않는다)")
def j06(b: Box):
    """1280×900 창에서 그림은 600px 인데 대사창이 880px 로 뻗어 양옆 140px 씩 넘치고,
    툴바 오른끝은 그림보다 326px 바깥에 있었다 — 글과 버튼이 그림에서 떨어져 나왔다.

    브라우저 없이 잠글 수 있는 것은 **계약**이다: ① 두 요소의 폭·위치가 그림 폭
    (`--vnr-picw`·`--vnr-gut`)을 보고, ② 그 값을 재는 곳이 있고, ③ 창 크기가 바뀌면 다시
    재고, ④ 그 리스너를 destroy 가 **되돌린다**(스튜디오는 뷰어를 열고 닫기를 반복한다),
    ⑤ 폰의 한 줄 툴바 규칙은 건드리지 않는다. 실제 픽셀은 실행해 확인했다(1280×900 ·
    1600×1000 · 400×860 전/후 스크린샷).
    """
    src = b.p("tools/vn_runtime.js").read_text(encoding="utf-8")
    # ① 폭의 기준
    has(src, "width:min(880px,92%,calc(var(--vnr-picw,100%) - 16px))",
        "대사창이 아직 창 폭(880px/92%)만 본다")
    has(src, "right:calc(14px + var(--vnr-gut,0px)", "툴바가 창 오른끝에 붙어 있다")
    has(src, "calc(var(--vnr-picw,100%) - 24px)", "툴바 최대폭이 그림 폭을 안 본다")
    # ② 재는 곳 · ③ 다시 재는 계기
    has(src, 'setProperty("--vnr-picw"', "그림 폭을 재서 넣는 곳이 없다")
    has(src, 'setProperty("--vnr-gut"', "레터박스 여백을 재서 넣는 곳이 없다")
    for ev in ("resize", "orientationchange", "fullscreenchange"):
        has(src, 'addEventListener("' + ev + '"', f"{ev} 때 다시 재지 않는다")
    # ④ 누수 없음 — 연 만큼 닫는다
    for ev in ("resize", "orientationchange", "fullscreenchange"):
        has(src, 'removeEventListener("' + ev + '"', f"destroy 가 {ev} 리스너를 안 거둔다")
    # ⑤ 폰 규칙은 그대로 · 좁아지면 버튼을 [⋯] 로 옮긴다(새로 만들지 않는다)
    has(src, "@media(pointer:coarse){", "폰 한 줄 툴바 규칙이 사라졌다")
    has(src, "function setBarCompact", "좁은 무대에서 툴바를 접는 장치가 없다 — 폭만 줄이면 두세 줄로 접힌다")
    has(src, "BAR_MAIN = [E.chip, E.aff, E.bAuto, E.bScenes, E.bMore, E.bExit]",
        "접은 툴바가 같은 버튼 노드를 쓰지 않는다(동작·단축키가 갈린다)")


@test("js", "J05 MakeFun 보조 버튼 — 토큰이 없으면 눌리지 않는다(유료 확인창 뒤의 확정 실패 차단)")
def j05(b: Box):
    """매니페스트에 makefun 블록만 있으면 보조 버튼은 생긴다. 그런데 MAKEFUN_API_TOKEN 이 서버에
    없으면 누르는 순간 '유료 호출입니다. 진행할까요?' 를 묻고 **확인한 뒤에** 실패한다 —
    사용자는 돈이 나갔는지조차 알 수 없다. 토큰이 없으면 이유를 달고 눌리지 않아야 한다.
    """
    src = b.p("tools/studio.js")
    if not src.exists():
        raise Gap("tools/studio.js 아직 없음 — 스튜디오 스크립트 분리 대기")
    funcs = _js_funcs(src.read_text(encoding="utf-8"),
                      "imgEngine", "imgEngines", "mfToken", "scBtnGenImageAlt")
    harness = """
let S={};let confirmed=0,started=0;
function confirm(){confirmed++;return true}
function el(tag,cls,txt){return {tag:tag,cls:cls,textContent:txt,title:"",disabled:false,onclick:null}}
function runGenImage(){started++}
__FUNCS__
function probe(state){S=state;confirmed=0;started=0;
 const b=scBtnGenImageAlt({scene_id:"SCENE-001"},{});
 if(b&&b.onclick&&!b.disabled)b.onclick();
 return {present:!!b,label:b?b.textContent:"",title:b?b.title:"",
         disabled:!!(b&&b.disabled),confirmed:confirmed,started:started}}
const two={engine:"comfyui",engines:["comfyui","makefun"]};
console.log(JSON.stringify({
 noToken:probe({image:Object.assign({},two,{mf_token:false})}),
 token:probe({image:Object.assign({},two,{mf_token:true})}),
 free:probe({image:{engine:"makefun",engines:["makefun","comfyui"],mf_token:true}}),
 alone:probe({image:{engine:"comfyui",engines:["comfyui"],mf_token:true}})}));
""".replace("__FUNCS__", funcs)
    r = _node_json(b, harness, "studio_alt")
    no = r["noToken"]
    ok(not no["present"] or no["disabled"],
       f"토큰이 없는데 누를 수 있는 MakeFun 버튼이 붙는다 — {no}")
    eq((no["confirmed"], no["started"]), (0, 0), f"토큰 없이 과금 확인창·생성 요청 — {no}")
    if no["present"]:
        has(no["title"], "MAKEFUN_API_TOKEN", "왜 눌리지 않는지 말하지 않음")
    yes = r["token"]
    ok(yes["present"] and not yes["disabled"], f"토큰이 있는데 보조 버튼이 막혔다 — {yes}")
    has(yes["label"], "MakeFun", "유료 버튼 표기")
    eq((yes["confirmed"], yes["started"]), (1, 1), f"유료 확인 한 번 뒤 생성 — {yes}")
    free = r["free"]
    ok(free["present"] and not free["disabled"], f"무료(ComfyUI) 보조 버튼이 막혔다 — {free}")
    eq((free["confirmed"], free["started"]), (0, 1), f"무료 경로가 과금 확인창을 띄운다 — {free}")
    eq(r["alone"]["present"], False, "엔진이 하나뿐인데 보조 버튼이 붙는다")



def _vnr_func(src: str, name: str) -> str:
    """vn_runtime.js 에서 함수 하나를 통째로 떼어 낸다(들여쓰기가 같은 줄의 닫는 괄호까지).

    이름을 못 찾으면 조용히 통과하지 않고 실패한다 — 이름을 바꿨다면 이 검사도 함께 고칠 자리다.
    """
    m = re.search(rf"^([ \t]*)function {re.escape(name)}\s*\(", src, re.M)
    if not m:
        raise Failed(f"vn_runtime.js 에서 {name}() 정의를 찾지 못했습니다 "
                     "— 이름을 바꿨다면 이 검사도 고치세요")
    indent, lines = m.group(1), src[m.start():].splitlines()
    out = [lines[0]]
    for line in lines[1:]:
        out.append(line)
        if line.startswith(indent + "}"):
            break
    return "\n".join(out)


@test("js", "J06 재생 엔진의 안전장치가 소스에 남아 있다(손짓 가드·컷 토큰·정수 검증·분기 폴백)")
def j06(b: Box):
    """브라우저에서만 드러났던 결함들을 소스 수준에서 잠근다.

    J07 이 실제로 굴려 보지만, **이미지 타이머·onerror** 처럼 DOM 대역으로 재현하기 어려운
    자리가 있다. 거기서 되돌아간 회귀는 "대사는 흐르는데 그림이 한 장도 없는 검은 무대" 로
    나타났다 — 장면이 페이드(0.54초)보다 빨리 바뀌면 앞 컷의 정리 타이머가 새 컷을 치우고,
    새 컷의 타이머가 남은 앞 컷을 치웠기 때문이다(스킵은 0.045초마다 넘어간다).
    """
    p = b.p("tools/vn_runtime.js")
    if not p.exists():
        raise Gap("tools/vn_runtime.js 아직 없음 — 공용 재생 엔진 이관 대기")
    src = p.read_text(encoding="utf-8")

    # ① 지금 무대에 있어야 할 컷을 가리키는 토큰 하나로, 늦게 도착한 일들을 전부 심판한다
    ri = _vnr_func(src, "renderImg")
    ok(ri.count("curImg") >= 3,
       "renderImg 이 '지금 컷' 토큰을 쓰지 않는다 — 빠른 장면 전환에서 무대가 비어 버린다")
    eq(ri.count("im !== curImg"), 2,
       "늦게 도착한 onload·onerror 두 곳 모두를 막고 있지 않다")
    ok(re.search(r"setTimeout\(function \(\) \{ if \(im === curImg\) clearImgs\(im\);", ri),
       "정리 타이머가 '내가 아직 현재 컷인가' 를 묻지 않는다(새 컷을 지운다)")

    # ② 선택지를 띄운 손짓이 선택까지 하지 않게 하는 가드
    for fn, why in (("showChoices", "선택지를 띄우면서 가드를 걸지 않는다"),
                    ("pick", "선택 직후 가드를 걸지 않는다 — 따라오는 클릭이 다음 장면의 첫 줄을 삼킨다")):
        has(_vnr_func(src, fn), "guardPointer()", why)
    for fn in ("onTap", "onTouchEnd"):
        has(_vnr_func(src, fn), "pointerGuarded()",
            f"{fn} 이 손짓 가드를 보지 않는다")
    has(_vnr_func(src, "showChoices"), "pointerGuarded()",
        "선택지 버튼이 손짓 가드를 보지 않는다 — 탭 한 번이 분기를 정해 버린다")

    # ③ 저장 위치는 정수만 통과한다
    st = _vnr_func(src, "start")
    for needle in ("intIn(pos.vi", "intIn(pos.di"):
        has(st, needle, "저장된 위치를 정수로 검증하지 않는다(손상된 저장이 뷰어를 멈춰 세운다)")
    ok(re.search(r"num\(pos && pos\.aff", st),
       "저장된 호감도를 수로 검증하지 않는다(NaN 이 눈금에 그대로 뜬다)")

    # ④ 갈 곳을 못 찾았다고 이야기를 끝내지 않는다
    nx = _vnr_func(src, "nextIndex")
    eq(nx.count("return -1"), 0,
       "만족되는 분기가 없을 때 -1 을 돌려준다 — 엔딩 장면도 아닌 곳에서 엔딩 카드가 뜬다")
    pk = _vnr_func(src, "pick")
    ok("nx = vi + 1" in pk,
       "없는 goto 를 만나면 선형 진행으로 잇지 않는다 — 선택 직후 가짜 엔딩이 뜬다")
    has(pk, "affPicks", "한 장면에서 고른 값을 장부에 적지 않는다(되돌아가 다시 고르면 쌓인다)")

    # ⑤ 수는 한 곳에서만 판정한다
    ns = _vnr_func(src, "normScene")
    for needle in ("num(c.affection", "num(b.min"):
        has(ns, needle, '선택지·분기의 수를 정규화하지 않는다("8" 이 문자열 덧셈이 된다)')

    # ⑥ 전체화면 거부가 사용자 콘솔에 남지 않는다
    has(_vnr_func(src, "quietly"), ".then(",
       "전체화면 요청의 거부(Promise)를 삼키지 않는다 — Uncaught (in promise) 가 찍힌다")
    has(_vnr_func(src, "toggleFull"), "quietly(", "toggleFull 이 그 방어를 쓰지 않는다")


# 최소 DOM 대역 — 브라우저 없이 tools/vn_runtime.js **원본 그대로** 를 올리기 위한 것.
# 화면을 흉내 내지 않는다(레이아웃·그리기 없음): 엔진이 실제로 만지는 것만 있다.
# 여기 걸리는 회귀는 스튜디오 뷰어와 감상본 양쪽에서 동시에 터지는 것들이다.
VNR_DOM_STUB = r"""
"use strict";
/* 최소 DOM 대역 — 브라우저 없이 재생 엔진을 그대로 올리기 위한 것.
   화면을 흉내 내지 않는다(레이아웃·그리기 없음): 엔진이 실제로 만지는 것만 있다. */
function El(tag) {
  this.tagName = String(tag || "div").toUpperCase();
  this.kids = []; this.parentNode = null; this.className = ""; this.attrs = {}; this.on = {};
  this.hidden = false; this.inert = false; this.disabled = false;
  this.scrollTop = 0; this.scrollHeight = 0; this.offsetWidth = 10; this.offsetHeight = 10;
  this.txt = "";
  this.style = { setProperty: function () {} };
  var self = this;
  this.classList = {
    add: function () { for (var i = 0; i < arguments.length; i++) self.cls(arguments[i], true); },
    remove: function () { for (var i = 0; i < arguments.length; i++) self.cls(arguments[i], false); },
    toggle: function (c, on) { self.cls(c, on === undefined ? !self.classList.contains(c) : !!on); },
    contains: function (c) { return self.className.split(/\s+/).indexOf(c) >= 0; }
  };
}
El.prototype.cls = function (c, on) {
  var l = this.className.split(/\s+/).filter(function (x) { return x && x !== c; });
  if (on) l.push(c);
  this.className = l.join(" ");
};
Object.defineProperty(El.prototype, "textContent", {
  get: function () {
    return this.kids.length ? this.kids.map(function (k) { return k.textContent; }).join("") : this.txt;
  },
  set: function (v) { this.kids = []; this.txt = String(v == null ? "" : v); }
});
Object.defineProperty(El.prototype, "children", {
  get: function () { return this.kids.slice(); }
});
Object.defineProperty(El.prototype, "firstElementChild", {
  get: function () { return this.kids[0] || null; }
});
El.prototype.appendChild = function (n) { n.parentNode = this; this.kids.push(n); return n; };
El.prototype.removeChild = function (n) {
  var i = this.kids.indexOf(n);
  if (i >= 0) { this.kids.splice(i, 1); n.parentNode = null; }
  return n;
};
El.prototype.remove = function () { if (this.parentNode) this.parentNode.removeChild(this); };
El.prototype.replaceChildren = function () {
  this.kids.forEach(function (k) { k.parentNode = null; });
  this.kids = []; this.txt = "";
  for (var i = 0; i < arguments.length; i++) this.appendChild(arguments[i]);
};
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) {
  return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null;
};
El.prototype.addEventListener = function (t, fn) { (this.on[t] = this.on[t] || []).push(fn); };
El.prototype.removeEventListener = function (t, fn) {
  var a = this.on[t] || [], i = a.indexOf(fn);
  if (i >= 0) a.splice(i, 1);
};
El.prototype.fire = function (t, ev) {
  (this.on[t] || []).slice().forEach(function (fn) { fn(ev || {}); });
};
El.prototype.click = function () { this.fire("click", { detail: 0, target: this }); };   // 키보드처럼
El.prototype.pointerClick = function () { this.fire("click", { detail: 1, target: this }); };  // 손가락처럼
El.prototype.focus = function () { DOC.activeElement = this; };
El.prototype.contains = function (n) {
  return n === this || this.kids.some(function (k) { return k.contains(n); });
};
El.prototype.getBoundingClientRect = function () {
  return { top: 0, left: 0, width: 10, height: 10, right: 10, bottom: 10 };
};
El.prototype.all = function (out) {
  out = out || [];
  this.kids.forEach(function (k) { out.push(k); k.all(out); });
  return out;
};
/* 아주 작은 선택자 매처 — 엔진이 쓰는 형태(tag · .class · tag.class · 쉼표 목록)만 본다 */
function vnrMatch(node, sel) {
  return String(sel).split(",").some(function (one) {
    var m = /^\s*([a-zA-Z]*)((?:\.[\w-]+)*)\s*$/.exec(one);
    if (!m || (!m[1] && !m[2])) return false;
    if (m[1] && node.tagName !== m[1].toUpperCase()) return false;
    return (m[2] || "").split(".").filter(Boolean)
      .every(function (c) { return node.classList.contains(c); });
  });
}
El.prototype.querySelectorAll = function (sel) {
  return this.all().filter(function (n) { return vnrMatch(n, sel); });
};
El.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };

var DOC = {
  activeElement: null, visibilityState: "visible", fullscreenElement: null, on: {},
  createElement: function (t) { return new El(t); },
  createTextNode: function (t) { var n = new El("#text"); n.textContent = t; return n; },
  getElementById: function () { return null; },
  addEventListener: function (t, fn) { (DOC.on[t] = DOC.on[t] || []).push(fn); },
  removeEventListener: function (t, fn) {
    var a = DOC.on[t] || [], i = a.indexOf(fn);
    if (i >= 0) a.splice(i, 1);
  },
  fire: function (t, ev) { (DOC.on[t] || []).slice().forEach(function (fn) { fn(ev || {}); }); }
};
DOC.documentElement = new El("html");
DOC.head = new El("head");
DOC.body = new El("body");

var STORE = {};
var WIN = {
  document: DOC,
  localStorage: {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(STORE, k) ? STORE[k] : null; },
    setItem: function (k, v) { STORE[k] = String(v); },
    removeItem: function (k) { delete STORE[k]; }
  },
  matchMedia: function () { return { matches: false }; },
  setTimeout: setTimeout, clearTimeout: clearTimeout,
  setInterval: setInterval, clearInterval: clearInterval,
  requestAnimationFrame: function (cb) { return setTimeout(cb, 0); },
  Image: function () { this.decoding = ""; this.src = ""; },
  navigator: {}
};
WIN.window = WIN;
global.window = WIN;
global.document = DOC;
"""

VNR_DRIVER = r"""
/* 재생 엔진을 실제로 굴려 본다: 호감도 장부 · 분기 폴백 · 손상된 저장 · 손짓 가드.
   마지막 줄에 JSON 한 줄만 낸다(파이썬 쪽이 그것만 읽는다). */
var OUT = {};
function vnrScenes() {
  return [
    { id: "A", order: 1, purpose: "a", img: "",
      lines: [{ n: "", c: null, t: "a1", p: "bottom" }, { n: "", c: null, t: "a2", p: "bottom" }] },
    { id: "B", order: 2, purpose: "b", img: "", lines: [{ n: "", c: null, t: "b1", p: "bottom" }],
      choices: [{ text: "up", affection: 8, goto: "C" },
                { text: "down", affection: -4, goto: "C" },
                { text: "str", affection: "5", goto: "C" }] },   // 손으로 고친 장면의 문자열 값
    { id: "C", order: 3, purpose: "c", img: "", lines: [{ n: "", c: null, t: "c1", p: "bottom" }],
      branch: [{ min: 35, goto: "D" }, { min: 0, goto: "E" }] },
    { id: "D", order: 4, purpose: "good", img: "", lines: [{ n: "", c: null, t: "d1", p: "bottom" }],
      ending: true, ending_label: "GOOD" },
    { id: "E", order: 5, purpose: "soft", img: "", lines: [{ n: "", c: null, t: "e1", p: "bottom" }],
      ending: true, ending_label: "SOFT" }
  ];
}
var VDATA = { title: "T", scenes: vnrScenes(), dating: { max: 100, start_affection: 30 }, episodes: [] };
STORE["k:settings"] = JSON.stringify({ textSpeed: 0, autoDelay: 1500, fs: 17, skipAll: false, cinema: false });
var P = WIN.VNRuntime.mount({ data: VDATA, root: DOC.body, storageKey: "k" });
var ST = DOC.body.kids[DOC.body.kids.length - 1];
function picks() { return ST.querySelector(".vnr-choices").kids; }
function affNow() {
  var m = /(-?\d+)\s*\/\s*(\d+)/.exec(ST.querySelector(".vnr-aff").textContent);
  return m ? +m[1] : null;
}
function endOpen() { return !ST.querySelector(".vnr-end").hidden; }
function endName() { return ST.querySelector(".vnr-nm").textContent; }
function body() { return ST.querySelector(".vnr-text").textContent; }
function press(k) { DOC.fire("keydown", { key: k, target: ST, preventDefault: function () {} }); }
function toChoices() { P.start(false, 1); press("ArrowRight"); }
// 처음부터 다시 시작하지 않고 **되돌아가** 같은 선택지를 다시 연다(호감도가 유지된 채로)
function reChoose() { press("ArrowLeft"); press("ArrowRight"); }
// 저장이 아예 쓰이지 않은 경우(=재생이 멈춘 경우)에도 검사가 죽지 않고 결과로 말하게 한다
// 선택지가 이미 사라졌으면(=가드가 없던 시절엔 첫 손짓이 골라 버렸다) 조용히 넘어간다
function vnrTap(i) { var b = picks()[i]; if (b) b.pointerClick(); }
function vnrPos() { try { return JSON.parse(STORE["k:pos:T"] || "{}") || {}; } catch (e) { return {}; } }

// 1. 호감도 장부 — 다시 고르면 바뀌는 것이지 쌓이는 것이 아니다
toChoices();
OUT.choicesShown = !ST.querySelector(".vnr-choices").hidden;
OUT.affStart = affNow();
picks()[0].click();
OUT.aff1 = affNow();
OUT.after1 = P.index();
reChoose(); picks()[0].click();            // 같은 선택을 한 번 더 — 쌓이면 안 된다
OUT.affRepeat = affNow();
reChoose(); picks()[1].click();            // 결정을 -4 로 바꾼다
OUT.affSwitch = affNow();
reChoose(); picks()[2].click();            // 문자열 "5" 로 바꾼다
OUT.affString = affNow();

// 2. 분기가 장부의 값으로 갈린다(양쪽 다)
toChoices(); picks()[0].click(); press("ArrowRight");
OUT.branchHigh = P.data().scenes[P.index()].id;
press("ArrowRight");
OUT.endHigh = endOpen() ? endName() : "";
toChoices(); picks()[1].click(); press("ArrowRight");
OUT.branchLow = P.data().scenes[P.index()].id;
press("ArrowRight");
OUT.endLow = endOpen() ? endName() : "";

// 3. 없는 goto·만족되는 분기 0 은 **이야기를 끝내지 않는다**(가짜 엔딩 금지)
var D2 = { title: "T", scenes: vnrScenes(), dating: VDATA.dating, episodes: [] };
D2.scenes[1].choices = [{ text: "nowhere", affection: 2, goto: "NOPE" }];
D2.scenes[2].branch = [{ min: 900, goto: "D" }];
P.setData(D2);
toChoices(); picks()[0].click();
OUT.danglingGoto = { id: P.data().scenes[P.index()].id, end: endOpen() };
press("ArrowRight");
OUT.deadBranch = { id: P.data().scenes[P.index()].id, end: endOpen() };

// 4. 손상되거나 손댄 저장 위치에서도 반드시 읽을 수 있는 화면이 남는다
P.setData(VDATA);
OUT.corrupt = [{ vi: "3", di: "1", aff: 30 }, { vi: 2.7, di: 1.3, aff: 12.5 },
               { vi: null, di: undefined, aff: "x" }, { vi: 99, di: 99, aff: 1e9 },
               { vi: -1, di: -1, aff: -50 }].map(function (bad) {
  STORE["k:pos:T"] = JSON.stringify(bad);
  P.start(true);
  var at = P.index();
  press("ArrowRight");
  return { vi: at, int: Number.isInteger(at) && at >= 0 && at < 5,
           moved: P.index() !== at || vnrPos().di > 0,
           aff: affNow(), affOk: affNow() >= 0 && affNow() <= 100, text: body() };
});
STORE["k:pos:T"] = "not json at all";
P.start(true);
OUT.junkSave = { vi: P.index(), text: body() };

// 5. 선택지를 띄운 그 손짓이 선택까지 하지 않는다(폰 탭 하나로 분기가 정해지던 자리)
toChoices();
vnrTap(0);
OUT.guardBlocks = { hidden: ST.querySelector(".vnr-choices").hidden, vi: P.index(), aff: affNow() };
setTimeout(function () {
  vnrTap(0);                                       // 가드가 풀린 뒤에는 그대로 눌린다
  OUT.guardReleases = { hidden: ST.querySelector(".vnr-choices").hidden, vi: P.index(), aff: affNow() };
  // 6. 장부는 이어보기에도 살아남는다(다시 걸어도 같은 값)
  toChoices(); picks()[0].click();
  OUT.savedPicks = vnrPos().picks || null;
  P.start(true);                           // 이어보기
  OUT.resumedAff = affNow();
  reChoose(); picks()[0].click();          // 이어본 뒤 되돌아가 같은 선택을 또 골라도
  OUT.resumedRepeat = affNow();
  console.log(JSON.stringify(OUT));
  process.exit(0);
}, 420);
"""


@test("js", "J07 재생 엔진 실행 — 호감도 장부·분기 폴백·손상된 저장 복구(브라우저 없이)")
def j07(b: Box):
    """분기 재생은 이 저장소에서 **눈으로만** 확인되던 마지막 자리였다. 그 사이에 네 가지가
    조용히 어긋나 있었다:
      · [장면]으로 되돌아가 같은 선택지를 다시 고르면 호감도가 **쌓였다**(어떤 시작값에서도
        눈금 최대까지 올려 원하는 엔딩을 열 수 있었다).
      · 선택지를 **띄운 그 손짓**이 선택까지 했다 — 폰에서는 탭 한 번으로, 엄지 위치가 분기를 정했다.
      · 없는 goto·만족되는 분기 0 이 **가짜 엔딩 카드**를 띄워 작품이 거기서 끝난 것처럼 보였다.
      · 손상된 저장 위치("3"·2.7·null)가 그대로 통과해 **아무 키도 듣지 않는 뷰어**가 됐다.
    """
    p = b.p("tools/vn_runtime.js")
    if not p.exists():
        raise Gap("tools/vn_runtime.js 아직 없음 — 공용 재생 엔진 이관 대기")
    code = "\n;\n".join([VNR_DOM_STUB, p.read_text(encoding="utf-8"), VNR_DRIVER])
    r = _node_json(b, code, "vn_engine")

    eq(r["choicesShown"], True, "장면 끝에서 선택지가 뜨지 않는다")
    eq(r["affStart"], 30, "시작 호감도가 매니페스트 눈금(start_affection)과 다름")
    eq(r["aff1"], 38, "선택지의 호감도(+8)가 반영되지 않음")
    eq(r["after1"], 2, "선택 뒤 goto 목적지로 가지 않음")
    eq(r["affRepeat"], 38,
       "되돌아가 같은 선택을 다시 골랐더니 호감도가 쌓인다 — 눈금을 채워 엔딩을 고를 수 있다")
    eq(r["affSwitch"], 26, "결정을 바꿨는데 앞 선택의 값이 남아 있다")
    eq(r["affString"], 35,
       '선택지의 affection 이 문자열 "5" 일 때 수로 더해지지 않는다(예전엔 눈금 최대로 튀었다)')
    eq(r["branchHigh"], "D", "호감도 38 인데 min 35 분기로 가지 않음")
    eq(r["branchLow"], "E", "호감도 26 인데 min 35 분기로 갔음")
    eq(r["endHigh"], "GOOD", "엔딩 카드 이름(ending_label)")
    eq(r["endLow"], "SOFT", "엔딩 카드 이름(ending_label)")
    eq(r["danglingGoto"], {"id": "C", "end": False},
       "목적지가 없는 goto 가 이야기를 끝낸다 — 작가의 오타 하나로 작품이 거기서 끝난다")
    eq(r["deadBranch"], {"id": "D", "end": False},
       "만족되는 분기가 하나도 없을 때 가짜 엔딩 카드가 뜬다")
    for i, c in enumerate(r["corrupt"]):
        ok(c["int"], f"손상된 저장 {i}: 장면 번호가 정수가 아니다 — {c}")
        ok(c["affOk"], f"손상된 저장 {i}: 호감도가 눈금을 벗어났다 — {c}")
        ok(c["moved"], f"손상된 저장 {i}: 진행 키가 듣지 않는다(빠져나올 길이 없다) — {c}")
        ok(c["text"], f"손상된 저장 {i}: 대사창이 비었다 — {c}")
    ok(r["junkSave"]["text"], f"JSON 이 아닌 저장값에서 화면이 비었다 — {r['junkSave']}")
    eq(r["guardBlocks"], {"hidden": False, "vi": 1, "aff": 30},
       "선택지를 띄운 그 손짓이 선택까지 해 버린다(폰에서 탭 한 번이면 분기가 정해진다)")
    eq(r["guardReleases"], {"hidden": True, "vi": 2, "aff": 38},
       "가드가 풀린 뒤에도 선택지를 고를 수 없다 — 화면이 먹통이 된다")
    eq(r["savedPicks"], {"B": 8}, "선택 장부가 저장되지 않아 이어보기 뒤 다시 쌓인다")
    eq(r["resumedAff"], 38, "이어보기 뒤 호감도가 어긋난다")
    eq(r["resumedRepeat"], 38, "이어보기 뒤 되돌아가 다시 고르면 호감도가 쌓인다")


_J08_HARNESS = """
let S={image:{engine:"comfyui",engines:["comfyui"],mf_token:false}};
let paidConfirm=0,apiPaths=[],apiReply={count:0,auto:"PASS"};
const scDraft=new Map();
function el(tag,cls,txt){return {tag:tag,cls:cls||"",textContent:(txt==null?"":String(txt)),
 title:"",disabled:false,hidden:false,onclick:null,rows:0,readOnly:false,value:"",
 style:{},attrs:{},kids:[],
 appendChild:function(n){this.kids.push(n);return n},
 setAttribute:function(k,v){this.attrs[k]=v},removeAttribute:function(k){delete this.attrs[k]}}}
function charName(id){return id}
function copyTo(){}
function confirm(){paidConfirm++;return true}
function refresh(){return Promise.resolve()}
function pollGen(){return function(){}}
function pollGenUntilDone(){return Promise.resolve({done:true})}
async function api(path){apiPaths.push(path);return apiReply}
function scBtnGenPrompt(){return el("button","btn","GENPROMPT")}
function scBtnGenImage(){return el("button","btn","GENIMAGE")}
function scBtnGenImageAlt(){return null}
function scAddUpload(act){act.appendChild(el("button","btn ghost","UPLOAD"))}
let played="";
function playFrom(id){played=id}
__FUNCS__
function buttons(node,out){out=out||[];
 for(const k of (node.kids||[])){
  if(k.tag==="button")out.push({t:k.textContent,d:!!k.disabled,click:!!k.onclick,title:k.title});
  buttons(k,out)}
 return out}
function scene(status,sel,prompt){return {scene_id:"SCENE-001",scene_order:1,status:status,
 purpose:"강변을 걷는다",prompt:(prompt===undefined?"anchor text":prompt),
 dialogue:[{speaker_id:"CHAR-001",text:"안녕"}],
 raw_images:["images/raw/SCENE-001/a.png","images/raw/SCENE-001/b.png"],
 selected_image:sel?"images/raw/SCENE-001/a.png":""}}
function actionsOf(status,sel){scDraft.clear();
 const r=scActions(scene(status,sel));return buttons(r.act).map(x=>x.t)}
function thumbsOf(status){scDraft.clear();
 const msg=el("span"),th=scThumbs(scene(status,true),msg);
 const bs=buttons(th);
 return {n:bs.length,disabled:bs.filter(x=>x.d).length,clickable:bs.filter(x=>x.click).length,
         hint:(th.kids.filter(k=>k.cls==="pickhint")[0]||{textContent:""}).textContent}}
function upscaleOf(tok){S.image.mf_token=tok;paidConfirm=0;
 const b=scBtnUpscale(scene("APPROVED",true),{printable:false},el("span"));
 const before={disabled:!!b.disabled,title:b.title};   // 누르면 핸들러가 스스로 잠근다
 if(b.onclick&&!b.disabled)b.onclick();
 return {disabled:before.disabled,title:before.title,confirmed:paidConfirm}}
function copyBtns(prompt){scDraft.clear();
 return buttons(scPromptBlock(scene("SCENE_PLAN",false,prompt))).map(x=>x.t)}
(async function(){
 const out={
  plan:actionsOf("SCENE_PLAN",false),image:actionsOf("IMAGE",true),
  review:actionsOf("REVIEW_HUMAN",true),approved:actionsOf("APPROVED",true),
  thApproved:thumbsOf("APPROVED"),thReview:thumbsOf("REVIEW_HUMAN"),
  upNoToken:upscaleOf(false),upToken:upscaleOf(true),
  copyWith:copyBtns("anchor text"),copyWithout:copyBtns("")};
 // 폴더 스캔: 서버가 '하지 않았다' 고 말한 사유(note)가 화면에 남고, 카드를 다시 그려도 살아남는가
 scDraft.clear();
 apiReply={count:0,auto:"-",note:"APPROVED 장면은 재스캔하지 않습니다. 되돌리려면 revise 를 사용하세요."};
 const sc=scene("APPROVED",true),msg=el("span");
 const scan=scBtnScan(sc,msg);
 await scan.onclick();
 out.scanMsg=msg.textContent;
 out.scanSurvives=scActions(sc).msg.textContent;   // 카드를 다시 그린 뒤에도 남아 있는가
 // 승인 직후: 결과 한 줄이 몇 컷째인지 말하고, [▶ 지금 보기]가 카드 재생성 뒤에도 남는가
 scDraft.clear();apiReply={};
 S.scenes=[{scene_id:"SCENE-001",status:"REVIEW_HUMAN"},{scene_id:"SCENE-002",status:"APPROVED"}];
 const apMsg=el("span");
 await scBtnApprove(scene("REVIEW_HUMAN",true),apMsg).onclick();
 out.approveMsg=apMsg.textContent;
 const after=scActions(scene("APPROVED",true));
 out.approveAgain=buttons(after.act).map(x=>x.t);
 out.approveMsgSurvives=after.msg.textContent;
 const watch=buttons(after.act).filter(x=>x.t.indexOf("지금 보기")>=0)[0];
 out.watchClickable=!!(watch&&watch.click);
 // 승인하지 않은 카드에는 붙지 않는다(서버가 아직 컷을 감상본에 싣지 않는다)
 scDraft.clear();
 out.watchOnUnapproved=buttons(scActions(scene("REVIEW_HUMAN",true)).act)
  .map(x=>x.t).filter(t=>t.indexOf("지금 보기")>=0).length;
 console.log(JSON.stringify(out));
})();
"""


VNR_BRANCH_DRIVER = r"""
/* 분기가 있는 작품에서 **화면이 사실만 말하는가**: 엔딩 카드가 세는 장면 수와,
   세로 스크롤 리딩의 갈림길·서로 배타적인 결말 표시. JSON 한 줄만 낸다. */
var OUT = {};
function vnrScenes() {
  return [
    { id: "A", order: 1, purpose: "a", img: "", lines: [{ n: "", c: null, t: "a1", p: "bottom" }] },
    { id: "B", order: 2, purpose: "b", img: "", lines: [{ n: "", c: null, t: "b1", p: "bottom" }],
      choices: [{ text: "up", affection: 8, goto: "C" }, { text: "down", affection: -4, goto: "C" }] },
    { id: "C", order: 3, purpose: "c", img: "", lines: [{ n: "", c: null, t: "c1", p: "bottom" }],
      branch: [{ min: 35, goto: "D" }, { min: 0, goto: "E" }] },
    { id: "D", order: 4, purpose: "good", img: "", lines: [{ n: "", c: null, t: "그럼 없던 걸로 해줄게", p: "bottom" }],
      ending: true, ending_label: "호감 엔딩" },
    { id: "E", order: 5, purpose: "soft", img: "", lines: [{ n: "", c: null, t: "여기서 헤어지자", p: "bottom" }],
      ending: true, ending_label: "여운 엔딩" }
  ];
}
var VDATA = { title: "T", scenes: vnrScenes(), dating: { max: 100, start_affection: 30 }, episodes: [] };
STORE["k:settings"] = JSON.stringify({ textSpeed: 0, autoDelay: 1500, fs: 17, skipAll: false, cinema: false });
var P = WIN.VNRuntime.mount({ data: VDATA, root: DOC.body, storageKey: "k" });
var ST = DOC.body.kids[DOC.body.kids.length - 1];
function picks() { return ST.querySelector(".vnr-choices").kids; }
function press(k) { DOC.fire("keydown", { key: k, target: ST, preventDefault: function () {} }); }
function endSub() { return ST.querySelector(".vnr-sub").textContent; }

// 1. 한 경로를 끝까지 걷고 엔딩 카드가 **본 장면 수**를 말하는지 본다(A·B·C·D 네 장면)
P.start(false, 0);
press("ArrowRight");            // A → B
press("ArrowRight");            // B 의 대사 끝 → 선택지
picks()[0].click();             // +8 → C
press("ArrowRight");            // C → D(호감)
press("ArrowRight");            // 엔딩 카드
OUT.walked = endSub();
OUT.total = P.data().scenes.length;

// 2. 세로 스크롤 리딩 — 갈림길과 서로 배타적인 결말에 이름표가 있는가
var box = DOC.createElement("div");
DOC.body.appendChild(box);
WIN.VNRuntime.renderScroll(VDATA, box, {});
var txt = box.textContent;
function classCount(node, cls, n) {
  n = n || 0;
  (node.kids || []).forEach(function (k) {
    if ((k.className || "").split(/\s+/).indexOf(cls) >= 0) n++;
    n = classCount(k, cls, n);
  });
  return n;
}
OUT.forks = classCount(box, "fork");
OUT.endmarks = classCount(box, "endmark");
OUT.scrollText = txt;
console.log(JSON.stringify(OUT));
"""


@test("js", "J10 분기 있는 작품 — 엔딩 카드는 본 장면만 세고, 스크롤 모드는 갈림길·결말에 이름표를 단다")
def j10(b: Box):
    """감상본이 사실이 아닌 말을 하던 두 자리.

      · 엔딩 카드가 **작품 전체 장면 수**를 "감상 완료" 라고 적었다 — 11장을 본 독자에게
        "장면 12개 감상 완료", 여운 엔딩 쪽 독자는 한 번도 못 본 장면까지 축하받았다.
      · 세로 스크롤 리딩은 분기를 모르고 전 장면을 차례로 싣는다. 선택지 셋이 전부 일어난
        일처럼 ▸ 목록으로 찍히고, 호감 엔딩의 "없던 걸로 해줄게" 바로 다음 줄에 여운 엔딩의
        "여기서 헤어지자" 가 왔다 — 세 줄 만에 작품이 스스로를 두 번 부정한다.

    고치는 방법은 둘 다 **이름표**다(재생 방식 자체는 바꾸지 않는다).
    """
    p = b.p("tools/vn_runtime.js")
    if not p.exists():
        raise Gap("tools/vn_runtime.js 아직 없음 — 공용 재생 엔진 이관 대기")
    code = "\n;\n".join([VNR_DOM_STUB, p.read_text(encoding="utf-8"), VNR_BRANCH_DRIVER])
    r = _node_json(b, code, "vn_branch")

    eq(r["total"], 5, "픽스처가 5장면이어야 이 검사가 뜻이 있다")
    hasnt(r["walked"], "5개 감상 완료",
          f"한 경로만 걸었는데 전체 장면 수를 '감상 완료' 라고 말한다 — {r['walked']!r}")
    has(r["walked"], "4", f"이 경로에서 본 장면 수(4)가 엔딩 카드에 없다 — {r['walked']!r}")
    has(r["walked"], "5", f"전체 장면 수(5)를 함께 보여 주지 않는다 — {r['walked']!r}")

    eq(r["forks"], 1, "스크롤 모드의 선택지 목록에 '여기서 갈립니다' 이름표가 없다")
    eq(r["endmarks"], 2, "스크롤 모드의 엔딩 둘에 이름표가 없다(서로 배타적인 결말이 붙어 나온다)")
    for label in ("호감 엔딩", "여운 엔딩", "갈립니다"):
        has(r["scrollText"], label, f"스크롤 모드 본문에 {label!r} 이름표가 없다")
    idx_good = r["scrollText"].index("호감 엔딩")
    idx_soft = r["scrollText"].index("여운 엔딩")
    ok(idx_good < r["scrollText"].index("그럼 없던 걸로 해줄게") < idx_soft,
       "엔딩 이름표가 그 엔딩의 대사보다 뒤에 온다 — 독자는 이미 다 읽은 뒤에야 알게 된다")


@test("js", "J08 장면 카드 — 거절될 일을 권하지 않고, 결과 한 줄과 [▶ 지금 보기]가 재생성보다 오래 산다")
def j08(b: Box):
    """화면이 사실과 다른 말을 하던 자리들의 잠금장치(브라우저 없이 함수를 실제로 굴린다).

      · 승인 도장이 **APPROVED 카드에도** 붙어 있었다 — 서버는 REVIEW_HUMAN 에서만 승인한다.
      · 승인된 컷의 후보 썸네일 47개가 전부 눌리는 버튼이었고, 거절 문구는 폰에서 실행할 수
        없는 셸 명령이었다.
      · 유료 [⬆ 인화용 업스케일]이 토큰 없이도 과금 확인창을 띄우고 나서 실패했다
        (보조 생성 버튼은 이미 같은 가드를 갖고 있었다 — J05).
      · 프롬프트가 없는 장면의 [프롬프트 복사]가 **빈 문자열**을 복사하고 "복사됨 ✓" 라고 했다.
      · 성공 문구가 만들어진 지 0.2초 만에 refresh 로 덮여 사라졌다 — 폰에서도 화면 낭독에서도
        '아무 일도 없었던 것' 과 구분되지 않았다. 서버가 보낸 '하지 않은 이유'(note)도 버려졌다.
    """
    src = b.p("tools/studio.js")
    if not src.exists():
        raise Gap("tools/studio.js 아직 없음 — 스튜디오 스크립트 분리 대기")
    funcs = _js_funcs(src.read_text(encoding="utf-8"),
                      "mfToken", "draftOf", "say", "scPromptBlock", "scBtnScan",
                      "scBtnApprove", "scBtnUpscale", "scActions", "scThumbs")
    r = _node_json(b, _J08_HARNESS.replace("__FUNCS__", funcs), "studio_card")

    # 승인 뒤의 다음 한 걸음이 '감상' 이어야 한다. 예전에는 "갤러리에 모입니다" 라고만
    # 말했고, 방금 만든 컷을 보려면 탭을 건너가 ▶ 를 찾아야 했다(폰에서 두 탭 더).
    has(r["approveMsg"], "승인됨", "승인 결과 한 줄이 없다")
    has(r["approveMsg"], "2/2", f"승인 결과가 몇 컷째인지 말하지 않는다 — {r['approveMsg']}")
    ok(any("지금 보기" in t for t in r["approveAgain"]),
       f"승인 직후 카드에서 바로 볼 수 없다(갤러리 탭까지 건너가야 한다) — {r['approveAgain']}")
    ok(r["watchClickable"], "[▶ 지금 보기] 가 눌리지 않는다")
    eq(r["approveMsgSurvives"], r["approveMsg"], "승인 문구가 카드 재생성에서 사라진다")
    eq(r["watchOnUnapproved"], 0, "아직 승인하지 않은 컷에도 [▶ 지금 보기] 가 붙는다")

    seal = "승인 도장 찍기"
    ok(seal in r["review"], f"시사 단계인데 승인 도장이 없다 — {r['review']}")
    for st in ("plan", "image", "approved"):
        ok(seal not in r[st], f"{st} 단계에 승인 도장이 붙는다(서버가 거절할 버튼) — {r[st]}")

    th_a, th_r = r["thApproved"], r["thReview"]
    eq((th_a["n"], th_a["disabled"], th_a["clickable"]), (2, 2, 0),
       f"승인된 컷의 후보 썸네일이 아직 눌린다(서버는 revise 를 요구한다) — {th_a}")
    has(th_a["hint"], "revise", "왜 고를 수 없는지 카드가 말하지 않음")
    eq((th_r["n"], th_r["disabled"], th_r["clickable"]), (2, 0, 2),
       f"고를 수 있어야 하는 단계에서 썸네일이 막혔다 — {th_r}")

    no, yes = r["upNoToken"], r["upToken"]
    ok(no["disabled"], f"토큰이 없는데 유료 업스케일이 눌린다 — {no}")
    eq(no["confirmed"], 0, f"토큰 없이 과금 확인창을 띄운다 — {no}")
    has(no["title"], "MAKEFUN_API_TOKEN", "왜 눌리지 않는지 말하지 않음")
    ok(not yes["disabled"], f"토큰이 있는데 업스케일이 막혔다 — {yes}")
    eq(yes["confirmed"], 1, f"유료 작업인데 확인을 묻지 않는다 — {yes}")

    copy = "프롬프트 복사"
    ok(copy in r["copyWith"], f"프롬프트가 있는데 복사 버튼이 없다 — {r['copyWith']}")
    ok(copy not in r["copyWithout"],
       f"프롬프트가 없는 장면에서 빈 문자열을 복사하고 성공이라 말한다 — {r['copyWithout']}")

    has(r["scanMsg"], "revise", f"서버가 보낸 '하지 않은 이유' 를 버렸다 — {r['scanMsg']!r}")
    eq(r["scanSurvives"], r["scanMsg"],
       "결과 한 줄이 카드 재생성에서 사라진다(성공이 '아무 일 없음' 으로 보인다)")


_J09_HARNESS = """
const TAB_KEY="vn:studio:tab";
let curTab="",scStale=false,galStale=false,vwStale=false,S={};
let nScenes=0,nGallery=0,nAlbum=0,partial=false;
const localStorage={setItem:function(){},getItem:function(){return ""}};
const stub={value:"",open:false,src:"",style:{},
 classList:{add:function(){},remove:function(){},toggle:function(){}}};
function $(){return stub}
const document={querySelectorAll:function(){return []}};
function el(){return stub}
function api(){return Promise.resolve({scenes:[],chat:[]})}
function renderChips(){}
function syncFav(){}
function syncResume(){}
function renderChat(){}
function renderLan(){}
function renderDl(){}
function talkStatus(){}
function loadChatHistory(){}
function setHash(){}
function renderScene(){return partial}
function renderScenes(){nScenes++}
function renderGallery(){nGallery++}
function renderAlbum(){nAlbum++}
__FUNCS__
function count(){return {scenes:nScenes,gallery:nGallery}}
function zero(){nScenes=0;nGallery=0;nAlbum=0}
(async function(){
 const out={};
 curTab="viewer";zero();await refresh();out.hiddenRefresh=count();
 zero();selectTab("scenes");out.enterScenes=count();
 zero();selectTab("scenes");out.enterAgain=count();
 curTab="scenes";zero();await refresh();out.visibleRefresh=count();
 curTab="gallery";zero();await refresh();out.galleryRefresh=count();
 curTab="viewer";partial=true;zero();await refresh({scene:"SCENE-001"});
 out.partialHidden=count();
 zero();selectTab("scenes");out.partialThenEnter=count();
 // 감상 탭 머리말도 같은 규칙을 지켜야 한다 — 표지 썸네일은 보이지 않는 탭에 붙지 않는다.
 curTab="scenes";zero();await refresh();out.albumHidden=nAlbum;
 zero();selectTab("viewer");out.albumEnter=nAlbum;
 zero();selectTab("viewer");out.albumAgain=nAlbum;
 curTab="viewer";zero();await refresh();out.albumVisible=nAlbum;
 out.sized=[imgSized("/img/raw/S/a.png",1000),imgSized("/img/raw/S/a.png?w=224",1000)];
 stub.src="";vnSetCG("/img/raw/S/cg.png");out.cg=stub.src;
 console.log(JSON.stringify(out));
})();
"""


_J12_HARNESS = """
const nodes={};
function node(id){if(!nodes[id])nodes[id]={id:id,textContent:"",className:"",hidden:false};
 return nodes[id]}
function $(id){return node(id)}
function imageChip(){}
let llmUp=null,S={title:"작품"};
__FUNCS__
function snap(){return {chip:node("chipLLM").textContent,cls:node("chipLLM").className,
 story:node("storyNotice").hidden?"":node("storyNotice").textContent,
 compose:node("composeNotice").hidden?"":node("composeNotice").textContent}}
const out={};
renderChips();out.unknown=snap();
llmUp=true;renderChips();out.up=snap();
llmUp=false;renderChips();out.down=snap();
console.log(JSON.stringify(out));
"""


@test("js", "J12 로컬 LLM 이 꺼지면 그것을 필요로 하는 화면이 각자 말하고 대신 쓸 길을 준다")
def j12(b: Box):
    """오늘 이 저장소의 로컬 LLM 은 꺼져 있다. 그 상태에서 [전송]·[장면 구성]·[프롬프트 생성]은
    전부 실패하는데, 예전에는 그것을 머리말 칩 하나만 알고 있었다 — 폰에서는 칩이 접히거나
    스크롤 위로 사라져 사용자는 버튼부터 누르고 2초 뒤에 배운다.

    화면이 **스스로** 말해야 하고, 말할 때는 대신 쓸 길의 **이름**을 줘야 한다. 그리고
    '모른다'(probe 전, llmUp=null)일 때는 단정하지 않는다 — 꺼졌다고 겁주는 쪽도 틀렸다.
    """
    src = b.p("tools/studio.js")
    if not src.exists():
        raise Gap("tools/studio.js 아직 없음")
    r = _node_json(b, _J12_HARNESS.replace("__FUNCS__", _js_funcs(src.read_text(encoding="utf-8"),
                                                                 "renderChips")), "studio_llmoff")
    down, up, unk = r["down"], r["up"], r["unknown"]
    has(down["chip"], "꺼짐", "칩이 꺼짐을 말하지 않는다")
    has(down["chip"], "직접 입력", "칩이 대신 쓸 길을 말하지 않는다")
    has(down["cls"], "bad", "꺼진 칩이 붉지 않다")
    for where, txt in (("스토리", down["story"]), ("장면", down["compose"])):
        ok(txt.strip(), f"{where} 화면이 LLM 꺼짐을 스스로 말하지 않는다(칩 하나에만 의존)")
        ok("직접 입력" in txt or "프롬프트 틀" in txt,
           f"{where} 화면이 대신 쓸 길의 이름을 주지 않는다 — {txt[:80]}")
    eq((up["story"], up["compose"]), ("", ""), "LLM 이 살아 있는데 경고가 떠 있다")
    eq((unk["story"], unk["compose"]), ("", ""), "아직 모르는 동안 꺼졌다고 단정한다")
    for k in ("chip", "story", "compose"):
        for bad in ("그록", "Grok", "grok.com"):
            hasnt(down[k], bad, f"은퇴한 공급자 이름이 {k} 에 남아 있다")


_J13_HARNESS = """
const box={children:[]};
let curTab="story",scStale=false,galStale=false,vwStale=false,S={};
let chatLoaded=false,stateResolve=null;   // studio.js 의 모듈 수준 상태(함수만 떼어 오므로 여기 둔다)
const localStorage={setItem:function(){},getItem:function(){return ""}};
const stub={value:"",open:false,src:"",style:{},textContent:"",
 classList:{add:function(){},remove:function(){},toggle:function(){}}};
function $(id){return id==="chatlog"?boxEl:stub}
const boxEl={replaceChildren:function(){box.children=[]},
 appendChild:function(m){box.children.push(m)},scrollTop:0,scrollHeight:0};
const document={querySelectorAll:function(){return []}};
function el(_t,_c,text){return text}
function renderChips(){}
function syncFav(){}
function syncResume(){}
function renderLan(){}
function renderScene(){return false}
function renderScenes(){}
function renderGallery(){}
function renderAlbum(){}
// /api/state 는 우리가 언제 답할지 정한다 — 경주(둘이 동시에 나가는 첫 화면)를 만들기 위해.
function api(path){
 if(path==="/api/state")return new Promise(function(r){stateResolve=function(){r({storyline:""})}});
 if(path==="/api/chat-history")return Promise.resolve({messages:[{role:"user",content:"지난 질문"},
  {role:"assistant",content:"지난 답변"}]});
 return Promise.resolve({})}
__FUNCS__
(async function(){
 const out={};
 const spin=refresh();                 // 첫 화면: refresh 와 loadChatHistory 가 같이 나간다
 await loadChatHistory();              // 챗 이력이 먼저 돌아온다(실측 5/5 이 순서였다)
 out.afterHistory=box.children.length;
 stateResolve();                       // 그 다음에 /api/state 가 돌아온다
 await spin;
 out.afterState=box.children.length;
 out.kept=(S.chat||[]).length;
 console.log(JSON.stringify(out));
})();
"""


@test("js", "J13 지난 스토리 대화 — 첫 화면의 두 요청이 겹쳐도 챗로그가 비지 않는다")
def j13(b: Box):
    """서버에는 대화가 6줄 남아 있는데 새로고침하면 스토리 탭이 **매번 빈 화면**이었다.

    첫 화면에서 ``loadChatHistory()`` 와 ``refresh()`` 가 동시에 나간다. refresh 는 S 를
    통째로 갈아 끼우므로 챗로그를 되살려야 하는데, 되살릴 값을 ``await`` **앞에서** 떠
    놨다(그때는 빈 배열이다). 챗 이력이 먼저 돌아오면 그 사이 채워진 대화가 빈 배열로
    덮인다 — 그리고 ``chatLoaded`` 는 이미 true 라 다시 받아오지도 않는다. 실측에서
    /api/chat-history 가 /api/state 보다 항상 먼저 돌아와 5/5 재현됐다.
    """
    src = b.p("tools/studio.js")
    if not src.exists():
        raise Gap("tools/studio.js 아직 없음")
    funcs = _js_funcs(src.read_text(encoding="utf-8"),
                      "refresh", "renderChat", "loadChatHistory")
    r = _node_json(b, _J13_HARNESS.replace("__FUNCS__", funcs), "studio_chatrace")
    eq(r["afterHistory"], 2, "지난 대화를 받아도 화면에 그리지 않는다")
    eq(r["afterState"], 2,
       "/api/state 응답이 방금 불러온 지난 대화를 지웠다 — 새로고침마다 스토리 챗이 빈 화면이 된다")
    eq(r["kept"], 2, "S.chat 이 빈 배열로 덮였다(다음 전송이 맥락 없이 나간다)")


@test("js", "J09 폰 데이터 — 보이지 않는 탭은 그리지 않고, 이미지는 보이는 크기만큼만 받는다")
def j09(b: Box):
    """폰 실측에서 **행동 한 번에 82.5MB** 가 흘렀다. 원인은 둘이었고 둘 다 화면에 보이지 않았다:

      · `refresh()` 가 display:none 인 장면·갤러리 탭까지 다시 그렸다 — 숨은 <img> 도 브라우저는
        내려받는다. 첫 승인 한 번에 보이지도 않는 썸네일 61장이 따라왔다.
      · 대화 배경 CG·백로그 사진·라이트박스가 **원본 PNG**(장당 1.3MB)를 요청했다. 서버는
        `?w=` 로 줄여 줄 수 있고 썸네일은 이미 그렇게 받고 있었다.

    두 번째를 고쳐도 첫 번째가 남으면 숨은 탭이 계속 따라오고, 반대도 마찬가지다 — 둘 다 잠근다.
    """
    src = b.p("tools/studio.js")
    if not src.exists():
        raise Gap("tools/studio.js 아직 없음 — 스튜디오 스크립트 분리 대기")
    funcs = _js_funcs(src.read_text(encoding="utf-8"),
                      "hasQuery", "imgSized", "vnSetCG", "refresh", "selectTab")
    r = _node_json(b, _J09_HARNESS.replace("__FUNCS__", funcs), "studio_bytes")

    eq(r["hiddenRefresh"], {"scenes": 0, "gallery": 0},
       "보이지 않는 탭을 refresh 가 다시 그린다(숨은 썸네일 82.5MB 가 폰으로 흐른다)")
    eq(r["partialHidden"], {"scenes": 0, "gallery": 0},
       "카드 하나만 고치는 경로에서도 숨은 갤러리를 다시 그린다")
    eq(r["enterScenes"], {"scenes": 1, "gallery": 0},
       "탭에 들어왔는데 뒤처진 목록을 갚지 않는다(빈 화면이 된다)")
    eq(r["enterAgain"], {"scenes": 0, "gallery": 0},
       "이미 최신인 탭을 다시 들어올 때마다 통째로 다시 그린다")
    eq(r["partialThenEnter"], {"scenes": 1, "gallery": 0},
       "숨은 동안 부분 갱신만 받은 목록이 뒤처진 채로 남는다")
    eq(r["visibleRefresh"], {"scenes": 1, "gallery": 0},
       "보이는 탭을 refresh 가 그리지 않는다(화면이 멈춘다)")
    eq(r["galleryRefresh"], {"scenes": 0, "gallery": 1},
       "갤러리 탭에서 갤러리가 갱신되지 않는다")

    # 감상 탭 머리말(표지 썸네일 1장)도 같은 규칙 위에 있다 — 규칙이 하나만 있어야
    # 다음 화면을 붙이는 사람이 어느 쪽을 본떠야 할지 헷갈리지 않는다.
    eq(r["albumHidden"], 0, "보이지 않는 감상 탭의 표지를 refresh 가 받아 온다")
    eq(r["albumEnter"], 1, "감상 탭에 들어왔는데 뒤처진 머리말을 갚지 않는다(빈 표지가 남는다)")
    eq(r["albumAgain"], 0, "이미 최신인 감상 탭을 들어올 때마다 표지를 다시 받는다")
    eq(r["albumVisible"], 1, "보이는 감상 탭에서 승인·내보내기 뒤에도 머리말이 그대로다")

    eq(r["sized"], ["/img/raw/S/a.png?w=1000", "/img/raw/S/a.png?w=224"],
       "축소본 요청 규칙이 깨졌다(원본을 받거나 부르는 쪽이 정한 폭을 덮어쓴다)")
    has(r["cg"], "?w=", "대화 배경 CG 가 원본(1.3MB)을 그대로 받는다")

# ============================================================ ux (폰 손짓 · 가독성)
# 화면에서만 드러나는 회귀도 소스로 잠글 수 있는 것들이 있다: 손짓 리스너가 어디 붙었는지,
# 글자색이 배경과 몇 대 몇인지. 둘 다 "폰에서 써 보면 아는" 종류라 자동 검사가 없으면
# 조용히 되돌아간다(실제로 스와이프가 대사창 위에서 죽어 있던 자리다).
_CSS_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_CSS_VAR = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+)")
_CSS_COLOR = re.compile(r"(?<![-\w])color\s*:\s*var\(\s*(--[\w-]+)")
_CSS_BG = re.compile(r"(?<![-\w])background(?:-color)?\s*:[^;]*?(var\(\s*--[\w-]+|#[0-9a-fA-F]{3,8})")


def css_tokens(css: str) -> dict[str, str]:
    """:root 에 선언된 CSS 변수 {이름: 값}."""
    out: dict[str, str] = {}
    for m in re.finditer(r":root\s*\{([^}]*)\}", css, re.S):
        for name, val in _CSS_VAR.findall(m.group(1)):
            out[name] = val.strip()
    return out


def css_hex(name: str, tokens: dict[str, str], depth: int = 0) -> str:
    """토큰 이름 → #rrggbb (한 단계 var() 참조도 따라간다). 색이 아니면 ""."""
    val = (name if name.startswith("#") else tokens.get(name, "")).strip()
    m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,[^)]*)?\)", val)
    if m and depth < 4:
        return css_hex(m.group(1), tokens, depth + 1)
    return val if re.fullmatch(r"#[0-9a-fA-F]{3,8}", val) else ""


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 명도 대비(1~21). 본문 글자는 4.5:1 이상이어야 읽힌다."""
    def lum(h: str) -> float:
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        ch = []
        for i in (0, 2, 4):
            c = int(h[i:i + 2], 16) / 255
            ch.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    a, c = lum(fg), lum(bg)
    return (max(a, c) + 0.05) / (min(a, c) + 0.05)


def swipe_targets(src: str) -> set[str]:
    """touchend 리스너가 **실제로 붙는 요소** 이름들.

    `E.click.addEventListener("touchend", …)` 같은 직접 형태와,
    `[E.click, E.dlg].forEach(function (n) { n.addEventListener("touchend", …) })` 처럼
    묶어 다는 형태를 모두 편다 — 뒤 형태를 못 읽으면 "n" 하나만 보고 통과해 버린다.
    """
    out: set[str] = set()
    for m in re.finditer(r"([\w.$]+)\s*\.addEventListener\(\s*[\"']touchend[\"']", src):
        recv = m.group(1)
        if "." in recv or recv in ("document", "window"):
            out.add(recv)
            continue
        head = src[max(0, m.start() - 500):m.start()]          # 반복 변수 → 묶음의 원소들
        loop = None
        for arr in re.finditer(r"\[([^\][]*)\]\s*\.forEach", head):
            loop = arr
        if loop:
            out |= {x.strip() for x in loop.group(1).split(",") if x.strip()}
        else:
            out.add(recv)
    return out


@test("ux", "X01 스와이프가 대사창 위에서도 먹는다(엄지가 놓이는 자리는 거의 항상 대사창)")
def x01(b: Box):
    """대사창(.vnr-dlg)은 클릭판(.vnr-click) 위에 떠 있다. 손짓 리스너를 클릭판에만 달면
    **화면 아래 절반에서 시작한 스와이프가 전부 '탭'으로 처리돼 앞으로만 넘어간다** —
    되돌아가려고 오른쪽으로 쓸면 한 장 더 나가는, 폰에서만 드러나는 회귀다."""
    p = b.p("tools/vn_runtime.js")
    if not p.exists():
        raise Gap("tools/vn_runtime.js 아직 없음 — 공용 재생 엔진 이관 대기")
    src = p.read_text(encoding="utf-8")
    targets = swipe_targets(src)
    ok(targets, "touchend 리스너가 하나도 없음 — 폰 스와이프가 통째로 죽었다")
    ok(re.search(r"addEventListener\(\s*[\"']touchstart[\"']", src),
       "touchend 만 있고 touchstart 가 없음 — 손짓의 시작 좌표가 없다")
    if not (targets & {"E.dlg", "E.stage", "E.root", "E.wrap", "document", "window"}):
        raise Gap("스와이프(touchend)가 " + ", ".join(sorted(targets)) + " 에만 걸려 있다 — "
                  "대사창(E.dlg)이 클릭판을 덮고 있어 화면 아래에서 시작한 스와이프가 먹지 않는다")
    has(src, "swallowClick", "스와이프 뒤따라 오는 click 을 억제하지 않음(한 번에 두 장 넘어간다)")
    ok(re.search(r"a?dx\s*>\s*a?dy|Math\.abs\(dy\)", src),
       "가로·세로 성분을 비교하지 않음 — 대사 스크롤이 장면 넘김으로 오인된다")


@test("ux", "X02 글자색 대비 — 스튜디오의 모든 텍스트 색이 배경과 4.5:1 이상")
def x02(b: Box):
    """도장 빨강(--seal)은 테두리로는 훌륭하지만 어두운 배경 위 **글자로는 3.2:1** 이라
    작은 배지·스탬프에서 읽기 어렵다. 텍스트에는 대비를 통과하는 변형(--seal-ink)을 쓴다.

    규칙 블록마다 그 블록이 선언한 배경을 기준으로 재고, 배경 선언이 없으면 페이지 바탕을
    쓴다. 색 토큰을 손보다 대비가 무너지면 여기서 바로 걸린다.
    """
    css = b.p("tools/studio.html").read_text(encoding="utf-8")
    js = b.p("tools/studio.js").read_text(encoding="utf-8") if b.p("tools/studio.js").exists() else ""
    tokens = css_tokens(css)
    for need in ("--bg", "--ink"):
        ok(need in tokens, f"{need} 토큰이 없음 — 색 체계가 바뀌었다면 이 검사도 함께 고칠 것")
    ok(contrast_ratio(css_hex("--ink", tokens), css_hex("--bg", tokens)) >= 7.0,
       "본문 글자(--ink)와 바탕(--bg)의 대비가 무너짐")     # 판독기 자체의 자기검증

    plain = re.sub(r"/\*.*?\*/", " ", css + "\n" + js, flags=re.S)
    weak: dict[str, str] = {}
    checked = 0
    for sel, body in _CSS_BLOCK.findall(plain):
        bg = _CSS_BG.search(body)
        ground = "--bg"
        if bg:
            tok = bg.group(1)
            ground = re.search(r"--[\w-]+", tok).group(0) if tok.startswith("var(") else tok
        gh = css_hex(ground, tokens)
        for name in _CSS_COLOR.findall(body):
            fh = css_hex(name, tokens)
            if not fh or not gh:                 # rgba()·gradient 등은 판정하지 않는다
                continue
            checked += 1
            ratio = contrast_ratio(fh, gh)
            if ratio < 4.5:
                weak[name] = (f"{ratio:.2f}:1  {name} on {ground}"
                              f"  ({' '.join(sel.split())[-40:]})")
    ok(checked >= 10, f"검사한 글자색 규칙이 {checked}개뿐 — 판독기가 CSS 를 못 읽고 있다")
    pending = {n for n in weak if n == "--seal"}   # 텍스트용 변형(--seal-ink)이 오면 사라진다
    eq(sorted(weak[n] for n in weak if n not in pending), [], "글자색 대비 4.5:1 미달")
    if pending:
        raise Gap("도장색을 글자에 그대로 쓰는 자리가 남아 있다 — "
                  + " / ".join(weak[n] for n in sorted(pending))
                  + " (텍스트용 대비 변형 도착 대기)")


# ============================================================ 보안
def drain_request(handler) -> None:
    """모의 서버가 요청 본문을 끝까지 읽게 한다.

    읽지 않고 응답해 버리면 클라이언트가 본문을 쓰는 도중에 연결이 끊겨(Windows 에서
    WinError 10053) 검사가 의도한 경로(302 차단·비JSON 응답) 대신 소켓 오류로 흔들린다.
    """
    with contextlib.suppress(Exception):
        n = int(handler.headers.get("Content-Length") or 0)
        if n:
            handler.rfile.read(n)


@test("security", "S01 A8 — 심어 둔 키 패턴을 검사기가 검출")
def s01(b: Box):
    fake = "xai-" + "abcdefghij0123456789" + "KLMN"     # 런타임 조립(이 파일 자체가 걸리지 않게)
    with replaced_text(b.p("project/leak.md"), f"memo: {fake}"):
        rc, out = b.checker()
    eq(rc, 1, "exit code")
    has(out, "[A8] FAIL", "키 검출")
    rc2, _ = b.checker()
    eq(rc2, 0, "픽스처 정리 후 GREEN")


@test("security", "S04 secret_scan — 심은 키를 잡고 원문은 출력하지 않는다(마스킹)")
def s04(b: Box):
    ss = b.mod("secret_scan")
    planted = "xai-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
    hits = ss.scan_text(f'KEY = "{planted}"')
    ok(len(hits) >= 1, "탐지 실패")
    rendered = json.dumps(hits, ensure_ascii=False, default=str)
    hasnt(rendered, planted, "원문 노출")


def gitignored(rel: str, patterns: list[str]) -> bool:
    """.gitignore 규칙 중 하나라도 이 경로를 제외하는가(뒤에 오는 규칙이 이긴다).

    git 의 전체 문법을 흉내 내지 않는다 — 이 저장소가 실제로 쓰는 형태
    (`logs/`, `project/story/talk_*.json`, `*.key`, `!scratch/.gitkeep`)만 판정한다.
    """
    hit = False
    name = rel.rsplit("/", 1)[-1]
    dirs = rel.split("/")[:-1]
    for raw in patterns:
        neg = raw.startswith("!")
        pat = raw.lstrip("!").rstrip("/")
        anchored = pat.startswith("/")
        pat = pat.lstrip("/")
        if not pat:
            continue
        if "/" in pat:                       # 경로를 가진 규칙은 저장소 뿌리에서 맞춘다
            match = fnmatch.fnmatch(rel, pat) or rel.startswith(pat + "/")
        elif anchored:                       # '/name' — 뿌리의 그 항목(과 그 아래)만
            match = fnmatch.fnmatch(rel.split("/")[0], pat)
        else:                                # 이름만 있는 규칙은 어느 깊이에서나 맞는다
            match = fnmatch.fnmatch(name, pat) or any(fnmatch.fnmatch(d, pat) for d in dirs)
        if match:
            hit = not neg
    return hit


@test("security", "S05 사적 대화·아카이브가 .gitignore 를 빠져나가지 않는다")
def s05(b: Box):
    """인물과 나눈 대화는 이 저장소에서 가장 사적인 파일이다. 상한을 넘겨 옮겨 담는
    아카이브는 확장자가 .jsonl 이라 talk_*.json 규칙에 **걸리지 않는다** — 규칙이 한 줄
    빠지면 `git add .` 한 번으로 전부 커밋된다. 파일명 규칙은 talk_store 가 정하므로
    여기서도 talk_store 에게 물어본다(규칙이 바뀌면 검사도 따라간다)."""
    ts = b.mod("talk_store")
    patterns = [l.strip() for l in b.p(".gitignore").read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.strip().startswith("#")]
    private = [ts.archive_path(ts.talk_path("CHAR-001")), ts.talk_path("CHAR-001"),
               ts.story_chat_path(), ts.STORY_DIR / "memory_CHAR-001.json"]
    naked = []
    for p in private:
        rel = Path(p).resolve().relative_to(b.root.resolve()).as_posix()
        if not gitignored(rel, patterns):
            naked.append(rel)
    eq(naked, [], "저장소에 실릴 수 있는 사적 파일")
    # 규칙이 지나치게 넓어 작품 데이터까지 삼키지는 않는지(반대 방향 회귀)
    for keep in ("project/manifest.json", "project/scenes/SCENE-001.json", "tools/webapp.py"):
        ok(not gitignored(keep, patterns), f"{keep} 까지 git 에서 빠짐")


# ============================================================ 단위(순수 함수)
@test("unit", "U01 scene_ops — APPROVED 장면은 어떤 쓰기 경로로도 바뀌지 않는다")
def u01(b: Box):
    so = b.mod("scene_ops")
    # 예외 클래스는 모듈이 실제로 쓰는 것을 그대로 쓴다(같은 파일을 두 번 적재하면
    # 이름이 같아도 다른 클래스가 되므로, 여기서 새로 import 하면 안 된다).
    err = getattr(so, "VNError", RuntimeError)
    with cli_scene(b, "APPROVED") as sid:
        before = b.scene(sid)
        raises(lambda: so.set_prompt(sid, "몰래 바꾸기"), err, "set_prompt")
        raises(lambda: so.select_image(sid, before["assets"]["raw_images"][-1]),
               err, "select_image")
        write_png(b.root / "images" / "raw" / sid / "extra.png", 1400, 1000)
        raises(lambda: so.register_images(sid), err, "register_images(후보 변경)")
        after = b.scene(sid)
        eq(after["status"], "APPROVED", "status")
        eq(after["prompt"]["grok_output"], before["prompt"]["grok_output"], "프롬프트")
        eq(after["assets"]["selected_image"], before["assets"]["selected_image"], "선택본")


@test("unit", "U02 대화 로그 병합 — 저장본은 절대 짧아지지 않는다")
def u02(b: Box):
    ts = b.mod("talk_store")
    merge = ts.merge_messages          # 병합의 단일 출처(webapp·local_llm 이 함께 쓴다)
    saved = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(20)]
    fresh = merge(saved, [{"role": "user", "content": "새 세션 첫 마디"}])
    cont = merge(saved, saved + [{"role": "user", "content": "이어서"}])
    empty = merge(saved, [])
    eq(len(fresh), 21, "빈 화면에서 보낸 요청이 지난 대화를 지움")
    eq(fresh[:20], saved, "앞부분 보존")
    eq(len(cont), 21, "이어쓰기")
    eq(cont[:20], saved, "이어쓰기 앞부분")
    ok(len(empty) >= 20, "빈 목록 요청이 저장본을 지움")


@test("unit", "U03 로컬 LLM — 서버가 꺼져 있으면 status.up=False + 페르소나 생성")
def u03(b: Box):
    llm = b.mod("local_llm")
    pb = b.mod("prompt_build")
    with env_var("LOCAL_LLM_URL", "http://127.0.0.1:59999/v1"):   # 죽은 포트
        st = llm.status()
        sysmsg, meta = pb.persona_prompt()    # 서버가 없어도 페르소나 조립은 성립해야 한다
    eq(st.get("up"), False, "서버 off 판정")
    ok(isinstance(sysmsg, str) and sysmsg.strip(), "시스템 메시지")
    ok(bool(meta.get("name")), "인물 이름")
    has(sysmsg, meta["name"], "페르소나에 이름 반영")


@test("unit", "U04 앨범 사진 — 태그 파싱 · '없다' 억제 · 키워드 폴백 · 요청 아님")
def u04(b: Box):
    pb = b.mod("prompt_build")          # 사진 규칙도 프롬프트 계층 소관이다
    album = {"SCENE-001": {"rel": "images/raw/SCENE-001/a.png", "label": "카페에서 만나는 장면"},
             "SCENE-005": {"rel": "images/raw/SCENE-005/a.png", "label": "노을 강변 산책"}}
    c1, p1 = pb.resolve_photos("이거 봐~ [사진:SCENE-005]", album, "노을 사진 보여줘")
    ok(p1 and p1[0]["scene_id"] == "SCENE-005", "태그 파싱")
    hasnt(c1, "사진:", "태그가 본문에 남음")
    _c2, p2 = pb.resolve_photos("그 사진은 지금 없네~", album, "수영복 사진 보여줘")
    eq(len(p2), 0, "'없다' 응답인데 사진을 붙임")
    _c3, p3 = pb.resolve_photos("응 좋았지!", album, "카페에서 찍은 사진 보여줘")
    ok(p3 and p3[0]["scene_id"] == "SCENE-001", "키워드 폴백")
    _c4, p4 = pb.resolve_photos("오늘 날씨 좋다", album, "그냥 잡담")
    eq(len(p4), 0, "요청이 아닌데 사진을 붙임")


@test("unit", "U05 vn_core — 경로 탈출 차단 · scene_id 형식 · 원자적 쓰기(찌꺼기 없음)")
def u05(b: Box):
    """저장소 전체의 보안·형식 관문. /img·/studio·백업 복원이 전부 여기에 의존한다."""
    vc = b.mod("vn_core")
    base = b.root / "images"
    for bad in ("../etc", "/etc/passwd", "C:/evil.txt", "raw/../../CLAUDE.md",
                ".git/config", "", "..\\evil", "//server/share/x"):
        raises(lambda bad=bad: vc.safe_path(base, bad), vc.VNError, f"통과됨: {bad!r}")
    good = vc.safe_path(base, "raw/SCENE-001/a.png")
    ok(good.is_relative_to(base.resolve()), f"기준 밖으로 해석됨: {good}")
    eq(vc.safe_path(base, ".cache/x.jpg", allow_hidden=True).name, "x.jpg", "허용된 숨김 경로")
    for sid, want in (("SCENE-001", True), ("SCENE-0001", True), ("SCENE-1", False),
                      ("scene-001", False), ("SCENE-001/../x", False), ("", False),
                      (None, False), ("SCENE-abc", False)):
        eq(vc.is_scene_id(sid), want, f"is_scene_id({sid!r})")
    eq(vc.safe_slug("../../etc"), "etc", "safe_slug 가 점·구분자를 남김")
    p = b.root / "_u05_atomic.json"
    vc.atomic_write_json(p, {"a": "한글", "b": [1, 2]})
    eq(read_json(p), {"a": "한글", "b": [1, 2]}, "원자적 쓰기 왕복")
    leftovers = [q.name for q in p.parent.glob("_u05_atomic.json.*")]
    p.unlink(missing_ok=True)
    eq(leftovers, [], "임시 파일 찌꺼기")


@test("unit", "U06 talk_store — 경로 정규화 · 상한 초과분은 버리지 않고 아카이브로 이관")
def u06(b: Box):
    """사용자가 가장 아끼는 자산이 대화 로그다. 규칙은 하나 — 조용히 짧아지지 않는다."""
    ts = b.mod("talk_store")
    for hostile in ("../../etc/passwd", "CHAR/../x", "..", ""):
        slug = ts.normalize_cid(hostile)
        ok("/" not in slug and "\\" not in slug and ".." not in slug and slug,
           f"경로 성분이 남음: {hostile!r} → {slug!r}")
        ok(ts.talk_path(hostile).parent == ts.STORY_DIR, "대화 로그가 story 폴더 밖으로 나감")
    path = ts.STORY_DIR / "talk_SELFTEST-U06.json"
    arch = ts.archive_path(path)
    try:
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"{i}:" + "가" * 200}
                for i in range(40)]
        ts.save_log(path, msgs, cap=3000)
        kept = ts.load_log(path)
        ok(0 < len(kept) < 40, f"상한이 적용되지 않음(남은 {len(kept)})")
        ok(arch.exists(), "잘라낸 구간이 아카이브로 옮겨지지 않음(대화 소실)")
        moved = [l for l in arch.read_text(encoding="utf-8").splitlines() if l.strip()]
        eq(len(moved) + len(kept), 40, "이관+보존 합계가 원본과 다름(대화가 사라짐)")
        eq(json.loads(moved[0])["content"], msgs[0]["content"], "가장 오래된 대화가 그대로 이관")
        eq(kept[-1]["content"], msgs[-1]["content"], "최신 대화가 잘림")
    finally:
        path.unlink(missing_ok=True)
        arch.unlink(missing_ok=True)


@test("unit", "U07 prompt_build — 앵커·화풍은 코드가 원문 그대로 넣는다(A6 보장)")
def u07(b: Box):
    """LLM 이 무엇을 뱉든 앵커는 코드가 조립한다. 대소문자까지 원문이어야 A6 가 통과한다."""
    pb = b.mod("prompt_build")
    anchor_c, anchor_l = b.anchors()
    sc = read_json(b.root / "examples" / "scenes" / "SCENE-001.json")
    with patched(pb.local_llm, "chat", lambda *a, **k: "she turns from the window"):
        text = pb.compose_image_prompt(sc)
    has(text, anchor_c, "인물 앵커 원문")
    has(text, anchor_l, "장소 앵커 원문")
    has(text, "2:3", "세로 규격")
    has(text, "she turns from the window", "동작 문장")
    with patched(pb.local_llm, "chat", lambda *a, **k: ""):     # LLM 이 빈손이어도
        bare = pb.compose_image_prompt(sc)
    has(bare, anchor_c, "LLM 실패 시 앵커까지 사라짐")
    has(bare, anchor_l, "LLM 실패 시 장소 앵커까지 사라짐")


@test("unit", "U17 prompt_build — 다인물 컷의 인원수 태그(앵커 원문은 그대로 · 린터와 같은 어휘)")
def u17(b: Box):
    """두 사람이 나오는 컷이 **한 사람만** 그려지던 문제의 잠금장치.

    앵커는 자연어 묘사라 사람 수를 세어 주지 않는다(A6 는 앵커가 있는지만 본다). 그래서
    조립부가 앵커 **앞에** 인원수 태그를 넣는다. 여기서 함께 묶는 것이 두 가지다 —
    ① 태그가 붙어도 A6 앵커 원문은 하나도 다치지 않는다,
    ② 태그를 만드는 쪽(prompt_build)과 그것을 되묻는 쪽(scene_ops.has_composition_cue ·
       scene_lint)이 같은 어휘를 본다. 갈라지면 린터가 영영 조용해진다.
    """
    pb, so, sl = b.mod("prompt_build"), b.mod("scene_ops"), b.mod("scene_lint")
    mfp = b.p("project/manifest.json")
    keep = mfp.read_text(encoding="utf-8")
    try:
        mf = read_json(mfp)
        girl = mf["characters"][0]
        boy = json.loads(json.dumps(girl))
        boy.update({"character_id": "CHAR-777", "name": "선배",
                    "prompt_anchor": "18-year-old Korean boy, neat short black hair, white shirt"})
        boy.setdefault("profile", {})["gender_presentation"] = "남성"
        mf["characters"].append(boy)
        write_json(mfp, mf)
        anchor_g, anchor_b = girl["prompt_anchor"], boy["prompt_anchor"]
        anchor_l = mf["locations"][0]["prompt_anchor"]
        sc = read_json(b.root / "examples" / "scenes" / "SCENE-001.json")
        sc["characters"] = [girl["character_id"], "CHAR-777"]
        sc["camera"] = {"shot": "two-shot", "angle": "eye-level"}

        tags = pb.composition_tags(sc)
        for want in ("1girl", "1boy", "2people", "couple", "facing each other"):
            has(tags, want, f"구도 태그에 {want!r} 가 없음")
        ok(so.has_composition_cue(tags),
           f"조립부가 낸 태그를 판정부가 못 알아봄(어휘가 갈렸다): {tags!r}")

        def boom(*_a, **_k):
            raise Failed("action 을 줬는데도 로컬 LLM 을 불렀다")

        with patched(pb.local_llm, "chat", lambda *a, **k: "walking side by side"):
            text = pb.compose_image_prompt(sc)
        for label, anchor in (("인물", anchor_g), ("두 번째 인물", anchor_b), ("장소", anchor_l)):
            has(text, anchor, f"{label} 앵커 원문이 사라짐(A6 FAIL)")
        ok(so.has_composition_cue(text), "완성된 프롬프트에 인원수 단서가 없음")
        ok(text.index("1girl") < text.index(anchor_g), "인원수 태그가 앵커 뒤에 옴(묘사보다 앞에 와야 한다)")
        hasnt(text, "two-shot shot", "샷 표기가 'shot shot' 으로 겹침")

        # 넓은 컷의 **거리 태그** — 샷 이름만으로는 거리가 지켜지지 않았다(실측 6장 중 1장,
        # 프로덕션 0/3). 태그 하나가 3/3 으로 바꿨으므로 그 한 토큰과 그 **자리**를 잠근다.
        # 좁은 컷에 새어 들어가면 연출 의도가 뒤집히므로 그쪽도 함께 잠근다.
        has(pb._shot_phrase("wide"), "wide shot, full body", "넓은 컷에 거리 태그가 없다")
        has(pb._shot_phrase("extreme-wide"), "full body, from a distance",
            "가장 넓은 컷에 거리 태그가 없다")
        eq(pb._shot_phrase("close-up"), "close-up shot", "좁은 컷에 거리 태그가 붙었다")
        eq(pb._shot_phrase("medium"), "medium shot", "중간 컷에 거리 태그가 붙었다")
        wide = pb.compose_image_prompt(dict(sc, camera={"shot": "wide", "angle": "eye-level"}),
                                       action="walking side by side")
        has(wide, "wide shot, full body", "넓은 컷 프롬프트에 거리 태그가 없다")
        ok(wide.index("full body") < wide.index("1girl"),
           "거리 태그가 구도 태그 뒤로 밀렸다 — 실측에서 그 자리는 두 번째 인물을 지웠다")
        hasnt(pb.compose_image_prompt(dict(sc, camera={"shot": "close-up"}),
                                      action="walking side by side"),
              "full body", "좁게 잡은 컷 프롬프트에 거리 태그가 섞였다")
        with patched(pb.local_llm, "chat", boom):      # 서버가 꺼져 있어도 다시 만들 수 있다
            eq(pb.compose_image_prompt(sc, action="walking side by side"), text,
               "action 경로가 LLM 경로와 다른 프롬프트를 만듦")

        # 감정이 '거리' 인 컷에서는 애정 태그를 **빼기만** 한다(실측: 교체하면 인원수 태그
        # 줄이 희석돼 두 번째 인물이 사라졌다 — 문구 2/3 · 문구+네거티브 3/3 손상).
        far = pb.composition_tags(dict(sc, emotion="어색한 침묵"))
        hasnt(far, "couple", "거리 비트인데 애정 태그가 남았다(분기 컷에서 이야기가 뒤집힌다)")
        for want in ("1girl", "1boy", "2people", "facing each other"):
            has(far, want, f"애정 태그를 빼면서 {want!r} 까지 사라짐 — 인원수는 남아야 한다")
        ok(so.has_composition_cue(far),
           f"couple 이 빠지자 판정부가 단서를 못 알아봄(린터가 영영 경고한다): {far!r}")
        has(pb.composition_tags(dict(sc, emotion="안도와 설렘")), "couple",
            "따뜻한 컷에서 애정 태그가 사라졌다")
        hasnt(pb.composition_tags(dict(sc, emotion="설렘", intimacy="distant")), "couple",
              "intimacy='distant' 가 감정을 이기지 못했다")
        has(pb.composition_tags(dict(sc, emotion="서먹함", intimacy="close")), "couple",
            "intimacy='close' 가 감정을 이기지 못했다")

        eq(pb.composition_tags(read_json(b.root / "examples" / "scenes" / "SCENE-001.json")),
           "1girl", "1인 장면 태그")
        hasnt(pb.composition_tags(dict(sc, camera={"shot": "close-up"})), "visible",
              "일부러 좁게 잡은 컷에 '둘 다 보이게' 가 붙음(연출 의도 뒤집기)")

        # 린터(자문)도 같은 사실을 본다 — 경고가 나야 할 때만 난다
        def rules(prompt_text):
            got = []
            sl._check_composition([dict(sc, prompt={"grok_output": prompt_text})], mf,
                                  lambda lv, rule, msg, sid="-": got.append(rule))
            return got

        ok("composition-cue" in rules(f"{anchor_g}, and {anchor_b}, {anchor_l}"),
           "인원수 단서가 없는 2인 프롬프트를 린터가 그냥 보냄")
        ok("two-shot-single" in rules(f"{tags}, {anchor_g}, {anchor_l}"),
           "two-shot 인데 앵커가 하나뿐인 프롬프트를 린터가 그냥 보냄")
        eq(rules(text), [], "제대로 만든 프롬프트에 경고가 남음")
    finally:
        mfp.write_text(keep, encoding="utf-8")


@test("unit", "U18 prompt_build — 인물 태그는 그 인물의 앵커 바로 앞에만 붙는다(A6 원문 보존)")
def u18(b: Box):
    """앵커 문장 끝의 의상·머리색이 옆 사람에게 새던 문제의 잠금장치.

    실측에서 반복해 들어맞은 유일한 처방이 **그 인물의 태그를 그 인물의 앵커 바로 앞에
    두는 것**이었다(순서 바꾸기·끝에 한 번 더·BREAK·네거티브 보강은 시드 노이즈와
    구분되지 않았다). 여기서 잠그는 것은 셋이다 —
    ① 태그가 **자기 앵커 앞**에 오고 남의 앵커 앞으로 가지 않는다,
    ② 앵커 원문은 글자 하나 다치지 않는다(A6),
    ③ prompt_tags 가 없거나 이상한 값이어도 예전과 같은 프롬프트가 나온다(기존 작품 보호).
    """
    pb = b.mod("prompt_build")
    mfp = b.p("project/manifest.json")
    keep = mfp.read_text(encoding="utf-8")
    try:
        mf = read_json(mfp)
        girl = mf["characters"][0]
        boy = json.loads(json.dumps(girl))
        boy.update({"character_id": "CHAR-778", "name": "선배",
                    "prompt_anchor": "18-year-old Korean boy, neat short black hair, white shirt",
                    "prompt_tags": ["black hair", "white shirt", " white shirt ", ""]})
        boy.setdefault("profile", {})["gender_presentation"] = "남성"
        girl["prompt_tags"] = ["light brown hair", "pink cardigan"]
        girl["wardrobe_variants"] = [                      # ④ 의상 배리에이션(아래)
            {"variant_id": "default", "tags": list(girl["prompt_tags"]),
             "anchor": "pastel knit cardigan"},
            {"variant_id": "outing", "tags": ["light brown hair", "cream trench coat"],
             "anchor": "cream trench coat over a beige dress"},
            {"variant_id": "no_tags", "anchor": "thick winter coat"},
        ]
        mf["characters"].append(boy)
        write_json(mfp, mf)
        anchor_g, anchor_b = girl["prompt_anchor"], boy["prompt_anchor"]
        sc = read_json(b.root / "examples" / "scenes" / "SCENE-001.json")
        sc["characters"] = [girl["character_id"], "CHAR-778"]

        eq(pb.character_tags(boy), "black hair, white shirt", "중복·공백 태그가 정리되지 않음")
        text = pb.compose_image_prompt(sc, action="walking side by side")
        for label, anchor in (("인물", anchor_g), ("두 번째 인물", anchor_b)):
            has(text, anchor, f"{label} 앵커 원문이 사라짐(A6 FAIL)")
        # ① 각 태그가 '자기' 앵커 바로 앞에 — 남의 앵커 앞으로 가면 드리프트가 그대로다
        has(text, "light brown hair, pink cardigan, " + anchor_g, "여자 태그가 자기 앵커 앞에 없음")
        has(text, "black hair, white shirt, " + anchor_b, "남자 태그가 자기 앵커 앞에 없음")
        ok(text.index("pink cardigan") < text.index("black hair"),
           "태그 덩어리가 서로 섞임(두 인물 블록의 경계가 무너졌다)")
        ok(text.index("1girl") < text.index(anchor_g), "인원수 태그가 여전히 맨 앞에 있어야 한다")

        # ④ 의상 배리에이션 — **태그 줄**이 통째로 바뀌고 앵커 원문은 그대로, 그 뒤에 wearing.
        #    실측에서 앵커를 갈아 끼우거나 덧붙이기만 해서는 옷이 바뀌지 않았다(SCHEMA §1.6).
        worn = pb.compose_image_prompt(dict(sc, wardrobe={girl["character_id"]: "outing"}),
                                       action="walking side by side")
        has(worn, "light brown hair, cream trench coat, " + anchor_g,
            "배리에이션 태그 줄이 그 인물의 앵커 앞에 오지 않음(옷이 안 바뀐다)")
        hasnt(worn, "pink cardigan", "배리에이션을 지정했는데 기본 태그 줄이 남음")
        has(worn, anchor_g + ", wearing cream trench coat over a beige dress",
            "앵커 **뒤에** wearing <배리에이션 anchor> 가 붙지 않음")
        has(worn, "black hair, white shirt, " + anchor_b,
            "지정하지 않은 인물의 태그가 함께 바뀜(남의 옷까지 갈아입혔다)")

        # 없는 이름·빈 값·이상한 값이면 **예전 프롬프트 그대로**(기존 12장이 안 깨진다)
        for bad in ({girl["character_id"]: "typo_variant"}, {girl["character_id"]: ""}, {}, "쓰레기", 7):
            eq(pb.compose_image_prompt(dict(sc, wardrobe=bad), action="walking side by side"), text,
               f"wardrobe={bad!r} 인데 프롬프트가 달라졌다(선언 안 한 장면이 바뀐다)")

        # tags 없는 배리에이션은 앵커만 덧붙는다 — 옷은 안 바뀐다(scene_lint 가 자문한다)
        thin = pb.compose_image_prompt(dict(sc, wardrobe={girl["character_id"]: "no_tags"}),
                                       action="walking side by side")
        has(thin, "light brown hair, pink cardigan, " + anchor_g,
            "tags 가 없는 배리에이션이 태그 줄을 지웠다")
        has(thin, anchor_g + ", wearing thick winter coat", "tags 가 없어도 앵커는 덧붙어야 한다")

        # ③ 태그가 없거나 망가진 값이면 예전 프롬프트 그대로(기존 작품이 깨지지 않는다)
        for bad in (None, [], "white shirt", 7, [None, "  ", ","]):
            mf2 = read_json(mfp)
            for c in mf2["characters"]:
                if bad is None:
                    c.pop("prompt_tags", None)
                else:
                    c["prompt_tags"] = bad
            write_json(mfp, mf2)
            plain = pb.compose_image_prompt(sc, action="walking side by side")
            for anchor in (anchor_g, anchor_b):
                has(plain, anchor, f"prompt_tags={bad!r} 에서 앵커 원문이 사라짐")
            hasnt(plain, "pink cardigan, 18-year-old", f"prompt_tags={bad!r} 인데 태그가 붙음")
    finally:
        mfp.write_text(keep, encoding="utf-8")


@test("unit", "U19 의상 배리에이션의 불변식 — 'default' 는 옷을 갈아입히지 않는다(린터가 지킨다)")
def u19(b: Box):
    """배리에이션은 **태그 줄을 통째로 대신한다**. 그래서 `"default"` 의 태그 줄이 그 인물의
    `prompt_tags` 와 다르면, '기본 의상' 을 가리킨 컷이 조용히 다른 옷을 입는다 —
    사람이 가장 안전하다고 믿는 값이 가장 위험해진다. `wardrobe_default` 도 같은 종류의
    약속이다(앵커 안 의상 구절을 가리키는 기준점이라 앵커에 글자 그대로 없으면 두 곳이 서로
    다른 옷을 말한다). 조립부는 앵커를 건드리지 않아 A6 가 이 둘을 못 보므로 린터가 지킨다.

    여기서 잠그는 것은 셋이다 — ① `"default"` 를 가리켜도 태그 줄이 그대로다,
    ② 어긋난 기준정보를 `scene_lint` 가 실제로 잡아낸다(경고가 나야 할 때만 난다),
    ③ 손편집 JSON 이 무엇이든 조회가 흔들리지 않는다.
    """
    pb, sl = b.mod("prompt_build"), b.mod("scene_lint")
    tags = ["light brown hair", "pink cardigan"]
    ch = {"character_id": "CHAR-001", "prompt_tags": list(tags),
          "prompt_anchor": "17-year-old girl, pastel knit cardigan, star earrings",
          "wardrobe_default": "pastel knit cardigan",
          "wardrobe_variants": [
              {"variant_id": "default", "tags": list(tags),
               "anchor": "pastel knit cardigan over a white blouse, pleated beige skirt"},
              {"variant_id": "outing", "tags": ["light brown hair", "cream trench coat"],
               "anchor": "cream trench coat"}]}

    # ① 'default' 는 태그 줄을 바꾸지 않는다 — 바뀌는 것은 덧붙는 앵커 한 구절뿐이다
    eq(pb.character_tags(ch, pb.wardrobe_variant(ch, "default")), pb.character_tags(ch),
       "'default' 를 가리켰더니 태그 줄이 달라졌다(기본 의상인데 옷이 바뀐다)")
    block = pb._character_block(ch, pb.wardrobe_variant(ch, "default"))
    has(block, ch["prompt_anchor"], "앵커 원문이 사라짐(A6 FAIL)")
    has(block, ch["prompt_anchor"] + ", wearing " + ch["wardrobe_variants"][0]["anchor"],
        "배리에이션 앵커가 인물 앵커 **뒤에** 붙지 않음")
    eq(pb._character_block(ch, pb.wardrobe_variant(ch, "없는이름")), pb._character_block(ch),
       "없는 배리에이션을 가리켰는데 프롬프트가 달라졌다")

    # ② 어긋난 기준정보를 린터가 잡는다(정상일 때는 조용하다)
    def rules(char: dict) -> list:
        got = []
        sl._check_wardrobe([], {"characters": [char]},
                           lambda lv, rule, msg, sid="-": got.append(rule))
        return got

    eq(rules(ch), [], "정상 기준정보에 경고가 남음")
    drifted = json.loads(json.dumps(ch))
    drifted["wardrobe_variants"][0]["tags"] = ["light brown hair", "cream trench coat"]
    ok("wardrobe-default-tags" in rules(drifted),
       "'default' 태그 줄이 prompt_tags 와 어긋났는데 린터가 그냥 보냄")
    off = json.loads(json.dumps(ch))
    off["wardrobe_default"] = "school blazer"
    ok("wardrobe-anchor-key" in rules(off),
       "wardrobe_default 가 앵커에 없는데 린터가 그냥 보냄")

    # ③ 손편집 JSON 방탄 — 무엇이 들어와도 프롬프트가 깨지지 않는다
    eq(pb.wardrobe_variant({"wardrobe_variants": "쓰레기"}, "default"), {}, "이상한 값에서 조회가 흔들림")
    eq(pb.wardrobe_variant({}, ""), {}, "빈 id 조회")
    eq(pb.scene_wardrobe({"wardrobe": "쓰레기"}, "CHAR-001"), "", "이상한 wardrobe 값")
    eq(pb.scene_wardrobe({}, "CHAR-001"), "", "wardrobe 키가 없는 장면")
    ok("wardrobe" in b.mod("scene_ops").EDITABLE_FIELDS,
       "wardrobe 가 편집 화이트리스트에 없다 — 스튜디오가 '알 수 없는 장면 필드' 로 거부한다")


@test("unit", "U20 prompt_build.is_distance_beat — 감정만 본다(목적을 훑으면 가장 따뜻한 컷이 걸린다)")
def u20(b: Box):
    """애정 태그(`couple`)를 언제 빼는지의 단일 판정. 여기서 잠그는 것은 셋이다.

    ① **목적·동작은 보지 않는다.** 이 작품의 호감 엔딩(SCENE-011)은 목적이
       "**오해**가 풀리고 한 걸음의 간격이 사라진다" 라서, 목적을 훑으면 앨범에서
       가장 따뜻한 컷의 애정 태그가 빠진다 — 규칙이 정반대로 작동한다.
    ② 12컷의 실제 감정으로 재면 정확히 셋(서운함 · 어색한 침묵 · 서먹함)만 걸린다.
       `아쉬움과 설렘`·`안도와 설렘` 처럼 '설렘' 이 든 감정을 끌어들이면 안 된다.
    ③ `intimacy` 는 **양방향 수동 스위치**다 — 사람이 적으면 감정을 이긴다.
       그 필드가 `scene_ops.EDITABLE_FIELDS` 에 없으면 스튜디오가 저장을 거부한다.
    """
    pb, so = b.mod("prompt_build"), b.mod("scene_ops")
    for emo in ("서운함", "어색한 침묵", "서먹함"):
        ok(pb.is_distance_beat({"emotion": emo}), f"거리 비트를 못 알아봄: {emo}")
    for emo in ("설렘", "포근함", "설렘과 평온", "두근거림", "잔잔한 두근거림", "따뜻한 여운",
                "아쉬움과 설렘", "안도와 설렘", "결연함, 약간의 긴장"):
        ok(not pb.is_distance_beat({"emotion": emo}), f"따뜻한 컷이 거리 비트로 걸림: {emo}")

    ok(not pb.is_distance_beat({"emotion": "안도와 설렘",
                                "purpose": "오해가 풀리고 한 걸음의 간격이 사라진다",
                                "action_beat": "어색한 침묵을 깨고 팔짱을 낀다"}),
       "목적·동작을 훑고 있다 — 호감 엔딩에서 애정 태그가 빠진다")

    ok(pb.is_distance_beat({"emotion": "설렘", "intimacy": "DISTANT"}),
       "intimacy='distant' 가 감정을 이기지 못함(대소문자 포함)")
    ok(not pb.is_distance_beat({"emotion": "서먹함", "intimacy": "close"}),
       "intimacy='close' 가 감정을 이기지 못함")
    ok(not pb.is_distance_beat({"emotion": "서먹함", "intimacy": "가까움"}),
       "'distant' 가 아닌 값은 전부 '거리 아님' 이어야 한다")
    ok("intimacy" in so.EDITABLE_FIELDS,
       "intimacy 가 편집 화이트리스트에 없다 — 스튜디오가 '알 수 없는 장면 필드' 로 거부한다")

    for bad in (None, 7, [], {"a": 1}):          # 손편집 JSON 방탄 — 판정이 죽으면 안 된다
        ok(not pb.is_distance_beat({"emotion": bad, "intimacy": bad}),
           f"이상한 값에서 판정이 흔들림: {bad!r}")
    ok(not pb.is_distance_beat({}), "빈 장면이 거리 비트로 걸림")


@test("unit", "U21 prompt_build — '노을' 은 두 낱말이다(golden hour) · 린터는 한 버킷으로 읽는다")
def u21(b: Box):
    """넓게 잡은 노을 컷이 **블루아워로 떨어지던** 문제의 잠금장치.

    시간대 낱말은 프롬프트 맨 끝 한 토큰이라, 하늘이 넓게 보이는 컷에서는 장소 앵커의
    밤 조명 낱말에 밀린다(SCENE-012 하늘 파랑 .670 = 밤 컷보다 더 파랬다). 실측에서
    자리를 바꾸는 것은 오히려 나빴고(.255 → .309) 화려한 문구는 과보정이었다 —
    `golden hour` **한 낱말**만 들어맞았다(010 · 012 3/3, 승인 컷 색 대역 안).

    여기서 잠그는 것은 둘이다 — ① 그 낱말이 사라지지 않는다, ② 두 낱말이 `scene_lint`
    에서 **한 시간대**로 읽힌다(갈리면 모든 노을 컷에 `time-mixed` 경고가 새로 뜬다).
    """
    pb, sl = b.mod("prompt_build"), b.mod("scene_lint")
    eq(pb.TIME_EN["노을"], "sunset, golden hour", "노을 시간대 낱말(실측으로 고정된 값)")
    eq(sorted(sl._prompt_hits(pb.TIME_EN["노을"])), ["evening"],
       "두 낱말이 서로 다른 시간대로 읽힌다 — 노을 컷마다 time-mixed 경고가 뜬다")
    eq(pb.TIME_EN["밤"], "night", "밤은 실측이 정상이라 손대지 않는다(근거 없는 변경 금지)")

    sc = read_json(b.root / "examples" / "scenes" / "SCENE-001.json")
    text = pb.compose_image_prompt(dict(sc, time="노을"), action="walking along the river")
    ok(text.rstrip().endswith("sunset, golden hour"),
       f"시간대 낱말이 프롬프트 꼬리에 그대로 붙지 않음: …{text[-60:]!r}")
    eq(pb.SEGMENT_ORDER[-1], "time",            # 꼬리 검사가 '우연히' 맞는 일이 없도록
       "시간대 조각이 마지막 자리를 떠났다 — 끝에 붙는 것은 실측으로 산 자리다")
    hasnt(pb.compose_image_prompt(dict(sc, time="오후"), action="walking along the river"),
          "golden hour", "노을이 아닌 컷에 golden hour 가 새어 들어감")


@test("unit", "U22 손편집한 장면의 두 낱말을 린터가 읽는다 — 편집 경로만 막으면 절반이다")
def u22(b: Box):
    """`intimacy` 와 `wardrobe` 는 **편집 경로에서만** 좁혀져 있었다
    (`scene_ops._apply_field`: 오타 거부 · dict 강제). 하지만 장면은 디스크의 JSON 이고
    이 저장소는 손으로도 고친다 — 그 경로에는 관문이 하나도 없었고, `check_protocol` 은
    두 필드를 아예 보지 않으며(A2/A6 는 양쪽 모양을 다 통과시킨다), `scene_lint` 도
    조용했다. 그래서 잘못 적힌 두 낱말이 **아무 데서도 티가 나지 않았다**.

    조용한 쪽이 위험한 이유가 서로 다르다.

    ① `intimacy` 오타는 연출을 **정확히 반대로** 뒤집는다. `is_distance_beat` 는 값이
       비어 있지 않으면 `emotion` 을 아예 보지 않고 `== "distant"` 하나만 묻는다 —
       `"distatn"` 은 거짓 = '가깝다' 가 되어, 감정으로는 거리 비트인 컷에 애정 태그가
       도로 붙는다. 이 작품에서 그 컷은 분기를 결정하는 SCENE-009(서운함)다.
    ② `wardrobe` 가 dict 가 아니면 `scene_wardrobe` 가 조용히 `''` 를 돌려주므로
       옷은 영원히 안 바뀐다. 사람은 옷을 지정했다고 믿는다.

    둘 다 '규격 위반' 이 아니라 '설계 사고' 라 자문 계층이 올바른 자리다 —
    그래서 여기서도 종료 코드는 0 이어야 한다(검사기 불침범).
    """
    pb, sl = b.mod("prompt_build"), b.mod("scene_lint")

    def rules(sc: dict) -> list:
        got = []
        sl._check_intimacy([sc], lambda lv, rule, msg, sid="-": got.append(rule))
        sl._check_wardrobe([sc], {"characters": []},
                           lambda lv, rule, msg, sid="-": got.append(rule))
        return got

    base = {"scene_id": "SCENE-009", "emotion": "서운함"}

    # ① intimacy — 오타는 잡고, 올바른 값과 빈 값은 조용하다
    ok(pb.is_distance_beat(base), "감정만으로는 거리 비트여야 한다(전제)")
    for typo in ("distatn", "far", "DISTANT_", "distant2"):
        sc = dict(base, intimacy=typo)
        ok(not pb.is_distance_beat(sc),
           f"{typo!r} 가 거리 비트로 읽혔다 — 이 테스트의 전제가 깨졌다")
        ok("intimacy-value" in rules(sc),
           f"intimacy {typo!r} 가 조용히 연출을 뒤집는데 린터가 그냥 보냄")
    for good in ("distant", "close", "DISTANT", " close ", ""):
        eq([r for r in rules(dict(base, intimacy=good)) if r == "intimacy-value"], [],
           f"정상 intimacy {good!r} 에 경고가 남음")
    eq([r for r in rules(base) if r == "intimacy-value"], [],
       "intimacy 키가 없는 장면(= 예전 그대로)에 경고가 남음")
    ok("intimacy-value" in rules(dict(base, intimacy=7)), "문자열이 아닌 intimacy 를 그냥 보냄")

    # ② wardrobe — 모양이 틀리면 잡고, 없거나 올바르면 조용하다
    for bad in ("outing", ["default"], 7):
        sc = dict(base, wardrobe=bad)
        eq(pb.scene_wardrobe(sc, "CHAR-001"), "",
           f"{bad!r} 에서 wardrobe 가 조용히 무시되지 않았다 — 전제가 깨졌다")
        ok("wardrobe-shape" in rules(sc),
           f"wardrobe 가 {type(bad).__name__} 인데 린터가 그냥 보냄(옷이 영영 안 바뀐다)")
    eq([r for r in rules(base) if r == "wardrobe-shape"], [],
       "wardrobe 키가 없는 장면(= 예전 그대로)에 경고가 남음")
    eq([r for r in rules(dict(base, wardrobe={"CHAR-001": "default"}))
        if r == "wardrobe-shape"], [], "정상 wardrobe 에 모양 경고가 남음")

    # ③ 자문 계층의 계약 — 이 경고들이 검사기를 오염시키지 않는다
    out = sl.run() if hasattr(sl, "run") else None
    if isinstance(out, dict):
        eq([f for f in out["findings"]
            if f["rule"] in ("intimacy-value", "wardrobe-shape")], [],
           "살아 있는 저장소에 새 경고가 떠 있다(장면 파일이 실제로 잘못 적혀 있다)")


@test("unit", "U23 prompt_build — 프롬프트 순서를 아는 곳은 SEGMENT_ORDER 하나뿐(조립은 순수 함수)")
def u23(b: Box):
    """실측으로 산 순서가 'append 가 몇 번째 줄이냐' 로만 남아 있던 자리의 잠금장치.

    조립부는 **이름 붙은 조각의 목록**이다 — 순서는 `prompt_build.SEGMENT_ORDER`,
    조각은 `prompt_segments`, 잇기는 `assemble`. 여기서 잠그는 것은 셋이다 —
    ① 실측이 정한 자리(샷 뒤 거리 태그 → 인원수 태그 → 앵커, 시간대는 맨 끝)가 **상수 하나**에 있다,
    ② `assemble` 은 매니페스트도 LLM 도 보지 않는 **순수 함수**다(장면 없이 순서를 되물을 수 있다),
    ③ 부수효과는 `action_for` 하나뿐이다 — 문장을 주면 서버를 부르지 않는다.
    """
    pb = b.mod("prompt_build")
    eq(pb.SEGMENT_ORDER,
       ("style", "shot", "camera", "composition", "subject", "action", "others", "location", "time"),
       "세그먼트 순서가 바뀌었다 — 실측으로 산 자리다(바꾸려면 다시 재 볼 것)")
    order = list(pb.SEGMENT_ORDER)
    ok(order.index("shot") < order.index("composition"),
       "거리 태그가 구도 태그 뒤로 밀렸다 — 실측에서 그 자리는 두 번째 인물을 지웠다")
    ok(order.index("shot") < order.index("camera") < order.index("composition"),
       "카메라 조각이 측정한 자리(샷 뒤 · 인원수 앞)를 떠났다")
    ok(order.index("composition") < order.index("subject"),
       "인원수는 묘사가 시작되기 전에 정해져야 한다")
    eq(order[-1], "time",
       "시간대 낱말이 꼬리를 떠났다 — 앞으로 옮기면 노을이 더 나빠졌다(.255 → .309)")

    # ② 순수 함수 — 장면도 매니페스트도 없이 그 자리에서 되물을 수 있다
    eq(pb.assemble({}), "", "빈 조각 묶음이 빈 문자열이 아니다")
    eq(pb.assemble({"style": " ", "action": "x"}), "x", "공백뿐인 조각이 쉼표만 남기고 들어갔다")
    eq(pb.assemble({"time": "night", "style": "anime"}), "anime, night",
       "조각을 넣은 순서가 결과 순서를 바꿨다 — 정본은 SEGMENT_ORDER 하나여야 한다")
    eq(pb.assemble({"style": "a", "zzz": "b"}), "a", "이름 없는 조각이 프롬프트에 새어 들어갔다")

    # ③ 부수효과는 한 곳뿐
    def boom(*_a, **_k):
        raise Failed("동작 문장을 줬는데도 로컬 LLM 을 불렀다")

    sc = read_json(b.root / "examples" / "scenes" / "SCENE-001.json")
    with patched(pb.local_llm, "chat", boom):
        eq(pb.action_for({}, " she waits" + chr(10) + "by the window "), "she waits by the window",
           "동작 문장 정규화(줄바꿈·앞뒤 공백)가 달라졌다")
        eq(pb.action_for({}, '"quoted"'), "quoted", "따옴표가 그대로 프롬프트에 실린다")
        eq(len(pb.action_for({}, "가" * 400)), 220, "동작 문장 길이 상한(220자)이 풀렸다")
        eq(pb.compose_image_prompt(sc, action="walking side by side"),
           pb.assemble(pb.prompt_segments(sc, pb.action_for(sc, "walking side by side"))),
           "compose_image_prompt 가 조립 삼단(action_for → prompt_segments → assemble)과 갈라졌다")


@test("unit", "U24 prompt_build.ANGLE_EN — 각도만 배선한다(eye-level 은 아무것도 안 낸다 · framing·focus 는 안 실린다)")
def u24(b: Box):
    """카메라 네 필드 중 **하나만** 프롬프트에 닿는다 — 실측이 그렇게 정했다.

    여기서 잠그는 것은 넷이다.
    ① 린터가 아는 각도(`vn_core.STD_ANGLES`)는 전부 프롬프트 표기가 정해져 있다 —
       어휘만 늘리고 표기를 안 정하면 작가가 적은 각도가 조용히 사라진다.
    ② `eye-level`·`front` 는 **빈 문자열**이다. 실측에서 0/6(변화량 = 시드 노이즈의 0.23~0.61배)
       이었고, 빈 문자열이라야 승인된 앨범 12장의 저장된 프롬프트가 글자 하나 안 바뀐다.
    ③ 각도 낱말의 **자리** — 샷 이름·거리 태그 뒤, 인원수 태그 앞(측정한 자리).
    ④ `framing`·`focus` 는 프롬프트에 **실리지 않는다**. focus 를 Danbooru 표기로 실었을 때
       샷을 덮어써 두 번째 인물을 3/3 지웠다 — 되살리려면 SCHEMA §2.2 각주부터 반증할 것.
    """
    pb, vc, sl = b.mod("prompt_build"), b.mod("vn_core"), b.mod("scene_lint")

    # ① 린터 어휘 ↔ 조립부 표기가 갈리지 않는다(정본은 vn_core 하나)
    eq(sl.STD_ANGLES, vc.STD_ANGLES, "린터가 vn_core 와 다른 각도 목록을 본다")
    missing = [a for a in vc.STD_ANGLES if a not in pb.ANGLE_EN]
    eq(missing, [], f"표준 각도인데 프롬프트 표기가 없다 — 조용히 사라진다: {missing}")

    # ② 측정된 무효값
    eq(pb.angle_phrase("eye-level"), "", "eye-level 이 낱말을 냈다 — 실측 0/6, 12장면 전부가 이 값이다")
    eq(pb.angle_phrase("front"), "", "front 가 낱말을 냈다(인원수 태그가 이미 함의한다)")
    eq(pb.angle_phrase("high-angle"), "from above", "측정으로 고른 표기(6/6 에서 카메라가 움직였다)")
    eq(pb.angle_phrase("low-angle"), "from below", "측정으로 고른 표기(4/6)")
    eq(pb.angle_phrase("Low Angle"), "from below", "표기 흔들림을 린터와 같은 함수로 펴지 않는다")
    eq(pb.angle_phrase("low"), "from below", "린터가 표준으로 고쳐 주는 약칭을 조립부가 못 알아본다")
    eq(pb.angle_phrase("옆에서"), "", "표준 밖 값이 프롬프트에 새어 들어갔다(린터가 말할 몫이다)")
    eq(pb.angle_phrase(""), "", "빈 각도가 낱말을 냈다")

    sc = read_json(b.root / "examples" / "scenes" / "SCENE-001.json")
    sc["camera"] = {"shot": "wide", "angle": "eye-level", "framing": "테이블을 사이에 둔 두 사람",
                    "focus": "식은 잔과 돌아간 시선"}
    base = pb.compose_image_prompt(sc, action="walking side by side")

    # ③ 자리 — 샷·거리 태그 뒤, 인원수 태그 앞
    high = pb.compose_image_prompt(dict(sc, camera=dict(sc["camera"], angle="high-angle")),
                                   action="walking side by side")
    has(high, "wide shot, full body, from above", "각도가 샷·거리 태그 바로 뒤에 붙지 않았다")
    ok(high.index("from above") < high.index("1girl"),
       "각도가 인원수 태그 뒤로 밀렸다 — 인원수는 묘사가 시작되기 전에 정해져야 한다")

    # ② 다시 — eye-level 은 배선 전과 **글자 하나** 다르지 않다
    eq(base, pb.compose_image_prompt({k: v for k, v in sc.items() if k != "camera"}
                                     | {"camera": {"shot": "wide"}}, action="walking side by side"),
       "eye-level 이 프롬프트를 바꿨다 — 승인된 앨범 12장의 프롬프트가 전부 어긋난다")

    # ④ framing·focus 는 닿지 않는다
    for word in ("테이블을 사이에 둔", "식은 잔", "focus", "depth of field"):
        hasnt(base, word, f"framing/focus 가 프롬프트에 실렸다({word!r}) — 실측에서 안 통했거나 해로웠다")
    eq(pb.camera_segment(sc), "", "카메라 조각이 각도 말고 다른 것을 내고 있다")


@test("unit", "U25 scene_lint.prompt-drift — 저장된 프롬프트가 조립부와 갈라진 컷을 말해 준다(자문)")
def u25(b: Box):
    """조립 규칙은 실측마다 바뀌는데 프롬프트는 **장면 파일에 저장**된다 — 그 차이를 아무도
    말해 주지 않던 자리의 잠금장치.

    '노을' 이 두 낱말이 된 뒤에도 옛 컷의 프롬프트는 `sunset` 한 낱말로 남아 있었고,
    거리 비트에서 `couple` 을 뺀 뒤에도 옛 프롬프트에는 그대로 있었다. 그 자체는 고장이
    아니다 — **그 그림은 그 조리법으로 구워졌다**. 그래서 여기서 잠그는 것은 셋이다.
    ① 갈라진 컷과 **어느 조각**이 갈라졌는지를 말한다,
    ② 동작 문장은 비교하지 않는다(사람이 쓰는 한 문장이라 재현할 수 없다),
    ③ 이것은 자문이다 — level 은 info 이고 종료 코드는 0 이다(검사기 불침범).
    """
    pb, sl = b.mod("prompt_build"), b.mod("scene_lint")
    mf = read_json(b.p("project/manifest.json"))
    base = read_json(b.root / "examples" / "scenes" / "SCENE-001.json")
    sc = dict(base, time="노을")
    text = pb.compose_image_prompt(sc, action="walking along the river")

    def drifts(stored: str, scene: dict | None = None) -> list:
        got = []
        sl._check_prompt_drift([dict(scene or sc, prompt={"grok_output": stored})], mf,
                               lambda lv, rule, msg, sid="-": got.append((lv, rule, msg)))
        return [g for g in got if g[1] == "prompt-drift"]

    # ① 지금 조립부가 낸 그대로면 조용하다
    eq(drifts(text), [], "방금 조립한 프롬프트를 갈라졌다고 한다(거짓 경보)")

    # ② 꼬리 — '노을' 이 옛 한 낱말로 남은 컷(실제로 이 저장소에 있던 상태)
    got = drifts(text.replace("sunset, golden hour", "sunset"))
    eq(len(got), 1, f"옛 시간대 낱말을 못 찾거나 여러 줄로 말한다: {got}")
    has(got[0][2], "'time'", "어느 조각이 갈라졌는지 말하지 않는다")
    eq(got[0][0], "info", "자문이어야 할 것이 경고로 떴다(검사기 불침범)")

    # ③ 머리 — 앞쪽 조각이 갈라져도 찾는다
    got = drifts(text.replace("portrait 2:3", "portrait 3:4"))
    eq(len(got), 1, "프롬프트 앞쪽 조각의 차이를 못 찾는다")
    has(got[0][2], "'style'", "갈라진 조각의 이름이 틀렸다")

    # ④ 동작 문장은 비교하지 않는다 — 사람이 손으로 쓴 문장이 매번 경고가 되면 안 된다
    eq(drifts(pb.compose_image_prompt(sc, action="she stops and looks back at him")), [],
       "동작 문장이 다르다고 갈라졌다고 한다 — 그 문장은 재현 대상이 아니다")
    eq(drifts(""), [], "프롬프트가 없는 장면에 대해 말한다")

    # ⑤ 살아 있는 저장소에서도 이것은 자문이다(종료 코드 0 · level info)
    out = sl.lint_scenes()
    for f in out["findings"]:
        if f["rule"] == "prompt-drift":
            eq(f["level"], "info", f"prompt-drift 가 경고로 떴다: {f}")


@test("unit", "U26 파생물 보관 규칙 — 도구는 다시 만들 수 있는 것만 지운다(후보·백업은 손대지 않는다)")
def u26(b: Box):
    """output/ 이 저장소에서 가장 큰 무제한 폴더이던 자리의 잠금장치(실측 239.1MB · 47개 파일).

    폴더마다 **누가 지워도 되는가**가 다르다. 인화 마스터·감상본 캐시·썸네일은 승인된 컷에서
    언제든 다시 만들어지므로 도구가 정리한다. 후보 이미지(다른 컷을 다시 고를 때 쓰는 대체
    테이크)와 백업(유일본)은 **사람이 정한다** — 그래서 도구의 정리 경로가 그 둘을 건드리지
    않는다는 것까지 여기서 잠근다.
    """
    pe, ev, wa = b.mod("print_export"), b.mod("export_viewer"), b.mod("webapp")

    # 지우면 안 되는 쪽 — 정리 전에 증거를 심어 둔다
    keepers = [b.root / "images" / "raw" / "SCENE-001" / "candidate.png",
               b.root / "backups" / "project_old.zip"]
    for f in keepers:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 2048)

    # ① 인화 마스터 — 최근 N종만 남고, 방금 구운 규격과 남의 폴더는 살아남는다
    out = b.root / "output" / "print"
    for i, name in enumerate(("4x6", "5x7", "8x10", "photocard")):
        d = out / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "001_SCENE-001.jpg").write_bytes(b"x" * 4096)
        sheet = d / "spec_sheet.json"
        sheet.write_text("{}", encoding="utf-8")
        os.utime(sheet, (1_700_000_000 + i * 60, 1_700_000_000 + i * 60))   # 뒤일수록 최신
    foreign = out / "직접만든폴더"          # spec_sheet 가 없다 = 이 도구가 만들지 않았다
    foreign.mkdir(parents=True, exist_ok=True)
    (foreign / "note.txt").write_text("사람이 둔 파일", encoding="utf-8")

    gone = pe.prune_size_dirs(keep=2, protect=out / "4x6")
    left = sorted(d.name for d in out.iterdir() if d.is_dir())
    eq(sorted(gone), ["5x7"], f"지운 규격이 기대와 다르다(지움: {gone} · 남음: {left})")
    ok((out / "4x6").is_dir(), "방금 구운 규격을 지웠다 — 사용자가 지금 쓰는 파일이다")
    ok(foreign.is_dir(), "spec_sheet 가 없는 폴더(사람이 만든 것)를 지웠다")
    for name in ("8x10", "photocard"):
        ok((out / name).is_dir(), f"최근 규격 {name} 이 사라졌다")

    # ② 감상본 캐시 — 상한은 개수가 아니라 **바이트**다(항목 하나가 컷 한 장을 담는다)
    ev.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for f in ev.CACHE_DIR.glob("*.txt"):       # 앞선 테스트가 남긴 항목과 섞이지 않게
        f.unlink()
    for i in range(5):
        f = ev.CACHE_DIR / f"k{i}.txt"
        f.write_text("y" * 10_000, encoding="utf-8")
        os.utime(f, (1_700_000_000 + i * 60, 1_700_000_000 + i * 60))
    eq(ev.prune_cache(keep=999, keep_bytes=25_000), 3, "바이트 예산을 넘겼는데 개수 상한만 봤다")
    rest = sorted(f.name for f in ev.CACHE_DIR.glob("*.txt"))
    eq(rest, ["k3.txt", "k4.txt"], f"오래된 것부터 지우지 않았다: {rest}")

    # ③ 썸네일 — 예전에는 지우는 코드가 아예 없었다(요청 한 번에 한 장씩 영원히 쌓였다)
    wa.THUMB_DIR.mkdir(parents=True, exist_ok=True)
    for f in wa.THUMB_DIR.glob("*.jpg"):
        f.unlink()
    for i in range(4):
        f = wa.THUMB_DIR / f"t{i}.jpg"
        f.write_bytes(b"z" * 10_000)
        os.utime(f, (1_700_000_000 + i * 60, 1_700_000_000 + i * 60))
    eq(wa.prune_thumbs(keep_bytes=25_000), 2, "썸네일 예산이 지켜지지 않았다")
    eq(sorted(f.name for f in wa.THUMB_DIR.glob("*.jpg")), ["t2.jpg", "t3.jpg"],
       "썸네일도 오래된 것부터 지워야 한다")

    # ④ 사람이 정하는 쪽은 그대로다
    for f in keepers:
        ok(f.is_file(), f"도구의 정리 경로가 {f.name} 을 지웠다 — 이쪽은 사람이 정한다")


@test("unit", "U08 gen_jobs — 같은 장면 동시 claim 거부 · CLI 경로도 같은 관문(중복 과금 방지)")
def u08(b: Box):
    gj = need_mod(b, "gen_jobs")
    err = getattr(gj, "VNError", RuntimeError)
    sid, other = "SCENE-901", "SCENE-902"

    def done(mod, s):     # release 는 계약에 없는 편의 API 라 없을 수도 있다고 본다
        rel = getattr(mod, "release", None)
        rel(s) if callable(rel) else mod.note(s, "정리", running=False)

    gj.claim(sid)
    try:
        raises(lambda: gj.claim(sid), err, "두 번째 claim 이 통과(같은 장면 2회 과금)")
        eq(gj.status(sid)["running"], True, "status.running")
        ok(sid in gj.running(), "running() 목록에 없음")
        gj.note(sid, "MakeFun 생성 중…")
        has(gj.status(sid)["message"], "생성 중", "note 가 반영되지 않음")
        gj.claim(other)                       # 다른 장면은 막히지 않는다
        gj.note(other, "완료", running=False)
        ok(other not in gj.running(), "끝난 작업이 목록에 남음")
        raises(lambda: gj.claim("../etc"), err, "형식이 틀린 id 가 관문을 통과")
    finally:
        for s in (sid, other):
            done(gj, s)
    eq(gj.status(sid)["running"], False, "해제 후에도 running")
    ok(sid not in gj.running(), "해제 후에도 목록에 남음")
    gj.claim(sid)                             # 끝난 뒤에는 다시 잡을 수 있어야 한다
    done(gj, sid)

    # CLI(makefun_client) 경로가 같은 표시를 보는가 — 서버 밖 중복 과금의 유일한 방어선.
    # (in-process 적재본과 makefun 이 import 한 gen_jobs 는 서로 다른 인스턴스라,
    #  반드시 makefun 이 실제로 쓰는 쪽을 잡아서 확인한다.)
    mk = b.mod("makefun_client")
    jobs = mk._jobs() if hasattr(mk, "_jobs") else None
    claim_scene = getattr(mk, "claim_scene", None)
    if jobs is None or claim_scene is None:
        raise Gap("makefun_client 가 아직 gen_jobs 를 통과하지 않음 — CLI 로 같은 장면을 또 구울 수 있다")
    cli_sid = "SCENE-903"
    jobs.claim(cli_sid)                       # 웹이 먼저 잡은 상태를 흉내
    try:
        raises(lambda: claim_scene(cli_sid, "생성").__enter__(), RuntimeError,
               "웹이 생성 중인 장면을 CLI 가 또 굽는다")
    finally:
        done(jobs, cli_sid)
    with claim_scene(cli_sid, "생성") as got:     # 네트워크 없음 — 표시만 잡았다 푼다
        eq(bool(got), True, "정상 상황인데 선점하지 못함")
    ok(cli_sid not in jobs.running(), "블록을 나갔는데 표시가 남음(영구 잠금)")

    # 실패는 **문구가 아니라 error 키**로 말한다. 예전에는 "실패: …" 라는 사람용 한 줄만
    # 남았고, 화면(studio.js pollGenUntilDone)은 error 키를 보므로 실패한 작업이 '완료' 로
    # 보고됐다 — 토큰 없는 업스케일이 "확대본을 저장했습니다" 로 끝났다(유료 경로에서는
    # 사용자가 한 번 더 눌러 두 번 결제하게 만드는 거짓말이다).
    fail_sid = "SCENE-904"

    def boom():
        raise err("MAKEFUN_API_TOKEN 환경변수가 없습니다")

    gj.claim(fail_sid)
    raises(lambda: gj.run(fail_sid, boom, "업스케일", register=False), err,
           "실패가 호출부로 전파되지 않음")
    st = gj.status(fail_sid)
    eq(st["running"], False, "실패한 작업이 아직 도는 것으로 보고됨")
    has(str(st.get("error", "")), "MAKEFUN_API_TOKEN",
        f"실패가 error 키로 오지 않음 — 화면은 이것을 완료로 읽는다: {st}")
    has(st["message"], "실패", "사람이 읽는 문구에서 실패가 사라짐")
    gj.claim(fail_sid)
    gj.release(fail_sid, "완료 — 업스케일 1장")
    ok("error" not in gj.status(fail_sid),
       f"성공한 작업에 error 키가 남음(멀쩡한 결과가 실패로 보인다) — {gj.status(fail_sid)}")


@test("unit", "U09 scene_ops.update_fields — 화이트리스트 병합 · 보호 필드는 거부(우회 차단)")
def u09(b: Box):
    """편집 폼이 status·review·assets 를 쓸 수 있으면 사람 승인 게이트가 필드 하나로
    우회된다. 조용히 무시하지 않고 **거부**하는 쪽이 규약이다(잘못 보낸 쪽이 알아야 한다)."""
    so = b.mod("scene_ops")
    err = getattr(so, "VNError", RuntimeError)
    update = need_attr(so, "update_fields", "웹 편집(/api/set-scene)의 유일한 구현")
    with fresh_scene(b) as sid:
        before = b.scene(sid)
        res = update(sid, {"purpose": "새 목적", "emotion": "설렘", "ending": True,
                           "ending_label": "호감 엔딩", "print": {"crop_anchor": "top"},
                           "camera": {"shot": "close-up"}})
        sc = b.scene(sid)
        eq(sc["purpose"], "새 목적", "purpose 병합")
        eq(sc["emotion"], "설렘", "emotion 병합")
        eq(sc.get("ending_label"), "호감 엔딩", "ending_label 병합")
        eq((sc.get("print") or {}).get("crop_anchor"), "top", "print 부분 병합")
        eq(sc["camera"]["shot"], "close-up", "camera 병합")
        eq(sc["action_beat"], before["action_beat"], "손대지 않은 필드가 지워짐(덮어쓰기)")
        eq(sc["status"], before["status"], "편집이 상태를 움직임")
        ok("purpose" in (res.get("updated") or []), f"updated 목록 — {res}")
        eq(res.get("checker_pass"), True, f"편집 후 검사 — {str(res.get('fails'))[:200]}")
        # 새로 생긴 선택 필드 둘 — 화이트리스트에만 올리고 **반영을 잊으면 조용히 사라진다**
        # (실제로 그랬다: 저장은 성공했다고 답하는데 장면 파일에는 아무것도 남지 않았다).
        update(sid, {"intimacy": "Distant", "wardrobe": {"CHAR-001": "outing", "CHAR-002": "  "}})
        sc2 = b.scene(sid)
        eq(sc2.get("intimacy"), "distant", "intimacy 가 저장되지 않음")
        eq(sc2.get("wardrobe"), {"CHAR-001": "outing"}, "wardrobe 가 저장되지 않음(빈 값은 버린다)")
        ok(b.mod("prompt_build").is_distance_beat(sc2), "저장된 intimacy 가 조립부 판정에 닿지 않음")
        raises(lambda: update(sid, {"intimacy": "distatn"}), err,
               "오타 intimacy 가 통과 — 조용히 '가깝다' 로 읽혀 연출이 뒤집힌다")
        raises(lambda: update(sid, {"wardrobe": "outing"}), err, "문자열 wardrobe 가 통과")
        update(sid, {"intimacy": "", "wardrobe": {}})
        sc3 = b.scene(sid)
        ok("intimacy" not in sc3 and "wardrobe" not in sc3,
           f"빈 값이 키를 지우지 않음 — {sc3.get('intimacy')!r} · {sc3.get('wardrobe')!r}")

        # 보호 필드는 하나씩 넣어도 전부 거부되고, 파일은 그대로여야 한다
        keep = b.scene(sid)
        for bad in ({"status": "APPROVED"}, {"review": {"human": "PASS"}},
                    {"assets": {"selected_image": "images/raw/x.png"}},
                    {"scene_id": "SCENE-999"}, {"scene_order": 77},
                    {"purpose": "같이 보낸 정상 필드", "status": "APPROVED"}):
            raises(lambda bad=bad: update(sid, bad), err, f"보호 필드 통과: {sorted(bad)}")
        raises(lambda: update(sid, {"없는필드": 1}), err, "화이트리스트 밖 필드")
        raises(lambda: update(sid, {}), err, "빈 편집")
        raises(lambda: update(sid, [1, 2]), err, "비-dict 본문")
        raises(lambda: update("../etc", {"purpose": "x"}), err, "장면 ID 형식 검증")
        eq(b.scene(sid), keep, "거부됐는데 파일이 바뀜")
    with cli_scene(b, "APPROVED") as sid2:
        keep2 = b.scene(sid2)
        raises(lambda: update(sid2, {"purpose": "몰래 수정"}), err, "APPROVED 편집")
        eq(b.scene(sid2), keep2, "APPROVED 장면이 바뀜")


@test("unit", "U10 set_prompt(fix_anchors) — 대소문자만 다른 앵커도 원문으로 되돌려 A6 통과")
def u10(b: Box):
    """외부 이미지 AI 는 프롬프트를 소문자로 정규화해 돌려주는 일이 흔하다.

    검사기 A6 는 대소문자를 구분하므로, 보정이 소문자 비교로 '빠진 것 없음' 이라고
    판정하면 정확히 필요한 순간에 아무 일도 하지 않는다(A6 FAIL).
    """
    so = b.mod("scene_ops")
    anchor_c, anchor_l = b.anchors()
    with fresh_scene(b) as sid:
        lower = f"medium shot, {anchor_c.lower()}, {anchor_l.lower()}, cel shading"
        sc = b.scene(sid)
        eq(sorted(so.missing_anchors(sc, lower)), sorted([anchor_c, anchor_l]),
           "소문자 앵커를 '들어 있음' 으로 오판(A6 와 판정이 갈림)")
        res = so.set_prompt(sid, lower, fix_anchors=True)
        saved = b.scene(sid)["prompt"]["grok_output"]
        has(saved, anchor_c, "인물 앵커 원문")
        has(saved, anchor_l, "장소 앵커 원문")
        eq(saved.lower().count(anchor_c.lower()), 1, "같은 인물 묘사가 두 번(화면에 사람이 늘어난다)")
        eq(res["checker_pass"], True, f"A6 검사 — {res.get('fails', '')[:200]}")
        eq(b.scene(sid)["status"], "PROMPT", "status")
        # 이미 원문 그대로면 손대지 않는다(멱등)
        again = so.set_prompt(sid, saved, fix_anchors=True)
        eq(b.scene(sid)["prompt"]["grok_output"], saved, "멱등하지 않음")
        eq(again["checker_pass"], True, "재저장 후 검사")


# 다른 프로세스에서 같은 장면을 선점해 보는 조각 — 네트워크·유료 API 는 건드리지 않는다.
_CLAIM_PY = (
    "import sys\n"
    "sys.path.insert(0, 'tools')\n"
    "import gen_jobs\n"
    "try:\n"
    "    gen_jobs.claim(sys.argv[1])\n"
    "    print('CLAIMED')\n"
    "    if len(sys.argv) > 2 and sys.argv[2] == 'crash':\n"
    "        import os; sys.stdout.flush(); os._exit(0)\n"     # 좌초 잠금을 남기고 급사
    "    gen_jobs.release(sys.argv[1])\n"
    "except Exception as exc:\n"
    "    print('REJECTED', type(exc).__name__)\n"
)


@test("unit", "U11 gen_jobs — 프로세스 경계에서도 같은 장면 선점 거부 · 좌초 잠금은 회수")
def u11(b: Box):
    """중복 과금의 마지막 구멍은 **서버 밖**이다. 웹이 굽고 있는 장면을 CLI 로 한 번 더
    돌리면 메모리 표시로는 막을 수 없다 — 표시가 프로세스마다 따로 있기 때문이다.
    그래서 여기서는 진짜 별도 프로세스를 띄워 확인한다(MakeFun 호출은 하지 않는다 —
    선점만).

    되찾는 규칙도 같은 자리에서 본다: 주인이 **죽었으면 즉시**, 주인을 믿을 수 없으면
    **STALE_SEC 뒤에**. 두 겹의 경계가 무너지면 한쪽은 20분 잠김이고 다른 쪽은 중복 과금이다.
    """
    gj = need_mod(b, "gen_jobs")
    lock_dir = getattr(gj, "LOCK_DIR", None)
    stale_sec = float(getattr(gj, "STALE_SEC", 1200) or 1200)

    def claim_in_subprocess(sid: str, crash: bool = False) -> str:
        rc, out = b.run("-c", _CLAIM_PY, sid, *(["crash"] if crash else []))
        ok("CLAIMED" in out or "REJECTED" in out,
           f"별도 프로세스가 답하지 않음(rc={rc}) — {out[:300]}")
        return "REJECTED" if "REJECTED" in out else "CLAIMED"

    held, other = "SCENE-921", "SCENE-922"
    try:
        # 1) 이 프로세스가 잡은 장면 → 다른 프로세스는 거절당해야 한다
        gj.claim(held)
        got = claim_in_subprocess(held)
        if got == "CLAIMED":
            if lock_dir is None:
                raise Gap("gen_jobs 선점이 아직 메모리 전용 — 서버 밖 CLI 가 같은 장면을 또 굽는다"
                          "(같은 이미지에 두 번 과금)")
            raise Failed("잠금 파일이 있는데도 다른 프로세스가 같은 장면을 선점함")
        gj.release(held)
        eq(claim_in_subprocess(held), "CLAIMED", "해제한 장면을 다른 프로세스가 잡지 못함")

        # 2) 급사한 프로세스가 남긴 잠금 — **주인이 죽었으므로 즉시** 회수된다.
        #    예전에는 여기서 REJECTED 를 기대했다. 그 기대가 곧 결함이었다: 렌더를 죽인
        #    사람이 같은 장면을 20분 기다려야 했고, 실제로 그 잠금이 게이트를 한 번 깼다.
        #    지금은 잠금에 적힌 pid 가 이 기기에서 죽었음이 확실하면 그 자리에서 열어 준다.
        eq(claim_in_subprocess(other, crash=True), "CLAIMED", "선점 실패")
        locks = sorted(Path(lock_dir).glob("*")) if lock_dir else []
        stale = [p for p in locks if other in p.name]
        ok(stale, f"급사가 남긴 잠금 파일을 찾지 못함: {[p.name for p in locks]}")
        eq(claim_in_subprocess(other), "CLAIMED",
           "주인이 죽은 잠금이 아직도 다음 프로세스를 막는다 — 20분 잠김이 그대로다")

        # 3) 시각 규칙은 그대로 살아 있다 — pid 를 믿을 수 없는 잠금(다른 기기·옛 형식)이
        #    남는 자리다. 살아 있는 동안은 막고, STALE_SEC 을 넘기면 회수한다.
        foreign = {"scene_id": other, "pid": 1, "host": "다른기기",
                   "label": "남의 기기 렌더", "token": "zz"}
        path = Path(lock_dir) / f"{other}.lock"
        path.write_text(json.dumps(foreign), encoding="utf-8")
        eq(claim_in_subprocess(other), "REJECTED",
           "pid 를 믿을 수 없는 잠금을 그냥 열었다 — 남의 렌더 위에 두 번 굽는다")
        old = time.time() - stale_sec - 60
        os.utime(path, (old, old))
        eq(claim_in_subprocess(other), "CLAIMED",
           f"{stale_sec / 60:.0f}분 넘게 방치된 좌초 잠금이 회수되지 않음(영구 잠금)")
    finally:
        with contextlib.suppress(Exception):
            gj.release(held)
        for sid in (held, other):
            with contextlib.suppress(Exception):
                b.run("-c", "import sys\nsys.path.insert(0,'tools')\nimport gen_jobs\n"
                            "gen_jobs.release(sys.argv[1])\n", sid)
        if lock_dir:
            for p in Path(lock_dir).glob("*"):
                if held in p.name or other in p.name:
                    with contextlib.suppress(OSError):
                        p.unlink()


# 잠금을 잡은 채 **살아서 기다리는** 조각 — 주인이 살아 있는 동안은 회수되면 안 된다.
_HOLD_PY = (
    "import sys, time\n"
    "sys.path.insert(0, 'tools')\n"
    "import gen_jobs\n"
    "gen_jobs.claim(sys.argv[1])\n"
    "print('CLAIMED', flush=True)\n"
    "time.sleep(float(sys.argv[2]))\n"
)


def dead_pid() -> int:
    """확실히 끝난 프로세스의 pid — 생존 판정의 False 쪽을 재는 재료."""
    p = subprocess.Popen([PY, "-c", "pass"])
    p.wait()
    time.sleep(0.2)          # 종료 직후 핸들이 정리될 틈
    return p.pid


@test("unit", "U11b gen_jobs — 샌드박스 잠금은 샌드박스 안에서만(살아 있는 저장소를 잠그지 않는다)")
def u11b(b: Box):
    """selftest 는 사람이 실제로 쓰는 저장소 옆에서 돈다. 잠금 파일이 그 저장소의
    logs/gen_locks 에 떨어지면 검사 한 번이 사람의 장면을 최대 STALE_SEC(20분) 잠근다 —
    스튜디오에서 [생성]을 눌렀는데 "이미 생성 중입니다" 가 나오고, 원인이 될 프로세스는
    어디에도 없다.

    결과만 보면 예전에도 샌드박스 안에 떨어졌다. 다만 그건 Box.build 가 sys.path 를
    갈아끼운 **부수효과**였고(gen_jobs → import vn_core → 샌드박스 사본), 부수효과는
    계약이 아니다. 지금은 VN_GEN_LOCK_DIR 로 대놓고 지정하며, 여기서 그것을 지킨다.
    """
    gj = need_mod(b, "gen_jobs")
    lock_dir = getattr(gj, "LOCK_DIR", None)
    ok(lock_dir is not None, "gen_jobs 에 LOCK_DIR 이 없다 — 프로세스 경계 잠금이 사라졌다")
    box_root = Path(b.root).resolve()
    real_locks = (SRC / "logs" / "gen_locks").resolve()
    got = Path(lock_dir).resolve()
    ok(str(got).startswith(str(box_root)), f"샌드박스 잠금 폴더가 샌드박스 밖이다: {got}")
    ok(got != real_locks and not str(got).startswith(str(real_locks) + os.sep),
       f"샌드박스가 살아 있는 저장소에 잠금을 떨어뜨린다: {got}")

    # 말이 아니라 파일로 확인한다 — 실제로 잡아 보고 진짜 저장소 쪽 개수를 센다.
    before = sorted(q.name for q in real_locks.glob("*")) if real_locks.is_dir() else []
    sid = "SCENE-931"
    gj.claim(sid, "잠금 위치 검사")
    try:
        ok((Path(lock_dir) / f"{sid}.lock").exists(),
           f"샌드박스 안에 잠금 파일이 생기지 않음: {lock_dir}")
        after = sorted(q.name for q in real_locks.glob("*")) if real_locks.is_dir() else []
        eq(after, before,
           f"살아 있는 저장소에 잠금이 떨어졌다 — 늘어난 것: {sorted(set(after) - set(before))}")
    finally:
        with contextlib.suppress(Exception):
            gj.release(sid)

    # 하위 프로세스(b.run)도 같은 폴더를 봐야 한다 — 아니면 U11 의 교차 프로세스 검증이
    # 서로 다른 폴더를 보며 통과해 버린다(가짜 초록불).
    rc, out = b.run("-c", "import sys\nsys.path.insert(0, 'tools')\nimport gen_jobs\n"
                          "print(gen_jobs.LOCK_DIR)\n")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    child = Path(lines[-1].strip()).resolve() if lines else None
    eq(child, got, f"하위 프로세스가 다른 잠금 폴더를 본다(rc={rc}) — {out[:200]}")


@test("unit", "U11c gen_jobs — 주인이 죽은 잠금은 즉시 회수 · 살아 있으면 그대로 거절(중복 과금)")
def u11c(b: Box):
    """좌초 잠금을 되찾는 규칙이 '20분 기다리기' 하나뿐이면, 렌더를 죽인 사람은 같은 장면을
    20분 동안 다시 그릴 수 없다(실제로 그렇게 게이트가 한 번 깨졌다). 그래서 pid 겹을 앞에
    두되 **확실할 때만** 회수한다. 여기서 재는 것은 세 방향이다.

      (1) 주인 프로세스가 죽었다 → mtime 을 건드리지 않고도 곧바로 다시 잡힌다
      (2) 주인 프로세스가 살아 있다 → 여전히 거절된다 — 이게 중복 과금 방지의 본체다
      (3) pid 를 믿을 수 없는 잠금(옛 형식·다른 기기) → (1) 로 새지 않고 시각 규칙에 남는다

    (3) 이 특히 중요하다. 남의 기기에서 적힌 pid 번호가 우연히 내 기기에서 비어 있다는
    이유로 잠금을 열면, 새 규칙이 막으려던 바로 그 사고(같은 이미지 2회 과금)를 만든다.
    """
    gj = need_mod(b, "gen_jobs")
    err = getattr(gj, "VNError", RuntimeError)
    lock_dir = Path(need_attr(gj, "LOCK_DIR", "프로세스 경계 잠금 폴더"))
    alive = need_attr(gj, "_pid_alive", "pid 생존 판정 — 죽은 잠금을 즉시 회수하는 근거")
    host = getattr(gj, "_HOST", None)
    ok(host, "잠금에 기기 이름이 없다 — pid 판정을 안전하게 할 수 없다")
    stale_sec = float(getattr(gj, "STALE_SEC", 1200) or 1200)

    # 판정 함수 자체 — 확실할 때만 답하고, 모르면 None 이어야 한다.
    eq(alive(os.getpid()), True, "자기 자신을 살아 있다고 보지 못한다")
    gone = dead_pid()
    eq(alive(gone), False, f"확실히 죽은 pid {gone} 를 죽었다고 판정하지 못한다")

    held, foreign = "SCENE-941", "SCENE-942"
    lock_dir.mkdir(parents=True, exist_ok=True)

    def write_lock(sid: str, info: dict, age: float = 0.0) -> None:
        path = lock_dir / f"{sid}.lock"
        path.write_text(json.dumps(info), encoding="utf-8")
        if age:
            t = time.time() - age
            os.utime(path, (t, t))

    try:
        # (1) 이 기기의 죽은 pid → 방금 찍힌 잠금이라도 즉시 회수된다
        write_lock(held, {"scene_id": held, "pid": gone, "host": host,
                          "label": "죽은 렌더", "token": "zz"})
        gj.claim(held)                       # 여기서 막히면 20분 잠김이 그대로다
        eq(gj.status(held)["running"], True, "회수 뒤 선점이 잡히지 않음")
        gj.release(held)

        # (2) 살아 있는 주인 → 여전히 거절
        proc = subprocess.Popen([PY, "-c", _HOLD_PY, held, "60"], cwd=b.root, env=b.env,
                                stdout=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace")
        try:
            line = (proc.stdout.readline() or "").strip()
            ok(line == "CLAIMED", f"살아 있는 잠금을 만들지 못함 — {line!r}")
            raises(lambda: gj.claim(held), err,
                   "주인이 살아 있는 잠금을 회수했다 — 같은 이미지에 두 번 과금된다")
            eq(gj.status(held)["running"], True, "살아 있는 남의 작업이 화면에 안 보인다")
        finally:
            proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=10)
        # 죽인 직후 — 시각 겹은 아직 막지만(방금 찍힌 mtime) pid 겹이 곧바로 열어 줘야 한다
        for _ in range(60):
            if alive(proc.pid) is False:
                break
            time.sleep(0.1)
        gj.claim(held)
        gj.release(held)

        # (3) pid 를 믿을 수 없는 잠금은 시각 규칙에 남는다 — 새로 뚫린 구멍이 없어야 한다
        for label, info in (("옛 형식(host 없음)", {"scene_id": foreign, "pid": gone}),
                            ("다른 기기", {"scene_id": foreign, "pid": gone,
                                          "host": str(host) + "-다른기기"})):
            write_lock(foreign, info)
            raises(lambda: gj.claim(foreign), err,
                   f"{label} 잠금을 pid 만 보고 회수했다 — 남의 렌더를 덮어쓴다")
            write_lock(foreign, info, age=stale_sec + 60)
            gj.claim(foreign)                # 늙으면 예전처럼 회수된다
            gj.release(foreign)
    finally:
        for sid in (held, foreign):
            with contextlib.suppress(Exception):
                gj.release(sid)
            with contextlib.suppress(OSError):
                (lock_dir / f"{sid}.lock").unlink()


@test("unit", "U11d gen_jobs — 막 끝난 작업을 '다른 곳에서 생성 중' 이라 하지 않는다(해제 순서)")
def u11d(b: Box):
    """CF07 을 이따금 깨뜨리던 자리. release() 가 _OWNED 에서 먼저 내리고 잠금 파일을
    나중에 지우면, 그 사이 한 순간 status() 가 **자기 pid 를 가리키며** "다른 곳에서
    생성 중입니다" 라고 답한다. 화면(_settle·studio.js)은 그걸 보고 끝난 작업을 계속
    도는 것으로 읽어, 사용자는 완료 문구를 영영 못 본다.

    여기서는 그 창을 손으로 열어 본다 — 파일이 아직 있고 메모리는 끝났다고 하는 상태를
    만들고, status() 가 무엇이라 답하는지 묻는다.
    """
    gj = need_mod(b, "gen_jobs")
    lock_dir = Path(need_attr(gj, "LOCK_DIR", "프로세스 경계 잠금 폴더"))
    sid = "SCENE-961"
    gj.claim(sid, "생성")
    try:
        gj.note(sid, "ComfyUI 생성 중… 3초 경과")
        lock = lock_dir / f"{sid}.lock"
        ok(lock.exists(), "잠금 파일이 만들어지지 않음 — 이 검사가 볼 것이 없다")

        # release() 가 하던 순서를 그대로 흉내 낸다: 메모리를 끝으로 바꾸고 소유만 내린다.
        with gj._LOCK:
            gj._JOBS[sid] = {"running": False, "message": "완료 — 후보 1장", "ts": time.time()}
            token = gj._OWNED.pop(sid, "")
        ok(lock.exists(), "흉내를 내려면 잠금 파일이 남아 있어야 한다")
        st = gj.status(sid)
        eq(st["running"], False,
           f"막 끝난 작업이 아직 도는 것으로 보고됨 — {st.get('message', '')}")
        hasnt(str(st.get("message", "")), "다른 곳",
              "내 pid 가 적힌 잠금을 '다른 곳' 이라고 말한다")
        has(str(st.get("message", "")), "완료", f"완료 문구가 사라짐 — {st}")
        with contextlib.suppress(Exception):
            gj._release_file(sid, token)

        # 그리고 진짜 release() 를 지나면 파일도 소유 표시도 남지 않아야 한다
        gj.claim(sid, "생성")
        gj.release(sid, "완료 — 후보 2장")
        ok(not lock.exists(), "release 뒤에도 잠금 파일이 남음(다음 생성이 막힌다)")
        eq(gj.status(sid)["running"], False, "release 뒤에도 도는 것으로 보고됨")
        has(gj.status(sid)["message"], "완료", "release 가 남긴 문구")

        # **해제 순서 자체를 잠근다** — 파일이 먼저, 메모리 표시가 나중. 그 반대이면
        # "끝났다" 고 답해 놓고 바로 이어지는 claim() 이 내 pid 를 가리키며 거절한다.
        seen = {}
        real = gj._release_file

        def watching(s, token):
            with gj._LOCK:
                seen["running_when_file_goes"] = bool((gj._JOBS.get(s) or {}).get("running"))
                seen["owned_when_file_goes"] = s in gj._OWNED
            return real(s, token)

        gj.claim(sid, "생성")
        with patched(gj, "_release_file", watching):
            gj.release(sid, "완료 — 후보 1장")
        eq(seen.get("running_when_file_goes"), True,
           "잠금 파일을 지우기 전에 이미 '끝남' 으로 바뀌어 있다 — status 와 claim 이 어긋나는 창")
        eq(seen.get("owned_when_file_goes"), True,
           "소유 표시를 먼저 내렸다 — 그 창에서 내 잠금이 남의 것으로 보인다")
        gj.claim(sid, "생성")          # 끝난 직후 다시 잡는 것이 실제 사용 흐름이다
        gj.release(sid, "완료")

        # 안전판: 내 pid 가 적혔는데 내 소유 표시가 없는 잠금(놓다 만 잔해)은 회수한다.
        # status() 는 이미 '내 pid 면 다른 곳이 아니다' 를 안다 — 두 층이 같은 규칙을 봐야 한다.
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"scene_id": sid, "pid": os.getpid(), "host": gj._HOST,
                                    "label": "생성", "token": "남의토큰"}), encoding="utf-8")
        eq(gj.status(sid).get("running"), False, "내 pid 잠금을 '다른 곳' 으로 읽었다")
        gj.claim(sid, "생성")          # 여기서 VNError 가 나면 화면과 서버가 서로 다른 말을 한다
        gj.release(sid, "완료")
    finally:
        with contextlib.suppress(Exception):
            gj.release(sid)
        with contextlib.suppress(OSError):
            (lock_dir / f"{sid}.lock").unlink()


def str_consts(b: Box, mod: str) -> list[str]:
    """모듈의 **문자열 리터럴**(독스트링 제외). 설명문과 실제로 모델에 가는 문장을 가른다."""
    tree = tool_ast(b, mod)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if getattr(node, "body", None) else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docs.add(id(first.value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


@test("unit", "U12 전송 계층(local_llm)에 모델 프롬프트 문자열 0 — 조립은 prompt_build 담당")
def u12(b: Box):
    """local_llm 은 '서버에 붙어 글자를 받아 오는' 계층이다. 여기에 프롬프트 문장이 한 줄이라도
    남으면 같은 문구가 두 벌이 되고(prompt_build 와), 조용히 갈린 쪽이 사용자 화면에 나온다.

    예전 이 자리는 '옛 이름(local_llm.persona_prompt)이 살아 있는가' 를 계약으로 검사했다.
    그 재수출이 prompt_build → local_llm → prompt_build 고리를 만들던 마지막 조각이라
    이번 라운드에 걷어냈다 — 원래 지키려던 것(문구가 한 벌인가)으로 검사를 옮긴다.
    """
    llm = b.mod("local_llm")
    pb = b.mod("prompt_build")
    persona = need_attr(pb, "persona_prompt", "페르소나 프롬프트 조립의 단일 출처")
    sysmsg, meta = persona()
    ok(isinstance(sysmsg, str) and sysmsg.strip(), "정본이 빈 페르소나를 돌려줌")
    ok(bool(meta.get("name")), "인물 이름")
    has(sysmsg, meta["name"], "페르소나에 이름이 반영되지 않음")

    # (1) 모델 메시지 리터럴({"role":…, "content":"…"})이 전송 계층에 없다 — L04 와 같은 검사
    bad = []
    for node in ast.walk(tool_ast(b, "local_llm")):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if not {"role", "content"} <= keys:
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant) and k.value == "content"
                    and isinstance(v, ast.Constant) and str(v.value).strip()):
                bad.append(f"local_llm.py:{node.lineno} {str(v.value)[:60]!r}")
    eq(bad, [], "전송 계층이 모델 메시지 문장을 직접 들고 있음")

    # (2) 프롬프트 조각이 문자열로 복사되지도 않았다(독스트링의 '무엇을 옮겼다' 설명은 제외)
    said = "\n".join(str_consts(b, "local_llm"))
    for marker in ("[말투 규칙]", "[관계]", "1인칭", "SCENES_JSON_ONLY", "NEGATIVE_PROMPT",
                   "[사진", "너는 '"):
        eq(said.count(marker), 0, f"프롬프트 조각 {marker!r} 이 local_llm 으로 복사됨")

    # (3) 조립 함수 자체가 남아 있지 않다 — 통로로라도 남으면 import 고리가 되살아난다
    for gone in ("persona_prompt", "resolve_photos", "album_list", "memory_digest",
                 "story_system_message", "compose_image_prompt"):
        ok(not hasattr(llm, gone),
           f"local_llm.{gone} 가 아직 있음 — 프롬프트 계층의 이름은 prompt_build 에만 둔다")
    where = tool_imports(b, "local_llm").get("prompt_build", "없음")
    ok(where in ("없음", "CLI 진입점"),      # 이 파일의 CLI(main)가 페르소나를 시연하는 것은 예외
       f"local_llm 이 라이브러리 경로({where})에서 prompt_build 를 부름 — 마지막 import 고리")

    # (4) 사라진 게 아니라 옮겨졌다 — 정본에 그 문구가 실제로 있다
    moved = "\n".join(str_consts(b, "prompt_build"))
    for marker in ("[말투 규칙]", "[관계]"):
        ok(marker in moved, f"이관처(prompt_build)에 {marker!r} 이 없음 — 문구가 사라졌다")


@test("unit", "U13 vn_core — 장면 훑기·선택본·완성 판정의 단일 출처(손상 파일·승인 게이트)")
def u13(b: Box):
    """'감상본과 인화 목록에 다른 컷이 실린다'는 사고의 뿌리는 이 판정이 여덟 벌이었다는 것이다.
    판정을 하나로 모은 뒤에는 **그 하나**를 잠근다 — 손상 파일 관용, 승인 게이트, --all 의 의미."""
    vc = b.mod("vn_core")
    it = need_attr(vc, "iter_scenes", "장면 훑기의 단일 출처")
    sel = need_attr(vc, "selected_of", "선택 이미지 판독")
    deliv = need_attr(vc, "is_deliverable", "감상본·인화에 실릴 컷의 정의")

    eq(sel({}), "", "assets 가 없는 장면")
    eq(sel({"assets": None}), "", "assets 가 dict 가 아닌 장면")
    eq(sel({"assets": {"selected_image": None}}), "", "selected_image=null")
    eq(sel({"assets": {"selected_image": "   "}}), "", "공백만 있는 경로를 '이미지 있음' 으로 셈")
    eq(sel({"assets": {"selected_image": " images/raw/a.png "}}), "images/raw/a.png", "앞뒤 공백 정리")
    eq(sel("장면이 아님"), "", "dict 가 아닌 입력")

    done = {"status": "APPROVED", "assets": {"selected_image": "images/raw/a.png"}}
    draft = {"status": "PROMPT", "assets": {"selected_image": "images/raw/a.png"}}
    ok(deliv(done), "승인 + 선택본인데 완성본이 아님")
    ok(not deliv({"status": "APPROVED"}), "선택본 없는 승인 장면이 완성본으로 셈")
    ok(not deliv(draft), "승인 전 컷이 감상본·인화에 실림(사람 승인 게이트 우회)")
    ok(deliv(draft, include_all=True), "--all 인데 빠짐")
    ok(not deliv({"status": "APPROVED", "assets": {}}, include_all=True),
       "--all 이어도 이미지가 없으면 실을 것이 없다")
    ok(not deliv(None) and not deliv([]), "장면이 dict 가 아닐 때 크래시·오판")

    with approved_scene(b) as sid:
        pairs = it()
        ok(all(isinstance(p, Path) and isinstance(s, dict) for p, s in pairs), "(경로, 장면) 형태")
        ok(any(p.stem == sid for p, _s in pairs), "만든 장면이 훑기에 없음")
        ok(any(deliv(s) for _p, s in pairs), "승인 장면이 완성본 판정을 받지 못함")
        with fresh_scene(b) as broken, corrupted(b.scene_path(broken)):
            got = it()
            ok(all(p.stem != broken for p, _s in got), "손상 장면이 관대 훑기에 섞임")
            ok(any(p.stem == sid for p, _s in got), "손상 파일 하나에 전체 훑기가 죽음")
            raises(lambda: it(strict=True), Exception, "strict 인데 손상 파일을 그냥 지나침")


@test("unit", "U14 scene_ops.create_scene — 생성은 한 곳 · 손상 파일이 있어도 덮어쓰지 않는다")
def u14(b: Box):
    """생성이 세 벌이던 시절, 그중 하나(대화→장면)에는 존재 확인이 없었다. 손상된 장면 파일이
    하나 있으면 같은 번호가 다시 뽑혀 **기존 장면을 조용히 덮어썼다** — 되돌릴 수 없는 사고다.
    여기서는 그 하나를 잠그고, 세 경로가 정말 그 하나를 거치는지 소스로 확인한다."""
    so = b.mod("scene_ops")
    vc = b.mod("vn_core")
    err = getattr(so, "VNError", RuntimeError)
    create = need_attr(so, "create_scene", "장면 생성의 유일한 구현")
    made: list[str] = []
    stray = None
    try:
        base = read_json(b.scene_path("SCENE-001"))
        sc = create()
        made.append(sc["scene_id"])
        ok(vc.is_scene_id(sc["scene_id"]), f"형식이 틀린 id — {sc['scene_id']!r}")
        ok(b.scene_path(sc["scene_id"]).exists(), "돌려줬는데 파일이 없음")
        eq(b.scene(sc["scene_id"])["scene_id"], sc["scene_id"], "파일명과 scene_id 불일치(A2)")
        eq(sc["status"], "SCENE_PLAN", "새 장면 시작 상태")
        eq(sc["review"]["human"], "PENDING", "승인 도장이 미리 찍혀 있음")
        eq(sc["assets"]["selected_image"], "", "선택 이미지가 미리 지정돼 있음")

        # 이미 있는 번호는 덮어쓰지 않는다(원본 소실 방지)
        raises(lambda: create("SCENE-001"), err, "존재하는 장면 번호로 생성")
        eq(read_json(b.scene_path("SCENE-001")), base, "거부됐는데 기존 장면이 바뀜")
        raises(lambda: create("SCENE-1"), err, "형식이 틀린 id")
        raises(lambda: create("../etc"), err, "경로 탈출 id")

        # **손상된 장면 파일도 '존재하는 번호'다** — 읽지 못한다고 그 자리를 재사용하면 덮어쓴다
        nxt, _order = b.next_ids()
        stray = b.scene_path(nxt)
        stray.write_text('[{"scene_id":"BROKEN"}]', encoding="utf-8")
        raw = stray.read_text(encoding="utf-8")
        sc2 = create()
        made.append(sc2["scene_id"])
        ok(sc2["scene_id"] != nxt, f"손상 파일의 번호({nxt})를 다시 씀")
        eq(stray.read_text(encoding="utf-8"), raw, "손상된 장면 파일을 덮어씀(원본 소실)")
        raises(lambda: create(nxt), err, "손상 파일이 있는 번호에 덮어쓰기")
        stray.unlink()
        stray = None

        # 내용·화 승계
        sc3 = create(fields={"purpose": "생성 경로 확인", "episode": 3})
        made.append(sc3["scene_id"])
        eq(b.scene(sc3["scene_id"])["purpose"], "생성 경로 확인", "fields 병합")
        eq(sc3.get("episode"), 3, "episode 지정")
        sc4 = create()
        made.append(sc4["scene_id"])
        eq(sc4.get("episode"), 3, "마지막 장면의 화를 승계하지 않음(감상본 화 선택에서 빠진다)")
        sc5 = create(episode=None)
        made.append(sc5["scene_id"])
        ok("episode" not in sc5, "화를 쓰지 않는 작품인데 episode 가 붙음")
        # 승인 게이트·자산은 생성으로도 만들 수 없다
        raises(lambda: create(fields={"status": "APPROVED"}), err, "APPROVED 로 태어나기")
        raises(lambda: create(fields={"review": {"human": "PASS"}}), err, "검수 결과를 갖고 태어나기")
        raises(lambda: create(fields={"assets": {"selected_image": "x.png"}}), err, "자산을 갖고 태어나기")
        raises(lambda: create(fields={"없는필드": 1}), err, "화이트리스트 밖 필드")
        rc, out = b.checker()
        eq(rc, 0, f"create_scene 이 만든 장면들이 검사기를 통과하지 못함 — "
                  f"{[l for l in out.splitlines() if 'FAIL' in l][:3]}")
    finally:
        if stray is not None:
            with contextlib.suppress(OSError):
                stray.unlink()
        for sid in reversed(made):      # LIFO — scene_order 1..N 연속을 유지한 채 되돌린다
            with contextlib.suppress(OSError):
                b.scene_path(sid).unlink()

    # 세 생성 경로가 전부 그 하나를 거치는가(원문 문자열이 아니라 실제 호출로 확인)
    for mod, fn in (("advance_scene", "cmd_new"), ("vn_compose", "_create_scenes_from_items"),
                    ("vn_compose", "scene_from_talk")):
        if not func_body(b, mod, fn):
            raise Gap(f"{mod}.{fn} 이 없음 — 생성 경로의 이름이 바뀌었다(검사 앵커도 함께 고칠 것)")
        calls = func_calls(b, mod, fn)
        ok(any(c.split(".")[-1] == "create_scene" for c in calls),
           f"{mod}.{fn} 이 create_scene 을 거치지 않음 — 부르는 것: {sorted(calls)}")
        for direct in ("adv.save", "save", "atomic_write_json", "vn_core.atomic_write_json"):
            ok(direct not in calls, f"{mod}.{fn} 이 장면 파일을 직접 씀({direct}) — 두 번째 생성 경로")


@test("unit", "U15 scene_ops — 생성 task 기록과 승인 잠금 문구가 각각 한 곳에서만 나온다")
def u15(b: Box):
    """task id 는 '이미 지출한 돈'의 영수증이다 — 다운로드만 실패했을 때 재생성(재과금) 없이
    다시 받아오는 유일한 근거라, 쓰기 경로가 둘로 갈려 한쪽이 덮어쓰면 그대로 손실이다.
    승인 잠금 문구도 한 벌이어야 한다(화면마다 다음에 할 일이 보였다 안 보였다 하던 자리)."""
    so = b.mod("scene_ops")
    err = getattr(so, "VNError", RuntimeError)
    rec = need_attr(so, "record_generation_tasks", "생성 task 기록의 유일한 통로")
    mutable = need_attr(so, "assert_mutable", "승인 잠금 사전 점검(문구 한 벌)")
    cap = int(getattr(so, "GEN_TASKS_MAX", 20))
    with fresh_scene(b) as sid:
        before = b.scene(sid)
        res = rec(sid, ["task_a", "task_b"], {"width": 832, "height": 1248})
        sc = b.scene(sid)
        tasks = (sc.get("assets") or {}).get("makefun_tasks")
        ok(isinstance(tasks, list) and len(tasks) == 2, f"기록 결과 {tasks}")
        eq([t.get("task_id") for t in tasks], ["task_a", "task_b"], "task id 기록")
        eq(res.get("count"), 2, f"반환 요약 — {res}")
        eq(sc["status"], before["status"], "기록이 장면 상태를 움직임")
        eq(sc["assets"]["raw_images"], before["assets"]["raw_images"], "기록이 후보 목록을 건드림")
        rec(sid, ["task_a"])                     # 같은 id 는 두 번 쌓지 않는다
        eq(len(b.scene(sid)["assets"]["makefun_tasks"]), 2, "중복 기록")
        rec(sid, [f"t{i}" for i in range(cap + 5)])
        eq(len(b.scene(sid)["assets"]["makefun_tasks"]), cap, f"보존 상한({cap}) 초과")
        got = mutable(sid, "이미지를 생성하려면")
        eq(got.get("scene_id"), sid, "assert_mutable 이 장면을 돌려주지 않음")
        raises(lambda: rec("../etc", ["x"]), err, "장면 ID 형식 검증")
        raises(lambda: rec("SCENE-404", ["x"]), err, "없는 장면")
    with cli_scene(b, "APPROVED") as sid2:
        e = raises(lambda: mutable(sid2, "이미지를 생성하려면"), err, "APPROVED 인데 통과")
        has(str(e), "APPROVED", "무엇 때문에 막혔는지")
        has(str(e), "이미지를 생성하려면", "무엇을 하려다 막혔는지")
        has(str(e), "revise", "다음에 할 일(revise) 안내")
    # 생성 클라이언트는 장면 파일을 직접 쓰지 않는다 — 통로는 scene_ops 하나다
    calls = func_calls(b, "makefun_client", "record_tasks")
    ok(calls, "makefun_client.record_tasks 가 없음 — 생성 기록 경로의 이름이 바뀌었다")
    ok(any(c.split(".")[-1] == "record_generation_tasks" for c in calls),
       f"생성 클라이언트가 scene_ops 를 거치지 않음 — 부르는 것: {sorted(calls)}")
    for direct in ("atomic_write_json", "vn_core.atomic_write_json", "_save"):
        ok(direct not in calls, f"생성 클라이언트가 장면 파일을 직접 씀({direct})")


@test("unit", "U16 console_guard — 리다이렉트된 출력은 UTF-8(로그 파일에 cp949 가 섞이지 않게)")
def u16(b: Box):
    """``start_studio.ps1 > log.txt`` 처럼 출력을 파일로 돌리면 파이썬은 로캘 인코딩으로 쓴다 —
    한국어 윈도우면 cp949 다. 같은 파일에 PowerShell 이 UTF-8 로 쓴 줄과 섞이면 한쪽이 반드시
    깨진다(실제로 '웹 스튜디오 주소' 가 '?? ??Ʃ??? ????' 로 남았다). 이 저장소의 파일은 전부
    UTF-8 이므로, 콘솔(tty)이 아닌 스트림은 UTF-8 로 맞춘다(콘솔은 코드페이지를 그대로 둔다).
    """
    korean = "웹 스튜디오 주소"
    out = b.root / "_u16_stdout.txt"
    env = {k: v for k, v in b.env.items() if k != "PYTHONIOENCODING"}
    env["PYTHONUTF8"] = "0"          # UTF-8 모드로 통과해 버리지 않게 로캘 인코딩을 강제한다
    code = ("import sys; sys.path.insert(0, 'tools'); import vn_core; "
            f"print({ascii(korean)}, sys.stdout.encoding)")
    try:
        with out.open("wb") as fh:                 # 파이프가 아니라 **파일**로 — 실제 사고와 같은 모양
            proc = subprocess.run([PY, "-c", code], cwd=b.root, stdout=fh,
                                  stderr=subprocess.PIPE, env=env)
        eq(proc.returncode, 0, f"자식 프로세스 실패 — {proc.stderr.decode('utf-8', 'replace')[:300]}")
        raw = out.read_bytes()
        text = raw.decode("utf-8", "replace")
        eq(text.count("�"), 0, f"UTF-8 로 읽을 수 없는 바이트가 섞임 — {raw[:48]!r}")
        has(text, korean, f"한글이 UTF-8 로 왕복하지 않음 — {raw[:48]!r}")
        has(text.lower(), "utf-8", f"리다이렉트된 stdout 이 UTF-8 이 아님 — {text.strip()!r}")
    finally:
        out.unlink(missing_ok=True)


# 실측 재료 — Qwen3.6-35B-A3B(노트북 llama.cpp)에 같은 지시문을 7번 보내 받은 **세 가지 모양**.
# 지시문은 "다른 말 없이 JSON 배열만" 이라고 못박지만 배열로 온 것은 3/7 뿐이었다.
_SCENE_A = ('{"order":1,"purpose":"도입","action_beat":"창밖","emotion":"설렘","time":"오후",'
            '"location_id":"LOC-001","camera":{"shot":"wide","angle":"eye-level",'
            '"framing":"two-shot","focus":"face"},'
            '"dialogue":[{"speaker_id":"CHAR-001","text":"안녕"},'
            '{"speaker_id":"CHAR-002","text":"(심장이 뛴다)"}],"image_prompt":"wide shot"}')
_SCENE_B = _SCENE_A.replace('"order":1', '"order":2').replace("도입", "전개")


@test("unit", "U27 장면 구성 응답 — 배열이 아니어도 읽고, 대사 줄을 장면으로 저장하지 않는다")
def u27(b: Box):
    """실제 모델이 돌려주는 모양은 세 가지다(실측 7회): ``[...]`` 배열 3 · ``{"scenes":[...]}``
    포장 2 · **배열 없이 객체만 줄줄이** 2. 옛 추출기는 ``find("[")``~``rfind("]")`` 로 잘랐다.

    세 번째 모양에서 그 방식이 집는 첫 ``[`` 는 첫 장면 안의 ``"dialogue": [`` 다. 운이 나쁘면
    터지고(JSONDecodeError), **운이 좋으면 파싱에 성공한다** — 그리고 대사 두 줄이 장면 두 개로
    저장된다. 화면에는 "2개 장면 생성 · 검사 통과" 만 떴다. 터지는 쪽보다 나쁜 고장이라
    여기서 둘 다 잠근다: 세 모양이 모두 읽히는 것과, 대사 줄이 절대 장면이 되지 않는 것.
    """
    vc = b.mod("vn_compose")
    shapes = {
        "배열": f"```json\n[{_SCENE_A},{_SCENE_B}]\n```",
        "포장": '앞말\n{"scenes": [' + _SCENE_A + "," + _SCENE_B + "]}\n뒷말",
        "객체나열": _SCENE_A + "\n\n" + _SCENE_B,
    }
    for label, text in shapes.items():
        items = vc._extract_json_array(text)
        eq(len(items), 2, f"{label} 모양에서 장면 수")
        eq([it.get("order") for it in items], [1, 2], f"{label} 모양에서 순서")
        for it in items:
            ok("speaker_id" not in it,
               f"{label} 모양에서 대사 줄이 장면으로 올라왔다 — {json.dumps(it, ensure_ascii=False)[:120]}")
            has(str(it.get("image_prompt", "")), "shot", f"{label} 모양에서 image_prompt")

    # 장면이 하나뿐이어도 그 하나로 읽힌다(옛 추출기는 여기서 대사 2줄을 돌려줬다).
    one = vc._extract_json_array(_SCENE_A)
    eq(len(one), 1, "객체 하나짜리 응답")
    ok("speaker_id" not in one[0], "객체 하나짜리 응답에서 대사 줄이 장면이 됐다")

    # JSON 이 아예 없으면 예전처럼 ValueError — 호출부의 재시도 분기가 그것으로 걸린다.
    raises(lambda: vc._extract_json_array("미안, 장면을 못 만들겠어."), ValueError, "JSON 없음")


@test("unit", "U31 사고 과정(<think>)은 화면에 닿지 않는다 — 네 기능이 지나는 한 곳에서 걷어낸다")
def u31(b: Box):
    """이 모델의 ChatML 템플릿은 판본에 따라 생성 프리픽스로 ``<think>`` 를 먼저 붙인다.
    그러면 **여는 태그 없이 ``</think>`` 로 시작하는 응답**이 온다 — 실측으로 받은 것이
    ``'</think>\\n\\nHello! How can I help'`` 였다. 그대로 두면 인물의 첫마디가 ``</think>``
    로 시작하고, 장면 JSON 앞에는 혼잣말이 붙는다.

    거르는 자리는 전송 계층 하나다. 네 기능이 모두 ``local_llm.chat`` 을 지나므로 화면마다
    따로 지울 이유가 없고, 따로 지우면 다음에 붙는 화면이 반드시 빠뜨린다.
    """
    ll = b.mod("local_llm")
    fn = need_attr(ll, "strip_reasoning", "<think> 제거")
    eq(fn("</think>\n\n안녕!"), "안녕!", "여는 태그 없이 닫는 태그만 온 응답(실측 모양)")
    eq(fn("<think>음… 뭐라 하지</think>\n오늘 뭐 해?"), "오늘 뭐 해?", "온전한 사고 블록")
    eq(fn("<think>a</think>앞<think>b</think>뒤"), "앞뒤", "블록이 여러 개")
    eq(fn('[{"order":1}]'), '[{"order":1}]', "태그가 없으면 한 글자도 바뀌지 않아야 한다")
    eq(fn(""), "", "빈 응답")


@test("unit", "U30 장면 구성 지시문이 인물의 말투를 싣는다 — 새 장면만 존댓말로 갈리지 않게")
def u30(b: Box):
    """대화 탭은 `profile.speech_style` 을 읽어 페르소나를 만드는데(prompt_build `[말투 규칙]`)
    장면 구성 지시문만 그 칸을 몰랐다. 실측: 반말로 말하는 인물이 새로 구성된 장면에서
    "미끄러질 뻔했네요... 고마워요" 라고 존댓말을 썼다 — 같은 작품의 기존 12장과 새 3장이
    말투부터 갈린다. 같은 데이터를 두 화면이 서로 다르게 보면 그 차이는 조용히 쌓인다.
    """
    vc = b.mod("vn_compose")
    style = "편한 반말. 기쁘면 말끝을 늘인다."
    with manifest_patch(b, lambda d: d["characters"][0].setdefault("profile", {})
                        .update({"speech_style": style})):
        ensure_storyline(b)
        text = vc.build_compose_instruction(2, False)
    has(text, style, "지시문이 인물의 말투를 싣지 않는다(장면 대사가 대화 탭과 갈린다)")
    has(text, "말투를 지킬 것", "말투를 지키라는 규칙이 없다 — 데이터만 있고 지시가 없다")


@test("unit", "U29 장면 구성도 앵커를 보정한다 — 자동 경로만 A6 에서 빨간불이지 않게")
def u29(b: Box):
    """지시문 1번은 "앵커 문구를 원문 그대로 포함하라" 다. 실측(장면 3개 구성)에서 모델은
    2개에서 **앵커 중간에 말을 끼워 넣었다** — "…Korean girl holding hands with boy, light
    brown semi-long hair…". 검사기 A6 는 원문 포함을 보므로 둘 다 FAIL 이고, 방금 만든
    작품이 저장소의 게이트에서 빨간불인 채로 태어난다.

    붙여넣기 경로는 이미 보정한다(스튜디오 [프롬프트 저장]의 '앵커 자동 보정' 은 기본
    켜짐). 같은 보정을 **자동 경로에도** 건다 — 두 경로가 같은 결과를 내야 사람이 어느
    길로 왔는지에 따라 손으로 고쳐야 하는지가 갈리지 않는다.
    """
    vc = b.mod("vn_compose")
    anchor_c, anchor_l = b.anchors()
    mf = b.manifest()
    cid = mf["characters"][0]["character_id"]
    lid = mf["locations"][0]["location_id"]
    # 모델이 실제로 한 짓: 앵커의 첫 조각 뒤에 제 말을 끼워 넣어 원문을 끊는다.
    broken = anchor_c.replace(", ", " holding hands with boy, ", 1)
    ok(anchor_c not in broken, "픽스처가 앵커를 끊지 못했다 — 이 검사가 무의미해진다")
    items = [{"order": 1, "purpose": "도입", "action_beat": "창밖", "emotion": "설렘",
              "time": "오후", "location_id": lid,
              "camera": {"shot": "wide", "angle": "eye-level", "framing": "", "focus": ""},
              "dialogue": [{"speaker_id": cid, "text": "안녕"}],
              "image_prompt": f"wide shot, {broken}, {anchor_l}, cel shading"}]
    res = vc.compose_from_json(json.dumps(items, ensure_ascii=False), force=True)
    sid = res["created"][0]
    saved = b.scene(sid)["prompt"]["grok_output"]
    has(saved, anchor_c, "자동 경로가 끊긴 인물 앵커를 원문으로 되돌리지 않는다(A6 FAIL)")
    has(saved, anchor_l, "장소 앵커 원문")
    eq(res.get("checker_pass"), True, f"자동 검사 — {res.get('checker', '')[:200]}")
    eq(res.get("fixed_anchors"), [sid], "보정했다는 사실을 결과에 남기지 않는다(화면이 말할 수 없다)")

    # 이미 원문 그대로면 손대지 않는다 — 보정이 없었다는 것도 결과에 남는다(멱등).
    items[0]["image_prompt"] = f"wide shot, {anchor_c}, {anchor_l}, cel shading"
    again = vc.compose_from_json(json.dumps(items, ensure_ascii=False), force=True)
    ok("fixed_anchors" not in again, f"손댈 것이 없는데 보정했다고 말한다 — {again.get('fixed_anchors')}")
    eq(again.get("checker_pass"), True, "재구성 후 검사")


@test("unit", "U28 장면 구성은 스트리밍으로 받는다 — 120초 상한이 '총 생성 시간' 이 되지 않게")
def u28(b: Box):
    """``local_llm.TIMEOUT`` 은 소켓 한 번의 상한이지 요청 전체의 상한이 아니다. 그런데
    비스트리밍이면 llama.cpp 는 답을 다 만들 때까지 한 바이트도 보내지 않으므로 **첫 recv 가
    생성 시간 전체를 기다린다** — 결국 120초가 총 상한이 된다.

    실측(Qwen3.6-35B-A3B · 13~14 tok/s): 장면 3개가 95~115초. 스튜디오 기본값 10개는
    4천 토큰이 넘어 5분 이상이므로 **언제나** 시간초과였다. 스트리밍이면 조각이 수십 ms
    마다 오므로 같은 120초가 '조각 사이의 침묵' 상한이 되고, 진짜로 멈춘 서버는 그대로
    걸린다. 숫자를 키우는 대신 받는 방식을 바꾼 것이라, 되돌아가면 조용히 다시 막힌다.
    """
    vc = b.mod("vn_compose")
    seen: dict = {}

    def fake_chat(messages, temperature=0.8, max_tokens=320, on_token=None, timeout=None):
        seen.update(on_token=on_token, max_tokens=max_tokens, timeout=timeout)
        return "[]"

    real = vc.local_llm.chat
    vc.local_llm.chat = fake_chat
    try:
        vc.orch_chat([{"role": "user", "content": "x"}])
    finally:
        vc.local_llm.chat = real
    ok(callable(seen.get("on_token")),
       "orch_chat 이 on_token 없이 부른다 — 비스트리밍이면 120초가 생성 시간 전체의 상한이 된다")
    eq(seen.get("max_tokens"), 8192, "장면 구성의 출력 상한")
    # 조립 자신은 줄을 서지 않는다(그게 줄을 세우는 쪽이다) — 기본 상한 그대로 간다.
    eq(seen.get("timeout"), None, "조립이 큰 상한을 쓴다 — 앞에 줄이 없는 쪽이다")


# ============================================================ 러너
GROUPS = ["meta", "arch", "pipeline", "template", "checker", "webapp", "auth", "makefun",
          "comfyui", "backup", "print", "viewer", "js", "ux", "security", "unit"]

# --list 에서 각 그룹이 무엇을 잠그는지 한 줄로 보여 준다(부분 실행을 고르기 쉽게).
GROUP_NOTE = {
    "meta": "자가진단 자신 — 필수 모듈·구문(가장 빠름)",
    "arch": "계층 규약을 소스로 강제(import 방향·상태 대입·프롬프트 위치·문서↔코드 상수)",
    "pipeline": "CLI 상태 전이 · 승인 게이트",
    "template": "templates/ 로 시작한 새 작품(사용자의 첫 5분)",
    "checker": "검사기가 '떨어뜨리는 능력'(부정 픽스처)",
    "webapp": "웹 스튜디오 라우트·잠금 (서버 기동)",
    "auth": "폰 접속 PIN·토큰",
    "makefun": "이미지 생성·업로드·확대·크레딧 클라이언트 (모의 · 실호출 0 · 과금 0)",
    "comfyui": "로컬 렌더 클라이언트·엔진 선택기·엔진 라우트 (모의 ComfyUI 서버 · GPU 0)",
    "backup": "스냅샷·복원·zip slip",
    "print": "인화 규격·마스터",
    "viewer": "감상본 데이터·분기",
    "js": "브라우저 코드 문법 + 주입 API 0",
    "ux": "폰 손짓·글자 대비 — 화면에서만 드러나던 회귀를 소스로 잠근다",
    "security": "키 유출·리다이렉트·비밀 스캔",
    "unit": "순수 함수 단위(서버 없이 가장 빠름)",
}


def _order(t: dict) -> tuple[int, int]:
    g = t["group"]
    return (GROUPS.index(g) if g in GROUPS else len(GROUPS), _REG.index(t))


def _match(t: dict, patterns: list[str]) -> bool:
    """그룹 이름과 정확히 같으면 그 그룹만, 그 밖에는 '그룹 + 이름' 부분 일치.

    (그룹 이름을 부분 일치로 다루면 -k js 가 'JSON' 이 든 다른 테스트까지 끌어온다.)
    """
    if not patterns:
        return True
    hay = f"{t['group']} {t['name']}".lower()
    for p in patterns:
        p = p.lower().strip()
        if p in GROUPS:
            if t["group"] == p:
                return True
        elif p in hay:
            return True
    return False


def _line(status: str, t: dict, secs: float) -> str:
    return f"{status:<4}  [{t['group']:<8}] {t['name']}  ({secs:.2f}s)"


def run_one(b: Box, t: dict, strict: bool = False) -> tuple[str, str, float]:
    started = time.perf_counter()
    boot_before = b.boot_secs
    status, detail = "PASS", ""
    try:
        if t["web"]:
            b.ensure_web()
        t["fn"](b)
    except Gap as e:                             # 아직 없는 계약 — 환경 SKIP 과 구분해서 센다
        status, detail = ("FAIL" if strict else "GAP"), str(e) or "계약 대기"
    except Skip as e:
        status, detail = "SKIP", str(e) or "건너뜀"
    except Failed as e:
        status, detail = "FAIL", str(e) or "실패"
    except Exception as e:                       # 예외는 이 테스트의 FAIL 로만 귀속된다
        tb = traceback.format_exc().strip().splitlines()
        where = next((l.strip() for l in reversed(tb[:-1]) if "selftest.py" in l), "")
        status = "FAIL"
        detail = f"{type(e).__name__}: {e}" + (f"  ({where})" if where else "")
    # 웹 스튜디오 기동은 실행당 한 번뿐인 비용이다 — 그것을 처음 부른 테스트의 시간에
    # 얹으면 그 테스트가 느린 것처럼 보인다(감사에서 'W01 20초' 로 읽혔다). 떼어 낸다.
    boot = b.boot_secs - boot_before
    secs = time.perf_counter() - started - boot
    print(_line(status, t, secs))
    if boot > 0:
        print(f"      └ 웹 스튜디오 기동 {boot:.1f}초 — 이 실행의 모든 웹 테스트가 이 서버 하나를 쓴다")
    if detail and status != "PASS":
        for ln in str(detail).splitlines()[:4]:
            print(f"      └ {ln}")
    sys.stdout.flush()
    return status, detail, secs


def print_list(tests: list[dict], patterns: list[str]) -> None:
    """그룹별 목록 — 어디를 부분 실행하면 되는지 한눈에 보이게."""
    sel = [t for t in tests if _match(t, patterns)]
    for g in GROUPS + sorted({t["group"] for t in tests} - set(GROUPS)):
        rows = [t for t in tests if t["group"] == g]
        if not rows:
            continue
        picked = sum(1 for t in rows if _match(t, patterns))
        note = GROUP_NOTE.get(g, "")
        mark = "" if picked == len(rows) else f" · 선택 {picked}"
        print(f"\n[{g}] {len(rows)}건{mark}" + (f" — {note}" if note else ""))
        for t in rows:
            flag = "웹" if t["web"] else "  "
            print(f"  {' ' if _match(t, patterns) else '-'} {flag} {t['name']}")
    print(f"\n총 {len(tests)}건 (선택 {len(sel)}건) · 그룹: {' '.join(GROUPS)}")
    print("부분 실행: python tools/selftest.py -k unit -k js   (그룹 이름·테스트 번호 모두 가능)")


def print_summary(results: list[tuple[str, dict, str, float]], elapsed: float,
                  boot: float = 0.0) -> int:
    npass = sum(1 for s, _t, _d, _x in results if s == "PASS")
    skips = [(t, d) for s, t, d, _x in results if s == "SKIP"]
    gaps = [(t, d) for s, t, d, _x in results if s == "GAP"]
    fails = [(t, d) for s, t, d, _x in results if s == "FAIL"]
    print("-" * 64)
    print(f"통과 {npass} · 실패 {len(fails)} · 건너뜀 {len(skips)} · 공백 {len(gaps)}"
          f"  (총 {len(results)}건, {elapsed:.1f}초)")
    if skips:
        print("환경 SKIP — 이 PC 에서 검사할 수 없을 뿐, 코드 문제가 아닙니다:")
        for t, d in skips:
            print(f"  [{t['group']}] {t['name']} — {d}")
    if gaps:
        print("구조적 공백(GAP) — 검사 대상이 아직 없습니다. 도착하면 그대로 회귀 잠금이 됩니다:")
        for t, d in gaps:
            print(f"  [{t['group']}] {t['name']}")
            print(f"      └ {d}")
        print("  (계약이 다 왔는지 확인: python tools/selftest.py --strict)")
    slow = sorted(results, key=lambda r: -r[3])[:3]
    if elapsed > 20 and slow:
        print("가장 느린 항목: " + " · ".join(f"{t['name'].split()[0]} {x:.1f}초"
                                              for _s, t, _d, x in slow))
        if boot > 0:
            print(f"  (+ 웹 스튜디오 기동 {boot:.1f}초 — 웹 테스트 "
                  f"{sum(1 for _s, t, _d, _x in results if t['web'])}건이 한 번만 낸다)")
    if fails:
        print("실패 항목:")
        for t, d in fails:
            print(f"  [{t['group']}] {t['name']}")
            first = str(d).splitlines()[0] if d else ""
            if first:
                print(f"      └ {first}")
        return 1
    if gaps:                 # --strict 면 여기 오지 않는다(GAP 이 이미 FAIL 로 집계된다)
        print(f"자가진단 통과 — 다만 구조적 공백 {len(gaps)}건이 아직 검사되지 않았습니다.")
    else:
        print("자가진단 전체 통과. 파이프라인 정상입니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="selftest.py", description="패키지 자가진단 (샌드박스 사본에서 실행)")
    ap.add_argument("-k", "--only", action="append", default=[], metavar="패턴",
                    help="그룹·이름에 이 문자열이 든 테스트만 실행 (여러 번 지정 가능)")
    ap.add_argument("--list", action="store_true", help="테스트 목록을 그룹별로 출력")
    ap.add_argument("--keep", action="store_true", help="실패 시 샌드박스를 지우지 않고 경로 출력")
    ap.add_argument("--strict", action="store_true",
                    help="구조적 공백(GAP)도 실패로 취급 — 계약이 전부 도착했는지 확인용")
    args = ap.parse_args(argv)

    tests = sorted(_REG, key=_order)
    sel = [t for t in tests if _match(t, args.only)]

    if args.list:
        print_list(tests, args.only)
        return 0
    if not sel:
        print(f"일치하는 테스트가 없습니다: {args.only}")
        print(f"쓸 수 있는 그룹: {' '.join(GROUPS)}  (전체 목록은 --list)")
        return 2

    print(f"자가진단 시작 — 원본 {SRC} · 테스트 {len(sel)}건"
          + (" · strict(GAP=실패)" if args.strict else ""))
    t0 = time.perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix="webtoon-selftest-"))
    results: list[tuple[str, dict, str, float]] = []
    box: Box | None = None
    try:
        box = Box(tmp / "repo")
        box.build()
        for t in sel:
            status, detail, secs = run_one(box, t, strict=args.strict)
            results.append((status, t, detail, secs))
    except KeyboardInterrupt:
        print("\n중단했습니다.")
        return 130
    finally:
        if box is not None:
            box.close()
        if args.keep and any(r[0] == "FAIL" for r in results):
            print(f"\n샌드박스 보존: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    return print_summary(results, time.perf_counter() - t0,
                         boot=(box.boot_secs if box is not None else 0.0))


if __name__ == "__main__":
    raise SystemExit(main())
