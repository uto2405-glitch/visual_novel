#!/usr/bin/env python3
"""웹 스튜디오 서버 — 5단계 워크플로우의 백엔드. 프론트는 tools/studio.html.

  1) 스토리 탭   : Grok 과 대화하며 스토리라인 작성 (xai_client)
  2) 장면 탭     : 스토리라인 → VN 텍스트 + 이미지 프롬프트 구성 (vn_compose)
  3) (외부·수동) : 이미지 생성 AI 에 프롬프트 붙여넣어 이미지 생성
  4) 장면 탭     : images/raw/<scene_id>/ 폴더 투입 → 스캔 → 선택 → 승인 도장
  5) 뷰어 탭     : 비주얼 노벨 감상

사용법:
  python tools/webapp.py [--port 8765] [--no-browser]
  python tools/webapp.py --lan            # 폰 접속 허용(PIN 자동 생성·콘솔 표시)
  python tools/webapp.py --lan --no-pin   # PIN 없이 (신뢰된 네트워크 전용)

보안:
  * API 키는 환경변수 XAI_API_KEY 로만. 서버 안에서만 쓰이고 브라우저로 전달되지 않는다.
  * 127.0.0.1 전용 바인딩 + Host 헤더 검증(DNS 리바인딩 방어) + /img·/dl 경로 탈출 차단.
  * 상태를 바꾸는 POST 는 Origin/Referer 를 자기 출처와 대조한다(CSRF 방어) — 임의 웹사이트가
    켜져 있는 스튜디오에 fetch 로 유료 생성 등을 시키지 못하게 한다.
  * 인물 대화 로그는 클라이언트 목록으로 덮어쓰지 않고 항상 저장본과 병합한다(reset:true 만 예외).
  * scene_id 는 정규식(SCENE-숫자)으로만 통과 — 경로 탈출·임의 파일 접근 차단.
  * LAN 모드는 PIN 인증이 기본. 127.0.0.1 접속은 면제(로컬 작업은 그대로 편하게).
    인증 토큰은 발급받은 기기(IP)에 묶이고 3시간 미사용 시 만료된다(슬라이딩).
    PIN 오입력은 IP 별로 세고, 5회면 1분 잠금 + 매 실패마다 0.3초 지연(무차별 대입 방지).
  * 모든 응답에 nosniff·no-referrer, 스튜디오 화면에는 CSP. /dl 은 inline 요청이 아니면
    application/octet-stream 으로 내려 output/ 의 HTML 이 동일 출처 스크립트로 실행되지 않게 한다.
  * 프론트는 서버 데이터를 innerHTML 로 넣지 않는다(studio.html 안전 규약).
  * 쓰기 요청은 vn_core.WRITE_LOCK 으로 직렬화된다.

계층: vn_core(경로·JSON·원자적 쓰기) ← advance_scene(저장소) ← scene_ops(상태 전이)
      ← webapp(HTTP). 이 파일에는 **전이 규칙이 없다** — 라우트는 scene_ops 를 부르는
      얇은 어댑터다. 대화 로그는 talk_store, 이미지 프롬프트 조립은 prompt_build 담당.

데이터 보존:
  * 대화 로그(스토리·인물)는 항상 저장본과 병합해 저장하고, 상한을 넘는 오래된 구간도
    버리지 않고 talk_<cid>.archive.jsonl 로 옮긴 뒤에만 잘라낸다.
  * 이미지 생성 스레드는 daemon 이라 **Ctrl+C 로 서버를 끄면 즉시 끊긴다.** 종료 시 진행 중인
    작업이 있으면 콘솔에 알리고, MakeFun 에 이미 만들어진 결과는 POST /api/refetch 로
    추가 과금 없이 다시 받아올 수 있다.

로그: logs/webapp.log (회전). 기본은 오류·생성 실패·LAN 접속만, --verbose 면 요청까지.

의존성: 표준 라이브러리만(썸네일만 선택적으로 Pillow). Python 3.9+.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import http.cookies
import inspect
import json
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
import advance_scene as adv  # noqa: E402
import local_llm  # noqa: E402
import make_grok_input  # noqa: E402
import makefun_client  # noqa: E402
import print_preflight  # noqa: E402
import prompt_build  # noqa: E402
import scene_lint  # noqa: E402
import scene_ops  # noqa: E402
import talk_store  # noqa: E402
import vn_compose  # noqa: E402
import vn_core  # noqa: E402
import xai_client  # noqa: E402
from vn_core import VNError  # noqa: E402

# 경로·상수는 vn_core 가 단일 출처다(아래는 읽기 편하게 붙인 별칭).
ROOT = vn_core.ROOT
MANIFEST = vn_core.MANIFEST
RAW_DIR = vn_core.IMAGES_RAW
STORY_DIR = vn_core.STORY
STUDIO_HTML = vn_core.TOOLS / "studio.html"
OUTPUT_DIR = vn_core.OUTPUT
THUMB_DIR = OUTPUT_DIR / ".thumbs"      # 파생물 — output/ 는 이미 git 제외 대상
FAVORITES = vn_core.PROJECT / "favorites.json"
LOG_DIR = vn_core.LOGS
IMAGE_EXTS = vn_core.IMAGE_EXTS
SCENE_ID_RE = vn_core.SCENE_ID_RE
WRITE_LOCK = vn_core.WRITE_LOCK
CHAT_WINDOW = 24  # API 로 보내는 최근 대화 수 (전체 로그는 디스크에 보존)
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
LAN_URLS: list[str] = []     # LAN 모드에서 폰이 실제로 열 수 있는 주소(QR 용). 그 외에는 빈 목록.
SERVER_PORT = 0              # 실제 바인딩된 포트 — CSRF 출처 검증에서 쓴다(0 = 미기동)
IMG_MAX_AGE = 86400          # /img 브라우저 캐시(초) — ETag 로 무효화되므로 길게 잡는다
GZIP_MIN = 1024              # 이보다 작은 응답은 압축 이득보다 오버헤드가 크다
DL_CHUNK = 256 * 1024        # /dl 전송 단위 — 큰 감상본을 통째로 메모리에 올리지 않는다
SEC_HEADERS = [("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer")]
# 스튜디오 화면(및 잠금 화면)의 콘텐츠 보안 정책. 페이지는 자기 출처 안에서만 동작한다
# — 외부 스크립트·외부 연결·프레임 삽입이 전부 막히므로, 혹시 주입이 생겨도 유출 경로가 없다.
CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' data: blob:; "
       "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; form-action 'self'; base-uri 'none'; object-src 'none'; "
       "frame-ancestors 'none'")

log = logging.getLogger("vn.webapp")
log.addHandler(logging.NullHandler())   # 라이브러리로 import 될 때는 조용히


def setup_logging(verbose: bool = False) -> None:
    """logs/webapp.log 회전 로그. 실패해도(권한 등) 서버 기동을 막지 않는다."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(
            LOG_DIR / "webapp.log", maxBytes=512_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    except OSError:
        pass
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.propagate = False


