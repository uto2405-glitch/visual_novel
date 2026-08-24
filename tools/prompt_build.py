#!/usr/bin/env python3
"""프롬프트 조립 — 장면 이미지 · 스토리 챗 · 인물 대화(페르소나) 프롬프트의 단일 출처.

역할 분담이 이 파일의 전부다:

  * **앵커(인물·장소 원문)는 코드가 조립한다** — 검사기 A6 를 구조적으로 보장하고,
    컷마다 얼굴·배경이 흔들리지 않게 한다.
  * **LLM 은 동작·구도 한 문장만 만든다** — 외모·장소를 다시 묘사하면 앵커와 충돌한다.

저장소 규약: **모델에 보내는 프롬프트 문자열은 prompt_build 와 vn_compose 에만 있다.**
HTTP 라우트(webapp)는 여기서 조립된 것을 넘기기만 한다 — 같은 프롬프트가 웹·CLI 로
갈라져 서로 다른 말을 하게 되는 것을 막는 경계다. 사용자가 가장 많이 마주하는 프롬프트인
**인물 페르소나**(말투 규칙·장기 기억·앨범 사진 규칙)도 그래서 여기 있다. local_llm 은
그 문자열을 서버에 실어 나르기만 하는 순수 전송 계층이고, 이제 이쪽을 되받지 않는다 —
프롬프트가 필요한 곳(webapp·CLI)은 **이 모듈을 직접 부른다**. 의존은 한 방향뿐이다:
local_llm ← prompt_build.

화풍 문자열의 단일 출처는 vn_core.visual_style(매니페스트 → 장면 → 기본값)이다.

Python 3.9+ · 표준 라이브러리만(로컬 LLM 호출은 local_llm 경유).
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_llm  # noqa: E402  (전송 계층 — 프롬프트는 이 파일이 만들고 저쪽은 보내기만 한다)
import talk_store  # noqa: E402  (대화 로그·대화 상대 결정의 단일 출처)
import vn_core  # noqa: E402

# 한국어 시간대 → 영어(이미지 AI 가 알아듣는 단어). 없는 값은 원문을 그대로 넘긴다.
TIME_EN = {"밤": "night", "낮": "daytime", "아침": "morning", "저녁": "evening",
           "노을": "sunset", "새벽": "dawn", "오후": "afternoon"}

STORYLINE_CHARS = 1500   # 컨텍스트에 싣는 스토리라인 길이 상한(토큰·비용 관리)
CONTEXT_SCENES = 40      # 컨텍스트에 싣는 장면 요약 수 상한

STORY_SYSTEM_HEAD = (
    "너는 비주얼 노벨/웹툰 스토리 기획 파트너다. 한국어로 간결하고 구체적으로 답한다.\n"
    "아래는 지금 작업 중인 작품의 현재 상태다. 이 설정과 이어지도록 제안하고, "
    "새 인물·장소를 만들 때만 새로 제안하라.\n\n")

_WEEKDAYS = "월화수목금토일"


def visual_style(sc: dict | None = None) -> str:
    """작품 화풍 — manifest.output.visual_style → 장면 visual_style → 기본 문구."""
    return vn_core.visual_style(None, sc)


def _read_story(name: str) -> str:
    """project/story/<name> 을 읽는다 — 없거나 못 읽으면 빈 문자열.

    스토리 문서가 없다고 챗이나 인물 대화가 멈춰서는 안 된다(작품 초기에는 늘 비어 있다).
    """
    try:
        return (vn_core.STORY / name).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""


def storyline_text() -> str:
    """project/story/storyline.md 원문 — 스토리 챗 컨텍스트에 그대로 싣는다."""
    return _read_story("storyline.md").strip()


def story_context() -> str:
    """스토리 챗이 '지금 이 작품'을 알고 답하도록 붙이는 요약 컨텍스트.

    작품 제목 · 등장인물 · 장소 · 현재 스토리라인 · 구성된 장면 목록을 한 덩어리로 만든다.
    (사람이 읽어도 이해되는 형태 그대로 — 모델이 이 형식을 가장 잘 따라 온다.)
    """
    mf = vn_core.load_manifest()
    out = []
    if str(mf.get("title", "")).strip():
        out.append(f"[작품] {mf['title']}")
    chars = [c for c in mf.get("characters", []) if isinstance(c, dict)]
    if chars:
        out.append("[등장인물] " + " / ".join(
            f"{c.get('character_id')} {c.get('name', '')}"
            + (f"({(c.get('profile') or {}).get('age', '')}세)"
               if (c.get('profile') or {}).get('age') else "")
            for c in chars))
    locs = [l for l in mf.get("locations", []) if isinstance(l, dict)]
    if locs:
        out.append("[장소] " + " / ".join(
            f"{l.get('location_id')} {l.get('name', '')}" for l in locs))
    sl = storyline_text()
    if sl:
        out.append("[현재 스토리라인]\n" + sl[:STORYLINE_CHARS])
    lines = []
    for _f, sc in vn_core.iter_scenes()[:CONTEXT_SCENES]:
        lines.append(f"- {sc.get('scene_id')} [{sc.get('status', '')}] "
                     f"{str(sc.get('purpose', ''))[:40]}")
    if lines:
        out.append("[구성된 장면]\n" + "\n".join(lines))
    return "\n".join(out)


def story_system_message() -> dict:
    """스토리 챗의 system 메시지 — 역할 지시 + 현재 작품 컨텍스트."""
    return {"role": "system", "content": STORY_SYSTEM_HEAD + story_context()}


def compose_image_prompt(sc: dict) -> str:
    """장면 dict → 이미지 프롬프트 문자열.

    LLM 응답이 비거나 이상해도 앵커·화풍·구도는 코드가 넣으므로 프롬프트가 무너지지 않는다.
    """
    mf = vn_core.load_manifest()
    chars = {c.get("character_id"): c for c in mf.get("characters", []) if isinstance(c, dict)}
    locs = {l.get("location_id"): l for l in mf.get("locations", []) if isinstance(l, dict)}
    ask = ("아래 장면을 그림으로 그릴 때의 '동작과 구도'만 영어 한 문장(20단어 이내)으로 써라. "
           "인물 외모나 장소 묘사는 쓰지 마라. 설명 없이 그 문장만 출력하라.\n"
           f"목적: {sc.get('purpose', '')}\n동작: {sc.get('action_beat', '')}\n"
           f"감정: {sc.get('emotion', '')}\n시간: {sc.get('time', '')}")
    action = local_llm.chat([{"role": "user", "content": ask}], temperature=0.4, max_tokens=120)
    action = " ".join(str(action).strip().splitlines()).strip().strip('"')[:220]
    cam = sc.get("camera", {}) if isinstance(sc.get("camera"), dict) else {}
    parts = [visual_style(sc) + ", portrait 2:3", f"{cam.get('shot', 'medium')} shot"]
    ids = [c for c in sc.get("characters", []) if c in chars]
    if ids:
        parts.append(chars[ids[0]].get("prompt_anchor", ""))
    parts.append(action)
    for cid in ids[1:]:
        parts.append("with " + str(chars[cid].get("prompt_anchor", "")))
    if sc.get("location_id") in locs:
        parts.append(locs[sc["location_id"]].get("prompt_anchor", ""))
    t = str(sc.get("time", "")).strip()
    if t:
        parts.append(TIME_EN.get(t, t))
    return ", ".join(str(p).strip() for p in parts if p and str(p).strip())


# ============================================================= 인물 대화 페르소나
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
def _memory_path(cid: str) -> Path:
    """기억 요약 파일 — 파일명 규칙은 대화 로그와 같은 곳(talk_store)에서만 정한다.

    예전에는 이 규칙이 cid 를 그대로 파일명에 쓰고 웹은 영숫자만 남겨서, 특수문자가
    섞인 character_id 에서는 서로 다른 파일을 보게 되어 '장기 기억'이 조용히 비었다.
    """
    return vn_core.STORY / f"memory_{talk_store.normalize_cid(cid)}.json"


def _load_memory(cid: str) -> dict:
    return vn_core.load_json_safe(_memory_path(cid), {})


def save_memory_summary(cid: str, summary: str, covered: int = 0) -> bool:
    """기억 요약 저장. 실패해도 대화는 계속되어야 하므로 조용히 False."""
    try:
        vn_core.atomic_write_json(_memory_path(cid),
                                  {"summary": str(summary).strip(), "covered": int(covered)})
        return True
    except (OSError, vn_core.VNError, TypeError, ValueError):
        return False


def memory_digest(cid: str, window: int = local_llm.TALK_WINDOW, limit: int = 8) -> str:
    """최근 window 개 창 밖으로 밀려난 대화를 짧은 기억으로 되살린다.

    여기서는 LLM 을 호출하지 않는다 — 서버가 꺼져 있어도 페르소나는 만들어져야 한다.
    저장된 요약(memory_<cid>.json)이 있으면 먼저 쓰고, 그 뒤 대화는 발췌로 잇는다.
    대화 로그는 talk_store 가 보장한다(파일이 없거나 깨져도 빈 목록).
    """
    msgs = talk_store.load_messages(cid)
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


def refresh_memory(cid: str | None = None, window: int = local_llm.TALK_WINDOW) -> bool:
    """창 밖 대화를 로컬 LLM 으로 요약해 저장한다. 서버가 꺼져 있으면 조용히 False."""
    try:
        cid = talk_store.resolve_cid(cid)      # 대화 상대 결정 규칙도 단일 출처
        if not cid:
            return False
        msgs = talk_store.load_messages(cid)
        old = msgs[:-window] if len(msgs) > window else []
        if len(old) < 4:
            return False
        body = "\n".join(f"{'상대' if m.get('role') == 'user' else '나'}: "
                         f"{str(m.get('content', ''))[:200]}" for m in old)
        out = local_llm.chat([{"role": "user", "content":
                               "다음은 연인 사이의 지난 대화야. 앞으로의 대화에서 기억해야 할 사실"
                               "(약속·취향·사건·감정)만 한국어 3문장 이내로 요약해. "
                               "설명이나 머리말 없이 요약만 써라.\n\n"
                               + body[-6000:]}], temperature=0.2, max_tokens=220)
        return save_memory_summary(cid, out, covered=len(old))
    except Exception:
        return False   # 요약은 부가 기능 — 실패가 대화를 막아서는 안 된다


# ------------------------------------------------------------- 앨범 사진
_PHOTO_TAG = re.compile(r"\[\s*사진\s*[:：]\s*(SCENE-\d+)\s*\]")
_PHOTO_REQ = re.compile(r"사진|앨범|찍은|셀카|셀피")
_PHOTO_WANT = re.compile(r"보여|보고\s*싶|봐|볼래|있어|있니|줘|보내")
_PHOTO_NEG = re.compile(r"없(네|어|다|는데|음|지|을)")


def album_list() -> list:
    """승인된 장면 이미지 = 인물의 '앨범'. [{scene_id, label, rel}].

    '완성된 컷인가'의 판정은 vn_core.is_deliverable 하나다 — 감상본·인화·앨범이 같은
    질문에 각자 답하면 인물이 "그 사진 없어" 라고 말하는 컷이 감상본에는 들어 있게 된다.
    """
    out = []
    for _f, sc in vn_core.iter_scenes():
        if not vn_core.is_deliverable(sc):
            continue
        label = str(sc.get("purpose") or sc.get("action_beat") or sc.get("scene_id") or "")
        out.append({"scene_id": sc.get("scene_id"), "label": label[:70],
                    "rel": vn_core.selected_of(sc)})
    return out


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
        raise vn_core.VNError("매니페스트에 캐릭터가 없습니다. 먼저 작품을 세팅하세요.")
    talk = mf.get("talk") if isinstance(mf.get("talk"), dict) else {}
    # 대화 상대 결정(요청값 > manifest.talk > 첫 캐릭터)은 talk_store 하나에만 있다 —
    # 웹과 CLI 가 서로 다른 인물과 대화하면 로그·기억 파일이 갈린다.
    cid = talk_store.resolve_cid(character_id) or chars[0].get("character_id")
    ch = next((c for c in chars if c.get("character_id") == cid), chars[0])
    prof = ch.get("profile") if isinstance(ch.get("profile"), dict) else {}
    name = ch.get("name") or cid
    relationship = talk.get("relationship", "다정한 여자친구")

    traits = ", ".join(str(prof.get(k, "")) for k in ("age", "gender_presentation", "hair", "eyes", "wardrobe")
                       if prof.get(k))
    props = ", ".join(prof.get("signature_props", []) or [])
    personality = str(prof.get("personality", "") or "").strip()
    speech = str(prof.get("speech_style", "") or "").strip()
    story = _strip_meta_sections(_read_story("storyline.md"))
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
