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
  job: null,         // 서버가 들고 도는 조립 작업의 마지막 상태
  shown: 0,          // 화면에 이미 줄을 올린 장면 수
  picking: false,    // 고르기·승인 중 (굽는 중에도 골라야 하므로 busy 와 따로 둔다)
  llmDown: false,    // 모델이 꺼져 있는가 — 그러면 붙여넣기 경로를 화면에 연다
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
  /* 마지막 답이 아니면 그 뒤의 대화가 전부 다시 만들어진다 — 수정 경로는 그 사실을
   * 말하는데 여기만 말없이 잘랐다. 몇 개가 걸리는지 숫자로 알린다. */
  const after = S.msgs.length - idx - 1;
  if (after > 0) {
    const ok = window.confirm("이 답을 다시 만들면 뒤의 대화 " + after
                              + "개도 다시 만들어집니다. 지워지는 것이 아니라 보관됩니다. 계속할까요?");
    if (!ok) return;
  }
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
    const d = await api("/api/chat-trim",
                        { chat_id: S.chatId, keep: keep, expect_len: S.msgs.length });
    /* 자르기가 조용히 실패하면(아카이브 저장 불가 등) 화면만 깔끔해지고 저장본은 그대로다
     * — 다음에 열면 고친 줄과 옛 줄이 나란히 있다. 200 안에 실린 오류도 오류로 다룬다. */
    if (d && d.error) throw new Error(d.error);
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
  /* 답을 기다리는 1~2분 사이에 사람이 다른 대화로 넘어갈 수 있다. 서버는 요청에 실린
   * chat_id 로 올바른 파일에 저장하지만, 화면이 그걸 지금 열린 대화에 붙이면 남의 대화에
   * 남의 답이 섞이고 다음 한 마디에 그대로 저장된다. 떠날 때를 기억해 두고 확인한다. */
  const askedIn = S.chatId;
  const askedList = S.msgs;
  const wait = addNote("생각하는 중… (이 모델은 초당 12~14자 정도라 긴 답은 1~2분 걸립니다)");
  showStop(true);
  S.abort = new AbortController();
  try {
    const d = await api("/api/chat",
                        { messages: S.msgs, chat_id: S.chatId }, S.abort.signal);
    const reply = (d && d.reply) || "";
    wait.remove();
    if (S.chatId !== askedIn || S.msgs !== askedList) {
      // 다른 대화로 옮겨 갔다. 서버에는 제대로 저장됐으니 여기서는 알리기만 한다.
      addNote("다른 대화에서 답이 도착했습니다. 목록에서 그 대화를 열면 보입니다.");
      loadChats();
      return;
    }
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
  /* 지난 제안은 걷어낸다 — 안 그러면 대화를 이어갈수록 옛 버튼이 줄줄이 남는다.
   * 사람이 스크롤하다 예전 제안을 누르면 지금 이야기와 무관한 개수로 조립이 시작된다. */
  Array.prototype.forEach.call(document.querySelectorAll(".offer"), (n) => n.remove());
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
    addNote("이미 장면 " + already.length + "개가 있습니다. 덮어쓰려면 스튜디오 화면에서 "
            + "다시 구성하세요 — 여기서는 기존 작품을 지우지 않습니다.", true);
    closeDrawer();
    return;
  }
  closeDrawer();

  try {
    await api("/api/compose-job", { total: total, batch: batch, branching: false });
  } catch (e) {
    addNote(String(e.message || e), true);
    /* 거절당했다고 화면이 조용해지면 안 된다. 거절의 가장 흔한 이유가 "이미 돌고 있다" 이고,
     * 그때 이 기기가 할 일은 새로 시작하는 것이 아니라 **그 진행을 같이 보는 것**이다.
     * 폰과 PC 를 번갈아 쓰면 반드시 일어난다 — 예전에는 둘 중 나중에 누른 쪽이 빨간 줄
     * 하나만 보고 영원히 멈춰 있었다. 오류 문구를 읽는 대신 상태를 다시 묻는다. */
    try {
      const st = await api("/api/compose-job-status", {});
      if (st && (st.running || (st.scenes || []).length)) {
        S.shown = 0;                 // 이 기기는 이 작업을 처음 본다 — 받아 둔 것부터 줄이게
        addNote(st.running
          ? "다른 곳에서 시작한 현상이 돌고 있습니다 — 여기서도 같이 보여 드립니다."
          : "받아 둔 장면이 있습니다 — 아래에서 마무리하거나 버릴 수 있습니다.");
        startPolling();
      }
    } catch (e2) { /* 상태도 못 읽으면 위의 오류 문구가 마지막 말이다 */ }
    return;
  }
  addNote("현상을 시작했습니다 — " + total + "장면, 약 " + fmtSecs(total * 32) + ". "
          + "화면을 닫거나 폰을 잠그셔도 계속 돕니다.");
  liveShow("현상을 시작했습니다…", [], 0);
  startPolling();
}

