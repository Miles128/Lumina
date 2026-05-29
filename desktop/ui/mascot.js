(function () {
  "use strict";

  const mascot = document.getElementById("mascot");
  const mascotSpeech = document.getElementById("mascot-speech");
  const mascotForm = document.getElementById("mascot-form");
  const mascotInput = document.getElementById("mascot-input");

  document.getElementById("btn-minimize")?.addEventListener("click", () => window.secretary?.minimize());
  document.getElementById("btn-close")?.addEventListener("click", () => window.secretary?.close());
  document.getElementById("btn-open-workspace")?.addEventListener("click", openWorkspace);
  document.getElementById("btn-quick-sync")?.addEventListener("click", quickSync);
  mascotForm.addEventListener("submit", onAsk);

  function setState(state, speech) {
    mascot.dataset.state = state;
    if (speech) mascotSpeech.textContent = speech;
  }

  function openWorkspace() {
    window.secretary?.openWorkspace();
  }

  async function quickSync() {
    setState("thinking", "正在同步你的个人信息...");
    try {
      await window.SecretaryAPI.request("POST", "/api/sync");
      setState("happy", "同步完成，画像和知识库已更新。");
    } catch (error) {
      setState("idle", `同步失败：${error.message}`);
    }
  }

  async function onAsk(event) {
    event.preventDefault();
    const message = mascotInput.value.trim();
    if (!message) return;
    mascotInput.value = "";
    setState("thinking", "让我查一下你的本地知识...");
    try {
      const response = await window.SecretaryAPI.request("POST", "/api/chat", { message });
      setState("happy", response.reply.split("\n")[0].slice(0, 80));
    } catch (error) {
      setState("idle", `暂时无法回答：${error.message}`);
    }
  }
})();
