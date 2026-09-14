import type { IncomingMessage, ServerResponse } from "node:http";

export declare function proxyMakefun(
  req: IncomingMessage,
  res: ServerResponse,
  splat: string,
): Promise<void>;

export declare function proxyFetchImage(
  req: IncomingMessage,
  res: ServerResponse,
): Promise<void>;
