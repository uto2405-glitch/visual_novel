/**
 * MakeFun 프록시 코어 — dev(vite.config.ts)와 exe(server.cjs)가 공유하는 유일한 구현.
 * 의존성 없음(Node 내장만). 두 곳에 복제되어 있던 로직을 여기로 합쳤다.
 *
 * - proxyMakefun: `/api/makefun/<family>/<action>` → `https://makefun.ai/api/v1/...`
 *   Authorization은 요청 헤더를 그대로 전달할 뿐, 어디에도 저장하지 않는다.
 * - proxyFetchImage: 생성 결과 CDN URL을 서버에서 받아 돌려준다.
 *   리다이렉트는 수동으로 따라가며 매 홉 내부 주소를 검사한다 (SSRF 차단).
 */
"use strict";

const MAKEFUN_ORIGIN = "https://makefun.ai";

const FAMILIES = [
  "userWan27Image",
  "userFlux2",
  "userImageEdit",
  "userNanoBanana",
  "userGptImage",
  "userQwen2Image",
  "userKlingImage",
  "userText2Image",
  "userImage2Video", // 무빙 컷 (실험)
];

// start / detail/{id} / allRecords / list / {id} (Seedream 계열의 detail 폴백 — 짧은 숫자 id 포함)
const ACTION_RE = /^(start|detail\/[A-Za-z0-9_-]+|allRecords|list|[A-Za-z0-9_-]+)(\?.*)?$/;

const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const MAX_VIDEO_BYTES = 80 * 1024 * 1024; // 무빙 컷 결과 영상
const MAX_REDIRECT_HOPS = 5;

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function sendJson(res, status, body) {
  res.statusCode = status;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
}

function isPrivateHost(host) {
  const h = String(host).toLowerCase();
  if (
    h === "localhost" ||
    h === "0.0.0.0" ||
    h === "::1" ||
    h === "[::1]" ||
    h.endsWith(".local") ||
    h.endsWith(".internal")
  ) {
    return true;
  }
  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (!ipv4) return false;
  const a = Number(ipv4[1]);
  const b = Number(ipv4[2]);
  if (a === 10 || a === 127 || a === 0) return true;
  if (a === 169 && b === 254) return true;
  if (a === 192 && b === 168) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  return false;
}

/** `/api/makefun/` 뒤의 경로(splat)를 받아 업스트림으로 전달한다. */
async function proxyMakefun(req, res, splat) {
  const family = splat.split("/", 1)[0] || "";
  const action = splat.slice(family.length + 1);
  if (!FAMILIES.includes(family) || !ACTION_RE.test(action)) {
    sendJson(res, 400, { error: "허용되지 않은 카메라 경로입니다." });
    return;
  }
  const auth = String(req.headers["authorization"] || "");
  if (!auth.toLowerCase().startsWith("bearer ")) {
    sendJson(res, 401, { error: "카메라 토큰이 필요합니다." });
    return;
  }
  const headers = { Authorization: auth };
  if (typeof req.headers["content-type"] === "string") {
    headers["Content-Type"] = req.headers["content-type"];
  }
  const init = { method: req.method || "GET", headers };
  if (req.method !== "GET" && req.method !== "HEAD") {
    const body = await readBody(req);
    if (body.length > 0) init.body = new Uint8Array(body);
  }
  try {
    const upstream = await fetch(`${MAKEFUN_ORIGIN}/api/v1/${splat}`, init);
    const buf = Buffer.from(await upstream.arrayBuffer());
    res.statusCode = upstream.status;
    const ct = upstream.headers.get("content-type");
    if (ct) res.setHeader("content-type", ct);
    res.end(buf);
  } catch (err) {
    sendJson(res, 502, {
      error: "카메라(MakeFun)와 연결하지 못했습니다.",
      detail: err instanceof Error ? err.message : String(err),
    });
  }
}

/** POST {url} — 결과 이미지를 대신 받아온다. raw 상태 숫자는 사용자에게 노출하지 않는다. */
async function proxyFetchImage(req, res) {
  if (req.method !== "POST") {
    sendJson(res, 405, { error: "POST만 허용합니다." });
    return;
  }
  let url;
  try {
    const body = JSON.parse((await readBody(req)).toString("utf8"));
    url = String(body.url || "");
  } catch {
    sendJson(res, 400, { error: "잘못된 요청입니다." });
    return;
  }
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    sendJson(res, 400, { error: "올바르지 않은 URL입니다." });
    return;
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    sendJson(res, 400, { error: "http(s) URL만 허용합니다." });
    return;
  }
  if (isPrivateHost(parsed.hostname)) {
    sendJson(res, 400, { error: "내부 주소는 허용되지 않습니다." });
    return;
  }
  try {
    let current = parsed;
    let upstream = null;
    for (let hop = 0; hop < MAX_REDIRECT_HOPS; hop++) {
      const r = await fetch(current, { redirect: "manual" });
      if (r.status >= 300 && r.status < 400) {
        const loc = r.headers.get("location");
        if (!loc) break;
        const next = new URL(loc, current);
        if (next.protocol !== "https:" && next.protocol !== "http:") {
          sendJson(res, 400, { error: "http(s) URL만 허용합니다." });
          return;
        }
        if (isPrivateHost(next.hostname)) {
          sendJson(res, 400, { error: "내부 주소는 허용되지 않습니다." });
          return;
        }
        current = next;
        continue;
      }
      upstream = r;
      break;
    }
    if (!upstream) {
      sendJson(res, 502, { error: "리다이렉트가 너무 많아 그림을 받지 못했습니다." });
      return;
    }
    if (!upstream.ok) {
      const friendly =
        upstream.status === 403 || upstream.status === 404 || upstream.status === 410
          ? "원본 이미지 주소가 만료되었거나 접근이 막혔습니다. 이 컷을 다시 찍거나 URL을 새로 복사해 주세요."
          : "원본 이미지를 받지 못했습니다. 잠시 후 다시 시도해 주세요.";
      sendJson(res, 502, { error: friendly, detail: String(upstream.status) });
      return;
    }
    const buf = Buffer.from(await upstream.arrayBuffer());
    const ct = upstream.headers.get("content-type") || "image/png";
    const isVideo = ct.startsWith("video/") || /\.(mp4|webm|mov)(\?|$)/i.test(current.pathname);
    if (buf.length > (isVideo ? MAX_VIDEO_BYTES : MAX_IMAGE_BYTES)) {
      sendJson(res, 413, { error: isVideo ? "영상이 너무 큽니다." : "이미지가 너무 큽니다." });
      return;
    }
    res.statusCode = 200;
    res.setHeader(
      "content-type",
      ct.startsWith("image/") || ct.startsWith("video/") ? ct : isVideo ? "video/mp4" : "image/png",
    );
    res.end(buf);
  } catch (err) {
    sendJson(res, 502, {
      error: "이미지 다운로드에 실패했습니다.",
      detail: err instanceof Error ? err.message : String(err),
    });
  }
}

module.exports = { proxyMakefun, proxyFetchImage };
