#!/usr/bin/env python3
"""PWA 번들 내보내기 — 감상본을 '설치형 앱'(홈 화면 추가·오프라인)으로 패키징한다.

output/pwa/ 에 index.html + manifest.webmanifest + sw.js + 아이콘을 생성한다.
이 폴더를 정적 호스팅(GitHub Pages/Netlify 등)하면:
  ① 폰 브라우저에서 '홈 화면에 추가' → 앱 아이콘·전체화면·오프라인
  ② PWABuilder.com 에 그 URL 입력 → 실제 서명된 APK/AAB 다운로드 (로컬 안드로이드 SDK 불필요)

사용법:
  python tools/export_pwa.py            # 승인 장면
  python tools/export_pwa.py --all
  python tools/export_pwa.py --webp                     # 내장 이미지를 WebP 로(Pillow 있을 때)
  python tools/export_pwa.py --icon-from-cut            # 대표 컷으로 앱 아이콘 생성(Pillow 필요)
  python tools/export_pwa.py --icon-from-cut --icon-scene SCENE-004
읽기: project/·images/.  쓰기: output/pwa/ 만.  표준 라이브러리(+선택 Pillow).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core                                                     # noqa: E402
import export_viewer as ev                                         # noqa: E402
from vn_core import atomic_write_bytes, atomic_write_text          # noqa: E402

# 경로·원자적 쓰기·콘솔 방어는 vn_core 가 단일 출처(import 만으로 콘솔 보호가 걸린다).
ROOT = vn_core.ROOT
OUT = vn_core.OUTPUT / "pwa"
# 앱 색·아이콘 모양의 단일 출처는 감상본(export_viewer)이다 — PWA 는 그 감상본을 감싼
# 포장이므로 여기서 색을 따로 정하면 같은 작품이 경로마다 다른 앱으로 보인다.
THEME = ev.THEME
ICON_SIZES = (192, 512)
# maskable 아이콘의 '안전 영역' 은 한 변의 80% 원이다 — 안드로이드는 그 밖을 마음대로 깎는다
# (원형·물방울·사각 등 런처마다 다르다). 그래서 maskable 은 **피사체를 80% 로 줄여 배경에
# 앉힌 별도 파일**이어야 한다. 같은 파일에 purpose "any maskable" 을 붙이면 한 파일이 두
# 약속을 하게 되고, 컷으로 만든 아이콘에서는 안드로이드가 인물의 얼굴을 잘라 버린다.
MASKABLE_SAFE = 0.8

# 제목은 사용자 문자열이므로 템플릿 치환이 아니라 json.dumps 로 직렬화한다
# (따옴표·역슬래시·제어문자가 든 제목이 webmanifest 를 깨뜨리지 않게).
MANIFEST_BASE = {
    "start_url": "./index.html",
    "scope": "./",
    "display": "standalone",
    "orientation": "any",
    "lang": "ko",
    "dir": "ltr",
    "background_color": THEME,
    "theme_color": THEME,
    "description": "비주얼 노벨 소장본",
}


def icon_entries(from_cut: bool) -> list[dict]:
    """webmanifest 의 icons 배열 — **만든 방식에 따라** purpose 를 다르게 선언한다.

    기본 아이콘은 피사체가 없는 방사형 그라데이션이라 어느 모양으로 잘려도 잃는 것이 없다.
    그때는 한 파일이 둘 다 맡아도 거짓말이 아니다("any maskable").

    --icon-from-cut 으로 만든 아이콘은 다르다. 인물이 가운데 있는 컷을 정사각으로 자른
    그림이라, 안드로이드가 maskable 안전 영역(80%) 밖을 깎으면 **얼굴이 잘린다**.
    그래서 컷 아이콘은 "any" 로만 선언하고, maskable 은 여백을 준 별도 파일에 맡긴다.
    """
    out = [{"src": f"icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png",
            "purpose": "any" if from_cut else "any maskable"} for n in ICON_SIZES]
    if from_cut:
        out += [{"src": f"icon-{n}-maskable.png", "sizes": f"{n}x{n}", "type": "image/png",
                 "purpose": "maskable"} for n in ICON_SIZES]
    return out


def icon_files(from_cut: bool) -> list[str]:
    """번들에 실제로 놓이는 아이콘 파일 이름 — 서비스워커 캐시 목록과 같은 출처를 쓴다."""
    return [e["src"] for e in icon_entries(from_cut)]


# 결합열 도중에서 잘리면 안 되는 문자 — ZWJ, 변이 선택자(emoji/text presentation).
_JOINERS = "\u200d\ufe0f\ufe0e"   # ZWJ · 이모지 표현 선택자 — 보이지 않는 글자라 이스케이프로 적는다


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


def webmanifest(title: str, from_cut: bool = False) -> str:
    """webmanifest 문자열. 제목은 어떤 문자가 들어와도 유효한 JSON 으로 직렬화된다."""
    name = _clean_title(title) or "VN"
    data = {"name": name, "short_name": short_name(name)}
    data.update(MANIFEST_BASE)
    data["icons"] = icon_entries(from_cut)
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


SW = """// 오프라인 캐시(cache-first). CACHE 는 번들 내용의 sha256 — 내용이 바뀐 재배포에서만 갱신된다.
const CACHE = "vn-__VER__";
const ASSETS = __ASSETS__;
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

