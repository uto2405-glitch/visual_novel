/**
 * 촬영 클라이언트 — 시작 → (id 유실 시 복구) → 폴링 → 다운로드.
 * 브라우저에서 makefun.ai를 직접 부르지 않는다. `/api/makefun/*` 프록시만.
 * 토큰은 localStorage `makefun_token`에만 있고, 여기서는 헤더로 흘려보낼 뿐이다.
 * 시사(플레이) 중에는 이 모듈의 어떤 함수도 호출되지 않는다.
 */
import type { SizeKey } from "../../types";
import { toJpegDataUrl } from "../blob";
import {
  MakefunError,
  isNsfwPayload,
  normalizeError,
  serverMessage,
  translateFailureMessage,
  translateHttpError,
} from "./errors";
import type { CameraModel } from "./models";
import { buildBody, detailPaths, listPaths, startPath } from "./request";
import {
  extractCoins,
  extractImageUrls,
  extractPollStatus,
  extractTaskId,
  extractRecordPrompt,
  newestRecordNamed,
  promptsLookSame,
} from "./parse";

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

/** 429/502/503/504/네트워크만 3회 재시도: 1.5s → 3s → 6s. 400/401은 즉시 번역. */
const RETRY_DELAYS = [1500, 3000, 6000];

async function withRetry<T>(fn: () => Promise<T>, signal: AbortSignal): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= RETRY_DELAYS.length; attempt++) {
    if (signal.aborted) throw new MakefunError("중단했습니다.", { kind: "aborted" });
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      const retryable =
        err instanceof MakefunError ? err.retryable : err instanceof TypeError; // fetch 네트워크 오류
      if (!retryable || attempt === RETRY_DELAYS.length) throw normalizeError(err);
      await sleep(RETRY_DELAYS[attempt], signal);
    }
  }
  throw normalizeError(lastErr);
}

async function readJson(res: Response): Promise<unknown> {
  return res.json().catch(() => ({ status: res.status }));
}

/** 결과 URL은 만료되므로 완료 즉시 프록시로 받아 Blob으로 보관한다. */
export async function downloadResultImage(url: string, signal: AbortSignal): Promise<Blob> {
  return withRetry(async () => {
    const res = await fetch("/api/fetch-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
      signal,
    });
    if (!res.ok) {
      const json = await readJson(res);
      const msg = serverMessage(json) || "생성된 그림을 받아오지 못했습니다.";
      throw new MakefunError(msg, {
        kind: "network",
        retryable: res.status >= 500 || res.status === 429,
      });
    }
    const blob = await res.blob();
    if (blob.size === 0) {
      throw new MakefunError("받은 그림이 비어 있습니다.", { kind: "network", retryable: true });
    }
    const type = blob.type.startsWith("image/") ? blob.type : "image/png";
    return blob.type === type ? blob : new Blob([await blob.arrayBuffer()], { type });
  }, signal);
}

export interface ShootInput {
  token: string;
  model: CameraModel;
  size: SizeKey;
  sceneId: string;
  prompt: string;
  /** 배우 캐스팅 사진들. data URL로 변환해 input_images에 넣는다 */
  referenceBlobs: Blob[];
  signal: AbortSignal;
}

export interface ShootResult {
  blob: Blob;
  /** 결과 이미지의 MakeFun CDN URL (약 3일 유효) — 무빙 컷 변환의 원본으로 보관 */
  sourceUrl: string | null;
  /** 실제 과금된 코인 (응답 기준) — 제작비 장부에 누적 */
  coins: number | null;
}

/**
 * 한 컷 촬영 전체 흐름. 성공하면 이미지 Blob + 원본 URL.
 * 실패는 전부 번역된 MakefunError — raw 상태 문자열은 사용자에게 닿지 않는다.
 */
