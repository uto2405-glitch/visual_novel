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
  export_chat_bytes(chat_id) -> (name, zip)   대화 하나를 zip 한 덩어리로
  import_chat_bytes(data, want_id) -> dict    zip → **새** 갈래 (기존 갈래를 덮어쓰지 않는다)

Python 3.9+ · 표준 라이브러리만.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import zipfile
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


def chat_cast(chat_id: Any):
    """이 대화에 **누가 나오는가** — 고유 캐릭터 id 목록. 안 정했으면 ``None``.

    ``None`` 과 ``[]`` 는 다른 뜻이다. 안 정했으면 예전 그대로 매니페스트의 인물을 쓰고,
    빈 목록은 **사람이 "아무도 안 나온다" 고 말한 것**이다(고양이 이야기·풍경 단편).
    그 둘을 같이 취급하면, 조립이 고양이 이야기에 이지혜를 밀어 넣던 그 버그로 돌아간다.
    """
    rec = load_chat_meta().get(normalize_chat_id(chat_id) or "")
    raw = rec.get("cast") if isinstance(rec, dict) else None
    if not isinstance(raw, list):
        return None
    return [str(x).strip() for x in raw if str(x).strip()]


def set_chat_cast(chat_id: Any, ids: Any) -> list:
    """출연진을 적는다. ``None`` 을 주면 '안 정한 상태'로 되돌린다."""
    cid = normalize_chat_id(chat_id) or ""
    meta = load_chat_meta()
    rec = meta.get(cid) if isinstance(meta.get(cid), dict) else {}
    if ids is None:
        rec = {k: v for k, v in rec.items() if k != "cast"}
        out: list = []
    else:
        seen, out = set(), []
        for x in (ids if isinstance(ids, list) else []):
            s = str(x).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        rec = {**rec, "cast": out}
    meta[cid] = rec
    vn_core.atomic_write_json(chat_meta_path(), meta)
    return out


def chat_composed_upto(chat_id: Any) -> int:
    """이 갈래에서 **어디까지 장면으로 만들었는가**(발화 수).

    이것이 있어야 [장면으로 조립] 을 다시 눌렀을 때 **새로 쓴 대목만** 만들 수 있다.
    없으면 누를 때마다 처음부터 다시 만들어 같은 장면이 쌓이고, 그게 바로
    "통스토리로 바로 굽는다" 는 불만의 정체다.
    """
    rec = load_chat_meta().get(normalize_chat_id(chat_id) or "")
    n = (rec or {}).get("composed_upto") if isinstance(rec, dict) else None
    try:
        return max(0, int(n))
    except (TypeError, ValueError):
        return 0


def set_chat_composed_upto(chat_id: Any, n: int) -> int:
    """장면으로 만든 지점을 옮긴다. 뒤로는 가지 않는다(같은 대목을 두 번 만들지 않게)."""
    cid = normalize_chat_id(chat_id) or ""
    meta = load_chat_meta()
    rec = meta.get(cid)
    cur = 0
    if isinstance(rec, dict):
        try:
            cur = max(0, int(rec.get("composed_upto") or 0))
        except (TypeError, ValueError):
            cur = 0
    val = max(cur, max(0, int(n or 0)))
    meta[cid] = {**(rec if isinstance(rec, dict) else {}), "composed_upto": val}
    vn_core.atomic_write_json(chat_meta_path(), meta)
    return val


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


# ---------------------------------------------------------------- 목록 요약 표
#
# 목록 화면은 대화마다 제목 한 줄과 개수 하나만 쓴다. 그런데 그 둘을 얻으려면 로그 전체를
# json 으로 풀어야 한다 — 대화가 50개면 페이지를 열 때마다 50개 파일을 전부 다시 읽었다.
#
# 파일이 그대로면 요약도 그대로다. 그래서 (mtime_ns, size) 로 표를 만들어 두고, 바뀜 파일만
# 다시 읽는다. 초 단위(st_mtime)가 아니라 **나노초**를 쓰는 이유는, 같은 초 안에 길이가 같은
# 수정(한 글자 고침)이 일어나면 초 단위 키로는 변화를 못 보기 때문이다.
_SUMMARY: dict = {}
_SUMMARY_CAP = 400          # 표가 무한히 자라지 않게 — 넘으면 이번에 본 것만 남긴다


