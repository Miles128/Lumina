(function () {
  "use strict";

  let md = null;

  function initEngine() {
    if (md) {
      return md;
    }
    if (typeof window.markdownit !== "function") {
      throw new Error("markdown-it is not loaded");
    }
    if (typeof window.DOMPurify === "undefined") {
      throw new Error("DOMPurify is not loaded");
    }
    md = window.markdownit({
      html: false,
      linkify: true,
      breaks: true,
      typographer: false,
    });
    const defaultLinkOpen =
      md.renderer.rules.link_open ||
      ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options));
    md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
      tokens[idx].attrSet("target", "_blank");
      tokens[idx].attrSet("rel", "noopener noreferrer");
      return defaultLinkOpen(tokens, idx, options, env, self);
    };
    // fence: 提取语言到 pre[data-lang]，跳过 text/空，不改代码内容
    md.renderer.rules.fence = (tokens, idx) => {
      const token = tokens[idx];
      const lang = (token.info || "").trim().split(/\s+/)[0];
      const code = md.utils.escapeHtml(token.content);
      const langAttr =
        lang && lang !== "text" ? ` data-lang="${md.utils.escapeHtml(lang)}"` : "";
      return `<pre${langAttr}><code>${code}</code></pre>`;
    };
    return md;
  }

  function render(text) {
    const source = String(text || "");
    if (!source.trim()) {
      return "";
    }
    try {
      const engine = initEngine();
      const raw = engine.render(source);
      const clean = window.DOMPurify.sanitize(raw, {
        ADD_ATTR: ["target", "rel", "class", "data-lang"],
      });
      return clean || `<p>${LuminaUtils.escapeHtml(source)}</p>`;
    } catch (error) {
      console.warn("[Lumina] markdown render failed:", error);
      return `<p>${LuminaUtils.escapeHtml(source)}</p>`;
    }
  }

  window.LuminaMarkdown = { render };
})();
