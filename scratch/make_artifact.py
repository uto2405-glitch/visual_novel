"""감상본 HTML → 아티팩트용(외곽 문서 태그 제거) 파일로 변환.

아티팩트는 <!doctype>/<head>/<body> 골격을 자동으로 감싸므로, <title>+<style>+본문+<script> 만 남긴다.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import export_viewer as ev  # noqa: E402

_, html = ev.build_html(include_all=False, max_edge=1400, quality=82)

# 외곽 문서 태그 제거 (아티팩트 스켈레톤이 대체)
html = re.sub(r'^<!DOCTYPE html>\s*<html[^>]*><head>.*?(<title>)', r'\1', html, flags=re.S)
html = html.replace("</style></head><body>", "</style>", 1)
html = re.sub(r'</body>\s*</html>\s*$', '', html)

out = ROOT / "output" / "viewer" / "artifact.html"
out.write_text(html, encoding="utf-8")
print("아티팩트용 저장:", out.relative_to(ROOT).as_posix(), f"({out.stat().st_size/1_000_000:.2f} MB)")
print("has doctype:", "<!DOCTYPE" in html, "| has <title>:", "<title>" in html[:200])
