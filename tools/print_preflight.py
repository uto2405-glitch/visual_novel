#!/usr/bin/env python3
"""인화 프리플라이트 — 선택 이미지가 실제로 몇 인치까지 인화 가능한지 승인 전에 수치로 판정한다.

배경: 매니페스트가 min_long_edge_px=1024, print_ready=true 라도 1024px 를 300DPI 로 인화하면
      긴 변이 약 3.4인치(엽서보다 작다). 검사기 A3 는 화면 기준 최소 해상도만 보므로, 실물 인화
      적합성은 이 도구가 따로 판정한다. (SCORECARD/검사기는 건드리지 않는 별도 게이트)

판정에서 끝내지 않는다 — 모자랄 때 **규격마다 매니페스트의 어느 키를 얼마로 바꿔야 하는지**
값까지 찍는다. 그 조치는 활성 엔진의 클라이언트(size_recipe)가 만든다: 상한은 8의 배수로 내려
잘리고(2250 → 2248), ComfyUI 는 hires 가 1차 캔버스의 2배까지라 8×10(3600px)은 상한만 올려서는
닿지 않는다. 이 규칙을 여기서 다시 구현하면 상한이 하나 더 생길 때 이 파일만 옛 답을 말한다.

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
import struct
import sys
import unicodedata
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:          # 저장소가 복제된 곳에서 이 파일만 적재돼도 '옆에 있는' vn_core 를 쓴다
    sys.path.insert(0, str(_HERE))

import vn_core                                           # noqa: E402
from vn_core import VNError, load_json, load_json_safe   # noqa: E402  (console_guard 는 import 만으로 적용)

# 경로 이름은 vn_core 규약을 따르되 값은 이 파일 위치에서 계산한다.
# (자가진단은 저장소를 임시폴더에 복제해 이 모듈만 따로 적재한다 — 그때도 자기 트리 안만 봐야 한다.)
# 장면 폴더 상수는 두지 않는다 — 훑기는 vn_core.iter_scenes 하나뿐이다.
ROOT = _HERE.parent
MANIFEST = ROOT / "project" / "manifest.json"

load = load_json          # 하위호환: 기존 print_preflight.load(path) 호출부 유지

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


# 판독 결과 메모이즈 — 웹 스튜디오는 화면을 새로 그릴 때마다 모든 장면의 선택본을 물어본다.
# 키에 (수정시각·크기)를 넣어 파일이 바뀌면 자동으로 무효화된다(오래된 값이 남지 않는다).
_SIZE_CACHE: dict[str, tuple] = {}
_SIZE_CACHE_MAX = 512


def image_size(path: Path):
    """(width, height) 또는 None. PNG/JPEG/WEBP/TIFF 헤더만 읽는다(전체 로드 없음)."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None                      # 없는 파일은 캐시하지 않는다(생기면 바로 반영)
    key = (st.st_mtime_ns, st.st_size)
    name = str(p)
    hit = _SIZE_CACHE.get(name)
    if hit is not None and hit[0] == key:
        return hit[1]
    size = _read_image_size(p)
    if len(_SIZE_CACHE) >= _SIZE_CACHE_MAX:
        _SIZE_CACHE.clear()              # 단일 사용자 도구 — LRU 대신 통째로 비운다
    _SIZE_CACHE[name] = (key, size)
    return size


def _read_image_size(path: Path):
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


def needed_px_for(short_in: float, long_in: float, target: int = DPI_GOOD):
    """임의 규격(인치)을 target DPI 로 채우려면 2:3 원본에 필요한 (짧은변, 긴변) 픽셀.

    프리셋 밖 규격(print_export 의 자유 규격·mm 규격)도 같은 산수를 써야 두 도구가 다른 수를
    말하지 않는다 — needed_px 는 이 함수의 프리셋 조회판이다.
    """
    if short_in <= 0 or long_in <= 0:
        return None
    # 2:3 이미지가 채우려면 짧은 변이 구속 → short_in*dpi, 긴 변은 그 3/2
    return round(short_in * target), round(max(long_in, short_in * 1.5) * target)


def needed_px(name: str, target: int = DPI_GOOD):
    """규격 name 을 target DPI(2:3 기준)로 인화하려면 필요한 (짧은변, 긴변) 픽셀."""
    for n, s_in, l_in in PRINT_SIZES:
        if n == name:
            return needed_px_for(s_in, l_in, target)
    return None


