import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MarkdownContent from "@/components/MarkdownContent.vue";
import { createAppI18n } from "@/i18n";
import { codeLanguage, renderMarkdown } from "@/markdown";
import { useConnectionStore } from "@/stores/connection";
import { connection, fakeClient, fakePlatform } from "./fixtures";

/** Parse the rendered HTML the way the webview would, without executing anything. */
function dom(source: string): HTMLElement {
  const div = document.createElement("div");
  div.innerHTML = renderMarkdown(source);
  return div;
}

describe("Safe Markdown", () => {
  it("renders the supported formatting", () => {
    const el = dom(
      [
        "# Başlık",
        "**kalın** ve *eğik* ve `satır içi`",
        "- bir",
        "- iki",
        "1. ilk",
        "> alıntı",
        "| a | b |\n|---|---|\n| 1 | 2 |",
        "[site](https://example.com/yol)",
      ].join("\n\n"),
    );
    expect(el.querySelector("h1")?.textContent).toBe("Başlık");
    expect(el.querySelector("strong")?.textContent).toBe("kalın");
    expect(el.querySelector("em")?.textContent).toBe("eğik");
    expect(el.querySelector("p code")?.textContent).toBe("satır içi");
    expect(el.querySelectorAll("ul li")).toHaveLength(2);
    expect(el.querySelector("ol li")?.textContent).toBe("ilk");
    expect(el.querySelector("blockquote")?.textContent?.trim()).toBe("alıntı");
    expect(el.querySelector(".table-wrap table td")?.textContent).toBe("1");
    const a = el.querySelector("a");
    expect(a?.getAttribute("href")).toBe("https://example.com/yol");
    expect(a?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(a?.hasAttribute("data-external")).toBe(true);
  });

  it("code blocks: escaped content, sanitized language label, copy button", () => {
    const el = dom("```ts\nconst a = '<b>' && 1 < 2;\n```\n\n```<img src=x onerror=alert(1)>\nx\n```");
    const blocks = el.querySelectorAll(".code-block");
    expect(blocks).toHaveLength(2);
    expect(blocks[0]?.querySelector(".code-lang")?.textContent).toBe("ts");
    expect(blocks[0]?.querySelector("pre code")?.textContent).toBe("const a = '<b>' && 1 < 2;\n");
    expect(blocks[0]?.querySelector("[data-copy-code]")?.textContent).toBe("Kopyala");
    expect(blocks[1]?.querySelector(".code-lang")).toBeNull(); // unsafe info string dropped
    expect(el.querySelector("img")).toBeNull();
    expect(codeLanguage("Python {title=x}")).toBe("python");
    expect(codeLanguage("a\"b")).toBe("");
  });

  it.each([
    ["<script>alert(1)</script>"],
    ['<img src="x" onerror="alert(1)">'],
    ['<a href="javascript:alert(1)">x</a>'],
    ['<iframe src="https://example.com"></iframe>'],
    ['<div onclick="alert(1)">tıkla</div>'],
    ['<style>body{display:none}</style>'],
    ['<svg><script>alert(1)</script></svg>'],
  ])("raw HTML is shown as text, never as markup: %s", (source) => {
    const el = dom(source);
    for (const tag of ["script", "img", "iframe", "div", "style", "svg"]) {
      expect(el.querySelector(tag)).toBeNull();
    }
    expect(el.querySelector("a")).toBeNull();
    expect(el.textContent).toContain(source.slice(1, 6)); // visible as text
    const attributes = [...el.querySelectorAll("*")].flatMap((n) => n.getAttributeNames());
    expect(attributes.filter((a) => a.startsWith("on") || a === "src" || a === "style")).toEqual([]);
  });

  it.each([
    "[x](javascript:alert(1))",
    "[x](JaVaScRiPt:alert(1))",
    "[x](data:text/html;base64,PHNjcmlwdD4=)",
    "[x](vbscript:msgbox)",
    "[x](file:///etc/passwd)",
    "[x](/relative/path)",
    "[x](lazis://internal)",
    "<javascript:alert(1)>",
  ])("dangerous or non-web links do not become links: %s", (source) => {
    const el = dom(source);
    expect(el.querySelector("a")).toBeNull();
  });

  it("images are never rendered or fetched", () => {
    const el = dom("![izleme pikseli](https://tracker.example/p.png)");
    expect(el.querySelector("img")).toBeNull();
    expect(el.innerHTML).not.toContain("<img");
  });

  it("does not autolink bare URLs or rewrite typography", () => {
    const el = dom('https://example.com ve "tırnak" -- (c)');
    expect(el.querySelector("a")).toBeNull();
    expect(el.textContent).toContain('"tırnak" -- (c)');
  });
});

describe("MarkdownContent", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => useConnectionStore().stop());

  async function mountContent(source: string) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const platform = fakePlatform(connection());
    await useConnectionStore().start({ platform, clientFactory: () => fakeClient() });
    const wrapper = mount(MarkdownContent, {
      props: { source },
      global: { plugins: [pinia, createAppI18n()] },
      attachTo: document.body,
    });
    return { wrapper, platform };
  }

  it("a link asks for confirmation and opens only through the shell", async () => {
    const { wrapper, platform } = await mountContent("[belge](https://example.com/a)");
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    wrapper.get("a").element.dispatchEvent(click);
    await flushPromises();
    expect(click.defaultPrevented).toBe(true); // the webview never navigates
    expect(wrapper.get('[data-testid="link-confirm"]').text()).toContain("https://example.com/a");
    expect(platform.openExternalUrl).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="link-cancel"]').trigger("click");
    expect(wrapper.find('[data-testid="link-confirm"]').exists()).toBe(false);
    expect(platform.openExternalUrl).not.toHaveBeenCalled();

    wrapper.get("a").element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    await flushPromises();
    await wrapper.get('[data-testid="link-open"]').trigger("click");
    await flushPromises();
    expect(platform.openExternalUrl).toHaveBeenCalledWith("https://example.com/a");
    wrapper.unmount();
  });

  it("copies a code block's text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { wrapper } = await mountContent("```sh\nmake check\n```");
    await wrapper.get("[data-copy-code]").trigger("click");
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith("make check\n");
    expect(wrapper.get("[data-copy-code]").text()).toBe("Kopyalandı");
    wrapper.unmount();
  });
});
