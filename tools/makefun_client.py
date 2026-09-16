#!/usr/bin/env python3
"""MakeFun AI 이미지 클라이언트 — 생성·업스케일·업로드(파이프라인 3단계 자동화).

API: POST /api/v1/userText2Image/start → {code:0, data:[{_id,...}]}
     GET  /api/v1/userText2Image/{id}  → current_status: initialized/processing → completed/failed
     POST /api/v1/r2/get_upload_presigned_url → {uploadUrl, cdnUrl} (로컬 파일 → 공개 URL)
     POST /api/v1/userUpscale/start → GET /api/v1/userUpscale/{id} (해상도만 키우는 유료 호출)
     GET  /api/v1/transactionRecord/creditsHistory (읽기 전용 — 그래도 토큰을 쓰는 실호출)
토큰은 환경변수 MAKEFUN_API_TOKEN 로만 공급한다(파일 저장 금지 — 검사기 A8).
설정은 manifest image_generator.makefun(model·api) + 공용 키(max_long_edge_px) — 옛 최상위
api/model 도 그대로 읽힌다(_cfg 가 합친다). 기본 엔진 선택은 image_generator.engine(image_gen).

사용:
  python tools/makefun_client.py SCENE-001 [--n 2] [--long-edge 1536] [--no-reference]
  python tools/makefun_client.py --prompt "..." --out scratch/test.png
  python tools/makefun_client.py --all-pending [--dry-run] [--limit 5]
  python tools/makefun_client.py SCENE-001 --refetch   # 과금 없이 기록된 task 로 재수령
  python tools/makefun_client.py --upscale SCENE-001   # 승인본을 재생성 없이 확대(유료)
  python tools/makefun_client.py --upload images/refs/jihye.png   # 레퍼런스용 공개 URL 발급
  python tools/makefun_client.py --credits             # 크레딧 이력(무과금이지만 실호출)
  python tools/makefun_client.py --check [--online]    # 토큰·설정 사전 점검(생성 크기 함정 포함)

인화 크기 주의: 요청 긴 변은 image_generator.max_long_edge_px(기본 2048)로 잘린다.
output.min_long_edge_px 만 1800/2250/3600 으로 올리면 과금은 그대로 되고 결과만 2048px 이 된다.
--check 와 생성 직전 경고가 그 조합을 미리 알려 준다(size_plan / size_warnings).

**업스케일이 그 상한을 재생성 없이 푸는 유일한 길이다.** 이미 승인된 컷(1200×1800)은 다시
만들면 그림이 달라지고 과금도 다시 된다. :func:`upscale_scene` 은 **사람이 고른 그 파일**을
올려서 크기만 키우고 새 후보로만 저장한다 — 선택·승인 상태는 건드리지 않으므로 승인 게이트의
의미가 그대로 남는다(그래서 APPROVED 장면에도 허용한다).

캐릭터 일관성: 매니페스트 characters[].reference_images 를 text2image 의 ``input_images`` 로
싣는다(A2E 최대 2장). 레퍼런스가 로컬 파일이면 R2 에 올려 URL 로 바꿔 보낸다 — 매니페스트를
고쳐 쓰지는 않는다(그 파일을 쓰는 것은 이 모듈의 일이 아니다).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import logging
import mimetypes
import os
import random
import re
import socket
import sys
import time
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:          # 저장소가 복제된 곳에서 이 파일만 적재돼도 '옆에 있는' vn_core 를 쓴다
    sys.path.insert(0, str(_HERE))

import gen_common                                              # noqa: E402
import vn_core                                                 # noqa: E402
from vn_core import (IMAGE_EXTS, VNError,                      # noqa: E402
                     atomic_write_bytes, is_scene_id,
                     iter_scenes, load_json, load_json_safe, safe_path,
                     safe_slug, selected_of)

# 경로는 vn_core 하나에서 온다. vn_core 도 자기 파일 위치(_HERE 와 같은 tools/)에서 계산하므로
# 자가진단이 저장소를 복제해 이 모듈만 적재해도 그대로 **그 복제본 안**만 읽고 쓴다.
# (예전에는 같은 값을 여기서 다시 조립했다 — 한쪽 폴더 이름이 바뀌면 조용히 갈리는 5벌이었다.)
ROOT = vn_core.ROOT
MANIFEST = vn_core.MANIFEST        # 테스트가 갈아끼우므로 함수는 호출 시점에 읽는다
SCENES_DIR = vn_core.SCENES
RAW_DIR = vn_core.IMAGES_RAW
USAGE_LOG = vn_core.LOGS / "makefun_usage.jsonl"
# 결과형·메타 파일 규약은 엔진 공용(gen_common)이다 — ComfyUI 경로와 같은 모양이어야
# gen_jobs·스튜디오가 어느 엔진의 결과든 같은 코드로 읽는다. 이름은 별칭으로 남겨 둔다
# (mk.GenResult / mk.META_NAME / mk.write_gen_meta 를 쓰는 호출부·테스트가 그대로 동작).
GenResult = gen_common.GenResult
META_NAME = gen_common.META_NAME
META_MAX_ENTRIES = gen_common.META_MAX_ENTRIES
write_gen_meta = gen_common.write_gen_meta
_now = gen_common.now_iso
ENGINE = "makefun"
LABEL = "MakeFun"
TOKEN_ENV = "MAKEFUN_API_TOKEN"
DEFAULT_BASE = "https://makefun.ai"
POLL_SEC = 4
POLL_MAX_SEC = 300
DL_CAP = 30 * 1024 * 1024
UP_CAP = 30 * 1024 * 1024          # 업로드 상한 — 다운로드와 같은 값으로 둔다

# 엔드포인트 — 경로 문자열이 코드 여기저기 흩어지면 오타가 조용한 404 가 된다.
P_T2I_START = "/api/v1/userText2Image/start"
P_T2I_TASK = "/api/v1/userText2Image/"
P_R2_PRESIGN = "/api/v1/r2/get_upload_presigned_url"
P_UPSCALE_START = "/api/v1/userUpscale/start"
P_UPSCALE_TASK = "/api/v1/userUpscale/"
P_UPSCALE_RECORDS = "/api/v1/userUpscale/allRecords"
P_CREDITS = "/api/v1/transactionRecord/creditsHistory"
# 생성 전 견적. 명세(A2E Developer API v1.0.0)가 "작업을 만들지도, 공급자를 부르지도,
# 크레딧을 차감하지도 않는다" 고 못박은 경로다 — 그래서 누르기 전에 물어볼 수 있다.
P_QUOTE = "/api/v1/generation/quote"
# 컷 한 장 → 움직이는 컷. 요청 쪽은 명세로 확정되지만 **응답 쪽은 비어 있다**
# ({"type":"object"} · example {}) — 작업 id 도 mp4 URL 도 어느 필드인지 모른다.
# 업스케일과 같은 상황이라 같은 방식으로 간다(관용 파서 + 모르면 응답을 담아 던지기).
P_I2V_START = "/api/v1/userImage2Video/start"
P_I2V_TASK = "/api/v1/userImage2Video/"
P_I2V_RECORDS = "/api/v1/userImage2Video/allRecords"
VIDEO_TIMES = (5, 10, 15, 20)          # 명세: min 5 · max 20 · 기본 5 (설명에 이 넷)
VIDEO_MODELS = ("a2e", "a2e-v2", "a2e-v2-flash")

# ---------------------------------------------------------------- NSFW 안전장치
# 공급자 명세에 이런 파라미터가 있다:
#
#   force_generate — "Force generation even if NSFW content is detected.
#                     **Defaults to true for API users**, false for web users"
#
# 우리는 API 토큰 사용자다. 즉 **값을 안 보내면 그쪽 안전장치가 꺼진 채로 돈다.**
# 그런데 이 프로젝트는 input_images 로 **실존 인물의 얼굴 사진**을 싣는다. 그 조합에서
# 사고가 나면 되돌릴 방법이 없다.
#
# 이 저장소에는 "ComfyUI 에 extra safety·필터를 붙이지 말 것" 이라는 규칙이 있다. 그건
# **내 기계의 로컬 엔진에 필터를 덧대지 말라**는 뜻이지, **남의 서버가 켜 둔 안전장치를
# 꺼도 된다**는 뜻이 아니다. 끄지 않는 쪽이 기본이다.
#
# 규칙으로 두지 않고 **구조로** 둔다: 아래 경로로 나가는 POST 는 _call 이 값을 채워 넣는다.
# 규칙은 다음 사람이 잊지만 구조는 잊지 않는다.
#
# 출처: 노트북 보존본 scratch/makefun_spec.json — A2E Developer API v1.0.0(openapi 3.0.0),
#       paths 206, 2026-08 수집본. 앞의 둘은 default=true 가 명시돼 있고, 뒤의 셋은
#       스키마에 default 가 안 적혀 있을 뿐이다(서버 기본이 false 라는 뜻이 아니다).
NSFW_FORCE_PATHS = ("/api/v1/userFlux2/start", "/api/v1/userNanoBanana/start",
                    "/api/v1/userGptImage/start", "/api/v1/userWan26Image/start",
                    "/api/v1/userWan27Image/start")


def with_safety(path: str, body):
    """그 경로가 안전장치를 끌 수 있는 경로면 **끄지 않는다고 명시**해서 보낸다.

    부르는 쪽이 이미 값을 적어 두었으면 건드리지 않는다 — 사람이 일부러 적은 값을
    코드가 덮으면, 몇 번을 적어도 바뀌지 않는 칸이 된다(그건 그것대로 거짓말이다).
    """
    if path not in NSFW_FORCE_PATHS or not isinstance(body, dict):
        return body
    if "force_generate" in body:
        return body
    out = dict(body)
    out["force_generate"] = False
    return out

# 레퍼런스 이미지(input_images) 상한 — 모델이 정한다. A2E 2장 · Seedream 5.0 Pro 10장.
REF_MAX_A2E = 2
REF_MAX_SEEDREAM = 10
UPLOAD_PREFIX = "vn-studio"        # R2 key 접두 — 이 도구가 올린 것을 나중에 알아볼 수 있게

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

# _gen_meta.json 보존 개수(META_MAX_ENTRIES)는 gen_common 이, 장면 assets.makefun_tasks 의
# 보존 개수는 그 파일을 쓰는 쪽(scene_ops.GEN_TASKS_MAX)이 정한다.
# 대장·메타의 read-modify-write 직렬화는 gen_common 이 저장소 전역 잠금(vn_core.WRITE_LOCK)으로 한다.


# 생성 작업 로그와 같은 채널(vn.gen) — webapp.setup_logging 이 logs/webapp.log 에 물린다.
# CLI 로 단독 실행될 때는 핸들러가 없어 조용하다(라이브러리 규약).
log = logging.getLogger("vn.gen")
log.addHandler(logging.NullHandler())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


_API = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())
_DL = urllib.request.build_opener(urllib.request.ProxyHandler())   # 결과 CDN 은 리다이렉트 허용(무토큰)
# presigned PUT 전용 — **Authorization 을 절대 싣지 않는다.** 서명 URL 에 우리 토큰까지 붙으면
# S3/R2 는 서명 불일치로 403 을 준다(그리고 남의 스토리지에 우리 토큰을 흘리는 셈이다).
# 리다이렉트는 여기서도 따라가지 않는다 — 서명은 원래 호스트에만 유효하다.
_UP = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())


class _Transient(RuntimeError):
    """재시도 가치가 있는 오류(429·5xx·일시 네트워크). presend=요청이 전송되기 전에 실패."""

    def __init__(self, msg: str, code: int | None = None,
                 retry_after: float | None = None, presend: bool = False):
        super().__init__(msg)
        self.code = code
        self.retry_after = retry_after
        self.presend = presend


def _host_of(url: str) -> str:
    """안내문에 실을 수 있는 주소 — scheme://host[:port]/path 까지, **쿼리는 버린다.**

    presigned URL 의 쿼리에는 서명(자격증명)이 들어 있다. 오류 문장은 화면과 로그에
    그대로 남으므로, 여기서 잘라내지 않으면 안내 한 줄이 곧 유출이다.
    """
    try:
        u = urllib.parse.urlsplit(str(url))
        return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))[:200]
    except ValueError:
        return "(주소 판독 불가)"


def _not_http(where: str, exc: Exception) -> VNError:
    """HTTP 가 아닌 응답(http.client.HTTPException) → **재시도하지 않는** 안내.

    그 주소에 MakeFun 이 아닌 것이 앉아 있으면(오타난 base_url · 사내 프록시 · TLS 포트에
    평문 요청) 응답 첫 줄이 상태줄이 아니라 ``BadStatusLine`` 이 난다. 그것은 URLError 도
    OSError 도 아니라서 여기서 잡지 않으면 **CLI 로 traceback 이 그대로 샜다**.

    **_Transient 가 아니라 VNError 다 — 다시 보내지 않는다.** 이 예외는 요청을 보낸 *뒤*
    응답을 읽다가 난다. 생성 시작(POST start)은 task 를 만드는 순간 과금되므로, 서버가
    이미 받아 처리했는지 알 수 없는 POST 를 다시 보내면 **한 번 더 청구될 수 있다.**
    사용자가 할 일은 재시도가 아니라 주소 확인이라, 두드린 주소를 문장에 담는다
    (토큰은 담지 않는다 — 안내문은 로그·화면에 그대로 남는다).
    """
    return VNError(f"{where} 에서 HTTP 응답이 아닌 답을 받았습니다 — 그 주소에 MakeFun API 가 "
                   f"아닌 것이 있는 것 같습니다({type(exc).__name__}). "
                   "base_url(매니페스트 image_generator.makefun.api.base_url)을 확인하세요. "
                   "이미 과금됐을 수 있는 요청이라 자동으로 다시 보내지 않습니다.")


def token() -> str:
    t = os.environ.get(TOKEN_ENV, "").strip()
    if not t:
        raise VNError(f"{TOKEN_ENV} 환경변수가 없습니다. makefun.ai Account > API Token 발급 후 "
                      f'PowerShell: $env:{TOKEN_ENV}="sk_..." 로 설정하세요.')
    return t


def _cfg() -> dict:
    """manifest image_generator — 최상위 블록에 ``makefun`` 하위 블록을 덧씌운 한 장의 dict.

    엔진이 둘이 되면서(ComfyUI 기본·MakeFun 보조) MakeFun 전용 설정(model·api·
    max_reference_images·skip_face_enhance)은 ``image_generator.makefun`` 아래로 들어갔다.
    공용 키(max_long_edge_px 등)는 최상위에 남는다. 예전 매니페스트(최상위 api/model)도
    그대로 읽힌다 — 하위 블록이 있으면 그 키가 이기고, 다른 엔진 블록은 섞지 않는다.
    """
    mf = load_json_safe(MANIFEST, {})
    cfg = mf.get("image_generator", {})
    if not isinstance(cfg, dict):
        return {}
    merged = {k: v for k, v in cfg.items() if k not in ("makefun", "comfyui")}
    sub = cfg.get("makefun")
    if isinstance(sub, dict):
        merged.update(sub)
    return merged


def base_url() -> str:
    u = str((_cfg().get("api", {}) or {}).get("base_url", "") or DEFAULT_BASE).rstrip("/")
    if not u.startswith("https://"):
        raise VNError(f"MakeFun base_url 은 https 만 허용합니다: {u}")
    return u


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
    url = base_url() + path       # 아래 안내문이 '어디를 두드렸나'를 말하려면 이름이 필요하다
    req = urllib.request.Request(
        url,
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
    except http.client.HTTPException as e:
        raise _not_http(f"{method} {url}", e) from e
    except OSError as e:
        # URLError(위 절)가 아닌 OSError 는 **요청을 보낸 뒤** 응답을 읽다가 끊긴 것이다
        # (연결 리셋·응답 대기 시간 초과). urllib 은 h.request() 의 오류만 URLError 로
        # 감싸므로 h.getresponse() 단계의 이것들은 그대로 새어 나왔다.
        # 여기서도 **다시 보내지 않는다** — 서버가 이미 받아 처리했는지 알 수 없고,
        # 생성 시작은 task 를 만드는 순간 과금이다.
        raise VNError(f"{method} {url} 의 응답을 받지 못했습니다({type(e).__name__}: {e}). "
                      "요청이 이미 처리됐을 수 있어(생성은 시작하는 순간 과금됩니다) 자동으로 "
                      "다시 보내지 않습니다. --refetch 로 기록된 task 를 다시 받아올 수 있습니다.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise VNError("MakeFun 응답이 JSON 이 아닙니다.")
    if isinstance(data, list):
        # allRecords·creditsHistory 는 스펙에 응답 스키마가 비어 있고 배열을 그대로 주기도 한다.
        # 그 형태를 '오류 응답' 으로 몰지 않고 data 로 감싸 위층의 관대 파싱에 넘긴다.
        return {"code": 0, "data": data}
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
    # 안전장치를 끄지 않는다는 표시는 **여기서** 붙는다. 부르는 쪽마다 챙기게 하면
    # 새 경로를 붙인 사람이 한 번 잊는 것으로 그대로 꺼진다.
    body = with_safety(path, body)
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


# --- 관대 파싱 --------------------------------------------------------------
# 업스케일 상세·크레딧 이력·allRecords 는 **OpenAPI 스펙에 응답 스키마가 비어 있다.**
# 필드명을 하나로 단정하면 이름이 다를 때 조용히 실패하고, 이미 과금된 결과를 잃는다.
# 그래서 후보 이름을 여러 개 시도하되 **전부 실패하면 응답 일부를 담아 오류를 던진다**
# (조용한 실패 금지). 여기 모아 둔 이유는 그 관용 규칙이 한 곳에만 있어야 하기 때문이다.

_ID_FIELDS = ("_id", "id", "task_id", "taskId", "record_id", "recordId",
              "upscale_id", "upscaleId", "job_id", "jobId", "uuid")
_STATUS_FIELDS = ("current_status", "status", "state", "task_status", "job_status")
_URL_FIELDS = ("image_urls", "imageUrls", "result_url", "resultUrl", "result_urls",
               "output_url", "outputUrl", "image_url", "imageUrl", "target_url",
               "cdnUrl", "cdn_url", "output", "url")
_ERR_FIELDS = ("failed_message", "fail_reason", "error", "error_message", "message", "msg")
_LIST_FIELDS = ("list", "records", "items", "rows", "results", "data", "content")

DONE_STATES = ("completed", "complete", "success", "successful", "succeeded", "done", "finished")
FAIL_STATES = ("failed", "failure", "error", "cancelled", "canceled", "rejected", "timeout")


def _trim(obj, limit: int = 300) -> str:
    """응답을 오류 문구에 실을 만큼만 잘라 문자열로. (형태를 모를 때의 유일한 단서)"""
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(obj)
    return text[:limit]


def _as_rec(value) -> dict:
    """dict / [dict] / {"data": {...}} 어느 형태로 와도 레코드 하나로."""
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, dict)), {})
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    """목록 응답 — 배열이거나, 배열을 품은 dict(list/records/items…)거나."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in _LIST_FIELDS:
            v = value.get(key)
            if isinstance(v, list):
                return v
    return []


