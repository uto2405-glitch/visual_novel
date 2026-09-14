/** 오류 번역 — raw 문자열(`시작 실패 (400)`) 금지. 검열 403과 파라미터 400을 구분한다. */
import type { CameraModel } from "./models";

export type ErrorKind =
  | "auth"
  | "params"
  | "censored"
  | "network"
  | "timeout"
  | "aborted"
  | "unknown";

export class MakefunError extends Error {
  kind: ErrorKind;
  retryable: boolean;
  /** 시작 시점에 이미 과금된 코인 — 실패해도 장부에 기록해야 한다 */
  coins: number | null;

  constructor(
    message: string,
    opts: { kind: ErrorKind; retryable?: boolean; coins?: number | null },
  ) {
    super(message);
    this.name = "MakefunError";
    this.kind = opts.kind;
    this.retryable = opts.retryable ?? false;
    this.coins = opts.coins ?? null;
  }
}

/**
 * 완료 후 실패(failed_message)의 번역. Seedream의 저작권/초상권 거부가 대표적.
 * 반환: [번역된 문장, kind]
 */
export function translateFailureMessage(server: string): [string, ErrorKind] {
  if (/copyright|portrait|likeness|celebrit|public figure/i.test(server)) {
    return [
      "Seedream이 캐스팅 사진의 인물을 저작권·초상권 제한으로 거부했습니다. " +
        "카메라를 Wan 2.7이나 Flux 2로 바꿔 「NG만 다시」를 눌러보세요. " +
        "그래도 거부되면 실존 인물이 아닌 사진(본인 사진, AI 생성 얼굴 등)으로 캐스팅해야 합니다.",
      "censored",
    ];
  }
  if (/nsfw|sensitive|content.?policy/i.test(server)) {
    return [
      "MakeFun이 이 컷의 내용을 받지 않았습니다(검열). 표현을 조금 바꾸거나, 이 컷만 다른 카메라로 찍어보세요.",
      "censored",
    ];
  }
  return [
    `이 컷은 NG가 났습니다.${server ? ` (${server})` : ""} 프롬프트를 다듬어 다시 찍어보세요.`,
    "unknown",
  ];
}

export function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

export function serverMessage(json: unknown): string {
  const root = asRecord(json);
  if (!root) return "";
  const data = asRecord(root.data) ?? root;
  const msg =
    data.error ??
    data.message ??
    data.fail_reason ??
    data.failed_message ?? // 실제 MakeFun 응답 필드 (2026-08 확인)
    root.error ??
    root.message;
  return typeof msg === "string" ? msg.trim() : "";
}

export function isNsfwPayload(json: unknown): boolean {
  const text = JSON.stringify(json ?? {}).toLowerCase();
  return (
    text.includes("nsfw") ||
    text.includes("sensitive content") ||
    text.includes("content_policy")
  );
}

export function translateHttpError(
  status: number,
  json: unknown,
  model: CameraModel,
): MakefunError {
  const server = serverMessage(json);
  if (status === 401) {
    return new MakefunError(
      "카메라 토큰이 통하지 않습니다. 설정에서 MakeFun 토큰을 다시 확인해 주세요.",
      { kind: "auth" },
    );
  }
  if (status === 403 || isNsfwPayload(json)) {
    return new MakefunError(
      "MakeFun이 이 컷의 내용을 받지 않았습니다(검열). 표현을 조금 바꾸거나, 이 컷만 다른 카메라로 찍어보세요.",
      { kind: "censored" },
    );
  }
  if (status === 400) {
    if (model.family === "seedream") {
      return new MakefunError(
        "이 필름명은 MakeFun이 거절했을 수 있습니다. Wan으로 이 장면만 찍을까요? " +
          "배우 사진(레퍼런스) 형식이 원인일 수도 있으니, 레퍼런스 없이 찍거나 " +
          "MakeFun 사이트에 결과가 나왔다면 「MakeFun URL 붙이기」로 가져올 수 있습니다.",
        { kind: "params" },
      );
    }
    return new MakefunError(
      `카메라가 요청을 받지 않았습니다(설정 문제). 프롬프트나 크기를 바꿔 다시 찍어보세요.${server ? ` (${server})` : ""}`,
      { kind: "params" },
    );
  }
  if (status === 429) {
    return new MakefunError("카메라가 붐빕니다. 잠시 후 자동으로 다시 시도합니다.", {
      kind: "network",
      retryable: true,
    });
  }
  if (status === 502 || status === 503 || status === 504) {
    return new MakefunError("카메라 응답이 늦습니다. 잠시 후 자동으로 다시 시도합니다.", {
      kind: "network",
      retryable: true,
    });
  }
  return new MakefunError(`카메라 응답에 문제가 있습니다.${server ? ` (${server})` : ""}`, {
    kind: "unknown",
  });
}

export function normalizeError(err: unknown): MakefunError {
  if (err instanceof MakefunError) return err;
  if (err instanceof TypeError) {
    return new MakefunError("카메라와 연결이 끊겼습니다. 네트워크를 확인해 주세요.", {
      kind: "network",
      retryable: true,
    });
  }
  if (err instanceof DOMException && err.name === "AbortError") {
    return new MakefunError("중단했습니다.", { kind: "aborted" });
  }
  return new MakefunError(
    err instanceof Error && err.message ? err.message : "알 수 없는 문제가 생겼습니다.",
    { kind: "unknown" },
  );
}
