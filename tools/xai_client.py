#!/usr/bin/env python3
"""xAI API 클라이언트 — 모든 도구(webapp / grok_api / vn_compose)가 공유하는 단일 호출 경로.

키: 환경변수 XAI_API_KEY 전용. 파일 저장 금지 (CLAUDE.md 금지 조항).
모델/주소: project/manifest.json 의 orchestrator.api (base_url, model).
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
KEY_ENV = "XAI_API_KEY"
TIMEOUT_SEC = 300
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트 추종 차단 — cross-host 302 로 Authorization(Bearer 키) 가 외부로 재전송되는 것을 막는다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code,
            f"리다이렉트 차단(키 유출 방지): {newurl}", headers, fp)


# 전역 opener 대신 리다이렉트 비추종 opener 사용 (프록시는 환경변수 존중)
_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())


def _validate_base(base: str) -> None:
    """base_url 스킴/호스트 검증 — 평문 http 로 키가 나가는 것을 막는다(로컬호스트 제외)."""
    u = urllib.parse.urlparse(base)
    host = (u.hostname or "").lower()
    if u.scheme == "https":
        return
    if u.scheme == "http" and host in _LOOPBACK:
        return  # selftest 의 로컬 모의 서버 등 루프백만 평문 허용
    raise RuntimeError(
        f"base_url 이 안전하지 않습니다({base}). API 키가 평문/외부로 전송될 수 있습니다. "
        "https URL 을 사용하세요 (평문 http 는 127.0.0.1 등 로컬호스트만 허용).")

_HINTS = {401: "키가 잘못되었거나 만료됨 — console.x.ai 에서 재발급하세요.",
          403: "권한 없음 — SuperGrok OAuth 가 아닌 console.x.ai 발급 API 키인지 확인하세요.",
          404: "모델명이 존재하지 않음 — docs.x.ai 에서 현재 모델명을 확인해 manifest 를 고치세요.",
          429: "요금/속도 한도 초과 — 잠시 후 재시도하거나 콘솔에서 크레딧을 확인하세요."}


def config() -> tuple[str, str]:
    """(base_url, model). manifest 미비 시 RuntimeError."""
    if not MANIFEST.exists():
        raise RuntimeError("project/manifest.json 이 없습니다. templates/manifest.json 을 복사해 시작하세요.")
    mf = json.loads(MANIFEST.read_text(encoding="utf-8"))
    orch = mf.get("orchestrator")
    api = orch.get("api", {}) if isinstance(orch, dict) else {}
    base = (api.get("base_url") or "https://api.x.ai/v1").rstrip("/")
    model = (api.get("model") or "").strip()
    if not model or model.upper() == "TBD":
        raise RuntimeError("orchestrator.api.model 이 지정되지 않았습니다. "
                           "docs.x.ai 에서 모델명을 확인해 project/manifest.json 에 기입하세요.")
    return base, model


def key_set() -> bool:
    return bool(os.environ.get(KEY_ENV, "").strip())


def chat(messages: list[dict], temperature: float = 0.7) -> str:
    """messages 를 보내고 응답 본문을 돌려준다. 실패는 RuntimeError(사유 포함)."""
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(f"환경변수 {KEY_ENV} 가 비어 있습니다. "
                           "(Windows: set XAI_API_KEY=키 / PowerShell: $env:XAI_API_KEY=\"키\" / mac·Linux: export XAI_API_KEY=키)")
    base, model = config()
    _validate_base(base)
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": model, "messages": messages,
                         "temperature": temperature}).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    try:
        with _OPENER.open(req, timeout=TIMEOUT_SEC) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"xAI API HTTP {e.code}. {_HINTS.get(e.code, '')}".strip())
    except urllib.error.URLError as e:
        raise RuntimeError(f"네트워크 오류: {e.reason} — 인터넷 연결과 base_url 을 확인하세요.")
    # 200 이어도 본문이 JSON/UTF-8 이 아닐 수 있다(프록시·게이트웨이 오류 페이지 등) → 안내로 변환
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise RuntimeError("예상치 못한 API 응답 형식 — 본문이 JSON 이 아닙니다"
                           "(프록시/게이트웨이 오류 페이지일 수 있음).")
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("예상치 못한 API 응답 형식")
    if not isinstance(content, str):
        raise RuntimeError("API 응답에 텍스트 content 가 없습니다"
                           "(안전 필터로 차단됐거나 tool_calls 응답일 수 있음).")
    return content.strip()
