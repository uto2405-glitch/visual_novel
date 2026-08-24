#!/usr/bin/env python3
"""xAI API 자동 오케스트레이션 (선택 기능) — 입력 조립 → API 호출 → 저장 → 상태 전이를 한 번에.

사용법:
  python tools/grok_api.py SCENE-001            # API 호출 + set-prompt 자동
  python tools/grok_api.py SCENE-001 --dry-run  # 호출 없이 입력만 확인

전제 (README "Grok 연동 모드" 참고):
  * SuperGrok 구독에는 API 가 포함되지 않는다. console.x.ai 에서 별도 키 발급 필요.
  * 키는 오직 환경변수 XAI_API_KEY 로만 주입한다.
      Windows cmd :  set XAI_API_KEY=발급받은키
      PowerShell  :  $env:XAI_API_KEY="발급받은키"
      mac/Linux   :  export XAI_API_KEY=발급받은키
  * 키를 .env 를 포함한 어떤 파일에도 저장하지 않는다. 서드파티 CLI/에이전트에
    키를 넘기지 않는다. (2026-07 Grok Build CLI 평문 전송 사고 — CLAUDE.md 금지 조항)
  * 모델명은 project/manifest.json 의 orchestrator.api.model 에 지정한다.
    (모델 목록은 docs.x.ai 에서 확인 — 명칭이 수시로 바뀌므로 하드코딩하지 않는다)

의존성: 표준 라이브러리만 사용 (urllib).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advance_scene as adv          # noqa: E402  (apply_prompt 등 공용 로직 재사용)
import xai_client                    # noqa: E402  (단일 API 호출 경로)
from make_grok_input import build_input  # noqa: E402

adv._console_guard()

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "project" / "grok_outputs"
KEY_ENV = xai_client.KEY_ENV



def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    sid = args[0]
    dry = "--dry-run" in args

    try:
        text = build_input(sid)
    except FileNotFoundError as exc:
        print(f"오류: {exc}")
        return 2

    if dry:
        print(text)
        print("-" * 56)
        print("(--dry-run: API 를 호출하지 않았습니다)")
        return 0

    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"오류: 환경변수 {KEY_ENV} 가 비어 있습니다.")
        print("SuperGrok 구독에는 API 가 포함되지 않습니다 — 두 가지 선택지:")
        print("  1) 수동 모드(무료): python tools/make_grok_input.py 결과를 grok.com 에 붙여넣기")
        print("  2) API 모드: console.x.ai 에서 키 발급 후 환경변수로 주입 (위 사용법 참고)")
        return 2

    try:
        base, model = xai_client.config()
        print(f"호출: {base} / model={model} / scene={sid} ...")
        out = xai_client.chat([{"role": "user", "content": text}])
    except RuntimeError as exc:
        print(f"오류: {exc}")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / f"{sid}.txt"
    out_file.write_text(out + "\n", encoding="utf-8")

    print(f"저장: {out_file.relative_to(ROOT)}")
    adv.apply_prompt(sid, out)   # 수동 모드 set-prompt 와 동일 경로 (단일 소스)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
