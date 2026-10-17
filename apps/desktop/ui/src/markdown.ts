/**
 * Safe Markdown for assistant replies (Phase 4).
 *
 * The model's output is untrusted text. markdown-it runs with `html: false`, so any HTML in a
 * reply (tags, <script>, event handlers) is escaped and shown as text. On top of that:
 * - images are disabled (nothing is ever loaded from the network);
 * - links are kept only for http(s) URLs and never navigate the webview: a click is
 *   intercepted, the user confirms, and the shell opens the validated URL in the browser
 *   (`open_external_url`); the window's navigation guard blocks anything else;
 * - no autolinking or typographic replacement (the text stays what the model wrote);
 * - code blocks get a language label and a copy button; no syntax highlighting (not worth a
 *   highlighter dependency in Phase 4).
 * The production CSP (no inline scripts) is the second layer of defence.
 */
import MarkdownIt from "markdown-it";
import { tr } from "@/i18n/tr";

const md = new MarkdownIt({ html: false, linkify: false, typographer: false, breaks: true });
md.disable(["image"]);

/** Only absolute http(s) links stay links; everything else is rendered as plain text. */
md.validateLink = (url: string) => /^https?:\/\/[^\s]+$/i.test(url.trim());

const escape = md.utils.escapeHtml;

/** A conservative label from the fence's info string ("ts {title=x}" → "ts"). */
export function codeLanguage(info: string): string {
  const word = info.trim().split(/\s+/)[0] ?? "";
  return /^[A-Za-z0-9_+#.-]{1,24}$/.test(word) ? word.toLowerCase() : "";
}

md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx];
  if (!token) return "";
  const lang = codeLanguage(token.info);
  const label = lang ? `<span class="code-lang">${escape(lang)}</span>` : "<span></span>";
  return (
    `<div class="code-block">` +
    `<div class="code-head">${label}` +
    `<button type="button" class="code-copy" data-copy-code>${escape(tr.conversation.copy)}</button></div>` +
    `<pre><code>${escape(token.content)}</code></pre></div>`
  );
};
md.renderer.rules.code_block = md.renderer.rules.fence;

md.renderer.rules.table_open = () => `<div class="table-wrap"><table>`;
md.renderer.rules.table_close = () => `</table></div>`;

md.renderer.rules.link_open = (tokens, idx, options, _env, self) => {
  const token = tokens[idx];
  if (token) {
    token.attrSet("rel", "noopener noreferrer");
    token.attrSet("data-external", "");
    token.attrSet("title", token.attrGet("href") ?? "");
  }
  return self.renderToken(tokens, idx, options);
};

/** Rendered HTML for a reply. Safe to bind with v-html (see the module comment). */
export function renderMarkdown(source: string): string {
  return md.render(source);
}
