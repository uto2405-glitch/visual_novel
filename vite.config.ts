import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import type { IncomingMessage, ServerResponse } from "node:http";
import { proxyFetchImage, proxyMakefun } from "./proxy-core.cjs";

/**
 * MakeFun 프록시 (dev + preview 공용).
 * 실제 로직은 exe(server.cjs)와 공유하는 proxy-core.cjs 한 곳에 있다.
 * `server.host: true` — 같은 Wi-Fi의 폰에서 dev 서버로 접속할 수 있게 한다.
 */

function attach(middlewares: {
  use: (route: string, fn: (req: IncomingMessage, res: ServerResponse) => void) => void;
}) {
  middlewares.use("/api/makefun", (req, res) => {
    const splat = String(req.url ?? "").replace(/^\/+/, "");
    void proxyMakefun(req, res, splat);
  });
  middlewares.use("/api/fetch-image", (req, res) => {
    void proxyFetchImage(req, res);
  });
}

function makefunProxy(): Plugin {
  return {
    name: "vn-makefun-proxy",
    configureServer(server) {
      attach(server.middlewares);
    },
    configurePreviewServer(server) {
      attach(server.middlewares);
    },
  };
}

export default defineConfig({
  plugins: [react(), makefunProxy()],
  server: { host: true },
  preview: { host: true },
});
