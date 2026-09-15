/* 통합 화면 — 대화로 소설을 쓰고, 그걸 장면으로 조립하고, 그림을 고른다.
 *
 * 기존 스튜디오(studio.js)를 대체하지 않는다. 같은 서버·같은 API·같은 데이터를 쓰는
 * 두 번째 화면이다. 마음에 들지 않으면 chat_ui.html 과 이 파일만 지우면 원래대로다.
 *
 * 설계에서 물러서지 않는 선 세 가지 — 전부 실측 때문에 생겼다:
 *
 *  1) 모델은 **누르지 않는다. 제안만 한다.**
 *     같은 지시문 7회에서 시킨 형식을 지킨 것이 3회다(docs/SCHEMA.md §1.2). 그 모델에게
 *     실행 권한을 주면 나머지 4회에 무엇이 실행될지 아무도 모른다. 그리고 실제로 위험한
 *     명령이 있다 — /api/compose 의 force 는 승인된 장면을 전부 백업으로 밀어낸다.
 *     그래서 모델의 답에서 [제안:...] 태그를 찾아 **버튼으로만** 만든다. 글자는 글자다.
 *
 *  2) 조립은 **3개씩 나눠서** 부르고, 저장은 **마지막에 한 번**만 한다.
 *     장면 1개에 약 30초다. 10개를 한 번에 시키면 254초가 걸려 소켓 상한에 걸린다.
 *     그래서 /api/chat 으로 3개씩 받아 배열을 모으고, 다 모이면 /api/compose-manual 로
 *     한 번에 넘긴다. 그 경로는 LLM 을 쓰지 않으므로 저장 단계에서는 시간이 문제되지 않고,
 *     개수가 어긋나면 서버가 디스크를 건드리기 전에 멈춘다(_create_scenes_from_items).
 *
 *  3) 후보 그림 중 **어느 것을 쓸지는 사람이 고른다.**
 *     register_images 는 IMAGE 에서 멈추고 select_image 만 REVIEW_HUMAN 을 쓴다
 *     (docs/SCHEMA.md §2.1). 검사기 A3 는 REVIEW_HUMAN 이상인데 selected_image 가 없으면
 *     떨어진다. 화면이 첫 장을 자동으로 고르면 검사는 통과인데 아무도 안 고른 그림이
 *     작품에 들어간다. 그래서 여기서는 자동 선택을 하지 않는다.
 *
 * DOM 은 전부 el() 로 만든다. 문자열을 그대로 마크업으로 집어넣는 DOM API 는 쓰지 않는다
 * — selftest 의 BANNED_DOM 목록이 그것들을 막는다(이름을 여기 적으면 그 검사가 이 주석을
 * 세므로 적지 않는다).
 */

/* ---------------------------------------------------------------- 뼈대 */
function $(id) { return document.getElementById(id); }

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

async function api(path, body, signal) {
  let r;
  try {
    const init = body
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {};
    if (signal) init.signal = signal;
    r = await fetch(path, init);
  } catch (e) {
    if (e && e.name === "AbortError") throw e;   // 중단은 오류가 아니다 — 그대로 올린다
    throw new Error("서버에 연결할 수 없습니다 — 스튜디오 서버가 켜져 있는지 확인하세요.");
  }
  let d = null;
  try { d = await r.json(); } catch (e) { d = null; }
  if (r.status === 401 && d && d.auth_required) {
    throw new Error("PIN 인증이 필요합니다 — 스튜디오 탭에서 인증한 뒤 돌아오세요.");
  }
  if (!r.ok) throw new Error((d && d.error) || ("오류 " + r.status));
  return d;
}

/* ---------------------------------------------------------------- 상태 */
const S = {
  state: null,       // /api/state 의 마지막 응답
  msgs: [],          // 대화 (역할/내용) — 서버의 스토리 챗로그와 같은 것
  view: "talk",      // list | talk | scenes | gallery | view
  gfilter: "all",    // 갤러리 필터
  chatId: "",        // 지금 보고 있는 대화 갈래 ("" = 기본 = 스튜디오와 같은 기록)
  chats: [],         // 갈래 목록
  useContext: true,  // 이 갈래가 작품(인물·장소·스토리라인)을 아는 채로 답하는가
  abort: null,       // 답을 기다리는 중이면 AbortController
  collected: [],     // 조립 중 받아 모은 장면 — 실패해도 살아남아야 한다
  busy: false,
};

/* 기다리는 동안 보내기 버튼을 중지로 바꾼다. 눈앉을 띄지 않고 누를 수 있는 자리가 거기뿐이다. */
function showStop(on) {
  const b = $("send");
  if (!b) return;
  b.textContent = on ? "중지" : "보내기";
  b.disabled = false;
  b.dataset.mode = on ? "stop" : "send";
}

function setBusy(on) {
  S.busy = on;
  const send = $("send");
  /* 중지 모드에서는 잠그지 않는다 — 잠그면 기다리는 사람이 멈출 방법이 없다. */
  if (send && send.dataset.mode !== "stop") send.disabled = on;
  const run = $("runCompose");
  if (run) run.disabled = on;
}

/* ---------------------------------------------------------------- 대화 그리기 */
function stream() { return $("stream"); }

function scrollEnd() {
  const m = stream();
  if (m) m.scrollTop = m.scrollHeight;
}

/* 모델은 **굵게** 를 습관적으로 쓴다. 그대로 두면 별표가 글자로 새어 읽기 나쁘다.
 * 마크다운을 전부 해석하지는 않는다 — 굵게 하나만, 그것도 노드로 만든다.
 * (문자열을 마크업으로 집어넣는 경로는 이 파일에서 한 번도 쓰지 않는다.) */
function fillText(node, text) {
  const parts = String(text == null ? "" : text).split("**");
  parts.forEach((part, i) => {
    if (part === "") return;
    if (i % 2 === 1) node.appendChild(el("strong", null, part));
    else node.appendChild(document.createTextNode(part));
  });
  if (!node.firstChild) node.appendChild(document.createTextNode(""));
}

function addTurn(role, text, idx) {
  const wrap = el("div", role === "user" ? "turn me" : "turn");
  wrap.appendChild(el("div", "who", role === "user" ? "나" : "이야기"));
  const bubble = el("div", "bubble");
  fillText(bubble, role === "user" ? text : stripOffers(text));
  wrap.appendChild(bubble);
  if (typeof idx === "number") wrap.appendChild(turnActions(role, text, idx, wrap));
  stream().appendChild(wrap);
  scrollEnd();
  return wrap;
}

