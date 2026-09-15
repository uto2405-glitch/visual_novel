#!/usr/bin/env python3
"""로컬 LLM 전송 계층 — 캐릭터와 '실제 대화'하기 위한 통로.

llama.cpp 서버(OpenAI 호환, 기본 http://127.0.0.1:8080/v1)에 붙는다. **이 PC 안일 필요는 없다** —
같은 공유기 아래 다른 기기(예: 노트북 http://192.168.0.7:8080/v1)도 주소 한 줄이면 된다.
오케스트레이터(스토리·장면 구성·이미지 프롬프트)와 인물 대화가 같은 이 통로를 쓴다.

**이 모듈에는 프롬프트 문자열이 없다.** 인물 페르소나·말투 규칙·장기 기억·앨범 사진 규칙은
prompt_build 가 조립한다(저장소 규약: 모델 프롬프트는 prompt_build 와 vn_compose 에만 둔다).
여기 남은 것은 주소 검증 · 상태 조회 · 전송뿐이고, **의존은 vn_core 하나다**.
예전에는 옛 이름(persona_prompt·resolve_photos)을 위한 재수출이 파일 끝에 있었고, 그것이
prompt_build 를 함수 안에서 되받아 `prompt_build → local_llm → prompt_build` 고리를 만들었다.
호출부는 webapp 두 줄뿐이었고 webapp 은 이미 prompt_build 를 import 하므로 통로를 걷어냈다 —
프롬프트가 필요한 곳은 prompt_build 를 직접 부른다(이 파일의 CLI 도 main 안에서만 부른다).

설정 우선순위: 환경변수 LOCAL_LLM_URL > manifest.talk.base_url >
manifest.orchestrator.api.base_url > 기본값 (정본 표는 docs/SCHEMA.md §1.2).
API 키도 같은 모양이다: LOCAL_LLM_KEY > api.key_env 가 가리키는 환경변수 > talk.api_key >
orchestrator.api.api_key > 빈 문자열(키를 요구하지 않는 서버). llama.cpp 를 ``--api-key`` 로
띄우면 /v1/models 는 키 없이 열려 있고 /v1/chat/completions 만 401 이 된다 — 키가 틀리면
'연결됨' 으로 보이면서 네 기능만 죽는다. :func:`status` 가 그 구멍을 따로 막는다.

전송 방식: :func:`chat` 은 기본이 비스트리밍(응답 전문을 한 번에 받는다)이고, ``on_token``
콜백을 주면 SSE 스트리밍으로 바뀌어 **첫 글자가 나오는 즉시** 조각을 흘려 준다. 콜백이
없을 때의 동작은 예전과 한 글자도 다르지 않다(하위호환).

주소 규칙(중요): 인물 대화 전문이 나가는 통로이므로 **루프백·사설망만** 허용한다.
scheme 이 https 라고 통과시키지 않는다 — 그 한 줄이 오타 하나로 대화 전체를 외부
호스트에 넘길 수 있는 유일한 구멍이었다.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:8080/v1"
TIMEOUT = 120
TALK_WINDOW = 16   # 서버가 모델에 넘기는 최근 대화 수 — 창 밖 맥락은 prompt_build.memory_digest 가 잇는다
# 이름으로 허용하는 것은 루프백 별칭뿐. 그 외 호스트명은 DNS 가 어디로든 향할 수 있어 거부한다.
_LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
# 사고 과정 태그 — 답이 아니라 모델이 혼잣말한 흔적이다.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
_THINK_CLOSE = "</think>"


def strip_reasoning(text: str) -> str:
    """``<think>…</think>`` 를 걷어낸 본문. 없으면 한 글자도 바뀌지 않는다.

    이 모델(Qwen3.6)의 ChatML 템플릿은 판본에 따라 생성 프리픽스로 ``<think>`` 를 먼저
    붙인다 — 그러면 **여는 태그 없이 ``</think>`` 로 시작하는 응답**이 온다. 실측에서
    ``'</think>

