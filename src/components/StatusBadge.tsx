/** 상태 배지 — OK / NG / 지연 / 대기 / 촬영 중. 완료·실패라는 말은 쓰지 않는다. */
import type { CutStatus } from "../types";

export function StatusBadge({
  status,
  shooting,
  delayed,
}: {
  status: CutStatus;
  shooting: boolean;
  delayed?: boolean;
}) {
  if (shooting) return <span className="badge badge-shoot">촬영 중…</span>;
  if (status === "ok") return <span className="badge badge-ok">OK</span>;
  if (status === "ng") return <span className="badge badge-ng">NG</span>;
  // 지연은 「거부(NG)」가 아니라 「아직 만드는 중일 수 있음」 — 별도 표시로 오해를 막는다.
  if (delayed) return <span className="badge badge-delayed">⏳ 지연</span>;
  return <span className="badge badge-wait">대기</span>;
}
