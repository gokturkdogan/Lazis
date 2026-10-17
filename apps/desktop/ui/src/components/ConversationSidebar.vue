<script setup lang="ts">
/** Conversation list: new chat, most recently updated first, rename inline, delete with a
 *  confirmation dialog. */
import { nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { Conversation } from "@/api/client";
import { formatWhen } from "@/format";
import { useConversationsStore } from "@/stores/conversations";

const store = useConversationsStore();
const { t } = useI18n();
const editing = ref<string | null>(null);
const editTitle = ref("");
const editInput = ref<HTMLInputElement[] | null>(null);
const pendingDelete = ref<Conversation | null>(null);
const deleting = ref(false);

async function startRename(c: Conversation) {
  editing.value = c.id;
  editTitle.value = c.title;
  await nextTick();
  editInput.value?.[0]?.select();
}

async function saveRename(c: Conversation) {
  const title = editTitle.value.trim();
  if (title && title !== c.title) await store.rename(c.id, title);
  editing.value = null;
}

function onRenameKey(event: KeyboardEvent, c: Conversation) {
  if (event.key === "Enter") {
    event.preventDefault();
    void saveRename(c);
  } else if (event.key === "Escape") {
    editing.value = null;
  }
}

async function confirmDelete() {
  const target = pendingDelete.value;
  if (target === null) return;
  deleting.value = true;
  try {
    if (await store.remove(target.id)) pendingDelete.value = null;
  } finally {
    deleting.value = false;
  }
}
</script>

<template>
  <aside class="sidebar panel" data-testid="conversation-sidebar">
    <header>
      <h2>{{ t("conversation.list") }}</h2>
      <button
        class="btn btn-primary"
        type="button"
        data-testid="new-conversation"
        :disabled="store.busy"
        @click="store.newConversation()"
      >
        {{ t("conversation.newChat") }}
      </button>
    </header>

    <p v-if="store.listLoaded && store.conversations.length === 0" class="muted empty">
      {{ t("conversation.emptyList") }}
    </p>

    <ul class="items" role="list">
      <li
        v-for="c in store.conversations"
        :key="c.id"
        :class="['item', { active: c.id === store.activeId }]"
        data-testid="conversation-item"
        :aria-current="c.id === store.activeId ? 'true' : undefined"
      >
        <template v-if="editing === c.id">
          <input
            ref="editInput"
            v-model="editTitle"
            class="rename"
            maxlength="120"
            data-testid="rename-input"
            :aria-label="t('conversation.rename')"
            @keydown="onRenameKey($event, c)"
            @blur="saveRename(c)"
          />
        </template>
        <template v-else>
          <button
            class="open"
            type="button"
            :data-testid="`open-${c.id}`"
            :disabled="store.busy && c.id !== store.activeId"
            @click="c.id !== store.activeId && store.open(c.id)"
          >
            <span class="title">{{ c.title }}</span>
            <span class="when muted">{{ formatWhen(c.updated_at) }}</span>
          </button>
          <div class="actions">
            <button
              class="icon"
              type="button"
              data-testid="rename-conversation"
              :title="t('conversation.rename')"
              :aria-label="t('conversation.rename')"
              @click="startRename(c)"
            >
              ✎
            </button>
            <button
              class="icon danger"
              type="button"
              data-testid="delete-conversation"
              :title="t('conversation.delete')"
              :aria-label="t('conversation.delete')"
              :disabled="store.busy && store.turn?.conversationId === c.id"
              @click="pendingDelete = c"
            >
              ✕
            </button>
          </div>
        </template>
      </li>
    </ul>

    <button
      v-if="store.listCursor"
      class="btn more"
      type="button"
      data-testid="more-conversations"
      @click="store.loadMoreConversations()"
    >
      {{ t("conversation.loadMore") }}
    </button>

    <div v-if="pendingDelete" class="overlay" role="dialog" aria-modal="true" data-testid="delete-dialog">
      <div class="dialog panel">
        <h3>{{ t("conversation.deleteTitle") }}</h3>
        <p>{{ t("conversation.deleteBody", { title: pendingDelete.title }) }}</p>
        <p class="muted small">{{ t("conversation.deleteBackups") }}</p>
        <div class="dialog-actions">
          <button class="btn" type="button" data-testid="delete-cancel" @click="pendingDelete = null">
            {{ t("conversation.deleteCancel") }}
          </button>
          <button
            class="btn btn-danger"
            type="button"
            data-testid="delete-confirm"
            :disabled="deleting"
            @click="confirmDelete"
          >
            {{ t("conversation.deleteConfirm") }}
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  min-height: 0;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
h2 {
  margin: 0;
  font-size: 15px;
}
.empty {
  margin: 4px 2px;
  font-size: 13px;
}
.items {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
  flex: 1;
}
.item {
  display: flex;
  align-items: center;
  gap: 4px;
  border-radius: 10px;
  border: 1px solid transparent;
}
.item.active {
  border-color: var(--panel-border-strong);
  background: rgba(58, 160, 255, 0.12);
}
.open {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 8px 10px;
  border: 0;
  background: transparent;
  color: var(--text);
  text-align: left;
}
.title {
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.when {
  font-size: 11px;
}
.actions {
  display: flex;
  opacity: 0.35;
}
.item:hover .actions,
.item.active .actions,
.actions:focus-within {
  opacity: 1;
}
.icon {
  border: 0;
  background: transparent;
  color: var(--text-muted);
  padding: 4px 6px;
  border-radius: 6px;
}
.icon.danger:hover {
  color: var(--danger);
}
.rename {
  flex: 1;
  margin: 4px;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid var(--panel-border-strong);
  background: rgba(6, 10, 19, 0.9);
  color: var(--text);
  font: inherit;
  user-select: text;
}
.more {
  align-self: center;
}
.overlay {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(3, 6, 12, 0.72);
  backdrop-filter: blur(6px);
  z-index: 10;
}
.dialog {
  width: min(520px, calc(100vw - 48px));
  padding: 22px 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.dialog h3,
.dialog p {
  margin: 0;
}
.small {
  font-size: 12px;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.btn-danger {
  border-color: var(--danger);
  color: var(--danger);
}
</style>
