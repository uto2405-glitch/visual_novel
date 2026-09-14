import { useEffect, useMemo, useRef, type RefObject } from "react";

/**
 * Blob → object URL. 렌더와 동기적으로 URL을 만들어, key가 바뀌며 마운트되는
 * <img>가 이전 컷의 URL을 한 프레임이라도 물지 않게 한다. 바뀌면 revoke.
 */
export function useObjectUrl(blob: Blob | null | undefined): string | null {
  const url = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob]);
  useEffect(() => {
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [url]);
  return url;
}

/**
 * 초점을 창 안에 가둔다 — 모달이 뜬 동안 뒤 화면은 «만질 수 없는 것»이어야 한다.
 *
 * 실측(2026-09-08): 확인창에서 탭을 두 번 누르면 초점이 뒤 화면으로 새어, 스무 번 중 열여덟 번이
 * 창 밖이었다. 보이지 않는 단추를 누르게 되고 무엇이 눌렸는지도 알 수 없다.
 * 그래서 (1) 열릴 때 초점을 창 안으로, (2) 마지막에서 Tab은 처음으로(Shift+Tab은 반대로) 감싸고,
 * (3) 닫힐 때는 열기 전 자리로 되돌려 준다(그 자리에서 이어서 일하도록).
 */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFocusTrap<T extends HTMLElement>(ref: RefObject<T | null>, active = true): void {
  useEffect(() => {
    if (!active) return;
    const box = ref.current;
    if (!box) return;
    const before = document.activeElement as HTMLElement | null;
    const list = () =>
      [...box.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
      });
    // 열릴 때 초점을 안으로 — 이미 안에 있으면 그대로 둔다(입력칸에 커서가 있는 채로 열릴 수 있다)
    if (!box.contains(document.activeElement)) {
      const first = list()[0];
      if (first) first.focus();
      else box.focus?.();
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const items = list();
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const cur = document.activeElement as HTMLElement | null;
      const at = cur ? items.indexOf(cur) : -1;
      if (!cur || !box.contains(cur)) {
        e.preventDefault();
        items[e.shiftKey ? items.length - 1 : 0].focus();
        return;
      }
      if (!e.shiftKey && at === items.length - 1) {
        e.preventDefault();
        items[0].focus();
      } else if (e.shiftKey && at === 0) {
        e.preventDefault();
        items[items.length - 1].focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      // 닫은 뒤 초점을 원래 자리로 — 없어진 요소라면 아무것도 하지 않는다
      if (before && document.body.contains(before)) before.focus();
    };
  }, [ref, active]);
}

/**
 * 창 닫기 Escape — 겹쳐 뜬 창들 중 «가장 위» 하나만 먹는다.
 *
 * 확인창이 인쇄본 위에 떠 있을 때 Escape 한 번에 둘 다 닫히면, 감독은 자기가 무엇을 취소했는지
 * 알 수 없다. 그래서 등록 순서를 스택으로 들고, 맨 위 창만 응답한다.
 * 한글 조합 중의 Escape는 «조합 취소»이므로 창을 닫지 않는다.
 */
const escStack: Array<() => void> = [];

export function useEscapeClose(active: boolean, onEscape: () => void): void {
  const ref = useRef(onEscape);
  useEffect(() => {
    ref.current = onEscape;
  });
  useEffect(() => {
    if (!active) return;
    const fn = () => ref.current();
    escStack.push(fn);
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.isComposing) return;
      if (escStack[escStack.length - 1] !== fn) return;
      e.stopPropagation();
      fn();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      const i = escStack.lastIndexOf(fn);
      if (i >= 0) escStack.splice(i, 1);
    };
  }, [active]);
}

/**
 * 무거운 일을 하기 «전에» 화면을 한 번 그리게 한다.
 *
 * 600컷 대본을 반영하면 화면이 1.5초 멈춘다(실측). 그 사이 아무 말이 없으면 감독은
 * 앱이 죽었다고 읽는다. 상태를 「반영 중」으로 바꾼 뒤 이것을 기다렸다가 일을 시작하면,
 * 멈추기 전에 그 글자가 화면에 찍힌다(프레임 두 번을 기다리는 이유: 첫 프레임은 아직
 * 그리기 전이다).
 */
export function nextPaint(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });
}
