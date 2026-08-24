#!/usr/bin/env python3
"""인화 프리플라이트 — 선택 이미지가 실제로 몇 인치까지 인화 가능한지 승인 전에 수치로 판정한다.

배경: 매니페스트가 min_long_edge_px=1024, print_ready=true 라도 1024px 를 300DPI 로 인화하면
      긴 변이 약 3.4인치(엽서보다 작다). 검사기 A3 는 화면 기준 최소 해상도만 보므로, 실물 인화
      적합성은 이 도구가 따로 판정한다. (SCORECARD/검사기는 건드리지 않는 별도 게이트)

사용법:
  python tools/print_preflight.py                 # 승인/선택된 모든 장면
  python tools/print_preflight.py --scene SCENE-001
  python tools/print_preflight.py --all           # 상태 무관, selected_image 있는 전부
  python tools/print_preflight.py --dpi 300        # 목표 DPI(기본 300)

판독 지원: PNG / JPEG / WEBP / TIFF (헤더만 읽는다 — 전체 로드·Pillow 불필요)
읽기 전용. project/·images/ 를 변경하지 않는다. 표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project" / "manifest.json"
SCENES = ROOT / "project" / "scenes"

MM_PER_IN = 25.4

# (이름, 짧은 변 in, 긴 변 in) — 개인 소장 인화 기본 규격.
# 순서 주의: 회귀 테스트가 rows[0] 을 엽서 4×6 으로 보므로 새 규격은 뒤에 덧붙인다.
PRINT_SIZES = [
    ("엽서 4×6", 4.0, 6.0),
    ("5×7", 5.0, 7.0),
    ("8×10", 8.0, 10.0),
    ("A5", 5.83, 8.27),
    ("A4", 8.27, 11.69),
    ("3×5", 3.5, 5.0),          # 89×127mm, 한국 인화소 최소 사진 규격
]
# 소형 굿즈 규격 — 표에는 보여주되 '인화 가능' 판정에는 넣지 않는다
# (엽서보다 작아 거의 항상 통과해서, 통과시키면 판정이 무의미해진다)
SMALL_SIZES = [
    ("포토카드 55×85mm", 55.0 / MM_PER_IN, 85.0 / MM_PER_IN),
    ("명함 50×90mm", 50.0 / MM_PER_IN, 90.0 / MM_PER_IN),
]
DPI_GOOD = 300   # 사진 인화 권장
DPI_OK = 240     # 근거리 감상 허용 하한


def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


# ------------------------------------------------------------- 이미지 크기 판독
def _tiff_size(f, head):
    """클래식 TIFF 의 첫 IFD 에서 ImageWidth(256)/ImageLength(257) 만 읽는다."""
    bo = "<" if head[:2] == b"II" else ">"
    if struct.unpack(bo + "H", head[2:4])[0] != 42:
        return None                       # BigTIFF(43) 등 변종은 미지원 → 수동 확인
    f.seek(struct.unpack(bo + "I", head[4:8])[0])
    raw = f.read(2)
    if len(raw) < 2:
        return None
    w = h = None
    for _ in range(min(struct.unpack(bo + "H", raw)[0], 256)):
        e = f.read(12)
        if len(e) < 12:
            break
        tag, typ = struct.unpack(bo + "HH", e[:4])
        if tag in (256, 257):
            if typ == 3:                  # SHORT (값이 앞 2바이트에 채워진다)
                val = struct.unpack(bo + "H", e[8:10])[0]
            elif typ == 4:                # LONG
                val = struct.unpack(bo + "I", e[8:12])[0]
            else:
                continue
            if tag == 256:
                w = val
            else:
                h = val
            if w and h:
                break
    return (int(w), int(h)) if w and h else None


def image_size(path: Path):
    """(width, height) 또는 None. PNG/JPEG/WEBP/TIFF 헤더만 읽는다(전체 로드 없음)."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            # PNG
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
            # JPEG
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    b = f.read(1)
                    if not b:
                        break
                    if b != b"\xff":
                        continue
                    marker = f.read(1)
                    while marker == b"\xff":
                        marker = f.read(1)
                    if marker in (b"\xc0", b"\xc1", b"\xc2", b"\xc3",
                                  b"\xc5", b"\xc6", b"\xc7", b"\xc9",
                                  b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"):
                        f.read(3)  # length(2) + precision(1)
                        hh, ww = struct.unpack(">HH", f.read(4))
                        return int(ww), int(hh)
                    seg = f.read(2)
                    if len(seg) < 2:
                        break
                    length = struct.unpack(">H", seg)[0]
                    f.seek(length - 2, 1)
                return None
            # WEBP (VP8X / VP8 / VP8L)
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                fmt = head[12:16]
                if fmt == b"VP8X":
                    wm1 = head[24:27]
                    hm1 = head[27:30]
                    w = 1 + (wm1[0] | wm1[1] << 8 | wm1[2] << 16)
                    h = 1 + (hm1[0] | hm1[1] << 8 | hm1[2] << 16)
                    return w, h
                if fmt == b"VP8 ":
                    w = struct.unpack("<H", head[26:28])[0] & 0x3FFF
                    h = struct.unpack("<H", head[28:30])[0] & 0x3FFF
                    return w, h
                if fmt == b"VP8L":
                    b = head[21:26]
                    bits = b[0] | b[1] << 8 | b[2] << 16 | b[3] << 24
                    w = (bits & 0x3FFF) + 1
                    h = ((bits >> 14) & 0x3FFF) + 1
                    return w, h
            # TIFF (인화 마스터 형식 — 후보로 허용하므로 판독도 지원)
            if head[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
                return _tiff_size(f, head)
    except (OSError, struct.error):
        return None
    return None


# ------------------------------------------------------------- 인화 계산
def fill_dpi(px_w: int, px_h: int, short_in: float, long_in: float):
    """이미지를 인화 규격에 '채움(fill+crop)'으로 앉혔을 때의 실효 DPI 와 크롭률(%)."""
    long_px, short_px = max(px_w, px_h), min(px_w, px_h)
    if short_px <= 0 or short_in <= 0 or long_in <= 0:
        return 0.0, 0.0
    dpi = min(short_px / short_in, long_px / long_in)
    if dpi <= 0:
        return 0.0, 0.0
    # 크롭: 비구속 축의 초과분
    phys_short = short_px / dpi
    phys_long = long_px / dpi
    crop_short = max(0.0, (phys_short - short_in) / phys_short) if phys_short else 0.0
    crop_long = max(0.0, (phys_long - long_in) / phys_long) if phys_long else 0.0
    crop = round(max(crop_short, crop_long) * 100, 1)
    return dpi, crop


def grade(dpi: float, target: int) -> str:
    if dpi >= target:
        return "좋음"
    if dpi >= DPI_OK:
        return "보통"
    return "업스케일필요"


def _row(name: str, s_in: float, l_in: float, px_w: int, px_h: int, target: int) -> dict:
    dpi, crop = fill_dpi(px_w, px_h, s_in, l_in)
    dpi = round(dpi)                           # 표시 DPI 와 판정을 일치시킨다
    return {"size": name, "dpi": dpi, "crop_pct": crop, "grade": grade(dpi, target),
            "short_in": s_in, "long_in": l_in,
            "mm": [round(s_in * MM_PER_IN), round(l_in * MM_PER_IN)]}


def preflight_image(px_w: int, px_h: int, target: int = DPI_GOOD) -> dict:
    """이미지 픽셀 → 규격별 판정 + 목표DPI 만족 최대 크기 + 요약."""
    rows, best, best_area = [], None, -1.0
    for name, s_in, l_in in PRINT_SIZES:
        r = _row(name, s_in, l_in, px_w, px_h, target)
        rows.append(r)
        area = s_in * l_in                     # 통과 규격 중 '물리 면적 최대'를 최대 규격으로
        if r["dpi"] >= target and area > best_area:
            best, best_area = name, area
    small = [_row(n, s, l, px_w, px_h, target) for n, s, l in SMALL_SIZES]
    # 목표DPI 로 이 이미지가 낼 수 있는 긴 변 인치
    long_px = max(px_w, px_h)
    max_long_in = round(long_px / target, 2)
    return {"px": [px_w, px_h], "target_dpi": target, "rows": rows, "small_rows": small,
            "max_size_at_target": best, "max_long_in_at_target": max_long_in,
            "printable": best is not None}


def needed_px(name: str, target: int = DPI_GOOD):
    """규격 name 을 target DPI(2:3 기준)로 인화하려면 필요한 (짧은변, 긴변) 픽셀."""
    for n, s_in, l_in in PRINT_SIZES:
        if n == name:
            # 2:3 이미지가 채우려면 짧은 변이 구속 → short_in*dpi, 긴 변은 그 3/2
            short_px = round(s_in * target)
            long_px = round(max(l_in, s_in * 1.5) * target)
            return short_px, long_px
    return None


# ------------------------------------------------------------- 장면 수집
def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect(scene_filter: str | None, include_all: bool):
    if not MANIFEST.exists():
        raise RuntimeError("project/manifest.json 이 없습니다.")
    out = []
    for f in sorted(SCENES.glob("SCENE-*.json")) if SCENES.exists() else []:
        sc = load(f)
        if not isinstance(sc, dict):
            continue
        if scene_filter and sc.get("scene_id") != scene_filter:
            continue
        sel = (sc.get("assets", {}).get("selected_image") or "").strip()
        status = sc.get("status", "")
        if not sel:
            continue
        if not include_all and status != "APPROVED" and not scene_filter:
            continue
        out.append((sc, sel))
    return out


def _pad(s: str, width: int) -> str:
    """한글은 콘솔에서 두 칸을 먹으므로 표시폭 기준으로 채운다."""
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
    return s + " " * max(0, width - w)


def _row_line(r: dict) -> str:
    """규격 1줄 표시 — 인치 이름 옆에 mm 를 같이 보여 인화소 주문서와 맞춘다."""
    mark = {"좋음": "OK ", "보통": "~  ", "업스케일필요": "✗  "}[r["grade"]]
    mm = f"({r['mm'][0]}×{r['mm'][1]}mm)"
    crop = f" · 크롭 {r['crop_pct']}%" if r["crop_pct"] > 1 else ""
    return f"{mark}{_pad(r['size'], 18)}{_pad(mm, 14)}{r['dpi']:>4}DPI  {r['grade']}{crop}"


def report(target: int, scene_filter: str | None, include_all: bool) -> int:
    mf = load(MANIFEST)
    min_edge = mf.get("output", {}).get("min_long_edge_px", 1024)
    try:
        cur_in = round(int(min_edge) / target, 2)
    except (TypeError, ValueError):
        cur_in = None

    print("=" * 60)
    print(f"인화 프리플라이트 — 목표 {target}DPI  (개인 소장 인화 기준)")
    print("=" * 60)
    if cur_in is not None:
        note = "엽서도 빠듯" if cur_in < 4 else ("최대 " + str(cur_in) + "인치")
        print(f"매니페스트 min_long_edge_px={min_edge} → {target}DPI 에서 긴 변 {cur_in}인치 ({note})")
    print()

    scenes = collect(scene_filter, include_all)
    if not scenes:
        print("판정할 장면이 없습니다. (selected_image 가 있고 APPROVED 인 장면 대상 — --all 로 전체)")
        return 0

    worst = 0
    for sc, sel in scenes:
        sid = sc.get("scene_id", "?")
        p = ROOT / sel
        size = image_size(p)
        print(f"[{sid}] {Path(sel).name}", end="  ")
        if size is None:
            print("→ 크기 판독 불가 (수동 확인 필요)")
            worst = max(worst, 2)
            print()
            continue
        pf = preflight_image(size[0], size[1], target)
        print(f"{size[0]}×{size[1]}px  →  {target}DPI 최대: "
              f"{pf['max_size_at_target'] or '(엽서 미만)'}  (긴 변 {pf['max_long_in_at_target']}인치)")
        for r in sorted(pf["rows"], key=lambda r: r["short_in"] * r["long_in"]):
            print("     " + _row_line(r))
        for r in pf["small_rows"]:             # 굿즈 규격은 판정 밖 참고용
            print("     ·  " + _row_line(r))
        if not pf["printable"]:
            worst = max(worst, 1)
        print()

    print("-" * 60)
    if worst == 0:
        print("판정 완료: 모든 대상 장면이 최소 한 규격 이상 인화 가능(≥목표DPI).")
    else:
        print("판정 완료: 일부 장면이 목표DPI 를 못 채웁니다 — 업스케일 또는 재생성 권장.")
        for name, _s, _l in PRINT_SIZES[:3]:
            need = needed_px(name, target)
            if need:
                print(f"  · {name} @{target}DPI 인화하려면 최소 약 {need[0]}×{need[1]}px 로 생성하세요.")
    print("주의: 예술적 발색·톤은 사람 시사(SCORECARD C)로 최종 판정합니다.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="인화 프리플라이트 — 실물 인화 규격 판정(읽기 전용)")
    ap.add_argument("--scene", help="특정 장면만 (예: SCENE-001)")
    ap.add_argument("--all", action="store_true", help="상태 무관, selected_image 있는 전부")
    ap.add_argument("--dpi", type=int, default=DPI_GOOD, help="목표 DPI (기본 300)")
    args = ap.parse_args()
    try:
        return report(args.dpi, args.scene, args.all)
    except RuntimeError as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