# ------------------------------------------------------------- 장면 수집
def collect(scene_filter: str | None, include_all: bool):
    """판정 대상 (장면, 선택 이미지) 목록 — 훑기·판정은 vn_core 단일 출처를 쓴다.

    손상된 장면 하나가 보고서 전체를 죽이지 않는다(iter_scenes 가 건너뛴다).
    --scene 으로 지목한 한 장은 승인 전이라도 판정한다(인화 전 확인이 이 도구의 목적).
    """
    if not MANIFEST.exists():
        raise VNError("project/manifest.json 이 없습니다.")
    out = []
    for _f, sc in vn_core.iter_scenes():
        if scene_filter and sc.get("scene_id") != scene_filter:
            continue
        if not vn_core.is_deliverable(sc, include_all or bool(scene_filter)):
            continue
        out.append((sc, vn_core.selected_of(sc)))
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


def _check_cmd(client) -> str:
    """그 엔진의 무과금 확인 명령 — 모듈 이름이 곧 파일 이름이다(둘을 따로 적으면 갈린다)."""
    name = getattr(client, "__name__", "") or "comfyui_client"
    return f"python tools/{name}.py --check"


def engine_note(engine=None) -> list[str]:
    """활성 엔진이 **지금 설정으로 실제로 내는 크기**와 상한 경고.

    예전 이 자리는 makefun_client 만 물었다 — 기본 엔진이 ComfyUI 로 바뀐 뒤로는 **쓰지도 않는
    엔진의 상한**을 보고 "경고 없음" 이라고 말했고, ComfyUI 의 hires 2배 상한(1248 → 2496px)은
    한 번도 화면에 뜨지 않았다. 그래서 8×10(3600px)을 노린 사용자는 매니페스트 두 값을 올리고
    다시 렌더한 뒤에야 2496px 을 보게 됐다.

    엔진 선택 규칙은 image_gen 한 곳에 있고 여기서는 **main() 이 건네준 것**을 전달만 한다
    (라이브러리 경로에서 image_gen 을 부르면 print_preflight ↔ makefun_client ↔ image_gen
    지연 고리가 생긴다 — selftest L02).

    실패는 두 가지로 나눈다 — 섞으면 "왜 경고가 안 뜨지?"를 추적할 수 없다.
      * 엔진을 못 정했다: 생성기를 쓰지 않는 설치다. 조용히 넘어간다(인화 판정은 그대로 돈다).
      * 정했는데 못 읽었다(매니페스트 손상·계산 오류): 상한을 **확인하지 못했다는 사실**을
        보고한다. 삼키면 상한이 안전한 것처럼 보인 채로 재생성(유료 엔진이면 과금)으로 이어진다.
    """
    if not engine:
        return []
    label, client = engine
    try:
        plan = client.size_plan()
        warns = list(client.size_warnings(plan))
    except Exception as exc:           # 매니페스트 손상·값 형식 오류 등
        return [f"※ 생성기 상한을 확인하지 못했습니다 — 상한 계산 실패 "
                f"({type(exc).__name__}: {exc}). 확인: {_check_cmd(client)}"]
    long_px = max(int(plan.get("width", 0)), int(plan.get("height", 0)))
    out = [f"엔진 {label} 는 지금 {plan.get('width')}×{plan.get('height')}px 로 그립니다 "
           f"(요청 {plan.get('want')}px · 상한 {plan.get('cap')}px"
           + (f" · hires 상한 {plan['hires_cap']}px" if plan.get("hires_cap") else "") + ")"]
    if long_px:
        pf = preflight_image(long_px, long_px, DPI_GOOD)   # 긴 변만 보면 되므로 정사각으로 재도 같다
        out.append(f"  → 그 크기는 {DPI_GOOD}DPI 로 긴 변 {round(long_px / DPI_GOOD, 2)}인치 "
                   f"(최대 {pf['max_size_at_target'] or '엽서 미만'})")
    return out + ["※ " + m for m in warns]


# 하위호환 별칭 — 예전 이름으로 부르던 자리가 남아 있어도 깨지지 않는다.
generator_cap_note = engine_note


def recipe_lines(long_px: int, engine=None, indent: str = "      ") -> list[str]:
    """목표 긴 변을 내려면 매니페스트를 어떻게 고치는지 — 값까지 적힌 실행 가능한 조치.

    조치 계산은 엔진 클라이언트(size_recipe)가 한다. 여기서 규칙을 다시 구현하면 상한이 하나
    더 생길 때(ComfyUI 의 hires 2배처럼) 이 파일만 조용히 옛날 답을 계속 말한다.
    """
    if not engine:
        return []
    _label, client = engine
    fn = getattr(client, "size_recipe", None)
    if fn is None:
        return []
    try:
        r = fn(long_px)
    except Exception as exc:
        return [f"{indent}(조치를 계산하지 못했습니다: {type(exc).__name__}: {exc})"]
    if r.get("reachable"):
        return [f"{indent}지금 설정 그대로 나옵니다 — 고칠 값 없음"]
    lines = [f"{indent}{path} = {val}" for path, val in r.get("edits") or []]
    if not r.get("feasible"):
        lines.append(f"{indent}※ 이 엔진의 하드 상한을 넘습니다 — 생성으로는 닿지 않습니다"
                     " (승인 뒤 업스케일 경로로만 가능).")
    if r.get("hires_note"):
        lines.append(f"{indent}※ {r['hires_note']}")
    return lines


