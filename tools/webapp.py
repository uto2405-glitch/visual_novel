#!/usr/bin/env python3
"""웹 스튜디오 서버 — 5단계 워크플로우의 백엔드. 프론트는 tools/studio.html.

  1) 스토리 탭   : Grok 과 대화하며 스토리라인 작성 (xai_client)
  2) 장면 탭     : 스토리라인 → VN 텍스트 + 이미지 프롬프트 구성 (vn_compose)
  3) (외부·수동) : 이미지 생성 AI 에 프롬프트 붙여넣어 이미지 생성
  4) 장면 탭     : images/raw/<scene_id>/ 폴더 투입 → 스캔 → 선택 → 승인 도장
  5) 뷰어 탭     : 비주얼 노벨 감상

사용법:
  python tools/webapp.py [--port 8765] [--no-browser]

보안:
  * API 키는 환경변수 XAI_API_KEY 로만. 서버 안에서만 쓰이고 브라우저로 전달되지 않는다.
  * 127.0.0.1 전용 바인딩 + Host 헤더 검증(DNS 리바인딩 방어) + /img 경로 탈출 차단.
  * 프론트는 서버 데이터를 innerHTML 로 넣지 않는다(studio.html 안전 규약).
  * 쓰기 요청은 advance_scene.WRITE_LOCK 으로 직렬화된다.

의존성: 표준 라이브러리만. Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advance_scene as adv  # noqa: E402
import make_grok_input  # noqa: E402
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
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
CHAT_WINDOW = 24  # API 로 보내는 최근 대화 수 (전체 로그는 디스크에 보존)
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


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
    size = print_preflight.image_size(ROOT / sel)
    if not size:
        return {"px": None, "printable": None, "max": None, "long_in": None}
    r = print_preflight.preflight_image(size[0], size[1], 300)
    return {"px": size, "printable": r["printable"], "max": r["max_size_at_target"],
            "long_in": r["max_long_in_at_target"]}


def _load_json_safe(path: Path) -> dict | None:
    """손상/비-dict JSON 은 None — 파일 하나가 UI 전체(/api/state)를 죽이지 못하게 한다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


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
    return {"manifest": bool(mf), "title": (mf or {}).get("title", ""),
            "key_set": xai_client.key_set(), "model": model,
            "characters": [{"id": c.get("character_id"), "name": c.get("name", "")}
                           for c in (mf or {}).get("characters", [])],
            "scenes": scenes, "storyline": storyline, "chat": chat}


