/**
 * 작업본 저장소.
 *
 * IndexedDB `vn-studio`
 *  - projects: 프로젝트 메타 + story JSON + 컷 상태
 *  - assets:   캐릭터 JPG, 생성된 장면 이미지 Blob, 테이크 Blob
 *  - saves:    플레이 세이브 (슬롯 3개)
 *  - troupe:   전속 배우단 — 프로젝트 밖에 사는 배우(사진 Blob 포함). 작품을 넘어 재출연한다.
 *
 * localStorage에는 목록만: 프로젝트 목록(이름/수정시각), lastProjectId, makefun_token.
 */
import { openDB, type IDBPDatabase } from "idb";
import type { ProjectListEntry, ProjectRecord, SaveSlot, TroupeActor } from "../types";

const DB_NAME = "vn-studio";

let dbPromise: Promise<IDBPDatabase> | null = null;

function db(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    // v2: troupe(전속 배우단) 추가 — 기존 v1 데이터는 그대로 열린다(파괴적 변경 없음)
    dbPromise = openDB(DB_NAME, 2, {
      upgrade(d) {
        if (!d.objectStoreNames.contains("projects")) {
          d.createObjectStore("projects", { keyPath: "id" });
        }
        if (!d.objectStoreNames.contains("assets")) {
          d.createObjectStore("assets");
        }
        if (!d.objectStoreNames.contains("saves")) {
          d.createObjectStore("saves");
        }
        if (!d.objectStoreNames.contains("troupe")) {
          d.createObjectStore("troupe", { keyPath: "id" });
        }
      },
    });
  }
  return dbPromise;
}

/* ---------- projects ---------- */

export async function getProjectRecord(id: string): Promise<ProjectRecord | undefined> {
  return (await db()).get("projects", id) as Promise<ProjectRecord | undefined>;
}

/** IndexedDB의 실제 프로젝트 전체 — localStorage 목록 유실 시 복원용. */
export async function listProjectRecords(): Promise<ProjectRecord[]> {
  return (await db()).getAll("projects") as Promise<ProjectRecord[]>;
}

export async function putProjectRecord(rec: ProjectRecord): Promise<void> {
  await (await db()).put("projects", rec);
}

export async function deleteProjectRecord(id: string): Promise<void> {
  await (await db()).delete("projects", id);
}

/* ---------- assets ---------- */

export function assetKey(projectId: string, kind: "char" | "gen", name: string): string {
  return `${projectId}:${kind}:${name}`;
}

/**
 * 공간이 모자라 «일부만» 저장된 경우 — 몇 장까지 들어갔는지 들고 다닌다.
 * 감독에게 「스물넉 장 중 열두 장까지는 저장했습니다」라고 말할 수 있어야 한다.
 */
export class PartialAssetsError extends Error {
  constructor(
    readonly saved: number,
    readonly total: number,
    readonly reason: unknown,
  ) {
    const rn = reason instanceof Error ? reason.name : "";
    const rm = reason instanceof Error ? reason.message : String(reason);
    // 이름을 함께 실어 둔다 — 저장 실패를 «가득 찼는가»로 가려내는 곳이 이 문장을 본다
    super(`${saved}/${total} 저장 · ${rn} ${rm}`.trim());
    this.name = "PartialAssetsError";
  }
}

/**
 * 여러 asset을 저장한다 — **묶음으로 나눠** 쓴다.
 *
 * 한 트랜잭션에 전부 담으면 할당량을 넘긴 순간 통째로 취소된다: 실측(v1.3.0, 할당량 4MB)에서
 * 그림 스물넉 장을 걸었을 때 저장소에 남은 것이 **0장**이었다 — 4MB만큼은 들어갈 수 있었는데도.
 * 나눠 쓰면 «들어가는 것까지»는 남고, 감독이 자리를 만든 뒤 다시 저장하면 남은 것만 채워진다
 * (같은 키를 다시 써도 자리를 더 쓰지 않으므로 저장이 조금씩 «앞으로 나아간다»).
 */
export async function putAssets(entries: ReadonlyMap<string, Blob>): Promise<void> {
  if (entries.size === 0) return;
  const d = await db();
  const list = [...entries];
  const CHUNK = 4;
  let saved = 0;
  for (let i = 0; i < list.length; i += CHUNK) {
    const part = list.slice(i, i + CHUNK);
    try {
      const tx = d.transaction("assets", "readwrite");
      for (const [key, blob] of part) void tx.store.put(blob, key);
      await tx.done;
      saved += part.length;
    } catch (e) {
      // 자리가 없으면 뒤 묶음도 못 들어간다 — 여기서 멈추고 «몇 장까지»를 알린다
      throw new PartialAssetsError(saved, list.length, e);
    }
  }
}

export async function getAssets(keys: readonly string[]): Promise<Map<string, Blob>> {
  const d = await db();
  const tx = d.transaction("assets", "readonly");
  const out = new Map<string, Blob>();
  await Promise.all(
    keys.map(async (k) => {
      const v = (await tx.store.get(k)) as Blob | undefined;
      if (v) out.set(k, v);
    }),
  );
  await tx.done;
  return out;
}

