#!/usr/bin/env python3
"""인화 마스터 익스포트 — 승인 이미지를 실물 인화용 마스터 파일로 굽는다.

선택 이미지를 목표 규격(예 5x7·포토카드 55x85mm)·DPI(기본 300)에 맞춰 채움(cover) 크롭 또는
여백(fit)으로 앉히고 리샘플해, DPI 메타·sRGB ICC 를 넣은 TIFF(무손실)+고품질 JPEG 마스터와
스펙시트를 output/print/ 에 낸다. 컨택트시트(색인 프린트)도 만든다.

의존성: Pillow. (감상/검사 파이프라인은 여전히 Pillow 불필요 — 이 익스포트 도구만 사용)

사용법:
  python tools/print_export.py --size 5x7                 # 승인 장면 전체
  python tools/print_export.py --size 4x6 --scene SCENE-001
  python tools/print_export.py --size 55x85mm             # mm 규격(포토카드) — --size photocard 도 동일
  python tools/print_export.py --size A5 --bleed 0.125     # 재단 여백 0.125인치
  python tools/print_export.py --size 5x7 --bleed 0.125 --marks   # 재단선(크롭 마크) 인쇄
  python tools/print_export.py --size 8x10 --anchor top    # 크롭 기준(center/top/bottom/left/right)
  python tools/print_export.py --size 5x7 --mode fit --bg "#f5f0e4"   # 크롭 없이 여백 채움
  python tools/print_export.py --size 5x7 --upscale step   # 다단계 확대+샤픈(원본이 작을 때)
  python tools/print_export.py --size 5x7 --upscale auto   # 외부 업스케일러 있으면 사용, 없으면 step
  python tools/print_export.py --size 5x7 --only SCENE-001,SCENE-004   # 즐겨찾기 등 일부만
  python tools/print_export.py --all --size 5x7            # 상태 무관 selected 전부
  python tools/print_export.py --contact                   # 컨택트시트만
  python tools/print_export.py --size 5x7 --skip-upscale   # 업스케일 필요분은 건너뜀
  python tools/print_export.py --list-sizes                # 규격 프리셋 목록

읽기: project/manifest.json, project/scenes/*.json, images/.
쓰기: output/print/ (외부 업스케일러 사용 시 임시 폴더를 잠깐 쓴다).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:          # 저장소가 복제된 곳에서 이 파일만 적재돼도 '옆에 있는' vn_core 를 쓴다
    sys.path.insert(0, str(_HERE))

import vn_core                                                    # noqa: E402
from vn_core import (VNError, atomic_write_json, load_json_safe,   # noqa: E402
                     safe_slug)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:  # 서버(webapp)가 Pillow 없이도 import 가능하도록 예외를 던지지 않는다
    Image = ImageDraw = ImageFont = None
    PIL_OK = False


class PrintArgError(VNError, SystemExit):
    """규격·전제조건 오류.

    VNError(=RuntimeError) 이므로 웹 스튜디오의 ``except RuntimeError`` 가 잡아 400 으로 바꾼다.
    예전에 이 자리에서 던지던 SystemExit 는 요청 스레드를 통째로 끊어 연결이 잘렸다.
    다만 기존 호출부·회귀 테스트가 ``except SystemExit`` 로 이 오류를 기다리므로 두 타입을 모두
    상속해 하위호환을 유지한다 — ``except Exception`` 으로도 잡히므로 프로세스를 죽이지 않는다.
    """


def _require_pil():
    if not PIL_OK:
        raise VNError("인화 내보내기는 Pillow 가 필요합니다:  python -m pip install Pillow")


# 경로 이름은 vn_core 규약을 따르되 값은 이 파일 위치에서 계산한다.
# (자가진단이 저장소를 복제해 이 모듈만 적재하므로 — 그때도 자기 트리 안에만 쓴다.)
ROOT = _HERE.parent
MANIFEST = ROOT / "project" / "manifest.json"
OUT = ROOT / "output" / "print"          # 함수는 이 전역을 호출 시점에 읽는다(테스트가 갈아끼운다)
# 장면 폴더 상수는 두지 않는다 — 훑기는 vn_core.iter_scenes 하나뿐이다.

MM_PER_IN = 25.4

SIZES = {  # 이름: (짧은 변 in, 긴 변 in) — 키는 폴더명으로도 쓰이므로 ASCII 만
    "4x6": (4.0, 6.0), "5x7": (5.0, 7.0), "8x10": (8.0, 10.0),
    "a5": (5.83, 8.27), "a4": (8.27, 11.69),
    # 한국 인화소 상용 규격 추가
    "3x5": (3.5, 5.0),                                    # 89×127mm
    "11x14": (11.0, 14.0),                                # 203×254mm 위 크기
    "a6": (4.13, 5.83),                                   # 105×148mm
    "photocard": (55.0 / MM_PER_IN, 85.0 / MM_PER_IN),    # 포토카드 55×85mm
    "namecard": (50.0 / MM_PER_IN, 90.0 / MM_PER_IN),     # 명함 50×90mm
}
SIZE_ALIASES = {  # 한글·별칭 → SIZES 키
    "포토카드": "photocard", "photo_card": "photocard", "photocard55x85": "photocard",
    "명함": "namecard", "엽서": "4x6", "postcard": "4x6",
    "카드": "photocard", "3.5x5": "3x5",
}

KOR_FONTS = [r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunsl.ttf",
             "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]

# 외부 업스케일러 훅 — 있으면 쓰고 없으면 자동 폴백(설치를 강제하지 않는다)
UPSCALE_EXES = ("realesrgan-ncnn-vulkan", "realsr-ncnn-vulkan", "waifu2x-ncnn-vulkan")


def parse_size(s: str):
    """규격 문자열 → (짧은 변, 긴 변) 인치. 프리셋 / 'WxH' 인치 / 'WxHmm'·'WxHcm' 지원."""
    key = str(s).lower().replace("×", "x").replace(" ", "").strip()
    key = SIZE_ALIASES.get(key, key)
    if key in SIZES:
        return SIZES[key]
    div = 1.0
    for suf, per_in in (("mm", MM_PER_IN), ("cm", 2.54), ("inch", 1.0), ("in", 1.0), ('"', 1.0)):
        if key.endswith(suf):
            key, div = key[:-len(suf)], per_in
            break
    if "x" in key:  # 커스텀 WxH
        try:
            a, b = (float(x) / div for x in key.split("x"))
        except ValueError:
            a = b = None
        if a is not None and a > 0 and b > 0 and max(a, b) <= 100:
            return (min(a, b), max(a, b))
    raise PrintArgError(f"오류: 규격 '{s}' 을 해석할 수 없습니다. "
                        f"({'/'.join(list(SIZES)[:6])} 등 프리셋, '가로x세로'인치, "
                        "'55x85mm' 형식 지원 · 0<크기≤100인치)")


def size_dir(short_in: float, long_in: float) -> str:
    """출력 폴더명 — 기존 숫자 라벨(5x7, 5.83x8.27)을 유지하고, mm 유래 소수만 프리셋 이름으로."""
    lab = f"{short_in:g}x{long_in:g}"
    if len(lab) <= 11:
        return lab
    for name, (s, l) in SIZES.items():
        if abs(s - short_in) < 0.01 and abs(l - long_in) < 0.01:
            return name
    return f"{short_in:.2f}x{long_in:.2f}"


def size_label(short_in: float, long_in: float) -> str:
    """사람이 읽는 규격 표기 — 인치와 mm 를 함께 보여준다."""
    return (f"{size_dir(short_in, long_in)} "
            f"({round(short_in * MM_PER_IN)}×{round(long_in * MM_PER_IN)}mm)")


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


_SRGB_ICC = None


def srgb_icc_bytes():
    """마스터에 임베드할 sRGB ICC 바이트(1회 생성 후 재사용). littleCMS 없으면 None."""
    global _SRGB_ICC
    if _SRGB_ICC is None:
        try:
            from PIL import ImageCms
            _SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        except Exception:
            _SRGB_ICC = b""   # 재시도 비용을 아끼려고 실패도 캐시
    return _SRGB_ICC or None


def _bg_rgb(spec):
    """여백 색 해석 — '#f5f0e4' / 'white' / '245,240,228'. 실패하면 흰색."""
    if isinstance(spec, (tuple, list)) and len(spec) >= 3:
        try:
            return tuple(max(0, min(255, int(v))) for v in list(spec)[:3])
        except (TypeError, ValueError):
            return (255, 255, 255)
    s = str(spec or "").strip()
    if not s:
        return (255, 255, 255)
    try:
        from PIL import ImageColor
        return tuple(ImageColor.getrgb(s))[:3]
    except Exception:
        pass
    try:
        parts = [int(v) for v in s.split(",")]
        if len(parts) == 3:
            return tuple(max(0, min(255, v)) for v in parts)
    except ValueError:
        pass
    return (255, 255, 255)


def _flatten(im, bg):
    """알파가 있으면 여백 색으로 먼저 합성 — 검정 합성으로 어두워지는 것을 막는다."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        base = Image.new("RGBA", im.size, tuple(bg) + (255,))
        base.alpha_composite(im.convert("RGBA"))
        icc = im.info.get("icc_profile")
        if icc:
            base.info["icc_profile"] = icc
        return base
    return im


