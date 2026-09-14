/** MakeFun 응답 해석 — task id, 이미지 URL, 진행 상태. */
import { asRecord, isNsfwPayload } from "./errors";

const ID_KEYS = [
  "_id",
  "id",
  "task_id",
  "taskId",
  "job_id",
  "jobId",
  "record_id",
  "uuid",
] as const;

/** `_id, id, task_id, taskId, job_id, jobId, record_id, uuid, data.data._id, task.id` 전부 본다. */
export function extractTaskId(json: unknown): string | null {
  const root = asRecord(json);
  if (!root) return null;
  const spots: Array<Record<string, unknown> | null> = [
    root,
    asRecord(root.data),
    asRecord(asRecord(root.data)?.data ?? null),
    asRecord(root.task),
    asRecord(asRecord(root.data)?.task ?? null),
  ];
  for (const spot of spots) {
    if (!spot) continue;
    for (const k of ID_KEYS) {
      const v = spot[k];
      if (typeof v === "string" && v) return v;
      if (typeof v === "number") return String(v);
    }
  }
  return null;
}

function looksLikeImageUrl(u: string): boolean {
  return (
    /\.(png|jpe?g|webp|gif|bmp)(\?|$)/i.test(u) ||
    /makefun|a2e|cloudfront|s3\.|r2\.|cdn|image|oss|tos|qiniu|aliyuncs/i.test(u)
  );
}

function walkForUrls(node: unknown, depth: number, acc: string[]) {
  if (depth > 8 || node == null) return;
  if (typeof node === "string") {
    if (/^https?:\/\//i.test(node) && looksLikeImageUrl(node)) acc.push(node);
    return;
  }
  if (Array.isArray(node)) {
    for (const x of node) walkForUrls(x, depth + 1, acc);
    return;
  }
  if (typeof node === "object") {
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      if (typeof v === "string" && /^https?:\/\//i.test(v)) {
        if (looksLikeImageUrl(v) || /url|image|result|output|file|src/i.test(k)) acc.push(v);
      } else {
        walkForUrls(v, depth + 1, acc);
      }
    }
  }
}

export function extractImageUrls(json: unknown): string[] {
  const found: string[] = [];
  walkForUrls(json, 0, found);
  return Array.from(new Set(found)).filter((u) => /^https?:\/\//i.test(u));
}

/** MakeFun 응답의 실제 과금 코인 (제작비 장부용). 없으면 null. */
export function extractCoins(json: unknown): number | null {
  const root = asRecord(json);
  if (!root) return null;
  const data = asRecord(root.data) ?? root;
  const v = data.coins;
  return typeof v === "number" && v >= 0 ? v : null;
}

export type PollStatus = "pending" | "done" | "failed" | "nsfw";

export function extractPollStatus(json: unknown): PollStatus {
  if (isNsfwPayload(json)) return "nsfw";
  const root = asRecord(json);
  if (!root) return "pending";
  const data = asRecord(root.data) ?? root;
  const raw =
    data.current_status ?? // 실제 MakeFun 응답 필드 (2026-08 확인: initialized/…)
    data.status ??
    data.state ??
    data.task_status ??
    data.taskStatus ??
    root.status;
  const s = String(raw ?? "").toLowerCase();
  if (["completed", "complete", "success", "succeeded", "done", "finished", "ok"].includes(s)) {
    return "done";
  }
  if (["failed", "fail", "error", "canceled", "cancelled", "timeout"].includes(s)) {
    return "failed";
  }
  if (s.includes("nsfw")) return "nsfw";
  if (raw === 2 || raw === "2") return "done";
  if (raw === 3 || raw === "3" || raw === -1) return "failed";
  if (extractImageUrls(json).length > 0 && (s === "" || s === "pending")) return "done";
  return "pending";
}

function recordTimestamp(rec: Record<string, unknown>): number {
  for (const k of ["created_at", "createdAt", "updated_at", "updatedAt", "create_time", "time"]) {
    const v = rec[k];
    if (typeof v === "number") return v;
    if (typeof v === "string") {
      const t = Date.parse(v);
      if (!Number.isNaN(t)) return t;
    }
  }
  const id = rec._id ?? rec.id;
  return typeof id === "string" ? id.length : 0;
}

/** allRecords/list 응답에서 name === sceneId 인 가장 최근 레코드.
 *  minTs를 주면 그 시각(서버 createdAt 기준) 이후의 레코드만 본다 —
 *  다른 프로젝트의 같은 장면 이름과 섞이지 않게. */
export function newestRecordNamed(
  json: unknown,
  sceneId: string,
  minTs = 0,
): Record<string, unknown> | null {
  const matches: Record<string, unknown>[] = [];
  const visit = (node: unknown, depth: number) => {
    if (depth > 6 || node == null) return;
    if (Array.isArray(node)) {
      for (const x of node) visit(x, depth + 1);
      return;
    }
    if (typeof node === "object") {
      const rec = node as Record<string, unknown>;
      if (rec.name === sceneId && (minTs === 0 || recordTimestamp(rec) >= minTs)) {
        matches.push(rec);
      }
      for (const v of Object.values(rec)) visit(v, depth + 1);
    }
  };
  visit(json, 0);
  if (matches.length === 0) return null;
  matches.sort((a, b) => recordTimestamp(b) - recordTimestamp(a));
  return matches[0];
}

/** 기록 레코드에 남아 있는 프롬프트 (필드 이름이 계정·모델마다 다르다) */
export function extractRecordPrompt(rec: unknown): string | null {
  if (!rec || typeof rec !== "object") return null;
  const r = rec as Record<string, unknown>;
  for (const k of ["prompt", "input_prompt", "positive_prompt", "text"]) {
    const v = r[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

/**
 * 두 프롬프트가 «같은 촬영»으로 보이는가.
 *
 * 회수는 기록에서 `name === 컷 id`인 레코드를 찾는다. 그런데 컷 id는 편마다 새로 시작해서
 * (거의 모든 작품에 s01이 있다) 다른 편의 같은 번호를 물어 올 수 있다 — 그러면 남의 그림이
 * 이 컷에 «추가 과금 없이 OK»라는 말과 함께 걸린다. 프롬프트를 맞대어 그 사고를 걸러낸다.
 * 한쪽이 비어 있으면 판정하지 않는다(null) — 계정에 따라 프롬프트를 안 돌려주기도 한다.
 */
export function promptsLookSame(a: string | null, b: string | null): boolean | null {
  const norm = (t: string | null) => (t ?? "").replace(/\s+/g, " ").trim().toLowerCase();
  const x = norm(a);
  const y = norm(b);
  if (!x || !y) return null;
  if (x === y) return true;
  /* 기록이 «잘려» 저장되는 계정을 위한 접두 규칙 — 다만 짧은 쪽이 긴 쪽의 절반 이상일 때만 인정한다.
     앞머리만 보고 같다고 하면 안 된다: 새 작품은 모두 «같은 기본 화풍»으로 시작하므로 서로 다른 두
     편의 프롬프트가 앞 100자까지 똑같다(그러면 가드가 잠들어 남의 그림을 그대로 건다).
     실측(실제 계정 조회, 2026-09-08): 기록의 prompt는 380자 그대로였다 — 잘림은 예외적인 경우다. */
  const [short, long] = x.length <= y.length ? [x, y] : [y, x];
  return long.startsWith(short) && short.length * 2 >= long.length;
}
