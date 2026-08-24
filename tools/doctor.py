#!/usr/bin/env python3
"""환경 종합 점검 — "왜 안 되지?" 를 30초 안에 좁혀준다.

파이썬·의존성·환경변수·로컬 LLM·디스크·프로젝트 구조·백업·비밀값을 한 번에 훑고, 항목마다
무엇을 하면 되는지 한국어로 알려준다. **읽기 전용** — 어떤 파일도 만들거나 고치지 않고,
과금되는 이미지 생성 API 는 호출하지 않는다(토큰이 있는지 여부만 본다).

판정은 다른 도구에 위임한다(중복 구현 금지): 연출 리듬·분기는 scene_lint, 비밀값은 secret_scan,
프로토콜 준수는 check_protocol. doctor 는 그 결과를 한 화면에 모아 보여준다.

사용법:
  python tools/doctor.py            # 전체 점검
  python tools/doctor.py --json     # 기계 판독용

종료코드: 0 = 치명 문제 없음(경고는 있을 수 있음) / 1 = 고쳐야 할 문제 있음
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import shutil
import sys
import urllib.parse
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:          # 도구 모듈(vn_core·secret_scan·scene_lint)을 직접 부르기 위해
    sys.path.insert(0, str(_HERE))

import vn_core                       # noqa: E402
from vn_core import load_json_safe   # noqa: E402  (import 만으로 콘솔 인코딩 방어가 걸린다)

ROOT = _HERE.parent                  # vn_core 규약과 같은 값 — 복제본에서도 자기 트리를 본다
TOOLS = _HERE
MANIFEST = ROOT / "project" / "manifest.json"
SCENES = ROOT / "project" / "scenes"

OK, WARN, ERR = "OK", "경고", "문제"
_results: list = []


def add(section: str, name: str, level: str, detail: str, fix: str = "") -> None:
    _results.append({"section": section, "name": name, "level": level,
                     "detail": detail, "fix": fix})


# ------------------------------------------------------------------ 1. 실행 환경
def check_python() -> None:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (3, 9):
        add("실행 환경", "파이썬 버전", OK, f"{ver} ({sys.executable})")
    else:
        add("실행 환경", "파이썬 버전", ERR, f"{ver} — 3.9 이상이 필요합니다",
            "python.org 에서 3.9+ 를 설치한 뒤 다시 실행하세요.")


def check_pillow() -> None:
    try:
        from PIL import Image  # noqa: F401
        try:
            from PIL import __version__ as pv
        except ImportError:
            pv = getattr(Image, "__version__", "?")
        add("실행 환경", "Pillow(인화·감상본 최적화)", OK, f"설치됨 {pv}")
    except ImportError:
        add("실행 환경", "Pillow(인화·감상본 최적화)", WARN,
            "없음 — 감상·검사·생성은 그대로 되지만 인화 마스터 굽기(print_export)는 막힙니다",
            "python -m pip install Pillow")


# 없으면 파이프라인이 멈추는 파일. vn_core(공용 기반)·scene_ops(상태 전이)는 다른 도구가 의존한다.
NEED_TOOLS = ["webapp.py", "studio.html", "vn_core.py", "scene_ops.py", "advance_scene.py",
              "check_protocol.py", "scene_lint.py", "vn_compose.py", "make_grok_input.py",
              "local_llm.py", "makefun_client.py", "print_preflight.py", "print_export.py",
              "export_viewer.py", "export_pwa.py", "backup_project.py", "secret_scan.py",
              "selftest.py"]
# 없어도 되는 파일 — 있으면 그 경로가 쓸 수 있다는 뜻이라 상태만 알린다.
OPTIONAL_TOOLS = {"talk_store.py": "대화 저장 계층(없으면 webapp 내장 구현을 씁니다)",
                  "grok_api.py": "그록 API 모드", "xai_client.py": "그록 API 클라이언트"}


def check_tools() -> None:
    missing = [n for n in NEED_TOOLS if not (TOOLS / n).exists()]
    if missing:
        add("실행 환경", "도구 파일", ERR, "누락: " + ", ".join(missing),
            "패키지를 다시 받거나 백업에서 복원하세요 (docs/RECOVERY_RUNBOOK.md).")
    else:
        add("실행 환경", "도구 파일", OK, f"{len(NEED_TOOLS)}개 모두 있음 (vn_core·scene_ops 포함)")

    have = [n for n in OPTIONAL_TOOLS if (TOOLS / n).exists()]
    lack = [n for n in OPTIONAL_TOOLS if n not in have]
    add("실행 환경", "선택 모듈", OK,
        (("있음: " + ", ".join(have)) if have else "없음") +
        ((" · 미설치: " + ", ".join(f"{n}({OPTIONAL_TOOLS[n]})" for n in lack)) if lack else ""))
    check_skew()


# 웹 스튜디오가 넘기는 인자를 설치된 도구가 실제로 받는지 — 파일을 섞어 복원하면
# 옛 도구 + 새 서버 조합이 되어 기능이 조용히 죽는다(즐겨찾기 인화·PWA 아이콘 등).
# 예전에는 webapp 이 요청마다 inspect.signature 로 확인했다. 진단은 여기서 한 번만 한다.
SKEW_EXPECT = (
    ("print_export", "export_batch",
     ("only_ids", "mode", "bg", "marks", "upscale", "order_prefix"), "즐겨찾기 인화·여백/재단선 옵션"),
    ("export_pwa", "export",
     ("cover_id", "font_spec", "icon_from_cut", "icon_scene"), "PWA 표지·글꼴·아이콘 옵션"),
)


def check_skew() -> None:
    """버전 스큐 — 도구 파일들이 서로 같은 세대인가(요청 경로가 아니라 진단에서 한 번만)."""
    bad, unknown = [], []
    for mod_name, fn_name, expect, what in SKEW_EXPECT:
        try:
            params = inspect.signature(
                getattr(importlib.import_module(mod_name), fn_name)).parameters
        except Exception as exc:
            unknown.append(f"{mod_name}.{fn_name}({type(exc).__name__})")
            continue
        missing = [p for p in expect if p not in params]
        if missing:
            bad.append(f"{mod_name}.{fn_name} 에 {', '.join(missing)} 없음 → {what} 실패")
    if bad:
        add("실행 환경", "도구 버전 정합", ERR,
            " / ".join(bad) + (" / 확인 불가: " + ", ".join(unknown) if unknown else ""),
            "tools/ 를 한 세대로 맞추세요 — 같은 백업 스냅샷에서 함께 복원하면 됩니다 "
            "(python tools/backup_project.py list → restore --snapshot <스탬프>).")
    elif unknown:
        add("실행 환경", "도구 버전 정합", WARN, "확인 불가: " + ", ".join(unknown),
            "해당 모듈을 직접 import 해 보고 오류를 확인하세요.")
    else:
        add("실행 환경", "도구 버전 정합", OK,
            f"{len(SKEW_EXPECT)}개 도구가 서버가 기대하는 인자를 모두 받습니다")


def check_disk() -> None:
    try:
        usage = shutil.disk_usage(str(ROOT))
    except OSError as exc:
        add("실행 환경", "디스크 여유", WARN, f"확인 실패: {exc}")
        return
    free_gb = usage.free / (1024 ** 3)
    detail = f"{free_gb:.1f}GB 남음"
    if free_gb < 1:
        add("실행 환경", "디스크 여유", ERR, detail + " — 이미지·백업 저장이 실패할 수 있습니다",
            "backups/ 의 오래된 스냅샷이나 output/ 을 정리하세요.")
    elif free_gb < 5:
        add("실행 환경", "디스크 여유", WARN, detail + " — 감상본·인화 마스터는 수백 MB 를 씁니다")
    else:
        add("실행 환경", "디스크 여유", OK, detail)


# ------------------------------------------------------------------ 2. 환경변수
def _env_state(name: str) -> tuple[bool, int]:
    v = os.environ.get(name, "").strip()
    return bool(v), len(v)


def check_env() -> None:
    """설정 여부와 길이만 본다 — 값은 어떤 경우에도 출력하지 않는다."""
    mf_set, mf_len = _env_state("MAKEFUN_API_TOKEN")
    if mf_set:
        add("환경변수", "MAKEFUN_API_TOKEN(이미지 생성)", OK, f"설정됨 (길이 {mf_len}자, 값 비표시)")
    else:
        add("환경변수", "MAKEFUN_API_TOKEN(이미지 생성)", WARN,
            "미설정 — 이미지 생성만 막히고 나머지 기능은 정상입니다",
            "docs/ENV_SETUP.md 의 setx 절차로 영구 등록하세요.")

    xai_set, xai_len = _env_state("XAI_API_KEY")
    if xai_set:
        add("환경변수", "XAI_API_KEY(그록 예비 경로)", OK, f"설정됨 (길이 {xai_len}자, 값 비표시)")
    else:
        add("환경변수", "XAI_API_KEY(그록 예비 경로)", OK,
            "미설정 — 현재 오케스트레이터는 로컬 LLM 이라 필요 없습니다")

    url = os.environ.get("LOCAL_LLM_URL", "").strip()
    if url:
        p = urllib.parse.urlparse(url)
        add("환경변수", "LOCAL_LLM_URL", OK, f"{p.scheme}://{p.netloc} (매니페스트 talk.base_url 보다 우선)")
    else:
        add("환경변수", "LOCAL_LLM_URL", OK, "미설정 — 매니페스트 talk.base_url 또는 기본값을 씁니다")


# ------------------------------------------------------------------ 3. 로컬 LLM
def check_local_llm() -> None:
    try:
        import local_llm
    except Exception as exc:
        add("로컬 LLM", "모듈 로드", ERR, f"tools/local_llm.py 를 불러올 수 없습니다: {exc}")
        return
    st = local_llm.status()
    if st.get("up"):
        models = ", ".join(m for m in st.get("models", []) if m) or "(모델명 미표시)"
        add("로컬 LLM", "서버 응답", OK, f"{st['url']} · 모델 {models}")
    else:
        add("로컬 LLM", "서버 응답", WARN,
            f"{st.get('url')} 에 응답 없음 — 스토리·프롬프트·대화 탭이 막힙니다",
            "start_studio.ps1 로 함께 켜거나, "
            "powershell -File c:\\Users\\USER\\claude\\local_llm\\runtime\\serve.ps1 을 실행하세요.")


# ------------------------------------------------------------------ 4. 프로젝트 구조
def _load(path: Path):
    """(데이터, 오류문구) — 손상 파일을 '왜 못 읽었는지' 함께 알려야 해서 예외를 문자열로 받는다."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (ValueError, OSError) as exc:
        return None, str(exc)


