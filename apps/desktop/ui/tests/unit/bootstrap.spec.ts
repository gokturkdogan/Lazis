import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  ApiClient,
  BootstrapBatch,
  BootstrapItem,
  BootstrapPerson,
  BootstrapPreview,
  BootstrapSummary,
} from "@/api/client";
import { ApiError } from "@/api/client";
import { createAppI18n } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import MemoryView from "@/views/MemoryView.vue";
import { connection, fakeClient, fakePlatform } from "./fixtures";

/* The personal knowledge import screen (Phase 8). Synthetic data only. */

function batch(extra: Partial<BootstrapBatch> = {}): BootstrapBatch {
  return {
    id: "IMP1", status: "ready", running: false, file_name: "profil.md", format: "markdown", size_bytes: 120,
    sections_total: 3, sections_done: 3, sections_failed: 0, model_calls: 3, error: null, warnings: [],
    counts: {}, undo_counts: {}, created_at: "2026-10-21T10:00:00.000Z", applied_at: null, undone_at: null,
    ...extra,
  };
}

function item(id: string, extra: Partial<BootstrapItem> = {}): BootstrapItem {
  return {
    id, kind: "fact", category: "profile", subject: "Kullanıcı", subject_ref: "user", source_ref: null,
    target_ref: null, predicate: "occupation", predicate_label: "meslek", value: "veri analisti",
    statement: "Kullanıcı — meslek: veri analisti", time: null, section: "Hakkımda", excerpt: "Meslek: veri analisti",
    line: 2, method: "gemma", confidence: 0.8, classification: "new", existing: [], note: null,
    decision: "pending", resolution: null, edited_value: null, blocked: null, result: null,
    save_state: "save_pending_approval", ...extra,
  };
}

function person(id: string, extra: Partial<BootstrapPerson> = {}): BootstrapPerson {
  return {
    id, name: "Ahmet", kind: "person", relation: "komşusu", description: null, match: "ambiguous",
    options: [{ id: "E1", label: "Ahmet (komşusu)", stored: true }, { id: "E2", label: "Ahmet (iş arkadaşı)", stored: true }],
    suggested_id: null, note: "namesakes", decision: "pending", link_id: null, section: "Aile", items: 1, ...extra,
  };
}

function summary(extra: Partial<BootstrapSummary> = {}): BootstrapSummary {
  return {
    analyzed: 3, approved: 0, writable: 0, blocked: 0, rejected: 0, held: 0, pending: 3, excluded: 0, updates: 0,
    people_new: 0, people_linked: 0, people_unresolved: 0, people_rejected: 0, people_pending: 1, by_category: {},
    ...extra,
  };
}

const ITEMS = [
  item("I1"),
  item("I2", { category: "person", subject: "Ahmet (komşusu)", subject_ref: "P1", value: "mimar",
               classification: "ambiguous_entity", excerpt: "Komşum Ahmet mimar", line: 6, section: "Aile" }),
  item("I3", { predicate: "location", predicate_label: "yaşadığı yer (şehir)", value: "İzmir", classification: "conflict",
               existing: ["Ankara"], excerpt: "İzmir'de yaşıyorum", line: 3 }),
  item("I4", { category: "fact", predicate: "note", value: "[gizli bilgi çıkarıldı]", classification: "excluded",
               note: "secret", excerpt: null }),
];

function previewOf(extra: Partial<BootstrapPreview> = {}): BootstrapPreview {
  return { batch: batch(), people: [person("P1")], items: ITEMS, summary: summary(), ...extra };
}

