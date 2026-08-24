#!/usr/bin/env python3
"""PWA 번들 내보내기 — 감상본을 '설치형 앱'(홈 화면 추가·오프라인)으로 패키징한다.

output/pwa/ 에 index.html + manifest.webmanifest + sw.js + 아이콘을 생성한다.
이 폴더를 정적 호스팅(GitHub Pages/Netlify 등)하면:
  ① 폰 브라우저에서 '홈 화면에 추가' → 앱 아이콘·전체화면·오프라인
  ② PWABuilder.com 에 그 URL 입력 → 실제 서명된 APK/AAB 다운로드 (로컬 안드로이드 SDK 불필요)

사용법:
  python tools/export_pwa.py            # 승인 장면
  python tools/export_pwa.py --all
  python tools/export_pwa.py --icon-from-cut            # 대표 컷으로 앱 아이콘 생성(Pillow 필요)
  python tools/export_pwa.py --icon-from-cut --icon-scene SCENE-004
읽기: project/·images/.  쓰기: output/pwa/ 만.  표준 라이브러리(+선택 Pillow).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
import unicodedata
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import export_viewer as ev  # noqa: E402

OUT = ROOT / "output" / "pwa"
THEME = "#17110D"
ACCENT = (224, 166, 75)

# 제목은 사용자 문자열이므로 템플릿 치환이 아니라 json.dumps 로 직렬화한다
# (따옴표·역슬래시·제어문자가 든 제목이 webmanifest 를 깨뜨리지 않게).
MANIFEST_BASE = {
    "start_url": "./index.html",
    "scope": "./",
    "display": "standalone",
    "orientation": "any",
    "background_color": THEME,
    "theme_color": THEME,
    "description": "비주얼 노벨 소장본",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}

# 결합열 도중에서 잘리면 안 되는 문자 — ZWJ, 변이 선택자(emoji/text presentation).
_JOINERS = "\u200d\ufe0f\ufe0e"


def _clean_title(title: str) -> str:
    """서로게이트·제어문자를 제거한 안전한 제목. (UTF-8 로 쓸 수 없는 문자가 섞이면 저장 자체가 실패한다)"""
    return "".join(ch for ch in str(title)
                   if unicodedata.category(ch) not in ("Cs", "Cc")).strip()


def short_name(title: str, limit: int = 12) -> str:
    """홈 화면 아이콘 밑에 뜨는 짧은 이름. 이모지 결합열을 중간에서 자르지 않는다."""
    s = _clean_title(title)
    if len(s) <= limit:
        return s or "VN"
    cut = s[:limit]
    while cut and (unicodedata.combining(cut[-1]) or cut[-1] in _JOINERS
                   or 0x1F3FB <= ord(cut[-1]) <= 0x1F3FF):     # 피부색 수정자
        cut = cut[:-1]
    ri = 0                                                     # 국기: 지역 표시자 2개가 한 글자
    while ri < len(cut) and 0x1F1E6 <= ord(cut[-1 - ri]) <= 0x1F1FF:
        ri += 1
    if ri % 2:
        cut = cut[:-1]
    return cut.strip() or "VN"


def webmanifest(title: str) -> str:
    """webmanifest 문자열. 제목은 어떤 문자가 들어와도 유효한 JSON 으로 직렬화된다."""
    name = _clean_title(title) or "VN"
    data = {"name": name, "short_name": short_name(name)}
    data.update(MANIFEST_BASE)
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

SW = """// 오프라인 캐시(cache-first). CACHE 는 번들 내용의 sha256 — 내용이 바뀐 재배포에서만 갱신된다.
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


def _pick_cut(data: dict, scene_id: str | None):
    """아이콘으로 쓸 대표 컷의 data URI. 지정이 없으면 표지 커버와 같은 컷."""
    scenes = data.get("scenes") or []
    if scene_id:
        for s in scenes:
            if s.get("id") == scene_id and s.get("img"):
                return s["img"]
        return None
    cover = data.get("cover")
    if isinstance(cover, int) and 0 <= cover < len(scenes) and scenes[cover].get("img"):
        return scenes[cover]["img"]
    for s in scenes:
        if s.get("img"):
            return s["img"]
    return None


