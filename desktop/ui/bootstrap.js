// Lumina UI bootstrap — must be an external file to satisfy CSP (script-src 'self').
// Inline <script> blocks are blocked by the Content-Security-Policy header set in
// desktop/main.js, so all initialisation calls live here and are loaded via <script src>.
window.LuminaI18n?.applyDocument();
window.ConversationMapModule?.init();