/* 지금 돌고 있는 일을 탭 밖의 고정 자리에 그린다.
 * #stream 은 탭을 옮길 때마다 비워진다 — 진행과 복구 버튼이 거기 있으면 장면 탭을
 * 한 번 눌렀다 오는 것만으로 받아 둔 장면을 되살릴 방법이 사라진다. */
function liveShow(msg, actions, frac) {
  const box = $("live");
  if (!box) return;
  box.hidden = false;
  $("liveMsg").textContent = msg || "";
  const bar = $("liveBar");
  if (bar) bar.style.width = (frac == null ? 0 : Math.max(0, Math.min(1, frac)) * 100) + "%";
  const acts = $("liveActs");
  while (acts.firstChild) acts.removeChild(acts.firstChild);
  (actions || []).forEach((a) => {
    const b = el("button", a.go ? "go" : null, a.label);
    b.type = "button";
    if (a.id) b.id = a.id;
    b.addEventListener("click", () => a.onClick(b));
    acts.appendChild(b);
  });
}

function liveHide() {
  const box = $("live");
  if (box) box.hidden = true;
}

function fmtSecs(n) {
  const s = Math.round(n);
  if (s < 90) return s + "초";
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? (m + "분 " + r + "초") : (m + "분");
}

/* 진행은 서버에 물어본다. 이 폴링은 화면을 다시 열었을 때도 시작되므로,
 * 자리를 떴다 돌아와도 그 사이에 진행된 것이 보인다. 조립을 서버로 내린 유일한 이유다. */
let pollTimer = null;

function startPolling() {
  if (pollTimer) return;
  S.shown = 0;
  setBusy(true);
  pollCompose();
  pollTimer = setInterval(pollCompose, 2500);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  setBusy(false);
}