def _pick(rec: dict, names, skip: str = "") -> str:
    """후보 필드명 중 처음 나오는 비어 있지 않은 문자열(없으면 "")."""
    for n in names:
        v = rec.get(n) if isinstance(rec, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v)
        if isinstance(v, str) and v.strip() and v.strip() != skip:
            return v.strip()
    return ""


def _urls_in(rec: dict, names=_URL_FIELDS, skip: str = "") -> list[str]:
    """레코드에서 결과 이미지 URL 로 보이는 것들 — 문자열이든 배열이든.

    ``skip`` 은 원본 URL 이다. 업스케일 응답은 source_url 을 되돌려 주기도 하는데,
    그걸 결과로 착각하면 **같은 크기의 원본을 받아 놓고 성공으로 표시한다**(가장 나쁜 실패).
    """
    out: list[str] = []
    for n in names:
        v = rec.get(n) if isinstance(rec, dict) else None
        for u in (v if isinstance(v, list) else [v]):
            if not isinstance(u, str):
                continue
            u = u.strip()
            if u.startswith(("https://", "http://")) and u != skip and u not in out:
                out.append(u)
    return out


# --- 이미지 판별 · R2 업로드 --------------------------------------------------
# 매직바이트 판정이 webapp.sniff_image 와 두 벌인 것은 알고 있다. 계층 규약상 이 모듈(3층)은
# webapp(4층)을 import 할 수 없고, 공용 자리인 vn_core 는 이번 작업 범위가 아니다.
# (합칠 자리는 vn_core — 옮길 때 두 곳을 함께 지운다.)
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", (".png",)),
    (b"\xff\xd8\xff", (".jpg", ".jpeg")),
    (b"GIF87a", (".gif",)), (b"GIF89a", (".gif",)),
    (b"II*\x00", (".tif", ".tiff")), (b"MM\x00*", (".tif", ".tiff")),
)
_CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webp": "image/webp", ".gif": "image/gif",
                  ".tif": "image/tiff", ".tiff": "image/tiff"}


