#!/usr/bin/env python3
"""이미지 생성 클라이언트 공용 조각 — 결과형·생성 메타·사용 대장(엔진 무관).

MakeFun(유료·원격)과 ComfyUI(무료·로컬)가 같은 결과형(:class:`GenResult`)을 돌려주고,
같은 파일(``images/raw/<scene>/_gen_meta.json``)에 같은 모양의 메타를 남기게 하는 자리다.
두 클라이언트가 이 조각을 각자 한 벌씩 들고 있으면 gen_jobs·스튜디오가 읽는 필드가
조용히 갈린다 — 그래서 여기 한 곳에만 두고 두 쪽이 별칭으로 가져다 쓴다.

의존은 vn_core 하나다(계층 1). 클라이언트(계층 3)와 조립기(image_gen)가 이 위에 선다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:          # 이 파일만 적재돼도 '옆에 있는' vn_core 를 쓴다
    sys.path.insert(0, str(_HERE))

from vn_core import WRITE_LOCK, atomic_write_json, load_json_safe   # noqa: E402

META_NAME = "_gen_meta.json"
META_MAX_ENTRIES = 200      # _gen_meta.json 무한 증식 방지(엔진마다 다르면 한쪽만 부푼다)
SIZE_ALIGN = 8              # 생성 크기는 8의 배수 — SDXL/VAE 규약이라 두 엔진에 같이 걸린다


def align_up(px) -> int:
    """8의 배수로 **올림**(음수·형 오류는 0).

    상한을 올리라고 권하는 자리에 쓴다. 클라이언트는 상한을 8의 배수로 **내림**해 자르므로
    (cap 2250 → 2248) 권고값을 그대로 쓰면 "이미 그 값인데 더 올리라"는 말이 되고, 사용자가
    시키는 대로 해도 A3 는 계속 FAIL 한다. 권고는 실행 가능해야 한다.
    """
    try:
        v = int(px)
    except (TypeError, ValueError):
        return 0
    if v <= 0:
        return 0
    return (v + SIZE_ALIGN - 1) // SIZE_ALIGN * SIZE_ALIGN


class GenResult(list):
    """저장된 파일 경로 목록 — list 그대로라 기존 호출부와 호환되고, 부분 실패 정보를 함께 싣는다.

    warnings 는 사람에게 보여야 할 한 줄들(크기 절삭·일부 실패), task_ids 는 엔진이 준
    작업 id(MakeFun task / ComfyUI prompt_id) — 어느 엔진이든 gen_jobs 는 이 둘만 읽는다.
    """

    def __init__(self, files=(), warnings=None, task_ids=None):
        super().__init__(files)
        self.warnings: list[str] = list(warnings or [])
        self.task_ids: list[str] = list(task_ids or [])


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_usage(path: Path | str, record: dict) -> None:
    """append-only 사용 대장(jsonl). 기록 실패가 생성을 막지 않는다.

    엔진별로 파일이 다르다(logs/makefun_usage.jsonl · logs/comfyui_usage.jsonl) — 유료·무료
    대장을 한 파일에 섞으면 과금 합산이 어긋난다. 어느 파일에 쓸지는 호출부가 정한다.
    """
    try:
        p = Path(path)
        with WRITE_LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": now_iso(), **record}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def write_gen_meta(out_dir: Path | str, entry: dict) -> None:
    """생성 메타데이터를 images/raw/<scene>/_gen_meta.json 에 누적한다.

    read-modify-write 는 저장소 전역 잠금(vn_core.WRITE_LOCK) 안에서 한다 — 웹에서 장면을
    저장하는 순간과 겹쳐도 이미 과금된 task_id 기록이 덮여 사라지지 않게(재수령 불가 = 손실).
    """
    try:
        path = Path(out_dir) / META_NAME
        with WRITE_LOCK:
            doc = load_json_safe(path, {})
            entries = doc.get("entries")
            if not isinstance(entries, list):
                entries = []
            entries.append(entry)
            doc["entries"] = entries[-META_MAX_ENTRIES:]
            doc.setdefault("scene_id", entry.get("scene_id", ""))
            doc["updated_at"] = now_iso()
            atomic_write_json(path, doc)
    except Exception:
        pass
