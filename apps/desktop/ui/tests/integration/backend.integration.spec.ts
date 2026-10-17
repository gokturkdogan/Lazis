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
import { Window } from "happy-dom";
import { ApiError, createApiClient } from "@/api/client";
import { renderMarkdown } from "@/markdown";

const CORE = fileURLToPath(new URL("../../../../../core", import.meta.url));
const PYTHON = join(CORE, ".venv", "bin", "python");

let proc: ChildProcessWithoutNullStreams;
let port = 0;
let root = "";
const token = randomBytes(32).toString("hex");
const key = randomBytes(32).toString("hex");

function startBackend(dataRoot: string, sessionToken: string): Promise<{ child: ChildProcessWithoutNullStreams; port: number }> {
  const child = spawn(
    PYTHON,
    ["-I", "-m", "lazis", "serve", "--stdin-secrets", "--environment", "test",
     "--data-dir", join(dataRoot, "data"), "--log-dir", join(dataRoot, "logs"), "--config", join(dataRoot, "none.toml")],
    { cwd: CORE, env: { HOME: process.env.HOME ?? "", PATH: "/usr/bin:/bin" } },
  );
  child.stdin.write(`${JSON.stringify({ version: 1, session_token: sessionToken, db_key: key })}\n`);
  const lines = createInterface({ input: child.stdout });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("backend did not become ready")), 20_000);
    lines.on("line", (line) => {
      if (line.startsWith("LAZIS_READY ")) {
        clearTimeout(timer);
        resolve({ child, port: JSON.parse(line.slice("LAZIS_READY ".length)).port as number });
      } else if (line.startsWith("LAZIS_FATAL ")) {
        clearTimeout(timer);
        reject(new Error(line));
      }
    });
  });
}

async function stopBackend(child: ChildProcessWithoutNullStreams): Promise<number | null> {
  if (child.exitCode !== null) return child.exitCode;
  const exited = new Promise<number | null>((resolve) => child.once("exit", (code) => resolve(code)));
  child.stdin.end(); // closing the lifeline = graceful shutdown
  return exited;
}