# ------------------------------------------------------------- 업스케일 (81)
def find_upscaler() -> str | None:
    """외부 업스케일러 실행파일 경로. 환경변수 UPSCALER_EXE 우선, 없으면 PATH 검색."""
    env = (os.environ.get("UPSCALER_EXE", "") or "").strip().strip('"')
    if env and Path(env).exists():
        return env
    for name in UPSCALE_EXES:
        p = shutil.which(name)
        if p:
            return p
    return None


def external_upscale(img, factor: float, exe: str | None = None, timeout: int = 600):
    """Real-ESRGAN 계열 실행파일로 2/4배 선확대. 없거나 실패하면 None → 호출부가 폴백한다."""
    exe = exe or find_upscaler()
    if not exe or factor <= 1.0:
        return None
    s = 4 if factor > 2.0 else 2
    try:
        with tempfile.TemporaryDirectory(prefix="vn_upscale_") as td:
            src = Path(td) / "in.png"
            dst = Path(td) / "out.png"
            img.save(src, format="PNG")
            r = subprocess.run([exe, "-i", str(src), "-o", str(dst), "-s", str(s)],
                               capture_output=True, timeout=timeout)
            if r.returncode != 0 or not dst.exists():
                return None
            with Image.open(dst) as up:
                up.load()
                return up.convert("RGB")
    except Exception:
        return None