/** 프로젝트의 대표 이미지(표지 컷 → 없으면 첫 OK 컷) — 최근 목록 썸네일용. */
export async function getProjectThumbBlob(id: string): Promise<Blob | undefined> {
  const rec = await getProjectRecord(id);
  if (!rec) return undefined;
  const posterKey = rec.posterSceneId ? rec.cuts[rec.posterSceneId]?.imageKey : undefined;
  const firstOkKey = rec.story.scenes
    .map((sc) => rec.cuts[sc.id])
    .find((c) => c?.status === "ok" && c.imageKey)?.imageKey;
  const key = posterKey ?? firstOkKey;
  if (!key) return undefined;
  return (await db()).get("assets", key) as Promise<Blob | undefined>;
}

/** 이 프로젝트 접두사의 저장된 asset 키 전부 — 저장소 청소용. */
export async function listAssetKeysByPrefix(prefix: string): Promise<string[]> {
  const d = await db();
  const keys: string[] = [];
  let cursor = await d.transaction("assets").store.openKeyCursor();
  while (cursor) {
    const k = String(cursor.key);
    if (k.startsWith(prefix)) keys.push(k);
    cursor = await cursor.continue();
  }
  return keys;
}

/** 지정한 asset들을 지우고, 지운 바이트 수를 돌려준다. */
export async function deleteAssetsMeasured(keys: readonly string[]): Promise<number> {
  if (keys.length === 0) return 0;
  const d = await db();
  const tx = d.transaction("assets", "readwrite");
  let bytes = 0;
  for (const key of keys) {
    const v = (await tx.store.get(key)) as Blob | undefined;
    if (v) bytes += v.size;
    await tx.store.delete(key);
  }
  await tx.done;
  return bytes;
}

async function deleteAssetsByPrefix(prefix: string): Promise<void> {
  const d = await db();
  const tx = d.transaction("assets", "readwrite");
  let cursor = await tx.store.openCursor();
  while (cursor) {
    if (String(cursor.key).startsWith(prefix)) {
      await cursor.delete();
    }
    cursor = await cursor.continue();
  }
  await tx.done;
}

/* ---------- troupe (전속 배우단) ---------- */

export async function listTroupe(): Promise<TroupeActor[]> {
  const all = (await (await db()).getAll("troupe")) as TroupeActor[];
  return all.sort((a, b) => b.updatedAt - a.updatedAt);
}

export async function putTroupeActor(actor: TroupeActor): Promise<void> {
  await (await db()).put("troupe", actor);
}

export async function getTroupeActor(id: string): Promise<TroupeActor | undefined> {
  return (await db()).get("troupe", id) as Promise<TroupeActor | undefined>;
}

export async function deleteTroupeActor(id: string): Promise<void> {
  await (await db()).delete("troupe", id);
}

/* ---------- saves ---------- */

function saveSlotKey(projectId: string, slot: number): string {
  return `${projectId}:slot${slot}`;
}

export async function getSaveSlot(projectId: string, slot: number): Promise<SaveSlot | undefined> {
  return (await db()).get("saves", saveSlotKey(projectId, slot)) as Promise<SaveSlot | undefined>;
}

export async function putSaveSlot(slot: number, data: SaveSlot): Promise<void> {
  await (await db()).put("saves", data, saveSlotKey(data.projectId, slot));
}

export async function deleteSaveSlot(projectId: string, slot: number): Promise<void> {
  await (await db()).delete("saves", saveSlotKey(projectId, slot));
}

export async function deleteProjectDeep(id: string): Promise<void> {
  await deleteProjectRecord(id);
  await deleteAssetsByPrefix(`${id}:`);
  for (const s of [1, 2, 3]) await deleteSaveSlot(id, s);
}

/* ---------- localStorage (목록만) ---------- */

const LS_LIST = "vn-studio:projects";
const LS_LAST = "vn-studio:lastProjectId";
const LS_TOKEN = "makefun_token";

export function readProjectList(): ProjectListEntry[] {
  try {
    const raw = localStorage.getItem(LS_LIST);
    if (!raw) return [];
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr)) return [];
    return arr.filter(
      (e): e is ProjectListEntry =>
        Boolean(e) && typeof (e as ProjectListEntry).id === "string",
    );
  } catch {
    return [];
  }
}

function writeProjectList(entries: ProjectListEntry[]) {
  try {
    localStorage.setItem(LS_LIST, JSON.stringify(entries));
  } catch {
    /* 목록 저장 실패는 치명적이지 않다 */
  }
}

export function upsertProjectListEntry(entry: ProjectListEntry) {
  const list = readProjectList().filter((e) => e.id !== entry.id);
  list.unshift(entry);
  list.sort((a, b) => b.updatedAt - a.updatedAt);
  writeProjectList(list);
}

export function removeProjectListEntry(id: string) {
  writeProjectList(readProjectList().filter((e) => e.id !== id));
}

export function getLastProjectId(): string | null {
  try {
    return localStorage.getItem(LS_LAST);
  } catch {
    return null;
  }
}

export function setLastProjectId(id: string | null) {
  try {
    if (id) localStorage.setItem(LS_LAST, id);
    else localStorage.removeItem(LS_LAST);
  } catch {
    /* noop */
  }
}

/** 카메라(MakeFun) 토큰 — localStorage key `makefun_token`. ZIP/내보내기에 절대 넣지 않는다. */
export function getToken(): string {
  try {
    return localStorage.getItem(LS_TOKEN) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string) {
  try {
    if (token) localStorage.setItem(LS_TOKEN, token);
    else localStorage.removeItem(LS_TOKEN);
  } catch {
    /* noop */
  }
}
