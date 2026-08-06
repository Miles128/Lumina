/* LuminaConfirm — lightweight two-stage danger confirmation dialog. */
(function () {
  "use strict";

  let active = null;

  function escapeHtml(value) {
    return window.LuminaUtils?.escapeHtml
      ? window.LuminaUtils.escapeHtml(value)
      : String(value ?? "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
  }

  function close() {
    if (active) {
      active.remove();
      active = null;
    }
  }

  function openDialog({ title, message, confirmText, danger, onConfirm, onCancel }) {
    close();
    const overlay = document.createElement("div");
    overlay.className = "lumina-confirm-overlay";
    overlay.innerHTML = `
      <div class="lumina-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="lumina-confirm-title">
        <h3 id="lumina-confirm-title">${escapeHtml(title)}</h3>
        <p class="lumina-confirm-message">${escapeHtml(message)}</p>
        <div class="lumina-confirm-actions">
          <button type="button" class="lumina-confirm-btn lumina-confirm-cancel">取消</button>
          <button type="button" class="lumina-confirm-btn lumina-confirm-ok${danger ? " danger" : ""}">${escapeHtml(confirmText)}</button>
        </div>
      </div>
    `;
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) {
        close();
        onCancel();
      }
    });
    overlay.querySelector(".lumina-confirm-cancel").addEventListener("click", () => {
      close();
      onCancel();
    });
    overlay.querySelector(".lumina-confirm-ok").addEventListener("click", () => {
      close();
      onConfirm();
    });
    document.body.appendChild(overlay);
    active = overlay;
    overlay.querySelector(".lumina-confirm-ok").focus();
  }

  /**
   * Two-stage destructive confirmation. Resolves true only when the user
   * confirms both stages; resolves false on cancel/backdrop at either stage.
   */
  function confirmDanger({
    title = "确认删除",
    message = "",
    confirmText = "删除",
    secondTitle = "再次确认",
    secondMessage = "此操作不可恢复，将永久删除相关文件。是否继续？",
  } = {}) {
    return new Promise((resolve) => {
      openDialog({
        title,
        message,
        confirmText,
        onConfirm: () => {
          openDialog({
            title: secondTitle,
            message: secondMessage,
            confirmText,
            danger: true,
            onConfirm: () => resolve(true),
            onCancel: () => resolve(false),
          });
        },
        onCancel: () => resolve(false),
      });
    });
  }

  window.LuminaConfirm = { confirmDanger };
})();
