#!/usr/bin/env python3
"""웹 스튜디오 서버 — 5단계 워크플로우의 백엔드. 프론트는 tools/studio.html.

  1) 스토리 탭   : 로컬 LLM 과 대화하며 스토리라인 작성 (local_llm)
  2) 장면 탭     : 스토리라인 → VN 텍스트 + 이미지 프롬프트 구성 (vn_compose)
  3) (외부·수동) : 이미지 생성 AI 에 프롬프트 붙여넣어 이미지 생성
  4) 장면 탭     : images/raw/<scene_id>/ 폴더 투입 → 스캔 → 선택 → 승인 도장
  5) 뷰어 탭     : 비주얼 노벨 감상

사용법:
  python tools/webapp.py [--port 8765] [--no-browser]
  python tools/webapp.py --lan            # 폰 접속 허용(PIN 자동 생성·콘솔 표시)
  python tools/webapp.py --lan --no-pin   # PIN 없이 (신뢰된 네트워크 전용)

보안:
  * 오케스트레이터는 로컬 LLM 하나뿐이라 키가 없다. 보조 엔진 토큰(MAKEFUN_API_TOKEN)은
    환경변수로만 읽고 서버 안에서만 쓰인다 — 브라우저로는 불리언조차 값 없이 전달된다.
  * 127.0.0.1 전용 바인딩 + Host 헤더 검증(DNS 리바인딩 방어) + /img·/dl 경로 탈출 차단.
  * 상태를 바꾸는 POST 는 Origin/Referer 를 자기 출처와 대조한다(CSRF 방어) — 임의 웹사이트가
    켜져 있는 스튜디오에 fetch 로 유료 생성 등을 시키지 못하게 한다.
  * 인물 대화 로그는 클라이언트 목록으로 덮어쓰지 않고 항상 저장본과 병합한다(reset:true 만 예외).
  * scene_id 는 정규식(SCENE-숫자)으로만 통과 — 경로 탈출·임의 파일 접근 차단.
  * LAN 모드는 PIN 인증이 기본. 127.0.0.1 접속은 면제(로컬 작업은 그대로 편하게).
    인증 토큰은 발급받은 기기(IP)에 묶이고 3시간 미사용 시 만료된다(슬라이딩).
    PIN 오입력은 IP 별로 세고, 5회면 1분 잠금 + 매 실패마다 0.3초 지연(무차별 대입 방지).
  * 모든 응답에 nosniff·no-referrer, 스튜디오 화면에는 CSP. CSP 는 문서마다 계산한다
    (csp_for) — 인라인 스크립트가 없는 문서는 script-src 에서 'unsafe-inline' 이 빠진다.
    /dl 은 inline 요청이 아니면 application/octet-stream 으로 내려 output/ 의 HTML 이
    동일 출처 스크립트로 실행되지 않게 한다.
  * /studio/<이름>.js 는 tools/ 아래 **평범한 이름의 .js 파일만** 내보낸다(하위 폴더·숨김·
    확장자 위장 불가, 경로 판정은 vn_core.safe_path).
  * 장면 편집(/api/set-scene)은 화이트리스트 필드만 통과한다 — status·review·assets·
    scene_id·scene_order 는 이 경로로 바뀌지 않는다(사람 승인 게이트 우회 차단).
  * 프론트는 서버 데이터를 innerHTML 로 넣지 않는다(studio.html 안전 규약).
  * 쓰기 요청은 vn_core.WRITE_LOCK 으로 직렬화된다.

계층: vn_core(경로·JSON·원자적 쓰기·장면 훑기) ← scene_ops(상태 전이·장면 생성)
      ← webapp(HTTP). 이 파일에는 **전이 규칙도 도메인 로직도 없다** — 라우트는 아래를
      부르는 얇은 어댑터다. CLI(advance_scene)는 여기서 부르지 않는다 — 한동안 그쪽이
      재수출한 이름으로 vn_core 를 썼는데, 계층 4가 계층 2를 지나 계층 0에 닿는 우회로였다.
        scene_ops    장면 상태 전이·필드 편집        vn_compose  장면 구성·대화→장면
        prompt_build 프롬프트 문자열(이미지·스토리챗)  gen_jobs    생성 작업 상태기계
        image_gen    이미지 엔진 선택(ComfyUI 기본·MakeFun 보조) — 재수령·확대·크레딧은 MakeFun 전용
        talk_store   대화 로그                        print_export/export_viewer  내보내기
      **모델에 보내는 프롬프트 문자열은 이 파일에 한 줄도 없다**(prompt_build·vn_compose 전담).

데이터 보존:
  * 대화 로그(스토리·인물)는 항상 저장본과 병합해 저장하고, 상한을 넘는 오래된 구간도
    버리지 않고 talk_<cid>.archive.jsonl 로 옮긴 뒤에만 잘라낸다.
  * 이미지 생성 스레드는 daemon 이라 **Ctrl+C 로 서버를 끄면 즉시 끊긴다.** 종료 시 진행 중인
    작업이 있으면 콘솔에 알리고(gen_jobs.running), MakeFun 에 이미 만들어진 결과는
    POST /api/refetch 로 추가 과금 없이 다시 받아올 수 있다.
  * 같은 장면의 중복 생성(=중복 과금)은 gen_jobs.claim 하나가 막는다. 웹 요청끼리는 서버
    메모리 표시로, 웹 서버와 CLI 처럼 **프로세스가 다를 때는** logs/gen_locks/<scene_id>.lock
    파일로 막는다(협조적 잠금 — 이 관문을 지나는 경로만 지키고, 좌초된 잠금은 20분 뒤
    회수된다. 보장 범위는 gen_jobs 모듈 설명에 적어 두었다).
  * 유료 호출은 전부 같은 관문을 지난다 — 생성(/api/gen-image)과 확대(/api/upscale).
    확대는 사람이 승인한 그 그림의 픽셀만 키워 새 후보로 놓는 경로라 APPROVED 장면에서도
    허용되지만(선택본·승인 상태는 그대로), 과금이므로 선점·진행 조회·로그는 생성과 같다.
    /api/credits 는 이미지 과금이 없는 읽기지만 API 토큰을 쓰는 실호출이라 그렇다고 응답에 밝힌다.

로그: logs/webapp.log (회전). 기본은 오류·생성 실패·LAN 접속만, --verbose 면 요청까지.
      생성 작업 로그(vn.gen)도 같은 파일에 모인다.

의존성: 표준 라이브러리만(썸네일만 선택적으로 Pillow). Python 3.9+.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import hashlib
import http.cookies
import json
import ipaddress
import logging
import logging.handlers
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_jobs  # noqa: E402
import image_gen  # noqa: E402
import local_llm  # noqa: E402

import makefun_client  # noqa: E402
import print_preflight  # noqa: E402
import prompt_build  # noqa: E402
import scene_brief  # noqa: E402
import scene_lint  # noqa: E402
import scene_ops  # noqa: E402
import works        # noqa: E402  작품 전환(대화별 장면·그림)
import talk_store  # noqa: E402
import vn_compose  # noqa: E402
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

# 경로·상수는 vn_core 가 단일 출처다(아래는 읽기 편하게 붙인 별칭).
ROOT = vn_core.ROOT
MANIFEST = vn_core.MANIFEST
RAW_DIR = vn_core.IMAGES_RAW
STORY_DIR = vn_core.STORY
STUDIO_HTML = vn_core.TOOLS / "studio.html"
CHAT_HTML = vn_core.TOOLS / "chat_ui.html"      # 통합 화면(/chat) — 없으면 그 경로만 404
OUTPUT_DIR = vn_core.OUTPUT
THUMB_DIR = OUTPUT_DIR / ".thumbs"      # 파생물 — output/ 는 이미 git 제외 대상
THUMB_MAX_BYTES = 32 * 1024 * 1024      # 썸네일 캐시 예산(초과분은 오래된 것부터 정리)
FAVORITES = vn_core.PROJECT / "favorites.json"
LOG_DIR = vn_core.LOGS
IMAGE_EXTS = vn_core.IMAGE_EXTS
SCENE_ID_RE = vn_core.SCENE_ID_RE
WRITE_LOCK = vn_core.WRITE_LOCK
CHAT_WINDOW = 24  # API 로 보내는 최근 대화 수 (전체 로그는 디스크에 보존)
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
LAN_URLS: list[str] = []     # LAN 모드에서 폰이 실제로 열 수 있는 주소(QR 용). 그 외에는 빈 목록.
# --trust 로 지정한 기기(IP). 이 주소에서 오는 요청만 PIN 을 묻지 않는다.
# 실행 중에만 유효하다 — 파일로 남기지 않으므로 다음 실행에서는 다시 적어야 한다.
TRUSTED_IPS: set[str] = set()
SERVER_PORT = 0              # 실제 바인딩된 포트 — CSRF 출처 검증에서 쓴다(0 = 미기동)
IMG_MAX_AGE = 86400          # /img 브라우저 캐시(초) — ETag 로 무효화되므로 길게 잡는다
GZIP_MIN = 1024              # 이보다 작은 응답은 압축 이득보다 오버헤드가 크다
DL_CHUNK = 256 * 1024        # /dl 전송 단위 — 큰 감상본을 통째로 메모리에 올리지 않는다
MAX_BODY_BYTES = 10_000_000  # POST 본문 상한. 초과·음수 길이는 본문을 읽지 않고 거절한다
                             # (음수 Content-Length 는 rfile.read(-1) 로 이어져 인증 전에
                             #  서버를 메모리 고갈로 떨굴 수 있다 — 상한과 같은 문에서 막는다).
SEC_HEADERS = [("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer")]
# 스튜디오 화면(및 잠금 화면)의 콘텐츠 보안 정책. 페이지는 자기 출처 안에서만 동작한다
# — 외부 스크립트·외부 연결·프레임 삽입이 전부 막히므로, 혹시 주입이 생겨도 유출 경로가 없다.
CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' data: blob:; "
       "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; form-action 'self'; base-uri 'none'; object-src 'none'; "
       "frame-ancestors 'none'")
# src= 없는 <script ...> 여는 태그 — 그 안에 내용이 있으면 인라인 스크립트가 있는 문서다.
_INLINE_SCRIPT_OPEN = re.compile(rb"<script(?![^>]*\bsrc\s*=)[^>]*>", re.I)
# 스튜디오 JS 는 /studio/<이름>.js 로 서빙한다(감상본은 같은 파일을 인라인으로 품는다).
STUDIO_JS_RE = re.compile(r"^[A-Za-z0-9_-]+\.js$")
JS_MAX_AGE = 0               # 파일을 고치면 즉시 반영되도록 매번 재검증(ETag 로 304)

log = logging.getLogger("vn.webapp")
log.addHandler(logging.NullHandler())   # 라이브러리로 import 될 때는 조용히
# 생성 작업(gen_jobs)의 로그도 같은 파일로 모은다 — 실패 사유가 두 곳으로 갈라지지 않게.
LOG_NAMES = ("vn.webapp", "vn.gen")


def has_inline_script(body: bytes) -> bool:
    """문서에 **내용이 있는** 인라인 스크립트가 있는가. 닫는 태그가 없으면 있다고 본다(보수적)."""
    for m in _INLINE_SCRIPT_OPEN.finditer(body):
        end = body.find(b"</script", m.end())
        if (body[m.end():] if end < 0 else body[m.end():end]).strip():
            return True
    return False


def csp_for(body: bytes) -> str:
    """이 문서에 맞는 CSP — 인라인 스크립트가 없으면 script-src 에서 'unsafe-inline' 을 뺀다.

    스튜디오 JS 가 /studio/*.js 파일로 분리되면 인라인 예외가 필요 없어지고, 그때는
    주입된 <script> 조각이 아예 실행되지 못한다. 아직 인라인이 남아 있는 문서(잠금 화면 등)는
    지금까지와 같은 정책을 그대로 받는다 — 어느 쪽이든 화면은 동작한다.
    """
    if has_inline_script(body):
        return CSP
    return CSP.replace("script-src 'self' 'unsafe-inline'", "script-src 'self'")


def setup_logging(verbose: bool = False) -> None:
    """logs/webapp.log 회전 로그. 실패해도(권한 등) 서버 기동을 막지 않는다."""
    handler = None
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / "webapp.log", maxBytes=512_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    except OSError:
        pass
    for name in LOG_NAMES:
        lg = logging.getLogger(name)
        if handler is not None:
            lg.addHandler(handler)
        lg.setLevel(logging.DEBUG if verbose else logging.INFO)
        lg.propagate = False


def _load_json_safe(path: Path) -> dict | None:
    """손상/비-dict JSON 은 None — 파일 하나가 UI 전체(/api/state)를 죽이지 못하게 한다."""
    return vn_core.load_json_safe(path, {}) or None


# ---------------------------------------------------------------- 상태·도메인
def scene_image_url(sc: dict) -> str | None:
    rel = vn_core.selected_of(sc)      # 선택본 판정의 단일 출처
    if not rel:
        assets = sc.get("assets") if isinstance(sc.get("assets"), dict) else {}
        raws = assets.get("raw_images") or []
        rel = raws[0] if raws else ""
    if rel and rel.startswith("images/") and (ROOT / rel).exists():
        return "/img/" + rel[len("images/"):]
    return None


_PRINT_CACHE: dict[tuple, dict] = {}     # (rel, mtime, size) → 인화 규격 요약
_PRINT_CACHE_LOCK = threading.Lock()
_PRINT_CACHE_MAX = 512


def _print_measure(rel: str, key: tuple) -> dict:
    """이미지 1장의 인화 규격 측정 — 같은 파일(경로·mtime·크기)이면 다시 재지 않는다.

    /api/state 는 장면 수만큼 이 값을 부르는데, 측정은 파일을 열어 헤더를 읽는 일이라
    장면이 수십 개가 되면 목록 새로고침이 눈에 띄게 느려진다(감사 지적: 성능).
    """
    with _PRINT_CACHE_LOCK:
        hit = _PRINT_CACHE.get(key)
    if hit is not None:
        return hit
    size = print_preflight.image_size(ROOT / rel)
    if not size:
        val = {"px": None, "printable": None, "max": None, "long_in": None}
    else:
        r = print_preflight.preflight_image(size[0], size[1], 300)
        val = {"px": size, "printable": r["printable"], "max": r["max_size_at_target"],
               "long_in": r["max_long_in_at_target"]}
    with _PRINT_CACHE_LOCK:
        if len(_PRINT_CACHE) >= _PRINT_CACHE_MAX:
            _PRINT_CACHE.clear()     # 단일 사용자 도구 — 복잡한 LRU 대신 통째로 비운다
        _PRINT_CACHE[key] = val
    return val


def scene_print(sc: dict) -> dict | None:
    """장면 선택 이미지의 인화 규격 요약(없으면 None). 실물 인화 목표용."""
    sel = vn_core.selected_of(sc)
    if not sel:
        return None
    anchor = (sc.get("print", {}) or {}).get("crop_anchor", "center")
    try:
        st = (ROOT / sel).stat()
        key = (sel, int(st.st_mtime), st.st_size)
    except OSError:
        return {"px": None, "printable": None, "max": None, "long_in": None,
                "crop_anchor": anchor}
    # crop_anchor 는 캐시 키가 아니다 — 기준점을 바꿔도 이미지 측정값은 그대로다.
    return {**_print_measure(sel, key), "crop_anchor": anchor}


def load_favorites() -> list[str]:
    """인화 후보 ★ 목록 — project/favorites.json. 형식이 깨져도 빈 목록으로 살아남는다."""
    d = _load_json_safe(FAVORITES) or {}
    ids = d.get("scene_ids")
    if not isinstance(ids, list):
        return []
    return [s for s in ids if isinstance(s, str) and SCENE_ID_RE.match(s)]


def save_favorites(ids: list[str]) -> None:
    vn_core.atomic_write_json(FAVORITES, {"scene_ids": ids})


def last_viewer_export() -> dict | None:
    """가장 최근에 만든 감상본 파일 (경로·크기·시각). 없으면 None.

    감상 탭이 "이 감상본은 얼마나 낡았나" 를 말할 수 있는 유일한 근거다 — 승인 세 컷을
    더 하고도 예전 파일을 친구에게 보내는 일은 여기서만 막을 수 있다.
    """
    best = None
    try:
        for f in (OUTPUT_DIR / "viewer").glob("*.html"):
            st = f.stat()
            if best is None or st.st_mtime > best[1]:
                best = (f, st.st_mtime, st.st_size)
    except OSError:
        return None
    if best is None:
        return None
    f, mtime, size = best
    return {"file": f.relative_to(ROOT).as_posix(), "mtime": int(mtime),
            "mb": round(size / 1_000_000, 2)}


def state() -> dict:
    mf = _load_json_safe(MANIFEST) if MANIFEST.exists() else None
    scenes = []
    # 훑기·정렬·손상 파일 처리는 vn_core.iter_scenes 하나에 있다(손상 장면은 건너뛰고
    # 나머지 UI 는 살린다). 도구마다 다르게 훑으면 같은 프로젝트가 화면마다 다른 개수로 보인다.
    for _f, sc in vn_core.iter_scenes():
        is_end, end_label = vn_core.ending_of(sc)
        assets = sc.get("assets") if isinstance(sc.get("assets"), dict) else {}
        scenes.append({
            "scene_id": sc.get("scene_id"), "scene_order": sc.get("scene_order"),
            "status": sc.get("status"), "purpose": sc.get("purpose", ""),
            "dialogue": sc.get("dialogue", []),
            "prompt": (sc.get("prompt") or {}).get("grok_output", "")
                      if isinstance(sc.get("prompt"), dict) else "",
            "raw_images": assets.get("raw_images", []),
            "selected_image": vn_core.selected_of(sc),
            "review": sc.get("review", {}), "image_url": scene_image_url(sc),
            "print": scene_print(sc),
            "choices": sc.get("choices", []), "branch": sc.get("branch", []),
            # 엔딩 표기는 감상본과 같은 규칙으로 정규화한다(vn_core.ending_of).
            # 화면은 ending_label → purpose 순으로 이름을 고른다.
            "ending": is_end, "ending_label": end_label,
            "episode": sc.get("episode"),   # 화 단위 선택(뷰어)용
        })
    scenes.sort(key=lambda s: s.get("scene_order") or 0)
    storyline = ""
    if (STORY_DIR / "storyline.md").exists():
        try:
            storyline = (STORY_DIR / "storyline.md").read_text(encoding="utf-8")
        except OSError:
            storyline = ""
    model = ""
    if mf and isinstance(mf.get("orchestrator"), dict):
        model = mf["orchestrator"].get("api", {}).get("model", "")
    dating = (mf or {}).get("dating") if isinstance((mf or {}).get("dating"), dict) else None
    orch_local = str(((mf or {}).get("orchestrator", {}) or {}).get("mode", "")) == "local"
    return {"manifest": bool(mf), "title": (mf or {}).get("title", ""),
            "dating": dating,
            "model": model,
            "orch_local": orch_local,
            "mf_token": bool(os.environ.get(makefun_client.TOKEN_ENV, "").strip()),
            # 이미지 엔진 요약(기본 엔진·모델·host:port·쓸 수 있는 엔진 목록) — 비밀값 없음.
            "image": image_gen.engine_info(mf or {}),
            "characters": [{"id": c.get("character_id"), "name": c.get("name", "")}
                           for c in (mf or {}).get("characters", [])],
            "favorites": load_favorites(),
            "last_export": last_viewer_export(),
            # 폰 접속 QR 은 반드시 폰에서 열리는 주소여야 한다(127.0.0.1 은 폰 자신을 가리킨다).
            "lan_urls": list(LAN_URLS),
            "episodes": [e for e in (mf or {}).get("episodes", []) if isinstance(e, dict)],
            "scenes": scenes, "storyline": storyline,
            # 스토리 챗로그는 여기 싣지 않는다 — 대화가 길어질수록 모든 탭의 새로고침이
            # 같이 무거워졌다. 스토리 탭이 필요할 때만 POST /api/chat-history 로 받아간다.
            "chat_count": chat_count(),
            # 지금 이 서버가 굽고 있는 장면들. 새로고침하면 벌어지는 것은 브라우저의
            # 폴링이지 작업이 아니다 — 그런데 화면이 조용해지니 사람은 작업도 죽은 줄 알고
            # 다시 누른다(=같은 장면을 한 번 더 굽는다). 메모리 표만 읽으므로 비용은 0 이다.
            "gen_running": gen_jobs.running()}


_CHAT_COUNT: dict = {"key": None, "n": 0}


def chat_count() -> int:
    """저장된 스토리 대화 수 — '이어서 대화' 여부를 UI 에 알리는 값.

    파일이 그대로면(mtime·크기 동일) 다시 파싱하지 않는다 — /api/state 가 매번
    대화 로그 전체를 읽는 일이 없게 한다.
    """
    p = talk_store.story_chat_path()
    try:
        st = p.stat()
        key = (int(st.st_mtime), st.st_size)
    except OSError:
        return 0
    if _CHAT_COUNT["key"] != key:
        _CHAT_COUNT["n"] = len(talk_store.load_log(p))
        _CHAT_COUNT["key"] = key
    return int(_CHAT_COUNT["n"])


def llm_queue_wait() -> dict:
    """지금 모델 앞에 줄이 서 있는가 → {"busy": bool, "eta": 초|None}.

    씀크북의 llama-server 는 --parallel 1 로 돌고, 그 뜻은 조립이 도는 동안 대화는
    **통째로 줄을 선다**는 것이다. 더 나쁜 것은 그 서버가 줄 선 요청에 응답 헤더조차
    주지 않는다는 점이다 — 그래서 평소의 120초 상한이 그대로 걸려 정확히 120.0초에
    죽는다(씀크북 실측: 조립 275초 동안 걸은 대화가 전부 실패).

    앞에 무엇이 도는지를 아는 곳은 이 서버다(조립을 여기서 돌리므로). 그러니 상한을
    푸는 판단도 여기서 한다 — local_llm 의 기본값은 손대지 않는다(그걸 키우면 진짜로
    꺼진 서버를 알아차리는 데도 15분이 걸린다).
    """
    # 두 가지를 본다.
    #  (1) 서버 조립 작업(_JOB) — 남은 시간까지 알려 줄 수 있는 유일한 것이다.
    #  (2) **지금 소켓을 들고 있는 호출이 있는가**(local_llm.holding).
    #      이게 없으면 스튜디오의 [스토리라인 → 장면 구성](동기 /api/compose)이
    #      몇 분을 붙잡고 있어도 여기서는 "한가하다" 고 대답하고, 그 동안 대화는
    #      예전처럼 120초에 죽는다. 경로마다 표시를 붙이는 대신 붙잡는 곳에서 센다 —
    #      새 경로가 생겨도 자동으로 포함된다.
    try:
        st = vn_compose.compose_job_status()
    except Exception:                      # 상태를 못 읽는 것이 대화를 막을 이유는 없다
        st = {}
    try:
        held = local_llm.holding()
    except Exception:
        held = []
    return {"busy": bool(st.get("running")) or bool(held),
            "eta": st.get("eta") if st.get("running") else None}


def _chat_timeout(wait: dict):
    """줄이 서 있으면 긴 상한, 아니면 None(=기본값)."""
    return local_llm.QUEUE_TIMEOUT if wait.get("busy") else None


def _log_mark(path) -> tuple:
    """대화 로그의 '지금 모습' 표 — (발화 수, 크기, 수정시각).

    답을 기다리는 1~2분 사이에 그 로그가 **다른 기기에서** 바뀔 수 있다. 지워지거나,
    [수정]·[다시 생성]으로 짧아지거나. 그 뒤에 이 답을 그냥 붙이면 방금 지운 말이
    되살아난다 — 그것도 보관 기록은 이미 떠난 반쪽으로.
    """
    try:
        st = path.stat()
        return (len(talk_store.load_log(path)), st.st_size, st.st_mtime_ns)
    except OSError:
        return (0, 0, 0)


def do_chat(messages: list[dict], chat_id: str = "") -> str:
    """스토리 챗 1턴 — 프롬프트 조립은 prompt_build, 모델 선택은 vn_compose 담당.

    (이 함수에 남는 일은 '창 자르기 → 호출 → 병합 저장' 뿐이다.)
    """
    # 지워진 대화는 되살아나지 않는다. 예전에는 다른 기기가 그 대화에 한 마디만 보내면
    # 파일이 다시 만들어졌고, 그때 보관 기록은 이미 지워진 뒤라 영영 사라졌다.
    # **모델을 부르기 전에** 본다 — 1~2분 기다리게 한 뒤 거절하는 것은 거절이 아니라 낭비다.
    cid = talk_store.normalize_chat_id(chat_id)
    path = talk_store.story_chat_path_for(chat_id)
    # 파일이 없는 것으로 판단하지 않는다. '지워진 대화' 와 '아직 한 마디도 저장되지 않은
    # 새 대화' 는 디스크에서 같은 모습이라, 그렇게 보면 [+ 새 대화] 가 통째로 막힌다.
    if talk_store.is_deleted_chat(cid) and messages:
        raise VNError("이 대화는 삭제되었습니다. 목록에서 새 대화를 시작하세요.")

    # 이 갈래가 작품 문맥을 쓰는지는 서버에 저장된 값이 단일 출처다 — 클라이언트가
    # 매번 보내면 기기마다 다른 값이 오가고, 어느 쪽이 맞는지 알 수 없게 된다.
    sys_msg = prompt_build.story_system_message(talk_store.chat_use_context(chat_id))
    window = messages[-CHAT_WINDOW:]  # 비용·컨텍스트 관리: 최근 대화만 전송
    before = _log_mark(path)
    reply = vn_compose.orch_chat([sys_msg] + window, temperature=0.7, max_tokens=1000,
                                 timeout=_chat_timeout(llm_queue_wait()))
    with WRITE_LOCK:
        # **기다리는 사이에 바뀌었는가.** 검사를 모델 앞에만 두면 늦다 — 지우기·자르기는
        # 정확히 그 1~2분 사이에 다른 기기에서 일어난다(폰에서 지우고 PC 가 답을 받는 식).
        if talk_store.is_deleted_chat(cid):
            raise VNError("답을 기다리는 사이 이 대화가 삭제되었습니다 — 답을 붙이지 않았습니다.")
        after = _log_mark(path)
        if after[0] < before[0]:
            # 짧아졌다 = 사람이 [수정]·[다시 생성]으로 뒤를 걷어냈다. 여기서 클라이언트가
            # 보낸 옛 목록으로 병합하면 방금 걷어낸 말이 그대로 되살아난다.
            raise VNError("답을 기다리는 사이 이 대화가 바뀌었습니다(다른 기기에서 수정했거나 "
                          "다시 생성했습니다) — 이 답은 붙이지 않았습니다. 다시 물어보세요.")
        # 인물 대화와 같은 규칙: 클라이언트가 보낸 목록으로 덮어쓰지 않고 저장본과 병합한다.
        # (/api/state 가 더 이상 챗로그를 싣지 않으므로, 병합이 없으면 새 탭에서 보낸
        #  첫 메시지가 지난 대화를 통째로 지웠을 것이다.)
        final = talk_store.merge_messages(talk_store.load_log(path), messages)
        final.append({"role": "assistant", "content": reply})
        talk_store.save_log(path, final)
    return reply


def _require_scene(sid) -> Path:
    """장면 ID 형식 검증 + 존재 확인.

    형식 검증이 먼저인 이유: '../..' 같은 값이 scene_path 를 통해 장면 폴더 밖 파일에
    닿는 것을 원천 차단한다. 존재 확인은 뒤이은 로더가 파일 없음으로 터지기 전에
    사람이 읽을 수 있는 400 안내를 주기 위해서다.
    """
    if not vn_core.is_scene_id(sid):
        raise VNError(f"장면 ID 형식이 올바르지 않습니다(SCENE-001 형식): {sid!r}")
    path = vn_core.scene_path(sid)
    if not path.exists():
        raise VNError(f"장면을 찾을 수 없습니다: {sid}")
    return path


def _load_scene(sid) -> dict:
    """검증된 장면 읽기 — 손상 파일은 VNError(=400)로, 요청 스레드는 살아남는다."""
    return vn_core.load_dict(_require_scene(sid))


# ---------------------------------------------------------------- POST 라우팅
# 각 핸들러는 요청 body(dict) 를 받아 응답 dict 를 반환하거나 RuntimeError 를 던진다.
def r_chat(b):
    return {"reply": do_chat(b.get("messages", []), str(b.get("chat_id") or ""))}


def r_chat_history(b):
    """저장된 스토리 대화 이력 → {messages}. /api/state 에서 분리한 무거운 부분이다.

    chat_id 를 주면 그 갈래의 것만 온다. 안 주면 예전과 같은 기본 갈래다.
    """
    path = talk_store.story_chat_path_for(b.get("chat_id"))
    return {"messages": talk_store.load_log(path)}


def r_chats(b):
    """대화 갈래 목록 → {chats:[{id,title,count,mtime}]}. 최근 것이 앞."""
    return {"chats": talk_store.list_story_chats()}


def r_chat_trim(b):
    """대화를 앞에서 keep 개만 남기고 자른다 → {kept, dropped}.

    화면의 '수정'·'다시 생성'이 쓴다. 자른 뒤 곧바로 /api/chat 을 부르면 그 지점부터
    다시 이어진다. 잘린 구간은 아카이브 파일로 옮겨지므로 사라지지 않는다.
    """
    keep = int(b.get("keep", 0) or 0)
    path = talk_store.story_chat_path_for(b.get("chat_id"))
    with WRITE_LOCK:
        # 화면이 들고 있는 번호는 **화면이 본 시점**의 것이다. 그 사이 다른 기기가 말을
        # 보탰으면 그 번호는 남의 대화를 가리킨다 — 실제로 폰에서 [다시 생성] 한 번이
        # 데스크탑의 질문과 답을 통째로 잘라낸 적이 있다. 길이가 다르면 자르지 않는다.
        expect = b.get("expect_len")
        if expect is not None:
            have = len(talk_store.load_log(path))
            if int(expect) != have:
                raise VNError(f"그 사이 대화가 바뀌었습니다(화면 {int(expect)}턴 · 저장본 {have}턴). "
                              "새로고침한 뒤 다시 시도하세요 — 아무것도 자르지 않았습니다.")
        res = talk_store.truncate_log(path, keep)
    if res.get("error"):
        raise VNError(res["error"])        # 200 안에 숨기지 않는다 — 화면이 성공으로 읽는다
    return res


def r_chat_meta(b):
    """갈래 설정 저장 → {chat_id, use_context}.

    use_context=False 면 그 갈래는 작품의 인물·장소·스토리라인을 모르는 채로 답한다.
    새 대화에 "8살 민수의 등교" 만 적었는데 기존 작품의 인물이 따라 나오던 것이 이 값 때문이다.
    """
    cid = talk_store.normalize_chat_id(b.get("chat_id"))
    with WRITE_LOCK:
        val = talk_store.set_chat_use_context(cid, bool(b.get("use_context")))
    return {"chat_id": cid, "use_context": val}


CHAT_EXPORT_DIR = OUTPUT_DIR / "chats"
# POST 본문 상한(MAX_BODY_BYTES)에 base64 의 4/3 팽창을 반영한 실질 상한.
# 내보내기가 이 값을 넘으면 "받을 수는 있지만 이 화면으로는 다시 못 넣는다" 고 말해 준다 —
# 나중에 가져오기를 눌렀을 때 거절당하는 것보다, 내보내는 그 자리에서 아는 편이 낫다.
IMPORT_POST_CAP = MAX_BODY_BYTES * 3 // 4 - 8192


def r_chat_export(b):
    """대화 하나를 zip 으로 내보낸다 — output/chats/ 에 두고 /dl 주소를 돌려준다.

    본문에 실어 돌려주지 않고 **파일로 두는** 이유가 둘이다. 폰에서 무언가를 받아가는
    길이 이미 /dl 하나뿐이고(받아가기 목록이 그것을 쓴다), 파일로 남아 있으면 브라우저가
    받다가 끊겨도 다시 받을 수 있다. 대화 로그는 사용자가 잃으면 안 되는 자산이다.
    """
    cid = talk_store.normalize_chat_id(b.get("chat_id"))
    name, data = talk_store.export_chat_bytes(cid)
    with WRITE_LOCK:
        CHAT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        vn_core.atomic_write_bytes(CHAT_EXPORT_DIR / name, data)
    return {"name": name, "chat_id": cid,
            "url": "/dl/" + urllib.parse.quote("chats/" + name),
            "bytes": len(data), "mb": round(len(data) / 1_000_000, 2),
            "reimportable": len(data) <= IMPORT_POST_CAP}


def r_chat_import(b):
    """zip → **새** 대화. 기존 대화는 어떤 경우에도 덮어쓰지 않는다(talk_store 가 이름을 비킨다).

    두 갈래로 받는다: 폰·다른 PC 에서 고른 파일은 base64 로 본문에 실려 오고, 이미 이
    기계의 output/chats/ 에 있는 파일은 이름만 온다. 두 번째 갈래가 있는 이유는 본문
    상한 때문이다 — 큰 대화는 본문으로는 못 들어오지만 파일로는 들어온다.
    """
    raw = b.get("b64")
    if isinstance(raw, str) and raw.strip():
        try:
            data = base64.b64decode(raw.strip(), validate=True)
        except (ValueError, binascii.Error):
            raise VNError("파일을 읽지 못했습니다 — 다시 골라 주세요.")
    else:
        rel = str(b.get("name") or "").strip()
        if not rel:
            raise VNError("가져올 파일이 없습니다.")
        target = vn_core.safe_path(CHAT_EXPORT_DIR, rel)
        if target is None or not target.is_file():
            raise VNError(f"{rel[:60]} 을(를) 찾지 못했습니다 — output/chats/ 안에 있어야 합니다.")
        if target.stat().st_size > talk_store.IMPORT_CAP:
            raise VNError("파일이 너무 큽니다 — 가져오지 않았습니다.")
        data = target.read_bytes()
    with WRITE_LOCK:
        res = talk_store.import_chat_bytes(data, b.get("chat_id") or "")
    log.info("대화 가져오기: %s (%d발화, 보관 %d줄)",
             res["chat_id"], res["count"], res["archived"])
    return res


def r_chat_exports(b):
    """이 기계에 남아 있는 내보내기 파일 목록 — 최근 것이 앞."""
    out = []
    for f in sorted(CHAT_EXPORT_DIR.glob("*.zip")) if CHAT_EXPORT_DIR.is_dir() else []:
        try:
            st = f.stat()
        except OSError:
            continue
        out.append({"name": f.name, "url": "/dl/" + urllib.parse.quote("chats/" + f.name),
                    "bytes": st.st_size, "mb": round(st.st_size / 1_000_000, 2),
                    "mtime": int(st.st_mtime)})
    out.sort(key=lambda d: -d["mtime"])
    return {"files": out[:200]}


def r_work_switch(b):
    """그 대화의 작품을 올린다 — 장면·그림이 대화마다 따로 산다.

    굽는 중·조립 중에는 거절한다. 그 작업들은 장면 id 로 파일을 잡고 있어서,
    밑에서 폴더를 바꾸면 굽던 그림이 남의 작품으로 들어간다.
    """
    cid = talk_store.normalize_chat_id(b.get("chat_id"))
    try:
        if vn_compose.compose_job_status().get("running"):
            raise VNError("조립이 도는 중입니다 — 끝난 뒤에 대화를 옮기세요.")
    except VNError:
        raise
    except Exception:
        pass
    busy = gen_jobs.running()
    if busy:
        raise VNError(f"그림을 굽는 중입니다({', '.join(busy)}) — 끝난 뒤에 옮기세요.")
    return works.switch(cid)


def r_works(b):
    return {"current": works.current(), "works": works.list_works()}


def r_chat_delete(b):
    """갈래 하나 삭제. 기본 갈래(id 없음)는 지우지 않는다 — 스튜디오가 같은 파일을 쓴다."""
    cid = talk_store.normalize_chat_id(b.get("chat_id"))
    if not cid:
        raise VNError("기본 대화는 지울 수 없습니다 — 새 대화를 만들어 쓰세요.")
    with WRITE_LOCK:
        ok = talk_store.delete_story_chat(cid)
        # 그 대화의 작품도 같이 치운다. 장면·그림은 다시 만들 수 없으므로
        # 지우지 않고 .deleted 로 이름만 바꾼다(대화 보관본과 같은 규칙).
        works.forget(cid)
    return {"deleted": ok, "chat_id": cid}


def r_storyline(b):
    with WRITE_LOCK:
        vn_core.atomic_write_text(STORY_DIR / "storyline.md", str(b.get("text", "")))
    return {"ok": True}


def r_compose(b):
    return vn_compose.compose_scenes(int(b.get("count", 10)), bool(b.get("force")),
                                     bool(b.get("branching")))


def r_compose_input(b):
    return {"instruction": vn_compose.build_compose_instruction(
        int(b.get("count", 10)), bool(b.get("branching")))}


def r_compose_batch(b):
    """구간 조립 한 번 — 모델 원문을 그대로 돌려준다(저장하지 않는다).

    통합 화면(/chat)이 장면을 3개씩 받아 모을 때 쓴다. /api/chat 을 쓰지 않는 이유는
    vn_compose.compose_batch 의 주석에 있다(출력 상한 1000 · 챗로그 오염).
    """
    made = b.get("made")
    return {"reply": vn_compose.compose_batch(
        int(b.get("total", 1)), bool(b.get("branching")),
        int(b.get("start", 1)), int(b.get("end", 1)),
        made if isinstance(made, list) else [])}


def r_compose_job_start(b):
    """조립을 서버에서 시작한다 → 진행 상태. 화면을 닫아도 계속 돈다.

    브라우저가 작업의 주인이면 탭을 닫거나 폰을 잠그는 순간 7분짜리 작업이 죽는다.
    서버가 들고 있으면 사람이 자리를 뜰 수 있고, 다시 열면 그 사이 진행된 것이 보인다.
    """
    return vn_compose.compose_job_start(int(b.get("total", 6) or 6),
                                        int(b.get("batch", 3) or 3),
                                        bool(b.get("branching")),
                                        resume=bool(b.get("resume")))


def r_compose_job_status(b):
    """조립 진행 조회 — 받은 장면이 도착하는 대로 목록에 쌓인다."""
    return vn_compose.compose_job_status()


def r_compose_job_cancel(b):
    """이번 구간이 끝나면 멈춘다. 받아 둔 장면은 그대로 둔다."""
    return vn_compose.compose_job_cancel()


def r_compose_job_save(b):
    """서버가 모아 둔 장면을 저장한다 → compose_from_json 과 같은 결과.

    저장까지 서버가 들고 있으므로, 조립 도중 화면을 닫았다가 나중에 열어도 마무리할 수 있다.
    '누가 저장하는가' 의 판정은 vn_compose 안에서 잠금으로 한 번만 일어난다(화면 두 개가
    같은 순간에 눌러도 한 번만 저장된다).
    """
    return vn_compose.compose_job_save(bool(b.get("force")))


def r_compose_job_discard(b):
    """받아 둔 장면을 버린다 — 사람이 명시적으로 눌렀을 때만."""
    return vn_compose.compose_job_discard()


def r_compose_manual(b):
    exp = int(b["count"]) if str(b.get("count", "")).strip() else None
    return vn_compose.compose_from_json(b.get("text", ""), bool(b.get("force")), expected=exp)


def r_scene_brief(b):
    """장면 브리프 — 직접 입력 경로의 입구. LLM 없이 조립되므로 로컬 LLM 이 꺼져 있어도 된다."""
    _require_scene(b.get("scene_id"))
    return {"text": scene_brief.build_brief(b["scene_id"])}


def r_set_prompt(b):
    return scene_ops.set_prompt(b.get("scene_id"), b.get("text", ""), bool(b.get("fix_anchors")))


def r_preflight(b):
    sc = _load_scene(b.get("scene_id"))
    sel = vn_core.selected_of(sc)
    if not sel:
        raise VNError("선택된 이미지가 없습니다. 먼저 이미지를 선택하세요.")
    size = print_preflight.image_size(ROOT / sel)
    if not size:
        return {"px": None, "rows": [], "printable": None}
    return print_preflight.preflight_image(size[0], size[1], int(b.get("dpi", 300)))


def r_set_crop(b):
    """인화 크롭 기준점 저장 — 어디를 살릴지는 사람이 정한다(print_export.crop_anchor).

    print.crop_anchor 는 /api/set-scene 이 이미 다루는 필드다. 여기서 장면 파일을
    직접 고쳐 쓰면 값 검증도 APPROVED 가드도 없는 **두 번째 쓰기 경로**가 생긴다
    (승인 도장을 찍은 장면의 인화 설정이 이 경로로만 바뀌는 상태가 된다).
    그래서 저장은 scene_ops 하나에 맡긴다 — 승인 장면의 인화 설정 변경이
    허용되는 것도 그쪽의 명시적 예외(set_crop)이지 이 라우트의 우회가 아니다.
    """
    anchor = str(b.get("anchor", "center"))
    return scene_ops.set_crop(b.get("scene_id"), anchor)


def r_set_scene(b):
    """장면 내용 편집 — {scene_id, fields:{...}}.

    화이트리스트·APPROVED 가드·쓰기 잠금은 scene_ops.update_fields 하나에만 있다
    (status·review·assets·scene_id·scene_order 는 이 경로로 바뀌지 않는다).
    """
    return scene_ops.update_fields(b.get("scene_id"), b.get("fields"))


def r_export(b):
    # 서버는 Pillow 없이도 뜨도록 지연 임포트
    try:
        import print_export
    except Exception:
        raise RuntimeError("인화 내보내기는 Pillow 가 필요합니다:  python -m pip install Pillow")
    inc_all = bool(b.get("all"))
    only_ids = None
    if b.get("favorites_only"):
        only_ids = load_favorites()
        if not only_ids:
            raise RuntimeError("★ 즐겨찾기로 표시한 장면이 없습니다. 갤러리에서 먼저 골라 주세요.")

    def _pick(scenes):   # 즐겨찾기 필터 (컨택트시트도 같은 대상으로 맞춘다)
        return [s for s in scenes if s.get("scene_id") in only_ids] if only_ids is not None else scenes

    if b.get("contact_only"):
        made = print_export.contact_sheet(_pick(print_export.collect(None, inc_all)))
        return {"contact": bool(made), "count": 0}
    try:
        short_in, long_in = print_export.parse_size(str(b.get("size", "5x7")))
    except SystemExit as e:
        raise RuntimeError(str(e))
    kw = {}
    if only_ids is not None:
        kw["only_ids"] = only_ids
    # 인화 옵션(여백 모드·재단선 등)은 요청에 있을 때만 넘긴다 — 나머지는 도구 기본값.
    for key, cast in (("mode", str), ("bg", str), ("upscale", str),
                      ("marks", bool), ("order_prefix", bool)):
        if key in b:
            kw[key] = cast(b[key])
    summ = print_export.export_batch(
        short_in, long_in, dpi=int(b.get("dpi", 300)), bleed=float(b.get("bleed", 0)),
        anchor=str(b.get("anchor", "center")), include_all=inc_all, scene_filter=None,
        skip_upscale=bool(b.get("skip_upscale")), **kw)
    if b.get("contact"):
        print_export.contact_sheet(_pick(print_export.collect(None, inc_all)))
    # refused 는 **굽지 않은 이유**다 — 세지 않으면 화면에 "0장 → (없음)" 만 남아서
    # 사용자가 실패로 읽고 같은 버튼을 다시 누른다(실측 가능한 낭비는 아니지만 같은 종류의 침묵).
    return {"count": summ["count"], "dir": summ["dir"], "upscaled": summ["upscaled"],
            "skipped": summ["skipped"], "missing": summ["missing"],
            "refused": summ.get("refused") or [], "floor_dpi": summ.get("floor_dpi"),
            "needed_px": summ.get("needed_px")}


def r_favorite(b):
    """인화 후보 ★ 토글 — 서버(project/favorites.json)에 저장해 폰·PC 가 같은 목록을 본다."""
    sid = b.get("scene_id")
    _require_scene(sid)
    with WRITE_LOCK:
        ids = load_favorites()
        if bool(b.get("on")):
            if sid not in ids:
                ids.append(sid)
        elif sid in ids:
            ids.remove(sid)
        ids.sort()
        save_favorites(ids)
    return {"scene_ids": ids}


def r_register(b):
    return scene_ops.register_images(b.get("scene_id"))


def r_select(b):
    return scene_ops.select_image(b.get("scene_id"), b.get("image", ""))


def r_approve(b):
    return scene_ops.approve(b.get("scene_id"))


def r_check(b):
    code, out = vn_core.run_checker()
    return {"pass": code == 0, "output": out}


def r_lint(b):
    return scene_lint.lint_scenes()


def r_gen_prompt(b):
    """로컬 LLM 으로 장면 이미지 프롬프트 생성 → 저장 + 자동 검사.

    LLM 이 꺼져 있으면 여기는 실패한다 — 그때의 경로는 /api/scene-brief + /api/set-prompt(직접 입력)다.
    """
    sid = b.get("scene_id")
    sc = _load_scene(sid)
    return scene_ops.set_prompt(sid, prompt_build.compose_image_prompt(sc))


# ------------------------------------------------- 이미지 생성 (중복 방지·백그라운드)
# 상태기계는 gen_jobs 하나에만 있다(웹·CLI 공용). 여기 남는 것은 요청 해석과 호출뿐이다.
def _candidates(sc: dict) -> int:
    return len(sc.get("assets", {}).get("raw_images", []))


def _progress(sid: str, label: str, engine: str | None = None):
    """엔진 폴링 진행을 그대로 진행 표시로 넘기는 콜백(문구는 image_gen.progress_text 하나).

    화면에 경과 시간이 보이는 것도 이유지만, 더 중요한 건 **살아 있다는 신호**다 —
    gen_jobs 의 선점 잠금은 마지막 갱신에서 STALE_SEC 이 지나면 좌초로 보고 회수된다.
    갱신이 없으면 오래 걸리는 생성이 스스로 그 판정을 받아 다른 프로세스에게 자리를
    내주고, 같은 장면이 한 번 더 과금될 수 있다.
    """
    def on_progress(elapsed, status_text):
        gen_jobs.note(sid, image_gen.progress_text(engine, label, elapsed, status_text))
    return on_progress


def r_image_engine(b):
    """이미지 엔진 상태 — {engine, provider, ok, detail, checkpoints, model, billable}.

    ComfyUI 는 로컬이라 실제로 물어본다(3초 상한). MakeFun 은 토큰 유무만 본다 — 조회조차
    토큰을 쓰는 실호출이라 '상태 버튼'이 계정을 두드리면 안 된다(그건 /api/credits 의 일이다).
    """
    return image_gen.health(b.get("engine") or None)


def r_gen_image(b):
    """설정된 이미지 엔진으로 장면 이미지 생성 → images/raw/<scene>/ 저장 + 자동 등록·검사.

    body.engine 으로 기본 엔진(manifest image_generator.engine)을 한 번만 바꿔 부를 수 있다
    — ComfyUI 가 기본일 때 "MakeFun 생성(유료)" 보조 버튼이 그 경로다.
    기본은 백그라운드 실행 후 즉시 응답(폰 브라우저 타임아웃 방지) — 진행은 /api/gen-status.
    sync:true 면 예전처럼 끝날 때까지 기다렸다가 결과를 반환한다.
    """
    sid = b.get("scene_id")
    engine = str(b.get("engine") or image_gen.active_engine()).lower()
    if engine not in image_gen.ENGINES:
        raise VNError(f"알 수 없는 이미지 엔진입니다: {str(b.get('engine'))[:40]!r} "
                      f"(가능: {', '.join(image_gen.ENGINES)})")
    label = image_gen.label(engine)
    # 승인 잠금 안내는 scene_ops 하나가 낸다 — 라우트마다 다른 문장을 쓰면 같은 거절인데
    # 다음에 할 일(revise 명령)이 화면마다 보이기도 하고 안 보이기도 한다.
    sc = scene_ops.assert_mutable(sid, "이미지를 다시 생성하려면")
    n = max(1, min(int(b.get("n", 1) or 1), 4))

    # 지난 '그만' 표시는 지운다. 다만 **이미 굽고 있는 장면**에는 손대지 않는다 —
    # 그러면 방금 누른 '그만' 이 [그림 뽑기] 한 번에 조용히 취소되고, 거절당한 뒤에도
    # 원래 작업은 취소 표시를 잃은 채 끝까지 굽는다.
    if not gen_jobs.status(sid).get("running"):
        gen_jobs.clear_cancel(sid)

    def work():
        gen_jobs.note(sid, f"{label} 에 생성 요청 중…")

        def _each(done, want, files):
            """한 장이 나올 때마다 등록하고 알린다 — 다 구워질 때까지 기다리지 않는다.

            등록을 장마다 하는 이유: 화면이 후보를 바로 보여 주려면 assets 에 들어 있어야
            한다. register_images 는 IMAGE 에서 멈추므로(선택은 사람이) 불변식은 그대로다.
            """
            note = f"{done}/{want}장 나왔습니다 — 고르거나 더 뽑을 수 있습니다."
            try:
                scene_ops.register_images(sid)
            except Exception as exc:
                # 굽는 중에 그 장면을 승인해 버리면 여기서부터 등록이 전부 막힌다.
                # 조용히 넘기면 파일은 쌓이는데 화면에는 후보가 안 늘어난다 — 말한다.
                note = (f"{done}/{want}장 나왔지만 목록에 넣지 못했습니다 "
                        f"({str(exc)[:60]}). 파일은 images/raw 에 있습니다.")
            gen_jobs.note(sid, note, done=done, want=want)

        return image_gen.generate_for_scene(
            sid, n=n, engine=engine,
            on_progress=_progress(sid, "생성", engine),
            on_each=_each,
            should_stop=lambda: gen_jobs.cancelled(sid))

    return gen_jobs.start(
        sid, work, "생성", sync=bool(b.get("sync")), count=_candidates(sc),
        message=f"{label} 생성 중… (ComfyUI: 보통 20~90초 / MakeFun: 1~3분) "
                "진행 상황은 자동으로 갱신됩니다.")


def r_gen_cancel(b):
    """생성을 그만두라고 표시한다 → {cancelled, scene_id}.

    이미 구워진 장은 남는다. 장 사이에서만 멈추므로 반쯤 쓰인 파일이 생기지 않는다.
    """
    sid = _require_scene(b.get("scene_id")) and b.get("scene_id")
    return gen_jobs.request_cancel(sid)


def r_refetch(b):
    """이미 만들어진 MakeFun 작업 결과를 다시 받아 온다 — **새로 만들지 않으므로 무과금**.

    생성 도중 서버가 꺼졌거나(생성 스레드는 daemon 이라 Ctrl+C 에 즉시 끊긴다) 다운로드가
    끊긴 경우, 과금을 다시 치르지 않고 결과만 회수하는 경로다.
    """
    sid = b.get("scene_id")
    sc = scene_ops.assert_mutable(sid, "후보를 다시 받으려면")

    def work():
        gen_jobs.note(sid, "이미 만들어진 결과를 다시 받는 중… (무과금)")
        return makefun_client.refetch_scene(sid, on_progress=_progress(sid, "재수령", "makefun"))

    return gen_jobs.start(sid, work, "재수령", sync=bool(b.get("sync")),
                          count=_candidates(sc),
                          message="이전 생성 결과를 다시 받는 중… (무과금)")


def r_upscale(b):
    """선택 이미지를 **재생성 없이** 확대해 새 후보로 저장 — 인화 규격을 키우는 유료 호출.

    왜 있나: 승인된 컷이 1200×1800 이면 300DPI 인화는 엽서(4×6)가 한계다. 크기를 올려
    다시 만들면 그림이 달라지고(사람이 승인한 그 컷이 아니다) 과금도 장수만큼 다시 든다.
    확대는 같은 그림의 픽셀만 키운다 — 2400×3600 이면 8×10 이다.

    **assert_mutable 을 걸지 않는다.** 승인 게이트가 지키는 것은 "사람이 고른 그림"인데,
    확대는 그림도 선택본도 승인 상태도 바꾸지 않고 파일 한 장을 더 놓을 뿐이다. 오히려
    APPROVED 컷이야말로 인화 대상이라, 여기서 막으면 이 기능의 목적 자체가 사라진다.
    후보 목록을 건드릴지 말지의 최종 판단은 scene_ops 가 한다 — makefun_client 는 승인
    장면이면 등록을 건너뛰고 되돌리는 방법을 경고로 알린다(그래서 register=False 다).

    유료라서 나머지 안전장치는 생성과 **완전히 같다**: gen_jobs 선점(웹·CLI 공통 잠금으로
    중복 과금 차단) · 백그라운드 실행 · /api/gen-status 진행 조회 · 심장박동 · 로그.
    """
    sid = b.get("scene_id")
    sc = _load_scene(sid)
    # 선택본이 없으면 확대할 대상 자체가 없다. makefun_client 도 같은 검사를 하지만 그쪽은
    # 백그라운드 스레드 안이라, 여기서 미리 걸러야 사용자가 폴링을 기다리지 않고 바로 안다.
    if not vn_core.selected_of(sc):
        raise VNError("선택된 이미지가 없습니다. 확대할 컷을 먼저 고르세요.")

    # 화면 문구·잠금 라벨·사용 대장의 이름을 "업스케일" 하나로 맞춘다 — CLI(--upscale)도
    # 같은 라벨을 쓴다. 잠금 주인을 알려 주는 문구가 창마다 다른 단어를 쓰면 안 된다.
    def work():
        gen_jobs.note(sid, "원본 업로드 후 MakeFun 업스케일 요청 중… (1~3분)")
        return makefun_client.upscale_scene(sid, on_progress=_progress(sid, "업스케일", "makefun"))

    return gen_jobs.start(
        sid, work, "업스케일", sync=bool(b.get("sync")), register=False,
        count=_candidates(sc),
        message="MakeFun 업스케일 중… (1~3분) 진행 상황은 자동으로 갱신됩니다.")


def r_credits(b):
    """MakeFun 크레딧 이력 조회 — 이미지 과금은 없지만 **API 토큰을 쓰는 실호출**이다.

    가볍고 장면과 무관하므로 동기로 처리한다(선점 대상도 아니다). 대신 응답에 그 성격을
    실어 화면이 "이 조회도 토큰을 씁니다" 를 사용자에게 보여줄 수 있게 한다 — 버튼 하나가
    조용히 계정을 두드리는 일이 없도록.

    잔액 단정은 하지 않는다(응답 스키마가 공개돼 있지 않다). 판단은 makefun_client 담당이고
    여기서는 그대로 전달만 한다.
    """
    res = makefun_client.credits()
    return {**res, "billable": False, "token_call": True,
            "notice": "이 조회도 MakeFun API 토큰을 사용합니다(이미지 생성 과금은 없습니다)."}


def r_gen_status(b):
    """생성·업스케일 진행 조회 — {running, message, result?, error?}.

    result 는 끝난 작업이 남긴 것(저장 파일 이름·경고)이다. 백그라운드 작업은 요청이 이미
    끝난 뒤에 결과가 나오므로, 확대본 파일 이름을 화면에 알려 줄 통로가 여기뿐이다.
    """
    return gen_jobs.status(b.get("scene_id"))


def _shown_url(url: str) -> str:
    """화면으로 나가는 주소는 scheme://host:port 만 — user:pw@(basic-auth)는 싣지 않는다.

    doctor·image_gen 이 쓰는 규칙과 같다(vn_core.host_port). LOCAL_LLM_URL 은 비밀값이 아니지만
    리버스 프록시 뒤에 두면 자격증명이 붙는 자리라, 브라우저로 그대로 내보내지 않는다.
    """
    raw = str(url or "").strip()
    try:
        host = vn_core.host_port(raw)
        scheme = urllib.parse.urlsplit(raw).scheme
    except ValueError:
        return ""
    return f"{scheme}://{host}" if host and scheme else host


def r_talk_status(b):
    """로컬 LLM 상태 — {up, url, models|error}. 주소는 마스킹해서 내보낸다.

    studio.js 는 up 만 읽지만(그리고 구서버 호환으로 messages 를 찾는다), 응답 전체가 화면·
    개발자도구에 남으므로 오류 문구에 섞여 나오는 같은 주소까지 함께 가린다.
    """
    st = dict(local_llm.status())
    raw = str(st.get("url", "") or "")
    # remote=True 면 이 PC 에서 serve.ps1 을 실행해도 소용이 없다(서버는 저쪽에 있다).
    st["remote"] = local_llm.is_remote(raw) if raw else False
    shown = _shown_url(raw)
    st["url"] = shown
    err = st.get("error")
    if raw and shown and isinstance(err, str) and raw in err:
        st["error"] = err.replace(raw, shown)
    return st


# ------------------------------------------------- 인물 대화 로그(사용자의 사적 자산)
# 원칙: 이 로그는 어떤 경로로도 "조용히" 줄어들지 않는다. 클라이언트가 보낸 목록으로
# 파일을 통째로 갈아엎지 않고 항상 저장본과 병합한다(명시적 reset:true 만 예외).
# 파일 경로·병합·상한 이관은 talk_store 하나에만 있다(local_llm 도 같은 경로 규칙을 쓴다).
def r_talk_history(b):
    """저장된 인물 대화 이력 → {messages, character_id}. 새 세션이 지난 대화를 이어받는 경로."""
    cid = talk_store.resolve_cid(b.get("character_id"))
    return {"messages": talk_store.load_messages(cid), "character_id": cid}


def r_talk(b):
    """로컬 LLM 으로 인물과 실제 대화 + 어울리는 앨범 사진 표시.

    모델이 [사진:SCENE-ID] 를 붙이거나, 명시적 요청이면 라벨 키워드로 폴백 매칭.
    앨범(승인 이미지)에 실제로 있을 때만, '없다'는 답장이면 억제한다.

    저장은 항상 '저장본 + 이번 대화' 병합이다. reset:true 를 명시했을 때만 새로 시작한다.
    """
    raw = b.get("messages", []) if isinstance(b.get("messages"), list) else []
    incoming = [{"role": m.get("role"), "content": str(m.get("content", "") or "")}
                for m in raw
                if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    # 프롬프트 조립은 prompt_build, 서버 전송은 local_llm — 두 일을 한 이름 뒤에 섞지 않는다.
    # (예전에는 local_llm 이 prompt_build 를 되받아 넘겨주는 통로를 갖고 있었고, 그것이
    #  이 저장소에 마지막으로 남은 import 순환이었다. 호출부는 이 두 줄뿐이었다.)
    sysmsg, meta = prompt_build.persona_prompt(b.get("character_id"))
    cid = str(meta["character_id"])
    reset = bool(b.get("reset"))
    # 모델에 넘길 창은 병합 이력 기준 — 빈 화면에서 시작해도 대화가 이어진다.
    context = (list(incoming) if reset
               else talk_store.merge_messages(talk_store.load_messages(cid), incoming))
    # 모델에 넘기는 창의 크기는 local_llm 이 정한다(기억 요약이 덮는 창과 같아야 한다).
    window = [{"role": m["role"], "content": m["content"]}
              for m in context[-local_llm.TALK_WINDOW:]]
    reply = local_llm.chat([{"role": "system", "content": sysmsg}] + window,
                           timeout=_chat_timeout(llm_queue_wait()))

    last_user = next((m["content"] for m in reversed(context) if m["role"] == "user"), "")
    clean, photo_meta = prompt_build.resolve_photos(reply, meta.get("album", {}), last_user)
    photos = [{"scene_id": p["scene_id"], "url": "/img/" + p["rel"][len("images/"):],
               "caption": p.get("caption", "")}
              for p in photo_meta if p["rel"].startswith("images/")]
    with WRITE_LOCK:
        # 잠금 안에서 다시 읽어 병합한다 — 답장을 기다리는 동안 다른 기기가 남긴 대화도 보존.
        final = (list(incoming) if reset
                 else talk_store.merge_messages(talk_store.load_messages(cid), incoming))
        final.append({"role": "assistant", "content": clean, "photos": photos})
        talk_store.save_messages(cid, final)
    return {"reply": clean, "name": meta["name"], "photos": photos, "saved": len(final)}


def r_talk_to_scene(b):
    """'이 순간을 사진으로' — 최근 대화 → 새 장면(계획) + 이미지 프롬프트. 구현은 vn_compose."""
    res = vn_compose.scene_from_talk(b.get("messages"), b.get("character_id"))
    log.info("대화 → 장면 생성 %s", res.get("scene_id"))
    return res


_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", {".png"}),
    (b"\xff\xd8\xff", {".jpg", ".jpeg"}),
    (b"GIF87a", {".gif"}), (b"GIF89a", {".gif"}),
    (b"II*\x00", {".tif", ".tiff"}), (b"MM\x00*", {".tif", ".tiff"}),
)


def sniff_image(raw: bytes) -> set | None:
    """파일 앞머리(매직바이트)로 실제 이미지 형식을 판정 — 확장자만 믿지 않는다."""
    for sig, exts in _MAGIC:
        if raw.startswith(sig):
            return exts
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return {".webp"}
    return None


def r_upload_image(b):
    """폰 등에서 생성한 이미지를 base64 로 업로드 → images/raw/<scene>/ 저장 후 자동 스캔.

    (폰에서는 이미지를 폴더에 직접 넣을 수 없으므로 이 경로로 '만들기'를 완성한다.)
    """
    sid = b.get("scene_id")
    _require_scene(sid)
    name = os.path.basename(str(b.get("filename", "upload.png")))
    ext = Path(name).suffix.lower()
    if ext not in IMAGE_EXTS:
        raise VNError("이미지 파일만 업로드할 수 있습니다 (png/jpg/jpeg/webp).")
    data = str(b.get("data_b64", ""))
    if data.startswith("data:") and "," in data:   # data URI 접두 제거
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        raise VNError("이미지 데이터를 해석할 수 없습니다.")
    if not raw:
        raise VNError("빈 이미지입니다.")
    if len(raw) > 30_000_000:
        raise VNError("이미지가 너무 큽니다 (30MB 초과).")
    real = sniff_image(raw)
    if real is None:
        raise VNError("이미지 파일이 아닙니다 (PNG/JPEG/WEBP/GIF/TIFF 시그니처 불일치).")
    if ext not in real:
        raise VNError(f"파일 내용과 확장자가 다릅니다 (내용: {'/'.join(sorted(real))}, 이름: {ext}).")
    dest = RAW_DIR / sid
    dest.mkdir(parents=True, exist_ok=True)
    safe = vn_core.safe_slug(Path(name).stem, "upload")
    with WRITE_LOCK:      # 이름 정하기~저장을 한 잠금 안에 둬 동시 업로드가 서로를 덮지 않게
        target = dest / f"{safe}{ext}"
        n = 2
        while target.exists():
            target = dest / f"{safe}-{n}{ext}"
            n += 1
        # 원자적 저장: 전송이 끊겨 반쯤 쓰인 파일이 후보 목록에 등록되는 일을 막는다.
        vn_core.atomic_write_bytes(target, raw)
        reg = scene_ops.register_images(sid)   # 저장 즉시 후보 등록·자동검사
    return {"saved": target.relative_to(ROOT).as_posix(), "count": reg.get("count"),
            "auto": reg.get("auto")}


def r_export_viewer(b):
    # 타임캡슐 감상본: 승인 장면+이미지+뷰어를 단일 HTML 로 (Pillow 있으면 용량 최적화)
    import export_viewer
    out, data = export_viewer.export(bool(b.get("all")),
                                     int(b.get("max_edge", 1600)), int(b.get("quality", 85)))
    # 빠진 컷·경고를 **브라우저까지** 올려 보낸다. 예전에는 서버 콘솔로만 갔고,
    # 스튜디오가 곧 제품인 지금 그 콘솔을 읽는 사람은 없다.
    return {"file": out.relative_to(ROOT).as_posix(),
            "mb": round(out.stat().st_size / 1_000_000, 2),
            "count": len(data.get("scenes") or []),
            "skipped": list(data.get("skipped") or []),
            "warnings": list(data.get("warnings") or [])}


def r_export_pwa(b):
    """감상본을 설치형 앱(PWA) 번들로 — output/pwa/. 아이콘 옵션은 Pillow 가 있을 때만 효과."""
    try:   # 서버는 Pillow·export_viewer 없이도 뜨도록 지연 임포트(r_export 와 같은 규칙)
        import export_pwa
    except Exception as exc:
        raise RuntimeError(f"PWA 내보내기를 불러올 수 없습니다({exc}). "
                           "아이콘을 컷으로 만들려면:  python -m pip install Pillow")
    max_edge = max(480, min(int(b.get("max_edge", 1600) or 1600), 4096))
    quality = max(40, min(int(b.get("quality", 85) or 85), 100))
    kw = {}
    for key, arg, cast in (("cover", "cover_id", str), ("embed_font", "font_spec", str),
                           ("icon_from_cut", "icon_from_cut", bool),
                           ("icon_scene", "icon_scene", str)):
        if b.get(key):
            kw[arg] = cast(b[key])
    out = export_pwa.export(bool(b.get("all")), max_edge, quality, **kw)
    files = sorted(f.name for f in out.glob("*") if f.is_file())
    total = sum((out / f).stat().st_size for f in files)
    return {"dir": out.relative_to(ROOT).as_posix(), "files": files,
            "mb": round(total / 1_000_000, 2)}


def r_logout_all(b):
    """모든 기기의 인증을 즉시 무효화한다(폰을 잃어버렸을 때의 회수 경로).

    다음 접속부터는 PC 화면의 PIN 을 다시 입력해야 한다. 이 요청을 보낸 기기도 포함된다.
    """
    with AUTH_LOCK:
        n = len(AUTH["tokens"])
        AUTH["tokens"].clear()
    log.warning("전체 로그아웃 — 토큰 %d개 무효화", n)
    return {"ok": True, "revoked": n}


POST_ROUTES = {
    "/api/chat": r_chat, "/api/chat-history": r_chat_history,
    "/api/chats": r_chats, "/api/chat-delete": r_chat_delete,
    "/api/work-switch": r_work_switch, "/api/works": r_works,
    "/api/chat-export": r_chat_export, "/api/chat-import": r_chat_import,
    "/api/chat-exports": r_chat_exports,
    "/api/chat-meta": r_chat_meta, "/api/chat-trim": r_chat_trim,
    "/api/storyline": r_storyline,
    "/api/compose": r_compose, "/api/compose-input": r_compose_input,
    "/api/compose-batch": r_compose_batch,
    "/api/compose-job": r_compose_job_start,
    "/api/compose-job-status": r_compose_job_status,
    "/api/compose-job-cancel": r_compose_job_cancel,
    "/api/compose-job-save": r_compose_job_save,
    "/api/compose-job-discard": r_compose_job_discard,
    "/api/compose-manual": r_compose_manual, "/api/scene-brief": r_scene_brief,
    "/api/set-prompt": r_set_prompt, "/api/preflight": r_preflight, "/api/export": r_export,
    "/api/set-crop": r_set_crop, "/api/set-scene": r_set_scene,
    "/api/register-images": r_register, "/api/select": r_select,
    "/api/approve": r_approve, "/api/check": r_check, "/api/lint": r_lint,
    "/api/export-viewer": r_export_viewer, "/api/export-pwa": r_export_pwa,
    "/api/upload-image": r_upload_image,
    "/api/talk": r_talk, "/api/talk-status": r_talk_status,
    "/api/talk-history": r_talk_history,
    "/api/gen-prompt": r_gen_prompt, "/api/gen-image": r_gen_image,
    "/api/image-engine": r_image_engine,
    "/api/gen-status": r_gen_status, "/api/gen-cancel": r_gen_cancel,
    "/api/refetch": r_refetch,
    "/api/upscale": r_upscale, "/api/credits": r_credits,
    "/api/favorite": r_favorite,
    "/api/talk-to-scene": r_talk_to_scene,
    "/api/logout-all": r_logout_all,
}


# ---------------------------------------------------------------- PIN 인증(LAN)
# tokens: {토큰: {"ip": 발급받은 기기, "exp": 만료시각}} — 토큰이 새더라도 다른 기기에서는
#         쓸 수 없고(IP 고정), 쓰지 않으면 3시간 뒤 스스로 만료된다(슬라이딩 갱신).
# fails/until: **IP 별** 오입력 카운터와 잠금 시각. 한 기기의 오타가 다른 기기를 잠그지 않고,
#         한 기기가 5회 틀리면 그 기기만 1분간 잠긴다.
AUTH: dict = {"pin": "", "tokens": {}, "fails": {}, "until": {}}
AUTH_LOCK = threading.RLock()
COOKIE_NAME = "vn_studio"
AUTH_TTL = 3 * 3600          # 미사용 3시간 뒤 만료(요청마다 갱신되는 슬라이딩 만료)
AUTH_MAX_TOKENS = 20         # 기기 20대분
AUTH_FAIL_MAX = 5            # 이 횟수를 넘기면
AUTH_LOCK_SEC = 60           # 이 시간만큼 그 IP 를 잠근다
AUTH_FAIL_DELAY = 0.3        # 실패 응답을 늦춰 대량 시도를 비싸게 만든다
LOGIN_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>스튜디오 잠금</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#17110D;color:#F0E6D8;font-family:system-ui,"Malgun Gothic",sans-serif}
.box{width:min(340px,88vw);text-align:center}h1{font-size:19px;margin:0 0 6px}
p{color:#B4A492;font-size:13px;margin:0 0 18px}
input{width:100%;box-sizing:border-box;font-size:26px;letter-spacing:8px;text-align:center;
padding:12px;border-radius:12px;border:1px solid #4A3A2C;background:#221A14;color:#F0E6D8}
button{width:100%;margin-top:12px;padding:12px;border:0;border-radius:12px;
background:#E0A64B;color:#17110D;font-size:16px;font-weight:700}
#m{color:#E88;font-size:13px;min-height:18px;margin-top:10px}</style>
<div class="box"><h1>스튜디오 잠금</h1>
<p>PC 화면에 표시된 PIN 을 입력하세요.</p>
<form id="f"><input id="p" inputmode="numeric" autocomplete="off" maxlength="6" autofocus>
<button type="submit">열기</button></form><div id="m"></div></div>
<script>
document.getElementById("f").addEventListener("submit",async function(e){e.preventDefault();
 var m=document.getElementById("m");m.textContent="확인 중…";
 try{var r=await fetch("/api/auth",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({pin:document.getElementById("p").value})});
  var d=await r.json();
  /* 보려던 화면으로 돌아간다. 늘 "/" 로 보내면 /chat 을 친 사람이 스튜디오로 끌려간다. */
  if(r.ok){location.replace(location.pathname||"/")}else{m.textContent=d.error||"인증 실패"}}
 catch(err){m.textContent="연결 실패"}});
