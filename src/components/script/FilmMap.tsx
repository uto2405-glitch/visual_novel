/** 필름 맵 — 분기 구조를 한눈에 보는 조감독의 콘티 보드.
 *  노드 = 컷(상태 색), 실선 = next, 점선 = 선택지. 클릭하면 그 컷 카드로 스크롤. */
import { memo, useMemo, useState } from "react";
import { useStudio } from "../../store/useStudio";
import { useProject } from "../hooks";
import { chapterRanges } from "../../lib/chapters";
import type { CutRecord, Story } from "../../types";

const NODE_W = 74;
const NODE_H = 30;
const COL_GAP = 132;
const ROW_GAP = 44;
const PAD = 24;
/**
 * 한 띠에 담을 열 수 — 이보다 깊어지면 지도를 «줄바꿈»한다.
 *
 * 100컷 선형 대본은 열이 100개가 되어 지도가 12,042px(가로 10.3화면)이 됐다(실측).
 * 이야기의 형태를 한눈에 보려고 만든 지도가 열 화면을 긁어야 하면 지도가 아니다.
 * 글줄처럼 접으면 세로로 길어지지만, 세로 스크롤은 가로 스크롤보다 훨씬 자연스럽다.
 */
const WRAP_COLS = 8;

interface Node {
  id: string;
  /** 줄바꿈된 지도에서 이 노드가 속한 띠 (접지 않으면 0) */
  band: number;
  x: number;
  y: number;
  status: "ok" | "ng" | "wait";
  cutscene: boolean;
  reachable: boolean;
}

interface EdgeDef {
  from: string;
  to: string;
  kind: "next" | "choice";
  label?: string;
}

function buildMap(story: Story, cuts: Record<string, CutRecord>) {
  const ids = new Set(story.scenes.map((s) => s.id));
  // BFS 깊이 = 열
  const depth = new Map<string, number>();
  if (story.scenes.length > 0) {
    const queue: [string, number][] = [[story.scenes[0].id, 0]];
    while (queue.length > 0) {
      const [id, d] = queue.shift() as [string, number];
      if (depth.has(id)) continue;
      depth.set(id, d);
      const sc = story.scenes.find((s) => s.id === id);
      if (!sc) continue;
      if (sc.next && ids.has(sc.next)) queue.push([sc.next, d + 1]);
      for (const c of sc.choices ?? []) if (ids.has(c.next)) queue.push([c.next, d + 1]);
    }
  }
  const maxDepth = Math.max(0, ...depth.values());
  // 도달 불가 컷은 마지막 열 뒤에 모아둔다
  const unreachableCol = maxDepth + 1;
  const rowsPerCol = new Map<number, number>();
  const nodes: Node[] = [];
  const wrap = unreachableCol + 1 > WRAP_COLS; // 접을지 (짧은 대본은 지금 모습 그대로)
  // 띠마다 «그 띠에서 가장 많이 갈라진 열»의 행 수만큼 높이를 준다
  const bandRows = new Map<number, number>();
  for (const sc of story.scenes) {
    const reachable = depth.has(sc.id);
    const col = reachable ? (depth.get(sc.id) as number) : unreachableCol;
    const row = rowsPerCol.get(col) ?? 0;
    rowsPerCol.set(col, row + 1);
    const band = wrap ? Math.floor(col / WRAP_COLS) : 0;
    bandRows.set(band, Math.max(bandRows.get(band) ?? 1, row + 1));
    const cut = cuts[sc.id];
    nodes.push({
      id: sc.id,
      x: PAD + (wrap ? col % WRAP_COLS : col) * COL_GAP,
      y: PAD + row * ROW_GAP, // 띠 오프셋은 아래에서 더한다(띠 높이를 다 알아야 한다)
      band,
      status: cut?.status ?? "wait",
      cutscene: Boolean(cut?.cutscene || cut?.videoKey),
      reachable,
    });
  }
  // 띠 오프셋 — 앞 띠들의 높이 합
  const bandOffset = new Map<number, number>();
  let acc = 0;
  const bandCount = Math.max(...bandRows.keys()) + 1;
  for (let b = 0; b < bandCount; b++) {
    bandOffset.set(b, acc);
    acc += (bandRows.get(b) ?? 1) * ROW_GAP + (wrap ? ROW_GAP : 0);
  }
  for (const n of nodes) n.y += bandOffset.get(n.band) ?? 0;
  const edges: EdgeDef[] = [];
  for (const sc of story.scenes) {
    if (sc.next && ids.has(sc.next)) edges.push({ from: sc.id, to: sc.next, kind: "next" });
    for (const c of sc.choices ?? []) {
      if (ids.has(c.next)) edges.push({ from: sc.id, to: c.next, kind: "choice", label: c.label });
    }
  }
  const lastCol = nodes.some((n) => !n.reachable) ? unreachableCol : maxDepth;
  const shownCols = wrap ? Math.min(WRAP_COLS, lastCol + 1) : lastCol + 1;
  const width = PAD * 2 + (shownCols - 1) * COL_GAP + NODE_W + 40;
  const height = wrap
    ? PAD * 2 + acc
    : PAD * 2 + Math.max(1, ...rowsPerCol.values()) * ROW_GAP;
  return { nodes, edges, width, height };
}

