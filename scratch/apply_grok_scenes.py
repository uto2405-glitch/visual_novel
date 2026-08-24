import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import vn_compose  # noqa: E402

text = (ROOT / "scratch" / "grok_scenes.json").read_text(encoding="utf-8")
r = vn_compose.compose_from_json(text, force=True, expected=10)
print(f"{len(r['created'])}개 장면 생성: {', '.join(r['created'])}")
print("검사:", r["checker"])
