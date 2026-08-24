#!/usr/bin/env python3
"""패키지 자가진단 — 임시 샌드박스 사본에서 전체 파이프라인을 검증한다.

사용법:
  python tools/selftest.py                전체 실행
  python tools/selftest.py --list         테스트 목록만 보기
  python tools/selftest.py -k webapp      이름·그룹에 'webapp' 이 든 것만 실행 (여러 번 지정 가능)
  python tools/selftest.py -k P03 -k B02  개별 테스트만
  python tools/selftest.py --keep         실패했을 때 샌드박스를 지우지 않고 경로 출력

설계 원칙
  * 사용자의 project/ · images/ 원본은 절대 건드리지 않는다 — 모든 실행은 샌드박스 사본에서.
  * 유료 API(MakeFun·xAI)는 절대 호출하지 않는다. 네트워크가 나가는 지점만 스텁으로 막는다.
  * 없을 수 있는 것(Pillow·node·이관 중인 모듈)은 PASS 가 아니라 **SKIP** 으로 집계한다.
  * 테스트는 서로의 뒷정리에 기대지 않는다 — 상태를 바꾸면 픽스처가 반드시 원상 복구한다.
  * 한 테스트에서 난 예외는 그 테스트의 FAIL 로만 귀속된다(전체 실행이 멈추지 않는다).

수정 후에는 반드시 이 스크립트로 회귀를 확인한다.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import contextlib
import datetime as dt
import http.server
import importlib.util
import io
import json
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
import urllib.request as ur
import zipfile
import zlib
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
PY = sys.executable
ADV = "tools/advance_scene.py"
CHK = "tools/check_protocol.py"

# studio.html / 감상본 HTML 이 절대 쓰면 안 되는 DOM API (문자열 주입 경로)
BANNED_DOM = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")


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
    """이 환경에서는 검사할 수 없음 — 통과로 집계하지 않는다."""


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
    "__pycache__", "*.pyc", ".git", ".claude", "grok_inputs", "grok_outputs",
    "backups", "output", "logs", "scratch", "*.zip", ".venv", "node_modules")


class Box:
    """샌드박스 저장소 + 실행 도우미. 모든 테스트가 이 하나를 공유한다."""

    def __init__(self, root: Path):
        self.root = root
        self.env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        self._mods: dict[str, object] = {}
        self._syspath: list[str] | None = None
        self._web: subprocess.Popen | None = None
        self._web_error: str | None = None
        self._mock = None
        self.web_port = 0
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
    def run(self, *args: str, no_key: bool = False, env: dict | None = None) -> tuple[int, str]:
        e = dict(env if env is not None else self.env)
        if no_key:
            e.pop("XAI_API_KEY", None)
        p = subprocess.run([PY, *args], cwd=self.root, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=e)
        return p.returncode, p.stdout + p.stderr

    def checker(self, *args: str) -> tuple[int, str]:
        return self.run(CHK, *args)

    # -------------------------------------------------- in-process 모듈
    def mod(self, name: str, optional: bool = False):
        """tools/<name>.py 를 샌드박스에서 in-process 로 적재(캐시).

        optional=True 는 '다른 에이전트가 이관 중이라 아직 없을 수 있는' 모듈용 —
        없거나 적재 실패면 그 테스트만 SKIP 된다.
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
        try:
            self._start_web()
        except Failed as e:
            self._web_error = str(e)
            raise

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
            """OpenAI 호환 최소 서버 — xAI 경로와 로컬 LLM 경로가 함께 쓴다.

            실제 모델(로컬 :8080 / xAI)이 떠 있든 말든 자가진단 결과가 같아야 한다.
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
        wenv["XAI_API_KEY"] = "dummy"
        wenv["NO_PROXY"] = wenv["no_proxy"] = "127.0.0.1,localhost"
        self._web = subprocess.Popen(
            [PY, "tools/webapp.py", "--port", str(self.web_port), "--no-browser"],
            cwd=self.root, env=wenv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            if self._web.poll() is not None:
                raise Failed("웹 스튜디오가 기동 직후 종료했습니다.")
            code, _h, _b = self.raw("/api/state")
            if code == 200:
                return
            time.sleep(0.2)
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
            self.set_api(api.get("base_url", "https://api.x.ai/v1"), api.get("model", "TBD"))

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

    stage: PLAN → PROMPT → REVIEW(후보 등록까지) → APPROVED
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
        gp = b.root / "grok_out.txt"
        gp.write_text(f"SCENE_PROMPT: medium shot, {anchor_c}, {anchor_l}, cel shading\n"
                      "NEGATIVE_PROMPT: text\n", encoding="utf-8")
        rc, out = b.run(ADV, "set-prompt", sid, "--file", str(gp))
        gp.unlink(missing_ok=True)
        eq(rc, 0, f"rc — {out[:200]}")
        eq(b.scene(sid)["status"], "PROMPT", "status")
        hasnt(out, "FAIL", "자동 검사")


@test("pipeline", "P04 add-images → 자동검사 PASS → REVIEW_HUMAN 전이")
def p04(b: Box):
    with cli_scene(b, "PROMPT") as sid:
        a, c = b.root / "cand_a.png", b.root / "cand_b.png"
        write_png(a, 1400, 1000)
        write_png(c, 1400, 1000, (150, 190, 230))
        rc, out = b.run(ADV, "add-images", sid, str(a), str(c))
        a.unlink(missing_ok=True)
        c.unlink(missing_ok=True)
        st = b.scene(sid)
        eq(rc, 0, f"rc — {out[:200]}")
        eq(st["status"], "REVIEW_HUMAN", "status")
        eq(st["review"]["auto"], "PASS", "review.auto")
        eq(len(st["assets"]["raw_images"]), 2, "후보 수")


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


@test("pipeline", "P08 grok_api — 키 없으면 안내 종료 · --dry-run 은 키 없이 조립")
def p08(b: Box):
    rc, out = b.run("tools/grok_api.py", "SCENE-001", no_key=True)
    eq(rc, 2, f"rc — {out[:200]}")
    has(out, "XAI_API_KEY", "안내")
    rc2, out2 = b.run("tools/grok_api.py", "SCENE-001", "--dry-run", no_key=True)
    eq(rc2, 0, f"dry-run rc — {out2[:200]}")
    has(out2, "dry-run", "dry-run 표시")


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
@test("webapp", "W01 기동 + 상태 API(키는 불리언만 노출)", web=True)
def w01(b: Box):
    st, d = b.wapi("/api/state")
    eq(st, 200, "status")
    eq(d.get("key_set"), True, "key_set")
    eq(d.get("model"), "mock-model", "model")
    ok(all(not isinstance(v, str) or "dummy" not in v for v in d.values()), "키 원문 노출")


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
    cenv["XAI_API_KEY"] = "dummy"
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


@test("webapp", "W13 수동 grok-input + set-prompt → PROMPT + 앵커 검사 통과", web=True)
def w13(b: Box):
    anchor_c, anchor_l = b.anchors()
    with fresh_scene(b) as sid:
        st, d = b.wapi("/api/grok-input", {"scene_id": sid})
        eq(st, 200, "status")
        has(d.get("text", ""), anchor_c, "지시문 앵커")
        ptext = f"SCENE_PROMPT: medium shot, {anchor_c}, {anchor_l}, cel shading\nNEGATIVE_PROMPT: text"
        st2, d2 = b.wapi("/api/set-prompt", {"scene_id": sid, "text": ptext})
        sc = b.scene(sid)
        eq(st2, 200, "set-prompt status")
        eq(d2.get("checker_pass"), True, f"검사 — {d2}")
        eq(sc["status"], "PROMPT", "status")
        eq(sc["prompt"]["grok_output"], ptext, "저장 내용")


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
@contextlib.contextmanager
def mf_stub(mk, api, fetch=None):
    """MakeFun 이 네트워크로 나가는 두 지점만 스텁으로 막는다.

    실제 API 는 절대 호출되지 않는다(_once·_fetch_bytes 가 전부다). 대기·백오프는 0초.
    """
    calls: list[tuple[str, str]] = []

    def _once(method, path, body, timeout):
        calls.append((method, path))
        return api(method, path, body)

    def _fetch(url, timeout):
        if fetch is None:
            raise RuntimeError("다운로드 스텁 없음")
        return fetch(url)

    with patched(mk, "_once", _once), patched(mk, "_fetch_bytes", _fetch), \
            patched(mk, "POLL_SEC", 0), patched(mk, "_backoff", lambda a, ra: 0.0):
        yield calls


def _mf_api(task_id: str, urls: list[str]):
    """start → task_id, 조회 → completed + urls 를 돌려주는 최소 모의 서버."""
    def api(method, path, body):
        if path.endswith("/start"):
            return {"code": 0, "data": [{"_id": task_id}]}
        return {"code": 0, "data": {"current_status": "completed", "image_urls": urls}}
    return api


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
            bpm.snapshot(dt.datetime(2026, 3, 1 + i, 12, 0, 0))
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


@test("viewer", "V01 타임캡슐 감상본 — 단일 HTML·이미지 내장·스크롤 모드·주입 API 0")
def v01(b: Box):
    tcm = b.mod("export_viewer")
    with approved_scene(b):
        out = tcm.export(False, 800, 80)
        html = out.read_text(encoding="utf-8")
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


# ============================================================ JS 구문 게이트
def _scripts(html: str) -> list[str]:
    return [s for s in re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I) if s.strip()]


def _node_check(b: Box, html: str, label: str) -> None:
    """<script> 본문을 모아 node --check — 문법 오류로 화면이 백지가 되는 회귀를 잡는다."""
    node = shutil.which("node")
    if not node:
        raise Skip("node 없음 — JS 구문 검사 생략")
    blocks = _scripts(html)
    ok(len(blocks) >= 1, f"{label}: <script> 를 찾지 못함")
    tmp = b.root / f"_syntax_{label}.js"
    tmp.write_text("\n;\n".join(blocks), encoding="utf-8")
    p = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tmp.unlink(missing_ok=True)
    eq(p.returncode, 0, f"{label} JS 문법 오류 — {(p.stderr or p.stdout)[:400]}")


@test("js", "J01 studio.html — JS 문법 통과 + 주입 API(innerHTML 등) 0")
def j01(b: Box):
    html = b.p("tools/studio.html").read_text(encoding="utf-8")
    for api in BANNED_DOM:
        eq(html.count(api), 0, f"studio.html 이 {api} 사용")
    _node_check(b, html, "studio")


@test("js", "J02 감상본 HTML — JS 문법 통과(내보낸 결과물 그대로)")
def j02(b: Box):
    tcm = b.mod("export_viewer")
    with approved_scene(b):
        html = tcm.export(False, 640, 70).read_text(encoding="utf-8")
    _node_check(b, html, "viewer")


# ============================================================ 보안
@test("security", "S01 A8 — 심어 둔 키 패턴을 검사기가 검출")
def s01(b: Box):
    fake = "xai-" + "abcdefghij0123456789" + "KLMN"     # 런타임 조립(이 파일 자체가 걸리지 않게)
    with replaced_text(b.p("project/leak.md"), f"memo: {fake}"):
        rc, out = b.checker()
    eq(rc, 1, "exit code")
    has(out, "[A8] FAIL", "키 검출")
    rc2, _ = b.checker()
    eq(rc2, 0, "픽스처 정리 후 GREEN")


@test("security", "S02 xai cross-host 302 리다이렉트로 키가 유출되지 않는다(critical)")
def s02(b: Box):
    attacker = {"auth": "NOT-CALLED"}

    class Atk(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            attacker["auth"] = self.headers.get("Authorization")
            raw = json.dumps({"choices": [{"message": {"content": "leaked"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    atk = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Atk)
    threading.Thread(target=atk.serve_forever, daemon=True).start()

    class Redir(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.send_response(302)
            self.send_header("Location",
                             f"http://127.0.0.1:{atk.server_address[1]}/v1/chat/completions")
            self.end_headers()

    rd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redir)
    threading.Thread(target=rd.serve_forever, daemon=True).start()
    try:
        xc = b.mod("xai_client")
        with env_var("XAI_API_KEY", "sk-SECRET-LEAK-TEST-XYZ"), \
                env_var("NO_PROXY", "127.0.0.1,localhost"), env_var("no_proxy", "127.0.0.1,localhost"), \
                b.api_pointed_at(f"http://127.0.0.1:{rd.server_address[1]}/v1"):
            raises(lambda: xc.chat([{"role": "user", "content": "hi"}]), RuntimeError, "리다이렉트")
        eq(attacker["auth"], "NOT-CALLED", "공격 서버가 Authorization 헤더를 받음")
    finally:
        atk.shutdown()
        atk.server_close()
        rd.shutdown()
        rd.server_close()


@test("security", "S03 xai — content=null·비JSON 200 응답은 안내(크래시 아님)")
def s03(b: Box):
    mode = {"v": "null"}

    class Weird(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            if mode["v"] == "null":
                raw = json.dumps({"choices": [{"message": {"content": None}}]}).encode()
                ct = "application/json"
            else:
                raw, ct = b"<html>gateway error</html>", "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Weird)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        xc = b.mod("xai_client")
        with env_var("XAI_API_KEY", "sk-TEST"), env_var("NO_PROXY", "127.0.0.1,localhost"), \
                env_var("no_proxy", "127.0.0.1,localhost"), \
                b.api_pointed_at(f"http://127.0.0.1:{srv.server_address[1]}/v1"):
            raises(lambda: xc.chat([{"role": "user", "content": "x"}]), RuntimeError, "content=null")
            mode["v"] = "html"
            raises(lambda: xc.chat([{"role": "user", "content": "x"}]), RuntimeError, "비JSON 200")
    finally:
        srv.shutdown()
        srv.server_close()


@test("security", "S04 secret_scan — 심은 키를 잡고 원문은 출력하지 않는다(마스킹)")
def s04(b: Box):
    ss = b.mod("secret_scan")
    planted = "xai-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
    hits = ss.scan_text(f'KEY = "{planted}"')
    ok(len(hits) >= 1, "탐지 실패")
    rendered = json.dumps(hits, ensure_ascii=False, default=str)
    hasnt(rendered, planted, "원문 노출")


# ============================================================ 단위(순수 함수)
@test("unit", "U01 scene_ops — APPROVED 장면은 어떤 쓰기 경로로도 바뀌지 않는다")
def u01(b: Box):
    so = b.mod("scene_ops", optional=True)
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
    wa = b.mod("webapp")
    merge = getattr(wa, "_merge_talk", None)
    if merge is None:
        ts = b.mod("talk_store", optional=True)
        merge = getattr(ts, "merge_talk", None) or getattr(ts, "merge", None)
    if merge is None:
        raise Skip("대화 병합 함수를 찾지 못함(이관 중)")
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
    with env_var("LOCAL_LLM_URL", "http://127.0.0.1:59999/v1"):   # 죽은 포트
        st = llm.status()
        sysmsg, meta = llm.persona_prompt()
    eq(st.get("up"), False, "서버 off 판정")
    ok(isinstance(sysmsg, str) and sysmsg.strip(), "시스템 메시지")
    ok(bool(meta.get("name")), "인물 이름")
    has(sysmsg, meta["name"], "페르소나에 이름 반영")


@test("unit", "U04 앨범 사진 — 태그 파싱 · '없다' 억제 · 키워드 폴백 · 요청 아님")
def u04(b: Box):
    llm = b.mod("local_llm")
    album = {"SCENE-001": {"rel": "images/raw/SCENE-001/a.png", "label": "카페에서 만나는 장면"},
             "SCENE-005": {"rel": "images/raw/SCENE-005/a.png", "label": "노을 강변 산책"}}
    c1, p1 = llm.resolve_photos("이거 봐~ [사진:SCENE-005]", album, "노을 사진 보여줘")
    ok(p1 and p1[0]["scene_id"] == "SCENE-005", "태그 파싱")
    hasnt(c1, "사진:", "태그가 본문에 남음")
    _c2, p2 = llm.resolve_photos("그 사진은 지금 없네~", album, "수영복 사진 보여줘")
    eq(len(p2), 0, "'없다' 응답인데 사진을 붙임")
    _c3, p3 = llm.resolve_photos("응 좋았지!", album, "카페에서 찍은 사진 보여줘")
    ok(p3 and p3[0]["scene_id"] == "SCENE-001", "키워드 폴백")
    _c4, p4 = llm.resolve_photos("오늘 날씨 좋다", album, "그냥 잡담")
    eq(len(p4), 0, "요청이 아닌데 사진을 붙임")


# ============================================================ 러너
GROUPS = ["pipeline", "checker", "webapp", "auth", "makefun", "backup",
          "print", "viewer", "js", "security", "unit"]


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
    return f"{status}  [{t['group']:<8}] {t['name']}  ({secs:.2f}s)"


def run_one(b: Box, t: dict) -> tuple[str, str, float]:
    started = time.perf_counter()
    status, detail = "PASS", ""
    try:
        if t["web"]:
            b.ensure_web()
        t["fn"](b)
    except Skip as e:
        status, detail = "SKIP", str(e) or "건너뜀"
    except Failed as e:
        status, detail = "FAIL", str(e) or "실패"
    except Exception as e:                       # 예외는 이 테스트의 FAIL 로만 귀속된다
        tb = traceback.format_exc().strip().splitlines()
        where = next((l.strip() for l in reversed(tb[:-1]) if "selftest.py" in l), "")
        status = "FAIL"
        detail = f"{type(e).__name__}: {e}" + (f"  ({where})" if where else "")
    secs = time.perf_counter() - started
    print(_line(status, t, secs))
    if detail and status != "PASS":
        for ln in str(detail).splitlines()[:4]:
            print(f"      └ {ln}")
    sys.stdout.flush()
    return status, detail, secs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="selftest.py", description="패키지 자가진단 (샌드박스 사본에서 실행)")
    ap.add_argument("-k", "--only", action="append", default=[], metavar="패턴",
                    help="그룹·이름에 이 문자열이 든 테스트만 실행 (여러 번 지정 가능)")
    ap.add_argument("--list", action="store_true", help="테스트 목록만 출력")
    ap.add_argument("--keep", action="store_true", help="실패 시 샌드박스를 지우지 않고 경로 출력")
    args = ap.parse_args(argv)

    tests = sorted(_REG, key=_order)
    sel = [t for t in tests if _match(t, args.only)]

    if args.list:
        for t in tests:
            mark = " " if _match(t, args.only) else "-"
            print(f"{mark} [{t['group']:<8}] {t['name']}")
        print(f"\n총 {len(tests)}건 (선택 {len(sel)}건)")
        return 0
    if not sel:
        print(f"일치하는 테스트가 없습니다: {args.only}")
        return 2

    print(f"자가진단 시작 — 원본 {SRC} · 테스트 {len(sel)}건")
    t0 = time.perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix="webtoon-selftest-"))
    results: list[tuple[str, dict, str]] = []
    box: Box | None = None
    try:
        box = Box(tmp / "repo")
        box.build()
        for t in sel:
            status, detail, _secs = run_one(box, t)
            results.append((status, t, detail))
    except KeyboardInterrupt:
        print("\n중단했습니다.")
        return 130
    finally:
        if box is not None:
            box.close()
        fails = [r for r in results if r[0] == "FAIL"]
        if args.keep and fails:
            print(f"\n샌드박스 보존: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    npass = sum(1 for s, _, _ in results if s == "PASS")
    nskip = sum(1 for s, _, _ in results if s == "SKIP")
    fails = [(t, d) for s, t, d in results if s == "FAIL"]
    print("-" * 64)
    print(f"통과 {npass} · 실패 {len(fails)} · 건너뜀 {nskip}"
          f"  (총 {len(results)}건, {time.perf_counter() - t0:.1f}초)")
    if nskip:
        for s, t, d in results:
            if s == "SKIP":
                print(f"  SKIP [{t['group']}] {t['name']} — {d}")
    if fails:
        print("실패 항목:")
        for t, d in fails:
            print(f"  [{t['group']}] {t['name']}")
            first = str(d).splitlines()[0] if d else ""
            if first:
                print(f"      └ {first}")
        return 1
    print("자가진단 전체 통과. 파이프라인 정상입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
