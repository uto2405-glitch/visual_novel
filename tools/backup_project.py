#!/usr/bin/env python3
"""백업 + sha256 무결성 + 복원 — 원본 소실·비트로트로부터 작품을 지킨다.

snapshot: project/ 를 zip 백업 + project/·images/ 의 sha256 체크섬 매니페스트 저장.
verify  : 매니페스트와 현재 파일을 대조해 변경/손상/누락을 보고(인화 직전 원본 확인).
list    : 백업 목록.
restore : 스냅샷 zip 을 되돌린다(파괴적 — 미리보기·확인·되돌림 백업 필수).
prune   : 오래된 스냅샷 정리(보존 개수 상한).
migrate : project/ 에 남은 옛 scenes_backup_* 사본을 backups/legacy/ 로 이관.
schedule: 주기 자동 스냅샷+verify 용 스크립트/등록 명령 안내(등록은 사용자가 직접 실행).

사용법:
  python tools/backup_project.py snapshot                  # 백업 + 체크섬 스냅
  python tools/backup_project.py snapshot --with-images    # 승인 이미지 원본까지 zip 에 포함
  python tools/backup_project.py snapshot --dest D:/backup # 외장드라이브/클라우드 폴더에 사본
  python tools/backup_project.py snapshot --force          # 내용이 같아도 zip 을 새로 굽는다
  python tools/backup_project.py snapshot --include-private # 개인 대화 기록까지 담는다(기본은 제외)
  python tools/backup_project.py verify                    # 최신 스냅과 현재 비교
  python tools/backup_project.py list
  python tools/backup_project.py restore --dry-run         # 복원 차이만 미리보기
  python tools/backup_project.py restore --snapshot 20260824_224601
  python tools/backup_project.py prune --keep 10
  python tools/backup_project.py prune --keep 10 --keep-images 3   # 이미지 든 스냅샷은 따로 상한
  python tools/backup_project.py migrate --dry-run          # project/scenes_backup_* → backups/legacy/
  python tools/backup_project.py schedule --time 21:00

쓰기: backups/ 와 --dest 로 지정한 폴더만. 예외로 restore 만 project/·images/ 를 되돌린다.
표준 라이브러리만.

복구할 때 zip 을 손으로 풀 필요는 없다 — restore 가 차이 미리보기·확인·되돌림 백업까지 한다.
이미지 원본은 기본 백업에 없다(체크섬만) — 지키려면 snapshot --with-images 를 쓴다.
개인 대화 기록(vn_core.PRIVATE_PATTERNS — chatlog.json · talk_*.json · *.archive.jsonl ·
memory_*.json)은 zip 에도 체크섬 매니페스트에도 **담지 않는다**. --dest 가 클라우드 동기화
폴더를 겨냥한 옵션이라, 기본값이 '담는다' 이면 표준 백업 명령 한 줄이 사적 대화를 밖으로
내보낸다. 정말 담으려면 --include-private 를 명시한다(--dest 와 함께 쓰면 확인을 묻는다).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:          # 저장소가 복제된 곳에서 이 파일만 적재돼도 '옆에 있는' vn_core 를 쓴다
    sys.path.insert(0, str(_HERE))

import vn_core                                                              # noqa: E402
from vn_core import VNError, atomic_write_json, load_json_safe, safe_path   # noqa: E402

# 경로 이름은 vn_core 규약을 따르되 값은 이 파일 위치에서 계산한다.
# (자가진단이 저장소를 복제해 이 모듈만 적재하므로 — 그때도 복제본 안에서만 백업·복원한다.)
ROOT = _HERE.parent
BACKUPS = ROOT / "backups"
TARGETS = ["project", "images"]          # 체크섬 대상
SKIP_PARTS = {"__pycache__", ".git"}
RESTORE_TOPS = ("project", "images")     # 복원이 건드릴 수 있는 최상위 폴더(그 밖은 거부)
KEEP_DEFAULT = 12                        # prune 기본 보존 개수(체크섬만 있는 가벼운 스냅샷 기준)
# 이미지 원본을 담은 스냅샷은 한 장이 수백 MB 다(실측 118.4MB). 가벼운 스냅샷과 같은 상한(12)을
# 쓰면 backups/ 가 GB 단위로 자란다 — 그래서 '이미지 든 스냅샷' 만 따로 더 짧게 센다.
# 몇 개를 남기든 **최신 스냅샷과 이미지가 든 최신 스냅샷은 절대 지우지 않는다**(prune 의 안전장치).
KEEP_IMAGES_DEFAULT = 3
TASK_NAME_DEFAULT = "VN-AutoBackup"
LEGACY_SCENE_DIRS = "scenes_backup_*"    # 옛 도구가 project/ 안에 남긴 사본(백업 폴더로 이관 대상)


def _sha256_fh(fh) -> str:
    h = hashlib.sha256()
    for chunk in iter(lambda: fh.read(1 << 16), b""):
        h.update(chunk)
    return h.hexdigest()


def _sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return _sha256_fh(f)


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _iter_files(include_private: bool = False):
    for top in TARGETS:
        base = ROOT / top
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or (set(p.parts) & SKIP_PARTS):
                continue
            if not include_private and vn_core.is_private_rel(_rel(p)):
                continue
            yield p


def _checksums(include_private: bool = False) -> dict:
    """매니페스트에 적을 sha256 목록.

    사적 대화 기록은 zip 에서 빼는 것으로 끝나지 않는다 — **매니페스트에서도 뺀다.**
    매니페스트가 약속한 것과 zip 이 주는 것이 갈리면 복원 직후 verify 가 있지도 않은
    '누락' 을 뱉고(실측 전례: _gen_meta 12개), 그 처방은 같은 스냅샷을 다시 restore 하라는
    무한 루프였다. 게다가 매니페스트는 --dest 로 함께 복사되는 파일이라, 내용이 아니어도
    **대화 상대의 이름이 박힌 파일 목록**이 클라우드로 나간다.
    """
    return {_rel(p): {"sha256": _sha256(p), "size": p.stat().st_size}
            for p in _iter_files(include_private)}


def _stamp(now: datetime) -> str:
    return f"{now:%Y%m%d_%H%M%S}"


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}GB"


def _load_json(p: Path) -> dict:
    return load_json_safe(p, {})


def _base_dir(base: Path | None) -> Path:
    return BACKUPS if base is None else Path(base)


def _confirm(question: str, word: str, assume_yes: bool) -> bool:
    """파괴적 동작 전 확인. 비대화형(스케줄러 등)에서는 --yes 없이는 진행하지 않는다."""
    print(question)
    if assume_yes:
        print("  --yes 로 확인됨.")
        return True
    try:
        interactive = bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):     # 스케줄러 등 stdin 이 닫힌 실행
        interactive = False
    if not interactive:
        print("  대화형 입력이 불가합니다. 확인했다면 --yes 를 붙여 다시 실행하세요.")
        return False
    try:
        ans = input(f"  계속하려면 '{word}' 를 입력하세요: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n취소했습니다.")
        return False
    if ans != word:
        print("취소했습니다.")
        return False
    return True


# ---------------------------------------------------------------- 백업 대상 수집

def _project_files(include_private: bool = False) -> list[Path]:
    """zip 에 담을 project/ 의 파일들 — 기본은 **사적 대화 기록을 뺀다.**

    이 함수가 담는 것이 그대로 --dest(클라우드 동기화 폴더를 겨냥한 옵션)로 복사된다.
    기본값이 '담는다' 이면 런북의 표준 명령 한 줄이 인물과 나눈 대화를 제3자 서버에 올린다.
    목록의 정본은 vn_core.PRIVATE_PATTERNS 하나다(SCHEMA §3.1 · .gitignore 와 같은 넷).
    """
    proj = ROOT / "project"
    if not proj.exists():
        return []
    out = []
    for p in sorted(proj.rglob("*")):
        if not p.is_file() or (set(p.parts) & SKIP_PARTS):
            continue
        if not include_private and vn_core.is_private_rel(_rel(p)):
            continue
        out.append(p)
    return out


def _private_files() -> list[Path]:
    """지금 트리에 실제로 있는 사적 대화 기록(없으면 빈 목록 — 대개 여기다)."""
    proj = ROOT / "project"
    if not proj.exists():
        return []
    return [p for p in sorted(proj.rglob("*"))
            if p.is_file() and vn_core.is_private_rel(_rel(p))]


def _approved_images() -> list[Path]:
    """감상본·인화에 실릴 컷이 쓰는 이미지 — 유일본이라 소실되면 재생성 비용이 든다.

    '실릴 컷인가'의 판정은 vn_core.is_deliverable 하나뿐이다(상태를 추가해도 여기는 그대로).
    다만 **훑기는 이 파일의 ROOT 아래에서 한다** — 백업·복원은 대상 트리를 인자로 받는
    도구라서(테스트·복제본이 ROOT 를 갈아끼운다) 저장소 전역 폴더를 보면 엉뚱한 트리의
    이미지를 담는다. 그래서 iter_scenes 대신 같은 순서로 자기 트리를 읽는다.
    후보(raw_images)까지 담는 것은 의도다 — 선택본만으로는 다른 컷을 다시 고를 수 없다.

    컷 옆의 ``_gen_meta.json`` 도 함께 담는다. 매니페스트를 쓰는 :func:`_checksums` 는
    ``images/`` 를 통째로 훑어 이 파일까지 **기록**하는데 zip 에는 안 들어가서, 매니페스트가
    약속한 것과 zip 이 주는 것이 갈렸다. 그 결과 복원 직후 ``verify`` 가 장면마다 '✗ 누락'
    을 뱉고(실측: 매니페스트 112 · zip 100 · 차이는 정확히 이 12개), 처방으로 **같은
    스냅샷을 다시 restore** 하라고 안내했다 — 무엇을 다시 풀어도 없는 파일이라 무한 루프다.
    """
    out: list[Path] = []
    seen: set[Path] = set()
    cut_dirs: list[Path] = []        # 컷이 들어 있는 폴더 — 아래 _gen_meta 를 같은 곳에서 찾는다
    sdir = ROOT / "project" / "scenes"
    if not sdir.exists():
        return out
    for sp in sorted(sdir.glob("*.json")):
        data = _load_json(sp)
        if not vn_core.is_deliverable(data):
            continue
        assets = data.get("assets")
        if not isinstance(assets, dict):
            continue
        cands = list(assets.get("raw_images") or [])
        cands.append(vn_core.selected_of(data))
        for rel in cands:
            if not isinstance(rel, str) or not rel.strip():
                continue
            p = (ROOT / rel).resolve()
            try:
                p.relative_to(ROOT)          # 저장소 밖을 가리키는 경로는 백업하지 않는다
            except ValueError:
                continue
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
                if p.parent not in cut_dirs:
                    cut_dirs.append(p.parent)
    # 컷 폴더의 생성 메타 — 경로를 다시 조립하지 않고 **컷이 실제로 있던 폴더**에서 찾는다
    # (폴더 규칙이 바뀌어도 따라간다). 없으면 조용히 넘어간다 — 옛 트리에는 없을 수 있다.
    for d in cut_dirs:
        meta = d / vn_core.GEN_META_NAME
        if meta.is_file() and meta not in seen:
            seen.add(meta)
            out.append(meta)
    return out


def _all_images() -> list[Path]:
    base = ROOT / "images"
    if not base.exists():
        return []
    return [p for p in sorted(base.rglob("*"))
            if p.is_file() and not (set(p.parts) & SKIP_PARTS)]


def _zip_payload(with_images: bool, images_scope: str,
                 include_private: bool = False) -> list[Path]:
    files = _project_files(include_private)
    if with_images:
        imgs = _all_images() if images_scope == "all" else _approved_images()
        seen = set(files)
        files += [p for p in imgs if p not in seen]
    return files


def _legacy_scene_dirs() -> list[Path]:
    """옛 도구가 project/ 안에 만들어 둔 scenes_backup_* 사본.

    project/ 안에 있으면 매번 zip 에 통째로 들어가 백업이 부풀고, 장면 폴더를 훑는 도구들이
    사본을 실제 장면으로 착각할 여지도 생긴다. backups/ 로 옮기는 것이 맞다(migrate).
    """
    proj = ROOT / "project"
    if not proj.exists():
        return []
    return sorted(p for p in proj.glob(LEGACY_SCENE_DIRS) if p.is_dir())


def _warn_no_images(prefix: str = "  ") -> None:
    """이미지가 zip 에 안 들어갔다는 사실을 '숫자로' 알린다.

    체크섬만 기록된 이미지는 사고가 났을 때 '무엇이 사라졌는지'만 알려줄 뿐 되돌리지 못한다.
    승인 이미지는 유료 생성물이자 유일본이라, 이 한 줄이 실제 복구 가능 여부를 가른다.
    """
    imgs = _approved_images()
    if imgs:
        size = _human(sum(p.stat().st_size for p in imgs if p.exists()))
        print(f"{prefix}※ 이미지는 체크섬만 기록됨 — 승인 이미지 {len(imgs)}개({size})는 "
              "이 zip 으로 복구할 수 없습니다.")
        print(f"{prefix}   원본까지 지키려면: snapshot --with-images "
              "(외장드라이브 사본은 --dest D:/backup)")
    else:
        print(f"{prefix}※ 이미지는 체크섬만 기록됨 — 원본 사본이 필요하면 --with-images")


def _warn_private(private: list[Path], included: bool, dest: str | None,
                  prefix: str = "  ") -> None:
    """사적 대화 기록에 대해 **이번 스냅샷이 실제로 무엇을 했는지** 한자리에서 말한다.

    조용한 쪽이 위험한 방향이 서로 반대다.
      * 뺐다면 — 사용자는 "백업했다" 고 믿는다. 무엇이 안 담겼는지 수로 말해야 한다.
      * 담았는데 --dest 가 있다면 — 그 폴더는 대개 클라우드 동기화 폴더다. 여기서 조용하면
        사적 대화가 제3자 서버로 올라간 사실을 아무도 모른다. 그래서 이쪽은 크게 외친다.
    """
    if not private:
        return
    n = len(private)
    size = _human(sum(p.stat().st_size for p in private if p.exists()))
    if not included:
        print(f"{prefix}※ 개인 대화 기록 {n}개({size})는 백업에서 제외했습니다 — "
              "인물과 나눈 사적 대화입니다.")
        print(f"{prefix}   담으려면 --include-private (zip 과 체크섬 매니페스트 양쪽에 들어갑니다).")
        return
    print(f"{prefix}⚠ 개인 대화 기록 {n}개({size})를 이 백업에 담았습니다 — --include-private")
    for q in private[:6]:
        print(f"{prefix}    - {_rel(q)}")
    if n > 6:
        print(f"{prefix}    ... 외 {n - 6}개")
    if dest:
        print(f"{prefix}⚠⚠ 그 사본이 지금 외부 폴더로 복사됩니다: {dest}")
        print(f"{prefix}    클라우드 동기화 폴더라면 인물과 나눈 대화가 제3자 서버로 올라갑니다.")
        print(f"{prefix}    → docs/PRIVACY_HOSTING.md §1")


def _warn_legacy(prefix: str = "  ") -> None:
    old = _legacy_scene_dirs()
    if not old:
        return
    n = sum(1 for d in old for p in d.rglob("*") if p.is_file())
    print(f"{prefix}※ project/{LEGACY_SCENE_DIRS} 사본 {len(old)}개({n}개 파일)가 남아 있어 "
          "백업에 매번 함께 담깁니다.")
    print(f"{prefix}   정리: python tools/backup_project.py migrate --dry-run  → 확인 후 --yes")


def _write_zip(zpath: Path, files: list[Path]) -> int:
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
    return len(files)


# ---------------------------------------------------------------- snapshot

def _same_as_latest(sums: dict, files: list[Path]) -> Path | None:
    """지금 뜨려는 스냅샷이 **최신 스냅샷과 내용이 같은가** — 같으면 그 매니페스트를 돌려준다.

    예전에는 비교가 없어서, 아무것도 바뀌지 않은 날 snapshot 을 한 번 더 부르면 같은 zip 이
    한 벌 더 구워졌다(실측: project_20260915_075622.zip 과 082157.zip 이 sha256 3d361f37…
    로 **바이트 단위 동일**, 112.9MB × 2). 백업이 둘이 되어도 복구력은 하나치인데 용량만 두 배다.

    같다고 말하려면 세 가지가 모두 맞아야 한다 — 하나라도 어긋나면 새로 굽는다.
      ① 체크섬 전체가 동일(파일 목록도, 내용도).
      ② 그 스냅샷의 zip 이 아직 있다.
      ③ 그 zip 이 **지금 담으려던 파일을 전부** 갖고 있다. ③이 없으면 어제 뜬 가벼운
        스냅샷(project 만) 때문에 오늘의 --with-images 가 조용히 생략된다 — 그 순간
        '이미지가 들어 있다고 믿는 백업' 이 하나도 없는 상태가 된다.
    """
    m = _latest_manifest()
    if not m:
        return None
    data = _load_json(m)
    recorded = data.get("files") or {}
    if len(recorded) != len(sums):
        return None
    for rel, meta in recorded.items():
        cur = sums.get(rel)
        if not cur or cur["sha256"] != meta.get("sha256"):
            return None
    stamp = m.stem.replace("manifest_", "")
    z = BACKUPS / (data.get("zip") or f"project_{stamp}.zip")
    if not z.is_file():
        return None
    try:
        with zipfile.ZipFile(z) as zf:
            packed = {i.filename for i in zf.infolist() if not i.is_dir()}
    except (OSError, zipfile.BadZipFile):
        return None
    want = {p.relative_to(ROOT).as_posix() for p in files}
    return m if want <= packed else None


def snapshot(now: datetime, *, with_images: bool = False, images_scope: str = "approved",
             dest: str | None = None, keep: int | None = None, keep_images: int | None = None,
             dry_run: bool = False, force: bool = False, include_private: bool = False,
             assume_yes: bool = False) -> int:
    private = _private_files()
    if include_private and private and dest and not dry_run:
        # 되돌릴 수 없는 방향의 동작이라 여기서만 한 번 묻는다. 확인되지 않으면 **백업을
        # 멈추는 대신** 사적 기록만 빼고 진행한다 — 예약 실행에서 확인이 불가능하다고
        # 백업 자체가 서 버리면, 조용한 실패 하나를 다른 조용한 실패로 바꾸는 것뿐이다.
        print(f"⚠ 개인 대화 기록 {len(private)}개를 외부 폴더로 복사하려 합니다: {dest}")
        if not _confirm("  인물과 나눈 사적 대화가 그 폴더(클라우드라면 제3자 서버)로 나갑니다.",
                        "포함", assume_yes):
            print("  → 사적 기록을 빼고 나머지만 백업합니다(작품·이미지는 그대로 담깁니다).")
            include_private = False
    files = _zip_payload(with_images, images_scope, include_private)
    total = sum(p.stat().st_size for p in files)
    sums = _checksums(include_private)
    same = None if force else _same_as_latest(sums, files)

    if dry_run:
        print("[미리보기] 스냅샷 예정")
        print(f"  zip 대상 {len(files)}개 파일 · 원본 합계 {_human(total)}")
        if with_images:
            print(f"  이미지 포함: {images_scope}")
        else:
            _warn_no_images("  ")
        if dest:
            print(f"  외부 사본: {dest}")
        if keep:
            print(f"  정리: 최신 {keep}개만 보존")
        _warn_private(private, include_private, dest)
        if same is not None:
            print(f"  ※ 바뀐 파일이 없습니다 — 새 zip 을 굽지 않고 기존 스냅샷"
                  f"({same.stem.replace('manifest_', '')})을 그대로 씁니다(--force 면 새로 굽습니다).")
        _warn_legacy()
        return 0

    if same is not None:
        return _report_same(same, dest, keep, keep_images, with_images, private, include_private)

    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(now)
    n = 2
    while (BACKUPS / f"manifest_{stamp}.json").exists():  # 같은 초 재실행 시 이전 스냅 보존
        stamp = f"{_stamp(now)}_{n}"
        n += 1

    print(f"백업 완료 [{stamp}]")
    zpath = BACKUPS / f"project_{stamp}.zip"
    count = 0
    if files:
        count = _write_zip(zpath, files)
        print(f"  project zip: {zpath.relative_to(ROOT).as_posix()} ({count}개 파일, {_human(zpath.stat().st_size)})")
        if with_images:
            n_img = sum(1 for p in files if p.relative_to(ROOT).parts[0] == "images")
            print(f"  이미지 원본 포함: {n_img}개 ({images_scope})")
    else:
        zpath = None
        print("  project/ 없음 — zip 생략(체크섬만 기록)")

    manifest = BACKUPS / f"manifest_{stamp}.json"
    atomic_write_json(manifest, {          # 원자적 — 쓰다 끊겨도 반쪽 매니페스트가 남지 않는다
        "created": stamp,
        "root": str(ROOT),
        "zip": zpath.name if zpath else "",
        "zip_files": count,
        "images_included": bool(with_images and zpath),
        "images_scope": images_scope if with_images else "",
        # 이 스냅샷이 사적 대화 기록을 담았는지 — 나중에 이 zip 을 어디로 옮겨도 되는지의 기준
        "private_included": bool(include_private and private),
        "private_skipped": 0 if include_private else len(private),
        "files": sums,
    })
    print(f"  체크섬 매니페스트: {manifest.relative_to(ROOT).as_posix()} ({len(sums)}개 파일)")
    if zpath:   # 사고가 났을 때 찾아 헤매지 않도록 되돌리는 명령을 지금 남겨 둔다
        print(f"  되돌리기: python tools/backup_project.py restore --snapshot {stamp} --dry-run"
              "   → 확인 후 --dry-run 없이 다시")

    if not with_images:
        _warn_no_images("  ")
    _warn_private(private, include_private, dest)
    _warn_legacy()

    if dest:
        rc = _copy_out(Path(dest), [p for p in (manifest, zpath) if p])
        if rc:
            return rc
    if keep:
        prune(keep, keep_images=keep_images, dry_run=False, assume_yes=True)
    return 0


def _report_same(manifest: Path, dest: str | None, keep: int | None,
                 keep_images: int | None, with_images: bool,
                 private: list[Path] | None = None, include_private: bool = False) -> int:
    """내용이 같아 새로 굽지 않았을 때 — **이미 있는 그 스냅샷**을 복구 지점으로 안내한다.

    '생략했다' 로 끝내면 사용자는 오늘의 백업이 없다고 믿는다. 있는 것을 이름으로 말하고,
    --dest 사본과 --keep 정리는 그대로 해 준다(외부 사본은 '오늘 그 폴더에 한 벌 있는가'
    의 문제라, 새로 구웠는지와 무관하게 사용자가 기대하는 결과다).
    """
    stamp = manifest.stem.replace("manifest_", "")
    data = _load_json(manifest)
    z = BACKUPS / (data.get("zip") or f"project_{stamp}.zip")
    print(f"백업 생략 — 마지막 스냅샷 이후 바뀐 파일이 없습니다. [{stamp}]")
    print(f"  같은 내용: {z.relative_to(ROOT).as_posix()} "
          f"({_human(z.stat().st_size)}, {data.get('zip_files', 0)}개 파일)"
          + (" · 이미지 포함" if data.get("images_included") else ""))
    print(f"  체크섬 매니페스트: {manifest.relative_to(ROOT).as_posix()} "
          f"({len(data.get('files') or {})}개 파일)")
    print(f"  되돌리기: python tools/backup_project.py restore --snapshot {stamp} --dry-run"
          "   → 확인 후 --dry-run 없이 다시")
    print("  같은 내용을 한 벌 더 굽고 싶다면: snapshot --force")
    if not with_images:
        _warn_no_images("  ")
    _warn_private(private or [], include_private, dest)
    _warn_legacy()
    if dest:
        rc = _copy_out(Path(dest), [p for p in (manifest, z) if p.exists()])
        if rc:
            return rc
    if keep:
        prune(keep, keep_images=keep_images, dry_run=False, assume_yes=True)
    return 0


def _copy_out(dest: Path, files: list[Path]) -> int:
    """외장드라이브·클라우드 동기화 폴더로 사본 — 같은 디스크 사고에 함께 죽지 않도록."""
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"  ✗ 외부 사본 실패 — 경로를 열 수 없습니다: {dest} ({e})")
        return 1
    for p in files:
        try:
            shutil.copy2(p, dest / p.name)
        except OSError as e:
            print(f"  ✗ 외부 사본 실패: {p.name} ({e})")
            return 1
    print(f"  외부 사본: {dest} ({len(files)}개 파일)")
    return 0


# ---------------------------------------------------------------- 목록·검증

def _manifests(base: Path | None = None) -> list[Path]:
    b = _base_dir(base)
    return sorted(b.glob("manifest_*.json")) if b.exists() else []


def _latest_manifest(base: Path | None = None) -> Path | None:
    ms = _manifests(base)
    return ms[-1] if ms else None


def _pick_manifest(stamp: str | None, base: Path | None = None) -> Path | None:
    if not stamp:
        return _latest_manifest(base)
    p = _base_dir(base) / f"manifest_{stamp}.json"
    return p if p.exists() else None


def verify(stamp: str | None = None, base: Path | None = None) -> int:
    m = _pick_manifest(stamp, base)
    if not m:
        if stamp:
            print(f"해당 스냅샷이 없습니다: {stamp}")
        else:
            print("검증할 백업이 없습니다. 먼저 snapshot 을 실행하세요.")
        return 1
    recorded = _load_json(m).get("files", {})
    # 현재 트리는 **사적 기록까지 포함해** 잰다. 매니페스트가 그것을 담고 있을 수도 있고
    # (--include-private), 안 담고 있으면 아래에서 '추가' 가 아니라 '대상 아님' 으로 분류한다.
    current = _checksums(include_private=True)
    changed, missing, added, untracked = [], [], [], []
    for rel, meta in recorded.items():
        if rel not in current:
            missing.append(rel)
        elif current[rel]["sha256"] != meta["sha256"]:
            changed.append(rel)
    for rel in current:
        if rel in recorded:
            continue
        (untracked if vn_core.is_private_rel(rel) else added).append(rel)

    print(f"무결성 검증 — 기준: {m.name}")
    print(f"  기록 {len(recorded)} · 현재 {len(current) - len(untracked)}")
    if untracked:
        print(f"  · 개인 대화 기록 {len(untracked)}개는 이 스냅샷의 대상이 아닙니다 "
              "(사적 대화 — --include-private 로만 담깁니다)")
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
    # 변경(비트로트·실수 저장)도 누락과 똑같이 restore 로 되돌린다 — zip 을 손으로 풀 필요 없다.
    stamp = m.stem.replace("manifest_", "")
    print(f"  되돌리려면: python tools/backup_project.py restore --snapshot {stamp} --dry-run"
          "   → 무엇이 바뀌는지 본 뒤 --dry-run 없이 다시 실행")
    print("  (복원 전 현재 상태는 backups/prerestore_*.zip 으로 자동 보관됩니다)")
    return 1


def list_backups(base: Path | None = None) -> int:
    b = _base_dir(base)
    ms = _manifests(base)
    if not ms:
        print("백업 없음.")
        return 0
    for m in ms:
        data = _load_json(m)
        stamp = m.stem.replace("manifest_", "")
        line = f"  {stamp} — {len(data.get('files', {}))}개 파일"
        z = b / (data.get("zip") or f"project_{stamp}.zip")
        if z.exists():
            line += f" · zip {_human(z.stat().st_size)}"
            if data.get("images_included"):
                line += f" · 이미지 포함({data.get('images_scope') or 'approved'})"
        else:
            line += " · zip 없음"
        print(line)
    saves = sorted(b.glob("prerestore_*.zip"))
    for s in saves:
        print(f"  [복원 전 보관] {s.name} · {_human(s.stat().st_size)}")

    # 목록만 보고 끝나지 않게 — 여기서 바로 쓸 수 있는 다음 명령을 붙인다.
    latest = ms[-1].stem.replace("manifest_", "")
    print()
    print("복원(수작업 압축 해제 불필요):")
    print(f"  python tools/backup_project.py restore --snapshot {latest} --dry-run   # 차이 먼저 확인")
    print(f"  python tools/backup_project.py restore --snapshot {latest}             # 되돌리기")
    # 경고의 기준은 '최신 스냅샷' 이다 — restore 가 기본으로 겨냥하는 바로 그것.
    # 옛날 스냅샷 하나에 이미지가 들어 있다고 해서 오늘의 복구가 되는 것은 아니다.
    with_img = [m for m in ms if _load_json(m).get("images_included")]
    if not _load_json(ms[-1]).get("images_included"):
        print()
        if not with_img:
            print("※ 어느 스냅샷에도 이미지 원본이 없습니다 — images/ 는 체크섬만 있어 "
                  "zip 으로 되돌릴 수 없습니다.")
        else:
            newest = with_img[-1].stem.replace("manifest_", "")
            print(f"※ 최신 스냅샷({latest})에는 이미지 원본이 없습니다 — 위의 restore 명령은 "
                  "장면 파일만 되돌립니다.")
            print(f"   이미지까지 들어 있는 가장 최근 스냅샷은 {newest} 입니다: "
                  f"python tools/backup_project.py restore --snapshot {newest}")
        print("   다음 백업부터: python tools/backup_project.py snapshot --with-images "
              "(외장 사본: --dest D:/backup)")
    return 0


# ---------------------------------------------------------------- restore

def _safe_member(name: str) -> Path | None:
    """zip slip 방지 — 절대경로·상위탈출·허용 밖 폴더는 복원하지 않는다.

    경로 성분 검증과 심볼릭 링크 재확인은 vn_core.safe_path 한 곳에서 하고(저장소 공통 규약),
    여기서는 '복원해도 되는 최상위 폴더인가'만 덧붙인다.
    """
    if not name or name.endswith("/"):
        return None
    try:
        target = safe_path(ROOT, name, allow_hidden=True)   # 백업본에는 .gitkeep 같은 숨김 파일도 있다
    except VNError:
        return None
    try:
        top = target.relative_to(ROOT).parts[0]
    except (ValueError, IndexError):
        return None
    return target if top in RESTORE_TOPS else None


def _pick_zip(stamp: str | None, base: Path | None = None) -> Path | None:
    b = _base_dir(base)
    if not b.exists():
        return None
    if stamp:
        p = b / f"project_{stamp}.zip"
        return p if p.exists() else None
    zs = sorted(b.glob("project_*.zip"))
    return zs[-1] if zs else None


def _restore_plan(zpath: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    """(덮어씀, 새로생성, 동일, 거부) — 복원 전 차이 미리보기."""
    over, new, same, rejected = [], [], [], []
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = _safe_member(info.filename)
            if target is None:
                rejected.append(info.filename)
                continue
            rel = info.filename
            if not target.exists():
                new.append(rel)
                continue
            with z.open(info) as fh:
                zsum = _sha256_fh(fh)
            if zsum == _sha256(target):
                same.append(rel)
            else:
                over.append(rel)
    return over, new, same, rejected


def _extras_after(zpath: Path) -> list[str]:
    """스냅샷에 없는 현재 파일 — 복원해도 지우지 않는다(있는 그대로 보고만)."""
    with zipfile.ZipFile(zpath) as z:
        inside = {i.filename for i in z.infolist() if not i.is_dir()}
    out = []
    for p in _project_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel not in inside:
            out.append(rel)
    return out


def _print_list(title: str, items: list[str], limit: int = 15) -> None:
    if not items:
        return
    print(f"  {title} {len(items)}건")
    for rel in items[:limit]:
        print(f"    - {rel}")
    if len(items) > limit:
        print(f"    ... 외 {len(items) - limit}건")


def restore(*, stamp: str | None = None, base: Path | None = None, dry_run: bool = False,
            assume_yes: bool = False, skip_backup: bool = False) -> int:
    zpath = _pick_zip(stamp, base)
    if not zpath:
        print("복원할 스냅샷 zip 이 없습니다. list 로 확인하세요.")
        return 1

    over, new, same, rejected = _restore_plan(zpath)
    extras = _extras_after(zpath)
    print(f"복원 미리보기 — {zpath.name}")
    print(f"  동일 {len(same)} · 덮어씀 {len(over)} · 새로 생성 {len(new)}")
    _print_list("✗ 덮어씀(현재 내용이 사라짐):", over)
    _print_list("+ 새로 생성:", new)
    _print_list("· 스냅샷에 없어 그대로 남는 현재 파일:", extras)
    if rejected:
        _print_list("! 안전하지 않은 경로 — 건너뜀:", rejected)
    if not (over or new):
        print("복원할 차이가 없습니다 — 현재 상태가 스냅샷과 같습니다.")
        return 0
    if dry_run:
        print("[미리보기] 실제로 바꾼 것은 없습니다. 실행하려면 --dry-run 없이 다시 실행하세요.")
        return 0

    if not _confirm(f"파일 {len(over) + len(new)}개를 스냅샷 상태로 되돌립니다(파괴적).", "복원", assume_yes):
        return 1

    if not skip_backup and over:
        rc, saved = _pre_restore_backup(over)
        if rc:
            print("되돌림용 백업에 실패해 복원을 중단했습니다. (--no-backup 으로 생략 가능)")
            return 1
        print(f"  복원 전 현재 상태 보관: {saved}")

    todo = set(over) | set(new)          # 동일한 파일은 건드리지 않는다(수정시각 보존)
    done = 0
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename not in todo:
                continue
            target = _safe_member(info.filename)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            done += 1
    print(f"복원 완료 — {done}개 파일을 {zpath.name} 기준으로 되돌렸습니다.")
    print("  확인: python tools/backup_project.py verify")
    return 0


def _pre_restore_backup(rels: list[str]) -> tuple[int, str]:
    """복원으로 사라질 현재 파일만 zip — 복원 자체를 되돌릴 수 있게 한다."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(datetime.now())
    zpath = BACKUPS / f"prerestore_{stamp}.zip"
    n = 2
    while zpath.exists():
        zpath = BACKUPS / f"prerestore_{stamp}_{n}.zip"
        n += 1
    try:
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in rels:
                p = ROOT / rel
                if p.is_file():
                    z.write(p, rel)
    except OSError as e:
        print(f"  ✗ 되돌림용 백업 실패: {e}")
        return 1, ""
    return 0, zpath.relative_to(ROOT).as_posix()


