#!/usr/bin/env python3
"""로컬 LLM 클라이언트 — 캐릭터와 '실제 대화'하기 위한 경로.

C:\\Users\\USER\\claude\\local_llm 의 llama.cpp 서버(OpenAI 호환, 기본 http://127.0.0.1:8080/v1)에 붙는다.
xai_client 와 별개(그록은 연출/프롬프트용, 로컬 LLM 은 인물 대화용). 키 불필요(로컬).

설정 우선순위: 환경변수 LOCAL_LLM_URL > manifest.talk.base_url > 기본값.

주소 규칙(중요): 인물 대화 전문이 나가는 통로이므로 **루프백·사설망만** 허용한다.
scheme 이 https 라고 통과시키지 않는다 — 그 한 줄이 오타 하나로 대화 전체를 외부
호스트에 넘길 수 있는 유일한 구멍이었다.
"""
from __future__ import annotations

import ipaddress
import json
import re
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

try:                       # 대화 로그 경로·입출력의 단일 출처(웹 스튜디오와 공유)
    import talk_store      # noqa: E402
except ImportError:        # 아직 없으면 같은 규칙(safe_slug)으로 직접 읽는다
    talk_store = None      # type: ignore[assignment]

ROOT = vn_core.ROOT
MANIFEST = vn_core.MANIFEST
STORY_DIR = vn_core.STORY
DEFAULT_URL = "http://127.0.0.1:8080/v1"
TIMEOUT = 120
TALK_WINDOW = 16   # 서버가 모델에 넘기는 최근 대화 수 — 그 밖의 맥락은 기억 요약으로 유지한다
# 이름으로 허용하는 것은 루프백 별칭뿐. 그 외 호스트명은 DNS 가 어디로든 향할 수 있어 거부한다.
_LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_WEEKDAYS = "월화수목금토일"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())


def base_url() -> str:
    env = os.environ.get("LOCAL_LLM_URL", "").strip()
    if env:
        return env.rstrip("/")
    talk = vn_core.load_manifest().get("talk")
    u = talk.get("base_url", "") if isinstance(talk, dict) else ""
    if isinstance(u, str) and u.strip():
        return u.strip().rstrip("/")
    return DEFAULT_URL


_warned: set[str] = set()


def _warn_once(msg: str) -> None:
    """같은 경고를 매 요청마다 찍지 않는다(대화 중 화면이 경고로 덮이지 않게)."""
    if msg in _warned:
        return
    _warned.add(msg)
    print(f"경고: {msg}", file=sys.stderr)


def _validate(url: str) -> None:
    """대화가 나갈 수 있는 주소를 좁힌다 — 루프백 IP·localhost 는 통과, 사설망은 경고 후 통과.

    공인 IP 와 임의 호스트명은 거부한다. 인물 대화는 사용자의 사적 자산이라
    '이 PC 안'을 벗어나는 순간을 최소한 눈에 보이게 만든다.
    """
    u = urllib.parse.urlparse(str(url or ""))
    host = (u.hostname or "").strip().lower()
    if u.scheme not in ("http", "https") or not host:
        raise VNError(f"로컬 LLM base_url 형식이 올바르지 않습니다({url}). "
                      "예: http://127.0.0.1:8080/v1")
    if host in _LOOPBACK_NAMES:
        return
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise VNError(f"로컬 LLM base_url 의 호스트 '{host}' 는 허용되지 않습니다 — "
                      "127.0.0.1 같은 루프백 주소나 사설망 IP 만 쓸 수 있습니다.")
    if ip.is_loopback:
        return
    if ip.is_private:
        _warn_once(f"로컬 LLM 주소 {host} 는 루프백이 아닙니다(사설망) — "
                   "인물 대화가 이 PC 밖의 기기로 전송됩니다.")
        return
    raise VNError(f"로컬 LLM base_url 이 안전하지 않습니다({url}). 로컬/사설망만 허용합니다.")


