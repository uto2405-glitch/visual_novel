#!/usr/bin/env python3
"""이미지 엔진 선택기 — ComfyUI(무료·로컬·기본)와 MakeFun(유료·원격·보조)을 한 문으로.

webapp·doctor 는 어느 엔진인지 모르고 이 모듈만 부른다. 엔진을 고르는 규칙은 매니페스트
``image_generator.engine`` 하나다("comfyui" | "makefun"). 키가 **없으면 "makefun"** — 이 키가 생기기
전의 매니페스트는 전부 MakeFun 단독 시절 것이라, 그 파일을 그대로 열어도 동작이 바뀌지 않는다.

두 클라이언트는 같은 공개 계약(generate_for_scene / generate_to_dir → gen_common.GenResult,
size_plan, check)을 갖는다. 여기서는 그 계약 위에 라벨·상태 조회·진행 문구만 얹는다 —
재수령(refetch)·업스케일·크레딧은 MakeFun 에만 있는 개념이라 여기 두지 않는다(webapp 이 직접 부른다).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import comfyui_client   # noqa: E402
import makefun_client   # noqa: E402
import vn_core          # noqa: E402
from vn_core import VNError   # noqa: E402

ENGINES = {"comfyui": "ComfyUI", "makefun": "MakeFun"}
DEFAULT_ENGINE = "makefun"          # engine 키가 없는 옛 매니페스트 = MakeFun 단독 시절
FREE_ENGINE = "comfyui"             # 설정이 있으면 폴백은 무료 쪽으로 — 아래 _fallback_engine
_CLIENTS = {"comfyui": comfyui_client, "makefun": makefun_client}
HEALTH_TIMEOUT = 3                  # 상태 버튼 한 번에 화면이 3초 넘게 멈추지 않게

log = logging.getLogger("vn.gen")   # 생성 작업과 같은 채널 — webapp.setup_logging 이 파일에 물린다
log.addHandler(logging.NullHandler())


def _ig(mf: dict | None = None) -> dict:
    mf = mf if isinstance(mf, dict) else vn_core.load_manifest()
    ig = mf.get("image_generator", {})
    return ig if isinstance(ig, dict) else {}


def label(engine: str) -> str:
    return ENGINES.get(str(engine or "").lower(), str(engine or ""))


_WARNED_ENGINES: set[str] = set()   # 모르는 엔진 값 — 값마다 프로세스당 한 번만 경고한다
_WARN_CAP = 50                      # 방어적 상한(매니페스트가 계속 바뀌어도 집합이 무한히 자라지 않게)


def _fallback_engine(ig: dict) -> str:
    """`engine` 을 못 읽었을 때 **어느 쪽으로 떨어질 것인가.**

    예전에는 무조건 MakeFun 이었다. 그 규칙은 engine 키가 생기기 전 매니페스트(= MakeFun
    단독 시절)를 그대로 열어도 동작이 바뀌지 않게 하려는 것이었는데, 오타 하나에도 **유료
    원격 엔진**으로 떨어진다는 뜻이기도 하다 — `engien: "comfyui"` 한 글자가 과금이 된다.

    그래서 조건을 하나 붙인다: 이 매니페스트에 **ComfyUI 설정 블록이 있으면** 무료 쪽으로
    떨어진다. 옛 매니페스트에는 그 블록이 없으므로 호환은 글자 그대로 유지되고, 무료
    엔진을 설정해 둔 작품에서 오타가 과금으로 이어지는 길만 닫힌다.
    """
    return FREE_ENGINE if isinstance(ig.get("comfyui"), dict) else DEFAULT_ENGINE


def active_engine(mf: dict | None = None) -> str:
    """매니페스트가 고른 기본 엔진. 못 읽는 값은 폴백하되 로그에 남긴다(:func:`_fallback_engine`).

    경고는 **값마다 한 번**이다. 이 함수는 webapp.state() 가 부르고 스튜디오는 그 상태를
    주기적으로 폴링하므로, 매번 경고하면 오타 하나가 logs/webapp.log 를 같은 줄로 채운다
    (진짜 사고가 그 사이에 묻힌다). 사실은 한 번 말하면 충분하고, 값이 바뀌면 다시 말한다.
    """
    ig = _ig(mf)
    fallback = _fallback_engine(ig)
    engine = str(ig.get("engine", "") or "").strip().lower()
    if not engine:
        return fallback
    if engine not in ENGINES:
        if engine not in _WARNED_ENGINES:
            if len(_WARNED_ENGINES) < _WARN_CAP:
                _WARNED_ENGINES.add(engine)
            log.warning("image_generator.engine=%r 는 모르는 값 — %s 로 동작합니다(이 값은 한 번만 알립니다)",
                        engine, fallback)
        return fallback
    return engine


def configured_engines(mf: dict | None = None) -> list[str]:
    """설정이 있어 쓸 수 있는 엔진들 — 기본 엔진이 맨 앞. 화면의 보조 버튼이 이 목록을 본다."""
    ig = _ig(mf)
    active = active_engine(mf)
    out = [active]
    if "comfyui" not in out and (isinstance(ig.get("comfyui"), dict) or active == "comfyui"):
        out.append("comfyui")
    if "makefun" not in out and (isinstance(ig.get("makefun"), dict) or isinstance(ig.get("api"), dict)):
        out.append("makefun")
    return out


def client(engine: str | None = None):
    """엔진 이름 → 클라이언트 모듈. 모르는 이름은 VNError(요청 body 로 들어오는 값이라 검증한다)."""
    name = str(engine or active_engine()).lower()
    mod = _CLIENTS.get(name)
    if mod is None:
        raise VNError(f"알 수 없는 이미지 엔진입니다: {str(engine)[:40]!r} (가능: {', '.join(ENGINES)})")
    return mod


def _netloc(url: str) -> str:
    """host:port 만 — userinfo(user:pw@)·토큰·경로가 화면으로 나가지 않게(vn_core.host_port)."""
    return vn_core.host_port(url)


def _model_of(engine: str) -> str:
    if engine == "comfyui":
        return comfyui_client.configured_checkpoint() or "(ComfyUI 첫 체크포인트)"
    return str(makefun_client._cfg().get("model", "") or "a2e")


def _url_of(engine: str) -> str:
    try:
        return _netloc(client(engine).base_url())
    except VNError:
        return ""


def engine_info(mf: dict | None = None) -> dict:
    """/api/state 에 실리는 요약 — 비밀값 없음(mf_token 은 불리언만)."""
    engine = active_engine(mf)
    return {"engine": engine,
            "provider": str(_ig(mf).get("provider", "") or label(engine)),
            "model": _model_of(engine),
            "url": _url_of(engine),
            "engines": configured_engines(mf),
            "mf_token": bool(os.environ.get(makefun_client.TOKEN_ENV, "").strip()),
            "billable": engine == "makefun"}


def health(engine: str | None = None) -> dict:
    """엔진 상태 — comfyui 는 /system_stats + 체크포인트(3초 상한), makefun 은 토큰 유무(네트워크 없음).

    MakeFun 에는 묻지 않는다: 조회 호출도 토큰을 쓰는 실호출이라 '상태 버튼'이 계정을 두드리면 안 된다.
    """
    name = str(engine or active_engine()).lower()
    mod = client(name)
    out = {"engine": name, "provider": label(name), "ok": False, "detail": "",
           "checkpoints": [], "model": _model_of(name), "billable": name == "makefun"}
    if name == "makefun":
        has = bool(os.environ.get(makefun_client.TOKEN_ENV, "").strip())
        out["ok"] = has
        out["detail"] = ("토큰 설정됨 — 유료 종량제(호출 1회 = 과금)" if has
                         else f"{makefun_client.TOKEN_ENV} 미설정 — MakeFun 생성 불가")
        return out
    try:
        st = mod._json("GET", "/system_stats", timeout=HEALTH_TIMEOUT)
        ver = str((st.get("system") or {}).get("comfyui_version", "?"))
        names = mod.checkpoints(refresh=True)
        ck = mod.configured_checkpoint()
        out["checkpoints"] = names
        if ck and ck not in names:
            out["detail"] = f"ComfyUI {ver} 응답 · 지정 체크포인트 {ck} 가 설치 목록에 없습니다"
        elif not names:
            out["detail"] = f"ComfyUI {ver} 응답 · 체크포인트 없음"
        else:
            out["ok"] = True
            out["detail"] = f"ComfyUI {ver} · {_netloc(mod.base_url())} · 체크포인트 {len(names)}개 · 무료"
    except VNError as e:
        out["detail"] = str(e)
    return out


def generate_for_scene(sid: str, n: int = 1, engine: str | None = None, on_progress=None,
                       quiet: bool = False, **kw):
    return client(engine).generate_for_scene(sid, n=n, on_progress=on_progress, quiet=quiet, **kw)


def generate_to_dir(prompt: str, out_dir, engine: str | None = None, **kw):
    return client(engine).generate_to_dir(prompt, out_dir, **kw)


def progress_text(engine: str | None, kind: str, elapsed, status: str = "") -> str:
    """gen_jobs 진행 한 줄 — 어느 엔진이 굽고 있는지 화면에 보인다."""
    return f"{label(engine or active_engine())} {kind} 중… {float(elapsed or 0):.0f}초 경과 · {status or '조회중'}"
