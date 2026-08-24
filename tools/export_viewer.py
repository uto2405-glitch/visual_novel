#!/usr/bin/env python3
"""타임캡슐 감상본 내보내기 — 승인 장면+이미지+VN 뷰어를 단일 HTML 로 굽는다.

서버·폰트·네트워크 없이 어디서든(폰 포함) 열리는 자족 파일. 이미지가 base64 로 내장되어
파일 하나가 곧 디지털 소장본이다. VN 모드(타자기·자동/스킵·이어보기·선택지 affection·
분기·엔딩·백로그·장면 이동·시네마틱·설정)와 세로 스크롤 웹툰 모드, 화(episode) 구분을 포함한다.

재생 엔진은 스튜디오와 공용이다: ``tools/vn_runtime.js`` 를 빌드할 때 __RUNTIME__ 자리에
그대로 인라인하므로 단일 HTML 자기완결 성질(외부 요청 0)은 그대로다. 이 파일이 만드는
``build_data()`` 의 모양이 두 화면이 함께 쓰는 정본 데이터 스키마다.

사용법:
  python tools/export_viewer.py                # 승인 장면
  python tools/export_viewer.py --all          # selected_image 있는 전부
  python tools/export_viewer.py --max-edge 1600 --quality 85   # (Pillow 있을 때) 재인코딩 크기/화질
  python tools/export_viewer.py --webp                         # (Pillow 있을 때) WebP 로 더 작게
  python tools/export_viewer.py --cover SCENE-004              # 표지 커버 CG 지정
  python tools/export_viewer.py --embed-font                   # assets/fonts 의 폰트 임베드(기본 꺼짐)
  python tools/export_viewer.py --no-cache                     # 이미지 재인코딩 캐시 무시

출력: output/viewer/<제목>.html   (쓰기: output/ 만. Pillow·fontTools 는 선택 — 있으면 용량 최적화)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html as _html
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core                                          # noqa: E402
from vn_core import (VNError, atomic_write_text,        # noqa: E402
                     load_json_safe, load_manifest, safe_slug)

# 경로·JSON·원자적 쓰기·콘솔 방어는 vn_core 가 단일 출처다(import 만으로 콘솔 보호가 걸린다).
ROOT = vn_core.ROOT
MANIFEST = vn_core.MANIFEST
SCENES = vn_core.SCENES
OUT_DIR = vn_core.OUTPUT / "viewer"
# 스튜디오 뷰어와 공용인 VN 재생 엔진. 감상본은 이 파일을 인라인해 자기완결을 유지한다.
RUNTIME_JS = vn_core.TOOLS / "vn_runtime.js"

# 재인코딩 캐시 — 같은 원본·같은 옵션이면 다시 굽지 않는다(output/ 안, 점 폴더라 목록에서 감춰짐).
CACHE_DIR = vn_core.OUTPUT / ".cache" / "viewer"
CACHE_MAX = 160          # 오래된 항목부터 정리하는 상한(옵션을 바꿔가며 굽는 경우 대비)

NAME_COLORS = ["#5FB39A", "#D9A441", "#C77DBB", "#6FA8DC", "#E07A5F", "#84C18B", "#B58BE0", "#E0A458"]

# 폰트 임베드(옵션) — 확장자 → (mime, css format)
FONT_EXT = {".woff2": ("font/woff2", "woff2"), ".woff": ("font/woff", "woff"),
            ".ttf": ("font/ttf", "truetype"), ".otf": ("font/otf", "opentype")}
FONT_DIRS = ("assets/fonts", "fonts")
# 서브셋 시 반드시 살려야 하는 UI 문자(본문 글자와 별개).
# 표지·스크롤 모드(이 파일)와 재생 엔진(tools/vn_runtime.js)이 쓰는 문구를 모두 덮어야 한다 —
# 빠뜨리면 폰트 임베드 시 그 글자만 네모로 보인다.
UI_TEXT = ("VISUAL NOVEL · 소장본 처음부터 감상 ▸ 이어보기 세로 스크롤로 읽기 화 선택 VN 모드 "
           "비주얼 노벨 뷰어 감상 도구 자동 스킵 장면 기록 설정 숨기기 전체화면 닫기 대사 선택지 "
           "지난 대사 장면 이동 텍스트 속도 즉시 자동 진행 딜레이 초 글자 크기 화 이동 목록 "
           "스킵이 안 읽은 대사도 건너뜀 끄면 새 대사에서 자동 정지 시네마틱 모드 비네트 레터박스 "
           "탭/Space 진행 ← 이전 L C S Esc 갤러리 처음부터 ENDING 엔딩 — "
           "아직 지나온 대사가 없습니다. 지금 읽음 새 장면 — 끝 — 탭하면 닫힙니다 "
           "위아래 화살표로 고르고 Enter 선택지를 먼저 고르세요. 그만 보려면 버튼을 누르세요. "
           "호감도 올라감 내려감 감상 완료 개 장면 오프라인 자족 파일 "
           "이미지 없음 이미지를 불러올 수 없음 ♥ ()[]「」『』…,.!?~-—:;\"'%/ "
           "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def html_escape(text: str) -> str:
    """HTML 본문/속성에 넣어도 안전한 문자열. (제목처럼 사람이 정한 값도 그대로 믿지 않는다)"""
    return _html.escape(str(text), quote=True)


def char_color(cid: str) -> str:
    h = 0
    for c in str(cid):
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return NAME_COLORS[h % len(NAME_COLORS)]


# ------------------------------------------------------------ 이미지 → data URI (+캐시)
_PIL = None            # None=미확인 / False=없음 / 모듈=있음
_MEMO: dict[str, str | None] = {}


def _pillow():
    """Pillow 를 한 번만 찾아 기억한다. 없으면 None(원본 바이트 그대로 내장)."""
    global _PIL
    if _PIL is None:
        try:
            from PIL import Image
            _PIL = Image
        except ImportError:
            _PIL = False
    return _PIL or None


def has_pillow() -> bool:
    """Pillow 로 재인코딩(축소·JPEG/WebP)이 가능한가. 없으면 원본을 그대로 내장한다."""
    return _pillow() is not None


def _mime_of(path: Path) -> str:
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp"}.get(path.suffix.lower().lstrip("."), "application/octet-stream")


def _cache_key(path: Path, st, max_edge: int, quality: int, fmt: str) -> str:
    """원본(경로·크기·수정시각)과 인코딩 옵션이 모두 같을 때만 같은 키가 된다."""
    h = hashlib.sha1()
    h.update(str(path).encode("utf-8", "replace"))
    h.update(f"|{st.st_size}|{st.st_mtime_ns}|{max_edge}|{quality}|{fmt}"
             f"|{'pil' if _pillow() else 'raw'}".encode("ascii"))
    return h.hexdigest()


def _cache_read(key: str) -> str | None:
    try:
        return (CACHE_DIR / f"{key}.txt").read_text(encoding="ascii")
    except OSError:
        return None


def _cache_write(key: str, uri: str) -> None:
    try:
        atomic_write_text(CACHE_DIR / f"{key}.txt", uri)
    except (OSError, VNError):
        pass          # 캐시는 있으면 좋은 것 — 못 써도 내보내기는 계속된다


def prune_cache(keep: int = CACHE_MAX) -> int:
    """캐시가 무한히 자라지 않게 오래된 항목부터 지운다. → 지운 개수."""
    try:
        files = sorted(CACHE_DIR.glob("*.txt"), key=lambda f: f.stat().st_mtime)
    except OSError:
        return 0
    dropped = 0
    for f in files[:max(0, len(files) - keep)]:
        try:
            f.unlink()
            dropped += 1
        except OSError:
            pass
    return dropped


def _encode(path: Path, max_edge: int, quality: int, fmt: str) -> str | None:
    """실제 인코딩(캐시 미스일 때만 호출). Pillow 없으면 원본 바이트."""
    Image = _pillow()
    if Image is not None:
        try:
            with Image.open(path) as im:
                im.load()
                img = im.convert("RGB")
            if max(img.size) > max_edge:
                img.thumbnail((max_edge, max_edge), Image.LANCZOS)
            buf = io.BytesIO()
            if fmt == "webp":
                img.save(buf, format="WEBP", quality=quality, method=4)
                mime = "image/webp"
            else:
                img.save(buf, format="JPEG", quality=quality)
                mime = "image/jpeg"
            return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return f"data:{_mime_of(path)};base64," + base64.b64encode(raw).decode("ascii")


def image_data_uri(path: Path, max_edge: int, quality: int,
                   fmt: str = "jpeg", use_cache: bool = True) -> str | None:
    """이미지 → data URI.

    같은 원본·같은 옵션이면 다시 굽지 않는다: 프로세스 안에서는 메모, 실행 사이에는
    output/.cache/viewer 의 파일 캐시를 쓴다(감상본 + PWA 를 잇달아 내보낼 때가 특히 빠르다).
    Pillow 가 있으면 JPEG/WebP 로 재인코딩해 용량을 줄이고, 없으면 원본을 그대로 내장한다.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    fmt = "webp" if fmt == "webp" else "jpeg"
    key = _cache_key(path, st, max_edge, quality, fmt)
    if key in _MEMO:
        return _MEMO[key]
    uri = _cache_read(key) if use_cache else None
    if uri is None:
        uri = _encode(path, max_edge, quality, fmt)
        if uri and use_cache:
            _cache_write(key, uri)
    _MEMO[key] = uri
    return uri


