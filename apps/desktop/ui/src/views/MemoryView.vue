<script setup lang="ts">
/**
 * Personal memory (Phase 6): what LAZIS knows, where it came from, and the user's control over
 * it — search, edit, forget, people and projects, decisions waiting for the user, import.
 * Everything goes through the backend's memory API (same checks as learning from chat).
 */
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import MemoryEntities from "@/components/memory/MemoryEntities.vue";
import MemoryImport from "@/components/memory/MemoryImport.vue";
import MemoryInbox from "@/components/memory/MemoryInbox.vue";
import MemoryRecords from "@/components/memory/MemoryRecords.vue";
import { currentApiClient } from "@/stores/connection";

type Section = "records" | "entities" | "inbox" | "import";
const sections: Section[] = ["records", "entities", "inbox", "import"];
const section = ref<Section>("records");
const pending = ref(0);
const { t } = useI18n();

async function refreshPending() {
  const client = currentApiClient();
  if (client === null) return;
  try {
    pending.value = (await client.memoryOverview()).inbox_open;
  } catch {
    pending.value = 0;
  }
}

onMounted(refreshPending);
</script>

<template>
  <div class="memory" data-testid="memory-view">
    <header class="head">
      <p class="muted small">{{ t("memory.intro") }}</p>
      <p class="muted small">{{ t("memory.separateLayers") }}</p>
      <nav class="sections">
        <button
          v-for="item in sections"
          :key="item"
          type="button"
          class="section-tab"
          :class="{ active: section === item }"
          :data-testid="`memory-tab-${item}`"
          @click="section = item"
        >
          {{ t(`memory.tabs.${item}`) }}
          <span v-if="item === 'inbox' && pending > 0" class="count" data-testid="memory-pending">{{ pending }}</span>
        </button>
      </nav>
    </header>
    <MemoryRecords v-if="section === 'records'" @changed="refreshPending" />
    <MemoryEntities v-else-if="section === 'entities'" @changed="refreshPending" />
    <MemoryInbox v-else-if="section === 'inbox'" @changed="refreshPending" />
    <MemoryImport v-else @changed="refreshPending" />
  </div>
</template>

<style scoped>
.memory {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 920px;
}
.head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.small {
  font-size: 12px;
  margin: 0;
}
.sections {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.section-tab {
  border: 1px solid var(--panel-border);
  background: transparent;
  padding: 6px 12px;
  border-radius: 9px;
  color: var(--text-muted);
}
.section-tab.active {
  border-color: var(--panel-border-strong);
  background: rgba(58, 160, 255, 0.14);
  color: var(--text);
}
.count {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 8px;
  background: rgba(255, 200, 58, 0.2);
  color: var(--warn);
  font-size: 11px;
}
</style>
