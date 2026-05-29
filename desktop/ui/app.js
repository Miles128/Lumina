const API_BASE = window.secretary ? null : "";

async function apiRequest(method, route, body) {
  if (window.secretary) {
    return window.secretary.request(method, route, body);
  }

  const options = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body) {
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`${API_BASE}${route}`, options);
  const text = await response.text();
  if (!text) {
    return null;
  }
  return JSON.parse(text);
}

const SOURCE_LABELS = {
  feishu: "飞书",
  email: "邮箱",
  weread: "微信读书",
  xiaohongshu: "小红书",
  weixin_oa: "微信公众号",
  cloud_drive: "本地网盘",
};

const mascot = document.getElementById("mascot");
const mascotSpeech = document.getElementById("mascot-speech");
const syncStatus = document.getElementById("sync-status");
const memoryCount = document.getElementById("memory-count");
const connectorList = document.getElementById("connector-list");
const profileView = document.getElementById("profile-view");
const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

document.getElementById("btn-minimize").addEventListener("click", () => {
  if (window.secretary) {
    window.secretary.minimize();
  }
});
document.getElementById("btn-close").addEventListener("click", () => {
  if (window.secretary) {
    window.secretary.close();
  }
});
document.getElementById("btn-sync-all").addEventListener("click", syncAll);
document.getElementById("btn-refresh-profile").addEventListener("click", loadProfile);
chatForm.addEventListener("submit", onChatSubmit);

boot();

async function boot() {
  await refreshHealth();
  await loadProfile();
  appendBot("我已就绪。你可以先点「全量同步」，我会从飞书、邮箱、微信读书等平台收集信息并更新画像。");
}

function setMascotState(state, speech) {
  mascot.dataset.state = state;
  if (speech) {
    mascotSpeech.textContent = speech;
  }
}

async function refreshHealth() {
  const health = await apiRequest("GET", "/api/health");
  renderConnectors(health);
  const total = health.reduce((sum, item) => sum + (item.item_count || 0), 0);
  memoryCount.textContent = `${total} 条记忆`;
}

function renderConnectors(items) {
  connectorList.innerHTML = "";
  for (const item of items) {
    const label = SOURCE_LABELS[item.source] || item.source;
    const row = document.createElement("div");
    row.className = "connector-item";
    row.innerHTML = `
      <div>
        <div class="name">${label}</div>
        <div class="meta">${item.message || "等待同步"}</div>
      </div>
      <span class="state ${item.status}">${statusLabel(item.status)}</span>
      <button class="ghost" data-source="${item.source}">同步</button>
    `;
    row.querySelector("button").addEventListener("click", () => syncOne(item.source));
    connectorList.appendChild(row);
  }
}

function statusLabel(status) {
  if (status === "ready") return "已连接";
  if (status === "error") return "异常";
  return "未配置";
}

async function syncAll() {
  setMascotState("thinking", "正在同步你的飞书、邮箱、读书和社交数据…");
  syncStatus.textContent = "同步中";
  try {
    const results = await apiRequest("POST", "/api/sync");
    const inserted = results.reduce((sum, item) => sum + item.inserted, 0);
    syncStatus.textContent = "同步完成";
    setMascotState("happy", `同步完成，本轮写入 ${inserted} 条记忆。`);
    await refreshHealth();
    await loadProfile();
  } catch (error) {
    syncStatus.textContent = "同步失败";
    setMascotState("idle", `同步遇到问题：${error.message}`);
  }
}

async function syncOne(source) {
  setMascotState("thinking", `正在同步 ${SOURCE_LABELS[source] || source}…`);
  try {
    const result = await apiRequest("POST", `/api/sync/${source}`);
    setMascotState("happy", `${SOURCE_LABELS[source] || source} 同步完成，写入 ${result.inserted} 条。`);
    await refreshHealth();
    await loadProfile();
  } catch (error) {
    setMascotState("idle", `同步失败：${error.message}`);
  }
}

async function loadProfile() {
  const profile = await apiRequest("GET", "/api/profile");
  profileView.textContent = profile.markdown;
}

async function onChatSubmit(event) {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) {
    return;
  }
  chatInput.value = "";
  appendUser(message);
  setMascotState("thinking", "让我查一下你的本地画像和记忆…");
  try {
    const response = await apiRequest("POST", "/api/chat", { message });
    appendBot(response.reply);
    setMascotState("happy", "我已经根据本地记忆回复你啦。");
  } catch (error) {
    appendBot(`抱歉，暂时无法回复：${error.message}`);
    setMascotState("idle", "我需要你先启动后端并完成一次同步。");
  }
}

function appendUser(text) {
  appendBubble("user", text);
}

function appendBot(text) {
  appendBubble("bot", text);
}

function appendBubble(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  bubble.textContent = text;
  chatLog.appendChild(bubble);
  chatLog.scrollTop = chatLog.scrollHeight;
}
