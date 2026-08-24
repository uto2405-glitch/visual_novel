#!/usr/bin/env python3
"""저장소 공용 기반 — 경로·JSON·원자적 쓰기·경로 안전·오류 타입의 단일 출처.

지금까지 도구마다 복제돼 있던 것들(콘솔 방어 12벌, 경로 상수 14벌, JSON 로더 9종,
원자적 쓰기 4벌, 경로 탈출 방어 3벌)을 여기 하나로 모은다. 각 도구는 자기 파일에서
같은 코드를 다시 쓰지 말고 이 모듈을 import 한다.

여기 있는 것은 세 가지다.
  1. 기반: 경로 상수·JSON 읽기·원자적 쓰기·경로 안전·오류 타입.
  2. **저장소 계층**: 장면 파일 읽기/쓰기(scene_path·load_dict·scene_files·iter_scenes·
     all_scenes)와 검사기 실행(run_checker). 예전에는 advance_scene(CLI)에 있었고, 그래서
     위층인 scene_ops 가 CLI 를 import 하고 CLI 가 다시 scene_ops 를 지연 import 하는
     **순환**이 있었다.
  3. **여러 층이 공유하는 도메인 규칙**: ending_of·norm_episode·last_episode·크롭 집합과
     "감상본·인화에 실릴 컷"의 정의(selected_of·is_deliverable).
     같은 규칙이 두세 벌로 갈리면 화면마다 다른 답이 나온다(엔딩 이름·화 번호가 실제로 갈렸고,
     완성 컷 판정은 여덟 개 도구에 흩어져 있었다).

설계 규약(어기면 순환 import 로 서버가 죽는다):
  * **다른 tools 모듈을 import 하지 않는다.** 표준 라이브러리만 쓴다.
  * 의존 방향은 한 방향뿐: vn_core ← scene_ops ← advance_scene(CLI)·vn_compose·webapp.

오류 규약:
  * 사용자에게 보여줄 오류는 :class:`VNError`(RuntimeError 파생)로 던진다.
  * **라이브러리 코드는 sys.exit()/SystemExit 를 쓰지 않는다** — 웹 스튜디오는 요청
    스레드에서 이 코드를 부르므로 프로세스 종료는 서버를 통째로 위험하게 만든다.
    종료 코드 변환은 각 도구의 main() 이 VNError 를 잡아서 한다.

Python 3.9+ · 외부 패키지 없음.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 경로 상수
# 저장소 안의 위치를 계산하는 유일한 출처. 도구가 각자 ROOT 를 다시 만들지 않는다.
ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
PROJECT = ROOT / "project"
SCENES = PROJECT / "scenes"
MANIFEST = PROJECT / "manifest.json"
STORY = PROJECT / "story"
IMAGES = ROOT / "images"
IMAGES_RAW = IMAGES / "raw"
OUTPUT = ROOT / "output"
LOGS = ROOT / "logs"
BACKUPS = ROOT / "backups"
TEMPLATES = ROOT / "templates"
SCENE_TEMPLATE = TEMPLATES / "scene.json"
CHECKER = TOOLS / "check_protocol.py"

# 장면 ID 형식 — 경로 탈출 차단과 order 무결성의 첫 관문(웹·CLI 공통).
SCENE_ID_RE = re.compile(r"^SCENE-\d{3,}$")

# 후보 이미지로 허용하는 확장자 — check_protocol A3 가 검사하는 집합과 같아야 한다.
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"})

# 작품 화풍 기본값 — manifest.output.visual_style 이 없을 때만 쓴다.
# (프롬프트 조립 경로마다 문구가 갈리면 컷 사이 화풍이 흔들린다. 문자열 출처는 여기 하나.)
DEFAULT_VISUAL_STYLE = ("bright cel-shaded Korean romance webtoon, soft warm palette, "
                        "clean line art")

# 인화 크롭 규약 — 자르기 방식(print_export)과 입력 검증(webapp·scene_ops)이 같은 집합을 봐야 한다.
# 두 벌로 갈리면 UI 에서 고른 값이 저장은 되고 출력에서만 조용히 무시된다.
CROP_MODES = ("cover", "fit")
CROP_ANCHORS = ("center", "top", "bottom", "left", "right")

# 저장소 전역 단일 쓰기 잠금 — 장면 JSON 의 read-modify-write 를 직렬화한다.
# 웹 스튜디오는 스레드 서버라 폰과 PC 에서 동시에 눌러도 이 잠금 하나로 순서가 정해진다.
# (RLock: 같은 스레드에서 select→register 처럼 겹쳐 잡는 경로가 있다.)
WRITE_LOCK = threading.RLock()


class VNError(RuntimeError):
    """사용자에게 그대로 보여줄 수 있는 오류.

    RuntimeError 를 상속하므로 기존의 ``except RuntimeError`` 경로(웹 핸들러 400 변환,
    CLI 의 승인 실패 처리)가 그대로 잡는다 — 하위호환을 깨지 않는다.
    """


# ---------------------------------------------------------------- 콘솔
_CONSOLE_GUARDED = False


def console_guard() -> None:
    """비 UTF-8 콘솔(cp437·cp949 등)에서 한글 출력이 크래시하지 않게 한다.

    여러 번 불러도 안전하다(첫 호출 이후에는 아무 일도 하지 않는다).
    """
    global _CONSOLE_GUARDED
    if _CONSOLE_GUARDED:
        return
    _CONSOLE_GUARDED = True
    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            if enc not in ("utf-8", "utf8"):
                stream.reconfigure(errors="replace")   # type: ignore[union-attr]
        except Exception:
            pass          # 파이프·pythonw 등 reconfigure 가 없는 스트림은 그냥 둔다


console_guard()   # import 만으로도 보호된다(도구가 호출을 잊어도 한글이 깨지지 않게)


def _rel(path: Path) -> str:
    """오류 메시지용 짧은 경로 — 저장소 밖이면 절대경로 그대로."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return str(path)


