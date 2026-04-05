/* ========================================
   Toast Notification System
   ======================================== */
(function () {
  "use strict";

  const ICONS = {
    success: "✅",
    error: "❌",
    info: "ℹ️",
    warning: "⚠️",
  };

  const DURATIONS = {
    success: 3500,
    error: 6000,
    info: 4000,
    warning: 5000,
  };

  let container = null;

  function ensureContainer() {
    if (container && document.body.contains(container)) return container;
    container = document.createElement("div");
    container.className = "toast-container";
    container.setAttribute("aria-live", "polite");
    document.body.appendChild(container);
    return container;
  }

  function show(message, type = "info") {
    const wrap = ensureContainer();
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <span class="toast-icon">${ICONS[type] || ICONS.info}</span>
      <span class="toast-body">${escapeHtml(String(message))}</span>
      <button class="toast-close" aria-label="Đóng">×</button>
    `;

    const closeBtn = toast.querySelector(".toast-close");
    closeBtn.addEventListener("click", () => dismiss(toast));

    wrap.appendChild(toast);

    // Cap max visible toasts
    const toasts = wrap.querySelectorAll(".toast:not(.removing)");
    if (toasts.length > 5) {
      dismiss(toasts[0]);
    }

    const duration = DURATIONS[type] || 4000;
    const timer = setTimeout(() => dismiss(toast), duration);
    toast._timer = timer;

    return toast;
  }

  function dismiss(toast) {
    if (!toast || toast.classList.contains("removing")) return;
    clearTimeout(toast._timer);
    toast.classList.add("removing");
    toast.addEventListener("animationend", () => {
      toast.remove();
    }, { once: true });
    // Fallback in case animationend doesn't fire
    setTimeout(() => toast.remove(), 300);
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  window.Toast = {
    success: (msg) => show(msg, "success"),
    error: (msg) => show(msg, "error"),
    info: (msg) => show(msg, "info"),
    warning: (msg) => show(msg, "warning"),
    show,
    dismiss,
  };
})();
