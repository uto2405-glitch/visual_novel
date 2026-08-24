"use strict";
/* tools/studio.js — 로컬 웹 스튜디오의 화면 로직.
 *
 * studio.html 에서 분리된 이유: 인라인 <script> 가 하나도 없어야 서버가 CSP 에서
 * script-src 'unsafe-inline' 을 뗄 수 있다(webapp.csp_for 가 문서별로 계산한다).
 * /studio/<이름>.js 라우트로 서빙되며, 같은 라우트가 재생 엔진 vn_runtime.js 도 내보낸다.
 * 두 파일 모두 defer 라 문서 순서대로 실행된다 — 엔진이 먼저, 이 파일이 나중.
 *
 * 안전 규약: 서버 데이터를 HTML 문자열로 조립해 넣지 않는다 (selftest J01 이 감시).
 * 모든 삽입은 el()/textContent/value/속성 대입으로만 — 주입이 구조적으로 불가능하다.
 */
let S={scenes:[],chat:[],characters:[]};
const $=id=>document.getElementById(id);
function el(tag,cls,text){const n=document.createElement(tag);
 if(cls)n.className=cls;if(text!=null)n.textContent=text;return n}
// 전역 단축키가 폼 컨트롤의 키 입력을 가로채지 않게 하는 가드.
// (뷰어 설정의 슬라이더에서 ←/→ 를 누르면 값 조절 대신 이야기가 넘어가던 문제)
const FORM_TAGS={INPUT:1,TEXTAREA:1,SELECT:1,OPTION:1};
function isTypingTarget(e){const t=e&&e.target;
 if(!t||!t.tagName)return false;
 return FORM_TAGS[t.tagName]===1||t.isContentEditable===true}
const charName=id=>{const c=S.characters.find(c=>c.id===id);return c&&c.name?c.name:id};
// 복사 버튼 6곳이 쓰던 같은 코드 — 실패(비보안 컨텍스트·권한 거부)도 화면에 알린다
async function copyTo(btn,text,label){
 try{await navigator.clipboard.writeText(String(text==null?"":text));btn.textContent="복사됨 ✓"}
 catch(e){btn.textContent="복사 실패 — 직접 선택해 복사하세요"}
 setTimeout(()=>{btn.textContent=label},1500)}
// 긴 작업(장면 구성·마스터 굽기·내보내기)이 정지된 한 줄만 남기면 "멈춘 것 같다" 가 된다.
// 점 애니메이션(.typing)과 경과 초를 붙여 살아 있다는 것을 보여준다.
// 초 카운터는 aria-hidden — role=status 칸에서 1초마다 다시 읽히면 방해만 되기 때문이다.
function busy(node,label){
 if(!node)return {stop(){return 0}};
 const t0=Date.now();
 node.replaceChildren();
 node.appendChild(el("span",null,label));
 const dots=el("span","typing");dots.setAttribute("aria-hidden","true");
 for(let i=0;i<3;i++)dots.appendChild(el("i"));
 const sec=el("span",null," 0초");sec.setAttribute("aria-hidden","true");
 node.appendChild(dots);node.appendChild(sec);
 const tick=setInterval(()=>{sec.textContent=" "+Math.round((Date.now()-t0)/1000)+"초"},1000);
 return {stop(text){clearInterval(tick);node.replaceChildren();
  if(text!=null)node.textContent=text;
  return Math.round((Date.now()-t0)/1000)}}}
const took=s=>" · "+s+"초 걸림";
// PIN 세션이 끊기면(401 auth_required) 요청마다 실패 문구만 뿌리지 말고 재인증 경로를 준다
function showAuthGate(){const g=$("authGate");if(!g||!g.hidden)return;
 g.hidden=false;const b=$("authReload");if(b&&b.focus)b.focus()}
async function api(path,body){
 let r;
 try{r=await fetch(path,body?{method:"POST",
  headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{})}
 catch(e){throw new Error("서버에 연결할 수 없습니다 — 스튜디오 서버가 켜져 있는지 확인하세요.")}
 let d=null;
 try{d=await r.json()}catch(e){d=null}
 if(r.status===401&&d&&d.auth_required){showAuthGate();throw new Error("PIN 인증이 필요합니다.")}
 if(!r.ok)throw new Error((d&&d.error)||("오류 "+r.status));
 return d}
function renderChips(){
 $("chipTitle").textContent=S.title||"제목 미정";
 if(S.orch_local){$("chipKey").textContent="스토리: 로컬 LLM";$("chipKey").className="chip ok"}
 else{$("chipKey").textContent="API 키 "+(S.key_set?"연결됨":"미설정");
  $("chipKey").className="chip "+(S.key_set?"ok":"bad")}
 $("chipModel").textContent="이미지: MakeFun "+(S.mf_token?"연결됨":"토큰 미설정");
 $("chipModel").className="chip "+(S.mf_token?"ok":"bad")}
// refresh(opts) — opts.scene 이 주어지면 그 장면 카드 하나만 새로 그린다.
// 전면 재렌더는 다른 카드에 붙여넣던 그록 응답·펼친 <details> 를 통째로 날려 버렸다(감사 지적).
async function refresh(opts){
 const o=opts||{};
 const prevChat=(S&&S.chat)||[];
 S=await api("/api/state");
 // 서버는 챗로그를 /api/state 에 싣지 않는다(폰 전송량) — S 를 통째로 교체하므로
 // 여기서 되살리지 않으면 S.chat 이 undefined 가 되어 화면 전체가 죽는다.
 if(!Array.isArray(S.chat))S.chat=prevChat;
 renderChips();
 if(!$("storyline").value)$("storyline").value=S.storyline||"";
 syncFav();syncResume();
 if(o.scene&&renderScene(o.scene)){renderGallery();return}
 renderChat();renderScenes();renderGallery();renderLan()}
function renderChat(){const box=$("chatlog");box.replaceChildren();
 // /api/state 는 챗로그를 싣지 않는다(폰 전송량) — 없을 수 있으므로 반드시 가드.
 for(const m of (S.chat||[]))box.appendChild(el("div","msg "+m.role,m.content));
 box.scrollTop=box.scrollHeight}
// 챗로그는 /api/state 에서 분리돼 있다(폰 전송량) — 스토리 탭에 들어올 때 한 번만 받아온다.
let chatLoaded=false;
async function loadChatHistory(){
 if(chatLoaded||(S.chat&&S.chat.length))return;
 chatLoaded=true;
 try{const d=await api("/api/chat-history",{});
  if(Array.isArray(d.messages)&&d.messages.length){S.chat=d.messages;renderChat()}}
 catch(e){chatLoaded=false;   // 구버전 서버(라우트 없음)면 조용히 빈 상태로 둔다
  if(S.chat_count)$("storyMsg").textContent="지난 대화 "+S.chat_count+"줄을 불러오지 못했습니다."}}
async function send(){const t=$("chatInput").value.trim();if(!t)return;
 $("chatInput").value="";S.chat.push({role:"user",content:t});renderChat();
 try{const d=await api("/api/chat",{messages:S.chat});
  S.chat.push({role:"assistant",content:d.reply});renderChat()}
 catch(e){alert(e.message+"\n\nAPI 크레딧이 없으면: 아래 [그록 프롬프트 틀]을 복사해 grok.com 에서 직접 대화하고, 결과를 스토리라인 칸에 붙여넣으세요.")}}
$("btnSend").onclick=send;
$("chatInput").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send()}});
$("btnPull").onclick=()=>{const last=[...S.chat].reverse().find(m=>m.role==="assistant");
 if(last)$("storyline").value=($("storyline").value+"\n\n"+last.content).trim()};
$("btnSaveStory").onclick=async()=>{await api("/api/storyline",{text:$("storyline").value});
 $("storyMsg").textContent="저장됨 — 장면 탭에서 구성할 수 있습니다."};

// ---- 그록 프롬프트 틀 (한글) — 전체판은 templates/grok-prompts-ko.md ----
const FRAMES={
"① 아이디어 → 스토리라인":
`너는 비주얼 노벨/웹툰 스토리 기획 파트너다. 한국어로 답해.

[아이디어]
{한 줄 아이디어 또는 소재}

[원하는 것]
- 장르/분위기: {예: 청춘 성장, 잔잔+따뜻}
- 분량: 한 화 기준 장면 {10}개
- 주인공: {간단 설명, 없으면 "네가 제안해줘"}
- 꼭 넣고 싶은 요소: {…}
- 피하고 싶은 것: {…}

[출력 형식 — 이 형식만, 다른 말 없이]
1) 로그라인 1줄
2) 스토리라인 10~15문장 (기승전결이 보이게)
3) 등장인물 2~3명 — 이름/나이/성격/외형(머리·눈·복장·소품을 그림에 쓸 수 있게 구체적으로)
4) 장소 1~3곳 — 이름/분위기/시각 특징`,

"② 스토리라인 다듬기":
`아래는 내 비주얼 노벨의 스토리라인이다. 한국어로 답해.

[현재 스토리라인]
{스토리라인 붙여넣기}

[고치고 싶은 점]
- {예: 중반이 늘어짐 — 작은 갈등 하나 추가}
- {예: 결말을 더 여운 있게}

[출력]
수정된 스토리라인 전체(비슷한 길이) + 끝에 "변경 요약" 3줄. 다른 말 없이.`,

"③ 장면 구성 JSON (※자동 버튼 권장)":
`※ [장면] 탭 → 수동 모드 → [지시문 생성] 버튼이 이 틀을 앵커까지 채워 자동 생성합니다.
※ 직접 쓸 때만 아래를 채우세요.

너는 비주얼 노벨 연출가다. 아래 스토리라인을 정확히 {N}개 장면으로 분해하라.

[스토리라인]
{스토리라인}

[캐릭터 (speaker_id 는 반드시 이 목록의 id)]
- CHAR-001 {이름}: anchor="{영어 외형 앵커 원문}"

[장소]
- LOC-001 {이름}: anchor="{영어 장소 앵커 원문}"

[규칙]
1. image_prompt 는 영어, anchor 문구 원문 포함. 2. 이미지 안 글자/말풍선 금지.
3. dialogue 는 한국어 1~4줄. 4. location_id 는 목록의 id.

[출력 형식 — SCENES_JSON_ONLY]
다른 말 없이 JSON 배열만. 각 원소:
{"order":1,"purpose":"...","action_beat":"...","emotion":"...","time":"...",
 "location_id":"LOC-001","camera":{"shot":"...","angle":"...","framing":"...","focus":"..."},
 "dialogue":[{"speaker_id":"CHAR-001","text":"..."}],"image_prompt":"..."}`,

"④ 장면 이미지 프롬프트 (※자동 버튼 권장)":
`※ 장면 카드 → 수동 모드 → [① 지시문 생성] 버튼이 연속성·앵커까지 자동 조립합니다.
※ 직접 쓸 때만 아래를 채우세요.

너는 웹툰 연출 감독 겸 이미지 프롬프트 작성자다.

[캐릭터 기준(원문 그대로 포함)] {영어 앵커}
[장소 기준(원문 그대로 포함)] {영어 앵커}

[이번 장면]
- 목적: {…}  - 행동: {…}  - 감정: {…}
- 카메라: {shot/angle/framing/focus}
- 화풍: {예: 따뜻한 셀 셰이딩 웹툰}

[규칙] 이미지 안 글자·말풍선 금지, 대사 영역은 하단 여백으로만.

[출력 — 이 4개 항목만]
SCENE_PROMPT: (영어, 앵커 원문 포함)
NEGATIVE_PROMPT: (영어)
CONTINUITY_NOTES: (다음 장면으로 이어질 요소, 한국어)
DIALOGUE_PLACEMENT: (대사 빈 공간 위치, 한국어)`,

"⑤ 캐릭터 시트 (Gate B)":
`너는 캐릭터 디자이너다. 아래 캐릭터의 "캐릭터 시트"를 외부 이미지 AI 로 생성할 프롬프트를 만들어줘.

[캐릭터]
- 이름: {…}
- 외형 앵커(원문 그대로 포함): {영어 앵커}
- 성격(표정에 반영): {…}
- 화풍: {따뜻한 셀 셰이딩 웹툰}

[시트 구성]
- 전신 3면도(정면/측면/뒷면) + 표정 4종(기본/미소/놀람/울먹)
- 단색 배경 캐릭터 시트 레이아웃, 고해상도(긴 변 {2048}px 이상)

[출력 — 딱 2줄]
PROMPT: (영어 1문단)
NEGATIVE_PROMPT: (영어 1문단)`,

"⑥ 리테이크 (일관성 수정)":
`방금 생성한 장면 이미지가 기준과 어긋났다. 이미지 프롬프트를 수정해줘.

[기준 앵커(원문 유지)] {영어 앵커}
[현재 프롬프트] {붙여넣기}
[어긋난 점] {예: 머리색이 다름 / 소품 누락 / 배경 시간대 다름}
[유지할 점] {예: 구도와 조명은 그대로}

앵커 문구를 원문 그대로 포함한 수정 SCENE_PROMPT 와 NEGATIVE_PROMPT 만 출력해.`,

"⑦ 대사 톤 다듬기":
`아래 장면 대사를 캐릭터 말투에 맞게 다듬어줘. 한국어.

[캐릭터 말투]
- {이름: 말투 특징}
- {이름: 말투 특징}

[대사]
{장면 대사 붙여넣기}

장면당 1~4줄 유지. 수정본만 출력.`};

