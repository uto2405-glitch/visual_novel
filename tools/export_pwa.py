#!/usr/bin/env python3
"""PWA 번들 내보내기 — 감상본을 '설치형 앱'(홈 화면 추가·오프라인)으로 패키징한다.

output/pwa/ 에 index.html + manifest.webmanifest + sw.js + 아이콘을 생성한다.
이 폴더를 정적 호스팅(GitHub Pages/Netlify 등)하면:
  ① 폰 브라우저에서 '홈 화면에 추가' → 앱 아이콘·전체화면·오프라인
  ② PWABuilder.com 에 그 URL 입력 → 실제 서명된 APK/AAB 다운로드 (로컬 안드로이드 SDK 불필요)

사용법:
  python tools/export_pwa.py            # 승인 장면
  python tools/export_pwa.py --all
읽기: project/·images/.  쓰기: output/pwa/ 만.  표준 라이브러리(+선택 Pillow).
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import export_viewer as ev  # noqa: E402

OUT = ROOT / "output" / "pwa"
THEME = "#17110D"
ACCENT = (224, 166, 75)

MANIFEST = """{
  "name": "__TITLE__",
  "short_name": "__SHORT__",
  "start_url": "./index.html",
  "scope": "./",
  "display": "standalone",
  "orientation": "any",
  "background_color": "#17110D",
  "theme_color": "#17110D",
  "description": "비주얼 노벨 소장본",
  "icons": [
    {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
    {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
  ]
}
"""

SW = """// 오프라인 캐시(cache-first). 재배포 시 CACHE 버전만 올리면 갱신.
const CACHE = "vn-__VER__";
const ASSETS = ["./", "./index.html", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(res => {
    const copy = res.clone();
    caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
    return res;
  }).catch(() => caches.match("./index.html"))));
});
"""

HEAD_INJECT = ('<link rel="manifest" href="manifest.webmanifest">'
               '<meta name="theme-color" content="#17110D">'
               '<link rel="apple-touch-icon" href="icon-192.png">'
               '<meta name="apple-mobile-web-app-capable" content="yes">'
               '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">')
SW_REG = ('<script>if("serviceWorker" in navigator){'
          'addEventListener("load",()=>navigator.serviceWorker.register("sw.js").catch(()=>{}))}</script>')


def _icon(path: Path, size: int) -> None:
    """단순 방사형 그라데이션 앱 아이콘(투명 없음, maskable 안전)."""
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    cx = cy = size / 2
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / (size / 2)
            t = min(1.0, d)
            r = int(ACCENT[0] * (1 - t) + 0x17 * t)
            g = int(ACCENT[1] * (1 - t) + 0x11 * t)
            b = int(ACCENT[2] * (1 - t) + 0x0D * t)
            rows += bytes((r, g, b))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))


def export(include_all: bool, max_edge: int, quality: int) -> Path:
    data, html = ev.build_html(include_all, max_edge, quality)
    html = html.replace("</head>", HEAD_INJECT + "</head>", 1)
    html = html.replace("</body>", SW_REG + "</body>", 1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    title = data["title"]
    short = (title[:12]) or "VN"
    (OUT / "manifest.webmanifest").write_text(
        MANIFEST.replace("__TITLE__", title).replace("__SHORT__", short), encoding="utf-8")
    ver = str(abs(hash(html)) % 100000)  # 내용 바뀌면 캐시 버전 변경
    (OUT / "sw.js").write_text(SW.replace("__VER__", ver), encoding="utf-8")
    _icon(OUT / "icon-192.png", 192)
    _icon(OUT / "icon-512.png", 512)
    return OUT


def main() -> int:
    ap = argparse.ArgumentParser(description="PWA(설치형 앱) 번들 내보내기")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-edge", type=int, default=1600)
    ap.add_argument("--quality", type=int, default=85)
    args = ap.parse_args()
    try:
        out = export(args.all, args.max_edge, args.quality)
    except RuntimeError as exc:
        print(f"오류: {exc}")
        return 1
    total = sum(f.stat().st_size for f in out.glob("*"))
    print(f"PWA 번들 생성: {out.relative_to(ROOT).as_posix()}/ ({total / 1_000_000:.2f} MB)")
    print("  index.html · manifest.webmanifest · sw.js · icon-192/512.png")
    print("다음: 이 폴더를 정적 호스팅 → 폰에서 '홈 화면에 추가' 또는 PWABuilder.com 으로 APK 생성.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