def check_project() -> None:
    if not MANIFEST.exists():
        add("프로젝트", "매니페스트", ERR, "project/manifest.json 이 없습니다",
            "templates/manifest.json 을 project/manifest.json 으로 복사해 시작하세요.")
        return
    mf, err = _load(MANIFEST)
    if not isinstance(mf, dict):
        add("프로젝트", "매니페스트", ERR, f"JSON 을 읽을 수 없습니다: {err}",
            "backups/ 의 최신 스냅샷에서 복원하세요 (docs/RECOVERY_RUNBOOK.md).")
        return

    title = str(mf.get("title", "")).strip()
    add("프로젝트", "매니페스트", OK if title else WARN,
        f"제목 '{title}'" if title else "제목이 비어 있습니다 (템플릿 상태)")

    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    no_anchor = [c.get("character_id", "?") for c in chars if not str(c.get("prompt_anchor", "")).strip()]
    if not chars:
        add("프로젝트", "캐릭터 기준정보", WARN, "캐릭터가 없습니다")
    elif no_anchor:
        add("프로젝트", "캐릭터 기준정보", WARN,
            f"{len(chars)}명 중 prompt_anchor 없음: {', '.join(no_anchor)}",
            "앵커가 없으면 검사기 A6 와 컷 간 얼굴 일관성이 무너집니다.")
    else:
        add("프로젝트", "캐릭터 기준정보", OK, f"{len(chars)}명 · 앵커 모두 있음")

    no_ref = [c.get("character_id", "?") for c in chars if not c.get("reference_images")]
    if chars:
        add("프로젝트", "레퍼런스 이미지", WARN if no_ref else OK,
            f"reference_images 비어 있음: {', '.join(no_ref)}" if no_ref else "모든 캐릭터에 등록됨",
            "캐릭터 시트를 만들어 등록하면 컷 간 얼굴이 안정됩니다." if no_ref else "")

    style = str(mf.get("output", {}).get("visual_style", "")).strip()
    add("프로젝트", "화풍(output.visual_style)", OK if style else WARN,
        style[:60] if style else "미지정 — 코드 기본 화풍이 쓰입니다")

    check_gen_size()
    check_scenes(mf)


