/**
 * 비주얼노벨 스튜디오 — 단일 실행 서버 (exe 패키징용).
 *
 * dist/ 정적 파일 + MakeFun/이미지 프록시(공용 구현은 proxy-core.cjs).
 * 포트는 5173 고정: IndexedDB/localStorage가 origin(호스트:포트)에 묶여 있어,
 * 포트가 바뀌면 기존 프로젝트가 보이지 않게 되기 때문이다.
 *
 * 0.0.0.0에 바인딩 — 같은 Wi-Fi의 폰에서 http://<PC IP>:5173 로 접속할 수 있다.
 * (폰의 작업본은 폰 브라우저에 저장된다. 기기 간 이동은 필름캔 ZIP으로.)
 */
"use strict";

const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { exec } = require("child_process");
const { proxyMakefun, proxyFetchImage } = require("./proxy-core.cjs");
const { version } = require("./package.json");

const PORT = 5173;
const DIST = path.join(__dirname, "dist");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".woff2": "font/woff2",
};

function serveStatic(req, res) {
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(req.url || "/", "http://x").pathname);
  } catch {
    pathname = "/";
  }
  let file = path.normalize(path.join(DIST, pathname));
  if (!file.startsWith(DIST)) {
    res.statusCode = 403;
    res.end("Forbidden");
    return;
  }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    file = path.join(DIST, "index.html"); // SPA 폴백
  }
  try {
    const buf = fs.readFileSync(file);
    res.statusCode = 200;
    res.setHeader(
      "content-type",
      MIME[path.extname(file).toLowerCase()] || "application/octet-stream",
    );
    res.end(buf);
  } catch {
    res.statusCode = 404;
    res.end("Not Found");
  }
}

const server = http.createServer((req, res) => {
  const url = req.url || "/";
  if (url.startsWith("/api/makefun/")) {
    const splat = url.slice("/api/makefun/".length).replace(/^\/+/, "");
    void proxyMakefun(req, res, splat);
    return;
  }
  if (url === "/api/fetch-image" || url.startsWith("/api/fetch-image?")) {
    void proxyFetchImage(req, res);
    return;
  }
  serveStatic(req, res);
});

/** 같은 Wi-Fi의 폰이 접속할 수 있는 이 PC의 IPv4 주소들. */
function lanAddresses() {
  const out = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const info of list || []) {
      if (info.family === "IPv4" && !info.internal) out.push(info.address);
    }
  }
  return out;
}

server.on("error", (err) => {
  if (err && err.code === "EADDRINUSE") {
    console.log("");
    console.log("  이미 비주얼노벨 스튜디오가 켜져 있는 것 같습니다.");
    console.log("  브라우저를 열어 드릴게요. 이 창은 곧 닫힙니다.");
    exec(`start "" "http://localhost:${PORT}/"`);
    setTimeout(() => process.exit(0), 2500);
  } else {
    console.error("서버를 시작하지 못했습니다:", err);
    setTimeout(() => process.exit(1), 5000);
  }
});

server.listen(PORT, "0.0.0.0", () => {
  const line = (s) => `  │ ${s.padEnd(45)}│`;
  console.log("");
  console.log("  ┌──────────────────────────────────────────────┐");
  console.log(line(`🎬  비주얼노벨 스튜디오  v${version}`));
  console.log(line(""));
  console.log(line(`이 컴퓨터:  http://localhost:${PORT}/`));
  for (const ip of lanAddresses()) {
    console.log(line(`폰(같은 Wi-Fi): http://${ip}:${PORT}/`));
  }
  console.log(line(""));
  console.log(line("이 창을 닫으면 스튜디오가 꺼집니다."));
  console.log(line("중요한 작품은 필름캔(ZIP)으로 내보내 두세요."));
  console.log("  └──────────────────────────────────────────────┘");
  console.log("");
  exec(`start "" "http://localhost:${PORT}/"`);
});