async function pollCompose() {
  let st;
  try {
    st = await api("/api/compose-job-status", {});
  } catch (e) {
    return;                     // 일시적 실패로 폴링을 죽이지 않는다
  }
  S.job = st;

  /* 도착한 장면만큼 줄을 쌓는다 — 배치가 다 모일 때까지 기다리지 않는다.
   * 첫 보상이 118초에서 30초로 당겨지는 지점이 정확히 여기다. */
  const scenes = st.scenes || [];

  /* 서버의 목록이 **줄어들 수도** 있다 — 버리기를 눌렀거나, 다른 기기에서 저장하고
   * 새 작업이 시작됐거나, 서버가 다시 켜졌을 때. S.shown 은 올라가기만 하므로 그런 날
   * 이후의 장면은 영원히 안 보였다(목록은 늘고 있는데 화면은 조용했다). 뒤로 갔으면 따라간다. */
  if (S.shown > scenes.length) S.shown = scenes.length;

  while (S.shown < scenes.length) {
    const sc = scenes[S.shown];
    S.shown += 1;
    /* 멈추기를 누른 뒤에도 한 컷이 더 도착한다 — 이미 굽던 것은 끌까지 간다. 그걸
     * 그냥 "나왔습니다" 라고만 적으면 멈추기가 안 듣는 것처럼 보인다. 어느 쪽인지 말한다. */
    const tail = st.cancelled ? " (멈추기 전에 이미 굽던 것)" : "";
    addNote("▸ " + (sc.order != null ? sc.order : S.shown) + "컷 나왔습니다" + tail
            + " — " + (sc.purpose || ""));
    setBar(S.shown, st.total || 1);
  }

  /* 서버가 재시작됐거나 다른 탭이 저장을 마치면 작업 자체가 사라진다. 그때 아무 말도
   * 없이 멈춰 서면 사람은 아직 돌고 있다고 믿고 기다린다. */
  if (!st.running && !(st.scenes || []).length && !st.error && S.shown > 0) {
    stopPolling();
    liveHide();
    addNote("현상 작업이 더 이상 없습니다 — 다른 화면에서 저장되었거나 서버가 다시 시작됐습니다.");
    refresh().then(() => { if (S.view === "scenes") showView("scenes"); }).catch(() => {});
    return;
  }
  if (st.running) {
    liveShow(st.message || ("현상 중… " + (st.done || 0) + "/" + (st.total || "?")),
             [{ label: "현상 멈추기", onClick: async (b) => {
                  b.disabled = true; b.textContent = "이번 구간까지만…";
                  try { await api("/api/compose-job-cancel", {}); } catch (e) { /* 폴링이 본다 */ }
                } }],
             (st.total ? (st.done || 0) / st.total : 0));
    return;
  }

  stopPolling();

  if (st.error) { composeFailed(st); return; }
  if (st.message) addNote(st.message);
  if (st.cancelled) {
    addNote("멈췄습니다. 받아 둔 " + scenes.length + "개는 그대로 있습니다.");
    if (scenes.length) {
      liveShow("멈췄습니다 — 받아 둔 " + scenes.length + "개를 들고 있습니다.", [
        { label: "받은 " + scenes.length + "개로 마무리", go: true,
          onClick: (b) => { b.disabled = true; saveJob(); } },
        { label: "이어서 더 받기",
          onClick: async (b) => {
            b.disabled = true;
            try {
              await api("/api/compose-job", { total: st.total, batch: st.batch || 3,
                                              branching: false, resume: true });
              startPolling();
            } catch (e) { b.disabled = false; addNote(String(e.message || e), true); }
          } },
        { label: "받은 것 버리기",
          onClick: async (b) => {
            b.disabled = true;
            try { await api("/api/compose-job-discard", {}); liveHide();
                  addNote("받아 둔 장면을 버렸습니다."); }
            catch (e) { b.disabled = false; addNote(String(e.message || e), true); }
          } },
      ], (st.total ? scenes.length / st.total : 0));
    } else { liveHide(); }
    return;
  }
  if (scenes.length) await saveJob();
}

function showCancel(on) {
  let b = document.getElementById("cancelCompose");
  if (!on) { if (b && b.parentNode) b.parentNode.remove(); return; }
  if (b) return;
  b = el("button", null, "현상 멈추기");
  b.id = "cancelCompose";
  b.type = "button";
  b.addEventListener("click", async () => {
    b.disabled = true;
    b.textContent = "멈추는 중…";
    try { await api("/api/compose-job-cancel", {}); } catch (e) { /* 폴링이 결과를 본다 */ }
  });
  const row = el("div", "offer");
  row.appendChild(b);
  stream().appendChild(row);
  scrollEnd();
}

/* 실패했을 때 — 빈손으로 돌려보내지 않는다. 없는 것을 말하고, 있는 것을 보이고,
 * 할 수 있는 것을 버튼으로 둔다. 모델이 보낸 원문도 버리지 않는다. */
