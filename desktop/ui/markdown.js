(function () {
  "use strict";

  let md = null;

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

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
        ADD_ATTR: ["target", "rel", "class"],
      });
      return clean || `<p>${escapeHtml(source)}</p>`;
    } catch (error) {
      console.warn("[Lumina] markdown render failed:", error);
      return `<p>${escapeHtml(source)}</p>`;
    }
  }

  window.LuminaMarkdown = { render, init: initEngine };
})();