def check_gen_size() -> None:
    """생성 크기 상한과 인화 목표의 모순 — 돈이 새기 전에 잡는다.

    문서는 "인화하려면 output.min_long_edge_px 를 1800/2250/3600 으로 올려라"고 안내하는데,
    image_generator.max_long_edge_px 를 함께 올리지 않으면 요청이 상한(기본 2048px)으로 깎인다.
    **과금은 요청대로 되고** 결과는 인화 규격과 검사기 A3 양쪽에 미달한다.
    판정은 makefun_client 한 곳에 있고(중복 구현 금지) doctor 는 그 결과를 전달만 한다.
    """
    try:
        import makefun_client as mkc
        plan = mkc.size_plan()
        warns = mkc.size_warnings(plan)
    except Exception as exc:
        add("프로젝트", "생성 크기 상한", WARN, f"makefun_client 로 확인할 수 없습니다: {exc}",
            "python tools/makefun_client.py --check 로 직접 확인하세요.")
        return
    detail = (f"요청 {plan['want']}px → 실제 {plan['long']}px "
              f"(상한 {plan['cap']}px{', 기본값' if plan['cap_is_default'] else ''})")
    if warns:
        add("프로젝트", "생성 크기 상한", ERR,
            detail + " — 요청이 조용히 깎인 채 과금됩니다",
            f"manifest image_generator.max_long_edge_px 를 {plan['want']} 이상으로 올리세요. "
            "그대로 두면 인화 규격과 검사기 A3(긴 변 ≥ min_long_edge_px) 양쪽에 미달합니다.")
    elif plan["cap_is_default"]:
        add("프로젝트", "생성 크기 상한", OK,
            detail + " — 인화용으로 min_long_edge_px 를 올릴 때 max_long_edge_px 도 함께 올리세요")
    else:
        add("프로젝트", "생성 크기 상한", OK, detail)