def sniff_image(raw: bytes) -> tuple | None:
    """파일 앞머리로 실제 이미지 형식을 판정 → 확장자 후보(첫 번째가 대표). 아니면 None."""
    for sig, exts in _MAGIC:
        if raw.startswith(sig):
            return exts
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return (".webp",)
    return None


def _content_type(path: Path, raw: bytes, given: str | None) -> str:
    if given:
        return str(given)
    ext = path.suffix.lower()
    real = sniff_image(raw)
    if real:                                  # 내용이 우선 — 이름은 틀릴 수 있다
        return _CONTENT_TYPES.get(real[0], "application/octet-stream")
    return (_CONTENT_TYPES.get(ext) or mimetypes.guess_type(path.name)[0]
            or "application/octet-stream")


def _put_once(url: str, data: bytes, content_type: str, timeout: int) -> int:
    """presigned URL 에 파일 바이트를 올린다(PUT). **토큰 헤더를 붙이지 않는다.**"""
    req = urllib.request.Request(url, data=data, method="PUT",
                                 headers={"Content-Type": content_type,
                                          "Content-Length": str(len(data))})
    try:
        with _UP.open(req, timeout=timeout) as r:
            return int(getattr(r, "status", 0) or 0)
    except urllib.error.HTTPError as e:
        if e.code in RETRY_CODES:
            raise _Transient(f"업로드 HTTP {e.code}", e.code, _retry_after(e.headers))
        if e.code in (401, 403):
            raise VNError(f"업로드가 거부됐습니다(HTTP {e.code}) — 서명 URL 이 만료됐거나 "
                          f"Content-Type 이 발급 때와 다릅니다.")
        raise VNError(f"업로드 HTTP {e.code}")
    except urllib.error.URLError as e:
        raise _Transient(f"업로드 연결 실패: {e.reason}", None, None, True)
    except http.client.HTTPException as e:
        raise _not_http(f"업로드(PUT {_host_of(url)})", e) from e
    except OSError as e:
        # 같은 key 에 같은 바이트를 다시 올리는 것은 멱등이라 재시도로 돌린다(과금 없음).
        raise _Transient(f"업로드 전송 중 끊김: {type(e).__name__}", None, None, False)


def _put_bytes(url: str, data: bytes, content_type: str, quiet: bool = True) -> int:
    """PUT + 지수 백오프 재시도. 같은 key 에 같은 바이트를 다시 올리는 것은 안전하다(멱등)."""
    for attempt in range(RETRY_MAX + 1):
        try:
            return _put_once(url, data, content_type, 180)
        except _Transient as e:
            if attempt >= RETRY_MAX:
                raise VNError(str(e)) from e
            delay = _backoff(attempt, e.retry_after)
            _say(f"  업로드 일시 오류 — {delay:.0f}초 후 재시도 {attempt + 1}/{RETRY_MAX}", quiet)
            time.sleep(delay)
    raise VNError("업로드 재시도 한도를 초과했습니다.")   # 도달하지 않음(방어)


def _presign(key: str, content_type: str, size: int, quiet: bool = True) -> tuple[str, str]:
    """업로드용 서명 URL 발급 → (uploadUrl, cdnUrl)."""
    body = {"key": key, "contentType": content_type, "fileSize": size, "contentLength": size}
    d = _call("POST", P_R2_PRESIGN, body, quiet=quiet)      # 발급 자체는 멱등(재시도 안전)
    rec = _as_rec(d.get("data")) or (d if isinstance(d, dict) else {})
    up = _pick(rec, ("uploadUrl", "upload_url", "presignedUrl", "presigned_url",
                     "signedUrl", "signed_url", "putUrl", "url"))
    cdn = _pick(rec, ("cdnUrl", "cdn_url", "publicUrl", "public_url", "fileUrl",
                      "file_url", "downloadUrl", "url"), skip=up)
    if not up or not cdn:
        raise VNError("업로드 URL 을 받지 못했습니다(uploadUrl/cdnUrl 없음) — 응답: " + _trim(d))
    if not up.startswith("https://") or not cdn.startswith("https://"):
        # 서명 URL 로 파일을 보내고 그 주소를 다시 생성 API 에 넘기는 경로다. 평문 http 는 쓰지 않는다.
        raise VNError(f"https 가 아닌 업로드 주소를 거부했습니다: {up[:60]} / {cdn[:60]}")
    return up, cdn


def upload_file(path: Path | str, *, content_type: str | None = None, quiet: bool = True) -> str:
    """로컬 파일 → R2 업로드 → **공개 CDN URL**. (업스케일·레퍼런스가 URL 만 받기 때문에 전제다)

    key 에 내용 해시를 넣는다 — 같은 파일을 다시 올려도 같은 주소가 되어 스토리지가
    복사본으로 불어나지 않는다.

    이미지가 아닌 파일은 ``content_type`` 을 명시해야 올라간다. 오타 하나로 매니페스트나
    설정 파일이 남의 CDN 에 공개되는 사고를 막는 관문이다(이 저장소는 키·사적 자산을 다룬다).
    """
    p = Path(str(path)).expanduser()
    if not p.is_file():
        raise VNError(f"올릴 파일이 없습니다: {p}")
    size = p.stat().st_size
    if size <= 0:
        raise VNError(f"빈 파일은 올릴 수 없습니다: {p.name}")
    if size > UP_CAP:
        raise VNError(f"파일이 너무 큽니다({size / 1_000_000:.1f}MB > {UP_CAP // 1_000_000}MB): {p.name}")
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise VNError(f"{p.name} 읽기 실패: {exc}") from exc
    real = sniff_image(raw)
    ext = p.suffix.lower()
    if real is None and not content_type:
        raise VNError(f"이미지 파일이 아닙니다({p.name}) — 이미지가 아닌 파일을 올리려면 "
                      f"content_type 을 명시하세요.")
    if real and ext in IMAGE_EXTS and ext not in real:
        raise VNError(f"파일 내용과 확장자가 다릅니다({p.name}: 내용 {real[0]}, 이름 {ext}).")
    ctype = _content_type(p, raw, content_type)
    key = (f"{UPLOAD_PREFIX}/{safe_slug(p.stem, 'file')}-"
           f"{hashlib.sha1(raw).hexdigest()[:12]}{ext or (real[0] if real else '')}")
    up, cdn = _presign(key, ctype, size, quiet=quiet)
    _put_bytes(up, raw, ctype, quiet=quiet)
    _say(f"  업로드 완료 {p.name} → {cdn}", quiet)
    log_usage({"kind": "upload", "billable": False, "ok": True, "file": p.name,
               "bytes": size, "url": cdn})
    return cdn


# --- 생성 크기(19) ----------------------------------------------------------

def _cap_px() -> int:
    """허용 상한 — 인화용 큰 값은 manifest image_generator.max_long_edge_px 로 올린다."""
    try:
        v = int(_cfg().get("max_long_edge_px", SIZE_MAX_PX) or SIZE_MAX_PX)
    except (TypeError, ValueError):
        v = SIZE_MAX_PX
    return max(SIZE_MIN_PX, min(v, SIZE_HARD_MAX_PX))


def _align8(px: int) -> int:
    """8의 배수 정렬 — 긴 변은 '최소' 요구라 올림하되 상한은 넘지 않는다.

    상한이 8의 배수가 아니면 **내려서** 자른다(2250 → 2248). 그래서 상한을 올리라는 권고는
    8의 배수여야 실행 가능하다(size_warnings 가 gen_common.align_up 으로 올려 말한다).
    """
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