</script></html>"""


def _issue_token(ip: str) -> str:
    """새 인증 토큰 — 발급받은 기기(IP)에 묶는다. (AUTH_LOCK 은 재진입 가능)"""
    tok = secrets.token_urlsafe(24)
    now = time.time()
    with AUTH_LOCK:
        toks = AUTH["tokens"]
        for t, meta in list(toks.items()):          # 만료분 정리
            if float(meta.get("exp", 0)) <= now:
                del toks[t]
        while len(toks) >= AUTH_MAX_TOKENS:         # 가장 오래된 것부터 밀어낸다
            del toks[min(toks, key=lambda k: float(toks[k].get("exp", 0)))]
        toks[tok] = {"ip": ip, "exp": now + AUTH_TTL}
    return tok


def _token_ok(tok: str, ip: str = "") -> bool:
    """토큰 검증 — 만료·기기(IP) 불일치는 거부하고, 통과하면 만료를 뒤로 민다.

    슬라이딩 만료라 계속 쓰는 폰은 다시 PIN 을 묻지 않고, 서랍에 넣어 둔 기기는
    3시간 뒤 스스로 잠긴다. IP 고정은 토큰이 유출돼도 다른 기기에서 못 쓰게 한다
    (같은 폰이 와이파이를 옮겨 IP 가 바뀌면 PIN 을 한 번 다시 입력하면 된다).
    """
    if not tok:
        return False
    now = time.time()
    with AUTH_LOCK:
        toks = AUTH["tokens"]
        for t, meta in list(toks.items()):
            if float(meta.get("exp", 0)) <= now:
                del toks[t]
        # compare_digest 로 훑어 존재 여부가 응답 시간으로 새지 않게 한다.
        found = None
        for t in toks:
            if secrets.compare_digest(t, tok):
                found = t
                break
        if found is None:
            return False
        meta = toks[found]
        if ip and str(meta.get("ip", "")) != ip:
            log.warning("토큰 기기 불일치 — 발급 %s / 요청 %s", meta.get("ip"), ip)
            return False
        meta["exp"] = now + AUTH_TTL      # 슬라이딩 갱신
        return True


def check_pin(pin: str, ip: str = "") -> str:
    """PIN 확인 → 토큰. 실패는 IP 별로 세고, 연속 실패는 그 IP 를 잠근다(무차별 대입 방지).

    잠금 확인·비교·카운터 증가·잠금 설정이 **하나의 AUTH_LOCK 블록** 안에서 일어난다.
    (예전에는 확인과 증가 사이가 벌어져 있어, 동시에 들이닥친 요청들이 카운터가 오르기
     전의 잠깐을 나눠 쓰면 5회 제한을 넘겨 시도할 수 있었다.)
    """
    ip = str(ip or "")
    with AUTH_LOCK:
        now = time.time()
        if now < float(AUTH["until"].get(ip, 0)):
            raise VNError("입력 시도가 많습니다. 1분 뒤 다시 시도하세요.")
        ok = bool(AUTH["pin"]) and secrets.compare_digest(str(pin or ""), AUTH["pin"])
        if ok:
            AUTH["fails"].pop(ip, None)
            AUTH["until"].pop(ip, None)
            return _issue_token(ip)
        n = int(AUTH["fails"].get(ip, 0)) + 1
        AUTH["fails"][ip] = n
        if n >= AUTH_FAIL_MAX:
            AUTH["fails"][ip] = 0
            AUTH["until"][ip] = now + AUTH_LOCK_SEC
        if len(AUTH["fails"]) > 256:      # 위조 IP 로 메모리를 불리지 못하게
            AUTH["fails"].clear()
        AUTH["until"] = {k: v for k, v in AUTH["until"].items() if v > now}
    log.warning("PIN 인증 실패 %s (%d회)", ip or "?", n)
    time.sleep(AUTH_FAIL_DELAY)   # 잠금 밖에서 지연 — 정상 사용자를 막지 않으면서 시도를 비싸게
    raise VNError("PIN 이 올바르지 않습니다.")


# ---------------------------------------------------------------- 정적 파일
IMG_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
             "webp": "image/webp", "tif": "image/tiff", "tiff": "image/tiff"}
DL_TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
            ".webmanifest": "application/manifest+json", ".js": "text/javascript; charset=utf-8",
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".tiff": "image/tiff", ".zip": "application/zip"}


def safe_path(base: Path, rel: str) -> Path | None:
    """base 아래로만 해석되는 경로(없으면 None).

    판정 규칙은 vn_core.safe_path 하나뿐이다 — '..'·절대경로·드라이브 문자·숨김 항목·
    심볼릭 링크 탈출을 모두 막는다. 여기서는 라우트가 그대로 404 로 답할 수 있게
    예외를 None 으로 바꿔 준다(요청 경로 오류는 사용자 잘못이 아니라 그냥 없는 파일).
    """
    try:
        return vn_core.safe_path(base, rel)
    except (VNError, ValueError, OSError):
        # ValueError: 경로에 널바이트 등 OS 가 거부하는 문자(resolve 가 던진다).
        # OSError: 이름이 너무 길거나 잘못된 경로. 어느 쪽이든 '없는 파일'(404)로 답한다
        # — 500(서버 오류)이 아니라. 잘못된 요청 경로는 사용자 잘못이지 서버 고장이 아니다.
        return None


def etag_for(p: Path, w: int = 0) -> str:
    """mtime·크기(+썸네일 폭) 기반 ETag — 같은 파일은 304 로 끝낸다."""
    st = p.stat()
    return f'W/"{int(st.st_mtime)}-{st.st_size}-{w}"'


def make_thumb(src: Path, w: int):
    """폭 w 로 줄인 JPEG(디스크 캐시). Pillow 가 없거나 실패하면 None → 원본을 보낸다."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        st = src.stat()
        key = hashlib.sha1(
            f"{src.as_posix()}|{int(st.st_mtime)}|{st.st_size}|{w}".encode("utf-8")).hexdigest()
        cache = THUMB_DIR / f"{key}.jpg"
        if cache.is_file():
            return cache.read_bytes(), "image/jpeg"
        with Image.open(src) as im:
            im.load()
            if im.width <= w:
                return None            # 원본이 이미 작으면 변환 이득이 없다
            img = im.convert("RGB")
        img.thumbnail((w, w * 4), Image.LANCZOS)
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        tmp = THUMB_DIR / f"{key}.{threading.get_ident():x}.tmp"   # 동시 요청 충돌 방지
        img.save(tmp, format="JPEG", quality=82, optimize=True)
        os.replace(tmp, cache)
        return cache.read_bytes(), "image/jpeg"
    except Exception as exc:
        log.debug("썸네일 실패 %s: %s", src.name, exc)
        return None