def _resample(img, rw, rh, method="lanczos", sharpen=False):
    """리샘플. 'step' 은 1.5배씩 나눠 확대해 한 번에 늘릴 때보다 윤곽 뭉개짐을 줄이고 가볍게 샤픈."""
    sw, sh = img.size
    if (rw, rh) == (sw, sh):
        out = img
    elif method == "step" and rw > sw and rh > sh:
        cur, cw, ch = img, sw, sh
        while cw * 1.5 <= rw and ch * 1.5 <= rh:
            cw, ch = round(cw * 1.5), round(ch * 1.5)
            cur = cur.resize((cw, ch), Image.LANCZOS)
        out = cur.resize((rw, rh), Image.LANCZOS) if (cw, ch) != (rw, rh) else cur
    else:
        out = img.resize((rw, rh), Image.LANCZOS)
    if sharpen and out is not img:
        try:
            from PIL import ImageFilter
            out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=55, threshold=3))
        except Exception:
            pass
    return out


# ------------------------------------------------------------- 재단선 (77)
def _draw_crop_marks(img, bleed_px: int, dpi: int) -> bool:
    """블리드 영역 안쪽에만 코너 재단선을 긋는다 — 재단하면 마크도 함께 잘려 나간다."""
    if bleed_px < 4:
        return False
    w, h = img.size
    ln = max(8, min(bleed_px - 2, round(dpi * 0.12)))   # 마크 길이
    lw = max(1, round(dpi / 300))                       # 선 두께
    d = ImageDraw.Draw(img)
    xs, ys = (bleed_px, w - bleed_px), (bleed_px, h - bleed_px)
    for x in xs:
        for y in ys:
            hx = (x - ln, x) if x == xs[0] else (x, x + ln)
            vy = (y - ln, y) if y == ys[0] else (y, y + ln)
            # 어두운 배경에서도 보이도록 흰 밑선 위에 검은 선을 겹친다
            for color, width in (((255, 255, 255), lw * 3), ((0, 0, 0), lw)):
                d.line([hx[0], y, hx[1], y], fill=color, width=width)
                d.line([x, vy[0], x, vy[1]], fill=color, width=width)
    return True