const fsel=$("frameSel");
for(const k of Object.keys(FRAMES)){const o=el("option",null,k);o.value=k;fsel.appendChild(o)}
function showFrame(){$("frameText").value=FRAMES[fsel.value]||""}
fsel.onchange=showFrame;showFrame();
$("btnFrameCopy").onclick=()=>copyTo($("btnFrameCopy"),$("frameText").value,"복사");
$("btnFrameChat").onclick=()=>{$("chatInput").value=$("frameText").value;$("chatInput").focus()};
$("btnCompose").onclick=async()=>{
 const bz=busy($("composeMsg"),"구성 중… 로컬 LLM 이 장면을 나누고 있습니다");
 try{const d=await api("/api/compose",{count:+$("composeCount").value,force:$("composeForce").checked});
  const s=bz.stop();
  $("composeMsg").textContent=d.created.length+"개 장면 생성 · "+(d.checker_pass?"검사 통과":"검사 경고 있음")+took(s);
  scDraft.clear();   // 장면이 갈렸으니 같은 id 의 옛 초안을 새 장면에 되붙이지 않는다
  await refresh()}
 catch(e){bz.stop("실패: "+e.message+" — 아래 [수동 모드]로 진행하세요(크레딧 불필요)")}};

// ---- 수동 모드: 장면 구성 (grok.com 복붙) ----
$("btnComposeInput").onclick=async()=>{try{
  const d=await api("/api/compose-input",{count:+$("composeCount").value});
  $("composeInput").value=d.instruction;$("btnComposeInputCopy").hidden=false;
  $("btnComposeInputCopy").textContent="복사"}catch(e){$("composeInput").value="실패: "+e.message}};
$("btnComposeInputCopy").onclick=()=>copyTo($("btnComposeInputCopy"),$("composeInput").value,"복사");
$("btnComposeManual").onclick=async()=>{
 const bz=busy($("composeManualMsg"),"생성 중…");
 const force=$("composeManualForce").checked||$("composeForce").checked;
 try{const d=await api("/api/compose-manual",{text:$("composeJson").value,force:force,count:+$("composeCount").value});
  bz.stop(d.created.length+"개 장면 생성 · "+(d.checker_pass?"검사 통과":"검사 경고")+(d.warning?" · "+d.warning:""));
  scDraft.clear();   // 장면이 갈렸으니 같은 id 의 옛 초안을 새 장면에 되붙이지 않는다
  await refresh()}catch(e){
  const m=/이미 장면이 있습니다/.test(e.message)
   ? "이미 장면이 있습니다 → 위 '기존 장면 백업 후 재구성'을 체크하고 다시 누르세요(기존 장면은 백업됩니다)"
   : "실패: "+e.message;
  bz.stop(m)}};

// ---- 인화 내보내기 ----
$("btnExport").onclick=async()=>{
 const bz=busy($("exportMsg"),"굽는 중… 300DPI 마스터를 만들고 있습니다");
 try{const d=await api("/api/export",{size:$("exportSize").value,bleed:+$("exportBleed").value,
   all:$("exportAll").checked,skip_upscale:$("exportSkipUp").checked});
  const s=bz.stop();
  $("exportMsg").textContent=d.count+"장 → "+(d.dir||"(없음)")
   +(d.upscaled?" · ⚠업스케일 "+d.upscaled+"장":"")+(d.skipped?" · 제외 "+d.skipped:"")+took(s)
   +" · 폰으로 받기: [뷰어] 탭 → [📥 내보낸 파일 받기]";
 }catch(e){bz.stop("실패: "+e.message)}};
$("btnContact").onclick=async()=>{
 const bz=busy($("exportMsg"),"컨택트시트 생성 중…");
 try{const d=await api("/api/export",{contact_only:true,all:$("exportAll").checked});
  bz.stop(d.contact?"컨택트시트 저장: output/print/contact_sheet.png":"대상 없음");
 }catch(e){bz.stop("실패: "+e.message)}};

// 생성 진행 조회 — 서버가 /api/gen-status 를 지원할 때만 상황을 보여주고, 없으면 조용히 멈춘다.
function pollGen(sid,msg){let live=true;
 const tick=async()=>{if(!live)return;
  try{const s=await api("/api/gen-status",{scene_id:sid});
   if(!live)return;
   if(s&&s.message)msg.textContent=s.message;
   if(s&&s.running===false){live=false;return}}
  catch(e){live=false;return}   // 미지원 서버 → 폴링 중단(기존 동작 그대로)
  setTimeout(tick,4000)};
 setTimeout(tick,4000);
 return ()=>{live=false}}
// 결함 12: 정상 종료·실패·시간초과를 구분해 돌려준다.
// {done:true} | {error:"사유"} | {timeout:true} — 호출부가 실패 사유를 화면에 남길 수 있어야 한다.
async function pollGenUntilDone(sid,msg){
 for(let i=0;i<180;i++){                       // 최대 약 12분
  await new Promise(r=>setTimeout(r,4000));
  let s;
  try{s=await api("/api/gen-status",{scene_id:sid})}
  catch(e){return {error:(e&&e.message)||"진행 상태를 확인할 수 없습니다"}}
  if(s&&s.message)msg.textContent=s.message;
  if(!s)return {done:true};                    // 구버전 서버(빈 응답) → 기존처럼 완료로 간주
  if(s.running===false)return s.error?{error:String(s.error)}:{done:true}}
 return {timeout:true}}

// ================= 장면 카드 =================
// 원래는 193줄짜리 단일 함수였다. 의미 단위(머리/프롬프트/그록수동/행동/후보/인화)로 쪼개
// 각 조각이 자기 DOM 만 만들고 돌려주게 했다. sceneCard 는 조립만 한다.

// 카드가 다시 그려져도 사용자가 입력하던 것은 살아남아야 한다(그록 응답 붙여넣기, 펼침 상태).
const scDraft=new Map();   // scene_id → {gen, set, open}
function draftOf(sid){let d=scDraft.get(sid);
 if(!d){d={gen:"",set:"",open:null};scDraft.set(sid,d)}
 return d}

function scHeader(sc){const head=el("div","row");
 head.appendChild(el("b",null,sc.scene_order+". "+sc.scene_id));
 head.appendChild(el("span","badge "+sc.status,sc.status));
 return head}

function scPromptBlock(sc){
 const det=el("details");
 det.appendChild(el("summary","small","대사 "+sc.dialogue.length+"줄 · 이미지 프롬프트"));
 det.appendChild(el("pre",null,(sc.dialogue||[]).map(d=>charName(d.speaker_id)+": "+d.text).join("\n")));
 const ta=el("textarea");ta.rows=4;ta.readOnly=true;ta.value=sc.prompt||"";
 ta.setAttribute("aria-label",sc.scene_id+" 이미지 프롬프트");
 det.appendChild(ta);
 const detRow=el("div","row");detRow.style.marginTop="6px";
 const btnCopy=el("button","btn ghost","프롬프트 복사");
 btnCopy.onclick=()=>copyTo(btnCopy,sc.prompt||"","프롬프트 복사");
 detRow.appendChild(btnCopy);
 detRow.appendChild(el("span","small","폴더: images/raw/"+sc.scene_id+"/"));
 det.appendChild(detRow);
 return det}

