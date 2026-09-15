#!/usr/bin/env python3
"""대화 로그 저장 계층 — 인물 대화와 스토리 챗로그의 **단일 출처**.

사용자가 가장 아끼는 자산이 이 파일들이다. 그래서 규칙이 하나뿐이다:

  **대화 로그는 어떤 경로로도 조용히 짧아지지 않는다.**

  * 클라이언트가 보낸 목록으로 저장본을 덮어쓰지 않는다 — 항상 :func:`merge_messages` 로 합친다.
  * 상한(LOG_CAP)을 넘어 잘라내야 할 때도 **버리지 않고** 옆 파일
    ``talk_<cid>.archive.jsonl`` 로 이관한 뒤에만 자른다. 이관이 실패하면 자르지 않는다.

경로 규칙도 여기 하나뿐이다. webapp 과 local_llm 이 서로 다른 규칙으로 파일명을 만들면
특수문자가 든 character_id 에서 "장기 기억이 조용히 비는" 현상이 생긴다. 두 쪽 모두
:func:`talk_path` 를 부른다.

공개 API
  normalize_cid(cid) -> str          파일명에 쓸 안전한 character_id (경로 탈출 차단)
  talk_path(cid) -> Path             project/story/talk_<cid>.json
  load_messages(cid) -> list         저장된 대화 (없거나 깨져도 빈 목록)
  save_messages(cid, msgs)           저장 (상한 초과분은 아카이브로 이관)
  merge_messages(saved, incoming)    저장본 + 클라이언트 이력 → 잃는 것 없이 합치기
  load_log(path) / save_log(path, msgs)   파일 경로를 직접 다루는 저수준(스토리 챗로그용)
  story_chat_path() -> Path          project/story/chatlog.json
  resolve_cid(cid=None) -> str       요청값 > manifest.talk.character_id > 첫 캐릭터

Python 3.9+ · 표준 라이브러리만.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core  # noqa: E402

STORY_DIR = vn_core.STORY
LOG_CAP = 1_500_000          # 대화 로그 파일 상한(바이트). 초과분은 아카이브로 이관한다.
ARCHIVE_SUFFIX = ".archive.jsonl"
ROLES = ("user", "assistant")


# ---------------------------------------------------------------- 경로
def normalize_cid(cid: Any) -> str:
    """대화 로그 파일명에 쓸 안전한 character_id.

    영숫자(한글 포함)·하이픈·언더스코어만 남긴다 → '../x' 같은 값이 파일 경로가 되지 못한다.
    정상적인 id(CHAR-001)에는 아무 변화가 없다.
    """
    return vn_core.safe_slug(cid, "CHAR")


def talk_path(cid: Any) -> Path:
    """인물 대화 로그 파일. **webapp 과 local_llm 이 함께 쓰는 유일한 경로 규칙.**"""
    return STORY_DIR / f"talk_{normalize_cid(cid)}.json"


def story_chat_path() -> Path:
    """스토리 기획 대화 로그(작품 단위 하나)."""
    return STORY_DIR / "chatlog.json"


# 여러 갈래의 스토리 대화 — 통합 화면의 '목록'이 쓴다.
# 기본 갈래(chat_id 없음)는 위의 chatlog.json 그대로다. 스튜디오의 스토리 탭과 같은 파일을
# 계속 쓰므로, 목록 기능이 생겨도 예전 대화가 사라지지 않는다.
CHAT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
CHAT_PREFIX = "chat_"


def normalize_chat_id(chat_id: Any) -> str:
    """대화 갈래 id → 안전한 문자열. 빈 값·형식 위반은 '' (=기본 갈래)로 떨어뜨린다.

    파일 이름이 되는 값이라 형식 관문이 곧 경로 탈출 방어다. vn_core.safe_path 도 뒤에
    있지만, 이름 단계에서 먼저 막는 편이 무엇이 거부됐는지 읽기 쉽다.
    """
    s = str(chat_id or "").strip()
    return s if CHAT_ID_RE.match(s) else ""


def story_chat_path_for(chat_id: Any = None) -> Path:
    """갈래별 스토리 대화 로그 경로. id 가 없으면 기본 갈래(chatlog.json)."""
    cid = normalize_chat_id(chat_id)
    return STORY_DIR / f"{CHAT_PREFIX}{cid}.json" if cid else story_chat_path()


def chat_meta_path() -> Path:
    """갈래별 설정(작품 문맥 사용 여부 등) — 한 파일에 모은다.

    갈래마다 파일을 하나 더 만들지 않는 이유: 설정은 몇 바이트인데 파일 수만 두 배가 되고,
    git 제외 규칙이 파일 이름을 따라가야 하는 부담이 늘어난다.

    이름이 ``chats_meta`` 인 이유: 예전엔 ``chat_meta.json`` 이었는데 그게 갈래 파일 규칙
    (``chat_<id>.json``)과 겹쳐서, 설정 파일 자신이 'meta' 라는 이름의 빈 대화로 목록에
    나타났다. 접두사를 달리해 충돌 자체를 없앤다.
    """
    return STORY_DIR / "chats_meta.json"


def _default_use_context(chat_id: str) -> bool:
    """기본 갈래는 작품을 아는 채로, 새 갈래는 백지로 시작한다.

    기본 갈래는 스튜디오의 스토리 탭과 같은 기록이라 예전 동작(작품 문맥 포함)을 지킨다.
    새로 만든 갈래는 '새 이야기'라는 뜻이므로 백지가 맞다 — 그렇지 않으면 사용자가
    말하지도 않은 인물이 답에 섞여 나온다.
    """
    return not chat_id


def load_chat_meta() -> dict:
    """{chat_id: {use_context: bool}} — 파일이 없거나 깨졌으면 빈 dict."""
    raw = vn_core.load_json_safe(chat_meta_path(), {})
    return raw if isinstance(raw, dict) else {}


def chat_use_context(chat_id: Any) -> bool:
    """이 갈래가 작품 문맥을 쓰는가. 저장된 값이 없으면 기본값."""
    cid = normalize_chat_id(chat_id)
    rec = load_chat_meta().get(cid or "")
    if isinstance(rec, dict) and isinstance(rec.get("use_context"), bool):
        return rec["use_context"]
    return _default_use_context(cid)


def set_chat_use_context(chat_id: Any, value: bool) -> bool:
    """이 갈래의 작품 문맥 사용 여부를 저장한다."""
    cid = normalize_chat_id(chat_id)
    meta = load_chat_meta()
    rec = meta.get(cid or "")
    meta[cid or ""] = {**(rec if isinstance(rec, dict) else {}), "use_context": bool(value)}
    vn_core.atomic_write_json(chat_meta_path(), meta)
    return bool(value)


def list_story_chats() -> list[dict]:
    """대화 갈래 목록 → [{id, title, count, mtime}] · 최근에 쓴 것이 앞.

    title 은 첫 사용자 발화의 앞부분이다. 따로 이름을 받지 않는 이유는, 이름을 묻는 순간
    사용자가 대화를 시작하기 전에 한 번 멈춰야 하기 때문이다(요즘 챗 UI 가 그렇게 한다).
    """
    out: list[dict] = []
    seen: set[Path] = set()
    candidates = [story_chat_path()]
    try:
        meta = chat_meta_path()
        candidates += [p for p in sorted(STORY_DIR.glob(f"{CHAT_PREFIX}*.json")) if p != meta]
    except OSError:
        pass
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            if path == story_chat_path():
                continue
            continue
        msgs = load_log(path)
        cid = "" if path == story_chat_path() else path.stem[len(CHAT_PREFIX):]
        title = ""
        for m in msgs:
            if m.get("role") == "user":
                title = str(m.get("content") or "").strip().replace("\n", " ")[:40]
                break
        try:
            mtime = int(path.stat().st_mtime)
        except OSError:
            mtime = 0
        out.append({"id": cid, "title": title, "count": len(msgs), "mtime": mtime,
                    "use_context": chat_use_context(cid)})
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out


def truncate_log(path: Path | str, keep: int) -> dict:
    """대화를 앞에서 ``keep`` 개만 남기고 자른다. **잘린 부분은 버리지 않는다.**

    이 모듈의 규칙은 "대화 로그는 조용히 짧아지지 않는다" 이고, 이 함수는 그 규칙의
    **유일한 예외**다 — 사용자가 화면에서 '수정'·'다시 생성'을 눌러 명시적으로 요청했을 때만
    불린다. 그래서 조용하지 않다: 잘라낸 구간을 save_log 와 같은 아카이브 파일로 옮긴 뒤에만
    자르고, 옮기지 못하면 자르지 않는다(실패하면 아무것도 잃지 않는 쪽으로 넘어진다).

    반환: {"kept": 남은 수, "dropped": 옮긴 수}
    """
    path = Path(path)
    msgs = load_log(path)
    keep = max(0, int(keep))
    if keep >= len(msgs):
        return {"kept": len(msgs), "dropped": 0}
    dropped = msgs[keep:]
    if dropped:
        try:
            _append_archive(archive_path(path), dropped)
        except OSError:
            # 이관 실패 → 자르지 않는다. 사용자는 다시 시도할 수 있지만, 지워진 말은 못 돌린다.
            return {"kept": len(msgs), "dropped": 0, "error": "아카이브 저장 실패 — 자르지 않았습니다."}
    vn_core.atomic_write_text(
        path, json.dumps({"messages": msgs[:keep]}, ensure_ascii=False, indent=2))
    return {"kept": keep, "dropped": len(dropped)}


def delete_story_chat(chat_id: Any) -> bool:
    """갈래 하나를 지운다. 기본 갈래는 지우지 않는다(스튜디오가 같은 파일을 쓴다)."""
    cid = normalize_chat_id(chat_id)
    if not cid:
        return False
    path = story_chat_path_for(cid)
    ok = False
    for p in (path, archive_path(path)):
        try:
            if p.is_file():
                p.unlink()
                ok = True
        except OSError:
            pass
    return ok


def archive_path(path: Path | str) -> Path:
    """상한 초과분을 옮겨 담는 파일 — talk_CHAR-001.json → talk_CHAR-001.archive.jsonl.

    (새 파일로 회전하지 않고 이름을 하나로 고정하는 이유: 사적 대화 로그의 파일명이
     계속 늘어나면 git 제외 규칙이 따라가지 못해 개인 대화가 저장소에 실릴 수 있다.)
    """
    p = Path(path)
    return p.with_name(p.stem + ARCHIVE_SUFFIX)


# ---------------------------------------------------------------- 읽기
def _clean(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for m in raw:
        if not isinstance(m, dict) or m.get("role") not in ROLES:
            continue
        item = {"role": m["role"], "content": str(m.get("content", "") or "")}
        ph = m.get("photos")
        if isinstance(ph, list):
            item["photos"] = [p for p in ph if isinstance(p, dict)]
        out.append(item)
    return out


def load_log(path: Path | str) -> list[dict]:
    """{"messages":[...]} 형식의 로그 읽기 — 없거나 깨져도 예외 없이 빈 목록."""
    data = vn_core.load_json_safe(path, {})
    return _clean(data.get("messages"))


def load_messages(cid: Any) -> list[dict]:
    return load_log(talk_path(cid))


# ---------------------------------------------------------------- 쓰기
def _append_archive(path: Path, dropped: list[dict]) -> None:
    """잘라낼 구간을 JSONL 로 이어붙인다(한 줄 = 한 발화).

    통째로 다시 쓰지 않고 append 하므로 아카이브가 아무리 커져도 저장 비용이 일정하고,
    도중에 멈춰도 이미 적힌 줄은 남는다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for m in dropped:
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def save_log(path: Path | str, messages: list, cap: int = LOG_CAP) -> None:
    """대화 로그 저장. 상한을 넘으면 오래된 구간을 **아카이브로 옮긴 뒤** 잘라낸다.

    이관에 실패하면 자르지 않고 전체를 그대로 저장한다 — 파일이 상한을 넘는 것보다
    사용자의 대화가 사라지는 쪽이 훨씬 나쁘다.
    """
    path = Path(path)
    msgs = [m for m in messages if isinstance(m, dict)]
    dropped: list[dict] = []
    while True:
        body = json.dumps({"messages": msgs}, ensure_ascii=False, indent=2)
        if len(body.encode("utf-8")) <= cap or len(msgs) <= 2:
            break
        cut = len(msgs) // 4 + 1
        dropped.extend(msgs[:cut])
        msgs = msgs[cut:]
    if dropped:
        try:
            _append_archive(archive_path(path), dropped)
        except OSError:
            vn_core.atomic_write_text(       # 이관 실패 → 손실 대신 상한 초과를 택한다
                path, json.dumps({"messages": [m for m in messages if isinstance(m, dict)]},
                                 ensure_ascii=False, indent=2))
            return
    vn_core.atomic_write_text(path, body)