# 감상본 HTML 이 이미 theme-color·apple-mobile-web-app-* 를 들고 있다(같은 앱 겉모습).
# 여기서 다시 넣지 않고, PWA 에만 필요한 것 — webmanifest 링크와 **파일** 아이콘만 더한다.
# rel="icon" 이 없으면 브라우저는 선언되지 않은 파비콘을 **서버 루트에서** 찾는다 —
# 정적 호스팅에 올린 이 번들은 페이지를 열 때마다 /favicon.ico 404 를 남겼다. 번들에는
# 이미 같은 아이콘 파일이 있으므로 새로 만들 것 없이 선언만 하면 된다.
HEAD_INJECT = ('<link rel="manifest" href="manifest.webmanifest">'
               '<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">'
               '<link rel="icon" type="image/png" sizes="512x512" href="icon-512.png">'
               '<link rel="apple-touch-icon" href="icon-192.png">')
# 감상본의 인라인 data URI 아이콘(rel="icon" · apple-touch-icon)은 걷어낸다 — 같은 rel 이
# 둘이면 어느 쪽이 쓰일지 브라우저마다 달라, --icon-from-cut 으로 만든 아이콘이 조용히
# 무시될 수 있다. 번들 안에서는 **파일 아이콘 하나**만 남긴다.
INLINE_ICON_RE = re.compile(r'<link rel="(?:apple-touch-icon|icon)"[^>]*>')
SW_REG = ('<script>if("serviceWorker" in navigator){'
          'addEventListener("load",()=>navigator.serviceWorker.register("sw.js").catch(()=>{}))}</script>')


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