// 그록 수동 경로: 로컬 LLM 이 느릴 때 grok.com 복붙으로 이번 장면 프롬프트 만들기 (승인 전 장면만)
function scManualGrok(sc){
 const dr=draftOf(sc.scene_id);
 const mp=el("details");mp.style.marginTop="6px";
 mp.open=(dr.open==null)?!sc.prompt:dr.open;   // 프롬프트 없는 장면은 처음부터 펼쳐 둔다
 mp.addEventListener("toggle",()=>{dr.open=mp.open});
 mp.appendChild(el("summary","small","⚡ 그록 수동 · 지시문 복사 → grok.com → 결과 붙여넣기 (로컬 LLM 느릴 때)"));
 const genRow=el("div","row");genRow.style.marginTop="6px";
 const btnGen=el("button","btn ghost","① 지시문 생성");
 const btnGenCopy=el("button","btn ghost","복사");btnGenCopy.hidden=!dr.gen;
 const genOut=el("textarea");genOut.rows=5;genOut.readOnly=true;genOut.style.marginTop="6px";
 genOut.placeholder="[지시문 생성] → 복사해서 grok.com(폰 앱도 OK)에 붙여넣기";
 genOut.setAttribute("aria-label",sc.scene_id+" 그록 지시문");
 genOut.value=dr.gen;
 btnGen.onclick=async()=>{btnGen.disabled=true;
  try{const d=await api("/api/grok-input",{scene_id:sc.scene_id});
   genOut.value=d.text;btnGenCopy.hidden=false}
  catch(e){genOut.value="실패: "+e.message}
  dr.gen=genOut.value;btnGen.disabled=false};
 btnGenCopy.onclick=()=>copyTo(btnGenCopy,genOut.value,"복사");
 genRow.appendChild(btnGen);genRow.appendChild(btnGenCopy);
 mp.appendChild(genRow);mp.appendChild(genOut);
 const setIn=el("textarea");setIn.rows=5;setIn.style.marginTop="8px";
 setIn.placeholder="② grok 의 SCENE_PROMPT 응답 전체를 여기에 붙여넣기 → [프롬프트 저장] → [🎨 이미지 생성]";
 setIn.setAttribute("aria-label",sc.scene_id+" 그록 응답 붙여넣기");
 setIn.value=dr.set;
 setIn.oninput=()=>{dr.set=setIn.value};
 const setRow=el("div","row");setRow.style.marginTop="6px";
 const btnSet=el("button","btn","프롬프트 저장");
 const fixLab=el("label","small");const fixCk=el("input");fixCk.type="checkbox";fixCk.checked=true;
 fixLab.appendChild(fixCk);fixLab.appendChild(document.createTextNode(" 앵커 자동 보정(검사 통과 보장)"));
 const setMsg=el("span","small");setMsg.setAttribute("role","status");
 btnSet.onclick=async()=>{btnSet.disabled=true;setMsg.textContent="저장 중…";
  try{const d=await api("/api/set-prompt",
   {scene_id:sc.scene_id,text:setIn.value,fix_anchors:fixCk.checked});
   dr.set="";                                   // 저장에 성공한 초안만 비운다
   setMsg.textContent=d.checker_pass?"저장됨 · 검사 통과":"저장됨 · 경고: "+d.fails;
   await refresh({scene:sc.scene_id})}
  catch(e){setMsg.textContent="실패: "+e.message;btnSet.disabled=false}};
 mp.appendChild(setIn);setRow.appendChild(btnSet);setRow.appendChild(fixLab);
 setRow.appendChild(setMsg);mp.appendChild(setRow);
 return mp}

function scBtnGenPrompt(sc,msg){
 const b=el("button","btn","🤖 프롬프트 생성");
 b.title="로컬 LLM 이 이 장면의 이미지 프롬프트를 만듭니다";
 b.onclick=async()=>{b.disabled=true;msg.textContent="로컬 LLM 프롬프트 생성 중…";
  try{const d=await api("/api/gen-prompt",{scene_id:sc.scene_id});
   msg.textContent=d.checker_pass?"프롬프트 생성 · 검사 통과":"생성됨 · 경고: "+d.fails;
   await refresh({scene:sc.scene_id})}
  catch(e){msg.textContent="실패: "+e.message;b.disabled=false}};
 return b}

function scBtnGenImage(sc,msg){
 const b=el("button","btn","🎨 이미지 생성");
 b.title="MakeFun AI 로 이미지를 생성해 자동 등록합니다 (1~3분)";
 b.onclick=async()=>{b.disabled=true;msg.textContent="MakeFun 생성 중… (1~3분)";
  const stop=pollGen(sc.scene_id,msg);   // 서버가 진행 조회를 지원하면 상황을 보여준다
  try{const d=await api("/api/gen-image",{scene_id:sc.scene_id,n:1});
   if(d&&d.running){const r=await pollGenUntilDone(sc.scene_id,msg);stop();
    // 실패·시간초과면 사유를 화면에 남긴다(카드가 새로 그려지면 메시지가 지워지므로 여기서 끝낸다)
    if(r&&r.error){msg.textContent="실패: "+r.error;b.disabled=false;return}
    if(r&&r.timeout){msg.textContent="시간 초과 — 아직 생성 중일 수 있습니다. 잠시 뒤 [폴더 스캔]으로 확인하세요.";
     b.disabled=false;return}
    msg.textContent="생성 완료 — 후보를 확인하세요";await refresh({scene:sc.scene_id});return}
   stop();msg.textContent="생성 "+(d.generated||[]).length+"장 · 자동검사 "+d.auto;
   await refresh({scene:sc.scene_id})}
  catch(e){stop();msg.textContent="실패: "+e.message;b.disabled=false}};
 return b}

function scBtnScan(sc,msg){
 const b=el("button","btn ghost","폴더 스캔");
 b.onclick=async()=>{b.disabled=true;msg.textContent="폴더 확인 중…";
  try{const d=await api("/api/register-images",{scene_id:sc.scene_id});
   msg.textContent="후보 "+d.count+"장 · 자동검사 "+d.auto;await refresh({scene:sc.scene_id})}
  catch(e){msg.textContent="실패: "+e.message;b.disabled=false}};
 return b}

// 폰/PC 공용: 이미지 직접 업로드(폴더 접근 없이 만들기 완성)
function scAddUpload(act,sc,msg){
 const up=el("input");up.type="file";up.accept="image/*";up.style.display="none";
 up.setAttribute("aria-hidden","true");up.tabIndex=-1;
 const b=el("button","btn ghost","📤 이미지 업로드");
 b.onclick=()=>up.click();
 up.onchange=()=>{const f=up.files&&up.files[0];if(!f)return;
  msg.textContent="업로드 중…";const rd=new FileReader();
  rd.onerror=()=>{msg.textContent="실패: 파일을 읽을 수 없습니다"};
  rd.onload=async()=>{try{const d=await api("/api/upload-image",
    {scene_id:sc.scene_id,filename:f.name,data_b64:String(rd.result)});
    msg.textContent="업로드+검사 "+d.auto+" (후보 "+d.count+"장)";
    await refresh({scene:sc.scene_id})}
   catch(e){msg.textContent="실패: "+e.message}};
  rd.readAsDataURL(f)};
 act.appendChild(b);act.appendChild(up)}

function scBtnApprove(sc,msg){
 const b=el("button","btn seal","승인 도장 찍기");
 b.onclick=async()=>{b.disabled=true;msg.textContent="승인 중…";
  try{await api("/api/approve",{scene_id:sc.scene_id});
   msg.textContent="승인됨 — 갤러리에 모입니다";await refresh({scene:sc.scene_id})}
  catch(e){msg.textContent="실패: "+e.message;b.disabled=false}};
 return b}

function scActions(sc){
 const act=el("div","row");act.style.marginTop="8px";
 const msg=el("span","small");msg.setAttribute("role","status");
 if(sc.status!=="APPROVED"&&!sc.prompt)act.appendChild(scBtnGenPrompt(sc,msg));
 if(sc.status!=="APPROVED"&&sc.prompt)act.appendChild(scBtnGenImage(sc,msg));
 if(sc.prompt){const bcp=el("button","btn ghost","🖼 프롬프트 복사");
  bcp.title="이 프롬프트를 외부 이미지 AI 에 붙여넣을 수도 있습니다";
  bcp.onclick=()=>copyTo(bcp,sc.prompt,"🖼 프롬프트 복사");
  act.appendChild(bcp)}
 act.appendChild(scBtnScan(sc,msg));
 if(sc.status!=="APPROVED")scAddUpload(act,sc,msg);
 if(sc.selected_image)act.appendChild(scBtnApprove(sc,msg));
 act.appendChild(msg);
 return {act,msg}}