export async function shootCut(input: ShootInput): Promise<ShootResult> {
  const { token, model, size, sceneId, prompt, signal } = input;
  if (!token) {
    throw new MakefunError("카메라 토큰이 없습니다. 설정에서 MakeFun 토큰을 넣어주세요.", {
      kind: "auth",
    });
  }
  if (model.family === "editor" && input.referenceBlobs.length < 2) {
    throw new MakefunError(
      "Image Editor는 입력 이미지가 2장 필요합니다. 장면 컷에는 Seedream이나 Wan을 쓰세요.",
      { kind: "params" },
    );
  }

  const images: string[] = [];
  for (const b of input.referenceBlobs) {
    try {
      images.push(await toJpegDataUrl(b)); // webp·큰 사진도 카메라가 받는 JPEG로
    } catch {
      /* 읽을 수 없는 레퍼런스는 건너뛴다 */
    }
  }

  // 1) 시작
  const startJson = await withRetry(async () => {
    const res = await fetch(startPath(model), {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(buildBody(model, sceneId, prompt, images, size)),
      signal,
    });
    const json = await readJson(res);
    if (!res.ok) throw translateHttpError(res.status, json, model);
    if (isNsfwPayload(json)) throw translateHttpError(403, json, model);
    return json;
  }, signal);

  const coins = extractCoins(startJson);

  // 시작이 접수된 순간 이미 과금됐다 — 이후 어떤 실패든 coins를 오류에 실어 장부에 남긴다
  try {
    // 2) 시작 응답에 이미지가 바로 있으면 즉시 다운로드
    const immediate = extractImageUrls(startJson);
    if (immediate.length > 0) {
      return {
        blob: await downloadResultImage(immediate[0], signal),
        sourceUrl: immediate[0],
        coins,
      };
    }

    // 3) task id — 없으면 실패로 끝내지 말고 복구 검색
    let taskId = extractTaskId(startJson);
    if (!taskId) {
      const recovered = await recoverTask(token, model, sceneId, signal);
      if (recovered.url) {
        return {
          blob: await downloadResultImage(recovered.url, signal),
          sourceUrl: recovered.url,
          coins,
        };
      }
      taskId = recovered.id;
    }
    if (!taskId) {
      throw new MakefunError(
        "카메라가 작업 번호를 돌려주지 않았습니다. MakeFun 사이트에 결과가 나왔다면 「MakeFun URL 붙이기」로 가져올 수 있습니다.",
        { kind: "unknown" },
      );
    }

    // 4) 폴링
    const url = await pollUntilDone(token, model, taskId, signal);
    return { blob: await downloadResultImage(url, signal), sourceUrl: url, coins };
  } catch (err) {
    const e = normalizeError(err);
    if (e.coins == null) e.coins = coins;
    // 연결 끊김·타임아웃이라면 MakeFun 쪽에는 결과가 있을 수 있다 —
    // NG로 끝내기 전에 기록에서 한 번 회수를 시도한다 (돈 나간 컷을 버리지 않는다).
    if (e.kind === "network" || e.kind === "timeout") {
      try {
        const url = await findRecentResult(
          token,
          model,
          sceneId,
          Date.now() - 15 * 60_000,
          signal,
          prompt,
        );
        if (url) {
          return { blob: await downloadResultImage(url, signal), sourceUrl: url, coins };
        }
      } catch {
        /* 회수 실패 — 원래 오류를 그대로 낸다 */
      }
    }
    throw e;
  }
}

/**
 * MakeFun 기록에서 이 컷의 「완성된」 결과 URL을 찾는다 (추가 과금 없음).
 * 서버 재시작·연결 끊김으로 앱이 결과를 놓쳤을 때의 회수 경로.
 */
export interface CameraCheck {
  ok: boolean;
  /** 어디까지 갔는지 — 실패의 «위치»를 알면 불안이 줄어든다 */
  step: "token" | "network" | "auth" | "ready";
  message: string;
  /** 응답한 카메라 계열 수 */
  families?: number;
}

/**
 * 카메라 시운전 — 촬영 전에 장비가 살아 있는지 본다.
 * 생성이 아니라 «기록 조회(GET)»만 하므로 크레딧이 들지 않는다.
 * 실패해도 사용자를 탓하지 않는 문장으로 돌려준다.
 */
