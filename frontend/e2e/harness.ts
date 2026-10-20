/**
 * Phase 56 end-to-end harness: the real Next.js production server (the built app, started with
 * `next start`) talking over real HTTP to the read-only mock API in `mock-api.ts`.
 *
 * It needs a production build (`pnpm build`) and starts nothing else: no database, no Redis, no
 * Docker, no scheduler. The child process gets a minimal environment (no `.env`, no credentials).
 */
import { type ChildProcess, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createServer } from "node:net";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

import { JSDOM } from "jsdom";

import { type MockApi, startMockApi } from "./mock-api";

const ROOT = join(__dirname, "..");

export type Page = { status: number; html: string; doc: Document };

export type Stack = {
  api: MockApi;
  baseUrl: string;
  get: (path: string) => Promise<Page>;
  streamChunks: (path: string) => Promise<string[]>;
  logs: () => string;
  stop: () => Promise<void>;
};

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      const port = typeof address === "object" && address ? address.port : 0;
      probe.close(() => resolve(port));
    });
  });
}

export async function startStack(): Promise<Stack> {
  if (!existsSync(join(ROOT, ".next", "BUILD_ID"))) {
    throw new Error("No production build found. Run `pnpm build` before `pnpm test:e2e`.");
  }
  const api = await startMockApi();
  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  let output = "";
  const child: ChildProcess = spawn(
    process.execPath,
    [
      join(ROOT, "node_modules", "next", "dist", "bin", "next"),
      "start",
      "-p",
      String(port),
      "-H",
      "127.0.0.1",
    ],
    {
      cwd: ROOT,
      env: {
        PATH: process.env.PATH ?? "",
        HOME: process.env.HOME ?? "",
        NODE_ENV: "production",
        NEXT_TELEMETRY_DISABLED: "1",
        API_INTERNAL_URL: api.url,
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  child.stdout?.on("data", (d: Buffer) => (output += d.toString()));
  child.stderr?.on("data", (d: Buffer) => (output += d.toString()));

  const stop = async () => {
    child.kill("SIGTERM");
    await Promise.race([new Promise((r) => child.once("exit", r)), sleep(5000)]);
    await api.close();
  };

  const deadline = Date.now() + 60_000;
  for (;;) {
    try {
      if ((await fetch(`${baseUrl}/healthz`)).ok) break;
    } catch {
      /* not up yet */
    }
    if (child.exitCode !== null || Date.now() > deadline) {
      await stop();
      throw new Error(`The Next.js server did not become ready.\n${output}`);
    }
    await sleep(250);
  }

  const get = async (path: string): Promise<Page> => {
    const response = await fetch(`${baseUrl}${path}`, { redirect: "manual" });
    const html = await response.text();
    return { status: response.status, html, doc: new JSDOM(html).window.document };
  };

  const streamChunks = async (path: string): Promise<string[]> => {
    const response = await fetch(`${baseUrl}${path}`);
    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    const chunks: string[] = [];
    if (!reader) return chunks;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(decoder.decode(value, { stream: true }));
    }
    return chunks;
  };

  return { api, baseUrl, get, streamChunks, logs: () => output, stop };
}