// 후보 썸네일: img+onclick 이 아니라 button — 키보드로 고를 수 있고 선택 상태를 읽어 준다.
// 표시 폭 96px 이므로 원본이 아니라 서버 축소본(?w=)을 받는다(고해상도 화면 대비 2배).
function scThumbs(sc,msg){
 const th=el("div","thumbs");
 const raws=sc.raw_images||[];
 raws.forEach((r,i)=>{
  const sel=r===sc.selected_image;
  const b=el("button");
  b.title=r.split("/").pop();
  b.setAttribute("aria-pressed",sel?"true":"false");
  b.setAttribute("aria-label","후보 "+(i+1)+"/"+raws.length+" 고르기 — "+(sc.purpose||sc.scene_id));
  const img=el("img",sel?"sel":null);
  img.src="/img/"+r.replace(/^images\//,"")+"?w=224";
  img.alt="";img.loading="lazy";img.decoding="async";
  b.appendChild(img);
  b.onclick=async()=>{msg.textContent="선택 중…";
   try{const d=await api("/api/select",{scene_id:sc.scene_id,image:r});
    msg.textContent=d.auto_pass?"선택됨 — 도장 찍을 수 있음":"선택됨 · 경고: "+d.fails;
    await refresh({scene:sc.scene_id})}
   catch(e){msg.textContent="실패: "+e.message}};
  th.appendChild(b)});
 return th}

// 인화 규격 — 서버 print_export.SIZES 와 같은 목록(parse_size 가 이 값들을 모두 받는다).
// [굽기]·[즐겨찾기만 인화]·[크롭 미리보기] 세 곳이 갈라지지 않도록 여기 한 번만 적는다.
// 값은 키·한글 라벨·세로 기준 종횡비(짧은 변/긴 변) 순. 작은 규격부터.
const PRINT_SIZES=[
 ["photocard","포토카드 55×85mm",55/85],
 ["namecard","명함 50×90mm",50/90],
 ["3x5","3.5×5 (89×127mm)",3.5/5],
 ["a6","A6 (105×148mm)",105/148],
 ["4x6","엽서 4×6",4/6],
 ["5x7","5×7",5/7],
 ["a5","A5 (148×210mm)",148/210],
 ["8x10","8×10",8/10],
 ["a4","A4 (210×297mm)",210/297],
 ["11x14","11×14",11/14]];
const CROP_RATIO={};
for(const s of PRINT_SIZES)CROP_RATIO[s[0]]=s[2];
function fillSizeSel(sel,def){if(!sel)return;
 sel.replaceChildren();
 for(const s of PRINT_SIZES){const o=el("option",null,s[1]);o.value=s[0];sel.appendChild(o)}
 sel.value=def||"5x7"}
fillSizeSel($("exportSize"));fillSizeSel($("favPrintSize"));
// 75 · 크롭 미리보기 — 규격을 고르면 어디가 잘리는지 이미지 위에 직접 보여주고 앵커를 정한다
function scCrop(sc){
 const bc=el("button","btn ghost","✂ 크롭 미리보기");
 const wrap=el("div");wrap.hidden=true;wrap.style.marginTop="8px";
 const ctl=el("div","row");
 const selSize=el("select");selSize.setAttribute("aria-label","크롭 규격");
 fillSizeSel(selSize,"5x7");   // 굽기 select 와 같은 목록·같은 라벨
 const selAnc=el("select");selAnc.setAttribute("aria-label","크롭 기준 위치");
 for(const a of [["center","가운데"],["top","위"],["bottom","아래"],["left","왼쪽"],["right","오른쪽"]]){
  const o=el("option",null,a[1]);o.value=a[0];selAnc.appendChild(o)}
 selAnc.value=(sc.print&&sc.print.crop_anchor)||"center";
 const note=el("span","small");note.setAttribute("role","status");
 ctl.appendChild(el("span","small","규격"));ctl.appendChild(selSize);
 ctl.appendChild(el("span","small","기준"));ctl.appendChild(selAnc);ctl.appendChild(note);
 const stage=el("div");stage.style.cssText=
  "position:relative;display:inline-block;margin-top:8px;max-width:100%;line-height:0";
 // 접혀 있는 동안에는 src 를 넣지 않는다 — 예전에는 카드가 그려지는 순간 장면 수만큼
 // 숨은 요청(과 서버 썸네일 생성)이 한꺼번에 일어났다. 펼칠 때 한 장만 받는다.
 const im=el("img");im.alt=sc.purpose||sc.scene_id;
 im.loading="lazy";im.decoding="async";
 const loadOnce=()=>{if(!im.getAttribute("src"))im.src=sc.image_url+"?w=420"};
 im.style.cssText="max-width:100%;border-radius:8px;display:block";
 const shadeTop=el("div"),shadeBot=el("div"),frame=el("div");
 const shadeCss="position:absolute;left:0;right:0;background:rgba(8,6,14,.66);pointer-events:none";
 shadeTop.style.cssText=shadeCss;shadeBot.style.cssText=shadeCss;
 frame.style.cssText="position:absolute;border:2px solid var(--jade);pointer-events:none;"+
  "box-shadow:0 0 0 1px rgba(0,0,0,.5)";
 stage.appendChild(im);stage.appendChild(shadeTop);stage.appendChild(shadeBot);stage.appendChild(frame);
 function draw(){
  const iw=sc.print.px[0],ih=sc.print.px[1];
  const want=CROP_RATIO[selSize.value]||(5/7);        // 세로(긴 변 아래) 기준 종횡비
  const src=iw/ih;
  let cw,ch;                                          // 잘라낼 영역(원본 px)
  if(src>want){ch=ih;cw=Math.round(ih*want)}else{cw=iw;ch=Math.round(iw/want)}
  const keep=Math.round((cw*ch)/(iw*ih)*100);
  note.textContent="원본의 "+keep+"% 사용 · "+(100-keep)+"% 잘림";
  const pw=im.clientWidth||1,ph=im.clientHeight||1;   // 화면 표시 크기로 환산
  const fw=pw*(cw/iw),fh=ph*(ch/ih);
  let left=(pw-fw)/2,top=(ph-fh)/2;
  const a=selAnc.value;
  if(a==="top")top=0; else if(a==="bottom")top=ph-fh;
  else if(a==="left")left=0; else if(a==="right")left=pw-fw;
  frame.style.left=left+"px";frame.style.top=top+"px";
  frame.style.width=Math.max(0,fw-4)+"px";frame.style.height=Math.max(0,fh-4)+"px";
  shadeTop.style.top="0px";shadeTop.style.height=Math.max(0,top)+"px";
  shadeBot.style.top=(top+fh)+"px";shadeBot.style.height=Math.max(0,ph-top-fh)+"px"}
 selSize.onchange=draw;
 selAnc.onchange=async()=>{draw();
  try{await api("/api/set-crop",{scene_id:sc.scene_id,anchor:selAnc.value});
   note.textContent+=" · 기준 저장됨"}catch(e){note.textContent+=" · 저장 실패(미지원 서버)"}};
 im.onload=draw;
 bc.onclick=()=>{wrap.hidden=!wrap.hidden;bc.setAttribute("aria-expanded",String(!wrap.hidden));
  if(!wrap.hidden){loadOnce();draw()}};   // 이미지가 늦게 오면 im.onload 가 다시 그린다
 bc.setAttribute("aria-expanded","false");
 wrap.appendChild(ctl);wrap.appendChild(stage);
 return {btn:bc,wrap}}

// 인화 프리플라이트 배지 (선택 이미지가 실물 인화에 적합한지) — 카드에 붙일 노드 배열
function scPrint(sc){
 if(!sc.print)return [];
 const p=sc.print,pr=el("div","row");pr.style.marginTop="8px";
 let txt,cls;
 if(!p.px){txt="인화: 크기 판독 불가";cls="bad"}
 else if(p.printable){txt="인화 @300DPI 최대 "+p.max+" · 긴 변 "+p.long_in+"인치";cls="ok"}
 else{txt="인화 @300DPI 부적합 (긴 변 "+p.long_in+"인치, 엽서 미만) — 업스케일 권장";cls="bad"}
 pr.appendChild(el("span","chip "+cls,txt));
 const out=el("pre");out.hidden=true;out.style.marginTop="6px";out.setAttribute("role","status");
 const btn=el("button","btn ghost","인화 규격 상세");
 btn.onclick=async()=>{try{const d=await api("/api/preflight",{scene_id:sc.scene_id});
  if(!d.rows||!d.rows.length){out.textContent="크기 판독 불가"}
  else{out.textContent=d.px[0]+"×"+d.px[1]+"px  →  300DPI 최대: "+(d.max_size_at_target||"엽서 미만")+"\n"+
   d.rows.map(r=>{const m=r.grade==="좋음"?"OK  ":(r.grade==="보통"?"~   ":"✗   ");
    return m+r.size+"  "+r.dpi+"DPI  "+r.grade+(r.crop_pct>1?" · 크롭 "+r.crop_pct+"%":"")}).join("\n")}
  out.hidden=false}catch(e){out.textContent="실패: "+e.message;out.hidden=false}};
 pr.appendChild(btn);
 const nodes=[pr];
 if(sc.image_url&&p.px){const c=scCrop(sc);pr.appendChild(c.btn);nodes.push(c.wrap)}
 nodes.push(out);
 return nodes}

function sceneCard(sc){
 const card=el("div","card");
 card.appendChild(scHeader(sc));
 if(sc.status==="APPROVED")card.appendChild(el("div","stamp","승인"));
 const purpose=el("p","small",sc.purpose||"");purpose.style.margin="6px 0";
 card.appendChild(purpose);
 card.appendChild(scPromptBlock(sc));
 if(sc.status!=="APPROVED")card.appendChild(scManualGrok(sc));
 const a=scActions(sc);
 card.appendChild(a.act);
 card.appendChild(scThumbs(sc,a.msg));
 for(const n of scPrint(sc))card.appendChild(n);
 return card}

// 카드를 scene_id 로 기억해 둔다 — 한 장면을 조작해도 나머지 카드는 건드리지 않는다.
const sceneCards=new Map();
function renderScenes(){const box=$("sceneList");box.replaceChildren();sceneCards.clear();
 for(const sc of S.scenes){const c=sceneCard(sc);sceneCards.set(sc.scene_id,c);box.appendChild(c)}}
// 한 장면만 교체. 목록 자체가 달라졌으면 false 를 돌려 호출부가 전면 재구성하게 한다.
function renderScene(sid){
 const old=sceneCards.get(sid);
 if(!old||!old.isConnected)return false;
 if(S.scenes.length!==sceneCards.size)return false;
 const sc=S.scenes.find(s=>s.scene_id===sid);
 if(!sc)return false;
 const fresh=sceneCard(sc);
 sceneCards.set(sid,fresh);old.replaceWith(fresh);
 return true}
// ---- 회상 갤러리 + 즐겨찾기(71) + 라이트박스(72) ----
// 즐겨찾기는 서버(project/favorites.json)가 정본이고, 서버가 없거나 실패하면 localStorage 로 폴백한다.
let favSet=new Set(),favRemote=false,favPushed=false;
// 결함 17: 서버의 빈 배열은 "즐겨찾기 없음"과 "favorites.json 이 아직 없음"을 구분하지 못한다.
// 그러므로 서버 목록으로 로컬을 덮어쓰지 않고 항상 합집합을 취하고, 로컬에만 있던 항목은 서버로 올린다.
function syncFav(){
 if(!Array.isArray(S.favorites)){if(!favRemote)favSet=loadFavLocal();return}
 const merged=new Set(S.favorites),extra=[];
 for(const id of loadFavLocal())if(!merged.has(id)){merged.add(id);extra.push(id)}
 favSet=merged;favRemote=true;saveFavLocal(favSet);
 if(extra.length&&!favPushed){favPushed=true;pushFavUp(extra)}}
async function pushFavUp(ids){
 for(const id of ids){
  try{await api("/api/favorite",{scene_id:id,on:true})}
  catch(e){favRemote=false;break}}   // 실패해도 로컬 목록은 그대로 살아 있다
 $("galMsg").textContent=favNote();renderGallery()}
function favNote(){return "즐겨찾기 "+favSet.size+"개 (인화 후보)"+(favRemote?"":" · 이 브라우저에만 저장됨")}
// ★ 토글은 별 하나만 칠한다 — 갤러리를 통째로 다시 만들면 스크롤 위치와 로딩된 이미지가 날아간다.
const galStars=new Map();   // scene_id → 별 버튼
function paintFav(id){
 $("galMsg").textContent=favNote();
 if($("galFavOnly").checked){renderGallery();return}   // 필터 중엔 목록 구성 자체가 바뀐다
 const b=galStars.get(id);
 if(!b||!b.isConnected){renderGallery();return}
 const on=favSet.has(id);
 b.classList.toggle("on",on);b.setAttribute("aria-pressed",on?"true":"false")}
async function toggleFav(id){
 if(favSet.has(id))favSet.delete(id);else favSet.add(id);
 const on=favSet.has(id);
 saveFavLocal(favSet);paintFav(id);
 try{const d=await api("/api/favorite",{scene_id:id,on:on});
  if(d&&Array.isArray(d.scene_ids)){
   // 결함 17: 서버 응답으로 통째로 갈아끼우면 아직 서버에 없는 로컬 항목이 사라진다 → 합집합.
   const srv=new Set(d.scene_ids);if(on)srv.add(id);else srv.delete(id);
   for(const x of favSet)if(x!==id)srv.add(x);
   favSet=srv;favRemote=true;
   saveFavLocal(favSet);paintFav(id)}}
 catch(e){favRemote=false;$("galMsg").textContent=favNote()}}
function galList(){const favOnly=$("galFavOnly").checked;
 return S.scenes.filter(s=>s.status==="APPROVED"&&(!favOnly||favSet.has(s.scene_id)))}
function galCard(sc,i){
 const card=el("div","galcard");
 // 카드 본체를 button 으로 — 중첩 button 이 되지 않도록 ★/▶ 는 형제로 띄운다
 const main=el("button","galmain");main.title="크게 보기";
 if(sc.image_url){const im=el("img");
  im.src=sc.image_url+"?w=380";        // 표시 폭 150~190px · 축소본으로 충분
  im.alt=sc.purpose||sc.scene_id;im.loading="lazy";im.decoding="async";main.appendChild(im)}
 else main.appendChild(el("div","empty",sc.purpose||sc.scene_id));
 const cap=el("div","cap",(sc.scene_order||"")+". "+(sc.purpose||sc.scene_id));
 cap.setAttribute("aria-hidden","true");   // 이미지 alt 와 같은 내용이라 두 번 읽히지 않게
 main.appendChild(cap);
 main.onclick=()=>openLightbox(i);            // 72: 클릭 = 크게 보기
 main.ondblclick=()=>playFrom(sc.scene_id);   // 기존 동작(그 장면부터 감상) 유지
 card.appendChild(main);
 const play=el("button","play","▶");
 play.title="이 장면부터 감상";
 play.setAttribute("aria-label","이 장면부터 감상 — "+(sc.purpose||sc.scene_id));
 play.onclick=e=>{e.stopPropagation();playFrom(sc.scene_id)};
 card.appendChild(play);
 const on=favSet.has(sc.scene_id);
 const star=el("button","fav"+(on?" on":""),"★");
 star.setAttribute("aria-label","즐겨찾기(인화 후보) — "+(sc.purpose||sc.scene_id));
 star.setAttribute("aria-pressed",on?"true":"false");star.title="즐겨찾기(인화 후보)";
 star.onclick=e=>{e.stopPropagation();toggleFav(sc.scene_id)};
 galStars.set(sc.scene_id,star);
 card.appendChild(star);
 return card}
function renderGallery(){const grid=$("galGrid");if(!grid)return;
 grid.replaceChildren();galStars.clear();
 const favOnly=$("galFavOnly").checked,list=galList();
 if(!list.length){grid.appendChild(el("p","small",favOnly?"즐겨찾기한 장면이 없습니다.":"승인된 장면이 아직 없습니다 — 장면을 승인하면 여기 모입니다."));return}
 list.forEach((sc,i)=>grid.appendChild(galCard(sc,i)))}
async function playFrom(sceneId){closeLightbox();await refresh();
 const idx=S.scenes.findIndex(s=>s.scene_id===sceneId);   // refresh 후 재검색 — stale 인덱스 방지
 if(idx<0){alert("장면을 찾을 수 없습니다.");return}
 startPlayback(false,idx)}
$("galFavOnly").onchange=renderGallery;
// 즐겨찾기만 인화 — 서버가 only_ids/favorites_only 를 받아 대상 장면을 제한한다
$("btnFavPrint").onclick=async()=>{
 if(!favSet.size){$("galMsg").textContent="먼저 ★ 로 인화할 장면을 골라주세요.";return}
 const bz=busy($("galMsg"),"즐겨찾기 "+favSet.size+"장 인화 마스터 굽는 중…");
 try{const d=await api("/api/export",{size:$("favPrintSize").value,
   favorites_only:true,only_ids:[...favSet]});
  const s=bz.stop();
  $("galMsg").textContent=(d.count||0)+"장 → "+(d.dir||"(없음)")
   +(d.upscaled?" · ⚠업스케일 "+d.upscaled+"장":"")+took(s)}
 catch(e){bz.stop("실패: "+e.message)}};

let lbList=[],lbIdx=-1;
function openLightbox(i){lbList=galList();lbIdx=i;
 if(lbIdx<0||lbIdx>=lbList.length)return;
 const sc=lbList[lbIdx],box=$("lightbox"),im=$("lbImg");
 if(sc.image_url){im.hidden=false;im.src=sc.image_url;im.alt=sc.purpose||sc.scene_id}
 else{im.hidden=true;im.removeAttribute("src")}
 $("lbCap").textContent=(sc.scene_order||"")+". "+(sc.purpose||sc.scene_id)+"  ·  "+sc.scene_id
  +(sc.image_url?"":"  (이미지 없음)");
 $("lbPrev").disabled=lbIdx<=0;$("lbNext").disabled=lbIdx>=lbList.length-1;
 box.hidden=false;$("lbClose").focus()}
function closeLightbox(){$("lightbox").hidden=true;lbIdx=-1}
function lbMove(step){if(lbIdx<0)return;const n=lbIdx+step;
 if(n>=0&&n<lbList.length)openLightbox(n)}
$("lbClose").onclick=closeLightbox;
$("lbPrev").onclick=e=>{e.stopPropagation();lbMove(-1)};
$("lbNext").onclick=e=>{e.stopPropagation();lbMove(1)};
$("lbPlay").onclick=e=>{e.stopPropagation();const sc=lbList[lbIdx];if(sc)playFrom(sc.scene_id)};
$("lightbox").onclick=e=>{if(e.target===$("lightbox")||e.target===$("lbImg"))closeLightbox()};
document.addEventListener("keydown",e=>{if($("lightbox").hidden)return;
 if(isTypingTarget(e)&&e.key!=="Escape")return;
 if(e.key==="Escape"){e.preventDefault();closeLightbox()}
 else if(e.key==="ArrowLeft")lbMove(-1);
 else if(e.key==="ArrowRight")lbMove(1)});

// ---- 인물과 대화 (로컬 LLM · 미연시 창) ----
let talkChat=[],vnTimer=null,vnFull="",talkWaiting=false,talkLoaded=false,talkReset=false;
function vnHeroine(){return (S&&S.characters&&S.characters[0]&&S.characters[0].name)||"이지혜"}
function vnCharId(){return (S&&S.characters&&S.characters[0]&&S.characters[0].id)||""}
function vnDefaultCG(){const s=(S&&S.scenes||[]).find(x=>x.image_url);return s?s.image_url:""}
function vnSetCG(url){const im=$("vnCG");if(!url){im.style.opacity=0;return}
 if(im.src!==url)im.src=url;im.style.opacity=1}
// 57 · 타자기 속도는 뷰어 설정(재생 엔진의 텍스트 속도)을 그대로 쓴다 — 0 이면 즉시 표시
function vnType(text){if(vnTimer){clearInterval(vnTimer);vnTimer=null}
 vnFull=text;const box=$("vnText");box.textContent="";
 const ms=vnTextSpeed();
 if(REDUCE||ms<=0){box.textContent=text;return}
 const chars=[...text];let i=0;   // 코드포인트 단위(이모지 안전)
 vnTimer=setInterval(()=>{i++;box.textContent=chars.slice(0,i).join("");
  if(i>=chars.length){clearInterval(vnTimer);vnTimer=null}},Math.max(6,ms))}
function vnDone(){if(vnTimer){clearInterval(vnTimer);vnTimer=null;$("vnText").textContent=vnFull}}
// 51 · 응답 대기 인디케이터(점 3개)
function vnTypingOn(){const box=$("vnText");box.replaceChildren();
 const w=el("span","typing");w.setAttribute("aria-label","답장을 쓰는 중");
 for(let i=0;i<3;i++)w.appendChild(el("i"));
 box.appendChild(w)}
function renderTalk(){
 $("vnName").textContent=vnHeroine();
 let cg=vnDefaultCG();
 for(const m of talkChat)if(m.photos&&m.photos.length)cg=m.photos[m.photos.length-1].url;
 vnSetCG(cg);
 const last=talkChat[talkChat.length-1];
 if(talkWaiting)vnTypingOn();
 else if(!last)$("vnText").textContent="(말을 걸어보세요…)";
 else if(last.role==="user")$("vnText").textContent="…";
 else if(!vnTimer)$("vnText").textContent=last.content;   // 타자기 중이면 건드리지 않는다
 // 백로그
 const log=$("talkLog");log.replaceChildren();
 for(const m of talkChat){const b=el("div","msg "+m.role,(m.role==="user"?"나: ":vnHeroine()+": ")+m.content);
  for(const p of (m.photos||[])){const im=el("img");im.src=p.url;im.alt=p.caption||"";
   im.loading="lazy";im.decoding="async";
   im.style.cssText="max-width:60%;border-radius:10px;margin-top:8px;display:block";b.appendChild(im)}
  log.appendChild(b)}
 log.scrollTop=log.scrollHeight}
// 49 · 서버에 저장된 대화 이력을 불러와 이어서 대화한다.
// 상태/상태조회 응답에 이력이 실려 오면 그것을, 없으면 /api/talk-history 를, 그것도 없으면 조용히 빈 상태.
function pickMsgs(o){if(!o||typeof o!=="object")return null;
 for(const k of ["talk_messages","talk_history","talk","messages","history"]){
  const v=o[k];
  if(Array.isArray(v))return v;
  if(v&&typeof v==="object"&&Array.isArray(v.messages))return v.messages}
 return null}
// 결함 1: 세 경로가 모두 실패하면 조용히 빈 화면으로 두지 않고 사용자에게 알린다.
// 1순위는 서버 계약 POST /api/talk-history → {messages,character_id}.
let talkRestoring=false;
async function restoreTalk(status){
 if(talkLoaded||talkRestoring||talkChat.length||talkWaiting)return;
 talkRestoring=true;
 let msgs=null,ok=false;
 try{
  try{const d=await api("/api/talk-history",vnCharId()?{character_id:vnCharId()}:{});
   if(d&&Array.isArray(d.messages)){msgs=d.messages;ok=true}
   else{const v=pickMsgs(d);if(Array.isArray(v)){msgs=v;ok=true}}}
  catch(e){ok=false}
  if(!ok){const v=pickMsgs(S)||pickMsgs(status);   // 구버전 서버: 상태 응답에 이력이 실려 오는 경우
   if(Array.isArray(v)){msgs=v;ok=true}}
  if(!ok){$("talkMsg").textContent=
    "지난 대화를 불러오지 못했습니다 — 빈 상태로 시작합니다. (서버가 꺼져 있거나 대화 기록 경로를 지원하지 않습니다. 지금부터의 대화는 정상 저장됩니다.)";
   return}                                          // talkLoaded 를 세우지 않아 서버 복구 후 재시도된다
  talkLoaded=true;
  if(!msgs.length)return;                           // 저장된 대화가 아직 없음 — 정상
  const restored=[];
  for(const m of msgs){
   if(!m||typeof m!=="object")continue;
   if(m.role!=="user"&&m.role!=="assistant")continue;
   restored.push({role:m.role,content:String(m.content==null?"":m.content),
    photos:Array.isArray(m.photos)?m.photos:[]})}
  if(!restored.length){$("talkMsg").textContent=
    "지난 대화를 불러오지 못했습니다 — 기록 형식을 읽을 수 없습니다. 빈 상태로 시작합니다.";return}
  talkChat=restored;renderTalk();
  $("talkMsg").textContent="지난 대화 "+restored.length+"줄을 불러왔습니다 — 이어서 이야기하세요."}
 finally{talkRestoring=false}}
async function talkStatus(){const c=$("talkStatus");
 renderTalk();
 let st=null;
 try{st=await api("/api/talk-status",{});
  if(st.up){c.textContent="로컬 LLM 연결됨";c.className="chip ok"}
  else{c.textContent="로컬 LLM 꺼짐 — serve.ps1 실행 필요";c.className="chip bad"}}
 catch(e){c.textContent="상태 확인 실패";c.className="chip bad"}
 await restoreTalk(st)}
// 50 · 전송 중에는 입력창·전송 버튼을 잠가 중복 전송을 막는다
function talkLock(on){talkWaiting=on;
 $("talkInput").disabled=on;$("btnTalk").disabled=on;$("btnTalkShot").disabled=on;
 $("btnTalk").textContent=on?"전송 중…":"전송"}
async function talkSend(){if(talkWaiting)return;
 const t=$("talkInput").value.trim();if(!t)return;
 $("talkInput").value="";talkChat.push({role:"user",content:t});
 talkLock(true);renderTalk();vnTypingOn();
 const send=talkChat.map(m=>({role:m.role,content:m.content}));   // 모델엔 텍스트만
 // 서버는 저장본과 병합해 지난 대화를 지키므로, [처음부터]로 비운 뒤 첫 발화에만 reset 을 실어
 // 사용자가 의도한 초기화를 서버에도 반영한다(그 외에는 절대 덮어쓰지 않는다).
 const body={messages:send};if(talkReset){body.reset=true}
 try{const d=await api("/api/talk",body);
  talkReset=false;
  talkChat.push({role:"assistant",content:d.reply,photos:d.photos||[]});
  talkLock(false);renderTalk();vnType(d.reply)}
 catch(e){talkLock(false);$("vnText").textContent="(대화 실패) "+e.message}
 $("talkInput").focus()}
$("btnTalk").onclick=talkSend;
// 56 · 오터치로 대화 전체가 날아가지 않게 확인 단계를 둔다
$("btnTalkClear").onclick=()=>{
 if(talkWaiting)return;
 if(talkChat.length&&!confirm("지금까지의 대화 "+talkChat.length+"줄을 지우고 처음부터 시작할까요?\n(이 화면에서는 되돌릴 수 없습니다)"))return;
 talkChat=[];talkLoaded=true;   // 명시적으로 비운 대화를 복원 재시도가 되살리지 않게
 talkReset=true;                // 다음 발화에 reset 을 실어 서버 저장본도 함께 비운다
 $("talkLog").hidden=true;$("talkMsg").textContent="처음부터 시작합니다. (다음 대화부터 새로 저장됩니다)";
 vnDone();renderTalk();$("talkInput").focus()};
// 58 · 지금 이 대화를 장면으로 남긴다 (이미지 생성은 하지 않는다 — [장면] 탭에서 따로)
$("btnTalkShot").onclick=async()=>{
 if(talkWaiting)return;
 if(!talkChat.length){$("talkMsg").textContent="먼저 대화를 나눠보세요 — 남길 순간이 있어야 합니다.";return}
 const b=$("btnTalkShot");b.disabled=true;$("talkMsg").textContent="이 순간을 장면으로 옮기는 중…";
 try{const d=await api("/api/talk-to-scene",
   {character_id:vnCharId(),messages:talkChat.map(m=>({role:m.role,content:m.content}))});
  const id=(d&&(d.scene_id||d.created||d.id))||"";
  $("talkMsg").textContent="새 장면이 만들어졌습니다"+(id?" — "+id:"")
   +" · [장면] 탭에서 프롬프트를 확인하고 [🎨 이미지 생성]을 누르세요. (이미지는 아직 만들지 않았습니다)";
  await refresh()}
 catch(e){$("talkMsg").textContent=/not found/i.test(e.message)
   ?"이 서버는 아직 [이 순간을 사진으로] 를 지원하지 않습니다 — 서버를 최신으로 올린 뒤 다시 시도하세요."
   :"실패: "+e.message}
 b.disabled=false};
$("vnTalk").onclick=e=>{if(e.target.id==="talkLogBtn"||!$("talkLog").hidden)return;vnDone()};
$("talkLogBtn").onclick=e=>{e.stopPropagation();const l=$("talkLog");l.hidden=!l.hidden;if(!l.hidden)renderTalk()};
$("talkLog").onclick=e=>{e.stopPropagation();$("talkLog").hidden=true};
$("talkInput").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();talkSend()}});