async function mountImport(overrides: Partial<ApiClient> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const client = fakeClient(overrides);
  await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
  const wrapper = mount(MemoryView, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  await wrapper.get('[data-testid="memory-tab-import"]').trigger("click");
  await flushPromises();
  return { wrapper, client };
}

async function pickFile(wrapper: ReturnType<typeof mount>, name: string, content: string) {
  const input = wrapper.get('[data-testid="bootstrap-file"]');
  const file = new File([content], name, { type: "text/plain" });
  Object.defineProperty(input.element, "files", { value: [file], configurable: true });
  await input.trigger("change");
  await flushPromises();
}

afterEach(() => {
  vi.useRealTimers();
});

describe("personal knowledge import", () => {
  it("is the memory screen's import tab, with the privacy note", async () => {
    const { wrapper } = await mountImport();
    expect(wrapper.get('[data-testid="memory-tab-import"]').text()).toBe("Kişisel Bilgi Aktarımı");
    const text = wrapper.get('[data-testid="memory-bootstrap"]').text();
    expect(text).toContain("hiçbiri siz onaylamadan kaydedilmez");
    expect(text).toContain("Dosyadaki talimatlar uygulanmaz");
  });

  it("sends the file once as base64 and shows the preview with nothing approved", async () => {
    const bootstrapAnalyze = vi.fn().mockResolvedValue(batch({ format: "json" }));
    const bootstrapImport = vi.fn().mockResolvedValue(previewOf());
    const { wrapper } = await mountImport({ bootstrapAnalyze, bootstrapImport });
    await pickFile(wrapper, "profil.json", '{"schema_version": "1.0"}');
    expect(bootstrapAnalyze).toHaveBeenCalledWith("profil.json", btoa('{"schema_version": "1.0"}'));
    const rows = wrapper.findAll('[data-testid="bootstrap-item"]');
    expect(rows).toHaveLength(4);
    expect(rows.every((r) => r.attributes("data-decision") === "pending")).toBe(true);
    const first = rows[0]!.text();
    expect(first).toContain("Kaynak: Hakkımda");
    expect(first).toContain("satır 2");
    expect(first).toContain("yerel model okudu");
    expect(first).toContain("güven 80%");
    expect(first).toContain("“Meslek: veri analisti”");
    expect(wrapper.text()).toContain("Güven yalnızca bilgi içindir; onayın yerini tutmaz.");
    expect(wrapper.text()).not.toMatch(/Tümünü onayla|Hepsini onayla/);
    // An excluded item cannot be approved at all.
    expect(rows[3]!.find('[data-testid="bootstrap-approve"]').exists()).toBe(false);
    expect(rows[3]!.text()).toContain("şifre, anahtar ya da numara: hafızaya alınmaz");
  });

  it("refuses a file over 1 MB without sending it", async () => {
    const bootstrapAnalyze = vi.fn();
    const { wrapper } = await mountImport({ bootstrapAnalyze });
    await pickFile(wrapper, "büyük.txt", "a".repeat(1_000_001));
    expect(bootstrapAnalyze).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="bootstrap-error"]').text()).toContain("en fazla 1 MB");
  });

  it("shows the line of an invalid JSON file", async () => {
    const bootstrapAnalyze = vi.fn().mockRejectedValue(
      new ApiError(422, "import_profile_invalid_json", "", true, { line: 4, column: 12 }),
    );
    const { wrapper } = await mountImport({ bootstrapAnalyze });
    await pickFile(wrapper, "profil.json", "{");
    expect(wrapper.get('[data-testid="bootstrap-error"]').text()).toBe("JSON dosyası geçersiz. (satır 4)");
  });

  it("shows progress and cancels at once", async () => {
    vi.useFakeTimers();
    const analyzing = batch({ status: "analyzing", sections_done: 1, sections_total: 4 });
    const bootstrapImport = vi.fn().mockResolvedValue(previewOf({ batch: analyzing, items: [], people: [] }));
    const bootstrapCancel = vi.fn().mockResolvedValue(batch({ status: "cancelled" }));
    const { wrapper } = await mountImport({
      bootstrapAnalyze: vi.fn().mockResolvedValue(analyzing), bootstrapImport, bootstrapCancel,
    });
    await pickFile(wrapper, "profil.md", "# Hakkımda");
    expect(wrapper.get('[data-testid="bootstrap-progress"]').text()).toContain("1 / 4 bölüm okundu");
    await vi.advanceTimersByTimeAsync(800);
    expect(bootstrapImport).toHaveBeenCalled();
    await wrapper.get('[data-testid="bootstrap-cancel"]').trigger("click");
    await flushPromises();
    expect(bootstrapCancel).toHaveBeenCalledWith("IMP1");
    expect(wrapper.get('[data-testid="bootstrap-notice"]').text()).toContain("Hafızaya hiçbir şey yazılmadı.");
    const calls = bootstrapImport.mock.calls.length;
    await vi.advanceTimersByTimeAsync(3000);
    expect(bootstrapImport.mock.calls.length).toBe(calls); // polling stopped
  });

  it("sends one decision per click; conflicts offer keep / update / keep both", async () => {
    const bootstrapDecide = vi.fn().mockResolvedValue(previewOf());
    const { wrapper } = await mountImport({
      bootstrapAnalyze: vi.fn().mockResolvedValue(batch()),
      bootstrapImport: vi.fn().mockResolvedValue(previewOf()),
      bootstrapDecide,
    });
    await pickFile(wrapper, "profil.md", "# x");
    const rows = wrapper.findAll('[data-testid="bootstrap-item"]');
    await rows[0]!.get('[data-testid="bootstrap-approve"]').trigger("click");
    await flushPromises();
    expect(bootstrapDecide).toHaveBeenLastCalledWith("IMP1", { people: [], items: [{ id: "I1", decision: "approve", resolution: null }] });
    const conflictRow = rows.find((r) => r.text().includes("İzmir"))!; // grouped by category
    expect(conflictRow.find('[data-testid="bootstrap-approve"]').exists()).toBe(false); // a conflict needs a choice
    await conflictRow.get('[data-testid="bootstrap-resolve-keep_both"]').trigger("click");
    await flushPromises();
    expect(bootstrapDecide).toHaveBeenLastCalledWith("IMP1", { people: [], items: [{ id: "I3", decision: "approve", resolution: "keep_both" }] });
    await wrapper.get('[data-testid="bootstrap-tab-conflicts"]').trigger("click");
    const conflict = wrapper.get('[data-testid="bootstrap-conflict"]').text();
    expect(conflict).toContain("Kayıtlı: Ankara");
    expect(conflict).toContain("→ İzmir");
    expect(conflict).toContain("İkisini de zaman bilgisiyle tut");
  });

  it("edits a value before approving it", async () => {
    const bootstrapDecide = vi.fn().mockResolvedValue(previewOf());
    const { wrapper } = await mountImport({
      bootstrapAnalyze: vi.fn().mockResolvedValue(batch()),
      bootstrapImport: vi.fn().mockResolvedValue(previewOf()),
      bootstrapDecide,
    });
    await pickFile(wrapper, "profil.md", "# x");
    await wrapper.findAll('[data-testid="bootstrap-edit"]')[0]!.trigger("click");
    await wrapper.get('[data-testid="bootstrap-edit-input"]').setValue("kıdemli veri analisti");
    await wrapper.get('[data-testid="bootstrap-edit-save"]').trigger("click");
    await flushPromises();
    expect(bootstrapDecide).toHaveBeenLastCalledWith("IMP1", {
      people: [], items: [{ id: "I1", decision: "approve", resolution: null, edited_value: "kıdemli veri analisti" }],
    });
  });

  it("a namesake is placed by the user; a suggestion is never applied by itself", async () => {
    const bootstrapDecide = vi.fn().mockResolvedValue(previewOf());
    const { wrapper } = await mountImport({
      bootstrapAnalyze: vi.fn().mockResolvedValue(batch()),
      bootstrapImport: vi.fn().mockResolvedValue(previewOf()),
      bootstrapDecide,
    });
    await pickFile(wrapper, "profil.md", "# x");
    await wrapper.get('[data-testid="bootstrap-tab-people"]').trigger("click");
    const row = wrapper.get('[data-testid="bootstrap-person"]');
    expect(row.attributes("data-decision")).toBe("pending");
    expect(row.text()).toContain("aynı adda birden fazla kişi");
    expect(row.get('[data-testid="bootstrap-person-link"]').attributes("disabled")).toBeDefined();
    await row.get('[data-testid="bootstrap-person-target"]').setValue("E2");
    await row.get('[data-testid="bootstrap-person-link"]').trigger("click");
    await flushPromises();
    expect(bootstrapDecide).toHaveBeenLastCalledWith("IMP1", { people: [{ id: "P1", decision: "link", link_id: "E2" }], items: [] });
    await row.get('[data-testid="bootstrap-person-unresolved"]').trigger("click");
    await flushPromises();
    expect(bootstrapDecide).toHaveBeenLastCalledWith("IMP1", { people: [{ id: "P1", decision: "unresolved" }], items: [] });
  });

  it("confirms with counts from the decisions, then shows the real result and the import id", async () => {
    const decided = previewOf({ summary: summary({ approved: 2, writable: 1, blocked: 1, pending: 2, by_category: { profile: 1 } }) });
    const applied = batch({ status: "applied", counts: { written: 1, updated: 0, blocked: 1, pending: 2, people_created: 0 } });
    const bootstrapApply = vi.fn().mockResolvedValue({ batch: applied, change_set_id: "CS1" });
    const { wrapper } = await mountImport({
      bootstrapAnalyze: vi.fn().mockResolvedValue(batch()),
      bootstrapImport: vi.fn().mockResolvedValue(decided),
      bootstrapApply,
    });
    await pickFile(wrapper, "profil.md", "# x");
    await wrapper.get('[data-testid="bootstrap-to-confirm"]').trigger("click");
    const s = wrapper.get('[data-testid="bootstrap-summary"]').text();
    expect(s).toContain("1 bilgi kaydedilecek");
    expect(s).toContain("2 için karar verilmedi — kaydedilmez");
    expect(s).toContain("1 onaylı bilgi kaydedilemez");
    await wrapper.get('[data-testid="bootstrap-apply"]').trigger("click");
    await flushPromises();
    expect(bootstrapApply).toHaveBeenCalledWith("IMP1");
    const r = wrapper.get('[data-testid="bootstrap-result"]').text();
    expect(r).toContain("1 bilgi kaydedildi");
    expect(r).toContain("2 karar verilmediği için kaydedilmedi");
    expect(wrapper.get('[data-testid="bootstrap-import-id"]').text()).toContain("IMP1");
  });

  it("nothing approved means nothing to save", async () => {
    const { wrapper } = await mountImport({
      bootstrapAnalyze: vi.fn().mockResolvedValue(batch()),
      bootstrapImport: vi.fn().mockResolvedValue(previewOf()),
    });
    await pickFile(wrapper, "profil.md", "# x");
    await wrapper.get('[data-testid="bootstrap-to-confirm"]').trigger("click");
    expect(wrapper.get('[data-testid="bootstrap-apply"]').attributes("disabled")).toBeDefined();
  });

  it("a memory change before writing brings the preview back", async () => {
    const bootstrapImport = vi.fn().mockResolvedValue(previewOf({ summary: summary({ writable: 1, approved: 1 }) }));
    const { wrapper } = await mountImport({
      bootstrapAnalyze: vi.fn().mockResolvedValue(batch()),
      bootstrapImport,
      bootstrapApply: vi.fn().mockRejectedValue(new ApiError(409, "import_memory_changed", "", true, { items: ["I1"] })),
    });
    await pickFile(wrapper, "profil.md", "# x");
    await wrapper.get('[data-testid="bootstrap-to-confirm"]').trigger("click");
    await wrapper.get('[data-testid="bootstrap-apply"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="bootstrap-preview"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="bootstrap-notice"]').text()).toContain("hafıza değişti");
  });

  it("undo shows its plan first and sends the records chosen for restore", async () => {
    const applied = batch({ status: "applied", counts: { written: 2 } });
    const plan = {
      import_id: "IMP1", already_undone: false,
      steps: [
        { table: "memory" as const, target_id: "M1", action: "remove" as const, label: "Kullanıcı — meslek: veri analisti", reason: "" },
        { table: "memory" as const, target_id: "M2", action: "keep" as const, label: "Kullanıcı — alışkanlık: koşu", reason: "confirmed_elsewhere" },
        { table: "memory" as const, target_id: "M3", action: "decide" as const, label: "Kullanıcı — şehir: Ankara", reason: "changed_later" },
      ],
      counts: { remove: 1, restore: 0, keep: 1, decide: 1, remove_evidence: 0, gone: 0 },
    };
    const bootstrapUndo = vi.fn().mockResolvedValue({ batch: batch({ status: "undone" }), plan, change_set_id: "CS2" });
    const { wrapper } = await mountImport({
      bootstrapHistory: vi.fn().mockResolvedValue([applied]),
      bootstrapUndoPlan: vi.fn().mockResolvedValue(plan),
      bootstrapUndo,
    });
    await wrapper.get('[data-testid="bootstrap-history-undo"]').trigger("click");
    await flushPromises();
    const groups = wrapper.findAll('[data-testid="bootstrap-undo-group"]').map((g) => g.text());
    expect(groups[0]).toContain("Silinecek");
    expect(groups.join(" ")).toContain("sohbette de doğrulandı");
    expect(groups.join(" ")).toContain("Sizin kararınız gerekiyor");
    await wrapper.get('[data-testid="bootstrap-undo-restore"]').setValue(true);
    await wrapper.get('[data-testid="bootstrap-undo-confirm"]').trigger("click");
    await flushPromises();
    expect(bootstrapUndo).toHaveBeenCalledWith("IMP1", ["M3"]);
    expect(wrapper.get('[data-testid="bootstrap-notice"]').text()).toContain("Aktarım geri alındı");
  });

  it("a failed analysis says so and retries only on request", async () => {
    const failed = batch({ status: "failed", error: "no_section_read" });
    const bootstrapRetry = vi.fn().mockResolvedValue(batch());
    const { wrapper } = await mountImport({
      bootstrapAnalyze: vi.fn().mockResolvedValue(failed),
      bootstrapImport: vi.fn().mockResolvedValue(previewOf()),
      bootstrapRetry,
    });
    await pickFile(wrapper, "profil.md", "# x");
    expect(wrapper.get('[data-testid="bootstrap-failed"]').text()).toContain("hiçbir bölüm okunamadı");
    expect(wrapper.get('[data-testid="bootstrap-failed"]').text()).toContain("Hafızaya hiçbir şey yazılmadı.");
    expect(bootstrapRetry).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="bootstrap-retry"]').trigger("click");
    await flushPromises();
    expect(bootstrapRetry).toHaveBeenCalledWith("IMP1");
  });
});
