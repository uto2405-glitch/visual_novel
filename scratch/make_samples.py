"""테스트용 샘플 이미지 생성기 — 외부 이미지 AI 대역.

순수 파이썬 PNG 인코더로 1024x1536(2:3) 석양 교실 무드의 후보 이미지를 만든다.
사용:  python scratch/make_samples.py SCENE-001 2
출력:  scratch/samples/<scene_id>_cand<N>.png
"""
import os
import struct
import sys
import zlib

W, H = 1024, 1536

# 후보별 팔레트: (하늘 위, 하늘 아래/노을, 바닥) RGB
PALETTES = [
    ((255, 214, 120), (255, 120, 60), (90, 45, 60)),    # cand1: 주황 석양
    ((255, 180, 160), (230, 90, 110), (70, 40, 80)),    # cand2: 분홍빛 황혼
    ((250, 230, 150), (250, 150, 40), (60, 50, 70)),    # cand3: 황금빛
    ((210, 160, 200), (240, 100, 90), (50, 35, 70)),    # cand4: 보랏빛
]

DIGITS = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
}


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def png_chunk(tag, data):
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def make_image(path, cand_no):
    sky_top, sky_low, floor = PALETTES[(cand_no - 1) % len(PALETTES)]
    sun_cx, sun_cy, sun_r = int(W * 0.72), int(H * 0.30), 130
    floor_y = int(H * 0.80)          # 하단 20%는 대사 영역(단색에 가깝게)
    bars = [int(W * f) for f in (0.18, 0.50, 0.82)]  # 창틀 세로 실루엣

    # 후보 번호 도장(좌상단): 3x5 비트맵을 32배 확대
    digit = DIGITS[str(cand_no)[-1]]
    dscale, dx0, dy0 = 32, 48, 48

    rows = bytearray()
    for y in range(H):
        rows.append(0)  # PNG filter: none
        row = bytearray()
        for x in range(W):
            if y >= floor_y:                      # 바닥/대사 영역
                r, g, b = floor
            else:                                 # 하늘 그라데이션
                r, g, b = lerp(sky_top, sky_low, y / floor_y)
                dx, dy = x - sun_cx, y - sun_cy
                d2 = dx * dx + dy * dy
                if d2 < sun_r * sun_r:            # 태양
                    r, g, b = 255, 246, 200
                elif d2 < (sun_r + 40) ** 2:      # 태양 테두리 글로우
                    r = min(255, r + 60); g = min(255, g + 40)
                for bx in bars:                   # 창틀 실루엣
                    if abs(x - bx) < 10:
                        r, g, b = r // 3, g // 3, b // 3
                        break
            gx, gy = (x - dx0) // dscale, (y - dy0) // dscale
            if 0 <= gy < 5 and 0 <= gx < 3 and digit[gy][gx] == "1":
                r, g, b = 255, 255, 255          # 후보 번호
            row += bytes((r, g, b))
        rows += row

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr)
           + png_chunk(b"IDAT", zlib.compress(bytes(rows), 6))
           + png_chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    print(f"생성: {path} ({W}x{H})")


def main():
    scene_id = sys.argv[1] if len(sys.argv) > 1 else "SCENE-001"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
    os.makedirs(out_dir, exist_ok=True)
    for n in range(1, count + 1):
        make_image(os.path.join(out_dir, f"{scene_id}_cand{n}.png"), n)


if __name__ == "__main__":
    main()