/* 말풍선 하나에 붙는 동작들.
 * idx 는 S.msgs 안의 위치다 — 수정과 다시 생성은 "여기까지 남기고 다시" 이므로
 * 위치가 정확해야 한다. 기록을 다시 그릴 때마다 번호를 다시 매긴다. */
function turnActions(role, text, idx, wrap) {
  const bar = el("div", "acts");

  const copy = el("button", null, "복사");
  copy.type = "button";
  copy.addEventListener("click", () => copyText(text, copy));
  bar.appendChild(copy);

  if (role === "user") {
    const edit = el("button", null, "수정");
    edit.type = "button";
    edit.addEventListener("click", () => beginEdit(idx, text, wrap));
    bar.appendChild(edit);
  } else {
    const again = el("button", null, "다시 생성");
    again.type = "button";
    again.addEventListener("click", () => regenerate(idx));
    bar.appendChild(again);
  }
  return bar;
}

/* 클립보드는 보안 문맥에서만 쓸 수 있다. 이 페이지는 LAN IP 위의 평문 http 라
 * navigator.clipboard 가 없는 브라우저가 있다 — 그럴 땐 숨긴 칸에 넣고 execCommand 로 복사한다. */
async function copyText(text, btn) {
  const before = btn.textContent;
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(String(text || ""));
      ok = true;
    }
  } catch (e) { ok = false; }
  if (!ok) {
    try {
      const ta = document.createElement("textarea");
      ta.value = String(text || "");
      ta.setAttribute("readonly", "readonly");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      ok = document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (e) { ok = false; }
  }
  btn.textContent = ok ? "복사됨" : "복사 안됨";
  btn.classList.toggle("done", ok);
  setTimeout(() => { btn.textContent = before; btn.classList.remove("done"); }, 1400);
}

/* 내가 쓴 말 고치기 — 고치면 그 지점 이후는 다시 만든다(클로드 채팅과 같은 규칙).
 * 잘린 구간은 서버의 아카이브 파일로 옮겨지므로 사라지지 않는다. */
function beginEdit(idx, text, wrap) {
  if (S.busy) return;
  const box = el("div", "editbox");
  const ta = el("textarea");
  ta.value = String(text || "");
  box.appendChild(ta);
  const row = el("div", "row");
  const save = el("button", "go", "수정하고 다시 묻기");
  save.type = "button";
  const cancel = el("button", null, "취소");
  cancel.type = "button";
  row.appendChild(save);
  row.appendChild(cancel);
  box.appendChild(row);
  box.appendChild(el("p", "line",
    "이 지점 이후의 대화는 다시 만들어집니다. 지워지는 것이 아니라 보관됩니다."));

  wrap.replaceWith(box);
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);

  cancel.addEventListener("click", () => renderTalk());
  save.addEventListener("click", () => {
    const v = (ta.value || "").trim();
    if (!v) return;
    resendFrom(idx, v);
  });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); renderTalk(); }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save.click(); }
  });
}

/* idx 번째 발화를 newText 로 바꾸고 그 뒤를 다시 만든다. */
async function resendFrom(idx, newText) {
  await trimAndAsk(idx, newText);
}

/* idx 번째 답변을 다시 만든다 — 그 답변만 걸어내고 같은 질문을 다시 보낸다. */
async function regenerate(idx) {
  await trimAndAsk(idx, null);
}

/* 공통 경로: 서버 기록을 keep 개로 자르고, (있으면) 새 발화를 붙여 다시 묻는다. */
async function trimAndAsk(idx, newUserText) {
  if (S.busy) return;
  const keep = idx;
  const base = S.msgs.slice(0, keep);
  if (newUserText != null) base.push({ role: "user", content: newUserText });

  setBusy(true);
  try {
    await api("/api/chat-trim", { chat_id: S.chatId, keep: keep });
  } catch (e) {
    setBusy(false);
    addNote(String(e.message || e), true);
    return;
  }
  S.msgs = base;
  renderTalk();
  setBusy(true);
  await askServer();
}

/* 마지막 발화까지를 서버에 보내 답을 받는다 — send/수정/다시생성이 모두 이걸 통한다. */
async function askServer() {
  const wait = addNote("생각하는 중… (이 모델은 초당 12~14자 정도라 긴 답은 1~2분 걸립니다)");
  showStop(true);
  S.abort = new AbortController();
  try {
    const d = await api("/api/chat",
                        { messages: S.msgs, chat_id: S.chatId }, S.abort.signal);
    const reply = (d && d.reply) || "";
    wait.remove();
    S.msgs.push({ role: "assistant", content: reply });
    const turn = addTurn("assistant", reply, S.msgs.length - 1);
    renderOffers(reply, turn);
    loadChats();
  } catch (e) {
    wait.remove();
    if (e && e.name === "AbortError") {
      addNote("기다리기를 멈췤습니다. 서버는 답을 마저 만들고 있을 수 있고, 완성되면 기록에 남습니다. "
              + "새로고침하면 보입니다.");
    } else {
      addNote(String(e.message || e), true);
    }
  } finally {
    S.abort = null;
    showStop(false);
    setBusy(false);
  }
}

function addNote(text, bad) {
  const wrap = el("div", "turn");
  wrap.appendChild(el("div", "bubble sys" + (bad ? " err" : ""), text));
  stream().appendChild(wrap);
  scrollEnd();
  return wrap;
}

/* 모델이 제안한 행동을 버튼으로 — 누르는 것은 사람이다.
 * 태그 형식: [제안:조립 6]  ·  [제안:그림 SCENE-003]
 * 형식을 지키지 않은 답에는 버튼이 생기지 않는다. 그게 맞다 — 아무 일도 안 일어난다. */
const OFFER_RE = /\[제안:(조립|그림)\s*([A-Za-z0-9-]*)\]/g;

/* 태그는 기계용 표시다. 버튼으로 바꿔 놓고 말풍선에서는 지운다 —
 * 안 지우면 사용자가 "[제안:조립 2]" 라는 글자를 읽게 된다. */
function stripOffers(text) {
  return String(text == null ? "" : text).replace(OFFER_RE, "").replace(/\n{3,}/g, "\n\n").trim();
}

