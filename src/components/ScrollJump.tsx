/**
 * 맨 위 / 맨 아래 — 긴 목록(대본실 240컷·촬영장)에서 엄지 한 번으로 끝과 끝을 오간다.
 * 문서가 한 화면 넘게 길 때만 나온다(짧은 방에서는 군더더기). 폰에서는 하단 탭 위, 토스트와 겹치지 않는 왼쪽.
 * 이동은 «한 번에»(smooth 아님): content-visibility:auto 카드는 그려지기 전엔 어림 높이여서 부드러운 스크롤은
 * 중간에 멎는다 — 즉시 이동한 뒤 두 프레임에 걸쳐 끝을 다시 맞춘다.
 */
import { useEffect, useState } from "react";
import { useStudio } from "../store/useStudio";

/** 문서가 화면보다 이만큼 더 길어야 버튼이 나온다 */
const MIN_EXTRA = 600;
/** 끝에 «닿았다»고 볼 여유(px) — 어림 높이의 오차를 덮는다 */
const EDGE = 8;

export function ScrollJump() {
  const [st, setSt] = useState({ show: false, atTop: true, atBottom: false });
  // 방이 바뀌면 문서 길이가 통째로 바뀐다 — 스크롤 이벤트 없이도 다시 재야 한다
  const tab = useStudio((s) => s.tab);

  useEffect(() => {
    let raf = 0;
    const measure = () => {
      raf = 0;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const y = window.scrollY;
      const next = { show: max > MIN_EXTRA, atTop: y <= EDGE, atBottom: y >= max - EDGE };
      setSt((cur) =>
        cur.show === next.show && cur.atTop === next.atTop && cur.atBottom === next.atBottom ? cur : next,
      );
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    /* 카드가 펼쳐지거나 목록이 자라 문서 길이가 변하면 — «본문(body)»의 크기를 본다.
       html 요소만 보면 안 된다: 실측에서 방을 옮긴 뒤 버튼이 다시 나타나지 않았다(html의 상자는
       내용이 자라도 그대로인 경우가 있어 ResizeObserver가 울리지 않는다). */
    const ro = new ResizeObserver(schedule);
    ro.observe(document.body);
    ro.observe(document.documentElement);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      ro.disconnect();
    };
  }, []);

  /* 방을 옮긴 직후 — 새 방이 그려진 뒤(두 프레임) 다시 잰다 */
  useEffect(() => {
    let a = 0;
    let b = 0;
    a = requestAnimationFrame(() => {
      b = requestAnimationFrame(() => {
        const max = document.documentElement.scrollHeight - window.innerHeight;
        const y = window.scrollY;
        setSt({ show: max > MIN_EXTRA, atTop: y <= EDGE, atBottom: y >= max - EDGE });
      });
    });
    return () => {
      cancelAnimationFrame(a);
      cancelAnimationFrame(b);
    };
  }, [tab]);

  if (!st.show) return null;

  const toTop = () => window.scrollTo({ top: 0, behavior: "auto" });
  const toBottom = () => {
    const go = () =>
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" });
    go();
    // 어림 높이였던 카드들이 실제 높이로 자리 잡은 뒤 한 번 더 — 진짜 끝에 닿게
    requestAnimationFrame(() => {
      go();
      requestAnimationFrame(go);
    });
  };

  return (
    <div className="scrolljump" role="group" aria-label="페이지 끝으로 이동">
      <button
        type="button"
        className="scrolljump-btn"
        onClick={toTop}
        disabled={st.atTop}
        aria-label="맨 위로"
        title="맨 위로 (키보드: Home)"
      >
        ▲
      </button>
      <button
        type="button"
        className="scrolljump-btn"
        onClick={toBottom}
        disabled={st.atBottom}
        aria-label="맨 아래로"
        title="맨 아래로 (키보드: End)"
      >
        ▼
      </button>
    </div>
  );
}