// ---- 세로 스크롤 웹툰 리딩 + 감상본 내보내기 ----
// 컷 목록 DOM 도, 읽던 위치 저장·복원(82)도 공용 엔진의 VNRuntime.renderScroll 이 한다 —
// 예전에는 스튜디오와 감상본이 같은 화면을 각자 만들고 있어서 이미 갈라져 있었다.
// 여기서 넘기는 것은 스튜디오 고유의 것뿐이다: 이미지 경로·화 제목·이름표 기본색.
let svHandle=null;
function openScrollView(){
 const rt=window.VNRuntime;
 if(!rt||typeof rt.renderScroll!=="function"){
  alert("재생 엔진(vn_runtime.js)을 불러오지 못했습니다 — 새로고침 해 보세요.");return}
 if(svHandle){svHandle.destroy();svHandle=null}
 $("svTitle").textContent=S.title||"작품";
 svHandle=rt.renderScroll(vnData(),$("svCuts"),{
  imageSrc:sc=>sc.img||"",
  epLabel:ep=>player?player.epLabel(ep):ep+"화",
  nameColor:"var(--jade)",
  scroller:$("scrollView"),
  storageKey:"vn"});          // 저장 키는 예전과 같다(vn:scroll:<제목>) — 읽던 위치가 이어진다
 if(!svHandle||!svHandle.count){alert("표시할 장면이 없습니다.");return}
 $("scrollView").hidden=false;
 svHandle.restore()}