# ---------------------------------------------------------------- prune

def prune(keep: int, *, keep_images: int | None = None, base: Path | None = None,
          dry_run: bool = False, assume_yes: bool = False) -> int:
    """오래된 스냅샷 정리 — 이미지 든 스냅샷에는 **더 짧은 상한**을 따로 적용한다.

    상한이 하나뿐이던 시절의 기본값 12 는 '체크섬만 든 23KB zip' 기준이었다. 같은 12를
    이미지 든 스냅샷(실측 118.4MB)에 적용하면 backups/ 가 1.4GB 까지 자라는데, 그 열두 개가
    지키는 것은 대개 같은 앨범이다. 그래서 무거운 쪽만 KEEP_IMAGES_DEFAULT 로 센다.

    지우지 않는 두 개는 어떤 상한에서도 남는다 — **가장 최신 스냅샷**과 **이미지가 든 가장
    최신 스냅샷**. 앞은 restore 가 기본으로 겨냥하는 복구 지점이고, 뒤는 그림을 되돌릴 수
    있는 유일한 종류의 백업이다(기본 snapshot 은 체크섬만 담는다).
    """
    keep_images = KEEP_IMAGES_DEFAULT if keep_images is None else int(keep_images)
    if keep < 1 or keep_images < 1:
        print("보존 개수는 1 이상이어야 합니다.")
        return 1
    b = _base_dir(base)
    ms = _manifests(base)
    heavy = [m for m in ms if _load_json(m).get("images_included")]

    survivors = set(ms[max(0, len(ms) - keep):])
    for m in heavy[:max(0, len(heavy) - keep_images)]:
        survivors.discard(m)                 # 무거운 쪽은 더 짧게 센다
    if ms:                                   # 안전장치 — 이 둘은 상한과 무관하게 남는다
        survivors.add(ms[-1])
    if heavy:
        survivors.add(heavy[-1])
    old = [m for m in ms if m not in survivors]
    if not old:
        print(f"정리할 스냅샷 없음 — 현재 {len(ms)}개"
              f"(보존 상한 {keep} · 이미지 든 스냅샷 {keep_images}, 현재 {len(heavy)}개).")
        return 0

    victims: list[Path] = []
    for m in old:
        stamp = m.stem.replace("manifest_", "")
        victims.append(m)
        z = b / (_load_json(m).get("zip") or f"project_{stamp}.zip")
        if z.exists():
            victims.append(z)
    freed = sum(p.stat().st_size for p in victims if p.exists())

    n_heavy = sum(1 for m in old if _load_json(m).get("images_included"))
    print(f"오래된 스냅샷 {len(old)}개 정리 — 최신 {keep}개"
          f"(이미지 든 스냅샷은 최신 {keep_images}개) 보존, {_human(freed)} 회수")
    for m in old:
        img = " · 이미지 포함" if _load_json(m).get("images_included") else ""
        print(f"    - {m.stem.replace('manifest_', '')}{img}")
    if n_heavy:
        print(f"  ※ 그중 {n_heavy}개는 이미지 원본을 담고 있었습니다 — 지우면 그 시점의 "
              "그림은 이 폴더에서 되돌릴 수 없습니다(최신 이미지 스냅샷은 남습니다).")
    if dry_run:
        print("[미리보기] 삭제하지 않았습니다.")
        return 0
    if not _confirm("위 스냅샷을 삭제합니다.", "정리", assume_yes):
        return 1
    for p in victims:
        try:
            p.unlink()
        except OSError as e:
            print(f"  ✗ 삭제 실패: {p.name} ({e})")
    print(f"정리 완료 — {len(old)}개 스냅샷 삭제. 남은 {len(ms) - len(old)}개"
          f"(이미지 포함 {len(heavy) - n_heavy}개).")
    print("  ※ prerestore_*.zip(복원 전 보관본)은 건드리지 않습니다.")
    return 0


