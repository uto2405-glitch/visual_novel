/** 전역 모달 — 설정(토큰), 확인창, 입력창, 토스트. App이 마운트한다.
 *  입력 초기값은 key 리마운트로 리셋한다 (effect 없이). */
import { useRef, useState } from "react";
import { useStudio } from "../store/useStudio";
import { useEscapeClose, useFocusTrap } from "../lib/hooks";
import { CAMERA_MODELS, checkCamera, type CameraCheck } from "../lib/makefun";

/* ---------------- 설정: 카메라(MakeFun) 토큰 ---------------- */

export function SettingsModal() {
  const open = useStudio((s) => s.settingsOpen);
  if (!open) return null;
  // 열릴 때마다 리마운트 → value가 현재 토큰으로 초기화된다
  return <SettingsModalInner />;
}

function SettingsModalInner() {
  const token = useStudio((s) => s.token);
  const setToken = useStudio((s) => s.setToken);
  const setOpen = useStudio((s) => s.setSettingsOpen);
  const toast = useStudio((s) => s.toast);
  useEscapeClose(true, () => setOpen(false));
  const [value, setValue] = useState(token);
  // 카메라 시운전 — 생성이 아니라 기록 조회(GET)만 하므로 크레딧이 들지 않는다
  const [check, setCheck] = useState<CameraCheck | null>(null);
  const [checking, setChecking] = useState(false);
  // 초점은 창 안에 머문다 — 뒤 화면은 만질 수 없는 것이어야 한다
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);

  const runCheck = async () => {
    setChecking(true);
    setCheck(null);
    const abort = new AbortController();
    try {
      const r = await checkCamera(
        value,
        CAMERA_MODELS.filter((m) => m.group === "image"),
        abort.signal,
      );
      setCheck(r);
    } catch (err) {
      setCheck({
        ok: false,
        step: "network",
        message: err instanceof Error ? err.message : "확인하지 못했습니다.",
      });
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => setOpen(false)}>
      <div className="modal" ref={box} onClick={(e) => e.stopPropagation()}>
        <h2 className="modal-title">카메라 설정</h2>
        <div className="modal-body">
          <label className="field">
            <span>MakeFun 토큰</span>
            <input
              type="password"
              value={value}
              placeholder="MakeFun API 토큰"
              onChange={(e) => setValue(e.target.value)}
              autoFocus
            />
          </label>
          <p className="fine">
            토큰은 이 브라우저의 localStorage(<code>makefun_token</code>)에만 둡니다. 프로젝트
            파일이나 필름캔(ZIP)에는 절대 들어가지 않습니다. 촬영 요청은 이 앱의 프록시를 거쳐
            서버에서 Authorization 헤더로만 전달됩니다.
          </p>
        </div>
        {check && (
          <p className={`notice ${check.ok ? "" : "notice-warn"}`}>
            {check.ok ? "✓ " : "⚠ "}
            {check.message}
          </p>
        )}
        <div className="modal-actions">
          <button
            className="btn"
            disabled={checking}
            title="촬영 전에 장비가 살아 있는지 봅니다 — 기록 조회만 하므로 크레딧이 들지 않습니다"
            onClick={() => void runCheck()}
          >
            {checking ? "확인 중…" : "🎬 카메라 시운전 (무료)"}
          </button>
          <button className="btn btn-ghost" onClick={() => setOpen(false)}>
            닫기
          </button>
          <button
            className="btn btn-primary"
            onClick={() => {
              setToken(value);
              setOpen(false);
              toast(value.trim() ? "카메라 토큰을 넣어두었습니다." : "카메라 토큰을 비웠습니다.");
            }}
          >
            저장
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- 확인창 ---------------- */

export function ConfirmModal() {
  const req = useStudio((s) => s.confirmReq);
  const answer = useStudio((s) => s.answerConfirm);
  // Escape는 언제나 «안 하는 쪽»으로 — 지우기 확인창에서 잘못 눌러도 잃는 것이 없어야 한다
  useEscapeClose(Boolean(req), () => answer(false));
  // 초점은 창 안에 머문다(훅은 이른 반환 «위»에 있어야 한다 — 렌더마다 같은 순서로 불려야 하므로)
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box, Boolean(req));
  if (!req) return null;
  return (
    <div className="modal-backdrop" onClick={() => answer(false)}>
      <div className="modal" ref={box} onClick={(e) => e.stopPropagation()}>
        <h2 className="modal-title">{req.title}</h2>
        {req.body && <div className="modal-body pre-line">{req.body}</div>}
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={() => answer(false)} autoFocus={req.danger}>
            {req.cancelLabel ?? "그만두기"}
          </button>
          <button
            className={`btn ${req.danger ? "btn-danger" : "btn-primary"}`}
            onClick={() => answer(true)}
            autoFocus={!req.danger}
          >
            {req.okLabel ?? "확인"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- 입력창 ---------------- */

export function PromptModal() {
  const req = useStudio((s) => s.promptReq);
  if (!req) return null;
  // 요청마다 key 리마운트 → value가 initial로 초기화된다
  return <PromptModalInner key={req.id} />;
}

function PromptModalInner() {
  const req = useStudio((s) => s.promptReq)!;
  const answer = useStudio((s) => s.answerPrompt);
  const [value, setValue] = useState(req.initial ?? "");
  useEscapeClose(true, () => answer(null));
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);

  const submit = () => answer(value);
  return (
    <div className="modal-backdrop" onClick={() => answer(null)}>
      <div
        className={`modal ${req.multiline ? "modal-wide" : ""}`}
        ref={box}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="modal-title">{req.title}</h2>
        <div className="modal-body">
          {req.body && <p className="pre-line">{req.body}</p>}
          {req.multiline ? (
            <textarea
              className="mono"
              rows={12}
              value={value}
              placeholder={req.placeholder}
              onChange={(e) => setValue(e.target.value)}
              autoFocus
            />
          ) : (
            <input
              value={value}
              placeholder={req.placeholder}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                // 한글 IME 조합 중의 Enter로 조기 제출되지 않게 한다
                if (e.key === "Enter" && !e.nativeEvent.isComposing) submit();
              }}
              autoFocus
            />
          )}
        </div>
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={() => answer(null)}>
            그만두기
          </button>
          <button className="btn btn-primary" onClick={submit}>
            {req.okLabel ?? "확인"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- 감독 수첩 (도움말) ---------------- */

export function HelpModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEscapeClose(open, onClose);
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box, open);
  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" ref={box} onClick={(e) => e.stopPropagation()}>
        <h2 className="modal-title">📖 감독 수첩</h2>
        <div className="modal-body help-body">
          <h3>오늘 밤의 흐름</h3>
          <ol className="help-list">
            <li>
              <b>조감독 리포트</b> — 촬영 전에 걸리는 것(끊어진 연결·도달 못 하는 컷·얼굴 없는
              배우·reuse 오류)을 읽기만 하고 아무것도 고치지 않습니다. 컷과 관련된 항목에는{" "}
              <b>「3장 · s37 보기」</b>가 붙어, 누르면 정리대가 그 장으로 맞춰지고 그 컷으로
              내려갑니다.
            </li>
            <li>
              <b>장별 진도</b> — 장이 둘 이상이면 대본실에 「장별 진도」 판이 생깁니다(기본은 접힘).
              장마다 찍은 컷/전체·NG를 막대로 보고, 장 이름을 누르면 정리대가 그 장만,{" "}
              <b>촬영장에서</b>를 누르면 촬영장이 그 장으로 맞춰집니다 — 20장 연재에서는
              콜시트 한 줄로 전체 판이 안 보이니까요. 장마다 <b>✎ 다시 쓰기</b>는 그 장만 담은
              프롬프트를 만들어 주고, 돌려받은 JSON을 <b>다시 쓴 대본 넣기</b>에 붙이면 같은 id의
              컷만 덮어씁니다 — 찍어둔 그림·판정·말풍선은 그대로예요(되돌리기로 취소됩니다).
            </li>
            <li>
              <b>오늘 밤의 콜시트</b> — 대본실 맨 위에 «이어갈 일»이 한 장으로 모입니다. 각 줄의
              버튼이 바로 그 자리로 데려갑니다. 걸리는 게 없으면 그렇다고 말해줍니다.
            </li>
            <li>
              <b>대본실</b> — 컷을 쓰고 배우를 캐스팅합니다. 사진을 올리면 새 배우를 바로 만들 수
              있고, 컷의 <b>등장 배우</b>를 켜야 그 얼굴이 레퍼런스로 전달됩니다. 마음에 드는
              연재라면 <b>▶ 다음 화 만들기</b>가 화풍·노트·배우를 그대로 물려받은 새 화를 한 번에
              열어줍니다. 배우는 <b>⭐ 배우단</b>에 올려두면 다른 작품에서도 사진째로 데려올 수 있어요(필름캔에도
              함께 담깁니다). 배우단 선반에서 <b>📷</b>로 얼굴만 더 좋은 사진으로 갈아끼우거나{" "}
              <b>✎</b>로 이름·메모를 고칠 수 있고, 지금 작품에 같은 배우가 있으면 사진이 함께
              맞춰집니다. 장이 여럿이면 캐스팅 카드에 <b>이 배우가 나온 장</b>이 한 줄로 붙고,
              그 장 이름을 누르면 정리대가 그 장만 보여줍니다. 대본이 막히면{" "}
              <b>✨ AI 이어쓰기 프롬프트</b>를 복사해 LLM에게 맡기세요 — 연재가 길어지면 대본 전체가 아니라
              <b>뒤 18컷만</b> 실립니다(20장이면 전체가 60KB라서요). 컷이 많아지면{" "}
              <b>🔍 정리대</b>(검색·상태·<b>장별</b> 필터, 카드·목록 모두 <b>장 머리글</b>로 갈립니다)와{" "}
              <b>☰ 목록 보기</b>(한 줄 요약, 탭하면 펼침),{" "}
              <b>필름 맵</b>(분기 지도 — 금색 링이 시사 커서, 🔗 연결 모드로 탭 두 번에 next
              잇기)을 쓰세요. 실수는{" "}
              <b>↩ 되돌리기</b>(Ctrl+Z, 30단계)가 받아줍니다 — 찍어둔 필름·판정은 건드리지
              않아요. 장이 여럿이면 정리대의 <b>장</b> 줄에서 장을 하나 고르고{" "}
              <b>▲ 장 앞으로 / ▼ 장 뒤로</b>로 <b>장을 통째로</b> 옮기세요 — 컷이 블록째 따라오고
              장 나누기 표시는 다시 매겨지니 장 수가 늘거나 줄지 않습니다. 너무 짧은 장은{" "}
              <b>⤺ 앞 장과 합치기</b>로 앞에 붙이고(컷은 그대로), 장 이름은 촬영장의{" "}
              <b>✎ 장 이름</b>에서 고칩니다(인쇄본의 장 제목 띠·목차도 함께 바뀝니다).
              장을 «만드는» 것도 여기서 됩니다 — 컷 카드의 <b>⏎ 새 장</b>을 켜면 그 컷부터 새 장이에요
              (첫 컷은 표시가 없어도 1장입니다). 셋 다 되돌리기 한 번으로 돌아옵니다. 「이 장은 이번 화에 안 들어가겠다」 싶으면{" "}
              <b>▶ 다음 화로</b> — 그 장이 새 화의 첫 장이 되고 화풍·노트·배우가 따라갑니다
              (아직 찍지 않은 장만 보냅니다 — 찍은 필름이 화를 넘어가면 어디 있는지 헷갈려서요). 액션은 한 컷으로 안 됩니다 — 컷 아래{" "}
              <b>🎞 연속 동작 3컷</b>을 누르면 같은 배경·같은 앵글(🔒 고정)로 맞춰진 두 컷이
              뒤에 붙으니 <b>자세</b>만 채우면 움직임으로 읽힙니다. 실측(3컷 촬영)에서 앵글·배경
              소품·옷·장갑에 <b>손에 든 우산까지</b> 그대로 유지됐어요 — 다만 소품은 컷마다{" "}
              <b>자세에 다시 적어야</b> 남습니다. 다만 자세가 «이동»을 담으면(문을 열고 들어가는
              식) 카메라가 따라가 앵글이 흔들립니다 — 이동은 컷을 나누세요. 2×2 그리드를 쓸 거면
              촬영을 <b>1:1 정사각</b>으로 두면 잘림이 아예 없습니다(실측, 크레딧은 1K와 같아요). <b>🎵 음악</b> 칩을 켠 컷부터 시사실에 밤의 음악이 흐릅니다.
            </li>
            <li>
              <b>촬영장</b> — 카메라를 고르고 「대기 컷 촬영」. reuse 컷은 크레딧을 쓰지 않아요.
              컷을 클릭하면 <b>페이스 체크 모니터</b>에서 캐스팅 사진과 나란히 보고 OK/NG 판정.
              이전 테이크를 누르면 <b>A/B 슬라이더</b>로 현재 그림과 겹쳐 비교하고, 마음이 바뀌면
              그 테이크로 복귀할 수 있어요. <b>▶ 여기부터 시사</b>로 그 컷부터 흐름을 바로
              확인합니다. 장이 여럿이면 <b>장 줄</b>에서 한 장만 골라 <b>이 장만 촬영</b>할 수 있고,
              그 옆에 <b>이 장의 크레딧 어림값</b>(지금 카메라 기준, reuse·내 파일은 0)이 나옵니다 —
              연재는 「이번 장에 얼마 드나」로 예산을 가늠하니까요. NG가 있으면{" "}
              <b>이 장 NG만 다시</b>로 그 장의 NG만 다시 찍습니다(대기 컷은 그대로).
              장 이름은 <b>✎ 장 이름</b>으로 고치고, 필름 맵에는 장 첫 컷 위에 장 이름이 얹힙니다.
            </li>
            <li>
              <b>컷씬</b> — 움직이면 좋을 컷에 「🎬 컷씬」을 켜고 「컷씬 영상화」. 시사실에서 그
              컷이 영상으로 흐릅니다.
            </li>
            <li>
              <b>시사실</b> — 이어진 OK 구간만 재생. 🔊 앰비언스·🎵 음악, 타자 속도·글자 크기
              취향도 기억합니다. 연재라면 <b>☰ 컷 목록</b>의 장 줄에서 장을 골라 그 장부터 보고,{" "}
              <b>⏹ 장 끝에서 멈춤</b>을 켜면 <b>그 장만</b> 보고 끝에서 멈춥니다 — 「여기까지입니다」에서
              이어서 볼지 고르면 돼요(엔딩 크레딧과는 다릅니다). 화마다 파일 하나로 주고 싶으면{" "}
              <b>📄 「장 이름」만</b>으로 그 장만 담은 시사본을 내보냅니다. 다 보면 <b>필름캔(ZIP)</b>으로 내 폴더에 백업 — ZIP이 곧
              원본이고, 기기를 옮길 때는 <b>최근 프로젝트 → 🎞 모두 내보내기</b>로 모든 작품을
              한 번에 꺼낼 수 있어요. 새 기기에서는 <b>내 기기에서 불러오기</b>에 그 ZIP들을{" "}
              <b>여러 개 한꺼번에</b> 골라 넣으면 됩니다(20편도 한 걸음 — 편마다 알림 대신 끝에 한 줄로
              알려줍니다). 같은 필름캔을 다시 넣으면 알아보고 <b>한 번만</b> 묻습니다
              (전부 교체 / 전부 사본으로). 내보낼 때 <b>시사본(HTML)</b>을 함께 담으면 ZIP 하나로 보관과 감상이 다
              됩니다 (토큰은 절대 담기지 않아요).
            </li>
            <li>
              <b>인쇄본</b> — 시사실의 <b>🖨 인쇄본 만들기</b>는 찍어둔 실사 컷을 만화처럼
              조판합니다. 말풍선·컷 제목은 앱이 직접 그리니 <b>크레딧이 들지 않고</b> 몇 번이든
              고칠 수 있어요. 세로 스트립(그림 안 잘림)과 2×2 그리드 중에 고르고, 2×2를 쓸
              거면 촬영 해상도를 <b>1:1 정사각</b>으로 두면 잘림이 없습니다. 표지는 <b>portrait
              샷 + 1:1</b>로 「카메라를 보는」 한 컷을 따로 찍으면 가장 좋아요. 야간 컷이 많으면{" "}
              <b>검은 여백</b>으로 두면 컷이 필름처럼 떠 보입니다. 말풍선 <b>꼬리</b>는 인물이
              있는 쪽으로 돌려주세요(자동으로 찾게 해봤지만 야간 사진에서 전광판을 인물로
              오판했습니다). 제목 자리는
              조판이 만드니 프롬프트에 여백은 요청하지 마세요. 맨 뒤에{" "}
              <b>👥 등장인물</b> 장을 붙이면 캐스팅 사진으로 인물 소개 페이지가 한 장 생깁니다
              (이름·외모 메모·몇 컷 등장). 사진에서 얼굴이 남을 쪽은 캐스팅 카드의{" "}
              <b>위·중·아래</b> 칩으로 고르세요. <b>🏷 컷 제목 채우기</b>로 한 장(또는 모든 장)의 제목을 한 번에 채우고(적어둔 제목은
              그대로 둡니다), 컷이 헝클어지면 <b>↺ 기본값</b>으로 그 컷 설정만 되돌립니다.
              장이 열리는 페이지에는 <b>📖 장 제목 띠</b>가 표제로 얹히고, 장이 다섯을 넘으면
              표지 다음에 <b>🗂 목차</b> 한 장이 붙습니다. 연재라면 <b>📖 「장 이름」만</b>으로
              지금 보고 있는 쪽이 속한 장만 뽑을 수 있어요 — 화마다 파일 하나로 올릴 때 씁니다
              (표지·목차·등장인물 장은 빠집니다).
              컷마다 <b>⏎ 새 장에서 시작</b>을 켜면 그 컷부터 장이
              넘어가요 — 절정 컷을 페이지 첫 칸에 두면 넘기는 손맛이 생깁니다. 다 됐으면{" "}
              <b>📜 긴 스크롤</b>(웹툰 업로드용 한 장)이나 <b>📄 PDF</b>(인쇄·메일 첨부)로도
              내보낼 수 있어요. 다시 찍을 컷이 보이면 <b>🎬 촬영장에서 열기</b>로 바로 갑니다 — 조판실
              안에는 촬영 버튼을 두지 않았습니다(이 방은 크레딧을 쓰지 않아요).
            </li>
          </ol>
          <h3>장(章)으로 하는 일 — 연재의 단위</h3>
          <p className="fine">
            장의 기준은 <b>하나</b>입니다 — 컷의 <b>⏎ 새 장에서 시작</b>. 대본실·촬영장·시사실·
            콜시트·인쇄본이 모두 이 기준을 쓰므로 「인쇄본의 3장」과 「촬영장의 3장」이 어긋나지
            않습니다. 장 이름은 그 장 <b>첫 컷의 컷 제목</b>이고, 이름을 안 붙이면 「N장」으로 셉니다.
          </p>
          <ul className="report-list fine">
            <li>
              <b>만들기·이름</b> — 컷 카드의 <b>⏎ 새 장</b>(첫 컷은 표시 없이도 1장), 촬영장의{" "}
              <b>✎ 장 이름</b>(인쇄본 띠·목차도 함께 바뀝니다)
            </li>
            <li>
              <b>순서·정리</b> — 정리대 장 줄의 <b>▲▼ 장 옮기기</b>(컷이 블록째 따라오고 표시는 다시
              매겨집니다) · <b>⤺ 앞 장과 합치기</b> · <b>▶ 다음 화로</b>(아직 안 찍은 장만)
            </li>
            <li>
              <b>찍기</b> — 촬영장에서 장을 고르면 <b>이 장만 촬영</b>, <b>이 장 NG만 다시</b>,
              그리고 <b>이 장의 크레딧 어림값</b>
            </li>
            <li>
              <b>보기</b> — 시사실 ☰ 목록의 <b>장부터</b>와 <b>⏹ 장 끝에서 멈춤</b>, 대본실의{" "}
              <b>장별 진도</b> 판(막대·찍은 수·NG), 필름 맵의 장 이름표
            </li>
            <li>
              <b>내보내기</b> — 인쇄본 <b>📖 「장」만</b>·<b>📜 긴 스크롤</b>·<b>📄 PDF</b>(모두 장 단위), 시사실{" "}
              <b>📄 「장」만</b> 시사본. 필름캔의 <b>읽어보기.txt</b>에도 장 목록이 적힙니다
            </li>
            <li>
              <b>다시 쓰기</b> — 진도판의 <b>✎ 다시 쓰기</b>로 그 장만 담은 프롬프트를 만들고, 받은
              JSON을 <b>다시 쓴 대본 넣기</b>에 넣으면 같은 id의 컷만 덮어씁니다(그림·판정은 그대로)
            </li>
            <li>
              <b>찾기</b> — 캐스팅의 <b>이 배우가 나온 장</b>, 배우단 선반의 <b>어느 작품 몇 장</b>,
              조감독 리포트의 <b>「3장 · s37 보기」</b>
            </li>
          </ul>
          <h3>손에 익는 조작</h3>
          <p className="fine">
            열린 창은 무엇이든 <b>Escape</b>로 닫힙니다 — 확인창의 Escape는 언제나 «안 하는 쪽»
            이라 잘못 눌러도 잃는 것이 없어요. 창이 겹쳐 있으면 맨 위 창만 닫힙니다.{" "}
            <b>Ctrl+Z</b>는 대본 되돌리기(30단계), 페이스 체크에서는 <b>←/→</b>로 컷을 넘깁니다.
          </p>
          <h3>비용 (실측, MakeFun 코인)</h3>
          <p className="fine">
            Wan 2.7 한 컷 ≈ 8 · Seedream 5 Pro ≈ 12~25 · 컷씬 영상 ≈ 30 · reuse/플레이스홀더/내
            파일 등록 = 0. <b>실패해도 시작 시점에 과금</b>되므로 같은 사유로 연속 NG면 배치가
            스스로 멈추고, 놓친 결과는 「결과 찾아오기」로 무과금 회수합니다.
          </p>
          <h3>촬영이 안 될 때</h3>
          <p className="fine">
            ⚙ <b>카메라 설정 → 🎬 카메라 시운전</b>을 누르면 <b>크레딧 0</b>으로 장비를 점검합니다
            — 토큰이 만료됐는지, 인터넷이 끊겼는지 어디까지 갔는지 알려줍니다. 생성이 오래 걸려
            <b>⏳ 지연</b>으로 표시된 컷은 NG가 아니라 아직 만드는 중일 수 있으니, 「결과 찾아오기」로
            무과금 회수하세요.
          </p>
          <h3>얼굴이 자꾸 거부되면</h3>
          <p className="fine">
            Seedream은 실존 인물 사진을 저작권·초상권으로 거부할 수 있어요 → 카메라를 Wan 2.7로
            바꿔 「NG만 다시」. 그래도 안 되면 본인 사진이나 AI 생성 얼굴로 캐스팅하세요.
          </p>
        </div>
        <div className="modal-actions">
          <button className="btn btn-primary" onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- 토스트 ---------------- */

export function ToastHost() {
  const toasts = useStudio((s) => s.toasts);
  const dismiss = useStudio((s) => s.dismissToast);
  if (toasts.length === 0) return null;
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`} onClick={() => dismiss(t.id)}>
          {t.text}
        </div>
      ))}
    </div>
  );
}
