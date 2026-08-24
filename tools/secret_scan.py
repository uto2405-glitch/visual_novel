#!/usr/bin/env python3
"""비밀값 유출 스캐너 — 저장소 텍스트 파일에서 API 키·토큰 패턴을 찾는다.

검사기 A8(수정 금지)은 xAI 키 패턴 하나만 본다. 이 도구는 그 사각지대를 메우는 보조
게이트로, MakeFun(sk_…)·Bearer 헤더·클라우드 키·JWT·개인키 블록까지 훑는다.
판정을 대체하지 않으므로 SCORECARD 는 건드리지 않는다.

발견해도 **실제 값은 절대 출력하지 않는다** — 종류·위치·앞 3글자·길이만 보고한다.
(콘솔 로그나 캡처로 비밀이 2차 유출되는 것이 스캔 자체보다 위험하다.)

사용법:
  python tools/secret_scan.py              # 저장소 전체 (발견 시 종료코드 1)
  python tools/secret_scan.py --path docs  # 일부만
  python tools/secret_scan.py --json       # 기계 판독용
  python tools/secret_scan.py --quiet      # 발견 건만 출력

읽기 전용. 어떤 파일도 수정하지 않는다. 표준 라이브러리만.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

TEXT_EXTS = {".json", ".md", ".py", ".txt", ".cfg", ".ini", ".yaml", ".yml",
             ".ps1", ".sh", ".bat", ".cmd", ".html", ".js", ".css", ".toml", ".env"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "images"}
MAX_BYTES = 5_000_000        # 감상본 HTML 처럼 이미지가 내장된 대용량 파일은 건너뛴다
MAX_LINE = 4000              # 한 줄이 base64 덩어리인 경우 정규식 폭주 방지

# 패턴 접두사는 런타임 조립 — 이 파일 자체가 스캐너(및 A8)에 걸리지 않게 한다.
_X = "xa" + "i-"
_SK = "s" + "k"
_GH = "g" + "h"
_AWS = "AK" + "IA"
_GOOG = "AI" + "za"
_SLACK = "xo" + "x"

# (라벨, 정규식, 설명) — 오탐을 줄이려 길이 하한을 넉넉히 잡았다.
PATTERNS = [
    ("xai-key", re.compile(_X + r"[A-Za-z0-9_-]{20,}"),
     "xAI(Grok) API 키"),
    ("sk-token", re.compile(r"\b" + _SK + r"[_-][A-Za-z0-9]{20,}"),
     "sk_/sk- 형식 토큰(MakeFun·OpenAI 계열)"),
    ("bearer", re.compile(r"[Bb]earer\s+[A-Za-z0-9._~+/-]{24,}={0,2}"),
     "Authorization 헤더에 박힌 토큰"),
    ("aws-key", re.compile(_AWS + r"[0-9A-Z]{16}"),
     "AWS 액세스 키 ID"),
    ("github-token", re.compile(_GH + r"[pousr]_[A-Za-z0-9]{30,}"),
     "GitHub 개인 액세스 토큰"),
    ("google-key", re.compile(_GOOG + r"[0-9A-Za-z_-]{30,}"),
     "Google API 키"),
    ("slack-token", re.compile(_SLACK + r"[abprs]-[A-Za-z0-9-]{20,}"),
     "Slack 토큰"),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
     "JWT(서명된 토큰)"),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----"),
     "개인키 블록"),
    # JSON·설정의 "key": "value" 와 코드의 key = "value" 를 함께 잡으려 닫는 따옴표를 허용한다.
    ("assigned-secret",
     re.compile(r"""(?ix)
        \b(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|secret[_-]?key
           |client[_-]?secret|password|passwd|token)\b
        ["']?\s*[:=]\s*
        ["']([^"'\s]{16,})["']"""),
     "코드/설정에 문자열로 박힌 비밀값"),
]

# 값처럼 보이지만 비밀이 아닌 것들 — 환경변수 이름·자리표시자·예시.
_ENVNAME = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")
_PLACEHOLDER = re.compile(
    r"(?i)(발급|여기|채우|your|example|sample|dummy|placeholder|changeme|xxx+|\.\.\.|"
    r"^<|^\$|^%|^\{|^env:|redacted|masked|없음|미설정)")


def _looks_benign(label: str, value: str) -> bool:
    """자리표시자·정규식 소스는 비밀이 아니다.

    접두사가 고정된 패턴(xai-/sk_/AKIA…)은 이미 정밀하므로 약한 휴리스틱을 적용하지 않는다.
    AWS 키처럼 전부 대문자인 진짜 키가 '환경변수 이름 같다'는 이유로 묻히면 안 된다.
    """
    v = value.strip()
    if not v:
        return True
    if _PLACEHOLDER.search(v):
        return True
    if any(ch in v for ch in "[]{}()\\*+|"):   # 정규식/포맷 문자열 소스
        return True
    if label != "assigned-secret":
        return False
    return bool(_ENVNAME.match(v)) or len(set(v)) <= 4   # 환경변수 이름·채움값


def mask(value: str) -> str:
    """앞 3글자 + 길이만. 원문은 어떤 경우에도 출력하지 않는다."""
    v = value.strip()
    head = v[:3]
    return f"{head}… (총 {len(v)}자)"


def iter_files(base: Path):
    for p in sorted(base.rglob("*")):
        if not p.is_file() or set(p.parts) & SKIP_DIRS:
            continue
        if p.resolve() == SELF:                # 스캐너 자신의 패턴 소스는 제외
            continue
        if p.suffix.lower() not in TEXT_EXTS and not p.name.startswith(".env"):
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
        except OSError:
            continue
        yield p


def scan_text(text: str) -> list:
    """텍스트 → [(줄번호, 라벨, 설명, 마스킹값)]"""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > MAX_LINE:
            continue
        for label, pat, desc in PATTERNS:
            for m in pat.finditer(line):
                value = m.group(1) if m.groups() else m.group(0)
                if _looks_benign(label, value):
                    continue
                hits.append((lineno, label, desc, mask(value)))
    return hits


def scan(base: Path) -> list:
    findings = []
    for p in iter_files(base):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, label, desc, masked in scan_text(text):
            rel = p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix()
            findings.append({"file": rel, "line": lineno, "kind": label,
                             "desc": desc, "masked": masked})
    return findings


def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


def main() -> int:
    _console_guard()
    ap = argparse.ArgumentParser(description="저장소 비밀값 유출 스캐너 (읽기 전용)")
    ap.add_argument("--path", default=None, help="검사할 폴더 (기본: 저장소 전체)")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
    ap.add_argument("--quiet", action="store_true", help="발견 건만 출력")
    args = ap.parse_args()

    base = Path(args.path).resolve() if args.path else ROOT
    if not base.exists():
        print(f"오류: 경로가 없습니다: {base}")
        return 2

    findings = scan(base)

    if args.json:
        print(json.dumps({"count": len(findings), "findings": findings},
                         ensure_ascii=False, indent=2))
        return 1 if findings else 0

    if not args.quiet:
        print("=" * 60)
        print("비밀값 스캔 — 검사기 A8 보조 (실제 값은 출력하지 않습니다)")
        print("=" * 60)
    if not findings:
        if not args.quiet:
            print("발견 없음 — 키·토큰은 환경변수에만 있습니다.")
        return 0

    for f in findings:
        print(f"  ✗ {f['file']}:{f['line']}  [{f['kind']}] {f['desc']}")
        print(f"      값: {f['masked']}")
    print("-" * 60)
    print(f"{len(findings)}건 발견 — 조치 순서:")
    print("  1) 해당 값을 발급처에서 즉시 폐기·재발급한다 (파일만 지우면 이미 노출된 값은 살아있다).")
    print("  2) 파일에서 값을 제거하고 환경변수 참조로 바꾼다 (docs/ENV_SETUP.md).")
    print("  3) 커밋된 적이 있으면 이력에도 남아 있으므로 사용자에게 보고한다.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