# ---------------------------------------------------------------- JSON 읽기
def load_json(path: Path | str) -> Any:
    """JSON 을 읽어 그대로 돌려준다(엄격). 실패는 VNError 로 전파한다.

    설정·장면처럼 "없으면 진행할 수 없는" 파일에 쓴다. 조용히 넘어가면 안 되는 자리다.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise VNError(f"파일 없음: {_rel(p)}") from exc
    except (OSError, ValueError) as exc:      # 권한·인코딩 오류
        raise VNError(f"{_rel(p)} 읽기 실패: {exc}") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise VNError(f"{p.name} 파싱 실패: {exc}") from exc


def load_json_safe(path: Path | str, default: Any = None) -> Any:
    """JSON 을 읽되 실패하면 default(관대). 파일 하나가 화면 전체를 죽이지 못하게 한다.

    default 를 준 경우에는 **형(型)까지 확인**한다 — 기대한 형이 아니면(예: dict 를
    기대했는데 배열이 든 파일) default 를 돌려준다. 호출부의 ``or {}`` 관용구보다 안전하다.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    if default is not None and not isinstance(data, type(default)):
        return default
    return data


def load_manifest() -> dict:
    """project/manifest.json — 없거나 손상이면 빈 dict. (UI·프롬프트 조립의 공통 입구)"""
    return load_json_safe(MANIFEST, {})


# ---------------------------------------------------------------- 원자적 쓰기
def _atomic(path: Path | str, writer) -> None:
    """임시 파일에 다 쓰고 flush+fsync 한 뒤 os.replace 로 교체한다.

    저장 도중 강제 종료·정전이 나도 원본이 반쯤 잘리지 않는다(교체는 원자적).
    임시 파일명에 pid·스레드 id 를 넣어 동시 저장끼리 서로의 임시 파일을 덮지 않게 한다.
    """
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise VNError(f"{_rel(p)} 저장 폴더를 만들 수 없습니다: {exc}") from exc
    tmp = p.with_name(f"{p.name}.{os.getpid():x}{threading.get_ident():x}.tmp")
    try:
        with open(tmp, "wb") as fh:
            writer(fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    _atomic(path, lambda fh: fh.write(data))


def atomic_write_text(path: Path | str, text: str) -> None:
    _atomic(path, lambda fh: fh.write(str(text).encode("utf-8")))


def atomic_write_json(path: Path | str, obj: Any) -> None:
    """사람이 읽고 git diff 로 볼 수 있게 들여쓰기 2·한글 그대로·끝에 개행."""
    body = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, body)


