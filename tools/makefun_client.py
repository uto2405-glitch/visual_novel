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
  python tools/makefun_client.py --check [--online]    # 토큰·설정 사전 점검
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project" / "manifest.json"
SCENES_DIR = ROOT / "project" / "scenes"
RAW_DIR = ROOT / "images" / "raw"
USAGE_LOG = ROOT / "logs" / "makefun_usage.jsonl"
META_NAME = "_gen_meta.json"
TOKEN_ENV = "MAKEFUN_API_TOKEN"
DEFAULT_BASE = "https://makefun.ai"
POLL_SEC = 4
POLL_MAX_SEC = 300
DL_CAP = 30 * 1024 * 1024
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
SCENE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")

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
TASKS_MAX = 20              # 장면 assets.makefun_tasks 보존 개수

_WRITE_LOCK = threading.RLock()   # 대장·메타·장면 JSON 의 read-modify-write 직렬화


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
        raise RuntimeError(f"{TOKEN_ENV} 환경변수가 없습니다. makefun.ai Account > API Token 발급 후 "
                           f'PowerShell: $env:{TOKEN_ENV}="sk_..." 로 설정하세요.')
    return t


def _cfg() -> dict:
    try:
        mf = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return mf.get("image_generator", {}) if isinstance(mf, dict) else {}
    except Exception:
        return {}


