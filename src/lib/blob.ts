/**
 * Blob / 파일 유틸.
 *
 * 이미지 업로드 버그 재발 금지 규칙:
 *  1) input onChange에서 FileList를 먼저 Array.from으로 복사
 *  2) 그 다음에야 input.value = ""
 *  3) Blob은 arrayBuffer → new Blob 으로 복제 (iframe/모바일 참조 소실 대비)
 *  4) size > 0 검사
 */

/** FileList를 즉시 배열로 복사하고 input을 리셋한다. 참조를 잃지 않는 유일한 안전 순서. */
export function takeFiles(input: HTMLInputElement): File[] {
  const files = input.files ? Array.from(input.files) : [];
  input.value = "";
  return files;
}

/** arrayBuffer → new Blob 복제. 원본 File 핸들이 무효화돼도 살아남는다. */
export async function cloneImageBlob(src: Blob, fallbackType = "image/jpeg"): Promise<Blob> {
  const buf = await src.arrayBuffer();
  if (buf.byteLength === 0) {
    throw new Error("파일 내용이 비어 있습니다. 다시 선택해 주세요.");
  }
  const type = src.type && src.type.startsWith("image/") ? src.type : fallbackType;
  return new Blob([buf], { type });
}

export function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(new Error("파일을 읽지 못했습니다."));
    r.readAsDataURL(blob);
  });
}

/**
 * 레퍼런스용 JPEG data URL — webp·png·큰 폰 사진을 1536px 이내 JPEG로 맞춘다.
 * 폰 갤러리는 webp나 5MB짜리 원본을 그대로 준다. 그걸 base64로 실으면 요청 하나가 수 MB가 되고,
 * 형식을 안 받는 카메라도 있다 — 그러면 얼굴이 «조용히» 실리지 않는다(사용자 보고: 얼굴이 전송이 안 된다).
 * EXIF 방향을 반영해 그린다(폰 사진은 돌아가 있는 경우가 많다). 디코딩이 안 되면 원본 data URL로 물러난다.
 */
export async function toJpegDataUrl(blob: Blob, maxSide = 1536): Promise<string> {
  try {
    const bmp = await createImageBitmap(blob, { imageOrientation: "from-image" });
    const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    const w = Math.max(1, Math.round(bmp.width * scale));
    const h = Math.max(1, Math.round(bmp.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas 2d 없음");
    ctx.fillStyle = "#ffffff"; // 투명 PNG는 흰 배경 위에
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(bmp, 0, 0, w, h);
    bmp.close();
    return canvas.toDataURL("image/jpeg", 0.92);
  } catch {
    return blobToDataUrl(blob);
  }
}

/** 파일 저장 (a[download] 클릭). */
export function downloadBlob(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

/** 파일명에 못 쓰는 문자를 정리. */
export function safeFileName(name: string): string {
  return name.replace(/[\\/:*?"<>|]+/g, "_").trim() || "project";
}