function closeScrollView(){if(svHandle)svHandle.save();$("scrollView").hidden=true}
$("btnScrollView").onclick=async()=>{await refresh();openScrollView()};
$("btnSvClose").onclick=closeScrollView;
$("btnSvTop").onclick=()=>{$("scrollView").scrollTop=0;if(svHandle)svHandle.save()};
document.addEventListener("keydown",e=>{
 if(!$("scrollView").hidden&&e.key==="Escape"&&!isTypingTarget(e))closeScrollView()});
// 63 · 내보내기 옵션(범위·최대 변·화질)을 UI 에서 그대로 서버로 전달
function exportOpts(){return {all:$("evAll").checked,
 max_edge:Math.max(480,Math.min(4096,+$("evMaxEdge").value||1600)),
 quality:Math.max(40,Math.min(100,+$("evQuality").value||85))}}
// ---- 내보낸 파일 받기 (GET /dl/) — 폰으로 접속했을 때 파일을 곧장 저장하게 ----
// 서버는 ROOT 기준 상대경로(output/…)를 주고, /dl/ 은 output/ 아래를 기준으로 받는다.
function dlUrl(rel){const s=String(rel||"").replace(/\\/g,"/");
 const i=s.indexOf("output/");if(i<0)return "";
 const parts=s.slice(i+"output/".length).split("/").filter(Boolean);
 if(!parts.length)return "";
 return "/dl/"+parts.map(encodeURIComponent).join("/")}
function dlLink(rel,label,inline){const u=dlUrl(rel);if(!u)return null;
 const a=el("a","dllink",label);
 a.href=inline?(u+"?inline=1"):u;
 if(inline){a.target="_blank";a.rel="noopener"}else a.setAttribute("download","");
 return a}
function setMsgWithLinks(node,text,links){node.replaceChildren();
 node.appendChild(el("span",null,text));
 for(const a of links)if(a)node.appendChild(a)}
async function renderDl(){const box=$("dlList");if(!box)return;
 const m=$("dlMsg");if(m)m.textContent="목록 불러오는 중…";
 let files=[];
 try{const d=await api("/dl/");files=(d&&Array.isArray(d.files))?d.files:[]}
 catch(e){if(m)m.textContent="목록을 불러오지 못했습니다: "+e.message;return}
 box.replaceChildren();
 if(m)m.textContent=files.length?files.length+"개":"";
 if(!files.length){box.appendChild(el("p","small",
  "아직 내보낸 파일이 없습니다 — [감상본 내보내기]·[PWA 내보내기]·[마스터 굽기]를 먼저 실행하세요."));return}
 for(const f of files.slice(0,200)){
  const row=el("div","dlrow");
  const a=el("a",null,f.path);a.href=f.url;a.setAttribute("download","");
  a.title="내려받기";
  row.appendChild(a);row.appendChild(el("span","small",(f.mb||0)+"MB"));
  box.appendChild(row)}}
$("btnDlRefresh").onclick=renderDl;
$("dlBox").addEventListener("toggle",()=>{if($("dlBox").open)renderDl()});
$("btnExportViewer").onclick=async()=>{const m=$("exportViewerMsg");
 const bz=busy(m,"내보내는 중… 이미지를 파일 하나에 넣고 있습니다");
 try{const d=await api("/api/export-viewer",exportOpts());
  const s=bz.stop();
  setMsgWithLinks(m,d.file+" ("+d.mb+"MB"+took(s)+") — 이 파일 하나로 폰에서도 재생됩니다 ",
   [dlLink(d.file,"⬇ 내려받기"),dlLink(d.file,"▶ 지금 열기",true)]);
  if($("dlBox").open)renderDl()}
 catch(e){bz.stop("실패: "+e.message)}};
