/**
 * 무빙 컷 (실험) — MakeFun userImage2Video: 이미지 URL → 짧은 영상.
 *
 * 실측 계약 (2026-08-29, 무과금 검증 오류로 확인):
 *  - POST /api/v1/userImage2Video/start
 *    { image_url(필수, http URL — data URL 아님), prompt+negative_prompt(필수), name }
 *  - model_type는 생략 시 기본값. 시작 즉시 과금(~30코인), current_status: initialized→sent→…
 *  - 결과는 result_url (mp4). 원본 이미지 URL은 MakeFun CDN 기준 약 3일 유효.
 */
import {
  MakefunError,
  normalizeError,
  serverMessage,
  translateFailureMessage,
  translateHttpError,
} from "./errors";
import { modelById } from "./models";
import { extractCoins, extractPollStatus, extractTaskId } from "./parse";

const FAM = "userImage2Video";
const DEFAULT_NEGATIVE = "blurry, distorted, deformed face, low quality, watermark";

/** 시사실이 기대하는 영상 MIME 판별에도 쓰인다 */
export const VIDEO_EXT_RE = /\.(mp4|webm|mov)(\?|$)/i;

function authHeaders(token: string, json = true): HeadersInit {
  const h: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (json) h["Content-Type"] = "application/json";
  return h;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new MakefunError("중단했습니다.", { kind: "aborted" }));
      return;
    }
    const t = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(new MakefunError("중단했습니다.", { kind: "aborted" }));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/** result_url/display_result_url 우선, 그다음 영상 확장자 URL 탐색 */
function extractVideoUrl(json: unknown): string | null {
  const root = json && typeof json === "object" ? (json as Record<string, unknown>) : null;
  if (!root) return null;
  const data =
    root.data && typeof root.data === "object" ? (root.data as Record<string, unknown>) : root;
  for (const k of ["result_url", "display_result_url", "video_url", "url_download"]) {
    const v = data[k];
    if (typeof v === "string" && /^https?:\/\//i.test(v)) return v;
  }
  const found: string[] = [];
  const walk = (node: unknown, depth: number) => {
    if (depth > 6 || node == null) return;
    if (typeof node === "string") {
      if (/^https?:\/\//i.test(node) && VIDEO_EXT_RE.test(node)) found.push(node);
      return;
    }
    if (Array.isArray(node)) {
      for (const x of node) walk(x, depth + 1);
      return;
    }
    if (typeof node === "object") {
      for (const v of Object.values(node as Record<string, unknown>)) walk(v, depth + 1);
    }
  };
  walk(json, 0);
  return found[0] ?? null;
}

async function readJson(res: Response): Promise<unknown> {
  return res.json().catch(() => ({ status: res.status }));
}

export interface MovingCutInput {
  token: string;
  sceneId: string;
  /** 공개 http(s) URL이어야 한다 — 촬영 직후 보관한 MakeFun 결과 URL */
  imageUrl: string;
  prompt: string;
  signal: AbortSignal;
}

export interface MovingCutResult {
  blob: Blob;
  /** 실제 과금된 코인 (응답 기준) */
  coins: number | null;
}

/** 이미지 → 영상 변환 전체 흐름. 성공 시 영상 Blob + 실비용. */
export async function makeMovingVideo(input: MovingCutInput): Promise<MovingCutResult> {
  const { token, sceneId, imageUrl, prompt, signal } = input;
  const model = modelById(undefined); // 오류 번역용 (seedream 특례 미적용 경로)

  const res = await fetch(`/api/makefun/${FAM}/start`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({
      name: sceneId,
      image_url: imageUrl,
      prompt: `${prompt}, subtle natural motion, cinemagraph, keep the same face`,
      negative_prompt: DEFAULT_NEGATIVE,
    }),
    signal,
  });
  const json = await readJson(res);
  if (!res.ok) throw translateHttpError(res.status, json, model);
  const coins = extractCoins(json);
  const taskId = extractTaskId(json);
  if (!taskId) {
    throw new MakefunError("영상 작업 번호를 받지 못했습니다.", { kind: "unknown" });
  }

  /* 시작이 접수된 순간 이미 과금됐다 — 이후 어떤 실패·중단이든 coins를 오류에 실어 장부에 남긴다.
     (이미지 쪽 shootCut과 같은 규율. 영상은 컷당 수십 코인이라 잃으면 더 아프다 —
     편을 옮기며 중단된 영상 30코인이 장부에서 사라지는 것을 실측으로 잡았다.) */
  try {
    return await pollVideo(token, taskId, coins, signal);
  } catch (err) {
    const e = normalizeError(err);
    if (e.coins == null) e.coins = coins;
    throw e;
  }
}

/** 영상 폴링 — 오래 걸린다. 넉넉히 기다린다(백오프, 총 ≈ 13분). 중단(signal)은 언제든 가능. */
async function pollVideo(
  token: string,
  taskId: string,
  coins: number | null,
  signal: AbortSignal,
): Promise<{ blob: Blob; coins: number | null }> {
  const paths = [`/api/makefun/${FAM}/${encodeURIComponent(taskId)}`, `/api/makefun/${FAM}/detail/${encodeURIComponent(taskId)}`];
  let goodPath: string | null = null;
  for (let i = 0; i < 200; i++) {
    if (signal.aborted) throw new MakefunError("중단했습니다.", { kind: "aborted" });
    const candidates: string[] = goodPath ? [goodPath] : paths;
    for (const path of candidates) {
      let r: Response;
      try {
        r = await fetch(path, { method: "GET", headers: authHeaders(token, false), signal });
      } catch (err) {
        const e = normalizeError(err);
        if (e.kind === "aborted") throw e;
        break; // 네트워크 순단 — 다음 턴
      }
      if (r.status === 404) continue;
      const j = await readJson(r);
      if (!r.ok) break;
      goodPath = path;
      const status = extractPollStatus(j);
      const url = extractVideoUrl(j);
      if (status === "failed") {
        const [msg, kind] = translateFailureMessage(serverMessage(j));
        throw new MakefunError(msg, { kind, coins });
      }
      if (url) {
        return { blob: await downloadVideo(url, signal), coins };
      }
      break;
    }
    await sleep(i < 30 ? 3000 : 5000, signal);
  }
  throw new MakefunError(
    "영상 생성이 오래 걸리고 있습니다. NG가 아니라 아직 만드는 중일 수 있어요 — 잠시 후 다시 확인해 주세요.",
    { kind: "timeout" },
  );
}

/** 결과 영상 다운로드 — 프록시 경유, Blob 보관. */
export async function downloadVideo(url: string, signal: AbortSignal): Promise<Blob> {
  const res = await fetch("/api/fetch-image", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
    signal,
  });
  if (!res.ok) {
    const json = await readJson(res);
    throw new MakefunError(serverMessage(json) || "영상을 받아오지 못했습니다.", {
      kind: "network",
    });
  }
  const blob = await res.blob();
  if (blob.size === 0) {
    throw new MakefunError("받은 영상이 비어 있습니다.", { kind: "network" });
  }
  const type = blob.type.startsWith("video/") ? blob.type : "video/mp4";
  return blob.type === type ? blob : new Blob([await blob.arrayBuffer()], { type });
}