# ---------------------------------------------------------------- migrate

def migrate(*, dry_run: bool = False, assume_yes: bool = False, base: Path | None = None) -> int:
    """project/scenes_backup_* 를 backups/legacy/ 로 옮긴다.

    지우지 않고 '옮기기만' 한다 — 사본이 사라지는 것보다 자리를 옮기는 편이 안전하다.
    옮긴 뒤에는 project/ zip 이 가벼워지고 장면 폴더에 사본이 섞이지 않는다.
    """
    old = _legacy_scene_dirs()
    if not old:
        print("이관할 사본이 없습니다 — project/scenes_backup_* 가 깨끗합니다.")
        return 0
    dest_root = _base_dir(base) / "legacy"
    total = 0
    print(f"이관 대상 {len(old)}개 → {dest_root}")
    for d in old:
        n = sum(1 for p in d.rglob("*") if p.is_file())
        size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
        total += size
        print(f"    - project/{d.name}  ({n}개 파일, {_human(size)})")
    print(f"  합계 {_human(total)}")
    if dry_run:
        print("[미리보기] 아무것도 옮기지 않았습니다. 실행하려면 --dry-run 없이 다시 실행하세요.")
        return 0
    if not _confirm("위 폴더를 backups/legacy/ 로 옮깁니다(삭제는 하지 않습니다).", "이관", assume_yes):
        return 1

    dest_root.mkdir(parents=True, exist_ok=True)
    moved = 0
    for d in old:
        target = dest_root / d.name
        n = 2
        while target.exists():                     # 이름이 겹치면 덮지 않고 새 이름을 쓴다
            target = dest_root / f"{d.name}_{n}"
            n += 1
        try:
            shutil.move(str(d), str(target))
            moved += 1
            print(f"  옮김: project/{d.name} → {target.relative_to(ROOT).as_posix()}")
        except OSError as e:
            print(f"  ✗ 이관 실패: {d.name} ({e}) — 원본은 그대로 있습니다.")
    print(f"이관 완료 — {moved}/{len(old)}개.")
    if moved:
        print("  다음 스냅샷부터 project/ zip 이 가벼워집니다.")
    return 0 if moved == len(old) else 1


