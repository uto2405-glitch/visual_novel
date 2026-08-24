#!/usr/bin/env python3
"""로컬 LLM 전송 계층 — 캐릭터와 '실제 대화'하기 위한 통로.

C:\\Users\\USER\\claude\\local_llm 의 llama.cpp 서버(OpenAI 호환, 기본 http://127.0.0.1:8080/v1)에 붙는다.
xai_client 와 별개(그록은 연출/프롬프트용, 로컬 LLM 은 인물 대화용). 키 불필요(로컬).

**이 모듈에는 프롬프트 문자열이 없다.** 인물 페르소나·말투 규칙·장기 기억·앨범 사진 규칙은
prompt_build 가 조립한다(저장소 규약: 모델 프롬프트는 prompt_build 와 vn_compose 에만 둔다).
여기 남은 것은 주소 검증 · 상태 조회 · 전송뿐이고, 의존은 vn_core 하나다.
옛 이름(local_llm.persona_prompt · local_llm.resolve_photos)으로 부르던 곳을 위해 파일 끝에
얇은 재수출만 남겨 둔다.

설정 우선순위: 환경변수 LOCAL_LLM_URL > manifest.talk.base_url > 기본값.

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


def chat(messages: list[dict], temperature: float = 0.8, max_tokens: int = 320) -> str:
    """대화 메시지 → 응답 텍스트. 실패는 RuntimeError(사유 포함)."""
    url = base_url()
    _validate(url)
    body = json.dumps({"messages": messages, "temperature": temperature,
                       "max_tokens": max_tokens, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
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


# ------------------------------------------------- 하위호환 재수출 (정본은 prompt_build)
# prompt_build 가 이 모듈을 import 하므로 최상단에서 되받으면 순환이다 — 호출 시점에 가져온다.
def _prompts():
    import prompt_build
    return prompt_build


def persona_prompt(character_id: str | None = None) -> tuple[str, dict]:
    """→ prompt_build.persona_prompt. 옛 이름으로 부르는 곳(webapp·selftest)을 위한 통로."""
    return _prompts().persona_prompt(character_id)


def resolve_photos(reply: str, album: dict, last_user: str = ""):
    """→ prompt_build.resolve_photos. 옛 이름으로 부르는 곳을 위한 통로."""
    return _prompts().resolve_photos(reply, album, last_user)


def main() -> int:
    st = status()
    print(f"로컬 LLM: {'ON' if st['up'] else 'OFF'} ({st['url']})")
    if not st["up"]:
        print(f"  {st.get('error', '')}")
        print("  → C:\\Users\\USER\\claude\\local_llm\\runtime\\serve.ps1 로 서버를 켜세요.")
        return 1
    print(f"  모델: {', '.join(m for m in st['models'] if m) or '(미표시)'}")
    if len(sys.argv) > 1 and sys.argv[1] == "--memory":   # 지난 대화 요약 갱신(장기 기억)
        ok = _prompts().refresh_memory(sys.argv[2] if len(sys.argv) > 2 else None)
        print("기억 요약을 갱신했습니다." if ok else "요약할 지난 대화가 없거나 요약에 실패했습니다.")
        return 0
    if len(sys.argv) > 1:
        try:
            sysmsg, meta = persona_prompt()
            reply = chat([{"role": "system", "content": sysmsg},
                          {"role": "user", "content": " ".join(sys.argv[1:])}])
        except VNError as exc:
            print(f"오류: {exc}")
            return 1
        print(f"\n{meta['name']}: {reply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