function composeFailed(st) {
  const got = (st.scenes || []).length;
  addNote(st.error, true);
  addNote(got
    ? ("앞서 받은 " + got + "개는 그대로 있습니다 — 버리지 않았습니다.")
    : "아직 받은 장면이 없습니다.");

  /* 복구 버튼은 탭 밖에 둔다 — 여기 두지 않으면 탭 한 번에 사라진다. */
  const acts = [];
  const left = Math.max(0, (st.total || 0) - got);
  acts.push({ label: "이어서 다시 · 약 " + fmtSecs(left * 32), go: true,
              onClick: async (b) => {
                b.disabled = true;
                try {
                  await api("/api/compose-job", { total: st.total, batch: st.batch || 3,
                                                  branching: false, resume: true });
                  startPolling();
                } catch (e) { b.disabled = false; addNote(String(e.message || e), true); }
              } });
  if (got) {
    acts.push({ label: "받은 " + got + "개로 마무리",
                onClick: (b) => { b.disabled = true; saveJob(); } });
    acts.push({ label: "받은 것 버리기",
                onClick: async (b) => {
                  b.disabled = true;
                  try { await api("/api/compose-job-discard", {}); liveHide();
                        addNote("받아 둔 장면을 버렸습니다."); }
                  catch (e) { b.disabled = false; addNote(String(e.message || e), true); }
                } });
  }
  liveShow(got ? ("현상이 멈췄습니다 — 받아 둔 " + got + "개를 들고 있습니다.")
               : "현상이 멈췄습니다.", acts, 0);

  const row = el("div", "offer");
  const from = st.failed_from || (got + 1);
  const to = st.failed_to || from;

  const again = el("button", null, "받은 글자 보기 자리");
  again.type = "button";
  again.hidden = true;
  again.addEventListener("click", async () => {
    row.remove();
    try {
      /* resume:true — 받아 둔 장면을 지우지 않고 그 다음부터 이어받는다.
       * 이게 없던 동안 이 버튼은 라벨과 정반대로 동작했다(전부 버리고 1번부터). */
      await api("/api/compose-job", { total: st.total, batch: st.batch || 3,
                                      branching: false, resume: true });
      startPolling();
    } catch (e) { addNote(String(e.message || e), true); }
  });
  row.appendChild(again);

  if (got) {
    const save = el("button", null, "받은 " + got + "개로 마무리");
    save.type = "button";
    save.addEventListener("click", () => { row.remove(); saveJob(); });
    row.appendChild(save);
  }
  if (st.raw && st.raw.trim()) {
    const show = el("button", null, "받은 글자 보기");
    show.type = "button";
    show.addEventListener("click", () => {
      show.disabled = true;
      const wrap = el("div", "turn");
      const bub = el("div", "bubble sys");
      bub.textContent = st.raw;
      wrap.appendChild(bub);
      wrap.appendChild(el("p", "line",
        "이 글자는 버리지 않았습니다. 스튜디오의 [✍ 직접 입력]에 붙여넣으면 "
        + "모델을 다시 부르지 않고도 장면이 됩니다."));
      stream().appendChild(wrap);
      scrollEnd();
    });
    row.appendChild(show);
  }
  stream().appendChild(row);
  scrollEnd();
  setBar(0, 1);
}

function offerSave(n) {
  const row = el("div", "offer");
  const save = el("button", null, "받은 " + n + "개로 마무리");
  save.type = "button";
  save.addEventListener("click", () => { row.remove(); saveJob(); });
  row.appendChild(save);
  stream().appendChild(row);
  scrollEnd();
}

