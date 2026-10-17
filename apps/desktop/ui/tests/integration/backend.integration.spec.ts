/**
 * Frontend ↔ backend communication against the real Python backend (no mocks): the UI's API
 * client talks to `python -m lazis serve` started exactly like the Rust shell starts it.
 */
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ApiError, createApiClient } from "@/api/client";

const CORE = fileURLToPath(new URL("../../../../../core", import.meta.url));
const PYTHON = join(CORE, ".venv", "bin", "python");

let proc: ChildProcessWithoutNullStreams;
let port = 0;
let root = "";
const token = randomBytes(32).toString("hex");
const key = randomBytes(32).toString("hex");

beforeAll(async () => {
  if (!existsSync(PYTHON)) throw new Error(`backend venv missing at ${PYTHON}; run \`just setup\``);
  root = mkdtempSync(join(tmpdir(), "lazis-ui-it-"));
  proc = spawn(
    PYTHON,
    ["-I", "-m", "lazis", "serve", "--stdin-secrets", "--environment", "test",
     "--data-dir", join(root, "data"), "--log-dir", join(root, "logs"), "--config", join(root, "none.toml")],
    { cwd: CORE, env: { HOME: process.env.HOME ?? "", PATH: "/usr/bin:/bin" } },
  );
  proc.stdin.write(`${JSON.stringify({ version: 1, session_token: token, db_key: key })}\n`);
  const lines = createInterface({ input: proc.stdout });
  port = await new Promise<number>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("backend did not become ready")), 20_000);
    lines.on("line", (line) => {
      if (line.startsWith("LAZIS_READY ")) {
        clearTimeout(timer);
        resolve(JSON.parse(line.slice("LAZIS_READY ".length)).port as number);
      } else if (line.startsWith("LAZIS_FATAL ")) {
        clearTimeout(timer);
        reject(new Error(line));
      }
    });
  });
});

afterAll(async () => {
  if (proc && proc.exitCode === null) {
    const exited = new Promise((resolve) => proc.once("exit", resolve));
    proc.stdin.end(); // closing the lifeline = graceful shutdown
    await exited;
  }
  if (root) rmSync(root, { recursive: true, force: true });
});

describe("UI API client ↔ real backend", () => {
  it("reads health, app info and verified encryption status", async () => {
    const api = createApiClient({ port, token });
    expect((await api.health()).status).toBe("ok");
    expect((await api.appInfo()).phase).toBe("P2");
    const status = await api.systemStatus();
    expect(status.database.encrypted).toBe(true);
    expect(status.database.encryption_verified).toBe(true);
    expect(status.privacy.research_mode).toBe("offline_only");
    expect((await api.settings()).network_egress_enabled).toBe(false);
  });

  it("is rejected with a wrong token", async () => {
    const api = createApiClient({ port, token: "0".repeat(64) });
    const error = await api.health().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).userMessage).toBe("Yetkisiz istek.");
  });

  it("reports the local model runtime without any cloud inference", async () => {
    const api = createApiClient({ port, token });
    const status = await api.llmStatus();
    expect(status.cloud_inference).toBe("disabled");
    expect(typeof status.runtime.available).toBe("boolean");
    if (status.runtime.available) {
      const models = (await api.models()).models;
      expect(models.every((m) => !m.name.includes("cloud"))).toBe(true);
    }
  });

  // Opt-in (needs Ollama + an installed model): LAZIS_TEST_MODEL=qwen3.5:9b-q4_K_M pnpm test:integration
  const liveModel = process.env.LAZIS_TEST_MODEL;
  it.skipIf(!liveModel)("streams a Turkish answer from the real model and can cancel it", async () => {
    const api = createApiClient({ port, token }, fetch, 60_000);
    const events: string[] = [];
    let text = "";
    await api.chatStream(
      { model: liveModel as string, request_id: "ui-it-0001",
        messages: [{ role: "user", content: "Türkiye'nin başkenti neresidir? Tek kelimeyle yaz." }] },
      (e) => {
        events.push(e.type);
        if (e.type === "delta") text += e.text;
      },
    );
    expect(events[0]).toBe("start");
    expect(events.at(-1)).toBe("done");
    expect(text.toLowerCase()).toContain("ankara");

    const seen: string[] = [];
    let deltas = 0;
    await api.chatStream(
      { model: liveModel as string, request_id: "ui-it-0002",
        messages: [{ role: "user", content: "Bana çok uzun bir hikâye anlat." }] },
      (e) => {
        seen.push(e.type === "error" ? `error:${e.code}` : e.type);
        if (e.type === "delta" && ++deltas === 5) void api.cancelChat("ui-it-0002");
      },
    );
    expect(seen.at(-1)).toBe("error:llm_cancelled");
  }, 300_000);

  it("shuts down cleanly when the lifeline closes and leaves no secret in the logs", async () => {
    const exited = new Promise<number | null>((resolve) => proc.once("exit", (code) => resolve(code)));
    proc.stdin.end();
    expect(await exited).toBe(0);
    const logs = readFileSync(join(root, "logs", "core.log"), "utf8");
    expect(logs).toContain('"app.stopped"');
    expect(logs).not.toContain(token);
    expect(logs).not.toContain(key);
  });
});
