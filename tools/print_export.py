#!/usr/bin/env python3
"""인화 마스터 익스포트 — 승인 이미지를 실물 인화용 마스터 파일로 굽는다.

선택 이미지를 목표 규격(예 5x7)·DPI(기본 300)에 맞춰 채움(cover)으로 크롭하고 LANCZOS 로
리샘플해, DPI 메타·sRGB 로 TIFF(무손실)+고품질 JPEG 마스터와 스펙시트를 output/print/ 에 낸다.
컨택트시트(색인 프린트)도 만든다.

의존성: Pillow. (감상/검사 파이프라인은 여전히 Pillow 불필요 — 이 익스포트 도구만 사용)

사용법:
  python tools/print_export.py --size 5x7                 # 승인 장면 전체
  python tools/print_export.py --size 4x6 --scene SCENE-001
  python tools/print_export.py --size A5 --bleed 0.125     # 재단 여백 0.125인치
  python tools/print_export.py --size 8x10 --anchor top    # 크롭 기준(center/top/bottom/left/right)
  python tools/print_export.py --all --size 5x7            # 상태 무관 selected 전부
  python tools/print_export.py --contact                   # 컨택트시트만
  python tools/print_export.py --size 5x7 --skip-upscale   # 업스케일 필요분은 건너뜀

읽기: project/manifest.json, project/scenes/*.json, images/.  쓰기: output/print/ 만.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:  # 서버(webapp)가 Pillow 없이도 import 가능하도록 예외를 던지지 않는다
    Image = ImageDraw = ImageFont = None
    PIL_OK = False


def _require_pil():
    if not PIL_OK:
        raise RuntimeError("인화 내보내기는 Pillow 가 필요합니다:  python -m pip install Pillow")

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project" / "manifest.json"
SCENES = ROOT / "project" / "scenes"
OUT = ROOT / "output" / "print"

SIZES = {  # 이름: (짧은 변 in, 긴 변 in)
    "4x6": (4.0, 6.0), "5x7": (5.0, 7.0), "8x10": (8.0, 10.0),
    "a5": (5.83, 8.27), "a4": (8.27, 11.69),
}
KOR_FONTS = [r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunsl.ttf",
             "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]


def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_size(s: str):
    key = s.lower().replace("×", "x")
    if key in SIZES:
        return SIZES[key]
    if "x" in key:  # 커스텀 WxH 인치
        try:
            a, b = (float(x) for x in key.split("x"))
        except ValueError:
            a = b = None
        if a is not None and a > 0 and b > 0 and max(a, b) <= 100:
            return (min(a, b), max(a, b))
    raise SystemExit(f"오류: 규격 '{s}' 을 해석할 수 없습니다. "
                     "(4x6/5x7/8x10/A5/A4 또는 '가로x세로'인치, 0<크기≤100)")


def _anchor_box(rw, rh, tw, th, anchor):
    """리사이즈된 (rw,rh) 에서 (tw,th) 를 anchor 기준으로 잘라낼 박스."""
    left = (rw - tw) // 2
    top = (rh - th) // 2
    if anchor == "top":
        top = 0
    elif anchor == "bottom":
        top = rh - th
    elif anchor == "left":
        left = 0
    elif anchor == "right":
        left = rw - tw
    left = max(0, min(left, rw - tw))
    top = max(0, min(top, rh - th))
    return (left, top, left + tw, top + th)


def to_srgb(img: Image.Image) -> Image.Image:
    """ICC 프로파일이 있으면 sRGB 로 변환, 없으면 RGB 로."""
    try:
        from PIL import ImageCms
        icc = img.info.get("icc_profile")
        if icc:
            import io
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            return ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
    except Exception:
        pass
    return img.convert("RGB")


def export_one(scene_id: str, src_path: Path, short_in, long_in, dpi, bleed, anchor):
    """이미지 1장 → 마스터 픽셀·크롭·리샘플 후 저장. 스펙 dict 반환."""
    _require_pil()
    with Image.open(src_path) as im:
        im.load()
        img = to_srgb(im)
    sw, sh = img.size
    landscape = sw >= sh
    pw_in = (long_in if landscape else short_in) + 2 * bleed
    ph_in = (short_in if landscape else long_in) + 2 * bleed
    tw, th = round(pw_in * dpi), round(ph_in * dpi)

    scale = max(tw / sw, th / sh)          # 채움(cover)
    upscaled = scale > 1.0001
    rw, rh = max(tw, round(sw * scale)), max(th, round(sh * scale))
    resized = img.resize((rw, rh), Image.LANCZOS)
    box = _anchor_box(rw, rh, tw, th, anchor)
    master = resized.crop(box)
    crop_pct = round((1 - (tw * th) / (rw * rh)) * 100, 1)

    dest = OUT / f"{short_in:g}x{long_in:g}"
    dest.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in str(scene_id) if c.isalnum() or c in "-_") or "SCENE"  # 경로 탈출 차단
    tiff = dest / f"{safe}.tiff"
    jpg = dest / f"{safe}.jpg"
    master.save(tiff, format="TIFF", dpi=(dpi, dpi), compression="tiff_lzw")
    master.save(jpg, format="JPEG", dpi=(dpi, dpi), quality=95, subsampling=0)
    return {"scene_id": scene_id, "src_px": [sw, sh], "out_px": [tw, th],
            "size_in": [pw_in, ph_in], "dpi": dpi, "bleed_in": bleed, "anchor": anchor,
            "crop_pct": crop_pct, "upscaled": upscaled,
            "eff_dpi_src": round(min(sw / pw_in, sh / ph_in), 0),  # fill_dpi 와 동일 정의
            "tiff": tiff.relative_to(ROOT).as_posix(), "jpg": jpg.relative_to(ROOT).as_posix()}


def collect(scene_filter, include_all):
    if not MANIFEST.exists():
        raise SystemExit("오류: project/manifest.json 이 없습니다.")
    out = []
    for f in sorted(SCENES.glob("SCENE-*.json")) if SCENES.exists() else []:
        sc = load(f)
        if not isinstance(sc, dict):
            continue
        if scene_filter and sc.get("scene_id") != scene_filter:
            continue
        sel = (sc.get("assets", {}).get("selected_image") or "").strip()
        if not sel:
            continue
        if not include_all and sc.get("status") != "APPROVED" and not scene_filter:
            continue
        out.append(sc)
    return out


def _load_font(size):
    for p in KOR_FONTS:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def contact_sheet(scenes, cols=3):
    """승인 장면 썸네일 색인 프린트 → output/print/contact_sheet.png"""
    _require_pil()
    if not scenes:
        print("컨택트시트: 대상 장면이 없습니다.")
        return None
    W = 2480  # A4 가로 @ ~300DPI 근사(세로형 시트)
    pad, gap, label_h = 40, 24, 70
    cell_w = (W - 2 * pad - (cols - 1) * gap) // cols
    cell_h = round(cell_w * 3 / 2)                     # 2:3 셀
    rows = (len(scenes) + cols - 1) // cols
    H = pad * 2 + 90 + rows * (cell_h + label_h + gap)
    sheet = Image.new("RGB", (W, H), (245, 240, 228))
    draw = ImageDraw.Draw(sheet)
    title_font = _load_font(48)
    label_font = _load_font(26)
    title = load(MANIFEST).get("title", "") or "무제"
    draw.text((pad, pad), f"{title} — 컨택트시트 ({len(scenes)}컷)", fill=(40, 30, 20), font=title_font)

    for i, sc in enumerate(scenes):
        r, c = divmod(i, cols)
        x = pad + c * (cell_w + gap)
        y = pad + 90 + r * (cell_h + label_h + gap)
        draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(225, 216, 198), outline=(180, 165, 140))
        sel = (sc.get("assets", {}).get("selected_image") or "").strip()
        p = ROOT / sel
        if sel and p.exists():
            try:
                with Image.open(p) as im:
                    im.load()
                    thumb = to_srgb(im).copy()
                thumb.thumbnail((cell_w, cell_h), Image.LANCZOS)
                sheet.paste(thumb, (x + (cell_w - thumb.width) // 2, y + (cell_h - thumb.height) // 2))
            except Exception:
                pass
        label = f"{sc.get('scene_id', '?')} · {(sc.get('purpose') or '')[:22]}"
        draw.text((x, y + cell_h + 8), label, fill=(50, 38, 26), font=label_font)

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "contact_sheet.png"
    sheet.save(out, dpi=(300, 300))
    print(f"컨택트시트 저장: {out.relative_to(ROOT).as_posix()}  ({W}×{H}px)")
    return out


def export_batch(short_in, long_in, dpi, bleed, anchor, include_all=False,
                 scene_filter=None, skip_upscale=False, emit=lambda *a: None) -> dict:
    """장면 수집 → 규격별 마스터 굽기 → spec_sheet 저장. 웹·CLI 공용. 요약 dict 반환."""
    scenes = collect(scene_filter, include_all)
    specs, skipped, missing = [], 0, 0
    for sc in scenes:
        sid = sc.get("scene_id", "?")
        sel = (sc.get("assets", {}).get("selected_image") or "").strip()
        p = ROOT / sel
        if not p.exists():
            emit(f"[{sid}] 원본 없음: {sel}")
            missing += 1
            continue
        pol = sc.get("print", {}) if isinstance(sc.get("print"), dict) else {}
        anc = pol.get("crop_anchor", anchor)
        try:
            spec = export_one(sid, p, short_in, long_in, dpi, bleed, anc)
        except Exception as exc:
            emit(f"[{sid}] 실패: {exc}")
            continue
        if spec["upscaled"] and skip_upscale:
            skipped += 1
            for f in (spec["tiff"], spec["jpg"]):
                try:
                    (ROOT / f).unlink()
                except OSError:
                    pass
            emit(f"[{sid}] 업스케일 필요 → 건너뜀(--skip-upscale)")
            continue
        specs.append(spec)
        warn = "  ⚠업스케일(원본<목표)" if spec["upscaled"] else ""
        emit(f"[{sid}] {spec['src_px'][0]}×{spec['src_px'][1]} → "
             f"{spec['out_px'][0]}×{spec['out_px'][1]}px @{dpi}DPI · 크롭 {spec['crop_pct']}%{warn}")

    dest = OUT / f"{short_in:g}x{long_in:g}"
    if specs:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "spec_sheet.json").write_text(
            json.dumps({"size_in": [short_in, long_in], "dpi": dpi, "bleed_in": bleed,
                        "count": len(specs), "scenes": specs}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return {"count": len(specs), "dir": dest.relative_to(ROOT).as_posix() if specs else None,
            "upscaled": sum(1 for s in specs if s["upscaled"]), "skipped": skipped,
            "missing": missing, "specs": specs}


def main() -> int:
    ap = argparse.ArgumentParser(description="인화 마스터 익스포트 (Pillow)")
    ap.add_argument("--size", help="4x6/5x7/8x10/A5/A4 또는 '가로x세로'인치")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--bleed", type=float, default=0.0, help="재단 여백(인치, 각 변)")
    ap.add_argument("--anchor", default="center", choices=["center", "top", "bottom", "left", "right"])
    ap.add_argument("--scene", help="특정 장면만")
    ap.add_argument("--all", action="store_true", help="상태 무관 selected 전부")
    ap.add_argument("--contact", action="store_true", help="컨택트시트 생성")
    ap.add_argument("--skip-upscale", action="store_true", help="업스케일 필요분은 굽지 않음")
    args = ap.parse_args()
    if not PIL_OK:
        print("오류: Pillow 가 필요합니다.  python -m pip install Pillow")
        return 1

    scenes = collect(args.scene, args.all)
    if args.contact:
        contact_sheet(scenes)
        if not args.size:
            return 0
    if not args.size:
        print("규격을 지정하세요: --size 5x7  (또는 색인만: --contact)")
        return 2

    short_in, long_in = parse_size(args.size)
    s = export_batch(short_in, long_in, args.dpi, args.bleed, args.anchor,
                     args.all, args.scene, args.skip_upscale, emit=print)
    print("-" * 56)
    if s["count"]:
        print(f"완료: {s['count']}장 → {s['dir']}/ (TIFF+JPEG), spec_sheet.json")
        if s["upscaled"]:
            print(f"  ⚠ {s['upscaled']}장은 업스케일됨 — 인화 화질 저하 가능. 외부 AI에서 더 큰 해상도로 재생성 권장.")
        if s["skipped"]:
            print(f"  {s['skipped']}장은 --skip-upscale 로 제외됨.")
    else:
        print("구운 마스터가 없습니다. (selected_image 있고 APPROVED 인 장면 대상 — --all 로 전체)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