/* 저장도 서버가 들고 있던 것을 쓴다 — 조립 도중 화면을 닫았다가 나중에 열어도 마무리된다. */
async function saveJob() {
  setBusy(true);
  try {
    const res = await api("/api/compose-job-save", {});
    const created = (res && res.created) || [];
    const made = created.length;
    const fixed = (res && res.fixed_anchors) || [];
    addNote("장면 " + made + "개를 저장했습니다."
            + (fixed.length ? " 앵커를 " + fixed.length + "개 장면에서 자동 보정했습니다." : "")
            + ((res && res.checker_pass === false)
               ? " 자동 검사에서 지적이 있습니다 — 스튜디오의 검사에서 확인하세요." : ""));
    S.job = null;
    S.shown = 0;
    liveHide();
    await refresh();
    const go = el("div", "offer");
    const btn = el("button", null, "장면 " + made + "개 보러 가기");
    btn.type = "button";
    btn.addEventListener("click", () => showView("scenes"));
    go.appendChild(btn);
    stream().appendChild(go);
    scrollEnd();
  } catch (e) {
    addNote(String(e.message || e), true);
    offerSave((S.job && (S.job.scenes || []).length) || 0);
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

  /* 가격표를 버튼에 붙인다 — 누르기 전에 얼마나 걸릴지 알아야 계속할지 정할 수 있다.
   * 한 장씩 뽑는 쪽을 앞에 둔다: 마음에 드는 것이 먼저 나오면 23초에 끝난다. */
  const one = el("button", "go", raws.length ? "한 장 더 · 23초" : "그림 뽑기 · 23초");
  one.type = "button";
  one.addEventListener("click", () => genFor(sc.scene_id, one, 1));
  row.appendChild(one);

  const many = el("button", null, "4장 한 번에 · 약 1분 32초");
  many.type = "button";
  many.addEventListener("click", () => genFor(sc.scene_id, many, 4));
  row.appendChild(many);

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
  /* 굽는 중에도 고를 수 있어야 한다. 서버는 "한 장 나왔습니다 — 고르거나 더 뽑으세요" 라고
   * 말하는데 화면이 S.busy 로 막고 있으면 그 안내가 거짓말이 된다. 고르기는 장면 파일
   * 하나를 바꾸는 일이고 굽는 일과 겹치지 않는다. */
  if (S.picking) return;
  S.picking = true;
  try {
    await api("/api/select", { scene_id: sid, image: rel });
    await refresh();
    /* 어느 화면에서 골랐든 그 화면이 갱신돼야 한다 — 갤러리에서 고르고 장면 탭만
     * 다시 그리면, 방금 고른 별표가 눈앞에서 안 바뀐다. */
    showView(S.view);
  } catch (e) {
    addNote(String(e.message || e), true);
  } finally { S.picking = false; }
}

async function approve(sid, btn) {
  if (S.picking) return;
  S.picking = true;
  btn.disabled = true;
  try {
    await api("/api/approve", { scene_id: sid });
    await refresh();
    showView(S.view);
  } catch (e) {
    addNote(String(e.message || e), true);
    btn.disabled = false;
  } finally { S.picking = false; }
}
/* 그림 뽑기 — 후보가 나오는 대로 보여 주고, 원할 때 멈춘다.
 *
 * 예전에는 요청한 장수가 다 구워질 때까지 화면이 한 줄짜리 문구였다. 실측으로 한 장에
 * 23초이므로 4장을 시키면 92초 동안 아무것도 못 한다. 이제 한 장이 나올 때마다 서버가
 * 등록하고, 화면은 그때마다 장면을 다시 그린다 — 마음에 드는 것이 먼저 나오면 23초에
 * 끝낼 수 있다. 총 시간이 줄어드는 게 아니라, 계속할지 내가 정하게 되는 것이다.
 *
 * 고르는 것은 여전히 사람이다. 자동 선택은 하지 않는다. */
async function genFor(sid, btn, want) {
  if (S.busy) return;
  const n = Math.max(1, Math.min(parseInt(want, 10) || 1, 4));
  setBusy(true);
  if (btn) btn.disabled = true;
  liveShow(sid + " · " + n + "장 요청 — 한 장에 약 23초", [genStopBtn(sid)], 0);
  try {
    await api("/api/gen-image", { scene_id: sid, n: n });
  } catch (e) {
    liveHide();
    addNote(String(e.message || e), true);
    if (btn) btn.disabled = false;
    setBusy(false);
    return;
  }
  await watchGen(sid, n, btn);
}

/* 굽고 있는 장면 하나를 끝날 때까지 지켜본다.
 *
 * genFor 안에 묻어 두지 않고 떼어 둔 이유: 이 고리는 **버튼을 누른 지금**만이
 * 아니라 새로고침 **뒤**에도 필요하다. 예전에는 페이지를 다시 열면 진행이
 * 통째로 안 보였다 — 그림은 서버에서 계속 굽는데 화면은 아무 일도 없는 얼굴이라,
 * 사람은 죽은 줄 알고 같은 장면을 한 번 더 시켰다(GPU 시간이 두 배로 든다). */
async function watchGen(sid, n, btn) {
  let seen = 0;
  /* 새로고침 뒤에는 몇 장을 시켰는지 페이지가 모른다 — 그건 서버가 알고 있다(want). */
  let total = Math.max(0, Number(n) || 0);
  try {
    for (;;) {
      await new Promise((r) => setTimeout(r, 2200));
      const st = await api("/api/gen-status", { scene_id: sid });
      if (st) {
        if (!total) total = Math.max(0, Number(st.want) || 0);
        liveShow(sid + " · " + (st.message || "굽는 중…"), [genStopBtn(sid)],
                 total ? (Number(st.done || 0) / total) : 0);
      }
      /* 한 장이 등록될 때마다 장면 목록이 늘어난다 — 그때마다 다시 그려서 바로 보이게 한다.
       * 숫자는 문구가 아니라 done 칸에서 읽는다: 문구는 엔진 폴링이 1.5초마다 갈아치운다. */
      if (st && Number(st.done || 0) > seen) {
        seen = Number(st.done);
        await refresh();
        if (S.view === "scenes" || S.view === "gallery") showView(S.view);
      }
      if (!st || !st.running) {
        if (st && st.error) throw new Error(st.error);
        break;
      }
    }
    liveHide();
    addNote(sid + " · 후보가 나왔습니다. 마음에 드는 것을 고르세요.");
    await refresh();
    showView("scenes");
  } catch (e) {
    liveHide();
    addNote(String(e.message || e), true);
    await refresh();
  } finally {
    if (btn) btn.disabled = false;
    setBusy(false);
  }
}

/* '그만 뽑기' 버튼 한 군데서 만든다 — 세 군데에 복사해 두면 한 곳만 고치는 날이 온다. */
function genStopBtn(sid) {
  return { label: "그만 뽑기", onClick: async (b) => {
    b.disabled = true; b.textContent = "이번 장까지만…";
    try { await api("/api/gen-cancel", { scene_id: sid }); } catch (e) { /* 폴링이 본다 */ }
  } };
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
  const want = S.chatId;
  /* setBusy 를 쓰지 않는다 — 대화를 바꾸는 일이 남이 걸어 둔 잠금을 풀면,
   * 답을 기다리는 중에 목록을 눌렀다는 이유로 보내기 버튼이 되살아난다. */
  const box = $("box");
  if (box) box.disabled = true;
  try {
    const h = await api("/api/chat-history", { chat_id: want });
    /* 목록을 빠르게 두 번 누르면 두 요청이 겹친다. 늦게 온 응답이 지금 열린 대화를
     * 덮으면 A 의 내용이 B 이름 밑에 뜨고, 거기서 한 마디 보내면 두 대화가 합쳐진다. */
    if (S.chatId !== want) return;
    S.msgs = (h && h.messages) || [];
  } catch (e) {
    if (S.chatId !== want) return;
    S.msgs = [];
    addNote(String(e.message || e), true);
  } finally {
    if (box) box.disabled = false;
  }
  if (S.chatId !== want) return;
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
    /* 기본 대화는 이 화면만의 것이 아니다 — 스튜디오의 스토리 탭이 같은 파일을 쓴다.
     * 여기서 끄면 저쪽 탭의 대답도 백지가 된다. 조용히 바꾸지 않고 먼저 말한다.
     * (따로 만든 갈래는 이 화면 전용이라 묻지 않는다.) */
    if (!S.chatId && S.useContext) {
      const ok = window.confirm(
        "기본 대화는 스튜디오의 스토리 탭과 같은 기록을 씁니다.\n" +
        "작품 설정을 끄면 그쪽 대답도 백지에서 시작합니다.\n\n" +
        "작품을 건드리고 싶지 않으면 [새 대화] 를 만드세요 — 새 대화는 처음부터 백지입니다.\n\n" +
        "그래도 끕니까?");
      if (!ok) return;
    }
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

/* 모델이 꺼져 있어도 장면은 만들 수 있다 — 저장소 규칙이 지키라고 한 유일한 경로다.
 * 지시문을 복사해 다른 곳(폰의 다른 앱, 다른 PC)에서 답을 받아 붙여넣으면 된다.
 * 이 길이 없으면 노트북을 닫는 순간 이 화면에서 할 수 있는 일이 그림 굽기뿐이다. */
function pasteBox() {
  const wrap = el("div", "editbox");
  wrap.appendChild(el("p", "line",
    "모델이 꺼져 있어도 장면은 만들 수 있습니다. 아래에서 지시문을 복사해 어디서든 답을 받고, "
    + "그 JSON 을 그대로 붙여넣으세요. 모델을 부르지 않습니다."));
  const row = el("div", "row");

  const copy = el("button", null, "지시문 복사");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    const n = Math.max(1, Math.min(parseInt($("total").value, 10) || 6, 24));
    try {
      const d = await api("/api/compose-input", { count: n, branching: false });
      await copyText((d && d.instruction) || "", copy);
    } catch (e) { addNote(String(e.message || e), true); }
  });
  row.appendChild(copy);

  const ta = el("textarea");
  ta.placeholder = "받은 JSON 을 여기에 붙여넣으세요";
  const save = el("button", "go", "붙여넣은 것으로 장면 만들기");
  save.type = "button";
  save.addEventListener("click", async () => {
    const text = (ta.value || "").trim();
    if (!text) return;
    save.disabled = true;
    try {
      const res = await api("/api/compose-manual", { text: text, force: false });
      const made = ((res && res.created) || []).length;
      /* 확인 문구는 고정 자리에 둔다 — 바로 뒤 showView 가 #stream 을 비운다. */
      liveShow("붙여넣은 것으로 장면 " + made + "개를 만들었습니다.", [
        { label: "확인", onClick: () => liveHide() },
      ], 1);
      await refresh();
      showView("scenes");
    } catch (e) {
      save.disabled = false;
      addNote(String(e.message || e), true);
    }
  });
  row.appendChild(save);

  wrap.appendChild(ta);
  wrap.appendChild(row);
  return wrap;
}