def _title_of(msgs: list) -> str:
    """목록에 적을 한 줄 — 첫 사용자 발화의 앞부분."""
    for m in msgs:
        if m.get("role") == "user":
            return str(m.get("content") or "").strip().replace("\n", " ")[:40]
    return ""


def _summary_of(path: Path):
    """{title, count, mtime} — 파일이 그대로면 다시 파싱하지 않는다. 읽을 수 없으면 None."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    k = str(path)
    hit = _SUMMARY.get(k)
    if hit is not None and hit.get("key") == key:
        return hit
    msgs = load_log(path)
    card = {"key": key, "title": _title_of(msgs), "count": len(msgs),
            "mtime": int(st.st_mtime)}
    _SUMMARY[k] = card
    return card


def _forget_missing(live: set) -> None:
    """이번 훑기에 없던 대화는 표에서 뺀다(삭제된 파일이 영원히 남지 않게)."""
    keep = {str(p) for p in live}
    for k in [k for k in _SUMMARY if k not in keep]:
        _SUMMARY.pop(k, None)
    if len(_SUMMARY) > _SUMMARY_CAP:
        _SUMMARY.clear()


def forget_summary(path) -> None:
    """이 파일의 요약을 잊는다 — 삭제처럼 파일이 사라지는 경로에서 부른다."""
    _SUMMARY.pop(str(path), None)


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
            continue
        card = _summary_of(path)
        if card is None:
            continue
        cid = "" if path == story_chat_path() else path.stem[len(CHAT_PREFIX):]
        out.append({"id": cid, "title": card["title"], "count": card["count"],
                    "mtime": card["mtime"], "use_context": chat_use_context(cid)})
    _forget_missing(seen)
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


def deleted_chat_ids() -> set:
    """지워진 갈래 id 들 — **묘비(tombstone)**.

    왜 파일 존재 여부로는 안 되는가: '지워진 대화' 와 '아직 한 마디도 저장되지 않은 새
    대화' 는 디스크에서 **완전히 같은 모습**이다(파일이 없다). 예전에는 그걸로 판정해서,
    [+ 새 대화] 로 만든 갈래가 첫 발화를 보낼 때마다 "이 대화는 삭제되었습니다" 로
    거절당했다 — 그것도 "목록에서 새 대화를 시작하세요" 라는, 방금 한 행동을 다시 하라는
    문구로. 새 대화 기능이 통째로 막혀 있었다.

    그래서 지웠다는 **사실 자체를 적어 둔다.** 없는 것으로 추측하지 않는다.
    """
    meta = load_chat_meta()
    out = set()
    for cid, rec in meta.items():
        if isinstance(rec, dict) and rec.get("deleted_at"):
            out.add(str(cid))
    return out


def is_deleted_chat(chat_id: Any) -> bool:
    """이 갈래가 '지워진 것' 인가. 저장된 적 없는 새 갈래는 False 다."""
    cid = normalize_chat_id(chat_id)
    return bool(cid) and cid in deleted_chat_ids()


TOMBSTONE_CAP = 300     # 묘비가 무한히 쌓이지 않게 — 오래된 것부터 버린다


def _mark_deleted(cid: str) -> None:
    """묘비를 세운다(설정 파일 한 곳에 모아 둔다)."""
    meta = load_chat_meta()
    rec = meta.get(cid)
    meta[cid] = {**(rec if isinstance(rec, dict) else {}), "deleted_at": int(time.time())}
    stones = sorted(((int((v or {}).get("deleted_at") or 0), k) for k, v in meta.items()
                     if isinstance(v, dict) and v.get("deleted_at")), reverse=True)
    for _ts, k in stones[TOMBSTONE_CAP:]:
        meta.pop(k, None)
    vn_core.atomic_write_json(chat_meta_path(), meta)


def deleted_archive_path(path: Path) -> Path:
    """지운 대화의 보관 기록이 갈 자리 — ``chat_x.deleted.archive.jsonl``.

    ``.deleted`` 를 **``.archive.jsonl`` 앞에** 붙이는 것이 핵심이다. 예전에는 뒤에 붙여
    ``chat_x.archive.deleted.jsonl`` 이 됐는데, 그러면 .gitignore 의
    ``project/story/*.archive.jsonl`` 한 줄에 **걸리지 않는다**. 대화를 하나 지운 뒤
    ``git add .`` 한 번이면 그 사적인 말들이 저장소 이력에 박힌다 — 이 저장소가 절대
    하지 않기로 한 그 일이다. 이름의 순서 하나가 그 규칙을 지키고 깬다.
    """
    p = Path(path)
    base = p.stem + ".deleted"
    cand = p.with_name(base + ARCHIVE_SUFFIX)
    n = 2
    while cand.exists() and n < 100:
        # 같은 id 를 다시 만들어 다시 지우면 먼저 지운 기록을 덮어쓰게 된다 — 비켜 간다.
        cand = p.with_name("%s-%d%s" % (base, n, ARCHIVE_SUFFIX))
        n += 1
    return cand


def clear_default_chat() -> dict:
    """기본 대화를 **비운다**(지우는 것이 아니라).

    기본 갈래는 사라질 수 없다 — 스튜디오의 스토리 탭이 같은 파일을 쓰고, 그 자리가
    없으면 저쪽 탭이 깨진다. 그런데 목록에서는 삭제 버튼만 회색으로 꺼져 있어서,
    사람은 "왜 이것만 안 지워지나" 만 알고 비울 방법은 알 수 없었다.

    그래서 지우는 대신 비운다. 내용은 보관본으로 옮기고(이 모듈의 규칙 그대로)
    빈 기록을 남긴다 — 사람이 보기엔 사라진 것이고, 되돌릴 길도 남는다.
    """
    path = story_chat_path()
    msgs = load_log(path)
    if not msgs:
        return {"cleared": 0}
    try:
        _append_archive(archive_path(path), msgs)
    except OSError:
        raise vn_core.VNError("보관에 실패해 비우지 않았습니다 — 대화는 그대로 있습니다.")
    vn_core.atomic_write_json(path, {"messages": []})
    forget_summary(path)
    meta = load_chat_meta()
    rec = meta.get("")
    if isinstance(rec, dict) and rec.get("composed_upto"):
        meta[""] = {**rec, "composed_upto": 0}   # 비웠으니 조립 지점도 처음으로
        vn_core.atomic_write_json(chat_meta_path(), meta)
    return {"cleared": len(msgs)}


def delete_story_chat(chat_id: Any) -> bool:
    """갈래 하나를 지운다. 기본 갈래는 지우지 않는다(스튜디오가 같은 파일을 쓴다).

    **본문도 버리지 않는다.** 예전에는 본문을 unlink 하고 보관 기록만 남겼다 — 그래서
    '내가 지운 말'(수정·다시 생성으로 밀어낸 것)은 남고 '내가 나눈 대화'만 사라졌다.
    이 모듈의 규칙은 대화 로그가 조용히 짧아지지 않는 것이고, 삭제도 그 규칙 안에 둔다:
    본문을 보관 기록으로 옮긴 **뒤에만** 지운다. 옮기지 못하면 지우지 않는다.
    """
    cid = normalize_chat_id(chat_id)
    if not cid:
        return False
    path = story_chat_path_for(cid)
    forget_summary(path)          # 요약 표에서 먼저 뺀다 — 지우는 중간에 목록이 열려도 유령이 안 나오게

    arch = archive_path(path)
    ok = False
    if path.is_file():
        msgs = load_log(path)
        try:
            if msgs:
                _append_archive(arch, msgs)      # 본문을 먼저 보관한다
            path.unlink()
            ok = True
        except OSError:
            return False                          # 못 옮겼으면 아무것도 지우지 않는다

    # 보관 기록은 지우지 않는다 — 이름만 바꿔 둔다. 거기에는 사용자가 나눈 말과
    # '수정'·'다시 생성' 으로 밀어낸 말이 함께 들어 있다.
    try:
        if arch.is_file():
            arch.replace(deleted_archive_path(path))
            ok = True
    except OSError:
        pass

    # 설정은 지우지 않고 **묘비로 바꾼다.** 지웠다는 사실을 남기지 않으면, 이 id 로 오는
    # 다음 요청이 '지워진 것' 인지 '새 것' 인지 알 수 없다(그게 새 대화를 막고 있던 버그다).
    try:
        _mark_deleted(cid)
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


# ---------------------------------------------------------------- 내보내기 · 가져오기
#
# 대화 하나를 zip 한 덩어리로 들고 다닌다. 왜 필요한가: 이 로그들은 사용자가 이 저장소에서
# 가장 아끼는 자산인데, 지금까지 백업 경로가 "F 드라이브를 통째로 복사한다" 뿐이었다.
# 폰에서 쓰기 시작한 뒤로는 그것마저 안 된다.
#
# 규칙은 이 모듈의 원래 규칙 그대로다: **가져오기가 기존 대화를 덮어쓰지 않는다.** 같은
# id 가 이미 있으면 뒤에 숫자를 붙여 새 갈래로 들어온다. 덮어쓰기는 편해 보이지만, 한 번
# 잘못 누르면 되돌릴 수 없는 유일한 동작이다 — 그 편함은 이 파일들에 걸 만한 것이 아니다.
EXPORT_VERSION = 1
EXPORT_NAME_MSG = "가져올 수 있는 파일이 아닙니다 — 이 화면에서 내보낸 zip 인지 확인하세요."
IMPORT_CAP = 40_000_000      # 압축을 푼 뒤의 상한(zip 폭탄 방어). 대화 로그 상한의 20배 넘는다.


def _export_stem(chat_id: str, when: int) -> str:
    """파일 이름 — 사람이 폴더에서 보고 어느 대화인지 알아볼 수 있게."""
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(when))
    return "chat_%s_%s" % (chat_id or "기본", stamp)


def export_chat_bytes(chat_id: Any = None) -> tuple:
    """대화 하나 → (파일이름, zip 바이트). 보관 기록(archive)도 같이 담는다.

    보관 기록을 왜 넣는가: 거기에는 사용자가 '수정'·'다시 생성' 으로 밀어낸 말들이 들어
    있다. 그것까지 가져와야 "이 대화를 통째로 옮겼다" 가 참이 된다.
    """
    cid = normalize_chat_id(chat_id)
    path = story_chat_path_for(cid)
    msgs = load_log(path)
    when = int(time.time())
    meta = {
        "version": EXPORT_VERSION,
        "kind": "vn-chat",
        "chat_id": cid,
        "title": _title_of(msgs),
        "count": len(msgs),
        "use_context": chat_use_context(cid),
        "exported_at": when,
    }
    buf = io.BytesIO()
    # deflate 로 압축한다 — 대화는 텍스트라 보통 1/4 아래로 줄어든다(폰의 업로드 상한에 걸리는
    # 것이 실제 제약이라, 여기서 줄여 두는 것이 나중에 가져오기가 되느냐를 가른다).
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        z.writestr("chat.json", json.dumps({"messages": msgs}, ensure_ascii=False))
        arch = archive_path(path)
        if arch.is_file():
            try:
                z.writestr("archive.jsonl", arch.read_bytes())
            except OSError:
                pass                    # 보관 기록을 못 읽어도 대화 본문은 내보낸다
    return _export_stem(cid, when) + ".zip", buf.getvalue()


def free_chat_id(want: str) -> str:
    """이미 있는 갈래를 비켜 가는 id. ``want`` 가 비었거나 형식 위반이면 날짜로 만든다."""
    base = normalize_chat_id(want) or ("imp" + time.strftime("%m%d%H%M"))
    base = base[:36] or "imp"           # 뒤에 '-99' 를 붙여도 40자를 넘지 않게
    # 묘비가 서 있는 id 도 피해 간다 — 거기로 가져오면 바로 다음 발화가
    # "삭제되었습니다" 로 거절된다(파일은 있는데 묘비도 있는 상태).
    gone = deleted_chat_ids()
    if not story_chat_path_for(base).exists() and base not in gone:
        return base
    for n in range(2, 100):
        cand = "%s-%d" % (base, n)
        if not story_chat_path_for(cand).exists() and cand not in gone:
            return cand
    raise vn_core.VNError("같은 이름의 대화가 너무 많습니다 — 몇 개를 정리한 뒤 다시 하세요.")


def _zip_text(z, name: str, cap: int) -> str:
    """zip 안의 한 파일을 상한을 지키며 읽는다. 없으면 ''."""
    try:
        info = z.getinfo(name)
    except KeyError:
        return ""
    if info.file_size > cap:
        raise vn_core.VNError("압축을 푼 크기가 너무 큽니다(%s) — 가져오지 않았습니다." % name)
    with z.open(info) as fh:
        return fh.read(cap + 1).decode("utf-8", "replace")


def import_chat_bytes(data: bytes, want_id: Any = "") -> dict:
    """zip → **새** 대화 갈래. 기존 갈래는 어떤 경우에도 덮어쓰지 않는다.

    반환: {"chat_id", "count", "title", "archived", "renamed"}
      renamed=True 면 원래 id 가 이미 쓰여서 다른 이름으로 들어왔다는 뜻이다(화면이 말해 준다).
    """
    try:
        z = zipfile.ZipFile(io.BytesIO(bytes(data)))
    except (zipfile.BadZipFile, ValueError):
        raise vn_core.VNError(EXPORT_NAME_MSG)
    with z:
        raw = _zip_text(z, "chat.json", IMPORT_CAP)
        if not raw:
            raise vn_core.VNError(EXPORT_NAME_MSG)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            raise vn_core.VNError("대화 내용을 읽지 못했습니다 — 파일이 손상된 것 같습니다.")
        msgs = _clean(body.get("messages") if isinstance(body, dict) else None)
        if not msgs:
            raise vn_core.VNError("이 파일에는 대화가 들어 있지 않습니다 — 가져오지 않았습니다.")
        meta = {}
        try:
            meta = json.loads(_zip_text(z, "meta.json", 200_000) or "{}")
        except json.JSONDecodeError:
            meta = {}
        meta = meta if isinstance(meta, dict) else {}
        archive = _zip_text(z, "archive.jsonl", IMPORT_CAP)

    src_id = normalize_chat_id(want_id) or normalize_chat_id(meta.get("chat_id"))
    cid = free_chat_id(src_id)
    path = story_chat_path_for(cid)
    save_log(path, msgs)
    archived = 0
    if archive.strip():
        # 보관 기록은 append 로 들어간다 — 새 갈래라 비어 있지만, 규칙을 여기서도 지킨다.
        lines = [l for l in archive.splitlines() if l.strip()]
        try:
            _append_archive(archive_path(path), [json.loads(l) for l in lines])
            archived = len(lines)
        except (OSError, json.JSONDecodeError):
            archived = 0               # 보관 기록이 깨져도 대화 본문은 들어온 뒤다
    if isinstance(meta.get("use_context"), bool):
        set_chat_use_context(cid, meta["use_context"])
    forget_summary(path)               # 방금 만든 파일 — 요약 표를 다시 읽게 한다
    return {"chat_id": cid, "count": len(msgs), "title": _title_of(msgs),
            "archived": archived, "renamed": bool(src_id) and cid != src_id}
