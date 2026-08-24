#!/usr/bin/env python3
"""타임캡슐 감상본 내보내기 — 승인 장면+이미지+VN 뷰어를 단일 HTML 로 굽는다.

서버·폰트·네트워크 없이 어디서든(폰 포함) 열리는 자족 파일. 이미지가 base64 로 내장되어
파일 하나가 곧 디지털 소장본이다. VN 모드(타자기·자동·이어보기·분기·백로그)와
세로 스크롤 웹툰 모드 포함.

사용법:
  python tools/export_viewer.py                # 승인 장면
  python tools/export_viewer.py --all          # selected_image 있는 전부
  python tools/export_viewer.py --max-edge 1600 --quality 85   # (Pillow 있을 때) 재인코딩 크기/화질
  python tools/export_viewer.py --cover SCENE-004              # 표지 커버 CG 지정
  python tools/export_viewer.py --embed-font                   # assets/fonts 의 폰트 임베드(기본 꺼짐)

출력: output/viewer/<제목>.html   (쓰기: output/ 만. Pillow·fontTools 는 선택 — 있으면 용량 최적화)
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "project" / "manifest.json"
SCENES = ROOT / "project" / "scenes"
OUT_DIR = ROOT / "output" / "viewer"

NAME_COLORS = ["#5FB39A", "#D9A441", "#C77DBB", "#6FA8DC", "#E07A5F", "#84C18B", "#B58BE0", "#E0A458"]

# 폰트 임베드(옵션) — 확장자 → (mime, css format)
FONT_EXT = {".woff2": ("font/woff2", "woff2"), ".woff": ("font/woff", "woff"),
            ".ttf": ("font/ttf", "truetype"), ".otf": ("font/otf", "opentype")}
FONT_DIRS = ("assets/fonts", "fonts")
# 서브셋 시 반드시 살려야 하는 UI 문자(본문 글자와 별개)
UI_TEXT = ("VISUAL NOVEL · 소장본 처음부터 감상 ▸ 이어보기 세로 스크롤로 읽기 자동 기록 스크롤 닫기 "
           "즉시 빠름 보통 느림 탭/Space 진행 ← 이전 Esc VN 모드 지난 대사 "
           "아직 지나온 대사가 없습니다. — 끝 — 탭하면 닫힙니다 엔딩 · 선택지 "
           "개 장면 오프라인 자족 파일 이미지 없음 ♥ ()「」『』…,.!?~-—:;\"'%/ "
           "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _console_guard() -> None:
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_console_guard()


def _load(path: Path):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (ValueError, OSError):
        return None


def char_color(cid: str) -> str:
    h = 0
    for c in str(cid):
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return NAME_COLORS[h % len(NAME_COLORS)]


def image_data_uri(path: Path, max_edge: int, quality: int) -> str | None:
    """이미지 → data URI. Pillow 있으면 JPEG 재인코딩으로 용량 최적화, 없으면 원본 그대로."""
    if not path.exists():
        return None
    try:
        from PIL import Image
        import io
        with Image.open(path) as im:
            im.load()
            img = im.convert("RGB")
        if max(img.size) > max_edge:
            img.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except ImportError:
        pass
    except Exception:
        return None
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp"}.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_data(include_all: bool, max_edge: int, quality: int, cover_id: str | None = None) -> dict:
    mf = _load(MANIFEST)
    if not mf:
        raise RuntimeError("project/manifest.json 이 없거나 손상됐습니다.")
    chars = {c.get("character_id"): {"name": c.get("name") or c.get("character_id"),
                                     "color": char_color(c.get("character_id", ""))}
             for c in mf.get("characters", []) if isinstance(c, dict)}
    scenes = []
    for f in sorted(SCENES.glob("SCENE-*.json")) if SCENES.exists() else []:
        sc = _load(f)
        if not sc:
            continue
        sel = (sc.get("assets", {}).get("selected_image") or "").strip()
        if not sel:
            continue
        if not include_all and sc.get("status") != "APPROVED":
            continue
        lines = []
        for d in (sc.get("dialogue") if isinstance(sc.get("dialogue"), list) else []):
            if not isinstance(d, dict):
                continue
            spk = d.get("speaker_id")
            info = chars.get(spk)
            lines.append({"n": info["name"] if info else "", "c": info["color"] if info else "",
                          "t": str(d.get("text", "")), "p": d.get("placement", "bottom")})
        entry = {"id": sc.get("scene_id", "?"), "order": sc.get("scene_order", 0),
                 "purpose": str(sc.get("purpose", "")),
                 "img": image_data_uri(ROOT / sel, max_edge, quality),
                 "lines": lines}
        if isinstance(sc.get("choices"), list) and sc["choices"]:
            entry["choices"] = sc["choices"]
        if isinstance(sc.get("branch"), list) and sc["branch"]:
            entry["branch"] = sc["branch"]
        if sc.get("ending"):
            # 엔딩 이름(문자열)이 있으면 보존 — 없으면 기존처럼 참
            entry["ending"] = sc["ending"] if isinstance(sc["ending"], str) else True
        scenes.append(entry)
    scenes.sort(key=lambda s: s.get("order") or 0)
    if not scenes:
        raise RuntimeError("내보낼 장면이 없습니다. (selected_image 있는 APPROVED 장면 — --all 로 전체)")
    dating = mf.get("dating") if isinstance(mf.get("dating"), dict) else None
    return {"title": mf.get("title") or "무제", "scenes": scenes, "dating": dating,
            "cover": pick_cover(scenes, cover_id)}


def pick_cover(scenes: list, cover_id: str | None) -> int | None:
    """표지 커버로 쓸 장면 인덱스. 이미 내장된 이미지를 재사용해 용량 증가가 없다."""
    if cover_id:
        for i, s in enumerate(scenes):
            if s.get("id") == cover_id and s.get("img"):
                return i
    for i, s in enumerate(scenes):
        if s.get("img"):
            return i
    return None


# ------------------------------------------------------------------ 폰트(옵션)
def find_font(spec: str | None) -> Path | None:
    """--embed-font 값 해석. 'auto' 면 assets/fonts 에서 첫 폰트를 찾는다. 없으면 None(시스템 폰트 폴백)."""
    if not spec:
        return None
    if spec != "auto":
        p = Path(spec)
        if not p.is_absolute():
            p = ROOT / spec
        return p if p.is_file() and p.suffix.lower() in FONT_EXT else None
    for d in FONT_DIRS:
        dd = ROOT / d
        if not dd.is_dir():
            continue
        for f in sorted(dd.iterdir()):
            if f.is_file() and f.suffix.lower() in FONT_EXT:
                return f
    return None


def subset_font(path: Path, text: str):
    """fontTools 가 있으면 사용 문자만 남긴 서브셋 바이트를 만든다. 없으면 None(원본 통째 임베드)."""
    try:
        import io
        from fontTools import subset as ftsubset
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    for flavor, mime, fmt in (("woff2", "font/woff2", "woff2"),
                              ("woff", "font/woff", "woff"),
                              (None, "font/ttf", "truetype")):
        try:
            font = TTFont(str(path))
            opts = ftsubset.Options()
            opts.layout_features = ["*"]
            opts.notdef_outline = True
            sub = ftsubset.Subsetter(options=opts)
            sub.populate(text=text)
            sub.subset(font)
            font.flavor = flavor
            buf = io.BytesIO()
            font.save(buf)
            return buf.getvalue(), mime, fmt
        except Exception:
            continue
    return None


def font_css(path: Path | None, text: str) -> str:
    """@font-face + body 폰트 지정 CSS. 폰트가 없으면 빈 문자열(조용히 건너뜀)."""
    if not path:
        return ""
    made = subset_font(path, text)
    if made:
        raw, mime, fmt = made
        how = "서브셋"
    else:
        try:
            raw = path.read_bytes()
        except OSError:
            return ""
        mime, fmt = FONT_EXT[path.suffix.lower()]
        how = "원본(fontTools 없음 — pip install fonttools brotli 시 서브셋)"
    b64 = base64.b64encode(raw).decode("ascii")
    print(f"  폰트 임베드: {path.name} · {how} · {len(raw) / 1_000_000:.2f} MB")
    if len(raw) > 4_000_000:
        print("  ⚠ 폰트가 큽니다 — 감상본 용량이 그만큼 늘어납니다.")
    return ('@font-face{font-family:"VNKR";font-style:normal;font-weight:400;font-display:swap;'
            f'src:url(data:{mime};base64,{b64}) format("{fmt}")}}'
            '\nbody{font-family:"VNKR","Pretendard","Noto Sans KR","Malgun Gothic",system-ui,sans-serif}')


def used_text(data: dict) -> str:
    """서브셋 대상 문자 — 제목·대사·선택지·목적문 + UI 문구."""
    parts = [str(data.get("title") or ""), UI_TEXT]
    for s in data.get("scenes", []):
        parts.append(str(s.get("purpose") or ""))
        for line in s.get("lines", []):
            parts.append(str(line.get("n") or ""))
            parts.append(str(line.get("t") or ""))
        for c in (s.get("choices") or []):
            if isinstance(c, dict):
                parts.append(str(c.get("text") or ""))
    return "".join(parts)


TEMPLATE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#17110D;--ink:#EFE4D0;--sub:#A79680;--line:#3A2C1F;--amber:#E0A64B;
--paper:#F2E8D5;--pink:#241C14}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:"Pretendard","Noto Sans KR","Malgun Gothic",system-ui,sans-serif;
font-size:15px;line-height:1.6;-webkit-tap-highlight-color:rgba(224,166,75,.25)}
__FONTCSS__
button{font:inherit;cursor:pointer;touch-action:manipulation}
#card{position:fixed;inset:0;z-index:5;display:flex;flex-direction:column;align-items:center;
justify-content:center;gap:14px;background:radial-gradient(120% 90% at 50% 40%,#241A12,#100B07);text-align:center;padding:20px}
#card h1{font-size:clamp(26px,7vw,44px);letter-spacing:-.01em;text-shadow:0 2px 18px rgba(0,0,0,.75)}
#card .sub{color:var(--sub);font-size:12px;letter-spacing:.25em}
#card button{background:var(--amber);color:#1B130C;border:none;border-radius:99px;padding:12px 30px;font-weight:700}
#card button.ghost{background:none;color:var(--sub);border:1px solid var(--line)}
#card.hide{display:none}
/* 표지 커버 CG — 내장 이미지 재사용(추가 용량 0) */
#cover{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.55}
#cover[hidden]{display:none}
#scrim{position:absolute;inset:0;
background:radial-gradient(115% 85% at 50% 38%,rgba(21,15,10,.42),rgba(14,10,6,.95))}
#card>*:not(#cover):not(#scrim){position:relative;z-index:1}
#stage{position:fixed;inset:0;background:#0E0A07;display:none}
#stage.on{display:block}
#img{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden}
#img img{max-width:100%;max-height:100%;object-fit:contain}
#img .empty{color:var(--sub);padding:26px;text-align:center}
#tap{position:absolute;inset:0;cursor:pointer}
#bar{position:absolute;top:10px;right:10px;display:flex;gap:6px;z-index:3;flex-wrap:wrap;justify-content:flex-end;
align-items:center}
#bar .b{background:rgba(30,24,18,.72);color:var(--ink);border:1px solid var(--line);border-radius:8px;
padding:7px 11px;font-size:12px;font-weight:600}
#bar .b.on{color:var(--amber);border-color:var(--amber)}
#prog{position:absolute;top:14px;left:12px;z-index:3;font-size:11px;color:var(--sub);
background:rgba(30,24,18,.72);border:1px solid var(--line);border-radius:99px;padding:4px 10px}
#dlg{position:absolute;left:50%;transform:translateX(-50%);bottom:18px;width:min(860px,93%);z-index:2;
background:var(--paper);color:var(--pink);border-radius:13px;padding:13px 18px;cursor:pointer;
box-shadow:0 16px 40px -14px rgba(0,0,0,.7)}
#dlg.top{bottom:auto;top:56px}
#dlg.narr{background:rgba(18,13,9,.82);color:var(--paper)}
#dlg.narr #txt{text-align:center;font-style:italic}
#who{display:inline-block;font-size:12px;font-weight:800;padding:2px 11px;border-radius:99px;margin-bottom:6px;color:#fff}
#txt{font-size:clamp(15px,2.4vw,18px);line-height:1.62;min-height:1.6em;white-space:pre-wrap;
max-height:34vh;overflow-y:auto;overflow-wrap:anywhere;word-break:keep-all;line-break:strict}
#aff{align-self:center;font-weight:700;color:#F2C0B6;background:rgba(196,61,43,.22);
border:1px solid #C43D2B;border-radius:99px;padding:4px 10px;font-size:12px;transition:transform .18s ease}
#aff.bump{transform:scale(1.16);background:rgba(196,61,43,.5)}
#choices{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:4;
display:flex;flex-direction:column;gap:12px;width:min(560px,88%)}
#choices[hidden]{display:none}
#choices button{background:rgba(24,18,12,.95);color:var(--ink);border:1px solid var(--amber);
border-radius:12px;padding:14px 18px;font:inherit;font-size:15px;cursor:pointer;text-align:left;
box-shadow:0 8px 24px -10px rgba(0,0,0,.7)}
#choices button:hover,#choices button:focus-visible{background:rgba(224,166,75,.22);outline:none}
/* 백로그(지난 대사) */
#log{position:absolute;inset:0;z-index:6;background:rgba(12,8,5,.95);display:flex;flex-direction:column}
#log[hidden]{display:none}
#logHead{display:flex;justify-content:space-between;align-items:center;gap:10px;
padding:12px 14px;border-bottom:1px solid var(--line)}
#logInner{flex:1;overflow-y:auto;padding:6px 12px 28px;-webkit-overflow-scrolling:touch}
#logInner .row{display:block;width:100%;text-align:left;background:none;border:none;color:inherit;
font:inherit;padding:11px 12px;border-bottom:1px solid var(--line);border-radius:8px;
word-break:keep-all;overflow-wrap:anywhere}
#logInner .row:hover,#logInner .row:focus-visible{background:rgba(224,166,75,.14);outline:none}
#logInner .row b{font-weight:800}
#logInner .row .nar{color:var(--sub);font-style:italic}
#logInner .none{color:var(--sub);padding:16px 12px}
@media(max-width:640px){
 #bar{flex-wrap:wrap;gap:5px;max-width:calc(100% - 16px)}
 .b{padding:8px 10px;font-size:12px}
 #dlg{bottom:14px;padding:12px 15px} #dlg.top{top:52px}
 #txt{font-size:var(--dlg-fs,clamp(15px,4.2vw,18px));max-height:32vh}
 #choices{width:92%} #choices button{padding:13px 15px;font-size:14.5px}
}
#scroll{position:fixed;inset:0;background:var(--bg);display:none;overflow-y:auto;z-index:4;
-webkit-overflow-scrolling:touch}
#scroll.on{display:block}
#scroll .cut{max-width:820px;margin:0 auto}
#scroll .cut img{width:100%;display:block}
#scroll .say{padding:12px 18px;border-bottom:1px solid var(--line)}
#scroll .say b{font-weight:800}
#scroll .say .nar{color:var(--sub);font-style:italic;text-align:center;display:block}
#scroll .say .pick{color:var(--amber)}
#scroll .topbar{position:sticky;top:0;background:rgba(23,17,13,.9);backdrop-filter:blur(4px);
padding:10px 14px;display:flex;justify-content:space-between;align-items:center;z-index:2;border-bottom:1px solid var(--line)}
.small{color:var(--sub);font-size:12px}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style></head><body>
<div id="card">
<img id="cover" alt="" hidden><div id="scrim"></div>
<div class="sub">VISUAL NOVEL · 소장본</div>
<h1>__TITLE__</h1>
<div class="small" id="meta"></div>
<button id="bStart">처음부터 감상 ▸</button>
<button id="bResume" class="ghost" hidden>이어보기</button>
<button id="bScroll" class="ghost">세로 스크롤로 읽기</button>
</div>

<div id="stage">
<div id="img"></div><div id="tap"></div>
<span id="prog"></span>
<div id="bar">
<span id="aff" hidden></span>
<button class="b" id="bAuto">자동</button>
<button class="b" id="bSpeed">보통</button>
<button class="b" id="bLog">기록</button>
<button class="b" id="bToScroll">스크롤</button>
<button class="b" id="bExit">닫기</button></div>
<div id="choices" hidden></div>
<div id="dlg"><span id="who"></span><div id="txt"></div>
<div class="small" style="text-align:right;margin-top:5px;opacity:.6">탭/Space 진행 · ← 이전 · L 기록 · Esc 닫기</div></div>
<div id="log" hidden><div id="logHead"><b>지난 대사</b>
<button class="b" id="bLogClose">닫기</button></div><div id="logInner"></div></div>
</div>

<div id="scroll">
<div class="topbar"><b id="scTitle"></b>
<span><button class="b" id="bToVN" style="background:rgba(30,24,18,.72);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:12px">VN 모드</button>
<button class="b" id="bScExit" style="background:rgba(30,24,18,.72);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:12px">닫기</button></span></div>
<div class="cut" id="cuts"></div>
</div>

<script>
"use strict";
const DATA=__DATA__;
const $=id=>document.getElementById(id);
const el=(t,c,x)=>{const n=document.createElement(t);if(c)n.className=c;if(x!=null)n.textContent=x;return n};
const REDUCE=matchMedia("(prefers-reduced-motion: reduce)").matches;
const SPEEDS=[[0,"즉시"],[18,"빠름"],[28,"보통"],[46,"느림"]];
let vi=0,di=0,ended=false,revealing=false,timer=null,aTimer=null,autoOn=false,full="";
let aff=0,awaiting=false,path=[];        // 분기 엔진: 호감도 · 선택지 대기 · 지나온 장면
let hist=[],histKeys=new Set();          // 백로그(지난 대사)
const K={pos:"tc:pos:"+DATA.title,set:"tc:set:"+DATA.title,hist:"tc:hist:"+DATA.title};
let SET={sp:2};
try{const s=JSON.parse(localStorage.getItem(K.set)||"{}");if(typeof s.sp==="number")SET.sp=s.sp}catch(e){}
function saveSet(){try{localStorage.setItem(K.set,JSON.stringify(SET))}catch(e){}}
function savePos(){try{localStorage.setItem(K.pos,JSON.stringify({vi,di,aff,path}))}catch(e){}}
function loadPos(){try{return JSON.parse(localStorage.getItem(K.pos)||"null")}catch(e){return null}}
function saveHist(){try{localStorage.setItem(K.hist,JSON.stringify(hist.slice(-500)))}catch(e){}}
function loadHist(){try{const h=JSON.parse(localStorage.getItem(K.hist)||"[]");return Array.isArray(h)?h:[]}catch(e){return []}}
const dlen=s=>(s.lines||[]).length||1;

// ---- 분기 엔진(호감도·선택지·엔딩) ----
const affMax=()=>(DATA.dating&&DATA.dating.max)||100;
const affStart=()=>(DATA.dating&&typeof DATA.dating.start_affection==="number")?DATA.dating.start_affection:30;
const clampAff=v=>Math.max(0,Math.min(affMax(),v));
function updateAff(d){const m=$("aff");if(!DATA.dating){m.hidden=true;return}
 m.hidden=false;m.textContent="♥ "+aff+" / "+affMax()+(d?(d>0?"  +"+d:"  "+d):"");
 if(d){m.classList.add("bump");setTimeout(()=>{m.classList.remove("bump");
  m.textContent="♥ "+aff+" / "+affMax()},1100)}}
const idxOf=id=>DATA.scenes.findIndex(s=>s.id===id);
function nextIndex(sc){
 if(sc.branch&&sc.branch.length){   // 조건 만족하는 첫 분기로(위에서부터)
  for(const b of sc.branch){if(aff>=(b.min||0)){const i=idxOf(b.goto);if(i>=0)return i}}
  return -1}
 return vi+1<DATA.scenes.length?vi+1:-1}
function goTo(idx){path.push(vi);vi=idx;di=0;ended=false;renderImg();show()}
function hideChoices(){const box=$("choices");box.replaceChildren();box.hidden=true;
 awaiting=false;$("dlg").style.opacity=""}
function showChoices(sc){awaiting=true;clearTimeout(aTimer);
 const box=$("choices");box.replaceChildren();
 for(const c of sc.choices){const b=el("button",null,c.text||"…");b.onclick=()=>pick(c);box.appendChild(b)}
 box.hidden=false;$("dlg").style.opacity=".3";
 const first=box.querySelector("button");if(first)first.focus()}
function pick(c){hideChoices();
 const d=c.affection||0;if(d){aff=clampAff(aff+d)}updateAff(d);savePos();
 const nx=c.goto?idxOf(c.goto):(vi+1<DATA.scenes.length?vi+1:-1);
 if(nx<0){end();return}goTo(nx)}

function renderImg(){const sc=DATA.scenes[vi],box=$("img");box.replaceChildren();
 if(!sc)return;
 if(sc.img){const im=el("img");im.src=sc.img;im.alt=sc.id;box.appendChild(im)}
 else box.appendChild(el("div","empty",sc.purpose||sc.id))}
function type(t){clearInterval(timer);full=t;const e=$("txt");const ms=SPEEDS[SET.sp][0];
 if(REDUCE||ms<=0){e.textContent=t;e.scrollTop=e.scrollHeight;revealing=false;shown();return}
 revealing=true;const cs=[...t];let i=0;e.textContent="";
 timer=setInterval(()=>{i++;e.textContent=cs.slice(0,i).join("");e.scrollTop=e.scrollHeight;
  if(i>=cs.length){clearInterval(timer);revealing=false;shown()}},ms)}
function shown(){clearTimeout(aTimer);
 if(autoOn&&!awaiting&&!logOpen())aTimer=setTimeout(()=>adv(1),1400+full.length*22)}
function record(n,t,c){const k=vi+":"+di;if(histKeys.has(k))return;
 histKeys.add(k);hist.push({n:n,t:t,c:c,vi:vi,di:di});saveHist()}
function show(){const sc=DATA.scenes[vi];if(!sc)return;
 $("prog").textContent=(vi+1)+" / "+DATA.scenes.length+(dlen(sc)>1?" · "+(di+1)+"/"+dlen(sc):"");
 const line=(sc.lines||[])[di],dlg=$("dlg"),who=$("who");
 dlg.classList.toggle("top",!!(line&&line.p==="top"));
 if(line&&line.n){dlg.classList.remove("narr");who.style.display="inline-block";
  who.textContent=line.n;who.style.background=line.c||"#2F6B59";
  const h=(line.c||"").replace("#","");
  const lum=h.length>=6?(.299*parseInt(h.slice(0,2),16)+.587*parseInt(h.slice(2,4),16)+.114*parseInt(h.slice(4,6),16)):0;
  who.style.color=lum>150?"#17110D":"#fff";
  record(line.n,line.t||"",line.c||null)}
 else{dlg.classList.add("narr");who.style.display="none";
  record("",line?(line.t||""):(sc.purpose||""),null)}
 type(line?line.t:(sc.purpose||"…"));savePos()}
function adv(step){
 if(logOpen()){closeLog();return}
 if(awaiting)return;                       // 선택지 대기 중엔 선택해야 진행
 if(ended){exit();return}
 if(step>0&&revealing){clearInterval(timer);$("txt").textContent=full;revealing=false;shown();return}
 const sc=DATA.scenes[vi];if(!sc)return;clearTimeout(aTimer);
 if(step>0){
  if(di+1<dlen(sc)){di++;show();return}
  if(sc.choices&&sc.choices.length){showChoices(sc);return}   // 장면 끝 → 선택지
  if(sc.ending){end();return}                                 // 엔딩 장면
  const nx=nextIndex(sc);                                     // 분기 or 선형
  if(nx<0){end();return}
  goTo(nx);return}
 if(di>0){di--;show();return}
 const prev=path.length?path.pop():(vi>0?vi-1:-1);             // 분기 경로를 따라 되돌아감
 if(prev<0||prev>=DATA.scenes.length)return;
 vi=prev;di=dlen(DATA.scenes[vi])-1;ended=false;renderImg();show()}
function end(){ended=true;autoOn=false;$("bAuto").classList.remove("on");hideChoices();
 const sc=DATA.scenes[vi],lab=(sc&&typeof sc.ending==="string")?sc.ending:"";
 const dlg=$("dlg");dlg.classList.remove("top");dlg.classList.add("narr");$("who").style.display="none";
 $("txt").textContent="— 끝 —\\n\\n『"+DATA.title+"』"+(lab?"\\n엔딩 · "+lab:"")+"\\n\\n(탭하면 닫힙니다)";
 try{localStorage.removeItem(K.pos)}catch(e){}}
function start(resume,at){ended=false;$("card").classList.add("hide");
 $("scroll").classList.remove("on");$("stage").classList.add("on");
 autoOn=false;$("bAuto").classList.remove("on");clearTimeout(aTimer);closeLog();hideChoices();
 const pos=resume?loadPos():null;
 if(pos){hist=loadHist();histKeys=new Set(hist.map(h=>h.vi+":"+h.di));
  path=Array.isArray(pos.path)?pos.path.filter(n=>typeof n==="number"):[]}
 else{hist=[];histKeys=new Set();path=[];saveHist()}
 aff=clampAff(pos&&typeof pos.aff==="number"?pos.aff:affStart());
 if(typeof at==="number"){vi=at;di=0;path=[]}
 else{vi=pos&&pos.vi<DATA.scenes.length?pos.vi:0;di=pos&&pos.di<dlen(DATA.scenes[vi])?pos.di:0}
 updateAff(0);renderImg();show()}
function exit(){clearInterval(timer);autoOn=false;$("bAuto").classList.remove("on");
 clearTimeout(aTimer);closeLog();hideChoices();   // 자동 끄고 닫아야 뒤에서 되살아나지 않는다
 $("stage").classList.remove("on");$("card").classList.remove("hide");
 $("bResume").hidden=!loadPos()}

// ---- 백로그 패널 ----
const logOpen=()=>!$("log").hidden;
function closeLog(){$("log").hidden=true;$("bLog").setAttribute("aria-expanded","false");
 if(autoOn&&!revealing&&!ended&&!awaiting)shown()}
function renderLog(){const box=$("logInner");box.replaceChildren();
 if(!hist.length){box.appendChild(el("div","none","아직 지나온 대사가 없습니다."));return}
 for(const h of hist){const row=el("button","row");
  if(h.n){const b=el("b",null,h.n+"  ");if(h.c)b.style.color=h.c;row.appendChild(b);
   row.appendChild(el("span",null,h.t))}
  else row.appendChild(el("span","nar",h.t));
  row.onclick=()=>jump(h.vi,h.di);
  box.appendChild(row)}
 box.scrollTop=box.scrollHeight}
function toggleLog(){if(logOpen()){closeLog();return}
 clearTimeout(aTimer);renderLog();   // 선택지 대기 중이면 그 위를 덮기만 한다(선택은 유지)
 $("log").hidden=false;$("bLog").setAttribute("aria-expanded","true");$("bLogClose").focus()}
function jump(v,d){closeLog();hideChoices();ended=false;const before=vi;vi=v;di=d;
 if(vi!==before)renderImg();show()}

// ---- 세로 스크롤 웹툰 모드 ----
function buildScroll(){const box=$("cuts");if(box.childElementCount)return;
 for(const sc of DATA.scenes){
  if(sc.img){const im=el("img");im.src=sc.img;im.alt=sc.id;im.loading="lazy";box.appendChild(im)}
  for(const l of (sc.lines||[])){const say=el("div","say");
   if(l.n){const b=el("b",null,l.n+"  ");b.style.color=l.c||"var(--amber)";say.appendChild(b);
    say.appendChild(el("span",null,l.t))}
   else say.appendChild(el("span","nar",l.t));
   box.appendChild(say)}
  for(const c of (sc.choices||[])){const say=el("div","say");   // 스크롤 모드는 선택지를 목록으로만
   say.appendChild(el("span","pick","▸ "+(c.text||"")));box.appendChild(say)}}}
function openScroll(){buildScroll();$("card").classList.add("hide");
 $("stage").classList.remove("on");$("scroll").classList.add("on")}

$("bStart").onclick=()=>start(false);
$("bResume").onclick=()=>start(true);
$("bScroll").onclick=openScroll;
$("bToScroll").onclick=()=>{clearInterval(timer);clearTimeout(aTimer);openScroll()};
$("bToVN").onclick=()=>{$("scroll").classList.remove("on");start(false,vi)};
$("bScExit").onclick=()=>{$("scroll").classList.remove("on");$("card").classList.remove("hide")};
$("bExit").onclick=exit;
$("bLog").onclick=toggleLog;$("bLogClose").onclick=closeLog;
$("bAuto").onclick=()=>{autoOn=!autoOn;$("bAuto").classList.toggle("on",autoOn);
 if(autoOn&&!revealing)shown();else clearTimeout(aTimer)};
$("bSpeed").onclick=()=>{SET.sp=(SET.sp+1)%SPEEDS.length;$("bSpeed").textContent=SPEEDS[SET.sp][1];saveSet()};
$("tap").onclick=()=>adv(1);$("dlg").onclick=()=>adv(1);
let tx=0,ty=0;
$("tap").addEventListener("touchstart",e=>{const t=e.changedTouches[0];tx=t.clientX;ty=t.clientY},{passive:true});
$("tap").addEventListener("touchend",e=>{const t=e.changedTouches[0],dx=t.clientX-tx,dy=t.clientY-ty;
 if(Math.abs(dx)>45&&Math.abs(dx)>Math.abs(dy))adv(dx<0?1:-1)},{passive:true});
addEventListener("keydown",e=>{
 if($("scroll").classList.contains("on")){if(e.key==="Escape")$("bScExit").click();return}
 if(!$("stage").classList.contains("on")){if(e.key==="Enter"||e.key===" "){e.preventDefault();start(false)}return}
 if(logOpen()){if(e.key==="Escape"||e.key==="l"||e.key==="L")closeLog();return}
 if(e.key==="Escape"){if(awaiting)return;exit();return}
 if(e.key==="l"||e.key==="L"){toggleLog();return}
 if(awaiting)return;
 if(e.key==="ArrowLeft"){adv(-1);return}
 if(e.key===" "||e.key==="ArrowRight"||e.key==="Enter"){e.preventDefault();adv(1);return}
 if(e.key==="a"||e.key==="A")$("bAuto").click()});
$("meta").textContent=DATA.scenes.length+"개 장면 · 오프라인 자족 파일";
$("scTitle").textContent=DATA.title;
$("bSpeed").textContent=SPEEDS[SET.sp][1];
$("bResume").hidden=!loadPos();
if(typeof DATA.cover==="number"&&DATA.scenes[DATA.cover]&&DATA.scenes[DATA.cover].img){
 const cv=$("cover");cv.src=DATA.scenes[DATA.cover].img;cv.hidden=false}
</script></body></html>
"""