# ------------------------------------------------------------------ 장면 수집
def prune_dangling_gotos(scenes: list) -> list:
    """감상본에 실리지 않은 장면을 가리키는 goto 를 정리한다. → 경고 문구 목록.

    이미지 없는 장면은 payload 에서 빠지는데 goto 는 그대로 남아, 재생기가 목적지를 찾지 못하고
    선택 직후 이야기가 멈춘다. 선택지는 goto 만 떼어 선형 진행으로 폴백시키고(선택 자체는 살린다),
    조건 분기는 해당 항목을 지운다. 무엇을 떨어뜨렸는지 반드시 호출자가 알리게 한다.
    """
    ids = {s.get("id") for s in scenes}
    warns: list[str] = []
    for s in scenes:
        sid = s.get("id", "?")
        if isinstance(s.get("choices"), list):
            fixed = []
            for c in s["choices"]:
                if isinstance(c, dict) and c.get("goto") and c["goto"] not in ids:
                    label = str(c.get("text", "")).strip()[:18] or "(무제)"
                    warns.append(f"{sid}: 선택지 '{label}' 의 goto {c['goto']} 가 감상본에 없음 "
                                 f"— 다음 장면으로 이어지도록 폴백")
                    c = {k: v for k, v in c.items() if k != "goto"}
                fixed.append(c)
            s["choices"] = fixed
        if isinstance(s.get("branch"), list):
            kept = []
            for b in s["branch"]:
                if not isinstance(b, dict) or b.get("goto") not in ids:
                    tgt = b.get("goto") if isinstance(b, dict) else b
                    warns.append(f"{sid}: 분기 goto {tgt} 가 감상본에 없음 — 그 분기를 제거")
                    continue
                kept.append(b)
            if kept:
                s["branch"] = kept
            else:
                s.pop("branch", None)   # 분기가 모두 사라지면 선형 진행으로 되돌린다
                warns.append(f"{sid}: 분기가 모두 제거됨 — 선형 진행으로 이어짐")
    return warns


def ending_of(sc: dict) -> tuple[bool, str]:
    """엔딩 표기를 하나로 정규화한다 → (엔딩인가, 엔딩 이름).

    규약은 ``ending: true`` + 선택적 ``ending_label: "호감 엔딩"`` 이다.
    예전 데이터의 ``ending: "호감 엔딩"``(문자열)도 그대로 받아 label 로 옮긴다.
    """
    raw = sc.get("ending")
    label = str(sc.get("ending_label") or "").strip()
    if isinstance(raw, str):
        label = label or raw.strip()
        return bool(raw.strip()), label
    return bool(raw), label


def episode_of(sc: dict):
    """장면의 화 번호(정수)만 받아들인다. 없거나 형이 다르면 None."""
    ep = sc.get("episode")
    if isinstance(ep, bool) or not isinstance(ep, int):
        try:
            ep = int(str(ep).strip())
        except (TypeError, ValueError):
            return None
    return ep if ep > 0 else None


def episode_list(mf: dict, scenes: list) -> list:
    """감상본에 실제로 실린 화만, 매니페스트 제목을 붙여 번호순으로."""
    titles = {}
    for e in (mf.get("episodes") or []):
        if isinstance(e, dict):
            n = e.get("episode")
            if isinstance(n, int) and not isinstance(n, bool):
                titles[n] = str(e.get("title") or "").strip()
    present = sorted({s["ep"] for s in scenes if isinstance(s.get("ep"), int)})
    return [{"ep": n, "title": titles.get(n, "")} for n in present]


