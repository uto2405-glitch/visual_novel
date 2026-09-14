/**
 * 인쇄본(웹툰) 조판 — 찍어둔 컷을 만화 페이지로 옮긴다.
 *
 * 원칙:
 *  - 말풍선은 절대 AI에게 맡기지 않는다. 생성 모델은 한글을 흉내만 낸다(실측: 간판이
 *    「NOPII SED」로 나온다). 그림은 그대로 두고 그 위에 Canvas로 얹는다 → 무과금·무한 재편집.
 *  - 조판은 세로 스트립이 기본. 16:9 컷을 자르지 않아도 되고 스크롤 웹툰의 표준 형식이다.
 *  - 2×2 그리드는 1:1로 잘라야 하므로 컷마다 남길 쪽(left/center/right)을 고를 수 있다.
 *  - 내레이션은 꼬리 없는 캡션 박스, 인물 대사는 꼬리 달린 말풍선 — 만화 문법을 따른다.
 */
import type { BalloonKind, BalloonPos, BalloonTail, Scene, Story, WebtoonFx } from "../types";

export type Layout = "strip" | "grid";

export interface WebtoonPanel {
  scene: Scene;
  /** 이 컷의 그림 (OK 컷만 들어온다) */
  bitmap: ImageBitmap;
  /** 컷 번호 (1부터) — 제목 라벨에 쓴다 */
  index: number;
  /** 화자 표시 이름 ("narration"이면 내레이션으로 조판) */
  speaker: string;
  isNarration: boolean;
}

export interface WebtoonOptions {
  layout: Layout;
  /** 페이지 한 장에 담을 컷 수 (strip 기본 4, grid는 항상 4) */
  perPage: number;
  /** 컷 사이 간격 */
  gutter: number;
  /** 페이지 바깥 여백 */
  margin: number;
  /** 컷 제목 라벨을 그릴지 */
  showCaptions: boolean;
  /** 페이지 하단에 작품 제목을 넣을지 */
  footer: boolean;
  /** 첫 장에 표지(제목 + 표지 컷)를 넣을지 */
  cover: boolean;
  /** 표지에 쓸 컷 (panels 기준 인덱스). 기본은 첫 컷 */
  coverIndex?: number;
  /** 말풍선·캡션 글자 배율 (0.85 = 작게, 1 = 보통, 1.2 = 크게) */
  textScale: number;
  /** 맨 뒤에 「등장인물」 소개 장을 붙일지 (단행본 관례) */
  castPage: boolean;
  /** 종이 색 — 컷 사이 여백과 페이지 바탕. 야간 실사는 검은 여백이 어울린다 */
  paper: "white" | "black";
  /** 컷 제목 앞에 번호를 붙일지 — 만화는 번호를 안 붙이는 편이 흔하다 */
  captionNumbers: boolean;
  /** 장이 다섯을 넘는 합본이면 표지 다음에 장 목차 한 장을 붙일지 */
  contents: boolean;
  /**
   * 장이 시작되는 페이지 맨 위에 «장 제목 띠»를 얹을지.
   * 연재 합본에서는 장이 바뀌어도 컷만 이어져 구분이 약하다 — 단행본은 장마다 표제를 둔다.
   */
  chapterBand: boolean;
  /**
   * 합본(여러 화를 한 권으로)에서 쪽 번호를 이어 붙이기 위한 값들.
   * 화마다 따로 조판하면 발치의 번호가 매 화 1부터 다시 시작한다 — 한 권이 아니라 다섯 권이 된다.
   * pageOffset은 «이 화 앞에 이미 몇 쪽이 있었나», pageGrandTotal은 «책 전체가 몇 쪽인가».
   */
  pageOffset?: number;
  pageGrandTotal?: number;
}

/** 등장인물 장에 실을 배우 한 명 — 캐스팅 사진을 그대로 쓴다 */
export interface CastCard {
  name: string;
  look?: string;
  bitmap: ImageBitmap;
  /** 이 배우가 등장하는 OK 컷 수 — 단행본 인물 소개의 「출연」 칸 */
  cuts?: number;
  /** 정사각으로 자를 때 남길 쪽 (감독이 고른다. 기본은 가로 가운데·세로 위 35%) */
  crop?: { x?: "left" | "center" | "right"; y?: "top" | "center" | "bottom" };
  /** 전속 배우단 출연 편수 — 여러 작품에 나온 배우라면 그것도 이력이다 */
  films?: number;
  /**
   * 이 배우가 나온 «다른» 작품 이름들(이 책은 뺀 것).
   * 「3편 출연」은 어느 편인지 못 알려 준다 — 이름이 있으면 이름을 적고, 칸에 안 들어가면 숫자로 물러난다.
   */
  filmTitles?: string[];
}

const DEFAULT_OPTIONS: WebtoonOptions = {
  layout: "strip",
  perPage: 4,
  gutter: 10,
  margin: 14,
  showCaptions: true,
  footer: true,
  cover: true,
  textScale: 1,
  castPage: false,
  paper: "white",
  captionNumbers: true,
  chapterBand: true,
  contents: true,
};

const FONT_STACK =
  '"Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif';
const INK = "#111";
const PAPER = "#fff"; // 말풍선·캡션 바탕 — 종이색과 무관하게 항상 흰색(글자가 읽혀야 한다)
/** 페이지 바탕·컷 사이 여백 색 */
const pageColor = (opts: { paper: "white" | "black" }) => (opts.paper === "black" ? "#0d0b09" : "#fff");
/** 어두운 종이에서는 컷 테두리·바닥글도 밝아야 보인다 */
const inkOn = (opts: { paper: "white" | "black" }) => (opts.paper === "black" ? "#efe8dc" : INK);

/** 폰트가 준비되기 전에 그리면 글자가 폴백으로 나온다 — 한 번 기다린다. */
async function waitForFonts(): Promise<void> {
  try {
    await document.fonts?.ready;
  } catch {
    /* 폰트 API가 없어도 그리기는 계속 */
  }
}

/* ---------- 텍스트 ---------- */

/** 한글은 단어 경계가 드물다 — 공백 우선으로 나누고, 한 덩어리가 길면 글자 단위로 쪼갠다. */
function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = [];
  for (const paragraph of text.split("\n")) {
    let line = "";
    const chunks = paragraph.split(/(\s+)/); // 공백을 유지해 자연스러운 줄바꿈
    for (const chunk of chunks) {
      if (!chunk) continue;
      const trial = line + chunk;
      if (ctx.measureText(trial).width <= maxWidth || !line) {
        // 한 덩어리 자체가 최대폭을 넘으면 글자 단위로 흘린다
        if (ctx.measureText(trial).width > maxWidth && !line.trim()) {
          let acc = "";
          for (const ch of trial) {
            if (ctx.measureText(acc + ch).width > maxWidth && acc) {
              lines.push(acc);
              acc = ch;
            } else {
              acc += ch;
            }
          }
          line = acc;
          continue;
        }
        line = trial;
      } else {
        lines.push(line.trimEnd());
        line = chunk.trimStart();
      }
    }
    lines.push(line.trimEnd());
  }
  return lines.filter((l, _i, arr) => l !== "" || arr.length === 1);
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

/* ---------- 말풍선 ---------- */

interface BalloonBox {
  x: number;
  y: number;
  w: number;
  h: number;
  lines: string[];
  lineH: number;
  padX: number;
  padY: number;
  /** 컷에 맞추려고 줄인 뒤의 실제 글자 크기 — 그리는 쪽이 이 값을 써야 한다 */
  fontSize: number;
}

/** 말풍선 상자 크기·자리를 먼저 계산한다 (꼬리는 상자 위치가 정해진 뒤에 그린다). */
function layoutBalloon(
  ctx: CanvasRenderingContext2D,
  text: string,
  panel: { x: number; y: number; w: number; h: number },
  pos: BalloonPos,
  fontSize: number,
  /** 컷 제목 라벨이 차지한 높이 — 위쪽 말풍선은 이 아래에서 시작한다 */
  safeTop = 0,
): BalloonBox {
  // 긴 대사는 말풍선을 컷보다 크게 만든다 — 그림을 뚫는 것보다는 넓게 펼치고, 그래도 안 되면
  // 글자를 줄이고, 마지막에는 잘라서 «…»를 붙인다. 조판이 무너지는 것만은 막는다.
  const maxH = Math.max(panel.h * 0.62 - safeTop, fontSize * 4);
  let size = fontSize;
  let spread = 0.46; // 컷 폭 대비 글줄 폭
  let padX = 0;
  let padY = 0;
  let lineH = 0;
  let lines: string[] = [];
  for (let attempt = 0; attempt < 6; attempt++) {
    ctx.font = `600 ${size}px ${FONT_STACK}`;
    padX = Math.round(size * 0.85);
    padY = Math.round(size * 0.7);
    lines = wrapText(ctx, text, Math.min(panel.w * spread, spread <= 0.46 ? 520 : 900));
    lineH = Math.round(size * 1.45);
    if (lines.length * lineH + padY * 2 <= maxH) break;
    if (spread < 0.78) spread = Math.min(0.78, spread + 0.16);
    else size = Math.max(Math.round(fontSize * 0.66), Math.round(size * 0.86));
  }
  const maxLines = Math.max(1, Math.floor((maxH - padY * 2) / lineH));
  if (lines.length > maxLines) {
    lines = lines.slice(0, maxLines);
    const last = lines[maxLines - 1].trimEnd();
    lines[maxLines - 1] = `${last.slice(0, Math.max(1, last.length - 1))}…`;
  }
  const textW = Math.max(...lines.map((l) => ctx.measureText(l).width), 1);
  const w = Math.ceil(textW + padX * 2);
  const h = Math.ceil(lines.length * lineH + padY * 2);
  const inset = Math.round(panel.w * 0.025);
  const x = pos === "tl" || pos === "bl" ? panel.x + inset : panel.x + panel.w - inset - w;
  const top = pos === "tl" || pos === "tr";
  const y = top ? panel.y + inset + safeTop : panel.y + panel.h - inset - h;
  return { x, y, w, h, lines, lineH, padX, padY, fontSize: size };
}

