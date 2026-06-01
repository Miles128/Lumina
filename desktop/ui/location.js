(function () {
  "use strict";

  const STORAGE_KEY = "lumina.location.v1";
  const CACHE_MS = 60 * 60 * 1000;
  const WEATHER_RE = /天气|气温|温度|下雨|下雪|降雪|降雨|weather|forecast/i;
  const CITY_WEATHER_RE = /([\u4e00-\u9fffA-Za-z·]{2,12}?)天气/;
  const NON_CITY_PREFIXES = new Set(["今天", "明天", "后天", "本地", "当地", "现在", "这边", "这里", "最近"]);

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return { enabled: true, city: "", lat: null, lng: null, updatedAt: 0 };
      }
      const parsed = JSON.parse(raw);
      return {
        enabled: parsed?.enabled !== false,
        city: typeof parsed?.city === "string" ? parsed.city : "",
        lat: typeof parsed?.lat === "number" ? parsed.lat : null,
        lng: typeof parsed?.lng === "number" ? parsed.lng : null,
        updatedAt: typeof parsed?.updatedAt === "number" ? parsed.updatedAt : 0,
      };
    } catch (_error) {
      return { enabled: true, city: "", lat: null, lng: null, updatedAt: 0 };
    }
  }

  function saveState(partial) {
    const next = { ...loadState(), ...partial };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent("lumina:location", { detail: next }));
    return next;
  }

  function isEnabled() {
    return loadState().enabled !== false;
  }

  function setEnabled(enabled) {
    return saveState({ enabled: Boolean(enabled) });
  }

  function isWeatherQuery(text) {
    return WEATHER_RE.test(String(text || "").trim());
  }

  function hasExplicitCity(text) {
    const match = String(text || "").trim().match(CITY_WEATHER_RE);
    if (!match) {
      return false;
    }
    const city = match[1].replace(/的$/, "");
    return city && !NON_CITY_PREFIXES.has(city);
  }

  function getCachedCity() {
    const state = loadState();
    if (!state.city) {
      return "";
    }
    if (state.updatedAt && Date.now() - state.updatedAt < CACHE_MS) {
      return state.city;
    }
    return "";
  }

  function getCurrentPosition() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error("geolocation unsupported"));
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (position) => {
          resolve({
            lat: position.coords.latitude,
            lng: position.coords.longitude,
          });
        },
        (error) => reject(error),
        {
          enableHighAccuracy: false,
          timeout: 15000,
          maximumAge: 300000,
        },
      );
    });
  }

  async function reverseGeocode(lat, lng) {
    const result = await window.SecretaryAPI.request("POST", "/api/location/reverse", {
      lat,
      lng,
    });
    return typeof result?.city === "string" ? result.city : "";
  }

  async function ensureCity() {
    if (!isEnabled()) {
      return "";
    }
    const cached = getCachedCity();
    if (cached) {
      return cached;
    }
    const position = await getCurrentPosition();
    const city = await reverseGeocode(position.lat, position.lng);
    if (!city) {
      return "";
    }
    saveState({
      enabled: true,
      city,
      lat: position.lat,
      lng: position.lng,
      updatedAt: Date.now(),
    });
    return city;
  }

  async function cityForWeatherQuery(text) {
    if (!isWeatherQuery(text) || hasExplicitCity(text)) {
      return "";
    }
    return ensureCity();
  }

  window.LuminaLocation = {
    loadState,
    saveState,
    isEnabled,
    setEnabled,
    isWeatherQuery,
    hasExplicitCity,
    getCachedCity,
    ensureCity,
    cityForWeatherQuery,
  };
})();
