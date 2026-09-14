/** placeholder: true 컷의 단색 이미지. API를 부르지 않는다. */

const PALETTE = [
  "#232028",
  "#1f262b",
  "#2b2126",
  "#202821",
  "#282420",
  "#212030",
  "#2d2530",
  "#1e2c2c",
  "#302322",
  "#242e24",
];

function hashCode(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export async function makePlaceholderBlob(sceneId: string): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = 1280;
  canvas.height = 720;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("캔버스를 만들 수 없습니다.");
  ctx.fillStyle = PALETTE[hashCode(sceneId) % PALETTE.length];
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("이미지 생성 실패"))), "image/png");
  });
}