def check_scenes(mf: dict | None = None) -> None:
    if not SCENES.exists():
        add("프로젝트", "장면 폴더", ERR, "project/scenes/ 가 없습니다",
            "폴더를 만들고 templates/scene.json 으로 첫 장면을 작성하세요.")
        return
    files = vn_core.scene_files()     # 목록은 vn_core 단일 출처(정렬·대상 파일명 규약이 한 곳)
    if not files:
        add("프로젝트", "장면", WARN, "장면 파일이 없습니다 — 스토리라인부터 시작하세요")
        return

    broken, mismatch, orders, status_count, missing_img = [], [], [], {}, []
    episodes: dict = {}          # 장면이 실제로 쓰는 화 번호 → 장면 수
    no_episode = []
    for f in files:
        sc, err = _load(f)
        if not isinstance(sc, dict):
            broken.append(f.name)
            continue
        if sc.get("scene_id") != f.stem:
            mismatch.append(f.name)
        order = sc.get("scene_order")
        if isinstance(order, int):
            orders.append(order)
        ep = sc.get("episode")
        if isinstance(ep, int):
            episodes[ep] = episodes.get(ep, 0) + 1
        else:
            no_episode.append(f.stem)
        st = str(sc.get("status", "?"))
        status_count[st] = status_count.get(st, 0) + 1
        sel = vn_core.selected_of(sc)      # 선택 이미지 판독은 vn_core 단일 출처
        if sel and not (ROOT / sel).exists():
            missing_img.append(f"{f.stem}→{sel}")

    add("프로젝트", "장면 수", OK, f"{len(files)}개 · " +
        " / ".join(f"{k} {v}" for k, v in sorted(status_count.items())))

    if broken:
        add("프로젝트", "장면 JSON 무결성", ERR, "읽을 수 없는 파일: " + ", ".join(broken),
            "backups/ 스냅샷에서 해당 파일만 복원하세요.")
    else:
        add("프로젝트", "장면 JSON 무결성", OK, "모두 정상 JSON")

    if mismatch:
        add("프로젝트", "파일명=scene_id", ERR, "불일치: " + ", ".join(mismatch),
            "파일명과 scene_id 를 일치시키세요 (검사기 A2).")
    else:
        add("프로젝트", "파일명=scene_id", OK, "모두 일치")

    if orders:
        expected = list(range(1, len(orders) + 1))
        if sorted(orders) != expected:
            add("프로젝트", "scene_order 연속성", ERR,
                f"1..{len(orders)} 연속이 아닙니다 (현재 {sorted(orders)})",
                "검사기 A5 가 FAIL 합니다. 번호를 1부터 빈틈없이 다시 매기세요.")
        else:
            add("프로젝트", "scene_order 연속성", OK, f"1..{len(orders)} 연속")

    if missing_img:
        add("프로젝트", "선택 이미지 존재", ERR, "원본 없음: " + ", ".join(missing_img),
            "images/ 를 백업에서 복원하거나 해당 장면을 revise 하세요.")
    else:
        add("프로젝트", "선택 이미지 존재", OK, "선택된 이미지 원본이 모두 있습니다")

    check_episodes(mf or {}, episodes, no_episode, len(files) - len(broken))
    check_lint()


