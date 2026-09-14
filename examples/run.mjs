/** verify.mjs를 esbuild로 인메모리 번들 후 실행 — 임시파일·쉘 의존 없음(크로스플랫폼). */
import { build } from "esbuild";
import path from "node:path";

const entry = path.resolve(process.cwd(), "examples/verify.mjs");
const result = await build({
  entryPoints: [entry],
  bundle: true,
  platform: "node",
  format: "esm",
  write: false,
  logLevel: "error",
});
const code = result.outputFiles[0].text;
await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));
