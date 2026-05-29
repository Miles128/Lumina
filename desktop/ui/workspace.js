(function () {
  "use strict";

  const topicTree = document.getElementById("topic-tree");
  const noteEditor = document.getElementById("note-editor");
  const notePreview = document.getElementById("note-preview");
  const editorTitle = document.getElementById("editor-title");
  const profilePanel = document.getElementById("profile-panel");
  const aiMessages = document.getElementById("ai-messages");
  const aiForm = document.getElementById("ai-form");
  const aiInput = document.getElementById("ai-input");

  let currentPath = "";

  document.querySelectorAll(".sidebar-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".sidebar-tab").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".sidebar-pane").forEach((pane) => pane.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`pane-${tab.dataset.pane}`).classList.add("active");
      if (tab.dataset.pane === "graph") {
        window.GraphModule.reload(document.querySelector("[data-graph-filter].active")?.dataset.graphFilter);
      }
    });
  });

  document.getElementById("btn-sync-all").addEventListener("click", syncAll);
  document.getElementById("btn-save-note").addEventListener("click", saveNote);
  document.getElementById("btn-rebuild-kb").addEventListener("click", rebuildKb);
  document.getElementById("btn-open-mascot").addEventListener("click", () => {
    window.secretary?.openMascot();
  });

  noteEditor.addEventListener("input", renderPreview);
  aiForm.addEventListener("submit", onChatSubmit);
  aiInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      aiForm.requestSubmit();
    }
  });

  boot();

  async function boot() {
    appendAi("bot", "你好，我是灵犀。左侧可看主题树和个人图谱，右侧可以像 NoteAI 一样对话检索本地知识库。");
    await Promise.all([loadTree(), loadProfile()]);
    window.GraphModule.init();
  }

  async function loadTree() {
    const data = await window.SecretaryAPI.request("GET", "/api/kb/tree");
    topicTree.innerHTML = "";
    for (const l1 of data.topics || []) {
      const l1El = document.createElement("div");
      l1El.className = "tree-l1";
      l1El.textContent = `${l1.name} (${l1.file_count || 0})`;
      topicTree.appendChild(l1El);
      for (const l2 of l1.children || []) {
        const l2El = document.createElement("div");
        l2El.className = "tree-l2";
        l2El.textContent = l2.name;
        topicTree.appendChild(l2El);
        for (const file of l2.files || []) {
          const fileBtn = document.createElement("button");
          fileBtn.className = "tree-file";
          fileBtn.textContent = file.name;
          fileBtn.addEventListener("click", () => openNote(file.path, file.name));
          topicTree.appendChild(fileBtn);
        }
      }
    }
  }

  async function openNote(path, title) {
    const data = await window.SecretaryAPI.request("GET", `/api/kb/note?path=${encodeURIComponent(path)}`);
    currentPath = path;
    editorTitle.textContent = title;
    noteEditor.value = data.content;
    document.getElementById("btn-save-note").disabled = false;
    renderPreview();
  }

  async function saveNote() {
    if (!currentPath) return;
    const button = document.getElementById("btn-save-note");
    button.disabled = true;
    try {
      const updated = await window.SecretaryAPI.request("PUT", "/api/kb/note", {
        path: currentPath,
        content: noteEditor.value,
      });
      noteEditor.value = updated.content;
      appendAi("bot", `已保存笔记：${currentPath}`);
      renderPreview();
    } catch (error) {
      appendAi("bot", `保存失败：${error.message}`);
    } finally {
      button.disabled = false;
    }
  }

  function renderPreview() {
    const body = noteEditor.value.replace(/^---[\s\S]*?---\n?/, "");
    notePreview.innerHTML = body
      .split("\n")
      .map((line) => {
        if (line.startsWith("# ")) return `<h1>${escapeHtml(line.slice(2))}</h1>`;
        if (line.startsWith("## ")) return `<h2>${escapeHtml(line.slice(3))}</h2>`;
        if (line.startsWith("- ")) return `<li>${escapeHtml(line.slice(2))}</li>`;
        return `<p>${escapeHtml(line)}</p>`;
      })
      .join("");
  }

  async function loadProfile() {
    const profile = await window.SecretaryAPI.request("GET", "/api/profile");
    profilePanel.textContent = profile.markdown;
  }

  async function syncAll() {
    appendAi("bot", "开始全量同步，请稍候...");
    const results = await window.SecretaryAPI.request("POST", "/api/sync");
    const inserted = results.reduce((sum, item) => sum + item.inserted, 0);
    appendAi("bot", `同步完成，写入 ${inserted} 条记忆，并已更新知识库与画像。`);
    await Promise.all([loadTree(), loadProfile()]);
    window.GraphModule.reload("personal");
  }

  async function rebuildKb() {
    const result = await window.SecretaryAPI.request("POST", "/api/kb/rebuild");
    appendAi("bot", `知识库已重建，导出 ${result.exported} 篇笔记。`);
    await loadTree();
  }

  async function onChatSubmit(event) {
    event.preventDefault();
    const message = aiInput.value.trim();
    if (!message) return;
    aiInput.value = "";
    appendAi("user", message);
    const response = await window.SecretaryAPI.request("POST", "/api/chat", { message });
    appendAi("bot", response.reply);
  }

  function appendAi(role, text) {
    const bubble = document.createElement("div");
    bubble.className = `ai-bubble ${role}`;
    bubble.textContent = text;
    aiMessages.appendChild(bubble);
    aiMessages.scrollTop = aiMessages.scrollHeight;
  }

  function escapeHtml(value) {
    return value
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }
})();
