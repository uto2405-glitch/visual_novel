"""수동 모드 웹 경로 E2E 테스트 — 실행 중인 스튜디오(127.0.0.1:8765)를 실제로 두드린다.

Grok 응답(SCENES_JSON / SCENE_PROMPT)과 외부 이미지 생성은 사람이 하는 수작업이므로
이 스크립트가 그 자리를 샘플로 채운다. 나머지(compose-manual / grok-input / set-prompt /
register / select / approve / viewer)는 사용자가 웹에서 누를 그 엔드포인트를 그대로 호출한다.
"""
import json
import shutil
import struct
import subprocess
import sys
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
PY = sys.executable
OK = 0
FAIL = 0


def step(name, cond, detail=""):
    global OK, FAIL
    mark = "PASS" if cond else "FAIL"
    if cond:
        OK += 1
    else:
        FAIL += 1
    print(f"  [{mark}] {name}" + ("" if cond or not detail else f"\n         └ {detail}"))


def api(path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def write_png(path, w=1400, h=1000, rgb=(210, 180, 150)):
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress((b"\x00" + bytes(rgb) * w) * h, 6)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


# ---- 캐릭터/장소 앵커 (프롬프트에 원문 그대로 들어가야 A6 통과) ----
A_HARI = "17-year-old Korean girl, short brown bob hair, bright eyes, yellow hoodie"
A_JUN = "17-year-old Korean boy, black curly hair, round glasses, navy school uniform"
A_ROOF = "school rooftop at sunset, orange sky, chain-link fence"
A_STUDIO = "old school broadcasting room, fluorescent light, vintage radio equipment"

MANIFEST = {
    "project_id": "PROJECT-001", "title": "옥상의 라디오", "language": "ko-KR",
    "orchestrator": {"provider": "Grok (SuperGrok 구독)", "mode": "manual",
                     "api": {"base_url": "https://api.x.ai/v1", "model": "grok-4.6",
                             "key_env": "XAI_API_KEY", "note": "수동 모드 — API 미사용"}},
    "image_generator": {"provider": "샘플(E2E)", "model": "sample"},
    "output": {"mode": "visual_novel_scene_cards", "print_ready": True,
               "aspect_ratio": "2:3", "min_long_edge_px": 1024},
    "workflow": {"human_gates": ["story", "visual_reference", "scene_plan", "image", "delivery"],
                 "scene_batch_size": 1},
    "characters": [
        {"character_id": "CHAR-001", "name": "하리", "version": 1,
         "profile": {"age": "17", "gender_presentation": "여성", "hair": "갈색 단발",
                     "eyes": "밝은 갈색", "build": "보통", "wardrobe": "노란 후드",
                     "signature_props": ["헤드폰"]},
         "reference_images": [], "prompt_anchor": A_HARI},
        {"character_id": "CHAR-002", "name": "준", "version": 1,
         "profile": {"age": "17", "gender_presentation": "남성", "hair": "검은 곱슬",
                     "eyes": "검정", "build": "마른", "wardrobe": "남색 교복",
                     "signature_props": ["둥근 안경"]},
         "reference_images": [], "prompt_anchor": A_JUN},
    ],
    "locations": [
        {"location_id": "LOC-001", "name": "학교 옥상", "version": 1,
         "description": "노을 지는 방과 후 옥상", "reference_images": [], "prompt_anchor": A_ROOF},
        {"location_id": "LOC-002", "name": "방송실", "version": 1,
         "description": "오래된 교내 방송실", "reference_images": [], "prompt_anchor": A_STUDIO},
    ],
    "props": [],
}

STORYLINE = ("폐지 위기에 놓인 교내 라디오 방송부. 3학년 하리는 마지막 방송을 준비하며 "
             "무뚝뚝한 엔지니어 준을 설득한다. 방송실에서 결심하고, 준을 끌어들이고, "
             "옥상에서 장비를 세팅하고, 노을 아래 마지막 멘트를 띄운다.")

# ---- Grok 이 돌려줄 SCENES_JSON 을 사람 대신 샘플로 작성 (앵커 포함) ----
SCENES = [
    {"order": 1, "purpose": "폐지 공문을 보고 마지막 방송을 결심", "action_beat": "책상 위 공문을 손에 쥐고 마이크를 바라본다",
     "emotion": "쓸쓸함에서 결의로", "time": "방과 후", "location_id": "LOC-002",
     "camera": {"shot": "medium", "angle": "eye level", "framing": "좌측 인물", "focus": "표정"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "마지막이라도... 제대로 해보자."}],
     "image_prompt": f"warm cel-shaded webtoon, {A_HARI}, in {A_STUDIO}, holding a document, looking at the microphone, determined"},
    {"order": 2, "purpose": "엔지니어 준을 설득", "action_beat": "준의 앞에 헤드폰을 내밀며 부탁한다",
     "emotion": "간절함과 장난기", "time": "방과 후", "location_id": "LOC-002",
     "camera": {"shot": "two shot", "angle": "eye level", "framing": "마주보는 두 인물", "focus": "손과 표정"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "너 없으면 소리가 안 나오잖아."},
                  {"speaker_id": "CHAR-002", "text": "...딱 한 번이야."}],
     "image_prompt": f"warm cel-shaded webtoon, {A_HARI} and {A_JUN}, in {A_STUDIO}, offering headphones, facing each other"},
    {"order": 3, "purpose": "옥상에서 장비 세팅", "action_beat": "케이블을 정리하며 노을을 본다",
     "emotion": "설렘", "time": "해질녘", "location_id": "LOC-001",
     "camera": {"shot": "wide", "angle": "low", "framing": "옥상 전경 속 두 인물", "focus": "실루엣"},
     "dialogue": [{"speaker_id": "CHAR-002", "text": "전파 상태 좋아. 갈 수 있어."}],
     "image_prompt": f"warm cel-shaded webtoon, {A_HARI} and {A_JUN}, on {A_ROOF}, setting up radio cables, silhouettes"},
    {"order": 4, "purpose": "노을 아래 마지막 멘트", "action_beat": "마이크에 대고 미소지으며 인사한다",
     "emotion": "벅참", "time": "노을", "location_id": "LOC-001",
     "camera": {"shot": "close-up", "angle": "eye level", "framing": "우측 인물, 좌측 여백", "focus": "미소"},
     "dialogue": [{"speaker_id": "CHAR-001", "text": "여기는 옥상의 라디오. 마지막 방송을 시작합니다."}],
     "image_prompt": f"warm cel-shaded webtoon, {A_HARI}, on {A_ROOF}, speaking into a microphone, gentle smile, golden light"},
]


