import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient, ImportItem, MemoryEntity, MemoryInboxItem, MemoryRecord } from "@/api/client";
import { createAppI18n } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import DiagnosticsView from "@/views/DiagnosticsView.vue";
import MemoryView from "@/views/MemoryView.vue";
import { connection, fakeClient, fakePlatform } from "./fixtures";

function record(id: string, content: string, extra: Partial<MemoryRecord> = {}): MemoryRecord {
  return {
    id, kind: "profile", predicate: "location", predicate_label: "yaşadığı yer (şehir)", subject: null,
    value: content, content, status: "active", origin: "stated", confidence: 0.85, importance: 0.6,
    sensitivity: "normal", sensitivity_category: null, conflict_state: "none", event_time: null,
    valid_from: "2026-10-20T08:00:00Z", valid_to: null, supersedes_id: null, recall_count: 0,
    created_at: "2026-10-20T08:00:00Z", updated_at: "2026-10-20T08:00:00Z", ...extra,
  };
}

const AHMET: MemoryEntity = {
  id: "E1", kind: "person", name: "Ahmet", relation: "çocukluk arkadaşı", description: null, aliases: [],
  records: 2, updated_at: "2026-10-20T08:00:00Z",
};

async function mountMemory(overrides: Partial<ApiClient> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const client = fakeClient(overrides);
  await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
  const wrapper = mount(MemoryView, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, client };
}

