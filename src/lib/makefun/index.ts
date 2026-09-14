/**
 * 카메라(MakeFun) 패키지의 공개 표면.
 * 소비자(store, Stage, Screening)는 `../lib/makefun` 경로 그대로 쓴다.
 * 응답 파서(extract*)는 내부 구현 — 여기서 재수출하지 않는다.
 */
export {
  CAMERA_MODELS,
  DEFAULT_MODEL,
  SIZES,
  creditLine,
  creditsOf,
  modelById,
  type CameraModel,
  type ModelId,
  type SizeInfo,
} from "./models";
export { MakefunError, type ErrorKind } from "./errors";
export {
  checkCamera,
  downloadResultImage,
  findRecentRecord,
  findRecentResult,
  type CameraCheck,
  shootCut,
  type ShootInput,
  type ShootResult,
} from "./client";
export { makeMovingVideo, downloadVideo, VIDEO_EXT_RE } from "./video";