def check_episodes(mf: dict, used: dict, no_episode: list, total: int) -> None:
    """화(episode) 드리프트 — 장면의 화 번호와 매니페스트 episodes 목록이 어긋났는지.

    뷰어의 '화 단위 감상'은 두 곳이 맞물려야 동작한다. 어긋나면 제목 없는 화가 생기거나
    (선언은 있는데 장면이 없어) 빈 화가 목록에 뜬다. 검사기 항목이 아니라 여기서 잡는다.
    """
    declared = {e.get("episode") for e in mf.get("episodes", [])
                if isinstance(e, dict) and isinstance(e.get("episode"), int)}
    if not declared and not used:
        add("프로젝트", "화(episode) 구성", OK, "화 구분을 쓰지 않는 작품입니다")
        return

    undeclared = sorted(e for e in used if e not in declared)
    empty = sorted(e for e in declared if e not in used)
    problems = []
    if undeclared:
        problems.append("매니페스트에 없는 화 " + ", ".join(str(e) for e in undeclared))
    if empty:
        problems.append("장면이 없는 화 " + ", ".join(str(e) for e in empty))
    if no_episode and used:
        head = ", ".join(no_episode[:5]) + (f" 외 {len(no_episode) - 5}개" if len(no_episode) > 5 else "")
        problems.append(f"episode 가 없는 장면 {len(no_episode)}/{total}개 ({head})")

    spread = " · ".join(f"{k}화 {v}컷" for k, v in sorted(used.items()))
    if problems:
        add("프로젝트", "화(episode) 정합", WARN, " / ".join(problems) + (f" [{spread}]" if spread else ""),
            "manifest.episodes 와 각 장면의 episode 번호를 맞추세요 (감상본 화 선택이 어긋납니다).")
    else:
        add("프로젝트", "화(episode) 정합", OK, f"{len(declared)}개 화 · {spread}")


def check_lint() -> None:
    """연출 리듬·분기 무결성은 scene_lint 가 판단한다 — doctor 는 요약만 전달(중복 구현 금지)."""
    try:
        import scene_lint
        r = scene_lint.lint_scenes()
    except Exception as exc:
        add("프로젝트", "연출 린트", WARN, f"scene_lint 를 실행할 수 없습니다: {exc}",
            "python tools/scene_lint.py 로 직접 확인하세요.")
        return
    findings = r.get("findings", []) if isinstance(r, dict) else []
    warns = sum(1 for f in findings if isinstance(f, dict) and f.get("level") == "warn")
    add("프로젝트", "연출 리듬(scene_lint 위임)", WARN if warns else OK,
        str(r.get("summary", ""))[:100],
        "자세한 내용과 대상 장면: python tools/scene_lint.py" if warns else "")


