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
  // 세 가지를 따로 센다 — setBusy 위의 주석 참고.
  busy: false,       // 대화 한 턴을 기다리는 중 (보내기 잠김)
  composing: false,  // 조립이 도는 중 ([장면으로 조립]만 잠김)
  gen: false,        // 그림을 굽는 중 (굽기 버튼만 잠김)
  works: {},         // 대화 id → 그 대화가 가진 장면 수
  work: "",          // 지금 올라와 있는 작품의 대화 id
  style: "",         // 고른 그림체 키("" = 매니페스트 그대로)
  styles: [],        // 쓸 수 있는 그림체 목록
};

/* 기다리는 동안 보내기 버튼을 중지로 바꾼다. 눈앉을 띄지 않고 누를 수 있는 자리가 거기뿐이다. */
function showStop(on) {
  const b = $("send");
  if (!b) return;
  b.textContent = on ? "중지" : "보내기";
  b.disabled = false;
  b.dataset.mode = on ? "stop" : "send";
}

/* 잠금이 세 가지인데 깃발이 하나였다.
 *
 *   S.busy      — **이 화면이 대화 한 턴을 기다리는 중.** 보내기를 막는다.
 *   S.composing — 조립 작업이 도는 중. [장면으로 조립]만 막는다.
 *   S.gen       — 그림을 굽는 중. 굽기 버튼만 막는다.
 *
 * 셋을 한 깃발로 묶었더니, 조립을 시작한 화면에서 5~7분 동안 말을 걸 수 없었다.
 * 서버는 정확히 그 상황을 위해 만들어져 있는데(줄을 세워 900초까지 기다려 주고,
 * 화면은 "조립이 모델을 잡고 있어 답이 그 뒤에 옵니다 — 약 N분" 이라고 말할 준비가
 * 돼 있다) 정작 그 문구는 조립을 시작하지 **않은** 기기에서만 볼 수 있었다.
 * 새로고침해도 boot 이 다시 폴링을 켜므로 잠금이 그대로 돌아왔다.
 *
 * 뒤에서 도는 일이 앞에서 쓰는 일을 막지 않는다 — 그게 조립을 서버로 내린 이유다. */
function setBusy(on) {
  S.busy = on;
  const send = $("send");
  /* 중지 모드에서는 잠그지 않는다 — 잠그면 기다리는 사람이 멈출 방법이 없다. */
  if (send && send.dataset.mode !== "stop") send.disabled = on;
}