# ---------------------------------------------------------------- 도메인 값
def visual_style(mf: dict | None = None, sc: dict | None = None) -> str:
    """작품 화풍 문구 — manifest.output.visual_style → 장면 visual_style → 기본 문구.

    mf 를 주지 않으면 매니페스트를 읽는다. 장면 오버라이드까지 다루는 이 순서가
    전 저장소의 단일 규약이다(프롬프트 조립·장면 구성·웹 생성이 모두 같은 답을 낸다).
    """
    if mf is None:
        mf = load_manifest()
    out = mf.get("output") if isinstance(mf, dict) else None
    v = str((out or {}).get("visual_style", "") or "").strip() if isinstance(out, dict) else ""
    if not v and isinstance(sc, dict):
        v = str(sc.get("visual_style", "") or "").strip()
    return v or DEFAULT_VISUAL_STYLE


def is_scene_id(sid: Any) -> bool:
    """SCENE-001 형식인지. 파일 접근 전에 반드시 통과시켜야 하는 관문."""
    return isinstance(sid, str) and bool(SCENE_ID_RE.match(sid))


def ending_of(sc: Any) -> tuple[bool, str]:
    """엔딩 표기를 하나로 정규화한다 → (엔딩인가, 엔딩 이름).

    규약은 ``ending: true`` + 선택적 ``ending_label: "호감 엔딩"`` 이다.
    예전 데이터의 ``ending: "호감 엔딩"``(문자열)도 그대로 받아 label 로 옮긴다.

    감상본(export_viewer)·장면 구성(vn_compose)·스튜디오 목록(/api/state)이 **이 함수 하나**를
    써야 같은 장면의 엔딩 이름이 화면마다 달라지지 않는다.
    """
    if not isinstance(sc, dict):
        return False, ""
    raw = sc.get("ending")
    label = str(sc.get("ending_label") or "").strip()
    if isinstance(raw, str):
        return bool(raw.strip()), (label or raw.strip())
    return bool(raw), label


def norm_episode(v: Any):
    """화 번호는 **양의 정수만** — 그 밖의 값은 None(화를 쓰지 않는 작품).

    감상본의 화 선택, 장면 편집(scene_ops), 장면 구성이 같은 답을 내야 화 하나가
    통째로 빠지는 사고가 없다. bool 은 int 지만 화 번호가 아니므로 먼저 걸러낸다.
    """
    if isinstance(v, bool):
        return None
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


# ---------------------------------------------------------------- 저장소 계층
def scene_path(sid: str) -> Path:
    """장면 파일 경로. 형식 검증(is_scene_id)은 부르는 쪽 몫이다 — 외부 입력은 반드시 먼저 거른다."""
    return SCENES / f"{sid}.json"


def load_dict(path: Path | str) -> dict:
    """JSON 을 읽어 dict 로 돌려준다. 최상위가 객체가 아니면 VNError.

    장면·매니페스트처럼 "객체가 아니면 이후 코드가 전부 KeyError"인 파일의 입구다.
    """
    data = load_json(path)
    if not isinstance(data, dict):
        raise VNError(f"{Path(path).name}: JSON 최상위가 객체({{...}})가 아닙니다. 파일을 확인하세요.")
    return data


