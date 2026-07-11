const { app, BrowserWindow, ipcMain, session, nativeImage, dialog } = require("electron");
const fs = require("fs");
const path = require("path");
const { spawn, exec } = require("child_process");

const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = 8765;
const BACKEND_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}`;

let mainWindow = null;
let knowledgeWindow = null;
let backendProcess = null;
let isQuitting = false;
const RESTART_DELAY_MS = 3000;
const LOAD_RETRY_COUNT = 40;
const LOAD_RETRY_DELAY_MS = 500;
const LOAD_RETRY_FLAG = "__luminaLoadingWithRetry";
// Guards against unbounded restart loops when the backend port is held by a
// process we cannot kill. Reset to 0 once the backend produces stdout.
const MAX_ADDRESS_IN_USE_RETRIES = 3;
let addressInUseRetries = 0;

function projectRoot() {
  return path.resolve(__dirname, "..");
}

function killPortHolder(port) {
  return new Promise((resolve) => {
    exec(`lsof -ti :${port} 2>/dev/null`, (error, stdout) => {
      if (error || !stdout.trim()) {
        resolve();
        return;
      }
      for (const pid of stdout.trim().split("\n")) {
        const numeric = Number(pid);
        if (!Number.isFinite(numeric) || numeric === process.pid) {
          continue;
        }
        try {
          process.kill(numeric, "SIGKILL");
        } catch (_killError) {
          // ignore stale pid
        }
      }
      setTimeout(resolve, 600);
    });
  });
}

function startBackend() {
  if (backendProcess) return;
  const env = { ...process.env, PYTHONPATH: path.join(projectRoot(), "src") };
  backendProcess = spawn(
    "python3",
    ["-m", "secretary.main", "--host", BACKEND_HOST, "--port", String(BACKEND_PORT)],
    { cwd: projectRoot(), env, stdio: ["ignore", "pipe", "pipe"] },
  );
  backendProcess.stdout.on("data", (data) => {
    console.log(`[backend] ${data.toString().trimEnd()}`);
    // Backend is alive and producing output — clear the retry counter.
    addressInUseRetries = 0;
  });
  backendProcess.stderr.on("data", (data) => {
    const text = data.toString();
    console.error(`[backend:err] ${text.trimEnd()}`);
    if (text.includes("address already in use")) {
      if (addressInUseRetries >= MAX_ADDRESS_IN_USE_RETRIES) {
        console.error(
          `[backend] giving up after ${MAX_ADDRESS_IN_USE_RETRIES} failed attempts to reclaim port ${BACKEND_PORT}`,
        );
        return;
      }
      addressInUseRetries += 1;
      console.warn(
        `[backend] port in use, retry ${addressInUseRetries}/${MAX_ADDRESS_IN_USE_RETRIES}`,
      );
      killPortHolder(BACKEND_PORT).then(() => {
        backendProcess = null;
        startBackend();
      });
    }
  });
  backendProcess.on("exit", (code) => {
    console.log(`[backend] exited with code ${code}`);
    backendProcess = null;
    if (isQuitting) return;
    waitForBackend(2).then(async (stillUp) => {
      if (stillUp) return;
      console.log(`[backend] restarting in ${RESTART_DELAY_MS / 1000}s...`);
      await killPortHolder(BACKEND_PORT);
      setTimeout(startBackend, RESTART_DELAY_MS);
    });
  });
}

async function ensureBackend() {
  if (await waitForBackend(2)) return;
  await killPortHolder(BACKEND_PORT);
  startBackend();
  if (await waitForBackend(30)) return;
  await killPortHolder(BACKEND_PORT);
  backendProcess = null;
  startBackend();
  await waitForBackend(30);
}

function routeInternalUrl(url) {
  try {
    const parsed = new URL(url);
    if (!["127.0.0.1", "localhost"].includes(parsed.hostname)) return false;
    if (parsed.pathname === "/" || parsed.pathname === "") {
      createMainWindow();
      return true;
    }
    if (parsed.pathname.startsWith("/workspace")) {
      createKnowledgeWindow();
      return true;
    }
  } catch (_error) {
    // ignore malformed URLs
  }
  return false;
}

function attachWindowOpenHandler(win) {
  win.webContents.setWindowOpenHandler(({ url }) => {
    routeInternalUrl(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    if (routeInternalUrl(url)) event.preventDefault();
  });
}

function createMainWindow() {
  if (mainWindow) {
    mainWindow.focus();
    return;
  }
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    title: "灵犀",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 14, y: 16 },
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  attachWindowOpenHandler(mainWindow);
  attachLoadRetry(mainWindow, `${BACKEND_URL}/`);
  loadUrlWithBackendRetry(mainWindow, `${BACKEND_URL}/`);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function createKnowledgeWindow() {
  if (knowledgeWindow) {
    knowledgeWindow.focus();
    return;
  }
  knowledgeWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    title: "Shibei · 知识库",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  attachWindowOpenHandler(knowledgeWindow);
  attachLoadRetry(knowledgeWindow, `${BACKEND_URL}/workspace`);
  loadUrlWithBackendRetry(knowledgeWindow, `${BACKEND_URL}/workspace`);
  knowledgeWindow.on("closed", () => {
    knowledgeWindow = null;
  });
}

function attachLoadRetry(win, targetUrl) {
  // Listener lifetime is bound to win.webContents: when the window is closed
  // the webContents is destroyed and all its listeners are GC'd automatically.
  // No explicit removal is needed (and removing it on loadUrlWithBackendRetry
  // completion would break retry on a subsequent navigation failure).
  win.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedUrl, isMainFrame) => {
    if (!isMainFrame) return;
    if (errorCode === -3) return;
    if (!validatedUrl.startsWith(BACKEND_URL)) return;
    console.warn(`[window] load failed (${errorCode}): ${errorDescription}`);
    loadUrlWithBackendRetry(win, targetUrl);
  });
}

async function loadUrlWithBackendRetry(win, targetUrl) {
  if (!win || win.isDestroyed()) return;
  if (win[LOAD_RETRY_FLAG]) return;
  win[LOAD_RETRY_FLAG] = true;
  for (let attempt = 0; attempt < LOAD_RETRY_COUNT; attempt += 1) {
    if (!win || win.isDestroyed()) return;
    const healthy = await waitForBackend(1);
    if (!healthy) {
      await new Promise((resolve) => setTimeout(resolve, LOAD_RETRY_DELAY_MS));
      continue;
    }
    try {
      await win.loadURL(targetUrl);
      win[LOAD_RETRY_FLAG] = false;
      return;
    } catch (_error) {
      await new Promise((resolve) => setTimeout(resolve, LOAD_RETRY_DELAY_MS));
    }
  }
  if (win && !win.isDestroyed()) {
    win[LOAD_RETRY_FLAG] = false;
  }
}

function appIconPath() {
  return path.join(__dirname, "icons", "icon.icns");
}

function applyAppIcon() {
  const iconFile = appIconPath();
  if (!fs.existsSync(iconFile)) {
    return;
  }
  const image = nativeImage.createFromPath(iconFile);
  if (image.isEmpty()) {
    return;
  }
  if (process.platform === "darwin" && app.dock) {
    app.dock.setIcon(image);
  }
}

function isLocalOrigin(url) {
  if (!url) return false;
  return url.startsWith("http://127.0.0.1") || url.startsWith("http://localhost");
}

function setupGeolocationPermissions() {
  const ses = session.defaultSession;
  // Only grant geolocation to our own local backend origin. Any other origin
  // (e.g. a navigated third-party page) is denied.
  ses.setPermissionCheckHandler((webContents, permission) => {
    if (permission !== "geolocation") return false;
    return isLocalOrigin(webContents.getURL());
  });
  ses.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission !== "geolocation") {
      callback(false);
      return;
    }
    callback(isLocalOrigin(webContents.getURL()));
  });
}

async function waitForBackend(retries = 30) {
  for (let attempt = 0; attempt < retries; attempt += 1) {
    try {
      const response = await fetch(`${BACKEND_URL}/api/health`);
      if (response.ok) return true;
    } catch (_error) {
      // retry
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

function setupContentSecurityPolicy() {
  // Lock down the renderer to local + explicitly-allowlisted origins.
  // Google Fonts (stylesheets + font files) are allowlisted because the UI
  // loads Fraunces/Geist/Geist Mono from fonts.googleapis.com at runtime.
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [
          [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' data: https://fonts.gstatic.com",
            "img-src 'self' data:",
            "connect-src 'self'",
          ].join("; "),
        ],
      },
    });
  });
}

app.setName("灵犀");

app.whenReady().then(async () => {
  applyAppIcon();
  setupContentSecurityPolicy();
  setupGeolocationPermissions();
  await ensureBackend();
  createMainWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (!mainWindow) createMainWindow();
});

app.on("before-quit", () => {
  isQuitting = true;
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});

ipcMain.handle("backend:request", async (_event, method, route, body) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60_000);
  try {
    const options = {
      method,
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
    };
    if (body) options.body = JSON.stringify(body);
    const response = await fetch(`${BACKEND_URL}${route}`, options);
    const text = await response.text();
    if (!response.ok) {
      throw new Error(text.trim() || `请求失败 (${response.status})`);
    }
    return text ? JSON.parse(text) : null;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("请求超时，请稍后重试");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
});

ipcMain.handle("window:minimize", (event) => {
  BrowserWindow.fromWebContents(event.sender)?.minimize();
});

ipcMain.handle("window:close", (event) => {
  BrowserWindow.fromWebContents(event.sender)?.close();
});

ipcMain.handle("window:openKnowledge", () => {
  createKnowledgeWindow();
});

ipcMain.handle("window:openWorkspace", () => {
  createKnowledgeWindow();
});

ipcMain.handle("dialog:pickDirectory", async (_event, defaultPath) => {
  const result = await dialog.showOpenDialog({
    title: "选择工作区目录",
    defaultPath: typeof defaultPath === "string" && defaultPath ? defaultPath : undefined,
    properties: ["openDirectory", "createDirectory"],
  });
  if (result.canceled || !result.filePaths.length) {
    return null;
  }
  return result.filePaths[0];
});

ipcMain.handle("dialog:pickFiles", async (_event, defaultPath) => {
  const result = await dialog.showOpenDialog({
    title: "选择附件",
    defaultPath: typeof defaultPath === "string" && defaultPath ? defaultPath : undefined,
    properties: ["openFile", "multiSelections"],
    filters: [
      { name: "Documents", extensions: ["pdf", "docx", "xlsx", "xlsm", "csv", "txt", "md", "json"] },
      { name: "All Files", extensions: ["*"] },
    ],
  });
  if (result.canceled || !result.filePaths.length) {
    return [];
  }
  return result.filePaths;
});
