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
  * 프론트는 서버 데이터를 innerHTML 로 넣지 않는다(studio.html 안전 규약).
  * 쓰기 요청은 advance_scene.WRITE_LOCK 으로 직렬화된다.

로그: logs/webapp.log (회전). 기본은 오류·생성 실패·LAN 접속만, --verbose 면 요청까지.

의존성: 표준 라이브러리만(썸네일만 선택적으로 Pillow). Python 3.9+.
"""
from __future__ import annotations

import argparse
import base64
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
import scene_lint  # noqa: E402
import vn_compose  # noqa: E402
import xai_client  # noqa: E402

adv._console_guard()

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project" / "manifest.json"
RAW_DIR = ROOT / "images" / "raw"
STORY_DIR = vn_compose.STORY_DIR
STUDIO_HTML = Path(__file__).resolve().parent / "studio.html"
OUTPUT_DIR = ROOT / "output"
THUMB_DIR = OUTPUT_DIR / ".thumbs"      # 파생물 — output/ 는 이미 git 제외 대상
FAVORITES = ROOT / "project" / "favorites.json"
LOG_DIR = ROOT / "logs"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
CHAT_WINDOW = 24  # API 로 보내는 최근 대화 수 (전체 로그는 디스크에 보존)
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
SCENE_ID_RE = re.compile(r"^SCENE-\d{3,}$")
LOG_CAP = 1_500_000          # 대화 로그 파일 상한(초과분은 오래된 대화부터 잘라낸다)
LAN_URLS: list[str] = []     # LAN 모드에서 폰이 실제로 열 수 있는 주소(QR 용). 그 외에는 빈 목록.
SERVER_PORT = 0              # 실제 바인딩된 포트 — CSRF 출처 검증에서 쓴다(0 = 미기동)
IMG_MAX_AGE = 86400          # /img 브라우저 캐시(초) — ETag 로 무효화되므로 길게 잡는다
DEFAULT_STYLE = "bright cel-shaded Korean romance webtoon, soft warm palette, clean line art"

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


# ---------------------------------------------------------------- 저장 유틸
def _atomic_write_text(path: Path, text: str) -> None:
    """임시 파일 → os.replace. 저장 중 강제 종료돼도 원본 로그가 반쯤 잘리지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_messages(path: Path, messages: list, cap: int = LOG_CAP) -> None:
    """대화 로그 저장 — 무한 성장 방지로 상한을 넘으면 오래된 대화부터 버린다.

    (새 파일로 회전하지 않는 이유: 사적 대화 로그의 파일명이 늘어나면 git 제외 규칙이
     따라가지 못해 개인 대화가 저장소에 실릴 수 있다. 파일은 항상 하나로 유지한다.)
    """
    msgs = list(messages)
    while True:
        body = json.dumps({"messages": msgs}, ensure_ascii=False, indent=2)
        if len(body.encode("utf-8")) <= cap or len(msgs) <= 2:
            break
        msgs = msgs[len(msgs) // 4 + 1:]
    _atomic_write_text(path, body)


# ---------------------------------------------------------------- 상태·도메인
def scene_image_url(sc: dict) -> str | None:
    rel = (sc.get("assets", {}).get("selected_image") or "").strip()
    if not rel:
        raws = sc.get("assets", {}).get("raw_images", [])
        rel = raws[0] if raws else ""
    if rel and rel.startswith("images/") and (ROOT / rel).exists():
        return "/img/" + rel[len("images/"):]
    return None


def scene_print(sc: dict) -> dict | None:
    """장면 선택 이미지의 인화 규격 요약(없으면 None). 실물 인화 목표용."""
    sel = (sc.get("assets", {}).get("selected_image") or "").strip()
    if not sel:
        return None
    anchor = (sc.get("print", {}) or {}).get("crop_anchor", "center")
    size = print_preflight.image_size(ROOT / sel)
    if not size:
        return {"px": None, "printable": None, "max": None, "long_in": None,
                "crop_anchor": anchor}
    r = print_preflight.preflight_image(size[0], size[1], 300)
    return {"px": size, "printable": r["printable"], "max": r["max_size_at_target"],
            "long_in": r["max_long_in_at_target"], "crop_anchor": anchor}


def _load_json_safe(path: Path) -> dict | None:
    """손상/비-dict JSON 은 None — 파일 하나가 UI 전체(/api/state)를 죽이지 못하게 한다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def load_favorites() -> list[str]:
    """인화 후보 ★ 목록 — project/favorites.json. 형식이 깨져도 빈 목록으로 살아남는다."""
    d = _load_json_safe(FAVORITES) or {}
    ids = d.get("scene_ids")
    if not isinstance(ids, list):
        return []
    return [s for s in ids if isinstance(s, str) and SCENE_ID_RE.match(s)]


def save_favorites(ids: list[str]) -> None:
    _atomic_write_text(FAVORITES,
                       json.dumps({"scene_ids": ids}, ensure_ascii=False, indent=2) + "\n")


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
    storyline, chat = "", []
    if (STORY_DIR / "storyline.md").exists():
        storyline = (STORY_DIR / "storyline.md").read_text(encoding="utf-8")
    if (STORY_DIR / "chatlog.json").exists():
        try:
            chat = json.loads((STORY_DIR / "chatlog.json").read_text(encoding="utf-8")).get("messages", [])
        except Exception:
            chat = []
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
            "scenes": scenes, "storyline": storyline, "chat": chat}


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
    with adv.WRITE_LOCK:
        _write_messages(STORY_DIR / "chatlog.json",
                        messages + [{"role": "assistant", "content": reply}])
    return reply


def _require_scene(sid) -> Path:
    """장면 ID 형식 검증 + 존재 확인.

    형식 검증이 먼저인 이유: '../..' 같은 값이 scene_path 를 통해 장면 폴더 밖 파일에
    닿는 것을 원천 차단한다. 존재 확인은 adv.load 의 die()/SystemExit 가 요청 스레드를
    죽이는 것을 막는다.
    """
    if not isinstance(sid, str) or not SCENE_ID_RE.match(sid):
        raise RuntimeError(f"장면 ID 형식이 올바르지 않습니다(SCENE-001 형식): {sid!r}")
    path = adv.scene_path(sid)
    if not path.exists():
        raise RuntimeError(f"장면을 찾을 수 없습니다: {sid}")
    return path


def _missing_anchors(sc: dict, text: str) -> list[str]:
    """장면에 필요한 인물/장소 앵커 중 프롬프트에 빠진 원문 목록."""
    try:
        mf = json.loads((ROOT / "project" / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    chars = {c.get("character_id"): c.get("prompt_anchor", "") for c in mf.get("characters", [])}
    for cid in sc.get("characters", []):
        a = (chars.get(cid) or "").strip()
        if a and a.lower() not in text.lower():
            out.append(a)
    for l in mf.get("locations", []):
        if l.get("location_id") == sc.get("location_id"):
            a = (l.get("prompt_anchor") or "").strip()
            if a and a.lower() not in text.lower():
                out.append(a)
    return out


def set_scene_prompt(sid: str, text: str, fix_anchors: bool = False) -> dict:
    """이미지 프롬프트를 장면에 저장 → 상태 PROMPT + 자동 검사. (로컬 LLM 생성/수동 붙여넣기 공용)

    fix_anchors=True 면 그록 등 외부 AI 출력에 빠진 앵커 원문을 뒤에 이어붙여 A6 를 보장한다.
    """
    text = (text or "").strip()
    if not text:
        raise RuntimeError("이미지 프롬프트가 비어 있습니다.")
    path = _require_scene(sid)
    with adv.WRITE_LOCK:
        sc = adv.load(path)
        if sc.get("status") == "APPROVED":
            raise RuntimeError("APPROVED 장면은 프롬프트를 바꿀 수 없습니다. 먼저 revise 하세요.")
        if fix_anchors:
            miss = _missing_anchors(sc, text)
            if miss:
                text = text.rstrip(" .,") + ", " + ", ".join(miss)
        sc.setdefault("prompt", {})["grok_output"] = text
        sc["status"] = "PROMPT"
        adv.save(path, sc)
        code, out = adv.run_checker(sid)
    return {"status": "PROMPT", "checker_pass": code == 0,
            "fails": "\n".join(l for l in out.splitlines() if "FAIL" in l)}


def register_images(sid: str) -> dict:
    _require_scene(sid)
    with adv.WRITE_LOCK:
        path = adv.scene_path(sid)
        sc = adv.load(path)
        if sc.get("status") == "APPROVED":
            # 승인 잠금 장면은 재스캔이 selected/auto 를 훼손하지 못하게 한다(불변식 보호).
            raws = sc["assets"].get("raw_images", [])
            return {"count": len(raws), "auto": sc.get("review", {}).get("auto", "PASS"),
                    "fails": "", "locked": True,
                    "note": "APPROVED 장면은 재스캔하지 않습니다. 되돌리려면 revise 를 사용하세요."}
        folder = RAW_DIR / sid
        files = sorted(f for f in folder.glob("*") if f.suffix.lower() in IMAGE_EXTS) if folder.exists() else []
        sc["assets"]["raw_images"] = [f.relative_to(ROOT).as_posix() for f in files]
        sel = sc["assets"].get("selected_image", "")
        if sel and not (ROOT / sel).exists():
            sc["assets"]["selected_image"] = ""
        if files and sc.get("status") in ("SCENE_PLAN", "PROMPT"):
            sc["status"] = "IMAGE"
        adv.save(path, sc)
        code, out = adv.run_checker(sid)
        sc = adv.load(path)
        sc["review"]["auto"] = "PASS" if code == 0 else "FAIL"
        if code == 0 and sc.get("status") == "IMAGE":
            sc["status"] = "REVIEW_HUMAN"
        adv.save(path, sc)
    return {"count": len(files), "auto": sc["review"]["auto"],
            "fails": "\n".join(l for l in out.splitlines() if "FAIL" in l)}


def select_image(sid: str, rel: str) -> dict:
    _require_scene(sid)
    with adv.WRITE_LOCK:   # 검사~저장을 한 잠금 안에 둬 승인 직후의 교체(경쟁 상태)까지 막는다
        path = adv.scene_path(sid)
        if adv.load(path).get("status") == "APPROVED":
            # 승인 잠금 장면의 선택본 교체 금지 — 사람 승인 없이 다른 이미지가 완성본이 되면 안 된다.
            raise RuntimeError("APPROVED 장면은 선택 이미지를 바꿀 수 없습니다. 먼저 revise 하세요.")
        register_images(sid)
        sc = adv.load(path)
        if rel not in sc["assets"].get("raw_images", []):
            raise RuntimeError("해당 파일이 후보 목록에 없습니다. 폴더 스캔을 먼저 하세요.")
        sc["assets"]["selected_image"] = rel
        # 선택 반영을 auto=PASS 로 낙관적 기록 후 검사로 확정한다. (REVIEW_HUMAN 단계는
        # A7 이 auto=PASS 선행을 요구하므로, 먼저 PASS 로 두지 않으면 정상 선택도 A7 FAIL 로 막힌다.)
        sc["review"]["auto"] = "PASS"
        adv.save(path, sc)
        code, out = adv.run_checker(sid)
        if code != 0:
            sc = adv.load(path)
            sc["review"]["auto"] = "FAIL"
            adv.save(path, sc)
    return {"selected": rel, "auto_pass": code == 0,
            "fails": "\n".join(l for l in out.splitlines() if "FAIL" in l)}


# ---------------------------------------------------------------- POST 라우팅
# 각 핸들러는 요청 body(dict) 를 받아 응답 dict 를 반환하거나 RuntimeError 를 던진다.
def r_chat(b):
    return {"reply": do_chat(b.get("messages", []))}


def r_storyline(b):
    with adv.WRITE_LOCK:
        _atomic_write_text(STORY_DIR / "storyline.md", str(b.get("text", "")))
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
    return set_scene_prompt(b.get("scene_id"), b.get("text", ""), bool(b.get("fix_anchors")))


def r_preflight(b):
    _require_scene(b.get("scene_id"))
    sc = adv.load(adv.scene_path(b["scene_id"]))
    sel = (sc.get("assets", {}).get("selected_image") or "").strip()
    if not sel:
        raise RuntimeError("선택된 이미지가 없습니다. 먼저 이미지를 선택하세요.")
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
        raise RuntimeError(f"crop_anchor 는 {'/'.join(sorted(_CROP_ANCHORS))} 중 하나여야 합니다.")
    with adv.WRITE_LOCK:
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
    with adv.WRITE_LOCK:
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
    return register_images(b["scene_id"])


def r_select(b):
    return select_image(b["scene_id"], b["image"])


def r_approve(b):
    _require_scene(b.get("scene_id"))
    adv.do_approve(b["scene_id"])
    return {"status": "APPROVED"}


def r_check(b):
    code, out = adv.run_checker()
    return {"pass": code == 0, "output": out}


def r_lint(b):
    return scene_lint.lint_scenes()


_TIME_EN = {"밤": "night", "낮": "daytime", "아침": "morning", "저녁": "evening",
            "노을": "sunset", "새벽": "dawn", "오후": "afternoon"}


def visual_style() -> str:
    """화풍 — manifest.output.visual_style. 없으면 기존 기본 화풍을 그대로 쓴다."""
    mf = _load_json_safe(MANIFEST) or {}
    v = ((mf.get("output") or {}) if isinstance(mf.get("output"), dict) else {}).get("visual_style", "")
    return v.strip() if isinstance(v, str) and v.strip() else DEFAULT_STYLE


def compose_image_prompt(sc: dict) -> str:
    """장면 → 이미지 프롬프트 문자열. 앵커(인물/장소 원문)는 코드가 조립해 A6 를 보장하고,
    LLM 은 동작·구도 문장만 만든다."""
    mf = _load_json_safe(MANIFEST) or {}
    chars = {c.get("character_id"): c for c in mf.get("characters", [])}
    locs = {l.get("location_id"): l for l in mf.get("locations", [])}
    ask = ("아래 장면을 그림으로 그릴 때의 '동작과 구도'만 영어 한 문장(20단어 이내)으로 써라. "
           "인물 외모나 장소 묘사는 쓰지 마라. 설명 없이 그 문장만 출력하라.\n"
           f"목적: {sc.get('purpose', '')}\n동작: {sc.get('action_beat', '')}\n"
           f"감정: {sc.get('emotion', '')}\n시간: {sc.get('time', '')}")
    action = local_llm.chat([{"role": "user", "content": ask}], temperature=0.4, max_tokens=120)
    action = " ".join(action.strip().splitlines()).strip().strip('"')[:220]
    cam = sc.get("camera", {}) if isinstance(sc.get("camera"), dict) else {}
    parts = [visual_style() + ", portrait 2:3", f"{cam.get('shot', 'medium')} shot"]
    ids = [c for c in sc.get("characters", []) if c in chars]
    if ids:
        parts.append(chars[ids[0]].get("prompt_anchor", ""))
    parts.append(action)
    for cid in ids[1:]:
        parts.append("with " + chars[cid].get("prompt_anchor", ""))
    if sc.get("location_id") in locs:
        parts.append(locs[sc["location_id"]].get("prompt_anchor", ""))
    t = str(sc.get("time", "")).strip()
    if t:
        parts.append(_TIME_EN.get(t, t))
    return ", ".join(p.strip() for p in parts if p and p.strip())


def r_gen_prompt(b):
    """로컬 LLM 으로 장면 이미지 프롬프트 생성 (그록 대체) → 저장 + 자동 검사."""
    sid = b.get("scene_id")
    _require_scene(sid)
    sc = adv.load(adv.scene_path(sid))
    return set_scene_prompt(sid, compose_image_prompt(sc))


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
            raise RuntimeError(f"{sid} 이미지를 이미 생성 중입니다. 끝난 뒤 다시 시도하세요.")
        _GEN_JOBS[sid] = {"running": True, "message": "생성 준비 중…", "ts": time.time()}


def _gen_note(sid: str, message: str, running: bool = True) -> None:
    with _GEN_LOCK:
        _GEN_JOBS[sid] = {"running": running, "message": message, "ts": time.time()}


def _gen_run(sid: str, n: int) -> dict:
    """실제 생성 — 성공/실패 어느 쪽이든 in-flight 표시를 반드시 해제한다."""
    try:
        _gen_note(sid, "MakeFun 에 생성 요청 중… (1~3분)")
        files = makefun_client.generate_for_scene(sid, n=n)
        _gen_note(sid, f"{len(files)}장 수신 · 등록·검사 중…")
        reg = register_images(sid)
        reg["generated"] = [f.name for f in files]
        _gen_note(sid, f"완료 — {len(files)}장 생성 · 자동검사 {reg.get('auto', '')}", running=False)
        log.info("이미지 생성 완료 %s (%d장)", sid, len(files))
        return reg
    except Exception as exc:
        log.warning("이미지 생성 실패 %s: %s", sid, exc)
        _gen_note(sid, f"실패: {exc}", running=False)
        raise


def r_gen_image(b):
    """MakeFun AI 로 장면 이미지 생성 → images/raw/<scene>/ 저장 + 자동 등록·검사.

    기본은 백그라운드 실행 후 즉시 응답(폰 브라우저 타임아웃 방지) — 진행은 /api/gen-status.
    sync:true 면 예전처럼 끝날 때까지 기다렸다가 결과를 반환한다.
    """
    sid = b.get("scene_id")
    _require_scene(sid)
    sc = adv.load(adv.scene_path(sid))
    if sc.get("status") == "APPROVED":
        raise RuntimeError("APPROVED 장면입니다. 다시 생성하려면 먼저 revise 하세요.")
    n = max(1, min(int(b.get("n", 1) or 1), 4))
    _gen_claim(sid)
    if b.get("sync"):
        return _gen_run(sid, n)

    def _bg():
        try:
            _gen_run(sid, n)
        except Exception:
            pass   # 사유는 _gen_run 이 로그·진행 메시지에 남긴다(스레드는 조용히 종료)

    threading.Thread(target=_bg, daemon=True).start()
    return {"started": True, "running": True, "scene_id": sid,
            "message": "MakeFun 생성 중… (1~3분) 진행 상황은 자동으로 갱신됩니다.",
            "generated": [], "auto": "생성 중",
            "count": len(sc.get("assets", {}).get("raw_images", []))}


def r_gen_status(b):
    """생성 진행 조회 — {running, message}."""
    sid = b.get("scene_id")
    if not isinstance(sid, str) or not SCENE_ID_RE.match(sid):
        raise RuntimeError(f"장면 ID 형식이 올바르지 않습니다: {sid!r}")
    with _GEN_LOCK:
        job = dict(_GEN_JOBS.get(sid) or {})
    return {"running": bool(job.get("running")), "message": str(job.get("message", "")),
            "scene_id": sid}


def r_talk_status(b):
    return local_llm.status()


# ------------------------------------------------- 인물 대화 로그(사용자의 사적 자산)
# 원칙: 이 로그는 어떤 경로로도 "조용히" 줄어들지 않는다. 클라이언트가 보낸 목록으로
# 파일을 통째로 갈아엎지 않고 항상 저장본과 병합한다(명시적 reset:true 만 예외).
def _safe_cid(cid) -> str:
    """대화 로그 파일명에 쓸 안전한 캐릭터 ID(경로 탈출 차단). r_talk 저장 규칙과 동일."""
    return "".join(c for c in str(cid or "") if c.isalnum() or c in "-_") or "CHAR"


def _talk_file(cid) -> Path:
    return STORY_DIR / f"talk_{_safe_cid(cid)}.json"


def _resolve_talk_cid(cid) -> str:
    """대화 상대 ID — 요청값 > manifest.talk.character_id > 첫 캐릭터 (local_llm 과 같은 규칙)."""
    if isinstance(cid, str) and cid.strip():
        return cid.strip()
    mf = _load_json_safe(MANIFEST) or {}
    talk = mf.get("talk") if isinstance(mf.get("talk"), dict) else {}
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    return str((talk or {}).get("character_id")
               or (chars[0].get("character_id") if chars else "") or "")


def _load_talk(cid) -> list[dict]:
    """저장된 대화 로그 읽기 — {"messages":[...]} 형식. 없거나 깨져도 예외 없이 빈 목록."""
    d = _load_json_safe(_talk_file(cid)) or {}
    raw = d.get("messages")
    if not isinstance(raw, list):
        return []
    out = []
    for m in raw:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            continue
        item = {"role": m["role"], "content": str(m.get("content", "") or "")}
        ph = m.get("photos")
        if isinstance(ph, list):
            item["photos"] = [p for p in ph if isinstance(p, dict)]
        out.append(item)
    return out


def _msg_eq(a: dict, b: dict) -> bool:
    """같은 대사인지 — 사진 메타는 클라이언트가 떼고 보내므로 역할·본문만 비교한다."""
    return (a.get("role") == b.get("role")
            and str(a.get("content", "")) == str(b.get("content", "")))


def _merge_talk(saved: list, incoming: list) -> list:
    """저장본 + 클라이언트가 보낸 이력 → 잃는 것 없이 합친다.

    * 정상(이어서 대화): 저장본이 incoming 의 접두사 → 뒤에 붙은 새 대화만 추가.
    * 새 세션이 빈 화면에서 시작: 겹치는 부분이 없음 → 저장본 뒤에 이어붙인다(절대 잘라내지 않음).
    * 저장본이 더 길고 incoming 이 그 일부: 남는 저장본을 보존하고 새 발화만 뒤에 붙인다.
    사진 메타는 저장본 쪽을 유지한다(클라이언트는 텍스트만 되돌려 보내므로).
    """
    if not saved:
        return [dict(m) for m in incoming]
    if not incoming:
        return [dict(m) for m in saved]
    p = 0
    while p < len(saved) and p < len(incoming) and _msg_eq(saved[p], incoming[p]):
        p += 1
    if p == 0:   # 접두사가 전혀 겹치지 않으면 저장본의 꼬리와 겹치는지 본다(중복 방지)
        for k in range(min(len(saved), len(incoming)), 0, -1):
            if all(_msg_eq(saved[len(saved) - k + i], incoming[i]) for i in range(k)):
                p = k
                break
    return [dict(m) for m in saved] + [dict(m) for m in incoming[p:]]


def r_talk_history(b):
    """저장된 인물 대화 이력 → {messages, character_id}. 새 세션이 지난 대화를 이어받는 경로."""
    cid = _resolve_talk_cid(b.get("character_id"))
    return {"messages": _load_talk(cid), "character_id": cid}


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
    context = list(incoming) if reset else _merge_talk(_load_talk(cid), incoming)
    win = int(getattr(local_llm, "TALK_WINDOW", 16) or 16)   # 기억 요약이 덮는 창과 같은 크기
    window = [{"role": m["role"], "content": m["content"]} for m in context[-win:]]
    reply = local_llm.chat([{"role": "system", "content": sysmsg}] + window)

    last_user = next((m["content"] for m in reversed(context) if m["role"] == "user"), "")
    clean, photo_meta = local_llm.resolve_photos(reply, meta.get("album", {}), last_user)
    photos = [{"scene_id": p["scene_id"], "url": "/img/" + p["rel"][len("images/"):],
               "caption": p.get("caption", "")}
              for p in photo_meta if p["rel"].startswith("images/")]
    with adv.WRITE_LOCK:
        # 잠금 안에서 다시 읽어 병합한다 — 답장을 기다리는 동안 다른 기기가 남긴 대화도 보존.
        final = list(incoming) if reset else _merge_talk(_load_talk(cid), incoming)
        final.append({"role": "assistant", "content": clean, "photos": photos})
        _write_messages(_talk_file(cid), final)
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
    with adv.WRITE_LOCK:
        sid, order = _next_scene_slot()
        idx = int(re.sub(r"\D", "", sid) or 1)
        sc = vn_compose._build_scene(item, idx, char_ids, loc_ids, locs)
        sc["scene_id"], sc["scene_order"] = sid, order
        sc["status"] = "SCENE_PLAN"
        sc["prompt"]["grok_output"] = ""
        adv.SCENES.mkdir(parents=True, exist_ok=True)
        adv.save(adv.scene_path(sid), sc)
    log.info("대화 → 장면 생성 %s", sid)
    res = set_scene_prompt(sid, compose_image_prompt(sc))   # 프롬프트까지만(생성은 사용자 몫)
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
        raise RuntimeError("이미지 파일만 업로드할 수 있습니다 (png/jpg/jpeg/webp).")
    data = str(b.get("data_b64", ""))
    if data.startswith("data:") and "," in data:   # data URI 접두 제거
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        raise RuntimeError("이미지 데이터를 해석할 수 없습니다.")
    if not raw:
        raise RuntimeError("빈 이미지입니다.")
    if len(raw) > 30_000_000:
        raise RuntimeError("이미지가 너무 큽니다 (30MB 초과).")
    real = sniff_image(raw)
    if real is None:
        raise RuntimeError("이미지 파일이 아닙니다 (PNG/JPEG/WEBP/GIF/TIFF 시그니처 불일치).")
    if ext not in real:
        raise RuntimeError(f"파일 내용과 확장자가 다릅니다 (내용: {'/'.join(sorted(real))}, 이름: {ext}).")
    dest = RAW_DIR / sid
    dest.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in Path(name).stem if c.isalnum() or c in "-_") or "upload"
    target = dest / f"{safe}{ext}"
    n = 2
    while target.exists():
        target = dest / f"{safe}-{n}{ext}"
        n += 1
    target.write_bytes(raw)
    reg = register_images(sid)   # 저장 즉시 후보 등록·자동검사
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


POST_ROUTES = {
    "/api/chat": r_chat, "/api/storyline": r_storyline,
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
    "/api/gen-status": r_gen_status, "/api/favorite": r_favorite,
    "/api/talk-to-scene": r_talk_to_scene,
}


# ---------------------------------------------------------------- PIN 인증(LAN)
AUTH = {"pin": "", "tokens": [], "fails": 0, "until": 0.0}
AUTH_LOCK = threading.Lock()
COOKIE_NAME = "vn_studio"
AUTH_TTL = 12 * 3600
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


def _issue_token() -> str:
    tok = secrets.token_urlsafe(24)
    with AUTH_LOCK:
        AUTH["tokens"].append((tok, time.time() + AUTH_TTL))
        del AUTH["tokens"][:-20]   # 기기 20대분만 유지
    return tok


def _token_ok(tok: str) -> bool:
    if not tok:
        return False
    now = time.time()
    with AUTH_LOCK:
        AUTH["tokens"] = [(t, exp) for t, exp in AUTH["tokens"] if exp > now]
        return any(secrets.compare_digest(t, tok) for t, _ in AUTH["tokens"])


def check_pin(pin: str) -> str:
    """PIN 확인 → 토큰. 연속 실패는 잠시 잠근다(무차별 대입 방지)."""
    with AUTH_LOCK:
        if time.time() < AUTH["until"]:
            raise RuntimeError("입력 시도가 많습니다. 1분 뒤 다시 시도하세요.")
    ok = bool(AUTH["pin"]) and secrets.compare_digest(str(pin or ""), AUTH["pin"])
    if not ok:
        with AUTH_LOCK:
            AUTH["fails"] += 1
            if AUTH["fails"] >= 5:
                AUTH["fails"], AUTH["until"] = 0, time.time() + 60
        log.warning("PIN 인증 실패")
        raise RuntimeError("PIN 이 올바르지 않습니다.")
    with AUTH_LOCK:
        AUTH["fails"] = 0
    return _issue_token()


# ---------------------------------------------------------------- 정적 파일
IMG_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
             "webp": "image/webp", "tif": "image/tiff", "tiff": "image/tiff"}
DL_TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
            ".webmanifest": "application/manifest+json", ".js": "text/javascript; charset=utf-8",
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".tiff": "image/tiff", ".zip": "application/zip"}


def safe_path(base: Path, rel: str) -> Path | None:
    """base 아래로만 해석되는 경로. '..'·절대경로·숨김 항목은 거부(경로 탈출 차단)."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or p.startswith(".") or ":" in p for p in parts):
        return None
    base_r = base.resolve()
    target = (base_r / "/".join(parts)).resolve()
    return target if target.is_relative_to(base_r) else None


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
    timeout = 60  # Content-Length 불일치 등으로 rfile.read 가 영원히 막히지 않게 소켓 타임아웃

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
        return _token_ok(m.value if m else "")

    def _json(self, obj, code: int = 200, extra: list | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data: bytes, ctype: str, extra: list | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

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
                self._bytes(LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
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
            self._bytes(body, "text/html; charset=utf-8")
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
            self.end_headers()
            return
        self._bytes(data, ctype, [("ETag", tag),
                                 ("Cache-Control", f"private, max-age={IMG_MAX_AGE}")])

    def _serve_download(self, rel: str, qs: dict) -> None:
        target = safe_path(OUTPUT_DIR, rel)
        if target is None or not target.is_file():
            self._json({"error": "not found"}, 404)
            return
        data = target.read_bytes()
        ctype = DL_TYPES.get(target.suffix.lower(), "application/octet-stream")
        quoted = urllib.parse.quote(target.name)
        disp = "inline" if (qs.get("inline") or [""])[0] else "attachment"
        self._bytes(data, ctype, [("Content-Disposition", f"{disp}; filename*=UTF-8''{quoted}"),
                                  ("Cache-Control", "private, no-store")])

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
                raise RuntimeError("요청 본문이 너무 큽니다(10MB 초과).")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise RuntimeError("요청 본문이 JSON 객체가 아닙니다.")
            if self.path == "/api/auth":     # 인증 자체는 잠금 대상에서 제외
                tok = check_pin(str(body.get("pin", "")))
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


def _resolve_pin(args) -> str:
    """LAN 모드면 기본으로 PIN 을 켠다(--no-pin 으로 해제). 값 미지정 시 6자리 생성."""
    if args.no_pin:
        return ""
    if args.pin is None and not args.lan:
        return ""
    given = (args.pin or "").strip()
    if given:
        if not re.fullmatch(r"\d{4,6}", given):
            raise SystemExit("오류: --pin 은 4~6자리 숫자여야 합니다.")
        return given
    return f"{secrets.randbelow(1_000_000):06d}"


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
    AUTH["pin"] = _resolve_pin(args)
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
    if AUTH["pin"]:
        # 콘솔을 놓치거나(창 숨김·출력 리다이렉트) 스크롤로 지나쳐도 폰 접속을 못 하게 되면 안 되므로
        # 실행 중에만 유효한 PIN 을 조회 가능한 자리에 남긴다. logs/ 는 git 제외 대상.
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            (LOG_DIR / "lan_pin.txt").write_text(
                f"{AUTH['pin']}\n(이번 실행에만 유효한 접속 PIN — 서버를 끄면 무효)\n", encoding="utf-8")
            print("  PIN 을 놓쳤다면: logs/lan_pin.txt")
        except OSError:
            pass
    sys.stdout.flush()   # 출력이 리다이렉트돼도 PIN·주소가 즉시 보이도록
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    log.info("서버 종료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