def scene_files() -> list[Path]:
    """project/scenes/ 의 장면 파일 경로(파일명 순). 폴더가 없으면 빈 목록.

    glob 패턴과 "폴더가 아직 없을 수 있다"는 방어를 여기 한 줄에 둔다. 예전에는 여덟 개
    도구가 각자 ``sorted(SCENES.glob("SCENE-*.json")) if SCENES.exists() else []`` 를 썼다 —
    한 곳이라도 exists 검사를 빠뜨리면 첫 실행(장면 폴더가 아직 없는 새 프로젝트)에서
    그 화면만 예외로 죽는다.

    파일 목록이 필요한 쪽(손상 파일을 **보고해야 하는** doctor 등)은 이것을 쓰고,
    내용까지 필요한 쪽은 :func:`iter_scenes` 를 쓴다.
    """
    if not SCENES.exists():
        return []
    return sorted(SCENES.glob("SCENE-*.json"))


def iter_scenes(strict: bool = False) -> list[tuple[Path, dict]]:
    """모든 장면을 ``(파일 경로, 장면 dict)`` 로 (파일명 순).

    **한 곳에 있어야 하는 이유**: 장면을 훑는 코드는 세 가지를 매번 함께 결정해야 한다 —
    (1) 정렬 순서, (2) 손상된 파일을 만났을 때의 태도, (3) 최상위가 객체가 아닌 파일 처리.
    이 셋이 도구마다 갈리면 같은 프로젝트가 화면마다 다른 개수로 보인다(감상본에는 나오는데
    인화 목록에는 없는 컷). 그래서 훑기는 이 함수 하나만 쓴다.

    strict=False(기본): 읽기·파싱 실패와 "객체가 아닌 JSON"은 **건너뛴다**. 손상 파일 하나가
        감상본·인화·백업·진단 전체를 죽이지 않게 하려는 관대한 경로다.
    strict=True: 손상 파일에서 VNError. 장면 번호·순서를 계산하거나 전수 검증하는 쪽처럼
        "조용히 빠지면 안 되는" 자리에서 쓴다.

    경로를 함께 돌려주는 이유: 오류 메시지와 파일명↔scene_id 대조에 원본 경로가 필요하다.
    """
    out: list[tuple[Path, dict]] = []
    for f in scene_files():
        if strict:
            out.append((f, load_dict(f)))
            continue
        sc = load_json_safe(f, {})      # 형까지 확인 — 배열이 든 파일도 여기서 걸러진다
        if sc:
            out.append((f, sc))
    return out


def all_scenes() -> list[dict]:
    """project/scenes/ 의 모든 장면(파일명 순). 깨진 파일은 VNError 로 즉시 드러낸다."""
    return [sc for _f, sc in iter_scenes(strict=True)]


def selected_of(sc: Any) -> str:
    """이 장면이 실제로 쓰는 이미지의 저장소 상대경로(없으면 "").

    ``assets`` 가 없거나 dict 가 아니거나 값이 None 인 낡은/손상 장면에서도 예외 없이 "" 다.
    여덟 개 도구가 각자 ``sc.get("assets", {}).get("selected_image")`` 를 쓰면서 방어 수준이
    조금씩 달랐다 — 어떤 곳은 strip 을 안 해 공백 한 칸짜리 경로를 '이미지 있음'으로 셌다.
    """
    assets = sc.get("assets") if isinstance(sc, dict) else None
    if not isinstance(assets, dict):
        return ""
    return str(assets.get("selected_image") or "").strip()


def is_deliverable(sc: Any, include_all: bool = False) -> bool:
    """감상본·인화에 실릴 컷인가.

    **"완성된 컷"의 정의는 이 저장소에 하나만 있어야 한다.** 예전에는 export_viewer·
    print_export·print_preflight·prompt_build·makefun_client·webapp·doctor·backup_project 가
    같은 판정을 각자 썼고, 조건 하나만 어긋나도 "감상본에는 있는데 인화 목록에는 없는 컷"이
    생겼다. 판정을 바꿀 일이 생기면 **여기만** 고친다(호출부에 다시 흩뜨리지 말 것).

    기본: ``status == "APPROVED"`` 이고 선택 이미지가 있는 장면 — 사람 승인 게이트를
        통과한 것만 완성본 자리에 놓는다.
    include_all=True: 상태를 보지 않고 선택 이미지만 본다(도구들의 ``--all`` 옵션).
        단일 장면을 지정한 경우(``--scene SCENE-007``)도 사용자가 그 컷을 명시적으로
        고른 것이므로 호출부에서 ``include_all=include_all or bool(scene_filter)`` 로 넘긴다.
    """
    if not selected_of(sc):
        return False
    return bool(include_all) or (isinstance(sc, dict) and sc.get("status") == "APPROVED")


