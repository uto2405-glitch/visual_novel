#!/usr/bin/env python3
"""고유 캐릭터 — 모든 대화가 함께 쓰는 인물 서랍.

왜 매니페스트로는 부족한가: ``project/manifest.json`` 의 인물은 **지금 올라와 있는
작품의 것**이고, 작품은 대화마다 갈아 끼운다(:mod:`works`). 그런데 사람이 공들여 만든
인물은 작품보다 오래 산다 — 고양이 이야기에서 만든 인물을 다음 단편에서도 쓰고 싶다.
그래서 인물은 ``project/characters/`` 에 따로 둔다. **works 가 바꾸지 않는 자리라서,
어느 대화를 열든 같은 서랍이 보인다.**

매니페스트와의 관계는 사본이 아니라 **투영**이다(:func:`sync_manifest`).
서랍이 원본이고, 매니페스트에는 그 사본이 얹힌다. 왜 얹어야 하느냐면 판정자
``check_protocol`` 의 A2 가 **장면이 가리키는 인물 id 는 매니페스트에 있어야 한다**고
요구하는데, 그 파일은 고칠 수 없기 때문이다.

투영은 **더하기만 한다. 빼지 않는다.** 매니페스트는 모든 작품이 함께 쓰므로, 여기서 한
줄을 지우면 그 인물을 쓰던 **다른 작품의 장면이 통째로 A2 FAIL** 이 된다 — 사람은 건드린
적도 없는 작품이 왜 빨간지 알 수 없다. 그래서 서랍에서 지운 인물도 매니페스트에는 남는다.

얼굴 고정에 대하여 — 지금 이 저장소가 가진 레버는 둘뿐이다:
  ``prompt_tags`` (그 인물의 앵커 **바로 앞**에 붙는 태그 줄) 와 ``prompt_anchor`` (원문).
  이 둘을 **모든 작품에서 글자 하나 다르지 않게** 유지하는 것이 이 모듈이 하는 일이다.
  사진을 등록하면 그림 엔진이 그 얼굴을 쓸 수 있다(ComfyUI + PhotoMaker). 다만
  **쓸 수 있는지는 이 모듈이 답하지 않는다** — 엔진마다 다르고, 모델 파일이 있어야 하기
  때문이다. 그 질문의 답은 :func:`image_gen.face_state` 한 곳에만 있다. 답이 두 곳에
  있으면 반드시 갈라지고, 그때 사람은 '사진을 쓴다' 는 화면을 보면서 얼굴이 흔들리는
  그림을 받는다.

Python 3.9+ · 표준 라이브러리만. vn_core 하나만 본다(계층 1).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vn_core  # noqa: E402
from vn_core import VNError  # noqa: E402

DIR = vn_core.PROJECT / "characters"          # works 가 바꾸지 않는 자리 = 모든 대화 공유
REFS = DIR / "refs"                           # 사람이 올린 참고 사진 (커밋 금지 — .gitignore)
ARCHIVE = vn_core.PROJECT / "characters_deleted"
ID_RE = re.compile(r"^OC-(\d{3,})$")

# 사람이 올릴 수 있는 것 — 그림 파일만, 그리고 **머리 바이트로 판정한다.**
# 확장자는 사람이 바꿀 수 있고(.exe → .png), 이 파일들은 나중에 웹으로 되돌려준다.
_MAGIC = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"),
          (b"RIFF", ".webp"), (b"GIF87a", ".gif"), (b"GIF89a", ".gif"))
REF_MAX_BYTES = 8 * 1024 * 1024               # 한 장 8MB — 폰 사진 한 장이 넉넉히 들어간다
REF_MAX_COUNT = 8                             # 한 인물당 참고 사진 수

# 매니페스트 인물과 **같은 모양**으로 저장한다 — 투영이 단순 복사가 되도록.
_PROFILE_KEYS = ("age", "gender_presentation", "hair", "eyes", "build", "wardrobe",
                 "signature_props", "personality", "speech_style")
_MANIFEST_KEYS = ("character_id", "name", "version", "profile", "reference_images",
                  "prompt_anchor", "prompt_tags", "wardrobe_default", "wardrobe_variants")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path(cid: str) -> Path:
    return DIR / (cid + ".json")


def is_id(cid: Any) -> bool:
    return bool(ID_RE.match(str(cid or "").strip()))


def _require_id(cid: Any) -> str:
    s = str(cid or "").strip()
    if not is_id(s):
        raise VNError("고유 캐릭터 id 형식이 아닙니다: %r (OC-001 처럼 적습니다)" % s)
    return s


def _load(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VNError("%s 을 읽지 못했습니다: %s" % (path.name, exc))
    if not isinstance(obj, dict):
        raise VNError("%s 이 인물 기록이 아닙니다." % path.name)
    return obj


def list_all() -> list[dict]:
    """서랍 전체를 id 순으로. 깨진 파일은 **건너뛰지 않고 표시해서** 돌려준다.

    조용히 건너뛰면 사람은 인물이 사라진 줄 알고 다시 만들고, 그러면 같은 사람이 둘이 된다.
    """
    out: list[dict] = []
    if not DIR.is_dir():
        return out
    for p in sorted(DIR.glob("OC-*.json")):
        try:
            oc = _load(p)
        except VNError as exc:
            out.append({"character_id": p.stem, "name": p.stem, "broken": str(exc)})
            continue
        oc.setdefault("character_id", p.stem)
        out.append(oc)
    return out


def get(cid: str) -> dict:
    cid = _require_id(cid)
    p = _path(cid)
    if not p.is_file():
        raise VNError("%s 인물이 서랍에 없습니다." % cid)
    return _load(p)


def exists(cid: Any) -> bool:
    return is_id(cid) and _path(str(cid).strip()).is_file()


def _next_id() -> str:
    """서랍에 있는 것 + **보관소에 있는 것**보다 큰 번호.

    지운 인물의 번호를 다시 쓰면, 보관소에서 되살렸을 때 두 사람이 같은 id 를 갖는다.
    """
    top = 0
    for base in (DIR, ARCHIVE):
        if not base.is_dir():
            continue
        for p in base.rglob("OC-*.json"):
            m = ID_RE.match(p.stem)
            if m:
                top = max(top, int(m.group(1)))
    return "OC-%03d" % (top + 1)


def _clean_tags(raw: Any) -> list[str]:
    out, seen = [], set()
    for t in (raw if isinstance(raw, list) else str(raw or "").split(",")):
        tag = " ".join(str(t or "").split()).strip(" ,")
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def _clean_profile(raw: Any) -> dict:
    src = raw if isinstance(raw, dict) else {}
    prof: dict = {}
    for k in _PROFILE_KEYS:
        v = src.get(k)
        if k == "signature_props":
            prof[k] = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
        else:
            prof[k] = " ".join(str(v or "").split())
    return prof


def create(name: str, *, profile: Any = None, prompt_anchor: str = "",
           prompt_tags: Any = None, source_chat: str = "", notes: str = "") -> dict:
    """새 인물 한 명. id 는 이 함수만 붙인다(부르는 쪽이 번호를 세지 않는다).

    이름은 비울 수 없다 — 이름 없는 인물은 목록에서 고를 수가 없고, 매칭 화면에서
    사람이 무엇을 고르는지 모른 채 고르게 된다.
    """
    nm = " ".join(str(name or "").split())
    if not nm:
        raise VNError("인물 이름이 비어 있습니다.")
    DIR.mkdir(parents=True, exist_ok=True)
    cid = _next_id()
    oc = {
        "character_id": cid,
        "name": nm,
        "version": 1,
        "profile": _clean_profile(profile),
        "reference_images": [],
        "prompt_anchor": " ".join(str(prompt_anchor or "").split()),
        "prompt_tags": _clean_tags(prompt_tags),
        "wardrobe_default": "",
        "wardrobe_variants": [],
        "notes": str(notes or "")[:1000],
        "source_chat": str(source_chat or ""),
        "created": _now(),
        "updated": _now(),
    }
    vn_core.atomic_write_json(_path(cid), oc)
    return oc


EDITABLE = ("name", "profile", "prompt_anchor", "prompt_tags",
            "wardrobe_default", "wardrobe_variants", "notes")


def update(cid: str, fields: dict) -> dict:
    """적힌 칸만 고친다. ``character_id`` · ``reference_images`` 는 이 경로로 바뀌지 않는다.

    id 가 바뀌면 그 인물을 가리키던 장면이 전부 미아가 되고, 참고 사진 목록은 파일과
    한 쌍이라 :func:`add_reference` 만이 만든다.
    """
    cid = _require_id(cid)
    oc = get(cid)
    given = fields if isinstance(fields, dict) else {}
    bad = [k for k in given if k not in EDITABLE]
    if bad:
        raise VNError("여기서 고칠 수 없는 칸입니다: %s (고칠 수 있는 칸: %s)"
                      % (", ".join(sorted(bad)), ", ".join(EDITABLE)))
    for k, v in given.items():
        if k == "profile":
            oc["profile"] = _clean_profile(v)
        elif k == "prompt_tags":
            oc["prompt_tags"] = _clean_tags(v)
        elif k == "name":
            nm = " ".join(str(v or "").split())
            if not nm:
                raise VNError("인물 이름은 비울 수 없습니다.")
            oc["name"] = nm
        elif k == "notes":
            oc["notes"] = str(v or "")[:1000]
        else:
            oc[k] = v
    oc["updated"] = _now()
    vn_core.atomic_write_json(_path(cid), oc)
    return oc


def delete(cid: str) -> dict:
    """서랍에서 내린다 — **버리지 않고** ``project/characters_deleted/`` 로 옮긴다.

    매니페스트의 사본은 **그대로 둔다**(:func:`sync_manifest` 참조). 지워 버리면 그 인물이
    나오는 다른 작품의 장면이 A2 FAIL 이 되는데, 사람은 그 작품을 건드린 적이 없다.
    """
    cid = _require_id(cid)
    src = _path(cid)
    if not src.is_file():
        raise VNError("%s 인물이 서랍에 없습니다." % cid)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    home = ARCHIVE / ("%s_%s" % (stamp, cid))
    home.mkdir(parents=True, exist_ok=True)
    src.replace(home / src.name)
    moved = 0
    folder = REFS / cid
    if folder.is_dir():
        moved = sum(1 for _ in folder.rglob("*") if _.is_file())
        try:
            folder.replace(home / "refs")
        except OSError:
            moved = 0       # 사진을 못 옮겨도 인물 기록은 이미 보관됐다
    return {"character_id": cid, "archived_to": home.name, "refs": moved}


# ------------------------------------------------------------------ 참고 사진
def ref_path(cid: str, rel: str) -> Path | None:
    """기록된 사진 경로 → **디스크의 실제 파일.** 밖으로 나가는 길은 없다.

    기록된 문자열(``project/characters/refs/OC-001/x.png``)을 저장소 뿌리에 그대로 이어
    붙이면 안 된다. 두 가지가 한꺼번에 깨진다: 서랍 자리를 옮기면 조용히 엉뚱한 곳을
    가리키고(지우기가 말없이 실패한다), 그 문자열은 **웹에서 들어온 값**이라
    ``../../tools/vn_core.py`` 한 줄이면 저장소 파일을 가리킨다.

    그래서 파일 이름 한 조각만 취하고, 나머지 길은 이 모듈이 아는 ``REFS`` 로 만든다.
    """
    name = str(rel or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in (".", "..") or ":" in name:
        return None
    return REFS / _require_id(cid) / name


def _ext_of(data: bytes) -> str:
    for head, ext in _MAGIC:
        if data.startswith(head):
            if ext == ".webp" and data[8:12] != b"WEBP":
                continue
            return ext
    return ""


def add_reference(cid: str, data: bytes, label: str = "") -> dict:
    """사람이 자기 기기에서 고른 사진 한 장을 그 인물에 붙인다.

    **머리 바이트로 그림인지 본다** — 확장자는 믿지 않는다. 이 파일은 나중에 웹으로 다시
    나가므로, 그림이 아닌 것을 그림인 척 저장하면 그 경로가 임의 파일 배달로 변한다.
    """
    cid = _require_id(cid)
    oc = get(cid)
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise VNError("사진이 비어 있습니다.")
    if len(data) > REF_MAX_BYTES:
        raise VNError("사진이 너무 큽니다 (%.1fMB) — %dMB 까지 받습니다."
                      % (len(data) / 1048576.0, REF_MAX_BYTES // 1048576))
    ext = _ext_of(bytes(data[:16]))
    if not ext:
        raise VNError("그림 파일이 아닙니다 (PNG·JPG·WEBP·GIF 만 받습니다).")
    have = oc.get("reference_images") if isinstance(oc.get("reference_images"), list) else []
    if len(have) >= REF_MAX_COUNT:
        raise VNError("참고 사진은 한 인물당 %d장까지입니다." % REF_MAX_COUNT)
    folder = REFS / cid
    folder.mkdir(parents=True, exist_ok=True)
    name = "%s_%03d%s" % (datetime.now().strftime("%Y%m%d_%H%M%S"), len(have) + 1, ext)
    vn_core.atomic_write_bytes(folder / name, bytes(data))
    rel = "project/characters/refs/%s/%s" % (cid, name)
    have.append(rel)
    oc["reference_images"] = have
    if label:
        labels = oc.get("reference_labels")
        if not isinstance(labels, dict):
            labels = {}
        labels[rel] = str(label)[:120]
        oc["reference_labels"] = labels
    oc["updated"] = _now()
    vn_core.atomic_write_json(_path(cid), oc)
    return {"character_id": cid, "file": rel, "count": len(have)}


def remove_reference(cid: str, rel: str) -> dict:
    """사진 한 장을 뗀다. 목록에 없는 경로는 거절한다 — 경로가 곧 삭제 대상이기 때문이다."""
    cid = _require_id(cid)
    oc = get(cid)
    have = oc.get("reference_images") if isinstance(oc.get("reference_images"), list) else []
    want = str(rel or "").strip()
    if want not in have:
        raise VNError("그 사진은 이 인물의 목록에 없습니다.")
    have = [x for x in have if x != want]
    oc["reference_images"] = have
    labels = oc.get("reference_labels")
    if isinstance(labels, dict):
        labels.pop(want, None)
    oc["updated"] = _now()
    vn_core.atomic_write_json(_path(cid), oc)
    gone = False
    try:
        p = ref_path(cid, want)
        if p is not None and p.is_file():
            p.unlink()
            gone = True
    except OSError:
        pass
    return {"character_id": cid, "removed": want, "file_gone": gone, "count": len(have)}


# ------------------------------------------------------------------ 매니페스트 투영
def manifest_entry(oc: dict) -> dict:
    """서랍의 인물 → 매니페스트가 쓰는 모양(서랍 전용 칸은 떼고 나간다)."""
    out: dict = {}
    for k in _MANIFEST_KEYS:
        if k in oc:
            out[k] = oc[k]
    out.setdefault("version", 1)
    out.setdefault("profile", {})
    out.setdefault("reference_images", [])
    out.setdefault("prompt_tags", [])
    return out


def sync_manifest(ids: Any = None) -> dict:
    """서랍을 매니페스트에 **얹는다**(더하기·갱신만, 삭제 없음).

    ``ids`` 를 주면 그 인물들만 — 조립 직전에 이 대화에 나오는 사람들만 올리는 길이다.
    이미 같은 내용이면 파일을 건드리지 않는다(매 호출마다 쓰면 백업이 의미 없이 불어난다).
    """
    want = None
    if ids is not None:
        want = {str(x).strip() for x in ids if str(x).strip()}
    mf = vn_core.load_manifest()
    chars = mf.get("characters")
    if not isinstance(chars, list):
        chars = []
    index = {c.get("character_id"): i for i, c in enumerate(chars) if isinstance(c, dict)}
    added, updated = [], []
    for oc in list_all():
        cid = oc.get("character_id")
        if oc.get("broken") or not cid:
            continue
        if want is not None and cid not in want:
            continue
        entry = manifest_entry(oc)
        if cid in index:
            if chars[index[cid]] != entry:
                chars[index[cid]] = entry
                updated.append(cid)
        else:
            chars.append(entry)
            index[cid] = len(chars) - 1
            added.append(cid)
    if added or updated:
        mf["characters"] = chars
        vn_core.atomic_write_json(vn_core.PROJECT / "manifest.json", mf)
    return {"added": added, "updated": updated, "total": len(chars)}


def main(argv: list[str] | None = None) -> int:
    import argparse
    vn_core.console_guard()
    ap = argparse.ArgumentParser(description="고유 캐릭터 서랍")
    ap.add_argument("--show", metavar="OC-001")
    ap.add_argument("--sync", action="store_true", help="서랍을 매니페스트에 얹는다")
    a = ap.parse_args(argv)
    if a.show:
        print(json.dumps(get(a.show), ensure_ascii=False, indent=1))
    elif a.sync:
        print(json.dumps(sync_manifest(), ensure_ascii=False))
    else:
        for oc in list_all():
            print("%-8s %-14s 사진 %d장%s" % (
                oc.get("character_id", "?"), oc.get("name", ""),
                len(oc.get("reference_images") or []),
                "  [깨짐] " + oc["broken"] if oc.get("broken") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