def do_chat(messages: list[dict]) -> str:
    sys_msg = {"role": "system",
               "content": "너는 비주얼 노벨/웹툰 스토리 기획 파트너다. 한국어로 간결하고 구체적으로 답한다."}
    window = messages[-CHAT_WINDOW:]  # 비용·컨텍스트 관리: 최근 대화만 전송
    reply = xai_client.chat([sys_msg] + window)
    with adv.WRITE_LOCK:
        STORY_DIR.mkdir(parents=True, exist_ok=True)
        (STORY_DIR / "chatlog.json").write_text(
            json.dumps({"messages": messages + [{"role": "assistant", "content": reply}]},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    return reply


def _require_scene(sid) -> Path:
    """존재하는 장면만 통과 — adv.load 의 die()/SystemExit 가 요청 스레드를 죽이는 것을 막는다."""
    if not isinstance(sid, str) or not sid or not adv.scene_path(sid).exists():
        raise RuntimeError(f"장면을 찾을 수 없습니다: {sid!r}")
    return adv.scene_path(sid)


def set_scene_prompt(sid: str, text: str) -> dict:
    """수동 모드: grok.com 에서 받은 이미지 프롬프트 출력을 장면에 저장 → 상태 PROMPT + 자동 검사."""
    text = (text or "").strip()
    if not text:
        raise RuntimeError("붙여넣은 Grok 출력이 비어 있습니다.")
    path = _require_scene(sid)
    with adv.WRITE_LOCK:
        sc = adv.load(path)
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
    register_images(sid)
    with adv.WRITE_LOCK:
        path = adv.scene_path(sid)
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
        STORY_DIR.mkdir(parents=True, exist_ok=True)
        (STORY_DIR / "storyline.md").write_text(b.get("text", ""), encoding="utf-8")
    return {"ok": True}


def r_compose(b):
    return vn_compose.compose_scenes(int(b.get("count", 10)), bool(b.get("force")))


def r_compose_input(b):
    return {"instruction": vn_compose.build_compose_instruction(int(b.get("count", 10)))}


def r_compose_manual(b):
    exp = int(b["count"]) if str(b.get("count", "")).strip() else None
    return vn_compose.compose_from_json(b.get("text", ""), bool(b.get("force")), expected=exp)


def r_grok_input(b):
    _require_scene(b.get("scene_id"))
    return {"text": make_grok_input.build_input(b["scene_id"])}


def r_set_prompt(b):
    return set_scene_prompt(b.get("scene_id"), b.get("text", ""))


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


def r_export(b):
    # 서버는 Pillow 없이도 뜨도록 지연 임포트
    try:
        import print_export
    except Exception:
        raise RuntimeError("인화 내보내기는 Pillow 가 필요합니다:  python -m pip install Pillow")
    inc_all = bool(b.get("all"))
    if b.get("contact_only"):
        made = print_export.contact_sheet(print_export.collect(None, inc_all))
        return {"contact": bool(made), "count": 0}
    try:
        short_in, long_in = print_export.parse_size(str(b.get("size", "5x7")))
    except SystemExit as e:
        raise RuntimeError(str(e))
    summ = print_export.export_batch(
        short_in, long_in, int(b.get("dpi", 300)), float(b.get("bleed", 0)),
        str(b.get("anchor", "center")), inc_all, None, bool(b.get("skip_upscale")))
    if b.get("contact"):
        print_export.contact_sheet(print_export.collect(None, inc_all))
    return {"count": summ["count"], "dir": summ["dir"], "upscaled": summ["upscaled"],
            "skipped": summ["skipped"], "missing": summ["missing"]}


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


POST_ROUTES = {
    "/api/chat": r_chat, "/api/storyline": r_storyline,
    "/api/compose": r_compose, "/api/compose-input": r_compose_input,
    "/api/compose-manual": r_compose_manual, "/api/grok-input": r_grok_input,
    "/api/set-prompt": r_set_prompt, "/api/preflight": r_preflight, "/api/export": r_export,
    "/api/register-images": r_register, "/api/select": r_select,
    "/api/approve": r_approve, "/api/check": r_check, "/api/lint": r_lint,
}


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in ALLOWED_HOSTS

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            self._json({"error": "forbidden host"}, 403)
            return
        try:
            self._get()
        except (Exception, SystemExit) as exc:  # 어떤 실패도 응답 없는 절단 대신 JSON 오류로
            try:
                self._json({"error": f"서버 처리 실패: {exc}"}, 500)
            except OSError:
                pass

    def _get(self):
        if self.path == "/" or self.path.startswith("/?"):
            try:
                body = STUDIO_HTML.read_bytes()
            except OSError:
                self._json({"error": "tools/studio.html 이 없습니다. 패키지를 다시 확인하세요."}, 500)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            self._json(state())
        elif self.path.startswith("/img/"):
            rel = urllib.parse.unquote(self.path[len("/img/"):])
            target = (ROOT / "images" / rel).resolve()
            images_root = (ROOT / "images").resolve()
            if not target.is_relative_to(images_root) or not target.is_file():
                self._json({"error": "not found"}, 404)
                return
            ext = target.suffix.lower().lstrip(".")
            ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                     "webp": "image/webp", "tif": "image/tiff",
                     "tiff": "image/tiff"}.get(ext, "application/octet-stream")
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._host_ok():
            self._json({"error": "forbidden host"}, 403)
            return
        handler = POST_ROUTES.get(self.path)
        if handler is None:
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 10_000_000:
                raise RuntimeError("요청 본문이 너무 큽니다(10MB 초과).")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise RuntimeError("요청 본문이 JSON 객체가 아닙니다.")
            self._json(handler(body))
        except SystemExit as exc:
            # CLI 용 die()/sys.exit 가 핸들러 안에서 터져도 응답 없는 절단 대신 400 으로
            self._json({"error": f"도구가 중단됨(코드 {exc.code}) — 장면/매니페스트 파일 상태를 확인하세요."}, 400)
        except Exception as exc:  # 실패 사유를 그대로 UI 로 (검사 실패·잘못된 입력 등)
            self._json({"error": str(exc)}, 400)


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 웹툰 웹 스튜디오")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    key = "설정됨" if xai_client.key_set() else "미설정 (스토리/장면구성 탭 사용 불가)"
    print(f"웹 스튜디오 실행: {url}")
    print(f"XAI_API_KEY: {key}  |  종료: Ctrl+C")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