# ---------------------------------------------------------------- schedule (95)

PS_TEMPLATE = """# 자동 스냅샷 + 무결성 검증 — 작업 스케줄러가 주기 실행한다.
# 이 파일은 tools/backup_project.py schedule 이 생성했다. 등록은 사용자가 직접 한다.
$ErrorActionPreference = 'Continue'   # 파이썬 stderr 를 치명 오류로 보지 않도록

$py     = '__PY__'
$script = '__SCRIPT__'
$log    = '__LOG__'

# 로그 무한 성장 방지 — 1MB 넘으면 새로 시작
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) { Remove-Item $log -Force }

"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') 자동 백업 시작 ===" | Out-File -FilePath $log -Append -Encoding utf8
& $py $script snapshot __SNAPARGS__ 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
$rcSnap = $LASTEXITCODE
& $py $script verify 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
$rcVerify = $LASTEXITCODE
"=== 종료 snapshot=$rcSnap verify=$rcVerify ===" | Out-File -FilePath $log -Append -Encoding utf8

if ($rcSnap -ne 0 -or $rcVerify -ne 0) { exit 1 }
exit 0
"""


REG_TEMPLATE = """# 작업 스케줄러 등록 — 사용자가 직접 실행한다(이 스크립트는 등록만 하고 백업하지 않는다).
# 해제:  Unregister-ScheduledTask -TaskName '__TASK__' -Confirm:$false
$ErrorActionPreference = 'Stop'

$job = '__JOB__'
if (-not (Test-Path $job)) { throw "백업 스크립트가 없습니다: $job" }

$arg     = '-NoProfile -ExecutionPolicy Bypass -File "' + $job + '"'
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg
$trigger = __TRIGGER__
# 노트북 배터리 상태에서도 건너뛰지 않도록
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$desc = '비주얼노벨 작품 자동 스냅샷 + 무결성 검증'

Register-ScheduledTask -TaskName '__TASK__' -Action $action -Trigger $trigger -Settings $set -Description $desc -Force | Out-Null

Write-Host "등록 완료: __TASK__ (__WHEN__)"
Write-Host "즉시 시험 실행:  Start-ScheduledTask -TaskName '__TASK__'"
Write-Host "실행 기록:       __LOG__"
"""