/** 꼬리는 화면 중앙(인물이 있을 확률이 높은 쪽)을 향한다. */
function drawTail(
  ctx: CanvasRenderingContext2D,
  box: BalloonBox,
  panel: { x: number; y: number; w: number; h: number },
  pos: BalloonPos,
  kind: BalloonKind,
  /** 꼬리가 가리킬 곳 (인물 추정 위치). 없으면 컷 한가운데 */
  anchorX?: number,
) {
  const towardRight = pos === "tl" || pos === "bl";
  const towardDown = pos === "tl" || pos === "tr";
  const baseX = towardRight ? box.x + box.w * 0.62 : box.x + box.w * 0.38;
  const baseY = towardDown ? box.y + box.h : box.y;
  const cx = anchorX ?? panel.x + panel.w / 2;
  let len = Math.min(panel.h * 0.12, 68);
  if (kind === "shout") len *= 0.55; // 외침은 꼬리가 짧아야 날카롭다

  if (kind === "think") {
    // 생각 — 점점 작아지는 원 세 개
    const steps = [0.45, 0.75, 1.0];
    const sizes = [9, 6.5, 4.5];
    for (let i = 0; i < steps.length; i++) {
      const t = steps[i];
      // 인물은 보통 컷 가운데 있다 — 점이 그쪽으로 확실히 흘러가게 한다
      const px = baseX + (cx - baseX) * 0.34 * (i + 1);
      const py = baseY + (towardDown ? len * t : -len * t);
      ctx.beginPath();
      ctx.arc(px, py, sizes[i], 0, Math.PI * 2);
      ctx.fillStyle = PAPER;
      ctx.fill();
      ctx.stroke();
    }
    return;
  }

  // 대사·외침 — 삼각 꼬리 (외침은 더 날카롭게)
  // 멀리 가리킬수록 밑동도 넓혀야 «쐐기»가 된다. 폭을 고정하면 300px짜리 바늘이 되어
  // 말풍선 꼬리가 아니라 지시선처럼 보인다(실측: 2×2에서 꼬리를 왼쪽으로 돌렸을 때).
  const dxRaw = (cx - baseX) * 0.62;
  const reachCap = panel.w * 0.3;
  const dx = Math.max(-reachCap, Math.min(reachCap, dxRaw));
  const spread = Math.max(
    9,
    Math.min(30, (kind === "shout" ? 9 : 15) + Math.abs(dx) * 0.055),
  );
  const tipX = baseX + dx;
  const tipY = baseY + (towardDown ? len : -len);
  ctx.beginPath();
  ctx.moveTo(baseX - spread, baseY);
  ctx.lineTo(baseX + spread, baseY);
  ctx.lineTo(tipX, tipY);
  ctx.closePath();
  ctx.fillStyle = PAPER;
  ctx.fill();
  // 꼬리 바깥선만 덧그려 상자 경계선이 지워지지 않게 한다
  ctx.beginPath();
  ctx.moveTo(baseX - spread, baseY);
  ctx.lineTo(tipX, tipY);
  ctx.lineTo(baseX + spread, baseY);
  ctx.stroke();
}

