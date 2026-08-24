#!/usr/bin/env python3
"""MakeFun AI 텍스트→이미지 클라이언트 — 파이프라인 3단계(이미지 생성) 자동화.

API: POST /api/v1/userText2Image/start → {code:0, data:[{_id,...}]}
     GET  /api/v1/userText2Image/{id}  → current_status: initialized/processing → completed/failed
토큰은 환경변수 MAKEFUN_API_TOKEN 로만 공급한다(파일 저장 금지 — 검사기 A8).
사용: python tools/makefun_client.py SCENE-001 [--n 2]
     python tools/makefun_client.py --prompt "..." --out scratch/test.png
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project" / "manifest.json"
RAW_DIR = ROOT / "images" / "raw"
TOKEN_ENV = "MAKEFUN_API_TOKEN"
DEFAULT_BASE = "https://makefun.ai"
POLL_SEC = 4
POLL_MAX_SEC = 300
DL_CAP = 30 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


_API = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())
_DL = urllib.request.build_opener(urllib.request.ProxyHandler())   # 결과 CDN 은 리다이렉트 허용(무토큰)


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


def _call(method: str, path: str, body: dict | None = None, timeout: int = 60) -> dict:
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
        raise RuntimeError(f"MakeFun HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"MakeFun 연결 실패: {e.reason}")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise RuntimeError("MakeFun 응답이 JSON 이 아닙니다.")
    if not isinstance(data, dict) or data.get("code") not in (0, None):
        raise RuntimeError(f"MakeFun 오류 응답: {str(data)[:200]}")
    return data


def _size_from_manifest() -> tuple[int, int]:
    """출력 규격(기본 2:3 세로, 긴 변 최소 1024)에 맞는 생성 크기."""
    try:
        mf = json.loads(MANIFEST.read_text(encoding="utf-8"))
        ar = str(mf.get("output", {}).get("aspect_ratio", "2:3"))
        w, h = (int(x) for x in ar.split(":"))
    except Exception:
        w, h = 2, 3
    if h >= w:
        return (1024 * w // h) // 8 * 8, 1024
    return 1024, (1024 * h // w) // 8 * 8


def start(prompt: str, n: int = 1, name: str = "") -> list[str]:
    """생성 시작 → task id 목록."""
    w, h = _size_from_manifest()
    body = {"prompt": prompt, "width": w, "height": h,
            "model_type": str(_cfg().get("model", "") or "a2e"),
            "max_images": max(1, min(int(n), 4))}
    if name:
        body["name"] = name
    d = _call("POST", "/api/v1/userText2Image/start", body)
    items = d.get("data") if isinstance(d.get("data"), list) else [d.get("data")]
    ids = [it["_id"] for it in items if isinstance(it, dict) and it.get("_id")]
    if not ids:
        raise RuntimeError(f"task id 를 받지 못했습니다: {str(d)[:200]}")
    return ids


def wait(task_id: str) -> list[str]:
    """폴링 → 완료 시 image_urls."""
    deadline = time.monotonic() + POLL_MAX_SEC
    while time.monotonic() < deadline:
        d = _call("GET", f"/api/v1/userText2Image/{task_id}", timeout=30)
        rec = d.get("data")
        if isinstance(rec, list):
            rec = rec[0] if rec else {}
        rec = rec if isinstance(rec, dict) else {}
        st = str(rec.get("current_status", "")).lower()
        if st == "completed" or (rec.get("image_urls") and st not in ("failed", "failure")):
            urls = [u for u in rec.get("image_urls", []) if isinstance(u, str) and u.startswith("https://")]
            if urls:
                return urls
            raise RuntimeError("완료됐지만 image_urls 가 비어 있습니다.")
        if st in ("failed", "failure"):
            raise RuntimeError(f"생성 실패(작업 {task_id}): {str(rec.get('failed_message', ''))[:150]}")
        time.sleep(POLL_SEC)
    raise RuntimeError(f"생성 대기 시간 초과({POLL_MAX_SEC}초) — 작업 {task_id}")


def download(url: str, dest: Path) -> Path:
    if not url.startswith("https://"):
        raise RuntimeError(f"https 가 아닌 결과 URL 거부: {url[:80]}")
    req = urllib.request.Request(url, headers={"User-Agent": "vn-studio/1.0"})   # 토큰 미포함(CDN)
    with _DL.open(req, timeout=120) as r:
        data = r.read(DL_CAP + 1)
    if len(data) > DL_CAP:
        raise RuntimeError("결과 이미지가 30MB 를 초과합니다.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _ext(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for e in (".png", ".jpg", ".jpeg", ".webp"):
        if path.endswith(e):
            return e
    return ".png"


def generate_to_dir(prompt: str, out_dir: Path, n: int = 1, name: str = "") -> list[Path]:
    """생성→대기→다운로드. 저장된 파일 경로 목록."""
    saved = []
    for tid in start(prompt, n=n, name=name):
        for i, url in enumerate(wait(tid)):
            saved.append(download(url, out_dir / f"mf_{tid[-6:]}_{i + 1}{_ext(url)}"))
    if not saved:
        raise RuntimeError("생성된 이미지가 없습니다.")
    return saved


def generate_for_scene(scene_id: str, n: int = 1) -> list[Path]:
    """장면의 이미지 프롬프트로 생성해 images/raw/<scene>/ 에 저장."""
    p = ROOT / "project" / "scenes" / f"{scene_id}.json"
    if not p.exists():
        raise RuntimeError(f"장면 파일이 없습니다: {scene_id}")
    sc = json.loads(p.read_text(encoding="utf-8"))
    prompt = str(sc.get("prompt", {}).get("grok_output", "")).strip()
    if not prompt:
        raise RuntimeError(f"{scene_id} 에 이미지 프롬프트가 없습니다. 먼저 프롬프트를 생성하세요.")
    return generate_to_dir(prompt, RAW_DIR / scene_id, n=n, name=scene_id)


def main() -> int:
    ap = argparse.ArgumentParser(description="MakeFun 텍스트→이미지")
    ap.add_argument("scene", nargs="?", help="장면 ID (예: SCENE-001)")
    ap.add_argument("--n", type=int, default=1, help="생성 장수(1~4)")
    ap.add_argument("--prompt", help="장면 대신 직접 프롬프트로 생성")
    ap.add_argument("--out", help="--prompt 모드의 저장 경로/폴더")
    a = ap.parse_args()
    if a.prompt:
        out = Path(a.out) if a.out else ROOT / "scratch"
        files = generate_to_dir(a.prompt, out if out.is_dir() or not out.suffix else out.parent, n=a.n)
        if a.out and Path(a.out).suffix and files:
            files[0].replace(Path(a.out))
            files[0] = Path(a.out)
    elif a.scene:
        files = generate_for_scene(a.scene, n=a.n)
    else:
        ap.error("장면 ID 또는 --prompt 가 필요합니다.")
        return 2
    for f in files:
        print("저장:", f.relative_to(ROOT) if str(f).startswith(str(ROOT)) else f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
