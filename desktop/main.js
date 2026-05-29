const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");
const { spawn } = require("child_process");

const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = 8765;
const BACKEND_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}`;

let mainWindow = null;
let knowledgeWindow = null;
let mascotWindow = null;
let backendProcess = null;
let isQuitting = false;
const RESTART_DELAY_MS = 3000;
const LOAD_RETRY_COUNT = 40;
const LOAD_RETRY_DELAY_MS = 500;
const LOAD_RETRY_FLAG = "__luminaLoadingWithRetry";

function projectRoot() {
  return path.resolve(__dirname, "..");
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
  });
  backendProcess.stderr.on("data", (data) => {
    console.error(`[backend:err] ${data.toString().trimEnd()}`);
  });
  backendProcess.on("exit", (code) => {
    console.log(`[backend] exited with code ${code}`);
    backendProcess = null;
    if (isQuitting) return;
    waitForBackend(2).then((stillUp) => {
      if (stillUp) return;
      console.log(`[backend] restarting in ${RESTART_DELAY_MS / 1000}s...`);
      setTimeout(startBackend, RESTART_DELAY_MS);
    });
  });
}

async function ensureBackend() {
  if (await waitForBackend(2)) return;
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
    if (parsed.pathname.startsWith("/mascot")) {
      createMascotWindow();
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
    title: "灵犀 · 知识库",
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

function createMascotWindow() {
  if (mascotWindow) {
    mascotWindow.focus();
    return;
  }
  mascotWindow = new BrowserWindow({
    width: 340,
    height: 460,
    minWidth: 300,
    minHeight: 400,
    title: "灵犀",
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  attachWindowOpenHandler(mascotWindow);
  attachLoadRetry(mascotWindow, `${BACKEND_URL}/mascot`);
  loadUrlWithBackendRetry(mascotWindow, `${BACKEND_URL}/mascot`);
  mascotWindow.on("closed", () => {
    mascotWindow = null;
  });
}

function attachLoadRetry(win, targetUrl) {
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

app.whenReady().then(async () => {
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

ipcMain.handle("window:openMascot", () => {
  createMascotWindow();
});
