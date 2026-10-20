import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient, MemoryEntity, MemoryInboxItem, Relationship, RelationshipType } from "@/api/client";
import { createAppI18n } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import MemoryView from "@/views/MemoryView.vue";
import { connection, fakeClient, fakePlatform } from "./fixtures";

const AHMET: MemoryEntity = {
  id: "E1", kind: "person", name: "Ahmet", relation: "çocukluk arkadaşı", description: null, aliases: [],
  records: 0, updated_at: "2026-10-20T08:00:00Z",
};
const MEHMET: MemoryEntity = { ...AHMET, id: "E2", name: "Mehmet", relation: null };
const subject = (id: string, name: string) => ({ id, kind: "person" as const, name, relation: null });

function rel(id: string, extra: Partial<Relationship> = {}): Relationship {
  return {
    id, source: subject("E1", "Ahmet"), type: "sibling", type_label: "kardeşi", target: subject("E2", "Mehmet"),
    text: "Mehmet: Ahmet'in kardeşi", reading: "kardeşi", other: subject("E2", "Mehmet"), status: "active",
    origin: "stated", confidence: 0.85, sensitivity: "personal", time_text: null, qualifier: null,
    valid_from: "2026-10-20T08:00:00Z", valid_to: null, conflict_state: "none",
    created_at: "2026-10-20T08:00:00Z", updated_at: "2026-10-20T08:00:00Z", ...extra,
  };
}

const TYPES: RelationshipType[] = [
  { key: "sibling", label: "kardeşi", inverse_label: "kardeşi", category: "family", symmetric: true,
    sensitivity: "personal", source_kinds: ["person"], target_kinds: ["person"] },
  { key: "works_at", label: "çalıştığı yer", inverse_label: "çalışanı", category: "organization", symmetric: false,
    sensitivity: "personal", source_kinds: ["person"], target_kinds: ["organization", "group"] },
];

async function openAhmet(overrides: Partial<ApiClient>) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const client = fakeClient({
    memoryEntities: vi.fn().mockResolvedValue([AHMET, MEHMET]),
    memoryEntity: vi.fn().mockResolvedValue({ entity: AHMET, records: [] }),
    relationshipTypes: vi.fn().mockResolvedValue(TYPES),
    ...overrides,
  });
  await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
  const wrapper = mount(MemoryView, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  await wrapper.get('[data-testid="memory-tab-entities"]').trigger("click");
  await flushPromises();
  await wrapper.findAll('[data-testid="memory-entity"] button')[0]!.trigger("click");
  await flushPromises();
  return { wrapper, client };
}