/** 외침 말풍선 — 뾰족한 폭발형 테두리 */
function shoutPath(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  spikes = 18,
) {
  const cx = x + w / 2;
  const cy = y + h / 2;
  ctx.beginPath();
  for (let i = 0; i < spikes * 2; i++) {
    const t = (i / (spikes * 2)) * Math.PI * 2;
    const out = i % 2 === 0 ? 1 : 0.87;
    const px = cx + Math.cos(t) * (w / 2) * out;
    const py = cy + Math.sin(t) * (h / 2) * out;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.closePath();
}

/**
 * 꼬리가 가리킬 곳 — 감독이 고른다.
 *
 * 그려진 컷에서 «세로 엣지가 가장 몰린 띠»를 인물로 보는 자동 추정을 만들어 실사 3컷에 재봤더니,
 * 세 컷 모두 인물(x≈0.30)이 아니라 역 전광판(x≈0.77)을 골랐다 — 오차 0.47. 야간 실사에서
 * 네온·전광판·선로가 인물보다 윤곽이 강해서다. 틀린 방향을 자동으로 가리키는 것은 가운데를
 * 가리키는 것보다 나쁘므로 추정은 버리고, 4귀퉁이(pos)를 고르듯 꼬리 방향도 고르게 했다.
 */
function tailAnchorX(
  panel: { x: number; w: number },
  tail: BalloonTail | undefined,
): number {
  const at = tail === "l" ? 0.18 : tail === "r" ? 0.82 : 0.5;
  return panel.x + panel.w * at;
}

function drawBalloon(
  ctx: CanvasRenderingContext2D,
  text: string,
  panel: { x: number; y: number; w: number; h: number },
  pos: BalloonPos,
  kind: BalloonKind,
  fontSize: number,
  safeTop = 0,
  anchorX?: number,
  /** 화면 밖 화자·독백처럼 꼬리가 없어야 할 때 */
  noTail = false,
) {
  // 외침은 폭발 테두리가 상자 밖으로 나가므로 그만큼 더 안쪽에서 시작한다
  const extra = kind === "shout" ? Math.round(fontSize * 0.6) : 0;
  const box = layoutBalloon(ctx, text, panel, pos, fontSize, safeTop + extra);
  const fs = box.fontSize; // 컷에 맞추려고 줄었을 수 있다
  ctx.save();
  ctx.strokeStyle = INK;
  ctx.lineWidth = Math.max(2, Math.round(fs * 0.09));
  ctx.fillStyle = PAPER;
  ctx.lineJoin = "round";

  // 꼬리를 먼저 그려 상자가 꼬리 밑동을 덮게 한다 (경계선이 깔끔해진다)
  if (!noTail) drawTail(ctx, box, panel, pos, kind, anchorX);

  if (kind === "shout") {
    const pad = Math.round(fs * 0.5);
    shoutPath(ctx, box.x - pad, box.y - pad, box.w + pad * 2, box.h + pad * 2);
    ctx.fill();
    ctx.stroke();
  } else {
    roundRect(ctx, box.x, box.y, box.w, box.h, Math.round(fs * 1.1));
    ctx.fill();
    ctx.stroke();
  }

  ctx.fillStyle = INK;
  ctx.font = `600 ${fs}px ${FONT_STACK}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const startY = box.y + box.padY + box.lineH / 2;
  box.lines.forEach((line, i) => {
    ctx.fillText(line, box.x + box.w / 2, startY + i * box.lineH);
  });
  ctx.restore();
}

/** 내레이션 — 꼬리 없는 사각 캡션. 컷 상단(또는 하단)에 가로로 눕는다. */
function drawNarration(
  ctx: CanvasRenderingContext2D,
  text: string,
  panel: { x: number; y: number; w: number; h: number },
  atBottom: boolean,
  fontSize: number,
  safeTop = 0,
) {
  ctx.save();
  ctx.font = `500 ${fontSize}px ${FONT_STACK}`;
  const padX = Math.round(fontSize * 0.8);
  const padY = Math.round(fontSize * 0.55);
  const inset = Math.round(panel.w * 0.025);
  // 컷 폭을 다 먹으면 그림이 가려진다 — 78%로 묶는다
  const maxW = panel.w * 0.78 - padX * 2;
  let lines = wrapText(ctx, text, maxW);
  const lineH = Math.round(fontSize * 1.4);
  // 내레이션이 컷 절반을 덮으면 그림이 사라진다 — 넘치면 잘라서 «…»
  const capLines = Math.max(1, Math.floor((panel.h * 0.5 - padY * 2 - safeTop) / lineH));
  if (lines.length > capLines) {
    lines = lines.slice(0, capLines);
    const last = lines[capLines - 1].trimEnd();
    lines[capLines - 1] = `${last.slice(0, Math.max(1, last.length - 1))}…`;
  }
  const w = Math.min(
    panel.w - inset * 2,
    Math.ceil(Math.max(...lines.map((l) => ctx.measureText(l).width), 1) + padX * 2),
  );
  const h = lines.length * lineH + padY * 2;
  const x = panel.x + inset;
  const y = atBottom ? panel.y + panel.h - inset - h : panel.y + inset + safeTop;

  ctx.fillStyle = "rgba(255,255,255,0.94)";
  ctx.strokeStyle = INK;
  ctx.lineWidth = Math.max(2, Math.round(fontSize * 0.08));
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = INK;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  lines.forEach((line, i) => {
    ctx.fillText(line, x + padX, y + padY + lineH / 2 + i * lineH);
  });
  ctx.restore();
}

/** 컷 제목 라벨의 크기 — 그리기 전에 자리를 알아야 말풍선이 라벨을 피할 수 있다. */
function captionMetrics(
  ctx: CanvasRenderingContext2D,
  label: string,
  panel: { w: number },
  fontSize: number,
) {
  ctx.font = `700 ${fontSize}px ${FONT_STACK}`;
  const padX = Math.round(fontSize * 0.7);
  const padY = Math.round(fontSize * 0.45);
  const inset = Math.round(panel.w * 0.018);
  const w = Math.ceil(ctx.measureText(label).width + padX * 2);
  const h = Math.ceil(fontSize * 1.35 + padY);
  return { w, h, padX, inset };
}

/** 컷 제목 라벨 — 좌상단 흰 판. 컷 선에 붙지 않게 살짝 들여쓴다. */
function drawCaption(
  ctx: CanvasRenderingContext2D,
  label: string,
  panel: { x: number; y: number; w: number; h: number },
  fontSize: number,
) {
  const m = captionMetrics(ctx, label, panel, fontSize);
  ctx.save();
  ctx.font = `700 ${fontSize}px ${FONT_STACK}`;
  const padX = m.padX;
  const w = m.w;
  const h = m.h;
  const x = panel.x + m.inset;
  const y = panel.y + m.inset;
  ctx.fillStyle = PAPER;
  ctx.strokeStyle = INK;
  ctx.lineWidth = Math.max(2, Math.round(fontSize * 0.09));
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = INK;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(label, x + padX, y + h / 2);
  ctx.restore();
}

/* ---------- 만화 효과선 ---------- */

type Rect = { x: number; y: number; w: number; h: number };

/**
 * 속도선 — 좌우 가장자리에서 안쪽으로 뻗는 평행선. 가운데(피사체)는 비워 둔다.
 * 어두운 실사 위에서는 흰 선이 가장 잘 읽힌다.
 */
function drawSpeedLines(ctx: CanvasRenderingContext2D, r: Rect) {
  ctx.save();
  ctx.beginPath();
  ctx.rect(r.x, r.y, r.w, r.h);
  ctx.clip();
  const n = 22;
  // 실측(실사 야간 사진, 2026-09-06): 안쪽으로 0.38까지 뻗으면 좌우 선이 가운데서 이어져
  // «인물 얼굴을 가로지르는 격자»가 된다. 만화의 유선은 프레임 가장자리에서 흘러들어오고
  // 인물이 서는 가운데는 비워 둔다 — 그래서 뻗는 길이를 줄이고 가장자리를 진하게 한다.
  const reach = r.w * 0.26;
  // 밝은 배경에서도 어두운 배경에서도 읽히게 검은 밑선 위에 흰 선을 겹친다
  const pass = [
    { col: "0,0,0", a: 0.55, w: 6.0, off: 1.8 },
    { col: "255,255,255", a: 0.95, w: 3.4, off: 0 },
  ];
  for (let i = 0; i < n; i++) {
    const noise = Math.sin(i * 12.9898) * 0.5 + 0.5;
    // 줄 간격을 살짝 흔든다 — 정확히 등간격이면 효과선이 아니라 «표 괘선»으로 보인다
    const t = (i + 0.5) / n + (noise - 0.5) * 0.018;
    const y = r.y + Math.min(1, Math.max(0, t)) * r.h;
    const jitter = noise * 0.55 + 0.45; // 길이를 불규칙하게
    const len = reach * jitter;
    for (const p2 of pass) {
      const a = p2.a * (0.5 + 0.5 * jitter);
      ctx.lineWidth = p2.w * (0.5 + 0.5 * jitter);
      for (const side of [-1, 1]) {
        const x0 = side < 0 ? r.x : r.x + r.w;
        const x1 = side < 0 ? r.x + len : r.x + r.w - len;
        const g = ctx.createLinearGradient(x0, y, x1, y);
        g.addColorStop(0, `rgba(${p2.col},${a})`);
        g.addColorStop(0.5, `rgba(${p2.col},${a * 0.4})`);
        g.addColorStop(1, `rgba(${p2.col},0)`);
        ctx.strokeStyle = g;
        ctx.beginPath();
        ctx.moveTo(x0, y + p2.off);
        ctx.lineTo(x1, y + p2.off);
        ctx.stroke();
      }
    }
  }
  ctx.restore();
}

/** 집중선 — 가장자리에서 중심으로 모이는 방사선. 중심 근처는 비워 인물을 살린다. */
/**
 * 방사 쐐기 — 집중선·섬광이 공유하는 형태.
 *
 * 실측(실사 야간 사진, 2026-09-06):
 *  - 얇은 «선»으로 그린 집중선은 복잡한 사진 위에서 거의 보이지 않았다(단색 픽스처에서는
 *    잘 보였다 — 그래서 못 잡았다). 만화의 집중선은 가장자리에서 두껍고 중심으로 뾰족해지는
 *    «쐐기»를 채운 것이다. 채우면 사진 위에서도 읽힌다.
 *  - 섬광은 중심을 채워 얼굴을 완전히 덮었다. 중심에서 시작하지 않고 내곽 반경 밖에서
 *    시작해야 인물이 살아남는다.
 * 그래서 두 효과 모두 «가장자리에서 흘러들고 가운데는 비운다» 한 가지 규칙으로 그린다.
 */
function drawRadialWedges(
  ctx: CanvasRenderingContext2D,
  r: Rect,
  opt: {
    /** 쐐기 개수 */
    n: number;
    /** 가운데 빈 구멍 (짧은 변 대비) */
    holeRatio: number;
    /** 가장자리에서의 각 폭 비율 (0~1, 1이면 틈이 없다) */
    fill: number;
    /** 채움색 rgb */
    rgb: string;
    /** 가장자리 불투명도 */
    alpha: number;
    /** 중심 y 위치 (0.5 = 가운데) */
    cyRatio?: number;
    /** 쐐기 위에 얇게 겹칠 대비색 (없으면 생략) */
    edgeRgb?: string;
  },
) {
  ctx.save();
  ctx.beginPath();
  ctx.rect(r.x, r.y, r.w, r.h);
  ctx.clip();
  const cx = r.x + r.w / 2;
  const cy = r.y + r.h * (opt.cyRatio ?? 0.5);
  // hypot(w,h)*0.5 가 정확히 컷 모서리다. 이보다 크게 잡으면 그라디언트의 «진한 끝»이
  // 컷 밖에서 잘려 안쪽엔 투명한 앞부분만 남는다 — 그러면 채움은 사라지고 윤곽선만 보인다.
  // (속도선에서 한 번 겪고도 쐐기로 바꾸며 같은 실수를 반복했다. 실측 2026-09-06)
  const outer = Math.hypot(r.w, r.h) * 0.52;
  const hole = Math.min(r.w, r.h) * opt.holeRatio;
  const step = (Math.PI * 2) / opt.n;
  for (let i = 0; i < opt.n; i++) {
    const a = i * step;
    const jitter = Math.sin(i * 7.13) * 0.5 + 0.5; // 길이·굵기를 불규칙하게
    const half = step * 0.5 * opt.fill * (0.7 + 0.6 * jitter);
    const inner = hole * (0.9 + 0.5 * jitter);
    const tip = inner;
    const g = ctx.createRadialGradient(cx, cy, tip, cx, cy, outer);
    g.addColorStop(0, `rgba(${opt.rgb},0)`);
    g.addColorStop(0.3, `rgba(${opt.rgb},${opt.alpha * 0.4})`);
    // 컷 모서리(≈0.96)에 닿기 전에 최대 진하기에 이르러야 «가장자리가 진한» 집중선이 된다
    g.addColorStop(0.75, `rgba(${opt.rgb},${opt.alpha})`);
    g.addColorStop(1, `rgba(${opt.rgb},${opt.alpha})`);
    ctx.fillStyle = g;
    ctx.beginPath();
    // 뾰족한 끝 하나 + 가장자리 호 = 쐐기
    ctx.moveTo(cx + Math.cos(a) * tip, cy + Math.sin(a) * tip);
    ctx.lineTo(cx + Math.cos(a - half) * outer, cy + Math.sin(a - half) * outer);
    ctx.arc(cx, cy, outer, a - half, a + half);
    ctx.closePath();
    ctx.fill();
    if (opt.edgeRgb) {
      // 반대색 실선 한 겹 — 어떤 배경에서도 경계가 남는다
      ctx.strokeStyle = `rgba(${opt.edgeRgb},${opt.alpha * 0.5})`;
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }
  }
  ctx.restore();
}

/** 집중선 — 어두운 쐐기가 가장자리에서 모인다. 놀람·강조의 한 컷에. */
function drawFocusLines(ctx: CanvasRenderingContext2D, r: Rect) {
  drawRadialWedges(ctx, r, {
    n: 44,
    holeRatio: 0.3,
    fill: 0.52,
    rgb: "10,8,6",
    alpha: 0.82,
    edgeRgb: "255,255,255",
  });
}

/** 충격 섬광 — 밝은 쐐기. 중심은 비워 얼굴을 살린다. 타격·각성의 한 컷에. */
function drawFlash(ctx: CanvasRenderingContext2D, r: Rect) {
  drawRadialWedges(ctx, r, {
    n: 26,
    holeRatio: 0.34,
    fill: 0.46,
    rgb: "255,255,255",
    alpha: 0.72,
    cyRatio: 0.45,
    edgeRgb: "20,16,12",
  });
}

function drawFx(ctx: CanvasRenderingContext2D, r: Rect, fx: WebtoonFx | undefined) {
  if (fx === "speed") drawSpeedLines(ctx, r);
  else if (fx === "focus") drawFocusLines(ctx, r);
  else if (fx === "flash") drawFlash(ctx, r);
}

/* ---------- 조판 ---------- */

function cropSource(bmp: ImageBitmap, target: number, crop: "left" | "center" | "right") {
  // target = 원하는 가로/세로 비율. 1:1이면 1.
  const srcRatio = bmp.width / bmp.height;
  if (Math.abs(srcRatio - target) < 0.001) {
    return { sx: 0, sy: 0, sw: bmp.width, sh: bmp.height };
  }
  if (srcRatio > target) {
    // 원본이 더 넓다 — 좌우를 자른다
    const sw = Math.round(bmp.height * target);
    const rest = bmp.width - sw;
    const sx = crop === "left" ? 0 : crop === "right" ? rest : Math.round(rest / 2);
    return { sx, sy: 0, sw, sh: bmp.height };
  }
  // 원본이 더 좁다 — 위아래를 자른다 (인물 얼굴이 위쪽에 있으니 위를 살린다)
  const sh = Math.round(bmp.width / target);
  const sy = Math.round((bmp.height - sh) * 0.25);
  return { sx: 0, sy, sw: bmp.width, sh };
}

function panelText(p: WebtoonPanel): string {
  const w = p.scene.webtoon;
  const line = (w?.line ?? "").trim();
  return line || (p.scene.text ?? "").trim();
}

/**
 * 페이지 나누기 — 페이지당 컷 수를 넘거나, 컷이 「새 장에서 시작」으로 표시돼 있으면 장을 넘긴다.
 * 미리보기(조판실)와 내보내기가 반드시 같은 함수를 써야 «보이는 대로 나온다»가 지켜진다.
 */
export function chunkByPage<T>(
  items: T[],
  per: number,
  breakBefore: (item: T) => boolean,
): T[][] {
  const out: T[][] = [];
  let cur: T[] = [];
  for (const it of items) {
    if (cur.length > 0 && (cur.length >= per || breakBefore(it))) {
      out.push(cur);
      cur = [];
    }
    cur.push(it);
  }
  if (cur.length > 0) out.push(cur);
  return out;
}

/** 페이지 크기·칸 배치 계산 — 본문과 표지가 같은 크기로 나오도록 한 곳에서 잰다. */
function pageMetrics(panels: WebtoonPanel[], opts: WebtoonOptions) {
  const isGrid = opts.layout === "grid";
  const cols = isGrid ? 2 : 1;
  // 장을 넘겨 한두 컷만 남은 페이지에서 빈 칸을 남기지 않는다
  const rows = isGrid ? Math.max(1, Math.ceil(Math.max(1, panels.length) / 2)) : panels.length;
  // 그리드는 1:1로 자른다. 스트립은 컷마다 원본 비율을 지킨다 —
  // 스크롤 웹툰은 컷 높이가 저마다 달라도 자연스럽고, 그래야 정사각 컷도 잘리지 않는다.
  const cellW = isGrid ? 640 : 1180;
  const cellH = isGrid ? 640 : 0; // 스트립은 컷별로 계산
  const stripHeights = isGrid
    ? []
    : panels.map((p) =>
        Math.round(cellW / Math.max(0.4, Math.min(3, p.bitmap.width / p.bitmap.height))),
      );
  const footerH = opts.footer ? 46 : 0;
  const width = opts.margin * 2 + cols * cellW + (cols - 1) * opts.gutter;
  // 장 제목 띠 — 이 페이지가 «장의 첫 페이지»일 때만 (첫 컷에 장 나누기 + 제목이 있을 때)
  const first = panels[0];
  const chapterTitle =
    opts.chapterBand && first?.scene.webtoon?.pageBreak
      ? (first.scene.webtoon?.caption ?? "").trim()
      : "";
  const chapterH = chapterTitle ? Math.round(cellW * 0.085) : 0;
  const bodyH = isGrid
    ? rows * cellH + (rows - 1) * opts.gutter
    : stripHeights.reduce((a, b) => a + b, 0) + (panels.length - 1) * opts.gutter;
  const height = opts.margin * 2 + chapterH + bodyH + footerH;
  return {
    isGrid,
    cols,
    rows,
    cellW,
    cellH,
    stripHeights,
    footerH,
    width,
    height,
    chapterTitle,
    chapterH,
  };
}

/** 페이지 한 장을 그린다. 반환: PNG Blob */
async function renderPage(
  panels: WebtoonPanel[],
  opts: WebtoonOptions,
  title: string,
  pageNo: number,
  pageTotal: number,
): Promise<Blob> {
  const m = pageMetrics(panels, opts);
  const { isGrid, cellW, cellH, stripHeights, footerH, width, height, chapterTitle, chapterH } = m;

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("이 브라우저에서 Canvas를 쓸 수 없습니다.");

  ctx.fillStyle = pageColor(opts);
  ctx.fillRect(0, 0, width, height);
  ctx.imageSmoothingQuality = "high";

  // 장 제목 띠 — 장이 시작되는 페이지 맨 위에. 컷은 그만큼 아래에서 시작한다.
  if (chapterTitle) {
    const size = Math.round(chapterH * 0.52);
    ctx.font = `800 ${size}px ${FONT_STACK}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillStyle = inkOn(opts);
    ctx.fillText(chapterTitle, opts.margin, opts.margin + chapterH * 0.42);
    // 얇은 밑줄로 «여기서 장이 열린다»를 못박는다
    ctx.fillRect(opts.margin, opts.margin + chapterH - 10, width - opts.margin * 2, 3);
  }

  let stripY = opts.margin + chapterH;
  panels.forEach((p, i) => {
    const col = isGrid ? i % 2 : 0;
    const x = opts.margin + col * (cellW + opts.gutter);
    const h = isGrid ? cellH : stripHeights[i];
    const y = isGrid
      ? opts.margin + chapterH + Math.floor(i / 2) * (cellH + opts.gutter)
      : stripY;
    if (!isGrid) stripY += h + opts.gutter;
    const panel = { x, y, w: cellW, h };

    const { sx, sy, sw, sh } = cropSource(
      p.bitmap,
      cellW / h,
      p.scene.webtoon?.crop ?? "center",
    );
    ctx.drawImage(p.bitmap, sx, sy, sw, sh, x, y, cellW, h);

    // 효과선은 그림 위, 말풍선 아래 — 동세는 그림에 얹고 글자는 가리지 않는다
    drawFx(ctx, panel, p.scene.webtoon?.fx);

    // 컷 테두리 — 만화의 칸 선
    ctx.strokeStyle = inkOn(opts);
    ctx.lineWidth = 3;
    ctx.strokeRect(x + 1.5, y + 1.5, cellW - 3, h - 3);

    // 글자 크기는 컷의 짧은 변을 따른다 — 컷 높이가 저마다 달라도 글자는 고르게 보인다
    // 컷마다 배율을 따로 줄 수 있다 — 긴 대사 한 컷 때문에 페이지 전체를 줄이지 않게
    const cutScale = p.scene.webtoon?.textScale ?? 1;
    const base = Math.round(Math.min(h, cellW * 0.62) * 0.045 * opts.textScale * cutScale);
    const captionSize = Math.max(13, Math.round(base * 0.82));
    const balloonSize = Math.max(14, base);

    // 라벨을 먼저 재둔다 — 말풍선이 라벨을 덮지 않으려면 라벨 높이를 알아야 한다
    const cap = (p.scene.webtoon?.caption ?? "").trim();
    // 장 띠에 이미 이 제목이 크게 있으면 컷 라벨은 겹치는 말이 된다
    const shownInBand = i === 0 && Boolean(chapterTitle) && cap === chapterTitle;
    const hasCap = opts.showCaptions && Boolean(cap) && !shownInBand;
    // 감독이 「1 · 플랫폼」처럼 스스로 번호를 붙였으면 앱이 또 붙이지 않는다(「1. 1 · 플랫폼」 방지).
    // 번호 자체를 원하지 않는 취향도 있다 — 만화는 번호 없는 라벨이 흔하다.
    const label = !opts.captionNumbers || /^\d/.test(cap) ? cap : `${p.index}. ${cap}`;
    const capM = hasCap ? captionMetrics(ctx, label, panel, captionSize) : null;
    const safeTop = capM ? capM.h + capM.inset + Math.round(captionSize * 0.35) : 0;

    if (hasCap) drawCaption(ctx, label, panel, captionSize);

    const text = panelText(p);
    if (text) {
      // 내레이션 기본은 아래(위는 컷 제목 라벨의 자리다), 인물 대사는 오른쪽 위
      const pos = p.scene.webtoon?.pos ?? (p.isNarration ? "bl" : "tr");
      if (p.isNarration) {
        // 내레이션은 가로로 눕는 캡션 — 좌우는 뜻이 없고 위/아래만 쓴다
        drawNarration(ctx, text, panel, pos === "bl" || pos === "br", balloonSize, safeTop);
      } else {
        const tail = p.scene.webtoon?.tail;
        drawBalloon(
          ctx,
          text,
          panel,
          pos,
          p.scene.webtoon?.kind ?? "say",
          balloonSize,
          safeTop,
          tail === "none" ? undefined : tailAnchorX(panel, tail),
          tail === "none",
        );
      }
    }
  });

  if (opts.footer) {
    ctx.fillStyle = opts.paper === "black" ? "#8d8578" : "#6b6459";
    ctx.font = `500 20px ${FONT_STACK}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(title, opts.margin, height - footerH / 2 - 2);
    ctx.textAlign = "right";
    ctx.fillText(`${pageNo} / ${pageTotal}`, width - opts.margin, height - footerH / 2 - 2);
  }

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("페이지를 그리지 못했습니다."))),
      "image/png",
    );
  });
}

/**
 * 말풍선 자리 추천 — 그림에서 「가장 비어 있는」 귀퉁이를 찾는다.
 *
 * 실사 사진에서 인물·간판은 디테일이 촘촘하고(픽셀 분산이 크다), 하늘·벽·바닥·젖은 노면은
 * 평평하다(분산이 작다). 그래서 분산이 가장 낮은 귀퉁이에 말풍선을 놓으면 얼굴을 덜 가린다.
 * 컷 제목 라벨이 있으면 좌상단은 이미 라벨이 쓰고 있으니 벌점을 준다.
 */
export function suggestBalloonPos(
  bitmap: ImageBitmap,
  hasCaption = false,
  /**
   * 감독이 고른 꼬리 방향 — 인물이 어느 쪽에 있는지에 대한 «사람의 판단»이다.
   * 그림 분석으로 인물을 찾는 시도는 실패했으므로(전광판을 인물로 골랐다), 감독이 이미
   * 알려준 이 정보를 쓴다: 인물이 왼쪽이면 말풍선은 오른쪽으로 간다.
   */
  tail?: BalloonTail,
): BalloonPos {
  const W = 64;
  const H = 40;
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return "tr";
  ctx.drawImage(bitmap, 0, 0, W, H);
  const { data } = ctx.getImageData(0, 0, W, H);
  const lum = (i: number) => 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];

  // 귀퉁이마다 가로 45% × 세로 42% 크기의 창을 본다 (말풍선이 차지할 만한 넓이)
  // (아래 점수 계산에서 꼬리 방향과 같은 쪽 귀퉁이에는 벌점을 준다 — 인물 위를 덮지 않게)
  const winW = Math.round(W * 0.45);
  const winH = Math.round(H * 0.42);
  const boxes: { pos: BalloonPos; x0: number; y0: number }[] = [
    { pos: "tl", x0: 0, y0: 0 },
    { pos: "tr", x0: W - winW, y0: 0 },
    { pos: "bl", x0: 0, y0: H - winH },
    { pos: "br", x0: W - winW, y0: H - winH },
  ];

  let best: BalloonPos = "tr";
  let bestScore = Infinity;
  for (const b of boxes) {
    let sum = 0;
    let sumSq = 0;
    let n = 0;
    // 이웃 픽셀과의 차이(엣지)도 함께 본다 — 평평함을 더 정확히 잡는다
    let edge = 0;
    for (let y = b.y0; y < b.y0 + winH; y++) {
      for (let x = b.x0; x < b.x0 + winW; x++) {
        const i = (y * W + x) * 4;
        const l = lum(i);
        sum += l;
        sumSq += l * l;
        n += 1;
        if (x + 1 < b.x0 + winW) edge += Math.abs(l - lum(i + 4));
      }
    }
    const variance = sumSq / n - (sum / n) ** 2;
    let score = Math.sqrt(Math.max(0, variance)) + (edge / n) * 1.5;
    if (hasCaption && b.pos === "tl") score += 40; // 라벨 자리는 양보한다
    // 꼬리가 왼쪽을 가리키면 인물이 왼쪽에 있다는 뜻 — 그쪽 귀퉁이는 피한다
    const onLeft = b.pos === "tl" || b.pos === "bl";
    if (tail === "l" && onLeft) score += 55;
    if (tail === "r" && !onLeft) score += 55;
    if (score < bestScore) {
      bestScore = score;
      best = b.pos;
    }
  }
  return best;
}

export interface WebtoonResult {
  pages: Blob[];
  /** 조판된 컷 수 */
  panelCount: number;
  /**
   * 장이 열리는 쪽 — 「몇 쪽부터 3장인가」. 쪽 번호는 «본문 기준 1부터»다
   * (목차·파일명이 그 기준을 쓴다 — 표지는 00번).
   */
  chapters: { title: string; page: number; cuts: number }[];
  /**
   * pages 배열 앞머리에 붙은 «본문이 아닌» 쪽 수 (표지·목차).
   * 인덱스 시트처럼 pages 인덱스로 세는 쪽에서는 chapters의 page에 이만큼 더해야 칸이 맞는다.
   */
  lead: number;
}

/**
 * OK 컷들을 인쇄본으로 조판한다. 이미지 생성은 전혀 하지 않는다 (무과금).
 * panels 순서가 곧 읽는 순서 — 호출자가 시사 경로대로 넣어준다.
 */
/**
 * 표지 제목 띠의 높이 — 제목을 실제로 재서 정한다.
 *
 * 폭의 30%로 고정해 뒀더니 16:9 실사 표지에서 검은 띠가 페이지의 34%를 먹었다(실측). 제목이
 * 한 줄이면 좁게, 여러 줄로 접히면 그만큼 넓게 — 띠가 글자를 따라가야 표지가 책처럼 보인다.
 */
function coverTitleLayout(title: string, innerW: number, hasByline = false) {
  const titleSize = Math.round(innerW * 0.085);
  const lineH = Math.round(titleSize * 1.25);
  const subSize = Math.max(15, Math.round(titleSize * 0.34));
  let lines = 1;
  const c = document.createElement("canvas");
  const ctx = c.getContext("2d");
  if (ctx) {
    ctx.font = `800 ${titleSize}px ${FONT_STACK}`;
    lines = Math.max(1, wrapText(ctx, title, innerW * 0.82).length);
  }
  // 위 여백 + 제목 + 부제 + 아래 여백
  const bandH = Math.round(
    titleSize * 0.7 + lines * lineH + subSize * 2.1 + titleSize * 0.5 + (hasByline ? subSize * 1.8 : 0),
  );
  return { titleSize, lineH, subSize, lines, bandH };
}

/**
 * 표지 — 제목 한 장. 표지 컷을 어둡게 깔고 그 위에 제목을 얹는다.
 * 페이지 크기는 본문 첫 장과 같게 맞춰 묶음이 흐트러지지 않게 한다.
 */
async function renderCover(
  story: Story,
  cover: WebtoonPanel,
  opts: WebtoonOptions,
  width: number,
  height: number,
  panelCount: number,
): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("이 브라우저에서 Canvas를 쓸 수 없습니다.");

  ctx.fillStyle = "#0d0b09";
  ctx.fillRect(0, 0, width, height);

  const inner = { x: opts.margin, y: opts.margin, w: width - opts.margin * 2, h: height - opts.margin * 2 };
  // 표지 컷은 «전체가 보이게» 담는다 (잘라 채우면 인물 팔·얼굴이 프레임 밖으로 나간다).
  // 남는 위아래는 밤 색으로 두고, 제목은 그림 아래 띠에 앉힌다.
  const imgRatio = cover.bitmap.width / cover.bitmap.height;
  const drawW = inner.w;
  // 비율 그대로 — 여기서 높이를 «inner.h의 72%»로 깎으면 정사각 표지가 6% 눌려 그려졌다(실측).
  // 페이지 높이는 이미 이 그림 높이 + 제목 띠로 계산돼 있으므로 깎을 이유가 없다.
  const drawH = Math.round(drawW / imgRatio);
  const drawX = inner.x;
  const drawY = inner.y;
  ctx.drawImage(cover.bitmap, drawX, drawY, drawW, drawH);

  // 그림 아래쪽만 살짝 어둡게 — 제목 띠로 자연스럽게 이어지도록
  const g = ctx.createLinearGradient(0, drawY + drawH * 0.55, 0, drawY + drawH);
  g.addColorStop(0, "rgba(8,6,4,0)");
  g.addColorStop(1, "rgba(8,6,4,0.75)");
  ctx.fillStyle = g;
  ctx.fillRect(drawX, drawY + drawH * 0.55, drawW, drawH * 0.45);

  ctx.strokeStyle = INK;
  ctx.lineWidth = 3;
  ctx.strokeRect(inner.x + 1.5, inner.y + 1.5, inner.w - 3, inner.h - 3);

  // 제목 — 컷 폭에 맞춰 줄바꿈
  const tl = coverTitleLayout(story.title, inner.w, Boolean((story.coverByline ?? "").trim()));
  const titleSize = tl.titleSize;
  ctx.font = `800 ${titleSize}px ${FONT_STACK}`;
  const lines = wrapText(ctx, story.title, inner.w * 0.82);
  const lineH = tl.lineH;
  const blockH = lines.length * lineH;
  const bandTop = drawY + drawH;
  const bandH = inner.y + inner.h - bandTop;
  // 제목 + 부제를 한 덩어리로 보고 띠 가운데에 세운다 — 예전엔 42%에 두어 아래가 더 비었다
  const groupH = blockH + tl.subSize * 2.1;
  const baseY = bandTop + (bandH - groupH) / 2;

  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const cx = inner.x + inner.w / 2;
  // 표지 제목의 «표정» — 폰트 파일을 번들에 넣지 않고 만든다(exe가 무거워지지 않는다).
  //  ① 아래로 살짝 번지는 그림자: 밤 사진 위에서 글자가 떠 보인다
  //  ② 두꺼운 검은 외곽선 + 금색 채움: 어떤 배경에서도 읽힌다(기존)
  //  ③ 위쪽 절반만 밝은 세로 그라디언트: 금속 활자 같은 입체감
  lines.forEach((line, i) => {
    const y = baseY + lineH / 2 + i * lineH;
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.55)";
    ctx.shadowBlur = Math.max(6, titleSize * 0.18);
    ctx.shadowOffsetY = Math.max(2, titleSize * 0.05);
    ctx.strokeStyle = "rgba(8,6,4,0.9)";
    ctx.lineWidth = Math.max(4, titleSize * 0.13);
    ctx.lineJoin = "round";
    ctx.strokeText(line, cx, y);
    ctx.restore();
    const g = ctx.createLinearGradient(0, y - lineH * 0.5, 0, y + lineH * 0.5);
    g.addColorStop(0, "#fff3d6");
    g.addColorStop(0.52, "#f7dfae");
    g.addColorStop(1, "#d9ab63");
    ctx.fillStyle = g;
    ctx.fillText(line, cx, y);
  });

  // 부제 — 몇 컷짜리인지
  const subSize = tl.subSize;
  ctx.font = `500 ${subSize}px ${FONT_STACK}`;
  // 감독이 부제를 적었으면 그것을, 없으면 몇 컷짜리인지
  const sub = (story.coverSubtitle ?? "").trim() || `${panelCount}컷`;
  const subY = baseY + blockH + subSize * 1.25;
  ctx.strokeStyle = "rgba(8,6,4,0.85)";
  ctx.lineWidth = Math.max(3, subSize * 0.16);
  ctx.strokeText(sub, cx, subY);
  ctx.fillStyle = "rgba(239,232,220,0.9)";
  ctx.fillText(sub, cx, subY);

  // 판권면 한 줄 — 지은이·발행일. 감독이 적었을 때만, 띠 맨 아래에 조용히.
  const by = (story.coverByline ?? "").trim();
  if (by) {
    const bySize = Math.max(12, Math.round(subSize * 0.72));
    ctx.font = `400 ${bySize}px ${FONT_STACK}`;
    ctx.strokeStyle = "rgba(8,6,4,0.8)";
    ctx.lineWidth = Math.max(2, bySize * 0.16);
    const byY = inner.y + inner.h - bySize * 1.4;
    ctx.strokeText(by, cx, byY);
    ctx.fillStyle = "rgba(200,192,180,0.85)";
    ctx.fillText(by, cx, byY);
  }

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("표지를 그리지 못했습니다."))),
      "image/png",
    );
  });
}

/**
 * 인물 카드의 「출연」 한 줄.
 *
 * 「3편 출연」은 사실이지만 어느 편인지 못 알려 준다 — 연재가 길어지면 그게 궁금해진다.
 * 그래서 다른 작품 이름을 적는다. 다만 이 칸은 좁고(2열에서 300px대) 제목은 길 수 있으므로
 * 재 보고 넣는다: 안 들어가면 제목 수를 줄이고, 그래도 안 되면 예전처럼 숫자로 물러난다.
 * 카드 밖으로 넘친 글자는 아래 카드 이름 위에 겹쳐 찍힌다(실측) — 넘치는 쪽이 더 나쁘다.
 */
function castCreditLine(
  ctx: CanvasRenderingContext2D,
  c: { cuts?: number; films?: number; filmTitles?: string[] },
  maxWidth: number,
): string {
  const base = `${c.cuts}컷 등장`;
  const fits = (t: string) => ctx.measureText(t).width <= maxWidth;
  const titles = (c.filmTitles ?? []).filter((t) => t.trim());
  /**
   * 후퇴를 «단계»로 둔다 — 한 번에 이름에서 컷 수로 떨어지면 이력이 통째로 사라진다.
   * 2열(배우 6명 이상)에서 글자칸은 388px인데 「「밤의 편지」 외 1편에도」가 423px이었다:
   * 제목을 4자로 잘라도 「…」이 그만큼을 먹어 못 들어갔고, 결국 「2컷 등장」만 찍혔다(실측).
   * 이름이 못 들어가면 편수라도 남긴다 — 「다른 2편에도」는 이름보다 덜하지만 없는 것보단 낫다.
   */
  const ladder: string[] = [];
  if (titles.length > 0) {
    const rest = titles.length - 1;
    const tail = rest > 0 ? ` 외 ${rest}편` : "";
    ladder.push(`${base} · 「${titles[0]}」${tail}에도`);
    ladder.push(`${base} · 「${titles[0]}」${tail}`);
    for (let cut = titles[0].length - 1; cut >= 3; cut--) {
      ladder.push(`${base} · 「${titles[0].slice(0, cut)}…」${tail}`);
    }
    ladder.push(`${base} · 다른 ${titles.length}편에도`);
    ladder.push(`${base} · 다른 ${titles.length}편`);
  }
  if (c.films && c.films > 1) ladder.push(`${base} · ${c.films}편 출연`);
  for (const line of ladder) if (fits(line)) return line;
  return base;
}

/**
 * 등장인물 장 — 단행본 맨 뒤에 붙는 인물 소개.
 *
 * 이미 캐스팅 사진이 있는데 인쇄본에는 얼굴이 컷 안에서만 스쳐 간다. 한 장 붙여두면
 * 「이 사람이 누구였지」가 사라진다. 사진은 정사각으로 잘라 나란히 세운다.
 */
async function renderCastPage(
  story: Story,
  cast: CastCard[],
  opts: WebtoonOptions,
  width: number,
  pageNo: number,
  pageTotal: number,
): Promise<Blob> {
  const innerW = width - opts.margin * 2;
  const titleSize = Math.round(Math.max(22, innerW * 0.055));
  const titleH = Math.round(titleSize * 2.1);
  const gap = Math.max(8, opts.gutter);
  const footerH = opts.footer ? 46 : 0;
  // 배우가 여섯을 넘으면 한 줄에 하나씩 세울 때 페이지가 세로로 끝없이 길어진다 —
  // 단행본의 인물 소개도 그쯤부터 두 칸으로 나눈다.
  const cols = cast.length > 5 ? 2 : 1;
  const colW = Math.round((innerW - (cols - 1) * gap) / cols);
  const cardH = Math.round(Math.max(88, colW * (cols === 1 ? 0.2 : 0.32)));
  const rows = Math.ceil(cast.length / cols);
  const height =
    opts.margin * 2 + titleH + rows * cardH + Math.max(0, rows - 1) * gap + footerH;

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("이 브라우저에서 Canvas를 쓸 수 없습니다.");
  ctx.fillStyle = pageColor(opts);
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = inkOn(opts);
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.font = `800 ${titleSize}px ${FONT_STACK}`;
  ctx.fillText("등장인물", opts.margin, opts.margin + titleH / 2);
  ctx.fillRect(opts.margin, opts.margin + titleH - 6, innerW, 3);

  for (let i = 0; i < cast.length; i++) {
    const c = cast[i];
    const col = i % cols;
    const cardX = opts.margin + col * (colW + gap);
    const y = opts.margin + titleH + Math.floor(i / cols) * (cardH + gap);
    const photo = cardH;
    // 정사각 «커버» 크롭 — 남는 높이의 35%만 내려서 자른다(얼굴이 가운데 오도록 위를 더 남긴다).
    // 「아주 긴 세로 사진은 얼굴이 맨 위에 있다」고 보고 12%로 묶어봤지만, 인물이 세로 가운데
    // 있는 사진에서는 오히려 얼굴이 잘렸다(실측 2026-09-06). 얼굴 검출 없이 비율만으로는
    // 어느 쪽도 항상 옳지 않아 원래의 35%를 둔다 — 필요하면 감독이 고르게 하는 것이 정답이다.
    const side = Math.min(c.bitmap.width, c.bitmap.height);
    const exX = c.bitmap.width - side;
    const exY = c.bitmap.height - side;
    const fx = c.crop?.x === "left" ? 0 : c.crop?.x === "right" ? 1 : 0.5;
    // 세로 기본값 0.35 — 얼굴이 위쪽에 있는 사진이 많다. 감독이 고르면 그 값을 따른다.
    const fy = c.crop?.y === "top" ? 0 : c.crop?.y === "bottom" ? 1 : c.crop?.y === "center" ? 0.5 : 0.35;
    const sx = exX * fx;
    const sy = Math.max(0, exY * fy);
    ctx.drawImage(c.bitmap, sx, sy, side, side, cardX, y, photo, photo);
    ctx.strokeStyle = inkOn(opts);
    ctx.lineWidth = 2;
    ctx.strokeRect(cardX + 1, y + 1, photo - 2, photo - 2);

    const tx = cardX + photo + gap;
    const tw = colW - photo - gap;
    // 이름 크기는 카드 높이와 «칸 폭» 둘 다를 따른다 — 2열에서 높이만 보면 이름이 과하게 커진다
    const nameSize = Math.round(Math.max(16, Math.min(cardH * 0.26, colW * 0.075)));
    const noteSize = Math.round(Math.max(12, nameSize * 0.62));
    ctx.font = `400 ${noteSize}px ${FONT_STACK}`;
    const cutsH = c.cuts ? noteSize * 1.5 : 0;
    // 카드 안에 안 들어가는 줄은 버린다 — 넘치면 아래 카드의 이름 위에 겹쳐 찍힌다(실측)
    const roomForNotes = photo - nameSize * 1.25 - cutsH;
    const maxNotes = Math.max(0, Math.min(3, Math.floor(roomForNotes / (noteSize * 1.35))));
    const noteLines = c.look ? wrapText(ctx, c.look, tw).slice(0, maxNotes) : [];
    // 글자 덩어리를 사진 높이에 맞춰 가운데 세운다 — 위로 붙으면 카드가 기울어 보인다
    const blockH = nameSize * 1.25 + noteLines.length * noteSize * 1.35 + cutsH;
    let ty = y + Math.max(0, (photo - blockH) / 2);

    ctx.fillStyle = inkOn(opts);
    ctx.font = `700 ${nameSize}px ${FONT_STACK}`;
    ctx.fillText(c.name, tx, ty + nameSize * 0.6);
    ty += nameSize * 1.25;
    if (noteLines.length > 0) {
      ctx.font = `400 ${noteSize}px ${FONT_STACK}`;
      ctx.fillStyle = opts.paper === "black" ? "#b3aa9b" : "#4a453e";
      noteLines.forEach((line, i) => {
        ctx.fillText(line, tx, ty + noteSize * 0.7 + i * noteSize * 1.35);
      });
      ty += noteLines.length * noteSize * 1.35;
    }
    if (c.cuts) {
      ctx.font = `600 ${noteSize}px ${FONT_STACK}`;
      ctx.fillStyle = opts.paper === "black" ? "#9a9184" : "#8a8175";
      // 두 편 이상 나온 전속 배우라면 그 이력도 함께 — 단행본 인물 소개의 「출연」 칸답게
      ctx.fillText(castCreditLine(ctx, c, tw), tx, ty + noteSize * 0.9);
    }
  }

  if (opts.footer) {
    ctx.font = `500 15px ${FONT_STACK}`;
    ctx.fillStyle = opts.paper === "black" ? "#8d8578" : "#7a7166";
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillText(story.title, opts.margin, height - footerH / 2 - 2);
    ctx.textAlign = "right";
    ctx.fillText(`${pageNo} / ${pageTotal}`, width - opts.margin, height - footerH / 2 - 2);
  }

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("등장인물 장을 그리지 못했습니다."))),
      "image/png",
    );
  });
}

/** 등장인물 장 한 장만 — 조판실 미리보기가 쓴다 (본문을 다시 그리지 않게). */
export async function buildCastPage(
  story: Story,
  cast: CastCard[],
  options: Partial<WebtoonOptions> = {},
  pageNo = 1,
  pageTotal = 1,
): Promise<Blob> {
  const opts: WebtoonOptions = { ...DEFAULT_OPTIONS, ...options };
  await waitForFonts();
  // 폭은 컷 내용과 무관하다 (조판·여백·간격만으로 정해진다)
  const { width } = pageMetrics([], opts);
  return await renderCastPage(story, cast, opts, width, pageNo, pageTotal);
}

/** 표지 한 장만 — 조판실 미리보기가 쓴다. buildWebtoon과 같은 계산을 공유한다. */
/**
 * 장 목차 — 장이 여럿인 합본에서 표지 다음 한 장.
 *
 * 「몇 장인지, 각 장이 몇 페이지에서 시작하는지」만 있으면 종이에서도 찾아갈 수 있다.
 * 장이 다섯을 넘을 때만 붙인다 — 두세 장짜리에 목차는 과하다.
 */
async function renderContents(
  story: Story,
  items: { title: string; page: number; cuts?: number }[],
  opts: WebtoonOptions,
  width: number,
): Promise<Blob> {
  const innerW = width - opts.margin * 2;
  const titleSize = Math.round(Math.max(24, innerW * 0.055));
  const rowH = Math.round(Math.max(34, innerW * 0.042));
  const footerH = opts.footer ? 46 : 0;
  const height = opts.margin * 2 + Math.round(titleSize * 2.4) + items.length * rowH + footerH;

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("이 브라우저에서 Canvas를 쓸 수 없습니다.");
  ctx.fillStyle = pageColor(opts);
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = inkOn(opts);
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.font = `800 ${titleSize}px ${FONT_STACK}`;
  ctx.fillText("목차", opts.margin, opts.margin + titleSize * 0.9);
  ctx.fillRect(opts.margin, opts.margin + Math.round(titleSize * 1.7), innerW, 3);

  const rowSize = Math.round(rowH * 0.46);
  items.forEach((it, i) => {
    const y = opts.margin + Math.round(titleSize * 2.4) + i * rowH + rowH / 2;
    ctx.font = `600 ${rowSize}px ${FONT_STACK}`;
    ctx.fillStyle = inkOn(opts);
    ctx.textAlign = "left";
    ctx.fillText(it.title, opts.margin, y);
    // 장의 두께 — 「3장이 8컷짜리인지 30컷짜리인지」가 목차에서 보이면 합본의 리듬이 읽힌다
    let titleW = ctx.measureText(it.title).width;
    if (it.cuts && it.cuts > 0) {
      const cutSize = Math.round(rowSize * 0.78);
      ctx.font = `500 ${cutSize}px ${FONT_STACK}`;
      ctx.globalAlpha = 0.55;
      ctx.fillText(`${it.cuts}컷`, opts.margin + titleW + Math.round(rowSize * 0.5), y);
      titleW += Math.round(rowSize * 0.5) + ctx.measureText(`${it.cuts}컷`).width;
      ctx.globalAlpha = 1;
      ctx.font = `600 ${rowSize}px ${FONT_STACK}`;
    }
    // 점선 리더 — 제목과 쪽번호를 눈으로 잇는다
    const numText = String(it.page);
    ctx.textAlign = "right";
    ctx.fillText(numText, width - opts.margin, y);
    const from = opts.margin + titleW + 12;
    const to = width - opts.margin - ctx.measureText(numText).width - 12;
    if (to > from) {
      ctx.fillStyle = opts.paper === "black" ? "rgba(239,232,220,0.28)" : "rgba(17,17,17,0.25)";
      for (let x = from; x < to; x += 8) ctx.fillRect(x, y + 1, 3, 2);
    }
  });

  if (opts.footer) {
    ctx.font = `500 15px ${FONT_STACK}`;
    ctx.fillStyle = opts.paper === "black" ? "#8d8578" : "#7a7166";
    ctx.textAlign = "left";
    ctx.fillText(story.title, opts.margin, height - footerH / 2 - 2);
  }

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("목차를 그리지 못했습니다."))),
      "image/png",
    );
  });
}

/** 목차 한 장만 — 조판실 미리보기가 쓴다. */
export async function buildContentsPage(
  story: Story,
  items: { title: string; page: number; cuts?: number }[],
  options: Partial<WebtoonOptions> = {},
): Promise<Blob> {
  const opts: WebtoonOptions = { ...DEFAULT_OPTIONS, ...options };
  await waitForFonts();
  const { width } = pageMetrics([], opts);
  return await renderContents(story, items, opts, width);
}

export async function buildCoverPage(
  story: Story,
  cover: WebtoonPanel,
  panelCount: number,
  options: Partial<WebtoonOptions> = {},
): Promise<Blob> {
  const opts: WebtoonOptions = { ...DEFAULT_OPTIONS, ...options };
  await waitForFonts();
  const { width } = pageMetrics([], opts);
  const innerW = width - opts.margin * 2;
  const ratio = cover.bitmap.width / cover.bitmap.height;
  const height =
    opts.margin * 2 +
    Math.round(innerW / ratio) +
    coverTitleLayout(story.title, innerW, Boolean((story.coverByline ?? "").trim())).bandH;
  return await renderCover(story, cover, opts, width, height, panelCount);
}

/**
 * 여러 장을 세로로 이어 한 장으로 — 웹툰 플랫폼은 «긴 이미지 한 장»을 받는다.
 *
 * 캔버스에는 한계가 있어(브라우저마다 다르지만 3만 픽셀쯤부터 위험) 너무 길어지면 나눠서
 * 여러 장으로 돌려준다. 조용히 잘리는 것보다 «2장으로 나왔다»가 정직하다.
 */
/** 작은 미리보기 JPEG data URL — 시사본 HTML이 「만화판도 있다」를 보여줄 때 쓴다(수십 KB). */
export async function thumbDataUrl(page: Blob, width = 240): Promise<string> {
  const bmp = await createImageBitmap(page);
  try {
    const h = Math.max(1, Math.round((bmp.height / bmp.width) * width));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("이 브라우저에서 Canvas를 쓸 수 없습니다.");
    ctx.imageSmoothingQuality = "high";
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, width, h);
    ctx.drawImage(bmp, 0, 0, width, h);
    return canvas.toDataURL("image/jpeg", 0.72);
  } finally {
    bmp.close?.();
  }
}

export async function stitchPages(pages: Blob[], maxH = 28000): Promise<Blob[]> {
  if (pages.length === 0) return [];
  const bitmaps = await Promise.all(pages.map((b) => createImageBitmap(b)));
  try {
    const width = Math.max(...bitmaps.map((b) => b.width));
    const groups: ImageBitmap[][] = [];
    let cur: ImageBitmap[] = [];
    let h = 0;
    for (const bm of bitmaps) {
      if (cur.length > 0 && h + bm.height > maxH) {
        groups.push(cur);
        cur = [];
        h = 0;
      }
      cur.push(bm);
      h += bm.height;
    }
    if (cur.length > 0) groups.push(cur);

    const out: Blob[] = [];
    for (const g of groups) {
      const total = g.reduce((a, b) => a + b.height, 0);
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = total;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("이 브라우저에서 Canvas를 쓸 수 없습니다.");
      let y = 0;
      for (const bm of g) {
        ctx.drawImage(bm, Math.round((width - bm.width) / 2), y);
        y += bm.height;
      }
      out.push(
        await new Promise<Blob>((resolve, reject) => {
          canvas.toBlob(
            (b) => (b ? resolve(b) : reject(new Error("이어 붙이지 못했습니다."))),
            "image/png",
          );
        }),
      );
    }
    return out;
  } finally {
    for (const bm of bitmaps) bm.close?.();
  }
}

/**
 * 인덱스 시트 — 모든 장을 한 장에 축소해 나열한다.
 *
 * «펼침면(두 장 나란히)»은 만들지 않았다: 조판실에서 말풍선을 확인하려면 글자가 읽혀야 하고,
 * 두 장을 나란히 놓으면 한 장이 원본의 27~42%로 줄어 4~7px가 된다(실측).
 * 이 시트는 목적이 다르다 — 글자를 읽는 게 아니라 **연재 전체의 리듬**(어느 장이 길고 짧은지,
 * 어디서 장이 열리는지)을 한눈에 보는 것이다. 그래서 미리보기가 아니라 «내보내기»로 만든다.
 */
export async function buildIndexSheet(
  pages: Blob[],
  title: string,
  options: Partial<WebtoonOptions> = {},
  cols = 4,
  /** 장이 열리는 쪽 — 그 칸에 장 이름을 얹어 20장 연재에서도 경계가 보이게 한다 */
  chapters: readonly { title: string; page: number }[] = [],
): Promise<Blob> {
  if (pages.length === 0) throw new Error("시트로 만들 장이 없습니다.");
  const opts: WebtoonOptions = { ...DEFAULT_OPTIONS, ...options };
  await waitForFonts();
  const bitmaps = await Promise.all(pages.map((b) => createImageBitmap(b)));
  try {
    const { width } = pageMetrics([], opts);
    const gap = Math.max(10, opts.gutter);
    const labelH = 26;
    const cellW = Math.floor((width - opts.margin * 2 - gap * (cols - 1)) / cols);
    // 칸 높이는 «가장 긴 장»에 맞춘다 — 장마다 높이가 달라도 격자가 흐트러지지 않게
    const tallest = Math.max(...bitmaps.map((b) => b.height / b.width));
    const cellH = Math.round(cellW * Math.min(tallest, 2.6)) + labelH;
    const rows = Math.ceil(bitmaps.length / cols);
    const headH = Math.round(width * 0.045);
    const height = opts.margin * 2 + headH + rows * cellH + (rows - 1) * gap;

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("이 브라우저에서 Canvas를 쓸 수 없습니다.");
    ctx.fillStyle = pageColor(opts);
    ctx.fillRect(0, 0, width, height);
    ctx.imageSmoothingQuality = "high";

    ctx.fillStyle = inkOn(opts);
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.font = `800 ${Math.round(headH * 0.52)}px ${FONT_STACK}`;
    ctx.fillText(`${title} — 전체 ${pages.length}장`, opts.margin, opts.margin + headH * 0.45);

    bitmaps.forEach((bm, i) => {
      const cx = opts.margin + (i % cols) * (cellW + gap);
      const cy = opts.margin + headH + Math.floor(i / cols) * (cellH + gap);
      const drawH = Math.min(cellH - labelH, Math.round((bm.height / bm.width) * cellW));
      ctx.drawImage(bm, 0, 0, bm.width, bm.height, cx, cy, cellW, drawH);
      ctx.strokeStyle = inkOn(opts);
      ctx.lineWidth = 2;
      ctx.strokeRect(cx + 1, cy + 1, cellW - 2, drawH - 2);
      ctx.font = `600 ${Math.round(labelH * 0.55)}px ${FONT_STACK}`;
      ctx.fillStyle = opts.paper === "black" ? "#9a9184" : "#6b6459";
      ctx.textAlign = "center";
      ctx.fillText(`${i + 1}`, cx + cellW / 2, cy + drawH + labelH * 0.55);
      ctx.textAlign = "left";
      // 장이 열리는 칸에는 이름표 — 20장 연재의 시트에서 장 경계가 보이지 않으면 리듬을 못 읽는다
      const chap = chapters.find((c) => c.page === i + 1);
      if (chap) {
        const tagH = Math.round(labelH * 0.86);
        ctx.font = `700 ${Math.round(tagH * 0.62)}px ${FONT_STACK}`;
        const tw = Math.min(cellW - 8, ctx.measureText(chap.title).width + 14);
        ctx.fillStyle = "rgba(240,180,94,0.92)";
        ctx.fillRect(cx + 4, cy + 4, tw, tagH);
        ctx.fillStyle = "#1a1510";
        ctx.textBaseline = "middle";
        ctx.fillText(chap.title, cx + 11, cy + 4 + tagH / 2, tw - 14);
        // 장 시작 칸은 테두리도 굵게 — 이름표를 못 읽는 작은 시트에서도 경계가 보인다
        ctx.strokeStyle = "rgba(240,180,94,0.9)";
        ctx.lineWidth = 4;
        ctx.strokeRect(cx + 2, cy + 2, cellW - 4, drawH - 4);
        ctx.lineWidth = 2;
        ctx.strokeStyle = inkOn(opts);
      }
    });

    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("시트를 그리지 못했습니다."))),
        "image/png",
      );
    });
  } finally {
    for (const bm of bitmaps) bm.close?.();
  }
}

/** 합본 한 권에 들어갈 한 «화» */
export interface OmnibusVolume {
  /** 화 제목 — 본문에서 그 화의 «장 제목 띠»와 목차에 쓰인다 */
  title: string;
  story: Story;
  panels: WebtoonPanel[];
}

/**
 * 합본 — 여러 화를 «한 권»으로 조판한다.
 *
 * 연재의 끝에 오는 일이다. 화마다 따로 뽑으면 표지도 목차도 쪽 번호도 다섯 벌이 되고,
 * 책장에 꽂을 한 권이 없다. 그래서 표지 한 장·목차 한 장·등장인물 한 장을 책 전체에 두고,
 * 본문은 화 순서대로 이어 붙이며 쪽 번호를 이어 센다(각 화의 발치가 「7 / 42」가 된다).
 * 화의 첫 컷은 그 화 제목으로 «장을 여는 컷»으로 취급한다 — 원본 대본은 건드리지 않는다.
 */
export async function buildOmnibus(
  seriesTitle: string,
  volumes: OmnibusVolume[],
  options: Partial<WebtoonOptions> = {},
  cast: CastCard[] = [],
): Promise<{
  pages: Blob[];
  entries: { title: string; page: number; cuts: number }[];
  lead: number;
}> {
  const base: WebtoonOptions = { ...DEFAULT_OPTIONS, ...options };
  await waitForFonts();
  const live = volumes.filter((v) => v.panels.length > 0);
  if (live.length === 0) return { pages: [], entries: [], lead: 0 };

  /** 화의 첫 컷을 그 화 제목의 «장»으로 연다 — 사본을 만들어 대본을 건드리지 않는다 */
  const marked = live.map((v) => {
    const first = v.panels[0];
    const head: WebtoonPanel = {
      ...first,
      scene: {
        ...first.scene,
        webtoon: { ...(first.scene.webtoon ?? {}), pageBreak: true, caption: v.title },
      },
    };
    return { ...v, panels: [head, ...v.panels.slice(1)] };
  });

  const counts = marked.map((v) =>
    countWebtoonPages(v.panels, { ...base, cover: false, contents: false, castPage: false }),
  );
  const withCast = base.castPage && cast.length > 0;
  const wantContents = base.contents && marked.length >= 2;
  const lead = (base.cover ? 1 : 0) + (wantContents ? 1 : 0);
  const grandTotal = lead + counts.reduce((a, b) => a + b, 0) + (withCast ? 1 : 0);

  const pages: Blob[] = [];
  const entries: { title: string; page: number; cuts: number }[] = [];
  /**
   * 목차 줄 — 화와 «그 안의 장»을 함께 싣는다.
   * 화만 실으면 화마다 장이 둘인 책에서 목차가 절반만 보인다(5화 10장인데 다섯 줄, 실측).
   * 다만 줄이 마흔을 넘으면 목차 한 장이 끝없이 길어지므로 그때는 화만 싣는다.
   */
  const rows: { title: string; page: number; cuts?: number }[] = [];
  let sofar = 0;
  for (let i = 0; i < marked.length; i++) {
    const v = marked[i];
    const built = await buildWebtoon(
      v.story,
      v.panels,
      {
        ...base,
        cover: false,
        contents: false,
        castPage: false,
        chapterBand: true, // 화가 바뀌는 자리는 띠로 알린다(합본에서는 이게 유일한 경계다)
        pageOffset: lead + sofar,
        pageGrandTotal: grandTotal,
      },
      [],
    );
    pages.push(...built.pages);
    entries.push({ title: v.title, page: lead + sofar + 1, cuts: v.panels.length });
    rows.push({ title: v.title, page: lead + sofar + 1, cuts: v.panels.length });
    // 첫 장은 «화 제목»으로 연 것이므로 건너뛴다 — 같은 줄을 두 번 적지 않는다
    for (const ch of built.chapters.slice(1)) {
      rows.push({ title: `· ${ch.title}`, page: lead + sofar + ch.page, cuts: ch.cuts });
    }
    sofar += counts[i];
  }

  const m = pageMetrics([marked[0].panels[0]], base);
  if (withCast) {
    pages.push(await renderCastPage({ ...marked[0].story, title: seriesTitle }, cast, base, m.width, grandTotal, grandTotal));
  }
  if (wantContents) {
    const items = rows.length <= 40 ? rows : entries;
    pages.unshift(await renderContents({ ...marked[0].story, title: seriesTitle }, items, base, m.width));
  }
  if (base.cover) {
    const cov = marked[0].panels[Math.max(0, Math.min(base.coverIndex ?? 0, marked[0].panels.length - 1))];
    const covRatio = cov.bitmap.width / cov.bitmap.height;
    const innerW = m.width - base.margin * 2;
    const seriesStory: Story = {
      ...marked[0].story,
      title: seriesTitle,
      coverSubtitle:
        (marked[0].story.coverSubtitle ?? "").trim() ||
        `${entries[0].title} ~ ${entries[entries.length - 1].title} 합본`,
    };
    const coverH =
      base.margin * 2 +
      Math.round(innerW / covRatio) +
      coverTitleLayout(seriesStory.title, innerW, Boolean((seriesStory.coverByline ?? "").trim())).bandH;
    pages.unshift(
      await renderCover(
        seriesStory,
        cov,
        base,
        m.width,
        coverH,
        marked.reduce((n, v) => n + v.panels.length, 0),
      ),
    );
  }
  return { pages, entries, lead };
}

/**
 * 그리지 않고 본문 쪽 수만 센다 — 합본의 쪽 번호를 «한 번에» 계산하려고 만들었다.
 * 두 번 그려서 세면 다섯 화짜리 책에 두 배의 시간이 든다(조판은 이 앱에서 가장 비싼 일이다).
 */
export function countWebtoonPages(panels: WebtoonPanel[], options: Partial<WebtoonOptions> = {}): number {
  const opts: WebtoonOptions = { ...DEFAULT_OPTIONS, ...options };
  if (opts.layout === "grid") opts.perPage = 4;
  const per = Math.max(1, Math.min(opts.perPage, 8));
  return chunkByPage(panels, per, (p) => p.scene.webtoon?.pageBreak === true).length;
}

export async function buildWebtoon(
  story: Story,
  panels: WebtoonPanel[],
  options: Partial<WebtoonOptions> = {},
  cast: CastCard[] = [],
): Promise<WebtoonResult> {
  const opts: WebtoonOptions = { ...DEFAULT_OPTIONS, ...options };
  if (opts.layout === "grid") opts.perPage = 4;
  const per = Math.max(1, Math.min(opts.perPage, 8));
  await waitForFonts();

  const chunks = chunkByPage(panels, per, (p) => p.scene.webtoon?.pageBreak === true);

  const withCast = opts.castPage && cast.length > 0;
  const own = chunks.length + (withCast ? 1 : 0);
  // 합본이면 발치의 번호는 «책 전체»를 따른다(한 화짜리 책에서는 예전과 똑같다)
  const offset = Math.max(0, opts.pageOffset ?? 0);
  const total = Math.max(own + offset, opts.pageGrandTotal ?? own);
  const pages: Blob[] = [];
  for (let i = 0; i < chunks.length; i++) {
    pages.push(await renderPage(chunks[i], opts, story.title, offset + i + 1, total));
  }
  // 등장인물 장은 맨 뒤 — 본문과 같은 폭으로 묶음이 흐트러지지 않게 한다
  if (withCast && chunks.length > 0) {
    const m = pageMetrics(chunks[0], opts);
    pages.push(await renderCastPage(story, cast, opts, m.width, offset + own, total));
  }
  // 장 목차 — 장이 여럿이면 표지 다음(= 배열 맨 앞, 표지가 그 앞에 unshift된다)
  // 장을 여는 쪽만 싣는다. 첫 쪽은 표시가 없어도 1장이고, 이름을 안 붙인 장도 「N장」으로 싣는다
  // — 목차에서 장이 빠지면 «몇 장짜리 책인지»가 어긋난다.
  const chapters: { title: string; page: number; cuts: number }[] = [];
  chunks.forEach((c, i) => {
    const opens = i === 0 || c[0]?.scene.webtoon?.pageBreak === true;
    if (opens) {
      chapters.push({
        title: (c[0]?.scene.webtoon?.caption ?? "").trim() || `${chapters.length + 1}장`,
        page: i + 1,
        cuts: c.length,
      });
    } else if (chapters.length > 0) {
      // 한 장이 여러 쪽에 걸치면 그 쪽의 컷도 그 장의 두께다
      chapters[chapters.length - 1].cuts += c.length;
    }
  });
  if (opts.contents && chapters.length >= 5 && chunks.length > 0) {
    const m = pageMetrics(chunks[0], opts);
    pages.unshift(await renderContents(story, chapters, opts, m.width));
  }
  // 표지는 본문 첫 장과 같은 크기로 맨 앞에 붙인다
  if (opts.cover && chunks.length > 0) {
    const idx = Math.max(0, Math.min(opts.coverIndex ?? 0, panels.length - 1));
    const m = pageMetrics(chunks[0], opts);
    const cov = panels[idx];
    const covRatio = cov.bitmap.width / cov.bitmap.height;
    const innerW = m.width - opts.margin * 2;
    // 그림 전체 높이 + 제목에 맞춘 띠 — 표지는 한 눈에 들어와야 한다
    const coverH =
      opts.margin * 2 +
      Math.round(innerW / covRatio) +
      coverTitleLayout(story.title, innerW, Boolean((story.coverByline ?? "").trim())).bandH;
    pages.unshift(await renderCover(story, cov, opts, m.width, coverH, panels.length));
  }
  // 표지·목차가 앞에 붙은 만큼이 lead — 장 쪽번호(본문 기준)를 pages 인덱스로 옮길 때 쓴다
  return { pages, panelCount: panels.length, chapters, lead: pages.length - chunks.length };
}
