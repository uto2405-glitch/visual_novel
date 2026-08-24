"use strict";
/* tools/vn_runtime.js — VN 재생 엔진(단일 출처).
 *
 * 스튜디오 뷰어(tools/studio.html)와 감상본(tools/export_viewer.py)이 이 파일 하나를 쓴다.
 *  - 감상본: export_viewer 가 빌드할 때 TEMPLATE 의 런타임 자리표시자에 이 파일 내용을 그대로
 *            인라인한다 (단일 HTML 자기완결 성질 유지 — 외부 요청 0).
 *            그래서 이 파일 안에는 그 자리표시자 토큰을 글자 그대로 쓰지 않는다 —
 *            쓰면 인라인된 사본에 남아 "치환되지 않은 자리표시자" 로 오진된다(자가진단 J04).
 *  - 스튜디오: /studio/vn_runtime.js 라우트로 같은 파일을 defer 로 읽어 간다.
 *            (여기에 script 시작 태그를 글자 그대로 쓰지 않는 이유도 위와 같다 — 인라인된
 *             사본에 남으면 감상본이 외부 스크립트를 참조하는 것으로 오진된다.)
 *
 * 정본 데이터 스키마는 export_viewer.build_data() 의 것이다:
 *   data  = {title, scenes:[...], dating:{max,start_affection}|null, episodes:[{ep,title}]}
 *   scene = {id, order, purpose, img, lines:[{n,c,t,p}], ep, choices, branch, ending, ending_label}
 *   choice= {text, goto?, affection?}     branch = {min, goto}
 * 스튜디오는 /api/state 의 장면(scene_id·dialogue·image_url…)을 이 모양으로 변환해 넘긴다.
 *
 * 전역은 하나만 노출한다: window.VNRuntime = {mount(opts), renderScroll(data,container,opts)}
 *   mount.opts = {data, root, imageSrc(sc,kind), storageKey, onExit(), onGallery(),
 *                 onSavedChange(has), backgroundNodes(), extraButtons}
 *   renderScroll  세로 스크롤 리딩(웹툰형) 화면 — 재생과 별개의 읽기 방식이라 상태가 없다.
 *                 두 호스트가 같은 DOM·같은 위치 저장 규약을 쓰게 하는 단일 출처.
 *
 * 규약: 이 파일은 문자열을 HTML 로 조립하지 않는다 — 문자열 주입 API 는 한 번도 쓰지 않고
 *       createElement/textContent/속성 대입만 쓴다(자가진단 J01·V01 이 감시). 감상본에
 *       인라인되므로 스크립트 종료 태그로 읽힐 수 있는 문자열도 쓰지 않는다.
 */
