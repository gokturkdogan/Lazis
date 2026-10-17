<script setup lang="ts">
/** An assistant reply as safe Markdown (see markdown.ts). Links ask for confirmation and open
 *  in the browser via the shell; code blocks copy their content. */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { renderMarkdown } from "@/markdown";
import { copyText } from "@/platform/clipboard";
import { currentPlatform } from "@/stores/connection";

const props = defineProps<{ source: string }>();
const { t } = useI18n();
const html = computed(() => renderMarkdown(props.source));
const pendingLink = ref<string | null>(null);
const linkError = ref(false);

async function onClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  const copy = target?.closest<HTMLButtonElement>("[data-copy-code]");
  if (copy) {
    const code = copy.closest(".code-block")?.querySelector("code")?.textContent ?? "";
    const ok = await copyText(code);
    copy.textContent = ok ? t("conversation.copied") : t("conversation.copyFailed");
    setTimeout(() => (copy.textContent = t("conversation.copy")), 1500);
    return;
  }
  const link = target?.closest<HTMLAnchorElement>("a[href]");
  if (link) {
    event.preventDefault(); // never navigate the app window
    linkError.value = false;
    pendingLink.value = link.getAttribute("href");
  }
}

async function openLink() {
  const url = pendingLink.value;
  if (url === null) return;
  try {
    await currentPlatform()?.openExternalUrl(url);
    pendingLink.value = null;
  } catch {
    linkError.value = true;
  }
}
</script>

<template>
  <div class="markdown">
    <!-- eslint-disable-next-line vue/no-v-html -- markdown-it with html:false, see markdown.ts -->
    <div class="md" data-testid="markdown" @click="onClick" v-html="html" />
    <div v-if="pendingLink" class="link-confirm" role="dialog" data-testid="link-confirm">
      <p>{{ t("conversation.linkConfirm") }}</p>
      <p class="mono url">{{ pendingLink }}</p>
      <p v-if="linkError" class="error small">{{ t("conversation.linkFailed") }}</p>
      <div class="actions">
        <button class="btn" type="button" data-testid="link-cancel" @click="pendingLink = null">
          {{ t("conversation.linkCancel") }}
        </button>
        <button class="btn btn-primary" type="button" data-testid="link-open" @click="openLink">
          {{ t("conversation.linkOpen") }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.md {
  margin-top: 4px;
  line-height: 1.55;
  overflow-wrap: anywhere;
  user-select: text;
}
.md :deep(p) {
  margin: 0 0 8px;
}
.md :deep(> :last-child) {
  margin-bottom: 0;
}
.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4) {
  margin: 12px 0 6px;
  line-height: 1.3;
}
.md :deep(h1) {
  font-size: 18px;
}
.md :deep(h2) {
  font-size: 16px;
}
.md :deep(h3),
.md :deep(h4) {
  font-size: 14px;
}
.md :deep(ul),
.md :deep(ol) {
  margin: 0 0 8px;
  padding-left: 22px;
}
.md :deep(li) {
  margin: 2px 0;
}
.md :deep(blockquote) {
  margin: 0 0 8px;
  padding: 2px 12px;
  border-left: 3px solid var(--panel-border-strong);
  color: var(--text-muted);
}
.md :deep(a) {
  color: var(--state-idle);
  text-decoration: underline;
  cursor: pointer;
}
.md :deep(code) {
  font-family: var(--font-mono, ui-monospace, Menlo, monospace);
  font-size: 12.5px;
  background: rgba(255, 255, 255, 0.07);
  border-radius: 4px;
  padding: 1px 4px;
}
.md :deep(.code-block) {
  margin: 0 0 8px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.35);
}
.md :deep(.code-head) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 6px 3px 10px;
  font-size: 11px;
  color: var(--text-muted);
  border-bottom: 1px solid var(--panel-border);
}
.md :deep(.code-copy) {
  font: inherit;
  color: inherit;
  background: transparent;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  padding: 2px 8px;
  cursor: pointer;
}
.md :deep(pre) {
  margin: 0;
  padding: 10px;
  overflow-x: auto;
}
.md :deep(pre code) {
  background: none;
  padding: 0;
  white-space: pre;
  overflow-wrap: normal;
}
.md :deep(.table-wrap) {
  overflow-x: auto;
  margin: 0 0 8px;
}
.md :deep(table) {
  border-collapse: collapse;
  font-size: 13px;
}
.md :deep(th),
.md :deep(td) {
  border: 1px solid var(--panel-border);
  padding: 4px 8px;
  text-align: left;
}
.md :deep(hr) {
  border: 0;
  border-top: 1px solid var(--panel-border);
}
.link-confirm {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid var(--panel-border-strong);
  border-radius: 10px;
  background: var(--bg-elevated);
}
.link-confirm p {
  margin: 0 0 6px;
  font-size: 13px;
}
.url {
  overflow-wrap: anywhere;
  font-size: 12px;
}
.actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.error {
  color: var(--danger);
}
.small {
  font-size: 12px;
}
</style>
