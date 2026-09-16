#!/usr/bin/env python3
"""ComfyUI(로컬 GPU) 이미지 클라이언트 — 무료 기본 경로. makefun_client 와 같은 공개 계약.

API: POST /prompt {"prompt": <API 그래프>, "client_id"} → {"prompt_id"} (400 이면 node_errors)
     GET  /history/<id>      → 진행 중 {} · 끝나면 {id: {status, outputs}}
     GET  /view?filename=&subfolder=&type=output → 이미지 바이트
     GET  /object_info/CheckpointLoaderSimple → 체크포인트 목록 · GET /system_stats → 살아 있음
     POST /interrupt · POST /queue {"delete": [id]} → 시간 초과 정리
토큰 없음(로컬). 주소는 환경변수 COMFYUI_URL > manifest image_generator.comfyui.api.base_url > 기본값.

사용:
  python tools/comfyui_client.py SCENE-001 [--n 2] [--seed 1] [--long-edge 1536] [--no-register]
  python tools/comfyui_client.py --prompt "..." --out scratch/test.png [--seed 1]
  python tools/comfyui_client.py --all-pending [--limit 5] [--dry-run]
  python tools/comfyui_client.py --check [--online]

크기: SDXL 은 1MP 근처(2:3 → 832×1248)에서 가장 잘 그린다. output.min_long_edge_px 가 그보다
크면 2단 hires(기본 렌더 → LatentUpscale → 낮은 denoise 재샘플)로 키운다 — 큰 캔버스를 한 번에
그리면 인물이 둘로 갈라진다. hires 는 1차 캔버스의 2배(HIRES_MAX_SCALE)까지만 키운다 — 그 이상은
잘리고 경고한다(3600px 을 한 번에 재샘플하면 12GB VRAM 이 OOM 으로 죽는다). 긴 변 상한은 MakeFun 과
같은 image_generator.max_long_edge_px 다.

일관성: 레퍼런스 이미지(IP-Adapter 류)는 아직 이 경로에서 쓰지 않는다. 컷 간 얼굴은 프롬프트
앵커와 **시드**로 잡는다(같은 시드·같은 체크포인트면 같은 그림이 다시 나온다 — 재현 가능).
MakeFun 쪽 레퍼런스가 매니페스트에 있으면 "쓰지 않는다"는 경고를 결과에 싣는다(조용히 무시 금지).

장면 파일의 status·assets·prompt 는 여기서 쓰지 않는다 — 등록은 gen_jobs/scene_ops, 생성기 기록은
scene_ops.record_external_generator 를 부른다(지연 import — 이 파일만 복제된 환경에서도 렌더는 된다).
makefun_client 는 import 하지 않는다(두 엔진은 서로를 모르고, 고르는 것은 image_gen 의 일이다).
"""
from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import logging
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:          # 이 파일만 적재돼도 '옆에 있는' vn_core·gen_common 을 쓴다
    sys.path.insert(0, str(_HERE))

import gen_common                                              # noqa: E402
import vn_core                                                 # noqa: E402
from vn_core import (IMAGE_EXTS, VNError, atomic_write_bytes, host_port,  # noqa: E402
                     is_scene_id, iter_scenes, load_json, load_json_safe, selected_of)

ROOT = vn_core.ROOT
MANIFEST = vn_core.MANIFEST        # 테스트가 갈아끼우므로 함수는 호출 시점에 읽는다
SCENES_DIR = vn_core.SCENES
RAW_DIR = vn_core.IMAGES_RAW
USAGE_LOG = vn_core.LOGS / "comfyui_usage.jsonl"

GenResult = gen_common.GenResult
META_NAME = gen_common.META_NAME
write_gen_meta = gen_common.write_gen_meta
_now = gen_common.now_iso

ENGINE = "comfyui"
LABEL = "ComfyUI"
TOKEN_ENV = ""                     # 로컬 — 토큰이 없다(image_gen 이 "토큰 필요 없음" 판정에 쓴다)
ENV_URL = "COMFYUI_URL"            # 비밀값이 아닌 주소 — LOCAL_LLM_URL 과 같은 우선순위 규칙
DEFAULT_BASE = "http://127.0.0.1:8188"
POLL_SEC = 1.5
DEFAULT_TIMEOUT_SEC = 600
DL_CAP = 60 * 1024 * 1024
FILE_PREFIX = "cf"                 # 저장 파일 cf_<promptid6>_<n>.png (MakeFun 은 mf_)
SAVE_PREFIX = "vn_studio"          # ComfyUI output/ 아래 하위 폴더 — 우리가 만든 것을 알아보게

# 크기 규약은 MakeFun 과 같은 값을 본다(공용 상한 image_generator.max_long_edge_px).
DEFAULT_LONG_EDGE = 1024
SIZE_MIN_PX = 512
SIZE_MAX_PX = 2048
SIZE_HARD_MAX_PX = 4096

# 매니페스트 image_generator.comfyui 가 비워 둔 항목의 기본값. 체크포인트 프리셋(PRESETS)이
# 그 위에, 매니페스트 명시값이 맨 위에 놓인다(사람이 적은 값이 항상 이긴다).
DEFAULTS = {
    "steps": 30, "cfg": 4.0, "sampler": "dpmpp_2m", "scheduler": "karras", "clip_skip": 1,
    "negative_prompt": ("text, letters, speech bubbles, watermark, signature, lowres, "
                        "bad anatomy, bad hands, extra fingers, missing fingers, blurry, "
                        "jpeg artifacts"),
    "base_long_edge_px": 1248, "hires_denoise": 0.4, "hires_steps": 16,
    "timeout_sec": DEFAULT_TIMEOUT_SEC, "prompt_prefix": "", "negative_prefix": "",
}
# Illustrious 계열(waiIllustrious 등)은 배포자가 권장하는 조합이 따로 있다 — 기본 SDXL 설정으로
# 돌리면 색이 탁하고 손이 무너진다. 이름으로 알아보고 **매니페스트가 비워 둔 항목만** 채운다.
PRESETS = (
    (("illustrious", "noobai", "wai"),
     {"sampler": "euler_ancestral", "scheduler": "normal", "cfg": 6.0, "clip_skip": 2,
      "prompt_prefix": "masterpiece,best quality,amazing quality,",
      "negative_prefix": "bad quality,worst quality,worst detail,sketch,censor,"}),
)
# hires 확대는 1차 캔버스의 이 배수까지 — 1248px 기준 2496px(1664x2496 ≈ 4MP). 그 이상(3600px = 8.6MP 를
# 한 번에 재샘플)은 12GB 급 VRAM 에서 2차 KSampler 가 OOM 으로 죽고, 맞더라도 0.4 denoise 로는 디테일이
# 뭉개진다. 더 큰 목표는 base_long_edge_px 를 올리거나(느려짐) 승인 뒤 MakeFun 업스케일(유료)로 간다.
HIRES_MAX_SCALE = 2.0
# KSampler 의 seed 는 0 ~ 2**64-1 부호 없는 정수다. 넘는 값은 제출(POST /prompt)까지 간 뒤에야
# 거절되므로(그래프를 다 만들고, 큐에 넣고, 400) 그래프를 만들 때 여기서 먼저 잡는다.
SEED_MAX = 2 ** 64 - 1
# negative_prompt 표기: ""(또는 키 없음) = 기본 부정 문구 · false 또는 아래 단어 = 끔(프리셋 접두어만 남는다).
NEG_OFF_WORDS = ("none", "off")
_INT_KEYS = ("steps", "clip_skip", "hires_steps", "timeout_sec", "base_long_edge_px")
_FLOAT_KEYS = ("cfg", "hires_denoise")
_RANGES = {"steps": (1, 150), "clip_skip": (1, 12), "hires_steps": (1, 150),
           "timeout_sec": (30, 7200), "base_long_edge_px": (SIZE_MIN_PX, SIZE_HARD_MAX_PX),
           "cfg": (0.0, 30.0), "hires_denoise": (0.0, 1.0)}

CLIENT_ID = uuid.uuid4().hex       # 프로세스당 하나 — ComfyUI 가 같은 클라이언트의 작업으로 묶는다
_CKPT_CACHE: dict = {"ts": 0.0, "names": []}
_CKPT_TTL = 60.0

log = logging.getLogger("vn.gen")  # webapp.setup_logging 이 같은 채널을 logs/webapp.log 에 물린다
log.addHandler(logging.NullHandler())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


# 로컬 주소로 가는 요청이 시스템 프록시를 타면 연결이 조용히 죽는다 — 프록시를 쓰지 않는다.
_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def _say(msg: str, quiet: bool = False) -> None:
    if quiet:
        return
    try:
        print(msg, flush=True)
    except Exception:
        pass


# --- 설정 -------------------------------------------------------------------