function renderTalk() {
  if (S.view !== "talk") return;
  const m = stream();
  while (m.firstChild) m.removeChild(m.firstChild);
  m.appendChild(ctxSwitch());
  if (S.llmDown) m.appendChild(pasteBox());
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
    const why = (d && d.reason) || "";
    /* 키가 거부된 것과 서버가 꺼진 것은 다른 문제다. 같은 문구로 덮으면 사람은 멀쩡히
     * 떠 있는 서버를 껐다 켜며 시간을 버린다. */
    llm.textContent = up ? "글자 연결됨" : (why === "auth" ? "글자 키 거부됨" : "글자 끊김");
    llm.title = up ? ((d && d.url) || "")
                   : (why === "auth" ? "서버는 떠 있는데 API 키를 거부했습니다."
                                     : ((d && d.error) || "연결할 수 없습니다."));
    llm.className = "chip " + (up ? "ok" : "bad");
    const wasDown = S.llmDown;
    S.llmDown = !up;
    if (wasDown !== S.llmDown && S.view === "talk") renderTalk();
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
    /* 시작할 때의 실패는 #stream 에 적으면 바로 뒤 showView 가 지운다 — 고정 자리에 둔다. */
    liveShow("서버에서 상태를 못 읽었습니다: " + String(e.message || e), [
      { label: "다시 시도", go: true, onClick: () => location.reload() },
    ], 0);
  }
  try {
    const h = await api("/api/chat-history", { chat_id: S.chatId });
    S.msgs = (h && h.messages) || [];
  } catch (e) { S.msgs = []; }
  await loadChats();

  showView("talk");

  /* 자리를 떴다 돌아왔을 때 그 사이의 진행이 보여야 한다 — 조립을 서버로 내린 이유가
   * 그것이므로, 화면을 열 때마다 돌고 있는 작업이 있는지 먼저 묻는다. */
  try {
    const st = await api("/api/compose-job-status", {});
    if (st && (st.running || (st.scenes || []).length)) {
      addNote(st.running
        ? "현상이 아직 돌고 있습니다 — 이어서 보여 드립니다."
        : "지난 현상에서 받아 둔 장면이 있습니다.");
      startPolling();
    }
  } catch (e) { /* 조립 이력이 없으면 그만이다 */ }

  /* 그림도 마찬가지다. 버튼을 누른 탭을 닫았거나 새로고침했다고 해서 굽던 것이 멈추지는
   * 않는다 — 멈춘 것은 화면의 폴링뿐이다. 그 사실을 다시 연결해 준다. */
  const pend = (S.state && S.state.gen_running) || [];
  if (pend.length) {
    addNote(pend.length > 1
      ? ("그림 작업 " + pend.length + "건이 아직 돌고 있습니다 — " + pend[0] + " 부터 보여 드립니다.")
      : (pend[0] + " 그림이 아직 굽고 있습니다 — 이어서 보여 드립니다."));
    setBusy(true);
    watchGen(pend[0], 0, null);      // await 하지 않는다 — boot 을 막으면 화면이 안 뜼다
  }

  probe();
  setInterval(probe, 30000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
