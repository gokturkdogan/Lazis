/**
 * Opening and closing the document the conversation is about (Phase 11; composer controls since
 * Phase 14.1). Unchanged behaviour: the app reads the chosen TXT/PDF/DOCX (at most 10 MB) and
 * sends its bytes; the backend keeps it in memory for this session only; one at a time.
 */
import { defineStore } from "pinia";
import { ApiError } from "@/api/client";
import { useAssistantStore } from "@/stores/assistant";
import { currentApiClient } from "@/stores/connection";

export const MAX_DOCUMENT_BYTES = 10_000_000;
export const DOCUMENT_ACCEPT = ".txt,.pdf,.docx";

function base64Of(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

export const useDocumentUi = defineStore("documentUi", {
  state: () => ({
    busy: false,
    /** An error code (translated by the view), or null. */
    error: null as string | null,
  }),

  actions: {
    async guarded(action: () => Promise<void>) {
      if (currentApiClient() === null) {
        this.error = "backend_unreachable";
        return;
      }
      this.busy = true;
      this.error = null;
      try {
        await action();
      } catch (e) {
        this.error = e instanceof ApiError ? e.code : "internal_error";
      } finally {
        this.busy = false;
      }
    },

    async open(file: File) {
      if (file.size > MAX_DOCUMENT_BYTES) {
        this.error = "document_too_large";
        return;
      }
      const store = useAssistantStore();
      await this.guarded(async () => {
        const bytes = new Uint8Array(await file.arrayBuffer());
        const opened = await currentApiClient()!.addDocument(file.name, base64Of(bytes));
        const previous = store.document;
        store.setDocument(opened);
        // One document at a time: the one it replaces is closed.
        if (previous !== null) await currentApiClient()!.removeDocument(previous.id).catch(() => false);
      });
    },

    async close() {
      const store = useAssistantStore();
      const open = store.document;
      if (open === null) return;
      await this.guarded(async () => {
        store.setDocument(null);
        await currentApiClient()!
          .removeDocument(open.id)
          .catch((e: unknown) => {
            // Already gone on the backend: closed is closed.
            if (!(e instanceof ApiError && e.code === "document_not_found")) throw e;
          });
      });
    },
  },
});