describe("memory screen", () => {
  it("lists records with their origin and searches", async () => {
    const memoryRecords = vi.fn().mockResolvedValue({
      records: [record("M1", "Kullanıcı İzmir'de yaşıyor.", { sensitivity: "sensitive" })],
      has_more: false,
    });
    const { wrapper } = await mountMemory({ memoryRecords });
    const row = wrapper.get('[data-testid="memory-record"]').text();
    expect(row).toContain("Kullanıcı İzmir'de yaşıyor.");
    expect(row).toContain("Sohbetten");
    expect(row).toContain("hassas");
    await wrapper.get('[data-testid="memory-search"]').setValue("nerede yaşıyorum");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(memoryRecords).toHaveBeenLastCalledWith(expect.objectContaining({ q: "nerede yaşıyorum", status: "active" }));
  });

  it("shows an honest empty state", async () => {
    const { wrapper } = await mountMemory();
    expect(wrapper.get('[data-testid="memory-empty"]').text()).toContain("Henüz kayıt yok");
    expect(wrapper.text()).toContain("bir kaydı silmek eski mesajları ve yedekleri silmez");
  });

  it("forgets only after confirmation", async () => {
    const forgetMemory = vi.fn().mockResolvedValue({ memories: 1, entities: 0 });
    const { wrapper } = await mountMemory({
      memoryRecords: vi.fn().mockResolvedValue({ records: [record("M1", "Kullanıcı çay sever.")], has_more: false }),
      forgetMemory,
    });
    await wrapper.get('[data-testid="memory-forget"]').trigger("click");
    expect(forgetMemory).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("LAZIS bunu yeniden öğrenmez");
    await wrapper.get('[data-testid="memory-forget-confirm"]').trigger("click");
    await flushPromises();
    expect(forgetMemory).toHaveBeenCalledWith("M1");
    expect(wrapper.findAll('[data-testid="memory-record"]')).toHaveLength(0);
    expect(wrapper.text()).toContain("Silindi.");
  });

  it("edits a record and shows its source and history", async () => {
    const editMemory = vi.fn().mockResolvedValue(record("M1", "Kullanıcı Bursa'da yaşıyor.", { origin: "user_edit" }));
    const memoryRecord = vi.fn().mockResolvedValue({
      record: record("M1", "Kullanıcı İzmir'de yaşıyor."),
      evidence: [{ source_type: "message", source_ref: "x", quote: "İzmir'de yaşıyorum", created_at: "2026-10-20T08:00:00Z" }],
      previous: [record("M0", "Ankara", { status: "superseded", valid_to: "2026-10-19T08:00:00Z" })],
    });
    const { wrapper } = await mountMemory({
      memoryRecords: vi.fn().mockResolvedValue({ records: [record("M1", "Kullanıcı İzmir'de yaşıyor.")], has_more: false }),
      editMemory,
      memoryRecord,
    });
    await wrapper.get('[data-testid="memory-source"]').trigger("click");
    await flushPromises();
    const detail = wrapper.get('[data-testid="memory-detail"]').text();
    expect(detail).toContain("Sohbet mesajından");
    expect(detail).toContain("“İzmir'de yaşıyorum”");
    expect(detail).toContain("Önceki değerler");
    expect(detail).toContain("Ankara");
    await wrapper.get('[data-testid="memory-edit"]').trigger("click");
    await wrapper.get('[data-testid="memory-edit-statement"]').setValue("Kullanıcı Bursa'da yaşıyor.");
    await wrapper.get('[data-testid="memory-edit-save"]').trigger("click");
    await flushPromises();
    expect(editMemory).toHaveBeenCalledWith("M1", "Kullanıcı İzmir'de yaşıyor.", "Kullanıcı Bursa'da yaşıyor.");
    expect(wrapper.text()).toContain("Sizin girdiniz");
  });

  it("adds a record about a new person", async () => {
    const addMemory = vi.fn().mockResolvedValue({ created: 1, updated: 0, superseded: 0, inbox: 0, entities_created: 1, dropped: {} });
    const { wrapper } = await mountMemory({
      addMemory,
      memoryPredicates: vi.fn().mockResolvedValue([
        { key: "occupation", label: "meslek", kind: "profile", cardinality: "single", sensitivity: "normal", subjects: ["user", "person"] },
      ]),
    });
    await wrapper.get('[data-testid="memory-add-toggle"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="memory-add-predicate"]').setValue("occupation");
    await wrapper.get('[data-testid="memory-add-value"]').setValue("öğretmen");
    await wrapper.get('[data-testid="memory-add-subject"]').setValue("new");
    const inputs = wrapper.get('[data-testid="memory-add"]').findAll("input");
    await inputs[inputs.length - 2]!.setValue("Can");
    await inputs[inputs.length - 1]!.setValue("kuzen");
    expect(wrapper.get('[data-testid="memory-add-submit"]').attributes("disabled")).toBeUndefined();
    await wrapper.get('[data-testid="memory-add"]').trigger("submit");
    await flushPromises();
    expect(addMemory).toHaveBeenCalledWith(
      expect.objectContaining({ predicate: "occupation", value: "öğretmen", entity_id: null, new_entity: { name: "Can", relation: "kuzen", kind: "person" } }),
    );
    expect(wrapper.text()).toContain("Kaydedildi.");
  });

  it("asks before deleting a person, then deletes", async () => {
    const forgetEntity = vi.fn().mockResolvedValue({ memories: 2, entities: 1 });
    const { wrapper } = await mountMemory({
      memoryEntities: vi.fn().mockResolvedValue([AHMET]),
      memoryEntity: vi.fn().mockResolvedValue({ entity: AHMET, records: [record("M2", "Ahmet yazılımcı.")] }),
      forgetEntity,
    });
    await wrapper.get('[data-testid="memory-tab-entities"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="memory-entity"]').text()).toContain("Ahmet (çocukluk arkadaşı)");
    await wrapper.get('[data-testid="memory-entity"] button').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="memory-entity-detail"]').text()).toContain("Ahmet yazılımcı.");
    await wrapper.get('[data-testid="entity-forget"]').trigger("click");
    expect(forgetEntity).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("2 kayıt ve kişi kaydı silinsin mi");
    await wrapper.get('[data-testid="entity-forget-confirm"]').trigger("click");
    await flushPromises();
    expect(forgetEntity).toHaveBeenCalledWith("E1");
  });

  it("lets the user decide which person is meant", async () => {
    const item: MemoryInboxItem = {
      id: "I1", type: "ambiguous_entity", summary: "Hangi Ahmet? — Ahmet satranç kulübüne yazıldı.",
      created_at: "2026-10-20T08:00:00Z", predicate_label: "ilgi alanı", value: "satranç", subject: "Ahmet",
      options: [{ id: "E1", label: "Ahmet (çocukluk arkadaşı)" }, { id: "E2", label: "Ahmet (iş ortağı)" }],
      existing: [], category: null, about: "memory", relationship: null,
    };
    const resolveInbox = vi.fn().mockResolvedValue({ created: 1, updated: 0, superseded: 0, inbox: 0, entities_created: 0, dropped: {} });
    const { wrapper } = await mountMemory({
      memoryOverview: vi.fn().mockResolvedValue({ memories: {}, entities: 2, inbox_open: 1, jobs: {}, auto_extract: true, trusted_models: [] }),
      memoryInbox: vi.fn().mockResolvedValue([item]),
      resolveInbox,
    });
    expect(wrapper.get('[data-testid="memory-pending"]').text()).toBe("1");
    await wrapper.get('[data-testid="memory-tab-inbox"]').trigger("click");
    await flushPromises();
    const options = wrapper.findAll('[data-testid="inbox-option"]');
    expect(options.map((o) => o.text())).toEqual(["Ahmet (çocukluk arkadaşı)", "Ahmet (iş ortağı)"]);
    await options[1]!.trigger("click");
    await flushPromises();
    expect(resolveInbox).toHaveBeenCalledWith("I1", "E2");
    expect(wrapper.find('[data-testid="inbox-empty"]').exists()).toBe(true);
  });

  it("imports only what the user selected; sensitive and conflicting items need a choice", async () => {
    const items: ImportItem[] = [
      { index: 0, status: "new", subject: "Kullanıcı", predicate: "occupation", predicate_label: "meslek", value: "analist",
        statement: "Kullanıcı — meslek: analist", reason: null, sensitive: false, options: [], existing: [] },
      { index: 1, status: "new", subject: "Kullanıcı", predicate: "health", predicate_label: "sağlık bilgisi", value: "astım",
        statement: "Kullanıcı — sağlık bilgisi: astım", reason: null, sensitive: true, options: [], existing: [] },
      { index: 2, status: "excluded", subject: "Kullanıcı", predicate: "note", predicate_label: "not", value: "wifi şifresi",
        statement: "Kullanıcı — not: wifi şifresi …", reason: "secret", sensitive: false, options: [], existing: [] },
      { index: 3, status: "conflict", subject: "Kullanıcı", predicate: "location", predicate_label: "yaşadığı yer (şehir)",
        value: "Bursa", statement: "Kullanıcı — yaşadığı yer (şehir): Bursa", reason: null, sensitive: false, options: [], existing: ["İzmir"] },
    ];
    const importApply = vi.fn().mockResolvedValue({ created: 1, updated: 0, superseded: 0, inbox: 0, entities_created: 0, dropped: {} });
    const { wrapper } = await mountMemory({
      importPreview: vi.fn().mockResolvedValue({ batch_id: "B1", items, errors: [] }),
      importApply,
    });
    await wrapper.get('[data-testid="memory-tab-import"]').trigger("click");
    await wrapper.get('[data-testid="import-content"]').setValue('{"user": {}}');
    await wrapper.get('[data-testid="import-preview"]').trigger("click");
    await flushPromises();
    const text = wrapper.get('[data-testid="memory-import"]').text();
    expect(text).toContain("şifre, anahtar ya da numara: hafızaya alınmaz");
    expect(text).toContain("Şu anki: İzmir");
    expect((wrapper.get('[data-testid="import-check-1"]').element as HTMLInputElement).checked).toBe(false);
    expect((wrapper.get('[data-testid="import-check-2"]').element as HTMLInputElement).disabled).toBe(true);
    await wrapper.get('[data-testid="import-apply"]').trigger("click");
    await flushPromises();
    expect(importApply).toHaveBeenCalledWith("B1", { 0: "apply" });
    expect(wrapper.text()).toContain("1 kayıt eklendi.");
  });
});

describe("diagnostics", () => {
  it("shows the learning state without content", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const client = fakeClient();
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
    const wrapper = mount(DiagnosticsView, { global: { plugins: [pinia, createAppI18n()] } });
    await flushPromises();
    const card = wrapper.get('[data-testid="diag-learning"]').text();
    expect(card).toContain("Açık (yazabilen model: gemma4:12b-it-qat)");
    expect(card).toContain("1 yeni kayıt, 0 onay bekleyen");
    expect(card).toContain("3 kayıt · 0 onay bekleyen");
    expect(card).toContain("2 güncel · 0 geçmiş");
    wrapper.unmount();
  });
});
