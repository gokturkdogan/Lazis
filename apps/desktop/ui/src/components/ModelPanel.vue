<script setup lang="ts">
/**
 * Ayarlar → Yapay Zekâ Modeli (Phase 14 polish; the chooser used to sit on the chat screen).
 * Lists the models already on this computer (Ollama's list); the active one is marked. Switching
 * is an explicit "Bu modeli kullan" and does exactly what the old chooser did: select the model
 * for this session and warm it. Nothing is downloaded and no Ollama setting changes; the
 * configured default (config) stays as it is.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import Icon from "@/components/Icon.vue";
import { formatBytes } from "@/format";
import { useAssistantStore } from "@/stores/assistant";

const store = useAssistantStore();
const { t } = useI18n();
const changed = ref<string | null>(null);

const rows = computed(() =>
  store.models.map((m) => {
    const loaded = store.loaded.find((l) => l.name === m.name);
    return {
      name: m.name,
      details: t("settings.ai.details", { params: m.parameter_size, quant: m.quantization, size: formatBytes(m.size_bytes) }),
      active: m.name === store.selectedModel,
      primary: m.name === store.primaryModel,
      inMemory: loaded ? t("settings.ai.inMemory", { size: formatBytes(loaded.size_bytes) }) : null,
    };
  }),
);

function use(name: string) {
  if (store.busy || name === store.selectedModel) return;
  store.selectedModel = name;
  changed.value = name;
  void store.prepare(true);
}
</script>

<template>
  <section class="panel ai" data-testid="settings-ai-model" aria-labelledby="ai-model-title">
    <header>
      <span class="glyph" aria-hidden="true"><Icon name="sparkles" :size="18" /></span>
      <div>
        <h3 id="ai-model-title">{{ t("settings.ai.title") }}</h3>
        <p class="muted intro">{{ t("settings.ai.intro") }}</p>
      </div>
    </header>

    <p v-if="store.runtimeDown" class="state danger" role="alert" data-testid="ai-runtime-down">{{ t("settings.ai.runtimeDown") }}</p>
    <p v-else-if="store.noModels" class="state" data-testid="ai-no-models">{{ t("settings.ai.none") }}</p>

    <ul v-else class="models" role="list">
      <li v-for="m in rows" :key="m.name" class="model" :class="{ active: m.active }" :data-testid="`ai-model-${m.name}`">
        <span class="dot" aria-hidden="true" />
        <span class="body">
          <span class="name mono">{{ m.name }}</span>
          <span class="meta">
            <span>{{ m.details }}</span>
            <span v-if="m.inMemory" class="tag">{{ m.inMemory }}</span>
            <span v-if="m.primary" class="tag">{{ t("settings.ai.primary") }}</span>
          </span>
        </span>
        <span v-if="m.active" class="badge" data-testid="ai-active">{{ t("settings.ai.active") }}</span>
        <button
          v-else
          class="btn"
          type="button"
          :disabled="store.busy"
          :data-testid="`ai-use-${m.name}`"
          @click="use(m.name)"
        >
          {{ t("settings.ai.use") }}
        </button>
      </li>
    </ul>
    <p v-if="store.busy" class="muted small" role="status">{{ t("settings.ai.busy") }}</p>
    <p v-else-if="changed && changed === store.selectedModel" class="muted small" role="status" data-testid="ai-changed">
      {{ t("settings.ai.changed", { model: changed }) }}
    </p>
  </section>
</template>

<style scoped>
.ai {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.glyph {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border-radius: 10px;
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  box-shadow: 0 0 14px color-mix(in srgb, var(--accent) 18%, transparent);
}
h3 {
  margin: 2px 0 4px;
}
.intro {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}
.models {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.model {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgb(255 255 255 / 0.06);
  background: rgb(4 10 22 / 0.45);
  transition: border-color 200ms ease, box-shadow 200ms ease, background 200ms ease;
}
.model:hover {
  border-color: color-mix(in srgb, var(--accent) 25%, transparent);
}
.model.active {
  border-color: color-mix(in srgb, var(--accent) 50%, transparent);
  background: color-mix(in srgb, var(--accent) 7%, rgb(4 10 22 / 0.6));
  box-shadow: 0 0 18px color-mix(in srgb, var(--accent) 14%, transparent);
}
.dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: rgb(255 255 255 / 0.15);
}
.active .dot {
  background: var(--accent);
  box-shadow: 0 0 8px var(--accent);
}
.body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.name {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  font-size: 11.5px;
  color: var(--text-muted);
}
.tag {
  padding: 0 7px;
  border-radius: 999px;
  border: 1px solid rgb(255 255 255 / 0.1);
}
.badge {
  flex: none;
  font-family: var(--font-display);
  font-size: 10.5px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--accent);
}
.state {
  margin: 0;
  font-size: 13px;
}
.danger {
  color: var(--danger);
}
.small {
  margin: 0;
  font-size: 12px;
}
</style>
