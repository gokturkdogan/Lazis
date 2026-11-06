<script setup lang="ts">
/**
 * The approval step of a web search (Phase 12). The backend says exactly what would be sent
 * (restricted data blocks it; stored people's names are pointed out); the user may edit it,
 * and only "Onayla ve araştır" sends the message with that search. Nothing is sent before.
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { ResearchPlan } from "@/api/client";
import { useAssistantStore } from "@/stores/assistant";

const props = defineProps<{ message: string; plan: ResearchPlan }>();
const emit = defineEmits<{ done: [sent: boolean] }>();

const { t } = useI18n();
const store = useAssistantStore();
const query = ref(props.plan.query);
const sending = ref(false);
watch(
  () => props.plan,
  (plan) => (query.value = plan.query),
);

const canApprove = computed(
  () => !props.plan.blocked && query.value.trim() !== "" && query.value.length <= 200 && store.canSend,
);

async function approve() {
  if (!canApprove.value) return;
  sending.value = true;
  try {
    emit("done", await store.send(props.message, { researchQuery: query.value.trim() }));
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <div class="panel prompt" data-testid="research-prompt" role="dialog" :aria-label="t('research.confirmTitle')">
    <label for="research-query">{{ t("research.confirmTitle") }}</label>
    <input id="research-query" v-model="query" maxlength="200" data-testid="research-query" :disabled="plan.blocked" />
    <p class="muted small" data-testid="research-not-general">{{ t("research.notGeneral") }}</p>
    <p v-if="plan.blocked" class="error small" role="alert" data-testid="research-blocked">{{ t("research.blocked") }}</p>
    <p v-else-if="plan.people.length" class="warn small" data-testid="research-people">
      {{ t("research.people", { names: plan.people.join(", ") }) }}
    </p>
    <div class="actions">
      <button class="btn btn-primary" type="button" data-testid="research-approve" :disabled="!canApprove || sending" @click="approve">
        {{ t("research.approve") }}
      </button>
      <button class="btn" type="button" data-testid="research-cancel" :disabled="sending" @click="emit('done', false)">
        {{ t("research.cancel") }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.prompt {
  padding: 12px 14px;
  margin-bottom: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
input {
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--panel-border-strong);
  background: rgba(6, 10, 19, 0.9);
  color: var(--text);
  font: inherit;
  user-select: text;
}
.actions {
  display: flex;
  gap: 8px;
}
.small {
  font-size: 12px;
  margin: 0;
}
.error {
  color: var(--danger);
}
.warn {
  color: var(--warning, #e0b050);
}
</style>