def check_backups() -> None:
    b = ROOT / "backups"
    snaps = sorted(b.glob("manifest_*.json")) if b.exists() else []
    if not snaps:
        add("백업", "스냅샷", WARN, "백업이 없습니다",
            "python tools/backup_project.py snapshot 을 한 번 실행해 두세요.")
    else:
        add("백업", "스냅샷", OK, f"{len(snaps)}개 · 최신 {snaps[-1].stem.replace('manifest_', '')}")

    # 이미지가 zip 에 없으면 체크섬은 '무엇이 사라졌는지'만 알려줄 뿐 되돌리지 못한다.
    # 승인 이미지는 유료 생성물이자 유일본이라 이 경고가 실제 복구 가능 여부를 가른다.
    imgs = sorted((ROOT / "images").rglob("*")) if (ROOT / "images").exists() else []
    n_img = sum(1 for p in imgs if p.is_file())
    if snaps and n_img:
        with_img = any(load_json_safe(m, {}).get("images_included") for m in snaps[-3:])
        add("백업", "이미지 원본 포함", OK if with_img else WARN,
            "최근 스냅샷에 이미지 원본 포함됨" if with_img else
            f"최근 3개 스냅샷에 이미지가 빠져 있습니다 — images/ 의 {n_img}개 파일은 "
            "체크섬만 있고 zip 으로 복구할 수 없습니다",
            "" if with_img else
            "python tools/backup_project.py snapshot --with-images  (외장 사본: --dest D:/backup)")

    legacy = sorted(p for p in (ROOT / "project").glob("scenes_backup_*") if p.is_dir()) \
        if (ROOT / "project").exists() else []
    if legacy:
        add("백업", "옛 사본 위치", WARN,
            f"project/scenes_backup_* 사본 {len(legacy)}개가 작업 폴더 안에 있습니다 "
            "(백업 zip 이 매번 부풀고 장면 폴더와 섞입니다)",
            "python tools/backup_project.py migrate --dry-run  → 확인 후 --yes 로 backups/legacy/ 이관")


# ------------------------------------------------------------------ 5. 비밀값
def check_secrets() -> None:
    """secret_scan 을 실제로 실행한다 — '따로 실행하세요' 안내는 아무도 실행하지 않는다.

    출력은 위치와 종류까지만. 마스킹된 값조차 콘솔·캡처로 2차 유출될 수 있어 doctor 는 싣지 않는다.
    """
    try:
        import secret_scan
    except Exception as exc:
        add("비밀값", "스캔", WARN, f"secret_scan 을 불러올 수 없습니다: {exc}",
            "python tools/secret_scan.py 로 직접 실행하세요.")
        return
    try:
        findings = secret_scan.scan(ROOT)
    except OSError as exc:
        add("비밀값", "스캔", WARN, f"스캔 중 파일 읽기 실패: {exc}")
        return
    if not findings:
        add("비밀값", "스캔", OK, "저장소에 키·토큰·개인키 파일 없음 (값은 환경변수에만)")
        return
    where = ", ".join(f"{f['file']}:{f['line']}[{f['kind']}]" if f["line"] else f"{f['file']}[{f['kind']}]"
                      for f in findings[:3])
    more = f" 외 {len(findings) - 3}건" if len(findings) > 3 else ""
    add("비밀값", "스캔", ERR, f"{len(findings)}건 발견 — {where}{more} (값은 표시하지 않습니다)",
        "python tools/secret_scan.py 로 전체 목록 확인 → 해당 키를 즉시 폐기·재발급하고 "
        "환경변수 참조로 바꾸세요 (docs/ENV_SETUP.md).")


# ------------------------------------------------------------------ 출력
def run_all() -> None:
    check_python()
    check_pillow()
    check_tools()
    check_disk()
    check_env()
    check_local_llm()
    check_project()
    check_backups()
    check_secrets()


def main() -> int:
    ap = argparse.ArgumentParser(description="환경 종합 점검 (읽기 전용)")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
    args = ap.parse_args()

    run_all()
    errors = sum(1 for r in _results if r["level"] == ERR)
    warns = sum(1 for r in _results if r["level"] == WARN)

    if args.json:
        print(json.dumps({"errors": errors, "warnings": warns, "results": _results},
                         ensure_ascii=False, indent=2))
        return 1 if errors else 0

    mark = {OK: "OK  ", WARN: "!   ", ERR: "✗   "}
    print("=" * 62)
    print("환경 점검 (doctor) — 읽기 전용 진단")
    print("=" * 62)
    section = None
    for r in _results:
        if r["section"] != section:
            section = r["section"]
            print(f"\n[{section}]")
        print(f"  {mark[r['level']]}{r['name']}: {r['detail']}")
        if r["fix"] and r["level"] != OK:
            print(f"        → {r['fix']}")
    print("\n" + "-" * 62)
    if errors:
        print(f"문제 {errors}건 · 경고 {warns}건 — 위의 → 안내부터 처리하세요.")
    elif warns:
        print(f"치명 문제 없음 · 경고 {warns}건 (기능은 동작합니다).")
    else:
        print("모두 정상입니다.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