def build_data(include_all: bool, max_edge: int, quality: int, cover_id: str | None = None,
               webp: bool = False, use_cache: bool = True) -> dict:
    mf = load_manifest()
    if not mf:
        raise VNError("project/manifest.json 이 없거나 손상됐습니다.")
    chars = {c.get("character_id"): {"name": c.get("name") or c.get("character_id"),
                                     "color": char_color(c.get("character_id", ""))}
             for c in mf.get("characters", []) if isinstance(c, dict)}
    fmt = "webp" if webp else "jpeg"
    scenes = []
    missing = []
    for f in sorted(SCENES.glob("SCENE-*.json")) if SCENES.exists() else []:
        sc = load_json_safe(f, {})
        if not sc:
            continue
        assets = sc.get("assets") if isinstance(sc.get("assets"), dict) else {}
        sel = str(assets.get("selected_image") or "").strip()
        if not sel:
            continue
        if not include_all and sc.get("status") != "APPROVED":
            continue
        lines = []
        for d in (sc.get("dialogue") if isinstance(sc.get("dialogue"), list) else []):
            if not isinstance(d, dict):
                continue
            spk = d.get("speaker_id")
            info = chars.get(spk)
            lines.append({"n": info["name"] if info else "", "c": info["color"] if info else "",
                          "t": str(d.get("text", "")), "p": d.get("placement", "bottom")})
        img = image_data_uri(ROOT / sel, max_edge, quality, fmt, use_cache)
        if img is None:
            missing.append(f"{sc.get('scene_id', f.stem)}: 이미지 파일을 읽지 못함 ({sel})")
        entry = {"id": sc.get("scene_id", "?"), "order": sc.get("scene_order", 0),
                 "purpose": str(sc.get("purpose", "")), "img": img, "lines": lines}
        ep = episode_of(sc)
        if ep is not None:
            entry["ep"] = ep
        if isinstance(sc.get("choices"), list) and sc["choices"]:
            entry["choices"] = sc["choices"]
        if isinstance(sc.get("branch"), list) and sc["branch"]:
            entry["branch"] = sc["branch"]
        is_end, label = ending_of(sc)
        if is_end:
            entry["ending"] = True                 # 규약: 참/거짓만. 이름은 ending_label 로.
            if label:
                entry["ending_label"] = label
        scenes.append(entry)
    scenes.sort(key=lambda s: s.get("order") or 0)
    if not scenes:
        raise VNError("내보낼 장면이 없습니다. (selected_image 있는 APPROVED 장면 — --all 로 전체)")
    for w in missing + prune_dangling_gotos(scenes):
        print(f"  ⚠ {w}")
    if use_cache:
        prune_cache()
    dating = mf.get("dating") if isinstance(mf.get("dating"), dict) else None
    return {"title": mf.get("title") or "무제", "scenes": scenes, "dating": dating,
            "episodes": episode_list(mf, scenes), "cover": pick_cover(scenes, cover_id)}


def pick_cover(scenes: list, cover_id: str | None) -> int | None:
    """표지 커버로 쓸 장면 인덱스. 이미 내장된 이미지를 재사용해 용량 증가가 없다."""
    if cover_id:
        for i, s in enumerate(scenes):
            if s.get("id") == cover_id and s.get("img"):
                return i
    for i, s in enumerate(scenes):
        if s.get("img"):
            return i
    return None


# ------------------------------------------------------------------ 폰트(옵션)
def find_font(spec: str | None) -> Path | None:
    """--embed-font 값 해석. 'auto' 면 assets/fonts 에서 첫 폰트를 찾는다. 없으면 None(시스템 폰트 폴백)."""
    if not spec:
        return None
    if spec != "auto":
        p = Path(spec)
        if not p.is_absolute():
            p = ROOT / spec
        return p if p.is_file() and p.suffix.lower() in FONT_EXT else None
    for d in FONT_DIRS:
        dd = ROOT / d
        if not dd.is_dir():
            continue
        for f in sorted(dd.iterdir()):
            if f.is_file() and f.suffix.lower() in FONT_EXT:
                return f
    return None


def subset_font(path: Path, text: str):
    """fontTools 가 있으면 사용 문자만 남긴 서브셋 바이트를 만든다. 없으면 None(원본 통째 임베드)."""
    try:
        from fontTools import subset as ftsubset
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    for flavor, mime, fmt in (("woff2", "font/woff2", "woff2"),
                              ("woff", "font/woff", "woff"),
                              (None, "font/ttf", "truetype")):
        try:
            font = TTFont(str(path))
            opts = ftsubset.Options()
            opts.layout_features = ["*"]
            opts.notdef_outline = True
            sub = ftsubset.Subsetter(options=opts)
            sub.populate(text=text)
            sub.subset(font)
            font.flavor = flavor
            buf = io.BytesIO()
            font.save(buf)
            return buf.getvalue(), mime, fmt
        except Exception:
            continue
    return None


def font_css(path: Path | None, text: str) -> str:
    """@font-face + body 폰트 지정 CSS. 폰트가 없으면 빈 문자열(조용히 건너뜀)."""
    if not path:
        return ""
    made = subset_font(path, text)
    if made:
        raw, mime, fmt = made
        how = "서브셋"
    else:
        try:
            raw = path.read_bytes()
        except OSError:
            return ""
        mime, fmt = FONT_EXT[path.suffix.lower()]
        how = "원본(fontTools 없음 — pip install fonttools brotli 시 서브셋)"
    b64 = base64.b64encode(raw).decode("ascii")
    print(f"  폰트 임베드: {path.name} · {how} · {len(raw) / 1_000_000:.2f} MB")
    if len(raw) > 4_000_000:
        print("  ⚠ 폰트가 큽니다 — 감상본 용량이 그만큼 늘어납니다.")
    return ('@font-face{font-family:"VNKR";font-style:normal;font-weight:400;font-display:swap;'
            f'src:url(data:{mime};base64,{b64}) format("{fmt}")}}'
            '\nbody{font-family:"VNKR","Pretendard","Noto Sans KR","Malgun Gothic",system-ui,sans-serif}')


def used_text(data: dict) -> str:
    """서브셋 대상 문자 — 제목·대사·선택지·목적문·화 제목·엔딩 이름 + UI 문구."""
    parts = [str(data.get("title") or ""), UI_TEXT]
    for e in (data.get("episodes") or []):
        parts.append(str(e.get("title") or ""))
    for s in data.get("scenes", []):
        parts.append(str(s.get("purpose") or ""))
        parts.append(str(s.get("ending_label") or ""))
        for line in s.get("lines", []):
            parts.append(str(line.get("n") or ""))
            parts.append(str(line.get("t") or ""))
        for c in (s.get("choices") or []):
            if isinstance(c, dict):
                parts.append(str(c.get("text") or ""))
    return "".join(parts)


