#!/usr/bin/env python3
"""백업 + sha256 무결성 — 원본 소실·비트로트로부터 작품을 지킨다.

snapshot: project/ 를 zip 백업 + project/·images/ 의 sha256 체크섬 매니페스트 저장.
verify  : 최신 매니페스트와 현재 파일을 대조해 변경/손상/누락을 보고(인화 직전 원본 확인).

사용법:
  python tools/backup_project.py snapshot     # 백업 + 체크섬 스냅
  python tools/backup_project.py verify       # 최신 스냅과 현재 비교
  python tools/backup_project.py list         # 백업 목록

쓰기: backups/ 만.  표준 라이브러리만.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / "backups"
TARGETS = ["project", "images"]          # 체크섬 대상
SKIP_PARTS = {"__pycache__", ".git"}


def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_files():
    for top in TARGETS:
        base = ROOT / top
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP_PARTS):
                yield p


def _checksums() -> dict:
    return {p.relative_to(ROOT).as_posix(): {"sha256": _sha256(p), "size": p.stat().st_size}
            for p in _iter_files()}


def _stamp(now: datetime) -> str:
    return f"{now:%Y%m%d_%H%M%S}"


def snapshot(now: datetime) -> int:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(now)
    n = 2
    while (BACKUPS / f"manifest_{stamp}.json").exists():  # 같은 초 재실행 시 이전 스냅 보존
        stamp = f"{_stamp(now)}_{n}"
        n += 1
    sums = _checksums()

    manifest = BACKUPS / f"manifest_{stamp}.json"
    manifest.write_text(json.dumps({"created": stamp, "root": str(ROOT), "files": sums},
                                   ensure_ascii=False, indent=2), encoding="utf-8")

    # project/ 만 zip (images 는 대용량이라 체크섬만; 필요 시 별도 백업)
    proj = ROOT / "project"
    print(f"백업 완료 [{stamp}]")
    if proj.exists():
        zpath = BACKUPS / f"project_{stamp}.zip"
        count = 0
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(proj.rglob("*")):
                if p.is_file() and not (set(p.parts) & SKIP_PARTS):
                    z.write(p, p.relative_to(ROOT).as_posix())
                    count += 1
        print(f"  project zip: {zpath.relative_to(ROOT).as_posix()} ({count}개 파일)")
    else:
        print("  project/ 없음 — zip 생략(체크섬만 기록)")
    print(f"  체크섬 매니페스트: {manifest.relative_to(ROOT).as_posix()} ({len(sums)}개 파일)")
    return 0


def _latest_manifest() -> Path | None:
    if not BACKUPS.exists():
        return None
    ms = sorted(BACKUPS.glob("manifest_*.json"))
    return ms[-1] if ms else None


def verify() -> int:
    m = _latest_manifest()
    if not m:
        print("검증할 백업이 없습니다. 먼저 snapshot 을 실행하세요.")
        return 1
    recorded = json.loads(m.read_text(encoding="utf-8")).get("files", {})
    current = _checksums()
    changed, missing, added = [], [], []
    for rel, meta in recorded.items():
        if rel not in current:
            missing.append(rel)
        elif current[rel]["sha256"] != meta["sha256"]:
            changed.append(rel)
    for rel in current:
        if rel not in recorded:
            added.append(rel)

    print(f"무결성 검증 — 기준: {m.name}")
    print(f"  기록 {len(recorded)} · 현재 {len(current)}")
    for rel in changed:
        print(f"  ✗ 변경/손상: {rel}")
    for rel in missing:
        print(f"  ✗ 누락: {rel}")
    for rel in added:
        print(f"  + 추가: {rel}")
    if not (changed or missing):
        print("무결성 정상 — 기록된 파일이 모두 동일합니다.")
        return 0
    print(f"이상 {len(changed) + len(missing)}건 — 인화/전달 전 확인하세요.")
    return 1


def list_backups() -> int:
    if not BACKUPS.exists() or not any(BACKUPS.glob("manifest_*.json")):
        print("백업 없음.")
        return 0
    for m in sorted(BACKUPS.glob("manifest_*.json")):
        data = json.loads(m.read_text(encoding="utf-8"))
        print(f"  {m.stem.replace('manifest_', '')} — {len(data.get('files', {}))}개 파일")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="백업 + sha256 무결성")
    ap.add_argument("cmd", choices=["snapshot", "verify", "list"])
    args = ap.parse_args()
    if args.cmd == "snapshot":
        return snapshot(datetime.now())
    if args.cmd == "verify":
        return verify()
    return list_backups()


if __name__ == "__main__":
    raise SystemExit(main())