def status() -> dict:
    """서버가 떠 있고 모델이 로드됐는지."""
    url = base_url()
    try:
        _validate(url)
        req = urllib.request.Request(url + "/models")
        with _OPENER.open(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
        return {"up": True, "url": url, "models": models}
    except Exception as exc:
        return {"up": False, "url": url, "error": str(exc)}


def chat(messages: list[dict], temperature: float = 0.8, max_tokens: int = 320) -> str:
    """대화 메시지 → 응답 텍스트. 실패는 RuntimeError(사유 포함)."""
    url = base_url()
    _validate(url)
    body = json.dumps({"messages": messages, "temperature": temperature,
                       "max_tokens": max_tokens, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise VNError(f"로컬 LLM HTTP {e.code} — 서버/모델 상태를 확인하세요.")
    except urllib.error.URLError as e:
        raise VNError(f"로컬 LLM 에 연결할 수 없습니다({e.reason}). "
                      "local_llm/runtime/serve.ps1 로 서버를 켜세요.")
    try:
        data = json.loads(raw.decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, UnicodeDecodeError):
        raise VNError("로컬 LLM 응답 형식이 예상과 다릅니다.")
    if not isinstance(content, str):
        raise VNError("로컬 LLM 응답에 텍스트가 없습니다.")
    return content.strip()


# ------------------------------------------------------------- 인물 페르소나
def _strip_meta_sections(md: str) -> str:
    """'제작 노트'·'표기 규약' 같은 메타 절을 걷어낸다 — 인물은 제작 지시를 알면 안 된다."""
    out, skip_level = [], 0
    for line in md.splitlines():
        s = line.lstrip()
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            if skip_level and level <= skip_level:
                skip_level = 0
            if not skip_level and ("제작" in s or "규약" in s):
                skip_level = level
        if not skip_level:
            out.append(line)
    return "\n".join(out).strip()


def _clip(text: str, limit: int) -> str:
    """줄 경계에서 자른다 — 프롬프트에 문장이 반쯤 잘린 채 들어가지 않게."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return (cut[:cut.rfind("\n")] if "\n" in cut else cut).rstrip()


def _read_story(name: str) -> str:
    """project/story/<name> 을 읽는다 — 없거나 못 읽으면 빈 문자열(대화는 계속돼야 한다)."""
    try:
        return (STORY_DIR / name).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""


def _storyline() -> str:
    return _strip_meta_sections(_read_story("storyline.md"))


def _section(md: str, key: str) -> str:
    """제목에 key 가 든 절의 본문(하위 절 포함)을 뽑는다."""
    out, level = [], 0
    for line in md.splitlines():
        s = line.lstrip()
        if s.startswith("#"):
            head = len(s) - len(s.lstrip("#"))
            if level and head <= level:      # 다음 인물 절에서 종료
                break
            if not level and key in s:
                level = head
                continue
        if level:
            out.append(line)
    return "\n".join(out).strip()


def _character_bible(cid: str, name: str = "") -> str:
    """캐릭터 바이블에서 해당 인물의 절만 뽑는다(취향·기념일·기억). 없으면 빈 문자열.

    id 로 먼저 찾는다 — 이름('나' 같은 한 글자)이 다른 제목에 우연히 걸리는 것을 막는다.
    """
    md = _strip_meta_sections(_read_story("character_bible.md"))
    if not md:
        return ""
    for key in (cid, name):
        if key and (found := _section(md, key)):
            return found
    return ""


def _now_block(now: datetime | None = None) -> str:
    """현재 시각·요일 — 시간대에 맞는 인사와 반응을 하게 한다."""
    now = now or datetime.now()
    h = now.hour
    if h < 5:
        part = "새벽"
    elif h < 11:
        part = "아침"
    elif h < 14:
        part = "점심때"
    elif h < 18:
        part = "오후"
    elif h < 21:
        part = "저녁"
    else:
        part = "밤"
    return (f"\n[지금] {now:%Y년 %m월 %d일} {_WEEKDAYS[now.weekday()]}요일 {now:%H시 %M분}, {part}이야.\n"
            "- 지금 시간대에 맞게 인사하고 반응해(새벽이면 왜 안 자냐고, 아침이면 잘 잤냐고 묻는 식).\n"
            "- 시각을 그대로 읊지 말고 말 속에 자연스럽게 녹여.\n")


# ------------------------------------------------------------- 장기 기억(요약)
def _talk_path(cid: str) -> Path:
    """대화 로그 파일 — talk_store 가 있으면 그 규칙을 그대로 따른다.

    예전에는 이 함수만 cid 를 그대로 파일명에 썼고 웹은 영숫자만 남겼다. 그래서
    특수문자가 섞인 character_id 에서는 서로 다른 파일을 보게 되어 '장기 기억'이
    조용히 비었다. 규칙은 한 곳(talk_store, 없으면 safe_slug)에서만 정한다.
    """
    if talk_store is not None:
        try:
            return Path(talk_store.talk_path(cid))
        except Exception:
            pass       # 폴백 규칙으로 계속 — 기억이 비어도 대화 자체는 막지 않는다
    return STORY_DIR / f"talk_{vn_core.safe_slug(cid, 'CHAR')}.json"


def _memory_path(cid: str) -> Path:
    return STORY_DIR / f"memory_{vn_core.safe_slug(cid, 'CHAR')}.json"


def _talk_messages(cid: str) -> list:
    """저장된 대화에서 user/assistant 발화만. 파일이 없거나 깨져도 빈 목록."""
    if talk_store is not None:
        try:
            msgs = talk_store.load_messages(cid)
        except Exception:
            msgs = []
    else:
        msgs = vn_core.load_json_safe(_talk_path(cid), {}).get("messages", [])
    if not isinstance(msgs, list):
        return []
    return [m for m in msgs if isinstance(m, dict) and m.get("role") in ("user", "assistant")]


def _load_memory(cid: str) -> dict:
    return vn_core.load_json_safe(_memory_path(cid), {})


def save_memory_summary(cid: str, summary: str, covered: int = 0) -> bool:
    """기억 요약 저장. 실패해도 대화는 계속되어야 하므로 조용히 False."""
    try:
        vn_core.atomic_write_json(_memory_path(cid),
                                  {"summary": str(summary).strip(), "covered": int(covered)})
        return True
    except (OSError, VNError, TypeError, ValueError):
        return False


def memory_digest(cid: str, window: int = TALK_WINDOW, limit: int = 8) -> str:
    """최근 window 개 창 밖으로 밀려난 대화를 짧은 기억으로 되살린다.

    여기서는 LLM 을 호출하지 않는다 — 서버가 꺼져 있어도 페르소나는 만들어져야 한다.
    저장된 요약(memory_<cid>.json)이 있으면 먼저 쓰고, 그 뒤 대화는 발췌로 잇는다.
    """
    msgs = _talk_messages(cid)
    old = msgs[:-window] if len(msgs) > window else []
    if not old:
        return ""
    mem = _load_memory(cid)
    summary = str(mem.get("summary", "")).strip()
    covered = int(mem.get("covered", 0)) if isinstance(mem.get("covered"), int) else 0
    parts = [summary] if summary else []
    for m in old[max(covered, 0):][-limit:]:
        text = " ".join(str(m.get("content", "")).split())
        if len(text) < 2:
            continue
        parts.append(f"- {'상대' if m.get('role') == 'user' else '나'}: {text[:60]}")
    if not parts:
        return ""
    return (f"\n[지난 대화 기억] 최근 대화창 밖의 일이지만 너는 기억하고 있어 (이전 대화 {len(old)}개):\n"
            + "\n".join(parts) +
            "\n- 먼저 꺼내 나열하지 말고, 이야기가 자연스럽게 닿을 때만 언급해.\n")


def refresh_memory(cid: str | None = None, window: int = TALK_WINDOW) -> bool:
    """창 밖 대화를 로컬 LLM 으로 요약해 저장한다. 서버가 꺼져 있으면 조용히 False."""
    try:
        if not cid:
            mf = vn_core.load_manifest()
            talk = mf.get("talk") if isinstance(mf.get("talk"), dict) else {}
            chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
            cid = talk.get("character_id") or (chars[0].get("character_id") if chars else "")
        if not cid:
            return False
        msgs = _talk_messages(cid)
        old = msgs[:-window] if len(msgs) > window else []
        if len(old) < 4:
            return False
        body = "\n".join(f"{'상대' if m.get('role') == 'user' else '나'}: "
                         f"{str(m.get('content', ''))[:200]}" for m in old)
        out = chat([{"role": "user", "content":
                     "다음은 연인 사이의 지난 대화야. 앞으로의 대화에서 기억해야 할 사실"
                     "(약속·취향·사건·감정)만 한국어 3문장 이내로 요약해. 설명이나 머리말 없이 요약만 써라.\n\n"
                     + body[-6000:]}], temperature=0.2, max_tokens=220)
        return save_memory_summary(cid, out, covered=len(old))
    except Exception:
        return False   # 요약은 부가 기능 — 실패가 대화를 막아서는 안 된다


def _load_scenes() -> list:
    out = []
    d = vn_core.SCENES
    for f in sorted(d.glob("SCENE-*.json")) if d.exists() else []:
        sc = vn_core.load_json_safe(f, {})
        if sc:
            out.append(sc)
    return out


def album_list() -> list:
    """승인된 장면 이미지 = 인물의 '앨범'. [{scene_id, label, rel}]."""
    out = []
    for sc in _load_scenes():
        if sc.get("status") != "APPROVED":
            continue
        assets = sc.get("assets") if isinstance(sc.get("assets"), dict) else {}
        rel = str(assets.get("selected_image", "") or "").strip()
        if not rel:
            continue
        label = str(sc.get("purpose") or sc.get("action_beat") or sc.get("scene_id") or "")
        out.append({"scene_id": sc.get("scene_id"), "label": label[:70], "rel": rel})
    return out


_PHOTO_TAG = re.compile(r"\[\s*사진\s*[:：]\s*(SCENE-\d+)\s*\]")
_PHOTO_REQ = re.compile(r"사진|앨범|찍은|셀카|셀피")
_PHOTO_WANT = re.compile(r"보여|보고\s*싶|봐|볼래|있어|있니|줘|보내")
_PHOTO_NEG = re.compile(r"없(네|어|다|는데|음|지|을)")


def _match_album(text: str, album: dict):
    """요청 텍스트와 앨범 라벨의 한글 토큰 겹침으로 가장 맞는 사진을 고른다(폴백)."""
    toks = [t for t in re.split(r"[^가-힣A-Za-z0-9]+", text) if len(t) >= 2]
    best, score = None, 0
    for sid, info in album.items():
        s = sum(1 for t in toks if t in (info.get("label", "") or ""))
        if s > score:
            best, score = sid, s
    return best if score >= 1 else None


def resolve_photos(reply: str, album: dict, last_user: str = ""):
    """응답에서 [사진:ID] 태그를 뽑아 실제 앨범에 있는 것만 사진으로, 텍스트는 정리해서 반환.

    - '없어/없네'라고 말하면 사진 억제(모순 방지).
    - 명시적 사진 요청인데 모델이 태그를 빠뜨렸으면 라벨 키워드로 폴백 매칭.
    반환: (clean_text, [{scene_id, rel, caption}])
    """
    photos = []

    def _grab(m):
        sid = m.group(1)
        info = album.get(sid)
        if info and len(photos) < 1:
            photos.append({"scene_id": sid, "rel": info["rel"], "caption": info.get("label", "")})
        return ""

    clean = _PHOTO_TAG.sub(_grab, reply).strip() or reply.strip()
    if photos and _PHOTO_NEG.search(clean):
        photos = []
    if (not photos and album and _PHOTO_REQ.search(last_user)
            and _PHOTO_WANT.search(last_user) and not _PHOTO_NEG.search(clean)):
        best = _match_album(last_user, album)
        if best:
            photos.append({"scene_id": best, "rel": album[best]["rel"],
                           "caption": album[best].get("label", "")})
    return clean, photos


def persona_prompt(character_id: str | None = None) -> tuple[str, dict]:
    """매니페스트의 캐릭터 기준정보 + 스토리로 인물 대화용 시스템 프롬프트를 만든다."""
    mf = vn_core.load_manifest()
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    if not chars:
        raise VNError("매니페스트에 캐릭터가 없습니다. 먼저 작품을 세팅하세요.")
    talk = mf.get("talk") if isinstance(mf.get("talk"), dict) else {}
    cid = character_id or talk.get("character_id") or chars[0].get("character_id")
    ch = next((c for c in chars if c.get("character_id") == cid), chars[0])
    prof = ch.get("profile") if isinstance(ch.get("profile"), dict) else {}
    name = ch.get("name") or cid
    relationship = talk.get("relationship", "다정한 여자친구")

    traits = ", ".join(str(prof.get(k, "")) for k in ("age", "gender_presentation", "hair", "eyes", "wardrobe")
                       if prof.get(k))
    props = ", ".join(prof.get("signature_props", []) or [])
    personality = str(prof.get("personality", "") or "").strip()
    speech = str(prof.get("speech_style", "") or "").strip()
    story = _storyline()
    story_line = f"\n[함께한 이야기]\n{_clip(story, 1600)}\n" if story else ""
    bible = _character_bible(cid, name)
    bible_line = f"\n[너에 대한 기록 — 전부 실제 네 기억이야]\n{_clip(bible, 1800)}\n" if bible else ""

    album = album_list()
    if album:
        lines = "\n".join(f"- {a['scene_id']}: {a['label']}" for a in album)
        album_block = (
            "\n[네 앨범 사진] — 아래 목록의 사진만 보여줄 수 있어:\n" + lines +
            "\n[사진 규칙 — 엄격히]\n"
            "- 위 목록에 있고, 상대가 찾는 것과 실제로 맞는 사진일 때만, 답장 맨 끝에 [사진:SCENE-ID] 를 붙여.\n"
            "- 상대가 찾는 사진이 목록에 없으면: '그 사진은 지금 없네~' 처럼 말하고 **절대 태그를 넣지 마**.\n"
            "- '없어/없네'라고 말하는 답장에는 어떤 [사진:] 태그도 넣지 마(모순 금지).\n"
            "- 한 번에 한 장만. 매 답장마다 보내지 말고 정말 어울릴 때만.\n")
    else:
        album_block = ("\n[사진] 지금은 보여줄 수 있는 사진이 없어. 사진을 찾으면 "
                       "'아직 사진이 없네~' 처럼 자연스럽게 말하고, 사진 태그는 쓰지 마.\n")

    sys_msg = (
        f"너는 '{name}'라는 인물이야. 지금부터 끝까지 '{name}' 본인으로서 1인칭으로 자연스럽게 대화해.\n"
        f"[너의 모습] {traits}" + (f" / 아끼는 것: {props}" if props else "") + "\n"
        + (f"[너의 성격] {personality}\n" if personality else "")
        + f"[관계] 상대는 너의 {relationship}. 편하고 다정한 반말로, 실제 연인처럼 대화해.\n"
        "[말투 규칙]\n"
        + (f"- {speech}\n" if speech else "")
        + "- 한국어로, 1~3문장의 짧고 자연스러운 구어체. 이모티콘은 가끔만.\n"
        "- 너는 사람이야. 'AI', '언어모델', '도울 수 있어' 같은 표현 절대 금지.\n"
        "- 설명하거나 나열하지 말고, 감정과 리액션이 있는 진짜 대화를 해.\n"
        "- 가끔 먼저 질문하거나 장난도 치면서 대화를 이어가.\n"
        + _now_block() + bible_line + story_line + memory_digest(cid) + album_block
    )
    meta_album = {a["scene_id"]: {"rel": a["rel"], "label": a["label"]} for a in album}
    return sys_msg, {"character_id": cid, "name": name, "album": meta_album}


def main() -> int:
    st = status()
    print(f"로컬 LLM: {'ON' if st['up'] else 'OFF'} ({st['url']})")
    if not st["up"]:
        print(f"  {st.get('error', '')}")
        print("  → C:\\Users\\USER\\claude\\local_llm\\runtime\\serve.ps1 로 서버를 켜세요.")
        return 1
    print(f"  모델: {', '.join(m for m in st['models'] if m) or '(미표시)'}")
    if len(sys.argv) > 1 and sys.argv[1] == "--memory":   # 지난 대화 요약 갱신(장기 기억)
        ok = refresh_memory(sys.argv[2] if len(sys.argv) > 2 else None)
        print("기억 요약을 갱신했습니다." if ok else "요약할 지난 대화가 없거나 요약에 실패했습니다.")
        return 0
    if len(sys.argv) > 1:
        try:
            sysmsg, meta = persona_prompt()
            reply = chat([{"role": "system", "content": sysmsg},
                          {"role": "user", "content": " ".join(sys.argv[1:])}])
        except VNError as exc:
            print(f"오류: {exc}")
            return 1
        print(f"\n{meta['name']}: {reply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
