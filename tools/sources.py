#!/usr/bin/env python3
"""올린 글 — 사람이 가져온 소설을 장면으로 만들기 위해 보관하고, 대목으로 나눈다.

왜 필요한가: 대화로 쓴 이야기는 이미 장면이 된다(:mod:`vn_compose` 의 ``source``).
그런데 **이미 써 둔 소설**은 대화창에 붙여 넣을 수가 없다 — 폰에서 30만 자를 붙여넣는
일도, 그걸 한 번에 모델에게 먹이는 일도 안 된다.

그래서 두 가지를 한다.

1. **파일을 받아 보관한다.** 텍스트만 받는다(.txt · .md). 한글 소설은 메모장에서 저장하면
   cp949 로 저장되는 일이 흔해서, UTF-8 → cp949 → euc-kr 순으로 읽어 본다. 이 순서를
   안 지키면 "글자가 다 깨져 나오는" 파일이 된다.

2. **대목으로 나눈다.** 모델이 한 번에 읽을 수 있는 양은 정해져 있고, 한 번 부를 때
   만들 수 있는 장면도 몇 개뿐이다. 그래서 문단 경계에서 끊어 대목을 만들고, 사람이
   "다음 대목" 을 누를 때마다 그만큼씩 장면이 된다. **문장 중간에서는 절대 안 끊는다** —
   끊긴 문장은 모델에게 다른 이야기로 읽힌다.

어디까지 만들었는지는 **파일 옆에 적어 둔다**(``.state.json``). 그래야 폰에서 하다가
PC 에서 이어도 같은 자리에서 계속된다.

사적인 글이다. ``VN_PRIVATE_DIR`` 이 설정돼 있으면 저장소 **밖**에 둔다(고유 캐릭터
사진과 같은 규칙). 없으면 ``project/story/sources/`` 에 두고 .gitignore 가 막는다.

Python 3.9+ · 표준 라이브러리만. vn_core 하나만 본다(계층 1).
"""
from __future__ import annotations

import codecs
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

try:
    DIR = vn_core.private_or(vn_core.STORY / "sources", "sources")
    PRIVATE_ERROR = ""
except VNError as _exc:                      # 설정이 잘못됐으면 조용히 안으로 돌아가지 않는다
    DIR = vn_core.STORY / "sources"
    PRIVATE_ERROR = str(_exc)

MAX_BYTES = 3 * 1024 * 1024        # 파일 하나 3MB — 장편 소설 한 권이 대략 1~2MB 다
MAX_FILES = 20                     # 대화 하나당 올릴 수 있는 글 수

# 한 대목의 글자 수. **짐작이다** — 로컬 모델의 문맥 크기를 여기서 알 방법이 없다.
# 근거: 조립 한 번이 만드는 장면이 4개 남짓이고, 장면 하나가 원고 한두 쪽에서 나온다.
# 너무 크면 모델이 뒷부분을 버리고(앞만 장면이 된다), 너무 작으면 장면이 잘게 쪼개진다.
# 첫 실사용 뒤에 이 값을 조정한다.
CHUNK_CHARS = 3500
CHUNK_MIN = 800                    # 이보다 짧은 꼬리는 앞 대목에 붙인다(장면 하나도 안 나온다)

_ID_RE = re.compile(r"^[0-9]{8}_[0-9]{6}$")


def _slug(chat_id: Any) -> str:
    s = vn_core.safe_slug(chat_id, "")
    return s or "_default"


def chat_dir(chat_id: Any) -> Path:
    return DIR / _slug(chat_id)


def _require_private() -> None:
    if PRIVATE_ERROR:
        raise VNError("올린 글을 다룰 수 없습니다 — " + PRIVATE_ERROR)


