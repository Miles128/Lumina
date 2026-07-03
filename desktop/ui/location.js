(function () {
  "use strict";

  /** Location is disabled until MCP / scheduled-task based geo is available. */
  const STORAGE_KEY = "lumina.location.v1";

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return { enabled: false, city: "", lat: null, lng: null, updatedAt: 0 };
      }
      const parsed = JSON.parse(raw);
      return {
        enabled: false,
        city: typeof parsed?.city === "string" ? parsed.city : "",
        lat: typeof parsed?.lat === "number" ? parsed.lat : null,
        lng: typeof parsed?.lng === "number" ? parsed.lng : null,
        updatedAt: typeof parsed?.updatedAt === "number" ? parsed.updatedAt : 0,
      };
    } catch (_error) {
      return { enabled: false, city: "", lat: null, lng: null, updatedAt: 0 };
    }
  }

  function saveState(partial) {
    const next = { ...loadState(), ...partial, enabled: false };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent("lumina:location", { detail: next }));
    return next;
  }

  function isEnabled() {
    return false;
  }

  function setEnabled(_enabled) {
    return saveState({ enabled: false });
  }

  function isWebSearchQuery(_text) {
    return false;
  }

  function hasExplicitCity(_text) {
    return false;
  }

  function getCachedCity(_allowStale) {
    return "";
  }

  async function ensurePosition() {
    return { city: "", lat: null, lng: null };
  }

  async function payloadForWebSearch(_text) {
    return {};
  }

  window.LuminaLocation = {
    loadState,
    saveState,
    isEnabled,
    setEnabled,
    isWebSearchQuery,
    hasExplicitCity,
    getCachedCity,
    ensurePosition,
    payloadForWebSearch,
  };
})();
