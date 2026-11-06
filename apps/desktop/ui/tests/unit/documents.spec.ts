import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { ApiError } from "@/api/client";
import DocumentPanel from "@/components/DocumentPanel.vue";
import { createAppI18n } from "@/i18n";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import { connection, documentFixture, fakeClient, fakePlatform } from "./fixtures";

async function mountPanel(client: ApiClient = fakeClient()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
  const wrapper = mount(DocumentPanel, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, client, store: useAssistantStore() };
}

async function choose(wrapper: Awaited<ReturnType<typeof mountPanel>>["wrapper"], file: File) {
  const input = wrapper.get('[data-testid="document-file"]');
  Object.defineProperty(input.element, "files", { value: [file], configurable: true });
  await input.trigger("change");
  await flushPromises();
}

describe("Document panel (Phase 11)", () => {
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
  });

  it("opens a chosen file, sends its bytes, and makes it the active document", async () => {
    const { wrapper, client, store } = await mountPanel();
    await choose(wrapper, new File(["Kira 40 bin TL"], "kira.txt", { type: "text/plain" }));
    expect(client.addDocument).toHaveBeenCalledWith("kira.txt", btoa("Kira 40 bin TL"));
    expect(store.document?.id).toBe(documentFixture().id);
    expect(wrapper.get('[data-testid="document-name"]').text()).toBe("kira.pdf");
    expect(wrapper.text()).toContain("PDF, 2 sayfa");
  });

  it("refuses a file over 10 MB without sending it", async () => {
    const { wrapper, client } = await mountPanel();
    const big = new File(["x"], "buyuk.pdf");
    Object.defineProperty(big, "size", { value: 10_000_001 });
    await choose(wrapper, big);
    expect(client.addDocument).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("en fazla 10 MB");
  });

  it("shows the backend's refusal in Turkish", async () => {
    const client = fakeClient({
      addDocument: vi.fn().mockRejectedValue(new ApiError(422, "document_no_text", "", true)),
    });
    const { wrapper, store } = await mountPanel(client);
    await choose(wrapper, new File(["%PDF"], "tarama.pdf"));
    expect(store.document).toBeNull();
    expect(wrapper.text()).toContain("metin katmanı yok");
  });

  it("closes the document on the backend and stops sending it", async () => {
    const { wrapper, client, store } = await mountPanel();
    store.setDocument(documentFixture());
    await flushPromises();
    await wrapper.get('[data-testid="document-close"]').trigger("click");
    await flushPromises();
    expect(client.removeDocument).toHaveBeenCalledWith(documentFixture().id);
    expect(store.document).toBeNull();
  });
});