# ---------------------------------------------------------------- 저장 유틸(별칭)
# 구현은 각각 vn_core(원자적 쓰기)와 talk_store(대화 로그)에 하나씩만 있다.
# 아래 이름은 기존 호출부·자가진단 호환용 별칭이다.
_atomic_write_text = vn_core.atomic_write_text
_write_messages = talk_store.save_log       # 잘라낼 구간을 아카이브로 이관한 뒤 자른다
_merge_talk = talk_store.merge_messages
_load_talk = talk_store.load_messages
_talk_file = talk_store.talk_path
_safe_cid = talk_store.normalize_cid
_resolve_talk_cid = talk_store.resolve_cid
_missing_anchors = scene_ops.missing_anchors
visual_style = prompt_build.visual_style
compose_image_prompt = prompt_build.compose_image_prompt
# 장면 상태 전이는 scene_ops 하나에만 있다(웹·CLI 공용, 승인 잠금·쓰기 잠금 포함).
set_scene_prompt = scene_ops.set_prompt
register_images = scene_ops.register_images
select_image = scene_ops.select_image


def _load_json_safe(path: Path) -> dict | None:
    """손상/비-dict JSON 은 None — 파일 하나가 UI 전체(/api/state)를 죽이지 못하게 한다."""
    return vn_core.load_json_safe(path, {}) or None


# ---------------------------------------------------------------- 상태·도메인
def scene_image_url(sc: dict) -> str | None:
    rel = (sc.get("assets", {}).get("selected_image") or "").strip()
    if not rel:
        raws = sc.get("assets", {}).get("raw_images", [])
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
    sel = (sc.get("assets", {}).get("selected_image") or "").strip()
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


