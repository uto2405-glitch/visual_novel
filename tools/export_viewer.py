#!/usr/bin/env python3
"""타임캡슐 감상본 내보내기 — 승인 장면+이미지+VN 뷰어를 단일 HTML 로 굽는다.

서버·폰트·네트워크 없이 어디서든(폰 포함) 열리는 자족 파일. 이미지가 base64 로 내장되어
파일 하나가 곧 디지털 소장본이다. VN 모드(타자기·자동·이어보기)와 세로 스크롤 웹툰 모드 포함.

사용법:
  python tools/export_viewer.py                # 승인 장면
  python tools/export_viewer.py --all          # selected_image 있는 전부
  python tools/export_viewer.py --max-edge 1600 --quality 85   # (Pillow 있을 때) 재인코딩 크기/화질

출력: output/viewer/<제목>.html   (쓰기: output/ 만. Pillow 는 선택 — 있으면 용량 최적화)
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


def build_data(include_all: bool, max_edge: int, quality: int) -> dict:
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
        scenes.append({"id": sc.get("scene_id", "?"), "order": sc.get("scene_order", 0),
                       "purpose": str(sc.get("purpose", "")),
                       "img": image_data_uri(ROOT / sel, max_edge, quality),
                       "lines": lines})
    scenes.sort(key=lambda s: s.get("order") or 0)
    if not scenes:
        raise RuntimeError("내보낼 장면이 없습니다. (selected_image 있는 APPROVED 장면 — --all 로 전체)")
    return {"title": mf.get("title") or "무제", "scenes": scenes}


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
button{font:inherit;cursor:pointer;touch-action:manipulation}
#card{position:fixed;inset:0;z-index:5;display:flex;flex-direction:column;align-items:center;
justify-content:center;gap:14px;background:radial-gradient(120% 90% at 50% 40%,#241A12,#100B07);text-align:center;padding:20px}
#card h1{font-size:clamp(26px,7vw,44px);letter-spacing:-.01em}
#card .sub{color:var(--sub);font-size:12px;letter-spacing:.25em}
#card button{background:var(--amber);color:#1B130C;border:none;border-radius:99px;padding:12px 30px;font-weight:700}
#card button.ghost{background:none;color:var(--sub);border:1px solid var(--line)}
#card.hide{display:none}
#stage{position:fixed;inset:0;background:#0E0A07;display:none}
#stage.on{display:block}
#img{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden}
#img img{max-width:100%;max-height:100%;object-fit:contain}
#img .empty{color:var(--sub);padding:26px;text-align:center}
#tap{position:absolute;inset:0;cursor:pointer}
#bar{position:absolute;top:10px;right:10px;display:flex;gap:6px;z-index:3;flex-wrap:wrap;justify-content:flex-end}
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
#scroll{position:fixed;inset:0;background:var(--bg);display:none;overflow-y:auto;z-index:4;
-webkit-overflow-scrolling:touch}
#scroll.on{display:block}
#scroll .cut{max-width:820px;margin:0 auto}
#scroll .cut img{width:100%;display:block}
#scroll .say{padding:12px 18px;border-bottom:1px solid var(--line)}
#scroll .say b{font-weight:800}
#scroll .say .nar{color:var(--sub);font-style:italic;text-align:center;display:block}
#scroll .topbar{position:sticky;top:0;background:rgba(23,17,13,.9);backdrop-filter:blur(4px);
padding:10px 14px;display:flex;justify-content:space-between;align-items:center;z-index:2;border-bottom:1px solid var(--line)}
.small{color:var(--sub);font-size:12px}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style></head><body>
<div id="card">
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
<button class="b" id="bAuto">자동</button>
<button class="b" id="bSpeed">보통</button>
<button class="b" id="bToScroll">스크롤</button>
<button class="b" id="bExit">닫기</button></div>
<div id="dlg"><span id="who"></span><div id="txt"></div>
<div class="small" style="text-align:right;margin-top:5px;opacity:.6">탭/Space 진행 · ← 이전 · Esc 닫기</div></div>
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
const K={pos:"tc:pos:"+DATA.title,set:"tc:set:"+DATA.title};
let SET={sp:2};
try{const s=JSON.parse(localStorage.getItem(K.set)||"{}");if(typeof s.sp==="number")SET.sp=s.sp}catch(e){}
function saveSet(){try{localStorage.setItem(K.set,JSON.stringify(SET))}catch(e){}}
function savePos(){try{localStorage.setItem(K.pos,JSON.stringify({vi,di}))}catch(e){}}
function loadPos(){try{return JSON.parse(localStorage.getItem(K.pos)||"null")}catch(e){return null}}
const dlen=s=>(s.lines||[]).length||1;

function renderImg(){const sc=DATA.scenes[vi],box=$("img");box.replaceChildren();
 if(sc.img){const im=el("img");im.src=sc.img;im.alt=sc.id;box.appendChild(im)}
 else box.appendChild(el("div","empty",sc.purpose||sc.id))}
function type(t){clearInterval(timer);full=t;const e=$("txt");const ms=SPEEDS[SET.sp][0];
 if(REDUCE||ms<=0){e.textContent=t;e.scrollTop=e.scrollHeight;revealing=false;shown();return}
 revealing=true;const cs=[...t];let i=0;e.textContent="";
 timer=setInterval(()=>{i++;e.textContent=cs.slice(0,i).join("");e.scrollTop=e.scrollHeight;
  if(i>=cs.length){clearInterval(timer);revealing=false;shown()}},ms)}
function shown(){clearTimeout(aTimer);
 if(autoOn)aTimer=setTimeout(()=>adv(1),1400+full.length*22)}
function show(){const sc=DATA.scenes[vi];if(!sc)return;
 $("prog").textContent=(vi+1)+" / "+DATA.scenes.length+(dlen(sc)>1?" · "+(di+1)+"/"+dlen(sc):"");
 const line=(sc.lines||[])[di],dlg=$("dlg"),who=$("who");
 dlg.classList.toggle("top",!!(line&&line.p==="top"));
 if(line&&line.n){dlg.classList.remove("narr");who.style.display="inline-block";
  who.textContent=line.n;who.style.background=line.c||"#2F6B59";
  const h=(line.c||"").replace("#","");
  const lum=h.length>=6?(.299*parseInt(h.slice(0,2),16)+.587*parseInt(h.slice(2,4),16)+.114*parseInt(h.slice(4,6),16)):0;
  who.style.color=lum>150?"#17110D":"#fff"}
 else{dlg.classList.add("narr");who.style.display="none"}
 type(line?line.t:(sc.purpose||"…"));savePos()}
function adv(step){if(ended){exit();return}
 if(step>0&&revealing){clearInterval(timer);$("txt").textContent=full;revealing=false;shown();return}
 const sc=DATA.scenes[vi];if(!sc)return;clearTimeout(aTimer);
 const before=vi;
 if(step>0){if(di+1<dlen(sc))di++;else{vi++;di=0}}
 else{if(di>0)di--;else if(vi>0){vi--;di=dlen(DATA.scenes[vi])-1}}
 if(vi>=DATA.scenes.length){end();return}
 if(vi!==before)renderImg();show()}
function end(){ended=true;autoOn=false;$("bAuto").classList.remove("on");
 const dlg=$("dlg");dlg.classList.remove("top");dlg.classList.add("narr");$("who").style.display="none";
 $("txt").textContent="— 끝 —\\n\\n『"+DATA.title+"』\\n\\n(탭하면 닫힙니다)";
 try{localStorage.removeItem(K.pos)}catch(e){}}
function start(resume,at){ended=false;$("card").classList.add("hide");
 $("scroll").classList.remove("on");$("stage").classList.add("on");
 const pos=resume?loadPos():null;
 if(typeof at==="number"){vi=at;di=0}
 else{vi=pos&&pos.vi<DATA.scenes.length?pos.vi:0;di=pos&&pos.di<dlen(DATA.scenes[vi])?pos.di:0}
 renderImg();show()}
function exit(){clearInterval(timer);clearTimeout(aTimer);
 $("stage").classList.remove("on");$("card").classList.remove("hide");
 $("bResume").hidden=!loadPos()}

// 세로 스크롤 웹툰 모드
function buildScroll(){const c=$("cuts");if(c.childElementCount)return;
 for(const sc of DATA.scenes){
  if(sc.img){const im=el("img");im.src=sc.img;im.alt=sc.id;im.loading="lazy";c.appendChild(im)}
  for(const l of (sc.lines||[])){const say=el("div","say");
   if(l.n){const b=el("b",null,l.n+"  ");b.style.color=l.c||"var(--amber)";say.appendChild(b);
    say.appendChild(el("span",null,l.t))}
   else say.appendChild(el("span","nar",l.t));
   c.appendChild(say)}}}
function openScroll(){buildScroll();$("card").classList.add("hide");
 $("stage").classList.remove("on");$("scroll").classList.add("on")}

$("bStart").onclick=()=>start(false);
$("bResume").onclick=()=>start(true);
$("bScroll").onclick=openScroll;
$("bToScroll").onclick=()=>{clearInterval(timer);clearTimeout(aTimer);openScroll()};
$("bToVN").onclick=()=>{$("scroll").classList.remove("on");start(false,vi)};
$("bScExit").onclick=()=>{$("scroll").classList.remove("on");$("card").classList.remove("hide")};
$("bExit").onclick=exit;
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
 if(e.key==="Escape"){exit();return}
 if(e.key==="ArrowLeft"){adv(-1);return}
 if(e.key===" "||e.key==="ArrowRight"||e.key==="Enter"){e.preventDefault();adv(1);return}
 if(e.key==="a"||e.key==="A")$("bAuto").click()});
$("meta").textContent=DATA.scenes.length+"개 장면 · 오프라인 자족 파일";
$("bSpeed").textContent=SPEEDS[SET.sp][1];
$("bResume").hidden=!loadPos();
</script></body></html>
"""