def prune_thumbs(keep_bytes: int = THUMB_MAX_BYTES) -> int:
    """썸네일 캐시를 예산 안으로 — 오래된 것부터 지운다. → 지운 개수.

    후보를 한 장 볼 때마다 한 장씩 쌓이기만 하던 폴더다(지우는 코드가 아예 없었다).
    원본에서 언제든 다시 만들어지는 파생물이라 사람의 허락이 필요 없다 — 그래서 서버가
    뜰 때 한 번 쓸고 시작한다(요청 경로에서 하면 응답이 그만큼 느려진다).
    """
    try:
        files = sorted((f for f in THUMB_DIR.glob("*.jpg") if f.is_file()),
                       key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
    except OSError:
        return 0
    dropped = 0
    for f in files:
        if total <= keep_bytes:
            break
        try:
            total -= f.stat().st_size
            f.unlink()
            dropped += 1
        except OSError:
            pass
    if dropped:
        log.info("썸네일 캐시 정리 %d개 (예산 %.0fMB)", dropped, keep_bytes / 1048576)
    return dropped


def list_downloads() -> list[dict]:
    """output/ 의 감상본·PWA·인화 마스터 색인 — 폰에서 받아가기 위한 목록."""
    out = []
    for f in (OUTPUT_DIR.rglob("*") if OUTPUT_DIR.exists() else []):
        if not f.is_file():
            continue
        rel = f.relative_to(OUTPUT_DIR).as_posix()
        if any(p.startswith(".") for p in rel.split("/")):
            continue                   # .thumbs 등 내부 캐시는 감춘다
        st = f.stat()
        out.append({"path": rel, "url": "/dl/" + urllib.parse.quote(rel),
                    "mb": round(st.st_size / 1_000_000, 2), "mtime": int(st.st_mtime)})
    out.sort(key=lambda d: -d["mtime"])
    return out[:500]


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 = 연결 재사용(keep-alive). 장면 목록 한 번에 이미지 수십 장을 받는 갤러리에서
    # 매번 TCP 연결을 새로 여는 비용이 사라진다. 모든 응답에 정확한 Content-Length 를
    # 붙이는 것이 전제이고(_json·_bytes·_stream 이 보장), 놀고 있는 연결은 timeout 으로 닫힌다.
    protocol_version = "HTTP/1.1"
    timeout = 60  # 소켓 타임아웃 — 본문이 안 오거나 keep-alive 로 놀고 있는 연결을 정리한다

    def log_message(self, *a):
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in ALLOWED_HOSTS

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else ""

    def _is_local(self) -> bool:
        ip = self._client_ip()
        return ip.startswith("127.") or ip in ("::1", "localhost")

    def _is_trusted(self) -> bool:
        """--trust 로 지정한 기기인가 — 그 기기만 PIN 을 묻지 않는다.

        --no-pin 과 다르다: --no-pin 은 같은 와이파이의 **모두**를 풀어 주지만, 이것은
        적어 준 주소 하나만 푼다. 나머지 기기는 그대로 PIN 을 묻는다.

        주의: IP 는 공유기가 빌려주는 번호다. 그 폰이 오래 꺼져 있으면 같은 번호가 다른
        기기에 갈 수 있고, 그러면 그 기기가 PIN 없이 들어온다. 그래서 이 값은 실행할 때만
        유효하고 파일로 남기지 않는다 — 켤 때마다 사람이 다시 적는다.
        """
        return self._client_ip() in TRUSTED_IPS

    def _origin_ok(self, url: str) -> bool:
        """그 URL 이 이 스튜디오 자신의 출처인지 — 허용 호스트(+LAN IP) & 서버 포트만."""
        try:
            u = urllib.parse.urlsplit(url.strip())
            host, port = (u.hostname or "").lower(), u.port
        except ValueError:
            return False
        if u.scheme not in ("http", "https") or host not in ALLOWED_HOSTS:
            return False
        want = {str(SERVER_PORT)} if SERVER_PORT else set()
        hp = (self.headers.get("Host") or "").partition(":")[2].strip()
        if hp.isdecimal():
            want.add(hp)          # 포트포워딩 등으로 대외 포트가 다를 수 있어 Host 포트도 인정
        got = str(port) if port else ("443" if u.scheme == "https" else "80")
        return not want or got in want

    def _csrf_ok(self) -> bool:
        """상태를 바꾸는 POST 의 출처 검증(CSRF 방어).

        브라우저는 교차 출처 POST 에 Origin 을 반드시 붙인다 → 있으면 허용 목록과 대조하고,
        불일치면 403. 사용자가 스튜디오를 켜 둔 채 임의 사이트를 열어도 그 페이지의 fetch 가
        /api/gen-image(유료) 같은 경로를 부를 수 없다.
        Origin 이 없는 요청(같은 출처 fetch·curl·자가진단·CLI)은 기존대로 통과시킨다.
        """
        if (self.headers.get("Sec-Fetch-Site") or "").strip().lower() == "cross-site":
            return False
        origin = (self.headers.get("Origin") or "").strip()
        if origin:
            return False if origin.lower() == "null" else self._origin_ok(origin)
        ref = (self.headers.get("Referer") or "").strip()
        if ref:
            return self._origin_ok(ref)   # Origin 을 안 붙이는 브라우저 경로는 Referer 로 대조
        return True                       # 비-브라우저 경로(curl·selftest·도구)

    def _authed(self) -> bool:
        """PIN 미사용이거나 로컬·신뢰 기기 접속이면 통과. 그 외에는 인증 쿠키가 있어야 한다."""
        if not AUTH["pin"] or self._is_local() or self._is_trusted():
            return True
        raw = self.headers.get("Cookie") or ""
        try:
            jar = http.cookies.SimpleCookie(raw)
        except http.cookies.CookieError:
            return False
        m = jar.get(COOKIE_NAME)
        return _token_ok(m.value if m else "", self._client_ip())

    # ---- 응답 -------------------------------------------------------------
    def _compress(self, data: bytes, ctype: str) -> tuple[bytes, list]:
        """텍스트 응답만 gzip — 장면 목록(JSON)과 스튜디오 HTML 이 폰에서 눈에 띄게 빨라진다.

        이미지·zip 처럼 이미 압축된 형식은 건드리지 않는다(CPU 만 쓰고 크기는 그대로).
        """
        head = ctype.split(";")[0].strip().lower()
        if (len(data) < GZIP_MIN
                or "gzip" not in (self.headers.get("Accept-Encoding") or "").lower()
                or not (head.startswith("text/") or head in (
                    "application/json", "application/javascript",
                    "application/manifest+json", "image/svg+xml"))):
            return data, []
        try:
            return gzip.compress(data, 6), [("Content-Encoding", "gzip"),
                                            ("Vary", "Accept-Encoding")]
        except Exception:
            return data, []

    def _conn(self) -> list:
        """연결을 닫을 참이면 그렇다고 알린다 — HTTP/1.1 클라이언트가 이미 닫힌 소켓을
        재사용하려다 헛돌지 않게(요청이 Connection: close 였던 경우도 포함)."""
        return [("Connection", "close")] if self.close_connection else []

    def _respond(self, code: int, data: bytes, ctype: str, extra: list | None = None) -> None:
        data, enc = self._compress(data, ctype)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in SEC_HEADERS + enc + list(extra or []) + self._conn():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, obj, code: int = 200, extra: list | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._respond(code, body, "application/json; charset=utf-8", extra)

    def _bytes(self, data: bytes, ctype: str, extra: list | None = None) -> None:
        self._respond(200, data, ctype, extra)

    def _trace(self) -> None:
        if not self._is_local():
            log.info("LAN 접속 %s %s %s", self._client_ip(), self.command, self.path[:120])
        else:
            log.debug("%s %s", self.command, self.path[:120])

    def do_GET(self):
        if not self._host_ok():
            self._json({"error": "forbidden host"}, 403)
            return
        self._trace()
        if not self._authed():
            # 사람이 직접 주소창에 치는 문서 경로에는 잠금 화면을 준다.
            # /chat 을 빼놓았더니 폰에서 날 것의 JSON 이 떴다 — 사용자는 먼저 / 로 가서
            # 인증하고 다시 /chat 을 쳐야 했고, 그걸 알 방법이 없었다.
            page = self.path.partition("?")[0]
            if page in ("/", "/chat", "/chat/"):
                body = LOGIN_HTML.encode("utf-8")
                self._bytes(body, "text/html; charset=utf-8",
                            [("Content-Security-Policy", csp_for(body))])
            else:
                self._json({"error": "PIN 인증이 필요합니다.", "auth_required": True}, 401)
            return
        try:
            self._get()
        except (Exception, SystemExit) as exc:  # 어떤 실패도 응답 없는 절단 대신 JSON 오류로
            log.warning("GET %s 실패: %s", self.path[:120], exc)
            try:
                self._json({"error": f"서버 처리 실패: {exc}"}, 500)
            except OSError:
                pass

    def _get(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            try:
                body = STUDIO_HTML.read_bytes()
            except OSError:
                self._json({"error": "tools/studio.html 이 없습니다. 패키지를 다시 확인하세요."}, 500)
                return
            # CSP: 페이지는 자기 출처 안에서만 동작한다(외부 스크립트·외부 연결·프레임 금지).
            self._bytes(body, "text/html; charset=utf-8",
                        [("Content-Security-Policy", csp_for(body))])
        elif path == "/chat" or path == "/chat/":
            # 통합 화면(대화 우선). 스튜디오와 같은 API·같은 데이터를 쓰는 두 번째 입구다.
            # 파일이 없으면 404 로 끝낸다 — 이 화면은 선택 사항이고, 없다고 해서
            # 스튜디오가 못 뜨면 안 된다.
            try:
                body = CHAT_HTML.read_bytes()
            except OSError:
                self._json({"error": "tools/chat_ui.html 이 없습니다."}, 404)
                return
            self._bytes(body, "text/html; charset=utf-8",
                        [("Content-Security-Policy", csp_for(body))])
        elif path == "/api/state":
            self._json(state())
        elif path.startswith("/studio/"):
            self._serve_studio_js(urllib.parse.unquote(path[len("/studio/"):]))
        elif path.startswith("/img/"):
            self._serve_image(urllib.parse.unquote(path[len("/img/"):]),
                              urllib.parse.parse_qs(query))
        elif path == "/dl" or path == "/dl/":
            self._json({"files": list_downloads()})
        elif path.startswith("/dl/"):
            self._serve_download(urllib.parse.unquote(path[len("/dl/"):]),
                                 urllib.parse.parse_qs(query))
        else:
            self._json({"error": "not found"}, 404)

    def _send_304(self, tag: str, cache: str) -> None:
        """본문 없는 재검증 응답 — 같은 파일이면 여기서 끝난다."""
        self.send_response(304)
        self.send_header("ETag", tag)
        self.send_header("Cache-Control", cache)
        for k, v in SEC_HEADERS + self._conn():
            self.send_header(k, v)
        self.end_headers()

    def _serve_studio_js(self, name: str) -> None:
        """tools/<이름>.js 서빙 — 스튜디오와 감상본이 같은 재생 엔진을 쓰게 하는 통로.

        tools/ 아래 **평범한 이름의 .js 파일만** 내보낸다(하위 폴더·숨김·확장자 위장 불가).
        경로 판정은 vn_core.safe_path 하나뿐이고, 그 앞에 이름 형식 관문을 하나 더 둔다.
        내용이 바뀌면 ETag 가 바뀌므로 브라우저는 즉시 새 파일을 받는다.
        """
        cache = f"private, max-age={JS_MAX_AGE}, must-revalidate"
        if not STUDIO_JS_RE.match(name):
            self._json({"error": "not found"}, 404)
            return
        target = safe_path(vn_core.TOOLS, name)
        if target is None or not target.is_file():
            self._json({"error": "not found"}, 404)
            return
        tag = etag_for(target)
        if (self.headers.get("If-None-Match") or "").strip() == tag:
            self._send_304(tag, cache)
            return
        self._bytes(target.read_bytes(), "text/javascript; charset=utf-8",
                    [("ETag", tag), ("Cache-Control", cache)])

    def _serve_image(self, rel: str, qs: dict) -> None:
        target = safe_path(ROOT / "images", rel)
        if target is None or not target.is_file():
            self._json({"error": "not found"}, 404)
            return
        try:
            w = int((qs.get("w") or ["0"])[0])
        except ValueError:
            w = 0
        # 같은 이미지를 반복 전송하지 않도록 mtime·크기 기반 ETag + 캐시 지시(항목 83).
        # 판정을 **읽기 전에** 한다 — 갤러리 새로고침마다 수십 MB 를 다시 읽거나 썸네일을
        # 다시 만들지 않고 304 로 끝낸다.
        tag = etag_for(target, w)
        cache = f"private, max-age={IMG_MAX_AGE}"
        if (self.headers.get("If-None-Match") or "").strip() == tag:
            self._send_304(tag, cache)
            return
        data, ctype = None, IMG_TYPES.get(target.suffix.lower().lstrip("."), "application/octet-stream")
        if w > 0:
            got = make_thumb(target, max(32, min(w, 2048)))
            if got:
                data, ctype = got
        if data is None:
            data = target.read_bytes()
        self._bytes(data, ctype, [("ETag", tag), ("Cache-Control", cache)])

    def _parse_range(self, size: int) -> tuple[int, int] | None | bool:
        """Range 헤더 → (start, end). 없으면 None, 범위가 잘못됐으면 False.

        폰에서 수백 MB 감상본을 받다 끊겼을 때 **이어받기**가 되게 하는 부분이다.
        """
        raw = (self.headers.get("Range") or "").strip().lower()
        if not raw.startswith("bytes="):
            return None
        spec = raw[len("bytes="):].split(",")[0].strip()   # 다중 구간은 첫 구간만 지원
        first, _, last = spec.partition("-")
        try:
            if not first:                      # 'bytes=-500' → 마지막 500바이트
                n = int(last)
                if n <= 0:
                    return False
                start, end = max(0, size - n), size - 1
            else:
                start = int(first)
                end = int(last) if last else size - 1
        except ValueError:
            return False
        if start >= size or start < 0 or end < start:
            return False
        return start, min(end, size - 1)

    def _serve_download(self, rel: str, qs: dict) -> None:
        """output/ 파일 내려주기 — 청크 전송 + 이어받기(Range) + 실행 방지.

        보안: inline 을 명시하지 않으면 **application/octet-stream 으로 강제**한다.
        output/ 에는 내보낸 감상본 HTML 이 있는데, 그것이 스튜디오와 같은 출처에서
        text/html 로 열리면 그 안의 스크립트가 스튜디오의 API 를 그대로 부를 수 있다.
        (감상본을 브라우저에서 바로 보려면 ?inline=1 — 사용자가 스스로 여는 경로다.)
        """
        target = safe_path(OUTPUT_DIR, rel)
        if target is None or not target.is_file():
            self._json({"error": "not found"}, 404)
            return
        inline = bool((qs.get("inline") or [""])[0])
        ctype = (DL_TYPES.get(target.suffix.lower(), "application/octet-stream") if inline
                 else "application/octet-stream")
        quoted = urllib.parse.quote(target.name)
        disp = "inline" if inline else "attachment"
        try:
            size = target.stat().st_size
        except OSError:
            self._json({"error": "not found"}, 404)
            return
        head = [("Content-Disposition", f"{disp}; filename*=UTF-8''{quoted}"),
                ("Cache-Control", "private, no-store"), ("Accept-Ranges", "bytes")]
        rng = self._parse_range(size)
        if rng is False:
            self._json({"error": "range not satisfiable"}, 416,
                       [("Content-Range", f"bytes */{size}")])
            return
        start, end = rng if rng else (0, size - 1)
        length = end - start + 1 if size else 0
        code = 206 if rng else 200
        if rng:
            head.append(("Content-Range", f"bytes {start}-{end}/{size}"))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        for k, v in SEC_HEADERS + head + self._conn():
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD" or not length:
            return
        try:                     # 통째로 메모리에 올리지 않고 조금씩 — 1GB 감상본도 안전하다
            with open(target, "rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(DL_CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True      # 폰이 중간에 끊음 — 정상적인 일이다
        except OSError as exc:
            log.warning("다운로드 전송 실패 %s: %s", rel[:80], exc)
            self.close_connection = True      # 길이를 못 채웠으니 연결을 재사용하면 안 된다

    def do_POST(self):
        if not self._host_ok():
            self._json({"error": "forbidden host"}, 403)
            return
        self._trace()
        if not self._csrf_ok():
            log.warning("교차 출처 POST 차단 %s %s origin=%s", self._client_ip(), self.path[:60],
                        (self.headers.get("Origin") or self.headers.get("Referer") or "")[:80])
            self._json({"error": "교차 출처 요청이 차단되었습니다(CSRF 방어). "
                                 "스튜디오 화면에서 직접 조작하세요."}, 403)
            return
        handler = POST_ROUTES.get(self.path)
        if handler is None and self.path != "/api/auth":
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > MAX_BODY_BYTES:
                # 초과분은 물론, **음수 길이**(위조 헤더)도 여기서 막는다. 음수를 통과시키면
                # 아래 read(length) 가 read(-1) 이 되어 연결이 끊길 때까지 본문을 통째로
                # 메모리에 읽어들이고 json 파싱까지 겹쳐, 인증도 받지 않은 기기가 서버를
                # 메모리 고갈(OOM)로 떨굴 수 있다. 본문을 읽지 않고 거절하므로 이 연결은
                # 재사용할 수 없다(남은 바이트가 다음 요청으로 해석되면 안 된다) — keep-alive 를 끊는다.
                self.close_connection = True
                raise VNError("요청 본문 길이가 올바르지 않습니다(10MB 이하만 허용).")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise VNError("요청 본문이 JSON 객체가 아닙니다.")
            if self.path == "/api/auth":     # 인증 자체는 잠금 대상에서 제외
                tok = check_pin(str(body.get("pin", "")), self._client_ip())
                log.info("PIN 인증 성공 %s", self._client_ip())
                self._json({"ok": True}, 200, [(
                    "Set-Cookie",
                    f"{COOKIE_NAME}={tok}; Path=/; HttpOnly; SameSite=Lax; Max-Age={AUTH_TTL}")])
                return
            if not self._authed():
                self._json({"error": "PIN 인증이 필요합니다.", "auth_required": True}, 401)
                return
            self._json(handler(body))
        except SystemExit as exc:
            # CLI 용 die()/sys.exit 가 핸들러 안에서 터져도 응답 없는 절단 대신 400 으로
            log.warning("POST %s 중단(코드 %s)", self.path, exc.code)
            self._json({"error": f"도구가 중단됨(코드 {exc.code}) — 장면/매니페스트 파일 상태를 확인하세요."}, 400)
        except Exception as exc:  # 실패 사유를 그대로 UI 로 (검사 실패·잘못된 입력 등)
            log.warning("POST %s 실패: %s", self.path, exc)
            self._json({"error": str(exc)}, 400)


def _own_names() -> list[str]:
    """이 기계를 가리키는 **자기 이름들** — DHCP 가 주소를 바꿔도 안 깨지는 길.

    공유기가 빌려주는 IP 는 껐다 켜면 바뀔 수 있다. 그때마다 폰의 북마크도, 다른 PC 의
    설정도 같이 틀어진다. 그런데 같은 랜의 윈도 기계끼리는 **이름**으로 서로를 찾는다
    (실측: 데스크탑에서 ``http://LENOVO:8080`` 이 0.24초에 200 을 냈다). 그래서 이름도
    자기 주소로 인정하면 주소가 바뀌어도 링크가 산다.

    이름을 허용하는 것이 Host 검증을 무르게 하지 않는가 — 무르게 하지 않는다. 여기 담기는
    것은 **이 기계 자신의 이름뿐**이고, 그건 이미 허용한 LAN IP 와 정확히 같은 대상을
    가리킨다. 임의의 이름은 여전히 403 이다(그게 DNS 리바인딩 방어의 핵심이다).
    """
    out: list[str] = []
    try:
        h = socket.gethostname().strip().lower()
    except OSError:
        return out
    if not h:
        return out
    out.append(h)
    short = h.split(".")[0]
    if short and short != h:
        out.append(short)
    out.append(short + ".local")        # mDNS 로 찾는 기기(아이폰 등)를 위해
    return out


def _lan_ips() -> list[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def _resolve_pin(args) -> tuple[str, bool]:
    """LAN 모드면 기본으로 PIN 을 켠다(--no-pin 으로 해제). 값 미지정 시 6자리 생성.

    반환: (pin, generated) — generated 는 '서버가 만든 PIN' 인지 여부다.
    사용자가 --pin 으로 직접 정한 PIN 은 파일에 적지 않는다(본인이 이미 알고 있고,
    다른 실행에서도 같은 값을 쓸 수 있는 값이라 디스크에 남기면 위험만 늘어난다).
    """
    if args.no_pin:
        return "", False
    if args.pin is None and not args.lan:
        return "", False
    given = (args.pin or "").strip()
    if given:
        if not re.fullmatch(r"\d{4,6}", given):
            raise SystemExit("오류: --pin 은 4~6자리 숫자여야 합니다.")
        return given, False
    return f"{secrets.randbelow(1_000_000):06d}", True


def _pin_file_write(pin: str) -> bool:
    """실행 중에만 유효한 PIN 을 조회 가능한 자리에 남긴다(logs/ 는 git 제외 대상)."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        vn_core.atomic_write_text(
            LOG_DIR / "lan_pin.txt",
            f"{pin}\n(이번 실행에만 유효한 접속 PIN — 서버를 끄면 무효)\n")
        return True
    except OSError:
        return False


def _pin_file_clear() -> None:
    """서버가 내려가면 PIN 파일도 지운다 — 유효하지 않은 비밀을 디스크에 남기지 않는다."""
    try:
        (LOG_DIR / "lan_pin.txt").unlink()
    except OSError:
        pass


def _orch_line() -> str:
    """기동 배너의 오케스트레이터 한 줄 — 사용자가 서버를 켜고 가장 먼저 읽는 문장이다.

    예전에는 여기에 은퇴한 외부 API 키의 설정 여부가 찍혔다. 키가 없는 것이 정상인데도
    '미설정' 이라 적혀 있어, 제품이 반쪽으로 돌고 있다는 인상을 매 실행마다 남겼다.
    지금 오케스트레이터는 로컬 LLM 하나뿐이므로 **주소**를 적는다(꺼져 있어도 주소는 맞다).
    """
    mf = vn_core.load_json_safe(MANIFEST, {})
    orch = mf.get("orchestrator") if isinstance(mf.get("orchestrator"), dict) else {}
    if str(orch.get("mode", "")) != "local":
        return "직접 입력(붙여넣기) — manifest.orchestrator.mode 가 local 이 아닙니다"
    url = local_llm.base_url()
    return f"로컬 LLM ({url}{' · 다른 기기' if local_llm.is_remote(url) else ''})"


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 웹툰 웹 스튜디오")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--lan", action="store_true",
                    help="같은 와이파이의 폰 등에서 접속 허용(0.0.0.0 바인딩). 신뢰된 네트워크에서만!")
    ap.add_argument("--pin", nargs="?", const="", default=None,
                    help="외부 기기 접속에 PIN 인증 요구(LAN 모드 기본값). 값을 주면 그 PIN 사용")
    ap.add_argument("--no-pin", action="store_true", help="LAN 모드에서도 PIN 을 쓰지 않음")
    ap.add_argument("--trust", action="append", default=[], metavar="IP",
                    help="이 기기(IP)만 PIN 을 묻지 않는다. 여러 번 쓸 수 있다. "
                         "--no-pin 과 달리 나머지 기기는 그대로 PIN 을 묻는다.")
    ap.add_argument("--verbose", action="store_true", help="요청까지 logs/webapp.log 에 기록")
    args = ap.parse_args()

    setup_logging(args.verbose)
    prune_thumbs()          # 파생 캐시는 서버가 뜰 때 한 번만 쓸고 시작한다(요청 경로는 안 건드린다)
    AUTH["pin"], pin_generated = _resolve_pin(args)
    bind = "0.0.0.0" if args.lan else "127.0.0.1"
    srv = ThreadingHTTPServer((bind, args.port), Handler)
    port = srv.server_address[1]
    globals()["SERVER_PORT"] = port

    # --trust 는 LAN 모드에서만 뜻이 있다(로컬은 이미 면제다). 형식이 아닌 값은 버리고 말한다.
    for raw in (getattr(args, "trust", None) or []):
        ip = str(raw).strip()
        if not ip:
            continue
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            print(f"경고: --trust {ip!r} 은 IP 주소가 아닙니다 — 무시합니다.")
            continue
        TRUSTED_IPS.add(ip)

    # 지난번 작품 전환이 끝나기 전에 서버가 죽었을 수 있다 — 받기 전에 먼저 맞춘다.
    try:
        fix = works.repair()
        if fix.get("repaired"):
            print(f"작품 전환을 마무리했습니다({fix.get('action')}) — 지금 작품: {fix.get('current') or '기본 대화'}")
            log.warning("works.repair: %s", fix)
    except Exception as exc:
        log.warning("works.repair 실패: %s", exc)

    log.info("서버 기동 bind=%s port=%s pin=%s trust=%s", bind, port,
             "on" if AUTH["pin"] else "off", ",".join(sorted(TRUSTED_IPS)) or "-")

    if args.lan:
        ips = _lan_ips()
        names = _own_names()
        # 폰이 보내는 Host(=LAN IP)와 이 기계의 자기 이름만 허용한다(그 외 Host 는 계속 403).
        # 이름을 넣는 이유는 DHCP 다 — 주소가 바뀜어도 http://LENOVO:8765 는 그대로 산다.
        ALLOWED_HOSTS.update(ips)
        ALLOWED_HOSTS.update(names)
        # 폰은 윈도 이름을 못 찾는 일이 많다 — QR 은 IP 를 먼저 둔다(폰에서 확실히 열리는 젠).
        LAN_URLS[:] = ([f"http://{ip}:{port}/" for ip in ips]
                       + [f"http://{n}:{port}/" for n in names[:1]])
        print("=" * 56)
        print("LAN 모드 — 같은 와이파이의 폰/태블릿에서 아래 주소로 접속:")
        for ip in ips:
            print(f"  http://{ip}:{port}/")
        if TRUSTED_IPS:
            # 무엇을 풀어 줬는지는 반드시 화면에 남아야 한다. 조용히 열린 문은 잊힌다.
            for ip in sorted(TRUSTED_IPS):
                print(f"\n  ★ {ip} 는 PIN 없이 들어옵니다 (--trust)")
            print("  (이 설정은 이번 실행에만 유효합니다 — 서버를 끄면 사라집니다)")
        if AUTH["pin"]:
            print(f"\n  접속 PIN:  {AUTH['pin']}   ← 폰 화면에 이 숫자를 입력하세요")
            print("  (이 PC 화면 = 127.0.0.1 접속은 PIN 없이 그대로 사용)")
        else:
            print("⚠ PIN 없음(--no-pin): 같은 네트워크의 다른 기기도 그대로 조작할 수 있습니다.")
        print("⚠ 신뢰된 와이파이에서만 쓰세요.")
        print("  (보조 엔진 토큰은 여전히 서버에만 있고 브라우저로 전달되지 않습니다.)")
        print("=" * 56)
    elif AUTH["pin"]:
        print(f"접속 PIN: {AUTH['pin']} (외부 기기 접속 시 필요)")
    url = f"http://127.0.0.1:{port}/"
    print(f"웹 스튜디오 실행: {url}")
    print(f"스토리·장면: {_orch_line()}  |  로그: logs/webapp.log  |  종료: Ctrl+C")
    # 콘솔을 놓치거나(창 숨김·출력 리다이렉트) 스크롤로 지나쳐도 폰 접속을 못 하게 되면 안 되므로
    # 자동 생성된 PIN 만 파일로 남긴다. 사용자가 --pin 으로 직접 정한 값은 적지 않는다
    # (본인이 이미 아는 값이고, 여러 실행에서 재사용되는 비밀을 디스크에 두면 위험만 커진다).
    if AUTH["pin"] and pin_generated:
        if _pin_file_write(AUTH["pin"]):
            print("  PIN 을 놓쳤다면: logs/lan_pin.txt (서버를 끄면 삭제됩니다)")
    else:
        _pin_file_clear()      # 이번 실행에는 PIN 파일이 없어야 한다(지난 실행의 잔재 정리)
    sys.stdout.flush()   # 출력이 리다이렉트돼도 PIN·주소가 즉시 보이도록
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        _pin_file_clear()      # 유효하지 않은 PIN 을 디스크에 남기지 않는다
        try:
            srv.server_close()
        except OSError:
            pass
        # 생성 스레드는 daemon 이라 여기서 함께 끊긴다. MakeFun 쪽에서는 이미 만들어졌을 수
        # 있으므로, 다시 과금하지 말고 재수령(/api/refetch)으로 받으라고 알려 준다.
        pend = gen_jobs.running()
        # 잠금 파일은 여기서 반드시 푼다 — 안 그러면 다시 켠 뒤 그 장면이 최대 20분(STALE_SEC)
        # 동안 "이미 생성 중" 으로 거절된다(중단된 작업을 회수하러 온 사용자를 막는 꼴).
        gen_jobs.release_all("서버 종료로 중단됨")
        if pend:
            print(f"\n⚠ 진행 중이던 이미지 작업이 중단되었습니다: {', '.join(pend)}")
            print("  MakeFun 에서 이미 만들어졌을 수 있습니다. 다시 켠 뒤 해당 장면에서")
            print("  '재수령'(POST /api/refetch)을 쓰면 추가 과금 없이 결과만 받아옵니다.")
            log.warning("종료 시 진행 중 작업: %s", ", ".join(pend))
    log.info("서버 종료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