def state() -> dict:
    mf = _load_json_safe(MANIFEST) if MANIFEST.exists() else None
    scenes = []
    for f in (sorted(adv.SCENES.glob("SCENE-*.json")) if adv.SCENES.exists() else []):
        sc = _load_json_safe(f)
        if sc is None:
            continue  # 손상 장면은 건너뛰고 나머지 UI 는 살린다
        scenes.append({
            "scene_id": sc.get("scene_id"), "scene_order": sc.get("scene_order"),
            "status": sc.get("status"), "purpose": sc.get("purpose", ""),
            "dialogue": sc.get("dialogue", []),
            "prompt": sc.get("prompt", {}).get("grok_output", ""),
            "raw_images": sc.get("assets", {}).get("raw_images", []),
            "selected_image": sc.get("assets", {}).get("selected_image", ""),
            "review": sc.get("review", {}), "image_url": scene_image_url(sc),
            "print": scene_print(sc),
            "choices": sc.get("choices", []), "branch": sc.get("branch", []),
            "ending": bool(sc.get("ending")),
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
            "key_set": xai_client.key_set(), "model": model,
            "orch_local": orch_local,
            "mf_token": bool(os.environ.get(makefun_client.TOKEN_ENV, "").strip()),
            "characters": [{"id": c.get("character_id"), "name": c.get("name", "")}
                           for c in (mf or {}).get("characters", [])],
            "favorites": load_favorites(),
            # 폰 접속 QR 은 반드시 폰에서 열리는 주소여야 한다(127.0.0.1 은 폰 자신을 가리킨다).
            "lan_urls": list(LAN_URLS),
            "episodes": [e for e in (mf or {}).get("episodes", []) if isinstance(e, dict)],
            "scenes": scenes, "storyline": storyline,
            # 스토리 챗로그는 여기 싣지 않는다 — 대화가 길어질수록 모든 탭의 새로고침이
            # 같이 무거워졌다. 스토리 탭이 필요할 때만 POST /api/chat-history 로 받아간다.
            # (키는 남겨 둔다: 예전 프론트가 S.chat 을 그대로 순회해도 깨지지 않게.)
            "chat": [], "chat_count": chat_count()}


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


def story_context() -> str:
    """스토리 챗이 '지금 이 작품'을 알고 답하도록 붙이는 요약 컨텍스트."""
    mf = _load_json_safe(MANIFEST) or {}
    out = []
    if str(mf.get("title", "")).strip():
        out.append(f"[작품] {mf['title']}")
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    if chars:
        out.append("[등장인물] " + " / ".join(
            f"{c.get('character_id')} {c.get('name', '')}"
            + (f"({(c.get('profile') or {}).get('age', '')}세)" if (c.get('profile') or {}).get('age') else "")
            for c in chars))
    locs = [l for l in mf.get("locations", []) if isinstance(l, dict)]
    if locs:
        out.append("[장소] " + " / ".join(
            f"{l.get('location_id')} {l.get('name', '')}" for l in locs))
    sl = ""
    if (STORY_DIR / "storyline.md").exists():
        sl = (STORY_DIR / "storyline.md").read_text(encoding="utf-8").strip()
    if sl:
        out.append("[현재 스토리라인]\n" + sl[:1500])
    lines = []
    for f in (sorted(adv.SCENES.glob("SCENE-*.json")) if adv.SCENES.exists() else [])[:40]:
        sc = _load_json_safe(f) or {}
        lines.append(f"- {sc.get('scene_id')} [{sc.get('status', '')}] {str(sc.get('purpose', ''))[:40]}")
    if lines:
        out.append("[구성된 장면]\n" + "\n".join(lines))
    return "\n".join(out)


def do_chat(messages: list[dict]) -> str:
    ctx = story_context()
    sys_msg = {"role": "system",
               "content": "너는 비주얼 노벨/웹툰 스토리 기획 파트너다. 한국어로 간결하고 구체적으로 답한다.\n"
                          "아래는 지금 작업 중인 작품의 현재 상태다. 이 설정과 이어지도록 제안하고, "
                          "새 인물·장소를 만들 때만 새로 제안하라.\n\n" + ctx}
    window = messages[-CHAT_WINDOW:]  # 비용·컨텍스트 관리: 최근 대화만 전송
    reply = vn_compose.orch_chat([sys_msg] + window, temperature=0.7, max_tokens=1000)
    path = talk_store.story_chat_path()
    with WRITE_LOCK:
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
    path = adv.scene_path(sid)
    if not path.exists():
        raise VNError(f"장면을 찾을 수 없습니다: {sid}")
    return path


def _load_scene(sid) -> dict:
    """검증된 장면 읽기 — 손상 파일은 VNError(=400)로, 요청 스레드는 살아남는다."""
    return adv.load(_require_scene(sid))


# ---------------------------------------------------------------- POST 라우팅
# 각 핸들러는 요청 body(dict) 를 받아 응답 dict 를 반환하거나 RuntimeError 를 던진다.
def r_chat(b):
    return {"reply": do_chat(b.get("messages", []))}


def r_chat_history(b):
    """저장된 스토리 대화 이력 → {messages}. /api/state 에서 분리한 무거운 부분이다."""
    return {"messages": talk_store.load_log(talk_store.story_chat_path())}


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


def r_compose_manual(b):
    exp = int(b["count"]) if str(b.get("count", "")).strip() else None
    return vn_compose.compose_from_json(b.get("text", ""), bool(b.get("force")), expected=exp)


def r_grok_input(b):
    _require_scene(b.get("scene_id"))
    return {"text": make_grok_input.build_input(b["scene_id"])}


def r_set_prompt(b):
    return scene_ops.set_prompt(b.get("scene_id"), b.get("text", ""), bool(b.get("fix_anchors")))


def r_preflight(b):
    sc = _load_scene(b.get("scene_id"))
    sel = (sc.get("assets", {}).get("selected_image") or "").strip()
    if not sel:
        raise VNError("선택된 이미지가 없습니다. 먼저 이미지를 선택하세요.")
    size = print_preflight.image_size(ROOT / sel)
    if not size:
        return {"px": None, "rows": [], "printable": None}
    return print_preflight.preflight_image(size[0], size[1], int(b.get("dpi", 300)))


_CROP_ANCHORS = {"center", "top", "bottom", "left", "right"}


def r_set_crop(b):
    """인화 크롭 기준점 저장 — 어디를 살릴지는 사람이 정한다(print_export.crop_anchor)."""
    sid = b.get("scene_id")
    _require_scene(sid)
    anchor = str(b.get("anchor", "center"))
    if anchor not in _CROP_ANCHORS:
        raise VNError(f"crop_anchor 는 {'/'.join(sorted(_CROP_ANCHORS))} 중 하나여야 합니다.")
    with WRITE_LOCK:
        path = adv.scene_path(sid)
        sc = adv.load(path)
        pr = sc.get("print") if isinstance(sc.get("print"), dict) else {}
        pr["crop_anchor"] = anchor
        sc["print"] = pr
        adv.save(path, sc)
    return {"scene_id": sid, "crop_anchor": anchor}


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
    params = inspect.signature(print_export.export_batch).parameters
    kw = {}
    if only_ids is not None:
        if "only_ids" not in params:
            raise RuntimeError("설치된 print_export 가 즐겨찾기 필터(only_ids)를 지원하지 않습니다.")
        kw["only_ids"] = only_ids
    # 인화 옵션(여백 모드·재단선 등)은 요청에 있을 때만, 그리고 도구가 받는 것만 넘긴다
    for key, cast in (("mode", str), ("bg", str), ("upscale", str),
                      ("marks", bool), ("order_prefix", bool)):
        if key in b and key in params:
            kw[key] = cast(b[key])
    summ = print_export.export_batch(
        short_in, long_in, dpi=int(b.get("dpi", 300)), bleed=float(b.get("bleed", 0)),
        anchor=str(b.get("anchor", "center")), include_all=inc_all, scene_filter=None,
        skip_upscale=bool(b.get("skip_upscale")), **kw)
    if b.get("contact"):
        print_export.contact_sheet(_pick(print_export.collect(None, inc_all)))
    return {"count": summ["count"], "dir": summ["dir"], "upscaled": summ["upscaled"],
            "skipped": summ["skipped"], "missing": summ["missing"]}


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
    code, out = adv.run_checker()
    return {"pass": code == 0, "output": out}


def r_lint(b):
    return scene_lint.lint_scenes()


def r_gen_prompt(b):
    """로컬 LLM 으로 장면 이미지 프롬프트 생성 (그록 대체) → 저장 + 자동 검사."""
    sid = b.get("scene_id")
    sc = _load_scene(sid)
    return scene_ops.set_prompt(sid, prompt_build.compose_image_prompt(sc))


# ------------------------------------------------- 이미지 생성 (중복 방지·백그라운드)
_GEN_LOCK = threading.Lock()
_GEN_JOBS: dict[str, dict] = {}   # scene_id → {running, message, ts}


def _gen_claim(sid: str) -> None:
    """같은 장면의 동시 생성을 막는다 — 폰과 PC 에서 동시에 눌러도 과금은 한 번만.

    (20분 넘게 끝나지 않은 표시는 죽은 작업으로 보고 풀어 준다 — 영구 잠금 방지.)
    """
    with _GEN_LOCK:
        job = _GEN_JOBS.get(sid)
        if job and job.get("running") and time.time() - float(job.get("ts") or 0) < 1200:
            raise VNError(f"{sid} 이미지를 이미 생성 중입니다. 끝난 뒤 다시 시도하세요.")
        _GEN_JOBS[sid] = {"running": True, "message": "생성 준비 중…", "ts": time.time()}


def running_jobs() -> list[str]:
    """아직 끝나지 않은 생성 작업 — 서버 종료 시 사용자에게 알려 주기 위한 목록."""
    now = time.time()
    with _GEN_LOCK:
        return sorted(sid for sid, j in _GEN_JOBS.items()
                      if j.get("running") and now - float(j.get("ts") or 0) < 1200)


def _gen_note(sid: str, message: str, running: bool = True) -> None:
    with _GEN_LOCK:
        _GEN_JOBS[sid] = {"running": running, "message": message, "ts": time.time()}


def _job_run(sid: str, label: str, work) -> dict:
    """생성/재수령 공통 실행틀 — 성공/실패 어느 쪽이든 in-flight 표시를 반드시 해제한다."""
    try:
        files = work()
        _gen_note(sid, f"{len(files)}장 수신 · 등록·검사 중…")
        reg = scene_ops.register_images(sid)
        reg["generated"] = [f.name for f in files]
        _gen_note(sid, f"완료 — {len(files)}장 {label} · 자동검사 {reg.get('auto', '')}",
                  running=False)
        log.info("%s 완료 %s (%d장)", label, sid, len(files))
        return reg
    except Exception as exc:
        log.warning("%s 실패 %s: %s", label, sid, exc)
        _gen_note(sid, f"실패: {exc}", running=False)
        raise


def _gen_run(sid: str, n: int) -> dict:
    def work():
        _gen_note(sid, "MakeFun 에 생성 요청 중… (1~3분)")
        return makefun_client.generate_for_scene(sid, n=n)
    return _job_run(sid, "생성", work)


def _refetch_run(sid: str) -> dict:
    def work():
        _gen_note(sid, "이미 만들어진 결과를 다시 받는 중… (무과금)")
        return makefun_client.refetch_scene(sid)
    return _job_run(sid, "재수령", work)


def _start_job(sid: str, b: dict, runner, message: str, count: int) -> dict:
    """백그라운드 기본 + sync:true 면 동기 — 폰 브라우저가 기다리다 끊기지 않게 한다."""
    _gen_claim(sid)
    if b.get("sync"):
        return runner()

    def _bg():
        try:
            runner()
        except Exception:
            pass   # 사유는 _job_run 이 로그·진행 메시지에 남긴다(스레드는 조용히 종료)

    threading.Thread(target=_bg, daemon=True).start()
    return {"started": True, "running": True, "scene_id": sid, "message": message,
            "generated": [], "auto": "진행 중", "count": count}


def r_gen_image(b):
    """MakeFun AI 로 장면 이미지 생성 → images/raw/<scene>/ 저장 + 자동 등록·검사.

    기본은 백그라운드 실행 후 즉시 응답(폰 브라우저 타임아웃 방지) — 진행은 /api/gen-status.
    sync:true 면 예전처럼 끝날 때까지 기다렸다가 결과를 반환한다.
    """
    sid = b.get("scene_id")
    sc = _load_scene(sid)
    if sc.get("status") == "APPROVED":
        raise VNError("APPROVED 장면입니다. 다시 생성하려면 먼저 revise 하세요.")
    n = max(1, min(int(b.get("n", 1) or 1), 4))
    return _start_job(sid, b, lambda: _gen_run(sid, n),
                      "MakeFun 생성 중… (1~3분) 진행 상황은 자동으로 갱신됩니다.",
                      len(sc.get("assets", {}).get("raw_images", [])))


def r_refetch(b):
    """이미 만들어진 MakeFun 작업 결과를 다시 받아 온다 — **새로 만들지 않으므로 무과금**.

    생성 도중 서버가 꺼졌거나(생성 스레드는 daemon 이라 Ctrl+C 에 즉시 끊긴다) 다운로드가
    끊긴 경우, 과금을 다시 치르지 않고 결과만 회수하는 경로다.
    """
    sid = b.get("scene_id")
    sc = _load_scene(sid)
    if sc.get("status") == "APPROVED":
        raise VNError("APPROVED 장면입니다. 후보를 다시 받으려면 먼저 revise 하세요.")
    return _start_job(sid, b, lambda: _refetch_run(sid),
                      "이전 생성 결과를 다시 받는 중… (무과금)",
                      len(sc.get("assets", {}).get("raw_images", [])))


def r_gen_status(b):
    """생성 진행 조회 — {running, message}."""
    sid = b.get("scene_id")
    if not vn_core.is_scene_id(sid):
        raise VNError(f"장면 ID 형식이 올바르지 않습니다: {sid!r}")
    with _GEN_LOCK:
        job = dict(_GEN_JOBS.get(sid) or {})
    return {"running": bool(job.get("running")), "message": str(job.get("message", "")),
            "scene_id": sid}


def r_talk_status(b):
    return local_llm.status()


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
    sysmsg, meta = local_llm.persona_prompt(b.get("character_id"))
    cid = str(meta["character_id"])
    reset = bool(b.get("reset"))
    # 모델에 넘길 창은 병합 이력 기준 — 빈 화면에서 시작해도 대화가 이어진다.
    context = (list(incoming) if reset
               else talk_store.merge_messages(talk_store.load_messages(cid), incoming))
    win = int(getattr(local_llm, "TALK_WINDOW", 16) or 16)   # 기억 요약이 덮는 창과 같은 크기
    window = [{"role": m["role"], "content": m["content"]} for m in context[-win:]]
    reply = local_llm.chat([{"role": "system", "content": sysmsg}] + window)

    last_user = next((m["content"] for m in reversed(context) if m["role"] == "user"), "")
    clean, photo_meta = local_llm.resolve_photos(reply, meta.get("album", {}), last_user)
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


def _next_scene_slot() -> tuple[str, int]:
    """다음 scene_id 와 scene_order (order 는 1부터 연속을 유지)."""
    nums, order = [], 0
    for f in (sorted(adv.SCENES.glob("SCENE-*.json")) if adv.SCENES.exists() else []):
        sc = _load_json_safe(f) or {}
        m = re.fullmatch(r"SCENE-(\d+)", str(sc.get("scene_id", "")))
        if m:
            nums.append(int(m.group(1)))
        try:
            order = max(order, int(sc.get("scene_order") or 0))
        except (TypeError, ValueError):
            pass
    return f"SCENE-{(max(nums) + 1 if nums else 1):03d}", order + 1


def _extract_json_object(text: str) -> dict:
    body = re.sub(r"```(?:json)?", "", str(text)).strip()
    s_i, e_i = body.find("{"), body.rfind("}")
    if s_i < 0 or e_i <= s_i:
        raise RuntimeError("장면 JSON 을 찾지 못했습니다. 대화를 조금 더 이어간 뒤 다시 시도하세요.")
    try:
        d = json.loads(body[s_i:e_i + 1])
    except ValueError as exc:
        raise RuntimeError(f"장면 JSON 해석 실패({exc}). 다시 시도해 주세요.")
    if not isinstance(d, dict):
        raise RuntimeError("장면 JSON 최상위가 객체가 아닙니다.")
    return d


def r_talk_to_scene(b):
    """'이 순간을 사진으로' — 최근 대화 → 새 장면(계획) + 이미지 프롬프트까지.

    이미지 생성은 하지 않는다(과금 대상). 만들어진 장면은 PROMPT 상태로 남고,
    사용자가 장면 탭에서 확인한 뒤 직접 생성 버튼을 누른다.
    """
    msgs = b.get("messages", []) if isinstance(b.get("messages"), list) else []
    talk = [f"{'나' if m.get('role') == 'user' else '상대'}: {str(m.get('content', ''))[:300]}"
            for m in msgs[-12:] if isinstance(m, dict) and str(m.get("content", "")).strip()]
    if not talk:
        raise RuntimeError("장면으로 만들 대화가 없습니다. 먼저 대화를 나눠 주세요.")

    mf = _load_json_safe(MANIFEST) or {}
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    locs = [l for l in mf.get("locations", []) if isinstance(l, dict)]
    if not chars:
        raise RuntimeError("매니페스트에 캐릭터가 없습니다. 먼저 작품을 세팅하세요.")
    who = b.get("character_id")   # 지금 대화 중인 상대 — 화자 배정을 정확히 하기 위해
    char_block = "\n".join(
        f"- {c.get('character_id')} {c.get('name', '')}"
        + ("  ← '상대' 는 이 인물" if c.get("character_id") == who else "")
        for c in chars)
    loc_block = "\n".join(f"- {l.get('location_id')} {l.get('name', '')}: {l.get('description', '')}"
                          for l in locs)
    ask = ("아래는 두 사람이 방금 나눈 대화다. 이 순간을 한 컷의 장면으로 만들어라.\n"
           "다른 말 없이 JSON 객체 하나만 출력하라.\n\n"
           f"[대화]\n{chr(10).join(talk)}\n\n[캐릭터]\n{char_block}\n\n[장소]\n{loc_block}\n\n"
           '{"purpose":"장면 목적(한국어)","action_beat":"동작(한국어)","emotion":"감정(한국어)",'
           '"time":"시간대(한국어)","location_id":"위 목록의 id",'
           '"camera":{"shot":"medium","angle":"eye","framing":"center","focus":"face"},'
           '"dialogue":[{"speaker_id":"위 목록의 id","text":"대사(한국어)"}]}')
    item = _extract_json_object(local_llm.chat([{"role": "user", "content": ask}],
                                               temperature=0.6, max_tokens=700))

    char_ids = [c.get("character_id") for c in chars]
    loc_ids = {l.get("location_id") for l in locs}
    with WRITE_LOCK:
        sid, order = _next_scene_slot()
        idx = int(re.sub(r"\D", "", sid) or 1)
        sc = vn_compose._build_scene(item, idx, char_ids, loc_ids, locs)
        sc["scene_id"], sc["scene_order"] = sid, order
        sc["status"] = "SCENE_PLAN"
        sc["prompt"]["grok_output"] = ""
        adv.SCENES.mkdir(parents=True, exist_ok=True)
        adv.save(adv.scene_path(sid), sc)
    log.info("대화 → 장면 생성 %s", sid)
    # 프롬프트까지만(생성은 사용자 몫)
    res = scene_ops.set_prompt(sid, prompt_build.compose_image_prompt(sc))
    saved = _load_json_safe(adv.scene_path(sid)) or {}
    res.update({"scene_id": sid, "scene_order": order, "purpose": saved.get("purpose", ""),
                "prompt": (saved.get("prompt") or {}).get("grok_output", "")})
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
    out = export_viewer.export(bool(b.get("all")),
                               int(b.get("max_edge", 1600)), int(b.get("quality", 85)))
    return {"file": out.relative_to(ROOT).as_posix(),
            "mb": round(out.stat().st_size / 1_000_000, 2)}


def r_export_pwa(b):
    """감상본을 설치형 앱(PWA) 번들로 — output/pwa/. 아이콘 옵션은 Pillow 가 있을 때만 효과."""
    try:   # 서버는 Pillow·export_viewer 없이도 뜨도록 지연 임포트(r_export 와 같은 규칙)
        import export_pwa
    except Exception as exc:
        raise RuntimeError(f"PWA 내보내기를 불러올 수 없습니다({exc}). "
                           "아이콘을 컷으로 만들려면:  python -m pip install Pillow")
    max_edge = max(480, min(int(b.get("max_edge", 1600) or 1600), 4096))
    quality = max(40, min(int(b.get("quality", 85) or 85), 100))
    params = inspect.signature(export_pwa.export).parameters
    kw = {}
    for key, arg, cast in (("cover", "cover_id", str), ("embed_font", "font_spec", str),
                           ("icon_from_cut", "icon_from_cut", bool),
                           ("icon_scene", "icon_scene", str)):
        if b.get(key) and arg in params:
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
    "/api/storyline": r_storyline,
    "/api/compose": r_compose, "/api/compose-input": r_compose_input,
    "/api/compose-manual": r_compose_manual, "/api/grok-input": r_grok_input,
    "/api/set-prompt": r_set_prompt, "/api/preflight": r_preflight, "/api/export": r_export,
    "/api/set-crop": r_set_crop,
    "/api/register-images": r_register, "/api/select": r_select,
    "/api/approve": r_approve, "/api/check": r_check, "/api/lint": r_lint,
    "/api/export-viewer": r_export_viewer, "/api/export-pwa": r_export_pwa,
    "/api/upload-image": r_upload_image,
    "/api/talk": r_talk, "/api/talk-status": r_talk_status,
    "/api/talk-history": r_talk_history,
    "/api/gen-prompt": r_gen_prompt, "/api/gen-image": r_gen_image,
    "/api/gen-status": r_gen_status, "/api/refetch": r_refetch,
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
  if(r.ok){location.replace("/")}else{m.textContent=d.error||"인증 실패"}}
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
    except VNError:
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
        """PIN 미사용이거나 로컬 접속이면 통과. 그 외에는 인증 쿠키가 있어야 한다."""
        if not AUTH["pin"] or self._is_local():
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
            if self.path == "/" or self.path.startswith("/?"):
                self._bytes(LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8",
                            [("Content-Security-Policy", CSP)])
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
                        [("Content-Security-Policy", CSP)])
        elif path == "/api/state":
            self._json(state())
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

    def _serve_image(self, rel: str, qs: dict) -> None:
        target = safe_path(ROOT / "images", rel)
        if target is None or not target.is_file():
            self._json({"error": "not found"}, 404)
            return
        try:
            w = int((qs.get("w") or ["0"])[0])
        except ValueError:
            w = 0
        data, ctype = None, IMG_TYPES.get(target.suffix.lower().lstrip("."), "application/octet-stream")
        if w > 0:
            got = make_thumb(target, max(32, min(w, 2048)))
            if got:
                data, ctype = got
        if data is None:
            data = target.read_bytes()
        # 같은 이미지를 반복 전송하지 않도록 mtime·크기 기반 ETag + 캐시 지시(항목 83)
        tag = etag_for(target, w)
        if (self.headers.get("If-None-Match") or "").strip() == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", f"private, max-age={IMG_MAX_AGE}")
            for k, v in SEC_HEADERS + self._conn():
                self.send_header(k, v)
            self.end_headers()
            return
        self._bytes(data, ctype, [("ETag", tag),
                                 ("Cache-Control", f"private, max-age={IMG_MAX_AGE}")])

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
            if length > 10_000_000:
                # 본문을 읽지 않고 거절하므로 이 연결은 재사용할 수 없다(남은 바이트가
                # 다음 요청으로 해석되면 안 된다) — keep-alive 를 끊는다.
                self.close_connection = True
                raise VNError("요청 본문이 너무 큽니다(10MB 초과).")
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


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 웹툰 웹 스튜디오")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--lan", action="store_true",
                    help="같은 와이파이의 폰 등에서 접속 허용(0.0.0.0 바인딩). 신뢰된 네트워크에서만!")
    ap.add_argument("--pin", nargs="?", const="", default=None,
                    help="외부 기기 접속에 PIN 인증 요구(LAN 모드 기본값). 값을 주면 그 PIN 사용")
    ap.add_argument("--no-pin", action="store_true", help="LAN 모드에서도 PIN 을 쓰지 않음")
    ap.add_argument("--verbose", action="store_true", help="요청까지 logs/webapp.log 에 기록")
    args = ap.parse_args()

    setup_logging(args.verbose)
    AUTH["pin"], pin_generated = _resolve_pin(args)
    bind = "0.0.0.0" if args.lan else "127.0.0.1"
    srv = ThreadingHTTPServer((bind, args.port), Handler)
    port = srv.server_address[1]
    globals()["SERVER_PORT"] = port
    key = "설정됨" if xai_client.key_set() else "미설정 (스토리/장면구성 탭은 수동 모드로)"
    log.info("서버 기동 bind=%s port=%s pin=%s", bind, port, "on" if AUTH["pin"] else "off")

    if args.lan:
        ips = _lan_ips()
        ALLOWED_HOSTS.update(ips)   # 폰이 보내는 Host(=LAN IP)를 허용(그 외 Host 는 계속 403)
        LAN_URLS[:] = [f"http://{ip}:{port}/" for ip in ips]   # /api/state → 폰 접속 QR
        print("=" * 56)
        print("LAN 모드 — 같은 와이파이의 폰/태블릿에서 아래 주소로 접속:")
        for ip in ips:
            print(f"  http://{ip}:{port}/")
        if AUTH["pin"]:
            print(f"\n  접속 PIN:  {AUTH['pin']}   ← 폰 화면에 이 숫자를 입력하세요")
            print("  (이 PC 화면 = 127.0.0.1 접속은 PIN 없이 그대로 사용)")
        else:
            print("⚠ PIN 없음(--no-pin): 같은 네트워크의 다른 기기도 그대로 조작할 수 있습니다.")
        print("⚠ 신뢰된 와이파이에서만 쓰세요.")
        print("  (API 키는 여전히 서버에만 있고 브라우저로 전달되지 않습니다.)")
        print("=" * 56)
    elif AUTH["pin"]:
        print(f"접속 PIN: {AUTH['pin']} (외부 기기 접속 시 필요)")
    url = f"http://127.0.0.1:{port}/"
    print(f"웹 스튜디오 실행: {url}")
    print(f"XAI_API_KEY: {key}  |  로그: logs/webapp.log  |  종료: Ctrl+C")
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
        pend = running_jobs()
        if pend:
            print(f"\n⚠ 진행 중이던 이미지 작업이 중단되었습니다: {', '.join(pend)}")
            print("  MakeFun 에서 이미 만들어졌을 수 있습니다. 다시 켠 뒤 해당 장면에서")
            print("  '재수령'(POST /api/refetch)을 쓰면 추가 과금 없이 결과만 받아옵니다.")
            log.warning("종료 시 진행 중 작업: %s", ", ".join(pend))
    log.info("서버 종료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