beforeAll(async () => {
  if (!existsSync(PYTHON)) throw new Error(`backend venv missing at ${PYTHON}; run \`make setup\``);
  root = mkdtempSync(join(tmpdir(), "lazis-ui-it-"));
  const started = await startBackend(root, token);
  proc = started.child;
  port = started.port;
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
    expect((await api.appInfo()).phase).toBe("P3");
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

  it("starts as one empty assistant timeline with no conversation management", async () => {
    const api = createApiClient({ port, token });
    const state = await api.assistantState();
    expect(state.session).toBeNull();
    expect(state.timeline_messages).toBe(0);
    expect((await api.timeline(null)).messages).toEqual([]);
    // There is no route to list, rename or delete conversations.
    const res = await fetch(`http://127.0.0.1:${port}/api/v1/conversations/01JZZZZZZZZZZZZZZZZZZZZZZZ`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    expect([404, 405]).toContain(res.status);
  });

  it("serves diagnostics without content (Phase 4)", async () => {
    const api = createApiClient({ port, token });
    const diag = await api.diagnostics();
    expect(diag.prewarm.state).toBe("idle");
    expect(diag.last_turn).toBeNull();
    expect(diag.model.automatic_fallback).toBe(false);
    expect(typeof diag.runtime.available).toBe("boolean");
  });

  // Opt-in (needs Ollama + an installed model): LAZIS_TEST_MODEL=gemma4:12b-it-qat pnpm test:integration
  const liveModel = process.env.LAZIS_TEST_MODEL;
  const MARKER = "Zeytinburnu-7f2";

  it.skipIf(!liveModel)("keeps one continuous conversation with the real model", async () => {
    const api = createApiClient({ port, token }, fetch, 60_000);
    const run = async (content: string, clientId: string) => {
      const events: string[] = [];
      let text = "";
      let cid = "";
      await api.submitTurn(
        { client_id: clientId, content, model: liveModel as string },
        (e) => {
          events.push(e.type === "status" ? `status:${e.stage}` : e.type);
          if (e.type === "start") cid = e.conversation.id;
          if (e.type === "delta") text += e.text;
        },
      );
      return { events, text, cid };
    };
    const first = await run(`Benim mahallemin adı ${MARKER}. Bunu aklında tut ve yalnızca "Tamam" yaz.`, "ui-it-turn-0001");
    expect(first.events[0]).toBe("start");
    expect(first.events).toContain("status:processing_context");
    expect(first.events.at(-1)).toBe("done");
    const second = await run("Mahallemin adı neydi? Yalnızca adı yaz.", "ui-it-turn-0002");
    expect(second.cid).toBe(first.cid); // same assistant, same session — nothing to choose
    expect(second.text).toContain("Zeytinburnu");

    const page = await api.timeline(null);
    expect(page.messages.map((m) => [m.timeline_seq, m.role, m.status])).toEqual([
      [1, "user", "complete"], [2, "assistant", "complete"], [3, "user", "complete"], [4, "assistant", "complete"],
    ]);

    // Stop a long reply: the partial text is kept as "cancelled".
    let deltas = 0;
    await api.submitTurn(
      { client_id: "ui-it-turn-0003", content: "Bana çok uzun bir hikâye anlat.", model: liveModel as string },
      (e) => {
        if (e.type === "delta" && ++deltas === 5) void api.cancelTurn("ui-it-turn-0003");
      },
    );
    const after = await api.timeline(null);
    const last = after.messages.at(-1);
    expect(last?.status).toBe("cancelled");
    expect(last?.content.length).toBeGreaterThan(0);
    expect((await api.assistantState()).session?.id).toBe(first.cid);

    // Phase 4 diagnostics: real timings of the last (cancelled) turn, and no content at all.
    const diag = await api.diagnostics();
    expect(diag.last_turn?.outcome).toBe("cancelled");
    expect(diag.last_turn?.ttft_ms).toBeGreaterThan(0);
    expect(diag.model.loaded?.name).toBe(liveModel);
    expect(JSON.stringify(diag)).not.toContain("Zeytinburnu");

    // A real Markdown reply renders through the safe renderer.
    let reply = "";
    await api.submitTurn(
      {
        client_id: "ui-it-turn-0004",
        content: "Markdown kullanarak: bir başlık, iki maddelik bir liste ve `ls -la` içeren bir bash kod bloğu yaz. Kısa olsun.",
        model: liveModel as string,
      },
      (e) => {
        if (e.type === "delta") reply += e.text;
      },
    );
    const el = new Window().document.createElement("div"); // parse only; nothing runs
    el.innerHTML = renderMarkdown(reply);
    expect(el.querySelector(".code-block pre code")?.textContent).toContain("ls -la");
    expect(el.querySelectorAll("li").length).toBeGreaterThanOrEqual(2);
    expect(el.querySelector("script, img, iframe")).toBeNull();
  }, 600_000);

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

  it.skipIf(!liveModel)("continues the same timeline after the backend restarts (same key)", async () => {
    const restartRoot = mkdtempSync(join(tmpdir(), "lazis-ui-it-restart-"));
    const tokenA = randomBytes(32).toString("hex");
    const tokenB = randomBytes(32).toString("hex");
    try {
      const first = await startBackend(restartRoot, tokenA);
      const apiA = createApiClient({ port: first.port, token: tokenA }, fetch, 60_000);
      let cid = "";
      await apiA.submitTurn(
        { client_id: "ui-it-restart-01", content: "Kuzey projesinin teslim tarihi 15 Aralık. Yalnızca 'Tamam' yaz.", model: liveModel as string },
        (e) => {
          if (e.type === "start") cid = e.conversation.id;
        },
      );
      expect(await stopBackend(first.child)).toBe(0);

      const second = await startBackend(restartRoot, tokenB); // new process, new token, same key
      try {
        const apiB = createApiClient({ port: second.port, token: tokenB }, fetch, 60_000);
        expect((await apiB.assistantState()).session?.id).toBe(cid); // same assistant session
        const page = await apiB.timeline(null);
        expect(page.messages.map((m) => [m.role, m.status])).toEqual([["user", "complete"], ["assistant", "complete"]]);
        let answer = "";
        let session = "";
        await apiB.submitTurn(
          { client_id: "ui-it-restart-02", content: "Teslim tarihi neydi? Yalnızca tarihi yaz.", model: liveModel as string },
          (e) => {
            if (e.type === "start") session = e.conversation.id;
            if (e.type === "delta") answer += e.text;
          },
        );
        expect(session).toBe(cid);
        expect(answer).toContain("15 Aralık");
      } finally {
        await stopBackend(second.child);
      }
    } finally {
      rmSync(restartRoot, { recursive: true, force: true });
    }
  }, 600_000);

  it("shuts down cleanly when the lifeline closes and leaves no secret in the logs", async () => {
    const exited = new Promise<number | null>((resolve) => proc.once("exit", (code) => resolve(code)));
    proc.stdin.end();
    expect(await exited).toBe(0);
    const logs = readFileSync(join(root, "logs", "core.log"), "utf8");
    expect(logs).toContain('"app.stopped"');
    expect(logs).not.toContain(token);
    expect(logs).not.toContain(key);
    expect(logs).not.toContain(MARKER); // conversation text never reaches the logs
  });
});