const FILL: Record<Node["status"], string> = {
  ok: "rgba(105,180,120,0.18)",
  ng: "rgba(224,122,106,0.18)",
  wait: "rgba(154,143,124,0.10)",
};
const STROKE: Record<Node["status"], string> = {
  ok: "#86c793",
  ng: "#e07a6a",
  wait: "#8a8378",
};

export const FilmMap = memo(function FilmMap() {
  const project = useProject();
  const cursor = project.currentSceneId ?? null; // 시사 커서 — 지금 어디까지 봤나
  const [open, setOpen] = useState(false);
  // 연결 모드 — 출발 컷 → 도착 컷 순서로 탭해서 next를 잇는다 (폰에서 셀렉트보다 빠르다)
  const updateScene = useStudio((st) => st.updateScene);
  const toast = useStudio((st) => st.toast);
  const [linkMode, setLinkMode] = useState(false);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  // 접혀 있으면 계산하지 않는다 — 대사 타이핑마다 지도를 다시 그릴 이유가 없다
  const map = useMemo(
    () => (open ? buildMap(project.story, project.cuts) : null),
    [open, project.story, project.cuts],
  );
  const pos = useMemo(() => new Map((map?.nodes ?? []).map((n) => [n.id, n])), [map]);
  /**
   * 장의 첫 컷 — 100컷 지도에서 «어디서 3장이 시작하나»가 안 보였다.
   * 지도는 이야기 순서가 아니라 «갈래 깊이»로 열을 잡으므로, 선을 긋는 대신
   * 그 컷 위에 장 이름을 얹는다(갈림길이 있어도 어긋나지 않는다).
   */
  const chapterAt = useMemo(() => {
    const ranges = chapterRanges(project.story.scenes);
    return new Map(ranges.length >= 2 ? ranges.map((c) => [c.firstId, c.title] as const) : []);
  }, [project.story.scenes]);

  const jump = (id: string) => {
    document.getElementById(`cut-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const tapNode = (id: string) => {
    if (!linkMode) {
      jump(id);
      return;
    }
    if (!linkFrom) {
      setLinkFrom(id);
      return;
    }
    if (linkFrom === id) {
      setLinkFrom(null);
      return;
    }
    const from = project.story.scenes.find((sc) => sc.id === linkFrom);
    if (from?.choices?.length) {
      toast(`${linkFrom}에는 선택지가 있어요 — 갈래는 카드에서 편집해 주세요.`);
      setLinkFrom(null);
      return;
    }
    updateScene(linkFrom, { next: id });
    toast(`${linkFrom} → ${id} 연결했습니다. (↩ 되돌리기 가능)`, "ok");
    setLinkFrom(null);
  };

  return (
    <section className="panel filmmap">
      <div className="panel-head">
        <h2>
          필름 맵 <span className="fine">실선 = 다음 · 점선 = 선택지 · 클릭하면 카드로</span>
        </h2>
        {open && (
          <button
            className={`btn btn-ghost btn-small ${linkMode ? "btn-toggled" : ""}`}
            title="출발 컷 → 도착 컷 순서로 탭하면 next가 이어집니다 (선택지 컷은 카드에서)"
            onClick={() => {
              setLinkMode((v) => !v);
              setLinkFrom(null);
            }}
          >
            {linkMode ? "🔗 연결 중…" : "🔗 연결 모드"}
          </button>
        )}
        <button className="btn btn-ghost btn-small" onClick={() => setOpen((v) => !v)}>
          {open ? "접기" : "펼치기"}
        </button>
      </div>
      {open && linkMode && (
        <p className="fine">
          {linkFrom
            ? `출발: ${linkFrom} — 이제 도착 컷을 탭하세요 (같은 컷을 다시 탭하면 취소)`
            : "출발 컷을 탭하세요"}
        </p>
      )}
      {open && map && (
        <div className="filmmap-scroll">
          <svg width={map.width} height={map.height} role="img" aria-label="분기 구조 지도">
            {map.edges.map((e, i) => {
              const a = pos.get(e.from);
              const b = pos.get(e.to);
              if (!a || !b) return null;
              const x1 = a.x + NODE_W;
              const y1 = a.y + NODE_H / 2;
              const x2 = b.x;
              const y2 = b.y + NODE_H / 2;
              const back = x2 <= x1; // 되감기 연결은 위로 크게 돈다
              const midX = back ? Math.max(x1, x2 + NODE_W) + 30 : (x1 + x2) / 2;
              // 줄바꿈된 지도에서 «띠를 넘는» 연결은 지도를 가로질러 잡음이 된다.
              // 글줄이 다음 줄로 넘어가듯, 오른쪽으로 나가고 왼쪽에서 들어오는 토막으로 그린다.
              const wrapJump = (a.band ?? 0) !== (b.band ?? 0);
              const d = wrapJump
                ? `M ${x1} ${y1} L ${x1 + 18} ${y1} M ${x2 - 18} ${y2} L ${x2} ${y2}`
                : back
                  ? `M ${x1} ${y1} C ${x1 + 40} ${y1 - 34}, ${x2 - 40} ${y2 - 34}, ${x2} ${y2}`
                  : `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
              const label =
                e.kind === "choice" && e.label
                  ? e.label.length > 8
                    ? e.label.slice(0, 8) + "…"
                    : e.label
                  : null;
              return (
                <g key={i}>
                  <path
                    d={d}
                    fill="none"
                    stroke={e.kind === "choice" ? "#f0b45e" : "rgba(239,232,220,0.4)"}
                    strokeWidth={1.4}
                    strokeDasharray={
                      wrapJump ? "3 3" : e.kind === "choice" ? "5 4" : undefined
                    }
                    opacity={wrapJump ? 0.55 : 1}
                  >
                    {e.label && <title>{e.label}</title>}
                  </path>
                  {label && !wrapJump && (
                    <text
                      x={(x1 + x2) / 2}
                      y={(y1 + y2) / 2 + (back ? -40 : -5)}
                      textAnchor="middle"
                      fontSize={10}
                      fill="#f0b45e"
                      opacity={0.9}
                      pointerEvents="none"
                    >
                      {label}
                    </text>
                  )}
                </g>
              );
            })}
            {map.nodes.map((n) => (
              <g
                key={n.id}
                className="filmmap-node"
                onClick={() => tapNode(n.id)}
                style={{ cursor: "pointer" }}
              >
                {n.id === linkFrom && (
                  <rect
                    x={n.x - 5}
                    y={n.y - 5}
                    width={NODE_W + 10}
                    height={NODE_H + 10}
                    rx={10}
                    fill="none"
                    stroke="#7db9e8"
                    strokeWidth={2}
                    strokeDasharray="6 4"
                  />
                )}
                {n.id === cursor && (
                  <rect
                    x={n.x - 3}
                    y={n.y - 3}
                    width={NODE_W + 6}
                    height={NODE_H + 6}
                    rx={9}
                    fill="none"
                    stroke="#f0b45e"
                    strokeWidth={1.6}
                    opacity={0.85}
                  >
                    <title>시사 커서 — 마지막으로 본 컷</title>
                  </rect>
                )}
                {chapterAt.has(n.id) && (
                  <text
                    x={n.x + NODE_W / 2}
                    y={n.y - 6}
                    textAnchor="middle"
                    fontSize={11}
                    fill="#f0b45e"
                    pointerEvents="none"
                  >
                    {chapterAt.get(n.id)}
                  </text>
                )}
                <rect
                  x={n.x}
                  y={n.y}
                  width={NODE_W}
                  height={NODE_H}
                  rx={7}
                  fill={FILL[n.status]}
                  stroke={STROKE[n.status]}
                  strokeWidth={1.3}
                  strokeDasharray={n.reachable ? undefined : "4 4"}
                  opacity={n.reachable ? 1 : 0.55}
                />
                <text
                  x={n.x + NODE_W / 2}
                  y={n.y + NODE_H / 2 + 4}
                  textAnchor="middle"
                  fontSize={12}
                  fontFamily="Consolas, monospace"
                  fill="#efe8dc"
                >
                  {n.cutscene ? "🎬" : ""}
                  {n.id}
                </text>
                <title>
                  {n.id} · {n.status === "ok" ? "OK" : n.status === "ng" ? "NG" : "대기"}
                  {n.reachable ? "" : " · 도달 불가"}
                </title>
              </g>
            ))}
          </svg>
        </div>
      )}
    </section>
  );
});