def decode(data: bytes) -> tuple[str, str]:
    """바이트 → (글, 인코딩 이름). 못 읽으면 VNError.

    순서가 중요하다. 한국어 텍스트 파일은 메모장에서 저장하면 cp949 인 경우가 많고,
    그 파일을 UTF-8 로 억지로 읽으면 **글자가 전부 깨진 채로** 저장된다 — 그 상태로
    장면을 만들면 모델도 사람도 무슨 글인지 알 수 없다.
    """
    if not data:
        raise VNError("파일이 비어 있습니다.")
    if b"\x00" in data[:4096]:
        raise VNError("글자 파일이 아닙니다(이진 파일로 보입니다). .txt 나 .md 를 올려 주세요.")
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16"):
        try:
            got = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # utf-8-sig 는 BOM 이 없어도 읽힌다 — 그때 이름은 그냥 utf-8 이라고 적는다.
        # 화면에 뜨는 이름이라, 없는 BOM 을 있다고 말하면 사람이 파일을 의심한다.
        return got, ("utf-8" if enc == "utf-8-sig" and not data.startswith(codecs.BOM_UTF8)
                     else enc)
    raise VNError("글자 인코딩을 알아보지 못했습니다 — UTF-8 로 저장해서 다시 올려 주세요.")


def split_chunks(text: str, budget: int = CHUNK_CHARS) -> list:
    """글 → 대목 목록. **문장 중간에서는 끊지 않는다.**

    끊는 자리를 세 단계로 찾는다: 빈 줄(문단) → 줄바꿈 → 문장 끝(. ? ! ” 다.).
    셋 다 없으면 그때만 글자 수로 끊는다(줄바꿈이 없는 한 덩어리 글).
    """
    body = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not body:
        return []
    budget = max(500, int(budget))
    out: list = []
    rest = body
    while len(rest) > budget:
        window = rest[:budget]
        cut = window.rfind("\n\n")
        if cut < budget // 3:
            cut = window.rfind("\n")
        if cut < budget // 3:
            m = None
            for m in re.finditer(r"[.!?…”\"']\s|다\.\s", window):
                pass
            cut = m.end() if m else -1
        if cut < budget // 3:
            cut = budget          # 끊을 자리가 없다 — 그때만 글자 수로
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        # 꼬리가 너무 짧으면 앞에 붙인다 — 200자짜리 대목은 장면 하나도 못 만든다
        if out and len(rest) < CHUNK_MIN:
            out[-1] = out[-1] + "\n\n" + rest
        else:
            out.append(rest)
    return [c for c in out if c.strip()]


def _state_path(chat_id: Any, sid: str) -> Path:
    return chat_dir(chat_id) / (sid + ".state.json")


def _text_path(chat_id: Any, sid: str) -> Path:
    return chat_dir(chat_id) / (sid + ".txt")


def _require_sid(sid: Any) -> str:
    s = str(sid or "").strip()
    if not _ID_RE.match(s):
        raise VNError(f"올린 글 id 형식이 아닙니다: {s[:40]!r}")
    return s