export async function checkCamera(
  token: string,
  models: CameraModel[],
  signal: AbortSignal,
): Promise<CameraCheck> {
  if (!token.trim()) {
    return {
      ok: false,
      step: "token",
      message: "토큰이 비어 있습니다. MakeFun에서 발급한 토큰을 위 칸에 넣어주세요.",
    };
  }
  let sawResponse = false;
  let sawAuthFail = false;
  let okFamilies = 0;
  const seen = new Set<string>();
  for (const model of models) {
    if (seen.has(model.family)) continue;
    seen.add(model.family);
    for (const path of listPaths(model)) {
      if (signal.aborted) throw new MakefunError("중단했습니다.", { kind: "aborted" });
      try {
        const res = await fetch(path, {
          method: "GET",
          headers: authHeaders(token, false),
          signal,
        });
        sawResponse = true;
        if (res.status === 401 || res.status === 403) {
          sawAuthFail = true;
          continue;
        }
        if (res.ok) {
          okFamilies += 1;
          break; // 이 계열은 확인됐다
        }
      } catch {
        /* 이 경로는 실패 — 다음 후보로 */
      }
    }
  }
  if (okFamilies > 0) {
    return {
      ok: true,
      step: "ready",
      message: `카메라 이상 없습니다 — ${okFamilies}개 계열이 응답했습니다. 크레딧은 쓰지 않았어요.`,
      families: okFamilies,
    };
  }
  if (sawAuthFail) {
    return {
      ok: false,
      step: "auth",
      message:
        "서버는 닿았는데 토큰을 받아주지 않았습니다. 만료됐거나 다른 토큰일 수 있어요 — MakeFun에서 새로 발급해 넣어주세요.",
    };
  }
  if (!sawResponse) {
    return {
      ok: false,
      step: "network",
      message:
        "카메라 서버에 닿지 못했습니다. 인터넷 연결을 확인해 주세요 — 토큰 문제는 아닙니다.",
    };
  }
  return {
    ok: false,
    step: "network",
    message: "서버가 응답했지만 기록을 읽지 못했습니다. 잠시 후 다시 눌러보세요.",
  };
}

/**
 * 최근 기록에서 이 컷의 완성본을 찾는다 — URL과 «그 기록에 적힌 프롬프트»를 함께 돌려준다.
 *
 * 프롬프트를 함께 주는 이유: 기록은 `name === 컷 id`로만 찾을 수 있고 컷 id는 편마다 다시
 * 시작하므로(거의 모든 작품에 s01이 있다) 다른 편의 같은 번호를 물어 올 수 있다. 부르는 쪽이
 * 이 컷의 프롬프트와 맞대어 «남의 그림»을 걸러내게 한다.
 */
export async function findRecentRecord(
  token: string,
  model: CameraModel,
  sceneId: string,
  minTs: number,
  signal: AbortSignal,
  expectPrompt?: string,
): Promise<{ url: string; prompt: string | null; samePrompt: boolean | null } | null> {
  for (const path of listPaths(model)) {
    if (signal.aborted) throw new MakefunError("중단했습니다.", { kind: "aborted" });
    try {
      const res = await fetch(path, { method: "GET", headers: authHeaders(token, false), signal });
      if (!res.ok) continue;
      const json = await readJson(res);
      const record = newestRecordNamed(json, sceneId, minTs);
      if (record) {
        const status = extractPollStatus(record);
        const urls = extractImageUrls(record);
        if ((status === "done" || urls.length > 0) && urls[0]) {
          const found = extractRecordPrompt(record);
          return {
            url: urls[0],
            prompt: found,
            samePrompt:
              expectPrompt === undefined ? null : promptsLookSame(found, expectPrompt),
          };
        }
      }
    } catch (err) {
      const e = normalizeError(err);
      if (e.kind === "aborted") throw e;
      /* 다음 후보 경로 */
    }
  }
  return null;
}

/**
 * URL만 필요한 자리(자동 회수). expectPrompt를 주면 «다른 촬영의 결과»는 버린다 —
 * 자동 회수는 감독에게 묻지 않고 그림을 걸므로, 애매하면 가져오지 않는 편이 옳다.
 */
export async function findRecentResult(
  token: string,
  model: CameraModel,
  sceneId: string,
  minTs: number,
  signal: AbortSignal,
  expectPrompt?: string,
): Promise<string | null> {
  const found = await findRecentRecord(token, model, sceneId, minTs, signal, expectPrompt);
  if (!found) return null;
  if (found.samePrompt === false) return null;
  return found.url;
}