def _maskable_icon_bytes(img, size: int) -> bytes | None:
    """컷 아이콘의 **maskable 판** — 피사체를 안전 영역(80%)까지 줄이고 남는 자리를 앱 색으로 채운다.

    안드로이드는 maskable 아이콘을 런처 모양대로(원·물방울·둥근 사각) 깎는다. 여백 없는
    컷을 maskable 이라고 선언하면 깎이는 것은 대개 **인물의 머리와 턱**이다. 여백을 준 이
    파일이 그 약속을 대신 맡고, 원본 컷은 purpose "any" 로만 쓰인다.
    """
    try:
        from PIL import Image
        inner = max(1, int(round(size * MASKABLE_SAFE)))
        edge = (int(THEME[1:3], 16), int(THEME[3:5], 16), int(THEME[5:7], 16))
        base = Image.new("RGB", (size, size), edge)
        base.paste(img.resize((inner, inner), Image.LANCZOS),
                   ((size - inner) // 2, (size - inner) // 2))
        buf = io.BytesIO()
        base.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def _cut_icon_bytes(img, size: int) -> bytes | None:
    """대표 컷을 size×size PNG 바이트로. 실패하면 None(기본 아이콘 폴백)."""
    try:
        from PIL import Image
        buf = io.BytesIO()
        img.resize((size, size), Image.LANCZOS).save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def export(include_all: bool, max_edge: int, quality: int,
           cover_id: str | None = None, font_spec: str | None = None,
           icon_from_cut: bool = False, icon_scene: str | None = None,
           webp: bool = False, use_cache: bool = True) -> Path:
    data, html = ev.build_html(include_all, max_edge, quality, cover_id, font_spec,
                               webp, use_cache)
    html = INLINE_ICON_RE.sub("", html)      # 인라인 아이콘(둘) → 아래의 파일 아이콘으로
    html = html.replace("</head>", HEAD_INJECT + "</head>", 1)
    html = html.replace("</body>", SW_REG + "</body>", 1)

    # 아이콘이 대표 컷으로 만들어졌는지 **여기서** 판정하고 말한다. 예전에는 실패해도 조용히
    # 기본 아이콘으로 떨어진 뒤 main() 이 "대표 컷 중앙 크롭으로 생성" 이라고 알렸다 —
    # --icon-scene 에 없는 장면을 적어도 성공했다고 답하던 자리다.
    cut = None
    if icon_from_cut:
        src = _pick_cut(data, icon_scene)
        if src is None:
            print(f"  ⚠ 아이콘: {icon_scene or '대표 컷'} 에 해당하는 이미지가 없습니다 "
                  "— 기본 아이콘을 씁니다.")
        else:
            cut = _square_image(src)
            if cut is None:
                print("  ⚠ 아이콘: 컷을 다룰 수 없어(Pillow 없음 또는 해석 실패) "
                      "기본 아이콘을 씁니다.")
    icons: dict[str, bytes] = {}
    from_cut = False
    for size in ICON_SIZES:
        made = _cut_icon_bytes(cut, size) if cut is not None else None
        if made:
            from_cut = True
        icons[f"icon-{size}.png"] = made or ev.app_icon_png(size)
    if from_cut:
        # maskable 은 여백을 준 **별도 파일**이다. 만들지 못하면 기본 아이콘(피사체 없는
        # 그라데이션)이 그 자리를 맡는다 — 깎여도 잃을 것이 없는 그림이라 안전하다.
        for size in ICON_SIZES:
            icons[f"icon-{size}-maskable.png"] = (_maskable_icon_bytes(cut, size)
                                                  or ev.app_icon_png(size))
    export.last_icon_from_cut = from_cut      # main() 이 사실대로 보고하기 위한 값

    wm = webmanifest(data["title"], from_cut)
    # 서비스워커가 캐시할 목록은 **실제로 쓰는 파일**에서 만든다(선언과 캐시가 갈리면
    # 오프라인에서 아이콘만 빠진 번들이 된다).
    assets = ["./", "./index.html", "./manifest.webmanifest"] + [f"./{n}" for n in icons]

    # 캐시 버전은 번들 내용의 sha256 — 내용이 같으면 재실행해도 그대로(불필요한 재캐시 방지)
    h = hashlib.sha256()
    h.update(html.encode("utf-8"))
    h.update(wm.encode("utf-8"))
    for name in sorted(icons):
        h.update(name.encode("utf-8"))
        h.update(icons[name])

    # 쓰기는 전부 원자적 — 중간에 끊겨도 반쯤 잘린 번들이 남지 않는다.
    atomic_write_text(OUT / "index.html", html)
    atomic_write_text(OUT / "manifest.webmanifest", wm)
    for name, blob in icons.items():
        atomic_write_bytes(OUT / name, blob)
    atomic_write_text(OUT / "sw.js", (SW.replace("__ASSETS__", json.dumps(assets))
                                      .replace("__VER__", h.hexdigest()[:12])))
    # 지난 실행이 남긴 아이콘은 지운다 — 매니페스트가 선언하지 않는 파일이 폴더에 남아 있으면
    # 다음 사람이 그것을 앱 아이콘으로 착각한다(컷→기본으로 되돌렸을 때 실제로 생긴다).
    for stale in OUT.glob("icon-*.png"):
        if stale.name not in icons:
            stale.unlink()
    return OUT


def main() -> int:
    ap = argparse.ArgumentParser(description="PWA(설치형 앱) 번들 내보내기")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-edge", type=int, default=1600)
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--webp", action="store_true",
                    help="(Pillow 있을 때) 내장 이미지를 WebP 로 — 같은 화질에서 더 작다")
    ap.add_argument("--no-cache", action="store_true",
                    help="이미지 재인코딩 캐시를 쓰지 않고 매번 다시 굽는다")
    ap.add_argument("--cover", metavar="SCENE-ID", help="표지 커버 CG 로 쓸 장면")
    ap.add_argument("--embed-font", nargs="?", const="auto", metavar="PATH",
                    help="한글 폰트 임베드(기본 꺼짐)")
    ap.add_argument("--icon-from-cut", action="store_true",
                    help="앱 아이콘을 대표 승인 컷으로 생성(Pillow 없으면 기본 아이콘)")
    ap.add_argument("--icon-scene", metavar="SCENE-ID", help="아이콘에 쓸 장면(기본: 표지 컷)")
    args = ap.parse_args()
    try:
        out = export(args.all, args.max_edge, args.quality, args.cover, args.embed_font,
                     args.icon_from_cut, args.icon_scene, args.webp, not args.no_cache)
    except RuntimeError as exc:      # VNError 포함
        print(f"오류: {exc}")
        return 1
    total = sum(f.stat().st_size for f in out.glob("*") if f.is_file())
    print(f"PWA 번들 생성: {out.relative_to(ROOT).as_posix()}/ ({total / 1_000_000:.2f} MB)")
    print("  " + " · ".join(["index.html", "manifest.webmanifest", "sw.js"]
                            + sorted(f.name for f in out.glob("icon-*.png"))))
    if args.icon_from_cut:
        if getattr(export, "last_icon_from_cut", False):
            print("  아이콘: 대표 컷 중앙 크롭으로 생성")
        elif not ev.has_pillow():
            print("  아이콘: Pillow 가 없어 기본 아이콘으로 폴백 (pip install pillow)")
        else:
            print("  아이콘: 기본 아이콘으로 폴백 (위 경고 참고)")
    print("다음: 이 폴더를 정적 호스팅 → 폰에서 '홈 화면에 추가' 또는 PWABuilder.com 으로 APK 생성.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