def _safe_stem(scene_id) -> str:
    """파일명에 쓸 수 있는 문자만 남긴다 — 경로 탈출 차단(vn_core 단일 구현)."""
    return safe_slug(scene_id, "SCENE")


def _order_prefix(order) -> str:
    """업로드 정렬용 3자리 접두사(78). 정수가 아니면 접두사 없이 기존 파일명 유지."""
    try:
        n = int(order)
    except (TypeError, ValueError):
        return ""
    return f"{n:03d}_" if 0 < n < 1000 else ""


def export_one(scene_id: str, src_path: Path, short_in, long_in, dpi, bleed, anchor,
               mode="cover", bg="#ffffff", marks=False, order=None, upscale="lanczos"):
    """이미지 1장 → 마스터 픽셀·크롭(또는 여백)·리샘플 후 저장. 스펙 dict 반환."""
    _require_pil()
    bgc = _bg_rgb(bg)
    with Image.open(src_path) as im:
        im.load()
        img = to_srgb(_flatten(im, bgc))
    sw, sh = img.size
    landscape = sw >= sh
    pw_in = (long_in if landscape else short_in) + 2 * bleed
    ph_in = (short_in if landscape else long_in) + 2 * bleed
    tw, th = round(pw_in * dpi), round(ph_in * dpi)

    fit = str(mode).lower() == "fit"
    pick = min if fit else max
    scale = pick(tw / sw, th / sh)
    upscaled = scale > 1.0001              # '원본이 목표보다 작았다' — 확대 방식과 무관한 사실
    umode = str(upscale or "lanczos").lower()
    used = "none"
    if upscaled:
        used = "lanczos"
        if umode in ("auto", "external", "esrgan"):
            pre = external_upscale(img, scale)
            if pre is not None:            # 외부 확대 성공 → 남은 배율만 LANCZOS 로 맞춘다
                img = pre
                sw, sh = img.size
                scale = pick(tw / sw, th / sh)
                used = "esrgan"
        if used == "lanczos" and umode in ("step", "auto", "external", "esrgan"):
            used = "step"

    resample = "step" if used == "step" else "lanczos"
    sharpen = used == "step"
    if fit:
        rw, rh = max(1, round(sw * scale)), max(1, round(sh * scale))
        rw, rh = min(rw, tw), min(rh, th)
        inner = _resample(img, rw, rh, resample, sharpen)
        master = Image.new("RGB", (tw, th), bgc)
        master.paste(inner, ((tw - rw) // 2, (th - rh) // 2))
        crop_pct, pad_pct = 0.0, round((1 - (rw * rh) / (tw * th)) * 100, 1)
    else:
        rw, rh = max(tw, round(sw * scale)), max(th, round(sh * scale))
        resized = _resample(img, rw, rh, resample, sharpen)
        box = _anchor_box(rw, rh, tw, th, anchor)
        master = resized.crop(box)
        crop_pct, pad_pct = round((1 - (tw * th) / (rw * rh)) * 100, 1), 0.0

    marked = _draw_crop_marks(master, round(bleed * dpi), dpi) if marks else False

    dest = OUT / size_dir(short_in, long_in)
    dest.mkdir(parents=True, exist_ok=True)
    stem = f"{_order_prefix(order)}{_safe_stem(scene_id)}"
    tiff = dest / f"{stem}.tiff"
    jpg = dest / f"{stem}.jpg"
    icc = srgb_icc_bytes()
    kw = {"dpi": (dpi, dpi)}
    if icc:  # 인화소가 색을 sRGB 로 해석하도록 프로파일을 함께 넣는다
        kw["icc_profile"] = icc
    master.save(tiff, format="TIFF", compression="tiff_lzw", **kw)
    master.save(jpg, format="JPEG", quality=95, subsampling=0, **kw)
    return {"scene_id": scene_id, "src_px": [sw, sh], "out_px": [tw, th],
            "size_in": [pw_in, ph_in], "dpi": dpi, "bleed_in": bleed, "anchor": anchor,
            "crop_pct": crop_pct, "upscaled": upscaled,
            "eff_dpi_src": round(min(sw / pw_in, sh / ph_in), 0),  # fill_dpi 와 동일 정의
            "mode": "fit" if fit else "cover", "pad_pct": pad_pct,
            "bg": "#%02x%02x%02x" % bgc if fit else None,
            "marks": marked, "icc": bool(icc), "upscale": used, "order": _order_prefix(order)[:-1] or None,
            "tiff": tiff.relative_to(ROOT).as_posix(), "jpg": jpg.relative_to(ROOT).as_posix()}


def collect(scene_filter, include_all):
    """인화 대상 장면 — 훑기와 '실릴 컷' 판정은 vn_core 단일 출처를 쓴다.

    손상된 장면 한 개가 인화 배치를 통째로 막지 않는다(iter_scenes 가 건너뛴다).
    --scene 으로 한 장을 지목한 경우는 사용자가 그 컷을 명시적으로 고른 것이므로
    승인 여부를 묻지 않는다 — 감상본·프리플라이트와 같은 규약이다.
    """
    if not MANIFEST.exists():
        raise PrintArgError("오류: project/manifest.json 이 없습니다.")
    out = []
    for _f, sc in vn_core.iter_scenes():
        if scene_filter and sc.get("scene_id") != scene_filter:
            continue
        if not vn_core.is_deliverable(sc, include_all or bool(scene_filter)):
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
    title = load_json_safe(MANIFEST, {}).get("title", "") or "무제"
    draw.text((pad, pad), f"{title} — 컨택트시트 ({len(scenes)}컷)", fill=(40, 30, 20), font=title_font)

    for i, sc in enumerate(scenes):
        r, c = divmod(i, cols)
        x = pad + c * (cell_w + gap)
        y = pad + 90 + r * (cell_h + label_h + gap)
        draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(225, 216, 198), outline=(180, 165, 140))
        sel = vn_core.selected_of(sc)
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
    icc = srgb_icc_bytes()
    sheet.save(out, dpi=(300, 300), **({"icc_profile": icc} if icc else {}))
    print(f"컨택트시트 저장: {out.relative_to(ROOT).as_posix()}  ({W}×{H}px)")
    return out


def export_batch(short_in, long_in, dpi, bleed, anchor, include_all=False,
                 scene_filter=None, skip_upscale=False, emit=lambda *a: None,
                 *, only_ids=None, mode="cover", bg="#ffffff", marks=False,
                 upscale="lanczos", order_prefix=True) -> dict:
    """장면 수집 → 규격별 마스터 굽기 → spec_sheet 저장. 웹·CLI 공용. 요약 dict 반환.

    only_ids 를 주면 그 scene_id 만 굽는다(즐겨찾기 인화용). None 이면 기존 동작 그대로.
    """
    scenes = collect(scene_filter, include_all)
    wanted = {str(s) for s in only_ids} if only_ids is not None else None
    if wanted is not None:
        scenes = [sc for sc in scenes if sc.get("scene_id") in wanted]
    specs, skipped, missing = [], 0, 0
    if marks and bleed <= 0:
        emit("재단선은 블리드가 있어야 그릴 수 있습니다 — --bleed 0.125 를 함께 주세요.")
    for sc in scenes:
        sid = sc.get("scene_id", "?")
        sel = vn_core.selected_of(sc)
        p = ROOT / sel
        if not p.exists():
            emit(f"[{sid}] 원본 없음: {sel}")
            missing += 1
            continue
        pol = sc.get("print", {}) if isinstance(sc.get("print"), dict) else {}
        anc = pol.get("crop_anchor", anchor)
        md = pol.get("crop_mode", mode)
        bgc = pol.get("pad_color", bg)
        order = sc.get("scene_order") if order_prefix else None
        try:
            spec = export_one(sid, p, short_in, long_in, dpi, bleed, anc,
                              md, bgc, marks, order, upscale)
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
        if spec["mode"] == "fit":
            geo = f"여백 {spec['pad_pct']}%"
        else:
            geo = f"크롭 {spec['crop_pct']}%"
        warn = "  ⚠업스케일(원본<목표)" if spec["upscaled"] else ""
        if spec["upscaled"] and spec["upscale"] in ("step", "esrgan"):
            warn += f"[{spec['upscale']}]"
        emit(f"[{sid}] {spec['src_px'][0]}×{spec['src_px'][1]} → "
             f"{spec['out_px'][0]}×{spec['out_px'][1]}px @{dpi}DPI · {geo}{warn}")

    dest = OUT / size_dir(short_in, long_in)
    # 접두사 규칙이 바뀌기 전에 구운 같은 장면의 옛 파일은 지우지 않고 알리기만 한다
    stale = sum(1 for s in specs if s["order"]
                for ext in ("tiff", "jpg") if (dest / f"{_safe_stem(s['scene_id'])}.{ext}").exists())
    if stale:
        emit(f"참고: 접두사 없는 옛 마스터 {stale}개가 같은 폴더에 남아 있습니다 — "
             "업로드 전에 정리하세요.")
    if specs:
        dest.mkdir(parents=True, exist_ok=True)
        # 인화소에 함께 넘기는 주문서 — 굽는 도중 중단돼도 반쪽 파일이 남지 않게 원자적으로 쓴다
        atomic_write_json(dest / "spec_sheet.json", {
            "size_in": [short_in, long_in], "dpi": dpi, "bleed_in": bleed,
            "mode": "fit" if str(mode).lower() == "fit" else "cover",
            "marks": bool(marks and bleed > 0), "upscale": str(upscale),
            "icc": "sRGB" if srgb_icc_bytes() else None,
            "only_ids": sorted(wanted) if wanted is not None else None,
            "count": len(specs), "scenes": specs})
    return {"count": len(specs), "dir": dest.relative_to(ROOT).as_posix() if specs else None,
            "upscaled": sum(1 for s in specs if s["upscaled"]), "skipped": skipped,
            "missing": missing, "specs": specs, "stale": stale,
            "mode": "fit" if str(mode).lower() == "fit" else "cover",
            "marks": bool(marks and bleed > 0), "icc": bool(srgb_icc_bytes())}


def _print_sizes() -> None:
    print("규격 프리셋 (--size 값):")
    for name, (s, l) in SIZES.items():
        print(f"  {name:<10} {s:g}×{l:g}in  ({round(s * MM_PER_IN)}×{round(l * MM_PER_IN)}mm)")
    print("  별칭: " + ", ".join(f"{k}→{v}" for k, v in SIZE_ALIASES.items()))
    print("  자유 규격: '4x6'(인치) · '55x85mm' · '10x15cm'")


def main() -> int:
    ap = argparse.ArgumentParser(description="인화 마스터 익스포트 (Pillow)")
    ap.add_argument("--size", help="4x6/5x7/8x10/A5/A4/photocard 등 프리셋, '가로x세로'인치, '55x85mm'")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--bleed", type=float, default=0.0, help="재단 여백(인치, 각 변)")
    ap.add_argument("--anchor", default="center", choices=["center", "top", "bottom", "left", "right"])
    ap.add_argument("--mode", default="cover", choices=["cover", "fit"],
                    help="cover=채움 크롭(기본) · fit=전체 넣고 여백")
    ap.add_argument("--bg", default="#ffffff", help="fit 여백 색 (#f5f0e4 / white / 245,240,228)")
    ap.add_argument("--marks", action="store_true", help="블리드 영역에 재단선(크롭 마크) 인쇄")
    ap.add_argument("--upscale", default="lanczos", choices=["lanczos", "step", "auto"],
                    help="확대 방식: lanczos(기본) · step(다단계+샤픈) · auto(외부 업스케일러 있으면 사용)")
    ap.add_argument("--scene", help="특정 장면만")
    ap.add_argument("--only", help="쉼표로 구분한 scene_id 목록만 (예: SCENE-001,SCENE-004)")
    ap.add_argument("--all", action="store_true", help="상태 무관 selected 전부")
    ap.add_argument("--contact", action="store_true", help="컨택트시트 생성")
    ap.add_argument("--skip-upscale", action="store_true", help="업스케일 필요분은 굽지 않음")
    ap.add_argument("--no-order-prefix", action="store_true",
                    help="파일명 앞 scene_order 접두사(001_)를 붙이지 않음")
    ap.add_argument("--list-sizes", action="store_true", help="규격 프리셋 목록만 출력")
    args = ap.parse_args()
    if args.list_sizes:
        _print_sizes()
        return 0
    if not PIL_OK:
        print("오류: Pillow 가 필요합니다.  python -m pip install Pillow")
        return 1

    try:
        scenes = collect(args.scene, args.all)
        if args.contact:
            contact_sheet(scenes)
            if not args.size:
                return 0
        if not args.size:
            print("규격을 지정하세요: --size 5x7  (또는 색인만: --contact, 목록: --list-sizes)")
            return 2

        only = ([s.strip() for s in args.only.replace(" ", ",").split(",") if s.strip()]
                if args.only else None)
        short_in, long_in = parse_size(args.size)
        if args.upscale == "auto" and not find_upscaler():
            print("외부 업스케일러를 찾지 못했습니다 → 다단계(step) 확대로 진행합니다. "
                  "(설치했다면 UPSCALER_EXE 환경변수에 실행파일 경로를 지정)")
        s = export_batch(short_in, long_in, args.dpi, args.bleed, args.anchor,
                         args.all, args.scene, args.skip_upscale, emit=print,
                         only_ids=only, mode=args.mode, bg=args.bg, marks=args.marks,
                         upscale=args.upscale, order_prefix=not args.no_order_prefix)
    except VNError as exc:          # 규격 오타·매니페스트 부재 등 — 트레이스백 대신 한 줄 안내
        print(exc)
        return 1
    print("-" * 56)
    if s["count"]:
        print(f"완료: {s['count']}장 → {s['dir']}/ (TIFF+JPEG), spec_sheet.json  "
              f"· {size_label(short_in, long_in)} @{args.dpi}DPI")
        print("  색공간: " + ("sRGB ICC 임베드됨" if s["icc"] else
                             "ICC 미임베드(littleCMS 없음) — 인화소에 sRGB 로 알려주세요"))
        if s["marks"]:
            print("  재단선 포함 — 재단 후 마크는 남지 않습니다.")
        if s["upscaled"]:
            print(f"  ⚠ {s['upscaled']}장은 업스케일됨 — 인화 화질 저하 가능. "
                  "--upscale step/auto 로 개선하거나 더 큰 해상도로 재생성 권장.")
            # "더 크게 재생성" 은 매니페스트 두 값이 함께 올라가야 실제로 커진다.
            # 요청 크기만 올리면 생성기 상한에 깎여 과금만 되고 결과는 그대로다.
            print("     재생성 전 확인: output.min_long_edge_px(요청 크기)와 "
                  "image_generator.max_long_edge_px(생성기 상한)를 함께 올렸는지 "
                  "—  python tools/makefun_client.py --check")
        if s["skipped"]:
            print(f"  {s['skipped']}장은 --skip-upscale 로 제외됨.")
    else:
        print("구운 마스터가 없습니다. (selected_image 있고 APPROVED 인 장면 대상 — --all 로 전체)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