def save(chat_id: Any, name: str, data: bytes) -> dict:
    """파일 하나를 받아 보관하고 대목으로 나눈다 → 요약."""
    _require_private()
    if not isinstance(data, (bytes, bytearray)):
        raise VNError("파일을 읽지 못했습니다.")
    if len(data) > MAX_BYTES:
        raise VNError("파일이 너무 큽니다 (%.1fMB) — %dMB 까지 받습니다."
                      % (len(data) / 1048576.0, MAX_BYTES // 1048576))
    text, enc = decode(bytes(data))
    if len(text.strip()) < 200:
        raise VNError("글이 너무 짧습니다 — 200자 이상이어야 장면으로 만들 수 있습니다.")
    folder = chat_dir(chat_id)
    folder.mkdir(parents=True, exist_ok=True)
    if len(list(folder.glob("*.txt"))) >= MAX_FILES:
        raise VNError(f"이 대화에는 글을 {MAX_FILES}개까지 올릴 수 있습니다.")
    sid = datetime.now().strftime("%Y%m%d_%H%M%S")
    chunks = split_chunks(text)
    vn_core.atomic_write_text(_text_path(chat_id, sid), text)
    # 이름은 **보여 주기용**이다(파일 이름은 sid 로 따로 짓는다). 그래서 경로 규칙으로
    # 뭉개지 않는다 — "비 오는 서점.txt" 가 "비오는서점txt" 로 보이면 자기 파일을 못 알아본다.
    # 다만 제어문자는 걷고 길이는 자른다(화면 한 줄에 들어가야 한다).
    show = " ".join(str(name or "").split())[:60] or "글"
    rec = {"id": sid, "name": show,
           "chars": len(text), "encoding": enc, "chunks": len(chunks),
           "done": 0, "added": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    vn_core.atomic_write_json(_state_path(chat_id, sid), rec)
    return rec


def load_state(chat_id: Any, sid: str) -> dict:
    sid = _require_sid(sid)
    rec = vn_core.load_json_safe(_state_path(chat_id, sid), None)
    if not isinstance(rec, dict):
        raise VNError(f"{sid} 올린 글을 찾지 못했습니다.")
    return rec


def text_of(chat_id: Any, sid: str) -> str:
    p = _text_path(chat_id, _require_sid(sid))
    try:
        return p.read_text(encoding="utf-8")
    except OSError as exc:
        raise VNError(f"올린 글을 읽지 못했습니다: {exc}")


def list_for(chat_id: Any) -> list:
    """이 대화에 올린 글 목록 — 최근 것이 앞."""
    folder = chat_dir(chat_id)
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.glob("*.state.json"), reverse=True):
        rec = vn_core.load_json_safe(p, None)
        if isinstance(rec, dict) and rec.get("id"):
            out.append(rec)
    return out


def next_chunk(chat_id: Any, sid: str) -> dict:
    """다음에 장면으로 만들 대목 → {index, total, text}. 다 했으면 text 가 빈 문자열."""
    rec = load_state(chat_id, sid)
    chunks = split_chunks(text_of(chat_id, sid))
    done = max(0, int(rec.get("done") or 0))
    if done >= len(chunks):
        return {"index": done, "total": len(chunks), "text": "", "name": rec.get("name", "")}
    return {"index": done, "total": len(chunks), "text": chunks[done],
            "name": rec.get("name", "")}


def mark_done(chat_id: Any, sid: str, upto: int) -> dict:
    """어디까지 만들었는지 적는다. **뒤로는 가지 않는다** — 같은 대목을 두 번 만들지 않게."""
    rec = load_state(chat_id, sid)
    cur = max(0, int(rec.get("done") or 0))
    rec["done"] = max(cur, max(0, int(upto or 0)))
    vn_core.atomic_write_json(_state_path(chat_id, rec["id"]), rec)
    return rec


def reset(chat_id: Any, sid: str) -> dict:
    """처음부터 다시 — 글은 그대로 두고 진행만 되돌린다."""
    rec = load_state(chat_id, sid)
    rec["done"] = 0
    vn_core.atomic_write_json(_state_path(chat_id, rec["id"]), rec)
    return rec


def delete(chat_id: Any, sid: str) -> dict:
    """올린 글을 지운다 — 사람이 가져온 파일이므로 원본은 그쪽에 있다(보관하지 않는다)."""
    sid = _require_sid(sid)
    gone = 0
    for p in (_text_path(chat_id, sid), _state_path(chat_id, sid)):
        try:
            if p.is_file():
                p.unlink()
                gone += 1
        except OSError as exc:
            raise VNError(f"올린 글을 지우지 못했습니다: {exc}")
    if not gone:
        raise VNError(f"{sid} 올린 글이 없습니다.")
    return {"id": sid, "removed": gone}


def where() -> dict:
    """올린 글이 **실제로** 어디 사는가 — 화면이 경로째 보여 준다."""
    return {"path": str(DIR), "env": vn_core.PRIVATE_ENV, "error": PRIVATE_ERROR,
            "outside_repo": vn_core.ROOT not in DIR.parents and DIR != vn_core.ROOT}


def main(argv: list[str] | None = None) -> int:
    import argparse
    vn_core.console_guard()
    ap = argparse.ArgumentParser(description="올린 글(소설) 보관·나누기")
    ap.add_argument("--chat", default="", help="대화 id")
    ap.add_argument("--add", metavar="파일", help="이 대화에 글 파일 추가")
    a = ap.parse_args(argv)
    if a.add:
        rec = save(a.chat, Path(a.add).name, Path(a.add).read_bytes())
        print(json.dumps(rec, ensure_ascii=False))
    else:
        for rec in list_for(a.chat):
            print("%s  %-20s %6d자 · %d대목 중 %d 완료"
                  % (rec["id"], rec.get("name", ""), rec.get("chars", 0),
                     rec.get("chunks", 0), rec.get("done", 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