/** 시작 응답에 id가 없을 때: 2초 후 allRecords/list에서 name === sceneId 최신 레코드를 찾는다. */
async function recoverTask(
  token: string,
  model: CameraModel,
  sceneId: string,
  signal: AbortSignal,
): Promise<{ id: string | null; url: string | null }> {
  await sleep(2000, signal);
  for (const path of listPaths(model)) {
    if (signal.aborted) throw new MakefunError("중단했습니다.", { kind: "aborted" });
    try {
      const res = await fetch(path, { method: "GET", headers: authHeaders(token, false), signal });
      if (!res.ok) continue;
      const json = await readJson(res);
      const record = newestRecordNamed(json, sceneId);
      if (record) {
        const urls = extractImageUrls(record);
        return { id: extractTaskId(record), url: urls[0] ?? null };
      }
    } catch (err) {
      // 사용자의 중단은 「작업 번호 없음」으로 둔갑시키지 않고 그대로 전파한다
      const e = normalizeError(err);
      if (e.kind === "aborted") throw e;
      /* 다음 후보 경로 */
    }
  }
  return { id: null, url: null };
}

async function pollUntilDone(
  token: string,
  model: CameraModel,
  taskId: string,
  signal: AbortSignal,
): Promise<string> {
  const paths = detailPaths(model, taskId);
  let goodPath: string | null = null;
  let netFails = 0; // 네트워크 오류는 3회까지 폴링을 이어간다 (재시도 계약)
  // 생성이 붐비면 몇 분씩 걸린다 — 넉넉히 기다린다(초반 촘촘, 이후 여유). 총 ≈ 11분.
  // 언제든 「촬영 중단」(signal)으로 끊을 수 있으니 길어도 안전하다.
  const maxAttempts = 160;
  for (let i = 0; i < maxAttempts; i++) {
    if (signal.aborted) throw new MakefunError("중단했습니다.", { kind: "aborted" });
    const candidates: string[] = goodPath ? [goodPath] : paths;
    let candidateErr: MakefunError | null = null;
    let pendingSeen = false;
    let deferRetry = false;
    for (const path of candidates) {
      let res: Response;
      try {
        res = await fetch(path, { method: "GET", headers: authHeaders(token, false), signal });
      } catch (err) {
        const e = normalizeError(err);
        if (e.kind === "aborted" || !e.retryable) throw e;
        netFails += 1;
        if (netFails > 3) throw e;
        deferRetry = true; // 잠깐의 연결 끊김 — 다음 턴에 다시 폴링
        break;
      }
      netFails = 0; // 응답이 왔다는 것 자체가 연결 회복 — 404여도 리셋
      if (res.status === 404) continue; // 다른 경로 후보 시도 / 아직 준비 안 됨
      const json = await readJson(res);
      if (!res.ok) {
        if (res.status === 429 || res.status >= 500) {
          deferRetry = true; // 다음 턴에 재시도
          break;
        }
        // 이 후보 경로가 4xx를 내도 남은 후보를 먼저 시도한다
        candidateErr = translateHttpError(res.status, json, model);
        continue;
      }
      goodPath = path;
      const status = extractPollStatus(json);
      const urls = extractImageUrls(json);
      if (status === "nsfw") throw translateHttpError(403, json, model);
      if (status === "failed") {
        const [msg, kind] = translateFailureMessage(serverMessage(json));
        throw new MakefunError(msg, { kind });
      }
      if (status === "done" || urls.length > 0) {
        if (!urls[0]) {
          throw new MakefunError(
            "촬영은 끝났는데 그림 주소가 없습니다. MakeFun 사이트에서 「MakeFun URL 붙이기」로 가져올 수 있습니다.",
            { kind: "unknown" },
          );
        }
        return urls[0];
      }
      pendingSeen = true;
      break; // pending — 대기 후 재폴링
    }
    if (candidateErr && !pendingSeen && !deferRetry) throw candidateErr;
    // 백오프 — 처음 30회(≈75초)는 촘촘히, 이후엔 여유롭게. 붐비는 생성도 끝까지 기다린다.
    await sleep(i < 30 ? 2500 : 5000, signal);
  }
  throw new MakefunError(
    "생성이 오래 걸리고 있습니다. NG가 아니라 아직 만드는 중일 수 있어요 — 잠시 후 「결과 찾아오기」로 가져오거나 이 컷만 다시 찍어보세요.",
    { kind: "timeout" },
  );
}