// 86 · PWA 내보내기 — 서버가 아직 지원하지 않으면 CLI 안내만
$("btnExportPwa").onclick=async()=>{const m=$("exportViewerMsg");
 const bz=busy(m,"PWA 내보내는 중…");
 try{const d=await api("/api/export-pwa",exportOpts());
  const s=bz.stop(),base=d.dir||d.file||"";
  setMsgWithLinks(m,(base||"완료")+" — 폰 브라우저로 열고 [홈 화면에 추가] 하면 앱처럼 씁니다"
   +(d.mb?" ("+d.mb+"MB"+took(s)+") ":" "),
   [d.dir?dlLink(d.dir+"/index.html","▶ 폰에서 열기",true):null]);
  if($("dlBox").open)renderDl()}
 catch(e){bz.stop(/not found/i.test(e.message)
   ?"이 서버는 아직 PWA 내보내기를 지원하지 않습니다 — 터미널에서: python tools/export_pwa.py"
   :"실패: "+e.message)}};

// ---- 90 · LAN 접속 주소 + QR (외부 라이브러리 없이 직접 생성) ----
// 결함 11·7: 서버 계약은 /api/state 의 lan_urls 배열 하나뿐이다.
// 없거나 비면 127.0.0.1 을 폰 주소인 것처럼 보여주지 않고 LAN 모드 안내를 낸다.
let lanUrl="";
function lanCandidates(){const out=[];
 if(Array.isArray(S.lan_urls))for(const u of S.lan_urls){
  const s=String(u||"").trim();if(s&&out.indexOf(s)<0)out.push(s)}
 return out}
function renderLan(){const pick=$("lanPick");if(!pick)return;
 const list=lanCandidates(),prev=pick.value;
 pick.replaceChildren();
 for(const u of list){const o=el("option",null,u);o.value=u;pick.appendChild(o)}
 pick.hidden=list.length<2;
 if(!list.length){pick.value="";showNoLan();return}
 pick.value=(list.indexOf(prev)>=0)?prev:list[0];
 drawQR(pick.value)}
function showNoLan(){const cv=$("qrCanvas"),msg=$("qrMsg"),addr=$("lanAddr"),b=$("btnLanCopy");
 lanUrl="";
 if(cv)cv.hidden=true;
 if(b)b.disabled=true;
 if(addr)addr.textContent="LAN 주소 없음";
 if(msg)msg.textContent="LAN 모드로 실행해야 폰에서 접속할 수 있습니다 — 터미널에서 "
  +"python tools/webapp.py --lan 로 다시 켜세요. 지금 주소("+location.origin+")는 이 PC 안에서만 열립니다."}
function drawQR(text){const cv=$("qrCanvas"),msg=$("qrMsg"),addr=$("lanAddr"),b=$("btnLanCopy");
 if(!cv||!addr)return;
 if(!text){showNoLan();return}
 lanUrl=text;addr.textContent=text;if(b)b.disabled=false;
 let mods=null;
 try{mods=qrEncode(text)}catch(e){mods=null}
 const ctx=cv.getContext?cv.getContext("2d"):null;
 if(!ctx||!mods){cv.hidden=true;
  msg.textContent="QR 을 만들 수 없습니다 — 위 주소를 폰 브라우저에 직접 입력하세요([주소 복사] 사용).";return}
 cv.hidden=false;
 const n=mods.length,q=4,total=n+q*2,scale=Math.max(3,Math.floor(220/total)),px=total*scale;
 cv.width=px;cv.height=px;
 ctx.fillStyle="#fff";ctx.fillRect(0,0,px,px);ctx.fillStyle="#000";
 for(let r=0;r<n;r++)for(let c=0;c<n;c++)if(mods[r][c])ctx.fillRect((c+q)*scale,(r+q)*scale,scale,scale);
 msg.textContent="폰 카메라로 이 QR 을 비추세요. 안 읽히면 위 주소를 직접 입력하세요."}
$("lanPick").onchange=e=>drawQR(e.target.value);
$("btnLanCopy").onclick=async()=>{const b=$("btnLanCopy");
 if(!lanUrl){b.textContent="복사할 주소 없음";setTimeout(()=>{b.textContent="주소 복사"},1300);return}
 try{await navigator.clipboard.writeText(lanUrl);
  b.textContent="복사됨";setTimeout(()=>{b.textContent="주소 복사"},1300)}
 catch(e){b.textContent="복사 실패 — 직접 입력하세요"}};