def build_html(include_all: bool, max_edge: int, quality: int,
               cover_id: str | None = None, font_spec: str | None = None):
    """(data, html) 반환 — 단일 파일 export 와 PWA 번들이 공유."""
    data = build_data(include_all, max_edge, quality, cover_id)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    fcss = font_css(find_font(font_spec), used_text(data))
    html = (TEMPLATE.replace("__TITLE__", data["title"])
            .replace("__FONTCSS__", fcss).replace("__DATA__", payload))
    return data, html


def safe_name(title: str) -> str:
    return ("".join(c for c in title if c.isalnum() or c in " -_가-힣").strip()) or "viewer"


def export(include_all: bool, max_edge: int, quality: int,
           cover_id: str | None = None, font_spec: str | None = None) -> Path:
    data, html = build_html(include_all, max_edge, quality, cover_id, font_spec)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{safe_name(data['title'])}.html"
    out.write_text(html, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="타임캡슐 감상본 내보내기 (단일 HTML)")
    ap.add_argument("--all", action="store_true", help="상태 무관 selected_image 전부")
    ap.add_argument("--max-edge", type=int, default=1600, help="(Pillow) 내장 이미지 최대 긴 변 px")
    ap.add_argument("--quality", type=int, default=85, help="(Pillow) JPEG 품질")
    ap.add_argument("--cover", metavar="SCENE-ID", help="표지 커버 CG 로 쓸 장면(기본: 첫 장면)")
    ap.add_argument("--embed-font", nargs="?", const="auto", metavar="PATH",
                    help="한글 폰트 임베드(기본 꺼짐). 값 없으면 assets/fonts 에서 자동 탐색")
    args = ap.parse_args()
    try:
        out = export(args.all, args.max_edge, args.quality, args.cover, args.embed_font)
    except RuntimeError as exc:
        print(f"오류: {exc}")
        return 1
    if args.embed_font and not find_font(args.embed_font):
        print("  · 폰트 파일을 찾지 못해 시스템 폰트로 폴백했습니다 (assets/fonts/*.woff2|ttf|otf).")
    size = out.stat().st_size
    print(f"감상본 저장: {out.relative_to(ROOT).as_posix()}  ({size / 1_000_000:.2f} MB)")
    if size > 15_000_000:
        print("  ⚠ 15MB 초과 — 폰 전송/아티팩트 게시가 어려울 수 있음. --max-edge/--quality 를 낮추세요.")
    print("이 파일 하나면 서버 없이 어디서든(폰 포함) 재생됩니다. VN 모드 + 세로 스크롤 모드 포함.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
