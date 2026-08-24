#!/usr/bin/env python3
"""패키지 자가진단 — 임시 샌드박스에 복사본을 만들어 전체 파이프라인을 검증한다.

사용법:
  python tools/selftest.py

사용자의 project/ 와 images/ 데이터는 절대 건드리지 않는다.
Pillow 등 외부 패키지 불필요 (테스트용 PNG 를 표준 라이브러리로 직접 생성).
수정 후에는 반드시 이 스크립트로 회귀를 확인한다.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
PY = sys.executable
_results: list[tuple[str, bool]] = []


def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, cond))
    mark = "PASS" if cond else "FAIL"
    print(f"{mark}  {name}" + ("" if cond or not detail else f"\n      └ {detail}"))


def write_png(path: Path, w: int, h: int, rgb=(210, 180, 150)) -> None:
    """Pillow 없이 유효한 RGB PNG 생성 (검사기 A3 의 크기 판독 대상)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * w
    idat = zlib.compress(row * h, 6)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def edit_json(path: Path, fn) -> None:
    d = json.loads(path.read_text(encoding="utf-8"))
    fn(d)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    print(f"자가진단 시작 — 원본: {SRC}")
    base_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    with tempfile.TemporaryDirectory(prefix="webtoon-selftest-") as td:
        box = Path(td) / "repo"
        shutil.copytree(SRC, box, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".git", "grok_inputs", "grok_outputs"))
        # 샌드박스의 작업 영역을 빈 상태로 초기화 (사용자 데이터가 복사돼 왔어도 원본은 불변)
        shutil.rmtree(box / "project", ignore_errors=True)
        (box / "project" / "scenes").mkdir(parents=True)
        shutil.rmtree(box / "images" / "raw", ignore_errors=True)
        (box / "images" / "raw").mkdir(parents=True)

        def run(*args: str, no_key: bool = False, env: dict | None = None) -> tuple[int, str]:
            env = dict(env if env is not None else base_env)
            if no_key:
                env.pop("XAI_API_KEY", None)
            p = subprocess.run([PY, *args], cwd=box, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", env=env)
            return p.returncode, p.stdout + p.stderr

        adv = "tools/advance_scene.py"
        chk = "tools/check_protocol.py"

        # T1 — 초기 상태는 안내와 함께 RED
        rc, out = run(chk)
        check("T1 초기 상태 RED(exit 1) + 시작 안내", rc == 1 and "manifest" in out, out[:200])

        # T2 — 데모 투입 시 PASS (A8 포함)
        shutil.copy(box / "examples" / "manifest.json", box / "project" / "manifest.json")
        shutil.copy(box / "examples" / "scenes" / "SCENE-001.json",
                    box / "project" / "scenes" / "SCENE-001.json")
        rc, out = run(chk)
        check("T2 데모 PASS + A8 키스캔 PASS", rc == 0 and "[A8] PASS" in out, out[:400])

        # T3 — new → 계획 채움 → set-prompt --file (앵커 포함) → PROMPT
        rc, out = run(adv, "new")
        s2 = box / "project" / "scenes" / "SCENE-002.json"
        check("T3a new 로 SCENE-002 생성(order 2)", rc == 0 and s2.exists(), out[:200])

        def plan(d):
            d.update(purpose="셀프테스트", action_beat="정면 응시", emotion="긴장",
                     visual_style="셀 셰이딩")
            d["dialogue"][0]["text"] = "테스트 대사"
        edit_json(s2, plan)
        mf = json.loads((box / "project" / "manifest.json").read_text(encoding="utf-8"))
        anchors = " ".join([mf["characters"][0]["prompt_anchor"],
                            mf["locations"][0]["prompt_anchor"]])
        gp = box / "grok_out.txt"
        gp.write_text(f"SCENE_PROMPT: medium shot, {anchors}, cel shading\n"
                      "NEGATIVE_PROMPT: text\nCONTINUITY_NOTES: -\n"
                      "DIALOGUE_PLACEMENT: bottom\n", encoding="utf-8")
        rc, out = run(adv, "set-prompt", "SCENE-002", "--file", str(gp))
        st = json.loads(s2.read_text(encoding="utf-8"))
        check("T3b set-prompt → 상태 PROMPT + 앵커검사 통과",
              rc == 0 and st["status"] == "PROMPT" and "FAIL" not in out, out[:300])

        # T4 — 후보 2장 등록 → 자동검사 PASS → REVIEW_HUMAN 자동 전이
        a = box / "cand_a.png"
        b = box / "cand_b.png"
        write_png(a, 1400, 1000)
        write_png(b, 1400, 1000, (150, 190, 230))
        rc, out = run(adv, "add-images", "SCENE-002", str(a), str(b))
        st = json.loads(s2.read_text(encoding="utf-8"))
        check("T4 add-images → auto PASS → REVIEW_HUMAN",
              rc == 0 and st["status"] == "REVIEW_HUMAN"
              and st["review"]["auto"] == "PASS" and len(st["assets"]["raw_images"]) == 2,
              out[:300])

        # T5 — select + approve → APPROVED 불변식
        rc1, _ = run(adv, "select", "SCENE-002", "2")
        rc2, out = run(adv, "approve", "SCENE-002")
        st = json.loads(s2.read_text(encoding="utf-8"))
        check("T5 select→approve → APPROVED + human PASS",
              rc1 == 0 and rc2 == 0 and st["status"] == "APPROVED"
              and st["review"]["human"] == "PASS", out[:300])

        # T6 — 저해상도 선택은 approve 가 거부하고 롤백
        small = box / "small.png"
        write_png(small, 500, 400)
        run(adv, "revise", "SCENE-002", "IMAGE", "--note", "저해상도 테스트")
        run(adv, "add-images", "SCENE-002", str(small))
        run(adv, "select", "SCENE-002", str(small.name))
        rc, out = run(adv, "approve", "SCENE-002")
        st = json.loads(s2.read_text(encoding="utf-8"))
        check("T6 저해상도 approve 거부 + 롤백(상태 비APPROVED)",
              rc != 0 and st["status"] != "APPROVED", out[:300])
        run(adv, "select", "SCENE-002", "2")
        rc, _ = run(adv, "approve", "SCENE-002")
        check("T6b 정상 후보 재선택 후 approve 성공", rc == 0)

        # T7 — 다른 장면 고장이 --scene 단위검사에 전염되지 않음
        s1 = box / "project" / "scenes" / "SCENE-001.json"
        edit_json(s1, lambda d: d["dialogue"].append(
            {"speaker_id": "CHAR-999", "text": "x", "placement": "top"}))
        rc_all, _ = run(chk)
        rc_one, _ = run(chk, "--scene", "SCENE-002")
        check("T7 전체 FAIL 이어도 --scene 격리 PASS", rc_all == 1 and rc_one == 0)
        shutil.copy(box / "examples" / "scenes" / "SCENE-001.json", s1)  # 복구

        # T8 — A8 키 유출 스캔 (가짜 키는 런타임 조립 — 이 파일 자체가 걸리지 않도록)
        leak = box / "project" / "leak.md"
        fake_key = "xai-" + "abcdefghij0123456789" + "KLMN"
        leak.write_text(f"memo: {fake_key}", encoding="utf-8")
        rc, out = run(chk)
        check("T8 심은 키 패턴을 A8 이 검출", rc == 1 and "[A8] FAIL" in out, out[:300])
        leak.unlink()

        # T9 — grok_api: 키 없음 안내 / --dry-run
        rc, out = run("tools/grok_api.py", "SCENE-002", no_key=True)
        check("T9a 키 없음 → 안내 후 종료(수동 모드 유도)",
              rc == 2 and "XAI_API_KEY" in out, out[:300])
        rc, out = run("tools/grok_api.py", "SCENE-001", "--dry-run", no_key=True)
        check("T9b --dry-run 은 키 없이 입력 조립만", rc == 0 and "dry-run" in out, out[:200])

        # T10 — 잘못된 인자는 크래시 대신 사용법 안내
        rc, out = run(adv, "revise", "SCENE-002", "WRONG_STATE")
        check("T10 잘못된 인자 → argparse 사용법 안내(traceback 아님)",
              rc == 2 and "Traceback" not in out and "usage" in out.lower(), out[:200])

        # ================= 웹 스튜디오 (모의 xAI 서버로 검증) =================
        import http.server
        import socket
        import time
        import urllib.error
        import urllib.request as ur

        anchor_c = "17-year-old Korean girl, short black hair, brown eyes, blue hairpin, summer school uniform"
        anchor_l = "empty Korean high school classroom at sunset, warm orange light"
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

        class MockXAI(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                last = (body.get("messages") or [{}])[-1].get("content", "")
                content = scenes_json if "SCENES_JSON_ONLY" in last else "모의 응답: 좋은 방향이에요."
                raw = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        import threading
        mock = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockXAI)
        threading.Thread(target=mock.serve_forever, daemon=True).start()
        edit_json(box / "project" / "manifest.json", lambda d: d["orchestrator"]["api"].update(
            {"base_url": f"http://127.0.0.1:{mock.server_address[1]}/v1", "model": "mock-model"}))

        with socket.socket() as s0:
            s0.bind(("127.0.0.1", 0))
            web_port = s0.getsockname()[1]
        wenv = dict(base_env)
        wenv["XAI_API_KEY"] = "dummy"
        wenv["NO_PROXY"] = wenv["no_proxy"] = "127.0.0.1,localhost"
        web = subprocess.Popen([PY, "tools/webapp.py", "--port", str(web_port), "--no-browser"],
                               cwd=box, env=wenv,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        opener = ur.build_opener(ur.ProxyHandler({}))

        def wapi(path: str, payload=None):
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            req = ur.Request(f"http://127.0.0.1:{web_port}{path}", data=data,
                             headers={"Content-Type": "application/json"} if data else {})
            with opener.open(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode("utf-8"))

        try:
            up, d = False, {}
            for _ in range(60):
                try:
                    _, d = wapi("/api/state")
                    up = True
                    break
                except Exception:
                    time.sleep(0.2)
            check("T11 웹 스튜디오 기동 + 상태 API(키는 불리언만 노출)",
                  up and d.get("key_set") is True and d.get("model") == "mock-model")

            st, d = wapi("/api/chat", {"messages": [{"role": "user", "content": "안녕"}]})
            check("T12 스토리 채팅(모의 xAI 경유) + 로그 저장",
                  st == 200 and "모의 응답" in d.get("reply", "")
                  and (box / "project" / "story" / "chatlog.json").exists())

            wapi("/api/storyline", {"text": "짝사랑 고백 이야기"})
            check("T13 스토리라인 저장",
                  (box / "project" / "story" / "storyline.md").read_text(encoding="utf-8").strip()
                  == "짝사랑 고백 이야기")

            st, d = wapi("/api/compose", {"count": 2, "force": True})
            check("T14 스토리라인 → 장면 2개 자동 구성 + 검사 통과",
                  st == 200 and len(d.get("created", [])) == 2 and d.get("checker_pass") is True
                  and (box / "project" / "scenes" / "SCENE-002.json").exists(),
                  json.dumps(d, ensure_ascii=False)[:300])

            folder = box / "images" / "raw" / "SCENE-001"
            folder.mkdir(parents=True, exist_ok=True)
            write_png(folder / "web_a.png", 1400, 1000)
            wapi("/api/register-images", {"scene_id": "SCENE-001"})
            wapi("/api/select", {"scene_id": "SCENE-001", "image": "images/raw/SCENE-001/web_a.png"})
            st3, _ = wapi("/api/approve", {"scene_id": "SCENE-001"})
            stt = json.loads((box / "project" / "scenes" / "SCENE-001.json").read_text(encoding="utf-8"))
            check("T15 웹 경로 등록→선택→승인 → APPROVED",
                  st3 == 200 and stt["status"] == "APPROVED"
                  and stt["review"]["human"] == "PASS")

            try:
                with opener.open(ur.Request(f"http://127.0.0.1:{web_port}/img/../CLAUDE.md"),
                                 timeout=10) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            check("T16 이미지 경로 탈출(/img/../) 차단", code == 404)

            # T17 — 주입 방어: 적대적 데이터가 서버를 왕복해도 원문 그대로(JSON 데이터로만) 유지되고,
            #        프론트 안전 규약(서버 데이터의 innerHTML 삽입 금지)이 코드 수준에서 지켜지는지
            hostile = "</textarea><img src=x onerror=alert(1)>"
            edit_json(box / "project" / "scenes" / "SCENE-002.json",
                      lambda d: d.update(purpose=hostile))
            _, d = wapi("/api/state")
            sc2 = next(x for x in d["scenes"] if x["scene_id"] == "SCENE-002")
            html_src = (box / "tools" / "studio.html").read_text(encoding="utf-8")
            inner_uses = html_src.count("innerHTML")
            check("T17 적대적 문자열 왕복 보존 + 프론트 innerHTML 미사용(주입 구조적 차단)",
                  sc2["purpose"] == hostile and inner_uses == 0,
                  f"innerHTML {inner_uses}회")

            # T18 — 동시 쓰기: 같은 장면에 병렬 요청을 퍼부어도 파일이 깨지지 않는다
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(lambda _:
                            wapi("/api/register-images", {"scene_id": "SCENE-001"}), range(8)))
            parsed = json.loads((box / "project" / "scenes" / "SCENE-001.json")
                                .read_text(encoding="utf-8"))
            check("T18 병렬 8회 register 후에도 장면 JSON 무결(WRITE_LOCK)",
                  parsed.get("scene_id") == "SCENE-001"
                  and parsed["assets"]["raw_images"] == ["images/raw/SCENE-001/web_a.png"])

            # T19 — Host 헤더 검증(DNS 리바인딩 방어)
            try:
                req = ur.Request(f"http://127.0.0.1:{web_port}/api/state",
                                 headers={"Host": "evil.example.com"})
                with opener.open(req, timeout=10) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            check("T19 외부 Host 헤더 차단(403)", code == 403)

            # T20 — compose 를 CLI 로도 동일하게 실행 가능(웹·CLI 단일 구현 공유)
            cenv = dict(base_env)
            cenv["XAI_API_KEY"] = "dummy"
            cenv["NO_PROXY"] = cenv["no_proxy"] = "127.0.0.1,localhost"
            rc, out = run("tools/vn_compose.py", "2", "--force", env=cenv)
            check("T20 vn_compose CLI 로 장면 재구성(웹과 동일 구현)",
                  rc == 0 and (box / "project" / "scenes" / "SCENE-002.json").exists(), out[:300])

            # ===== 수동 모드 (API 크레딧 없이 grok.com 복붙) =====
            # T21 — compose-input: grok.com 붙여넣기용 지시문(앵커·출력마커 포함, API 불필요)
            st, d = wapi("/api/compose-input", {"count": 3})
            check("T21 수동 compose-input 지시문 생성(앵커·마커 포함)",
                  st == 200 and "SCENES_JSON_ONLY" in d.get("instruction", "")
                  and anchor_c in d.get("instruction", ""),
                  d.get("instruction", "")[:120])

            # T22 — compose-manual: 사람이 붙여넣은 JSON(코드펜스 포함) → 장면 생성 + 검사 통과
            manual_items = [
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
            fenced = "```json\n" + json.dumps(manual_items, ensure_ascii=False) + "\n```"
            st, d = wapi("/api/compose-manual", {"text": fenced, "force": True})
            check("T22 수동 compose-manual JSON 붙여넣기 → 장면 2개 + 검사 통과",
                  st == 200 and len(d.get("created", [])) == 2 and d.get("checker_pass") is True,
                  json.dumps(d, ensure_ascii=False)[:300])

            # T23 — grok-input(앵커 포함) → set-prompt 로 상태 PROMPT + 앵커검사 통과
            st, d = wapi("/api/grok-input", {"scene_id": "SCENE-001"})
            gi_ok = st == 200 and anchor_c in d.get("text", "")
            ptext = f"SCENE_PROMPT: medium shot, {anchor_c}, {anchor_l}, cel shading\nNEGATIVE_PROMPT: text"
            st2, d2 = wapi("/api/set-prompt", {"scene_id": "SCENE-001", "text": ptext})
            sc1 = json.loads((box / "project" / "scenes" / "SCENE-001.json").read_text(encoding="utf-8"))
            check("T23 수동 grok-input + set-prompt → PROMPT + 앵커검사 통과",
                  gi_ok and st2 == 200 and d2.get("checker_pass") is True
                  and sc1["status"] == "PROMPT" and sc1["prompt"]["grok_output"] == ptext)

            # T24 — 빈 프롬프트 set-prompt 는 400 으로 거부(서버는 계속 살아있음)
            code24 = None
            try:
                wapi("/api/set-prompt", {"scene_id": "SCENE-001", "text": "   "})
            except urllib.error.HTTPError as e:
                code24 = e.code
            check("T24 빈 프롬프트 set-prompt → 400 거부", code24 == 400)

            # T25 — 없는 scene_id 로 register → 400 + 서버 스레드 생존(SystemExit 미전파)
            code25 = None
            try:
                wapi("/api/register-images", {"scene_id": "SCENE-404"})
            except urllib.error.HTTPError as e:
                code25 = e.code
            alive = False
            try:
                sA, _ = wapi("/api/state")
                alive = sA == 200
            except Exception:
                alive = False
            check("T25 없는 scene_id register → 400 + 서버 생존", code25 == 400 and alive)

            # ===== 감사(적대적 재현)로 확정된 결함들의 회귀 잠금 =====
            # T26 — 웹 register→select 해피패스에서 review.auto 가 PASS 로 유지(오염 회귀)
            f2 = box / "images" / "raw" / "SCENE-002"
            f2.mkdir(parents=True, exist_ok=True)
            write_png(f2 / "s2.png", 1400, 1000)
            wapi("/api/register-images", {"scene_id": "SCENE-002"})
            _, dsel = wapi("/api/select", {"scene_id": "SCENE-002",
                                           "image": "images/raw/SCENE-002/s2.png"})
            sc2 = json.loads((box / "project" / "scenes" / "SCENE-002.json").read_text(encoding="utf-8"))
            check("T26 웹 select 후 auto=PASS 유지(register 오염 회귀)",
                  dsel.get("auto_pass") is True and sc2["review"]["auto"] == "PASS",
                  json.dumps(dsel, ensure_ascii=False)[:200])

            # T27 — APPROVED 장면 재스캔은 잠금(선택/auto 훼손 금지, 불변식 보호)
            wapi("/api/approve", {"scene_id": "SCENE-002"})
            _, dreg = wapi("/api/register-images", {"scene_id": "SCENE-002"})
            sc2b = json.loads((box / "project" / "scenes" / "SCENE-002.json").read_text(encoding="utf-8"))
            check("T27 APPROVED 재스캔 잠금(불변식 보호)",
                  dreg.get("locked") is True and sc2b["status"] == "APPROVED"
                  and sc2b["review"]["auto"] == "PASS" and bool(sc2b["assets"]["selected_image"]))

            # T28 — 비표준 scene_id 로 new → order 무결성 보호 위해 거부(traceback 아님)
            rc, out = run(adv, "new", "abc")
            check("T28 비표준 scene_id(new abc) 거부",
                  rc == 2 and "Traceback" not in out
                  and not (box / "project" / "scenes" / "abc.json").exists(), out[:200])

            # T29 — revise IMAGE 는 selected 를 비우고, 즉시 approve 는 거부(오래된 이미지 재승인 차단)
            run(adv, "revise", "SCENE-002", "IMAGE", "--note", "regen")
            sc29 = json.loads((box / "project" / "scenes" / "SCENE-002.json").read_text(encoding="utf-8"))
            rc, out = run(adv, "approve", "SCENE-002")
            sc29b = json.loads((box / "project" / "scenes" / "SCENE-002.json").read_text(encoding="utf-8"))
            check("T29 revise IMAGE→즉시 approve 거부(오래된 이미지 재승인 차단)",
                  sc29["assets"]["selected_image"] == "" and rc == 1
                  and sc29b["status"] != "APPROVED" and "Traceback" not in out, out[:200])

            # T30 — add-images 중간 파일 누락 시 아무것도 복사 안 함(고아 파일 방지·원자성)
            run(adv, "new")  # SCENE-003
            gimg = box / "g1.png"
            write_png(gimg, 1400, 1000)
            rc, out = run(adv, "add-images", "SCENE-003", str(gimg), str(box / "NOPE.png"))
            s3dir = box / "images" / "raw" / "SCENE-003"
            orphans = list(s3dir.glob("*")) if s3dir.exists() else []
            check("T30 add-images 부분실패 시 고아 파일 없음(원자성)",
                  rc == 2 and "Traceback" not in out and len(orphans) == 0, out[:200])

            # T31 — select 위첨자('²'): isdigit 은 True 지만 int 불가 → 크래시 대신 안내
            run(adv, "add-images", "SCENE-003", str(gimg))
            rc, out = run(adv, "select", "SCENE-003", "²")
            check("T31 select 위첨자 인자 → 크래시 대신 안내",
                  rc == 2 and "Traceback" not in out, out[:200])

            # T32 — 씬 파일 최상위가 dict 가 아닌 JSON(배열)이어도 status 가 크래시하지 않음
            (box / "project" / "scenes" / "SCENE-003.json").write_text(
                '[{"scene_id":"SCENE-003"}]', encoding="utf-8")
            rc, out = run(adv, "status")
            check("T32 씬 파일이 JSON 배열이어도 크래시 대신 안내",
                  rc == 2 and "Traceback" not in out, out[:200])

            # ===== xai_client 회귀 (인프로세스 로컬 서버로 실측) =====
            import importlib.util
            key_backup = os.environ.get("XAI_API_KEY")
            os.environ["XAI_API_KEY"] = "sk-SECRET-LEAK-TEST-XYZ"
            os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
            spec = importlib.util.spec_from_file_location("xai_box", str(box / "tools" / "xai_client.py"))
            xc = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(xc)

            # T33 — cross-host 302 리다이렉트로 Authorization(키)이 외부 호스트로 유출되지 않는다(critical)
            attacker = {"auth": "NOT-CALLED"}

            class _Atk(http.server.BaseHTTPRequestHandler):
                def log_message(self, *a): pass
                def do_POST(self):
                    attacker["auth"] = self.headers.get("Authorization")
                    raw = json.dumps({"choices": [{"message": {"content": "leaked"}}]}).encode()
                    self.send_response(200); self.send_header("Content-Length", str(len(raw)))
                    self.end_headers(); self.wfile.write(raw)

            atk_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Atk)
            threading.Thread(target=atk_srv.serve_forever, daemon=True).start()
            atk_port = atk_srv.server_address[1]

            class _Redir(http.server.BaseHTTPRequestHandler):
                def log_message(self, *a): pass
                def do_POST(self):
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{atk_port}/v1/chat/completions")
                    self.end_headers()

            rd_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Redir)
            threading.Thread(target=rd_srv.serve_forever, daemon=True).start()
            rd_port = rd_srv.server_address[1]
            edit_json(box / "project" / "manifest.json", lambda d: d["orchestrator"]["api"].update(
                {"base_url": f"http://127.0.0.1:{rd_port}/v1", "model": "m"}))
            blocked = False
            try:
                xc.chat([{"role": "user", "content": "hi"}])
            except RuntimeError:
                blocked = True
            except Exception:
                blocked = False
            check("T33 xai cross-host 리다이렉트 키 유출 차단(critical)",
                  blocked and attacker["auth"] in (None, "NOT-CALLED"),
                  f"blocked={blocked} attacker_auth={attacker['auth']!r}")

            # T34 — 200 이지만 content=null / 비-JSON 본문 → 안내(RuntimeError), 크래시 아님
            weird = {"mode": "null"}

            class _Weird(http.server.BaseHTTPRequestHandler):
                def log_message(self, *a): pass
                def do_POST(self):
                    if weird["mode"] == "null":
                        raw = json.dumps({"choices": [{"message": {"content": None}}]}).encode()
                        ct = "application/json"
                    else:
                        raw = b"<html>gateway error</html>"; ct = "text/html"
                    self.send_response(200); self.send_header("Content-Type", ct)
                    self.send_header("Content-Length", str(len(raw))); self.end_headers()
                    self.wfile.write(raw)

            wd_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Weird)
            threading.Thread(target=wd_srv.serve_forever, daemon=True).start()
            wd_port = wd_srv.server_address[1]
            edit_json(box / "project" / "manifest.json", lambda d: d["orchestrator"]["api"].update(
                {"base_url": f"http://127.0.0.1:{wd_port}/v1", "model": "m"}))

            def _expect_runtime():
                try:
                    xc.chat([{"role": "user", "content": "x"}]); return False
                except RuntimeError:
                    return True
                except Exception:
                    return False

            r_null = _expect_runtime()
            weird["mode"] = "html"
            r_html = _expect_runtime()
            check("T34 xai content=null·비JSON 200 → 안내(크래시 아님)", r_null and r_html)

            atk_srv.shutdown(); rd_srv.shutdown(); wd_srv.shutdown()
            if key_backup is None:
                os.environ.pop("XAI_API_KEY", None)
            else:
                os.environ["XAI_API_KEY"] = key_backup

            # T35 — 인화 프리플라이트: 규격별 DPI 판정 정확도 + CLI 무크래시
            spec_pf = importlib.util.spec_from_file_location("pf_box", str(box / "tools" / "print_preflight.py"))
            pfm = importlib.util.module_from_spec(spec_pf)
            spec_pf.loader.exec_module(pfm)
            hi = pfm.preflight_image(1200, 1800, 300)   # 4×6 을 정확히 300DPI 로 채움
            lo = pfm.preflight_image(1000, 1400, 300)   # 엽서도 미달
            mx = pfm.preflight_image(2500, 3200, 300)   # 8×10 통과 → 최대 규격은 면적 최대인 8×10
            rc, out = run("tools/print_preflight.py", "--all")
            check("T35 인화 프리플라이트 규격 판정 + 최대규격(면적) + CLI 무크래시",
                  hi["printable"] is True and hi["rows"][0]["dpi"] == 300
                  and lo["printable"] is False and mx["max_size_at_target"] == "8×10"
                  and rc == 0 and "인화 프리플라이트" in out and "Traceback" not in out, out[:200])

            # T36 — 인화 마스터 익스포트: 규격 픽셀·DPI 메타·업스케일 플래그 (Pillow 없으면 스킵)
            try:
                from PIL import Image as _PImg
                _pil_ok = True
            except Exception:
                _pil_ok = False
            if _pil_ok:
                spec_pe = importlib.util.spec_from_file_location("pe_box", str(box / "tools" / "print_export.py"))
                pem = importlib.util.module_from_spec(spec_pe)
                spec_pe.loader.exec_module(pem)
                pem.OUT = box / "_pe_out"
                big = box / "pe_big.png"; write_png(big, 1600, 2400)     # 세로, 5×7 비업스케일
                sml = box / "pe_small.png"; write_png(sml, 1000, 1500)   # 업스케일 필요
                land = box / "pe_land.png"; write_png(land, 3000, 2000)  # 가로 → 규격 회전
                sb = pem.export_one("SCENE-BIG", big, 5.0, 7.0, 300, 0.0, "center")
                ss = pem.export_one("SCENE-SM", sml, 5.0, 7.0, 300, 0.0, "center")
                sl = pem.export_one("SCENE-LAND", land, 5.0, 7.0, 300, 0.0, "center")
                with _PImg.open(box / sb["tiff"]) as _im:
                    meta_ok = _im.size == (1500, 2100) and _im.info.get("dpi") == (300, 300)
                # 규격 검증 거부 + scene_id 경로탈출 차단
                bad_size = False
                try:
                    pem.parse_size("-4x6")
                except SystemExit:
                    bad_size = True
                pem.export_one("../../evil", big, 5.0, 7.0, 300, 0.0, "center")
                safe_ok = (box / "_pe_out" / "5x7" / "evil.tiff").exists() and not (box / "evil.tiff").exists()
                check("T36 인화 마스터(규격·DPI·업스케일·가로회전·eff_dpi·규격검증·경로차단)",
                      sb["out_px"] == [1500, 2100] and sb["upscaled"] is False
                      and ss["upscaled"] is True and meta_ok
                      and sl["out_px"] == [2100, 1500]                 # 가로: 규격 회전
                      and sb["eff_dpi_src"] == 320                     # min(1600/5,2400/7)=320
                      and bad_size and safe_ok)
            else:
                check("T36 인화 마스터 익스포트(Pillow 미설치 → 스킵)", True)
        finally:
            web.terminate()
            mock.shutdown()
            mock.server_close()

    fails = sum(1 for _, ok in _results if not ok)
    print("-" * 56)
    if fails:
        print(f"자가진단 실패: {fails}/{len(_results)} 건 — 위 FAIL 항목을 확인하세요.")
        return 1
    print(f"자가진단 전체 통과 ({len(_results)}건). 파이프라인 정상입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