def base_url() -> str:
    u = str((_cfg().get("api", {}) or {}).get("base_url", "") or DEFAULT_BASE).rstrip("/")
    if not u.startswith("https://"):
        raise RuntimeError(f"MakeFun base_url 은 https 만 허용합니다: {u}")
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
            raise RuntimeError("MakeFun 인증 실패(401) — 토큰을 확인하세요.")
        if e.code in RETRY_CODES:
            raise _Transient(f"MakeFun HTTP {e.code}: {detail}", e.code, _retry_after(e.headers))
        raise RuntimeError(f"MakeFun HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        # DNS·연결거부는 요청이 나가기 전 실패 — POST 재시도해도 이중 생성 위험이 없다.
        presend = isinstance(e.reason, (socket.gaierror, ConnectionRefusedError))
        raise _Transient(f"MakeFun 연결 실패: {e.reason}", None, None, presend)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise RuntimeError("MakeFun 응답이 JSON 이 아닙니다.")
    if not isinstance(data, dict) or data.get("code") not in (0, None):
        raise RuntimeError(f"MakeFun 오류 응답: {str(data)[:200]}")
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
                raise RuntimeError(str(e)) from e
            delay = _backoff(attempt, e.retry_after)
            _say(f"  일시 오류 — {delay:.0f}초 후 재시도 {attempt + 1}/{RETRY_MAX} ({e})", quiet)
            time.sleep(delay)
    raise RuntimeError("MakeFun 재시도 한도를 초과했습니다.")   # 도달하지 않음(방어)


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


def _size_from_manifest(long_edge: int | None = None) -> tuple[int, int]:
    """출력 규격(기본 2:3 세로)과 manifest.output.min_long_edge_px 에 맞는 생성 크기."""
    ar, want = "2:3", DEFAULT_LONG_EDGE
    try:
        mf = json.loads(MANIFEST.read_text(encoding="utf-8"))
        out = mf.get("output", {}) if isinstance(mf, dict) else {}
        ar = str(out.get("aspect_ratio", "2:3") or "2:3")
        want = int(out.get("min_long_edge_px", DEFAULT_LONG_EDGE) or DEFAULT_LONG_EDGE)
    except Exception:
        pass
    if long_edge:
        want = int(long_edge)
    try:
        w, h = (int(x) for x in ar.split(":"))
        if w <= 0 or h <= 0:
            raise ValueError(ar)
    except Exception:
        w, h = 2, 3
    long_px = _align8(want)
    if h >= w:
        return max(8, (long_px * w // h) // 8 * 8), long_px
    return long_px, max(8, (long_px * h // w) // 8 * 8)


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
        with _WRITE_LOCK:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": _now(), **record}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def write_gen_meta(out_dir: Path, entry: dict) -> None:
    """생성 메타데이터를 images/raw/<scene>/_gen_meta.json 에 누적(12)."""
    try:
        path = Path(out_dir) / META_NAME
        with _WRITE_LOCK:
            doc = {}
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    doc = loaded
            except Exception:
                doc = {}
            entries = doc.get("entries")
            if not isinstance(entries, list):
                entries = []
            entries.append(entry)
            doc["entries"] = entries[-META_MAX_ENTRIES:]
            doc.setdefault("scene_id", entry.get("scene_id", ""))
            doc["updated_at"] = _now()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)
    except Exception:
        pass


def _scene_path(scene_id: str) -> Path:
    if not SCENE_ID_RE.fullmatch(str(scene_id or "")):
        raise RuntimeError(f"장면 ID 형식이 올바르지 않습니다: {str(scene_id)[:40]!r}")
    return SCENES_DIR / f"{scene_id}.json"


def _load_scene(scene_id: str) -> dict:
    sc = json.loads(_scene_path(scene_id).read_text(encoding="utf-8"))
    if not isinstance(sc, dict):
        raise RuntimeError(f"{scene_id}: JSON 최상위가 객체가 아닙니다.")
    return sc


def record_tasks(scene_id: str, task_ids: list[str], width: int = 0, height: int = 0) -> None:
    """생성 task id 를 장면 assets.makefun_tasks 에 남긴다(10).

    다운로드만 실패했을 때 재생성(재과금) 없이 fetch_task_images 로 다시 받기 위한 기록.
    """
    if not scene_id or not task_ids:
        return
    try:
        with _WRITE_LOCK:
            path = _scene_path(scene_id)
            sc = _load_scene(scene_id)
            assets = sc.get("assets")
            if not isinstance(assets, dict):
                assets = {}
                sc["assets"] = assets
            tasks = assets.get("makefun_tasks")
            if not isinstance(tasks, list):
                tasks = []
            known = {t.get("task_id") for t in tasks if isinstance(t, dict)}
            for tid in task_ids:
                if not tid or tid in known:
                    continue
                known.add(tid)
                tasks.append({"task_id": tid, "created_at": _now(), "width": width, "height": height})
            del tasks[:-TASKS_MAX]
            assets["makefun_tasks"] = tasks
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(sc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)
    except Exception:
        pass   # 기록 실패로 이미 과금된 생성을 중단시키지 않는다


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
    """생성 시작 → task id 목록."""
    w, h = _size_from_manifest(long_edge)
    body = {"prompt": apply_negative(prompt, negative), "width": w, "height": h,
            "model_type": str(_cfg().get("model", "") or "a2e"),
            "max_images": max(1, min(int(n), 4))}
    if name:
        body["name"] = name
    d = _call("POST", "/api/v1/userText2Image/start", body, idempotent=False, quiet=quiet)
    items = d.get("data") if isinstance(d.get("data"), list) else [d.get("data")]
    ids = [it["_id"] for it in items if isinstance(it, dict) and it.get("_id")]
    if not ids:
        raise RuntimeError(f"task id 를 받지 못했습니다: {str(d)[:200]}")
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
                raise RuntimeError("완료됐지만 image_urls 가 비어 있습니다.")
            if st in ("failed", "failure"):
                raise RuntimeError(f"생성 실패(작업 {task_id}): {str(rec.get('failed_message', ''))[:150]}")
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
    raise RuntimeError(f"생성 대기 시간 초과({max_sec}초) — 작업 {task_id} "
                       f"(--refetch 로 나중에 다시 받을 수 있습니다)")


def _fetch_bytes(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "vn-studio/1.0"})   # 토큰 미포함(CDN)
    try:
        with _DL.open(req, timeout=timeout) as r:
            data = r.read(DL_CAP + 1)
    except urllib.error.HTTPError as e:
        if e.code in RETRY_CODES:
            raise _Transient(f"결과 다운로드 HTTP {e.code}", e.code, _retry_after(e.headers))
        raise RuntimeError(f"결과 다운로드 HTTP {e.code}")
    except urllib.error.URLError as e:
        raise _Transient(f"결과 다운로드 연결 실패: {e.reason}", None, None, True)
    if len(data) > DL_CAP:
        raise RuntimeError("결과 이미지가 30MB 를 초과합니다.")
    return data


def download(url: str, dest: Path, quiet: bool = True) -> Path:
    """결과 이미지 저장 — 일시 오류는 지수 백오프로 재시도한다(9)."""
    if not url.startswith("https://"):
        raise RuntimeError(f"https 가 아닌 결과 URL 거부: {url[:80]}")
    for attempt in range(RETRY_MAX + 1):
        try:
            data = _fetch_bytes(url, 120)
            break
        except _Transient as e:
            if attempt >= RETRY_MAX:
                raise RuntimeError(str(e)) from e
            delay = _backoff(attempt, e.retry_after)
            _say(f"  다운로드 일시 오류 — {delay:.0f}초 후 재시도 {attempt + 1}/{RETRY_MAX}", quiet)
            time.sleep(delay)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


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
        except RuntimeError as e:
            warns.append(f"작업 {task_id[-6:]} {i + 1}번째 이미지 저장 실패: {e}")
    return saved, warns


def generate_to_dir(prompt: str, out_dir: Path, n: int = 1, name: str = "",
                    long_edge: int | None = None, negative: bool = True,
                    scene_id: str = "", on_progress=None, quiet: bool = False) -> GenResult:
    """생성→대기→다운로드. 일부만 성공해도 저장된 파일과 경고를 함께 돌려준다(11)."""
    out_dir = Path(out_dir)
    sent = apply_negative(prompt, negative)
    w, h = _size_from_manifest(long_edge)
    model = str(_cfg().get("model", "") or "a2e")
    task_ids = start(sent, n=n, name=name, long_edge=long_edge, negative=False, quiet=quiet)
    if scene_id:
        record_tasks(scene_id, task_ids, w, h)   # 다운로드 전에 남겨야 유실 시 재수령이 가능하다(10)
    saved: list[Path] = []
    warns: list[str] = []
    for tid in task_ids:
        try:
            urls = wait(tid, on_progress=on_progress, quiet=quiet)
        except RuntimeError as e:
            warns.append(f"작업 {tid[-6:]}: {e}")
            log_usage({"scene_id": scene_id, "task_id": tid, "requested": n, "saved": 0,
                       "ok": False, "model": model, "width": w, "height": h,
                       "billable": True, "error": str(e)[:200]})
            write_gen_meta(out_dir, {"created_at": _now(), "scene_id": scene_id, "task_id": tid,
                                     "prompt": sent, "model": model, "width": w, "height": h,
                                     "files": [], "status": "failed", "error": str(e)[:200]})
            continue
        files, w2 = _download_all(tid, urls, out_dir, quiet)
        saved += files
        warns += w2
        log_usage({"scene_id": scene_id, "task_id": tid, "requested": n, "saved": len(files),
                   "ok": bool(files) and not w2, "model": model, "width": w, "height": h,
                   "billable": True, "error": "; ".join(w2)[:200]})
        write_gen_meta(out_dir, {"created_at": _now(), "scene_id": scene_id, "task_id": tid,
                                 "prompt": sent, "model": model, "width": w, "height": h,
                                 "files": [f.name for f in files],
                                 "status": "ok" if files and not w2 else ("partial" if files else "failed"),
                                 "error": "; ".join(w2)[:200]})
    if not saved:
        raise RuntimeError("생성된 이미지가 없습니다." + (" " + " / ".join(warns) if warns else ""))
    return GenResult(saved, warns, task_ids)


def fetch_task_images(task_id: str, out_dir: Path | None = None, scene_id: str = "",
                      on_progress=None, quiet: bool = False) -> GenResult:
    """이미 생성된(과금된) task 의 결과만 다시 내려받는다(10) — 재생성하지 않는다."""
    task_id = str(task_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", task_id):
        raise RuntimeError(f"task id 형식이 올바르지 않습니다: {task_id[:40]!r}")
    if out_dir is None:
        if not scene_id:
            raise RuntimeError("저장 폴더(out_dir) 또는 scene_id 가 필요합니다.")
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
        raise RuntimeError(f"작업 {task_id} 에서 받은 이미지가 없습니다." +
                           (" " + " / ".join(warns) if warns else ""))
    return GenResult(saved, warns, [task_id])


def refetch_scene(scene_id: str, on_progress=None, quiet: bool = False) -> GenResult:
    """장면에 기록된 task 들로 결과를 다시 받는다(10) — 새 생성 없음(무과금)."""
    ids = scene_task_ids(scene_id)
    if not ids:
        raise RuntimeError(f"{scene_id} 에 기록된 MakeFun task 가 없습니다. (기록 이전 생성분은 재수령 불가)")
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
        raise RuntimeError(f"{scene_id}: 재수령한 이미지가 없습니다." +
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
        raise RuntimeError(f"장면 파일이 없습니다: {scene_id}")
    prompt = scene_prompt(scene_id)
    if not prompt:
        raise RuntimeError(f"{scene_id} 에 이미지 프롬프트가 없습니다. 먼저 프롬프트를 생성하세요.")
    return generate_to_dir(prompt, RAW_DIR / p.stem, n=n, name=scene_id, long_edge=long_edge,
                           negative=negative, scene_id=scene_id, on_progress=on_progress, quiet=quiet)


# --- 배치(13) ---------------------------------------------------------------

def _has_images(scene_id: str, assets: dict) -> bool:
    if (assets.get("raw_images") or []) or str(assets.get("selected_image", "") or "").strip():
        return True
    folder = RAW_DIR / scene_id
    if folder.exists():   # 미등록 파일이 이미 있으면 중복 과금을 피한다
        return any(f.suffix.lower() in IMAGE_EXTS for f in folder.glob("*"))
    return False


def pending_scenes() -> list[str]:
    """프롬프트가 있고 아직 이미지가 없는 장면(승인 잠금 제외)."""
    out = []
    if not SCENES_DIR.exists():
        return out
    for p in sorted(SCENES_DIR.glob("SCENE-*.json")):
        try:
            sc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(sc, dict) or sc.get("status") == "APPROVED":
            continue
        if not str((sc.get("prompt", {}) or {}).get("grok_output", "")).strip():
            continue
        assets = sc.get("assets", {}) or {}
        if _has_images(p.stem, assets):
            continue
        out.append(p.stem)
    return out


def generate_all_pending(n: int = 1, limit: int = 0, long_edge: int | None = None,
                         negative: bool = True, dry_run: bool = False, quiet: bool = False) -> dict:
    """대기 장면을 순회 생성 — 한 장면이 실패해도 다음 장면으로 넘어간다(13)."""
    targets = pending_scenes()
    if limit and limit > 0:
        targets = targets[:limit]
    result = {"planned": targets, "done": {}, "failed": {}, "warnings": [], "dry_run": dry_run}
    if dry_run or not targets:
        return result
    for sid in targets:
        _say(f"[{sid}] 생성 시작 ({targets.index(sid) + 1}/{len(targets)})", quiet)
        try:
            files = generate_for_scene(sid, n=n, long_edge=long_edge, negative=negative, quiet=quiet)
            result["done"][sid] = [f.name for f in files]
            result["warnings"] += [f"{sid}: {w}" for w in getattr(files, "warnings", [])]
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
    except RuntimeError as e:
        add(False, str(e))
    cfg = _cfg()
    add(bool(cfg), f"manifest image_generator 설정 있음 (model={cfg.get('model', '') or 'a2e'})", fatal=False)
    w, h = _size_from_manifest()
    add(True, f"생성 크기 {w}x{h} (긴 변 {max(w, h)}px · 상한 {_cap_px()}px)")
    if max(w, h) < 1748:   # 10x15cm 300DPI 기준 긴 변
        rep["lines"].append("주의 10x15cm 300DPI 인화에는 긴 변 1748px 이상 권장 "
                            "— manifest.output.min_long_edge_px 를 올리세요.")
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

def _console_guard() -> None:
    """비 UTF-8 콘솔에서 한글 출력이 크래시하지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p)


def main() -> int:
    _console_guard()
    ap = argparse.ArgumentParser(description="MakeFun 텍스트→이미지")
    ap.add_argument("scene", nargs="?", help="장면 ID (예: SCENE-001)")
    ap.add_argument("--n", type=int, default=1, help="생성 장수(1~4)")
    ap.add_argument("--prompt", help="장면 대신 직접 프롬프트로 생성")
    ap.add_argument("--out", help="--prompt 모드의 저장 경로/폴더")
    ap.add_argument("--long-edge", type=int, default=0,
                    help="긴 변 픽셀(기본: manifest.output.min_long_edge_px)")
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
                return 0
            for sid, names in res["done"].items():
                print(f"완료 {sid}: {len(names)}장")
            for w in res["warnings"]:
                print("경고:", w)
            for sid, msg in res["failed"].items():
                print(f"실패 {sid}: {msg}")
            return 1 if res["failed"] else 0

        if a.task:
            out = Path(a.out) if a.out else None
            files = fetch_task_images(a.task, out, a.scene or "", quiet=a.quiet)
        elif a.refetch:
            if not a.scene:
                ap.error("--refetch 에는 장면 ID 가 필요합니다.")
            files = refetch_scene(a.scene, quiet=a.quiet)
        elif a.prompt:
            out = Path(a.out) if a.out else ROOT / "scratch"
            files = generate_to_dir(a.prompt, out if out.is_dir() or not out.suffix else out.parent,
                                    n=a.n, long_edge=long_edge, negative=neg, quiet=a.quiet)
            if a.out and Path(a.out).suffix and files:
                files[0].replace(Path(a.out))
                files[0] = Path(a.out)
        elif a.scene:
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
