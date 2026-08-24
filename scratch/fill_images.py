"""6장면에 샘플 이미지(외부 AI 대역)를 생성·등록·선택·승인해 완성작으로 만든다.

무드에 맞춘 그라데이션 플레이스홀더(1200x1800, 2:3). 실제로는 이 자리에 외부 이미지 AI 결과가 들어간다.
"""
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

# 장면별 무드 색 (위, 아래) — 비→갬 흐름
PALETTE = [
    ((90, 110, 130), (40, 55, 75)),     # 1 비 오는 실내(차분)
    ((120, 130, 120), (70, 80, 70)),    # 2 대화, 따뜻한 백열
    ((80, 95, 120), (45, 50, 80)),      # 3 회상(푸른)
    ((150, 120, 80), (90, 65, 40)),     # 4 수리, 앰버
    ((180, 175, 150), (110, 130, 140)), # 5 비 그침(밝아짐)
    ((235, 200, 150), (150, 175, 190)), # 6 무지개(환한 여운)
]
W, H = 1200, 1800


def write_png(path, top, bot):
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    rows = bytearray()
    for y in range(H):
        t = y / H
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        rows.append(0)
        rows += bytes((r, g, b)) * W
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))


def adv(*args):
    p = subprocess.run([PY, str(ROOT / "tools" / "advance_scene.py"), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr)


def main():
    for i in range(1, 7):
        sid = f"SCENE-{i:03d}"
        folder = ROOT / "images" / "raw" / sid
        folder.mkdir(parents=True, exist_ok=True)
        top, bot = PALETTE[i - 1]
        img = folder / f"{sid}_a.png"
        write_png(img, top, bot)
        adv("add-images", sid, str(img))
        adv("select", sid, "1")
        rc, out = adv("approve", sid)
        print(f"{sid}: {'APPROVED' if rc == 0 else 'FAIL'} {'' if rc == 0 else out.strip()[:80]}")


if __name__ == "__main__":
    main()