function setComposing(on) {
  S.composing = on;
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
/* 기다리는 동안 무슨 일이 벌어지고 있는지 한 줄로 말한다.
 *
 * 왜 필요한가(씽크북 실측): 노트북의 llama-server 는 --parallel 1 이라 조립이 도는 동안
 * 대화는 통째로 줄을 선다. 조립 275초 · 대화 단독 27초인데, 조립 중에 보낸 대화는 첫
 * 글자가 262초 뒤에 왔다. 그동안 화면에는 "생각하는 중…" 한 줄뿐이었다 — 사람은 고장 난
 * 줄 알고 새로고침하거나 같은 말을 한 번 더 보낸다.
 *
 * 조립을 서버 작업으로 내려 '탭을 닫아도 계속 돈다' 가 된 뒤로 이 상황은 더 흔해졌다.
 * 그러니 기다림 자체를 없앨 수는 없어도, **무엇을 기다리는지와 얼마나 남았는지**는
 * 말할 수 있다. 그 둘이 있으면 기다림은 견딜 만해진다(다른 탭을 보고 오면 된다). */
/* 남은 시간을 한 마디로.
 *
 * 서버가 eta 와 eta_late 를 같이 준다. eta 는 절대 올라가지 않고(올라가는 숫자를
 * 사람은 '어림이 틀렸다' 가 아니라 '작업이 고장 났다' 로 읽는다), 대신 약속한 시각까지
 * 못 끝낼 것 같으면 eta_late 가 켜진다. 그때는 어림을 내세우지 않고 **확실히 아는 것**
 * (몇 장 중 몇 장)을 앞에 둔다. 틀린 숫자보다 정확한 사실이 신뢰를 덜 깎아먹는다. */
function etaWord(st) {
  const done = Number((st && st.done) || 0);
  const total = Number((st && st.total) || 0);
  const got = total ? (total + "장 중 " + done + "장 받음") : (done + "장 받음");
  if (st && st.eta_late) return "예상보다 늦어지고 있습니다 · " + got;
  const left = Number((st && st.eta) || 0);
  return left ? ("약 " + fmtSecs(left) + " 남았습니다 · " + got) : got;
}

async function waitLine() {
  let st = null;
  try { st = await api("/api/compose-job-status", {}); } catch (e) { st = null; }
  if (st && st.running) {
    return "조립이 모델을 잡고 있어 답이 그 뒤에 옵니다 — " + etaWord(st)
           + ". 다른 탭을 보고 오셔도 됩니다.";
  }
  return "생각하는 중… (이 모델은 초당 12~14자 정도라 긴 답은 1~2분 걸립니다)";
}

async function askServer() {
  /* 답을 기다리는 1~2분 사이에 사람이 다른 대화로 넘어갈 수 있다. 서버는 요청에 실린
   * chat_id 로 올바른 파일에 저장하지만, 화면이 그걸 지금 열린 대화에 붙이면 남의 대화에
   * 남의 답이 섞이고 다음 한 마디에 그대로 저장된다. 떠날 때를 기억해 두고 확인한다. */
  const askedIn = S.chatId;
  const askedList = S.msgs;
  const wait = addNote("생각하는 중…");
  const line = wait.firstChild;
  const tick = async () => {
    if (!line || !line.parentNode) return;       // 이미 치운 뒤면 아무 일도 하지 않는다
    const t = await waitLine();
    if (line.parentNode) line.textContent = t;
  };
  tick();
  const ticker = setInterval(tick, 10000);
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
    /* 그림체 목록을 **그리기 전에** 받는다. 뒤에서 받으면 첫 화면의 드롭다운이
   * 빈 채로 그려지고, 사람은 탭을 한 번 옮겨야 보게 된다. */
  try {
    const d = await api("/api/image-style", {});
    S.style = (d && d.style) || "";
    S.styles = (d && d.styles) || [];
  } catch (e) { S.styles = []; }

  refreshComposeBtn();
    const turn = addTurn("assistant", reply, S.msgs.length - 1);
    renderOffers(reply, turn);
    loadChats();
  } catch (e) {
    wait.remove();
    if (e && e.name === "AbortError") {
      addNote("기다리기를 멈췄습니다. 서버는 답을 마저 만들고 있을 수 있고, 완성되면 기록에 남습니다. "
              + "새로고침하면 보입니다.");
    } else {
      addNote(String(e.message || e), true);
    }
  } finally {
    clearInterval(ticker);
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
      /* 모델이 적어 준 개수는 참고만 한다. 이 버튼이 하는 일은 문구와 같아야 한다 —
       * "여기까지 장면으로". 예전엔 이걸 누르면 스토리라인 문서로 통으로 굽기 시작했다. */
      const b = el("button", null, "여기까지 장면으로");
      b.type = "button";
      b.addEventListener("click", () => composeChat(false));
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

/* 지금 이 대화를 장면으로 — 새로 쓴 대목만, 기존 장면 뒤에 이어서.
 *
 * 예전 [장면으로 조립] 은 "총 몇 장면?" 을 묻고 project/story/storyline.md 를 읽었다.
 * 그런데 이 화면은 그 파일을 한 번도 쓰지 않는다 — 사람은 대화창에 이야기를 쓰는데
 * 조립은 엉뚱한 예전 문서로 장면을 만들었다(실측: 대화는 고양이·공원, 장면은 지혜·카페).
 *
 * 개수도 안 묻는다. 사람이 원한 것은 "대화하다 누르면 그 대목이 장면이 되는 것" 이지
 * "지금부터 몇 장면을 만들지 정하는 것" 이 아니었다. 새로 쓴 분량에 든 만큼(최대 4개)
 * 만들고, 통으로 다시 굽지 않으니 30~90초면 끝난다. */
async function composeChat(all) {
  if (S.composing) return;
  const btn = $("composeNow");
  if (btn) btn.disabled = true;
  try {
    const r = await api("/api/compose-chat", { chat_id: S.chatId, all: !!all });
    S.shown = 0;
    addNote(all ? "이 대화 전체를 장면으로 만듭니다 — 다 되면 이어 붙입니다."
                : "새로 쓴 대목을 장면으로 만듭니다 — 기존 장면 뒤에 이어 붙입니다.");
    liveShow("현상을 시작했습니다…", [], 0);
    startPolling();
  } catch (e) {
    addNote(String(e.message || e), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* 버튼 문구가 사실을 말하게 한다 — 새로 쓴 것이 없으면 그렇다고 적는다. */
async function refreshComposeBtn() {
  const btn = $("composeNow");
  if (!btn) return;
  try {
    const d = await api("/api/compose-chat-ready", { chat_id: S.chatId });
    const fresh = Number((d && d.fresh) || 0);
    btn.textContent = fresh ? ("여기까지 장면으로 (" + fresh + "턴)") : "장면으로 조립";
    btn.title = fresh
      ? "지난번 조립 이후 새로 쓴 " + fresh + "턴만 장면으로 만듭니다. 기존 장면은 그대로 둡니다."
      : "새로 쓴 이야기가 없습니다 — 대화를 더 이어 쓴 뒤에 누르세요.";
  } catch (e) { /* 문구만 못 고칠 뿐이다 */ }
}

async function runCompose() {
  if (S.composing) return;
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
  setComposing(true);
  pollCompose();
  pollTimer = setInterval(pollCompose, 2500);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  setComposing(false);
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
    liveShow((st.message || "현상 중…") + " — " + etaWord(st),
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

/* 장면 탭 위의 도구 띠 — 그림체 고르기 · 한 번에 굽기 · 장면 추가.
 *
 * 그림체를 여기 두는 이유: 그림을 뽑는 화면이 장면 탭이라, 무엇으로 구울지도 같은 자리에
 * 있어야 한다. 설정을 다른 탭에 두면 사람은 [그림 뽑기] 를 누른 **뒤에** 그림체가 틀렸다는
 * 걸 알게 되고, 그건 23초를 버린 뒤다. */
function sceneBar() {
  const bar = el("div", "scenebar");

  const sel = el("select", "styleSel");
  sel.id = "styleSel";
  /* 빈 배열은 자바스크립트에서 **참**이라 `S.styles || [기본]` 은 빈 목록을 그대로 쓴다.
   * 그러면 드롭다운에 항목이 하나도 없다 — 실제로 브라우저로 띄워 보고 잡았다.
   * 길이로 본다. 목록을 못 받았어도 "지금 설정" 하나는 반드시 고를 수 있어야 한다. */
  const opts = (S.styles && S.styles.length) ? S.styles : [{ key: "", label: "지금 설정" }];
  opts.forEach((st) => {
    const o = el("option", null, st.label + (st.found === false ? " (모델 없음)" : ""));
    o.value = st.key;
    if (st.key === (S.style || "")) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener("change", async () => {
    const want = sel.value;
    sel.disabled = true;
    try {
      const d = await api("/api/image-style", { style: want });
      S.style = (d && d.style) || "";
      S.styles = (d && d.styles) || S.styles;
      const hit = (S.styles || []).filter((x) => x.key === S.style)[0] || {};
      addNote(hit.found === false
        ? (hit.note || "그 그림체의 모델을 찾지 못했습니다.")
        : ("그림체: " + (hit.label || "지금 설정")
           + (S.style ? " · 바꾼 뒤 첫 장은 모델을 새로 올리느라 1분쯤 더 걸립니다" : "")));
    } catch (e) {
      addNote(String(e.message || e), true);
    } finally {
      sel.disabled = false;
    }
  });
  bar.appendChild(el("span", "note", "그림체"));
  bar.appendChild(sel);

  const all = el("button", "keep", "그림 없는 장면 전부 · 한 장씩");
  all.type = "button";
  all.id = "genAll";
  all.title = "그림이 아직 없는 장면마다 한 장씩 굽습니다. 승인된 장면은 건드리지 않습니다.";
  all.addEventListener("click", genAll);
  bar.appendChild(all);

  const add = el("button", "keep", "+ 빈 장면");
  add.type = "button";
  add.title = "맨 뒤에 빈 장면을 하나 만듭니다. 내용은 여기서 바로 고칠 수 있습니다.";
  add.addEventListener("click", addScene);
  bar.appendChild(add);
  return bar;
}

async function genAll() {
  const btn = $("genAll");
  if (btn) btn.disabled = true;
  try {
    const r = await api("/api/gen-all", { });
    addNote(r.total + "개 장면에 한 장씩 굽습니다 — 화면을 닫으셔도 계속 돕니다.");
    watchGenAll();
  } catch (e) {
    addNote(String(e.message || e), true);
    if (btn) btn.disabled = false;
  }
}

/* 일괄 생성은 몇 분짜리다. 그 사이 화면이 조용하면 사람은 죽은 줄 안다 —
 * 조립과 같은 규칙으로 고정 자리에 진행을 그리고, 멈출 길을 같이 둔다. */
async function watchGenAll() {
  const stop = { label: "그만 굽기", onClick: async (b) => {
    b.disabled = true; b.textContent = "이번 장까지만…";
    try { await api("/api/gen-all-cancel", {}); } catch (e) { /* 폴링이 본다 */ }
  } };
  let seen = -1;
  for (;;) {
    await new Promise((r) => setTimeout(r, 2500));
    let st;
    try { st = await api("/api/gen-all-status", {}); } catch (e) { continue; }
    const done = Number((st && st.done) || 0);
    const total = Number((st && st.total) || 0);
    liveShow(String((st && st.message) || "굽는 중…"), [stop], total ? done / total : 0);
    if (done !== seen) {
      seen = done;
      await refresh();
      if (S.view === "scenes" || S.view === "gallery") showView(S.view);
    }
    if (!st || !st.running) break;
  }
  const btn = $("genAll");
  if (btn) btn.disabled = false;
  let fin = {};
  try { fin = await api("/api/gen-all-status", {}); } catch (e) { fin = {}; }
  liveHide();
  addNote(String(fin.message || "일괄 생성이 끝났습니다.")
          + ((fin.failed || []).length ? (" — 실패: " + fin.failed.map((f) => f.scene_id).join(", ")) : ""));
  await refresh();
  if (S.view === "scenes") showView("scenes");
}

async function addScene() {
  try {
    const r = await api("/api/scene-add", {});
    addNote(r.scene_id + " 을 만들었습니다 — 아래에서 내용을 채우세요.");
    await refresh();
    showView("scenes");
  } catch (e) {
    addNote(String(e.message || e), true);
  }
}

/* 장면 한 줄을 그 자리에서 고친다 — 목적·대사·카메라.
 *
 * 예전에는 고치려면 스튜디오로 건너가야 했고, 폰에서는 그 화면이 좁아 사실상 불가능했다.
 * 여기서 고치는 것은 **장면 계획 필드뿐**이다(scene_ops.EDITABLE_FIELDS). 상태·승인·
 * 이미지 목록은 이 경로로 바뀌지 않는다 — 그 다섯은 상태 전이 함수만이 만든다. */
function sceneEditor(sc, card) {
  const box = el("div", "editbox");
  const rows = [
    { key: "purpose", label: "이 장면이 하는 일", value: sc.purpose || "", lines: 2 },
    { key: "dialogue", label: "대사 (한 줄에 하나)", lines: 4,
      value: (sc.dialogue || []).map((d) => (typeof d === "string" ? d
              : ((d.speaker_id ? d.speaker_id + ": " : "") + (d.line || "")))).join("\n") },
  ];
  const inputs = {};
  rows.forEach((r) => {
    box.appendChild(el("p", "line", r.label));
    const t = el("textarea");
    t.rows = r.lines;
    t.value = r.value;
    inputs[r.key] = t;
    box.appendChild(t);
  });

  const row = el("div", "row");
  const save = el("button", "go", "저장");
  save.type = "button";
  save.addEventListener("click", async () => {
    save.disabled = true;
    const fields = { purpose: inputs.purpose.value.trim() };
    /* "이름: 대사" 한 줄을 그대로 받는다 — 콜론이 없으면 화자 없는 줄로 둔다.
     * 사람에게 JSON 을 쓰게 하지 않는다. */
    const lines = inputs.dialogue.value.split("\n").map((s) => s.trim()).filter(Boolean);
    fields.dialogue = lines.map((s) => {
      const i = s.indexOf(":");
      if (i > 0 && i < 24) return { speaker_id: s.slice(0, i).trim(), line: s.slice(i + 1).trim() };
      return { speaker_id: "", line: s };
    });
    try {
      await api("/api/set-scene", { scene_id: sc.scene_id, fields: fields });
      addNote(sc.scene_id + " 을 고쳤습니다.");
      await refresh();
      showView("scenes");
    } catch (e) {
      save.disabled = false;
      addNote(String(e.message || e), true);
    }
  });
  const cancel = el("button", null, "닫기");
  cancel.type = "button";
  cancel.addEventListener("click", () => box.remove());
  row.appendChild(save);
  row.appendChild(cancel);
  box.appendChild(row);
  return box;
}

/* 삭제는 되돌릴 수 없는 유일한 장면 동작이라 반드시 묻는다.
 * 그리고 무엇이 어디로 가는지 말한다 — "지웁니다" 만으로는 사람이 판단할 수 없다. */
async function deleteScene(sc, btn) {
  const n = (sc.raw_images || []).length;
  if (!window.confirm(
    sc.scene_id + " 을 지웁니다.\n" +
    (n ? ("이 장면의 그림 " + n + "장도 같이 갑니다.\n") : "") +
    "버리지 않고 project/scenes_deleted/ 로 옮기므로 되돌릴 수 있습니다.\n\n" +
    "뒤 장면의 번호는 그대로 둡니다(당기면 이미 구운 그림과 어긋납니다).\n\n계속할까요?")) return;
  btn.disabled = true;
  try {
    const r = await api("/api/scene-delete", { scene_id: sc.scene_id });
    addNote(r.scene_id + " 을 보관소로 옮겼습니다 (" + r.archived_to + ", 그림 " + r.images + "장).");
    await refresh();
    showView("scenes");
  } catch (e) {
    btn.disabled = false;
    addNote(String(e.message || e), true);
  }
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
  /* 승인된 장면은 고치거나 지울 수 없다 — 서버가 어차피 거절하지만,
   * 누를 수 있는 버튼을 두고 거절하는 것은 사람을 두 번 움직이게 하는 일이다. */
  if (sc.status !== "APPROVED") {
    const ed = el("button", null, "내용 고치기");
    ed.type = "button";
    ed.addEventListener("click", () => {
      const open = card.querySelector(".editbox");
      if (open) { open.remove(); return; }
      card.appendChild(sceneEditor(sc, card));
    });
    row.appendChild(ed);
    const del = el("button", "del", "장면 삭제");
    del.type = "button";
    del.addEventListener("click", () => deleteScene(sc, del));
    row.appendChild(del);
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
  if (S.gen) return;
  const n = Math.max(1, Math.min(parseInt(want, 10) || 1, 4));
  S.gen = true;
  if (btn) btn.disabled = true;
  liveShow(sid + " · " + n + "장 요청 — 한 장에 약 23초", [genStopBtn(sid)], 0);
  try {
    await api("/api/gen-image", { scene_id: sid, n: n });
  } catch (e) {
    liveHide();
    addNote(String(e.message || e), true);
    if (btn) btn.disabled = false;
    S.gen = false;
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
    S.gen = false;
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
  m.appendChild(sceneBar());
  const scenes = (S.state && S.state.scenes) || [];
  if (!scenes.length) {
    addNote("아직 장면이 없습니다. [대화] 탭에서 이야기를 쓰고 조립하거나, 위의 [+ 빈 장면] 을 누르세요.");
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
  /* 대화마다 장면이 몇 개인지 같이 받는다 — 목록에서 어느 대화가 작품을 가졌는지
   * 보이지 않으면, 장면 탭을 열어 봐야 알 수 있다. */
  try {
    const w = await api("/api/works", {});
    const by = {};
    ((w && w.works) || []).forEach((x) => { by[x.chat_id || ""] = x.scenes; });
    S.works = by;
    S.work = (w && w.current) || "";
  } catch (e) { S.works = S.works || {}; }
}

async function openChat(id) {
  S.chatId = id || "";
  S.ocLoaded = false;      /* 출연진은 대화마다 다르다 — 옆 대화의 것이 켜져 보이면 안 된다 */
  /* 마지막에 본 대화를 기억한다 — 이 기기에만. 예전엔 열 때마다 기본 대화로
   * 되돌아가서, 어제 쓰던 이야기를 이어가려면 매번 목록에서 다시 찾아야 했다.
   * 서버에 두지 않는 이유: 폰과 PC 가 각자 다른 대화를 보고 있을 수 있고,
   * 그게 자연스럽다 — 한쪽이 다른 쪽을 끌고 다니면 안 된다. */
  try { localStorage.setItem("vn_last_chat", S.chatId); } catch (e) { /* 사사로운 편의다 */ }
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

  /* 장면·그림도 같이 갈아 끼운다. 이게 없으면 대화만 바뀜고 장면·갤러리·감상은
   * 남의 작품을 보여 준다 — 입력만 갈라지고 출력은 공용이던 그 상태다.
   * 굽는 중·조립 중이면 서버가 거절한다 — 그때는 이유를 적고 대화만 보여 준다. */
  try {
    const r = await api("/api/work-switch", { chat_id: want });
    if (S.chatId !== want) return;
    if (r && r.switched) {
      S.work = want;
      await refresh();
    }
  } catch (e) {
    if (S.chatId === want) addNote(String(e.message || e), true);
  }
  if (S.chatId !== want) return;
  showView("talk");     // 대화를 골랐으면 대화를 보여 준다 — 이 순간의 해시는 #list 라 그걸 따르면 목록으로 되돌아간다
}

function chatLabel(c) {
  if (c.title) return c.title;
  return c.id ? "제목 없는 대화" : "기본 대화";
}

/* ---------------------------------------------------------------- 대화 내보내기 · 가져오기
 *
 * 왜 필요한가: 이 로그들은 이 저장소에서 사용자가 가장 아끼는 자산인데, 지금까지 백업하는
 * 길이 "F 드라이브를 통째로 복사한다" 하나뿐이었다. 폰에서 쓰기 시작한 뒤로는 그것도 안 된다.
 *
 * 가져오기는 **절대 덮어쓰지 않는다**(서버가 이름을 비켜 준다). 덮어쓰기는 편해 보이지만
 * 한 번 잘못 누르면 되돌릴 수 없는 유일한 동작이고, 그 편함은 이 파일들에 걸 만한 것이 아니다. */

const IMPORT_CAP_BYTES = 7000000;   // 서버 본문 상한(10MB)에 base64 의 4/3 팽창을 반영한 값

function bytesToB64(buf) {
  /* 한 번에 넘기면 인자 수 상한에 걸려 큰 파일에서 터진다 — 잘라서 넘긴다. */
  const bytes = new Uint8Array(buf);
  const CH = 0x8000;
  let s = "";
  for (let i = 0; i < bytes.length; i += CH) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  }
  return btoa(s);
}

function dlLink(url, name, label) {
  const a = el("a", "keep", label);
  a.href = url;
  a.setAttribute("download", name);
  a.rel = "noopener";
  return a;
}

async function exportChat(c, btn) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "담는 중…";
  try {
    const r = await api("/api/chat-export", { chat_id: c.id });
    /* 눌러서 바로 받게 하고, **동시에** 고정 자리에 링크를 남긴다. 폰 브라우저는 스크립트가
     * 시작한 내려받기를 막는 일이 있는데, 그때 화면에 아무것도 안 남으면 사용자는 버튼이
     * 고장 난 줄 안다. 링크가 남아 있으면 직접 누르면 된다. */
    const a = dlLink(r.url, r.name, "받기");
    a.style.display = "none";
    document.body.appendChild(a);
    try { a.click(); } catch (e) { /* 막히면 아래 링크로 받는다 */ }
    if (a.parentNode) a.parentNode.removeChild(a);

    const acts = [{ label: "확인", onClick: () => liveHide() }];
    liveShow(r.name + " · " + (r.bytes < 1000000
               ? (Math.round(r.bytes / 1000) + "KB")
               : (r.mb + "MB"))
             + (r.reimportable ? "" : " · 이 화면으로는 다시 못 넣습니다(너무 큽니다)"),
             acts, 1);
    const row = document.getElementById("liveActs");
    if (row) row.insertBefore(dlLink(r.url, r.name, "다시 받기"), row.firstChild);
  } catch (e) {
    addNote(String(e.message || e), true);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function importChatFile(file) {
  if (!file) return;
  if (file.size > IMPORT_CAP_BYTES) {
    addNote(file.name + " 은(는) 너무 큽니다(" + Math.round(file.size / 1000000)
            + "MB). 이 화면으로 넣을 수 있는 상한은 7MB 입니다 — "
            + "PC 라면 output/chats/ 에 넣고 다시 시도하세요.", true);
    return;
  }
  liveShow(file.name + " 을(를) 읽는 중…", [], 0);
  try {
    const buf = await file.arrayBuffer();
    const r = await api("/api/chat-import", { b64: bytesToB64(buf) });
    await loadChats();
    if (S.view === "list") renderList();
    liveShow("가져왔습니다 — " + (r.title || "(제목 없음)") + " · " + r.count + "턴"
             + (r.archived ? (" · 보관 기록 " + r.archived + "줄") : "")
             + (r.renamed ? " · 같은 이름이 있어 새 이름으로 들어왔습니다" : ""),
             [{ label: "열기", go: true, onClick: () => { liveHide(); openChat(r.chat_id); } },
              { label: "확인", onClick: () => liveHide() }], 1);
  } catch (e) {
    liveHide();
    addNote(String(e.message || e), true);
  }
}

function listBar() {
  const bar = el("div", "listbar");
  const pick = el("input");
  pick.type = "file";
  pick.accept = ".zip,application/zip";
  pick.hidden = true;
  pick.addEventListener("change", async () => {
    const f = pick.files && pick.files[0];
    pick.value = "";              // 같은 파일을 두 번 고를 수 있게 비운다
    await importChatFile(f);
  });
  const b = el("button", "keep", "가져오기");
  b.type = "button";
  b.addEventListener("click", () => pick.click());
  bar.appendChild(b);
  bar.appendChild(pick);
  bar.appendChild(el("span", "note",
    "대화를 zip 으로 내보내고 다시 가져옵니다. 가져오기는 기존 대화를 덮어쓰지 않습니다 — "
    + "언제나 새 대화로 들어옵니다."));
  return bar;
}


function renderList() {
  if (S.view !== "list") return;
  const m = stream();
  while (m.firstChild) m.removeChild(m.firstChild);

  m.appendChild(listBar());

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
    const nsc = (S.works || {})[c.id || ""];
    open.appendChild(el("span", "meta", c.count + "턴 · " + when
                                        + (nsc ? (" · 장면 " + nsc + "개") : "")
                                        + (c.id === S.chatId ? " · 지금 보는 중" : "")));
    open.addEventListener("click", () => openChat(c.id));
    row.appendChild(open);

    const keep = el("button", "keep", "내보내기");
    keep.type = "button";
    keep.title = "이 대화를 zip 한 덩어리로 받습니다(보관 기록까지 들어있습니다).";
    keep.addEventListener("click", () => exportChat(c, keep));
    row.appendChild(keep);

    /* 기본 대화는 사라질 수 없다(스튜디오의 스토리 탭이 같은 파일을 쓴다).
     * 그렇다고 버튼만 회색으로 꺼 두면, 사람은 "왜 이것만 안 지워지나" 만 알고
     * 비울 방법은 모른다. 할 수 있는 일을 이름으로 준다 — 비우기. */
    const del = el("button", "del", c.id ? "삭제" : "비우기");
    del.type = "button";
    if (!c.id) {
      del.title = "기본 대화는 스튜디오와 같은 기록이라 사라지지는 않습니다. "
                + "내용을 보관본으로 옮기고 비웁니다.";
      del.addEventListener("click", async () => {
        if (!c.count) { addNote("기본 대화는 이미 비어 있습니다."); return; }
        if (!window.confirm(
          "기본 대화의 " + c.count + "턴을 비웁니다.\n" +
          "내용은 보관본으로 옮겨서 사라지지 않습니다.\n\n계속할까요?")) return;
        del.disabled = true;
        try {
          const d = await api("/api/chat-delete", { chat_id: "" });
          if (S.chatId === "") S.msgs = [];
          addNote((d && d.cleared ? d.cleared : 0) + "턴을 보관본으로 옮기고 비웠습니다.");
          await loadChats();
          renderList();
        } catch (e) {
          del.disabled = false;
          addNote(String(e.message || e), true);
        }
      });
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

/* 지금 사람이 무언가 쓰고 있는가 — 다시 그리면 그것이 사라진다.
 *
 * renderTalk 은 #stream 을 통째로 비우고 다시 그린다. 그런데 거기에는 사람이 입력 중인
 * 것들이 같이 산다: 수정 중인 문장, 모델이 꺼졌을 때 다른 데서 받아 붙여넣은 JSON.
 * 그 JSON 은 사람이 **다른 기기에서 몇 분 걸려 받아 온 것**이라, 지워지면 다시 받는 수밖에 없다.
 *
 * 상태 칩은 30초마다 돌고, 조립이 모델을 잡고 있으면 그 확인이 답을 못 받아 '꺼짐' 으로
 * 보였다가 돌아오기를 반복한다 — 그때마다 다시 그렸다. 하필 모델이 바쁨 때, 하필 그 때를
 * 위해 만든 붙여넣기 화면에서. */
function isTyping() {
  const nodes = document.querySelectorAll("#stream textarea, #stream input");
  for (let i = 0; i < nodes.length; i += 1) {
    const n = nodes[i];
    if (n === document.activeElement) return true;
    if (String(n.value || "").trim()) return true;
  }
  return false;
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

/* ---------------------------------------------------------------- 고유 캐릭터
 * 작품(장면·그림)은 대화마다 갈리지만 **인물은 모든 대화가 함께 쓴다.** 고양이 이야기에서
 * 만든 인물을 다음 단편에서도 쓰려면 서랍이 작품 밖에 있어야 한다(characters.py).
 *
 * 이 화면이 하는 일은 셋이다: 서랍 보기·고치기, 기기의 사진 붙이기,
 * 그리고 **이 대화에 누가 나오는지 고르기**(출연진). 셋째가 없으면 조립이 대화 내용과
 * 무관하게 매니페스트의 첫 인물을 모든 장면에 세운다 — 고양이 이야기에 이지혜가 서 있었다. */
/* 탭을 처음 열 때 한 번만 받아 온다 — 서랍은 자주 바뀌지 않는데, 탭을 옮길 때마다
 * 두 번씩 부르면 폰에서 화면이 눈에 띄게 늦게 뜬다. 대화를 바꾸면 다시 받는다
 * (출연진은 대화마다 다르므로, 안 받으면 옆 대화의 출연진이 켜져 보인다). */
function renderCastView() {
  renderCast();
  if (S.ocLoaded) return;
  S.ocLoaded = true;
  loadCast().then(() => renderCast()).catch((e) => {
    S.ocLoaded = false;
    addNote(String(e.message || e), true);
  });
}

async function loadCast() {
  const d = await api("/api/oc", {});
  S.oc = (d && d.characters) || [];
  S.faceLock = (d && d.face_lock) || null;
  const c = await api("/api/cast", { chat_id: S.chatId || "" });
  S.cast = (c && c.cast) || null;         /* null = 안 정함, [] = 아무도 안 나옴 */
  return S.oc;
}

function renderCast() {
  if (S.view !== "cast") return;
  const m = stream();
  while (m.firstChild) m.removeChild(m.firstChild);

  const bar = el("div", "scenebar");
  const add = el("button", "keep", "+ 대화에서 만들기");
  add.type = "button";
  add.title = "지금 대화를 읽고 로컬 LLM 이 인물 한 명을 정리합니다(대화창에 '고유캐릭터 생성하기' 라고 써도 같습니다).";
  add.addEventListener("click", () => makeOcFromChat());
  bar.appendChild(add);
  const blank = el("button", "keep", "+ 빈 인물");
  blank.type = "button";
  blank.addEventListener("click", () => saveOc("", { name: "새 인물" }));
  bar.appendChild(blank);
  m.appendChild(bar);

  /* 얼굴 고정이 지금 어디까지 되는지 **먼저** 말한다. 사진을 붙여 놓고 못 쓰면서
   * 말하지 않으면, 사람은 얼굴이 흔들릴 때마다 자기 사진을 의심한다. */
  if (S.faceLock && S.faceLock.photo_used === false) {
    const n = el("p", "note");
    n.textContent = "얼굴 고정: " + (S.faceLock.note || "");
    m.appendChild(n);
  }

  const list = (S.oc || []);
  if (!list.length) {
    addNote("아직 고유 캐릭터가 없습니다. 대화를 조금 나눈 뒤 [+ 대화에서 만들기] 를 눌러 보세요.");
    return;
  }
  list.forEach((oc) => m.appendChild(ocCard(oc)));
  m.scrollTop = 0;
}

function ocCard(oc) {
  const card = el("div", "card");
  const head = el("div", "row");
  const inCast = Array.isArray(S.cast) && S.cast.indexOf(oc.id) >= 0;
  const tick = el("button", inCast ? "go" : "keep", inCast ? "이 대화에 출연 중" : "이 대화에 넣기");
  tick.type = "button";
  tick.title = "장면으로 조립할 때 이 인물이 나옵니다.";
  tick.addEventListener("click", () => toggleCast(oc.id, !inCast));
  head.appendChild(el("b", null, oc.id + " " + (oc.name || "")));
  head.appendChild(tick);
  card.appendChild(head);

  if (oc.broken) {
    const bad = el("p", "note");
    bad.textContent = "이 인물 파일을 읽지 못했습니다: " + oc.broken;
    card.appendChild(bad);
    return card;
  }

  const p = oc.profile || {};
  const bits = [p.age, p.gender_presentation, p.hair, p.eyes, p.wardrobe].filter(Boolean);
  if (bits.length) card.appendChild(el("p", "line", bits.join(" · ")));
  if (oc.prompt_anchor) card.appendChild(el("p", "note", "그림 문장: " + oc.prompt_anchor));
  if ((oc.prompt_tags || []).length) card.appendChild(el("p", "note", "태그: " + oc.prompt_tags.join(", ")));

  if ((oc.photos || []).length) {
    const shelf = el("div", "shelf");
    oc.photos.forEach((ph) => {
      const wrap = el("div", "thumb");
      const img = el("img");
      img.src = ph.url + "?w=180";
      img.alt = oc.name + " 참고 사진";
      img.loading = "lazy";
      wrap.appendChild(img);
      const x = el("button", null, "떼기");
      x.type = "button";
      x.addEventListener("click", () => dropPhoto(oc.id, ph.rel));
      wrap.appendChild(x);
      shelf.appendChild(wrap);
    });
    card.appendChild(shelf);
  }

  const row = el("div", "row");
  const edit = el("button", null, "고치기");
  edit.type = "button";
  edit.addEventListener("click", () => {
    if (card.querySelector(".editbox")) return;
    card.appendChild(ocEditor(oc));
  });
  row.appendChild(edit);

  /* 사진 고르기는 label 안에 감춘 input 으로 연다 — 폰에서도 같은 길이다. */
  const pick = el("label", "filepick");
  pick.textContent = "사진 붙이기";
  const file = el("input");
  file.type = "file";
  file.accept = "image/*";
  file.addEventListener("change", () => addPhoto(oc.id, file));
  pick.appendChild(file);
  row.appendChild(pick);

  const del = el("button", "del", "서랍에서 내리기");
  del.type = "button";
  del.addEventListener("click", () => dropOc(oc));
  row.appendChild(del);
  card.appendChild(row);
  return card;
}

function ocEditor(oc) {
  const box = el("div", "editbox");
  const p = oc.profile || {};
  const rows = [
    { key: "name", label: "이름", value: oc.name || "", lines: 1 },
    { key: "prompt_anchor", label: "그림 문장 (영어 — 모든 장면에 그대로 들어갑니다)",
      value: oc.prompt_anchor || "", lines: 3 },
    { key: "prompt_tags", label: "태그 (영어, 쉼표로 구분 — 얼굴·옷을 잡는 줄)",
      value: (oc.prompt_tags || []).join(", "), lines: 2 },
    { key: "hair", label: "머리 (한국어)", value: p.hair || "", lines: 1 },
    { key: "eyes", label: "눈 (한국어)", value: p.eyes || "", lines: 1 },
    { key: "wardrobe", label: "기본 복장 (한국어)", value: p.wardrobe || "", lines: 1 },
    { key: "speech_style", label: "말투 (한국어 — 장면 대사가 이 말투로 나옵니다)",
      value: p.speech_style || "", lines: 2 },
  ];
  const inputs = {};
  rows.forEach((r) => {
    box.appendChild(el("p", "line", r.label));
    const t = el("textarea");
    t.rows = r.lines;
    t.value = r.value;
    inputs[r.key] = t;
    box.appendChild(t);
  });
  const row = el("div", "row");
  const save = el("button", "go", "저장");
  save.type = "button";
  save.addEventListener("click", async () => {
    save.disabled = true;
    const fields = {
      name: inputs.name.value.trim(),
      prompt_anchor: inputs.prompt_anchor.value.trim(),
      prompt_tags: inputs.prompt_tags.value.split(",").map((s) => s.trim()).filter(Boolean),
      profile: Object.assign({}, p, {
        hair: inputs.hair.value.trim(), eyes: inputs.eyes.value.trim(),
        wardrobe: inputs.wardrobe.value.trim(), speech_style: inputs.speech_style.value.trim(),
      }),
    };
    try {
      await saveOc(oc.id, fields);
    } catch (e) {
      save.disabled = false;
    }
  });
  const cancel = el("button", null, "닫기");
  cancel.type = "button";
  cancel.addEventListener("click", () => box.remove());
  row.appendChild(save);
  row.appendChild(cancel);
  box.appendChild(row);
  return box;
}

async function saveOc(id, fields) {
  try {
    const r = await api("/api/oc-save", { id: id || "", fields: fields, chat_id: S.chatId || "" });
    addNote((r.character.id || "") + " " + (r.character.name || "") + " 을(를) 저장했습니다.");
    await loadCast();
    showView("cast");
  } catch (e) {
    addNote(String(e.message || e), true);
    throw e;
  }
}

async function makeOcFromChat() {
  liveShow("대화에서 인물을 정리하는 중…", [], 0);
  try {
    const r = await api("/api/oc-from-chat", { chat_id: S.chatId || "" });
    liveHide();
    addNote(r.character.id + " " + r.character.name + " 을(를) 만들어 이 대화의 출연진에 넣었습니다.");
    await loadCast();
    showView("cast");
  } catch (e) {
    liveHide();
    addNote(String(e.message || e), true);
  }
}

/* 기기 사진은 base64 로 실어 보낸다 — 폰·다른 PC 에서도 같은 길이다(대화 가져오기와 같은 규칙). */
async function addPhoto(id, input) {
  const f = input.files && input.files[0];
  if (!f) return;
  input.value = "";
  if (f.size > 8 * 1024 * 1024) {
    addNote("사진이 너무 큽니다 (" + (f.size / 1048576).toFixed(1) + "MB) — 8MB 까지 받습니다.", true);
    return;
  }
  /* 못 읽으면 예외 대신 빈 값으로 돌아온다 — 읽기 실패의 결과는 "보낼 것이 없다" 하나뿐이라
   * 여기에 두 갈래를 만들 이유가 없다. */
  const b64 = await new Promise((res) => {
    const rd = new FileReader();
    rd.onload = () => res(String(rd.result || ""));
    rd.onerror = () => res("");
    rd.readAsDataURL(f);
  });
  if (!b64) {
    addNote("사진을 읽지 못했습니다 — 다시 골라 주세요.", true);
    return;
  }
  try {
    await api("/api/oc-photo", { id: id, b64: b64, label: f.name });
    addNote("사진을 붙였습니다. " + ((S.faceLock && S.faceLock.note) || ""));
    await loadCast();
    showView("cast");
  } catch (e) {
    addNote(String(e.message || e), true);
  }
}

async function dropPhoto(id, rel) {
  try {
    await api("/api/oc-photo-delete", { id: id, rel: rel });
    await loadCast();
    showView("cast");
  } catch (e) {
    addNote(String(e.message || e), true);
  }
}

async function dropOc(oc) {
  if (!window.confirm(
    oc.id + " " + (oc.name || "") + " 을(를) 서랍에서 내립니다.\n" +
    "버리지 않고 project/characters_deleted/ 로 옮기므로 되돌릴 수 있습니다.\n" +
    "이미 이 인물로 만든 장면은 그대로 남습니다.\n\n계속할까요?")) return;
  try {
    const r = await api("/api/oc-delete", { id: oc.id });
    addNote(r.character_id + " 을(를) 보관소로 옮겼습니다 (" + r.archived_to + ").");
    await loadCast();
    showView("cast");
  } catch (e) {
    addNote(String(e.message || e), true);
  }
}

/* 출연진은 **대화마다** 다르다. 여기서 끈 인물은 그 대화의 장면에 나오지 않는다.
 * 아무도 안 고르면(빈 목록) 사람 없는 장면이 나온다 — 고양이·풍경 단편이 그 경우다. */
async function toggleCast(id, want) {
  const now = Array.isArray(S.cast) ? S.cast.slice() : [];
  const at = now.indexOf(id);
  if (want && at < 0) now.push(id);
  if (!want && at >= 0) now.splice(at, 1);
  try {
    const r = await api("/api/cast", { chat_id: S.chatId || "", ids: now });
    S.cast = (r && r.cast) || [];
    addNote(S.cast.length
      ? ("이 대화의 출연진: " + (r.names || []).map((x) => x.name || x.id).join(", "))
      : "이 대화에는 아무도 등장하지 않습니다 — 장면에 사람이 나오지 않습니다.");
    showView("cast");
  } catch (e) {
    addNote(String(e.message || e), true);
  }
}

const VIEWS = { list: "tabList", talk: "tabTalk", scenes: "tabScenes",
                gallery: "tabGallery", view: "tabView", cast: "tabCast" };

/* 어느 화면을 보고 있는지를 주소창에 적어 둔다.
 *
 * 이유 둘. 새로고침하면 무조건 '대화' 로 돌아갔다 — 갤러리에서 그림을 고르다가
 * 한 번 새로고침하면 다시 갤러리를 찾아가야 했다. 그리고 폰에서 감상 화면을
 * 바로 열려면 북마크할 주소가 없었다. #gallery 처럼 적어 두면 둘 다 해결된다.
 * (pushState 가 아니라 replaceState 다 — 탭을 여러 번 옮긴 것이 뒤로가기 덕미가 되면
 *  폰에서 빠져나오는 데 열 번을 눌러야 한다.) */
function viewFromHash() {
  const h = String(location.hash || "").replace(/^#/, "");
  return VIEWS[h] ? h : "";
}

function showView(v) {
  if (!VIEWS[v]) v = "talk";
  S.view = v;
  try {
    if (viewFromHash() !== v) history.replaceState(null, "", "#" + v);
  } catch (e) { /* 주소창을 못 고쳐도 화면은 그대로 동작한다 */ }
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
  else if (v === "cast") renderCastView();
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
    /* 쓰고 있는 중이면 다시 그리지 않는다. 칩은 이미 갱신됐고(위에서), 붙여넣기
     * 화면은 다음번 확인 때나 탭을 옮길 때 열린다 — 쓰던 글을 날리는 것보다 달다. */
    if (wasDown !== S.llmDown && S.view === "talk" && !isTyping()) renderTalk();
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
  open.id = "composeNow";
  open.addEventListener("click", () => composeChat(false));
  /* 개수를 직접 정하고 싶을 때만 서람을 열어 준다 — 기본은 묻지 않는 것이다. */
  const more = el("button", null, "개수 정해서…");
  more.type = "button";
  more.title = "예전 방식 — 스토리라인 문서로 정해진 개수만큼 통으로 만듭니다.";
  more.addEventListener("click", openDrawer);
  hint.textContent = "";
  hint.appendChild(open);
  hint.appendChild(more);

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

  /* 마지막에 보던 대화로 돌아간다. 그 대화가 그사이 지워졌으면 기본으로 떨어진다. */
  let last = "";
  try { last = localStorage.getItem("vn_last_chat") || ""; } catch (e) { last = ""; }
  if (last && (S.chats || []).some((c) => c.id === last)) {
    await openChat(last);
  }
  refreshComposeBtn();

  /* 그림체 목록을 **그리기 전에** 받는다. 뒤에서 받으면 첫 화면의 드롭다운이 빈 채로
   * 그려지고, 사람은 탭을 한 번 옮겼다 와야 보게 된다 — 실제로 브라우저로 띄워 보고 알았다. */
  try {
    const d = await api("/api/image-style", {});
    S.style = (d && d.style) || "";
    S.styles = (d && d.styles) || [];
  } catch (e) { S.styles = []; }

  showView(viewFromHash() || "talk");

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
    S.gen = true;
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
