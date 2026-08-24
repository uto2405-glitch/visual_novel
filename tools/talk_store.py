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
