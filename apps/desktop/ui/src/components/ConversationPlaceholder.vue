<script setup lang="ts">
import { useI18n } from "vue-i18n";

const { t } = useI18n();
</script>

<template>
  <section class="conversation panel" data-testid="conversation-placeholder" aria-disabled="true">
    <header>
      <h2>{{ t("conversation.title") }}</h2>
      <span class="badge">{{ t("conversation.inactive") }}</span>
    </header>
    <p class="muted">{{ t("conversation.body") }}</p>
    <div class="composer">
      <input type="text" :placeholder="t('conversation.placeholder')" disabled />
    </div>
  </section>
</template>

<style scoped>
.conversation {
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
header {
  display: flex;
  align-items: center;
  gap: 12px;
}
h2 {
  margin: 0;
  font-size: 16px;
}
.badge {
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--panel-border);
  color: var(--text-muted);
}
p {
  margin: 0;
  max-width: 70ch;
}
.composer input {
  width: 100%;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px dashed var(--panel-border);
  background: rgba(6, 10, 19, 0.6);
  color: var(--text-faint);
}
</style>
