import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import type { ApiClient } from "@/api/client";
import { ApiError } from "@/api/client";
import DocumentAttach from "@/components/DocumentAttach.vue";
import DocumentChip from "@/components/DocumentChip.vue";
import { createAppI18n } from "@/i18n";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import { useDocumentUi } from "@/stores/documentUi";
import { connection, documentFixture, fakeClient, fakePlatform } from "./fixtures";

/** The paperclip and the chip as they sit next to the composer (Phase 14.1). */
const Composer = defineComponent(() => () => h("div", [h(DocumentChip), h(DocumentAttach)]));

async function mountPanel(client: ApiClient = fakeClient()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
  const wrapper = mount(Composer, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, client, store: useAssistantStore() };
}

async function choose(wrapper: Awaited<ReturnType<typeof mountPanel>>["wrapper"], file: File) {
  const input = wrapper.get('[data-testid="document-file"]');
  Object.defineProperty(input.element, "files", { value: [file], configurable: true });
  await input.trigger("change");
  await flushPromises();
}

describe("Document attach and chip (Phase 11, composer since 14.1)", () => {
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

  it("is a paperclip icon that opens the file picker for TXT, PDF and DOCX", async () => {
    const { wrapper } = await mountPanel();
    const attach = wrapper.get('[data-testid="document-attach"]');
    expect(attach.attributes("aria-label")).toBe("Belge ekle (TXT, PDF, DOCX)");
    expect(attach.find("svg").exists()).toBe(true);
    expect(attach.text()).toBe("");
    const input = wrapper.get('[data-testid="document-file"]');
    expect(input.attributes("accept")).toBe(".txt,.pdf,.docx");
    const click = vi.spyOn(input.element as HTMLInputElement, "click");
    await attach.trigger("click");
    expect(click).toHaveBeenCalled();
  });

  it("shows nothing above the composer until there is a document", async () => {
    const { wrapper } = await mountPanel();
    expect(wrapper.find('[data-testid="documents"]').exists()).toBe(false);
  });

  it("shows the reading state and blocks a second pick while busy", async () => {
    let finish: (v: unknown) => void = () => {};
    const client = fakeClient({ addDocument: vi.fn().mockReturnValue(new Promise((r) => (finish = r))) });
    const { wrapper } = await mountPanel(client);
    await choose(wrapper, new File(["a"], "a.txt"));
    expect(wrapper.get('[data-testid="documents"]').text()).toContain("okunuyor");
    expect(wrapper.get('[data-testid="document-attach"]').attributes("disabled")).toBeDefined();
    finish(documentFixture());
    await flushPromises();
    expect(wrapper.get('[data-testid="document-name"]').text()).toBe("kira.pdf");
    expect(wrapper.get('[data-testid="document-attach"]').attributes("disabled")).toBeUndefined();
  });

  it("replaces the open document with the new one and closes the old", async () => {
    const { wrapper, client, store } = await mountPanel();
    store.setDocument({ ...documentFixture(), id: "old" });
    await choose(wrapper, new File(["b"], "b.txt"));
    expect(store.document?.id).toBe(documentFixture().id);
    expect(client.removeDocument).toHaveBeenCalledWith("old");
  });

  it("clears an earlier error when a new file is chosen", async () => {
    const { wrapper } = await mountPanel();
    const big = new File(["x"], "buyuk.pdf");
    Object.defineProperty(big, "size", { value: 10_000_001 });
    await choose(wrapper, big);
    expect(wrapper.find('[data-testid="document-error"]').exists()).toBe(true);
    await choose(wrapper, new File(["c"], "c.txt"));
    expect(wrapper.find('[data-testid="document-error"]').exists()).toBe(false);
    expect(useDocumentUi().error).toBeNull();
  });
});