def save_messages(cid: Any, messages: list, cap: int = LOG_CAP) -> None:
    save_log(talk_path(cid), messages, cap)


# ---------------------------------------------------------------- 병합
def _msg_eq(a: dict, b: dict) -> bool:
    """같은 대사인지 — 사진 메타는 클라이언트가 떼고 보내므로 역할·본문만 비교한다."""
    return (a.get("role") == b.get("role")
            and str(a.get("content", "")) == str(b.get("content", "")))


def merge_messages(saved: list, incoming: list) -> list[dict]:
    """저장본 + 클라이언트가 보낸 이력 → 잃는 것 없이 합친다.

    * 정상(이어서 대화): 저장본이 incoming 의 접두사 → 뒤에 붙은 새 대화만 추가.
    * 새 세션이 빈 화면에서 시작: 겹치는 부분이 없음 → 저장본 뒤에 이어붙인다(절대 잘라내지 않음).
    * 저장본이 더 길고 incoming 이 그 일부: 남는 저장본을 보존하고 새 발화만 뒤에 붙인다.
    사진 메타는 저장본 쪽을 유지한다(클라이언트는 텍스트만 되돌려 보내므로).
    """
    if not saved:
        return [dict(m) for m in incoming]
    if not incoming:
        return [dict(m) for m in saved]
    p = 0
    while p < len(saved) and p < len(incoming) and _msg_eq(saved[p], incoming[p]):
        p += 1
    if p == 0:   # 접두사가 전혀 겹치지 않으면 저장본의 꼬리와 겹치는지 본다(중복 방지)
        for k in range(min(len(saved), len(incoming)), 0, -1):
            if all(_msg_eq(saved[len(saved) - k + i], incoming[i]) for i in range(k)):
                p = k
                break
    return [dict(m) for m in saved] + [dict(m) for m in incoming[p:]]


# ---------------------------------------------------------------- 대화 상대
def resolve_cid(cid: Any = None) -> str:
    """대화 상대 ID — 요청값 > manifest.talk.character_id > 첫 캐릭터 (local_llm 과 같은 규칙)."""
    if isinstance(cid, str) and cid.strip():
        return cid.strip()
    mf = vn_core.load_manifest()
    talk = mf.get("talk") if isinstance(mf.get("talk"), dict) else {}
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    return str((talk or {}).get("character_id")
               or (chars[0].get("character_id") if chars else "") or "")