Hello! How can I help'`` 를 받았다. 그대로 두면 인물의 첫마디가
    ``</think>`` 로 시작하고, 장면 JSON 앞에는 혼잣말이 붙는다.

    거르는 자리를 여기로 정한 이유: 네 기능(스토리 챗·장면 구성·이미지 프롬프트·인물 대화)이
    모두 :func:`chat` 하나를 지난다. 화면마다 따로 지우면 새로 붙는 화면이 반드시 빠뜨리고,
    프롬프트를 만드는 층(prompt_build·vn_compose)에 두면 '무엇을 시킬까' 와 '무엇을 받았나' 가
    한 파일에서 섞인다. 접어서 보여 주는 선택지도 있었지만, 이 저장소에서 모델의 사고 과정을
    읽어야 하는 화면은 하나도 없다 — 원고·대사·JSON 만 쓴다.
    """
    out = _THINK_BLOCK.sub("", str(text or ""))
    i = out.find(_THINK_CLOSE)          # 여는 태그가 프롬프트 쪽에 있던 경우
    if i >= 0:
        out = out[i + len(_THINK_CLOSE):]
    return out.strip()


def serve_script() -> Path:
    """llama.cpp 설치 폴더의 ``runtime\\serve.ps1`` 경로.

    해석 순서는 ``start_studio.ps1`` 과 같다: ``LOCAL_LLM_HOME`` > ``~/claude/local_llm``.
    예전에는 안내 문구에 개발 PC 경로(``c:\\Users\\USER\\...``)가 그대로 박혀 있어서,
    다른 기기에서는 시키는 대로 따라 해도 존재하지 않는 파일을 가리켰다 — 서버가 꺼져
    있다는 사실을 처음 알게 되는 자리가 바로 이 문구라서, 여기서 길을 잃으면 스토리·
    프롬프트·대화 네 탭이 통째로 막힌 채로 남는다. 경로 해석을 한 곳에 모아 둔다.
    """
    home = os.environ.get("LOCAL_LLM_HOME") or str(Path.home() / "claude" / "local_llm")
    return Path(home) / "runtime" / "serve.ps1"


def is_remote(url: str | None = None) -> bool:
    """이 주소가 **다른 기기**를 가리키는가(루프백이 아니면 원격).

    이 한 줄이 갈라 주는 것은 안내 문구다. LLM 이 노트북에 있는데 "이 PC 에서
    serve.ps1 을 실행하세요" 라고 말하면, 사용자는 없는 파일을 찾아 헤매다가
    **이 데스크톱에 두 번째 서버를 띄우려 든다** — 정확히 하지 말아야 할 일이다.
    """
    u = urllib.parse.urlparse(str(url if url is not None else base_url()))
    host = (u.hostname or "").strip().lower()
    if host in _LOOPBACK_NAMES:
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


def where_hint(url: str | None = None) -> str:
    """주소를 **어디서** 바꾸는가 — 두 자리를 모두 이름으로 부른다.

    노트북 IP 는 DHCP 라 옮겨 다닌다. 그때 사람이 고쳐야 할 곳이 어디인지 모르면
    manifest 를 고치고도 환경변수가 이기고 있는 상태에서 한참을 헤맨다(또는 그 반대).
    그래서 우선순위가 높은 쪽을 먼저, 두 자리를 한 줄에 함께 적는다.
    """
    u = (url or base_url()).rstrip("/")
    if os.environ.get("LOCAL_LLM_URL", "").strip():
        # 환경변수가 이기는 동안 매니페스트를 고쳐도 아무 일도 안 일어난다 — 그 사실을
        # 말하지 않으면 사람은 맞는 파일을 고치고도 틀린 주소를 계속 보게 된다.
        return (f'지금은 환경변수 LOCAL_LLM_URL 이 매니페스트를 덮고 있습니다 — '
                f'setx LOCAL_LLM_URL "{u}" 로 바꾸거나, 지우고(setx LOCAL_LLM_URL "") '
                f'project/manifest.json 의 talk.base_url · orchestrator.api.base_url 을 쓰세요.')
    return ('project/manifest.json 의 talk.base_url 과 orchestrator.api.base_url 두 줄을 고치세요 '
            f'(또는 setx LOCAL_LLM_URL "{u}" · 환경변수가 항상 우선).')


def serve_hint() -> str:
    """서버를 어떻게 살리는가 — **주소가 가리키는 기기에 따라 문장이 달라진다**.

    원격이면 켜는 방법을 알려 줄 수 없다(그 기기는 여기 없다). 대신 '거기서 떠 있는가'
    와 '주소를 어디서 고치는가' 두 가지만 말한다. 로컬이면 예전 그대로 serve.ps1 이다.
    """
    url = base_url()
    if is_remote(url):
        host = urllib.parse.urlparse(url).hostname or url
        return (f"LLM 은 이 PC 가 아니라 {host} 에 있습니다 — 그 기기에서 llama-server 가 떠 있는지, "
                f"IP 가 바뀌지 않았는지 확인하세요. " + where_hint(url))
    path = serve_script()
    cmd = f'powershell -File "{path}" 을 실행하세요.'
    if path.exists():
        return cmd
    return cmd + ' 그 경로가 아니면 setx LOCAL_LLM_HOME "D:\\llm\\local_llm" 로 알려 주세요.'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())


def base_url() -> str:
    """로컬 LLM 주소. 매니페스트를 한 번만 읽고 두 칸을 순서대로 본다.

    ``orchestrator.api.base_url`` 이 뒤에 붙어 있는 이유: 그 칸은 매니페스트를 읽는 사람이
    **오케스트레이터 주소라고 믿는 자리**다. 예전에는 은퇴한 외부 API 클라이언트만 그것을
    읽었고, 그 클라이언트를 지우자 적혀 있어도 아무 효과가 없는 칸이 됐다. 우선순위는
    바꾸지 않았다(``talk.base_url`` 이 여전히 먼저다) — 없을 때만 내려온다.
    """
    env = os.environ.get("LOCAL_LLM_URL", "").strip()
    if env:
        return env.rstrip("/")
    mf = vn_core.load_manifest()
    talk = mf.get("talk")
    orch = mf.get("orchestrator") if isinstance(mf.get("orchestrator"), dict) else {}
    api = orch.get("api") if isinstance(orch.get("api"), dict) else {}
    for src in (talk if isinstance(talk, dict) else {}, api):
        u = src.get("base_url", "")
        if isinstance(u, str) and u.strip():
            return u.strip().rstrip("/")
    return DEFAULT_URL


def api_key() -> str:
    """서버가 요구하는 API 키. base_url() 과 **같은 모양의 우선순위**를 쓴다.

    llama.cpp 를 ``--api-key`` 없이 띄웠으면 빈 문자열이 정답이고, 그때는 헤더를 아예
    붙이지 않는다(예전과 한 바이트도 다르지 않다). 키가 있는 서버에서는 이것이 없으면
    /v1/chat/completions 만 401 로 죽는다 — /v1/models 는 llama.cpp 가 키 없이 열어
    두기 때문에 '연결됨' 으로 보이면서 스토리·장면 구성·프롬프트·대화 네 기능이 전부
    실패한다. 값을 저장소에 적기 싫으면 key_env 에 **환경변수 이름**을 적으면 된다.
    """
    env = os.environ.get("LOCAL_LLM_KEY", "").strip()
    if env:
        return env
    mf = vn_core.load_manifest()
    talk = mf.get("talk") if isinstance(mf.get("talk"), dict) else {}
    orch = mf.get("orchestrator") if isinstance(mf.get("orchestrator"), dict) else {}
    api = orch.get("api") if isinstance(orch.get("api"), dict) else {}
    name = api.get("key_env", "")
    if isinstance(name, str) and name.strip():
        v = os.environ.get(name.strip(), "").strip()
        if v:
            return v
    for src in (talk, api):
        v = src.get("api_key", "")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _auth_headers() -> dict:
    """키가 있을 때만 Authorization 을 붙인다(없으면 빈 dict — 하위호환)."""
    key = api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


_warned: set[str] = set()


def _warn_once(msg: str) -> None:
    """같은 경고를 매 요청마다 찍지 않는다(대화 중 화면이 경고로 덮이지 않게)."""
    if msg in _warned:
        return
    _warned.add(msg)
    print(f"경고: {msg}", file=sys.stderr)


def _validate(url: str) -> None:
    """대화가 나갈 수 있는 주소를 좁힌다 — 루프백 IP·localhost 는 통과, 사설망은 경고 후 통과.

    공인 IP 와 임의 호스트명은 거부한다. 인물 대화는 사용자의 사적 자산이라
    '이 PC 안'을 벗어나는 순간을 최소한 눈에 보이게 만든다.
    """
    u = urllib.parse.urlparse(str(url or ""))
    host = (u.hostname or "").strip().lower()
    if u.scheme not in ("http", "https") or not host:
        raise VNError(f"로컬 LLM base_url 형식이 올바르지 않습니다({url}). "
                      "예: http://127.0.0.1:8080/v1")
    if host in _LOOPBACK_NAMES:
        return
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise VNError(f"로컬 LLM base_url 의 호스트 '{host}' 는 허용되지 않습니다 — "
                      "127.0.0.1 같은 루프백 주소나 사설망 IP 만 쓸 수 있습니다.")
    if ip.is_loopback:
        return
    if ip.is_private:
        _warn_once(f"로컬 LLM 주소 {host} 는 루프백이 아닙니다(사설망) — "
                   "인물 대화가 이 PC 밖의 기기로 전송됩니다.")
        return
    raise VNError(f"로컬 LLM base_url 이 안전하지 않습니다({url}). 로컬/사설망만 허용합니다.")


def _server_root(url: str) -> str:
    """OpenAI 경로(``/v1``)를 벗겨 서버 자체의 뿌리를 얻는다."""
    u = url.rstrip("/")
    return u[: -len("/v1")] if u.endswith("/v1") else u


def _auth_probe(url: str):
    """키가 받아들여지는가만 묻는다 — True(맞음) · False(거부) · None(알 수 없음).

    llama.cpp 의 ``/tokenize`` 는 인증 미들웨어 **아래**에 있으면서 생성을 하지 않는다.
    그래서 키 검사에 드는 비용이 사실상 0 이다 — 헤더 칩이 주기적으로 부르는 자리라
    이 점이 중요했다(1토큰 생성으로 확인하면 매번 1초씩 멈춘다).
    이 엔드포인트가 없는 서버(404 등)에서는 판단하지 않는다 — **모르면 막지 않는다**.
    """
    req = urllib.request.Request(
        _server_root(url) + "/tokenize", data=b'{"content":""}',
        headers={"Content-Type": "application/json", **_auth_headers()}, method="POST")
    try:
        with _OPENER.open(req, timeout=5):
            return True
    except urllib.error.HTTPError as exc:
        return False if exc.code in (401, 403) else None
    except Exception:
        return None


def _auth_error(url: str, code: int) -> str:
    """키가 거부됐을 때의 한 줄 — 무엇이 틀렸고 어느 칸을 고치는지."""
    where = ("환경변수 LOCAL_LLM_KEY" if os.environ.get("LOCAL_LLM_KEY", "").strip()
             else "매니페스트 talk.api_key / orchestrator.api.api_key")
    return (f"{url} 는 응답하지만 API 키를 거부했습니다(HTTP {code}) — 서버가 --api-key 로 떠 있고 "
            f"{where} 의 값이 그것과 다릅니다.")


def status() -> dict:
    """서버가 떠 있고 모델이 로드됐는지 — 그리고 **키가 맞는지**까지.

    ``reason`` 이 고장을 갈라 준다: ``unreachable``(주소가 틀렸거나 서버가 꺼짐) ·
    ``auth``(주소는 맞는데 키가 틀림) · ``ok``. 예전에는 ``/models`` 하나만 보고 up 을
    정했는데, llama.cpp 는 ``--api-key`` 로 띄워도 그 엔드포인트만은 키 없이 열어 둔다 —
    칩이 초록인데 네 기능이 전부 401 로 죽는, 가장 알아내기 어려운 고장이 거기서 났다.
    """
    url = base_url()
    try:
        _validate(url)
        req = urllib.request.Request(url + "/models", headers=_auth_headers())
        with _OPENER.open(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return {"up": False, "url": url, "models": [], "reason": "auth",
                    "error": _auth_error(url, exc.code)}
        return {"up": False, "url": url, "models": [], "reason": "unreachable",
                "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"up": False, "url": url, "models": [], "reason": "unreachable",
                "error": str(exc)}
    if _auth_probe(url) is False:
        return {"up": False, "url": url, "models": models, "reason": "auth",
                "error": _auth_error(url, 401)}
    return {"up": True, "url": url, "models": models, "reason": "ok"}


def _chunk_text(chunk) -> str:
    """스트리밍 조각 하나에서 늘어난 글자만 꺼낸다.

    OpenAI 호환 서버는 ``choices[0].delta.content`` 를 쓰지만, llama.cpp 의 판본에 따라
    ``message.content`` 나 ``content`` 로 오는 경우가 있다. 셋 다 받아 준다 — 서버를
    올리는 사람이 판본을 신경 쓰지 않아도 되게.
    """
    try:
        ch = chunk["choices"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(ch, dict):
        return ""
    for key in ("delta", "message"):
        part = ch.get(key)
        if isinstance(part, dict) and isinstance(part.get("content"), str):
            return part["content"]
    return ch["content"] if isinstance(ch.get("content"), str) else ""


def _read_stream(resp, on_token) -> str:
    """SSE 응답을 읽어 조각마다 on_token 을 부르고, 이어붙인 전문을 돌려준다.

    한 줄이 깨졌다고 대화를 끊지 않는다(그 줄만 건너뛴다). 중간에 연결이 끊긴 경우
    **이미 흘려보낸 글자는 살려서 돌려준다** — 사용자는 그 글자들을 이미 화면에서 봤고,
    거기서 예외를 던지면 눈으로 본 답장이 통째로 사라진다.

    stream 요청을 무시하고 통짜 JSON 으로 답하는 서버(구판 llama.cpp)도 받아 준다 —
    그 경우 조각이 하나뿐인 스트림처럼 다룬다. 스트리밍 지원 여부로 대화가 막히지 않게.
    """
    parts: list[str] = []
    plain: list[str] = []         # SSE 가 아닌 본문(위 폴백용). 첫 조각이 오면 더 모으지 않는다.
    try:
        for raw_line in resp:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line:
                continue
            if not line.startswith("data:"):
                if not parts and len(plain) < 400:
                    plain.append(line)   # 주석(:)·event: 는 규격상 무시 대상이라 폴백에서만 쓰인다
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except ValueError:
                continue
            piece = _chunk_text(chunk)
            if not piece:
                continue
            parts.append(piece)
            on_token(piece)
    except OSError as exc:        # 읽는 도중 끊김(타임아웃·소켓)
        if not parts:
            raise VNError(f"로컬 LLM 응답이 중간에 끊겼습니다({exc}).")
    if not parts and plain:
        try:                      # JSON 문자열은 줄을 넘지 못하므로 줄을 그냥 이어 붙여도 된다
            piece = _chunk_text(json.loads("".join(plain)))
        except ValueError:
            piece = ""
        if piece.strip():
            on_token(piece)
            return piece.strip()
    return "".join(parts).strip()


def chat(messages: list[dict], temperature: float = 0.8, max_tokens: int = 320,
         on_token=None) -> str:
    """대화 메시지 → 응답 텍스트. 실패는 RuntimeError(사유 포함).

    on_token 을 주면 SSE 스트리밍으로 받아 조각(str)마다 그 콜백을 부른다. 반환값은
    두 방식 모두 **완성된 전문**이라 호출부를 바꾸지 않고도 붙일 수 있다.
    콜백이 없으면 요청 본문의 stream 까지 예전 그대로다(하위호환).
    """
    url = base_url()
    _validate(url)
    stream = on_token is not None
    body = json.dumps({"messages": messages, "temperature": temperature,
                       "max_tokens": max_tokens, "stream": stream}).encode("utf-8")
    headers = {"Content-Type": "application/json", **_auth_headers()}
    if stream:
        headers["Accept"] = "text/event-stream"
    req = urllib.request.Request(url + "/chat/completions", data=body,
                                 headers=headers, method="POST")
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            if stream:
                # 조각은 그대로 흘려 보내고(콜백은 실시간 표시용) **반환값만** 정리한다 —
                # 저장·파싱되는 것은 반환값이다.
                content = strip_reasoning(_read_stream(r, on_token))
                if not content:
                    raise VNError("로컬 LLM 응답에 텍스트가 없습니다.")
                return content
            raw = r.read()
    except urllib.error.HTTPError as e:
        # 401/403 은 '서버가 이상하다' 가 아니라 '키가 다르다' 다 — 두 문장을 섞으면
        # 사용자는 멀쩡히 떠 있는 서버를 껐다 켜며 시간을 버린다.
        if e.code in (401, 403):
            raise VNError(_auth_error(url, e.code))
        raise VNError(f"로컬 LLM HTTP {e.code}({url}) — 서버/모델 상태를 확인하세요.")
    except urllib.error.URLError as e:
        raise VNError(f"로컬 LLM({url}) 에 연결할 수 없습니다({e.reason}). {serve_hint()}")
    try:
        data = json.loads(raw.decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, UnicodeDecodeError):
        raise VNError("로컬 LLM 응답 형식이 예상과 다릅니다.")
    if not isinstance(content, str):
        raise VNError("로컬 LLM 응답에 텍스트가 없습니다.")
    return strip_reasoning(content)


def main() -> int:
    # 프롬프트 조립은 prompt_build 담당이고 그쪽이 이 모듈을 import 한다 — 모듈 수준에서
    # 되받으면 순환이므로, **CLI 로 쓸 때만** 여기서 가져온다(라이브러리 경로는 무관).
    import prompt_build

    st = status()
    print(f"로컬 LLM: {'ON' if st['up'] else 'OFF'} ({st['url']})")
    if not st["up"]:
        print(f"  {st.get('error', '')}")
        print(f"  → {serve_hint()}")
        return 1
    print(f"  모델: {', '.join(m for m in st['models'] if m) or '(미표시)'}")
    if len(sys.argv) > 1 and sys.argv[1] == "--memory":   # 지난 대화 요약 갱신(장기 기억)
        ok = prompt_build.refresh_memory(sys.argv[2] if len(sys.argv) > 2 else None)
        print("기억 요약을 갱신했습니다." if ok else "요약할 지난 대화가 없거나 요약에 실패했습니다.")
        return 0
    if len(sys.argv) > 1:
        try:
            sysmsg, meta = prompt_build.persona_prompt()
            # CLI 는 글자가 나오는 대로 흘려 준다 — 320토큰을 다 만들 때까지 빈 화면으로
            # 기다리던 자리다(스트리밍 콜백의 첫 사용처).
            print(f"\n{meta['name']}: ", end="", flush=True)
            reply = chat([{"role": "system", "content": sysmsg},
                          {"role": "user", "content": " ".join(sys.argv[1:])}],
                         on_token=lambda piece: print(piece, end="", flush=True))
        except VNError as exc:
            print(f"\n오류: {exc}")
            return 1
        if not reply.endswith("\n"):
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