// ---- 탭 ----
// 탭은 주소(location.hash)로 라우팅하고 마지막 탭을 기억한다. 새로고침·재인증(location.reload)
// 뒤에도 보던 곳으로 돌아오고, 폰에서 특정 탭을 홈 화면에 추가하거나 링크로 열 수 있다.
const TAB_KEY="vn:studio:tab";
let curTab="";
function tabFromHash(){const h=decodeURIComponent(String(location.hash||"").replace(/^#/,""));
 return $("tab-"+h)?h:""}
// 첫 화면의 해시는 replaceState 로 조용히 적는다 — 그러지 않으면 뒤로가기 한 번이
// 아무 일도 하지 않고 주소의 #만 떼는 "죽은 한 걸음"이 된다.
function setHash(name,quiet){
 if(tabFromHash()===name)return;
 const h=window.history;
 if(quiet&&h&&h.replaceState){h.replaceState(null,"","#"+name);return}
 location.hash="#"+name}
function selectTab(name,quiet){const sec=$("tab-"+name);if(!sec)return;
 curTab=name;
 try{localStorage.setItem(TAB_KEY,name)}catch(e){}
 // 해시보다 curTab 을 먼저 세워 두었으므로 이 대입이 부르는 hashchange 는 알아서 무시된다
 setHash(name,quiet);
 document.querySelectorAll("nav button").forEach(x=>{const on=x.dataset.tab===name;
  x.classList.toggle("on",on);
  if(on)x.setAttribute("aria-current","page");else x.removeAttribute("aria-current")});
 document.querySelectorAll("section").forEach(x=>x.classList.remove("on"));
 sec.classList.add("on");
 if(name==="gallery")renderGallery();
 if(name==="talk")talkStatus();
 if(name==="story")loadChatHistory();
 if(name==="viewer"){syncResume();renderLan();if($("dlBox").open)renderDl()}}
window.addEventListener("hashchange",()=>{const t=tabFromHash();
 if(t&&t!==curTab)selectTab(t)});
// 첫 화면: 주소의 탭 > 마지막으로 보던 탭 > 스토리
function initTab(){let saved="";
 try{saved=localStorage.getItem(TAB_KEY)||""}catch(e){saved=""}
 selectTab(tabFromHash()||($("tab-"+saved)?saved:"")||"story",true)}
$("authReload").onclick=()=>{location.reload()};
$("authDismiss").onclick=()=>{$("authGate").hidden=true};
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>selectTab(b.dataset.tab));
$("btnCheck").onclick=async()=>{const d=await api("/api/check",{});
 $("checkOut").textContent=d.output};
$("btnLint").onclick=async()=>{const o=$("lintOut");o.hidden=false;o.textContent="점검 중…";
 try{const d=await api("/api/lint",{});
  o.textContent=d.findings.length?d.summary+"\n\n"+d.findings.map(f=>(f.level==="warn"?"⚠ ":"· ")+"["+f.scene_id+"] "+f.message).join("\n"):"연출·분기 양호 — 특이사항 없음"}
 catch(e){o.textContent="실패: "+e.message}};
// ---- 비주얼 노벨 뷰어 — 공용 재생 엔진(tools/vn_runtime.js) 어댑터 ----
// 재생 자체(타자기·자동/스킵·백로그·장면 이동·설정·시네마틱·엔딩 카드·화 이동·전체화면·
// 화면 꺼짐 방지)는 전부 엔진이 한다. 무대 DOM 과 CSS 도 엔진이 직접 만든다.
// 스튜디오가 하는 일은 두 가지뿐이다:
//   1) /api/state 의 장면(scene_id·dialogue·image_url…)을 엔진 스키마로 옮기기
//   2) 스튜디오에만 있는 것([이어보기] 표시·엔딩 후 갤러리 이동)을 콜백으로 잇기
// 감상본(export_viewer)이 같은 파일을 인라인해 쓴다 — 여기서 보는 연출이 곧 소장본의 연출이다.
const NAME_COLORS=["#5FB39A","#D9A441","#C77DBB","#6FA8DC","#E07A5F","#84C18B","#B58BE0","#E0A458"];
function charColor(id){if(!id)return null;let h=0;for(const c of String(id))h=(h*31+c.charCodeAt(0))>>>0;
 return NAME_COLORS[h%NAME_COLORS.length]}   // 세로 스크롤 리딩도 같은 이름 색을 쓴다
const REDUCE=window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// ★ 인화 후보는 재생과 무관하지만 같은 localStorage 규약을 쓴다(서버 저장 실패 시의 폴백)
const favKey=()=>"vn:fav:"+(S.title||"_");
function loadFavLocal(){try{return new Set(JSON.parse(localStorage.getItem(favKey())||"[]"))}catch(e){return new Set()}}
function saveFavLocal(set){try{localStorage.setItem(favKey(),JSON.stringify([...set]))}catch(e){}}

// /api/state 장면 → 엔진 스키마(export_viewer.build_data 가 만드는 것과 같은 모양)
function vnScene(sc){
 const o={id:sc.scene_id,order:sc.scene_order,purpose:sc.purpose||"",
  img:sc.image_url||"",
  lines:(sc.dialogue||[]).map(d=>({
   n:d.speaker_id?charName(d.speaker_id):"",
   c:d.speaker_id?charColor(d.speaker_id):null,
   t:d.text||"",
   p:d.placement==="top"?"top":"bottom"}))};
 if(sc.episode)o.ep=sc.episode;
 if(sc.choices&&sc.choices.length)o.choices=sc.choices;
 if(sc.branch&&sc.branch.length)o.branch=sc.branch;
 if(sc.ending){o.ending=true;
  // 엔딩 카드 이름은 ending_label 우선, 비어 있으면 purpose — 감상본과 같은 우선순위다.
  // (엔진의 endLabelOf 가 그 순서로 고른다. 여기서는 label 을 실어 보내기만 한다.)
  if(sc.ending_label)o.ending_label=sc.ending_label}
 return o}
function vnData(){return {title:S.title||"",
 scenes:(S.scenes||[]).map(vnScene),
 dating:S.dating||null,
 episodes:(S.episodes||[]).map(e=>({ep:e.episode,title:e.title||""}))}}

let player=null;
// 엔진은 한 번만 mount 하고 이후에는 데이터만 갈아 끼운다 — 무대 DOM 이 겹겹이 쌓이지 않게.
function ensurePlayer(){
 if(!window.VNRuntime)return null;
 if(player){player.setData(vnData());return player}
 player=window.VNRuntime.mount({
  data:vnData(),
  // 예전 스튜디오와 같은 저장 키 규약(vn:pos·vn:hist·vn:seen) — 읽던 위치가 그대로 이어진다
  storageKey:"vn",
  imageSrc:(sc,kind)=>{const u=(sc&&sc.img)||"";
   if(!u)return "";
   return kind==="thumb"?u+"?w=140":u},   // 목록 썸네일은 56px — 원본을 받을 이유가 없다
  onGallery:()=>selectTab("gallery"),
  onExit:syncResume,
  onSavedChange:has=>{const b=$("btnResume");if(b)b.hidden=!has},
  // 감상 중 배경을 inert 로 잠근다. 재인증 안내(#authGate)까지 잠그면 복구 버튼을 누를 수
  // 없고, 엔진이 만든 무대(.vnr)를 잠그면 뷰어 자신이 죽는다 — 둘 다 제외한다.
  backgroundNodes:()=>[...document.querySelectorAll("body > *")]
   .filter(n=>n.id!=="authGate"&&!n.classList.contains("vnr"))});
 return player}
// 65 · [이어보기] 표시는 저장 위치가 바뀔 때마다 즉시 갱신된다(새로고침 불필요)
function syncResume(){const p=ensurePlayer(),b=$("btnResume");
 if(b)b.hidden=!(p&&p.hasSaved())}
function startPlayback(resume,at){
 if(!S.scenes||!S.scenes.length){alert("장면이 없습니다. 먼저 장면을 구성하세요.");return}
 const p=ensurePlayer();
 if(!p){alert("재생 엔진(vn_runtime.js)을 불러오지 못했습니다 — 새로고침 해 보세요.");return}
 closeLightbox();
 p.start(!!resume,at)}
// 57 · 대화 탭 타자기도 뷰어 설정의 텍스트 속도를 그대로 쓴다(0 이면 즉시 표시)
function vnTextSpeed(){const s=player?player.settings():null;
 return (s&&typeof s.textSpeed==="number")?s.textSpeed:26}

$("btnPlay").onclick=async()=>{try{await refresh();startPlayback(false)}catch(e){alert("불러오기 실패: "+e.message)}};
$("btnResume").onclick=async()=>{try{await refresh();startPlayback(true)}catch(e){alert("불러오기 실패: "+e.message)}};

// ---- QR 생성기 (byte 모드 · EC=L · 버전 1~5) ----
// 외부 라이브러리 반입 금지 규약 때문에 직접 구현했다. 버전 5(106바이트)면 LAN 주소에 충분하다.
const QR_ECW={1:7,2:10,3:15,4:20,5:26};      // 버전별 EC 코드워드 수(L, 1블록)
const QR_DCW={1:19,2:34,3:55,4:80,5:108};    // 버전별 데이터 코드워드 수
const QR_ALIGN={1:0,2:18,3:22,4:26,5:30};    // 정렬 패턴 중심(0=없음)
const GEXP=new Array(512),GLOG=new Array(256);
(function(){let x=1;for(let i=0;i<255;i++){GEXP[i]=x;GLOG[x]=i;x<<=1;if(x&0x100)x^=0x11d}
 for(let i=255;i<512;i++)GEXP[i]=GEXP[i-255]})();
const gmul=(a,b)=>(a&&b)?GEXP[GLOG[a]+GLOG[b]]:0;
function qrGen(n){let g=[1];
 for(let i=0;i<n;i++){const ng=new Array(g.length+1).fill(0);
  for(let j=0;j<g.length;j++){ng[j]^=g[j];ng[j+1]^=gmul(g[j],GEXP[i])}
  g=ng}
 return g}
function qrRS(data,n){const g=qrGen(n),res=new Array(n).fill(0);
 for(const d of data){const f=d^res[0];res.shift();res.push(0);
  for(let j=0;j<n;j++)res[j]^=gmul(g[j+1],f)}
 return res}
function qrFormat(mask){const v=8|mask;   // EC=L(01) + 마스크 3비트 → BCH(15,5)
 let d=v<<10;
 for(let i=4;i>=0;i--)if(d&(1<<(i+10)))d^=0x537<<i;
 return ((v<<10)|d)^0x5412}
const QR_MASK=[(r,c)=>(r+c)%2===0,(r,c)=>r%2===0,(r,c)=>c%3===0,(r,c)=>(r+c)%3===0,
 (r,c)=>(Math.floor(r/2)+Math.floor(c/3))%2===0,(r,c)=>((r*c)%2+(r*c)%3)===0,
 (r,c)=>(((r*c)%2+(r*c)%3)%2)===0,(r,c)=>(((r+c)%2+(r*c)%3)%2)===0];
function qrPenalty(m){const n=m.length;let p=0;
 const runs=line=>{let s=1;
  for(let i=1;i<n;i++){if(line[i]===line[i-1])s++;else{if(s>=5)p+=3+(s-5);s=1}}
  if(s>=5)p+=3+(s-5)};
 const pat=line=>{const s=line.join("");let idx=-1;
  while((idx=s.indexOf("10111010000",idx+1))>=0)p+=40;
  idx=-1;
  while((idx=s.indexOf("00001011101",idx+1))>=0)p+=40};
 for(let r=0;r<n;r++){runs(m[r]);pat(m[r])}
 for(let c=0;c<n;c++){const col=[];for(let r=0;r<n;r++)col.push(m[r][c]);runs(col);pat(col)}
 for(let r=0;r<n-1;r++)for(let c=0;c<n-1;c++){const v=m[r][c];
  if(v===m[r][c+1]&&v===m[r+1][c]&&v===m[r+1][c+1])p+=3}
 let dark=0;for(let r=0;r<n;r++)for(let c=0;c<n;c++)dark+=m[r][c];
 return p+10*Math.floor(Math.abs(dark*100/(n*n)-50)/5)}
function qrEncode(text){
 const bytes=Array.from(new TextEncoder().encode(String(text||"")));
 let ver=0;
 for(let v=1;v<=5;v++)if(bytes.length+2<=QR_DCW[v]){ver=v;break}
 if(!ver)throw new Error("주소가 너무 깁니다");
 const bits=[],push=(val,n)=>{for(let i=n-1;i>=0;i--)bits.push((val>>i)&1)};
 push(4,4);push(bytes.length,8);for(const b of bytes)push(b,8);   // byte 모드
 const cap=QR_DCW[ver]*8;
 while(bits.length<cap&&bits.length%8!==0)bits.push(0);           // 종단자 + 바이트 정렬
 const dw=[];
 for(let i=0;i<bits.length;i+=8){let v=0;for(let j=0;j<8;j++)v=(v<<1)|bits[i+j];dw.push(v)}
 const pad=[0xEC,0x11];let pi=0;
 while(dw.length<QR_DCW[ver])dw.push(pad[pi++%2]);
 const all=dw.concat(qrRS(dw,QR_ECW[ver]));
 const size=17+4*ver,m=[],fn=[];
 for(let i=0;i<size;i++){m.push(new Array(size).fill(0));fn.push(new Array(size).fill(0))}
 const setF=(r,c,v)=>{if(r<0||c<0||r>=size||c>=size)return;m[r][c]=v;fn[r][c]=1};
 const finder=(r0,c0)=>{for(let r=-1;r<=7;r++)for(let c=-1;c<=7;c++){
  const inside=r>=0&&r<=6&&c>=0&&c<=6;let v=0;
  if(inside){const d=Math.max(Math.abs(r-3),Math.abs(c-3));v=d===2?0:1}
  setF(r0+r,c0+c,v)}};
 finder(0,0);finder(0,size-7);finder(size-7,0);
 for(let i=8;i<size-8;i++){setF(6,i,i%2===0?1:0);setF(i,6,i%2===0?1:0)}
 if(QR_ALIGN[ver]){const a=QR_ALIGN[ver];
  for(let r=-2;r<=2;r++)for(let c=-2;c<=2;c++){
   const d=Math.max(Math.abs(r),Math.abs(c));setF(a+r,a+c,d===1?0:1)}}
 setF(size-8,8,1);   // 다크 모듈
 for(let i=0;i<=8;i++){if(!fn[8][i])setF(8,i,0);if(!fn[i][8])setF(i,8,0)}
 for(let i=0;i<8;i++){if(!fn[8][size-1-i])setF(8,size-1-i,0);if(!fn[size-1-i][8])setF(size-1-i,8,0)}
 const dbits=[];for(const b of all)for(let i=7;i>=0;i--)dbits.push((b>>i)&1);
 let bi=0,up=true;
 for(let col=size-1;col>0;col-=2){
  if(col===6)col--;   // 세로 타이밍 열은 건너뛴다
  for(let k=0;k<size;k++){const row=up?size-1-k:k;
   for(let s=0;s<2;s++){const cc=col-s;
    if(fn[row][cc])continue;
    m[row][cc]=bi<dbits.length?dbits[bi]:0;bi++}}
  up=!up}
 let best=null,bestP=Infinity;
 for(let mk=0;mk<8;mk++){
  const t=m.map(r=>r.slice());
  for(let r=0;r<size;r++)for(let c=0;c<size;c++)if(!fn[r][c]&&QR_MASK[mk](r,c))t[r][c]^=1;
  const f=qrFormat(mk),gb=i=>(f>>i)&1;
  // 결함 5 · 포맷 정보 15비트를 ISO/IEC 18004 표준 위치에 배치한다(행렬 규약 m[행][열]).
  // 이전 코드는 행/열이 전치되어 있어 어떤 스캐너도 읽지 못했다.
  for(let i=0;i<=5;i++)t[i][8]=gb(i);          // 사본1 세로: 열 8, 행 0~5
  t[7][8]=gb(6);t[8][8]=gb(7);t[8][7]=gb(8);   // 사본1 모서리 3개
  for(let i=9;i<15;i++)t[8][14-i]=gb(i);       // 사본1 가로: 행 8, 열 5~0
  for(let i=0;i<8;i++)t[8][size-1-i]=gb(i);    // 사본2 가로: 행 8, 열 size-1~size-8
  for(let i=8;i<15;i++)t[size-15+i][8]=gb(i);  // 사본2 세로: 열 8, 행 size-7~size-1
  t[size-8][8]=1;                              // 다크 모듈 (행 4v+9, 열 8)
  const p=qrPenalty(t);
  if(p<bestP){bestP=p;best=t}}
 return best}

syncResume();renderLan();   // syncResume 이 재생 엔진을 mount 한다(설정·저장 위치를 읽어 온다)
initTab();                  // 주소·마지막 탭 복원 (스토리 탭이면 아래 loadChatHistory 와 합쳐진다)
refresh().then(loadChatHistory)   // 스토리 탭이 첫 화면이므로 지난 대화를 바로 채운다
 .catch(e=>{$("chipTitle").textContent="상태 불러오기 실패";$("chipTitle").className="chip bad"});
