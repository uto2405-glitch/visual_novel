"""프로젝트의 모든 장면에 무드 그라데이션 샘플 이미지 생성·등록·선택·승인."""
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
W, H = 1200, 1800
# 로맨스 무드 팔레트(따뜻→노을)
PAL = [
    ((255, 224, 178), (250, 200, 150)), ((255, 210, 190), (245, 180, 170)),
    ((250, 220, 235), (230, 200, 245)), ((255, 200, 200), (245, 170, 190)),
    ((255, 190, 150), (200, 150, 200)), ((255, 200, 160), (210, 160, 200)),
    ((235, 210, 180), (200, 180, 210)), ((240, 200, 170), (200, 170, 205)),
]


def write_png(path, top, bot):
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    rows = bytearray()
    for y in range(H):
        t = y / H
        px = bytes((int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
        rows.append(0)
        rows += px * W
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))


def adv(*a):
    return subprocess.run([PY, str(ROOT / "tools" / "advance_scene.py"), *a],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def main():
    scenes = sorted((ROOT / "project" / "scenes").glob("SCENE-*.json"))
    for i, f in enumerate(scenes):
        sid = f.stem
        folder = ROOT / "images" / "raw" / sid
        folder.mkdir(parents=True, exist_ok=True)
        top, bot = PAL[i % len(PAL)]
        img = folder / f"{sid}_a.png"
        write_png(img, top, bot)
        adv("add-images", sid, str(img))
        adv("select", sid, "1")
        r = adv("approve", sid)
        print(f"{sid}: {'APPROVED' if r.returncode == 0 else 'FAIL ' + r.stdout.strip()[:60]}")


if __name__ == "__main__":
    main()