_WEEKDAYS = {"SUN": "Sunday", "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
             "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday"}


def _psq(s: str) -> str:
    """PowerShell 작은따옴표 문자열용 이스케이프 — 경로에 ' 가 있어도 스크립트가 깨지지 않게."""
    return str(s).replace("'", "''")


def schedule(*, time_of_day: str = "21:00", freq: str = "DAILY", day: str = "SUN",
             keep: int = KEEP_DEFAULT, keep_images: int = KEEP_IMAGES_DEFAULT,
             with_images: bool = False, images_scope: str = "approved",
             include_private: bool = False,
             dest: str | None = None, task_name: str = TASK_NAME_DEFAULT,
             dry_run: bool = False, base: Path | None = None) -> int:
    hh, _, mm = time_of_day.partition(":")
    if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
        print(f"시각 형식이 잘못됐습니다: {time_of_day} (예: 21:00)")
        return 1
    time_of_day = f"{int(hh):02d}:{int(mm):02d}"
    day = day.upper()[:3]
    if freq == "WEEKLY" and day not in _WEEKDAYS:
        print(f"요일이 잘못됐습니다: {day} (SUN~SAT)")
        return 1
    if "'" in task_name:
        print("작업 이름에 작은따옴표는 쓸 수 없습니다.")
        return 1

    b = _base_dir(base)
    job = b / "auto_snapshot.ps1"
    reg = b / "register_task.ps1"
    log = b / "auto_snapshot_log.txt"

    snap_args = ["--keep", str(keep), "--keep-images", str(keep_images)]
    if with_images:
        snap_args += ["--with-images", "--images-scope", images_scope]
    if include_private:
        # 예약 실행은 비대화형이라 확인을 받을 수 없다 — 사용자가 등록 시점에 한 번 고른다.
        snap_args += ["--include-private", "--yes"]
    if dest:
        snap_args += ["--dest", f"'{_psq(dest)}'"]

    job_body = (PS_TEMPLATE
                .replace("__PY__", _psq(sys.executable))
                .replace("__SCRIPT__", _psq(ROOT / "tools" / "backup_project.py"))
                .replace("__LOG__", _psq(log))
                .replace("__SNAPARGS__", " ".join(snap_args)))

    if freq == "WEEKLY":
        trigger = f"New-ScheduledTaskTrigger -Weekly -DaysOfWeek {_WEEKDAYS[day]} -At '{time_of_day}'"
        when = f"매주 {_WEEKDAYS[day]} {time_of_day}"
    else:
        trigger = f"New-ScheduledTaskTrigger -Daily -At '{time_of_day}'"
        when = f"매일 {time_of_day}"

    reg_body = (REG_TEMPLATE
                .replace("__JOB__", _psq(job))
                .replace("__TRIGGER__", trigger)
                .replace("__TASK__", task_name)
                .replace("__WHEN__", when)
                .replace("__LOG__", _psq(log)))

    if dry_run:
        print(f"[미리보기] 파일을 만들지 않았습니다: {job.name}, {reg.name}")
    else:
        b.mkdir(parents=True, exist_ok=True)
        # PowerShell 5.1 은 BOM 없는 .ps1 을 ANSI 로 읽어 한글이 깨진다
        job.write_text(job_body, encoding="utf-8-sig")
        reg.write_text(reg_body, encoding="utf-8-sig")
        print("스케줄 스크립트 생성")
        print(f"  백업 작업: {job}")
        print(f"  등록 스크립트: {reg}")

    print()
    print(f"예약 내용: {when} — snapshot({' '.join(snap_args)}) + verify")
    print("등록은 자동으로 하지 않습니다. 아래 중 하나를 직접 실행하세요.")
    print(f'  powershell -NoProfile -ExecutionPolicy Bypass -File "{reg}"')
    print("  (cmd 에서 등록하려면)")
    sched = f"/SC {freq}" + (f" /D {day}" if freq == "WEEKLY" else "")
    print(f'  schtasks /Create /TN "{task_name}" {sched} /ST {time_of_day} '
          f'/TR "powershell -NoProfile -ExecutionPolicy Bypass -File \\"{job}\\"" /F')
    print()
    print("확인 · 해제:")
    print(f"  Start-ScheduledTask      -TaskName '{task_name}'   # 즉시 1회 실행해 동작 확인")
    print(f"  Get-ScheduledTaskInfo    -TaskName '{task_name}'   # 마지막 실행 결과")
    print(f"  Unregister-ScheduledTask -TaskName '{task_name}' -Confirm:$false")
    print()
    print(f"실행 기록: {log}")
    print("  · PC 가 켜져 있는 시각으로 잡으세요(꺼져 있으면 다음 로그온 때 밀려서 실행됩니다).")
    print("  · 이미지 원본까지 지키려면 --with-images, 외장드라이브 사본은 --dest 를 함께 주세요.")
    print("  · 개인 대화 기록은 예약 백업에서도 기본 제외입니다"
          + (" — 지금은 --include-private 로 담도록 등록됩니다." if include_private
             else " (담으려면 schedule --include-private)."))
    return 0