def _top() -> dict:
    """manifest image_generator 최상위 블록(공용 키: engine·max_long_edge_px·provider)."""
    cfg = load_json_safe(MANIFEST, {}).get("image_generator", {})
    return cfg if isinstance(cfg, dict) else {}


def _cfg() -> dict:
    """image_generator.comfyui 블록 — 없으면 빈 dict(전부 기본값으로 돈다)."""
    sub = _top().get("comfyui")
    return sub if isinstance(sub, dict) else {}


def base_url() -> str:
    """환경변수 COMFYUI_URL > manifest comfyui.api.base_url > 기본값. http(s) 만 허용."""
    env = os.environ.get(ENV_URL, "").strip()
    u = env or str((_cfg().get("api", {}) or {}).get("base_url", "") or DEFAULT_BASE)
    u = u.strip().rstrip("/")
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise VNError(f"ComfyUI base_url 형식이 올바르지 않습니다(http://호스트:포트): {u[:80]}")
    return u


def preset(ckpt: str) -> dict:
    """체크포인트 이름으로 알아본 권장 설정(없으면 빈 dict). 매니페스트 명시값이 항상 이긴다."""
    low = str(ckpt or "").lower()
    for keys, over in PRESETS:
        if any(k in low for k in keys):
            return dict(over)
    return {}


def _coerce(key: str, value):
    """매니페스트 값의 형·범위를 맞춘다 — 틀리면 None(=그 항목은 아래 단계 값으로)."""
    try:
        if key in _INT_KEYS:
            v = int(value)
        elif key in _FLOAT_KEYS:
            v = float(value)
        else:
            v = str(value).strip()
            return v or None
    except (TypeError, ValueError):
        return None
    lo, hi = _RANGES.get(key, (None, None))
    if lo is not None and not (lo <= v <= hi):
        log.warning("comfyui.%s=%r 는 허용 범위 %s~%s 밖 — 기본값을 씁니다", key, value, lo, hi)
        return None
    return v


def negative_off(value) -> bool:
    """매니페스트 negative_prompt 가 '끔'인가 — false / "none" / "off". ""(빈 값)은 기본 문구를 뜻한다.

    템플릿은 checkpoint 처럼 ""(= 기본값) 로 배포된다 — 빈 문자열이 '끔'이면 배포본 전부가 글자·말풍선
    억제 문구 없이 렌더돼 MakeFun 경로(NEGATIVE_PHRASES)와 결과가 달라진다.
    """
    return value is False or (isinstance(value, str) and value.strip().lower() in NEG_OFF_WORDS)


def settings(ckpt: str = "") -> dict:
    """실제로 쓸 샘플링 설정 — DEFAULTS ← 체크포인트 프리셋 ← 매니페스트 명시값(빈 값·불리언은 '기본')."""
    out = dict(DEFAULTS)
    out.update(preset(ckpt))
    cfg = _cfg()
    for key in DEFAULTS:
        val = cfg.get(key)
        if val is None or val == "" or isinstance(val, bool):
            continue
        v = _coerce(key, val)
        if v is not None:
            out[key] = v
    if negative_off(cfg.get("negative_prompt")):
        out["negative_prompt"] = ""          # 끔 — 프리셋 접두어(negative_prefix)만 남는다
    return out


# --- HTTP -------------------------------------------------------------------

def display_url() -> str:
    """화면·로그용 주소 — scheme://host:port 만(user:pw@ 같은 userinfo 는 뺀다)."""
    u = base_url()
    return f"{urllib.parse.urlsplit(u).scheme}://{host_port(u)}"


def _fail_connect(exc) -> VNError:
    try:
        where = display_url()
    except VNError:
        where = "(주소 오류)"
    return VNError(f"ComfyUI({where})에 연결할 수 없습니다 — ComfyUI 가 켜져 있는지, "
                   f"주소(COMFYUI_URL 또는 manifest comfyui.api.base_url)가 맞는지 확인하세요. ({exc})")


