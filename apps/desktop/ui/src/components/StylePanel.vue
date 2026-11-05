<script setup lang="ts">
/**
 * "LAZIS'in seninle konuşma tarzı" (Phase 10D): each preference, where it comes from, and the
 * user's own change or removal. Only the existing /style endpoints; no model call.
 */
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, type StyleDimension } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";

const { t } = useI18n();
const dimensions = ref<StyleDimension[]>([]);
const busy = ref(false);
const error = ref<string | null>(null);

const OPTIONS: Record<string, string[]> = {
  verbosity: ["3", "5", "7"],
  elaboration: ["3", "5", "7"],
  formality: ["3", "5", "7"],
  humor: ["0", "5", "7"],
  address: ["siz", "sen"],
  honorific: ["1", "0"],
};

function options(row: StyleDimension): string[] {
  const known = OPTIONS[row.dimension] ?? [];
  return known.includes(row.value) ? known : [row.value, ...known];
}

function optionLabel(row: StyleDimension, value: string): string {
  const key = `style.option.${row.dimension}.${value}`;
  return t(key) === key ? value : t(key);
}

async function run(action: () => Promise<{ dimensions: StyleDimension[] }>) {
  busy.value = true;
  error.value = null;
  try {
    dimensions.value = (await action()).dimensions;
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    busy.value = false;
  }
}

function withClient(action: (c: NonNullable<ReturnType<typeof currentApiClient>>) => Promise<{ dimensions: StyleDimension[] }>) {
  const client = currentApiClient();
  if (client === null) {
    error.value = t(errorKey("backend_unreachable"));
    return;
  }
  void run(() => action(client));
}

function change(row: StyleDimension, event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  withClient((c) => c.setStyle(row.dimension, value));
}

onMounted(() => withClient((c) => c.style()));
</script>

<template>
  <section class="panel style" data-testid="settings-style">
    <h3>{{ t("style.title") }}</h3>
    <p class="muted small">{{ t("style.hint") }}</p>
    <div v-for="row in dimensions" :key="row.dimension" class="row" :data-testid="`style-${row.dimension}`">
      <div class="what">
        <strong>{{ t(`style.dimension.${row.dimension}`) }}</strong>
        <small class="muted">{{ row.description }} · {{ t(`style.source.${row.source}`) }}</small>
      </div>
      <select :value="row.value" :disabled="busy" @change="change(row, $event)">
        <option v-for="value in options(row)" :key="value" :value="value">{{ optionLabel(row, value) }}</option>
      </select>
      <button
        class="btn"
        type="button"
        :disabled="busy || row.source === 'default'"
        @click="withClient((c) => c.clearStyle(row.dimension))"
      >
        {{ t("style.remove") }}
      </button>
    </div>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.style {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
h3 {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.what {
  flex: 1;
  display: flex;
  flex-direction: column;
}
small {
  font-size: 12px;
}
.small {
  font-size: 12px;
  margin: 0;
}
.error {
  color: var(--danger);
}
</style>