TEMPLATE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<style>
:root{--bg:#17110D;--ink:#EFE4D0;--sub:#A79680;--line:#3A2C1F;--amber:#E0A64B;
--paper:#F2E8D5;--pink:#241C14}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:"Pretendard","Noto Sans KR","Malgun Gothic",system-ui,sans-serif;
font-size:15px;line-height:1.6;-webkit-tap-highlight-color:rgba(224,166,75,.25)}
__FONTCSS__
button{font:inherit;cursor:pointer;touch-action:manipulation}
.sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
clip:rect(0 0 0 0);white-space:nowrap;border:0}
:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
#card{position:fixed;inset:0;z-index:5;display:flex;flex-direction:column;align-items:center;
justify-content:center;gap:14px;background:radial-gradient(120% 90% at 50% 40%,#241A12,#100B07);text-align:center;padding:20px}
#card h1{font-size:clamp(26px,7vw,44px);letter-spacing:-.01em;text-shadow:0 2px 18px rgba(0,0,0,.75)}
#card .sub{color:var(--sub);font-size:12px;letter-spacing:.25em}
#card button{background:var(--amber);color:#1B130C;border:none;border-radius:99px;padding:12px 30px;font-weight:700}
#card button.ghost{background:none;color:var(--sub);border:1px solid var(--line)}
#card.hide{display:none}
#eps{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;max-width:min(600px,94%)}
#eps[hidden]{display:none}
#eps button{background:rgba(30,24,18,.72);color:var(--ink);border:1px solid var(--line);
border-radius:99px;padding:8px 14px;font-size:12.5px;font-weight:600}
/* 표지 커버 CG — 내장 이미지 재사용(추가 용량 0) */
#cover{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.55}
#cover[hidden]{display:none}
#scrim{position:absolute;inset:0;
background:radial-gradient(115% 85% at 50% 38%,rgba(21,15,10,.42),rgba(14,10,6,.95))}
#card>*:not(#cover):not(#scrim){position:relative;z-index:1}
#stage{position:fixed;inset:0;background:#0E0A07;display:none}
#stage.on{display:block}
#img{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden}
#img img{max-width:100%;max-height:100%;object-fit:contain}
#img .empty{color:var(--sub);padding:26px;text-align:center}
#tap{position:absolute;inset:0;cursor:pointer}
#bar{position:absolute;top:10px;right:10px;display:flex;gap:6px;z-index:3;flex-wrap:wrap;justify-content:flex-end;
align-items:center}
#bar .b{background:rgba(30,24,18,.72);color:var(--ink);border:1px solid var(--line);border-radius:8px;
padding:7px 11px;font-size:12px;font-weight:600}
#bar .b.on{color:var(--amber);border-color:var(--amber)}
#prog{position:absolute;top:14px;left:12px;z-index:3;font-size:11px;color:var(--sub);
background:rgba(30,24,18,.72);border:1px solid var(--line);border-radius:99px;padding:4px 10px}
#dlg{position:absolute;left:50%;transform:translateX(-50%);bottom:18px;width:min(860px,93%);z-index:2;
background:var(--paper);color:var(--pink);border-radius:13px;padding:13px 18px;cursor:pointer;
box-shadow:0 16px 40px -14px rgba(0,0,0,.7)}
#dlg.top{bottom:auto;top:56px}
#dlg.narr{background:rgba(18,13,9,.82);color:var(--paper)}
#dlg.narr #txt{text-align:center;font-style:italic}
#who{display:inline-block;font-size:12px;font-weight:800;padding:2px 11px;border-radius:99px;margin-bottom:6px;color:#fff}
#txt{font-size:var(--dlg-fs,clamp(15px,2.4vw,18px));line-height:1.62;min-height:1.6em;white-space:pre-wrap;
max-height:34vh;overflow-y:auto;overflow-wrap:anywhere;word-break:keep-all;line-break:strict}
#aff{align-self:center;font-weight:700;color:#F2C0B6;background:rgba(196,61,43,.22);
border:1px solid #C43D2B;border-radius:99px;padding:4px 10px;font-size:12px;transition:transform .18s ease}
#aff.bump{transform:scale(1.16);background:rgba(196,61,43,.5)}
#choices{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:4;
display:flex;flex-direction:column;gap:12px;width:min(560px,88%)}
#choices[hidden]{display:none}
#choices button{background:rgba(24,18,12,.95);color:var(--ink);border:1px solid var(--amber);
border-radius:12px;padding:14px 18px;font:inherit;font-size:15px;cursor:pointer;text-align:left;
box-shadow:0 8px 24px -10px rgba(0,0,0,.7)}
#choices button:hover,#choices button:focus-visible{background:rgba(224,166,75,.22)}
/* 백로그(지난 대사) */
#log{position:absolute;inset:0;z-index:6;background:rgba(12,8,5,.95);display:flex;flex-direction:column}
#log[hidden]{display:none}
#logHead{display:flex;justify-content:space-between;align-items:center;gap:10px;
padding:12px 14px;border-bottom:1px solid var(--line)}
#logHead .b{background:rgba(30,24,18,.72);color:var(--ink);border:1px solid var(--line);
border-radius:8px;padding:7px 11px;font-size:12px;font-weight:600}
#logInner{flex:1;overflow-y:auto;padding:6px 12px 28px;-webkit-overflow-scrolling:touch}
#logInner .row{display:block;width:100%;text-align:left;background:none;border:none;color:inherit;
font:inherit;padding:11px 12px;border-bottom:1px solid var(--line);border-radius:8px;
word-break:keep-all;overflow-wrap:anywhere}
#logInner .row:hover,#logInner .row:focus-visible{background:rgba(224,166,75,.14)}
#logInner .row b{font-weight:800}
#logInner .row .nar{color:var(--sub);font-style:italic}
#logInner .none{color:var(--sub);padding:16px 12px}
/* 설정 오버레이 */
#set{position:absolute;inset:0;z-index:7;display:flex;align-items:flex-end;justify-content:center;
background:rgba(10,7,4,.72)}
#set[hidden]{display:none}
#set .panel{width:min(560px,100%);background:#20180F;border:1px solid var(--line);
border-radius:14px 14px 0 0;padding:14px 16px 20px;display:flex;flex-direction:column;gap:13px}
#set .head{display:flex;justify-content:space-between;align-items:center}
#set .row{display:flex;flex-direction:column;gap:7px}
#set .row[hidden]{display:none}
#set .lbl{color:var(--sub);font-size:12px;letter-spacing:.04em}
#set .seg{display:flex;gap:6px;flex-wrap:wrap}
#set .sb{background:rgba(30,24,18,.9);color:var(--ink);border:1px solid var(--line);
border-radius:9px;padding:9px 13px;font-size:13px}
#set .sb.on{color:var(--amber);border-color:var(--amber)}
#set .b{background:rgba(30,24,18,.72);color:var(--ink);border:1px solid var(--line);
border-radius:8px;padding:7px 11px;font-size:12px;font-weight:600}
@media(max-width:640px){
 #bar{flex-wrap:wrap;gap:5px;max-width:calc(100% - 16px)}
 #bar .b{padding:8px 10px;font-size:12px}
 #dlg{bottom:14px;padding:12px 15px} #dlg.top{top:52px}
 #txt{font-size:var(--dlg-fs,clamp(15px,4.2vw,18px));max-height:32vh}
 #choices{width:92%} #choices button{padding:13px 15px;font-size:14.5px}
}
#scroll{position:fixed;inset:0;background:var(--bg);display:none;overflow-y:auto;z-index:4;
-webkit-overflow-scrolling:touch}
#scroll.on{display:block}
#scroll .cut{max-width:820px;margin:0 auto}
#scroll .cut img{width:100%;display:block}
#scroll .say{padding:12px 18px;border-bottom:1px solid var(--line)}
#scroll .say b{font-weight:800}
#scroll .say .nar{color:var(--sub);font-style:italic;text-align:center;display:block}
#scroll .say .pick{color:var(--amber)}
#scroll .ep{padding:20px 18px 9px;color:var(--amber);font-weight:800;font-size:13px;
letter-spacing:.06em;border-bottom:1px solid var(--line)}
#scroll .topbar{position:sticky;top:0;background:rgba(23,17,13,.9);backdrop-filter:blur(4px);
padding:10px 14px;display:flex;justify-content:space-between;align-items:center;z-index:2;border-bottom:1px solid var(--line)}
#scroll .topbar .b{background:rgba(30,24,18,.72);color:var(--ink);border:1px solid var(--line);
border-radius:8px;padding:6px 10px;font-size:12px}
.small{color:var(--sub);font-size:12px}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
/* ---- safe-area(노치·홈바) — 대사창·버튼이 가려지지 않게 (마지막에 두어 우선) ---- */
body{padding-left:env(safe-area-inset-left);padding-right:env(safe-area-inset-right)}
#card{padding:calc(20px + env(safe-area-inset-top)) calc(20px + env(safe-area-inset-right))
 calc(20px + env(safe-area-inset-bottom)) calc(20px + env(safe-area-inset-left))}