def main():
    print("=" * 60)
    print("수동 모드 E2E — 작품 '옥상의 라디오' (샘플 자동 주입)")
    print("=" * 60)

    # 0) 초기화: 데모/테스트 데이터 제거 후 새 매니페스트/스토리 투입
    shutil.rmtree(ROOT / "project" / "scenes", ignore_errors=True)
    (ROOT / "project" / "scenes").mkdir(parents=True)
    shutil.rmtree(ROOT / "images" / "raw", ignore_errors=True)
    (ROOT / "images" / "raw").mkdir(parents=True)
    shutil.rmtree(ROOT / "project" / "scenes_backup_20260824_000000", ignore_errors=True)
    (ROOT / "project" / "manifest.json").write_text(
        json.dumps(MANIFEST, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n[준비] 새 매니페스트/캐릭터/장소 투입, 기존 장면·이미지 초기화")

    # 1) 스토리라인 저장 (엔드포인트)
    st, _ = api("/api/storyline", {"text": STORYLINE})
    stt, state = api("/api/state")
    step("1. 스토리라인 저장 + 상태 반영", st == 200 and state.get("title") == "옥상의 라디오"
         and state.get("storyline", "").startswith("폐지 위기"))

    # 2) 수동 compose-input: grok.com 붙여넣기용 지시문 (API 불필요)
    st, d = api("/api/compose-input", {"count": 4})
    inst = d.get("instruction", "")
    step("2. compose-input 지시문 생성(마커·앵커 포함)",
         st == 200 and "SCENES_JSON_ONLY" in inst and A_HARI in inst and A_ROOF in inst,
         inst[:80])

    # 3) (사람이 grok.com 에서 받은 JSON 대신) 샘플 JSON 을 붙여넣어 장면 생성
    fenced = "```json\n" + json.dumps(SCENES, ensure_ascii=False) + "\n```"
    st, d = api("/api/compose-manual", {"text": fenced, "force": True, "count": 4})
    step("3. compose-manual 붙여넣기 → 4장면 생성 + 검사 통과",
         st == 200 and len(d.get("created", [])) == 4 and d.get("checker_pass") is True
         and not d.get("warning"), json.dumps(d, ensure_ascii=False)[:160])

    # 4) 장면별 수동 프롬프트 경로도 실제로 사용 (grok-input → set-prompt) — 1번 장면으로 시연
    st, d = api("/api/grok-input", {"scene_id": "SCENE-001"})
    gi = d.get("text", "")
    step("4a. grok-input 지시서 생성(캐릭터·장소 앵커 포함)",
         st == 200 and A_HARI in gi and A_STUDIO in gi, gi[:80])
    sp = (f"SCENE_PROMPT: warm cel-shaded korean webtoon, medium shot, {A_HARI}, "
          f"in {A_STUDIO}, holding a paper, looking at the mic, determined, portrait 2:3\n"
          "NEGATIVE_PROMPT: text, letters, watermark, extra fingers\n"
          "CONTINUITY_NOTES: 헤드폰은 목에 건 상태 유지\n"
          "DIALOGUE_PLACEMENT: 하단 여백 확보")
    st, d = api("/api/set-prompt", {"scene_id": "SCENE-001", "text": sp})
    step("4b. set-prompt 저장 → PROMPT + 앵커검사 통과",
         st == 200 and d.get("status") == "PROMPT" and d.get("checker_pass") is True,
         d.get("fails", ""))

    # 5) 외부 이미지 AI 대역: 각 장면 후보 2장씩 생성 → images/raw/<scene>/
    palette = [(240, 170, 90), (250, 120, 110), (255, 200, 120), (230, 150, 170)]
    for i in range(1, 5):
        sid = f"SCENE-{i:03d}"
        folder = ROOT / "images" / "raw" / sid
        folder.mkdir(parents=True, exist_ok=True)
        write_png(folder / f"{sid}_a.png", 1400, 1000, palette[(i - 1) % 4])
        write_png(folder / f"{sid}_b.png", 1400, 1000, tuple(min(255, c + 25) for c in palette[(i - 1) % 4]))
    print("\n[외부 AI 대역] 4장면 × 후보 2장 = 8장 생성 완료 (2:3, 1400x1000)")

    # 6) 각 장면: 폴더 스캔 → 선택 → 승인 (사용자가 웹에서 누르는 그 흐름)
    all_approved = True
    for i in range(1, 5):
        sid = f"SCENE-{i:03d}"
        st1, d1 = api("/api/register-images", {"scene_id": sid})
        rel = f"images/raw/{sid}/{sid}_a.png"
        st2, d2 = api("/api/select", {"scene_id": sid, "image": rel})
        st3, d3 = api("/api/approve", {"scene_id": sid})
        ok = (st1 == 200 and d1.get("auto") == "PASS" and st2 == 200
              and d2.get("auto_pass") is True and st3 == 200 and d3.get("status") == "APPROVED")
        step(f"6.{i} {sid} 스캔(후보 {d1.get('count')})→선택→승인",
             ok, f"reg={d1} sel={d2} appr={d3}")
        all_approved = all_approved and ok

    # 7) 뷰어 상태: 4장 모두 APPROVED + 이미지 서빙 확인
    st, state = api("/api/state")
    scenes = state.get("scenes", [])
    approved = [s for s in scenes if s.get("status") == "APPROVED"]
    img_ok = True
    for s in approved:
        url = s.get("image_url")
        if not url:
            img_ok = False
            continue
        try:
            with urllib.request.urlopen(BASE + url, timeout=10) as r:
                img_ok = img_ok and r.status == 200 and int(r.headers.get("Content-Length", 0)) > 0
        except Exception:
            img_ok = False
    step("7. 뷰어: 4장면 APPROVED + 이미지 서빙(HTTP 200)",
         len(approved) == 4 and img_ok, f"approved={len(approved)}/4")

    # 8) 전체 자동 검사 (검사기)
    p = subprocess.run([PY, "tools/check_protocol.py"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    step("8. check_protocol 전체 PASS", p.returncode == 0 and "RESULT: PASS" in p.stdout,
         p.stdout.strip().splitlines()[-1] if p.stdout else "")

    print("\n" + "=" * 60)
    print(f"E2E 결과: {OK} PASS / {FAIL} FAIL")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