function renderOffers(text, after) {
  const offers = [];
  let m;
  OFFER_RE.lastIndex = 0;
  while ((m = OFFER_RE.exec(text)) !== null) offers.push({ kind: m[1], arg: m[2] });
  if (!offers.length) return;

  const row = el("div", "offer");
  const seen = {};
  offers.forEach((o) => {
    const key = o.kind + ":" + o.arg;
    if (seen[key]) return;
    seen[key] = 1;
    if (o.kind === "조립") {
      const n = Math.max(1, Math.min(parseInt(o.arg, 10) || 6, 24));
      const b = el("button", null, "장면 " + n + "개로 조립 (약 " + Math.ceil(n * 0.55) + "분)");
      b.type = "button";
      b.addEventListener("click", () => { $("total").value = String(n); openDrawer(); });
      row.appendChild(b);
    } else if (o.kind === "그림" && /^SCENE-\d+$/.test(o.arg)) {
      const b = el("button", null, o.arg + " 그림 뽑기");
      b.type = "button";
      b.addEventListener("click", () => { genFor(o.arg, b); });
      row.appendChild(b);
    }
  });
  if (row.childNodes.length) {
    stream().insertBefore(row, after ? after.nextSibling : null);
    scrollEnd();
  }
}

/* ---------------------------------------------------------------- 대화 보내기 */
async function send() {
  if (S.busy) return;
  const box = $("box");
  const text = (box.value || "").trim();
  if (!text) return;
  box.value = "";
  box.style.height = "auto";

  S.msgs.push({ role: "user", content: text });
  addTurn("user", text, S.msgs.length - 1);
  setBusy(true);
  await askServer();
}

/* ---------------------------------------------------------------- 조립 */
function openDrawer() { $("drawer").classList.add("open"); }
function closeDrawer() { $("drawer").classList.remove("open"); }

function setBar(done, total) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  $("bar").style.width = pct + "%";
}

/* 구간 요청문은 서버(vn_compose.compose_batch)가 만든다 — 모델에 보내는 문구가 두 벌이
 * 되면 조용히 갈린 쪽이 화면에 나온다. 여기서는 어느 구간인지와 앞 장면 요약만 넘긴다.
 * 요약은 order 와 purpose 만 보낸다(지시문이 무한정 커지지 않게). */
function madeSummary(items) {
  return items.map((s, i) => ({
    order: s && s.order != null ? s.order : i + 1,
    purpose: String((s && s.purpose) || "").slice(0, 80),
  }));
}

/* 이 객체가 장면 원소인가 — 서버의 _looks_like_scene 과 같은 판정(열쇠 두 개면 장면).
 * 이게 없으면 아래의 '포장 안에 배열이 하나뿐이면 그것' 규칙이 장면 객체의 dialogue 배열을
 * 장면 목록으로 착각한다. 실제로 그렇게 짰다가 3번 모양에서 빈 배열을 돌려줬다. */
const SCENE_KEYS = ["order", "purpose", "action_beat", "emotion", "time",
                    "location_id", "camera", "dialogue", "image_prompt"];

function looksLikeScene(v) {
  if (!v || typeof v !== "object" || Array.isArray(v)) return false;
  let n = 0;
  for (const k of SCENE_KEYS) if (k in v) n++;
  return n >= 2;
}

/* 응답에서 장면 배열을 꺼낸다 — 서버의 _extract_json_array 와 같은 세 모양을 받는다.
 * (배열 · {"scenes":[...]} 포장 · 배열 없이 객체만 줄줄이) */