def run_checker(sid: str | None = None) -> tuple[int, str]:
    """프로토콜 검사기를 별도 프로세스로 돌린다 → (종료코드, 출력 전문).

    별도 프로세스인 이유: 검사기는 도구가 고칠 수 없는 판정자다. 같은 프로세스에서
    import 하면 도구 쪽 전역 상태(경로·캐시)가 판정에 섞일 수 있다.
    """
    cmd = [sys.executable, str(CHECKER)]
    if sid:
        cmd += ["--scene", sid]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr)


def last_episode():
    """가장 뒤 순서 장면의 화 번호(없으면 None) — 새로 만드는 장면이 이어받을 값.

    이 승계가 없으면 지금 있는 장면들에만 episode 가 있고 앞으로 만드는 장면에는
    영영 붙지 않아, 감상본의 화 선택에서 새 장면이 통째로 빠진다.
    깨진 장면 파일 하나가 새 장면 생성을 막지 않도록 여기서는 관대하게 읽는다.
    """
    best_order, ep = None, None
    for _f, sc in iter_scenes():          # 관대 적재 — 손상 파일은 건너뛴다
        e = norm_episode(sc.get("episode"))
        if e is None:
            continue
        try:
            order = int(sc.get("scene_order"))
        except (TypeError, ValueError):
            order = 0
        if best_order is None or order >= best_order:
            best_order, ep = order, e
    return ep


# ---------------------------------------------------------------- 경로 안전
def safe_path(base: Path | str, rel: str, *, allow_hidden: bool = False) -> Path:
    """``base`` 아래로만 해석되는 경로를 돌려준다. 벗어나면 VNError.

    막는 것: 절대경로('/etc/x'), 상위 탈출('../'), 드라이브 문자('C:'), 숨김 항목('.git'),
    그리고 심볼릭 링크로 밖을 가리키는 경우(resolve 후 재확인).
    쓰는 곳: /img·/dl 라우트, 백업 zip 복원(zip slip), 인화 출력 경로.

    allow_hidden=True 는 숨김 항목까지 허용한다(내부 캐시를 다루는 경로 전용).
    """
    base_r = Path(base).resolve()
    text = str(rel or "").replace("\\", "/")
    if text.startswith("/"):
        # 절대경로·UNC('//server/share')는 base 아래로 억지 해석하지 않고 그냥 거부한다.
        raise VNError("절대경로는 사용할 수 없습니다.")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts:
        raise VNError("경로가 비어 있습니다.")
    for p in parts:
        if p == ".." or ":" in p:
            raise VNError(f"허용되지 않는 경로 성분: {p!r}")
        if not allow_hidden and p.startswith("."):
            raise VNError(f"숨김 항목에는 접근할 수 없습니다: {p!r}")
    target = (base_r / "/".join(parts)).resolve()
    if target != base_r and not target.is_relative_to(base_r):
        raise VNError("기준 폴더 밖의 경로입니다.")
    return target


def safe_slug(s: Any, default: str = "", maxlen: int = 120) -> str:
    """파일명에 써도 안전한 문자열 — 영숫자(한글 포함)·하이픈·언더스코어만 남긴다.

    점을 모두 버리므로 '..' 같은 입력은 자연히 빈 문자열이 되고 default 로 떨어진다.
    (파일명 한 조각을 만드는 용도다. 경로 조립에는 safe_path 를 쓴다.)
    """
    out = "".join(c for c in str(s or "") if c.isalnum() or c in "-_")[:maxlen]
    return out or default