def _square_image(data_uri: str):
    """data URI → 정사각 중앙 크롭 이미지. Pillow 가 없거나 실패하면 None(기본 아이콘 폴백)."""
    try:
        from PIL import Image
        import io
    except ImportError:
        return None
    try:
        raw = base64.b64decode(data_uri.split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            img = im.convert("RGB")
        w, h = img.size
        e = min(w, h)
        # 인물이 위쪽에 오는 세로 컷이 많아 중앙보다 조금 위를 잡는다
        top = max(0, int((h - e) * 0.32))
        return img.crop(((w - e) // 2, top, (w - e) // 2 + e, top + e))
    except Exception:
        return None


def _icon_from_cut(img, path: Path, size: int) -> bool:
    try:
        from PIL import Image
        out = img.resize((size, size), Image.LANCZOS)
        out.save(path, format="PNG", optimize=True)
        return True
    except Exception:
        return False


def export(include_all: bool, max_edge: int, quality: int,
           cover_id: str | None = None, font_spec: str | None = None,
           icon_from_cut: bool = False, icon_scene: str | None = None) -> Path:
    data, html = ev.build_html(include_all, max_edge, quality, cover_id, font_spec)
    html = html.replace("</head>", HEAD_INJECT + "</head>", 1)
    html = html.replace("</body>", SW_REG + "</body>", 1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    wm = webmanifest(data["title"])
    (OUT / "manifest.webmanifest").write_text(wm, encoding="utf-8")

    cut = _square_image(_pick_cut(data, icon_scene) or "") if icon_from_cut else None
    for size in (192, 512):
        p = OUT / f"icon-{size}.png"
        if not (cut is not None and _icon_from_cut(cut, p, size)):
            _icon(p, size)   # Pillow 없음·컷 없음 → 기존 기본 아이콘

    # 캐시 버전은 번들 내용의 sha256 — 내용이 같으면 재실행해도 그대로(불필요한 재캐시 방지)
    h = hashlib.sha256()
    h.update(html.encode("utf-8"))
    h.update(wm.encode("utf-8"))
    for size in (192, 512):
        h.update((OUT / f"icon-{size}.png").read_bytes())
    (OUT / "sw.js").write_text(SW.replace("__VER__", h.hexdigest()[:12]), encoding="utf-8")
    return OUT


def main() -> int:
    ap = argparse.ArgumentParser(description="PWA(설치형 앱) 번들 내보내기")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-edge", type=int, default=1600)
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--cover", metavar="SCENE-ID", help="표지 커버 CG 로 쓸 장면")
    ap.add_argument("--embed-font", nargs="?", const="auto", metavar="PATH",
                    help="한글 폰트 임베드(기본 꺼짐)")
    ap.add_argument("--icon-from-cut", action="store_true",
                    help="앱 아이콘을 대표 승인 컷으로 생성(Pillow 없으면 기본 아이콘)")
    ap.add_argument("--icon-scene", metavar="SCENE-ID", help="아이콘에 쓸 장면(기본: 표지 컷)")
    args = ap.parse_args()
    try:
        out = export(args.all, args.max_edge, args.quality, args.cover, args.embed_font,
                     args.icon_from_cut, args.icon_scene)
    except RuntimeError as exc:
        print(f"오류: {exc}")
        return 1
    total = sum(f.stat().st_size for f in out.glob("*"))
    print(f"PWA 번들 생성: {out.relative_to(ROOT).as_posix()}/ ({total / 1_000_000:.2f} MB)")
    print("  index.html · manifest.webmanifest · sw.js · icon-192/512.png")
    if args.icon_from_cut:
        try:
            import PIL  # noqa: F401
            print("  아이콘: 대표 컷 중앙 크롭으로 생성")
        except ImportError:
            print("  아이콘: Pillow 가 없어 기본 아이콘으로 폴백 (pip install pillow)")
    print("다음: 이 폴더를 정적 호스팅 → 폰에서 '홈 화면에 추가' 또는 PWABuilder.com 으로 APK 생성.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