# ---------------------------------------------------------------- CLI

EPILOG = """자주 쓰는 두 가지

  [복구] 파일이 사라졌거나 잘못 저장했을 때 — zip 을 손으로 풀 필요 없습니다.
    python tools/backup_project.py list                            어떤 스냅샷이 있나
    python tools/backup_project.py restore --dry-run               무엇이 바뀌는지 먼저
    python tools/backup_project.py restore --snapshot <스탬프>       되돌리기
    python tools/backup_project.py verify                          되돌린 결과 대조
    복원 전 현재 상태는 backups/prerestore_*.zip 으로 자동 보관됩니다(--no-backup 으로 생략).

  [이미지 원본] 기본 백업에는 체크섬만 들어갑니다. 승인 이미지는 유료 생성물이자 유일본입니다.
    python tools/backup_project.py snapshot --with-images          zip 에 원본까지
    python tools/backup_project.py snapshot --with-images --dest D:/backup   외장드라이브 사본

  [개인 대화 기록] chatlog.json · talk_*.json · *.archive.jsonl · memory_*.json 은 기본 제외입니다
    (zip 에도 체크섬 매니페스트에도 안 들어갑니다 — --dest 가 클라우드 폴더일 수 있으므로).
    python tools/backup_project.py snapshot --include-private      정말 담아야 할 때만
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="백업 + sha256 무결성 + 복원", epilog=EPILOG,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("snapshot", help="백업 + 체크섬 스냅 (이미지 원본은 --with-images 로)")
    sp.add_argument("--with-images", action="store_true",
                    help="이미지 원본도 zip 에 포함 — 없으면 체크섬만 남아 되돌릴 수 없습니다")
    sp.add_argument("--images-scope", default="approved", choices=["approved", "all"],
                    help="approved=승인 장면이 쓰는 이미지만(기본), all=images/ 전체")
    sp.add_argument("--dest", help="외장드라이브·클라우드 폴더에 사본 복사")
    sp.add_argument("--keep", type=int, help="스냅 후 최신 N개만 보존")
    sp.add_argument("--keep-images", type=int, default=None,
                    help=f"--keep 와 함께: 이미지 든 스냅샷은 최신 N개만 (기본 {KEEP_IMAGES_DEFAULT})")
    sp.add_argument("--force", action="store_true",
                    help="바뀐 파일이 없어도 zip 을 새로 굽는다(기본은 기존 스냅샷을 안내하고 생략)")
    sp.add_argument("--include-private", action="store_true",
                    help="개인 대화 기록(chatlog·talk_*·*.archive.jsonl·memory_*)까지 담는다 "
                         "— 기본은 제외. --dest 와 함께 쓰면 확인을 묻는다")
    sp.add_argument("--yes", action="store_true",
                    help="--include-private 와 --dest 를 함께 줬을 때의 확인을 생략")
    sp.add_argument("--dry-run", action="store_true", help="쓰지 않고 계획만 표시")

    vp = sub.add_parser("verify", help="스냅과 현재 파일 대조 (이상이 있으면 restore 를 안내)")
    vp.add_argument("--snapshot", help="기준 스냅샷 스탬프(기본: 최신)")
    vp.add_argument("--from", dest="src", help="백업 폴더(기본: backups/)")

    lp = sub.add_parser("list", help="백업 목록 + 바로 쓸 restore 명령")
    lp.add_argument("--from", dest="src", help="백업 폴더(기본: backups/)")

    rp = sub.add_parser("restore", help="스냅샷 zip 복원(파괴적) — 소실·오저장의 정식 복구 경로",
                        description="스냅샷 상태로 되돌린다. 먼저 --dry-run 으로 차이를 보고, "
                                    "실행하면 복원 전 현재 상태를 자동 보관한다.")
    rp.add_argument("--snapshot", help="복원할 스탬프(기본: 최신)")
    rp.add_argument("--from", dest="src", help="백업 폴더(기본: backups/)")
    rp.add_argument("--dry-run", action="store_true", help="차이만 미리보기")
    rp.add_argument("--yes", action="store_true", help="확인 절차 생략")
    rp.add_argument("--no-backup", action="store_true", help="복원 전 현재 상태 보관 생략")

    mg = sub.add_parser("migrate", help="project/scenes_backup_* 를 backups/legacy/ 로 이관")
    mg.add_argument("--from", dest="src", help="백업 폴더(기본: backups/)")
    mg.add_argument("--dry-run", action="store_true", help="옮기지 않고 대상만 표시")
    mg.add_argument("--yes", action="store_true", help="확인 절차 생략")

    pp = sub.add_parser("prune", help="오래된 스냅샷 정리")
    pp.add_argument("--keep", type=int, default=KEEP_DEFAULT, help=f"보존 개수(기본 {KEEP_DEFAULT})")
    pp.add_argument("--keep-images", type=int, default=KEEP_IMAGES_DEFAULT,
                    help=f"이미지 든 스냅샷 보존 개수(기본 {KEEP_IMAGES_DEFAULT}) — 한 장이 수백 MB 다")
    pp.add_argument("--from", dest="src", help="백업 폴더(기본: backups/)")
    pp.add_argument("--dry-run", action="store_true")
    pp.add_argument("--yes", action="store_true")

    cp = sub.add_parser("schedule", help="주기 자동 백업 스크립트·등록 명령 안내")
    cp.add_argument("--time", default="21:00", help="실행 시각 HH:MM(기본 21:00)")
    cp.add_argument("--freq", default="DAILY", choices=["DAILY", "WEEKLY"])
    cp.add_argument("--day", default="SUN", help="WEEKLY 일 때 요일(SUN~SAT)")
    cp.add_argument("--keep", type=int, default=KEEP_DEFAULT)
    cp.add_argument("--keep-images", type=int, default=KEEP_IMAGES_DEFAULT)
    cp.add_argument("--include-private", action="store_true",
                    help="예약 백업에 개인 대화 기록까지 담는다(기본 제외 — 확인 없이 돕니다)")
    cp.add_argument("--with-images", action="store_true")
    cp.add_argument("--images-scope", default="approved", choices=["approved", "all"])
    cp.add_argument("--dest", help="외부 사본 폴더")
    cp.add_argument("--name", default=TASK_NAME_DEFAULT, help="작업 이름")
    cp.add_argument("--dry-run", action="store_true", help="스크립트를 만들지 않고 안내만")

    args = ap.parse_args()
    src = Path(args.src) if getattr(args, "src", None) else None

    if args.cmd == "snapshot":
        return snapshot(datetime.now(), with_images=args.with_images,
                        images_scope=args.images_scope, dest=args.dest,
                        keep=args.keep, keep_images=args.keep_images,
                        dry_run=args.dry_run, force=args.force,
                        include_private=args.include_private, assume_yes=args.yes)
    if args.cmd == "verify":
        return verify(args.snapshot, src)
    if args.cmd == "list":
        return list_backups(src)
    if args.cmd == "restore":
        return restore(stamp=args.snapshot, base=src, dry_run=args.dry_run,
                       assume_yes=args.yes, skip_backup=args.no_backup)
    if args.cmd == "migrate":
        return migrate(dry_run=args.dry_run, assume_yes=args.yes, base=src)
    if args.cmd == "prune":
        return prune(args.keep, keep_images=args.keep_images, base=src,
                     dry_run=args.dry_run, assume_yes=args.yes)
    return schedule(time_of_day=args.time, freq=args.freq, day=args.day, keep=args.keep,
                    keep_images=args.keep_images, include_private=args.include_private,
                    with_images=args.with_images, images_scope=args.images_scope,
                    dest=args.dest, task_name=args.name, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