function pullScenes(text) {
  const body = String(text || "").replace(/```(?:json)?/g, "").trim();
  const found = [];
  for (let i = 0; i < body.length; i++) {
    const c = body[i];
    if (c !== "[" && c !== "{") continue;
    for (let j = body.length; j > i; j--) {
      const slice = body.slice(i, j);
      if (slice.length < 2) break;
      let v;
      try { v = JSON.parse(slice); } catch (e) { continue; }
      found.push(v);
      i = j - 1;
      break;
    }
  }
  for (const v of found) if (Array.isArray(v)) return v;        // ① 진짜 배열
  for (const v of found) {                                      // ② 한 겹 포장된 배열
    if (!v || typeof v !== "object" || Array.isArray(v)) continue;
    if (looksLikeScene(v)) continue;            // 장면 자체는 포장이 아니다 — 건너뛴다
    for (const k of ["scenes", "items", "data", "result", "list", "장면"]) {
      if (Array.isArray(v[k])) return v[k];
    }
    const lists = Object.keys(v).map((k) => v[k]).filter(Array.isArray);
    if (lists.length === 1) return lists[0];    // 이름이 무엇이든 배열이 하나뿐이면 그것
  }
  const objs = found.filter(looksLikeScene);                    // ③ 배열 없이 객체만 줄줄이
  return objs.length ? objs : null;
}

async function runCompose() {
  if (S.busy) return;
  const total = Math.max(1, Math.min(parseInt($("total").value, 10) || 6, 24));
  const batch = Math.max(1, Math.min(parseInt($("batch").value, 10) || 3, 6));

  const already = (S.state && S.state.scenes) || [];
  if (already.length) {
    addNote("\uc774\ubbf8 \uc7a5\uba74 " + already.length + "\uac1c\uac00 \uc788\uc2b5\ub2c8\ub2e4. \ub36e\uc5b4\uc4f0\ub824\uba74 \uc2a4\ud29c\ub514\uc624 \ud0ed\uc5d0\uc11c "
            + "\ub2e4\uc2dc \uad6c\uc131\ud558\uc138\uc694 \u2014 \uc5ec\uae30\uc11c\ub294 \uae30\uc874 \uc791\ud488\uc744 \uc9c0\uc6b0\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.", true);
    closeDrawer();
    return;
  }

  closeDrawer();
  S.collected = [];
  await composeRange(1, total, batch, total);
}

/* \uad6c\uac04\uc744 \ubc1b\uc544 \ubaa8\uc740\ub2e4. \uc2e4\ud328\ud574\ub3c4 \uc774\ubbf8 \ubc1b\uc740 \uac83\uc740 \uc808\ub300 \ubc84\ub9ac\uc9c0 \uc54a\ub294\ub2e4.
 *
 * \uc608\uc804\uc5d0\ub294 \uc5ec\uae30\uc11c throw \ub97c \ub358\uc84c\uace0, \uadf8 throw \uac00 for \ub97c \ube60\uc838\ub098\uac00\uba74\uc11c collected \uac00 \ud1b5\uc9f8\ub85c
 * \uc0ac\ub77c\uc84c\ub2e4. \ud615\uc2dd \uc900\uc218\uc728\uc774 7\ubc88 \uc911 3\ubc88\uc774\ub2c8, 4\ubc30\uce58\uc9dc\ub9ac \uc55c\ubc94\uc740 \ub300\ubd80\ubd84 \ub9c8\uc9c0\ub9c9 \ubc30\uce58\uc5d0\uc11c
 * 5~6\ubd84\uc5b4\uce58\ub97c \uc783\uc5c8\ub2e4. \uc774\uc81c \uc783\ub294 \uac83\uc740 \uadf8 \ubc30\uce58 \ud558\ub098\ubfd0\uc774\ub2e4. */
async function composeRange(from, to, batch, total) {
  setBusy(true);
  setBar(S.collected.length, total);
  addNote("\uc7a5\uba74 " + from + "~" + to + " \ub97c \ubc1b\uc2b5\ub2c8\ub2e4. \ud55c \uc7a5\uba74\uc5d0 \uc57d 30\ucd08 \u2014 "
          + "\uc57d " + fmtSecs((to - from + 1) * 32) + " \uac78\ub9bd\ub2c8\ub2e4.");

  for (let s = from; s <= to; s += batch) {
    const e = Math.min(s + batch - 1, to);
    const note = addNote("\uc7a5\uba74 " + s + "~" + e + " \ud604\uc0c1 \uc911\u2026");
    let reply = "";
    try {
      const d = await api("/api/compose-batch", {
        total: total, branching: false, start: s, end: e,
        made: madeSummary(S.collected),
      });
      reply = (d && d.reply) || "";
    } catch (err) {
      note.remove();
      failedBatch(s, e, batch, total, "", String(err.message || err));
      return;
    }
    const items = pullScenes(reply);
    note.remove();

    if (!items || !items.length) {
      failedBatch(s, e, batch, total, reply, "");
      return;
    }
    items.forEach((it) => { if (it && typeof it === "object") S.collected.push(it); });
    addNote("\uc7a5\uba74 " + s + "~" + e + " \ub098\uc654\uc2b5\ub2c8\ub2e4 \u2014 \uc9c0\uae08\uae4c\uc9c0 " + S.collected.length + "\uac1c");
    setBar(S.collected.length, total);
  }
  setBusy(false);
  await saveCollected(total);
}

function fmtSecs(n) {
  const s = Math.round(n);
  if (s < 90) return s + "\ucd08";
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? (m + "\ubd84 " + r + "\ucd08") : (m + "\ubd84");
}

/* \ubc30\uce58 \ud558\ub098\uac00 \uc2e4\ud328\ud588\uc744 \ub54c \u2014 \ube48\uc190\uc73c\ub85c \ub3cc\ub824\ubcf4\ub0b4\uc9c0 \uc54a\ub294\ub2e4.
 * \uc5c6\ub294 \uac83\uc744 \ub9d0\ud558\uace0, \uc788\ub294 \uac83\uc744 \ubcf4\uc5ec \uc8fc\uace0, \ud560 \uc218 \uc788\ub294 \uac83\uc744 \ubc84\ud2bc\uc73c\ub85c \ub460\ub2e4. */
function failedBatch(s, e, batch, total, reply, errText) {
  setBusy(false);
  const got = S.collected.length;

  const head = errText
    ? errText
    : ("\uc7a5\uba74 " + s + "~" + e + " \ub294 \ud615\uc2dd\uc744 \ubabb \ub9de\ucdc4\uc2b5\ub2c8\ub2e4. \uc81c \ucabd \ubaa8\ub378 \ubb38\uc81c\uc774\uace0, "
       + "\uac19\uc740 \uc9c0\uc2dc\ubb38\uc73c\ub85c 7\ubc88 \uc911 4\ubc88\uc740 \uc774\ub807\uac8c \ub429\ub2c8\ub2e4.");
  addNote(head, true);
  addNote(got
    ? ("\uc55e\uc11c \ubc1b\uc740 " + got + "\uac1c\ub294 \uadf8\ub300\ub85c \uc788\uc2b5\ub2c8\ub2e4 \u2014 \ubc84\ub9ac\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.")
    : "\uc544\uc9c1 \ubc1b\uc740 \uc7a5\uba74\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.");

  const row = el("div", "offer");

  const again = el("button", null, "\uc774 \uad6c\uac04\ub9cc \ub2e4\uc2dc \u00b7 \uc57d " + fmtSecs((e - s + 1) * 32));
  again.type = "button";
  again.addEventListener("click", () => { row.remove(); composeRange(s, total, batch, total); });
  row.appendChild(again);

  if (got) {
    const save = el("button", null, "\ubc1b\uc740 " + got + "\uac1c\ub85c \ub9c8\ubb34\ub9ac");
    save.type = "button";
    save.addEventListener("click", () => { row.remove(); saveCollected(got); });
    row.appendChild(save);
  }

  if (reply && reply.trim()) {
    const show = el("button", null, "\ubc1b\uc740 \uae00\uc790 \ubcf4\uae30");
    show.type = "button";
    show.addEventListener("click", () => {
      show.disabled = true;
      const wrap = el("div", "turn");
      const bub = el("div", "bubble sys");
      bub.textContent = reply;
      wrap.appendChild(bub);
      const hint = el("p", "line",
        "\uc774 \uae00\uc790\ub294 \ubc84\ub9ac\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4. \uc2a4\ud29c\ub514\uc624 \ud0ed\uc758 [\u270d \uc9c1\uc811 \uc785\ub825]\uc5d0 \uadf8\ub300\ub85c \ubd99\uc5ec\ub123\uc73c\uba74 "
        + "\ubaa8\ub378\uc744 \ub2e4\uc2dc \ubd80\ub974\uc9c0 \uc54a\uace0\ub3c4 \uc7a5\uba74\uc774 \ub429\ub2c8\ub2e4.");
      wrap.appendChild(hint);
      stream().appendChild(wrap);
      scrollEnd();
    });
    row.appendChild(show);
  }

  stream().appendChild(row);
  scrollEnd();
  setBar(0, 1);
}

/* \ubaa8\uc740 \uc7a5\uba74\uc744 \ud55c \ubc88\uc5d0 \uc800\uc7a5\ud55c\ub2e4. \uc800\uc7a5\uc740 LLM \uc744 \uc548 \uc4f0\ubbc0\ub85c \ube60\ub974\uace0,
 * \uac1c\uc218\uac00 \uc5b4\uae78\ub9ac\uba74 \uc11c\ubc84\uac00 \ub514\uc2a4\ud06c\ub97c \uac74\ub4dc\ub9ac\uae30 \uc804\uc5d0 \uba48\ucd98\ub2e4. */
async function saveCollected(expected) {
  const items = S.collected || [];
  if (!items.length) { addNote("\uc800\uc7a5\ud560 \uc7a5\uba74\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.", true); return; }

  /* order \ub97c \uc804\uccb4 \uae30\uc900\uc73c\ub85c \ub2e4\uc2dc \ub9e4\uae34\ub2e4 \u2014 \ubc30\uce58\ub9c8\ub2e4 1\ubd80\ud130 \ub2e4\uc2dc \uc138\ub294 \uc77c\uc774 \ud754\ud558\ub2e4. */
  items.forEach((it, i) => { it.order = i + 1; });

  setBusy(true);
  try {
    const res = await api("/api/compose-manual", {
      text: JSON.stringify(items), count: items.length, force: false,
    });
    const created = (res && res.created) || [];
    const made = created.length || items.length;
    const fixed = (res && res.fixed_anchors) || [];
    addNote("\uc7a5\uba74 " + made + "\uac1c\ub97c \uc800\uc7a5\ud588\uc2b5\ub2c8\ub2e4."
            + (fixed.length ? " \uc575\ucee4\ub97c " + fixed.length + "\uac1c \uc7a5\uba74\uc5d0\uc11c \uc790\ub3d9 \ubcf4\uc815\ud588\uc2b5\ub2c8\ub2e4." : "")
            + ((res && res.checker_pass === false)
               ? " \uc790\ub3d9 \uac80\uc0ac\uc5d0\uc11c \uc9c0\uc801\uc774 \uc788\uc2b5\ub2c8\ub2e4 \u2014 \uc2a4\ud29c\ub514\uc624 \ud0ed\uc758 \uac80\uc0ac\uc5d0\uc11c \ud655\uc778\ud558\uc138\uc694." : ""));
    S.collected = [];
    await refresh();

    const go = el("div", "offer");
    const btn = el("button", null, "\uc7a5\uba74 " + made + "\uac1c \ubcf4\ub7ec \uac00\uae30");
    btn.type = "button";
    btn.addEventListener("click", () => showView("scenes"));
    go.appendChild(btn);
    stream().appendChild(go);
    scrollEnd();
  } catch (e) {
    addNote(String(e.message || e), true);
    addNote("\ubc1b\uc740 " + items.length + "\uac1c\ub294 \uadf8\ub300\ub85c \ub4e4\uace0 \uc788\uc2b5\ub2c8\ub2e4 \u2014 \ub2e4\uc2dc \ub9c8\ubb34\ub9ac\ub97c \ub20c\ub7ec \ubcf4\uc138\uc694.", true);
    const row = el("div", "offer");
    const retry = el("button", null, "\ub2e4\uc2dc \ub9c8\ubb34\ub9ac");
    retry.type = "button";
    retry.addEventListener("click", () => { row.remove(); saveCollected(expected); });
    row.appendChild(retry);
    stream().appendChild(row);
    scrollEnd();
  } finally {
    setBar(0, 1);
    setBusy(false);
  }
}

/* ---------------------------------------------------------------- 장면 */
const STATE_LABEL = {
  SCENE_PLAN: "구성됨", PROMPT: "프롬프트 있음", IMAGE: "그림 뽑음",
  REVIEW_HUMAN: "고름", APPROVED: "승인됨",
};

function thumbUrl(rel) {
  const path = String(rel || "");
  const cut = path.indexOf("images/") === 0 ? path.slice("images/".length) : path;
  return "/img/" + cut + "?w=200";
}

function sceneCard(sc) {
  const card = el("div", "card");
  const head = el("h2");
  head.appendChild(el("span", "title",
    sc.scene_id + (sc.purpose ? " · " + String(sc.purpose).slice(0, 40) : "")));
  head.appendChild(el("span", "state " + (sc.status === "APPROVED" ? "done"
                                        : sc.status === "IMAGE" ? "wait" : ""),
                      STATE_LABEL[sc.status] || sc.status || ""));
  card.appendChild(head);

  const firstLine = (sc.dialogue && sc.dialogue.length && sc.dialogue[0].text) || "";
  if (firstLine) card.appendChild(el("p", "line", String(firstLine).slice(0, 120)));

  const raws = sc.raw_images || [];
  if (raws.length) {
    const strip = el("div", "shots");
    raws.forEach((rel) => {
      const b = el("button", "shot" + (rel === sc.selected_image ? " pick" : ""));
      b.type = "button";
      b.title = rel === sc.selected_image ? "고른 그림" : "이걸로 고르기";
      const img = el("img");
      img.src = thumbUrl(rel);
      img.alt = sc.scene_id + " 후보";
      img.loading = "lazy";
      b.appendChild(img);
      b.addEventListener("click", () => pick(sc.scene_id, rel, b));
      strip.appendChild(b);
    });
    card.appendChild(strip);
    if (!sc.selected_image) {
      card.appendChild(el("p", "line", "후보 " + raws.length + "장 중에서 하나를 누르세요. "
                                     + "고른 뒤에야 승인할 수 있습니다."));
    }
  }

  const row = el("div", "row");
  const gen = el("button", "go", raws.length ? "그림 더 뽑기" : "그림 뽑기");
  gen.type = "button";
  gen.addEventListener("click", () => genFor(sc.scene_id, gen));
  row.appendChild(gen);

  if (sc.selected_image && sc.status !== "APPROVED") {
    const ap = el("button", null, "승인");
    ap.type = "button";
    ap.addEventListener("click", () => approve(sc.scene_id, ap));
    row.appendChild(ap);
  }
  card.appendChild(row);
  return card;
}

async function pick(sid, rel, btn) {
  if (S.busy) return;
  setBusy(true);
  try {
    await api("/api/select", { scene_id: sid, image: rel });
    await refresh();
    /* 어느 화면에서 골랐든 그 화면이 갱신돼야 한다 — 갤러리에서 고르고 장면 탭만
     * 다시 그리면, 방금 고른 별표가 눈앞에서 안 바뀐다. */
    showView(S.view);
  } catch (e) {
    addNote(String(e.message || e), true);
  } finally { setBusy(false); }
}

async function approve(sid, btn) {
  if (S.busy) return;
  setBusy(true);
  btn.disabled = true;
  try {
    await api("/api/approve", { scene_id: sid });
    await refresh();
    showView(S.view);
  } catch (e) {
    addNote(String(e.message || e), true);
    btn.disabled = false;
  } finally { setBusy(false); }
}

/* 생성은 백그라운드로 돌고 진행은 따로 물어본다 — 폰 브라우저가 긴 POST 를 끊기 때문이다. */
async function genFor(sid, btn) {
  if (S.busy) return;
  setBusy(true);
  if (btn) btn.disabled = true;
  const note = addNote(sid + " 그림 요청 중…");
  try {
    await api("/api/gen-image", { scene_id: sid, n: 1 });
    for (;;) {
      await new Promise((r) => setTimeout(r, 2500));
      const st = await api("/api/gen-status", { scene_id: sid });
      if (st && st.message) note.textContent = sid + " · " + st.message;
      if (!st || !st.running) {
        if (st && st.error) throw new Error(st.error);
        break;
      }
    }
    note.textContent = sid + " 그림이 나왔습니다. 후보 중에서 고르세요.";
    await refresh();
    renderScenes();
    showView("scenes");
  } catch (e) {
    note.textContent = String(e.message || e);
    note.className = "bubble sys err";
  } finally {
    if (btn) btn.disabled = false;
    setBusy(false);
  }
}

function renderScenes() {
  if (S.view !== "scenes") return;
  const m = stream();
  while (m.firstChild) m.removeChild(m.firstChild);
  const scenes = (S.state && S.state.scenes) || [];
  if (!scenes.length) {
    addNote("아직 장면이 없습니다. [대화] 탭에서 이야기를 쓰고 조립하세요.");
    return;
  }
  scenes.forEach((sc) => m.appendChild(sceneCard(sc)));
  m.scrollTop = 0;
}

/* ---------------------------------------------------------------- 대화 목록
 * 대화 갈래마다 파일이 따로다(talk_store.story_chat_path_for). 그래서 문맥이 섞이지 않는다:
 * A 대화에서 쓰던 소설이 B 대화의 답에 끼어들지 않는다.
 * 기본 갈래(id 없음)는 스튜디오의 스토리 탭과 같은 파일이라 지울 수 없다. */
function newChatId() {
  /* 서버가 받는 형식: 영숫자로 시작, 40자 이내. 시각을 앞에 둬서 정렬이 자연스럽게. */
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return "c" + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate())
       + "-" + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
}

async function loadChats() {
  try {
    const d = await api("/api/chats", {});
    S.chats = (d && d.chats) || [];
  } catch (e) {
    S.chats = [];
  }
}

async function openChat(id) {
  S.chatId = id || "";
  const rec = (S.chats || []).filter((c) => c.id === S.chatId)[0];
  /* 서버가 준 값이 단일 출처다. 없으면(아직 파일이 없는 새 갈래) 기본값:
   * 기본 갈래는 작품을 알고, 새 갈래는 백지. */
  S.useContext = rec && typeof rec.use_context === "boolean"
    ? rec.use_context : !S.chatId;
  setBusy(true);
  try {
    const h = await api("/api/chat-history", { chat_id: S.chatId });
    S.msgs = (h && h.messages) || [];
  } catch (e) {
    S.msgs = [];
    addNote(String(e.message || e), true);
  } finally {
    setBusy(false);
  }
  showView("talk");
}

function chatLabel(c) {
  if (c.title) return c.title;
  return c.id ? "제목 없는 대화" : "기본 대화";
}

function renderList() {
  if (S.view !== "list") return;
  const m = stream();
  while (m.firstChild) m.removeChild(m.firstChild);

  const wrap = el("div", "chatlist");

  const nw = el("div", "chatrow");
  const nb = el("button", "open");
  nb.type = "button";
  nb.appendChild(el("span", "nm", "+ 새 대화"));
  nb.appendChild(el("span", "meta", "빈 문맥으로 시작합니다 — 앞의 대화가 끼어들지 않습니다"));
  nb.addEventListener("click", async () => {
    const id = newChatId();
    S.chats.unshift({ id: id, title: "", count: 0, mtime: 0 });
    await openChat(id);
  });
  nw.appendChild(nb);
  wrap.appendChild(nw);

  (S.chats || []).forEach((c) => {
    const row = el("div", "chatrow" + (c.id === S.chatId ? " on" : ""));
    const open = el("button", "open");
    open.type = "button";
    open.appendChild(el("span", "nm", chatLabel(c)));
    const when = c.mtime ? new Date(c.mtime * 1000).toLocaleString("ko-KR",
      { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "새 대화";
    open.appendChild(el("span", "meta", c.count + "턴 · " + when
                                        + (c.id === S.chatId ? " · 지금 보는 중" : "")));
    open.addEventListener("click", () => openChat(c.id));
    row.appendChild(open);

    const del = el("button", "del", "삭제");
    del.type = "button";
    if (!c.id) {
      del.disabled = true;
      del.title = "기본 대화는 스튜디오와 같은 기록이라 지울 수 없습니다";
    } else {
      del.addEventListener("click", async () => {
        del.disabled = true;
        try {
          await api("/api/chat-delete", { chat_id: c.id });
          if (S.chatId === c.id) { S.chatId = ""; S.msgs = []; }
          await loadChats();
          renderList();
        } catch (e) {
          del.disabled = false;
          addNote(String(e.message || e), true);
        }
      });
    }
    row.appendChild(del);
    wrap.appendChild(row);
  });

  m.appendChild(wrap);
  m.scrollTop = 0;
}

/* ---------------------------------------------------------------- 갤러리
 * 장면별로 흩어진 그림을 한 판에 모아 보고, 여기서 바로 고르고 승인한다.
 * 장면 탭은 "이 장면" 단위, 갤러리는 "작품 전체" 단위다 — 같은 데이터, 다른 눈높이.
 * 고르는 것은 여기서도 사람이다(자동 선택 없음). */
const GFILTERS = [
  { key: "all", label: "전체", fn: () => true },
  { key: "sel", label: "고른 것", fn: (it) => it.selected },
  { key: "unsel", label: "안 고른 것", fn: (it) => !it.selected },
  { key: "approved", label: "승인됨", fn: (it) => it.status === "APPROVED" },
  { key: "waiting", label: "고르기 대기", fn: (it) => it.status === "IMAGE" },
];

function galleryItems() {
  const out = [];
  ((S.state && S.state.scenes) || []).forEach((sc) => {
    (sc.raw_images || []).forEach((rel) => {
      out.push({
        scene: sc.scene_id, order: sc.scene_order, status: sc.status,
        rel: rel, selected: rel === sc.selected_image,
        purpose: sc.purpose || "",
      });
    });
  });
  return out;
}

function renderGallery() {
  if (S.view !== "gallery") return;
  const m = stream();
  while (m.firstChild) m.removeChild(m.firstChild);

  const items = galleryItems();
  if (!items.length) {
    addNote("아직 그림이 없습니다. [장면] 탭에서 그림을 뽑으세요.");
    return;
  }

  const bar = el("div", "gbar");
  const count = el("span", "count");
  GFILTERS.forEach((f) => {
    const b = el("button", S.gfilter === f.key ? "on" : null, f.label);
    b.type = "button";
    b.addEventListener("click", () => { S.gfilter = f.key; renderGallery(); });
    bar.appendChild(b);
  });
  bar.appendChild(count);
  m.appendChild(bar);

  const chosen = GFILTERS.filter((f) => f.key === S.gfilter)[0] || GFILTERS[0];
  const shown = items.filter(chosen.fn);
  const scenes = {};
  items.forEach((it) => { scenes[it.scene] = 1; });
  count.textContent = shown.length + " / " + items.length + "장 · 장면 "
                    + Object.keys(scenes).length + "개";

  const grid = el("div", "grid");
  shown.forEach((it) => {
    const cell = el("button", "cell" + (it.selected ? " pick" : ""));
    cell.type = "button";
    cell.title = it.scene + (it.selected ? " · 고른 그림" : " · 누르면 이걸로 고릅니다");
    const img = el("img");
    img.src = thumbUrl(it.rel);
    img.alt = it.scene;
    img.loading = "lazy";
    cell.appendChild(img);
    const tag = el("span", "tag" + (it.selected ? " sel" : ""),
                   it.selected ? "★ " + it.scene : it.scene);
    cell.appendChild(tag);
    cell.appendChild(el("span", "cap", STATE_LABEL[it.status] || it.status || ""));
    cell.addEventListener("click", () => pick(it.scene, it.rel));
    grid.appendChild(cell);
  });
  m.appendChild(grid);
  m.scrollTop = 0;
}

/* ---------------------------------------------------------------- 감상
 * 재생은 공용 엔진(vn_runtime.js)이 한다 — 스튜디오·감상본과 같은 파일이다.
 * 여기서 따로 만들면 세 화면이 서로 다른 재생을 하게 된다. */
function vnScene(sc) {
  const o = {
    id: sc.scene_id, order: sc.scene_order, purpose: sc.purpose || "",
    img: sc.image_url || "",
    lines: (sc.dialogue || []).map((d) => ({
      n: d.speaker_id ? charName(d.speaker_id) : "",
      c: null,
      t: d.text || "",
      p: d.placement === "top" ? "top" : "bottom",
    })),
  };
  if (sc.episode) o.ep = sc.episode;
  if (sc.choices && sc.choices.length) o.choices = sc.choices;
  if (sc.branch && sc.branch.length) o.branch = sc.branch;
  if (sc.ending) {
    o.ending = true;
    if (sc.ending_label) o.ending_label = sc.ending_label;
  }
  return o;
}

function charName(id) {
  const list = (S.state && S.state.characters) || [];
  for (const c of list) if (c.id === id) return c.name || id;
  return id;
}

function vnData() {
  const st = S.state || {};
  return {
    title: st.title || "",
    scenes: (st.scenes || []).map(vnScene),
    dating: st.dating || null,
    episodes: (st.episodes || []).map((e) => ({ ep: e.episode, title: e.title || "" })),
  };
}

let player = null;

function ensurePlayer() {
  if (!window.VNRuntime) return null;
  if (player) { player.setData(vnData()); return player; }
  player = window.VNRuntime.mount({
    data: vnData(),
    storageKey: "vn",          // 스튜디오와 같은 저장 키 — 읽던 위치가 그대로 이어진다
    imageSrc: (sc, kind) => {
      const u = (sc && sc.img) || "";
      if (!u) return "";
      return kind === "thumb" ? u + "?w=140" : u;
    },
    onGallery: () => showView("gallery"),
    onExit: () => showView("view"),
    backgroundNodes: () => Array.prototype.filter.call(
      document.querySelectorAll("body > *"),
      (n) => !n.classList || !n.classList.contains("vnr")),
  });
  return player;
}

function renderView() {
  if (S.view !== "view") return;
  const m = stream();
  while (m.firstChild) m.removeChild(m.firstChild);

  const scenes = (S.state && S.state.scenes) || [];
  const pane = el("div", "viewpane");
  const withImg = scenes.filter((s) => s.image_url).length;
  const approved = scenes.filter((s) => s.status === "APPROVED").length;

  pane.appendChild(el("p", "line",
    scenes.length ? ("장면 " + scenes.length + "개 · 그림 있는 컷 " + withImg
                     + "개 · 승인 " + approved + "개")
                  : "아직 장면이 없습니다."));

  if (!window.VNRuntime) {
    pane.appendChild(el("p", "line",
      "재생 엔진(vn_runtime.js)을 불러오지 못했습니다 — 새로고침 해 보세요."));
    m.appendChild(pane);
    return;
  }
  if (!scenes.length) {
    m.appendChild(pane);
    return;
  }

  const row = el("div", "row");
  const play = el("button", "go", "처음부터 보기");
  play.type = "button";
  play.addEventListener("click", () => startPlayback(false));
  row.appendChild(play);

  const p = ensurePlayer();
  if (p && p.hasSaved && p.hasSaved()) {
    const cont = el("button", null, "이어보기");
    cont.type = "button";
    cont.addEventListener("click", () => startPlayback(true));
    row.appendChild(cont);
  }
  pane.appendChild(row);

  if (withImg < scenes.length) {
    pane.appendChild(el("p", "line",
      "그림이 없는 컷 " + (scenes.length - withImg) + "개는 글자만 나옵니다."));
  }
  m.appendChild(pane);
  m.scrollTop = 0;
}

function startPlayback(resume) {
  const p = ensurePlayer();
  if (!p) { addNote("재생 엔진을 불러오지 못했습니다 — 새로고침 해 보세요.", true); return; }
  p.start(!!resume);
}

function ctxSwitch() {
  const row = el("div", "ctxbar");
  const label = el("span", "ctxname",
    S.chatId ? (chatLabel((S.chats || []).filter((c) => c.id === S.chatId)[0] || {})) : "기본 대화");
  row.appendChild(label);
  const b = el("button", S.useContext ? "on" : null,
               S.useContext ? "작품 설정 켜짐" : "작품 설정 꺼짐");
  b.type = "button";
  b.title = S.useContext
    ? "지금 작품의 인물·장소·스토리라인을 알고 답합니다. 끄면 백지에서 시작합니다."
    : "작품과 무관한 새 이야기로 답합니다. 켜면 지금 작품을 이어서 씁니다.";
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const d = await api("/api/chat-meta",
                          { chat_id: S.chatId, use_context: !S.useContext });
      S.useContext = !!(d && d.use_context);
      await loadChats();
      renderTalk();
    } catch (e) {
      b.disabled = false;
      addNote(String(e.message || e), true);
    }
  });
  row.appendChild(b);
  return row;
}

function renderTalk() {
  if (S.view !== "talk") return;
  const m = stream();
  while (m.firstChild) m.removeChild(m.firstChild);
  m.appendChild(ctxSwitch());
  if (!S.msgs.length) {
    addNote("이야기를 시작해 보세요. 예: \"고등학교 옥상에서 시작하는 짧은 연애물을 쓰고 싶어\"");
  } else {
    /* 기록을 다시 그릴 때도 제안은 버튼이어야 한다. 새로고침 한 번에 제안이 사라지면
     * 사용자는 모델이 방금 권한 것을 다시 물어봐야 한다 — 그 한 번이 1~2분이다.
     * 마지막 답의 제안만 살린다(지난 제안까지 다 띄우면 버튼이 줄줄이 쌓인다). */
    S.msgs.forEach((t, i) => {
      const role = t.role === "user" ? "user" : "assistant";
      const turn = addTurn(role, t.content, i);
      if (role === "assistant" && i === S.msgs.length - 1) renderOffers(t.content, turn);
    });
  }
  scrollEnd();
}

const VIEWS = { list: "tabList", talk: "tabTalk", scenes: "tabScenes",
                gallery: "tabGallery", view: "tabView" };

function showView(v) {
  if (!VIEWS[v]) v = "talk";
  S.view = v;
  Object.keys(VIEWS).forEach((k) => {
    const b = $(VIEWS[k]);
    if (b) b.classList.toggle("on", k === v);
  });
  const foot = document.querySelector("footer");
  if (foot) foot.style.display = v === "talk" ? "" : "none";
  const jump = $("jump");
  if (jump) jump.hidden = true;
  if (v === "list") renderList();
  else if (v === "talk") renderTalk();
  else if (v === "scenes") renderScenes();
  else if (v === "gallery") renderGallery();
  else renderView();
}

/* ---------------------------------------------------------------- 상태 칩 */
async function probe() {
  const llm = $("chipLlm");
  const img = $("chipImg");
  try {
    const d = await api("/api/talk-status", {});
    const up = !!(d && d.up);
    llm.textContent = up ? "글자 연결됨" : "글자 끊김";
    llm.className = "chip " + (up ? "ok" : "bad");
  } catch (e) { llm.textContent = "글자 확인 실패"; llm.className = "chip bad"; }
  try {
    const d = await api("/api/image-engine", {});
    const ok = !!(d && d.ok);
    img.textContent = ok ? ("그림 " + ((d && d.provider) || "연결됨")) : "그림 끊김";
    img.className = "chip " + (ok ? "ok" : "bad");
  } catch (e) { img.textContent = "그림 확인 실패"; img.className = "chip bad"; }
}

async function refresh() {
  S.state = await api("/api/state");
  /* 이건 한 작품 전용 도구가 아니라 비주얼 노벨 생성기다. 그래서 머리에는 앱 이름만 둔다.
   * 지금 열려 있는 작품 이름은 그것이 실제로 쓰이는 자리(장면·갤러리·감상)에서만 말한다. */
  if (player) player.setData(vnData());
}

/* ---------------------------------------------------------------- 시작 */
async function boot() {
  $("send").addEventListener("click", () => {
    const b = $("send");
    if (b && b.dataset.mode === "stop") {
      if (S.abort) S.abort.abort();
      return;
    }
    send();
  });

  /* 맨 아래로 — 위로 올라가 읽는 중에만 나타난다(늘 떠 있으면 손가락을 가린다). */
  const jump = $("jump");
  const sm = stream();
  if (jump && sm) {
    jump.addEventListener("click", () => { sm.scrollTop = sm.scrollHeight; });
    sm.addEventListener("scroll", () => {
      const far = sm.scrollHeight - sm.scrollTop - sm.clientHeight > 260;
      jump.hidden = !(far && S.view === "talk");
    });
  }
  Object.keys(VIEWS).forEach((k) => {
    const b = $(VIEWS[k]);
    if (b) b.addEventListener("click", () => showView(k));
  });
  $("runCompose").addEventListener("click", runCompose);
  $("closeDrawer").addEventListener("click", closeDrawer);

  const box = $("box");
  box.addEventListener("input", () => {
    box.style.height = "auto";
    box.style.height = Math.min(box.scrollHeight, 180) + "px";
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); }
  });

  /* 조립 버튼은 늘 닿는 곳에 있어야 한다 — 모델이 제안해 주기를 기다리게 두면
   * 형식을 안 지킨 날에는 사용자가 아무것도 할 수 없다. */
  const hint = $("hint");
  const open = el("button", null, "장면으로 조립");
  open.type = "button";
  open.addEventListener("click", openDrawer);
  hint.textContent = "";
  hint.appendChild(open);

  try {
    await refresh();
  } catch (e) {
    addNote(String(e.message || e), true);
  }
  try {
    const h = await api("/api/chat-history", { chat_id: S.chatId });
    S.msgs = (h && h.messages) || [];
  } catch (e) { S.msgs = []; }
  await loadChats();

  showView("talk");
  probe();
  setInterval(probe, 30000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