describe("relationships on the person screen", () => {
  it("lists current and past relationships as read from this person", async () => {
    const entityRelationships = vi.fn().mockResolvedValue([
      rel("R1"),
      rel("R2", { type: "spouse", reading: "eşi", other: subject("E3", "Deniz"), status: "ended", time_text: "2019'a kadar" }),
      rel("R3", { status: "active", conflict_state: "pending" }),
    ]);
    const { wrapper } = await openAhmet({ entityRelationships });
    expect(entityRelationships).toHaveBeenCalledWith("E1");
    const rows = wrapper.findAll('[data-testid="relation"]').map((r) => r.text());
    expect(rows[0]).toContain("Mehmet — kardeşi");
    expect(rows[1]).toContain("çelişen bilgi onay bekliyor");
    expect(rows[2]).toContain("Geçmiş ilişkiler");
    expect(rows[2]).toContain("Deniz — eşi");
    expect(rows[2]).toContain("sona erdi");
    expect(rows[2]).toContain("2019'a kadar");
  });

  it("shows evidence and the earlier version", async () => {
    const relationship = vi.fn().mockResolvedValue({
      relationship: rel("R1"),
      evidence: [{ source_type: "message", source_ref: "m", quote: "Ahmet'in kardeşi Mehmet", created_at: "2026-10-20T08:00:00Z" }],
      previous: [rel("R0", { type: "cousin", text: "Mehmet: Ahmet'in kuzeni", status: "superseded" })],
    });
    const { wrapper } = await openAhmet({ entityRelationships: vi.fn().mockResolvedValue([rel("R1")]), relationship });
    await wrapper.get('[data-testid="relation-evidence"]').trigger("click");
    await flushPromises();
    const detail = wrapper.get('[data-testid="relation-detail"]').text();
    expect(detail).toContain("Sohbet mesajından — “Ahmet'in kardeşi Mehmet”");
    expect(detail).toContain("Önceki hâli");
    expect(detail).toContain("Mehmet: Ahmet'in kuzeni");
  });

  it("adds a relationship with only the types that fit", async () => {
    const addRelationship = vi.fn().mockResolvedValue({ created: 1, updated: 0, ended: 0, superseded: 0, inbox: 0, dropped: {} });
    const { wrapper } = await openAhmet({ addRelationship });
    await wrapper.get('[data-testid="relation-add-toggle"]').trigger("click");
    await wrapper.get('[data-testid="relation-add-other"]').setValue("E2");
    const types = wrapper.findAll('[data-testid="relation-add-type"] option').map((o) => o.text());
    expect(types.some((x) => x.startsWith("kardeşi"))).toBe(true);
    expect(types.some((x) => x.startsWith("çalıştığı yer"))).toBe(false); // a person is not a workplace
    await wrapper.get('[data-testid="relation-add-type"]').setValue("sibling");
    expect(wrapper.get('[data-testid="relation-add-preview"]').text()).toBe("Ahmet için: Mehmet = kardeşi");
    await wrapper.get('[data-testid="relation-add"]').trigger("submit");
    await flushPromises();
    expect(addRelationship).toHaveBeenCalledWith(
      expect.objectContaining({ source_id: "E1", type: "sibling", target_id: "E2", status: "active" }),
    );
    expect(wrapper.text()).toContain("İlişki eklendi.");
  });

  it("says when an added relationship waits for a decision", async () => {
    const addRelationship = vi.fn().mockResolvedValue({ created: 0, updated: 0, ended: 0, superseded: 0, inbox: 1, dropped: {} });
    const { wrapper } = await openAhmet({ addRelationship });
    await wrapper.get('[data-testid="relation-add-toggle"]').trigger("click");
    await wrapper.get('[data-testid="relation-add-other"]').setValue("E2");
    await wrapper.get('[data-testid="relation-add-type"]').setValue("sibling");
    await wrapper.get('[data-testid="relation-add"]').trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("karar için Bekleyenler'e eklendi");
  });

  it("edits and deletes only after confirmation", async () => {
    const editRelationship = vi.fn().mockResolvedValue(rel("R1", { status: "ended" }));
    const forgetRelationship = vi.fn().mockResolvedValue({ memories: 1, entities: 0 });
    const { wrapper } = await openAhmet({
      entityRelationships: vi.fn().mockResolvedValue([rel("R1")]),
      editRelationship,
      forgetRelationship,
    });
    await wrapper.get('[data-testid="relation-edit"]').trigger("click");
    await wrapper.get('[data-testid="relation-edit-status"]').setValue("ended");
    await wrapper.get('[data-testid="relation-edit-save"]').trigger("click");
    await flushPromises();
    expect(editRelationship).toHaveBeenCalledWith("R1", { type: "sibling", status: "ended", time_text: null, qualifier: null });
    await wrapper.get('[data-testid="relation-forget"]').trigger("click");
    expect(forgetRelationship).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("LAZIS bunu yeniden öğrenmez");
    await wrapper.get('[data-testid="relation-forget-confirm"]').trigger("click");
    await flushPromises();
    expect(forgetRelationship).toHaveBeenCalledWith("R1");
  });

  it("draws a bounded relation map", async () => {
    const graphNeighbourhood = vi.fn().mockResolvedValue({
      nodes: [
        { id: "E1", name: "Ahmet", kind: "person", is_user: false, depth: 0 },
        { id: "E2", name: "Mehmet", kind: "person", is_user: false, depth: 1 },
        { id: "user", name: "Kullanıcı", kind: "person", is_user: true, depth: 1 },
      ],
      edges: [{ id: "R1", source_id: "E1", target_id: "E2", type: "sibling", label: "kardeşi", status: "active" }],
      truncated: false,
    });
    const { wrapper } = await openAhmet({ graphNeighbourhood });
    await wrapper.get('[data-testid="relation-map-toggle"]').trigger("click");
    await flushPromises();
    expect(graphNeighbourhood).toHaveBeenCalledWith("E1", 1, false);
    expect(wrapper.findAll('[data-testid="relation-map-node"]')).toHaveLength(3);
    expect(wrapper.get('[data-testid="relation-map"]').text()).toContain("Hassas ilişkiler haritada gösterilmez.");
    await wrapper.get('[data-testid="relation-map-depth"]').setValue("2");
    await flushPromises();
    expect(graphNeighbourhood).toHaveBeenLastCalledWith("E1", 2, false);
  });

  it("shows the user's own relationships first", async () => {
    const entityRelationships = vi.fn().mockResolvedValue([rel("R9", { reading: "çocukluk arkadaşı", other: subject("E1", "Ahmet") })]);
    const { wrapper } = await openAhmet({ entityRelationships });
    await wrapper.get('[data-testid="memory-me-toggle"]').trigger("click");
    await flushPromises();
    expect(entityRelationships).toHaveBeenCalledWith("user");
  });
});

describe("relationship decisions", () => {
  it("marks relationship questions and confirms merges", async () => {
    const items: MemoryInboxItem[] = [
      { id: "I1", type: "conflict", summary: "Mehmet: Ahmet'in kuzeni", created_at: "2026-10-20T08:00:00Z",
        predicate_label: "İlişki", value: null, subject: null, options: [], existing: ["Mehmet: Ahmet'in kardeşi"],
        category: null, about: "relationship", relationship: "Mehmet: Ahmet'in kuzeni" },
      { id: "I2", type: "destructive", summary: "Ahmet (çocukluk arkadaşı) ile Ahmet (iş ortağı) tek kişi olarak birleştirilsin mi?",
        created_at: "2026-10-20T08:00:00Z", predicate_label: null, value: null, subject: null, options: [], existing: [],
        category: null, about: "merge", relationship: null },
    ];
    const resolveInbox = vi.fn().mockResolvedValue({ created: 0, updated: 0, superseded: 0, inbox: 0, entities_created: 0, dropped: {} });
    const pinia = createPinia();
    setActivePinia(pinia);
    const client = fakeClient({ memoryInbox: vi.fn().mockResolvedValue(items), resolveInbox });
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
    const wrapper = mount(MemoryView, { global: { plugins: [pinia, createAppI18n()] } });
    await flushPromises();
    await wrapper.get('[data-testid="memory-tab-inbox"]').trigger("click");
    await flushPromises();
    const rows = wrapper.findAll('[data-testid="inbox-item"]').map((r) => r.text());
    expect(rows[0]).toContain("İlişki");
    expect(rows[0]).toContain("Şu anki: Mehmet: Ahmet'in kardeşi");
    expect(rows[1]).toContain("Birleştirme onayı");
    await wrapper.get('[data-testid="inbox-merge"]').trigger("click");
    await flushPromises();
    expect(resolveInbox).toHaveBeenCalledWith("I2", "approve");
  });
});