#bar{top:calc(10px + env(safe-area-inset-top));right:calc(10px + env(safe-area-inset-right))}
#prog{top:calc(14px + env(safe-area-inset-top));left:calc(12px + env(safe-area-inset-left))}
#dlg{bottom:calc(18px + env(safe-area-inset-bottom))}
#dlg.top{top:calc(56px + env(safe-area-inset-top))}
#choices{padding-bottom:env(safe-area-inset-bottom)}
#logHead{padding-top:calc(12px + env(safe-area-inset-top))}
#logInner{padding-left:calc(12px + env(safe-area-inset-left));
 padding-right:calc(12px + env(safe-area-inset-right));
 padding-bottom:calc(28px + env(safe-area-inset-bottom))}
#set .panel{padding-bottom:calc(20px + env(safe-area-inset-bottom))}
#scroll .topbar{padding-top:calc(10px + env(safe-area-inset-top))}
#scroll .cut{padding-left:env(safe-area-inset-left);padding-right:env(safe-area-inset-right);
 padding-bottom:calc(44px + env(safe-area-inset-bottom))}
@media(max-width:640px){
 #dlg{bottom:calc(14px + env(safe-area-inset-bottom))}
 #dlg.top{top:calc(52px + env(safe-area-inset-top))}}
</style></head><body>
<div id="card">
<img id="cover" alt="" hidden><div id="scrim"></div>
<div class="sub">VISUAL NOVEL · 소장본</div>
<h1>__TITLE__</h1>
<div class="small" id="meta"></div>
<button id="bStart">처음부터 감상 ▸</button>
<button id="bResume" class="ghost" hidden>이어보기</button>
<button id="bScroll" class="ghost">세로 스크롤로 읽기</button>
<div id="eps" hidden role="group" aria-label="화 선택"></div>
</div>

<div id="stage">
<div id="img"></div><div id="tap"></div>
<span id="prog" aria-live="off"></span>
<div id="bar" role="toolbar" aria-label="감상 도구">
<span id="aff" hidden></span>
<button class="b" id="bAuto" aria-pressed="false">자동</button>
<button class="b" id="bLog" aria-expanded="false">기록</button>
<button class="b" id="bSet" aria-expanded="false">설정</button>
<button class="b" id="bToScroll">스크롤</button>
<button class="b" id="bExit">닫기</button></div>
<div id="choices" hidden role="group" aria-label="선택지"></div>
<div id="dlg" role="group" aria-label="대사"><span id="who"></span><div id="txt"></div>
<div class="small" style="text-align:right;margin-top:5px;opacity:.6">탭/Space 진행 · ← 이전 · L 기록 · S 설정 · Esc 닫기</div></div>
<div id="log" hidden role="dialog" aria-modal="true" aria-label="지난 대사">
<div id="logHead"><b>지난 대사</b>
<button class="b" id="bLogClose">닫기</button></div><div id="logInner"></div></div>
<div id="set" hidden role="dialog" aria-modal="true" aria-label="설정">
<div class="panel"><div class="head"><b>설정</b><button class="b" id="bSetClose">닫기</button></div>
<div class="row"><span class="lbl" id="lblFs">글자 크기</span>
<span class="seg" id="segFs" role="group" aria-labelledby="lblFs"></span></div>
<div class="row"><span class="lbl" id="lblSp">텍스트 속도</span>
<span class="seg" id="segSp" role="group" aria-labelledby="lblSp"></span></div>
<div class="row" id="rowEp" hidden><span class="lbl" id="lblEp">화 이동</span>
<span class="seg" id="segEp" role="group" aria-labelledby="lblEp"></span></div>
</div></div>
<span class="sr" id="srLine" aria-live="polite"></span>
</div>

<div id="scroll">
<div class="topbar"><b id="scTitle"></b>
<span><button class="b" id="bToVN">VN 모드</button>
<button class="b" id="bScExit">닫기</button></span></div>
<div class="cut" id="cuts"></div>
</div>

<script>
"use strict";
const DATA=__DATA__;
const $=id=>document.getElementById(id);
const el=(t,c,x)=>{const n=document.createElement(t);if(c)n.className=c;if(x!=null)n.textContent=x;return n};
const REDUCE=matchMedia("(prefers-reduced-motion: reduce)").matches;
const SPEEDS=[[0,"즉시"],[18,"빠름"],[28,"보통"],[46,"느림"]];
const FS=[[15,"작게"],[17,"보통"],[19,"크게"],[22,"아주 크게"]];
let vi=0,di=0,ended=false,revealing=false,timer=null,aTimer=null,autoOn=false,full="";
let aff=0,awaiting=false,path=[];        // 분기 엔진: 호감도 · 선택지 대기 · 지나온 장면
let hist=[],histKeys=new Set();          // 백로그(지난 대사)
const K={pos:"tc:pos:"+DATA.title,set:"tc:set:"+DATA.title,hist:"tc:hist:"+DATA.title};
let SET={sp:2,fs:1};
try{const s=JSON.parse(localStorage.getItem(K.set)||"{}");
 if(typeof s.sp==="number"&&SPEEDS[s.sp])SET.sp=s.sp;
 if(typeof s.fs==="number"&&FS[s.fs])SET.fs=s.fs}catch(e){}
function applyFs(){document.documentElement.style.setProperty("--dlg-fs",FS[SET.fs][0]+"px")}
function saveSet(){try{localStorage.setItem(K.set,JSON.stringify(SET))}catch(e){}}
function savePos(){try{localStorage.setItem(K.pos,JSON.stringify({vi,di,aff,path}))}catch(e){}}
function loadPos(){try{return JSON.parse(localStorage.getItem(K.pos)||"null")}catch(e){return null}}
function saveHist(){try{localStorage.setItem(K.hist,JSON.stringify(hist.slice(-500)))}catch(e){}}
function loadHist(){try{const h=JSON.parse(localStorage.getItem(K.hist)||"[]");return Array.isArray(h)?h:[]}catch(e){return []}}
const dlen=s=>(s.lines||[]).length||1;
const say=t=>{const n=$("srLine");if(n)n.textContent=t};

// ---- 화(episode) ----
const EPS=Array.isArray(DATA.episodes)?DATA.episodes:[];
const epTitle=ep=>{const e=EPS.find(x=>x.ep===ep);return e&&e.title?e.title:""};
const epLabel=ep=>ep+"화"+(epTitle(ep)?" · "+epTitle(ep):"");
const epFirst=ep=>DATA.scenes.findIndex(s=>s.ep===ep);

// ---- 분기 엔진(호감도·선택지·엔딩) ----
const affMax=()=>(DATA.dating&&DATA.dating.max)||100;
const affStart=()=>(DATA.dating&&typeof DATA.dating.start_affection==="number")?DATA.dating.start_affection:30;
const clampAff=v=>Math.max(0,Math.min(affMax(),v));
function updateAff(d){const m=$("aff");if(!DATA.dating){m.hidden=true;return}
 m.hidden=false;m.textContent="♥ "+aff+" / "+affMax()+(d?(d>0?"  +"+d:"  "+d):"");
 if(d){m.classList.add("bump");setTimeout(()=>{m.classList.remove("bump");
  m.textContent="♥ "+aff+" / "+affMax()},1100)}}
const idxOf=id=>DATA.scenes.findIndex(s=>s.id===id);
function nextIndex(sc){
 if(sc.branch&&sc.branch.length){   // 조건 만족하는 첫 분기로(위에서부터)
  for(const b of sc.branch){if(aff>=(b.min||0)){const i=idxOf(b.goto);if(i>=0)return i}}
  return -1}
 return vi+1<DATA.scenes.length?vi+1:-1}
function goTo(idx){path.push(vi);vi=idx;di=0;ended=false;renderImg();show()}
function hideChoices(){const box=$("choices");box.replaceChildren();box.hidden=true;
 awaiting=false;$("dlg").style.opacity=""}
function showChoices(sc){awaiting=true;clearTimeout(aTimer);
 const box=$("choices");box.replaceChildren();
 for(const c of sc.choices){const b=el("button",null,c.text||"…");b.onclick=()=>pick(c);box.appendChild(b)}
 box.hidden=false;$("dlg").style.opacity=".3";
 say("선택지 "+sc.choices.length+"개 · 위아래 화살표로 고르고 Enter");
 const first=box.querySelector("button");if(first)first.focus()}
function pick(c){hideChoices();
 const d=c.affection||0;if(d){aff=clampAff(aff+d)}updateAff(d);savePos();
 if(d)say(d>0?"호감도 "+d+" 올라감":"호감도 "+Math.abs(d)+" 내려감");
 const nx=c.goto?idxOf(c.goto):(vi+1<DATA.scenes.length?vi+1:-1);
 if(nx<0){end();return}goTo(nx)}

function renderImg(){const sc=DATA.scenes[vi],box=$("img");box.replaceChildren();
 if(!sc)return;
 if(sc.img){const im=el("img");im.src=sc.img;im.alt=sc.purpose||sc.id;box.appendChild(im)}
 else box.appendChild(el("div","empty",sc.purpose||sc.id))}
function type(t){clearInterval(timer);full=t;const e=$("txt");const ms=SPEEDS[SET.sp][0];
 if(REDUCE||ms<=0){e.textContent=t;e.scrollTop=e.scrollHeight;revealing=false;shown();return}
 revealing=true;const cs=[...t];let i=0;e.textContent="";
 timer=setInterval(()=>{i++;e.textContent=cs.slice(0,i).join("");e.scrollTop=e.scrollHeight;
  if(i>=cs.length){clearInterval(timer);revealing=false;shown()}},ms)}
function shown(){clearTimeout(aTimer);
 if(autoOn&&!awaiting&&!logOpen()&&!setOpen())aTimer=setTimeout(()=>adv(1),1400+full.length*22)}
function record(n,t,c){const k=vi+":"+di;if(histKeys.has(k))return;
 histKeys.add(k);hist.push({n:n,t:t,c:c,vi:vi,di:di});saveHist()}
function show(){const sc=DATA.scenes[vi];if(!sc)return;
 $("prog").textContent=(sc.ep?sc.ep+"화 · ":"")+(vi+1)+" / "+DATA.scenes.length
  +(dlen(sc)>1?" · "+(di+1)+"/"+dlen(sc):"");
 const line=(sc.lines||[])[di],dlg=$("dlg"),who=$("who");
 dlg.classList.toggle("top",!!(line&&line.p==="top"));
 if(line&&line.n){dlg.classList.remove("narr");who.style.display="inline-block";
  who.textContent=line.n;who.style.background=line.c||"#2F6B59";
  const h=(line.c||"").replace("#","");
  const lum=h.length>=6?(.299*parseInt(h.slice(0,2),16)+.587*parseInt(h.slice(2,4),16)+.114*parseInt(h.slice(4,6),16)):0;
  who.style.color=lum>150?"#17110D":"#fff";
  record(line.n,line.t||"",line.c||null);say(line.n+": "+(line.t||""))}
 else{dlg.classList.add("narr");who.style.display="none";
  record("",line?(line.t||""):(sc.purpose||""),null);say(line?(line.t||""):(sc.purpose||""))}
 type(line?line.t:(sc.purpose||"…"));savePos()}
function adv(step){
 if(setOpen()){closeSet();return}
 if(logOpen()){closeLog();return}
 if(awaiting)return;                       // 선택지 대기 중엔 선택해야 진행
 if(ended){exit();return}
 if(step>0&&revealing){clearInterval(timer);$("txt").textContent=full;revealing=false;shown();return}
 const sc=DATA.scenes[vi];if(!sc)return;clearTimeout(aTimer);
 if(step>0){
  if(di+1<dlen(sc)){di++;show();return}
  if(sc.choices&&sc.choices.length){showChoices(sc);return}   // 장면 끝 → 선택지
  if(sc.ending){end();return}                                 // 엔딩 장면
  const nx=nextIndex(sc);                                     // 분기 or 선형
  if(nx<0){end();return}
  goTo(nx);return}
 if(di>0){di--;show();return}
 const prev=path.length?path.pop():(vi>0?vi-1:-1);             // 분기 경로를 따라 되돌아감
 if(prev<0||prev>=DATA.scenes.length)return;
 vi=prev;di=dlen(DATA.scenes[vi])-1;ended=false;renderImg();show()}
function endLabel(sc){if(!sc)return "";
 if(sc.ending_label)return String(sc.ending_label);
 return typeof sc.ending==="string"?sc.ending:""}   // 예전 문자열 ending 도 계속 받아준다
function end(){ended=true;setAuto(false);hideChoices();
 const lab=endLabel(DATA.scenes[vi]);
 const dlg=$("dlg");dlg.classList.remove("top");dlg.classList.add("narr");$("who").style.display="none";
 const msg="— 끝 —\\n\\n『"+DATA.title+"』"+(lab?"\\n엔딩 · "+lab:"")+"\\n\\n(탭하면 닫힙니다)";
 $("txt").textContent=msg;say(msg);
 try{localStorage.removeItem(K.pos)}catch(e){}}
function setAuto(on){autoOn=on;const b=$("bAuto");
 b.classList.toggle("on",on);b.setAttribute("aria-pressed",on?"true":"false")}
function start(resume,at){ended=false;$("card").classList.add("hide");
 $("scroll").classList.remove("on");$("stage").classList.add("on");
 setAuto(false);clearTimeout(aTimer);closeLog(true);closeSet(true);hideChoices();
 const pos=resume?loadPos():null;
 if(pos){hist=loadHist();histKeys=new Set(hist.map(h=>h.vi+":"+h.di));
  path=Array.isArray(pos.path)?pos.path.filter(n=>typeof n==="number"):[]}
 else{hist=[];histKeys=new Set();path=[];saveHist()}
 aff=clampAff(pos&&typeof pos.aff==="number"?pos.aff:affStart());
 if(typeof at==="number"){vi=at;di=0;path=[]}
 else{vi=pos&&pos.vi<DATA.scenes.length?pos.vi:0;di=pos&&pos.di<dlen(DATA.scenes[vi])?pos.di:0}
 updateAff(0);renderImg();show()}
function exit(){clearInterval(timer);setAuto(false);
 clearTimeout(aTimer);closeLog(true);closeSet(true);hideChoices();   // 자동 끄고 닫아야 뒤에서 되살아나지 않는다
 $("stage").classList.remove("on");$("card").classList.remove("hide");
 $("bResume").hidden=!loadPos();$("bStart").focus()}

// ---- 오버레이 공통(포커스 되돌리기 · Tab 가두기) ----
const FOCUSABLE="button:not([disabled]),[href],input,select,textarea,[tabindex]:not([tabindex='-1'])";
let lastFocus=null;
function trapTab(box,e){if(e.key!=="Tab")return;
 const f=Array.prototype.slice.call(box.querySelectorAll(FOCUSABLE))
  .filter(n=>n.offsetWidth>0||n.offsetHeight>0);
 if(!f.length)return;
 const first=f[0],last=f[f.length-1],cur=document.activeElement;
 if(e.shiftKey&&(cur===first||!box.contains(cur))){e.preventDefault();last.focus()}
 else if(!e.shiftKey&&(cur===last||!box.contains(cur))){e.preventDefault();first.focus()}}
function restoreFocus(){try{if(lastFocus&&lastFocus.focus)lastFocus.focus()}catch(e){}lastFocus=null}

// ---- 백로그 패널 ----
const logOpen=()=>!$("log").hidden;
function closeLog(quiet){const was=logOpen();$("log").hidden=true;
 $("bLog").setAttribute("aria-expanded","false");
 if(was&&!quiet)restoreFocus();
 if(autoOn&&!revealing&&!ended&&!awaiting&&!setOpen())shown()}
function renderLog(){const box=$("logInner");box.replaceChildren();
 if(!hist.length){box.appendChild(el("div","none","아직 지나온 대사가 없습니다."));return}
 for(const h of hist){const row=el("button","row");
  if(h.n){const b=el("b",null,h.n+"  ");if(h.c)b.style.color=h.c;row.appendChild(b);
   row.appendChild(el("span",null,h.t))}
  else row.appendChild(el("span","nar",h.t));
  row.onclick=()=>jump(h.vi,h.di);
  box.appendChild(row)}
 box.scrollTop=box.scrollHeight}
function toggleLog(){if(logOpen()){closeLog();return}
 closeSet(true);clearTimeout(aTimer);renderLog();   // 선택지 대기 중이면 그 위를 덮기만 한다(선택은 유지)
 lastFocus=document.activeElement;
 $("log").hidden=false;$("bLog").setAttribute("aria-expanded","true");$("bLogClose").focus()}
function jump(v,d){closeLog(true);hideChoices();ended=false;const before=vi;vi=v;di=d;
 if(vi!==before)renderImg();show();$("bLog").focus()}

// ---- 설정 오버레이 ----
const setOpen=()=>!$("set").hidden;
function seg(box,labels,cur,pick){box.replaceChildren();
 labels.forEach((lb,i)=>{const b=el("button","sb",lb);
  if(i===cur){b.classList.add("on");b.setAttribute("aria-pressed","true")}
  else if(cur>=0)b.setAttribute("aria-pressed","false");
  b.onclick=()=>pick(i);box.appendChild(b)})}
function renderSet(){
 seg($("segFs"),FS.map(f=>f[1]),SET.fs,i=>{SET.fs=i;applyFs();saveSet();renderSet()});
 seg($("segSp"),SPEEDS.map(s=>s[1]),SET.sp,i=>{SET.sp=i;saveSet();renderSet()});
 const row=$("rowEp");
 if(EPS.length<2){row.hidden=true;return}
 row.hidden=false;const box=$("segEp");box.replaceChildren();
 for(const e of EPS){const i=epFirst(e.ep);if(i<0)continue;
  const b=el("button","sb",epLabel(e.ep));b.onclick=()=>goEpisode(i);box.appendChild(b)}}
function toggleSet(){if(setOpen()){closeSet();return}
 closeLog(true);clearTimeout(aTimer);renderSet();
 lastFocus=document.activeElement;
 $("set").hidden=false;$("bSet").setAttribute("aria-expanded","true");$("bSetClose").focus()}
function closeSet(quiet){const was=setOpen();$("set").hidden=true;
 $("bSet").setAttribute("aria-expanded","false");
 if(was&&!quiet)restoreFocus();
 if(autoOn&&!revealing&&!ended&&!awaiting&&!logOpen())shown()}
function goEpisode(i){closeSet(true);hideChoices();ended=false;path=[];
 vi=i;di=0;renderImg();show();$("bSet").focus()}

// ---- 세로 스크롤 웹툰 모드 ----
function buildScroll(){const box=$("cuts");if(box.childElementCount)return;
 let curEp=null;
 for(const sc of DATA.scenes){
  if(sc.ep&&sc.ep!==curEp){curEp=sc.ep;box.appendChild(el("div","ep",epLabel(sc.ep)))}
  if(sc.img){const im=el("img");im.src=sc.img;im.alt=sc.purpose||sc.id;im.loading="lazy";box.appendChild(im)}
  for(const l of (sc.lines||[])){const s=el("div","say");
   if(l.n){const b=el("b",null,l.n+"  ");b.style.color=l.c||"var(--amber)";s.appendChild(b);
    s.appendChild(el("span",null,l.t))}
   else s.appendChild(el("span","nar",l.t));
   box.appendChild(s)}
  for(const c of (sc.choices||[])){const s=el("div","say");   // 스크롤 모드는 선택지를 목록으로만
   s.appendChild(el("span","pick","▸ "+(c.text||"")));box.appendChild(s)}}}
function openScroll(){buildScroll();$("card").classList.add("hide");
 $("stage").classList.remove("on");$("scroll").classList.add("on");$("bToVN").focus()}

function buildEps(){const box=$("eps");box.replaceChildren();
 if(EPS.length<2){box.hidden=true;return}
 for(const e of EPS){const i=epFirst(e.ep);if(i<0)continue;
  const b=el("button",null,epLabel(e.ep));b.onclick=()=>start(false,i);box.appendChild(b)}
 box.hidden=false}

$("bStart").onclick=()=>start(false);
$("bResume").onclick=()=>start(true);
$("bScroll").onclick=openScroll;
$("bToScroll").onclick=()=>{clearInterval(timer);clearTimeout(aTimer);closeLog(true);closeSet(true);openScroll()};
$("bToVN").onclick=()=>{$("scroll").classList.remove("on");start(false,vi)};
$("bScExit").onclick=()=>{$("scroll").classList.remove("on");$("card").classList.remove("hide");$("bStart").focus()};
$("bExit").onclick=exit;
$("bLog").onclick=toggleLog;$("bLogClose").onclick=()=>closeLog();
$("bSet").onclick=toggleSet;$("bSetClose").onclick=()=>closeSet();
$("set").onclick=e=>{if(e.target===$("set"))closeSet()};   // 어두운 바깥을 눌러도 닫힌다
$("bAuto").onclick=()=>{setAuto(!autoOn);if(autoOn&&!revealing)shown();else clearTimeout(aTimer)};
$("tap").onclick=()=>adv(1);$("dlg").onclick=()=>adv(1);
let tx=0,ty=0;
$("tap").addEventListener("touchstart",e=>{const t=e.changedTouches[0];tx=t.clientX;ty=t.clientY},{passive:true});
$("tap").addEventListener("touchend",e=>{const t=e.changedTouches[0],dx=t.clientX-tx,dy=t.clientY-ty;
 if(Math.abs(dx)>45&&Math.abs(dx)>Math.abs(dy))adv(dx<0?1:-1)},{passive:true});
addEventListener("keydown",e=>{
 const t=e.target,tag=t&&t.tagName;
 // 폼 컨트롤 위에서는 뷰어 단축키가 입력을 가로채지 않는다
 if(tag==="INPUT"||tag==="TEXTAREA"||tag==="SELECT"||(t&&t.isContentEditable))return;
 if(setOpen()){trapTab($("set"),e);
  if(e.key==="Escape"){e.preventDefault();closeSet()}return}
 if(logOpen()){trapTab($("log"),e);
  if(e.key==="Escape"||e.key==="l"||e.key==="L"){e.preventDefault();closeLog()}return}
 if($("scroll").classList.contains("on")){if(e.key==="Escape")$("bScExit").click();return}
 if(!$("stage").classList.contains("on")){
  if((e.key==="Enter"||e.key===" ")&&tag!=="BUTTON"){e.preventDefault();start(false)}return}
 if((e.key===" "||e.key==="Enter")&&tag==="BUTTON")return;   // 버튼에 포커스가 있으면 버튼이 먼저
 if(e.key==="Escape"){if(awaiting)return;exit();return}
 if(e.key==="l"||e.key==="L"){toggleLog();return}
 if(e.key==="s"||e.key==="S"){toggleSet();return}
 if(awaiting){                                              // 선택지: 위아래로 고른다
  const bs=Array.prototype.slice.call($("choices").querySelectorAll("button"));
  if(!bs.length||(e.key!=="ArrowDown"&&e.key!=="ArrowUp"))return;
  e.preventDefault();const i=bs.indexOf(document.activeElement);
  bs[e.key==="ArrowDown"?(i+1)%bs.length:(i<=0?bs.length-1:i-1)].focus();return}
 if(e.key==="ArrowLeft"){adv(-1);return}
 if(e.key===" "||e.key==="ArrowRight"||e.key==="Enter"){e.preventDefault();adv(1);return}
 if(e.key==="a"||e.key==="A")$("bAuto").click()});
applyFs();
buildEps();
$("meta").textContent=DATA.scenes.length+"개 장면"
 +(EPS.length>1?" · "+EPS.length+"화":"")+" · 오프라인 자족 파일";
$("scTitle").textContent=DATA.title;
$("bResume").hidden=!loadPos();
if(typeof DATA.cover==="number"&&DATA.scenes[DATA.cover]&&DATA.scenes[DATA.cover].img){
 const cv=$("cover");cv.src=DATA.scenes[DATA.cover].img;cv.hidden=false}
</script></body></html>
"""


def build_html(include_all: bool, max_edge: int, quality: int,
               cover_id: str | None = None, font_spec: str | None = None,
               webp: bool = False, use_cache: bool = True):
    """(data, html) 반환 — 단일 파일 export 와 PWA 번들이 공유."""
    data = build_data(include_all, max_edge, quality, cover_id, webp, use_cache)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    fcss = font_css(find_font(font_spec), used_text(data))
    # 제목은 <title>·<h1> 에 그대로 들어가므로 이스케이프한다(따옴표·꺾쇠가 든 제목이 문서를 깨지 않게).
    html = (TEMPLATE.replace("__TITLE__", html_escape(data["title"]))
            .replace("__FONTCSS__", fcss).replace("__DATA__", payload))
    return data, html


def safe_name(title: str) -> str:
    """파일명으로 쓸 제목 — 공백·하이픈·밑줄만 남기고 나머지 기호는 버린다."""
    out = "".join(c for c in str(title) if c.isalnum() or c in " -_").strip()[:120].strip()
    return out or safe_slug(title, "viewer")


def export(include_all: bool, max_edge: int, quality: int,
           cover_id: str | None = None, font_spec: str | None = None,
           webp: bool = False, use_cache: bool = True) -> Path:
    data, html = build_html(include_all, max_edge, quality, cover_id, font_spec, webp, use_cache)
    out = OUT_DIR / f"{safe_name(data['title'])}.html"
    atomic_write_text(out, html)      # 저장 도중 끊겨도 반쯤 잘린 감상본이 남지 않는다
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="타임캡슐 감상본 내보내기 (단일 HTML)")
    ap.add_argument("--all", action="store_true", help="상태 무관 selected_image 전부")
    ap.add_argument("--max-edge", type=int, default=1600, help="(Pillow) 내장 이미지 최대 긴 변 px")
    ap.add_argument("--quality", type=int, default=85, help="(Pillow) JPEG/WebP 품질")
    ap.add_argument("--webp", action="store_true",
                    help="(Pillow 있을 때) 내장 이미지를 WebP 로 — 같은 화질에서 더 작다")
    ap.add_argument("--cover", metavar="SCENE-ID", help="표지 커버 CG 로 쓸 장면(기본: 첫 장면)")
    ap.add_argument("--embed-font", nargs="?", const="auto", metavar="PATH",
                    help="한글 폰트 임베드(기본 꺼짐). 값 없으면 assets/fonts 에서 자동 탐색")
    ap.add_argument("--no-cache", action="store_true",
                    help="이미지 재인코딩 캐시를 쓰지 않고 매번 다시 굽는다")
    args = ap.parse_args()
    if args.webp and not has_pillow():
        print("  · Pillow 가 없어 WebP 대신 원본 이미지를 그대로 내장합니다 (pip install pillow).")
    try:
        out = export(args.all, args.max_edge, args.quality, args.cover, args.embed_font,
                     args.webp, not args.no_cache)
    except RuntimeError as exc:      # VNError 포함
        print(f"오류: {exc}")
        return 1
    if args.embed_font and not find_font(args.embed_font):
        print("  · 폰트 파일을 찾지 못해 시스템 폰트로 폴백했습니다 (assets/fonts/*.woff2|ttf|otf).")
    size = out.stat().st_size
    print(f"감상본 저장: {out.relative_to(ROOT).as_posix()}  ({size / 1_000_000:.2f} MB)")
    if size > 15_000_000:
        print("  ⚠ 15MB 초과 — 폰 전송/아티팩트 게시가 어려울 수 있음. "
              "--max-edge/--quality 를 낮추거나 --webp 를 쓰세요.")
    print("이 파일 하나면 서버 없이 어디서든(폰 포함) 재생됩니다. VN 모드 + 세로 스크롤 모드 포함.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
