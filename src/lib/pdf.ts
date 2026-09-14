/**
 * 인쇄본 PDF — 조판한 페이지들을 한 파일로 묶는다.
 *
 * 라이브러리를 붙이지 않는다: 「JPEG 이미지만 담은 PDF」는 구조가 단순해서(DCTDecode로 원본
 * 바이트를 그대로 품는다) 직접 쓰는 편이 exe 무게·의존성·공급망 위험 어느 쪽으로도 낫다.
 * 압축(zlib)이 필요한 부분이 없으므로 바이트를 계산해 xref만 정확히 적으면 된다.
 *
 * 페이지 크기는 A4 폭(595pt)에 맞추고 높이는 그림 비율을 지킨다 — 조판 페이지는 A4보다
 * 세로로 길기 때문에, 억지로 A4에 끼우면 위아래에 흰 띠가 생기고 컷이 작아진다.
 */

const A4_WIDTH_PT = 595;

/** PNG Blob → JPEG 바이트 (PDF가 그대로 품을 수 있는 형식) */
async function toJpegBytes(page: Blob, quality = 0.9): Promise<{ bytes: Uint8Array; w: number; h: number }> {
  const bmp = await createImageBitmap(page);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = bmp.width;
    canvas.height = bmp.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("이 브라우저에서 Canvas를 쓸 수 없습니다.");
    // JPEG는 투명을 모른다 — 흰 바탕을 먼저 깔아야 검은 여백 설정이 뒤집히지 않는다
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, bmp.width, bmp.height);
    ctx.drawImage(bmp, 0, 0);
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("PDF용 이미지를 만들지 못했습니다."))),
        "image/jpeg",
        quality,
      );
    });
    return { bytes: new Uint8Array(await blob.arrayBuffer()), w: bmp.width, h: bmp.height };
  } finally {
    bmp.close?.();
  }
}

/** PDF 문자열 안에서 특수문자를 피한다 (제목을 그대로 넣기 때문) */
function pdfText(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

/**
 * 페이지 PNG들을 PDF 한 벌로. 페이지 순서는 그대로 유지된다.
 * 반환은 PDF Blob — 호출자가 다운로드한다.
 */
export async function buildPdf(pages: Blob[], title: string): Promise<Blob> {
  if (pages.length === 0) throw new Error("PDF로 만들 페이지가 없습니다.");
  const imgs = await Promise.all(pages.map((p) => toJpegBytes(p)));

  // 객체 번호: 1=Catalog, 2=Pages, 3=Info, 그 뒤로 페이지마다 3개(Page/Contents/Image)
  const pageIds: number[] = [];
  const firstPageObj = 4;
  imgs.forEach((_, i) => pageIds.push(firstPageObj + i * 3));

  const enc = new TextEncoder();
  const parts: Uint8Array[] = [];
  const offsets: number[] = [];
  let length = 0;
  const push = (chunk: string | Uint8Array) => {
    const bytes = typeof chunk === "string" ? enc.encode(chunk) : chunk;
    parts.push(bytes);
    length += bytes.length;
  };
  const startObj = (n: number) => {
    offsets[n] = length;
    push(`${n} 0 obj\n`);
  };
  const endObj = () => push("endobj\n");

  push("%PDF-1.4\n%\u00e2\u00e3\u00cf\u00d3\n");

  startObj(1);
  push("<< /Type /Catalog /Pages 2 0 R >>\n");
  endObj();

  startObj(2);
  push(
    `<< /Type /Pages /Count ${imgs.length} /Kids [${pageIds.map((id) => `${id} 0 R`).join(" ")}] >>\n`,
  );
  endObj();

  startObj(3);
  push(`<< /Title (${pdfText(title)}) /Producer (VN Studio) >>\n`);
  endObj();

  imgs.forEach((img, i) => {
    const pageObj = pageIds[i];
    const contentObj = pageObj + 1;
    const imageObj = pageObj + 2;
    const wPt = A4_WIDTH_PT;
    const hPt = Math.round((img.h / img.w) * A4_WIDTH_PT);

    startObj(pageObj);
    push(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${wPt} ${hPt}] ` +
        `/Resources << /XObject << /Im0 ${imageObj} 0 R >> >> /Contents ${contentObj} 0 R >>\n`,
    );
    endObj();

    const content = `q\n${wPt} 0 0 ${hPt} 0 0 cm\n/Im0 Do\nQ\n`;
    startObj(contentObj);
    push(`<< /Length ${content.length} >>\nstream\n${content}endstream\n`);
    endObj();

    startObj(imageObj);
    push(
      `<< /Type /XObject /Subtype /Image /Width ${img.w} /Height ${img.h} ` +
        `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${img.bytes.length} >>\nstream\n`,
    );
    push(img.bytes);
    push("\nendstream\n");
    endObj();
  });

  const maxObj = firstPageObj + imgs.length * 3 - 1;
  const xrefAt = length;
  push(`xref\n0 ${maxObj + 1}\n`);
  push("0000000000 65535 f \n");
  for (let n = 1; n <= maxObj; n++) {
    const off = offsets[n] ?? 0;
    push(`${String(off).padStart(10, "0")} 00000 n \n`);
  }
  push(
    `trailer\n<< /Size ${maxObj + 1} /Root 1 0 R /Info 3 0 R >>\nstartxref\n${xrefAt}\n%%EOF\n`,
  );

  return new Blob(parts as BlobPart[], { type: "application/pdf" });
}