def report(target: int, scene_filter: str | None, include_all: bool, engine=None) -> int:
    if not MANIFEST.exists():
        raise VNError("project/manifest.json 이 없습니다.")
    mf = load_json_safe(MANIFEST, {})
    min_edge = (mf.get("output") or {}).get("min_long_edge_px", 1024)
    try:
        cur_in = round(int(min_edge) / target, 2)
    except (TypeError, ValueError):
        cur_in = None

    print("=" * 60)
    print(f"인화 프리플라이트 — 목표 {target}DPI  (개인 소장 인화 기준)")
    print("=" * 60)
    if cur_in is not None:
        note = "엽서도 빠듯" if cur_in < 4 else ("최대 " + str(cur_in) + "인치")
        print(f"매니페스트 min_long_edge_px={min_edge} → {target}DPI 에서 긴 변 {cur_in}인치 ({note})"
              " — '최소 요청' 값이라 실제 렌더는 더 클 수 있습니다")
    for line in engine_note(engine):
        print(line)
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
            # image_size 는 '깨진 헤더' 와 '파일이 없다' 를 똑같이 None 으로 돌려준다.
            # 그 둘을 뭉뚱그리면, 새 clone 을 연 사람이 멀쩡한 PNG 를 찾아 헤매다가
            # 있지도 않은 그림을 업스케일하라는 말까지 듣게 된다.
            if not p.exists():
                print("→ 원본 파일 없음 (images/ 를 복원하거나 그 장면을 revise 하세요)")
            else:
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
        label = engine[0] if engine else None
        print(f"규격별 — 새로 생성해서 채우려면 매니페스트를 이렇게 고칩니다"
              + (f" (엔진 {label})" if label else "") + ":")
        for name, _s, _l in PRINT_SIZES[:3]:
            need = needed_px(name, target)
            if not need:
                continue
            print(f"  · {name} @{target}DPI — 최소 {need[0]}×{need[1]}px")
            for line in recipe_lines(need[1], engine) or ["      (엔진을 확인할 수 없어 조치를 계산하지 못했습니다)"]:
                print(line)
        if engine:
            print(f"  고친 뒤 과금 없이 확인: {_check_cmd(engine[1])}  ·  python tools/doctor.py")
        else:
            print("  · 매니페스트는 두 값을 함께 올려야 합니다 — output.min_long_edge_px(요청 크기)와 "
                  "image_generator.max_long_edge_px(생성기 상한).")
        print("  ※ 이미 승인한 컷을 재생성하면 그림 자체가 바뀝니다(구도·표정·손). 같은 그림의 "
              "픽셀만 키우려면 python tools/print_export.py --upscale step 로 굽습니다.")
    print("주의: 예술적 발색·톤은 사람 시사(SCORECARD C)로 최종 판정합니다.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="인화 프리플라이트 — 실물 인화 규격 판정(읽기 전용)")
    ap.add_argument("--scene", help="특정 장면만 (예: SCENE-001)")
    ap.add_argument("--all", action="store_true", help="상태 무관, selected_image 있는 전부")
    ap.add_argument("--dpi", type=int, default=DPI_GOOD, help="목표 DPI (기본 300)")
    args = ap.parse_args()

    def resolve_engine():
        """활성 이미지 엔진 (라벨, 클라이언트 모듈) — **CLI 진입점 안에서만** 정한다.

        image_gen 은 이 도구보다 위층이고 makefun_client 를 거쳐 여기로 돌아오는 지연 고리를
        만든다. 그 고리는 '이 도구를 직접 실행한 사람' 경로에서만 생기므로(모듈 import 로는
        실행되지 않는다) main() 안에 둔다 — 라이브러리로 쓰는 webapp 경로는 여기를 지나지 않는다.
        엔진 선택 규칙 자체는 image_gen 하나가 갖는다(여기서 다시 구현하지 않는다).
        """
        try:
            import image_gen
            engine = image_gen.active_engine()
            return image_gen.label(engine), image_gen.client(engine)
        except Exception:
            return None                # 생성기를 쓰지 않는 설치 — 인화 판정은 그대로 돈다

    try:
        return report(args.dpi, args.scene, args.all, resolve_engine())
    except VNError as exc:          # VNError 는 RuntimeError 파생 — 기존 처리 경로와 동일하다
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
