// Lumina UI bootstrap — must be an external file to satisfy CSP (script-src 'self').
// Inline <script> blocks are blocked by the Content-Security-Policy header set in
// desktop/main.js, so all initialisation calls live here and are loaded via <script src>.
(function () {
  "use strict";

  // Scrollbars hidden by default; appear when the pointer is near a scrollable
  // container. Chromium does NOT reliably support :hover on ::-webkit-scrollbar
  // pseudo-elements, so we toggle a class (class+pseudo-element IS supported).
  const STYLE = document.createElement("style");
  STYLE.textContent = [
    ".scrollbar-visible::-webkit-scrollbar-thumb {",
    "  background: var(--border, #2a323b);",
    "}",
    ".scrollbar-visible::-webkit-scrollbar-thumb:hover {",
    "  background: var(--text-tertiary, #55606c);",
    "}",
  ].join("\n");
  document.head.appendChild(STYLE);

  let current = null;
  let hideTimer = null;
  const HIDE_DELAY = 1500;

  function findScrollable(el) {
    let node = el instanceof Element ? el : null;
    while (node && node !== document.body) {
      const style = getComputedStyle(node);
      if (
        /(auto|scroll)/.test(style.overflowY) &&
        node.scrollHeight > node.clientHeight + 4
      ) {
        return node;
      }
      node = node.parentElement;
    }
    return null;
  }

  function show(el) {
    if (current === el) return;
    if (current) current.classList.remove("scrollbar-visible");
    current = el;
    if (current) current.classList.add("scrollbar-visible");
  }

  function hide() {
    if (current) current.classList.remove("scrollbar-visible");
    current = null;
  }

  document.addEventListener(
    "mousemove",
    (event) => {
      const target = findScrollable(event.target);
      show(target);
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hide, HIDE_DELAY);
    },
    { passive: true },
  );
  document.addEventListener("mouseleave", () => {
    clearTimeout(hideTimer);
    hide();
  });
})();

window.LuminaI18n?.applyDocument();
window.ConversationMapModule?.init();