def _http(method: str, path: str, body=None, timeout: int = 30, cap: int = 4 * 1024 * 1024) -> bytes:
    req = urllib.request.Request(
        base_url() + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json", "User-Agent": "vn-studio/1.0"},
        method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            data = r.read(cap + 1)
    except urllib.error.HTTPError as e:
        detail = ""
        with contextlib.suppress(Exception):
            detail = e.read().decode("utf-8", "replace")
        if e.code == 400 and path == "/prompt":
            raise VNError(_explain_400(detail))
        raise VNError(f"ComfyUI HTTP {e.code} ({method} {path}): {detail[:200]}")
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        # 연결 거부·시간 초과·DNS(URLError/OSError) + **HTTP 가 아닌 응답**(HTTPException).
        # 그 포트에 ComfyUI 가 아닌 것이 앉아 있으면(다른 앱·프록시·TLS 포트) 응답 첫 줄이
        # 상태줄이 아니라 BadStatusLine 이 나고, 그것은 OSError 가 아니라 CLI 로 traceback 이
        # 그대로 샜다. 사용자가 할 일은 같다 — 주소를 확인하는 것이라 같은 안내로 모은다.
        raise _fail_connect(getattr(e, "reason", None) or f"{type(e).__name__}: {e}")
    if len(data) > cap:
        raise VNError(f"ComfyUI 응답이 너무 큽니다({method} {path}, {cap // 1_000_000}MB 초과).")
    return data


def _json(method: str, path: str, body=None, timeout: int = 30):
    raw = _http(method, path, body, timeout)
    if not raw.strip():
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise VNError(f"ComfyUI 응답이 JSON 이 아닙니다({method} {path}).")


def _explain_400(detail: str) -> str:
    """POST /prompt 400 — 어느 노드가 왜 거절됐는지 사람이 읽을 문장으로.

    가장 흔한 원인은 체크포인트 이름 오타·미설치("value not in list")라 노드별 메시지가 핵심이다.
    """
    try:
        d = json.loads(detail)
    except ValueError:
        return f"ComfyUI 가 그래프를 거절했습니다(400): {detail[:200]}"
    bits: list[str] = []
    err = d.get("error") if isinstance(d, dict) else None
    if isinstance(err, dict) and err.get("message"):
        bits.append(str(err.get("message")))
    nodes = d.get("node_errors") if isinstance(d, dict) else None
    for nid, info in (nodes.items() if isinstance(nodes, dict) else []):
        ctype = info.get("class_type", "?") if isinstance(info, dict) else "?"
        msgs = []
        for e in (info.get("errors", []) if isinstance(info, dict) else []):
            if isinstance(e, dict):
                m = str(e.get("message", "")).strip()
                ex = e.get("details")
                msgs.append(m + (f" ({str(ex)[:120]})" if ex else ""))
        bits.append(f"노드 {nid}[{ctype}]: " + ("; ".join(msgs) or "오류"))
    return "ComfyUI 가 그래프를 거절했습니다 — " + (" / ".join(bits) if bits else detail[:200])


# --- 체크포인트 · 크기 ---------------------------------------------------------

def checkpoints(refresh: bool = False) -> list[str]:
    """ComfyUI 에 설치된 체크포인트 이름 목록(60초 캐시 — 상태 조회마다 두드리지 않게)."""
    now = time.monotonic()
    if not refresh and _CKPT_CACHE["names"] and now - _CKPT_CACHE["ts"] < _CKPT_TTL:
        return list(_CKPT_CACHE["names"])
    d = _json("GET", "/object_info/CheckpointLoaderSimple", timeout=10)
    try:
        names = d["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except (KeyError, IndexError, TypeError):
        raise VNError("ComfyUI 체크포인트 목록을 읽지 못했습니다(object_info 형식이 다릅니다).")
    names = [str(n) for n in (names if isinstance(names, list) else []) if n]
    _CKPT_CACHE.update(ts=now, names=list(names))
    return names


def configured_checkpoint() -> str:
    """매니페스트가 지정한 체크포인트("" = 지정 없음 → ComfyUI 의 첫 항목을 쓴다)."""
    return str(_cfg().get("checkpoint", "") or "").strip()


def checkpoint() -> str:
    """실제로 쓸 체크포인트. 지정이 없으면 ComfyUI 의 첫 항목(네트워크 1회)."""
    name = configured_checkpoint()
    if name:
        return name
    names = checkpoints()
    if not names:
        raise VNError("ComfyUI 에 체크포인트가 하나도 없습니다 — models/checkpoints/ 에 .safetensors 를 넣으세요.")
    return names[0]


def _cap_px() -> int:
    """긴 변 상한 — MakeFun 과 같은 공용 키 image_generator.max_long_edge_px(기본 2048)."""
    try:
        v = int(_top().get("max_long_edge_px", SIZE_MAX_PX) or SIZE_MAX_PX)
    except (TypeError, ValueError):
        v = SIZE_MAX_PX
    return max(SIZE_MIN_PX, min(v, SIZE_HARD_MAX_PX))


def _align8(px: int, cap: int) -> int:
    """8의 배수 정렬 — 올림하되 상한을 넘지 않는다(상한이 8의 배수가 아니면 내려서 자른다).

    상한 2250 은 2248 이 된다 — 그래서 '상한을 올리라'는 권고는 8의 배수여야 실행 가능하다
    (size_warnings 가 gen_common.align_up 으로 올려 말한다).
    """
    px = max(SIZE_MIN_PX, min(int(px), cap))
    return min((px + 7) // 8 * 8, cap // 8 * 8)


def _dims(long_px: int, w: int, h: int) -> tuple[int, int]:
    if h >= w:
        return max(8, (long_px * w // h) // 8 * 8), long_px
    return long_px, max(8, (long_px * h // w) // 8 * 8)


def size_plan(long_edge: int | None = None) -> dict:
    """요청 크기와 실제 렌더 계획을 함께 돌려준다(MakeFun size_plan 과 같은 키 + base/hires).

    최종 긴 변 = max(요청, base_long_edge_px) 를 상한(max_long_edge_px)으로 자른 값. SDXL 은
    기본 캔버스(1MP 근처)보다 작게 그리면 품질이 떨어지므로 요청이 그보다 작아도 기본 크기로
    그린다(min_long_edge_px 는 '최소' 요구라 A3 에 유리하다). 기본보다 크면 hires 2단 — 단, 1차 캔버스의
    HIRES_MAX_SCALE 배(hires_cap)까지만이고 그 위는 잘린다(capped·hires_capped 가 참, size_warnings 가 말한다).
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
    cap = _cap_px()
    base_long = _align8(settings(configured_checkpoint())["base_long_edge_px"], cap)
    hires_cap = _align8(base_long * HIRES_MAX_SCALE, cap)      # hires 로 갈 수 있는 긴 변 상한
    long_px = _align8(max(int(want), base_long), cap)
    hires_capped = long_px > hires_cap
    if hires_capped:
        long_px = hires_cap
    hires = long_px > base_long
    width, height = _dims(long_px, w, h)
    bw, bh = _dims(base_long, w, h) if hires else (width, height)
    return {"width": width, "height": height, "long": long_px, "want": int(want),
            "cap": cap, "capped": long_px < int(want), "source": src,
            "cap_is_default": "max_long_edge_px" not in _top(),
            "base_width": bw, "base_height": bh, "hires": hires,
            "hires_cap": hires_cap, "hires_capped": hires_capped}


def size_warnings(plan: dict | None = None, long_edge: int | None = None) -> list[str]:
    """요청이 상한(공용 max_long_edge_px 또는 hires 배수)에 깎였을 때의 경고. 없으면 빈 목록.

    과금은 없지만 검사기 A3 가 FAIL 한다 — 어느 상한에 걸렸는지에 따라 올릴 값이 다르다.
    """
    plan = plan or size_plan(long_edge)
    if not plan.get("capped"):
        return []
    a3 = ("" if plan.get("source") == "--long-edge" else
          f" 지금 생성하면 검사기 A3(긴 변 ≥ {plan['want']}px)가 FAIL 합니다.")
    head = f"요청 {plan['want']}px({plan.get('source', '')}) → 실제 {plan['long']}px — "
    if plan.get("hires_capped"):
        base_long = max(int(plan.get("base_width", 0)), int(plan.get("base_height", 0)))
        return [head + f"hires 확대는 1차 캔버스 {base_long}px 의 {HIRES_MAX_SCALE:g}배({plan['hires_cap']}px)"
                f"까지입니다(그 이상은 VRAM 부족·디테일 뭉개짐). 더 크게는 manifest comfyui.base_long_edge_px 를 "
                f"올리거나(느려짐) 승인 뒤 MakeFun 업스케일(유료)을 쓰세요.{a3}"]
    # 권고값은 8의 배수로 올린다 — 상한은 8의 배수로 **내려서** 자르므로(cap 2250 → 2248)
    # 요청값을 그대로 권하면 "이미 그 값인데 올리라"가 되고 고쳐도 A3 가 계속 FAIL 한다.
    need = gen_common.align_up(plan["want"])
    return [head + f"상한 {plan['cap']}px 에 깎였습니다. 매니페스트 image_generator.max_long_edge_px 를 "
            f"{need} 이상(8의 배수)으로 올리세요.{a3}"]


def size_recipe(long_px: int) -> dict:
    """긴 변 long_px 를 이 엔진으로 실제로 뽑으려면 매니페스트에서 **무엇을 얼마로** 바꿔야 하는가.

    인화 도구(print_preflight·print_export)와 doctor 가 "더 크게 생성하세요" 라고 말할 때,
    지금까지는 **어느 값을 얼마로** 올려야 하는지를 부르는 쪽이 각자 추측해서 적었다. 그 추측이
    두 군데서 틀렸다:
      * 공용 상한만 올리면 된다고 적었지만 ComfyUI 에는 hires 2배 상한이 하나 더 있다
        (1248 기본 캔버스로는 2496px 이 천장이라 8×10(3600px)은 **상한을 올려도 안 나온다**).
      * 8의 배수 절삭을 잊고 요청값 그대로 권했다(2250 → 실제 2248 → A3 계속 FAIL).
    상한 지식은 이 파일 하나에 있으므로 조치 목록도 여기서 만든다 — 부르는 쪽은 옮겨 적기만 한다.

    돌려주는 dict:
      want        목표 긴 변(px)
      reachable   **지금 설정 그대로** 그 픽셀이 나오는가(= edits 가 비었는가)
      edits       [(매니페스트 경로, 넣을 값)] — 위에서부터 그대로 적으면 된다(빈 목록이면 조치 불필요)
      hires_note  기본 캔버스를 올려야 할 때의 이유(없으면 "")
      feasible    조치를 다 해도 하드 상한(4096) 안에 들어오는가
    """
    want = max(SIZE_MIN_PX, int(long_px))
    plan = size_plan(want)                      # source="--long-edge" — A3 문구가 섞이지 않는다
    edits: list[tuple[str, int]] = []
    out = load_json_safe(MANIFEST, {}).get("output", {})
    try:
        cur_min = int((out or {}).get("min_long_edge_px", DEFAULT_LONG_EDGE) or DEFAULT_LONG_EDGE)
    except (TypeError, ValueError):
        cur_min = DEFAULT_LONG_EDGE
    if cur_min < want:                          # 요청 크기이자 검사기 A3 의 기준
        edits.append(("output.min_long_edge_px", want))
    if _cap_px() // 8 * 8 < want:               # 상한은 8의 배수로 **내려서** 자른다
        edits.append(("image_generator.max_long_edge_px", gen_common.align_up(want)))
    base_long = max(int(plan["base_width"]), int(plan["base_height"]))
    hires_note = ""
    if base_long * HIRES_MAX_SCALE < want:      # 상한을 올려도 hires 가 못 따라간다
        need_base = gen_common.align_up(-(-want // int(HIRES_MAX_SCALE)))
        edits.append(("image_generator.comfyui.base_long_edge_px", need_base))
        # 천장은 '공용 상한에 깎이기 전' 값으로 말한다 — 상한 상향은 위에 따로 적혀 있고,
        # 깎인 값(2048)을 "1248 의 2배" 라고 부르면 산수가 안 맞아 신뢰를 잃는다.
        hires_note = (f"hires 는 1차 캔버스 {base_long}px 의 {HIRES_MAX_SCALE:g}배"
                      f"({int(base_long * HIRES_MAX_SCALE)}px)까지입니다 — 1차 캔버스를 {need_base}px 로 "
                      f"올려야 {want}px 에 닿습니다(렌더가 느려지고 12GB VRAM 에서는 OOM 위험, "
                      "SDXL 은 1MP 근처를 벗어날수록 인물이 갈라집니다).")
    return {"want": want, "reachable": not edits, "edits": edits, "hires_note": hires_note,
            "feasible": want <= SIZE_HARD_MAX_PX, "engine": "comfyui"}


# --- 프롬프트 · 그래프 ---------------------------------------------------------

def _with_prefix(text: str, prefix: str) -> str:
    """접두 문구를 한 번만 붙인다(이미 있으면 그대로 — 반복 호출해도 같은 결과)."""
    text = (text or "").strip()
    prefix = (prefix or "").strip()
    if not prefix or text.lower().startswith(prefix.lower().rstrip(",")):
        return text
    if not text:                          # 본문이 없으면(부정 끔) 접두어만 — 끝 쉼표는 남기지 않는다
        return prefix.rstrip(",")
    return f"{prefix} {text}" if prefix.endswith(",") else f"{prefix}, {text}"


def negative_text(s: dict, enabled: bool = True) -> str:
    return _with_prefix(s.get("negative_prompt", ""), s.get("negative_prefix", "")) if enabled else ""


# ---------------------------------------------------------------- 그림체 사전 설정
#
# 그림체를 바꾸는 진짜 레버는 **체크포인트**다. 같은 모델에 "photorealistic" 을 적어 봐야
# 애니 모델은 반실사 그림체까지만 가고, 실사 모델에 "anime" 를 적으면 어색한 중간이 된다.
# 그래서 프리셋은 체크포인트와 문구를 **한 쌍**으로 묶는다.
#
# 체크포인트는 파일 이름을 직접 박지 않고 **조각으로 찾는다.** 사람이 모델을 새 판으로
# 바꾸면(v170 → v180) 이름이 달라지는데, 그때마다 코드를 고쳐야 하면 프리셋이 조용히
# 죽는다. 못 찾으면 매니페스트가 지정한 것으로 떨어지고 **화면에 그렇게 말한다** —
# 조용히 다른 그림체로 굽는 것이 제일 나쁘다.
#
# 전환 비용: 체크포인트가 바뀌면 그 첫 장은 모델을 새로 올린다(SDXL 약 6.5GB).
# 이어지는 장은 다시 빠르다. 그 사실을 화면이 미리 말해 준다.
STYLE_PRESETS: dict = {
    "webtoon": {
        "label": "웹툰풍",
        "hint": "waiillustrious",
        "positive": "korean webtoon style, clean line art, cel shading, "
                    "soft warm palette, expressive eyes",
        "negative": "photorealistic, 3d render, western cartoon",
    },
    "anime": {
        "label": "일본만화풍",
        "hint": "waiillustrious",
        "positive": "japanese anime style, manga illustration, crisp linework, "
                    "vibrant cel shading, detailed eyes",
        "negative": "photorealistic, 3d render, western cartoon, sketch",
    },
    "real": {
        "label": "실사풍",
        "hint": "juggernautxl",
        "positive": "photorealistic, natural skin texture, realistic lighting, "
                    "shot on 85mm lens, shallow depth of field, film grain",
        "negative": "anime, cartoon, illustration, cel shading, line art, 2d",
    },
}
STYLE_KEEP = ""          # "" = 사전 설정 안 씀(매니페스트에 적힌 그대로)


def style_keys() -> list:
    return list(STYLE_PRESETS)


def _drop_style_words(text: str) -> str:
    """프롬프트에 박혀 있는 매니페스트 visual_style 문구를 걱어낸다(없으면 그대로)."""
    try:
        style = str(vn_core.visual_style(vn_core.load_json_safe(MANIFEST, {})) or "").strip()
    except Exception:
        style = ""
    out = str(text or "")
    if not style:
        return out.strip()
    low, sl = out.lower(), style.lower()
    i = low.find(sl)
    if i < 0:
        # 통째로는 없고 조각으로 있을 수 있다 — 쉼표로 끊어 같은 조각만 본다.
        parts = [x.strip() for x in style.split(",") if len(x.strip()) > 6]
        for chunk in parts:
            j = out.lower().find(chunk.lower())
            if j >= 0:
                out = out[:j] + out[j + len(chunk):]
        return re.sub(r"\s*,\s*,", ",", out).strip().strip(",").strip()
    out = out[:i] + out[i + len(style):]
    return re.sub(r"\s*,\s*,", ",", out).strip().strip(",").strip()


def resolve_style(key: str = "") -> dict:
    """프리셋 키 → {key, label, ckpt, positive, negative, found, note}.

    ``found`` 가 False 면 그 그림체의 체크포인트를 못 찾아 매니페스트 것으로 떨어졌다는
    뜻이다. 화면이 그것을 반드시 말해야 한다 — 고른 그림체와 다른 그림이 나오기 때문이다.
    """
    k = str(key or "").strip().lower()
    if not k or k not in STYLE_PRESETS:
        return {"key": "", "label": "지금 설정", "ckpt": checkpoint(),
                "positive": "", "negative": "", "found": True, "note": ""}
    p = STYLE_PRESETS[k]
    want = str(p["hint"]).lower()
    try:
        names = checkpoints()
    except VNError:
        names = []
    hit = next((n for n in names if want in n.lower().replace("_", "").replace("-", "")), "")
    if hit:
        return {"key": k, "label": p["label"], "ckpt": hit, "positive": p["positive"],
                "negative": p["negative"], "found": True, "note": ""}
    fallback = checkpoint()
    return {"key": k, "label": p["label"], "ckpt": fallback, "positive": p["positive"],
            "negative": p["negative"], "found": False,
            "note": f"{p['label']} 에 맞는 체크포인트를 찾지 못해 {fallback} 로 굽습니다 "
                    f"— 그림체가 고른 것과 다를 수 있습니다."}


def configured_style() -> str:
    """매니페스트에 저장된 그림체 키("" = 사전 설정 안 씀)."""
    k = str(_cfg().get("style", "") or "").strip().lower()
    return k if k in STYLE_PRESETS else STYLE_KEEP


def set_style(key: str) -> str:
    """그림체를 저장한다. 매니페스트의 다른 칸은 건드리지 않는다."""
    k = str(key or "").strip().lower()
    if k and k not in STYLE_PRESETS:
        raise VNError(f"모르는 그림체입니다: {k[:24]!r} (가능: {', '.join(STYLE_PRESETS)})")
    mf = vn_core.load_json_safe(MANIFEST, {})
    ig = mf.get("image_generator")
    if not isinstance(ig, dict):
        ig = {}
        mf["image_generator"] = ig
    cf = ig.get("comfyui")
    if not isinstance(cf, dict):
        cf = {}
        ig["comfyui"] = cf
    cf["style"] = k
    vn_core.atomic_write_json(MANIFEST, mf)
    _cfg.cache_clear() if hasattr(_cfg, "cache_clear") else None
    return k


# ------------------------------------------------------------------ 얼굴 고정(PhotoMaker)
#
# 왜 PhotoMaker 인가: 이 ComfyUI 에 **이미 기본 노드로 들어 있다**(PhotoMakerLoader ·
# PhotoMakerEncode). 커스텀 노드도, InsightFace 도, 추가 pip 도 필요 없다 — 이 저장소가
# '래퍼·부속 설치를 늘리지 않는다' 는 규칙 아래 있으므로 그 차이가 결정적이다.
# 필요한 것은 모델 파일 하나뿐이다: models/photomaker/photomaker-v1.bin (934MB).
#
# 어떻게 동작하나: 프롬프트 안의 **특별한 낱말 한 개**가 그 사람의 자리를 대신한다.
# ComfyUI 구현의 그 낱말은 "photomaker" 다(comfy_extras/nodes_photomaker.py 의
# special_token). 그 자리에 참고 사진에서 뽑은 얼굴 임베딩이 끼어든다.
#
# 한계를 분명히 적어 둔다 — 화면이 이 사실을 그대로 말해야 하기 때문이다:
#   * **한 장면에 한 사람.** 두 인물이 나오는 장면에는 쓸 수 없다(임베딩이 하나다).
#   * SDXL 실사 계열에서 가장 잘 듣는다. 애니·웹툰 체크포인트에서는 약해진다.
#   * 사진이 여러 장이면 같은 사람의 사진이어야 한다(여러 얼굴을 섞지 않는다).
PHOTOMAKER_TOKEN = "photomaker"
_PM_CACHE: dict = {"ts": 0.0, "names": []}
# 사람 낱말 — 특별한 낱말을 **이 낱말 바로 뒤**에 둔다("a young man photomaker").
# 그냥 앞에 붙이면("photomaker, a young man …") 성별·나이가 얼굴 임베딩과 따로 놀아서
# 실측에서 옷만 맞고 얼굴이 흔들리는 그림이 나온다.
_PERSON_WORD = re.compile(
    r"\b(man|woman|male|female|guy|girl|boy|lady|person|gentleman|student|adult)\b", re.I)


def _combo_options(spec) -> list:
    """object_info 의 콤보 입력 → 고를 수 있는 이름 목록.

    ComfyUI 안에 **두 가지 모양이 동시에** 산다(이 기계에서 실측):
      CheckpointLoaderSimple → [["a.safetensors", …], {tooltip: …}]      (예전 스키마)
      PhotoMakerLoader       → ["COMBO", {"options": ["photomaker-v1.bin"]}]  (새 스키마)
    한쪽만 읽으면 다른 쪽에서 조용히 빈 목록이 되고, 기능이 '설치 안 됨' 으로 보인다.
    """
    if not isinstance(spec, list) or not spec:
        return []
    head = spec[0]
    if isinstance(head, list):
        return [str(x) for x in head if x]
    tail = spec[1] if len(spec) > 1 else None
    opts = tail.get("options") if isinstance(tail, dict) else None
    return [str(x) for x in (opts if isinstance(opts, list) else []) if x]


def photomaker_models(refresh: bool = False) -> list:
    """설치된 PhotoMaker 모델 목록. **없어도 예외를 내지 않는다** — 기능이 꺼져 있을 뿐이다.

    노드 자체가 없는 ComfyUI(구버전)도 같은 취급이다. 여기서 예외를 던지면 그림 생성
    화면 전체가 얼굴 고정 하나 때문에 열리지 않는다.
    """
    now = time.monotonic()
    if not refresh and _PM_CACHE["names"] and now - _PM_CACHE["ts"] < _CKPT_TTL:
        return list(_PM_CACHE["names"])
    try:
        d = _json("GET", "/object_info/PhotoMakerLoader", timeout=10)
        spec = d["PhotoMakerLoader"]["input"]["required"]["photomaker_model_name"]
        names = _combo_options(spec)
    except (VNError, KeyError, IndexError, TypeError):
        names = []
    _PM_CACHE.update(ts=now, names=list(names))
    return names


def face_ready() -> dict:
    """사진으로 얼굴을 잡을 수 있는가 — **지금 이 엔진 기준으로**.

    화면이 이 답을 그대로 사람에게 보여 준다. 조용히 못 쓰면서 사진만 받아 두면,
    사람은 얼굴이 흔들릴 때마다 자기 사진을 의심한다.
    """
    names = photomaker_models()
    if not names:
        return {"ok": False, "model": "", "how": "text",
                "note": ("지금은 인물 태그와 앵커 문장으로만 얼굴을 고정합니다. 사진으로 잡으려면 "
                         "ComfyUI 의 models/photomaker/ 에 photomaker-v1.bin 이 있어야 합니다.")}
    return {"ok": True, "model": names[0], "how": "photomaker",
            "note": ("등록한 사진으로 얼굴을 잡습니다(PhotoMaker). 한 장면에 한 사람까지이고, "
                     "실사 계열 체크포인트에서 가장 잘 듣습니다.")}


def with_face_token(text: str) -> str:
    """프롬프트에 특별한 낱말을 **한 번** 넣는다(이미 있으면 그대로).

    사람 낱말 바로 뒤가 제자리다. 못 찾으면 맨 앞에 둔다 — 없는 것보다는 낫고,
    PhotoMakerEncode 는 낱말이 아예 없으면 **그 자리를 못 찾아 실패한다**.
    """
    body = str(text or "")
    if re.search(r"\b%s\b" % PHOTOMAKER_TOKEN, body, re.I):
        return body
    m = _PERSON_WORD.search(body)
    if m:
        return body[:m.end()] + " " + PHOTOMAKER_TOKEN + body[m.end():]
    return PHOTOMAKER_TOKEN + ", " + body if body else PHOTOMAKER_TOKEN


def upload_image(path, subfolder: str = "vn_faces") -> str:
    """참고 사진을 ComfyUI 로 올린다 → LoadImage 가 쓸 이름.

    경로로 건네지 않는 이유: **두 기계가 다를 수 있다.** 노트북에서 스튜디오를 돌리면
    사진은 노트북에 있고 ComfyUI 는 데스크탑에 있다 — 경로는 서로의 디스크를 가리키지
    못한다. 그림을 HTTP 로 받아오는 것과 같은 이유로, 보내는 것도 HTTP 로 한다.
    """
    src = Path(path)
    data = src.read_bytes()
    if not data:
        raise VNError(f"참고 사진이 비어 있습니다: {src.name}")
    boundary = "----vnstudio%s" % uuid.uuid4().hex
    ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
             "webp": "image/webp", "gif": "image/gif"}.get(src.suffix.lower().lstrip("."),
                                                           "application/octet-stream")
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                      % (boundary, name, value)).encode("utf-8"))

    field("overwrite", "true")
    if subfolder:
        field("subfolder", subfolder)
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\n"
                  "Content-Type: %s\r\n\r\n" % (boundary, src.name, ctype)).encode("utf-8"))
    parts.append(data)
    parts.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(
        base_url() + "/upload/image", data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                 "User-Agent": "vn-studio/1.0"})
    try:
        with _OPENER.open(req, timeout=60) as r:
            got = json.loads(r.read(1 << 20).decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        with contextlib.suppress(Exception):
            detail = e.read().decode("utf-8", "replace")
        raise VNError(f"참고 사진을 ComfyUI 에 올리지 못했습니다(HTTP {e.code}): {detail[:200]}")
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
        raise _fail_connect(getattr(e, "reason", None) or f"{type(e).__name__}: {e}")
    nm = str((got or {}).get("name", "") or "").strip()
    if not nm:
        raise VNError("ComfyUI 가 올린 사진의 이름을 주지 않았습니다.")
    sub = str((got or {}).get("subfolder", "") or "").strip()
    return f"{sub}/{nm}" if sub else nm


def build_graph(prompt: str, negative: str, *, ckpt: str, seed: int, s: dict, plan: dict,
                name: str = "", face: dict | None = None) -> dict:
    """ComfyUI API 그래프(노드 id → {class_type, inputs}).

    4 CheckpointLoaderSimple → [10 CLIPSetLastLayer] → 6/7 CLIPTextEncode → 5 EmptyLatentImage
    → 3 KSampler → [11 LatentUpscale → 12 KSampler(hires)] → 8 VAEDecode → 9 SaveImage.
    hires 2단은 plan["hires"] 일 때만 — 같은 시드를 두 단계에 쓴다(재현성).
    """
    clip = ["4", 1]
    g: dict = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}}}
    if int(s.get("clip_skip", 1)) > 1:
        g["10"] = {"class_type": "CLIPSetLastLayer",
                   "inputs": {"stop_at_clip_layer": -int(s["clip_skip"]), "clip": ["4", 1]}}
        clip = ["10", 0]
    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": clip}}
    g["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": clip}}
    positive = ["6", 0]
    if face and face.get("model") and face.get("image"):
        # 얼굴 고정 — 긍정 쪽 조건만 갈아 끼운다(부정 프롬프트는 그대로다).
        g["20"] = {"class_type": "PhotoMakerLoader",
                   "inputs": {"photomaker_model_name": str(face["model"])}}
        g["21"] = {"class_type": "LoadImage", "inputs": {"image": str(face["image"])}}
        g["22"] = {"class_type": "PhotoMakerEncode",
                   "inputs": {"photomaker": ["20", 0], "image": ["21", 0], "clip": clip,
                              "text": with_face_token(prompt)}}
        positive = ["22", 0]
    g["5"] = {"class_type": "EmptyLatentImage",
              "inputs": {"width": int(plan["base_width"]), "height": int(plan["base_height"]),
                         "batch_size": 1}}
    common = {"model": ["4", 0], "positive": positive, "negative": ["7", 0],
              "sampler_name": str(s["sampler"]), "scheduler": str(s["scheduler"]),
              "cfg": float(s["cfg"]), "seed": check_seed(seed)}
    g["3"] = {"class_type": "KSampler",
              "inputs": {**common, "steps": int(s["steps"]), "denoise": 1.0, "latent_image": ["5", 0]}}
    last = ["3", 0]
    if plan.get("hires"):
        g["11"] = {"class_type": "LatentUpscale",
                   "inputs": {"upscale_method": "bislerp", "width": int(plan["width"]),
                              "height": int(plan["height"]), "crop": "disabled", "samples": ["3", 0]}}
        g["12"] = {"class_type": "KSampler",
                   "inputs": {**common, "steps": int(s["hires_steps"]),
                              "denoise": float(s["hires_denoise"]), "latent_image": ["11", 0]}}
        last = ["12", 0]
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": last, "vae": ["4", 2]}}
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "prompt"))[:40] or "prompt"
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": f"{SAVE_PREFIX}/{safe}",
                                                     "images": ["8", 0]}}
    return g


# --- 제출 · 대기 · 다운로드 --------------------------------------------------------

def submit(graph: dict) -> str:
    """그래프 제출 → prompt_id. 400(node_errors)은 노드·종류·메시지를 담은 VNError 로."""
    d = _json("POST", "/prompt", {"prompt": graph, "client_id": CLIENT_ID}, timeout=60)
    pid = str((d or {}).get("prompt_id", "") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", pid):
        raise VNError(f"ComfyUI 가 prompt_id 를 주지 않았습니다: {str(d)[:200]}")
    return pid


def _short(pid: str) -> str:
    return pid.replace("-", "")[:6]


def _queue_state(pid: str) -> str:
    """이 작업이 큐의 어디에 있는지 — '렌더 중' / '대기 N번째' / ''(큐에 없음)."""
    try:
        q = _json("GET", "/queue", timeout=10)
    except VNError:
        return ""
    for item in (q.get("queue_running") or []):
        if isinstance(item, list) and len(item) > 1 and item[1] == pid:
            return "렌더 중"
    for i, item in enumerate(q.get("queue_pending") or []):
        if isinstance(item, list) and len(item) > 1 and item[1] == pid:
            return f"대기 {i + 1}번째"
    return ""


def _error_lines(status: dict) -> list[str]:
    out = []
    for m in (status.get("messages") or []):
        if isinstance(m, list) and len(m) > 1 and m[0] == "execution_error" and isinstance(m[1], dict):
            e = m[1]
            out.append(f"노드 {e.get('node_id', '?')}[{e.get('node_type', '?')}]: "
                       f"{str(e.get('exception_message', '')).strip()[:300]}")
    return out or [str(status.get("status_str", "error"))]


def cancel(pid: str) -> None:
    """시간 초과 정리 — 실행 중이면 중단, 대기 중이면 큐에서 뺀다(실패해도 조용히)."""
    with contextlib.suppress(VNError):
        if _queue_state(pid) == "렌더 중":
            _http("POST", "/interrupt", {}, timeout=10)
    with contextlib.suppress(VNError):
        _http("POST", "/queue", {"delete": [pid]}, timeout=10)


def wait(pid: str, on_progress=None, max_sec: int | None = None, quiet: bool = False) -> list[dict]:
    """완료까지 /history 를 1.5초마다 조회 → 결과 이미지 참조 [{filename, subfolder, type}].

    on_progress(elapsed_sec, status_text) 는 gen_jobs 의 심장박동이다 — 갱신이 끊기면 선점 잠금이
    좌초로 회수되어 같은 장면이 두 곳에서 굽힐 수 있으므로 매 조회마다 부른다.
    """
    max_sec = int(max_sec or settings(configured_checkpoint())["timeout_sec"])
    started = time.monotonic()
    deadline = started + max_sec
    tty = False
    with contextlib.suppress(Exception):
        tty = bool(sys.stdout.isatty())
    last_note, dirty = -99.0, False
    try:
        while time.monotonic() < deadline:
            hist = _json("GET", f"/history/{urllib.parse.quote(pid)}", timeout=20)
            rec = hist.get(pid) if isinstance(hist, dict) else None
            elapsed = time.monotonic() - started
            if isinstance(rec, dict) and rec:
                status = rec.get("status") if isinstance(rec.get("status"), dict) else {}
                if str(status.get("status_str", "")).lower() == "error":
                    raise VNError(f"ComfyUI 실행 실패(작업 {_short(pid)}): " + " / ".join(_error_lines(status)))
                refs = [img for node in (rec.get("outputs") or {}).values() if isinstance(node, dict)
                        for img in (node.get("images") or [])
                        if isinstance(img, dict) and img.get("filename")
                        and str(img.get("type", "output")) == "output"]
                if refs:
                    return refs
                if status.get("completed"):
                    raise VNError(f"ComfyUI 작업 {_short(pid)} 이 끝났지만 저장된 이미지가 없습니다.")
            st = _queue_state(pid) or "조회중"
            if callable(on_progress):
                with contextlib.suppress(Exception):
                    on_progress(elapsed, st)
            if not quiet:
                line = f"  렌더 대기 {elapsed:.0f}초 · {st} · 작업 {_short(pid)}"
                if tty:
                    with contextlib.suppress(Exception):
                        print("\r" + line.ljust(58), end="", flush=True)
                        dirty = True
                elif elapsed - last_note >= 30:
                    _say(line)
                    last_note = elapsed
            time.sleep(POLL_SEC)
    finally:
        if dirty:
            with contextlib.suppress(Exception):
                print("\r" + " " * 58 + "\r", end="", flush=True)
    cancel(pid)
    raise VNError(f"ComfyUI 렌더 대기 시간 초과({max_sec}초) — 작업 {_short(pid)} 을 중단·삭제했습니다. "
                  f"(manifest comfyui.timeout_sec 으로 늘릴 수 있습니다)")


def download(ref: dict, dest: Path) -> Path:
    """GET /view 로 결과를 받아 원자적으로 저장한다. PNG 매직바이트가 아니면 거부."""
    q = urllib.parse.urlencode({"filename": str(ref.get("filename", "")),
                                "subfolder": str(ref.get("subfolder", "") or ""),
                                "type": str(ref.get("type", "output") or "output")})
    data = _http("GET", "/view?" + q, timeout=120, cap=DL_CAP)
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise VNError(f"ComfyUI 결과가 PNG 가 아닙니다: {str(ref.get('filename', ''))[:80]}")
    atomic_write_bytes(dest, data)
    return Path(dest)


# --- 생성 ---------------------------------------------------------------------

REF_WARNING = "레퍼런스 이미지는 ComfyUI 경로에서 아직 쓰지 않습니다(앵커·시드로 일관성 유지)"


def check_seed(seed) -> int:
    """KSampler 가 받는 범위(0 ~ 2**64-1)의 정수로 확인한다 — 아니면 VNError.

    제출한 뒤 400 으로 알게 되면 어느 값이 문제였는지 화면에 남지 않는다(그래프 전체가
    오류 본문에 실린다). 그래서 그래프를 만드는 자리에서 먼저 막는다.
    """
    try:
        v = int(seed)
    except (TypeError, ValueError):
        raise VNError(f"시드는 정수여야 합니다: {seed!r}")
    if not 0 <= v <= SEED_MAX:
        raise VNError(f"시드는 0 ~ {SEED_MAX} 범위여야 합니다(ComfyUI KSampler): {v} "
                      f"(무작위로 두려면 --seed 를 빼세요)")
    return v


def _seed(seed) -> int:
    if seed is None:
        return random.randrange(0, 2 ** 53)
    return check_seed(seed)


def generate_to_dir(prompt: str, out_dir: Path, n: int = 1, name: str = "",
                    long_edge: int | None = None, negative: bool = True,
                    scene_id: str = "", on_progress=None, quiet: bool = False,
                    input_images=None, seed=None, on_each=None, should_stop=None,
                    style: str | None = None, face_photo=None) -> GenResult:
    """n 장을 **순차** 렌더(시드 seed, seed+1, …)해 out_dir 에 cf_<id6>_<i>.png 로 저장.

    한 장이 실패해도 나머지는 살리고 경고로 알린다. 장마다 _gen_meta.json 항목과
    logs/comfyui_usage.jsonl 한 줄(billable false)을 남긴다.
    """
    text = str(prompt or "").strip()
    if not text:
        raise VNError("이미지 프롬프트가 비어 있습니다.")
    out_dir = Path(out_dir)
    n = max(1, min(int(n or 1), 8))
    # 그림체 사전 설정 — 호출부가 명시하면 그것, 아니면 매니페스트에 저장된 것.
    # 체크포인트까지 함께 갈리므로(그게 그림체의 진짜 레버다) 여기서 한 번에 정한다.
    st = resolve_style(configured_style() if style is None else style)
    ckpt = st["ckpt"]
    s = settings(ckpt)
    plan = size_plan(long_edge)
    pos = _with_prefix(text, s.get("prompt_prefix", ""))
    if st["positive"]:
        # 매니페스트의 visual_style 은 저장된 프롬프트 **안에** 박혀 있다(조립할 때
        # 모델이 그렇게 쓴다). 그걸 두고 실사풍을 앞에 붙이면 한 프롬프트 안에서
        # "cel-shaded webtoon" 과 "photorealistic" 이 서로 싸운다 — 실측으로 그랬다.
        # 그림체를 골랏으면 그것이 정본이다 — 예전 그림체 문구를 빼고 바꿔 끼운다.
        pos = _drop_style_words(pos)
        pos = _with_prefix(pos, st["positive"])
    neg = negative_text(s, negative)
    if st["negative"] and neg:
        neg = st["negative"] + ", " + neg
    elif st["negative"]:
        neg = st["negative"]
    base = _seed(seed)
    warns: list[str] = list(size_warnings(plan))
    if st.get("note"):
        warns.append(st["note"])       # 조용히 다른 그림체로 굽지 않는다
    if input_images:
        warns.append(REF_WARNING)
    for msg in warns:
        _say("  ⚠ " + msg, quiet)
    _say(f"  {LABEL} · {st['label']} · {ckpt} · {plan['width']}x{plan['height']}"
         f"{' (hires ' + str(plan['base_width']) + 'x' + str(plan['base_height']) + '→)' if plan['hires'] else ''}"
         f" · seed {base}{'+' if n > 1 else ''}", quiet)
    # 얼굴 고정 — **한 번만** 올린다(장마다 올리면 같은 사진이 n번 네트워크를 탄다).
    # 실패해도 그림은 굽는다: 얼굴이 안 잡힌 그림이 아무 그림도 없는 것보다 낫고,
    # 무엇이 안 됐는지는 경고로 남는다.
    face = None
    if face_photo:
        try:
            names = photomaker_models()
            if not names:
                warns.append("얼굴 고정을 건너뜁니다 — ComfyUI 에 PhotoMaker 모델이 없습니다.")
            else:
                face = {"model": names[0], "image": upload_image(face_photo)}
        except (VNError, OSError) as e:
            face = None
            warns.append(f"얼굴 고정을 건너뜁니다({e}).")
    saved: list[Path] = []
    ids: list[str] = []
    stopped = False
    for i in range(n):
        # 장 사이에서만 멈춘다 — 굽는 도중에 끊으면 반쯤 쓰인 파일이 남는다.
        if should_stop and should_stop():
            stopped = True
            warns.append(f"{i + 1}번째부터는 멈췄습니다(사람이 그만두었습니다).")
            break
        sd = (base + i) % (SEED_MAX + 1)      # 상한을 넘으면 되돌아온다(값은 여전히 결정적이다)
        started = _now()
        pid, err = "", ""
        files: list[Path] = []
        try:
            pid = submit(build_graph(pos, neg, ckpt=ckpt, seed=sd, s=s, plan=plan,
                                     name=name or scene_id or "prompt", face=face))
            ids.append(pid)
            refs = wait(pid, on_progress=on_progress, max_sec=s["timeout_sec"], quiet=quiet)
            for j, ref in enumerate(refs):
                tail = f"{i + 1}" + (f"_{j + 1}" if j else "")
                files.append(download(ref, out_dir / f"{FILE_PREFIX}_{_short(pid)}_{tail}.png"))
        except VNError as e:
            err = str(e)[:300]
            warns.append(f"{i + 1}번째(seed {sd}): {e}")
        # 대장·메타는 장마다 한 줄씩 — 실패도 남긴다(무엇을 어떤 설정으로 시켰는지가 재현의 단서다).
        gen_common.log_usage(USAGE_LOG, {
            "kind": "text2image", "scene_id": scene_id, "task_id": pid, "requested": 1,
            "saved": len(files), "ok": bool(files) and not err, "model": ckpt, "seed": sd,
            "width": plan["width"], "height": plan["height"], "hires": plan["hires"],
            "billable": False, "error": err})
        write_gen_meta(out_dir, {
            "created_at": started, "scene_id": scene_id, "task_id": pid, "kind": "text2image",
            "engine": ENGINE, "prompt": pos, "negative": neg, "model": ckpt, "seed": sd,
            "steps": s["steps"], "cfg": s["cfg"], "sampler": s["sampler"],
            "scheduler": s["scheduler"], "clip_skip": s["clip_skip"],
            "width": plan["width"], "height": plan["height"], "hires": plan["hires"],
            "files": [f.name for f in files],
            "status": "ok" if files and not err else ("partial" if files else "failed"),
            "error": err, "billable": False})
        saved += files
        # 한 장이 끝날 때마다 알린다 — 다 구워질 때까지 기다리지 않고 화면이 바로 보여 준다.
        # 실측: 4장이면 92초인데, 한 장에 만족한 날은 23초에 끝낼 수 있다.
        if on_each and files:
            try:
                on_each(i + 1, n, [str(f) for f in files])
            except Exception:
                pass      # 화면 갱신 실패가 남은 장을 굽지 못하게 두지 않는다
    if not saved:
        if stopped:
            raise VNError("한 장도 굽기 전에 멈췄습니다.")
        raise VNError("생성된 이미지가 없습니다." + (" " + " / ".join(warns) if warns else ""))
    return GenResult(saved, warns, ids)


def _scene_path(scene_id: str) -> Path:
    if not is_scene_id(scene_id):
        raise VNError(f"장면 ID 형식이 올바르지 않습니다: {str(scene_id)[:40]!r}")
    return SCENES_DIR / f"{scene_id}.json"


def _load_scene(scene_id: str) -> dict:
    p = _scene_path(scene_id)
    if not p.exists():
        raise VNError(f"장면 파일이 없습니다: {scene_id}")
    sc = load_json(p)
    if not isinstance(sc, dict):
        raise VNError(f"{scene_id}: JSON 최상위가 객체가 아닙니다.")
    return sc


def _scene_refs(sc: dict) -> list[str]:
    """장면 등장인물의 매니페스트 reference_images — 쓰지 않지만 '있는데 안 쓴다'를 알리기 위해 센다."""
    chars = load_json_safe(MANIFEST, {}).get("characters")
    index = {str(c.get("character_id", "")): c
             for c in (chars if isinstance(chars, list) else []) if isinstance(c, dict)}
    out: list[str] = []
    for cid in (sc.get("characters") if isinstance(sc.get("characters"), list) else []):
        refs = (index.get(str(cid)) or {}).get("reference_images")
        out += [str(r) for r in (refs if isinstance(refs, list) else []) if str(r or "").strip()]
    return out


def _assert_mutable(scene_id: str, sc: dict) -> None:
    """APPROVED 장면은 다시 굽지 않는다 — 표준 문구는 scene_ops 가 낸다(지연 import).

    scene_ops 가 없는 복제 환경에서도 같은 결정을 내려야 하므로 상태 확인은 여기서도 한다.
    """
    try:
        import scene_ops
    except ImportError:
        if sc.get("status") == "APPROVED":
            raise VNError(f"{scene_id} 는 APPROVED 입니다. 이미지를 다시 생성하려면 먼저 revise 로 되돌리세요.")
        return
    scene_ops.assert_mutable(scene_id, "이미지를 다시 생성하려면")


def _record_generator(scene_id: str, ckpt: str) -> str:
    """prompt.external_generator/external_model 기록 — 쓰기는 scene_ops 가 한다. 실패는 경고 문구."""
    try:
        import scene_ops
        scene_ops.record_external_generator(scene_id, LABEL, ckpt)
        return ""
    except Exception as exc:
        log.warning("생성기 기록 실패 %s: %s", scene_id, exc)
        return f"생성기 기록 실패(prompt.external_generator): {exc}"


def generate_for_scene(scene_id: str, n: int = 1, long_edge: int | None = None,
                       negative: bool = True, on_progress=None, quiet: bool = False,
                       reference: bool = True, seed=None, on_each=None,
                       should_stop=None, style: str | None = None,
                       face_photo=None) -> GenResult:
    """장면의 이미지 프롬프트(prompt.grok_output)로 렌더해 images/raw/<scene>/ 에 저장.

    성공하면 scene_ops.record_external_generator 로 "ComfyUI · <체크포인트>" 를 남긴다(실패는 경고).
    reference=True 여도 레퍼런스는 아직 쓰지 않는다 — 매니페스트에 있으면 경고로 알린다.
    """
    sc = _load_scene(scene_id)
    _assert_mutable(scene_id, sc)
    prompt = str((sc.get("prompt", {}) or {}).get("grok_output", "")).strip()
    if not prompt:
        raise VNError(f"{scene_id} 에 이미지 프롬프트가 없습니다. 먼저 프롬프트를 생성하세요.")
    refs = _scene_refs(sc) if reference else []
    res = generate_to_dir(prompt, RAW_DIR / scene_id, n=n, name=scene_id, long_edge=long_edge,
                          negative=negative, scene_id=scene_id, on_progress=on_progress,
                          quiet=quiet, input_images=refs, seed=seed,
                          on_each=on_each, should_stop=should_stop, style=style,
                          face_photo=face_photo)
    warn = _record_generator(scene_id, checkpoint())
    if warn:
        res.warnings.append(warn)
    return res


# --- 선점(gen_jobs) · 배치 -------------------------------------------------------
# 웹과 CLI 가 같은 장면을 동시에 굽지 않게 하는 관문은 gen_jobs 하나다(makefun_client 와 동일).
# 무료라 이중 과금은 없지만 GPU 한 대에 같은 컷을 두 번 시키는 일과, 등록이 겹쳐 후보 목록이
# 서로를 덮는 일은 막아야 한다. gen_jobs 가 없는 환경(이 파일만 복제)에서는 잠금 없이 통과한다.

def _jobs():
    try:
        import gen_jobs
    except ImportError:
        return None
    return gen_jobs


@contextlib.contextmanager
def claim_scene(scene_id: str, label: str = "생성"):
    jobs = _jobs()
    if not scene_id or jobs is None:
        yield False
        return
    with jobs.claimed(scene_id, label):
        yield True


def run_scene(scene_id: str, *, n: int = 1, long_edge: int | None = None, negative: bool = True,
              seed=None, quiet: bool = False, register: bool = True) -> dict:
    """CLI 용 — 선점 → 렌더 → (register 면) 후보 등록·자동 검사까지 gen_jobs.run 으로.

    MakeFun CLI 는 파일만 남기고 등록은 스튜디오에 맡겼다(유료 결과를 검사기 실패로 잃지 않게).
    로컬 렌더는 다시 만들면 되므로 한 명령으로 후보 등록·자동 검사(상태 IMAGE)까지 간다
    — --no-register 로 끌 수 있다. 시사 단계(REVIEW_HUMAN)는 사람이 후보를 고를 때 찍힌다.
    gen_jobs 가 없으면 등록 없이 파일만 남긴다.
    """
    def work():
        return generate_for_scene(scene_id, n=n, long_edge=long_edge, negative=negative,
                                  quiet=quiet, seed=seed)
    jobs = _jobs()
    if jobs is None:
        files = work()
        return {"scene_id": scene_id, "generated": [f.name for f in files], "count": len(files),
                "warnings": list(files.warnings), "auto": ""}
    return jobs.start(scene_id, work, "생성", sync=True, register=register)


def _has_images(scene_id: str, sc: dict) -> bool:
    assets = sc.get("assets") if isinstance(sc.get("assets"), dict) else {}
    if (assets.get("raw_images") or []) or selected_of(sc):
        return True
    folder = RAW_DIR / scene_id
    return folder.exists() and any(f.suffix.lower() in IMAGE_EXTS for f in folder.glob("*"))


def pending_scenes() -> list[str]:
    """프롬프트가 있고 이미지가 없는 장면(APPROVED 제외) — 훑기는 vn_core.iter_scenes 하나."""
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
                         seed=None, register: bool = True) -> dict:
    """대기 장면을 순회 렌더 — 한 장면이 실패해도 다음으로 넘어간다."""
    targets = pending_scenes()
    if limit and limit > 0:
        targets = targets[:limit]
    result = {"planned": targets, "done": {}, "failed": {}, "warnings": [],
              "size_warnings": size_warnings(long_edge=long_edge), "dry_run": dry_run}
    if dry_run or not targets:
        for msg in result["size_warnings"]:
            _say("⚠ 생성 크기 — " + msg, quiet)
        return result
    for k, sid in enumerate(targets, 1):
        _say(f"[{sid}] 렌더 시작 ({k}/{len(targets)})", quiet)
        try:
            rep = run_scene(sid, n=n, long_edge=long_edge, negative=negative, seed=seed,
                            quiet=quiet, register=register)
            result["done"][sid] = list(rep.get("generated", []))
            result["warnings"] += [f"{sid}: {w}" for w in rep.get("warnings", [])
                                   if w not in result["size_warnings"]]
        except RuntimeError as e:
            result["failed"][sid] = str(e)
            _say(f"[{sid}] 실패 — {e}", quiet)
    return result


# --- 사전 점검 -------------------------------------------------------------------

def check(online: bool = False) -> dict:
    """주소·체크포인트·샘플링 설정·크기 계획 점검. online=True 면 ComfyUI 에 실제로 물어본다(무료)."""
    rep = {"ok": True, "lines": []}

    def add(ok: bool, msg: str, fatal: bool = True) -> None:
        rep["lines"].append(("OK  " if ok else "FAIL") + " " + msg)
        if not ok and fatal:
            rep["ok"] = False

    env = os.environ.get(ENV_URL, "").strip()
    try:
        add(True, f"base_url: {display_url()}" + (f" (환경변수 {ENV_URL})" if env else " (매니페스트/기본값)"))
    except VNError as e:
        add(False, str(e))
    top = _top()
    add(bool(top.get("comfyui")), "manifest image_generator.comfyui 설정 "
        + ("있음" if top.get("comfyui") else "없음 — 전부 기본값으로 돕니다"), fatal=False)
    if str(top.get("engine", "")).strip().lower() not in ("", ENGINE):
        rep["lines"].append(f"주의 기본 엔진이 {top.get('engine')} 입니다 — 스튜디오 기본 버튼은 그 엔진을 씁니다.")
    ck = configured_checkpoint()
    s = settings(ck)
    add(True, f"체크포인트: {ck or '(미지정 → ComfyUI 첫 항목)'}"
              + (" · Illustrious 계열 프리셋 적용(매니페스트 명시값 우선)" if preset(ck) else ""))
    add(True, f"샘플링: steps {s['steps']} · cfg {s['cfg']} · {s['sampler']}/{s['scheduler']}"
              f" · clip_skip {s['clip_skip']} · hires denoise {s['hires_denoise']}/{s['hires_steps']}steps"
              f" · timeout {s['timeout_sec']}초")
    plan = size_plan()
    add(True, f"생성 크기 {plan['width']}x{plan['height']} (요청 {plan['want']}px · 기본 캔버스 "
              f"{plan['base_width']}x{plan['base_height']} · hires {'예' if plan['hires'] else '아니오'}"
              f" · 상한 {plan['cap']}px{'(기본값)' if plan['cap_is_default'] else ''}"
              f" · hires 상한 {plan['hires_cap']}px)")
    for msg in size_warnings(plan):
        add(False, msg, fatal=False)
    if online:
        try:
            st = _json("GET", "/system_stats", timeout=5)
            ver = str((st.get("system") or {}).get("comfyui_version", "?"))
            devs = [str(d.get("name", "")) for d in (st.get("devices") or []) if isinstance(d, dict)]
            add(True, f"온라인: ComfyUI {ver} 응답" + (f" · {devs[0][:60]}" if devs else ""))
            names = checkpoints(refresh=True)
            add(bool(names), f"체크포인트 {len(names)}개: " + ", ".join(names)[:300])
            if ck:
                add(ck in names, f"지정 체크포인트 {'설치됨' if ck in names else '없음 — 이름을 위 목록에서 고르세요'}: {ck}")
        except VNError as e:
            add(False, str(e))
    return rep


# --- CLI ----------------------------------------------------------------------------

def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p)


def main() -> int:
    ap = argparse.ArgumentParser(description="ComfyUI(로컬) 텍스트→이미지")
    ap.add_argument("scene", nargs="?", help="장면 ID (예: SCENE-001)")
    ap.add_argument("--n", type=int, default=1, help="생성 장수(1~8, 시드 +1 씩)")
    ap.add_argument("--seed", type=int, default=None, help="시드(기본 무작위 — 같은 시드면 같은 그림)")
    ap.add_argument("--prompt", help="장면 대신 직접 프롬프트로 생성")
    ap.add_argument("--out", help="--prompt 모드의 저장 경로/폴더")
    ap.add_argument("--long-edge", type=int, default=0,
                    help="긴 변 픽셀(기본: manifest.output.min_long_edge_px, 최소 기본 캔버스)")
    ap.add_argument("--no-negative", action="store_true", help="네거티브 프롬프트를 비운다")
    ap.add_argument("--no-register", action="store_true",
                    help="장면 모드에서 후보 등록·자동 검사를 하지 않고 파일만 남긴다")
    ap.add_argument("--all-pending", action="store_true", help="프롬프트가 있고 이미지가 없는 장면을 일괄 렌더")
    ap.add_argument("--limit", type=int, default=0, help="--all-pending 최대 장면 수")
    ap.add_argument("--dry-run", action="store_true", help="--all-pending 대상만 표시")
    ap.add_argument("--check", action="store_true", help="주소·설정 사전 점검")
    ap.add_argument("--online", action="store_true", help="--check 에서 ComfyUI 에 실제로 물어본다")
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
            res = generate_all_pending(n=a.n, limit=a.limit, long_edge=long_edge, negative=neg,
                                       dry_run=a.dry_run, quiet=a.quiet, seed=a.seed,
                                       register=not a.no_register)
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

        if a.prompt:
            out = Path(a.out) if a.out else ROOT / "scratch"
            folder = out if out.is_dir() or not out.suffix else out.parent
            files = generate_to_dir(a.prompt, folder, n=a.n, long_edge=long_edge, negative=neg,
                                    quiet=a.quiet, seed=a.seed)
            if a.out and Path(a.out).suffix and files:
                files[0].replace(Path(a.out))
                files[0] = Path(a.out)
            for w in files.warnings:
                print("경고:", w)
            for f in files:
                print("저장:", _rel(f))
            return 0

        if a.scene:
            rep = run_scene(a.scene, n=a.n, long_edge=long_edge, negative=neg, seed=a.seed,
                            quiet=a.quiet, register=not a.no_register)
            for w in rep.get("warnings", []):
                print("경고:", w)
            for name in rep.get("generated", []):
                print("저장:", _rel(RAW_DIR / a.scene / name))
            if rep.get("auto"):
                print(f"등록 {rep.get('count', 0)}장 · 자동검사 {rep['auto']}"
                      + (f"\n{rep['fails']}" if rep.get("fails") else ""))
            return 0

        ap.error("장면 ID 또는 --prompt 가 필요합니다.")
        return 2
    except RuntimeError as e:
        print("오류:", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
