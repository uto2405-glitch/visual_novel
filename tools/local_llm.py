#!/usr/bin/env python3
"""로컬 LLM 전송 계층 — 캐릭터와 '실제 대화'하기 위한 통로.

C:\\Users\\USER\\claude\\local_llm 의 llama.cpp 서버(OpenAI 호환, 기본 http://127.0.0.1:8080/v1)에 붙는다.
xai_client 와 별개(그록은 연출/프롬프트용, 로컬 LLM 은 인물 대화용). 키 불필요(로컬).

**이 모듈에는 프롬프트 문자열이 없다.** 인물 페르소나·말투 규칙·장기 기억·앨범 사진 규칙은
prompt_build 가 조립한다(저장소 규약: 모델 프롬프트는 prompt_build 와 vn_compose 에만 둔다).
여기 남은 것은 주소 검증 · 상태 조회 · 전송뿐이고, **의존은 vn_core 하나다**.
예전에는 옛 이름(persona_prompt·resolve_photos)을 위한 재수출이 파일 끝에 있었고, 그것이
prompt_build 를 함수 안에서 되받아 `prompt_build → local_llm → prompt_build` 고리를 만들었다.
호출부는 webapp 두 줄뿐이었고 webapp 은 이미 prompt_build 를 import 하므로 통로를 걷어냈다 —
프롬프트가 필요한 곳은 prompt_build 를 직접 부른다(이 파일의 CLI 도 main 안에서만 부른다).

설정 우선순위: 환경변수 LOCAL_LLM_URL > manifest.talk.base_url > 기본값.

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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())


def base_url() -> str:
    env = os.environ.get("LOCAL_LLM_URL", "").strip()
    if env:
        return env.rstrip("/")
    talk = vn_core.load_manifest().get("talk")
    u = talk.get("base_url", "") if isinstance(talk, dict) else ""
    if isinstance(u, str) and u.strip():
        return u.strip().rstrip("/")
    return DEFAULT_URL


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


def status() -> dict:
    """서버가 떠 있고 모델이 로드됐는지."""
    url = base_url()
    try:
        _validate(url)
        req = urllib.request.Request(url + "/models")
        with _OPENER.open(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
        return {"up": True, "url": url, "models": models}
    except Exception as exc:
        return {"up": False, "url": url, "error": str(exc)}


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
    headers = {"Content-Type": "application/json"}
    if stream:
        headers["Accept"] = "text/event-stream"
    req = urllib.request.Request(url + "/chat/completions", data=body,
                                 headers=headers, method="POST")
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            if stream:
                content = _read_stream(r, on_token)
                if not content:
                    raise VNError("로컬 LLM 응답에 텍스트가 없습니다.")
                return content
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise VNError(f"로컬 LLM HTTP {e.code} — 서버/모델 상태를 확인하세요.")
    except urllib.error.URLError as e:
        raise VNError(f"로컬 LLM 에 연결할 수 없습니다({e.reason}). "
                      "local_llm/runtime/serve.ps1 로 서버를 켜세요.")
    try:
        data = json.loads(raw.decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, UnicodeDecodeError):
        raise VNError("로컬 LLM 응답 형식이 예상과 다릅니다.")
    if not isinstance(content, str):
        raise VNError("로컬 LLM 응답에 텍스트가 없습니다.")
    return content.strip()


def main() -> int:
    # 프롬프트 조립은 prompt_build 담당이고 그쪽이 이 모듈을 import 한다 — 모듈 수준에서
    # 되받으면 순환이므로, **CLI 로 쓸 때만** 여기서 가져온다(라이브러리 경로는 무관).
    import prompt_build

    st = status()
    print(f"로컬 LLM: {'ON' if st['up'] else 'OFF'} ({st['url']})")
    if not st["up"]:
        print(f"  {st.get('error', '')}")
        print("  → C:\\Users\\USER\\claude\\local_llm\\runtime\\serve.ps1 로 서버를 켜세요.")
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
