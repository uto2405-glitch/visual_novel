#!/usr/bin/env python3
"""MakeFun AI 텍스트→이미지 클라이언트 — 파이프라인 3단계(이미지 생성) 자동화.

API: POST /api/v1/userText2Image/start → {code:0, data:[{_id,...}]}
     GET  /api/v1/userText2Image/{id}  → current_status: initialized/processing → completed/failed
토큰은 환경변수 MAKEFUN_API_TOKEN 로만 공급한다(파일 저장 금지 — 검사기 A8).

사용:
  python tools/makefun_client.py SCENE-001 [--n 2] [--long-edge 1536]
  python tools/makefun_client.py --prompt "..." --out scratch/test.png
  python tools/makefun_client.py --all-pending [--dry-run] [--limit 5]
  python tools/makefun_client.py SCENE-001 --refetch   # 과금 없이 기록된 task 로 재수령
  python tools/makefun_client.py --check [--online]    # 토큰·설정 사전 점검(생성 크기 함정 포함)

인화 크기 주의: 요청 긴 변은 image_generator.max_long_edge_px(기본 2048)로 잘린다.
output.min_long_edge_px 만 1800/2250/3600 으로 올리면 과금은 그대로 되고 결과만 2048px 이 된다.
--check 와 생성 직전 경고가 그 조합을 미리 알려 준다(size_plan / size_warnings).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:          # 저장소가 복제된 곳에서 이 파일만 적재돼도 '옆에 있는' vn_core 를 쓴다
    sys.path.insert(0, str(_HERE))

import vn_core                                                 # noqa: E402
from vn_core import (IMAGE_EXTS, WRITE_LOCK, VNError,          # noqa: E402
                     atomic_write_bytes, atomic_write_json, is_scene_id,
                     iter_scenes, load_json, load_json_safe, selected_of)

# 경로는 vn_core 하나에서 온다. vn_core 도 자기 파일 위치(_HERE 와 같은 tools/)에서 계산하므로
# 자가진단이 저장소를 복제해 이 모듈만 적재해도 그대로 **그 복제본 안**만 읽고 쓴다.
# (예전에는 같은 값을 여기서 다시 조립했다 — 한쪽 폴더 이름이 바뀌면 조용히 갈리는 5벌이었다.)
ROOT = vn_core.ROOT
MANIFEST = vn_core.MANIFEST        # 테스트가 갈아끼우므로 함수는 호출 시점에 읽는다
SCENES_DIR = vn_core.SCENES
RAW_DIR = vn_core.IMAGES_RAW
USAGE_LOG = vn_core.LOGS / "makefun_usage.jsonl"
META_NAME = "_gen_meta.json"
TOKEN_ENV = "MAKEFUN_API_TOKEN"
DEFAULT_BASE = "https://makefun.ai"
POLL_SEC = 4
POLL_MAX_SEC = 300
DL_CAP = 30 * 1024 * 1024

# 재시도(9) — 일시 오류 한 번에 과금 생성이 통째로 실패하지 않게 한다.
RETRY_MAX = 4
RETRY_BASE_SEC = 2.0
RETRY_CAP_SEC = 30.0
RETRY_CODES = (408, 429, 500, 502, 503, 504)

# 생성 크기(19) — manifest.output.min_long_edge_px 를 따르고 8의 배수로 정렬한다.
DEFAULT_LONG_EDGE = 1024
SIZE_MIN_PX = 512
SIZE_MAX_PX = 2048          # API 허용 상한 가정치. image_generator.max_long_edge_px 로 조정 가능
SIZE_HARD_MAX_PX = 4096

# 이미지 내 글자 억제(15) — text2image API 에 negative 필드가 없어 프롬프트 말미에 덧붙인다.
NEGATIVE_PHRASES = ("no text", "no letters", "no speech bubbles", "no watermark", "no signature")

META_MAX_ENTRIES = 200      # _gen_meta.json 무한 증식 방지
# 장면 assets.makefun_tasks 의 보존 개수는 그 파일을 쓰는 쪽(scene_ops.GEN_TASKS_MAX)이 정한다.

# 대장·메타·장면 JSON 의 read-modify-write 직렬화는 저장소 전역 잠금(vn_core.WRITE_LOCK)을 쓴다.
# 예전처럼 이 파일만의 잠금을 따로 두면 웹에서 장면을 저장하는 순간과 task_id 를 적는 순간이
# 서로를 막지 못해, 이미 과금된 task_id 기록이 통째로 덮여 사라질 수 있다(재수령 불가 = 금전 손실).


# 생성 작업 로그와 같은 채널(vn.gen) — webapp.setup_logging 이 logs/webapp.log 에 물린다.
# CLI 로 단독 실행될 때는 핸들러가 없어 조용하다(라이브러리 규약).
log = logging.getLogger("vn.gen")
log.addHandler(logging.NullHandler())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


_API = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())
_DL = urllib.request.build_opener(urllib.request.ProxyHandler())   # 결과 CDN 은 리다이렉트 허용(무토큰)


class _Transient(RuntimeError):
    """재시도 가치가 있는 오류(429·5xx·일시 네트워크). presend=요청이 전송되기 전에 실패."""

    def __init__(self, msg: str, code: int | None = None,
                 retry_after: float | None = None, presend: bool = False):
        super().__init__(msg)
        self.code = code
        self.retry_after = retry_after
        self.presend = presend


class GenResult(list):
    """저장된 파일 경로 목록 — list 그대로라 기존 호출부와 호환되고, 부분 실패 정보를 함께 싣는다(11)."""

    def __init__(self, files=(), warnings=None, task_ids=None):
        super().__init__(files)
        self.warnings: list[str] = list(warnings or [])
        self.task_ids: list[str] = list(task_ids or [])


def token() -> str:
    t = os.environ.get(TOKEN_ENV, "").strip()
    if not t:
        raise VNError(f"{TOKEN_ENV} 환경변수가 없습니다. makefun.ai Account > API Token 발급 후 "
                      f'PowerShell: $env:{TOKEN_ENV}="sk_..." 로 설정하세요.')
    return t


def _cfg() -> dict:
    mf = load_json_safe(MANIFEST, {})
    cfg = mf.get("image_generator", {})
    return cfg if isinstance(cfg, dict) else {}


def base_url() -> str:
    u = str((_cfg().get("api", {}) or {}).get("base_url", "") or DEFAULT_BASE).rstrip("/")
    if not u.startswith("https://"):
        raise VNError(f"MakeFun base_url 은 https 만 허용합니다: {u}")
    return u


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _say(msg: str, quiet: bool = False) -> None:
    if quiet:
        return
    try:
        print(msg, flush=True)
    except Exception:
        pass


# --- HTTP + 재시도(9) -------------------------------------------------------

def _retry_after(headers) -> float | None:
    try:
        v = float(str(headers.get("Retry-After", "")).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    return max(0.0, min(v, RETRY_CAP_SEC))


def _once(method: str, path: str, body: dict | None, timeout: int) -> dict:
    req = urllib.request.Request(
        base_url() + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"},
        method=method)
    try:
        with _API.open(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 401:
            raise VNError("MakeFun 인증 실패(401) — 토큰을 확인하세요.")
        if e.code in RETRY_CODES:
            raise _Transient(f"MakeFun HTTP {e.code}: {detail}", e.code, _retry_after(e.headers))
        raise VNError(f"MakeFun HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        # DNS·연결거부는 요청이 나가기 전 실패 — POST 재시도해도 이중 생성 위험이 없다.
        presend = isinstance(e.reason, (socket.gaierror, ConnectionRefusedError))
        raise _Transient(f"MakeFun 연결 실패: {e.reason}", None, None, presend)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise VNError("MakeFun 응답이 JSON 이 아닙니다.")
    if not isinstance(data, dict) or data.get("code") not in (0, None):
        raise VNError(f"MakeFun 오류 응답: {str(data)[:200]}")
    return data


def _backoff(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return retry_after
    return min(RETRY_BASE_SEC * (2 ** attempt), RETRY_CAP_SEC) + random.uniform(0, 1.0)


def _call(method: str, path: str, body: dict | None = None, timeout: int = 60,
          idempotent: bool = True, quiet: bool = True) -> dict:
    """지수 백오프 재시도(9).

    왜 idempotent 구분: 생성 시작(POST start)은 재시도가 이중 과금이 될 수 있으므로
    '확실히 처리되지 않은' 경우(429 거절·전송 전 실패)에만 다시 보낸다.
    """
    for attempt in range(RETRY_MAX + 1):
        try:
            return _once(method, path, body, timeout)
        except _Transient as e:
            safe = idempotent or e.code == 429 or e.presend
            if attempt >= RETRY_MAX or not safe:
                raise VNError(str(e)) from e
            delay = _backoff(attempt, e.retry_after)
            _say(f"  일시 오류 — {delay:.0f}초 후 재시도 {attempt + 1}/{RETRY_MAX} ({e})", quiet)
            time.sleep(delay)
    raise VNError("MakeFun 재시도 한도를 초과했습니다.")   # 도달하지 않음(방어)


# --- 생성 크기(19) ----------------------------------------------------------

def _cap_px() -> int:
    """허용 상한 — 인화용 큰 값은 manifest image_generator.max_long_edge_px 로 올린다."""
    try:
        v = int(_cfg().get("max_long_edge_px", SIZE_MAX_PX) or SIZE_MAX_PX)
    except (TypeError, ValueError):
        v = SIZE_MAX_PX
    return max(SIZE_MIN_PX, min(v, SIZE_HARD_MAX_PX))


def _align8(px: int) -> int:
    """8의 배수 정렬 — 긴 변은 '최소' 요구라 올림하되 상한은 넘지 않는다."""
    cap = _cap_px() // 8 * 8
    px = max(SIZE_MIN_PX, min(int(px), cap))
    return min((px + 7) // 8 * 8, cap)


def size_plan(long_edge: int | None = None) -> dict:
    """실제로 요청될 크기 + '요청한 값이 깎였는지' 를 함께 돌려준다.

    조용한 절삭은 돈이 새는 함정이다. 문서(README·SCHEMA·PRINT_ORDER_GUIDE·STATUS)는
    "인화하려면 output.min_long_edge_px 를 1800/2250/3600 으로 올려라"고 안내하는데,
    image_generator.max_long_edge_px 가 없으면 상한 2048 로 깎여 나간다 — **과금은 그대로 되고**
    결과는 인화 규격에 미달하며 검사기 A3(긴 변 ≥ min_long_edge_px)까지 FAIL 한다.
    그래서 크기 계산은 이 한 곳에서 하고, 호출부는 생성 전에 size_warnings 로 사실을 알린다.
    """
    ar, want, src = "2:3", DEFAULT_LONG_EDGE, "output.min_long_edge_px"
    out = load_json_safe(MANIFEST, {}).get("output", {})
    if isinstance(out, dict):
        try:
            ar = str(out.get("aspect_ratio", "2:3") or "2:3")
            want = int(out.get("min_long_edge_px", DEFAULT_LONG_EDGE) or DEFAULT_LONG_EDGE)
        except (TypeError, ValueError):
            ar, want = "2:3", DEFAULT_LONG_EDGE
    if long_edge:
        try:
            want, src = int(long_edge), "--long-edge"
        except (TypeError, ValueError):
            pass
    try:
        w, h = (int(x) for x in ar.split(":"))
        if w <= 0 or h <= 0:
            raise ValueError(ar)
    except Exception:
        w, h = 2, 3
    long_px = _align8(want)
    if h >= w:
        width, height = max(8, (long_px * w // h) // 8 * 8), long_px
    else:
        width, height = long_px, max(8, (long_px * h // w) // 8 * 8)
    cap = _cap_px()
    return {"width": width, "height": height, "long": long_px, "want": int(want),
            "cap": cap, "capped": long_px < int(want), "source": src,
            "cap_is_default": "max_long_edge_px" not in _cfg()}


def _size_from_manifest(long_edge: int | None = None) -> tuple[int, int]:
    """출력 규격(기본 2:3 세로)과 manifest.output.min_long_edge_px 에 맞는 생성 크기."""
    plan = size_plan(long_edge)
    return plan["width"], plan["height"]


def _print_note(width: int, height: int) -> str:
    """이 크기가 실물 인화로 어디까지 가는지 한 줄 — 규격 판정은 print_preflight 에 위임한다.

    지연 import 인 이유: print_preflight 도 상한 경고를 받으러 이 모듈을 부른다(서로 부른다).
    최상단에서 서로를 import 하면 순환이 되므로 각자 쓰는 자리에서만 불러온다.
    실패해도 생성은 계속돼야 하지만(여기는 안내문일 뿐이다) **조용히 사라지지는 않게** 남긴다.
    """
    try:
        import print_preflight as pf
    except ImportError as exc:
        log.debug("인화 규격 안내 생략 — print_preflight 없음: %s", exc)
        return ""
    try:
        rep = pf.preflight_image(int(width), int(height), pf.DPI_GOOD)
        need = pf.needed_px("5×7", pf.DPI_GOOD)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        log.warning("인화 규격 안내 생략 — print_preflight 계산 실패: %s", exc)
        return ""
    best = rep.get("max_size_at_target")
    inches = rep.get("max_long_in_at_target")
    head = (f"이 크기는 {pf.DPI_GOOD}DPI 인화로 최대 {best} 까지입니다 (긴 변 {inches}인치)"
            if best else
            f"이 크기는 {pf.DPI_GOOD}DPI 인화 기준 엽서(4×6)에도 미달합니다 (긴 변 {inches}인치)")
    row = next((r for r in rep.get("rows", []) if r.get("size") == "5×7"), None)
    if need and row and row.get("dpi", 0) < rep.get("target_dpi", pf.DPI_GOOD):
        head += f" — 5×7 인화 기준({need[0]}×{need[1]}px)에 미달합니다"
    return head


def size_warnings(plan: dict | None = None, long_edge: int | None = None) -> list[str]:
    """생성(=과금) 전에 반드시 보여야 할 크기 경고. 문제가 없으면 빈 목록."""
    plan = plan or size_plan(long_edge)
    if not plan.get("capped"):
        return []
    a3 = ("" if plan.get("source") == "--long-edge" else
          f" 지금 생성하면 검사기 A3(긴 변 ≥ {plan['want']}px)도 FAIL 합니다.")
    msgs = [f"요청 {plan['want']}px({plan.get('source', '')}) → 실제 {plan['long']}px "
            f"— 상한 {plan['cap']}px 에 깎였습니다. 과금은 요청대로 됩니다. "
            f"매니페스트 image_generator.max_long_edge_px 를 {plan['want']} 이상으로 "
            f"올린 뒤 생성하세요.{a3}"]
    note = _print_note(plan["width"], plan["height"])
    if note:
        msgs.append(note)
    return msgs


# --- 프롬프트 억제 문구(15) --------------------------------------------------

def apply_negative(prompt: str, enabled: bool = True) -> str:
    """이미지 안에 글자가 생기지 않게 억제 문구를 덧붙인다.

    MakeFun text2image 에는 negative prompt 필드가 없어 프롬프트 문자열로 처리한다.
    이미 들어 있는 문구는 다시 넣지 않는다(반복 호출해도 결과가 같다).
    """
    text = (prompt or "").strip()
    if not enabled or not text:
        return text
    low = text.lower()
    missing = [p for p in NEGATIVE_PHRASES if not re.search(r"\b" + re.escape(p) + r"\b", low)]
    if not missing:
        return text
    sep = "" if text.endswith(",") else ","
    return f"{text}{sep} " + ", ".join(missing)


# --- 기록: 대장(17) · 메타(12) · 장면 task(10) --------------------------------

def log_usage(record: dict) -> None:
    """종량제 비용 추적용 append-only 대장(17). 기록 실패가 생성을 막지 않는다."""
    try:
        with WRITE_LOCK:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": _now(), **record}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def write_gen_meta(out_dir: Path, entry: dict) -> None:
    """생성 메타데이터를 images/raw/<scene>/_gen_meta.json 에 누적(12)."""
    try:
        path = Path(out_dir) / META_NAME
        with WRITE_LOCK:
            doc = load_json_safe(path, {})
            entries = doc.get("entries")
            if not isinstance(entries, list):
                entries = []
            entries.append(entry)
            doc["entries"] = entries[-META_MAX_ENTRIES:]
            doc.setdefault("scene_id", entry.get("scene_id", ""))
            doc["updated_at"] = _now()
            atomic_write_json(path, doc)
    except Exception:
        pass


def _scene_path(scene_id: str) -> Path:
    # 저장소 공통 형식(SCENE-001)만 허용 — 경로 탈출과 엉뚱한 파일 덮어쓰기를 입구에서 막는다.
    if not is_scene_id(scene_id):
        raise VNError(f"장면 ID 형식이 올바르지 않습니다: {str(scene_id)[:40]!r}")
    return SCENES_DIR / f"{scene_id}.json"


def _load_scene(scene_id: str) -> dict:
    sc = load_json(_scene_path(scene_id))
    if not isinstance(sc, dict):
        raise VNError(f"{scene_id}: JSON 최상위가 객체가 아닙니다.")
    return sc


def record_tasks(scene_id: str, task_ids: list[str], width: int = 0, height: int = 0) -> None:
    """생성 task id 를 장면 assets.makefun_tasks 에 남긴다(10).

    다운로드만 실패했을 때 재생성(재과금) 없이 fetch_task_images 로 다시 받기 위한 기록.

    **쓰기는 scene_ops 가 한다.** 생성 클라이언트가 장면 파일을 직접 고쳐 쓰면 잠금과
    정규화를 각자 한 벌씩 갖게 되고, 그중 하나만 어긋나도 이미 과금된 task 기록이
    덮여 사라진다(= 재수령 불가 = 금전 손실). 여기 남는 것은 호출과 실패 기록뿐이다.
    """
    if not scene_id or not task_ids:
        return
    try:
        # 지연 import: 이 모듈만 복제된 환경(자가진단 등)에서 scene_ops 가 없어도 생성 자체는
        # 계속되어야 한다 — 기록 실패는 아래에서 경고로 남는다(gen_jobs 와 같은 태도).
        import scene_ops
        scene_ops.record_generation_tasks(scene_id, list(task_ids),
                                          {"width": width, "height": height})
    except Exception as exc:
        # 기록 실패로 이미 과금된 생성을 중단시키지는 않는다. 다만 이 기록이 없으면
        # 나중에 재수령(무과금 회수)을 못 하므로 무슨 일이 있었는지는 남긴다.
        log.warning("task 기록 실패 %s: %s (재수령이 불가능해질 수 있습니다)", scene_id, exc)


def scene_task_ids(scene_id: str) -> list[str]:
    """장면에 기록된 MakeFun task id 목록(오래된 순)."""
    try:
        tasks = (_load_scene(scene_id).get("assets", {}) or {}).get("makefun_tasks", [])
    except Exception:
        return []
    return [t["task_id"] for t in tasks
            if isinstance(t, dict) and isinstance(t.get("task_id"), str) and t["task_id"]]


# --- 생성 · 폴링 · 다운로드 --------------------------------------------------

def start(prompt: str, n: int = 1, name: str = "",
          long_edge: int | None = None, negative: bool = True, quiet: bool = True) -> list[str]:
    """생성 시작 → task id 목록. 요청 크기가 상한에 깎이면 과금 전에 알린다."""
    plan = size_plan(long_edge)
    w, h = plan["width"], plan["height"]
    for msg in size_warnings(plan):
        _say("  ⚠ 생성 크기 — " + msg, quiet)
    body = {"prompt": apply_negative(prompt, negative), "width": w, "height": h,
            "model_type": str(_cfg().get("model", "") or "a2e"),
            "max_images": max(1, min(int(n), 4))}
    if name:
        body["name"] = name
    d = _call("POST", "/api/v1/userText2Image/start", body, idempotent=False, quiet=quiet)
    items = d.get("data") if isinstance(d.get("data"), list) else [d.get("data")]
    ids = [it["_id"] for it in items if isinstance(it, dict) and it.get("_id")]
    if not ids:
        raise VNError(f"task id 를 받지 못했습니다: {str(d)[:200]}")
    return ids


def wait(task_id: str, max_sec: int = POLL_MAX_SEC,
         on_progress=None, quiet: bool = False) -> list[str]:
    """폴링 → 완료 시 image_urls. 경과 시간·상태를 진행 표시한다(18).

    on_progress(elapsed_sec: float, status: str) 로 외부(웹 진행 조회 등)에 상태를 넘길 수 있다.
    """
    started = time.monotonic()
    deadline = started + max_sec
    tty = False
    try:
        tty = bool(sys.stdout.isatty())
    except Exception:
        tty = False
    last_note = -99.0
    dirty = False
    try:
        while time.monotonic() < deadline:
            d = _call("GET", f"/api/v1/userText2Image/{task_id}", timeout=30, quiet=quiet)
            rec = d.get("data")
            if isinstance(rec, list):
                rec = rec[0] if rec else {}
            rec = rec if isinstance(rec, dict) else {}
            st = str(rec.get("current_status", "")).lower()
            elapsed = time.monotonic() - started
            if callable(on_progress):
                try:
                    on_progress(elapsed, st)
                except Exception:
                    pass
            if st == "completed" or (rec.get("image_urls") and st not in ("failed", "failure")):
                urls = [u for u in rec.get("image_urls", []) if isinstance(u, str) and u.startswith("https://")]
                if urls:
                    return urls
                raise VNError("완료됐지만 image_urls 가 비어 있습니다.")
            if st in ("failed", "failure"):
                raise VNError(f"생성 실패(작업 {task_id}): {str(rec.get('failed_message', ''))[:150]}")
            if not quiet:
                line = f"  생성 대기 {elapsed:.0f}초 · 상태 {st or '조회중'} · 작업 {task_id[-6:]}"
                if tty:
                    try:
                        print("\r" + line.ljust(58), end="", flush=True)
                        dirty = True
                    except Exception:
                        pass
                elif elapsed - last_note >= 30:   # 비 tty(서버 로그)에서는 30초마다 한 줄
                    _say(line)
                    last_note = elapsed
            time.sleep(POLL_SEC)
    finally:
        if dirty:
            try:
                print("\r" + " " * 58 + "\r", end="", flush=True)
            except Exception:
                pass
    raise VNError(f"생성 대기 시간 초과({max_sec}초) — 작업 {task_id} "
                  f"(--refetch 로 나중에 다시 받을 수 있습니다)")


def _fetch_bytes(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "vn-studio/1.0"})   # 토큰 미포함(CDN)
    try:
        with _DL.open(req, timeout=timeout) as r:
            data = r.read(DL_CAP + 1)
    except urllib.error.HTTPError as e:
        if e.code in RETRY_CODES:
            raise _Transient(f"결과 다운로드 HTTP {e.code}", e.code, _retry_after(e.headers))
        raise VNError(f"결과 다운로드 HTTP {e.code}")
    except urllib.error.URLError as e:
        raise _Transient(f"결과 다운로드 연결 실패: {e.reason}", None, None, True)
    if len(data) > DL_CAP:
        raise VNError("결과 이미지가 30MB 를 초과합니다.")
    return data


def download(url: str, dest: Path, quiet: bool = True) -> Path:
    """결과 이미지 저장 — 일시 오류는 지수 백오프로 재시도한다(9).

    저장은 임시 파일에 다 받은 뒤 교체하는 원자적 쓰기다. 받는 도중 끊기거나 창을 닫아도
    반쪽짜리 이미지가 후보 폴더에 남지 않는다(반쪽 파일은 이미 과금된 결과를 잃은 것처럼 보인다).
    """
    if not url.startswith("https://"):
        raise VNError(f"https 가 아닌 결과 URL 거부: {url[:80]}")
    for attempt in range(RETRY_MAX + 1):
        try:
            data = _fetch_bytes(url, 120)
            break
        except _Transient as e:
            if attempt >= RETRY_MAX:
                raise VNError(str(e)) from e
            delay = _backoff(attempt, e.retry_after)
            _say(f"  다운로드 일시 오류 — {delay:.0f}초 후 재시도 {attempt + 1}/{RETRY_MAX}", quiet)
            time.sleep(delay)
    atomic_write_bytes(dest, data)
    return Path(dest)


def _ext(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for e in (".png", ".jpg", ".jpeg", ".webp"):
        if path.endswith(e):
            return e
    return ".png"


def _download_all(task_id: str, urls: list[str], out_dir: Path, quiet: bool) -> tuple[list[Path], list[str]]:
    """한 task 의 결과를 내려받는다 — 개별 실패는 경고로 모으고 나머지는 살린다(11)."""
    saved, warns = [], []
    for i, url in enumerate(urls):
        try:
            saved.append(download(url, out_dir / f"mf_{task_id[-6:]}_{i + 1}{_ext(url)}", quiet=quiet))
        except (RuntimeError, OSError) as e:
            warns.append(f"작업 {task_id[-6:]} {i + 1}번째 이미지 저장 실패: {e}")
    return saved, warns


def generate_to_dir(prompt: str, out_dir: Path, n: int = 1, name: str = "",
                    long_edge: int | None = None, negative: bool = True,
                    scene_id: str = "", on_progress=None, quiet: bool = False) -> GenResult:
    """생성→대기→다운로드. 일부만 성공해도 저장된 파일과 경고를 함께 돌려준다(11)."""
    out_dir = Path(out_dir)
    sent = apply_negative(prompt, negative)
    plan = size_plan(long_edge)
    w, h = plan["width"], plan["height"]
    model = str(_cfg().get("model", "") or "a2e")
    # 크기 경고는 start() 가 출력한다. 여기서는 호출부(웹·CLI)가 그대로 볼 수 있게 결과에 싣되,
    # 실패 메시지에는 섞지 않는다(실패 사유가 긴 안내문에 묻히지 않게).
    size_warns: list[str] = list(size_warnings(plan))
    warns: list[str] = []
    capped = {"capped": True, "want_px": plan["want"], "cap_px": plan["cap"]} if plan["capped"] else {}
    task_ids = start(sent, n=n, name=name, long_edge=long_edge, negative=False, quiet=quiet)
    if scene_id:
        record_tasks(scene_id, task_ids, w, h)   # 다운로드 전에 남겨야 유실 시 재수령이 가능하다(10)
    saved: list[Path] = []
    for tid in task_ids:
        try:
            urls = wait(tid, on_progress=on_progress, quiet=quiet)
        except RuntimeError as e:
            warns.append(f"작업 {tid[-6:]}: {e}")
            log_usage({"scene_id": scene_id, "task_id": tid, "requested": n, "saved": 0,
                       "ok": False, "model": model, "width": w, "height": h,
                       "billable": True, "error": str(e)[:200], **capped})
            write_gen_meta(out_dir, {"created_at": _now(), "scene_id": scene_id, "task_id": tid,
                                     "prompt": sent, "model": model, "width": w, "height": h,
                                     "files": [], "status": "failed", "error": str(e)[:200],
                                     **capped})
            continue
        files, w2 = _download_all(tid, urls, out_dir, quiet)
        saved += files
        warns += w2
        log_usage({"scene_id": scene_id, "task_id": tid, "requested": n, "saved": len(files),
                   "ok": bool(files) and not w2, "model": model, "width": w, "height": h,
                   "billable": True, "error": "; ".join(w2)[:200], **capped})
        write_gen_meta(out_dir, {"created_at": _now(), "scene_id": scene_id, "task_id": tid,
                                 "prompt": sent, "model": model, "width": w, "height": h,
                                 "files": [f.name for f in files], **capped,
                                 "status": "ok" if files and not w2 else ("partial" if files else "failed"),
                                 "error": "; ".join(w2)[:200]})
    if not saved:
        raise VNError("생성된 이미지가 없습니다." + (" " + " / ".join(warns) if warns else ""))
    return GenResult(saved, size_warns + warns, task_ids)


def fetch_task_images(task_id: str, out_dir: Path | None = None, scene_id: str = "",
                      on_progress=None, quiet: bool = False) -> GenResult:
    """이미 생성된(과금된) task 의 결과만 다시 내려받는다(10) — 재생성하지 않는다."""
    task_id = str(task_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", task_id):
        raise VNError(f"task id 형식이 올바르지 않습니다: {task_id[:40]!r}")
    if out_dir is None:
        if not scene_id:
            raise VNError("저장 폴더(out_dir) 또는 scene_id 가 필요합니다.")
        out_dir = RAW_DIR / _scene_path(scene_id).stem
    out_dir = Path(out_dir)
    urls = wait(task_id, on_progress=on_progress, quiet=quiet)
    saved, warns = _download_all(task_id, urls, out_dir, quiet)
    log_usage({"scene_id": scene_id, "task_id": task_id, "requested": len(urls), "saved": len(saved),
               "ok": bool(saved) and not warns, "model": str(_cfg().get("model", "") or "a2e"),
               "billable": False, "refetch": True, "error": "; ".join(warns)[:200]})
    write_gen_meta(out_dir, {"created_at": _now(), "scene_id": scene_id, "task_id": task_id,
                             "prompt": "", "model": str(_cfg().get("model", "") or "a2e"),
                             "files": [f.name for f in saved], "status": "refetch",
                             "error": "; ".join(warns)[:200]})
    if not saved:
        raise VNError(f"작업 {task_id} 에서 받은 이미지가 없습니다." +
                      (" " + " / ".join(warns) if warns else ""))
    return GenResult(saved, warns, [task_id])


def refetch_scene(scene_id: str, on_progress=None, quiet: bool = False) -> GenResult:
    """장면에 기록된 task 들로 결과를 다시 받는다(10) — 새 생성 없음(무과금)."""
    ids = scene_task_ids(scene_id)
    if not ids:
        raise VNError(f"{scene_id} 에 기록된 MakeFun task 가 없습니다. (기록 이전 생성분은 재수령 불가)")
    out_dir = RAW_DIR / _scene_path(scene_id).stem
    saved: list[Path] = []
    warns: list[str] = []
    tasks: list[str] = []
    for tid in reversed(ids):   # 최근 작업부터
        try:
            got = fetch_task_images(tid, out_dir, scene_id, on_progress=on_progress, quiet=quiet)
            saved += list(got)
            warns += got.warnings
            tasks.append(tid)
        except RuntimeError as e:
            warns.append(f"작업 {tid[-6:]}: {e}")
    if not saved:
        raise VNError(f"{scene_id}: 재수령한 이미지가 없습니다." +
                      (" " + " / ".join(warns) if warns else ""))
    return GenResult(saved, warns, tasks)


def scene_prompt(scene_id: str) -> str:
    sc = _load_scene(scene_id)
    return str((sc.get("prompt", {}) or {}).get("grok_output", "")).strip()


def generate_for_scene(scene_id: str, n: int = 1, long_edge: int | None = None,
                       negative: bool = True, on_progress=None, quiet: bool = False) -> GenResult:
    """장면의 이미지 프롬프트로 생성해 images/raw/<scene>/ 에 저장."""
    p = _scene_path(scene_id)
    if not p.exists():
        raise VNError(f"장면 파일이 없습니다: {scene_id}")
    prompt = scene_prompt(scene_id)
    if not prompt:
        raise VNError(f"{scene_id} 에 이미지 프롬프트가 없습니다. 먼저 프롬프트를 생성하세요.")
    return generate_to_dir(prompt, RAW_DIR / p.stem, n=n, name=scene_id, long_edge=long_edge,
                           negative=negative, scene_id=scene_id, on_progress=on_progress, quiet=quiet)


# --- 중복 과금 방지: 생성 작업 상태기계(gen_jobs) 연동 ------------------------
# 웹 스튜디오는 gen_jobs 로 "이 장면은 지금 생성 중" 을 표시해 폰과 PC 가 동시에 눌러도
# 과금이 한 번만 되게 막는다. CLI 는 별도 프로세스라 그 메모리 표시를 볼 수 없다 —
# 프로세스 경계를 넘는 방어는 gen_jobs 가 잡는 잠금 파일(logs/gen_locks/<scene_id>.lock)이고,
# CLI 경로도 그 관문(claim)을 통과하기 때문에 서버 밖에서 같은 장면을 또 굽지 못한다.
# gen_jobs 가 없는 환경(이 모듈만 복제된 자가진단 등)에서는 잠금 없이 통과한다.

def _jobs():
    try:
        import gen_jobs
    except ImportError:
        return None
    return gen_jobs


@contextlib.contextmanager
def claim_scene(scene_id: str, label: str = "생성"):
    """같은 장면의 동시 생성을 막는 선점을 잡는다(웹·CLI 공통).

    이미 진행 중이면 gen_jobs 가 오류를 던지고, 그것을 그대로 올려 보낸다(중복 과금 차단).
    선점 해제는 gen_jobs.claimed 가 성공·실패 어느 쪽에서도 책임진다.
    gen_jobs 를 불러올 수 없는 환경에서만 잠금 없이 통과한다(yield False).
    """
    jobs = _jobs()
    if not scene_id or jobs is None:
        yield False
        return
    with jobs.claimed(scene_id, label):
        yield True


# --- 배치(13) ---------------------------------------------------------------

def _has_images(scene_id: str, sc: dict) -> bool:
    """이 장면에 이미 이미지가 있는가 — 있으면 과금 대상에서 뺀다(중복 과금 방지).

    선택본 판정은 vn_core.selected_of 하나를 쓴다(assets 가 손상돼 dict 가 아닌 장면에서도
    예외 없이 "" 로 떨어진다 — 여기서 터지면 배치 생성이 통째로 멈춘다).
    """
    assets = sc.get("assets") if isinstance(sc.get("assets"), dict) else {}
    if (assets.get("raw_images") or []) or selected_of(sc):
        return True
    folder = RAW_DIR / scene_id
    if folder.exists():   # 미등록 파일이 이미 있으면 중복 과금을 피한다
        return any(f.suffix.lower() in IMAGE_EXTS for f in folder.glob("*"))
    return False


def pending_scenes() -> list[str]:
    """프롬프트가 있고 아직 이미지가 없는 장면(승인 잠금 제외).

    훑기는 vn_core.iter_scenes 하나를 쓴다 — 손상 파일을 건너뛰는 태도까지 저장소 공통이라,
    같은 프로젝트가 화면마다 다른 개수로 보이지 않는다(그리고 과금 대상 판단은 멈추지 않는다).
    """
    out = []
    for p, sc in iter_scenes():
        if sc.get("status") == "APPROVED":
            continue
        if not str((sc.get("prompt", {}) or {}).get("grok_output", "")).strip():
            continue
        if _has_images(p.stem, sc):
            continue
        out.append(p.stem)
    return out


def generate_all_pending(n: int = 1, limit: int = 0, long_edge: int | None = None,
                         negative: bool = True, dry_run: bool = False, quiet: bool = False,
                         claim: bool = True) -> dict:
    """대기 장면을 순회 생성 — 한 장면이 실패해도 다음 장면으로 넘어간다(13).

    claim=True 면 장면마다 gen_jobs 표시를 잡는다(웹에서 생성 중인 장면을 CLI 가 또 굽지 않게).
    크기 경고는 --dry-run 에서도 먼저 보여 준다 — 과금 전에 알아야 의미가 있다.
    """
    targets = pending_scenes()
    if limit and limit > 0:
        targets = targets[:limit]
    size_warns = size_warnings(long_edge=long_edge)
    result = {"planned": targets, "done": {}, "failed": {}, "warnings": [],
              "size_warnings": size_warns, "dry_run": dry_run}
    if dry_run or not targets:
        for msg in size_warns:        # 실제 생성 때는 start() 가 장면마다 같은 경고를 낸다
            _say("⚠ 생성 크기 — " + msg, quiet)
        return result
    for sid in targets:
        _say(f"[{sid}] 생성 시작 ({targets.index(sid) + 1}/{len(targets)})", quiet)
        try:
            if claim:
                with claim_scene(sid):
                    files = generate_for_scene(sid, n=n, long_edge=long_edge,
                                               negative=negative, quiet=quiet)
            else:
                files = generate_for_scene(sid, n=n, long_edge=long_edge,
                                           negative=negative, quiet=quiet)
            result["done"][sid] = [f.name for f in files]
            # 크기 경고는 위에서 한 번 알렸으니 장면마다 되풀이하지 않는다
            result["warnings"] += [f"{sid}: {w}" for w in getattr(files, "warnings", [])
                                   if w not in size_warns]
        except RuntimeError as e:
            result["failed"][sid] = str(e)
            _say(f"[{sid}] 실패 — {e}", quiet)
    return result


# --- 사전 점검(16) ----------------------------------------------------------

def check(online: bool = False) -> dict:
    """토큰 형식·환경변수·설정 점검. online=True 일 때만 무과금 조회 1회를 시도한다."""
    rep = {"ok": True, "lines": []}

    def add(ok: bool, msg: str, fatal: bool = True) -> None:
        rep["lines"].append(("OK  " if ok else "FAIL") + " " + msg)
        if not ok and fatal:
            rep["ok"] = False

    raw = os.environ.get(TOKEN_ENV, "")
    t = raw.strip()
    if not t:
        add(False, f"{TOKEN_ENV} 환경변수가 없습니다. "
                   f'PowerShell: $env:{TOKEN_ENV}="sk_..." (영구 등록은 setx)')
    else:
        add(True, f"{TOKEN_ENV} 설정됨 (길이 {len(t)}, 앞 2자 {t[:2]}**)")   # 토큰 본문은 출력하지 않는다
        add(raw == t, "토큰 앞뒤 공백 없음 — 공백이 있으면 401 이 납니다.", fatal=False)
        add(not (t[0] in "\"'" or t[-1] in "\"'"), "토큰에 따옴표가 섞이지 않음", fatal=False)
        add(len(t) >= 16 and " " not in t, "토큰 형식이 그럴듯함(공백 없음·길이 16+)")
    try:
        add(True, f"base_url: {base_url()}")
    except VNError as e:
        add(False, str(e))
    cfg = _cfg()
    add(bool(cfg), f"manifest image_generator 설정 있음 (model={cfg.get('model', '') or 'a2e'})", fatal=False)
    plan = size_plan()
    w, h = plan["width"], plan["height"]
    add(True, f"생성 크기 {w}x{h} (요청 {plan['want']}px · 실제 긴 변 {plan['long']}px · "
              f"상한 {plan['cap']}px{'(기본값)' if plan['cap_is_default'] else ''})")
    for msg in size_warnings(plan):      # 지금 생성하면 돈이 새는 조합 — 점검을 실패로 만든다
        add(False, msg)
    if not plan["capped"]:
        if plan["cap_is_default"]:       # 아직 안 걸렸을 뿐, 인화 상향과 동시에 걸리는 함정
            rep["lines"].append(
                f"주의 상한이 기본값 {SIZE_MAX_PX}px 입니다. 인화하려고 "
                f"output.min_long_edge_px 를 1800(4×6)·2250(5×7)·3600(8×10) 으로 올리면 "
                f"image_generator.max_long_edge_px 도 함께 올려야 합니다 "
                f"— 안 올리면 요청이 {SIZE_MAX_PX}px 로 깎인 채 과금됩니다.")
        if plan["long"] < 1748:   # 10x15cm 300DPI 기준 긴 변
            rep["lines"].append("주의 10x15cm 300DPI 인화에는 긴 변 1748px 이상 권장 "
                                "— manifest.output.min_long_edge_px 를 올리세요.")
        note = _print_note(w, h)
        if note:
            rep["lines"].append("정보 " + note)
    if online:
        if not t:
            add(False, "온라인 점검 생략 — 토큰이 없습니다.")
        else:
            # 이미지 생성이 아닌 조회 호출 1회(무과금). 401 이면 토큰 문제로 판정.
            try:
                _call("GET", "/api/v1/userText2Image/000000000000000000000000", timeout=20)
                add(True, "온라인 점검: 인증 통과")
            except RuntimeError as e:
                msg = str(e)
                add("401" not in msg, f"온라인 점검 응답: {msg[:120]}")
    return rep


# --- CLI --------------------------------------------------------------------

def _rel(p: Path) -> str:
    """출력용 짧은 경로 (콘솔 인코딩 방어는 vn_core import 시 이미 적용된다)."""
    return str(p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p)


def main() -> int:
    ap = argparse.ArgumentParser(description="MakeFun 텍스트→이미지")
    ap.add_argument("scene", nargs="?", help="장면 ID (예: SCENE-001)")
    ap.add_argument("--n", type=int, default=1, help="생성 장수(1~4)")
    ap.add_argument("--prompt", help="장면 대신 직접 프롬프트로 생성")
    ap.add_argument("--out", help="--prompt 모드의 저장 경로/폴더")
    ap.add_argument("--long-edge", type=int, default=0,
                    help="긴 변 픽셀(기본: manifest.output.min_long_edge_px). "
                         "image_generator.max_long_edge_px 상한을 넘으면 깎이고 경고가 뜹니다")
    ap.add_argument("--no-negative", action="store_true",
                    help="이미지 내 글자 억제 문구를 프롬프트에 덧붙이지 않음")
    ap.add_argument("--all-pending", action="store_true",
                    help="프롬프트가 있고 이미지가 없는 장면을 일괄 생성")
    ap.add_argument("--limit", type=int, default=0, help="--all-pending 최대 장면 수")
    ap.add_argument("--dry-run", action="store_true", help="--all-pending 대상만 표시(호출 없음)")
    ap.add_argument("--refetch", action="store_true",
                    help="장면에 기록된 task 로 결과만 다시 받기(재생성 없음)")
    ap.add_argument("--task", help="특정 task id 의 결과만 받기")
    ap.add_argument("--check", action="store_true", help="토큰·설정 사전 점검")
    ap.add_argument("--online", action="store_true", help="--check 에서 조회 1회로 인증까지 확인")
    ap.add_argument("--quiet", action="store_true", help="진행 표시 끄기")
    a = ap.parse_args()
    neg = not a.no_negative
    long_edge = a.long_edge or None

    try:
        if a.check:
            rep = check(online=a.online)
            for line in rep["lines"]:
                print(line)
            return 0 if rep["ok"] else 1

        if a.all_pending:
            res = generate_all_pending(n=a.n, limit=a.limit, long_edge=long_edge,
                                       negative=neg, dry_run=a.dry_run, quiet=a.quiet)
            if not res["planned"]:
                print("대기 중인 장면이 없습니다(프롬프트 있고 이미지 없는 장면 기준).")
                return 0
            if a.dry_run:
                print("생성 대상:", ", ".join(res["planned"]))
                return 1 if res["size_warnings"] else 0
            for sid, names in res["done"].items():
                print(f"완료 {sid}: {len(names)}장")
            for w in res["warnings"]:
                print("경고:", w)
            for sid, msg in res["failed"].items():
                print(f"실패 {sid}: {msg}")
            return 1 if res["failed"] else 0

        if a.task:
            out = Path(a.out) if a.out else None
            with claim_scene(a.scene or "", "재수령"):
                files = fetch_task_images(a.task, out, a.scene or "", quiet=a.quiet)
        elif a.refetch:
            if not a.scene:
                ap.error("--refetch 에는 장면 ID 가 필요합니다.")
            with claim_scene(a.scene, "재수령"):
                files = refetch_scene(a.scene, quiet=a.quiet)
        elif a.prompt:
            out = Path(a.out) if a.out else ROOT / "scratch"
            files = generate_to_dir(a.prompt, out if out.is_dir() or not out.suffix else out.parent,
                                    n=a.n, long_edge=long_edge, negative=neg, quiet=a.quiet)
            if a.out and Path(a.out).suffix and files:
                files[0].replace(Path(a.out))
                files[0] = Path(a.out)
        elif a.scene:
            with claim_scene(a.scene):     # 웹에서 같은 장면을 생성 중이면 여기서 막힌다
                files = generate_for_scene(a.scene, n=a.n, long_edge=long_edge,
                                           negative=neg, quiet=a.quiet)
        else:
            ap.error("장면 ID 또는 --prompt 가 필요합니다.")
            return 2
    except RuntimeError as e:
        print("오류:", e)
        return 1

    for w in getattr(files, "warnings", []):
        print("경고:", w)
    for f in files:
        print("저장:", _rel(f))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
