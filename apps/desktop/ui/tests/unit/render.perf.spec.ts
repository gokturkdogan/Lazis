/**
 * Phase 4 UI render cost (indicative: happy-dom in Node, not WebKit). Opt-in:
 *   LAZIS_UI_PERF=1 pnpm vitest run --config vitest.config.ts ui/tests/unit/render.perf.spec.ts
 * Writes evals/reports/phase4/ui_render.json.
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";
import { createAppI18n } from "@/i18n";
import { renderMarkdown } from "@/markdown";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import AssistantView from "@/views/AssistantView.vue";
import { connection, fakeClient, fakePlatform, messageFixture } from "./fixtures";

const run = process.env.LAZIS_UI_PERF === "1";

function longReply(paragraphs: number): string {
  const parts: string[] = [];
  for (let i = 0; i < paragraphs; i++) {
    parts.push(`## Bölüm ${i + 1}`, "Bu bölümde **önemli** noktalar ve `kod` örnekleri var. ".repeat(6));
    parts.push("- birinci madde\n- ikinci madde\n- üçüncü madde");
    if (i % 3 === 0) parts.push("```python\n" + "print('merhaba')\n".repeat(12) + "```");
    if (i % 4 === 0) parts.push("| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |");
  }
  return parts.join("\n\n");
}

function median(values: number[]): number {
  const s = [...values].sort((a, b) => a - b);
  return Math.round((s[Math.floor(s.length / 2)] ?? 0) * 100) / 100;
}

describe.skipIf(!run)("UI render cost", () => {
  it("measures Markdown, a long timeline and streaming updates", async () => {
    const result: Record<string, unknown> = { environment: "happy-dom (Node), indicative only" };

    const reply = longReply(24); // ~3,000 words
    const times: number[] = [];
    for (let i = 0; i < 20; i++) {
      const t0 = performance.now();
      renderMarkdown(reply);
      times.push(performance.now() - t0);
    }
    result.markdown_long_reply = { chars: reply.length, median_ms: median(times) };

    const pinia = createPinia();
    setActivePinia(pinia);
    const messages = Array.from({ length: 200 }, (_, i) =>
      messageFixture(i + 1, i % 2 === 0 ? "user" : "assistant", i % 2 === 0 ? "Kısa bir soru?" : longReply(2)),
    );
    const client = fakeClient({ timeline: vi.fn().mockResolvedValue({ messages, has_more: true }) });
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
    const t0 = performance.now();
    const wrapper = mount(AssistantView, { global: { plugins: [pinia, createAppI18n()] } });
    await flushPromises();
    result.mount_200_messages_ms = Math.round(performance.now() - t0);
    expect(wrapper.findAll('[data-testid="message-assistant"]')).toHaveLength(100);

    // Streaming: 500 deltas into the last reply (plain text while streaming).
    const store = useAssistantStore();
    store.messages.push(messageFixture(201, "assistant", "", { status: "streaming", metrics: null }));
    await flushPromises();
    const reply201 = store.messages[store.messages.length - 1];
    const deltas: number[] = [];
    for (let i = 0; i < 500; i++) {
      const s = performance.now();
      if (reply201) reply201.content += "kelime ";
      await flushPromises();
      deltas.push(performance.now() - s);
    }
    result.streaming_delta_update = { deltas: 500, median_ms: median(deltas), max_ms: Math.round(Math.max(...deltas)) };

    mkdirSync("../../evals/reports/phase4", { recursive: true });
    writeFileSync("../../evals/reports/phase4/ui_render.json", JSON.stringify(result, null, 1) + "\n");
    console.log(JSON.stringify(result));
    wrapper.unmount();
    useAssistantStore().stop();
    useConnectionStore().stop();
  }, 120_000);
});
