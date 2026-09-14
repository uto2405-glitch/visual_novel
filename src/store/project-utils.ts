/** 프로젝트 레코드 생성/집계 — 순수 함수. */
import * as db from "../lib/db";
import { DEFAULT_MODEL } from "../lib/makefun";
import { countCutStatus, type ProjectListEntry, type ProjectRecord, type Story } from "../types";

export function newProjectId(): string {
  return `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

export function makeProject(story: Story, title?: string): ProjectRecord {
  const now = Date.now();
  return {
    id: newProjectId(),
    title: title ?? story.title ?? "무제",
    story,
    cuts: {},
    charAssets: {},
    camera: { model: DEFAULT_MODEL, size: "1k" },
    currentSceneId: null,
    createdAt: now,
    updatedAt: now,
  };
}

export function listEntryOf(p: ProjectRecord): ProjectListEntry {
  return {
    id: p.id,
    title: p.title,
    sceneCount: p.story.scenes.length,
    okCount: countCutStatus(p).ok,
    updatedAt: p.updatedAt,
    ...(p.lastExportAt ? { lastExportAt: p.lastExportAt } : {}),
    // 크레딧 장부의 사본 — 0이어도 «세어 봤다»는 뜻이므로 함께 싣는다
    coinsSpent: p.coinsSpent ?? 0,
  };
}

/** 생성/테이크 이미지의 asset 키 — 시각+난수로 유일성 보장. */
export function genKey(projectId: string, sceneId: string): string {
  return db.assetKey(
    projectId,
    "gen",
    `${sceneId}:${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
  );
}
