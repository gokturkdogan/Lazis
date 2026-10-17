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
    expect((await api.appInfo()).phase).toBe("P1");
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