def export(include_all: bool, max_edge: int, quality: int) -> Path:
    data = build_data(include_all, max_edge, quality)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__TITLE__", data["title"]).replace("__DATA__", payload)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in data["title"] if c.isalnum() or c in " -_가-힣") or "viewer"
    out = OUT_DIR / f"{safe.strip() or 'viewer'}.html"
    out.write_text(html, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="타임캡슐 감상본 내보내기 (단일 HTML)")
    ap.add_argument("--all", action="store_true", help="상태 무관 selected_image 전부")
    ap.add_argument("--max-edge", type=int, default=1600, help="(Pillow) 내장 이미지 최대 긴 변 px")
    ap.add_argument("--quality", type=int, default=85, help="(Pillow) JPEG 품질")
    args = ap.parse_args()
    try:
        out = export(args.all, args.max_edge, args.quality)
    except RuntimeError as exc:
        print(f"오류: {exc}")
        return 1
    size = out.stat().st_size
    print(f"감상본 저장: {out.relative_to(ROOT).as_posix()}  ({size / 1_000_000:.2f} MB)")
    if size > 15_000_000:
        print("  ⚠ 15MB 초과 — 폰 전송/아티팩트 게시가 어려울 수 있음. --max-edge/--quality 를 낮추세요.")
    print("이 파일 하나면 서버 없이 어디서든(폰 포함) 재생됩니다. VN 모드 + 세로 스크롤 모드 포함.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
