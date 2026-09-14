/** 카메라(MakeFun) 필름 목록 — 모델·크기·크레딧 레지스트리. */
import type { SizeKey } from "../../types";

export type ModelId =
  | "seedream-5-pro"
  | "seedream-5"
  | "seedream-4.5"
  | "wan2.7-image"
  | "wan2.7-image-pro"
  | "flux-2"
  | "nano-banana-pro"
  | "gpt-image-2"
  | "qwen-image-2.0"
  | "kling-image"
  | "image-editor";

export type Family =
  | "wan"
  | "flux"
  | "nano"
  | "gpt"
  | "qwen"
  | "kling"
  | "seedream"
  | "editor";

export interface SizeInfo {
  key: SizeKey;
  label: string;
  w: number;
  h: number;
}

export const SIZES: Record<SizeKey, SizeInfo> = {
  "1k": { key: "1k", label: "1K 16:9", w: 1280, h: 720 },
  "2k": { key: "2k", label: "2K 16:9", w: 1920, h: 1080 },
  sq: { key: "sq", label: "1:1 정사각", w: 1024, h: 1024 },
};

export interface CameraModel {
  id: ModelId;
  label: string;
  hint: string;
  family: Family;
  /** 이 모델이 지원하는 크기만 노출한다 */
  sizes: SizeKey[];
  /** 컷당 예상 크레딧 (MakeFun 크레딧, LLM 토큰 아님). 미상은 비워둔다 */
  credits: Partial<Record<SizeKey, number>>;
  group: "image" | "edit";
  discouraged?: boolean;
}

export const DEFAULT_MODEL: ModelId = "seedream-5-pro";

export const CAMERA_MODELS: CameraModel[] = [
  {
    id: "seedream-5-pro",
    label: "Seedream 5 Pro",
    hint: "기본 카메라 · 검열에 가장 강함",
    family: "seedream",
    sizes: ["1k", "2k", "sq"],
    // 실측(2026-08-30·31, 7컷): 1280×720과 1024×1024 모두 응답 coins = 12.
    // 2k는 아직 실측하지 않아 보수적으로 남겨둔다(과소 표시보다 과대 표시가 안전하다).
    credits: { "1k": 12, "2k": 36, sq: 12 },
    group: "image",
  },
  {
    id: "seedream-5",
    label: "Seedream 5",
    hint: "시드림 5",
    family: "seedream",
    sizes: ["1k", "2k", "sq"],
    credits: { "1k": 20, "2k": 28, sq: 20 },
    group: "image",
  },
  {
    id: "seedream-4.5",
    label: "Seedream 4.5",
    hint: "시드림 4.5",
    family: "seedream",
    sizes: ["1k", "2k", "sq"],
    credits: { "1k": 15, "2k": 22, sq: 15 },
    group: "image",
  },
  {
    id: "wan2.7-image",
    label: "Wan 2.7 Image",
    hint: "얼굴이 깨진 컷의 대안",
    family: "wan",
    sizes: ["1k"],
    credits: { "1k": 12 },
    group: "image",
  },
  {
    id: "wan2.7-image-pro",
    label: "Wan 2.7 Image Pro",
    hint: "Wan 고품질",
    family: "wan",
    sizes: ["1k"],
    credits: { "1k": 18 },
    group: "image",
  },
  {
    id: "flux-2",
    label: "Flux 2",
    hint: "레퍼런스 합성에 강함",
    family: "flux",
    sizes: ["1k"],
    credits: { "1k": 14 },
    group: "image",
  },
  {
    id: "nano-banana-pro",
    label: "Nano Banana Pro",
    hint: "얼굴 레퍼런스에 강함",
    family: "nano",
    sizes: ["1k", "2k"],
    credits: { "1k": 16, "2k": 24 },
    group: "image",
  },
  {
    id: "gpt-image-2",
    label: "GPT Image 2",
    hint: "프롬프트 이해도가 높음",
    family: "gpt",
    sizes: ["1k", "2k"],
    credits: { "1k": 20, "2k": 32 },
    group: "image",
  },
  {
    id: "qwen-image-2.0",
    label: "Qwen Image 2.0",
    hint: "문장·한자 표현에 강함",
    family: "qwen",
    sizes: ["1k"],
    credits: {},
    group: "image",
  },
  {
    id: "kling-image",
    label: "Kling Image",
    hint: "시네마틱 정지 화면",
    family: "kling",
    sizes: ["1k"],
    credits: {},
    group: "image",
  },
  {
    id: "image-editor",
    label: "Image Editor",
    hint: "의상/제품 편집용 · 장면 컷에는 비권장",
    family: "editor",
    sizes: ["1k"],
    credits: {},
    group: "edit",
    discouraged: true,
  },
];

export function modelById(id: string | undefined): CameraModel {
  return CAMERA_MODELS.find((m) => m.id === id) ?? CAMERA_MODELS[0];
}

export function creditsOf(model: CameraModel, size: SizeKey): number | null {
  return model.credits[size] ?? null;
}

/** `Seedream 5 Pro · 1K 1280×720 · 컷당 예상 28 크레딧 · 이번 8컷 약 224` */
export function creditLine(model: CameraModel, size: SizeKey, count: number): string {
  const s = SIZES[size];
  const per = creditsOf(model, size);
  const head = `${model.label} · ${s.label.split(" ")[0]} ${s.w}×${s.h}`;
  if (per == null) {
    return `${head} · 크레딧 정보 없음 · 이번 ${count}컷`;
  }
  return `${head} · 컷당 예상 ${per} 크레딧 · 이번 ${count}컷 약 ${per * count}`;
}
