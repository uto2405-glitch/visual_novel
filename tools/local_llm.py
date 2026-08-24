#!/usr/bin/env python3
"""로컬 LLM 클라이언트 — 캐릭터와 '실제 대화'하기 위한 경로.

C:\\Users\\USER\\claude\\local_llm 의 llama.cpp 서버(OpenAI 호환, 기본 http://127.0.0.1:8080/v1)에 붙는다.
xai_client 와 별개(그록은 연출/프롬프트용, 로컬 LLM 은 인물 대화용). 키 불필요(로컬).

설정 우선순위: 환경변수 LOCAL_LLM_URL > manifest.talk.base_url > 기본값.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project" / "manifest.json"
DEFAULT_URL = "http://127.0.0.1:8080/v1"
TIMEOUT = 120
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())


def base_url() -> str:
    env = os.environ.get("LOCAL_LLM_URL", "").strip()
    if env:
        return env.rstrip("/")
    try:
        mf = json.loads(MANIFEST.read_text(encoding="utf-8"))
        u = (mf.get("talk", {}) or {}).get("base_url", "")
        if isinstance(u, str) and u.strip():
            return u.strip().rstrip("/")
    except Exception:
        pass
    return DEFAULT_URL


def _validate(url: str) -> None:
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme == "https":
        return
    if u.scheme == "http" and (host in _LOOPBACK or host.startswith("192.168.") or host.startswith("10.")
                               or host.startswith("172.")):
        return
    raise RuntimeError(f"로컬 LLM base_url 이 안전하지 않습니다({url}). 로컬/사설망만 허용합니다.")


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
        raise RuntimeError(f"로컬 LLM HTTP {e.code} — 서버/모델 상태를 확인하세요.")
    except urllib.error.URLError as e:
        raise RuntimeError(f"로컬 LLM 에 연결할 수 없습니다({e.reason}). "
                           "local_llm/runtime/serve.ps1 로 서버를 켜세요.")
    try:
        data = json.loads(raw.decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, UnicodeDecodeError):
        raise RuntimeError("로컬 LLM 응답 형식이 예상과 다릅니다.")
    if not isinstance(content, str):
        raise RuntimeError("로컬 LLM 응답에 텍스트가 없습니다.")
    return content.strip()


# ------------------------------------------------------------- 인물 페르소나
def _load_manifest() -> dict:
    try:
        d = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _storyline() -> str:
    p = ROOT / "project" / "story" / "storyline.md"
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def persona_prompt(character_id: str | None = None) -> tuple[str, dict]:
    """매니페스트의 캐릭터 기준정보 + 스토리로 인물 대화용 시스템 프롬프트를 만든다."""
    mf = _load_manifest()
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    if not chars:
        raise RuntimeError("매니페스트에 캐릭터가 없습니다. 먼저 작품을 세팅하세요.")
    talk = mf.get("talk", {}) if isinstance(mf.get("talk"), dict) else {}
    cid = character_id or talk.get("character_id") or chars[0].get("character_id")
    ch = next((c for c in chars if c.get("character_id") == cid), chars[0])
    prof = ch.get("profile", {}) if isinstance(ch.get("profile"), dict) else {}
    name = ch.get("name") or cid
    relationship = talk.get("relationship", "다정한 여자친구")

    traits = ", ".join(str(prof.get(k, "")) for k in ("age", "gender_presentation", "hair", "eyes", "wardrobe")
                       if prof.get(k))
    props = ", ".join(prof.get("signature_props", []) or [])
    story = _storyline()
    story_line = f"\n[함께한 이야기]\n{story[:600]}" if story else ""

    sys = (
        f"너는 '{name}'라는 인물이야. 지금부터 끝까지 '{name}' 본인으로서 1인칭으로 자연스럽게 대화해.\n"
        f"[너의 모습] {traits}" + (f" / 아끼는 것: {props}" if props else "") + "\n"
        f"[관계] 상대는 너의 {relationship}. 편하고 다정한 반말로, 실제 연인처럼 대화해.\n"
        "[말투 규칙]\n"
        "- 한국어로, 1~3문장의 짧고 자연스러운 구어체. 이모티콘은 가끔만.\n"
        "- 너는 사람이야. 'AI', '언어모델', '도울 수 있어' 같은 표현 절대 금지.\n"
        "- 설명하거나 나열하지 말고, 감정과 리액션이 있는 진짜 대화를 해.\n"
        "- 가끔 먼저 질문하거나 장난도 치면서 대화를 이어가.\n"
        + story_line
    )
    return sys, {"character_id": cid, "name": name}


def main() -> int:
    import sys
    st = status()
    print(f"로컬 LLM: {'ON' if st['up'] else 'OFF'} ({st['url']})")
    if not st["up"]:
        print(f"  {st.get('error', '')}")
        print("  → C:\\Users\\USER\\claude\\local_llm\\runtime\\serve.ps1 로 서버를 켜세요.")
        return 1
    print(f"  모델: {', '.join(st['models']) or '(미표시)'}")
    if len(sys.argv) > 1:
        sysmsg, meta = persona_prompt()
        reply = chat([{"role": "system", "content": sysmsg},
                      {"role": "user", "content": " ".join(sys.argv[1:])}])
        print(f"\n{meta['name']}: {reply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