def size_recipe(long_px: int) -> dict:
    """긴 변 long_px 를 이 엔진으로 뽑으려면 매니페스트에서 무엇을 얼마로 바꿔야 하는가.

    두 클라이언트의 공용 계약이다(comfyui_client.size_recipe 와 같은 키) — 인화 도구와 doctor 가
    엔진을 모르는 채로 "무엇을 올려라" 를 그대로 옮겨 적을 수 있어야 한다. MakeFun 에는 hires
    2배 상한이 없으므로 조치는 두 값뿐이고 hires_note 는 항상 빈 문자열이다.
    """
    want = max(SIZE_MIN_PX, int(long_px))
    edits: list[tuple[str, int]] = []
    out = load_json_safe(MANIFEST, {}).get("output", {})
    try:
        cur_min = int((out or {}).get("min_long_edge_px", DEFAULT_LONG_EDGE) or DEFAULT_LONG_EDGE)
    except (TypeError, ValueError):
        cur_min = DEFAULT_LONG_EDGE
    if cur_min < want:
        edits.append(("output.min_long_edge_px", want))
    if _cap_px() // 8 * 8 < want:               # 상한은 8의 배수로 내려서 자른다(2250 → 2248)
        edits.append(("image_generator.max_long_edge_px", gen_common.align_up(want)))
    return {"want": want, "reachable": not edits, "edits": edits, "hires_note": "",
            "feasible": want <= SIZE_HARD_MAX_PX, "engine": "makefun"}


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
    # 권고값은 8의 배수로 올린다 — 상한 자체가 8의 배수로 **내려** 잘리므로(cap 2250 → 2248)
    # 요청값을 그대로 권하면 "이미 그 값인데 올리라"가 되고, 고쳐도 다시 깎이고 돈만 쓴다.
    need = gen_common.align_up(plan["want"])
    msgs = [f"요청 {plan['want']}px({plan.get('source', '')}) → 실제 {plan['long']}px "
            f"— 상한 {plan['cap']}px 에 깎였습니다. 과금은 요청대로 됩니다. "
            f"매니페스트 image_generator.max_long_edge_px 를 {need} 이상(8의 배수)으로 "
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
    """종량제 비용 추적용 append-only 대장(17) — logs/makefun_usage.jsonl 고정.

    쓰기 자체는 gen_common 이 한다(ComfyUI 대장과 같은 형식·같은 잠금). 파일이 엔진마다
    다른 이유는 유료·무료 기록을 한 파일에 섞으면 과금 합산이 어긋나기 때문이다.
    """
    gen_common.log_usage(USAGE_LOG, record)


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


# --- 레퍼런스 이미지(input_images) --------------------------------------------
# 컷마다 얼굴이 흔들리는 1차 원인은 프롬프트가 아니라 **레퍼런스 미첨부**다. text2image 에는
# 처음부터 input_images 파라미터가 있었는데 우리가 보내지 않고 있었다(매니페스트의
# reference_images 도 빈 배열이라 보낼 것도 없었다).
# 레퍼런스는 URL 이어야 한다 — 로컬 파일이면 upload_file 로 올려서 URL 로 바꿔 보낸다.
# **매니페스트에 되쓰지 않는다**: 그 파일을 쓰는 것은 이 모듈의 일이 아니다(scene_ops 규약과 같다).

def _ref_cap() -> int:
    """모델이 허용하는 레퍼런스 장수 — A2E 2장, Seedream 5.0 Pro 10장."""
    model = str(_cfg().get("model", "") or "a2e").lower()
    cap = REF_MAX_SEEDREAM if "seedream" in model else REF_MAX_A2E
    try:
        cap = int(_cfg().get("max_reference_images", cap) or cap)
    except (TypeError, ValueError):
        pass
    return max(0, min(cap, REF_MAX_SEEDREAM))


def _ref_to_url(ref, upload: bool, quiet: bool) -> str:
    """레퍼런스 한 항목 → URL. 로컬 파일이면 올려서 URL 로. 실패는 건너뛴다(생성은 계속)."""
    text = str(ref or "").strip()
    if not text:
        return ""
    if text.startswith("https://"):
        return text
    if text.startswith("http://"):
        log.warning("레퍼런스가 평문 http 입니다 — 그대로 보냅니다: %s", text[:80])
        return text
    if not upload:
        return ""
    try:
        # 고유 캐릭터의 사진은 **저장소 밖**(비공개 폴더)에 있을 수 있다. 그 자리를 아는
        # 곳은 characters 하나뿐이라 먼저 물어본다 — 여기서 뿌리에 이어 붙이면
        # 비공개 폴더를 켠 순간 이 경로만 조용히 사진을 못 찾는다.
        got = None
        try:
            import characters                                  # noqa: PLC0415 (계층 1)
            got = characters.resolve_ref(text)
        except Exception:                                      # 그 모듈이 없어도 예전대로 돈다
            got = None
        p = got if got is not None else Path(text).expanduser()
        # 저장소 상대경로는 밖으로 나가지 못하게 걸러서 연다(매니페스트도 결국 데이터다).
        if got is None:
            p = p if p.is_absolute() else safe_path(ROOT, text)
        return upload_file(p, quiet=quiet)
    except (RuntimeError, OSError) as exc:
        log.warning("레퍼런스 업로드 실패 — 이 장은 빼고 생성합니다: %s (%s)", text[:80], exc)
        return ""


def reference_urls(character_ids: list, *, limit: int = 2,
                   upload: bool = True, quiet: bool = True) -> list[str]:
    """매니페스트 characters[].reference_images → 보낼 수 있는 URL 목록(최대 limit 개).

    로컬 경로는 R2 에 올려 URL 로 바꾼다. 매니페스트는 고치지 않는다 — 필요하면 호출부가
    이 반환값을 보고 직접 기록한다.
    """
    ids = [str(c).strip() for c in (character_ids or []) if str(c or "").strip()]
    if not ids or limit <= 0:
        return []
    chars = load_json_safe(MANIFEST, {}).get("characters")
    index = {str(c.get("character_id", "")): c
             for c in (chars if isinstance(chars, list) else []) if isinstance(c, dict)}
    out: list[str] = []
    for cid in ids:
        refs = (index.get(cid) or {}).get("reference_images")
        for ref in (refs if isinstance(refs, list) else []):
            if len(out) >= limit:
                return out
            url = _ref_to_url(ref, upload, quiet)
            if url and url not in out:
                out.append(url)
    return out[:limit]


def _clean_refs(urls, quiet: bool = True) -> list[str]:
    """보낼 input_images 를 모델 상한까지만 — 넘치면 조용히 자르지 않고 알린다."""
    cap = _ref_cap()
    seen: list[str] = []
    for u in (urls or []):
        u = str(u or "").strip()
        if u.startswith(("https://", "http://")) and u not in seen:
            seen.append(u)
    if len(seen) > cap:
        _say(f"  레퍼런스 {len(seen)}장 중 {cap}장만 보냅니다 "
             f"(모델 {_cfg().get('model', '') or 'a2e'} 상한).", quiet)
    return seen[:cap]


def scene_reference_urls(sc: dict, quiet: bool = True) -> list[str]:
    """장면에 등장하는 캐릭터의 레퍼런스 URL — 실패해도 생성을 막지 않는다."""
    try:
        chars = sc.get("characters") if isinstance(sc, dict) else []
        return reference_urls(chars if isinstance(chars, list) else [],
                              limit=_ref_cap(), quiet=quiet)
    except (RuntimeError, OSError) as exc:
        log.warning("레퍼런스 준비 실패 — 레퍼런스 없이 생성합니다: %s", exc)
        return []


# --- 생성 · 폴링 · 다운로드 --------------------------------------------------

def t2i_body(prompt: str, n: int = 1, name: str = "",
             long_edge: int | None = None, negative: bool = True, quiet: bool = True,
             input_images=None) -> dict:
    """text2image 요청 본문 한 벌.

    **견적과 생성이 같은 본문을 써야 한다.** 견적은 "이 요청이 얼마냐" 를 묻는 것인데,
    본문을 두 곳에서 따로 만들면 물어본 것과 보낸 것이 달라지고 숫자는 조용히 틀린다.
    """
    plan = size_plan(long_edge)
    w, h = plan["width"], plan["height"]
    for msg in size_warnings(plan):
        _say("  ⚠ 생성 크기 — " + msg, quiet)
    body = {"prompt": apply_negative(prompt, negative), "width": w, "height": h,
            "model_type": str(_cfg().get("model", "") or "a2e"),
            "max_images": max(1, min(int(n), 4))}
    if name:
        body["name"] = name
    refs = _clean_refs(input_images, quiet)
    if refs:
        body["input_images"] = refs
        # 얼굴 유사도 보정은 기본 켜짐(false)이 레퍼런스의 목적에 맞다. 끄고 싶은 사람만
        # 매니페스트 image_generator.skip_face_enhance 로 끈다.
        if _cfg().get("skip_face_enhance"):
            body["skip_face_enhance"] = True
        _say(f"  레퍼런스 {len(refs)}장 첨부", quiet)
    return body


def quote_enabled() -> bool:
    """견적을 물어봐도 되는가 — **기본은 아니다.**

    과금되지 않는 경로지만 그래도 **바깥 서버를 두드리는 일**이고, 이 저장소의 규칙은
    MakeFun 에 대해 '모의만' 이다. 사람이 매니페스트에서 켜야 실제로 물어본다:
    ``image_generator.makefun.quote: true``
    """
    return bool(_cfg().get("quote"))


def quote(endpoint: str, request_body: dict, quiet: bool = True) -> dict:
    """생성 전 견적 — 명세상 **과금되지 않는다**(작업도 안 만들고 공급자도 안 부른다).

    응답 스키마가 명세에 비어 있다({"type":"object"}). 그래서 필드 이름을 단정하지 않고
    **받은 것을 그대로** 돌려준다 — 잔액 조회와 같은 규칙이다. 화면은 :func:`quote_numbers`
    로 뽑아 **필드명째** 보여 준다. 모르는 응답에 이름을 붙이면 그 순간부터 그 이름이
    사실인 척한다.

    명세 주의 문구도 그대로 옮긴다: 가격 관련 필드만 해석되며, 견적이 성공했다고 해서
    생성 요청 전체가 유효하다는 뜻은 아니다.
    """
    path = str(endpoint or "").strip()
    if path.upper().startswith("POST "):
        path = path[5:].strip()
    if not path.startswith("/"):
        raise VNError(f"견적 대상 경로가 이상합니다: {endpoint!r}")
    if not isinstance(request_body, dict):
        raise VNError("견적에는 보낼 요청 본문이 그대로 필요합니다.")
    return _call("POST", P_QUOTE, {"endpoint": path, "requestBody": request_body},
                 idempotent=True, quiet=quiet)


def quote_numbers(resp) -> list:
    """견적 응답 → [(필드 이름, 값)] — **숫자인 것만, 이름을 붙이지 않고.**

    어느 필드가 '장당 크레딧' 인지 이 코드는 모른다. 모르는 것을 아는 척하면 화면에
    그럴듯한 거짓이 뜨고, 사람은 그걸 믿고 돈 쓰는 결정을 한다. 그래서 이름째 보여 준다.
    """
    out: list = []

    def walk(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}.{k}" if prefix else str(k))
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            out.append((prefix or "값", node))

    walk(resp.get("data") if isinstance(resp, dict) and "data" in resp else resp)
    return out[:12]


def quote_text2image(prompt: str, n: int = 1, **kw) -> dict:
    """'이 장면을 이 설정으로 구우면 얼마인가' — 보낼 본문 그대로 물어본다."""
    body = t2i_body(prompt, n=n, **kw)
    raw = quote(P_T2I_START, body)
    inner = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw
    # 명세가 이름을 확정해 준 **유일한** 필드다:
    #   "generationRequestValidated=false means only pricing inputs were checked."
    # 즉 견적이 나왔다고 해서 그 생성 요청이 통과한다는 보장은 아니다 — 화면이 그걸 말해야
    # 사람이 "견적이 됐으니 되겠지" 로 읽지 않는다.
    validated = inner.get("generationRequestValidated") if isinstance(inner, dict) else None
    return {"endpoint": P_T2I_START, "numbers": quote_numbers(raw),
            "validated": validated if isinstance(validated, bool) else None, "raw": raw}


def start(prompt: str, n: int = 1, name: str = "",
          long_edge: int | None = None, negative: bool = True, quiet: bool = True,
          input_images=None) -> list[str]:
    """생성 시작 → task id 목록. 요청 크기가 상한에 깎이면 과금 전에 알린다.

    input_images 는 캐릭터 레퍼런스 URL(모델 상한까지만 실린다 — A2E 2장).
    """
    body = t2i_body(prompt, n=n, name=name, long_edge=long_edge, negative=negative,
                    quiet=quiet, input_images=input_images)
    d = _call("POST", P_T2I_START, body, idempotent=False, quiet=quiet)
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
            d = _call("GET", P_T2I_TASK + task_id, timeout=30, quiet=quiet)
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


def video_body(image_url: str, prompt: str = "", *, seconds: int = 5,
               model_version: str = "", negative: bool = True, end_image_url: str = "",
               quiet: bool = True) -> dict:
    """userImage2Video 요청 본문 한 벌.

    **model_version 을 반드시 실어 보낸다.** 명세 원문이 이렇다: *"Ultra users default to
    a2e-v2 and other roles default to a2e. a2e-v2 costs more per second; a2e-v2-flash uses
    a2e pricing."* 즉 값을 비우면 **계정 등급에 따라 단가가 달라진다** — 같은 버튼을 눌러도
    사람마다 다른 돈이 나가고, 그건 화면이 무엇을 약속해도 지킬 수 없다는 뜻이다.
    """
    src = str(image_url or "").strip()
    if not src.startswith("https://"):
        raise VNError(f"https 가 아닌 주소는 영상 원본으로 쓸 수 없습니다: {src[:80]}")
    try:
        secs = int(seconds)
    except (TypeError, ValueError):
        secs = 5
    if secs not in VIDEO_TIMES:
        # 명세는 min/max 만 걸고 5·10·15·20 은 설명에만 있다. 그 사이 값(7초)을 서버가
        # 어떻게 처리하는지는 미정의라, **가까운 허용값으로 내린다**(올리면 돈이 더 든다).
        allowed = [t for t in VIDEO_TIMES if t <= max(5, min(secs, 20))]
        secs = allowed[-1] if allowed else 5
        _say(f"  영상 길이를 {secs}초로 맞춥니다(허용: {', '.join(map(str, VIDEO_TIMES))}).", quiet)
    ver = str(model_version or _cfg().get("video_model", "") or "a2e").strip()
    if ver not in VIDEO_MODELS:
        raise VNError(f"모르는 영상 모델입니다: {ver!r} (가능: {', '.join(VIDEO_MODELS)})")
    body = {"image_url": src, "video_time": secs, "model_version": ver,
            "number_of_images": 1}
    text = str(prompt or "").strip()
    if text:
        body["prompt"] = apply_negative(text, negative) if negative else text
    tail = str(end_image_url or "").strip()
    if tail:
        body["model_type"] = "FLF2V"      # 첫 컷 → 끝 컷 보간
        body["end_image_url"] = tail
    return body


_VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v")


def video_urls_in(rec, skip: str = "") -> list:
    """영상 응답에서 **결과처럼 생긴 주소**를 모은다 — 필드 이름이 아니라 값으로 찾는다.

    다른 경로는 이름으로 찾아도 된다(`_urls_in`). 여기는 그럴 수가 없다 — 이 경로의 응답
    스키마가 명세에 통째로 비어 있어서, 우리가 아는 이름 목록에 결과가 들어 있으리라는
    근거가 없다. 그래서 값을 훑는다.

    두 가지를 조심한다:
      * **보낸 그림이 그대로 돌아올 수 있다.** 그걸 결과로 착각하면 영상 대신 원본 png 를
        내려받아 mp4 라는 이름으로 저장한다 — 사람은 돈을 내고 원본을 돌려받는다.
      * 영상 확장자를 **앞**에 둔다. 섬네일 같은 것이 같이 와도 첫 번째가 영상이 되도록.
    """
    out: list = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            u = node.strip()
            if u.startswith("https://") and u not in out and u != str(skip or "").strip():
                out.append(u)

    walk(rec)
    vids = [u for u in out if u.lower().split("?")[0].endswith(_VIDEO_EXT)]
    return vids + [u for u in out if u not in vids]


def video_start(image_url: str, prompt: str = "", **kw) -> str:
    """영상 생성 시작 → 작업 id. **유료 호출이다.**

    응답 스키마가 명세에 비어 있어 id 가 어느 필드인지 모른다. 관용 파서로 찾고,
    **못 찾으면 응답을 담아 던진다** — 조용히 실패하면 이미 과금된 작업을 영영 못 찾는다.
    그리고 첫 호출의 응답을 통째로 로그에 남긴다: 그 한 번이 이 미지를 끝낸다.
    """
    quiet = bool(kw.pop("quiet", True))
    body = video_body(image_url, prompt, quiet=quiet, **kw)
    d = _call("POST", P_I2V_START, body, idempotent=False, quiet=quiet)
    log.info("영상 시작 응답(원문 일부) — 형식 확인용: %s", _trim(d, 400))
    if d.get("success") is False:
        raise VNError("영상 생성 시작이 거부됐습니다 — 응답: " + _trim(d))
    rec = _as_rec(d.get("data"))
    vid = _pick(rec, _ID_FIELDS) or _pick(d, _ID_FIELDS)
    if not vid:
        raise VNError("영상 작업 id 를 찾지 못했습니다(명세에 응답 스키마가 없습니다) — "
                      "응답 원문: " + _trim(d, 300))
    return _uid_ok(vid)


def video_result(vid: str, max_sec: int = 900, quiet: bool = True,
                 source_url: str = "") -> dict:
    """영상 작업을 기다렸다가 결과 → {id, status, urls, raw}.

    mp4 URL 이 어느 필드인지도 명세에 없다. 그래서 **URL 처럼 생긴 것을 전부 모아** 돌려주고,
    고르는 것은 부르는 쪽에 맡긴다. 다 끝났는데 URL 이 하나도 없으면 조용히 빈손으로
    돌아가지 않고 응답을 담아 던진다 — 이미 돈이 나갔기 때문이다.
    """
    vid = _uid_ok(vid)
    deadline = time.time() + max(30, int(max_sec))
    last: dict = {}
    while True:
        try:
            d = _call("GET", P_I2V_TASK + urllib.parse.quote(vid), timeout=30, quiet=quiet)
            rec = _as_rec(d.get("data")) or (d if isinstance(d, dict) else {})
        except VNError as exc:
            log.warning("영상 상세 조회 실패 — 목록으로 넘어갑니다: %s", exc)
            rec = {}
        if not rec:
            d = _call("GET", P_I2V_RECORDS + "?pageNum=1&pageSize=50", timeout=30, quiet=quiet)
            for it in _as_list(d.get("data")) or _as_list(d):
                if isinstance(it, dict) and _pick(it, _ID_FIELDS) == vid:
                    rec = it
                    break
        last = rec or last
        st = _pick(rec, _STATUS_FIELDS).lower()
        urls = video_urls_in(rec, skip=source_url)
        if st in ("completed", "success", "succeeded", "done", "finished") or (urls and not st):
            if not urls:
                raise VNError("영상이 끝났다는데 결과 주소가 없습니다(명세에 응답 스키마가 "
                              "없습니다) — 응답 원문: " + _trim(rec, 300))
            log.info("영상 완료 응답(원문 일부) — 형식 확인용: %s", _trim(rec, 400))
            return {"id": vid, "status": st or "completed", "urls": urls, "raw": rec}
        if st in ("failed", "error", "cancelled", "canceled"):
            raise VNError(f"영상 생성이 실패했습니다(작업 {vid}) — 응답: " + _trim(rec, 200))
        if time.time() > deadline:
            raise VNError(f"영상이 제한 시간 안에 끝나지 않았습니다(작업 {vid}). "
                          "돈은 이미 나갔으므로 이 id 로 나중에 결과를 받을 수 있습니다.")
        time.sleep(POLL_SEC)


def video_for_scene(scene_id: str, *, seconds: int = 5, prompt: str = "",
                    model_version: str = "", quiet: bool = True) -> dict:
    """장면의 **고른 컷**으로 영상 한 편 → 저장 경로와 주소.

    고른 컷만 쓰는 이유: 후보 중 무엇을 쓸지는 사람이 정하는 일이고(승인 게이트),
    영상은 유료다 — 고르지 않은 컷으로 돈을 쓰면 그 돈은 사람이 시킨 적이 없다.

    컷은 **밖으로 나간다.** 공급자가 URL 만 받으므로 R2 에 먼저 올려야 하고, 그 컷에는
    사람 얼굴이 들어 있을 수 있다(PhotoMaker 로 얼굴을 고정했다면 실존 인물의 얼굴이다).
    그래서 부르는 쪽이 사람에게 먼저 묻는다 — 이 함수는 묻지 않는다(부르면 나간다).

    응답 형식이 명세에 없어 **첫 호출의 원문을 로그에 남긴다.** 그 한 번으로 확정된다.
    """
    started = now_iso()          # 소비 기록 조회의 시작 경계(명세: startDate 는 포함 경계)
    sc = _load_scene(scene_id)
    rel = selected_of(sc)
    if not rel:
        raise VNError(f"{scene_id} 에 고른 컷이 없습니다 — 먼저 후보 중 하나를 고르세요.")
    src = ROOT / rel
    if not src.is_file():
        raise VNError(f"고른 컷 파일이 없습니다: {rel}")
    url = upload_file(src, quiet=quiet)
    vid, err, saved = "", "", None
    try:
        vid = video_start(url, prompt or str(sc.get("purpose", "") or ""),
                          seconds=seconds, model_version=model_version, quiet=quiet)
        got = video_result(vid, quiet=quiet, source_url=url)
        out_dir = RAW_DIR / scene_id / "video"
        out_dir.mkdir(parents=True, exist_ok=True)
        data = _fetch_bytes(got["urls"][0], 300)
        saved = out_dir / f"mf_{vid[-6:]}.mp4"
        saved.write_bytes(data)
    except VNError as exc:
        err = str(exc)[:300]
        raise
    finally:
        # 대장은 성공·실패 둘 다 남긴다. 실패해도 **돈은 이미 나갔을 수 있고**, 그때
        # 남은 작업 id 하나가 재과금 없이 결과를 되찾는 유일한 단서다.
        log_usage({"kind": "image2video", "scene_id": scene_id, "task_id": vid,
                              "requested": 1, "saved": 1 if saved else 0,
                              "ok": bool(saved), "model": model_version or "a2e",
                              "seconds": seconds, "billable": True, "error": err})
        # 얼마가 실제로 나갔는지 **잰다**. 실패 뒤에도 재는 이유: 실패도 과금되는지는
        # 공급자가 말해 주지 않고, 이 기록으로만 알 수 있다.
        record_spend("image2video", scene_id, started,
                     {"seconds": seconds, "task_id": vid, "gen_ok": bool(saved)})
    return {"scene_id": scene_id, "task_id": vid, "seconds": seconds,
            "file": saved.relative_to(ROOT).as_posix()}


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
    except http.client.HTTPException as e:
        raise _not_http(f"결과 다운로드({_host_of(url)})", e) from e
    except OSError as e:
        # 이미 과금된 결과를 받는 중이다 — 끊겼다고 포기하면 돈만 날아간다. 재시도로 돌린다.
        raise _Transient(f"결과 다운로드 중 끊김: {type(e).__name__}", None, None, False)
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
                    scene_id: str = "", on_progress=None, quiet: bool = False,
                    input_images=None) -> GenResult:
    """생성→대기→다운로드. 일부만 성공해도 저장된 파일과 경고를 함께 돌려준다(11)."""
    out_dir = Path(out_dir)
    sent = apply_negative(prompt, negative)
    plan = size_plan(long_edge)
    w, h = plan["width"], plan["height"]
    model = str(_cfg().get("model", "") or "a2e")
    refs = _clean_refs(input_images, quiet=True)   # 기록용(실제 첨부는 start 가 같은 규칙으로)
    # 크기 경고는 start() 가 출력한다. 여기서는 호출부(웹·CLI)가 그대로 볼 수 있게 결과에 싣되,
    # 실패 메시지에는 섞지 않는다(실패 사유가 긴 안내문에 묻히지 않게).
    size_warns: list[str] = list(size_warnings(plan))
    warns: list[str] = []
    capped = {"capped": True, "want_px": plan["want"], "cap_px": plan["cap"]} if plan["capped"] else {}
    spend_from = now_iso()        # 굽기 **전** 시각 — 이 뒤의 소비만 이번 호출의 몫이다
    task_ids = start(sent, n=n, name=name, long_edge=long_edge, negative=False, quiet=quiet,
                     input_images=refs)
    if scene_id:
        record_tasks(scene_id, task_ids, w, h)   # 다운로드 전에 남겨야 유실 시 재수령이 가능하다(10)
    saved: list[Path] = []
    for tid in task_ids:
        try:
            urls = wait(tid, on_progress=on_progress, quiet=quiet)
        except RuntimeError as e:
            warns.append(f"작업 {tid[-6:]}: {e}")
            log_usage({"kind": "text2image", "scene_id": scene_id, "task_id": tid,
                       "requested": n, "saved": 0, "refs": len(refs),
                       "ok": False, "model": model, "width": w, "height": h,
                       "billable": True, "error": str(e)[:200], **capped})
            write_gen_meta(out_dir, {"created_at": _now(), "scene_id": scene_id, "task_id": tid,
                                     "kind": "text2image", "input_images": refs,
                                     "prompt": sent, "model": model, "width": w, "height": h,
                                     "files": [], "status": "failed", "error": str(e)[:200],
                                     **capped})
            continue
        files, w2 = _download_all(tid, urls, out_dir, quiet)
        saved += files
        warns += w2
        log_usage({"kind": "text2image", "scene_id": scene_id, "task_id": tid,
                   "requested": n, "saved": len(files), "refs": len(refs),
                   "ok": bool(files) and not w2, "model": model, "width": w, "height": h,
                   "billable": True, "error": "; ".join(w2)[:200], **capped})
        write_gen_meta(out_dir, {"created_at": _now(), "scene_id": scene_id, "task_id": tid,
                                 "kind": "text2image", "input_images": refs,
                                 "prompt": sent, "model": model, "width": w, "height": h,
                                 "files": [f.name for f in files], **capped,
                                 "status": "ok" if files and not w2 else ("partial" if files else "failed"),
                                 "error": "; ".join(w2)[:200]})
    # 얼마가 실제로 나갔는지 **잰다**(호출 한 번에 한 줄). 공급자가 장당 단가를 공개하지
    # 않으므로 이 기록이 화면에 숫자를 띄울 수 있는 유일한 근거가 된다.
    record_spend("text2image", scene_id, spend_from,
                 {"requested": n, "model": model, "width": w, "height": h,
                  "gen_ok": bool(saved)})
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
    log_usage({"kind": "refetch", "scene_id": scene_id, "task_id": task_id,
               "requested": len(urls), "saved": len(saved),
               "ok": bool(saved) and not warns, "model": str(_cfg().get("model", "") or "a2e"),
               "billable": False, "refetch": True, "error": "; ".join(warns)[:200]})
    write_gen_meta(out_dir, {"created_at": _now(), "scene_id": scene_id, "task_id": task_id,
                             "kind": "refetch",
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
                       negative: bool = True, on_progress=None, quiet: bool = False,
                       reference: bool = True) -> GenResult:
    """장면의 이미지 프롬프트로 생성해 images/raw/<scene>/ 에 저장.

    reference=True(기본)면 등장 캐릭터의 매니페스트 레퍼런스를 함께 보낸다 — 컷마다 얼굴이
    흔들리지 않게 하는 1차 수단이다. 레퍼런스가 없거나 준비에 실패하면 그냥 없이 생성한다.
    """
    p = _scene_path(scene_id)
    if not p.exists():
        raise VNError(f"장면 파일이 없습니다: {scene_id}")
    sc = _load_scene(scene_id)
    prompt = str((sc.get("prompt", {}) or {}).get("grok_output", "")).strip()
    if not prompt:
        raise VNError(f"{scene_id} 에 이미지 프롬프트가 없습니다. 먼저 프롬프트를 생성하세요.")
    refs = scene_reference_urls(sc, quiet=quiet) if reference else []
    return generate_to_dir(prompt, RAW_DIR / p.stem, n=n, name=scene_id, long_edge=long_edge,
                           negative=negative, scene_id=scene_id, on_progress=on_progress,
                           quiet=quiet, input_images=refs)


# --- 업스케일: 재생성 없이 인화 규격으로 --------------------------------------
# 왜 이 경로가 있나: 승인된 컷 7장이 1200×1800 이라 300DPI 인화는 엽서(4×6)가 한계다.
# min_long_edge_px 를 올려 **다시 만들면** 그림이 달라지고(사람이 승인한 그 컷이 아니다)
# 과금도 7장분이 다시 든다. 업스케일은 같은 그림의 픽셀만 키운다 — 2400×3600 이면 8×10 이다.
#
# 응답 스키마가 스펙에 비어 있어 파싱은 관대하게 하되(위 _pick/_urls_in), **모르는 형태면
# 조용히 실패하지 않고 응답 일부를 담아 던진다.** 업스케일도 과금이라 조용한 실패가 곧 손실이다.

def _uid_ok(uid: str) -> str:
    """작업 id 를 URL 경로에 넣기 전 관문 — 경로 탈출·이상한 값이 섞이면 여기서 막는다."""
    uid = str(uid or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", uid):
        raise VNError(f"업스케일 작업 id 형식이 올바르지 않습니다: {uid[:60]!r}")
    return uid


def upscale_start(source_url: str, name: str = "", quiet: bool = True) -> str:
    """업스케일 시작 → 작업 id. (유료 호출이므로 재시도는 '확실히 실패한' 경우만)"""
    src = str(source_url or "").strip()
    if not src.startswith("https://"):
        raise VNError(f"https 가 아닌 원본 URL 은 업스케일에 쓸 수 없습니다: {src[:80]}")
    body = {"source_url": src}
    if name:
        body["name"] = name
    d = _call("POST", P_UPSCALE_START, body, idempotent=False, quiet=quiet)
    if d.get("success") is False:      # 이 API 는 code 대신 success 로 실패를 알린다
        raise VNError("업스케일 시작이 거부됐습니다 — 응답: " + _trim(d))
    rec = _as_rec(d.get("data"))
    uid = _pick(rec, _ID_FIELDS) or _pick(d, _ID_FIELDS)
    if not uid:
        raise VNError("업스케일 작업 id 를 찾지 못했습니다 — 응답: " + _trim(d))
    return _uid_ok(uid)


def _upscale_record(uid: str, use_records: bool, quiet: bool) -> tuple[dict, bool]:
    """작업 상세 한 번 → (레코드, 이후 allRecords 를 써야 하는가).

    상세 경로가 통하지 않으면(스펙에 응답이 비어 있고 경로가 다를 수 있다) 목록 API 로 넘어간다
    — 이미 과금된 결과를 '조회를 못 해서' 잃지 않기 위한 대안 경로다.
    """
    if not use_records:
        try:
            d = _call("GET", P_UPSCALE_TASK + urllib.parse.quote(uid), timeout=30, quiet=quiet)
            rec = _as_rec(d.get("data")) or (d if isinstance(d, dict) else {})
            if rec:
                return rec, False
            log.warning("업스케일 상세 응답이 비어 있습니다 — 목록 조회로 전환합니다: %s", _trim(d, 120))
        except VNError as exc:
            log.warning("업스케일 상세 조회 실패 — 목록 조회로 전환합니다: %s", exc)
    d = _call("GET", P_UPSCALE_RECORDS + "?pageNum=1&pageSize=50", timeout=30, quiet=quiet)
    for it in _as_list(d.get("data")) or _as_list(d):
        if isinstance(it, dict) and _pick(it, _ID_FIELDS) == uid:
            return it, True
    return {}, True


def wait_upscale(uid: str, source_url: str = "", max_sec: int = POLL_MAX_SEC,
                 on_progress=None, quiet: bool = False) -> str:
    """폴링 → 결과 이미지 URL. 상태·URL 필드명이 무엇이든 흡수하되 모르면 오류로 알린다."""
    uid = _uid_ok(uid)
    started = time.monotonic()
    deadline = started + max_sec
    use_records = False
    last = ""
    last_note = -99.0
    while time.monotonic() < deadline:
        rec, use_records = _upscale_record(uid, use_records, quiet)
        last = _trim(rec, 200)
        st = _pick(rec, _STATUS_FIELDS).lower()
        found = _urls_in(rec, skip=source_url)
        urls = [u for u in found if u.startswith("https://")]
        elapsed = time.monotonic() - started
        if callable(on_progress):
            try:
                on_progress(elapsed, st or "조회중")
            except Exception:
                pass
        done = st in DONE_STATES or rec.get("success") is True
        if st in FAIL_STATES:
            raise VNError(f"업스케일 실패(작업 {uid}): {_pick(rec, _ERR_FIELDS)[:150] or last}")
        if done or (urls and not st):
            if urls:
                return urls[0]
            if found:
                raise VNError(f"업스케일 결과가 https 주소가 아닙니다(작업 {uid}): {found[0][:100]}")
            if done:
                # 완료라는데 결과 주소가 없다 — 여기서 조용히 넘어가면 과금만 남는다.
                raise VNError(f"업스케일이 완료됐지만 결과 URL 을 찾지 못했습니다"
                              f"(작업 {uid}) — 응답: {last}")
        if not quiet and elapsed - last_note >= 15:   # 폴링마다 한 줄씩 쏟지 않는다
            _say(f"  업스케일 대기 {elapsed:.0f}초 · 상태 {st or '조회중'} · 작업 {uid[-6:]}")
            last_note = elapsed
        time.sleep(POLL_SEC)
    raise VNError(f"업스케일 대기 시간 초과({max_sec}초) — 작업 {uid} 는 이미 과금됐습니다. "
                  f"allRecords 에서 결과를 확인할 수 있습니다. 마지막 응답: {last}")


def upscale_url(source_url: str, *, name: str = "", on_progress=None,
                quiet: bool = True) -> str:
    """공개 URL 한 장을 업스케일 → 결과 이미지 URL. (유료)"""
    uid = upscale_start(source_url, name=name, quiet=quiet)
    return wait_upscale(uid, source_url=source_url, on_progress=on_progress, quiet=quiet)


def _image_size(path: Path):
    """(width, height) 또는 None — 판독은 print_preflight 하나에 맡긴다(지연 import)."""
    try:
        import print_preflight as pf
        return pf.image_size(Path(path))
    except Exception as exc:                       # 판독 실패가 업스케일을 막지는 않는다
        log.debug("이미지 크기 판독 생략: %s", exc)
        return None


def _unique(path: Path) -> Path:
    """이미 있는 이름이면 -2, -3 … 을 붙인다(같은 컷을 두 번 키워도 덮지 않게)."""
    p, n = Path(path), 2
    while p.exists():
        p = Path(path).with_name(f"{Path(path).stem}-{n}{Path(path).suffix}")
        n += 1
    return p


def _upscale_notes(before, after) -> list[str]:
    """무엇이 얼마나 커졌고 그래서 어디까지 인화되는지 — 이 기능의 존재 이유를 그대로 확인."""
    msgs: list[str] = []
    if before and after:
        msgs.append(f"업스케일 {before[0]}×{before[1]} → {after[0]}×{after[1]}")
        if after[0] <= before[0] and after[1] <= before[1]:
            msgs.append("주의: 결과가 원본보다 크지 않습니다 — 과금됐는데 인화 규격은 그대로입니다.")
    if after:
        note = _print_note(after[0], after[1])
        if note:
            msgs.append(note)
    return msgs


def _register_upscaled(sid: str) -> list[str]:
    """새 후보를 장면에 등록한다 — 장면 쓰기는 scene_ops 하나만 한다(record_tasks 와 같은 규약).

    APPROVED 장면은 후보 목록을 바꾸는 것 자체가 승인 게이트 위반이라 scene_ops 가 막는다.
    업스케일은 그림을 바꾸지 않으므로 **파일은 남기고 등록만 건너뛴 뒤 사실을 알린다** —
    사람이 되돌린 뒤(revise) 새 후보를 보고 고르는 것이 이 저장소의 순서다.

    상태는 지금 다시 읽는다 — 업스케일이 도는 몇 분 사이에 사람이 승인했을 수 있다.
    (최종 관문은 어차피 scene_ops 다. 여기 판정은 더 친절한 문구를 내기 위한 것이다.)
    """
    sc = load_json_safe(_scene_path(sid), {})
    if sc.get("status") == "APPROVED":
        # 단계는 위치 인자이고 대문자다(BACK_STATES). 예전 문구는 `--stage image` 라
        # 그대로 복사해 실행하면 argparse 오류가 났다 — scene_ops._REVISE_HINT 와 같은 형태로 맞춘다.
        return [f"{sid} 는 APPROVED 라 후보 목록은 건드리지 않았습니다 — 확대본은 "
                f"images/raw/{sid}/ 에 저장했습니다. 새 후보로 쓰려면 되돌린 뒤 폴더 스캔을 하세요:\n"
                f"  python tools/advance_scene.py revise {sid} IMAGE --note \"인화용 확대본 적용\""]
    try:
        import scene_ops
        scene_ops.register_images(sid)
        return []
    except Exception as exc:
        return [f"후보 등록 실패({sid}): {exc} — 파일은 저장했으니 폴더 스캔으로 등록할 수 있습니다."]


def upscale_scene(sid: str, *, on_progress=None, quiet: bool = False) -> GenResult:
    """장면의 선택 이미지를 재생성 없이 확대해 **새 후보로만** 저장한다(유료).

    선택·승인 상태는 바꾸지 않는다. 사람이 새 후보를 보고 고르는 순서를 그대로 둔다.
    """
    sc = _load_scene(sid)
    sel = selected_of(sc)
    if not sel:
        raise VNError(f"{sid} 에 선택된 이미지가 없습니다. 먼저 후보를 고른 뒤 확대하세요.")
    try:
        src = safe_path(ROOT, sel)
    except VNError as exc:
        raise VNError(f"{sid} 의 선택 이미지 경로가 올바르지 않습니다({sel}): {exc}") from exc
    if not src.is_file():
        raise VNError(f"{sid} 의 선택 이미지 파일이 없습니다: {sel}")
    out_dir = RAW_DIR / sid
    before = _image_size(src)
    _say(f"[{sid}] 원본 업로드 중… ({src.name}"
         + (f" · {before[0]}×{before[1]}" if before else "") + ")", quiet)
    source_url = upload_file(src, quiet=quiet)     # 업스케일 API 는 URL 만 받는다

    uid = ""
    try:
        uid = upscale_start(source_url, name=sid, quiet=quiet)
        _say(f"[{sid}] 업스케일 작업 {uid} 시작 — 결과를 기다립니다.", quiet)
        out_url = wait_upscale(uid, source_url=source_url,
                               on_progress=on_progress, quiet=quiet)
    except RuntimeError as e:
        # 시작이 됐다면 이미 과금이다. 작업 id 를 대장과 메타에 남겨야 나중에 회수할 수 있다.
        log_usage({"kind": "upscale", "scene_id": sid, "task_id": uid, "requested": 1,
                   "saved": 0, "ok": False, "billable": bool(uid), "source": sel,
                   "source_url": source_url, "error": str(e)[:200]})
        write_gen_meta(out_dir, {"created_at": _now(), "scene_id": sid, "task_id": uid,
                                 "kind": "upscale", "source": sel, "source_url": source_url,
                                 "files": [], "status": "failed", "error": str(e)[:200]})
        raise VNError(f"{e}" + (f" (작업 id 는 {out_dir.name}/{META_NAME} 에 남겼습니다)"
                                if uid else "")) from e

    dest = _unique(out_dir / f"{Path(sel).stem}_up{_ext(out_url)}")
    try:
        download(out_url, dest, quiet=quiet)
        with open(dest, "rb") as fh:        # 매직바이트만 — 큰 인화본을 통째로 읽지 않는다
            real = sniff_image(fh.read(32))
        if real is None:
            with contextlib.suppress(OSError):
                dest.unlink()
            raise VNError(f"업스케일 결과가 이미지가 아닙니다(작업 {uid}) — 저장하지 않았습니다.")
    except (RuntimeError, OSError) as e:
        # 여기까지 왔으면 과금은 끝났고 결과는 서버에 있다. **결과 URL 을 남겨야** 다시
        # 돈을 내지 않고 회수할 수 있다(생성 경로의 task_id 기록과 같은 이유).
        log_usage({"kind": "upscale", "scene_id": sid, "task_id": uid, "requested": 1,
                   "saved": 0, "ok": False, "billable": True, "source": sel,
                   "source_url": source_url, "result_url": out_url, "error": str(e)[:200]})
        write_gen_meta(out_dir, {"created_at": _now(), "scene_id": sid, "task_id": uid,
                                 "kind": "upscale", "source": sel, "source_url": source_url,
                                 "result_url": out_url, "files": [], "status": "failed",
                                 "error": str(e)[:200]})
        raise VNError(f"{e} — 결과는 이미 만들어졌습니다(과금 완료). "
                      f"주소를 {out_dir.name}/{META_NAME} 의 result_url 에 남겼으니 "
                      f"그 주소로 내려받으면 다시 결제하지 않아도 됩니다.") from e
    if dest.suffix.lower() not in real:            # 확장자와 내용이 다르면 이름을 내용에 맞춘다
        fixed = _unique(dest.with_suffix(real[0]))
        with contextlib.suppress(OSError):
            dest.replace(fixed)
            dest = fixed
    after = _image_size(dest)
    notes = _upscale_notes(before, after)
    for msg in notes:
        _say("  " + msg, quiet)
    log_usage({"kind": "upscale", "scene_id": sid, "task_id": uid, "requested": 1, "saved": 1,
               "ok": True, "billable": True, "source": sel, "file": dest.name,
               "width": (after or (0, 0))[0], "height": (after or (0, 0))[1],
               "src_width": (before or (0, 0))[0], "src_height": (before or (0, 0))[1],
               "error": ""})
    write_gen_meta(out_dir, {"created_at": _now(), "scene_id": sid, "task_id": uid,
                             "kind": "upscale", "source": sel, "source_url": source_url,
                             "prompt": "", "model": "upscale",
                             "width": (after or (0, 0))[0], "height": (after or (0, 0))[1],
                             "files": [dest.name], "status": "ok", "error": ""})
    # 업스케일 id 는 assets.makefun_tasks 에 넣지 않는다 — 그 목록은 text2image 재수령
    # 전용이고, 다른 엔드포인트의 id 가 섞이면 --refetch 가 통째로 실패한다.
    warns = notes + _register_upscaled(sid)
    return GenResult([dest], warns, [uid])


# --- 크레딧(읽기 전용) --------------------------------------------------------

def _credit_hint(data) -> str:
    """잔액처럼 **보이는** 값이 있으면 필드명과 함께 인용한다 — 단정하지는 않는다."""
    hits: list[str] = []
    seen = 0
    for rec in ([data] if isinstance(data, dict) else []) + _as_list(data)[:1]:
        if not isinstance(rec, dict) or seen > 1:
            continue
        seen += 1
        for k, v in rec.items():
            low = str(k).lower()
            if any(w in low for w in ("balance", "credit", "remain", "point", "amount")) \
                    and isinstance(v, (int, float)) and not isinstance(v, bool):
                hits.append(f"{k}={v}")
    return ", ".join(hits[:4])


def credits(*, page: int = 1, size: int = 20, quiet: bool = True) -> dict:
    """크레딧 이력 조회 → {"ok", "raw", "note"}.

    **이미지 생성 과금은 없지만 API 토큰을 쓰는 실제 호출이다.**
    응답 스키마가 스펙에 비어 있고 잔액 필드가 있다는 보장도 없으므로 **잔액을 단정하지 않는다**
    — 보이는 것만 그대로 인용한다.
    """
    q = urllib.parse.urlencode({"pageNum": max(1, int(page)),
                                "pageSize": max(1, min(int(size), 100))})
    try:
        d = _call("GET", f"{P_CREDITS}?{q}", timeout=30, quiet=quiet)
    except RuntimeError as e:
        log_usage({"kind": "credits", "billable": False, "ok": False, "error": str(e)[:200]})
        return {"ok": False, "raw": "", "note": f"크레딧 이력을 불러오지 못했습니다: {e}"}
    items = _as_list(d.get("data")) or _as_list(d)
    hint = _credit_hint(d.get("data") if d.get("data") is not None else d)
    note = (f"이력 {len(items)}건" + (f" · 응답에 보이는 값: {hint}" if hint else "")
            + " — 응답 형식이 공개돼 있지 않아 잔액으로 단정하지 않습니다. "
              "실제 잔액은 makefun.ai 계정 화면에서 확인하세요.")
    log_usage({"kind": "credits", "billable": False, "ok": True, "records": len(items)})
    return {"ok": True, "raw": _trim(d, 800), "note": note}


def now_iso() -> str:
    """지금 시각(UTC · ISO 8601). 소비 기록 조회의 시작 경계로 쓴다.

    UTC 로 보내는 이유: 공급자 시각대를 모른다. 로컬 시각을 보내면 시차만큼 앞뒤의
    남의 기록이 섞여 들어오거나 내 기록이 빠진다 — 둘 다 실측을 조용히 망친다.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SPEND_PAGE = 50            # 한 번에 받아 오는 소비 기록 수
SPEND_MAX_PAGES = 5       # 더 있어도 여기서 끊는다(창이 좁으니 이보다 많을 일이 거의 없다)
SPEND_RETRY_SEC = 3.0     # 기록이 아직 안 올라왔을 때 한 번 더 기다리는 시간
SPEND_SAMPLE_CAP = 10     # 이만큼 쌓이면 그만 잰다 — 덤은 덤으로 끝나야 한다


def consumption_since(since_iso: str, *, limit: int = SPEND_PAGE, quiet: bool = True) -> list:
    """그 시각 이후의 **소비 기록**만 → [{amount, at, raw}] (실패하면 빈 목록).

    공급자는 "장당 몇 크레딧" 을 공개하지 않는다. 그래서 물어보는 대신 **잰다** —
    굽기 직전 시각을 적어 두고, 구운 뒤에 그 시각 이후의 소비만 조회한다.
    두세 번 쌓이면 "이 크기·이 모델이면 얼마" 가 나오고, 그때부터 화면이 **실측한** 숫자를
    보여 줄 수 있다. 추측한 숫자와 잰 숫자는 다른 물건이다.

    부호 규약은 명세가 확정해 준 몇 안 되는 것 중 하나다:
    *"Positive amounts are credit grants or purchases; negative amounts are credit consumption."*
    그래서 **음수만** 소비로 센다. 응답 스키마 자체는 여전히 비어 있어 필드 이름은 모른다 —
    숫자를 찾되 이름을 단정하지 않는다.

    실패해도 조용히 넘어간다(빈 목록). 이건 **덤으로 재는 일**이라, 여기서 예외를 던지면
    이미 성공한 생성이 실패로 뒤집힌다.
    """
    stamp = str(since_iso or "").strip()
    if not stamp:
        return []
    size = max(1, min(int(limit), 100))
    out: list = []
    for page in range(1, SPEND_MAX_PAGES + 1):
        q = urllib.parse.urlencode({"pageNum": page, "pageSize": size,
                                    "is_consumption": "true", "startDate": stamp})
        try:
            d = _call("GET", f"{P_CREDITS}?{q}", timeout=30, quiet=quiet)
        except (RuntimeError, VNError) as exc:
            log.warning("소비 기록을 못 읽었습니다(실측만 건너뜁니다): %s", str(exc)[:120])
            return []
        rows = [it for it in (_as_list(d.get("data")) or _as_list(d)) if isinstance(it, dict)]
        for it in rows:
            amount = None
            for _k, v in _flat_numbers(it):
                if v < 0:                 # 명세: 음수 = 소비
                    amount = v
                    break
            if amount is None:
                continue
            out.append({"amount": amount,
                        "at": _pick(it, ("createdAt", "created_at", "date", "time")),
                        "raw": _trim(it, 200)})
        # **페이지가 꽉 찼으면 더 있다.** 한 장만 읽고 끝내면 기록이 6줄인데 5줄만 세고,
        # 평균 단가가 **실제보다 싸게** 나온다 — 화면이 사람에게 덜 든다고 말하는 쪽의
        # 오류라 더 나쁘다. 한 번의 생성이 여러 줄을 만든다(장수 최대 8 · 업스케일 등).
        if len(rows) < size:
            break
        log.info("소비 기록이 한 페이지를 채웠습니다 — 다음 장을 읽습니다(page %d)", page + 1)
    return out


def _flat_numbers(node, prefix=""):
    """중첩된 응답에서 (이름, 숫자) 를 납작하게 — 이름을 해석하지 않고 값만 본다."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            out.extend(_flat_numbers(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out.append((prefix, float(node)))
    return out


def record_spend(kind: str, scene_id: str, since_iso: str, detail: dict | None = None) -> dict:
    """유료 호출 뒤 **실제로 얼마가 나갔는지** 재서 대장에 남긴다.

    이 한 줄이 쌓이면 다음번엔 사람에게 "지난번엔 이만큼 나갔습니다" 를 보여 줄 수 있다.
    실패한 호출 뒤에도 부른다 — **실패도 과금되는지**가 여기서만 답이 나온다.
    """
    # 이미 충분히 쟀으면 그만 잰다. 이 조회도 실호출이라(무과금이지만 토큰을 쓴다)
    # 생성마다 계속 재면 덤이 세금이 된다.
    seen = measured_spend(kind)
    if seen.get("n", 0) >= SPEND_SAMPLE_CAP:
        return {"kind": "spend", "of": str(kind), "skipped": "enough",
                "spent": None, "records": 0, "ok": False}
    rows = consumption_since(since_iso)
    if not rows:
        # **과금은 보통 제출이 아니라 완료 시점에 확정된다.** 끝나자마자 재면 아직 줄이
        # 안 올라와 있을 수 있다. 한 번만 더 기다려 본다 — 그래도 없으면 '못 쟀음' 이다
        # ('0 크레딧을 썼다' 가 아니다. 그 둘을 같이 적으면 실측이 오염된다).
        time.sleep(SPEND_RETRY_SEC)
        rows = consumption_since(since_iso)
    total = round(sum(abs(r["amount"]) for r in rows), 4)
    rec = {"kind": "spend", "of": str(kind), "scene_id": str(scene_id or ""),
           "billable": False, "ok": bool(rows), "records": len(rows),
           "spent": total if rows else None, "since": str(since_iso or "")}
    if detail:
        rec.update({k: v for k, v in detail.items() if k not in rec})
    if not rows:
        # **못 쟀으면 대장에 남기지 않는다.** 아무것도 안 적힌 줄은 나중에 읽는 사람에게
        # '0 크레딧이 나갔다' 로 보이고, 그건 잰 것이 아니라 못 잰 것이다.
        log.info("소비 기록이 없어 실측을 건너뜁니다(%s · %s 이후)", kind, since_iso)
        return rec
    log_usage(rec)
    return rec


def measured_spend(of: str = "", limit: int = 20) -> dict:
    """대장에 쌓인 실측을 요약 → {"n", "avg", "last"} (없으면 n=0).

    **화면이 숫자를 보여도 되는 유일한 근거**다. 지어낸 값도, 남의 가격표도 아니고
    이 계정에서 실제로 빠져나간 크레딧이다.
    """
    rows = []
    try:
        with open(USAGE_LOG, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("kind") == "spend" and isinstance(r.get("spent"), (int, float)):
                    if not of or r.get("of") == of:
                        rows.append(r)
    except OSError:
        return {"n": 0, "avg": None, "last": None}
    rows = rows[-max(1, int(limit)):]
    if not rows:
        return {"n": 0, "avg": None, "last": None}
    vals = [float(r["spent"]) for r in rows]
    return {"n": len(vals), "avg": round(sum(vals) / len(vals), 3), "last": vals[-1]}


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
                         claim: bool = True, reference: bool = True) -> dict:
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
                                               negative=negative, quiet=quiet,
                                               reference=reference)
            else:
                files = generate_for_scene(sid, n=n, long_edge=long_edge,
                                           negative=negative, quiet=quiet,
                                           reference=reference)
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
    # 레퍼런스는 컷 사이 얼굴이 흔들리지 않게 하는 1차 수단이다 — 비어 있으면 알린다(네트워크 없음).
    chars = load_json_safe(MANIFEST, {}).get("characters")
    chars = [c for c in (chars if isinstance(chars, list) else []) if isinstance(c, dict)]
    with_ref = [c.get("character_id", "?") for c in chars if c.get("reference_images")]
    if chars:
        rep["lines"].append(
            (f"OK   레퍼런스 이미지: {len(with_ref)}/{len(chars)}명 등록 "
             f"(생성마다 최대 {_ref_cap()}장 첨부)") if with_ref else
            (f"주의 캐릭터 {len(chars)}명 모두 reference_images 가 비어 있습니다 — "
             f"컷마다 얼굴이 흔들립니다. 시트를 승인한 뒤 매니페스트에 등록하세요"
             f"(로컬 파일이면 --upload 로 URL 을 만들 수 있습니다)."))
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
    ap.add_argument("--no-reference", action="store_true",
                    help="매니페스트 reference_images 를 생성에 첨부하지 않음(기본은 첨부)")
    ap.add_argument("--upscale", metavar="SCENE-001",
                    help="선택 이미지를 재생성 없이 확대해 새 후보로 저장 — **유료**. "
                         "선택·승인 상태는 바뀌지 않고 APPROVED 장면도 확대할 수 있습니다")
    ap.add_argument("--upload", metavar="파일",
                    help="로컬 이미지를 올려 공개 URL 을 출력(레퍼런스 등록용). 생성 과금 없음")
    ap.add_argument("--credits", action="store_true",
                    help="크레딧 이력 조회 — 이미지 생성 과금은 없지만 **API 토큰을 쓰는 실제 호출**입니다")
    ap.add_argument("--check", action="store_true", help="토큰·설정 사전 점검")
    ap.add_argument("--online", action="store_true", help="--check 에서 조회 1회로 인증까지 확인")
    ap.add_argument("--quiet", action="store_true", help="진행 표시 끄기")
    a = ap.parse_args()
    neg = not a.no_negative
    ref = not a.no_reference
    long_edge = a.long_edge or None

    try:
        if a.check:
            rep = check(online=a.online)
            for line in rep["lines"]:
                print(line)
            return 0 if rep["ok"] else 1

        if a.credits:
            rep = credits(quiet=a.quiet)
            print(rep["note"])
            if rep["raw"]:
                print(rep["raw"])
            return 0 if rep["ok"] else 1

        if a.upload:
            print(upload_file(a.upload, quiet=a.quiet))
            return 0

        if a.all_pending:
            res = generate_all_pending(n=a.n, limit=a.limit, long_edge=long_edge,
                                       negative=neg, dry_run=a.dry_run, quiet=a.quiet,
                                       reference=ref)
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

        if a.upscale:
            # 생성과 같은 관문을 탄다 — 웹에서 그 장면을 굽고 있으면 여기서 막힌다(중복 과금 차단).
            with claim_scene(a.upscale, "업스케일"):
                files = upscale_scene(a.upscale, quiet=a.quiet)
        elif a.task:
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
                                           negative=neg, quiet=a.quiet, reference=ref)
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
