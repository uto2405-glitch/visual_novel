/** 프록시 경로와 계열별 시작 본문. name은 반드시 sceneId — id 유실 시 복구 검색 키. */
import type { SizeKey } from "../../types";
import { SIZES, type CameraModel, type Family, type ModelId } from "./models";

function familyPath(family: Family): string {
  switch (family) {
    case "flux":
      return "userFlux2";
    case "nano":
      return "userNanoBanana";
    case "gpt":
      return "userGptImage";
    case "qwen":
      return "userQwen2Image";
    case "kling":
      return "userKlingImage";
    case "seedream":
      return "userText2Image";
    case "editor":
      return "userImageEdit";
    default:
      return "userWan27Image";
  }
}

export function startPath(model: CameraModel): string {
  return `/api/makefun/${familyPath(model.family)}/start`;
}

/** detail 경로 후보 — 계열마다 detail/{id} 또는 /{id}가 섞여 있어 둘 다 시도한다. */
export function detailPaths(model: CameraModel, id: string): string[] {
  const fam = familyPath(model.family);
  const enc = encodeURIComponent(id);
  if (model.family === "seedream" || model.family === "editor") {
    return [`/api/makefun/${fam}/${enc}`, `/api/makefun/${fam}/detail/${enc}`];
  }
  return [`/api/makefun/${fam}/detail/${enc}`, `/api/makefun/${fam}/${enc}`];
}

export function listPaths(model: CameraModel): string[] {
  const fam = familyPath(model.family);
  return [`/api/makefun/${fam}/allRecords`, `/api/makefun/${fam}/list`];
}

/**
 * 실제 API 계약 (2026-08-29 실측): model_type enum은 `a2e | zimage | seedream`뿐이고
 * 시드림 세대는 별도의 model_version으로 구분한다. 성공 레코드 기준 5 Pro = "5.0-pro".
 */
function seedreamVersion(id: ModelId): string {
  if (id === "seedream-5-pro") return "5.0-pro";
  if (id === "seedream-5") return "5.0";
  return "4.5";
}

export function buildBody(
  model: CameraModel,
  sceneId: string,
  prompt: string,
  inputImages: string[],
  size: SizeKey,
): Record<string, unknown> {
  // 정사각 촬영(인쇄본 2×2용) — Seedream에서 1024×1024 실측 확인
  const ratio = size === "sq" ? "1:1" : "16:9";
  switch (model.family) {
    case "flux":
      return {
        name: sceneId,
        prompt,
        input_images: inputImages,
        aspect_ratio: ratio,
        resolution: "1K",
        force_generate: false,
      };
    case "nano":
      return {
        name: sceneId,
        prompt,
        model: "nano-banana-pro",
        input_images: inputImages,
        aspect_ratio: ratio,
        image_size: size === "2k" ? "2K" : "1K",
        force_generate: false,
      };
    case "gpt":
      return {
        name: sceneId,
        prompt,
        model: "gpt-image-2",
        input_images: inputImages,
        aspect_ratio: ratio,
        quality: "high",
        resolution: size === "2k" ? "2K" : "1K",
        force_generate: false,
      };
    case "qwen":
      return {
        name: sceneId,
        prompt,
        model: "qwen-image-2.0",
        input_images: inputImages,
        size: "1280*720",
      };
    case "kling":
      return {
        name: sceneId,
        prompt,
        input_images: inputImages,
        aspect_ratio: ratio,
        resolution: "1k",
        n: 1,
      };
    case "seedream": {
      const s = SIZES[size];
      return {
        name: sceneId,
        prompt,
        width: s.w,
        height: s.h,
        model_type: "seedream",
        model_version: seedreamVersion(model.id),
        input_images: inputImages,
        aspect_ratio: ratio,
        max_images: 1,
      };
    }
    case "editor":
      return {
        name: sceneId,
        edit_type: "clothing",
        image_urls: inputImages.slice(0, 8),
        timeout: 120,
      };
    default:
      return {
        name: sceneId,
        prompt,
        model: model.id === "wan2.7-image-pro" ? "wan2.7-image-pro" : "wan2.7-image",
        input_images: inputImages,
        aspect_ratio: ratio,
        force_generate: false,
      };
  }
}