(function (global) {
  if (!global || !global.document || global.VNRuntime) return;
  var D = global.document;

  var el = function (t, c, x) {
    var n = D.createElement(t);
    if (c) n.className = c;
    if (x != null) n.textContent = x;
    return n;
  };
  var REDUCE = !!(global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var COARSE = !!(global.matchMedia && global.matchMedia("(pointer:coarse)").matches);
  var FOCUSABLE = "button:not([disabled]),[href],input,select,textarea,[tabindex]:not([tabindex='-1'])";
  var PRELOAD_SPAN = 2;      // 현재 위치 ±2컷만 미리 받는다(100컷 작품에서 수백 MB 선요청 방지)
  var BAR_IDLE_MS = 3000;    // 폰: 이만큼 손을 떼고 있으면 툴바가 그림 위에서 물러난다
  var TAP_R = 24;            // 이 반경 안이면 탭. 가로로 이만큼을 넘기면 스와이프 — 사이에 빈 구간이 없다
  // 단축키 힌트: 폰(터치)에는 없는 키를 나열하지 않고, 몇 컷 읽고 나면 사라진다 —
  // 좁은 화면에서 대사창 한 줄을 매 컷 빼앗지 않기 위해서다.
  var HINT_KEYS = "탭/Space 진행 · ← 이전 · L 기록 · C 장면 · S 설정 · Esc 닫기";
  var HINT_TOUCH = "탭으로 진행 · 좌우 스와이프";
  var HINT_LINES = COARSE ? 3 : 6;

  /* ------------------------------------------------------------------ 스타일
   * 두 화면이 같은 연출을 쓰도록 CSS 도 런타임이 들고 있다. 색은 호스트가
   * --vnr-* 커스텀 속성으로 갈아끼울 수 있고, 없으면 기본값으로 그려진다.
   */
  var CSS = [
    ".vnr{position:fixed;inset:0;z-index:9;display:none;background:var(--vnr-stage,#0E0B08);",
    "color:var(--vnr-ink,#EDE4D3);line-height:1.55}",
    ".vnr.on{display:block}",
    ".vnr [hidden]{display:none!important}",
    ".vnr button{font:inherit;cursor:pointer;touch-action:manipulation}",
    ".vnr :focus-visible{outline:2px solid var(--vnr-accent,#5FB39A);outline-offset:2px}",
    ".vnr-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;",
    "clip:rect(0 0 0 0);white-space:nowrap;border:0}",
    /* 이미지 */
    ".vnr-img{position:absolute;inset:0;overflow:hidden;background:var(--vnr-stage,#0E0B08)}",
    ".vnr-img img{position:absolute;inset:0;margin:auto;max-width:100%;max-height:100%;",
    "object-fit:contain;opacity:0;transition:opacity .5s ease}",
    ".vnr-img img.vnr-show{opacity:1}",
    ".vnr-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;",
    "color:var(--vnr-sub,#A79680);text-align:center;padding:30px}",
    ".vnr-click{position:absolute;inset:0;cursor:pointer;z-index:1}",
    /* 시네마틱(비네트+레터박스) */
    ".vnr-fx{position:absolute;inset:0;pointer-events:none;z-index:1}",
    ".vnr-fx::after{content:'';position:absolute;inset:0;",
    "background:radial-gradient(125% 100% at 50% 45%,transparent 58%,rgba(0,0,0,.5) 100%)}",
    ".vnr-fx i{position:absolute;left:0;right:0;height:7%;background:#000;display:block}",
    ".vnr-fx i.vnr-t{top:0}.vnr-fx i.vnr-b{bottom:0}",
    /* 진행률 */
    ".vnr-progbar{position:absolute;left:0;right:0;top:0;height:3px;z-index:3;",
    "background:rgba(255,255,255,.09);pointer-events:none;transition:opacity .2s ease}",
    ".vnr-progbar i{display:block;height:100%;width:0;background:var(--vnr-accent,#5FB39A)}",
    ".vnr.vnr-uihidden .vnr-progbar{opacity:0}",
    /* 툴바 */
    ".vnr-bar{position:absolute;z-index:3;display:flex;gap:6px;align-items:center;flex-wrap:wrap;",
    "justify-content:flex-end;top:calc(12px + env(safe-area-inset-top));",
    "right:calc(14px + env(safe-area-inset-right));max-width:calc(100% - 24px)}",
    ".vnr-btn,.vnr-chip{background:rgba(30,24,18,.72);color:var(--vnr-ink,#EDE4D3);",
    "border:1px solid var(--vnr-line,#453828);border-radius:8px;padding:6px 11px;",
    "font-size:12px;font-weight:600}",
    ".vnr-chip{border-radius:999px;font-weight:600}",
    ".vnr-btn.on{color:var(--vnr-accent,#5FB39A);border-color:var(--vnr-accent,#5FB39A)}",
    ".vnr-aff{background:rgba(196,61,43,.22);border-color:var(--vnr-seal,#C43D2B);",
    "color:#F2C0B6;font-weight:700}",
    /* 툴바 유휴 숨김 — 대사창은 그대로 두고 툴바만 물러난다(읽는 중에 글이 사라지면 안 된다) */
    ".vnr.vnr-baridle .vnr-bar{opacity:0;pointer-events:none}",
    /* [⋯] 보조 도구 — 폰에서 툴바를 한 줄로 유지하기 위해 같은 버튼 노드를 여기로 옮겨 담는다 */
    ".vnr-more{position:absolute;top:calc(100% + 6px);right:0;z-index:4;display:flex;",
    "flex-direction:column;gap:6px;padding:8px;min-width:136px;",
    "background:rgba(24,18,12,.96);border:1px solid var(--vnr-line,#453828);border-radius:10px;",
    "box-shadow:0 14px 34px rgba(0,0,0,.55)}",
    ".vnr-more .vnr-btn{width:100%;text-align:left;background:transparent;border-color:transparent}",
    ".vnr-more .vnr-btn:hover,.vnr-more .vnr-btn:focus-visible{",
    "border-color:var(--vnr-accent,#5FB39A)}",
    /* 대사창 */
    ".vnr-dlg{position:absolute;left:50%;transform:translateX(-50%);",
    "bottom:calc(26px + env(safe-area-inset-bottom));width:min(880px,92%);",
    "background:var(--vnr-paper,#F2EAD9);color:var(--vnr-paper-ink,#2A2118);border-radius:14px;",
    "padding:14px 22px 16px;box-shadow:0 8px 30px rgba(0,0,0,.5);cursor:pointer;z-index:2}",
    ".vnr-dlg.vnr-top{bottom:auto;top:calc(70px + env(safe-area-inset-top))}",
    ".vnr-dlg.vnr-narr{background:rgba(18,14,10,.82);color:var(--vnr-paper,#F2EAD9)}",
    ".vnr-dlg.vnr-narr .vnr-text{text-align:center;font-style:italic}",
    ".vnr-name{display:inline-block;color:#fff;font-size:12.5px;font-weight:800;",
    "padding:2px 12px;border-radius:999px;margin-bottom:7px}",
    ".vnr-text{font-size:var(--vnr-fs,17px);line-height:1.6;min-height:48px;white-space:pre-wrap;",
    "max-height:38vh;overflow-y:auto;overflow-wrap:anywhere;word-break:keep-all;line-break:strict}",
    ".vnr-hint{margin-top:6px;text-align:right;opacity:.78;font-size:11.5px;font-style:normal}",
    ".vnr-dlg,.vnr-bar{transition:opacity .2s ease}",
    ".vnr.vnr-uihidden .vnr-dlg,.vnr.vnr-uihidden .vnr-bar{opacity:0;pointer-events:none}",
    /* 선택지 — 무대(.vnr)는 position:fixed 라 스크롤 컨테이너가 아니다. 선택지가 화면보다
       길어지면 첫/마지막 항목을 누를 수 없으므로 이 상자 자신이 스크롤해야 한다. */
    ".vnr-choices{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:4;",
    "display:flex;flex-direction:column;gap:12px;width:min(560px,88%);",
    "max-height:calc(100% - 140px);overflow-y:auto;-webkit-overflow-scrolling:touch;",
    "overscroll-behavior:contain;",
    "padding:4px 4px calc(4px + env(safe-area-inset-bottom))}",
    ".vnr-choices button{background:rgba(24,18,12,.94);color:var(--vnr-ink,#EDE4D3);",
    "border:1px solid var(--vnr-accent,#5FB39A);border-radius:12px;padding:14px 18px;",
    "font-size:15px;text-align:left;box-shadow:0 8px 24px -10px rgba(0,0,0,.7)}",
    ".vnr-choices button:hover,.vnr-choices button:focus-visible{",
    "background:var(--vnr-accent-d,#2F6B59);outline:none}",
    /* 패널 공통 */
    ".vnr-panel{position:absolute;z-index:5;background:var(--vnr-panel,#2E251C);",
    "border:1px solid var(--vnr-line,#453828);border-radius:12px;color:var(--vnr-ink,#EDE4D3);",
    "box-shadow:0 12px 44px rgba(0,0,0,.6);display:flex;flex-direction:column;gap:10px;padding:16px}",
    ".vnr-panel h3{font-size:13px;color:var(--vnr-accent,#5FB39A);letter-spacing:.1em;font-weight:800}",
    ".vnr-panel .vnr-close{align-self:flex-end}",
    ".vnr-log,.vnr-scenes{inset:7% 9%}",
    ".vnr-inner{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:6px;padding-right:6px;",
    "-webkit-overflow-scrolling:touch}",
    ".vnr-line{padding:8px 11px;border-radius:8px;background:var(--vnr-panel2,#372D22);",
    "white-space:pre-wrap;border:0;color:inherit;font:inherit;text-align:left;cursor:pointer;",
    "word-break:keep-all;overflow-wrap:anywhere}",
    ".vnr-line b{font-weight:800}",
    ".vnr-line .vnr-nar{color:var(--vnr-sub,#A79680);font-style:italic}",
    ".vnr-line:hover,.vnr-line:focus-visible{background:var(--vnr-line,#453828)}",
    ".vnr-none{color:var(--vnr-sub,#A79680);padding:14px 11px}",
    /* 장면 이동 */
    ".vnr-ephead{color:var(--vnr-accent,#5FB39A);font-size:11.5px;font-weight:800;",
    "letter-spacing:.06em;padding:10px 2px 2px}",
    ".vnr-item{text-align:left;background:var(--vnr-panel2,#372D22);color:var(--vnr-ink,#EDE4D3);",
    "border:1px solid var(--vnr-line,#453828);border-radius:8px;padding:9px 12px;font-size:13px;",
    "display:flex;gap:12px;align-items:center}",
    ".vnr-item:hover,.vnr-item:focus-visible{border-color:var(--vnr-accent,#5FB39A)}",
    ".vnr-item .vnr-n{color:var(--vnr-accent,#5FB39A);font-weight:800;",
    "font-variant-numeric:tabular-nums;flex-shrink:0;min-width:1.5em}",
    ".vnr-item .vnr-th,.vnr-item .vnr-thx{width:56px;height:42px;border-radius:5px;flex-shrink:0}",
    ".vnr-item .vnr-th{object-fit:cover;border:1px solid var(--vnr-line,#453828)}",
    ".vnr-item .vnr-thx{border:1px dashed var(--vnr-line,#453828)}",
    ".vnr-item .vnr-tx{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
    ".vnr-item .vnr-rd{flex-shrink:0;font-size:11px;color:var(--vnr-accent,#5FB39A)}",
    ".vnr-item .vnr-rd.vnr-no{color:var(--vnr-sub,#A79680);opacity:.82}",
    ".vnr-item.vnr-here{border-color:var(--vnr-accent,#5FB39A);background:var(--vnr-line,#453828)}",
    /* 설정 */
    ".vnr-set{top:calc(52px + env(safe-area-inset-top));right:14px;width:min(330px,86%);gap:14px}",
    ".vnr-set label{display:flex;flex-direction:column;gap:6px;font-size:12px;",
    "color:var(--vnr-sub,#A79680)}",
    ".vnr-set label.vnr-ck{flex-direction:row;align-items:center;gap:8px}",
    ".vnr-set input[type=range]{width:100%;accent-color:var(--vnr-accent,#5FB39A)}",
    ".vnr-seg{display:flex;gap:6px;flex-wrap:wrap}",
    ".vnr-seg button{background:var(--vnr-panel2,#372D22);color:var(--vnr-ink,#EDE4D3);",
    "border:1px solid var(--vnr-line,#453828);border-radius:9px;padding:8px 12px;font-size:12.5px}",
    ".vnr-seg button:hover,.vnr-seg button:focus-visible{border-color:var(--vnr-accent,#5FB39A)}",
    /* 호감도 연출 */
    ".vnr-afffloat{position:absolute;left:50%;top:46%;z-index:6;pointer-events:none;font-size:26px;",
    "font-weight:800;transform:translate(-50%,-50%);text-shadow:0 2px 12px rgba(0,0,0,.65)}",
    ".vnr-afffloat.vnr-up{color:#FF8FA3}",
    ".vnr-afffloat.vnr-down{color:#8FBEE0}",
    /* 엔딩 카드 */
    ".vnr-end{position:absolute;inset:0;z-index:7;display:flex;flex-direction:column;",
    "align-items:center;justify-content:center;gap:14px;text-align:center;padding:26px;",
    "background:radial-gradient(120% 90% at 50% 45%,rgba(20,15,10,.74),rgba(6,5,4,.96))}",
    ".vnr-end .vnr-ttl{font-size:12px;letter-spacing:.45em;color:var(--vnr-accent,#5FB39A)}",
    ".vnr-end .vnr-nm{font-size:clamp(20px,5vw,30px);font-weight:800;letter-spacing:-.01em;",
    "max-width:min(680px,92%);word-break:keep-all}",
    ".vnr-end .vnr-sub{color:var(--vnr-sub,#A79680);font-size:13px}",
    ".vnr-end .vnr-row{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin-top:6px}",
    "@media(prefers-reduced-motion:no-preference){",
    ".vnr-afffloat.vnr-go{animation:vnrAffPop 1.15s ease-out forwards}",
    ".vnr-aff.vnr-bump{animation:vnrAffBump .42s ease-out}",
    ".vnr-progbar i{transition:width .28s ease}",
    ".vnr-end{animation:vnrEndIn .9s ease-out}",
    ".vnr-end .vnr-nm{animation:vnrEndUp .9s ease-out}}",
    "@media(prefers-reduced-motion:reduce){.vnr-img img{transition:none}}",
    "@keyframes vnrAffPop{0%{opacity:0;transform:translate(-50%,-10%) scale(.75)}",
    "22%{opacity:1;transform:translate(-50%,-60%) scale(1.14)}",
    "100%{opacity:0;transform:translate(-50%,-150%) scale(1)}}",
    "@keyframes vnrAffBump{0%,100%{transform:scale(1)}45%{transform:scale(1.16)}}",
    "@keyframes vnrEndIn{from{opacity:0}to{opacity:1}}",
    "@keyframes vnrEndUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}",
    "@media(max-width:720px){",
    ".vnr-btn{padding:9px 12px;font-size:12.5px}",
    ".vnr-dlg{bottom:calc(14px + env(safe-area-inset-bottom));padding:13px 16px}",
    ".vnr-dlg.vnr-top{top:calc(58px + env(safe-area-inset-top))}",
    ".vnr-text{font-size:var(--vnr-fs,16px);max-height:34vh}",
    ".vnr-hint{font-size:11px;text-align:center;opacity:.62}",
    ".vnr-choices{max-height:calc(100% - 96px);gap:10px}",
    ".vnr-choices button{padding:12px 15px;font-size:14.5px}",
    ".vnr-set{right:8px;left:8px;width:auto}",
    ".vnr-log,.vnr-scenes{inset:6% 5%}}",
    /* 세로 스크롤 리딩(renderScroll)의 구조 CSS — 레이아웃·타이포·간격은 여기 한 벌뿐이다.
       두 호스트(스튜디오·감상본)는 자기 껍데기(고정 오버레이·상단바)와 팔레트 토큰만 얹는다:
         --vnr-line(구분선) · --vnr-sub(나레이션) · --vnr-accent(화 머리) · --vnr-pick(선택지)
       renderScroll 이 컨테이너에 .vnr-scroll 을 붙여 주므로 호스트는 선택자를 몰라도 된다. */
    ".vnr-scroll{max-width:820px;margin:0 auto;",
    "padding-left:env(safe-area-inset-left);padding-right:env(safe-area-inset-right);",
    "padding-bottom:calc(44px + env(safe-area-inset-bottom))}",
    ".vnr-scroll .cut img{width:100%;display:block}",
    ".vnr-scroll .say{padding:12px 18px;border-bottom:1px solid var(--vnr-line,#453828);",
    "line-height:1.6;word-break:keep-all;overflow-wrap:anywhere}",
    ".vnr-scroll .say b{font-weight:800}",
    ".vnr-scroll .say .nar{color:var(--vnr-sub,#A79680);font-style:italic;display:block;",
    "text-align:center}",
    ".vnr-scroll .say .pick{color:var(--vnr-pick,#D9A441)}",
    ".vnr-scroll .ep{padding:20px 18px 9px;color:var(--vnr-accent,#5FB39A);font-weight:800;",
    "font-size:13px;letter-spacing:.06em;border-bottom:1px solid var(--vnr-line,#453828)}",
    "@media(max-width:720px){.vnr-scroll .say{padding:11px 14px}",
    ".vnr-scroll .ep{padding:16px 14px 8px}}",
    /* 폰(터치): 툴바는 한 줄을 넘지 않는다 — 3줄로 접혀 그림 상단을 상시 덮던 문제.
       보조 버튼은 [⋯] 안으로 들어가고(.vnr-more), 남은 것은 3초 뒤 스스로 물러난다. */
    "@media(pointer:coarse){",
    ".vnr-bar{flex-wrap:nowrap;gap:5px;max-width:none;",
    "left:calc(8px + env(safe-area-inset-left));right:calc(8px + env(safe-area-inset-right))}",
    ".vnr-bar>.vnr-btn{padding:8px 10px;font-size:12px;white-space:nowrap;flex:0 0 auto}",
    ".vnr-bar>.vnr-chip{padding:6px 9px;font-size:11.5px;white-space:nowrap;",
    "flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis}",
    "}"
  ].join("");

  var cssDone = false;
  function injectCss() {
    if (cssDone || D.getElementById("vnr-css")) { cssDone = true; return; }
    cssDone = true;
    var s = D.createElement("style");
    s.id = "vnr-css";
    s.textContent = CSS;
    (D.head || D.documentElement).appendChild(s);
  }

  /* -------------------------------------------------------------- 데이터 정규화 */
  function epNum(v) {
    if (typeof v === "number" && !isNaN(v) && v > 0) return Math.floor(v);
    var n = parseInt(String(v == null ? "" : v).trim(), 10);
    return (!isNaN(n) && n > 0) ? n : null;
  }

  function normScene(s) {
    s = (s && typeof s === "object") ? s : {};
    var o = {
      id: String(s.id == null ? "" : s.id),
      order: s.order,
      purpose: String(s.purpose == null ? "" : s.purpose),
      img: s.img || "",
      lines: []
    };
    var lines = Array.isArray(s.lines) ? s.lines : [];
    for (var i = 0; i < lines.length; i++) {
      var l = lines[i];
      if (!l || typeof l !== "object") continue;
      o.lines.push({ n: String(l.n || ""), c: l.c || null,
                     t: String(l.t == null ? "" : l.t), p: l.p === "top" ? "top" : "bottom" });
    }
    var ep = epNum(s.ep);
    if (ep) o.ep = ep;
    if (Array.isArray(s.choices) && s.choices.length) o.choices = s.choices.filter(function (c) {
      return c && typeof c === "object";
    });
    if (Array.isArray(s.branch) && s.branch.length) o.branch = s.branch.filter(function (b) {
      return b && typeof b === "object" && b.goto;
    });
    // 엔딩 표기 정규화: 규약은 ending:true + ending_label. 예전 데이터의 ending:"이름" 도 받아준다.
    var label = String(s.ending_label || "").trim();
    if (typeof s.ending === "string") {
      if (s.ending.trim()) { o.ending = true; label = label || s.ending.trim(); }
    } else if (s.ending) o.ending = true;
    if (o.ending && label) o.ending_label = label;
    return o;
  }

  function normData(d) {
    d = (d && typeof d === "object") ? d : {};
    var scenes = (Array.isArray(d.scenes) ? d.scenes : []).map(normScene);
    var eps = [];
    var raw = Array.isArray(d.episodes) ? d.episodes : [];
    for (var i = 0; i < raw.length; i++) {
      var e = raw[i];
      if (!e || typeof e !== "object") continue;
      var n = epNum(e.ep != null ? e.ep : e.episode);
      if (n) eps.push({ ep: n, title: String(e.title || "").trim() });
    }
    var dating = (d.dating && typeof d.dating === "object") ? d.dating : null;
    return { title: String(d.title || ""), scenes: scenes, dating: dating, episodes: eps };
  }

  /* Tab 가둠 — 열린 상자 밖으로 포커스가 새지 않게 한다.
   * mount 밖(모듈 최상위)에 둔 이유: 스튜디오의 오버레이(라이트박스·세로 스크롤·재인증 안내)도
   * 같은 규칙을 써야 하는데, 규칙이 두 벌이 되면 반드시 한쪽만 고쳐진다.
   * VNRuntime.trapTab(box, e) 로 노출한다 — 호스트는 keydown 에서 그대로 넘기면 된다.
   */
  function trapTab(box, e) {
    if (!box || !e || e.key !== "Tab") return;
    var f = Array.prototype.slice.call(box.querySelectorAll(FOCUSABLE))
      .filter(function (n) { return n.offsetWidth > 0 || n.offsetHeight > 0; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1], cur = D.activeElement;
    if (e.shiftKey && (cur === first || !box.contains(cur))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (cur === last || !box.contains(cur))) { e.preventDefault(); first.focus(); }
  }

  /** 이름표 글자색 자동 — 배경 밝기에 따라 검정/흰색 (WCAG 대비 확보) */
  function readableInk(hex) {
    var h = String(hex || "").replace("#", "");
    if (h.length < 6) return "#fff";
    var r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    if (isNaN(r) || isNaN(g) || isNaN(b)) return "#fff";
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? "#17110D" : "#fff";
  }

  /* ======================================================== 세로 스크롤 리딩
   * "위에서 아래로 쭉 읽는" 웹툰형 읽기 화면. 스튜디오와 감상본이 각자 같은 DOM 을
   * 따로 만들고 있었고(그래서 이미 갈렸다 — 읽던 위치 저장은 스튜디오에만 있었다),
   * 여기 하나로 합쳤다. 재생 엔진과 달리 상태가 없으므로 mount 밖의 독립 함수다.
   *
   *   renderScroll(data, container, opts) → {count, save(), restore(), destroy()}
   *   opts = {imageSrc(sc,"scroll"), epLabel(ep), nameColor, scroller, storageKey}
   *     scroller    실제로 스크롤되는 요소(위치 저장·복원의 기준). 없으면 그리기만 한다.
   *     storageKey  주면 "<key>:scroll:<제목>" 에 읽던 위치를 저장한다(엔진의 vn:pos 와 별도).
   *
   * 클래스 이름은 두 호스트의 기존 CSS 규약을 그대로 쓴다 —
   *   .cut(장면 블록) · .ep(화 머리) · .say(대사 줄) · .nar(나레이션) · .pick(선택지)
   * 그래서 호스트는 CSS 한 줄 바꾸지 않고 이 함수로 갈아탈 수 있다.
   */
  function renderScroll(data, container, opts) {
    if (!container || !container.appendChild) return null;
    opts = opts || {};
    injectCss();                       // 구조 CSS 는 엔진이 들고 있다(호스트엔 팔레트 토큰만)
    container.classList.add("vnr-scroll");
    var d = normData(data);
    var imgOf = (typeof opts.imageSrc === "function")
      ? opts.imageSrc : function (sc) { return (sc && sc.img) || ""; };
    var epLabel = (typeof opts.epLabel === "function")
      ? opts.epLabel : function (ep) { return ep + "화"; };
    var nameColor = (opts.nameColor == null) ? "" : String(opts.nameColor);
    var scroller = (opts.scroller && opts.scroller.addEventListener) ? opts.scroller : null;
    var key = opts.storageKey ? String(opts.storageKey) + ":scroll:" + (d.title || "_") : "";
    var timers = [], scrollTimer = null;

    container.replaceChildren();
    var curEp = null, count = 0;
    d.scenes.forEach(function (sc) {
      var url = imgOf(sc, "scroll") || "";
      var lines = sc.lines || [], choices = sc.choices || [];
      if (!url && !lines.length && !choices.length) return;   // 그릴 것이 없는 장면은 건너뛴다
      var blk = el("div", "cut");
      blk.setAttribute("data-sid", sc.id);                    // 위치 복원의 기준점
      if (sc.ep && sc.ep !== curEp) {
        curEp = sc.ep;
        blk.appendChild(el("div", "ep", epLabel(sc.ep)));
      }
      if (url) {
        var im = el("img");
        im.src = url;
        im.alt = sc.purpose || sc.id;
        im.loading = "lazy";
        im.decoding = "async";
        blk.appendChild(im);
      }
      lines.forEach(function (l) {
        var s = el("div", "say");
        if (l.n) {
          var b = el("b", null, l.n + "  ");
          b.style.color = l.c || nameColor;
          s.appendChild(b);
          s.appendChild(el("span", null, l.t || ""));
        } else s.appendChild(el("span", "nar", l.t || ""));
        blk.appendChild(s);
      });
      choices.forEach(function (c) {          // 스크롤 모드는 선택지를 목록으로만 보여준다
        var s = el("div", "say");
        s.appendChild(el("span", "pick", "▸ " + ((c && c.text) || "")));
        blk.appendChild(s);
      });
      container.appendChild(blk);
      count++;
    });

    /* 읽던 위치는 픽셀로 기억하지 않는다 — 이미지가 lazy 로 늦게 실려 높이가 계속 바뀌기
       때문이다. "어느 장면 블록의 어디쯤"으로 적어 두고, 복원은 몇 번 나눠 다시 맞춘다. */
    function save() {
      if (!key || !scroller) return;
      var y = scroller.scrollTop, sid = "", off = y, kids = container.children;
      for (var i = 0; i < kids.length; i++) {
        if (kids[i].offsetTop <= y + 4) {
          sid = kids[i].getAttribute("data-sid") || "";
          off = y - kids[i].offsetTop;
        } else break;
      }
      try {
        global.localStorage.setItem(key, JSON.stringify({ sid: sid, off: off, y: y }));
      } catch (e) { /* 저장 불가여도 읽기는 계속된다 */ }
    }
    function restore() {
      if (!key || !scroller) return false;
      var p = null;
      try { p = JSON.parse(global.localStorage.getItem(key) || "null"); } catch (e) { p = null; }
      if (!p || typeof p !== "object") return false;
      var go = function () {
        if (scroller.hidden) return;               // 닫힌 뒤 늦게 도착한 타이머는 무시
        if (p.sid) {
          var kids = container.children;
          for (var i = 0; i < kids.length; i++) {
            if (kids[i].getAttribute("data-sid") === p.sid) {
              scroller.scrollTop = kids[i].offsetTop + (p.off || 0);
              return;
            }
          }
        }
        scroller.scrollTop = p.y || 0;
      };
      go();
      [160, 700, 1800].forEach(function (ms) { timers.push(global.setTimeout(go, ms)); });
      return true;
    }
    function onScroll() {
      global.clearTimeout(scrollTimer);
      scrollTimer = global.setTimeout(save, 250);
    }
    if (key && scroller) scroller.addEventListener("scroll", onScroll, { passive: true });
    function destroy() {
      if (key && scroller) scroller.removeEventListener("scroll", onScroll);
      global.clearTimeout(scrollTimer);
      timers.forEach(function (t) { global.clearTimeout(t); });
      timers = [];
    }
    return { count: count, save: save, restore: restore, destroy: destroy };
  }

  /* ================================================================ mount */
  function mount(opts) {
    opts = opts || {};
    injectCss();
    var host = (opts.root && opts.root.appendChild) ? opts.root : D.body;
    var data = normData(opts.data);
    var imgOf = (typeof opts.imageSrc === "function")
      ? opts.imageSrc : function (sc) { return (sc && sc.img) || ""; };
    var ns = String(opts.storageKey || "vn");

    function fire(name, arg) {
      var f = opts[name];
      if (typeof f !== "function") return undefined;
      try { return f(arg); } catch (e) { return undefined; }
    }

    // ---- 상태 ----
    var vi = 0, di = 0, ended = false, revealing = false, fullText = "", awaiting = false, hintLeft = 0;
    var autoOn = false, skipOn = false, isOpen = false;
    var revealTimer = null, autoTimer = null, affTimer = null, wakeLock = null, idleTimer = null;
    var aff = 0, navStack = [], backlog = [], backlogKeys = new Set(), seen = new Set();
    var preloaded = new Set(), lastFocus = null, returnFocus = null;
    var SET = { textSpeed: 26, autoDelay: 1500, fs: 17, skipAll: false, cinema: false };

    // ---- 저장(이 브라우저 로컬) ----
    var suffix = function () { return ":" + (data.title || "_"); };
    var kPos = function () { return ns + ":pos" + suffix(); };
    var kHist = function () { return ns + ":hist" + suffix(); };
    var kSeen = function () { return ns + ":seen" + suffix(); };
    var kSet = ns + ":settings";
    function lsGet(k) { try { return global.localStorage.getItem(k); } catch (e) { return null; } }
    function lsSet(k, v) { try { global.localStorage.setItem(k, v); } catch (e) { /* 저장 불가여도 감상은 계속 */ } }
    function lsDel(k) { try { global.localStorage.removeItem(k); } catch (e) { /* 무시 */ } }
    function jparse(raw, fb) { try { var v = JSON.parse(raw); return v == null ? fb : v; } catch (e) { return fb; } }

    function loadSet() {
      var s = jparse(lsGet(kSet), {});
      if (!s || typeof s !== "object") return;
      if (typeof s.textSpeed === "number") SET.textSpeed = Math.max(0, Math.min(80, s.textSpeed));
      if (typeof s.autoDelay === "number") SET.autoDelay = Math.max(400, Math.min(4000, s.autoDelay));
      if (typeof s.fs === "number") SET.fs = Math.max(14, Math.min(26, s.fs));
      if (typeof s.skipAll === "boolean") SET.skipAll = s.skipAll;
      if (typeof s.cinema === "boolean") SET.cinema = s.cinema;
    }
    function saveSet() { lsSet(kSet, JSON.stringify(SET)); applyFs(); }
    function loadPos() {
      var p = jparse(lsGet(kPos()), null);
      return (p && typeof p === "object") ? p : null;
    }
    function savePos() {
      lsSet(kPos(), JSON.stringify({ vi: vi, di: di, aff: aff, stack: navStack.slice(-300) }));
      fire("onSavedChange", true);
    }
    function clearPos() { lsDel(kPos()); fire("onSavedChange", false); }
    function saveHist() { lsSet(kHist(), JSON.stringify(backlog.slice(-500))); }
    function loadHist() { var h = jparse(lsGet(kHist()), []); return Array.isArray(h) ? h : []; }
    function loadSeen() {
      var s = jparse(lsGet(kSeen()), []);
      seen = new Set(Array.isArray(s) ? s : []);
    }
    /** 이 대사를 처음 보는가 — 스킵이 새 대사에서 멈추는 근거. → 이미 봤으면 true */
    function markSeen() {
      var k = vi + ":" + di, was = seen.has(k);
      if (!was) {
        seen.add(k);
        lsSet(kSeen(), JSON.stringify(Array.from(seen).slice(-5000)));
      }
      return was;
    }

    // ---- 화(episode) ----
    /** 실제로 실린 화만, 매니페스트 제목을 붙여 번호순으로 */
    function presentEps() {
      var titles = {}, i;
      for (i = 0; i < data.episodes.length; i++) titles[data.episodes[i].ep] = data.episodes[i].title;
      var have = {};
      for (i = 0; i < data.scenes.length; i++) {
        var e = data.scenes[i].ep;
        if (e) have[e] = 1;
      }
      return Object.keys(have).map(Number).sort(function (a, b) { return a - b; })
        .map(function (n) { return { ep: n, title: titles[n] || "" }; });
    }
    function epLabel(ep) {
      var t = "";
      var list = presentEps();
      for (var i = 0; i < list.length; i++) if (list[i].ep === ep) t = list[i].title;
      return ep + "화" + (t ? " · " + t : "");
    }
    function epFirstIndex(ep) {
      for (var i = 0; i < data.scenes.length; i++) if (data.scenes[i].ep === ep) return i;
      return -1;
    }

    // ---- 분기 엔진(호감도·선택지·엔딩) ----
    var affMax = function () { return (data.dating && data.dating.max) || 100; };
    var affStart = function () {
      return (data.dating && typeof data.dating.start_affection === "number")
        ? data.dating.start_affection : 30;
    };
    var clampAff = function (v) { return Math.max(0, Math.min(affMax(), v)); };
    var dlen = function (sc) { return ((sc && sc.lines) || []).length || 1; };  // 대사 0줄이면 purpose 1줄
    var idxOf = function (id) {
      for (var i = 0; i < data.scenes.length; i++) if (data.scenes[i].id === id) return i;
      return -1;
    };

    /* ------------------------------------------------------------------ DOM */
    var E = {};
    function mkBtn(label, title, fn, cls) {
      var b = el("button", "vnr-btn" + (cls ? " " + cls : ""), label);
      b.type = "button";
      if (title) b.title = title;
      b.addEventListener("click", fn);
      return b;
    }
    function panel(cls, heading) {
      var p = el("div", "vnr-panel " + cls);
      p.hidden = true;
      p.setAttribute("role", "dialog");
      p.setAttribute("aria-modal", "true");
      p.setAttribute("aria-label", heading);
      p.appendChild(el("h3", null, heading));
      return p;
    }

    E.stage = el("div", "vnr");
    E.stage.setAttribute("role", "dialog");
    E.stage.setAttribute("aria-modal", "true");
    E.stage.setAttribute("aria-label", "비주얼 노벨 뷰어");
    E.stage.setAttribute("aria-hidden", "true");
    E.stage.tabIndex = -1;

    E.img = el("div", "vnr-img");
    E.fx = el("div", "vnr-fx");
    E.fx.hidden = true;
    E.fx.appendChild(el("i", "vnr-t"));
    E.fx.appendChild(el("i", "vnr-b"));
    E.click = el("div", "vnr-click");
    E.progBar = el("div", "vnr-progbar");
    E.progFill = el("i");
    E.progBar.appendChild(E.progFill);
    E.affFloat = el("div", "vnr-afffloat");
    E.affFloat.hidden = true;
    E.affFloat.setAttribute("aria-hidden", "true");

    E.bar = el("div", "vnr-bar");
    E.bar.setAttribute("role", "toolbar");
    E.bar.setAttribute("aria-label", "감상 도구");
    E.chip = el("span", "vnr-chip");
    E.aff = el("span", "vnr-chip vnr-aff");
    E.aff.hidden = true;
    E.bAuto = mkBtn("자동", "자동 진행 (A)", function () { setAuto(!autoOn); });
    E.bSkip = mkBtn("스킵", "스킵 (Ctrl)", function () { setSkip(!skipOn); });
    E.bScenes = mkBtn("장면", "장면 이동 (C)", function () { togglePanel(E.pScenes); });
    E.bLog = mkBtn("기록", "지난 대사 (L)", function () { togglePanel(E.pLog); });
    E.bSet = mkBtn("설정", "설정 (S)", function () { togglePanel(E.pSet); });
    E.bHide = mkBtn("숨기기", "화면 보기 — UI 숨김 (H)", function () { setUiHidden(!uiHidden()); });
    E.bFull = mkBtn("전체화면", "전체화면 (F)", toggleFull);
    E.bExit = mkBtn("닫기", "닫기 (Esc)", function () { exit(); });
    E.bAuto.setAttribute("aria-pressed", "false");
    E.bSkip.setAttribute("aria-pressed", "false");
    // 호스트 전용 버튼(감상본의 [스크롤] 처럼)은 여기로 끼운다 — 툴바가 두 벌로 갈리지 않게.
    var extraKids = [];
    (Array.isArray(opts.extraButtons) ? opts.extraButtons : []).forEach(function (x) {
      if (!x || !x.label) return;
      extraKids.push(mkBtn(String(x.label), x.title || "", function () {
        if (typeof x.onClick === "function") x.onClick();
      }));
    });
    /* 폰(coarse)에서는 버튼 10~11개가 360px 안에서 두세 줄로 접혀 그림 위를 상시 덮었다.
       한 줄에 남는 것은 진행률·호감도·[자동]·[장면]·[⋯]·[닫기] 뿐이고, 나머지는 같은 버튼
       노드를 [⋯] 메뉴로 옮겨 담는다(버튼을 새로 만들지 않으므로 동작·단축키가 갈리지 않는다). */
    E.more = el("div", "vnr-more");
    E.more.hidden = true;
    E.more.setAttribute("role", "group");
    E.more.setAttribute("aria-label", "다른 도구");
    E.bMore = mkBtn("⋯", "다른 도구", function () { toggleMore(); });
    E.bMore.setAttribute("aria-haspopup", "true");
    E.bMore.setAttribute("aria-expanded", "false");
    E.bMore.setAttribute("aria-label", "다른 도구");
    if (COARSE) {
      [E.chip, E.aff, E.bAuto, E.bScenes, E.bMore, E.bExit].forEach(function (n) {
        E.bar.appendChild(n);
      });
      [E.bLog, E.bSet, E.bSkip, E.bHide, E.bFull].concat(extraKids).forEach(function (n) {
        E.more.appendChild(n);
      });
      E.bar.appendChild(E.more);
      // 메뉴에서 무엇을 고르든 메뉴는 닫는다(버튼 자신의 동작이 먼저 실행된 뒤 버블로 도달).
      E.more.addEventListener("click", function () { closeMore(); });
    } else {
      [E.chip, E.aff, E.bAuto, E.bSkip, E.bScenes, E.bLog, E.bSet, E.bHide, E.bFull]
        .concat(extraKids).concat([E.bExit])
        .forEach(function (n) { E.bar.appendChild(n); });
    }

    E.dlg = el("div", "vnr-dlg");
    E.dlg.setAttribute("role", "group");
    E.dlg.setAttribute("aria-label", "대사");
    E.name = el("span", "vnr-name");
    E.text = el("div", "vnr-text");
    E.hint = el("div", "vnr-hint", COARSE ? HINT_TOUCH : HINT_KEYS);
    E.dlg.appendChild(E.name);
    E.dlg.appendChild(E.text);
    E.dlg.appendChild(E.hint);

    E.choices = el("div", "vnr-choices");
    E.choices.hidden = true;
    E.choices.setAttribute("role", "group");
    E.choices.setAttribute("aria-label", "선택지");

    E.pLog = panel("vnr-log", "지난 대사");
    E.logInner = el("div", "vnr-inner");
    E.pLog.appendChild(E.logInner);
    E.pLog.appendChild(mkBtn("닫기", null, closePanels, "vnr-close"));

    E.pScenes = panel("vnr-scenes", "장면 이동");
    E.scenesInner = el("div", "vnr-inner");
    E.pScenes.appendChild(E.scenesInner);
    E.pScenes.appendChild(mkBtn("닫기", null, closePanels, "vnr-close"));

    E.pSet = panel("vnr-set", "설정");
    (function buildSettings() {
      function range(labelText, min, max, step, key, fmt) {
        var lab = el("label"), head = el("span"), val = el("span");
        head.appendChild(D.createTextNode(labelText + " "));
        head.appendChild(val);
        var inp = el("input");
        inp.type = "range";
        inp.min = String(min); inp.max = String(max); inp.step = String(step);
        inp.addEventListener("input", function (e) {
          SET[key] = +e.target.value;
          val.textContent = fmt(SET[key]);
          if (key === "fs") applyFs();
          saveSet();
        });
        lab.appendChild(head);
        lab.appendChild(inp);
        E.pSet.appendChild(lab);
        return { input: inp, val: val, fmt: fmt, key: key };
      }
      function check(labelText, key, after) {
        var lab = el("label", "vnr-ck"), inp = el("input");
        inp.type = "checkbox";
        inp.addEventListener("change", function (e) {
          SET[key] = !!e.target.checked;
          saveSet();
          if (after) after();
        });
        lab.appendChild(inp);
        lab.appendChild(D.createTextNode(" " + labelText));
        E.pSet.appendChild(lab);
        return inp;
      }
      E.ctl = {};
      E.ctl.speed = range("텍스트 속도", 0, 80, 2, "textSpeed",
        function (v) { return v <= 0 ? "즉시" : v + "ms/자"; });
      E.ctl.delay = range("자동 진행 딜레이", 400, 4000, 100, "autoDelay",
        function (v) { return (v / 1000).toFixed(1) + "초"; });
      E.ctl.fs = range("글자 크기", 14, 26, 1, "fs", function (v) { return v + "px"; });
      E.ctl.skipAll = check("스킵이 안 읽은 대사도 건너뜀 (끄면 새 대사에서 자동 정지)", "skipAll");
      E.ctl.cinema = check("시네마틱 모드 (비네트 + 레터박스)", "cinema", applyCinema);
      E.epRow = el("label");
      E.epRow.hidden = true;
      E.epRow.appendChild(el("span", null, "화 이동"));
      E.epSeg = el("div", "vnr-seg");
      E.epRow.appendChild(E.epSeg);
      E.pSet.appendChild(E.epRow);
      E.pSet.appendChild(mkBtn("닫기", null, closePanels, "vnr-close"));
    })();

    E.end = el("div", "vnr-end");
    E.end.hidden = true;
    E.end.setAttribute("role", "dialog");
    E.end.setAttribute("aria-modal", "true");
    E.end.setAttribute("aria-label", "엔딩");
    E.endName = el("div", "vnr-nm");
    E.endSub = el("div", "vnr-sub");
    var endRow = el("div", "vnr-row");
    E.bRestart = mkBtn("처음부터", null, function () { hideEnd(); clearPos(); start(false); });
    endRow.appendChild(E.bRestart);
    if (typeof opts.onGallery === "function") {
      endRow.appendChild(mkBtn("갤러리", null, function () { hideEnd(); exit(); fire("onGallery"); }));
    }
    endRow.appendChild(mkBtn("닫기", null, function () { hideEnd(); exit(); }));
    E.end.appendChild(el("div", "vnr-ttl", "ENDING"));
    E.end.appendChild(E.endName);
    E.end.appendChild(E.endSub);
    E.end.appendChild(endRow);

    E.sr = el("div", "vnr-sr");
    E.sr.setAttribute("aria-live", "polite");
    E.sr.setAttribute("role", "status");

    [E.img, E.fx, E.click, E.progBar, E.affFloat, E.bar, E.dlg, E.choices,
      E.pLog, E.pScenes, E.pSet, E.end, E.sr].forEach(function (n) { E.stage.appendChild(n); });
    host.appendChild(E.stage);

    var say = function (t) { E.sr.textContent = t; };

    /* ------------------------------------------------------------ 표시 갱신 */
    function applyFs() { E.stage.style.setProperty("--vnr-fs", SET.fs + "px"); }
    function applyCinema() { E.fx.hidden = !SET.cinema; }
    function uiHidden() { return E.stage.classList.contains("vnr-uihidden"); }
    function barIdle() { return E.stage.classList.contains("vnr-baridle"); }
    /** 툴바가 보이지 않을 때는 포커스·스크린리더에서도 빼 둔다(숨김 두 갈래를 한 곳에서 반영) */
    function syncBarInert() { E.bar.inert = uiHidden() || barIdle(); }
    function setUiHidden(h) {
      E.stage.classList.toggle("vnr-uihidden", h);
      if (h) closeMore();
      syncBarInert();
    }
    function setBarIdle(on) {
      E.stage.classList.toggle("vnr-baridle", !!on);
      if (on) closeMore();
      syncBarInert();
    }
    /* 폰에서 툴바는 3초 쉬면 스스로 물러나고, 화면을 건드리면(탭·스와이프·키) 돌아온다.
       대사창은 건드리지 않는다 — 읽는 중에 글이 사라지면 안 된다. */
    function wakeBar() {
      if (!COARSE) return;
      clearTimeout(idleTimer);
      setBarIdle(false);
      if (!isOpen) return;
      idleTimer = setTimeout(function () {
        if (!isOpen || uiHidden() || panelOpen() || !E.end.hidden || !E.more.hidden) return;
        setBarIdle(true);
      }, BAR_IDLE_MS);
    }
    function closeMore() {
      if (!E.more || E.more.hidden) return;
      E.more.hidden = true;
      E.bMore.setAttribute("aria-expanded", "false");
    }
    function toggleMore() {
      if (!E.more) return;
      var open = E.more.hidden;
      E.more.hidden = !open;
      E.bMore.setAttribute("aria-expanded", open ? "true" : "false");
      wakeBar();
      if (open) {
        var f = E.more.querySelector("button");
        if (f && f.focus) f.focus();
      }
    }
    function toggleFull() {
      var s = E.stage;
      if (!D.fullscreenElement) {
        var rq = s.requestFullscreen || s.webkitRequestFullscreen;
        if (rq) { try { rq.call(s); } catch (e) { /* 사용자 제스처 없이 거부되면 무시 */ } }
      } else {
        var ex = D.exitFullscreen || D.webkitExitFullscreen;
        if (ex) { try { ex.call(D); } catch (e) { /* 무시 */ } }
      }
    }

    function updateAff(delta) {
      if (!data.dating) { E.aff.hidden = true; E.affFloat.hidden = true; return; }
      E.aff.hidden = false;
      E.aff.textContent = COARSE ? ("♥" + aff + "/" + affMax()) : ("♥ " + aff + " / " + affMax());
      if (!delta) return;
      E.affFloat.textContent = (delta > 0 ? "+♥ " : "−♥ ") + Math.abs(delta);
      E.affFloat.className = "vnr-afffloat " + (delta > 0 ? "vnr-up" : "vnr-down");
      E.affFloat.hidden = false;
      if (!REDUCE) {
        void E.affFloat.offsetWidth;          // 연속 선택 시 애니메이션 재시작
        E.affFloat.classList.add("vnr-go");
        E.aff.classList.remove("vnr-bump");
        void E.aff.offsetWidth;
        E.aff.classList.add("vnr-bump");
        setTimeout(function () { E.aff.classList.remove("vnr-bump"); }, 460);
      }
      clearTimeout(affTimer);
      affTimer = setTimeout(function () {
        E.affFloat.hidden = true;
        E.affFloat.classList.remove("vnr-go");
      }, REDUCE ? 900 : 1200);
      say(delta > 0 ? "호감도 " + delta + " 올라감" : "호감도 " + Math.abs(delta) + " 내려감");
    }

    function updateProg() {
      var sc = data.scenes[vi], dl = dlen(sc), total = data.scenes.length || 1;
      var full = (sc && sc.ep ? sc.ep + "화 · " : "") + (vi + 1) + " / " + total
        + (dl > 1 ? "  ·  " + (di + 1) + "/" + dl : "");
      // 폰에서는 한 줄 툴바의 폭을 버튼에 양보한다(전체 표기는 title 로 남긴다)
      E.chip.textContent = COARSE
        ? ((sc && sc.ep ? sc.ep + "화 " : "") + (vi + 1) + "/" + total) : full;
      E.chip.title = full;
      var p = ended ? 1 : Math.max(0, Math.min(1, (vi + (di + 1) / dl) / total));
      E.progFill.style.width = (p * 100).toFixed(2) + "%";
    }

    /* -------------------------------------------------------------- 이미지 */
    function preloadAround(center) {
      var lo = Math.max(0, center - PRELOAD_SPAN);
      var hi = Math.min(data.scenes.length - 1, center + PRELOAD_SPAN);
      if (preloaded.size > 60) preloaded = new Set();
      for (var i = lo; i <= hi; i++) {
        var u = imgOf(data.scenes[i], "full");
        // data URI 는 이미 문서 안에 있다 — 다시 디코드할 이유가 없다(감상본은 전부 data URI).
        if (!u || u.slice(0, 5) === "data:" || preloaded.has(u)) continue;
        preloaded.add(u);
        var p = new global.Image();
        p.decoding = "async";
        p.src = u;
      }
    }
    function clearImgs(keep) {
      var imgs = E.img.querySelectorAll("img");
      for (var i = 0; i < imgs.length; i++) if (imgs[i] !== keep) imgs[i].remove();
    }
    function emptyNote(sc, why) {
      clearImgs(null);
      if (!E.img.querySelector(".vnr-empty")) {
        E.img.appendChild(el("div", "vnr-empty", why + " " + ((sc && (sc.purpose || sc.id)) || "")));
      }
    }
    function renderImg() {
      var sc = data.scenes[vi], url = imgOf(sc, "full");
      var old = E.img.querySelector(".vnr-empty");
      if (old) old.remove();
      if (!url) { emptyNote(sc, "(이미지 없음)"); preloadAround(vi); return; }
      var cur = E.img.querySelector("img.vnr-show");
      if (cur && cur.getAttribute("src") === url) { preloadAround(vi); return; }
      var im = el("img");
      im.src = url;
      im.alt = (sc && (sc.purpose || sc.id)) || "";
      im.decoding = "async";
      var show = function () {
        im.classList.add("vnr-show");
        setTimeout(function () { clearImgs(im); }, REDUCE ? 0 : 540);
      };
      im.onerror = function () { emptyNote(sc, "(이미지를 불러올 수 없음)"); };
      E.img.appendChild(im);
      if (REDUCE || im.complete) global.requestAnimationFrame(show); else im.onload = show;
      preloadAround(vi);
    }

    /* -------------------------------------------------------------- 대사 */
    function record(name, text, color) {
      var k = vi + ":" + di;
      if (backlogKeys.has(k)) return;
      backlogKeys.add(k);
      backlog.push({ n: name, t: text, c: color, vi: vi, di: di });
      saveHist();
    }
    function typeText(t) {
      clearInterval(revealTimer);
      fullText = t;
      if (REDUCE || skipOn || SET.textSpeed <= 0) {
        E.text.textContent = t;
        E.text.scrollTop = E.text.scrollHeight;
        revealing = false;
        onShown();
        return;
      }
      revealing = true;
      var cs = Array.from(t), i = 0;        // 코드포인트 단위 — 이모지가 쪼개지지 않는다
      E.text.textContent = "";
      revealTimer = setInterval(function () {
        i++;
        E.text.textContent = cs.slice(0, i).join("");
        E.text.scrollTop = E.text.scrollHeight;
        if (i >= cs.length) { clearInterval(revealTimer); revealing = false; onShown(); }
      }, Math.max(6, SET.textSpeed));
    }
    function completeText() {
      clearInterval(revealTimer);
      E.text.textContent = fullText;
      revealing = false;
      onShown();
    }
    function onShown() {
      clearTimeout(autoTimer);
      if (!isOpen || ended || awaiting || panelOpen()) return;
      if (skipOn) {
        autoTimer = setTimeout(function () { if (!panelOpen()) advance(1); }, 45);
        return;
      }
      if (autoOn) {
        autoTimer = setTimeout(function () { if (!panelOpen()) advance(1); },
          SET.autoDelay + fullText.length * 22);
      }
    }

    function showLine() {
      var sc = data.scenes[vi];
      if (!sc) return;
      updateProg();
      if (hintLeft > 0 && --hintLeft === 0) E.hint.hidden = true;   // 조작법을 익힌 뒤엔 자리를 돌려준다
      var wasSeen = markSeen();
      if (skipOn && !wasSeen && !SET.skipAll) setSkip(false);   // 스킵은 안 읽은 대사에서 멈춘다
      var line = (sc.lines || [])[di];
      E.dlg.classList.toggle("vnr-top", !!(line && line.p === "top"));
      var body = line ? (line.t || "") : (sc.purpose || "");
      if (line && line.n) {
        E.dlg.classList.remove("vnr-narr");
        E.name.style.display = "inline-block";
        var col = line.c || "#2F6B59";
        E.name.textContent = line.n;
        E.name.style.background = col;
        E.name.style.color = readableInk(col);
        record(line.n, body, col);
        if (!skipOn) say(line.n + ": " + body);
      } else {
        E.dlg.classList.add("vnr-narr");
        E.name.style.display = "none";
        record("", body, null);
        if (!skipOn) say(body);
      }
      typeText(body || "…");
      savePos();
    }

    /* -------------------------------------------------------------- 선택지 */
    function hideChoices() {
      awaiting = false;
      E.choices.hidden = true;
      E.choices.replaceChildren();
      E.dlg.style.opacity = "";
    }
    function showChoices(sc) {
      awaiting = true;
      clearTimeout(autoTimer);
      E.choices.replaceChildren();
      sc.choices.forEach(function (c) {
        var b = el("button", null, c.text || "…");
        b.type = "button";
        b.addEventListener("click", function () { pick(c); });
        E.choices.appendChild(b);
      });
      E.choices.hidden = false;
      E.dlg.style.opacity = ".3";
      say("선택지 " + sc.choices.length + "개 · 위아래 화살표로 고르고 Enter");
      var first = E.choices.firstElementChild;
      if (first && first.focus) first.focus();
    }
    function pick(c) {
      hideChoices();
      var d = c.affection || 0;
      if (d) aff = clampAff(aff + d);
      updateAff(d);
      savePos();
      var nx = c.goto ? idxOf(c.goto) : (vi + 1 < data.scenes.length ? vi + 1 : -1);
      if (nx < 0) { endPlayback(); return; }
      goTo(nx);
    }
    function nextIndex(sc) {
      if (sc.branch && sc.branch.length) {         // 조건 만족하는 첫 분기로(위에서부터)
        for (var i = 0; i < sc.branch.length; i++) {
          var b = sc.branch[i];
          if (aff >= (b.min || 0)) { var j = idxOf(b.goto); if (j >= 0) return j; }
        }
        return -1;
      }
      return vi + 1 < data.scenes.length ? vi + 1 : -1;
    }
    function goTo(idx) {
      var before = vi;
      if (idx !== before) navStack.push(before);   // 온 길을 기억 — ← 가 분기 경로를 거꾸로 따라간다
      vi = idx; di = 0; ended = false;
      hideEnd();
      if (vi !== before) renderImg();
      showLine();
    }

    /* -------------------------------------------------------------- 진행 */
    function advance(step) {
      if (panelOpen()) { closePanels(); return; }
      if (awaiting) return;                    // 선택지 대기 중엔 선택해야 진행
      if (ended) { exit(); return; }
      if (step > 0 && revealing) { completeText(); return; }
      var sc = data.scenes[vi];
      if (!sc) return;
      clearTimeout(autoTimer);
      if (step > 0) {
        if (di + 1 < dlen(sc)) { di++; showLine(); return; }
        if (sc.choices && sc.choices.length) { showChoices(sc); return; }   // 장면 끝 → 선택지
        if (sc.ending) { endPlayback(); return; }                            // 엔딩 장면
        var nx = nextIndex(sc);                                              // 분기 or 선형
        if (nx < 0) { endPlayback(); return; }
        goTo(nx);
        return;
      }
      if (di > 0) { di--; showLine(); return; }
      if (navStack.length) {                   // 분기 뒤 ← 가 엉뚱한 장면으로 가지 않게
        vi = navStack.pop();
        di = dlen(data.scenes[vi]) - 1;
        renderImg(); showLine();
        return;
      }
      if (vi > 0) { vi--; di = dlen(data.scenes[vi]) - 1; renderImg(); showLine(); }
    }

    function endLabelOf(sc) {
      if (!sc) return "";
      // 계약: 엔딩 이름은 ending_label 우선, 없으면 purpose (스튜디오·감상본 동일 우선순위)
      if (sc.ending_label) return String(sc.ending_label);
      if (sc.ending && sc.purpose) return String(sc.purpose);
      return "";
    }
    function endPlayback() {
      var last = data.scenes[vi];
      ended = true;
      clearTimeout(autoTimer);
      clearInterval(revealTimer);
      setAuto(false); setSkip(false);
      hideChoices();
      E.dlg.classList.remove("vnr-top");
      E.dlg.classList.add("vnr-narr");
      E.name.style.display = "none";
      E.text.textContent = "— 끝 —" + (data.title ? "\n\n『" + data.title + "』" : "");
      updateProg();
      clearPos();
      showEnd(last);
    }
    function showEnd(sc) {
      var nm = endLabelOf(sc) || (data.title ? "『" + data.title + "』" : "— 끝 —");
      E.endName.textContent = nm;
      var parts = [];
      if (data.dating) parts.push("호감도 ♥ " + aff + " / " + affMax());
      parts.push("장면 " + data.scenes.length + "개 감상 완료");
      var eps = presentEps();
      if (eps.length > 1) parts.push(eps.length + "화");
      E.endSub.textContent = parts.join("   ·   ");
      closeMore();
      setBarIdle(false);              // 엔딩 카드 위에서 툴바가 사라져 있지 않게
      E.end.hidden = false;
      releaseWake();
      say("엔딩 — " + nm);
      if (E.bRestart.focus) E.bRestart.focus();
    }
    function hideEnd() { E.end.hidden = true; }

    /* -------------------------------------------------------------- 자동/스킵 */
    function requestWake() {
      var nav = global.navigator;
      if (wakeLock || !nav || !nav.wakeLock || !nav.wakeLock.request) return;
      try {
        nav.wakeLock.request("screen").then(function (l) {
          wakeLock = l;
          l.addEventListener("release", function () { wakeLock = null; });
        }, function () { wakeLock = null; });
      } catch (e) { wakeLock = null; }
    }
    function releaseWake() {
      if (!wakeLock) return;
      try { wakeLock.release(); } catch (e) { /* 이미 풀렸으면 무시 */ }
      wakeLock = null;
    }
    function setAuto(on) {
      autoOn = on;
      if (on) skipOn = false;
      E.bAuto.classList.toggle("on", autoOn);
      E.bSkip.classList.toggle("on", skipOn);
      E.bAuto.setAttribute("aria-pressed", autoOn ? "true" : "false");
      E.bSkip.setAttribute("aria-pressed", skipOn ? "true" : "false");
      if (autoOn) requestWake(); else if (!skipOn) releaseWake();
      if (autoOn && !revealing) onShown(); else if (!autoOn) clearTimeout(autoTimer);
    }
    function setSkip(on) {
      skipOn = on;
      if (on) autoOn = false;
      E.bSkip.classList.toggle("on", skipOn);
      E.bAuto.classList.toggle("on", autoOn);
      E.bSkip.setAttribute("aria-pressed", skipOn ? "true" : "false");
      E.bAuto.setAttribute("aria-pressed", autoOn ? "true" : "false");
      if (skipOn) requestWake(); else if (!autoOn) releaseWake();
      if (skipOn) { if (revealing) completeText(); else onShown(); }
      else clearTimeout(autoTimer);
    }

    /* -------------------------------------------------------------- 패널 */
    function panelOpen() { return !E.pLog.hidden || !E.pSet.hidden || !E.pScenes.hidden; }
    function openPanelEl() {
      if (!E.pLog.hidden) return E.pLog;
      if (!E.pSet.hidden) return E.pSet;
      if (!E.pScenes.hidden) return E.pScenes;
      return null;
    }
    function syncExpanded() {
      E.bLog.setAttribute("aria-expanded", E.pLog.hidden ? "false" : "true");
      E.bSet.setAttribute("aria-expanded", E.pSet.hidden ? "false" : "true");
      E.bScenes.setAttribute("aria-expanded", E.pScenes.hidden ? "false" : "true");
    }
    function closePanels() {
      var was = panelOpen();
      E.pLog.hidden = true; E.pSet.hidden = true; E.pScenes.hidden = true;
      syncExpanded();
      if (was && lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) { /* 사라진 노드 */ } }
      lastFocus = null;
      if (was) wakeBar();                 // 패널이 닫혔으니 툴바 유휴 시계를 다시 건다
      if ((autoOn || skipOn) && !revealing && !ended && !awaiting) onShown();
    }
    function togglePanel(p) {
      var wasOpen = !p.hidden;
      closeMore();
      closePanels();
      if (wasOpen) return;
      clearTimeout(autoTimer);
      lastFocus = D.activeElement;
      // 숨김 상태에선 레이아웃 박스가 없어 scrollTop 이 무시된다 → 반드시 펼친 뒤 렌더한다.
      p.hidden = false;
      if (p === E.pLog) renderLog();
      else if (p === E.pScenes) renderSceneJump();
      else if (p === E.pSet) syncSettings();
      syncExpanded();
      var close = p.querySelector(".vnr-close");
      if (close && close.focus) close.focus();
    }
    function renderLog() {
      E.logInner.replaceChildren();
      if (!backlog.length) {
        E.logInner.appendChild(el("div", "vnr-none", "아직 지나온 대사가 없습니다."));
        return;
      }
      backlog.forEach(function (h) {
        var row = el("button", "vnr-line");
        row.type = "button";
        if (h.n) {
          var b = el("b", null, h.n + "  ");
          if (h.c) b.style.color = h.c;
          row.appendChild(b);
          row.appendChild(el("span", null, h.t));
        } else row.appendChild(el("span", "vnr-nar", h.t));
        row.addEventListener("click", function () { jumpTo(h.vi, h.di); });
        E.logInner.appendChild(row);
      });
      E.logInner.scrollTop = E.logInner.scrollHeight;
    }
    function sceneRead(i) {
      var dl = dlen(data.scenes[i]);
      for (var d = 0; d < dl; d++) if (seen.has(i + ":" + d)) return true;
      return false;
    }
    function renderSceneJump() {
      E.scenesInner.replaceChildren();
      var here = null, curEp = null;
      data.scenes.forEach(function (sc, i) {
        if (sc.ep && sc.ep !== curEp) {
          curEp = sc.ep;
          E.scenesInner.appendChild(el("div", "vnr-ephead", epLabel(sc.ep)));
        }
        var it = el("button", "vnr-item" + (i === vi ? " vnr-here" : ""));
        it.type = "button";
        it.appendChild(el("span", "vnr-n", String(sc.order || i + 1)));
        var th = imgOf(sc, "thumb");
        if (th) {
          var im = el("img", "vnr-th");
          im.src = th;
          im.alt = "";
          im.loading = "lazy";
          im.decoding = "async";
          it.appendChild(im);
        } else it.appendChild(el("span", "vnr-thx"));
        var first = (sc.lines || [])[0];
        it.appendChild(el("span", "vnr-tx", sc.purpose || (first && first.t) || sc.id));
        var rd = sceneRead(i);
        it.appendChild(el("span", "vnr-rd" + (rd ? "" : " vnr-no"),
          i === vi ? "● 지금" : (rd ? "읽음" : "새 장면")));
        it.addEventListener("click", function () { jumpTo(i, 0); });
        if (i === vi) here = it;
        E.scenesInner.appendChild(it);
      });
      // 페이지 전체가 딸려 스크롤되지 않도록 scrollIntoView 대신 컨테이너 scrollTop 만 조정한다.
      if (here) {
        var br = E.scenesInner.getBoundingClientRect(), hr = here.getBoundingClientRect();
        if (br.height > 0) E.scenesInner.scrollTop += (hr.top - br.top) - (br.height - hr.height) / 2;
      }
    }
    function syncSettings() {
      E.ctl.speed.input.value = String(SET.textSpeed);
      E.ctl.speed.val.textContent = E.ctl.speed.fmt(SET.textSpeed);
      E.ctl.delay.input.value = String(SET.autoDelay);
      E.ctl.delay.val.textContent = E.ctl.delay.fmt(SET.autoDelay);
      E.ctl.fs.input.value = String(SET.fs);
      E.ctl.fs.val.textContent = E.ctl.fs.fmt(SET.fs);
      E.ctl.skipAll.checked = SET.skipAll;
      E.ctl.cinema.checked = SET.cinema;
      var eps = presentEps();
      E.epSeg.replaceChildren();
      if (eps.length < 2) { E.epRow.hidden = true; return; }
      E.epRow.hidden = false;
      eps.forEach(function (e) {
        var i = epFirstIndex(e.ep);
        if (i < 0) return;
        var b = el("button", null, epLabel(e.ep));
        b.type = "button";
        b.addEventListener("click", function () { goEpisode(i); });
        E.epSeg.appendChild(b);
      });
    }
    function jumpTo(v, d) {
      if (v < 0 || v >= data.scenes.length) return;
      var before = vi;
      ended = false;
      hideEnd();
      if (v !== before) navStack.push(before);
      vi = v;
      di = Math.max(0, Math.min(dlen(data.scenes[v]) - 1, d || 0));
      hideChoices();               // 선택지 대기 상태를 남기면 advance() 가 전부 무시되어 진행 불능이 된다
      clearTimeout(autoTimer);
      closePanels();
      if (vi !== before) renderImg();
      showLine();
    }
    function goEpisode(i) {
      navStack = [];               // 화를 갈아타면 되짚을 경로도 새로 시작한다
      ended = false;
      hideEnd();
      hideChoices();
      closePanels();
      vi = i; di = 0;
      renderImg();
      showLine();
    }

    /* -------------------------------------------------------------- 시작/종료 */
    function bgNodes() {
      var f = opts.backgroundNodes;
      if (typeof f !== "function") return [];
      try { var v = f(); return Array.isArray(v) ? v : []; } catch (e) { return []; }
    }
    function start(resume, at) {
      if (!data.scenes.length) return false;
      loadSeen();
      ended = false;
      hintLeft = HINT_LINES;
      E.hint.hidden = false;
      applyFs();
      applyCinema();
      hideEnd();
      hideChoices();
      var pos = resume ? loadPos() : null;
      if (pos) {
        backlog = loadHist();
        backlogKeys = new Set(backlog.map(function (h) { return h.vi + ":" + h.di; }));
        navStack = Array.isArray(pos.stack)
          ? pos.stack.filter(function (n) {
            return Number.isInteger(n) && n >= 0 && n < data.scenes.length;
          }) : [];
      } else {
        backlog = []; backlogKeys = new Set(); navStack = [];
        saveHist();
      }
      if (typeof at === "number" && at >= 0 && at < data.scenes.length) {
        vi = at; di = 0; navStack = [];
      } else {
        vi = (pos && pos.vi >= 0 && pos.vi < data.scenes.length) ? pos.vi : 0;
        di = (pos && pos.di >= 0 && pos.di < dlen(data.scenes[vi])) ? pos.di : 0;
      }
      aff = clampAff((pos && typeof pos.aff === "number") ? pos.aff : affStart());
      updateAff(0);
      setAuto(false); setSkip(false);
      closePanels();
      setUiHidden(false);
      returnFocus = D.activeElement;
      bgNodes().forEach(function (n) { n.inert = true; });   // 배경 비활성 — 포커스/스크린리더 트랩
      isOpen = true;
      E.stage.classList.add("on");
      E.stage.setAttribute("aria-hidden", "false");
      E.stage.focus();
      wakeBar();                       // 폰: 툴바는 3초 뒤 스스로 물러난다(탭하면 돌아온다)
      preloaded = new Set();
      renderImg();
      showLine();
      return true;
    }
    function exit() {
      clearInterval(revealTimer);
      clearTimeout(autoTimer);
      setAuto(false); setSkip(false);
      hideChoices();
      hideEnd();
      closeMore();
      closePanels();
      clearTimeout(idleTimer);         // 유휴 시계는 닫는 순간 멈춘다(닫힌 뒤 도는 타이머 없음)
      setBarIdle(false);               // 다음에 열 때 툴바가 사라진 채로 시작하지 않게
      releaseWake();
      isOpen = false;
      E.stage.classList.remove("on");
      E.stage.setAttribute("aria-hidden", "true");
      bgNodes().forEach(function (n) { n.inert = false; });
      fire("onSavedChange", !!loadPos());
      if (returnFocus && returnFocus.focus) { try { returnFocus.focus(); } catch (e) { /* 사라진 노드 */ } }
      returnFocus = null;
      fire("onExit");
    }

    /* -------------------------------------------------------------- 입력 */
    function tap() {
      if (uiHidden()) { setUiHidden(false); return; }
      advance(1);
    }
    var swallowClick = false, swallowTimer = null, tx = 0, ty = 0;
    function onTap() {
      wakeBar();
      closeMore();
      if (!swallowClick) tap();
      swallowClick = false;
    }
    function onTouchStart(e) {
      var t = e.changedTouches[0];
      tx = t.clientX; ty = t.clientY;
    }
    function onTouchEnd(e) {
      var t = e.changedTouches[0], dx = t.clientX - tx, dy = t.clientY - ty;
      var adx = Math.abs(dx), ady = Math.abs(dy);
      // 뒤따라 올 click 은 이 손짓의 그림자다. 시계는 **마지막** 손짓 기준으로 다시 건다 —
      // 예전에는 연달아 넘길 때 앞 손짓의 타이머가 먼저 풀려 click 이 한 번 더 진행시켰다.
      swallowClick = true;
      clearTimeout(swallowTimer);
      swallowTimer = setTimeout(function () { swallowClick = false; }, 450);
      wakeBar();
      closeMore();
      if (uiHidden()) { setUiHidden(false); return; }
      // 가로로 TAP_R 을 넘게 끌면 스와이프, 그 안이면 탭. 두 판정이 맞닿아 있어 무반응 구간이 없다.
      if (adx > TAP_R && adx > ady) { advance(dx < 0 ? 1 : -1); return; }
      if (adx <= TAP_R && ady <= TAP_R) advance(1);
      // 세로로 크게 끈 손짓은 대사·선택지 스크롤이다 — 이야기를 넘기지 않는다.
    }
    /* 대사창(.vnr-dlg, z-index:2)이 아래 클릭판(.vnr-click, z-index:1)을 덮고 있다.
       엄지가 놓이는 화면 하단은 거의 항상 대사창이므로, 같은 손짓 판정을 대사창에도 단다 —
       예전에는 그 자리에서 시작한 스와이프가 방향과 무관하게 앞으로만 넘어갔다. */
    [E.click, E.dlg].forEach(function (n) {
      n.addEventListener("click", onTap);
      n.addEventListener("touchstart", onTouchStart, { passive: true });
      n.addEventListener("touchend", onTouchEnd, { passive: true });
    });
    E.bar.addEventListener("touchstart", function () { wakeBar(); }, { passive: true });

    var FORM_TAGS = { INPUT: 1, TEXTAREA: 1, SELECT: 1, OPTION: 1 };
    function typingTarget(e) {
      var t = e && e.target;
      if (!t || !t.tagName) return false;
      return FORM_TAGS[t.tagName] === 1 || t.isContentEditable === true;
    }
    /** 지금 눌러 볼 수 있는 툴바 버튼(숨은 것·[⋯] 안에 접힌 것 제외) — 화살표 이동의 대상 */
    function barButtons() {
      return Array.prototype.slice.call(E.bar.querySelectorAll("button"))
        .filter(function (b) { return !b.disabled && (b.offsetWidth > 0 || b.offsetHeight > 0); });
    }
    function onKeyDown(e) {
      if (!isOpen) return;
      wakeBar();
      // 엔딩 카드가 떠 있으면 버튼으로만 진행 — Space/Enter 가 카드를 지나쳐 닫지 않게
      if (!E.end.hidden) {
        if (e.key === "Escape") { hideEnd(); exit(); }
        return;
      }
      // 설정 슬라이더 위에서 ←/→ 는 값 조절이어야 한다. Escape 만은 언제나 탈출구.
      if (typingTarget(e) && e.key !== "Escape") {
        if (panelOpen()) trapTab(openPanelEl(), e);
        return;
      }
      if (panelOpen()) {
        var box = openPanelEl();
        trapTab(box, e);
        if (e.key === "Escape"
          || (box === E.pLog && (e.key === "l" || e.key === "L"))
          || (box === E.pSet && (e.key === "s" || e.key === "S"))
          || (box === E.pScenes && (e.key === "c" || e.key === "C"))) {
          e.preventDefault();
          closePanels();
        }
        return;
      }
      if (!E.more.hidden && e.key === "Escape") {   // [⋯] 메뉴가 열려 있으면 Esc 는 메뉴만 닫는다
        e.preventDefault();
        closeMore();
        if (E.bMore.focus) E.bMore.focus();
        return;
      }
      if (e.key === "Escape") {
        if (awaiting) {                       // 선택 대기 중에 뷰어가 통째로 닫히지 않게
          var f = E.choices.firstElementChild;
          if (f && f.focus) f.focus();
          say("선택지를 먼저 고르세요. 그만 보려면 [닫기] 버튼을 누르세요.");
          return;
        }
        if (uiHidden()) { setUiHidden(false); return; }
        exit();
        return;
      }
      // 선택지·툴바 버튼 위의 Space/Enter 는 버튼 활성화에 양보한다
      if ((e.key === " " || e.key === "Enter") && e.target && e.target.tagName === "BUTTON") return;
      /* role="toolbar" 규약: 툴바 안에서는 ←/→ 가 이야기가 아니라 버튼 사이를 옮긴다.
         (예전에는 [자동] 에 포커스를 둔 채 ← 를 누르면 대사가 되감겼다 — 선언과 동작이 어긋났다) */
      if (e.target && E.bar.contains(e.target)
        && (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "Home" || e.key === "End")) {
        var tb = barButtons();
        if (tb.length) {
          e.preventDefault();
          var at = tb.indexOf(e.target), to;
          if (e.key === "Home") to = 0;
          else if (e.key === "End") to = tb.length - 1;
          else if (e.key === "ArrowRight") to = (at + 1) % tb.length;
          else to = (at <= 0 ? tb.length - 1 : at - 1);
          if (tb[to] && tb[to].focus) tb[to].focus();
          return;
        }
      }
      if (awaiting) {                          // 선택지: 위아래로 고른다
        var bs = Array.prototype.slice.call(E.choices.querySelectorAll("button"));
        if (!bs.length || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
        e.preventDefault();
        var i = bs.indexOf(D.activeElement);
        bs[e.key === "ArrowDown" ? (i + 1) % bs.length : (i <= 0 ? bs.length - 1 : i - 1)].focus();
        return;
      }
      if (e.key === "ArrowLeft") { advance(-1); return; }
      if (e.key === " " || e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        advance(1);
        return;
      }
      if (e.key === "a" || e.key === "A") setAuto(!autoOn);
      else if (e.key === "l" || e.key === "L") togglePanel(E.pLog);
      else if (e.key === "s" || e.key === "S") togglePanel(E.pSet);
      else if (e.key === "c" || e.key === "C") togglePanel(E.pScenes);
      else if (e.key === "h" || e.key === "H") setUiHidden(!uiHidden());
      else if (e.key === "f" || e.key === "F") toggleFull();
      else if (e.key === "Control" && !skipOn) setSkip(true);
    }
    function onKeyUp(e) { if (isOpen && e.key === "Control" && skipOn) setSkip(false); }
    function onVisible() {                     // 탭 복귀 시 잠금이 풀려 있으면 다시 요청
      if (D.visibilityState === "visible" && isOpen && (autoOn || skipOn)) requestWake();
    }
    D.addEventListener("keydown", onKeyDown);
    D.addEventListener("keyup", onKeyUp);
    D.addEventListener("visibilitychange", onVisible);

    loadSet();
    applyFs();
    applyCinema();
    fire("onSavedChange", !!loadPos());

    /* -------------------------------------------------------------- 핸들 */
    return {
      start: start,
      exit: exit,
      isOpen: function () { return isOpen; },
      index: function () { return vi; },
      setData: function (d) {
        data = normData(d);
        preloaded = new Set();
        if (isOpen) {
          if (vi >= data.scenes.length) vi = Math.max(0, data.scenes.length - 1);
          if (di >= dlen(data.scenes[vi])) di = 0;
          renderImg();
          showLine();
        }
        fire("onSavedChange", !!loadPos());
      },
      data: function () { return data; },
      hasSaved: function () { return !!loadPos(); },
      clearSaved: clearPos,
      settings: function () { return SET; },
      episodes: presentEps,
      epLabel: epLabel,
      epFirstIndex: epFirstIndex,
      goEpisode: function (ep) {
        var i = epFirstIndex(ep);
        return i < 0 ? false : (start(false, i), true);
      },
      destroy: function () {
        exit();
        D.removeEventListener("keydown", onKeyDown);
        D.removeEventListener("keyup", onKeyUp);
        D.removeEventListener("visibilitychange", onVisible);
        E.stage.remove();
      }
    };
  }

  // trapTab 도 함께 내보낸다 — 스튜디오의 오버레이(라이트박스·세로 스크롤·재인증 안내)가
  // 같은 규칙으로 포커스를 가둘 수 있게. 규칙이 두 벌이 되면 반드시 한쪽만 고쳐진다.
  global.VNRuntime = { mount: mount, renderScroll: renderScroll, trapTab: trapTab, schema: 1 };
})(typeof window !== "undefined" ? window : this);
